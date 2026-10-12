## Introduction



一种同步辅助工具，允许**一个或多个线程**等待，直到其他线程中正在执行**的一组操作**完成。
CountDownLatch 是一个非常简洁却极为常用的工具，用于阻塞直到给定数量的信号、事件或条件成立。

CountDownLatch 以给定的计数初始化。await 方法会阻塞，直到因调用 countDown 方法使当前计数归零，此后所有等待线程被释放，且后续对 await 的调用会立即返回。这是一种一次性（one-shot）机制——计数无法被重置。如果需要可重置计数的版本，可以考虑使用 **CyclicBarrier**。
CountDownLatch 是一种通用的同步工具，可用于多种目的。以计数 1 初始化的 CountDownLatch 充当一个简单的开/关锁存器（或闸门）：所有调用 await 的线程都在闸门处等待，直到某个线程调用 countDown 将其打开。以 N 初始化的 CountDownLatch 可用于让一个线程等待，直到 N 个线程各自完成某个动作，或某个动作被完成 N 次。
CountDownLatch 有一个有用特性：它不要求调用 countDown 的线程在继续之前等待计数归零，它只是阻止任何线程越过 await 继续，直到所有线程都可通过。

**内存一致性效果**：*在计数归零之前，某线程在调用 countDown() 之前的操作 happen-before 另一线程中对应 await() 成功返回之后的操作。*

Sync

```java
    /**
     * Synchronization control For CountDownLatch.
     * Uses AQS state to represent count.
     */
    private static final class Sync extends AbstractQueuedSynchronizer {
        private static final long serialVersionUID = 4982264981922014374L;

        Sync(int count) {
            setState(count);
        }

        int getCount() {
            return getState();
        }

        protected int tryAcquireShared(int acquires) {
            return (getState() == 0) ? 1 : -1;
        }

        protected boolean tryReleaseShared(int releases) {
            // Decrement count; signal when transition to zero
            for (;;) {
                int c = getState();
                if (c == 0)
                    return false;
                int nextc = c-1;
                if (compareAndSetState(c, nextc))
                    return nextc == 0;
            }
        }
    }
```





## await
导致当前线程等待，直到锁存器计数归零，除非线程被中断，或指定的等待时间耗尽。
1. 若当前计数为零，则该方法立即以 true 返回。
2. 若当前计数大于零，则当前线程被禁用调度并陷入休眠，直到以下三件事之一发生：
   1. 因调用 countDown 方法使计数归零；或
   2. 其他线程中断了当前线程；或
   3. 指定的等待时间耗尽。
3. 若计数已归零，则该方法以 true 返回。
4. 若当前线程：
      1. 在进入该方法时中断状态已置位；
      2. 或在等待期间被中断，则抛出 InterruptedException，且当前线程的中断状态被清除。
5. 若指定的等待时间耗尽，则返回 false。若时间小于等于零，则该方法根本不等待。

```java
public boolean await(long timeout, TimeUnit unit)
    throws InterruptedException {
    return sync.tryAcquireSharedNanos(1, unit.toNanos(timeout));
}

// in AQS
public final boolean tryAcquireSharedNanos(int arg, long nanosTimeout)
        throws InterruptedException {
    if (Thread.interrupted())
        throw new InterruptedException();
    return tryAcquireShared(arg) >= 0 ||
        doAcquireSharedNanos(arg, nanosTimeout);
}

protected int tryAcquireShared(int acquires) {
    return (getState() == 0) ? 1 : -1;
}
```



## countDown

使锁存器计数递减，若计数因此归零，则释放所有等待线程（参见 [shared release in AQS](/docs/CS/Java/JDK/Concurrency/AQS.md?id=propagation)）。
- 若当前计数大于零，则将其递减。若新计数为零，则所有等待线程重新被启用调度。
- 若当前计数已为零，则什么也不发生。



```java
public void countDown() {
    sync.releaseShared(1);
}

protected boolean tryReleaseShared(int releases) {
    for (;;) {
        int c = getState();
```
检查 c == 0，以避免在 [await](/docs/CS/Java/JDK/Concurrency/CountDownLatch.md?id=await) 时变为负数
```java
        if (c == 0)
            return false;
        int nextc = c-1;
        if (compareAndSetState(c, nextc))
            return nextc == 0;
    }
}
```

## Example


CountDownLatch 有一个有用特性：它不要求调用 countDown 的线程在继续之前等待计数归零，它只是阻止任何线程越过 await 继续，直到所有线程都可通过。

 下面是一对类的示例，其中一组工作线程使用了两个倒计时锁存器：
第一个是启动信号，阻止任何工作线程继续，直到驱动线程准备好让它们继续；
第二个是完成信号，让驱动线程能够等待，直到所有工作线程都已完成。

```java
class Driver { // ...
   void main() throws InterruptedException {
     CountDownLatch startSignal = new CountDownLatch(1);
     CountDownLatch doneSignal = new CountDownLatch(N);

     for (int i = 0; i < N; ++i) // create and start threads
       new Thread(new Worker(startSignal, doneSignal)).start();

     doSomethingElse();            // don't let run yet
     startSignal.countDown();      // let all threads proceed
     doSomethingElse();
     doneSignal.await();           // wait for all to finish
   }
 }

 class Worker implements Runnable {
   private final CountDownLatch startSignal;
   private final CountDownLatch doneSignal;
   Worker(CountDownLatch startSignal, CountDownLatch doneSignal) {
     this.startSignal = startSignal;
     this.doneSignal = doneSignal;
   }
   public void run() {
     try {
       startSignal.await();
       doWork();
       doneSignal.countDown();
     } catch (InterruptedException ex) {} // return;
   }

   void doWork() { ... }
 }
```



另一种典型用法是将一个问题拆分为 N 部分，用执行该部分并在锁存器上倒计时的 Runnable 描述每一部分，然后把所有 Runnable 提交到一个 Executor。当所有子部分都完成后，协调线程就能通过 await。（如果线程必须这样反复倒计时，应改用 CyclicBarrier。）

```java
class Driver2 { // ...
   void main() throws InterruptedException {
     CountDownLatch doneSignal = new CountDownLatch(N);
     Executor e = ...

     for (int i = 0; i < N; ++i) // create and start threads
       e.execute(new WorkerRunnable(doneSignal, i));

     doneSignal.await();           // wait for all to finish
   }
 }

 class WorkerRunnable implements Runnable {
   private final CountDownLatch doneSignal;
   private final int i;
   WorkerRunnable(CountDownLatch doneSignal, int i) {
     this.doneSignal = doneSignal;
     this.i = i;
   }
   public void run() {
     try {
       doWork(i);
       doneSignal.countDown();
     } catch (InterruptedException ex) {} // return;
   }

   void doWork() { ... }
 }
```



## Summary


1. 基于 AQS 实现
2. 使用共享锁（sharedLock）
3. 仅当 state 非零时阻塞调用 `await` 方法的线程
4. 计数递减至 0 且不可重置



## Links
- [Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
- [AQS](/docs/CS/Java/JDK/Concurrency/AQS.md)
