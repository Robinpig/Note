## Introduction

Kafka 与 Pulsar 提供的是「独立 MQ 集群」形态的 WAL：数据先写 broker，由 broker 负责副本复制与保留，Milvus 只是其上的一个消费者。这带来一套固定运维成本——集群要部署、扩容、调优、跨 AZ 保活，而这份数据只服务 Milvus 一家。Woodpecker 是 Zilliz 为 Milvus 自研的云原生 WAL 引擎（仓库 `github.com/zilliztech/woodpecker`，Milvus 依赖 v0.1.38）：它把持久化层交给对象存储，把排队与复制收进客户端与轻量 LogStore，设计上沿用 BookKeeper 式分布式日志的分段模型，目标是比独立 MQ 更低的运维成本与跨 AZ 网络开销。

在 Milvus 里它是第四种 WAL 后端，v2.6 以 Embed 模式引入，Service 模式在 3.0 系列加入（v3.0.0 已含，非 v3.0.1 新增）。两者的取舍是全篇主线：Embed 零额外常驻服务，但写入攒批、单条延迟略高；Service 引入一个可选的 LogStore 副本组，换来低延迟写入与拓扑感知的副本放置。`configs/milvus.yaml` 注释明确建议新实例显式选 Woodpecker。

边界：四后端横向对比与选择算法在 [Deployment and Ops](/docs/CS/DB/Milvus/Deployment_and_Ops.md)（含选型表，本篇不复制）；WAL 抽象层、PChannel/VChannel 与 append/consume/broadcast 协议归 [WAL and StreamingNode](/docs/CS/DB/Milvus/WAL_and_StreamingNode.md)；端到端写链路归 [Write Path](/docs/CS/DB/Milvus/Write_Path.md)；集群部署实操归 [Deploy](/docs/CS/DB/Milvus/Deploy.md)。本篇聚焦集成点、两种模式的数据路径、存储布局、quorum、fence、retention 与配置面。

## Position in Milvus

Milvus 的 WAL 后端按注册制装配：每个后端实现一个 builder 注册自己的 `message.WALName`。Woodpecker 的实现位于 `pkg/streaming/walimpls/impls/wp/`，注册名 `WALNameWoodpecker`，字符串 "woodpecker"。选择由 `mq.type` 决定，可选值 `default / pulsar / kafka / rocksmq / woodpecker`；`default` 的解析优先级是 standalone 下 rocksmq > Pulsar > Kafka > Woodpecker，cluster 下 Pulsar > Kafka > Woodpecker。Woodpecker 是否参与 default 竞争看 `woodpecker.meta.prefix` 是否为空——默认 "woodpecker"，即默认配置下它总在候选里。

`mq.type` 不可热切：启动时 `util.InitAndSelectWALName()` 解析出具体名字并注册为进程默认，协调者再用 `ProcessImmutableConfigs` 将其固化进 etcd，此后全集群角色读到同一个 WAL 选择；解析结果故意不写回本进程配置 overlay，否则 overlay 会长期盖过 etcd 源，让后续切换对进程不可见。

选中后，opener 的 `Open` 对每个 PChannel 执行 `LogExists → CreateLog → OpenLog → OpenLogWriter`，即一个 PChannel 对应一个 log，log 名就是 channel 名。`Append` 把消息交给 log writer 并返回 `{SegmentId, EntryId}` 二元组消息 ID（base64 序列化，先比 Segment 再比 Entry）；`Read` 支持 All/Latest/StartFrom/StartAfter 四种 deliver policy。与 Kafka/Pulsar 的本质差异是谁负责持久化：broker 形态由 MQ 集群收下并复制数据；Woodpecker 的权威副本最终在对象存储，副本组只承担低延迟与仲裁，复制协调发生在客户端进程内。写栅栏的可见信号是 `ErrLogWriterLockLost`，Milvus 把它标记成 `walimpls.ErrFenced` 传播；且 WAL 只在 read-write 模式下允许 `Append`/`Truncate`，否则直接 panic（按编程错误处理）。

