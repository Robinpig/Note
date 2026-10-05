## Introduction

RocketMQ 的事务消息用来解决「本地事务与消息发送的原子性」问题：消息发出去了但本地事务回滚（钱扣了、订单没建），或本地事务成功了但消息没发出（订单建了、用户没收到通知）。

它的实现是 **2PC + 补偿**，不是 XA，也不是 Seata 的 AT 模式 —— 核心思路是：先把消息存起来（对用户不可见），本地事务执行完再根据结果决定这条消息可见与否；如果结果丢了（Broker 挂了、Producer 崩了），Broker 回头找 Producer 问清楚。

> 版本基线：**5.5.1**（tag `rocketmq-all-5.5.1`）。

```tex
Producer                  Broker
  │                         │
  │ ① sendMessageInTransaction(HALF)
  │────────────────────────▶│ 存 half 消息
  │                         │   topic 改写为 RMQ_SYS_TRANS_HALF_TOPIC
  │                         │   REAL_TOPIC/REAL_QID 备份进 properties
  │  ◀── SendResult(PUT_OK) │
  │                         │
  │ ② executeLocalTransaction()  ← 本地事务（扣款/建单）
  │                         │
  │ ③ endTransaction(COMMIT/ROLLBACK)
  │────────────────────────▶│ COMMIT: 删 half，写最终消息到 REAL_TOPIC（建 CQ 索引，此刻用户可见）
  │                         │ ROLLBACK: 仅写 Op 消息打标
  │                         │
  │   若 ③ 丢失 ────────────▶│ 定时回查
  │                         │  CHECK_TRANSACTION_STATE (单向 RPC 39)
  │  ◀──────────────────────│
  │ ④ checkLocalTransaction()
  │                         │
  │ ⑤ endTransaction(REPLY)  ──▶│ 补偿到达
```

## Topic 与 flag 常量

### Topic 名称

`common/src/main/java/org/apache/rocketmq/common/topic/TopicValidator.java:29-34`：

| 常量名 | 字符串值 |
| ------ | -------- |
| `RMQ_SYS_TRANS_HALF_TOPIC` | `"RMQ_SYS_TRANS_HALF_TOPIC"` |
| `RMQ_SYS_TRANS_OP_HALF_TOPIC` | `"RMQ_SYS_TRANS_OP_HALF_TOPIC"` |
| `RMQ_SYS_ROCKSDB_TRANS_HALF_TOPIC` | `"RMQ_SYS_ROCKSDB_TRANS_HALF_TOPIC"` |
| `RMQ_SYS_ROCKSDB_TRANS_OP_HALF_TOPIC` | `"RMQ_SYS_ROCKSDB_TRANS_OP_HALF_TOPIC"` |
| `RMQ_SYS_TRANS_CHECK_MAX_TIME_TOPIC` | `"TRANS_CHECK_MAX_TIME_TOPIC"` |

> [!WARNING]
> Op 消息 topic 的常量名是 **`RMQ_SYS_TRANS_OP_HALF_TOPIC`**，不是常见资料写的 `TRANS_OP_MSG_HALF_TOPIC`（全仓 grep 零命中）。注意它的**字符串值与常量名同名**，容易误以为值是 `TRANS_OP_HALF_TOPIC` 之类。

两者都在 `SYSTEM_TOPIC_SET`（`:62,64`）与 `NOT_ALLOWED_SEND_TOPIC_SET`（`:73,74`）中 —— **客户端不能直接发送**，只能由 Broker 内部流程写入。Broker 启动时初始化为 1 读 1 写队列（`broker/.../topic/TopicConfigManager.java:197-215`）。

### sysflag 事务位

`common/src/main/java/org/apache/rocketmq/common/sysflag/MessageSysFlag.java:33-38`：

