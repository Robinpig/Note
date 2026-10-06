## Introduction

RocketMQ 5.x 的架构改动主线只有一条：**把 Broker 的计算职责剥离成无状态 Proxy，让存储可以独立弹性扩缩**。计算与存储解耦后，云厂商的弹性策略（按需扩计算、按需扩存储）才能真正生效。

> 版本基线：**5.5.1**（tag `rocketmq-all-5.5.1`，2026-08-20 发布，为当前最新 release）。
> ⚠️ `master` 分支 `pom.xml` 的 `<version>` 是 **5.3.3**，不是 5.5.x —— 引用 master 结论时务必注明。

5.0 引入了全新的弹性无状态代理模式，把 Broker 职责拆分：客户端协议适配、权限管理、消费管理等**计算逻辑**抽离给独立无状态的 Proxy，Broker 继续专注**存储能力**的优化。

> [!IMPORTANT]
> 5.0 的代理架构与 4.x 的极简架构**相容相通** —— Proxy 可以以 `Local` 模式运行，实现与 4.0 完全一致的效果。开发者按业务场景自由选择部署形态。
>
> 这一点在 5.5.1 中体现为 `LocalMessageService`（走本地 Broker）与 `ClusterMessageService`（经 TopicRoute 转发到远端 Broker）两个实现，见下文「Proxy 与 Broker 的关系」。

```tex
Client ──▶ Proxy（无状态，gRPC 8081 + Remoting 8080）
            │  TopicRouteService 解析出 brokerAddr
            ▼
          Broker（专注存储）──▶ CommitLog / ConsumeQueue
```

## 关键事实：gRPC SDK 在独立仓库

> [!WARNING]
> **常见误解：「RocketMQ 5.0 把 gRPC 客户端 `rocketmq-client-java` 合入了主仓库 `client/java/`」——完全错误。**
>
> 核实结果（5.5.1 与 master **trees API 全量递归检索**）：
> - 5.5.1 树中 `client/` 下只有 `BUILD.bazel`、`pom.xml`、`src/` —— **无 `client/java/`**
> - 全树检索 `client/apis` → **0 命中**；`ClientServiceProvider` → **0 命中**；`rocketmq-client-java` → **0 命中**
>
> gRPC 客户端在独立仓库 **`apache/rocketmq-clients`**（monorepo，含 `rocketmq-apis` 子模块）。主仓库 `client/` 是 **Remoting 协议**客户端。
>
> 官方文档印证（`https://rocketmq.apache.org/docs/sdk/01overview`）：
> > "The gRPC protocol SDK evolves as an **independent repository** RocketMQ Clients… 仓库坐标如果是 `rocketmq-client` 则是 Remoting 协议，坐标如果是 `rocketmq-client-java` 则是 gRPC 协议。"

因此以下 API 类在 5.5.1 主仓库中**未查到**（属 `rocketmq-clients`，其内部默认值本次未逐个核实）：`ClientServiceProvider`、`PushConsumer`（gRPC 版）、`SimpleConsumer`、`FilterExpression`、`Message`、`ClientConfiguration`、`ClientRetryConfiguration`、`ClientConsumeResult`、`Telemetry`、`CredentialsProvider`、`StaticCredentialsProvider`、`ExponentialBackoff`。

> [!NOTE]
> 5.5.1 树中确有 15 个含 `PushConsumer` 的文件，但**全部是 Remoting 客户端**（`DefaultMQPushConsumer`、`MQPushConsumer`），非 gRPC 版，勿混淆。
>
> `PullResult` 存在于 `client/.../consumer/PullResult.java`（Remoting 版）。

## 模块与关键类

5.5.1 根目录一级模块（trees API 全量，`truncated: false`，3562 条）：

```text
auth  bazel  broker  client  common  container  controller  dev
distribution  docs  example  filter  namesrv  openmessaging
proxy  remoting  srvutil  store  style  test  tieredstore  tools
```

