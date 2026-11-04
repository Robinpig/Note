## Introduction

Netty 的"限流"指的是**流量整形（Traffic Shaping）**：对读写带宽做限速，让单位时间内通过的数据量不超过设定速率，从而平滑突发流量、避免把下游或网络打满。它由 `AbstractTrafficShapingHandler` 这一 `ChannelHandler` 实现，放在 pipeline 中即可对经过的字节流限速。

需要先区分两类"限流"，避免与应用层 QPS 限流混淆：

- **流量整形（本页）**：限制的是**字节/秒带宽**，作用在网络读写层，单位是 B/s。手段是**延迟**，不是拒绝。
- **应用层限流（QPS/请求数）**：限制单位时间的请求数（令牌桶/漏桶），那是通用算法层面的内容，见 [RateLimiter](/docs/CS/SE/RateLimiter.md)。Netty 本身不直接提供分布式 QPS 限流，需要结合应用层信号量、Guava RateLimiter 或网关限流。

本文以 **Netty 4.2.19.Final**（git tag `netty-4.2.19.Final`，commit `64cc10f`）源码为准。相关代码全在 `handler` 模块：`handler/src/main/java/io/netty/handler/traffic/`。

## AbstractTrafficShapingHandler

`AbstractTrafficShapingHandler extends ChannelDuplexHandler`（源码：`handler/src/main/java/io/netty/handler/traffic/AbstractTrafficShapingHandler.java:53`），同时拦截入站 `channelRead` 与出站 `write`。它**不是**令牌桶：没有"桶"和"令牌"实体，而是每次读写时算一个「还需等待多少毫秒」，用定时任务把这次读写推迟到那个时刻再执行。

### Config Knobs

| 字段                 | 默认值                                             | 含义                                            | 源码位置                                       |
| :----------------- | :---------------------------------------------- | :-------------------------------------------- | :----------------------------------------- |
| `writeLimit`       | `0`                                             | 写限速，**B/s**；`0` = 不限                          | `AbstractTrafficShapingHandler.java:86`    |
| `readLimit`        | `0`                                             | 读限速，**B/s**；`0` = 不限                          | `...:91`                                   |
| `checkInterval`    | `DEFAULT_CHECK_INTERVAL = 1000` ms              | 统计窗口：多久做一次 `resetAccounting`（结算吞吐）           | `...:59` / `...:101`                       |
| `maxTime`          | `DEFAULT_MAX_TIME = 15000` ms                   | 单次延迟的上限，避免一次算出几十秒的等待                          | `...:66` / `...:96`                        |
| `MINIMAL_WAIT`     | `10` ms                                         | 小于 10 ms 的等待**直接忽略**，避免为几个字节起一堆定时任务           | `...:76`                                   |
| `maxWriteDelay`    | `4 * DEFAULT_CHECK_INTERVAL` = 4000 ms          | 排队延迟超过它就置 `isWritable() = false`（背压）          | `...:111`                                  |
| `maxWriteSize`     | `DEFAULT_MAX_SIZE` = 4 MB                       | 单 Channel 排队字节超过它就置 `isWritable() = false`     | `...:71` / `...:115`                       |
| `maxGlobalWriteSize` | `DEFAULT_MAX_SIZE * 100` = 400 MB             | **仅 `GlobalTrafficShapingHandler`**：全局排队字节上限 | `GlobalTrafficShapingHandler.java:94`      |

> [!NOTE]
>
> 两个容易记错的地方：
>
> 1. `writeLimit` / `readLimit` 的单位是 **B/s（每秒字节数）**，不是「每个 `checkInterval` 的字节数」。源码里换算靠 `* 1000`，见 [Time To Wait](/docs/CS/Framework/Netty/Limiter.md?id=time-to-wait)。
> 2. **没有"峰值速率"这个参数**。老资料里常说的「平均速率 + 峰值速率」是别的整形器（如 Linux tc）的概念，Netty 这里是 `writeLimit`/`readLimit` + `maxTime`（单次延迟上限）的组合。

