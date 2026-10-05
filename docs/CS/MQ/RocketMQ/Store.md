## Introduction

RocketMQ 的存储引擎（`store` 模块）是它区别于 Kafka 的核心设计：所有 Topic 的消息都顺序追加写入同一个 `CommitLog` 物理文件，再由 `ReputMessageService` 异步派发到各 Topic 的 `ConsumeQueue` 逻辑队列与 `IndexFile` 时间索引。

> 版本基线：**5.5.1**（tag `rocketmq-all-5.5.1`，2026-08-20 发布，为当前最新 release）。
> 注意 `master` 分支的 `pom.xml` 里 `<version>` 是 **5.3.3**，不是 5.5.x —— 引用 master 结论时要注明。

```tex
Producer ──▶ ┌─────────────────────────────────────────┐
             │  CommitLog（1G，所有 Topic 共享，顺序写） │  ← 单一真相来源
             └─────────────────────────────────────────┘
                            │ 异步 dispatch（ReputMessageService）
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
        ConsumeQueue₁   ConsumeQueue₂   IndexFile（按 Key/Tag 建 Hash 索引）
        （Topic-A 队列） （Topic-B 队列）   （按时间 + Key 检索）
```

这种「一写多读」的结构是 RocketMQ 高吞吐的来源，也是它所有痛点的来源（无法按消息删除、磁盘稀疏、恢复复杂）。

## 5.5.1 的包路径重构（踩坑预警）

5.5.1 对 `store` 模块做过一次大规模包重构，**网上绝大多数资料给的是 4.x 路径，照着找不到文件**：

| 4.x / 旧资料路径 | 5.5.1 实际路径 |
| ----------------- | -------------- |
| `store/MappedFile.java` | `store/logfile/MappedFile.java`（**已改为 interface**）<br>`store/logfile/DefaultMappedFile.java`（**实现类，1122 行**）<br>`store/logfile/AbstractMappedFile.java`（空壳） |
| `store/IndexFile.java` | `store/index/IndexFile.java` |
| `store/IndexService.java` | `store/index/IndexService.java` |
| `store/MessageStoreConfig.java` | `store/config/MessageStoreConfig.java` |
| `store/SelectMappedBuffer.java` | **类已删除**，仅剩 `SelectMappedBufferResult.java` |
| `store/GroupCommitService.java` | **文件已删除**，成为 `CommitLog` 内部类 |
| `store/FlushCommitLogService.java` | **文件已删除**，成为 `CommitLog` 抽象内部类 |
| `store/CleanCommitLogService.java` | **文件已删除**，逻辑并入 `DefaultMessageStore` 内部类 |

刷盘三兄弟现在的继承链（均在 `CommitLog.java` 内）：

```java
ServiceThread
  └─ FlushCommitLogService（abstract，只有一个常量 RETRY_TIMES_OVER = 10）
       ├─ GroupCommitService     // 同步刷盘（flushDiskType = SYNC_FLUSH）
       ├─ FlushRealTimeService   // 异步刷盘（flushDiskType = ASYNC_FLUSH）
       └─ CommitRealTimeService  // commit 阶段（仅 transientStorePool 开启时有内容）
```

> [!WARNING]
> 常见误解：「`FlushCommitLogService` 是异步刷盘类」——错。它是**抽象基类**，异步用的是子类 `FlushRealTimeService`。

## 三类文件的物理结构

### CommitLog

默认文件大小 **1 GB**，来自 `MessageStoreConfig.java:52`：

```java
// CommitLog file size,default is 1G
private int mappedFileSizeCommitLog = 1024 * 1024 * 1024;
```

> [!TIP]
> 5.5.1 中这个值**原样**传给 `MappedFileQueue`，**不再有** 4.x 时代 `mappedFileSize - END_FILE_MIN_BLANK_LENGTH` 这样的扣减。文件就是 1 GB。

消息编码已从 `CommitLog` 抽到独立类 `MessageExtEncoder`，`calMsgLength()` 给出权威布局（`MessageExtEncoder.java:66-82`）：

| 序号 | 字段 | 字节 | 备注 |
| --- | ---- | ---- | ---- |
| 1 | TOTALSIZE | 4 | 整条消息长度 |
| 2 | MAGICCODE | 4 | 由 `MessageVersion` 决定 |
| 3 | BODYCRC | 4 | |
| 4 | QUEUEID | 4 | |
| 5 | FLAG | 4 | |
| 6 | QUEUEOFFSET | 8 | `doAppend` 中回填 |
| 7 | PHYSICALOFFSET | 8 | `doAppend` 中回填 |
| 8 | SYSFLAG | 4 | 事务标记等 |
| 9 | BORNTIMESTAMP | 8 | |
| 10 | BORNDHOST | **8 或 20** | IPv6 走 20（`BORNHOST_V6_FLAG`）|
| 11 | STORETIMESTAMP | 8 | `doAppend` 中刷新 |
| 12 | STOREHOSTADDRESS | **8 或 20** | 同上 |
| 13 | RECONSUMETIMES | 4 | |
| 14 | Prepared Transaction Offset | 8 | |
| 15 | BODY | 4 + bodyLength | 4 字节长度前缀 |
| 16 | TOPIC | **1 或 2** + topicLength | 宽度随 `MessageVersion` 变 |
| 17 | propertiesLength | **2** + propertiesLength | ⚠️ 是 **short（2 字节）**，不是 4 字节 |

两个易错点：

- **TOPIC 长度字段宽度不固定**。`common/.../message/MessageVersion.java`：`MESSAGE_VERSION_V1` → `getTopicLengthSize()` 返回 1；`MESSAGE_VERSION_V2` 返回 2。`CommitLog.java:1016-1022` 会在 topic 名超过 `Byte.MAX_VALUE`（127）时自动切 V2：

  ```java
  msg.setVersion(MessageVersion.MESSAGE_VERSION_V1);
  if (autoMessageVersionOnTopicLen && topic.length() > Byte.MAX_VALUE) {
      msg.setVersion(MessageVersion.MESSAGE_VERSION_V2);
  }
  ```
  默认 topic 名（`%RETRY%group`、`SCHEDULE_TOPIC_XXXX`）都远小于 127，所以实际生产中绝大多数消息是 V1（省 1 字节）。
- **PROPERTIES 长度前缀是 2 字节**。这是从 4.x 迁移时最容易写错的地方。

**已删除的字段**：`BLANK_LEN`、`msgBeginTimeMax`、`msgBeginTimeMin`、`storeTimestampBaseOffset`、`msgMagicCode` 在 5.5.1 中**全部不存在**（全模块 grep 零命中）。仅存两个 magic code 常量（`CommitLog.java:79-82`）：

```java
public final static int MESSAGE_MAGIC_CODE = -626843481;   // daa320a7
public final static int BLANK_MAGIC_CODE   = -875286124;   // cbd43194
public static final int CRC32_RESERVED_LEN = 19;           // "CRC32" + 1 + 10 + 1
```

#### 文件末尾的 blank 保护

`maxBlank` 是 `doAppend()` 的**方法参数**而非类字段。边界保护逻辑（`CommitLog.java:2054-2067`）：