## Embed and Service Modes

builder 按 `woodpecker.storage.type` 分流：`minio` / `local` 走 Embed，`service` 走 Service。

| 维度 | Embed | Service |
| --- | --- | --- |
| `storage.type` | `minio` 或 `local` | `service` |
| 客户端 | `NewEmbedClient`，log store 在 Milvus 进程内 | `NewClient`，经 gRPC 连独立 LogStore 集群 |
| 额外常驻服务 | 无，仅 etcd + 对象存储 | LogStore 副本组 3 或 5 节点 |
| 数据路径 | 内存攒批，直接写对象存储或本地盘 | 先写 LogStore 本地盘，rolling/compaction 后上传对象存储 |
| 引入版本 | 2.6 | 3.0 |
| 适用 | 吞吐优先、可接受攒批延迟、单实例 | 低延迟生产集群、跨 AZ 拓扑感知 |

Embed 的关键词是零额外基础设施：LogStore 逻辑作为库嵌进 Milvus 进程，持久化直接落到 `minio` 或 `local`。代价是所有写入按 sync 策略攒批，单条消息的确认延迟上界约等于一个 sync 间隔；`local` 还只允许单机（见 Storage Layout）。Service 模式把 LogStore 拆为独立进程，节点间用 HashiCorp memberlist gossip 互相发现（v0.1.38 的 go.mod 额外 pin 了一个 hotfix fork；gossip 的完整用途属 woodpecker 仓库行为），写入先落节点本地盘，segment rolling 后整段上传对象存储，本地只留最近少量未 rolling 的 segment，以压缩恢复面与本地存储成本。

## Data Path and Sync Cadence

客户端写入面由 `woodpecker.client.segmentAppend` 控制：`queueSize` 10000、`maxRetries` 3，以及两个 group commit 键——`maxBatchEntries` 1000 与 `maxBatchBytes` 2MB。合批是机会主义的：只合并已在队列里的 append，低负载不引入额外等待；`maxBatchEntries` 设为 1 即关闭。builder 对这两个键有保护逻辑，但两者语义不同：解析失败或负值会回退 Woodpecker 内置默认并打 warn——因为 woodpecker 会把 `maxBatchEntries <= 0` 静默钳到 1，反而关掉合批；而显式写 `"0"` 的 `maxBatchBytes` 会原样透传，其语义是解除字节上限。段由 `segmentRollingPolicy` 滚动：`maxSize` 256M、`maxInterval` 10m、`maxBlocks` 1000，任一满足即滚。

sync 策略决定缓冲刷出到持久介质的节奏，即 durability 窗口的上界。Milvus 的 yaml 默认与 Woodpecker 内置默认刻意不同，builder 会用 Milvus 值覆盖：

| 键 | Milvus 默认 | Woodpecker 内置默认 | 语义 |
| --- | --- | --- | --- |
| `segmentSyncPolicy.maxInterval` | 200ms | 1000ms | 两次 sync 的最大间隔 |
| `segmentSyncPolicy.maxIntervalForLocalStorage` | 10ms | 5ms | 本地盘模式的 sync 间隔 |
| `segmentSyncPolicy.maxIntervalForService` | 10ms | 1ms | 只被 service 模式 LogStore 服务端消费 |
| `segmentSyncPolicy.maxEntries` / `maxBytes` | 10000 / 256M | 2000 / 100M | 缓冲触发 sync 的条目数 / 字节数 |
| `segmentSyncPolicy.maxFlushSize` / `maxFlushThreads` | 2M / 32 | 16M / 8 | 单个 flush 分片上限 / flush 线程数 |
| `segmentCompactionPolicy.maxSize` | 2M | - | 合并后文件上限；并行上传 4、并行读 8 |

