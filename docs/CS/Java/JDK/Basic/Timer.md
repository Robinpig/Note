## Introduction

Timer 工具管理延迟执行（"在 100 毫秒后运行此任务"）和周期性执行（"每 10 毫秒运行此任务"）的任务。
然而，Timer 有一些缺点，ScheduledThreadPoolExecutor 应被视为其替代品。
你可以通过构造方法或 newScheduledThreadPool 工厂来构造 ScheduledThreadPoolExecutor。

Timer 确实支持基于绝对时间（而非相对时间）的调度，因此任务可以对系统时钟的变化敏感；
ScheduledThreadPoolExecutor 只支持相对时间。

Timer 只创建一个线程来执行定时器任务。
如果一个定时器任务运行时间过长，其他 TimerTask 的定时准确性可能会受到影响。
如果一个重复性的 TimerTask 被安排每 10 毫秒运行一次，而另一个 TimerTask 需要 40 毫秒才能运行完成，
那么重复性任务要么（取决于它是按固定速率还是固定延迟调度）在长时间运行的任务完成后连续被调用四次，
要么完全"错过"四次调用。
Scheduled 线程池通过允许你提供多个线程来执行延迟和周期性任务，解决了这个限制。

Timer 的另一个问题是，如果 TimerTask 抛出未受检异常，其行为不佳。
Timer 线程不会捕获异常，因此从 TimerTask 抛出的未受检异常会终止定时器线程。
Timer 在这种情况下也不会恢复线程；相反，它错误地假定整个 Timer 已被取消。在这种情况下，
已经调度但尚未执行的 TimerTask 永远不会运行，新的任务也无法被调度。（这个问题称为"`线程泄漏`"）。

Timer 中有两个核心组件，一个是用于调度延时任务的 TimerThread ，另一个是 TaskQueue，用于组织延时任务

```java
public class Timer {
    /**
     * The timer task queue.  This data structure is shared with the timer
     * thread.  The timer produces tasks, via its various schedule calls,
     * and the timer thread consumes, executing timer tasks as appropriate,
     */
    private final TaskQueue queue = new TaskQueue();
    private final TimerThread thread = new TimerThread(queue);
}
```

## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)
