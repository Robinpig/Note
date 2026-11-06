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

### DbLedgerStorage: When To Choose It

默认 `SortedLedgerStorage` 的索引是**内存页缓存 + 磁盘 Index 文件**（`LedgerCacheImpl`），对「百万级 ledger、海量小 ledger」场景，内存页缓存会被撑爆。此时应切到 `DbLedgerStorage`：

- 索引改用 **RocksDB**（`EntryLocationIndex` + `LedgerMetadataIndex`），把 `(ledgerId, entryId) → (entryLogId, offset)` 落盘到 LSM-tree，内存占用与 ledger 数量解耦；
- 配合 **WriteCache / ReadCache** 两级缓存承接热数据（即 Pulsar 默认推荐配置，见 [ManagedLedger 存储层](/docs/CS/MQ/Pulsar/ManagedLedger.md)）；
- 代价：多一层 RocksDB 的写放大与 compaction 开销，运维复杂度高于纯页缓存。

> [!TIP]
> 一句话取舍：**ledger 数量不多、单 ledger 较大 → `SortedLedgerStorage`（简单、零额外进程）；ledger 数量极多（百万级）、需要稳定内存占用 → `DbLedgerStorage`**。Pulsar 因每个 topic 的 cursor、每个 managed-ledger 都对应独立 ledger，天然落入后者。

### DbLedgerStorage: Read Path (Source-level)

> [!NOTE]
> `DbLedgerStorage` 本身只是一个**分片路由层**。它持有 `List<SingleDirectoryDbLedgerStorage> ledgerStorageList`（每个 ledger 目录一个实例），`getEntry()`（`DbLedgerStorage.java:360`）只是 `getLedgerStorage(ledgerId).getEntry(...)` 的转发；分片由 `MathUtils.signSafeMod(ledgerId, numberOfDirs)`（`:429`）决定。真正的读逻辑在 `SingleDirectoryDbLedgerStorage.doGetEntry`（`:580`）。源码取自本地 `E:/Projects/bookkeeper`（master，末提交 `Generate 4.18.2 release note`，与 4.18.1 基线一致）。

读一条 entry 的顺序（命中即返回）：

1. **WriteCache**（`:608`）：先查 `writeCache`。因为 flush 是异步 swap，还要查 `writeCacheBeingFlushed`（`:615`，正在落盘的缓冲），两者都通过 `writeCacheRotationLock.tryOptimisticRead()`（`:593`）乐观读锁取引用，避免缓存切换时的并发问题。命中即返回（stats `writeCacheHit`）。
2. **ReadCache**（`:624`）：read-ahead 缓存命中即返回（`readCacheHit`）。
3. **索引查找**（`:636`）：`entryLocationIndex.getLocation(ledgerId, entryId)`。底层是 RocksDB（`KeyValueStorage locationsDb`，`EntryLocationIndex.java:48`），key = `ledgerId(8) + entryId(8)` 共 16 字节，value = 8 字节 packed location（`entryLogId<<32 | offset`）。**返回 0 = 该 entry 不存在/已删除**，此时 `throwIfLimbo` 后抛 `NoEntryException`（`:637-642`）；读 LAC 之外的未确认 entry 也是在这里失败。
4. **EntryLog 随机读**（`:650`）：`entryLogger.readEntry(ledgerId, entryId, entryLocation)` 按 location 直接定位文件 + offset，不依赖顺序扫描。
5. **回填 + 预读**（`:656-660`）：读到的 entry 放入 `ReadCache`，并触发 `fillReadAheadCache(ledgerId, entryId+1, nextEntryLocation)` 预读后续 entry。

```java
// SingleDirectoryDbLedgerStorage.java:636-660（节选）
entryLocation = entryLocationIndex.getLocation(ledgerId, entryId);   // RocksDB 索引
if (entryLocation == 0) throw new NoEntryException(ledgerId, entryId);
entry = entryLogger.readEntry(ledgerId, entryId, entryLocation);     // entry log 随机读
readCache.put(ledgerId, entryId, entry);
fillReadAheadCache(ledgerId, entryId + 1, entryLocation + 4 + entry.readableBytes());
```

**Read-ahead 的边界（多 ledger 交错的物理体现）**：`fillReadAheadCache`（`:665`）从 `nextEntryLocation` 起循环预读，有两个硬约束（`chargeReadAheadCache`, `:714`）—— 批次上限 `readAheadCacheBatchSize` / `maxReadAheadBytesSize`（默认 `readCacheMaxSize/2`，`:191`），以及**只在同一个 entry log 文件内**预读（entryLogId 取 location 高 32 位 `>> 32`，`:671/696`，`:675` 的 `currentEntryLogId == firstEntryLogId`）。每次预读都解析 entry 头部 `entry.getLong(0)=ledgerId`、`entry.getLong(8)=entryId`（正是上文的 V1 落盘格式），一旦 `currentEntryLedgerId != originalLedgerId`（撞到另一个 ledger 的交错 entry）立即停（`:683`）—— 这就是「多 ledger 共用一个 entry log」在读取端必须逐条校验 ledgerId 的原因。

