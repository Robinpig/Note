## Introduction

Pulsar 的集群能力围绕一个核心抽象展开：**namespace 级的 bundle 切分 + 独立负载均衡器**。Broker 无状态，topic 归属由 metadata store 记录，可以随时 unload 并在别处重新加载。4.x 起默认负载均衡器换成 `ModularLoadManagerImpl`，并支持通过 `loadbalance/extensions/` 扩展。

> 版本基线：**4.2.4**（tag `v4.2.4`）。

## Multi-tenant Three-level Model

```
cluster
└── tenant          （账号/项目级，adminRoles + allowedClusters）
    └── namespace   （虚拟队列集合，bundle 切分的单位）
        └── topic   （persistent / non-persistent / partitioned）
```

### Metadata key: tenant and namespace Share One Tree

> [!WARNING]
> 旧资料常写 `/admin/namespaces`、`/admin/persistent`、`LOCAL_`/`GLOBAL_` 前缀 —— **4.2.4 中全不存在**。真实只有两个常量（`pulsar-broker-common/.../broker/resources/BaseResources.java:52-53`）：
> ```java
> protected static final String BASE_POLICIES_PATH = "/admin/policies";
> protected static final String BASE_CLUSTERS_PATH = "/admin/clusters";
> ```

| 资源 | 路径 | 出处 |
| ---- | ---- | ---- |
| tenant | `/admin/policies/{tenant}` | `TenantResources.java:69` |
| namespace | `/admin/policies/{tenant}/{namespace}` | `NamespaceResources.java:89` |
| 租户列表 | `getChildren(BASE_POLICIES_PATH)` | `TenantResources.java:41` |
| 分区元数据 | `/admin/partitioned-topics` | `NamespaceResources.java:258` |
| **bundle 归属** | `/namespace/{tenant}/{ns}/{hash}` | `ServiceUnitUtils.java:37-42` |
| broker 负载上报 | `/loadbalance/brokers` | `LoadManager.java:53` |
| 只读标记 | `/admin/flags/policies-readonly` | `NamespaceResources.java:55` |

> [!TIP]
> bundle 归属在**独立的 ephemeral 树** `/namespace/...`，与 `/admin/policies` 分开。设计上的好处是 unload 时归属信息能保留（ephemeral 节点随 broker 存活），恢复后能重新接管。

### Two Data Classes

`TenantInfo`（`pulsar-client-admin-api/.../policies/data/TenantInfo.java:24-33`）只有 2 个字段：

```java
getAdminRoles()  getAllowedClusters()
```

`NamespaceOwnershipStatus`（`NamespaceOwnershipStatus.java:24-31`）只有 3 个公有字段：

```java
public BrokerAssignment broker_assignment;
public boolean is_controlled;
public boolean is_active;
```

> [!WARNING]
> **字段名是下划线风格**（`is_controlled` / `is_active`），不是驼峰。`isAssigned` 字段**不存在**。赋值见 `NamespaceService.java:924-938`。

### tiered namespace Does Not Exist

> [!WARNING]
> `SystemTopicNames.TIERED_NAMESPACE_TOPIC` **不存在**，tiered namespace 这个概念在 4.2.4 中**全仓零命中**（`tierStoragePolicies` / `TIERED_NAMESPACE_TOPIC` / `tiered_namespace` 全部 0 命中）。
>
> 4.2.4 的分层存储配置是 `OffloadPolicies`（`pulsar-client-admin-api/.../data/OffloadPolicies.java:23`），走 **driver 名 + 阈值**，不是策略名引用。详见 [BookKeeper 存储分层](/docs/CS/MQ/Pulsar/BookKeeper.md) 与本文「分层存储」一节。

## Bundle Splitting

`NamespaceBundleFactory` 的实际位置：**`pulsar-broker/src/main/java/org/apache/pulsar/common/naming/NamespaceBundleFactory.java`** —— 包名是 `org.apache.pulsar.common.naming`，但**物理在 `pulsar-broker` 模块**（不是 `pulsar-common`，这是 3.x→4.x 的模块迁移）。

### hash Range Encoding

