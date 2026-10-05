## Introduction

RocketMQ 的消息过滤分两个层级：**Tag 过滤**（精确匹配 tag 字符串）和 **SQL92 过滤**（属性级表达式）。两者的实现位置、开关、精度都不同，而且**几乎所有常见资料都写错了**。

> 版本基线：**5.5.1**（tag `rocketmq-all-5.5.1`）。

## 三大误解先纠正

| 常见说法 | 5.5.1 真相 |
| -------- | --------- |
| SQL92 过滤用 Calcite 解析 | ❌ **完全不含 Calcite**。用 JavaCC 手写语法解析器 + AST 解释执行 |
| `enablePropertyFilter` 默认 `true` | ❌ **默认 `false`**。这是 SQL92 能否工作的总开关，不开直接报 `SYSTEM_ERROR` |
| 多 Tag 会按分隔符切分成多个 hash | ❌ `tagsString2tagsCode` **完全忽略** `filter` 参数，只对整串 `tag1 || tag2` 做一次 `hashCode()` |

## 属性名常量

`common/src/main/java/org/apache/rocketmq/common/message/MessageConst.java`：

| 字段名 | 字符串值 | 行号 |
| ------ | -------- | ---- |
| `PROPERTY_KEYS` | `"KEYS"` | 22 |
| `PROPERTY_TAGS` | `"TAGS"` | 23 |
| `PROPERTY_BUYER_ID` | `"BUYER_ID"` | 34 |
| `PROPERTY_UNIQ_CLIENT_MESSAGE_ID_KEYIDX` | `"UNIQ_KEY"` | 42 |
| `PROPERTY_DELAY_TIME_LEVEL` | `"DELAY"` | 25 |
| `PROPERTY_RETRY_TOPIC` | `"RETRY_TOPIC"` | 26 |
| `KEY_SEPARATOR` | `" "`（空格） | 93 |

> [!WARNING]
> 两个常见错误：
> - 属性名常量在 **`MessageConst`**，**不在 `MessageDecoder`**。grep `PROPERTY_TAGS|PROPERTY_KEYS` 在 `MessageDecoder.java` 中**零命中**。
> - 真实常量名是 `PROPERTY_UNIQ_CLIENT_MESSAGE_ID_KEYIDX`，**没有** `_INDEXCHARS` 后缀。写成 `PROPERTY_UNIQ_CLIENT_MESSAGE_ID_KEY_INDEXCHARS` 是错的。
>
> `MessageDecoder` 里只有 `NAME_VALUE_SEPARATOR = 1`（`\u0001`，`:53`），是属性串的 KV 分隔符。

## Tag 过滤

### 实现位置是 remoting 模块，不是 TagFilter 类

> [!WARNING]
> **`TagFilter` 类不存在**（common/client 均无）。`TagFilterProducer` / `TagFilterConsumer` 只是 `example/.../filter/` 下的示例类。
>
> 真实实现是 **`remoting/src/main/java/org/apache/rocketmq/remoting/protocol/filter/FilterAPI.java`**。

```java
// remoting/.../filter/FilterAPI.java:27-47
public static SubscriptionData buildSubscriptionData(String topic, String subString) throws Exception {
    final SubscriptionData subscriptionData = new SubscriptionData();
    subscriptionData.setTopic(topic);
    subscriptionData.setSubString(subString);
    if (StringUtils.isEmpty(subString) || subString.equals(SubscriptionData.SUB_ALL)) {
        subscriptionData.setSubString(SubscriptionData.SUB_ALL);
        return subscriptionData;
    }
    String[] tags = subString.split("\\|\\|");
    if (tags.length > 0) {
        Arrays.stream(tags).map(String::trim).filter(tag -> !tag.isEmpty()).forEach(tag -> {
            subscriptionData.getTagsSet().add(tag);
            subscriptionData.getCodeSet().add(tag.hashCode());
        });
    } else { throw new Exception("subString split error"); }
    return subscriptionData;
}
```

- 分隔符是正则 `"\\|\\|"`（字面 `||`），切分后 `trim()` 并丢弃空串
- `SubscriptionData.SUB_ALL = "*"`（`remoting/.../heartbeat/SubscriptionData.java:30`）

