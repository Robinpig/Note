## Introduction

JetCache 是一个由阿里巴巴开源的、面向 Java/Spring 生态的轻量级缓存抽象框架。它不替代 Redis 或本地缓存组件，而是站在业务应用层，提供一套统一、易用、生产级的缓存开发与管理方案。

如果熟悉 Spring Cache，可以把 JetCache 理解为"同一件事的更完整版本"：它在注解式缓存之上补出了 **TTL、两级缓存、自动刷新、防击穿** 这几项在生产里绕不开的能力，同时保留了一套脱离注解也能用的 Cache API。缓存自身的体系问题（命中率、一致性、穿透/雪崩）见 [Cache](/docs/CS/SE/Cache.md)，本地缓存的实现原理见 [Caffeine Architecture](/docs/CS/SE/Caffeine/Architecture.md)。

## Configuration Shape

框架按「区域（area）」组织缓存实例，本地与远程各自声明：

```yml
# application.yml
jetcache:
  statIntervalMinutes: 15
  areaInCacheName: false
  local:
    default:
      type: caffeine
      keyConvertor: fastjson2
  remote:
    default:
      type: redis.lettuce
      keyConvertor: fastjson2
      valueEncoder: java
      valueDecoder: java
      uri: redis://127.0.0.1:6379/
```

本地可选 `caffeine` / `linkedhashmap`，远程可选 Redis（含 Lettuce/Jedis 客户端）、阿里 Tair，`statIntervalMinutes` 控制统计输出间隔。

## Annotations

| 注解 | 作用 |
|------|------|
| `@Cached` | 在方法上加缓存；`expire` 定 TTL，`cacheType` 取 `LOCAL` / `REMOTE` / `BOTH` |
| `@CacheUpdate` | 更新缓存项（用新的 value 覆盖），与 `@Cached` 用同一个 name + key |
| `@CacheInvalidate` | 删除缓存项，用于数据失效而非重算的场景 |
| `@CacheRefresh` | 后台定时刷新；`stopRefreshAfterLastAccess` 决定长期无人访问的 key 何时停止刷新 |
| `@CachePenetrationProtect` | 同一 JVM 内并发未命中时只允许一个线程回源，其余等待结果（防缓存击穿） |
| `@CreateCache` | 直接创建 Cache 实例，用于注解不够灵活的场合 |

配合 Spring Boot 时还需要 `@EnableMethodCache` 指定扫描包路径，注解才生效。

## Cache API

注解之外有一套类似 `Map` 的 API，`get` / `put` / `remove` / `computeIfAbsent` 都有，也支持异步（`GET` 返回带 `future()` 的结果）与简单的分布式锁（`tryLockAndRun`）。它实现了 JSR-107 风格的部分接口，因此从 Spring Cache 迁移过来心智负担不大：

```java
cache.computeIfAbsent(1234567L, key -> loadUserFromDataBase(key));
cache.tryLockAndRun("key", 60, TimeUnit.SECONDS, () -> heavyDatabaseOperation());
```

## Two-Level Caching Is Where It Gets Risky

`cacheType = BOTH` 同时启用本地层与远程层，热数据的大部分读请求在本地就被挡掉，能显著降低 Redis 压力与 RT——但它引入了本地层一致性问题：

- 本地层是**每 JVM 独立**的，某个节点更新数据后，其它节点的本地副本必须靠**失效广播**清除；广播通道（`broadcastChannel`）在所有实例上必须配置成同一个值，否则会静默地长期持有脏数据；
- 跨 JVM 的本地失效能力是较晚版本才具备的，早期版本下 `BOTH` 意味着脏数据要熬到 TTL 过期才消失。

因此数据变更频繁、且对一致性敏感的热 key，**不如只用单层远程缓存**；能接受短暂陈旧、且本地层收益明确的场景才用 `BOTH`。这与 [Cache](/docs/CS/SE/Cache.md) 里"多级缓存要算清每一层命中率提升能抵消多少不一致风险"的判断一致。

## When Not to Use It

- 项目已经重度依赖 Spring Cache 且没有上述几项诉求，迁移收益有限；
- 团队不在 Java/Spring 技术栈上——它是为该生态设计的抽象层；
- JDK / Spring Boot 的版本要求会随版本演进变化（README 有过从 JDK 8 起步到更高版本起步的更迭），选型时以当前官方 README 为准。

## Links

- [Cache](/docs/CS/SE/Cache.md)
- [Caffeine](/docs/CS/SE/Caffeine.md)
- [Performance](/docs/CS/SE/Performance.md)

## References

1. [alibaba/jetcache — GitHub](https://github.com/alibaba/jetcache)
2. [阿里巴巴开源的通用缓存访问框架 JetCache 介绍 — 阿里云开发者社区](https://developer.aliyun.com/article/584312)
