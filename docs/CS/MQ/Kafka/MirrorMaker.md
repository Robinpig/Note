## Introduction

MirrorMaker v2（MM2）把一个 Kafka 集群的 topic、配置、ACL 与消费组位点持续复制到另一个集群，用于**跨地域灾备**、**多活数据中心**、**集群迁移**。

它的核心特征是**基于 Connect 框架实现** —— MM2 不是一个独立进程，而是一组跑在 Connect 集群里的 connector。

> 版本基线：**4.3.1**（`gradle.properties:17`）。源码在 `connect/mirror` 与 `connect/mirror-client`。

```tex
┌── 源集群 ──┐                      ┌── 目标集群 ──┐
│ topic A   │                      │ source,topic A│ ← 自动加源集群前缀
│ topic B   │                      │ source,topic B│
│ consumer  │                      │                │
│ group G   │                      │ source,checkpoints.internal
└─────┬─────┘                      └───────▲────────┘
      │ ① MirrorHeartbeat 周期发心跳 ────────┘（目标集群据此发现上游存活）
      │ ② MirrorCheckpoint 读位点，同步消费组
      │ ③ MirrorSource    实际复制数据 + 配置 + ACL
      ▼
  （三个 connector 都跑在 Connect 分布式集群上）
```

## 4.x 状态

> [!IMPORTANT]
> **MM2 在 4.x 仍是官方推荐的跨集群复制方案，未被 Connect 的其他 connector 取代。**
>
> 官方文档 `docs/operations/geo-replication-(cross-cluster-data-mirroring).md:41-45` 原文：
> > "Administrators can set up such inter-cluster data flows with Kafka's MirrorMaker (version 2), a tool to replicate data between different Kafka environments in a streaming manner. **MirrorMaker is built on top of the Kafka Connect framework**"
>
> 列出能力："Replicates topics (data plus configurations)"、"Replicates consumer groups including offsets to migrate applications between clusters"。

**MM1 已移除**：

> [!WARNING]
> **`MirrorMakerPartitioner` 类在 4.3.1 中全仓零命中** —— MM1 的分区器机制已删除。`MirrorMaker.java` 类仍存在（`connect/mirror/.../MirrorMaker.java`），但不带 `@Deprecated` 标记。
>
> 即「MM1 与 MM2 并存」的说法已过时，现在只有 MM2。

## 三个 Connector 的分工

`connect/mirror/src/main/java/org/apache/kafka/connect/mirror/` 完整类清单：

| 类 | 职责 |
| -- | ---- |
| **`MirrorHeartbeatConnector`** | 周期性向**源集群**发心跳，让目标集群能发现"上游还活着" |
| **`MirrorCheckpointConnector`** | 读源集群 consumer group 位点，翻译后写目标集群 |
| **`MirrorSourceConnector`** | 实际复制 topic 数据、配置与 ACL |
| `MirrorHerder` | 编排上述三者 |
| `MirrorCheckpointTask` / `MirrorHeartbeatTask` / `MirrorSourceTask` | 各自的 Task 实现 |
| `OffsetSyncStore` / `OffsetSyncWriter` | 位点同步存储 |
| `MirrorMaker` | 遗留类 |

> [!IMPORTANT]
> **`MirrorSinkConnector` 不存在**（`find -name "MirrorSink*"` 零匹配）。MM2 是**「一进一出」单个 source connector** 复制双向数据，没有独立的 sink connector。
>
> `MirrorSourceConnector.java:84` → `class MirrorSourceConnector extends SourceConnector`，未标 deprecated。

## 关键配置默认值

`connect/mirror/src/main/java/org/apache/kafka/connect/mirror/MirrorConnectorConfig.java` 等：

### 集群标识

| 配置名 | 默认值 | 出处 |
| ------ | ------ | ---- |
| `source.cluster.alias` | `source` | MirrorConnectorConfig.java:75 |
| `target.cluster.alias` | `target` | :78 |

### 复制策略

