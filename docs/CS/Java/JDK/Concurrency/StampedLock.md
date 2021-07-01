

## Introduction



A capability-based lock with three modes for controlling read/write access. The state of a StampedLock consists of a version and mode. Lock acquisition methods return a stamp that represents and controls access with respect to a lock state; "try" versions of these methods may instead return the special value zero to represent failure to acquire access. Lock release and conversion methods require stamps as arguments, and fail if they do not match the state of the lock. The three modes are:
Writing. Method writeLock possibly blocks waiting for exclusive access, returning a stamp that can be used in method unlockWrite to release the lock. Untimed and timed versions of tryWriteLock are also provided. When the lock is held in write mode, no read locks may be obtained, and all optimistic read validations will fail.
Reading. Method readLock possibly blocks waiting for non-exclusive access, returning a stamp that can be used in method unlockRead to release the lock. Untimed and timed versions of tryReadLock are also provided.
Optimistic Reading. Method tryOptimisticRead returns a non-zero stamp only if the lock is not currently held in write mode. Method validate returns true if the lock has not been acquired in write mode since obtaining a given stamp. This mode can be thought of as an extremely weak version of a read-lock, that can be broken by a writer at any time. The use of optimistic mode for short read-only code segments often reduces contention and improves throughput. However, its use is inherently fragile. Optimistic read sections should only read fields and hold them in local variables for later use after validation. Fields read while in optimistic mode may be wildly inconsistent, so usage applies only when you are familiar enough with data representations to check consistency and/or repeatedly invoke method validate(). For example, such steps are typically required when first reading an object or array reference, and then accessing one of its fields, elements or methods.
This class also supports methods that conditionally provide conversions across the three modes. For example, method tryConvertToWriteLock attempts to "upgrade" a mode, returning a valid write stamp if (1) already in writing mode (2) in reading mode and there are no other readers or (3) in optimistic mode and the lock is available. The forms of these methods are designed to help reduce some of the code bloat that otherwise occurs in retry-based designs.
StampedLocks are designed for use as internal utilities in the development of thread-safe components. Their use relies on knowledge of the internal properties of the data, objects, and methods they are protecting. They are not reentrant, so locked bodies should not call other unknown methods that may try to re-acquire locks (although you may pass a stamp to other methods that can use or convert it). The use of read lock modes relies on the associated code sections being side-effect-free. Unvalidated optimistic read sections cannot call methods that are not known to tolerate potential inconsistencies. Stamps use finite representations, and are not cryptographically secure (i.e., a valid stamp may be guessable). Stamp values may recycle after (no sooner than) one year of continuous operation. A stamp held without use or validation for longer than this period may fail to validate correctly. StampedLocks are serializable, but always deserialize into initial unlocked state, so they are not useful for remote locking.
The scheduling policy of StampedLock does not consistently prefer readers over writers or vice versa. All "try" methods are best-effort and do not necessarily conform to any scheduling or fairness policy. A zero return from any "try" method for acquiring or converting locks does not carry any information about the state of the lock; a subsequent invocation may succeed.
Because it supports coordinated usage across multiple lock modes, this class does not directly implement the Lock or ReadWriteLock interfaces. However, a StampedLock may be viewed asReadLock(), asWriteLock(), or asReadWriteLock() in applications requiring only the associated set of functionality.
Sample Usage. The following illustrates some usage idioms in a class that maintains simple two-dimensional points. The sample code illustrates some try/catch conventions even though they are not strictly needed here because no exceptions can occur in their bodies.



### StampedLock的基本使用



Sample Usage. The following illustrates some usage idioms in a class that maintains simple two-dimensional points. The sample code illustrates some try/catch conventions even though they are not strictly needed here because no exceptions can occur in their bodies. 

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

