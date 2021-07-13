## Introduction



Method 

- reject
- queue
- mock

## Algorithms

- 信号量 只适用瞬时并发峰值控制
- 计数器
  - 固定窗口 瞬时峰值隐患
  - 滑动窗口 窗口粒度越小消耗资源高
- leaky bucket algorithm
  - as a meter 类似令牌桶 存储累积量 允许一定的突发
  - as a queue 限制速率 不支持突发流量
- 令牌桶 存储累积量



### 令牌桶

guava `RateLimiter` has two child class `SmoothBursty` and `SmoothWarmingUp` in `SmoothRateLimiter`.

- 令牌会累积 获取频率较低时可无需等待
- 累积令牌可应对突发流量
- 令牌不足时 前一个请求等待时间由后一个承受 第一次请求无须等待



RateLimiter rateLimiter = new SmoothBursty()

```java
static RateLimiter create(double permitsPerSecond, SleepingStopwatch stopwatch) {
  //only save up permits of 1 second if unsed 
  RateLimiter rateLimiter = new SmoothBursty(stopwatch, 1.0);
  rateLimiter.setRate(permitsPerSecond);
  return rateLimiter;
}

final void doSetRate(double permitsPerSecond, long nowMicros) {
  resync(nowMicros);
  double stableIntervalMicros = SECONDS.toMicros(1L) / permitsPerSecond;
  this.stableIntervalMicros = stableIntervalMicros;
  doSetRate(permitsPerSecond, stableIntervalMicros);
}

/** Updates storedPermits and nextFreeTicketMicros based on the current time. */
void resync(long nowMicros) {
  // if nextFreeTicket is in the past, resync to now
  if (nowMicros > nextFreeTicketMicros) {
    double newPermits = (nowMicros - nextFreeTicketMicros) / coolDownIntervalMicros();
    storedPermits = min(maxPermits, storedPermits + newPermits);
    nextFreeTicketMicros = nowMicros;
  }
}

void doSetRate(double permitsPerSecond, double stableIntervalMicros) {
  double oldMaxPermits = this.maxPermits;
  maxPermits = maxBurstSeconds * permitsPerSecond;
  if (oldMaxPermits == Double.POSITIVE_INFINITY) {
    // if we don't special-case this, we would get storedPermits == NaN, below
    storedPermits = maxPermits;
  } else {
    storedPermits =
        (oldMaxPermits == 0.0)
            ? 0.0 // initial state
            : storedPermits * maxPermits / oldMaxPermits;
  }
}
```





acquire

```java
public double acquire(int permits) {
    long microsToWait = this.reserve(permits);
    this.stopwatch.sleepMicrosUninterruptibly(microsToWait);
    return 1.0D * (double)microsToWait / (double)TimeUnit.SECONDS.toMicros(1L);
}

final long reserve(int permits) {
    synchronized (mutex()) {
      return reserveAndGetWaitLength(permits, stopwatch.readMicros());
    }
}

final long reserveAndGetWaitLength(int permits, long nowMicros) {
    long momentAvailable = reserveEarliestAvailable(permits, nowMicros);
    return max(momentAvailable - nowMicros, 0);
}

final long reserveEarliestAvailable(int requiredPermits, long nowMicros) {
  resync(nowMicros);//Updates storedPermits and nextFreeTicketMicros based on the current time
  long returnValue = nextFreeTicketMicros;
  double storedPermitsToSpend = min(requiredPermits, this.storedPermits);
  double freshPermits = requiredPermits - storedPermitsToSpend;
  //waitMicors = (requiredPermits - storedPermitsToSpend) * stableIntervalMicros
  long waitMicros =	
      storedPermitsToWaitTime(this.storedPermits, storedPermitsToSpend)
          + (long) (freshPermits * stableIntervalMicros);

  this.nextFreeTicketMicros = LongMath.saturatedAdd(nextFreeTicketMicros, waitMicros);
  this.storedPermits -= storedPermitsToSpend;
  return returnValue;
}
```




```java
public boolean tryAcquire(int permits, long timeout, TimeUnit unit) {
    long timeoutMicros = Math.max(unit.toMicros(timeout), 0L);
    checkPermits(permits);
    long microsToWait;
    synchronized(this.mutex()) {
        long nowMicros = this.stopwatch.readMicros();
        if (!this.canAcquire(nowMicros, timeoutMicros)) {
            return false;
        }
        microsToWait = this.reserveAndGetWaitLength(permits, nowMicros);
    }

    this.stopwatch.sleepMicrosUninterruptibly(microsToWait);
    return true;
}
```



分布式

Redis+Lua

Nginx+Lua

Sentinel