| 配置名 | 默认值 | 出处 |
| ------ | ------ | ---- |
| `replication.policy.class` | `org.apache.kafka.connect.mirror.DefaultReplicationPolicy` | MirrorClientConfig.java:54 |
| `replication.policy.separator` | `,` | MirrorClientConfig.java:57 |
| `replication.policy.internal.topic.separator.enabled` | **true** | MirrorClientConfig.java:66 |

### 内部 topic

| 配置名 | 默认值 | 出处 |
| ------ | ------ | ---- |
| `offset-syncs.topic.location` | `source` | MirrorConnectorConfig.java:116 |
| `offset-syncs.topic.replication.factor` | 3 | MirrorSourceConfig.java:53 |
| `heartbeats.topic.replication.factor` | 3 | MirrorHeartbeatConfig.java:30 |
| `checkpoints.topic.replication.factor` | 3 | MirrorCheckpointConfig.java:42 |
| `replication.factor`（远端 topic）| **2** | MirrorSourceConfig.java:37 |
| `heartbeats.replication.enabled` | true | MirrorConnectorConfig.java:95 |

### 周期与刷新

| 配置名 | 默认值 | 出处 |
| ------ | ------ | ---- |
| **`refresh.topics.interval.seconds`** | **600（10 分钟）** | MirrorSourceConfig.java:66 |
| `refresh.topics.enabled` | true | MirrorSourceConfig.java:63 |
| `sync.topic.configs.enabled` / `.interval.seconds` | true / **600** | :70,73 |
| `sync.topic.acls.enabled` / `.interval.seconds` | true / **600** | :77,80 |
| `refresh.groups.enabled` / `.interval.seconds` | true / 600 | MirrorCheckpointConfig.java:52,55 |
| `sync.group.offsets.enabled` | **false** | MirrorCheckpointConfig.java:66 |
| `sync.group.offsets.interval.seconds` | 60 | :69 |
| `emit.heartbeats.enabled` | true | MirrorHeartbeatConfig.java:34 |
| **`emit.heartbeats.interval.seconds`** | **1** | :37 |
| `emit.checkpoints.enabled` | true | MirrorCheckpointConfig.java:59 |
| `emit.checkpoints.interval.seconds` | 60 | :62 |
| `admin.task.timeout.ms` | 60000 | MirrorConnectorConfig.java:96 |
| `consumer.poll.timeout.ms` | 1000 | MirrorSourceConfig.java:59 |
| `offset.lag.max` | 100 | MirrorSourceConfig.java:89 |

### 转发与过滤

| 配置名 | 默认值 | 出处 |
| ------ | ------ | ---- |
| `forwarding.admin.class` | `...Mirror.ForwardingAdmin` | MirrorClientConfig.java:71 |
| `topic.filter.class` | `...DefaultTopicFilter` | MirrorConnectorConfig.java:112 |
| `group.filter.class` | `...DefaultGroupFilter` | MirrorCheckpointConfig.java:79 |
| `config.property.filter.class` | `...DefaultConfigPropertyFilter` | MirrorSourceConfig.java:85 |

> [!WARNING]
> **过滤器配置名是 `topics` / `topics.exclude`（group 侧 `groups` / `groups.exclude`）**，**不是** `inclusion.filters` / `exclusion.filters`。
>
> `MirrorSourceConfig.java:38,41`；**排除优先于包含**（`:43-44`）。默认委托 `DefaultTopicFilter.TOPICS_INCLUDE_DEFAULT` / `TOPICS_EXCLUDE_DEFAULT`（`:39,42`）。
>
> group 侧同理：`MirrorCheckpointConfig.java:31,34`。

## 内部 topic 名是动态拼接的

