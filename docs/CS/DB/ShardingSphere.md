## Introduction

[Apache ShardingSphere](https://shardingsphere.apache.org/) is positioned as a Database Plus, and aims at building a standard layer and ecosystem above heterogeneous databases.
It focuses on how to reuse existing databases and their respective upper layer, rather than creating a new database.
The goal is to minimize or eliminate the challenges caused by underlying databases fragmentation.

The concepts at the core of the project are Connect, Enhance and Pluggable.

- **Connect**:
  Flexible adaptation of database protocol, SQL dialect and database storage.
  It can quickly connect applications and heterogeneous databases quickly.
- **Enhance**:
  Capture database access entry to provide additional features transparently, such as:
  redirect (sharding, readwrite-splitting and shadow),
  transform (data encrypt and mask),
  authentication (security, audit and authority),
  governance (circuit breaker and access limitation and analyze, QoS and observability).
- **Pluggable**:
  Leveraging the micro kernel and 3 layers pluggable mode, features and database ecosystem can be embedded flexibily.
  Developers can customize their ShardingSphere just like building with LEGO blocks.

![](https://shardingsphere.apache.org/document/current/img/overview.en.png)

Apache ShardingSphere including 3 independent products: JDBC, Proxy & Sidecar (Planning). 
They all provide functions of data scale-out, distributed transaction and distributed governance, applicable in a variety of situations such as Java isomorphism, heterogeneous language and Cloud-Native.

## ShardingSphere-JDBC

ShardingSphere-JDBC defines itself as a lightweight Java framework that provides extra services at the Java JDBC layer. With the client end connecting directly to the database, it provides services in the form of a jar and requires no extra deployment and dependence. It can be considered as an enhanced JDBC driver, which is fully compatible with JDBC and all kinds of ORM frameworks.

Applicable in any ORM framework based on JDBC, such as JPA, Hibernate, Mybatis, Spring JDBC Template or direct use of JDBC;
Supports any third-party database connection pool, such as DBCP, C3P0, BoneCP, HikariCP;
Support any kind of JDBC standard database: MySQL, PostgreSQL, Oracle, SQLServer and any JDBC adapted databases.

## ShardingSphere-Proxy

ShardingSphere-Proxy defines itself as a transparent database proxy, providing a database server that encapsulates database binary protocol to support heterogeneous languages. 
Currently, MySQL and PostgreSQL (compatible with PostgreSQL-based databases, such as openGauss) versions are provided. 
It can use any kind of terminal (such as MySQL Command Client, MySQL Workbench, etc.) that is compatible of MySQL or PostgreSQL protocol to operate data, which is friendlier to DBAs.

Transparent towards applications, it can be used directly as MySQL and PostgreSQL servers;
Applicable to any kind of terminal that is compatible with MySQL and PostgreSQL protocol.

## ShardingSphere-Sidecar

ShardingSphere-Sidecar (TODO) defines itself as a cloud-native database agent of the Kubernetes environment, in charge of all database access in the form of a sidecar. 
It provides a mesh layer interacting with the database, we call this Database Mesh.

Database Mesh emphasizes how to connect distributed data-access applications with the databases. 
Focusing on interaction, it effectively organizes the interaction between messy applications and databases. 
The applications and databases that use Database Mesh to visit databases will form a large grid system, where they just need to be put into the right positions accordingly. 
They are all governed by the mesh layer.




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
