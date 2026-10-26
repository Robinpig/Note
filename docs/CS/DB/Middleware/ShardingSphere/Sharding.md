## Introduction

分片是 ShardingSphere 的主轴功能：把单库单表的数据按规则分散到多个数据节点，让应用像用「一个库」一样用「一组库」。本页覆盖分片的全部构件——表类型、数据节点、算法族、策略、行表达式、分布式主键与分片审计。分片本身的机制与再均衡算法见 [Shard](/docs/CS/DB/Concept/Shard.md)，本页只讲 ShardingSphere 的实现口径。

## Vertical and Horizontal Sharding

- **垂直分片**：按业务把表分到不同数据库（用户库、订单库），让专业库干专业事。它缓解单节点压力但不解决单表过大，表量继续涨仍要水平分片。
- **水平分片**：按某个字段的规则把同一张表的数据分散到多个库/表，每片只含一部分数据。理论上突破了单机数据处理量上限，是分库分表的标准解。

官方选型逻辑：垂直分片「一次架构调整、跟不上互联网业务变化」，水平分片才真正消除单节点瓶颈；两者常叠加使用。

## Table Types

分片语境下「表」有五种，混淆它们是配置错误的第一来源：

| 类型 | 含义 | 配置 |
| :--- | :--- | :--- |
| 逻辑表（logic table） | SQL 里写的表名，水平分片同构表的逻辑标识 | `tables` 下的键 |
| 真实表（actual table） | 物理存在的分片表，如 `t_order_0` ~ `t_order_9` | `actualDataNodes` |
| 绑定表（binding table） | 分片规则一致的表组，join 时按主表分片条件一次算完 | `bindingTables` |
| 广播表（broadcast table） | 每个数据源都有一份相同结构与数据的表（字典表） | `!BROADCAST` |
| 单表（single table） | 只存在于一个数据源、不参与分片的表 | `!SINGLE` |

- **绑定表的价值**：`t_order` 与 `t_order_item` 都按 `order_id` 分片且用 `order_id` join，未绑定前一条 `IN (10,11)` 的路由结果是 2×2 的笛卡尔积；绑定后路由出 2 条，`t_order` 作为主表决定全部计算。**命名硬规则：绑定关系靠剥离真实表名尾部的数字后缀推导，数字后缀只能留给分片后缀（`_0`、`_1`）**。
- **单表不会全部自动加载**：只有出现在 encrypt/mask 等规则配置里的单表、以及用户经 ShardingSphere 执行 DDL 创建的单表会被自动加载；其余单表要用 `!SINGLE` 显式管理，否则路由不到。`tables` 支持通配：`ds_0.*`（加载某库全部单表）、`*.*`（全部，MySQL 两级名）、`*.*.*`（PostgreSQL 三级名）；`defaultDataSource` 决定 `CREATE TABLE` 建单表时落到哪个库，默认 null = 随机单播路由。

## Data Nodes

数据节点 = 数据源名 + 真实表名，是分片的最小单位（`ds_0.t_order_0`）。逻辑表到真实表的映射有两种分布：

- **均匀分布**：每个数据源内的表集合相同（`db0.t_order0, db0.t_order1, db1.t_order0, db1.t_order1`）。
- **自定义分布**：按模式分布，每个库的表数可以不同（`db1` 挂 `t_order2`~`t_order4`）。

均匀分布用行表达式一行搞定；自定义分布显式枚举。

## Sharding Keys and Full Routing

分片键是路由的唯一输入。算法支持 `=`、`>=`、`<=`、`>`、`<`、`BETWEEN`、`IN` 的比较语义；**SQL 里不带分片键时执行全路由**——所有节点全扫一遍再归并。这是分片中间件性能问题里最常见的单点，配合分片审计规则可以在开发期拦截。

## Sharding Algorithms

5.5 的内置算法按「自动 / 标准 / 复杂 / Hint / 自定义」分组，全部经 `shardingAlgorithms` 配置：

### Auto Sharding（自动分片）

配在 `autoTables` 下，**数据节点的物理分布由 ShardingSphere 自动管理**，用户不写 `actualDataNodes`：

| type | 关键属性 | 语义 |
| :--- | :--- | :--- |
| `MOD` | `sharding-count`，`start-offset`/`stop-offset`，`zero-padding` | 取模分片，可选截取偏移段、后缀补零 |
| `HASH_MOD` | `sharding-count`，`normalize-numeric-int-range` | 哈希取模；后者把 Long/BigInteger 归一到整数语义，保证跨数值类型路由一致 |
| `VOLUME_RANGE` | `range-lower`/`range-upper`/`sharding-volume` | 按数据量切范围段 |
| `BOUNDARY_RANGE` | `sharding-ranges` | 按自定义边界切范围段 |
| `AUTO_INTERVAL` | `datetime-lower`/`datetime-upper`/`sharding-seconds` | 按时间自动分片，单片最大秒数，秒级以上精度自动截断 |

### Standard / Complex / Hint

