## Introduction

Pulsar 的存储是三层解耦的架构：**Broker 只管调度，数据落到 BookKeeper 的 ledger，元数据（ledger 列表、cursor 位点、bundle 归属）落到 metadata store**。这种「计算无状态、存储无状态」的分层是 Pulsar 与 Kafka 最本质的架构差异。

> 版本基线：**4.2.4**（tag `v4.2.4`，当前稳定版，2026-08-03 发布）。
> ⚠️ 另有里程碑版 `v5.0.0-M1/M2`（2026-06/09），**里程碑版不是生产可用基线**，本文所有结论出自 4.2.4。
> BookKeeper 版本：**4.17.3**（根 `pom.xml:185`）。

```tex
Broker（无状态计算）
  │  ① 写：asyncAppend(ByteBuf) → 封装成 entry
  ▼
BookKeeper（4.17.3，独立进程/集群）
  ledger ── segment（副本集合变更历史）── entry（真正的数据）
  │  ② 确认：E/Qw/Qa 三级 quorum
  ▼
metadata store（pulsar-metadata）
  ledgers: {ledgerId → LedgerInfo(size/entries/timestamp)}
  cursors: {cursorName → markDeletePosition}
  /namespace/{tenant}/{ns}/{hash}  ← bundle 归属（ephemeral 节点）
```

## 4.2.4 的大规模重构（照旧资料写必错）

这是本篇最重要的部分。Pulsar 4.x 相对 2.x/3.x 有**大量类删除与包路径迁移**，网上流传的中文资料几乎全部停留在 2.x。

### 类名对照表

| 旧资料中的类 | 4.2.4 实际情况 |
| ------------ | --------------- |
| `PersistentLedgerImpl` | ❌ **不存在**。持久化统一由 `ManagedLedgerImpl`（5269 行）承担 |
| `NonPersistentLedgerImpl` | ❌ 不存在。`NonPersistent*` 现在只指 **topic 类型**，与 ledger 实现无关 |
| `ReadOnlyLedgerImpl` | ❌ 名为 **`ReadOnlyManagedLedgerImpl`** |
| `EntryCacheImpl` / `LedgerEntryCache` | ❌ 已重构为 **`RangeEntryCacheImpl` / `RangeCache`** |
| `MLAsyncWriteCallback` / `MLAddEntryCallback` | ❌ 实际是 **`AddEntryCallback`**（`OpAddEntry.java:84`） |
| `GroupWriteOp` / `WriteOp` / `WriteDataOp` | ❌ **全部不存在** —— group commit 已从 managed-ledger 移除 |
| `EntryBatchOp` / `EntryBatchIndexEntry` / `dataBuffers` | ❌ 不存在。batch 已在 **broker 侧**完成 |
| `LedgerMetadata` | 真实是 protobuf **`MLDataFormats.proto`** |
| `RocksDBMetadataStore` | ⚠️ 类名是 **`RocksdbMetadataStore`**（小写 db），且在 `pulsar-metadata/` 模块 |
| `metadata-store/` 顶层模块 | ❌ 不存在，实为 **`pulsar-metadata/`** |
| `PulsarClientImpl#createBkConf` | ❌ 类的职责已拆为 `PulsarClientResourcesConfigurer` |
| `BookKeeperClientConfiguration` | ❌ 真实是 **`org.apache.bookkeeper.conf.ClientConfiguration`** |
| `PulsarService`（`org.apache.pulsar`） | ⚠️ 包名改为 **`org.apache.pulsar.broker.PulsarService`** |
| `NamespaceBundleData` | ⚠️ 更名为 **`BundlesData`** |
| `LedgerHandleImpl`（BookKeeper 侧） | ❌ 4.17.3 已合并为单一 `LedgerHandle.java`（2384 行） |
| `compaction` 包位置 | ⚠️ 从 `org.apache.pulsar.broker.compaction` 改为 **`org.apache.pulsar.compaction`** |

> [!WARNING]
> `EntryBatchOp` / `GroupWriteOp` 被删除意味着 **managed-ledger 不再做 group commit**。这是 4.x 与 2.x 最大的实现差异之一：批量合并的职责上移到了 broker，写入延迟特性与 2.x 不同。

### 字段名对照表

`LedgerInfo` 现在是 protobuf（`MLDataFormats.proto:55-62`）：

```protobuf
message LedgerInfo {
    required int64 ledgerId = 1;
    optional int64 entries = 2;
    optional int64 size = 3;
    optional int64 timestamp = 4;
    optional OffloadContext offloadContext = 5;
    repeated KeyValue properties = 6;
}
```

> [!WARNING]
> 旧资料常提的 `off`、`ledgerClosedTimestamp`、`marker`、`length` 四个字段**全部不存在**。
>
> 另有一个**同名但不同用途**的类 `org.apache.bookkeeper.mledger.ManagedLedgerInfo.LedgerInfo`（字段 `ledgerId/entries/size/timestamp/isOffloaded/offloadedContextUuid`），用于 JSON/admin 输出，**不是** `ledgers` map 的 value 类型 —— 极易混淆。

