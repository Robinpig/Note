## Introduction

bookie 的存储由**三件套**组成，理解它们的关系就理解了 bookie 的全部 I/O：

| 组件 | 角色 | 访问模式 |
| ---- | ---- | -------- |
| **Journal** | 预写日志（WAL），只为**持久性**服务，写完即可覆盖 | 严格顺序 append + fsync |
| **EntryLog** | entry 的**数据本体**，多个 ledger 交错写入同一个文件 | 顺序 append（写入时），随机读（读取时） |
| **Index** | `(ledgerId, entryId) → (entryLogId, offset)` 的映射 | 小随机读，靠内存页缓存 |

Journal 保证「确认过的写不会因进程崩溃而丢」，EntryLog 保证「能按位点把数据读回来」，Index 负责两者之间的定位。三者分离的直接结果是：**写放大可控（顺序写），而读需要一次索引跳转**。

> 版本基线：**4.18.1**（`release-4.18.1`）。行号均出自该 tag；配置项默认出自 `ServerConfiguration.java`。

## LedgerStorage Implementations

默认实现是 **`SortedLedgerStorage`**，不是很多资料写的 `DbLedgerStorage`：

```java
// ServerConfiguration.java:64-75
protected static final ConfigKey LEDGER_STORAGE_CLASS_KEY = ConfigKey.builder(LEDGER_STORAGE_CLASS)
    .type(Type.CLASS)
    .description("Ledger storage implementation class")
    .defaultValue(SortedLedgerStorage.class)                       // :68 ★默认
    .optionValues(Lists.newArrayList(
        InterleavedLedgerStorage.class.getName(),
        SortedLedgerStorage.class.getName(),
        DbLedgerStorage.class.getName()))
    .validator(ClassValidator.of(LedgerStorage.class))
    ...
```

> [!WARNING]
> 两个常见误记：
> - 「4.x 默认用 `DbLedgerStorage`」 —— **错**。默认 `SortedLedgerStorage`；`DbLedgerStorage`（`org.apache.bookkeeper.bookie.storage.ldb` 包）是**可选项**，需要用 `ledgerStorageClass` 显式指定。
> - 「`EntryLogger.java` 是 entry log 的实现类」 —— 4.18.1 的 `bookie/` 包里**没有 `EntryLogger.java`**，实际类是 `DefaultEntryLogger.java`（另有 `ReadOnlyDefaultEntryLogger`、`EntryLogManager*` 系列）。按旧类名去源码里找会 404。

`getLedgerStorageClass()`（`:3126-3139`）还保留了一段 4.3 兼容逻辑：若显式配置了 `SortedLedgerStorage` 但 `sortedLedgerStorageEnabled=false`，则退化为 `InterleavedLedgerStorage`。

### SortedLedgerStorage: Write Into A Skip List, Flush Sorted

`SortedLedgerStorage` 在 `InterleavedLedgerStorage` 之上加了一层**内存排序**：entry 先进 `EntryMemTable`（跳表），刷盘时按 `(ledgerId, entryId)` 排序写入 entry log，从而让同一个 ledger 的 entry 在文件里尽量连续 —— 这正是「同一 ledger 顺序读很快、随机读很慢」的物理原因。

```java
// EntryMemTable.java:42-45（类注释）
// The EntryMemTable holds in-memory representation to the entries not-yet flushed.
// When asked to flush, current EntrySkipList is moved to snapshot and is cleared.
```

相关配置：

| 配置 | 默认 | 行号 |
| ---- | ---- | ---- |
| `sortedLedgerStorageEnabled` | true | 2298 |
| `skipListSizeLimit` | **64 MB** | 2308 |
| `skipListArenaChunkSize` | 4 MB | 2333 |
| `skipListArenaMaxAllocSize` | 128 KB | 2355 |
| `flushInterval` | **10000 ms** | 651-653 |
| `flushIntervalInBytes` | 0（按字节刷盘阈值，0 表示不启用） | 678-680 |

## Journal

写入侧见 [Write](/docs/CS/Framework/BookKeeper/Write.md)，这里只列文件与配置层面的事实：

| 配置 | 默认 | 行号 | 说明 |
| ---- | ---- | ---- | ---- |
| `journalDirectory` / `journalDirectories` | `/tmp/bk-txn` | 1379 | **默认是临时目录**，生产必须改 |
| `journalMaxSizeMB` | **2048 MB** | 844-846 | 单个 journal 文件大小上限，达到即滚动 |
| `journalMaxBackups` | 5 | 894-895 | 保留的旧 journal 文件数 |
| `journalPreAllocSizeMB` | 16 | 866 | 预分配，减少文件碎片 |
| `journalWriteBufferSizeKB` | 64 | 875 | 写缓冲 |
| `journalAlignmentSize` | 512 | 917 | V5 格式会写 padding（`Journal.java:1126-1128`） |
| `journalQueueSize` | 10000 | 971 | 待刷队列长度 |
| `journalSyncData` | **true** | 2378 | 是否等 fsync |
| `journalAdaptiveGroupWrites` | true | 2429 | 自适应 group commit |

