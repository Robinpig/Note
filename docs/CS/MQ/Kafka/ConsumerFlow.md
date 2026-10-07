## Introduction

本页把 `KafkaConsumer.poll()` 的内部调用链固定下来，作为读 [Consumer](/docs/CS/MQ/Kafka/Consumer.md) 与排查消费问题的参照。**4.x 的客户端实现已重构分层**，理解这一点是读懂调用链的前提。

> 版本基线：**4.3.1**（`gradle.properties:17`）。

## 4.x Client New Layering

> [!IMPORTANT]
> **4.x 的消费端不再是「一个 `KafkaConsumer` 干所有事」，而是拆成了 delegate + 两种实现**：
>
> ```
> clients/src/main/java/org/apache/kafka/clients/consumer/
> ├── KafkaConsumer.java          ← 1896 行，已大幅瘦身（4.x 之前是 3000+ 行的庞然大物）
> └── internals/
>     ├── ConsumerDelegate.java    ← 统一门面
>     ├── ConsumerDelegateCreator.java
>     ├── ClassicKafkaConsumer.java   ← 1304 行，poll 主流程在此
>     └── AsyncKafkaConsumer.java     ← 异步实现（4.x 新增）
> ```
>
> 与 4.x 其他模块一样，这里正在做 **Java 化重构**，大量逻辑从旧版 `KafkaConsumer` 下沉到 `internals/` 下的专门类。读 4.x 代码时不要在 `KafkaConsumer.java` 里找 poll 的实现。

`internals/` 包里值得注意的其他类（都是职责拆分的结果）：

| 类 | 职责 |
| -- | ---- |
| `ConsumerCoordinator` | 组协调、rebalance、offset 提交 |
| `AbstractCoordinator` | 协调者基类（心跳线程等）|
| `AbstractMembershipManager` | 成员管理抽象 |
| `AbstractHeartbeatRequestManager` / `BaseHeartbeatThread` | 心跳管理 |
| `CommitRequestManager` | 异步提交 offset |
| `AbstractFetch` / `CompletedFetch` / `AsyncClient` | 拉取路径 |
| `AcknowledgementBatch` / `Acknowledgements` | **Share Group 专用**（见 [ShareGroup](/docs/CS/MQ/Kafka/ShareGroup.md)）|
| `AutoOffsetResetStrategy` | 位点重置策略 |
| `AbstractStickyAssignor` / `CooperativeStickyAssignor` | 分配器 |

## poll Main Flow

核心在 `internals/ClassicKafkaConsumer.java:660-662`：

```java
updateAssignmentMetadataIfNeeded(timer, false);
...
final Fetch<K, V> fetch = pollForFetches(timer);
```

**`KafkaConsumer` 不是线程安全的，且单线程使用**（这是 poll 链路设计的前提）：

| 约束 | 说明 |
| ---- | ---- |
| **单线程** | `KafkaConsumer` 的所有方法（除 `pause`/`resume` 等少数）只能在**创建它的线程**上调用，否则抛 `ConcurrentModificationException` |
| **不跨 poll 保留 iterator** | 必须消费完返回的所有记录才能再调 `poll`（`KafkaConsumer.java:258` javadoc 明确）|
| **rebalance 只在 poll 期间发生** | `:684`、`:739` javadoc：「Group rebalances only take place during an active call to `poll(Duration)`」|

## Complete Call Chain

```java
KafkaConsumer.poll(Duration)
  └─ ConsumerDelegate → ClassicKafkaConsumer.poll()
       ├─ acquireAndEnsureOpen()              // 检查未关闭 + 单线程持有者
       ├─ maybeTriggerPartitionReassignment()  // 触发 rebalance
       ├─ updateAssignmentMetadataIfNeeded()   // :660  加入组 / 同步元数据 / 分配分区
       │    └─ ConsumerCoordinator
       │         ├─ pollForJoinGroup()         // classic 协议：JoinGroup/SyncGroup
       │         ├─ onJoinComplete()           // 拿到分区分配
       │         └─ updateAssignmentMetadataIfNeeded(timer, true)  // :1301 阻塞版
       ├─ pollForFetches()                     // :662  拉消息
       │    └─ Fetcher
       │         ├─ fetchedRecords()           // 已拉回的 records
       │         └─ sendFetches()              // 发送 fetch 请求
       ├─ interceptors.onConsume()             // ConsumerInterceptor 前置钩子
       └─ return ConsumerRecords
```

### 1. Trigger Rebalance

`maybeTriggerPartitionReassignment()` —— 依据 `heartbeat` 超时、`max.poll.interval.ms` 超限等条件判断是否需要重新分配。

> [!TIP]
> `max.poll.interval.ms` 是最常见的消费卡死原因：两次 `poll` 间隔超过它，consumer 被踢出组并触发 rebalance，即使 `session.timeout.ms` 还没到。处理逻辑慢（比如 `poll` 后做耗时计算）是最典型的触发方式。