> [!TIP]
> - **存在**：`proxy/` `common/` `client/` `remoting/` `srvutil/` `filter/` `auth/` `controller/` `tieredstore/`
> - **不存在 `sampledata/`**（5.5.1 与 master 均无）
> - 根 `pom.xml` 的 `<modules>` 共 **17** 项，与目录一致，含 `<module>proxy</module>`

| 类 | 路径 | 作用 |
| -- | ---- | ---- |
| `ProxyStartup` | `proxy/.../proxy/ProxyStartup.java` | 启动入口，`main` 中装配并启动 gRPC + Remoting 两个 Server（`:85,95`）|
| `GrpcServer` | `proxy/.../proxy/grpc/GrpcServer.java` | gRPC 服务端 |
| `RemotingProtocolServer` | `proxy/.../proxy/remoting/RemotingProtocolServer.java` | Remoting 协议服务端 |
| `ProxyConfig` | `proxy/.../proxy/config/ProxyConfig.java` | Proxy 配置（1621 行）|

> [!WARNING]
> `org.apache.rocketmq.proxy.grpc.v2.ProxyGrpcServer` **不存在**（5.5.1 与 master 均无）。`v2` 包存在但只含 activity 类（`AbstractMessagingActivity`、`DefaultGrpcMessagingActivity`、`GrpcMessagingActivity`、`ContextStreamObserver`），无 Server 类。真实类名是 **`GrpcServer`**。
>
> 同理 `AbstractProxyMessageService` 也不存在 —— 5.5.1 为 `Cluster` / `Local` 二分实现。

### 端口默认值

`ProxyConfig.java`：

| 字段 | 值 | 出处 |
| ---- | -- | ---- |
| `grpcServerPort` | `8081` | `ProxyConfig.java:91`（`private Integer grpcServerPort = 8081;`）|
| `remotingListenPort` | `8080` | `ProxyConfig.java:265`（`private int remotingListenPort = 8080;`）|
| `metricsPromExporterPort` | `5557` | `:251` |
| `proxyMode` | `ProxyMode.CLUSTER.name()` | `:90` |

> [!NOTE]
> 8081/8080 的常见说法成立，但注意 gRPC 端口是 `Integer`（可为 null 表示不启用），remoting 是 `int`（必启用）。

## Proxy：不存消息、无需元数据存储

> [!IMPORTANT]
> **Proxy 是无状态的**（不存消息），请求经 `TopicRouteService` 解析出 `messageQueue.getBrokerAddr()` / `getBrokerName()` 后转发。
>
> **不需要配置 zookeeper / metadataStore** —— `ProxyConfig.java` 全文件**无 `metadataStore` / zookeeper / zk 字段**（只有 `metadataThreadPoolNums = 3` 这类线程池项）。Proxy 只依赖 `namesrvAddr`（`System.getProperty(MixAll.NAMESRV_ADDR_PROPERTY, ...)`）。
>
> → 「5.0 有 zookeeper/metadataStore 概念」的说法在 **5.5.1 已不存在**。这是 Proxy 无状态化的直接体现。

### 旧 Remoting 客户端能连 5.x Proxy

> [!WARNING]
> **常见误解：「5.x 只能用新 gRPC 客户端」——错。** 5.5.1 Proxy **同时启用两种协议**。
>
> `ProxyStartup.java:95` 在启动 gRPC 的同时 `new RemotingProtocolServer(messagingProcessor, ...)` 并 `appendStartAndShutdown`。`remoting/` 子包下有 `activity/AbstractRemotingActivity.java`（含 Acl 引用）等完整实现。
>
> 且 Remoting 协议请求码与 4.x **数值完全一致**：`SEND_MESSAGE=10`、`PULL_MESSAGE=11`、`QUERY_MESSAGE=12`、`UPDATE_AND_CREATE_TOPIC=17`、`CONSUMER_SEND_MSG_BACK=36`、`END_TRANSACTION=37` —— Remoting SDK 双向兼容成立。