Service 模式的落盘是两级 staged storage：活跃 block 先写 LogStore 本地盘，compaction 把块合并后上传对象存储；`maxIntervalForService` 只在这个服务端 staged writer 里生效，Milvus 进程并不消费它——`milvus.yaml` 里的该键是给独立部署的 woodpecker 服务端用的配置面，注释特意说明它相对内置 1ms 的默认会放宽 sync 节奏。间隔越大，单次 flush 合并越多条目、QPS 越高，代价是额外的持久性延迟。

## Storage Layout and Types

| `storage.type` | 模式 | 约束 | 持久化位置 |
| --- | --- | --- | --- |
| `minio` | Embed | 需要对象存储 | 对象存储 |
| `local` | Embed | 仅单机；cluster 下启动即 panic | 本地盘 |
| `service` | Service | 需可达的 LogStore 集群 | 本地盘 staged + 对象存储 |

- 本地根目录：`woodpecker.storage.rootPath` 默认为 "default" 时取 `localStorage.path` 加 `/wp` 子目录，显式配置则原样使用；集群模式用 `local` 会被 `validateWALName` 拒绝并 panic，唯一逃生门是 `woodpecker.storage.forceLocalStorage`（默认 false、未导出、注释明确不推荐）。
- 对象存储：bucket 复用 Milvus 的 `minio.bucketName`，前缀是 `minio.rootPath` 加 `/wp`，凭据、SSL、region 全部复用 Milvus 的 minio 配置段。
- 元数据：只支持 etcd（`woodpecker.meta.type` 仅 `etcd`），`woodpecker.meta.prefix` 默认 "woodpecker"，叠在 `etcd.rootPath` 之下；带历史前缀兼容——检测到旧根下已有 woodpecker 元数据就沿用旧前缀。
- 对象键布局：每个 segment 一个目录 `{baseDir}/{logId}/{segmentId}/`，内含数据块 `m_*.blk`、footer `footer.blk` 与写锁对象 `write.lock`（fence 用，见下节）。

## Quorum and Replica Placement

Service 模式下 `woodpecker.client.quorum` 决定副本组的组成与位置：

- `replicas`：ensemble 大小 E，只接受 3 或 5，默认 3；`quorumSelectStrategy.strategy` 支持 `random`、`random-group`、`single-az-single-rg`、`single-az-multi-rg`、`multi-az-single-rg`、`multi-az-multi-rg`、`cross-region`、`custom`，`custom` 需配 `customPlacement` 逐副本指定 region/az/resourceGroup。
- `quorumBufferPools`：JSON 数组的节点分组，每组 `name` + `seeds`；seeds 指向 LogStore 节点的 seed 地址（官方 compose 模板里即 gossip 端口），用于按区域/用途圈定候选节点。
- `affinityMode`：`soft` 优先但不强制、`hard` 严格（节点凑不齐即失败）。

仲裁语义按 woodpecker v0.1.38 源码：写仲裁 WQ = E（数据要发往全部副本），确认仲裁 AQ = (WQ/2)+1（拿到多数确认即对调用方成功，E=3 时 2 个）；因此 3 副本可容忍 1 个节点不可用；客户端与副本之间的具体发送与转发路径属 woodpecker 仓库行为，本仓库只能核实到上述仲裁公式与副本数配置。这些键在 Milvus 侧都是 refreshable：builder 把 Milvus 动态配置绑定为 woodpecker 的运行时源（Milvus 为准），quorum 在每个 segment 选择时重新读取，所以 etcd 改配下一个 segment 生效、不必重启；JSON 类键（bufferPools、customPlacement）解析失败则回退 woodpecker 静态默认，启动时校验一次并打 warn。故障恢复层面，节点经 gossip 剔除与新节点加入属 woodpecker 仓库行为，Milvus 侧只能核实到 memberlist 依赖与 seeds 配置面。

## Fence and Condition Write

Embed 模式（对象存储直写路径）没有独立协调者，防脑裂靠对象存储条件写：`woodpecker.logstore.fencePolicy.conditionWrite` 取值 `auto / enable / disable`（默认 auto）。打开后写锁对象 `write.lock` 用 `PutObjectIfNoneMatch`（即 `If-None-Match: *`）原子创建，陈旧 writer 的写会被对象存储以 precondition 失败拒绝，封死同一 log 双 writer 的窗口。

