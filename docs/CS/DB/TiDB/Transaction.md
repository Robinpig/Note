## Introduction

TiDB 的分布式事务建立在 Google BigTable 的 Percolator 模型上：两阶段提交 + 集中式授时（PD 的 TSO）+ MVCC 冲突检测。它解决的核心问题是「一次写入可能落在多个 Region 上，如何保证原子性」。代价同样清晰：2PC 的网络交互、对时间戳服务的依赖、以及事务过大时的内存压力。

本页覆盖 2PC 全流程、乐观与悲观两种模式、隔离级别的真实语义、事务大小限制与 GC。KV 层如何承载锁与多版本见 [TiKV](/docs/CS/DB/TiDB/TiKV.md)。

## Percolator and Two-Phase Commit

一次乐观事务的完整流程（官方口径）：

1. `BEGIN` 时 TiDB 从 PD 取全局递增的 `start_ts`，同时作为本次读的 MVCC 快照版本；
2. 读请求按 start_ts 版本读，写请求先做约束校验（类型、非空等），**校验通过的数据暂存在 TiDB 该事务的私有内存里**——这是事务内存压力的来源；
3. `COMMIT` 开始 2PC：选一个 Key 作为 **Primary**，其余为 Secondary；从 PD 拿所有 Key 的路由；**并发向所有涉及节点发起 prewrite**，TiKV 检查版本冲突并加锁，Secondary 锁里存指向 Primary 的指针；
4. 所有 prewrite 成功后取第二个时间戳 `commit_ts`；
5. 向 Primary 所在节点提交：写 Write 记录（提交或回滚）、清 prewrite 锁；随后异步清理 Secondary 锁。**Primary 的 Write 记录即整个事务的提交事实**——Secondary 锁若因故障残留，GC/后续事务可沿锁中指针找到 Primary 判断该事务是否提交。

锁冲突检测在 **TiKV 层**完成（prewrite 阶段，scheduler 内置内存锁 latch，每 Key hash 到不同 slot），因为 TiDB 节点无状态、互相不可感知。死锁由检测器自动发现，随机终止其中一个事务并返回 MySQL 兼容错误码 1213，事件记入 `INFORMATION_SCHEMA.DEADLOCKS`。

v8.5 默认开启两个降延迟机制：**Async Commit**（`tidb_enable_async_commit`，二阶段异步化）与 **1PC**（`tidb_enable_1pc`，单 Region 事务一阶段提交）——所以「2PC 一定慢」在 v8.5 不成立，单 Region 事务根本没有二阶段。

## Optimistic and Pessimistic Modes

**自 v3.0.8 起，新创建集群默认悲观事务**（从 ≤v3.0.7 升级来的老集群保持原默认值不变）。`BEGIN PESSIMISTIC` / `BEGIN OPTIMISTIC` 优先级高于全局 `tidb_txn_mode`，两种模式可混用。

乐观事务靠提交时冲突检测 + 重试；**自动重试自 v3.0.0 起默认关闭，v8.0.0 起 `tidb_disable_txn_auto_retry` 被正式废弃**，官方理由是重试会破坏隔离级别（重试只重执行写语句、重新取 start_ts）。生产上应改用悲观事务或应用层捕获重试。

悲观事务的关键默认值：等锁超时 `innodb_lock_wait_timeout` 默认 50 秒（超时报 1205）；事务持锁上限 `max-txn-ttl` 默认 1 小时（超时锁可能被清除）；单语句最大重试 256 次。v8.5 默认开启 **pipelined 加锁**（满足条件即通知 TiDB 继续、异步写锁）与 **内存悲观锁**（锁只存 Region leader 内存、不过 Raft，超 `in-memory-instance-size-limit` 100 MiB 回退写盘）。

与 InnoDB 的差异值得记：TiDB 悲观事务**没有 gap locking**，不支持 `SELECT LOCK IN SHARE MODE`（v8.3.0 起可用变量使其加排他锁）；DDL 不阻塞事务但可能导致悲观事务提交报 `Information schema is changed`；`BEGIN` 即取快照（等价 MySQL 的 `WITH CONSISTENT SNAPSHOT`），而 MySQL 是首个普通 SELECT 后才取。

## Isolation Levels

