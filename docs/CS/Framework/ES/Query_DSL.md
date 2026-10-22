## Introduction

本篇讲 Elasticsearch 的查询：两阶段（Query Then Fetch）的完整流程、filter 与 query 上下文、核心查询语义与分页手段。

**版本基线：Elasticsearch 9.5.5**（Lucene 10.5.1）。结论均标注 `文件:行号`，可回源码反查。

> [!IMPORTANT]
> **先打破三个直觉**：① 查询不止「Query / Fetch 两个阶段」——9.x 默认还有 **can_match 预过滤阶段**，可在扇出前把不可能命中的分片整个跳过；② `index.write.wait_for_active_shards` 默认是 **1**，不是 all——默认配置下写成功不代表副本已同步；③ scroll 和 PIT 的 `keep_alive` **没有默认值**，不传直接报错。

事实来源：Elasticsearch 源码 v9.5.5（`elastic/elasticsearch` tag `v9.5.5`）。

## 查询两阶段：Query Then Fetch

默认 `search_type` 是 `QUERY_THEN_FETCH`（`SearchType.java:36` `public static final SearchType DEFAULT = QUERY_THEN_FETCH`）。完整流程：

```
客户端 → 协调节点（任意节点均可充当）
  ├─ can_match 预过滤（9.x 默认开启，见下）
  ├─ Query 阶段：广播到相关分片（主或副本，负载均衡）
  │     每个分片本地查询 → 返回 Top N 的 doc id + score（不含原文）
  ├─ 协调节点归并排序 → 全局 Top N doc id
  └─ Fetch 阶段：按 doc id 去对应分片取 _source → 组装返回
```

- Query 阶段实现：`org/elasticsearch/search/query/QueryPhase.java:53-75`；Fetch 阶段：`org/elasticsearch/search/fetch/FetchPhase.java:70-75`；
- 返回「doc id + score 而非原文」是两阶段的核心：广播阶段只传轻量结果，省带宽；
- `DFS_QUERY_THEN_FETCH` 仍然存在（先取各分片词频统计再打分，更准但更慢）；**kNN 向量搜索会强制切到 DFS**（`TransportSearchAction.java:836-841` `adjustSearchType`）。

### 9.x 新增：can_match 预过滤

`CanMatchPreFilterSearchPhase.java:50-63` 描述的机制：在扇出前把查询 rewrite 到各分片，**能确定改写为 match-none 或按主排序 min/max 排除的分片直接不查**。触发条件（`TransportSearchAction.java:205-2074` `shouldPreFilterSearchShards`）：

- `search_type` 必须是 `QUERY_THEN_FETCH`（DFS 不做预过滤）；
- `pre_filter_shard_size < numShards`；
- 查询可改写为 match-none，或存在主排序可做 min/max 剪枝。

预过滤的分片数由 `action.search.pre_filter_shard_size.default` 控制，默认 **128**（`SearchRequest.java:64`）。对「按时间过滤 + 分片数很多」的日志类查询，这是 9.x 的免费提速。

## filter 与 query 上下文

DSL 的每个子句都运行在两种上下文之一：

| | query context | filter context |
| ---- | ---- | ---- |
| 回答的问题 | 「这篇文档有多相关？」 | 「这篇文档是否匹配？」 |
| 打分 | 计算 `_score` | 不打分，`constant_score` |
| 可缓存 | 一般不缓存（每次重算） | 可被 ES 自动缓存（bitset） |
| 典型用途 | 全文搜索相关性排序 | 状态码、时间范围、精确匹配 |

9.x 的实现细节：filter 子句直接编译成 Lucene `BooleanClause.Occur.FILTER`（`BoolQueryBuilder.java:319`），**不存在** ES 自定义的 `ScoreWrapper` / `CachingWrapper` 包装类（全 server 代码零命中）——缓存行为完全由 Lucene 查询自身的缓存能力决定。

实践准则：**能进 filter 的就进 filter**（bool 的 `filter` 数组或 `constant_score` 包裹），只有真正需要相关性排序的子句才留在 query context。

## 核心查询语义

| 查询 | 语义 | 源码要点 |
| ---- | ---- | ---- |
| `term` | 精确词项查倒排，**不走 analyzer** | `TermQueryBuilder.java:217`；对 text 字段也直接查原词 |
| `terms` | 多词项 OR | `TermsQueryBuilder.java` |
| `match` | 先对查询词走字段的 search analyzer，再查 | `MatchQueryBuilder.java:162-166`；analyzer 为 keyword 时退化为 term |
| `match_phrase` | 短语匹配，词序与位置都要对 | slop 默认 **0**（`MatchQueryParser.java:110`） |
| `multi_match` | 跨多字段 match | — |
| `range` | 数值/日期范围 | filter context 常客 |
| `bool` | must / should / must_not / filter 组合 | `minimum_should_match` 默认 **null**（`BoolQueryBuilder.java:66`，即 Lucene 默认行为：仅 should 子句时至少命中 1 个） |
| `constant_score` | 包住 filter，统一打固定分 | `ConstantScoreQueryBuilder.java:127-130` |
| `function_score` | 自定义算分函数 | boost_mode / score_mode 默认都是 **MULTIPLY**（`FunctionScoreQueryBuilder.java:64-65`） |