```java
// NamespaceBundle.java:51
this.bundleRange = String.format("0x%08x_0x%08x",
        keyRange.lowerEndpoint(), keyRange.upperEndpoint());
```

- 边界常量 `Policies.java:75-76`：`FIRST_BOUNDARY = "0x00000000"`、`LAST_BOUNDARY = "0xffffffff"`
- 哈希函数 `NamespaceBundleFactory.java:303-304`：`hashFunc.hashString(name, UTF_8).padToLong()`（Guava `HashFunction`）
- 区间**半开**语义（`NamespaceBundle.java:40-47`）：下界必 CLOSED，上界除 `0xffffffff` 外必 OPEN

所以形如 `0x00000000_0x7fffffff` 的 bundle 覆盖前一半 hash 空间。namespace 下的 topic 名做 hash 后落入哪个区间，就归哪个 bundle。

> [!TIP]
> 拆分边界存在 metadata store（`BundlesData`，`pulsar-client-admin-api/.../data/BundlesData.java:27-30`，字段 `boundaries` / `numBundles`）。注意与 `org.apache.pulsar.policies.data.loadbalancer.BundleData`（`pulsar-common`）区分 —— 后者是**负载均衡统计数据**，与 hash 范围无关。
>
> `NamespaceBundleData` 这个类名**不存在**，已更名 `BundlesData`。

## Load Balancing

### 4.x Defaults to ModularLoadManager

```java
// ServiceConfiguration.java:3053
private String loadManagerClassName = "org.apache.pulsar.broker.loadbalance.impl.ModularLoadManagerImpl";
```

配套配置：

| 字段 | 默认值 | 行号 |
| ---- | ------ | ---- |
| `loadBalancerEnabled` | `true` | 2683 |
| `loadBalancerSheddingEnabled` | `true` | 2745 |
| `loadBalancerBrokerOverloadedThresholdPercentage` | 85 | 2787 |
| `loadManagerClassName` | `ModularLoadManagerImpl` | 3053 |

`LoadManager` 接口（`pulsar-broker/.../loadbalance/LoadManager.java:50`）关键方法：`getLeastLoaded`(69)、`findBrokerServiceUrl`(71)、`checkOwnershipAsync`(76)、`generateLoadReport`(83)。

> [!WARNING]
> `RandomDistributionPolicy`（旧版默认策略）**不存在**；`BundleBrokerSelector` / `BrokerVersion` 也不存在。`LookupResult` 路径为 `pulsar-broker/.../broker/lookup/LookupResult.java`。
>
> 4.x 另有 `loadbalance/extensions/` 提供 `ExtensibleLoadManager` / `ExtensibleLoadManagerImpl` 作为扩展点。

### Overload Protection Is the LoadSheddingStrategy Family

> [!WARNING]
> `OverloadSheddingService` / `BrokerService#isOverloaded` / `LoadManager#getOverloadedBroker` **均不存在**（旧资料常提）。
>
> 真实实现在 `pulsar-broker/.../loadbalance/`：`OverloadShedder.java`、`ThresholdShedder.java`、`AvgShedder.java`、`UniformLoadShedder.java`，判定基于 `loadBalancerBrokerOverloadedThresholdPercentage`（85%），见 `OverloadShedder.java:68`。
>
> 另有一路独立的 producer 生产限流 `ServerCnxThrottleTracker`（`broker/service/`）。

## Unload and Bundle Transfer

### Two Independent Paths

> [!IMPORTANT]
> **topic 级 unload 与 bundle 级 unload 是两条不同的路**，旧资料常混为一谈。

**topic 级 unload**（`PersistentTopicsBase.java:1139-1146`）—— **不经过 NamespaceService**：

```java
validateTopicOwnershipAsync(topicName, authoritative)
        .thenCompose(__ -> getTopicReferenceAsync(topicName))
        .thenCompose(topic -> topic.close(false));   // ← 直接关 topic
```

分区 topic 逐分区调 admin `unloadAsync`（`:947`）；TC assign topic 特判走 `internalUnloadTransactionCoordinatorAsync`（`:1157`）。

