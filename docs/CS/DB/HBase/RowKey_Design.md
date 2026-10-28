## Introduction

RowKey 是 HBase 唯一的查询主键，也是唯一的分区键——分布是否均匀、前缀扫描是否可用、能否定位到单 Region，三件事全压在这一个字段上。本页讲热点（hotspotting）的成因与四类官方缓解手段（salting / 哈希 / 复合前缀 / 预分裂），以及二级索引的三类补偿方案。它是 [HBase](/docs/CS/DB/HBase/HBase.md) 数据模型之后最该先读的一页。

## RowKey Design

RowKey 是 HBase 唯一的查询主键，也是唯一的分区键，三件事同时压在这一个字段上：分布是否均匀、前缀扫描是否可用、能否定位到单 Region。

**热点（hotspotting）** 是头号故障模式：大量读写集中打到某一个 Region（进而某一个节点），该 Region 成为瓶颈甚至不可用，同时拖垮同机其它 Region。典型成因是**单调递增 RowKey**——用时间戳或自增 ID 打头时，一整批写入的 key 全落在最后一个 Region 上；导入进程还会步调一致地把当前 Region 打满再整体移到下一个，集群里其余节点全程闲置。

官方给出的四类缓解手段：

| 手法 | 做法 | 代价 |
| :--- | :--- | :--- |
| **Salting** | 在 key 前加随机/散列前缀，前缀取值数对应希望打散的 Region 数 | 彻底打乱语义顺序，读时必须显式带上前缀或全扫 N 份，无法前缀扫描 |
| **哈希 / 取反** | 用 `Hash(key)` 或固定长度摘要做前缀（如按天聚合时用「实体 + `Long.MAX_VALUE - ts`」让最新数据排在前面） | 仍是散列分区，牺牲范围查询；与 [分区策略](/docs/CS/Distributed/Partition.md)里哈希分区的取舍同源 |
| **复合前缀** | 把基数高、天然均匀的字段（用户 ID、设备 ID）拼在前面，时间戳放后面 | 需要按查询模式设计，拼错等于把热点搬到另一个字段 |
| **预分裂 presplitting** | 建表时给出显式分裂点或按均匀分布预分裂，空表就有多个 Region | 要求事先知道 key 分布；否则只是把空 Region 摊平 |

其它约束：

- **长度**：RowKey 是 `byte[]`，会被复制进 meta、Bloom filter、每个 KV 的 key。业务上「越短越好」，定长优于变长，能用 `long`/`int` 二进制就别用字符串。
- **不可更新**：改 RowKey 只能「读旧行 → 写新行 → 删旧行」，删掉的行只留 tombstone，要等 major compaction 才真正消失，所以高频改主键的场景本身就不该用 HBase。
- **二级索引**：HBase 自身不提供。补偿办法是三类——① 用 [Phoenix](/docs/CS/DB/HBase/Coprocessor_and_Phoenix.md)（或 Trafodion）在表上建**全局 / 本地索引**，把索引写成另一张 HBase 表；② 自建**异构索引表**，索引表 RowKey 用查询维度、value 存主表 RowKey，写入时双写或用 Coprocessor / [canal](/docs/CS/DB/Middleware/canal.md) 异步同步；③ 把非主键维度倒排到 [Elasticsearch](/docs/CS/Framework/ES/ES.md)，ES 出 RowKey、HBase 取明细。三类都逃不过索引与主数据的一致性维护。

## Links

- [HBase](/docs/CS/DB/HBase/HBase.md)
- [LSM Tree](/docs/CS/Algorithms/tree/LSM.md)
- [Bigtable](/docs/CS/Distributed/Bigtable.md)

## References

1. [Apache HBase Reference Guide](https://hbase.apache.org/book.html)
2. [Apache Phoenix](https://phoenix.apache.org/)