> [!TIP]
> **Journal 与 entry log 必须放在不同磁盘**（journal 顺序写 + fsync，entry log 随机读），这是 BookKeeper 部署的硬建议，也是为什么配置里 `journalDirectories` 与 `ledgerDirectories` 是两个独立的键（`:174-175`）。放同一块盘时，读写会互相打断顺序性。

## EntryLog

- 多个 ledger 的 entry **交错写入同一个 entry log 文件**，靠 index 定位。
- 文件达到 `logSizeLimit` 就滚动新建。默认 **1 GiB**（`ServerConfiguration.java:85-91`：默认值取 `BookKeeperConstants.MAX_LOG_SIZE_LIMIT`，其定义为 `1 * 1024 * 1024 * 1024`，即 1 GiB）。

> [!NOTE]
> 「entry log 默认 2 GB」是流传很广的错误说法。4.18.1 的上限常量是 **1 GiB**（`BookKeeperConstants.java` `MAX_LOG_SIZE_LIMIT = 1 * 1024 * 1024 * 1024`），而 `logSizeLimit` 的默认值就等于这个上限。

- `entryLogPerLedgerEnabled` 默认 **false**（`ServerConfiguration.java:3981`）。打开后每个 ledger 单独一个 entry log，利于删除但会产生大量文件（有 `entryLogPerLedgerCounterLimitsMultFactor` 兜底，默认 10，`:4054`）。

## Index

索引由 `LedgerCacheImpl` 管理（详见 [Read](/docs/CS/Framework/BookKeeper/Read.md) 的「Bookie-Side Read」一节）：

```java
this.pageSize = conf.getPageSize();        // 默认 8192（ServerConfiguration.java:750-751）
this.entriesPerPage = pageSize / 8;        // 每项 8 字节 → 1024 项/页
this.indexPersistenceManager = new IndexPersistenceMgr(...);
this.indexPageManager = new IndexInMemPageMgr(...);
```

| 配置 | 默认 | 行号 |
| ---- | ---- | ---- |
| `pageSize` | 8192 | 750-751 |
| `pageLimit` | **-1**（由 openFileLimit 推导） | 729-730 |
| `openFileLimit` | 20000 | 708-709 |
| `indexDirectories` | 未配置时与 `ledgerDirectories` 相同 | 1488-1491 |
| fileInfo 缓存初始容量 | `max(openFileLimit / 4, 64)` | 777 |

## Garbage Collection

entry log 里混着活的和已删除的 ledger 数据，空间回收靠 `GarbageCollectorThread`（`bookie/GarbageCollectorThread.java`）**扫描 + 搬迁**：把一个 entry log 里仍然存活的 entry 读出来重写到新文件，然后删掉旧文件。

```
GarbageCollectorThread.run()                  // :445
  └─ runWithFlags(force, suspendMajor, suspendMinor)   // :453
       extractMetaFromEntryLogs()             // :879  扫描 entry log，建立「entryLogId → 含哪些 ledger、占多少字节」
       if (major 到期)  doCompactEntryLogs(majorCompactionThreshold, ...)   // :501
       if (minor 到期)  doCompactEntryLogs(minorCompactionThreshold, ...)   // :524
            └─ compactor.compact(entryLogMeta)   // :861
```

- **minor compaction**：存活率低于 `minorCompactionThreshold` 的 entry log 被压缩，默认 **0.2 / 3600 秒**（`:1785` / `:1865`）。
- **major compaction**：默认 **0.8 / 86400 秒**（`:1813` / `:1890`）。
- **GC 间隔**：`gcWaitTime` 默认 **600000 ms**（`:424`），且启动时校验 `minorCompactionInterval >= gcWaitTime`（`:251-253`）。

| 配置 | 默认 | 行号 |
| ---- | ---- | ---- |
| `minorCompactionThreshold` | 0.2 | 1785 |
| `minorCompactionInterval` | 3600 秒 | 1865 |
| `majorCompactionThreshold` | 0.8 | 1813 |
| `majorCompactionInterval` | 86400 秒 | 1890 |
| `gcWaitTime` | 600000 ms | 424 |
| `compactionRate` | 1000（条/秒） | 3016 |
| `compactionRateByBytes` | 1000000 | 3058 |
| `isForceGCAllowWhenNoSpace` | —（磁盘满时是否允许强制 GC） | 113 / 213 |
| `gcEntryLogMetadataCacheEnabled` / `gcEntryLogMetadataCachePath` | 元数据缓存，避免每次全量扫描 | 120-121 |

