## Introduction

> 版本基线：**4.3.1**。4.0 起 ZooKeeper 模式彻底移除，所有副本管理走 KRaft controller quorum。

Follow-Replicas not supported read/write.
- Read-your-writes
- Monotonic Reads



## ISR

An ISR is a replica that is up to date with the leader broker for a partition.
Any replica that is not up to date with the leader is out of sync.

When the leader for a partition is no longer available, one of the in-sync replicas (ISR) will be chosen as the new leader. This leader election is ”clean“ in the sense that it guarantees no loss of committed data - by definition, committed data exists on all ISRs.

But what to do when no ISR exists except for the leader that just became unavailable?

Wait for an ISR to come back online. This is the default behavior, and this makes you run the risk of the topic becoming unavailable.

Enable unclean.leader.election.enable=true and start producing to non-ISR partitions. We are going to lose all messages that were written to the old leader while that replica was out of sync and also cause some inconsistencies in consumers.

### Consumers Replicas Fetching

Kafka consumers read by default from the partition leader.
But since Apache Kafka 2.4, it is possible to configure consumers to read from in-sync replicas instead (usually the closest).
Reading from the closest in-sync replicas (ISR) may improve the request latency, and also decrease network costs, because in most cloud environments cross-data centers network requests incur charges.

### Preferred leader

The preferred leader is the designated leader broker for a partition at topic creation time (as opposed to being a replica).
When the preferred leader goes down, any partition that is an ISR (in-sync replica) is eligible to become a new leader (but not a preferred leader).
Upon recovering the preferred leader broker and having its partition data back in sync, the preferred leader will regain leadership for that partition.

### Replication Factor and Partition Count

When creating a topic, we have to provide a partition count and the replication factor.
These two are very important to set correctly as they impact the performance and durability in the system.

The factors to consider while choosing replication factor are:

It should be at least 2 and a maximum of 4.
The recommended number is 3 as it provides the right balance between performance and fault tolerance

### Partition Scale in KRaft

4.0 起 KRaft 成为唯一模式，ZooKeeper 的 `200,000 partition` 上限彻底移除。KRaft controller quorum 通过 Raft 日志复制元数据，分区数量上限由 controller 节点的内存与磁盘决定，单集群可支撑数百万分区。

单 broker 推荐分区数仍是 4,000 左右（Confluent 建议值），过多分区会增加 broker 的日志管理开销与 controller 的元数据复制压力。


replica.lag.time.max.ms


replication.factor = min.insync.replicas + 1


### Unclean Leader Election


When the leader for a partition is no longer available, one of the in-sync replicas (ISR) will be chosen as the new leader. 
This leader election is "clean" in the sense that it guarantees no loss of committed data - by definition, committed data exists on all ISRs.

But what to do when no ISR exists except for the leader that just became unavailable?

- Wait for an ISR to come back online. 
  This is the default behavior, and this makes you run the risk of the topic becoming unavailable.
- Enable unclean.leader.election.enable=true and start producing to non-ISR partitions.
  We are going to lose all messages that were written to the old leader while that replica was out of sync and also cause some inconsistencies in consumers.

These unclean leader elections can help improve the availability of your cluster, 
but they could result in data loss if you do not duplicate the data to another cluster or other storage destination.
Here’s how that might play out:

1. The broker that is the leader for Partition A goes offline. 
   None of the followers of Partition A are caught up to the leader (ISR=0).
2. If unclean leader elections are enabled, one of the follower brokers will get elected as the new leader for the partition,
   even though it is “unclean.” This allows consumers and producers to continue sending requests to Partition A.
3. If the previous leader comes back online, it will reset its offset to match the new leader’s offset, resulting in data loss. 
   For example, if the previous leader processed messages up to offset=7, and the new, 
   unclean leader was slightly behind (offset=4) at the time it was elected leader, 
   some messages (offsets 5–7) will get deleted after the first leader comes back online and rejoins the cluster as a replica/follower.

