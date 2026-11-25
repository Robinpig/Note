## Introduction

Loki 的「只索引标签」并不意味着存储里只有两种简单文件。至少有三层格式需要分开理解：

1. 对象存储中的 **chunk 对象**：压缩后的日志正文、structured metadata 和校验信息。
2. chunk 内部的 **MemChunk**：block、entry、符号表与偏移元数据。
3. **TSDB index**：labels、fingerprint、series 与 `ChunkMeta`，用于把标签查询定位到 chunk。

查询器从不从 TSDB 里读取日志正文；它先用 index 得到 `ChunkRef`，再按 schema 计算 object key 并下载 chunk。本文以 **v3.7.10**（commit `c792f58577a46c64b0a8e808d7c643ed0e8c5e83`）为基线。

## Three Storage Layers

| 层次 | 保存什么 | 不保存什么 |
| --- | --- | --- |
| Chunk object | 日志行、structured metadata、压缩 block、chunk 元数据与 checksum | 可直接查询的 labels postings |
| MemChunk V4 | block 二进制、entry、metadata 符号表、block meta | 跨 chunk 的全局索引 |
| TSDB series | labels、fingerprint、`ChunkMeta`、chunk 引用 | 日志正文与 structured metadata 值 |

「stream」这个词在不同层含义不同：写入侧的 stream 是 `{labels}`；TSDB builder 中的 `stream` 只是以 `labels.String()` 为 key 的内存聚合对象；最终写到 TSDB 的是 series。三者相关，但不是同一个磁盘结构。

## Chunk Object Envelope

外层 `chunk.Chunk` 包含 `ChunkRef`、`Metric`、`Encoding`、`Data`。编码后的对象布局可概括为：

```text
[u32 metadataLen]
[Snappy(JSON metadata)]
[u32 dataLen]
[MemChunk bytes]
```

对象字节计算 `CRC32C`，最终 checksum 由 external key 携带。读取时先校验 CRC，再解 metadata、核对 user/fingerprint/from/through/checksum，最后按 `Encoding` 解码内层数据。证据见 `pkg/storage/chunk/chunk.go:42-55,228-385`、`pkg/storage/chunk/client/object_client.go:117-154`。

这意味着两层压缩并不矛盾：外层 metadata 使用 Snappy，内层日志 block 默认使用 gzip。

## MemChunk V4 and Structured Metadata

schema v13 使用 chunk format V4。V4 在 chunk 级维护一个去重的 structured metadata 符号表；每条 entry 的 block 数据只保存名称符号 ID 与值符号 ID，而不是反复写入字符串：

```text
timestamp
lineLen
line bytes
symbolSectionLen
pairCount
(nameID, valueID) ...
```

整个 block 再按 chunk codec 压缩。相同 timestamp、line 和 symbols 的 entry 会被判重。证据见 `pkg/chunkenc/unordered.go:100-173,405-475`、`pkg/chunkenc/memchunk.go:408-741`。

structured metadata 的关键性质是：

- 它不是 stream label，不产生新 series。
- 它不进入 TSDB postings。
- 它随 chunk 存储，查询时需要先定位并读取 chunk。
- v3.7.10 的 bloom filter 可以索引它的 key/value，但 bloom 仍是独立的实验特性。

默认单行 structured metadata 上限为 `64KB`、`128` 项；超限 entry 会被拒绝或按配置丢弃。证据见 `pkg/validation/limits.go:491-494`。

## Schema v13

schema 同时决定 chunk 格式和 TSDB index 格式：

| Schema | Chunk format | TSDB format |
| --- | --- | --- |
| `<= v12` | V3 | FormatV2 |
| `v13` | V4 | FormatV3 |

TSDB 的 index period 被强制为 **24 小时**，不是建议值；配置成其他周期会启动失败。v10-v13 要求 `row_shards > 0`，默认 `16`。证据见 `pkg/storage/config/schema_config.go:32-33,380-386,421-497`。

```yaml
schema_config:
  configs:
    - from: "2024-04-01"
      store: tsdb
      object_store: s3
      schema: v13
      index:
        prefix: loki_index_
        period: 24h
      row_shards: 16
```

schema 可以按 `from` 日期分段，查询会跨 schema 路由；但已经写入数据后不能随意回退旧 schema。升级前应同时考虑 chunk 格式、index 格式和组件版本兼容性。

## TSDB File Structure

一个 TSDB 文件按 TOC 组织，主要 section 包括：

```text
Symbols
Series
LabelIndices
Postings
LabelIndicesTable
PostingsTable
FingerprintOffsets
```

