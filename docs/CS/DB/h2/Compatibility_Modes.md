## Introduction

H2 的兼容模式（`MODE=`）是用来「让写给 MySQL / Oracle / PostgreSQL 的 SQL 能在 H2 上跑」的机制，最常见的用途是 **CI 里用内存库跑贴近生产的方言**。但它的边界必须写在最前面：官方对每一种模式都留了同一句话——**「只实现了数据库之间差异的很小一部分」**（`features.html#compatibility_modes`）。模式改的是语法与少量语义习惯，**不改**并发模型、锁行为、成本模型与真实边界条件。

模式集合的真实来源是 `engine/Mode.java`（478-737 行的开关集）与 `engine/ModeEnum`，而 `features.html` 的每一节只列出其中一部分。以源码为准。

## Eleven Modes

`ModeEnum` 实测有 **11 个**：

```
REGULAR, STRICT, LEGACY, DB2, Derby, MariaDB, MSSQLServer, HSQLDB, MySQL, Oracle, PostgreSQL
```

**`MariaDB` 是独立模式，不是 `MySQL` 的别名**——这一点在多数二手资料里被省略。用法两种：写在 URL 上（`jdbc:h2:~/test;MODE=MySQL`）或运行时 `SET MODE MySQL`。

## REGULAR, STRICT, LEGACY

**`REGULAR`（默认）** 允许一批非标准便利行为：空的 `IN` 谓词、`TOP`、`OFFSET/LIMIT`、用 `MINUS` 代替 `EXCEPT`、把 `IDENTITY` 当数据类型、`SERIAL`/`BIGSERIAL`、`AUTO_INCREMENT`。

**`STRICT`** 关掉上面这些弃用特性，并提示「未来会更严格，不要用于生产」。官方明确建议：**在单元测试里用 STRICT**，以便暴露应用或框架代码对这些宽松行为的隐性依赖——这是本页与 CI 最直接的联系（见 [Spring Boot Test](/docs/CS/Framework/Spring_Boot/Test.md)）。

**`LEGACY`** 为 H2 1.x 时代写的应用重新打开兼容特性，但**不等于完整的 1.x 兼容**。它额外允许：MSSQL 风格的 `IDENTITY` 子句、`SMALLDATETIME`/`DATETIME`/`DATETIME2` 当作 TIMESTAMP、手工插入后回写序列、identity 的 `DEFAULT ON NULL`、Oracle 式 `CURRVAL`/`NEXTVAL`、DML 里的 `TOP`、Oracle 式 `MERGE ... WHERE`、外键自动创建唯一约束、数值与布尔互相比较、`GREATEST`/`LEAST` 忽略 NULL、`IDENTITY()` / `SCOPE_IDENTITY()`、`SYSDATE` / `SYSTIMESTAMP` / `TODAY`。

## Per-Mode Behaviors

下表是从 `Mode.java` 与文档小节里核实到的**具体差异点**，它们只在对应模式下生效：

