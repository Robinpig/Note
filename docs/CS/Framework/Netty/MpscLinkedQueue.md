## Introduction

MPSC 是 **Multi-Producer, Single-Consumer** 的缩写：任意多个线程可以并发 `offer()`，但**只有一个线程**允许 `poll()`。Netty 的 EventLoop 恰好就是这种访问模式——外部业务线程往队列里塞任务，唯一的 EventLoop 线程负责取出并执行——所以 EventLoop 的任务队列默认就是一个 MPSC 队列，用无锁（lock-free）的 CAS 循环换掉了 `LinkedBlockingQueue` 的 `ReentrantLock`。

> [!WARNING]
>
> **文件名 `MpscLinkedQueue` 是历史命名：这个类在当前的 4.2.19.Final 中不存在**（全树无 `MpscLinkedQueue` / `MpscLinkedQueueHead` / `MpscLinkedQueueTail` / `LinkedQueueNode` 的任何定义）。本文记录的是 Netty 实际使用的 **MPSC 数组队列**家族：EventLoop 任务队列默认走无界的 `MpscUnboundedArrayQueue`（按 chunk 分块的链式数组）。
>
> **这些类不是 Netty 自己写的**：Netty 依赖外部构件 `org.jctools:jctools-core`，版本 **4.0.7**（源码：`pom.xml:768`；该版本从 **4.2.18.Final** 起使用），在打包时用 maven-shade-plugin 把包名 `org.jctools.` 重定位到 `io.netty.util.internal.shaded.org.jctools.`（源码：`common/pom.xml:166-172`，依赖声明在 `common/pom.xml:55-65` 且特意保留 `compile` scope 以便被 shade 插件处理）。netty 仓库里 `io/netty/util/internal/shaded/org/jctools/**` 只有 `DoNotRemove.java` 占位文件——它的作用是「让 module-info 插件把这个包写进模块描述符」（源码：`common/src/main/java/io/netty/util/internal/shaded/org/jctools/queues/DoNotRemove.java:18-20`），**没有任何队列实现源码**。因此本文凡涉及队列内部算法的片段，都无法给出 netty 仓库行号，已单独标注。

## Class Inventory

能在本仓库定位到的全部队列类名，来自 `PlatformDependent` 的 import 清单（源码：`common/src/main/java/io/netty/util/internal/PlatformDependent.java:21-39`）：

| 包名（shade 前） | 类 | 用途 |
| --- | --- | --- |
| `org.jctools.queues` | `MpscUnboundedArrayQueue` | 无界，Unsafe 分支，EventLoop 默认路径 |
| | `MpscChunkedArrayQueue` | 有界，按 chunk 增长，**只在有界分支出现** |
| | `MpscArrayQueue` | 固定容量（不增长） |
| | `MpscUnpaddedArrayQueue` | 固定容量、去掉缓存行 padding |
| | `MpmcArrayQueue` | 多生产者多消费者 |
| | `SpscLinkedQueue` | 单生产者单消费者（当前唯一还在用的 LinkedQueue） |
| `...queues.atomic` | `MpscUnboundedAtomicArrayQueue`、`MpscChunkedAtomicArrayQueue`、`MpscAtomicArrayQueue`、`MpscAtomicUnpaddedArrayQueue`、`MpscChunkedAtomicArrayQueue` | 无 Unsafe 时的 `AtomicXxxFieldUpdater` 实现 |
| `...queues.varhandle` | `MpscUnboundedVarHandleArrayQueue`、`MpscChunkedVarHandleArrayQueue`、`MpscVarHandleArrayQueue`、`MpscVarHandleUnpaddedArrayQueue` | 无 Unsafe 时的 `VarHandle` 实现（自 **4.2.18.Final** 起，提交 `95012caf2c`） |
| `...queues.atomic.unpadded` / `...queues.varhandle.unpadded` | `MpscAtomicUnpaddedArrayQueue`、`MpscVarHandleUnpaddedArrayQueue` | unpadded 变体 |

注意 unpadded 系列的真实类名是 `MpscUnpaddedArrayQueue` / `MpscVarHandleUnpaddedArrayQueue` / `MpscAtomicUnpaddedArrayQueue`，**不存在 `MpscUnpaddedQueue`**。

## Queue Selection

