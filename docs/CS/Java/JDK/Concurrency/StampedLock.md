## Introduction

A capability-based lock with three modes for controlling read/write access. 
**The state of a StampedLock consists of a version and mode**. 
Lock acquisition methods return a stamp that represents and controls access with respect to a lock state; 
"try" versions of these methods may instead return the special value zero to represent failure to acquire access. 
Lock release and conversion methods require stamps as arguments, and fail if they do not match the state of the lock. 

The three modes are:

Writing. Method writeLock possibly blocks waiting for exclusive access, returning a stamp that can be used in method unlockWrite to release the lock. 
Untimed and timed versions of tryWriteLock are also provided.
When the lock is held in write mode, no read locks may be obtained, and all optimistic read validations will fail.

Reading. Method readLock possibly blocks waiting for non-exclusive access, returning a stamp that can be used in method unlockRead to release the lock. 
Untimed and timed versions of tryReadLock are also provided.

Optimistic Reading. Method tryOptimisticRead returns a non-zero stamp only if the lock is not currently held in write mode. 
Method validate returns true if the lock has not been acquired in write mode since obtaining a given stamp. 
This mode can be thought of as an extremely weak version of a read-lock, that can be broken by a writer at any time. 
The use of optimistic mode for short read-only code segments often reduces contention and improves throughput. 
However, its use is inherently fragile. Optimistic read sections should only read fields and hold them in local variables for later use after validation. 
Fields read while in optimistic mode may be wildly inconsistent, so usage applies only when you are familiar enough with data representations to check consistency and/or repeatedly invoke method `validate()`. 

For example, such steps are typically required when first reading an object or array reference, and then accessing one of its fields, elements or methods.
This class also supports methods that conditionally provide conversions across the three modes. 
For example, method tryConvertToWriteLock attempts to "upgrade" a mode, returning a valid write stamp if 

1. already in writing mode 
2. in reading mode and there are no other readers or 
3. in optimistic mode and the lock is available. 

The forms of these methods are designed to help reduce some of the code bloat that otherwise occurs in retry-based designs.

StampedLocks are designed for use as internal utilities in the development of thread-safe components. 
Their use relies on knowledge of the internal properties of the data, objects, and methods they are protecting. 
They are not reentrant, so locked bodies should not call other unknown methods that may try to re-acquire locks (although you may pass a stamp to other methods that can use or convert it). 
The use of read lock modes relies on the associated code sections being side-effect-free. 
Unvalidated optimistic read sections cannot call methods that are not known to tolerate potential inconsistencies.
Stamps use finite representations, and are not cryptographically secure (i.e., a valid stamp may be guessable).
Stamp values may recycle after (no sooner than) one year of continuous operation.
A stamp held without use or validation for longer than this period may fail to validate correctly.
StampedLocks are serializable, but always deserialize into initial unlocked state, so they are not useful for remote locking.

The scheduling policy of StampedLock does not consistently prefer readers over writers or vice versa. 
All "try" methods are best-effort and do not necessarily conform to any scheduling or fairness policy. 
A zero return from any "try" method for acquiring or converting locks does not carry any information about the state of the lock; a subsequent invocation may succeed.
Because it supports coordinated usage across multiple lock modes, this class does not directly implement the Lock or ReadWriteLock interfaces.
However, a StampedLock may be viewed asReadLock(), asWriteLock(), or asReadWriteLock() in applications requiring only the associated set of functionality.
Sample Usage. The following illustrates some usage idioms in a class that maintains simple two-dimensional points. 
The sample code illustrates some try/catch conventions even though they are not strictly needed here because no exceptions can occur in their bodies.



## Sample

Sample Usage. The following illustrates some usage idioms in a class that maintains simple two-dimensional points.
The sample code illustrates some try/catch conventions even though they are not strictly needed here because no exceptions can occur in their bodies. 

