## Introduction

Loki 的写入路径可以概括为：**校验并路由到若干 ingester，达到 quorum 后返回；ingester 先写本地 WAL，再异步把内存中的 chunk 和索引送进对象存储。** 因此 push 成功、WAL 持久化、chunk 落盘、索引可查是四个不同阶段。

本文以 **v3.7.10**（commit `c792f58577a46c64b0a8e808d7c643ed0e8c5e83`）为基线。理解这条路径最好的方式是沿着调用链，同时记录每个阶段的失败语义。

## End-to-End Path

```text
Promtail / Alloy / OTel Collector / 任意 Loki client
        │
        │ POST /loki/api/v1/push
        ▼
HTTP auth + tenant resolver
        │  X-Scope-OrgID
        ▼
Push parser ── JSON / protobuf + Snappy / Gzip / Deflate
        ▼
Distributor
  ├─ labels、entries、structured metadata 校验
  ├─ ingestion policy 与租户/单流限流
  └─ FNV32(tenantID + normalized labels) -> consistent hash ring
        │
        ├──────────────┬──────────────┐
        ▼              ▼              ▼
     Ingester A     Ingester B     Ingester C      默认 RF=3
        │              │              │
        │              │              └─ stream/chunk + 本地 WAL
        │              └───────────────── stream/chunk + 本地 WAL
        └──────────────────────────────── stream/chunk + 本地 WAL
                        │
                        │ flush：Close -> Encode -> PutChunks -> IndexChunk
                        ▼
             对象存储中的 chunk + TSDB index
                        ▲
                        │ index head/WAL rotation + shipper upload
                        └─ 异步、批量、非原子
```

distributor 达到 quorum 即可返回，不必等待所有副本；ingester 的 flush 与 index shipper 的上传则继续在后台发生。源码入口见 `pkg/loki/modules.go:395-412`、`pkg/distributor/http.go:27-57`、`pkg/distributor/distributor.go:552-932`。

## HTTP and Tenant Boundary

`/loki/api/v1/push` 与 `/api/prom/push` 共用 `distributor.PushHandler`。默认 `auth.enabled=true`，租户 ID 来自 `X-Scope-OrgID`；关闭认证时使用固定的 `fake` tenant。生产环境中的身份验证仍应由网关或代理完成，Loki 的 fakeauth 只负责提取 header，不校验凭据。

一次 push 只能包含一个 tenant。请求解析支持 JSON v1 与 protobuf，请求体支持 Snappy、Gzip、Deflate；随后逐 stream 解析 labels。相关实现位于 `pkg/loki/loki.go:149-162`、`pkg/loghttp/push/push.go:316-428`。

HTTP 状态码表达的是请求处理结果，不是数据已经进入对象存储：

| 状态码 | 典型含义 |
| --- | --- |
| `204` | 至少一个 entry 被接受且写入 quorum 成功；全部 entry 被过滤时也可能返回 `204` |
| `400` | 请求解析、时间、标签或 entry 校验失败；部分合法 entry 仍可能已写入 |
| `413` | 请求体超过 HTTP 层限制 |
| `422` | 请求中没有 stream |
| `429` | 租户或单 stream 限流、stream 数量超限 |
| `500` | ring、RPC 等未单独映射的错误 |

证据见 `pkg/distributor/http.go:58-181`、`pkg/distributor/distributor.go:780-932`。

## Distributor

### Validation and Policy

`PushWithResolver` 依次处理空 stream、行截断、labels 解析、enforced labels、ingestion policy、entry 时间与大小、structured metadata，最后进入限流。标签使用规范化后的 `labels.String()` 参与后续处理，所以 ring token 不是客户端原始字符串。

默认限制包括：

- 单行 `256KB`，超长行默认丢弃；只有开启 `max_line_size_truncate` 才截断。
- 单条日志 structured metadata 最大 `64KB`、最多 `128` 项。
- label name 最大 `1024` 字节、value 最大 `2048` 字节、每条 series 最多 `15` 个 label name。
- 全局 ingestion rate 默认 `4MB/s`、burst `6MB`；单 stream 默认 `3MB/s`、burst `15MB`。
- 每租户全局 active stream 默认上限 `5000`；单 ingester local stream 上限默认 `0`，即不限制。

这些值来自 `pkg/validation/limits.go:314-380,491-494`。全局 ingestion limiter 会根据 distributor ring 的健康实例数分摊额度，和 ingester 的数据 ring 不是同一个 ring。

### Ring Placement

每条 stream 的 ring key 为：

```text
FNV32(tenantID + normalized labels)
```

实现位于 `pkg/util/ring/ring.go:11-17`。distributor 使用 `ring.WriteNoExtend` 获取副本，只选择 `ACTIVE` 实例；节点处于 `JOINING` 或 `LEAVING` 时不会自动扩展副本集。证据见 `pkg/distributor/distributor.go:879-894`。

