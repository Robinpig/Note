## Introduction

Milvus 3.0 相对 2.x 最大的一次架构迁移，是把「日志」从一条旁路的消息总线，升格为整个系统**唯一的事实来源（single source of truth）**。2.x 里存在两条并行的写路径：一条走消息流，一条走独立的数据节点落盘。3.0 把它们收敛成一条——**所有数据变更只往 WAL append，读、恢复、复制一律以 WAL 为准**。这一收敛的落地载体就是 StreamingNode：它是 WAL 分区的持有者与落盘者，其它组件通过进程内库访问它。这里的「持有」是**按 PChannel 计**的：集群里同时运行多个 StreamingNode，一个 PChannel 在任意时刻只有唯一持有者，而一个节点会持有多个 PChannel——不存在持有整个 WAL 的单点。

这套设计的代价是必须回答三个约束同时成立的问题：**多个 collection 要共享同一条物理日志**（否则 topic 数随 collection 爆炸），**单个 collection 内部要严格保序**（否则事务与 segment 分配无法定义），**集群级广播要有唯一排序点**（否则 RBAC 这类跨库变更在哪个副本上先生效不确定）。Milvus 用 PChannel / VChannel / CChannel 三层通道模型来同时满足它们。本篇讲清这层地基：WAL 后端抽象、三层通道、PChannel 归属与 Term fencing、TimeTick 与 tSafe、msgdispatcher 消费模型，以及 WAL 保留与 checkpoint 的关系。

边界之外的事各归其篇：端到端业务写链路见 [Write Path](/docs/CS/DB/Milvus/Write_Path.md)，查询侧如何等待 tSafe 见 [Query Path](/docs/CS/DB/Milvus/Query_Path.md)，Woodpecker 的部署与选型见 [Deployment and Ops](/docs/CS/DB/Milvus/Deployment_and_Ops.md)，WAL 落盘后的对象存储文件与格式见 [Storage Layer](/docs/CS/DB/Milvus/Storage_Layer.md)。

## WAL Backend Abstraction

WAL 的后端可替换，抽象点是 `pkg/streaming/walimpls/` 下的统一接口 `WALImpls`，暴露 `Append`、`Read`（返回一个 `ScannerImpls`）与 `Truncate` 三族方法。每个后端把 PChannel 一一映射为自身的一个 topic / partition，从而让「一个 PChannel 一条独立日志」这一语义在任意后端上等价。

后端选择由配置项 `mq.type` 决定，它是 **immutable**（`Version: 2.3.0`，`DefaultValue: default`）。启动时 `cmd/roles` 会把解析后的真实 walName 固化进 etcd，运行期不再切换，避免同一集群混用两种日志语义。v3.0.1 的 `walimpls/impls/` 目录里有四个生产后端加一个测试桩：

| 后端    | impls 目录 | `mq.type` 取值 | 定位                                                             |
| :---- | :------- | :----------- | :------------------------------------------------------------- |
| Kafka | `kafka`  | `kafka`      | 基于 confluent-kafka-go，集群部署主力                                  |
| Pulsar| `pulsar` | `pulsar`     | 原生支持多 topic 与消息确认，历史默认云端后端                                    |
| RocksMQ| `rmq`   | `rocksmq`    | 内嵌 RocksDB 的单机日志，standalone 用；这里 rmq 指 rocksmq 而非 RocketMQ     |
| Woodpecker| `wp` | `woodpecker` | Milvus 原生日志存储，支持写栅栏 `ErrFenced`，对象存储与本地盘混合                     |
| 测试桩  | `walimplstest` | —        | 仅供单测，非生产后端                                                     |

`default` 不是第五个后端，而是随部署形态解析到上表之一的别名。后端与对象存储、复制的关系见 Storage Layer 与 [Distributed Systems](/docs/CS/Distributed/Distributed.md)。

## Three-Layer Channel Model

