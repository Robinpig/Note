## Introduction

Kafka Connect 是 Kafka 生态中**在 Kafka 与外部数据存储之间搬数据的可扩展运行时**：提供统一 API 与集群化 worker 进程，用现成的 **connector 插件**（而非手写 Producer/Consumer）把数据库、对象存储、消息系统、数据湖接入 Kafka。典型用途是 CDC 把 MySQL binlog 流入 Kafka，或把 Kafka 主题落盘到 S3 / Elasticsearch。

> 版本基线：**4.3.1**（`gradle.properties:17`）。源码在 **`connect/runtime`**（**不是** `connect/connect-runtime`，模块名在 4.x 已改）。

## 核心概念

- **Connector**：逻辑作业，描述「从哪到哪」（`SourceConnector` 读外部写 Kafka，`SinkConnector` 读 Kafka 写外部）。配置驱动，无需写代码。
- **Task**：Connector 的并行执行单元。Connector 把工作拆成若干 Task 分发到 worker，实现水平扩展与容错（Task 失败由框架重调度）。
- **Worker**：运行 Connector/Task 的进程，两种模式：
  - **Standalone**：单进程跑全部，适合边缘/简单场景。
  - **Distributed**：多 worker 组成集群，REST API 提交配置，任务自动均衡与故障转移（生产首选）。

## 重要更正：4.x Connect 没有使用虚拟线程

> [!WARNING]
> **4.3.1 的 Connect 不使用 Java 虚拟线程。** 这是最容易被误传的说法，实测证伪：
>
> 全仓 grep `ofVirtual` / `newVirtualThreadPerTaskExecutor` / `VirtualThread` / `newThreadPerTaskExecutor`（排除测试代码）→ **零匹配**。
>
> 也不能说「KIP-898 是虚拟线程运行时」—— KIP-898 实际是 Producer 端 EOS 事务边界（`transaction.boundary`）相关，与虚拟线程无关。
>
> 写笔记时不要沿用「4.x Connect 基于虚拟线程」这个说法。

## WorkerConfig 关键默认值

`connect/runtime/src/main/java/org/apache/kafka/connect/runtime/WorkerConfig.java`：

| 配置名 | 默认值 | 行号 |
| ------ | ------ | ---- |
| `offset.flush.interval.ms` | **60000（60 秒）** | 常量 :119，注册 :223 |
| `offset.flush.timeout.ms` | 5000 | :127 |
| `task.shutdown.graceful.timeout.ms` | 5000 | :114 |
| **`connector.client.config.override.policy`** | **`All`** | :166 |
| `topic.tracking.enable` | **true** | :174-177 |
| `topic.tracking.allow.reset` | true | :182 |
| `config.providers` | `List.of()`（空）| :260 → `AbstractConfig.java:67` |
| `plugin.path` / `plugin.discovery` | 见 doc | :129-148 |

### override policy 四个合法值

`All`（默认）、`Allowlist`、`None`、`Principal`（**已 deprecated**）。

实现类在 `connect/runtime/src/main/java/org/apache/kafka/connect/connector/policy/`：
- `AllConnectorClientConfigOverridePolicy`
- `AllowlistConnectorClientConfigOverridePolicy`（含 `ALLOWLIST_CONFIG`）
- `NoneConnectorClientConfigOverridePolicy`
- `PrincipalConnectorClientConfigOverridePolicy`
- `AbstractConnectorClientConfigOverridePolicy`

接口在 `connect/api/.../connector/policy/ConnectorClientConfigOverridePolicy.java`。

> [!NOTE]
> 类名是 **`ConnectorClientConfigOverridePolicy`**（Policy 结尾），不是 `ConnectorClientConfigOverrides`。

> [!WARNING]
> **`connector.client.config.override.policy` 默认 `All` 是个安全风险** —— 意味着 worker 上的 connector 配置可以覆盖任何 client 配置（含 `bootstrap.servers`、`sasl.*`）。多租户或半信任环境应显式设为 `None` 或 `Allowlist`。

## Config Provider

配置目录 `clients/src/main/java/org/apache/kafka/common/config/provider/` 下**只有 3 个实现 + 1 个接口**：

- `EnvVarConfigProvider`（`${env:VAR}` 语法）
- `FileConfigProvider`（`${file:/path}`）
- `DirectoryConfigProvider`
- `ConfigProvider`（接口）

> [!WARNING]
> **没有** Secrets / ConfigMap / AWS Secrets Manager / Azure Key Vault / Google Secret Manager 的内置实现类 —— 这些由独立项目（如 Confluent Vault）提供。
>
> 另有约束：`WorkerConfig.java:140-142` 注明 **`plugin.path` 不能用 config provider 变量**（插件扫描早于 provider 初始化）。

## Exactly-once

> [!WARNING]
> **定义在 `SourceConnectorConfig`（不是 `ConnectorConfig`）**，且**取值只有两个**：
>
> | 值 | 含义 |
> | -- | ---- |
> | `REQUESTED` | 默认值，connector 可以但不强求 |
> | `REQUIRED` | 必须支持 EOS，否则连接被拒 |
>
> **不存在 `disabled` / `enabled`**。
>
> `SourceConnectorConfig.java:67-79` 枚举，`:155` 默认值，`:156` 校验器 `CaseInsensitiveValidString.in(enumOptions(...))`。

配套配置：

| 配置名 | 说明 |
| ------ | ---- |
| `transaction.boundary` | `poll` / `connector` / `interval`（`SourceConnectorConfig.java:91`）|
| `transaction.boundary.interval.ms` | 未设时回落到 worker 的 `offset.flush.interval.ms`（`:99`、`:101-103`）|