**bundle 级 unload** 方法名是 **`unloadNamespaceBundle`**（不是 `unloadBundle`），`NamespaceService.java:868-884`，核心 `ob.handleUnloadRequest(...)`（`:882`）。

> [!WARNING]
> - `BrokerService.unloadBundle` **不存在**。
> - **unload 时不显式持久化 cursor 状态** —— cursor 状态由 managed-ledger 自行持久化到 ledger，unload 路径中未见显式持久化调用。旧资料说「unload 会持久化 cursor 到 ledger」不准确。

### Data Readability

归属 ephemeral 节点在 metadata store，ledger 数据在 bookie。`isNamespaceBundleOwned`(886) 读 `/namespace/...` 存在性；`is_controlled` 表达是否受隔离策略管控。

即 unload 后随时可被任何 broker 重新加载并继续读 —— 这是「计算无状态」的直接收益。

## Broker Startup Order

`PulsarService#start`（`pulsar-broker/.../broker/PulsarService.java:841-1112`）：

```
841  start() 入口，state 必须为 Init
859  校验 webServicePort/webServicePortTls 必须存在
888  OpenTelemetry *Stats 初始化
897  createLocalMetadataStore            ← 本地元数据
903  configurationMetadataStore（可分离）
914  newPulsarResources
919  ProtocolHandlers.load / initialize
923  newBookKeeperClientFactory
925  newManagedLedgerStorage
927  newBrokerService
930  LoadManager.create                  ← loadManager 先建
933  startNamespaceService
935  createAndStartSchemaStorage
939  OffloadPoliciesImpl.create
948  createManagedLedgerOffloader → 默认 NullLedgerOffloader
957  brokerService.start()
962  new WebService → 965 start()       ← Web 服务
968  回填动态端口（brokerServicePort 0 → 实际值）
981  createBrokerId                      ← brokerId = host:webPort
998  nsService.initialize()
1001 startLeaderElectionService()
1009 startLoadManagementService()        ← broker 注册（创建 ephemeral 节点）
1012 initTopicPoliciesService + start    ← topic 加载
1016 nsService.registerBootstrapNamespaces()
1019 if (transactionCoordinatorEnabled) → TC 元数据/缓冲/pendingAck provider
1061 protocolHandlers.start
1066 acquireSLANamespace()
1069 startWorkerService(...)             ← functions worker 最后
1103 state = State.Started
```

> [!TIP]
> 注意 **broker 注册在 topic 加载之前**（1009 → 1012），保证 broker 接管 topic 时已可被负载均衡器发现。
>
> 类名包名：`org.apache.pulsar.PulsarService`（2.x）→ **`org.apache.pulsar.broker.PulsarService`**（4.x）。

## Ports and Key Configuration

| 字段 | 默认值 | 行号 | 备注 |
| ---- | ------ | ---- | ---- |
| `brokerServicePort` | `Optional.of(6650)` | 177 | ⚠️ **`Optional<Integer>`**，非 int |
| `brokerServicePortTls` | `Optional.empty()` | 183 | `Optional` 类型 |
| `webServicePort` | `Optional.of(8080)` | 188 | `Optional` |
| `webServicePortTls` | `Optional.empty()` | 193 | `Optional` |
| `numExecutorThreadPoolSize` | `availableProcessors()` | 312 | ❌ 无 `executorServicePoolSize` |
| `functionsWorkerEnabled` | `false` | 3626 | |
| `brokerDeduplicationEnabled` | `false` | 911 | |
| `brokerDeduplicationMaxNumberOfProducers` | `10000` | 917 | |
| `maxMessageSize` | `5 * 1024 * 1024` | 1590 | 来自 `Commands.DEFAULT_MAX_MESSAGE_SIZE`（`Commands.java:123`）|
| `brokerDeleteInactiveTopicsEnabled` | **`true`** | 736 | |
| `topicLevelPoliciesEnabled` | `true` | 1758 | |

