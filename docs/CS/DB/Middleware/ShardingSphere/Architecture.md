## Introduction

ShardingSphere 把自己定位成 Database Plus：不造新数据库，而是在既有数据库之上加一层**标准与生态**，把「分库分表、读写分离、分布式事务、加密脱敏、影子库、治理」这些单库缺失的能力透明地补回去。本页拆开它的三层可插拔架构、两种接入端与两种运行模式——分册里所有功能的形状都由这三件事决定。

版本锚点 **5.5.3（2026-03-01 发布，5.5.4 开发中）**；Apache 顶级项目（TLP）自 2020-04-16 起。所有结论以官方文档、发布说明与源码为准。

## Database Plus

设计哲学拆成三个关键词，对应三种不同的工程动作：

- **Connect（连接）**：灵活适配数据库协议、SQL 方言与数据库存储，在多模态异构数据库之上建立标准，并通过内置 DistSQL 给应用提供统一的连接方式。产物是「用什么库都一样」。
- **Enhance（增强）**：捕获数据库访问入口，透明地叠加能力——redirect（分片、读写分离、影子库）、transform（加密、脱敏）、authentication（安全、审计、权限）、governance（熔断、限流、分析、QoS、可观测）。产物是「单库没有的功能」。
- **Pluggable（可插拔）**：微内核 + 三层可插拔，功能与数据库生态像乐高一样嵌入，开发者可以拼出自己的 ShardingSphere。

注意 Connect/Enhance/Pluggable 是**能力分类**，不是目录结构；真正落到代码与部署上的是下面的三层模型与两种接入端。

## Pluggable Architecture

微内核 + 三层，每层的组件地位完全不同：

| 层 | 地位 | 内容 |
| :--- | :--- | :--- |
| L1 内核层 | 全部必需，实现可替换 | 查询优化器、分布式事务引擎、分布式执行引擎、权限引擎、调度引擎 |
| L2 功能层 | 全部可选，相互隔离、可叠加 | 数据分片、读写分离、数据加密、影子库等；面向内核定义的顶层接口自定义，不改内核代码 |
| L3 生态层 | 对接外部世界 | 数据库协议、SQL 解析器、存储适配器——分别对应「用什么协议提供服务」「用什么方言操作数据」「与哪类存储节点交互」 |

「数据库类型完全解耦、功能模块完全解耦」是这套架构的直接结果：接入新数据库只动 L3，加新功能只动 L2。代价是抽象层数多——同一事实（比如一条 SQL 怎么路由）可能在内核、功能、生态三层各出现一次，读源码时容易迷路。

## Access Ends

ShardingSphere 有两个接入端：**ShardingSphere-JDBC** 与 **ShardingSphere-Proxy**。旧文档里的 Sidecar（Database Mesh）早已不在官方叙事中，2026 年的官方表述就是「两个既可独立部署、又可混合部署配合使用的产品」。

| 维度 | ShardingSphere-JDBC | ShardingSphere-Proxy |
| :--- | :--- | :--- |
| 形态 | jar 包，增强版 JDBC 驱动 | 独立部署的数据库代理服务器 |
| 数据库 | 任何 JDBC 标准数据库（MySQL、PostgreSQL、Oracle、SQLServer 等） | MySQL / PostgreSQL 协议（兼容 MariaDB、openGauss） |
| 异构语言 | 仅 Java | 任意兼容 MySQL/PostgreSQL 协议的客户端 |
| 连接数成本 | 多（每个应用一份） | 少（一个静态入口） |
| 性能 | 低损耗 | 相对高损耗（多一跳网络） |
| 去中心化 | 是 | 否 |
| 静态入口 | 无 | 有 |
| 适用 | 高性能轻量 OLTP、Java 同构 | OLAP、异构语言、DBA 运维 |

**混合部署**：JDBC 与 Proxy 通过同一个注册中心配置统一的分片策略，架构师可以按业务现状自由调整两者比例。官方明确建议混合部署使用集群模式。

## Running Modes

- **单机模式（Standalone）**：元数据持久化在本地文件，实例之间互不感知——改一个实例的元数据，其他实例不会同步。适合本地开发与测试。
- **集群模式（Cluster）**：元数据存注册中心，多实例共享配置、协调状态，支撑计算能力水平扩展与高可用。**生产环境与混合部署都必须用集群模式**。

两种模式的切换就是元数据持久化仓库的切换：Standalone 用 File，Cluster 用 ZooKeeper 或 Etcd。细节见 [Governance](/docs/CS/DB/Middleware/ShardingSphere/Governance.md)。

## Facts Worth Pinning Down

1. **Sidecar 已死（至少不在官方产品叙事里）**：旧版文档的「Sidecar (Planning)」与 Database Mesh 叙事，在 5.x 后期已从官网与 README 消失。当前只有 JDBC 与 Proxy 两款产品，别再按三件套做架构选型。
2. **L2 功能层全部可选且相互隔离**：加密、分片、读写分离是独立规则，可以任意组合；没用到的功能不会进执行链路。
3. **Proxy 是静态入口**：新增 Proxy 节点即扩展计算能力，这是集群模式「水平扩展算力」的物理基础；JDBC 的算力则随应用实例走。
4. **单机模式的元数据不共享**：多实例各改各的，配置漂移没有告警——本地环境可以，生产不行。

## Links

- [Distributed Transaction](/docs/CS/DB/Middleware/ShardingSphere/Distributed_Transaction.md)
- [Operations](/docs/CS/DB/Middleware/ShardingSphere/Operations.md)
- [DB](/docs/CS/DB/DB.md)

## References

1. [Apache ShardingSphere](https://shardingsphere.apache.org/)
2. [ShardingSphere Documentation](https://shardingsphere.apache.org/document/)
3. [Overview :: ShardingSphere](https://shardingsphere.apache.org/document/current/en/overview/)
4. [Your Detailed Guide to Apache ShardingSphere's Operating Modes](https://shardingsphere.apache.org/blog/en/material/jan_28_your_detailed_guide_to_apache_shardingspheres_operating_modes)
5. [apache/shardingsphere](https://github.com/apache/shardingsphere)
