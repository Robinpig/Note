## Introduction

本篇拆解一次 search 请求在 ES 内部的完整旅程：协调节点如何扇出、每个分片收集多少文档、协调节点如何归并、fetch 阶段到底按什么顺序补数据。

**版本基线：Elasticsearch 9.5.5**。下文 `server/...` 路径相对源码根（tag `v9.5.5`），可逐条反查。

> [!IMPORTANT]
> **先打破四个直觉**：① 每个分片返回的是 **from+size** 条而不是 size 条——少了 from 条，全局第 from 页就拼不出来；② `terminate_after` 是**每分片独立计数**，且刻意在 post_filter **之后**才计数；③ `size=0` 依然执行完整 query phase（只是 fetch 短路）；④ `action.search.shard_count.limit` 默认是 **Long.MAX_VALUE**——不是广为流传的 10000。

## 全景图

```
协调节点（search_coordination 线程池）
 ├─ can_match 预过滤（默认开，128 分片阈值，见 Query DSL 篇）
 ├─ DFS 阶段（可选）：各分片上报 term statistics → 求和 → 随查询下发
 ├─ Query 阶段：扇出到相关分片（数据节点 search 线程池）
 │     per-shard: query rewrite → collector 收 from+size 条（含聚合）
 ├─ reduce：mergeTopDocs 全局排序（batchedReduceSize=512 分批 partial reduce）
 └─ Fetch 阶段：按 doc id 批量取原文 → 11 个 fetch subphase 依序加工
```

## Query 阶段：每个分片收多少条

`QueryPhase.execute`（`server/.../search/query/QueryPhase.java:62-75`）在分片上的执行顺序固定：

```java
executeQuery(searchContext):
  AggregationPhase.preProcess(...)   // :140 聚合与 top docs 共用同一 collector
  addCollectorsAndSearch(...)        // :142 searcher.search(query, collectorManager)
  RescorePhase.execute(...)          // :144
  SuggestPhase.execute(...)          // :145
```

**分片级 topN = from + size**（`QueryPhaseCollectorManager.java:236-239`）：

```java
final int totalNumDocs = Math.max(1, reader.numDocs());
if (searchContext.scrollContext() == null) {
    int numDocs = Math.min(searchContext.from() + searchContext.size(), totalNumDocs);
```

协调节点侧同样以 from+size 定义请求大小（`SearchPhaseController.java:549-564` `getTopDocsSize`）。原因：全局排序前任何分片都可能贡献 top from+size 窗口内的任意一条，单分片无法预知自己的位置；归并时在 from 处截取（`TopDocs.merge(sort, from, topN, shardTopDocs)`，`SearchPhaseController.java:145-176`），最终只返回 size 条（`SearchPhaseController.java:308-312`）。

三个 collector 分支（`QueryPhaseCollectorManager.java:214-302`）：

| 场景 | collector | 分片收集数 |
| ---- | ---- | ---- |
| 普通查询（size>0） | `TopScoreDocCollectorManager` / `TopFieldCollectorManager`（**Lucene 类**，`:456-460`） | from+size |
| scroll | `forScroll` 分支 | 仅 size（`:285`） |
| size=0 | `EmptyHits` + `PartialHitCountCollector`（只计数，`:346-404`） | 0 条文档 |

`terminate_after` 每分片独立计数（`QueryPhaseCollector.java:335-364`，`GlobalTerminateAfterChecker` 内 `AtomicInteger`），且计数点在 `collect()` 里、post_filter 之后（`:246-252` 注释原文 "terminate_after is purposely applied after post_filter"）。

## reduce：归并与分批

协调节点归并入口 `SearchPhaseController.sortDocs`（`:100-176`），单分片且 from==0 时直接返回不 merge（`:154-156`），多分片走 Lucene 的 `TopDocs.merge`（priority queue 大小为 topN）。

**分批 partial reduce**：`QueryPhaseResultConsumer.java:135` 决定批量大小：

```java
batchReduceSize = (hasAggs || hasTopDocs) ? Math.min(request.getBatchedReduceSize(), expectedResultSize) : expectedResultSize;
```

`batchedReduceSize` 默认 **512**（`SearchRequest.java:65` `DEFAULT_BATCHED_REDUCE_SIZE`）；数据节点在发送 query phase 结果前也会做一次 final partial reduce（`:369-371`）——这是「聚合结果先在一部分分片间合并再回传」的优化，减少协调节点内存峰值。并发扇出上限 `DEFAULT_MAX_CONCURRENT_SHARD_REQUESTS = 5`（`SearchRequest.java:106`）。

## DFS：为什么打分能跨分片比较

两个类，分工与多数教程的描述相反：

