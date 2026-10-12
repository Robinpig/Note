## Introduction



一种同步辅助工具，允许**一组线程**互相等待，直到所有线程都到达一个共同的屏障点。
CyclicBarrier 是一个可重置的多路同步点，在某些并行编程风格中很有用。

CyclicBarrier 适用于这样的程序：其中一组固定数量的线程必须偶尔互相等待。
之所以称为「cyclic」（可循环），是因为它在等待的线程被释放后可以重复使用。
CyclicBarrier 支持一个可选的 Runnable 命令，该命令在每一轮屏障点、即方（party）中最后一个线程到达之后、但在任何线程被释放之前执行一次。
这个屏障动作对于在各方继续之前更新共享状态很有用。
示例用法：下面是一个在并行分解设计中使用屏障的例子：

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


这里，每个工作线程先处理矩阵的一行，然后在屏障处等待，直到所有行都处理完毕。当所有行都处理完后，所提供的 Runnable 屏障动作会被执行并合并各行。如果合并者判定已找到解，则 done() 返回 true，各工作线程随之终止。
如果屏障动作在执行时并不依赖各方处于挂起状态，那么方中任意一个线程在被释放时都可以执行该动作。为了方便这一点，每次调用 await 都会返回该线程在屏障处的到达序号（index）。于是你可以选择由哪个线程来执行屏障动作，例如：
```java
 if (barrier.await() == 0) {
   // log the completion of this iteration
 }
```


CyclicBarrier 对失败的同步尝试采用「全有或全无」的破坏模型：
如果某个线程因为中断、失败或超时而提前离开屏障点，
所有在该屏障点等待的其他线程也会异常离开，抛出 *BrokenBarrierException*（若它们也在大约同时被中断，则抛出 *InterruptedException*）。

**内存一致性效果**：
某线程在调用 await() 之前的操作 happen-before 属于屏障动作的操作，
而后者又 happen-before 其他线程中对应 await() 成功返回之后的操作。

```java
public CyclicBarrier(int parties, Runnable barrierAction) {
    if (parties <= 0) throw new IllegalArgumentException();
    this.parties = parties;
    this.count = parties;
    this.barrierCommand = barrierAction;
}
```



## await

等待，直到所有方（party）都在此屏障上调用了 await，或指定的等待时间耗尽。
如果当前线程不是最后一个到达的，则它被禁用调度并陷入休眠，直到以下之一发生：

1. 最后一个线程到达；或
2. 指定的超时时间耗尽；或
3. 其他线程中断了当前线程；或
4. 其他线程中断了某个其他等待中的线程；或
5. 其他线程在等待屏障时超时；或
6. 其他线程在此屏障上调用了 reset。

如果当前线程：

1. 进入该方法时中断状态已置位；或
2. 在等待期间被中断，

则抛出 InterruptedException，且当前线程的中断状态被清除。

如果指定的等待时间耗尽，则抛出 TimeoutException。若时间小于等于零，该方法根本不等待。
如果在任何线程等待期间屏障被重置，或当调用 await 时屏障已损坏，或在任意线程等待期间屏障损坏，则抛出 *BrokenBarrierException*。
如果任意线程在等待期间被中断，则所有其他等待线程都会抛出 BrokenBarrierException，并且屏障进入损坏（broken）状态。
如果当前线程是最后一个到达的，且构造时提供了非空的屏障动作，则当前线程会在允许其他线程继续之前先运行该动作。若屏障动作执行过程中发生异常，该异常会在当前线程中传播，并且屏障进入损坏状态。

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

CyclicBarrier 会在 count == 0 或调用 `reset` 方法时创建新的 `Generation`，因此要确保线程数量是 parties 的整数倍，否则会在 `await` 处阻塞。

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

由 `dowait` 或 `reset` 调用

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

将屏障重置为初始状态。如果当前有任何方正在屏障处等待，它们将返回并抛出 BrokenBarrierException。注意，若屏障已因其他原因损坏，随后的重置操作可能比较复杂：线程需要以其他方式重新同步，并选定其中一个来执行重置。更可取的做法或许是为后续使用直接创建一个新的屏障。

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
| 内部类      | ReentrantLock & Condition | Sync extends AbstractQueuedSynchronizer |
| 可重用            | :white_check_mark:        | :x:                                     |
| 计数            | 与线程数相同    | -                                       |
| 阻塞方法     | `await`                   | `await`                                 |
| 递减方法 | `await`                   | `countDwon`                             |


## Links
- [Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
- [AQS](/docs/CS/Java/JDK/Concurrency/AQS.md)
