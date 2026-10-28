## Introduction

一条 SQL 在 SQLite 里的生命线是：解析成语法树 → 规划器选出执行策略 → 代码生成器产出 VDBE 字节码 → 虚拟机执行。规划器是其中唯一「做决策」的部件，也是慢查询调优的唯一入口。它的一切决策都是**基于统计信息的估计**，估计会错——所以这页的重点不是「它怎么选」，而是「怎么观测它选了什么、怎么把估计校准」。

## VDBE

**VDBE（Virtual Database Engine）是 SQLite 的心脏**：一台寄存器式虚拟机，运行专为「搜索、读取、修改数据库」设计的指令集。每条语句被编译成一段程序，执行从指令 0 顺序推进，遇 `OP_Halt` 或越界即结束，程序结束时自动关游标、释放内存——所以不存在资源泄漏式的收尾问题。

- 3.x 的 VDBE 每条指令带 5 个操作数（opcode + P1~P4 + P5）；游标、寄存器、跳转目标都编码在操作数里。
- `EXPLAIN <SQL>` 打印程序不执行；`PRAGMA vdbe_trace=ON` 逐指令跟踪执行过程。两者是读汇编级真相的手段，日常调优用不上，但怀疑「规划器到底生了什么」时没有替代品。
- 文档坑：官方 `vdbe.html` 描述的是 **2.8.0 的栈式 VDBE**（每指令 3 个操作数、无寄存器），与现行实现有本质区别；引用其中结论前先看页面自己的版本声明。

## Query Planning Basics

规划器把 JOIN 拆成**嵌套循环**：每表一层循环，`IN`/`OR` 再插循环层。问题分解成两步——**定循环嵌套顺序**（难，连接数上来是组合爆炸）与**为每层选索引**（顺序定了通常显然）。成本是**对数刻度**的估计值：嵌套循环工作量相乘而非相加，所以对数差 6.87 意味着实际约 963 倍差距；「看起来差不多」的两个计划执行起来可以天差地别。

成本由几部分构成：一次性 setup 成本（比如现算一个自动索引）、每步执行成本、估计行数（喂给内层循环）、以及 `ORDER BY` 的排序成本。

## Index Selection Tricks

三类把「不能用索引」变成「能用索引」的重写，值得逐条记住触发条件：

- **覆盖索引**：索引查找通常两次二分（先在索引定位、再按 rowid 回表）。查询所需列全在索引里时 SQLite 不再回表，每行少一次查找，实测常快一倍。`EXPLAIN QUERY PLAN` 里出现 `USING COVERING INDEX` 即是。
- **LIKE 优化**：`col LIKE 'abc%'` 被改写成 `col >= 'abc' AND col < 'abd'` 的范围约束。前提：右侧是字符串字面量或经 `prepare_v2` 绑定的参数、不能以通配符开头、未被应用重载 `like()`、`ESCAPE` 字符是单字节；**GLOB 要求 `BINARY` 排序规则索引，LIKE 的要求随 `PRAGMA case_sensitive_like` 变**——默认 OFF（LIKE 大小写不敏感，仅限 ASCII），须 `COLLATE NOCASE` 索引；打开该 pragma 后则须 `BINARY` 索引。
- **OR 优化**：同列多个 OR 项先改写成 `IN`；改不了时若每个子项都能单独用索引，则为每个子项分别查（可各用不同索引）再取并集——这是 SQLite「一个表一次只用一个索引」规则的主要例外。子项太多或索引太烂时规划器仍会选全表扫描。

两个手工控制手段：`A CROSS JOIN B` **永不重排**（强制 A 外层 B 内层，是留给程序员的手动档）；WHERE 里的**一元 `+`** 让该项失去驱动索引的能力（`WHERE +x=5 AND y=6` 强制绕开 x 上的索引），但副作用是同时剥掉该列的类型亲和性，可能悄悄改变比较语义。

## Automatic Indexes

没有可用索引时，规划器可能为**单条语句的持续时间**现算一个临时索引：成本 O(N log N)，全表扫描是 O(N)，因此只有预计查找会执行**超过 log N 次**时才划得来。缺 ANALYZE 统计时 SQLite 默认猜 N = 1,000,000——天然倾向于建自动索引。自 3.8.0 起，每次动用自动索引都会向错误日志发一条 `SQLITE_WARNING_AUTOINDEX`，这是「该补真索引了」的官方提示。`PRAGMA automatic_index` 可运行时关闭，`SQLITE_DEFAULT_AUTOMATIC_INDEX` / `SQLITE_OMIT_AUTOMATIC_INDEX` 从编译期控制。

