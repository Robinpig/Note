## Introduction

向量库的账单和延迟，绝大部分不是写入路径决定的，而是**封口之后**这一段决定的。段（segment）在 Milvus 里同时是索引单位、加载单位和查询扇出单位：QueryCoord 按段把数据搬到 QueryNode，一次检索要对「每个 VChannel 上所有可见段」各打一发。封口太碎 → 扇出爆炸、每段一份索引和元数据；不合并删除 → 段里留着墓碑，结果要在查询侧现算位图；GC 保守 → 对象存储只涨不跌。这三件事分别对应 compaction、L0 删除段的消化、以及 garbage collection，全部由 **DataCoord** 调度。

本篇讲的是 DataCoord 视角下的 segment 生命周期：`Flushed` 之后到「文件真的从对象存储消失」之前发生的一切——状态机、compaction 类型与触发、L0 删除段、GC 判定、stats/analyze、clustering、TTL 的真实语义、批量导入。锚定 **v3.0.1**：这一版架构迁移剧烈，凡是与 2.x 资料冲突处，一律以 v3.0.1 源码为准。

边界：写入到封口（Proxy → WAL → StreamingNode flusher → `SaveBinlogPaths`）见 [Write Path](/docs/CS/DB/Milvus/Write_Path.md)；段内文件格式与 manifest 见 [Storage Layer](/docs/CS/DB/Milvus/Storage_Layer.md)；索引类型本身见 [Index and Vector Engine](/docs/CS/DB/Milvus/Index_and_Vector_Engine.md)；查询侧如何把删除位图叠到段上见 [Query Path](/docs/CS/DB/Milvus/Query_Path.md)。

一个贯穿全篇的判断法则：**配置项存在不等于它还生效**。要看消费方函数读的是哪个变量、默认值代码在哪。本篇里至少有三处踩到这个坑，都已标注。

## Segment State Machine

枚举是 `commonpb.SegmentState`（milvus-proto v3.0.1，共 8 个值）。下表只列 **DataCoord 元数据里真实会被写入**的状态与其写入方：

| 状态 | 谁写入、什么条件 |
| :--- | :--- |
| `SegmentStateNone` | 零值；只出现在 `isSegmentHealthy` 的排除判定里 |
| `NotExist` | v3.0.1 的 DataCoord 侧无写入方，仅作健康性排除 |
| `Growing` | `buildSegment` / `AllocSegment` RPC——StreamingNode flusher 收到 CreateSegment 消息后回 DataCoord 申请 |
| `Sealed` | 只有 `SegmentManager.tryToSealSegment` 与 `SealAllSegments` 会写，而 `SealAllSegments` 的调用点被 `!streamingutil.IsStreamingServiceEnabled()` 包着；流式服务在 3.0 恒开 ⇒ 这条边基本不触发 |
| `Flushing` | v3.0.1 生产链路无写入方——通用写入口只有 `SetSegmentState` RPC，它经 `meta.SetState` 可落任意状态、但全仓无调用方——是 2.x DataNode flush 的遗留状态；读点除 `isFlushState` 判定与重启恢复 `handleFlushingSegments` 外，`services.go`、`index_service.go`、`meta.go` 还各自直读该状态 |
| `Flushed` | `SaveBinlogPaths` 带 `flushed=true` → `UpdateStatusOperator`；若 `dataCoord.sortCompaction.enable` 为真，同一次更新还会 `SetSegmentIsInvisible(true)` |
| `Dropped` | compaction 元数据变异（`completeMixCompactionMutation` / `completeSortCompactionMutation` / clustering 的 `markInputSegmentsDropped`）、零行段 `UpdateAsDroppedIfEmptyWhenFlushing`、`NotifyDropPartition` → `DropSegmentsOfPartition` 与 drop collection |
| `Importing` | `AllocImportSegment`，见下文 Batch Import 一节 |

⚠️ 也就是说，3.0 里段的实际状态轨迹短得惊人：`Growing → Flushed (invisible) → Flushed (visible, sorted) → Dropped`，中间那些状态要么是兼容残留，要么是并行标记。

**段等级**是另一根正交轴（`datapb.SegmentLevel`）：

