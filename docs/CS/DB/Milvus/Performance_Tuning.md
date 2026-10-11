## Introduction

Milvus 的性能没有「调优开关」这种银弹。一条数据从写入到可查，要穿过 WAL、落盘、索引、加载、检索一串环节，每个环节的旋钮都只是把一种代价换成另一种：段封得大，索引质量换段数；同步节奏放慢，吞吐换 durability 窗口；内存压得低，成本换首查延迟。机制篇各自回答了「为什么」——封口与落盘见 [Write Path](/docs/CS/DB/Milvus/Write_Path.md)，WAL 的同步节奏见 [Woodpecker](/docs/CS/DB/Milvus/Woodpecker.md)，索引与加载预算见 [Index and Vector Engine](/docs/CS/DB/Milvus/Index_and_Vector_Engine.md)，检索执行见 [Query Path](/docs/CS/DB/Milvus/Query_Path.md)，段的生死与压缩见 [Compaction and Lifecycle](/docs/CS/DB/Milvus/Compaction_and_Lifecycle.md)。本篇把这些散落的取舍收拢成一张决策面：按数据流分站列出旋钮，每个都标「换来什么、牺牲什么、详见哪篇」，末尾用 Symptom to Knob 给「症状 → 先看什么 → 调哪两三个」的定位地图。

两条使用前提。其一，默认值以随包 `configs/milvus.yaml` 与 paramtable 注册代码为准，两处不一致处单独注明；「配置项存在 ≠ 生效」在本篇多次出现（`knowhereThreadPoolNumRatio`、`ttProtection` 都是例子）。其二，先分层再动手：写入被拒先查 [Deployment and Ops](/docs/CS/DB/Milvus/Deployment_and_Ops.md) 的配额与观测小节，错误语义（可重试的 `ErrServiceRateLimit` 与不可重试的 `ErrServiceQuotaExceeded`）见 [Error Model](/docs/CS/DB/Milvus/Error_Model.md)。可观测性入口与排障顺序也在 Deployment 篇，本篇不重复。

## Write Path Knobs

写侧调的两件事：段多大、何时封口。封得早，growing 段内存停得短，但小段多，查询扇出与压缩压力大；封得晚，单段索引质量高、段数少，但落盘与索引更晚、内存占用更久。

| 旋钮 | 默认 | 换来 | 牺牲 | 详见 |
| :--- | :--- | :--- | :--- | :--- |
| `dataCoord.segment.maxSize` + `sealProportion`（`sealProportionJitter` 0.1 向下浮动） | 1024 MB / 0.12 | 段大→单段索引更优、段数少→扇出与元数据压力小 | 实际封口点约 111~123 MB（0.108~0.12 倍），封口晚则 growing 段内存停得久 | [Write Path](/docs/CS/DB/Milvus/Write_Path.md) |
| `dataCoord.segment.diskSegmentMaxSize` | 2048 MB | Disk 索引集合单段可放大一倍，段数再降 | 单段构建时间与临时空间翻倍 | [Write Path](/docs/CS/DB/Milvus/Write_Path.md) |
| `dataNode.segment.insertBufSize` / `deleteBufBytes` | 16 MB / 16 MB | 攒批发对象存储，减少小文件 | 缓冲在内存里，粒度越大越费内存 | [Write Path](/docs/CS/DB/Milvus/Write_Path.md) |
| `dataNode.segment.syncPeriod` | 600 s | sync 频率低，对象存储写放大小 | 异常时未 sync 的数据要等 WAL 重放，durability 由 WAL 兜底 | [Woodpecker](/docs/CS/DB/Milvus/Woodpecker.md) |
| `dataNode.memory.forceSyncWatermark` | standalone 0.2 / 其余 0.5（yaml 写 0.5） | 内存逼近水位强制 sync，防把写入憋爆内存 | 落盘更频繁，小文件与调度压力上升 | [Write Path](/docs/CS/DB/Milvus/Write_Path.md) |
| `dataCoord.sealPolicy.channel.growingSegmentsMemSize` / `blockingL0EntryNum` / `blockingL0SizeInMB` | 4096 MB / 500 万行 / 64 MB | shard 维度撑爆或 L0 积压时被动封口，给 L0 compaction 让路 | 被动封口产生更多小段，压缩队列压力增大 | [Compaction and Lifecycle](/docs/CS/DB/Milvus/Compaction_and_Lifecycle.md) |
| `streaming.flush.l0.maxRowNum` / `maxSize` / `maxLifetime` | 50 万行 / 32 MB / 10 min | L0 删除段尽快落盘、可被压缩消化 | 删除密集时 L0 生成更快，读放大靠压缩追 | [Compaction and Lifecycle](/docs/CS/DB/Milvus/Compaction_and_Lifecycle.md) |