> [!TIP]
> **`*` 不做通配匹配，而是整体订阅全部。** `subString.equals("*")` 时直接返回，`codeSet`/`tagsSet` 为空集就表示订阅所有。所以 `tag*` 这种「前缀匹配」**不被支持** —— 想要前缀语义只能用 SQL92 的 `LIKE`。

`SubscriptionData` 同时维护两个集合（`SubscriptionData.java:34-35`）：

| 字段 | 类型 | 用途 |
| ---- | ---- | ---- |
| `tagsSet` | `Set<String>` | 精确串，客户端精筛用 |
| `codeSet` | `Set<Integer>` | hash，Broker 端 CQ 预筛用 |

`classFilterMode` 字段（`:31`，默认 false）**仍然存在**，但见下文「类过滤已失效」。

### 多 Tag 的 tagsCode 是整串的 hash

> [!WARNING]
> `MessageExtBrokerInner.tagsString2tagsCode`（`common/.../message/MessageExtBrokerInner.java:46-50`）：
> ```java
> public static long tagsString2tagsCode(final TopicFilterType filter, final String tags) {
>     if (Strings.isNullOrEmpty(tags)) { return 0; }
>     return tags.hashCode();
> }
> ```
> **`filter` 参数被完全忽略** —— 没有逗号/空格切分。ConsumeQueue 里的 `tagsCode` 是**整个 `tag1 || tag2` 拼接串的 hashCode**，不是各 tag 的 hash。
>
> 这就是 Broker 端无法对多 Tag 做精确匹配的根本原因，精确匹配**必须**在客户端做。

Broker 端只打标记位，不做切分（`broker/.../processor/SendMessageProcessor.java:235-239`、`AbstractSendMessageProcessor.java:406-410`）：

```java
if (TopicFilterType.MULTI_TAG == topicConfig.getTopicFilterType()) {
    sysFlag |= MessageSysFlag.MULTI_TAGS_FLAG;
}
```

`MULTI_TAGS_FLAG = 0x1 << 1`（`MessageSysFlag.java:34`，byte1 的 bit1），消费端由 `MessageExt.parseTopicFilterType(sysFlag)`（`MessageExt.java:63-69`）还原。

> [!NOTE]
> `MULTI_TAGS_DISPATCH_TAG_SPLIT_CHAR` 与 `checkMessageTag` 在 5.5.1 中**均不存在**（全仓零命中）。

## SQL92 过滤

### SQL92 是表达式类型，不是消息属性

> [!WARNING]
> **`PROPERTY_SQL92` 不存在**（全仓零命中）。SQL92 不是消息属性名，而是**订阅的表达式类型**：
> ```java
> // common/.../filter/ExpressionType.java:52
> public static final String SQL92 = "SQL92";
> // :59  TAG = "TAG"
> // :61-64  isTagType()
> ```

### FilterAPI 在 remoting 模块

`remoting/src/main/java/org/apache/rocketmq/remoting/protocol/filter/FilterAPI.java`。

> [!WARNING]
> **`FilterAPI` 中没有 `buildFilter` / `buildClassFilter`**（零命中）。实际入口是三个：
> - `buildSubscriptionData(topic, subString)`（`:27`）
> - `buildSubscriptionData(topic, subString, expressionType)`（`:49`）
> - `build(topic, subString, type)`（`:57`）
>
> 签名均为 `throws Exception`。

### 表达式引擎是 JavaCC，不是 Calcite

