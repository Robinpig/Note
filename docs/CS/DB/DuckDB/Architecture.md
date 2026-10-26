## Introduction

DuckDB 的架构可以用一个反差概括：**内部是最激进的分析型引擎，外部是最保守的嵌入式形态**。它没有进程边界、没有网络协议栈（2.0 前）、没有连接池，就是一个被链接进宿主进程的库；但一旦开始执行查询，向量化、morsel 并行、压缩态执行、out-of-core spill 这些数仓引擎的看家本领一样不少。本页讲清这台引擎的骨架：七段编译执行流水线、push-based 向量化模型、并行与内存模型，以及「Duck Stack」三层产品的边界。存储与执行格式的细节分别在 [Storage_Format](/docs/CS/DB/DuckDB/Storage_Format.md) 与 [Execution_Engine](/docs/CS/DB/DuckDB/Execution_Engine.md) 展开。

## In-Process by Design

DuckDB 把「数据库」实现成宿主进程内的一个对象（Python 的 `duckdb.connect()`、Java 的 `JdbcConnection`、C 的 `duckdb_open()`），这个选择带来一连串连锁后果：

- **没有网络 hop**：查询编译、目录访问、数据读取都在同一地址空间完成，函数指针与 catalog 可以常驻缓存——官方明确把这列为并发模型采用「单写者进程」的理由之一。
- **部署单位是一个文件**：持久库是「一个 `.duckdb` 文件 + 一个 `.wal` 预写日志」，备份是文件拷贝，分发是拷贝文件。
- **客户端 API 是门面**：同一份磁盘格式、同一套 SQL 语义跑在十一门客户端上（见 [Operations](/docs/CS/DB/DuckDB/Operations.md)），差异只在惯用法（如 Python 的 relational API 与 replacement scan）。
- **生态是进程间的**：数据交换不走专有协议，走 Parquet / Arrow / CSV 这些通用格式，以及与 Postgres/MySQL/SQLite 互通的内置 scanner。

## Query Pipeline

一条 SQL 从文本到结果经过七个阶段，前六段在提交前完成，最后一段执行：

```
Parser → Binder → Logical Planner → Optimizer → Column Binding Resolver → Physical Plan Generator → Execution
```

### Parser

Parser 只做词法与语法：输入 SQL 文本，输出 `SQLStatement` / `QueryNode` / `TableRef` / `ParsedExpression` 四种语法树节点。**它不查 catalog、不解析类型**——表不存在不报错，列类型未定不报错，这些全部推迟到 Binder。`ParsedExpression` 上没有类型信息（`CAST` 节点除外），比较、列引用、常量在语法层是同构的节点。

2.0 起默认解析器换成 **PEG 解析器**（1.5 起作为 opt-in 引入），它是「extensible SQL parser」的载体：可以用 SQL 语句本身给语法加新结构。旧的 PostgreSQL 派生解析器移入 `legacy_parser` 扩展，需要旧语法兼容时显式加载。

### Binder

Binder 是第一个「知道数据库存在」的阶段：

- 用 catalog 解析表与列引用，产出 `BoundStatement` / `BoundQueryNode` / `BoundTableRef` / `Expression`。
- 解析所有表达式的类型——类型检查、隐式转换、函数重载决议都在这里完成，此后类型不再变化。
- 抽取聚合函数与窗口函数，把 `SELECT a, sum(b) FROM t GROUP BY a` 这类查询的聚合结构显式化，供后续规划使用。

绑定失败的错误（`Binder Error`）是 DuckDB 最常见的报错类别——「表不存在」「列不存在」「类型不匹配」「没有这个函数」全部出自这一层。

### Logical Planner

把 bound statement 转成 `LogicalOperator` 组成的逻辑查询树：`LOGICAL_GET`（扫表/扫文件）、`LOGICAL_FILTER`、`LOGICAL_JOIN`、`LOGICAL_AGGREGATE`、`LOGICAL_PROJECTION`、`LOGICAL_ORDER_BY`、`LOGICAL_LIMIT` 等。此时树还是「逻辑」的：连接顺序未定、访问路径未选。

### Optimizer

优化器是一组顺序作用的规则（rule），每条规则改写逻辑树。2.0 文档列出的规则：

| 规则 | 作用 |
| :--- | :--- |
| Expression Rewriter | 简化表达式、常量折叠 |
| Filter Pushdown | 过滤条件下推、按等价类复制过滤、静态为假时剪掉子树 |
| Join Order Optimizer | 用动态规划重排连接顺序，算法是 **DPhyp**（*Dynamic Programming Strikes Back*） |
| Common Sub Expressions | 提取投影/过滤中的公共子表达式，避免重复执行 |
| In Clause Rewriter | 把大的静态 `IN` 列表重写成 MARK join 或 INNER join |

