## Introduction

ReentrantLock 实现了 [Lock](/docs/CS/Java/JDK/Concurrency/Lock.md)，提供与 [synchronized](/docs/CS/Java/JDK/Concurrency/synchronized.md) 相同的互斥与内存可见性（memory visibility）保证。获取 ReentrantLock 的内存语义等同于进入 synchronized 块，释放它的内存语义等同于退出 synchronized 块。与 synchronized 一样，它是可重入的：已经持有该锁的线程可以再次获取，每次嵌套获取使重入计数加一，每次释放使其减一。

**为什么需要一个看起来如此接近内置锁的新锁？**

内置锁在多数场景下都能工作，但存在功能层面的限制——无法中断一个阻塞在等锁上的线程，无法在不愿意无限等待的前提下尝试加锁，也无法在与获取锁不同的词法作用域中释放锁。ReentrantLock 提供了带超时、可轮询、可中断的获取方式以及多个可绑定的 `Condition` 对象，代价是必须在 `finally` 块中显式调用 `unlock()`。标准写法如下：

```java
class X {
  private final ReentrantLock lock = new ReentrantLock();
  public void m() {
    lock.lock();                 // acquire, block until available
    try {
      // ... method body
    } finally {
      lock.unlock();             // always first statement in finally
    }
  }
}
```

ReentrantLock 允许同一线程最多递归持有 `Integer.MAX_VALUE`（2147483647）次；超过该上限时，锁方法会抛出 `Error`。反序列化得到的锁始终处于未加锁状态。

## Constructors

```java
public ReentrantLock()              // equivalent to ReentrantLock(false) — nonfair
public ReentrantLock(boolean fair)  // fair=true => FIFO under contention
```

公平性标志**仅**影响发生争用时的获取顺序。无超时的 `tryLock()` 无论是否公平都直接插队抢锁，而且公平并不意味着公平的**调度**——持有锁的线程仍可能被操作系统抢占。

## lock

在 **JDK 25** 中，获取路径围绕 AQS 于 2024 年节点类型化重构引入的 `initialTryLock()` 钩子进行了重组。每个公开的获取方法都先做一次快速预判，失败后才回落到 AQS 队列：

```java
// Sync
final void lock() {
    if (!initialTryLock())
        acquire(1);
}
```

`initialTryLock()` 是唯一处理「快速 CAS + 可重入」的地方；排队路径所使用的 `tryAcquire` 相应地更简单：

```java
// NonfairSync
final boolean initialTryLock() {
    Thread current = Thread.currentThread();
    if (compareAndSetState(0, 1)) {        // first attempt is unguarded (barge)
        setExclusiveOwnerThread(current);
        return true;
    } else if (getExclusiveOwnerThread() == current) {
        int c = getState() + 1;
        if (c < 0) throw new Error("Maximum lock count exceeded");
        setState(c);                       // reentrant: bump hold count
        return true;
    }
    return false;
}

// NonfairSync.tryAcquire (queued fallback)
protected final boolean tryAcquire(int acquires) {
    if (getState() == 0 && compareAndSetState(0, acquires)) {
        setExclusiveOwnerThread(Thread.currentThread());
        return true;
    }
    return false;                          // reentrancy already handled above
}
```

### FairSync#tryAcquire

公平版本在已有线程排队时会拒绝抢锁——它在执行 CAS 之前先检查 `hasQueuedPredecessors()`：

```java
// FairSync
final boolean initialTryLock() {
    Thread current = Thread.currentThread();
    int c = getState();
    if (c == 0) {
        if (!hasQueuedThreads() && compareAndSetState(0, 1)) {
            setExclusiveOwnerThread(current);
            return true;
        }
    } else if (getExclusiveOwnerThread() == current) {
        if (++c < 0) throw new Error("Maximum lock count exceeded");
        setState(c);
        return true;
    }
    return false;
}

protected final boolean tryAcquire(int acquires) {
    if (getState() == 0 && !hasQueuedPredecessors() &&
        compareAndSetState(0, acquires)) {
        setExclusiveOwnerThread(Thread.currentThread());
        return true;
    }
    return false;
}
```

参见 [hasQueuedPredecessors](/docs/CS/Java/JDK/Concurrency/AQS.md?id=hasqueuedpredecessors)

## unlock

`unlock()` 就是 `sync.release(1)`；真正的工作在 `tryRelease` 中——它递减重入计数，只有当计数降到 0 时才清除持有者：

```java
protected final boolean tryRelease(int releases) {
    int c = getState() - releases;
    if (getExclusiveOwnerThread() != Thread.currentThread())
        throw new IllegalMonitorStateException();
    boolean free = (c == 0);
    if (free)
        setExclusiveOwnerThread(null);
    setState(c);
    return free;
}
```

注意其中的持有者校验：释放一把自己并未持有的锁会抛出 `IllegalMonitorStateException`，与释放一个并不属于自己的 monitor 完全一致。

## lockInterruptibly

可中断的获取方式：若调用线程已处于中断状态则立即退出，否则先做同样的 `initialTryLock` 预判，再走 `acquireInterruptibly`——后者在队列中挂起时仍能响应中断。

```java
public void lockInterruptibly() throws InterruptedException {
    if (Thread.interrupted())
        throw new InterruptedException();
    if (!initialTryLock())
        acquireInterruptibly(1);
}
```

## tryLock

无超时的 `tryLock()` 就是一个纯粹的 `initialTryLock()`——它从不入队、从不阻塞；只有当锁在该时刻恰好空闲（包括可重入命中）时才会成功。即使在公平锁上，它也**无视公平性**。