> [!TIP]
> **为什么 DbLedgerStorage 内存可控**：`ReadCache` / `WriteCache` 用 Netty 的 `ByteBufAllocator`（直接内存，off-heap，`ReadCache.java:157` `allocator.buffer(...)`），`EntryLocationIndex` 是 RocksDB（block cache 也是堆外）。三者都不占 JVM 堆，与 ledger 数量**解耦** —— 这是它相对 `SortedLedgerStorage`（索引在 JVM 堆内页缓存 `LedgerCacheImpl`）能在百万级 ledger 下保持内存平稳的根本原因。

> [!WARNING]
> **long-poll 不在 DbLedgerStorage**。此处 `doGetEntry` 是**同步**的：entry 不存在直接抛 `NoEntryException`，**不挂起、不 pending**。读 LAC 之外的未确认 entry 时「等待写入完成」的 long-poll 语义由上层 `ReadEntryProcessor` / `LongPollReadEntryProcessor` 实现（见 [Read](/docs/CS/Framework/BookKeeper/Read.md)）。对比表里写的「+ speculative」在此处指**存储层 read-ahead**（`fillReadAheadCache`），不是 client 跨副本的 speculative read。

**与 SortedLedgerStorage 读路径对比**：

| 维度 | SortedLedgerStorage | DbLedgerStorage |
| -- | -- | -- |
| 索引位置 | JVM 堆内页缓存（`LedgerCacheImpl`）+ 磁盘 Index 文件 | RocksDB（堆外 block cache） |
| 热数据缓存 | 仅索引页缓存，entry 不常驻 | off-heap ReadCache + WriteCache（Netty 直接内存） |
| 定位 entry | `(ledgerId, entryId) → offset`（页内偏移） | `(ledgerId, entryId) → (entryLogId<<32\|offset)`（RocksDB） |
| 预读 | 无显式 read-ahead | `fillReadAheadCache`（同 entry log 内连续预取） |
| LAC 外 entry | 同步抛异常 | 同步抛 `NoEntryException`（long-poll 在上层） |
| 内存与 ledger 数 | 强相关（堆内缓存随 ledger 膨胀） | 解耦（堆外 + RocksDB） |

#### EntryLogger: Location → Bytes（文件定位与 Direct I/O 读）

> [!NOTE]
> 第 4 步 `entryLogger.readEntry(ledgerId, entryId, entryLocation)` 中的 `entryLogger` 是实现接口 `org.apache.bookkeeper.bookie.storage.EntryLogger` 的实例。DbLedgerStorage 在初始化时按条件二选一（`DbLedgerStorage.java:227/239`）：
> - `if (conf.isUseDirectEntryLogger() && NativeIO.isAvailable())` → **`DirectEntryLogger`**（direct I/O 版本）；
> - 否则（默认）→ **`DefaultEntryLogger`**（普通 FileChannel 版本）。
> 两种实现**共用同一套 location 编码**，因此 `EntryLocationIndex` 里存的 8 字节 location 对两者都有效。

**location 的编码与解码**（两种实现完全一致）：

```java
// DefaultEntryLogger.java:700-705（解码）
static long logIdForOffset(long offset) { return offset >> 32L; }       // 高 32 位 = entryLogId
static long posForOffset(long location) { return location & 0xffffffffL; } // 低 32 位 = 文件内 offset

// DirectEntryLogger.java:247-248（同一编码）
int logId = (int) (location >> 32);
int pos   = (int) (location & 0xFFFFFFFF);
// ⇒ location = (entryLogId << 32) | (offset in file)
```

**物理文件定位**：从 `entryLogId` 找到磁盘文件由 `findFile(logId)`（`DefaultEntryLogger.java:977`）完成 —— 在**所有 ledger 目录**下逐个试 `Long.toHexString(logId) + ".log"`（十六进制文件名，如 `log.1f3a`）。找到后用 `getChannelForLogId`（`:909-932`）以 `new RandomAccessFile(file, "r").getChannel()` 打开**只读** `FileChannel`，包成 `BufferedReadChannel`（带 BK 自己的 read-ahead buffer，大小 `readBufferBytes`），并以 `logid2FileChannel.putIfAbsent` 缓存（每个 logId 一个 channel，线程安全）。`DirectEntryLogger` 则走 `DirectReader` + 每 logId 一个 `Cache<Integer,LogReader>` 的 FD 缓存（`maxFdCacheTimeSeconds` 控制回收）。

**两条读实现对比**：

