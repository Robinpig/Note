## Introduction

Apache Lucene 是一个用 Java 编写的**高性能、全文检索库**，不是独立运行的服务，而是一个可嵌入的 jar 库。Elasticsearch 本身不直接实现索引/检索算法，而是在 Lucene 之上做了分布式、REST 接口、近实时写入、集群协调与运维封装。理解 ES 的很多行为（近实时、段合并、占用内存、删除是“假删除”）都要回到 Lucene 的存储模型。

Lucene 提供的核心能力：倒排索引、分词分析（Analyzer）、多种 Query、相关性打分（BM25/历史的 TF-IDF）、列式存储（Doc Values，用于排序/聚合）、以及基于不可变段的存储结构。Solr 与 Elasticsearch 同样构建在 Lucene 之上。

## Inverted Index

与传统数据库按“文档 → 字段值”组织的正排不同，**倒排索引（inverted index）**按“词项（term）→ 包含它的文档列表”组织，这是全文检索能做到毫秒级的根本：

- 写入时文本先经 **Analysis**（字符过滤 → 分词器 Tokenizer → Token Filter，如小写化、去停用词、词干提取）切成 term；
- 每个 term 维护一个 postings list：包含该 term 的文档 id 列表（还可存词频、位置、偏移，用于打分与短语查询）；
- term 词典本身排序存储（FST 等紧凑结构），可用二分/前缀快速定位；postings 用压缩的跳表/位集结构，便于求交并集（`AND`/`OR`）。

配套还有两类关键存储：

- **Doc Values**：列式、面向 docid 的正排结构，用于排序、聚合、script 字段访问（倒排不擅长“取某字段所有值”）。
- **stored fields / `_source`**：保存原始 JSON，用于 Fetch 阶段取回文档原文。

## Segment

**Segment（段）是 Lucene 索引的基本存储单位，且一经写入就不可变（write-once / immutable）**。这是 Lucene 最重要的设计：

- 一次写入先进入内存中的 **indexing buffer**，定时（`refresh`，ES 默认 1s）把缓冲区数据写成一个新的 segment，并打开一个可搜索的 reader——这就是 ES“近实时（NRT）”的来源：写入后默认最多 1 秒才可被搜到。
- 数据先写 **translog**（类似 WAL）保证未落盘段不丢；`flush` 时把段 fsync 到磁盘并清空 translog。
- 因为文件不可变，段文件可以构建成完全平衡的 KD-tree/词典，无需在线再平衡；缓存与并发控制也大大简化（reader 只读快照）。

### Delete and Update

不可变性带来的直接后果：

- **删除**不是真的从段里抹掉，而是在一个 `.liv` 位图里把该 doc 标记为 deleted，查询时过滤；
- **更新** = 旧文档标记删除 + 写入一篇新文档（本质是 delete + index）。

因此大量删除/更新后段里会堆积“死文档”，空间不会立即回收。

### Merge

随着 refresh 不断产生小 segment，Lucene 后台执行 **segment merge（段合并）**：把多个小段读出来、归并排序、丢弃其中被标记删除的文档，写成一个更大的新段，再原子替换旧段、删除旧文件。

合并的好处：减少段数量（避免打开过多文件/reader）、真正回收死文档占用的空间、让查询少遍历几个段。代价是显著的 CPU/IO 开销，写入洪峰时合并跟不上会导致段膨胀、甚至磁盘打满。ES 有 Tiered Merge Policy 与限流（`indices.store.throttle`、merge 调度）。

## Shard

Lucene 的单个索引受单机资源限制，ES 通过**分片（shard）**把索引水平切开：一个 ES index 拆成若干 primary shard，每个 primary shard 在物理上就是**一个独立的 Lucene 索引（一份完整的 Lucene 目录/段集合）**。

- Primary shard 承担写入，replica shard 是它的副本，承担读负载与容灾；
- 路由公式 `shard = hash(_routing) % number_of_primary_shards` 决定文档落到哪个分片，这也是**主分片数创建后不能随意改**的原因（会改变历史文档的路由）；
- 查询时由协调节点把请求扇出到相关分片，再做 Query Then Fetch 归并（见 [Cluster](/docs/CS/Framework/ES/Cluster.md)）。

可以把层级理解为：`ES Index → 多个 Shard（每个是一个 Lucene Index）→ 多个不可变 Segment → 倒排索引/Doc Values/Stored Fields`。

## Why It Matters for ES Operations

| 现象 | Lucene 根因 |
| ---- | ---- |
| 写入后 1 秒才可搜 | refresh 生成新 segment 的周期 |
| 删除不立即释放磁盘 | 段不可变，仅位图标记，靠 merge 回收 |
| 段合并占用 CPU/IO、磁盘水位告警 | 后台 merge 大段 |
| 堆外/文件系统缓存很关键 | 段文件不可变，非常适合 OS page cache |
| 聚合排序吃内存/磁盘 | Doc Values 列存 |
| 主分片数创建后不可变 | 路由取模依赖分片总数 |

## Links

- [Elasticsearch](/docs/CS/Framework/ES/ES.md)
- [ES Cluster 与 Query Then Fetch](/docs/CS/Framework/ES/Cluster.md)
- [OpenSearch](/docs/CS/Framework/ES/OpenSearch.md)

## References

1. [Apache Lucene Documentation](https://lucene.apache.org/core/documentation.html)
2. [Elastic Docs - Near real-time search / Translog / Segments](https://www.elastic.co/guide/en/elasticsearch/reference/current/near-real-time.html)
3. [Lucene Core - Index Reader / Segment Merge](https://lucene.apache.org/core/)
