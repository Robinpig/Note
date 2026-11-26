## Introduction

Cassandra 的招牌是**可调一致性（Tunable Consistency）**：每条读写可独立指定一致性级别（CL），在「一致性强度」与「延迟/可用性」之间自由权衡。这是 Dynamo「AP 优先」与 BigTable「强一致」的折中体现。

> 基线：Cassandra 5.0.9。普通读写提供可调一致性；`IF` 条件写走单 partition Paxos LWT。5.0.9 没有 Accord，也没有跨 partition ACID 事务。

## Consistency Levels

| CL | 5.0.9 语义 | 典型用途 |
| --- | --- | --- |
| `ONE` / `TWO` / `THREE` | 等待指定数量的 replica ack；写路径可把 pending replica 计入 | 低延迟、可容忍暂时不一致 |
| `QUORUM` | 全部 full replica 的 `allReplicas / 2 + 1` | 单 DC 或全局 quorum 折中 |
| `LOCAL_QUORUM` | coordinator 所在 DC 的 `allReplicas / 2 + 1` | 多 DC 低延迟本地一致 |
| `EACH_QUORUM` | 每个 DC 分别达到 local quorum，写还需覆盖 pending 调整 | 写要求每个 DC 都确认 |
| `ALL` | 等待复制因子要求的全部 replica | 最强可用性约束，任一不足即失败 |
| `ANY` | 写可由本地存储的 hint 满足，不要求正常 replica ack | 极高写可用性；不是普通数据确认 |
| `SERIAL` / `LOCAL_SERIAL` | Paxos consensus quorum，供 LWT 的 SERIAL 读/写 | 单 partition 条件更新 |
| `NODE_LOCAL` | 仅 coordinator 本地，不用于普通跨副本语义 | 内部/测试 |

`ConsistencyLevel.quorumFor`（`:91`）与 `localQuorumFor`（`:96`）直接给出公式；`EACH_QUORUM` 在写路径还会按 pending replica 调整每 DC 的等待数。`ANY` 由 `AnyWriteResponseHandler` 处理，hint 只说明写被某个协调节点接受，不能马上从 replica 读到。

## NRW Model

设静态 full replica 数为 `N`，成功读覆盖 `R` 个，成功写覆盖 `W` 个：

- `W + R > N` ⇒ 两个集合必相交 ⇒ 在**同一 DC/复制域、无 pending/transient 特殊规则、写确实成功**的前提下，读能看到该次写入的最新值。
- `W + R ≤ N` ⇒ 读可能不覆盖写成功的 replica ⇒ 只能保证最终收敛。

经典配置 `N=3, R=W=QUORUM`（quorum = 2）：允许一个 replica 不可用仍可满足 quorum。但 NRW 不是无条件定理：

- `LOCAL_QUORUM` 只与同一 DC 的读写构成交集，不能据此推出跨 DC 可见性；
- pending range 会临时扩大写等待集合，transient replica 又有独立的 full/transient 数据规则；
- 失败写可能只落在少数 replica，`read_repair=BLOCKING` 的单调 quorum 读正是为处理这种情况；
- quorum 一致不是 serializable：并发写仍可能产生可接受但不满足实时顺序的结果，严格 CAS 要用 LWT。

## Read Repair and Speculative Retry

这两个机制经常被混为一谈，实际上解决的问题不同：

| 机制 | 触发 | 行为 |
| --- | --- | --- |
| **Read repair** | 参与读的 replica 返回不同版本 | 用 LWW 结果修复落后 replica |
| **Speculative retry** | 某个 replica 响应慢，可能超时 | 向额外 replica 发重复读，先到者帮助满足 CL |
| **Hinted handoff** | 写目标 replica 不可达 | coordinator 暂存 hint，目标恢复后投递 |

4.0+ 的表参数 `read_repair` 只有 `BLOCKING`（默认）与 `NONE`，不是概率：

- `BLOCKING`：读发现分歧时等待修复写达到 CL，提供 monotonic quorum reads；但修复只覆盖 `SELECT` 读到的粒度，可能破坏比写入更细的分区级原子可见性。
- `NONE`：coordinator 仍合并响应，但不发送修复 mutation；保留分区级写原子可见性，不提供 monotonic quorum reads。

`speculative_retry` 默认是 `99p`（`TableParams.java:366`），与 `read_repair` 正交。`EACH_QUORUM` 或 `NeverSpeculativeRetryPolicy` 会禁用 speculative retry（`AbstractReadExecutor.java:202`），避免重复请求干扰每 DC 响应计数。

## Digest Reads and Data Reconciliation

一次单分区读的初始请求被拆成三类（`AbstractReadExecutor.java:178`）：

- 少量 full replica 返回**全量 data**；
- 其余 full replica 返回 **digest**；
- transient replica 返回 transient data，不能只发 digest。

`DigestResolver.responsesMatch`（`:105`）比较 full replica 的摘要；一致时直接使用已有 data response，省掉额外网络传输。若 transient replica 的数据仍含未合并内容，即使 full replica 摘要一致，也要用 `DataResolver` 再 reconcile（`DigestResolver.java:77`）。digest 是传输优化，不是新的一致性级别。

## Hinted Handoff

hint 是 coordinator 为暂时不可达的目标 replica 暂存的 mutation，不是 replica 已经接受写入。5.0.9 默认：

- `max_hint_window: 3h`；
- hint 默认开启，超过窗口或每目标大小上限时拒绝；
- transient replica 永不写 hint；
- 自身、已退出 ring 的 endpoint、禁用 DC 等目标也不会写 hint。