> [!IMPORTANT]
> **没有 `checkpoint.topic` 这样的配置项** —— 内部 topic 名由 `DefaultReplicationPolicy` 动态生成。
>
> `connect/mirror-client/.../DefaultReplicationPolicy.java`：
> - `offsetSyncsTopic(clusterAlias)`（`:102`）
> - `checkpointsTopic(clusterAlias)` = `clusterAlias + checkpointsTopicSuffix()`（`:107-108`）
> - `checkpointsTopicSuffix()` = `internalSeparator() + "checkpoints" + internalSuffix()`（`:97-99`）
> - `internalSuffix()` = `internalSeparator() + "internal"`（`:93-95`）
> - `internalSeparator()` 在自定义分隔符被禁用时回落 `"."`（`:90-92`）
>
> 远端 topic 名：`formatRemoteTopic(sourceClusterAlias, topic)` = `sourceClusterAlias + separator + topic`（`:65-67`），默认 separator `,` → **`source,my-topic`**。
>
> 只有 `*.topic.replication.factor` 与 `offset-syncs.topic.location` 是配置项，topic 名本身不是。

> [!NOTE]
> **`__cluster_metadata` 不是 MM2 的目标 topic** —— 它是 **KRaft 集群自身的 metadata log**（`clients/.../internals/Topic.java:30`）。MM2 复制 ACL 时是从源集群读 ACL 再在目标集群**重新创建**（`sync.topic.acls.*`），不是往 `__cluster_metadata` 写。

## Exactly-once 支持

`MirrorSourceConnector.java:91` 定义 `EXACTLY_ONCE_SUPPORT_CONFIG = "exactly.once.support"`，`:254` 判断 `"required".equals(...)` 并在 `:257-260` 注入 ConfigValue 做校验。

取值与 Connect 一致：**`requested`（默认）/ `required`**，无 `disabled`/`enabled`。见 [Connect](/docs/CS/MQ/Kafka/Connect.md)。

## 需要打假的常见说法

| 说法 | 4.3.1 实况 |
| ---- | --------- |
| 「MM2 有 `MirrorSourceConnector` **和** `MirrorSinkConnector`」 | ❌ **只有 `MirrorSourceConnector`**，无 `MirrorSinkConnector` |
| 「4.x 仍保留 MM1（`MirrorMakerPartitioner`）」 | ❌ **已移除**，全仓零命中 |
| 「有 `checkpoint.topic` 配置（默认 `__consumer_offsets`）」 | ❌ **不存在**；内部 topic 名由 `DefaultReplicationPolicy` 动态拼接 |
| 「配置 `heartbeat.interval.ms`」 | ❌ 是 **`emit.heartbeats.interval.seconds`**，默认 1 |
| 「过滤器配置叫 `inclusion.filters`/`exclusion.filters`」 | ❌ 是 **`topics`/`topics.exclude`**（group 侧 `groups`/`groups.exclude`），**排除优先于包含** |
| 「目标集群有 `__cluster_metadata` 供 MM2 写入」 | ❌ 那是 KRaft 自身的 metadata log |
| 「MM2 是独立进程」 | ❌ 是 **Connect connector**，跑在 Connect 分布式集群上 |

## 未查到清单

- MM2 在 4.x 相对 3.x 的新增特性（本次仅核实源码现状，未逐版本比对 changelog）
- `metric.names.format` 的完整可选值（默认 `legacy`，`MirrorConnectorConfig.java:128`，已标 Deprecated）

## Links

- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)
- [Connect](/docs/CS/MQ/Kafka/Connect.md)
- [KRaft](/docs/CS/MQ/Kafka/KRaft.md)
- [Consumer](/docs/CS/MQ/Kafka/Consumer.md)
- [Pulsar（对比：其跨地域复制已在 4.x 移除）](/docs/CS/MQ/Pulsar/Cluster.md)

## References

1. [Apache Kafka 4.3.1 Download](https://kafka.apache.org/downloads)
2. [MirrorConnectorConfig.java (4.3.1)](https://github.com/apache/kafka/blob/4.3.1/connect/mirror/src/main/java/org/apache/kafka/connect/mirror/MirrorConnectorConfig.java)
3. [DefaultReplicationPolicy.java (4.3.1)](https://github.com/apache/kafka/blob/4.3.1/connect/mirror-client/src/main/java/org/apache/kafka/connect/mirror/DefaultReplicationPolicy.java)
4. [Geo-Replication (Cross-Cluster Data Mirroring)](https://kafka.apache.org/documentation/#georeplication)
