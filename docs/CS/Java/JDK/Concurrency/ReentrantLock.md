# ReentrantLock原理

ReentrantLock是Java并发包中一个非常有用的组件，一些并发集合类也是用ReentrantLock实现，包括ConcurrentHashMap。ReentrantLock具有三个特性：等待可中断、可实现公平锁、以及锁可以绑定多个条件。

## Java中的ReentrantLock

ReentrantLock与synchronized关键字一样，属于互斥锁，synchronized中的锁是非公平的（公平锁是指多个线程等待同一个锁时，必须按照申请锁的时间顺序来依次获得锁），ReentrantLock默认情况下也是非公平的，但可以通过带布尔值的构造函数要求使用公平锁。线程通过ReentrantLock的lock()方法获得锁，用unlock()方法释放锁。

### ReentrantLock和synchronized关键字的区别

1. ReentrantLock在等待锁时可以使用lockInterruptibly()方法选择中断， 改为处理其他事情，而synchronized关键字，线程需要一直等待下去。同样的，tryLock()方法可以设置超时时间，用于在超时时间内一直获取不到锁时进行中断。
2. ReentrantLock可以实现公平锁，而synchronized的锁是非公平的。
3. ReentrantLock拥有方便的方法用于获取正在等待锁的线程。
4. ReentrantLock可以同时绑定多个Condition对象，而synchronized中，锁对象的wait()和notify()或notifyAll()方法可以实现一个隐含的条件，如果要和多于一个条件关联时，只能再加一个额外的锁，而ReentrantLock只需要多次调用newCondition方法即可。

## 性能比较

在JDK1.6之前，ReentrantLock的性能要明显优于synchronized，但是JDK1.6中加入了很多针对锁的优化措施，synchronized和ReentrantLock的性能基本完全持平了。

### ReentrantLock缺点

ReentrantLock的主要缺点是方法需要置于try-finally块中，另外，开发人员需要负责获取和释放锁，而开发人员常常忘记在finally中释放锁。

## 源码

###### 

### 入队

入队实际上就是创建一个新的节点并将其设为tail的过程。

AbstractQueuedSynchronizer.addWaiter():

```
private Node addWaiter(Node mode) {
    Node node = new Node(Thread.currentThread(), mode);
    // Try the fast path of enq; backup to full enq on failure
    Node pred = tail;
    if (pred != null) {
        node.prev = pred;
        if (compareAndSetTail(pred, node)) {
            pred.next = node;
            return node;
        }
    }
    enq(node);
    return node;
}
```

可见，此处同样使用了快速尝试的思想，如果CAS尝试失败，那么再调用enq方法，源码:

```
private Node enq(final Node node) {
    for (;;) {
        Node t = tail;
        if (t == null) { // Must initialize
            //可见，head其实是一个"空的Node"
            if (compareAndSetHead(new Node()))
                tail = head;
        } else {
            node.prev = t;
            if (compareAndSetTail(t, node)) {
                t.next = node;
                return t;
            }
        }
    }
}
```

其实还是CAS操作，加了一个死循环，直到成功为止。

###### 

### 锁获取/等待

当前线程被加入到锁队列之后，整下的便是排队等候了。锁队列中当前节点可以获得锁的条件便是**上一个节点(prev)释放了锁**。

AbstractQueuedSynchronizer.acquireQueued:

```
final boolean acquireQueued(final Node node, int arg) {
    boolean failed = true;
    try {
        boolean interrupted = false;
        for (;;) {
            final Node p = node.predecessor();
            //前一个是head，那么表示当前节点即是等待时间最长的线程，并立即尝试获得锁
            if (p == head && tryAcquire(arg)) {
                setHead(node);
                p.next = null; // help GC
                failed = false;
                return interrupted;
            }
            //执行到这里说明当前节点不是等待时间最长的节点或者锁竞争失败
            if (shouldParkAfterFailedAcquire(p, node) &&
                parkAndCheckInterrupt())
                interrupted = true;
        }
    } finally {
        if (failed)
            cancelAcquire(node);
    }
}
```