```java
public final static int COMPRESSED_FLAG = 0x1;
public final static int MULTI_TAGS_FLAG = 0x1 << 1;
public final static int TRANSACTION_NOT_TYPE = 0;
public final static int TRANSACTION_PREPARED_TYPE = 0x1 << 2;
public final static int TRANSACTION_COMMIT_TYPE = 0x2 << 2;
public final static int TRANSACTION_ROLLBACK_TYPE = 0x3 << 2;
```

| 常量 | 表达式 | 实际值 |
| ---- | ------ | ------ |
| `TRANSACTION_NOT_TYPE` | `0` | **0x0** |
| `TRANSACTION_PREPARED_TYPE` | `0x1 << 2` | **0x4** |
| `TRANSACTION_COMMIT_TYPE` | `0x2 << 2` | **0x8** |
| `TRANSACTION_ROLLBACK_TYPE` | `0x3 << 2` | **0xC** |

占用 byte1 的 bit2~bit3。辅助方法：`getTransactionValue(flag) = flag & 0xC`，`resetTransactionValue(flag, type) = (flag & ~0xC) | type`。

## 半消息为什么对消费者不可见

> [!IMPORTANT]
> **不是靠 flag 屏蔽，而是靠改写 topic。** 关键代码在 `broker/.../transaction/queue/TransactionalMessageBridge.java:219-237`：

```java
MessageAccessor.putProperty(msgInner, MessageConst.PROPERTY_REAL_TOPIC, msgInner.getTopic());
MessageAccessor.putProperty(msgInner, MessageConst.PROPERTY_REAL_QUEUE_ID, String.valueOf(msgInner.getQueueId()));
msgInner.setSysFlag(MessageSysFlag.resetTransactionValue(msgInner.getSysFlag(), MessageSysFlag.TRANSACTION_NOT_TYPE));
msgInner.setTopic(TransactionalMessageUtil.buildHalfTopic());   // ← 换成 half topic
msgInner.setQueueId(0);                                          // ← 强制 0
```

真实 topic/queueId 被备份进 `PROPERTY_REAL_TOPIC`（`"REAL_TOPIC"`）与 `PROPERTY_REAL_QUEUE_ID`（`"REAL_QID"`）属性。提交时再取出来写回真实 topic。

因为用户不订阅这个系统 topic，消费端就看不见 —— 这是**存储层实现**而非过滤逻辑，可靠性比「消费时判断 flag 跳过」高得多。

### 半消息照常占 20 字节 ConsumeQueue 单元

```java
// store/.../ConsumeQueue.java:851-853
this.byteBufferIndex.putLong(offset);    // 8B  queueOffset
this.byteBufferIndex.putInt(size);       // 4B  消息大小
this.byteBufferIndex.putLong(tagsCode);  // 8B  tag hashcode / ext 地址
```

半消息同样经 `DispatchRequest` 落 ConsumeQueue（Broker 内部用 `CID_RMQ_SYS_TRANS` 这个**内部消费组**订阅它做回查，见 `TransactionalMessageUtil.java:53-55`），所以它**占** 20 字节单元，只是不对用户订阅组可见。

> [!TIP]
> 5.5.1 中**没有**任何「半消息不占 ConsumeQueue」的开关，commitlog 侧也**没有**针对 half topic 的特殊 `PutMessageStatus` 分支。

## 事务 ID 与 opaque 的误解

> [!WARNING]
> **`opaque` 不是本地事务 ID，也不是 Producer 端的 `endTransactionOpaque`。**
>
> - 全仓 grep `endTransactionOpaque` → **零命中**（5.5.1 不存在）
> - `DefaultMQProducerImpl` 中 grep `opaque` → **零命中**
>
> `opaque` 的真实含义是 **remoting 层的请求-响应配对序号**（`remoting/.../protocol/RemotingCommand.java:89`）：
> ```java
> private int opaque = requestId.getAndIncrement();
> ```
> 它由 `NettyRemotingAbstract` 配合 `responseTable`（`ConcurrentMap<Integer /* opaque */, ResponseFuture>`，`:97`）匹配请求响应，**与事务毫无关系**。

