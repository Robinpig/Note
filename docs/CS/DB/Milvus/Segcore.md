## Introduction

segcore 是 Milvus 的 C++ 数据平面。Go 侧掌管调度、元数据与 segment 生命周期，真正的数据——插入的行、删除标记、标量与向量索引——都住在 QueryNode 进程内 `internal/core/src/` 这一侧；Go 只通过 cgo 递进一份已经序列化好的查询计划与占位向量，再把结果取回。跨过这条边界的请求形态与 Go 侧视角见 [Query Path](/docs/CS/DB/Milvus/Query_Path.md)；本篇只看边界之内：数据结构、执行模型与翻译层。

segcore 里的 segment 同时以两种形态存在：还在从流中追数据的 growing 段，和已经固化、可只读并发访问的 sealed 段。两者共享同一套查询协议——同一个 `search_info`、同一棵计划树、同一套删除与时间戳语义——但底层数据结构完全不同：前者要支持无锁的并发追加，后者要支持按 chunk 的惰性加载、索引与原始数据共存。

一次段内查询不是「过滤、检索、可见性」三个独立阶段，而是在同一棵执行计划树的一次遍历里完成：`MvccNode` 决定哪些行在当前时间戳可见，`FilterBitsNode` / `IterativeFilterNode` 决定哪些行满足谓词，`VectorSearchNode` 决定哪些行与查询向量最近，中间结果以位图或列式 RowVector 在算子之间流动。

边界归位：索引算法与 Knowhere 见 [Index and Vector Engine](/docs/CS/DB/Milvus/Index_and_Vector_Engine.md)；binlog / 列组等存储格式见 [Storage Layer](/docs/CS/DB/Milvus/Storage_Layer.md)；growing 到 sealed 的落盘与 compaction 的 C++ 落点见 [Compaction and Lifecycle](/docs/CS/DB/Milvus/Compaction_and_Lifecycle.md)。

## Two Segment Implementations

`InsertRecord<is_sealed>` 是一个模板别名，指向两份不同实现：`InsertRecordGrowing` 与 `InsertRecordSealed`。`SegmentGrowingImpl` 与 `ChunkedSegmentSealedImpl` 分别持有一份，外加各自的 `DeletedRecord` 与索引结构。sealed 侧另有 `SegmentSealed` 接口承载 load、索引加载与 `PublishedSegmentState` 发布；growing 侧则把追流、追加与 ack 全留在自己手里。

| 维度 | SegmentGrowingImpl | ChunkedSegmentSealedImpl |
| :--- | :--- | :--- |
| 字段数据 | `ConcurrentVector<T>` 按 FieldId 分列，append-only | `ChunkedColumnInterface` 列，按 chunk 惰性加载 |
| 写入 | `PreInsert` 预留 offset 后多线程追加 | 只读，load 完成后发布快照 |
| PK 映射 | `OffsetOrderedMap` 有序 map 加读写锁 | `OffsetOrderedArray` 排序数组，可另建 `CompressedInt64PkArray` |
| 时间戳 | `ConcurrentVector<Timestamp>` | `TimestampData` 加 `TimestampIndex` |
| 删除 | `DeletedRecord<false>` 跳表加 mask | `DeletedRecord<true>` 跳表加 mask |
| 索引 | `IndexingRecord` 增量构建 interim index | `RuntimeResourceState` 里的 scalar / vector / ngram / text / json 索引 |
| 行可见性 | `AckResponder::GetAck` 连续水位 | 发布快照加各类就绪位图 |

### SegmentGrowingImpl

