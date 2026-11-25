## Introduction

Loki 的一次查询不是「把 LogQL 发给 querier」这么简单。请求先经过前端排队与 scheduler 公平队列，再由 queryrange 层做时间切分和 TSDB keyspace 分片；每个子查询执行 `matchers -> postings -> series -> ChunkRef -> chunk decode -> LogQL pipeline`，最后合并、去重并应用 limit。

本文以 **v3.7.10**（commit `c792f58577a46c64b0a8e808d7c643ed0e8c5e83`）为基线。查询优化的大部分收益来自减少无效工作：少下无关索引、少下载 chunk、少解压、提前停止，而不是为日志正文建立全文倒排索引。

## End-to-End Query Path

```text
Grafana / LogCLI
  │  /loki/api/v1/query_range | query | labels | series
  ▼
Query Frontend v2
  ├─ 长连接、query ID、actor、租户
  └─ 入队，等待结果
  ▼
Query Scheduler
  └─ tenant/actor 分层公平队列
  ▼
Querier
  ├─ queryrange middleware
  │    ├─ 时间 split
  │    ├─ TSDB fingerprint shard
  │    ├─ cache
  │    └─ retry / limit
  ▼
LogQL Engine
  ├─ ingester：近期内存数据
  └─ storage：TSDB index -> ChunkRef -> chunk cache/object store
                 │
                 ▼
          decode -> pipeline -> sample extraction
  ▼
merge / deduplicate / sort / limit
  ▲
  │
Querier queryrange 合并子查询结果并返回完整响应
  ▲
  │
Frontend v2 解码响应并转发给客户端
```

Frontend v2 本身主要是传输与排队层：它不合并子查询，只等待并解码 querier 返回的完整响应；split/cache/shard 中间件与子结果合并均位于 querier 的 queryrange 路径。证据见 `pkg/lokifrontend/frontend/v2/frontend.go:65-79,219-395`、`pkg/querier/queryrange/split_by_interval.go:244-248`、`pkg/querier/queryrange/roundtrip.go:415-493,689-753,1028-1107`。

## Queueing and Fairness

Frontend v2 为每个 scheduler 地址启动 worker，默认 `scheduler-worker-concurrency=5`。scheduler 按 tenant 与 actor 组织分层队列，默认 `MaxOutstandingPerTenant=32000`、最多 `3` 层队列。actor 来自 `X-Loki-Actor-Path`，用于区分同一租户内的不同工作流。

同一个 scheduler stream 使用 Recv/Send lockstep，不会在该 stream 上并行处理多个请求；querier 默认 `max-concurrent=4`，并分配到各 scheduler stream。这里的并发度和后续 LogQL 子查询并行度不是同一个概念。

证据见 `pkg/scheduler/scheduler.go:107-120,353-550`、`pkg/querier/worker/worker.go:263-294`、`pkg/querier/worker/scheduler_processor.go:139-178`。

## Time Split and Keyspace Shard

查询规划有两个正交维度：

1. **时间 split**：把查询窗口切成多个时间片。
2. **TSDB shard**：把 fingerprint keyspace 切成多个区间。

普通日志与 instant metric 查询默认按 `1h` split，metadata 默认按 `24h` split。`split_recent_metadata_queries_by_interval` 虽有 `1h` 默认值，但 `recent_metadata_query_window` 默认 `0`，该分支默认不启用，实际仍按 `24h` split；只有显式配置非零 window，且请求 start 落在该窗口内时，才使用近期 split。`ingester_query_split_duration=0` 表示沿用普通 split，而不是禁用 ingester 查询。证据见 `pkg/validation/limits.go:432-448`、`pkg/querier/queryrange/labels_cache.go:22-42`、`pkg/querier/queryrange/split_by_interval.go:114-225`。

TSDB 默认使用 `power_of_two` 策略：先估算索引字节数，再以 `600MiB` 为目标向上取到 2 的幂，最后按 fingerprint 前缀等分 keyspace。`600MiB` 是目标，不是硬上限；等分也不保证各 shard 的真实工作量完全均匀。`bounded` 策略可根据 series/chunk sizing 生成边界，并可预计算 `ChunkGroups`。

证据见 `pkg/querier/queryrange/shard_resolver.go:31-61,184-306`、`pkg/querier/queryrange/querysharding.go:179-220,322-348,440-484`、`pkg/storage/stores/shipper/indexshipper/tsdb/sharding/power.go:12-101`。