实际类型由 `PlatformDependent` 的私有静态内部类 `Mpsc` 决定（源码：`common/src/main/java/io/netty/util/internal/PlatformDependent.java:1252-1302`）：

```java
// 源码：common/src/main/java/io/netty/util/internal/PlatformDependent.java:1279
static <T> Queue<T> newMpscQueue(final int maxCapacity) {
    // Calculate the max capacity which can not be bigger than MAX_ALLOWED_MPSC_CAPACITY.
    // This is forced by the MpscChunkedArrayQueue implementation as will try to round it
    // up to the next power of two and so will overflow otherwise.
    final int capacity = max(min(maxCapacity, MAX_ALLOWED_MPSC_CAPACITY), MIN_MAX_MPSC_CAPACITY);
    return newChunkedMpscQueue(MPSC_CHUNK_SIZE, capacity);
}

// 源码：common/src/main/java/io/netty/util/internal/PlatformDependent.java:1287
static <T> Queue<T> newChunkedMpscQueue(final int chunkSize, final int capacity) {
    if (USE_MPSC_CHUNKED_ARRAY_QUEUE) {
        return new MpscChunkedArrayQueue<T>(chunkSize, capacity);
    }
    return hasJctoolsVarHandle() ? new MpscChunkedVarHandleArrayQueue<T>(chunkSize, capacity)
            : new MpscChunkedAtomicArrayQueue<T>(chunkSize, capacity);
}

// 源码：common/src/main/java/io/netty/util/internal/PlatformDependent.java:1295
static <T> Queue<T> newMpscQueue() {
    if (USE_MPSC_CHUNKED_ARRAY_QUEUE) {
        return new MpscUnboundedArrayQueue<T>(MPSC_CHUNK_SIZE);
    }
    return hasJctoolsVarHandle() ? new MpscUnboundedVarHandleArrayQueue<T>(MPSC_CHUNK_SIZE)
            : new MpscUnboundedAtomicArrayQueue<T>(MPSC_CHUNK_SIZE);
}
```

即：**无界路径优先用基于 Unsafe 的 `MpscUnboundedArrayQueue`；没有 Unsafe 时按 JDK 版本二选一**——JDK 11+ 用 `VarHandle` 版，更老用 `AtomicXxxFieldUpdater` 版。相关常量与判定：

```java
// 源码：common/src/main/java/io/netty/util/internal/PlatformDependent.java:106
private static final int MPSC_CHUNK_SIZE =  1024;
private static final int MIN_MAX_MPSC_CAPACITY =  MPSC_CHUNK_SIZE * 2;
private static final int MAX_ALLOWED_MPSC_CAPACITY = Pow2.MAX_POW2;

// 源码：common/src/main/java/io/netty/util/internal/PlatformDependent.java:693
static boolean hasJctoolsVarHandle() {
    return javaVersion() >= 11;
}
```

`USE_MPSC_CHUNKED_ARRAY_QUEUE` 的判定不是看 JDK 版本，而是看 **`sun.misc.Unsafe` 能否拿到**——它会用 `AccessController.doPrivileged` 强制 JCTools 初始化 `UnsafeAccess.UNSAFE`，拿不到就整条路径退化到非 Unsafe 实现（源码：`common/src/main/java/io/netty/util/internal/PlatformDependent.java:1255-1277`）。有界分支还会把容量夹在 `[MIN_MAX_MPSC_CAPACITY, MAX_ALLOWED_MPSC_CAPACITY]` 之间，避免向上取整到 2 的幂时溢出。

对外的三个工厂方法因此有明确分工：

| 工厂方法 | 源码位置 | 返回 |
| --- | --- | --- |
| `newMpscQueue()` | `PlatformDependent.java:1309-1311` | 无界，EventLoop 默认 |
| `newMpscQueue(int maxCapacity)` | `PlatformDependent.java:1317-1319` | 有界 chunked（`MpscChunkedArrayQueue`） |
| `newMpscQueue(int chunkSize, int maxCapacity)` | `PlatformDependent.java:1326-1328` | 指定 chunk 大小的有界队列 |
| `newFixedMpscQueue(int capacity)` | `PlatformDependent.java:1345-1350` | 固定容量，不增长 |
| `newFixedMpscUnpaddedQueue(int capacity)` | `PlatformDependent.java:1358-1363` | 固定容量、无 padding，「队列不会被激烈争用时优先用它」 |

