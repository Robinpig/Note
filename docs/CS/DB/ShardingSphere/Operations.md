## Introduction

本页是落地口径：两种接入端怎么选、配置体系有几种、混合部署的正确姿势、与相邻方案的边界，以及一套上线前的反模式清单。版本锚点 **5.5.3（2026-03-01）**，5.5.4 在开发中；Apache TLP 自 2020-04-16。

## Choosing an Access End

| 你的处境 | 选择 |
| :--- | :--- |
| Java 同构、高性能轻量 OLTP、不想多一跳网络 | ShardingSphere-JDBC |
| 异构语言（PHP/Go/Python…）、DBA 统一运维入口、OLAP 查询 | ShardingSphere-Proxy |
| 平台团队要集中控制路由策略、多团队共用一套分片规则 | ShardingSphere-Proxy（静态入口） |
| 单体应用各自演进、规则随应用发布 | ShardingSphere-JDBC（去中心化） |
| 两者都要 | 混合部署，注册中心统一分片策略（必须集群模式） |

判据是**控制点在哪**：JDBC 的路由策略跟着应用走，升级随应用发布；Proxy 把路由收拢成平台资产，代价是多一个有状态服务要保活、监控、扩缩。

## Configuration Systems

四种配置入口，语义等价：

- **YAML**：`YamlShardingSphereDataSourceFactory.createDataSource(...)` 一把创建 `ShardingSphereDataSource`，规则依赖在 YAML 里一眼可读——示例与文档最全的入口。
- **Java API**：`ShardingSphereDataSourceFactory` + `ShardingRuleConfiguration` 系列配置对象（`ShardingStrategyConfiguration`、`TableRuleConfiguration`、`KeyGeneratorConfiguration` 等），适合动态拼装规则。
- **Spring Boot Starter**：`spring.shardingsphere.*` 配置树，与 Spring 生态连接池（HikariCP 等）直接集成。
- **DistSQL**：SQL 式规则管理，集群模式下经注册中心广播（见 [Governance](/docs/CS/DB/ShardingSphere/Governance.md)）。

JDBC 接入端的硬注意事项：**ANTLR 解析缓存随 SQL 模板数量增长**，模板多的应用要预留堆内存（官方 README 点名，ANTLR issue#4232 未修复）。

## Hybrid Deployment

- JDBC（去中心化，高性能 OLTP）+ Proxy（静态入口，全语言）+ **同一注册中心统一分片策略**。
- 官方约束：混合部署必须用集群模式，否则两端配置各改各的，必然漂移。
- 两端共享的是规则与元数据，不共享连接与执行——JDBC 侧仍然是应用直连数据库。

## Adjacent Solutions

| 方案 | 形态 | 与 ShardingSphere 的分工 |
| :--- | :--- | :--- |
| [TDDL](/docs/CS/DB/TDDL.md) | 客户端分库分表中间件 | 同层竞品；TDDL 阿里系、绑定淘宝技术栈，ShardingSphere 跨生态、功能面更宽 |
| [canal](/docs/CS/DB/canal.md) | binlog 订阅（伪装从库） | 互补：canal 把增量变更喂给缓存/数仓，ShardingSphere 管在线读写入口 |
| TiDB / OceanBase / PolarDB | 分布式数据库内核 | 替代关系：分片做进存储内核，无中间件层；ShardingSphere 的立场是「复用现有数据库，不造新库」 |
| Vitess | MySQL 分片中间件（CNCF） | 同层竞品，MySQL-only、原生 ACID 更强；ShardingSphere 多数据库 + 功能面（加密/影子/治理）更宽 |

选中间件还是选内核，本质是「改造存量」还是「新建系统」：存量 MySQL/PG 生态平滑增强选前者，绿地项目要原生分布式语义选后者。

## Anti-Patterns

1. **无分片键查询上生产**：全路由扇出所有节点，配合 `DML_SHARDING_CONDITIONS` 审计在测试期拦截（见 [Sharding](/docs/CS/DB/ShardingSphere/Sharding.md)）。
2. **分片键拍脑袋**：分片键一旦选定极难更改（数据重分布的代价）；选型前按业务访问模式验证，别上线后重构。
3. **跨片 join/子查询当常规操作**：能收进同片（绑定表）就收；收不了的要么改 SQL，要么接受改写/归并代价；SQL Federation 是 experimental，别当生产路径（见 [SQL Pipeline](/docs/CS/DB/ShardingSphere/SQL_Pipeline.md)）。
4. **XA 用在长事务**：prepare 后资源锁定到全局裁决，长事务直接打爆并发（见 [Distributed Transaction](/docs/CS/DB/ShardingSphere/Distributed_Transaction.md)）。
5. **绑定表命名带业务数字**：`t_order_2024` 这类真实表名会破坏「剥离数字后缀」的绑定推导。
6. **Standalone 上生产 / 混合部署不用集群模式**：配置漂移无告警，官方明令禁止。
7. **深分页跨片查**：`LIMIT 10000, 10` 在归并层重算全局窗口，深分页是性能陷阱；大偏移量翻页改用游标/键集。
8. **把影子库当压测环境**：影子库只做数据隔离，schema 与基础数据要自备，压测标没传下来 = 污染生产（见 [Shadow](/docs/CS/DB/ShardingSphere/Shadow.md)）。

## Release Cadence

| 版本 | 时间 | 备注 |
| :--- | :--- | :--- |
| 5.5.0 | 2024-04 | 5.5 基线 |
| 5.5.1 | 2024-10 | — |
| 5.5.2 | 2025-01 | — |
| 5.5.3 | 2026-03 | 当前最新发布版 |
| 5.5.4 | 开发中 | 安全增强与性能优化 |

跨版本迁移要点随版本查发布说明；已知的一次配置断代是 SQL Federation：旧 `sqlFederationEnabled` 在 5.5 被 `providerType: NONE/CALCITE` 取代（见 [SQL Pipeline](/docs/CS/DB/ShardingSphere/SQL_Pipeline.md)）。

## Facts Worth Pinning Down

1. **只有两款接入端**：JDBC 与 Proxy；Sidecar/Database Mesh 已不在官方叙事，按三件套做选型会落空。
2. **JDBC 与 Proxy 共享同一注册中心才叫混合部署**，且必须集群模式。
3. **ANTLR 缓存是 JDBC 接入端独有的内存债**，Proxy 不背。
4. **项目状态健康但 issue 不少**（2026 年 GitHub 20k+ stars、数百 open issues），接入新数据库或新特性前先查 issue 里对应引擎的已知问题。

## Links

- [ShardingSphere Hub](/docs/CS/DB/ShardingSphere.md)
- [Governance](/docs/CS/DB/ShardingSphere/Governance.md)
- [TDDL](/docs/CS/DB/TDDL.md)
- [canal](/docs/CS/DB/canal.md)
- [TiDB](/docs/CS/DB/TiDB.md)
- [Shard](/docs/CS/DB/Shard.md)

## References

1. [Overview :: ShardingSphere](https://shardingsphere.apache.org/document/current/en/overview/)
2. [Downloads :: ShardingSphere](https://shardingsphere.apache.org/document/current/en/downloads)
3. [apache/shardingsphere](https://github.com/apache/shardingsphere)
4. [Apache ShardingSphere document v5.0.0](https://shardingsphere.apache.org/document/5.0.0/en/shardingsphere_docs_en.pdf)