运行时可以改（`configure(...)` / `setWriteLimit(...)` / `setReadLimit(...)`，源码：`...:237` / `:290` / `:313`），但源码注释明确写了这是 **best effort**——已经排进队列的写不受影响，只对新流量生效。改限速值时会顺带 `trafficCounter.resetAccounting(...)` 重置窗口。

### Three-Level Implementation

三个具体子类对应三种作用域：

| 实现类                                   | 作用域                                                    | 典型用途                              | `userDefinedWritabilityIndex` |
| :------------------------------------ | :----------------------------------------------------- | :-------------------------------- | :---------------------------- |
| `ChannelTrafficShapingHandler`        | **单 Channel**：每条连接一个实例、一个 `TrafficCounter`，各自独立计数        | 限制单个连接的上下行带宽（如每用户限速）              | `1`（`...:126`）                |
| `GlobalTrafficShapingHandler`         | **全局**：整个进程共享一个 `TrafficCounter`，所有 Channel 合计不超总带宽      | 限制进程总出口带宽                          | `2`（`...:131`）                |
| `GlobalChannelTrafficShapingHandler`  | 全局 + 每 Channel 两级：既限全局总带宽，又给每个 Channel 一个上限              | 既要总带宽封顶又要保证单连接公平（防个别连接抢占）         | `3`（`...:136`）                |

- Channel 级：每个连接一个 handler 实例，状态互不影响。它的 `TrafficCounter` 在 `handlerAdded` 里用 **`ctx.executor()`**（即该 Channel 绑定的 EventLoop）创建（源码：`handler/src/main/java/io/netty/handler/traffic/ChannelTrafficShapingHandler.java:132`），所以统计任务就跑在连接自己的 EventLoop 上。
- Global 级：所有 pipeline 共享**同一个 handler 实例**（这是使用上的关键，误给每 channel new 一个就退化为 channel 级）。它的 `TrafficCounter` 用构造器传入的**外部** `ScheduledExecutorService` 创建（源码：`.../GlobalTrafficShapingHandler.java:106`），所有连接共用这一个——这也是全局限速能做到"合计不超标"的原因。

> [!NOTE]
>
> `userDefinedWritabilityIndex` 必须三档不同，因为它就是 `ChannelOutboundBuffer` 里 `unwritable` 位图的**位下标**——不同 handler 各占一位才能互不干扰。详见 [Water Marks](/docs/CS/Framework/Netty/Limiter.md?id=water-marks)。

### Constructor Signatures

原笔记写的 `(EventExecutorGroup?, writeLimit, readLimit, checkInterval)` 与实际签名不符，准确的是：

```java
// Channel 级：没有 executor 参数，直接用 Channel 自己的 EventLoop
// 源码：handler/src/main/java/io/netty/handler/traffic/ChannelTrafficShapingHandler.java:82
public ChannelTrafficShapingHandler(long writeLimit, long readLimit, long checkInterval, long maxTime)
public ChannelTrafficShapingHandler(long writeLimit, long readLimit, long checkInterval)
public ChannelTrafficShapingHandler(long writeLimit, long readLimit)      // checkInterval=1000, maxTime=15000
public ChannelTrafficShapingHandler(long checkInterval)                  // 不限速，只统计

// Global 级：第一个参数是 ScheduledExecutorService（另有 EventExecutor 重载），用于跑全局 TrafficCounter
// 源码：handler/src/main/java/io/netty/handler/traffic/GlobalTrafficShapingHandler.java:136
public GlobalTrafficShapingHandler(ScheduledExecutorService executor,
        long writeLimit, long readLimit, long checkInterval, long maxTime)
public GlobalTrafficShapingHandler(ScheduledExecutorService executor, long writeLimit, long readLimit)
public GlobalTrafficShapingHandler(ScheduledExecutorService executor, long checkInterval)
public GlobalTrafficShapingHandler(EventExecutor executor)               // 不限速，只统计
```

`maxTime` 走的是 `checkPositive`（源码：`.../AbstractTrafficShapingHandler.java:170`），所以**不能传 0**，最小 1 ms。

## How Limiting Works

### Read Path