## WAL and Woodpecker Knobs

WAL 侧调的是「攒批与同步」：批越大、同步越稀，吞吐越高，单条可见延迟与故障窗口越大。四后端选型见 Deployment 篇，内部机制见 [Woodpecker](/docs/CS/DB/Milvus/Woodpecker.md)。

| 旋钮 | 默认 | 换来 | 牺牲 | 详见 |
| :--- | :--- | :--- | :--- | :--- |
| `woodpecker.client.segmentAppend.queueSize` / `maxRetries` | 10000 / 3 | 高并发下 append 排队吸收抖动，重试兜瞬时错误 | 队列满即对写侧表现为背压；重试拉长尾延迟 | [Woodpecker](/docs/CS/DB/Milvus/Woodpecker.md) |
| `woodpecker.client.segmentAppend.maxBatchEntries` / `maxBatchBytes` | 1000 / 2 MB | 客户端组批摊薄 RPC，只批已排队请求，低载不加延迟 | 大批意味着批内后续请求的等待更久 | [Woodpecker](/docs/CS/DB/Milvus/Woodpecker.md) |
| `woodpecker.client.segmentRollingPolicy.maxSize` / `maxInterval` / `maxBlocks` | 256 MB / 10 min / 1000 | 段滚动小，恢复 replay 快、易并行 | 文件与元数据数量变多 | [Woodpecker](/docs/CS/DB/Milvus/Woodpecker.md) |
| `woodpecker.logstore.segmentSyncPolicy.maxInterval` | 200 ms（local 与 service 模式 10 ms） | 攒批换 QPS | 同步间隔就是 durability 窗口上限，最多丢这么多 | [Woodpecker](/docs/CS/DB/Milvus/Woodpecker.md) |
| `woodpecker.logstore.retentionPolicy.ttl` | 72 h | 可回放窗口长，恢复与排障余地大 | 对象存储成本 | [Woodpecker](/docs/CS/DB/Milvus/Woodpecker.md) |
| `woodpecker.client.directRead.enabled` / `maxBatchSize` / `maxFetchThreads` | true / 16 MB / 4 | 读已封段直连对象存储，绕过 LogStore 服务 | 命中延迟受对象存储影响 | [Woodpecker](/docs/CS/DB/Milvus/Woodpecker.md) |

## Index Build Knobs

构建侧调的是「质量、内存、并发」三角：索引类型决定前两项，slot 记账与并发键决定第三项。v3.0.1 构建任务由 DataNode 本地执行（不再有独立 IndexNode 进程），所以构建并发与压缩、导入共享同一槽池。