| type | 归属 | 关键属性 |
| :--- | :--- | :--- |
| `INLINE` | 标准（单键） | `algorithm-expression`，`allow-range-query-with-inline-sharding` |
| `INTERVAL` | 标准（单键，时间） | `datetime-pattern`、`datetime-lower`/`datetime-upper`、`sharding-suffix-pattern`、`datetime-interval-amount`/`datetime-interval-unit` |
| `COMPLEX_INLINE` | 复杂（多键） | `sharding-columns`、`algorithm-expression` |
| `HINT_INLINE` | Hint | `algorithm-expression`，值用 `${value}` 取注入的分片值 |
| `CLASS_BASED` | 自定义 | `strategy`（STANDARD/COMPLEX/HINT）、`algorithmClassName` 全限定类名，属性经 `java.util.Properties` 的 `props` 传入 |

两个容易踩的点：

- `INTERVAL` **主动忽略时区信息**：`datetime-lower`/`datetime-upper` 与分片键都带时区也不做转换；分片键是 `Instant`/`Date` 时按系统时区格式化成字符串再进算法。
- `allow-range-query-with-inline-sharding` 默认 false：范围查询（`BETWEEN`/`>`）默认**放弃分片策略走全路由**，打开它意味着范围查询仍按 inline 算法逐值算——两者都要权衡。

## Sharding Strategies

策略 = 分片键 + 算法，按场景选型：

| 策略 | 适用 | 说明 |
| :--- | :--- | :--- |
| `standard` | 单分片列 | 一个 shardingColumn + 一个算法，`=`/`IN` |
| `complex` | 多分片列 | 多个 shardingColumns + 一个算法，多键组合逻辑自己实现 |
| `hint` | 分片值来自外部 | 不依赖 SQL 条件，由 Hint 注入 |
| `none` | 不分片 | 显式声明，避免误继承默认策略 |

配合 `defaultDatabaseStrategy`/`defaultTableStrategy`/`defaultShardingColumn` 做缺省，未配策略的表按默认策略走。

## Row Value Expressions

行表达式用 Groovy 语法做配置简化，同时是 `actualDataNodes` 与 inline 算法的共同语法：

- 标识：`${ expression }` 或 `$->{ expression }`；多个子表达式的结果做**笛卡尔组合**——`${['online', 'offline']}_table${1..3}` 展开成 `online_table1..3, offline_table1..3`。
- 区间 `${begin..end}`、枚举 `${[unit1, unit2]}`；未指定类型名时默认走 `GROOVY` 实现的 `InlineExpressionParser` SPI，也可显式写 `<GROOVY>...`。
- 例：`actualDataNodes: ds_${0..1}.t_order_${0..1}` = 2 库 × 2 表；`algorithm-expression: ds_${user_id % 2}`。

## Distributed Primary Key

分片后自增键跨真实表互不感知、必然重复；靠错开初始值和步长能绕，但把运维规则引进来了，不完整也不扩展。ShardingSphere 内置两种分布式主键生成器：

- `SNOWFLAKE`：雪花算法，集群模式下 worker-id 可由注册中心自动分配（不必手工规划机器位）。
- `UUID`：无序字符串，省心但索引友好性差。

经 `keyGenerateStrategies` 绑定到逻辑表与列（`keyGenerateType: column` + `keyGenerateColumn`），INSERT 缺主键时自动补值。

## Sharding Audit

`auditStrategy` + `auditors` 提供开发期的分片约束检查，内置 `DML_SHARDING_CONDITIONS` 审计器：DML 必须带分片条件，堵住全路由 SQL；`allowHintDisable` 允许用 Hint 临时豁免。这是把「无分片键全路由」拦在测试环境而不是生产的第一道闸。

## Facts Worth Pinning Down

1. **绑定表靠剥离数字后缀推导关系**——真实表名尾部的数字必须只用作分片后缀，`t_order_2024` 这种命名会直接破坏绑定关系。
2. **单表不自动加载**：除规则内引用和经 ShardingSphere 建的 DDL 外，都要 `!SINGLE` 显式登记，否则 SQL 路由不到。
3. **范围查询默认全路由**：inline 算法的 `allow-range-query-with-inline-sharding` 默认关闭，`BETWEEN` 查询会退化成全片扫描。
4. **自动分片算法下用户不管理 `actualDataNodes`**——扩容时的节点变迁由框架接管，这是 autoTables 与手写 `actualDataNodes` 的本质区别。
5. **`AUTO_INTERVAL` 只保留到秒**：秒以下精度自动截断，时间分片键带毫秒时会静默归片。

## Links

- [SQL Pipeline](/docs/CS/DB/Middleware/ShardingSphere/SQL_Pipeline.md)
- [Architecture](/docs/CS/DB/Middleware/ShardingSphere/Architecture.md)
- [Distributed Transaction](/docs/CS/DB/Middleware/ShardingSphere/Distributed_Transaction.md)

## References

1. [Core Concept :: ShardingSphere](https://shardingsphere.apache.org/document/current/en/features/sharding/concept/)
2. [Sharding Algorithm (built-in list)](https://shardingsphere.apache.org/document/current/en/user-manual/common-config/builtin-algorithm/sharding)
3. [Sharding YAML Configuration](https://shardingsphere.apache.org/document/current/en/user-manual/shardingsphere-jdbc/yaml-config/rules/sharding/)
4. [Single Table YAML Configuration](https://shardingsphere.apache.org/document/current/en/user-manual/shardingsphere-jdbc/yaml-config/rules/single/)
5. [Developer Guide: Inline Expression Parser](https://shardingsphere.apache.org/document/current/en/dev-manual/sharding/)
6. [Data Sharding (core feature)](https://shardingsphere.apache.org/document/current/en/features/sharding/)
