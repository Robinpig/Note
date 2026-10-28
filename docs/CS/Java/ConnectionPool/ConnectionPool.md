## Introduction

Connection pooling is a well-known data access pattern.
Its main purpose is to reduce the overhead of establishing a database connection and executing read/write operations.
**At the most basic level, a connection pool is a database connection cache implementation** that can be configured to suit specific requirements.

建立一条物理连接的成本很高：至少要经历 TCP 三次握手、数据库服务端鉴权、权限/会话上下文初始化，部分驱动还会做 SSL 协商。
若每个 SQL 都现建现断，这套开销会直接吃掉吞吐。连接池把**已建立的物理连接**缓存起来，应用通过 `getConnection()` 借出、用完后 `close()`（逻辑归还而非物理断开），由池负责复用、校验与回收。

连接池的契约是 `javax.sql.DataSource`：应用只面向 `DataSource` 编程、拿到的 `Connection` 往往是**代理**，关闭即归还。
这一层与 [JDBC](/docs/CS/Java/JDK/Basic/JDBC.md) 的关系见下文 `## Integration`。

## Connection Lifecycle

一次借还的典型流程：

```sequence
Title: 一次借还的典型流程

participant App
participant Pool
participant Phys as PhysicalConn

App->>Pool: getConnection()
alt 有空闲且校验通过
    Pool-->>App: 代理 Connection（复用）
else 无空闲且未达上限
    Pool->>Phys: 新建物理连接
    Pool-->>App: 代理 Connection
else 无空闲且达上限
    App->>Pool: 阻塞等待 connectionTimeout
    Pool-->>App: 超时抛 SQLException
end
App->>Phys: 执行 SQL
App->>Pool: connection.close()
Pool->>Pool: 重置脏状态 / 校验
Pool-->>Phys: 归还空闲队列 或 超时驱逐
```

关键点：

- **`close()` 是归还，不是断开**。代理 `Connection` 拦截 `close()`，把底层物理连接放回空闲队列；只有被驱逐或池关闭时才真正 `close()`。
- **借出/归还都会触发校验**（取决于配置），剔除已被数据库侧关闭的连接。
- **后台维护线程**周期性驱逐空闲过久、或寿命到期的连接；HikariCP 叫 `HouseKeeper`，Druid 叫 `DestroyThread`，DBCP2 叫 `Evictor`。

## Core Parameters

连接池的可调参数大同小异，下面按语义归类（具体属性名因实现而异，见 `## Parameter Mapping`）。

| 维度 | 语义 | 调优要点 |
| --- | --- | --- |
| 规模上限 | 池能同时持有的最大连接数 | 等于（或略大于）数据库可接受并发；过大反而争抢 DB 资源 |
| 最小空闲 | 池长期保有的空闲连接下限 | `minIdle == maxPoolSize` 即固定大小池，适合稳定负载 |
| 借出超时 `connectionTimeout` | 无空闲时最多等待多久 | 避免线程无限阻塞；超时即失败快速降级 |
| 空闲超时 `idleTimeout` | 空闲连接存活上限 | 低于 DB 的 `wait_timeout`，否则拿到已被服务端关掉的死连接 |
| 寿命上限 `maxLifetime` | 连接绝对寿命 | 必须比 DB 侧超时（如 MySQL `wait_timeout`）短 1 分钟以上 |
| 保活 `keepaliveTime` | 周期性发轻量探活包 | 维持空闲连接不被中间网络设备回收 |
| 校验 `validationQuery` / `isValid()` | 借出/归还时确认连接可用 | 优先 `Connection.isValid()`（JDBC4），避免额外 SQL 开销 |
| 泄漏检测 `leakDetectionThreshold` | 借出后超过阈值未归还即告警 | 定位未正确 `close()` 的连接泄漏 |

> **pool-locking**：单个线程/事务一次性借走大量连接时，会触发「池锁定」——本质是**应用层用法问题**。加大池只能缓解表象；根本做法是审查代码（例如把长事务拆小、及时归还）。

## Implementations Map

