## Introduction

TiFlash 是 TiDB 的列存扩展，用来承接 HTAP 场景中的分析型负载。它不是「另一个数据库」，也不是 TiKV 的独立分支，而是与 TiKV 平级的一种存储副本：同一张表可以同时拥有行存副本（TiKV）与列存副本（TiFlash），由 TiDB 根据查询类型自动选择读哪边。

## 定位与节点类型

TiFlash 有两种角色：

- **TiFlash 节点**（`tiflash` store）：专职列存副本，只存列式数据，不参与 TiKV 的 Raft 写多数派（以 Learner 身份存在）。
- **TiFlash compute node**：在 TiFlash 进程内承担 MPP 计算任务的节点，`tiflash` store 本身即包含 compute 能力；管理面上二者由同一进程组提供，运维视角仍表现为一个 TiFlash store。

关键点：**TiFlash 副本与 TiKV 副本是同一份 Raft Group 的成员**。一个 Region 的 Raft Group 里通常有 3 个 TiKV voter，外加若干 TiFlash Learner。Raft log 会照样复制给 Learner，只是 Learner **只应用日志、不参与选举、不投票、不参与多数派确认**。

这带来两个直接后果：

1. **写入性能不受 TiFlash 影响**：TiKV 的写只要多数派 voter 确认即可返回，不用等 TiFlash。TiFlash 是异步追赶的。
2. **读取有一致的进度锚点**：TiFlash 通过 Raft index / applied index 汇报自己的复制进度，TiDB 可以拿到「TiFlash 已应用到哪个 MVCC 版本」，从而保证在 TiFlash 上的读满足 Snapshot Isolation，而不是读到落后的旧版本。

所以「TiFlash 异步复制所以会读到旧数据」是错误说法——复制确实异步，但读路径上有一个显式的一致性检查（Raft index + MVCC 过滤），异步的是复制进度，不是数据正确性。

## DeltaTree：列存组织方式

TiFlash 的存储引擎叫 DeltaTree，与 TiKV 的 RocksDB 是两套完全不同的组织方式：

- **写入路径**：新写入的数据进入内存中的 Delta 层（类 LSM 的小 memtable），按行组织。
- **合并路径**：Delta 层定期 merge 进 Stable 层，Stable 层按列切分、以类似 Parquet 的列块格式落盘，并带 min/max 等索引信息。
- **读路径**：查询同时扫 Stable + Delta，按列读需要的列块，行级过滤在 Stable 的索引与 Delta 的稀疏索引上完成。

与传统「Parquet 离线文件 + 外表查询」的区别在于：DeltaTree 是**在线、可持续写入、支持 MVCC 版本过滤**的列存。分析查询不需要「先导入数仓再查」，改动的数据在秒级内可查。

TiFlash 上建索引（`CREATE INDEX ... USING INVERTED` 或普通索引）会生成加速结构，用来在 Stable 层做更有效的行过滤。

## MPP 查询

TiDB 8.5 的执行器支持把一部分计划下推到 TiFlash 的 MPP 引擎执行。MPP 的核心是 **Exchange 算子**：把数据按 shuffle key 在各 TiFlash 节点间重分布，然后各节点并行计算（典型如 hash join 的 build/probe 两侧、聚合的 partial+final 两阶段）。

触发 MPP 需要满足：

- 表有 TiFlash 副本，且 `SESSION` / 全局变量 `tidb_allow_mpp = ON`（v8.5 默认 ON）。
- 优化器代价模型认为下推 MPP 更优（估算的数据量与 join 大小）。
- 计划里不存在 MPP 不支持的算子。

没有 MPP 时，TiFlash 也可以被普通「表扫描 + 谓词/聚合下推」的方式使用（coprocessor 请求打到 TiFlash store），只是 join 等算子仍回到 TiDB 层做。用 `EXPLAIN ANALYZE` 看执行计划时，Exchange 算子的出现即代表走了 MPP。

## TiDB 如何选择读 TiKV 还是 TiFlash

选择由优化器基于代价模型自动完成，用户可以干预：

- **自动选择**：若查询只涉及 TiKV 副本即可满足，或估算分析代价过高，优化器可能选 TiKV；涉及大表扫描 + 聚合 + join 的分析查询通常选 TiFlash。
- **手动指定**：
  - `SELECT /*+ read_from_storage(tiflash[table_name]) */ ...`：强制走 TiFlash。
  - `SET SESSION tidb_isolation_read_engines = "tidb,tikv"`：把 TiFlash 从候选读引擎中去掉。
- **一致性保证**：走 TiFlash 的读会在 TiFlash 已应用的 MVCC 版本上取快照，保证 SI。

## 与常见认知的差异

- **「TiFlash 是 TiKV 的列存扩展」**：对，但要说清它扩展的是**副本**而非引擎内核——存储格式、执行引擎都是独立的，只是通过同一套 Raft Group 拿到数据。
- **「TiFlash 异步所以读到旧数据」**：见上文，读路径有一致性锚点。
- **「TiFlash 是独立数据库，需要自己同步数据」**：不需要。副本同步由 Raft 自动完成，建副本就是一条 `ALTER TABLE ... SET TIFLASH REPLICA 1`。
- **「MPP 就是分布式 SQL 的全部」**：TiDB 的分布式能力还有 TiKV coprocessor 下推这一层；MPP 是 TiFlash 上的第二层并行，二者叠加。

## Links

- [TiDB 整体架构](/docs/CS/DB/TiDB/Architecture.md)
- [TiKV 存储引擎](/docs/CS/DB/TiDB/TiKV.md)
- [分布式事务](/docs/CS/DB/TiDB/Transaction.md)

## References

- https://docs.pingcap.com/zh/tidb/v8.5/tiflash-overview/
- https://docs.pingcap.com/zh/tidb/v8.5/use-tiflash-mpp-mode/
- https://docs.pingcap.com/zh/tidb/v8.5/tiflash-disaggregated-and-s3/
