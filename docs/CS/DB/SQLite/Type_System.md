## Introduction

SQLite 是**柔性类型**（官方对照词：flexibly typed vs rigidly typed）：值的类型与值本身绑定，而不是与容器（列）绑定。声明的列类型只是**建议**——向 INTEGER 列插 `'wxyz'` 不报错，`VARCHAR(50)` 能存 2000 字符不截断。这套设计向后兼容静态类型数据库的 SQL，代价是「在 SQLite 上开发正常、移植到 PostgreSQL/MySQL 上线即炸」成了最常见的事故类型。3.37.0（2021-11-27）起的 STRICT 表是官方给出的刚性选项，但它只此一档，不改变存储类本身。

## Storage Classes

存储类比数据类型更通用——例如 INTEGER 存储类在磁盘上有 7 种长度（serial type 1~6、8/9），读入内存统一为 8 字节补码：

| 存储类 | 说明 |
| :--- | :--- |
| NULL | 空值 |
| INTEGER | 有符号整数，按大小以 0/1/2/3/4/6/8 字节存储 |
| REAL | 8 字节 IEEE 754 |
| TEXT | 按库编码（UTF-8/16）存储 |
| BLOB | 按输入原样存储 |

除 INTEGER PRIMARY KEY 列外，**任何列都可以存任何存储类**。没有独立 BOOLEAN（TRUE/FALSE 是 3.23.0 起的 1/0 别名）与 DATETIME（TEXT 存 ISO-8601、INTEGER 存 Unix 秒、REAL 存儒略日，三种自选可互转）。

## Affinity

非 STRICT 表的列按**声明类型文本**依序匹配，命中的顺序就是规则的顺序：

| 规则 | 声明类型含 | 亲和性 |
| :--- | :--- | :--- |
| 1 | `INT` | INTEGER |
| 2 | `CHAR`、`CLOB`、`TEXT` | TEXT |
| 3 | `BLOB` 或未指定类型 | BLOB |
| 4 | `REAL`、`FLOA`、`DOUB` | REAL |
| 5 | 其它 | NUMERIC |

顺序制造的意外：`CHARINT` 命中规则 1 和 2，1 优先 → INTEGER；`FLOATING POINT` 因 "POINT" 以 INT 结尾 → INTEGER（不是 REAL）；`STRING` → NUMERIC（不是 TEXT）。类型名后的括号数字被忽略，SQLite 从不强制长度。

各亲和性的转换行为：TEXT 列把插入的数字转成文本；NUMERIC/INTEGER 列把格式良好的整数字面量文本转 INTEGER、实数字面量文本转 REAL，超 64 位整数文本转 REAL，`'3.0e+5'` 存为整数 300000；REAL 列强制把整数转浮点。**INTEGER 与 NUMERIC 的唯一可见差异在 CAST**：`CAST(4.0 AS INT)` 得整数 4，`CAST(4.0 AS NUMERIC)` 保留浮点 4.0。表达式的亲和性：列引用继承列的亲和性，一旦加上运算符（包括一元 `+`）就变成无亲和性。

## Comparison and CAST

跨存储类的排序顺序：NULL 最小（且 NULL 之间也小于）；INTEGER/REAL 之间按数值比且小于 TEXT/BLOB；TEXT 小于 BLOB，TEXT 按 collation 比、BLOB 按 `memcmp` 比。比较前按序应用亲和性：一侧有数值亲和性而另一侧是 TEXT/BLOB/无 → 给另一侧上 NUMERIC；一侧 TEXT 而另一侧无 → 给另一侧上 TEXT；否则原样比。「应用亲和性」只在**不丢本质信息**时转换。

几个由此派生的陷阱：`SELECT 1='1'` 为 **false**（主流引擎都为 true）；`a IN (x,y,z)` 的右侧值一律视为无亲和性，即使它们是列值；ORDER BY 不做存储类转换；GROUP BY 中不同存储类视为不同组，但 INTEGER 与 REAL 数值相等时算同一组。