### Write Quorum

默认 `replication_factor=3`。dskit 的复制策略**先**根据原始副本数计算 quorum，**再**过滤不健康实例：

```text
N        = 原始副本数
minOK    = floor(N / 2) + 1
healthy  = 过滤后的实例集合
maxError = len(healthy) - minOK
```

因此 unhealthy 实例不会降低 quorum 分母。`vendor/github.com/grafana/dskit/ring/replication_strategy.go:33-75` 明确写了这一点；distributor 在 `pkg/distributor/distributor.go:885-888` 用 `len(replicationSet.Instances) - MaxErrors` 得到实际 `minSuccess`。

| 初始副本 | 健康副本 | 需要成功 | 结果 |
| --- | --- | --- | --- |
| 3 | 3 | 2 | 允许 1 个 RPC 失败 |
| 3 | 2 | 2 | 不允许再失败 |
| 3 | 1 | 2 | ring 直接返回错误，不发送 |

distributor 用 `context.WithoutCancel` 克隆 RPC context，确保客户端提前取消后，已下发的请求仍尽量到达 ingester；默认 `RemoteTimeout` 为 `5s`。这不是所有副本都确认后才返回的同步复制。

## Ingester

### Tenant, Instance and Stream

ingester 内部先按 tenant 找 `instance`，再按规范化 labels 找 `stream`。`instance.Push` 遍历请求中的多个 stream，把接受的 entry 合并进一条 WAL record，最后统一调用 `wal.Log`。证据见 `pkg/ingester/ingester.go:1011-1034`、`pkg/ingester/instance.go:226-280`。

这里有两个容易忽略的边界：

- 多 stream 的 push 不是事务。函数注释明确说明返回错误只反映最后处理的 stream；前面的成功不会回滚。
- WAL record 是在所有 stream 处理完后统一写的。如果中途进程崩溃，内存中已 append 但尚未写入 WAL 的数据可能丢失。

### Out-of-Order and Duplicate Handling

默认 `unordered_writes=true`，但「允许乱序」不等于接受任意旧数据。stream 的接受下界是 `highestTimestamp - MaxChunkAge/2`；默认 `MaxChunkAge=2h`，所以通常仍会拒绝约一小时以前的 entry。更旧的请求还会受到 `reject_old_samples_max_age=7d` 限制。

stream 级 `lastLine` 去重比较上一次追加 entry 的时间戳、日志行和 structured metadata，状态跨 chunk 截断与已 flush chunk 保留；head block 内也有相同字段去重。stream 因不活跃被删除后，这层去重状态会消失。WAL replay 另有 entry counter。它不提供全局 exactly-once，也不会对同一时间戳的不同日志做多数裁决。证据见 `pkg/ingester/stream.go:401-449`、`pkg/chunkenc/unordered.go:115-174`、`pkg/ingester/recovery.go:190-209`。

### Chunk Lifecycle

ingester 为每个 stream 维护一个 chunk，chunk 内由若干 block 组成。默认参数如下：

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `chunk_encoding` | `gzip` | chunk block 的压缩编码 |
| `chunk_block_size` | `256KiB` | 未压缩 block 的目标大小 |
| `chunk_target_size` | `1.5MiB` | 压缩 chunk 的目标大小，不是硬上限 |
| `chunk_idle_period` | `30m` | 无更新后 flush |
| `max_chunk_age` | `2h` | chunk 内日志时间跨度上限 |
| `sync_period` | `1h` | 多 ingester 同步切 chunk 的周期 |
| `flush_check_period` | `30s` | 检查是否应 flush 的周期 |
| `concurrent_flushes` | `32` | 单 ingester 并发 flush 数 |

证据见 `pkg/ingester/ingester.go:148-162`。`shouldFlushChunk` 判断 closed/synced/full、idle 与 max-age；`not-owned` 和 `immediate/forced` 由 `collectChunksToFlush` 叠加，shutdown 不是该函数的独立分支。它不是简单地「每 30 分钟落盘」。实现见 `pkg/ingester/flush.go:318-374`。

## WAL

默认 WAL 开启，目录为 `wal`，checkpoint 周期 `5m`，shutdown flush 默认关闭，磁盘使用率节流阈值 `0.90`，replay 内存上限 `4GiB`。证据见 `pkg/ingester/wal.go:27-59`。

正常路径下，`stream.Push` 把 entry 写入 record，`instance.Push` 随后调用 `wal.Log`；除磁盘满的特殊分支外，WAL 错误会作为 RPC 错误返回。

`ENOSPC` 是例外：代码记录指标并触发 shutdown-flush 开关，但不把该次 WAL 错误直接返回。磁盘监控每 `10s` 检查一次，超过阈值后后续 push 返回 `ErrReadOnly`。实现见 `pkg/ingester/instance.go:264-280`、`pkg/ingester/wal.go:172-238`。

