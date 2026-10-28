## Introduction

DBCP2 的可观测性来自底层 Commons Pool2 的 `GenericObjectPoolMXBean` 与 DBCP2 自己的 JMX 开关，外加 Micrometer / Spring Boot Actuator 的自动接入。本文给出接入路径与关键指标，并对比 [Druid](/docs/CS/Java/ConnectionPool/Druid/Monitoring.md) / [HikariCP](/docs/CS/Java/ConnectionPool/HiKariCP/Monitoring.md) 的监控路径。

## JMX (GenericObjectPoolMXBean)

`GenericObjectPool` 实现了 `GenericObjectPoolMXBean`，通过 `BasicDataSource.setJmxEnabled(true)` 或 `jmx-name`（Spring Boot 的 `spring.datasource.dbcp2.jmx-name`）暴露。常用指标：

| 指标（MXBean 属性） | 含义 |
| --- | --- |
| `NumActive` | 当前借出的连接数 |
| `NumIdle` | 当前空闲连接数 |
| `NumWaiters` | 正在等待连接的线程估计数（**> 0 即池已饱和**） |
| `MeanBorrowWaitTimeMillis` | 平均借出等待时间（高说明争用严重） |
| `BorrowedCount` / `ReturnedCount` | 累计借出 / 归还次数 |
| `CreatedCount` / `DestroyedCount` | 累计创建 / 销毁连接数 |

> 与 HikariCP 的 `HikariPoolMXBean` 相比，DBCP2 的指标由 Commons Pool2 统一定义，对**任何** Commons Pool2 池化对象都一致；`NumWaiters` / `MeanBorrowWaitTimeMillis` 是判断瓶颈最直接的信号。

## Micrometer / Spring Boot Actuator

引入 `micrometer-core` 与 Actuator 后，Spring Boot 的 `DataSourcePoolMetrics` 会自动为 DBCP2 暴露 `jdbc.connections.*`（active / idle / minimum / maximum），足以支撑池饱和告警，无需自己接 JMX Exporter。

```bash
curl http://localhost:8080/actuator/metrics/jdbc.connections.active
curl http://localhost:8080/actuator/metrics/jdbc.connections.max
```

## Abandoned Connection Detection

DBCP2 的泄漏检测叫「Abandoned」，对应连接被借出却既不使用也不归还：

| 参数 | 作用 |
| --- | --- |
| `removeAbandonedOnBorrow` | 借出时若池接近饥饿，触发 abandoned 检查 |
| `removeAbandonedOnMaintenance` | 由 evictor 线程周期性检查（推荐开启） |
| `removeAbandonedTimeout`（秒） | 借出超过该秒数未归还即判定为 abandoned |
| `logAbandoned` | 回收时打印借出处的调用栈，便于定位未关闭连接的代码 |

> 与 [HikariCP](/docs/CS/Java/ConnectionPool/HiKariCP/Monitoring.md) 的 `leakDetectionThreshold`（只告警、不回收）不同，DBCP2 的 abandoned 机制**既记录又强制回收**，代价是 `logAbandoned` 会捕获完整栈，生产高并发下有一定开销，按需开启。

## Contrast

| 维度 | DBCP2 | Druid | HikariCP |
| --- | --- | --- | --- |
| 监控入口 | JMX (`GenericObjectPoolMXBean`) + Micrometer | Web 控制台 + `DruidDataSourceStatManager` | MXBean + Micrometer |
| 指标前缀 | `jdbc.connections.*` / Pool2 MXBean | `druid.*` | `hikaricp.connections.*` |
| 防注入 | 无 | `WallFilter` | 无 |
| 泄漏检测 | Abandoned（回收 + 可选栈） | 无内置 | `leakDetectionThreshold`（仅告警） |

## Links

- [DBCP](/docs/CS/Java/ConnectionPool/DBCP.md)
- [Configuration](/docs/CS/Java/ConnectionPool/DBCP/Configuration.md)
- [Druid Monitoring](/docs/CS/Java/ConnectionPool/Druid/Monitoring.md)
- [DataSource](/docs/CS/Java/ConnectionPool/ConnectionPool.md)

## References

1. [Apache Commons Pool2 GenericObjectPoolMXBean](https://commons.apache.org/proper/commons-pool/apidocs/org/apache/commons/pool2/impl/GenericObjectPoolMXBean.html)
2. [Apache Commons DBCP Configuration](https://commons.apache.org/proper/commons-dbcp/configuration.html)
