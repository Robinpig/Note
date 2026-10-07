## Introduction

Pulsar Functions 是「在 broker 旁边跑一个轻量处理进程」的轻量计算模型，不需要独立计算集群。同时它与 `pulsar-io`（连接器）**共用同一套 runtime 体系**。

> 版本基线：**4.2.4**（tag `v4.2.4`）。

```tex
                 Function / Source / Sink（三种 API）
                            │共用
                  RuntimeFactory（决定进程模型）
        ┌───────────────────┼───────────────────┐
   ThreadRuntimeFactory  ProcessRuntimeFactory  KubernetesRuntimeFactory
      （同 JVM 线程池）    （独立 java 子进程）      （K8s Pod）
```

## Module Structure

`pulsar-functions/` 子目录：`api-java`、`runtime`、`runtime-all`、`instance`、`worker`、`proto`、`localrun`、`localrun-shaded`、`java-examples`、`java-examples-builtin`、`python-examples`、`utils`、`secrets`、`scripts`。

> [!TIP]
> **配置在 `WorkerConfig` 而不在 `ServiceConfiguration`** —— 这是最容易走错的地方。真实路径：
> **`pulsar-functions/runtime/src/main/java/org/apache/pulsar/functions/worker/WorkerConfig.java`**
> （在 **runtime 模块**，不在 worker 模块）。

## Two Deployment Modes

| 模式 | 开关 | 位置 |
| ---- | ---- | ---- |
| 独立 Functions Worker 集群 | `functionsWorkerEnabled=false` + 单独起 worker | `pulsar-functions/worker/`（19 个类：`Worker.java`、`PulsarWorkerService.java`、`FunctionRuntimeManager.java`、`FunctionActioner.java` 等）|
| Broker 内嵌 | `functionsWorkerEnabled = true` | `ServiceConfiguration.java:3626`，启动点 `PulsarService.java:1069` `startWorkerService(...)`（**全流程最后一步**）|

Worker 端口（`WorkerConfig.java:105,110`）：

| 字段 | 类型 | yml 默认 |
| ---- | ---- | -------- |
| `workerPort` | `Integer` | 6750（`conf/functions_worker.yml:26`）|
| `workerPortTls` | `Integer` | 6751（`:27`）|

`workerId` 空则惰性生成 `{hostname}-{port}`（`:95` / `:850-854`），`workerHostname` 空则 `unsafeLocalhostResolve()`（`:100` / `:858-861`）。

## Runtime Selection: Three Implementations, No Implicit Default

| Runtime | 类 | 进程模型 |
| -------- | -- | -------- |
| Thread | `thread/ThreadRuntimeFactory.java` | 同 JVM 线程池 |
| Process | `process/ProcessRuntimeFactory.java` | 独立 java 子进程 |
| Kubernetes | `kubernetes/KubernetesRuntimeFactory.java` | K8s Pod |

三者都实现 `RuntimeFactory`（`pulsar-functions/runtime/.../runtime/RuntimeFactory.java`）。配套的 `RuntimeSpawner` / `RuntimeUtils` / `JavaInstanceStarter` 在同包。

> [!WARNING]
> **`GoRuntimeFactory` 不存在。** `pulsar-function-go/` 是**纯 Go SDK**（目录只有 `pf/`、`pb/`、`logutil/`、`go.mod`，**无任何 .java 文件**），4.x 已移除 Go runtime 实现。

### runtime Selection Logic

`FunctionRuntimeManager.java:194-216`：

```
functionRuntimeFactoryClassName 非空 → 反射加载
否则依次检查：
  threadContainerFactory     → ThreadRuntimeFactory      (:199)
  processContainerFactory    → ProcessRuntimeFactory     (:204)
  kubernetesContainerFactory → KubernetesRuntimeFactory  (:209)
三者都为空 → throw RuntimeException("A Function Runtime Factory needs to be set")  (:214)
```

> [!IMPORTANT]
> **没有隐式默认，必须显式配置。** 旧资料说「默认 `{"threads":8}`」—— 源码中**未查到**该默认值，且 `ThreadContainerFactory` 已被 `@Deprecated`（`:915`），注释明确「Deprecated in favor of using functionRuntimeFactoryClassName and functionRuntimeFactoryConfigs」。

## WorkerConfig Defaults

| 字段 | 默认值 | 行号 | 备注 |
| ---- | ------ | ---- | ---- |
| `functionRuntimeFactoryClassName` | **无字段默认值** | 703 | |
| `functionRuntimeFactoryConfigs` | `Map<String,Object>` | 709 | ⚠️ **是 Map 不是 JSON 字符串** |
| `numFunctionPackageReplicas` | 无字段默认值 | 369 | yml `:70` = **1** |