```java
class Point {
   private double x, y;
   private final StampedLock sl = new StampedLock();

   void move(double deltaX, double deltaY) { // an exclusively locked method
     long stamp = sl.writeLock();
     try {
       x += deltaX;
       y += deltaY;
     } finally {
       sl.unlockWrite(stamp);
     }
   }

   double distanceFromOrigin() { // A read-only method
     long stamp = sl.tryOptimisticRead();
     double currentX = x, currentY = y;
     if (!sl.validate(stamp)) {
        stamp = sl.readLock();
        try {
          currentX = x;
          currentY = y;
        } finally {
           sl.unlockRead(stamp);
        }
     }
     return Math.sqrt(currentX * currentX + currentY * currentY);
   }

   void moveIfAtOrigin(double newX, double newY) { // upgrade
     // Could instead start with optimistic, not read mode
     long stamp = sl.readLock();
     try {
       while (x == 0.0 && y == 0.0) {
         long ws = sl.tryConvertToWriteLock(stamp);
         if (ws != 0L) {
           stamp = ws;
           x = newX;
           y = newY;
           break;
         }
         else {
           sl.unlockRead(stamp);
           stamp = sl.writeLock();
         }
       }
     } finally {
       sl.unlock(stamp);
     }
   }
 }
```





#### validate()

