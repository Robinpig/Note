## Introduction

单集群内部的高可用解决的是「同一份数据、多个副本」的问题：PChannel 的 Term 栅栏、协调器 active-standby、节点失联后的再分配，都在一个故障域里完成。但它回答不了另一类问题：整个集群或整个机房不可用怎么办，能不能在另一个集群就近读、只让主集群承写，以及如何把数据平滑迁移到新集群。这些只能靠**第二个集群里的逻辑数据副本**来解决，落地机制就是跨集群复制，Milvus 里以 CDC 命名。

Milvus 的复制刻意**不是「拷贝数据文件」**。对象存储里的 binlog、manifest 与索引只覆盖已落盘的历史：growing segment、delete 操作、schema 变更、还没 flush 的写入都不在其中，而快照也无法表达「切换那一刻的一致点」。所以复制的对象是 **WAL 变更流**：source 集群的 CDC 从本集群 WAL 读出消息，经 gRPC 转发给 target 集群的 Proxy，Proxy 把它 append 进 target 自己的 WAL，之后 target 集群的 StreamingNode 照常落盘、QueryNode 照常消费——落盘、索引、查询链路对复制完全无感知。复制保的是**变更流**，不是存储快照。

角色上默认是单写多读：primary 接受读写，standby 只读、拒写。本库 WAL 基础设施（PChannel/VChannel、append/consume、拦截器链）见 [WAL and StreamingNode](/docs/CS/DB/Milvus/WAL_and_StreamingNode.md)，端到端写链路见 [Write Path](/docs/CS/DB/Milvus/Write_Path.md)，副本与 HA 的语境见 [Deployment and Ops](/docs/CS/DB/Milvus/Deployment_and_Ops.md)。本篇只讲跨集群这条线：CDC 角色装配、复制流的建立、消息过滤与去重、切换语义与运维限制。

## Roles and Process Model

`milvus run cdc` 走的装配链是 `typeutil.CDCRole` → `MilvusRoles.EnableCDC` → `components.NewCDC`，入口在 `internal/distributed/cdc/service.go`。它与其它角色最大的区别：**CDC 不监听任何 gRPC 端口**，对外不提供业务 RPC，只做两件事——连 etcd、把「以本集群为 source」的复制任务跑起来。因此 CDC 进程的扩容不涉及端口与路由，健康状态只体现在组件状态上报里。

`Server.Prepare` 为空；`Run` 先 `init`：拿共享 etcd 客户端（`kvfactory.GetEtcdAndPath`），然后 `resource.Init` 注入两项资源——etcd 客户端与 `replicatemanager.NewReplicateManager()`（实现 `resource.Resource()` 单例，供各子模块取用）。`NewCDCServer` 内部只持有一个 `controller.Controller`；`Start()` 仅启动 controller 的 watch 循环，`Stop()` 停 controller 并关闭 ReplicateManager。

| 组件 | 所在包 | 职责 |
| :--- | :--- | :--- |
| Controller | `internal/cdc/controller` | watch etcd 中 `replicating-pchannel/` 前缀元数据，按事件增删 replicator |
| ReplicateManager | `internal/cdc/replication/replicatemanager` | 进程内 replicator 注册表，key 为 `metaKey/_v<modRevision>` |
| ChannelReplicator | `replicatemanager.channelReplicator` | 一条 source PChannel 到 target PChannel 边的复制循环 |
| ReplicateStreamClient | `internal/cdc/replication/replicatestream` | 对 target Proxy 的双向流、确认收集、断线重连 |
| MilvusClient | `internal/cdc/cluster` | 以 target 集群的 URI/token 建连，提供 `GetReplicateInfo` 与 `CreateReplicateStream` |

主从两侧的分工由**出边**决定：controller 对每条元数据只处理 `SourceChannelName` 里包含本地 cluster id 的条目，即「以我为 source」的边才建 replicator；从集群的 etcd 里同样有自己视角的复制配置，但不会去跑别人的出边。所以部署原则是：每个可能成为 source 的集群（当前 primary，以及切换后要接棒的 standby）都需要一个 CDC 实例。