| 旋钮 | 默认 | 换来 | 牺牲 | 详见 |
| :--- | :--- | :--- | :--- | :--- |
| AUTOINDEX 默认策略 | `HNSW_SQ`，`M=18` `efConstruction=240` `sq_type=SQ4U` `refine=true` `refine_type=FP16` `COSINE`（CUDA 发行版换 `GPU_CAGRA`） | 开箱即得「图索引速度 + 量化省内存」 | 想要别的精度内存曲线就得放弃 AUTOINDEX 手写参数 | [Index and Vector Engine](/docs/CS/DB/Milvus/Index_and_Vector_Engine.md) |
| `build_dram_budget_gb`（DataNode 建索引前按本机空闲内存注入） | 构建时注入 | 内存换构建吞吐，大索引不被内存不足打断 | 预算过大会与前台负载争内存 | [Index and Vector Engine](/docs/CS/DB/Milvus/Index_and_Vector_Engine.md) |
| `common.buildIndexThreadPoolRatio` | 0.75 | 构建线程池按 CPU 数比例放大 | 构建吃满 CPU 时查询与写入抖动 | [Index and Vector Engine](/docs/CS/DB/Milvus/Index_and_Vector_Engine.md) |
| `dataCoord.slot.indexTaskSlotUsage` / `scalarIndexTaskSlotUsage` / `statsTaskSlotUsage` | 64 / 16 / 8（每 512 MB） | 大任务按数据量占更多槽，天然限并发 | 大索引接近串行构建 | [Write Path](/docs/CS/DB/Milvus/Write_Path.md) |
| `dataCoord.slot.mixCompactionUsage` / `l0DeleteCompactionUsage` / `clusteringCompactionUsage` | 4 / 8 / 65535 | 给压缩分级定价；clustering 直接独占一个 worker | 大任务挑低峰执行，否则挤走构建 | [Compaction and Lifecycle](/docs/CS/DB/Milvus/Compaction_and_Lifecycle.md) |
| `dataNode.slot.slotCap` / `dataNode.workerSlotUnit` / `dataNode.standaloneSlotFactor` | 16 / 16 / 0.25 | 单节点任务容量封顶防过载；standalone 下离线任务只占 25% 槽 | 构建、压缩、导入互相排队 | [Write Path](/docs/CS/DB/Milvus/Write_Path.md) |
| `indexNode.scheduler.buildParallel` / `dataNode.index.maxVecIndexBuildConcurrency` | 1 / 4 | 抬升单任务并行度与向量构建并发 | 两个键 v3.0.1 仍被 DataNode 索引路径读取，调大直接吃 DataNode CPU | [Index and Vector Engine](/docs/CS/DB/Milvus/Index_and_Vector_Engine.md) |

## Query Path Knobs

查询侧调的是「等多久、算多深、保多少」：一致性等级与降级决定等多少 TimeTick、concurrency 与检索参数决定算多深、分段裁剪决定少看多少数据。执行链与一致性等待的原理见 [Query Path](/docs/CS/DB/Milvus/Query_Path.md)。