use [Unsafe#loadFence()](/docs/CS/Java/JDK/Basic/unsafe.md?id=memory-barrier)

1. Returns true if the lock has not been exclusively acquired since issuance of the given stamp.
2.  Always returns false if the stamp is zero.
3.  Always returns true if the stamp represents a currently held lock. 

Invoking this method with a value not obtained from `tryOptimisticRead` or a locking method for this lock has no defined effect or result.


```java
public boolean validate(long stamp) {
    U.loadFence();
    return (stamp & SBITS) == (state & SBITS);
}
```



### 内部数据结构

为了帮助大家更好的理解StampedLock，这里再简单给大家介绍一下它的内部实现和数据结构。

在StampedLock中，有一个队列，里面存放着等待在锁上的线程。该队列是一个链表，链表中的元素是一个叫做WNode的对象：

![img](https://p3-juejin.byteimg.com/tos-cn-i-k3u1fbpfcp/f814a1b33bca4fa8aacfce65eaab3e6c~tplv-k3u1fbpfcp-zoom-1.image)

当队列中有若干个线程等待时，整个队列可能看起来像这样的：

![img](https://p3-juejin.byteimg.com/tos-cn-i-k3u1fbpfcp/d6a9245aa33e4170a95f97c272d83e01~tplv-k3u1fbpfcp-zoom-1.image)

除了这个等待队列，StampedLock中另外一个特别重要的字段就是long state， 这是一个64位的整数，StampedLock对它的使用是非常巧妙的。

state 的初始值是:

```java
/** Lock sequence/state */
private transient volatile long state;
/** extra reader count when state read count saturated */
private transient int readerOverflow;

/**
 * Creates a new lock, initially in unlocked state.
 */
public StampedLock() {
    state = ORIGIN;
}

/** The number of bits to use for reader count before overflowing */
private static final int LG_READERS = 7; // 127 readers

// Values for lock state and stamp operations
private static final long RUNIT = 1L;
private static final long WBIT  = 1L << LG_READERS;
private static final long RBITS = WBIT - 1L;
private static final long RFULL = RBITS - 1L;
private static final long ABITS = RBITS | WBIT;
private static final long SBITS = ~RBITS; // note overlap with ABITS
// not writing and conservatively non-overflowing
private static final long RSAFE = ~(3L << (LG_READERS - 1));

/*
 * 3 stamp modes can be distinguished by examining (m = stamp & ABITS):
 * write mode: m == WBIT
 * optimistic read mode: m == 0L (even when read lock is held)
 * read mode: m > 0L && m <= RFULL (the stamp is a copy of state, but the
 * read hold count in the stamp is unused other than to determine mode)
 *
 * This differs slightly from the encoding of state:
 * (state & ABITS) == 0L indicates the lock is currently unlocked.
 * (state & ABITS) == RBITS is a special transient value
 * indicating spin-locked to manipulate reader bits overflow.
 */

/** Initial value for lock state; avoids failure value zero. */
private static final long ORIGIN = WBIT << 1;

// Special value from cancelled acquire methods so caller can throw IE
private static final long INTERRUPTED = 1L;
```



也就是 ...0001 0000 0000 (前面的0太多了，不写了，凑足64个吧~)，为什么这里不用0做初始值呢？因为0有特殊的含义，为了避免冲突，所以选择了一个非零的数字。

如果有写锁占用，那么就让第7位设置为1  ...0001 1000 0000，也就是加上WBIT。

每次释放写锁，就加1，但不是state直接加，而是去掉最后一个字节，只使用前面的7个字节做统计。因此，释放写锁后，state就变成了：...0010 0000 0000， 再加一次锁，又变成：...0010 1000 0000，以此类推。

**这里为什么要记录写锁释放的次数呢？**

这是因为整个state 的状态判断都是基于CAS操作的。而普通的CAS操作可能会遇到ABA的问题，如果不记录次数，那么当写锁释放掉，申请到，再释放掉时，我们将无法判断数据是否被写过
而这里记录了释放的次数，因此出现"释放->申请->释放"的时候，CAS操作就可以检查到数据的变化，从而判断写操作已经有发生，作为一个乐观锁来说，就可以准确判断冲突已经产生，剩下的就是交给应用来解决冲突即可
因此，这里记录释放锁的次数，是为了精确地监控线程冲突。

而state剩下的那一个字节的其中7位，用来记录读锁的线程数量，由于只有7位，因此只能记录可怜的126个,看下面代码中的RFULL，就是读线程满载的数量。超过了怎么办呢，多余的部分就记录在readerOverflow字段中。

```java
    private static final long WBIT  = 1L << LG_READERS;
    private static final long RBITS = WBIT - 1L;
    private static final long RFULL = RBITS - 1L;
    private transient int readerOverflow;
复制代码
```

总结一下，state变量的结构如下：

![img](https://p3-juejin.byteimg.com/tos-cn-i-k3u1fbpfcp/f9eda5b6969f413f8d8589e46bec30ca~tplv-k3u1fbpfcp-zoom-1.image)



### Node

```java
// Bits for Node.status
static final int WAITING   = 1;
static final int CANCELLED = 0x80000000; // must be negative

/** CLH nodes */
abstract static class Node {
    volatile Node prev;       // initially attached via casTail
    volatile Node next;       // visibly nonnull when signallable
    Thread waiter;            // visibly nonnull when enqueued
    volatile int status;      // written by owner, atomic bit ops by others

    // methods for atomic operations
    final boolean casPrev(Node c, Node v) {  // for cleanQueue
        return U.weakCompareAndSetReference(this, PREV, c, v);
    }
    final boolean casNext(Node c, Node v) {  // for cleanQueue
        return U.weakCompareAndSetReference(this, NEXT, c, v);
    }
    final int getAndUnsetStatus(int v) {     // for signalling
        return U.getAndBitwiseAndInt(this, STATUS, ~v);
    }
    final void setPrevRelaxed(Node p) {      // for off-queue assignment
        U.putReference(this, PREV, p);
    }
    final void setStatusRelaxed(int s) {     // for off-queue assignment
        U.putInt(this, STATUS, s);
    }
    final void clearStatus() {               // for reducing unneeded signals
        U.putIntOpaque(this, STATUS, 0);
    }

    private static final long STATUS
        = U.objectFieldOffset(Node.class, "status");
    private static final long NEXT
        = U.objectFieldOffset(Node.class, "next");
    private static final long PREV
        = U.objectFieldOffset(Node.class, "prev");
}

static final class WriterNode extends Node { // node for writers
}

static final class ReaderNode extends Node { // node for readers
    volatile ReaderNode cowaiters;           // list of linked readers
    final boolean casCowaiters(ReaderNode c, ReaderNode v) {
        return U.weakCompareAndSetReference(this, COWAITERS, c, v);
    }
    final void setCowaitersRelaxed(ReaderNode p) {
        U.putReference(this, COWAITERS, p);
    }
    private static final long COWAITERS
        = U.objectFieldOffset(ReaderNode.class, "cowaiters");
}

/** Head of CLH queue */
private transient volatile Node head;
/** Tail (last) of CLH queue */
private transient volatile Node tail;
```



### 写锁的申请和释放

在了解了StampedLock的内部数据结构之后，让我们再来看一下有关写锁的申请和释放吧！首先是写锁的申请：

```java
    public long writeLock() {
        long s, next;  
        return ((((s = state) & ABITS) == 0L &&  //有没有读写锁被占用，如果没有，就设置上写锁标记
                 U.compareAndSwapLong(this, STATE, s, next = s + WBIT)) ?
                //如果写锁占用成功范围next，如果失败就进入acquireWrite()进行锁的占用。
                next : acquireWrite(false, 0L));
    }
复制代码
```

如果CAS设置state失败，表示写锁申请失败，这时，会调用acquireWrite()进行申请或者等待。acquireWrite()大体做了下面几件事情：

1. 入队
   1. 如果头结点等于尾结点`wtail == whead`， 表示快轮到我了，所以进行自旋等待，抢到就结束了
   2. 如果`wtail==null` ，说明队列都没初始化，就初始化一下队列
   3. 如果队列中有其他等待结点，那么只能老老实实入队等待了
2. 阻塞并等待
   1. 如果头结点等于前置结点`(h = whead) == p)`, 那说明也快轮到我了，不断进行自旋等待争抢
   2. 否则唤醒头结点中的读线程
   3. 如果抢占不到锁，那么就park()当前线程

![img](data:image/svg+xml;utf8,<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="800" height="600"></svg>)

简单地说，acquireWrite()函数就是用来争抢锁的，它的返回值就是代表当前锁状态的邮戳，同时，为了提高锁的性能，acquireWrite()使用大量的自旋重试，因此，它的代码看起来有点晦涩难懂。

写锁的释放如下所示，unlockWrite()的传入参数是申请锁时得到的邮戳：

```java
    public void unlockWrite(long stamp) {
        WNode h;
        //检查锁的状态是否正常
        if (state != stamp || (stamp & WBIT) == 0L)
            throw new IllegalMonitorStateException();
        // 设置state中标志位为0，同时也起到了增加释放锁次数的作用
        state = (stamp += WBIT) == 0L ? ORIGIN : stamp;
        // 头结点不为空，尝试唤醒后续的线程
        if ((h = whead) != null && h.status != 0)
            //唤醒(unpark)后续的一个线程
            release(h);
    }
复制代码
```

### readLock

```java
/**
 * Non-exclusively acquires the lock, blocking if necessary
 * until available.
 *
 * @return a read stamp that can be used to unlock or convert mode
 */
@ReservedStackAccess
public long readLock() {
    // unconditionally optimistically try non-overflow case once
    long s = U.getLongOpaque(this, STATE) & RSAFE, nextState;
    if (casState(s, nextState = s + RUNIT))
        return nextState;
    else
        return acquireRead(false, false, 0L);
}
```

#### acquireRead

```java
private long acquireRead(boolean interruptible, boolean timed, long time) {
    boolean interrupted = false;
    ReaderNode node = null;
    /*
     * Loop:
     *   if empty, try to acquire
     *   if tail is Reader, try to cowait; restart if leader stale or cancels
     *   else try to create and enqueue node, and wait in 2nd loop below
     */
    for (;;) {
        ReaderNode leader; long nextState;
        Node tailPred = null, t = tail;
        if ((t == null || (tailPred = t.prev) == null) &&
            (nextState = tryAcquireRead()) != 0L) // try now if empty
            return nextState;
        else if (t == null)
            tryInitializeHead();
        else if (tailPred == null || !(t instanceof ReaderNode)) {
            if (node == null)
                node = new ReaderNode();
            if (tail == t) {
                node.setPrevRelaxed(t);
                if (casTail(t, node)) {
                    t.next = node;
                    break; // node is leader; wait in loop below
                }
                node.setPrevRelaxed(null);
            }
        } else if ((leader = (ReaderNode)t) == tail) { // try to cowait
            for (boolean attached = false;;) {
                if (leader.status < 0 || leader.prev == null)
                    break;
                else if (node == null)
                    node = new ReaderNode();
                else if (node.waiter == null)
                    node.waiter = Thread.currentThread();
                else if (!attached) {
                    ReaderNode c = leader.cowaiters;
                    node.setCowaitersRelaxed(c);
                    attached = leader.casCowaiters(c, node);
                    if (!attached)
                        node.setCowaitersRelaxed(null);
                } else {
                    long nanos = 0L;
                    if (!timed)
                        LockSupport.park(this);
                    else if ((nanos = time - System.nanoTime()) > 0L)
                        LockSupport.parkNanos(this, nanos);
                    interrupted |= Thread.interrupted();
                    if ((interrupted && interruptible) ||
                        (timed && nanos <= 0L))
                        return cancelCowaiter(node, leader, interrupted);
                }
            }
            if (node != null)
                node.waiter = null;
            long ns = tryAcquireRead();
            signalCowaiters(leader);
            if (interrupted)
                Thread.currentThread().interrupt();
            if (ns != 0L)
                return ns;
            else
                node = null; // restart if stale, missed, or leader cancelled
        }
    }

    // node is leader of a cowait group; almost same as acquireWrite
    byte spins = 0, postSpins = 0;   // retries upon unpark of first thread
    boolean first = false;
    Node pred = null;
    for (long nextState;;) {
        if (!first && (pred = node.prev) != null &&
            !(first = (head == pred))) {
            if (pred.status < 0) {
                cleanQueue();           // predecessor cancelled
                continue;
            } else if (pred.prev == null) {
                Thread.onSpinWait();    // ensure serialization
                continue;
            }
        }
        if ((first || pred == null) &&
            (nextState = tryAcquireRead()) != 0L) {
            if (first) {
                node.prev = null;
                head = node;
                pred.next = null;
                node.waiter = null;
            }
            signalCowaiters(node);
            if (interrupted)
                Thread.currentThread().interrupt();
            return nextState;
        } else if (first && spins != 0) {
            --spins;
            Thread.onSpinWait();
        } else if (node.status == 0) {
            if (node.waiter == null)
                node.waiter = Thread.currentThread();
            node.status = WAITING;
        } else {
            long nanos;
            spins = postSpins = (byte)((postSpins << 1) | 1);
            if (!timed)
                LockSupport.park(this);
            else if ((nanos = time - System.nanoTime()) > 0L)
                LockSupport.parkNanos(this, nanos);
            else
                break;
            node.clearStatus();
            if ((interrupted |= Thread.interrupted()) && interruptible)
                break;
        }
    }
    return cancelAcquire(node, interrupted);
}
```

acquireRead()的实现相当复杂，大体上分为这么几步：

![img](data:image/svg+xml;utf8,<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="800" height="600"></svg>)

总之，就是自旋，自旋再自旋，通过不断的自旋来尽可能避免线程被真的挂起，只有当自旋充分失败后，才会真正让线程去等待。

下面是释放读锁的过程：

![img](data:image/svg+xml;utf8,<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="800" height="600"></svg>)

### writeLock

```java
/**
 * Exclusively acquires the lock, blocking if necessary
 * until available.
 *
 * @return a write stamp that can be used to unlock or convert mode
 */
@ReservedStackAccess
public long writeLock() {
    // try unconditional CAS confirming weak read
    long s = U.getLongOpaque(this, STATE) & ~ABITS, nextState;
    if (casState(s, nextState = s | WBIT)) {
        U.storeStoreFence();
        return nextState;
    }
    return acquireWrite(false, false, 0L);
}
```

#### acquireWrite

```java
private long acquireWrite(boolean interruptible, boolean timed, long time) {
    byte spins = 0, postSpins = 0;   // retries upon unpark of first thread
    boolean interrupted = false, first = false;
    WriterNode node = null;
    Node pred = null;
    for (long s, nextState;;) {
        if (!first && (pred = (node == null) ? null : node.prev) != null &&
            !(first = (head == pred))) {
            if (pred.status < 0) {
                cleanQueue();           // predecessor cancelled
                continue;
            } else if (pred.prev == null) {
                Thread.onSpinWait();    // ensure serialization
                continue;
            }
        }
        if ((first || pred == null) && ((s = state) & ABITS) == 0L &&
            casState(s, nextState = s | WBIT)) {
            U.storeStoreFence();
            if (first) {
                node.prev = null;
                head = node;
                pred.next = null;
                node.waiter = null;
                if (interrupted)
                    Thread.currentThread().interrupt();
            }
            return nextState;
        } else if (node == null) {          // retry before enqueuing
            node = new WriterNode();
        } else if (pred == null) {          // try to enqueue
            Node t = tail;
            node.setPrevRelaxed(t);
            if (t == null)
                tryInitializeHead();
            else if (!casTail(t, node))
                node.setPrevRelaxed(null);  // back out
            else
                t.next = node;
        } else if (first && spins != 0) {   // reduce unfairness
            --spins;
            Thread.onSpinWait();
        } else if (node.status == 0) {      // enable signal
            if (node.waiter == null)
                node.waiter = Thread.currentThread();
            node.status = WAITING;
        } else {
            long nanos;
            spins = postSpins = (byte)((postSpins << 1) | 1);
            if (!timed)
                LockSupport.park(this);
            else if ((nanos = time - System.nanoTime()) > 0L)
                LockSupport.parkNanos(this, nanos);
            else
                break;
            node.clearStatus();
            if ((interrupted |= Thread.interrupted()) && interruptible)
                break;
        }
    }
    return cancelAcquire(node, interrupted);
}
```
## Tuning

### CPU的问题

StampedLock固然是个好东西，但是由于它特别复杂，难免也会出现一些小问题。下面这个例子，就演示了StampedLock悲观锁疯狂占用CPU的问题：

```java
public class StampedLockTest {
    public static void main(String[] args) throws InterruptedException {
        final StampedLock lock = new StampedLock();
        Thread t1 = new Thread(() -> {
            // 获取写锁
            lock.writeLock();
            // 模拟程序阻塞等待其他资源
            LockSupport.park();
        });
        t1.start();
        // 保证t1获取写锁
        Thread.sleep(100);
        Thread t2 = new Thread(() -> {
            // 阻塞在悲观读锁
            lock.readLock();
        });
        t2.start();
        // 保证t2阻塞在读锁
        Thread.sleep(100);
        // 中断线程t2,会导致线程t2所在CPU飙升
        t2.interrupt();
        t2.join();
    }
}
```
interrupt() 可能会导致 CPU 使用率飙升。
这是因为线程接收到了中断请求，但 StampedLock 并没有正确处理中断信号，那么线程可能会陷入无限循环中，试图从中断状态中恢复，这可能会导致 CPU 使用率飙升。

如果没有中断，那么阻塞在readLock()上的线程在经过几次自旋后，会进入park()等待，一旦进入park()等待，就不会占用CPU了
但是park()这个函数有一个特点，就是一旦线程被中断，park()就会立即返回，返回还不算，它也不给你抛点异常啥的，那这就尴尬了
本来呢，你是想在锁准备好的时候，unpark()的线程的，但是现在锁没好，你直接中断了，park()也返回了，但是，毕竟锁没好，所以就又去自旋了。

转着转着，又转到了park()函数，但悲催的是，线程的中断标记一直打开着，park()就阻塞不住了，于是乎，下一个自旋又开始了，没完没了的自旋停不下来了，所以CPU就爆满了。

要解决这个问题，本质上需要在StampedLock内部，在park()返回时，需要判断中断标记为，并作出正确的处理，比如，退出，抛异常，或者把中断位给清理一下，都可以解决问题。


## Comparison


|           | StampedLock                             | ReentrantReadWriteLock    |
| --------- | --------------------------------------- | ------------------------- |
| Mode      | Support Read/Write/OptimisticRead       | Support Read/Write        |
| Reentrant | not support(dead lock when write twice) | support                   |
| Lock      | support Read <-> Write                  | not support Read -> Write |
| Condition | not support                             | support                   |
|           |                                         |                           |


## Links
- [Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
- [AQS](/docs/CS/Java/JDK/Concurrency/AQS.md)

## References

1. [多线程小冷门 StampedLock - 敖丙](https://juejin.cn/post/6944872312843960356)