> [!WARNING]
> - **`functionRuntimeFactoryConfig`（单数）不存在** —— 真实是 `functionRuntimeFactoryConfigs`（复数）且类型是 `Map<String,Object>`。
> - **`functionDirectory` 不存在** —— `WorkerConfig` 无此字段，yml `:71` 是 `downloadDirectory: download/pulsar_functions`。

## Three Types of API: Source/Sink/Function Share runtime

| API | 路径 | 注解 |
| --- | ---- | ---- |
| Function | `pulsar-functions/api-java/.../functions/api/Function.java` | `@InterfaceStability.Stable`，签名 `Function<X, T>` |
| Source | `pulsar-io/core/.../io/core/Source.java`、`PushSource.java`、`AbstractPushSource.java` | |
| Sink | `pulsar-io/core/.../io/core/Sink.java` | |

> [!WARNING]
> **v1 API 已移除。** 全仓仅 1 个 `Function.java`，即 v2（`org.apache.pulsar.functions.api.Function`）。v1（`pulsar.functions.api.Function`，单参 `process`）**不存在**。旧资料说「v1/v2 并存」不准确。
>
> 同样**无 `functions/source`、`functions/sink` 包** —— `pulsar-functions/api-java/.../functions/` 下只有 `api` 一个子目录；Source/Sink 在 `pulsar-io/core`。

### pulsar-io Is a Connector Collection

`pulsar-io/` 含 `core` + **约 30 个 connector**（kafka / jdbc / redis / es / hbase 等）。`pulsar-io/core/.../io/core/` 里的类：`Source`、`Sink`、`PushSource`、`AbstractPushSource`、`SinkContext`、`SourceContext`、`BatchSourceTriggerer`。

> [!IMPORTANT]
> **Source/Sink 与 Function 共用 `RuntimeFactory` 体系**，由 `pulsar-io` 提供连接器实现。两者是同一套运行时、两套 API，不是一套两套。

> [!WARNING]
> **`pulsar-streams` 模块已被移除**（根目录无此目录），能力并入 `pulsar-io`。旧资料把 pulsar-streams 当作独立流处理模块的说法已过时。

## Windowed Functions

`pulsar-functions/instance/.../functions/windowing/`：`Window.java`（注解）、`WindowContextImpl.java`、**`WindowFunctionExecutor.java`**、`WindowManager`、`WindowImpl`、`EvictionPolicy`、`TriggerPolicy`、`WaterMarkEventGenerator`，加 `evictors/`、`triggers/` 子包。

API 侧：`api-java/.../api/WindowFunction.java`、`WindowContext.java`。

### Log Topic Mechanism

`pulsar-functions/instance/.../functions/instance/LogAppender.java`：

- 字段 `logTopic`（`:44`）
- 构造 `LogAppender(PulsarClient, String logTopic, String fqn, String instance)`（`:51`）
- 发送 `.topic(logTopic)`（`:115`）

根目录有 `run-logtopic-function.sh` 佐证。`GoInstanceConfig.java:45` 亦有 `logTopic = ""`。

> [!NOTE]
> **无 `PulsarLogger` 类** —— 旧资料提到的这个类不存在。

## Transactions

> [!IMPORTANT]
> **默认关闭**：`transactionCoordinatorEnabled = false`（`ServiceConfiguration.java:3756`）。

### TC Implementation Has Been Renamed

> [!WARNING]
> `TransactionCoordinatorImpl` **不存在**。`pulsar-broker/.../broker/transaction/` 下**无 `coordinator` 子包**（仅 `buffer` / `exception` / `pendingack` / `recover` / `timeout` / `util`）。
>
> 4.x 由 **`TransactionMetadataStoreService`**（`pulsar-broker/src/main/java/org/apache/pulsar/broker/TransactionMetadataStoreService.java`，注意在 `broker/` **根下**）替代，构造见 `PulsarService.java:1031`。

其他相关类：

| 类 | 位置 |
| -- | ---- |
| `TransactionBufferClientImpl` | `broker/transaction/buffer/impl/` |
| `TransactionBufferHandlerImpl` | 同上 |
| `SystemTopicTxnBufferSnapshotService` | ⚠️ **`broker/service/` 下**，非 transaction 包 |
| `TransactionBufferSnapshotServiceFactory` | 同上 |
| `TransactionCoordinatorClientImpl`、`TransactionImpl` | `pulsar-client/.../impl/transaction/` |

