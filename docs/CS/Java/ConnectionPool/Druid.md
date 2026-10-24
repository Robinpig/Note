## Introduction

[Druid](https://github.com/alibaba/druid) 是一个 JDBC 组件库，包含数据库连接池、SQL Parser 等组件。
Druid 连接池**为监控而生**，内置强大的监控功能，且监控特性基本不影响性能；同时能防 SQL 注入，内置 Logging 诊断异常应用行为。

Version baseline: 最新稳定版 **1.2.28**（2026-03），要求 **Java 8+**；`druid-spring-boot-starter` 提供 Spring Boot 自动装配。与追求极速的 [HikariCP](/docs/CS/Java/ConnectionPool/HiKariCP.md) 不同，Druid 的卖点是**可观测 + 可管控**；通用稳健型见 [DBCP](/docs/CS/Java/ConnectionPool/DBCP.md)，总览见 [DataSource](/docs/CS/Java/ConnectionPool/ConnectionPool.md)。

## Map of This Section

Druid 的能力不是写在池内核里的一坨逻辑，而是沿一条**「过滤器链」**长出来的——理解这一点，其余各篇才站得住：

- **[Architecture](/docs/CS/Java/ConnectionPool/Druid/Architecture.md)** 是根基。Druid 把「建立连接、借出、归还、执行 SQL」这些关键动作都穿过一条可插拔的 `FilterChain`，监控、安全、日志都是挂在链上的过滤器，而不是池内核的分支判断。这一设计决定了为什么监控「基本不影响性能」，也决定了 Fair Lock 这类并发问题出现在链入口的锁上。读完架构，才知道 Stat/Wall/Log 这些 Filter 各自处在链上的什么位置。
- **[Monitoring](/docs/CS/Java/ConnectionPool/Druid/Monitoring.md)** 是「为监控而生」这句话的直接落地。它在架构之上展开：`StatFilter` 在链上采集 SQL/URI/Spring 等多维统计，再通过 Web 控制台、编程接口、JMX 三种出口暴露。若你关心「我的慢 SQL 在哪、连接为什么被借光」，看这一篇。
- **[Security](/docs/CS/Java/ConnectionPool/Druid/Security.md)** 是监控之外的第二卖点。`WallFilter` 同样挂在链上，借助 Druid 内置的 SQL Parser 把每条 SQL 解析成 AST 再做注入校验，与 `StatFilter` 共享同一条链。它和监控是并列的两条过滤能力。
- **[Configuration](/docs/CS/Java/ConnectionPool/Druid/Configuration.md)** 把以上全部能力收口成可运维的配置：参数语义映射、Spring Boot starter 的声明式开启、以及「何时开 `testWhileIdle`、为何不建议 `removeAbandoned`」这类生产决策。架构与监控/安全讲「能做什么」，配置讲「怎么开、怎么调」。

一句话：架构是骨架，监控与安全是长在骨架上的两种能力，配置是把它们拧进生产的旋钮。

## Links

- [DataSource](/docs/CS/Java/ConnectionPool/ConnectionPool.md)
- [HiKariCP](/docs/CS/Java/ConnectionPool/HiKariCP.md)
- [Druid Architecture](/docs/CS/Java/ConnectionPool/Druid/Architecture.md)
- [Druid Monitoring](/docs/CS/Java/ConnectionPool/Druid/Monitoring.md)
- [Druid Configuration](/docs/CS/Java/ConnectionPool/Druid/Configuration.md)
- [Druid Security](/docs/CS/Java/ConnectionPool/Druid/Security.md)

## References

1. [Alibaba Druid GitHub](https://github.com/alibaba/druid)
2. [Druid 常见问题 Wiki](https://github.com/alibaba/druid/wiki/%E5%B8%B8%E8%A7%81%E9%97%AE%E9%A2%98)
3. [Druid FAQ](https://github.com/alibaba/druid/wiki/FAQ)
4. [druid-spring-boot-starter](https://github.com/alibaba/druid/tree/master/druid-spring-boot-starter)