### 2. Join Group and Assign Partitions

`updateAssignmentMetadataIfNeeded()`（`:695`）负责：

- **首次订阅后自动入组** —— `:134` javadoc：「After subscribing to a set of topics, the consumer will automatically join the group when `poll(Duration)` is [called]」
- classic 协议走 `JoinGroup` + `SyncGroup`；KIP-848 新协议走 `group.protocol=consumer` 的新 coordinator 路径
- 完成后 `ConsumerRebalanceListener` 的回调被触发（`onPartitionsAssigned` / `onPartitionsRevoked`）

> [!NOTE]
> 分区分配策略在 `ConsumerPartitionAssignor` / `CooperativeStickyAssignor`，细节见 [Consumer 分区分配](/docs/CS/MQ/Kafka/Consumer.md?id=consumerpartitionassignor)。

### 3. Fetch Messages

`pollForFetches()`（`:706`）—— 注意 `:723` 注释强调：**必须在 `updateAssignmentMetadataIfNeeded` 之后调用**，否则分配还没同步完。

控制参数：

| 配置 | 作用 |
| ---- | ---- |
| `max.poll.records` | 单次 poll 返回的最大记录数（Streams 内部固定覆盖为 1000）|
| `fetch.min.bytes` / `fetch.max.bytes` | 拉取量上下限 |
| `fetch.max.wait.ms` | 等待 broker 返回的最长时间 |

### 4. Interceptors

`interceptors.onConsume()` 在记录返回给用户**之前**调用。**`onConsume` 必须返回原记录**，不能替换成 null 或数量不同的集合，否则 `poll` 抛 `IllegalStateException`。详见 [Interceptor](/docs/CS/MQ/Kafka/Consumer.md?id=commit)。

### 5. Correct Approach to Multi-threaded Consumption

> [!WARNING]
> `KafkaConsumer` 本身**不支持**多线程消费。常见错误是多个线程共享一个 consumer —— 每个线程各自调 `poll`，会导致 `ConcurrentModificationException`（`acquire` 失败）。
>
> 正确模式是**每个线程一个独立的 `KafkaConsumer` 实例**，它们属于**同一个 `group.id`**，由 Kafka 自己做分区分配与再平衡。

## Comparison with Share Consumer

4.x 新增的 `KafkaShareConsumer`（同包下，配套 `MockShareConsumer`）走的是**完全不同的协议**：

| | `KafkaConsumer` | `KafkaShareConsumer` |
| -- | -------------- | ------------------- |
| 协议 | Fetch + offset commit | **`SHARE_FETCH`(78) / `SHARE_ACKNOWLEDGE`(79)** |
| 位点 | `__consumer_offsets` | `__share_group_state`（记录锁与投递状态）|
| 并发上限 | partition 数 | 记录数 |
| 状态类 | `ConsumerCoordinator` | `AcknowledgementBatch` / `Acknowledgements` |

详见 [ShareGroup](/docs/CS/MQ/Kafka/ShareGroup.md)。

## Troubleshooting Clues

| 症状 | 优先怀疑 |
| ---- | -------- |
| `ConcurrentModificationException` | 多线程共享了同一个 consumer |
| 被反复踢出组、rebalance 频繁 | `max.poll.interval.ms` 超限（处理逻辑太慢）|
| `poll` 返回空但明明有数据 | 位点已到末尾；或 `fetch.max.wait.ms` 与 `max.poll.records` 配置不合理 |
| `CommitFailedException` | 已被踢出组，提交失败 |
| `OffsetOutOfRangeException` | 被重置位点 / `log.retention.ms` 已把数据删掉（见 [Storage](/docs/CS/MQ/Kafka/Storage.md)）|
| 消费延迟持续增长 | 拉取量不足（`max.poll.records` / `max.partition.fetch.bytes`），或下游处理慢 |
| 消费停滞且日志无 rebalance | 检查是否 `pause` 了分区未恢复 |

## Links

- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)
- [Consumer](/docs/CS/MQ/Kafka/Consumer.md)
- [ShareGroup](/docs/CS/MQ/Kafka/ShareGroup.md)
- [Storage（位点与截断）](/docs/CS/MQ/Kafka/Storage.md)
- [Broker（fetch 请求的服务端侧）](/docs/CS/MQ/Kafka/Broker.md)

## References

1. [Apache Kafka 4.3.1 Download](https://kafka.apache.org/downloads)
2. [ClassicKafkaConsumer.java (4.3.1)](https://github.com/apache/kafka/blob/4.3.1/clients/src/main/java/org/apache/kafka/clients/consumer/internals/ClassicKafkaConsumer.java)
3. [KafkaConsumer.java (4.3.1)](https://github.com/apache/kafka/blob/4.3.1/clients/src/main/java/org/apache/kafka/clients/consumer/KafkaConsumer.java)
