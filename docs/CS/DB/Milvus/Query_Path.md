## Introduction

Milvus 3.0 的查询链路是一个**两级模型**：Proxy 是无状态的接入与汇聚层，QueryNode 是唯一的执行层，中间由 QueryCoord 决定「哪些数据此刻必须在哪些节点上可读」。理解这条链路的关键不在于 RPC 调用顺序，而在于三个彼此咬合的设计决定：

1. **数据双态**。同一份数据同时以 **growing segment**（QueryNode 内存态，实时消费 WAL 维持）和 **sealed segment**（对象存储，按目标视图加载）两种形态服务查询。查询必须同时命中两者再去重合并，这才需要「一个 shard 有一个协调点」的结构。
2. **shard leader 聚合**。每个 VChannel 在每个 replica 内有且只有一个 leader，即某个 QueryNode 上的 `shardDelegator`。全集群对该 shard 的查询只发给 leader，由它按自身 `distribution` pin 出的 `SnapshotItem` 把子任务分给同 replica 的其他 QueryNode 并合并结果——把「任意节点查任意分片」的 N×M 全互联压成每 shard 一个协调点，故障转移也天然落在 replica 内部。
3. **目标视图驱动**。QueryCoord 不直接对 QueryNode 下「查什么」的指令，只维护 target（期望的 segment / channel 分布），由差异检查器把「期望减实际」翻译成 load/release 任务。**读什么**由 delegator 在查询瞬间决定，**装什么**由 QueryCoord 在后台决定，两件事解耦。

本篇边界：WAL 消息、TimeTick 与 tSafe 的内部产生机制见 [WAL and StreamingNode](/docs/CS/DB/Milvus/WAL_and_StreamingNode.md)；L0 段的产生与压缩见 [Compaction and Lifecycle](/docs/CS/DB/Milvus/Compaction_and_Lifecycle.md)；索引类型与 Knowhere 见 [Index and Vector Engine](/docs/CS/DB/Milvus/Index_and_Vector_Engine.md)；落盘格式见 [Storage Layer](/docs/CS/DB/Milvus/Storage_Layer.md)；写入侧如何把请求变成 WAL 消息见 [Write Path](/docs/CS/DB/Milvus/Write_Path.md)。

## End-to-End Flow

一次 `Search` 的完整旅程，可以按「谁在什么时刻做了什么决定」拆成五段：

| 阶段 | 执行者 | 关键动作 |
| --- | --- | --- |
| 准入与翻译 | Proxy | `dqQueue` 排队、schema 与参数校验、DSL 转 `SerializedExprPlan`、计算 `GuaranteeTimestamp` |
| 扇出 | Proxy | `GetShardLeaders` 发现每个 VChannel 的 leader，负载均衡策略选节点，按 shard 拆成多个子请求 |
| 定快照 | delegator | `speedupGuranteeTS` 微调 → `waitTSafe` 等到可见性水位 → 用 tSafe 填 `MvccTimestamp` → pin 可读 segment 快照 |
| 执行 | segcore | sealed 走索引与对象存储数据，growing 走内存态；表达式向量化求值，MVCC 位图裁行 |
| 汇聚 | delegator 与 Proxy | QueryNode 侧段间 reduce，Proxy 侧跨 shard reduce、group by、rerank、聚合、ORDER BY |

查询与检索共享同一套骨架：**Search** 走 `searchTask` 与 `SearchHistorical` / `SearchStreaming`，**Query** 走 `queryTask` 与 `Retrieve`。3.0 的服务端排序、聚合与分面检索把一部分计算下推进 segcore，再由 Proxy 做全局归并。

## Proxy Fan-out and Reduction

3.0 的 Proxy 只持有**一个** `mixCoord types.MixCoordClient`，2.x 时代四个协调器客户端的写法已不存在。`taskScheduler` 维护四条队列，`ddQueue` 串行处理 DDL、`dmQueue` 处理 DML、`dqQueue` 处理 DQL、`dcQueue` 处理 flush 一类数据控制；gRPC 协程入队后阻塞在 `WaitToFinish`，由调度协程 `Notify` 唤醒。

