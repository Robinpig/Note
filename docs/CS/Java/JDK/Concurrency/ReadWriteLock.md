# ReadWriteLock

## Introduction

A ReadWriteLock maintains a pair of associated locks, one for read-only operations and one for writing. The read lock may be held simultaneously by multiple reader threads, so long as there are no writers. The write lock is exclusive.

All ReadWriteLock implementations must guarantee that the memory synchronization effects of writeLock operations (as specified in the Lock interface) also hold with respect to the associated readLock. That is, a thread successfully acquiring the read lock will see all updates made upon previous release of the write lock.
A read-write lock allows for a greater level of concurrency in accessing shared data than that permitted by a mutual exclusion lock. It exploits the fact that while only a single thread at a time (a writer thread) can modify the shared data, in many cases any number of threads can concurrently read the data (hence reader threads). In theory, the increase in concurrency permitted by the use of a read-write lock will lead to performance improvements over the use of a mutual exclusion lock. In practice this increase in concurrency will only be fully realized on a multi-processor, and then only if the access patterns for the shared data are suitable.
Whether or not a read-write lock will improve performance over the use of a mutual exclusion lock depends on the frequency that the data is read compared to being modified, the duration of the read and write operations, and the contention for the data - that is, the number of threads that will try to read or write the data at the same time. For example, a collection that is initially populated with data and thereafter infrequently modified, while being frequently searched (such as a directory of some kind) is an ideal candidate for the use of a read-write lock. However, if updates become frequent then the data spends most of its time being exclusively locked and there is little, if any increase in concurrency. Further, if the read operations are too short the overhead of the read-write lock implementation (which is inherently more complex than a mutual exclusion lock) can dominate the execution cost, particularly as many read-write lock implementations still serialize all threads through a small section of code. Ultimately, only profiling and measurement will establish whether the use of a read-write lock is suitable for your application.
Although the basic operation of a read-write lock is straight-forward, there are many policy decisions that an implementation must make, which may affect the effectiveness of the read-write lock in a given application. Examples of these policies include:

1. Determining whether to grant the read lock or the write lock, when both readers and writers are waiting, at the time that a writer releases the write lock. Writer preference is common, as writes are expected to be short and infrequent. Reader preference is less common as it can lead to lengthy delays for a write if the readers are frequent and long-lived as expected. Fair, or "in-order" implementations are also possible.
2. Determining whether readers that request the read lock while a reader is active and a writer is waiting, are granted the read lock. Preference to the reader can delay the writer indefinitely, while preference to the writer can reduce the potential for concurrency.
3. Determining whether the locks are reentrant: can a thread with the write lock reacquire it? Can it acquire a read lock while holding the write lock? Is the read lock itself reentrant?
4. Can the write lock be downgraded to a read lock without allowing an intervening writer? Can a read lock be upgraded to a write lock, in preference to other waiting readers or writers?

You should consider all of these things when evaluating the suitability of a given implementation for your application.

```java
public interface ReadWriteLock {
    // Returns the lock used for reading.
    Lock readLock();

    // Returns the lock used for writing.
    Lock writeLock();
}
```



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



tryAcquireShared Walkthrough:
1. If write lock held by another thread, fail.
2. Otherwise, this thread is eligible for lock wrt state, so ask if it should block because of queue policy. If not, try to grant by CASing state and updating count. Note that step does not check for reentrant acquires, which is postponed to full version to avoid having to check hold count in the more typical non-reentrant case. If step 2 fails either because thread apparently not eligible or CAS fails or count saturated, chain to version with full retry loop.

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

As a heuristic to avoid indefinite writer starvation, block if the thread that momentarily appears to be head of queue, if one exists, is a waiting writer.  This is only a probabilistic effect since a new reader will not block if there is a waiting writer behind other enabled readers that have not yet drained from the queue.

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

tryAcquire Walkthrough:

1. If read count nonzero or write count nonzero and owner is a different thread, fail.
2. If count would saturate, fail. (This can only happen if count is already nonzero.)
3. Otherwise, this thread is eligible for lock if it is either a reentrant acquire or queue policy allows it. If so, update state and set owner.

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
writerShouldBlock:
- FairLock will invoke hasQueuedPredecessors
- NonFairLock always return false



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

if nextc still > 0, return fase and not invoke [doReleaseShared]() to wake up next waiter

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



## tryLock





## Summary

|      | ReadLock                                                | WriteLock                             |
| ---- | ------------------------------------------------------- | ------------------------------------- |
|      | ReadLock will block WriteLock(unless writeLock is next) | WriteLock block readLock(unless self) |
|      |                                                         |                                       |
|      |                                                         |                                       |



## Reference



1. [](https://www.jianshu.com/p/c4af8c70ff99)