> [!IMPORTANT]
> GC **不感知上层的删除语义**，它只看「这个 ledger 在元数据里还存在吗」。所以：ledger 被 delete 之后，空间不会立刻释放 —— 要等到下一轮 GC 扫到它所在的 entry log 并压缩。这是「删了数据但磁盘没降」的第一解释。

> [!WARNING]
> `minorCompactionThreshold` 与 `majorCompactionThreshold` 都是**存活率阈值**（不是「垃圾率」）：entry log 里存活比例低于 0.2 才触发 minor。启动时若 `threshold > 1.0` 会直接抛 `IOException`（`:247-249`）。

## Disk Usage And Read-Only Mode

bookie 会周期性检查磁盘使用率（`diskCheckInterval` 默认 **10000 ms**，`:2679`），超过阈值就进入只读：

| 配置 | 默认 | 行号 |
| ---- | ---- | ---- |
| `diskUsageWarnThreshold` | 0.90 | 2587 |
| `diskUsageThreshold` | **0.95** | 2631 |
| `diskUsageLwmThreshold` | 未设置时 = `diskUsageThreshold` | 2659 |
| `readOnlyModeEnabled` | **true** | 2544 |
| `readOnlyModeOnAnyDiskFullEnabled` | true | 2566 |
| `minUsableSizeForEntryLogCreation` | **1.2 × `logSizeLimit`** | 3620 |
| `minUsableSizeForHighPriorityWrites` | 未设置时 = `minUsableSizeForEntryLogCreation` | 3646 |

只读模式下仍有两类写入被允许（源码注释 `:3626-3628`）：**compaction 的搬迁写入**与 **journal replay**，前提是剩余空间 ≥ `minUsableSizeForEntryLogCreation`。

> [!TIP]
> 这个设计解释了运维中的一个反直觉现象：**bookie 已经只读了，磁盘却还在被写入**。那不是泄漏，是 GC 在搬迁数据以腾出空间；只要剩余空间不足 `1.2 × logSizeLimit`，连搬迁都会停 —— 所以磁盘水位**不要逼近 100%**，否则连自愈都做不了。

## Write Path On Disk (Summary)

```
写入请求
  ├─ LedgerStorage.addEntry → EntryMemTable（跳表，排序）
  │       刷盘触发：flushInterval / skipListSizeLimit / 显式 flush
  │       └─ 排序后 append 到 EntryLog（DefaultEntryLogger）
  │             └─ 更新 Index（IndexInMemPageMgr → IndexPersistenceMgr）
  └─ Journal.logAddEntry → 队列 → group commit → fsync（ForceWriteThread）
        └─ fsync 成功后回调客户端
```

## Corrections To Common Claims

| 说法 | 4.18.1 实况 |
| ---- | ----------- |
| 「默认存储实现是 `DbLedgerStorage`」 | ❌ 默认 `SortedLedgerStorage`（`ServerConfiguration.java:68`） |
| 「entry log 默认 2 GB」 | ❌ 1 GiB（`MAX_LOG_SIZE_LIMIT = 1 * 1024 * 1024 * 1024`） |
| 「bookie 用 `LedgerCache` 缓存 entry 数据」 | ❌ 只缓存**索引页** |
| 「写满内存才刷盘」 | ❌ `memLimit` 等已不存在；由 `flushInterval`（默认 10 s）与 skip list 上限驱动 |
| 「删掉 ledger 立刻释放磁盘」 | ❌ 要等 GC 扫描 + 压缩该 entry log |

## Links

- [BookKeeper](/docs/CS/Framework/BookKeeper/BookKeeper.md)
- [Write](/docs/CS/Framework/BookKeeper/Write.md)
- [Read](/docs/CS/Framework/BookKeeper/Read.md)
- [Cluster](/docs/CS/Framework/BookKeeper/Cluster.md)
- [Ops](/docs/CS/Framework/BookKeeper/Ops.md)
- [ManagedLedger 存储层](/docs/CS/MQ/Pulsar/ManagedLedger.md)

## References

1. [ServerConfiguration.java (release-4.18.1)](https://github.com/apache/bookkeeper/blob/release-4.18.1/bookkeeper-server/src/main/java/org/apache/bookkeeper/conf/ServerConfiguration.java)
2. [GarbageCollectorThread.java (release-4.18.1)](https://github.com/apache/bookkeeper/blob/release-4.18.1/bookkeeper-server/src/main/java/org/apache/bookkeeper/bookie/GarbageCollectorThread.java)
3. [BookKeeper — Bookie storage](https://bookkeeper.apache.org/docs/latest/reference/config)
4. [BookKeeper — Admin: disk full / readonly](https://bookkeeper.apache.org/docs/latest/admin/bookies)
