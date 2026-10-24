## Introduction

DBCP2 的参数直接挂在 `BasicDataSource`（`GenericObjectPoolConfig` 之上）上。本文给出完整参数表、DBCP 1.x→2.x 的改名映射、Spring Boot 装配，以及生命周期铁律。组件与借还见 [Architecture](/docs/CS/Java/ConnectionPool/DBCP/Architecture.md)。

## Parameter Table — Sizing

| Parameter     | Default      | Description                                                                                                                                                                                    |
| --------------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| initialSize   | 0            | The initial number of connections that are created when the pool is started. <br/>Since: 1.2                                                                                                       |
| maxTotal      | 8            | The maximum number of active connections that can be allocated from this pool at the same time, or negative for no limit.                                                                      |
| maxIdle       | 8            | The maximum number of connections that can remain idle in the pool, without extra ones being released, or negative for no limit.                                                               |
| minIdle       | 0            | The minimum number of connections that can remain idle in the pool, without extra ones being created, or zero to create none.                                                                  |
| maxWaitMillis | indefinitely | The maximum number of milliseconds that the pool will wait (when there are no available connections) for a connection to be returned before throwing an exception, or -1 to wait indefinitely. |

NOTE: If maxIdle is set too low on heavily loaded systems it is possible you will see connections being closed and almost immediately new connections being opened.
This is a result of the active threads momentarily closing connections faster than they are opening them, causing the number of idle connections to rise above maxIdle.
The best value for maxIdle for heavily loaded system will vary but the default is a good starting point.

## Parameter Table — Validation and Eviction

| Parameter                      | Default        | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| ------------------------------ | -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| validationQuery                |                | The SQL query that will be used to validate connections from this pool before returning them to the caller. If specified, this query**MUST** be an SQL SELECT statement that returns at least one row. If not specified, connections will be validation by calling the isValid() method.                                                                                                                                                                                                                                                                                                                                                 |
| validationQueryTimeout         | no timeout     | The timeout in seconds before connection validation queries fail. If set to a positive value, this value is passed to the driver via the`setQueryTimeout` method of the `Statement` used to execute the validation query.                                                                                                                                                                                                                                                                                                                                                                                                                |
| testOnCreate                   | false          | The indication of whether objects will be validated after creation. If the object fails to validate, the borrow attempt that triggered the object creation will fail.                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| testOnBorrow                   | true           | The indication of whether objects will be validated before being borrowed from the pool. If the object fails to validate, it will be dropped from the pool, and we will attempt to borrow another.                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| testOnReturn                   | false          | The indication of whether objects will be validated before being returned to the pool.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| testWhileIdle                  | false          | The indication of whether objects will be validated by the idle object evictor (if any). If an object fails to validate, it will be dropped from the pool.                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| timeBetweenEvictionRunsMillis  | -1             | The number of milliseconds to sleep between runs of the idle object evictor thread. When non-positive, no idle object evictor thread will be run.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| numTestsPerEvictionRun         | 3              | The number of objects to examine during each run of the idle object evictor thread (if any).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| minEvictableIdleTimeMillis     | 1000 * 60 * 30 | The minimum amount of time an object may sit idle in the pool before it is eligible for eviction by the idle object evictor (if any).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| softMinEvictableIdleTimeMillis | -1             | The minimum amount of time a connection may sit idle in the pool before it is eligible for eviction by the idle connection evictor, with the extra condition that at least "minIdle" connections remain in the pool. When minEvictableIdleTimeMillis is set to a positive value, minEvictableIdleTimeMillis is examined first by the idle connection evictor - i.e. when idle connections are visited by the evictor, idle time is first compared against minEvictableIdleTimeMillis (without considering the number of idle connections in the pool) and then against softMinEvictableIdleTimeMillis, including the minIdle constraint. |
| maxConnLifetimeMillis          | -1             | The maximum lifetime in milliseconds of a connection. After this time is exceeded the connection will fail the next activation, passivation or validation test. A value of zero or less means the connection has an infinite lifetime.                                                                                                                                                                                                                                                                                                                                                                                                   |
| logExpiredConnections          | true           | Flag to log a message indicating that a connection is being closed by the pool due to maxConnLifetimeMillis exceeded. Set this property to false to suppress expired connection logging that is turned on by default.                                                                                                                                                                                                                                                                                                                                                                                                                    |
| connectionInitSqls             | null           | A Collection of SQL statements that will be used to initialize physical connections when they are first created. These statements are executed only once - when the configured connection factory creates the connection.                                                                                                                                                                                                                                                                                                                                                                                                                |
| lifo                           | true           | True means that borrowObject returns the most recently used ("last in") connection in the pool (if there are idle connections available). False means that the pool behaves as a FIFO queue - connections are taken from the idle instance pool in the order that they are returned to the pool.                                                                                                                                                                                                                                                                                                                                         |