`ManagedCursorImpl`（4242 行）字段：

| 字段 | 行号 | 说明 |
| ---- | ---- | ---- |
| `markDeletePosition` | 141 | **已确认（ack）位点** |
| `readPosition` | 153 | **已投递位点**，读时即推进 |
| `messagesConsumedCounter` | 183 | 初始为 `-backlog`，避免遍历算积压 |
| `cursorLedger` | 187 | 游标自身也写 BK ledger 存 position |
| `individualDeletedMessages` | 205 | 范围删除（**不是 `individualDeletedRanges`**）|
| `readCompacted` | — | ❌ 不是字段，是 `rewind(boolean readCompacted)` 的参数（`:2850`）|

```java
// ManagedCursorImpl.java:180-182（源码注释）
// 初始化为 -backlog，每次读或删递增，用于免遍历 ledger 列表计算 backlog
messagesConsumedCounter = -getNumberOfEntries(Range.openClosed(position, ledger.getLastPosition()));
```

## 写入路径

### 完整链路

```
producer.sendAsync
  → ManagedLedgerImpl.asyncAppend(buffer, numberOfMessages, callback, ctx)   // 845
      buffer.retain()                                                        // 846
      executor.execute(...)   ← 切到单线程，避免多写线程竞争                   // 849
        OpAddEntry.createNoRetainBuffer(this, buffer, numberOfMessages, ...)
        internalAsyncAddEntry(addOperation)                                  // 852→856
```

`internalAsyncAddEntry`（`ManagedLedgerImpl.java:856-925`）按 `state` 分支，5 个写入失败态直接抛异常：

```
Fenced           → ManagedLedgerFencedException              // 861
Terminated       → ManagedLedgerTerminatedException          // 864
Closed           → ManagedLedgerAlreadyClosedException       // 867
WriteFailed      → AlreadyClosed("Waiting to recover")       // 870
pendingAddEntries.add(op)                                     // 874
switch (state):
  ClosingLedger | CreatingLedger → 排队等待，不发起             // 876-889
  ClosedLedger  → CAS → CreatingLedger → asyncCreateLedger    // 892-896
  LedgerOpened  → 写 currentLedger                            // 898
      ++currentLedgerEntries; currentLedgerSize += readableBytes // 905-906
      if (currentLedgerIsFull()) {                            // 913 ★封口判定
          addOperation.setCloseWhenDone(true)                 // 918
          STATE_UPDATER.set(this, State.ClosingLedger)        // 919
      }
      addOperation.initiate()                                 // 921
```

最终写入是 `OpAddEntry.java:172` 一行：

```java
ledger.asyncAddEntry(duplicateBuffer, this, addOpCount);
```

> [!NOTE]
> 方法名是 **`asyncAddEntry`**，不是 `asyncWriteEntry`（旧资料常写后者）。

### quorum 由 BookKeeper 负责，managed-ledger 不参与

`ManagedLedgerImpl.java:4684-4685` —— 创建 ledger 时一次性把 E/Qw/Qa 交给 BookKeeper：

```java
bookKeeper.asyncCreateLedger(config.getEnsembleSize(), config.getWriteQuorumSize(),
        config.getAckQuorumSize(), digestType, config.getPassword(), cb, ledgerFutureHook, finalMetadata);
```

之后每次写只调 `asyncAddEntry`，**确认逻辑全在 BK 侧**。这也是一个常见误解点：E/Qw/Qa 不是在客户端配置里生效的。

> [!TIP]
> 推论：这三项**不在** BookKeeper client 配置里设置，而是每次创建 ledger 时随 metadata 传递。所以改 quorum 只影响**新建**的 ledger，已有 ledger 的 E/Qw/Qa 不可变。

## Rollover（切账本）

### 封口判定

`currentLedgerIsFull()`（`ManagedLedgerImpl.java:4431-4458`）是唯一判定：

```java
boolean spaceQuotaReached = (currentLedgerEntries >= config.getMaxEntriesPerLedger()
        || currentLedgerSize >= (config.getMaxSizePerLedgerMb() * MegaByte));        // 4437-4438
long timeSinceLedgerCreationMs = clock.millis() - lastLedgerCreatedTimestamp;
boolean maxLedgerTimeReached = timeSinceLedgerCreationMs >= config.getMaximumRolloverTimeMs();  // 4441
if (spaceQuotaReached || maxLedgerTimeReached) {
    if (config.getMinimumRolloverTimeMs() > 0) {
        return timeSinceLedgerCreationMs > config.getMinimumRolloverTimeMs();        // 4446 需同时满足 min
    } else { return true; }
} else { return false; }
```

三个要点：

1. **元数据服务不可用时直接返回 false**（`:4432-4435`），不触发元数据操作。
2. **`maxLedgerTimeReached` 绕过 min 检查**（4441 在 if 之外）—— 超最长时限会**强制切**，不受最小间隔约束。这是有意设计：避免 topic 卡住不切。
3. **最长时限带随机抖动**（`:4546-4547`）：

