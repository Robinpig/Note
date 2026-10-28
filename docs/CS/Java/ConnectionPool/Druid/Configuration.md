## Introduction

架构与监控讲「能做什么」，本篇讲「怎么开、怎么调」。Druid 没有 HikariCP 那种零配置哲学，生产上通常需要显式声明核心参数，并通过 `druid-spring-boot-starter` 把 [Architecture](/docs/CS/Java/ConnectionPool/Druid/Architecture.md) 的过滤链和 [Monitoring](/docs/CS/Java/ConnectionPool/Druid/Monitoring.md) 的统计能力拧进 Spring 环境。总览见 [Druid](/docs/CS/Java/ConnectionPool/Druid.md)，通用参数语义对照见 [DataSource](/docs/CS/Java/ConnectionPool/ConnectionPool.md) 的 `## Parameter Mapping`。

## Parameter Groups

### Connection Scale

| 参数 | 常用值 | 说明 |
| --- | --- | --- |
| `url` / `username` / `password` | — | JDBC 基础连接信息 |
| `initialSize` | 0 | 启动时初始建立的连接数 |
| `maxActive` | 8（建议调大） | 最大活跃连接数，应等于 DB 可承受并发上限 |
| `minIdle` | 0 | 最小空闲连接数，`CreateThread` 据此补充 |
| `maxWait` | -1（建议 60000） | 获取连接最大等待（ms），-1 表示无限等待；该值 `> 0` 会触发 fair 锁（见 [Architecture](/docs/CS/Java/ConnectionPool/Druid/Architecture.md?id=fair-lock)） |

### Validation and Eviction

| 参数 | 常用值 | 说明 |
| --- | --- | --- |
| `validationQuery` | `SELECT 1`（MySQL） | 校验 SQL；JDBC4 驱动可省，靠 `isValid()` |
| `validationQueryTimeout` | 秒 | 校验查询超时 |
| `testWhileIdle` | true（推荐） | 空闲时校验，由 `DestroyThread` 驱逐扫描触发，开销小、保活好 |
| `testOnBorrow` | false（推荐） | 借出时校验，每次借都多一次 SQL/isValid 往返，高并发得不偿失 |
| `testOnReturn` | false | 归还时校验，一般无需 |
| `timeBetweenEvictionRunsMillis` | 60000 | `DestroyThread` 驱逐扫描间隔（ms） |
| `minEvictableIdleTimeMillis` | 300000 | 空闲超过该值即可被驱逐（ms） |
| `maxEvictableIdleTimeMillis` | — | 空闲硬上限，超过立即驱逐（优先级高于 `minEvictableIdleTimeMillis`） |
| `keepAlive` | false | 保活：对空闲超 `keepAliveBetweenTimeMillis` 的连接发校验，防被中间网络设备回收 |
| `keepAliveBetweenTimeMillis` | — | 保活判定间隔（ms） |

### Leak and Hardening

| 参数 | 常用值 | 说明 |
| --- | --- | --- |
| `removeAbandoned` | false（见下） | 强制回收「借出超时不还」的连接 |
| `removeAbandonedTimeout` | 秒 | 借出超过该值即判定为泄漏并强摘 |
| `logAbandoned` | true（排查时） | 记录连接借出时的堆栈，定位未 `close()` 的代码 |
| `breakAfterIfSQLException` | false | 连接抛 SQL 异常后是否直接剔除（避免坏连接复用） |
| `connectionProperties` | 如 `config.decrypt=true` | 驱动额外属性，可接 Druid 的密码加密 |

## Spring Boot Starter

引入 `druid-spring-boot-starter`（不引则需在 `@Bean` 上 `@ConfigurationProperties(prefix="spring.datasource.druid")` 手动绑定），通过 `spring.datasource.druid.*` 声明式配置：

```yaml
spring:
  datasource:
    type: com.alibaba.druid.pool.DruidDataSource
    url: jdbc:mysql://localhost:3306/app?useUnicode=true&characterEncoding=utf8
    username: app
    password: ${DB_PWD}
    druid:
      initial-size: 5
      min-idle: 5
      max-active: 50
      max-wait: 60000
      time-between-eviction-runs-millis: 60000
      min-evictable-idle-time-millis: 300000
      test-while-idle: true
      test-on-borrow: false
      test-on-return: false
      validation-query: SELECT 1
      keep-alive: true
      filters: stat,wall,slf4j
```

典型生产配置要点：`max-active` 配到 DB 侧连接上限以内、`test-while-idle=true` 做廉价保活、显式 `max-wait` 避免线程无限阻塞、`filters` 开启 `stat,wall` 同时拿到监控与防注入。

## Validation and Leak

`testXXX` 开启建议：**通常开 `testWhileIdle`（`testIdle`），`testOnBorrow` 可不开**——借出校验每次都多一次 SQL 往返，高并发下得不偿失；空闲校验由后台线程顺带完成，几乎零额外成本。

`removeAbandoned` **不建议开启**：它会强制回收「借出超时不还」的连接，可能把正在执行事务的连接误杀，且会掩盖真正的连接泄漏 bug（应在代码层保证 `close()`，优先 `try-with-resources`）。排查泄漏更稳妥的做法是结合 `logAbandoned`（记录借出堆栈）与 [Monitoring](/docs/CS/Java/ConnectionPool/Druid/Monitoring.md) 的慢 SQL 监控定位，而非交给池去强摘。

`keepAlive` 与 `testWhileIdle` 互补：前者针对「长期空闲连接被中间件（L4/L7 网关、防火墙）静默回收」的场景，周期性发探活包维持连接新鲜；后者针对「借出前确认连接仍可用」。两者都依赖 `DestroyThread` 的后台扫描。

## Links

- [Druid](/docs/CS/Java/ConnectionPool/Druid.md)
- [Druid Architecture](/docs/CS/Java/ConnectionPool/Druid/Architecture.md)
- [Druid Monitoring](/docs/CS/Java/ConnectionPool/Druid/Monitoring.md)
- [Druid Security](/docs/CS/Java/ConnectionPool/Druid/Security.md)

## References

1. [Druid 配置属性 Wiki](https://github.com/alibaba/druid/wiki/%E9%85%8D%E7%BD%AE)
2. [druid-spring-boot-starter](https://github.com/alibaba/druid/tree/master/druid-spring-boot-starter)