文档印证 `docs/kafka-connect/connector-development-guide.md:332`：*"set the `exactly.once.support` property to `required`"*。

## 分布式模式的内部 topic

`connect/runtime/.../runtime/distributed/DistributedConfig.java`：

| 配置名 | 默认值 | 行号 |
| ------ | ------ | ---- |
| `config.storage.topic` | **无默认，必填** | 声明 :153，注册 :443-446 |
| `offset.storage.topic` | **无默认，必填** | 声明 :135，注册 :427-430 |
| `status.storage.topic` | **无默认，必填** | 注册 :453-456 |
| `offset.storage.partitions` | 25 | :433 |
| `status.storage.partitions` | 5 | :459 |
| `offset.storage.replication.factor` | **3** | :437-442 |
| `config.storage.replication.factor` | **3** | :447-452 |
| `status.storage.replication.factor` | 3 | :465 |

前缀常量（`:125-126`）：

```java
CONFIG_STORAGE_PREFIX = "config.storage.";
OFFSET_STORAGE_PREFIX = "offset.storage.";
```

> [!TIP]
> - 三个 storage topic **无默认值、必填**（`.define()` 第二参数缺失即无默认）。`connect-configs` / `connect-offsets` / `connect-status` 这三个名字来自 `config/connect-distributed.properties:43,53,62` 的**示例值**，不是硬编码默认。`CONFIG_TOPIC` / `OFFSET_STORE_TOPIC` 这类常量名在 4.3.1 中不存在。
> - **`connect.offset.storage` 前缀不存在**（零匹配）。现代码只有 Kafka backing store（`KafkaConfigBackingStore` / `KafkaOffsetBackingStore` / `KafkaStatusBackingStore`），**没有 `standalone` 选项**。

## 4.x 移除情况

> [!IMPORTANT]
> Connect 目录下（排除测试）**无任何 `zookeeper` / `--zookeeper` 引用** —— 已彻底移除，仅剩 `--bootstrap-server`。这与 Kafka 4.0 的 KRaft-only 方向一致。

## DLQ

Connect 与 Streams 的 DLQ 配置**前缀不同，不要混**：

| 组件 | 配置 | 默认值 | 开关 |
| ---- | ---- | ------ | ---- |
| Connect Sink | `errors.deadletterqueue.*`（`SinkConnectorConfig.java:54` `DLQ_PREFIX`）| — | **有** enable 开关 |
| Streams | `errors.dead.letter.queue.topic.name` | `null` | **无**开关，配了即启用 |

## 与 Kafka 其他组件的边界

| 组件 | 角色 | 何时用 |
|---|---|---|
| Producer/Consumer | 应用直接读写 | 业务代码内集成 |
| **Kafka Connect** | 系统间批量/增量同步 | 把 DB/存储/SAAS 接进 Kafka |
| **Kafka Streams** | 流内计算转换 | 主题间做实时聚合/Join |
| **MirrorMaker v2** | 跨集群复制 | 建在 Connect 框架上（见 [MirrorMaker](/docs/CS/MQ/Kafka/MirrorMaker.md)）|

Connect 解决「管道」，Streams 解决「处理」，二者常串联：Connect 把源吸入 → Streams 计算 → Connect 把结果下沉。

## 需要打假的常见说法

| 说法 | 4.3.1 实况 |
| ---- | --------- |
| 「4.x Connect 基于 Java 21 虚拟线程，是核心特性」 | ❌ **零匹配**，4.3.1 不用虚拟线程；`connect-runtime` 模块名也不存在（是 `connect/runtime`）|
| 「`exactly.once.support` 取 `disabled`/`enabled`/`requested`」 | ❌ 只有 **`requested`（默认）/ `required`**，且定义在 `SourceConnectorConfig` |
| 「类名是 `ConnectorClientConfigOverrides`」 | ❌ 正确名 `ConnectorClientConfigOverridePolicy` |
| 「Connect 内置 Secrets/ConfigMap/AWS/Azure/GCP config provider」 | ❌ 内置只有 `EnvVar`/`File`/`Directory` 三个 |
| 「`config.storage.topic` 默认 `connect-configs`」 | ❌ **无默认、必填**；`connect-configs` 只是示例配置里的值 |
| 「内部 topic 前缀是 `connect.offset.storage`，可选 `standalone`」 | ❌ 是 `offset.storage.`；**无 `standalone` 选项** |
| 「override policy 默认 `None`（最安全）」 | ❌ 默认 **`All`**，多租户需显式收紧 |

## Links

- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)
- [Streams](/docs/CS/MQ/Kafka/Streams.md)
- [MirrorMaker](/docs/CS/MQ/Kafka/MirrorMaker.md)
- [Consumer](/docs/CS/MQ/Kafka/Consumer.md)
- [Security](/docs/CS/MQ/Kafka/Security.md)
- [Flink（对比：真正的流处理框架）](/docs/CS/Framework/Flink/Flink.md)

## References

1. [Apache Kafka 4.3.1 Download](https://kafka.apache.org/downloads)
2. [WorkerConfig.java (4.3.1)](https://github.com/apache/kafka/blob/4.3.1/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/WorkerConfig.java)
3. [DistributedConfig.java (4.3.1)](https://github.com/apache/kafka/blob/4.3.1/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/distributed/DistributedConfig.java)
4. [Kafka Connect 官方文档](https://kafka.apache.org/documentation/#connect)
