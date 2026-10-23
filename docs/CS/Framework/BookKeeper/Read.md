## Introduction

读路径的核心约束只有一条：**只能读到 LAC 之前的 entry**。写路径决定 LAC 推进到哪（见 [Write](/docs/CS/Framework/BookKeeper/Write.md)），读路径只负责在副本集合里把 entry 取回来、并在取的过程中顺手把 LAC 往前推。

与写路径对称又不对称的地方是：**读只需要命中一个副本**（因为任意持有该 entry 的 bookie 内容都相同），但为了对抗慢节点，客户端会做 speculative read 与读序重排。

> 版本基线：**4.18.1**（`release-4.18.1`）。行号均出自该 tag。

## Entry Read: One Replica Is Enough

`PendingReadOp.initiate()`（`PendingReadOp.java:66-92`）把一次区间读拆成若干个单 entry 请求，并按 ensemble 的分段边界切换副本集合：

```java
long nextEnsembleChange = startEntryId, i = startEntryId;
do {
    if (i == nextEnsembleChange) {
        ensemble = getLedgerMetadata().getEnsembleAt(i);                              // :72
        nextEnsembleChange = LedgerMetadataUtils.getNextEnsembleChange(getLedgerMetadata(), i);  // :73
    }
    SingleLedgerEntryRequest entry;
    if (parallelRead) {
        entry = new ParallelReadRequest(ensemble, lh.ledgerId, i);                    // :77
    } else {
        entry = new SequenceReadRequest(ensemble, lh.ledgerId, i);                    // :79
    }
    seq.add(entry);
    i++;
} while (i <= endEntryId);
```

两种模式的差别很关键：

| 模式 | 行为 | 代价 |
| ---- | ---- | ---- |
| `SequenceReadRequest`（默认） | 一条一条读：读完 entry k 才发 k+1 | 延迟 = Σ 单条延迟，但只对副本集合中的一个 bookie 产生压力 |
| `ParallelReadRequest`（`parallelRead=true`） | 把区间内所有 entry 一次性发出去 | 吞吐高，但会同时打在多个 bookie 上，且可能读到 LAC 之后的空洞 |

> [!WARNING]
> 默认并不是并行读。`PendingReadOp.java:48` 的字段声明是 `protected boolean parallelRead = false;`，由 `parallelRead(boolean)`（`:61`）显式打开。把它当成默认行为会严重误判读性能模型。

单个 entry 读失败时按顺序换下一个副本（`PendingReadOp.java:99-101` → `logErrorAndReattemptRead`），最多试到 write quorum 个副本为止（`:358-370` `sendNextRead()`，`nextReplicaIndexToReadFrom >= getLedgerMetadata().getWriteQuorumSize()` 时放弃）。

> [!NOTE]
> `PendingReadOp.java:393` 有一条注释值得记住：**speculative 读的结果不走重投逻辑**（「a faster (e.g. speculative) read must not flow through the reattempt logic」）—— 否则一次慢响应会把慢 bookie 错误地标记为故障。

## LAC: The Read Boundary

读请求超过 LAC 会被直接拒绝。`LedgerHandle` 里有两处校验：

```java
// LedgerHandle.java:936-940（batch 读）
if (lastEntry > lastAddConfirmed) { ... }        // 抛错
// LedgerHandle.java:968-971（区间读）
if (startEntry > lastAddConfirmed) { ... }
```

另外 **`readUnconfirmedAsync` / `batchReadUnconfirmedAsync`（`LedgerHandle.java:1162` / `:1006`）是例外**：它们允许读未确认的尾部 entry，只用于恢复与运维探查，正常消费路径不要用。

有意思的是，**读响应本身也会推进 LAC**：

```java
// PendingReadOp.java:110-113
if (!isRecoveryRead) {
    // do not advance LastAddConfirmed for recovery reads
    lh.updateLastConfirmed(rctx.getLastAddConfirmed(), 0L);
}
```

因为每个读响应都携带该 bookie 认为的 LAC（`computeDigestAndPackageForSending` 时写进 entry 的字段），所以**一个只读客户端也能通过观察把 LAC 往前推**。这也是「打开 ledger 读一会儿后可读范围变大」的原因。