| 模式 | 关键行为 |
| :--- | :--- |
| `DB2` | `SYSIBM.SYSDUMMY1`、带横杠的时间戳格式、`TRANSLATE` 的 2/3 参语义互换、支持 `LIMIT`、`NEXTVAL`/`CURRVAL` |
| `Derby` | `SYSIBM.SYSDUMMY1`、NULL **不 distinct**、`FOR BIT DATA` |
| `HSQLDB` | `\|\|` 与 `+` 都可做字符串串接 |
| `MSSQLServer` | `[标识符]` 引用、NULL 不 distinct、`+` 串接、`LOG` 与 `CONVERT` 参数顺序互换、`#` 前缀临时表、**表提示被丢弃**、`MONEY`/`SMALLMONEY`/`UNIQUEIDENTIFIER` 类型映射、`0x` 字面量转二进制、`TRUNCATE` 重置 identity、SELECT/UPDATE/DELETE 中可用 `TOP` |
| `MySQL` / `MariaDB` | `CREATE TABLE` 内可写 `KEY()` / `INDEX()`、浮点转整数按四舍五入、`ON DUPLICATE KEY UPDATE`、`INSERT IGNORE`（部分）、`REPLACE INTO`（部分）、CHAR 读取时右去空格、`REGEXP_REPLACE` 用 `\` 反向引用、**容忍 MySQL 表选项（含 `ENGINE=`）**、`ALTER TABLE MODIFY`、`YEAR` 映射 SMALLINT、`GROUP BY` 可用 1-based 位置、`JSON_OBJECT` 用逗号分隔键值 |
| `Oracle` | **空串等于 NULL** 且 `\|\|NULL` 返回另一操作数、全 NULL 行可视为重复（`NULLS_ALL_DISTINCT`）、`DATE` = TIMESTAMP(0)、`ALTER TABLE MODIFY COLUMN`、`NEXTVAL`/`CURRVAL` 返回 NUMERIC、`MERGE ... WHEN MATCHED ... WHERE`、`RAWTOHEX`/`HEXTORAW` 语义改写、`CHAR`/`BYTE` 长度单位、小数序列 |
| `PostgreSQL` | 系统列 `ctid` / `oid`、`LOG` 以 10 为底、`LIMIT/OFFSET`、`SERIAL`/`BIGSERIAL`、`ON CONFLICT DO NOTHING`、CHAR 结果集右补齐、**无参 `NUMERIC`/`DECIMAL` → `DECFLOAT`**、`MONEY` = NUMERIC(19,2)、`EXTRACT(DOW)` 为 0–6 且周日是 0、`UPDATE ... FROM`、`GROUP BY` 位置、`JSONB` → JSON、`OID` → INTEGER、提供 `pg_catalog` 兼容 schema；**禁用类型 `NUMBER` / `TINYINT` / `BLOB` / `VARCHAR_IGNORECASE`** |

## Identifier Case Must Be Configured Separately

这是最容易踩的一条：**大小写与排序规则不属于模式本身**，要另配 URL 开关。文档给出的推荐组合是——

| 目标库 | 推荐完整 URL 片段 |
| :--- | :--- |
| MySQL / MariaDB | `;MODE=MySQL;DATABASE_TO_LOWER=TRUE` |
| MSSQLServer | `;MODE=MSSQLServer;DATABASE_TO_LOWER=FALSE;CASE_INSENSITIVE_IDENTIFIERS=TRUE` |
| DB2 / Oracle / PostgreSQL | `;MODE=...;DEFAULT_NULL_ORDERING=HIGH` |

只写 `MODE=` 而漏掉这些，会得到「语法过了但标识符解析行为不同」的假绿测试。`DEFAULT_NULL_ORDERING` 值得单独注意：SQL 标准没有规定 NULL 在 `ORDER BY` 里的位置，Oracle/PG 系默认 NULL 最大，而 H2 默认不同——排序敏感的分页逻辑全靠这个开关对齐。

## What Modes Do Not Cover

模式**不模拟**：真实优化器与执行计划、锁与隔离行为、`RETURNING`（H2 根本没有，见 [SQL_Language](/docs/CS/DB/h2/SQL_Language.md)）、存储过程包与 PL/SQL、序列的 `CACHE`/`NOCACHE` 语义细节、以及各家独有的类型与函数全集（PG 的 JSON 函数族、Oracle 的层级查询等）。

因此合理的用法是：**把兼容模式当「语法兼容层 + CI 冒烟」，不当「生产等价物」**。真正的语义验证要靠 Testcontainers 起真库；而 H2 自身的 `INFORMATION_SCHEMA` 与 PG 的 catalog 也不是一回事（它只是提供了 `pg_catalog` 的一层薄壳）。

## 1.x to 2.x Migration

没有 `ConvertFile`、也没有 `ShrinkDatabase` 这类工具（都不存在）。正确的迁移通道在脚本层：

```sql
-- 用 1.4.x 导出
SCRIPT TO 'old.sql';
-- 2.x 导入，FROM_1X 是正解
RUNSCRIPT FROM 'old.sql' FROM_1X;
```

`FROM_1X` 会隐式打开 `QUIRKS_MODE` 与 `VARIABLE_BINARY`——后者是必需的，因为 **2.x 把 `BINARY` 改成了定长类型**（见 [SQL_Language](/docs/CS/DB/h2/SQL_Language.md) 的四条行为反转）。1.x 的 legacy `INFORMATION_SCHEMA` 只对 ≤1.4.200 的 TCP 客户端可见、无开关；MVStore 格式方面 **2.x 只认 `format:3`，打不开 1.4.x 的文件**（见 [MVStore](/docs/CS/DB/h2/MVStore.md)）。第三方还有 H2MigrationTool，但官方未做验证。

## Pitfalls

1. 以为 `MariaDB` 是 `MySQL` 的别名——它是独立模式。
2. 只写 `MODE=`、不配 `DATABASE_TO_LOWER` / `CASE_INSENSITIVE_IDENTIFIERS` / `DEFAULT_NULL_ORDERING`。
3. 以为 STRICT 能上生产：官方自己写「未来会更严格，勿用于生产」。
4. 把兼容模式当语义等价：PG 模式下 `NUMERIC` 无参会变成 `DECFLOAT`，这类差异正是模式的作用范围，但也说明模式改的是**类型映射与语法**，不是行为全貌。
5. 用 `LEGACY` 当「完整 1.x 兼容」——文档明说不是。

## Links

- [H2](/docs/CS/DB/h2/H2.md)
- [SQL Language](/docs/CS/DB/h2/SQL_Language.md)
- [Connection and Servers](/docs/CS/DB/h2/Connection_and_Servers.md)
- [Tools and Operations](/docs/CS/DB/h2/Tools_and_Operations.md)
- [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)
- [MySQL](/docs/CS/DB/MySQL/MySQL.md)

## References

1. [H2 Database Engine - Compatibility](https://h2database.com/html/features.html)
2. [H2 Database Engine - Migrating to Version 2](https://h2database.com/html/migration-to-v2.html)
3. [H2 Database Engine - Commands](https://h2database.com/html/commands.html)
4. [H2 source at tag 2.5.252: org/h2/engine/Mode.java](https://github.com/h2database/h2/blob/2.5.252/src/main/h2/org/h2/engine/Mode.java)
