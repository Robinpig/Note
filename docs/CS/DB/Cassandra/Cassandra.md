## Introduction

[Apache Cassandra](https://cassandra.apache.org/) 是去中心化的**宽列（wide-column）分布式存储**，源自 Amazon Dynamo（最终一致、P2P）与 Google BigTable（列族数据模型）。为高写入、多数据中心、无单点故障的场景设计。

## Version Notes

| 版本 | 发布 | 关键特性 |
| --- | --- | --- |
| 4.0 | 2021-07 | 全量测试重写、zero-copy streaming、Audit Logging、backpressure |
| 4.1 | 2022-12 | Guardrails Framework、JDK 17 支持 |
| 5.0 | 2024-09 | SAI、Vector Search、Trie Memtable、BTI SSTable、Unified Compaction、Dynamic Data Masking；支持 Java 11/17 |
| 5.0.9 | 2026-08 | 本文源码基线；标准配置仍为 BIG + SkipList + STCS |
| 6.0+ | 另行核实 | TCM、Accord 等后续能力需按对应源码与发布状态单独核实，不属于 5.0.9 基线 |

> 本文基线 **Cassandra 5.0.9**，源码 tag 为 `cassandra-5.0.9`。5.0 引入的 Trie Memtable 与 UCS 不在标准 `cassandra.yaml` 的默认配置中；BTI 也需显式设置全局 `sstable.selected_format: bti`。Transactional Cluster Metadata（TCM）不在 5.0.9 源码中，5.0.9 的 `NEWS.txt` 将其规划到 5.1。

## Architecture and Positioning

Cassandra 的骨架是**无主 P2P**：每个节点角色完全相同，都能接收读写，故障容忍来自冗余而非选举。数据按 partition key 经 Murmur3 哈希落入 token 环，借助 vnode 实现平滑负载均衡与线性扩展；标准 `cassandra.yaml` 的 `num_tokens` 默认是 **16**，不是旧笔记常见的 256。多 DC 容灾是其一等公民能力。与有主的 [HBase](/docs/CS/DB/HBase/HBase.md) 相比，Cassandra 把「去中心 + 多 DC + 易运维」做到极致，代价是放弃跨分区事务与复杂查询。详见 [Comparison](/docs/CS/DB/Cassandra/Comparison.md)。

### Masterless Peer-to-Peer

- 集群中**每个节点角色完全相同**：都持有 token 环信息，都能接收客户端读写（成为 coordinator），也都存储数据副本。没有 HMaster / NameNode 这类单点。
- 客户端连接任意节点（通常通过驱动的 TokenAware 负载均衡直连 replica），该节点作为 **coordinator** 按 partition key 的 token 把请求路由到对应的 replica 集合，再按一致性级别（CL）收集响应。
- 故障容忍来自**冗余而非选举**：单个节点乃至整个 DC 宕机，其余节点能否继续满足请求取决于 RF、CL 与剩余健康副本，而不是「永远可用」。

### Ring, Token and Vnodes

- **Partitioner** 把 partition key 的序列化字节哈希成 token。默认 `Murmur3Partitioner`，内部对 128-bit hash 的首个 64-bit 值做归一化，映射到有符号 64-bit token 空间；另可选 `RandomPartitioner`（弃用）、`ByteOrderedPartitioner`（按字节序，慎用——易热点）。
- 所有 token 构成一个**首尾相接的环**。每个 token 区间（range）对应一份数据的 primary replica。
- **虚拟节点（vnode）**：每个物理节点持有 `num_tokens` 个 token 区间；5.0.9 标准 `cassandra.yaml:42` 的默认值是 **16**。好处：
  - 新节点加入时从集群随机窃取多个小 range，负载均衡更平滑，无需手工 `move`；
  - 单节点失效时其负载被多个存活节点分摊；
  - 异构硬件可按能力设不同 `num_tokens`。
- 3.0 引入的 `ReplicationAwareTokenAllocator` 让 token 分配考虑复制布局，比旧随机分配更公平。详见 [Distributed](/docs/CS/DB/Cassandra/Distributed.md)。

### On-Disk Components

单节点持久化由四件套组成（详见 [Storage Engine](/docs/CS/DB/Cassandra/StorageEngine.md)）：

- **CommitLog**：顺序写 WAL；`periodic` 模式可能先确认写入、后 fsync，不能笼统宣称「任何已确认写入都不会丢」。
- **Memtable**：内存中的可变有序结构，写满后 flush 成 SSTable；标准配置为 `SkipListMemtable`。
- **SSTable**：不可变磁盘文件，标准格式为 BIG；BTI 通过全局 `sstable.selected_format: bti` 显式选择，`cassandra_latest.yaml` 也采用该配置。
- **Caches**：row cache、key cache、counter cache，加速读路径；BTI 不使用 key cache。

### Request Lifecycle (Coordinator)

一次客户端请求在单节点内的代码路径，是理解「为什么 Cassandra 这样设计」的钥匙：

1. **协议解析**：native protocol v5 请求经 `org.apache.cassandra.transport` 进入 `org.apache.cassandra.cql3.QueryProcessor`；编译缓存把 CQL 变成 `ModificationStatement` / `SelectStatement`，最终形成 `Mutation` / `ReadCommand`。
2. **构造副本计划**：`StorageProxy` 根据 partition key、keyspace 复制策略、DC/rack、CL 与 pending ranges 构造 `ReplicaPlan`；full、transient、pending replica 的参与规则不同。
3. **协调写**：`StorageProxy.mutate`（`StorageProxy.java:878`）创建响应处理器并投递 mutation；`AbstractWriteResponseHandler.blockFor`（`:227`）按 CL 等待 ack，失败时在允许的条件下写 hint。
4. **replica 落盘与入内存**：durable write 先在 `CassandraKeyspaceWriteHandler`（`:42`）追加 CommitLog，再由 `ColumnFamilyStore.apply`（`:1467`）选择 memtable 并写入；二者顺序是持久化语义的关键。
5. **协调读**：`StorageProxy.read` 构造 `SinglePartitionReadCommand` 等请求；`AbstractReadExecutor` 把候选请求分成 full-data、transient-data 与 digest，`DigestResolver` 在摘要一致时避免额外数据传输，不一致时再拉全量。
6. **本地读**：`ReadCommand.executeLocally`（`ReadCommand.java:426`）依次执行索引查找、storage query、tombstone purge、row filter 与 limit；候选 SSTable 与 memtable 在本地合并后返回。
7. **节点间 RPC**：`net.MessagingService` 负责 internode 消息投递；4.0 的 messaging v2 改变协议实现，但不等于 5.0 已有 TCM。

### Metadata and Failure Detection

5.0.9 的集群元数据仍由既有组件维护：

- `locator.TokenMetadata` 描述 token → endpoint 与拓扑/成员变化；
- `schema.Schema` / `DistributedSchema` 管理 schema 版本与传播；
- `gms.Gossiper` 交换 endpoint state 与 heartbeat，`FailureDetector` 根据 Phi 值在本节点形成 UP/DOWN 判断；
- bootstrap、decommission、repair 等流程仍经 `StorageService` 与 token metadata 协调。

该 tag 的 `org.apache.cassandra` 下不存在 `tcm.ClusterMetadata`、`ClusterMetadataService`、`PaxosBackedProcessor` 或 `RemoteProcessor`。因此「5.0 已用 TCM 取代 gossip 元数据」是错误结论；版本升级到包含 TCM 的发行线时，应重新核对元数据、滚动升级与回滚约束。

### Cassandra vs HBase

| 维度 | Cassandra | HBase |
| --- | --- | --- |
| 架构 | 无主 P2P，节点对等 | HMaster + RegionServer（有主） |
| 一致性 | 可调：最终一致 ~ quorum 一致；LWT 单分区线性一致 | 行级强一致 |
| 多 DC | 内建 multi-DC 复制，可跨 DC 异步 | 依赖 ReplicationSource/外部同步 |
| 依赖 | 自带（仅依赖自身 + 可选 JMX 工具） | 强依赖 HDFS + ZooKeeper |
| 运维复杂度 | 节点对等、线性扩缩 | 组件多、运维更重 |
| 典型场景 | 写多、多地域、AP 容忍 | 强一致、Hadoop 生态内 |

## Core Mechanisms

- **数据模型**：宽列多维 map，按查询建表，partition key 决定分布、clustering key 决定分区内排序——[Data Model](/docs/CS/DB/Cassandra/DataModel.md)。
- **可调一致性**：每条读写可独立指定 CL，用 NRW 模型在一致性与延迟间权衡；配合 read repair、hinted handoff、LWT(Paxos) 收敛——[Consistency](/docs/CS/DB/Cassandra/Consistency.md)。
- **复制与拓扑**：RF + NetworkTopologyStrategy + snitch 把副本散布到跨机架/DC；多 DC 的等待范围由 `LOCAL_QUORUM` / `EACH_QUORUM` 等 CL 决定，不是天然的「全部异步」——[Replication](/docs/CS/DB/Cassandra/Replication.md)。
- **存储引擎**：LSM 谱系，CommitLog(WAL) → Memtable → SSTable，读路径 LWW 合并 + Bloom 过滤；持久性取决于 `commitlog_sync` 模式——[Storage Engine](/docs/CS/DB/Cassandra/StorageEngine.md)。
- **Compaction**：STCS/LCS/TWCS 各有所长，5.0 的 UCS 提供统一调参模型；标准默认仍是 STCS——[Compaction](/docs/CS/DB/Cassandra/Compaction.md)。
- **分布式机制**：gossip 发现与 Phi-accrual 故障检测、partitioner/token ring/vnode、基于 Merkle 树的 repair、zero-copy streaming；5.0.9 尚无 TCM——[Distributed](/docs/CS/DB/Cassandra/Distributed.md)。

## Interface and Indexing

- **CQL**：类 SQL 但无 join、无跨分区 ACID 事务，必须按查询建表；logged batch 是最终一致的原子交付机制，不是 SQL 事务——[CQL](/docs/CS/DB/Cassandra/CQL.md)。
- **索引**：经典本地二级索引读放大随节点数增长；5.0 的 SAI 支持标量等值/范围/集合包含与向量 ANN，但**不支持 `LIKE`，也不是分词全文索引**；SASI 仍保留为实验性可选实现——[Indexing](/docs/CS/DB/Cassandra/Indexing.md)。

## Operations and Security

- **运维监控**：部署、关键配置、JMX/Prometheus 指标、调优、扩缩容、备份恢复与常见坑——[Operations](/docs/CS/DB/Cassandra/Operations.md)。
- **安全**：认证/授权(RBAC)、TLS、TDE、审计、5.0 动态脱敏与 CIDR 授权——[Security](/docs/CS/DB/Cassandra/Security.md)。

## Source Map

| 机制 | 5.0.9 源码落点 |
| --- | --- |
| token 化与 vnode 默认值 | `dht/Murmur3Partitioner.java:256`、`db/DecoratedKey.java:88-90`、`conf/cassandra.yaml:42` |
| 协调写与副本等待 | `service/StorageProxy.java:878`、`service/AbstractWriteResponseHandler.java:227` |
| CommitLog 与 Memtable | `db/CassandraKeyspaceWriteHandler.java:42`、`db/ColumnFamilyStore.java:1467` |
| 读执行与 digest | `db/ReadCommand.java:426`、`service/reads/AbstractReadExecutor.java:116`、`service/reads/DigestResolver.java:65` |
| 一致性级别与 Paxos | `db/ConsistencyLevel.java:91`、`service/paxos/Paxos.java:840` |
| 拓扑复制 | `locator/NetworkTopologyStrategy.java:115`、`locator/ReplicaPlans.java:98` |
| 故障检测与 repair | `gms/FailureDetector.java:335`、`repair/RepairSession.java:76` |
| TCM 版本边界 | `NEWS.txt:149` |
| SSTable 与 compaction | `io/sstable/format/bti/BtiTableReader.java:223`、`db/compaction/UnifiedCompactionStrategy.java:106` |
| 数据模型与 SAI | `db/marshal/CompositeType.java:509`、`dht/Murmur3Partitioner.java:256`、`index/sai/plan/Expression.java:73` |

## Links

- [Database](/docs/CS/DB/DB.md)

## References

- [Cassandra - A Decentralized Structured Storage System](https://citeseerx.ist.psu.edu/viewdoc/download?doi=10.1.1.161.6751&rep=rep1&type=pdf)
- [Cassandra Architecture Overview](https://cassandra.apache.org/doc/5.0/cassandra/architecture/overview.html)
- [Cassandra Dynamo Architecture](https://cassandra.apache.org/doc/5.0/cassandra/architecture/dynamo.html)
- [Apache Cassandra 5.0 Documentation](https://cassandra.apache.org/doc/5.0/cassandra/)
- [Cassandra 5.0.9 Source](https://github.com/apache/cassandra/tree/cassandra-5.0.9)