**本地事务 ID 的真实载体**是消息属性：

| 常量 | 值 | 出处 |
| ---- | -- | ---- |
| `MessageConst.PROPERTY_UNIQ_CLIENT_MESSAGE_ID_KEYIDX` | `"UNIQ_KEY"` | `MessageConst.java:42` |
| `MessageConst.PROPERTY_TRANSACTION_ID` | `"__transactionId__"` | `MessageConst.java:53` |
| `TransactionalMessageUtil.TRANSACTION_ID` | `"__transactionId__"` | `TransactionalMessageUtil.java:35` |

`UNIQ_KEY` 由 `MessageClientIDSetter.createUniqID()` 生成（`:116`）。Broker 存 half 时把 `UNIQ_KEY` 复制为 `__transactionId__`（`TransactionalMessageBridge.java:220-223`）。

读取点（**只在事务消息场景**）：
- 消费端 `PullAPIWrapper.java:132-135` —— 仅当 `PROPERTY_TRANSACTION_PREPARED`（`"TRAN_MSG"`）为 true 时才 `msg.setTransactionId(msg.getProperty(PROPERTY_UNIQ_CLIENT_MESSAGE_ID_KEYIDX))`，普通消息该字段为空。
- 回查端 `ClientRemotingProcessor.java:106-109` 同样从该属性取。

> [!NOTE]
> 5.5.1 中 `GetMessageResponseHeader` 类**不存在**。

## 事务回查：两个方向要分清

> [!WARNING]
> 常见说法「Broker 主动 pull 事务回查消息」部分正确但**极易误导**。准确表述是**两个动作，方向不同**：

### 动作一：Broker pull half/op 消息（走 RocketMQ 自己的存储）

`TransactionalMessageServiceImpl.check()` 调 `getHalfMsg()` / `fillOpRemoveMap()`，最终 `TransactionalMessageBridge.java:112-124` 调 `store.getMessage(...)`，即 `DefaultMQPushConsumer` 式拉取。half 用 `new SubscriptionData(topic, "*")`。

**这是为了拿到「哪些消息还没定论」这个列表，属于消费语义。**

### 动作二：Broker 向 Producer 发 RPC（`CHECK_TRANSACTION_STATE`）

`broker/.../client/net/Broker2Client.java:74-88`：

```java
public void checkProducerTransactionState(final String group, final Channel channel,
        CheckTransactionStateRequestHeader requestHeader, final MessageExt messageExt) throws Exception {
    RemotingCommand request = RemotingCommand.createRequestCommand(
        RequestCode.CHECK_TRANSACTION_STATE, requestHeader);
    request.setBody(MessageDecoder.encode(messageExt, false));
    try {
        this.brokerController.getRemotingServer().invokeOneway(channel, request, 10);
    } catch (Exception e) { ... }
}
```

> [!IMPORTANT]
> 注意是 **`invokeOneway`（单向，10ms）** —— 结果**不回传 Broker**。Broker 发完就不管了，**由 Producer 另发 `END_TRANSACTION` 请求告知结果**。
>
> 这解释了为什么回查走单向：Broker 只需要「敲一下门」，最终答案由 Producer 主动送来，避免 Broker 阻塞等待。

请求码（`remoting/.../protocol/RequestCode.java`）：

| 常量 | 值 | 行号 |
| ---- | -- | ---- |
| `END_TRANSACTION` | **37** | 58 |
| `CHECK_TRANSACTION_STATE` | **39** | 61 |
| `NOTIFY_CONSUMER_IDS_CHANGED` | **40** | 63 |

> [!NOTE]
> `NOTIFY_CONSUMER_IDS_CHANGED` 与事务回查**无关**，是通知客户端消费组变化（`Broker2Client.java:96-108`）。`NotifyConsumerRequestChanged` 这个类**不存在**。

