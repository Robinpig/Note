## Introduction

HikariCP 的所有时间参数单位都是**毫秒**，且自带合理默认值，多数部署只需改 `maximumPoolSize` 与 `maxLifetime`。本文给出完整参数表、默认值语义，以及两个生产必知的陷阱（寿命铁律、时钟同步）。架构层面的借还流程见 [Architecture](/docs/CS/Java/ConnectionPool/HiKariCP/Architecture.md)。

## Parameter Table

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `maximumPoolSize` | 10 | 最大连接数；应匹配 DB 可承受并发，而非盲目调大 |
| `minimumIdle` | = `maximumPoolSize` | 最小空闲连接；二者相等即为固定大小池 |
| `connectionTimeout` | 30000 | 借出超时（ms），超时抛 `SQLException` |
| `idleTimeout` | 600000 | 空闲连接存活上限（ms）；`minIdle < maxPoolSize` 时生效 |
| `maxLifetime` | 1800000 | 连接绝对寿命（ms）；**必须比 DB `wait_timeout` 短 1 分钟以上** |
| `keepaliveTime` | 0（关闭） | 周期性探活间隔（ms），维持空闲连接不被中间网络设备回收；必须 `< maxLifetime` |
| `validationTimeout` | 5000 | 连接校验超时（ms） |
| `connectionTestQuery` | 无 | 仅 JDBC4 之前驱动需要；现代驱动用 `isValid()` 无需配置 |
| `leakDetectionThreshold` | 0（关闭） | 借出超过该毫秒数未归还则记录疑似泄漏日志（见 [Monitoring](/docs/CS/Java/ConnectionPool/HiKariCP/Monitoring.md)） |
| `autoCommit` | true | 是否默认自动提交 |
| `poolName` | 自动生成 | 日志/指标中标识该池 |

## Defaults Semantics

- **`minimumIdle` 默认等于 `maximumPoolSize`**：即一个**固定大小**的池，不会在空闲时缩容。`minimumIdle` 仅在你要「弹性缩容」（`< maxPoolSize`）时才显式调小，此时 `idleTimeout` 才会真正回收多余空闲连接。多数高并发服务保持默认固定池即可，避免缩容/扩容的抖动。
- **时间参数的单位是毫秒**：`maxLifetime=1800000` 是 30 分钟，不是 1.8 秒。`connectionTimeout` 默认 30s 已经偏长，高并发常压到 2~5s 避免请求长时间阻塞在等连接上（见 [DataSource](/docs/CS/Java/ConnectionPool/ConnectionPool.md) 的超时维度）。

## Lifetime Rule

> 配置 MySQL 时，`idleTimeout` 与 `maxLifetime` 必须比 MySQL 的 `wait_timeout` **短至少 1 分钟**。否则池可能把一条已被 DB 端静默关闭的连接借给应用，触发 `Communications link failure`（见 ConnectionPool 的 `## Connection Issues`）。

`keepaliveTime` 若开启，必须 `< maxLifetime`，否则探活本身就会把连接撑过寿命上限，失去淘汰意义。

## Clock-Sync Trap

HikariCP 依赖高精度时钟做超时与回收调度，**必须保证服务器时钟同步（NTP）**。在虚拟机里要在**客户机内部**做时钟同步，不能依赖 hypervisor 的时钟对齐——否则 `HouseKeeper` 会检测到「时钟回拨」并对连接做 soft-evict（见 [Architecture](/docs/CS/Java/ConnectionPool/HiKariCP/Architecture.md) 的 HouseKeeper），表现为连接被频繁重建、性能骤降且无明显报错。

## Spring Boot Integration

Spring Boot（`starter-jdbc` / `data-jpa`）自动装配 HikariCP，无需手动声明依赖（手动声明 `com.zaxxer:HikariCP` 可能触发与 Boot 托管版本冲突的告警）。专用参数统一挂在 `spring.datasource.hikari.*` 前缀下：

```yaml
spring:
  datasource:
    url: jdbc:mysql://host:3306/app
    username: app_user
    password: ${DB_PASSWORD}
    hikari:
      maximum-pool-size: 20
      minimum-idle: 20
      connection-timeout: 30000
      max-lifetime: 1800000      # < MySQL wait_timeout
      keepalive-time: 300000
      pool-name: order-svc-pool
      register-mbeans: true      # 暴露 HikariPoolMXBean，见 Monitoring
```

> Spring Boot 3.x 起要求 `jakarta` 命名空间与 Java 17+，与 HikariCP 6/7.x 的 Java 11+ 基线兼容；具体托管的 HikariCP 版本随 Boot 版本走，升级时以 `mvn dependency:tree` 实测为准，不要凭版本号推断。

## Links

- [HiKariCP](/docs/CS/Java/ConnectionPool/HiKariCP.md)
- [Architecture](/docs/CS/Java/ConnectionPool/HiKariCP/Architecture.md)
- [Monitoring](/docs/CS/Java/ConnectionPool/HiKariCP/Monitoring.md)
- [DataSource](/docs/CS/Java/ConnectionPool/ConnectionPool.md)

## References

1. [HikariCP FAQ](https://github.com/brettwooldridge/HikariCP/wiki/FAQ)