```java
if ((msgLen + END_FILE_MIN_BLANK_LENGTH) > maxBlank) {
    this.msgStoreItemMemory.clear();
    this.msgStoreItemMemory.putInt(maxBlank);                  // TOTALSIZE
    this.msgStoreItemMemory.putInt(CommitLog.BLANK_MAGIC_CODE); // MAGICCODE
    byteBuffer.put(this.msgStoreItemMemory.array(), 0, 8);     // 实际只写 8 字节
    return new AppendMessageResult(AppendMessageStatus.END_OF_FILE, wroteOffset,
        maxBlank,  // ← 却声明写了 maxBlank 字节
        ...);
}
```

设计要点：**物理只写 8 字节**（`4 + 4`，即 `END_FILE_MIN_BLANK_LENGTH`），但**声明写了 `maxBlank` 字节**，让 `MappedFileQueue` 的 wrotePosition 直接跳到文件末尾，下一条消息落到新文件。这样既保证消息不跨文件边界，又不用真的把剩余空间写满。

### ConsumeQueue

逻辑队列的存储单元，**20 字节**（`ConsumeQueue.java:64-65`）：

```java
public static final int CQ_STORE_UNIT_SIZE = 20;
public static final int MSG_TAG_OFFSET_INDEX = 12;
```

```
┌───────────────────────────────┬───────────────────┬───────────────────────────────┐
│    CommitLog Physical Offset  │      Body Size    │            Tag HashCode       │
│          (8 Bytes)            │      (4 Bytes)    │             (8 Bytes)         │
├───────────────────────────────┴───────────────────┴───────────────────────────────┤
│                                    Store Unit                                   │
└────────────────────────────────────────────────────────────────────────────────┘
```

文件大小：`mappedFileSizeConsumeQueue = 300000 * CQ_STORE_UNIT_SIZE` = **6,000,000 字节 ≈ 5.72 MiB**（注意是 5.72 MiB，不是 6 MB）。即每个 ConsumeQueue 文件恰好容纳 **30 万个队列单元**。

> [!TIP]
> 5.5.1 中 `commitLogMinOffset`、`whereMinOffset`、`whereMaxOffset` 这三个 4.x 字段**已不存在**（grep 零命中），被 `ConsumeQueueStore` 抽象层取代。现存字段只有 `minLogicOffset` 与 `maxPhysicOffset`。消费进度用 `mappedFileQueue.getMaxOffset() / CQ_STORE_UNIT_SIZE` 换算。

写失败会重试：`putMessagePositionInfoWrapper` 最多重试 **30 次**，每次 `Thread.sleep(1000)`，全失败则 `runningFlags.makeLogicsQueueError()`（`ConsumeQueue.java:725-771`）。另有幂等保护：若 `offset + size <= getMaxPhysicOffset()` 直接返回 true，避免恢复期重复构建。

写入方式由 `putConsumeQueueDataByFileChannel`（默认 **true**）决定走 `FileChannel.write()` 还是 mmap 写（`ConsumeQueue.java:891-909`）。

### IndexFile

按 Key / Tag 建立的 Hash 索引，布局（`index/IndexHeader.java:37-38`、`index/IndexFile.java:31,46-47`）：

```
┌──────────────────────────────────────────────────────────┐
│  Header（40 字节）                                         │
│  BeginTimestamp(8) EndTimestamp(8)                        │
│  BeginPhysicalOffset(8) EndPhysicalOffset(8)              │
│  HashSlotCount(4) IndexCount(4)                           │
├──────────────────────────────────────────────────────────┤
│  Slot 区：hashSlotNum × 4 字节（默认 500 万 × 4 = 20 MB）  │
├──────────────────────────────────────────────────────────┤
│  Index 区：indexNum × 20 字节（默认 2000 万 × 20 = 400 MB）│
│  KeyHashCode(4) PhysicalOffset(8) TimeDiff(4)             │
│  NextIndexPos(4)  ← 反向链表指针，指向「上一条」          │
└──────────────────────────────────────────────────────────┘
```

> [!WARNING]
> **两个字段各司其职，不要混为一谈**（`MessageStoreConfig.java:237-238`，5.5.1 与 master 一致）：
> ```java
> private int maxHashSlotNum = 5000000;      // 槽数（桶数），20 MB
> private int maxIndexNum = 5000000 * 4;     // 条目数 = 2000 万，400 MB
> ```
> 常见资料说「`maxSlotNum` 是 5000000 还是 5000000×4」——其实**两个字段都存在**。判断写满用的是**条目数**：`isWriteFull() { return indexHeader.getIndexCount() >= this.indexNum; }`

单文件总大小 = 40 + 5000000×4 + 20000000×20 = **420,000,040 字节 ≈ 400 MB**。

#### 查找是链表反向遍历，不是二分查找

> [!WARNING]
> 5.5.1 中 `getMessagePositionByTime` 与 `getMessageOffset` **均不存在**（master 同样不存在）。真实方法是 `selectPhyOffset`（`IndexFile.java:201-253`），走**槽 + 反向链表**：

```
selectPhyOffset(phyOffsets, key, maxNum, begin, end):
  keyHash = abs(key.hashCode())
  slotPos = keyHash % hashSlotNum
  slotValue = mappedByteBuffer.getInt(40 + slotPos*4)   // 读槽，得到最后写入的条目
  nextIndexToRead = slotValue
  loop:
    读 keyHashRead / phyOffsetRead / timeDiff / prevIndexRead
    timeRead = beginTimestamp + timeDiff*1000
    if keyHash == keyHashRead and begin <= timeRead <= end: 加入结果
    // 沿反向链表回退（越往前时间越小）
    if prevIndexRead 无效 or timeRead < begin: break
    nextIndexToRead = prevIndexRead
```

**能提前退出的原因**：条目里存的是 `TimeDiff`（相对 `beginTimestamp` 的**秒数**差），沿链表回退时时间单调递减，一旦早于 `begin` 即可终止。这是「有序链表 + 提前退出」替代二分的原理。

哈希冲突用**头插法**处理（`putKey`，`IndexFile.java:113-171`）：新条目的第 4 字段填旧槽值（链头），再把槽更新为新条目下标。槽只存一条链的头，冲突多了退化为线性扫描。

## MappedFile 与 mmap

### 两条 map 分支

`DefaultMappedFile.java:199-221`：

```java
this.fileChannel = new RandomAccessFile(this.file, "rw").getChannel();
if (writeWithoutMmap) {
    // 写走 FileChannel，但仍建 MappedByteBuffer 供读
    this.mappedByteBuffer = this.fileChannel.map(MapMode.READ_ONLY, 0, fileSize);
} else {
    // 默认：读写都用 MappedByteBuffer
    this.mappedByteBuffer = this.fileChannel.map(MapMode.READ_WRITE, 0, fileSize);
}
```

`writeWithoutMmap`（`MessageStoreConfig.java:287`，默认 false）是 5.x 新增的开关。

> [!TIP]
> 5.5.1 中 `MappedFile` 接口**没有 `size()` 也没有 `getSize()`**（旧资料的 `getSize() * unitSize - 2` 公式不存在）。对应 API 是 `getFileSize()`，直接返回构造时传入的 `fileSize`，**无任何修正**。

