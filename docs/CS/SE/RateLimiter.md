## Introduction

Rate limiting is an essential technique used in software systems to control the rate of incoming requests. 
It helps to prevent the overloading of servers by limiting the number of requests that can be made in a given time frame.

Rate limiting helps prevent resource starvation caused by Denial of Service (DoS) attacks.
Rate limiting can help limit cost overruns by preventing the overuse of a resource.




Most rate limiting implementations share three core concepts. 
They are the limit, the window, and the identifier.

## Algorithms

Several algorithms are used for rate limiting, including

- Token bucket
- Leaky bucket
- Fixed window counter
- Sliding window log
- Sliding window counter

### Counter

最大连接数


#### Semaphore

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

### Fixed Window Counter

### Sliding Window Logs

Another approach to rate limiting is to use sliding window logs. 
This data structure involves a “window” of **fixed size** that slides along a timeline of events, storing information about the events that fall within the window at any given time.

This rate limitation keeps track of each client’s request in a time-stamped log. 
These logs are normally stored in a time-sorted hash set or table.

The sliding window logs algorithm can be implemented using the following steps:

- A time-sorted queue or hash table of timestamps within the time range of the most recent window is maintained for each client making the requests.
- When a certain length of the queue is reached or after a certain number of minutes, whenever a new request comes, a check is done for any timestamps older than the current window time.
- The queue is updated with new timestamp of incoming request and if number of elements in queue does not exceed the authorised count, it is proceeded otherwise an exception is triggered.



时间精度越高 花费越高

### Sliding Window Counters

The sliding window counter algorithm is an optimization over sliding window logs. As we can see in the previous approach, memory usage is high. For example, to manage numerous users or huge window timeframes, all the request timestamps must be kept for a window time, which eventually uses a huge amount of memory. Also, removing numerous timestamps older than a particular timeframe means high complexity of time as well.

To reduce surges of traffic, this algorithm accounts for a weighted value of the previous window’s request based on timeframe. If we have a one-minute rate limit, we can record the counter for each second and calculate the sum of all counters in the previous minute whenever we get a new request to determine the throttling limit.

The sliding window counters can be separated into the following concepts:

- Remove all counters which are more than 1 minute old.
- If a request comes which falls in the current bucket, the counter is increased.
- If a request comes when the current bucket has reached it’s throat limit, the request is blocked.

### Leaky Bucket

It is based on the idea that if the average rate at which water is poured exceeds the rate at which the bucket leaks, the bucket will overflow.

**The leaky bucket empties at a fixed rate. 
Each incoming request adds to the bucket’s depth, and if the bucket overflows, the request is rejected.**

One way to implement this is using a queue, which corresponds to the bucket that will contain the incoming requests. 
Whenever a new request is made, it is added to the queue’s end. If the queue is full at any time, then the additional requests are discarded.

The leaky bucket algorithm can be separated into the following concepts:

- Initialize the leaky bucket with a fixed depth and a rate at which it leaks.
- For each request, add to the bucket’s depth.
- If the bucket’s depth exceeds its capacity, reject the request.
- Leak the bucket at a fixed rate.


### Token Bucket


The token bucket algorithm allocates tokens at a fixed rate into a “bucket.”
Each request consumes a token from the bucket, and requests are only allowed if there are sufficient tokens available.
Unused tokens are stored in the bucket, up to a maximum capacity.
This algorithm provides a simple and flexible way to control the rate of requests and smooth out bursts of traffic.

The token bucket algorithm can be conceptually understood as follows:

A token is added to the bucket every $1/r$ seconds.
The bucket can hold at the most b tokens. If a token arrives when the bucket is full, it is discarded.
When a packet (network layer PDU) of n bytes arrives,
if at least n tokens are in the bucket, n tokens are removed from the bucket, and the packet is sent to the network.
if fewer than n tokens are available, no tokens are removed from the bucket, and the packet is considered to be non-conformant.


guava `RateLimiter` has two child class `SmoothBursty` and `SmoothWarmingUp` in `SmoothRateLimiter`.

- 令牌会累积 获取频率较低时可无需等待
- 累积令牌可应对突发流量
- 令牌不足时 前一个请求等待时间由后一个承受 第一次请求无须等待



#### Guava RateLimiter

![Guava RateLimiter](img/Ratelimiter.png)



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


## Distributed

Distributed rate limiting involves distributing rate limiting across multiple nodes or instances of a system to handle high traffic loads and improve scalability. Techniques such as consistent hashing, token passing, or distributed caches are used to coordinate rate limiting across nodes.



Sentinel


Hystrix


### Redis





## Links

## References

1. [Rate Limiting Fundamentals](https://blog.bytebytego.com/p/rate-limiting-fundamentals)