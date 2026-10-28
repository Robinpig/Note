## Introduction

[Apache ShardingSphere](https://shardingsphere.apache.org/) 的定位是 **Database Plus**：不创造新数据库，而是在异构数据库之上建立标准层与生态，把计算与存储能力「最大化复用」在现有数据库上，补齐单库缺失的分布式能力。核心方法论是三个关键词：

- **Connect**：灵活适配数据库协议、SQL 方言与数据库存储，让应用与异构数据库快速建立标准化连接（内置 DistSQL 作为统一入口）。
- **Enhance**：捕获数据库访问入口，透明叠加能力——redirect（分片、读写分离、影子库）、transform（加密、脱敏）、authentication（安全、审计、权限）、governance（熔断、限流、分析、QoS、可观测）。
- **Pluggable**：微内核 + 三层可插拔，功能与数据库生态像乐高一样嵌入，开发者可拼出自己的 ShardingSphere。

产品形态上，官方当前只有**两个既可独立部署、又可混合部署的接入端**：ShardingSphere-JDBC（jar 形态的增强 JDBC 驱动，Java 同构、低损耗）与 ShardingSphere-Proxy（二进制协议代理服务器，MySQL/PostgreSQL 协议、异构语言、静态入口）。旧文档里的 Sidecar（Database Mesh）已不在官方叙事中。版本锚点 **5.5.3（2026-03-01 发布，5.5.4 开发中）**，Apache 顶级项目（TLP）自 2020-04-16 起。

本页是枢纽：只放定位、架构总览、选型与最要紧的几条反直觉事实；九个方向的分册各有展开。

## Architecture

微内核 + 三层可插拔是理解全部功能的钥匙：

| 层 | 地位 | 内容 |
| :--- | :--- | :--- |
| L1 内核层 | 全部必需，实现可替换 | 查询优化器、分布式事务引擎、分布式执行引擎、权限引擎、调度引擎 |
| L2 功能层 | 全部可选，相互隔离、可叠加 | 数据分片、读写分离、数据加密、影子库等 |
| L3 生态层 | 对接外部世界 | 数据库协议、SQL 解析器、存储适配器 |

```
应用 ── JDBC / Proxy ──▶ L2 功能层（分片 · 读写分离 · 加密 · 影子库）
                              │
                              ▼
                     L1 内核层（解析 → 路由 → 改写 → 执行 → 归并）
                              │
                              ▼
                     L3 生态层（MySQL / PostgreSQL / Oracle / SQLServer …）
```

一条逻辑 SQL 在内核层走完五阶段流水线，功能层决定这条 SQL 在哪些节点上被怎么改造——细节见 [SQL Pipeline](/docs/CS/DB/Middleware/ShardingSphere/SQL_Pipeline.md) 与 [Architecture](/docs/CS/DB/Middleware/ShardingSphere/Architecture.md)。

![](https://shardingsphere.apache.org/document/current/img/overview.en.png)

## Map of This Section

分册的排布顺序就是一条 SQL 的「一生」加上它背后的运维面：

- **[Architecture](/docs/CS/DB/Middleware/ShardingSphere/Architecture.md)**——「它到底是什么形状」。Database Plus 定位、三层可插拔模型、JDBC 与 Proxy 的六维对比、混合部署与两种运行模式。理解所有其他分册的地图。
- **[SQL Pipeline](/docs/CS/DB/Middleware/ShardingSphere/SQL_Pipeline.md)**——「一条 SQL 在里面经历什么」。解析（ANTLR 多方言）、路由（分片键/全路由/Hint）、改写（表名/分页/补列）、执行（并发）、归并（排序/分页/聚合），以及联邦查询的真实状态（experimental，默认关闭）。所有性能问题的定位入口。
- **[Sharding](/docs/CS/DB/Middleware/ShardingSphere/Sharding.md)**——「主轴功能怎么配」。五种表类型、数据节点分布、内置算法族（MOD/HASH_MOD/VOLUME_RANGE/BOUNDARY_RANGE/AUTO_INTERVAL/INLINE/INTERVAL/COMPLEX_INLINE/HINT_INLINE/CLASS_BASED）、四种策略、行表达式、分布式主键与分片审计。分片机制本身见 [Shard](/docs/CS/DB/Concept/Shard.md)。
- **[Distributed Transaction](/docs/CS/DB/Middleware/ShardingSphere/Distributed_Transaction.md)**——「分片的代价怎么还」。LOCAL/XA/BASE 三模式的语义、DTP 两阶段提交、Seata 集成与选型表。分片把事务切成跨节点问题，这一页回答「要么都提交要么都回滚」。
- **[Readwrite Splitting](/docs/CS/DB/Middleware/ShardingSphere/Readwrite_Splitting.md)**——「另一维流量怎么分」。读写路由、三种负载均衡算法、事务内读策略（PRIMARY/FIXED/DYNAMIC）与高可用边界。与分片正交、可叠加。
- **[Shadow](/docs/CS/DB/Middleware/ShardingSphere/Shadow.md)**——「生产压测怎么不污染数据」。影子库的数据对/表/算法四层配置，REGEX_MATCH 与 SQL_HINT 两种内置影子算法，全链路压测的实施边界。
- **[Encryption](/docs/CS/DB/Middleware/ShardingSphere/Encryption.md)**——「敏感数据怎么管」。加密（`!ENCRYPT`，内置仅 AES/MD5，辅助查询列机制）与脱敏（`!MASK`，八种内置掩码算法）两块独立规则，以及在线加密改造的真实复杂度。
- **[Governance](/docs/CS/DB/Middleware/ShardingSphere/Governance.md)**——「多实例怎么协同」。Standalone/Cluster 运行模式与元数据仓库、注册中心四树数据结构、DistSQL、Agent 可观测性（Prometheus/Jaeger/Zipkin/OpenTelemetry/SkyWalking）、数据迁移四阶段（binlog / test_decoding）。
- **[Operations](/docs/CS/DB/Middleware/ShardingSphere/Operations.md)**——「怎么落地、怎么不翻车」。接入端选型、四种配置入口、混合部署约束、与 MyCat/TDDL/canal/TiDB/Vitess 的边界、八条反模式与版本节奏。

## Applicable Scenarios

适合：

- **海量数据高并发 OLTP**：单表单库过阈值后水平扩展，JDBC 接入端满足高性能轻量场景（官方口径：单库数据量宜控制在 1TB 内）。
- **异构语言与 DBA 运维**：非 Java 生态、需要统一数据库入口与运维界面时用 Proxy。
- **存量库平滑增强**：加密合规、读写分离、影子压测都可以不改业务 SQL 叠加。
- **单库到分片集群迁移**：迁移管线做存量 + 增量 + 流量切换四阶段。

不适合：

- **绿地项目的原生分布式需求**：要分片与共识做进内核，选 [TiDB](/docs/CS/DB/TiDB/TiDB.md)/OceanBase 类分布式数据库更直接。
- **分片键缺失的重分析负载**：无分片键全路由 + 深分页跨片归并的代价，超过中间件能优雅承担的范围；这类负载应下沉数仓或走 Proxy + 联邦（后者仍是 experimental）。
- **高并发强一致跨片事务**：XA 的锁定语义打不了高并发；BASE 要业务改造与对账——先按绑定表/同片设计消除跨片事务，比选事务模式更根本。

| 条件 | 选择 |
| :--- | :--- |
| Java 同构、高性能 OLTP、规则随应用演进 | ShardingSphere-JDBC |
| 异构语言、集中运维、OLAP 查询 | ShardingSphere-Proxy |
| 平台化统一分片策略、多团队共用 | 混合部署（必须集群模式） |
| 新建系统、要原生分布式语义 | TiDB / OceanBase / Vitess |

## Facts Worth Pinning Down

最容易被版本与默认值坑到的几条，完整清单散布各分册：

1. **Sidecar 已退出官方叙事**：只有 JDBC 与 Proxy 两个接入端；按旧文档的三件套（含 Database Mesh）做架构选型会落空。
2. **SQL Federation 是 experimental，默认关闭**：官方原话「currently not suitable for use in core system production environments」；`providerType: NONE` 是默认值，旧 `sqlFederationEnabled` 配置项已废弃。
3. **无分片键 = 全路由**：SQL 不带分片条件时扇出所有数据节点，性能断崖；用 `DML_SHARDING_CONDITIONS` 审计在测试期拦截。
4. **JDBC 接入端背着 ANTLR 缓存债**：SQL 模板过多时解析缓存持续增长占用堆内存（ANTLR issue#4232 未修），必须预留 `-Xmx`；Proxy 无此问题。
5. **Standalone 元数据不共享，混合部署必须集群模式**：多实例各改各的配置没有漂移告警，这是官方明令的生产约束。
6. **XA 只适合短事务低并发**：prepare 之后资源锁定到全局裁决完成，长事务在 XA 下是性能灾难；高并发长事务走 BASE（Seata）并接受最终一致。
7. **绑定表靠剥离数字后缀推导**：真实表名尾部的数字必须只用作分片后缀，`t_order_2024` 式命名直接破坏绑定关系。
8. **内置加密算法只有 AES 与 MD5**：辅助查询列用 MD5 摘要换等值可查；范围/模糊查询在加密列上不可用。

## Links

- [DataBases](/docs/CS/DB/DB.md)
- [MyCat](/docs/CS/DB/MyCat/MyCat.md)
- [MySQL](/docs/CS/DB/MySQL/MySQL.md)
- [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)
- [WAL](/docs/CS/DB/Concept/WAL.md)

## References

1. [Apache ShardingSphere](https://shardingsphere.apache.org/)
2. [ShardingSphere Documentation](https://shardingsphere.apache.org/document/)
3. [Overview :: ShardingSphere](https://shardingsphere.apache.org/document/current/en/overview/)
4. [Downloads :: ShardingSphere](https://shardingsphere.apache.org/document/current/en/downloads)
5. [apache/shardingsphere](https://github.com/apache/shardingsphere)