## EventLoop Task Queue

EventLoop 的任务队列就在上面这张表里选。默认最大待处理任务数来自系统属性，默认 `Integer.MAX_VALUE` 即「无界」：

```java
// 源码：transport/src/main/java/io/netty/channel/SingleThreadEventLoop.java:36
protected static final int DEFAULT_MAX_PENDING_TASKS = Math.max(16,
        SystemPropertyUtil.getInt("io.netty.eventLoop.maxPendingTasks", Integer.MAX_VALUE));
```

```java
// 源码：transport/src/main/java/io/netty/channel/SingleThreadIoEventLoop.java:338
protected static Queue<Runnable> newTaskQueue0(int maxPendingTasks) {
    // This event loop never calls takeTask()
    return maxPendingTasks == Integer.MAX_VALUE ? PlatformDependent.<Runnable>newMpscQueue()
            : PlatformDependent.<Runnable>newMpscQueue(maxPendingTasks);
}
```

也就是说：**只有在显式把 `io.netty.eventLoop.maxPendingTasks` 调小（或自定义 `EventLoopTaskQueueFactory`）时，才会走有界的 chunked 分支**。另外 `SingleThreadEventExecutor` 另有一套默认值，用的属性名是 `io.netty.eventexecutor.maxPendingTasks`（源码：`common/src/main/java/io/netty/util/concurrent/SingleThreadEventExecutor.java:57-58`），两者不要混。

`NioEventLoop` 会调两次 `newTaskQueue`，分别建主任务队列和 `tailTasks`（源码：`transport/src/main/java/io/netty/channel/nio/NioEventLoop.java:52-62`）。

想完全接管队列实现时传 `EventLoopTaskQueueFactory`（`transport/src/main/java/io/netty/channel/EventLoopTaskQueueFactory.java:29`），它只有一个方法 `Queue<Runnable> newTaskQueue(int maxCapacity)`，注意返回值不要求实现 `BlockingQueue`。

### Why Single Consumer Is Safe Here

MPSC 队列的正确性前提是「只有一个线程 poll」。EventLoop 天然满足：所有出队都发生在 EventLoop 自己的线程上，且 `pollTask()` 一进来就断言在 loop 内。

```java
// 源码：common/src/main/java/io/netty/util/concurrent/SingleThreadEventExecutor.java:282
protected Runnable pollTask() {
    assert inEventLoop();
    return pollTaskFrom(taskQueue);
}

protected static Runnable pollTaskFrom(Queue<Runnable> taskQueue) {
    for (;;) {
        Runnable task = taskQueue.poll();
        if (task != WAKEUP_TASK) {
            return task;
        }
    }
}
```

`inEventLoop()` 这个 assert 就是「单消费者」约束在代码里的落点；关闭时的 `drainTasks()` 同样只在自己的线程上跑（源码：`common/src/main/java/io/netty/util/concurrent/SingleThreadEventExecutor.java:1338-1341`）。反过来说，**用户代码绝不能自己去 `poll()` EventLoop 的任务队列**。

生产者侧则是无锁的：任意线程 `execute()` 都只是 `taskQueue.offer(task)`，CAS 失败就自旋重试，没有锁、也没有 `synchronized`，这正是 EventLoop 在大量跨线程提交时仍能保持吞吐的原因。

## Message Passing Queue API

jctools 在这些队列之上还定义了一组「松弛（relaxed）」批量接口 `MessagePassingQueue`，Netty 在 `Recycler` 里直接用了它。这是本仓库唯一能观察到 `relaxedOffer` / `relaxedPoll` / `relaxedPeek` 的地方：

```java
// 源码：common/src/main/java/io/netty/util/Recycler.java:565
return handles.relaxedPoll();
```

```java
// 源码：common/src/main/java/io/netty/util/Recycler.java:583
MessagePassingQueue<H> handles = pooledHandles;
if (handles != null) {
    handles.relaxedOffer(handle);
}
```

