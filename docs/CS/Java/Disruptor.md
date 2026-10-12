## Introduction

Disruptor 是 LMAX 交易所开源的**线程间消息传递（ITC，inter-thread communication）并发框架**，最初用于其低延迟交易系统的可靠消息架构，2011 年获得 Duke's Choice Award。它不是一个通用的并发集合，而是**为"一个生产者/一组生产者 → 一组消费者"的流水线场景设计的高吞吐、低延迟有界队列替代方案**。

本笔记以 **3.4.4（2023-09-29，Maven Central 当前最新稳定版，`com.lmax:disruptor`）** 源码为事实基线。Disruptor 的核心不是"又一个队列"，而是把硬件特性（CPU 缓存行、内存屏障、CAS）直接编入数据结构的设计范式——其设计哲学被称为 **Mechanical Sympathy（机械同理心，Martin Thompson 提出）**：理解底层硬件如何工作，并写出与之协作而非对抗的代码。

> 注意：Disruptor 是第三方库（Apache License 2.0），不在 JDK 标准库中。它与 [Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md) 中的 `java.util.concurrent` 工具（[volatile](/docs/CS/Java/JDK/Concurrency/volatile.md)、[JMM](/docs/CS/Java/JDK/Concurrency/JMM.md)、AQS、BlockingQueue）是互补关系——Disruptor 在后者之上用更激进的无锁 + 缓存友好设计把吞吐/延迟再压一个数量级。

## Mechanical Sympathy

Mechanical Sympathy 是 Disruptor 一切优化的出发点，三条主线：

1. **缓存行友好**：CPU 以缓存行（通常 64 字节）为单位在核间搬运数据。若两个被高频修改的变量落在同一缓存行，一个核的写入会使其他核的该行失效（伪共享），吞吐量断崖式下跌。Disruptor 对每一个被并发修改的 `Sequence` 都做缓存行填充，把关键字段孤立在独立缓存行。
2. **最小化的内存屏障**：只在该用的地方用屏障。生产者的"发布"用 `StoreStore`（ordered write）而非全屏障 `volatile` 写，消费者用一次 `volatile` 读来"看到"发布标志——既保证可见性，又避免 `volatile` 写自带的 `StoreLoad` 全屏障开销。
3. **无锁化**：用 CAS + 序号推进代替 `synchronized` / `Lock` + `Condition`，消除上下文切换与锁竞争。

## Core Components

Disruptor 的运行时由一组相互协作的类构成，按职责分层：

| 组件 | 角色 | 关键实现类（3.4.4） |
| --- | --- | --- |
| Event | 数据载体，由用户定义；预分配、运行时只改字段 | 用户实现 + `EventFactory` |
| RingBuffer | 核心数据结构，环形数组存储 Event | `RingBuffer`（含 `RingBufferFields`） |
| Sequencer | "大脑"，分配序列号、协调生产者/消费者进度 | `SingleProducerSequencer` / `MultiProducerSequencer` |
| Sequence | 并发进度计数器（每个生产者/消费者各持一个） | `Sequence` |
| SequenceBarrier | 消费者等待进度的屏障，内含 WaitStrategy 与依赖关系 | `ProcessingSequenceBarrier` |
| WaitStrategy | 消费者"追不上"时如何等待 | 6 种（见下文） |
| EventProcessor | 消费者线程循环拉取事件 | `BatchEventProcessor` / `WorkProcessor` |
| EventHandler / WorkHandler | 用户业务逻辑（多播 / 竞争两种语义） | 用户实现 |
| Disruptor (DSL) | 装配入口，定义消费拓扑并 `start()` | `com.lmax.disruptor.dsl.Disruptor` |

## RingBuffer: the Heart

`RingBuffer` 不是"环形链表"，而是**预分配的定长数组**（`E[] entries`）。几个关键设计：

- **数组而非链表**：预分配所有 Event 对象，运行时生产者/消费者只修改对象字段，不创建/销毁对象 → **零 GC 压力**；同时数组对 CPU 预取与缓存机制天然友好。
- **容量必须是 2 的幂**：`createSingleProducer` / `createMultiProducer` 要求 `bufferSize` 为 2^n，从而用位运算 `index = sequence & (bufferSize - 1)` 替代取模，下标递增定位极快。
- **下标不溢出**：序号是 `long`，即使 100 万 QPS 也要约 29 万年才会回绕，实践中无需处理溢出。
- **缓存行填充**：`RingBufferPad`（前 7 个 `long`）→ `RingBufferFields`（含 `entries` 数组、`indexMask`、`bufferSize`）→ 尾部再填充 7 个 `long`（`RingBuffer.java:24,26,106`），把 `entries` 数组这一被所有线程高频访问的字段与相邻字段隔开，避免伪共享。