查询 LAC 的三个入口：

| 方法 | 位置 | 说明 |
| ---- | ---- | ---- |
| `tryReadLastAddConfirmedAsync()` | `LedgerHandle.java:1899` | 返回**本地已知**的 LAC，不发请求 |
| `readLastAddConfirmedAsync()` | `:1909` | 向 bookie 询问 |
| `readLastAddConfirmedAndEntryAsync(entryId)` | `:1919` | 读 LAC 同时把该 entry 取回（长轮询场景用） |

## Speculative Read

慢 bookie 是读延迟的主要来源。BookKeeper 的做法是**超时后向下一个副本再发一次同样的请求，谁先回来用谁**（`PendingReadOp.java:87-90`）：

```java
if (!parallelRead && clientCtx.getConf().readSpeculativeRequestPolicy.isPresent()) {
    speculativeTask = clientCtx.getConf().readSpeculativeRequestPolicy.get()
        .initiateSpeculativeRequest(clientCtx.getScheduler(), entry);
}
```

相关配置（`ClientConfiguration.java`）：

| 配置 | 默认 | 行号 |
| ---- | ---- | ---- |
| `speculativeReadTimeout` | **2000 ms** | 945-946 |
| `firstSpeculativeReadTimeout` | = `speculativeReadTimeout` | 971 |
| `maxSpeculativeReadTimeout` | = `speculativeReadTimeout` | 1036 |
| `speculativeReadTimeoutBackoffMultiplier` | **2.0** | 991 |
| `firstSpeculativeReadLACTimeout` / LAC 相关 | 同上体系 | 110-112 |

> [!TIP]
> 默认值构成一个「首次 2 秒后重试，之后按 2 倍退避直到上限」的策略。低延迟场景（如 Pulsar 的 tailing read）通常会把 `firstSpeculativeReadTimeout` 调到几十毫秒量级，而把 `maxSpeculativeReadTimeout` 保持在秒级以避免无效重发。

## Read Ordering: Reorder And Sticky Reads

读序由 placement policy 决定（默认 `RackawareEnsemblePlacementPolicy`，`ClientConfiguration.java:1233-1237`）：

- `reorderReadSequence(ensemble, bookiesHealthInfo, ...)`（`RackawareEnsemblePlacementPolicy.java:152`）——按历史延迟与「本地性」把副本排序，把最快的排前面。
- `reorderReadLACSequence(...)`（`:161`）——读 LAC 时的排序，逻辑与上者不同（LAC 请求更轻）。
- 开关：`reorderReadSequenceEnabled`（配置键见 `ClientConfiguration.java:116`），触发阈值 `reorderThresholdPendingRequests` 默认 **0（关闭）**（`:1259`）。
- `stickyReadSEnabled`（配置键 `:117`）：让同一客户端尽量固定读同一个副本，利于利用 bookie 侧的文件缓存。

> [!NOTE]
> 读序重排**默认不生效**（阈值为 0）。它是为「bookie 多、延迟差异大」的集群准备的调优项，不是基础机制。

## Bookie-Side Read

```java
// BookieImpl.java:1159-1185
public ByteBuf readEntry(long ledgerId, long entryId) throws ... {
    LedgerDescriptor handle = handles.getReadOnlyHandle(ledgerId);
    ByteBuf entry = handle.readEntry(entryId);
    ...
}
```

`LedgerDescriptorImpl` 只是把读写委派给 `LedgerStorage`（`LedgerDescriptorImpl.java:162` `return ledgerStorage.getEntry(ledgerId, entryId);`）。因此「从 entryId 找到数据」的责任在存储层，分两步：

1. **查索引**：`(ledgerId, entryId) → (entryLogId, offset)`。索引由 `LedgerCacheImpl` 管理，它**只管索引页**：

   ```java
   // LedgerCacheImpl.java（构造）
   this.pageSize = conf.getPageSize();             // 默认 8192（ServerConfiguration.java:751）
   this.entriesPerPage = pageSize / 8;             // 每个 entry 索引占 8 字节 → 1024 项/页
   this.indexPersistenceManager = new IndexPersistenceMgr(...);
   this.indexPageManager = new IndexInMemPageMgr(...);
   ```

   内存页由 `IndexInMemPageMgr` 管理（LRU 换入换出），持久化由 `IndexPersistenceMgr` 负责写 index 文件（`.idx`）。
