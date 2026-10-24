## Introduction

Region 是 HBase 分布式与负载均衡的单位，它的分裂与合并直接决定集群是否均衡、是否出现碎 Region。本页讲默认 `SteppingSplitPolicy` 的设计意图、七种分裂策略的语义，以及 Normalizer 对过碎 / 过大 Region 的自动收拾。分裂流程的细节（RS 本地完成、子 Region 先开在父节点）见 [Architecture](/docs/CS/DB/HBase/Architecture.md)，前缀切分策略与 [RowKey Design](/docs/CS/DB/HBase/RowKey_Design.md) 配套。

## Region Splitting and Merge

默认分裂策略 `SteppingSplitPolicy` 的源码语义很能说明设计意图：当这个 RegionServer 上该表**只有一个 Region** 时，用 2× MemStore flush 阈值判定分裂，否则退回 `hbase.hregion.max.filesize`（10 GB）——让新表能快速铺开到集群，又不会一下子生成一堆小 Region。配合 `hbase.regionserver.regionSplitLimit`（默认 1000）为 RS 级分裂上限。

`hbase.hregion.max.filesize` 的两种判定方式：任一 Store 超限即分裂，或整个 Region 的文件求和超限（`hbase.hregion.split.overallfiles`，默认 `true`）。策略可换，全部挂在 `hbase.regionserver.regionSplitPolicy` 下：

| 策略 | 语义 |
| :--- | :--- |
| `SteppingSplitPolicy` | **默认**，见上 |
| `ConstantSizeRegionSplitPolicy` | 固定阈值，到点就切，Region 少时切得太早 |
| `IncreasingToUpperBoundRegionSplitPolicy` | 阈值随 RS 上的 Region 数递增，1.x 时代默认 |
| `KeyPrefixRegionSplitPolicy` | 按 RowKey 前缀长度切，保证同前缀的数据不劈进两个 Region——与 RowKey 前缀设计配套 |
| `DelimitedKeyPrefixRegionSplitPolicy` | 在指定分隔符处切，适合「实体:子键」型 key |
| `BusyRegionSplitPolicy` | 按繁忙度切热点 Region，配合热点治理 |
| `DisabledRegionSplitPolicy` | 关闭自动分裂，**且连手工分裂也一并拦下** |

分裂流程见 [Architecture](/docs/CS/DB/HBase/Architecture.md) 一节：RS 本地完成、子 Region 先开在父 Region 所在节点、写回 `hbase:meta` 后才上报 Master。反方向的**在线合并**（`merge_region`）用来收拾预分裂过碎或删除导致的碎 Region，由 RegionNormalizer 自动化（见 [Architecture](/docs/CS/DB/HBase/Architecture.md) 一节）。

## Links

- [HBase](/docs/CS/DB/HBase.md)
- [Architecture](/docs/CS/DB/HBase/Architecture.md)
- [RowKey Design](/docs/CS/DB/HBase/RowKey_Design.md)

## References

1. [Apache HBase Reference Guide](https://hbase.apache.org/book.html)