```java
// RingBuffer.java:24-29, 106  — 数组前后的缓存行填充
abstract class RingBufferPad {
    protected long p1, p2, p3, p4, p5, p6, p7;
}
abstract class RingBufferFields<E> extends RingBufferPad {
    protected final int bufferSize;
    // ... entries 数组、indexMask 等
    protected long p1, p2, p3, p4, p5, p6, p7; // 尾部填充
}
```

## Sequence and False Sharing Elimination

`Sequence` 是 Disruptor 里被并发读写最频繁的计数器，每个生产者、每个消费者都各有独立的 `Sequence`。它的实现是**消除伪共享的范本**：

```java
// Sequence.java:23-46 — 通过类继承链做手工缓存行填充
class LhsPadding { protected long p1, p2, p3, p4, p5, p6, p7; }
class Value extends LhsPadding { protected volatile long value; }
class RhsPadding extends Value { protected long p9, p10, p11, p12, p13, p14, p15; }
public class Sequence extends RhsPadding { /* ... */ }
```

> **反直觉事实**：Disruptor 3.4.4 **没有**使用 `@sun.misc.Contended` / `jdk.internal.vm.annotation.Contended` 注解，而是用**手工 padding 类继承链**（14 个填充 `long` 包裹 `value`）实现隔离。这比 `@Contended` 更可控、不依赖 JVM 的 `-XX:-RestrictContended` 开关（JDK 8 默认限制 `@Contended` 仅 JDK 内部类可用）。

`Sequence` 刻意提供三种不同强度的写语义，让调用方按需取用：

| 方法 | 底层操作 | 内存语义 | 用途 |
| --- | --- | --- | --- |
| `get()` | 普通 `volatile` 读 | 看到其他线程对该字段的最新写 | 消费者读进度 |
| `set(v)` | `UNSAFE.putOrderedLong`（lazySet） | **StoreStore** 屏障，不保证立即对其他线程可见 | 进度更新（消费者 `sequence.set`） |
| `setVolatile(v)` | `UNSAFE.putLongVolatile` | **StoreLoad** 全屏障 | 单生产者 `next()` 刷新游标给消费者 |
| `compareAndSet(e, n)` | `UNSAFE.compareAndSwapLong` | CAS | 多生产者分配序号 |

## Sequencer: Single vs Multi Producer

`Sequencer` 负责分配序号并防止生产者覆盖尚未被消费者读取的数据。单/多生产者是两套完全不同的实现，复杂度差异巨大，**根源在于"发布顺序是否等于序号顺序"**。

### SingleProducerSequencer (No CAS, Simplest)

单线程生产，因此不需要 CAS，也不需要 per-slot 发布跟踪：

```java
// SingleProducerSequencer.java:117-146 (节选)
public long next(int n) {
    long nextValue = this.nextValue;
    long nextSequence = nextValue + n;
    long wrapPoint = nextSequence - bufferSize;
    long cachedGatingSequence = this.cachedValue;
    if (wrapPoint > cachedGatingSequence || cachedGatingSequence > nextValue) {
        cursor.setVolatile(nextValue);          // StoreLoad 屏障：刷新游标可见性
        long minSequence;
        while (wrapPoint > (minSequence = Util.getMinimumSequence(gatingSequences, nextValue)))
            LockSupport.parkNanos(1L);          // 追上了最慢消费者，自旋等待
        this.cachedValue = minSequence;
    }
    this.nextValue = nextSequence;              // 直接赋值，无 CAS
    return nextSequence;
}
```

- `next()` 直接 `this.nextValue = nextSequence`，**不用 CAS**（单线程安全）。
- 仅在需要把游标可见性推给消费者时才 `cursor.setVolatile`（StoreLoad）。
- `publish()` 只是 `cursor.set(sequence)`（ordered write，`StoreStore`）——因为单生产者保证顺序，`isAvailable(sequence)` 只需 `sequence <= cursor.get()`，无需额外的发布标志数组。

