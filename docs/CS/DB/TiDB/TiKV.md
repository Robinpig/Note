## Introduction

TiKV 是 TiDB 的行存引擎：对外是一个分布式事务型 KV 存储，对内是「RocksDB 单机引擎 + multi-raft-group 复制 + MVCC + Coprocessor」的分层结构。官方文档反复强调的一个反直觉点是：**TiKV 不是「每个 Region 一个 RocksDB」**——同一节点所有 Region 的数据不加区分地存在同一个 RocksDB 实例（kvdb）里，Raft 日志在另一个实例（raftdb），这样不同 Region 的随机写才能合并成一次顺序 I/O。

本页从数据分片（Region）讲到单机引擎（RocksDB/Titan）与 MVCC 落地。事务如何在 KV 之上叠加一致性见 [Transaction](/docs/CS/DB/TiDB/Transaction.md)，调度见 [PD](/docs/CS/DB/TiDB/PD.md)。TiKV 与单机 RocksDB 的关系也可对照本库 [RocksDB](/docs/CS/DB/RocksDB/RocksDB.md) 笔记。

## Region

数据按 Key Range 切成左闭右开区间 `[StartKey, EndKey)`，即一个 Region；每个 Region 多个副本构成 Raft Group，其中一个 Leader 提供读写。v8.5 默认值：

| 参数 | 默认值 | 说明 |
| :--- | :--- | :--- |
| Region 大小 | 256 MiB | v8.4.0 起从 96 MiB 上调 |
| 分裂阈值 | 384 MiB | `region-max-size` = split-size × 3/2 |
| 合并阈值 | 54 MiB / 540000 keys | v8.4.0 起从 20 MiB / 200000 上调 |
| 副本数 | 3 | 1 Leader + 2 Follower |

注意单位坑：tikv-overview 页写「256 MB」，配置项与其它页面写 `256MiB`，以配置项为准。Region 调小的收益是扫描并行度与调度粒度，代价是 Raft 心跳与调度元信息开销——百万级 Region 场景有专门的最佳实践页。

## Raft Replication

TiKV 参考 Spanner 的 multi-raft-group：每个 Region 独立跑一组 Raft。写请求只能在 Leader 进入，**多数副本落盘后才向客户端返回成功**（3 副本时至少 2 个）。数据写入必须过 Raft 层接口，而不是直接写 RocksDB。

副本调度通过 Learner 过渡：PD 先在目标节点加 Learner（复制数据但不计入多数派），追上后提升为 Follower，再移除旧副本；Leader 迁移则多一次 Leader Transfer 让新 Follower 主动当选。PD 侧 `enable-joint-consensus` 默认开启，用 Joint Consensus 做副本变更。

Raftstore 内部节拍（v8.5 配置默认值）：基础 tick 1s、心跳 2 ticks（约 2s）、选举超时 10 ticks（约 10s）、开启 prevote；store/apply 线程池各 2，store-io-pool-size 1；`hibernate-regions` 默认开启（空闲 Region 不驱动 Raft 状态机，大幅降低心跳开销）；snapshot 相关有独立的生成/应用线程池与 GC 超时（4h）。**旧源码走读文章里「心跳 1s / 选举 5s」的口径对 v8.5 已过时**，调排查超时类问题要对配置项而不是记忆。

## RocksDB

每个 TiKV 实例两个 RocksDB 实例：

- **raftdb**：存 Raft 日志（一个 defaultcf）；
- **kvdb**：存用户数据与 MVCC，四个 ColumnFamily——`raft`（Region 元信息，极少）、`lock`（悲观锁与 prewrite 锁，正常少于 1GB，异常增大说明大量事务悬挂）、`write`（真实数据 + MVCC 的 start_ts/commit_ts）、`default`（超过 255 字节的大 value）。

内存侧关键默认值：BlockCache 默认取系统内存 45%（分 CF 口径 25%+15%+2%+2%=44%，不建议超 60%）；每 CF 单 MemTable 128 MiB、最多 5 个（超限阻塞前台写入）；后台 compaction/flush 线程池默认 8，CPU≤8 时取 CPU 数减一。写延迟突增时先看 Grafana RocksDB KV 面板的 WriteStall Reason——L0 文件过多会把 `level0-slowdown-writes-trigger`（默认 20）打满。空间放大方面，层间倍数默认 10，即 90% 数据在最后一层，理论空间放大不超过 1.11。

v8.5.0 起 TiKV 引入 **MVCC 内存引擎（IME）**：把最新版本的 MVCC 数据缓存在内存中，降低点查延迟，同时显著改善大量小事务场景下的写放大——这是 8.5 相对 8.1 最值得关注的存储侧变化。

## Titan

Titan 是 RocksDB 的插件形态单机引擎，把大 value 从 LSM-tree 分离到 BlobFile 单独存储，以降低写放大。要点：

- **v7.6.0 起已是 TiDB 默认存储引擎**——小 value 仍直接存 RocksDB，所以不存在「要不要开 Titan」的问题，只有 `min-blob-size` 阈值怎么配；
- 官方建议：写与点查为主的负载 `min-blob-size = 1KB`；有大量扫描的负载至少 16KB；
- 代价是空间（推荐按 RocksDB 占用的两倍预留）与范围查询（顺序性差，实测回退 40% 到数倍，**是性能回退而非不可用**）；
- v7.6.0 起默认压缩算法从 lz4 改为 zstd；GC 走 BlobFile 重写，可选 Level Merge 让 compaction 顺带处理。

## MVCC

MVCC 通过在 Key 后追加版本号实现：同一 Key 的多个版本大版本在前，通过 `SeekPrefix(Key_Version)` 定位。实际落盘的是 `key + commit_ts`——更新与删除都是写新 key，旧版本由 GC 周期性物理删除（见 [Transaction](/docs/CS/DB/TiDB/Transaction.md)）。TiKV 对外提供的隔离级别是 Snapshot Isolation，官方为兼容 MySQL 称其为 REPEATABLE READ——这个名字与 ANSI RR、MySQL RR 都不同名同义，见 [Transaction](/docs/CS/DB/TiDB/Transaction.md) 的隔离级别一节。

统计信息也存在 TiKV（优化器 auto-analyze 的输入），加上 `m_` 前缀的表元信息——「TiKV 只存用户数据」同样是常见误解。

## Links

- [TiDB Architecture](/docs/CS/DB/TiDB/Architecture.md)
- [TiDB Transaction](/docs/CS/DB/TiDB/Transaction.md)
- [PD](/docs/CS/DB/TiDB/PD.md)
- [TiFlash](/docs/CS/DB/TiDB/TiFlash.md)
- [RocksDB](/docs/CS/DB/RocksDB/RocksDB.md)

## References

- [TiKV 简介](https://docs.pingcap.com/zh/tidb/v8.5/tikv-overview/)
- [TiDB 存储](https://docs.pingcap.com/zh/tidb/v8.5/tidb-storage/)
- [RocksDB 简介](https://docs.pingcap.com/zh/tidb/v8.5/rocksdb-overview/)
- [Titan 简介](https://docs.pingcap.com/zh/tidb/v8.5/titan-overview/)
- [TiKV 配置文件](https://docs.pingcap.com/zh/tidb/v8.5/tikv-configuration-file/)
- [大规模 Region 集群调优最佳实践](https://docs.pingcap.com/zh/tidb/v8.5/massive-regions-best-practices)
