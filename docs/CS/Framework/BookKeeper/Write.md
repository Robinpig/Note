## Introduction

BookKeeper 的写路径可以概括成一句话：**客户端把 entry 并行发给 Qw 个 bookie，收到任意 Qa 个成功就算成功；bookie 侧先落 LedgerStorage（entry log），再写 Journal（WAL），由 Journal 的 group commit 决定什么时候 fsync**。

这条路径上有三个和直觉不同、而且旧资料普遍写错的地方：

1. **确认逻辑在客户端、不在 bookie**。bookie 只负责「我收到了、我落盘了」， quorum 判定完全在 `PendingAddOp` 里。
2. **entry 先进 LedgerStorage，后进 Journal**（`BookieImpl.java:988-989` 的注释明确写了原因）。
3. **fsync 与「回调成功」解耦**：`journalSyncData=true` 时回调要等 fsync；`ackBeforeSync=true` 的单条请求可以提前回调。

> 版本基线：**4.18.1**（`release-4.18.1`）。行号均出自该 tag。

## Client-Side Write Path

```
asyncAddEntry(...)                                  // LedgerHandle.java:1416 / 1469 / 1497 ...
  └─ doAsyncAddEntry(PendingAddOp)                  // :1716
       throttler.acquire()                          // :1717-1718  客户端侧限流（默认 5000 permits/s）
       synchronized {
           entryId = ++lastAddPushed                // :1727  ★entryId 在这里分配
           op.setEntryId(entryId); pendingAddOps.add(op)   // :1729-1731
       }
       waitForWriteSetMs >= 0 → waitForWritable(...)       // :1763-1772  等待到 write set 的通道可用
       op.initiate()                                       // :1774
```

`PendingAddOp.initiate()`（`PendingAddOp.java:246`）：

```java
int flags = isRecoveryAdd ? FLAG_RECOVERY_ADD | FLAG_HIGH_PRIORITY : FLAG_NONE;      // :260
this.toSend = lh.macManager.computeDigestAndPackageForSending(
        entryId, lh.lastAddConfirmed, currentLedgerLength, payload, lh.ledgerKey, flags);  // :261-263
lh.maybeHandleDelayedWriteBookieFailure();                                           // :269
for (int i = 0; i < lh.distributionSchedule.getWriteQuorumSize(); i++) {             // :272
    sendWriteRequest(ensemble, lh.distributionSchedule.getWriteSetBookieIndex(entryId, i));
}
```

三个细节：

- **digest 是链式的**：`computeDigestAndPackageForSending` 把 `lastAddConfirmed` 与 `currentLedgerLength` 一起参与计算，所以 entry 携带了「写入时客户端认为的 LAC 与长度」。这既用于校验数据，也让 bookie 能在读 LAC 时返回可信值。
- **写发的不是 E 个而是 Qw 个**，发给 ensemble 中的哪 Qw 个由 `DistributionSchedule` 决定（默认 `RoundRobinDistributionSchedule`，按 entryId 轮转）。
- **限流在客户端**：`RateLimiter.create(conf.throttleValue)`（`LedgerHandle.java:250`），默认 `throttleValue = 5000`（`ClientConfiguration.java:237`）；设为 0 则不启用（`:252`）。

## AckSet: How Many Successes Count

每条 entry 带一个 `AckSet`（`PendingAddOp.java:101` `op.ackSet = lh.getDistributionSchedule().getAckSet()`），判定式在 `RoundRobinDistributionSchedule.java`：

```java
// :307-311  成功：已成功的 bookie 数 >= Qa
public boolean completeBookieAndCheck(int bookieIndexHeardFrom) {
    failureMap[bookieIndexHeardFrom] = null;
    ackSet.set(bookieIndexHeardFrom);
    return ackSet.cardinality() >= ackQuorumSize;
}

// :314-319  失败：失败数超过 (Qw - Qa) 就认为 ack quorum 被打破
public boolean failBookieAndCheck(int bookieIndexHeardFrom, BookieId address) {
    ackSet.clear(bookieIndexHeardFrom);
    failureMap[bookieIndexHeardFrom] = address;
    return failed() > (writeQuorumSize - ackQuorumSize);
}
```