`OS_PAGE_SIZE = 4096`（`DefaultMappedFile.java:65`），刷盘整页判定用它：

```java
// isAbleToFlush
return ((write / OS_PAGE_SIZE) - (flush / OS_PAGE_SIZE)) >= flushLeastPages;
```

### hold() / release() 引用计数

不在 `MappedFile` 里，而在父类 `ReferenceResource`（`ReferenceResource.java:26-63`）：

```java
protected final AtomicLong refCount = new AtomicLong(1);

public synchronized boolean hold() {
    if (this.isAvailable()) {
        if (this.refCount.getAndIncrement() > 0) return true;
        else this.refCount.getAndDecrement();
    }
    return false;
}

public void release() {
    long value = this.refCount.decrementAndGet();
    if (value > 0) return;
    synchronized (this) { this.cleanupOver = this.cleanup(value); }  // 归零 → unmap
}
```

`incrementBufferNum` 这个方法**不存在**（零命中），计数由 `AtomicLong refCount` 直接承载。

`selectMappedBuffer`（`DefaultMappedFile.java:667-688`）在 `hold()` 成功后 `slice()` 出新 ByteBuffer 并把 `this` 塞进 `SelectMappedBufferResult`，调用方释放时触发 `release()` —— 这是零拷贝读的安全机制，防止映射区被 unmap 后仍持有引用。

### 预分配（warm）

`warmMapedFileEnable` 默认 **false**（`MessageStoreConfig.java:266`）。开启后由 `AllocateMappedFileService` 触发 `warmMappedFile`（`DefaultMappedFile.java:797-835`）：逐 4 KB 页 `put(0)` 触碰全部页面触发**缺页预分配**（避免真实写入时才换页），SYNC_FLUSH 时按 `flushLeastPagesWhenWarmMapedFile`（默认 `1024/4*16 = 4096` 页）分批 `force()`，最后整体 `force()` 一次并 `mlock()`。**只预热，不写业务数据。**

### swap 机制存在，但配置已成死代码

> [!WARNING]
> `swapMap()` 实现还在（`DefaultMappedFile.java:839-860`）：重新 `map()` 并把老区暂存待清理，`cleanSwapedMap` 真正 unmap 且非 force 时会 sleep 到距上次 swap 满 **120 秒**（`minGapTime`），避免刚换出的页立刻换回。
>
> **但 5.5.1 中驱动它的 4 个参数全部零消费方**：

| 参数 | 默认值 | 是否被读取 |
| ---- | ------ | ---------- |
| `mappedFileSwapEnable` | `true` | ❌ 零消费 |
| `commitLogSwapMapInterval` | 1 小时 | ❌ 零消费 |
| `commitLogForceSwapMapInterval` | 12 小时 | ❌ 零消费 |
| `commitLogSwapMapReserveFileNum` | 100 | ❌ 零消费 |

搜索 `isMappedFileSwapEnable()` 等在整个仓库（排除 `MessageStoreConfig` 自身）**零命中**。`swapMap()` 与 `MappedFileQueue.cleanSwappedMap()` 也均无调用方。写笔记时不应把它描述为「启用的机制」。

## 刷盘：flush 与 commit 是两件事

这是整个 store 模块**最容易被搞混**的地方，也是本文档的核心区分：

| | flush | commit |
| - | ----- | ------ |
| 动作 | `force()` | `fileChannel.write()` |
| 效果 | mmap 脏页 **page cache → 物理磁盘** | 数据从 **writeBuffer（堆外 DirectByteBuffer）→ FileChannel（page cache）** |
| 代码 | `DefaultMappedFile.flush()` `:526-557` | `DefaultMappedFile.commit0()` `:589-601` |

```java
// flush —— 真正落盘
protected void flush0(int flushLeastPages) {
    if (writeWithoutMmap || writeBuffer != null || this.fileChannel.position() != 0) {
        this.fileChannel.force(false);     // TransientStorePool 模式：force FileChannel
    } else {
        this.mappedByteBuffer.force();     // 默认模式：force mmap 区
    }
    this.lastFlushTime = System.currentTimeMillis();
    FLUSHED_POSITION_UPDATER.set(this, value);
}
```

```java
// commit —— 只在 transientStorePoolEnable = true 时才有实际内容
protected void commit0() {
    int writePos = WROTE_POSITION_UPDATER.get(this);
    int lastCommittedPosition = COMMITTED_POSITION_UPDATER.get(this);
    if (writePos - lastCommittedPosition > 0) {
        ByteBuffer byteBuffer = writeBuffer.slice();
        byteBuffer.position(lastCommittedPosition);
        byteBuffer.limit(writePos);
        this.fileChannel.position(lastCommittedPosition);
        this.fileChannel.write(byteBuffer);   // ← 进 page cache
        COMMITTED_POSITION_UPDATER.set(this, writePos);
    }
}
```

> [!IMPORTANT]
> **默认配置下 commit 是空操作**。`commit()` 开头短路：`if (writeBuffer == null) return WROTE_POSITION_UPDATER.get(this);` —— `transientStorePoolEnable` 默认 false，没有 writeBuffer，直接把 committed 当成 wrote。
>
> 所以 `commitIntervalCommitLog`（200ms）、`commitCommitLogLeastPages`（4）、`commitCommitLogThoroughInterval`（200ms）这三个参数**在默认配置下形同虚设**，只有开了 TransientStorePool 才有意义。

### 同步 vs 异步

`CommitLog.java:2228-2233` 的选择逻辑：

```java
if (FlushDiskType.SYNC_FLUSH == config.getFlushDiskType()) {
    this.flushCommitLogService = new CommitLog.GroupCommitService();     // 同步
} else {
    this.flushCommitLogService = new CommitLog.FlushRealTimeService();   // 异步
}
this.commitRealTimeService = new CommitLog.CommitRealTimeService();
```

`GroupCommitService.doCommit()`（`:1729-1763`）对每个请求最多重试 **1000 次** `flush(0)`，每次间隔 `Thread.sleep(1)`（注释说明：TransientStorePool 开启时 writeBuffer 到 pageCache 有延迟）。全部满足 `getFlushedWhere() >= req.getNextOffset()` 才回 `PUT_OK`，否则 `FLUSH_DISK_TIMEOUT`。

### 触发条件是「或」不是「与」

默认参数（`MessageStoreConfig.java`，5.5.1 与 master 一致）：

| 参数 | 默认值 | 行号 |
| ---- | ------ | ---- |
| `flushCommitLogLeastPages` | `4` | `:215` |
| `flushCommitLogThoroughInterval` | `1000 * 10`（10s） | `:222` |
| `flushIntervalCommitLog` | `500` ms | `:151` |
| `commitIntervalCommitLog` | `200` ms | `:156` |
| `commitCommitLogLeastPages` | `4` | `:217` |
| `commitCommitLogThoroughInterval` | `200` ms | `:223` |
| `flushIntervalConsumeQueue` | `1000` | `:173` |
| `flushConsumeQueueLeastPages` | `2` | `:221` |
| `flushConsumeQueueThoroughInterval` | `1000*60` | `:224` |

