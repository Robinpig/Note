## Introduction

PD（Placement Driver）是 TiDB 集群的元数据与调度中枢。它对外提供两类关键服务：全局授时（TSO）与集群调度决策，对内以 etcd 作为强一致的元数据存储。可以把 PD 理解为集群的「大脑 + 时钟 + 大脑皮层」：TiDB 事务需要它发时间戳，TiKV 副本分布与均衡需要它做决策，而这一切决策所依赖的集群拓扑与配置信息则存在它自己的 etcd 里。

## 为什么 PD 用 etcd

PD 自身是一个 3 节点（或 5 节点）的 etcd 集群之上的服务层。选择 etcd 的理由与 TiKV 选择 Raft 是同源的：

- **强一致的元数据**：集群有哪些 store、每个 Region 的副本分布在哪、配置的最新版本，这些信息必须在 PD 节点故障切换后不丢不错。etcd 的 Raft 保证写入多数派确认。
- **Watch 机制**：TiKV 通过 gRPC 心跳上报 store 状态，PD 内部各角色（scheduler、operator 控制器、TSO 分配器）通过 etcd 的 watch 订阅变化，避免轮询。
- **事务性操作**：如把一个 leader 从 store A 调度到 store B，涉及元数据的读-改-写，etcd 的 mini-transaction 可以把多步状态变更做成原子的。

需要注意：PD 用 etcd，但 **TiKV 并不通过 etcd 通信**。TiKV 与 PD 之间是 gRPC 心跳 + region 信息上报，TiKV 节点之间才是 Raft。etcd 里不存任何用户数据。

## TSO：全局授时

TiDB 的事务依赖一个**全局单调递增的时间戳**（Timestamp Oracle，TSO）来判定事务可见性顺序。PD 的 TSO 服务是时间戳的唯一来源：

- 每个 PD 节点本地维护「物理时间 + 逻辑计数器」。客户端申请 tso 时，leader 节点把当前物理时间（毫秒）与逻辑部分组合返回。
- **物理时间相同、逻辑部分递增**：同一毫秒内的多个请求靠逻辑位区分，保证严格单调。这也解释了为什么 `TIDB_TRX` / `SHOW TABLE ... REGIONS` 里看到的 ts 形如 `450849153070001000`——高若干位是物理毫秒，低位是逻辑计数。
- PD 是 TSO 的单点（逻辑上），TiDB Server 会批量申请一段 ts 缓存到本地（`tso` batch），减少对 PD 的 RPC 压力；但这不改变「PD 是唯一权威」的事实。
- 单 PD leader 故障时，etcd 选主期间授时短暂不可用（秒级），这也是生产上推荐 3 节点 PD、避免脑分裂导致的两个 TSO 来源的原因。

## PD 存储哪些元信息

PD 的 etcd 中保存的元信息大致分三类：

1. **集群拓扑**：每个 TiKV store 的地址、label、状态（Up/Down/Offline/ Tombstone）；每个 TiDB Server / TiFlash 节点的注册信息。
2. **Region 元数据**：所有 Region 的 range、epoch、副本所在 store。TiKV 上报，PD 汇总成全局路由表，供 TiDB 计算「这个 key 该去哪台 store」。
3. **配置与规则**：`placement-rules`、`resource-groups`、`scheduler` 配置、`config` 中各种组件参数的最新版本号。

PD **不存储**表结构（schema 在 TiKV 的 key 空间中）、**不存储**用户 KV 数据、也不存储统计信息文件本体。

## 调度器体系

PD 调度的目标是让副本分布均匀、读写热点摊平、故障域隔离（把同一表的副本打散到不同机架/可用区）。调度的基本循环是：

1. **心跳上报**：每个 TiKV store 周期性向 PD 上报自身状态（store heartbeat）与其所辖 Region 状态（region heartbeat，含 leader/peer 的读写 QPS、size、key 数量）。
2. **检查器（checker）**：调度器基于心跳数据运行各类 checker，发现「不健康」的状态。典型 checker：副本数不足、多余副本、leader 分布不均、region 大小不均、热点 region。
3. **Operator**：一旦 checker 判定需要调整，就生成一个 operator——一组有序 step，如 `AddLearner` → `PromoteLearner` → `TransferLeader` → `RemovePeer`。
4. **下发与限制**：operator 通过心跳响应带回给 TiKV 执行；PD 有 operator 限制（limit），控制同时进行的调度数量与速率，防止调度风暴。

v8.5 中可配置的调度器（`pd-ctl scheduler config` / 配置文件 `schedule` 段）包括：

| 调度器 | 作用 |
| --- | --- |
| `balance-leader-scheduler` | 让 leader 副本在各 store 间均衡（读流量均衡的主力） |
| `balance-region-scheduler` | 让 region 副本在各 store 间数量、大小均衡（写流量与容量均衡的主力） |
| `balance-hot-region-scheduler` | 针对热点 region 的专项均衡 |
| `evict-leader-scheduler` | 把 leader 从指定 store 上撤走（滚动重启、隔离故障 store） |
| `grant-leader-scheduler` | 反向操作，把 leader 集中到指定 store |
| `evict-scheduler` | 把某个 store 上的全部副本迁走（下线机器） |
| `shuffle-leader-scheduler` / `shuffle-region-scheduler` | 随机化副本分布，用于打散初始集中的集群 |
| `label-scheduler` | 按拓扑 label（zone/rack/host）约束副本隔离 |

配套的还有调度相关配置：`max-merge-region-size`、`max-merge-region-keys`、`split-merge-interval`、`hot-region-schedule-limit` 等。

## Placement Rules

Placement Rules 是 PD 提供的**副本放置策略**，在 v8.5 已 GA 并取代早期的 `replica.config` 静态配置方式。它以 JSON 规则的形式描述「什么样的数据应该放在哪里」：

- **约束维度**：副本数量、label 约束（如 `zone: "z1"`、`rack: "r2"`）、leader 约束（leader 必须落在某些 store）。
- **作用对象**：按 `groupID` + 规则中的 key range，可以针对某个数据库/表/索引单独设置策略（如把一张热表的 follower 放 SSD、leader 固定在高配机器）。
- **典型用法**：三副本跨三个可用区；金融场景把审计表固定到某个 zone；TiFlash 副本的放置也是通过 placement rule 描述的。

Placement Rules 与 PD 调度器的关系是：规则定义「目标状态」，调度器负责把现状推向目标。

## PD 与 TiDB 故障场景

- **PD leader 故障**：授时短暂中断，TiDB 事务在该窗口内报 `Tso request failed` 类错误；etcd 自动选主后恢复。
- **单个 PD 节点故障**：多数派仍在，服务不受影响，尽快补节点恢复 3 副本冗余。
- **PD 集群不可用**：新事务无法开始，存量事务的读走本地已缓存的 ts 仍可继续一段时间；调度停止但数据不丢。

## Links

- [TiDB 整体架构](/docs/CS/DB/TiDB/Architecture.md)
- [TiKV 存储引擎](/docs/CS/DB/TiDB/TiKV.md)
- [分布式事务](/docs/CS/DB/TiDB/Transaction.md)

## References

- https://docs.pingcap.com/zh/tidb/v8.5/schedule-replicas-by-topology-labels/
- https://docs.pingcap.com/zh/tidb/v8.5/configure-placement-rules/
- https://docs.pingcap.com/zh/tidb/v8.5/pd-configuration-file/
- https://github.com/tikv/pd
- https://etcd.io/docs/v3.5/