三层通道各自解决一个约束，命名与数量由 `pkg/util/funcutil/` 生成与解析（从 VChannel 名剥出 PChannel 用 `funcutil.ToPhysicalChannel()`）。

| 通道             | 定义                                | 命名格式                                  | 数量与来源                                    |
| :------------- | :-------------------------------- | :------------------------------------ | :-------------------------------------- |
| **PChannel**   | WAL 分区的基本单元，与后端 topic/partition 1:1 | `<prefix>_<index>` 如 `by-dev-rootcoord-dml_0` | 启动时固定，`rootCoord.dmlChannelNum` 默认 **16** |
| **VChannel**   | 一个 collection 的一个 shard 的逻辑通道       | `<pchannel>_<collectionID>v<shardIndex>` | 每 collection 按 `shardNum` 生成，可多库共享同一 PChannel |
| **CChannel**   | 全集群唯一的特殊 VChannel，绑死一个固定 PChannel   | `<pchannel>_vcchan`，后缀常量 `ControlChannelSuffix = "vcchan"` | 每集群 1 个，初始化时确定且永不变更                      |

三者的分工对应三个目标：**多 collection 共享一条日志**由「多个 VChannel 落到同一 PChannel」实现，物理 topic 数与 collection 数解耦；**单 collection 内保序**由「VChannel 是 DML 路由、事务、segment 分配的粒度」保证，同一 VChannel 内的消息经 TimeTick 形成全序；**集群级广播唯一排序点**由 CChannel 承担——像 RBAC 这类与任何 collection 无关的变更，通过 Broadcaster 写入所有目标 PChannel，但回调按 CChannel 的 TimeTick 序统一执行，从而有确定的全局顺序。

VChannel 到 PChannel 的映射由 StreamingCoord 内的 `ChannelManager.AllocVirtualChannels` 分配，它把可用 PChannel 按当前 VChannel 数排序后取前 `shardNum` 个，即按 VChannel 负载做公平挑选；`balancer/policy/vchannelfair` 策略管的是下一层——这些 PChannel 各自落到哪些 StreamingNode。shard 作为数据分布概念的更多细节见 [Shard](/docs/CS/DB/Shard.md)。

### Atomic Broadcast Path

集群级变更走 CChannel 这条唯一排序点，具体由 StreamingCoord 的 Broadcaster（`broadcaster/`）执行一次跨 PChannel 的原子广播。流程是：先按 `Domain → Key` 排序获取 `ResourceKey` 锁，避免死锁；把广播任务持久化进 catalog，保证协调者崩溃后仍能最终完成；再把消息 append 进所有目标 PChannel；等待消费端 ACK 后，按 **CChannel 的 TimeTick 序**执行回调 `AckCallback`——这正是「唯一排序点」的落点：无论消息物理上散落在多少条 PChannel，回调的全局执行顺序都由 CChannel 时间线定死。任务状态机为 `PENDING → TOMBSTONE → DONE`，复制场景下的次集群引入 `REPLICATED` 态；旧状态机里的 `WAIT_ACK` 态在 v3.0.1 已标 deprecated，恢复时与 `PENDING` 走同一处理分支。回调的定序在实现层由 ack scheduler 兜住：待回调任务先按 CChannel 的 TimeTick 排序（对冲突 resource key 的任务，其 broadcastID 序与 TimeTick 序一致，故按 broadcastID 执行即可让 ack 顺序与 WAL 顺序对齐）；消息确定写入 WAL 后（`AckSyncUp` 未开启时）还可先做 `FastAck` 加速，不必干等消费端逐条确认。DDL、RBAC 这类变更都经此路径广播，端到端细节见 [Write Path](/docs/CS/DB/Milvus/Write_Path.md)。

## PChannel Ownership and Term Fencing