实现方式很巧：**把页数阈值置 0** 来触发无条件刷（`FlushRealTimeService`，`CommitLog.java:1598-1603`）：

```java
long currentTimeMillis = System.currentTimeMillis();
if (currentTimeMillis >= (this.lastFlushTimestamp + flushPhysicQueueThoroughInterval)) {
    this.lastFlushTimestamp = currentTimeMillis;
    flushPhysicQueueLeastPages = 0;      // ← 定时器到 → 阈值归零 → 无条件刷
    printFlushProgress = (printTimes++ % 10) == 0;
}
CommitLog.this.mappedFileQueue.flush(flushPhysicQueueLeastPages);
```

即：**满 4 页** 或 **满 10 秒**，任一满足即刷。`CommitRealTimeService` 用完全相同的模式。

### 唤醒受两个开关控制

```java
// MessageStoreConfig.java:364, 366
private boolean wakeCommitWhenPutMessage = true;
private boolean wakeFlushWhenPutMessage = false;
```

异步分支（`CommitLog.java:2270-2280`）：

```java
if (!isTransientStorePoolEnable()) {
    if (config.isWakeFlushWhenPutMessage()) flushCommitLogService.wakeup();
} else {
    if (config.isWakeCommitWhenPutMessage()) commitRealTimeService.wakeup();
}
```

> [!TIP]
> 默认 `wakeFlushWhenPutMessage = false` —— 异步模式下**写完消息不主动唤醒刷盘线程**，而是等 10 秒定时器或攒够 4 页。这对吞吐有利，但意味着 Broker 崩溃时最多丢 10 秒的页缓存数据（这正是 ASYNC_FLUSH 的语义）。

## TransientStorePool 双写

`TransientStorePool`（默认 **false**，`MessageStoreConfig.java:275`）预分配 `poolSize`（默认 5）个 `ByteBuffer.allocateDirect(fileSize)`，并用 JNA `LibC.INSTANCE.mlock()` **锁内存**防换出；`borrowBuffer()` / `returnBuffer()` 池化复用；可用 buffer 低于 `poolSize * 0.4` 时告警。

创建时机（`DefaultMessageStore.java:257`）：

```java
this.transientStorePool = new TransientStorePool(
    messageStoreConfig.getTransientStorePoolSize(),
    messageStoreConfig.getMappedFileSizeCommitLog());
```

`start()` / `shutdown()` 中 `commitRealTimeService` **仅在 `isTransientStorePoolEnable()` 为真时**才启动/关闭（`:2239-2243`、`:2325-2330`）。

## CompletableFuture 化（5.x 异步重构）

`MessageStore` 接口提供 default 异步方法（`MessageStore.java:91-103`）：

```java
default CompletableFuture<PutMessageResult> asyncPutMessage(final MessageExtBrokerInner msg) {
    return CompletableFuture.completedFuture(putMessage(msg));
}
```

同步 API 现在已被降级为 future 的**阻塞包装**（`DefaultMessageStore.java:716-738`）：

```java
public PutMessageResult putMessage(MessageExtBrokerInner msg) {
    return waitForPutResult(asyncPutMessage(msg));
}

private PutMessageResult waitForPutResult(CompletableFuture<PutMessageResult> f) {
    int putMessageTimeout = Math.max(
        this.messageStoreConfig.getSyncFlushTimeout(),   // 5000
        this.messageStoreConfig.getSlaveTimeout())        // 3000
        + 5000;                                          // = 10s
    return f.get(putMessageTimeout, TimeUnit.MILLISECONDS);
}
```

`ExecutionException` / `InterruptedException` / `TimeoutException` 均返回 `PutMessageStatus.UNKNOWN_ERROR`。

5.x 新增 `FlushDiskWatcher`（`store/.../FlushDiskWatcher.java`）：单线程从 `LinkedBlockingQueue<GroupCommitRequest>` 取请求，轮询 `future().isDone()`，到 deadline 就 `wakeupCustomer(FLUSH_DISK_TIMEOUT)`，睡眠粒度 `Math.min(10, sleepTime)` ms 避免频繁线程切换。

## ReputMessageService：异步派发

作用（`DefaultMessageStore.java:2712-2783`）：从 `reputFromOffset` 开始反复 `commitLog.getData(reputFromOffset)` 读 CommitLog，逐条解析并 dispatch 到 ConsumeQueue / IndexService，推进 `reputFromOffset += size`；到文件尾则 `commitLog.rollNextFile()` 跳下一文件；`reputFromOffset < commitLog.getMinOffset()` 时被强制前移。

> [!WARNING]
> **`enableAsyncReput`（默认 true）是死配置** —— 全仓搜索 `isEnableAsyncReput()`，除 `MessageStoreConfig` 自身 getter/setter 外**零命中**。
>
> 实际决定用哪个实现的是**另一个参数** `enableBuildConsumeQueueConcurrently`（默认 **false**，`MessageStoreConfig.java:465`），见 `DefaultMessageStore.java:254-255`：
> ```java
> this.reputMessageService = messageStoreConfig.isEnableBuildConsumeQueueConcurrently()
>     ? new ConcurrentReputMessageService() : new ReputMessageService();
> ```

`reputFromOffset` 的初始值在 `start()` 里设置（`:439`）：`setReputFromOffset(this.commitLog.getConfirmOffset())`。

## 恢复（recover）

### load() 完整顺序

`DefaultMessageStore.java:324-368`（**注意与 4.x 资料完全不同**）：

```
load():
  1. lastExitOK = !isTempFileExist()                      // 正常/异常退出判定
  2. commitLog.load()                                     → LOAD_COMMITLOG_OK
  3. consumeQueueStore.load()                             → LOAD_CONSUME_QUEUE_OK
  4. registerCommitLogDispatchStore(consumeQueueStore)
  5. if (enableCompaction) compactionService.load()      → LOAD_COMPACTION_OK
  6. loadCheckPoint()
  7. indexService.load(lastExitOK)
  8. registerCommitLogDispatchStore(indexService)
  9. if (indexRocksDBEnable) registerCommitLogDispatchStore(indexRocksDBStore)
 10. if (transRocksDBEnable) registerCommitLogDispatchStore(transMessageRocksDBStore)
 11. recover(lastExitOK)
 12. setBrokerInitMaxOffset(getMaxPhyOffset())
```

`recover(lastExitOK)` 内部（`:389-416`）：

```
 1. consumeQueueStore.recover(brokerConfig.isRecoverConcurrently())  → RECOVER_CONSUME_QUEUE_OK
 2. dispatchFromPhyOffset = consumeQueueStore.getDispatchFromPhyOffset(lastExitOK)
 3. 对每个 commitLogDispatchStore 取 getDispatchFromPhyOffset()，取 min
 4. lastExitOK ? commitLog.recoverNormally(offset) : commitLog.recoverAbnormally(offset)
                                                                  → RECOVER_COMMITLOG_OK
 5. recoverTopicQueueTable()                                         → RECOVER_TOPIC_QUEUE_TABLE_OK
```