```java
private static long getMaximumRolloverTimeMs(ManagedLedgerConfig config) {
    return (long) (config.getMaximumRolloverTimeMs() * (1 + random.nextDouble() * 5 / 100.0));
}
```

即实际最长 rollover = 配置值 × [1, 1.05)，用于**打散各 topic 的切账本时刻**，避免大量 topic 同时切造成的写入尖峰。

> [!WARNING]
> 旧资料常见的「写阻塞时按 `closingBacklogThreshold` 加速切账本」机制在 4.2.4 **不存在**（全库零命中）。`currentLedgerIsFull()` 的三个维度（entries / size / maxTime）**与写入阻塞、背压、closing backlog 完全无耦合**。

另有一个独立触发点 `checkInactiveLedgerAndRollOver()`（`:5145-5174`）：`inactiveLedgerRollOverTimeMs > 0` 且距最后写入超时 → CAS 到 `ClosingLedger` 并 `asyncClose`，**但不立即新建 ledger**（`:5168` 注释说明：topic 长期不活跃场景）。

## 默认值对照表

### 账本相关（`ManagedLedgerConfig` 原生值 vs broker 侧覆盖后）

`ManagedLedgerConfig`（`managed-ledger/src/main/java/org/apache/bookkeeper/mledger/ManagedLedgerConfig.java`）：

| 字段 | 原生默认 | 行号 | broker 侧覆盖后 | 覆盖项行号 |
| ---- | -------- | ---- | --------------- | ---------- |
| `ensembleSize` | **3** | 57 | **2** | `ServiceConfiguration:2234` |
| `writeQuorumSize` | **2** | 58 | **2** | `:2240` |
| `ackQuorumSize` | **2** | 59 | **2** | `:2247` |
| `maxEntriesPerLedger` | 50000 | 53 | 50000 | `:2444` |
| `maxSizePerLedgerMb` | 100 | 54 | **2048** | `:2459` |
| `minimumRolloverTimeMs` | 0 | 55 | **10 分钟** | `:2449` |
| `maximumRolloverTimeMs` | 4 小时 | 56 | **240 分钟** | `:2454` |
| `digestType` | `CRC32C` | 76 | `CRC32C` | `:2267` |
| `metadataOperationsTimeoutSeconds` | 60 | 73 | 60 | `:2592` |
| `readEntryTimeoutSeconds` | 120 | 74 | **0**（不超时）| `:2599` |
| `addEntryTimeoutSeconds` | 120 | 75 | **0** | `:2603` |
| `throttleMarkDelete` | 0 | 65 | 1.0 | `:2389` |
| `maxUnackedRangesToPersist` | 10000 | 48 | 10000 | `:2518` |
| `deletionAtBatchIndexLevelEnabled` | true | 51 | true | `:433` |
| `inactiveLedgerRollOverTimeMs` | 0 | 86 | 0 | `:3716` |
| `lazyCursorRecovery` | false | 72 | — | — |

> [!IMPORTANT]
> **默认部署实际是 2/2/2，不是 3/2/2。** `ManagedLedgerConfig` 的库级默认是 3/2/2，但 `ServiceConfiguration` 把它覆盖成 2/2/2。
>
> 2/2/2 意味着 **ensemble 只有 2 个副本，容忍 0 个 bookie 故障**（W-Q = 2-2 = 0）。生产环境通常需要显式调回 3/2/2。
>
> 上限：`managedLedgerMaxEnsembleSize=5`、MaxWriteQuorum=5、MaxAckQuorum=5（`:2281/2287/2293`）。
>
> 顺带一提：`ManagedLedgerConfig:2230-2232` 的注释指出 **sticky reads 仅在 E == Qw 时生效**，默认 2/2/2 恰好满足。

### 缓存相关（`ManagedLedgerFactoryConfig`）

> [!WARNING]
> 缓存类配置**不在 `ManagedLedgerConfig`** 而在 `ManagedLedgerFactoryConfig`。旧资料把 `cacheEvictionInterval` 写进 MLConfig 是错的。

| 字段 | 原生默认 | 行号 | broker 侧覆盖后 | 覆盖项行号 |
| ---- | -------- | ---- | --------------- | ---------- |
| `maxCacheSize` | **128 MB** | 35 | **`max(64, JVM直接内存/5)` MB** | `:2300-2301` |
| `cacheEvictionWatermark` | 0.90 | 40 | 0.9 | `:2326` |
| `cacheEvictionIntervalMs` | 10 | 47 | 10 | `:2334` |
| `cacheEvictionTimeThresholdMillis` | 1000 | 58 | 1000 | `:2346` |
| `numManagedLedgerSchedulerThreads` | CPU 核数 | 42 | CPU 核数 | `:2434` |
| `managedLedgerMaxReadsInFlightSize` | 0（关闭） | 95 | 0 | `:2310` |
| `cursorPositionFlushSeconds` | 60 | 122 | 60 | `:2253` |
| `copyEntriesInCache` | false | 90 | false | `:2305` |

