## Introduction

一条 SQL 在 ShardingSphere 内部要走完五个阶段：**解析（parse）→ 路由（route）→ 改写（rewrite）→ 执行（execute）→ 归并（merge）**。分库分表中间件的全部魔法与全部坑都压在这五步里；联邦查询则是「改写不动了」时的兜底出口。本页按这五步展开，并交代 SQL Federation 的真实状态。

## Pipeline Overview

```
SQL 文本
  │
  ▼
SQL Parser ── ANTLR 解析为 AST，按方言（MySQL / PostgreSQL / Oracle / SQLServer / SQL92）分支
  │
  ▼
SQL Router ── 由分片策略算出该去哪些真实数据节点；无分片键则全路由
  │
  ▼
SQL Rewriter ── 逻辑表名改写为真实表名，修正分页/排序/分组，补充分片键
  │
  ▼
SQL Executor ── 多线程并发执行真实 SQL，独立执行引擎管理
  │
  ▼
Result Merger ── 多路结果流按内存/流式策略归并：排序、分组、分页、聚合
```

这五步是 Agent 可观测性埋点的天然骨架：Tracing 插件分别暴露解析与执行各阶段的耗时，慢查询定位先看卡在哪一步（见 [Governance](/docs/CS/DB/ShardingSphere/Governance.md)）。

## SQL Parser

- **多方言**：每种数据库一套解析引擎，产出与方言无关的内部 AST。这也是「SQL 方言翻译」类能力的底座——Proxy 面向异构语言时，语法树先归一化再进路由。
- **JDBC 接入端的内存坑（官方 README 明确提醒）**：ANTLR 在解析过程中使用内部缓存提升性能，**SQL 模板数量过多时缓存会持续增长、占用大量堆内存**，对应 ANTLR issue#4232 长期未修复。对策是给 JDBC 接入端的应用设置合理的 `-Xmx`——接入端与应用共享 JVM，这是它与 Proxy 的关键差异。
- 解析失败或方言不支持时走应用层报错，不会静默降级。

## SQL Router

路由的输入是 AST 里的分片条件，输出是**真实数据节点列表**：

- **有分片键**：按分片策略（见 [Sharding](/docs/CS/DB/ShardingSphere/Sharding.md)）精确路由，`=` 与 `IN` 是标准算法的基本盘。
- **无分片键**：**全路由**——每条 SQL 扇出到所有数据节点。功能正确，性能最差；「为什么突然变慢」的高频答案就是某条查询丢了分片条件。
- **Hint 强制路由**：分片值不由 SQL 决定而由外部条件决定时，用 SQL Hint（Java API 的 `HintManager` 或 SQL 注释）注入分片值，绕过对 SQL 条件的依赖。
- **绑定表短路**：绑定表组内只用主表的分片条件计算一次，其余表复用该结果。没有绑定表关系时，`t_order` 与 `t_order_item` 按同一 `order_id` 分片也会产生 2×2 的笛卡尔积路由（官方概念页有完整例子）；配了绑定表，同样 SQL 只路由出 2 条。

## SQL Rewriter

改写器把「面向逻辑库表的 SQL」变成「面向真实节点的 SQL」：

- **表名替换**：`t_order` → `t_order_0`，数据源名同步替换。
- **分页修正**：跨分片 `LIMIT` 不能原样下发——每个节点只取自己那一份，再由归并层拼出正确窗口；排序、分组同理。
- **补列**：INSERT 未显式给出分片键/分布式主键时，由键生成器（SNOWFLAKE/UUID）补值后再路由——所以分片键列在逻辑上「不写也能对」。
- **改不动的场景**：跨库 join、子查询、复杂聚合天然超出单节点语义，要么靠归并层硬撑（代价高），要么改 SQL，要么上联邦查询。

## SQL Executor

- 多个真实节点的 SQL **并发执行**，执行引擎独立于连接管理，可通过 `max-connections-size-per-query` 一类属性约束单查询的连接占用（默认 1，即串行取连接、并发执行）。
- 执行阶段本身不感知分片语义——它只拿到一组「节点 + 已改写 SQL」，这也解释了为什么分片配置错误往往在执行层才暴露成数据错误。

## Result Merger

多路结果流的合并是五步里最容易被低估的一步：

- **排序归并**：各节点已按 `ORDER BY` 排好序，归并层做多路归并；若下层没排序，则退化为全量内存排序。
- **分页归并**：跨分片 `LIMIT 10000, 10` 的语义是「全局第 10000 条起 10 条」，必须在归并层重算窗口——深分页是跨片查询的经典性能陷阱。
- **聚合改写**：`COUNT` 变成「各节点 COUNT 再求和」这类逐层聚合，改写器与归并器协同完成。
- **流式 vs 内存**：结果集可流式归并的查询内存友好；需要全量缓存的分组/排序则吃堆——大数据量跨片分析优先考虑 Proxy + 联邦或直接走数仓，别在中间件上硬扛。

## SQL Federation

当跨库 join、子查询、聚合查询无法靠改写与归并体面解决时，ShardingSphere 提供联邦查询作为出口。**但必须先看状态：官方文档明确标注它是 experimental（实验性）功能，「currently not suitable for use in core system production environments」（当前不适合用于核心系统生产环境）**。

配置形态（5.5 迁移口径）：

```yaml
sqlFederation:
  providerType: CALCITE        # NONE 为默认值，即关闭联邦
  allQueryUseSQLFederation: false
  executionPlanCache:
    initialCapacity: 2000      # 执行计划本地缓存初始容量
    maximumSize: 65535         # 执行计划本地缓存上限
```

- 提供方为 **CALCITE**（Apache Calcite 优化器），执行计划带本地缓存；`allQueryUseSQLFederation` 控制是否所有查询都走联邦。
- 从旧配置迁移时**移除 `sqlFederationEnabled`**，原 `sqlFederationEnabled: false` 的配置改为 `providerType: NONE`。
- 结论：联邦查询是逃生舱，不是常规路径。跨片关联查询的正解仍然是业务侧按分片键设计（绑定表、同片存放），见 [Sharding](/docs/CS/DB/ShardingSphere/Sharding.md) 与 [Shard](/docs/CS/DB/Shard.md)。

## Facts Worth Pinning Down

1. **无分片键 = 全路由**，性能断崖；上线前用审计规则（`DML_SHARDING_CONDITIONS`）把这类 SQL 找出来。
2. **SQL Federation 默认关闭且官方不推荐上核心生产**：`providerType: NONE` 是默认值，别被「联邦查询」四个字误导成 GA 能力。
3. **ANTLR 缓存会随 SQL 模板数量增长**，JDBC 接入端必须预留堆内存；Proxy 无此问题。
4. **深分页、跨片排序、跨片分组**都在归并层付出内存或全量传输代价——这类负载属于 OLAP，放 Proxy 或下沉数仓，别塞进 OLTP 链路。

## Links

- [Operations](/docs/CS/DB/ShardingSphere/Operations.md)
- [Encryption](/docs/CS/DB/ShardingSphere/Encryption.md)

## References

1. [Core Concept :: ShardingSphere](https://shardingsphere.apache.org/document/current/en/features/sharding/concept/)
2. [SQL Federation Configuration](https://shardingsphere.apache.org/document/current/en/user-manual/shardingsphere-jdbc/yaml-config/rules/sql-federation/)
3. [Observability :: ShardingSphere](https://shardingsphere.apache.org/document/current/en/features/observability/)
4. [apache/shardingsphere README](https://github.com/apache/shardingsphere)
