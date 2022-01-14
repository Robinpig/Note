## Introduction



A synchronization aid that allows **a set of threads** to all wait for each other to reach a common barrier point. 
CyclicBarriers are useful in programs involving a fixed sized party of threads that must occasionally wait for each other. 
The barrier is called cyclic because it can be re-used after the waiting threads are released.
A CyclicBarrier supports an optional Runnable command that is run once per barrier point, after the last thread in the party arrives, 
but before any threads are released. This barrier action is useful for updating shared-state before any of the parties continue.
Sample usage: Here is an example of using a barrier in a parallel decomposition design:

```java
 class Solver {
   final int N;
   final float[][] data;
   final CyclicBarrier barrier;

   class Worker implements Runnable {
     int myRow;
     Worker(int row) { myRow = row; }
     public void run() {
       while (!done()) {
         processRow(myRow);

         try {
           barrier.await();
         } catch (InterruptedException ex) {
           return;
         } catch (BrokenBarrierException ex) {
           return;
         }
       }
     }
   }

   public Solver(float[][] matrix) {
     data = matrix;
     N = matrix.length;
     Runnable barrierAction =
       new Runnable() { public void run() { mergeRows(...); }};
     barrier = new CyclicBarrier(N, barrierAction);

     List<Thread> threads = new ArrayList<Thread>(N);
     for (int i = 0; i < N; i++) {
       Thread thread = new Thread(new Worker(i));
       threads.add(thread);
       thread.start();
     }
    
     // wait until done
     for (Thread thread : threads)
       thread.join();
   }
 }
```


Here, each worker thread processes a row of the matrix then waits at the barrier until all rows have been processed. When all rows are processed the supplied Runnable barrier action is executed and merges the rows. If the merger determines that a solution has been found then done() will return true and each worker will terminate.
If the barrier action does not rely on the parties being suspended when it is executed, then any of the threads in the party could execute that action when it is released. To facilitate this, each invocation of await returns the arrival index of that thread at the barrier. You can then choose which thread should execute the barrier action, for example:
```java
 if (barrier.await() == 0) {
   // log the completion of this iteration
 }
```


The CyclicBarrier uses an all-or-none breakage model for failed synchronization attempts: 
If a thread leaves a barrier point prematurely because of interruption, failure, or timeout, 
all other threads waiting at that barrier point will also leave abnormally via *BrokenBarrierException* (or *InterruptedException* 
if they too were interrupted at about the same time).

**Memory consistency effects**: 
Actions in a thread prior to calling await() happen-before actions that are part of the barrier action, 
which in turn happen-before actions following a successful return from the corresponding await() in other threads.

```java
public CyclicBarrier(int parties, Runnable barrierAction) {
    if (parties <= 0) throw new IllegalArgumentException();
    this.parties = parties;
    this.count = parties;
    this.barrierCommand = barrierAction;
}
```



## await

Waits until all parties have invoked await on this barrier, or the specified waiting time elapses.
If the current thread is not the last to arrive then it is disabled for thread scheduling purposes and lies dormant until one of the following things happens:

1. The last thread arrives; or
2. The specified timeout elapses; or
3. Some other thread interrupts the current thread; or
4. Some other thread interrupts one of the other waiting threads; or
5. Some other thread times out while waiting for barrier; or
6. Some other thread invokes reset on this barrier.

If the current thread:

1. has its interrupted status set on entry to this method; or
2. is interrupted while waiting

then InterruptedException is thrown and the current thread's interrupted status is cleared.

If the specified waiting time elapses then TimeoutException is thrown. If the time is less than or equal to zero, the method will not wait at all.
If the barrier is reset while any thread is waiting, or if the barrier is broken when await is invoked, or while any thread is waiting, then *BrokenBarrierException* is thrown.
If any thread is interrupted while waiting, then all other waiting threads will throw BrokenBarrierException and the barrier is placed in the broken state.
If the current thread is the last thread to arrive, and a non-null barrier action was supplied in the constructor, then the current thread runs the action before allowing the other threads to continue. If an exception occurs during the barrier action then that exception will be propagated in the current thread and the barrier is placed in the broken state.

