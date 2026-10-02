## Introduction

Netty 的“限流”指的是**流量整形（Traffic Shaping）**：对读写带宽做限速，让单位时间内通过的数据量不超过设定速率，从而平滑突发流量、避免把下游或网络打满。它由 `AbstractTrafficShapingHandler` 这一 `ChannelHandler` 实现，放在 pipeline 中即可对经过的字节流限速。

需要先区分两类“限流”，避免与应用层 QPS 限流混淆：

- **流量整形（本页）**：限制的是**字节/秒带宽（带宽整形）**，作用在网络读写层，单位是 bytes/s。
- **应用层限流（QPS/请求数）**：限制单位时间的请求数（令牌桶/漏桶），那是通用算法层面的内容，见 [RateLimiter](/docs/CS/SE/RateLimiter.md)。Netty 本身不直接提供分布式 QPS 限流，需要结合应用层信号量、Guava RateLimiter 或网关限流。

## AbstractTrafficShapingHandler

`AbstractTrafficShapingHandler` 继承自 `ChannelDuplexHandler`，同时拦截读（`channelRead`）和写（`write`）。其工作原理基于一个简化的令牌桶/信用累积模型：

- 配置读限速 `checkInterval`（检查周期）、`writeLimit` / `readLimit`（每周期允许的字节数）、峰值速率等。
- 数据经过时统计字节数；若超出允许速率，就把本次读写**挂起并延迟（suspend/delay）**，通过 `TrafficCounter` 计算需要等待的时间，到点再用 EventLoop 的定时任务继续 flush/read，而不是直接拒绝。
- 因此整形的手段是“**延迟发送/读取**”（平滑），而非丢包或报错——这与 QPS 限流的“拒绝”不同。

构造参数典型为：`(EventExecutorGroup? , long writeLimit, long readLimit, long checkInterval)`，可分别限制上行/下行带宽，值为 `0` 表示不限。

### 三个层级实现

原笔记列出的 Channel / Global 对应两个具体子类，加上 GlobalChannel 共三种作用域：

| 实现类 | 作用域 | 典型用途 |
| ---- | ---- | ---- |
| `ChannelTrafficShapingHandler` | **单 Channel**：每个连接各自独立计数、独立限速 | 限制单个连接的上下行带宽（如每用户限速） |
| `GlobalTrafficShapingHandler` | **全局**：整个 EventExecutor/应用共享一个计数器，所有 Channel 合计不超过总带宽 | 限制进程总出口带宽 |
| `GlobalChannelTrafficShapingHandler` | 全局 + 每 Channel 两级：既限全局总带宽，又给每个 Channel 一个上限 | 既要总带宽封顶又要保证单连接公平（防个别连接抢占） |

- Channel 级：每个连接一个 handler 实例，状态互不影响。
- Global 级：所有 pipeline 共享**同一个 handler 实例**（这是使用上的关键，误给每 channel new 一个就退化为 channel 级），通常挂在每个 channel 的 pipeline 里但引用同一对象。

## Usage Snippet

```java
// 全局出口限速：写 10MB/s、读 10MB/s，每 1s 检查一次
GlobalTrafficShapingHandler global =
        new GlobalTrafficShapingHandler(executor, 10 * 1024 * 1024, 10 * 1024 * 1024);

ch.pipeline().addLast("traffic", global);
ch.pipeline().addLast(new MyBusinessHandler());
```

单连接限速则在每个 channel 初始化时 new `ChannelTrafficShapingHandler`。

## Caveats

- Traffic shaping 通过**延迟**实现平滑，高负载下会增大延迟、占用 EventLoop 定时器，限速值过低会导致数据在发送队列堆积（注意水位线与 OOM 风险，可配合 `writeBufferWaterMark` 与背压）。
- 它统计的是**字节流**，不感知应用消息边界，不能用来精确限制“请求条数”。
- Global 级共享计数器在多 EventLoop 下有同步开销；超大流量场景需评估。
- 真正的 QPS/并发限流、熔断仍应在业务或网关层做（令牌桶、信号量、连接数控制），见 [RateLimiter](/docs/CS/SE/RateLimiter.md) 与 [Resilience4j](/docs/CS/Framework/Spring_Cloud/Resilience4j.md)。

## Links

- [Netty](/docs/CS/Framework/Netty/Netty.md)
- [ChannelHandler](/docs/CS/Framework/Netty/ChannelHandler.md)
- [EventLoop](/docs/CS/Framework/Netty/EventLoop.md)
- [应用层限流 RateLimiter](/docs/CS/SE/RateLimiter.md)
- [Resilience4j RateLimiter](/docs/CS/Framework/Spring_Cloud/Resilience4j.md)

## References

1. [Netty Javadoc - AbstractTrafficShapingHandler](https://netty.io/4.1/api/io/netty/handler/traffic/AbstractTrafficShapingHandler.html)
2. [Netty Javadoc - GlobalTrafficShapingHandler](https://netty.io/4.1/api/io/netty/handler/traffic/GlobalTrafficShapingHandler.html)
3. [Netty Traffic Shaping Package](https://netty.io/4.1/api/io/netty/handler/traffic/package-summary.html)
