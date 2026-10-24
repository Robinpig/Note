## Introduction

Apache HBase 是构建在 [HDFS](/docs/CS/Framework/Hadoop/HDFS.md) 之上的开源分布式**宽表（column-family）NoSQL 数据库**，补齐的是 Hadoop 生态里「海量数据的**低延迟随机读写**」这一格：Hive 走 [MapReduce](/docs/CS/Framework/Hadoop/MapReduce.md) 做高延迟离线分析，HBase 提供在线点查与按 RowKey 的范围扫描。

它是 Google [Bigtable](/docs/CS/Distributed/Bigtable.md) 论文的开源实现，组件一一对应：GFS → HDFS，Chubby（锁与协调）→ [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)，Master / Tablet Server → HMaster / HRegionServer，Tablet → Region。存储引擎侧它与 LevelDB、RocksDB、Cassandra 同属 **LSM 谱系**（见 [LSM Tree](/docs/CS/Algorithms/tree/LSM.md)）。

> [!NOTE]
> 版本口径：Maven Central 上 `org.apache.hbase:hbase` 的 release 已到 **3.0.0**（2.x 线仍在维护，2.6 系列已到 2.6.7），但生产集群以 2.x 为主体。两代在**客户端依赖**与**部分默认值**上不同，本页凡涉及具体默认值均以源码常量标注所属分支，不以手册正文为准——官方 `book.html` 当前是 4.0.0-alpha-1-SNAPSHOT 的开发版文档，正文数字存在滞后（下文 `hbase.client.scanner.caching` 就是一例）。

## Version Notes

2.x 为主体、3.0 开始铺开的当下，本页涉及的版本断点汇总：

| 事项 | 2.x | 3.0 |
| :--- | :--- | :--- |
| 客户端引导 | 必须配 `hbase.zookeeper.quorum`，读 ZK 拿 Master 与 meta 位置 | 默认 RPC connection registry，配 `hbase.masters`，不再依赖 ZK |
| Coprocessor | `hbase-protocol` 在位，旧 CPEP 可用 | `hbase-protocol` 模块移除，CPEP 需重编译 |
| 数据块编码 | 枚举含 `PREFIX_TREE` | 移除 `PREFIX_TREE`（枚举编号 1 不再占用） |

JDK 的口径是另一回事：JDK11 预支持自 2.3.0、JDK17 支持自 2.5.x（HBASE-22972 / HBASE-26038），生产选型前先核对所用 2.x 小版本与 Hadoop 的 JDK 兼容矩阵。

## Architecture and Positioning

HBase 是 Bigtable 的开源实现，组件一一对应：GFS→HDFS、Chubby→ZooKeeper、Master/Tablet Server→HMaster/HRegionServer、Tablet→Region；存储引擎与 LevelDB、RocksDB、[Cassandra](/docs/CS/DB/Cassandra.md) 同属 LSM 谱系。它与去中心化的 Cassandra 走的是两条宽列路线——HBase 有主（HMaster 管调度）、强依赖 HDFS 与 ZooKeeper，换来与 Hadoop 生态的紧耦合及 Phoenix 这类 SQL/二级索引生态；Cassandra 无主、自带提交日志与多 DC，换来易运维但放弃跨分区事务。

集群角色分工、Region 数量治理、以及 3.0 把客户端引导从 ZooKeeper 改为 RPC registry 的断点，见 [Architecture](/docs/CS/DB/HBase/Architecture.md)。

## Core Mechanisms

理解 HBase 性能，先抓住它「稀疏、多维、有序 map」的本质与 RowKey 这一唯一主键：数据模型决定列族即物理文件、RowKey 全局有序既是扫描快的原因也是二级索引弱的根因，详见 [Data Model](/docs/CS/DB/HBase/Data_Model.md)（含列族默认值与 MOB 这条独立 IO 路径）。

RowKey 三件事——分布是否均匀、前缀扫描是否可用、能否定位单 Region——全压在一个字段上，热点与二级索引是头号课题，缓解手段与索引补偿见 [RowKey Design](/docs/CS/DB/HBase/RowKey_Design.md)。