## DBCP 1.x to 2.x Rename Map

| DBCP 1.x | DBCP 2.x | 说明 |
| --- | --- | --- |
| `maxActive` | `maxTotal` | 最常见的静默失效：配了 maxActive 但池仍保持默认 8 |
| `maxWait` | `maxWaitMillis`（或 Duration 形式 `max-wait`） | 旧版单位也是 ms |
| `removeAbandoned` | `removeAbandonedOnBorrow` / `removeAbandonedOnMaintenance` | 拆成两个触发点 |
| `removeAbandonedTimeout` | `removeAbandonedTimeout`（秒，不变） | 单位仍是秒 |
| `logAbandoned` | `logAbandoned` | 不变 |
| `maxConnLifetimeMillis` | 无 1.x 对应 | 2.x 新增，连接绝对寿命 |
| `fastFailValidation` | 无 1.x 对应 | 2.x 新增，快速失败校验 |

> 任何配置改动后，建议经 JMX 读回 `MaxTotal` / `MaxWaitMillis` / `TimeBetweenEvictionRunsMillis` 的**生效值**，而非信任配置文件——拼写错误或遗留属性会被静默忽略。

## Spring Boot Integration

Spring Boot 默认装配 HikariCP，要用 DBCP2 需显式指定 `type` 并排除 HikariCP（或让其不在 classpath），专用参数挂在 `spring.datasource.dbcp2.*` 前缀下：

```yaml
spring:
  datasource:
    type: org.apache.commons.dbcp2.BasicDataSource
    url: jdbc:postgresql://orders-db:5432/orders
    username: app
    password: ${DB_PASSWORD}
    dbcp2:
      initial-size: 4
      max-total: 24
      max-idle: 24
      min-idle: 4
      max-wait-millis: 3000
      test-on-borrow: false
      test-while-idle: true
      validation-query-timeout: 2
      time-between-eviction-runs-millis: 30000
      num-tests-per-eviction-run: -1
      min-evictable-idle-time-millis: 120000
      max-conn-lifetime-millis: 1800000   # < DB wait_timeout
      remove-abandoned-on-maintenance: true
      remove-abandoned-timeout: 120
      log-abandoned: true
      jmx-name: org.apache.commons.dbcp2:name=ordersDS
```

> 注意 `spring.datasource.dbcp2.*` 是 Spring Boot 的宽松绑定，**kebab-case 属性名**会映射到 `BasicDataSource` 的 camelCase setter（如 `max-total` → `setMaxTotal`）。Spring Boot Common Application Properties 文档列出了全部支持项。

## Lifetime Rule

> `maxConnLifetimeMillis` 必须比数据库端 `wait_timeout`（MySQL）或等价连接超时**短至少 1 分钟**，否则池可能把一条已被 DB 静默关闭的连接借给应用，触发 `Communications link failure`（见 [DataSource](/docs/CS/Java/ConnectionPool/ConnectionPool.md) 的 `## Connection Issues`）。这与 [HikariCP](/docs/CS/Java/ConnectionPool/HiKariCP/Configuration.md) 的 `maxLifetime` 铁律同源。

## Links

- [DBCP](/docs/CS/Java/ConnectionPool/DBCP.md)
- [Architecture](/docs/CS/Java/ConnectionPool/DBCP/Architecture.md)
- [Monitoring](/docs/CS/Java/ConnectionPool/DBCP/Monitoring.md)
- [DataSource](/docs/CS/Java/ConnectionPool/ConnectionPool.md)

## References

1. [Apache Commons DBCP Configuration](https://commons.apache.org/proper/commons-dbcp/configuration.html)
2. [Spring Boot Common Application Properties](https://docs.spring.io/spring-boot/appendix/application-properties/index.html)