growing 段所有字段共享一个 `chunk_rows`（`SegcoreConfig::get_chunk_rows()`；有效值来自 `queryNode.segcore.chunkRows`，默认 **128**，由 Go 侧 `SegcoreSetChunkRows` 在初始化时注入，C++ 静态兜底才是 32 * 1024）。`ConcurrentVector` 把每列切成固定大小的块：append 只写当前块，读侧通过 `acquire_chunks()` 取一份 chunk 快照，块缓冲是固定大小的 deque，已有块的地址在并发插入下保持稳定。所以「多线程写入加并发查询」不需要全局列锁，PK 反查另走 `OffsetOrderedMap`（`std::map` 加 `shared_mutex`）。

写入协议是 `PreInsert(size)` 先预留一段 offset，插入完成后由 `AckResponder::AddSegment` 登记已完成的区间；ack 区间必须从 0 开始连续，缺口会卡住 `GetAck`，直到缺口补上——`GetAck` 即查询可见的行数上界，查询侧再按时间戳把可见行冻结成一个前缀，即计划里的 `active_count_`。`insert_record_` 之外，growing 段还持有 `IndexingRecord indexing_record_`（interim index）与 `DeletedRecord<false> deleted_record_`。

### ChunkedSegmentSealedImpl

sealed 段的数据全部经翻译层从对象存储加载，按 FieldId 收进 `RuntimeResourceState`：字段是 `ChunkedColumnInterface`（`ChunkedColumn` / `ChunkedColumnGroup`），与标量索引、向量索引、text / json / ngram 索引、`TimestampData`、`TimestampIndex` 并列。`PublishedSegmentState` 用 copy-on-write 把 schema、load info、runtime 与就绪位图（`field_data_ready_bitset`、`index_ready_bitset`、`binlog_index_bitset`）作为不可变快照原子发布：写入者克隆、修改、整体换新，读者每走一步取一次一致的快照。

PK 映射在 load 时从 PK 列一次构建：sealed 用 `OffsetOrderedArray`（`seal()` 后排序，二分查找），int64 主键的段可另建 `CompressedInt64PkArray` 做 offset 到 PK 的压缩反查（128 行一块，块内按最大差值位打包）。构建时对 PK 列按 chunk 先 `PrefetchChunks` 再顺序取数，避免逐个 chunk 阻塞在远端下载上。

发布还有一个跨线程请求闸门：`operation_gate_` 保证在线的 sealed `SearchResult` 还活着时，后台 reopen / load 不会提前替换快照（growing 段没有这层闸门）。v2 的 PK 索引与时间戳索引本身也走 CacheSlot 懒加载（`PkIndexCell`、`TimestampIndexCell`），不强行常驻内存。

chunk 是 sealed 侧加载、索引与释放的最小单元。块太大，首批结果前的等待、mmap 与淘汰的粒度都变粗；块太小，每 chunk 的索引元数据与调度开销上升——interim index 的 nlist 官方建议就取 sqrt(chunkRows)。`get_chunk_rows()` 同时被 growing 的块划分、interim index 参数生成、`SegmentChunkReader` 的游标步进复用。

## Insert and Delete Records

插入记录与删除记录分开存放。growing 的插入把每行拆进各字段的 `ConcurrentVector`：`timestamps_` 与 `row_ids_` 各一列，字段值各一列（`set_data_raw` 按预留 offset 写入）；sealed 的插入不保留逐行追加结构，只把 PK 抽出建 pk 到 offset 映射。时间戳的载体也不同：growing 始终是 `ConcurrentVector<Timestamp>` 加查询期前缀冻结，sealed 则改用 `TimestampData` 配 `TimestampIndex`，不再保留并发向量形态。

删除记录由 `DeletedRecord<is_sealed>` 承载：内部是 folly 的 `ConcurrentSkipList`，键为 `(Timestamp, Offset)`。插入删除时先由 `search_pk_func_` 把删除的 PK 翻译成段内 offset，跳过 `delete_ts <= insert_ts` 的迟到删除（正常路径下 PK 检索已用 `include_same_ts=false` 保证这一点），再写跳表并置位 `deleted_mask_`。入口分两个：`LoadPush` 用于加载批量删除，`StreamPush` 用于流式删除；后者在 `ENABLE_LATEST_DELETE_SNAPSHOT_OPTIMIZATION` 打开时维护 `(max_ts, bitset)` 的原子快照，查询可以直接读快照而不必每次扫跳表。

