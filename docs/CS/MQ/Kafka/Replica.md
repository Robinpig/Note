## Introduction

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

A Kafka cluster should have a maximum of 200,000 partitions across all brokers when managed by Zookeeper. The reason is that if brokers go down, Zookeeper needs to perform a lot of leader elections.
Confluent still recommends up to 4,000 partitions per broker in your cluster.
This problem should be solved by Kafka in a Zookeeper-less mode (Kafka KRaft)
If you need more than 200,000 partitions in your cluster, follow the Netflix model and create more Kafka clusters


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

## Links

- [Apache Kafka](/docs/CS/MQ/Kafka/Kafka.md)