Producer 侧处理入口：`client/.../ClientRemotingProcessor.java:72-73`，注册于 `MQClientAPIImpl.java:336`。

### 调度器与配置

`TransactionalMessageCheckService`（`extends ServiceThread`）：

```java
// broker/.../transaction/TransactionalMessageCheckService.java:42-60
public void run() {
    while (!this.isStopped()) {
        long checkInterval = brokerController.getBrokerConfig().getTransactionCheckInterval();
        this.waitForRunning(checkInterval);
    }
}
protected void onWaitEnd() {
    long timeout = brokerController.getBrokerConfig().getTransactionTimeOut();
    int checkMax = brokerController.getBrokerConfig().getTransactionCheckMax();
    brokerController.getTransactionalMessageService().check(timeout, checkMax,
        brokerController.getTransactionalMessageCheckListener());
}
```

> [!WARNING]
> `common/.../BrokerConfig.java:283-301` 的真实默认值：
>
> | 字段 | 默认值 | 源码注释含义 |
> | ---- | ------ | ------------ |
> | `transactionTimeOut` | `6 * 1000` = **6000 ms** | 首次回查前的免疫时间 |
> | `transactionCheckMax` | **15** | 超过则丢弃该消息 |
> | `transactionCheckInterval` | `30 * 1000` = **30000 ms** | 回查间隔 |
>
> **两个常见错误**：
> - `transactionCheckInterval` 是 **30s，不是 60s**
> - `transactionTimeOut` 只有 **6 秒**，不是 6 分钟或其他

次数控制（`TransactionalMessageServiceImpl.java:108-121` `needDiscard`）：读 `PROPERTY_TRANSACTION_CHECK_TIMES`（`"TRANSACTION_CHECK_TIMES"`），`>= transactionCheckMax` 则丢弃（`listener.resolveDiscardMsg`），否则 `checkTime++` 写回。另有 `needSkip`（`:123-133`）：消息年龄超过 `fileReservedTime`（默认 72 小时）则跳过。

> [!IMPORTANT]
> **回查超限不是「告警」，而是直接丢弃消息。** `needDiscard` 达 15 次即调 `resolveDiscardMsg` 丢弃 —— 这本身就是「不保证强一致、允许丢弃」的直接证据。

## BrokerController 没有 checkTransactionalState

> [!WARNING]
> 全仓 grep `checkTransactionalState` → **零命中**。5.5.1 的 `BrokerController` **没有**该方法（4.x 资料里的常见写法）。

回查入口改为 `brokerController.getTransactionalMessageService().check(timeout, checkMax, listener)`。相关类：

| 类 | 路径 |
| -- | ---- |
| 接口 | `broker/.../transaction/TransactionalMessageService.java` |
| 实现 | `broker/.../transaction/queue/TransactionalMessageServiceImpl.java` |
| 调度器 | `broker/.../transaction/TransactionalMessageCheckService.java` |
| 监听器 | `broker/.../transaction/queue/DefaultTransactionalMessageCheckListener.java` |

## 三种回调结果的处理路径

Producer 侧（`client/.../producer/DefaultMQProducerImpl.java:403-436`）：

```java
switch (localTransactionState) {
    case COMMIT_MESSAGE:
        thisHeader.setCommitOrRollback(MessageSysFlag.TRANSACTION_COMMIT_TYPE); break;
    case ROLLBACK_MESSAGE:
        thisHeader.setCommitOrRollback(MessageSysFlag.TRANSACTION_ROLLBACK_TYPE); break;
    case UNKNOW:
        thisHeader.setCommitOrRollback(MessageSysFlag.TRANSACTION_NOT_TYPE);
        log.warn("when broker check, client does not know this transaction state, {}", thisHeader); break;
}
```

经 `endTransactionOneway(brokerAddr, thisHeader, remark, 3000)`（`:445-446`）发出 `END_TRANSACTION`，`fromTransactionCheck = true` 标记这是回查响应。

