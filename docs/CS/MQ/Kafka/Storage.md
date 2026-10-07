## Introduction

Kafka 的存储引擎围绕一个核心取舍：**用「顺序写 + 稀疏索引」换取吞吐，代价是消息不能就地修改、删除只能是截断或重写**。理解这一点,才能理解 retention、compaction、unclean leader election 等一系列看似奇怪的行为。

> 版本基线：**4.3.1**（`gradle.properties:17` `version=4.3.1`），2026-06-25 发布。

```tex
partition 目录（log.dir / tmp/kafka-logs）
├── 00000000000000000000.log            ← 消息数据（顺序追加）
├── 00000000000000000000.index          ← 稀疏索引：offset → position
├── 00000000000000000000.timeindex      ← 稀疏索引：timestamp → offset
├── 00000000000000000001.log
├── ...
└── __leader_epoch                      ← partition 级（不是段级！）
```

## 4.3.1 Package Paths Have Migrated (Old Docs Will Not Find Files)

> [!WARNING]
> `kafka.log` 包已整体迁到 **`storage` 模块的 Java 包** `org.apache.kafka.storage.internals.log`。整个 4.3.1 树里 `.scala` 文件只剩 309 个。
>
> | 旧资料路径 | 4.3.1 实际 |
> | ---------- | ---------- |
> | `core/src/main/scala/kafka/log/LogConfig.scala` | `storage/src/main/java/org/apache/kafka/storage/internals/log/LogConfig.java` |
> | `core/src/main/scala/kafka/server/KafkaConfig.scala` | 仍在 `core/src/main/scala/kafka/server/KafkaConfig.scala`（配置项来源已改成 `server-common`）|
> | `connect/connect-runtime` | `connect/runtime` |
> | `core/src/main/scala/kafka/config/` | `server-common/src/main/java/org/apache/kafka/server/config/` |
> | `SaslServerConfigs.java` | **不存在** |
>
> 更重要的是：**`LogConfig.java` 只有 66 处 `define(`，且不含任何 retention 配置** —— 常量与 ConfigDef 定义已拆分到 `server-common/.../ServerLogConfigs.java`（179 行）。查默认值要去对的地方。

## Segment File Structure

`storage/src/main/java/org/apache/kafka/storage/internals/log/LogFileUtils.java:27-67`：

| 后缀 | 常量 | 行号 | 用途 |
| ---- | ---- | ---- | ---- |
| `.log` | `LOG_FILE_SUFFIX` | 37 | 消息数据 |
| `.index` | `INDEX_FILE_SUFFIX` | 42 | 稀疏索引 offset→position |
| `.timeindex` | `TIME_INDEX_FILE_SUFFIX` | 47 | 稀疏索引 timestamp→offset |
| **`.txnindex`** | `TXN_INDEX_FILE_SUFFIX` | 52 | **4.x 事务索引** |
| `.snapshot` | `PRODUCER_SNAPSHOT_FILE_SUFFIX` | 27 | producer id/epoch 快照 |
| `.cleaned` | `CLEANED_FILE_SUFFIX` | 55 | compaction 标记 |
| `.swap` | `SWAP_FILE_SUFFIX` | 58 | 进程崩溃时未清理的临时段 |
| `.deleted` | `DELETED_FILE_SUFFIX` | 32 | 待删除标记 |
| `-delete` / `-future` / `-stray` | 目录后缀 | 61/64/67 | 目录级 |

> [!WARNING]
> **两个常见误解**：
> - **没有 `leader-epoch-checkpoint` 段文件**。leader epoch 由 `leaderEpochCache` 独立管理（`UnifiedLog.java:2356,2369`），checkpoint 写在 **partition 目录级**（`__leader_epoch`），不是每个 segment。
> - **没有 `partition.metadata` 文件**（4.x 已移除）。

## Sparse Index and Binary Search

`storage/.../OffsetPosition.java:23` 定义了索引条目：