| Level | 语义 | 谁赋的值 |
| :--- | :--- | :--- |
| `Legacy` | 零值，老数据 | — |
| `L0` | 只装删除记录的段 | `CreateL0Operator`（`SaveBinlogPaths` 的 `SegLevel=L0` 分支）、L0 import |
| `L1` | 普通段，无额外分布信息 | flush、mix compaction 输出 |
| `L2` | 带数据分布信息的段 | **只有** `completeClusterCompactionMutation` |

还有几个不带在 `State` 里的旁路标记，共同决定一个段能不能被 compaction 挑中：`IsInvisible`（flush 时置真，sort compaction 或 clustering `markResultSegmentsVisible` 置假，期间查询侧看不见）、`IsImporting`、`Compacted` + `DroppedAt`（GC 的计时起点）、`CommitTimestamp`（import/CDC 段专用，非零时行时间戳是陈旧的，可见性与过期都用 `tsoutil.EffectiveTimestamp(rowTs, commitTs)`）、以及纯内存的 `isCompacting`（`CheckAndSetSegmentsCompacting` 保证一个段同时只参与一个任务）。

## Compaction Types

`datapb.CompactionType` 里列了 12 个具名值（另有编号 1 为 `reserved`），但 v3.0.1 **真正会被产出的只有 5 类**：`Level0DeleteCompaction`、`MixCompaction`、`SortCompaction`、`ClusteringCompaction`、`BumpSchemaVersionCompaction`。`MergeCompaction`、`SingleCompaction`、`MinorCompaction`、`MajorCompaction` 是 2.x 的分档遗留，`PartitionKeySortCompaction` / `ClusteringPartitionKeySortCompaction` 只在 LOB 压实策略的 switch 里被读——**没有任何产出方**，照旧资料写它们会错。

「single」「merge」这两个概念在 3.0 并没有消失，只是塌进了 `MixCompaction`：`compactionTrigger.generatePlans` 把候选分成 *prioritized*（单段自身就该压实：删除过多、过期过多、索引版本过老）与 *small*（段太小该合并），前者可以单独成桶，后者按 `MinSegmentToMerge` 打包——一张计划里两种动机共存。

| 类型 | 解决什么 | 产出它的策略 |
| :--- | :--- | :--- |
| `Level0DeleteCompaction` | 把 L0 删除记录摊到各目标段，避免每次查询都叠一层通道级删除 | `l0CompactionPolicy` |
| `MixCompaction` | 小段合并 + 物理消除墓碑与过期行 + 重建老版本索引 | `compactionTrigger`（flush 信号与手动 `Compact`）、`singleCompactionPolicy`、`forceMergeCompactionPolicy`、`storageVersionUpgradePolicy` |
| `SortCompaction` | 单段按 PK 排序并让它可见；导入段与 compaction 产出的必经一步 | `singleCompactionPolicy`、import checker |
| `ClusteringCompaction` | 按 clustering key 重排全量数据并产出 partition stats，供查询侧段裁剪 | `clusteringCompactionPolicy` |
| `BumpSchemaVersionCompaction` | schema 版本演进后重写段，避免长期带着旧 schema | `bumpSchemaVersionPolicy` |

## Triggers and Thresholds

开关是**四层与门**：`dataCoord.enableCompaction`（总闸，关掉连 `Compact` RPC 都不可用）→ `dataCoord.compaction.enableAutoCompaction`（自动策略与周期）→ collection property `collection.autocompaction.enabled`（未设则跟随全局）→ snapshot 保护 / `collection.on.truncating` / 外部集合（三者都会直接跳过该 collection 的全部策略）。

