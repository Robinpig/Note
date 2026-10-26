## Introduction

HBase 的写路径是 LSM 写优化的典型实现：WAL 顺序追加 → MemStore 内存有序 → flush 成 HFile → compaction 收敛。本页覆盖写流程、写侧背压与删除 tombstone 语义、Bulk Load 这条绕开写路径的 TB 级灌数通道，以及 WAL 的多 provider 设计与 RegionServer 崩溃后的 WAL split / replay 恢复。读路径与 compaction 策略分别见 [Read Path](/docs/CS/DB/HBase/Read_Path.md) 与 [Compaction](/docs/CS/DB/HBase/Compaction.md)。

## Write Path and Compaction

写路径（LSM 的写优化本质）：

1. 先顺序追加 **WAL**（HLog，落在 HDFS）保证宕机可回放；
2. 再写入内存中按 key 有序的 **MemStore**，写请求即返回；
3. Region 的 MemStore 达到 `hbase.hregion.memstore.flush.size`（默认 128 MB）后 **flush 成不可变 HFile**；
4. Store 里 HFile 数达到 `hbase.hstore.compactionThreshold`（默认 **3**）触发 **minor compaction**，单次最多合并 `hbase.hstore.compaction.max`（默认 **10**）个文件，扫描批大小 `hbase.hstore.compaction.kv.max` 默认 10；
5. **major compaction** 把一个 Store 的文件合成一个，并清除删除标记与过期版本，默认周期 `hbase.hregion.majorcompaction` = **604800000 ms，即 7 天**（配 `hbase.hregion.majorcompaction.jitter` = 0.50 打散，避免全体同时开跑）。

> [!WARNING]
> 「HBase 默认一天一次 major compaction」是流传很久的旧事实。`hbase.hregion.majorcompaction` 的默认值在 **branch-2.4、branch-2.6、branch-3.0 三处源码里都是 7 天**，要按业务低峰控制节奏就把周期项设为 0 关掉自动触发、改用外部 cron 或 `major_compact` 手工调度。

写侧的背压与保护：

- 同一个 Store 的 HFile 数超过 `hbase.hstore.blockingStoreFiles`（默认 **16**）就**阻塞该 Region 的更新**，直到 compaction 追上来或超过 `hbase.hstore.blockingWaitTime`（默认 90000 ms）后自行解除。写入突然卡住，先看这个。
- MemStore 涨到 `hbase.hregion.memstore.block.multiplier`（默认 **4**）× flush 阈值时同样阻塞更新；全局 MemStore 上限 `hbase.regionserver.global.memstore.size` 默认 **0.4（40% 堆）**，撞到就强制 flush 并阻塞。
- compaction 本身被限速：默认的 `PressureAwareCompactionThroughputController` 在忙时把总吞吐压到 `hbase.hstore.compaction.throughput.lower.bound`（默认 50 MB/s）。
- **删除 = 写 tombstone**，不立即抹除，只在 major compaction 时真正清除。大量删除或大量过期版本会让读路径反复跳过墓碑，因此「先大删再查」的性能塌方是结构性的（与 [Lucene 段合并的删除标记](/docs/CS/Framework/ES/Lucene.md)同源，都是不可变文件 + 后台合并）。
- 批量写入用 **BufferedMutator**（旧 `HTable` 的 `setAutoFlush(false)` + `write buffer`），攒够再一次 RPC；`hbase.client.write.buffer` 是它的默认缓冲大小（2 MB）。
- **WAL 可以按 Mutation 跳过**：`Mutation.setDurability(Durability.SKIP_WAL)`，枚举取值为 `USE_DEFAULT / SKIP_WAL / ASYNC_WAL / SYNC_WAL / FSYNC_WAL`。但**没有「按表关闭 WAL」的开关**，且官方明确警告：除批量导入外关 WAL 就是拿数据换吞吐，RegionServer 崩了这段数据永久丢失。

### Bulk Load

Bulk Load 是把 TB 级数据灌入 HBase 的唯一合理做法（[HBase](/docs/CS/DB/HBase/HBase.md) 的 Consistency 一节已点出它绕开 WAL 与 MemStore）。它分两步，核心是「先用 MapReduce 产出 HBase 原生 HFile，再把文件直接 adopt 进在线集群」，因此**不占用 RegionServer 的写路径、不写 WAL、不进 MemStore**，CPU 与网络开销远低于走客户端 API：

1. **生成 HFile**：用 `HFileOutputFormat2` 跑一个 MapReduce 作业，把源数据写成 HBase 内部存储格式。关键是让每个输出 HFile 落在单个 Region 内——通过 `configureIncrementalLoad()` 基于表的当前 Region 边界自动建好 `TotalOrderPartitioner`（全局有序分区器），reduce 数设为目标表 Region 数；mapper 自己实现，value 可以是 `KeyValue` / `Put` / `Delete`。
2. **导入并 adopt**：`completebulkload` 工具（底层 `LoadIncrementalHFiles`）逐个检查生成的 HFile，定位其所属 Region，联系对应 RegionServer 把文件**移动**进存储目录并加载对外服务。