`pulsar-transaction/` 子模块**只有 `common` 和 `coordinator`**，且 `coordinator` 内是 TC 元数据存储（`MLTransactionMetadataStore` 等），**无 TC 服务实现**。

### State Machine: 7 States, Class Name Is Transaction.State

> [!WARNING]
> `org.apache.pulsar.transaction.impl.TransactionState` **不存在**。真实是 `pulsar-client-api/.../client/api/transaction/Transaction.java:32-79` 的**嵌套 enum `Transaction.State`**。

`Transaction.State`（`Transaction.java`）：

| 状态 | 行号 |
| ---- | ---- |
| `OPEN` | 39 |
| `COMMITTING` | 44 |
| `ABORTING` | 49 |
| `COMMITTED` | 55 |
| `ABORTED` | 60 |
| `ERROR`（异常态）| 72 |
| `TIME_OUT`（超时态）| 78 |

合法转换（源码注释即规格）：

```
commit: OPEN → COMMITTING → COMMITTED
        若 TC 侧已 ABORTED/ABORTING → ERROR        (:66-67)
abort:  OPEN → ABORTING → ABORTED
        若 TC 侧已 COMMITTED/COMMITTING → ERROR    (:69-70)
超时:   OPEN → TIME_OUT                             (:75-76)
```

客户端实现 `TransactionImpl.java`：`commit()`(184) 先 `checkState(OPEN, COMMITTING)`(186) 再置 `COMMITTING`(188)，失败回滚 `internalAbort`(191) 并可能置 `ERROR`(200)；`abort()`(215) 同构；`checkState`(264)。

### Two-phase Commit: commit marker Written to Ledger

```java
// pulsar-broker/.../transaction/buffer/impl/TopicTransactionBuffer.java:455-458
ByteBuf commitMarker = Markers.newTxnCommitMarker(-1L, txnID.getMostSigBits(), ...);
topic.getManagedLedger().asyncAddEntry(commitMarker, new AsyncCallbacks.AddEntryCallback() { ... });
```

marker 走普通 entry 写入路径 —— 即事务提交标记与其他消息一样追加到 ledger。

### Transaction Default Configuration

| 字段 | 默认值 | 行号 |
| ---- | ------ | ---- |
| `transactionCoordinatorEnabled` | **`false`** | 3756 |
| `transactionMetadataStoreProviderClassName` | `...MLTransactionMetadataStoreProvider` | 3762-3763 |
| `transactionBufferProviderClassName` | `...TopicTransactionBufferProvider` | 3769-3770 |
| `transactionPendingAckStoreProviderClassName` | `...MLPendingAckStoreProvider` | 3776-3777 |
| `transactionBufferSnapshotMaxTransactionCount` | 1000 | 3792 |
| `transactionBufferSnapshotMinTimeInMillis` | 5000 | 3800 |
| `transactionBufferSnapshotSegmentSize` | 262144（256 KB）| 3808 |
| `transactionBufferSegmentedSnapshotEnabled` | `false` | 3815 |
| `transactionBufferClientMaxConcurrentRequests` | 1000 | 3821 |
| `transactionBufferClientOperationTimeoutInMills` | 3000 | 3827 |
| `maxActiveTransactionsPerCoordinator` | 0L（无限制）| 3833 |
| `transactionPendingAckLogIndexMinLag` | 500 | 3842 |
| `transactionLogBatchedWriteEnabled` | `false` | 3851 |
| `transactionLogBatchedWriteMaxRecords` | 512 | 3858 |
| `transactionLogBatchedWriteMaxSize` | 4 MB | 3865 |
| `transactionPendingAckBatchedWriteEnabled` | `false` | 3882 |
| `numTransactionReplayThreadPoolSize` | `availableProcessors()` | 3784 |

> [!WARNING]
> 三个不存在的老配置名：
> - `transactionBufferSnapshotServiceEnabled` —— 不存在，改由 `transactionCoordinatorEnabled` + provider 类名决定
> - `transactionSnapshotPeriodSeconds` —— 不存在，对应的是**分段快照**机制（`transactionBufferSnapshotMinTimeInMillis=5000` + `...MaxTransactionCount=1000`）
> - `transactionMaxPendingAck` —— 不存在

### Internal Transaction topic Constants

`pulsar-common/.../common/naming/SystemTopicNames.java`：