> [!WARNING]
> **4.2.4 没有 `brokerClientPort` / `brokerClientTlsPort` 字段**（已 grep 确认）。4.x 用 `brokerServicePort` + TLS 变体表达双绑定。旧资料说「brokerClientPort 默认 6651」不适用 4.x。
>
> `brokerDeleteInactiveTopicsEnabled` 默认是 **`true`**（旧资料常说 false）。

### Rate Limiting and Quota Defaults

| 字段 | 默认值 | 行号 | 备注 |
| ---- | ------ | ---- | ---- |
| `backlogQuotaDefaultLimitBytes` | `-1` | 696 | ❌ **无 `backlogQuotaMap`**，改为标量 |
| `backlogQuotaDefaultLimitGB` | `-1` | 689 | `@Deprecated` |
| `backlogQuotaDefaultLimitSecond` | `-1` | 703 | 时间配额 |
| `backlogQuotaDefaultRetentionPolicy` | `producer_request_hold` | 713-714 | |
| `backlogQuotaCheckIntervalInSeconds` | 60 | 682 | |
| `retentionCheckIntervalInSeconds` | 120 | 1640 | |
| `maxTopicsPerNamespace` | 0（0 = 禁用） | 971 | |
| `maxConsumersPerTopic` | 0（0 = 禁用） | 1561 | |
| `maxSubscriptionsPerTopic` | 0（0 = 禁用） | 1577 | |
| `maxUnackedMessagesPerConsumer` | **`50000`** | 1064 | ❌ 旧资料称 -1 |
| `maxUnackedMessagesPerSubscription` | **`4 * 50000` = 200000** | 1072 | ❌ 旧资料称 -1 |
| `maxUnackedMessagesPerSubscriptionOnBrokerBlocked` | 0.16 | 1126 | 达到水位即阻塞 |
| `dispatcherPauseOnAckStatePersistentEnabled` | `false` | 2568 | |
| `replicationProducerQueueSize` | 1000 | 3318 | |

> [!IMPORTANT]
> 三个容易记错的默认值：
> - `maxUnackedMessagesPerConsumer` = **50000**（不是 -1）
> - `maxUnackedMessagesPerSubscription` = **200000**（是前者的 4 倍，不是 -1）
> - **无 `backlogQuotaMap`**，4.x 改为标量 `backlogQuotaDefaultLimitBytes` 等
>
> `maxConsumerCountPerTopic` / `maxProducerCountPerTopic` 在 `ServiceConfiguration` 中**不存在**（未查到）。

## Replication

### Package Path Moved Up, Deduplication Variants Simplified

> [!WARNING]
> `pulsar-broker/src/main/java/org/apache/pulsar/broker/replication/` 目录**不存在**，类已上移到 `broker/service/`。

| 类 | 4.2.4 位置 |
| -- | ---------- |
| `Replicator`（接口） | `broker/service/Replicator.java:26` |
| `AbstractReplicator` | `broker/service/AbstractReplicator.java` |
| `PersistentReplicator`（**abstract class**，83 行） | `broker/service/persistent/PersistentReplicator.java` |

`ReplicatorState` 被 `AbstractReplicator.State` 取代（`:93-114`）：

```java
public enum State {
    Disconnected,   // 内部 producer 断开（兼表 Init 语义，见 :95-98 注释）
    Starting,       // 正在创建 producer
    Started,        // 已启动并复制
    Disconnecting,  // 正在断开
    Terminating,    // 终止中
    Terminated      // 永不再用，重启用时新建 Replicator
}
```

初始状态 `STATE_UPDATER.set(this, State.Disconnected)`（`:145`）。

> [!WARNING]
> `MessageIdReplicator` / `NonDeduplicatingMessageIdReplicator` **均不存在**。`PersistentReplicator` 现为 abstract，只有两个子类：
> - `GeoPersistentReplicator`（`persistent/GeoPersistentReplicator.java:41`）
> - `ShadowReplicator`（`persistent/ShadowReplicator.java:40`）
>
> 去重改为在 `MessageDeduplication` 内按 `Producer.isRemoteOrShadow(...)` 分支（`persistent/MessageDeduplication.java:287-290`），不再靠子类区分。