> [!WARNING]
> prepare 与 complete 之间有延迟、或 bulk load 期间 Region 边界发生变化，`completebulkload` 会把 HFile **按新边界自动切分**再导入——这一步并不高效。所以应缩短「生成」与「导入」之间的间隔，尤其当集群同时在用其它方式写数时。
> 同样因为文件是直接 move 进表目录，BulkLoad **不触发 WAL**，本身不提供崩溃恢复；但数据来自 HDFS 上的 HFile，重跑代价低。导入前同样要保证 `hbase:meta` 健康（见 [Operations](/docs/CS/DB/HBase/Operations.md) 一节）。

`completebulkload` 还能当「孤儿目录收养」工具用：集群因故障丢失对某些 region 目录 / 文件的记账时，只要按 `列族子目录 → HFile` 的结构组织好，把它连同表名传给工具即可把数据接回（meta 健康是前提）。

## WAL and MultiWAL

WAL 有三种 provider：`asyncfs`（默认，日志里能看到 `AsyncFSWALProvider`）、`filesystem`、`multiwal`——最后一个由多个 asyncfs / filesystem 实例组成，用多管道摊薄单个 WAL 的写入串行化。WAL 压缩默认关闭（`hbase.regionserver.wal.enablecompression` 默认 `false`），开启后 tag 压缩随之启用。同一个 RegionServer 的并发写汇入同一条 WAL 管道顺序追加，故障恢复时按 Region 重放，这就是「已确认的写」在 RS 崩溃后仍可见的机制来源（见 [Replication](/docs/CS/DB/HBase/Replication.md) 分册的 Consistency）。

另有一条容易漏的时间线：**2.4.0 为 `hbase:meta` 表引入了异步 WAL 复制**，让 meta 自身的可用性方案与普通表对齐（3.0 延续）。

## RegionServer Failure and WAL Replay

Master 不参与数据读写，但**宕机恢复是 Master 的责任**。RegionServer 进程挂掉（或 ZK 会话超时）后，其 ephemeral znode 消失，Master 的 `ServerCrashProcedure`（**SCP**，基于 procedureV2）接管：

1. **先恢复 meta**：若死掉的 RS 承载 `hbase:meta`，SCP 必须先把它在别处 open 上线，才能开始切任何 WAL——meta 是所有数据位置的权威，没它恢复无从谈起。
2. **WAL split**：死 RS 的 WAL 按 Region 拆成 `recovered.edits` 文件。HBase 2.4+ 默认走 **procedureV2 协调的 split**（HBASE-20610），Master 为每个 WAL 起一个 `SplitWALProcedure`，再派 `SplitWALRemoteProcedure` 随机选一个存活 RS 当 worker 并行切；旧版是 ZK 协调的分布式切分（`hbase.master.distributed.log.splitting`，0.92 起默认开）。切分时把 `/hbase/WALs/<rs>` 目录重命名为 `-splitting`，防止「以为死了但其实还活着在写」的 RS 误写。
3. **重分配 Region**：Region 迁到存活 RS，新宿主 open Region 时发现 `recovered.edits`，把日志**重放进 MemStore**——数据由此复活。

> [!WARNING]
> 受影响的 Region 在「WAL 全部 replay 完」之前**不可用**（offline），所以恢复时间 ≈ split 耗时 + replay 耗时。WAL 是** RegionServer 级**而非 Region 级单位（一台 RS 一个 WAL 实例，所有 Region 共享），理解这点才能判断「恢复慢在切分还是慢在回放」。幂等靠每个 KeyValue 的 **sequence id**：MemStore / HFile 里若已有更大序号，旧条目丢弃，重放不会重复数据。

这层机制是 [Replication](/docs/CS/DB/HBase/Replication.md) 分册里「已确认的写」在 RS 崩溃后仍可见的来源；反过来 `SKIP_WAL` 的写从不进 WAL，死在哪丢在哪，无 replay 可救。

## Links

- [HBase](/docs/CS/DB/HBase/HBase.md)
- [HDFS](/docs/CS/Framework/Hadoop/HDFS.md)
- [LSM Tree](/docs/CS/Algorithms/tree/LSM.md)
- [Operations](/docs/CS/DB/HBase/Operations.md)
- [Replication](/docs/CS/DB/HBase/Replication.md)

## References

1. [Apache HBase Reference Guide](https://hbase.apache.org/book.html)
2. [Apache HBase Bulk Loading](https://hbase.apache.org/docs/architecture/bulk-loading/)
3. [Salesforce Engineering - Evolution of Region Assignment Part 3 (SCP / WAL split)](https://engineering.salesforce.com/evolution-of-region-assignment-in-the-apache-hbase-architecture-part-3-e03b814ae92/)
