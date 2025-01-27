## Introduction


Kafka 通过引入 DelayQueue 以及多层时间轮，巧妙地解决了时间轮的空推进现象和海量延时任务时间跨度大的管理问题

Kafka 中也有一个工作线程 —— Reaper 来推动多层时间轮的运转

A timing wheel with size n has n buckets and can hold timer tasks in n * u time interval.

The timer never insert a task into the bucket for the current time since it is already expired. 

```scala

@nonthreadsafe
private[timer] class TimingWheel(tickMs: Long, wheelSize: Int, startMs: Long, taskCounter: AtomicInteger, queue: DelayQueue[TimerTaskList]) {

  private[this] val interval = tickMs * wheelSize
  private[this] val buckets = Array.tabulate[TimerTaskList](wheelSize) { _ => new TimerTaskList(taskCounter) }

  private[this] var currentTime = startMs - (startMs % tickMs) // rounding down to multiple of tickMs

  // overflowWheel can potentially be updated and read by two concurrent threads through add().
  // Therefore, it needs to be volatile due to the issue of Double-Checked Locking pattern with JVM
  @volatile private[this] var overflowWheel: TimingWheel = null
 }

```
The timer immediately runs the expired task.
The emptied bucket is then available for the next round, so if the current bucket is for the time t, it becomes the bucket for [t + u * n, t + (n + 1) * u) after a tick.
A timing wheel has O(1) cost for insert/delete (start-timer/stop-timer) whereas priority queue based timers, such as java.util.concurrent.DelayQueue and java.util.Timer, have O(log n) insert/delete cost.




```scala

  def add(timerTaskEntry: TimerTaskEntry): Boolean = {
    val expiration = timerTaskEntry.expirationMs

    if (timerTaskEntry.cancelled) {
      // Cancelled
      false
    } else if (expiration < currentTime + tickMs) {
      // Already expired
      false
    } else if (expiration < currentTime + interval) {
      // Put in its own bucket
      val virtualId = expiration / tickMs
      val bucket = buckets((virtualId % wheelSize.toLong).toInt)
      bucket.add(timerTaskEntry)

      // Set the bucket expiration time
      if (bucket.setExpiration(virtualId * tickMs)) {
        // The bucket needs to be enqueued because it was an expired bucket
        // We only need to enqueue the bucket when its expiration time has changed, i.e. the wheel has advanced
        // and the previous buckets gets reused; further calls to set the expiration within the same wheel cycle
        // will pass in the same value and hence return false, thus the bucket with the same expiration will not
        // be enqueued multiple times.
        queue.offer(bucket)
      }
      true
    } else {
      // Out of the interval. Put it into the parent timer
      if (overflowWheel == null) addOverflowWheel()
      overflowWheel.add(timerTaskEntry)
    }
  }
```


而 Kafka 为了解决时间轮空推进的问题，只有 TimerTaskList 到期的时候 Reaper 线程才会向前推进多层时间轮，如果没有 TimerTaskList 到期，Kafka 是不会向前推进的，仿佛时间静止了一样。

延时任务会按照过期时间的不同被组织在不同的 TimerTaskList 中， 每个 TimerTaskList 都有一个过期时间范围 —— [ startTime , endTime) ， 只要过期时间在这个范围内的延时任务，那么它就会被添加到该 TimerTaskList 中。TimerTaskList 自身的过期时间被设置为 startTime

当没有任何 TimerTaskList 到期的情况下，Reaper 线程就会一直在 delayQueue 上阻塞等待，直到有到期的 TimerTaskList 出现，
Reaper 线程从 delayQueue 上被唤醒，开始处理 TimerTaskList 中的延时任务，并向前推进多层时间轮

当某一个 TimerTaskList 到期之后，说明现在时间已经来到了该 TimerTaskList 对应的 startTime , 那么 Kafka 就会先从第一层时间轮开始，尝试将多层时间轮的 currentTimeMs 推进到 startTime。

但在推进之前，首先需要判断 startTime 与当前 currentTimeMs 的时间间隔是否满足当前时间轮的 tickMs（时钟间隔），如果不满足，时间轮就不能向前推进，因为还不够一个时钟间隔。


## Links

- [Apache Kafka](/docs/CS/MQ/Kafka/Kafka.md)