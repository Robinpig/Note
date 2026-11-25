## Introduction

Loki 的高可用由 consistent hash ring、副本复制、quorum、WAL 与失败检测共同构成。它保证的是一组可度量的容错语义，而不是跨副本强一致：没有 Raft 式冲突裁决，没有全局 exactly-once，也不会对同一时间戳的冲突日志做多数表决。

本文以 **v3.7.10**（commit `c792f58577a46c64b0a8e808d7c643ed0e8c5e83`）为基线，重点回答三个问题：节点故障时写入还能否成功，查询需要等待多少副本，以及数据在哪些阶段可能不可见或丢失。

## Ring Placement and Membership

每条 stream 的 ring key 是：

```text
FNV32(tenantID + normalized labels)
```

每个 ingester 默认注册 `128` 个 token。distributor 通过 ring 找到该 key 的副本集合，使用 `WriteNoExtend` 选择 `ACTIVE` 实例；`JOINING`/`LEAVING` 节点不会自动扩大副本集。证据见 `pkg/util/ring/ring.go:11-17`、`pkg/distributor/distributor.go:879-894`、`vendor/github.com/grafana/dskit/ring/lifecycler.go:83-103`。

成员生命周期有两个不同概念：

- **unhealthy**：心跳超时，实例仍留在 ring 中，只是不再参与健康副本集。
- **unregister/forget**：实例记录被移除。clean shutdown 会注销；`autoforget_unhealthy` 默认关闭。

默认 lifecycler 心跳周期 `5s`、heartbeat timeout `1m`；显式 common ring 可把心跳周期覆盖为 `15s`。因此「心跳超时」和「节点从 ring 消失」不能混为一谈。

## Write Quorum

默认 `replication_factor=3`。复制策略先计算原始 quorum，再过滤不健康实例：

```text
minOK = floor(N / 2) + 1
maxError = len(healthy) - minOK
```

如果过滤后健康实例少于 `minOK`，ring 直接报错；否则 distributor 等待 `minOK` 个成功 ACK。证据见 `vendor/github.com/grafana/dskit/ring/replication_strategy.go:33-75`。

| 场景 | 行为 |
| --- | --- |
| 3 个副本全部健康 | 2 个 ACK 即成功 |
| 1 个副本不健康 | 剩余 2 个必须全部成功 |
| 2 个副本不健康 | 直接失败，不降低 quorum |
| 客户端取消 | 已下发的 RPC 使用 `WithoutCancel`，仍尽量完成 |

达到 quorum 后，其他 RPC 可能还在执行，因此会短暂存在部分副本已写入、部分未写入的状态。这是复制语义，不是线性一致性。

## Zone-Aware Replication

zone-aware replication 默认关闭。开启后，配置的 RF 被当作期望 zone 数，通常每个 zone 放一个副本；代码不验证实际部署是否真的有 RF 个 zone。

写入仍按成功实例数计算 quorum。读取则按 zone 计算：如果某 zone 内有一个不健康实例，整个 zone 的健康实例都会被排除，再要求多数 zone 成功。证据见 `vendor/github.com/grafana/dskit/ring/ring.go:497-668`。

因此「三 zone 各一副本」不意味着任意单 zone 故障都一定能继续读；必须同时满足 zone 数量、健康 zone 数与 quorum 约束。

## Read Quorum

默认查询不使用 partition ingester，而是访问所有健康 ingester。读取 quorum 不是按每条 stream 的 RF 计算，而是按整个健康 ring 计算：

```text
N          = ring 中实例总数
required   = max(N, RF)
required  -= RF / 2
healthy   = 当前健康实例
maxErrors = len(healthy) - required
```

RF=3 时：

- ring 只有 3 个 ingester：需要 2 个成功。
- ring 有 10 个 ingester：需要 9 个成功。
- 10 个中已有 1 个不健康：剩余 9 个必须全部成功。
- 10 个中已有 2 个不健康：健康数不足，查询失败。

证据见 `vendor/github.com/grafana/dskit/ring/ring.go:711-791`、`pkg/querier/ingester_querier.go:167-247`。默认 `query_ingesters_within=3h`，查询超时默认 `1m`。

