

## Introduction

ReadWriteLock 维护一对关联的锁，一把用于只读操作，一把用于写入。只要没有写者，读锁就可以同时被多个读线程持有；写锁则是独占的。

所有 ReadWriteLock 的实现都必须保证：writeLock 操作的内存同步效果（如 Lock 接口所规定）对关联的 readLock 同样成立。也就是说，成功获取读锁的线程能看到此前写锁释放时所做的全部更新。
与互斥锁相比，读写锁允许以更高的并发度访问共享数据。它利用了这样一个事实：虽然同一时刻只有一个线程（写线程）能修改共享数据，但在很多情况下任意数量的线程都可以并发读取数据（因此称为读线程）。理论上，使用读写锁带来的并发度提升会带来比互斥锁更好的性能；实际上，这种提升只有在多处理器上、且数据共享的访问模式合适时才能充分体现。
读写锁能否比互斥锁带来性能提升，取决于数据被读取相对于被修改的频率、读写操作的持续时间，以及数据竞争程度——即同一时刻尝试读写数据的线程数量。例如，一个先填充数据、之后很少修改却频繁查询（如某种目录）的集合，就是使用读写锁的理想候选。然而，如果更新变得频繁，数据大部分时间都处于独占锁定状态，并发度几乎得不到提升。此外，如果读取操作过短，读写锁实现（本质上比互斥锁更复杂）的开销就会主导执行成本，尤其是许多读写锁实现仍会让所有线程串行地经过一小段代码。归根到底，只有借助性能剖析与实测，才能判断读写锁是否适合你的应用。
尽管读写锁的基本操作很简单，但实现必须做出许多策略决策，这些决策会影响读写锁在特定应用中的效果。这类策略包括：

1. 当读写线程都在等待、且写者释放写锁时，决定授予读锁还是写锁。写者优先很常见，因为写入通常预期短暂且不频繁。读者优先则较少见，因为如果读者频繁且存活时间长，可能导致写者长时间延迟。公平（"in-order"）实现也是可能的。
2. 当读锁已被持有时有写者在等待，此时新请求读锁的读者是否被授予读锁。偏向读者可能让写者无限期延迟，而偏向写者则会降低潜在的并发度。
3. 决定锁是否可重入：持有写锁的线程能否再次获取它？持有写锁时能否获取读锁？读锁本身是否可重入？
4. 写锁能否在不插入写者的情况下降级为读锁？读锁能否优先于其他等待的读者或写者升级为写锁？

在评估某个实现是否适合你的应用时，应当把以上这些都考虑进去。

```java
public interface ReadWriteLock {
    // Returns the lock used for reading.
    Lock readLock();

    // Returns the lock used for writing.
    Lock writeLock();
}
```


读锁与写锁之间的相互作用允许多种可能的实现。ReadWriteLock 的部分实现选项包括”

- **释放偏好（Release preference）**。 
  当写者释放写锁、且读者与写者都在排队时，应当优先给谁——读者、写者，还是先请求的？
- **读者插队（Reader barging）**。 
  如果锁被读者持有但已有写者在等待，新到达的读者是否应立即获得访问权，还是应当排在写者之后？ 
  允许读者插到写者前面能提升并发度，但有饿死写者的风险。
- **可重入（Reentrancy）**。 
  读锁和写锁是否可重入？
- **降级（Downgrading）**。 
  如果某线程持有写锁，它能否在不释放写锁的情况下获取读锁？ 
  这样写者就能「降级」为读锁，同时不让其他写者在此期间修改受保护资源。
- **升级（Upgrading）**。 
  读锁能否优先于其他等待的读者或写者升级为写锁？ 
  大多数读写锁实现都不支持升级，因为没有显式的升级操作很容易导致死锁。 
  （如果两个读者同时尝试升级为写锁，谁都不会释放读锁。）”



## ReentrantReadWriteLock