## Replication Topology and Config Delivery

拓扑变更的唯一入口是 Proxy 的 `UpdateReplicateConfiguration`，它转给 `streaming.WAL().Replicate()`，最终到达 streamingcoord 的 assignment 服务。该服务先做幂等检查（配置相同直接成功），然后以**排他的集群级资源锁** `NewExclusiveClusterResourceKey` 发起一次广播，消息类型为 `AlterReplicateConfig`。在非 primary 集群上调用会因 `broadcast.ErrNotPrimary` 失败，此时服务端不退化成报错，而是 `waitUntilPrimaryChangeOrConfigurationSame`：等待复制把新配置带到本地后再返回——多集群 A/B/C 各自调用一次接口、全部返回即视为配置已同步。

消息作为广播写入所有 PChannel 并收获各通道 ack 后，broadcaster 执行 ack 回调 `alterReplicateConfiguration`，进而由 `balancer/channel` 的 `ChannelManager` 完成三件事：解析出本集群在配置图中的角色与 target 列表、保存 `ReplicateConfigurationMeta`（含是否由 force promote 产生）、以及由 `getNewIncomingTask` 生成**新增的复制任务**。从集群侧的同一机制由复制流触发：`getOrCreateBroadcastTask` 见到未知的、带 `ReplicateHeader` 的广播消息就为它登记 `REPLICATED` 态任务，同一 ack 回调据此在从集群本地应用配置——因此每个集群都会落地**自己视角**的配置与出边任务。只有新增 pchannel（或新出现的目标边）才生成任务，已存在的不重复建。每个任务写成一条 `streamingpb.ReplicatePChannelMeta`，etcd 键格式为 `replicating-pchannel/<targetClusterID>-<sourceChannelName>`。

任务里的 `InitializedCheckpoint` 语义要特别注意：它取**配置广播消息自身落 WAL 的结果**（`LastConfirmedMessageID` 与 TimeTick），代表「从这条配置消息之后开始复制」。这样无论 CDC 何时启动、target 端有没有已存 checkpoint，复制的起点都有一个确定且两端一致的锚点。对「新增 pchannel」型任务还有 `SkipGetReplicateCheckpoint` 标记：新 pchannel 在从集群还没收到配置消息，`GetReplicateInfo` 必然失败，直接使用 InitializedCheckpoint，并把 TimeTick 减一，好让配置消息本身被扫描到（扫描用严格大于的时间过滤）。

## Replicator per PChannel

CDC 进程启动后，controller 先做一轮恢复：`ListReplicatePChannels` 拉全部元数据，对每条 source 匹配本集群的条目调 `CreateReplicator`，再以 `RemoveOutdatedReplicators` 清掉已经不在 etcd 里的 replicator；随后从 `Revision + 1` 开始 watch，PUT 事件建 replicator，DELETE 事件删 replicator。删除操作带 **ModRevision 条件**：`RemoveReplicatePChannelWithRevision` 用 etcd 事务比较版本号后才真正删 key，用来消解主从连续切换时 Save/Delete 的乱序（期望 `[Save, Delete, Save]` 却可能观察到 `[Save, Save, Delete]`）。

ReplicateManager 用 `metaKey/_v<modRevision>` 作为 replicator 的键——**同一 pchannel 的元数据每被改写一次（revision 变化）就是新一代 replicator**，旧代的停止与新一代的启动互不覆盖。每条复制边的生命周期由 `channelReplicator` 承载，它同时持有三个部件：

- `targetClient`：`cluster.NewMilvusClient` 以 target 集群的 `ConnectionParam` 的 Uri 与 Token 建连，TLS 按 `tls.clusters.<clusterID>` 配置逐集群加载，grpc authority 也按目标集群查询；
- `msgScanner`：`streaming.WAL().Read` 读本集群 source PChannel，`DeliverPolicyStartFrom(cp.MessageID)` 且 `DeliverFilterTimeTickGT(cp.TimeTick)`，并带 `IgnorePauseConsumption`，保证 CDC 内置消费者不受普通消费暂停逻辑影响；
- `streamClient`：`replicatestream.NewReplicateStreamClient`，负责与 target 的流与确认。