```java
public record OffsetPosition(long offset, int position) implements IndexEntry {
```

javadoc（`:19-22`）说明了 offset 与 position 的区别：

> "The mapping between a logical log **offset** and the physical **position** in some log file of the beginning of the message set entry with the given offset."

- `offset` = **逻辑**消息序号（Kafka 用户可见的坐标系）
- `position` = 该消息在 `.log` 文件中的**字节偏移**

二分查找（`OffsetIndex.java:97-105`）：

```java
public OffsetPosition lookup(long targetOffset) {
    return inRemapReadLock(() -> {
        ByteBuffer idx = mmap().duplicate();
        int slot = largestLowerBoundSlotFor(idx, targetOffset, IndexSearchType.KEY);
        if (slot == -1) return new OffsetPosition(baseOffset(), 0);
        else return parseEntry(idx, slot);
    });
}
```

> [!TIP]
> 方法名是 **`OffsetIndex#lookup`**,不是 `LogSegment#lookup`。因为 index 文件预映射了全部槽位,可以像数组一样随机访问 → 真正的二分查找,不需要像 RocketMQ 那样加载全部索引再线性扫描。这是 Kafka 读性能的关键优势。

写入侧（`LogSegment.java:270`）：

```java
if (bytesSinceLastIndexEntry > indexIntervalBytes) {
    offsetIndex().append(batchLastOffset, physicalPosition);
    timeIndex().maybeAppend(maxTimestampSoFar(), shallowOffsetOfMaxTimestampSofar());
    bytesSinceLastIndexEntry = 0;
}
```

> [!WARNING]
> **`activeIndex` 字段在 4.x 已不存在**（grep 零命中），由 `bytesSinceLastIndexEntry` 计数器替代。

索引大小上限 `index.size.max.bytes` 默认 **10 MB**（`ServerLogConfigs.java:93`,映射见 `ServerTopicConfigSynonyms.java:58`）。因为是稀疏索引,10 MB 足以索引数亿条消息。

## Rolling Strategy: 5 Conditions

`storage/.../LogSegment.java:167-173`（完整实现）：

```java
public boolean shouldRoll(RollParams rollParams) throws IOException {
    boolean reachedRollMs = timeWaitedForRoll(rollParams.now(), rollParams.maxTimestampInMessages()) > rollParams.maxSegmentMs() - rollJitterMs;
    int size = size();
    return size > rollParams.maxSegmentBytes() - rollParams.messagesSize() ||
        (size > 0 && reachedRollMs) ||
        offsetIndex().isFull() || timeIndex().isFull() || !canConvertToRelativeOffset(rollParams.maxOffsetInMessages());
}
```

| # | 条件 | 触发原因 |
| - | ---- | -------- |
| 1 | `size > maxSegmentBytes - messagesSize` | 大小超限 |
| 2 | `size > 0 && reachedRollMs` | 时间超 `maxSegmentMs - rollJitterMs` |
| 3 | `offsetIndex().isFull()` | offset 索引写满（10 MB）|
| 4 | `timeIndex().isFull()` | 时间索引写满 |
| 5 | `!canConvertToRelativeOffset(maxOffsetInMessages)` | 相对 offset 溢出防护 |

> [!WARNING]
> **没有 `maxTimestampDiffMs` / `maxTimerRatio` 条件。** 这类「按消息时间戳差滚动」的机制在 4.3.1 中**全仓零命中** —— 4.x 没有引入基于 `log.message.timestamp.difference.*` 的滚动。
>
> 时间滚动实际基于**段首条消息的时间戳**（不是 broker 时钟），`LogSegment.java:709-712`：
> ```java
> public long timeWaitedForRoll(long now, long messageTimestamp) {
>     loadFirstBatchTimestamp();
>     long ts = rollingBasedTimestamp.orElse(-1L);
> ```
> 调用点 `UnifiedLog.java:2153`。

## Core Defaults Table

