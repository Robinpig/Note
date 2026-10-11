## Introduction

Milvus 2.x 的写链路以 DataNode 为中心：Proxy 把 DML 写进 DML channel，DataNode 经 msgdispatcher 消费、聚段、flush，再向 DataCoord 汇报。**3.0 把这条链路彻底改写**——所有变更统一落到一条 WAL 总线上，落盘的唯一执行者变成了持有该 WAL 的 **StreamingNode flusher**，DataNode 不再消费 WAL（`WatchDmChannels` 在 v3.0.1 是一个只打警告直接返回成功的 no-op，见 `internal/datanode/services.go`）。理解写入链路，关键不在"数据存到哪里"，而在"每一条变更都先变成一条 WAL 记录"。

这带来三个结构性变化：其一，**Proxy 写路径上不再有 segment 分配这一步**——`AssignSegmentID` 这个 RPC 本身仍然存在且被服务（`internal/datacoord/services.go` 的 `AssignSegmentID`，经 `internal/coordinator/mix_coord.go` 转发，客户端封装留在 `internal/flushcommon/broker/datacoord.go`），但 **Proxy 与 flusher 的生产写路径在 v3.0.1 都不再调用它**：segment 的创建与分配下沉到 StreamingNode 的 shard interceptor，由它本地生成 segment ID 并以 `CreateSegment` WAL 消息广播出去；其二，**写入的"号码机"是 MixCoord**，TSO、RowID、每条消息的 TimeTick 都向它取号；其三，**落盘与实时可见是 WAL 的两路消费**，对象存储上的 sealed segment 与 QueryNode 内存里的 growing segment 都只是 WAL 的物化投影。

本篇覆盖端到端写链路本身：Proxy 的处理与约束、DML 如何映射成 WAL 消息并保序、身份与时间戳从哪来、flusher 凭什么封口、索引何时由谁构建。**WAL 基础设施的内部机制**（LogStore 抽象、PChannel/VChannel、fencing、retention）见 [WAL and StreamingNode](/docs/CS/DB/Milvus/WAL_and_StreamingNode.md)；封口之后的 compaction、GC、L0 段见 [Compaction and Lifecycle](/docs/CS/DB/Milvus/Compaction_and_Lifecycle.md)；查询侧的实时读与一致性等待见 [Query Path](/docs/CS/DB/Milvus/Query_Path.md)；对象存储上的文件格式见 [Storage Layer](/docs/CS/DB/Milvus/Storage_Layer.md)。

## End-to-End Flow

一条 `insert` / `delete` / `upsert` 从客户端到对用户可见，经过七跳：

```
Client → Proxy（校验 / 限流 / 入队 / TSO+RowID 分配 / 主键哈希路由到 VChannel）
       → WALAccesser.AppendMessages → 持有目标 PChannel 的 StreamingNode
       → interceptor 链（redo → lock → replicate → timetick → shard → partialupdate）→ 后端持久化 + 分配 TimeTick
       → 双路消费：StreamingNode flusher 落盘   +   QueryNode growing 实时可见
       → DataCoord 感知 segment 生命周期 → seal → flush → 索引构建 DataNode 本地执行
       → QueryCoord 目标视图纳入新 sealed segment → 查询命中
```

| 跳 | 角色 | 为什么必须存在 |
| :--- | :--- | :--- |
| Proxy | 无状态接入层 | 校验、限流、把"行"切成按 VChannel 对齐的批次；它是用户语义与 WAL 字节流之间的翻译层 |
| StreamingNode | PChannel leader | WAL 实例的唯一持有者，落 TimeTick 与做 shard 管理只能由它来，否则无法保证全序 |
| WAL 后端 | Kafka / Pulsar / Woodpecker / RocksMQ | 唯一事实来源；持久化 + 总序都靠它，segment 与索引都可由它重放派生 |
| flusher | StreamingNode 内 | "channel 拥有者负责持久化"——落盘位置与 WAL 消费位置天然对齐，checkpoint 即恢复锚点 |
| QueryNode | 第二消费者 | growing segment 内存态实时更新，让提交后的写入立即可被 shard leader 读到 |
| DataCoord | 后处理调度 | 接收 flusher 汇报，驱动 seal / flush / compaction / 索引下发 |

## Proxy Request Chain

Proxy 是无状态的，gRPC 入口在 `internal/distributed/proxy/service.go`，落到 `internal/proxy/proxy.go` 的 `Proxy` 结构。一条写请求的处理顺序是**先约束、再取号、最后路由**：