Broker 侧 `broker/.../processor/EndTransactionProcessor.java`：

| sysflag | 处理 |
| ------ | ---- |
| `TRANSACTION_NOT_TYPE` | `return null`（`:73-80` / `:105-112`）—— **不处理**，等下一轮回查，这是 `UNKNOW` 的兜底 |
| `TRANSACTION_COMMIT_TYPE` | `commitMessage` → `checkPrepareMessage` → `endMessageTransaction` → **`sendFinalMessage`（此时才建索引、对消费者可见）** → `deletePrepareMessage` → 指标 `addAndGet(topic, -1)`（`:131-165`） |
| `TRANSACTION_ROLLBACK_TYPE` | `rollbackMessage` → 写 Op 消息，仅打标不投递（`:166-175`） |

Slave 模式直接返回 `SLAVE_NOT_AVAILABLE`（`:65-69`）。

> [!NOTE]
> 官方文档 `docs/en/Design_Transaction.md` 说明了为什么 rollback 只能「打标」而非删除：*"RocketMQ can't actually delete a message because it is a sequential-write file"* —— 顺序写文件无法物理删除中间的消息。

## 完整时序

```
Producer                          Broker
  │ sendMessageInTransaction
  │ (HALF, "TRAN_MSG"未置位)
  │────────────────────────────────▶ store.asyncPutMessage(parseHalfMessageInner)
  │                                   topic=RMQ_SYS_TRANS_HALF_TOPIC, queueId=0
  │                                   REAL_TOPIC/REAL_QUEUE_ID 备份进 properties
  │  ◀────── SendResult(PUT_OK)
  │
  │ executeLocalTransaction()
  │
  │ endTransaction(END_TRANSACTION=37, commitOrRollback=0x8/0xC)
  │────────────────────────────────▶ EndTransactionProcessor
  │                                   commit: 删 half, 写最终消息到 REAL_TOPIC(建 CQ 索引)
  │                                   rollback: 仅写 Op 消息
  │
  │=== 若上述 END_TRANSACTION 丢失 ===│
  │                                   │
  │        TransactionalMessageCheckService (每 30s)
  │          check(): pull RMQ_SYS_TRANS_HALF_TOPIC + RMQ_SYS_TRANS_OP_HALF_TOPIC
  │             维护 removeMap/opMsgMap 判断 half 是否已有 op 消息(已定论则跳过)
  │             needDiscard(>=15次) / needSkip(>72h) / storeTimestamp>=startTime(新鲜) -> 跳过
  │             age > transactionTimeOut(6s) -> listener.resolveHalfMsg(msgExt)
  │                                   │
  │  ◀── invokeOneway(CHECK_TRANSACTION_STATE=39, body=MessageEncoder(msg))
  │ ClientRemotingProcessor.checkTransactionState
  │   -> TransactionListener.checkLocalTransaction(msg)
  │
  │ endTransactionOneway(END_TRANSACTION=37, fromTransactionCheck=true)
  │────────────────────────────────▶ 补偿到达
```

## 用户侧 API

### TransactionListener

`client/.../producer/TransactionListener.java:22-39`：

```java
public interface TransactionListener {
    LocalTransactionState executeLocalTransaction(final Message msg, final Object arg);
    LocalTransactionState checkLocalTransaction(final MessageExt msg);
}
```

> [!WARNING]
> 两个方法名都有坑：
> - 第一个是 **`executeLocalTransaction`**，常见资料写的 `localTransaction` **不存在**
> - 第二个是 **`checkLocalTransaction`**，不是 `checkMessage`
>
> 参数类型也不同：前者 `(Message, Object)`，后者 `(MessageExt)`（**仅一个参数**）。

`client/.../producer/LocalTransactionState.java:19-23`：

```java
public enum LocalTransactionState {
    COMMIT_MESSAGE,
    ROLLBACK_MESSAGE,
    UNKNOW,      // ⚠️ 源码即如此，缺末尾 N
}
```

