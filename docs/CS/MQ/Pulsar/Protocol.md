## Introduction

Pulsar 的客户端与 broker 之间走**自定义二进制协议**（自定义帧格式 + protobuf 序列化的命令），不是 HTTP、也不是 AMQP 这类通用协议。数据面（6650 端口）全部由它承载：producer 发送、consumer 拉取与 ack、lookup 寻址、schema 协商乃至事务协调器的交互，都是同一条 TCP 连接上的一组命令帧。

协议处理的共享代码在 `pulsar-common` 的 `org.apache.pulsar.common.protocol` 包：`Commands`（帧与命令的构造/序列化）、`PulsarDecoder`（入站解码）、`PulsarHandler`（连接生命周期与 keep-alive）、`FrameDecoderUtil`（Netty 帧解码器管理）。客户端 `ClientCnx` 与 broker 侧 `ServerCnx` 继承同一棵类树 —— 注意这是 4.x 的模块位置：`PulsarHandler` 在 4.2.4 已位于 `pulsar-common`（contents API 实测），旧资料写的 `pulsar-broker/.../service/PulsarHandler.java` 路径已不存在。

> 版本基线：**4.2.4**（tag `v4.2.4`）。本篇所有结论以该 tag 源码为准，协议演进以 `PulsarApi.proto` 的 `ProtocolVersion` 枚举注释为权威。

## Frame Format

一条 Pulsar 协议消息在 Netty 层是「长度前缀帧」：前 4 字节大端 `TOTAL_SIZE`，其后是命令与可选负载。源码里有两个序列化入口，对应两种帧形态（`Commands.java:1673-1741`）：

```
// serializeWithPrecalculatedSerializedSize：纯命令帧
[TOTAL_SIZE] [CMD_SIZE][CMD]

// serializeCommandSendWithSize：带 payload 的命令帧（SEND / MESSAGE 等）
[TOTAL_SIZE] [CMD_SIZE][CMD] [MAGIC_NUMBER][CHECKSUM] [METADATA_SIZE][METADATA] [PAYLOAD]
```

