## Introduction

复制（Replication）决定数据副本如何放置在集群与多 DC 中，是 Cassandra「无单点、多 DC 容灾」的根基。它与 [Consistency](/docs/CS/DB/Cassandra/Consistency.md) 协同：一致性级别决定一次操作要触及几个副本，复制策略决定这些副本物理在哪。

> 基线：Cassandra 5.0。Transient Replication 自 4.0 起可用。

## Replication Factor

**复制因子（RF）** = 每份数据保存的副本数。RF 在 keyspace 级声明，典型生产取 **3**（每 DC 各 3）。RF 可在 `ALTER KEYSPACE` 时在线调整，但**只影响新写入**，旧数据需靠 repair/ compaction 逐步达到新 RF。

## Replication Strategies

- **SimpleStrategy**：按 token 环顺时针取连续 N 个 replica。仅适合单 DC 测试——扩缩容、节点增减会改变「环上邻居」，导致大量数据需要重分布，且完全无视机架/DC 拓扑。
- **NetworkTopologyStrategy（生产标准）**：按 DC 维度分别指定 RF（如 `dc1:3, dc2:3`），并借助 snitch 把同一 partition 的多个 replica 尽量分散到不同**机架**。这样单机架故障至多损失一个副本，跨 DC 容灾也天然成立。

## Snitch

Snitch 向 Cassandra 描述「网络拓扑与邻近性」，影响 replica 放置与 coordinator 选近 replica 读：

| Snitch | 说明 |
| --- | --- |
| `SimpleSnitch` | 无视拓扑，仅单 DC 可用 |
| `RackInferringSnitch` | 从 IP  octet 推断 DC/rack（10.x.y.z），少用 |
| `PropertyFileSnitch` | 手工在各节点 `cassandra-topology.properties` 声明 DC/rack |
| `GossipingPropertyFileSnitch`（默认推荐） | 节点本地 `cassandra-rackdc.properties` 声明，并通过 gossip 广播，无需中心文件 |
| `Ec2Snitch` / `Ec2MultiRegionSnitch` | AWS 环境按 AZ 推断；multi-region 版支持跨 region 通信 |
| `CloudstackSnitch` / `GoogleCloudSnitch` 等 | 对应云厂商 |

## Multi-Datacenter Placement

NetworkTopologyStrategy 下，每个 DC 独立维持自己的 RF 份副本。写路径（见 [Storage Engine](/docs/CS/DB/Cassandra/StorageEngine.md)）把写发往**所有 DC** 的相应 replica，但 coordinator 通常**只等本地 DC 的 quorum** 就返回（用 `LOCAL_QUORUM`），跨 DC 同步在后台完成——因此本地写入不受跨 DC 链路延迟影响，又能异步获得异地冗余。读同理：`LOCAL_QUORUM` 避免跨 DC 读延迟。

## Write / Read Routing

- **写**：coordinator 计算 partition 的 **preference list**（按 token 顺序的 replica 序列），把写发往所有 replica，按 CL 收集 ack。第一个全副本（full replica）负责把写「转发」给下游瞬态/后续 replica。
- **读**：coordinator 从 replica 中按 CL 选一批（优先本地、低延迟），发 digest/数据请求，做 LWW 合并与 read-repair（见 [Consistency](/docs/CS/DB/Cassandra/Consistency.md)）。
- **客户端 TokenAware**：4.x 驱动支持按 token 直连对应 replica 作 coordinator，省一跳网络。

## Transient Replication (4.0+)

`ALTER KEYSPACE ... WITH replication = {'class':'NetworkTopologyStrategy','dc1': '3/1'}` 表示 3 个全副本 + 1 个**瞬态**副本。瞬态副本只服务于 `ONE` 读、不参与 quorum 计算，宕机也不影响 `QUORUM` 可用性，用更少的存储换更高可用性。限制：瞬态副本不能位于全副本所在节点、不能与 full 混用某些操作。

## Failed Node Handling

- 副本暂不可达：coordinator 改向 preference list 中下一个 replica 写入，并为其生成 **hint**（见 [Consistency](/docs/CS/DB/Cassandra/Consistency.md)）。
- 节点永久离开：通过 `nodetool decommission` / `removenode` 将其 range 迁移走；新节点 `bootstrap` 时从现有 replica **流式**拷贝数据（4.0+ 的 zero-copy streaming 见 [Distributed](/docs/CS/DB/Cassandra/Distributed.md)）。

## Source-Level Classes

- **复制策略**：`locator.AbstractReplicationStrategy` 抽象基类，`SimpleStrategy` / `NetworkTopologyStrategy` / `LocalStrategy`（系统 keyspace）是实现；`calculateNaturalEndpoints(token)` 给出某 token 的 replica 序列。
- **ReplicaPlan**：`locator.ReplicaPlan` / `ReplicaPlans` 是 3.0+ 引入的「为一次具体操作构造副本集合 + pending 副本」门面——它结合 CL、RF、拓扑与 `pending ranges`（扩缩容/拓扑变更时临时放大的副本），决定 coordinator 把请求发给谁；`StorageProxy.getReplicaPlanFor*` 系列据此路由。
- **拓扑 / 成员**：5.0 前元数据在 `locator.TokenMetadata`（含 `getNaturalEndpoints`、`getEndpointWithToken`）；5.0 起被 `tcm.ClusterMetadata.placements`（`DataPlacements`，即 (keyspace, token range) → replica 集合映射）吸收，拓扑变更走 TCM 的 `InProgressSequences`（见 [Distributed](/docs/CS/DB/Cassandra/Distributed.md)）。
- **Snitch**：`locator.AbstractNetworkTopologySnitch` 基类，`SimpleSnitch` / `RackInferringSnitch` / `PropertyFileSnitch` / `GossipingPropertyFileSnitch`（默认）/ `Ec2Snitch` / `Ec2MultiRegionSnitch` / `CloudstackSnitch` / `GoogleCloudSnitch`；决定「近 replica 优先」与机架感知。
- **vnode 分配**：`num_tokens` 经 `dht.tokenallocator` 包分配。3.0 起 `ReplicationAwareTokenAllocator` 取代旧 `RandomTokenAllocator`，使 token 分布更均匀、避免热点；vnode 的「随机多区间」天然支持异构硬件差异化 `num_tokens`。
- **Transient 副本**：`locator.Replica` 区分 `full` 与 `transient()`；`ReplicationParams` 携带 `rf:3/1` 这类「全副本 + 瞬态」声明，`NetworkTopologyStrategy` 据此把瞬态副本只放在不持有全副本的节点。

## Links

- [Cassandra](/docs/CS/DB/Cassandra/Cassandra.md)
- [Consistency](/docs/CS/DB/Cassandra/Consistency.md)
- [Distributed](/docs/CS/DB/Cassandra/Distributed.md)
- [Storage Engine](/docs/CS/DB/Cassandra/StorageEngine.md)

## References

- [Cassandra Replication (官方文档)](https://cassandra.apache.org/doc/latest/cassandra/architecture/replication.html)
- [Snitch (官方文档)](https://cassandra.apache.org/doc/latest/cassandra/architecture/snitch.html)