扫描起点来自 target 端的确认：`GetReplicateInfo{SourceClusterId, TargetPchannel}` 问 target 要到最新 checkpoint；若 target 尚无该 channel 的复制状态或返回空，则回退到 InitializedCheckpoint「从头开始」。初始化失败不 panic，而是循环重试；链路断开会由 stream client 内部以指数退避（100ms 起、上限 10s）重连，重连后 `SeekToHead` 重发所有未确认消息。从集群侧流量的唯一入口是 Proxy 的 `CreateReplicateStream` 双向流。

## Source Side Selective Forwarding

source 侧并非「见消息就转」，复制循环 `streamClient.Replicate(msg)` 先做两道过滤，命中即返回 `ErrReplicateIgnored`（consume loop 视为正常）：

| 判定 | 覆盖的消息 | 为什么不复制 |
| :--- | :--- | :--- |
| `MessageType.IsSelfControlled()` | `TimeTick`、`CreateSegment`、`Flush` | 由各集群 WAL 系统自己生成，是本地时序与落盘的内部产物 |
| `ImmutableMessage.IsUnreplicable()` | 带 `_ur` 属性的消息 | 显式标记为「不安全复制」，由生产方按语义打上，如本地专属资源相关操作 |

事务消息在发送时展开：`sendLoop` 遇到 `MessageTypeTxn` 会拆成 begin、body 序列、commit 分别发送，保证 target 端看到完整事务边界。发送格式是 `ReplicateRequest_ReplicateMessage`，携带源集群 id 与原始 immutable message 的 Id/Payload/Properties，而不是解析后的业务语义——**转发的仍然是 WAL 日志本身**。

转发使用一个有界队列 `pendingMessages`：容量与总字节数分别受 `streaming.replication.pendingMessagesQueueLength`（默认 128）与 `pendingMessagesQueueMaxSize`（默认 128MB）约束。target 端回 `ReplicateConfirmedMessageInfo{ConfirmedTimeTick}` 后，队列里所有 TimeTick 不大于该水位的消息被清理，并触发 OnConfirmed 指标。需要留意的确认约定：**事务只有 commit 消息会得到确认**（begin 与 body 不回），因此事务的复制进度天然按 CommitTxn 推进；非事务消息逐条确认。

## Secondary Side Append Path

从集群把 `CreateReplicateStream` 视为一条普通写路径：`ReplicateStreamServer` 的前台 `recvLoop` 收到 `ReplicateMessage` 后，用 `message.NewReplicateMessage` 重建消息，调 `streaming.WAL().Replicate().Append`。这个入口不落地到任何面向用户的 API，Proxy 侧仅保留给复制流使用，权限上按集群级操作授权。

Append 之前会经过 `replicateService.overwriteReplicateMessage` 的改写与校验，这是从集群接受复制的核心关卡：

- **类型过滤**：消息类型命中 `streaming.replication.skipMessageTypes` 时直接以 `IgnoreOperation` 拒绝（服务端仍给源端回确认），默认列表是 `AlterResourceGroup,DropResourceGroup`；
- **角色校验**：本地角色是 primary 时拒收复制的消息（`ReplicateViolation`）；源集群 id 必须在配置中存在；
- **通道重映射**：按配置把源 vchannel 里的 PChannel 换成 target PChannel（`funcutil.ToPhysicalChannel` 剥出物理通道后查映射），广播消息里的 vchannel 列表同样逐个重映射；`CreateCollection` 消息 body 里的 `PhysicalChannelNames`/`VirtualChannelNames` 不能漏——它们写死在新集合的元数据里；
- **配置类消息改写**：`AlterReplicateConfig` 若是「新增 pchannel」型，用消息头里的新配置做映射；若本地已不在新配置里（被移出拓扑），改写为「只有自己的单集群 primary 配置」；`AlterLoadConfig` 在 `streaming.replication.useLocalReplicaConfig`（默认 true）时打上 `UseLocalReplicaConfig`，让从集群保留自己的副本配置而不盲从主集群。