Java 生态的连接池实现沿两条主线分化：**极致性能**与**可观测/可管控**。下面把主流实现串起来看。

**HikariCP** 是当代事实标准的「高性能」代表。它通过 `ConcurrentBag` 无锁集合、`FastList` 替换 `ArrayList`、`invokevirtual → invokestatic` 字节码级优化，把单次借还开销压到极低；Spring Boot 2.0 起默认内置它。详见 [HikariCP](/docs/CS/Java/ConnectionPool/HiKariCP.md)。

**Druid** 由阿里开源，定位是「为监控而生的连接池」——除池化外，还内置 SQL Parser、`StatFilter` 监控、`WallFilter` 防 SQL 注入、Web 监控台。性能略逊于 HikariCP，但运维可观测性最强，是国内金融/中后台项目常见选择。详见 [Druid](/docs/CS/Java/ConnectionPool/Druid.md)。

**Apache Commons DBCP2** 是历史最悠久的池化组件之一，基于 Apache Commons Pool2 实现，接口稳定、文档完备，常作为「无特殊诉求时的稳妥默认」。注意 1.x 与 2.x 包名不同（`org.apache.commons.dbcp` → `org.apache.commons.dbcp2`）。详见 [DBCP](/docs/CS/Java/ConnectionPool/DBCP.md)。

其余可选项多在「legacy」区间：**Tomcat JDBC Pool** 随 Tomcat 提供、轻量；**c3p0 / BoneCP** 已基本停止演进（BoneCP 作者本人推荐直接换 HikariCP）；**MyBatis `PooledDataSource`** 是一个简单同步池，在 MyBatis 不接第三方池时兜底（见 [MyBatis DataSource](/docs/CS/Framework/MyBatis/DataSource.md)）。选型的本质是「要性能还是要监控」的取舍。

| 实现 | 维护方 | 最新版本 | 定位 | 监控 | 防注入 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| HikariCP | brettwooldridge | 7.1.0（Java 11+） | 极致性能 | Micrometer/JMX 指标 | 无内建 | Spring Boot 默认 |
| Druid | 阿里巴巴 | 1.2.28（Java 8+） | 监控 + 管控 | Web 控制台 + StatFilter | WallFilter | 内置 SQL Parser |
| DBCP2 | Apache | 2.14.0（Java 8+） | 通用稳健 | JMX | 无内建 | 基于 Commons Pool2 |
| Tomcat JDBC Pool | Apache Tomcat | 随 Tomcat 发布 | 轻量内嵌 | JMX | 无内建 | 随容器可用 |
| c3p0 / BoneCP | 社区 | 停滞 | legacy | 弱 | 无内建 | 不建议新项目使用 |
| MyBatis PooledDataSource | MyBatis | 随 MyBatis 发布 | 简单兜底 | 无 | 无内建 | 仅 MyBatis 内部 |

## Parameter Mapping

同一语义在不同池里属性名不同，迁移时最容易踩坑，对照如下：

| 语义 | HikariCP | Druid | DBCP2 |
| --- | --- | --- | --- |
| JDBC URL | `jdbcUrl` | `url` | `url` |
| 用户名 | `username` | `username` | `username` |
| 最大连接数 | `maximumPoolSize` | `maxActive` | `maxTotal` |
| 最小空闲 | `minimumIdle` | `minIdle` | `minIdle` |
| 初始连接数 | —（懒建） | `initialSize` | `initialSize` |
| 借出超时 | `connectionTimeout` | `maxWait` | `maxWaitMillis` |
| 空闲超时 | `idleTimeout` | `minEvictableIdleTimeMillis` | `minEvictableIdleTimeMillis` |
| 寿命上限 | `maxLifetime` | `phyTimeoutMillis`（或 `maxEvictableIdleTimeMillis`） | `maxConnLifetimeMillis` |
| 保活周期 | `keepaliveTime` | `keepAlive` + `timeBetweenEvictionRunsMillis` | — |
| 校验 SQL | `connectionTestQuery` | `validationQuery` | `validationQuery` |
| 借出校验 | 默认 `isValid()` | `testOnBorrow` | `testOnBorrow` |
| 空闲校验 | — | `testWhileIdle` | `testWhileIdle` |
| 泄漏阈值 | `leakDetectionThreshold` | `removeAbandoned` | `removeAbandonedOnBorrow` |

