## Introduction

HBase 的数据模型是它所有性能的源头，也是所有坑的根：表是「稀疏、多维、有序的 map」，按 RowKey 全局字典序排列。本页拆出列族、列限定符、版本、Cell 的语义与建表默认值，并解释「宽列 ≠ 列式存储」这一最常被混用的概念，以及中等对象（MOB）这条独立 IO 路径。完整数据模型与 [HBase](/docs/CS/DB/HBase/HBase.md) 的其它机制串在一起看。

## Data Model

HBase 的数据模型是稀疏、多维、有序的 map，逻辑坐标即 `Map<RowKey, Map<ColumnFamily, Map<Qualifier, Map<Timestamp, Value>>>>`：

- **Row（行）**：以 **RowKey** 唯一标识，表内所有行按 RowKey **字典序全局有序**存储。这是 HBase 最重要的性质——它同时是范围扫描快的原因、二级索引弱的根因，以及 RowKey 设计成为核心课题的由来。
- **Column Family（列族）**：建表时预定义，数量少且固定（如 `info`、`addr`）。**物理上一个列族就是一个 Store、一组独立文件**，因此列族划分就是物理布局划分。
- **Column Qualifier（列限定符）**：列族下的列，**无需预定义、可动态增减**，空列不占空间，所以表是稀疏的。
- **Timestamp / Version**：每个 cell 按时间戳保留多版本，列族默认 `VERSIONS => 1`。
- **Cell**：由 `(rowkey, column family, qualifier, timestamp)` 定位，值是无类型 `byte[]`。

列族（column family）不等于列式存储（column store）。宽表把「同一行、同一列族」的数据存在一起，面向按行取；OLAP 列存把「同一列、跨行」的值压缩在一起，面向扫描聚合。两者的取舍见 [HBase](/docs/CS/DB/HBase/HBase.md) 的 Comparison，混用这两个概念是最常见的表述错误。

建表时的列族默认值（`ColumnFamilyDescriptorBuilder`，branch-2.6 与 branch-3.0 一致）：

| 属性 | 默认值 | 含义与代价 |
| :--- | :--- | :--- |
| `BLOOMFILTER` | `ROW` | 默认就开行级 Bloom，不是关闭 |
| `BLOCKSIZE` | `65536`（64 KB） | HFile 块大小，决定读粒度与索引开销 |
| `DATA_BLOCK_ENCODING` | `NONE` | 3.0 的枚举为 `NONE/PREFIX/DIFF/FAST_DIFF`，2.6 还含 `PREFIX_TREE`（3.0 已移除） |
| `COMPRESSION` | `NONE` | 生产上几乎必改 SNAPPY/ZSTD |
| `VERSIONS` | `1` | 多版本直接放大读路径要扫的文件数 |
| `IN_MEMORY` | `false` | 仅对极少数量小的元数据表有意义 |
| `IS_MOB` / `MOB_THRESHOLD` | `false` / `102400`（100 KB） | 见下 |

**值的大小**：HBase 常规读写路径为**小于 100 KB 的 value** 优化。存图片、文档这类中等对象应开 MOB（`IS_MOB => true`），让大 value 落到独立的 MobFile，避免把 HFile 与索引撑爆——把 10 MB 的 cell 塞进普通列族，等于让 BlockCache 和 compaction 陪葬。

## MOB (Medium Object Storage)

中等大小对象（100 KB ~ 10 MB 的图片、文档、短视频）直接塞进普通列族会拖垮 HBase：大 value 让 HFile 与 BlockCache 膨胀、compaction 与 split 的写放大剧增。HBASE-11339（**2.0.0 引入**，并需要 HFile v3）专门为此加了 MOB 这条独立 IO 路径。

机制核心是「**把大于阈值的 value 搬出普通 Region 文件**」：

- 开启 MOB 的列族，flush 时**同时写两份**：小于阈值的 cell 走普通 Region HFile；大于阈值的 cell 写进独立的 **MOB HFile**，并在普通 HFile 里留一个 **MOB reference cell**（key 与原 cell 相同，value 是「真实值大小 + 所在 MOB 文件」两段元数据）。读时先取 reference、再按元数据去 MOB 文件取真实值。
- 列族开关：`IS_MOB => true`（必填）与 `MOB_THRESHOLD`（默认 **102400，即 100 KB**）。不配阈值时用默认 100 KB 判定。客户端代码**无感知**——这对应用是透明的。
- 收益：MOB 数据不参与普通 Region 的 split / merge / 常规 compaction，写放大与 IO 压力大幅下降；代价是大 value 多一次文件 IO（reference → MOB file），且 MOB 自身有独立的 compaction（HBASE-22749 起跨 RegionServer 并行做 MOB compaction）。

> [!NOTE]
> MOB 阈值与「常规读写路径优化 < 100 KB」的口径一致：100 KB 以下是 HBase 的舒适区，100 KB~10 MB 交给 MOB，超过 10 MB 仍建议直接存 HDFS、在 HBase 里只留引用。MOB 与 MOB_THRESHOLD 一起定义，对普通列族无任何影响（官方 release note 强调 MOB 与其它组件几乎隔离）。

## Links

- [HBase](/docs/CS/DB/HBase/HBase.md)
- [LSM Tree](/docs/CS/Algorithms/tree/LSM.md)
- [Bigtable](/docs/CS/Distributed/Bigtable.md)

## References

1. [Apache HBase Reference Guide](https://hbase.apache.org/book.html)
2. [Apache HBase ColumnFamilyDescriptorBuilder](https://github.com/apache/hbase/blob/branch-3.0/hbase-client/src/main/java/org/apache/hadoop/hbase/client/ColumnFamilyDescriptorBuilder.java)
3. [Bigtable: A Distributed Storage System for Structured Data](https://research.google/pubs/bigtable-a-distributed-storage-system-for-structured-data/)
4. [HBASE-11339 - HBase MOB](https://issues.apache.org/jira/browse/HBASE-11339)
