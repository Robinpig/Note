## Introduction

[Apache Cassandra](https://cassandra.apache.org/) 是去中心化的**宽列（wide-column）分布式存储**，源自 Amazon Dynamo（最终一致、P2P）与 Google BigTable（列族数据模型）。为高写入、多数据中心、无单点故障的场景设计。

## Data Model

- **Keyspace → Table（Column Family）→ Partition → Row → Cell（name/value/timestamp）**。
- **Partition Key**：决定数据落在哪个节点（用 `token(partition_key)` 一致性哈希）；**Clustering Key**：分区内排序。
- 宽行：同一 partition key 下可有海量动态列，适合时序/物化视图。

## Tunable Consistency

- 读写可分别指定 `ONE/QUORUM/LOCAL_QUORUM/ALL` 等级别。
- **NRW 模型**：N 副本数，R 读份数，W 写份数；`W+R > N` 保证强一致，`W+R ≤ N` 为最终一致。典型 `R=W=QUORUM, N=3` → 容忍 1 节点故障。

## Write / Read Path

- **写入**：CommitLog（WAL）→ MemTable → 满后 flush 成 **SSTable**；后台 compaction（STCS/LCS/TWCS）合并。
- **读取**：读 MemTable + 多个 SSTable，按 **timestamp 最后写入胜出（LWW）** 合并；用 Bloom Filter / Row Cache / Key Cache 加速。

## Distributed Mechanism

- **Gossip**：节点间定期交换状态，维护集群拓扑与故障探测（failure detector）。
- **Snitch**：感知网络拓扑，把副本放不同机架/DC。
- **Partitioner**：Murmur3Partitioner（默认）做 token 环；虚拟节点（vnode）均衡负载。
- **Thread Model**：Netty + epoll 事件循环，OptionalSslHandler、连接限流（Connection limiter）、Flusher 批量刷盘。

## Links

- [Netty](/docs/CS/Framework/Netty/Netty.md)
- [DataBases](/docs/CS/DB/DB.md)
- [HBase](/docs/CS/DB/HBase.md)

## References

- [Cassandra - A Decentralized Structured Storage System](https://citeseerx.ist.psu.edu/viewdoc/download?doi=10.1.1.161.6751&rep=rep1&type=pdf)