兼容性矩阵（官方文档）：

| SDK | 支持的服务端版本 |
| --- | ---------------- |
| Remoting SDK（`rocketmq-client`） | 4.x 与 5.x |
| gRPC SDK（`rocketmq-client-java`） | **仅 ≥ 5.0** |

两者 API 不兼容，切换需改代码。

### Proxy 支持 ACL

`proxy/auth/ProxyAuthorizationMetadataProvider.java`（`implements AuthorizationMetadataProvider`，含 createAcl / deleteAcl / updateAcl / getAcl / listAcl）。

`ProxyConfig` 相关配置：

| 配置 | 默认值 |
| ---- | ------ |
| `enableAclRpcHookForClusterMode` | `false` |
| `aclCacheExpiredSeconds` | `300` |
| `aclCacheRefreshSeconds` | `20` |
| `aclCacheMaxNum` | `20000` |

> [!NOTE]
> ACL RPC Hook 在 Cluster 模式下默认**关闭**，多租户场景需显式开启。

## POP：无状态消费模型

5.0 在队列模型之上引入**无状态消费模型（POP）**，在同一个主体上同时支持两种消费模型，体现消息与流的「二象性」：面向流场景用高性能队列模型，面向消息场景用无状态消息模型。

**POP 是 Broker 侧能力**，不是客户端特性：

| 事实 | 值 | 出处 |
| ---- | -- | ---- |
| 请求码 | `RequestCode.POP_MESSAGE = 200050` | `remoting/.../protocol/RequestCode.java:80` |
| 请求头 | `PopMessageRequestHeader`（`@RocketMQAction(value = POP_MESSAGE, action = Action.SUB)`），含 `private long invisibleTime` | — |
| Broker 实现 | `PopMessageProcessor`、`PopLiteMessageProcessor`、`PopLongPollingService`、`PopLiteLongPollingService`、`PopBufferMergeService`、`PopReviveService`、`PopConsumerService`、`PopInflightMessageCounter` | — |
| 旧客户端侧 | `PopResult`、`PopStatus`、`PopCallback` | `client/.../consumer/` |
| 5.5.1 新增 | `broker/pop/` 包：`PopConsumerKVStore`、`PopConsumerLockService`、`PopConsumerRocksdbStore`、`PopConsumerCache`、`PopConsumerRecord` | — |

### invisibleTime 由客户端携带

> [!WARNING]
> **常见说法「POP 的 invisibleTime 服务端默认 15s」——未查到服务端默认值。** `PopMessageProcessor` 直接透传 `requestHeader.getInvisibleTime()`（`:383/431/594/736`）。
>
> 边界约束在 **`ProxyConfig`**：

| 配置 | 默认值 |
| ---- | ------ |
| `defaultInvisibleTimeMills` | `Duration.ofSeconds(60)` = **60000 ms** |
| `minInvisibleTimeMillsForRecv` | `Duration.ofSeconds(10)` = **10000 ms** |
| `maxInvisibleTimeMills` | `Duration.ofHours(12)` |
| `invisibleTimeMillisWhenClear` | `1000` |
| `longPollingReserveTimeInMillis` | `100` |

> [!NOTE]
> `ClientConsumeResult.nextVisibleTime`、`popDelay` 属 `rocketmq-clients` 仓库，本仓库**不存在 `ClientConsumeResult` 类**，未查到。
>
> 「POP 解决消息不可见但已 ack 问题」这一表述**未在 5.5.1 源码/文档中查到**对应说明，不作断言。

## 新特性清单

逐项经 trees API / contents API 核实：