### MultiProducerSequencer（CAS + per-slot availability flag）

多个生产者并发时，A 拿到序号 100、B 拿到 101，但 **B 可能比 A 先发布**。消费者不能只看全局 `cursor` 就认为 100 可读，必须确认 100 这格确实被发布了。因此多生产者引入 `availableBuffer`（一个 `int[]`，每格记录"已绕第几圈"的标志）：

```java
// MultiProducerSequencer.java:112-149 (节选) — 用 CAS 分配序号
public long next(int n) {
    do {
        current = cursor.get();
        next = current + n;
        long wrapPoint = next - bufferSize;
        long cachedGatingSequence = gatingSequenceCache.get();
        if (wrapPoint > cachedGatingSequence || cachedGatingSequence > current) {
            long gatingSequence = Util.getMinimumSequence(gatingSequences, current);
            if (wrapPoint > gatingSequence) { LockSupport.parkNanos(1); continue; }
            gatingSequenceCache.set(gatingSequence);
        } else if (cursor.compareAndSet(current, next)) {  // CAS
            break;
        }
    } while (true);
    return next;
}
```

```java
// MultiProducerSequencer.java:253-273 — 发布时标记该格可用，消费者 volatile 读确认
private void setAvailable(final long sequence) {
    setAvailableBufferValue(calculateIndex(sequence), calculateAvailabilityFlag(sequence));
}
private void setAvailableBufferValue(int index, int flag) {
    long bufferAddress = (index * SCALE) + BASE;
    UNSAFE.putOrderedInt(availableBuffer, bufferAddress, flag);  // StoreStore
}
public boolean isAvailable(long sequence) {
    int index = calculateIndex(sequence);
    int flag = calculateAvailabilityFlag(sequence);
    long bufferAddress = (index * SCALE) + BASE;
    return UNSAFE.getIntVolatile(availableBuffer, bufferAddress) == flag;  // volatile 读
}
```

消费者侧因此必须用 `getHighestPublishedSequence(lower, upper)` **扫描连续可用的最高序号**，跳过那些已被 CAS 分配但尚未发布的格子：

```java
// MultiProducerSequencer.java:277-288
public long getHighestPublishedSequence(long lowerBound, long availableSequence) {
    for (long sequence = lowerBound; sequence <= availableSequence; sequence++)
        if (!isAvailable(sequence))
            return sequence - 1;
    return availableSequence;
}
```

**对比结论**：单生产者是 Disruptor 的"快路径"，无 CAS、无 `availableBuffer`、无扫描；多生产者为正确性付出 CAS 竞争 + per-slot 标志 + 连续扫描的代价。能用单生产者就不要上多生产者。

## Memory Barriers in the Publish Path

这是 Disruptor 正确性的核心，也是常被误解的点。关键不在"用 volatile 全屏障"，而在**用最小屏障配平生产者写与消费者读**：

- **生产者写 Event 字段**：普通写（无屏障）。
- **生产者发布**：`publish()` → 多生产者 `UNSAFE.putOrderedInt(availableBuffer)` / 单生产者 `cursor.set()`，均为 **StoreStore**（ordered write）。
- **消费者读发布标志**：`isAvailable()` 用 `getIntVolatile` / 单生产者 `cursor.get()` 用 volatile 读。

由于 `StoreStore`（生产者发布）与随后的 `volatile` 读（消费者）之间存在 **happens-before** 关系（StoreStore 之后的普通写对能看到该 StoreStore 结果的线程可见），消费者一旦看到"该格已发布"，就**一定能读到生产者此前写入的完整 Event 字段**，不会读到半填充的脏数据。这比"每个字段都标 `volatile`"或"发布用 `putLongVolatile` 全屏障"便宜得多——这正是 [JMM](/docs/CS/Java/JDK/Concurrency/JMM.md) 中"发布方写屏障 + 消费方读屏障配平"原则的工程落地。

## Wait Strategies

当消费者追上生产者（或下游消费者追上上游）时，如何等待由 `WaitStrategy` 决定。6 种策略在 **CPU 占用 vs 延迟** 上取舍鲜明：