因此 `ANY` 或 `ONE` 成功不等于所有目标都有数据。hint 过期、节点永久离开、磁盘损坏等情况最终都要靠 anti-entropy repair 收敛。

## Monotonic Reads

`read_repair=BLOCKING` 让成功的 quorum 读在修复完成后返回，从而在 quorum 读序列中避免「先读到新值、后读到旧值」。它依赖 quorum 交集与修复语义，不是客户端缓存前缀，也不是跨任意 CL 的全局实时顺序保证。`read_repair=NONE` 或 transient replication 不提供这套保证。

## Transient Replication

`rf: 3/1` 表示**总共 3 个 replica，其中 1 个 transient**，不是 3 个 full 再加 1 个 transient。transient replica 只保存尚未 incremental repair 的数据，目标是降低存储成本，同时保留更大的复制组。

该特性在 5.0.9 仍是实验性、默认关闭，要求 `read_repair=NONE`，且不支持 monotonic reads、LWT、logged batch、counter、MV keyspace 与 secondary index。详细放置与限制见 [Replication](/docs/CS/DB/Cassandra/Replication.md)。

## Lightweight Transactions (LWT / Paxos)

需要单 partition 的线性一致 compare-and-set 时，用 `IF` 条件与 `SERIAL` / `LOCAL_SERIAL`：

```sql
UPDATE accounts SET balance = balance - 100 WHERE id = ? IF balance >= 100;
```

Paxos 通过 prepare/promise、propose/accept 与 commit/read 完成竞争仲裁，并把每 partition 的 ballot 与 proposal 状态持久化在 system keyspace。LWT 的原子范围是**一个 partition**，可以包含该分区内多行修改，但不是跨 partition 事务。

### Paxos Variants and Round Trips

5.0.9 的 `paxos_variant` 默认仍是 `v1`，但 YAML 推荐升级到 `v2`：

| variant | 写 RT | 读 RT | 线性保证 |
| --- | --- | --- | --- |
| `v1`（默认） | 4 | 3 | 完整 legacy 语义 |
| `v1_without_linearizable_reads_or_rejected_writes` | 4 | 2 | 牺牲 read/read 与被拒绝写的部分线性保证 |
| `v2`（推荐） | 2 | 1 或 2 | 保留完整线性语义 |
| `v2_without_linearizable_reads` | 2 | 1 | 牺牲 read/read 线性保证 |
| `v2_without_linearizable_reads_or_rejected_writes` | 2 | 1 | 进一步牺牲被拒绝写语义 |

所以「每个 LWT 固定四轮往返」只适用于默认 `v1` 写。`v2` 在 prepare 已能提供 linearizable read 时可直接返回，否则提交一个 empty proposal 后再返回（`Paxos.java:858`）。

### Cost and Failure Modes

- 高竞争会不断产生更高 ballot、retry 与超时，吞吐显著退化；
- LWT 比普通写有更多持久化状态与网络往返，不应作为普通更新路径；
- `SERIAL` 只接受单 partition 查询；跨 partition 要拆成应用层协议或等待后续版本事务能力；
- transient replication 不支持 LWT。

## Consistency Failure Matrix

| 现象 | 根因 | 处理 |
| --- | --- | --- |
| `UnavailableException` | 健康 replica 不足以满足 CL | 检查 RF、DC 分布、DOWN 节点与 CL |
| `ReadTimeoutException` | replica 响应慢或 digest/data 不一致修复慢 | 看慢查询、tombstone、compaction、speculative retry |
| 读到旧值后消失 | 失败写只落少数 replica，且 `read_repair=NONE` | 改 `BLOCKING` 或 repair，并重试写 |
| `ANY` 成功但读不到 | 只写入 hint，目标尚未投递 | 等待 hint replay，超过窗口则 repair |
| LWT 高延迟 | ballot 竞争、Paxos 状态热点、`v1` 往返 | 降低竞争、评估 `v2`、按 partition 拆热 key |

## Source Map

| 机制 | 5.0.9 源码落点 |
| --- | --- |
| quorum / local quorum / each quorum | `db/ConsistencyLevel.java:91-191` |
| 写等待与 hint | `service/AbstractWriteResponseHandler.java:227`、`service/StorageProxy.java:2423` |
| 读请求拆分 | `service/reads/AbstractReadExecutor.java:116-218` |
| digest 与 transient reconcile | `service/reads/DigestResolver.java:65-139` |
| 默认 retry / read repair | `schema/TableParams.java:354-376` |
| read repair 语义 | `doc/modules/cassandra/pages/managing/operating/read_repair.adoc:23-71` |
| Paxos variant | `conf/cassandra.yaml:1575-1602`、`service/paxos/Paxos.java:840-904` |

## Links

- [Cassandra](/docs/CS/DB/Cassandra/Cassandra.md)
- [Distributed](/docs/CS/DB/Cassandra/Distributed.md)
- [CQL](/docs/CS/DB/Cassandra/CQL.md)
- [Storage Engine](/docs/CS/DB/Cassandra/StorageEngine.md)

## References

- [Cassandra Consistency Levels](https://cassandra.apache.org/doc/5.0/cassandra/developing/cql/dml.html)
- [Cassandra Read Repair](https://cassandra.apache.org/doc/5.0/cassandra/managing/operating/read_repair.html)
- [Cassandra Transient Replication](https://cassandra.apache.org/doc/5.0/cassandra/managing/operating/transientreplication.html)
- [Cassandra 5.0.9 Source](https://github.com/apache/cassandra/tree/cassandra-5.0.9)