TOC 还内嵌 `Metadata{From, Through, Checksum}`，它不是独立 section。series 按 fingerprint、再按 labels 排序，并做 16 字节对齐；series ref 是文件位置除以 16。series 内保存 fingerprint、label 名称/值符号 ID，以及一组 chunk meta。证据见 `pkg/storage/stores/shipper/indexshipper/tsdb/index/index.go:158-168,341-387`。

`ChunkMeta` 只保存定位与筛选所需字段：

```text
Checksum
MinTime
MaxTime
KB
Entries
```

FormatV3 每 16 个 chunk 写一个 page marker；读取时可以跳过无关页，chunk 少于 64 个时也可线性扫描。证据见 `pkg/storage/stores/shipper/indexshipper/tsdb/index/chunk.go:12-105,176-248`。

TSDB 不保存 object path。查询得到 `ChunkMeta` 后构造：

```text
ChunkRef{tenant, fingerprint, from, through, checksum}
```

再由 `SchemaConfig.ExternalKey` 计算对象键。证据见 `pkg/storage/stores/shipper/indexshipper/tsdb/single_file_index.go:164-280`、`pkg/storage/config/schema_config.go:758-785`。

## Object Keys

v12+ 的 external key 为：

```text
<tenant>/<fingerprint>/<from>:<through>:<checksum>
```

S3 直接使用该 key，**不会自动添加 `chunks/` 前缀**；根前缀来自 `storage_prefix` 或 legacy `object_prefix`。filesystem 使用 `FSEncoder`：v12+ 保留 tenant/fingerprint 目录，只 base64 编码尾部；旧 schema 会编码整个 key。

典型布局：

```text
S3:
s3://<bucket>/<optional-prefix>/<tenant>/<fingerprint>/<from>:<through>:<checksum>

filesystem v13:
<directory>/<optional-prefix>/<tenant>/<fingerprint>/<base64(from:through:checksum)>
```

索引默认前缀为 `index/`，table 名是 `Unix秒 / 86400` 得到的天序号；per-tenant 文件再增加 tenant 目录。证据见 `pkg/storage/chunk/client/object_client.go:65-155`、`pkg/storage/config/schema_config.go:421-429,745-785`、`pkg/storage/stores/shipper/indexshipper/storage/client.go:79-155`。

## Write and Index Upload

chunk 与 index 的写入顺序是：

```text
PutChunks
  -> IndexChunk
  -> chunk cache write-back
```

`PutOne` 会先查 chunk cache；命中且不跨 schema period 时可以跳过重复写。否则 chunk 先上传，随后更新 index。两步不是原子事务，可能留下孤儿 chunk。证据见 `pkg/storage/stores/series_store_write.go:62-133`。

TSDB index 上传是另一条异步链路：

1. append 更新 active head，并写 index WAL。
2. 默认每 `15m` 按真实时间 rotation，每 `1m` 检查。
3. rotation 后按 chunk 所在 24 小时 bucket 构建多租户 TSDB。
4. 多租户 TSDB 加入 `__loki_tenant__` matcher，但保留原 fingerprint。
5. index shipper 默认每分钟检查，将本地 `.tsdb` gzip 成 `.tsdb.gz` 后上传。

证据见 `pkg/storage/stores/shipper/indexshipper/tsdb/head_manager.go:35-51,155-275,386-434`、`pkg/storage/stores/shipper/indexshipper/tsdb/manager.go:160-245`、`pkg/storage/stores/shipper/indexshipper/uploads/index_set.go:126-182`。

## Index Gateway

index gateway 是索引查询 gRPC 服务，负责：

- 下载并缓存 TSDB/BoltDB index。
- 按 table 分发查询。
- 返回 series、labels 或 chunk refs。
- 在 ring mode 下按租户 shuffle sharding。

它不写索引，也不是 chunk 数据网关；使用 gateway client 的读路径不会通过它读取 chunk 正文。默认使用 simple mode。证据见 `pkg/indexgateway/gateway.go:112-243`、`pkg/indexgateway/config.go:12-92`、`pkg/storage/store.go:248-295`。

querier 侧支持 query-time 按需下载、周期 resync、query readiness 和缓存 TTL 清理。`query_ready_num_days=0` 只表示不主动预热，不影响历史查询。

## Compactor

Compactor 通过单 token、RF=1 的 ring 选举一个 leader。通用提交顺序是：

```text
rebuild index
  -> retention / deletion
  -> build new files
  -> upload
  -> 上传成功后删除源 index
```

TSDB compaction 将 common 多租户索引与已有 per-tenant 索引合并，去掉 tenant label、保留原 fingerprint，排序去重 chunk metas，最终形成 per-tenant TSDB。证据见 `pkg/compactor/compactor.go:37-69`、`pkg/storage/stores/shipper/indexshipper/tsdb/compactor.go:95-273`。

### Retention