| 策略 | 等待方式 | CPU 占用 | 延迟 | 适用 |
| --- | --- | --- | --- | --- |
| `BlockingWaitStrategy`（默认） | `ReentrantLock` + `Condition.await/signalAll` | 最低 | 最高 | 吞吐/延迟不敏感、CPU 珍贵 |
| `SleepingWaitStrategy` | 自旋 200 次 → `yield()` → `parkNanos(100ns)` | 低 | 中（静默后有尖刺） | 延迟与 CPU 的折中 |
| `YieldingWaitStrategy` | 自旋 100 次 → `Thread.yield()` | 高（100%） | 低 | 低延迟、有空闲核 |
| `BusySpinWaitStrategy` | 纯自旋 | 最高（占满核） | 最低 | 必须绑核、极致延迟 |
| `TimeoutBlockingWaitStrategy` | 同 Blocking 但带超时 | 低 | 高 | 需要超时语义 |
| `PhasedBackoffWaitStrategy` | 分阶段 spin→yield→park→fallback | 可调 | 可调 | 自适应退避 |

```java
// SleepingWaitStrategy.java:76-96 — 典型的三段式退避
private int applyWaitMethod(final SequenceBarrier barrier, int counter) {
    barrier.checkAlert();
    if (counter > 100)        --counter;            // 先自旋
    else if (counter > 0)  {  --counter; Thread.yield(); }  // 再让出
    else                     LockSupport.parkNanos(sleepTimeNs);  // 最后睡
    return counter;
}
```

注意 `BlockingWaitStrategy` 是唯一真正实现 `signalAllWhenBlocking()` 的策略（其余策略的 `signalAllWhenBlocking()` 为空实现，因为自旋类策略不需要被唤醒，自己会循环重读）。

## Consumption Models (DSL)

`Disruptor` 这个 DSL 类用流畅 API 定义消费拓扑，三种核心模式：

- **多播（Multicast）**：`handleEventsWith(A, B)` —— A、B 各持独立 `Sequence`，**都看到全部事件**，并行消费（如"风控"与"记账"互不依赖）。
- **依赖（Dependency / 流水线）**：`handleEventsWith(A, B).then(C)` —— C 的 `SequenceBarrier` 跟踪 A、B 两者的 `Sequence`，**必须等 A、B 都处理完才处理**，形成 `A,B → C` 的 DAG。
- **竞争（Competition / Work Pool）**：`handleEventsWithWorkerPool(w1, w2)` —— 通过 `WorkerPool` + `WorkProcessor`，**一个事件只被池中一个 worker 处理**（如"一组等价消费者分摊负载"），区别于多播的"每个都处理"。

### Batch Processing: the BatchEventProcessor Loop

`BatchEventProcessor` 是 `handleEventsWith` 背后的消费者线程，其核心是**一次等待、批量处理**：

```java
// BatchEventProcessor.java:150-172 (节选)
while (true) {
    final long availableSequence = sequenceBarrier.waitFor(nextSequence);  // 等高水位
    while (nextSequence <= availableSequence) {                            // 一次性处理中间所有事件
        event = dataProvider.get(nextSequence);
        eventHandler.onEvent(event, nextSequence, nextSequence == availableSequence); // 仅最后一个是 endOfBatch
        nextSequence++;
    }
    sequence.set(availableSequence);   // 批量结束后一次性推进自己的进度
}
```

`endOfBatch` 参数让业务方在批量末尾做聚合/flush，是 Disruptor 高吞吐的关键之一（减少每事件的边界检查与方法调用）。`ProcessingSequenceBarrier.waitFor` 在委派 `WaitStrategy` 后，还会调用 `sequencer.getHighestPublishedSequence` 做多生产者场景下的连续可用性确认：

```java
// ProcessingSequenceBarrier.java:50-64
public long waitFor(final long sequence) {
    checkAlert();
    long availableSequence = waitStrategy.waitFor(sequence, cursorSequence, dependentSequence, this);
    if (availableSequence < sequence) return availableSequence;
    return sequencer.getHighestPublishedSequence(sequence, availableSequence);  // 多生产者必须
}
```

## End-to-End Publish-Consume Flow

完整一次事件生命周期：