`Recycler` 拿到的队列正是 `PlatformDependent.newMpscQueue(chunkSize, maxCapacity)` 直接强转来的（源码：`common/src/main/java/io/netty/util/Recycler.java:549`），说明 Netty 依赖「MPSC 工厂返回的实例同时实现 `MessagePassingQueue`」这一契约。Netty 自己的调试用实现 `BlockingMessageQueue` 也照此实现了这三个方法（源码：`common/src/main/java/io/netty/util/Recycler.java:682-694`）。

> [!NOTE]
>
> `relaxedOffer` / `relaxedPoll` / `relaxedPeek` 的**语义定义（relaxed 指的是比 `offer`/`poll` 更弱的跨线程可见性保证）写在 jctools 的 `MessagePassingQueue` 接口 javadoc 里**，而 jctools 源码不在 netty 仓库内，本文无法给出源码行号；上面能确认的只有：这些方法确实存在、确实被 `Recycler` 这样调用。`Recycler` 注释明确指出 `BlockingMessageQueue` 不支持 `fill` 批量操作（源码：`common/src/main/java/io/netty/util/Recycler.java:623`）。

## MpscIntQueue

`MpscIntQueue` 是 **Netty 自己在仓库内实现的唯一一个 MPSC 队列**（自 **4.2.3.Final** 起引入，提交 `5ca90a70db`；接口定义见 `common/src/main/java/io/netty/util/concurrent/MpscIntQueue.java:32`），存原始 `int` 以避开装箱。它的注释直接点明了血缘——「This implementation is based on MpscAtomicUnpaddedArrayQueue from JCTools」（源码：`MpscIntQueue.java:109-111`），所以可以用它来讲清 MPSC 数组队列的核心套路。

三个 volatile 索引，消费者索引被生产者**缓存**成 `producerLimit`，避免每次 `offer` 都去读对方的缓存行：

```java
// 源码：common/src/main/java/io/netty/util/concurrent/MpscIntQueue.java:113-123
private static final AtomicLongFieldUpdater<MpscAtomicIntegerArrayQueue> PRODUCER_INDEX =
        AtomicLongFieldUpdater.newUpdater(MpscAtomicIntegerArrayQueue.class, "producerIndex");
private static final AtomicLongFieldUpdater<MpscAtomicIntegerArrayQueue> PRODUCER_LIMIT =
        AtomicLongFieldUpdater.newUpdater(MpscAtomicIntegerArrayQueue.class, "producerLimit");
private static final AtomicLongFieldUpdater<MpscAtomicIntegerArrayQueue> CONSUMER_INDEX =
        AtomicLongFieldUpdater.newUpdater(MpscAtomicIntegerArrayQueue.class, "consumerIndex");
private final int mask;
private final int emptyValue;
private volatile long producerIndex;
private volatile long producerLimit;
private volatile long consumerIndex;
```

入队是标准的「CAS 抢下标 → 再写元素」两阶段。多生产者之间**只争抢 `producerIndex` 这一个 CAS 点**，抢到之后各自写各自的槽位，互不干扰：

```java
// 源码：common/src/main/java/io/netty/util/concurrent/MpscIntQueue.java:141
public boolean offer(int value) {
    if (value == emptyValue) {
        throw new IllegalArgumentException("Cannot offer the \"empty\" value: " + emptyValue);
    }
    // use a cached view on consumer index (potentially updated in loop)
    final int mask = this.mask;
    long producerLimit = this.producerLimit;
    long pIndex;
    do {
        pIndex = producerIndex;
        if (pIndex >= producerLimit) {
            final long cIndex = consumerIndex;
            producerLimit = cIndex + mask + 1;
            if (pIndex >= producerLimit) {
                // FULL :(
                return false;
            } else {
                // update producer limit to the next index that we must recheck the consumer index
                // this is racy, but the race is benign
                PRODUCER_LIMIT.lazySet(this, producerLimit);
            }
        }
    } while (!PRODUCER_INDEX.compareAndSet(this, pIndex, pIndex + 1));
    /*
     * NOTE: the new producer index value is made visible BEFORE the element in the array. If we relied on
     * the index visibility to poll() we would need to handle the case where the element is not visible.
     */
    // Won CAS, move on to storing
    final int offset = (int) (pIndex & mask);
    lazySet(offset, value);
    // AWESOME :)
    return true;
}
```

三个要点：