| 维度 | DefaultEntryLogger（默认） | DirectEntryLogger（direct I/O） |
| -- | -- | -- |
| 底层读 | `BufferedReadChannel` → `FileChannel.read(buf, pos)` | `NativeIO.pread(fd, alignedPtr, size, blockStart)` |
| 是否过 page cache | 是（走 OS page cache） | **否**（O_DIRECT，直接读进 native 对齐 buffer） |
| 缓冲层 | BK `readBufferBytes` read-ahead buffer | `nativeBuffer`（block 对齐，O_DIRECT 必需对齐） |
| FD/reader 管理 | `logid2FileChannel` map | `Cache<Integer,LogReader>`，按 logId 缓存 + 超时回收 |
| 典型场景 | 通用默认 | 大 entry、想避免污染 page cache |

**零拷贝本质辨析**：`DirectEntryLogger` 的「零拷贝」不是 sendfile 那种「内核→socket 零拷贝」，而是 **direct I/O（O_DIRECT）绕过 page cache** —— `DirectReader.readBlock`（`DirectReader.java:194-216`）把文件按 `nativeBuffer` 的 block 大小对齐，再用 `nativeIO.pread(fd, nativeBuffer.pointer(...), readSize, blockStart + bufferOffset)`（`:214`）把数据**直接 pread 进堆外对齐内存**，绕开 OS page cache。好处：① 大块 entry log 顺序读**不再污染 page cache**，让 BK 自己的 `ReadCache` 成为唯一读缓存层，命中率与回收完全可控；② 减少一次「内核页缓存 → 用户 buffer」的拷贝，对大 entry 友好。代价是 O_DIRECT 要求 offset/count/buffer 全部按 block 对齐（代码注释明确 `offsets and counts must be aligned`），且 `readBufferAt` → `nativeBuffer.readByteBuf(buf, ...)`（`:160`）这一步仍要把数据从 native 对齐 buffer 拷到 Netty `ByteBuf`，所以**并非完全零拷贝到用户 buffer**，而是「绕 page cache + 减一次内核拷贝」。

```java
// DirectReader.java:165-191（节选）—— 先读 size 字段，再读整条
int entrySize = readIntAt(offset - Integer.BYTES);   // 读 4 字节 entrySize（pos-4）
if (entrySize == 0) { clearCache(); entrySize = readIntAt(offset - 4); } // 处理预分配空洞
return readBufferAt(offset, entrySize);              // → readBytesIntoBuf → readBlock → nativeIO.pread(O_DIRECT)
```

> [!TIP]
> **多 ledger 交错的硬约束 —— 读后必校验 ledgerId/entryId**：因为 entry log 是「多 ledger 交错」的，location 只是索引给的绝对位点，一旦索引写错就可能指向别的 ledger 的 entry。两种实现读后都校验：`DefaultEntryLogger.validateEntry`（`:826-831`）读 `sizeBuff.getLong(4)/getLong(12)` 比对 `ledgerId/entryId`，不符抛 `WrongEntryException`；`DirectEntryLogger`（`:256-266`）读 `buf.getLong(0)/getLong(8)` 比对，不符抛 `IOException`。这正对应落盘格式 V1 的 `ledgerId(8)+entryId(8)` 头 —— 读路径与写路径（文件格式）在这里闭环。

> [!WARNING]
> 不要以为 `DirectEntryLogger` 一定比 `DefaultEntryLogger` 快。direct I/O 绕开 page cache 意味着**冷读没有缓存兜底**、且对齐读对小 entry 反而有额外开销；它主要价值在「隔离大 entry log 读与 page cache、稳定 ReadCache 命中率」。是否开启看 workload（大 entry / 读多写少且想保护 page cache 时开 `useDirectEntryLogger`），且要求运行平台 `NativeIO.isAvailable()`（Linux 通常满足，否则自动回退到 `DefaultEntryLogger`）。

#### EntryLogger: Bytes → Location（写路径与 flush 时序）

> [!NOTE]
> 写路径是分三层的：**① Bookie/Journal（WAL，持久性 + ack 关口）→ ② DbLedgerStorage 双缓冲 WriteCache（内存）→ ③ EntryLogger（entry log 文件）**。EntryLogger 自身**不立即 fsync**——它只是把字节写入文件缓冲，真正的 fsync 由上层 flush 触发。源码取自本地 `E:/Projects/bookkeeper`（master，末提交 `Generate 4.18.2 release note`，与 4.18.1 基线一致）。

**层 ①：Bookie 入口与 Journal（WAL）**。`BookieImpl.addEntry`（`:1112`）→ `addEntryInternal`（`:980`）→ `getJournal(ledgerId).logAddEntry(entry, ackBeforeSync, cb, ctx)`（`:1015`）。注意 **client 的 `WriteCallback cb` 直接传给 Journal**：Journal 内部走 group commit（按时间/字节攒批 fsync，默认 2ms / 512KB），fsync 完成后（或 `ackBeforeSync=true` 时 fsync 前）才回调 `cb.writeComplete` 给 client。**即 client 的 ack 由 Journal 的 fsync 决定，而非 entry log**。Journal fsync 完成后的回调里，entry 才被异步交给 LedgerStorage 放入内存 WriteCache——这就是「Journal 是前 log、entry log 是后 log」的根源。

