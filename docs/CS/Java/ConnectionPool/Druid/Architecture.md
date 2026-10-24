## Introduction

本篇是 Druid 连接池的**设计骨架**：它不像 HikariCP 把优化埋进无锁集合，而是用一条**可插拔的过滤器链（FilterChain）**把监控、安全、日志从池内核里剥离出来。理解这条链，才能理解 [Monitoring](/docs/CS/Java/ConnectionPool/Druid/Monitoring.md) 与 [Security](/docs/CS/Java/ConnectionPool/Druid/Security.md) 为什么「几乎不影响性能」、以及 [Configuration](/docs/CS/Java/ConnectionPool/Druid/Configuration.md) 里 `filters` 一项到底在挂什么。总览见 [Druid](/docs/CS/Java/ConnectionPool/Druid.md)，连接池通用契约见 [DataSource](/docs/CS/Java/ConnectionPool/ConnectionPool.md)。

## Filter Chain

Druid 把连接生命周期里的**每个关键动作**都抽象成对 `FilterChain` 的一次调用，链上每个 `Filter` 都能在动作前后插手：

- 获取连接：`dataSource_getConnection`
- 连接包装：`connection_getConnection`（用于事务嵌套）
- 语句创建：`connection_createStatement` / `connection_prepareStatement` / `connection_prepareCall`
- 语句执行：`statement_execute` / `statement_executeQuery` / `statement_executeUpdate` / `statement_executeBatch`
- 结果集：`resultSet_next` / `resultSet_getXXX`
- 连接关闭：`connection_close`（逻辑归还，非物理断开）
- 事务：`connection_commit` / `connection_rollback`

以「借连接」为例，调用顺序是：

```
DruidDataSource.getConnection()
  -> FilterChainImpl.dataSource_getConnection()
    -> 依次回调每个 Filter.dataSource_getConnection(filterChain, ...)
      -> 末位 Filter 调用 chain.next() 进入真正逻辑
        -> 创建 / 复用物理连接，返回 DruidPooledConnection 代理
```

`FilterChainImpl` 持有一个 `Filter[]` 与当前游标 `pos`，每回调一个 Filter 就 `pos++`，直到末位才执行真实动作。这意味着**新增 `StatFilter` / `WallFilter` 只是往数组里加一个元素，池内核的借还逻辑一行都不用改**——这正是「监控不影响性能、且可插拔」的结构性来源。

`filters` 配置项用逗号分隔的工厂名串起来，例如 `stat,wall,slf4j` 即同时挂上统计、防注入、日志三类过滤器。

## Core Classes

| 类 | 职责 |
| --- | --- |
| `DruidDataSource` | 池主体。持有物理连接数组 `connections[]`、各类计数器（`activeCount` / `poolingCount` / `createCount` / `destroyCount` / `errorCount` / `connectCount`），并驱动三个后台线程 |
| `DruidPooledConnection` | 代理 `Connection`。`close()` 触发逻辑归还；拦截 `createStatement` / `prepareStatement` 以便把语句纳入统计与链路 |
| `FilterChainImpl` | 过滤器链实现，维护 `Filter[]` 与游标，逐个回调后落到真实动作 |
| `DruidDataSourceStatManager` | 全局统计管理器，聚合进程内所有 `DruidDataSource` 的 `StatData`，供 Web 控制台 / JMX / 编程接口拉取 |

`DruidDataSource` 的后台维护线程（与 [DataSource](/docs/CS/Java/ConnectionPool/ConnectionPool.md) 提到的通用维护线程对应）：

- **CreateThread**：连接数不足 `minIdle` 或借出达上限时，异步补充物理连接
- **DestroyThread**：周期性驱逐空闲过久、寿命到期、或泄漏的连接（对应 `timeBetweenEvictionRunsMillis`）
- **LogStatsThread**：按 `timeBetweenLogStatsMillis` 周期输出统计快照

## Built-in Filters

| Filter | 在链上的作用 | 详见 |
| --- | --- | --- |
| `StatFilter` | 在 statement / resultSet 各级回调里采集耗时、行数、慢 SQL，merge 进 `StatData` | [Monitoring](/docs/CS/Java/ConnectionPool/Druid/Monitoring.md) |
| `WallFilter` | 在语句执行前用 SQL Parser 解析成 AST，做注入校验并拦截危险语句 | [Security](/docs/CS/Java/ConnectionPool/Druid/Security.md) |
| `LogFilter`（`slf4j` / `log4j` / `commons-log` 适配） | 记录 SQL 与执行耗时，慢 SQL 单独告警 |
| `EncodingConvertFilter` | 结果集字符集转换 |

这四类过滤器都实现同一套 `Filter` 接口（即上面那张回调方法表），因此可任意组合、顺序可调。

## Fair Lock

配置了 `maxWait`（获取连接的最大等待时间）后，连接争用激烈时 Druid 用一把 `ReentrantLock` 保护「从空闲队列取连接」这段临界区。

- **unfair 模式**（0.2.8 起默认）：`ReentrantLock.tryLock` 不保证等待顺序，极端争用下个别线程可能一直抢不到，直到 `maxWait` 超时抛异常——表现为「明明有连接释放，某些线程却拿不到」。
- **fair 模式**：锁按请求顺序排队（`AQS` 队列），杜绝饿死，但上下文切换与排队开销上升，吞吐下降。
- 触发转换：若 `DruidDataSource` 尚未初始化，把 `maxWait` 设为 `> 0` 会自动切到 fair；也可手工 `setUseUnfairLock(true)` 强制不公平。

> 公平锁是「连接不够用」的表象放大器，不是根因。真正要做的仍是把 `maxActive` 配到 DB 可承受并发、并排查连接泄漏（见 [Configuration](/docs/CS/Java/ConnectionPool/Druid/Configuration.md) 的 Validation and Leak）。

## Links

- [Druid](/docs/CS/Java/ConnectionPool/Druid.md)
- [Druid Monitoring](/docs/CS/Java/ConnectionPool/Druid/Monitoring.md)
- [Druid Security](/docs/CS/Java/ConnectionPool/Druid/Security.md)
- [Druid Configuration](/docs/CS/Java/ConnectionPool/Druid/Configuration.md)

## References

1. [Alibaba Druid GitHub](https://github.com/alibaba/druid)
2. [Druid Filter 扩展机制 Wiki](https://github.com/alibaba/druid/wiki/%E8%87%AA%E5%AE%9A%E4%B9%89%E8%BF%87%E6%BB%A4%E5%99%A8Filter)
