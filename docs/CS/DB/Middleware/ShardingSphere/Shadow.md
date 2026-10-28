## Introduction

影子库（shadow database）解决**全链路压测的数据隔离**：压测流量打在生产环境，但读写被自动导向影子库，测试数据不污染生产数据。它是 ShardingSphere 里少有的「纯流量治理」功能——不碰数据正确性，只改路由目标。本页讲它的配置形态与两种内置影子算法。

## Background

微服务架构下，单服务压测反映不了真实场景；在测试环境重建一套与生产等价的压测环境，成本高到不现实。于是正确姿势是**在生产环境压测**——但前提是数据库层做好数据隔离：压测产生的数据必须进影子库，不能落生产表。

这要求应用在执行业务 SQL 前先识别压测流量（压测标），ShardingSphere 的影子算法就是「识别 + 改道路由」这一跳。

## Configuration

```yaml
rules:
- !SHADOW
  dataSources:
    shadowDataSource:
      productionDataSourceName: ds
      shadowDataSourceName: shadow_ds
  tables:
    t_order:
      dataSourceNames:
        - shadowDataSource
      shadowAlgorithmNames:
        - user_id_insert_match_algorithm
        - sql_hint_algorithm
  defaultShadowAlgorithmName: user_id_insert_match_algorithm
  shadowAlgorithms:
    user_id_insert_match_algorithm:
      type: REGEX_MATCH
      props:
        operation: insert
        column: user_id
        regex: "[1]"
    sql_hint_algorithm:
      type: SQL_HINT
```

结构分四层：影子数据源对（生产/影子一一对应）、影子表（挂哪些影子数据源、用哪些算法）、默认算法、算法定义。

## Shadow Algorithms

内置两种影子算法：

| type | 判定依据 | 关键属性 |
| :--- | :--- | :--- |
| `REGEX_MATCH` | 列值正则匹配 | `operation`（如 insert）、`column`、`regex` |
| `SQL_HINT` | SQL Hint 标记 | 无属性，靠提示注入识别 |

- `REGEX_MATCH` 按「操作类型 + 列 + 正则」判定：例如 insert 且 `user_id` 匹配 `[1]` 的流量判为压测流量。适合压测标落在数据行里的场景。
- `SQL_HINT` 靠 SQL 注释/提示携带的标识别，适合全链路透传压测标（HTTP header → 服务 → SQL）的场景。
- 一张表可以同时挂多个算法，任一命中即走影子路由；`defaultShadowAlgorithmName` 兜底未显式挂算法的表。

## Working Model

1. 压测流量经影子算法判定（列值或 Hint）；
2. 命中则 SQL 路由到影子数据源而非生产数据源；
3. 未命中的正常流量行为不变。

对应用的要求只是**把压测标传下来**（数据行里带标或 SQL 带 Hint），路由与隔离由中间件完成——这是它相对「应用自己判断写哪张表」的核心价值。

## Boundaries

- 影子库是**结构相同的另一套库**：压测前要在影子库准备等价 schema 与基础数据，ShardingSphere 只做路由不做数据准备。
- 影子路由与分片、读写分离是不同维度的规则，可组合使用；组合时先分片/分离定位到逻辑节点，影子算法再决定落生产还是影子。
- 它治理的是「写不污染」，压测读到的生产数据量与生产一致——这也是生产压测的价值所在。

## Facts Worth Pinning Down

1. **两种内置算法：`REGEX_MATCH`（列值正则）与 `SQL_HINT`（提示标记）**，没有第三种；列值场景选前者、链路透传场景选后者。
2. **影子库结构与数据要自己准备**：中间件不克隆生产库。
3. **影子判定是「命中才改道」**：没带标的流量永远走生产库，标传丢了 = 压测数据落生产，这是最常见的实施事故。

## Links

- [SQL Pipeline](/docs/CS/DB/Middleware/ShardingSphere/SQL_Pipeline.md)
- [Readwrite Splitting](/docs/CS/DB/Middleware/ShardingSphere/Readwrite_Splitting.md)
- [Sharding](/docs/CS/DB/Middleware/ShardingSphere/Sharding.md)
- [Operations](/docs/CS/DB/Middleware/ShardingSphere/Operations.md)

## References

1. [Shadow Database :: ShardingSphere](https://shardingsphere.apache.org/document/current/en/features/shadow/)
2. [Shadow DB YAML Configuration](https://shardingsphere.apache.org/document/current/en/user-manual/shardingsphere-jdbc/yaml-config/rules/shadow/)