1. **生产者申请序号**：`ringBuffer.next()` → `Sequencer.next()`，单生产者直接推进、多生产者 CAS 竞争。
2. **生产者填充 Event**：`ringBuffer.get(sequence)` 拿到预分配对象，修改其字段（普通写）。
3. **生产者发布**：`ringBuffer.publish(sequence)` → `Sequencer.publish()`，用 StoreStore 屏障标记该格可用并 `signalAllWhenBlocking()` 唤醒阻塞消费者。
4. **消费者等待**：`BatchEventProcessor` 的 `sequenceBarrier.waitFor(nextSequence)` 通过 `WaitStrategy` 等到高水位，并经 `getHighestPublishedSequence` 确认连续可用。
5. **消费者批量处理**：从 `nextSequence` 循环到 `availableSequence`，逐个 `onEvent(...)`，末尾 `endOfBatch=true`。
6. **消费者推进进度**：`sequence.set(availableSequence)`（ordered write），该 `Sequence` 同时作为下游消费者的 gating 依赖与最慢消费者水位，供生产者判断是否会覆盖未消费数据（`wrapPoint > minSequence` 时阻塞）。

## Disruptor vs java.util.concurrent Queues

Disruptor 之所以能碾压标准库队列，根源在它逐一消除了后者的瓶颈：

| 维度 | `ArrayBlockingQueue` | `LinkedBlockingQueue` | `Disruptor` |
| --- | --- | --- | --- |
| 存储结构 | 数组（含 `takeIndex/putIndex/count` 三个 volatile 同缓存行 → **伪共享**） | 链表（每个节点独立对象 → **GC 压力、cache miss**） | 预分配环形数组（**零 GC、缓存友好**） |
| 并发控制 | `ReentrantLock` + `Condition`（**锁竞争、上下文切换**） | 两把锁（生产者/消费者各一把） | **无锁**：CAS + `Sequence` + 内存屏障 |
| 进度跟踪 | 单个 `count` 变量 | `count`（原子） | 每个线程独立 `Sequence`，无共享写竞争 |
| 消费粒度 | 一次取一个 | 一次取一个 | **批量消费**（一次 `waitFor` 处理整批） |
| 伪共享 | 严重（三变量同缓存行） | 节点级，仍存在 | 手工缓存行填充彻底消除 |
| 典型吞吐 | 基准 1x | ~1x | 高 **1-2 个数量级**（视场景） |

标准队列的瓶颈恰恰分布在 Disruptor 逐点优化之处：锁带来上下文切换与竞争、链表带来 GC 与缓存未命中、共享 `count` 与 `index` 带来伪共享、单条出队无法摊薄批量开销。

## Performance Characteristics

LMAX 在其生产环境（早期测试，详见 Martin Fowler 的架构剖析）报告 Disruptor 可达约 **600 万订单/秒** 级别吞吐，p99 延迟在微秒级——但这是特定硬件与场景下的数据，不应作为普适承诺。工程上更稳妥的结论是：**在"多生产者/消费者、事件短生命周期、吞吐或延迟敏感"的场景下，Disruptor 通常比 `BlockingQueue` 高 1~2 个数量级**。典型落地：

- **金融交易系统**（LMAX 本身）：订单撮合流水线。
- **高性能日志**：Log4j 2 的 `AsyncLogger` 底层即基于 Disruptor。
- **复杂事件处理（CEP）/ 实时流计算**、系统内模块间的高性能异步解耦。

## When Not to Use

- **长生命周期数据**：Disruptor 适合瞬时、突发的事件流；若单事件处理极久或数据需长期驻留，RingBuffer 会迅速填满、反压生产者。
- **大 Event × 大 buffer 的内存占用**：Event 对象在初始化时全部预分配，`bufferSize × sizeof(Event)` 常驻堆外/堆内，buffer 过大或 Event 过大都会吃内存。
- **简单单消费者场景**：若只有一个生产者一个消费者、吞吐要求不高，标准 `BlockingQueue` 更简单、可读性更好，Disruptor 的复杂度不划算。

## Links

- [Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
- [volatile](/docs/CS/Java/JDK/Concurrency/volatile.md)
- [JMM](/docs/CS/Java/JDK/Concurrency/JMM.md)
- [Queue](/docs/CS/Java/JDK/Collection/Queue.md)

## References

1. [LMAX-Exchange/disruptor @ 3.4.4 (源码基线)](https://github.com/LMAX-Exchange/disruptor/tree/3.4.4)
2. [Disruptor 官方文档](https://lmax-exchange.github.io/disruptor/)
3. [Martin Fowler, "The LMAX Architecture"](https://martinfowler.com/articles/lmax.html)
4. [美团技术团队《高性能队列——Disruptor》](https://tech.meituan.com/2016/11/18/disruptor.html)