```java
public class ReentrantReadWriteLock
        implements ReadWriteLock, java.io.Serializable {
    private static final long serialVersionUID = -6992448646407690164L;
    /** Inner class providing readlock */
    private final ReentrantReadWriteLock.ReadLock readerLock;
    /** Inner class providing writelock */
    private final ReentrantReadWriteLock.WriteLock writerLock;
    /** Performs all synchronization mechanics */
    final Sync sync;

    // Creates a new {@code ReentrantReadWriteLock} with default (nonfair) ordering properties.
    public ReentrantReadWriteLock() {
        this(false);
    }

    // Creates a new {@code ReentrantReadWriteLock} with the given fairness policy.
    public ReentrantReadWriteLock(boolean fair) {
        sync = fair ? new FairSync() : new NonfairSync();
        readerLock = new ReadLock(this);
        writerLock = new WriteLock(this);
    }
...
}
```



### Sync

```java
abstract static class Sync extends AbstractQueuedSynchronizer {
    private static final long serialVersionUID = 6317671515068378041L;

    /*
     * Read vs write count extraction constants and functions.
     * Lock state is logically divided into two unsigned shorts:
     * The lower one representing the exclusive (writer) lock hold count,
     * and the upper the shared (reader) hold count.
     */

    static final int SHARED_SHIFT   = 16;
    static final int SHARED_UNIT    = (1 << SHARED_SHIFT);
    static final int MAX_COUNT      = (1 << SHARED_SHIFT) - 1;
    static final int EXCLUSIVE_MASK = (1 << SHARED_SHIFT) - 1;

    /** Returns the number of shared holds represented in count  */
    static int sharedCount(int c)    { return c >>> SHARED_SHIFT; }
    /** Returns the number of exclusive holds represented in count  */
    static int exclusiveCount(int c) { return c & EXCLUSIVE_MASK; }

    /**
     * A counter for per-thread read hold counts.
     * Maintained as a ThreadLocal; cached in cachedHoldCounter
     */
    static final class HoldCounter {
        int count = 0;
        // Use id, not reference, to avoid garbage retention
        final long tid = getThreadId(Thread.currentThread());
    }

    /**
     * ThreadLocal subclass. Easiest to explicitly define for sake
     * of deserialization mechanics.
     */
    static final class ThreadLocalHoldCounter
        extends ThreadLocal<HoldCounter> {
        public HoldCounter initialValue() {
            return new HoldCounter();
        }
    }

    /**
     * The number of reentrant read locks held by current thread.
     * Initialized only in constructor and readObject.
     * Removed whenever a thread's read hold count drops to 0.
     */
    private transient ThreadLocalHoldCounter readHolds;

    /**
     * The hold count of the last thread to successfully acquire
     * readLock. This saves ThreadLocal lookup in the common case
     * where the next thread to release is the last one to
     * acquire. This is non-volatile since it is just used
     * as a heuristic, and would be great for threads to cache.
     *
     * <p>Can outlive the Thread for which it is caching the read
     * hold count, but avoids garbage retention by not retaining a
     * reference to the Thread.
     *
     * <p>Accessed via a benign data race; relies on the memory
     * model's final field and out-of-thin-air guarantees.
     */
    private transient HoldCounter cachedHoldCounter;

    /**
     * firstReader is the first thread to have acquired the read lock.
     * firstReaderHoldCount is firstReader's hold count.
     *
     * <p>More precisely, firstReader is the unique thread that last
     * changed the shared count from 0 to 1, and has not released the
     * read lock since then; null if there is no such thread.
     *
     * <p>Cannot cause garbage retention unless the thread terminated
     * without relinquishing its read locks, since tryReleaseShared
     * sets it to null.
     *
     * <p>Accessed via a benign data race; relies on the memory
     * model's out-of-thin-air guarantees for references.
     *
     * <p>This allows tracking of read holds for uncontended read
     * locks to be very cheap.
     */
    private transient Thread firstReader = null;
    private transient int firstReaderHoldCount;

    Sync() {
        readHolds = new ThreadLocalHoldCounter();
        setState(getState()); // ensures visibility of readHolds
    }
  ...
}
```

## lock

```java
// ReadLock
public void lock() {
    sync.acquireShared(1);
}

// WriteLock
public void lock() {
    sync.acquire(1);
}
```



#### acquireShared