| 旋钮 | 默认 | 换来 | 牺牲 | 详见 |
| :--- | :--- | :--- | :--- | :--- |
| 一致性级别 + `common.gracefulTime` | Bounded / 5000 ms | 调到 Bounded/Eventually 少等 TimeTick，查询更快 | 数据新鲜度下降；Strong 必须等最新 TimeTick | [Query Path](/docs/CS/DB/Milvus/Query_Path.md) |
| `proxy.partialResultRequiredDataRatio` | 1 | 调低后部分 shard 缺失也返回部分结果，可用性换完整性 | 默认 1 意味着宁可失败也不给半份结果 | [Deployment and Ops](/docs/CS/DB/Milvus/Deployment_and_Ops.md) |
| `queryNode.scheduler.maxReadConcurrentRatio` | 1.0（= CPU×1，Doc 注释写 2.0 系滞后文本） | 调大同时执行的 search/query 更多，吞吐升 | 单查询尾延迟恶化，超过 CPU 承载即互相排队 | [Query Path](/docs/CS/DB/Milvus/Query_Path.md) |
| `queryNode.segcore.knowhereThreadPoolNumRatio` | 4，但仅 `enableDisk=true` 时生效；否则池大小强制为 CPU×1 | 磁盘索引场景放大检索 IO 并行（钳制 [1, 32]） | 非磁盘场景该值不生效，调了也白调 | [Index and Vector Engine](/docs/CS/DB/Milvus/Index_and_Vector_Engine.md) |
| `queryNode.segcore.chunkRows` | 128（下限也钳在 128） | 调大→顺序扫描摊薄；调小→缓存粒度细 | chunk 越大单次 IO 越粗、内存峰值越高 | [Query Path](/docs/CS/DB/Milvus/Query_Path.md) |
| `queryNode.segcore.interimIndex.*` | `nlist=128` `nprobe=16` `indexBuildRatio=0.1` `memExpansionRate=1.15` `growingBuildThreadRate=0` `buildParallelRate=0.5`；`enableIndex` 三处不一致：随包 yaml `true`、代码默认 `false`、Doc 写 true，常规部署以随包 yaml 为准（开启） | 给 growing 与未建索引段临时索引，新写入立即可查得快 | 建索引吃 `memExpansionRate` 倍额外内存；`growingBuildThreadRate=0` 单线程 | [Query Path](/docs/CS/DB/Milvus/Query_Path.md) |
| `autoIndex.twoStageSearch.enabled` / `minTopk` / `minNumSegments` | false / 2000 / 5 | 开启后先跑过滤拿真实选择率再调向量检索参数，高选择性过滤省算力 | 多一次过滤执行，低选择性场景纯亏 | [Index and Vector Engine](/docs/CS/DB/Milvus/Index_and_Vector_Engine.md) |
| `autoIndex.globalRefine.enabled` / `minDimThreshold` / `searchTopkRatio` / `refineTopkRatio` | false / 256 / 0 / 0 | 段内多取候选再精确重排，召回补回（ratio 为 0 表示不启该侧） | 多存多算一批候选 | [Index and Vector Engine](/docs/CS/DB/Milvus/Index_and_Vector_Engine.md) |
| `queryNode.exprCache` | `enabled=false`；开启后 disk 模式上限 10 GB / memory 模式 256 MB | 重复过滤表达式缓存结果，热点过滤变快 | 吃内存或磁盘；只缓存估值 ≥ 1 ms 且出现 ≥ 2 次的表达式 | [Query Path](/docs/CS/DB/Milvus/Query_Path.md) |
| `queryNode.enableSegmentFilter` / `bloomFilterApplyParallelFactor` | true / 2 | PK 谓词先做 min-max 与 bloom 段裁剪，少扫段 | 裁剪不中时白付一次过滤 | [Query Path](/docs/CS/DB/Milvus/Query_Path.md) |

## Memory Watermarks and Sizing

内存是跨组件的联锁：QuotaCenter 用「进程内存使用率」决定写限流，QueryNode 用估算量决定加载准入，StreamingNode 用 growing 字节决定封口。水位都是相对进程/容器内存上限的比值——v3.0.1 没有 queryNode/DataNode 的内存硬限额键（`queryNode.cache.memoryLimit` 已标 Deprecated），要控内存只能控工作集本身。

| 旋钮 | 默认 | 换来 | 牺牲 | 详见 |
| :--- | :--- | :--- | :--- | :--- |
| `quotaAndLimits.limitWriting.memProtection` | on，DataNode 与 QueryNode 同为 0.85 / 0.95 | 低水位起线性削 DML 速率、高水位整体拒写，保护不 OOM | 稳态内存必须留 15% 余量，否则写入被自己掐死 | [Deployment and Ops](/docs/CS/DB/Milvus/Deployment_and_Ops.md) |
| 容量反推口径（非旋钮） | QueryNode 常驻峰值（加载段+缓存+delegator）≤ 容器上限 × 0.85；DataNode 覆盖全 channel 的 delete buffer（每 channel 上限 `deleteBufBytes`）与 insert buffer | 按水位反推容量，比拍脑袋可靠 | 按峰值配，日常利用率低 | [Deployment and Ops](/docs/CS/DB/Milvus/Deployment_and_Ops.md) |
| `queryNode.loadMemoryUsageFactor` | 1 | 加载准入按估算内存乘因子预留 | 调大更保守（加载慢），调小有超卖风险 | [Query Path](/docs/CS/DB/Milvus/Query_Path.md) |
| `queryCoord.overloadedMemoryThresholdPercentage` / `memoryUsageMaxDifferencePercentage` | 90 / 30 | 节点超 90% 或两节点差超 30% 触发 sealed 段再平衡 | 搬段本身耗带宽与时间 | [Query Path](/docs/CS/DB/Milvus/Query_Path.md) |
| `queryCoord.delegatorMemoryOverloadFactor` | 0.1 | delegator 内存超标时拒新加载任务 | 敏感度过高会拖慢加载 | [Query Path](/docs/CS/DB/Milvus/Query_Path.md) |
| `streaming.flush.memoryThreshold` / `growingSegmentBytesHwmThreshold` / `growingSegmentBytesLwmThreshold` | 0.6 / 0.2 / 0.1 | StreamingNode 内存过 60% 或 growing 字节过 20% 即封口落盘，压回 10% | 频繁 flush 产生小段，压缩压力上升 | [WAL and StreamingNode](/docs/CS/DB/Milvus/WAL_and_StreamingNode.md) |

