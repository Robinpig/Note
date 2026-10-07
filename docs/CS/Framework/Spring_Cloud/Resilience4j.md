## Introduction

[Resilience4j](https://resilience4j.readme.io/) 是一个轻量级的容错（fault tolerance）库，设计上受 [Netflix Hystrix](/docs/CS/Framework/Spring_Cloud/Hystrix.md) 启发，但面向函数式风格、无外部依赖、面向组合。

> [!NOTE]
> 版本基线：Spring Cloud Circuitbreaker 在 2025.1（Oakwood）随列车统一到 **5.0.x**（跳过 4.0.x），Resilience4j 升级到 **2.3.0**。同时新增一个直接基于 **Spring Framework 7 内建 retry** 的 Circuitbreaker 实现，作为不引入 Resilience4j 时的轻量选择；原 `spring-cloud-circuitbreaker-spring-retry` 模块进入维护状态，待 Spring Retry 停止支持后移除。

与 Hystrix 的关键区别：Hystrix 已停止开发，且强依赖 Archaius、要求继承 `HystrixCommand` 的命令模式；Resilience4j 则是一组独立、可单独引用的模块，用**高阶函数（装饰器）**包装任意函数式接口、lambda 或方法引用，按需叠加熔断、限流、重试、隔离、缓存、限时等能力，也天然适配 Reactor / RxJava。

## Modules

每个能力是一个独立 jar，可按需引入而不必拖入全套：

| 模块 | 作用 |
| ---- | ---- |
| `resilience4j-circuitbreaker` | 熔断器，失败率/慢调用超阈值时快速失败 |
| `resilience4j-ratelimiter` | 限流器，限制单位时间的调用次数 |
| `resilience4j-retry` | 自动重试（可配退避、随机抖动） |
| `resilience4j-bulkhead` | 舱壁隔离，限制并发调用数 |
| `resilience4j-timelimiter` | 超时控制 |
| `resilience4j-cache` | 结果缓存 |
| `resilience4j-reactor` / `-rxjava2/3` | 装饰 `Mono`/`Flux` 等响应式类型 |

## CircuitBreaker

熔断器把对下游的调用包一层，统计失败率与慢调用比例，在下游不健康时**快速失败**，避免请求堆积导致级联雪崩，并给下游喘息恢复的时间。三种状态：

- **CLOSED（关闭/正常）**：请求正常通过，持续统计。
- **OPEN（打开/熔断）**：失败率或慢调用率超过阈值，直接抛 `CallNotPermittedException`，不再发请求。
- **HALF_OPEN（半开）**：OPEN 等待 `waitDurationInOpenState` 后进入，放行少量试探请求；成功则回到 CLOSED，失败则重新 OPEN。

判定条件：`slidingWindowType`（count-based / time-based）、窗口大小、`failureRateThreshold`、`slowCallRateThreshold`、`slowCallDurationThreshold`、`minimumNumberOfCalls`、允许的半开请求数等。

两个容易混淆的参数：`slidingWindowSize` 是**采样空间**，`minimumNumberOfCalls` 是**开始判定所需的最小样本量**。COUNT_BASED 窗口下后者取两者较小值，因此**调大 `minimumNumberOfCalls` 超过 `slidingWindowSize` 是无效的**——在样本量不足前熔断器不会动作，看起来像"配了不生效"。

半开状态的触发还取决于 `automaticTransitionFromOpenToHalfOpenEnabled`：默认 false，**要等下一个请求进来**才会切到 HALF_OPEN；设为 true 则由后台线程在计时结束后主动切换。默认 false 的表现是：下游已恢复，但迟迟没有请求进来，熔断器就一直停在 OPEN。

编程式用法（装饰一个 `Supplier`）：

```java
CircuitBreakerRegistry registry = CircuitBreakerRegistry.ofDefaults();
CircuitBreaker cb = registry.circuitBreaker("userService");

Supplier<List<User>> supplier = CircuitBreaker
        .decorateSupplier(cb, userServiceClient::listUsers);

// 再叠加重试
Supplier<List<User>> withRetry = Retry
        .decorateSupplier(Retry.ofDefaults("retry"), supplier);

Try.ofSupplier(withRetry)
   .recover(CallNotPermittedException.class, e -> List.of()) // 熔断时的降级
   .get();
```

### Decorators and Events

- 装饰方式：`decorateSupplier/Function/CheckedRunnable`，响应式用 `transformDeferred(CircuitBreakerOperator.of(cb))`。
- 事件回调：`cb.getEventPublisher().onSuccess(...)`、`onError(...)`、`onStateTransition(...)`，可接指标与告警。
- 状态与指标通过 [Micrometer](/docs/CS/log/Micrometer.md) 暴露，便于监控熔断状态与失败率。

## Annotations and Aspect Order

多个注解可以叠在同一方法上，但**叠加顺序由切面 order 决定，而不是注解的书写顺序**。这是配置类故障里最难查的一类：代码看着对，行为却不同。

Spring AOP 里 **order 值越小，优先级越高，越在外层**。Resilience4j 的默认值：

| 切面 | 属性 | 默认 order |
| :-- | :-- | :-- |
| Retry | `resilience4j.retry.retryAspectOrder` | `LOWEST_PRECEDENCE - 4` |
| CircuitBreaker | `resilience4j.circuitbreaker.circuitBreakerAspectOrder` | `LOWEST_PRECEDENCE - 3` |
| RateLimiter | `resilience4j.ratelimiter.rateLimiterAspectOrder` | `LOWEST_PRECEDENCE - 2` |
| TimeLimiter | `resilience4j.timelimiter.timeLimiterAspectOrder` | — |
| Bulkhead | `resilience4j.bulkhead.bulkheadAspectOrder` | `LOWEST_PRECEDENCE` |

于是默认嵌套关系是：

```
Retry ( CircuitBreaker ( RateLimiter ( TimeLimiter ( Bulkhead ( method ) ) ) ) )
```

**Retry 默认在最外层，而这通常不是你想要的。** 因为熔断打开后 `CallNotPermittedException` 会被外层的 Retry 当成普通失败来重试——每次重试都立刻被熔断拒绝，白耗完重试次数才抛异常，等于在下游已经明确不可用时还对着它连打若干次。

想要的行为是**熔断在外、重试在内**：熔断一旦打开就直接快速失败，压根不进重试；熔断关闭时才由内层重试处理瞬时抖动。做法是让 CircuitBreaker 的 order 值**小于** Retry：

```yaml
resilience4j:
  circuitbreaker:
    circuitBreakerAspectOrder: 1        # 值更小 → 更外层 → 先判定
  retry:
    retryAspectOrder: 2                # 值更大 → 更内层 → 后执行
```

网上不少文章把这条写反了（"order 值越大优先级越高"），照抄会得到与预期完全相反的嵌套。判断依据始终是 Spring 的规则：**小值优先、小值在外**。

### fallbackMethod Signature Rules

```java
@CircuitBreaker(name = "userService", fallbackMethod = "fallback")
public List<User> listUsers(String tenant) {
    return userServiceClient.listUsers(tenant);
}

// 降级方法：原参数照抄，再追加一个 Throwable 参数
private List<User> fallback(String tenant, CallNotPermittedException e) {
    return List.of();
}
```

规则：

- 返回类型必须与原方法**一致**，参数列表为原参数**追加一个异常参数**。
- 多个降级方法时按**最接近匹配**选择：抛 `NumberFormatException` 会优先匹配签名里写 `NumberFormatException` 的方法，而不是写 `Throwable` 的。
- 想给一批同返回类型的方法配同一个兜底，才定义带 `Throwable` 参数的"全局"降级方法。
- **签名写错不会在启动时报错**，只在真正触发降级时抛 `NoSuchMethodException`——也就是说降级逻辑在平时完全没被验证过，等到故障时才暴露。

### Programmatic and Factory Customization

注解之外，Spring Cloud Circuit Breaker 提供 `CircuitBreakerFactory` 抽象（Resilience4j 实现为 `Resilience4JCircuitBreakerFactory`），可统一给所有实例加默认配置与事件监听：

```java
@Bean
Customizer<Resilience4JCircuitBreakerFactory> slowCalls() {
    return factory -> factory.configureDefault(id -> new Resilience4JConfigBuilder(id)
        .circuitBreakerConfig(CircuitBreakerConfig.custom()
            .slidingWindowType(SlidingWindowType.COUNT_BASED)
            .slidingWindowSize(20)
            .minimumNumberOfCalls(5)
            .failureRateThreshold(50)
            .slowCallRateThreshold(50)
            .slowCallDurationThreshold(Duration.ofSeconds(2))
            .build())
        .build());
}
```

走这个抽象层的好处是**换实现不改业务代码**（Resilience4j、Spring Retry 内建实现可切换），代价是 Resilience4j 的特有能力用不上。反之若已确定用 Resilience4j 且要细粒度调参，直接用它的注解或注册表更直接。

## Other Resilience Patterns

### RateLimiter

令牌桶式限流，限制某个后端在刷新周期内的允许调用数（`limitForPeriod` / `limitRefreshPeriod` / `timeoutDuration`），超出立即拒绝或等待。

### Bulkhead

借鉴船舱分舱的思路，把对不同下游的调用隔离开，避免一个慢下游占满全部线程。两种实现：

- `SemaphoreBulkhead`：信号量限制并发数，轻量、不额外开线程。
- `FixedThreadPoolBulkhead`：固定线程池加队列，提供线程级隔离（更接近 Hystrix 的线程池隔离）。

在启用[虚拟线程](/docs/CS/Framework/Spring/Task.md)的应用里，`FixedThreadPoolBulkhead` 的价值需要重新评估：平台线程稀缺"一个慢下游吃满线程池"的前提被削弱了，而信号量舱壁依然能限制并发数。反过来，**限并发这件事本身仍然有意义**——虚拟线程让"多"变廉价，不代表下游能承受无限并发。

### Retry / TimeLimiter

- `Retry`：配最大尝试次数、固定或指数退避、随机抖动，可对指定异常重试。
- `TimeLimiter`：配合 `CompletableFuture` 或响应式类型给下游调用设上限，防止无限等待。

这些装饰器可像洋葱一样层层包裹，组合出"限流 → 熔断 → 超时 → 重试 → 舱壁"的完整容错链。

## Spring Boot Integration

```yaml
resilience4j:
  circuitbreaker:
    instances:
      userService:
        sliding-window-size: 20
        minimum-number-of-calls: 5
        failure-rate-threshold: 50
        wait-duration-in-open-state: 10s
        permitted-number-of-calls-in-half-open-state: 5
    configs:
      default:
        sliding-window-type: COUNT_BASED
```

指标与端点：CircuitBreaker、Retry、RateLimiter、Bulkhead、TimeLimiter 的指标会自动发布，经 [Actuator](/docs/CS/Framework/Spring_Boot/actuator.md) 的 `/actuator/metrics` 可查（`resilience4j.circuitbreaker.state`、`...calls` 等）；`management.health.circuitbreakers.enabled: true` 可把熔断状态纳入健康端点。

## Common Misconfigurations

| 现象 | 原因 |
| :-- | :-- |
| 熔断打开后还在不停重试 | Retry 在外层，默认顺序所致，需调 aspect order |
| 熔断器迟迟不跳闸 | `minimumNumberOfCalls` 样本量未达标（或超过 `slidingWindowSize` 被截断） |
| 下游恢复后熔断器卡在 OPEN | `automaticTransitionFromOpenToHalfOpenEnabled` 默认 false，没有新请求触发 |
| 降级没生效且报 `NoSuchMethodException` | `fallbackMethod` 签名不匹配，且启动时无校验 |
| 注解配了但完全不生效 | 缺少 `spring-boot-starter-aop`，或方法是同类内部调用（未走代理） |

最后一条是所有 Spring AOP 能力的通病：同类内方法互调绕过了代理，熔断、重试、[事务](/docs/CS/Framework/Spring/Transaction.md)全都失效且无任何提示。

## Links

- [Netflix Hystrix](/docs/CS/Framework/Spring_Cloud/Hystrix.md)
- [Spring Boot Actuator](/docs/CS/Framework/Spring_Boot/actuator.md)
- [Spring Cloud Gateway](/docs/CS/Framework/Spring_Cloud/gateway.md)
- [Spring Task](/docs/CS/Framework/Spring/Task.md)
- [Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md)
- [Spring AOP](/docs/CS/Framework/Spring/AOP.md)

## References

1. [Resilience4j Documentation](https://resilience4j.readme.io/docs/getting-started)
2. [Resilience4j CircuitBreaker](https://resilience4j.readme.io/docs/circuitbreaker)
3. [Spring Cloud Circuit Breaker](https://docs.spring.io/spring-cloud-commons/reference/spring-cloud-commons/circuitbreaker.html)