retention 默认关闭，周期默认 `0s`。开启后由 compactor 按 `now - chunk.Through > retention_period` 判断过期；不是按 chunk 的起始时间。证据见 `pkg/validation/limits.go:425-427`、`pkg/compactor/config.go:49-56`、`pkg/compactor/retention/expiration.go:56-78`。

默认 compaction interval 为 `10m`；retention 与其同周期执行时会加 `5m` jitter，实际默认间隔变为 `15m`。retention marker 默认延迟 `2h` 后进入 sweeper。对象存储 lifecycle 必须长于 retention 加删除延迟，否则可能在 compactor 完成索引清理前直接删掉 chunk。

### Deletion

删除请求默认模式为 `filter-and-delete`：

- `filter-only`：查询时隐藏匹配行，chunk 仍保留。
- `filter-and-delete`：整块命中时从 index 移除并延迟删除对象；部分命中时先重写 chunk、更新 index，再删除源 chunk。

持久化主状态为 `received` 与 `processed`；部分完成时 API 会派生 `<percent>% Complete` 状态。取消通过移除请求记录实现，不存在持久化的 `cancelled` 状态。`processed` 也不等于对象已经立即物理消失，后面仍有 marker 延迟和 sweeper。状态派生见 `pkg/compactor/deletion/request_handler.go:246-256`，详细生命周期见 [Consistency](/docs/CS/Distributed/Tracing/Loki/Consistency.md)。

## Defaults

| 项目 | 默认值 | 证据 |
| --- | --- | --- |
| TSDB index period | `24h`，强制 | `schema_config.go:470-472` |
| schema v13 row shards | `16` | `schema_config.go:380-386` |
| chunk encoding | `gzip` | `ingester.go:158` |
| block target | `256KiB` 未压缩 | `ingester.go:156` |
| chunk target | `1.5MiB` 压缩 | `ingester.go:157` |
| head rotation / check | `15m` / `1m` | `head_manager.go:47-51` |
| shipper upload / resync / cache TTL | `1m` / `5m` / `24h` | `shipper.go:43-88` |
| query readiness | `0d` | `shipper.go:88` |
| compactor interval | `10m` | `compactor/config.go:52` |
| retention | 关闭，`0s` | `validation/limits.go:425-427`、`compactor/config.go:55` |
| retention delete delay | `2h` | `compactor/config.go:54` |
| deletion cancellation window | `24h` | `compactor/config.go:62` |
| TSDB 单文件上限 | `64GiB` | `index/writer.go:71-76` |
| TSDB shard 字节目标 | `600MiB`，非硬上限 | `sharding/power.go:12-13` |

## Common Misconceptions

1. **structured metadata 是另一种 label。** 错误；它存在 chunk 中，不进 postings。
2. **TSDB 保存 chunk 字节。** 错误；只保存 labels、fingerprint 与 `ChunkMeta`。
3. **TSDB index period 可以随意配置。** 错误；必须是 24 小时。
4. **`query_ready_num_days=0` 不能查历史。** 错误；只是不主动预热。
5. **S3 一定使用 `chunks/` 前缀。** 错误；v12+ external key 直接从 tenant 开始。
6. **index gateway 代理 chunk 正文。** 错误；它只服务索引。
7. **retention 默认 31 天。** 错误；默认关闭且周期为 `0s`。
8. **chunk 与 index 是分布式事务。** 错误；存在孤儿 chunk 窗口。

## Links

- [Loki](/docs/CS/Distributed/Tracing/Loki.md)
- [Loki Write Path](/docs/CS/Distributed/Tracing/Loki/Write_Path.md)
- [Loki Query Path](/docs/CS/Distributed/Tracing/Loki/Query_Path.md)
- [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md)
- [Distributed Systems](/docs/CS/Distributed/Distributed.md)

## References

1. [Loki storage](https://grafana.com/docs/loki/latest/configure/storage/)
2. [Migrate to TSDB](https://grafana.com/docs/loki/latest/setup/migrate/migrate-to-tsdb/)
3. [Structured metadata](https://grafana.com/docs/loki/latest/get-started/labels/structured-metadata/)
4. [Log retention](https://grafana.com/docs/loki/latest/operations/storage/retention/)
5. [Log entry deletion](https://grafana.com/docs/loki/latest/operations/storage/logs-deletion/)
6. [Chunk source](https://github.com/grafana/loki/blob/v3.7.10/pkg/storage/chunk/chunk.go)
7. [TSDB index source](https://github.com/grafana/loki/blob/v3.7.10/pkg/storage/stores/shipper/indexshipper/tsdb/index/index.go)
8. [Compactor source](https://github.com/grafana/loki/blob/v3.7.10/pkg/compactor/compactor.go)