WAL 横跨多个 PChannel，分布在一批 StreamingNode 上；**每个 PChannel 在任意时刻只归属唯一一个 StreamingNode**，归属由 StreamingCoord 的 Balancer 决定。归属关系确立后，被分配的 StreamingNode 才在本进程内打开该 PChannel 的 WAL 实例，挂上 append 拦截器链 `redo → lock → replicate → timetick → shard → partialupdate`，并驱动落盘侧的 `WALFlusherImpl`。也就是说「谁持有 PChannel，谁就负责它的持久化与时序推进」，这正是 3.0 把 DataNode 从落盘路径上移除后确立的新模型。

Balancer 通过两阶段分配管理 PChannel 状态机 `UNINITIALIZED → ASSIGNING → ASSIGNED → UNAVAILABLE`：`AssignPChannels` 先持久化分配结果并**递增该 PChannel 的 Term**，`AssignPChannelsDone` 由目标节点确认后转为已就绪。节点健康变化时触发再平衡，把 PChannel 迁到新节点。

**Term 是防脑裂的关键**：它是一个单调递增的整数，隔离旧归属者。一旦某 PChannel 被重新分配，Term 变大，旧 StreamingNode 上任何仍以更小 Term 发起的 append 都会被拒绝——在 Woodpecker 后端上表现为写栅栏 `ErrFenced`。因此即使旧节点因网络分区仍在运行，也无法把脏数据写进已被接管的日志。分配结果通过 gRPC `AssignmentDiscover` 以版本化的 `(Global, Local)` 对发布给所有客户端；当某进程恰好持有目标 PChannel 时，进程内 StreamingClient 会**绕过 gRPC 直连本地 WAL**。故障切换与高可用的更多语境见 [Deployment and Ops](/docs/CS/DB/Milvus/Deployment_and_Ops.md)。

### WAL Rebalancing

Balancer 的平衡动作分两类，配置注释与策略代码都强调这一区分：**恢复性分配**处理「没有健康持有者」的 PChannel——新接入的、所在节点失联或被标记不可用的——把它们分配给健康节点；**再平衡迁移**则是把已有健康持有者的 PChannel 从一个节点搬到另一个节点，纯粹为负载均衡。`streaming.walBalancer.balancePolicy.allowRebalance`（默认 true）为 false 时策略只走前者、跳过后者，这正是该键注释「only the lost wal recovery will be executed」的落点。迁移的执行序列是：对旧持有者的每条历史 assignment 调 `Remove`，向目标节点 `Assign`，再以 `AssignPChannelsDone` 记账；分配同时递增 Term，旧节点残余的写入被栅栏拒绝——再平衡天然复用了 Term fencing 机制。

平衡任务由后台循环在多个事件上触发：定时器（`triggerInterval` 默认 1m）、StreamingNode 上下线（节点变化 watch）、VChannel 增删引起的 PChannel 统计变化、primary resource group 配置变更、新的 incoming channel，以及显式的 `Trigger` 请求。任务失败进入指数退避（10ms 起、乘 2、上限 5s），每个 assign / remove 操作受 `operationTimeout` 30m 的超时约束。

`vchannelFair` 策略要解决的公平性问题：一个 PChannel 承载的 VChannel 数差异可以很大，若只按 PChannel **数量**做均衡，会出现「节点间 PChannel 数相等、但 VChannel 负载悬殊」的布局——而 VChannel 数才是 StreamingNode 消费与落盘负载的近似。策略的代价函数对每个节点计算加权平方相对偏差，三个权重各管一件事：`pchannelWeight`（0.4）管 PChannel 数量均衡；`vchannelWeight`（0.3）管 VChannel 数量均衡；`antiAffinityWeight`（0.01）惩罚两个「共享同一 collection 的 VChannel」的 PChannel 落在同一节点，让一个 collection 的 VChannel 尽量分散到不同节点，收敛单节点故障的影响面。每轮最多解绑 `rebalanceMaxStep`（3）个 PChannel 做深度优先重排，且只有新布局的总分改善超过 `rebalanceTolerance`（0.01）才采纳，否则维持现状——避免为微小收益来回抖动。