```java
// 源码：handler/src/main/java/io/netty/handler/traffic/AbstractTrafficShapingHandler.java:471
@Override
public void channelRead(final ChannelHandlerContext ctx, final Object msg) throws Exception {
    long size = calculateSize(msg);
    long now = TrafficCounter.milliSecondFromNano();
    if (size > 0) {
        // compute the number of ms to wait before reopening the channel
        long wait = trafficCounter.readTimeToWait(size, readLimit, maxTime, now);
        wait = checkWaitReadTime(ctx, wait, now);
        if (wait >= MINIMAL_WAIT) { // At least 10ms seems a minimal
            // time in order to try to limit the traffic
            Channel channel = ctx.channel();
            ChannelConfig config = channel.config();
            if (config.isAutoRead() && isHandlerActive(ctx)) {
                config.setAutoRead(false);
                channel.attr(READ_SUSPENDED).set(true);
                // Create a Runnable to reactive the read if needed. If one was create before it will just be
                // reused to limit object creation
                Attribute<Runnable> attr = channel.attr(REOPEN_TASK);
                Runnable reopenTask = attr.get();
                if (reopenTask == null) {
                    reopenTask = new ReopenReadTimerTask(ctx);
                    attr.set(reopenTask);
                }
                ctx.executor().schedule(reopenTask, wait, TimeUnit.MILLISECONDS);
            }
        }
    }
    informReadOperation(ctx, now);
    ctx.fireChannelRead(msg);
}
```

读限速的机制是**关掉自动读**：`config.setAutoRead(false)` 之后，内核侧就绪的数据不会再被读上来；同时 `ctx.executor().schedule(reopenTask, wait, ...)` 排一个 `ReopenReadTimerTask`，到点了再 `setAutoRead(true)` + `channel.read()`（源码：`...:424`）。因为 TCP 本身有滑动窗口，读慢了对端自然就发慢了——这是读限速能生效的根本原因。

`ReopenReadTimerTask` 缓存在 channel 的 `REOPEN_TASK` 属性里复用，避免每次限速都 new 一个对象。

### Write Path

```java
// 源码：handler/src/main/java/io/netty/handler/traffic/AbstractTrafficShapingHandler.java:553
@Override
public void write(final ChannelHandlerContext ctx, final Object msg, final ChannelPromise promise)
        throws Exception {
    long size = calculateSize(msg);
    long now = TrafficCounter.milliSecondFromNano();
    if (size > 0) {
        // compute the number of ms to wait before continue with the channel
        long wait = trafficCounter.writeTimeToWait(size, writeLimit, maxTime, now);
        if (wait >= MINIMAL_WAIT) {
            submitWrite(ctx, msg, size, wait, now, promise);
            return;
        }
    }
    // to maintain order of write
    submitWrite(ctx, msg, size, 0, now, promise);
}
```

注意最后一行：**即使不需要等待，也要走 `submitWrite(ctx, msg, size, 0, ...)`**，而不是直接 `ctx.write`。因为写顺序必须保持——如果前面有消息还在排队，这次的 0 延迟消息也必须排到队尾，否则会插队导致乱序。

`submitWrite` 是抽象方法（源码：`...:580`），三个子类各自实现。

`calculateSize`（源码：`...:655`）只认三种类型：`ByteBuf` → `readableBytes()`，`ByteBufHolder` → `content().readableBytes()`，`FileRegion` → `count()`；其它返回 `-1`（`size > 0` 为假 → 完全不参与限速）。**自定义消息类型不重写这个方法就等于完全没被限速**。

### Time To Wait

真正算"等多久"的是 `TrafficCounter`。读方向（源码：`handler/src/main/java/io/netty/handler/traffic/TrafficCounter.java:489`）：