- **shard 侧**：`org.elasticsearch.search.dfs.DfsPhase`（`server/.../search/dfs/DfsPhase.java:80-191`）用匿名 `IndexSearcher` 重写 `termStatistics()/collectionStatistics()` 拦截统计请求，收集本分片每个 term 的 docFreq/totalTermFreq 与每个 field 的 CollectionStatistics；
- **协调侧**：`org.elasticsearch.action.search.DfsQueryPhase`（`:189-244`）把各分片统计**求和**，随 query 请求下发。

注入方式：`SearchService.executeQueryPhase` 调 `readerContext.setAggregatedDfs(request.dfs())`（`server/.../search/SearchService.java:1416`），`ContextIndexSearcher` 重写 `termStatistics()/collectionStatistics()/docFreq()/totalTermFreq()` 优先返回全局值（`:602-653`）。

不打 DFS 时，各分片用**本地** idf 打分，同一文档在不同分片得分不可比；DFS 用全局词频统一 idf，代价是多一轮广播。kNN 搜索强制走 DFS（`TransportSearchAction.java:836-841`）。

## Fetch 阶段：11 个子 phase 的固定顺序

`FetchPhase` 只保存注入的数组并在末尾追加 `InnerHitsPhase`（`server/.../search/fetch/FetchPhase.java:81-84`）；权威注册顺序在 `SearchModule.java:1063-1078`：

```
1  ExplainPhase          8  SeqNoPrimaryTermPhase
2  StoredFieldsPhase     9  MatchedQueriesPhase
3  FetchDocValuesPhase  10  HighlightPhase
4  ScriptFieldsPhase    11  FetchScorePhase
5  FetchFieldsPhase     12  （插件追加的 subphase）
6  FetchSourcePhase     13  InnerHitsPhase（固定最后）
7  FetchVersionPhase
```

执行即数组顺序（`FetchPhase.java:434-436`）。值得注意的排序意图：`StoredFieldsPhase` 在前（先取回 stored 字段）；`FetchDocValuesPhase` 在 script_fields 之前（doc_values 已可取）；`FetchSourcePhase` 被刻意放在 fetch fields **之后**，以便把需要拷贝进 `_source` 的元数据字段（如 `_inference_fields`）一并处理（`SearchModule.java:1072-1073` 注释）。

size=0 时 fetch 短路：`FetchPhase.java:181-188`（`docIdsToLoad == null || length == 0` 直接返回空 hits）；协调节点更彻底——无聚合/suggest/kNN 且 `track_total_hits=accurate` 时换 `CountOnlyQueryPhaseResultConsumer` 只累加总数（`SearchPhaseController.java:658-670`）。

## preference：五种路由偏好

`Preference.parse`（`server/.../cluster/routing/Preference.java:14-71`）只认 5 种，分片/副本选择在 `OperationRouting.java:242-307`：

| preference | 行为 |
| ---- | ---- |
| `_shards:1,2` | 只查指定分片，不匹配返回 null；支持 `\|` 链式回退 |
| `_prefer_nodes:node1,node2` | 优先指定节点，不可用则回退任意副本 |
| `_local` | 优先本地节点副本 |
| `_only_local` | **只**用本地节点副本，没有则失败 |
| `_only_nodes:attr1,attr2` | 只查带指定 `node.attr.*` 的节点 |

**没有 `_primary`**——preference 选副本不选主从，ES 没有「强制读主分片」的 preference 值。

## scroll 与 PIT 的内部

scroll 没有查询包装类（`ScrollQuery` 不存在）：首次请求整体存入 `LegacyReaderContext`（`SearchService.java:1662-1670`），每批次**重跑完整 query**、`from` 递增（`processScroll`，`:2407-2411`），定位优化靠 `ScrollContext.lastEmittedDoc` 构造 `SearchAfterSortedDocQuery` 提前终止（`QueryPhase.java:182-202`，仅当 sort 是 index sort 前缀时生效）。

上下文清理：`SearchService.Reaper` 内部类（`:2486-2518`）按 `search.keep_alive_interval`（默认 **1m**）扫描过期 context 并 `freeReaderContext`；并发上限 `search.max_open_scroll_context` 默认 **500**。默认 keep_alive 5m、上限 24h（`SearchService.java:192-208`）。

PIT 走独立路径：`openReaderContext`（`:1761-1830`）先 `checkKeepAliveLimit`（超 `search.max_keep_alive` 报错），经 `shard.acquireExternalSearcherSupplier` **固定一个 searcher**，`PitReaderContext` 与 `searcherId` 绑定——这是 PIT 保证「查询期间索引不变」的方式：后续 search_after 复用同一 reader。

