## Introduction

一种基于能力（capability）的锁，提供三种模式来控制读/写访问。
**StampedLock 的状态由一个版本号和模式（mode）组成**。
加锁方法会返回一个邮戳（stamp），用来表示并控制对某个锁状态的访问；
这些方法的 "try" 版本可能返回特殊值 0，表示获取访问失败。
解锁与转换方法需要以邮戳作为参数，并且如果邮戳与锁状态不匹配就会失败。

三种模式如下：

写模式（Writing）。writeLock 方法可能会阻塞以等待独占访问，返回一个可用于 unlockWrite 方法释放锁的邮戳。
同时提供了 tryWriteLock 的无时限与有时限版本。
当锁处于写模式时，无法获取任何读锁，并且所有乐观读校验都会失败。

读模式（Reading）。readLock 方法可能会阻塞以等待非独占访问，返回一个可用于 unlockRead 方法释放锁的邮戳。
同时提供了 tryReadLock 的无时限与有时限版本。

乐观读（Optimistic Reading）。tryOptimisticRead 方法仅当锁当前未被写模式持有时，才返回一个非零邮戳。
validate 方法在获取给定邮戳之后锁未被写模式获取过的情况下返回 true。
该模式可以看作是一种极弱的读锁，随时可能被写者打破。
在短小的只读代码片段中使用乐观模式，通常能减少竞争并提升吞吐量。
但它的使用本质上很脆弱。乐观读代码段应当只读取字段并将其保存在局部变量中，留待校验之后使用。
在乐观模式下读取到的字段可能极其不一致，因此只有在你足够熟悉数据表示、能够检查一致性并/或反复调用 `validate()` 方法时才能使用。 

例如，当先读取某个对象或数组引用、再访问其字段、元素或方法时，通常就需要这类步骤。
本类还支持在三种模式之间进行有条件转换的方法。
例如，tryConvertToWriteLock 方法会尝试"升级"模式，在以下情况下返回有效的写邮戳： 

1. 已经处于写模式 
2. 处于读模式，且没有其他读者 
3. 处于乐观模式，且锁可用 

这些方法的形式旨在减少基于重试的设计中本会出现的一些代码膨胀。

StampedLock 被设计为开发线程安全组件时的内部工具。
它的使用依赖于对所保护数据、对象及方法内部特性的了解。
它不可重入，因此被锁保护的代码体不应调用其他可能尝试重新获取锁的未知方法（不过，你可以把一个邮戳传给其他能够使用或转换它的方法）。
读锁模式的使用依赖于相关代码段无副作用。
未经校验的乐观读代码段不能调用那些无法确定能否容忍潜在不一致性的方法。
邮戳采用有限位表示，且并非加密安全的（即一个有效邮戳有可能被猜测出来）。
邮戳值会在连续运行（不早于）一年后发生回收。
若邮戳在超过该时长后仍未被使用或校验，就可能无法通过校验。
StampedLock 可序列化，但反序列化后总是处于初始未加锁状态，因此不适合用于远程加锁。

StampedLock 的调度策略并不会一味偏向读者或写者。
所有 "try" 方法都是尽最大努力（best-effort）的，不一定遵循任何调度或公平性策略。
任何用于获取或转换锁的 "try" 方法返回 0，并不携带关于锁状态的任何信息；随后的再次调用可能会成功。
由于它支持跨多种锁模式的协调使用，本类并未直接实现 Lock 或 ReadWriteLock 接口。
不过，在只需要相应功能集的应用中，可以将 StampedLock 视为 asReadLock()、asWriteLock() 或 asReadWriteLock()。
使用示例。下面展示了在一个维护简单二维点的类中用法的惯用写法。
示例代码展示了一些 try/catch 约定，尽管这里并非严格需要，因为其方法体内不会发生任何异常。



## Sample

使用示例。下面展示了在一个维护简单二维点的类中用法的惯用写法。
示例代码展示了一些 try/catch 约定，尽管这里并非严格需要，因为其方法体内不会发生任何异常。 

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

使用 [Unsafe#loadFence()](/docs/CS/Java/JDK/Basic/unsafe.md?id=memory-barrier)

1. 若自给定邮戳（stamp）签发以来该锁未被独占获取，则返回 true。
2. 若邮戳为零，则始终返回 false。
3. 若邮戳表示一个当前持有的锁，则始终返回 true。

若传入的不是通过本锁的 `tryOptimisticRead` 或加锁方法获取到的邮戳，调用本方法没有定义的效果或结果。


```java
public boolean validate(long stamp) {
    U.loadFence();
    return (stamp & SBITS) == (state & SBITS);
}
```



### Internal Data Structure

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



### Acquisition and Release of Write Lock

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


总之，就是自旋，自旋再自旋，通过不断的自旋来尽可能避免线程被真的挂起，只有当自旋充分失败后，才会真正让线程去等待。

下面是释放读锁的过程：


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

### CPU Issues

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
| 模式      | 支持 读/写/乐观读                        | 支持 读/写                |
| 可重入    | 不支持（写两次会死锁）                   | 支持                      |
| 锁        | 支持 读 <-> 写                          | 不支持 读 -> 写           |
| 条件      | 不支持                                  | 支持                      |
|           |                                         |                           |


## Links
- [Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
- [AQS](/docs/CS/Java/JDK/Concurrency/AQS.md)
- [Lock](/docs/CS/Java/JDK/Concurrency/Lock.md)
- [ReentrantLock](/docs/CS/Java/JDK/Concurrency/ReentrantLock.md)
- [ReadWriteLock](/docs/CS/Java/JDK/Concurrency/ReadWriteLock.md)

## References

1. [多线程小冷门 StampedLock - 敖丙](https://juejin.cn/post/6944872312843960356)