1. **准入约束**：RBAC 与 schema 校验，随后 `RateLimitInterceptor` 做令牌桶限流。任何写任务都要先 `PreExecute`，失败即返回，不进 WAL。
2. **任务入队**：`task_scheduler.go` 维护四类队列——`ddQueue` 串行跑 DDL、`dmQueue` 并行跑 DML、另有查询队列与调度队列。**`ddQueue` 的串行化是保证同一 collection 上 DDL 顺序确定的关键**，DML 队列则不串行，靠后面的 WAL 总序补回顺序。
3. **取号**：`PreExecute` 阶段用 `rowIDAllocator` 分配 RowID 段、用 `tsoAllocator` 分配 TSO。
4. **路由与执行**：`Execute`（insert 走 `task_insert_streaming.go`）用 `repackInsertDataForStreamingService` 按主键哈希把行重新打包到各 VChannel，逐 channel/partition 构造 `message.MutableMessage`，调 `streaming.WAL().AppendMessages()` 提交，并用返回的 `MaxTimeTick` 回填会话级可见性水位。

delete 与 upsert 是同一套链路，区别只在构造的消息类型与 upsert 在 Proxy 侧多一步"先转 delete 再转 insert"的拆分；upsert 的主键去重**不在 Proxy 做**，而是把语义原样写进 WAL，由消费端处理。

## DML to WAL Mapping

VChannel 是 collection 的逻辑分片，PChannel 是 WAL 的物理流；**VChannel→PChannel 的绑定在 `CreateCollection` 时确定，但 RootCoord 只是触发者与记录者**：`internal/rootcoord/create_collection_task.go` 的 `assignChannels` 调 `snmanager.StaticStreamingNodeManager.AllocVirtualChannels`，后者经 `internal/coordinator/snmanager/streaming_node_manager.go` 转给 StreamingCoord 的 `balancer.AllocVirtualChannels`，最终落进 `balancer/channel/manager.go` 的 `ChannelManager.AllocVirtualChannels`——**真正挑 PChannel 的是它**：用 `sortAvailableChannelsByVChannelCount` 把可用 PChannel 按当前承载的 VChannel 数排序后取前 `shardNum` 个，即按 VChannel 数做公平分配；`vchannelfair` 策略负责的不是这一步，而是把这些 PChannel 放到哪些 StreamingNode 上。RootCoord 拿到返回的 VChannel 列表后用 `funcutil.ToPhysicalChannel` 剥出 PChannel，一并写进 collection 元数据。每个 shard 对应一个 VChannel。DML 消息按主键哈希落到某个 VChannel，再经该 VChannel 绑定的 PChannel 进入某条 WAL。

保序性的来源很朴素：**同一条 WAL 流内的消息由持有者单点追加、TimeTick 单调递增**，所以"按主键哈希路由 + 单点 append"就自然保证了同一行（同一主键必然落同一 VChannel）的所有变更在全序上保持发起顺序。跨 VChannel 之间没有用户可感知的相对顺序要求——这也是为什么 Proxy 的 DML 队列可以并行。

值得注意的是 v3.0.1 生产路径上真正串起来的 interceptor 链与骨架文档里的描述并不一致。以 `internal/streamingnode/server/walmanager/manager_impl.go` 的 `newInterceptorBuilders` 为准，append 调用顺序是 **redo → lock → replicate → timetick → shard → partialupdate**。`shard` 在前、`partialupdate` 在后的设计意图，源码注释写得很清楚：让 shard 校验排在 partial-update 写追踪之前，而两者都仍在 TimeTick 发布边界之内。这条链里**没有注册名为 txn 的顶层 interceptor**：`interceptors/txn` 包（`session.go` / `commit.go` / `txn_manager.go`）是被 lock、timetick、shard、replicate、partialupdate 共同引用的事务状态组件，事务语义因此散落在链的各个环节，而不是单列一层。

## Identity and Timestamp Assignment

写路径上有三个独立的水位，分配者各不相同：

| 水位 | 分配者 | 粒度 | 作用 |
| :--- | :--- | :--- | :--- |
| **TSO** | Proxy 经 MixCoord 的 `newTimestampAllocator(node.mixCoord, ...)` | 全局 | 事务与可见性排序的全局时间基准 |
| **RowID** | Proxy 的 `rowIDAllocator`，即 `allocator.NewIDAllocator(node.ctx, node.mixCoord, ...)` | 全局 | autoID 主键、行号；skip-timestamp 场景走 `metacache` 缓存 |
| **TimeTick** | StreamingNode 的 timetick interceptor，其 `TSOAllocator` 同样指向 MixCoordClient | PChannel 级 | 日志序号，即 MVCC 可见性边界 |

