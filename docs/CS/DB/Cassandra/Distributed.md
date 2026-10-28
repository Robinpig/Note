## Introduction

Cassandra 的分布式机制让「无主、自愈、线性扩展」成为可能：节点靠 **gossip** 发现彼此与故障，靠 **partitioner + vnode** 分片，靠 **repair + streaming** 在扩缩容与故障后重新均衡数据。本页覆盖这些横切机制。

> 基线：Cassandra 5.0。Zero-copy streaming 自 4.0；Auto Repair 自 5.0.8 起 opt-in。**TCM（CEP-21）已在 5.0 落地**，改变元数据管理方式；6.0 进一步引入 Accord 跨分区事务。

## Gossip Protocol

- 每节点每秒随机选 1~3 个 peer 交换** gossip digest**（端点状态的摘要），几跳内全集群状态收敛。
- 交换内容包含 **endpoint state**：心跳（heartbeat, 单调递增）、应用状态（DC/rack、token、状态 UP/DOWN、schema 版本等）。
- **Seed nodes**（`cassandra.yaml` 的 `seeds`）仅用于「新节点首次发现集群」，不参与选主；非 seed 节点之间也互相 gossip，seed 故障不影响集群运转。
- 请求可发往任意节点，由该节点按 token 转发（见 [Replication](/docs/CS/DB/Cassandra/Replication.md)）。

## Failure Detection (Phi-Accrual)

Cassandra 不用「ping 超时即判死」的硬阈值，而用 **Φ (phi) 值** 的 accrual 算法：基于历史心跳间隔的分布，动态给出「该节点已死」的置信度。当 `phi > phi_convict_threshold`（默认 8）才标记为 DOWN。好处：在抖动/GC 暂停网络下减少误判（flapping），比固定超时更稳。

## Partitioner and Token Ring

- 默认 **Murmur3Partitioner**（128-bit 有符号哈希，分布均匀、性能好）。`RandomPartitioner`（MD5，弃用）与 `ByteOrderedPartitioner`（按原始字节序，易热点，仅特殊场景）。
- 所有 token 首尾相接成环，每个 token range 对应一份 primary replica。详见 [Architecture](/docs/CS/DB/Cassandra/Architecture.md)。

## Vnodes

- `num_tokens`（默认 **256**）个随机 token 区间/节点，负载天然分散，扩缩容平滑，单节点故障时压力被多节点分摊。3.0 起用更公平的 rebalance 算法替代旧随机拆分。
- 调优：超大集群或异构硬件可上调/下调 `num_tokens`；过小则负载不均、过大则 metadata 与修复开销上升。

## Repair (Anti-Entropy)

hinted handoff 与 read-repair 只能收敛**近期**分歧；磁盘静默错误、长期宕机的副本恢复、墓碑gc_grace 窗口外的数据，必须靠 `nodetool repair`：

- 基于 **Merkle 树** 对 partition 范围做逐段 hash 比对，只传输真正不一致的数据。
- **增量 repair（4.0+ 默认）**：记录已 repair 的边界，避免每次全量，大幅降低开销。
- **Subrange / 并行 repair**：大表应分片、限流、错峰跑，避免打爆集群。
- 必须**在 `gc_grace_seconds` 内定期 repair**，否则删除数据会复活（zombie）。
- **Auto Repair（5.0.8+）**：可配置自动调度 repair，减少人工遗漏（opt-in 功能）。

## Streaming and Zero-Copy (4.0+)

数据在 bootstrap、decommission、rebuild、repair、拓扑变更时通过 **streaming** 在节点间传输。4.0 对「整 SSTable」引入 **zero-copy streaming** 路径：直接传输文件而非反序列化→再序列化，官方称可快约 **5 倍**，对大集群扩缩容、故障恢复时间影响巨大。

## TCM (Transactional Cluster Metadata, 5.0, CEP-21)

5.0 用 **Transactional Cluster Metadata (TCM, CEP-21)** 取代「每个节点各自通过 gossip 维护 schema/topology」的最终一致模型。核心是把集群元数据变成一份**不可变、全局有序、带 epoch 的日志**：

- `org.apache.cassandra.tcm.ClusterMetadata`：不可变数据对象，聚合 `schema`（`DistributedSchema`）、`directory`（成员目录）、`tokenMap`、`placements`（`DataPlacements`，即 (keyspace, token range) → replica 集合映射）、`lockedRanges`、`inProgressSequences`（bootstrap/decommission 等分阶段计划）。
- `ClusterMetadataService`：CMS（Cluster Metadata Service，少数节点组成）的门面；CMS 成员本地走 `PaxosBackedProcessor`，其它节点走 `RemoteProcessor` 提交变更；`o.a.c.tcm.log.LocalLog` 把复制来的日志条目按序应用到本地 `ClusterMetadata`。
- **epoch**：每个元数据版本对应一个单调递增计数器，唯一标识该版本，便于读写路径检测分歧（`CoordinatorBehindException` + 日志回补 `FetchPeerLog` / `FetchCMSLog`）。
- Gossip **并未消失**：仍负责 liveness（`FailureDetector` 不变）与瞬时状态（load、rpc readiness），但不再传播所有权/成员/schema 版本。

> 6.0 在 TCM 之上进一步引入 **Accord 跨分区事务（CEP-15）** 与 **Auto Repair（CEP-37）**；TCM 本身是 5.0 的能力。

## Source-Level Classes

- **Gossip**：`gms.Gossiper`（端点状态交换）、`GossipDigestSynMessage` / `GossipDigestAckMessage` 等消息、`ApplicationState`（承载 DC/rack/token/schema 版本/load 等）。`FailureDetector` / `PhiAccrualFailureDetector` 实现 phi 累计故障检测（`phi_convict_threshold` 默认 8）。
- **Token / 拓扑**：`dht.Token`（抽象，Murmur3Partitioner 用 128-bit 变体）、`Murmur3Partitioner` / `RandomPartitioner` / `ByteOrderedPartitioner`；`dht.tokenallocator` 做 vnode 分配（3.0+ `ReplicationAwareTokenAllocator` 取代旧 `RandomTokenAllocator`，分布更均匀、避免热点）。
- **Repair**：`repair.RepairRunnable` / `RepairSession` / `RepairJob` 驱动；Merkle 树 `repair.consistent` + `MerkleTree.RowHash` 逐 range 比对；增量 repair（4.0+）记录已修复边界避免全量。Auto Repair（CEP-37，5.0.8+）把调度移入数据库（`cassandra.autorepair.enable` 一次性开关 + 配置/JMX）。
- **Streaming**：`streaming.StreamSession` / `StreamingService` / `StreamPlan`；4.0 的 **zero-copy streaming**（整 SSTable 文件直传而非反序列化）官方称提速约 5x。`nodetool rebuild` / `bootstrap` / `decommission` 都走它。

## Links

- [Cassandra](/docs/CS/DB/Cassandra/Cassandra.md)
- [Architecture](/docs/CS/DB/Cassandra/Architecture.md)
- [Replication](/docs/CS/DB/Cassandra/Replication.md)
- [Consistency](/docs/CS/DB/Cassandra/Consistency.md)

## References

- [Cassandra Gossip / Failure Detection (官方文档)](https://cassandra.apache.org/doc/latest/cassandra/architecture/cluster_metadata.html)
- [Cassandra Repair (官方文档)](https://cassandra.apache.org/doc/latest/cassandra/operations/repair.html)