从这里可以看出，当当前节点就是等待时间最长的节点(队首节点)时，仍然需要调用tryAcquire竞争锁，而与此同时新来的线程有可能同时调用tryAcquire方法与之竞争，这便是非公平性的体现。

shouldParkAfterFailedAcquire方法用于检测当前线程是否应该休眠，源码:

```
private static boolean shouldParkAfterFailedAcquire(Node pred, Node node) {
    int ws = pred.waitStatus;
    if (ws == Node.SIGNAL)
        /*
         * This node has already set status asking a release
         * to signal it, so it can safely park.
         */
        return true;
    //上一个节点已经被取消，所以需要"跳过"前面所有已经被取消的节点
    if (ws > 0) {
        do {
            node.prev = pred = pred.prev;
        } while (pred.waitStatus > 0);
        pred.next = node;
    } else {
        /*
         * waitStatus must be 0 or PROPAGATE.  Indicate that we
         * need a signal, but don't park yet.  Caller will need to
         * retry to make sure it cannot acquire before parking.
         */
        compareAndSetWaitStatus(pred, ws, Node.SIGNAL);
    }
    return false;
}
```

从这里可以看出，**当前一个节点的status为Signal时，当前节点(线程)便进入挂起状态，等待前一个节点释放锁，前一个节点释放锁时，会唤醒当前节点，那时当前节点会再次进行锁竞争**。

再来看一下是如何挂起线程的，AbstractQueuedSynchronizer.parkAndCheckInterrupt:

```
private final boolean parkAndCheckInterrupt() {
    LockSupport.park(this);
    return Thread.interrupted();
}
```

LockSupport相当于一个工具类，只有静态方法，私有构造器。

LockSupport.park:

```
public static void park(Object blocker) {
    Thread t = Thread.currentThread();
    setBlocker(t, blocker);
    //native
    UNSAFE.park(false, 0L);
    setBlocker(t, null);
}
```

此时，线程便会阻塞(休眠)在UNSAFE.park(false, 0L);这一句，直到有以下三种情形发生:

- unpark方法被调用

- interrupt方法被调用