`max_query_parallelism` 默认 `32`，`tsdb_max_query_parallelism` 默认 `128`；跨 schema 查询会按 TSDB/非 TSDB 时间占比加权。真正限制单个查询下游并发的是 `LimitedRoundTripper` 的 semaphore，不是 querier 进程数。

## LogQL Parsing and Engine

HTTP 层默认创建 v1 engine，可启用 v2；v2 不可用或返回 `ErrNotSupported` 时回退 v1，其他错误直接返回。Parser 解析后执行 validate，stream selector 至少要有一个 matcher，纯 `{}` 会被拒绝。

`Engine.Eval` 按 query variant 与 AST 类型分派：

- `LogSelectorExpr` -> `SelectLogs` -> entry iterator。
- `SampleExpr` -> `SelectSamples` -> sample iterator / vector。

公开 HTTP instant API 只接受 `SampleExpr`，对 log selector 返回 unsupported syntax。`maxLookBackPeriod` 的向前回看只出现在内部 `InstantType` 的 `SelectLogs` 求值路径，不能描述为公开 instant log 查询的行为。证据见 `pkg/logql/syntax/parser.go:73-153`、`pkg/querier/http.go:65-111,122-127`、`pkg/logql/engine.go:309-434`、`pkg/logql/evaluator.go:322-324`。

## Labels to TSDB ChunkRefs

存储侧先将 LogQL matchers 转成存储请求，注入 shard，并把时间边界 round 到毫秒。`lazyChunks` 模式此时只取 `ChunkRef`，尚未下载 chunk 内容。

`PostingsForMatchers` 的处理可概括为：

```text
equality matcher
  -> 直接查 postings

有限集合 regexp
  -> 展开后查 postings

复杂 regexp
  -> 枚举 LabelValues

否定 matcher
  -> inverse postings

正 matcher postings
  -> Intersect / Merge

否定集合
  -> Without
```

得到 series ref 后，Reader 在查询窗口内读取 labels 与 chunk metas，只保留时间重叠的 `ChunkMeta`，再转成 `ChunkRef`。FormatV3 的 page marker 用于跳过无关页。

证据见 `pkg/storage/stores/shipper/indexshipper/tsdb/querier.go:87-253`、`pkg/storage/stores/shipper/indexshipper/tsdb/index/postings.go:441-657`、`pkg/storage/stores/shipper/indexshipper/tsdb/index/index.go:2346-2444`、`pkg/storage/stores/shipper/indexshipper/tsdb/single_file_index.go:164-280`。

这一步的主要成本是 postings 膨胀、regexp 枚举和 series/chunk page 解码，不是日志正文扫描。

## Ingester and Store Merge

querier 按 schema 时间窗把查询分给 ingester 与 store，再 merge 两侧结果。默认 `query_ingesters_within=3h`；ingester 还可能在一定回看范围内继续查询 store，以覆盖尚未 flush 或重复数据。

ingester 从 tenant instance 找内存 stream，构造 pipeline，按 stream labels 缓存 pipeline，迭代后返回按时间排序的 entry iterator。证据见 `pkg/querier/querier.go:74-80,153-275`、`pkg/ingester/ingester.go:1077-1205`、`pkg/ingester/instance.go:486-616`。

读取 quorum 与去重不属于 LogQL 语义，详见 [Consistency](/docs/CS/Distributed/Tracing/Loki/Consistency.md)。

## Chunk Fetch and Decode

Fetcher 的流程是：

```text
ChunkRef / ExternalKey
  -> L1 chunk cache
  -> L2 chunk cache
  -> object store GET
  -> decode
  -> write-back cache
```

固定 `16` 个 decode worker 并行解码，返回顺序不保证。`chunk.Decode` 校验 CRC、metadata 身份与长度，再按 encoding 创建可迭代 Data。证据见 `pkg/storage/chunk/fetcher/fetcher.go:42-90,127-328`、`pkg/storage/chunk/chunk.go:329-385`。

Batch iterator 会：

- 先加载首批 chunk，并按 series matchers 预过滤。
- 相邻 batch 保留 overlap chunk，调整时间边界，避免漏掉跨界日志。
- `LazyChunk` 按 block 迭代，并缓存与下一 chunk 重叠的 block，减少重复解压。
- backward 查询反转 block/entry 顺序。

证据见 `pkg/storage/batch.go:106-459,604-784`、`pkg/storage/lazy_chunk.go:31-225`。