### Authoritative Sources

配置定义在两个地方,查的时候别搞错：

- **`server-common/src/main/java/org/apache/kafka/server/config/ServerLogConfigs.java`** —— 常量 + broker 级 ConfigDef
- **`storage/.../log/LogConfig.java:125-134`**（`DEFAULT_*` 常量）与 `:188-251`（topic 级 ConfigDef）

### Storage-related

| 配置名 | 默认值 | 出处 |
| ------ | ------ | ---- |
| `log.dir` | `/tmp/kafka-logs` | ServerLogConfigs.java:50 |
| `segment.bytes` | **1073741824（1 GiB）** | LogConfig.java:125 |
| `segment.ms` | **604800000（7 天）** | LogConfig.java:126 |
| `segment.jitter.ms` | 0 | LogConfig.java:127 |
| `segment.index.bytes` | **10485760（10 MB）** | ServerLogConfigs.java:93 |
| `index.interval.bytes` | **4096** | ServerLogConfigs.java:97 |
| `retention.ms` | **604800000（7 天）** | LogConfig.java:128 |
| `retention.bytes` | **-1**（不限） | ServerLogConfigs.java:81 |
| `delete.retention.ms` | 86400000（1 天） | LogConfig.java:129 |
| `min.cleanable.dirty.ratio` | 0.5 | LogConfig.java:132 |
| `unclean.leader.election.enable` | **false** | LogConfig.java:133 |
| `min.insync.replicas` | 1 | ServerLogConfigs.java:155 |
| `max.message.bytes` | 1048588 | — |
| `preallocate` | false | LogConfig.java:134 |
| `num.recovery.threads.per.data.dir` | 2 | ServerLogConfigs.java:147 |
| `log.dir.failure.timeout.ms` | 30000 | ServerLogConfigs.java:173 |
| `cordoned.log.dirs` | `List.of()` | ServerLogConfigs.java:55（4.3 新增 KIP-1066）|

### Flush-related

| 配置名 | 默认值 | 出处 |
| ------ | ------ | ---- |
| `flush.messages` | **Long.MAX_VALUE** | ServerLogConfigs.java:101 |
| `flush.ms` | **Long.MAX_VALUE** | ServerLogConfigs.java:109 |
| `log.flush.interval.messages` | Long.MAX_VALUE | ServerLogConfigs.java:167 |
| `log.flush.scheduler.interval.ms` | Long.MAX_VALUE | :169 |
| `log.flush.interval.ms` | null（回落 scheduler）| :170 |
| `log.flush.offset.checkpoint.interval.ms` | 60000 | :171 |
| `log.flush.start.offset.checkpoint.interval.ms` | 60000 | :172 |
| `log.segment.delete.delay.ms` | 60000 | ServerLogConfigs.java:168 |

> [!IMPORTANT]
> **`flush.ms` 默认是 `Long.MAX_VALUE`** —— 即**默认不主动刷盘**。这意味着 Kafka 的默认持久性完全依赖 OS page cache：进程崩溃不丢（page cache 还在），但机器断电会丢。
>
> 需要更强的持久性时要显式设 `flush.ms` / `flush.messages`,代价是吞吐下降。这与 RocketMQ 的 `ASYNC_FLUSH`（每 500ms 攒 4 页刷）形成鲜明对比 —— **Kafka 默认连异步刷盘周期都没有**。

### Timestamp

| 配置名 | 默认值 | 出处 |
| ------ | ------ | ---- |
| `message.timestamp.type` | **`CreateTime`** | ServerLogConfigs.java:127 |
| `message.timestamp.before.max.ms` | **Long.MAX_VALUE** | ServerLogConfigs.java:132 |
| `message.timestamp.after.max.ms` | **3600000（1 小时）** | ServerLogConfigs.java:139 |