TiDB 的默认且唯一内置级别是 **Snapshot Isolation**，官方为兼容 MySQL 称其为 REPEATABLE READ——**它与 ANSI RR 和 MySQL RR 都不同名同义**：不出现狭义幻读（A3），但不阻止广义幻读（P3），且存在写偏斜（write skew）。与 MySQL RR 的行为差（更新不检验当前版本可见性）靠「默认悲观 + 当前读」弥合：MySQL RR 下能更新成功的场景，TiDB 用默认悲观事务也能成功，用乐观事务则会回滚。

Read Committed 仅悲观事务模式下生效（乐观模式下设置 RC 不生效，仍是 RR）。跨节点事务的启动/提交顺序取决于从 PD 取时间戳的顺序——**全局顺序由 TSO 定义，不是由客户端提交顺序定义**。

### Introduction Limits

v8.5 的硬限制（官方口径）：

| 限制 | 默认值 | 说明 |
| :--- | :--- | :--- |
| 单行大小 | 6 MiB | `txn-entry-size-limit`，最大可调到 120 MiB |
| 单事务总大小 | 100 MiB | `txn-total-size-limit`，最大 1 TB；实际还受服务器剩余内存约束 |
| 单事务语句数 | 5000 | `stmt-count-limit`，仅可重试的乐观事务生效 |
| 单事务 Key 数 | 无限制 | v4.0 起取消旧的 30 万条上限 |
| 单条 Raft 日志 | 8 MiB | `raft-entry-max-size`，TiKV 侧硬限制 |
| 写队列积压 | 100 MiB | `scheduler-pending-write-threshold`，超限返回 Server Is Busy |

「单事务最多 30 万 Key」是 v4.0 之前的老黄历；「prewrite 单 Region 大小上限」在官方文档中**不存在**这个配置项，二手文章常把 `txn-total-size-limit` 误传成它。

## Garbage Collection

GC 清理 MVCC 旧版本与残留锁。机制：

- 一个 TiDB 实例被选为 **GC leader**，默认每 10 分钟一轮；
- safe point = 当前时间 − `tidb_gc_life_time`（默认 10 分钟），且 **safe point 不会超过正在执行事务的 start_ts**——长事务不会被打扰，但会阻塞 GC 推进，`tidb_gc_max_wait_time` 默认 24 小时后强制推进；
- 每轮三步：**Resolve Locks**（清理 safe point 之前的锁，默认 LEGACY 模式由 leader 遍历 Region；PHYSICAL 模式即 Green GC 为实验特性）→ **Delete Ranges**（快速物理删除 DROP TABLE/INDEX 的整区间数据）→ **Do GC**（TiDB 只把 safe point 发给 PD，每个 TiKV 自行扫描自己节点上作为 leader 的 Region，删除每个 Key 不再需要的旧版本，保留 safe point 前最后一次写入）；
- 自 v5.0 起 CENTRAL 模式废弃，Do GC 只跑 DISTRIBUTED；
- 可选 **GC in Compaction Filter**（`gc.enable-compaction-filter`，默认关闭）：让 RocksDB compaction 顺带做 GC，避免单独 GC 的额外读盘，但可能延迟 GC 进度。

「GC 会把活跃事务数据清掉」不成立——safe point 受活跃 start_ts 保护；真正会咬人的是长事务拖住 safe point 导致旧版本堆积、扫描变慢。

## Links

- [TiKV](/docs/CS/DB/TiDB/TiKV.md)
- [PD](/docs/CS/DB/TiDB/PD.md)
- [TiDB Server](/docs/CS/DB/TiDB/TiDB_Server.md)
- [MySQL Transaction](/docs/CS/DB/MySQL/Transaction.md)

## References

- [乐观事务模型](https://docs.pingcap.com/zh/tidb/v8.5/optimistic-transaction/)
- [悲观事务模式](https://docs.pingcap.com/zh/tidb/v8.5/pessimistic-transaction/)
- [事务隔离级别](https://docs.pingcap.com/zh/tidb/v8.5/transaction-isolation-levels/)
- [事务概览](https://docs.pingcap.com/zh/tidb/v8.5/transaction-overview/)
- [GC 机制简介](https://docs.pingcap.com/zh/tidb/v8.5/garbage-collection-overview/)
- [GC 配置](https://docs.pingcap.com/zh/tidb/v8.5/garbage-collection-configuration/)
- [Percolator: Large-Scale Incremental Processing and Change (OSDI 2010)](https://www.usenix.org/legacy/event/osdi10/tech/full_papers/Peng.pdf)