| 常量 | 值 | 行号 |
| ---- | -- | ---- |
| `TRANSACTION_BUFFER_SNAPSHOT` | `__transaction_buffer_snapshot` | 38 |
| `TRANSACTION_BUFFER_SNAPSHOT_SEGMENTS` | `__transaction_buffer_snapshot_segments` | 43 |
| `TRANSACTION_BUFFER_SNAPSHOT_INDEXES` | `__transaction_buffer_snapshot_indexes` | 48 |
| `PENDING_ACK_STORE_SUFFIX` | `__transaction_pending_ack` | 50 |
| `PENDING_ACK_STORE_CURSOR_NAME` | `__pending_ack_state` | 52 |
| `TRANSACTION_COORDINATOR_ASSIGN` | `persistent://pulsar/system/transaction_coordinator_assign` | 67-68 |
| `TRANSACTION_COORDINATOR_LOG` | `persistent://pulsar/system/__transaction_log_` | 70-71 |
| `NAMESPACE_EVENTS_LOCAL_NAME` | `__change_events` | 33 |

> [!WARNING]
> `TRANSACTION_COORDINATOR_SNAPSHOT` **不存在** —— 正确是 `TRANSACTION_BUFFER_SNAPSHOT`（`:38`）。
>
> 所有事务 topic 落在 `pulsar/system`（`NamespaceName.SYSTEM_NAMESPACE`）。

## Idempotent Producer: The Switch Itself Has Been Removed

> [!IMPORTANT]
> **这是本篇最反直觉的发现**：4.2.4 中 **幂等开关已被彻底移除**，不是「默认开」也不是「默认关」。
>
> 核实证据：
> - 全仓 `grep -rli "idempoten"` 仅命中 8 个文件，且命中的是**内部方法名**（如 `PersistentTopic`、`TopicPolicyListenerWrapper` 里的去重逻辑），**不是客户端配置**
> - `ProducerBuilder` / `ProducerConfigurationData` **无 `enableIdempotence` 字段**
> - `ClientBuilderData.java` **文件已不存在**（`ProducerConfigurationData` 是唯一生产者配置类）
> - `DEFAULT_IDEMPOTENCE` 常量 **0 命中**

替代机制是 **`ProducerAccessMode`**（`pulsar-client-api/.../client/api/ProducerAccessMode.java:24-45`）：

| 值 | 语义 | 行号 |
| -- | ---- | ---- |
| `Shared` | **默认**，多生产者可发 | 28 |
| `Exclusive` | 需独占，已有 producer 立即失败 | 33 |
| `ExclusiveWithFencing` | 抢占独占，踢掉并作废旧 producer | 39 |
| `WaitForExclusive` | 阻塞等待直到获得独占 | 44 |

默认值：`ProducerConfigurationData.java:207` → `accessMode = ProducerAccessMode.Shared`。

> [!TIP]
> 去重实际由 namespace/topic 策略驱动：`brokerDeduplicationEnabled = false`（`ServiceConfiguration:911`）+ `brokerDeduplicationMaxNumberOfProducers = 10000`（`:917`），状态机见 `persistent/MessageDeduplication.java:65,140,156-228`。
>
> 所以问题「4.x 是否默认开启幂等」的答案是：**该开关已不存在，问题本身失效**。

## Delivery Semantics

| 场景 | 语义 | 依据 |
| ---- | ---- | ---- |
| 普通订阅 | **at-least-once** | `readPosition` 在读时推进（`OpReadEntry.java:181-184`），投递后崩溃会从 `markDeletePosition` 重读重复 |
| 事务订阅（TC 开启 + 事务 API） | effectively-once | `pulsar-transaction/coordinator` 提供 TC |
| 幂等 producer | 由 `accessMode` + broker 去重策略驱动 | 见上 |

> [!WARNING]
> 笼统说「Pulsar 是 exactly-once」是**错误的**。准确表述：普通非事务订阅是 at-least-once，仅在事务订阅范围内提供 exactly-once 效果，且需 `transactionCoordinatorEnabled=true`（默认关闭）。

## Practical Selection

| 需求 | 方案 | 说明 |
| ---- | ---- | ---- |
| 轻量状态转换、协议适配 | **Pulsar Functions**（Thread runtime）| 无需独立集群 |
| 需要独立进程隔离 | Functions（Process runtime）| 独立 java 子进程 |
| 已在 K8s、需要弹性 | Functions（K8s runtime）| Pod 编排 |
| 数据库/ES/Redis 接入 | **pulsar-io connector** | 与 Function 共用 runtime |
| 复杂有状态流计算 | **Flink**（见 [Flink](/docs/CS/Framework/Flink/Flink.md)）| Functions 状态能力有限 |
| 跨集群/跨地域复制 | 4.x 已移除内置方案 | 需 MirrorMaker 或自研 |