| 特性 | 结论 | 证据 |
| ---- | ---- | ---- |
| **轻量队列 LMQ** | ✅ 存在，**默认关闭** | `MessageStoreConfig.java:299 enableLmq = false`；`:301 maxLmqConsumeQueueNum = 20000`；`:302 enableLmqQuota = false`。类：`LmqBrokerStatsManager`、`LmqDispatch`、`MultiDispatchUtils`。⚠️ **`LmqQueueManager` 不存在** |
| **多存储队列（多路分发）** | ✅ 存在，默认关闭 | 配置名 **`enableMultiDispatch`**（小写 d），非 `EnableMultiDispatch`；实现 `store/queue/MultiDispatchUtils.java:39-44` |
| **消息过滤** | ⚠️ 见专篇 | `BrokerConfig.java:178 enablePropertyFilter = false`（**默认 false**）。5.x 新 filter 机制**未查到**独立 `FILTER_MODE` 配置 |
| **延时消息时间轮** | ✅ **5.5.1 已默认开启** | `:84 timerWheelEnable = true`；实现 `store/timer/`（`TimerMessageStore`、`TimerWheel`、`TimerLog`、`TimerCheckpoint`、`TimerRequest`、`TimerMetrics`、`Slot`、`Timeline`、`TimerMessageRocksDBStore`）。⚠️ `TimerMessageService`、`ScheduleMessageTimerWheel` **均不存在**。`messageDelayLevel` **仍是 18 级** |
| **冷读限流** | ✅ 存在，全默认关闭 | `:456 coldDataFlowControlEnable = false`；`:457 coldDataScanEnable = false`；`:458 dataReadAheadEnable = true`（唯一默认 true）；配合 `CommitLog.ColdDataCheckService` |
| **RocksDB 版 ConsumeQueue** | ✅ 存在，**默认关闭** | `:486 rocksdbCQDoubleWriteEnable = false`；`:489 rocksdbCQSelectiveDoubleWriteEnable`；`:135 iteratorWhenUseRocksdbConsumeQueue = true`；`:525 popRocksdbBlockCacheSize = 256MB`；`:519 bottomMostCompressionTypeForConsumeQueueStore = ZSTD`。实现 8 个类（`queue/RocksDBConsumeQueue` 等）。⚠️ **`useRocksDBStore` 配置项未查到** |
| **事务消息** | ✅ Proxy 支持 | `proxy/service/transaction/`：`TransactionService`、`AbstractTransactionService`、`ClusterTransactionService`、`LocalTransactionService`、`TransactionData`、`TransactionDataManager`、`EndTransactionRequestData` |
| **LiteTopic（5.5.0 新增）** | ✅ 存在 | 源码 3 个相关类；`mqadmin tools/command/lite/` 下 6 个子命令；`ResponseCode.LITE_SUBSCRIPTION_QUOTA_EXCEEDED = 2018` |

`messageDelayLevel` 完整值（`MessageStoreConfig.java:262`，Broker 与 Proxy 两处一致）—— **即使时间轮默认开启，18 级延迟队列仍然保留**：

```text
1s 5s 10s 30s 1m 2m 3m 4m 5m 6m 7m 8m 9m 10m 20m 30m 1h 2h
```

## 高可用：BrokerContainer 与 DLedger Controller

5.0 对 Master-Slave 架构和基于 Raft 的架构都做了优化。

**BrokerContainer**：一个 BrokerContainer 中可部署多个 Broker，各 Broker 拥有独立端口、功能完全独立，可通过 admin 增减 Broker。

4.x 两种主流高可用设计的痛点：

| 方案 | 痛点 |
| ---- | ---- |
| 主备冷备（无切换）| 两副本备节点资源利用率低；主宕机时**特殊类型消息**（延时/事务）存在可用性问题 |
| Raft 多副本 | 高度串行化；基于多数派的确认机制扩展只读副本不够灵活；无法很好支持两机房对等部署、异地多中心 |

5.x 融合两者优势，提出 **Controller** 作为管控节点，将选主逻辑插件化并优化数据复制实现。它是**轻量级、可拔插的**选主组件，既可部署在 NameServer 中，也可部署在本地。