读取结果按完整 `Entry.Equal` 去重：timestamp、stream、line、structured metadata 等字段都相同才合并。它不比较冲突日志值，也不做多数表决。

## WAL and Failure Windows

WAL 默认开启，目录 `wal`，checkpoint `5m`，shutdown flush 默认关闭，磁盘节流阈值 `0.90`。启动时先恢复 checkpoint 与 segments，完成后才启动 WAL、flush loop 和 ring lifecycler。证据见 `pkg/ingester/wal.go:27-59`、`pkg/ingester/ingester.go:539-665,776-801`。

WAL 是节点本地日志，不是跨节点复制或修复机制：

- 进程崩溃且磁盘完好：可以 replay 未 flush 数据。
- 节点磁盘整体丢失：无法从对端 WAL 重建本节点，只能依赖其他副本。
- 普通 `SIGTERM`：默认不保证 flush；`prepare_shutdown` 与 `/ingester/shutdown` 才有明确的 flush/unregister 路径。
- `ENOSPC`：当前实现记录指标并触发 shutdown-flush，但不把该次 WAL 错误直接返回；磁盘监控每 `10s` 检查一次。

所以「push 返回 204」不能绝对等同于「每个副本的 WAL 都已可靠持久化」。

## Multi-Tenancy and Limits

默认 `auth_enabled=true`，tenant 来自 `X-Scope-OrgID`；关闭认证时使用 `fake` tenant。tenant ID 贯穿：

- ring token。
- ingester 内的 tenant instance map。
- chunk object key。
- index 路径与 TSDB `__loki_tenant__` matcher。
- limits、retention、delete request。

fakeauth 只提取 header，不验证身份凭据；生产环境仍需要在网关或代理层鉴权。证据见 `pkg/loki/loki.go:149-162`、`pkg/util/fakeauth/fake_auth.go:15-69`、`pkg/ingester/ingester.go:1011-1072`。

默认租户限制包括：

| 限制 | 默认值 |
| --- | --- |
| ingestion rate / burst | `4MB/s` / `6MB` |
| per-stream rate / burst | `3MB/s` / `15MB` |
| max line size | `256KB` |
| global streams per tenant | `5000` |
| local streams per ingester | `0`，不限 |
| reject old samples max age | `7d` |
| max query length | `721h` |
| max query series | `500` |
| runtime override reload | `10s` |

证据见 `pkg/validation/limits.go:314-380,425-450`。runtime override 是异步重载，修改后不会立刻生效。

shuffle sharding 可把 querier、ruler、index gateway 的子集分配给租户，降低单个租户对共享资源的影响；它与 ingester 的数据复制 ring 是不同机制。

## Deployment Modes

Loki 的所有组件都在同一个二进制中，通过 `-target` 选择启动哪些组件。

### Monolithic

`-target=all` 在单进程运行全部组件，适合评估与较小规模。可共享对象存储并横向扩展，但组件无法独立扩缩容。

### Simple Scalable

SSD 拆成三个 target：

- `write`：Distributor、Ingester。
- `read`：Query Frontend、Querier。
- `backend`：Compactor、Index Gateway、Query Scheduler、Ruler、Bloom 组件。

**v3.7.10 官方文档已标记 SSD 弃用，并计划在 Loki 4.0 移除。** 新项目不应再把「SSD 是长期推荐起点」当作稳定结论；可评估 HA monolithic 或 microservices。证据见 `docs/sources/get-started/deployment-modes.md:31-66`、`docs/sources/get-started/overview.md:37`。

### Microservices

每个组件作为独立进程运行，可分别扩缩容，适合超大规模或需要精细控制部署拓扑的场景，也是运维复杂度最高的模式。实际 target 清单应以当前版本的 `-list-targets` 为准。

## Retention and Deletion Lifecycle

retention 默认关闭且周期为 `0s`。开启 retention 时必须配置 compactor 的 `delete_request_store`；否则配置校验失败。

删除请求生命周期：

```text
create request
  -> received
  -> cancellation window（默认 24h）
  -> 额外等待 1m
  -> compactor 处理
  -> processed
  -> marker delay（默认 2h）
  -> sweeper 物理删除 chunk
```