> [!IMPORTANT]
> **5.5.1 全仓不含 Calcite** —— `grep -rn -i calcite`（含所有 pom.xml）→ **零命中**。类 `FilterExpression`、`SQLOperator` **不存在**。
>
> 真实实现是 **JavaCC 手写语法解析器 + 解释执行的 AST**（源自 ActiveMQ 的 `SelectorParser`）：
>
> | 要素 | 位置 |
> | ---- | ---- |
> | 模块 | `filter/`（artifactId `rocketmq-filter`），依赖仅 `rocketmq-common`、`rocketmq-srvutil`、`guava`（**无 SQL 引擎依赖**）|
> | 语法文件 | `filter/.../parser/SelectorParser.jj`（头部注释写明取自 ActiveMQ `SelectorParser.jj`，并列出对 LIKE/ESCAPE/XPATH/计算表达式的删减）|
> | 编译入口 | `filter/.../SqlFilter.java:32-36` → `SelectorParser.parse(expr)` |
> | AST 节点 | `filter/.../expression/`：`BooleanExpression`、`BinaryExpression`、`ComparisonExpression`、`LogicExpression`、`PropertyExpression`、`UnaryExpression`、`UnaryInExpression`、`ConstantExpression`，均实现 `Expression`（`evaluate(EvaluationContext)`）|
> | 执行 | `broker/.../filter/ExpressionMessageFilter.java:143-158` |

```java
// filter/.../SqlFilter.java:32-36
public class SqlFilter implements FilterSpi {
    public Expression compile(final String expr) throws MQFilterException {
        return SelectorParser.parse(expr);
    }
```

```java
// broker/.../filter/ExpressionMessageFilter.java:143-158
MessageEvaluationContext context = new MessageEvaluationContext(tempProperties);
ret = realFilterData.getCompiledExpression().evaluate(context);
...
return (Boolean) ret;   // 非 Boolean 一律 false
```

`ExpressionMessageFilter` **无状态且可复用**（持有 `subscriptionData` + `consumerFilterData`），**解释执行，无字节码生成**。

> [!NOTE]
> 性能优化靠 **BloomFilter**：`filter/util/BloomFilter.java` + `BitsArray`，由 `ConsumerFilterManager` 维护。`maxErrorRateOfBloomFilter = 20`（`BrokerConfig.java:171`），数据存于 ConsumeQueue **ext 文件**（`ConsumeQueueExt.CqExtUnit`）。预筛逻辑在 `ExpressionMessageFilter.java:89-107`。
>
> 注意 BloomFilter 未命中或位图长度不符时**保守放行**（返回 true）—— 宁可放过不可错杀。

### enablePropertyFilter 默认是 false

```java
// common/.../BrokerConfig.java:176-178
// whether do filter when retry.
private boolean filterSupportRetry = false;
private boolean enablePropertyFilter = false;
```

> [!IMPORTANT]
> **默认 `false`，不是 `true`。** 5.5.1 的 `example/.../filter/SqlFilterConsumer.java:34` 甚至留了提示注释：
> ```java
> // Don't forget to set enablePropertyFilter=true in broker
> ```
>
> 这是「配了 SQL92 订阅却完全不过滤」的头号原因。

唯一使用点 `broker/.../processor/PullMessageProcessor.java:478-492`：

```java
if (!ExpressionType.isTagType(subscriptionData.getExpressionType())
    && !this.brokerController.getBrokerConfig().isEnablePropertyFilter()) {
    response.setCode(ResponseCode.SYSTEM_ERROR);
    response.setRemark("The broker does not support consumer to filter message by " + ...);
    return response;
}
MessageFilter messageFilter;
if (this.brokerController.getBrokerConfig().isFilterSupportRetry()) {
    messageFilter = new ExpressionForRetryMessageFilter(...);
} else {
    messageFilter = new ExpressionMessageFilter(...);
}
```

关系表：

| 表达式类型 | 需要 `enablePropertyFilter=true` | 说明 |
| ---------- | ------------------------------ | ---- |
| `TAG` | ❌ 不需要 | 走 CQ hash 预筛，**恒开** |
| `SQL92` | ✅ **必须** | 否则 Pull 请求直接返回 `SYSTEM_ERROR` |

另有 `filterSupportRetry`（默认 false）决定是否用 `ExpressionForRetryMessageFilter` 包裹（对重试消息放宽过滤条件）。

> [!NOTE]
> **`enableTagMessageFiltering` 不存在**（全仓零命中）—— 5.x 已统一到 `enablePropertyFilter`。

## 过滤发生在什么时候

