## Introduction

Project Reactor 是一个基于 [Reactive Streams](https://www.reactive-streams.org/) 规范的 JVM 响应式编程库，是 **Spring WebFlux / Spring 响应式栈的默认实现**。
Spring 里的 `Mono`、`Flux`、`WebClient`、R2DBC 响应式数据访问都构建在 Reactor 之上；它也可以脱离 Spring 单独使用。

Reactor 的定位是“响应式管道的胶水层”：用声明式的操作符把异步的数据流组装起来，通过非阻塞 + 背压，让少量线程支撑高并发。它本身不是 Web 框架（那是 WebFlux），也不是数据驱动的理念本身（那见 [Spring Reactive](/docs/CS/Framework/Spring/Reactive.md)）。

## Mono and Flux

Reactor 围绕两个核心发布者类型展开，二者都实现了 Reactive Streams 的 `Publisher`：

- **`Mono<T>`**：发出 **0 或 1 个**元素后结束（可能成功 `onComplete` 或失败 `onError`）。适合“返回一个结果”的异步调用，相当于响应式版本的 `CompletableFuture<T>`/单个对象。
- **`Flux<T>`**：发出 **0..N 个**元素的异步序列，可以是有限集合，也可以是无限流（如事件、WebSocket 消息）。

```java
Mono<User> user = userRepository.findById(1L);          // 0/1
Flux<Order> orders = orderRepository.findByUserId(1L);  // 0..N
```

Reactive Streams 的三种信号：`onNext`（数据）、`onComplete`（正常结束）、`onError`（异常终止，是终止信号，会沿链路传播）。

## Nothing Happens Until You Subscribe

Reactor 的关键特性是**声明与执行分离、默认冷（cold）且惰性**：在调用 `subscribe()`（或由 WebFlux 框架替你订阅）之前，操作符只是在描述一条流水线，**不会真正执行任何数据获取**。

```java
Flux<String> flux = Flux.just("a","b","c")
        .map(String::toUpperCase)   // 此刻还不会执行
        .doOnNext(s -> log.info(s));

flux.subscribe();   // 触发后数据才开始流动
```

在 WebFlux 的 Controller 里直接返回 `Mono`/`Flux` 即可，订阅发生在框架层；如果在非 Web 的命令式代码里不订阅，整条链什么都不会发生（一个经典坑）。

`Mono`/`Flux` 是 cold 的：每个新订阅者都会重新触发数据源（如重新发起一次 HTTP 请求）；要共享/复用流需显式用 `cache()`、`share()`、`Sinks` 或 hot publisher。

## Operators

操作符以声明式组合流水线，常见分类：

- **转换**：`map`（同步变换）、`flatMap`（异步 1→N 后合并，不保序）、`concatMap`（保序、串行）、`switchMap`（只保留最新）。
- **过滤/聚合**：`filter`、`take`、`skip`、`distinct`、`reduce`、`collectList`、`groupBy`。
- **组合**：`zip`（按位组合多个源）、`merge`（交错合并）、`concat`（顺序拼接）、`then`（丢弃数据只关心完成信号）。
- **错误处理**：`onErrorReturn`（兜底值）、`onErrorResume`（切换到备用流）、`onErrorMap`（转换异常）、`retry` / `retryBackoff` / `retryWhen`（重试，可配退避）。
- **阻塞逃生舱**：`block()`/`blockFirst()` 会把响应式代码拉回阻塞，**绝不能在响应式线程里调用**（会死锁/破坏非阻塞），仅适合测试或边界适配。

选择 `flatMap` vs `concatMap` 是高频考点：前者高并发但乱序，后者保证顺序但牺牲并发。

## Scheduler and Threading

Reactor 的发布者本身不持有线程，线程由 **Scheduler** 决定切换点：`publishOn` 影响其下游，`subscribeOn` 影响订阅与数据源的线程。
常见 Scheduler 与响应式数据库/Web 客户端内置的 event-loop 线程见 [Reactor Scheduler](/docs/CS/Framework/reactor/Scheduler.md)。核心原则：操作符链内绝不放阻塞调用，否则会占用极少的事件循环线程拖垮整个应用。

## Backpressure

背压是 Reactive Streams 的灵魂：下游通过 `request(n)` 向上游声明需求，生产者按需求发数据，避免快速生产者压垮慢消费者。`Flux` 的限流操作符 `onBackpressureBuffer` / `onBackpressureDrop` / `onBackpressureLatest` 定义无法即时消费时的策略。
在 WebFlux + R2DBC 的端到端链路里，背压可以从 HTTP 响应一路传导到数据库读取（见 [Spring Data](/docs/CS/Framework/Spring/Data.md)）。

## Error Handling Model

- 错误是**终止事件**而非返回值：一旦某环节 `onError`，默认后续数据停止流动，除非用 `onErrorResume` 等接管。
- `try/catch` 对异步链无效，必须用响应式操作符表达异常处理与重试。
- 检查型异常需要在 lambda 内处理或包装；`Exceptions.propagate` / `Exceptions.unwrap` 用于在操作符间传递。

## Testing

用 `reactor-test` 的 `StepVerifier` 以声明式断言流的元素、完成与错误：

```java
StepVerifier.create(Flux.just(1, 2, 3).map(i -> i * 2))
        .expectNext(2, 4, 6)
        .verifyComplete();
```

可用 `withVirtualTime` 测试基于时间的操作符（`delayElements`、窗口），不必真实等待。

## Links

- [Reactor Scheduler](/docs/CS/Framework/reactor/Scheduler.md)
- [RxJava](/docs/CS/Framework/RxJava/RxJava.md) — 同源响应式模型对照（Observable/Flowable）
- [Spring Reactive](/docs/CS/Framework/Spring/Reactive.md)
- [Spring WebFlux](/docs/CS/Framework/Spring/webflux.md)
- [Spring Data / R2DBC](/docs/CS/Framework/Spring/Data.md)
- [Netty](/docs/CS/Framework/Netty/Netty.md)

## References

1. [Project Reactor Reference Documentation](https://projectreactor.io/docs/core/release/reference/)
2. [Reactive Streams Specification](https://www.reactive-streams.org/)
3. [Which operator do I need?](https://projectreactor.io/docs/core/release/reference/#which-operator)
