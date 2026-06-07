## Introduction

[Apache ShardingSphere](https://shardingspache.apache.org/) 定位为 Database Plus，旨在构建异构数据库之上的标准层和生态系统。
它专注于如何在现有数据库及其各自上层之上进行复用，而不是创建新的数据库。
目标是最大限度地减少或消除底层数据库碎片化带来的挑战。

该项目的核心概念是 Connect、Enhance 和 Pluggable。

- **Connect：**
  灵活适配数据库协议、SQL 方言和数据库存储。
  它可以快速连接应用程序和异构数据库。
- **Enhance：**
  捕获数据库访问入口以透明地提供额外功能，例如：
  重定向（分片、读写分离和影子库）、
  转换（数据加密和脱敏）、
  认证（安全、审计和权限）、
  治理（熔断和访问限制与分析、QoS 和可观测性）。
- **Pluggable：**
  利用微内核和 3 层可插拔模式，可以灵活地嵌入功能和数据库生态。
  开发人员可以像搭 LEGO 积木一样自定义他们的 ShardingSphere。

![](https://shardingsphere.apache.org/document/current/img/overview.en.png)

Apache ShardingSphere 包含 3 个独立的产品：JDBC、Proxy 和 Sidecar（规划中）。
它们都提供数据扩展、分布式事务和分布式治理的功能，适用于 Java 同构、异构语言和云原生等多种场景。

## ShardingSphere-JDBC

ShardingSphere-JDBC 将自己定义为一个轻量级 Java 框架，在 Java JDBC 层提供额外服务。
客户端直接连接到数据库，以 jar 包形式提供服务，无需额外的部署和依赖。
它可以被视为一个增强的 JDBC 驱动，完全兼容 JDBC 和各种 ORM 框架。

适用于任何基于 JDBC 的 ORM 框架，例如 JPA、Hibernate、Mybatis、Spring JDBC Template 或直接使用 JDBC；
支持任何第三方数据库连接池，例如 DBCP、C3P0、BoneCP、HikariCP；
支持任何类型的 JDBC 标准数据库：MySQL、PostgreSQL、Oracle、SQLServer 以及任何适配 JDBC 的数据库。

## ShardingSphere-Proxy

ShardingSphere-Proxy 将自己定义为一个透明的数据库代理，提供一个封装了数据库二进制协议的数据库服务器以支持异构语言。
目前，提供 MySQL 和 PostgreSQL（兼容基于 PostgreSQL 的数据库，如 openGauss）版本。
它可以与任何兼容 MySQL 或 PostgreSQL 协议的终端（如 MySQL Command Client、MySQL Workbench 等）一起使用来操作数据，对 DBA 更加友好。

对应用程序透明，可以像 MySQL 和 PostgreSQL 服务器一样直接使用；
适用于任何兼容 MySQL 和 PostgreSQL 协议的终端。

## ShardingSphere-Sidecar

ShardingSphere-Sidecar（TODO）将自己定义为 Kubernetes 环境中的云原生数据库代理，以 sidecar 的形式负责所有数据库访问。
它提供了一个与数据库交互的网格层，我们称之为 Database Mesh。

Database Mesh 强调如何将分布式数据访问应用程序与数据库连接起来。
它专注于交互，有效地组织了混乱的应用程序和数据库之间的交互。
使用 Database Mesh 访问数据库的应用程序和数据库将形成一个大型网格系统，它们只需被放置在相应的正确位置。
它们都由网格层管理。


ShardingSphereDataSourceFactory

ShardingStrategyConfiguration(shardingAlgorithmName, shardingColumns)
- StandardShardingStrategyConfiguration
- HintShardingStrategyConfiguration
- ComplexShardingStrategyConfiguration
ShardingRuleConfiguration
TableRuleConfiguration
KeyGeneratorConfiguration

## Links

- [DataBases](/docs/CS/DB/DB.md)