改写后的消息 `appendReplicateMessageToWAL` 写入 target vchannel，随后进入 WAL 的 replicate 拦截器（拦截器链位置见 [WAL and StreamingNode](/docs/CS/DB/Milvus/WAL_and_StreamingNode.md)）。拦截器承担两个职责：对 `AlterReplicateConfig` 消息在 append 前调用 `SwitchReplicateMode` 切换本集群的角色状态（primary 丢弃 secondary 状态；secondary 记录源集群并重建 secondary 状态），对普通消息则走 `BeginReplicateMessage` 的角色与去重校验。

skipMessageTypes 还有一个容易忽略的配套动作：被跳过的类型不是被丢弃，而是**在从集群本地直应用**。以 Resource Group DDL 为例，QueryCoord 的 DDL 回调在 `broadcast.ErrNotPrimary` 且类型命中 skip 列表时，绕过广播、在本集群直接执行（`shouldApplyLocallyOnNonPrimary`）。因为从集群的 RG 是集群本地概念，从主集群复制过来既无意义、还会因「非 primary 不能广播」而失败。

## Duplicates and Checkpoints

复制流的重连语义是「至少一次」：stream client 重连后从队列头重发，源端重启后从 InitializedCheckpoint 或 target 端 checkpoint 重扫，重复消息必然存在，必须由从集群吸收。去重发生在 secondary 状态里：

- 每条复制消息的 `ReplicateHeader` 带源集群 id、源 TimeTick 与 LastConfirmedMessageID；若 TimeTick 不大于 checkpoint 水位，判为「太旧」直接 `IgnoreOperation`（服务端给源端回确认，推进源端队列）；
- 事务消息例外：同一笔在途事务的 body 共享同一 TimeTick，用严格小于比较后交给 txn helper 按消息 id 去重，避免误伤同为一段事务的相邻消息；
- checkpoint 只在**提交点**前推：事务在 commit 消息 append 成功后推进（begin 与 body 不推进），非事务消息在 append 成功后推进。

从集群重启时 secondary 状态不靠 etcd 保存，而是从 WAL 恢复快照重建（`RecoverReplicateManager` 读取恢复检查点与未提交事务缓冲，按源集群 id 过滤出「从源集群复制来且未提交」的事务继续跟踪）。强制切换时还有一层兜底：提升为 primary 前会把当时的 checkpoint 克隆为 **salvage checkpoint** 按源集群 id 存下。之后 `GetReplicateInfo` 同时返回实时 checkpoint 与按源集群 id 过滤出的那个 salvage checkpoint；此时本地已不是 secondary、实时 checkpoint 不可取，Proxy 对 `ReplicateViolation` 的处理是「降级为只返回 salvage」而不是报错——切换后调用方真正需要的恰恰是它，供运维判断复制停在哪里。

## Switchover and Failover Semantics

计划切换与强制切换走同一条配置广播，区别在消息头：`AlterReplicateConfig` 可以带 `ForcePromote` 与 `Ignore` 两种标记。ForcePromote 在 WAL 拦截器里的处理顺序是「先 append 配置消息，再回滚全部在途事务」（`RollbackAllInFlightTransactions`），保证切换后不残留半提交事务；同时把当时的 secondary checkpoint 存为 salvage。`Ignore` 用于强制切换后补发的、已失去意义的残缺切换消息：拦截器、ack 回调、复制客户端三处见到该标记都只把它当作普通日志写下去，不切换状态、不触发删除。