### Plan and Placeholder

`searchTask` 在 `PreExecute` 阶段把请求翻译成 segcore 可执行的计划：设置输出字段、partition 裁剪、rerank 输入字段、下推到 QueryNode 的函数链，再 `proto.Marshal` 成 `SerializedExprPlan`。待检索的向量不进 plan，而是走 `SearchInput` 的另一支 `PlaceholderGroup`——两者一个描述「怎么算」、一个描述「拿什么算」，这个分工决定了 cgo 边界的形状。

### Pushdown Boundary between Go and segcore

Proxy 只负责把请求编码成 plan，真正决定「哪些节点在 C++ 里建」的是 `PlanProto.cpp`。可下推的不是具体的算子清单，而是**只依赖单段数据、可并行的计算**：表达式过滤、向量检索（`VectorSearchNode`）、MVCC 裁行（`MvccNode`）、迭代过滤（`IterativeFilterNode`）、group_by 的每组截断（`SearchGroupByNode`）。需要全局视图的留在 Go：跨 shard topK、融合、最终聚合与全局排序。

query 侧的 plan 比 search 多两类节点，这正是「聚合与排序下推」的真实边界：

| 能力 | plan 字段 | segcore 侧节点 | Go 侧残留的工作 |
| --- | --- | --- | --- |
| 聚合与 GROUP BY | `QueryPlanNode` 的 `aggregates`、`group_by_field_ids` | `AggregationNode`，由 `BuildProjectAndAggregationNodes` 构建；avg 只产出 sum 与 count 两个部分态 | Proxy 的 `query_pipeline.go` 用 `reduce_by_groups` 跨段跨 shard 合并，`avg` 由 sum 与 count 相除补齐 |
| ORDER BY | `QueryPlanNode` 的 `order_by_fields` | `OrderByNode`，由 `BuildOrderByNode` 构建，执行时落到 `PhyQueryOrderByNode` 的 SortBuffer | Proxy 只归并各分片已排序的结果流，外加截断与字段重映射 |

search 侧则相反：plan 里没有聚合节点，也没有排序节点。`order_by_fields` 只是 search params 里的字符串，由 Proxy 的 `parseOrderByFields` 解析成 `OrderByField` 列表，排序完全发生在 Proxy 的 `orderByOperator`；排序字段常不在输出列里，`requeryOperator` 负责回表补齐。分面聚合同样全在 Proxy：`searchReduceOperator` 先完成跨 shard 归并，`aggregateOperator` 再对归并后的 `SearchResultData` 做层级遍历，逐层分桶、累计度量、处理 `top_hits` 与子聚合。所以 3.0 的下推是单向的——query 能推的尽量推，search 的聚合与全局排序一行都没进 segcore。

### VChannel Fan-out and Leader Selection

`shardclient.Manager` 调 `GetShardLeaders` 拿到 collection 每个 VChannel 的 leader 列表，结果按 collectionID 缓存在内存表里；缓存条目没有版本号，失效是显式的——`InvalidateShardLeaderCache` 在 shard leader 均衡、collection drop 与查询重试路径上删除条目，QueryCoord 侧的均衡与 load 变更也会主动调用它清缓存。`LBPolicyImpl` 在 `roundrobin_balancer` 与 `look_aside_balancer` 之间选择策略，从 leader 列表挑一个 QueryNode 直连其 `Search` / `Query`。被选中节点若已不再持有该 shard，会返回 `NotShardLeader`，Proxy 据此删除该 collection 的缓存条目并重试——这条错误路径就是 shard 迁移期间的实际收敛机制，`NotShardLeader` 一类 RPC 错误的分类与重试语义见 [Error Model](/docs/CS/DB/Milvus/Error_Model.md)。

