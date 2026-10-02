## Introduction

熔断器（Circuit Breaker）源自电路里的保险丝：当下游服务持续失败时，调用方主动"跳闸"，在一段时间内直接返回失败/降级结果而不再发请求，避免请求线程被慢调用全部占满导致故障级联放大（雪崩）。它与限流、降级、隔离舱一起构成微服务的**韧性（resilience）四件套**。

没有熔断器时的典型死法：下游响应从 10ms 恶化到 5s，调用方线程池/连接池在等待中被耗尽，上游自己也被拖垮——一台节点的故障沿调用链反向扩散，最终整条链路不可用。

## 三种状态

```
        失败率超阈值                超时后放一个探测请求
 CLOSED ───────────────► OPEN ──────────────────────► HALF_OPEN
  ▲                         │                            │
  │探测成功(或连续成功)       │探测仍失败                   │
  └─────────────────────────┴────────────────────────────┘
```

- **CLOSED（关闭/正常）**：请求正常通过，统计滑动窗口内的失败率/慢调用率；
- **OPEN（打开/跳闸）**：直接快速失败（fail-fast），不再访问下游，可走 fallback 降级逻辑；持续 `waitDurationInOpenState` 后进入半开；
- **HALF_OPEN（半开）**：放行有限数量的探测请求，成功达到阈值则回到 CLOSED，仍有失败则重回 OPEN。半开防止下游刚恢复时被海量请求再次压垮（惊群）。

## 关键参数

- 失败率阈值（如 50%）与最小统计样本数（样本太少不判熔断，避免冷启动误判）；
- 慢调用比例阈值与慢调用耗时定义（RT 超过 N 秒即记为慢，不必等到超时）；
- 滑动窗口：基于计数（最近 N 次）或时间（最近 N 秒），时间窗口还要选桶粒度；
- OPEN 等待时长、HALF_OPEN 探测数、fallback 降级策略（返回默认值、缓存旧值、排队稍后重试）。

## 实现

- **Resilience4j**（推荐，轻量函数式）：`CircuitBreakerRegistry` 创建断路器，支持注解 `@CircuitBreaker(fallbackMethod=...)`，基于 Ring Bit Buffer 统计；同一库还提供 Bulkhead（线程隔离）、RateLimiter、Retry、TimeLimiter。
- **Hystrix**（Netflix，已停止维护）：最早普及该模式，线程池隔离是其标志性设计（代价是线程切换开销）；新项目不应再用。
- **Sentinel**：阿里开源，熔断与[限流](/docs/CS/SE/RateLimiter.md)一体，按资源统计，支持流控/热点/系统自适应规则，见 [Sentinel 熔断器](/docs/CS/Framework/Sentinel/CircuitBreaker.md)。
- 服务网格层：Istio/Envoy 的 OutlierDetection（主动驱逐异常端点）在流量层实现同等效果，语言无关。

## 与其他模式的边界

| 模式 | 触发依据 | 作用 |
|------|---------|------|
| Timeout 超时 | 单次请求耗时 | 不把资源无限期押在一个调用上（熔断的前置条件） |
| Retry 重试 | 单次失败 | 对幂等操作重试瞬时故障；必须配合退避，否则加剧雪崩 |
| Circuit Breaker | 一段时间窗的统计失败率 | 保护调用方与下游，给故障方恢复窗口 |
| Bulkhead 隔离舱 | 并发占用 | 给每个依赖独立线程池/信号量，互不拖垮 |
| RateLimiter | 请求速率 | 入口削峰，见 [RateLimiter](/docs/CS/SE/RateLimiter.md) |

注意熔断是"有损"方案（跳闸期间部分用户拿到降级结果），与缓存降级一样属于用局部体验换整体可用，缓存侧的雪崩/击穿应对见 [Cache](/docs/CS/SE/Cache.md)。

## Links

- [Sentinel 熔断器](/docs/CS/Framework/Sentinel/CircuitBreaker.md)
- [RateLimiter](/docs/CS/SE/RateLimiter.md)
- [Cache](/docs/CS/SE/Cache.md)
- [SystemDesign 高可用](/docs/CS/SE/SystemDesign.md)

## References

1. [CircuitBreaker - Martin Fowler](https://martinfowler.com/bliki/CircuitBreaker.html)
2. [Resilience4j 官方文档](https://resilience4j.readme.io/docs/circuitbreaker)