> [!WARNING]
> **写盘时完全不过滤。** 常见误解是「commitlog 空间不足时返回 FILTERED_MESSAGE」——5.5.1 中：
> - `CommitLog#asyncPutMessage`（`CommitLog.java:999` 起）只做时间戳/CRC/版本/bornHost 填充，grep `maxFilterMessageSize`、`FILTERED_MESSAGE` **零命中**
> - **`FILTERED_MESSAGE` 这个状态不存在**。`PutMessageStatus` 共 16 项：`PUT_OK`、`FLUSH_DISK_TIMEOUT`、`FLUSH_SLAVE_TIMEOUT`、`SLAVE_NOT_AVAILABLE`、`SERVICE_NOT_AVAILABLE`、`CREATE_MAPPED_FILE_FAILED`、`MESSAGE_ILLEGAL`、`PROPERTIES_SIZE_EXCEEDED`、`OS_PAGE_CACHE_BUSY`、`UNKNOWN_ERROR`、`IN_SYNC_REPLICAS_NOT_ENOUGH`、`PUT_TO_REMOTE_BROKER_FAIL`、`LMQ_CONSUME_QUEUE_NUM_EXCEEDED`、`WHEEL_TIMER_FLOW_CONTROL`、`WHEEL_TIMER_MSG_ILLEGAL`、`WHEEL_TIMER_NOT_ENABLE`
> - `ResponseCode` 里也没有 `FILTERED_MESSAGE`（只有 `MESSAGE_ILLEGAL = 13`）
> - `DefaultMessageStore#isMessageFull` 与 `MSG_CHECK*` 异常**均不存在**
>
> `CommitLog.java:757`、`:1429` 的 `mappedFile.isAvailable()` 是**文件可写**检查，与过滤无关。

### 过滤在读路径，且是「预筛 + 精判」两级

`DefaultMessageStore.getMessage` 内（`DefaultMessageStore.java:974-1000`）：

```java
// ① 先用 ConsumeQueue 预筛
if (messageFilter != null
    && !messageFilter.isMatchedByConsumeQueue(cqUnit.getValidTagsCodeAsLong(), cqUnit.getCqExtUnit())) {
    if (getResult.getBufferTotalSize() == 0) { status = GetMessageStatus.NO_MATCHED_MESSAGE; }
    continue;                        // 不读 CommitLog
}
SelectMappedBufferResult selectResult = this.commitLog.getMessage(offsetPy, sizePy);
// ② 读了 CommitLog 再精确判定
if (messageFilter != null
    && !messageFilter.isMatchedByCommitLog(selectResult.getByteBuffer().slice(), null)) {
    ...
    continue;
}
```

`MessageFilter` 接口（`store/.../MessageFilter.java:30-42`）两个方法：

| 方法 | 用途 |
| ---- | ---- |
| `isMatchedByConsumeQueue(Long tagsCode, CqExtUnit)` | 预筛（tagHash / BloomFilter）|
| `isMatchedByCommitLog(ByteBuffer, Map<String,String>)` | 精确判定（SQL92）|

### 三级过滤链

| 级别 | 位置 | 判据 | 精度 |
| ---- | ---- | ---- | ---- |
| ① Broker CQ 预筛 | `ExpressionMessageFilter.isMatchedByConsumeQueue`（`:60-80`）| `subscriptionData.getCodeSet().contains(tagsCode.intValue())` | hash 粗筛，可能误放 |
| ② Broker CommitLog 精判 | `isMatchedByCommitLog`（`:117-158`）| `compiledExpression.evaluate(context)` | 属性级精确（**仅 SQL92**）|
| ③ 客户端 tag 精筛 | `PullAPIWrapper`（`:113-122`）| `subscriptionData.getTagsSet().contains(msg.getTags())` | **tag 字符串精确** |

> [!IMPORTANT]
> `isMatchedByCommitLog` 对 **Tag 类型直接 `return true`**（`:126-128`）—— **Broker 端从不对 Tag 做精确判定**，只靠客户端 ③。

### 客户端过滤的调用点在 PullAPIWrapper

`client/.../impl/consumer/PullAPIWrapper.java:112-129`：

