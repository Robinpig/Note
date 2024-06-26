
## Timer
The Timer facility manages the execution of deferred (“run this task in 100 ms”) and periodic (“run this task every 10 ms”) tasks.
However, Timer has some drawbacks, and ScheduledThreadPoolExecutor should be thought of as its replacement.
You can construct a ScheduledThreadPoolExecutor through its constructor or through the newScheduledThreadPool factory.

Timer does have support for scheduling based on absolute, not relative time, so that tasks can be sensitive to changes in the system clock;
ScheduledThreadPoolExecutor supports only relative time.

A Timer creates only a single thread for executing timer tasks. 
If a timer task takes too long to run, the timing accuracy of other TimerTasks can suffer. 
If a recurring TimerTask is scheduled to run every 10 ms and another Timer-Task takes 40 ms to run, 
the recurring task either (depending on whether it was scheduled at fixed rate or fixed delay) gets called four times in rapid succession after the long-running task completes, 
or “misses” four invocations completely. 
Scheduled thread pools address this limitation by letting you provide multiple threads for executing deferred and periodic tasks.

Another problem with Timer is that it behaves poorly if a TimerTask throws an unchecked exception. 
The Timer thread doesn't catch the exception, so an unchecked exception thrown from a TimerTask terminates the timer thread. 
Timer also doesn't resurrect the thread in this situation; instead, it erroneously assumes the entire Timer was cancelled. In this case, 
TimerTasks that are already scheduled but not yet executed are never run, and new tasks cannot be scheduled.(This problem, called “`thread leakage`”.)




## ScheduledExecutorService
An ExecutorService that can schedule commands to run after a given delay, or to execute periodically.

The schedule methods create tasks with various delays and return a task object that can be used to cancel or check execution. 
The scheduleAtFixedRate and scheduleWithFixedDelay methods create and execute tasks that run periodically until cancelled.

Commands submitted using the Executor.execute(Runnable) and ExecutorService submit methods are scheduled with a requested delay of zero. 
Zero and negative delays (but not periods) are also allowed in schedule methods, and are treated as requests for immediate execution.

All schedule methods accept relative delays and periods as arguments, not absolute times or dates. 
It is a simple matter to transform an absolute time represented as a java.util.Date to the required form. 
For example, to schedule at a certain future date, you can use: schedule(task, date.getTime() - System.currentTimeMillis(), TimeUnit.MILLISECONDS). 
Beware however that expiration of a relative delay need not coincide with the current Date at which the task is enabled due to network time synchronization protocols, clock drift, or other factors.

The Executors class provides convenient factory methods for the ScheduledExecutorService implementations provided in this package.




```java
public interface ScheduledExecutorService extends ExecutorService {

    public ScheduledFuture<?> schedule(Runnable command,
                                       long delay, TimeUnit unit);

    public <V> ScheduledFuture<V> schedule(Callable<V> callable,
                                           long delay, TimeUnit unit);

    public ScheduledFuture<?> scheduleAtFixedRate(Runnable command,
                                                  long initialDelay,
                                                  long period,
                                                  TimeUnit unit);
    
    public ScheduledFuture<?> scheduleWithFixedDelay(Runnable command,
                                                     long initialDelay,
                                                     long delay,
                                                     TimeUnit unit);

}
```

### Usage Example
Here is a class with a method that sets up a ScheduledExecutorService to beep every ten seconds for an hour:

```java
import static java.util.concurrent.TimeUnit.*;
class BeeperControl {
    private final ScheduledExecutorService scheduler =
            Executors.newScheduledThreadPool(1);

    public void beepForAnHour() {
        final Runnable beeper = new Runnable() {
            public void run() { System.out.println("beep"); }
        };
        final ScheduledFuture<?> beeperHandle =
                scheduler.scheduleAtFixedRate(beeper, 10, 10, SECONDS);
        scheduler.schedule(new Runnable() {
            public void run() { beeperHandle.cancel(true); }
        }, 60 * 60, SECONDS);
    }
}
```



## ScheduledThreadPoolExecutor

This class specializes ThreadPoolExecutor implementation by

1. Using a custom task type, ScheduledFutureTask for tasks, even those that don't require scheduling (i.e., those submitted using ExecutorService execute, not ScheduledExecutorService methods) which are treated as delayed tasks with a delay of zero.
2. Using a custom queue (DelayedWorkQueue), a variant of unbounded DelayQueue. The lack of capacity constraint and the fact that corePoolSize and maximumPoolSize are effectively identical simplifies some execution mechanics (see delayedExecute) compared to ThreadPoolExecutor.
3. Supporting optional run-after-shutdown parameters, which leads to overrides of shutdown methods to remove and cancel tasks that should NOT be run after shutdown, as well as different recheck logic when task (re)submission overlaps with a shutdown.
4. Task decoration methods to allow interception and instrumentation, which are needed because subclasses cannot otherwise override submit methods to get this effect. These don't have any impact on pool control logic though.





```java
public void run() {
    if (!canRunInCurrentRunState(this))
        cancel(false);
    else if (!isPeriodic())
        super.run();
    else if (super.runAndReset()) {
        setNextRunTime();
        reExecutePeriodic(outerTask);
    }
}
```



### compareTo

```java
public int compareTo(Delayed other) {
    if (other == this) // compare zero if same object
        return 0;
    if (other instanceof ScheduledFutureTask) {
        ScheduledFutureTask<?> x = (ScheduledFutureTask<?>)other;
        long diff = time - x.time;
        if (diff < 0)
            return -1;
        else if (diff > 0)
            return 1;
        else if (sequenceNumber < x.sequenceNumber)
            return -1;
        else
            return 1;
    }
    long diff = getDelay(NANOSECONDS) - other.getDelay(NANOSECONDS);
    return (diff < 0) ? -1 : (diff > 0) ? 1 : 0;
}
```