查询时的裁剪顺序是固定的：`MvccNode` 先做时间戳过滤（growing 按 `get_active_count(timestamp)` 冻结前缀，sealed 用 `TimestampIndex` 把时间戳换算成行范围），再 `mask_with_delete` 按 `deleted_mask_` 扣掉删除行。sealed 段还有一条 fast path：当 `query_timestamp >= get_max_timestamp()` 且没有 TTL 时，时间戳掩码整体跳过，只做删除 mask。

offset 与 rowID 的关系：段内 offset 是全段统一坐标——位图下标、删除掩码、结果里的 offset 都用它；growing 额外保留 `row_ids_` 列，因为 flush 时行标识必须随字段落到 binlog，不能丢。sealed 段对外回答「这一行是谁」靠 pk 与 offset 的双向映射。`DeletedRecord` 回调里拿到的 `SegOffset` 就是段内 offset。

`OffsetMap` 这族结构不止做等值查找：`find_range` 把 `Equal` / `GreaterThan` / `LessThan` 等 PK 谓词直接转成位图（PK 过滤下推），`find_first_n` / `find_first_n_element` 支持按 PK 顺序取前 N 个未命中行（growing 段同一 PK 的多个 offset 按时间戳从新到旧取，只认最新一条）。外部表场景用 `VirtualPKOffsetMap`：虚拟 PK 由段 id 与 offset 位拼出，映射零存储；时间戳也退化为常量（`init_timestamps_constant`），整段永远可见。选择率策略由 `BruteForceSelectivity` 决定：命中占比高时改用 PK 索引，低时暴力收集 PK 再排序。

growing 与 sealed 两侧都维护 `TimestampIndex`（分别挂在 `InsertRecordGrowing` 与 sealed 的 runtime 快照里），把时间戳快速收敛成行号上界，供 `get_max_timestamp` 与查询前缀冻结使用。

删除在两种段上的落点也不同：growing 段的删除只写跳表与 mask，数据列完全不动；sealed 段的删除在 `LoadDeletedRecord` 时成批灌入，`deleted_mask_` 的大小随段行数固定。物理回收统一交给 compaction，查询期只做 mask 裁剪。

## From PlanProto to Plan Nodes

Go 传来的 proto 计划由 `ProtoParser`（`query/PlanProto`）翻译：`CreatePlan` / `PlanNodeFromProto` / `RetrievePlanNodeFromProto` 是三个入口，表达式经 `ParseExprs` 变成 `expr::TypedExprPtr` 表达式树，解析时按字段 `DataType` 做类型检查；过滤谓词还有 BinaryExpr、BinaryRangeExpr、BinaryArithOpEvalRangeExpr 等形态。元素级查询走单独分支：`element_filter_expr` 与可选的文档级 `predicate` 分开解析。

计划树在 C++ 侧自底向上拼装，节点通过 `sources` 串成下游子树，节点种类以 `src/plan/PlanNode.h` 为准：`FilterBitsNode`（文档级谓词位图）、`ElementFilterBitsNode`（元素级过滤）、`IterativeFilterNode` 与 `IterativeElementFilterNode`（迭代检索的行级后过滤）、`MvccNode`（时间戳加删除的可见性）、`VectorSearchNode`（向量检索），以及结果成型用的 `ProjectNode`、`OrderByNode`、`AggregationNode`、`SearchGroupByNode`、`RescoresNode`、`RandomSampleNode`。

两条路径的节点顺序不同：非迭代路径在 `MvccNode` 之下先挂 `FilterBitsNode`、之上挂 `VectorSearchNode`，即先过滤后检索；iterator_v2 的迭代路径反过来，`VectorSearchNode` 在上、`IterativeFilterNode` 在后，行级过滤发生在检索之后。proto 里的 `search_info_`、`plan_options_`、`iterative_filter_execution`、`active_count_` 等都在这一步翻进 plan，执行层不再回看 proto。