> 通用铁律：**`maxLifetime` / `idleTimeout` 必须比数据库侧超时（如 MySQL `wait_timeout`，默认 28800s）短**；否则池会借出已被服务端静默关闭的连接，报 `Communications link failure`。

## Integration

连接池不是孤立组件，它嵌在一条更长的链里：

- **JDBC 契约**：池实现 `javax.sql.DataSource`，应用经 `getConnection()` 取得代理 `Connection`；`PooledConnection` 则用于 `javax.sql` 的连接池扩展。基础见 [JDBC](/docs/CS/Java/JDK/Basic/JDBC.md)。
- **Spring Boot**：`spring-boot-starter-jdbc` / `data-jpa` 默认带入 HikariCP，配置前缀 `spring.datasource.hikari.*`；换 Druid 需引入 `druid-spring-boot-starter` 并指定 `type`。
- **MyBatis**：自身带 `PooledDataSource`，但生产上通常把 HikariCP/Druid 注入为 `DataSource` 后交给 MyBatis（见 [MyBatis DataSource](/docs/CS/Framework/MyBatis/DataSource.md)）。
- **JNDI**：在 Java EE / Jakarta EE 容器里，`DataSource` 由服务器声明、经 JNDI 暴露，应用只按名查找（详见 [JNDI](/docs/CS/Java/JDK/Basic/JNDI.md)）。
- **分布式事务**：需要 XA 时换用 `XADataSource` / `XAConnection`，接入 JTA 两阶段提交（与 [Spring Transaction](/docs/CS/Framework/Spring/Transaction.md) 协同）。

## Connection Issues

> [Connect Java to a MySQL database Stack Overflow](https://stackoverflow.com/questions/2839321/connect-java-to-a-mysql-database/2840358#2840358)
>
> If you get a `SQLException: Connection refused` or `Connection timed out` or a MySQL specific `CommunicationsException: Communications link failure`, then it means that the DB isn't reachable at all.
>
> This can have one or more of the following causes:
>
> 1. IP address or hostname in JDBC URL is wrong.
> 2. Hostname in JDBC URL is not recognized by local DNS server.
> 3. Port number is missing or wrong in JDBC URL.
> 4. DB server is down.
> 5. DB server doesn't accept TCP/IP connections.
> 6. DB server has run out of connections.
> 7. Something in between Java and DB is blocking connections, e.g. a firewall or proxy.
>
> To solve the one or the other, follow the following advices:
>
> 1. Verify and test them with `ping`.
> 2. Refresh DNS or use IP address in JDBC URL instead.
> 3. Verify it based on `my.cnf` of MySQL DB.
> 4. Start the DB.
> 5. Verify if `mysqld` is started without the `--skip-networking` option.
> 6. Restart the DB and fix your code accordingly that it closes connections in `finally`.
> 7. Disable firewall and/or configure firewall/proxy to allow/forward the port.

`Communications link failure` 在连接池场景下，多半是**池子借出了「服务端已关」的死连接**——根因几乎都是 `maxLifetime`/`idleTimeout` 配得比 DB 超时还长。把池寿命压短一截即可，而非去改数据库。

## Links

- [JDBC](/docs/CS/Java/JDK/Basic/JDBC.md)
- [MyBatis DataSource](/docs/CS/Framework/MyBatis/DataSource.md)
- [Spring Transaction](/docs/CS/Framework/Spring/Transaction.md)

## References

1. [HikariCP GitHub](https://github.com/brettwooldridge/HikariCP)
2. [HikariCP FAQ](https://github.com/brettwooldridge/HikariCP/wiki/FAQ)
3. [Alibaba Druid GitHub](https://github.com/alibaba/druid)
4. [Apache Commons DBCP 2.x Changes](https://commons.apache.org/proper/commons-dbcp/changes.html)