use [Unsafe#loadFence()]

```java
public boolean validate(long stamp) {
        U.loadFence();
        return (stamp & SBITS) == (state & SBITS);
    }
```

它的接受参数是上次锁操作返回的邮戳，如果在调用validate()之前，这个锁没有写锁申请过，那就返回true，这也表示锁保护的共享数据并没有被修改，因此之前的读取操作是肯定能保证数据完整性和一致性的。

反之，如果锁在validate()之前有写锁申请成功过，那就表示，之前的数据读取和写操作冲突了，程序需要进行重试，或者升级为悲观锁。

#### 和重入锁的比较

从上面的例子其实不难看到，就编程复杂度来说，StampedLock其实是要比重入锁复杂的多，代码也没有以前那么简洁了。

**那么，我们为什么还要使用它呢？**

最本质的原因，就是为了提升性能！一般来说，这种乐观锁的性能要比普通的重入锁快几倍，而且随着线程数量的不断增加，性能的差距会越来越大。

简而言之，在大量并发的场景中StampedLock的性能是碾压重入锁和读写锁的。

但毕竟，世界上没有十全十美的东西，StampedLock也并非全能，它的缺点如下：

1. 编码比较麻烦，如果使用乐观读，那么冲突的场景要应用自己处理
2. 它是不可重入的，如果一不小心在同一个线程中调用了两次，那么你的世界就清净了。。。。。
3. 它不支持wait/notify机制

如果以上3点对你来说都不是问题，那么我相信StampedLock应该成为你的首选。

### 内部数据结构

为了帮助大家更好的理解StampedLock，这里再简单给大家介绍一下它的内部实现和数据结构。

在StampedLock中，有一个队列，里面存放着等待在锁上的线程。该队列是一个链表，链表中的元素是一个叫做WNode的对象：

![img](https://p3-juejin.byteimg.com/tos-cn-i-k3u1fbpfcp/f814a1b33bca4fa8aacfce65eaab3e6c~tplv-k3u1fbpfcp-zoom-1.image)

当队列中有若干个线程等待时，整个队列可能看起来像这样的：

![img](https://p3-juejin.byteimg.com/tos-cn-i-k3u1fbpfcp/d6a9245aa33e4170a95f97c272d83e01~tplv-k3u1fbpfcp-zoom-1.image)

除了这个等待队列，StampedLock中另外一个特别重要的字段就是long state， 这是一个64位的整数，StampedLock对它的使用是非常巧妙的。

state 的初始值是:

```java
private static final int LG_READERS = 7;
private static final long WBIT  = 1L << LG_READERS;
private static final long ORIGIN = WBIT << 1;
复制代码
```

也就是 ...0001 0000 0000 (前面的0太多了，不写了，凑足64个吧~)，为什么这里不用0做初始值呢？因为0有特殊的含义，为了避免冲突，所以选择了一个非零的数字。

如果有写锁占用，那么就让第7位设置为1  ...0001 1000 0000，也就是加上WBIT。

每次释放写锁，就加1，但不是state直接加，而是去掉最后一个字节，只使用前面的7个字节做统计。因此，释放写锁后，state就变成了：...0010 0000 0000， 再加一次锁，又变成：...0010 1000 0000，以此类推。

**这里为什么要记录写锁释放的次数呢？**

这是因为整个state 的状态判断都是基于CAS操作的。而普通的CAS操作可能会遇到ABA的问题，如果不记录次数，那么当写锁释放掉，申请到，再释放掉时，我们将无法判断数据是否被写过。而这里记录了释放的次数，因此出现"释放->申请->释放"的时候，CAS操作就可以检查到数据的变化，从而判断写操作已经有发生，作为一个乐观锁来说，就可以准确判断冲突已经产生，剩下的就是交给应用来解决冲突即可。因此，这里记录释放锁的次数，是为了精确地监控线程冲突。

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

### 读锁的申请和释放

获取读锁的代码如下：

```java
    public long readLock() {
        long s = state, next;  
        //如果队列中没有写锁，并且读线程个数没有超过126，直接获得锁，并且读线程数量加1
        return ((whead == wtail && (s & ABITS) < RFULL &&
                 U.compareAndSwapLong(this, STATE, s, next = s + RUNIT)) ?
                //如果争抢失败，进入acquireRead()争抢或者等待
                next : acquireRead(false, 0L));
    }
复制代码
```

acquireRead()的实现相当复杂，大体上分为这么几步：

![img](data:image/svg+xml;utf8,<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="800" height="600"></svg>)

总之，就是自旋，自旋再自旋，通过不断的自旋来尽可能避免线程被真的挂起，只有当自旋充分失败后，才会真正让线程去等待。

下面是释放读锁的过程：

![img](data:image/svg+xml;utf8,<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="800" height="600"></svg>)

### StampedLock悲观读占满CPU的问题

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
复制代码
```

上述代码中，在中断t2后，t2的CPU占用率就会沾满100%。而这时候，t2正阻塞在readLock()函数上，换言之，在受到中断后，StampedLock的读锁有可能会占满CPU。这是什么原因呢？机制的小傻瓜一定想到了，这是因为StampedLock内太多的自旋引起的！没错，你的猜测是正确的。

**具体原因如下：**

如果没有中断，那么阻塞在readLock()上的线程在经过几次自旋后，会进入park()等待，一旦进入park()等待，就不会占用CPU了。但是park()这个函数有一个特点，就是一旦线程被中断，park()就会立即返回，返回还不算，它也不给你抛点异常啥的，那这就尴尬了。本来呢，你是想在锁准备好的时候，unpark()的线程的，但是现在锁没好，你直接中断了，park()也返回了，但是，毕竟锁没好，所以就又去自旋了。

转着转着，又转到了park()函数，但悲催的是，线程的中断标记一直打开着，park()就阻塞不住了，于是乎，下一个自旋又开始了，没完没了的自旋停不下来了，所以CPU就爆满了。

要解决这个问题，本质上需要在StampedLock内部，在park()返回时，需要判断中断标记为，并作出正确的处理，比如，退出，抛异常，或者把中断位给清理一下，都可以解决问题。

但很不幸，至少在JDK8里，还没有这样的处理。因此就出现了上面的，中断readLock()后，CPU爆满的问题。请大家一定要注意。

## StampedLock vs ReentrantReadWriteLock



|           | StampedLock                       | ReentrantReadWriteLock    |
| --------- | --------------------------------- | ------------------------- |
| Mode      | Support Read/Write/OptimisticRead | Support Read/Write        |
| Reentrant | not support                       | support                   |
| Lock      | support Read <-> Write            | not support Read -> Write |
| Condition | not support                       | support                   |
|           |                                   |                           |



## Reference

1. [多线程小冷门 StampedLock - 敖丙](https://juejin.cn/post/6944872312843960356)