1. **下标先可见、元素后可见**，所以消费端不能只信 `producerIndex`。
2. `producerLimit` 是对 `consumerIndex` 的**乐观缓存**，只在触界时才重新读一次；注释直言「this is racy, but the race is benign」——缓存偏保守只会少卖槽位，不会破坏正确性。
3. 写元素用 `lazySet`（有序写/最终可见）而不是 `set`，省掉一次全屏障。

出队侧因为只有一个消费者，连 CAS 都不需要，直接普通读 + `lazySet` 推进 `consumerIndex`：

```java
// 源码：common/src/main/java/io/netty/util/concurrent/MpscIntQueue.java:176
public int poll() {
    final long cIndex = consumerIndex;
    final int offset = (int) (cIndex & mask);
    // If we can't see the next available element we can't poll
    int value = get(offset);
    if (emptyValue == value) {
        /*
         * NOTE: Queue may not actually be empty in the case of a producer (P1) being interrupted after
         * winning the CAS on offer but before storing the element in the queue. Other producers may go on
         * to fill up the queue after this element.
         */
        if (cIndex != producerIndex) {
            do {
                value = get(offset);
            } while (emptyValue == value);
        } else {
            return emptyValue;
        }
    }
    lazySet(offset, emptyValue);
    CONSUMER_INDEX.lazySet(this, cIndex + 1);
    return value;
}
```

那个 `do { ... } while` 自旋正是要点 1 的代价：生产者可能已经 CAS 成功但元素还没写出来，此时 `cIndex != producerIndex` 说明队列「逻辑上非空」，消费者只能等元素可见，不能误判为空队列。

`MpscIntQueue` 是**固定容量**的，所以索引没有翻倍、也没有 resize 位（这一点与下面无界的 chunked 队列不同）。它另提供 `drain(int, IntConsumer)` 与 `fill(int, IntSupplier)` 两个批量方法（源码：`MpscIntQueue.java:201`、`:225`），对应 `MessagePassingQueue` 的批量语义。

## Unbounded Chunked Queue Internals

> [!WARNING]
>
> 下面这一节的代码来自 **jctools-core 4.0.7**（`MpscUnboundedArrayQueue` 及其父类 `BaseMpscLinkedArrayQueue` 系列），源码不在 netty 仓库内，无法给出「源码：<netty 路径>:<行号>」。保留它们是因为 EventLoop 默认队列的行为确实由它们决定；如需逐行核对，请以 jctools 4.0.7 的对应文件为准。

无界队列的做法是「chunk 链表」：每个 chunk 是 1024 槽的数组，装不下就再分配一个更大的 chunk，用数组尾部的额外槽位指向下一个 chunk。`producerIndex` / `consumerIndex` 因此**每次推进 2 而不是 1**——**最低位被借去做 resize 标志位**，看到奇数就说明有生产者正在扩容，其它生产者自旋等待：

```java
// jctools 4.0.7，BaseMpscLinkedArrayQueue#offer（netty 仓库无此源码）
public boolean offer(final E e) {
    long mask;
    E[] buffer;
    long pIndex;

    while (true) {
        long producerLimit = lvProducerLimit();
        pIndex = lvProducerIndex();
        // lower bit is indicative of resize, if we see it we spin until it's cleared
        if ((pIndex & 1) == 1) {
            continue;
        }
        // pIndex is even (lower bit is 0) -> actual index is (pIndex >> 1)

        mask = this.producerMask;
        buffer = this.producerBuffer;

        // assumption behind this optimization is that queue is almost always empty or near empty
        if (producerLimit <= pIndex) {
            int result = offerSlowPath(mask, pIndex, producerLimit);
            switch (result) {
                case CONTINUE_TO_P_INDEX_CAS:
                    break;
                case RETRY:
                    continue;
                case QUEUE_FULL:
                    return false;
                case QUEUE_RESIZE:
                    resize(mask, buffer, pIndex, e, null);
                    return true;
            }
        }

        if (casProducerIndex(pIndex, pIndex + 2)) {
            break;
        }
    }
    // INDEX visible before ELEMENT
    final long offset = modifiedCalcCircularRefElementOffset(pIndex, mask);
    soRefElement(buffer, offset, e); // release element e
    return true;
}
```