服务端一侧的语义要更细：`GetShardLeaders` 只返回 `IsQueryVisible()` 的 replica，默认还跳过 leader 缺失或 `IsServiceable()` 为假的条目——任一 channel 在所有 replica 都拿不到可用 leader 时整体报 `channel not available`。调用方可以传 `WithUnserviceableShards` 跳过「全量装载完成」这道门禁，并把每个 leader 的 `Serviceable` 标志带回，自行决定是否使用尚未就绪的 leader——Proxy 的 `shardclient.Manager` 刷新 shard location 缓存时正是这样调用的。

### Reduce Pipeline

`PostExecute` 不是手写归并，而是一条算子流水线：`newSearchPipeline` 按请求特征装配 `searchReduceOperator`（跨 shard topK 合并）、`hybridSearchReduceOperator`、`elementBestCollapseOperator`、`aggregateOperator`、`rerankOperator`、`requeryOperator`、`organizeOperator`、`hybridAssembleOperator`、`orderByOperator`、`highlightOperator`、`lambdaOperator`、`endOperator`。GROUP BY 有 `reduceSearchResultDataNoGroupBy` 与 `WithGroupBy` 两条实现路径。ORDER BY 与聚合是「QueryNode 局部加 Proxy 全局」两阶段。

### Fusion Layer for Multi-Vector and Hybrid Search

混合检索在协议层就是 `IsAdvanced` 加一组 `SubReqs`：Proxy 把每个向量字段的检索编成子请求，delegator 在**同一份 pin 住的 segment 快照与同一个 tSafe** 下并行执行每个子请求，每个子请求内部先做 QueryNode 侧 `ReduceSearchOnQueryNode`，然后把**各子请求各自的**结果原样返回 Proxy。因此融合发生在 Proxy：`hybridSearchReduceOperator` 与 `hybridAssembleOperator` 对齐 nq，`rerankOperator` 执行加权或 RRF 之类的打分函数。需要 rerank 输入字段时，plan 会把 `rerankInputFieldIDs` 塞进输出，必要时触发 `requeryOperator` 回表补齐。

一处容易被误解的边界：打分函数链可以拆分——`plan.QuerynodeFunctionChains` 允许把部分链下推到 QueryNode 执行，其余留在 Proxy。两个约束是硬编码的：search iterator 不支持 function rerank，因为 rerank 改写了分数域，续查会误读；`order_by` 与 function rerank 互斥，因为排序准则冲突。

### Iterators and Continuation

迭代器在协议上只是一个布尔开关加一组游标参数，续查本身没有独立的执行路径，服务端每次请求都按参数重建续查现场。search 侧是 `IsIterator` 加 V2 的 `SearchIteratorV2Info`：客户端携带 `token`（首轮可缺省，服务端生成 UUID）、`batch_size` 与上一轮的 `last_bound`，响应回填 `SearchIteratorV2Results` 里的 token 与新的 `last_bound`，续查位置完全由这两个值重建。query 侧的游标是「主键 + 元素级 offset」：`query_iter_last_pk` 与 `query_iter_last_element_offset` 两个参数必须成对出现，Proxy 解析成 `QueryIteratorCursor` 放进 plan，续查在 segcore 按主键序推进，首屏响应通过 `SessionTs` 把快照时间戳交回客户端。

跨批一致性的做法是**锁快照时间戳**而非重放游标：续查批次把上一轮的时间戳经请求的 `GuaranteeTimestamp` 字段送回，Proxy 检测到非零值就同时写入 `MvccTimestamp` 与 `GuaranteeTimestamp`，delegator 复用同一快照、不再重新定水位。这也解释了 `speedupGuranteeTS` 为什么对迭代器一律跳过——shard 级 mvcc 加速会改变快照，破坏「所有批次同一视图」。其余差异都是协议层硬限制：search iterator V2 与 group_by、offset 互斥；query iterator 与 ORDER BY 互斥，游标推进依赖主键序。