这张表里最关键、也最容易读错的一点：**TSO、RowID、TimeTick 三个号码最终都源自 MixCoord**。Proxy 的 `rowIDAllocator` 与 `tsoAllocator` 直接以 `node.mixCoord` 为后端；StreamingNode 每条消息的 TimeTick 又经 timetick interceptor 向 MixCoord 取 TSO。这意味着 **MixCoord 是写路径上被调用频率最高的单点之一**——3.0 把 RootCoord / DataCoord / QueryCoord / StreamingCoord 合并进单进程 MixCoord 后，进程内直连与 loopback 优化收益明显，正是因为取号频率太高。autoID 的连续段由 IDAllocator 在 Proxy 侧缓存批量预取，避免每行一次 RPC。

## Write Transactions and TimeTick

消息落 WAL 后端后，`LastConfirmedMessageID` 推进——从该位置往后读，后续消息的 TimeTick 严格更大。消费端用 `ReOrderByTimeTickBuffer` 按 TimeTick 重排，形成 MVCC 的可见性边界。

可选地，单 VChannel 内多条消息可包成一个写事务：`Begin` → 多次 `Append` → `Commit`，整体可见性以 `CommitTxn` 的 TimeTick 为边界——要么全部对读可见，要么都不可见。这个事务能力是 WAL append 协议之上的薄封装，不在 interceptor 链里单列一层（事务的完整生命周期、锁与未提交可见性见 [Transactions and Locking](/docs/CS/DB/Milvus/Transactions_and_Locking.md)）。

## Flush Entry Points and Seal Conditions

封口落盘的执行者是 StreamingNode flusher（`internal/streamingnode/server/flusher/`，`WALFlusherImpl`）。**`MILVUS_STREAMING_SERVICE_ENABLED` 由 `cmd/main.go` 恒置为 1**，它不是可关的灰度开关；DataNode 那条 2.x 经 msgdispatcher 消费 WAL 的旧路径在 v3.0.1 已无生产调用点。

flush 有三类入口，都落成 WAL 控制消息，由 flusher 的 `msg_handler_impl.go` 处理：

- **用户或系统显式 Flush**：`Flush` / `ManualFlush` / `FlushAll` 控制消息进 WAL，触发 `HandleFlush` / `HandleManualFlush`，flusher 调 writebuffer 的 `SealSegments` 与 `FlushChannel`。
- **growing 段满自动封口**：达到 seal 条件时由 WAL 的 **shard interceptor** 发 `FlushMessage`——`internal/streamingnode/server/wal/interceptors/shard/shards/segment_flush_worker.go` 用 `NewFlushMessageBuilderV2` 把它 append 进 WAL；flusher 侧的 `msg_handler_impl.go` 只是消费方（`HandleFlush`）。flusher 只在一种遗留场景下自己发：恢复时 `flusher_components.go` 为 `SegmentsNotCreatedByStreaming` 补发 `FlushMessage`。
- **DataCoord 侧推进**：`startFlushLoop` / `postFlush`（`internal/datacoord/server.go`）把 segment 状态从 Flushing 推进到 `Flushed`，并触发后续索引或压缩。

落盘流水线复用 `flushcommon`：`writeNode` 缓冲进 `writebuffer.BufferManager`（insert/delta/stats buffer），`SyncManager.SyncData` 异步写 binlog 到对象存储，`SaveBinlogPaths` 上报 DataCoord，checkpoint 由 `ChannelCheckpointUpdater` 写回 RecoveryStorage。

| 配置键 | 默认值 | 含义 |
| :--- | :--- | :--- |
| `dataCoord.segment.maxSize` | `1024` MB | growing 段封口目标大小，与 `sealProportion` 共同决定是否封口 |
| `dataCoord.segment.diskSegmentMaxSize` | `2048` MB | 建 Disk 索引的 collection 的段上限 |
| `dataCoord.segment.sealProportion` | `0.12` | 相对 `maxSize` 的最小封口比例 |
| `dataCoord.segment.sealProportionJitter` | `0.1` | 封口比例抖动率，实际生效比例**向下**浮动，如 `0.12` 对应 `0.108~0.12` |
| `dataNode.segment.insertBufSize` | `16777216` B | 内存中缓冲的 binlog 文件大小阈值 |
| `dataNode.segment.deleteBufBytes` | `16777216` B | 单 channel 删除缓冲上限 |
| `dataNode.segment.syncPeriod` | `600` | buffer 非空时的周期 sync |
| `dataNode.memory.forceSyncWatermark` | standalone `0.2`，其余形态 `0.5` | 内存水位达到即强制 sync，`forceSyncEnable` 默认开启；代码默认值按部署形态分叉（`component_param.go` 里 standalone 分支为 `0.2`，else 分支为 `0.5`），`configs/milvus.yaml` 写的是 `0.5` |

## Index Build Trigger and Executor

**v3.0.1 里 IndexNode 不再是独立进程**。索引构建任务由 **DataNode 本地执行**：`types.DataNode` 接口同时实现 `datapb.DataNodeServer` 与 `workerpb.IndexNodeServer`，构建逻辑在 `internal/datanode/index/`，内部直接调 segcore 的索引构建 C++ 代码 `internal/core/src/indexbuilder/`。

