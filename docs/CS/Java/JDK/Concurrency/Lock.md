## Introduction

Lock 接口定义了一系列抽象的加锁操作。
不同于语言内置（intrinsic）加锁，Lock 提供无条件、轮询、定时、可中断等多种获取锁的方式，
且所有加锁与解锁操作都是显式的。
Lock 的实现必须与内置锁提供相同的内存可见性（memory visibility）语义，
但在加锁语义、调度算法、顺序保证和性能特征上可以有所不同。



## Lock
Lock 的实现提供了比使用 [synchronized](/docs/CS/Java/JDK/Concurrency/synchronized.md) 方法和语句更丰富的加锁操作。
它允许更灵活的结构设计，可能具备截然不同的特性，并且可以支持多个关联的 Condition 对象。*

锁（Lock）是一种用于控制多个线程对共享资源访问的工具。
通常，锁提供对共享资源的独占访问：同一时刻只有一个线程能获取该锁，而所有对共享资源的访问都要求先获取到该锁。
不过，某些锁可能允许对共享资源的并发访问，例如 ReadWriteLock 的读锁。

使用 synchronized 方法或语句可以访问与每个对象关联的隐式 monitor 锁，但强制所有加锁与解锁都以「块结构」的方式进行：
当获取了多个锁时，必须以相反的顺序释放它们，并且所有锁都必须在获取它们的同一词法作用域内释放。

虽然 synchronized 方法与语句的作用域机制让 monitor 锁的编程变得简单得多，
也有助于避免许多与锁相关的常见编程错误，但有时确实需要以更灵活的方式使用锁。
例如，一些遍历并发访问数据结构的算法需要使用「hand-over-hand」（逐节点）或「chain locking」（链式加锁）：
先获取节点 A 的锁，再获取节点 B 的锁，然后释放 A、获取 C，接着释放 B、获取 D，依此类推。
Lock 接口的实现通过允许在不同作用域中加锁与解锁、并允许以任意顺序获取和释放多个锁，使这类技巧成为可能。



```java
public interface Lock {
    void lock();
    void lockInterruptibly() throws InterruptedException;

    boolean tryLock();
    boolean tryLock(long time, TimeUnit unit) throws InterruptedException;

    void unlock();

    Condition newCondition();
}
```

**自旋锁与队列锁（理解 AQS 队列锁的来由）**：[Ticket / CLH / MCS](/docs/CS/Java/JDK/Concurrency/SpinQueueLocks.md) —— 从「全局热点变量」演进到「每线程本地自旋、O(1) 交接」，AQS 正是 CLH 的阻塞变体。

### Polled and Timed Lock Acquisition

tryLock 提供的定时与轮询获取模式，比无条件获取具备更强的错误恢复能力。
对于内置锁，死锁是致命的——唯一的恢复手段是重启应用，唯一的防御办法是在程序构造上杜绝不一致的加锁顺序。
定时与轮询加锁提供了另一种选择：概率性的死锁规避。

### Interruptible Lock Acquisition

正如定时获取让独占锁可用于限时活动，可中断获取让锁可用于可取消的活动。
一些机制（例如获取内置锁）对中断并不响应。
这些不可中断的阻塞机制让可取消任务的实现变得复杂。
`lockInterruptibly` 方法允许在保持对中断响应的同时尝试获取锁，将其纳入 Lock 接口也避免了再引入一类不可中断的阻塞机制。

可中断获取的标准结构比普通获取略复杂，因为需要两层 try 块。
（如果可中断获取会抛出 InterruptedException，标准的 try-finally 加锁习惯用法仍然适用。）
定时的 `tryLock` 同样响应中断，因此在既需要定时又需要可中断获取时可以使用它。

### Non-block-structured Locking

对于内置锁，加锁与解锁总是成对出现在块结构中——无论控制流如何离开该块，锁总是在获取它的同一基本块中被释放。
自动释放简化了分析并避免了潜在的编码错误，但有时确实需要更灵活的加锁规范。
在 ConcurrentMap 中我们已经看到，降低锁粒度可以提升可扩展性；锁分段（Lock striping）让基于哈希的集合中不同的哈希链使用不同的锁。
这种技巧的一个例子就是 **hand-over-hand locking**（逐节点加锁）或 **lock coupling**（锁耦合）。

### Fairness

ReentrantLock 的构造函数提供两种公平性选项：创建非公平锁（默认）或公平锁。
（*轮询式的 `tryLock` 总是会插队，即便是公平锁也是如此*。）




### Summary of Lock