| 项 | 配置键 | 默认值 | 判定逻辑 |
| :--- | :--- | :--- | :--- |
| mix 与 single 周期 | `dataCoord.compaction.mix.triggerInterval` | 60s | 同时驱动 `SingleTicker` 与 `StorageVersionTicker`；flush 完成还会即时发一次信号 |
| 小段定义 | `dataCoord.segment.smallProportion` | 0.5 | 段大小 < `smallProportion × expectedSize` |
| 合并后需达到 | `dataCoord.segment.compactableProportion` | 0.85 | 打包后大小 > 该比例才值得做 |
| 允许超配 | `dataCoord.segment.expansionRate` | 1.25 | 挤进已有桶时可超出 `expectedSize` 25% |
| 最少合并段数 | `dataCoord.compaction.min.segment` | 3 | — |
| 段目标大小 | `dataCoord.segment.maxSize` / `diskSegmentMaxSize` | 1024 MB / 2048 MB | 全 dense 向量都是 DiskANN 时取后者（`getExpectedSegmentSize`） |
| 删除比例 | `dataCoord.compaction.single.ratio.threshold` | 0.2 | `deletedRows / numRows ≥ 0.2` |
| deltalog 数量 | `dataCoord.compaction.single.deltalog.maxnum` | 200 | 文件数即 IO 次数 |
| deltalog 体积 | `dataCoord.compaction.single.deltalog.maxsize` | 16 MB | varchar PK 更容易撞这条 |
| 过期体积 | `dataCoord.compaction.single.expiredlog.maxsize` | 10 MB | 由段统计 `expirQuantiles` 估算 |
| 严格过期容忍 | `dataCoord.compaction.expiry.tolerance` | **-1，即关闭** | 开启后按行的最早时间戳精确判定 |
| L0 周期 | `dataCoord.compaction.levelzero.triggerInterval` | 10s | 活跃集合走 `ViewChange`，闲置集合走 `IDLE` 强制触发 |
| L0 触发下界 | `levelzero.forceTrigger.deltalogMinNum` / `minSize` | 10 个 / 8 MB | 任一满足即触发 |
| L0 单次上界 | `levelzero.forceTrigger.deltalogMaxNum` / `maxSize` | 1000 个 / 64 MB | 挑拣时同时受两界约束 |
| clustering 周期 | `dataCoord.compaction.clustering.triggerInterval` | 600s | 自动还须 `clustering.enable` 与 `clustering.autoEnable`（代码默认 false，而 `milvus.yaml` 出厂写 `enable: true`；`autoEnable` 两边都是 false） |
| clustering 门槛 | `minInterval` / `maxInterval` / `newDataSizeThreshold` | 3600s / 86400s（YAML 259200s）/ 512m | 距上次提交 < min 跳过；> max 强制；否则看未压实数据量 |
| schema bump | `dataCoord.compaction.bumpSchemaVersion.enabled` | **false** | 开启后每 20s 扫一轮 |

手动入口是 `Compact` RPC → `CompactionTriggerManager.ManualTrigger`：带 `targetSize` 走 force merge（单位 MB，必须 ≥ 配置段上限，本质是「把小段拼成大段」的容量整形工具），`majorCompaction=true` 走 clustering，`l0Compaction=true` 走 L0。**手动 clustering 会绕过 `Enable()` 与全部间隔判定**，只要求 schema 里有 clustering key。

## Scheduling and Execution

调度在 DataCoord，执行在 DataNode——3.0 里 IndexNode 已不是独立进程，`types.DataNode` 同时实现 `datapb.DataNodeServer` 与 `workerpb.IndexNodeServer`。三段式流水：

1. **策略产 view**：`CompactionTriggerManager.loop` 上挂 5 个 ticker，每个 `CompactionPolicy` 返回 `map[TriggerType][]CompactionView`；inspector 队列满（`dataCoord.compaction.taskQueueCapacity` 100000）则整轮跳过。
2. **入队与互斥**：view 经 `Trigger()` / `ForceTrigger()` 收敛成 `datapb.CompactionTask` 落 etcd，状态 `pipelining`；`CheckAndSetSegmentsCompacting` 给输入段上锁，一个段同时只能进一个任务。
3. **选节点下发**：`compactionInspector.schedule` 每 `compaction.scheduleInterval` 500ms 跑一次，按 `(channel, partition)` 标签做互斥——L0 与 mix/clustering 在同一 channel 上互斥（L0 会往该通道任意段追加 deltalog），mix 与 clustering 按 label 互斥；通过后交给 `globalScheduler`，后者用**可用 slot 最大堆挑最闲的 DataNode**（`pickNode`，水床式均摊），再走 `CreateCompaction` RPC。

并行度是三层：全局由队列容量与 `dataCoord.compaction.taskPrioritizer`（默认 `level`：L0 → mix → clustering）决定排队顺序；单节点由 slot 记账（`dataNode.slot.slotCap` 16，mix 占 4、L0 占 `8 × totalRows / BloomFilterApplyBatchSize`、clustering 占 65535 即独占一台）；真正跑数据的线程池是 `dataNode.compaction.maxConcurrency` 10。`dataCoord.compaction.maxParallelTaskNum` 默认 -1 且标注 Deprecated，别再去调它。