- The call spuriously (that is, for no reason) returns.

  其实说的就是Spurious wakeup: 虚假唤醒。虚假唤醒指的便是阻塞的线程被"莫名其妙"的唤醒，这是多核处理器中不可避免的问题，参见:

  [Spurious wakeup](https://en.wikipedia.org/wiki/Spurious_wakeup)

  其实经常写的:

  ```
  while (!condition)
    await();
  ```

  便是为了防止此问题。

从acquireQueued方法的源码中可以看出，即使发生了上面所说的三个条件，也只是将变量interrupted设为了true而已，这也就是为什么lock方法会"义无反顾"地在这里等待锁的原因了。

###### 

### 自中断

当获得锁成功后，会将自己中断:

AbstractQueuedSynchronizer.selfInterrupt:

```
static void selfInterrupt() {
    Thread.currentThread().interrupt();
}
```

### 

### lockInterruptibly

此方法将在以下两种情况下返回:

- 获得锁
- 被中断

AbstractQueuedSynchronizer.acquireInterruptibly:

```
public final void acquireInterruptibly(int arg) throws InterruptedException {
    if (Thread.interrupted())
        throw new InterruptedException();
    if (!tryAcquire(arg))
        doAcquireInterruptibly(arg);
}
```

tryAcquire方法前面已经说过了，这里不再赘述。

AbstractQueuedSynchronizer.doAcquireInterruptibly:

```
private void doAcquireInterruptibly(int arg) throws InterruptedException {
    final Node node = addWaiter(Node.EXCLUSIVE);
    boolean failed = true;
    try {
        for (;;) {
            final Node p = node.predecessor();
            if (p == head && tryAcquire(arg)) {
                setHead(node);
                p.next = null; // help GC
                failed = false;
                return;
            }
            if (shouldParkAfterFailedAcquire(p, node) &&
                parkAndCheckInterrupt())
                //看这里!
                throw new InterruptedException();
        }
    } finally {
        if (failed)
            cancelAcquire(node);
    }
}
```

和lock方法相比其实只有一行不一样，这便是lockInterruptibly可以相应中断的原因了。

### 

### tryLock

此方法只是尝试一下现在能不能获得锁，不管结果怎样马上返回。

源码就是Sync.nonfairTryAcquire方法，前面已经说过了。

### 

#### tryLock带时间参数

AbstractQueuedSynchronizer.tryAcquireNanos:

```
public final boolean tryAcquireNanos(int arg, long nanosTimeout) throws InterruptedException {
    if (Thread.interrupted())
        throw new InterruptedException();
    return tryAcquire(arg) || doAcquireNanos(arg, nanosTimeout);
}
```

doAcquireNanos:

```
private boolean doAcquireNanos(int arg, long nanosTimeout) throws InterruptedException {
    if (nanosTimeout <= 0L)
        return false;
    final long deadline = System.nanoTime() + nanosTimeout;
    final Node node = addWaiter(Node.EXCLUSIVE);
    boolean failed = true;
    try {
        for (;;) {
            final Node p = node.predecessor();
            if (p == head && tryAcquire(arg)) {
                setHead(node);
                p.next = null; // help GC
                failed = false;
                return true;
            }
            nanosTimeout = deadline - System.nanoTime();
            if (nanosTimeout <= 0L)
                return false;
            if (shouldParkAfterFailedAcquire(p, node) && nanosTimeout > spinForTimeoutThreshold)
                //挂起指定的时间
                LockSupport.parkNanos(this, nanosTimeout);
            if (Thread.interrupted())
                throw new InterruptedException();
        }
    } finally {
        if (failed)
            cancelAcquire(node);
    }
}
```

spinForTimeoutThreshold为1000纳秒，可以看出，如果给定的等待时间大于1000纳秒，才会进行线程休眠，否则将会一直轮询。

### 

### unlock

调用了AbstractQueuedSynchronizer.release:

```
public final boolean release(int arg) {
    if (tryRelease(arg)) {
        Node h = head;
        if (h != null && h.waitStatus != 0)
            unparkSuccessor(h);
        return true;
    }
    return false;
}
```

#### 

#### 锁释放

Sync.tryRelease:

```
protected final boolean tryRelease(int releases) {
    int c = getState() - releases;
    if (Thread.currentThread() != getExclusiveOwnerThread())
        throw new IllegalMonitorStateException();
    boolean free = false;
    if (c == 0) {
        free = true;
        setExclusiveOwnerThread(null);
    }
    setState(c);
    return free;
}
```

由于锁释放的时候必定拥有锁，所以可以放心大胆的搞。如果当前线程已经不再持有此锁，那么返回true。

#### 

#### 节点唤醒

如果当前线程已经不再持有此锁(即tryRelease返回true)，那么将会唤醒锁队列中的下一个或多个节点。

unparkSuccessor:

```
 private void unparkSuccessor(Node node) {
    int ws = node.waitStatus;
    if (ws < 0)
        compareAndSetWaitStatus(node, ws, 0);

    Node s = node.next;
    if (s == null || s.waitStatus > 0) {
        s = null;
        for (Node t = tail; t != null && t != node; t = t.prev)
            if (t.waitStatus <= 0)
                s = t;
    }
    if (s != null)
        LockSupport.unpark(s.thread);
}
```

可以看出，先是检查下一个节点(next)，如果没有被取消，那么唤醒它即可，如果已经被取消，那么将倒着从后面查找。

## ReentrantLock的非公平策略原理

ReenrantLock非公平策略的内部实现和公平策略没啥太大区别：
非公平策略和公平策略的最主要区别在于：

1. 公平锁获取锁时，会判断等待队列中是否有线程排在当前线程前面。只有没有情况下，才去获取锁，这是公平的含义。
2. 非公平锁获取锁时，会立即尝试修改同步状态，失败后再调用AQS的acquire方法。 

## 总结

1. ReentrantLock是一个可重入的锁（被当前占用的线程重入）。
2. 它有两种模式公平与非公平，通过NonfairSync和FairSync赋值sync成员变量实现。
3. 两种模式都是AQS的子类，通过重写tryAcquire()区别不同。公平锁多了是否在队列的头的判断。
4. tryLock()方法没有区分模式，都是一样的。