> [!TIP]
> broker 侧把 `maxCacheSize` 默认改成 **JVM 直接内存的 1/5**（而非固定 128MB），是为了适配容器化环境 —— 这是与官方文档 128MB 的实质差异。

### `managedLedgerCacheEvictionFrequency = 0` 的真实含义

> [!WARNING]
> **不表示「关闭」** —— 这是个易误判处。`ServiceConfiguration.java:4240-4246`：
> ```java
> public long getManagedLedgerCacheEvictionIntervalMs() {
>     return managedLedgerCacheEvictionFrequency > 0
>         ? (long) (1000 / Math.max(
>                 Math.min(managedLedgerCacheEvictionFrequency, MAX_ML_CACHE_EVICTION_FREQUENCY),
>                            MIN_ML_CACHE_EVICTION_FREQUENCY))
>         : Math.min(MAX_ML_CACHE_EVICTION_INTERVAL_MS, managedLedgerCacheEvictionIntervalMs);
> }
> ```
> 常量：`MIN_ML_CACHE_EVICTION_FREQUENCY=0.001`（`:113`）、`MAX_ML_CACHE_EVICTION_FREQUENCY=1000.0`（`:114`）、`MAX_ML_CACHE_EVICTION_INTERVAL_MS=1000000L`（`:115`）。
>
> 默认 `frequency = 0`（`:2330`）→ 走 else 分支 → `min(1000000, 10)` = **10 ms**。即「不按频率换算，直接用毫秒值」。
>
> 而且淘汰**不是**定时全量清理，而是**水位触发**（`RangeEntryCacheManagerImpl.java:136-155` `triggerEvictionWhenNeeded`）：
> ```java
> sizeToEvict = currentSize - (long)(maxSize * cacheEvictionWatermark);   // :174
> evictionHandler.evictEntries(sizeToEvict);
> ```
> 水位 0.9，即缓存用到 90% 时按 LRU 淘汰到该水位。

## 读路径

### 缓存数据结构是跳表不是链表

`RangeEntryCacheImpl`（`impl/cache/RangeEntryCacheImpl.java:59`）内部：

```java
this.entries = new RangeCache(rangeCacheRemovalQueue);
```

```java
// impl/cache/RangeCache.java:47, 66
private final ConcurrentNavigableMap<Position, RangeCacheEntryWrapper> entries;
this.entries = new ConcurrentSkipListMap();
```

类注释（`:35-44`）说明 `RangeCacheEntryWrapper` 的作用：确保**同一 entry 只被移除一次**，避免引用计数重复释放。数据按 `Position`（ledgerId + entryId）排序，跳表便于按位点范围查找。

> [!WARNING]
> 旧资料说缓存是 `LinkedList` —— 4.2.4 是 **`ConcurrentSkipListMap`**。

### 消息解析不再用 magic number

`Commands.parseMessageMetadata`（`pulsar-common/.../protocol/Commands.java:469-485`）：

```java
public static void parseMessageMetadata(ByteBuf buffer, MessageMetadata msgMetadata) {
    skipBrokerEntryMetadataIfExist(buffer);               // 478
    skipChecksumIfPresent(buffer);                        // 481
    int metadataSize = (int) buffer.readUnsignedInt();    // 482
    msgMetadata.parseFrom(buffer, metadataSize);          // 484
}
```

> [!WARNING]
> `Commands` 中 `MAGIC_NUMBER` / `hasMagicNumber` **未查到**。4.x 改为**三层前缀 + 长度**的跳过机制：broker entry metadata 前缀 → checksum → 4 字节 metadataSize，不再用 magic number 判定格式。

`MessageImpl<T>` 实际路径：`pulsar-client/src/main/java/org/apache/pulsar/client/impl/MessageImpl.java:64`（**不在 compression/impl 下**）。

### MessageId 是 protobuf

`PulsarApi.proto:59-69`：

```protobuf
message MessageIdData {
    required uint64 ledgerId = 1;
    required uint64 entryId  = 2;
    optional int32 partition = 3 [default = -1];
    optional int32 batch_index = 4 [default = -1];
    repeated int64 ack_set = 5;
    optional int32 batch_size = 6;
    optional MessageIdData first_chunk_message_id = 7;   // 分块消息
}
```

Java 侧：

| 类 | 行号 | 字段 |
| -- | ---- | ---- |
| `MessageIdImpl` | `:32-55` | `ledgerId`(35) / `entryId`(36) / `partitionIndex`(37) |
| `BatchMessageIdImpl extends MessageIdImpl` | `:24-53` | 增 `batchIndex`(27) / `batchSize`(28) / `BitSet ackSet`(30) |

即**四元组 (ledgerId, entryId, partitionIndex, batchIndex) + batchSize + ackSet**，比 2.x 多了 chunk 与 batchSize。

## BookKeeper 侧

### 术语：segment 不是 fragment

> [!WARNING]
> BookKeeper 4.17.3 源码中**没有 "fragment" 这个术语**，实际是 **`segment`**。

`bookkeeper-proto/src/main/proto/DataFormats.proto:26-65`：