```java
// 源码：handler/src/main/java/io/netty/handler/traffic/TrafficCounter.java:489
public long readTimeToWait(final long size, final long limitTraffic, final long maxTime, final long now) {
    bytesRecvFlowControl(size);
    if (size == 0 || limitTraffic == 0) {
        return 0;
    }
    final long lastTimeCheck = lastTime.get();
    long sum = currentReadBytes.get();
    long localReadingTime = readingTime;
    long lastRB = lastReadBytes;
    final long interval = now - lastTimeCheck;
    long pastDelay = Math.max(lastReadingTime - lastTimeCheck, 0);
    if (interval > AbstractTrafficShapingHandler.MINIMAL_WAIT) {
        // Enough interval time to compute shaping
        long time = sum * 1000 / limitTraffic - interval + pastDelay;
        if (time > AbstractTrafficShapingHandler.MINIMAL_WAIT) {
            if (time > maxTime && now + time - localReadingTime > maxTime) {
                time = maxTime;
            }
            readingTime = Math.max(localReadingTime, now + time);
            return time;
        }
        readingTime = Math.max(localReadingTime, now);
        return 0;
    }
    // take the last read interval check to get enough interval time
    long lastsum = sum + lastRB;
    long lastinterval = interval + checkInterval.get();
    long time = lastsum * 1000 / limitTraffic - lastinterval + pastDelay;
    ...
}
```

写方向 `writeTimeToWait`（源码：`...:564`）结构完全对称，只是把 `currentReadBytes` 换成 `currentWrittenBytes`、`readingTime` 换成 `writingTime`。

变量含义与公式：

| 变量              | 含义                                                        |
| :-------------- | :-------------------------------------------------------- |
| `sum`           | 当前窗口已累积的字节数（`bytesRecvFlowControl(size)` **先**把本次 size 加进去再算，所以包含本次） |
| `limitTraffic`  | `readLimit` / `writeLimit`，单位 B/s                          |
| `interval`      | `now - lastTime`，距上次结算过了多少 ms                             |
| `pastDelay`     | `max(lastReadingTime - lastTimeCheck, 0)`：上一次算出的等待里**还没走完**的部分 |
| `time`          | 本次需要等待的 ms 数                                              |

```java
// 窗口时间足够（> 10ms）：直接用本窗口数据
time = sum * 1000 / limitTraffic - interval + pastDelay;

// 窗口太短（刚 reset 过）：把上一个窗口的数据一起算进来，避免刚结算完就"忘记"了上窗口的突发
lastsum      = sum + lastRB;                 // 本窗口 + 上一窗口
lastinterval = interval + checkInterval;     // 本窗口已过时间 + 一个完整窗口
time         = lastsum * 1000 / limitTraffic - lastinterval + pastDelay;
```

直觉解释：`sum * 1000 / limitTraffic` 是「这么多字节按限速发完**总共**需要多少 ms」；减去 `interval`（本窗口已经过去的时间）就是「还需要等多少」；再加上 `pastDelay`（上次欠着的等待）就是最终等待时间。

两个后处理：

- **`time > MINIMAL_WAIT`（10 ms）才真的等**。否则返回 0。这是性能保护：为几 KB 数据起一个 1 ms 的定时任务，光调度开销就比省下的带宽贵。
- **`maxTime` 截断**：`time > maxTime && now + time - localReadingTime > maxTime` 时把 `time` 压到 `maxTime`（默认 15000 ms）。第二个条件是防止反复截断导致饿死。

### Traffic Counter

`TrafficCounter` 只做记账，不参与决策（源码：`handler/src/main/java/io/netty/handler/traffic/TrafficCounter.java`）：

| 方法                                    | 作用                                                               |
| :------------------------------------ | :--------------------------------------------------------------- |
| `bytesRecvFlowControl(long recv)`     | `currentReadBytes += recv; cumulativeReadBytes += recv`（`:323`）   |
| `bytesWriteFlowControl(long write)`   | `currentWrittenBytes += write; cumulativeWrittenBytes += write`（`:334`） |
| `bytesRealWriteFlowControl(long w)`   | 真正落盘/落网的字节数（`realWrittenBytes`），用于对比"业务想写"与"实际写出"              |
| `resetAccounting(long newLastTime)`   | 结算本窗口：把 `current*` 归零、算出 `last*Throughput`（`:222`）               |

结算公式（源码：`...:231`）：