## Consistency Levels and Guarantee Timestamp

一致性级别不是「要不要加锁」，而是**这次查询要等到哪个时间戳**。Proxy 的 `parseGuaranteeTsFromConsistency` 把级别折成一个数值，随请求下推：

| 级别 | guaranteeTs 取值 | 含义 |
| --- | --- | --- |
| `Strong` | `ts = tMax` | 等到本次请求覆盖的 channel 时间戳上界，`tMax` 由 `getMaxMvccTsFromChannels` 取最大 |
| `Bounded` | `tMax - CommonCfg.GracefulTime` | 默认级别，允许回退一段毫秒数换掉等待代价 |
| `Eventually` | `ts = 1` | 完全不等待，可能读到明显滞后的水位 |
| `Session` / `Customized` | 显式 `GuaranteeTimestamp` | 哨兵值 `strongTS` / `boundedTS` 走 `parseGuaranteeTs` 再折算，否则用调用方给的时间点 |

真正的等待发生在 delegator：`waitTSafe(ctx, guaranteeTs)` 阻塞到该 channel 的 WAL 消费水位越界，这正是「读已提交」的实现点——查询不会读到 guaranteeTs 之后写入的数据。等到之后，delegator 把返回的 tSafe 写进 `MvccTimestamp`，请求自带非零 mvcc ts 时保留原值供续查复用同一快照，这个 ts 就是整个 shard 本次查询的快照边界。外部表集合走 `skipStreamingForExternalTable` 分支，不订阅 WAL，直接把 tSafe 置为 `typeutil.MaxTimestamp`。

### GracefulTime and speedupGuranteeTS

`Bounded` 的回退量来自配置 `common.gracefulTime`，默认 5000 毫秒，生效点只有两处：`parseGuaranteeTsFromConsistency` 的 `Bounded` 分支与 `parseGuaranteeTs` 的哨兵 `boundedTS` 分支，两者都用 `AddPhysicalDurationOnTs(tMax, -ratio)` 从 tMax 的物理时间往回扣。它不引入任何锁，只是把等待目标从「追上最新」降成「追到约 5 秒前」。

反方向的调整发生在 delegator 的 `speedupGuranteeTS`，`Search`、`Query`、`QueryStream` 三个读入口都会先调它：它只作用于 `Strong` 且请求未自带 mvcc ts 的非迭代器读请求——先经 `GetLatestMVCCTimestampIfLocal` 读本地 WAL 的最新 mvcc 水位，若低于 guaranteeTs 就直接把它当等待目标。加速的道理是 Strong 真正要等的其实是「本地已确认写入的最新数据」，而这正是 mvcc 水位的定义，再等 tMax 属于多余。跳过加速的条件在源码里是硬编码的：外部表、迭代器（客户端不支持 shard 级 mvcc，加速会让不同批次落到不同快照）、非 Strong、请求已带非零 `MvccTimestamp`。`GetStatistics` 这类旁路读取只登记不加速。

同一次调用还会把 guaranteeTs 登记进 `latestRequiredMVCCTimeTick`，供 QueryNode 消费管道里的 empty timetick slowdowner 使用：无数据的空 TimeTick 平时被过滤掉以省 CPU，但只要有读者在等某个 ts，时间戳就必须放行到这个水位，否则 tSafe 永不推进、等待者全部卡死；delegator 启动追赶阶段该值直接取当前物理时间，保证装载尽快完成。

跨 shard 的一致性不靠分布式事务：每个 delegator 独立等待自己 channel 的水位，靠同一个 guaranteeTs 语义把各 shard 的时间上界对齐，Proxy 只做结果归并、不再二次校验可见性。TimeTick 与 tSafe 如何产生见 [WAL and StreamingNode](/docs/CS/DB/Milvus/WAL_and_StreamingNode.md)。

## QueryCoord Target Views

### Three Views

