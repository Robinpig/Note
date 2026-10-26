## Introduction

MyCAT 的架构可以用一个反差概括：**对外是最保守的「一台 MySQL 服务器」，对内是一次彻底的 SQL 重写与结果重组**。它不改动任何一个存储节点的部署形态，却在中间件层把「单库单表」的语法翻译成「多分片并行执行 + 内存归并」的分布式执行计划。本页讲清这台机器的骨架：Cobar 血脉、NIO 前端、解析—路由—归并五段流水线，以及 MyCAT1 与 MyCAT2 两套内核的边界。分片算法的选型在 [Sharding_Rules](/docs/CS/DB/MyCat/Sharding_Rules.md)，配置语法在 [Configuration](/docs/CS/DB/MyCat/Configuration.md)。

## From Cobar to MyCAT

2013 年，阿里开源的 Cobar 在社区使用中暴露出若干严重问题与使用限制，MyCAT 发起人做了第一代改良，MyCAT 由此诞生。它与 Cobar 的关系不是 fork 后打补丁，而是**彻底重构**：

- **网络层用 NIO 重写**，替换 Cobar 的阻塞式线程模型，Buffer 内核一并优化——这是「解决高并发」的根基，也是官方特性清单里「基于 Nio 实现，有效管理线程」的来历。
- **增强了聚合、Join 等基本特性**：跨库两表 join、caltet 多表 join、跨库分页都是这一层的产物。
- **兼容绝大多数数据库**：从 MySQL 专用代理扩展为通用数据库中间件（前端 MySQL 协议不变，后端 JDBC 通用）。
- **1.4 版本以后完全脱离 Cobar 内核**，此后叠加集群管理、自动扩容、智能优化等自有方向。

2015 年 5 月《Mycat 权威指南》电子版发布（社区编写，开源项目中少有的成体系文档），同年项目已有 16 位 Committer、超过 300 个采用项目——这是 MyCAT 影响力的顶点，此后重心逐渐转向 MyCAT2。

## The Five-Stage Pipeline

### 1. Frontend Protocol

MyCAT 监听 8066 端口（管理口 9066），与客户端完成 MySQL 握手、认证（server.xml 里配置的逻辑用户）、命令解析。对客户端而言它只是一台 MySQL：`mysql -h mycat -P8066 -uroot` 直接可用，客户端不需要任何特殊驱动。1.6 起前端还支持：

- **prepare 预编译指令**（COM_STMT_*）
- **PostgreSQL native 协议**（不只是 JDBC 后端）
- **IP 白名单、SQL 黑名单、密码加密**——安全特性收在中间件层

这一层有一个必须记住的限制：**1.6 不支持一个连接内多条语句**（multi-statement）。

### 2. SQL Parsing

路由之前先解析。默认解析器是 **druidparser**（server.xml 的 `defaultSqlParser` 指定，基于 Druid 的 SQL 解析器），输出的是「这条 SQL 碰了哪些逻辑表、WHERE 里有哪些分片列、条件是什么形态」。解析结果直接决定路由的可能性：

- 分片列上出现**等值条件** → 精确路由，只打一个分片
- 分片列上出现**范围条件** → 可能路由到多个分片
- 分片列缺失或条件不可解析 → **全分片广播**

### 3. Routing

Router 拿解析结果去查两样东西：schema.xml 里的逻辑表配置（dataNode、rule）和 rule.xml 里的分片算法。产出两部分决策：

- **节点集合**：哪些 dataNode 参与这条 SQL
- **SQL 改写**：把逻辑表名替换成物理表名、把跨库 join 拆成多次单库查询、把 `LIMIT` 改写成各分片可执行的形式

改写逻辑按表类型分流：全局表（type="global"）在每个节点都有全量，直接下发任一节点；ER 子表跟着父表的分片列走；普通分片表按 rule 计算。

### 4. Execution

每个参与节点对应一个后端 JDBC 连接（dataHost 的 maxCon/minCon 控制连接池）。MyCAT 对多分片查询是**并发下发**的，不是串行；连接池按 dataHost 隔离，读写分离的调度在 Read_Write_Split 里展开。