因此 WAL 提供的是**节点本地崩溃恢复**，不是跨节点复制：

- 进程崩溃、磁盘完好：可从 checkpoint 与 segment replay。
- 节点磁盘丢失：没有从对端 WAL 修复本节点的路径，只能依赖其他副本。
- 普通 `SIGTERM`：默认不保证 flush；`prepare_shutdown` 或 `/ingester/shutdown` 才有更明确的 flush/unregister 语义。

## Flush and Upload

flush 的核心顺序是：

```text
Close head block
  -> Encode chunk
  -> store.PutChunks
  -> IndexChunk
  -> 标记 flushed / 失败退避重试
```

`SeriesStore.PutOne` 先写 chunk 对象，再更新 index；两步不是原子事务。chunk 上传成功而 index 失败时可能留下孤儿 chunk。证据见 `pkg/ingester/flush.go:411-519`、`pkg/storage/stores/series_store_write.go:62-133`。

TSDB index 也不是 flush 时同步上传：

1. append 更新 active head，并写 index WAL。
2. 默认每 `15m` 按真实时间 rotation，每 `1m` 检查一次。
3. rotation 后构建多租户 TSDB。
4. index shipper 默认每分钟检查并上传 `.tsdb.gz`。

证据见 `pkg/storage/stores/shipper/indexshipper/tsdb/head_manager.go:35-51,254-275,386-434`、`pkg/storage/stores/shipper/indexshipper/tsdb/manager.go:160-245`。

## Failure Windows

| 故障点 | 已经确认的事实 | 仍可能丢失或不可见的部分 |
| --- | --- | --- |
| HTTP 返回前 | 无成功承诺 | 整个请求 |
| HTTP `204` 返回 | 写入 quorum 成功 | 尚未 flush 的 chunk、尚未上传的 index |
| WAL `Log` 成功 | 本地 WAL 已有记录 | 节点磁盘整体损坏；其他副本也失败 |
| chunk `PutChunks` 成功 | 对象存储已有 chunk | index 尚未写入时该 chunk 不可被正常查询定位 |
| `IndexChunk` 成功 | ingester 侧索引已记录 | index shipper 上传前，其他 querier 可能尚不可见 |
| shipper 上传成功 | 历史索引可被读取 | retention、compaction 或缓存一致性仍有独立生命周期 |

这张表解释了一个常见现象：push 全部成功，但刚写入的数据在对象存储里找不到。它通常仍在 ingester 内存/WAL 或本地 index head 中，而不是必然丢失。

## Common Misconceptions

1. **`204` 等于对象存储已持久化。** 错误；只表示写入 quorum 成功。
2. **RF=3 要求三个 ingester 全部 ACK。** 错误；健康时需要两个。
3. **一个 ingester 不健康后，quorum 自动降为 1。** 错误；原始 quorum 不降低，剩余两个必须全部成功。
4. **WAL 会把故障节点数据复制到对端。** 错误；WAL 是本地日志。
5. **unordered writes 接受任意旧日志。** 错误；仍受 stream 时间窗和租户旧样本限制约束。
6. **chunk 与 index 是一个事务。** 错误；可能产生孤儿 chunk。
7. **去重意味着 exactly-once。** 错误；只在有限范围内消除完全相同的 entry。

## Links

- [Loki](/docs/CS/Distributed/Tracing/Loki.md)
- [Loki Storage](/docs/CS/Distributed/Tracing/Loki/Storage.md)
- [Loki Query Path](/docs/CS/Distributed/Tracing/Loki/Query_Path.md)
- [Loki Consistency](/docs/CS/Distributed/Tracing/Loki/Consistency.md)
- [Grafana Alloy](/docs/CS/Distributed/Tracing/Alloy.md)
- [Promtail](/docs/CS/Distributed/Tracing/Promtail.md)

## References

1. [Loki HTTP API](https://grafana.com/docs/loki/latest/reference/loki-http-api/)
2. [Loki components](https://grafana.com/docs/loki/latest/get-started/components/)
3. [Distributor source](https://github.com/grafana/loki/blob/v3.7.10/pkg/distributor/distributor.go)
4. [Ingester instance source](https://github.com/grafana/loki/blob/v3.7.10/pkg/ingester/instance.go)
5. [Ingester stream source](https://github.com/grafana/loki/blob/v3.7.10/pkg/ingester/stream.go)
6. [Ingester WAL source](https://github.com/grafana/loki/blob/v3.7.10/pkg/ingester/wal.go)
7. [Ingester flush source](https://github.com/grafana/loki/blob/v3.7.10/pkg/ingester/flush.go)
8. [Series store writer source](https://github.com/grafana/loki/blob/v3.7.10/pkg/storage/stores/series_store_write.go)