```java
List<MessageExt> msgListFilterAgain = msgList;
if (!subscriptionData.getTagsSet().isEmpty() && !subscriptionData.isClassFilterMode()) {
    msgListFilterAgain = new ArrayList<>(msgList.size());
    for (MessageExt msg : msgList) {
        if (msg.getTags() != null) {
            if (subscriptionData.getTagsSet().contains(msg.getTags())) {
                msgListFilterAgain.add(msg);
            }
        }
    }
}
if (this.hasHook()) { ... this.executeHook(filterMessageContext); }
```

> [!WARNING]
> 常见资料说「`executeHookBeforeFilterMessage` / `filterMessage` 在 `DefaultMQPushConsumerImpl#pullMessage` 中」——**调用点定位有误**：
> - Tag 精确过滤在 **`PullAPIWrapper`**（`:112-122`），是**内联循环，没有独立方法名**
> - `hook.filterMessage(context)` 在 `PullAPIWrapper.java:170-173` 的 `executeHook` 中，**在 Tag 过滤之后**执行
> - `DefaultMQPushConsumerImpl` 中只有 `filterMessageHookList`（`:119`）与注册（`registerFilterMessageHook`，由 `DefaultMQPushConsumerImpl.java:950` 调用）
> - `DefaultMQPushConsumerImpl.java:638-645` 另有一处 hook 调用，处理 unpack 后的 `msgListFilterAgain`

## 为什么过滤主要发生在消费端

官方文档 `docs/en/Design_Filter.md` 说得很直接：

> *"It's do the filter when the messages are subscribed via **consumer side**… Consumer side will get an index from a logical message queue ConsumeQueue when subscribing, then read message entity from CommitLog using the index."*
>
> *"it is **unable to filter the messages exactly in the server side** because of only the hashcode will be used when filtering, Therefore, **after the Consumer pulls the message, it also needs to compare the original tag string** of the message. If the original tag string is not same with the expected, the message will be ignored."*

**根因**：ConsumeQueue 只存 `tagsCode`（8 字节 hash），**没有原始 tag 字符串**。Broker 端无法做精确判定（多 Tag 场景下 `tagsCode` 还是整串 hash，见上文）。

### tagHashCode 在 20 字节单元中的角色

`store/.../ConsumeQueue.java:64-65`：

```java
public static final int CQ_STORE_UNIT_SIZE = 20;
public static final int MSG_TAG_OFFSET_INDEX = 12;   // ← tagsCode 的偏移
```

第 3 个字段（offset 12 起）即 `tagsCode`，20 字节布局：

```
┌───────────────────────────────┬───────────────────┬───────────────────────────────┐
│CommitLog Physical Offset (8B) │  Body Size (4B)   │  Tag HashCode (8B)  ← 12    │
└───────────────────────────────┴───────────────────┴───────────────────────────────┘
```

### 性能含义

由于 Broker 端只有 hash 粗筛，客户端 ③ 之前**可能已拉回大量 tag 不匹配的消息** → 产生无效网络流量与客户端内存/CPU 开销。

> [!TIP]
> 实践建议：订阅端**尽量用 `||` 精确声明所需 tag**，而不是 `*` 全量订阅 + 客户端过滤。全量订阅时 Broker 端的 hash 预筛会全部放行，等于过滤完全失效。
>
> 若需要前缀/正则/嵌套条件等复杂语义，必须走 SQL92 且**开 `enablePropertyFilter=true`**，并接受额外的 BloomFilter 内存与 CPU 开销。

## 类过滤已失效

> [!WARNING]
> **`enableClassFilter` 配置项在 5.5.1 不存在**（全仓零命中）。已统一为 `enablePropertyFilter`。
>
> 残留的类过滤痕迹**均为协议层遗留，无可用实现**：
> - `common/.../sysflag/PullSysFlag.java:23` `FLAG_CLASS_FILTER = 0x1 << 3`，`:43` 设置，`:85` `hasClassFilterFlag()`
> - `SubscriptionData.classFilterMode`（`:31`，`isClassFilterMode()` `:100-101`）
> - `ExpressionMessageFilter.java:65-67` 与 `:122-124`：`if (subscriptionData.isClassFilterMode()) return true;` —— **直接放行**
> - `RegisterMessageFilterClassRequestHeader` 仅存于 `test/src/test/resources/schema/`（测试 schema 残留），**无生产代码实现**
>
> `isValidConsumerGroup` → **未查到**（零命中）。
>
> **结论：任何 `classFilterMode = true` 的订阅会被全量放行**，即 4.x 时代「服务端类过滤白名单」的功能在 5.x 已经完全没有了。