因此**在 Qw 个目标里最多容忍 (Qw − Qa) 个失败**。以默认 3/2/2 为例：Qw=2、Qa=2 → 容忍 0 个失败，任一个 bookie 写失败就要换 ensemble；而 Pulsar 默认 2/2/2 同样容忍 0 个。

回调的触发点（`PendingAddOp.java:395-425`）：

```java
if (ackQuorum && !completed) {
    if (clientCtx.getConf().enforceMinNumFaultDomainsForWrite
        && !clientCtx.getPlacementPolicy().areAckedBookiesAdheringToPlacementPolicy(
                addEntrySuccessBookies, ...)) {
        // 已满足 Qa，但成功的 bookie 没跨够 fault domain → 延迟回调，继续等
    } else {
        completed = true;
        this.qwcLatency = MathUtils.elapsedNanos(requestTimeNanos);
        sendAddSuccessCallbacks();          // :423  ★成功回调在这里发出
    }
}
```

> [!NOTE]
> `enforceMinNumFaultDomainsForWrite` 是一个**「宁可慢也要跨够故障域」**的开关：满足 Qa 之后如果成功的副本都落在同一个 rack/region，仍不回调，等其它副本追上。它会提高写延迟，默认关闭（见 [Cluster](/docs/CS/Framework/BookKeeper/Cluster.md)）。

### Success Is Not The End Of The Story

即使在回调之后收到了其它 bookie 的错误，`PendingAddOp` 也会记账并触发 ensemble 修复（`PendingAddOp.java:300-309`）：

```java
if (completed) {
    if (rc != BKException.Code.OK) {
        // Got an error after satisfying AQ. This means we are under replicated at the create itself.
        clientCtx.getClientStats().getAddOpUrCounter().inc();
        ...
        lh.notifyWriteFailed(bookieIndex, addr);
    }
}
```

即：**「回调成功」只代表 Qa 份落盘，剩下的副本由 ensemble change 或后台 auto-recovery 补齐**。

## Ensemble Change

写失败有两条处理分支（`PendingAddOp.java:361-391`），取决于 `delayEnsembleChange`（默认 **false**，`ClientConfiguration.java:1875`）：

| 分支 | 条件 | 行为 |
| ---- | ---- | ---- |
| 延迟换副本 | `delayEnsembleChange=true` 且 `failBookieAndCheck` 为真（或遇到 `WriteOnReadOnlyBookieException`） | 攒够失败后一次性 `handleBookieFailure(failedBookies)` |
| 立即换副本 | 否则（默认） | 每个失败立即 `lh.handleBookieFailure(ImmutableMap.of(bookieIndex, addr))` |

换 ensemble 之后，**正在飞行中的 entry 要重发**，`unsetSuccessAndSendWriteRequest`（`PendingAddOp.java:191-241`）负责这件事。它有一段很有价值的注释（`:206-214`）：

> 若某条 entry k 的 write set 里**不包含**被替换的那个 bookie，那么 ensemble 变更后没人会再触发它的成功回调 —— 所以此时必须主动调一次 `sendAddSuccessCallbacks()`，否则 k 永远不完成。

```java
if (!lh.distributionSchedule.hasEntry(entryId, bookieIndex)) {   // :215
    lh.sendAddSuccessCallbacks();
    return;
}
if (!ackSet.removeBookieAndCheck(bookieIndex)) { completed = false; }   // :235-237
sendWriteRequest(ensemble, bookieIndex);                          // :240
```

> [!WARNING]
> 换 ensemble 会**追加一个 segment 到 ledger 元数据**（代价是一次元数据写入，见 [Ledger](/docs/CS/Framework/BookKeeper/Ledger.md)）。频繁 ensemble change 意味着元数据服务压力大、写延迟抖动 —— 排查写延迟时先看 ensemble change 计数，而不是只看 bookie 的磁盘。

## Bookie-Side Write Path

```java
// BookieImpl.java:980-1016
private void addEntryInternal(LedgerDescriptor handle, ByteBuf entry, boolean ackBeforeSync,
                              WriteCallback cb, Object ctx, byte[] masterKey) {
    long ledgerId = handle.getLedgerId();
    long entryId = handle.addEntry(entry);              // :984  ★先写 LedgerStorage（entry log）
    bookieStats.getWriteBytes().addCount(entry.readableBytes());
    // journal `addEntry` should happen after the entry is added to ledger storage.
    // otherwise the journal entry can be rolled before the ledger is created in ledger storage.
    ...
    if (!writeDataToJournal) {                           // :1004
        cb.writeComplete(0, ledgerId, entryId, null, ctx);
        return;
    }
    getJournal(ledgerId).logAddEntry(entry, ackBeforeSync, cb, ctx);   // :1015  ★再写 Journal
}
```