TTL 的注入也在这层：字段级 TTL 打开时，即使没有用户谓词也会插入一个挂 `AlwaysTrueExpr` 的 `FilterBitsNode`，让表达式编译阶段在运行时挂上 TTL 位图过滤，而不是单独做一遍全段扫描。带命名空间的多租户集合另有一步：谓词解析完成后经 `MergeExprWithNamespace` 与命名空间条件合并，再进入节点构造。

## Execution Model

`SegmentInterface` 是 Go 侧唯一可见的段抽象，`SegmentInternalInterface` 在其上统一提供 `Search`、`Retrieve`、`mask_with_timestamps`、`mask_with_delete`、`get_active_count` 等入口，growing 与 sealed 各自实现——所以同一份 plan 不需要知道段处在哪一态。`SegmentInternalInterface::Search` / `Retrieve` 持段级读锁构造 `ExecPlanNodeVisitor`，再按 plan 根节点 `accept`；visitor 只有 `get_moved_result` 与 `get_retrieve_result` 两个出口，分别产出 `SearchResult` 与 `RetrieveResult`。实际执行收束到 `ExecPlanNodeVisitor::ExecuteTask`：把 `plan::PlanFragment` 与 `exec::QueryContext`（segment、query timestamp、active_count、TTL、查询配置）交给 `exec/` 的执行框架。

执行框架由 `Driver` 与 `Task` 组织，物理算子都是 `exec/operator/` 下的 `Phy*Node`：`PhyMvccNode`、`PhyFilterBitsNode`、`PhyElementFilterBitsNode`、`PhyIterativeFilterNode`、`PhyIterativeElementFilterNode`、`PhyVectorSearchNode`、`PhyProjectNode`、`PhyAggregationNode`、`PhyQueryOrderByNode`、`PhySearchGroupByNode`、`PhyRescoresNode`、`PhyRandomSampleNode`，以及汇总用的 `CallbackSink`。算子接口是 push-pull 混合的火山模型：`AddInput` / `NoMoreInput` 推入上游数据，`NeedInput` 表达还需输入，`GetOutput` 拉出结果，`BlockingReason` 表示等待异步资源；`SortBuffer`、`HashTable`、`VectorHasher` 是聚合与排序算子共享的运行时设施。

执行期的取消与等待也随这棵树流动：visitor 持有 `folly::CancellationToken`，取消从 cgo 边界一路带进算子；算子返回 `BlockingReason` 时由 `Driver` 决定重试时机，而不是占住调用线程忙等。

表达式也在这棵树里执行：`exec/expression/` 把 `expr::TypedExprPtr` 编译成可执行表达式，`EntryPool` 缓存表达式结果（压缩位图，Clock 淘汰）。过滤结果通常以位图在算子间流动，检索与排序结果则是列式 RowVector，最后由 visitor 装回 `SearchResult` / `RetrieveResult`。

## Vector Search Paths

分派规则：growing 段的 `vector_search` 直接进 `query::SearchOnGrowing`；sealed 段看字段的 `binlog_index_bitset`，索引就绪走 `query::SearchOnSealedIndex`（对 knowhere `VectorIndex` 直接 Query），否则走 `SearchOnSealedColumn`（在 `ChunkedColumn` 的 chunk 上扫描）。两条路径的索引检索都复用 `query::SearchOnIndex`，它内部先尝试 `PrepareVectorIteratorsFromIndex` 接管已有迭代器，再对 iterator_v2 用 `CachedSearchIterator` 分批，最后才落到 knowhere 的一次性 `Query`。sealed 侧的检索参数来自 `vec_binlog_config` 按字段生成的 `GetSearchConf`，即加载时按索引元数据推出来的临时检索配置。

