## Introduction

The Lock interface defines a number of abstract locking operations.
Unlike intrinsic locking, Lock offers a choice of unconditional, polled, timed, and interruptible lock acquisition,
and all lock and unlock operations are explicit.
Lock implementations must provide the same memory-visibility semantics as intrinsic locks,
but can differ in their locking semantics, scheduling algorithms, ordering guarantees, and performance characteristics.



## Lock
Lock implementations provide more extensive locking operations than can be obtained using [synchronized](/docs/CS/Java/JDK/Concurrency/synchronized.md) methods and statements. 
They allow more flexible structuring, may have quite different properties, and may support multiple associated Condition objects.*

A lock is a tool for controlling access to a shared resource by multiple threads. 
Commonly, a lock provides exclusive access to a shared resource: only one thread at a time can acquire the lock and all access to the shared resource requires that the lock be acquired first. 
However, some locks may allow concurrent access to a shared resource, such as the read lock of a ReadWriteLock.

The use of synchronized methods or statements provides access to the implicit monitor lock associated with every object, but forces all lock acquisition and release to occur in a block-structured way: 
when multiple locks are acquired they must be released in the opposite order, and all locks must be released in the same lexical scope in which they were acquired.

While the scoping mechanism for synchronized methods and statements makes it much easier to program with monitor locks, 
and helps avoid many common programming errors involving locks, there are occasions where you need to work with locks in a more flexible way. 
For example, some algorithms for traversing concurrently accessed data structures require the use of "hand-over-hand" or "chain locking": 
you acquire the lock of node A, then node B, then release A and acquire C, then release B and acquire D and so on. 
Implementations of the Lock interface enable the use of such techniques by allowing a lock to be acquired and released in different scopes, and allowing multiple locks to be acquired and released in any order.



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

TicketLock

CLHLock

MCSLock

### Polled and Timed Lock Acquisition

The timed and polled lock-acqusition modes provided by tryLock allow more sophisticated error recovery than unconditional acquisition. 
With intrinsic locks, a deadlock is fatal—the only way to recover is to restart the application, and the only defense is to construct your program so that inconsistent lock ordering is impossible. 
Timed and polled locking offer another option: probabalistic deadlock avoidance.

### Interruptible Lock Acquisition

Just as timed lock acquisition allows exclusive locking to be used within timelimited activities, interruptible lock acquisition allows locking to be used within cancellable activities. 
Several mechanisms, such as acquiring an intrinsic lock, that are not responsive to interruption. 
These noninterruptible blocking mechanisms complicate the implementation of cancellable tasks. 
The `lockInterruptibly` method allows you to try to acquire a lock while remaining responsive to interruption, and its inclusion in Lock avoids creating another category of non-interruptible blocking mechanisms.

The canonical structure of interruptible lock acquisition is slightly more complicated than normal lock acquisition, as two try blocks are needed. 
(If the interruptible lock acquisition can throw InterruptedException, the standard try-finally locking idiom works.) 
The timed `tryLock` is also responsive to interruption and so can be used when you need both timed and interruptible lock acquisition.

### Non-block-structured Locking

With intrinsic locks, acquire-release pairs are block-structured—a lock is always released in the same basic block in which it was acquired, regardless of how control exits the block. 
Automatic lock release simplifies analysis and prevents potential coding errors, but sometimes a more flexible locking discipline is needed.
In ConcurrentMap, we saw how reducing lock granularity can enhance scalability. Lock striping allows different hash chains in a hash-based collection to use different locks.
An example of this technique, called **hand-over-hand locking** or **lock coupling**.

### Fairness

The ReentrantLock constructor offers a choice of two fairness options: create a nonfair lock (the default) or a fair lock.
(*The polled `tryLock` always barges, even for fair locks*.)




### Summary of Lock

> ReentrantLock is an advanced tool for situations where intrinsic locking is not practical.
> 
> Use it if you need its advanced features: 
> timed, polled, or interruptible lock acquisition, fair queueing, or non-block-structured locking. 
> 
> **Otherwise, prefer synchronized.**

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



|               | Object                | Condition                          |
| ------------- | --------------------- | ---------------------------------- |
| Method        | wait/notify           | await/signal                       |
| Depend        | synchronized          | AQS                                |
| Implement     | C++                   | Java                               |
| Interruptibility | interruptibility |                                    |
| wait time     |                       | could set a future time            |
| Num           |                       | a Lock can use multiple Conditions |
| Sleep         | Unsupported           | Supported                          |
|               |                       |                                    |





## LockSupport

**LockSupport call [Unsafe](/docs/CS/Java/JDK/Basic/unsafe.md)**.



### parker

Disables the current thread for thread scheduling purposes unless the permit is available.

If the permit is available then it is consumed and the call returns immediately; otherwise the current thread becomes disabled for thread scheduling purposes and lies dormant until one of three things happens:
- Some other thread invokes unpark with the current thread as the target; or
- Some other thread interrupts the current thread; or
- The call spuriously (that is, for no reason) returns.

This method does not report which of these caused the method to return. Callers should re-check the conditions which caused the thread to park in the first place. Callers may also determine, for example, the interrupt status of the thread upon return.

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
**sample**:

```
while (!canProceed()) { ... LockSupport.park(this); }
```

Makes available the permit for the given thread, if it was not already available. 
If the thread was blocked on park then it will unblock. 
Otherwise, its next call to park is guaranteed not to block. This operation is not guaranteed to have any effect at all if the given thread has not been started.
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

## Links
- [synchronized](/docs/CS/Java/JDK/Concurrency/synchronized.md)
- [AQS](/docs/CS/Java/JDK/Concurrency/AQS.md)