触发在 DataCoord 侧，执行者是 `initIndexInspector` 建出的 `indexInspector`（`internal/datacoord/server.go`、`index_inspector.go`）：它的 `createIndexForSegmentLoop` 有三个事件源——`postFlush` 在 segment 落盘后把 segmentID 推给 `getBuildIndexChSingleton()`（开启 sort compaction 时改推 stats task 通道，由 `compaction_trigger_v2.go` 消费并触发排序 compaction，而未排序的段会被下发逻辑跳过，等排序完成后由 compaction 任务或下面的周期扫描接手）、`CreateIndex` 的 DDL 回调 `ddl_callbacks_create_index.go` 把 collectionID 推给 `notifyIndexChan`（为存量已 flush 段补建），以及按 `dataCoord.taskCheckInterval` 周期扫描「已 flush 且仍未建索引」的段兜底。拿到段后 `createIndexesForSegment` 逐个索引调 `createIndexForSegment`：分配 buildID、写 `SegmentIndex` 元数据，再 `scheduler.Enqueue(newIndexBuildTask(...))` 投进 DataCoord 的全局任务调度器。`build_index_policy.go`（`buildIndexPolicy` / `defaultBuildIndexPolicy`）在 v3.0.1 是**全库零引用的遗留死代码**，不参与任何下发。任务落到 DataNode 本地执行，索引文件写对象存储，供 QueryNode 加载。标量索引与向量索引在此同构处理；具体索引类型与 Knowhere 的算法边界见 [Index and Vector Engine](/docs/CS/DB/Milvus/Index_and_Vector_Engine.md)。

## DDL Broadcast Path

DDL/DCL 走的是另一条总线——**广播**。Proxy 的 `ddQueue` 串行化 DDL，保证同 collection 的顺序确定；MixCoord 内的 RootCoord 构造广播消息，交给 StreamingCoord 的 `Broadcaster`（`internal/streamingcoord/server/broadcaster/`）跨所有相关 PChannel 含 CChannel 原子写入 WAL，ACK 后再回调落元数据（如 `createCollectionShard`）。广播的原子性与幂等性由 broadcaster 保证。DDL 不落 segment，落的是"让元数据与 WAL 一致"这件事，细节归 [WAL and StreamingNode](/docs/CS/DB/Milvus/WAL_and_StreamingNode.md)。

## Growing to Sealed Visibility

写入成功后用户能立刻"读到自己的写"，靠的不是等 flush，而是 WAL 的第二路消费者：QueryNode 实时消费同一 WAL，把数据维持成内存态的 growing segment，shard leader 的 delegator 提供一致读。**落盘路径与实时可见路径是分离的**——flusher 异步把 growing 物化成对象存储上的 sealed segment，QueryCoord 的 CurrentTarget 把新 segment 纳入后才对"任意 QueryNode 可加载"成立。这条可见性链路在查询侧展开，见 [Query Path](/docs/CS/DB/Milvus/Query_Path.md)。

## Links

- [Milvus](/docs/CS/DB/Milvus/Milvus.md)
- [WAL and StreamingNode](/docs/CS/DB/Milvus/WAL_and_StreamingNode.md)
- [Query Path](/docs/CS/DB/Milvus/Query_Path.md)
- [Storage Layer](/docs/CS/DB/Milvus/Storage_Layer.md)
- [Compaction and Lifecycle](/docs/CS/DB/Milvus/Compaction_and_Lifecycle.md)
- [Index and Vector Engine](/docs/CS/DB/Milvus/Index_and_Vector_Engine.md)

## References

- [Milvus v3.0.1 proxy.go](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/proxy/proxy.go)
- [Milvus v3.0.1 task_insert_streaming.go](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/proxy/task_insert_streaming.go)
- [Milvus v3.0.1 walmanager manager_impl.go](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/streamingnode/server/walmanager/manager_impl.go)
- [Milvus v3.0.1 shard interceptor](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/streamingnode/server/wal/interceptors/shard/shard_interceptor.go)
- [Milvus v3.0.1 flusher msg_handler_impl.go](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/streamingnode/server/flusher/flusherimpl/msg_handler_impl.go)
- [Milvus v3.0.1 datanode services.go](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/datanode/services.go)
- [Milvus v3.0.1 datanode index directory](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/datanode/index)
- [Milvus v3.0.1 core indexbuilder directory](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/core/src/indexbuilder)
- [Milvus v3.0.1 configs milvus.yaml](https://github.com/milvus-io/milvus/blob/v3.0.1/configs/milvus.yaml)
- [Milvus v3.0.1 streamingcoord broadcaster directory](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/streamingcoord/server/broadcaster)