再平衡还有两道逐 PChannel 的保护闸，实现在 `CurrentLayout.AllowRebalance()`：**最短迁移间隔** `minRebalanceIntervalThreshold`（5m），刚完成分配的 PChannel 在该窗口内不再被选为迁移候选；**恢复滞后保护** `allowRebalanceRecoveryLagThreshold`（1s），节点上报的 recovery lag（最新 MVCC 时间戳与恢复水位之差）超过 1s 的 PChannel 不允许再平衡，等它先追平重放——否则会把一个还在追赶 WAL 积压的 channel 挪来挪去。配置面汇总如下：

| 配置键 | 默认值 | 作用 |
| :--- | :--- | :--- |
| `streaming.walBalancer.triggerInterval` | 1m | 后台平衡任务的定时触发间隔 |
| `streaming.walBalancer.backoffInitialInterval` | 10ms | 任务失败后的退避起始间隔 |
| `streaming.walBalancer.backoffMultiplier` | 2 | 退避倍数 |
| `streaming.walBalancer.backoffMaxInterval` | 5s | 退避间隔上限 |
| `streaming.walBalancer.operationTimeout` | 30m | 单次 assign / remove 操作的超时 |
| `streaming.walBalancer.balancePolicy.name` | `vchannelFair` | 平衡策略；v3.0.1 注册的策略只有这一个 |
| `streaming.walBalancer.balancePolicy.allowRebalance` | true | 关闭后仅做恢复性分配，跳过再平衡迁移 |
| `streaming.walBalancer.balancePolicy.minRebalanceIntervalThreshold` | 5m | 同一 PChannel 两次迁移的最短间隔 |
| `streaming.walBalancer.balancePolicy.allowRebalanceRecoveryLagThreshold` | 1s | 恢复滞后超过它则禁止迁移该 PChannel |
| `streaming.walBalancer.balancePolicy.vchannelFair.pchannelWeight` | 0.4 | PChannel 数量均衡权重 |
| `streaming.walBalancer.balancePolicy.vchannelFair.vchannelWeight` | 0.3 | VChannel 数量均衡权重 |
| `streaming.walBalancer.balancePolicy.vchannelFair.antiAffinityWeight` | 0.01 | 同 collection VChannel 分散权重 |
| `streaming.walBalancer.balancePolicy.vchannelFair.rebalanceTolerance` | 0.01 | 采纳新布局所需的最小改善 |
| `streaming.walBalancer.balancePolicy.vchannelFair.rebalanceMaxStep` | 3 | 每轮参与重排的 PChannel 数上限 |

## TimeTick as MVCC Visibility Boundary

TimeTick 是 PChannel 级单调递增的日志序号，是 **MVCC 的可见性边界**——只在同一 PChannel 内可比较。每条消息在 append 时经 `wal/interceptors/timetick/` 由 TSO 分配唯一 TimeTick，随后经过源码实有的两个水位：分配器先推进 `lastAllocatedTimeTick`（已分配出去的最新时间戳），`AckManager` 再推进 `lastConfirmedTimeTick`（早于它的消息已全部提交进 WAL），只有当某个时间戳之前的**全部**消息都被确认，确认水位才推进；后台 `TimeTickSyncInspector` 周期性把已确认水位构造成 TimeTick 消息追加进 WAL，形成对外可见的进度信号。

因为消息可能乱序落盘，消费端用 `ReOrderByTimeTickBuffer` 以小顶堆按 TimeTick 重排，恢复物理写入顺序之外的总序；`lastConfirmedManager` 计算 `LastConfirmedMessageID`，保证从该位置之后读到的消息 TimeTick 严格更大，断点续读不会漏也不会倒。事务由 `wal/interceptors/txn/` 的 `TxnManager` 协调：Begin 分配 TxID 与 TimeTick，Commit 时以 `CommitTxn` 的 TimeTick 作为整组的可见时刻，实现原子可见。