tryAcquireShared 走查：
1. 若写锁被其他线程持有，失败。
2. 否则，本线程在状态层面有资格获取锁，于是询问是否因队列策略而应当阻塞；若否，则通过 CAS 更新状态与计数来尝试授予。注意这一步不检查可重入获取，而是推迟到完整版本，以避免在更常见的非重入情况下检查持有计数。若第 2 步失败（线程明显无资格、CAS 失败或计数饱和），则转入带完整重试循环的版本。

```java
protected final int tryAcquireShared(int unused) {
   Thread current = Thread.currentThread();
    int c = getState();
    if (exclusiveCount(c) != 0 &&
        getExclusiveOwnerThread() != current)
        return -1;
    int r = sharedCount(c);
    if (!readerShouldBlock() &&
        r < MAX_COUNT &&
        compareAndSetState(c, c + SHARED_UNIT)) {
        if (r == 0) {
            firstReader = current;
            firstReaderHoldCount = 1;
        } else if (firstReader == current) {
            firstReaderHoldCount++;
        } else {
            HoldCounter rh = cachedHoldCounter;
            if (rh == null || rh.tid != getThreadId(current))
                cachedHoldCounter = rh = readHolds.get();
            else if (rh.count == 0)
                readHolds.set(rh);
            rh.count++;
        }
        return 1;
    }
    return fullTryAcquireShared(current);
}
```





NonFairLock

作为一种启发式以避免写者无限期饿死：若（存在的）队列头部线程恰好是一个等待中的写者，则阻塞。这只是一个概率性效果，因为若等待中的写者后面还有其他已启用的读者尚未离开队列，新读者并不会被阻塞。

```java
// FairLock
final boolean readerShouldBlock() {
    return hasQueuedPredecessors();
}

// NonFairLock
final boolean readerShouldBlock() {
    return apparentlyFirstQueuedIsExclusive();
}

/**
 * Returns {@code true} if the apparent first queued thread, if one
 * exists, is waiting in exclusive mode.  If this method returns
 * {@code true}, and the current thread is attempting to acquire in
 * shared mode (that is, this method is invoked from {@link
 * #tryAcquireShared}) then it is guaranteed that the current thread
 * is not the first queued thread.  Used only as a heuristic in
 * ReentrantReadWriteLock.
 */
final boolean apparentlyFirstQueuedIsExclusive() {
    Node h, s;
    return (h = head) != null &&
        (s = h.next)  != null &&
        !s.isShared()         &&
        s.thread != null;
}
```



 #### fullTryAcquireShared



```java
/**
 * Full version of acquire for reads, that handles CAS misses
 * and reentrant reads not dealt with in tryAcquireShared.
 */
final int fullTryAcquireShared(Thread current) {
    /*
     * This code is in part redundant with that in
     * tryAcquireShared but is simpler overall by not
     * complicating tryAcquireShared with interactions between
     * retries and lazily reading hold counts.
     */
    HoldCounter rh = null;
    for (;;) {
        int c = getState();
        if (exclusiveCount(c) != 0) {
            if (getExclusiveOwnerThread() != current)
                return -1;
            // else we hold the exclusive lock; blocking here
            // would cause deadlock.
        } else if (readerShouldBlock()) {
            // Make sure we're not acquiring read lock reentrantly
            if (firstReader == current) {
                // assert firstReaderHoldCount > 0;
            } else {
                if (rh == null) {
                    rh = cachedHoldCounter;
                    if (rh == null || rh.tid != getThreadId(current)) {
                        rh = readHolds.get();
                        if (rh.count == 0)
                            readHolds.remove();
                    }
                }
                if (rh.count == 0)
                    return -1;
            }
        }
        if (sharedCount(c) == MAX_COUNT)
            throw new Error("Maximum lock count exceeded");
        if (compareAndSetState(c, c + SHARED_UNIT)) {
            if (sharedCount(c) == 0) {
                firstReader = current;
                firstReaderHoldCount = 1;
            } else if (firstReader == current) {
                firstReaderHoldCount++;
            } else {
                if (rh == null)
                    rh = cachedHoldCounter;
                if (rh == null || rh.tid != getThreadId(current))
                    rh = readHolds.get();
                else if (rh.count == 0)
                    readHolds.set(rh);
                rh.count++;
                cachedHoldCounter = rh; // cache for release
            }
            return 1;
        }
    }
}
```



### tryAcquire

tryAcquire 走查：