```protobuf
message LedgerMetadataFormat {
    required int32 quorumSize = 1;      // ← 即 writeQuorum（字段名不对称！）
    required int32 ensembleSize = 2;
    required int64 length = 3;
    optional int64 lastEntryId = 4;
    enum State { OPEN = 1; IN_RECOVERY = 2; CLOSED = 3; }
    required State state = 5 [default = OPEN];
    message Segment {
        repeated string ensembleMember = 1;
        required int64 firstEntryId = 2;
    }
    repeated Segment segment = 6;       // ← 副本集合变更的历史记录
    optional int32 ackQuorumSize = 9;   // ← 独立字段
}
```

真实关系是：**ledger（由 metadata 描述）→ segment（副本集合变更记录，`ensembleMember` 是 bookie 列表）→ entry（按 entryId 索引的实际数据）**。

> [!TIP]
> 两个易踩的坑：
> - proto 字段叫 `quorumSize`，但 Java 接口方法是 **`getWriteQuorumSize()`**（`client/api/LedgerMetadata.java:56`）—— 字段名与方法名不对称。
> - `ackQuorumSize` 是**独立字段**（:9），不在 `quorumSize` 里。
> - 「一个 ledger 固定写 E 个 bookie」**不严谨** —— `segment` 记录了 ensemble 变更历史，ensemble 可通过 ensemble change 调整。

### quorum 确认逻辑

`PendingAddOp.java`：

```java
// 276-278：每个 bookie 响应都记 ack
boolean ackQuorum = false;
if (BKException.Code.OK == rc) {
    ackQuorum = ackSet.completeBookieAndCheck(bookieIndex);
    addEntrySuccessBookies.add(ensemble.get(bookieIndex));
}
...
// 358-384：达到 ack quorum 才回调成功
if (ackQuorum && !completed) {
    if (clientCtx.getConf().enforceMinNumFaultDomainsForWrite
            && !clientCtx.getPlacementPolicy().areAckedBookiesAdheringToPlacementPolicy(...)) {
        // 延迟：acked bookie 未跨足够 fault domain        // 359-372
    } else {
        completed = true;                                              // 374
        this.qwcLatency = MathUtils.elapsedNanos(requestTimeNanos);     // 375
        sendAddSuccessCallbacks();        // ← ENTRY_ADDED 在此发出      // 384
    }
}
```

AckSet 判定式（`RoundRobinDistributionSchedule.java:311`）：

```java
return ackSet.cardinality() >= ackQuorumSize;
```

ack quorum 被打破的判定（`:319`）：

```java
return failed() > (writeQuorumSize - ackQuorumSize);
```

即 **E 个副本中最多容忍 W-Q 个失败**。以默认 2/2/2 为例：W-Q = 0，即**一个 bookie 挂掉写入就阻塞**。

> [!TIP]
> `AckSetImpl.create(ensembleSize, writeQuorumSize, ackQuorumSize)` 来自 `RoundRobinDistributionSchedule.java:260`。`DistributionSchedule.java:165-167` 的注释是官方定义：「An ack set represents the set of bookies from which a response must be received so that an entry can be considered to be replicated on a quorum.」

> [!NOTE]
> **`minBookies` 在 4.17.3 中未查到**（grep 返回空）。相近能力以 `enforceMinNumFaultDomainsForWrite` / `minNumRacksPerWriteQuorum` 形式存在。

### entry 落盘：先 LedgerStorage 再 Journal

`BookieImpl.java:957-993` `addEntryInternal`：

```java
long entryId = handle.addEntry(entry);          // 961  先写 LedgerStorage
bookieStats.getWriteBytes().addCount(entry.readableBytes());
// 965-966 注释：journal addEntry 应在 entry 加入 ledger storage 之后，
//           否则 journal entry 可能在 ledger 创建前被 roll
...
if (!writeDataToJournal) {                      // 981
    cb.writeComplete(0, ledgerId, entryId, null, ctx);   // 982  未开 journal 则直接成功
    return;
}
getJournal(ledgerId).logAddEntry(entry, ackBeforeSync, cb, ctx);   // 992  再写 Journal(WAL)
```

> [!IMPORTANT]
> **重要纠正**：BK 4.17.3 中 **`memLimit` / `bytesSinceLastSync` 均已不存在**（全库零命中）。旧版「写满 memLimit 才刷盘」的机制已被移除。
>
> `LedgerCacheImpl` 现在**只是索引页管理者**（`IndexInMemPageMgr` + `IndexPersistenceMgr`），**不持有 entry 数据缓存**。`LedgerDescriptorImpl`（`:156`）也只把读写委派给 `LedgerStorage`。
>
> 即：**entry 数据不在 bookie 内存长期缓存**，而是写入 **entry log（LedgerStorage）+ Journal（WAL）**。写入的内存聚合由 `EntryMemTable` / `EntryMemTableWithParallelFlusher` 承担。
>
> 这与「写满内存才刷盘」的旧描述完全不同 —— 内存压力不再驱动刷盘。

### LedgerHandle 已合并