`SearchOnGrowing` 的第一步是问 `indexing_record_.SyncDataWithIndex(field_id)`：为真说明 interim index 已可用且接管了原始数据，走索引检索；为假则暴力降级——以计划冻结的 `active_count_` 为可见行边界，先 `acquire_chunks()` 固定一份 chunk 快照，再逐块计算距离。快照的意义在于竞态：interim index 一旦接管原始数据，`try_remove_chunks` 随时可能回收 `ConcurrentVector` 的缓冲，快照保证本轮扫描以及返回给外层的迭代器不碰悬空指针。

interim index 即 growing 段的增量小索引：`IndexingRecord` 在插入侧按阈值触发构建，参数由 `VecIndexConfig`（`IndexConfigGenerator`）生成，构建阈值为 `max(max_index_row_count * build_ratio, nlist * 39)`；参数族来自 `queryNode.segcore.interimIndex.*`（build_ratio、nlist、nprobe、sub_dim、refine_ratio 等），经 `SegcoreSetEnableInterminSegmentIndex` / `SegcoreSetNlist` / `SegcoreSetNprobe` / `SegcoreSetSubDim` / `SegcoreSetRefineRatio` / `SegcoreSetIndexBuildRatio` 等初始化接口注入 `SegcoreConfig`（仅 targetVersion 与 memExpansionRate 两个 setter 带 InterimIndex 前缀）。

暴力分支自身也有小归并：参数先过 `CheckBruteForceSearchParam`，chunk 级结果打包成 `SubSearchResult` 再汇入段级 `SearchResult`；稀疏向量、BM25、MinHash 各有独立的距离计算与参数取值路径。sealed 段没有索引可用的字段在 `SearchOnSealedColumn` 里同样按 chunk 分批计算再归并 topk。段级结果里的 offset 再经 `FillTargetEntry` 换成对外返回的 PK 与距离，这一步仍在 C++ 内完成。

`CachedSearchIterator` 只服务 iterator_v2（有状态的分批检索）：它按数据形态有三种构造——knowhere 索引、chunk 列、growing 的 chunk 快照——内部为每个 chunk 持有 knowhere 迭代器或缓冲，用优先队列归并出下一批结果；`PinWrapper` 在迭代期间把 caching layer 里的 chunk 钉住，防止边迭代边被换出。没有它，跨 chunk 的有状态迭代每次 `NextBatch` 都要重开游标。

## Reduce and Result Assembly

单段内，一次向量检索的原始结果是 `SubSearchResult`（每个查询 topk 的距离与 offset 缓冲）；group-by 与元素级过滤在 C++ 侧完成（`SearchGroupByNode` 会把分组值随 offset 一起写回）。跨段归并在 v3.0.1 主要落在 Go 侧（`internal/util/reduce` 包，QueryNode 侧入口是 `searchReduce.ReduceSearchResultData`；`internal/util/segcore/reduce.go` 只是含 `StorageCost` 的小工具），C++ 侧负责 `ReduceHelper::PreReduce`：对每个段的 `SearchResult` 过滤无效行、按需做 Global Refine（截断加 refine，用占位组里的查询向量）、填充 PK，由 C 导出层 `PrepareSearchResultsForExport` 调用；随后 Go 把准备好的结果按 Arrow 导出并做最终归并。一句话：单段预处理与 PK 回填在 C++，跨段排序与截断在 Go。

导出侧还有两个细节：`PrepareSearchResultsForExport` 会把各段 `total_data_cnt_` 之和写进 `all_search_count`，作为 Go 侧归并的输入之一；group-by 标志、分组上限、扫描字节数等结果元数据由 `GetSearchResultMetadata` 一次读完，减少 cgo 往返。

## Translation Layer and Memory