```java
// 源码：handler/src/main/java/io/netty/handler/traffic/TrafficCounter.java:231
lastReadBytes = currentReadBytes.getAndSet(0);
lastWrittenBytes = currentWrittenBytes.getAndSet(0);
lastReadThroughput = lastReadBytes * 1000 / interval;
lastWriteThroughput = lastWrittenBytes * 1000 / interval;
realWriteThroughput = realWrittenBytes.getAndSet(0) * 1000 / interval;
lastWritingTime = Math.max(lastWritingTime, writingTime);
lastReadingTime = Math.max(lastReadingTime, readingTime);
```

最后两行的作用是「把上次的目标时刻向后推到不早于本次目标时刻」，这样下一次算 `pastDelay = max(lastReadingTime - lastTimeCheck, 0)` 时才不会把已经过期的目标时刻算成残留欠账。

结算的驱动是 `TrafficMonitoringTask`（源码：`...:169`），由 `start()` 用 `executor.scheduleAtFixedRate(monitor, 0, localCheckInterval, MILLISECONDS)` 起（源码：`...:196`）。所以 **`checkInterval` 既是统计窗口也是定时任务周期**。

对外可读的指标：`lastReadThroughput()` / `lastWriteThroughput()` / `realWriteThroughput()`（B/s）、`currentReadBytes()` / `currentWrittenBytes()`（本窗口）、`cumulativeReadBytes()` / `cumulativeWrittenBytes()`（累计）。

## Global vs Channel Internals

### ChannelTrafficShapingHandler

结构最简单：一个 `ArrayDeque<ToSend> messagesQueue` + 一个 `queueSize`（源码：`.../ChannelTrafficShapingHandler.java:66`），全部操作 `synchronized (this)`（源码：`...:183`）。

```java
// 源码：handler/src/main/java/io/netty/handler/traffic/ChannelTrafficShapingHandler.java:178
void submitWrite(final ChannelHandlerContext ctx, final Object msg,
        final long size, final long delay, final long now,
        final ChannelPromise promise) {
    final ToSend newToSend;
    // write order control
    synchronized (this) {
        if (delay == 0 && messagesQueue.isEmpty()) {
            trafficCounter.bytesRealWriteFlowControl(size);
            ctx.write(msg, promise);
            return;
        }
        newToSend = new ToSend(delay + now, msg, promise);
        messagesQueue.addLast(newToSend);
        queueSize += size;
        checkWriteSuspend(ctx, delay, queueSize);
    }
    final long futureNow = newToSend.relativeTimeAction;
    ctx.executor().schedule(new Runnable() {
        @Override
        public void run() {
            sendAllValid(ctx, futureNow);
        }
    }, delay, TimeUnit.MILLISECONDS);
}
```

**快路径**：`delay == 0 && 队列为空` 时直接 `ctx.write`，不进队列也不排任务。这是绝大多数不限速场景走的路径。

`sendAllValid(ctx, now)`（源码：`...:203`）按 `relativeTimeAction <= now` 从队头连续取出所有到期消息逐个 `ctx.write`，遇到未到期的放回队头并停，最后统一 `ctx.flush()`。队列空了就 `releaseWriteSuspended(ctx)`。

### GlobalTrafficShapingHandler

多一层 `ConcurrentMap<Integer, PerChannel> channelQueues`（源码：`.../GlobalTrafficShapingHandler.java:83`），key 是 `channel.hashCode()`。每个 `PerChannel` 有自己的 `messagesQueue` / `queueSize` / `lastReadTimestamp` / `lastWriteTimestamp`（源码：`...:96`）。

与 Channel 级的关键差异：