> [!WARNING]
> **`log.message.timestamp.difference.max.ms` 在 4.x 中已不存在。** 它被拆成两项（`ServerLogConfigs.java:131-144`）：`before.max.ms`（Long.MAX_VALUE）+ `after.max.ms`（1 小时）。
>
> `CreateTime` 是默认类型意味着：**producer 客户端时间戳决定消息时间**,若客户端时钟漂移会导致消息落到「未来」,超出 `after.max.ms`（1 小时）会被拒绝或落到新段。

### Retention and Cleanup

| 配置名 | 默认值 | 出处 |
| ------ | ------ | ---- |
| `log.retention.ms` | null（次级）| ServerLogConfigs.java:158 |
| `log.retention.minutes` | null（三级）| :159 |
| `log.retention.hours` | **168**（兜底）| :160 |
| `log.retention.bytes` | -1 | :162 |
| **`log.retention.check.interval.ms`** | **300000（5 分钟）** | :163 |
| `log.cleanup.policy` | `delete` | :164 |
| `log.index.size.max.bytes` | 10485760（10 MB） | :165 |
| `log.segment.bytes` | 1 GiB，validator `atLeast(1024*1024)` | :150 |
| `log.roll.ms` | null（回落 roll.hours）| :152 |
| `log.roll.hours` | 168 | :153 |
| `log.roll.jitter.hours` | 0 | :156 |

`log.cleaner.*`（`storage/.../CleanerConfig.java`）：

| 配置名 | 默认值 | 行号 |
| ------ | ------ | ---- |
| **`log.cleaner.enable`** | **`true`** | :44 |
| `log.cleaner.threads` | 1 | :38 |
| `log.cleaner.dedupe.buffer.size` | 134217728（128 MB）| :40 |
| `log.cleaner.io.buffer.size` | 524288（512 KB）| :41 |
| `log.cleaner.io.buffer.load.factor` | 0.9 | :42 |
| `log.cleaner.io.max.bytes.per.second` | Double.MAX_VALUE | :39 |
| `log.cleaner.backoff.ms` | 15000 | :43 |
| `log.cleaner.min.compaction.lag.ms` | 0 | :56 |
| `log.cleaner.max.compaction.lag.ms` | Long.MAX_VALUE | :57 |
| `log.cleaner.min.cleanable.ratio` | 0.5 | :52 |

> [!IMPORTANT]
> **`log.cleaner.enable` 默认是 `true`,不是 false**（`CleanerConfig.java:44`）—— 而且该配置**已弃用**（`:73` 原文：*"This configuration has been deprecated and will be removed in Kafka 5.0. Users should not set it to false to prepare for its future removal."*）
>
> 所以「关掉 cleaner 省资源」这个建议在 4.x 是错的。

## Configuration Priority: Which Is Authoritative

这是最多人搞错的一点。`server-common/.../ServerTopicConfigSynonyms.java:49-86`,注释原文（`:44-47`）：

> "The broker configurations will be used in the order specified here. In other words, if both the first and the second synonyms are configured, we will use only the value of the first synonym and ignore the second."

```java
listWithLogPrefix(TopicConfig.RETENTION_MS_CONFIG,
    new ConfigSynonym("retention.ms"),
    new ConfigSynonym("retention.minutes", ConfigSynonym.MINUTES_TO_MILLISECONDS),
    new ConfigSynonym("retention.hours", ConfigSynonym.HOURS_TO_MILLISECONDS)),
```

**优先级顺序**：

| 目标配置 | 优先级（从高到低） |
| -------- | ------------------ |
| 保留时长 | `log.retention.ms` > `log.retention.minutes` > `log.retention.hours` |
| 段滚动时间 | `log.roll.ms` > `log.roll.hours` |
| 刷盘间隔 | `log.flush.interval.ms` > `log.flush.scheduler.interval.ms` |