## 聚合与 eager_global_ordinals

- per-shard 聚合在 query phase 内执行（`AggregationPhase.preProcess` 创建 `AggregatorCollector`），多 slice 时节点内先 partial reduce（`AggregatorCollectorManager.java:44-55`），协调节点最终归并（`QueryPhaseResultConsumer.java:481-488`，统一入口 `InternalAggregations.topLevelReduce`）；
- terms 聚合用 global ordinals（`GlobalOrdinalsStringTermsAggregator.java:61-202`）：按段取 `globalOrdinalsValues` 后映射回 term 值，避免字符串比较；
- `eager_global_ordinals` 是 **mapping 参数**（keyword/text/flattened/join，默认 **true**，`KeywordFieldMapper.java:210-215`），代价在 reader 打开时前移：`IndexWarmer.java:120-160` 对 eager 字段执行 `loadGlobal` 预热。所以它的真实代价是 **refresh/新 reader 打开时的 CPU/IO**，不是查询本身——把它当聚合参数理解会找错优化位置。

## 关键默认值表

| 配置/常量 | 默认值 | 定义处 |
| ---- | ---- | ---- |
| `SearchContext.DEFAULT_TRACK_TOTAL_HITS_UP_TO` | 10000 | `server/.../search/internal/SearchContext.java:74` |
| `SearchRequest.DEFAULT_BATCHED_REDUCE_SIZE` | 512 | `SearchRequest.java:65` |
| `SearchRequest.DEFAULT_MAX_CONCURRENT_SHARD_REQUESTS` | 5 | `SearchRequest.java:106` |
| `action.search.shard_count.limit` | **Long.MAX_VALUE** | `TransportSearchAction.java:156-162` |
| `action.search.pre_filter_shard_size.default` | 128 | `TransportSearchAction.java:164-169` |
| `search.default_keep_alive` / `max_keep_alive` | 5m / 24h | `SearchService.java:192-203` |
| `search.keep_alive_interval` | 1m | `SearchService.java:204-208` |
| `search.max_open_scroll_context` | 500 | `SearchService.java:297-303` |
| `search.query_phase_parallel_collection_enabled` | true | `SearchService.java:266-271` |
| `search.fetch_phase_chunked_enabled` / `max_in_flight_chunks` / `target_chunk_bytes` | true / 3 / 1MB | `SearchService.java:273-295` |
| `SearchService.DEFAULT_SIZE` / `DEFAULT_FROM` | 10 / 0 | `SearchService.java:366-367` |

`track_total_hits` 默认 10000 的含义：命中超过 1 万时 `hits.total` 是一个「≥10000」的关系值（除非显式 `track_total_hits: true` 或 false）。scroll 场景会被强制覆盖为 accurate（`SearchRequest.java:871-879`）。

## 陷阱清单

| 说法 / 做法 | 9.5.5 真相 |
| ---- | ---- |
| 每分片只返回 size 条 | 返回 from+size；scroll 每批每分片才是 size |
| `terminate_after=10` 全局最多 10 条 | 每分片独立计数 10；且在 post_filter 之后 |
| `size=0` 不执行查询 | query phase 照常执行（只计数），fetch 才短路 |
| `action.search.shard_count.limit` 默认 10000 | 默认 Long.MAX_VALUE，无实际限制 |
| preference 有 `_primary` | 只有 5 种，无 `_primary` |
| scroll 是增量查询 | 每批重跑完整 query，靠 `SearchAfterSortedDocQuery` 提前终止 |
| `eager_global_ordinals` 是聚合参数 | 是 mapping 参数；代价在 reader 预热而非查询 |
| DFS 有 `setTermStatistics` 接口 | 实际是 `setAggregatedDfs(AggregatedDfs)` |
| fetch 子 phase 有 SourcePhase/VersionPhase 等名 | 实际 `FetchSourcePhase`/`FetchVersionPhase` 等 11+1 个，顺序固定 |

## Links

- [Elasticsearch（枢纽页）](/docs/CS/Framework/ES/ES.md)
- [Query DSL：查询两阶段与分页](/docs/CS/Framework/ES/Query_DSL.md)
- [Cluster：集群与选举](/docs/CS/Framework/ES/Cluster.md)
- [Replication：写入与复制协议](/docs/CS/Framework/ES/Replication.md)
- [Thread Pools：线程池模型](/docs/CS/Framework/ES/Thread_Pools.md)

## References

1. [Elasticsearch Reference - Search execution](https://www.elastic.co/guide/en/elasticsearch/reference/current/search-execution.html)
2. [elastic/elasticsearch v9.5.5 源码](https://github.com/elastic/elasticsearch/tree/v9.5.5)