> [!WARNING]
> 第三个枚举值拼写是 **`UNKNOW`**（不是 `UNKNOWN`）—— 源码就是这样，写代码时必须照抄。

### TransactionMQProducer

`client/.../producer/TransactionMQProducer.java:26-34`：

```java
public class TransactionMQProducer extends DefaultMQProducer {
    private TransactionCheckListener transactionCheckListener;
    private int checkThreadPoolMinSize = 1;
    private int checkThreadPoolMaxSize = 1;
    private int checkRequestHoldMax = 2000;
    private ExecutorService executorService;
    private TransactionListener transactionListener;
```

### @RocketMQTransactionListener 不在 5.5.1 主仓库

> [!WARNING]
> 全仓 grep `RocketMQTransactionListener` → **零命中**；模块列表无 `spring/`；grep `rocketmq-spring` 于 pom → 零命中。**5.5.1 主仓库已不含 Spring 支持。**
>
> 因此注解及其属性 `rocketMQTemplateBeanName`、`corePoolSize`、`maxReconsumeTimes` **在本 tag 内未查到** —— 它们属于独立的 `rocketmq-spring-boot-starter` 项目（`apache/rocketmq-spring`），需要另去那个仓库核实，不能挂在 5.5.1 名下。

## 与 Spring 事务 / XA / Seata 的关系

> [!NOTE]
> **未查到**源码或 5.5.1 仓内文档中对 "XA"、"Seata"、"AT 模式"、"强一致/最终一致" 的任何直接表述（grep 无命中）。以下是基于源码事实的推断，不是官方引用。

可从源码确认的机制性事实：

1. half 消息第一阶段对用户不可见（靠改 topic），靠**回查补偿**保证最终落地 —— 这是 2PC + 补偿。
2. `needDiscard` 达 15 次即 `resolveDiscardMsg` **丢弃** —— 允许丢弃，**不保证强一致**。
3. rollback 只能写 Op 消息打标，**无法物理删除** —— 因为顺序写文件。

官方 `docs/en/Design_Transaction.md` 的定位表述是：*"RocketMQ implements transaction message by using the protocol of 2PC(two-phase commit), in addition adding a compensation logic to handle timeout-case or failure-case of commit-phase"*。

按此可判断它与 Seata AT 的差异：AT 靠 undo_log 自动生成反向补偿，RocketMQ **不生成反向补偿**，只做「问清楚再定论」；且 RocketMQ 的回查是**有次数上限的**，超了直接丢，而 Seata AT 的全局事务会一直重试回滚。

## 死信与重试 topic 前缀

`common/.../MixAll.java:103-104`：

```java
public static final String RETRY_GROUP_TOPIC_PREFIX = "%RETRY%";
public static final String DLQ_GROUP_TOPIC_PREFIX = "%DLQ%";
```

> [!TIP]
> `%RETRY%` / `%DLQ%` **正确**。常量名是 `RETRY_GROUP_TOPIC_PREFIX` / `DLQ_GROUP_TOPIC_PREFIX`，**不是** `DLQ_NAMESPACE`（后者不存在）。
>
> `TopicValidator` 注释（`:44-47`）确认 retry/DLQ topic 形如 `%RETRY%group_topic`，故 `GROUP_MAX_LENGTH = 120`、`RETRY_OR_DLQ_TOPIC_MAX_LENGTH = 255`（`:48-49`）。

### 定时清理

> [!WARNING]
> **`checkExpireMessage` 不存在**（全仓零命中）。实际机制在 `store/.../DefaultMessageStore.java:1931-1938` `addScheduleTask()`：

```java
this.scheduledExecutorService.scheduleAtFixedRate(new Runnable() {
    public void run() { DefaultMessageStore.this.cleanFilesPeriodically(); }
}, 1000 * 60, this.messageStoreConfig.getCleanResourceInterval(), TimeUnit.MILLISECONDS);
```

