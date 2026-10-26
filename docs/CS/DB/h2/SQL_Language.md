## Introduction

H2 的 SQL 层是它相对 SQLite / Derby 最大的优势：类型系统最完整、函数最多、扩展点最丰富。但 2.x 相对 1.x 做了**一批行为反转与功能收拢**，而网上多数资料还停在 1.x。这一页以 2.5.252 的 `datatypes.html`、`commands.html`、`grammar.html` 与源码 `command/dml/Parser.java` 为准。

## Data Types

先说最容易被写错的一条：**类型表里没有 `IDENTITY`**。它是**只在 REGULAR / LEGACY 及部分兼容模式下可用的非标准别名**，`STRICT` 模式明确禁用并指示改用 `GENERATED { ALWAYS | BY DEFAULT } AS IDENTITY`（`features.html` 各模式小节 + `migration-to-v2.html#Identity`）——是「降级为方言特性」，不是被删除。

| 类型 | 2.x 事实 | 注意 |
| :--- | :--- | :--- |
| `CHAR` / `VARCHAR` | 1 – 1,000,000,000 字符 | `CHARACTERS` / `OCTETS` 长度单位**在 H2 无效** |
| `BINARY` / `BINARY VARYING` | 定长（**无参默认 1**）/ 变长 ≤1e9 字节 | 1.x 二者是同一类型，2.x 拆开 |
| `NUMERIC` / `DECIMAL` / `DEC` | 精度 1–100000，**无参时 scale = 0**，不允许负 scale | 变长小数请用 `DECFLOAT` |
| `TIME` / `TIMESTAMP` | 分数秒 0–9；默认 TIME=0、TIMESTAMP=6 | |
| `INTERVAL` | 前导精度 1–18（默认 2），秒分数 0–9（默认 6） | |
| `ENUM` | 2.x 新类型：值不可重复、不可为空、最多 65536 个、**序数从 1 开始** | 1.x 是 0-based |
| `ARRAY` | 元素**强类型**，基数 0–65536，语法 `INTEGER ARRAY[10]` | 混合类型不再支持 → 用 `ROW` |
| `ROW (name type, ...)` | 2.x 新类型，用于取代 1.x 的混合数组 | |
| `JSON` | 2.x 新类型，RFC 8259，内部按 byte[]；`JSON 'null'` ≠ SQL NULL；保留成员顺序、允许重复键 | 见下文「JSON 支持其实很薄」 |
| `GEOMETRY` | 内部 **EWKB**，文本 WKT/EWKT（**仅子集**）；支持 POINT/LINESTRING/POLYGON/MULTI*/GEOMETRYCOLLECTION × 2D/Z/M/ZM，支持 SRID | JTS 可选：类路径有 JTS 时映射 `org.locationtech.jts.geom.Geometry`，否则 `String` |
| `JAVA_OBJECT` | ≤1e9 字节，可配 `org.h2.api.JavaObjectSerializer` | |

迁移文档自己划了线：除 `TINYINT` / `JAVA_OBJECT` / `ENUM` / `GEOMETRY` / `JSON` / `UUID` 之外，**所有非标准类型都已废弃**。

## Functions and Aggregates

聚合函数按类别（`functions-aggregate.html`）：

- **一般聚合**：`AVG` `MAX` `MIN` `SUM` `EVERY` `ANY` `COUNT` `STDDEV_POP` `STDDEV_SAMP` `VAR_POP` `VAR_SAMP` `ANY_VALUE`、位聚合 `BIT_AND_AGG`/`BIT_OR_AGG`/`BIT_XOR_AGG`/`BIT_NAND_AGG`/`BIT_NOR_AGG`/`BIT_XNOR_AGG`、以及 `ENVELOPE` `GCD_AGG` `LCM_AGG`。
- **有序聚合**：`LISTAGG`、`ARRAY_AGG`。**`GROUP_CONCAT` 仍然存在，但它只是 `LISTAGG` 的解析别名**（`Parser.java:3397` → `AggregateType.LISTAGG`），新代码只写 `LISTAGG`。
- **假想聚合**：`RANK` / `DENSE_RANK` / `PERCENT_RANK` / `CUME_DIST` 也可当聚合用。
- **逆分布聚合**：`PERCENTILE_CONT` / `PERCENTILE_DISC` / `MEDIAN` / `MODE`。
- **JSON 聚合**：`JSON_OBJECTAGG` / `JSON_ARRAYAGG`。

