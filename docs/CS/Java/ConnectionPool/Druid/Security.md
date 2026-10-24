## Introduction

`WallFilter` 是 Druid「可管控」一面的代表，也是它区别于 HikariCP / DBCP 的关键能力：它借助 Druid 内置的 **SQL Parser** 把每条 SQL 解析成 AST 再做注入校验，而非简单正则黑名单。它与 [Architecture](/docs/CS/Java/ConnectionPool/Druid/Architecture.md) 里的 `StatFilter` 挂在同一条 `FilterChain` 上，统计维度见 [Monitoring](/docs/CS/Java/ConnectionPool/Druid/Monitoring.md)。总览见 [Druid](/docs/CS/Java/ConnectionPool/Druid.md)。

## SQL Parser

Druid 自带一套覆盖多种方言（MySQL、Oracle、PostgreSQL、SQL Server、H2 等）的 SQL Parser，能把任意 SQL 文本解析为结构化的 AST（`SQLStatement` → `SQLSelect` / `SQLDelete` / `SQLUpdate` / `SQLInsert` 等节点）。Parser 是 WallFilter、StatFilter（SQL 归一化/参数化）、以及 Druid 其它组件共用的基础设施——解析一次即可被多处消费。

## WallVisitor

`WallFilter` 在链上拦截语句执行，把待执行的 SQL 交给 `WallProvider` / `WallVisitor`：

1. 用 SQL Parser 解析出 AST；
2. `WallVisitor` 遍历 AST，按 `WallConfig` 逐项校验；
3. 命中危险规则则抛 `WallSQLException` 拒绝执行，并写入 Wall 维度的统计（可在 [Monitoring](/docs/CS/Java/ConnectionPool/Druid/Monitoring.md) 的「SQL 防火墙」页看到）。

因为是 AST 语义级校验，它能识别正则黑名单难以覆盖的绕过手法（见下）。

## WallConfig Key Items

| 配置项 | 默认倾向 | 作用 |
| --- | --- | --- |
| `multiStatementAllow` | false | 禁止一次执行多条语句（`a; drop table t`） |
| `strictSyntaxCheck` | true | 严格语法检查，拒绝明显畸形语句 |
| `noneBaseStatementAllow` | false | 禁止非基本语句（如 `USE`、`SET` 等） |
| `selectAllow` / `deleteAllow` / `updateAllow` / `insertAllow` | true | 是否允许对应 DML 类型 |
| `dropTableAllow` / `truncateAllow` | false | 禁止 `DROP TABLE` / `TRUNCATE` |
| `commentAllow` | false | 禁止 SQL 内注释（`/**/` 常用于绕过） |
| `selectIntoOutfileAllow` | false | 禁止 `SELECT ... INTO OUTFILE`（读文件外泄） |
| `conditionAndAlgorithmCheck` | false | 检查 `WHERE` 条件是否可绕过（防 `OR 1=1` 类） |

> 这些项可在 `spring.datasource.druid.filter.wall.config.*` 下声明式覆盖；生产上通常保持默认（禁 drop/truncate/多语句/注释），再按业务白名单放开必要 DML。

## Defense against Injection

基于 AST 语义，WallFilter 能拦截的典型攻击面：

- **多语句注入**：`'; DROP TABLE users; --`，被 `multiStatementAllow=false` 拦下
- **注释绕过**：`SELECT * FROM t WHERE id=1/**/OR/**/1=1`，被 `commentAllow=false` 拦下
- **UNION 拖库**：`UNION SELECT password FROM admin`，`conditionAndAlgorithmCheck` 结合白名单语义可识别
- **无 WHERE 的 DML**：`DELETE FROM t`（整表清空），可配 `deleteAllow` 结合条件检查拦截
- **`SELECT INTO OUTFILE`**：服务端写文件外泄，被 `selectIntoOutfileAllow=false` 拦下

需注意：WallFilter 是**纵深防御中的一层**，不能替代参数化查询（`PreparedStatement`）。它主要挡住「已绕过参数化的异常 SQL」与「运维/内部接口误用危险语句」。

## Config Example

```yaml
spring:
  datasource:
    druid:
      filters: stat,wall,slf4j
      filter:
        wall:
          enabled: true
          config:
            multi-statement-allow: false
            strict-syntax-check: true
            drop-table-allow: false
            truncate-allow: false
            comment-allow: false
            select-into-outfile-allow: false
            log-violation: true        # 命中规则时记录日志
            throw-exception: true       # 命中即抛异常拒绝执行
```

## Links

- [Druid](/docs/CS/Java/ConnectionPool/Druid.md)
- [Druid Architecture](/docs/CS/Java/ConnectionPool/Druid/Architecture.md)
- [Druid Monitoring](/docs/CS/Java/ConnectionPool/Druid/Monitoring.md)
- [Druid Configuration](/docs/CS/Java/ConnectionPool/Druid/Configuration.md)

## References

1. [Druid WallFilter Wiki](https://github.com/alibaba/druid/wiki/%E9%85%8D%E7%BD%AE_%E9%98%B2%E6%B3%A8%E5%85%A5%E6%94%BB%E5%87%BB)
2. [Druid SQL Parser](https://github.com/alibaba/druid/tree/master/core/src/main/java/com/alibaba/druid/sql)