1. 若读计数非零，或写计数非零且持有者并非本线程，失败。
2. 若计数将溢出，失败。（这仅在计数已非零时发生。）
3. 否则，若本次为可重入获取，或队列策略允许，则本线程有资格获取锁；若是，则更新状态并设置持有者。

```java
protected final boolean tryAcquire(int acquires) {
    Thread current = Thread.currentThread();
    int c = getState();
    int w = exclusiveCount(c);
    if (c != 0) {
        // (Note: if c != 0 and w == 0 then shared count != 0)
        if (w == 0 || current != getExclusiveOwnerThread())
            return false;
        if (w + exclusiveCount(acquires) > MAX_COUNT)
            throw new Error("Maximum lock count exceeded");
        // Reentrant acquire
        setState(c + acquires);
        return true;
    }
    if (writerShouldBlock() ||
        !compareAndSetState(c, c + acquires))
        return false;
    setExclusiveOwnerThread(current);
    return true;
}
```
writerShouldBlock：
- FairLock 会调用 hasQueuedPredecessors
- NonFairLock 始终返回 false



### unlock

```java
// ReadLock
public void unlock() {
    sync.releaseShared(1);
}

// WriteLock
public void unlock() {
    sync.release(1);
}
```



#### tryReleaseShared

若 nextc 仍 > 0，返回 false 且不会调用 [doReleaseShared]() 来唤醒下一个等待者

```java
protected final boolean tryReleaseShared(int unused) {
    Thread current = Thread.currentThread();
    if (firstReader == current) {
        // assert firstReaderHoldCount > 0;
        if (firstReaderHoldCount == 1)
            firstReader = null;
        else
            firstReaderHoldCount--;
    } else {
        HoldCounter rh = cachedHoldCounter;
        if (rh == null || rh.tid != getThreadId(current))
            rh = readHolds.get();
        int count = rh.count;
        if (count <= 1) {
            readHolds.remove();
            if (count <= 0)
                throw unmatchedUnlockException();
        }
        --rh.count;
    }
    for (;;) {
        int c = getState();
        int nextc = c - SHARED_UNIT;
        if (compareAndSetState(c, nextc))
            // Releasing the read lock has no effect on readers,
            // but it may allow waiting writers to proceed if
            // both read and write locks are now free.
            return nextc == 0;
    }
}
```



#### tryRelease

注意，tryRelease 与 tryAcquire 都可能被 Condition 调用。因此它们的参数中可能同时包含读锁与写锁的持有计数，这些计数会在一次条件等待期间被全部释放，并在 tryAcquire 中重新建立。

```java
protected final boolean tryRelease(int releases) {
    if (!isHeldExclusively())
        throw new IllegalMonitorStateException();
    int nextc = getState() - releases;
    boolean free = exclusiveCount(nextc) == 0;
    if (free)
        setExclusiveOwnerThread(null);
    setState(nextc);
    return free;
}
```



## tryLock

`ReentrantReadWriteLock` 的 `tryLock` 有一个容易踩的坑：**读锁的 `tryLock` 和写锁的 `tryLock` 语义不同**。
读锁的 `tryLock()` **允许插队**——当有写锁在等待时，新来的读锁仍可能立即拿到锁；
写锁的 `tryLock()` 则完全遵循「现有读者全部让位」的规则，拿不到就是拿不到。

两个实现都是薄封装，真正干活的是 `Sync` 里的方法：

```java
// 读锁侧
public boolean tryLock() {
    return sync.tryReadLock();
}

public boolean tryLock(long timeout, TimeUnit unit) throws InterruptedException {
    return sync.tryAcquireSharedNanos(1, unit.toNanos(timeout));
}

// 写锁侧
public boolean tryLock() {
    return sync.tryWriteLock();
}

public boolean tryLock(long timeout, TimeUnit unit) throws InterruptedException {
    return sync.tryAcquireNanos(1, unit.toNanos(timeout));
}
```

### tryWriteLock

写锁的立即获取实现如下，注意第一行的短路条件：

