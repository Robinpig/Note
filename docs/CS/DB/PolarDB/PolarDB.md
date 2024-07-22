## Introduction











PolarDB-X 是一款面向超高并发、海量存储、复杂查询场景设计的云原生分布式数据库系统。其采用 Shared-nothing 与存储计算分离架构，支持水平扩展、分布式事务、混合负载等能力，具备企业级、云原生、高可用、高度兼容 MySQL 系统及生态等特点。



 PolarDB-X 的核心特性如下：

- 水平扩展

PolarDB-X 采用 Shared-nothing 架构进行设计，支持多种 Hash 和 Range 数据拆分算法，通过隐式主键拆分和数据分片动态调度，实现系统的透明水平扩展。

- 分布式事务

PolarDB-X 采用 MVCC + TSO 方案及 2PC 协议实现分布式事务。事务满足 ACID 特性，支持 RC/RR 隔离级别，并通过一阶段提交、只读事务、异步提交等优化实现事务的高性能。

- 混合负载

PolarDB-X 通过原生 MPP 能力实现对分析型查询的支持，通过 CPU quota 约束、内存池化、存储资源分离等实现了 OLTP 与 OLAP 流量的强隔离。

- 企业级

PolarDB-X 为企业场景设计了诸多内核能力，例如 SQL 限流、SQL Advisor、TDE、三权分立、Flashback Query 等。

- 云原生

PolarDB-X 在阿里云上有多年的云原生实践，支持通过 K8S Operator 管理集群资源，支持公有云、混合云、专有云等多种形态进行部署，并支持国产化操作系统和芯片。

- 高可用

通过多数派 Paxos 协议实现数据强一致，支持两地三中心、三地五副本等多种容灾方式，同时通过 Table Group、Geo-locality 等提高系统可用性。

- 兼容 MySQL 系统及生态

PolarDB-X 的目标是完全兼容 MySQL ，目前兼容的内容包括 MySQL 协议、MySQL 大部分语法、Collation、事务隔离级别、Binlog 等。



## References

1. [PolarDB-X](https://www.zhihu.com/org/polardb-x)
2. [PolarDB 文档](https://polardbx.com/document?type=PolarDB-X)