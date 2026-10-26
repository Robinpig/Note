# Distributed Storage

## Introduction

传统单机存储（本地磁盘、NFS、SAN/NAS）在容量、可靠性、性能、扩展性与成本上都有天花板：容量有极限、单点故障即丢数据、IO 集中在单机、扩容不能无限加盘、专业设备昂贵。分布式存储把数据**分散到多台服务器**并对外提供统一存储能力，用副本冗余、纠删码（EC）、分布式元数据与分布式调度来消弭这些痛点：

- 某台宕机 → 业务照常（冗余 / 多副本）
- 数据变多 → 加机器就能扩容
- 读写压力大 → 多节点分担

本笔记按**访问接口**把主流方案切成四类（文件系统 / 对象 / 块 / 分布式 KV），再把它们与本库既有笔记对接，最后给出选型决策表与运维要点。

## Classification by Access Interface

### File System

提供"文件 + 目录"语义，是传统 POSIX 文件系统的分布式版本（多为弱化 POSIX）。

- 特点：对大文件顺序读写非常友好；海量小文件表现一般；需要元数据服务（常成性能瓶颈）。
- 代表：HDFS、CephFS、GlusterFS、Lustre。
- 典型场景：大数据平台（Hadoop、Spark）、离线分析、日志归档、大吞吐顺序读写。

### Object Storage

无目录结构，只有 Key（路径）+ Value（对象），走 HTTP REST 接口。

- 特点：S3 协议已成事实标准；天然适合海量小对象；横向扩展极强；非 POSIX，不适合随机写。
- 代表：Amazon S3、[MinIO](/docs/CS/Distributed/MinIO.md)（社区版已停更，社区维护 fork 见 [Silo](/docs/CS/Distributed/Silo.md)）、Ceph RGW、OpenStack Swift。
- 典型场景：图片 / 视频 / 附件 / 静态资源、数据湖（Iceberg / Delta / Hudi，非 Hadoop 架构）、备份归档、云原生 S3 存储。

### Block Storage

对外提供块设备（如一块云盘），其上可再格式化 ext4/xfs。

- 特点：可做快照、克隆、高可用复制；延迟通常比对象 / 文件系统低。
- 代表：Ceph RBD、Longhorn、OpenEBS、Portworx。
- 典型场景：虚拟机磁盘（KVM / OpenStack）、Kubernetes PersistentVolume、对 IO 延迟敏感的数据库（MySQL、PostgreSQL、Elasticsearch）。

### Distributed KV / Database-style

这类系统不是通用存储，但常被当作"分布式数据存储层"使用。

- 代表：Cassandra、TiKV（TiDB 的存储引擎）。
- 特点：去中心化、高可用；Cassandra 适合高写入高并发；TiKV 基于 Raft 强一致、支持分布式事务。
- 典型场景：分布式事务、元数据存储、Session、时序、热点更新数据。

## Relations to Other Topics

分布式存储不是孤立的，它咬合在本库多条主线上，也承接分布式系统的经典论文系统：

- **经典 lineage（本目录）**：[GFS](/docs/CS/Distributed/GFS.md) 是 HDFS 的设计原型——单一 Master + 多 ChunkServer + 追加写，HDFS 几乎逐一对齐；[Haystack](/docs/CS/Distributed/Haystack.md) 是 Facebook 的海量小对象（图片）存储，现代对象存储（[MinIO](/docs/CS/Distributed/MinIO.md) / S3）在"海量小文件高吞吐"这一命题上与之同源。把分类与选型放在本目录，正是因为它们首先是**分布式系统的子领域**。
- **与计算**：[HDFS](/docs/CS/Framework/Hadoop/Hadoop.md) 是 [Hadoop](/docs/CS/Framework/Hadoop/Hadoop.md) / [Spark](/docs/CS/Framework/Spark/Spark.md) / [Flink](/docs/CS/Framework/Flink/Flink.md) 的默认存储底座，数据本地性（data locality）直接决定批 / 流作业性能。
- **与数据库**：[Cassandra](/docs/CS/DB/Cassandra.md) 与 [TiDB / TiKV](/docs/CS/DB/TiDB.md) 既是"存储"也是"数据库"，后者用 Raft 把 KV 与 SQL 层解耦。
- **与容器编排**：[K8s](/docs/CS/Container/Container.md) 的 StatefulSet（MySQL、Kafka 等）依赖块存储提供稳定持久卷，Ceph RBD / Longhorn / OpenEBS 是主流实现。
- **与协调组件**：HDFS HA 依赖 [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)，TiKV 的 PD 依赖 [etcd](/docs/CS/Framework/etcd/README.md) 做元数据与调度——存储集群的"大脑"往往是协调层。

## Selection Guide

| 场景 | 推荐 | 备注 |
| :--- | :--- | :--- |
| 大数据、离线分析 | HDFS / CephFS / S3 + 查询引擎 | 大规模批处理 → HDFS；统一对象 + 块 → Ceph；数据湖（Iceberg/Delta/Hudi）→ S3/[MinIO](/docs/CS/Distributed/MinIO.md) |
| K8s 应用持久化 | Ceph RBD / Longhorn / OpenEBS / Portworx | 数据库须强一致 → Ceph RBD；中小团队 → Longhorn；有企业预算 → Portworx |
| 海量图片 / 视频 / 对象 | [MinIO](/docs/CS/Distributed/MinIO.md) / Ceph RGW / S3 | 自建 S3 → MinIO；已有私有云生态 → Ceph RGW |
| 高并发在线（强一致） | TiKV / TiDB、[CockroachDB](/docs/CS/Distributed/CockroachDB.md) | 分布式事务、元数据、实时系统 |
| 低预算 / 中小团队 | [MinIO](/docs/CS/Distributed/MinIO.md)（对象）+ GlusterFS（文件）+ Longhorn（K8s） | 简单、够用、易运维 |

一句话选型：对象 → [MinIO](/docs/CS/Distributed/MinIO.md) / S3；块 → Ceph RBD / Longhorn；文件 → HDFS（大数据）/ GlusterFS（一般业务）/ CephFS（复杂场景）；数据库式 → TiKV / Cassandra。没有"最好的技术"，只有"最适合业务的技术"。

## Trade-offs and Operations

- **网络优先**：Ceph / HDFS 建议 10Gb / 25Gb 网络；对象存储上万兆收益明显。
- **SSD 做元数据**：Ceph 的 MDS、MON、OSD Journal 用 SSD，性能差异巨大。
- **多副本 vs 纠删码**：副本可靠但成本高（3 副本 = 3 倍存储）；EC 成本低但恢复耗时长。惯例：热数据用副本，冷数据用纠删码。
- **必须监控**：IOPS、延迟、OSD / 节点健康、磁盘故障、网络丢包。
- **定期数据恢复演练**：一次演练相当于十次安全保障。

## Links

- [GFS（HDFS 的设计原型）](/docs/CS/Distributed/GFS.md)
- [Haystack（海量小对象存储）](/docs/CS/Distributed/Haystack.md)
- [Hadoop（HDFS）](/docs/CS/Framework/Hadoop/Hadoop.md)
- [Cassandra](/docs/CS/DB/Cassandra.md)
- [TiDB / TiKV](/docs/CS/DB/TiDB.md)
- [Container（K8s 持久化）](/docs/CS/Container/Container.md)

## References

1. [一文读懂分布式存储：主流技术、适用场景与选型指南](https://cloud.tencent.com/developer/article/2589794)
2. [Ceph Documentation](https://docs.ceph.com/en/latest/)
3. [MinIO Documentation](https://min.io/docs/)