`client/LedgerHandle.java:94`（2384 行）：

```java
public class LedgerHandle implements WriteHandle
```

`LedgerHandleImpl` / `PackagePrivateLedgerHandleImpl` **均不存在**。引用 `LedgerHandleImpl.asyncWriteEntry` 会指向不存在的类。

## 元数据存储：4.x 重要变化

> [!IMPORTANT]
> metadata store 实现注册在 `pulsar-metadata/.../MetadataStoreFactoryImpl.java:66-73`：
> ```java
> providers.put(MEMORY_SCHEME_IDENTIFIER,  new MemoryMetadataStoreProvider());
> providers.put(ROCKSDB_SCHEME_IDENTIFIER,  new RocksdbMetadataStoreProvider());
> providers.put(ETCD_SCHEME_IDENTIFIER,     new EtcdMetadataStoreProvider());
> providers.put(OXIA_SCHEME_IDENTIFIER,     new OxiaMetadataStoreProvider());
> providers.put(ZK_SCHEME_IDENTIFIER,       new ZkMetadataStoreProvider());
> ```
> 4.2.4 比 2.x 多了 **etcd** 与 **Oxia** 两个 provider。

| scheme | 类 | 位置 |
| ------ | -- | ---- |
| `memory:` | `LocalMemoryMetadataStore` | `LocalMemoryMetadataStore.java:56` |
| `rocksdb:` | **`RocksdbMetadataStore`** | `RocksdbMetadataStore.java:81` |
| `etcd:` | `EtcdMetadataStore` | `EtcdMetadataStore.java:95` |
| `oxia:` | `OxiaMetadataStoreProvider` | `oxia/OxiaMetadataStoreProvider.java:35` |
| `zk:` | `ZKMetadataStore` | `ZKMetadataStore.java:75` |

> [!WARNING]
> **默认回退是 ZK，不是 RocksDB**（`MetadataStoreFactoryImpl.java:97`）：URL 无任何已知 scheme 前缀时 `return providers.get(ZK_SCHEME_IDENTIFIER)`。`isBasedOnZookeeper`（`:117-123`）：不含 `://` 一律视为 ZK。
>
> 常见误解是「Pulsar 默认用 RocksDB 存元数据」—— 那只在显式配置 `rocksdb://` 时成立。

`getMetadataStoreUrl()`（`ServiceConfiguration.java:4134-4143`）三级回退：

```java
public String getMetadataStoreUrl() {
    if (StringUtils.isNotBlank(metadataStoreUrl)) { return metadataStoreUrl; }
    else if (StringUtils.isNotBlank(zookeeperServers)) {
        return ZKMetadataStore.ZK_SCHEME_IDENTIFIER + zookeeperServers;   // 回退到已废弃的 zookeeperServers
    } else { return ""; }
}
```

`metadataStoreUrl` 字段（`:139`）**无默认值（null）**。

### bookkeeperMetadataServiceUri 的作用

```java
// ServiceConfiguration.java:4173-4182
public String getBookkeeperMetadataStoreUrl() {
    if (isBookkeeperMetadataStoreSeparated()) {
        return bookkeeperMetadataServiceUri;
    } else {
        return "metadata-store:" + getMetadataStoreUrl() + BookKeeperConstants.DEFAULT_ZK_LEDGERS_ROOT_PATH;
    }
}
```

- `bookkeeperMetadataServiceUri` 存在，**默认空**（`:2031`）
- **`bookkeeperClientMetadataServiceUri` 不存在** —— 4.2.4 只有前者一个，写笔记不要并列两个
- 分离判定 `isBookkeeperMetadataStoreSeparated()`（`:4169-4171`）= `StringUtils.isNotBlank(bookkeeperMetadataServiceUri)`
- 未分离时**共享 MetadataStore 实例**（`BookKeeperClientFactoryImpl.java:142-146`）：`bkConf.setProperty(AbstractMetadataDriver.METADATA_STORE_INSTANCE, store)`

## 元数据 key 规范

> [!WARNING]
> 旧资料的 `/admin/namespaces`、`/admin/persistent`、`LOCAL_`/`GLOBAL_` 前缀**全不存在**。真实只有两个前缀常量（`pulsar-broker-common/.../broker/resources/BaseResources.java:52-53`）：
> ```java
> protected static final String BASE_POLICIES_PATH = "/admin/policies";
> protected static final String BASE_CLUSTERS_PATH = "/admin/clusters";
> ```

**tenant 与 namespace 共用同一棵 `/admin/policies` 树**，靠路径层级区分而非不同前缀：

| 资源 | 路径 | 出处 |
| ---- | ---- | ---- |
| tenant | `/admin/policies/{tenant}` | `TenantResources.java:69` |
| namespace | `/admin/policies/{tenant}/{namespace}` | `NamespaceResources.java:89` |
| 租户列表 | `getChildren(BASE_POLICIES_PATH)` | `TenantResources.java:41` |
| 分区元数据 | `/admin/partitioned-topics` | `NamespaceResources.java:258` |
| managed-ledger 主题 | `/managed-ledgers/{ns}/{persistent\|non-persistent}` | `TopicResources.java:43,60` |
| **bundle 归属** | `/namespace/{tenant}/{ns}/{hash}` | `ServiceUnitUtils.java:37-42` |
| broker 负载上报 | `/loadbalance/brokers` | `LoadManager.java:53` |
| 只读标记 | `/admin/flags/policies-readonly` | `NamespaceResources.java:55` |