> [!IMPORTANT]
> **顺序是「先 LedgerStorage 后 Journal」，与很多资料写的相反**。源码注释（`:988-989`）给出的理由是：若先写 journal，journal 文件可能在 ledger 于 LedgerStorage 中创建之前就被 roll 掉。
>
> 另外 `memLimit` / `bytesSinceLastSync` 这套「写满内存再刷盘」的旧机制在 4.18.1 **全仓零命中**，不要照抄旧描述。内存聚合由 `EntryMemTable` 承担，刷盘由 journal 的 group commit 驱动 —— 见 [Storage](/docs/CS/Framework/BookKeeper/Storage.md)。

journal 的选择按 ledgerId 哈希分桶（`BookieImpl.java:962-964`）：

```java
private Journal getJournal(long ledgerId) {
    return journals.get(MathUtils.signSafeMod(ledgerId, journals.size()));
}
```

## Journal Group Commit And fsync

`Journal.logAddEntry`（`Journal.java:931`）把请求放进队列（`:941` `queue.put(...)`），主循环（`Journal.java:989`）决定**何时 flush**，三个条件（`Journal.java:1088-1122`）：

| 条件 | 说明 | 配置项（默认） |
| ---- | ---- | -------------- |
| 最老请求等待超时 | 队头请求等待超过阈值 | `journalMaxGroupWaitMSec` = **2 ms**（`ServerConfiguration.java:2448`） |
| 缓冲量超阈值 | 条数或字节数超阈值 | `journalBufferedWritesThreshold` = **512 KB**（`:2469`）、`journalBufferedEntriesThreshold` |
| 队列已空 | 没有可合并的请求，直接刷 | `journalFlushWhenQueueEmpty`（默认由 `journalAdaptiveGroupWrites` 推导） |

```java
// Journal.java:1130
bc.flush();
// :1134 —— 开了 syncData 但请求要求 ackBeforeSync 的，可以在 fsync 前就回调
if (entry != null && (!syncData || entry.ackBeforeSync)) { ... entry.run(); }
```

随后由 `ForceWriteThread` 批量 fsync（`Journal.java:485-557`）：

```java
int requestsCount = forceWriteRequests.takeAll(localRequests);      // :507  一次取一批
ForceWriteRequest lastRequest = localRequests[requestsCount - 1];
syncJournal(lastRequest);                                            // :513 → flushFileToDisk() :548
for (int i = 0; i < requestsCount; i++) { localRequests[i].process(writeHandlers); }  // :517-522  批量回调
```

**这就是 BookKeeper 写入延迟低但持久的原因**：一批 entry 只做一次 fsync，`lastLogMark` 记录已持久位置（`:551`）。

关键配置项（均出自 `ServerConfiguration.java`）：

| 配置 | 默认 | 行号 | 说明 |
| ---- | ---- | ---- | ---- |
| `journalSyncData` | **true** | 2378 | 是否等 fsync 后才回调。关掉可提高吞吐，但掉电会丢数据 |
| `journalAdaptiveGroupWrites` | true | 2429 | 自适应 group commit |
| `journalMaxGroupWaitMSec` | 2 | 2448 | group commit 最长等待 |
| `journalBufferedWritesThreshold` | 512 KB | 2469 | 触发刷盘的缓冲字节数 |
| `journalQueueSize` | 10000 | 971 | 待刷队列长度 |
| `numJournalCallbackThreads` | 1 | 2278 | 回调线程数 |
| `journalPreAllocSizeMB` | 16 | 866 | journal 文件预分配大小 |
| `journalWriteBufferSizeKB` | 64 | 875 | 写缓冲 |
| `journalAlignmentSize` | 512 | 917 | 对齐（V5 格式写 padding，见 `Journal.java:1126-1128`） |
| `journalMaxBackups` | 5 | 894-895 | 保留的旧 journal 文件数 |

## LAC Propagation