**层 ②：DbLedgerStorage 双缓冲 WriteCache（内存）**：

```java
// SingleDirectoryDbLedgerStorage.java:469-507（节选）—— addEntry 只放内存
long ledgerId = entry.getLong(entry.readerIndex());        // 解析 entry 头
long entryId  = entry.getLong(entry.readerIndex() + 8);
long stamp = writeCacheRotationLock.tryOptimisticRead();   // 乐观读锁（writeCache 每分钟才 swap 一次，几乎无竞争）
if (stamp != 0) inserted = writeCache.put(ledgerId, entryId, entry);  // 放入 writeCache，不写磁盘
if (!inserted) triggerFlushAndAddEntry(ledgerId, entryId, entry);     // 满了就先 flush 再插
```

`flush`（`:910`）的核心是 **双缓冲 swap**：`swapWriteCache`（`:891`）用写锁把 `writeCache` ↔ `writeCacheBeingFlushed` 交换（`:896-898`），于是**前台写入继续落到新的 `writeCache`，后台把旧的 `writeCacheBeingFlushed` 刷盘**，两者交替：

```java
// SingleDirectoryDbLedgerStorage.java:814-850（节选）
swapWriteCache();  // writeCache ⇄ writeCacheBeingFlushed
try (Batch batch = entryLocationIndex.newBatch()) {
    writeCacheBeingFlushed.forEach((ledgerId, entryId, entry) -> {
        long location = entryLogger.addEntry(ledgerId, entry);          // ③ 写入 entry log 文件缓冲
        entryLocationIndex.addLocation(batch, ledgerId, entryId, location); // 同时记 RocksDB 索引
    });
    entryLogger.flush();                 // ③ fsync entry log
    batch.flush();                       // fsync RocksDB 索引
    ledgerIndex.flush();
}
writeCacheBeingFlushed.clear();          // 已持久化，丢弃该缓冲
```

> [!TIP]
> **双缓冲 swap 的无锁设计**：`writeCache` 平时由 `tryOptimisticRead` 乐观读锁保护，因为 `swapWriteCache` 每分钟才发生一次（`:483` 注释），绝大多数写线程零竞争；只有 swap 瞬间才升级为写锁。这与 Journal 的 group commit、「WriteCache 满/定时触发 flush」共同构成 BK 的高吞吐写路径。

**层 ③a：DefaultEntryLogger（默认，FileChannel）**。`addEntry`（`:616`）→ `entryLogManager.addEntry`（`:617`）→ `EntryLogManagerBase.addEntry`（`:70-80`）—— 写 `size(4)` + `entry`（内容含 `ledgerId/entryId/LAC/...`），`pos = logChannel.position()` 记录 entry 内容起始（读时回退 4 字节取 size，与读路径闭环），返回 `(logId<<32)|pos`。数据先写进 **`BufferedLogChannel`（`BufferedChannel` 子类，`:88`）的内存缓冲**，满了才 flush 到 `FileChannel`（**不 fsync**）。`flush`（`:603`）→ `entryLogManager.flush()` → 对 active/rotated channel 调 `flushAndForceWrite(force)`（`:191/651`）即「缓冲落盘 + **fsync**」。active log 切换（`getCurrentLogForLedgerForAddEntry`, `:91-115`）在达到 `entryLogSizeLimit`（默认 2GB）或磁盘满时触发：先 `flushAndForceWriteIfRegularFlush(false)` 刷旧 log，再 `createNewLog` 切新文件（旧 channel 转入 `rotatedLogChannels`，`flushRotatedLogs` 负责 fsync + close）。

**层 ③b：DirectEntryLogger（direct I/O）**。`addEntry`（`:182-205`，synchronized）：若 `curWriter.shouldRoll`（按 maxFileSize）则 `flushAndCloseCurrent`（异步 flush + close 旧 log）；否则若 `curWriter==null` 则新建 `DirectWriter`（`:195`，`newDirectWriter` 打开 `O_CREAT|O_WRONLY|O_DIRECT` fd + `fallocate` 预分配空洞，`:456-97`）。`DirectWriter.writeDelimited`（`:164-183`）把 `size(4)+entry` 攒进 **`nativeBuffer`（direct I/O 对齐堆外 buffer）**，满了（`hasSpace` 假）才 `flushBuffer`（`:290-316`）提交给 `writeExecutor` 单线程**异步 `pwrite`** 并 acquire 新 buffer。`flush`（`:279-305`）→ `flushCurrent`（`:307`）提交 `flushWriter.flush()` 到 `flushExecutor` 单线程：`DirectWriter.flush`（`:209-222`）= `flushBuffer`（提交残余）+ `waitForOutstandingWrites`（等所有异步 pwrite 完成）+ `nativeIO.fsync(fd)`。两个 executor（`entryLoggerWriteExecutor` / `entryLoggerFlushExecutor`，在 `DbLedgerStorage.java:217/219` 创建）分别承载「异步累积写」与「fsync」。