快慢路径的分工很清楚：绝大多数情况下队列接近空，`producerLimit <= pIndex` 不成立，直接 CAS 就完事；只有触界才落进 `offerSlowPath`，在那里重新读 `consumerIndex`、抬高 `producerLimit`，或者抢到 `pIndex + 1`（置起 resize 位）去扩容：

```java
// jctools 4.0.7，BaseMpscLinkedArrayQueue#offerSlowPath（netty 仓库无此源码）
private int offerSlowPath(long mask, long pIndex, long producerLimit) {
    final long cIndex = lvConsumerIndex();
    long bufferCapacity = getCurrentBufferCapacity(mask);

    if (cIndex + bufferCapacity > pIndex) {
        if (!casProducerLimit(producerLimit, cIndex + bufferCapacity)) {
            return RETRY;
        } else {
            return CONTINUE_TO_P_INDEX_CAS;
        }
    }
    // full and cannot grow
    else if (availableInQueue(pIndex, cIndex) <= 0) {
        return QUEUE_FULL;
    }
    // grab index for resize -> set lower bit
    else if (casProducerIndex(pIndex, pIndex + 1)) {
        return QUEUE_RESIZE;
    } else {
        return RETRY;
    }
}
```

出队时遇到哨兵元素 `JUMP` 就表示「当前 chunk 已消费完，跳到下一个 chunk」：

```java
// jctools 4.0.7，BaseMpscLinkedArrayQueue#poll（netty 仓库无此源码）
public E poll() {
    final E[] buffer = consumerBuffer;
    final long index = lpConsumerIndex();
    final long mask = consumerMask;

    final long offset = modifiedCalcCircularRefElementOffset(index, mask);
    Object e = lvRefElement(buffer, offset);
    if (e == null) {
        if (index != lvProducerIndex()) {
            // poll() == null iff queue is empty, null element is not strong enough indicator, so we must
            // check the producer index. If the queue is indeed not empty we spin until element is visible.
            do {
                e = lvRefElement(buffer, offset);
            }
            while (e == null);
        } else {
            return null;
        }
    }

    if (e == JUMP) {
        final E[] nextBuffer = nextBuffer(buffer, mask);
        return newBufferPoll(nextBuffer, index);
    }

    soRefElement(buffer, offset, null); // release element null
    soConsumerIndex(index + 2); // release cIndex
    return (E) e;
}
```

### Cache Line Padding

MPSC 队列里最容易被伪共享拖垮的是「生产者的 `producerIndex`」和「消费者的 `consumerIndex`」——它们被不同线程高频读写，若落在同一缓存行会互相失效。jctools 的做法是用填充字段把冷热字段隔开：

```java
// jctools 4.0.7，BaseMpscLinkedArrayQueuePad1（netty 仓库无此源码）
abstract class BaseMpscLinkedArrayQueuePad1<E> extends AbstractQueue<E> implements IndexedQueue {
    long p01, p02, p03, p04, p05, p06, p07;
    long p10, p11, p12, p13, p14, p15, p16, p17;
}
```

要不要这份 padding 是可以选的——`PlatformDependent.newFixedMpscQueue()` 用带 padding 的 `MpscArrayQueue`，`newFixedMpscUnpaddedQueue()` 用不带 padding 的 `MpscUnpaddedArrayQueue`。后者 javadoc 的建议是「当队列不会被激烈争用时优先用它」（源码：`common/src/main/java/io/netty/util/internal/PlatformDependent.java:1352-1357`），因为 padding 是用内存换缓存行独占。

## Links

- [Netty](/docs/CS/Framework/Netty/Netty.md)
- [EventLoop](/docs/CS/Framework/Netty/EventLoop.md)
- [Memory Pool](/docs/CS/Framework/Netty/memory.md)
- [HashedWheelTimer](/docs/CS/Framework/Netty/HashedWheelTimer.md)

## References

1. [JCTools — MpscUnboundedArrayQueue (jctools-core 4.0.7)](https://github.com/JCTools/JCTools/blob/master/jctools-core/src/main/java/org/jctools/queues/MpscUnboundedArrayQueue.java)
2. [JCTools 官方仓库：并发队列工具库](https://github.com/JCTools/JCTools)
3. [PlatformDependent (Netty API Reference 4.2)](https://netty.io/4.2/api/io/netty/util/internal/PlatformDependent.html)