失败重试分两条路。RPC 层：`CreateTaskOnWorker` 或 `QueryTaskOnWorker` 出错就把任务退回 `pipelining` 并把 `nodeID` 清成 `NullNodeID`，等下一轮重新分配节点；重派之间由 `dataCoord.taskRetryBackoffInterval` 1s 起指数退避到 `taskRetryBackoffMaxInterval` 60s。任务层：只有 `clusteringCompactionTask` 实现了 `retryableProcess` + `retryOnError`，可重试错误最多 `maxRetryTimes` 3 次，不可重试（如 collection 已删）直接 `failed`。

⚠️ **超时在 v3.0.1 是虚的**：`dataCoord.compaction.timeout`（900）与 `dataCoord.compaction.clustering.timeout`（3600）在全仓 Go 代码里**没有任何消费方**，只有参数定义；`CompactionTaskState_timeout` 也无人产出（协调器只是镜像 worker 返回的状态，而 DataNode 侧从不返回 timeout）。唯一活着的是 `maxCompactionTaskExecutionDuration` 表（mix/L0 30min、clustering 60min、sort 20min），而它只打一条 "compaction task is delay" 的告警日志，**不杀任务**。想要超时得自己盯指标。

已清理的任务元数据由 `loopClean`（`compaction.gcInterval` 1800s）在结束超过 `dropTolerance` 3600s 后删除；partition stats 每个 `(coll, part, vchannel)` 只保留最新 2 个版本。

## The L0 Segment

删除不能直接改段：段的插入数据不可变，改一行就要重写整段并重建索引，一次批量删除会打出无法接受的写放大。Milvus 的做法是把删除**独立成段**——L0 段没有 insert binlog，只装 `(PK, timestamp)` 的 deltalog，粒度是整个 VChannel 而不是单个目标段，所以它天然跨段、可以极便宜地追加。

**创建与封口**：flusher 把删除消息攒成 L0 的 delta binlog，通过 `SaveBinlogPaths` 带 `SegLevel=L0` 上报，DataCoord 侧 `CreateL0Operator` 直接把它建成 `Flushed` 的 L0 段——L0 没有 `Growing`/`Sealed` 过程。封口时机在流式侧的 `StatsManager`：行数 `streaming.flush.l0.maxRowNum` 50 万、体积 `streaming.flush.l0.maxSize` 32m、存活 `streaming.flush.l0.maxLifetime` 10m，三个条件都乘一个 jitter 系数打散同时封口的风暴。

**如何被消化**：`l0CompactionPolicy` 按 collection 分组，再用 `groupL0ViewsByPartChan` 拆到 `(partition, channel)`；每个 view 的 `latestDeletePos` 取 **该 label 下最早 growing 段的 start position**（`GetEarliestStartPositionOfGrowingSegments`），只有 dml 位置不晚于它的 L0 才会被挑进去。这个位置随任务落到 `CompactionTask.Pos`，执行时 `selectFlushedSegment` 用它筛目标段：`segmentEffectiveTs < Pos`。含义是——**只要还有 growing 段的时间区间盖住这批删除，删除就只能继续堆在 L0 里**。于是有了背压：StreamingNode 的 `selectSegmentsWithBlockingL0Policy` 在删除压力（`dataCoord.sealPolicy.channel.blockingL0EntryNum` 500 万条 / `blockingL0SizeInMB` 64）超阈时，提前 seal 该 vchannel 上**最早**的 L1 growing 段。DataCoord 里的同名实现 `sealByBlockingL0` 被**无条件**注册进 `defaultChannelSealPolicy`，只在 `GetFlushableSegments → tryToSealSegment` 这条链上被消费，而 `GetFlushableSegments` 全仓没有生产调用方，于是这条 DataCoord 侧的路径实际从不触发——v3.0.1 真正生效的是流式侧那一份。那道 `!IsStreamingServiceEnabled()` 守卫只包着 `services.go` 里 `SealAllSegments` 的调用点，与 `sealByBlockingL0` 无关。

执行时 DataNode 的 `LevelZeroCompactionTask` **不读目标段的数据**，只 `loadBF` 载入各段主键布隆过滤器，`applyBFInParallel` 把删除记录按 PK 命中情况拆开（`levelZeroBatchMemoryRatio` 0.5、`levelZeroMaxBatchSize` -1 控制分批）。产出是**每个目标段一组新的 deltalog**；对 StorageV3 的段，DataCoord 在元数据更新里自己调 `AddDeltaLogsToManifestOverwrite` 把 delta 追加进段 manifest（并发度 `dataCoord.compaction.levelzero.manifestUpdatePoolSize` 16），然后 L0 段被置 `Dropped` + `Compacted`。目标段为空集时走 fast finish，直接把 L0 丢掉不派工。

