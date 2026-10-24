## Introduction

[HikariCP](https://github.com/brettwooldridge/HikariCP) contains many micro-optimizations that individually are barely measurable, but together combine as a boost to overall performance.
Some of these optimizations are measured in fractions of a millisecond amortized over millions of invocations.

Version baseline: 最新稳定版 **7.1.0**（2026-06），**HikariCP 6.x / 7.x 要求 Java 11+**；Java 8 只能停留在 5.x（4.0.3 处于维护模式）。7.x 用 `VarHandle` 重写了并发控制，进一步压低 `ConcurrentBag` 的争用开销。HikariCP 是 **Spring Boot 2.0+ 的默认连接池**，依赖 `spring-boot-starter-jdbc` / `data-jpa` 即自动装配。

HikariCP 与同类实现的取舍见 [DataSource](/docs/CS/Java/ConnectionPool/ConnectionPool.md) 的 `## Implementations Map`；重监控/防注入能力对照 [Druid](/docs/CS/Java/ConnectionPool/Druid.md)，通用稳健型对照 [DBCP](/docs/CS/Java/ConnectionPool/DBCP.md)。

## Map of This Section

HikariCP 的「快」不是玄学，而是一组可被拆解的工程选择。本节四篇分册从四个角度把它讲透：

- [Architecture](/docs/CS/Java/ConnectionPool/HiKariCP/Architecture.md) 是骨架：先把 `HikariDataSource` → `HikariPool` → `ConcurrentBag` → `ProxyConnection` 这条主链路，以及 `PoolEntry`、`HouseKeeper` 等关键组件讲清楚，理解连接是怎么被借出、归还与回收的。
- [Performance](/docs/CS/Java/ConnectionPool/HiKariCP/Performance.md) 解释为什么快：`FastList` 替换 `ArrayList`、`ConcurrentBag` 的无锁设计、以及构建期用 Javassist 生成代理把 `invokevirtual` 改成 `invokestatic` 这几项微优化如何叠加成借还开销的数量级下降，并给出与 Druid / DBCP 的对照。
- [Configuration](/docs/CS/Java/ConnectionPool/HiKariCP/Configuration.md) 是把旋钮拧进生产：所有时间参数的单位与默认值、`minIdle = maxPoolSize` 的固定池语义、`maxLifetime` 必须短于 DB `wait_timeout` 的铁律，以及 Spring Boot 的 `spring.datasource.hikari.*` 装配与时钟同步陷阱。
- [Monitoring](/docs/CS/Java/ConnectionPool/HiKariCP/Monitoring.md) 讲如何观测：HikariCP 不像 Druid 有内置 Web 控制台，它的可观测性来自 `HikariPoolMXBean`、Micrometer / Dropwizard 指标、泄漏检测日志三件套，本节给出接入 Actuator / Prometheus 的具体路径。

## Links

- [DataSource](/docs/CS/Java/ConnectionPool/ConnectionPool.md)
- [Druid](/docs/CS/Java/ConnectionPool/Druid.md)
- [DBCP](/docs/CS/Java/ConnectionPool/DBCP.md)

## References

1. [HikariCP FAQ](https://github.com/brettwooldridge/HikariCP/wiki/FAQ)
