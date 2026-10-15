## Introduction

本文汇集 PostgreSQL 日常使用的 psql 元命令、EXPLAIN 解读要点，以及常用 SQL 特性。更深入的机制见各专题（[MVCC](/docs/CS/DB/PostgreSQL/MVCC.md)、[Index](/docs/CS/DB/PostgreSQL/Index.md)、[Transaction](/docs/CS/DB/PostgreSQL/Transaction.md)）。

| 项 | 值 |
| :--- | :--- |
| 版本基线 | PostgreSQL 18 |
| 核实日期 | 2026-10-15 |

## psql Common Commands

```sql
\l              -- 列出数据库
\c dbname      -- 切换数据库
\d             -- 列出表/视图/序列
\d+ tbl        -- 详细结构
\dt *.*        -- 按 schema 过滤表
\di            -- 索引
\dn            -- schema
\df            -- 函数
\dv            -- 视图
\dx            -- 扩展
\copy          -- 客户端 COPY（不是 SQL）
\timing        -- 显示语句耗时
\x             -- 扩展显示
```

## EXPLAIN

```sql
EXPLAIN (ANALYZE, BUFFERS, VERBOSE)
SELECT * FROM orders WHERE tenant_id = $1 AND created_at > now() - interval '1 day';
```

关注点：

- `Seq Scan` vs `Index Scan` / `Index Only Scan`
- `Buffers: shared hit=N` vs `read=N`：hit 说明走共享缓存（见 [Storage](/docs/CS/DB/PostgreSQL/Storage.md)）
- 实际行数（`rows=N`）与估算（EXPLAIN）和统计值（ANALYZE 后）
- 节点耗时及 `* Execution time`

## Common SQL Features

| 特性 | 说明 |
| :--- | :--- |
| CTE / 递归 | `WITH` 子句；`WITH RECURSIVE` 处理树/图 |
| UPSERT | `INSERT ... ON CONFLICT (key) DO UPDATE` |
| MERGE | PG 15+ 引入，按源表条件 INSERT/UPDATE/DELETE |
| 生成列 | `GENERATED ALWAYS AS (...) STORED` |
| 行级安全 | `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` + 策略 |
| 物化视图 | `CREATE MATERIALIZED VIEW`，`REFRESH MATERIALIZED VIEW` |

> [!NOTE]
>
> `MERGE` 在 PG 15 才正式可用（早前有 `INSERT ... ON CONFLICT` 覆盖大部分 upsert 场景）；递归 CTE 是实现闭包查询（如组织树）的惯用法。

## Links

- [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)
- [Index](/docs/CS/DB/PostgreSQL/Index.md)
- [MVCC](/docs/CS/DB/PostgreSQL/MVCC.md)
- [Transaction](/docs/CS/DB/PostgreSQL/Transaction.md)

## References

1. [PostgreSQL 官方文档: psql](https://www.postgresql.org/docs/current/app-psql.html)
2. [PostgreSQL 官方文档: EXPLAIN](https://www.postgresql.org/docs/current/using-explain.html)