**两条写实现对比**：

| 维度 | DefaultEntryLogger（默认） | DirectEntryLogger（direct I/O） |
| -- | -- | -- |
| 落盘缓冲 | `BufferedLogChannel`（BufferedChannel 内存缓冲） | `nativeBuffer`（O_DIRECT 对齐堆外 buffer） |
| 实际写盘 | `BufferedChannel` 满→写 FileChannel | `writeExecutor` 单线程异步 `pwrite` |
| fsync 时机 | `flush` → `flushAndForceWrite` | `flush` → `flushExecutor` → `nativeIO.fsync(fd)` |
| 文件切换 | `reachEntryLogLimit` / 磁盘满 → `createNewLog` | `shouldRoll`（maxFileSize）→ `flushAndCloseCurrent` |
| 预分配 | 普通创建 | `fallocate(FALLOC_FL_ZERO_RANGE)`（避免 O_DIRECT 空洞读） |

**与 Journal 协同（前 log / 后 log）**：

1. **Journal 决定 ack**：client addEntry 先落 Journal（group commit fsync），ack 由 Journal fsync 决定；LedgerStorage 收到后才放 WriteCache，后台 flush 才写 entry log。
2. **entry log 不需要独立保证 ack 的 fsync**：Journal 已保证持久性，entry log 的 fsync 由 checkpoint/WriteCache 满驱动（定期或定量）；即便 entry log 还没 fsync 就崩溃，重启时 **Journal replay** 会重新把 entry 补齐到 entry log（这正是 Journal 作为 WAL 的价值）。
3. **两层都靠「攒批 + 定时 fsync」的 group commit**：Journal（2ms / 512KB）与 EntryLogger（WriteCache 满 / 定时 swap 后 flush）是 BK 高吞吐写的核心——前者保持久性，后者把「多 ledger 交错」的 entry 顺序追加入 entry log 文件。

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

### Journal: Group Commit (Source-level)

Journal 采用**两段式 group commit**：主线程（`Journal.run`，写线程）只负责把 entry 攒进 `BufferedChannel` 内存缓冲；独立的 `ForceWriteThread` 才负责 `fsync` 并触发 client 回调（ack）。落盘与 ack 解耦，是高吞吐写的根因。

**① `logAddEntry`（`:931`）：极轻量，不入盘、不 fsync**

```java
entry.retain();
memoryLimitController.reserveMemory(entry.readableBytes());
queue.put(QueueEntry.create(entry, ackBeforeSync, ledgerId, entryId, cb, ctx, ...));
```

仅 `retain` + 内存记账 + 把 `QueueEntry`（含 client 的 `WriteCallback cb`）推入 `queue`（`BlockingMpscQueue` 或 `BatchedArrayBlockingQueue`，由 `journalQueueSize` 决定）即返回。client 的回调不在这一步触发。

**② 主线程 `run`（`:989`）：攒批写 Buffer，判 flush**

- `queue.takeAll/pollAll`（`:1066/1076`）批量取 entry；
- 对每条：`lenBuff.writeInt(entrySize)` + `bc.write(lenBuff, entry)`（`:1232-1238`）写入 `BufferedChannel`（Netty `ByteBuf` 内存缓冲，**只进内存、不落盘**）；
- 判 `shouldFlush`（`:1089-1122`），三触发条件：

| 条件 | 判据 | 默认 |
| :-- | :-- | :-- |
| ① 超时 | 最老 pending entry 等待 > `maxGroupWaitInNanos` | **2ms** |
| ② 字节 / 条数 | `bc.position() - lastFlushPosition > bufferedWritesThreshold` 或 `toFlush.size() > bufferedEntriesThreshold` | **512KB** / 0(禁用) |
| ③ 队列空 | `qe == null && flushWhenQueueEmpty` | 测试场景 |

- `shouldFlush` 时：`bc.flush()`（`:1130`，**仅把缓冲 write 进 OS page cache，不是 fsync**）；对 `ackBeforeSync` 的 entry 立即 `entry.run()`（`:1141`）提前 ack；
- 构造 `ForceWriteRequest`（`:1184`）推入 `forceWriteRequests` 队列，主线程继续循环。

**③ `ForceWriteThread`（`:489`）：fsync + 触发持久性 ack**

```java
int requestsCount = forceWriteRequests.takeAll(localRequests);   // 取一批
syncJournal(lastRequest);                                        // :513
// → lastRequest.flushFileToDisk() :548
//   → JournalChannel.forceWrite() :310
//     → BufferedChannel.forceWrite()  // 真正的 FileChannel.force，fsync 到磁盘
for (int i = 0; i < requestsCount; i++) {
    req.process(writeHandlers);                                  // :519 触发 client WriteCallback
}
```

