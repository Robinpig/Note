## Introduction

Apache HBase 是构建在 [HDFS](/docs/CS/Framework/Hadoop/HDFS.md) 之上的、开源的、分布式、面向列（column-family）的 **NoSQL 数据库**，提供 Hadoop 生态里的**海量结构化数据实时随机读写**能力（低延迟点查/写、按 rowkey 范围扫描）。

它是 Google [Bigtable](/docs/CS/Distributed/Bigtable.md) 论文的开源实现：Bigtable 论文里的 GFS → HBase 用 HDFS，Chubby（锁/协调）→ [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)，Master/Tablet Server → HMaster/HRegionServer。HBase 与 Hive 解决的是互补问题：Hive 走 [MapReduce](/docs/CS/Framework/Hadoop/MapReduce.md) 做高延迟离线分析，HBase 提供在线随机访问（定位对比见 [HBase 与 Hive/MySQL 对比](/docs/CS/DB/HBase.md)）。

## Data Model

HBase 的数据模型是稀疏、多维、有序的 map：

- **Row（行）**：以 **RowKey** 唯一标识，表内所有行按 RowKey **字典序全局有序**存储——这是 HBase 最重要的特性，决定了按前缀/范围扫描很快，而二级索引很弱，RowKey 设计（salting、反转、前缀）是核心课题。
- **Column Family（列族）**：建表时预定义，数量少且固定（如 `info`、`addr`）；物理上不同列族存成不同文件。
- **Column Qualifier（列限定符）**：列族下的列，**无需预先定义、可动态增减**，因此表是“稀疏”的，空列不占空间。
- **Timestamp / Version**：每个单元格（cell）按时间戳保留多个版本。
- **Cell**：由 `(rowkey, column family, qualifier, timestamp)` 定位，值是无类型字节数组。

逻辑坐标即 `Map<RowKey, Map<ColumnFamily, Map<Qualifier, Map<Timestamp, Value>>>>`。

## Architecture

- **HMaster**：管理元数据（建表/删表、列族变更、region 分配与迁移、负载均衡），**不参与实际数据读写**，因此 Master 宕机不影响在线读写（短时只影响管理操作）。
- **HRegionServer**：工作节点，服务多个 **Region**，处理客户端的读写请求、flush、compaction、WAL。
- **Region**：一张大表按 RowKey 范围水平切分成多个 Region，是分布式与负载均衡的单位；一个 Region 内按列族有多个 **Store**。
- **ZooKeeper**：集群协调、Master 选举、元数据入口（`hbase:meta` 位置）、RegionServer 注册与故障发现。
- 元数据定位：客户端先通过 ZooKeeper 找到 `hbase:meta` 系统表，再查出某 RowKey 属于哪个 RegionServer 的哪个 Region，并在客户端缓存路由。

```
Client -> ZooKeeper(找 meta) -> hbase:meta(定位 Region) -> HRegionServer(读写)
HRegionServer -> Region -> Store(per CF) -> MemStore + HFile
读写持久化 -> HDFS(HFile)；协调 -> ZooKeeper；元数据/调度 -> HMaster
```

## Storage: LSM Tree

HBase 底层采用 **LSM-Tree（Log-Structured Merge Tree）** 写优化结构，这是它高写入吞吐的来源：

1. 写入先追加 **WAL（HLog）** 保证宕机不丢，再写入内存中的 **MemStore**（有序）。
2. MemStore 达到阈值后 **flush** 成磁盘上不可变的 **HFile**（实际落在 HDFS）。
3. HFile 越来越多，后台触发 **Compaction** 合并：minor compaction 合并小 HFile，major compaction 把一个 Store 的 HFile 合并成一个、清理删除标记与过期版本（代价较大）。
4. 删除不是立即抹除，而是写入 **tombstone 标记**，在 major compaction 时才真正清除（与 [Lucene 段合并的删除标记](/docs/CS/Framework/ES/Lucene.md)思路类似，都是不可变文件 + 后台合并）。
5. 读取需在 MemStore 与多个 HFile（含 BlockCache、Bloom Filter 快速判断文件是否含该 rowkey）中合并结果，因此读可能被过多 HFile 拖慢——compaction 调优很关键。

## Consistency and Use Cases

- 提供**单行强一致**（同一 row 的原子读写、checkAndPut/CAS、行级事务）；跨行/跨表事务支持有限。
- 适合：超大表、高写入吞吐、按 RowKey 的点查与范围扫描、时序/画像/消息/订单明细等。
- 不适合：复杂 SQL join、任意列的即席条件查询（无原生二级索引时非 RowKey 查询等于全表扫描）、多行事务。

## Links

- [Bigtable 论文](/docs/CS/Distributed/Bigtable.md)
- [HBase 与 Hive/MySQL 对比](/docs/CS/DB/HBase.md)
- [HDFS](/docs/CS/Framework/Hadoop/HDFS.md)
- [Hadoop](/docs/CS/Framework/Hadoop/Hadoop.md)
- [MapReduce](/docs/CS/Framework/Hadoop/MapReduce.md)
- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)

## References

1. [Apache HBase Reference Guide](https://hbase.apache.org/book.html)
2. [Bigtable: A Distributed Storage System for Structured Data](https://research.google/pubs/bigtable-a-distributed-storage-system-for-structured-data/)
3. [Apache HBase Architecture](https://hbase.apache.org/book.html#arch)