请求只有 `received` 与 `processed` 两个持久化状态；取消是删除请求记录，不存在持久化的 `cancelled` 状态。已经 processed 的请求不能普通取消。

- `filter-only`：只隐藏查询结果，不物理删除。
- `filter-and-delete`：默认模式；整块命中直接删，部分命中会重写 chunk 并更新 index。
- `processed`：索引处理完成，不代表对象存储已立即删除。

证据见 `pkg/compactor/config.go:49-70,109-121`、`pkg/compactor/deletion/delete_requests_manager.go:291-311,415-456`、`pkg/compactor/retention/marker.go:147-177,349-379`。带 line filter 的删除成本很高，可能需要水平扩展 compactor；对象存储 versioning 是重要的恢复手段。

## Failure Matrix

| 故障 | 写入 | 查询 | 数据风险 |
| --- | --- | --- | --- |
| 单个 ingester 进程崩溃 | quorum 仍可能成功 | 其他副本可服务 | 本地 WAL 可恢复 |
| 单节点磁盘丢失 | 其他副本可服务 | 其他副本可服务 | 丢失该副本未 flush 数据 |
| 少于 quorum 的副本可用 | push 失败 | 可能仍可读已有数据 | 不应对失败请求假设已写入 |
| 所有副本在 flush 前永久丢失 | 不可恢复 | 不可读 | 可能丢失尚未进入对象存储的数据 |
| chunk 上传成功、index 失败 | flush 重试 | 该 chunk 暂不可定位 | 孤儿 chunk |
| index shipper 上传延迟 | 写入仍可成功 | ingester 可查近期，其他 querier 延迟可见 | 通常不是丢失 |
| compactor 故障 | 写入不受直接影响 | 已有索引仍可查 | retention/deletion 延迟 |

## Common Misconceptions

1. **Loki 是强一致系统。** 错误；它使用 quorum 复制和失败检测，不做跨副本冲突裁决。
2. **心跳超时等于节点被删除。** 错误；默认只是标记不健康。
3. **RF=3 的读取只需任意两个 ingester。** 错误；默认按整个健康 ring 计算读取 quorum。
4. **WAL 会修复故障节点。** 错误；WAL 是本地日志。
5. **`processed` 表示 chunk 已立即物理删除。** 错误；后面还有 marker delay 与 sweeper。
6. **SSD 是长期推荐架构。** 错误；v3.7.10 已标记弃用。
7. **多租户只靠对象 key 前缀。** 错误；tenant 同时进入 ring、内存 map、index、limits 与 retention。

## Links

- [Loki](/docs/CS/Distributed/Tracing/Loki.md)
- [Loki Write Path](/docs/CS/Distributed/Tracing/Loki/Write_Path.md)
- [Loki Storage](/docs/CS/Distributed/Tracing/Loki/Storage.md)
- [Loki Query Path](/docs/CS/Distributed/Tracing/Loki/Query_Path.md)
- [Distributed Systems](/docs/CS/Distributed/Distributed.md)
- [etcd Raft](/docs/CS/Framework/etcd/raft.md)

## References

1. [Loki deployment modes](https://grafana.com/docs/loki/latest/get-started/deployment-modes/)
2. [Consistent hash rings](https://grafana.com/docs/loki/latest/get-started/hash-rings/)
3. [Isolate tenant workflows using shuffle sharding](https://grafana.com/docs/loki/latest/operations/shuffle-sharding/)
4. [Write-ahead logs](https://grafana.com/docs/loki/latest/operations/storage/wal/)
5. [Log retention](https://grafana.com/docs/loki/latest/operations/storage/retention/)
6. [Log entry deletion](https://grafana.com/docs/loki/latest/operations/storage/logs-deletion/)
7. [Ring replication strategy source](https://github.com/grafana/loki/blob/v3.7.10/vendor/github.com/grafana/dskit/ring/replication_strategy.go)
8. [Ingester WAL source](https://github.com/grafana/loki/blob/v3.7.10/pkg/ingester/wal.go)