写路径是 LSM 写优化的典型：WAL→MemStore→flush→compaction，Bulk Load 绕开写路径灌 TB 级数据，WAL 的 provider 与 RegionServer 崩溃后的 split/replay 恢复见 [Write Path](/docs/CS/DB/HBase/Write_Path.md)。compaction 是读/写/空间放大分配的核心旋钮，内存侧 Accordion 与磁盘侧策略家族见 [Compaction](/docs/CS/DB/HBase/Compaction.md)。读路径是「内存 + 不可变文件」的归并，BlockCache 两种实现与 Bloom、scanner caching 见 [Read Path](/docs/CS/DB/HBase/Read_Path.md)。落盘格式 HFile 的 v2/v3 演进与 per-cell Tags 见 [HFile](/docs/CS/DB/HBase/HFile.md)。

## Region Management and Recovery

一张表按 RowKey 切分成 Region，是均衡单位；默认 SteppingSplitPolicy 让新表快速铺开又不碎，七种分裂策略与 Normalizer 收拾碎 Region，见 [Region Management](/docs/CS/DB/HBase/Region_Management.md)。宕机恢复是 Master 的 SCP 责任：先恢复 meta、再 WAL split、再重放，详见 [Write Path](/docs/CS/DB/HBase/Write_Path.md) 的故障恢复一节。

一致性一侧：HBase 只保证单行原子，CAS 是官方推荐的事务边界，跨行一致性要借外部框架或迁 TiDB / OceanBase；跨集群复制与集群内 Region 副本读见 [Replication](/docs/CS/DB/HBase/Replication.md)。运维上 2.x 起 hbck 只读化、修复移交 HBCK2，快照是零拷贝备份，见 [Operations](/docs/CS/DB/HBase/Operations.md)。

## Interface and Integration

HBase 内核没有 SQL 与原生二级索引，这两件事由 Coprocessor（注入 RegionServer 的 Observer / Endpoint）与构建其上的 Phoenix（SQL 层、JDBC、Global / Local 索引）补上，见 [Coprocessor and Phoenix](/docs/CS/DB/HBase/Coprocessor_and_Phoenix.md)。它也是 Hive 的常见存储后端——Hive 用 HBaseStorageHandler 把 HBase 表映射为外部表做 SQL 批量分析，组合边界见下文 Comparison。

## Security and Quotas

认证走 Kerberos，但要注意 2.x 起授权默认关闭这一反直觉事实；cell 级 Visibility Labels 依赖 HFile v3 的 per-cell Tags。配额与多租户见 [Security](/docs/CS/DB/HBase/Security.md)。

## Comparison

### Hive versus MySQL

| | Hive | MySQL |
| :---: | :--- | :--- |
| 查询语言 | HQL | SQL |
| 数据存储 | HDFS | 磁盘上 |
| 执行 | MR | Executor |
| 延迟 | 高 | 低 |
| 处理规模 | 大 | 小 |
| 索引 | 分区与桶裁剪为主，无 OLTP 式行级索引 | 有复杂的索引 |

### Hive versus HBase

| | HBase | Hive |
| :--- | :--- | :--- |
| 类型 | 宽表（列族）NoSQL 数据库 | 数据仓库 |
| 内部机制 | 数据库引擎 | MR |
| 增删改查 | 都支持 | 只支持导入跟查询 |
| Schema | 只需预定义列族，列可动态修改 | 需要预先定义表格 |
| 应用场景 | 实时 | 离线 |
| 特点 | K-V | 类 SQL |

两者常见组合是 Hive 把 HBase 当外部表（`STORED BY 'org.apache.hadoop.hive.hbase.HBaseStorageHandler'`）：用 HBase 存明细并提供点查，用 Hive 出 SQL 做批量分析。反过来说，这两张对比表也界定了各自的边界——把它们当同一个东西替换，是选型阶段最常见的事故。

### MySQL versus HBase

| | HBase | MySQL |
| :--- | :--- | :--- |
| 数据库 | NoSQL 数据库 | 关系型数据库 |
| 存储 | 按列族分文件，族内按行存 KV | 行 |
| 数据量 | 大 | 小 |
| 结构操作 | 非结构化与结构化数据的插入修改查询等简单操作 | 结构化数据的复杂操作 |

### Capability Matrix