| 维度      | Channel 级                       | Global 级                                                                                   |
| :------ | :----------------------------- | :----------------------------------------------------------------------------------------- |
| 计数器      | 每 Channel 一个                   | **全局一个**（`createGlobalTrafficCounter`，`...:106`）                                              |
| 同步粒度     | `synchronized (this)`          | `synchronized (perChannel)`——只锁单连接队列，不同连接互不阻塞                                                |
| 全局排队上限   | 无                              | `queuesSize` + `maxGlobalWriteSize`（400 MB，`...:94`），超过就把**所有** Channel 置不可写（`...:365`）        |
| 单连接延迟修正  | 无                              | `delay > maxTime && now + delay - perChannel.lastWriteTimestamp > maxTime` 时截断（`...:353`）   |
| 读操作时间戳   | 无                              | `checkWaitReadTime` / `informReadOperation`（`...:296` / `:308`），按通道修正读等待                     |
| 释放       | `handlerRemoved` 里 `stop()`    | 必须显式 `release()` 才会 `trafficCounter.stop()`（`...:237`），否则全局定时任务一直跑                          |

`submitWrite` 的全局部分（源码：`...:331`）：

```java
// 源码：handler/src/main/java/io/netty/handler/traffic/GlobalTrafficShapingHandler.java:357
newToSend = new ToSend(delay + now, msg, size, promise);
perChannel.messagesQueue.addLast(newToSend);
perChannel.queueSize += size;
queuesSize.addAndGet(size);
checkWriteSuspend(ctx, delay, perChannel.queueSize);
if (queuesSize.get() > maxGlobalWriteSize) {
    globalSizeExceeded = true;
}
```

`handlerRemoved`（源码：`...:264`）兜底处理积压：连接还活着就把队列里剩下的全部 `ctx.write` 出去；连接已关就逐个 `releaseAndFailQueuedWrite(..., new ClosedChannelException())`——**这一步很重要**，否则调用方的 promise 永远不完成，且 `ByteBuf` 泄漏。

## Water Marks

原笔记提到「注意水位线与 OOM 风险，可配合 `writeBufferWaterMark` 与背压」，但两者的协作方式需要说清楚——它们**不是同一个机制，而是两个独立的位**。

`ChannelOutboundBuffer.isWritable()`（源码：`transport/src/main/java/io/netty/channel/ChannelOutboundBuffer.java:578`）：

```java
// 源码：transport/src/main/java/io/netty/channel/ChannelOutboundBuffer.java:578
public boolean isWritable() {
    return unwritable == 0;
}
```

`unwritable` 是一个 **int 位图**：

| 位      | 谁置位                                                                            | 置位条件                                     |
| :----- | :----------------------------------------------------------------------------- | :--------------------------------------- |
| bit 0  | `setUnwritable`（`...:649`），由 `incrementPendingOutboundBytes` 触发                  | 待写字节 ≥ `WRITE_BUFFER_HIGH_WATER_MARK`    |
| bit 1  | `ChannelTrafficShapingHandler`                                                 | 排队延迟 > `maxWriteDelay` 或排队字节 > `maxWriteSize` |
| bit 2  | `GlobalTrafficShapingHandler`                                                  | 同上（全局口径），或 `queuesSize > maxGlobalWriteSize` |
| bit 3  | `GlobalChannelTrafficShapingHandler`                                           | 同上                                       |

置位入口（源码：`handler/src/main/java/io/netty/handler/traffic/AbstractTrafficShapingHandler.java:597`）：

```java
// 源码：handler/src/main/java/io/netty/handler/traffic/AbstractTrafficShapingHandler.java:597
void setUserDefinedWritability(ChannelHandlerContext ctx, boolean writable) {
    ChannelOutboundBuffer cob = ctx.channel().unsafe().outboundBuffer();
    if (cob != null) {
        cob.setUserDefinedWritability(userDefinedWritabilityIndex, writable);
    }
}

// 源码：.../AbstractTrafficShapingHandler.java:610
void checkWriteSuspend(ChannelHandlerContext ctx, long delay, long queueSize) {
    if (queueSize > maxWriteSize || delay > maxWriteDelay) {
        setUserDefinedWritability(ctx, false);
    }
}
```

结论：

- **`isWritable()` 是「水位线正常」AND「所有 user-defined 位都正常」**。任一位被置，`Channel.isWritable()` 就是 false，`channelWritabilityChanged` 事件就会触发。
- 业务代码里正确的背压写法是 **`if (channel.isWritable())` 才继续产生数据**，而不是只盯 `WRITE_BUFFER_WATER_MARK`——只盯后者会漏掉流量整形造成的积压。
- 反过来，`WRITE_BUFFER_WATER_MARK` 与流量整形**互不感知**：整形器不知道水位线，水位线也不知道整形队列里还有多少字节。所以整形队列的 4 MB / 400 MB 上限是独立的第二道防线，它不是从水位线推导出来的。