从集群「只读」的强制性落在 WAL 层：secondary 角色下，凡是不带 `ReplicateHeader` 的消息（即本地客户端直接 append 的写入）都会被拒为 `ReplicateViolation`，因为 secondary 角色的 WAL 只接受复制消息。反过来，一条复制边的消失也是自感知的：复制客户端在确认到一条使「本边不再存在」的配置消息后，用 `RemoveReplicatePChannelWithRevision` 条件删除自己的 etcd 元数据；consume loop 侧等 `BlockUntilFinish` 收尾后同步删除该边的 lag 指标序列，etcd 的 DELETE 事件再驱动 controller 走标准清理路径。

## Operations and Observability

CDC 没有独立 RPC 面，运行状态主要看三处：Prometheus 指标、Proxy 的配置查询接口、以及 etcd 里的复制元数据。

| 指标 | 含义 |
| :--- | :--- |
| `replicated_messages_total` / `replicated_bytes_total` | 已复制消息数与字节数 |
| `replicate_end_to_end_latency` | 单条消息从源端发送到确认的端到端延迟 |
| `last_replicated_time_tick` | 最近被复制消息的 TimeTick，按 source/target channel 打标 |
| `stream_rpc_connections` / `stream_rpc_reconnect_times` | 复制流的连接状态与重连次数 |

复制延迟（CDC lag）等于主集群当前 TimeTick 与 `last_replicated_time_tick` 之差；后者以秒为单位的物理时间呈现，断连期间由已确认位置保守回填，避免「序列缺失读作零延迟」。接口层面：`GetReplicateConfiguration` 读配置，`GetReplicateInfo` 读某 target PChannel 的 checkpoint 与 salvage checkpoint；两条都经由 Proxy，从集群同样可查。

运维限制集中在 import：处于复制拓扑中的集群默认**禁止 import**（`dataCoord.import.enableInReplicatingCluster` 默认 false）。放开后只接受两阶段提交模式（`auto_commit=false`）——import 的第一阶段写临时文件、第二阶段才广播 `CommitImport`，这样主从两端要么都提交、要么都回滚；若源集群的 2PC import 最终失败，其 GC 会先广播 `RollbackImport` 释放从集群侧复制出来的 Uncommitted 任务，再从本地清除任务记录，避免从集群被一个无人回收的任务悬空。import 本身的调度细节见 [Compaction and Lifecycle](/docs/CS/DB/Milvus/Compaction_and_Lifecycle.md)。

| 配置键 | 默认值 | 语义 |
| :--- | :--- | :--- |
| `streaming.replication.skipMessageTypes` | `AlterResourceGroup,DropResourceGroup` | 从集群 replicate stream 忽略的消息类型，配套本地直应用 |
| `streaming.replication.useLocalReplicaConfig` | true | 复制来的 `AlterLoadConfig` 使用从集群本地副本配置 |
| `streaming.replication.pendingMessagesQueueLength` | 128 | 每复制流客户端待确认消息队列条数上限 |
| `streaming.replication.pendingMessagesQueueMaxSize` | 134217728 | 上述队列字节上限，默认 128MB |
| `dataCoord.import.enableInReplicatingCluster` | false | 是否允许复制中的集群执行 2PC import |

## Links

- [Milvus](/docs/CS/DB/Milvus/Milvus.md)
- [WAL and StreamingNode](/docs/CS/DB/Milvus/WAL_and_StreamingNode.md)
- [Write Path](/docs/CS/DB/Milvus/Write_Path.md)
- [Deployment and Ops](/docs/CS/DB/Milvus/Deployment_and_Ops.md)
- [Compaction and Lifecycle](/docs/CS/DB/Milvus/Compaction_and_Lifecycle.md)
- [Distributed Systems](/docs/CS/Distributed/Distributed.md)

## References

- [Milvus CDC Server](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/cdc/server.go)
- [Milvus CDC Controller](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/cdc/controller/controller.go)
- [Channel Replicator](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/cdc/replication/replicatemanager/channel_replicator.go)
- [Replicate Stream Client](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/cdc/replication/replicatestream/replicate_stream_client_impl.go)
- [Replicate Stream Server](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/proxy/replicate/replicate_stream_server.go)
- [Replicate Service](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/distributed/streaming/replicate_service.go)
