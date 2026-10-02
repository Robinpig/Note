## Introduction

“Reactive”在 Spring 语境里其实有两层容易混淆的含义，需要先分开：

- **响应式系统（Reactive Systems）**：一种架构风格与设计理念，由 [The Reactive Manifesto](https://www.reactivemanifesto.org/) 定义，描述的是**整个分布式系统**应具备的特质。
- **响应式编程（Reactive Programming）**：一种基于**异步数据流 + 非阻塞 + 声明式组合**的编程范式，是构建响应式系统的一种实现手段，Spring 中对应 Reactor + WebFlux。

前者是“系统长什么样”，后者是“代码怎么写”。一个系统可以用阻塞式技术栈实现，却在架构层面满足响应式特质；反之，用了 WebFlux 也不自动等于整个系统就是响应式系统。

## Reactive Manifesto

*Systems built as Reactive Systems are more flexible, loosely-coupled and scalable.
This makes them easier to develop and amenable to change.
They are significantly more tolerant of failure and when failure does occur they meet it with elegance rather than disaster.
Reactive Systems are highly responsive, giving users effective interactive feedback.*

Reactive Systems are:

1. **Responsive（即时响应）**：系统及时响应请求，响应性是可用性与实用性的基石。
2. **Resilient（弹性容错/韧性）**：出现故障仍保持响应，靠复制、隔离、委派和失败 containment 实现，失败被限制在组件内而不拖垮全局。
3. **Elasticic（伸缩性/弹性扩展）**：负载变化时通过增删资源保持响应，无竞争点与中心化瓶颈，允许分片与复制。
4. **Message Driven（消息驱动）**：组件间通过异步消息传递交互，从而获得松耦合、隔离、位置透明与背压（back-pressure）。

四个特质的关系：message driven 是手段，它支撑了 resilient 与 elastic，最终共同保证 responsive。

## Reactive Streams

响应式编程落到 JVM 上的底层规范是 [Reactive Streams](https://www.reactive-streams.org/)，它只定义了四个核心接口：`Publisher`、`Subscriber`、`Subscription`、`Processor`。
其最重要的贡献是把**异步非阻塞**与**背压**标准化：`Subscriber` 通过 `subscription.request(n)` 向上游声明自己还能处理多少数据，从而避免快速生产者压垮慢消费者（这正是消息驱动系统里背压的代码级体现）。

JDK 9 把该规范收进 `java.util.concurrent.Flow`。Spring 选择的实现库是 **Project Reactor**，提供两个核心发布者：

- `Mono<T>`：0 或 1 个元素的异步序列（对应“一个结果”，如返回单个对象）。
- `Flux<T>`：0..N 个元素的异步序列（对应“一串结果/流”）。

操作符（`map` / `flatMap` / `filter` / `merge` / `zip` / `onErrorResume` / `retryBackoff` 等）以声明式方式组合数据流水线，只有在订阅（subscribe）时才真正触发执行。Reactor 细节见 [Reactor](/docs/CS/Framework/reactor/Reactor.md)，线程调度见 [Reactor Scheduler](/docs/CS/Framework/reactor/Scheduler.md)。

## Backpressure

背压是响应式区别于普通异步回调的关键。下游把处理能力反馈给上游，常见策略：`onBackpressureBuffer`（排队缓冲）、`onBackpressureDrop`（丢弃）、`onBackpressureLatest`（只留最新）、`onBackpressureError`（报错）。
在非阻塞 Web 场景里，背压能沿“HTTP 响应 → 业务流 → 数据库驱动”整条链路传导，例如 R2DBC 读取速度会被客户端写入速度限制，避免把整个结果集一次性载入内存。

## Spring WebFlux

Spring 5 引入 [Spring WebFlux](/docs/CS/Framework/Spring/webflux.md)，与基于 Servlet 阻塞模型的 [Spring MVC](/docs/CS/Framework/Spring/MVC.md) 并列：

| 维度 | Spring MVC | Spring WebFlux |
| ---- | ---- | ---- |
| 编程模型 | 同步阻塞，一请求一线程 | 异步非阻塞，少量事件循环线程扛大量连接 |
| 容器 | Servlet 容器（Tomcat） | Netty / Servlet 3.1+ 异步容器 / Undertow |
| 返回类型 | 对象 / `ResponseEntity` | `Mono` / `Flux` |
| 适配场景 | 传统 CRUD、阻塞 JDBC | 高并发连接、流式、需端到端非阻塞（WebClient + R2DBC） |
| 背压 | 无 | 端到端 |

关键约束：**响应式收益要求整条链路非阻塞**。如果在 WebFlux 的 handler 里调用阻塞的 JDBC 或 `Thread.sleep`，会卡住极少数事件循环线程，反而比 MVC 更差。因此数据访问要配 R2DBC / 响应式 NoSQL 驱动（见 [Spring Data](/docs/CS/Framework/Spring/Data.md)），出站调用用 `WebClient` 而非 `RestTemplate`。

并非所有应用都该上响应式：在典型阻塞型业务（大量同步 ORM 访问）下，MVC + 虚拟线程往往更简单且吞吐足够；WebFlux 的价值集中在超高并发连接数、流式推送与 IO 密集的网关/聚合层。

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [Spring WebFlux](/docs/CS/Framework/Spring/webflux.md)
- [Spring MVC](/docs/CS/Framework/Spring/MVC.md)
- [Reactor](/docs/CS/Framework/reactor/Reactor.md)
- [Spring Data](/docs/CS/Framework/Spring/Data.md)

## References

1. [The Reactive Manifesto](https://www.reactivemanifesto.org/)
2. [Reactive Streams Specification](https://www.reactive-streams.org/)
3. [Project Reactor Reference](https://projectreactor.io/docs/core/release/reference/)
4. [Spring WebFlux Reference](https://docs.spring.io/spring-framework/reference/web/webflux.html)