在消费侧，这一 TimeTick 水位最终体现为 QueryNode 的 **tSafe**：v3.0.1 已无独立 `tSafeManager`，水位即 `shardDelegator.latestTsafe`，随消息走完消费流水线单调推进，查询据此等待可见性边界。跨通道一致性依赖 TSO 的全局单调性——不同 PChannel 的 TimeTick 虽不可直接比较，但都源自同一全局时间戳分配器。tSafe 的等待与一致性级别细节属查询侧，见 [Query Path](/docs/CS/DB/Milvus/Query_Path.md)。

### Append Interceptor Chain

TimeTick 与事务都挂在 WAL 实例的 append 拦截器链上，顺序为 `redo → lock → replicate → timetick → shard → partialupdate`（以 `walmanager/manager_impl.go` 的 `newInterceptorBuilders` 为准）。`redo` 在 append 返回可重做错误时按新的上下文重试；`lock` 提供 VChannel / PChannel 级的排他与共享锁；`replicate` 供复制链路校验 clusterID 并按 TimeTick 去重；`timetick` 分配全局序号；`shard` 维护每 PChannel 的 collection / partition / segment 内存元数据，为每条 DML 分配 growing segment 并按 seal policy 触发封口；`partialupdate` 追踪部分更新的版本索引。shard 校验排在 partialupdate 之前，而两者都仍在 TimeTick 发布边界之内。**链上没有 txn builder**：`wal/interceptors/txn/` 的 `TxnManager` 不是单列的一层，而是被 lock、timetick、shard、replicate、partialupdate 共同引用的事务状态组件，事务语义散落在链的各个环节——`Begin` 分配 TxID 与 TimeTick，`Append` 计数并续租，`Commit` 以 `CommitTxn` 的 TimeTick 作为整组可见时刻，`Rollback` 丢弃，`Expire` 在 keepalive 续租过期时强制失败。

对上层而言这些都在进程内库中完成：其它组件通过 `internal/distributed/streaming/` 的 `WALAccesser` 单例与 `internal/streamingnode/client/` 组成的 StreamingClient 访问 WAL。`WALAccesser` 接口（定义在 `internal/distributed/streaming/streaming.go`）按用途分三类：写入与读取的 `RawAppend` / `AppendMessages` / `Read`，广播的 `Broadcast`，以及取子服务与本地状态的 `ForwardService` / `Replicate` / `ControlChannel` / `Balancer` / `Local`。接口上**没有 `Txn` 方法**——事务由 `AppendMessages` 内部判定：同属一个 VChannel 的消息按事务发送，否则逐条独立发送。请求经 `AssignmentDiscover` 路由到持有目标 PChannel 的节点，Broadcast 委托给 StreamingCoord 的 Broadcaster。

## msgdispatcher and WAL Consumers

msgdispatcher（`pkg/mq/msgdispatcher/`）是节点内的「消费共享层」，解决一个具体问题：同一节点上若有多个消费者各自开一个 MQ 消费者，会对同一 PChannel 重复拉取。它改为**每节点每 PChannel 只保留一个底层消费者**，再按 VChannel 向各订阅者 fan-out。`Client` 按 PChannel 复用 `DispatcherManager`，Manager 维护 vchannel 到 target 的注册表并周期性补建或合并 `Dispatcher`。交付语义是 **at-least-once**，机制在 `dispatcher.go` 的发送分支里：只有一个 target 时发送出错就持续重试直到成功或 dispatcher 被暂停/终止，有多个 target 时先发送再拆分 target，失败则把 target 的位点回退到本批消息的起始 position 重放。重复投递由**按位点时间戳过滤**兜住而非按 messageID 去重：dispatcher 从最老的 target 位点 seek，因此对每个 target 会跳过 `EndTs` 早于该 target 位点时间戳的批次（2.6 起每条消息 TimeTick 唯一，故用 `<` 或 `<=` 判定）。

