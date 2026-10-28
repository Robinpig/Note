## Introduction

本页合并 HBase 的「跨集群复制」与「一致性 / 事务」两条线：集群复制把 WAL 编辑异步投递到 peer 集群（最终一致、建议串行复制），Region 副本读是集群内共享文件的复制；一致性一侧讲清 HBase 只保证单行原子、CAS 是官方推荐的事务边界、跨行一致性要靠外部框架或迁 TiDB / OceanBase。写路径与 WAL 重放见 [Write Path](/docs/CS/DB/HBase/Write_Path.md)。

## Cluster Replication

跨集群复制把源集群 WAL 中的编辑**异步**投递到 peer 集群，开关在列族级：`REPLICATION_SCOPE`（默认 `0` 关闭，设正整数开启）。它是**最终一致**的，主备之间存在可见性延迟；「写入顺序」在复制场景是正确性问题——官方明确建议开复制就用**串行复制**（HBASE-9465，2.0 之后进入 2.x），保证 Mutation 按提交顺序到达 peer。

典型用途是异地容灾、就近读与双活写入。它和 Region 副本的「Async WAL Replication」不是一回事：后者是**集群内**把主 Region 的写同步给同数据的副本 Region（数据文件共享、无额外存储），前者是**跨集群**的数据分发。

## Consistency and Transactions

- **单行强一致**：同一 RowKey 的读写是原子的，行内有 RegionServer 级锁；跨行/跨分区**没有原生多行事务**，只有跨行原子写（batch / `BufferedMutator`）带来的「逐行原子、整体非原子」语义。
- **CAS**：`checkAndPut` / `checkAndMutate` 提供「读到预期值才写」，是自实现乐观锁与状态机的基础，也是官方推荐的「HBase 上的事务边界」。
- **行级操作的实现套路**：需要跨行一致性时，业界做法是 ① 引外部事务框架（如 Tephra 一类，借助 ZooKeeper/协调器做事务日志与隔离）；② 把多行聚合到一行（用「事务行」存状态再幂等重放）；③ 迁到有 SQL 与跨行事务的引擎（[TiDB](/docs/CS/DB/TiDB/TiDB.md)、[OceanBase](/docs/CS/DB/OceanBase.md)），HBase 只留作明细宽表。
- **Region 副本读**：`REGION_REPLICATION` 默认 **1**（一 Region 一副本）。调大后启用「Async WAL Replication」（HBase 1.1+，本质是集群内复制）：副本 Region 按主 Region 的提交顺序观察写入，数据文件与主副本共享、无额外存储开销，各副本自己维护内存态。代价是副本异步、有可见性延迟；`REGION_MEMSTORE_REPLICATION` 默认 `true`，关掉后副本只回收 flush/bulkload 事件，读到的数据可能比主副本更旧。
- **写侧顺序**：一个 RegionServer 的 WAL 是全局有序的，崩溃恢复按 WAL 重放（见 [Write Path](/docs/CS/DB/HBase/Write_Path.md)），因此「已确认的写」在 RegionServer 故障后仍然可见；反过来 `SKIP_WAL` 就放弃了这个保证。
- **批量导入不要走正常写路径**：BulkLoad 直接在 MapReduce / Spark 侧生成符合表布局的 HFile，再 move 进表并通知 RegionServer 加载（见 [Write Path](/docs/CS/DB/HBase/Write_Path.md)），绕开 WAL 与 MemStore，是 TB 级灌数唯一合理的做法。

## Links

- [HBase](/docs/CS/DB/HBase/HBase.md)
- [Write Path](/docs/CS/DB/HBase/Write_Path.md)
- [Coprocessor and Phoenix](/docs/CS/DB/HBase/Coprocessor_and_Phoenix.md)
- [TiDB](/docs/CS/DB/TiDB/TiDB.md)
- [OceanBase](/docs/CS/DB/OceanBase.md)

## References

1. [Apache HBase Reference Guide](https://hbase.apache.org/book.html)
2. [Apache Phoenix](https://phoenix.apache.org/)