`meta/target_manager.go` 维护 collection 级的 `CurrentTarget` / `NextTarget` / `GlobalTarget`，底层结构是 `CollectionTarget` 映射表，每项含目标 segment 集合、DML channel 集合与 `TargetVersion`。`updateCollectionTarget` 拒绝版本不回退的写入，保证并发更新单调。DataCoord 的 checkpoint 或 flush 推进后，`UpdateCollectionCurrentTarget` 把 Next 提升为 Current，这个提升带时间戳，正是查询侧「只看到已封口数据」快照语义的协调端来源。

### Checkers and Tasks

差异检查器在 `checkers/`：`segment_checker.go` 负责 segment 的 load 与 release，`channel_checker.go` 负责 channel 订阅，`leader_checker.go` 维护 shard leader 结构，`balance_checker.go` 触发再均衡，`index_checker.go` 处理索引加载。`observers/` 负责观测与派发：`collection_observer.go`、`target_observer.go`、`replica_observer.go`、`resource_observer.go`、`leader_cache_observer.go` 把实际分布与 target 对齐，`task_dispatcher.go` 再去重并把任务交给 `task` 调度器执行。实际的节点分布记录在 `meta/dist_manager.go`、`segment_dist_manager.go`、`channel_dist_manager.go`。

### Balance and Replica

`balance/` 下有多套实现：`rowcount_based_balancer.go`、`score_based_balancer.go`、`channel_level_score_balancer.go`、`multi_target_balance.go`、`stopping_balancer.go`，在 segment 与 channel 两个粒度上做均衡。`meta/replica_manager.go` 管 replica：load 时按资源组创建 replica，**每个 replica 覆盖 collection 的全部分片**，replica 之间互为冗余，因此 `GetShardLeaders` 可以按 replica 过滤返回，Proxy 也能通过指定 replica 做读隔离。

### Why Not Direct Segment Assignment

直接分配意味着 QueryCoord 每次 flush、compaction、节点上下线都要重算并推送「该查哪些段」，查询路径被控制面抖动牵住。target 驱动把这件事切成两层：QueryCoord 只负责让「实际分布」逼近「期望分布」，收敛期间旧 target 依然可查；delegator 每次查询从 pin 住的 `distribution` 读出此刻真正可读的段。segment 换版、索引就绪、compaction 生效都表现为 target 版本推进，而不是查询协议变化。

## QueryNode ShardDelegator

### Distribution and Snapshot Pinning

每个 VChannel 一个 `shardDelegator`，持有该 shard 的分布 `distribution`（sealed 段的可读视图是其中的 `channelQueryView`）与全文检索用的 `IDFOracle`。这里的 `LeaderView` 是另一回事——它是 QueryCoord 侧 `meta/channel_dist_manager.go` 的分布类型，也是 QueryNode 上报给 QueryCoord 的载体，属控制面视角，delegator 查询时并不直接读它。`Search` 入口先做 `lifetime.Add(IsWorking)` 生命周期检查与 channel 归属校验，不属于本 shard 直接返回 `WrapErrChannelMisrouted`；随后 `distribution.PinReadableSegments(ratio, partitionIDs...)` 拿到三样东西：按节点分组成 `SnapshotItem` 的 sealed 段、本节点 growing 段、每个 sealed 段的行数，以及一个 `version`，查询结束时 `Unpin(version)`。**pin 而不是拷贝**是这里的核心：它保证同一次查询、以及混合检索的每个子请求，看到的段集合完全一致。

### Growing Segments and WAL Consumption

实时流水线在 `querynodev2/pipeline/`：delegator 经 msgdispatcher 订阅本 channel 的 WAL 流，`insert_node` 写 growing 段、`delete_node` 应用删除、`filter_node` 过滤过期数据。msgdispatcher 的唯一生产消费者就是 QueryNode。这条流水线推进的水位就是 tSafe，也就是上一节等待的对象。

### Deletion and L0

