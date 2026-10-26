## Introduction

TDengine 的查询语言是**类 MySQL 的 SQL 方言**：大部分标准语法可以直接用，时序特有的能力以扩展关键字和伪列的形式注入。它和通用 SQL 最大的分野不在语法糖，而在**执行形状**——一次超级表查询会被拆成"各 vnode 本地预聚合 → 全局归并"的两阶段，时间窗口、降采样、插值这些都围绕时间轴设计。

本页讲方言的时序扩展、窗口算子全家桶、JOIN 的三个版本断点、查询策略与执行流程、UDF、TSMA 预计算。流计算与订阅虽然也用 SQL 创建，但属于另一条产品线，见 [Stream_Compute](/docs/CS/DB/TDengine/Stream_Compute.md)。

## Dialect Extensions

相对标准 MySQL SQL 的时序扩展：

| 扩展 | 形式 |
| :-- | :--- |
| 超级表关键字 | `CREATE STABLE meters (...) TAGS (...)`；子表 `CREATE TABLE ... USING meters TAGS (...)` |
| 直接在超级表上按 tag 过滤 | `SELECT ... FROM meters WHERE groupid = 1` |
| 降采样窗口 | `INTERVAL(5m)`、`INTERVAL(1d, start_time)` |
| 窗口伪列 | `_wstart`（窗口起始）、`_wend`（窗口结束）、`_rowts`（行主时间戳） |
| 时间函数 | `NOW()`、`TODAY()`、`TIMETRUNCATE(NOW(), 1w/1n/1h...)`、`ELAPSED()`、`TWA()` |
| 顺序分析函数 | `FIRST`、`LAST`、`LAST_ROW`、`DIFF`、`CSUM`、`MAVG`、`DERIVATIVE`、`STATECOUNT`、`STATEDURATION`、`LAG`、`LEAD`、`UNIQUE`、`FILL_FORWARD` |
| 元数据命令 | `SHOW STABLES`、`SHOW TABLES`、`SHOW DATABASES`、`SHOW VGROUPS`、`SHOW QNODES`…… |

时间范围过滤推荐**左闭右开**：`WHERE ts >= start AND ts < end`。这是所有窗口类算子的前提。

## Window Operators

官方技术内幕列出的窗口类型：**time window、state window、session window、event window、count window**，3.4 起 TDgpt 又加了算法驱动的**异常窗口**（见 [TDgpt](/docs/CS/DB/TDengine/TDgpt.md)）。几个高频的语义：

- **time window（`INTERVAL`）**：等长切窗，`_wstart`/`_wend` 标出每窗边界；长跨度趋势查询靠它降采样。
- **session window**：按间隔容差把连续活动聚成会话（`SESSION(ts, tol)`），适合"事件流按静默分段"。
- **state window**：按某列的状态值分段（设备运行/空闲/故障切换自动分段统计）。
- **event window**：由开始/结束条件表达式界定，适合"从告警发生到恢复"这类业务事件。
- **count window**：按行数切窗。

窗口查询要处理空洞：`FILL` 系列（`FILL(VALUE)`、`FILL(PREV)`、`FILL(LINEAR)`、`FILL(NULL)`）决定空窗口怎么补，另有 `INTERP` 做插值。**注意 3.4.3.0 起窗口算子对 timeline 有硬要求**：输入无系统时间列时会退化为"第一个 TIMESTAMP 列"，连 TIMESTAMP 列都没有则进 no-timeline 模式——此时 `FIRST/LAST/LAST_ROW/DIFF/CSUM/MAVG/LAG/LEAD/FILL_FORWARD/UNIQUE` 可按行序跑，但 `DERIVATIVE/TWA/ELAPSED/STATEDURATION/INTERP/INTERVAL` 直接报错。子查询要稳定行序就显式 `ORDER BY`。

## JOIN：三个版本断点

这是选型时最容易踩的过时结论。TDengine 的 JOIN 是分三步放开的：

| 版本 | 能力 |
| :-- | :--- |
| **< 3.3.0.0** | 只支持 INNER JOIN |
| **≥ 3.3.0.0** | LEFT、RIGHT、FULL、SEMI、ANTI-SEMI，外加时序特色的 **ASOF JOIN**（为左表每行匹配右表此前最近的读数）和 **WINDOW JOIN**（按时间邻域匹配，`WINDOW_TIME`/`WINDOW_OFFSET`） |
| **≥ 3.4.3.0** | 显式 **CROSS JOIN** 与无条件逗号 join；JOIN 结果可再作为另一个 JOIN 的左右输入，**INNER/CROSS/LEFT/RIGHT/FULL/SEMI/ANTI/ASOF/WINDOW 可混合嵌套** |

