## Introduction

本篇拆解 ES 的分布式协调层：一次集群状态更新如何经过批量、发布、持久化与应用，以及 21+ 个分片分配决策器如何决定「哪个分片放哪个节点」。

**版本基线：Elasticsearch 9.5.5**。下文 `server/...` 路径相对源码根（tag `v9.5.5`），可逐条反查。

> [!IMPORTANT]
> **先打破四个直觉**：① 集群状态不是存 `data/cluster-state` 目录——是每个 data path 下的 **`_state` Lucene 索引**；② `TaskBatcher`、`ClusterMetadataPersister` 在 9.x 都已不存在（分别换成 `MasterService.BatchingTaskQueue`、`PersistedClusterStateService`）；③ `gateway.expected_nodes`/`recover_after_nodes` 已移除，现行是 `*_data_nodes`；④ failed allocation **没有指数退避**——是固定延迟 + 失败 5 次闸断。

## 集群状态发布的四级流水线

master 节点上任何元数据变更（建索引、分片分配、节点加入）都走同一条路：

```
MasterService 提交任务 → BatchingTaskQueue 批量合并 → executeAndPublishBatch
 → Coordinator.publish → Publication.start → 各 follower 确认 → commit → master apply
```

### 1. 批量提交

`MasterService.BatchingTaskQueue`（`server/.../cluster/service/MasterService.java:1844`）取代了 7.x 的 `TaskBatcher`：同一队列的任务在 master 繁忙时合并成一次 cluster state 更新（`createTaskQueue` 注释，`:1725-1738`）；提交即触发执行（`:1906-1908`：`queueSize.getAndIncrement() == 0` 时启动 processor）。

### 2. 发布（publish）

`Coordinator.publish`（`server/.../cluster/coordination/Coordinator.java:1666-1778`）前置校验：非 LEADER 或 term 不符抛 `NotMasterException`（`:1673`）、已有 publication 在进行则拒绝（`:1688`）、写入 `coordinationState.handleClientValue`（`:1725`）、最后 `publication.start(followersChecker.getFaultyNodes())`（`:1758`）。

`Publication.start`（`server/.../cluster/coordination/Publication.java:58-66`）向所有 master-first 目标并发发 publish 请求；传输优先发 diff、失败回落全量（`PublicationTransportHandler.java:64-70,335-336`，`newState.diff(previousState)`）。`cluster.publish.timeout` 默认 **30s**（`Coordinator.java:130-136`）。

### 3. 法定人数与提交

`onPossibleCommitFailure`（`Publication.java:145-170`）检查未失败节点是否构成 quorum，不足则 `FailedToCommitClusterStateException`——**这是防脑裂的最后闸门**：少数派分区无法提交集群状态。quorum 判定 `2*voted > size`（`CoordinationMetadata.VotingConfiguration.hasQuorum`，`:326-334`）。

### 4. apply

follower 与 master 都在 `onCompletion` 里应用新状态：`clusterApplier.onNewClusterState(...)`（`Coordinator.java:2113`），随后才向客户端 ack（`:2019-2021`）。**先 apply 后 ack** 保证客户端看到成功时状态已生效。

## 持久化：每个 data path 一个 Lucene 索引

`PersistedClusterStateService`（`server/.../gateway/PersistedClusterStateService.java:117-145`，类注释 "Stores cluster metadata in a bare Lucene index (per data path)"）：

- 写入位置 `<data path>/_state`（`MetadataStateFormat.STATE_DIR_NAME = "_state"`，`server/.../gateway/MetadataStateFormat.java:61`）；
- 写入策略（`GatewayMetaState.java:616-642`）：**term 变化写全量、同 term 增量写**（`writeFullStateAndCommit` / `writeIncrementalStateAndCommit`）；
- follower 侧在 `CoordinationState.handlePublishRequest` 就落盘（`CoordinationState.java:405`），master 在 apply 前落盘——任一端掉电重启后都能从 `_state` 恢复 last accepted state；
- 分页写 `cluster_state.document_page_size` 默认 1MB、慢写告警 `gateway.slow_write_logging_threshold` 默认 10s。

> [!WARNING]
> `gateway.expected_nodes` / `gateway.recover_after_nodes` **已移除**（全仓零命中）。9.x 只有 `gateway.expected_data_nodes`（默认 -1）、`gateway.recover_after_data_nodes`（默认 -1）、`gateway.recover_after_time`（默认 0，设了 expected_data_nodes 而未显式给则 5m）——`GatewayService.java:47-108`。写「expected_nodes 控制集群启动等待」的资料是 7.x 以前的。

## 故障检测：改名过的两个 checker