正则与文件类：`REGEXP_LIKE` / `REGEXP_REPLACE` / `REGEXP_SUBSTR`；表函数 `CSVREAD`、语句 `CSVWRITE`；`FILE_READ` / `FILE_WRITE` 支持 URL 与 `classpath:`（也因此属高危能力，与 `h2.allowedClasses` 联动，见 [Connection_and_Servers](/docs/CS/DB/h2/Connection_and_Servers.md)）。

**压缩函数的真名是 `COMPRESS` 与 `EXPAND`**——不存在 `DECOMPRESS`，也不存在 `COMPRESS_X` / `COMPRESS_Z`（`table/function/CompressFunction.java:22-34`，算法为 DEFLATE / LZF）。

**JSON 支持其实很薄**：只有类型 + `JSON_OBJECT` / `JSON_ARRAY` + 两个聚合，**没有 `JSON_VALUE` / `JSON_QUERY` / `JSON_TABLE` / `JSON_EXISTS`**（`Parser.java` 全文无命中）。指望它替代 PG 的 JSONB 查询是不现实的。

XML 侧有 `XMLATTR` `XMLNODE` `XMLCOMMENT` `XMLCDATA` `XMLSTARTDOC` `XMLTEXT`；方言兼容用 `DECODE` `NVL2` `CASEWHEN` `CONVERT` `ROWNUM` `TRUNCATE_VALUE`。

## Window Functions and QUALIFY

12 个窗口函数：`ROW_NUMBER` `RANK` `DENSE_RANK` `PERCENT_RANK` `CUME_DIST` `LEAD` `LAG` `FIRST_VALUE` `LAST_VALUE` `NTH_VALUE` `NTILE` `RATIO_TO_REPORT`。聚合普遍支持 `FILTER (WHERE ...)`，帧边界支持 `EXCLUDE CURRENT ROW | GROUP | TIES | NO OTHERS`。

值得单独一提的是 **`QUALIFY` 子句存在**（`commands.html` 的 SELECT 处理步骤 7；`command/query/Select.java:1474`），用于过滤窗口结果，省掉一层子查询——这个特性常被以为只有 Snowflake/Teradata 有。

## Statements

**`MERGE` 是两条不同的命令**：非标准的 `MERGE INTO t(cols) [KEY(c)] {VALUES | query}`（`Merge.java:258`）与标准的 `MERGE INTO t USING s ON ... WHEN [NOT] MATCHED THEN UPDATE/DELETE/INSERT`（文档标题写作 "MERGE USING"）。Oracle/LEGACY 模式下才有非标准的 `MERGE ... WHERE`。

方言扩展按兼容模式开关，**不在默认模式里**：

| 语法 | 可用条件 | 证据 |
| :--- | :--- | :--- |
| `INSERT ... ON CONFLICT DO NOTHING` | **仅 PostgreSQL 模式**，且**只有 `DO NOTHING`，没有 `DO UPDATE`** | `Mode.java:704`、`Parser.java:1623` |
| `ON DUPLICATE KEY UPDATE`、`INSERT IGNORE`、`REPLACE INTO` | 仅 MySQL / MariaDB 模式（部分支持） | `Mode.java` `onDuplicateKeyUpdate` |
| `UPDATE ... FROM` | 仅 PostgreSQL 模式 | `Parser.java:1007` |

**没有 `INSERT/UPDATE/DELETE ... RETURNING`**。要拿回生成的值，用数据变更增量表：

```sql
SELECT id, created_at FROM FINAL TABLE (INSERT INTO t(name) VALUES ('x'));
```

（`grammar.html:1768`；另有 `OLD TABLE(...)` / `NEW TABLE(...)`，`Parser.java:1861-1878`），或者用 JDBC 的 `getGeneratedKeys()`。迁移文档也是这么指的。

其它：**`CREATE TABLE LIKE` 不存在**，改用 `CREATE TABLE t AS (query) [WITH [NO] DATA]`；**`DELETE ... USING` 不存在**；支持 `OVERRIDING {USER|SYSTEM} VALUE` 与 `INSERT ... DIRECT query`；`TRUNCATE TABLE t [CONTINUE|RESTART] IDENTITY` 存在，但**只对无外键约束的普通表有效，链接表不能 TRUNCATE**。

`ALTER TABLE ... ALTER COLUMN` 支持的子操作：改列定义、`RENAME TO`、`SET GENERATED {ALWAYS|BY DEFAULT}`（含序列选项）、`DROP IDENTITY`、`SELECTIVITY n`、`SET/DROP DEFAULT`、`DROP EXPRESSION`、`SET/DROP ON UPDATE`、`SET/DROP DEFAULT ON NULL`、`SET NOT NULL` / `DROP NOT NULL` / `SET NULL`、`SET DATA TYPE ... USING`、`SET VISIBLE | INVISIBLE`。

