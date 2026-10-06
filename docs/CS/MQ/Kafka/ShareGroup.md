## Introduction

Share Group 是 Kafka 4.x 引入的新消费模型，本质是把「队列」语义搬进消息队列：多个消费者**并发读同一个 partition**，每条消息只被其中一个确认。KIP-932 从 4.0 的 Early Access 到 4.2.0 GA，是近年 Kafka 最大的功能变化之一。

> 版本基线：**4.3.1**（`gradle.properties:17`）。

## 为什么需要 Share Group

Consumer Group 的核心约束是**partition 与 consumer 的一对一绑定**：一个 partition 在同一时刻只能被组内一个 consumer 消费。这带来两个硬限制：

1. **并发上限 = partition 数**。想增加消费并发必须先增加 partition。
2. **无法表达「任务池」语义**。消息处理耗时不均时，快的 consumer 空闲，慢的 consumer 积压，无法把慢任务分给空闲 consumer。

官方对 Share Group 的定位（4.0.0 announcement 原文）：

> "You can think of a share group as roughly equivalent to a **'durable shared subscription'** in existing systems."

```tex
Consumer Group（独占式）                Share Group（共享式）
┌──────────────┐                      ┌──────────────┐
│ partition 0  │ ←── C1（独占）        │ partition 0  │
├──────────────┤                      ├──────────────┤
│ partition 1  │ ←── C2（独占）        │ record 1  → C1│ ✅
└──────────────┘                      │ record 2  → C2│ ✅
                                       │ record 3  → C1│ ✅ ← 三者并发
并发上限 = partition 数                │ record 4  → C2│ ✅
                                       └──────────────┘
                                       并发上限 = 记录数
```

| 维度 | Consumer Group | Share Group |
| ---- | -------------- | ----------- |
| 分配单位 | **partition → 至多一个 consumer** | **record 级**，多 consumer 并发读同一 partition |
| 并发上限 | 受 partition 数硬限制 | **不受 partition 数限制** |
| 确认粒度 | 批量 offset commit | **逐条 acknowledge** |
| 失败处理 | 重试由客户端决定 | **delivery count 计数超限自动进 DLQ** |
| 锁 | 无 | **acquisition record lock** |
| 状态 topic | `__consumer_offsets` | **`__share_group_state`** |

## 内部 topic

`clients/src/main/java/org/apache/kafka/common/internals/Topic.java:27-30`：

```java
public static final String GROUP_METADATA_TOPIC_NAME = "__consumer_offsets";
public static final String TRANSACTION_STATE_TOPIC_NAME = "__transaction_state";
public static final String SHARE_GROUP_STATE_TOPIC_NAME = "__share_group_state";
```

> [!TIP]
> 三者都是 `INTERNAL_TOPICS`（`:37`）。
>
> 注意区分：`__share_group_state` 存的是 share partition 的**记录锁与投递状态**（`ShareCoordinatorShard.java:306` 注释：记录写入后回放到内存状态）；**committed offset 仍走 `__consumer_offsets`**。

`ShareCoordinatorService.java:91` 可见 `numPartitions = -1; // Number of partitions for __share_group_state`（分区数由 coordinator 自行决定，不静态配置）。

## 配置项

> [!WARNING]
> **两个常见配置名在 4.3.1 中不存在**：
> - `group.share.enable` —— **无此开关**（Share Group 无独立总开关）
> - `group.share.partition.max.inflight.requests` —— **无此项**，真实是 `group.share.partition.max.record.locks`
>
> 配置定义分散在**两个类**：`ShareGroupConfig` 与 `GroupCoordinatorConfig`。

### `ShareGroupConfig`（`group-coordinator/.../group/modern/share/ShareGroupConfig.java`）

| 配置名 | 默认值 | 行号 |
| ------ | ------ | ---- |
| `group.share.partition.max.record.locks` | 2000 | 36-37 |
| `group.share.max.partition.max.record.locks` | 4000 | 40-41 |
| `group.share.min.partition.max.record.locks` | 100 | 44-45 |
| **`group.share.delivery.count.limit`** | **5** | 48-49 |
| `group.share.max.delivery.count.limit` | 10 | 52-53 |
| `group.share.min.delivery.count.limit` | 2 | 56-57 |
| **`group.share.record.lock.duration.ms`** | **30000** | 60-61 |
| `group.share.min.record.lock.duration.ms` | 15000 | 64-65 |
| `group.share.max.record.lock.duration.ms` | 60000 | 68-69 |
| `share.fetch.purgatory.purge.interval.requests` | 1000 | 72-73 |
| `group.share.max.share.sessions` | 2000 | 76-77 |
| **`group.share.persister.class.name`** | `org.apache.kafka.server.share.persister.DefaultStatePersister` | 80-81 |