| 设置 | 默认 | 定义处 |
| ---- | ---- | ---- |
| `cluster.fault_detection.follower_check.interval` | 1s | `server/.../cluster/coordination/FollowersChecker.java:72-77` |
| `cluster.fault_detection.follower_check.timeout` | 10s | `:80-85` |
| `cluster.fault_detection.follower_check.retry_count` | 3 | `:88-93` |
| `cluster.fault_detection.leader_check.interval` | 1s | `LeaderChecker.java:66-71` |
| `cluster.fault_detection.leader_check.timeout` | 10s | `:74-79` |
| `cluster.fault_detection.leader_check.retry_count` | 3 | `:82-87` |

旧名 `cluster.fault_detection.follower_checks`/`leader_checks`、`ClusterFaultDetectionConfiguration` 类均不存在。机制：follower 每秒 ping master，10s 超时重试 3 次即认定 master 失效并发起选举；master 侧反向检查各 follower 存活。

## join 与 voting config

- `cluster.initial_master_nodes` 引导：`ClusterBootstrapService.java:242-255` 把「已发现节点 id」与「未满足需求的占位 id」（`{bootstrap-placeholder}-` 前缀，`:61`）合成初始 voting config；触发条件是「发现节点数 × 2 > 需求数」（`:198`）；
- **自动收缩**（`Reconfigurator.java:130-145`）：`minimumConfigEnforcedSize = autoShrink ? (nonRetiredConfigSize < 3 ? 1 : 3) : nonRetiredConfigSize`，`targetSize = max(roundDownToOdd(存活 master 数), minimumConfigEnforcedSize)`，新配置无存活 quorum 则保持不动。即「≥3 个 master 节点、最多 1 个不可用仍可运作」是公式推论而非显式常量；
- `cluster.max_voting_config_exclusions` 默认 10；手工排除节点用 `POST/DELETE /_cluster/voting_config_exclusions`（`RestAddVotingConfigExclusionAction.java:39`、`RestClearVotingConfigExclusionsAction.java:31`）。

## 分片分配：决策器清单

分配决策 = `AllocationService.reroute` 跑一遍全部 decider（每个返回 YES/NO/throttle），注册表在 `ClusterModule.createAllocationDeciders`（`server/.../cluster/ClusterModule.java:485-516`）。9.5.5 server 侧 **21 个** + x-pack 1 个：

| Decider | 闸什么 | 关键配置（默认） |
| ---- | ---- | ---- |
| `MaxRetryAllocationDecider` | 失败次数超限不再尝试 | `index.allocation.max_retries`（5） |
| `ResizeAllocationDecider` | shrink/split 目标须紧邻源 primary | — |
| `ReplicaAfterPrimaryActiveAllocationDecider` | primary 未 active 不分配副本 | — |
| `RebalanceOnlyWhenActiveAllocationDecider` | 复制组未全 active 不 rebalance | — |
| `ClusterRebalanceAllocationDecider` | 集群级 rebalance 开关 | `cluster.routing.allocation.allow_rebalance`（条件默认 always） |
| `ConcurrentRebalanceAllocationDecider` | 并发 rebalance 数 | `cluster_concurrent_rebalance`（2，-1 无限）；frozen 单独计数 |
| `EnableAllocationDecider` | 总开关 | `cluster.routing.allocation.enable` 等（ALL） |
| `IndexVersionAllocationDecider` | 索引版本兼容 | — |
| `NodeVersionAllocationDecider` | ES 版本兼容 | — |
| `SnapshotInProgressAllocationDecider` | 快照中分片不动 | — |
| `RestoreInProgressAllocationDecider` | 恢复失败不再分配 | — |
| `NodeShutdownAllocationDecider` | 关机（remove）节点迁出；restart 可留 | — |
| `WriteLoadConstraintDecider` | 按目标节点写线程池使用率决策 | `WriteLoadConstraintSettings` |
| `NodeReplacementAllocationDecider` | 迁往 replacement 节点 | — |
| `FilterAllocationDecider` | require/include/exclude | `cluster.routing.allocation.{require,include,exclude}.*` |
| `SameShardAllocationDecider` | 同分片不同副本不落同机 | `same_shard.host`（false） |
| `DiskThresholdDecider` | 磁盘水位 | `index.routing.allocation.disk.watermark.ignore`（false） |
| `ThrottlingAllocationDecider` | 每节点并发 recovery | 见下表 |
| `ShardsLimitAllocationDecider` | 每节点分片数上限 | `total_shards_per_node`（-1 无限） |
| `AwarenessAllocationDecider` | 机架/区域感知 | `awareness.attributes`（空）、`awareness.force.*`（空） |
| `IndexBalanceAllocationDecider` | 单索引均衡约束 | `IndexBalanceConstraintSettings` |
| `DataTierAllocationDecider`（**x-pack**） | 冷热分层强制迁移 | `_tier_preference` |