> [!WARNING]
> **早期资料把这条路径写成「DLedger Controller」，在 5.5.1 中已不准确**，需分三层理解：
> - **Broker DLedger 模式已废弃** —— 源码常量 `DLEDGER_COMMIT_LOG_DEPRECATION_WARNING`（`BrokerStartup.java:47-49`）写明 "Use Controller mode for new deployments"，启动即打警告。**但官方 5.x 文档页至今没标 deprecation**
> - **Controller 模式是推荐路径**，与 DLedger 模式**互斥**，同开直接 `System.exit(-4)`
> - **Controller 自身默认仍用 DLedger 组做 Raft** —— `ControllerConfig.controllerType = "DLedger"`，jRaft 需显式配置。所以「废弃 DLedger」指的是 **Broker 侧的 Raft 接管**，不是整个生态不再用它
>
> 两个开关默认都是 `false`，5.x 默认仍是传统主从。详见 [Cluster](/docs/CS/MQ/RocketMQ/Cluster.md)。

## 5.x 限制与坑

> [!WARNING]
> | 常见说法 | 5.5.1 真相 |
> | -------- | --------- |
> | 只能用新 gRPC 客户端 | ❌ Proxy 同时启用 8081(gRPC) 与 8080(Remoting)，旧客户端可连 |
> | Proxy 需配 zookeeper/metadataStore | ⚠️ 前半对（无状态）后半错 —— 该概念 5.5.1 已移除 |
> | `ProxyGrpcServer` 类 | ❌ 真实类名 `GrpcServer` |
> | `AbstractProxyMessageService` 类 | ❌ 真实为 `ClusterMessageService` / `LocalMessageService` |
> | `LmqQueueManager` 类 | ❌ 不存在 |
> | `TimerMessageService` / `ScheduleMessageTimerWheel` | ❌ 真实为 `store/timer/*` 下的 `TimerMessageStore` + `TimerWheel` |
> | `sampledata/` 模块 | ❌ 5.5.1 与 master 均无 |
> | POP invisibleTime 服务端默认 15s | ❌ 服务端不设默认值，由请求携带；边界在 ProxyConfig：默认 60s / 最小 10s / 最大 12h |
> | 存在 `useRocksDBStore` 配置 | ❌ 未查到，实际是 `rocksdbCQDoubleWriteEnable` 等 |
> | 官方限制章节在 `/docs/featureBehavior/` 与 `/docs/deployment/` | ❌ 两路径均为 JS 渲染的空目录索引；实际路径是 `/docs/bestPractice/*`、`/docs/observability/*`、`/docs/sdk/*` |

## 监控指标

> [!IMPORTANT]
> Prometheus 指标**自 5.1.0 起引入，且仅支持 broker**（官方 `/docs/observability/01metrics`）。

| 类别 | 指标 |
| ---- | ---- |
| Broker | `rocketmq_messages_in_total`、`rocketmq_messages_out_total`、`rocketmq_throughput_in_total`、`rocketmq_throughput_out_total`、`rocketmq_message_size`(histogram)、`rocketmq_consumer_ready_messages`、`rocketmq_consumer_inflight_messages`、`rocketmq_consumer_queueing_latency`、`rocketmq_consumer_lag_latency`、`rocketmq_send_to_dlq_messages_total`、`rocketmq_rpc_latency`(histogram)、`rocketmq_storage_message_reserve_time`、`rocketmq_storage_dispatch_behind_bytes`、`rocketmq_storage_flush_behind_bytes`、`rocketmq_thread_pool_wartermark`、`rocketmq_topic_create_execution_time`、`rocketmq_consumer_group_create_execution_time`、`rocketmq_topic_number`、`rocketmq_consumer_group_number` |
| Producer | `rocketmq_send_cost_time` |
| Consumer | `rocketmq_consume_cost_time` |