翻译层把存储格式翻译成内存列，两侧的 translator 都实现 cachinglayer 的 `Translator<Cell>` 接口（按 cell 惰性加载并接受缓存与计量）。storagev1translator 面向 binlog：`ChunkTranslator` 把 binlog 翻成 `Chunk`，另有 `SealedIndexTranslator`、`InterimSealedIndexTranslator`、`TextMatchIndexTranslator`、`BsonInvertedIndexTranslator` 负责各类型索引的加载。storagev2translator 面向 manifest 与列组：`ManifestGroupTranslator`、`GroupChunkTranslator` 加载 `GroupChunk`，`SystemIndexTranslator` 处理系统字段。读取侧的 `SegmentChunkReader` 提供按 `(chunk_id, chunk_pos)` 的游标式 chunk 访问，`num_rows_until_chunk` 与 `get_chunk_by_offset` 负责 offset 与 chunk 坐标互转。

mmap 与缓存的接入点：`MmapManager` 决定字段是否走 mmap（`GetEnableGrowingMmap`、`GetVectorFieldEnableMmap`、`GetScalarFieldEnableMmap`）；growing 在 `append_field_meta` 时把 `MmapChunkDescriptor` 传给 `ConcurrentVector`，sealed 段持有自己的 `mmap_descriptor_`。字段列是否挂 mmap 还有细分条件：dense 向量列只有在 interim 索引类型为 SCANN 且向量字段 mmap 打开时才单独拿 descriptor，其余字段跟随 `GetEnableGrowingMmap` 总开关。caching layer 同时承担内存记账（`ChargeLoadedResource` / `RefundLoadedResource`）：`InsertRecordSealed` 的 PK 映射与时间戳、`DeletedRecord` 的跳表都按估算大小计费。

`SegcoreConfig` 的关键项：`chunk_rows`（有效默认 128，Go 注入；C++ 兜底 32 * 1024）、`nprobe`（有效默认 16，即 nlist/8；C++ 兜底 4）、interim index 一族与 `enable_interim_segment_index`，由 Go 侧 `queryNode.segcore.*` 参数经初始化接口写入；C++ 侧各处通过 `SegcoreConfig::default_config()` 读取这份全局配置。分配器方面：表达式缓存 `EntryPool` 的注释写明 jemalloc / tcmalloc 是 Milvus 的默认 allocator；jemalloc 统计经 `monitor/jemalloc_stats_c` 暴露给 Go 侧；PK 映射等结构使用 `TrackingStdAllocator` 自行记账，不依赖全局分配器统计。

读取路径上，sealed 字段列按 chunk 为单位取数（远端或本地缓存），单次只取用到的 chunk；cache 能容纳的 chunk 越多，查询中途触发的远端拉取就越少——这也是 chunk 行数不能一味调大的另一面。

## Links

- [Milvus](/docs/CS/DB/Milvus/Milvus.md)
- [Query Path](/docs/CS/DB/Milvus/Query_Path.md)
- [Write Path](/docs/CS/DB/Milvus/Write_Path.md)
- [Storage Layer](/docs/CS/DB/Milvus/Storage_Layer.md)
- [Index and Vector Engine](/docs/CS/DB/Milvus/Index_and_Vector_Engine.md)
- [Compaction and Lifecycle](/docs/CS/DB/Milvus/Compaction_and_Lifecycle.md)

## References

- [SegmentGrowingImpl.h](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/core/src/segcore/SegmentGrowingImpl.h)
- [segcore](https://github.com/milvus-io/milvus/tree/v3.0.1/internal/core/src/segcore)
- [plan](https://github.com/milvus-io/milvus/tree/v3.0.1/internal/core/src/plan)
- [query](https://github.com/milvus-io/milvus/tree/v3.0.1/internal/core/src/query)
- [exec](https://github.com/milvus-io/milvus/tree/v3.0.1/internal/core/src/exec)
- [Milvus v3.0.1](https://github.com/milvus-io/milvus/releases/tag/v3.0.1)