**已删除的方法**（4.x 资料里的这些在 5.5.1 全部不存在）：`recoverConsumeQueue`（合并进 `consumeQueueStore.recover(boolean)`）、`recoverLatestOffset`、`recoverConsumeQueueExt`（并入 `ConsumeQueue.recover()`）、`recoverBatchConsumeQueue`、`recoverPoints`。`recoverOffsetTable` 仍在，但现在是 `recoverTopicQueueTable()` 的唯一实现体（`:2026-2028`）。

### ConsumeQueue 恢复是纯 CQ 侧自校验

> [!WARNING]
> `STORE_TIME_AND_OFFSET_INDEX` 与 `STORE_TIME_AND_MAGIC_INDEX` 常量在 5.5.1 `CommitLog.java` 中**零命中** —— 这是 4.x 的机制。
>
> 5.5.1 的 `ConsumeQueue.recover()`（`ConsumeQueue.java:135-203`）**不回读 CommitLog**，做法是从倒数第 3 个文件开始逐单元扫：

```
从倒数第 3 个文件开始（index = mappedFiles.size() - 3，不足则取 0）
loop:
  for (i = 0; i < mappedFileSize; i += CQ_STORE_UNIT_SIZE):
      offset = getLong(); size = getInt(); tagsCode = getLong()
      if (offset >= 0 && size > 0):
          mappedFileOffset = i + CQ_STORE_UNIT_SIZE       // 有效槽
          setMaxPhysicOffset(offset + size)
          if (isExtAddr(tagsCode)) maxExtAddr = tagsCode
      else:
          log "recover current consume queue file over"; break   // 遇未填充槽即停
processOffset += mappedFileOffset
mappedFileQueue.setFlushedWhere(processOffset)
mappedFileQueue.setCommittedWhere(processOffset)
mappedFileQueue.truncateDirtyFiles(processOffset)        // 截断尾部脏数据
if (extReadEnable) consumeQueueExt.truncateByMaxAddress(maxExtAddr)
```

判定条件就是三元组 `offset >= 0 && size > 0`，`maxPhysicOffset` 取最后一条的 `offset + size`。**不与 CommitLog 交叉验证**，一致性由 CommitLog 侧的 `getDispatchFromPhyOffset` 间接保证。

### CRC 校验的作用范围

`checkCRCOnRecover`（默认 **true**，`MessageStoreConfig.java:210`）使用点在 `recoverNormally`（`:349`）、`recoverAbnormally`（`:770`）、`isMappedFileMatchedRecover`（`:940`）。

> [!TIP]
> 作用域**仅 CommitLog**。`ConsumeQueue.recover()` 中**不涉及任何 CRC 校验**（见上文伪代码，只读 offset/size/tagsCode）。

配套的 `checkCommitLogOffsetOnRecover` 默认 **false**（`:213`），仅在 `recoverAbnormally` 中使用。恢复时最多回溯文件数由 `commitLogRecoverMaxNum` 控制，默认 **10**（`:109`）。

## 过期文件清理

`CleanCommitLogService` 现为 `DefaultMessageStore` 内部类。触发条件（`:2374-2376`）三者取或：

```java
boolean isTimeUp = isTimeToDelete();                        // deleteWhen 到点
boolean isUsageExceedsThreshold = this.isSpaceToDelete();  // 磁盘水位
boolean isManualDelete = manualDeleteFileSeveralTimes.get() > 0;
if (isTimeUp || isUsageExceedsThreshold || isManualDelete) { ... }
```

清理任务调度（`addScheduleTask`，`:1931-1938`）：首次延迟 60s，周期 `cleanResourceInterval`（`MessageStoreConfig.java:175` = 10000 ms）。

### diskMaxUsedSpaceRatio 是 75，不是 72

> [!WARNING]
> **这是与旧资料最重要的不一致点。** 5.5.1 与 master **均为 75**：
> ```java
> // MessageStoreConfig.java:184-185
> private String deleteWhen = "04";
> private int diskMaxUsedSpaceRatio = 75;
> ```
> master `MessageStoreConfig.java:160` 同为 `75`。**72 是 4.x 时代的旧值。**
>
> master 还有边界校验：`< 10` 抛异常、`> 95` 抛异常，合法区间 [10, 95]。

`isSpaceToDelete()` 的判定阶梯（`:2428+`），按优先级：

1. `physicRatio > diskSpaceWarningLevelRatio`(90) → `cleanImmediately = true`，返回 true，并 `runningFlags.getAndMakeDiskFull()`
2. `physicRatio > diskSpaceCleanForciblyRatio`(85) → 返回 true
3. 同样两步检查 **ConsumeQueue 所在逻辑盘** `logicsRatio`
4. `ratio = diskMaxUsedSpaceRatio / 100.0`（即 **0.75**），`replicasPerPartition <= 1` 时：`minPhysicRatio > 0.75` 或 `logicsRatio > 0.75` → 返回 true（**75 唯一生效的地方**）
5. 多副本场景（`replicasPerPartition > 1`）有独立分支（`:2552` 起）

其他清理参数（5.5.1 与 master 一致）：

| 参数 | 默认值 | 出处 |
| ---- | ------ | ---- |
| `fileReservedTime` | `72` 小时 | `MessageStoreConfig.java:188` |
| `deleteWhen` | `"04"` | `:184` |
| `diskSpaceCleanForciblyRatio` | `85` | `:162` |
| `diskSpaceWarningLevelRatio` | `90` | `:160` |
| `deleteCommitLogFilesInterval` | `100` ms | `:177` |
| `deleteFileBatchMax` | `10` | `:190` |
| `cleanFileForciblyEnable` | `true` | `:265` |
| `maxBatchDeleteFilesNum` | `50` | `:308` |

> [!IMPORTANT]
> RocketMQ **不检查消息是否被消费**。`fileReservedTime` 到期就删，长期未消费的消息会被删除 —— 这是「消息积压 + 72 小时」场景下的头号数据丢失原因。
>
> 删除顺序：先删 CommitLog 过期文件，再删对应 ConsumeQueue 与 IndexFile，保证索引与数据一致性。

多路径支持：遍历 `storePathPhysic` 按 `MixAll.MULTI_PATH_SPLITTER` 分割，`physicRatio > 85` 的路径加入 `fullStorePath` 并 `commitLog.setFullStorePaths()`（`:2446-2447`）。

## 索引写入

`IndexService#indexMessage` 已**改名**为 `buildIndex(DispatchRequest)`（`IndexService.java:224`）。

触发链路（`DefaultMessageStore.java:2255-2268`，内部类 `CommitLogDispatcherBuildIndex`）：

```java
public void dispatch(DispatchRequest request) {
    if (messageStoreConfig.isMessageIndexEnable()) {          // 默认 true
        if (messageStoreConfig.isIndexFileWriteEnable()) {    // 默认 true
            DefaultMessageStore.this.indexService.buildIndex(request);
        }
        if (messageStoreConfig.isIndexRocksDBEnable()) {      // 默认 false
            DefaultMessageStore.this.indexRocksDBStore.buildIndex(request);
        }
    }
}
```