## Tiered Storage Warmup and Eviction

预热与驱逐是同一枚硬币：预热把对象存储数据提前拉进缓存换首查快，驱逐在紧水期丢缓存换内存。逐字段选 `sync / async / disable`——`sync` 段才算加载完成（首查快、加载慢），`async` 后台补（加载快、首查可能慢），`disable` 按需读。

| 旋钮 | 默认 | 换来 | 牺牲 | 详见 |
| :--- | :--- | :--- | :--- | :--- |
| `queryNode.segcore.tieredStorage.warmup.scalarField` / `scalarIndex` / `vectorIndex` / `vectorField` | sync / sync / sync / disable | 前三类默认同步预热；向量原始数据按需 | 预热吃加载时间与缓存；`vectorField` 默认 disable，首查命中向量原始数据退化为一次远程读 | [Index and Vector Engine](/docs/CS/DB/Milvus/Index_and_Vector_Engine.md) |
| `queryNode.cache.warmup` | 已废弃，默认 disable | 旧 chunk 缓存预热键 | 用 `tieredStorage.warmup` 代替 | [Index and Vector Engine](/docs/CS/DB/Milvus/Index_and_Vector_Engine.md) |
| `evictionEnabled` / `backgroundEvictionEnabled` / `evictionIntervalMs` | false / false / 1000 ms | 开启后按水位（memory 0.75/0.8、disk 0.75/0.8）周期性驱逐 | 驱逐后热点要重新拉；sync 预热的数据也会被驱逐 | [Query Path](/docs/CS/DB/Milvus/Query_Path.md) |
| `tieredStorage.cacheTtl` | 0（按时间驱逐关） | 长期未访问的 cell 自动清 | 访问间隔长的负载反复回源 | [Query Path](/docs/CS/DB/Milvus/Query_Path.md) |
| `tieredStorage.loadingTimeoutMs` / `warmupLoadingTimeoutMs` | -1（不超时）/ 0（资源预约不到即失败） | 控制缓存加载在紧水期的排队行为 | 默认 0 意味着预热抢不到资源就直接放弃 | [Query Path](/docs/CS/DB/Milvus/Query_Path.md) |
| `queryNode.segcore.enableGeometryCache` | false | GIS 负载开启后几何数据缓存提速空间谓词 | 吃内存，非 GIS 负载无收益 | [Query Path](/docs/CS/DB/Milvus/Query_Path.md) |

标注：`evictionIntervalMs`、`loadingTimeoutMs`、`warmupLoadingTimeoutMs` 不在随包 yaml 中，默认值取自 paramtable 代码；写入 yaml 时以 yaml 为准。

## Proxy Fan-out and Concurrency

shard 与分区决定写入的并行度，也决定查询的扇出：每个 shard 一条 VChannel、一个 delegator，写得更散，读就要聚得更多。