```java
public int await(long timeout, TimeUnit unit)
    throws InterruptedException,
           BrokenBarrierException,
           TimeoutException {
    return dowait(true, unit.toNanos(timeout));
}

// Main barrier code, covering the various policies.
private int dowait(boolean timed, long nanos)
    throws InterruptedException, BrokenBarrierException,
           TimeoutException {
    final ReentrantLock lock = this.lock;
    lock.lock();
    try {
        final Generation g = generation;

        if (g.broken)
            throw new BrokenBarrierException();

        if (Thread.interrupted()) {
            breakBarrier();
            throw new InterruptedException();
        }

        int index = --count;
        if (index == 0) {  // tripped
            boolean ranAction = false;
            try {
                final Runnable command = barrierCommand;
                if (command != null)
                    command.run();
                ranAction = true;
                nextGeneration();
                return 0;
            } finally {
                if (!ranAction)
                    breakBarrier();
            }
        }

        // loop until tripped, broken, interrupted, or timed out
        for (;;) {
            try {
              	// Condition.await()
                if (!timed)
                    trip.await();
                else if (nanos > 0L)
                    nanos = trip.awaitNanos(nanos);
            } catch (InterruptedException ie) {
                if (g == generation && ! g.broken) {
                    breakBarrier();
                    throw ie;
                } else {
                    // We're about to finish waiting even if we had not
                    // been interrupted, so this interrupt is deemed to
                    // "belong" to subsequent execution.
                    Thread.currentThread().interrupt();
                }
            }

            if (g.broken)
                throw new BrokenBarrierException();

            if (g != generation)
                return index;

            if (timed && nanos <= 0L) {
                breakBarrier();
                throw new TimeoutException();
            }
        }
    } finally {
        lock.unlock();
    }
}
```

CyclicBarrier will new `Generation` when count == 0 || call `reset` method, so make sure num of threads is a multiple of parties or block at `await`.

## breakBarrier

```java
/**
 * Sets current barrier generation as broken and wakes up everyone.
 * Called only while holding lock.
 */
private void breakBarrier() {
    generation.broken = true;
    count = parties;
    trip.signalAll();
}
```



## nextGeneration

called by `dowait` or `reset`

```java
/**
 * Updates state on barrier trip and wakes up everyone.
 * Called only while holding lock.
 */
private void nextGeneration() {
    // signal completion of last generation
    trip.signalAll();
    // set up next generation
    count = parties;
    generation = new Generation();
}
```



### reset

Resets the barrier to its initial state. If any parties are currently waiting at the barrier, they will return with a BrokenBarrierException. Note that resets after a breakage has occurred for other reasons can be complicated to carry out; threads need to re-synchronize in some other way, and choose one to perform the reset. It may be preferable to instead create a new barrier for subsequent use.

```java
public void reset() {
    final ReentrantLock lock = this.lock;
    lock.lock();
    try {
        breakBarrier();   // break the current generation
        nextGeneration(); // start a new generation
    } finally {
        lock.unlock();
    }
}
```



### Generation

```java
    /**
     * Each use of the barrier is represented as a generation instance.
     * The generation changes whenever the barrier is tripped, or
     * is reset. There can be many generations associated with threads
     * using the barrier - due to the non-deterministic way the lock
     * may be allocated to waiting threads - but only one of these
     * can be active at a time (the one to which {@code count} applies)
     * and all the rest are either broken or tripped.
     * There need not be an active generation if there has been a break
     * but no subsequent reset.
     */
    private static class Generation {
        boolean broken = false;
    }
```



## CyclicBarrier vs CountDownLatch



|                  | CyclicBarrier             | CountDownLatch                          |
| ---------------- | ------------------------- | --------------------------------------- |
| Inner Class      | ReentrantLock & Condition | Sync extends AbstractQueuedSynchronizer |
| Reuse            | :white_check_mark:        | :x:                                     |
| Count            | same as Threads Number    | -                                       |
| Block method     | `await`                   | `await`                                 |
| Decrement method | `await`                   | `countDwon`                             |