## Pipeline, Deduplication and Limit

LogQL pipeline 按 stream labels 复用，stage 顺序执行；任一 stage 失败就丢弃该 entry。metric extractor 先执行 deletion filter，再提取样本。

多 stream 使用排序 entry iterator；单 stream 先通过 `NonOverlapping` 串联，再 `MergeEntryIterator` 去重。Merge 只在多个输入 iterator 之间按 stream hash 与 timestamp 缓冲比较，不处理单个 iterator 内部重复；`Entry.Equal` 同时比较 timestamp、line、structured metadata 与 parsed 字段，而非只比较原始日志三元组。同 timestamp 不同 line 保留顺序。`NonOverlappingIterator` 本身不是去重器。

证据见 `pkg/logql/log/pipeline.go:187-233`、`pkg/logql/log/metrics_extraction.go:240-299`、`pkg/iter/entry_iterator.go:66-155,408-435`、`pkg/push/types.go:797-838`、`pkg/storage/batch.go:419-459`。

range query 根据 direction 取最早或最新结果；时间 split 后，如果下游已经达到 limit，可以提前停止，避免继续拉取更旧的分片。

## Metric Queries

`SampleExpr` 从日志流提取样本，`SelectSamples` 在 ingester 和 store 分别执行后 merge。`NewStepEvaluator` 递归处理 range aggregation、vector、binop、`label_replace`；range aggregation 会把 start 提前 `interval+offset`、end 延后 `1ns`，保证边界样本完整。

`sum(vector(range))` 在部分场景下可把 vector aggregation 下推，减少中间 labels。engine 随后按 step 循环求值并 Join 各 shard 向量，同时受 `MaxQuerySeries` 限制。

证据见 `pkg/logql/evaluator.go:329-397`、`pkg/logql/engine.go:374-434`、`pkg/storage/store.go:527-588`。

metric 查询的成本不仅是日志过滤，还包括：

- 每个 step 的 range window。
- 解析与 unwrap 的 CPU。
- 中间 series cardinality。
- 向量聚合与 Join。

## Caching

Loki 有多个独立缓存层，不能笼统理解成「缓存查询结果」。

| 缓存 | 键 / 内容 | 语义 |
| --- | --- | --- |
| Chunk cache | `ChunkRef` / external key | 缓存压缩 chunk，减少对象存储 GET |
| Metric results cache | query hash | 缓存 metric query 的分片结果 |
| Log results cache | query + interval bucket | v3.7.10 主要缓存 filter query 的空结果 |
| Series cache | 排序后的 matchers | 缓存 series 查询 |
| Labels cache | label names / values | 缓存 metadata 查询 |
| Index gateway local cache | TSDB/BoltDB 文件 | 避免重复下载与解析索引 |

通用 results cache key 可概括为：

```text
userID:query:step:currentInterval
```

instant metric cache 使用另一套带 `instant-metric` 前缀并把 split duration 纳入键的格式，避免 split 配置变化后复用旧结果。log results cache 只在 `interval != 0`、`limit != 0` 等条件下使用；命中空区间后会补查对齐产生的首尾缺口，因此不会把边界外数据误判为空。证据见 `pkg/storage/chunk/cache/resultscache/cache.go:30-37`、`pkg/querier/queryrange/instant_metric_cache.go:16-37`、`pkg/querier/queryrange/queryrangebase/results_cache.go:116-260`、`pkg/querier/queryrange/log_result_cache.go:66-320`、`pkg/querier/queryrange/series_cache.go:29-47`、`pkg/querier/queryrange/labels_cache.go:22-65`。

## Bloom Filters

Bloom filter 用于在下载 chunk 前排除「不可能包含目标 structured metadata」的候选。它由 planner、builder、gateway 三类组件组成，默认关闭，仍为实验特性。

### Build

Planner 比较 TSDB 与已有 bloom meta 的 source/bounds，找出未索引 gap，再把任务入队。Builder 读取 chunk 的 structured metadata，为每个 key/value 生成四类 token：

```text
name
prefix + name
name=value
prefix + name=value
```

chunk prefix 编码 From、Through、Checksum。默认规划策略按 keyspace 拆分，factor 为 `256`。证据见 `pkg/bloombuild/planner/planner.go:221-675`、`pkg/bloombuild/builder/builder.go:367-532`、`pkg/storage/bloom/v1/bloom_tokenizer.go:59-221`。