```java
final boolean tryWriteLock() {
    Thread current = Thread.currentThread();
    long c = getState();
    if (c != 0) {
        int w = exclusiveCount(c);
        if (w == 0 || current != getExclusiveOwnerThread())
            return false;
        if (w == MAX_COUNT)
            throw new Error("Maximum lock count exceeded");
    }
    if (!compareAndSetState(c, c + 1))
        return false;
    setExclusiveOwnerThread(current);
    return true;
}
```

三个要点：

1. **仅当锁完全空闲（`c == 0`）或已被当前线程持有时才继续**。
   `w == 0` 表示状态里只有读锁（有读者但无写者），此时 `tryWriteLock` 返回 false；
2. **重入例外**：若写锁已被当前线程持有（`current == getExclusiveOwnerThread()`），
   仍然允许再加一层重入计数——这与 `ReentrantLock` 的重入语义一致，
   否则一个写锁内嵌套 `lock()` 的方法会自己把自己锁死；
3. **最后 CAS 一次而非独占**。前两步是快速路径上的无锁判断，只有在确定可以获取后才做一次
   `compareAndSetState`，把并发竞争收敛到单条原子指令上。

### Timeout Variants

带超时的两个变体直接复用 AQS 的模板方法（见 [AQS](/docs/CS/Java/JDK/Concurrency/AQS.md)），
这正是 AQS 把「独占/共享获取」抽象成两套钩子的价值：

```java
// 写锁：独占路径
return sync.tryAcquireNanos(1, unit.toNanos(timeout));
// 读锁：共享路径
return sync.tryAcquireSharedNanos(1, unit.toNanos(timeout));
```

读锁走的是 `tryAcquireSharedNanos`，与 [Semaphore](/docs/CS/Java/JDK/Concurrency/Semaphore.md)
`tryAcquire` 是同一套机制。所以读锁的「获取一个」在语义上就是**获取一个共享许可**——
这也是 `ReadWriteLock` 与 `Semaphore` 的抽象亲缘关系：前者是后者的特化，只是许可数固定为 1。

### Usage

`tryLock` 的典型用途是**在拿不到时立刻走降级路径**，而不是阻塞等待：

```java
if (lock.tryWriteLock()) {
    try {
        rebuildCache();
    } finally {
        unlock();
    }
} else {
    serveStaleCache();      // 有其它线程在写，直接读旧值，不排队
}
```

在缓存/配置这类「读多写少且允许短暂不一致」的场景里，这比排队等写锁更划算：
写锁的持有时间往往远大于一次读，让读者绕开等待能显著改善尾延迟。
反过来，在必须保证一致性的地方不要用 `tryLock` 静默降级——正确做法是 `lock()` 或带超时版本，
让失败以异常形式暴露。

需要注意 `tryLock()` **不响应中断也不抛 `InterruptedException`**（只在调用者已持有锁时才抛），
所以它对「等待可被中断」的需求无能为力；那时应该用
`tryLock(timeout, unit)`，它会抛 `InterruptedException`。


## Summary


|      | ReadLock                | WriteLock                                                    |
| ---- | ----------------------- | ------------------------------------------------------------ |
| Lock | 读锁允许读锁 | 写锁阻塞读锁和写锁（除非自身 W → R） |
| Condition |         不支持      |   支持    |
| 升级/降级    |         不支持升级                |        支持降级 |



读写锁是一种性能优化手段，目的是在特定场景下提供更高的并发度。
实践中，在多用处理器的系统上，读写锁能够提升那些频繁读取、基本只读的数据结构的性能；
但在其他条件下，由于其更高的复杂度，它表现反而略逊于独占锁。
读写锁是否在特定场景下带来改善，最好通过性能剖析来判断；由于 ReadWriteLock 在读、写两部分都使用 Lock，
若剖析表明读写锁并无收益，将其替换为独占锁也相对容易。


## Links

- [AQS](/docs/CS/Java/JDK/Concurrency/AQS.md)
- [Atomic](/docs/CS/Java/JDK/Concurrency/Atomic.md)
- [Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
- [CountDownLatch](/docs/CS/Java/JDK/Concurrency/CountDownLatch.md)
- [CyclicBarrier](/docs/CS/Java/JDK/Concurrency/CyclicBarrier.md)
- [Exchanger](/docs/CS/Java/JDK/Concurrency/Exchanger.md)

## References



1. [](https://www.jianshu.com/p/c4af8c70ff99)