`buildIndex` 内部：跳过 `commitLogOffset < indexFile.getEndPhyOffset()` 的重复请求；事务消息跳过 `TRANSACTION_ROLLBACK_TYPE`；依次为 **uniqKey**、**keys**（按 `KEY_SEPARATOR` = 空格分割）、**TAGS** 建索引。

### 写满换新文件，不阻塞不丢弃

`IndexService.putKey`（`:284-295`）：

```java
private IndexFile putKey(IndexFile indexFile, DispatchRequest msg, String idxKey) {
    for (boolean ok = indexFile.putKey(idxKey, msg.getCommitLogOffset(),
                                       msg.getStoreTimestamp()); !ok; ) {
        LOGGER.warn("Index file [" + indexFile.getFileName() + "] is full, trying to create another one");
        indexFile = retryGetAndCreateIndexFile();
        if (null == indexFile) return null;      // ← 唯一失败出口
        ok = indexFile.putKey(idxKey, msg.getCommitLogOffset(), msg.getStoreTimestamp());
    }
    return indexFile;
}
```

`retryGetAndCreateIndexFile` 最多尝试 `MAX_TRY_IDX_CREATE = 3` 次（`:45`、`:307`）。**结论：写满 → 循环建新文件 → 不阻塞生产者、不丢弃索引。** 只有连续 3 次创建都失败才返回 null，此时打 ERROR 日志放弃**这一条**索引（不影响消息写入，因为索引构建在 dispatch 阶段）。

> [!WARNING]
> **`putMsgIndexHightWater`（默认 600000）是死配置** —— 全仓搜索除 `MessageStoreConfig` 自身 getter/setter 外**无任何调用方**。5.5.1 的 `IndexService` 只在 `flush()` 里用 `isWriteFull()`。

## 其他高频疑问

### 四个 maxTransfer 参数

| 参数 | 默认值 | 含义 |
| ---- | ------ | ---- |
| `maxTransferBytesOnMessageInMemory` | `1024 * 256`（256 KB） | 内存态单次拉取字节上限 |
| `maxTransferCountOnMessageInMemory` | `32` | 内存态单次拉取条数上限 |
| `maxTransferBytesOnMessageInDisk` | `1024 * 64`（64 KB） | 磁盘态 |
| `maxTransferCountOnMessageInDisk` | `8` | 磁盘态 |

用途（`DefaultMessageStore.java:1897-1910`，`isTheBatchFull` 最后一段）：

```java
if (isInMem) {
    if ((bufferTotal + sizePy) > getMaxTransferBytesOnMessageInMemory()) return true;
    return messageTotal > getMaxTransferCountOnMessageInMemory() - 1;
} else {
    if ((bufferTotal + sizePy) > getMaxTransferBytesOnMessageInDisk()) return true;
    return messageTotal > getMaxTransferCountOnMessageInDisk() - 1;
}
```

> [!TIP]
> 这是 `getMessage` 路径上**单个 `GetMessageResult` 累积消息的字节数与条数上限**，`isInMem` 由 `estimateInMemByCommitOffset(offsetPy, maxOffsetPy)` 判定（CommitLog 是否已刷盘）。**不是** CommitLog 零拷贝读的 batch 参数。
>
> 注意实际生效值是**参数值 − 1**（源码写 `> count - 1`），即内存 **31** 条、磁盘 **7** 条。

### maxFilterMessageSize 是读路径扫描上限

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

> [!WARNING]
> **它与 CommitLog 文件空间、filter 文件都无关。** 常见误解是「commitlog 文件剩余空间不足时返回 FILTERED_MESSAGE」——5.5.1 中 `PutMessageStatus` **没有** `FILTERED_MESSAGE`（共 16 项），`asyncPutMessage` 里也**没有任何过滤逻辑**。
>
> 真实语义：从消费者请求的 offset 起，最多扫描 **16000 字节的 CQ 空间**（≈800 条消息）就 `break`，防止为一条已被过滤掉的消息扫完整条队列。`Math.max` 保证不会小于本次请求条数所需的 CQ 字节数。

### osPageCacheBusy 判据是「持锁时长」

`osPageCacheBusyTimeOutMills = 1000`（`MessageStoreConfig.java:271`），判断逻辑（`DefaultMessageStore.java:742-749`）：

```java
public boolean isOSPageCacheBusy() {
    long begin = this.getCommitLog().getBeginTimeInLock();
    long diff = this.systemClock.now() - begin;
    return diff < 10000000
        && diff > this.messageStoreConfig.getOsPageCacheBusyTimeOutMills();
}
```

> [!TIP]
> 判据基准是 **`beginTimeInLock`（进入 `putMessage` 锁的时刻）**，不是「读 CommitLog 前」。判定条件是 **`1000ms < diff < 10,000,000ms`（约 2.78 小时）**：
> - `diff ≤ 1000ms`：正常，不算忙
> - `1000ms < diff < 2.78h`：**busy**（持锁过久，疑似 page cache 压力导致写慢），此时 putMessage 会 sleep
> - `diff ≥ 2.78h`：视为异常挂死的锁，放弃判定
>
> 顺带一提，`diff` 与 1000 的比较是**毫秒**，而 `10000000` 是纳秒量级的硬编码上界 —— 两个比较量纲不同，这是源码原样。

### LMQ 轻量队列

```java
// MessageStoreConfig.java:299-302
private boolean enableLmq = false;              // 默认关闭
private boolean enableMultiDispatch = false;     // 注意小写 d
private int maxLmqConsumeQueueNum = 20000;
private boolean enableLmqQuota = false;
```

`enableLmq` 消费点在 `LmqDispatch`、`ConsumeQueue:792`（`isEnableLmq() && MixAll.isLmq(queueName)`）、`CommitLog:1995`、`MessageExtEncoder:178` 等。

`enableMultiDispatch` 语义（`queue/MultiDispatchUtils.java:39-44`）：

```java
public static boolean isNeedHandleMultiDispatch(MessageStoreConfig cfg, String topic) {
    return cfg.isEnableMultiDispatch()
        && !topic.startsWith(MixAll.RETRY_GROUP_TOPIC_PREFIX)
        && !topic.startsWith(TopicValidator.SYSTEM_TOPIC_PREFIX)
        && !topic.equals(TopicValidator.RMQ_SYS_SCHEDULE_TOPIC);
}
```

即多路分发（一条消息投递到多个 LMQ 队列），排除重试组、系统 topic、延时 topic。

> [!TIP]
> `LmqQueueManager` 类**不存在**于 5.5.1。

### 冷数据限流（5.x 新增，全默认关闭）

| 参数 | 默认值 | 说明 |
| ---- | ------ | ---- |
| `accessMessageInMemoryMaxRatio` | `40` | 判定消息是否已落盘的内存占比阈值 |
| `accessMessageInMemoryHotRatio` | `26` | 热数据占比 |
| `dataReadAheadEnable` | **`true`** | 唯一默认开启的预读 |
| `coldDataFlowControlEnable` | `false` | 冷读限流开关 |
| `coldDataScanEnable` | `false` | 冷数据扫描 |
| `timerColdDataCheckIntervalMs` | `60 * 1000` | |
| `sampleCountThreshold` | `5000` | |
| `sampleSteps` | `32` | |
| `travelCqFileNumWhenGetMessage` | `1` | |

