# Ceph

## Introduction

Ceph 是 Sage A. Weil 等人在 2006 年（OSDI）提出的**统一分布式存储系统**，目标是用单一集群同时提供**块、文件、对象**三种访问接口，且能线性扩展到上千节点、无单点瓶颈。核心创新是 **CRUSH** 数据放置算法与 **RADOS** 对象存储底座，使客户端能直接计算数据位置、无需查询中心元数据服务。它是 [Distributed Storage](/docs/CS/Distributed/Distributed_Storage.md) 枢纽按访问接口分类时最典型的"一套架构、三种接口"实现。

## Architecture

Ceph 集群由四类守护进程组成：

- **Monitor（ceph-mon）**：维护集群的成员与状态映射（cluster map），使用 Paxos 类共识保证一致；是集群的"大脑"，只存小量元数据，不处理数据 IO。
- **Manager（ceph-mgr）**：提供监控指标、管理接口与插件（如 dashboard、balancer）。
- **OSD（ceph-osd）**：Object Storage Daemon，实际存储对象、处理数据复制、恢复与再平衡；每个 OSD 管理一块磁盘。
- **MDS（ceph-mds）**：仅在 **CephFS（文件系统）** 场景需要，管理文件系统的元数据（目录树），文件数据仍存于 RADOS。

核心层 **RADOS（Reliable Autonomic Distributed Object Store）** 负责对象的可靠存储、复制与自愈，是上面对接三种接口的底座。

## CRUSH

**CRUSH（Controlled Replication Under Scalable Hashing）** 用伪随机、可计算的哈希把对象映射到 OSD 集合：客户端 / OSD 只需 cluster map + CRUSH 规则就能算出对象位置，**无需查中心元数据**。集群扩缩容时，CRUSH 只迁移受影响的数据（基于权重与故障域），避免全局重平衡。

## Three Interfaces

| 接口 | 组件 | 语义 | 典型用途 |
| --- | --- | --- | --- |
| 块（Block） | **RBD** | 暴露块设备，可格式化 ext4 / xfs，支持快照 / 克隆 | 虚拟机镜像、数据库卷、K8s 持久卷 |
| 文件（File） | **CephFS** | POSIX 兼容的分布式文件系统，经 MDS 管元数据 | 共享文件系统、HPC |
| 对象（Object） | **RGW（RADOS Gateway）** | 兼容 S3 / Swift 的 REST 对象存储 | 数据湖、备份归档、AI 训练数据 |

## Relation to Other Topics

- 与 Distributed Storage：Ceph 是"一套架构三种接口"的典范，正好对应存储枢纽按**访问接口**切分的文件 / 对象 / 块三类。
- 与 HDFS：HDFS 只做文件、为批处理高吞吐设计；Ceph 统一三接口、更通用，但元数据（MDS）与一致性模型不同。
- 与 K8s：Container 的持久卷可用 RBD / CSI 对接 Ceph。
- CRUSH 控制的副本放置配合 OSD 的 primary-copy 复制，是 Replica 的工程范例。

## Links

- [Distributed Storage](/docs/CS/Distributed/Distributed_Storage.md)
- [HDFS / Hadoop](/docs/CS/Framework/Hadoop/Hadoop.md)
- [Container（K8s 持久化）](/docs/CS/Container/Container.md)
- [Replica](/docs/CS/Distributed/Replica.md)
- [GFS](/docs/CS/Distributed/GFS.md)

## References

- Ceph: A Scalable, High-Performance Distributed Storage System (Weil et al., OSDI 2006)