关键现状：v3.0.1 里 msgdispatcher 的底层已适配统一 WAL，但**唯一的生产消费者是 QueryNode**。DataNode 曾经经由 msgdispatcher 消费 WAL 再 flush segment，这条路径在 3.0 已拆除——`WatchDmChannels` 成为 no-op，落盘改由 StreamingNode 的 `WALFlusherImpl` 直接消费 WAL 完成，不再经过 msgdispatcher。因此今天谈 WAL 消费者，DataNode 已不在其列；这与全局 WAL 作为唯一真相源、由 channel 持有者统一持久化的模型一致。消息队列的通用消费模型对照见 [MQ](/docs/CS/MQ/MQ.md)。

### Streaming Service Gate

新旧两套落盘模型在代码里由进程级环境变量 `MILVUS_STREAMING_SERVICE_ENABLED` 隔离（判定函数 `IsStreamingServiceEnabled()`）。**v3.0.1 该开关恒为 1**：`cmd/main.go` 在二进制启动时无条件调用 `SetStreamingServiceEnabled()`，standalone 与 cluster 的所有角色都是开启态，不存在节点级半开。它已不是可关的灰度开关，而残留为一批行为分叉的 gate，保证 StreamingNode 就绪前旧路径不塌：

| 开启后的行为                                                        | 语义                                        |
| :------------------------------------------------------------- | :---------------------------------------- |
| DataCoord 不再对集合自行 `SealAllSegments`                             | 封段改由 flusher 消费 Flush / ManualFlush 消息完成   |
| RootCoord 在 StreamingNode 就绪后停发 DDL 与 proxy timetick            | 时序信号改由 StreamingNode 发出                    |
| QueryCoord 优先把 channel 与 segment 分给 WAL 所在节点                     | 该节点即 StreamingQueryNode，副本数不足时报错          |

两类 flush 控制消息在 flusher 的 `msg_handler_impl.go` 里分工要分清：`HandleFlush` **只**对消息指定的 segment 调 `wbMgr.SealSegments`，并不推进 channel 级 flush；`FlushChannel` 只出现在 `HandleManualFlush`、`HandleFlushAll` 与 `HandleTruncateCollection` 中——手动 flush / flush all 才会额外对 write buffer 调 `SetFlushTimestamp`，把 channel 数据推进到消息携带的 TimeTick。

旧落盘模型里的 `DataSyncService` **并未退出生产路径，它就是 3.0 落盘的载体本身**：StreamingNode flusher 在 `internal/streamingnode/server/flusher/flusherimpl/flusher_components.go` 里为每个 VChannel 建一个服务——收到 create collection 消息时用 `NewEmptyStreamingNodeDataSyncService`，恢复或订阅已有 channel 时用 `NewStreamingNodeDataSyncService`，输入不再是 msgdispatcher 的注册流而是一个 `input <-chan *msgstream.MsgPack`，由 `WALFlusherImpl` 直接投喂。真正只剩测试可达的是旧构造器 `NewDataSyncService`（走 `DispClient` 注册 msgdispatcher 的那条路）与管理它的 `FlowgraphManager`——`NewFlowgraphManager` 在 v3.0.1 无任何生产调用点，只出现在同包的测试与 mock 中。开关本身的更多部署含义见 [Deployment and Ops](/docs/CS/DB/Milvus/Deployment_and_Ops.md)。

## WAL Retention and Checkpoint

WAL 不能无限增长，但它的截断必须与恢复状态对齐，否则会破坏核心不变量。StreamingNode 的 `wal/recovery/` 即 **RecoveryStorage**，负责把 WAL 消费状态持久化：`WALCheckpoint` 记录 `MessageID`、`TimeTick` 与 `ReplicateCheckpoint` 到 etcd，VChannel 元数据与 segment 分配随之内嵌，segment 数据落对象存储。它保证的**核心不变量**是：从任意 WAL 位置加上对应持久化状态，都能向前重放 WAL 恢复出一致的内存态。