> ReentrantLock 是一种高级工具，适用于内置加锁不切实际的场景。
> 
> 如果你需要它的高级特性才使用它：
> 定时、轮询或可中断的锁获取，公平排队，或非块结构的加锁。
> 
> **除此之外，优先使用 synchronized。**

[AQS](/docs/CS/Java/JDK/Concurrency/AQS.md)



`Object.wait()` 的问题在于它**强制持有对象的 monitor**。这意味着「进入等待」和「释放锁」被绑定成一个不可分割的动作，
而业务上经常需要「先释放锁去干别的事，回来时再检查条件」。`Condition` 把这两件事拆开：它本身没有锁，
`await()` 的语义是**完全释放关联的那把 `Lock`，等待，被 signal 后重新获取锁再返回**。

```java
Lock lock = new ReentrantLock();
Condition notEmpty = lock.newCondition();
Condition notFull  = lock.newCondition();

lock.lock();
try {
    while (queue.isEmpty()) {
        notEmpty.await();          // 释放 lock + 入条件队列
    }
    // 重新持有 lock 继续
} finally {
    lock.unlock();
}
```

七个工作方法，构成两组对称：

| 等待侧 | 唤醒侧 | 说明 |
| --- | --- | --- |
| `await()` | `signal()` | 可中断；返回时**已持有锁** |
| `awaitNanos(nanos)` | | 返回剩余纳秒数，<= 0 表示超时 |
| `await(time, unit)` | | 返回 `boolean`，`false` 表示超时 |
| `awaitUntil(deadline)` | | 绝对时间截止，返回 `boolean` |
| `awaitUninterruptibly()` | | 不可中断，返回时**不重设中断标志** |

三条必须记住的规则：

1. **必须用 `while` 而不是 `if` 检查条件**。`await` 返回不代表条件成立，只代表有人 signal 了；
   signal 存在「先唤醒 A，但 A 检查时条件已被 B 消费」的窗口，所以必须循环复检。
2. **`await()` 会抛 `InterruptedException`，且中断状态被清除**。这是它与 `Object.wait` 的
   [等价语义](/docs/CS/Java/JDK/Concurrency/Thread.md?id=wait)，不是缺陷；`awaitUninterruptibly()` 不抛异常也不清标志。
3. **必须在 `lock()` 之后、`unlock()` 之前调用**。`Condition` 关联的是创建它的那把 `Lock`，
   在其它线程调用 `signal()` 时，被唤醒的线程同样需要重新竞争这把锁，所以它只能被持锁者调用。

### Multiple Conditions

一个 `Lock` 可以 `newCondition()` 出任意多个 `Condition`，这是它相对 `Object` 的最大优势。
`Object.wait/notifyAll` 只有一个等待队列，唤醒后所有竞争者必须重新检查同一个条件谓词，唤醒无关的线程是纯浪费；
多个 `Condition` 则可以让生产者唤醒消费者、消费者唤醒生产者，互不干扰：

```java
// BoundedBuffer 的标准写法
notFull.await();      // 队列满，只等消费者腾出位置
item = queue.take();
notEmpty.signal();    // 有新元素，唤醒消费者
```

`signal()` 只唤醒**队列中第一个**等待者；`signalAll()` 唤醒全部。
多个 `Condition` 的正确用法是能用 `signal()` 就不用 `signalAll()`，
因为惊群唤醒会让所有竞争者被唤醒后立刻因条件不成立而重新入队，白白损失唤醒与上下文切换。

条件队列与同步队列是两套独立的队列：`Condition.await()` 先完全释放锁再进条件队列，
`signal()` 把节点从条件队列移到同步队列末尾，线程再在那里竞争锁。
这个「先脱离锁、再排队、再竞争锁」的两段式，是 `Condition` 与 `Object.wait` 在实现上的根本分野，
也是它能支持多个条件谓词的原因。

### Summary of Condition



| 维度 | `Object` | `Condition` |
| ------------- | --------------------- | ---------------------------------- |
| 方法 | `wait` / `notify` | `await` / `signal` |
| 依赖 | `synchronized` | AQS |
| 实现语言 | C++ | Java |
| 可中断性 | 只能整体中断 | 精确到单个等待条件 |
| 等待超时 | 不支持（只有 `wait(timeout)`） | 可指定未来时刻（`await(time, unit)`） |
| 数量 | 每个对象只有一个等待集 | 一个 Lock 可有多个条件谓词 |
| 睡眠语义 | 不支持（必须持锁） | 支持（`await` 会完全释放锁） |





