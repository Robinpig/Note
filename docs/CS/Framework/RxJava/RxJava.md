## Introduction

[RxJava](https://github.com/ReactiveX/RxJava) 是 Reactive Extensions（Rx）在 JVM 上的实现，是**响应式编程（FRP 风格）在 Java 生态的开山库**。
它把数据流抽象为可被订阅、可组合的 `Observable`，用一整套操作符以声明式方式处理异步与事件序列，并内置线程切换与背压支持。

RxJava 早于 [Project Reactor](/docs/CS/Framework/reactor/Reactor.md) 出现，深刻影响了后来的 Reactive Streams 规范与 Spring WebFlux 栈；
二者概念高度对应，差异主要在 API 历史包袱与定位上（RxJava 面向更广义的多语言 Rx 家族，Reactor 是 Spring 的默认实现）。

## Observable Types

RxJava 3 按「元素数量」与「是否支持背压」区分五种源类型：

| 类型 | 元素数 | 背压 | 典型场景 |
| --- | --- | --- | --- |
| `Observable<T>` | 0..N | 不支持 | UI 事件、点击流、本来就无法降速的数据源 |
| `Flowable<T>` | 0..N | 支持（Reactive Streams `Publisher`） | 大数量、IO、需要背压的管道 |
| `Single<T>` | 恰好 1（或 error） | — | 一次性结果，类似 `CompletableFuture` |
| `Maybe<T>` | 0 或 1 | — | 可能为空的结果 |
| `Completable` | 0（只发完成/错误） | — | 只关心「做完没有」，如写库 |

与 Reactor 的对应关系几乎一一对应：`Flowable↔Flux`、`Single/Maybe↔Mono`、`Observable` 则是 Reactor 没有直接对应的「无背压流」。

## Signals

一条流由三类信号驱动：`onNext`（数据，可多次）、`onComplete`（正常结束）、`onError`（异常，终止信号）。
`onComplete` 与 `onError` 互斥且只出现一次，这是观察者模式 + 迭代器语义的结合（Reactive Streams 同样如此）。

```java
Flowable.just(1, 2, 3)
        .map(i -> i * 2)
        .filter(i -> i > 2)
        .subscribe(
            x  -> System.out.println(x),       // onNext
            e  -> log.error("error", e),       // onError
            () -> System.out.println("done")); // onComplete
```

## Nothing Happens Until Subscribe

与 [Reactor](/docs/CS/Framework/reactor/Reactor.md) 一样**声明与执行分离、默认冷（cold）且惰性**：
在 `subscribe()` 之前，操作符链只是在描述管道，不会取数、不发请求。每个新订阅者都会重新触发一次 cold 源；
要在多个订阅者间共享同一份数据流，用 `publish()`/`share()`（hot）或 `cache()`。

## Operators

操作符是 Rx 的核心资产，分类与 Reactor 基本同构：

- 变换：`map`、`flatMap`（异步 1→N，不保序）、`concatMap`（保序串行）、`switchMap`（只留最新）。
- 过滤/聚合：`filter`、`take`、`skip`、`distinct`、`reduce`、`toList`、`groupBy`。
- 组合：`zip`、`merge`、`concat`、`combineLatest`、`amb`。
- 错误处理：`onErrorReturn`、`onErrorResumeNext`、`retry`/`retryWhen`（可配退避）。
- 时间：`debounce`（抖动去抖）、`throttleFirst/throttleLast`、`sample`、`buffer`、`window`、`delay`——这是 Rx 在 UI/事件场景特别常用的一族。

选择 `flatMap` vs `concatMap` 同样是高频考点：前者并发高但乱序，后者保序但牺牲并发。

## Threading: subscribeOn / observeOn

RxJava 的源本身不绑定线程，线程由 [Scheduler](/docs/CS/Framework/RxJava/Scheduler.md) 决定：

- `subscribeOn(...)`：决定**订阅与数据源发射**所在的线程（整条链向上只生效一次，位置不限）。
- `observeOn(...)`：决定其**下游操作符**所在的线程，可在链中多次出现，逐段切换。

这与 Reactor 的 `subscribeOn`/`publishOn` 语义一致。内置 Scheduler 有 `io`（缓存线程池，适合阻塞 IO）、`computation`（核数固定，CPU 密集）、
`single`、`newThread`、`trampoline`（当前线程排队）。铁律：不要把阻塞调用放进 computation/event-loop 线程。

## Backpressure

`Observable` 不支持背压，遇到快生产者会有 `MissingBackpressureException` 风险；需要背压时使用 `Flowable`，
它实现了 Reactive Streams 的 `Publisher`，下游通过 `request(n)` 拉取。策略与 Reactor 对应：
`onBackpressureBuffer`、`onBackpressureDrop`、`onBackpressureLatest`。

## RxJava vs Reactor

| 维度 | RxJava 3 | Project Reactor |
| --- | --- | --- |
| 出身 | Netflix 发起，多语言 Rx 家族的 JVM 成员 | Pivotal/Spring，为 WebFlux 而生 |
| 冷类型 | Observable(无背压)/Flowable/Single/Maybe/Completable | Flux/Mono |
| 背压 | 仅 Flowable | Flux 原生支持 |
| 与 Spring | 可经适配器接入 | 原生默认 |
| 典型场景 | Android（RxJava/RxAndroid）、事件驱动、已有 Rx 代码 | Spring WebFlux、R2DBC 端到端响应式 |
| Reactive Streams | Flowable 实现 Publisher | Mono/Flux 均实现 Publisher |

两者经 `reactor-adapter` / RxJava 的 `Flowable` 互转成本很低，掌握其一后迁移主要是改操作符命名与冷热类型选择。

## Links

- [RxJava Scheduler](/docs/CS/Framework/RxJava/Scheduler.md)
- [Project Reactor](/docs/CS/Framework/reactor/Reactor.md) — 概念对照与 Spring 默认实现
- [Reactor Scheduler](/docs/CS/Framework/reactor/Scheduler.md)
- [Spring Reactive](/docs/CS/Framework/Spring/Reactive.md)

## References

1. [RxJava (GitHub)](https://github.com/ReactiveX/RxJava)
2. [ReactiveX](https://reactivex.io/)
3. [Reactive Streams Specification](https://www.reactive-streams.org/)
