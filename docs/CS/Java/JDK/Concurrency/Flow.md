## Introduction

[Flow](/docs/CS/Java/JDK/Concurrency/Flow.md) 是 `java.util.concurrent` 下的**响应式流（Reactive Streams）互操作层**：四个嵌套接口 `Flow.Publisher` / `Flow.Subscriber` / `Flow.Subscription` / `Flow.Processor`，加一个工具实现 `SubmissionPublisher`。JDK 9 随 **JEP 266: More Concurrency Updates** 引入，规格与 [Reactive Streams 1.0](http://www.reactive-streams.org/) 倡议对应，目的是让不同异步系统（RxJava、Reactor、各种消息中间件客户端）在 JVM 上能互相接驳。

JEP 266 对它的定位说得很保守：**接口很小，嵌在一个类里是为了给短期与长期演化和睦相处留空间**；JDK 不打算提供网络或 I/O 级的分布式消息组件。也就是说——JDK 只定义「插头标准」，不提供「电器」。

## Protocol

一次订阅的生命周期严格由四条消息构成：

```java
publisher.subscribe(subscriber);
// ① publisher 调 subscriber.onSubscribe(subscription)，至多一次
// ② subscriber 调 subscription.request(n)，表达还能收多少（背压）
// ③ publisher 至多推送 request 累计数量的 onNext(item)
// ④ 终态二选一：onError(throwable) 或 onComplete()
```

规则要点：

- `onSubscribe` 是**订阅成功的唯一信号**，之后 Subscriber 才能调 `Subscription` 的方法；`request` / `cancel` 允许被调用多次或跨线程调用，实现必须保证线程安全；
- `onNext` 的数量受 `request` 累计量约束——这是**拉-推混合**模型：订阅是推的，流速是拉的；
- `onError` / `onComplete` 是终态信号，之后 Publisher 不再发任何消息；
- `Processor<S,T>` 同时是 Subscriber 与 Publisher，用于变换管道。

`request(n)` 就是背压的全部机制：下游不 `request`，上游就不发。它把「消费者被生产者压垮」从运行时事故变成订阅者的显式决定。

## SubmissionPublisher

`SubmissionPublisher` 是 JDK 唯一内置的 Publisher 实现，规格（译意）：**异步地把提交的非 null 条目分发给当前订阅者，直到它被关闭为止**。

```java
var publisher = new SubmissionPublisher<String>(executor, 128);  // 执行器 + 每订阅者最大缓冲
publisher.subscribe(new Flow.Subscriber<String>() {
    @Override public void onSubscribe(Flow.Subscription s) {
        s.request(Long.MAX_VALUE);      // 无界拉取
    }
    @Override public void onNext(String item) { /* 处理 */ }
    @Override public void onError(Throwable t) { }
    @Override public void onComplete() { }
});
publisher.submit("item");               // 阻塞直到资源可用
publisher.close();                      // 之后所有订阅者收到 onComplete
```

工程语义集中在几处：

| 行为 | 规格 |
| --- | --- |
| 缓冲 | **每个订阅者独立 buffer**，首次使用创建、按需扩容至 `maxBufferCapacity`（容量会向上取到 2 的幂）；`request` 不直接触发扩容，未满足的 request 超过上限有饱和风险 |
| `submit` | 阻塞直到资源可用——最简单但最不灵敏 |
| `offer` 家族 | 可丢弃（立即或带超时），并可挂 drop handler 拦截后重试 |
| 执行器 | 构造器指定；生成者线程独立、订阅者可估量时用 `newFixedThreadPool`，否则默认 `ForkJoinPool.commonPool()` |
| 异常 | `onNext` 抛异常 → 取消该订阅（有 handler 则先回调）；`onSubscribe` / `onError` / `onComplete` 抛异常不记录，直接取消 |
| 内存可见 | 发布动作 happen-before 对应订阅者的后续动作；`estimateMaximumLag` / `estimateDemand` 等估算值**仅供监控**，规格明说不可用于同步控制 |
| `consume(Consumer)` | 常见场景快捷方式：订阅、request 全部、逐项处理 |

JDK 源码示例还给出两种典型子类化：`PeriodicPublisher`（继承 `SubmissionPublisher` + `ScheduledExecutorService` 周期 `submit`）与 `TransformProcessor`（实现 `Flow.Processor` 做变换，用单步 request 演示）。

## Relation to Reactor and RxJava

分工很清楚：

- **JDK 的 Flow**：接口标准 + 最小实现，随 JDK 发布，无额外依赖；
- **Reactor / RxJava**：完整算子生态（`flatMap`、`window`、背压策略、调度器），并实现 `Flow.Publisher` / `Subscriber` 以便与 JDK 侧组件互操作。

新代码要算子与背压策略，用 Reactor / RxJava；只在库边界上接驳（例如让某个库暴露「可订阅」能力又不想引入依赖）时，直接实现 `Flow.Publisher`。

## Links

- [CompletableFuture](/docs/CS/Java/JDK/Concurrency/CompletableFuture.md)
- [Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
- [ThreadPoolExecutor](/docs/CS/Java/JDK/Concurrency/ThreadPoolExecutor.md)
- [ForkJoinPool](/docs/CS/Java/JDK/Concurrency/ForkJoinPool.md)

## References

1. [JEP 266: More Concurrency Updates](https://openjdk.org/jeps/266)
2. [Flow (Java SE 25 & JDK 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/concurrent/Flow.html)
3. [SubmissionPublisher (Java SE 25 & JDK 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/concurrent/SubmissionPublisher.html)
4. [Reactive Streams](http://www.reactive-streams.org/)
