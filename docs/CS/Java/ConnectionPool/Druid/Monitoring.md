## Introduction

监控是 Druid「为监控而生」这句话的直接落地。它和 [Architecture](/docs/CS/Java/ConnectionPool/Druid/Architecture.md) 里那条 `FilterChain` 是配套的：`StatFilter` 挂在链上静默采集，再通过 Web 控制台、编程接口、JMX 三种出口暴露。安全侧同类能力见 [Security](/docs/CS/Java/ConnectionPool/Druid/Security.md)，怎么把它拧进生产见 [Configuration](/docs/CS/Java/ConnectionPool/Druid/Configuration.md)。总览见 [Druid](/docs/CS/Java/ConnectionPool/Druid.md)。

## Stat Dimensions

`StatFilter` 在链上把数据 merge 进多张 `StatData` 表，按维度分开统计：

| 维度 | 采集内容 | 典型字段 |
| --- | --- | --- |
| SQL | 每条 SQL 模板的执行情况 | `ExecuteCount` / `ErrorCount` / `TotalTime` / `MaxTimespan` / `InTxnCount` / `FetchRowCount` / `UpdateCount` / `Histogram`（耗时分布） |
| URI | 每个 Web 入口的请求 | 请求数、耗时、关联 SQL 数 |
| Session | 每个 HTTP Session | 请求数、SQL 数 |
| Spring | 每个 Bean/方法调用 | 方法耗时、SQL 数 |
| Wall | 每条被 WallFilter 拦截/放行的 SQL | 拦截原因、命中规则（与 [Security](/docs/CS/Java/ConnectionPool/Druid/Security.md) 共用同一统计底座） |

SQL 维度是日常排查慢查询的主战场：`MaxTimespan` 抓单条最慢、`Histogram` 看耗时分布、`InTxnCount` 看事务内执行占比。

## Web Console

启用 `stat-view-servlet`（Spring Boot 下由 starter 的 `spring.datasource.druid.stat-view-servlet.enabled=true` 开启），暴露 `url-pattern: /druid/*` 的可视化页面，可看：

- **数据源**：连接数、活跃/空闲、创建/销毁计数、连接池水位曲线
- **SQL 监控**：按执行次数 / 耗时排序的语句、慢 SQL 列表
- **SQL 防火墙**：WallFilter 拦截记录
- **URI / Session / Spring 监控**：入口维度的 SQL 关联

控制台本身要加访问控制，否则等于把 DB 拓扑和 SQL 明文暴露给内网任意人：

- `login-username` / `login-password`：基础登录
- `allow` / `deny`：IP 白名单 / 黑名单（CIDR 或具体 IP，`deny` 优先）
- `reset-enable=false`：禁止通过控制台 `reset` 清零统计

## Web Stat Filter

`web-stat-filter`（`WebStatFilter`）从 Web 层切入：在 HTTP 请求前后记录 URI、Session，并把「这次请求执行了哪些 SQL」关联起来。需配置 `url-pattern`（通常 `/*`）、`exclusions`（排除 `*.js`、`*.css`、`/druid/*` 等资源）以避免污染统计。它是 URI / Session / Spring 三个维度的数据来源。

## Programmatic API

不想开网页时，可在代码里直接拉统计：

- `DruidDataSourceStatManager.getDataSourceStatDataList()`：返回进程内所有 `DruidDataSource` 的数据源级 `StatData`
- `DruidDataSource.getStatData()`：当前数据源的数据源级统计
- `DruidDataSource.getSqlStatDataList()` / `getWallStatData()`：SQL 维度 / Wall 维度明细

这些 API 返回的 `StatData` 是普通 POJO，可序列化后推到 Prometheus / 自研监控。这也是把 Druid 监控接进统一可观测平台的标准入口。

## JMX

`DruidDataSource` 注册了 `DruidDataSourceMBean`（`com.alibaba.druid:type=DruidDataSource` 等），通过 `jconsole` / `jvisualvm` 或运维采集 Agent 可看到连接数、活跃数、各类计数与 `resetStat()` 等操作。JMX 是「不引 Web 控制台也能看水位」的轻量出口。

## Spring Boot

引入 `druid-spring-boot-starter` 后，监控能力通过 `spring.datasource.druid.*` 声明式开启：

```yaml
spring:
  datasource:
    druid:
      # 开启 StatFilter
      filters: stat,wall,slf4j
      stat-view-servlet:
        enabled: true
        url-pattern: /druid/*
        login-username: admin
        login-password: *****
        reset-enable: false
      web-stat-filter:
        enabled: true
        url-pattern: /*
        exclusions: "*.js,*.css,/druid/*"
      filter:
        stat:
          enabled: true
          slow-sql-millis: 5000   # 慢 SQL 阈值
          log-slow-sql: true
```

## Links

- [Druid](/docs/CS/Java/ConnectionPool/Druid.md)
- [Druid Architecture](/docs/CS/Java/ConnectionPool/Druid/Architecture.md)
- [Druid Security](/docs/CS/Java/ConnectionPool/Druid/Security.md)
- [Druid Configuration](/docs/CS/Java/ConnectionPool/Druid/Configuration.md)

## References

1. [Druid 监控配置 Wiki](https://github.com/alibaba/druid/wiki/%E9%85%8D%E7%BD%AE_StatViewServlet%E9%85%8D%E7%BD%AE)
2. [druid-spring-boot-starter](https://github.com/alibaba/druid/tree/master/druid-spring-boot-starter)
