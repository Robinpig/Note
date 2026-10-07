## Introduction

本文主要基于 Java 语言梳理实现定时任务的方式：从单机 `Timer` / `ScheduledThreadPoolExecutor`，到中间件场景的时间轮，再到分布式调度框架。

## 任务模型

- Cron
- Fixed Delay
- Fixed Rate
- One Time 一次性任务
  适用日历提醒、订单超时自动关闭。因为 Job 占用资源较多，当任务量过大时可使用 MQ 做定时消息，或者秒级 Map 任务扫库处理

## 任务分配

- 单机
- 广播
- MapReduce 模型

## 单机定时任务

Timer 是 JDK 内置的定时器，单线程搭配小顶堆的设计，Oracle 官方文档明确指出彻底弃用 Timer（源码解析见下文 [Timer 源码解析](#timer-源码解析)）。

从 Timer 的实现总结分析，对任务的优先级排序需要一个优先级队列，JDK 内置的 `DelayQueue` 可以实现。在此基础上封装的 `ScheduledThreadPoolExecutor` 能实现更精细地管理（源码解析见下文 [ScheduledThreadPoolExecutor 源码解析](#scheduledthreadpoolexecutor-源码解析)）。Spring Task 底层就是基于 JDK 的 `ScheduledThreadPoolExecutor` 线程池来实现的。

| 维度             | `Timer`                                                      | `ScheduledThreadPoolExecutor`                                |
| ---------------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| **线程模型**     | 单后台线程（所有任务串行执行）                               | 可配置线程池（支持并发执行）                                 |
| **异常处理**     | 脆弱：单个任务抛出未捕获异常会导致整个 Timer 线程终止，后续任务全部取消 | 健壮：捕获异常并记录，隔离故障任务，其他任务继续执行         |
| **API 设计**     | 继承 `TimerTask`，`schedule()` 返回 `void`                   | 直接接受 `Runnable`/`Callable`，返回 `ScheduledFuture<V>`（支持取消、查询状态） |
| **调度精度**     | 固定延迟/固定频率易受单线程阻塞影响，产生累积漂移            | 基于 `DelayedWorkQueue` + 纳秒时钟，固定频率模式支持自动“追赶”执行 |
| **生命周期管理** | `cancel()` 仅标记取消，线程可能常驻内存；不支持优雅关闭      | 完整实现 `ExecutorService` 生命周期，支持 `shutdown()`、`awaitTermination()`、线程池监控 |

两者都支持 `fixedDelay`（固定延迟）和 `fixedRate`（固定频率），但实现健壮性不同：

- **Timer**：`scheduleAtFixedRate` 在任务阻塞时会产生“堆积”，恢复后可能连续快速执行多次（追赶机制不完善）。
- **ScheduledThreadPoolExecutor**：严格遵循 `ScheduledExecutorService` 契约，`fixedRate` 模式会记录理论触发时间，阻塞恢复后仅执行**错过的最后一次**，避免雪崩。

## Timer 源码解析

虽然 `Timer` 已被官方弃用（`@Deprecated(forRemoval = true)`），但它是理解 Java 定时任务模型最直观的样本：从它的「单线程 + 小顶堆」出发，才能看清 `ScheduledThreadPoolExecutor` 为什么要改造成「可配置线程池 + `DelayedWorkQueue`」。

`Timer` 中有两个核心组件，一个是用于调度延时任务的 `TimerThread`，另一个是 `TaskQueue`，用于组织延时任务。

```java
public class Timer {
    /**
     * The timer task queue.  This data structure is shared with the timer
     * thread.  The timer produces tasks, via its various schedule calls,
     * and the timer thread consumes, executing timer tasks as appropriate,
     * and removing them from the queue when they're obsolete.
     */
    private final TaskQueue queue = new TaskQueue();

    private final TimerThread thread = new TimerThread(queue);

    /**
     * This object causes the timer's task execution thread to exit
     * gracefully when there are no live references to the Timer object and no
     * tasks in the timer queue.  It is used in preference to a finalizer on
     * Timer as such a finalizer would be susceptible to a subclass's
     * finalizer forgetting to call it.
     */
    private final Object threadReaper = new Object() {
        protected void finalize() throws Throwable {
            synchronized(queue) {
                thread.newTasksMayBeScheduled = false;
                queue.notify(); // In case queue is empty.
            }
        }
    };

    /**
     * This ID is used to generate thread names.
     */
    private final static AtomicInteger nextSerialNumber = new AtomicInteger(0);
}
```

### TaskQueue

`TaskQueue` 是一个优先级队列，其底层是一个数组实现的小根堆。`TaskQueue` 会将所有延时任务按照它们的 `ExecutionTime`，由近到远地组织在小根堆中，堆顶永远存放的是 `ExecutionTime` 最近的延时任务。

```java
class TaskQueue {
    /**
     * Priority queue represented as a balanced binary heap: the two children
     * of queue[n] are queue[2*n] and queue[2*n+1].  The priority queue is
     * ordered on the nextExecutionTime field: The TimerTask with the lowest
     * nextExecutionTime is in queue[1] (assuming the queue is nonempty).  For
     * each node n in the heap, and each descendant of n, d,
     * n.nextExecutionTime <= d.nextExecutionTime.
     */
    private TimerTask[] queue = new TimerTask[128];

    /**
     * The number of tasks in the priority queue.  (The tasks are stored in
     * queue[1] up to queue[size]).
     */
    private int size = 0;

    /**
     * Returns the number of tasks currently on the queue.
     */
    int size() {
        return size;
    }

    /**
     * Adds a new task to the priority queue.
     */
    void add(TimerTask task) {
        // Grow backing store if necessary
        if (size + 1 == queue.length)
            queue = Arrays.copyOf(queue, 2*queue.length);

        queue[++size] = task;
        fixUp(size);
    }

    /**
     * Return the "head task" of the priority queue.  (The head task is an
     * task with the lowest nextExecutionTime.)
     */
    TimerTask getMin() {
        return queue[1];
    }

    /**
     * Remove the head task from the priority queue.
     */
    void removeMin() {
        queue[1] = queue[size];
        queue[size--] = null;  // Drop extra reference to prevent memory leak
        fixDown(1);
    }
}
```

### TimerThread

`TimerThread` 会不断地从 `TaskQueue` 中获取堆顶任务，如果堆顶任务的 `ExecutionTime` 已经达到 —— `executionTime <= currentTime`，则执行任务。如果该任务是一个周期性任务，则将任务重新放入到 `TaskQueue` 中。

如果堆顶任务的 `ExecutionTime` 还没有到达，那么 `TimerThread` 就会等待 `executionTime - currentTime` 的时间，一直到堆顶任务的执行时间到达，`TimerThread` 被重新唤醒执行堆顶任务。

```java
class TimerThread extends Thread {
    /**
     * This flag is set to false by the reaper to inform us that there
     * are no more live references to our Timer object.  Once this flag
     * is true and there are no more tasks in our queue, there is no
     * work left for us to do, so we terminate gracefully.  Note that
     * this field is protected by queue's monitor!
     */
    boolean newTasksMayBeScheduled = true;

    /**
     * Our Timer's queue.  We store this reference in preference to
     * a reference to the Timer so the reference graph remains acyclic.
     * Otherwise, the Timer would never be garbage-collected and this
     * thread would never go away.
     */
    private TaskQueue queue;

    TimerThread(TaskQueue queue) {
        this.queue = queue;
    }

    public void run() {
        try {
            mainLoop();
        } finally {
            // Someone killed this Thread, behave as if Timer cancelled
            synchronized(queue) {
                newTasksMayBeScheduled = false;
                queue.clear();  // Eliminate obsolete references
            }
        }
    }
}
```

#### mainLoop

```java
class TimerThread extends Thread {
    /**
     * The main timer loop.  (See class comment.)
     */
    private void mainLoop() {
        while (true) {
            try {
                TimerTask task;
                boolean taskFired;
                synchronized(queue) {
                    // Wait for queue to become non-empty
                    while (queue.isEmpty() && newTasksMayBeScheduled)
                        queue.wait();
                    if (queue.isEmpty())
                        break; // Queue is empty and will forever remain; die

                    // Queue nonempty; look at first evt and do the right thing
                    long currentTime, executionTime;
                    task = queue.getMin();
                    synchronized(task.lock) {
                        if (task.state == TimerTask.CANCELLED) {
                            queue.removeMin();
                            continue;  // No action required, poll queue again
                        }
                        currentTime = System.currentTimeMillis();
                        executionTime = task.nextExecutionTime;
                        if (taskFired = (executionTime<=currentTime)) {
                            if (task.period == 0) { // Non-repeating, remove
                                queue.removeMin();
                                task.state = TimerTask.EXECUTED;
                            } else { // Repeating task, reschedule
                                queue.rescheduleMin(
                                    task.period<0 ? currentTime   - task.period
                                    : executionTime + task.period);
                            }
                        }
                    }
                    if (!taskFired) // Task hasn't yet fired; wait
                        queue.wait(executionTime - currentTime);
                }
                if (taskFired)  // Task fired; run it, holding no locks
                    task.run();
            } catch(InterruptedException e) {
            }
        }
    }
}
```

### Timer 的四个缺陷

根据以上 `Timer` 的核心实现，我们可以总结出 `Timer` 在应对中间件场景的延时任务时，有以下四种不足：

1. 首先用于组织延时任务的 `TaskQueue` 本质上是一个小根堆。对于堆这种数据结构来说，添加、删除一个延时任务时，堆都要向上、向下调整以便满足小根堆的特性，单次操作的时间复杂度为 O(logn)。显然在面对海量定时任务的添加、删除时，性能上还是差点意思。
2. `Timer` 调度框架中只有一个 `TimerThread` 线程来负责延时任务的调度、执行。在面对海量任务的时候，通常会显得力不从心。
3. 另外一个严重问题是，当延时任务在执行的过程中出现异常时，`Timer` 并不会捕获，会导致 `TimerThread` 终止。这样一来，`TaskQueue` 中的其他延时任务将永远不会得到执行。官方把这个问题称为 **thread leakage**（线程泄漏）：`TimerThread` 不会复活，反而错误地认为整个 `Timer` 已被取消——已排队但未执行的任务不再运行，新任务也无法再调度。
4. `Timer` 依赖于系统的**绝对时间**（`System.currentTimeMillis()`），如果系统时间本身不准确，那么延时任务的调度就可能会出问题；而 `ScheduledThreadPoolExecutor` 只支持**相对时间**，不受系统时钟调整影响。

此外，`Timer` 只创建一个线程执行任务：若某个任务运行过久，其他任务的计时精度都会受影响——比如一个每 10ms 执行一次的周期任务，遇到一个耗时 40ms 的任务后，要么在长任务完成后短时间内被连续调用四次（固定频率下「追赶」），要么完全「错过」四次调用。

## ScheduledThreadPoolExecutor 源码解析

`ScheduledThreadPoolExecutor` 是 `Timer` 的官方推荐替代。它在 [ThreadPoolExecutor](/docs/CS/Java/JDK/Concurrency/ThreadPoolExecutor.md) 之上做了四点定制：

1. 使用自定义任务类型 `ScheduledFutureTask`（即使是不需要调度的任务——即那些通过 `ExecutorService.submit` 提交的，也被当作延迟 0 的任务处理）。
2. 使用自定义队列 `DelayedWorkQueue`（无界 `DelayQueue` 的变体）。无容量约束，且 `corePoolSize` 与 `maximumPoolSize` 实际相等，简化了部分执行机制（见 `delayedExecute`），相比 `ThreadPoolExecutor` 更简单。
3. 支持可选的「shutdown 后仍运行」参数，因此覆写 shutdown 方法以移除并取消那些**不应在 shutdown 后运行**的任务，并在任务（重新）提交与 shutdown 重叠时采用不同的 recheck 逻辑。
4. 提供任务装饰方法以允许拦截与 instrumentation（子类无法覆写 submit 方法来达到同样效果）。这些对池控制逻辑没有影响。

### ScheduledExecutorService

An ExecutorService that can schedule commands to run after a given delay, or to execute periodically.

The schedule methods create tasks with various delays and return a task object that can be used to cancel or check execution.
The `scheduleAtFixedRate` and `scheduleWithFixedDelay` methods create and execute tasks that run periodically until cancelled.

Commands submitted using the `Executor.execute(Runnable)` and `ExecutorService.submit` methods are scheduled with a requested delay of zero.
Zero and negative delays (but not periods) are also allowed in schedule methods, and are treated as requests for immediate execution.

All schedule methods accept relative delays and periods as arguments, not absolute times or dates.
It is a simple matter to transform an absolute time represented as a `java.util.Date` to the required form.
For example, to schedule at a certain future date, you can use: `schedule(task, date.getTime() - System.currentTimeMillis(), TimeUnit.MILLISECONDS)`.
Beware however that expiration of a relative delay need not coincide with the current Date at which the task is enabled due to network time synchronization protocols, clock drift, or other factors.

The `Executors` class provides convenient factory methods for the `ScheduledExecutorService` implementations provided in this package.

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

#### Usage Example

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

### run 机制

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

> [!TIP]
>
> If any execution of the task encounters an exception, subsequent executions are suppressed.
> 执行 run 方法时如果抛出 OOM 则不会执行 `setNextRunTime` 函数，该任务不会被再次调度执行。
> 正确做法是在任务内部 try-catch，**永远不要依赖线程池帮你兜底周期性任务的异常**。必须在 `Runnable` 内部捕获所有异常，确保 `run()` 方法正常返回。

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

### scheduleAtFixedRate

Creates and executes a periodic action that becomes enabled first after the given initial delay, and subsequently with the given period;
that is executions will commence after `initialDelay` then `initialDelay+period`, then `initialDelay + 2 * period`, and so on.

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

### scheduleWithFixedDelay

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

### delayedExecute 与 ensurePrestart

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

Same as `prestartCoreThread` except arranges that at least one thread is started even if `corePoolSize` is 0.

```java
void ensurePrestart() {
    int wc = workerCountOf(ctl.get());
    if (wc < corePoolSize)
        addWorker(null, true);
    else if (wc == 0)
        addWorker(null, false);
}
```

### DelayedWorkQueue

A `DelayedWorkQueue` is based on a heap-based data structure like those in `DelayQueue` and [PriorityQueue](/docs/CS/Java/JDK/Collection/Queue.md?id=priorityqueue), except that every `ScheduledFutureTask` also records its index into the heap array.
This eliminates the need to find a task upon cancellation, greatly speeding up removal (down from O(n) to O(log n)), and reducing garbage retention that would otherwise occur by waiting for the element to rise to top before clearing.
But because the queue may also hold `RunnableScheduledFutures` that are not `ScheduledFutureTasks`, we are not guaranteed to have such indices available, in which case we fall back to linear search.
(We expect that most tasks will not be decorated, and that the faster cases will be much more common.)

Specialized delay queue. To mesh with TPE declarations, this class must be declared as a `BlockingQueue` even though it can only hold `RunnableScheduledFutures`.

```java
static class DelayedWorkQueue extends AbstractQueue<Runnable>
    implements BlockingQueue<Runnable> {}
```

#### take

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

#### offer

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

### Tuning

`ScheduledThreadPoolExecutor` 内部对 task 做了 catch，出现异常的 task 将不再加入队列。

## 中间件场景定时任务

在中间件的场景中，同样存在很多定时任务的需求。比如，网络连接的心跳检测，网络请求超时或失败的重试机制，网络连接断开之后的重连机制。

和业务场景不同的是，这些中间件场景的定时任务特点是逻辑简单，执行时间非常短，而且对时间精度的要求比较低。比如，心跳检测以及失败重试这些定时任务，其实晚执行个几十毫秒或者 100 毫秒也无所谓。

中间件场景定时任务特点：

1. 海量任务
2. 逻辑简单
3. 执行时间短
4. 任务调度的及时性要求不高

Kafka、Dubbo、ZooKeeper、Netty、Caffeine、Akka 中都有对时间轮的实现。

Netty 的 [HashedWheelTimer](/docs/CS/Framework/Netty/HashedWheelTimer.md) 是一个单层时间轮设计，通过一个 workerThread 每隔 tickDuration（100ms）将时钟 tick 向前推进一格。

Kafka 的 [Hierarchical Timing Wheels](/docs/CS/MQ/Kafka/Timer.md) 的多层时间轮设计，巧妙地解决了时间轮的空推进现象和海量延时任务时间跨度大的管理问题。

## 分布式定时任务

如果我们需要一些高级特性比如支持任务在分布式场景下的分片和高可用的话，我们就需要用到分布式任务调度框架了。

通常情况下，一个分布式定时任务的执行往往涉及到下面这些角色：

- 任务：首先肯定是要执行的任务，这个任务就是具体的业务逻辑比如定时发送文章。
- 调度器：其次是调度中心，调度中心主要负责任务管理，会分配任务给执行器。
- 执行器：最后就是执行器，执行器接收调度器分派的任务并执行。

[Quartz](/docs/CS/Framework/Job/Quartz/Quartz.md) 可以说是 Java 定时任务领域的老大哥或者说参考标准，其他的任务调度框架基本都是基于 Quartz 开发的，比如当当网的 [Elastic-job](/docs/CS/Framework/Job/ElasticJob.md) 就是基于 Quartz 二次开发之后的分布式调度解决方案。Quartz 虽然也支持分布式任务，但是，它是在数据库层面，通过数据库的锁机制做的，有非常多的弊端比如系统侵入性严重、节点负载不均衡。有点伪分布式的味道。

[XXL-JOB](/docs/CS/Framework/Job/xxl-job.md) 于 2015 年开源，是一款优秀的轻量级分布式任务调度框架，支持任务可视化管理、弹性扩容缩容、任务失败重试和告警、任务分片等功能。

[PowerJob](/docs/CS/Framework/Job/PowerJob.md)（原 OhMyScheduler）是全新一代分布式任务调度与计算框架，参考了阿里的 SchedulerX。

| **项目**     | **Quartz**                     | **Elastic-Job**                    | **XXL-JOB**                                | **SchedulerX**                                               | PowerJob |
| ------------ | ------------------------------ | ---------------------------------- | ------------------------------------------ | ------------------------------------------------------------ | --- |
| 定时调度     | Cron                           | Cron                               | Cron                                       | Cron、Fixed_Delay、Fixed_Rate、One_Time、OpenAPI             | Cron |
| 任务编排     | 不支持                         | 不支持                             | 不支持                                     | 支持，可以通过图形化配置，并且任务间可传递数据               | 支持 |
| 分布式跑批   | 不支持                         | 静态分片                           | 广播                                       | 广播、静态分片、MapReduce                                    | 广播、静态分片、MapReduce |
| 多语言       | Java                           | Java、脚本任务                     | Java、Go、脚本任务                         | Java、Go、脚本任务、HTTP任务、K8s Job                        | |
| 可观测       | 无                             | 弱，只能查看无法动态创建、修改任务 | 历史记录、运行日志（不支持搜索）、监控大盘 | 历史记录、运行日志（支持搜索）、监控大盘、操作记录、查看堆栈、链路追踪 | |
| 可运维       | 无                             | 启用、禁用任务                     | 启用、禁用任务、手动运行任务、停止任务     | 启用、禁用任务、手动运行任务、停止任务、标记成功、重刷历史数据 | |
| 报警监控     | 无                             | 邮件                               | 邮件                                       | 邮件、钉钉、飞书、企业微信、自定义WebHook、短信、电话        | |
| 高可用及容灾 | 需要自己维护数据库的容灾       | 需要自己维护ZooKeeper的容灾        | 需要自己维护数据库和Server的容灾           | 默认支持同城多机房容灾                                       | |
| 用户权限     | 无                             | 无                                 | 用户隔离，通过账号密码登录                 | 支持单点登录、主子账号、角色账号、RAM精细化权限管理          | |
| 优雅下线     | 不支持                         | 不支持                             | 支持                                       | 支持                                                         | |
| 灰度测试     | 不支持                         | 不支持                             | 不支持                                     | 支持                                                         | |
| 性能         | 每次调度通过DB抢锁，对DB压力大 | ZooKeeper是性能瓶颈                | 由Master节点调度，Master节点压力大          | 可水平扩展，支持海量任务调度                                 | |

## Tuning

### 任务堆积

同 MQ 中消息堆积，需考虑限流措施。

### 任务超时

### 任务重试

### 重复消费

### 任务分配

## Links

- [JDK](/docs/CS/Java/JDK/JDK.md)
- [Scheduled Task](/docs/CS/SE/Scheduled_Task.md)
- [Asyncio](/docs/CS/Python/Asyncio.md)

## References

1. [闲鱼技术 浅谈任务分发中的机制与并发](https://mp.weixin.qq.com/s/nGMxR7QDnoolTU5SYIDy2A)
2. [踩了定时线程池的坑，导致公司损失几千万，血的教训](https://mp.weixin.qq.com/s/nZNyF_DAdV3T8z07ALXOFg)