注意与 `sqlite_autoindex_*` 区分：后者是实现 PRIMARY KEY / UNIQUE 约束的**持久内部索引**，对所有连接可见；前者只在语句期间存在、不落盘。

## Flattening

子查询出现在 FROM 里时，最直接的做法是物化成临时表再扫——临时表无索引，外层只能全表扫或现场建索引。**扁平化**把子查询的 FROM 并进外层 FROM 并重写引用，视图和复杂查询的性能全靠它。不允许扁平化的情形又长又多（子查询带 DISTINCT / LIMIT / OFFSET、外层或子查询带窗口函数、复合 SELECT、位于外连接右侧等），官方原话是「细微且复杂，无需全部记忆」——但要记住 SQLite 对此**保守**：早期曾因过度扁平化出过 bug，所以宁可物化。

## Statistics and ANALYZE

`ANALYZE` 把数据分布写进 `sqlite_stat1`（编译进 `SQLITE_ENABLE_STAT4` 时还有 `sqlite_stat4` 全列直方图）。官方结论：有准确统计时规划器总能找到不差于旧版的计划；schema 里别有「最左列重复值超过 10~20 行」的低质量索引（布尔/枚举列别做索引首列），否则必须 ANALYZE 让规划器知道索引烂——没有统计时它假设所有索引同等选择性。

日常维护就一条：**`PRAGMA optimize`**（连接关闭前自动跑，长跑应用约每天一次，schema 变更后也跑）。注意 STAT4 会违反查询规划器稳定性保证（QPSG），要用它与要「同一 SQL 永远同一计划」是互斥的。

## The Next-Generation Query Planner

3.8.0（2013-08-26）起重写，NN 启发式（每步选最便宜弧）换成 **N3**（每步保留 N 条最优路径）：存储 O(N)、计算 O(K·N)，远快于穷举 O(K!)。动因是 TPC-H Q8（8 路连接）：NN 得到成本 36.92 的计划而最优 27.38，**实际性能差近 750 倍**。N 的取值随连接数涨：二元 5、三元以上 10（后提至 12，星型 schema 18）。

N3 仍是贪心，星型 schema（大事实表 + 多个小维度表）会在搜索初期把「先搜事实表」的最优计划挤出 N-best 集合。现行启发式（3.49.0 起）是**人为抬高维度表全表扫描的成本估计**；3.47.0/3.48.0 曾试过「降低事实表访问成本」，引发回归已弃用。

**QPSG**（查询规划器稳定性保证）：schema 无重大变化、未重跑 ANALYZE、库版本相同，则同一 SQL 始终得到同一计划。默认关闭，需 `SQLITE_ENABLE_QPSG` 或 `sqlite3_db_config(SQLITE_DBCONFIG_ENABLE_QPSG, 1, 0)`。

## Reading Plans

- `EXPLAIN QUERY PLAN`：树状访问计划（SCAN / SEARCH / USE INDEX / AUTOMATIC COVERING INDEX），是日常调优的主界面。
- `EXPLAIN`：VDBE 程序，寄存器机的指令序列，回答「规划器到底生了什么」。
- `PRAGMA vdbe_trace=ON`：逐指令执行跟踪，最后手段。

## Links

- [SQLite](/docs/CS/DB/SQLite.md)
- [DataBases](/docs/CS/DB/DB.md)
- [Indexes](/docs/CS/DB/Concept/Index.md)
- [MySQL Optimizer](/docs/CS/DB/MySQL/Optimizer.md)
- [RocksDB Read_Path](/docs/CS/DB/RocksDB/Read_Path.md)

## References

1. [The Next-Generation Query Planner](https://sqlite.org/queryplanner-ng.html)
2. [The SQLite Query Optimizer Overview](https://sqlite.org/optoverview.html)
3. [The SQLite Bytecode Engine](https://sqlite.org/opcode.html)
4. [The Virtual Database Engine of SQLite](https://sqlite.org/vdbe.html)