## replica sync

Follower 发送 FETCH 请求给 Leader。接着，Leader 会读取底层日志文件中的消
息数据，再更新它内存中的 Follower 副本的 LEO 值，更新为 FETCH 请求中的
fetchOffset 值。最后，尝试更新分区高水位值。Follower 接收到 FETCH 响应之后，会把
消息写入到底层日志，接着更新 LEO 和 HW 值。

Leader 和 Follower 的 HW 值更新时机是不同的，Follower 的 HW 更新永远落后于
Leader 的 HW。这种时间上的错配是造成各种不一致的原因。

## Eligible Leader Replicas (KIP-966, 4.0 Preview)

KIP-966 在 4.0 引入 Eligible Leader Replicas (ELR)，是 ISR 的**安全子集**：保证数据完整到 high-watermark 的副本集合。ELR 的核心价值是**防止数据丢失的 leader 选举**。

ISR 只保证副本"跟上了 leader"，但在某些场景下（如 unclean leader election 关闭时 ISR 为空），仍然可能选出一个数据落后的 leader。ELR 则额外保证：

1. 所有 ELR 成员都**确认拥有 HW 之前的全部数据**
2. Leader 选举时优先从 ELR 中挑选，避免选出数据缺口的副本

> [!NOTE]
> ELR 在 4.0 是 **Preview** 阶段，需要显式启用。4.3 中已稳定，但文档仍标注为 preview。

## KRaft Replica Management Changes (4.x)

4.0 起副本管理从 ZooKeeper 的 `KafkaController` 迁到 KRaft controller quorum：

| 维度 | ZooKeeper 模式（已移除） | KRaft 模式（4.x 唯一） |
| ---- | ------------------------ | ---------------------- |
| 副本状态存储 | ZK 节点 `/brokers/topics/[topic]` | Raft metadata log（`__cluster_metadata` topic） |
| ISR 变更传播 | ZK watch 通知 | Controller 通过 `BrokerHeartbeat` / `BrokerRegistration` RPC 主动推送 |
| Leader 选举触发 | ZK session 超时 + controller watch | KRaft Raft 层 Pre-Vote（KIP-996）+ controller 元数据变更 |
| 分区 reassign | ZK `admin/reassign_partitions` 节点 | `PartitionReassignmentRecord` 写入 metadata log |
| unclean leader election | `unclean.leader.election.enable`（broker 级） | 同配置但由 controller 在 metadata log 中记录决策 |

### Pre-Vote (KIP-996)

KIP-996 在 4.0 引入，解决 KRaft leader 选举中的**无效投票风暴**问题。

在没有 Pre-Vote 的情况下，网络分区会让每个隔离节点都认为自己应该发起选举，导致：
- 每次选举都递增 term
- 网络恢复后需要多轮选举才能收敛

Pre-Vote 机制让节点在发起正式选举前，先发送一轮不递增 term 的 pre-vote 请求：
- 如果节点发现有更高 term 的 leader 存在，**放弃选举**
- 只有在确认没有更高 term leader 时才进入正式 Candidate 状态

这大幅减少了网络分区期间的 term 膨胀和选举抖动。

## Links

- [Apache Kafka](/docs/CS/MQ/Kafka/Kafka.md)
- [KRaft（Raft 协议与 controller quorum）](/docs/CS/MQ/Kafka/KRaft.md)
- [Broker（副本 append 与 fetch 路径）](/docs/CS/MQ/Kafka/Broker.md)
- [Storage（log segment 与索引）](/docs/CS/MQ/Kafka/Storage.md)

## References

1. [KIP-966: Eligible Leader Replicas](https://cwiki.apache.org/confluence/display/KAFKA/KIP-966%3A+Eligible+Leader+Replicas)
2. [KIP-996: Pre-Vote](https://cwiki.apache.org/confluence/display/KAFKA/KIP-996%3A+Pre-Vote)