| | [HBase](/docs/CS/DB/HBase.md) | [Cassandra](/docs/CS/DB/Cassandra.md) | [MongoDB](/docs/CS/DB/MongoDB.md) | [ClickHouse](/docs/CS/DB/ClickHouse.md) | [TiDB](/docs/CS/DB/TiDB.md) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 模型 | 宽表（列族）KV | 宽表（列族）KV | 文档 | 列式 OLAP | KV + SQL 关系模型 |
| 一致性 | 单行强一致 | 可调一致性，默认最终 | 副本集可线性读 | 副本最终一致为主 | Raft 强一致 + MVCC |
| 跨行事务 | 无原生支持 | 无（单分区原子批处理） | 多文档事务（4.0+） | 弱 | 支持，分布式 ACID |
| 二级索引 | 无，靠索引表 / Phoenix | 有但弱，代价是写放大 | 丰富，任意字段建索引 | 排序键 + 跳数索引 | B+ 树 + 全局索引 |
| 点查延迟 | 低 | 低 | 低 | 不适用 | 低 |
| 大范围扫描 | 按 RowKey 前缀/范围 | 需分区键友好 | 需索引或集合扫描 | 极强 | 走 TiFlash 列存 |
| 写入吞吐 | 极高（LSM + 顺序 WAL） | 极高 | 中 | 高（批量为主） | 中高 |
| 扩容 | Region 自动分裂迁移 | 无中心，线性 | 分片需规划 | 分片 + 副本 | 自动 Region 调度 |
| 关键依赖 | HDFS + ZooKeeper | 自带 gossip + 提交日志 | oplog + 副本集 | 本地存储 | PD + TiKV + Raft |
| 典型定位 | 超宽画像/明细/时序在线存 | 多活写入 | 灵活 Schema 业务库 | 报表与行为分析 | OLTP 主库 |

选型上真正要记住的是两句话：**要跨行事务和任意条件查询，就不该选 HBase；要在几十亿行上按主键取宽行、写入千万级 QPS，其它几个都做不动。** 更多分区与索引层面的取舍见 [Partition](/docs/CS/Distributed/Partition.md)。

## When to Use

适合：表规模到百亿行/TB 级以上、按 RowKey 或其前缀做点查与范围扫描、高写入吞吐、稀疏宽表（画像、特征、订单明细、消息、时序）、需要在线读到 HDFS 上那份数据。

不适合：复杂 join 与任意列即席查询（无二级索引时非 RowKey 查询等于全表扫描）、多行事务、频繁改主键、以 value 大小计的中大对象（走 MOB 或直接放对象存储）、低峰期需要一次性全表扫的业务（那是 Hive/Spark 的活）。

## Links

- [DataBases](/docs/CS/DB/DB.md)
- [Hive](/docs/CS/DB/Hive.md)
- [MySQL](/docs/CS/DB/MySQL/MySQL.md)

## References

1. [Apache HBase Reference Guide](https://hbase.apache.org/book.html)
2. [Apache HBase HConstants](https://github.com/apache/hbase/blob/branch-3.0/hbase-common/src/main/java/org/apache/hadoop/hbase/HConstants.java)
3. [Apache HBase ColumnFamilyDescriptorBuilder](https://github.com/apache/hbase/blob/branch-3.0/hbase-client/src/main/java/org/apache/hadoop/hbase/client/ColumnFamilyDescriptorBuilder.java)
4. [Apache Phoenix](https://phoenix.apache.org/)
5. [Apache HBase Operator Tools - HBCK2](https://github.com/apache/hbase-operator-tools)
6. [Bigtable: A Distributed Storage System for Structured Data](https://research.google/pubs/bigtable-a-distributed-storage-system-for-structured-data/)
7. [Apache HBase Bulk Loading](https://hbase.apache.org/docs/architecture/bulk-loading/)
8. [Storing Medium-sized Objects (MOB)](https://hbase.apache.org/docs/architecture/hbase-mob/)
9. [Apache HBase RegionServer (BlockCache)](https://hbase.apache.org/docs/architecture/regionserver/)
10. [Apache HBase Compaction package (policies)](https://hbase.apache.org/devapidocs/org/apache/hadoop/hbase/regionserver/compactions/package-summary.html)
11. [HBASE-11339 - HBase MOB](https://issues.apache.org/jira/browse/HBASE-11339)
12. [Salesforce Engineering - Evolution of Region Assignment Part 3 (SCP / WAL split)](https://engineering.salesforce.com/evolution-of-region-assignment-in-the-apache-hbase-architecture-part-3-e03b814ae92/)
13. [Apache Phoenix Downloads](https://phoenix.apache.org/downloads/)