> [!TIP]
> 两层 flush 语义不同：`bc.flush()`（主线程）只把 Netty `ByteBuf` 缓冲 `write` 进 OS page cache；`bc.forceWrite()`（ForceWriteThread）才是 `fsync`。**普通写入的 ack 在 forceWrite 之后才发**；只有 `ackBeforeSync=true`（对应 `journalSyncData` 关闭或显式配置）才会提前到 buffer flush 就 ack——这是吞吐与持久性的取舍开关。

> [!WARNING]
> 与 LedgerStorage 的先后：`BookieImpl.addEntryInternal` 里 Journal 是「先写 WAL、后写 LedgerStorage」——client 的 `cb` 直接传给 `journal.logAddEntry`（见 [Write](/docs/CS/Framework/BookKeeper/Write.md)）。LedgerStorage（WriteCache / entry log）是在 journal 之后才异步落盘的，因此**崩溃时靠 Journal replay 把 entry 补齐到 entry log**，这正是 Journal 作为 WAL 的价值。

### Journal: File Format & Replay

**文件格式（`JournalChannel`）**

- 文件头：`HEADER_SIZE = SECTOR_SIZE = 512` 按扇区对齐；V4 用 `VERSION_HEADER_SIZE = 8`（4B magic + 4B version），其它版本用 512B。当前 `CURRENT_JOURNAL_FORMAT_VERSION = V6`（`:75`），最小兼容 V1。
- 每条 record：`Length(4) + Entry`（`:1232-1238`），**无独立 magic 前缀**，靠长度定界；V5+ 在 forceWrite 前写 `PADDING_MASK(-256)` 做 512B 对齐（`:1126` / `writePaddingBytes`）。
- `preAllocIfNeeded`（`:288`）按 `journalPreAllocSize` 预分配（写 zeros 占位，减小碎片）。

**Replay（崩溃恢复，`scanJournal` `:844`）**

从 `lastLogMark`（上次成功 fsync 位点）起，循环 `fullRead` 读 4B length：

- `len == 0`：正常 EOF，停止；
- `len < 0 && == PADDING_MASK && version >= V5`：跳过 padding，读下一个 int 才是真实 len（`:874-886`）；
- `len > 0`：读 len 字节，调 `scanner.process(version, offset, recBuff)`（`:904`）由 `LedgerStorage` 作为 `JournalScanner` 重新应用（把 entry 重新写入 entry log + 更新 RocksDB 索引）；
- 读不足 len 字节：说明是上次崩溃时写到一半的尾巴，`break`（`:897-900`）——**这就是崩溃点**，其后的 journal 不再信任。

replay 把 WAL 里尚未刷到 entry log 的 entry 补齐，保证 ledger 内容不丢；replay 完成后该 journal 文件由 `SyncThread` 标记、按 `journalMaxBackups` 滚动清理。

### Journal: SyncThread — Checkpoint & Journal GC

`SyncThread` 是 journal 的「善后」线程。名字虽叫 sync，但**它不做 fsync**（fsync 在 `ForceWriteThread`）——它只负责两件事：① 推进 `LedgerStorage` 的 checkpoint（对 `DbLedgerStorage` 即 RocksDB checkpoint，把 memtable 落盘）② 在 checkpoint 完成后按 `journalMaxBackups` **GC 已无用的 journal 文件**。

**角色与触发（`SyncThread.java`）**

- 实现 `Checkpointer`，持有 `LedgerStorage` 与 `CheckpointSource`（即 `Journal`；`BookieImpl.java:452` 把多个 journal 包成 `CheckpointSourceList`）；
- 单线程 `ScheduledExecutorService`（`newExecutor`，:88），所有 checkpoint 串行化；
- 触发点：`InterleavedLedgerStorage.onRotateEntryLog`（:568-577）在 **entry log 文件滚动时**调 `checkpointer.startCheckpoint(checkpoint)`——语义是「此点之前所有 entry 已落 ledger storage，可 checkpoint」；`BookieImpl.replayJournal` 之后 `syncThread.requestFlush().get()`（:698）做一次启动期 flush。

**两路 checkpoint（`compact` 参数决定删不删 journal）**

| 路径 | 触发 | LedgerStorage 动作 | compact | 删 journal 文件 |
| :-- | :-- | :-- | :-- | :-- |
| `requestFlush` → `flush`（:128/141） | 启动 / replay 后 | `ledgerStorage.flush()`（:144） | **false** | 否（只持久化 mark） |
| `startCheckpoint` → `checkpoint`（:98/168） | entry log rotate | `ledgerStorage.checkpoint(checkpoint)`（:175，对 DbLedgerStorage 触发 RocksDB checkpoint） | **true** | 是 |

`checkpoint`（:175）→ `ledgerStorage.checkpoint`（`DbLedgerStorage.java:390` 遍历分片）→ `SingleDirectoryDbLedgerStorage.checkpoint` 对 RocksDB 创建 checkpoint（flush memtable 到 SST + 硬链接）。至此该 checkpoint 之前的所有 entry 已落盘到 entry log + RocksDB，journal 中对应内容即可安全丢弃。

