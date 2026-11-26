## Introduction

Cassandra 的分布式机制让「无主、自愈、线性扩展」成为可能：节点靠 **gossip** 发现彼此与故障，靠 **partitioner + vnode** 分片，靠 **repair + streaming** 在扩缩容与故障后重新均衡数据。本页覆盖这些横切机制。

> 基线：Cassandra 5.0.9。Zero-copy streaming 自 4.0；Auto Repair 在 6.0 引入并回移到 5.0.8，需两阶段显式启用。**TCM 不在 5.0.9 源码中**，`NEWS.txt:149` 将其规划到 5.1。

## Gossip Protocol

- Gossiper 每 **1000ms** 执行一轮（`Gossiper.java:142`），随机选择少量 peer 交换 endpoint state 的版本摘要，再按需拉取完整状态。
- 交换内容包括 heartbeat 版本、DC/rack、tokens、schema 版本、load 等 application state。
- **UP/DOWN 是本节点判断，不通过 gossip 传播**：gossip 传播 heartbeat 与状态，每个节点仍要等自己能通过网络实际通信后才认为对端可用。
- Seed nodes 只帮助新节点初次发现集群，不参与选主；非 seed 节点之间也互相 gossip，seed 故障不等于集群不可用。
- gossip 是最终收敛的控制面，不是强一致元数据日志；5.0.9 的 schema/topology 仍依赖既有 gossip 与本地元数据组件。

## Failure Detection (Phi-Accrual)

Cassandra 不用固定 ping 超时，而用 **Phi-accrual**：根据历史心跳到达间隔估计「节点已死」的置信度。`phi_convict_threshold` 默认 **8**，超过阈值后通知 listener  convict。

两个重要边界：

- conviction 是**本地事件**，不同节点可能在不同时间认为同一 endpoint DOWN；
- 本地长暂停会抑制判断：`FailureDetector.interpret` 在解释间隔或暂停保护窗口内发现本节点停顿时，会记录 `lastPause` 并暂停标记 DOWN，避免把本地 GC/调度问题误判成全网故障（`FailureDetector.java:335-378`）。

因此 status 里的 DOWN 不等于「所有节点同时达成共识」，也不等于节点已永久离开 ring；decommission/removenode 是另一条显式运维路径。

## Partitioner and Token Ring

- 默认 **Murmur3Partitioner**：先序列化 partition key，再取 Murmur3 hash 的首个 64-bit 并归一化为有符号 token；相同 key 得到稳定 token，不同 key 碰撞时由 raw key bytes 排序打破平局。
- `RandomPartitioner` 使用 MD5，已弃用；`ByteOrderedPartitioner` 按原始字节序，易热点，仅特殊场景。
- token 首尾相接成环，每个 range 由 preference list 中的第一个 full replica 作为 primary。详见 [Architecture](/docs/CS/DB/Cassandra/Cassandra.md?id=ring-token-and-vnodes)。

## Vnodes

- 5.0.9 标准 `num_tokens` 默认是 **16**，不是 256。
- 每个物理节点持有多个随机 token range，降低单节点失效与扩缩容时的负载倾斜。
- 3.0+ `ReplicationAwareTokenAllocator` 在分配时考虑复制布局，比纯随机分配更公平。
- `num_tokens` 不是越大越好：过小易不均，过大会增加 token metadata、repair 与 streaming 开销；异构硬件可按能力差异化配置。

## Repair (Anti-Entropy)

hinted handoff 与 read repair 只能收敛近期、被请求覆盖的分歧；长期宕机恢复、磁盘静默错误、hint 窗口外遗漏等需要 `nodetool repair`。

### Repair Phases

`RepairSession` 的注释与实现把每个 `RepairJob` 分为三步（`RepairSession.java:76-105`）：

1. **Paxos repair**：先完成范围内未结束的 Paxos 操作，避免 LWT 半成品参与后续比较。
2. **Validation**：各 replica 为相同 token range 构建 Merkle tree，协调节点比较树哈希。
3. **Synchronization**：只对存在差异的 range 启动 `SyncTask`，stream 缺失或过期的数据。

Merkle tree 的价值是把「全量逐行比对」变成「先按 range  hash，再只传差异」，但验证阶段仍会读取数据并构建哈希，不是零成本。

### Full and Incremental Repair

- **Incremental repair** 记录已 repaired 的 SSTable 边界，后续只处理 unrepaired 数据；启用后应持续运行，否则未修复集合会重新累积。
- **Full repair** 遍历全部数据，通常在增加 RF、加节点、首次启用 incremental repair 或验证副本一致性时执行。
- **Subrange / parallel repair** 把大表拆成 token 子范围并限流，避免 repair 与业务 IO 互相拖垮。
- **`gc_grace_seconds`** 是墓碑清除保护窗口，不是 repair 调度器；超期未 repair 会增加部分副本已清墓碑、另一副本仍有旧数据的风险。

### Auto Repair (5.0.8+)

Auto Repair 由 6.0 引入并回移到 5.0.8。5.0.8/5.0.9 的启用分两步：

1. 启动前设置 JVM property `-Dcassandra.autorepair.enable=true`，创建所需 schema；
2. 再在 `cassandra.yaml` 的 `auto_repair` 段或通过 JMX 启用调度。