```java
public boolean tryLock() {
    return sync.tryLock();   // = initialTryLock()
}
```

## tryLock with timeout

带超时的获取方式：先检查中断状态，然后要么立即抢到锁，要么借助 AQS 的 `tryAcquireNanos` 与截止时间赛跑。超时会返回 `false`，被中断则抛出 `InterruptedException`。

```java
public boolean tryLock(long timeout, TimeUnit unit) throws InterruptedException {
    return sync.tryLockNanos(unit.toNanos(timeout));
}

// Sync.tryLockNanos
final boolean tryLockNanos(long nanos) throws InterruptedException {
    if (Thread.interrupted())
        throw new InterruptedException();
    return initialTryLock() || tryAcquireNanos(1, nanos);
}
```

正是这一原语让*基于概率的死锁规避*成为可能：线程不必陷入无法挽回的无限阻塞，而是在超时后主动退出并回卷自己已持有的锁。

## Monitoring API

除 `Lock` 接口之外，ReentrantLock 还暴露了一批便于调试和监控的观测方法。它们*不可*用于控制流程，只用于检查：

| 方法 | 含义 |
| --- | --- |
| `int getHoldCount()` | 当前线程的重入次数（未持有时为 0） |
| `boolean isHeldByCurrentThread()` | 当前线程是否持有该锁 |
| `boolean isLocked()` | 是否有任意线程持有该锁（`state != 0`） |
| `boolean isFair()` | 该锁创建时是否指定了公平模式 |
| `boolean hasQueuedThreads()` | 当前是否有线程正在排队等待 |
| `int getQueueLength()` | 等待线程数量的估计值 |
| `boolean hasWaiters(Condition c)` | 是否有线程正等待在条件 `c` 上 |
| `int getWaitQueueLength(Condition c)` | 等待在条件 `c` 上的线程数量的估计值 |

这些方法与 AQS 的 protected 查询方法一一对应，也正是某些监控工具能报告「线程阻塞在锁 X 上」的原因——内置的 `synchronized` 并不提供任何等价的内省能力。

## Memory Semantics

ReentrantLock 的内存语义契约是明确写明的：

- `lock()`、`lockInterruptibly()`、成功的 `tryLock*()` → 对锁状态的一次*易失读（volatile read）*。上一个持有者在 `unlock()` 之前所做的任何写入，对获取者都是可见的（happens-before）。
- `unlock()` → 一次*易失写（volatile write）*。它把临界区内发生的所有写入发布给后续的获取者。

这被刻意设计成与进入/退出 `synchronized` 块完全一致，因此二者互换不会改变可见性——差异只在于*获取方式*（超时 / 轮询 / 可中断 / 多条件）。

## FairSync vs NonFairSync

两者唯一的行为差异在于：对空闲锁执行 CAS 允许发生在哪个位置。

| | `initialTryLock`（锁空闲） | `tryAcquire`（排队中） |
| --- | --- | --- |
| **非公平** | 无条件 CAS——直接越过队列插队 | 仅当 `state == 0` 时才 CAS |
| **公平** | 仅当 `!hasQueuedThreads()` 时 CAS | 仅当 `!hasQueuedPredecessors()` 时 CAS |

非公平模式有两个插队点（`lock()` 中的初始 CAS，以及 `tryAcquire` 中的 `state==0` 判断）；公平模式则始终让位于队首。公平锁能降低延迟抖动、避免饥饿，但在高争用下通常*更慢*，因为即便在最常见的无争用路径上也要付出队列开销。

## ReentrantLock vs synchronized

| | ReentrantLock | synchronized |
| --- | --- | --- |
| 可重入 | 是 | 是 |
| 公平顺序 | 可选（`fair=true`） | 否（非公平） |
| 可中断获取 | `lockInterruptibly` | 否 |
| 超时 / 轮询获取 | `tryLock(timeout)` / `tryLock()` | 否 |
| 多条件 | 多个 `newCondition()` | 单组等待/通知机制 |
| 内省能力 | 重入次数、队列长度、等待者 | 无 |
| 释放方式 | 在 `finally` 中显式 `unlock()` | 退出作用域或抛异常时自动释放 |
| 实现 | Java（`Sync` + AQS） | JVM（`ObjectMonitor`，C++） |

ReentrantLock 是一种*互斥*（exclusive）锁——它**没有共享/读模式**；后者的角色属于 [ReadWriteLock](/docs/CS/Java/JDK/Concurrency/ReadWriteLock.md) 和 [StampedLock](/docs/CS/Java/JDK/Concurrency/StampedLock.md)。默认优先选 `synchronized`；只有在需要上述某项高级特性时才改用 `ReentrantLock`。

## Summary

ReentrantLock 是显式锁的主力工具：与 `synchronized` 具有相同的互斥语义和内存语义，同时扩展出带超时、可轮询、可中断的获取方式以及多条件。在 JDK 25 中，它的快速路径是叠加在 AQS 队列之上的 `initialTryLock()` 预判（快速 CAS + 可重入）；`unlock()` 则只是一次重入计数递减，只有归零时才真正释放所有权。仅当需要高级获取选项或监控 API 时，才选择它而非 `synchronized`。

## Links

- [AQS](/docs/CS/Java/JDK/Concurrency/AQS.md)
- [Lock](/docs/CS/Java/JDK/Concurrency/Lock.md)
- [ReadWriteLock](/docs/CS/Java/JDK/Concurrency/ReadWriteLock.md)
- [StampedLock](/docs/CS/Java/JDK/Concurrency/StampedLock.md)
- [Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
- [synchronized](/docs/CS/Java/JDK/Concurrency/synchronized.md)