### 5. Result Merge

归并是 MyCAT 最容易被低估的一层：

- **聚合函数**：`sum`/`count`/`max`/`min` 等在各分片本地算完再合并（1.6 起支持非堆内存/Direct Memory 做聚合计算，缓解大结果集的内存压力）
- **排序**：跨分片 ORDER BY 走多路归并
- **分页**：跨库分页是「各分片取窗口 → 归并排序 → 截断」，不是全量拉回
- **去重与 UNION**：同样按集合语义归并

归并全部发生在 MyCAT 进程内——**中间件的内存就是分布式查询的内存上限**，这是分片数不能无限扩大的隐性约束。

## MyCAT1 vs MyCAT2: Two Kernels

「MyCAT」这个名字下有两套完全不同的执行内核，选型前必须分清：

| 维度 | MyCAT 1.x（Mycat-Server） | MyCAT 2.x（Mycat2） |
| :--- | :--- | :--- |
| 源码仓库 | MyCATApache/Mycat-Server | MyCATApache/Mycat2 |
| 查询引擎 | 自研路由 + 内建归并逻辑 | **Apache Calcite**（规则优化 + 代价优化） |
| 执行层 | 内建于 server 模块 | 独立物理执行引擎，支持自研 DSL 改写物理计划 |
| 配置形态 | XML（server/schema/rule 三件套） | JSON（datasource.json / user.json 等） |
| 运行环境 | Java（1.6-RELEASE 发行线） | **仅 Java 8**（README 明示） |
| License | Apache-2.0 | 2023.8 前 GPL，此后 Apache-2.0 |
| 跨库 join | 单库任意 join、跨库两表 join、caltet 多表 | Calcite 优化器 + BKAJOIN、全局二级索引 |
| 后端 | JDBC 通用 + PostgreSQL native | JDBC 通用 + 内置 ClickHouse 数据源 |
| 集群能力 | ZooKeeper 协调主从切换（1.6） | 会话粘滞、Prometheus exporter、PHP-Admin |

两行代码级的提醒：

- MyCAT2 的仓库模块名直接暴露了架构：`calcite`、`router`、`executor`、`replica`、`datasource`、`migrate`、`seata`——分别对应查询引擎、路由、执行、副本管理、数据源、迁移与事务集成。看到 `seata` 模块就知道它把外部事务协调者的集成当作一等公民。
- MyCAT2 声称「查询引擎可以脱离网络框架运行」，即引擎与协议层解耦，这是 1.x 没有的设计。

## What MyCAT Is Not

架构上三条边界，决定了它出问题时的排查方向：

- **不是高可用组件自身**：故障切换依赖后端 MySQL 主从复制状态或 Galera 集群，MyCAT 只做检测与摘除（见 [Read_Write_Split](/docs/CS/DB/MyCat/Read_Write_Split.md)）。MyCAT 进程本身多实例部署时彼此不共享状态，前面通常还要 LVS/HAProxy 层。
- **不缓存数据**：1.x 有 ehcache 配置项（源码 `src/main/resources/ehcache.xml`），但默认不改变「每次查询都打后端」的形态；MyCAT2 显式提供了结果集缓存开关。
- **不做共识**：元数据、binlog、事务持久化全在后端。中间件重启的代价是连接重建，不是数据风险。

## Links

- [MyCat](/docs/CS/DB/MyCat/MyCat.md)
- [Configuration](/docs/CS/DB/MyCat/Configuration.md)
- [SQL_Routing](/docs/CS/DB/MyCat/SQL_Routing.md)
- [Read_Write_Split](/docs/CS/DB/MyCat/Read_Write_Split.md)
- [Shard](/docs/CS/DB/Shard.md)

## References

1. [MyCATApache/Mycat-Server README（Cobar 渊源与已知限制）](https://github.com/MyCATApache/Mycat-Server)
2. [MyCATApache/Mycat2 README（Calcite 引擎与 Java 8 限制）](https://github.com/MyCATApache/Mycat2)
3. [MyCAT 官方网站 · 关键特性](https://www.mycat.org.cn)