recovery 限流默认值（`ThrottlingAllocationDecider.java:48-78`）：`node_concurrent_recoveries` **2**、`node_initial_primaries_recoveries` **4**、`node_concurrent_incoming/outgoing_recoveries` 跟随前者。**`node_initial_replicas_recoveries` 不存在**（零命中）。

## 磁盘水位：85/90/95

`DiskThresholdSettings.java`（`cluster.routing.allocation.disk.*`）：

| 水位 | 默认 | 动作 |
| ---- | ---- | ---- |
| low | **85%**（max_headroom 200GB） | 不再往该节点分配新分片 |
| high | **90%**（max_headroom 150GB） | 开始迁出该节点分片 |
| flood_stage | **95%**（max_headroom 100GB；frozen 95%/20GB） | 给索引加 **`read_only_allow_delete`** 块（不是 read_only！），落回 high 以下自动解除 |
| reroute_interval | 60s | 水位重算周期 |

`DiskThresholdMonitor`（`:415-437`）自动加/摘块。`enable_for_single_data_node` 在 9.0 已移除（`docs/release-notes/breaking-changes.md:321`）。

## rebalance 权重与 failed allocation

desired_balance 分配器（9.x 默认，`cluster.routing.allocation.type` 已标 Deprecated）的权重（`BalancedShardsAllocator.java:89-123`）：`balance.shard` 0.45f、`balance.index` 0.55f、`balance.write_load` 10.0f、`balance.disk_usage` 2e-11f、`balance.threshold` 1.0f。`allow_rebalance` 是**条件默认**：desired_balance 下默认 `always`，切回 balanced 分配器则默认 `indices_all_active`（`ClusterRebalanceAllocationDecider.java:47-55`）。

failed allocation 的处理是**线性**的：`AllocationService.applyFailedShards`（`:234-255`）把 `failedAllocations+1` 写入新 `UnassignedInfo` 并立即 reroute；是否再试由 `MaxRetryAllocationDecider` 闸断（≥5 次 → NO）。`DelayedAllocationService`（`:49-131`）只服务 node_left 固定延迟：监听 clusterChanged → 本地为 master 时按 `findNextDelayedAllocation` 排下一次 reroute（source `delayed_allocation_reroute`）。**没有指数退避公式**，NODE_RESTARTING 场景与 shutdown API 的 allocation delay 取 max（`UnassignedInfo.remainingDelay`，`:387-399`）。

## 陷阱清单

| 说法 / 做法 | 9.5.5 真相 |
| ---- | ---- |
| 集群状态存 `data/cluster-state` | 每 data path 的 `_state` Lucene 索引 |
| `gateway.expected_nodes` / `recover_after_nodes` | 已移除；现行 `*_data_nodes` / `recover_after_time` |
| `TaskBatcher` / `ClusterMetadataPersister` | 均不存在；换成 `BatchingTaskQueue` / `PersistedClusterStateService` |
| `cluster.fault_detection.follower_checks` | 改名 `follower_check.{interval,timeout,retry_count}`（1s/10s/3） |
| flood_stage 加 read_only 块 | 是 `read_only_allow_delete`，可删可清 |
| `node_initial_replicas_recoveries` | 不存在；incoming/outgoing 跟随 `node_concurrent_recoveries` |
| failed allocation 指数退避 | 固定延迟 + max_retries 5 线性闸断 |
| 磁盘水位有 `enable_for_single_data_node` | 9.0 移除 |
| `cluster.routing.allocation.type` 是稳定配置 | 默认 desired_balance 且已标 Deprecated |
| DataTier 决策器在 server 包 | 在 x-pack 插件（`org.elasticsearch.xpack.cluster.routing.allocation`） |

## Links

- [Elasticsearch（枢纽页）](/docs/CS/Framework/ES/ES.md)
- [Cluster：集群与选举](/docs/CS/Framework/ES/Cluster.md)
- [Install：安装与节点角色](/docs/CS/Framework/ES/Install.md)
- [Troubleshooting：排障](/docs/CS/Framework/ES/Troubleshooting.md)
- [Replication：写入与复制协议](/docs/CS/Framework/ES/Replication.md)

## References

1. [Elasticsearch Reference - Cluster formation](https://www.elastic.co/guide/en/elasticsearch/reference/current/modules-discovery.html)
2. [Elasticsearch Reference - Shard allocation settings](https://www.elastic.co/guide/en/elasticsearch/reference/current/allocation-awareness.html)
3. [elastic/elasticsearch v9.5.5 源码](https://github.com/elastic/elasticsearch/tree/v9.5.5)