| 旋钮 | 默认 | 换来 | 牺牲 | 详见 |
| :--- | :--- | :--- | :--- | :--- |
| `proxy.maxShardNum` / `rootCoord.dmlChannelNum` | 16 / 16 | shard 多→写入按 VChannel 并行、单 shard 背压被摊薄；PChannel 池同为 16 | 查询要 fan-out 到全部 shard，result 汇聚与 delegator 内存随 shard 数上升 | [Write Path](/docs/CS/DB/Milvus/Write_Path.md) |
| `rootCoord.maxPartitionNum` | 1024 | 分区多→按 partition 裁剪更细 | 元数据规模、DDL 与加载动作变多 | [Deployment and Ops](/docs/CS/DB/Milvus/Deployment_and_Ops.md) |
| `proxy.ddlConcurrency` / `dclConcurrency` | 16 / 16 | 管理面吞吐 | 同集合 DDL 仍被 ddQueue 串行；并发过高与元数据写打挤 | [Write Path](/docs/CS/DB/Milvus/Write_Path.md) |
| `proxy.maxTaskNum` | 1024 | 入口任务队列吸收突发 | 队列打满后新请求在入口被拒 | [Write Path](/docs/CS/DB/Milvus/Write_Path.md) |
| `proxy.maxResultEntries` | -1（关闭） | 设正值可对 nq × topk × group 的结果规模设上限，防内存放大 | 极端检索会被直接拒绝 | [Query Path](/docs/CS/DB/Milvus/Query_Path.md) |
| `queryNode.grouping.*` | `maxNQ=64` `nqMergeRatio=16` `topKMergeRatio=20` | 小查询成组合并执行，吞吐升 | 合并上限越高单任务越重、拆不开的越少 | [Query Path](/docs/CS/DB/Milvus/Query_Path.md) |

## Quota Protection Defaults

`quotaAndLimits.enabled` 随包 yaml 为 `true`（代码默认 `false`，以 yaml 为准）。执行端在 Proxy 拦截器，决策端在 MixCoord 的 QuotaCenter，每轮循环重读水位——配额类故障的机制与错误码见 [Deployment and Ops](/docs/CS/DB/Milvus/Deployment_and_Ops.md) 与 [Error Model](/docs/CS/DB/Milvus/Error_Model.md)。默认开/关速查：

| 保护 | 默认 | 行为 | 备注 |
| :--- | :--- | :--- | :--- |
| `memProtection` | 开，0.85 / 0.95 | ≥0.85 线性削 DML，≥0.95 全拒写 | 「写入被拒」最常见的默认触发源 |
| `streaming.walRateLimit.nodeMemory.*` | 开（0.85 削速 / 0.90 拒 / 0.80 恢复） | StreamingNode 侧 WAL 写入的独立内存阀门，**硬拒（0.90）早于 QuotaCenter 的 0.95** | 键未导出到随包 yaml，代码默认即生效；排查「写入被拒」别只看 memProtection |
| `diskProtection` | 开，但配额全为 -1 | 只有配了 `diskQuota` 等才拦；超限拒写、delete 放行 | 默认等于不生效 |
| `flushRate` | 开，`collection.max` 0.1 QPS（全局 -1） | 单集合 flush 超过 0.1 次/秒被限 | 注释写 default no limit 与值不符，以 0.1 为准 |
| `ttProtection` | 关（`maxTimeTickDelay` 1200 s） | 开后可对 TimeTick 延迟削写 | yaml 顶部注释宣称默认开，以配置值 false 为准 |
| `dml` / `dql` / `ddl` / `indexRate` / `compactionRate` / `dbRate` | 全部关 | 需显式开启并配 max | 想限流租户时从这些开 |
| `growingSegmentsSizeProtection` | 关（0.2 / 0.4） | 开后可限制 growing 字节 | 与 streaming.flush 水位互补 |
| `l0SegmentsRowCountProtection` | 关（3000 万 / 5000 万行） | 开后可限制 L0 行数 | |
| `deleteBufferRowCountProtection` / `deleteBufferSizeProtection` | 关 | 开后可限制删除缓冲 | |
| `limitWriting.forceDeny` / `limitReading.forceDeny` | false | 手动全拒开关 | 应急处置用 |