`CommitLog` 内部类 **`ColdDataCheckService`**（`CommitLog.java:139`，构造于 `:141`）与之配合。

> [!NOTE]
> 这些参数在 master（pom = 5.3.3）与 5.5.1 中均存在，但**是否在 5.3.0 之前引入未查到**（未拉更早 tag 核实）。

### Properties CRC（成对使用）

`CRC32_RESERVED_LEN = 19`（`CommitLog.java:86`），格式为 `[PROPERTY_CRC32 + NAME_VALUE_SEPARATOR + 10 位定长字符串 + PROPERTY_SEPARATOR]`。

```java
// MessageStoreConfig.java:338-339
private boolean enabledAppendPropCRC = false;   // 写入时在属性区尾部预留 19 字节写整体 CRC32
private boolean forceVerifyPropCRC = false;     // 校验时跳过 bodyCRC，改校验整条消息
```

两者**配套使用**：默认双 false，走传统 `bodyCRC` 校验路径（`CommitLog.java:551-560`）；`forceVerifyPropCRC = true` 时**跳过 bodyCRC**，改为从 properties 读回 `PROPERTY_CRC32` 手工解析期望值校验整条消息（`:619-632`）—— 而该属性由 `enabledAppendPropCRC = true` 写入。所以只开 `forceVerifyPropCRC` 而不开 `enabledAppendPropCRC` 会失效。

### RocksDB 版 ConsumeQueue

```java
// MessageStoreConfig.java:486, 519
private boolean rocksdbCQDoubleWriteEnable = false;
private String bottomMostCompressionTypeForConsumeQueueStore = CompressionType.ZSTD_COMPRESSION.getLibraryName();
```

相关实现类（5.5.1 存在）：`queue/RocksDBConsumeQueueStore`、`queue/RocksDBConsumeQueue`、`queue/CombineConsumeQueueStore`、`queue/RocksGroupCommitService`、`RocksDBMessageStore`。另有 `rocksdbCQSelectiveDoubleWriteEnable`（`:489`，`rocksdbCQDoubleWriteEnable` 的二级开关，CombineConsumeQueueStore 下只有特定 topic 双写）。

> [!WARNING]
> `useRocksDBStore` 这个配置项**不存在**于 5.5.1。

## 默认值汇总表

`MessageStoreConfig`（除注明外均在 `MessageStoreConfig.java`，5.5.1 与 master 一致）：

| 字段 | 默认值 | 行号 |
| ---- | ------ | ---- |
| `mappedFileSizeCommitLog` | `1024*1024*1024`（1G） | 52 |
| `mappedFileSizeConsumeQueue` | `300000 * 20` = 6,000,000 B | 138 |
| `mappedFileSizeTimerLog` | `100 * 1024 * 1024` | — |
| `maxMessageSize` | `1024*1024*4`（4 MB） | 194 |
| `maxFilterMessageSize` | `16000` | 206 |
| `maxHashSlotNum` | `5000000` | 237 |
| `maxIndexNum` | `5000000*4` = 20,000,000 | 238 |
| `messageIndexEnable` | `true` | 236 |
| `flushDiskType` | `FlushDiskType.ASYNC_FLUSH` | 256 |
| `syncFlushTimeout` | `1000*5` = 5000 | 258 |
| `flushCommitLogLeastPages` | `4` | 215 |
| `flushCommitLogThoroughInterval` | `1000*10` | 222 |
| `flushIntervalCommitLog` | `500` | 151 |
| `commitIntervalCommitLog` | `200` | 156 |
| `commitCommitLogLeastPages` | `4` | 217 |
| `commitCommitLogThoroughInterval` | `200` | 223 |
| `transientStorePoolEnable` | `false` | 275 |
| `transientStorePoolSize` | `5` | — |
| `warmMapedFileEnable` | `false` | 266 |
| `fileReservedTime` | `72`（小时） | 188 |
| `deleteWhen` | `"04"` | 184 |
| **`diskMaxUsedSpaceRatio`** | **`75`** | 185 |
| `diskSpaceCleanForciblyRatio` | `85` | 162 |
| `diskSpaceWarningLevelRatio` | `90` | 160 |
| `deleteCommitLogFilesInterval` | `100` | 177 |
| `deleteFileBatchMax` | `10` | 190 |
| `cleanResourceInterval` | `10000` | 175 |
| `checkCRCOnRecover` | `true` | 210 |
| `checkCommitLogOffsetOnRecover` | `false` | 213 |
| `commitLogRecoverMaxNum` | `10` | 109 |
| `useReentrantLockWhenPutMessage` | `true` | 167 |
| `maxTransferBytesOnMessageInMemory` | `1024*256` | 226 |
| `maxTransferCountOnMessageInMemory` | `32` | 228 |
| `maxTransferBytesOnMessageInDisk` | `1024*64` | 230 |
| `maxTransferCountOnMessageInDisk` | `8` | 232 |
| `accessMessageInMemoryMaxRatio` | `40` | 234 |
| `enableLmq` | `false` | 299 |
| `maxLmqConsumeQueueNum` | `20000` | 301 |
| `enableMultiDispatch` | `false` | 300 |
| `defaultQueryMaxNum` | `32` | 272 |
| `enableDLegerCommitLog` | `false` | 290 |
| `enableCompaction` | `true` | — |
| `maxHaTransferByteInSecond` | `100 * 1024 * 1024` | 416 |
| `putConsumeQueueDataByFileChannel` | `true` | 484 |
| `messageDelayLevel` | 18 级，见下 | 262 |
| `timerWheelEnable` | `true` | 84 |
| `timerMaxDelaySec` | `3600*24*3`（3 天） | 82 |
| `osPageCacheBusyTimeOutMills` | `1000` | 271 |
| `maxTopicLength` | `Byte.MAX_VALUE` = 127 | 318 |
| `autoMessageVersionOnTopicLen` | `true` | 325 |
| `rocksdbCQDoubleWriteEnable` | `false` | 486 |
| `bottomMostCompressionTypeForConsumeQueueStore` | `ZSTD_COMPRESSION` | 519 |
| `enabledAppendPropCRC` | `false` | 338 |
| `forceVerifyPropCRC` | `false` | 339 |
| `wakeCommitWhenPutMessage` | `true` | 364 |
| `wakeFlushWhenPutMessage` | `false` | 366 |
| `enableAsyncReput` | `true`（**死配置**） | 312 |
| `enableBuildConsumeQueueConcurrently` | `false` | 465 |
| `putMsgIndexHightWater` | `600000`（**死配置**） | 192 |
| `mappedFileSwapEnable` | `true`（**死配置**） | 349 |
| `commitLogSwapMapInterval` | `1L*60*60*1000`（**死配置**） | 351 |
| `commitLogForceSwapMapInterval` | `12L*60*60*1000`（**死配置**） | 350 |

`messageDelayLevel` 完整值（`:262`，Broker 与 Proxy 两处一致）：

```text
1s 5s 10s 30s 1m 2m 3m 4m 5m 6m 7m 8m 9m 10m 20m 30m 1h 2h
```