⚠️ 所以 L0 compaction **一个字节的数据段都没重写**，它只是把「通道级待办删除」降级成「段级已摊开的 deltalog」。墓碑真正消失要等第二跳：deltalog 的数量、体积、删除比例撑破 `hasTooManyDeletions` 三条阈值，触发 mix compaction 物理重写。**删除是两跳的，任何一跳停摆都会让查询侧继续叠位图。**

**查询侧**：L0 段只由 delegator 在 `watchChannel` 时加载（显式禁止下发给 worker，见 `LoadL0Segments` 的报错分支），Go 侧 `L0Segment` 只存 `pks`/`tss` 两个数组，靠 `processDeleteRecords` 做 BF 命中后转发进各段 delete buffer。DataCoord 通过 `GetQueryVChanPositions` 把 L0 装进 `LevelZeroSegmentIds`，并把**最小**的 L0 start position 作为 `deleteCheckPoint` 回给 QueryCoord，含义是「这个 ts 之前的删除已经物化到段上了，只需维护其后的流式删除」。细节见 [Query Path](/docs/CS/DB/Milvus/Query_Path.md)。

## Garbage Collection

GC 是四个独立 ticker，不是一轮全扫（`garbageCollector.work`）：

| 循环 | 周期 | 配置键与默认 | 回收什么 |
| :--- | :--- | :--- | :--- |
| `meta` | 每小时 | `dataCoord.gc.interval` 3600 | Dropped 段的文件与元数据、失效索引、channel checkpoint 元数据、analyze 文件、text/JSON 索引与统计、快照 |
| `orphan` | 每 7 天 | `dataCoord.gc.scanInterval` 168（小时） | `WalkWithPrefix` 全量扫对象存储，删掉「文件在、元数据不认」的孤儿 |
| `lob` | 每 30 分钟 | `dataCoord.gc.lob.checkInterval` 1800，安全窗 `lob.safetyWindow` 3600 | TEXT 列的 LOB 溢出文件 |
| control | 常驻 | — | 处理 `PauseGC` / `ResumeGC`，全局或按 collection 暂停 |

回收并发度 `dataCoord.gc.removeConcurrent` 默认 0 → 取 CPU 核数；CPU 占用超过 `gc.slowDownCPUUsageThreshold` 0.6 时把删除池缩到 1，压下来再恢复。

**判定输入**（`checkDroppedSegmentGC` 加 `recycleDroppedSegments` 的前置过滤）：段状态是 `Dropped`；`DroppedAt` 距今超过 `dataCoord.gc.dropTolerance` 10800s；该段不在 `ListLoadedSegments` 返回的已加载集合里；若它是被压实掉的父段，则**压实产物段必须已建好索引**（否则回收会让性能倒退）；所在 channel 的 checkpoint 必须已越过段的生效 dml 位置（`segmentEffectiveDmlTs`，即 `CommitTimestamp` 优先、否则 `DmlPosition`）；不被任何快照的 RefIndex 引用（RefIndex 未加载完成时是 **fail-closed 的粗粒度整库封禁**）。checkpoint 由 `WatchChannels` 初始化、由 StreamingNode 在 WAL 打开/恢复时经 `UpdateChannelCheckpoint` 推进。孤儿文件另有一道保险：修改时间距今不足 `gc.missingTolerance` 86400s 的文件一律不碰，防止误删刚写好、元数据还没落的新 binlog。

V3 段的回收方式和 V1/V2 不同：文件由 manifest 的 basePath 统辖，所以 `removeDroppedSegmentFiles` 对 `StorageV3` 走 `RemoveWithPrefix(basePath)` 整体删目录，孤儿扫描也会跳过 V3 段（否则会把 manifest 管的活文件当孤儿）。索引文件仍在独立前缀下，按记录的 file keys 逐条删。

**「数据删了但对象存储没变小」**——按可能性排序的原因：

