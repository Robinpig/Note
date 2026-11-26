## Introduction

复制（Replication）决定数据副本如何放置在集群与多 DC 中，是 Cassandra「无单点、多 DC 容灾」的根基。它与 [Consistency](/docs/CS/DB/Cassandra/Consistency.md) 协同：一致性级别决定一次操作要触及几个副本，复制策略决定这些副本物理在哪。

> 基线：Cassandra 5.0.9。Transient Replication 自 4.0 起提供，但仍是实验性、默认关闭；5.0.9 的拓扑元数据仍由 `TokenMetadata` 等既有组件维护，没有 TCM。

## Replication Factor

**复制因子（RF）** = 每份数据保存的副本数。RF 在 keyspace 级声明，典型生产取 **3**；多 DC 通常为每个 DC 单独声明，例如 `dc1:3, dc2:3`。

RF 可在线调整，但改配置不等于旧数据已经复制到新位置：

- **增加 RF**：新写入按新 preference list 路由；已有数据必须运行 full repair / rebuild，把缺失 range stream 到新 replica。
- **减少 RF**：新写入不再覆盖被移除的 replica；原 replica 上的历史数据需通过 `nodetool cleanup` 或后续 compaction 回收。
- **调整期间**：避免同时做多个拓扑变更，先确认所有节点 `NORMAL`、range movement 完成，再进入下一轮。

## Replication Strategies

### SimpleStrategy

按 token 环顺时针取连续 N 个 replica。仅适合单 DC 测试：扩缩容、节点增减会改变「环上邻居」，导致大量数据需要重分布，且完全无视机架/DC 拓扑。

### NetworkTopologyStrategy

生产标准。按 DC 维度分别指定 RF，并结合 snitch 的 DC/rack 信息放置 replica。5.0.9 的放置算法有几个容易忽略的约束（`NetworkTopologyStrategy.java:115`）：

1. **有效 RF** 是 `min(配置 RF, 该 DC 节点数)`；配置 5 份但只有 3 个节点时，不会凭空产生第 4、5 个副本。
2. 同一节点不能在同一 range 的 replica 列表中出现两次。
3. 先覆盖尽可能多的不同 rack；rack 数不足以填满 RF 时，允许在同一 rack 放多个节点。
4. 节点不足导致有效 RF 缩水时，优先减少 transient replica 数量，而不是破坏 full replica 布局。

因此「RF=3 就一定跨三个 rack」并不成立；只有 DC 内至少三个 rack 时才成立。

## Snitch

Snitch 向 Cassandra 描述「网络拓扑与邻近性」，影响 replica 放置与 coordinator 选近 replica 读：

| Snitch | 说明 |
| --- | --- |
| `SimpleSnitch` | 无视拓扑，仅单 DC 可用 |
| `RackInferringSnitch` | 从 IP octet 推断 DC/rack，少用 |
| `PropertyFileSnitch` | 手工在各节点 `cassandra-topology.properties` 声明 DC/rack |
| `GossipingPropertyFileSnitch`（默认推荐） | 节点本地 `cassandra-rackdc.properties` 声明，并通过 gossip 广播 |
| `Ec2Snitch` / `Ec2MultiRegionSnitch` | AWS 环境按 AZ 推断；multi-region 版支持跨 region |
| `CloudstackSnitch` / `GoogleCloudSnitch` 等 | 对应云厂商 |

snitch 不仅决定「副本在哪」，也影响 dynamic snitch 的延迟排序与 coordinator 的候选 replica 选择。修改 DC/rack 前必须确认 keyspace RF 与新拓扑匹配，否则可能降低实际冗余。

## Multi-Datacenter Placement

NetworkTopologyStrategy 下，每个 DC 独立维持自己的 RF 份副本。写路径会把 mutation 发往各 DC 的相应 replica，但 coordinator 等待哪些 DC 由 CL 决定：

| CL | 等待范围 | 结果 |
| --- | --- | --- |
| `LOCAL_QUORUM` | 仅本地 DC quorum | 本地低延迟；异地是否已落盘不保证 |
| `QUORUM` | 全局 full replica quorum | 可能等待跨 DC ack |
| `EACH_QUORUM` | 每个 DC 的 quorum | 所有 DC 都满足本地 quorum 才成功 |

`LOCAL_QUORUM` 的「不等异地」不是 Cassandra 把远程写放进一个可靠后台队列：远程请求仍会发送，可能成功、失败或延迟，最终靠 hint / repair 收敛。读路径同理，`LOCAL_QUORUM` 避免跨 DC 读延迟。

## Write and Read Routing