> [!IMPORTANT]
> 5.5.1 虽然新增了 `timerWheelEnable`（默认 **true**）等一整套 `timer*` 配置，但 `messageDelayLevel` **仍是 18 级**。时间轮实现在 `store/timer/` 包（`TimerMessageStore`、`TimerWheel`、`TimerLog`、`TimerCheckpoint`、`TimerRequest`、`TimerMetrics`、`Slot`、`Timeline`）。注意 `TimerMessageService` 与 `ScheduleMessageTimerWheel` 这两个类名**不存在**。

## 死配置速查表

以下参数在 5.5.1 中**只有字段声明与 getter/setter，没有任何消费方**。网上资料把它们当生效配置描述是错误的：

| 参数 | 默认值 | 备注 |
| ---- | ------ | ---- |
| `mappedFileSwapEnable` | `true` | swap 机制代码在，但 `swapMap()` 无调用方 |
| `commitLogSwapMapInterval` | 1 小时 | |
| `commitLogForceSwapMapInterval` | 12 小时 | |
| `commitLogSwapMapReserveFileNum` | 100 | |
| `logicQueueSwapMapInterval` | 1 小时 | |
| `logicQueueForceSwapMapInterval` | 12 小时 | |
| `cleanSwapedMapInterval` | 5 分钟 | |
| `putMsgIndexHightWater` | `600000` | 5.x 索引改用 `isWriteFull()` |
| `enableAsyncReput` | `true` | 实际由 `enableBuildConsumeQueueConcurrently` 决定 |
| `unmappedFile` | — | **全仓零命中，此字段不存在** |

> [!WARNING]
> 判断某个配置是否生效的可靠方法：grep 其 getter 名（`isXxx()` / `getXxx()`）在整个仓库的调用点，**排除 `MessageStoreConfig.java` 自身**。零命中即死配置。这个方法同样适用于其他模块。

## 核心默认值速查（跨模块）

`MessageStoreConfig` 里几个跨模块常被引用的值：

```java
brokerRole = BrokerRole.ASYNC_MASTER     // MessageStoreConfig.java:254（不是 BrokerConfig！）
haListenPort = 10912                      // 已确认
haSendHeartbeatInterval = 1000 * 5
haHousekeepingInterval = 1000 * 20
haTransferBatchSize = 1024 * 32
haMaxGapNotInSync = 1024 * 1024 * 256
```

> [!WARNING]
> **`brokerRole` 定义在 `MessageStoreConfig` 而非 `BrokerConfig`** —— 找配置时容易走错文件。
>
> 另外 `BrokerConfig` 实际路径是 `common/src/main/java/org/apache/rocketmq/common/BrokerConfig.java`（**不在 `broker/` 模块下**）。

## 已废弃 / 不存在的字段与类速查

写 5.x 笔记或读旧资料时最容易踩的坑，全部在 5.5.1 中**已确认不存在**：

| 旧资料中的东西 | 5.5.1 实际情况 |
| -------------- | -------------- |
| `BLANK_LEN` | 不存在，仅 `END_FILE_MIN_BLANK_LENGTH = 4+4 = 8` |
| `msgBeginTimeMax` / `msgBeginTimeMin` | 不存在 |
| `storeTimestampBaseOffset` | 不存在 |
| `msgMagicCode` | 不存在 |
| `MappedFile.size()` / `getSize()` | 不存在，用 `getFileSize()` |
| `incrementBufferNum` | 不存在，用 `ReferenceResource.refCount` |
| `SelectMappedBuffer` 类 | 已删除，仅存 `SelectMappedBufferResult` |
| `GroupCommitService.java` 等独立文件 | 已成为 `CommitLog` 内部类 |
| `commitLogMinOffset` / `whereMinOffset` / `whereMaxOffset` | 不存在 |
| `getMessagePositionByTime` / `getMessageOffset` | 不存在，用 `selectPhyOffset`（链表） |
| `STORE_TIME_AND_OFFSET_INDEX` | 不存在 |
| `recoverConsumeQueue` / `recoverLatestOffset` | 不存在，见 recover 章节 |
| `IndexService#indexMessage` | 改名 `buildIndex(DispatchRequest)` |
| `INDEX_ENTRY_SIZE` 字段名 | 实际叫 `indexSize` |
| `LmqQueueManager` | 不存在 |
| `TimerMessageService` / `ScheduleMessageTimerWheel` | 不存在，见 `store/timer/` |
| `unmappedFile` | 全仓零命中 |

## 内核机制关联

RocketMQ 的存储设计几乎每一步都踩在 Linux 内核机制上，可以与内核笔记对读：

- **mmap 与零拷贝**：`MappedFile` 的 `FileChannel.map(READ_WRITE)` + `slice()` 零拷贝读，与 [`ZeroCopy.md`](/docs/CS/OS/Linux/ZeroCopy.md) 里的 `sendfile` / `mmap` 对比值得单写一篇：Kafka 用 `sendfile`（拿不到消息内容，无法二次处理），RocketMQ 用 `mmap`（能拿到内容做死信投递、SQL92 过滤），这是两者架构分野的根源。
- **page cache 与刷盘**：`flush`（`force()` → page cache → 盘）与 `commit`（`writeBuffer` → page cache）的两级模型，依赖 writeback 机制；`osPageCacheBusy` 判据就是持锁时长。
- **`mlock` 锁内存**：`TransientStorePool` 用 JNA 调 `mlock()` 防止堆外 buffer 被换出到 swap，对应 [`mm/`](/docs/CS/OS/Linux/mm/memory.md) 系列的 mlock 相关机制。
- **文件预分配与缺页**：warm 机制逐 4 KB 触碰页面触发预分配，对应内存管理中的缺页处理路径。
- **定时器与时间轮**：`store/timer/TimerWheel` 的时间轮结构，对应 [`timer.md`](/docs/CS/OS/Linux/timer.md) 的定时器精度与时间缓存讨论 —— 时间轮是「用精度换效率」的典型，与内核定时器的取舍逻辑一致。

## Links

- [Apache RocketMQ](/docs/CS/MQ/RocketMQ/RocketMQ.md)
- [Broker](/docs/CS/MQ/RocketMQ/Broker.md)
- [Producer](/docs/CS/MQ/RocketMQ/Producer.md)
- [Consumer](/docs/CS/MQ/RocketMQ/Consumer.md)
- [事务消息](/docs/CS/MQ/RocketMQ/Transaction.md)
- [ZeroCopy](/docs/CS/OS/Linux/ZeroCopy.md)

## References

1. [RocketMQ 5.5.1 Release](https://github.com/apache/rocketmq/releases/tag/rocketmq-all-5.5.1)
2. [MessageStoreConfig.java (5.5.1)](https://github.com/apache/rocketmq/blob/rocketmq-all-5.5.1/store/src/main/java/org/apache/rocketmq/store/config/MessageStoreConfig.java)
3. [CommitLog.java (5.5.1)](https://github.com/apache/rocketmq/blob/rocketmq-all-5.5.1/store/src/main/java/org/apache/rocketmq/store/CommitLog.java)
4. [RocketMQ 官方文档](https://rocketmq.apache.org/docs/)