**Journal 文件 GC（`Journal.checkpointComplete` :786）—— 真正的删除逻辑**

```java
synchronized (checkpointLock) {                    // :794  #4105 原子化：单调决策 + 持久化
    if (mark.getCurMark().compare(lastPersistedMark) < 0) return;  // :795  lastLogMark 只前进
    persistLastLogMark(mark);                       // :798 → LastLogMark.rollLog 写磁盘 marker
    lastPersistedMark.setLogMark(...);              // :799
}
if (compact) {                                      // 仅 compact=true 才 GC
    List<Long> logs = listJournalIds(journalDirectory, new JournalRollingFilter(mark)); // :805  accept id < markedId
    if (logs.size() >= maxBackupJournals) {         // :807  maxBackupJournals = journalMaxBackups, 默认 5
        int maxIdx = logs.size() - maxBackupJournals;
        for (int i = 0; i < maxIdx; i++) {
            long id = logs.get(i);
            if (id < mark.getCurMark().getLogFileId()) {        // :812  确保早于标记点
                new File(journalDirectory, Long.toHexString(id) + ".txn").delete(); // :813-814
            }
        }
    }
}
```

> [!TIP]
> 为什么 journal 不会无限增长：每滚动一个 entry log 就触发一次 checkpoint，checkpoint 把数据推进到 entry log + RocksDB 后，旧 journal（早于 `lastLogMark` 且超过 `journalMaxBackups` 备份数）被物理删除。保留 `journalMaxBackups`（默认 5）个是为了「极端灾难可手工回放」。journal 文件格式见上节 `### Journal: File Format & Replay`。

> [!WARNING]
> 注意 `compact` 语义：`requestFlush`（启动 / replay 后）只持久化 `lastLogMark` **不删文件**；真正删 journal 文件只在 entry log rotate 触发的 `startCheckpoint`（compact=true）路径。所以 journal 文件数主要由 `journalMaxBackups`（默认 5）兜住，而非每次写都删。

**LastLogMark 与崩溃恢复**

`lastLogMark` 是 `(logFileId, logFileOffset)` 的持久化标记（存磁盘 marker 文件，重启时 `readLog()` 加载，:711；`ForceWriteThread.syncJournal` 每次 fsync 后 `setCurLogMark`，:551）。它定义「已安全持久化到 ledger storage 的 journal 位点」：recovery 时 `scanJournal` 从 `lastLogMark` 之后回放（见上节），而 id < `lastLogMark` 的 journal 文件在 checkpoints 中已被 GC——两者保证「replay 不会重放已落盘数据、也不会漏放未落盘数据」。

## EntryLog

- 多个 ledger 的 entry **交错写入同一个 entry log 文件**，靠 index 定位。
- 文件达到 `logSizeLimit` 就滚动新建。默认 **1 GiB**（`ServerConfiguration.java:85-91`：默认值取 `BookKeeperConstants.MAX_LOG_SIZE_LIMIT`，其定义为 `1 * 1024 * 1024 * 1024`，即 1 GiB）。

> [!NOTE]
> 「entry log 默认 2 GB」是流传很广的错误说法。4.18.1 的上限常量是 **1 GiB**（`BookKeeperConstants.java` `MAX_LOG_SIZE_LIMIT = 1 * 1024 * 1024 * 1024`），而 `logSizeLimit` 的默认值就等于这个上限。

- `entryLogPerLedgerEnabled` 默认 **false**（`ServerConfiguration.java:3981`）。打开后每个 ledger 单独一个 entry log，利于删除但会产生大量文件（有 `entryLogPerLedgerCounterLimitsMultFactor` 兜底，默认 10，`:4054`）。

### File Format

entry log 是一个**逻辑顺序文件**（多 ledger 交错），物理布局分两段：

- **文件头（1024 字节，`LOGFILE_HEADER_SIZE`）**：当前只用前 20 字节 —— 4 字节 fingerprint `BKLO`、4 字节版本号（`HEADER_V0` / `HEADER_V1`）、8 字节 `ledgersMapOffset`、4 字节 `ledgersMap` 长度。Header 之后才是真正的数据区。
- **数据区**：每条 entry 以「4 字节 `entrySize` + 8 字节 `ledgerId` + entry 内容」连续排列。`entrySize` 包含自身之后的全部字节（即 `8 + entry内容长度`），GC 扫描时先读 `entrySize` 与 `ledgerId`，再按 `entrySize` 跳过整条，从而把存活 ledger 的 entry 搬迁到新文件。

> [!NOTE]
> entry 在文件里的「内容」部分**不是** client 与 bookie 之间的网络协议，而是 bookie 落盘格式：V1 为 `ledgerId(8) + entryId(8) + LAC(8) + length(8) + digest + payload`，V2 在头部多了 1 字节 metadata flags（支持 128-bit ledger id 等扩展）。网络协议由 `BookieProtocol` 单独定义。