auto 的判定发生在 embed client 构造期：先查 etcd 是否已有历史判定，有则沿用；没有则实际探测对象存储能力——成功把 true 持久化，失败直接报错，且从不持久化 false。`enable` 忽略已存的 false 强制重验，`disable` 直接跳过探测。Milvus 侧收到的信号是 `ErrLogWriterLockLost`，被标记为 `walimpls.ErrFenced` 供上层识别通道所有权失效。Service 模式不走条件写：staged writer 用 quorum fence 机制在同一段上收敛出唯一 writer（v0.1.38 源码注释即 quorum fence），更细的仲裁过程依赖 woodpecker 仓库行为。

## Retention and Direct Read

`woodpecker.logstore.retentionPolicy.ttl` 默认 72h，语义是 truncated segment 过期后才可被 GC——约束回收时机，不是消息被截断的条件；截断由 StreamingNode 的 truncate 流程驱动。Milvus 侧该键的回退键是 `streaming.walTruncate.retentionInterval`。

`woodpecker.client.directRead` 是 Service 模式的读优化，默认开启：`enabled` true 表示 sealed segment 由客户端直接从对象存储读取，不回落 LogStore 本地；`maxBatchSize` 16M、`maxFetchThreads` 4 控制批量与并发。动机是省掉「本地盘再存一份已 sealed 数据」的持久化面：sealed segment 的权威副本在对象存储，直读使它不依赖 LogStore 本地状态，读路径也不挤占写入的本地 I/O。三个键均为非 refreshable，启动期固化。

## Deployment Switches

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `mq.type` | default | 设为 `woodpecker` 即启用；启动固化进 etcd，不可热切 |
| `woodpecker.meta.type` / `meta.prefix` | etcd / woodpecker | 元数据只支持 etcd，前缀叠在 `etcd.rootPath` 下 |
| `woodpecker.storage.type` | minio | `minio`/`local` 走 Embed，`service` 走 Service 模式 |
| `woodpecker.storage.rootPath` | default | default 时取 `localStorage.path` 加 `/wp` |
| `woodpecker.storage.forceLocalStorage` | false | 集群强制 local 的逃生门，未导出、不推荐 |
| `woodpecker.client.auditor.maxInterval` | 10s | 客户端对 log 状态的自审计节奏 |

另一个运维注意点：v3.0.1 的 MQ 健康检查对 Woodpecker 尚未实现，`factory.go` 直接返回 `Health = true`（源码标注 TODO），部署后应靠 LogStore 自身指标与 gossip 状态监控，不要把该健康位当真实探测。

## Links

- [Milvus](/docs/CS/DB/Milvus/Milvus.md)
- [WAL and StreamingNode](/docs/CS/DB/Milvus/WAL_and_StreamingNode.md)
- [Write Path](/docs/CS/DB/Milvus/Write_Path.md)
- [Deployment and Ops](/docs/CS/DB/Milvus/Deployment_and_Ops.md)
- [WAL](/docs/CS/DB/Concept/WAL.md)
- [Message Queues](/docs/CS/MQ/MQ.md)

## References

- [Woodpecker repository](https://github.com/zilliztech/woodpecker)
- [Woodpecker documentation](https://zilliztech.github.io/woodpecker/docs.html)
- [Woodpecker configuration reference](https://zilliztech.github.io/woodpecker/configuration.html)
- [Woodpecker v0.1.38](https://github.com/zilliztech/woodpecker/releases/tag/v0.1.38)
- [Milvus v3.0.1](https://github.com/milvus-io/milvus/releases/tag/v3.0.1)
- [Milvus Woodpecker integration](https://github.com/milvus-io/milvus/tree/v3.0.1/pkg/streaming/walimpls/impls/wp)
- [Apache BookKeeper](https://github.com/apache/bookkeeper)
