## Introduction

HFile 是 LSM 在 HDFS 上的落地文件格式，血统来自 Bigtable 的 SSTable 与 Hadoop 的 TFile。本页讲清版本演进的两条硬事实（v2 于 0.92 引入、2.0+ 只能写 v3），以及 v3 的 per-cell Tags 为何是 2.0+ 的分水岭——它同时支撑了 cell 级 TTL、Visibility Labels 与 MOB 引用。数据模型里的列族默认值与文件格式互为表里，见 [Data Model](/docs/CS/DB/HBase/Data_Model.md)。

## HFile Format

HFile 是 LSM 在 HDFS 上的落地文件格式，血统可查：源自 Bigtable 论文的 SSTable 设计与 Hadoop 的 TFile。版本演进里两条硬事实：**v2 于 0.92 引入**（inline blocks）；**2.0+ 只能写 v3，v2 只读不写**，升级时若 `hfile.format.version=2` 会导致 RegionServer 起不来。

v3 的关键增量是 **per-cell Tags**：每个 cell 可以挂任意 tag（cell 级 TTL、visibility labels、MOB 引用都靠它）。格式本身与 [Data Model](/docs/CS/DB/HBase/Data_Model.md) 一节的默认值互为表里：`BLOCKSIZE` 决定数据块粒度与索引开销，块级压缩（`COMPRESSION`）与 KV 前缀编码（`DATA_BLOCK_ENCODING`）是两个正交的层，前者压 value、后者压相邻 key 的重复前缀。排查时可用 `hbase hfile` 把文件内容文本化。

## Links

- [HBase](/docs/CS/DB/HBase/HBase.md)
- [Data Model](/docs/CS/DB/HBase/Data_Model.md)
- [Bigtable](/docs/CS/Distributed/Bigtable.md)
- [LSM Tree](/docs/CS/Algorithms/tree/LSM.md)

## References

1. [Apache HBase Reference Guide](https://hbase.apache.org/book.html)
2. [Bigtable: A Distributed Storage System for Structured Data](https://research.google/pubs/bigtable-a-distributed-storage-system-for-structured-data/)
