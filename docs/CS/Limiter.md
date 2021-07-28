## Introduction



Method 

- reject
- queue
- mock

## Algorithms

- Semaphore only for counts
- 计数器
  - 固定窗口 瞬时峰值隐患
  - 滑动窗口 窗口粒度越小消耗资源高
- leaky bucket algorithm
  - as a meter 类似令牌桶 存储累积量 允许一定的突发
  - as a queue 限制速率 不支持突发流量
- 令牌桶 存储累积量



### Semaphore

```java
Semaphore semaphore = new Semaphore(10);
for (int i = 0; i < 100; i++) {
    executor.submit(new Runnable() {
        @Override
        public void run() {
            semaphore.acquireUninterruptibly(1);
            try {
                doSomething();
            } finally {
                semaphore.release();
            }
        }
    });
}
```



### Token Bucket

guava `RateLimiter` has two child class `SmoothBursty` and `SmoothWarmingUp` in `SmoothRateLimiter`.

- 令牌会累积 获取频率较低时可无需等待
- 累积令牌可应对突发流量
- 令牌不足时 前一个请求等待时间由后一个承受 第一次请求无须等待



#### Guava RateLimiter

![Guava RateLimiter](./images/Ratelimiter.png)



```java
// RateLimiter
/**
 * The underlying timer; used both to measure elapsed time and sleep as necessary. A separate
 * object to facilitate testing.
 */
private final SleepingStopwatch stopwatch;

// Can't be initialized in the constructor because mocks don't call the constructor.
private volatile @Nullable Object mutexDoNotUseDirectly;

// init mutexDoNotUseDirectly
private Object mutex() {
  Object mutex = mutexDoNotUseDirectly;
  if (mutex == null) {
    synchronized (this) {
      mutex = mutexDoNotUseDirectly;
      if (mutex == null) {
        mutexDoNotUseDirectly = mutex = new Object();
      }
    }
  }
  return mutex;
}
```



```java
// SmoothRateLimiter

/** The currently stored permits. */
double storedPermits;

/** The maximum number of stored permits. */
double maxPermits;

/**
 * The interval between two unit requests, at our stable rate. E.g., a stable rate of 5 permits
 * per second has a stable interval of 200ms.
 */
double stableIntervalMicros;

/**
 * The time when the next request (no matter its size) will be granted. After granting a request,
 * this is pushed further in the future. Large requests push this further than small requests.
 */
private long nextFreeTicketMicros = 0L; // could be either in the past or future
```



##### SmoothBursty

Default cache permits of 1 second

```java
// SmoothRateLimiter
static RateLimiter create(double permitsPerSecond, SleepingStopwatch stopwatch) {
  //only save up permits of 1 second if unsed 
  RateLimiter rateLimiter = new SmoothBursty(stopwatch, 1.0);
  rateLimiter.setRate(permitsPerSecond);
  return rateLimiter;
}

// RateLimiter
public final void setRate(double permitsPerSecond) {
  // check rate permitsPerSecond be positive
  synchronized (mutex()) {
    doSetRate(permitsPerSecond, stopwatch.readMicros());
  }
}

// SmoothRateLimiter
final void doSetRate(double permitsPerSecond, long nowMicros) {
  resync(nowMicros);
  double stableIntervalMicros = SECONDS.toMicros(1L) / permitsPerSecond;
  this.stableIntervalMicros = stableIntervalMicros;
  doSetRate(permitsPerSecond, stableIntervalMicros);
}

// SmoothRateLimiter
/** Updates storedPermits and nextFreeTicketMicros based on the current time. */
void resync(long nowMicros) {
  // if nextFreeTicket is in the past, resync to now
  if (nowMicros > nextFreeTicketMicros) {
    double newPermits = (nowMicros - nextFreeTicketMicros) / coolDownIntervalMicros();
    storedPermits = min(maxPermits, storedPermits + newPermits);
    nextFreeTicketMicros = nowMicros;
  }
}

// SmoothBursty
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





```java
// SmoothBursty
@Override
long storedPermitsToWaitTime(double storedPermits, double permitsToTake) {
  return 0L;
}
```

##### acquire

```java
@CanIgnoreReturnValue
public double acquire(int permits) {
  long microsToWait = reserve(permits);
  stopwatch.sleepMicrosUninterruptibly(microsToWait);
  return 1.0 * microsToWait / SECONDS.toMicros(1L);
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



##### SmoothWarmingUp



coldFactor always = 3

```java
public static RateLimiter create(double permitsPerSecond, long warmupPeriod, TimeUnit unit) {
  checkArgument(warmupPeriod >= 0, "warmupPeriod must not be negative: %s", warmupPeriod);
  return create(
      permitsPerSecond, warmupPeriod, unit, 3.0, SleepingStopwatch.createFromSystemTimer());
}

@VisibleForTesting
static RateLimiter create(
    double permitsPerSecond,
    long warmupPeriod,
    TimeUnit unit,
    double coldFactor,
    SleepingStopwatch stopwatch) {
  RateLimiter rateLimiter = new SmoothWarmingUp(stopwatch, warmupPeriod, unit, coldFactor);
  rateLimiter.setRate(permitsPerSecond);
  return rateLimiter;
}
```





```java
@Override
void doSetRate(double permitsPerSecond, double stableIntervalMicros) {
  double oldMaxPermits = maxPermits;
  double coldIntervalMicros = stableIntervalMicros * coldFactor;
  thresholdPermits = 0.5 * warmupPeriodMicros / stableIntervalMicros;
  maxPermits =
      thresholdPermits + 2.0 * warmupPeriodMicros / (stableIntervalMicros + coldIntervalMicros);
  slope = (coldIntervalMicros - stableIntervalMicros) / (maxPermits - thresholdPermits);
  if (oldMaxPermits == Double.POSITIVE_INFINITY) {
    // if we don't special-case this, we would get storedPermits == NaN, below
    storedPermits = 0.0;
  } else {
    storedPermits =
        (oldMaxPermits == 0.0)
            ? maxPermits // initial state is cold
            : storedPermits * maxPermits / oldMaxPermits;
  }
}
```



```java
@Override
long storedPermitsToWaitTime(double storedPermits, double permitsToTake) {
  double availablePermitsAboveThreshold = storedPermits - thresholdPermits;
  long micros = 0;
  // measuring the integral on the right part of the function (the climbing line)
  if (availablePermitsAboveThreshold > 0.0) {
    double permitsAboveThresholdToTake = min(availablePermitsAboveThreshold, permitsToTake);
    // TODO(cpovirk): Figure out a good name for this variable.
    double length =
        permitsToTime(availablePermitsAboveThreshold)
            + permitsToTime(availablePermitsAboveThreshold - permitsAboveThresholdToTake);
    micros = (long) (permitsAboveThresholdToTake * length / 2.0);
    permitsToTake -= permitsAboveThresholdToTake;
  }
  // measuring the integral on the left part of the function (the horizontal line)
  micros += (long) (stableIntervalMicros * permitsToTake);
  return micros;
}
```





分布式

Redis+Lua

Nginx+Lua

Sentinel