Truncate 与这一 checkpoint 直接挂钩：截断点只能推进到「恢复状态已经持久化覆盖」的位置，让 checkpoint 之前的历史日志可安全回收，而 checkpoint 之后的日志始终为故障恢复、副本重放与 CDC 保留（复制侧如何消费保留窗口见 [CDC and Replication](/docs/CS/DB/Milvus/CDC_and_Replication.md)）。换句话说，**checkpoint 决定 WAL 保留的下界**，二者必须一起前进。恢复与复制如何消费这些保留窗口，见 [Write Path](/docs/CS/DB/Milvus/Write_Path.md) 与 [Distributed Systems](/docs/CS/Distributed/Distributed.md)。

### Truncation Mechanism

截断的真实机制（此前留白，本轮已核实）：生产代码里唯一调用 `WALImpls.Truncate` 的地方就是 RecoveryStorage 的后台任务。快照持久化按 `streaming.walRecovery.persistInterval`（默认 10s）周期执行，脏消息超过 `streaming.walRecovery.maxDirtyMessage`（100 条）时立即触发；写入顺序固定为 VChannel 元数据与 segment 分配、可选的 SalvageCheckpoint、最后 consume checkpoint（`SaveConsumeCheckpoint`），持久化成功后才调用 `simpleTruncateCheckpoint` 推进截断——「先持久化、后截断」是代码里的硬顺序，而不是约定。

截断点取两个水位的较小值：**recovery 的 consume checkpoint** 与 **flusher checkpoint**。flusher checkpoint 逐 VChannel 推进——flusher 把 channel 位点经 `UpdateChannelCheckpoint` RPC 上报 DataCoord，回调在 RPC 成功后才写入 `UpdateFlusherCheckpoint`；截断前取所有 VChannel 中最小的 flush checkpoint，任何一个 VChannel 尚未上报就整条 PChannel 不截断。于是保留窗口被两个条件共同卡住：恢复状态没追上的位置不能截，数据没落盘且没上报的位置也不能截。

`Truncate` 在四个后端上的落差本身也是语义：只有 Woodpecker 真正实现截断（`walImpl.Truncate` 把底层 log 截到给定 logMsgId）；Kafka 与 RocksMQ 的同名方法直接返回 nil，Pulsar 在 `backlogClearHelper` 存在时（v3.0.1 恒存在）同样返回 nil——这三种后端的日志保留完全交给各后端自身的 retention 策略。截断后 Woodpecker 再按 `woodpecker.logstore.retentionPolicy.ttl`（默认 72h）清理被截断的 segment，Woodpecker 存储侧细节见 [Woodpecker](/docs/CS/DB/Milvus/Woodpecker.md)。

## Links

- [Milvus](/docs/CS/DB/Milvus/Milvus.md)
- [Write Path](/docs/CS/DB/Milvus/Write_Path.md)
- [Query Path](/docs/CS/DB/Milvus/Query_Path.md)
- [CDC and Replication](/docs/CS/DB/Milvus/CDC_and_Replication.md)
- [Woodpecker](/docs/CS/DB/Milvus/Woodpecker.md)
- [WAL](/docs/CS/DB/WAL.md)

## References

- [milvus streaming pkg tree v3.0.1](https://github.com/milvus-io/milvus/tree/v3.0.1/pkg/streaming)
- [milvus streamingnode internal tree v3.0.1](https://github.com/milvus-io/milvus/tree/v3.0.1/internal/streamingnode)
- [milvus streamingcoord internal tree v3.0.1](https://github.com/milvus-io/milvus/tree/v3.0.1/internal/streamingcoord)
- [milvus configs milvus.yaml v3.0.1](https://github.com/milvus-io/milvus/blob/v3.0.1/configs/milvus.yaml)
- [Zilliz Woodpecker log store](https://github.com/zilliztech/woodpecker)