## Rowid Models

行模型三种，建表时定：

- **rowid 表**（默认）：隐式 64 位 rowid；`INTEGER PRIMARY KEY` 列是 rowid 的别名，插 NULL 自动分配，按 rowid 定位是全库最快路径。
- **WITHOUT ROWID 表**（3.8.2 起）：按主键组织的聚簇索引表，适合主键窄、常按主键点查的场景；主键必须 NOT NULL。选型判据是「访问是否几乎都走主键」。
- **STRICT 表**（3.37.0 起）：只允许 `INT`、`INTEGER`、`REAL`、`TEXT`、`BLOB`、`ANY` 六种类型名，做严格类型检查、不做亲和性转换。

`AUTOINCREMENT` 与 MySQL 同名特性语义不同：它只保证单调不重用（代价是维护 `sqlite_sequence` 表）；普通 INTEGER PRIMARY KEY 删掉最大行后**会**重用 rowid。`VACUUM` 可能改变没有显式 INTEGER PRIMARY KEY 的表的 rowid。

## Quirks

官方自己列出的与主流 SQL 引擎的差异，逐条可复现：

| # | 怪癖 |
| :--- | :--- |
| 1 | 外键约束**默认不强制**（3.6.19 才引入，为存量库默认关） |
| 2 | PRIMARY KEY 通常只是 UNIQUE 约束，**允许 NULL**；例外是 INTEGER PRIMARY KEY、WITHOUT ROWID、STRICT |
| 3 | 聚合查询可含不在 GROUP BY 的非聚合列；单 `min()/max()` 时其余列取该行值；无聚合时 GROUP BY 可当 DISTINCT ON 用 |
| 4 | `upper()/lower()` 只折 ASCII（完整 Unicode 表比整个库还大）；完整支持要 `-DSQLITE_ENABLE_ICU` |
| 5 | 双引号内容不匹配有效标识符时当**字符串字面量**（兼容 MySQL 3.x）；拼错的引号标识符不报错。3.29.0 起可运行时关，3.41.0 起 CLI 默认关 |
| 6 | 关键字可作标识符：`CREATE TABLE union(true INT, with BOOLEAN)` 合法；`CREATE TABLE t(INTEGER PRIMARY KEY)` 的列名就叫 "INTEGER" 且无类型 |
| 7 | `CREATE TRIGGER AFTER INSERT ...` 创建的触发器名叫 "AFTER" 且实际是 BEFORE 触发器 |
| 8 | 可疑 SQL 不报错（Postel 定律），数百万应用依赖此行为，无法在不破坏兼容的前提下改严格 |
| 9 | 字符串中间可含 NUL 字符 |
| 10 | 逗号连接与其它 join 同优先级从左到右，仅在混用 RIGHT/FULL OUTER JOIN 与逗号连接时影响结果 |
| 11 | `SELECT 1='1'` 为 false |
| 12 | 文本列可无损存超长内容，类型检查形同虚设 |

移植到严格引擎前的自检清单就三条：开 `PRAGMA foreign_keys=ON` 跑一遍、把所有建表语句的列类型按目标方言过一遍、用 STRICT 表提前暴露第 12 条。

## Links

- [SQLite](/docs/CS/DB/SQLite.md)
- [DataBases](/docs/CS/DB/DB.md)
- [H2 SQL_Language](/docs/CS/DB/h2/SQL_Language.md)
- [MySQL Type](/docs/CS/DB/MySQL/Type.md)
- [Indexes](/docs/CS/DB/Concept/Index.md)

## References

1. [Datatypes In SQLite](https://sqlite.org/datatype3.html)
2. [Quirks, Caveats, and Gotchas In SQLite](https://sqlite.org/quirks.html)
3. [Clustered Indexes and the WITHOUT ROWID Optimization](https://sqlite.org/withoutrowid.html)
4. [CREATE TABLE](https://sqlite.org/lang_createtable.html)
