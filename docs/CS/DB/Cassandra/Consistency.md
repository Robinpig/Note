## Introduction

Cassandra 的招牌是**可调一致性（Tunable Consistency）**：每条读写可独立指定一致性级别（CL），在「一致性强度」与「延迟/可用性」之间自由权衡。这是 Dynamo「AP 优先」与 BigTable「强一致」的折中体现。

> 基线：Cassandra 5.0。跨分区轻量事务（LWT/Paxos）在本页；6.0 的 Accord 跨分区事务见文末。

## Consistency Levels

| CL | 含义 | 典型用途 |
| --- | --- | --- |
| `ONE` / `TWO` / `THREE` | 只需 N 个 replica 响应 | 低延迟、可容忍暂时不一致 |
| `QUORUM` | `⌊N/2⌋ + 1` 个 replica | 默认强一致折中 |
| `LOCAL_QUORUM` | 仅本地 DC 的 `⌊N/2⌋+1` | 多 DC 场景避免跨 DC 延迟 |
| `EACH_QUORUM` | 每个 DC 各自 quorum | 写需各 DC 都确认 |
| `ALL` | 全部 replica | 最强一致、最脆（任一宕机即失败） |
| `ANY` | 至少一个节点（含 hint） | 写不丢即可，读可能暂时拿不到 |
| `SERIAL` / `LOCAL_SERIAL` | 走 Paxos 读/写（线性一致） | LWT 条件更新 |
| `NODE_LOCAL` | 仅 coordinator 本地 | 内部/测试 |

## NRW Model

设副本数 `N`、读份数 `R`、写份数 `W`：

- `W + R > N` ⇒ 读集合与写集合必相交 ⇒ **强一致**（读一定能看到最新写）。
- `W + R ≤ N` ⇒ 可能读不到最新写 ⇒ **最终一致**。

经典配置 `N=3, R=W=QUORUM`（quorum = 2）：容忍 1 节点故障仍强一致；若某 replica 暂不可用，quorum 仍能凑齐。

**容错速查（RF=3）**：

| 配置 | 可容忍同时故障 | 备注 |
| --- | --- | --- |
| `ONE/ONE` | 2（写），但读可能旧 | 可用性最高 |
| `QUORUM/QUORUM` | 1 | 强一致常用 |
| `ALL/ALL` | 0 | 最强一致、最脆 |

## Read Repair and Hinted Handoff

即便用 `ONE` 读，Cassandra 也会在后台逐步收敛：

- **Read Repair（前台）**：coordinator 读 quorum 时若发现副本间不一致，立即用最新时间戳（LWW）修复落后的 replica，并把修复结果返回。
- **Read Repair（后台 / speculative）**：以 `read_repair_chance`（旧）或 4.0+ 的 `read_repair` 表参数控制的概率，在后台异步修复。
- **Hinted Handoff**：某 replica 宕机时，coordinator 把发给它的写暂存为 **hint**，待其恢复后递送——避免临时故障造成永久不一致（hint 也有存活窗口与上限，超时则需走 [repair](/docs/CS/DB/Cassandra/Distributed.md)）。

## Anti-Entropy and Digest Reads

- **Digest Read**：coordinator 向 replica 要的是「数据摘要（hash）」而非全量，仅在摘要不一致时才拉全量比对，省网络。
- **Anti-Entropy Repair**：副本间长期分歧（hint 窗口外、磁盘静默错误）只能靠 `nodetool repair`（基于 Merkle 树比对）彻底对齐，是运维必做项。

## Monotonic and Transient

- **Monotonic Reads**：保证「读到新值后不会再读到旧值」，靠 client 端跟踪 `PREFIX` 或驱动保证。
- **Transient Replication（4.0+）**：允许声明「仅在某些 replica 上临时存一份」（如 `rf: 3/1` 表示 3 全副本 + 1 瞬态），瞬态副本只服务 `ONE` 读、不参与 quorum，省存储换可用性。

## Lightweight Transactions (LWT / Paxos)

需要「读-改-写」原子且冲突检测时，用 `IF` 条件 + `SERIAL` CL，走 **Paxos 两阶段**（prepare/promise → accept/propose），实现**行级线性一致 CAS**：

