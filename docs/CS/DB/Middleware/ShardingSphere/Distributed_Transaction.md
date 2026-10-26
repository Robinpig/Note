## Introduction

分片把单库事务切成跨节点问题：一个事务改了 3 个分片，就要让这 3 个分片「要么都提交、要么都回滚」。ShardingSphere 的做法是**集成现成成熟方案、对外统一 begin/commit/rollback 接口**，内部提供 LOCAL、XA、BASE 三种模式。本页讲三者的语义边界、DTP 模型与选型口径。

## Background

单数据节点上事务由数据库原生 ACID 保证（local transaction）；微服务与分片把多个数据源拉进同一个事务边界后，就出现了分布式事务。核心矛盾：

- 强一致事务（XA 系）好用，但不擅长长事务与高并发——执行期间资源持续锁定，访问成本高。
- 柔性事务（BASE 系）把互斥从资源层移到业务层，用最终一致性换吞吐，但要求业务改造（补偿、对账）。

ShardingSphere 的设计目标是**一站式分布式事务**：同一套事务接口下挂 2PC 与柔性事务两种引擎，按场景选用。

## LOCAL Transaction

LOCAL 模式基于接入端的 begin/commit/rollback 指令：对一条逻辑 SQL，ShardingSphere 在每个被代理数据库上分别开启事务、执行真实 SQL，最后各自 commit/rollback。

- 各数据节点自管理事务，**节点之间没有协调与通信**，互不知晓对方成败。
- 性能无损耗，但**不保证强一致性也不保证最终一致性**——不一致留给业务侧处理。
- 适用：业务自行容忍/处理分布式不一致的场景（如可对账的账务类补偿、幂等重试）。

## XA Transaction

XA 采用 X/Open DTP 模型的角色划分：**AP（应用程序）、TM（事务管理器）、RM（资源管理器）**；TM 与 RM 通过 XA 协议双向通信，由两阶段提交实现：

1. 每个被代理数据库以 `xa start` 开启分支事务；
2. 提交时走 `xa end` → `xa prepare`（询问各分支能否提交）→ 收集全部分支结果 → `xa commit` / `xa rollback`；
3. 异常中断时 `xa recover` 处理悬挂分支。

- ShardingSphere **内部集成 TM** 协调分支事务，对外仍是标准事务接口。
- 适合**执行时间固定的短事务、低并发**：prepare 之后资源持续锁定，长事务会把锁持有期拉长，直接打击并发。
- 与本地事务相比多出准备阶段——数据库可以「告诉调用方我能不能提交」，TM 才能做原子裁决。这是强一致性的来源，也是成本的来源。

## BASE Transaction

BASE = Basically Available、Soft state、Eventually consistent：参与方不必同时在线，状态允许延迟，最终一致靠补偿/消息驱动。ACID 把互斥放在资源层，柔性事务把互弃移回业务层。

ShardingSphere 集成 **Seata** 作为柔性事务方案：BASE 模式需要额外部署 Seata Server，事务的悬挂与补偿由 Seata AT/Saga 语义承担。

## Mode Comparison

| 维度 | LOCAL | XA | BASE |
| :--- | :--- | :--- | :--- |
| 业务改造 | 无 | 无 | 需要 |
| Seata Server | 不需要 | 不需要 | 需要 |
| 一致性 | 不支持 | 支持（强一致） | 最终一致 |
| 隔离性 | 不支持 | 支持 | 业务侧保证 |
| 并发性能 | 无损耗 | 损耗严重 | 轻微损耗 |
| 适用场景 | 业务自行处理不一致 | 短事务、低并发 | 长事务、高并发 |

## Choosing

- **短事务 + 强一致 + 低并发**（如库存扣减、资金类核心链路）：XA。
- **长事务 + 高并发 + 可补偿**（如跨服务下单、异步履约）：BASE（Seata），接受最终一致与对账成本。
- **不一致可业务兜底**（如日志、幂等写入）：LOCAL，零成本。

一个常见误区是把分布式事务当默认配置：能按分片键把相关表收进同一分片（绑定表/同片组）时，跨片事务根本不会发生——**减少事务扇出优先于选事务模式**，见 [Sharding](/docs/CS/DB/Middleware/ShardingSphere/Sharding.md)。

## Facts Worth Pinning Down

1. **XA 的代价在 prepare 之后**：分支资源锁定到全局裁决完成，长事务在 XA 下是性能灾难，不是「慢一点」。
2. **BASE 不是零成本**：Seata Server 是新组件、新运维面，业务还要写补偿与对账。
3. **LOCAL 的一致性责任在业务**：它没有任何协调语义，用错场景的数据不一致不会有任何告警。
4. **三种模式共用同一套 begin/commit/rollback 接口**，切换的是引擎而非 API——但也意味着隔离级别语义随模式变化，测试要按模式分别覆盖。

## Links

- [Distributed](/docs/CS/Distributed/Distributed.md)
- [Seata](/docs/CS/Framework/Seata/Seata.md)
- [WAL](/docs/CS/DB/Concept/WAL.md)

## References

1. [Distributed Transaction :: ShardingSphere](https://shardingsphere.apache.org/document/current/en/features/transaction/)
2. [X/Open DTP Model](http://pubs.opengroup.org/onlinepubs/009680699/toc.pdf)
3. [YAML Distributed Transaction Configuration](https://shardingsphere.apache.org/document/current/en/user-manual/shardingsphere-jdbc/yaml-config/rules/transaction/)