> [!TIP]
> 因为 header 预留 1024 字节而只用 20 字节，且数据区「size + ledgerId」自描述，entry log 可以**不依赖外部索引独立扫描** —— 这正是 GC 线程 `extractMetaFromEntryLogs()` 能离线重建「entryLog → 含哪些 ledger」映射、bookie 崩溃后仅靠 entry log + journal 即可恢复的基础。

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

## Comparison With Other Storage Engines

把「存储引擎实现」这一层单独拉出来对比，才能看清 BookKeeper 与 Kafka / RocketMQ / RabbitMQ / Pulsar 的本质差异。下列结论均出自各系统的源码级笔记（见 Links 与正文引用）：

| 维度 | BookKeeper 4.18.1 | Kafka 4.3.1 | RocketMQ 5.5.1 | RabbitMQ quorum 4.3 | Pulsar（managed-ledger） |
| -- | -- | -- | -- | -- | -- |
| 存储抽象 | ledger（不可变段） | partition（分段日志） | broker（CommitLog + 索引） | 每队列 Raft 日志 | **无存储引擎**，存储外包给 BookKeeper |
| WAL / 持久性 | Journal（独立 WAL） | 无独立 WAL，靠副本 + page cache | CommitLog 即 WAL（单文件） | Raft WAL（每节点共享，默认 512 MiB flush） | 复用 BookKeeper Journal |
| 数据文件组织 | 多 ledger 交错写同一 entry log | 每分区独立 `.log` 分段（1 GiB） | 全 topic 共用单 CommitLog（1 GiB） | 每队列 segment + snapshot | —（落 BK entry log） |
| 索引结构 | RocksDB（Db）/ 页缓存（Sorted） | 稀疏索引 `.index` mmap 二分 | ConsumeQueue 20B 定长 + IndexFile 链表 | 内存索引（≥32B/消息） | RangeCache 跳表（broker 侧缓存） |
| 刷盘策略 | Journal group commit（2ms / 512KB fsync） | 默认不主动刷（page cache） | 异步 500ms 攒 4 页 / 同步 group commit | 每条 fsync（publisher confirm） | 复用 BK |
| 读路径 | WriteCache→ReadCache→索引→entry log + speculative | sendfile 零拷贝 + page cache | mmap + ConsumeQueue 跳转 | 内存索引 → segment | 跳表缓存 → BK 读 |
| 空间回收 | minor/major GC（搬迁存活 entry） | log cleaner（key 去重） | 按时间/磁盘水位删过期文件 | Raft log compaction（minor/major） | ledger 整段删 + BK GC |
| 一致性边界 | ledger close / recovery | HW（高水位） | CommitLog 刷盘位点 | Raft committed index | BK LAC |
| 扩容模型 | 加 bookie，旧数据不搬迁 | 加分区需重平衡 | 加 broker + 队列 | 加节点需 Raft 全量 resync | 加 bookie（同 BK） |

### Why The Models Differ

最值得记住的三条：

1. **BookKeeper 是唯一「WAL 与数据分离、且多 ledger 交错」的**。Journal 只管顺序写 + fsync（持久性），entry log 管数据、可与 Journal 分盘，读写 IO 天然隔离；而 Kafka / RocketMQ 的「数据文件」本身就承担持久性（无独立 WAL）。
2. **BookKeeper 的扩容不搬迁历史数据**。新 bookie 只影响新建 ledger，旧 ledger 副本由 auto-recovery 异步补齐；Kafka 加分区要重平衡、RabbitMQ quorum 加节点要 Raft 全量 snapshot + log resync。
3. **Pulsar 是「无存储引擎」的极端**：它把 WAL、数据、索引全部外包给 BookKeeper，自己只做 managed-ledger 的 ledger 切换、cursor 位点、缓存与 compaction —— 这正是「存算分离」在存储引擎层的彻底体现，也是它比 Kafka / RocketMQ 更容易做存储独立扩缩容的根源（对比见 [MQ](/docs/CS/MQ/MQ.md)）。

> [!WARNING]
> 不要把这表当成「谁更好」的排名。BookKeeper 的「多 ledger 交错 + GC 搬迁」带来读放大与 GC 复杂度；Kafka 的「每分区独立文件 + sendfile」顺序读吞吐极高但扩容要重平衡；RabbitMQ quorum 的「每条 fsync + Raft」最稳但吞吐受限于单队列 Raft leader；RocketMQ 的「单 CommitLog」简单但删除只能按文件粒度。选型看工作负载，详见 [Kafka Storage](/docs/CS/MQ/Kafka/Storage.md)、[RocketMQ Store](/docs/CS/MQ/RocketMQ/Store.md)、[RabbitMQ](/docs/CS/MQ/RabbitMQ.md)、[Dledger](/docs/CS/MQ/RocketMQ/Dledger.md)。

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
