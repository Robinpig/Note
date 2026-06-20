## Introduction



A synchronization aid that allows **one or more threads** to wait until **a set of operations** being performed in other threads completes.
CountDownLatch is a very simple yet very common utility for blocking until a given number of signals, events, or conditions hold.

A CountDownLatch is initialized with a given count. The await methods block until the current count reaches zero due to invocations of the countDown method, after which all waiting threads are released and any subsequent invocations of await return immediately. This is a one-shot phenomenon -- the count cannot be reset. If you need a version that resets the count, consider using a **CyclicBarrier**.
A CountDownLatch is a versatile synchronization tool and can be used for a number of purposes. A CountDownLatch initialized with a count of one serves as a simple on/off latch, or gate: all threads invoking await wait at the gate until it is opened by a thread invoking countDown. A CountDownLatch initialized to N can be used to make one thread wait until N threads have completed some action, or some action has been completed N times.
A useful property of a CountDownLatch is that it doesn't require that threads calling countDown wait for the count to reach zero before proceeding, it simply prevents any thread from proceeding past an await until all threads could pass.

**Memory consistency effects**: *Until the count reaches zero, actions in a thread prior to calling countDown() happen-before actions following a successful return from a corresponding await() in another thread.*

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
Causes the current thread to wait until the latch has counted down to zero, unless the thread is interrupted, or the specified waiting time elapses.
1. If the current count is zero then this method returns immediately with the value true.
2. If the current count is greater than zero then the current thread becomes disabled for thread scheduling purposes and lies dormant until one of three things happen:
   1. The count reaches zero due to invocations of the countDown method; or
   2. Some other thread interrupts the current thread; or
   3. The specified waiting time elapses.
3. If the count reaches zero then the method returns with the value true.
4. If the current thread:
      1. has its interrupted status set on entry to this method; 
      2. or is interrupted while waiting, then InterruptedException is thrown and the current thread's interrupted status is cleared.
5. If the specified waiting time elapses then the value false is returned. If the time is less than or equal to zero, the method will not wait at all.

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

Decrements the count of the latch, releasing all waiting threads(see [doReleaseShared in AQS](/docs/CS/Java/JDK/Concurrency/AQS.md?id=doReleaseShared)) if the count reaches zero.
- If the current count is greater than zero then it is decremented. If the new count is zero then all waiting threads are re-enabled for thread scheduling purposes.
- If the current count equals zero then nothing happens.



```java
public void countDown() {
    sync.releaseShared(1);
}

protected boolean tryReleaseShared(int releases) {
    for (;;) {
        int c = getState();
```
check if c == 0 to avoid being negative when [await](/docs/CS/Java/JDK/Concurrency/CountDownLatch.md?id=await)
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


A useful property of a CountDownLatch is that it doesn't require that threads calling countDown wait for the count to reach zero before proceeding, it simply prevents any thread from proceeding past an await until all threads could pass.

 Here is a pair of classes in which a group of worker threads use two countdown latches:
The first is a start signal that prevents any worker from proceeding until the driver is ready for them to proceed;
The second is a completion signal that allows the driver to wait until all workers have completed.

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



Another typical usage would be to divide a problem into N parts, describe each part with a Runnable that executes that portion and counts down on the latch, and queue all the Runnables to an Executor. When all sub-parts are complete, the coordinating thread will be able to pass through await. (When threads must repeatedly count down in this way, instead use a CyclicBarrier.)

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


1. Implement AQS
2. Use sharedLock
3. only block threads which call `await` method when state not zero
4. Decrement state -> 0 and can not reset



## Links
- [Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
- [AQS](/docs/CS/Java/JDK/Concurrency/AQS.md)