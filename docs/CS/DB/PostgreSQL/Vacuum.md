## Introduction

PG 是"Append-only 派"代表：旧版本完全留在数据文件里，靠 VACUUM 清理 dead tuples。VACUUM 还承担更新统计信息、冻结老 XID 两项关键职责。本文覆盖三大任务、autovacuum 机制、freeze 与 HOT。

| 项 | 值 |
| :--- | :--- |
| 版本基线 | PostgreSQL 18 |
| 核实日期 | 2026-10-15 |

## Three Major Tasks

1. **清理 dead tuples**：回收对所有事务都已不可见的旧版本数据
2. **更新统计信息**（VACUUM ANALYZE 时）
3. **冻结行 XID**：将极旧提交的 `t_xmin` 改写为 `FrozenTransactionId`（常量 2），防止 XID 回绕（见 [MVCC](/docs/CS/DB/PostgreSQL/MVCC.md)）

> [!NOTE]
>
> PG 的崩溃恢复与前映像无关——完全依赖 WAL；Oracle/MySQL 用 UNDO 既做 MVCC 也做回滚/恢复。这是两大流派的根本差异。

## Before Image Schools

| 流派 | 实现 | 代表 |
| :--- | :--- | :--- |
| Undo 派 | 数据页原地修改，旧版存专用 Undo 区 | Oracle / SQLServer / MySQL / DB2 |
| Append-only 派 | 行永不原地修改；UPDATE = 新行 + 旧行打 xmax | PostgreSQL / CockroachDB / YugabyteDB |

## Autovacuum Mechanism

`autovacuum launcher`（每 60s 醒来）决定"何时做"，但不执行；真正干活的是被 fork 的 `autovacuum worker`（一个 worker / DB）。

触发条件（任一满足）：

- 表上 dead tuples 数 > `autovacuum_vacuum_threshold + autovacuum_vacuum_scale_factor * n_live_tup`
- XID 接近 `autovacuum_freeze_max_age`，强制 VACUUM 防回绕

`do_autovacuum` 核心：加载 GUC → 遍历 `pg_class` 收集需清理的表 OID（跳过临时表、过滤 relkind）→ 每表计算 cost-based vacuum limit → `autovacuum_do_vac_analyze()`。

## vacuum_rel Internal

1. 顺序扫表，对每页：设 PD_ALL_VISIBLE，重置 VM，重建 FSM，标记 LP_DEAD
2. 有死行时确认是否 `PageRepairFragmentation` 收缩碎片
3. 更新 `pg_class.relpages/reltuples` 统计
4. 多趟 freeze：把 `t_xmin < FreezeLimit` 的行冻结为 `FrozenTransactionId`

## HOT Update

`Heap-Only Tuples`（`hio.c` + `heapam.c`）：UPDATE 产生的新版本只追加到同一页（若能容纳），避免索引膨胀，通过 `HEAP_HOT_UPDATED` / `HEAP_ONLY_TUPLE` 位标记。

## Monitoring Bloat

```sql
-- 表膨胀：dead tuple 排行
SELECT relname, pg_size_pretty(pg_relation_size(oid)),
       n_live_tup, n_dead_tup
  FROM pg_stat_user_tables
 ORDER BY n_dead_tup DESC LIMIT 10;

-- 精确膨胀率（需 contrib/pageinspect 或 pgstattuple）
SELECT * FROM pgstattuple('orders');
```

> [!WARNING]
>
> `VACUUM FULL` 重写整表（`rewriteheap.c`），独占 `ACCESS EXCLUSIVE` 锁，会阻塞所有读写，且执行期间表会膨胀到 2 倍再收缩——大表务必在维护窗口执行，或改用 `pg_repack` 在线重组。

## Links

- [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)
- [PostgreSQL Internals](/docs/CS/DB/PostgreSQL/Internals.md)
- [MVCC](/docs/CS/DB/PostgreSQL/MVCC.md)
- [Storage](/docs/CS/DB/PostgreSQL/Storage.md)
- [Transaction](/docs/CS/DB/PostgreSQL/Transaction.md)

## References

1. [PostgreSQL 官方文档: Routine Vacuuming](https://www.postgresql.org/docs/current/routine-vacuuming.html)
2. [PostgreSQL 官方文档: The Autovacuum Daemon](https://www.postgresql.org/docs/current/runtime-config-autovacuum.html)