> [!IMPORTANT]
> Pulsar Functions 4.2.4 中**仍是完整可用的独立子系统**（9 个子模块、独立 WorkerConfig、3 个 JVM runtime + K8S、NAR 打包、`pulsar-package-management` 集成），**不能简单说「已废弃」**。
>
> 但确有两处收缩：① Go runtime 移除（`pulsar-function-go` 退化为纯 SDK）；② `pulsar-streams` 移除。
>
> 是否仍在官方 roadmap 上积极维护属**项目状态判断、非源码可核实** —— 4.2.4 tarball 内无 release notes / roadmap（`site2/` 目录不存在），**未查到**，建议查 Apache 官方 4.x 发布说明佐证。

## Common Claims That Need Debunking

| 说法 | 4.2.4 实况 |
| ---- | --------- |
| 「`ProducerBuilder.enableIdempotence()` 可开关幂等」 | ❌ **API 与配置字段双双消失**，改为 `ProducerAccessMode` |
| 「4.x 幂等默认开启」 | ❌ 开关已不存在，问题失效 |
| 「`FunctionsWorker` 有 `GoRuntimeFactory`」 | ❌ `pulsar-function-go` 仅 Go SDK，无 Java runtime |
| 「`pulsar-streams` 是 Pulsar 的流处理模块」 | ❌ 模块已删，并入 `pulsar-io` |
| 「Functions v1/v2 API 并存」 | ❌ 仅 v2 |
| 「`functionRuntimeFactoryConfig` 默认 `{"threads":8}`」 | ❌ 复数 `functionRuntimeFactoryConfigs`（Map 类型），默认值未查到 |
| 「`functionDirectory` 是 Functions 配置项」 | ❌ 不存在，是 `downloadDirectory` |
| 「runtime 有隐式默认，不配也能跑」 | ❌ 三者皆空时直接抛 `RuntimeException` |
| 「TC 快照由 `transactionBufferSnapshotServiceEnabled` 控制」 | ❌ 不存在，改由分段快照参数驱动 |
| 「有 `TRANSACTION_COORDINATOR_SNAPSHOT` topic」 | ❌ 正确是 `TRANSACTION_BUFFER_SNAPSHOT` |
| 「Pulsar Functions 是已废弃功能」 | ❌ 仍是完整子系统，仅 Go runtime 与 pulsar-streams 收缩 |
| 「`PulsarLogger` 是日志 topic 的类」 | ❌ 不存在，真实是 `LogAppender` |

## List Not Found

- `functionRuntimeFactoryConfigs` 的 `{"threads":8}` 默认值（源码与 yml 均无）
- `numFunctionPackageReplicas` 在 `WorkerConfig` 的字段级默认值（仅 yml 中为 1）
- `ProcessRuntimeFactory` vs `ThreadRuntimeFactory` 进程模型的**显式源码对比说明**（类继承关系已确认，但源码无对比描述）
- Pulsar Functions 4.x 维护状态 roadmap（tarball 内无文档）

## Links

- [Pulsar](/docs/CS/MQ/Pulsar/Pulsar.md)
- [Broker](/docs/CS/MQ/Pulsar/Broker.md)
- [BookKeeper 存储层](/docs/CS/MQ/Pulsar/BookKeeper.md)
- [集群复制与分层存储](/docs/CS/MQ/Pulsar/Cluster.md)
- [Flink](/docs/CS/Framework/Flink/Flink.md)
- [Kafka Streams](/docs/CS/MQ/Kafka/Streams.md)

## References

1. [Apache Pulsar 4.2.4 Release](https://github.com/apache/pulsar/releases/tag/v4.2.4)
2. [WorkerConfig.java (v4.2.4)](https://github.com/apache/pulsar/blob/v4.2.4/pulsar-functions/runtime/src/main/java/org/apache/pulsar/functions/worker/WorkerConfig.java)
3. [Transaction.java (v4.2.4)](https://github.com/apache/pulsar/blob/v4.2.4/pulsar-client-api/src/main/java/org/apache/pulsar/client/api/transaction/Transaction.java)
4. [SystemTopicNames.java (v4.2.4)](https://github.com/apache/pulsar/blob/v4.2.4/pulsar-common/src/main/java/org/apache/pulsar/common/naming/SystemTopicNames.java)