该 JVM property 官方标注为**不可逆**。代码默认调度关闭，`min_repair_interval` 为 **24h**、`sstable_upper_threshold` 为 **50000**（`AutoRepairConfig.java:464-486`）；新集群若要更频繁 incremental repair，应结合数据量与运维目标显式调整，而不是把默认值当成唯一推荐。

## Streaming and Zero-Copy (4.0+)

bootstrap、decommission、rebuild、replace、repair 与 range movement 都通过 streaming 在节点间传 SSTable。4.0 用 Netty 替代旧的同步阻塞模型，并对完整 SSTable 传输提供 zero-copy 路径。

### Eligibility

`CassandraOutgoingFile.computeShouldStreamEntireSSTables`（`:181`）只有在以下条件同时满足时才整文件传输：

- `stream_entire_sstables=true`（5.0.9 代码默认开启）；
- 请求覆盖该 SSTable 的全部 partition；
- 没有 legacy counter shards；
- 不是 pre-4.0 的旧 Bloom filter 格式。

不满足时仍可 streaming，只是退回 partition 级传输。官方 benchmark 曾给出约 **5x** 的整文件传输加速，但实际收益受磁盘、网络、限流与加密影响。

### TLS and Throttling

源码比 YAML 注释更细：

- 无 TLS 且不限流：Netty `FileRegion` 直接发送文件，避免数据进入用户空间；
- 无 TLS 但限流：按 **1 MiB** chunk 发送 `SharedFileRegion`，仍是文件区域零拷贝；
- 有 TLS：`SslHandler` 存在时按 **64 KiB** 读入 `ByteBuffer` 再加密发送，不能视为真正 zero-copy。

`AsyncStreamingOutputPlus.java:147-165` 是上述分支的直接落点。YAML 中「internode encryption 会自动禁用」是旧注释；5.0.9 代码实际会走 TLS 缓冲复制路径。

## Metadata Boundary (5.0.9)

5.0.9 的相关职责仍分布在：

| 职责 | 组件 |
| --- | --- |
| token → endpoint、拓扑、pending ranges | `locator.TokenMetadata` |
| DC/rack 与节点位置 | `locator.Topology` / snitch |
| schema 定义与版本传播 | `schema.Schema` / `DistributedSchema` |
| heartbeat 与 application state | `gms.Gossiper` |
| 本地 liveness 判断 | `gms.FailureDetector` |
| bootstrap / decommission 编排 | `service.StorageService` |

该 tag 下不存在 `tcm.ClusterMetadata`、`ClusterMetadataService`、`PaxosBackedProcessor` 或 `RemoteProcessor`。升级到包含 TCM 的发行线时，必须重新评估元数据兼容、滚动升级与回滚，不能沿用 5.0.9 的运维假设。

## Source Map

| 机制 | 5.0.9 源码落点 |
| --- | --- |
| gossip 周期 | `gms/Gossiper.java:142` |
| Phi 与本地暂停 | `gms/FailureDetector.java:335-378` |
| token 化与碰撞排序 | `dht/Murmur3Partitioner.java:256`、`db/DecoratedKey.java:88-90` |
| repair 三阶段 | `repair/RepairSession.java:76-105` |
| Auto Repair 默认值 | `repair/autorepair/AutoRepairConfig.java:464-486` |
| 整 SSTable 资格 | `db/streaming/CassandraOutgoingFile.java:180-202` |
| TLS / 限流传输 | `net/AsyncStreamingOutputPlus.java:147-257` |

## Source-Level Classes

- **Gossip / failure**：`gms.Gossiper`、`ApplicationState`、`FailureDetector`、`PhiAccrualFailureDetector`。
- **Token / allocation**：`dht.Token`、`Murmur3Partitioner`、`dht.tokenallocator.ReplicationAwareTokenAllocator`。
- **Repair**：`repair.RepairRunnable`、`RepairSession`、`RepairJob`、`ValidationTask`、`SyncTask`；Merkle tree 位于 `repair.consistent` 相关实现。
- **Auto Repair**：`repair.autorepair` 与 `service.AutoRepairService`；历史记录写入 `system_distributed.auto_repair_history`。
- **Streaming**：`streaming.StreamSession`、`StreamingService`、`StreamPlan`、`CassandraOutgoingFile`、`AsyncStreamingOutputPlus`。

## Links

- [Replication](/docs/CS/DB/Cassandra/Replication.md)
- [Compaction](/docs/CS/DB/Cassandra/Compaction.md)
- [Operations](/docs/CS/DB/Cassandra/Operations.md)

## References

- [Cassandra Dynamo Architecture](https://cassandra.apache.org/doc/5.0/cassandra/architecture/dynamo.html)
- [Cassandra Repair](https://cassandra.apache.org/doc/5.0/cassandra/managing/operating/repair.html)
- [Cassandra Auto Repair](https://cassandra.apache.org/doc/5.0/cassandra/managing/operating/auto_repair.html)
- [Cassandra Improved Streaming](https://cassandra.apache.org/doc/5.0/cassandra/architecture/streaming.html)
- [Cassandra 5.0.9 Source](https://github.com/apache/cassandra/tree/cassandra-5.0.9)