| 原因 | 机制 |
| :--- | :--- |
| 时间常数叠加 | dropTolerance 3h + gc.interval 1h + 快照 pin，最快也要小时级；孤儿文件路径上限是 scanInterval 7 天 + missingTolerance 1 天 |
| 删除只写了 L0 | 物理空间要等 L0 → deltalog → mix 重写两跳才释放；autoCompaction 关掉或 `collection.on.truncating` 会卡死这条链 |
| 压实产物还没建索引 | 父段被刻意留着不回收，索引慢或 `indexBasedCompaction` 相关异常都会表现为「不回收」 |
| channel checkpoint 没推进 | 流式侧停滞 → 已 Dropped 段的元数据和文件都不许删 |
| 段还被 QueryNode 加载着 | release 之前不回收，collection 处于 Loading 或有快照引用时同理 |
| GC 被暂停或没开 | `dataCoord.enableGarbageCollection` 为 false，或有别的模块通过 `PauseGC` 挂了 ticket；`cli == nil` 时 `start()` 只打一条 warn 就返回，GC 根本没起循环 |

## TTL Semantics

v3.0.1 的 TTL 是**两段式**，且**没有任何 TTL 守护任务、没有 `dataCoord.enableTTL` 这类开关、没有专属指标**——`internal/datacoord/` 与 `internal/rootcoord/` 里搜不到 TTL ticker，`garbage_collector.go` 也不参与 TTL 回收。这一点必须先钉死：配置项 `collection.ttl.seconds` 存在，但它不驱动任何后台删除。

- **逻辑模式二选一**：collection 级 `collection.ttl.seconds`（合法区间 `[-1, 3155760000]` 秒，基准是行的写入 ts）或 entity 级 `ttl_field`（collection property，指向一个 `TIMESTAMPTZ` 列存**绝对过期时刻**，NULL 表示永不过期）。两者互斥，Proxy 在创建与 `AlterCollection` 时双向校验；被引用的列不许 drop。
- **不可见**是即时的、强制的、关不掉的：Proxy 把 cutoff 随查询计划下传，segcore 在 Mvcc 与表达式层做时间戳掩码（详见 [Query Path](/docs/CS/DB/Milvus/Query_Path.md)）。所以「过期」在用户视角立即生效。
- **物理回收**只发生在 compaction 里，唯一实现是 `internal/compaction/entity_filter.go` 的 `EntityFilterImpl.Filtered`：已删 OR 按 `ttl` 过期 OR 按 `ttl_field` 的 `expirationTimeMicros` 过期。mix、sort、clustering、bump-schema 各 compactor 与 stats task 都会调它。
- **什么时候会被触发**：`ShouldDoSingleCompaction` 用段统计里的时间戳分位数组 `expirQuantiles`（20%~100%）估过期比例与体积，撞上 `single.ratio.threshold` 0.2 或 `single.expiredlog.maxsize` 10MB 就走；精确路径 `expiry.tolerance` 默认 **-1 关闭**，所以默认配置下过期数据的清理是**尽力而为且滞后的**。

两个语义细节容易踩：upsert / partial update 会刷新行 ts，等于**续期**；import/CDC 段用 `max(row_ts, commit_timestamp)` 作基准（`tsoutil.EffectiveTimestamp`），避免陈旧时间戳导致提前判过期——compaction 输出会把 `CommitTimestamp` 归零，因为行时间戳已被重写。外部集合不做 collection TTL；没有 `expirQuantiles` 统计的存量老段不会因 `ttl_field` 被触发。

## Stats and Analyze

`statsInspector` 与 compaction 共用同一个 `globalScheduler`，作业类型是 `indexpb.StatsSubJob`：v3.0.1 真正在跑的只有 `TextIndexJob`（全文索引）与 `JsonKeyIndexJob`（JSON 打散/shredding）。`Sort = 1` 在 proto 里已注明 deprecated——排序改由 `SortCompaction` 承担；`BM25Job` 的执行体存在但入口写死关闭（`enableBM25()` 与 `needDoBM25()` 恒返回 false）。

发现循环每 `dataCoord.taskCheckInterval` 60s 一轮，文本与 JSON 按轮次交换先后顺序（防止长文本积压饿死 JSON 打散）；准入只看一个预算：全局调度器里 pending 的 stats 任务数超过 `dataCoord.statsTaskPendingLimit` 100 就停止提交。⚠️ 老的 `dataCoord.jsonStatsTriggerCount` / `jsonStatsTriggerInterval` **已经不再节流**，`statsInspector.Start()` 会专门给还留着非默认值的部署打一条 deprecated 警告——典型的「配置项存在但已不生效」。