### Cross-region Replication and Backup Have Been Removed

> [!IMPORTANT]
> **4.2.4 确认移除了以下能力**（全仓零命中）：
>
> | 能力 | 状态 |
> | ---- | ---- |
> | `pulsar-replication` 模块 | ❌ 目录不存在，根 pom 无任何 replication module 声明 |
> | `PulsarGeoReplicationGroupCoordinator` | ❌ 0 命中 |
> | `PulsarReplication` / `GeoReplicationStatus` | ❌ 0 命中 |
> | `PulsarBackup` / `PulsarClientBackup` | ❌ 0 命中 |
> | `backupVersion` 配置 | ❌ 0 命中 |
>
> 这是 4.x 相对 2.x/3.x 的**重大功能收缩**。跨地域复制需另用 MirrorMaker（Kafka 侧）或自研方案；备份需靠 BookKeeper 层的 ledger 复制 + HDFS/S3 侧能力。

保留的跨集群配置是 metadata 层：`configurationStoreServers`(161) 与 `configurationMetadataStoreUrl`(168) 并存，解析优先级见 `:4153-4156`（后者优先，回落前者）。

## Tiered Storage (Offload)

### SPI Has Been Replaced by NAR

> [!WARNING]
> 旧资料列的 `TieredStorageProvider` / `TieredStoragePolicyConfig` / `StoragePolicy` / `TieredStoragePolicies` / `ManagedLedgerStorageConfiguration` / `OffloadPolicyContext` **全部不存在**；`pulsar/broker/tieredstorage/` 与 `pulsar/broker/offload/` 两个包也都不存在。
>
> 4.2.4 真实接口在 **`managed-ledger` 模块**的 `org.apache.bookkeeper.mledger.*`：
> - `OffloadPolicies`（`pulsar-client-admin-api/.../data/OffloadPolicies.java:23`）—— 仍是 driver 名 + 阈值，**不是策略名引用**
> - `Offloaders` / `OffloadersCache` / `Offloaders.NAR`（`managed-ledger/.../mledger/offload/`）—— **NAR SPI**，`Offloaders.NAR` 的 `OffloadDefinition` 三字段：`name` / `description` / `offloaderFactoryClass`
> - `NullLedgerOffloader`、`NonAppendableLedgerOffloader`、`LedgerOffloaderStatsImpl`、`OffloadSegmentInfoImpl`（`managed-ledger/.../impl/`）
> - `LedgerOffloader` / `LedgerOffloaderFactory` 接口本体在 **BookKeeper 上游仓库**，不在 Pulsar tarball 内
>
> 驱动装配走 NAR 加载：`PulsarService.java:1646-1684`，`offloaders.getOffloaderFactory(driver)`（`:1658`），未配置时用 `NullLedgerOffloader.INSTANCE`（`:1679`）。

### Trigger Timing: Not a Periodic Task, but a ledger Close Event

> [!IMPORTANT]
> `OffloadManager` / `OffloadScheduler` / `OffloadProcessor` **全部不存在**。4.2.4 改为**事件驱动**：
>
> ```
> 触发点1：ManagedLedgerImpl.java:1991  —— ledger 关闭后
>     trimConsumedLedgersInBackground();
>     maybeOffloadInBackground(AUTOMATIC_OFFLOAD_TRIGGER);   ← 这里
>
> 触发点2：ManagedLedgerFactoryImpl.java:489-490 —— topic 首次加载完成时
>     if (config.isTriggerOffloadOnTopicLoad()) { ... }
>     对应配置 managedLedgerTriggerOffloadOnTopicLoad，默认 false（ServiceConfiguration:2480）
>
> 执行：maybeOffloadInBackground(2844) → getOffloadThresholds() 为空则直接完成
>       → executor.execute(maybeOffload)
> ```
>
> `OffloadRequestSource` 是 **private 嵌套 enum** `{AUTOMATIC, EXPLICIT}`（`:233-236`），`OffloadThresholds` 是 **private record**（`:238`）。
>
> 并发合并由 `AutomaticOffloadTriggerController`（`:86`）保证，**三态 CAS**：`IDLE` / `RUNNING` / `RUNNING_WITH_PENDING_TRIGGER` —— 即「至多一个运行 + 一个合并的后续」。

