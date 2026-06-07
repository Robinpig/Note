## Introduction

Follow-Replicas 不支持读写。
- Read-your-writes
- Monotonic Reads

## ISR

ISR 是指与分区 leader broker 保持同步的副本。
任何与 leader 不同步的副本都是 out of sync。

当分区 leader 不可用时，将选择一个同步副本（ISR）作为新 leader。
这种 leader 选举是"干净的"，因为它保证不会丢失已提交的数据——根据定义，已提交的数据存在于所有 ISR 上。

但当除了刚刚不可用的 leader 之外没有 ISR 时该怎么办？

等待 ISR 重新上线。这是默认行为，但这会使 topic 面临不可用的风险。

启用 unclean.leader.election.enable=true 并开始向非 ISR 分区生产消息。我们将丢失在副本不同步期间写入旧 leader 的所有消息，并导致消费者中的一些不一致。

### Consumers Replicas Fetching

Kafka 消费者默认从分区 leader 读取。
但从 Apache Kafka 2.4 开始，可以配置消费者从同步副本（通常是最接近的那个）读取。
从最近的同步副本（ISR）读取可以改善请求延迟，并降低网络成本，因为在大多数云环境中，跨数据中心网络请求会产生费用。

### Preferred leader

Preferred leader 是在 topic 创建时为分区指定的 leader broker（相对于副本而言）。
当 preferred leader 下线时，任何属于 ISR（同步副本）的分区都有资格成为新 leader（但不是 preferred leader）。
当 preferred leader broker 恢复并且其分区数据重新同步后，preferred leader 将重新获得该分区的领导权。

### Replication Factor and Partition Count

创建 topic 时，我们必须提供分区数和复制因子。
这两个参数对系统的性能和持久性影响很大，需要正确设置。

选择复制因子时需要考虑的因素：

至少应为 2，最大为 4。
推荐数量为 3，因为这可以在性能和容错之间提供良好的平衡

在由 ZooKeeper 管理的 Kafka 集群中，所有 broker 的分区总数应不超过 200,000 个。原因是如果 broker 宕机，ZooKeeper 需要执行大量的 leader 选举。
Confluent 仍建议集群中每个 broker 最多 4000 个分区。
这个问题应该在无 ZooKeeper 模式（Kafka KRaft）下得到解决。
如果集群中需要超过 200,000 个分区，请遵循 Netflix 模型创建更多 Kafka 集群

replica.lag.time.max.ms

replication.factor = min.insync.replicas + 1

### Unclean Leader Election

当分区 leader 不再可用时，将选择一个同步副本（ISR）作为新 leader。
这种 leader 选举是"干净的"，因为它保证不会丢失已提交的数据——根据定义，已提交的数据存在于所有 ISR 上。

但当除了刚刚不可用的 leader 之外没有 ISR 时该怎么办？

- 等待 ISR 重新上线。
  这是默认行为，但这会使 topic 面临不可用的风险。
- 启用 unclean.leader.election.enable=true 并开始向非 ISR 分区生产消息。
  我们将丢失在副本不同步期间写入旧 leader 的所有消息，并导致消费者中的一些不一致。

这些不洁 leader 选举可以帮助提高集群的可用性，
但如果未将数据复制到另一个集群或其他存储目标，则可能导致数据丢失。
具体过程如下：

1. 作为分区 A leader 的 broker 离线。
   分区 A 的所有 follower 都未赶上 leader（ISR=0）。
2. 如果启用了不洁 leader 选举，其中一个 follower broker 将被选为分区的新 leader，
   即使它是"不洁的"。这允许消费者和生产者继续向分区 A 发送请求。
3. 如果之前的 leader 重新上线，它将重置其 offset 以匹配新 leader 的 offset，从而导致数据丢失。
   例如，如果之前的 leader 处理消息到 offset=7，而新的
   不洁 leader 在被选为 leader 时稍落后（offset=4），
   那么在第一个 leader 重新上线并以 replica/follower 身份重新加入集群后，某些消息（offsets 5-7）将被删除。

## replica sync

Follower 发送 FETCH 请求给 Leader。接着，Leader 会读取底层日志文件中的消
息数据，再更新它内存中的 Follower 副本的 LEO 值，更新为 FETCH 请求中的
fetchOffset 值。最后，尝试更新分区高水位值。Follower 接收到 FETCH 响应之后，会把
消息写入到底层日志，接着更新 LEO 和 HW 值。

Leader 和 Follower 的 HW 值更新时机是不同的，Follower 的 HW 更新永远落后于
Leader 的 HW。这种时间上的错配是造成各种不一致的原因。

## Links

- [Apache Kafka](/docs/CS/MQ/Kafka/Kafka.md)