**Analyze 在 v3.0.1 是纯内部机制**：没有对外 Analyze RPC，`analyzeInspector` 只服务于 clustering compaction 的 kmeans 训练（`CompactionTask.AnalyzeTaskID`），产物是质心与 `PartitionStatsInfo`。段统计（`Statistics` 里的 `insertBinlogCount` / `deltaBinlogCount` / `deleteNumRows` / `timestampQuantiles` / `expirQuantiles`）由 flusher 与 compactor 在写文件时顺带算出、随 `SaveBinlogPaths` 整体上报，是上面所有 compaction 判定的输入——**没有段统计，触发器就是瞎子**。

## Clustering Key versus Partition Key

三者常被混为一谈，实际作用在三个不同层次：

| 机制 | 作用对象 | 决策方 | 收益 |
| :--- | :--- | :--- | :--- |
| 显式 partition | 用户命名的分区 | 用户 | 手工隔离与裁剪 |
| `partition_key` 字段 | 行 → 已有分区的**哈希路由**（`Hash32Int64` / 字符串哈希 + 一致性哈希表定位分区） | Proxy 自动 | 免手工建分区地扩并发；配 `partitionKeyIsolation` 可强制查询带 key |
| `clustering_key` 字段 | **段内与段间的数据排布** | ClusteringCompaction | 产出 `L2` 段 + partition stats，QueryNode delegator 的 `segment_pruner` 按统计跳过整段 |

关键差别：partition key 只决定行落在哪个分区，不改变段内布局，也不会让段变少；clustering key 必须靠 clustering compaction 重排数据才生效，而 clustering compaction 会把整个 `(collection, partition, channel)` 组的所有 L2 段一起换掉——所以 `checkAllL2SegmentsContains` 要求该组里没有正在压实的 L2 段，否则宁可跳过（半换会让裁剪失效）。它还会等所有结果段索引建完才标记可见（`processIndexing` → `markResultSegmentsVisible`），代价是这段时间的磁盘与 IO 双份。

## Batch Import

导入段与在线写入段走的是完全不同的分配方式：在线写是「先建 growing 段，边写边长到封口」；导入是 **preimport 先估分布、coord 一次性预分配足量空段**（`AssignSegments` 按 `hashDataSize / GetSegmentMaxSize` 逐个 `AllocImportSegment`），再让 DataNode 直接往指定段 ID 里写文件。差异清单：

| 维度 | 在线写入的段 | 导入产出的段 |
| :--- | :--- | :--- |
| 初始状态 | `Growing` | `Importing` + `IsImporting=true`，所有 compaction 策略都排除它 |
| 大小上限 | `segment.maxSize` | 同左；但 L0 import（导入删除文件）用 `dataNode.segment.deleteBufBytes`（默认 16MB） |
| 段 ID / 时间戳 | flusher 申请 | 任务预分配；`MaxRowNum=0`、`LastExpireTime=math.MaxUint64` |
| 可见性 | 由 sort compaction 置 visible | 由 **2PC 提交栅栏**置：`HandleCommitVchannel` 收齐所有 vchannel 后，一次性 `UpdateCommitTimestamp` + `UpdateIsImporting(false)` |
| 收尾工序 | 直接进 sort/mix | 作业状态机 `Importing → Sorting → IndexBuilding → (Uncommitted →) Completed`，`Sorting` 阶段为每个段单独造一个 `SortCompaction` 任务；零行段直接 `Dropped` |
| 任务规模 | — | `filesPerPreImportTask` 2、`maxImportFileNumPerReq` 1024、`maxImportJobNum` 1024、状态保留 `import.taskRetention` 10800s |

`CommitTimestamp` 是导入段最需要记住的一件事：段的行数、时间戳都晚于文件里写的 ts，所以可见性、TTL 过期、删除应用三处都用 `max(row_ts, commitTs)`，且 `LevelZeroCompactionForceSelectAll`（配置键 `dataCoord.compaction.levelzero.forceSelectAllSegments`）这类修复开关正是为「导入段 StartPosition 记错导致 L0 挑不到目标」的历史 bug 准备的。

## Comparison with LSM-tree Compaction