**Bloom 索引的是 structured metadata，不是任意日志正文 substring。** 如果 trace_id 只在日志正文里、没有放进 structured metadata，bloom 不能直接用它排除 chunk。

### Query

查询侧只从首个 parse stage 之前提取 label filters：`LineFilterLabelFilter` 的 equality 与可简化为有限集合的 regexp 可测试；`StringLabelFilter` 只有 equality 可测试，其余类型转为 `UnsupportedLabelMatcher` 并保守放行。Gateway 按 fingerprint 分组、按天请求，并依次判断 series bloom 与 chunk prefix bloom。

- 命中：认为可能存在，保留 chunk。
- 未命中：排除 chunk。
- false positive：多扫一个 chunk，不会漏数。
- block 缺失、page 过大、schema 过低、matcher 不支持：fail-open，保留 chunk。

证据见 `pkg/storage/bloom/v1/ast_extractor.go:46-113`、`pkg/storage/bloom/v1/bloom_tester.go:21-197`、`pkg/bloomgateway/querier.go:105-193`、`pkg/bloomgateway/bloomgateway.go:223-508`。

v3.7.10 的普通 index gateway `GetChunkRef` 路径会调用 bloom filtering；但 bounded shards 路径中该逻辑被注释关闭，以避免加倍 bloom gateway 负载。因此不能声称所有分片路径都经过 bloom。

## Defaults and Bottlenecks

| 项目 | 默认值 |
| --- | --- |
| 普通 / instant metric split | `1h` |
| metadata split | `24h` |
| recent metadata split | `1h`，但默认 window 为 `0`，需显式启用 |
| `max_query_parallelism` | `32` |
| `tsdb_max_query_parallelism` | `128` |
| TSDB shard byte target | `600MiB` |
| querier `max-concurrent` | `4` |
| frontend scheduler worker concurrency | `5` |
| chunk decode workers | `16` |
| `query_ingesters_within` | `3h` |
| bloom read filtering | 关闭 |

排查慢查询时，按顺序看：

1. scheduler 队列是否堆积。
2. split/shard 扇出是否过多，是否在 semaphore 上等待。
3. TSDB postings/series 解码是否膨胀。
4. chunk cache miss、对象存储延迟与解压 CPU。
5. LogQL pipeline 是否扫描了过多行。
6. metric step 与 series cardinality 是否放大。
7. bloom 是否真正启用并覆盖目标 metadata。

## Common Misconceptions

1. **Query Frontend 负责所有 split。** 错误；v2 frontend 主要做传输与排队，split 在 queryrange 路径。
2. **`max_query_parallelism` 是 querier 进程数。** 错误；它限制单个查询的下游并发。
3. **TSDB shard 就是时间 split。** 错误；一个切时间，一个切 fingerprint keyspace。
4. **`NonOverlapping` 负责去重。** 错误；完整 entry 去重在 merge iterator。
5. **Bloom 是日志正文全文索引。** 错误；它主要索引 structured metadata。
6. **Bloom 误报会漏数。** 错误；误报只会保留候选、增加扫描。
7. **所有 TSDB 查询都经过 bloom。** 错误；v3.7.10 的 bounded shards 路径绕过了该逻辑。

## Links

- [Loki](/docs/CS/Distributed/Tracing/Loki.md)
- [Loki Storage](/docs/CS/Distributed/Tracing/Loki/Storage.md)
- [Loki Write Path](/docs/CS/Distributed/Tracing/Loki/Write_Path.md)
- [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md)
- [Grafana](/docs/CS/Distributed/Tracing/Grafana.md)

## References

1. [Loki components](https://grafana.com/docs/loki/latest/get-started/components/)
2. [Configure caches to speed up queries](https://grafana.com/docs/loki/latest/operations/caching/)
3. [Ensure query fairness within tenants](https://grafana.com/docs/loki/latest/operations/query-fairness/)
4. [Manage bloom filter building and querying](https://grafana.com/docs/loki/latest/operations/bloom-filters/)
5. [LogQL](https://grafana.com/docs/loki/latest/query/)
6. [Querier source](https://github.com/grafana/loki/blob/v3.7.10/pkg/querier/querier.go)
7. [LogQL engine source](https://github.com/grafana/loki/blob/v3.7.10/pkg/logql/engine.go)
8. [Bloom tokenizer source](https://github.com/grafana/loki/blob/v3.7.10/pkg/storage/bloom/v1/bloom_tokenizer.go)