`match` 对 text 字段会分词（查 "quick brown" 实际查两个词项的 OR/AND 组合），`term` 对 text 字段则是拿原词直接撞倒排——**对 text 字段用 `term` 查一个被分词器拆开的词，通常查不到**，这是最高频的 DSL 误用。

## 路由：文档落在哪个分片

`shard = Math.floorMod(Murmur3(routing), number_of_primary_shards)`：

- hash 函数是 **Murmur3**（`Murmur3HashFunction.java:16-17`，ES 2.0 起的默认）；
- `routing` 为空时用 `_id`（`IndexRouting.java:186-190,341-343`）；
- 取模用 `Math.floorMod` 保证非负（`RoutingFunction.java:26-38`）；
- 自定义 routing 可以把相关文档（如同一订单的全部子文档）钉在同一分片，避免查询扇出到全部分片；代价是分片可能倾斜。

主分片数在取模公式里，**这就是它创建后不能改的原因**（要改只能 scroll/reindex 到新索引，或用 split/shrink API 按规则变更）。

## 分页：三种手段的边界

| 手段 | 深度上限 | 适用场景 | 要点 |
| ---- | ---- | ---- | ---- |
| `from` + `size` | `from+size ≤ index.max_result_window`（默认 **10000**，`IndexSettings.java:146-152`） | 浅分页 | 超限直接报错；深分页协调节点要归并 `from+size` 条结果，内存与 CPU 都贵 |
| `search_after` | 无硬上限 | 深度翻页 / 游标 | 用上一页排序值当下页起点（`SearchAfterBuilder.java`）；要求排序键唯一（典型：`_id` 或时间+id tiebreaker） |
| `scroll` | 无硬上限 | **一次性遍历全量导出** | `scroll` 参数必传；上下文在服务端保持，不要用于实时用户翻页 |
| PIT（point-in-time） | 无硬上限 | 一致性快照 + search_after 组合 | `POST /{index}/_pit?keep_alive=1m`，`keep_alive` **必填无默认**（`OpenPointInTime.java:93-95`）；用完 `DELETE /_pit` |

> [!WARNING]
> scroll 与 PIT 的 `keep_alive` 都没有默认值——「scroll 默认保留 1 分钟」是不存在的说法，缺失 `keep_alive` 会在请求解析阶段直接报错（`RestSearchAction.java:272-275`、`RestOpenPointInTimeAction.java:63`）。

## 写入侧的等待语义（查询视角也要懂）

`index.write.wait_for_active_shards` 默认 **1**（`IndexMetadata.java:484-490`）：默认只等主分片本地写成功就返回，**不等副本**。请求级可用 `?wait_for_active_shards=all`（或 2、quorum）覆盖。这是「写入成功但随后主分片宕机可能丢刚写入数据」的根因——对一致性敏感的业务必须显式设。

## 陷阱清单

| 说法 / 做法 | 9.5.5 真相 |
| ---- | ---- |
| 查询只有 Query / Fetch 两阶段 | 默认还有 can_match 预过滤阶段（`QUERY_THEN_FETCH` 且分片数 > 128 时） |
| 对 text 字段用 `term` 搜词 | term 不走 analyzer，对分词后的 text 通常查不到；用 `match` 或查 `.keyword` |
| `wait_for_active_shards` 默认 all | 默认 1（只等主分片） |
| scroll 有默认 keep_alive | 无默认，必传 |
| `minimum_should_match` 有默认 1 | 默认为 null，行为交给 Lucene（纯 should 时至少命中 1 个） |
| `match_phrase` slop 有非零默认 | 默认 0（`MatchQueryParser.java:110`） |
| 深度分页靠调大 `max_result_window` | 默认 10000 只是上限；深翻页用 search_after / PIT |
| `function_score` 默认覆盖原分 | boost_mode/score_mode 默认都是 MULTIPLY |

## Links

- [Elasticsearch（枢纽页）](/docs/CS/Framework/ES/ES.md)
- [Cluster：集群、选举与查询两阶段](/docs/CS/Framework/ES/Cluster.md)
- [Mapping：数据模型与字段映射](/docs/CS/Framework/ES/Mapping.md)
- [Lucene：倒排、段与分片](/docs/CS/Framework/ES/Lucene.md)
- [Scripting / Painless](/docs/CS/Framework/ES/Script.md)

## References

1. [Elasticsearch Reference - Search](https://www.elastic.co/guide/en/elasticsearch/reference/current/search-search.html)
2. [Elasticsearch Reference - Paginate search results](https://www.elastic.co/guide/en/elasticsearch/reference/current/paginate-search-results.html)
3. [elastic/elasticsearch v9.5.5 源码](https://github.com/elastic/elasticsearch/tree/v9.5.5)