## scheduleAtFixedRate
Creates and executes a periodic action that becomes enabled first after the given initial delay, and subsequently with the given period; 
that is executions will commence after initialDelay then initialDelay+period, then initialDelay + 2 * period, and so on. 

**If any execution of the task encounters an exception, subsequent executions are suppressed.** 
Otherwise, the task will only terminate via cancellation or termination of the executor.

If any execution of this task takes longer than its period, then subsequent executions may start late, but will not concurrently execute.

```java
public ScheduledFuture<?> scheduleAtFixedRate(Runnable command,
                                              long initialDelay,
                                              long period,
                                              TimeUnit unit) {
    if (command == null || unit == null)
        throw new NullPointerException();
    if (period <= 0L)
        throw new IllegalArgumentException();
    ScheduledFutureTask<Void> sft =
        new ScheduledFutureTask<Void>(command,
                                      null,
                                      triggerTime(initialDelay, unit),
                                      unit.toNanos(period),
                                      sequencer.getAndIncrement());
    RunnableScheduledFuture<Void> t = decorateTask(command, sft);
    sft.outerTask = t;
    delayedExecute(t);
    return t;
}
```



## scheduleWithFixedDelay
Creates and executes a periodic action that becomes enabled first after the given initial delay, and subsequently with the given delay between the termination of one execution and the commencement of the next. If any execution of the task encounters an exception, subsequent executions are suppressed. Otherwise, the task will only terminate via cancellation or termination of the executor.

```java
public ScheduledFuture<?> scheduleWithFixedDelay(Runnable command,
                                                 long initialDelay,
                                                 long delay,
                                                 TimeUnit unit) {
    if (command == null || unit == null)
        throw new NullPointerException();
    if (delay <= 0L)
        throw new IllegalArgumentException();
    ScheduledFutureTask<Void> sft =
        new ScheduledFutureTask<Void>(command,
                                      null,
                                      triggerTime(initialDelay, unit),
                                      -unit.toNanos(delay),
                                      sequencer.getAndIncrement());
    RunnableScheduledFuture<Void> t = decorateTask(command, sft);
    sft.outerTask = t;
    delayedExecute(t);
    return t;
}
```





```java
private void delayedExecute(RunnableScheduledFuture<?> task) {
    if (isShutdown())
        reject(task);
    else {
        super.getQueue().add(task);
        if (!canRunInCurrentRunState(task) && remove(task))
            task.cancel(false);
        else
            ensurePrestart();
    }
}
```



Same as prestartCoreThread except arranges that at least one thread is started even if corePoolSize is 0.

```java
void ensurePrestart() {
    int wc = workerCountOf(ctl.get());
    if (wc < corePoolSize)
        addWorker(null, true);
    else if (wc == 0)
        addWorker(null, false);
}
```



## DelayedWorkQueue

A DelayedWorkQueue is based on a heap-based data structure like those in DelayQueue and [PriorityQueue](/docs/CS/Java/JDK/Collection/Queue.md?id=PriorityQueue), except that every ScheduledFutureTask also records its index into the heap array.
This eliminates the need to find a task upon cancellation, greatly speeding up removal (down from O(n) to O(log n)), and reducing garbage retention that would otherwise occur by waiting for the element to rise to top before clearing.
But because the queue may also hold RunnableScheduledFutures that are not ScheduledFutureTasks, we are not guaranteed to have such indices available, in which case we fall back to linear search. 
(We expect that most tasks will not be decorated, and that the faster cases will be much more common.)

Specialized delay queue. To mesh with TPE declarations, this class must be declared as a BlockingQueue  even though it can only hold RunnableScheduledFutures.

```java
static class DelayedWorkQueue extends AbstractQueue<Runnable>
    implements BlockingQueue<Runnable> {}
```



### take

```java
public RunnableScheduledFuture<?> take() throws InterruptedException {
    final ReentrantLock lock = this.lock;
    lock.lockInterruptibly();
    try {
        for (;;) {
            RunnableScheduledFuture<?> first = queue[0];
            if (first == null)
                available.await();
            else {
                long delay = first.getDelay(NANOSECONDS);
                if (delay <= 0L)
                    return finishPoll(first);
                first = null; // don't retain ref while waiting
                if (leader != null)
                    available.await();
                else {
                    Thread thisThread = Thread.currentThread();
                    leader = thisThread;
                    try {
                        available.awaitNanos(delay);
                    } finally {
                        if (leader == thisThread)
                            leader = null;
                    }
                }
            }
        }
    } finally {
        if (leader == null && queue[0] != null)
            available.signal();
        lock.unlock();
    }
}
```



### offer

```java
public boolean offer(Runnable x) {
    if (x == null)
        throw new NullPointerException();
    RunnableScheduledFuture<?> e = (RunnableScheduledFuture<?>)x;
    final ReentrantLock lock = this.lock;
    lock.lock();
    try {
        int i = size;
        if (i >= queue.length)
            grow();
        size = i + 1;
        if (i == 0) {
            queue[0] = e;
            setIndex(e, 0);
        } else {
            siftUp(i, e);
        }
        if (queue[0] == e) {
            leader = null;
            available.signal();
        }
    } finally {
        lock.unlock();
    }
    return true;
}
```
## Tuning

ScheduledThreadPoolExecutor内部对task做了catch, 出现异常的task将不再加入队列



## Links
- [ThreadPoolExecutor](/docs/CS/Java/JDK/Concurrency/ThreadPoolExecutor.md)

## References

1. [踩了定时线程池的坑，导致公司损失几千万，血的教训](https://mp.weixin.qq.com/s/nZNyF_DAdV3T8z07ALXOFg)