## Introduction

HBase 2.x 起 `hbck` 退化成只读诊断，真正的修复移交独立的 HBCK2 operator 工具集；快照是零拷贝的在线备份 / 克隆机制。本页讲清修复前的 meta 健康检查顺序与快照的一致性边界——快照只捕获 flush 之后的 HFile 集合，MemStore 里未 flush 的数据不在其中。修复动作依赖 [Architecture](/docs/CS/DB/HBase/Architecture.md) 里的 `hbase:meta`，写路径与 WAL 见 [Write Path](/docs/CS/DB/HBase/Write_Path.md)。

## Operations and Repair Tools

- **HBCK1 只读化**：自 2.0 起 `hbck` 是只读诊断工具，它读不懂 hbase2 的内部状态，修复必须换 **HBCK2**（独立发布的 operator 工具集）。
- **HBCK Report**：Master UI 上的不一致报告自 2.0.6 / 2.1.6 / 2.2.1 起可用，定位孤儿目录等状态。
- 修复动作前先跑 CatalogJanitor（shell `catalogjanitor_run`）确认 `hbase:meta` 本身健康——meta 不健康时一切「修复」都是在放大损坏。

### Snapshot

`snapshot` 是 HBase 的**在线、零拷贝**备份 / 克隆机制：对表打快照只记录「当前有哪些 HFile」的元数据，不复制数据、不阻塞读写；克隆表（`clone_snapshot`）更是直接复用底层 HFile、秒级建出一张新表。导出用 `ExportSnapshot` 把快照数据搬到别的集群 / HDFS，不影响线上。恢复（restore）则把表回滚到快照点。

> [!WARNING]
> 快照本身不保证跨 RegionServer 崩溃的一致性语义——它捕获的是 **flush 之后的 HFile 集合**，MemStore 里未 flush 的数据不在快照内。需要时间点一致的全量备份，仍要结合 WAL / replication，或接受「快照 = 最后一次 flush 之后」的语义。

## Links

- [HBase](/docs/CS/DB/HBase.md)
- [Architecture](/docs/CS/DB/HBase/Architecture.md)
- [Write Path](/docs/CS/DB/HBase/Write_Path.md)
- [Security](/docs/CS/DB/HBase/Security.md)

## References

1. [Apache HBase Reference Guide](https://hbase.apache.org/book.html)
2. [Apache HBase Operator Tools - HBCK2](https://github.com/apache/hbase-operator-tools)
