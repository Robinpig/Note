## Introduction

HikariCP 不提供像 [Druid](/docs/CS/Java/ConnectionPool/Druid/Monitoring.md) 那样的 Web 控制台，它的可观测性由三件套组成：**`HikariPoolMXBean` 运行时接口**、**Micrometer / Dropwizard 指标**、**泄漏检测与池状态日志**。本文给出接入路径与关键指标。

## HikariPoolMXBean

开启 `registerMbeans=true`（`spring.datasource.hikari.register-mbeans=true`）后，HikariCP 通过 `HikariDataSource.getHikariPoolMXBean()` 暴露一个 `HikariPoolMXBean`，可用 JConsole / VisualVM / Prometheus JMX Exporter 读取：

```java
HikariPoolMXBean bean = hikariDataSource.getHikariPoolMXBean();
log.info("active={} idle={} total={} waiting={}",
        bean.getActiveConnections(),
        bean.getIdleConnections(),
        bean.getTotalConnections(),
        bean.getThreadsAwaitingConnection());
```

常用方法：`getActiveConnections()`、`getIdleConnections()`、`getTotalConnections()`、`getThreadsAwaitingConnection()`；运维动作有 `softEvictConnections()`、`suspendPool()`、`resumePool()`。

## Micrometer / Dropwizard Metrics

Spring Boot Actuator 在引入 `micrometer-core` 后会**自动注册 HikariCP 指标**，经 `/actuator/metrics` 或 `/actuator/prometheus` 暴露：

| 指标 | 含义 |
| --- | --- |
| `hikaricp.connections.active` | 当前正在使用的连接数 |
| `hikaricp.connections.idle` | 空闲连接数 |
| `hikaricp.connections.pending` | 等待获取连接的线程数（**队列深度，> 0 即已有人在排队**） |
| `hikaricp.connections.max` | `maximumPoolSize` 设置值 |
| `hikaricp.connections.min` | `minimumIdle` 设置值 |
| `hikaricp.connections.timeout.total` | 累计获取连接超时次数 |
| `hikaricp.connections.acquire` | 获取连接耗时（直方图） |
| `hikaricp.connections.creation` | 新建连接耗时 |
| `hikaricp.connections.usage` | 连接被线程持有的耗时 |

```bash
curl http://localhost:8080/actuator/metrics/hikaricp.connections.active
curl http://localhost:8080/actuator/metrics/hikaricp.connections.pending
```

> 告警关键看 `hikaricp.connections.pending`：持续 > 0 说明池已耗尽、请求在排队；配合 `hikaricp.connections.timeout.total` 上升即可判定连接池瓶颈（而非慢 SQL 背锅）。

## Leak Detection and Pool Logging

`leakDetectionThreshold` 开启后，若连接被借出超过该毫秒数仍未归还，HikariCP 会在日志打印泄漏堆栈，便于定位未关闭 `Connection` 的代码：

```
HikariPool-1 - Connection leak detection triggered for connection ..., stack trace follows
```

配合 `poolName` 可在多数据源场景下快速定位是哪个池。借还、驱逐、补充等生命周期事件也会打印带 `poolName` 的日志，是排查连接频繁重建（如 [Configuration](/docs/CS/Java/ConnectionPool/HiKariCP/Configuration.md) 的时钟陷阱）的第一手证据。

## Contrast with Druid

| 维度 | HikariCP | Druid |
| --- | --- | --- |
| 监控入口 | MXBean + Micrometer/Dropwizard + 日志 | 内置 Web 控制台 + `DruidDataSourceStatManager` |
| 开箱面板 | 需接 Actuator/Prometheus | `stat-view-servlet` 自带 URI |
| 防注入 | 无（交给 DB/框架） | `WallFilter` SQL Parser |
| 观测哲学 | 极简，把指标交给外部体系 | 一体化，自带全栈监控 |

这正是选型时的核心权衡：**追求极致性能 + 已有 Prometheus/Grafana 体系** → HikariCP；**要开箱即用的监控面板与 SQL 防火墙** → [Druid](/docs/CS/Java/ConnectionPool/Druid.md)。

## Links

- [HiKariCP](/docs/CS/Java/ConnectionPool/HiKariCP.md)
- [Configuration](/docs/CS/Java/ConnectionPool/HiKariCP/Configuration.md)
- [Druid Monitoring](/docs/CS/Java/ConnectionPool/Druid/Monitoring.md)
- [DataSource](/docs/CS/Java/ConnectionPool/ConnectionPool.md)

## References

1. [HikariCP FAQ](https://github.com/brettwooldridge/HikariCP/wiki/FAQ)