删除有三条来路，delegator 都要处理：WAL 流里的 delete 消息直接落 growing 段；已封存段的删除记在 L0 段与 delta log 里；远端 worker 上的段则通过 `deleteBuffer` 按时间戳缓存删除项，`List(since)` 与 `TruncateBefore(ts)` 让 worker 能增量拉取而不必每次重放。L0 段的加载路径是特殊的——它只随 channel watch 进来，`LoadSegments` 显式拒绝 L0，报「load L0 segment is not supported」；`addL0ForGrowing` 则把 L0 删除转发给 growing 段。L0 段本身如何产生与被压缩消化，见 [Compaction and Lifecycle](/docs/CS/DB/Milvus/Compaction_and_Lifecycle.md)。

### Dual-State Execution and Result Merging

`segments/search.go` 把一次检索拆成 `SearchHistorical`（sealed，对象存储数据加索引）与 `SearchStreaming`（growing，内存态，必要时用 interim index 加速），`retrieve.go` 处理按主键与标量查询。段间结果由 QueryNode 侧 reduce 归并成该 shard 的部分结果。sealed 段若不在 leader 本节点，`executeSearchSubTasks` 按 `SnapshotItem` 里的节点信息转发给同 replica 的 worker，收回后再合并——这才是跨节点扇出的位置。

一处**容易写反的点**：`delegator_twostage.go` 的 `twoStageSearch` 不是跨 replica 的两阶段聚合，而是**同 replica 内的过滤代价优化**——但它也**不限于 leader 本节点**：两个 Stage 都经 `executeSearchSubTasks` 按 `SnapshotItem` 分发，Stage 1 的过滤同样会转发到同 replica 远端 worker 上的 sealed 段。Stage 1 设 `FilterOnly` 与 `EnableExprCache` 只在 sealed 段跑过滤，收集 `FilterValidCounts` 得到真实选择率；Stage 2 用这份统计调整检索参数后正常执行，过滤位图由进程级 `ExprResCacheManager` 跨阶段复用。worker 版本过旧、统计不完整时直接回退单阶段路径。

## segcore and the cgo Boundary

`internal/core/` 是独立 C++ 工程，产出 `milvus_core`，经 `internal/util/segcore` 与 cgo 暴露给 QueryNode。本节讲边界上「传什么」，边界之内 C++ 侧的数据结构与执行模型（两种 Segment 实现、InsertRecord/DeletedRecord、PlanNode 求值与 reduce）见 [Segcore](/docs/CS/DB/Milvus/Segcore.md)。边界上只有三类东西值得过：

| 上传物 | 载体 | 说明 |
| --- | --- | --- |
| 计划 | `SerializedExprPlan` | `src/query/PlanProto.cpp` 把 proto 解析成物理算子树，Go 侧不参与表达式求值 |
| 向量 | `PlaceholderGroup` | C 侧以 `CPlaceholderGroup` 持有，避免大向量在 Go 堆上多次拷贝 |
| 位图 | 结果侧 `TargetBitmap` | 过滤、删除、MVCC 三个位图在 C++ 侧就地求交并回填 |

Go 与 C++ 的错误经 `HandleCStatus` 分类成 merr 哨兵，即 `merr.SegcoreError`，Go 上层不需要理解 C++ 异常语义。执行引擎在 `src/exec/operator/`，一条典型算子链是 `FilterBitsNode` → `MvccNode` → `ProjectNode`，向量检索前还有 `ElementFilterBitsNode`；pre-filter 与 iterative filter 的区别不在 `MvccNode` 与 `VectorSearchNode` 的相对次序——`PlanProto.cpp` 里两种模式下 `MvccNode` 都排在 `VectorSearchNode` 之前——真正的分野是 `search_info.iterative_filter_execution`：它为假走 pre-filter，过滤节点前置成 `FilterBitsNode` → `MvccNode` → `VectorSearchNode`；它为真则过滤节点后置，链变成 `MvccNode` → `VectorSearchNode` → `IterativeFilterNode`（元素级再补 `IterativeElementFilterNode`）。