> [!WARNING]
> **`log.retention.hours` 是三级兜底,不是权威。** 很多资料说「保留时长由 `log.retention.hours` 控制」——错的。如果同时设了 `log.retention.ms`,`hours` 会被**完全忽略**。
>
> 陷阱：`log.retention.hours=168` 有默认值,意味着即使你只设 `log.retention.ms=3600000`,`hours` 的默认值也不会干扰（因为 `ms` 优先级更高）。但如果你**只设 minutes** 而 `ms` 未设,`ms` 是 null,此时会用 minutes —— 这才是三级的实际作用场景。

## Isolation Level: `log.isolation.level` Does Not Exist

> [!WARNING]
> **`log.isolation.level` 在 4.3.1 中零命中**（`LogConfig.java` 无此配置）。这是个常见误解。
>
> 隔离级别是**消费者端**配置（`clients/.../ConsumerConfig.java:348`），默认 `read_uncommitted`（`:357` `DEFAULT_ISOLATION_LEVEL = IsolationLevel.READ_UNCOMMITTED.toString()`）。
>
> Broker 侧只读取隔离级别的**API 参数**（`FetchRequest` 的 `isolationLevel` 字段），不通过 `log.*` 配置。
>
> Share Group 有独立的 `share.isolation.level`（`group-coordinator/.../GroupConfig.java:80`）。

## Zero-copy: Kafka Uses sendfile, Not mmap to Read Data

这是 Kafka 与 RocketMQ 最本质的架构分野，值得单写。

> [!IMPORTANT]
> **Kafka 的数据文件走 `FileChannel.transferTo`（内核 sendfile 零拷贝）；mmap 只用于索引文件。**

调用链：

```
FileRecords.java:302          return (int) destChannel.transferFrom(channel, position, count);
UnalignedFileRecords.java:49  return (int) destChannel.transferFrom(channel, position, count);
  └─> TransferableChannel#transferFrom  (clients/.../network/TransferableChannel.java:50)
        └─> PlaintextTransportLayer.java:213-214
              return fileChannel.transferTo(position, count, socketChannel);
        └─> SslTransportLayer.java:1003   (TLS 路径，无法零拷贝)
```

> [!TIP]
> 方法名是 **`transferFrom`**（Kafka 在 `TransferableChannel` 接口上定义 `transferFrom(FileChannel, position, count)`），内部**委托给** `FileChannel.transferTo`。两个方法都存在,容易搞混。
>
> **为什么要包一层**（`TransferableChannel.java:39-42` 官方注释）：
> > "This method will delegate to `FileChannel#transferTo(...)`, but it will **unwrap the destination channel, if possible, in order to benefit from zero copy**. This is required because the fast path of `transferTo` is only executed if the destination buffer inherits from an **internal JDK class**."
>
> 即 Kafka 拿到的是 Netty 的包装 channel，需要「解包」成真正的 JDK 内部类才能走 sendfile 快路径。

| 文件类型 | 访问方式 | 位置 |
| -------- | -------- | ---- |
| `.log`（数据） | **`transferTo` 零拷贝** | `PlaintextTransportLayer.java:214` |
| `.index` / `.timeindex` | **mmap** | `OffsetIndex.java:99` `ByteBuffer idx = mmap().duplicate()` |
| `.log`（写入） | `FileChannel.write`（进 page cache，不立即落盘）| |

> [!WARNING]
> - **`DirectByteBuffer` 在 Kafka 主代码中未找到使用**（`storage/src/main/` + `clients/src/main/` 零命中）。
> - **`LogWriteAheadManager` 类在 4.3.1 中不存在**（`find` → 0 结果）。4.x 没有独立的异步刷盘管理器。
> - `FileChannelImpl.transferToArbitraryChannels` 的 sendfile 退化条件属 **JDK 内部实现**，本环境无 OpenJDK 源码，**未查到**。能确认的只是 Kafka 侧前提：目标 channel 必须是 JDK 内部类的继承者。