> [!TIP]
> bundle 归属是**独立的 ephemeral 节点树**（`/namespace/...`），与 `/admin/policies` 分开。这也解释了为什么 unload 后归属信息仍在（节点未被真正删除）而元数据仍可读。

## 删除路径

`ManagedLedgerImpl` 的删除调用链：

```
asyncDeleteCursor(String, DeleteCursorCallback, Object)      // :1091
  └─ cursor.asyncDeleteCursorLedger()                        // :1126
doDeleteLedgers(List<LedgerInfo>)                             // :3307
asyncDeleteLedger / FromBookKeeper / WithRetry                // :3488-3559
  └─ bookKeeper.asyncDeleteLedger(...)                        // :3553/3559
```

关键默认值：

| 项 | 值 | 位置 |
| -- | -- | ---- |
| 删除重试次数 | `DEFAULT_LEDGER_DELETE_RETRIES = 3` | `:274`（退避重试 `:3525`）|
| 并发删除限流 | `managedLedgerDeleteMaxConcurrentRequests = 1000` | `:2394` → MLConfig `ledgerDeletionSemaphore`(`:66`) |
| 范围删除持久化 | `maxUnackedRangesToPersist = 10000` | MLConfig `:48` |
| 单 ledger 当前不可删 | — | `:3138-3139` |

保留清理遍历 `ledgers` + `retentionTimeMs` / `retentionSizeInMB`，`currentLedger` 始终跳过。

## 压缩（compaction）

### 已整体重写

`CompactedLedger` / `CompactedLedgerImpl` / `CompactorImpl` / `PulsarCompaction` / `AsyncCompaction` **全部不存在**。

4.2.4 压缩代码在 **`pulsar-broker/src/main/java/org/apache/pulsar/compaction/`**（包名从 `org.apache.pulsar.broker.compaction` 改来），18 个类，含 `AbstractTwoPhaseCompactor`、`CompactedTopic`、`CompactorTool`、`PublishingOrderCompactor`、`EventTimeOrderCompactor`、`StrategicTwoPhaseCompactor`。

### 排序 key 是 partition_key

`AbstractTwoPhaseCompactor.java:457-473` `extractKeyAndSize`：

```java
if (msgMetadata.hasPartitionKey()) {              // 458
    return Pair.of(msgMetadata.getPartitionKey(), payloadSize);   // 469
} else { return null; }
```

proto：`PulsarApi.proto:117` `optional string partition_key = 6;`、`:139` `partition_key_b64_encoded`。

> [!NOTE]
> `partition_key_b64_encoded` 用于长度超过 `partition_key` 字段限制时改 Base64 编码存储 —— 读路径需判断这个标记。

### 两阶段算法

- **Phase 1**（`:137-175`）：顺序读，累积 `Map<String, T> latestForKey`（key → 最新 MessageId），产出 `PhaseOneResult(first, to, lastReadId, latestForKey)`（`:490-499`）。
- **Phase 2**（`:271-363`）：**重新读一遍**，仅当 `latestForKey.get(key).equals(id)` 才写出（`:311-312`）。

所以输出**按 key 有序、每个 key 只保留最新一条**。

> [!IMPORTANT]
> 有序性范围需要注意：`latestForKey` 是**单个 compacted ledger 内**的 map，且 compaction 是 **topic 级**操作（`Compactor.compact(String topic)`，`:58`）。因此保证的是 **topic 全量 compaction 后新 compacted ledger 内按 key 有序**，**不是**跨 compacted ledger / 跨运行轮次的全局有序。

### 触发方式已变

| 旧资料 | 4.2.4 实际 |
| ------ | --------- |
| `topicCompactionRateThreshold`（backlog 百分比）| ❌ 不存在。改为**绝对字节阈值** `brokerServiceCompactionThresholdInBytes = 0`（`:3408`，注释 `:3405-3406` 明确「**0 表示禁用压缩检查**」）|
| `compactionThread` | ❌ 不存在 |
| — | 检查间隔 `brokerServiceCompactionMonitorIntervalInSeconds = 60`（`:3401`），消费点 `BrokerService.java:779` |
| — | topic 级覆盖：`AbstractTopic.java:511` |
| — | `topicCompactionRetainNullKey = false`（`:3421`）|

常量 `Compactor.java:36` `COMPACTION_SUBSCRIPTION = "__compaction"`。

输出走独立 ledger：`COMPACTED_TOPIC_LEDGER_PROPERTY = "CompactedTopicLedger"`（`:37`）、digest `CRC32`（`:38`）。入口 `RawReader.create(pulsar, topic, COMPACTION_SUBSCRIPTION, false, false)`（`:59`）。