## LockSupport

**LockSupport 调用 [Unsafe](/docs/CS/Java/JDK/Basic/unsafe.md)**。



### parker

除非许可（permit）可用，否则禁用当前线程的线程调度。

如果许可可用，则将其消费并立即返回；否则当前线程将被禁用调度并陷入休眠，直到以下三件事之一发生：
- 其他线程以当前线程为目标调用了 unpark；或
- 其他线程中断了当前线程；或
- 调用因故（即无原因地）伪唤醒而返回。

该方法不会报告是哪一种原因导致返回。调用方应当重新检查最初导致线程 park 的条件；例如，调用方也可以在返回时查询线程的中断状态。

```java
 public static void park(Object blocker) {
        Thread t = Thread.currentThread();
        setBlocker(t, blocker);
        UNSAFE.park(false, 0L);
        setBlocker(t, null);
    }

private static void setBlocker(Thread t, Object arg) {
    // Even though volatile, hotspot doesn't need a write barrier here.
    UNSAFE.putObject(t, parkBlockerOffset, arg);
    }
```
**示例**：

```
while (!canProceed()) { ... LockSupport.park(this); }
```

如果给定线程的许可尚不可用，则使其可用。
如果该线程因 park 而阻塞，则将其解除阻塞。
否则，保证它下一次对 park 的调用不会阻塞。如果给定线程尚未启动，该操作不保证产生任何效果。
```java
public static void unpark(Thread thread) {
  if (thread != null)
      UNSAFE.unpark(thread);
}
```

### Sample


```java
class FIFOMutex {
    private final AtomicBoolean locked = new AtomicBoolean(false);
    private final Queue<Thread> waiters
      = new ConcurrentLinkedQueue<Thread>();
 
    public void lock() {
      boolean wasInterrupted = false;
      Thread current = Thread.currentThread();
      waiters.add(current);
 
      // Block while not first in queue or cannot acquire lock
      while (waiters.peek() != current ||
             !locked.compareAndSet(false, true)) {
        LockSupport.park(this);
        if (Thread.interrupted()) // ignore interrupts while waiting
          wasInterrupted = true;
      }

      waiters.remove();
      if (wasInterrupted)          // reassert interrupt status on exit
        current.interrupt();
    }
 
    public void unlock() {
      locked.set(false);
      LockSupport.unpark(waiters.peek());
    }
  }
```

## Lock Implementations Panorama

`java.util.concurrent` 提供三类显式锁，加上语言内置的 `synchronized`，构成完整的互斥 / 读写工具箱。选型的优先级是：默认 `synchronized`，需要高级获取语义才上 `ReentrantLock`，读多写少才考虑读写锁，且 `StampedLock` 是 `ReentrantReadWriteLock` 的高吞吐替代而非补充：

| 实现 | 模式 | 公平性 | 中断 / 超时 | 读优化 | 典型用途 |
| --- | --- | --- | --- | --- | --- |
| [synchronized](/docs/CS/Java/JDK/Concurrency/synchronized.md) | 独占 | 无（非公平） | 否 | 否 | 简单临界区，默认首选 |
| [ReentrantLock](/docs/CS/Java/JDK/Concurrency/ReentrantLock.md) | 独占 | 可选 | 是 | 否 | 需要中断 / 超时 / 多条件 / 监控 |
| [ReentrantReadWriteLock](/docs/CS/Java/JDK/Concurrency/ReadWriteLock.md) | 读写 | 可选 | 是 | 是（读共享） | 读多写少 |
| [StampedLock](/docs/CS/Java/JDK/Concurrency/StampedLock.md) | 读写 + 乐观 | 无 | 否 | 是（乐观读） | 读极多、写极少，追求吞吐 |

读写锁的演进与取舍见各专篇；独占锁的底层队列机制统一由 [AQS](/docs/CS/Java/JDK/Concurrency/AQS.md) 支撑。

## Links
- [AQS](/docs/CS/Java/JDK/Concurrency/AQS.md)
- [ReentrantLock](/docs/CS/Java/JDK/Concurrency/ReentrantLock.md)
- [ReadWriteLock](/docs/CS/Java/JDK/Concurrency/ReadWriteLock.md)
- [StampedLock](/docs/CS/Java/JDK/Concurrency/StampedLock.md)
- [SpinQueueLocks](/docs/CS/Java/JDK/Concurrency/SpinQueueLocks.md)
- [synchronized](/docs/CS/Java/JDK/Concurrency/synchronized.md)
