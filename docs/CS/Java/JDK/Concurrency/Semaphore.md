## Introduction



计数信号量（counting semaphore）。从概念上讲，信号量维护一组许可（permit）。
每次 acquire 在必要时会阻塞，直到有许可可用时才取走它；每次 release 会增加一个许可，并可能唤醒一个正在阻塞的获取者。
不过信号量并不使用真实的许可对象，而是只记录可用许可的数量，并据此行事。
Semaphore 是一种经典的并发工具。
**信号量常用于限制能够访问某类（物理或逻辑）资源的线程数量。**

线程在获取某一项之前，必须先向信号量申请一个许可，从而保证该项可用。线程用完该项后将其归还到池中，并向信号量归还一个许可，使其他线程能够获取该项。注意，调用 acquire 时不会持有任何同步锁，否则会阻止该项被归还到池中。**信号量封装了限制访问对象池所需的同步逻辑，与维护对象池自身一致性所需的同步逻辑相互独立。**
初始化为 1、且最多只保持一个可用许可的信号量，可以充当互斥锁使用。这通常被称为二元信号量（binary semaphore），因为它只有两种状态：有 1 个许可可用，或 0 个许可可用。以这种方式使用时，二元信号量具有一个特性（与许多 `java.util.concurrent.locks.Lock` 实现不同）：**"锁"可以由非持有者线程释放（因为信号量没有所有权的概念）**。这在某些特殊场景下很有用，例如死锁恢复。

该类的构造方法可选地接受一个公平性（fairness）参数。当该参数为 false 时，类不保证线程获取许可的顺序，尤其允许"插队"（barging）：即调用 acquire 的线程可能排在早已等待的线程之前获得许可——从逻辑上看，新线程把自己放到了等待线程队列的队首。当公平性为 true 时，信号量保证调用任意 acquire 方法的线程，按照这些方法被处理的顺序（先进先出；FIFO）获得许可。需要注意的是，FIFO 顺序必然只作用于这些方法内部特定的执行点。因此完全可能出现这样的情况：某线程比另一线程先调用 acquire，却在后一个到达排序点，从方法返回时同理。另需注意，不带超时的 tryAcquire 方法不遵守公平性设置，但会取走任何可用的许可。
通常，用于控制资源访问的信号量应初始化为公平模式，以确保不会有线程因长期得不到资源访问权而被"饿死"。当把信号量用于其他类型的同步控制时，非公平顺序带来的吞吐优势往往超过公平性考量。
该类还提供了便捷方法，可一次性获取或释放多个许可。当公平性未设为 true 而使用这些方法时，需警惕无限期推迟（indefinite postponement）的风险上升。
**_内存一致性效应（memory consistency effects）_**：*线程中调用 release() 之前的操作 **happen-before** 另一线程中成功 acquire() 之后的操作。*



```java
public class Semaphore implements java.io.Serializable {
    /** All mechanics via AbstractQueuedSynchronizer subclass */
    private final Sync sync;
  
   public Semaphore(int permits) {
        sync = new NonfairSync(permits);
    }
  
   public Semaphore(int permits, boolean fair) {
        sync = fair ? new FairSync(permits) : new NonfairSync(permits);
    }
}
```



### Sync

```java
/**
 * Synchronization implementation for semaphore.  Uses AQS state
 * to represent permits. Subclassed into fair and nonfair
 * versions.
 */
abstract static class Sync extends AbstractQueuedSynchronizer {
    private static final long serialVersionUID = 1192457210091910933L;

    Sync(int permits) {
        setState(permits);
    }

    final int getPermits() {
        return getState();
    }
		// invoke by tryAcquire
    final int nonfairTryAcquireShared(int acquires) {
        for (;;) {
            int available = getState();
            int remaining = available - acquires;
            if (remaining < 0 ||
                compareAndSetState(available, remaining))
                return remaining;
        }
    }

    protected final boolean tryReleaseShared(int releases) {
        for (;;) {
            int current = getState();
            int next = current + releases;
            if (next < current) // overflow
                throw new Error("Maximum permit count exceeded");
            if (compareAndSetState(current, next))
                return true;
        }
    }

    final void reducePermits(int reductions) {
        for (;;) {
            int current = getState();
            int next = current - reductions;
            if (next > current) // underflow
                throw new Error("Permit count underflow");
            if (compareAndSetState(current, next))
                return;
        }
    }

    final int drainPermits() {
        for (;;) {
            int current = getState();
            if (current == 0 || compareAndSetState(current, 0))
                return current;
        }
    }
}
```



## acquire



重复执行以下流程：

1. 检查当前节点是否已是队首
2. 若是，确保 head 稳定；否则确保前驱节点有效
3. 若节点是队首或尚未入队，则尝试获取许可
4. 否则若节点尚未创建，则创建它
5. 否则若尚未入队，则尝试入队一次
6. 否则若从 park 中被唤醒，则重试（最多 postSpins 次）
7. 否则若尚未设置 WAITING 状态，则设置后重试
8. 否则执行 park 并清除 WAITING 状态，同时检查取消

```java
public void acquire() throws InterruptedException {
    sync.acquireSharedInterruptibly(1);
}

// in AQS
public final void acquireSharedInterruptibly(int arg)
        throws InterruptedException {
    if (Thread.interrupted())
        throw new InterruptedException();
    if (tryAcquireShared(arg) < 0)
        doAcquireSharedInterruptibly(arg);
}

// FairLock
protected int tryAcquireShared(int acquires) {
    for (;;) {
        if (hasQueuedPredecessors())
            return -1;
        int available = getState();
        int remaining = available - acquires;
        if (remaining < 0 ||
            compareAndSetState(available, remaining))
            return remaining;
    }
}

// NonFairLock
final int nonfairTryAcquireShared(int acquires) {
    for (;;) {
        int available = getState();
        int remaining = available - acquires;
        if (remaining < 0 ||
            compareAndSetState(available, remaining))
            return remaining;
    }
}
```





## release

```java
public void release() {
    sync.releaseShared(1);
}

protected final boolean tryReleaseShared(int releases) {
    for (;;) {
        int current = getState();
        int next = current + releases;
        if (next < current) // overflow
            throw new Error("Maximum permit count exceeded");
        if (compareAndSetState(current, next))
            return true;
    }
}
```



## Example

_下面以一个简单的类为例，展示如何用信号量控制对对象池的访问：_

```java
  
 class Pool {
   private static final int MAX_AVAILABLE = 100;
   private final Semaphore available = new Semaphore(MAX_AVAILABLE, true);

   public Object getItem() throws InterruptedException {
     available.acquire();
     return getNextAvailableItem();
   }

   public void putItem(Object x) {
     if (markAsUnused(x))
       available.release();
   }

   // Not a particularly efficient data structure; just for demo

   protected Object[] items = ... whatever kinds of items being managed
   protected boolean[] used = new boolean[MAX_AVAILABLE];

   protected synchronized Object getNextAvailableItem() {
     for (int i = 0; i < MAX_AVAILABLE; ++i) {
       if (!used[i]) {
         used[i] = true;
         return items[i];
       }
     }
     return null; // not reached
   }

   protected synchronized boolean markAsUnused(Object item) {
     for (int i = 0; i < MAX_AVAILABLE; ++i) {
       if (item == items[i]) {
         if (used[i]) {
           used[i] = false;
           return true;
         } else
           return false;
       }
     }
     return false;
   }
 }
```




## Links
- [Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
- [AQS](/docs/CS/Java/JDK/Concurrency/AQS.md)
