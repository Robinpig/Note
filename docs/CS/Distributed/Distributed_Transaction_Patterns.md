# Distributed Transaction Patterns

分布式事务的落地分两条路线：**协议层**与**应用层模式**。[Consensus/Consensus.md](/docs/CS/Distributed/Consensus/Consensus.md) 已经覆盖了 2PC / 3PC / Quorum NWR 这类**原子提交协议**——它们由基础设施（事务协调器、数据库）保证 ACID，但代价是同步阻塞、锁资源、可用性低，难以直接套在跨多个微服务、长生命周期的业务上。本篇聚焦**应用层事务模式**：Saga 与 TCC，它们主动牺牲强隔离、用"可补偿 / 可预留"的设计换取高可用与横向扩展，是微服务架构下跨服务一致性的主流选择。

数据库层也有原生的分布式事务实现，可作为对照：[TiDB](/docs/CS/DB/TiDB/TiDB.md) 用 Percolator 的两阶段提交 + MVCC，[CockroachDB](/docs/CS/Distributed/CockroachDB.md) 用 HLC + 分布式事务——它们把一致性下沉到存储引擎，应用无感；而 Saga / TCC 是应用自己编排的。

## 2PC/3PC as the Baseline

回顾协议层（详见 [Consensus/Consensus.md](/docs/CS/Distributed/Consensus/Consensus.md)）：

- **2PC（两阶段提交）**：准备阶段锁资源、投票；提交阶段统一提交或回滚。问题是**同步阻塞**（所有参与者在协调器决策前持有锁）、**协调器单点**、以及网络分区下可能**数据不一致**（部分参与者提交了、部分没收到指令）。
- **3PC**：引入超时与预查询，缓解阻塞，但并未根除不一致，且实现复杂。

2PC/3PC 适合"短事务、参与方都可信、都在数据库层"的场景。当业务跨多个独立服务、每个服务有自己的数据库、事务可能跑几秒到几分钟时，长时间持锁不可接受，于是需要 Saga / TCC。

## Saga

Saga 把**一个长事务**拆成一系列**本地事务**，每个本地事务都有对应的**补偿操作（compensation）**。正常路径依次执行 T1 → T2 → … → Tn；如果某一步 Ti 失败，则**反向**执行已完成的各步补偿 C(i-1) → … → C1，把系统回滚到一致状态。

Saga 有两种协调方式：

- **编排（Choreography）**：没有中心协调器，各服务通过**事件**直接驱动彼此。例如"下单"服务发 `OrderCreated` 事件，库存服务监听后扣减并可能发 `InventoryReserved`，失败则发 `InventoryFailed` 触发上游补偿。去中心、耦合低，但事件链路长时难追踪、易成"意大利面"。
- **协同（Orchestration）**：引入一个**中央协调器（orchestrator / Saga executor）**，它显式调用各服务的本地事务并决定前进或补偿。流程集中、可观测，但协调器成为新的中心节点。

Saga 的代价：

- **无强隔离**：补偿执行期间，中间态对外可见，可能读到"部分完成"的数据（缺乏 ACID 的隔离级别）。常用对策是语义锁、交换式更新、重读校验等。
- **补偿必须幂等**：消息重发、重试都要求补偿可重复执行而不产生副作用。
- **缺乏隔离带来的脏读/丢失更新**需要业务层额外处理，而非靠数据库锁。

## TCC

TCC（Try-Confirm-Cancel）把每个参与者的操作显式切成三阶段：

- **Try**：**预留**业务资源、做校验（如冻结库存、预扣额度）。不真正提交业务，只是把资源"占住"。
- **Confirm**：真正执行业务（消耗预留的资源）。**全局都成功**时调用。必须幂等。
- **Cancel**：释放 Try 阶段预留的资源。任一参与者失败或超时未确认时调用。必须幂等。

TCC 与 2PC 表面相似（都是两阶段），但本质不同：2PC 的锁在**数据库行锁 / 事务锁**上，阻塞到协调器决策；TCC 的"锁"是**业务层面的预留**（如冻结的库存字段），Try 之后立即释放数据库事务，Confirm/Cancel 是后续独立的业务动作。因此 TCC 的锁粒度更细、持锁时间更短，可用性更高。

TCC 的代价：业务侵入强——每个参与服务都要手写 Try/Confirm/Cancel 三套逻辑；且 Confirm/Cancel 必须幂等、Cancel 要能处理"Try 未成功执行却收到 Cancel"的边界。

## Saga vs TCC

| 维度 | Saga | TCC |
|---|---|---|
| 核心动作 | 正向执行 + 反向补偿 | 预留（Try）+ 确认/取消 |
| 隔离性 | 弱，中间态可见，需业务兜底 | 较强，Try 阶段即隔离资源 |
| 业务侵入 | 中（写补偿） | 高（写 Try/Confirm/Cancel） |
| 适合 | 长流程、跨多服务、可补偿业务 | 强一致诉求、资源可预留（库存/额度） |
| 典型实现 | [Seata](/docs/CS/Framework/Seata/Seata.md) Saga 模式 | [Seata](/docs/CS/Framework/Seata/Seata.md) TCC 模式 |

## Seata and the Implementation Landscape

[Seata](/docs/CS/Framework/Seata/Seata.md) 是阿里开源的分布式事务框架，同时提供三种模式：

- **AT 模式**：自动补偿，基于 2PC 改良，对业务无侵入，通过解析 SQL 自动生成回滚日志（undo log）。
- **TCC 模式**：上节所述，业务手写三阶段。
- **Saga 模式**：状态机编排的长事务，适合流程长、需可视化编排的场景。

选型上：短事务、同构数据库优先 AT（接近 2PC 但无长期锁）；跨异构系统、资源可预留用 TCC；超长流程、参与者不可控用 Saga。无论哪种，幂等、空回滚、防悬挂都是必须处理的工程细节。

## Links

- [Consensus（2PC/3PC/Quorum）](/docs/CS/Distributed/Consensus/Consensus.md)
- [Seata](/docs/CS/Framework/Seata/Seata.md)
- [TiDB](/docs/CS/DB/TiDB/TiDB.md)
- [CockroachDB](/docs/CS/Distributed/CockroachDB.md)

## References

- Sagas (Hector Garcia-Molina, Kenneth Salem, 1987)
- Transaction Management in the RODAIN/Saga Distributed Transaction Model
- Seata documentation: https://seata.apache.org/