2. **读数据**：用上一步拿到的位置去 entry log 文件里读，校验 digest 后返回。

> [!IMPORTANT]
> 常见误解：**「bookie 用 `LedgerCache` 缓存 entry 数据」**。`LedgerCacheImpl` 的类注释（`:36-38`）写的是它「serves two purposes」，但两个都指向索引页管理；entry 数据本体在 entry log 文件里，靠 OS page cache。所以内存调优里「给 entry 缓存分配多大」这个问题在 BookKeeper 里**不存在**（Pulsar 侧的 `RangeEntryCache` 才是 entry 缓存，见 [ManagedLedger 存储层](/docs/CS/MQ/Pulsar/ManagedLedger.md)）。

## Read Path Summary

```
readEntries(first, last)                     // LedgerHandle.java:677
  └─ asyncReadEntriesInternal(...)           // :1175
       校验 lastEntry <= lastAddConfirmed    // :936 / :968
       PendingReadOp.initiate()              // PendingReadOp.java:66
         按 segment 定位 ensemble            // :72-73
         SequenceReadRequest / ParallelReadRequest  // :79 / :77
         + speculative 定时任务              // :87-90
              └─ bookieClient.read(entry)
                   └─ BookieImpl.readEntry  // BookieImpl.java:1159
                        └─ LedgerDescriptorImpl.readEntry → LedgerStorage.getEntry  // :162
                              ├─ LedgerCacheImpl 查索引页（IndexInMemPageMgr）
                              └─ 从 entry log 读数据 + 校验 digest
       readEntryComplete → updateLastConfirmed  // PendingReadOp.java:112
```

## Corrections To Common Claims

| 说法 | 4.18.1 实况 |
| ---- | ----------- |
| 「读要拿到 Qw 个副本」 | ❌ 命中一个即可；失败才换下一个副本，最多试 Qw 个 |
| 「默认是并行读」 | ❌ `parallelRead` 默认 false（`PendingReadOp.java:48`），默认是 `SequenceReadRequest` |
| 「LAC 只有写者能推进」 | ❌ 读响应也携带 LAC 并推进（`PendingReadOp.java:112`），恢复读除外 |
| 「bookie 有 entry 数据缓存」 | ❌ `LedgerCacheImpl` 只管索引；数据靠 OS page cache |
| 「speculative read 默认关闭」 | ⚠️ speculative 由 `readSpeculativeRequestPolicy` 决定；阈值默认 2000 ms，**不是关闭** |

## Links

- [BookKeeper](/docs/CS/Framework/BookKeeper/BookKeeper.md)
- [Ledger](/docs/CS/Framework/BookKeeper/Ledger.md)
- [Write](/docs/CS/Framework/BookKeeper/Write.md)
- [Storage](/docs/CS/Framework/BookKeeper/Storage.md)
- [Cluster](/docs/CS/Framework/BookKeeper/Cluster.md)
- [ManagedLedger 存储层](/docs/CS/MQ/Pulsar/ManagedLedger.md)

## References

1. [PendingReadOp.java (release-4.18.1)](https://github.com/apache/bookkeeper/blob/release-4.18.1/bookkeeper-server/src/main/java/org/apache/bookkeeper/client/PendingReadOp.java)
2. [LedgerHandle.java (release-4.18.1)](https://github.com/apache/bookkeeper/blob/release-4.18.1/bookkeeper-server/src/main/java/org/apache/bookkeeper/client/LedgerHandle.java)
3. [BookieImpl.java (release-4.18.1)](https://github.com/apache/bookkeeper/blob/release-4.18.1/bookkeeper-server/src/main/java/org/apache/bookkeeper/bookie/BookieImpl.java)
4. [BookKeeper — Client configuration](https://bookkeeper.apache.org/docs/latest/reference/config)
