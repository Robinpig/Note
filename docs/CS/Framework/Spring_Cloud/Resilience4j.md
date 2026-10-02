## Introduction

[Resilience4j](https://resilience4j.readme.io/) 是一个轻量级的容错（fault tolerance）库，设计上受 [Netflix Hystrix](/docs/CS/Framework/Spring_Cloud/Hystrix.md) 启发，但面向 Java 8 函数式风格、无外部依赖、面向组合。

与 Hystrix 的关键区别：Hystrix 已停止开发（Hystrix 进入维护态，官方推荐继任者就是 Resilience4j），并且 Hystrix 强依赖 Archaius、用继承 `HystrixCommand` 的命令模式；Resilience4j 则是一组独立、可单独引用的模块，用**高阶函数（装饰器）**包装任意函数式接口、lambda 或方法引用，按需叠加熔断、限流、重试、隔离、缓存、限时等能力，也天然适配 Reactor / RxJava。

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

熔断器是核心。它把对下游的调用包一层，统计失败率与慢调用比例，在下游不健康时**快速失败**（fail fast），避免请求堆积导致级联雪崩，并给下游喘息恢复的时间。三种状态：

- **CLOSED（关闭/正常）**：请求正常通过，持续统计。
- **OPEN（打开/熔断）**：失败率或慢调用率超过阈值，直接抛 `CallNotPermittedException`，不再发请求。
- **HALF_OPEN（半开）**：OPEN 等待一段 `waitDurationInOpenState` 后进入，放行少量试探请求；成功则回到 CLOSED，失败则重新 OPEN。

判定条件可配置：`slidingWindowType`（count-based / time-based）、窗口大小、`failureRateThreshold`、`slowCallRateThreshold`、`slowCallDurationThreshold`、最小调用数、允许的半开请求数等。

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

### 装饰器与事件

- 装饰方式：`decorateSupplier/Function/CheckedRunnable`，响应式用 `transformDeferred(CircuitBreakerOperator.of(cb))`。
- 事件回调：`cb.getEventPublisher().onSuccess(...)`、`onError(...)`、`onStateTransition(...)`，可接指标与告警。
- 状态与指标通过 Micrometer / Actuator 暴露，便于监控熔断状态与失败率。

## Other Resilience Patterns

### RateLimiter

令牌桶式限流，限制某个后端在刷新周期内的允许调用数（`limitForPeriod` / `limitRefreshPeriod` / `timeoutDuration`），超出立即拒绝或等待。

### Bulkhead（舱壁）

借鉴船舱分舱的思路，把对不同下游的调用隔离开，避免一个慢下游占满全部线程。两种实现：

- `SemaphoreBulkhead`：信号量限制并发数，轻量、不额外开线程。
- `FixedThreadPoolBulkhead`：固定线程池 + 队列，提供线程级隔离（更接近 Hystrix 的线程池隔离）。

### Retry / TimeLimiter

- `Retry`：配最大尝试次数、固定/指数退避、随机抖动，可对指定异常重试。
- `TimeLimiter`：配合 `CompletableFuture` / 响应式类型给下游调用设上限，防止无限等待。

这些装饰器可像洋葱一样层层包裹，组合出“限流 → 熔断 → 超时 → 重试 → 舱壁”的完整容错链；顺序有讲究（通常最外层限流/超时，重试在内侧，避免对熔断态做无意义重试）。

## Spring Boot Integration

Spring Cloud Circuit Breaker 提供了对 Resilience4j 的封装，也可直接用 `spring-boot-starter-aop` + 注解式声明：

```yaml
resilience4j:
  circuitbreaker:
    instances:
      userService:
        sliding-window-size: 20
        failure-rate-threshold: 50
        wait-duration-in-open-state: 10s
        permitted-number-of-calls-in-half-open-state: 5
```

```java
@CircuitBreaker(name = "userService", fallbackMethod = "fallback")
public List<User> listUsers() {
    return userServiceClient.listUsers();
}

private List<User> fallback(CallNotPermittedException e) {
    return List.of();   // 熔断打开时的兜底
}
```

## Links

- [Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md?id=circuit-breaker)
- [Netflix Hystrix](/docs/CS/Framework/Spring_Cloud/Hystrix.md)
- [Spring Cloud Gateway](/docs/CS/Framework/Spring_Cloud/gateway.md)
- [Micrometer](/docs/CS/log/Micrometer.md)

## References

1. [Resilience4j Documentation](https://resilience4j.readme.io/docs/getting-started)
2. [Resilience4j CircuitBreaker](https://resilience4j.readme.io/docs/circuitbreaker)
3. [Spring Cloud Circuit Breaker](https://docs.spring.io/spring-cloud-commons/reference/spring-cloud-commons/circuitbreaker.html)