LAC 由**客户端**在写回调里推进（`LedgerHandle.java:1778`）：

```java
synchronized void updateLastConfirmed(long lac, long len) {
    if (lac > lastAddConfirmed) { lastAddConfirmed = lac; lacUpdateHitsCounter.inc(); }
    else { lacUpdateMissesCounter.inc(); }
    lastAddPushed = Math.max(lastAddPushed, lac);
    length.accumulateAndGet(len, (current, value) -> Math.max(current, value));
}
```

由于 entry 是并发写的，LAC 的推进需要按 entryId 顺序 —— 这就是为什么 `pendingAddOps` 是一个**有序队列**：只有队头 entry 完成，LAC 才能往前推。

另有**显式 LAC（explicit LAC）**机制：`explicitLacInterval > 0` 时客户端周期性把 LAC 作为一个特殊 entry 写入（`LedgerHandle.java:321-325`），让 bookie 侧也能知道 LAC。默认 **0（关闭）**（`ClientConfiguration.java:770`）。Pulsar 的场景通常不依赖它，读路径的安全线由客户端自己维护。

## Timeouts And Writability

| 项 | 默认 | 位置 |
| -- | ---- | ---- |
| `readTimeout` | **5 秒** | `ClientConfiguration.java:621` |
| `addEntryTimeout` | = `readTimeout` | `:646` |
| `readEntryTimeout` | = `readTimeout` | `:694` |
| `addEntryQuorumTimeout` | **-1（不启用）** | `:670` |
| `waitForWriteSetMs` | — | 在 `doAsyncAddEntry` 里决定是否等待通道可写（`LedgerHandle.java:1763-1772`） |

> [!WARNING]
> `addEntryQuorumTimeout` 默认 **-1**（不是 0，也不是某个秒数）。-1 表示「等 quorum 超时的独立计时器」关闭，此时写超时由 `addEntryTimeout` 统一兜底。把它和 `addEntryTimeout` 混为一谈是常见的配置错误。

## Corrections To Common Claims

| 说法 | 4.18.1 实况 |
| ---- | ----------- |
| 「entry 先写 Journal 再写 LedgerStorage」 | ❌ 相反。源码注释 `BookieImpl.java:988-989` 明确说明必须先进 LedgerStorage |
| 「写满 memLimit 才刷盘」 | ❌ `memLimit` / `bytesSinceLastSync` 已不存在；现在是 journal group commit + fsync |
| 「写要等 E 个副本确认」 | ❌ 只发 Qw 个、等 Qa 个 |
| 「ensemble 固定为 E 个 bookie」 | ❌ 写失败会换 ensemble，并在元数据追加 segment |
| 「ackQuorumSize 由 quorumSize 推导」 | ❌ 是 proto 的独立字段 `:9` |
| 「默认副本配置是 3/2/2」 | ⚠️ 是**客户端 API 默认重载值**（`BookKeeper.java:918`），不是配置项；Pulsar 侧默认是 2/2/2 |

## Links

- [BookKeeper](/docs/CS/Framework/BookKeeper/BookKeeper.md)
- [Ledger](/docs/CS/Framework/BookKeeper/Ledger.md)
- [Read](/docs/CS/Framework/BookKeeper/Read.md)
- [Storage](/docs/CS/Framework/BookKeeper/Storage.md)
- [Cluster](/docs/CS/Framework/BookKeeper/Cluster.md)
- [ManagedLedger 存储层](/docs/CS/MQ/Pulsar/ManagedLedger.md)

## References

1. [PendingAddOp.java (release-4.18.1)](https://github.com/apache/bookkeeper/blob/release-4.18.1/bookkeeper-server/src/main/java/org/apache/bookkeeper/client/PendingAddOp.java)
2. [Journal.java (release-4.18.1)](https://github.com/apache/bookkeeper/blob/release-4.18.1/bookkeeper-server/src/main/java/org/apache/bookkeeper/bookie/Journal.java)
3. [BookieImpl.java (release-4.18.1)](https://github.com/apache/bookkeeper/blob/release-4.18.1/bookkeeper-server/src/main/java/org/apache/bookkeeper/bookie/BookieImpl.java)
4. [BookKeeper — Persistence & performance](https://bookkeeper.apache.org/docs/latest/reference/config)