## 需要打假的常见说法

| 说法 | 4.2.4 实况 |
| ---- | --------- |
| 「Pulsar 一条消息 = 一个 entry」 | ❌ **支持 batch**。`MessageMetadata.num_messages_in_batch`（`PulsarApi.proto:126`，**default = 1**）区分。N 条消息打进一个 entry，条数经 `asyncAppend(buffer, numberOfMessages, ...)` 传入。batch 现在是**纯客户端侧**（`batchingMaxMessages` 在 `ProducerConfigurationData`），`ServiceConfiguration` 中已无 `isBatchingEnabled` / `maxMessagesPerBatch` |
| 「Pulsar 保证消息不重复」 | ❌ **at-least-once**。`readPosition` 在**读**时推进（`OpReadEntry.java:181-184` `updateReadPosition` → `cursor.setReadPosition`），不是 ack 时。投递后崩溃则重启从 `markDeletePosition` 重读 → 重复 |
| 「生产推荐 3/2/2」 | ⚠️ **源码/注释中未找到该推荐声明**。`ManagedLedgerConfig` 的 3/2/2 只是库级默认值，broker 侧默认是 2/2/2。不要把 3/2/2 写成「官方推荐」并声称有源码依据 |
| 「`maxMessageSize` 默认 4MB」 | ✅ **5 MB**（`Commands.java:123` `5*1024*1024`）。另有 `MESSAGE_SIZE_FRAME_PADDING = 10*1024`（`:124`）|
| 「entry 写满内存才刷盘」 | ❌ `memLimit`/`bytesSinceLastSync` 在 BK 4.17.3 已不存在。改为 entry log + Journal 双写 |
| 「BookKeeper 缓存用 LinkedList」 | ❌ 是 `ConcurrentSkipListMap` |
| 「用 magic number 校验消息格式」 | ❌ 4.x 改为 broker entry metadata 前缀 + checksum + 4 字节 size 三层跳过 |

## 未查到清单

以下项目在 4.2.4 / BK 4.17.3 **全仓零命中**，不要凭记忆补：

- `GroupWriteOp` / `WriteOp` / `WriteDataOp` / `EntryBatchOp` / `EntryBatchIndexEntry` / `dataBuffers`
- `MLAsyncWriteCallback` / `MLAddEntryCallback` / `WriteUtils` / `mlTransactionMarker` / `ErrorLogTracker`
- `EntryCacheImpl` / `LedgerEntryCache` / `NonPersistentLedgerImpl` / `PersistentLedgerImpl` / `ReadOnlyLedgerImpl`
- `CompactedLedger` / `CompactorImpl` / `PulsarCompaction` / `AsyncCompaction`
- `closingBacklogThreshold` / `closingEntryCacheSize` / `deleteFailedEntriesEnabled` / `forceDeleteLedger` / `deleteBatchLimit` / `topicCompactionRateThreshold` / `compactionThread`
- `maxGroupCommitSize` / `maxGroupCommitTime` / `readBatchSize` / `maxDeletesPerLedger` / `maxEntrySize` / `inMemoryCursorThreshold` / `numBookiesPerRack` / `isReadOnly`
- `bookkeeperClientMetadataServiceUri` / `PulsarClientImpl#createBkConf` / `BookKeeperClientConfiguration` / `RocksDBMetadataStore` / `metadata-store/` 模块
- `Commands` 中 `MAGIC_NUMBER` / `hasMagicNumber`
- BK `minBookies`（相近能力为 `enforceMinNumFaultDomainsForWrite`）
- BK `LedgerHandleImpl` / `PackagePrivateLedgerHandleImpl`
- `ManagedLedgerImpl#shouldRollOutLedger`（实际为私有 `currentLedgerIsFull()`）

## Links

- [Pulsar](/docs/CS/MQ/Pulsar/Pulsar.md)
- [Broker](/docs/CS/MQ/Pulsar/Broker.md)
- [Producer](/docs/CS/MQ/Pulsar/Producer.md)
- [Consumer](/docs/CS/MQ/Pulsar/Consumer.md)
- [集群复制与分层存储](/docs/CS/MQ/Pulsar/Cluster.md)
- [etcd（可作 metadata store）](/docs/CS/Framework/etcd/etcd.md)

## References

1. [Apache Pulsar 4.2.4 Release](https://github.com/apache/pulsar/releases/tag/v4.2.4)
2. [ManagedLedgerImpl.java (v4.2.4)](https://github.com/apache/pulsar/blob/v4.2.4/managed-ledger/src/main/java/org/apache/bookkeeper/mledger/impl/ManagedLedgerImpl.java)
3. [MLDataFormats.proto (v4.2.4)](https://github.com/apache/pulsar/blob/v4.2.4/managed-ledger/src/main/proto/MLDataFormats.proto)
4. [BookKeeper 4.17.3 LedgerHandle](https://github.com/apache/bookkeeper/blob/release-4.17.3/bookkeeper-server/src/main/java/org/apache/bookkeeper/bookie/LedgerHandle.java)