首次延迟 60s，周期 `cleanResourceInterval`（默认 10000 ms）。命令行工具：`tools/.../broker/DeleteExpiredCommitLogSubCommand.java`、`CleanExpiredCQSubCommand.java`。

**未查到**：Op 消息（`RMQ_SYS_TRANS_OP_HALF_TOPIC`）有任何独立的过期清理逻辑 —— 它依赖 CommitLog 文件级过期被一并清理。

## 实践要点

| 事项 | 建议 |
| ---- | ---- |
| `transactionCheckInterval` 调优 | 30s 是默认值。回查频繁会增加 Broker/Producer 压力；对延迟敏感业务可调小，但要保证 `transactionTimeOut`（6s）足够覆盖正常事务执行时间 |
| `transactionCheckMax` 调优 | 默认 15 次 × 30s ≈ 7.5 分钟后丢弃。重要业务应**在业务侧保证 `checkLocalTransaction` 永不返回 `UNKNOW`** |
| `checkLocalTransaction` 实现要点 | **必须是幂等的**（可能被调用多次）；**必须能查到真实结果**（不能依赖内存状态，Producer 可能已重启）；查不到就返回 `UNKNOW` 而非猜一个 |
| `executeLocalTransaction` 实现要点 | 抛异常时状态由框架处理，但业务代码应捕获并返回明确状态 |
| 半消息堆积 | half topic 长时间不 commit/rollback 会被回查直到丢弃。监控 `RMQ_SYS_TRANS_HALF_TOPIC` 的堆积量 |
| 消费者侧 | 事务消息对消费者是**完全透明的** —— 消费者不需要任何特殊处理，只看到「最终可见的消息」 |
| 与 Seata 混用 | 两者解决的问题不同（Seata 管跨服务数据库事务，RocketMQ 管消息可达性）。可配合使用但需注意：RocketMQ 事务**允许丢弃**，Seata 侧重补偿，混用时不要指望 RocketMQ 侧的「已提交」等于「数据一定正确」 |

## 5.x 补充

5.5.1 新增 `proxy/service/transaction/` 包支持 Proxy 模式下的事务消息：`TransactionService`、`AbstractTransactionService`、`ClusterTransactionService`、`LocalTransactionService`、`TransactionData`、`TransactionDataManager`、`EndTransactionRequestData`。

`ProxyConfig` 相关默认值：

| 字段 | 默认值 |
| ---- | ------ |
| `maxTransactionRecoverySecond` | `Duration.ofHours(1)` |
| `transactionHeartbeatPeriodSecond` | `20` |
| `transactionDataMaxNum` | `15` |

## Links

- [Apache RocketMQ](/docs/CS/MQ/RocketMQ/RocketMQ.md)
- [Broker](/docs/CS/MQ/RocketMQ/Broker.md)
- [Producer](/docs/CS/MQ/RocketMQ/Producer.md)
- [Consumer](/docs/CS/MQ/RocketMQ/Consumer.md)
- [Store](/docs/CS/MQ/RocketMQ/Store.md)
- [Seata](/docs/CS/Framework/Seata/Seata.md)

## References

1. [RocketMQ 5.5.1 Release](https://github.com/apache/rocketmq/releases/tag/rocketmq-all-5.5.1)
2. [MessageSysFlag.java (5.5.1)](https://github.com/apache/rocketmq/blob/rocketmq-all-5.5.1/common/src/main/java/org/apache/rocketmq/common/sysflag/MessageSysFlag.java)
3. [TransactionalMessageBridge.java (5.5.1)](https://github.com/apache/rocketmq/blob/rocketmq-all-5.5.1/broker/src/main/java/org/apache/rocketmq/broker/transaction/queue/TransactionalMessageBridge.java)
4. [RocketMQ 官方 Design_Transaction 文档](https://github.com/apache/rocketmq/blob/rocketmq-all-5.5.1/docs/en/Design_Transaction.md)
