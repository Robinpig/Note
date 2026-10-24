## Introduction

compaction 是 HBase 读放大、写放大、空间放大三者分配的核心旋钮。本页分两层：①内存侧的 Accordion（In-Memory Compaction，2.0 引入，把合并思想搬进 MemStore）；②磁盘侧的 CompactionPolicy 家族（Exploring 默认、DateTiered、Stripe、FIFO 等）。它与 [Write Path](/docs/CS/DB/HBase/Write_Path.md) 里 `compactionThreshold` / `blockingStoreFiles` 这些触发参数是两套不同的旋钮。

## In Memory Compaction

**Accordion**，2.0 引入：把 LSM 的合并思想搬进 MemStore，数据还在 RAM 时就消除冗余版本与重复，从而降低 flush 频次、写放大和磁盘足迹。它是列族属性 `IN_MEMORY_COMPACTION`，四个取值：

| 取值 | 行为 |
| :--- | :--- |
| `NONE` | 不做内存合并（默认） |
| `BASIC` | 维护 flush 管道到阈值再落盘；不做真合并，但把数据从 `ConcurrentSkipListMap` 挪进更紧凑的内存结构，吞吐受益 |
| `EAGER` | BASIC 之上真正执行内存合并，套用与 HFile 相同的规则清版本/重复/TTL 过期 |
| `ADAPTIVE` | 按数据里重复 cell 的占比自适应选择索引压缩或数据压缩；**实验性** |

系统表的 memstore 官方建议直接设 `BASIC` / `EAGER`。同一条线上的配套变化：2.0 起 MSLAB 的 chunk pool 默认开启（`hbase.hregion.memstore.chunkpool.maxsize` 默认 1.0，此前为 0.0，即 on-heap MemStore 不用 chunk pool）。

## Compaction Policies

minor / major compaction 的「触发与合并哪些文件」由 `CompactionPolicy` 决定，它是 `CompactionPolicy` 抽象类的不同实现，挂在 `hbase.hstore.engine.class` / 列族属性上。默认是 `ExploringCompactionPolicy`（0.96 起），其余几种按数据特征换：

| 策略 | 选取逻辑 | 适用 |
| :--- | :--- | :--- |
| `RatioBasedCompactionPolicy` | 旧默认（0.96 前），按 `ratio`（高峰默认 1.2、低谷 5.0）滑窗选文件 | **已弃用**，仅历史兼容 |
| `ExploringCompactionPolicy` | 遍历所有可能的文件组合，挑「文件数最多，或同数下总大小最小」的最优解 | **默认**，写入密集通用 |
| `DateTieredCompactionPolicy` | HBASE-15181，按写入时间戳分层组织 HFile | 时序 / 短 TTL、按时间区间扫描、热数据偏新；按 RowKey 区间扫描不友好 |
| `StripeCompactionPolicy` | 把大 Region 切成多个 stripe 子区间分别 compact | 大 Region、行键写入不均匀（如时间序列全堆在一个子区间） |
| `FIFOCompactionPolicy` | 只选「所有 cell 都已过期」的文件合并 | 全 TTL 数据、无版本需求，几乎只清过期 |

> [!NOTE]
> `RatioBasedCompactionPolicy` 在 0.98 之前是默认，之后被 `ExploringCompactionPolicy`（它的改进版）取代并标记弃用。非高峰合并更激进靠的是 `hbase.offpeak.start.hour` / `hbase.offpeak.end.hour` 切 `ratio`（高峰 1.2、低谷 5.0），不是换策略。策略选择与写放大 / 读放大直接相关，和 [Write Path](/docs/CS/DB/HBase/Write_Path.md) 里 `compactionThreshold` / `blockingStoreFiles` 等参数是两层不同的旋钮。

## Links

- [HBase](/docs/CS/DB/HBase.md)
- [Write Path](/docs/CS/DB/HBase/Write_Path.md)
- [Read Path](/docs/CS/DB/HBase/Read_Path.md)
- [LSM Tree](/docs/CS/Algorithms/tree/LSM.md)

## References

1. [Apache HBase Reference Guide](https://hbase.apache.org/book.html)
2. [Apache HBase Compaction package (policies)](https://hbase.apache.org/devapidocs/org/apache/hadoop/hbase/regionserver/compactions/package-summary.html)