## Usage Snippet

```java
// 全局出口限速：写 10MB/s、读 10MB/s，统计窗口 1s
ScheduledExecutorService executor = Executors.newSingleThreadScheduledExecutor();
GlobalTrafficShapingHandler global =
        new GlobalTrafficShapingHandler(executor, 10 * 1024 * 1024, 10 * 1024 * 1024, 1000);

ch.pipeline().addLast("traffic", global);
ch.pipeline().addLast(new MyBusinessHandler());

// 进程退出时必须释放，否则全局统计定时任务会一直跑
// global.release();
```

单连接限速则在每个 channel 初始化时 new `ChannelTrafficShapingHandler`（不需要传 executor）：

```java
ch.pipeline().addLast(new ChannelTrafficShapingHandler(1024 * 1024, 1024 * 1024)); // 每连接上下行各 1 MB/s
```

## Caveats

- **整形手段是"延迟"，不是"拒绝"**：高负载下排队会增大延迟、占用 EventLoop 定时器。限速值过低或 `maxWriteSize` 过大时，数据在队列里堆积，等价于把内存压力从对端搬到了自己进程。
- **必须配背压**：只加整形 handler 而不检查 `channel.isWritable()`，等于放任队列无限增长。见 [Water Marks](/docs/CS/Framework/Netty/Limiter.md?id=water-marks)。
- **统计的是字节流，不感知消息边界**：`calculateSize` 只认 `ByteBuf` / `ByteBufHolder` / `FileRegion`，自定义消息类型不重写就完全绕过限速；也不能用它精确限制"请求条数"。
- **Global 级的两把锁**：`queuesSize` 是 `AtomicLong`（`...:88`），单连接队列是 `synchronized (perChannel)`。多 EventLoop 下的竞争主要在 `queuesSize` 的 CAS 上，超大连接数场景需要评估；另外全局 `TrafficCounter` 只有一个，所有连接的 `writeTimeToWait` 都要读写它的字段。
- **Global 级必须共享实例**：误给每个 channel new 一个就退化为 channel 级（每个实例一个全局计数器），限速失效且定时任务数量暴涨。
- **读限速依赖 TCP 背压**：`setAutoRead(false)` 让内核缓冲区积压，靠滑动窗口反压到对端。若中间有代理/缓冲区很大的中间件，反压链路会被拉长甚至失效。
- **真正的 QPS/并发限流、熔断仍应在业务或网关层做**（令牌桶、信号量、连接数控制），见 [RateLimiter](/docs/CS/SE/RateLimiter.md) 与 [Resilience4j](/docs/CS/Framework/Spring_Cloud/Resilience4j.md)。

## Links

- [Netty](/docs/CS/Framework/Netty/Netty.md)
- [ChannelHandler](/docs/CS/Framework/Netty/ChannelHandler.md)
- [EventLoop](/docs/CS/Framework/Netty/EventLoop.md)
- [应用层限流 RateLimiter](/docs/CS/SE/RateLimiter.md)
- [Resilience4j RateLimiter](/docs/CS/Framework/Spring_Cloud/Resilience4j.md)

## References

1. [Netty 4.2 Javadoc - AbstractTrafficShapingHandler](https://netty.io/4.2/api/io/netty/handler/traffic/AbstractTrafficShapingHandler.html)
2. [Netty 4.2 Javadoc - GlobalTrafficShapingHandler](https://netty.io/4.2/api/io/netty/handler/traffic/GlobalTrafficShapingHandler.html)
3. [Netty 4.2 Javadoc - TrafficCounter](https://netty.io/4.2/api/io/netty/handler/traffic/TrafficCounter.html)
4. [Netty Traffic Shaping Package](https://netty.io/4.2/api/io/netty/handler/traffic/package-summary.html)