Milvus 的段模型是「不可变文件 + 删除日志 + 后台合并」，与 LSM-tree 同源，对照 [Compaction](/docs/CS/DB/RocksDB/Compaction.md) 与 [Versions and Compaction](/docs/CS/DB/LevelDB/Versions_and_Compaction.md) 能看清差异都出在「数据是要被 ANN 索引的」这一件事上：

| 维度 | LSM-tree | Milvus v3.0.1 |
| :--- | :--- | :--- |
| L0 的角色 | 层内 key 区间可重叠，等待下沉 | 同构：L0 段装删除，跨段重叠，等 L0 compaction 摊平 |
| 分层依据 | 容量阶梯（`max_bytes_for_level_base × multiplier`） | **不是容量阶梯**，而是「有无分布信息」：L1 普通段、L2 clustering 段，段目标大小由 `segment.maxSize` 与索引类型决定 |
| 策略可选项 | leveled / tiered / FIFO / universal | 基本是 tiered 式的桶打包（`generatePlans` 的 pack/squeeze）+ 一个可选的 clustering 重排；没有「按层容量」概念 |
| tombstone 回收前提 | 最后一层、无快照、无 iterating 事务 | 压实时要能证明「查询侧再也读不到这个 ts 之前的一致性视图」——由 channel checkpoint、`expiry.tolerance`、已摊开的 deltalog 共同决定，**没有 seq/mvcc id 可依据，靠时间戳** |
| 与索引耦合 | 无 | 强：`indexBasedCompaction` 让「索引没建完的段」不进候选，压实产物没索引前不回收父段，clustering 要等索引完成才可见 |
| 写停摆反压 | `Write Stall` 按 L0 文件数与待压实字节数限速 | 没有停写；反压表现为**提前 seal 最早的 growing 段**（blockingL0 策略），把压力转给 compaction 而不是转给客户端 |
| 空间回收 | compaction 内联删旧 SST + `DeleteFile` | compaction 只让元数据失效；对象存储由独立慢循环 GC，默认小时/天级滞后 |

HBase 的 compaction 对照见 [HBase](/docs/CS/DB/HBase/HBase.md)：它同样把「合并」和「回收」分开，但没有 Milvus 这层「段即索引、加载后不可变」的约束，也就不需要压实与建索引互相排队。

## Operational Diagnosis

| 症状 | 先看哪里 |
| :--- | :--- |
| 检索扇出高、延迟随时间爬升 | 每 DML channel 的 `Flushed` 段数；`mix.triggerInterval` 是否在跑；`taskQueueCapacity` 是否满；结果段是否长期 `IsInvisible`（sort compaction 积压，看 `sortCompactionTriggerCount` 100 与 stats pending limit） |
| 结果里混入已删数据、删除越来越慢 | L0 段数量与总大小（`DataCoordSizeStoredL0Segment`）；`Pos` 是否被某个长期不封口的 growing 段钉住；`blockingL0*` 阈值 |
| 对象存储只涨不跌 | 上面「GC 六个原因」按序排查；`PauseGC` 状态；是否有未加载 RefIndex 的快照造成 fail-closed |
| compaction 完全不动 | `enableCompaction` / `enableAutoCompaction` / collection property / `collection.on.truncating` / 外部集合，五道与门逐个查 |
| 任务反复失败但看不到原因 | `compactionInspector` 的 `failReason` 与 task meta；注意超时不会自动杀任务 |

## Links

- [Milvus](/docs/CS/DB/Milvus/Milvus.md)
- [Write Path](/docs/CS/DB/Milvus/Write_Path.md)
- [Storage Layer](/docs/CS/DB/Milvus/Storage_Layer.md)
- [Query Path](/docs/CS/DB/Milvus/Query_Path.md)
- [Index and Vector Engine](/docs/CS/DB/Milvus/Index_and_Vector_Engine.md)
- [Compaction](/docs/CS/DB/RocksDB/Compaction.md)

## References

- [Milvus v3.0.1 configs/milvus.yaml](https://github.com/milvus-io/milvus/blob/v3.0.1/configs/milvus.yaml)
- [Milvus Entity-Level TTL 设计文档](https://github.com/milvus-io/milvus/blob/master/docs/design-docs/design_docs/20251221-entity_level_ttl.md)
- [Milvus v3.0.1 DataCoord compaction trigger](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/datacoord/compaction_trigger.go)
- [RocksDB Wiki: Compaction](https://github.com/facebook/rocksdb/wiki/Compaction)
- [HBase Reference Guide](https://hbase.apache.org/book.html)