## Symptom to Knob

指标入口、Grafana 面板与排障顺序在 [Deployment and Ops](/docs/CS/DB/Milvus/Deployment_and_Ops.md) 的观测与排障小节，这里只给「看什么 → 调哪两三个」的映射。

| 症状 | 先看什么 | 最可能的旋钮 |
| :--- | :--- | :--- |
| 写入被拒 | 被拒错误码分布 + QN/DN 内存水位 + 限流计数 | `memProtection` 水位（扩内存或降载）、`streaming.walRateLimit.nodeMemory.*`（StreamingNode 侧独立阀门）、`diskProtection.diskQuota` |
| 写入慢 | WAL append 慢日志（`streaming.logging.appendSlowThreshold` 1 s）、produce 时延、growing 字节 | `segmentAppend.maxBatchEntries/maxBatchBytes`、`segmentSyncPolicy.maxInterval`、`sealPolicy.channel.growingSegmentsMemSize` |
| 查询 P99 慢 | 慢查询日志（`slowQuerySpanInSeconds` 1 s）、调度器排队、delegator 段数 | `maxReadConcurrentRatio`、检索参数 `ef`/`nprobe`、`enableSegmentFilter` + 压缩合并小段 |
| 首查慢（冷启动或驱逐后） | 缓存命中率、mmap 缺页、加载时长 | `tieredStorage.warmup.*`（vectorField 默认 disable）、`evictionEnabled`/`cacheTtl`、`cache.readAheadPolicy` |
| 内存高（近 OOM） | QN/DN 内存曲线、growing 字节、interim index 内存 | `memExpansionRate`/`growingBuildThreadRate`、`streaming.flush` 水位、`loadMemoryUsageFactor` |
| 元数据操作慢（DDL/load 卡） | etcd 请求时延与 leader 事件、QueryCoord task 积压 | 收敛 `maxShardNum` 与分区/段数量、避开高频小 DDL（ddQueue 串行）、`proxy.ddlConcurrency` |
| 对象存储持续涨 | 存储用量曲线、compaction 与 gc 指标 | `dataCoord.gc.interval`、`compaction.levelzero.triggerInterval`、WAL `retentionPolicy.ttl` |

## Links

- [Milvus](/docs/CS/DB/Milvus/Milvus.md)
- [Query Path](/docs/CS/DB/Milvus/Query_Path.md)
- [Write Path](/docs/CS/DB/Milvus/Write_Path.md)
- [Deployment and Ops](/docs/CS/DB/Milvus/Deployment_and_Ops.md)
- [Index and Vector Engine](/docs/CS/DB/Milvus/Index_and_Vector_Engine.md)
- [Compaction and Lifecycle](/docs/CS/DB/Milvus/Compaction_and_Lifecycle.md)

## References

- [Milvus v3.0.1 milvus.yaml](https://github.com/milvus-io/milvus/blob/v3.0.1/configs/milvus.yaml)
- [Milvus v3.0.1 component_param.go](https://github.com/milvus-io/milvus/blob/v3.0.1/pkg/util/paramtable/component_param.go)
- [Milvus v3.0.1 quota_param.go](https://github.com/milvus-io/milvus/blob/v3.0.1/pkg/util/paramtable/quota_param.go)
- [Milvus v3.0.1 autoindex_param_nocuda.go](https://github.com/milvus-io/milvus/blob/v3.0.1/pkg/util/paramtable/autoindex_param_nocuda.go)
- [Milvus v3.0.1 datanode index util.go](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/datanode/index/util.go)
- [Milvus v3.0.1 delegator_twostage.go](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/querynodev2/delegator/delegator_twostage.go)
- [Milvus v3.0.1 Release Notes](https://github.com/milvus-io/milvus/releases/tag/v3.0.1)
