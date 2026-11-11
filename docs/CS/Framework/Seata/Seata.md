## Introduction

[**Seata**](https://seata.io/en-us/index.html) 是一款开源的分布式事务解决方案，致力于提供高性能和简单易用的分布式事务服务。Seata 将为用户提供了 AT、TCC、SAGA 和 XA 事务模式，为用户打造一站式的分布式解决方案

## Architecture

Seata 围绕 **TC（协调者）/ TM（事务管理器）/ RM（资源管理器）** 三个角色构建，三者通过 Netty RPC 通信；XA / TCC / SAGA 复用同一套角色与通道，差别只在 RM 侧的 `BranchType`。v2.7.0 的模块拓扑、核心抽象与启动装配见 [Architecture](/docs/CS/Framework/Seata/Architecture.md)。

要点速览：
- **TC**（`server` 模块，`seata-server`）独立部署，持有全局锁与事务日志（session），驱动二阶段。
- **TM**（`tm` 模块）嵌入业务应用，由 `@GlobalTransactional` 触发，开启/提交/回滚全局事务；**XID 由 TC 生成**。
- **RM**（`rm` + `rm-datasource`）嵌入业务应用，AT 模式下把 JDBC 数据源包成 `DataSourceProxy`，一阶段本地提交业务数据 + `undo_log` 并注册分支。

## Transaction Flow

以默认 AT 模式为例，一次全局事务的链路是：TM 开全局事务拿 XID → 业务 SQL 经 RM 拦截生成前后镜像、`undo_log` 与业务数据同本地事务提交、并向 TC 注册分支（TC 占全局锁）→ TM 提交触发 TC 二阶段。AT 的二阶段**提交即异步删 `undo_log`、回滚即用 `undo_log` 反向补偿**。完整分步与序列图见 [Transaction Flow](/docs/CS/Framework/Seata/Transaction_Flow.md)；传输层见 [RPC Transport](/docs/CS/Framework/Seata/RPC_Transport.md)，TC 内部见 [TC Coordinator](/docs/CS/Framework/Seata/TC_Coordinator.md)，RM/AT 资源侧见 [AT and Undo Log](/docs/CS/Framework/Seata/AT_UndoLog.md)。

## Modes and Internals

四种事务模式共享同一套 TC/TM/RM 角色与 Netty 通道，差别只在 RM 侧的 `BranchType` 与一/二阶段的本地语义，因此各自值得单独展开：AT 的资源侧（数据源代理、前后镜像、`undo_log`）已在 [AT and Undo Log](/docs/CS/Framework/Seata/AT_UndoLog.md) 写透；[XA](/docs/CS/Framework/Seata/XA.md) 把两阶段委托给数据库原生 XA 协议（一阶段 `XA PREPARE` 持数据库锁到二阶段才释放，所以一致性强但并发差）；[TCC](/docs/CS/Framework/Seata/TCC.md) 由业务提供 Try/Confirm/Cancel，并用 TCC Fence 解决空回滚、防悬挂与幂等；[Saga](/docs/CS/Framework/Seata/Saga.md) 面向长事务，用状态机编排正向/补偿服务、通过 `GlobalReportRequest` 把终态上报 TC。TC 侧的状态持久化、全局锁与高可用则是另一组主题：[TC Storage](/docs/CS/Framework/Seata/TC_Storage.md) 讲会话如何落盘（db/file/redis 三后端）；[Global Lock](/docs/CS/Framework/Seata/Global_Lock.md) 讲 AT 写隔离依赖的全局锁（保护主键值，db/file/redis/raft 后端）；[Raft HA](/docs/CS/Framework/Seata/Raft_HA.md) 讲 TC 如何内嵌 SOFA JRaft 复制会话、实现 CP 高可用与 leader 切换续命。

## AT

前提
- 基于支持本地 ACID 事务的关系型数据库。
- Java 应用，通过 JDBC 访问数据库。

AT模式是两阶段提交协议的演变：

- 一阶段：业务数据和回滚日志记录在同一个本地事务中提交，释放本地锁和连接资源。
- 二阶段：
  - 提交异步化，非常快速地完成。
  - 回滚通过一阶段的回滚日志进行反向补偿

写隔离
一阶段本地事务提交前，需要确保先拿到 全局锁 。
拿不到 全局锁 ，不能提交本地事务。
拿 全局锁 的尝试被限制在一定范围内，超出范围将放弃，并回滚本地事务，释放本地锁。

Seata AT 的业务流程分为两个阶段来执行。
一阶段：执行核心业务逻辑（即代码中的 CRUD 操作）。Seata 会根据 DB 操作自动生
成相应的回滚日志，并将回滚日志添加到 RM 对应的 undo_log 表中。执行业务代码和
添加回滚日志这两步都是在同一个本地事务中提交的。
二阶段：如果全局事务的最终决议是 Commit，则更新分支事务状态并清空回滚日志；
如果最终决议是 Rollback，则根据 undo_log 中的回滚日志进行 rollback 操作。二阶
段是以异步化的方式来执行的

Seata AT 方案的核心在于这个 undo_log。正是有了这个记录回
滚日志的 undo_log 表，我们才能将一阶段和二阶段剥离成两个独立的本地事务来执行。
而 Seata AT 之所以执行效率高，主要原因有两个。一是核心业务逻辑可以在一阶段得到快
速提交，DB 资源被快速释放；二是全局事务的 Commit 和 Rollback 是异步执行

Seata 分布式事务是个双刃剑，当我们给项目引入 Seata 的时候，无形中也增加了架构层
面的复杂程度，说白了，就是增加了一个 failure point。你需要考虑 Seata Server 不可用
的情况，制定降级预案保证业务正常运转。同时在大促等环节的压测端，你也要对 Seata
Server 的高可用做好充足的功课

存在问题

- 性能损耗，一条 update 的 SQL，至少需要 6 次 DB 操作，并且很多操作需要一次额外的 RPC，另外 undo log 的 blog 写入性能也不高，在全局事务下回滚情况消耗更大，至少增加 5 倍响应时间
- 一阶段在 commit 前持有全局锁降低并发性，如果第二阶段是回滚则耗时更久；一旦出现死锁会不断重试直到全局锁超时
- 隔离性：一旦存在一个全局事务，这个库的其它操作也会收到限制
  - 分支事务一阶段提交，这时一个普通的 select 查询读取数据，之后第二阶段回滚，就造成脏读，需要 for update





推荐使用传统的事务型消息 + 日志补偿 + 跑批补偿的方式，用最经济实惠的技术手段搞定简单业务











## TCC


### TCC Issues

#### TCC Empty Rollback

所谓空回滚，是在没有执行 Try 方法的情况下，TC 下发了回滚指令并执行了 Cancel 逻
辑。
那么在什么情况下会出现空回滚呢？比如某个分支事务的一阶段 Try 方法因为网络不可用
发生了 Timeout 异常，或者 Try 阶段执行失败，这时候 TM 端会判定全局事务回滚，TC
端向各个分支事务发送 Cancel 指令，这就产生了一次空回滚。
处理空回滚的正确的做法是，在 Cancel 阶段，你应当先判断一阶段 Try 有没有执行成
功。示例程序中的判断方式比较简单，我先是判断资源是否已经被锁定，再执行释放操
作。如果资源未被锁定或者压根不存在，你可以认为 Try 阶段没有执行成功，这时在
Cancel 阶段直接返回成功即可。
更为完善的一种做法是，引入独立的事务控制表，在 Try 阶段中将 XID 和分支事务 ID 落
表保存，如果 Cancel 阶段查不到事务控制记录，那么就说明 Try 阶段未被执行。同理，
Cancel 阶段执行成功后，也可以在事务控制表中记录回滚状态，这样做是为了防止另一个
TCC 的坑，“倒悬”。

#### TCC Hanging

倒悬又被叫做“悬挂”，它是指 TCC 三个阶段没有按照先后顺序执行。我们就拿刚讲过的
空回滚的例子来说吧，如果 Try 方法因为网络问题卡在了网关层，导致锁定资源超时，这
时 Cancel 阶段执行了一次空回滚，到目前为止一切正常。但回滚之后，原先超时的 Try
方法经过网关层的重试，又被后台服务接收到了，这就产生了一次倒悬场景，即一阶段 Try
在二阶段回滚之后被触发

在倒悬的情况下，整个事务已经被全局回滚，那么如果你再执行一次 Try 操作，当前资源
将被长期锁定，这就造成了一种类似死锁的局面。解法很简单，你可以利用事务控制表记
录二阶段执行状态，并在 Try 阶段中检查该状态，如果二阶段回滚完毕，那么就直接跳过
一阶段 Try



## Transaction Comparison

Seata支持四种事务模式，适配不同业务场景，需根据一致性要求、性能需求选型：

| 事务模式       | 核心原理                                                     | 优势                                                         | 局限性                                                       | 适用场景                                                     |
| :------------- | :----------------------------------------------------------- | :----------------------------------------------------------- | :----------------------------------------------------------- | :----------------------------------------------------------- |
| AT模式（默认） | 基于 SQL 解析的两阶段提交：1. 一阶段执行本地事务并记录 undo_log（补偿日志）；2. 二阶段根据全局状态，提交则删除 undo_log，回滚则通过 undo_log 补偿数据。 | 1. 无侵入式开发，无需修改业务代码；2. 性能优异，一阶段直接提交本地事务；3. 适配绝大多数关系型数据库。 | 1. 仅支持关系型数据库；2. 依赖数据库事务和 undo_log 表；3. 不支持非幂等操作的回滚补偿。 | 大多数微服务场景（订单、库存、支付等），对一致性要求中等、追求性能。 |
| TCC模式        | 手动编码实现两阶段：1. Try（资源检查与锁定）；2. Confirm（确认执行）/Cancel（取消执行，补偿逻辑）。 | 1. 无数据库依赖，支持非关系型数据库；2. 一致性强，可自定义补偿逻辑；3. 性能最优。 | 1. 侵入式开发，需手动编写Try/Confirm/Cancel接口；2. 需保证接口幂等性和可补偿性。 | 对性能和一致性要求极高的场景（如金融交易、核心业务）。       |
| SAGA模式       | 长事务补偿模式，按业务流程顺序执行服务，失败则通过反向补偿服务回滚。 | 1. 支持长事务；2. 适配复杂业务流程；3. 无数据库依赖。        | 1. 一致性弱（最终一致）；2. 需编写大量补偿服务；3. 流程管理复杂。 | 长事务场景（如订单履约、物流调度），可接受最终一致性。       |
| XA模式         | 基于数据库 XA 协议的两阶段提交，一阶段预提交，二阶段统一提交/回滚。 | 1. 一致性最强；2. 无侵入式，依赖数据库原生支持。             | 1. 性能极差，一阶段需锁定资源；2. 适配数据库有限；3. 容错性差。 | 对一致性要求极高、性能要求极低的场景（如银行核心转账）。     |




## Links
- [Transaction](/docs/CS/Framework/Spring/Transaction.md)
- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)
- [Spring Cloud Alibaba](/docs/CS/Framework/Spring_Cloud/Alibaba.md)
- [Distributed Transaction Patterns](/docs/CS/Distributed/Distributed_Transaction_Patterns.md)