注意 DuckDB 没有基于代价的优化器（CBO）——没有直方图、没有行数估计驱动的连接顺序搜索；DPhyp 做的是纯粹的「最小化中间结果大小」的动态规划。这与 PostgreSQL/MySQL 的 CBO 传统是两条路。

### Column Binding Resolver

把 `BoundColumnRefExpression`（引用某张表的某列）转成 `BoundReferenceExpression`（引用 DataChunk 中的第几列）。此后执行层只看见「位置」，不再知道位置属于哪张表——这是逻辑与物理执行之间的解耦点。

### Physical Plan Generator

把逻辑算子转成 `PhysicalOperator` 树，同时把向量化执行需要的物理细节定下来：扫哪个表/哪组文件、用哪种连接算法（nested loop / hash join / piecewise merge join / IEJoin）、聚合用哪种分组策略（哈希聚合 / 排序聚合）、排序选哪种算法。

### Execution

物理算子以 **push-based（推式）** 执行：查询结果从叶子算子向上推，每个算子被上游「要数据」时生产一批 DataChunk 传给下游。与之相对的 pull-based（火山模型）每行一次函数调用，向量化把它变成每批 2048 行一次。推式的代价是 pipeline 边界（breaker）处需要物化中间结果（如哈希 join 的建侧、排序的全部输入、聚合的分组表），这是并行度与内存占用的分水岭，详见 [Execution_Engine](/docs/CS/DB/DuckDB/Execution_Engine.md)。

## Parallelism and Memory

- **线程数默认等于 CPU 核数**（`SET threads = N`）。DuckDB 的并行单位是 morsel——行组内部再切成更细的调度单元，由任务调度器分发给工作线程；数据源（扫描）与阻塞算子（排序、聚合、join 建侧）是并行的两个端点。
- **内存上限默认物理内存的 80%**（`SET memory_limit = '10GB'`）。超过即触发 out-of-core：排序与哈希表可落盘，2.0 起内存库与持久库都支持 spilling。容器部署必须显式收紧这两个旋钮，否则会被 cgroup OOM kill。
- **异步 I/O（2.0）**：Parquet、CSV 与原生格式的读取走异步 I/O 层，I/O 与查询处理独立伸缩，多个请求可同时在飞——官方称这给对象存储（如 S3）上的远程读取带来「far more parallelism」。

## The Duck Stack

2.0 之后，「DuckDB」这个词涵盖三层，边界值得分清：

| 层 | 形态 | 解决的问题 |
| :--- | :--- | :--- |
| DuckDB | 进程内数据库 + `.duckdb` 文件格式 | 单机、单写者进程的分析 |
| Quack | 客户端/服务器协议 + `quack` 扩展 | 多进程访问同一个 DuckDB（2.0 起打磨成熟） |
| DuckLake | 湖仓表格式 + `ducklake` 扩展 | 多writer、快照、时间旅行，目录存 SQL 数据库 |
| Iceberg | `iceberg` 扩展 | 与既有 Iceberg 生态互操作 |

换言之：进程内形态仍是地基，Quack 补上「服务器」这块短板，DuckLake 补上「多写者与快照」这块短板，而 Iceberg 支持让 DuckDB 能寄生在已有的湖仓生态上。部署选型见 [Operations](/docs/CS/DB/DuckDB/Operations.md)，格式细节见 [Ecosystem](/docs/CS/DB/DuckDB/Ecosystem.md)。

## Links

- [DuckDB](/docs/CS/DB/DuckDB.md)
- [Execution Engine](/docs/CS/DB/DuckDB/Execution_Engine.md)
- [Storage Format](/docs/CS/DB/DuckDB/Storage_Format.md)
- [Ecosystem](/docs/CS/DB/DuckDB/Ecosystem.md)
- [Table Format](/docs/CS/BigData/Table_Format.md)

## References

1. [DuckDB Internals – Overview](https://duckdb.org/docs/2.0/internals/overview.html)
2. [DuckDB Internals – Execution Format](https://duckdb.org/docs/2.0/internals/vector.html)
3. [Dynamic Programming Strikes Back (DPhyp)](https://15721.courses.cs.cmu.edu/spring2017/papers/14-optimizer1/p539-moerkotte.pdf)
4. [Push-Based Execution in DuckDB (talk)](https://www.youtube.com/watch?v=1kDrPgRUuEI)
5. [Announcing DuckDB 2.0.0 LTS](https://duckdb.org/2026/10/21/announcing-duckdb-200)
