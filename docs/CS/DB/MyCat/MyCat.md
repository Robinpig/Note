## Introduction

MyCAT 是一个**服务器端数据库代理中间件**：前端讲 MySQL 原生协议，对应用表现为一台普通的 MySQL 服务器；后端用 JDBC 连接真实的数据库集群，在中间完成分库分表路由、读写分离、结果归并。业务代码零侵入——应用连的是 MyCAT，不是 MySQL，这是它与 [ShardingSphere](/docs/CS/DB/Middleware/ShardingSphere.md) 这类客户端中间件的根本分野。

它有两条需要分开叙述的血脉：

- **MyCAT 1.x**：2013 年从阿里巴巴开源的 [Cobar](https://github.com/alibaba/cobar) 改良而来，发起人重构了网络模块（NIO）与 Buffer 内核，1.4 以后完全脱离 Cobar 内核独立演进。源码在 [MyCATApache/Mycat-Server](https://github.com/MyCATApache/Mycat-Server)，发行线基线 **1.6-RELEASE**（1.6.5 起支持 XA、1.6 起支持 ZooKeeper 协调与 PostgreSQL native 协议），仓库至今仍有零星修复（最后一次提交在 2025-10）。
- **MyCAT 2.x**：社区另起的重写版，源码在 [MyCATApache/Mycat2](https://github.com/MyCATApache/Mycat2)，当前发布线 **v1.22-release**。它换了一颗心脏——查询引擎基于 **Apache Calcite**（规则优化 + 代价优化），带独立的物理执行层、BKAJOIN、全局二级索引，配置从 XML 迁到 JSON。注意 README 明示**只支持 Java 8**，且自 2023.8 起改用 Apache License。

「同一个名字、两套代码」是理解 MyCAT 生态的第一道门槛：网上绝大多数教程（含官方站 mycat.org.cn 的入门文档）讲的是 1.6；看到 Calcite、datasource.json、8066 端口，说的是 MyCAT2。

本页是枢纽页：只放定位、架构总览、选型与最要紧的版本事实；配置细节、分片算法、SQL 路由、读写分离、事务、运维七个方向各有分册展开。分片本身的通用机制（为什么分、怎么分）见 [Shard](/docs/CS/DB/Concept/Shard.md)，本页不重述。

## Architecture

一次查询在 MyCAT 内部的旅程可以概括成五段，全程对客户端透明：

```
应用（MySQL 协议）
  │  connect 8066
  ▼
前端协议层 ── 伪装成 MySQL Server，解析握手、报文、命令
  │
  ▼
SQL 解析 ── 默认 druidparser（server.xml 的 defaultSqlParser 可换）
  │  产出分片列、分片条件、聚合/排序结构
  ▼
Router ── 查 schema.xml + rule.xml：哪些分片参与、SQL 改写成什么样
  │
  ▼
执行与归并 ── 后端 JDBC 连接池并发下发，跨分片结果内存聚合/排序/分页
  │
  ▼
MySQL 结果报文 ── 客户端看到的是一个单库单表的世界
```

三个结构性事实：

- **后端不挑数据库**：前端协议只有一种，后端只要是 JDBC 可达即可——MySQL、Oracle、DB2、SQL Server、PostgreSQL（1.6 起有 native 协议）、MongoDB 都可作为存储节点。MyCAT2 进一步内置了 ClickHouse 后端数据源（仅 select/insert，无自增值返回）。
- **中间件不持有数据**：元数据、事务、持久化全部在后端 MySQL 集群，MyCAT 挂掉不丢数据，重启即恢复——这是它与 [TiDB](/docs/CS/DB/TiDB/TiDB.md)、[OceanBase](/docs/CS/DB/OceanBase.md) 这类 NewSQL 的本质区别，也是它扩容/缩容时数据要搬家的原因。
- **MyCAT1 与 MyCAT2 的执行内核不同**：1.x 的路由与归并逻辑内建于 `io.mycat.route` 与 `io.mycat.server`；2.x 把这部分交给 Calcite 的 rule+cost 优化器和自研物理执行引擎，还支持用自研 DSL 直接改写物理执行计划。跨库 join 的能力上限因此完全不同。

## Map of This Section

七个分册对应使用 MyCAT 时七类不同的问题：

- **[Architecture](/docs/CS/DB/MyCat/Architecture.md)**——「它到底是什么形状」。Cobar 血脉、NIO 前端、解析—路由—归并五段流水线、MyCAT1 与 MyCAT2 两条内核的差异。理解其他分册的地图。
- **[Configuration](/docs/CS/DB/MyCat/Configuration.md)**——「怎么把它配起来」。server.xml / schema.xml / rule.xml 三件套 + sequence + zkconf，含 rule.xml 出厂函数的完整清单与属性。几乎所有「为什么没分上片」的问题都收敛到这页。
- **[Sharding_Rules](/docs/CS/DB/MyCat/Sharding_Rules.md)**——「数据按什么散开」。18 个分片算法的语义与选型、1.675 之后 `PartitionByLong` 分布不兼容这条暗礁、ER 分片与全局表两种「让 join 不跨库」的手段。
- **[SQL_Routing](/docs/CS/DB/MyCat/SQL_Routing.md)**——「一条 SQL 会被拆成什么样」。单节点路由 vs 广播、跨库 join 的三档支持（单库任意 join / 跨库两表 / caltlet 多表）、聚合与跨库分页的归并语义、1.6 的能力禁区。
- **[Read_Write_Split](/docs/CS/DB/MyCat/Read_Write_Split.md)**——「读请求去了哪、主库挂了怎么办」。balance / writeType / switchType 三组枚举值、心跳检测原理、Galera 集群支持，以及 MyCAT2 的连接回收与会话粘滞。
- **[Transactions](/docs/CS/DB/MyCat/Transactions.md)**——「一致性到什么程度」。弱 XA 与 XA（1.6.5 起）的语义边界、`next value for MYCATSEQ_GLOBAL` 全局序列、与 Seata 类外部事务协调者的分工。
- **[Operations](/docs/CS/DB/MyCat/Operations.md)**——「怎么部署、怎么排障、怎么撤」。1.6 与 2.0 两条安装路径、命令行与 Web 监控、1.6 已知要避开的功能清单、1.x 到 2.x 的迁移与「换掉 MyCAT」的路径。

## Applicable Scenarios

MyCAT 的甜点区可以一句话概括：**存储是现成的 MySQL 主从集群，业务已经撞上单库容量/写入上限，且接入方语言庞杂（Java 之外的客户端也要连）**。

适合：

- **多语言接入的分库分表**：PHP、C#、Go 客户端不可能装一个 JDBC jar，代理层是唯一对业务零侵入的方案。MyCAT2 甚至显式支持了 C# 客户端。
- **DBA 视角的统一入口**：对运维表现为一台 MySQL，权限、SQL 黑名单、慢查询、连接池都收在中间件一层管。
- **渐进式改造**：先用读写分离扛读流量，再逐步切分库表；schema.xml 里同一张表可以先只挂一个 dataNode。
- **异构后端聚合**：后端混布 MySQL + Oracle/DB2 的老系统，用一层 MySQL 协议面具统一 SQL 入口。

不适合：

- **追求极限延迟的 OLTP**：多一跳网络 + 一次结果归并，事务语义还降级，换来的是架构上的便利而不是性能。
- **强一致分布式事务是硬需求**：弱 XA 是尽力而为，XA 只是两阶段提交的最低保障；真需要 Serializable 跨分片事务，应该看 NewSQL。
- **SQL 极其灵活多变的场景**：路由依赖分片键，不带分片键的即席查询会退化成全分片广播，中间件只会放大这个问题。
- **Java 单体且愿意引 jar**：同代数下 [ShardingSphere](/docs/CS/DB/Middleware/ShardingSphere.md)-JDBC 少一跳，能力还更全。

| 条件 | 选择 |
| :--- | :--- |
| 多语言客户端、要求零侵入 | MyCAT 代理层 |
| Java 技术栈、要极致性能与更全特性 | ShardingSphere-JDBC |
| 跨分片复杂 join、要 Calcite 级优化 | MyCAT2 / ShardingSphere-Proxy |
| 数据量大但查询模式固定、能改 SQL | 应用层分片 + Shard 机制 |

## Facts Worth Pinning Down

最容易被版本与默认值坑到的几条，完整清单散布在各分册：

1. **`PartitionByLong` 在 1.675 之后数据分布与之前不兼容**：2020-01-01 合入的 PR 优化了该算法的均衡性，同一个分片列在 1.675 前后会落到不同分片。升级跨越这个点时，等于一次数据重分布。
2. **1.6 不支持一个连接里多条语句**（multi-statement），且官方 README 明确点名三个要避开的功能：批处理插入、多语句、堆外合并。
3. **XA 事务 1.6.5 才有**；更早的版本只有「弱 XA」——一阶段提交 + 异常时人工/应用补偿。看到「MyCAT 支持分布式事务」的旧文，先问版本。
4. **ZooKeeper 协调（主从切换、zk 序列、配置 zk 化）是 1.6 的特性**，不是 1.5 及更早的默认能力。
5. **MyCAT2 只支持 Java 8**（README 原文 "Currently, only mycat2 is supported on java8"），且 License 在 2023.8 从 GPL 换成了 Apache。
6. **全局序列号的 SQL 写法是 `next value for MYCATSEQ_GLOBAL`**，不是 MySQL 8 的 `AUTO_INCREMENT` 语义，ORM 默认主键策略直接接不上。
7. **默认 SQL 解析器是 `druidparser`**（server.xml `defaultSqlParser`），基于 Druid；解析失败的行为与 MySQL 原生解析器并不总是一致。
8. **MyCAT 是中间件不是数据库**：它不解决共识、不复制数据、故障切换依赖后端 MySQL 主从（或 Galera）自身，MyCAT 集群自身不共享状态。

## Links

- [Shard](/docs/CS/DB/Concept/Shard.md)
- [ShardingSphere](/docs/CS/DB/Middleware/ShardingSphere.md)
- [TDDL](/docs/CS/DB/Middleware/TDDL.md)
- [DB](/docs/CS/DB/DB.md)
- [MySQL](/docs/CS/DB/MySQL/MySQL.md)

## References

1. [MyCAT 官方网站](https://www.mycat.org.cn)
2. [MyCATApache/Mycat-Server（MyCAT1 源码）](https://github.com/MyCATApache/Mycat-Server)
3. [MyCATApache/Mycat2（MyCAT2 源码）](https://github.com/MyCATApache/Mycat2)
4. [Mycat-Server: src/main/resources/rule.xml（出厂分片规则）](https://github.com/MyCATApache/Mycat-Server/blob/master/src/main/resources/rule.xml)
5. [MyCAT 教程与案例](https://mycat.org.cn/docs/tutorial)