**MVCC 如何裁行**：`PhyMvccNode` 对候选行集做两层掩码——`mask_with_timestamps(data, query_timestamp, collection_ttl_timestamp)` 把快照水位之后写入的行抹掉，`mask_with_delete(data, active_count, query_timestamp)` 把水位之前被删的行抹掉。sealed 段有一条快路径：无 TTL 且 `query_timestamp >= segment_->get_max_timestamp()` 时跳过时间戳掩码，只算删除掩码，全零则直接标记 `all_rows_visible`。快照 ts 由此在**行粒度**生效，段与段的可见性差异则留给上层的 target 与 pin 机制处理。

## Query-Side Resource Governance

**Resource Group 事实在 QueryCoord，不在 RootCoord**：`internal/querycoordv2/meta/resource_manager.go` 与 `resource_group.go` 持有 `ResourceGroup` 与 `rgpb.ResourceGroupConfig`，节点归属校验由 `CheckNodesInResourceGroup` 完成，replica 创建时绑定资源组。这与配额限流在 RootCoord 的 `QuotaCenter` 是两套东西，容易记混，运维视角的展开见 [Deployment and Ops](/docs/CS/DB/Milvus/Deployment_and_Ops.md)。

内存与装载失败的处理走「降级返回」而不是「报错」：`QueryNodeCfg.PartialResultRequiredDataRatio` 决定容许的数据缺口比例。取 1.0 时查询必须 `waitTSafe` 且分布可服务；小于 1.0 时 delegator 直接用当前 `GetTSafe()` 不再等待、并容忍缺失段，`PinReadableSegments` 也按这个比例判定分布是否可服务。代价是结果可能不完整，收益是单节点装载失败或内存压力不再放大成整条查询链路不可用。装载失败的节点与 collection 由 `meta/failed_load_cache.go` 记录，避免反复重试同一坏目标。QueryNode 侧的 mmap 与分层存储配置在 `internal/util/initcore`，索引层的缓存与 Warmup 见 [Index and Vector Engine](/docs/CS/DB/Milvus/Index_and_Vector_Engine.md)。

## Links

- [Milvus](/docs/CS/DB/Milvus/Milvus.md)
- [Write Path](/docs/CS/DB/Milvus/Write_Path.md)
- [WAL and StreamingNode](/docs/CS/DB/Milvus/WAL_and_StreamingNode.md)
- [Compaction and Lifecycle](/docs/CS/DB/Milvus/Compaction_and_Lifecycle.md)
- [Index and Vector Engine](/docs/CS/DB/Milvus/Index_and_Vector_Engine.md)
- [Shard](/docs/CS/DB/Shard.md)

## References

- [milvus-io/milvus v3.0.1 shardDelegator](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/querynodev2/delegator/delegator.go)
- [milvus-io/milvus v3.0.1 search reduce pipeline](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/proxy/search_pipeline.go)
- [milvus-io/milvus v3.0.1 QueryCoord target manager](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/querycoordv2/meta/target_manager.go)
- [milvus-io/milvus v3.0.1 two-stage search](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/querynodev2/delegator/delegator_twostage.go)
- [milvus-io/milvus v3.0.1 MvccNode](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/core/src/exec/operator/MvccNode.cpp)
- [milvus-io/milvus v3.0.1 PlanProto](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/core/src/query/PlanProto.cpp)
- [milvus-io/milvus v3.0.1 resource manager](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/querycoordv2/meta/resource_manager.go)
- [milvus-io/milvus v3.0.1 shard client LB policy](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/proxy/shardclient/lb_policy.go)
- [milvus-io/milvus v3.0.1 empty timetick slowdowner](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/util/pipeline/consuming_slowdown.go)
- [milvus-io/milvus v3.0.1 query pipeline](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/proxy/query_pipeline.go)