`TOTAL_SIZE = CMD_SIZE 字段(4 字节) + CMD 序列化长度`，即不含自身那 4 字节；整帧字节数 = `TOTAL_SIZE + 4`。带 payload 的帧里 `MAGIC_NUMBER + CHECKSUM` 仅当 checksum 类型为 `Crc32c` 时存在（见下文 [Encoding Details](#encoding-details)）。

Netty 侧由 `FrameDecoderUtil` 统一装配（`FrameDecoderUtil.java:59-63`）：

```java
private static LengthFieldBasedFrameDecoder createFrameDecoder(int maxMessageSize) {
    return new LengthFieldBasedFrameDecoder(
            maxMessageSize + Commands.MESSAGE_SIZE_FRAME_PADDING, 0, 4, 0, 4);
}
```

参数含义：`maxFrameLength = maxMessageSize + 10KB`、`lengthFieldOffset = 0`、`lengthFieldLength = 4`、`lengthAdjustment = 0`、`initialBytesToStrip = 4`。也就是说 Netty 负责按 `TOTAL_SIZE` 切帧并**剥掉长度前缀**，交给 `PulsarDecoder` 的 buffer 是 `[CMD_SIZE][CMD][payload]`；`PulsarDecoder.channelRead` 再读一次无符号 int 得到 `CMD_SIZE`，用 `cmd.parseFrom(buffer, cmdSize)` 还原 protobuf 命令（`PulsarDecoder.java:123-124`）。

默认上限：`maxMessageSize` 取 `Commands.DEFAULT_MAX_MESSAGE_SIZE = 5MB`（`Commands.java:123`，`ServiceConfiguration.java:1590` 同值），加 `MESSAGE_SIZE_FRAME_PADDING = 10KB`（`Commands.java:124`），即单帧最大 **5,242,960 字节**。两侧的值可以不同，协商规则见 [Handshake](#handshake)。

> [!IMPORTANT]
> `PulsarDecoder` 持有**单个复用的 `BaseCommand` 实例**（`PulsarDecoder.java:109`），类注释明确警告：`handle*` 方法收到的命令对象在方法返回后即被清空复用，**不允许保留引用**，需要跨线程传递必须 deep copy（`PulsarDecoder.java:94-102`）。这是协议层的对象分配优化，读源码时容易踩。

## Command Set

协议命令全集以 `PulsarDecoder` 的 switch 分支为权威（`PulsarDecoder.java:130-479`），按职责分组：

| 分组 | 命令 | 说明 |
| ---- | ---- | ---- |
| 连接管理 | `CONNECT` / `CONNECTED` / `AUTH_CHALLENGE` / `AUTH_RESPONSE` / `PING` / `PONG` / `ERROR` | 握手、双向认证、保活 |
| Topic 元数据 | `LOOKUP`(+`RESPONSE`) / `PARTITIONED_METADATA`(+`RESPONSE`) / `GET_TOPICS_OF_NAMESPACE`(+`RESPONSE`) | 寻址与分区元数据 |
| 生产 | `PRODUCER`(+`SUCCESS`) / `SEND`(+`RECEIPT` / `SEND_ERROR`) / `CLOSE_PRODUCER` | 创建生产者、发送与回执 |
| 消费 | `SUBSCRIBE`(+`SUCCESS`) / `MESSAGE` / `FLOW` / `ACK`(+`RESPONSE`) / `REDELIVER_UNACKNOWLEDGED_MESSAGES` / `SEEK` / `UNSUBSCRIBE` / `CLOSE_CONSUMER` / `GET_LAST_MESSAGE_ID`(+`RESPONSE`) / `CONSUMER_STATS`(+`RESPONSE`) / `REACHED_END_OF_TOPIC` / `ACTIVE_CONSUMER_CHANGE` | 订阅、投递、位点与重投 |
| Schema | `GET_SCHEMA`(+`RESPONSE`) / `GET_OR_CREATE_SCHEMA`(+`RESPONSE`) | schema 注册表走二进制协议，不是 REST |
| 事务 | `TC_CLIENT_CONNECT_REQUEST`(+`RESPONSE`) / `NEW_TXN`(+`RESPONSE`) / `ADD_PARTITION_TO_TXN`(+`RESPONSE`) / `ADD_SUBSCRIPTION_TO_TXN`(+`RESPONSE`) / `END_TXN` / `END_TXN_ON_PARTITION` / `END_TXN_ON_SUBSCRIPTION`（各带 `RESPONSE`） | 事务协调器同样走这条协议（v19 引入） |
| Topic 监听 | `WATCH_TOPIC_LIST`(+`SUCCESS` / `CLOSE`) / `WATCH_TOPIC_UPDATE` | 4.x 已具备的 watcher 雏形 |
| 迁移 | `TOPIC_MIGRATED` | topic 迁移时的重定向（v20） |

两条结构性结论：

- **事务不是旁路**。TC 的 `NEW_TXN` / `END_TXN` 等与普通 SEND/ACK 在同一条连接、同一套帧格式上传输，客户端通过 `TC_CLIENT_CONNECT_REQUEST` 先与事务协调器建立逻辑通道。事务状态机本身见 [Functions 与事务](/docs/CS/MQ/Pulsar/Functions.md)。
- **schema 协商也走协议**。`GET_OR_CREATE_SCHEMA`（v15 引入）让 producer 在创建时即可上报/校验 schema，无需先调 REST。

## Version Negotiation

协议版本是 `PulsarApi.proto:254-280` 的 `ProtocolVersion` 枚举，4.2.4 共 **v0 ~ v21** 二十二个值；`Commands.getCurrentProtocolVersion()` 的实现是「取枚举最后一个值」（`Commands.java:146-147, 2137-2138`），因此 4.2.4 的当前协议版本是 **v21**。

| 版本 | 引入的能力（proto 注释原文语义） |
| ---- | ---- |
| v0 | 初始版本 |
| v1 | 应用层 keep-alive（`PING`/`PONG`） |
| v2 | `REDELIVER_UNACKNOWLEDGED_MESSAGES` |
| v3 | LZ4 与 ZLib 压缩 |
| v4 | batch 消息支持 |
| v5 | 断开客户端但不关闭连接 |
| v6 | metadata + payload 的 checksum 计算 |
| v7 | `CommandLookupTopic` 二进制寻址 |
| v8 | `CommandConsumerStats` 客户端拉取 broker 侧统计 |
| v9 | end of topic 通知 |
| v10 | proxy to broker |
| v11 | 此前版本的 C++ consumer 未正确处理 checksum 字段 |
| v12 | `GET_LAST_MESSAGE_ID` / `ACTIVE_CONSUMER_CHANGE` / `GET_TOPICS_OF_NAMESPACE` |
| v13 | schema-registry：avro schema for json |
| v14 | `AUTH_CHALLENGE` / `AUTH_RESPONSE` 双向认证 + Key_Shared 订阅 |
| v15 | `GET_OR_CREATE_SCHEMA` 及其响应命令 |
| v16 | broker entry metadata（服务端侧） |
| v17 | ack receipt |
| v18 | broker entry metadata（客户端侧支持） |
| v19 | `TC_CLIENT_CONNECT_REQUEST` / `RESPONSE` |
| v20 | topic 迁移重定向 `CommandTopicMigrated` |
| v21 | 把 `AUTO_CONSUME` schema 携带到 broker |

协商规则在 `Commands.newConnectedCommand`（`Commands.java:306-328`）：

```java
int currentProtocolVersion = getCurrentProtocolVersion();
int versionToAdvertise = Math.min(currentProtocolVersion, clientProtocolVersion);
connected.setProtocolVersion(versionToAdvertise);
```

即**服务端取自身与客户端的较小值**回告，源码注释解释是为了避免让客户端困惑（"it will anyway advertise the max version that the client supports"）。客户端在 `handleConnected` 里把这个值写入 `remoteEndpointProtocolVersion`（`ClientCnx.java:429`），此后所有能力判断都以它为准。

版本能力门控的代码形态是 `Commands` 里的一组 `peerSupportsXxx(int peerVersion)` 方法（`Commands.java:2149-2210`）：

| 能力 | 最低对端版本 |
| ---- | ---- |
| `getLastMessageId` / `activeConsumerListener` / 多消息 ack | v12 |
| JSON schema 的 avro 格式 | v13 |
| `getOrCreateSchema` | v15 |
| broker entry metadata | v16 |
| ack receipt | v17 |
| `AUTO_CONSUME` schema 带到 broker | v21 |

除版本号外，握手还交换一组 **FeatureFlags**（`CommandConnect.FeatureFlags` / `CommandConnected.FeatureFlags`），作为版本号之外的细粒度能力通告：客户端声明 `supportsAuthRefresh`、`supportsBrokerEntryMetadata`、`supportsPartialProducer`、`supportsGetPartitionedMetadataWithoutAutoCreation`、`supportsReplDedupByLidAndEid`（`Commands.java:196-201`）；服务端回告 `supportsTopicWatchers`、`supportsTopicWatcherReconcile` 等（`Commands.java:323-326`）。客户端在 `handleConnected` 逐项读取并置位（`ClientCnx.java:418-426`）。

## Handshake

连接建立后的第一个命令必须是 `CONNECT`（服务端 `handleConnect` 以 `checkArgument(state == State.Start)` 强制，`ServerCnx.java:1136`）。完整时序：

1. **客户端发 CONNECT**：`ClientCnx.channelActive` 里 `ctx.writeAndFlush(newConnectCommand())`，成功后进入 `SentConnectFrame` 态（`ClientCnx.java:312-324`）。命令携带 `clientVersion`（`"Pulsar-Java-v" + PulsarVersion.getVersion()`）、`authMethodName`、认证数据、`protocolVersion`；经 proxy 接入时额外带 `proxyToBrokerUrl` 与 `originalPrincipal` / `originalAuthData` / `originalAuthMethod`（`Commands.java:259-300`）。
2. **服务端校验前置条件**：`PulsarService` 未处于 running 直接回 `ServiceNotReady` 并关闭连接（`ServerCnx.java:1147-1160`）—— broker 启动未完成时新连接不会被挂起等待。
3. **认证（可多轮）**：未开认证时直接 `completeConnect`；开启认证则先进入 `Connecting` 态做异步认证（`ServerCnx.java:1173-1190`），必要时以 `AUTH_CHALLENGE` ↔ `AUTH_RESPONSE` 多轮交互（v14 引入的双向认证机制）。四类认证提供者与 ACL 见 [Broker](/docs/CS/MQ/Pulsar/Broker.md) 的 Authentication 一节。
4. **服务端回 CONNECTED**：`completeConnect` 在授权开启时校验 proxy 透传的 `originalPrincipal` 与 `proxyRole`（`ServerCnx.java:882-901`），随后 `Commands.newConnected(clientProtoVersion, maxMessageSize, enableTopicListWatcher)`（`ServerCnx.java:904`），进入 `Connected` 态并把 `remoteEndpointProtocolVersion` 置为客户端版本。
5. **客户端完成握手**：`handleConnected` 做三件事 —— 若 `connected.hasMaxMessageSize()` 则**按服务端宣告值替换帧解码器**（`ClientCnx.java:406-413`）、读取 FeatureFlags、置 `remoteEndpointProtocolVersion`，最后 `connectionFuture.complete(null)` 进入 `Ready` 态。

第 5 步的帧解码器替换值得单独强调：客户端建连时用的是本地配置的 `maxMessageSize`，收到 CONNECTED 后用服务端的值 `FrameDecoderUtil.replaceFrameDecoder` 动态换掉 pipeline 里的 `frameDecoder`（handler 名固定为 `"frameDecoder"`）。**双方 maxMessageSize 不一致时以服务端为准**，帧上限随之改变。

## Keep-alive

keep-alive 由 `PulsarHandler` 统一实现（客户端与 broker 共用），逻辑在 `PulsarHandler.java:110-136`：

- `channelActive` 时按 `keepAliveIntervalSeconds` 固定频率调度 `handleKeepAliveTimeout`（`PulsarHandler.java:78-82`）；间隔取构造函数参数 —— 客户端来自 `ClientConfigurationData.keepAliveIntervalSeconds`，**默认 30 秒**（`ClientConfigurationData.java:249`）；broker 来自 `ServiceConfiguration.keepAliveIntervalSeconds`，**默认同为 30 秒**（`ServiceConfiguration.java:3353`，经 `BrokerService.java:367` 注入 `ServerCnx`）。
- 每轮超时检查分三种情况：握手未完成（`isHandshakeCompleted()` 为假）→ 直接关闭连接；上一轮 ping 未收到响应且 `autoRead` 开启 → 判定对端假死，关闭；否则向对端发 `PING`。
- 对端协议版本 `< v1` 时**不发 ping**（ping/pong 是 v1 才引入的能力），此时连接没有应用层保活。
- `handlePing` 立即回 `PONG`，写失败同样强制关闭（`PulsarHandler.java:91-104`）；`messageReceived` 收到任意命令都会清零 `waitingForPingResponse`。

客户端还有一层独立的请求超时：`ClientCnx.channelActive` 起一个 `operationTimeoutMs` 周期的 `checkRequestTimeout` 任务（`ClientCnx.java:301-303`，默认 10s，`ClientConfigurationData.java:256`），扫描挂起的请求 future。它与 keep-alive 是两个机制：前者管「请求有没有回」，后者管「连接死没死」。

## Encoding Details

**Checksum**：仅当 `ChecksumType.Crc32c` 时存在，布局是 2 字节 magic（`magicCrc32c = 0x0e01`，`Commands.java:132`）+ 4 字节 checksum（`Commands.java:135`），覆盖 **metadata + payload**，不含 CMD 与长度头；非 Crc32c 类型时这 6 字节整体消失（`Commands.java:1700-1701`）。checksum 先占位后回填：序列化时跳过 4 字节，算出 `computeChecksum(headers)` 再 `resumeChecksum` 把 payload 续进去，最后 `setInt` 写回占位处（`Commands.java:1717-1739`）。

**BrokerEntryMetadata**：broker 把消息写入 BookKeeper entry 前，会在头部插入一段 broker 侧元数据，格式为 2 字节 magic（`magicBrokerEntryMetadata = 0x0e02`，`Commands.java:134`）+ 4 字节长度 + protobuf（`Commands.java:1751-1768`）；读侧用 `skipBrokerEntryMetadataIfExist` 按同样 magic 识别并跳过（`Commands.java:1781-1789`）。该能力由协议版本 v16（服务端）/ v18（客户端）门控。entry 层细节见 [ManagedLedger 存储层](/docs/CS/MQ/Pulsar/ManagedLedger.md)。

**MessageMetadata**（`PulsarApi.proto:107-137`）每条消息必带的 protobuf 元数据，与 payload 之间以 `METADATA_SIZE` 分隔：

| 字段 | 含义 |
| ---- | ---- |
| `producer_name` / `sequence_id` / `publish_time` | 生产者标识、序号、发布时间 |
| `partition_key` | 分区 key（有 key 时 hash 定分区，见 [Producer](/docs/CS/MQ/Pulsar/Producer.md)） |
| `replicated_from` / `replicate_to` | 跨地域复制的来源标记与覆盖目标 |
| `compression` / `uncompressed_size` | 压缩类型（默认 `NONE`）与解压后大小 |
| `num_messages_in_batch` | batch 内消息条数，默认 1 |
| `event_time` | 应用事件时间，缺省时用 `publish_time` |
| `encryption_keys` / `encryption_algo` / `encryption_param` | 端到端加密的密钥名、加密密钥与算法参数 |
| `schema_version` | 消息对应的 schema 版本号 |

> [!WARNING]
> `MessageMetadata` 的 field 10 曾是 checksum 字段，4.x 里它是**被移除的残留编号**（proto 注释：「it should be part of send-command which keeps checksum of header + payload」）—— 校验和已上移到命令层，不要按旧资料在 metadata 里找 checksum。

**零拷贝双缓冲**：`SEND`/`MESSAGE` 帧的 header 与 payload 不合并成一个 buffer，而是封装为 `ByteBufPair` 成对传递（`Commands.java:1728`），pipeline 里由 `ByteBufPairEncoder` 编码（`PulsarChannelInitializer.java:90`），避免大 payload 的内存拷贝。

## Pipeline

broker 侧每条连接的 Netty pipeline 在 `PulsarChannelInitializer.initChannel` 组装（`PulsarChannelInitializer.java:80-105`），顺序即数据流经的顺序：

| # | handler | 作用 |
| ---- | ---- | ---- |
| 1 | channel 配置 | `setAutoRead(false)` + 写高低水位线 —— **默认关闭 auto-read**，等 `ServerCnx` 在 `channelActive` 确认服务就绪后才开启 |
| 2 | `"consolidation"` | `FlushConsolidationHandler(1024, true)`，合并 flush 减少系统调用 |
| 3 | `"tls"`（可选） | `SslHandler`；`tlsCertRefreshCheckDurationSec > 0` 时按周期热刷新 SSL context（`PulsarChannelInitializer.java:69-74`） |
| 4 | `"ByteBufPairEncoder"` | 出站编码 `ByteBufPair` |
| 5 | `OptionalProxyProtocolDecoder`（可选） | HAProxy PROXY protocol，解析真实客户端地址 |
| 6 | `"frameDecoder"` | `LengthFieldBasedFrameDecoder`，按 `TOTAL_SIZE` 切帧 |
| 7 | `"flowController"` | `FlowControlHandler`，与 auto-read 配合做读背压 |
| 8 | `"handler"` | `ServerCnx`，协议命令分发 |

第 1 + 7 层的组合是 broker 流控的关键：`ByteToMessageDecoder` 一读到数据就可能触发多次 channelRead，auto-read 关不掉它，因此额外插入 `FlowControlHandler` 统一控制读节奏（`PulsarChannelInitializer.java:96-101` 的注释引用了对应的 Netty 问题）。背压在读路径的落点（`handleFlow` 的 permits 账）见 [Broker](/docs/CS/MQ/Pulsar/Broker.md)。

客户端侧 pipeline 由 `ConnectionPool` 建连时装配，`frameDecoder` 的初始值取本地 `maxMessageSize`，再按 [Handshake](#handshake) 第 5 步替换为服务端宣告值。**Proxy 是这条链上的特例**：直通模式下 proxy 调 `FrameDecoderUtil.removeFrameDecoder` 把帧解码器从 pipeline 移除，字节流不解码直接转发（`FrameDecoderUtil.java:47-54`）；解码转发模式下才逐命令解析后重写。两种模式的取舍见 [集群复制与分层存储](/docs/CS/MQ/Pulsar/Cluster.md)。

## Schema over the Protocol

schema 不是 REST 专属能力，协议层有三个落点：

1. **命令**：`GET_SCHEMA` / `GET_OR_CREATE_SCHEMA`（v15 引入）—— producer 创建时向 broker 查询或登记 schema，响应携带 schema 版本。
2. **消息元数据**：`MessageMetadata.schema_version`（field 16）随每条消息下发，consumer 据此找到对应 schema 反序列化。
3. **AUTO_CONSUME 携带**：v21 起客户端可把 `AUTO_CONSUME` 模式的 schema 选择带到 broker 侧（`Commands.java:2173-2174` 的 `peerSupportsCarryAutoConsumeSchemaToBroker`）。

服务端由 `SchemaRegistryService` 承接（broker 进程内组件，`ServerCnx` 构造时注入，`ServerCnx.java:346`），schema 的存储位置与 topic 策略的关系见 [集群复制与分层存储](/docs/CS/MQ/Pulsar/Cluster.md)。

## Common Claims That Need Debunking

| 说法 | 4.2.4 实况 |
| ---- | --------- |
| 「Pulsar 客户端通过 REST 与 broker 通信」 | ❌ 数据面是自定义二进制协议；broker 的 HTTP 服务（8080）只承担 admin API 与 lookup 辅助 |
| 「协议当前版本是 v20」 | ❌ **v21**（`AUTO_CONSUME` schema 到 broker）。`getCurrentProtocolVersion()` 取枚举末值，proto 共 v0~v21 |
| 「协议版本取双方较新者协商」 | ❌ 取 `Math.min(server, client)`（`Commands.java:319`），服务端刻意向旧客户端妥协 |
| 「ping/pong 各版本都有」 | ❌ v1 引入；对 v0 对端 `PulsarHandler` 明确跳过 keep-alive 探测 |
| 「事务协调器走 HTTP 旁路」 | ❌ `TC_*` 系列二进制命令，与 SEND/ACK 同帧同连接（v19 引入） |
| 「checksum 覆盖整个帧」 | ⚠️ 只覆盖 metadata + payload，且仅 `Crc32c` 类型时存在（magic `0x0e01` 标识） |
| 「`MessageMetadata` 里有 checksum 字段」 | ❌ field 10 是已移除的残留编号，校验和上移到了命令层 |
| 「`PulsarHandler` 在 pulsar-broker 模块」 | ❌ 4.2.4 位于 `pulsar-common/.../common/protocol/`（contents API 实测），客户端与 broker 共用 |
| 「每帧都会新建命令对象」 | ❌ `PulsarDecoder` 复用单个 `BaseCommand`，`handle*` 参数不可 retain（`PulsarDecoder.java:94-109`） |
| 「两侧 maxMessageSize 必须手工配成一致」 | ⚠️ 客户端以 CONNECTED 宣告值为准动态替换 frameDecoder，配置不一致时以服务端为准 |

## Links

- [MQ 总纲](/docs/CS/MQ/MQ.md)
- [Pulsar](/docs/CS/MQ/Pulsar/Pulsar.md)
- [Consumer](/docs/CS/MQ/Pulsar/Consumer.md)
- [Kafka Network](/docs/CS/MQ/Kafka/Network.md)
- [RocketMQ Remoting](/docs/CS/MQ/RocketMQ/Remoting.md)

## References

1. [Apache Pulsar 4.2.4 Release](https://github.com/apache/pulsar/releases/tag/v4.2.4)
2. [PulsarApi.proto (v4.2.4)](https://github.com/apache/pulsar/blob/v4.2.4/pulsar-common/src/main/proto/PulsarApi.proto)
3. [Commands.java (v4.2.4)](https://github.com/apache/pulsar/blob/v4.2.4/pulsar-common/src/main/java/org/apache/pulsar/common/protocol/Commands.java)
4. [PulsarDecoder.java (v4.2.4)](https://github.com/apache/pulsar/blob/v4.2.4/pulsar-common/src/main/java/org/apache/pulsar/common/protocol/PulsarDecoder.java)
5. [PulsarHandler.java (v4.2.4)](https://github.com/apache/pulsar/blob/v4.2.4/pulsar-common/src/main/java/org/apache/pulsar/common/protocol/PulsarHandler.java)
6. [FrameDecoderUtil.java (v4.2.4)](https://github.com/apache/pulsar/blob/v4.2.4/pulsar-common/src/main/java/org/apache/pulsar/common/protocol/FrameDecoderUtil.java)
7. [Pulsar 官方文档](https://pulsar.apache.org/docs/)