> [!NOTE]
> 与 [RocketMQ Store](/docs/CS/MQ/RocketMQ/Store.md) 的对比值得记住：Kafka 用 sendfile 是因为「读出去就够了，不需要在应用层看消息内容」；RocketMQ 用 mmap 是因为需要拿到消息内容做 SQL92 过滤与死信投递。**这个取舍决定了两者功能边界的差异** —— 详见 [ZeroCopy](/docs/CS/OS/Linux/ZeroCopy.md)。

## ProducerStateManager and Leader Epoch

`storage/.../ProducerStateManager.java` 存在，配置类 `ProducerStateManagerConfig.java`；且 `DYNAMIC_PRODUCER_STATE_MANAGER_CONFIGS` 在动态配置白名单内（`DynamicBrokerConfig.java:78`）。

快照机制（`LogLoader.java`）：
- `:234-237` 启动时重载所有 snapshot 到缓存 + `removeStraySnapshots`
- `:416-418` recover 后 `takeSnapshot()`
- `:546` `deleteProducerSnapshotsAsync`

ELR（Eligible Leader Replicas，KIP-966）：`storage/.../LeaderHwChange.java` 存在。

### Truncation: Method Name Is Not truncateToAndHandleDuplicates

> [!WARNING]
> **`UnifiedLog#truncateToAndHandleDuplicates` 在 4.3.1 中不存在**（grep 零命中）。真实方法名是 **`truncateTo`**（`UnifiedLog.java:2340-2376`）。

unclean leader election 的截断分支（`UnifiedLog.java:2340-2376`）：

```java
if (targetOffset >= localLog.logEndOffset()) {
    leaderEpochCache.truncateFromEndAsyncFlush(logEndOffset());
    return false;
} else {
    synchronized (lock) {
        if (localLog.segments().firstSegmentBaseOffset().getAsLong() > targetOffset) {
            truncateFullyAndStartAt(targetOffset, Optional.empty());
        } else {
            Collection<LogSegment> deletedSegments = localLog.truncateTo(targetOffset);
            deleteProducerSnapshots(deletedSegments, true);
            leaderEpochCache.truncateFromEndAsyncFlush(targetOffset);
            logStartOffset = Math.min(targetOffset, logStartOffset);
            rebuildProducerState(targetOffset, producerStateManager);
            if (highWatermark() >= localLog.logEndOffset())
                updateHighWatermark(localLog.logEndOffsetMetadata());
        }
        return true;
    }
}
```

> [!TIP]
> `unclean.leader.election.enable` 默认 **false**（`LogConfig.java:133`）。关闭时 follower 落后太多会主动放弃追日志（向 leader 返回 `OffsetOutOfRange`）而非截断数据 —— 这是「宁可不可用也不丢数据」的选择。
>
> 开启后（不建议生产）会截断到 `highWatermark` 之后,这会**丢数据**。

## Tiered Storage

> [!WARNING]
> 配置名是 **`remote.storage.enable`**（**没有 `log.` 前缀**），默认 **false**（`LogConfig.java:136` `DEFAULT_REMOTE_STORAGE_ENABLE = false`，ConfigDef `:243`）。
>
> 写成 `log.remote.storage.enable` 会因未知配置导致启动失败。

| 配置名 | 默认值 | 出处 |
| ------ | ------ | ---- |
| `remote.storage.enable` | **false** | LogConfig.java:136 |
| `local.retention.ms` | **-2**（表示从 `retention.*` 推导）| LogConfig.java:139 |
| `local.retention.bytes` | -2 | LogConfig.java:140 |

`remote.log.*` 前缀配置在 `storage/src/main/java/org/apache/kafka/server/log/remote/storage/RemoteLogManagerConfig.java:50,69,73,79`。

> [!IMPORTANT]
> **KIP-1050 不是 log format / cloud storage** —— 它是 4.1.0 的「Consistent error handling for Transactions」（`docs/getting-started/upgrade.md:320`）。**4.x 未引入新 log format**；tiered storage 的 KIP 是 KIP-1023、KIP-1208、KIP-1235 等。
>
> 这个误解来源很可能是把「KIP-1050」与 Kafka tiered storage 的 roadmap 混为一谈。

