## Introduction

MyCAT 对一条 SQL 的处置可以归纳成一个决策：**哪些分片参与、SQL 被改写成什么、结果怎么合回来**。前两者由解析与路由决定，第三者由归并层决定——而三层的能力上限共同划出了「哪些 SQL 能在 MyCAT 上跑」的边界。本页按这个顺序展开：路由决策树、跨库 join 的三档支持、聚合与分页的归并语义、1.6 的能力禁区，以及 MyCAT2 在 Calcite 加持下多出来的东西。

## The Routing Decision

SQL 进入 Router 后的第一件事是看分片键：

```
分片列上有等值条件（WHERE user_id = 123）
  └─ 精确路由：算法算出唯一 dataNode，只下发这一个分片

分片列上有范围条件（WHERE create_time BETWEEN ...）
  └─ 范围路由：算法算出多个 dataNode，并发下发

没有分片列 / 条件不可解析 / 非分片表
  └─ 全分片广播：所有 dataNode 都执行，归并结果
```

三种路径的性能差距是数量级的：**精确路由只打一个分片、走一次网络、无归并**；广播则打全部分片、全部网络、全部归并。所以 MyCAT 使用的第一条军规是：**查询必须带分片键**。不带分片键的即席查询会把中间件打成瓶颈——这不是缺陷，是分片架构的固有代价，见 [Shard](/docs/CS/DB/Concept/Shard.md)。

第二条军规与解析器有关：默认 `druidparser` 解析不了或解析异常的 SQL，路由会退化成广播甚至报错。**同一个 SQL 在 MySQL 上能跑、在 MyCAT 上行为不同，先怀疑解析层**。

## Cross-Database Joins: Three Tiers

MyCAT 对 join 的支持是分层的，能力边界必须记住：

| 层级 | 形态 | 条件 |
| :--- | :--- | :--- |
| 单库任意 join | 多表 join 原样下发 | 所有表落在同一个分片（同库） |
| 跨库两表 join | 拆成两次单库查询，内存做嵌套循环/哈希 | 仅两张表 |
| caltet 多表 join | 自定义插件（caltet）执行多表 join | 需开发 caltet 逻辑 |

第一档是「免费」的：同库 join 就是普通 MySQL 查询，MyCAT 只做表名替换。第三档是 escape hatch——caltet 允许把多表 join 的计算逻辑写成插件，在中间件层完成关联，但要自己开发维护。

让 join 尽量落进第一档的两个配置手段——ER 分片与全局表——在 [Sharding_Rules](/docs/CS/DB/MyCat/Sharding_Rules.md) 展开。经验法则：**能在 schema 设计阶段消灭的跨库 join，不要留给路由层**。

## Aggregation and Pagination

跨分片查询的归并语义：

- **聚合函数**：`sum` / `count` / `max` / `min` 在各分片本地计算后合并（count 是求和、max 是取大）。1.6 起支持**非堆内存（Direct Memory）聚合计算**，大结果集不再必然堆溢出——但只是缓解，归并内存的上限仍在中间件进程内。
- **排序**：跨分片 `ORDER BY` 走多路归并（各分片有序流合并）。
- **分页**：跨库分页是「各分片按改写后的 LIMIT 取窗口 → 归并排序 → 截断到目标页」。深翻页（`LIMIT 100000, 10`）会在每个分片上取 100010 行再归并，代价随深度线性增长——**大 offset 分页要么改造 API（游标/keyset），要么按分片键定位**。
- **UNION / DISTINCT**：按集合语义在各分片结果上归并。

这些语义与单库 MySQL 一致，但**成本模型完全不同**：单库上一个 `LIMIT` 是扫描终点，分片上它是每个分片的扫描终点之和。慢查询分析时要把 SQL 拆回各分片单独 explain。

## Capability Boundaries in 1.6

1.6 有几个明确写进 README 的限制与已知缺陷，接入前必须知道：

- **一个连接不支持多条语句**（multi-statement）：`stmt.execute("...; ...")` 直接不被支持。
- **三个点名要避开的功能**：批处理插入（JDBC batch）、多语句、堆外合并——官方 README 原文 "1.6的bug: 批处理插入,多语句,堆外合拼,请大家要避开这些功能"。
- **复杂聚合的建议是应用层完成**：官方教程对跨分片复杂查询的推荐策略就是「应用层聚合」，不要指望中间件包打天下。
- **存储过程**：1.6 起支持 MySQL 与 Oracle 的存储过程、out 参数与多结果集返回——老版本不行。

## What MyCAT2 Adds

MyCAT2 把查询引擎换成 Apache Calcite 后，同一批 SQL 的处理能力上了一个台阶：

- **规则优化 + 代价优化**：连接顺序、条件下推、投影剪裁都由优化器决定，不再依赖手写路由规则。
- **BKAJOIN**：批量键访问 join，配合回表生成条件下推——后续版本持续修复过 BKAJOIN 的执行计划生成与条件下推问题。
- **全局二级索引**：按非分片键查询不再必然全分片广播；配套修复过「全局索引表大于 1 个时无法使用」「使用二级索引字段报错」等问题。
- **范围查询增强**：分片表支持 `1 < col and col < 10` 这类双侧范围。
- **执行计划可观测**：`explain` 支持展示 colocatedpushdown；`fullTableScanLimit` / `fullTableScanException` 给全表扫描加了熔断（超限直接报错而非放行）。
- **修正过的深坑**：全局表下推后分片条件丢失、单表路由（HackRouter）duplicate key、回表场景行类型不匹配导致二级索引不生效——这些 1.x 时代「莫名其妙的结果错误」在 2.x 被逐个修掉，也从侧面说明 1.x 在这条路上有多脆弱。

## Links

- [MyCat](/docs/CS/DB/MyCat/MyCat.md)
- [Sharding_Rules](/docs/CS/DB/MyCat/Sharding_Rules.md)
- [Shard](/docs/CS/DB/Concept/Shard.md)
- [Architecture](/docs/CS/DB/MyCat/Architecture.md)

## References

1. [MyCATApache/Mycat-Server README（1.6 限制与已知缺陷）](https://github.com/MyCATApache/Mycat-Server)
2. [MyCATApache/Mycat2 Releases（BKAJOIN、全局二级索引、fullTableScanLimit 等变更）](https://github.com/MyCATApache/Mycat2/releases)
3. [MyCAT 官方网站 · 关键特性](https://www.mycat.org.cn)