## Extension Points

- **`CREATE ALIAS`**：`CREATE ALIAS [IF NOT EXISTS] name [DETERMINISTIC] FOR "class.method" | AS $$源码$$`——**支持源码即时编译**；受 `h2.allowedClasses` 与 `SET BUILTIN_ALIAS_OVERRIDE`（允许覆盖内置函数）约束。
- **自定义聚合**：`CREATE AGGREGATE name FOR className`，接口是 `org.h2.api.Aggregate`（`init` / `add` / `getResult`）或旧的 `AggregateFunction`。自定义标量函数**没有** `UserDefinedFunction` 这样的接口名。
- **Java 触发器**：实现 `org.h2.api.Trigger`，方法为 `init(Connection, schema, trigger, table, boolean before, int type)`、`fire(Connection, Object[] oldRow, Object[] newRow)`、`close()`、`remove()`——**没有 `getEnabledTopicsForTable`**。便利基类 `org.h2.tools.TriggerAdapter`。语法：`CREATE TRIGGER ... {BEFORE|AFTER|INSTEAD OF} {INSERT|UPDATE|DELETE|SELECT|ROLLBACK} ON t [FOR EACH {ROW|STATEMENT}] [QUEUE n] [NOWAIT] {CALL cls | AS 源码}`。
- **`TableEngine` 确实存在**：`org.h2.api.TableEngine`（单方法 `createTable(CreateTableData)`），配合 `CREATE TABLE ... ENGINE name [WITH (params)]` 与 `DEFAULT_TABLE_ENGINE` 选项。
- **链接表**：`CREATE LINKED TABLE [FORCE] [GLOBAL|LOCAL TEMPORARY] name(driver, url, user, pwd, [origSchema,] origTable) [EMIT UPDATES | READONLY] [FETCH_SIZE n] [AUTOCOMMIT ON|OFF]`，**没有 `MIGRATE` 选项**；`LINK_SCHEMA(targetSchema, driver, url, user, pwd, sourceSchema)` 可批量建链。
- 其它扩展接口：`JavaObjectSerializer`、`CredentialsValidator`、`DatabaseEventListener`、`UserToRolesMapper`、`H2Type`、`Interval`。

> [!NOTE]
> 「链接表做谓词下推」这个说法要精确化：真实行为是**把整条简单语句翻译成远程 SQL**（`SELECT * FROM LINK WHERE ID=1` → 远端执行 `SELECT * FROM TEST WHERE ID=?`），而**含 JOIN 的查询会被拆成多条简单查询、JOIN 在本地完成**（`advanced.html#Linked Tables`）。它是 SQL 翻译，不是优化器式的谓词下推。

## Constraints and Domains

约束只有 `PRIMARY KEY` / `UNIQUE` / `REFERENTIAL`(FK) / `CHECK` 四类，外加 `CREATE DOMAIN` / `ALTER DOMAIN`（含 `SET/DROP ON UPDATE`）与 `CREATE CONSTANT`。**没有 PostgreSQL 的 `EXCLUDE` 约束**；权限体系是 H2 自有的 `GRANT`（见 [Connection_and_Servers](/docs/CS/DB/h2/Connection_and_Servers.md)），不是标准 SQL 的细粒度权限。`MINUS` 等价 `EXCEPT`（非 STRICT 模式）。序列 `CREATE SEQUENCE` 完整支持。递归 CTE 官方标注 **experimental**。

## INFORMATION_SCHEMA

2.x 的 `INFORMATION_SCHEMA` 是**按 SQL 标准重写的**（38 个视图，含 `TABLES` `COLUMNS` `KEY_COLUMN_USAGE` `REFERENTIAL_CONSTRAINTS` `CHECK_CONSTRAINTS` `DOMAINS` `ENUM_VALUES` `ROLES` `USERS` `RIGHTS` `ROUTINES` `TRIGGERS` `SYNONYMS` `IN_DOUBT` `LOCKS` `SESSIONS` `SESSION_STATE` `SETTINGS` `QUERY_STATISTICS` 等）。

两点要记：① **没有 `SQL_` 前缀的视图**；② 1.x 的 legacy 版 `INFORMATION_SCHEMA`（`CATALOGS` / `CONSTRAINTS` / `CROSS_REFERENCES` / `FUNCTION_ALIASES` / `HELP` 等）在源码里保留，但**只对 ≤1.4.200 的旧 TCP 客户端自动可见、官方称"not documented"、没有开关可开**。表值生成还有 `RANGE(start, end[, step])`（列名 `X`）、`TABLE(X INT = 1)` / `TABLE_DISTINCT` / `UNNEST`。