## maxFilterMessageSize 的真实语义

`maxFilterMessageSize = 16000`（`MessageStoreConfig.java:206`）：

```java
// DefaultMessageStore.java:914
final int maxFilterMessageSize = Math.max(this.messageStoreConfig.getMaxFilterMessageSize(),
                                          maxMsgNums * consumeQueue.getUnitSize());
// :951 —— 遍历 CQ 单元的内层循环
if ((cqUnit.getQueueOffset() - offset) * consumeQueue.getUnitSize() >= maxFilterMessageSize) {
    break;
}
```

> [!IMPORTANT]
> **它是读路径上「单次拉取最多扫描多远就放弃」的上限，与 CommitLog 文件空间、filter 文件都无关。**
>
> 语义：从消费者请求的 offset 起，按 CQ 单元累加，超过 16000 字节（≈800 条消息）就 `break`，**防止为一条已被过滤掉的消息扫完整条队列**。`Math.max` 保证不会小于本次请求条数所需的 CQ 字节数。
>
> 想调大以支持「稀疏匹配 + 长区间扫描」的场景可以调，但会拉长单次 Pull 的响应时间。

## 实践要点

| 事项 | 建议 |
| ---- | ---- |
| SQL92 过滤不生效 | 首选检查 `enablePropertyFilter`（默认 false）；确认订阅的 `expressionType` 是不是 `SQL92`（用 `*` 或普通 tag 会被判为 TAG 类型）|
| 过滤性能 | Tag 精确声明而非 `*`；SQL92 需在 `Message` 上放**可索引属性**（如 `orderId`），避免全量扫描 |
| `enablePropertyFilter=true` 的代价 | Broker 端会构造 `ExpressionMessageFilter` 并维护 BloomFilter，占用额外内存；`maxErrorRateOfBloomFilter=20` 意味着有误判率 |
| SQL92 不支持的能力 | 无 `LIKE`/`ESCAPE`/XPATH/计算表达式（JavaCC 语法已删减）；`TAG` 与 `SQL92` 互斥，不能同时在一个订阅里混用 |
| 类过滤 | **5.x 已废弃**，别用 |
| 多 Tag 订阅 | `A || B` 在 Broker 端只存整串 hash，客户端才能精确匹配 → 客户端 CPU 开销与 tag 数成正比 |
| SQL92 与死信 | 过滤条件对**重试消息**可能不适用，`filterSupportRetry=true` 可对重试消息放宽 |

## Links

- [Apache RocketMQ](/docs/CS/MQ/RocketMQ/RocketMQ.md)
- [Broker](/docs/CS/MQ/RocketMQ/Broker.md)
- [Consumer](/docs/CS/MQ/RocketMQ/Consumer.md)
- [Store](/docs/CS/MQ/RocketMQ/Store.md)
- [事务消息](/docs/CS/MQ/RocketMQ/Transaction.md)

## References

1. [RocketMQ 5.5.1 Release](https://github.com/apache/rocketmq/releases/tag/rocketmq-all-5.5.1)
2. [FilterAPI.java (5.5.1)](https://github.com/apache/rocketmq/blob/rocketmq-all-5.5.1/remoting/src/main/java/org/apache/rocketmq/remoting/protocol/filter/FilterAPI.java)
3. [SelectorParser.jj (5.5.1)](https://github.com/apache/rocketmq/blob/rocketmq-all-5.5.1/filter/src/main/java/org/apache/rocketmq/filter/parser/SelectorParser.jj)
4. [RocketMQ Design_Filter 文档](https://github.com/apache/rocketmq/blob/rocketmq-all-5.5.1/docs/en/Design_Filter.md)
