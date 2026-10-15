## Introduction

PostgreSQL 的扩展机制（extension）是其生态强大的根源：第三方 C 代码可通过 hook 替换规划器、执行器、工具命令的行为，而无需改内核。本文覆盖扩展加载机制、可替换的 hook 点，以及常用扩展与 FDW。

| 项 | 值 |
| :--- | :--- |
| 版本基线 | PostgreSQL 18 |
| 扩展注册表 | `pg_extension` / `$sharedir/extension/<name>.control` |
| 核实日期 | 2026-10-15 |

## Loading Mechanism

扩展入口（`src/backend/utils/fmgr/` 与 `src/backend/commands/extension.c`）：

- `PG_MODULE_MAGIC` 宏：每个 `.so` 必须声明，校验 ABI 兼容
- `_PG_init`：模块加载时调用
- `PG_FUNCTION_INFO_V1`：C 函数导出
- `fmgr.c`：`fmgr_lookup` / `fmgr_builtins`

扩展注册到系统表 `pg_extension`，加载时通过 `$sharedir/extension/<name>.control` 描述。

## Pluggable Hooks

可被扩展替换的钩子（hook）是 PG 可扩展性的核心：

- `planner_hook` / `set_rel_pathlist_hook`
- `ExecutorStart_hook` / `ExecutorRun_hook`
- `ProcessUtility_hook`
- `post_parse_analyze_hook` / `object_access_hook`
- `explain_get_index_clause_hook`
- `emit_log_hook`

## Common Extensions

```sql
SELECT * FROM pg_available_extensions WHERE name LIKE 'pg%';

CREATE EXTENSION pg_stat_statements;     -- SQL 执行统计
CREATE EXTENSION pgcrypto;                -- 加密函数
CREATE EXTENSION uuid-ossp;               -- UUID
CREATE EXTENSION pg_trgm;                 -- 模糊匹配 GIN 索引
CREATE EXTENSION citext;                  -- 不区分大小写文本
CREATE EXTENSION hstore;                  -- 键值对类型
CREATE EXTENSION postgis;                 -- 地理空间
CREATE EXTENSION vector;                  -- pgvector 向量检索
```

## Foreign Data Wrappers (FDW)

FDW 让 PG 像查本地表一样查外部数据源，是扩展机制的重要应用：

- `postgres_fdw`：跨 PG 实例查询，常与 [Replication](/docs/CS/DB/PostgreSQL/Replication.md) 配合做跨库访问
- `file_fdw`：直接读 CSV/文本文件
- `mysql_fdw` / `sqlite_fdw`：对接其它数据库

`CREATE SERVER` + `CREATE USER MAPPING` + `CREATE FOREIGN TABLE` 三步即可挂载外部表；`IMPORT FOREIGN SCHEMA` 可批量导入远端 schema。

## contrib Modules

官方源码 `contrib/` 目录（如 `pg_stat_statements`、`pgcrypto`、`pageinspect`、`postgres_fdw`）随 PG 发行，是学习扩展开发的最佳范本。

## Links

- [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)
- [PostgreSQL Internals](/docs/CS/DB/PostgreSQL/Internals.md)
- [Replication](/docs/CS/DB/PostgreSQL/Replication.md)
- [pgvector 与向量检索](/docs/CS/DB/vector.md)

## References

1. [PostgreSQL 官方文档: Extensions](https://www.postgresql.org/docs/current/extend-extensions.html)
2. [PostgreSQL 官方文档: Foreign Data Wrappers](https://www.postgresql.org/docs/current/fdwhandler.html)