## Full-Text Search

H2 自带一个全文检索模块 `org.h2.fulltext`，2.5.252 里有两个实现：**`FullText`**（原生，倒排索引存在库内的普通表里）与 **`FullTextLucene`**（需要类路径上有 Apache Lucene，构建方式见 `build.html` 的 "Using Apache Lucene" 一节）。

它不是内置语法，而是**安装进去的一组函数**，官方给出的初始化方式就是两条语句：

```sql
CREATE ALIAS IF NOT EXISTS FT_INIT FOR "org.h2.fulltext.FullText.init";
CALL FT_INIT();
```

`init` 会新建一个专用于记账的 `FT` schema（含 `FT.MAP`、`FT.ROWS` 等），并注册这些别名：

```
FT_CREATE_INDEX(schemaName, tableName, columnList)
FT_DROP_INDEX(schemaName, tableName, columnList)
FT_SEARCH(query, limit, offset)      -> result set，列为 QUERY / SCORE
FT_SEARCH_DATA(query, limit, offset) -> result set，列为 SCHEMA / TABLE / COLUMNS / KEYS / SCORE
FT_REINDEX()
FT_DROP_ALL()
```

索引的实时性靠**自动创建的触发器**维持（内部触发器名统一以 `FT_` 前缀命名），所以它是「用触发器把写入同步进倒排表」的经典做法，而不是引擎内特性。Java 侧 API 与之一一对应：`init` / `createIndex` / `dropIndex` / `reindex` / `dropAll` / `search` / `searchData`，`FullText` 另提供 `setIgnoreList`、`setWhitespaceChars`、`closeAll`。

三点判断：**能力可用但朴素**（没有短语检索、字段权重、高亮、增量分词控制这些现代搜索特性）；**索引写放大明显**（每次 DML 多一次触发器 + 倒排表更新），高吞吐写入路径上要谨慎；**需要真正的搜索语义时该走外部引擎**——把非主键维度倒排到 Elasticsearch 再回表，是同一问题的常规解法，见 [HBase 的二级索引三类补偿](/docs/CS/DB/HBase/HBase.md)。

## Not Available in H2

明确不存在、但经常被当成「H2 应该支持」的东西：**`PIVOT` / `UNPIVOT`**、**`GROUPING SETS` / `CUBE` / `ROLLUP`**、`RETURNING`、`CREATE TABLE LIKE`、`DELETE ... USING`、`COPY FROM/TO` 语句、`EXCLUDE` 约束、`JSON_VALUE/QUERY/TABLE/EXISTS`、`SELECT ... FORMAT JSON` 输出子句（`FORMAT JSON` 只是**输入值**的格式标注）。

## Pitfalls

1. `NUMERIC` 无参 = **scale 0**、`BINARY` 无参 = **定长 1**、`ENUM` 序数 **1-based**、数组**强类型**——这四条都是 1.x→2.x 的行为反转，老脚本会静默改变语义。
2. `COMPRESS/EXPAND`，不是 `DECOMPRESS`；`GROUP_CONCAT` 只是别名。
3. 无 `RETURNING`，别把 Oracle/PG 的写法带过来。
4. 方言语法（`ON CONFLICT`、`ON DUPLICATE KEY`、`UPDATE ... FROM`）依赖兼容模式，**换模式就编译不过**——CI 与生产用同一模式，见 [Compatibility_Modes](/docs/CS/DB/h2/Compatibility_Modes.md)。
5. `TRUNCATE` 遇外键或链接表会失败。

## Links

- [H2](/docs/CS/DB/h2/H2.md)
- [Compatibility Modes](/docs/CS/DB/h2/Compatibility_Modes.md)
- [Transactions and Locks](/docs/CS/DB/h2/Transactions_and_Locks.md)
- [MVStore](/docs/CS/DB/h2/MVStore.md)
- [Index](/docs/CS/DB/Concept/Index.md)
- [Tools and Operations](/docs/CS/DB/h2/Tools_and_Operations.md)

## References

1. [H2 Database Engine - Data Types](https://h2database.com/html/datatypes.html)
2. [H2 Database Engine - Commands](https://h2database.com/html/commands.html)
3. [H2 Database Engine - Aggregate Functions](https://h2database.com/html/functions-aggregate.html)
4. [H2 Database Engine - Window Functions](https://h2database.com/html/functions-window.html)
5. [H2 Database Engine - Migrating to Version 2](https://h2database.com/html/migration-to-v2.html)