### `GroupCoordinatorConfig`（`group-coordinator/.../group/GroupCoordinatorConfig.java`）

| 配置名 | 默认值 | 行号 |
| ------ | ------ | ---- |
| `group.share.max.size` | 200 | 264-265 |
| `group.share.session.timeout.ms` | 45000 | 268-269 |
| `group.share.min.session.timeout.ms` | 45000 | 271-272 |
| `group.share.max.session.timeout.ms` | 60000 | 274-275 |
| `group.share.heartbeat.interval.ms` | 5000 | 280-281 |
| `group.share.min.heartbeat.interval.ms` | 5000 | 283-284 |
| `group.share.max.heartbeat.interval.ms` | 15000 | 286-287 |
| `group.share.assignors` | `SimpleAssignor`（内置单值）| 293-296 |

> [!TIP]
> **record lock 三档是自动调节的**（min 15s / 默认 30s / max 60s）—— 与 Consumer Group 的 session timeout 三档同构，coordinator 会根据锁获取情况动态调整，避免长尾记录被过早释放。
>
> 三个 `delivery.count.limit` 同理（min 2 / 默认 5 / max 10）。

## 协议：ApiKeys 数值

`clients/src/main/resources/common/message/*.json` 第 17 行 `"apiKey"`：

| ApiKeys | apiKey | 出处 |
| ------- | ------ | ---- |
| `CONSUMER_GROUP_HEARTBEAT`（KIP-848）| **68** | `ConsumerGroupHeartbeatRequest.json:17` |
| `SHARE_GROUP_HEARTBEAT` | **76** | `ShareGroupHeartbeatRequest.json:17` |
| `SHARE_FETCH` | **78** | `ShareFetchRequest.json:17` |
| `SHARE_ACKNOWLEDGE` | **79** | `ShareAcknowledgeRequest.json:17` |

枚举定义：`clients/src/main/java/org/apache/kafka/common/protocol/ApiKeys.java:124,126,127`。

> [!NOTE]
> 这些数值**不是我记忆里的值**，是从 4.3.1 的消息定义 JSON 里读出来的 `apiKey` 字段。KIP 编号与 apiKey 数值无对应关系，不要按 KIP 号推算。

## 与 KIP-848 新消费者组协议的关系

二者是**不同 group type，不是同一开关的两档**，可共存。

客户端选择项 = **`group.protocol`**（`ConsumerConfig.java:114-117`）：

```java
public static final String GROUP_PROTOCOL_CONFIG = "group.protocol";
public static final String DEFAULT_GROUP_PROTOCOL = GroupProtocol.CLASSIC.name().toLowerCase(Locale.ROOT);
```

> [!IMPORTANT]
> **默认是 `classic`。** 即使 4.0+ 服务端已默认启用新协议，**客户端不显式设置就用经典协议** —— 这是升级后最容易忽略的行为。
>
> 取值：`classic` / `consumer`（KIP-848 的新消费组协议）。相关配置 `group.remote.assignor`（`ConsumerConfig.java:121`）仅在 `group.protocol=consumer` 时生效。

> [!WARNING]
> **`group.coordinator.new.enable` 不存在**（全仓零命中）。真实机制是 `group.coordinator.rebalance.protocols`，默认 `List.of(CLASSIC, CONSUMER, STREAMS)`（`GroupCoordinatorConfig.java:82-85`）。
>
> 而且该配置在 4.3 已标 `@Deprecated(since="4.3", forRemoval=true)`（`:75-77`），原文：
> > "In Kafka 5.0, all protocols will always be enabled and cannot be disabled via this configuration. Use feature versions (group.version, streams.version, share.version) managed by kafka-features.sh instead."

`GroupMetadataManager.java:7471` 可见按 `protocolName` 分派（`classic` / `consumer` / `streams` / share）。

### 选型判据

| 需求 | 选择 |
| ---- | ---- |
| 每 partition 独占、顺序稳定、offset 长期提交 | **Consumer Group**（`classic` 或 `consumer`）|
| 多消费者抢同一批任务、逐条 ack、失败自动重投、水平扩展不受 partition 限制 | **Share Group** |