Label 集：`cluster`、`node_type`(proxy/broker/nameserver)、`node_id`、`topic`、`message_type`(Normal/FIFO/Transaction/Delay)、`consumer_group`、`invocation_status`。

> [!TIP]
> 排障常用：`rocketmq_storage_flush_behind_bytes` 观察刷盘积压、`rocketmq_storage_dispatch_behind_bytes` 观察 Reput 派发积压、`rocketmq_consumer_lag_latency` 观察消费延迟。写入即丢的丢消息问题优先看 `send_to_dlq_messages_total` 与 `storage_flush_behind_bytes`。

## JVM 与系统参数

官方推荐（`https://rocketmq.apache.org/docs/bestPractice/07JVMOS`）：

```text
-server -Xms8g -Xmx8g -Xmn4g
-XX:+AlwaysPreTouch        -XX:-UseBiasedLocking
-XX:+UseG1GC -XX:G1HeapRegionSize=16m -XX:G1ReservePercent=25 -XX:InitiatingHeapOccupancyPercent=30
-XX:+UseGCLogFileRotation -XX:NumberOfGCLogFiles=5 -XX:GCLogFileSize=30m
-Xloggc:/dev/shm/mq_gc_%p.log
```

要点：

- 最大堆 **不超过 32G**（否则失去指针压缩）
- `vm.swappiness = 10`
- fd 上限 **655350**
- IO 调度器用 **deadline**

## 相关配置速查

`MessageStoreConfig`（5.5.1，均为默认值）：

| 参数 | 默认值 |
| ---- | ------ |
| `mappedFileSizeCommitLog` | `1024*1024*1024`（1G）|
| `maxMessageSize` | `1024*1024*4`（4MB）|
| `flushDiskType` | `FlushDiskType.ASYNC_FLUSH` |
| `syncFlushTimeout` | `1000*5` |
| `maxHaTransferByteInSecond` | `100 * 1024 * 1024` |
| `timerWheelEnable` | `true` |
| `timerMaxDelaySec` | `3600*24*3`（3 天）|
| `timerPrecisionMs` | `1000` |
| `timerRollWindowSlot` | `3600*24*2` |
| `enableLmq` | `false` |
| `coldDataFlowControlEnable` | `false` |
| `rocksdbCQDoubleWriteEnable` | `false` |

> [!WARNING]
> `brokerRole` 实际定义在 **`MessageStoreConfig.java:254`**（默认 `BrokerRole.ASYNC_MASTER`），**不在 `BrokerConfig`** —— 找配置时容易走错文件。
>
> `BrokerConfig` 真实路径是 `common/src/main/java/org/apache/rocketmq/common/BrokerConfig.java`（**不在 `broker/` 模块下**），其中 `listenPort` 默认 **6888**（`:40`），不是常见的 10911（10911 是 NameServer 端口）。

## Links

- [Apache RocketMQ](/docs/CS/MQ/RocketMQ/RocketMQ.md)
- [Broker](/docs/CS/MQ/RocketMQ/Broker.md)
- [Store](/docs/CS/MQ/RocketMQ/Store.md)
- [Consumer](/docs/CS/MQ/RocketMQ/Consumer.md)
- [事务消息](/docs/CS/MQ/RocketMQ/Transaction.md)
- [消息过滤](/docs/CS/MQ/RocketMQ/Filter.md)

## References

1. [RocketMQ 5.5.1 Release](https://github.com/apache/rocketmq/releases/tag/rocketmq-all-5.5.1)
2. [RocketMQ 5.0 速览（官方）](https://rocketmq.apache.org/docs/featureBehavior/)
3. [RocketMQ SDK 概览（gRPC SDK 独立仓库说明）](https://rocketmq.apache.org/docs/sdk/01overview)
4. [RocketMQ 监控指标](https://rocketmq.apache.org/docs/observability/01metrics)
5. [RocketMQ JVM 与 OS 最佳实践](https://rocketmq.apache.org/docs/bestPractice/07JVMOS)