3.4.3.0 起普通 JOIN 还放宽了**条件与 timeline 要求**：join 条件不再必须有主时间戳，优化器按条件和输入顺序在 Hash / Theta 算法里选（不满足 Merge 前提时）；普通表、子表、超级表、虚拟表、子查询之间可以自由组合，子表间还支持等值之外的一般布尔条件。但**普通 JOIN 不保证结果顺序**，要顺序必须显式 `ORDER BY`。JOIN 结果再参与 ASOF/WINDOW 时须提供可用的 TIMESTAMP 参照列（未显式指定时按列序取第一个主时间列，没有则取第一个 TIMESTAMP 列）。

## Query Execution

一次查询在客户端主导下走八步（官方技术内幕）：

1. taosc 解析 SQL 成 **AST**，Catalog 向 vnode/mnode 请求元数据，做权限、语法、合法性校验。
2. 生成**逻辑查询计划**，顺序应用优化策略；再基于 vgroup 与 qnode 数量等元数据生成**物理计划**。
3-4. 客户端查询调度器按**数据亲和性或负载**把子任务派发到 vnode/qnode 所在 dnode，进各自的任务队列。
5. vnode/qnode 执行线程取任务执行，拿到部分结果即通知客户端。
6-8. 调度器收尾，向顶层算子所在节点发数据请求，算子按父子关系逐级下游取数，taosc 做最后一级归并返回应用。

超级表聚合的扇出路径：**taosc → mnode（取元数据）→ 各 vnode（本地预聚合）→ qnode（全局聚合）→ 客户端**。两个关键优化：

- **tag 先行过滤**：系统先在内存里过滤 tag 数据、确定参与聚合的子表集合，再扫 metric 列——大幅缩小扫描数据集。
- **两阶段聚合**：vnode 侧本地窗口/预聚合减少上传量，qnode 侧跨节点归并。

`queryPolicy`（taosc 配置，只对单个 taosc 生效，集群内可混用）控制这条路径的走法：

| 值 | 语义 |
| :-- | :--- |
| `1` | 所有查询只用 vnode（**默认**） |
| `2` | vnode/qnode 混合 |
| `3` | 只有表扫描用 vnode，其余计算全走 qnode |
| `4` | 客户端聚合模式 |

用了 UDF 时查询模块还会调度独立的 **UDF Daemon** 执行用户自定义函数，把计算负载从主查询流程里分离。

## TSMA

TSMA（物化聚合）把"固定窗口的固定聚合"在写入侧就算好、落成 sma 文件，查询命中时直接读预计算结果而不是扫原始数据——这是 TSDB 对抗"每次查询重算全量"的标准手段，官方在存储层为它单设了一类文件。流计算（[Stream_Compute](/docs/CS/DB/TDengine/Stream_Compute.md)）持续产出的结果表则覆盖另一类"持续计算"需求，两者互补：TSMA 是惰性按需预计算，stream 是写入即触发。

## Virtual Table Queries

3.4 起虚拟表（vtable）的查询有专门优化：投影查询、聚合函数、选择函数和窗口查询都做了下推与两阶段拆分（聚合下推 + 窗口两阶段）。跨表对齐、按区域汇总这类"报表维度 ≠ 存储维度"的查询不再需要应用层拼 SQL。

## Links

- [TDengine](/docs/CS/DB/TDengine.md)
- [Storage_Engine](/docs/CS/DB/TDengine/Storage_Engine.md)
- [Stream_Compute](/docs/CS/DB/TDengine/Stream_Compute.md)
- [TDgpt](/docs/CS/DB/TDengine/TDgpt.md)
- [Timeseries](/docs/CS/DB/Timeseries.md)

## References

1. [技术内幕：查询引擎](https://docs.tdengine.com/internals/query/)
2. [关联查询（JOIN）](https://docs.taosdata.com/tdengine-sql/data-query/join)
3. [数据查询总览](https://docs.tdengine.com/tdengine-sql/data-query/query)
4. [技术内幕：虚拟表查询](https://docs.tdengine.com/internals/vtable-query/)
