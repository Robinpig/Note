## Introduction

Apache Cassandra 是一个**无主（masterless）、宽列（wide-column）分布式数据库**，设计目标是高写入吞吐、多数据中心、无单点故障。它融合了 Amazon Dynamo 的**去中心化最终一致**哲学与 Google BigTable 的**列族数据模型**。

> 本文基线：**Cassandra 5.0（5.0.9，最新 GA；2024-09 GA）**。4.0.x / 4.1.x 仍受支持；6.0 尚处 pre-GA（Accord 跨分区事务 + Auto Repair）。**TCM（CEP-21）已在 5.0 落地**，下文凡涉及版本差异均显式标注。

### Version Baseline

| 版本 | 发布 | 关键特性 |
| --- | --- | --- |
| 4.0 | 2021-07 | 全量测试重写、zero-copy streaming、Audit Logging、backpressure |
| 4.1 | 2022-12 | Guardrails Framework、JDK 17 |
| 5.0 | 2024-09 | SAI、Vector Search、Trie Memtable/SSTable、Unified Compaction Strategy、Dynamic Data Masking、JDK 17 |
| 5.0.9 | 2026-08 | 5.0 最新补丁 |
| 6.0 | pre-GA | Accord 跨分区事务 (CEP-15)、Auto Repair (CEP-37)、Constraints Framework (CEP-42)、JDK 21 + Generational ZGC |

## Masterless Peer-to-Peer

- 集群中**每个节点角色完全相同**：都持有完整 token 环信息，都能接收客户端读写（成为 coordinator），也都存储数据副本。没有 HMaster / NameNode 这类单点。
- 客户端连接任意节点（通常通过驱动器的 TokenAware 负载均衡直连 replica），该节点作为 **coordinator** 按 partition key 的 token 把请求路由到对应的 replica 集合，再按一致性级别（CL）收集响应。
- 故障容忍来自**冗余而非选举**：单个节点乃至整个 DC 宕机，其余节点照常服务。

## Ring, Token and Vnodes

- **Partitioner** 把 partition key 哈希成 token。默认 `Murmur3Partitioner`（128-bit 有符号，范围约 `-2^63 ~ 2^63-1`），另可选 `RandomPartitioner`（弃用）、`ByteOrderedPartitioner`（按字节序，慎用——易热点）。
- 所有 token 构成一个**首尾相接的环**。每个 token 区间（range）对应一份数据的 primary replica。
- **虚拟节点（vnode）**：每个物理节点持有 `num_tokens`（默认 **256**）个随机 token 区间，而非早期的一整段连续 range。好处：
  - 新节点加入时从集群随机窃取多个小 range，负载均衡更平滑，无需手工 `move`；
  - 单节点失效时其负载被**多**个存活节点分摊，恢复更快；
  - 异构硬件可按能力设不同 `num_tokens`。
- Cassandra 3.0 引入更公平的再平衡算法，替代旧版「随机拆分固定数量分区」带来的不公平（见 [Distributed](/docs/CS/DB/Cassandra/Distributed.md)）。

## On-Disk Components

单节点持久化由四件套组成（详见 [Storage Engine](/docs/CS/DB/Cassandra/StorageEngine.md)）：

- **CommitLog**：顺序写 WAL，保证宕机不丢已确认写入。
- **Memtable**：内存中的可变有序结构，写满后 flush 成 SSTable。
- **SSTable**：不可变磁盘文件，多组件（Data/Index/Summary/Filter/Compression/Statistics…）。
- **Caches**：row cache、key cache、counter cache，加速读路径。

## Request Lifecycle (Coordinator)

一次客户端请求在单节点内的代码路径（以 5.0 源码为准），是理解「为什么 Cassandra 这样设计」的钥匙：

1. **协议解析**：native protocol v5 请求经 `org.apache.cassandra.transport` 进入 `org.apache.cassandra.cql3.QueryProcessor`；`QueryProcessor.process` 把 CQL 编译（带编译缓存）成 `cql3.statements.ModificationStatement` / `SelectStatement`，或直接构造 `db.Mutation` / `ReadCommand`。
2. **协调（写）**：`org.apache.cassandra.service.StorageProxy.mutate` 用 `getNaturalEndpoints` 算出副本集合、经 `ReplicaPlan` 封装，把 `Mutation` 发给各 replica，并用 `AbstractWriteResponseHandler`（`WriteResponseHandler` / `DatacenterSyncWriteResponseHandler` / `AnyWriteResponseHandler` 等）按 CL 收 ack。
3. **协调（读）**：`StorageProxy.read` 构造 `SinglePartitionReadCommand` 等发给 replica，由 `ReadCallback`（实现 `AbstractReadResponseHandler`）收响应；当部分 replica 只回 **digest**（摘要）而另一些回全量时，由 `db.ReadResponse` / `DataResolver` 比对摘要、仅在分歧时拉全量——即 digest read。
4. **副本执行**：replica 端 `db.Keyspace.apply`（写）或 `ReadCommand.execute`（读）本地执行，写落 `CommitLog`+`Memtable`、读合并 `Memtable`+`SSTable`（见 [Storage Engine](/docs/CS/DB/Cassandra/StorageEngine.md)）。
5. **节点生命周期 / 配置**：`service.StorageService` 掌管 bootstrap / decommission / 拓扑变更；`config.DatabaseDescriptor` 是 `cassandra.yaml` 的统一门面。
6. **节点间 RPC**：`net.MessagingService` 序列化与投递 `Message`；4.0 重写的 internode 协议（messaging v2）显著降低延迟与堆外碎片。

> 5.0 起集群元数据由 `tcm.ClusterMetadataService` 提供（见 [Distributed](/docs/CS/DB/Cassandra/Distributed.md)），旧 `locator.TokenMetadata` 的拓扑/成员职责被 `tcm.ClusterMetadata` 吸收。

## Cassandra vs HBase

| 维度 | Cassandra | HBase |
| --- | --- | --- |
| 架构 | 无主 P2P，节点对等 | HMaster + RegionServer（有主） |
| 一致性 | 可调：最终一致 ~ 强一致（quorum） | 行级强一致 |
| 多 DC | 内建 multi-DC 复制，可跨 DC 异步 | 依赖 ReplicationSource/外部同步 |
| 依赖 | 自带（仅依赖自身 + 可选 JMX 工具） | 强依赖 HDFS + ZooKeeper |
| 运维复杂度 | 节点对等、线性扩缩 | 组件多、运维更重 |
| 典型场景 | 写多、多地域、AP 容忍 | 强一致、Hadoop 生态内 |

## Links

- [Cassandra](/docs/CS/DB/Cassandra.md)
- [Data Model](/docs/CS/DB/Cassandra/DataModel.md)
- [Consistency](/docs/CS/DB/Cassandra/Consistency.md)
- [Comparison](/docs/CS/DB/Cassandra/Comparison.md)
- [HBase](/docs/CS/DB/HBase.md)

## References

- [Cassandra - A Decentralized Structured Storage System](https://citeseerx.ist.psu.edu/viewdoc/download?doi=10.1.1.161.6751&rep=rep1&type=pdf)
- [Apache Cassandra Architecture (官方文档)](https://cassandra.apache.org/doc/latest/cassandra/architecture/)