```sql
UPDATE accounts SET balance = balance - 100 WHERE id = ? IF balance >= 100;
```

代价与限制：

- 每个 LWT 需 4 次 round-trip（远慢于普通写），**绝对不要高频使用**。
- 仅保证**单行**原子；跨 partition 仍非事务。
- 5.0 及以前 LWT 基于「每 partition 一个 Paxos 状态」的实现，竞争时会显著退化。

## Accord (6.0, pre-GA)

Cassandra 6.0 引入 **Accord（CEP-15）**——**leaderless、strict-serializable 的跨 partition 线性一致事务**，正常路径一次 WAN 往返，目标是以接近普通写的成本提供跨行 ACID。它**与 TCM 相互独立**，6.0-alpha 默认关闭、按表启用（`CREATE TABLE ... WITH transactional_mode = 'accord'`）。截至 2026 仍 pre-GA，生产应评估风险。

## Source-Level Classes

- **CL 枚举**：`org.apache.cassandra.db.ConsistencyLevel`（含 `ONE/TWO/THREE/QUORUM/LOCAL_QUORUM/EACH_QUORUM/ALL/ANY/SERIAL/LOCAL_SERIAL/NODE_LOCAL`）。
- **写 ack 收集**：`service.AbstractWriteResponseHandler` 抽象基类，具体有 `WriteResponseHandler`（ONE/TWO/THREE/ALL）、`DatacenterSyncWriteResponseHandler`（EACH_QUORUM）、`DatacenterAsyncWriteResponseHandler`、`AnyWriteResponseHandler`（ANY）。`await()` 在达到 CL 要求的 ack 数后放行。
- **读响应 / digest 比对**：`service.AbstractReadResponseHandler` 与 `ReadCallback`（按 CL 选实现）；当部分 replica 回 digest 时由 `db.ReadResponse` / `DataResolver` 比对摘要、分歧再拉全量；`DigestResolver` 专用于「全部只回 digest」的场景。
- **Read Repair**：表参数 `read_repair`（替代旧 `read_repair_chance` 概率）与 `speculative_retry`（`COORDINATOR` / `LOCAL_ONE` / `ALWAYS` / `<N>ms`，在慢 replica 时触发备用副本读）；实现见 `db.ReadCommand` 的 read-repair 路径与 `ReadRepairDiagnostics`。
- **Hinted Handoff**：`hints.HintsService` / `Hint` / `HintWriteBuffer`；hint 写入受 `max_hint_window_in_ms`（默认 3h）限制，超时丢弃并需 repair 兜底。`nodetool truncatehints` 可清 hint。
- **Repair / Merkle**：`repair.RepairRunnable` / `RepairSession` 驱动，逐 token range 用 `MerkleTree.RowHash` 比对；4.0+ 增量 repair 记录已修复边界。
- **LWT / Paxos**：`service.paxos` 包——`PaxosState`（每 partition 持久化 Paxos 状态）、`Prepare` / `Propose` / `Commit` 三阶段消息（实际 4 轮往返）、`CASRequest`。Paxos 改进（CEP-14，4.1）降低了 prepare 风暴。LWT 仍**单 partition**。
- **Accord（6.0, CEP-15）**：`service.accord` 实现 leaderless、strict-serializable、跨多 partition 的通用事务，正常路径一次 WAN 往返；6.0-alpha **默认关闭**、按表启用，不应用于生产。它**并不依赖 TCM**——两者是独立演进的 6.0 特性。

## Links

- [Cassandra](/docs/CS/DB/Cassandra/Cassandra.md)
- [Replication](/docs/CS/DB/Cassandra/Replication.md)
- [Distributed](/docs/CS/DB/Cassandra/Distributed.md)
- [Architecture](/docs/CS/DB/Cassandra/Architecture.md)

## References

- [Cassandra Consistency Levels (官方文档)](https://cassandra.apache.org/doc/latest/cassandra/cql/consistency.html)
- [Accord Transactions (CEP)](https://cassandra.apache.org/doc/latest/cassandra/architecture/accord.html)