### Threshold Semantics

```java
// ManagedLedgerImpl.java:2862-2878
Optional<OffloadPolicies> p = getOffloadPoliciesIfAppendable();
long bytes   = Optional.ofNullable(p.getManagedLedgerOffloadThresholdInBytes()).orElse(-1L);
long seconds = Optional.ofNullable(p.getManagedLedgerOffloadThresholdInSeconds()).orElse(-1L);
if (bytes >= 0 || seconds >= 0) return Optional.of(new OffloadThresholds(bytes, seconds));
return Optional.empty();   // → 不触发
```

> [!WARNING]
> `managedLedgerOffloadThresholdInSeconds = -1` **不只是「禁用」**：
> - -1 只表示**不按时间/大小触发**
> - 还需 `managedLedgerOffloadDriver != null`（默认 `null`，`:3684`）才可能 offload
> - 双 -1 时 `maybeOffload` 会**抛 `IllegalArgumentException`**（`:2897-2899`），日志文案明确点名这两个字段
>
> ❌ `isTieredStorageEnabled` 方法在 4.2.4 **不存在**（全仓零命中）。

### Offload Default Configuration

| 字段 | 默认值 | 行号 |
| ---- | ------ | ---- |
| `managedLedgerOffloadDriver` | `null` | 3684 |
| `managedLedgerOffloadMaxThreads` | **2** | 3690 |
| `managedLedgerOffloadReadThreads` | 2 | 3696 |
| `managedLedgerOffloadPrefetchRounds` | 1 | 3708 |
| `managedLedgerOffloadDeletionLagMs` | `TimeUnit.HOURS.toMillis(4)` = 4 小时 | 2465 |
| `managedLedgerOffloadThresholdInSeconds` | `-1L` | 2475 |
| `managedLedgerOffloadAutoTriggerSizeThresholdBytes` | `-1L` | 2470 |
| `offloadersDirectory` | `"./offloaders"` | 3678 |
| `narExtractionDirectory` | `NarClassLoader.DEFAULT_NAR_EXTRACTION_DIR` | 3702 |
| `managedLedgerInactiveOffloadedLedgerEvictionTimeSeconds` | 600 | 3724 |
| `managedLedgerDataReadPriority` | `TIERED_STORAGE_FIRST` | 2627 |

> [!WARNING]
> **没有 `offloadMaxThreads` 这个配置名** —— 真实是 `managedLedgerOffloadMaxThreads`（默认 **2**，不是旧资料的 4/8）。

### Built-in offload Implementation

> [!WARNING]
> `tiered-storage/` 目录下**只有 2 个子模块，且没有 HDFS**：

| 目录 | 实现 |
| ---- | ---- |
| `tiered-storage/jcloud`（**非 `jclouds`**） | `JCloudLedgerOffloaderFactory`、`BlobStoreManagedLedgerOffloader`、OffloadIndexBlock V1/V2 |
| `tiered-storage/file-system` | `FileSystemLedgerOffloaderFactory`、`FileSystemManagedLedgerOffloader` |

根级另有 `jclouds-shaded/` 目录。旧资料说的 `tiered-storage/hdfs` 不存在。

## Architectural Comparison with Kafka

| 维度 | Pulsar | Kafka |
| ---- | ------ | ---- |
| 存储单元 | BookKeeper **ledger**（可跨节点分布） | **partition**（单 broker 本地磁盘）|
| 消息写入 | 一条消息 = 一个 entry，追加写 | 追加写 |
| 扩容方式 | **加 bookie**（存储层水平扩） | 加 broker（同时承担存储）|
| 扩容粒度 | 细到 **namespace 级别**（bundle 转移） | 只能整 topic 增分区 |
| 负载均衡 | 独立 LoadManager，按 **bundle** 动态均衡 | 客户端/分配器按 partition |
| 卸载 | **unload topic** 即释放 broker 内存，数据不动 | 只能停进程，partition 数据绑定 broker |
| 消费位点 | **cursor**，独立于消息存储 | offset 存在 `__consumer_offsets` |
| 消息删除 | 单条可删（ack 时写 delete marker） | 只能按 offset 截断（log retention）|
| 多租户 | 强（tenant/namespace/topic + bundle 隔离） | 弱（靠 topic 名约定）|
| 跨集群复制 | 4.x **已移除**，需外部方案 | MirrorMaker 2 成熟 |
| 延迟退读 | 分层存储（tiered storage）| 需自建 |