- **Preference list**：按 token 顺序排列的 replica 序列，第一个 full replica 是 primary；`ReplicaPlans` 在具体 CL 下生成 contacts、read candidates 与 pending 集合。
- **写**：普通写优先覆盖 full replica 与 pending replica；transient replica 在 full replica 不足以满足 CL 或 speculative write threshold 触发时加入。不是简单地「每个节点都写同样一份」。
- **Pending range**：bootstrap、decommission、move 等拓扑变更期间，新旧 replica 会暂时同时接收写，避免切换瞬间丢数据；写等待数也可能因 pending 增加。
- **读**：coordinator 按 CL、DC 局部性与 dynamic snitch 选择候选；full replica 可返回 data 或 digest，transient replica 返回 transient data。
- **TokenAware driver**：按 token 直连合适 replica 作 coordinator，减少一跳；任意节点仍可作为 coordinator。

## Transient Replication

`ALTER KEYSPACE ... WITH replication = {'class':'NetworkTopologyStrategy','dc1':'3/1'}` 表示 **DC1 总共 3 个 replica，其中 1 个 transient、2 个 full**。

设计目标是「廉价 quorum」：full replica 保存完整数据，transient replica 只保存尚未 incremental repair 的数据；repair 后 transient 数据可丢弃，从而降低存储成本。正常写会尽量避免给 transient 写数据，full replica 不足时才升级写入。

5.0.9 的限制：

- 实验性，需 `transient_replication_enabled: true`，不建议未经验证直接上生产；
- 表必须 `read_repair=NONE`；
- 不支持 monotonic reads、LWT、logged batch、counter、MV keyspace 与 secondary index；
- hint 永不写给 transient replica；
- read repair 不修复 transient replica，读必须至少包含一个 full replica；
- full/transient 角色转换需要 streaming 或 cleanup，不能把 `3/1` 当成普通 RF=4 的简写。

## Failed Node Handling

- **暂不可达**：coordinator 可向 preference list 中下一个 live replica 写入，并在目标符合条件时为其保存 hint。hint 是给原目标的，不是给新目标的。
- **不满足 CL**：如果剩余 live replica 不足以满足 quorum/all，请求返回 `UnavailableException`，不会用「转写成功」伪装满足一致性。
- **永久离开**：`nodetool decommission` 迁移本节点 range 后下线；节点已不可用时用 `removenode`；新节点 bootstrap 从现有 replica streaming 数据。
- **恢复后**：hint replay 只覆盖窗口内暂存写；更早或未记录的差异必须 repair。

## Source Map

| 机制 | 5.0.9 源码落点 |
| --- | --- |
| 有效 RF 与 rack 放置 | `locator/NetworkTopologyStrategy.java:115-225` |
| replica plan 与 live 检查 | `locator/ReplicaPlans.java:98-160` |
| 写 CL 与 pending 计数 | `db/ConsistencyLevel.java:172-191` |
| full / transient 读请求 | `service/reads/AbstractReadExecutor.java:116-185` |
| hint 目标过滤 | `service/StorageProxy.java:2423-2501` |
| RF 增加后 full repair | `doc/modules/cassandra/pages/managing/operating/repair.adoc:104-108` |
| transient 限制与转换 | `doc/modules/cassandra/pages/managing/operating/transientreplication.adoc:74-175` |

## Source-Level Classes

- **复制策略**：`locator.AbstractReplicationStrategy`、`SimpleStrategy`、`NetworkTopologyStrategy`、`LocalStrategy`。
- **副本计划**：`locator.ReplicaPlan` / `ReplicaPlans` 按 CL、RF、拓扑与 pending ranges 构造读写 contacts；`Replica` 区分 full、transient 与 pending。
- **拓扑 / 成员**：5.0.9 使用 `locator.TokenMetadata` 与 `locator.Topology`；`StorageService` 负责 bootstrap / decommission / 拓扑变更。
- **vnode 分配**：`dht.tokenallocator`；3.0+ `ReplicationAwareTokenAllocator` 让 token 分布考虑复制布局。
- **transient**：`ReplicationParams` / `ReplicationFactor` 表达 `3/1`，`NetworkTopologyStrategy` 决定哪些 endpoint 是 full 或 transient。

## Links

- [Cassandra](/docs/CS/DB/Cassandra/Cassandra.md)
- [Data Model](/docs/CS/DB/Cassandra/DataModel.md)
- [Operations](/docs/CS/DB/Cassandra/Operations.md)

## References

- [Cassandra Replication](https://cassandra.apache.org/doc/5.0/cassandra/architecture/dynamo.html)
- [Cassandra Snitch](https://cassandra.apache.org/doc/5.0/cassandra/managing/operating/snitch.html)
- [Cassandra Transient Replication](https://cassandra.apache.org/doc/5.0/cassandra/managing/operating/transientreplication.html)
- [Cassandra Repair](https://cassandra.apache.org/doc/5.0/cassandra/managing/operating/repair.html)
- [Cassandra 5.0.9 Source](https://github.com/apache/cassandra/tree/cassandra-5.0.9)