## Common Claims That Need Debunking

| 说法 | 4.3.1 实况 |
| ---- | --------- |
| 「`log.retention.hours` 是保留时长的权威配置」 | ❌ 它是**三级兜底**，权威顺序 `retention.ms` > `retention.minutes` > `retention.hours`（`ServerTopicConfigSynonyms.java:64-67`，注释明示）|
| 「`log.message.timestamp.difference.max.ms` 默认 Long.MAX_VALUE」 | ⚠️ **配置已不存在**，4.x 拆成 `before.max.ms`=Long.MAX_VALUE + `after.max.ms`=1 小时 |
| 「`log.cleaner.enable` 默认 false，建议关掉省资源」 | ❌ 默认 **true** 且已弃用，官方明确要求不要设 false |
| 「`log.isolation.level` 默认 read_uncommitted」 | ⚠️ 配置名错，**它不存在**；是消费者端 `isolation.level` |
| 「有 `log.remote.storage.enable`」 | ❌ 真实名 `remote.storage.enable`（无 `log.` 前缀）|
| 「`LogWriteAheadManager` 做异步刷盘」 | ❌ 类不存在 |
| 「有 `activeIndex` 字段」 | ❌ 4.x 改为 `bytesSinceLastIndexEntry` 计数器 |
| 「段文件含 `leader-epoch-checkpoint` 和 `partition.metadata`」 | ❌ epoch checkpoint 在 **partition 目录级**（`__leader_epoch`）；`partition.metadata` 已移除；4.x 新增 `.txnindex` |
| 「滚动条件含 `maxTimestampDiffMs`/`maxTimerRatio`」 | ❌ `shouldRoll` 只有 5 个条件，无时间戳差滚动 |
| 「Kafka 用 mmap 读日志数据零拷贝」 | ❌ 数据文件走 `transferTo`；mmap 只用于 `.index`/`.timeindex` |
| 「`UnifiedLog#truncateToAndHandleDuplicates`」 | ❌ 真实方法名 `truncateTo` |
| 「默认 flush.ms 是 5 秒或 1 秒」 | ❌ **`Long.MAX_VALUE`**，即默认完全不主动刷盘 |
| 「KIP-1050 是 log format/cloud storage」 | ❌ 是事务错误处理；4.x 无新 log format |

## List Not Found

- `FileChannelImpl.transferToArbitraryChannels` 的 sendfile 退化条件（属 JDK 源码，本环境不可达）
- `java.nio.Buffer` 的 `force`/`put` 与 page cache 交互的 JDK 层实现（同上）
- 4.x 是否引入新 log format —— 已确认**没有**

## Links

- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)
- [Broker](/docs/CS/MQ/Kafka/Broker.md)
- [Replica](/docs/CS/MQ/Kafka/Replica.md)
- [ShareGroup](/docs/CS/MQ/Kafka/ShareGroup.md)
- [ZeroCopy](/docs/CS/OS/Linux/ZeroCopy.md)
- [RocketMQ Store（mmap 路线对照）](/docs/CS/MQ/RocketMQ/Store.md)

## References

1. [Apache Kafka 4.3.1 Download](https://kafka.apache.org/downloads)
2. [LogSegment.java (4.3.1)](https://github.com/apache/kafka/blob/4.3.1/storage/src/main/java/org/apache/kafka/storage/internals/log/LogSegment.java)
3. [ServerLogConfigs.java (4.3.1)](https://github.com/apache/kafka/blob/4.3.1/server-common/src/main/java/org/apache/kafka/server/config/ServerLogConfigs.java)
4. [ServerTopicConfigSynonyms.java (4.3.1)](https://github.com/apache/kafka/blob/4.3.1/server-common/src/main/java/org/apache/kafka/server/config/ServerTopicConfigSynonyms.java)