## Common Claims That Need Debunking

| 说法 | 4.2.4 实况 |
| ---- | --------- |
| 「用 `pulsar-replication` 做跨地域复制」 | ❌ 模块与类全无。`PulsarGeoReplicationGroupCoordinator` 不存在 |
| 「geo-replication 用 `GeoReplicationStatus` 配」 | ❌ 无此类 |
| 「用 `PulsarClientBackup` 做备份恢复」 | ❌ 类与 `backupVersion` 配置均已删除 |
| 「元数据默认存 RocksDB」 | ❌ **默认回退是 ZK**（`MetadataStoreFactoryImpl.java:97`）。`rocksdb://` 需显式配置 |
| 「`maxUnackedMessagesPerConsumer` 默认 -1」 | ❌ **50000** |
| 「`maxUnackedMessagesPerSubscription` 默认 -1」 | ❌ **200000** |
| 「`brokerDeleteInactiveTopicsEnabled` 默认 false」 | ❌ **true** |
| 「`backlogQuotaMap` 有 `default` 键」 | ❌ 无该 Map，改为标量 |
| 「`offloadMaxThreads` 默认 4/8」 | ❌ `managedLedgerOffloadMaxThreads=2` |
| 「broker 有 `brokerClientPort=6651`」 | ❌ 4.x 无此字段 |
| 「`RandomDistributionPolicy` 是一种负载均衡策略」 | ❌ 类不存在 |
| 「`OverloadSheddingService` / `isOverloaded`」 | ❌ 改为 `LoadSheddingStrategy` 家族 |
| 「offload 由 broker 周期任务扫描触发」 | ❌ 改为 **ledger 关闭事件驱动** |
| 「`tiered-storage/hdfs` 提供 HDFS offload」 | ❌ 只有 `jcloud` 与 `file-system` |
| 「有 tiered namespace」 | ❌ 概念不存在 |
| 「unload topic 会持久化 cursor 状态」 | ❌ 未查到显式持久化调用，unload 即 `topic.close(false)` |

## List Not Found

- `brokerDeleteInactiveTopicsIntervalSeconds` 字段本体（`:789` 仅注释提及 86400 秒 = 24h 默认值，字段未在 `ServiceConfiguration` 中定位到）
- `maxConsumerCountPerTopic` / `maxProducerCountPerTopic`（`ServiceConfiguration` 中不存在）
- `SystemTopicNames.TIERED_NAMESPACE_TOPIC` 与 tiered namespace 概念

## Links

- [Pulsar](/docs/CS/MQ/Pulsar/Pulsar.md)
- [Broker](/docs/CS/MQ/Pulsar/Broker.md)
- [BookKeeper 存储层](/docs/CS/MQ/Pulsar/BookKeeper.md)
- [Consumer](/docs/CS/MQ/Pulsar/Consumer.md)
- [Functions 与事务](/docs/CS/MQ/Pulsar/Functions.md)
- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)

## References

1. [Apache Pulsar 4.2.4 Release](https://github.com/apache/pulsar/releases/tag/v4.2.4)
2. [ServiceConfiguration.java (v4.2.4)](https://github.com/apache/pulsar/blob/v4.2.4/pulsar-broker-common/src/main/java/org/apache/pulsar/broker/ServiceConfiguration.java)
3. [PulsarService.java (v4.2.4)](https://github.com/apache/pulsar/blob/v4.2.4/pulsar-broker/src/main/java/org/apache/pulsar/broker/PulsarService.java)
4. [Pulsar 官方文档](https://pulsar.apache.org/docs/)