## 生命周期要点

1. **记录锁（record lock）**：consumer fetch 时获得记录的独占锁，锁有超时（`group.share.record.lock.duration.ms`），超时后其他 consumer 可接手。
2. **acknowledge**：consumer 处理完发 `SHARE_ACKNOWLEDGE` 确认。
3. **delivery count 计数**：每次投递 +1，达 `group.share.delivery.count.limit`（5）后进入 DLQ。
4. **persister**：`group.share.persister.class.name` 默认 `DefaultStatePersister`，负责 `__share_group_state` 的记录持久化与回放（`PersisterStateManager.java:318-320` 负责内部 topic 生命周期）。
5. **分派器**：`group.share.assignors` 默认 `SimpleAssignor` —— Share Group 的分派逻辑是「记录级抢占」，与传统 partition 分派本质不同。

## 演进时间线

| 版本 | 状态 |
| ---- | ---- |
| 4.0.0（2025-03） | KIP-932 **Early Access** |
| 4.1.0（2025-09） | KIP-932 **Preview** |
| **4.2.0（2026-02）** | **KIP-932 GA**（4.2.0 整体 38 KIP、155 贡献者）|

4.3.0 相关 KIP：KIP-1244 弃用 streams-scala；KIP-1259 `state.cleanup.dir.max.age.ms`；KIP-1271/1285 State Store 存 Headers。

## 需要打假的常见说法

| 说法 | 4.3.1 实况 |
| ---- | --------- |
| 「Share Group 就是 Consumer Group 换个名字，都是分区独占」 | ❌ Share Group 是**记录级**共享订阅 + 逐条 ack + 投递计数 |
| 「有 `group.share.enable` 开关」 | ❌ **不存在**，Share Group 无独立开关 |
| 「有 `group.share.partition.max.inflight.requests`」 | ❌ 真实是 `group.share.partition.max.record.locks` |
| 「用 `group.coordinator.new.enable` 控制新旧 coordinator」 | ❌ 不存在；真实是 `group.coordinator.rebalance.protocols`（4.3 已弃用，5.0 移除）|
| 「4.x 默认走新消费组协议」 | ❌ 客户端默认 **`classic`**，须显式设 `group.protocol=consumer` |
| 「Share Group 的 offset 存在 `__share_group_state`」 | ⚠️ `__share_group_state` 存**记录锁与投递状态**；committed offset 仍走 `__consumer_offsets` |
| 「`group.share.session.timeout.ms` 默认 45s，可配到更大」 | ⚠️ 默认 45000，**max 也只有 60000**（Consumer Group 默认 45000 但上界远大于此）|

## 未查到清单

- `group.share.assignment.interval.ms` 的默认值（配置名已确认存在于 `GroupCoordinatorConfig.java:298`，未读取数值行）
- KIP-848 `memberEpoch` 字段的具体校验代码位置（仅确认 KIP-1251 在 4.3.0 改进 epoch 校验以减少不必要 fencing）
- KAFKA-20616（4.3.1 修复的 Streams RocksDB native memory leak）涉及的配置项与现象 —— 见 [Streams](/docs/CS/MQ/Kafka/Streams.md) 篇的升级警告

## Links

- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)
- [Consumer](/docs/CS/MQ/Kafka/Consumer.md)
- [KRaft](/docs/CS/MQ/Kafka/KRaft.md)
- [Storage](/docs/CS/MQ/Kafka/Storage.md)
- [Security](/docs/CS/MQ/Kafka/Security.md)
- [Pulsar（另一种消费模型）](/docs/CS/MQ/Pulsar/Consumer.md)

## References

1. [Apache Kafka 4.3.1 Download](https://kafka.apache.org/downloads)
2. [ShareGroupConfig.java (4.3.1)](https://github.com/apache/kafka/blob/4.3.1/group-coordinator/src/main/java/org/apache/kafka/coordinator/group/modern/share/ShareGroupConfig.java)
3. [Topic.java (4.3.1)](https://github.com/apache/kafka/blob/4.3.1/clients/src/main/java/org/apache/kafka/common/internals/Topic.java)
4. [KIP-932: Queues for Kafka](https://cwiki.apache.org/confluence/display/KAFKA/KIP-932%3A+Queues+for+Kafka)
