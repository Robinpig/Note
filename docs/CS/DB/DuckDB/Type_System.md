## Introduction

DuckDB 的 SQL 方言贴着 PostgreSQL，但类型系统比 Postgres 更宽：有 128 位整型 `HUGEINT` 与任意精度 `BIGNUM`，有七种嵌套类型，2.0 还加了半结构化的 `VARIANT`。本页按「标量 → 嵌套 → 特殊」三层过一遍类型，重点放在与 Postgres 的差异和三个真实会咬人的坑：大小写规则、「更新嵌套列 = 先删后插」、以及类型对性能的影响。

## General-Purpose Types

| 类型 | 别名 | 说明 |
| :--- | :--- | :--- |
| `BOOLEAN` | `BOOL`、`LOGICAL` | 逻辑布尔 |
| `TINYINT` / `SMALLINT` / `INTEGER` / `BIGINT` | `INT1`/`INT2`/`INT4`/`INT8`、`INT`、`LONG` | 1/2/4/8 字节有符号整型 |
| `HUGEINT` | — | **16 字节有符号整型**（128 位），Postgres 没有对应物 |
| `UTINYINT` / `USMALLINT` / `UINTEGER` / `UBIGINT` / `UHUGEINT` | — | 无符号家族，直到 128 位 |
| `BIGNUM` | — | 变长任意精度整数 |
| `DECIMAL(p, s)` | `NUMERIC` | 定点数，默认精度 18、标度 3 |
| `FLOAT` / `DOUBLE` | `FLOAT4` / `REAL`、`FLOAT8` | 单/双精度浮点 |
| `VARCHAR` | `CHAR`、`BPCHAR`、`TEXT`、`STRING` | 变长字符串 |
| `BLOB` | `BYTEA`、`BINARY`、`VARBINARY` | 变长二进制 |
| `BIT` | `BITSTRING` | 1/0 串 |
| `DATE` / `TIME` / `TIMESTAMP` / `TIMESTAMPTZ` | `DATETIME` / `TIMESTAMPTZ` | 日期时间家族；`TIMESTAMPTZ` 用当前时区解释 |
| `INTERVAL` | — | 日期时间差 |
| `UUID` | — | 128 位 UUID |
| `JSON` | — | 经 `json` 扩展的 JSON 类型 |
| `GEOMETRY` | — | 地理空间实体，经 `spatial` 扩展 |

类型之间大量支持隐式转换，规则见官方 Typecasting 页；`HUGEINT` 让「超出 int64 的 ID、雪花、金额累加」不需要迁到字符串或 `DECIMAL`，这是 DuckDB 与主流引擎的一个安静但实用的差异。

## Nested Types

七种嵌套类型，规则各不相同：

| 类型 | 语义 | 字面量 | DDL |
| :--- | :--- | :--- | :--- |
| `ARRAY` | 定长、同类型有序序列，每行元素数相同 | `[1, 2, 3]` | `INTEGER[3]` |
| `LIST` | 变长、同类型有序序列，每行元素数可不同 | `[1, 2, 3]` | `INTEGER[]` |
| `STRUCT` | 命名字段字典，每行键集合相同、值类型可异 | `{'i': 42, 'j': 'a'}` | `STRUCT(i INTEGER, j VARCHAR)` |
| `MAP` | 字典，key 同型、value 同型，各行可有不同键 | `map([1, 2], ['a', 'b'])` | `MAP(INTEGER, VARCHAR)` |
| `TUPLE` | 按位置访问的未命名序列 | `(42, 'a')` | `TUPLE(INTEGER, VARCHAR)` |
| `UNION` | 多选一，带 tag 记录当前成员类型 | `union_value(num := 2)` | `UNION(num INTEGER, text VARCHAR)` |
| `VARIANT` | 半结构化，**每个值自带类型信息**，行间类型可不同 | `42::VARIANT` | `VARIANT` |

要点：

- **任意深度嵌套**：`LIST` 套 `STRUCT` 套 `MAP` 合法，只要各自类型规则成立。存储与执行层的向量布局（递归 child）见 [Execution_Engine](/docs/CS/DB/DuckDB/Execution_Engine.md)。
- **大小写规则不一致且会咬人**：`MAP` 的 key **大小写敏感**，`STRUCT` 与 `UNION` 的 key **大小写不敏感**。从 JSON 导入 MAP 后按大小写查键，行为与 STRUCT 不同。
- **VARIANT（2.0 一等公民）**：半结构化数据的原生归宿——每个值自带类型，查询时按值上的类型 shred 成列执行，并可直接写 Parquet。它是把「JSON 字符串列」升级成「可列化执行」的关键类型，相关函数在 `json` 扩展。
- **`GEOMETRY` / `JSON` 来自扩展**：类型系统本身保持轻量，领域类型由 `spatial` / `json` 扩展注入。

## Update Semantics Trap

DuckDB 对嵌套类型的**更新是「DELETE + INSERT」**，不是原地改值。对普通表这只是实现细节；但表上若有 ART 索引（显式索引、主键或唯一约束都会建 ART），一次 `UPDATE t SET list_col = ...` 会先删行再插行——如果新值违反唯一约束，报出的错误来自「插入」而非「更新」，且约束检查的时机与原地更新的引擎不同。官方文档在索引页专门标注了这条。写批量改嵌套列的迁移脚本时，先确认目标表的约束与索引。

## Performance Implications

类型选择对性能的影响是结构性的，官方 Performance Guide 有专章：

- 数值列优先窄类型：`INTEGER` 比 `VARCHAR` 快一个量级，`DOUBLE` 上的压缩（ALP/Chimp/Patas）比 `VARCHAR` 上的字典/FSST 省得多。
- 嵌套列的解冻有代价：`LIST`/`STRUCT` 的过滤若不能下推到 child，会把整行物化。
- `TIMESTAMPTZ` 的时区解释依赖 icu 扩展（2.0 起自包含实现）；跨时区数据显式用 `TIMESTAMP` + UTC 约定，比依赖会话时区更稳。
- `VARIANT`/`JSON` 换取灵活性，代价是查询计划里多一层 shred；纯分析负载应尽量在建表时定型。

## Links

- [DuckDB](/docs/CS/DB/DuckDB.md)
- [Execution Engine](/docs/CS/DB/DuckDB/Execution_Engine.md)
- [Extensions](/docs/CS/DB/DuckDB/Extensions.md)
- [Indexes](/docs/CS/DB/Index.md)
- [SQLite Type System](/docs/CS/DB/SQLite/Type_System.md)

## References

1. [DuckDB Data Types Overview](https://duckdb.org/docs/2.0/sql/data_types/overview.html)
2. [DuckDB VARIANT Type](https://duckdb.org/docs/2.0/sql/data_types/variant.html)
3. [DuckDB Indexes – Constraint Checking in UPDATE Statements](https://duckdb.org/docs/2.0/sql/indexes.html)
4. [DuckDB Performance Guide – Schema](https://duckdb.org/docs/2.0/guides/performance/schema.html)
