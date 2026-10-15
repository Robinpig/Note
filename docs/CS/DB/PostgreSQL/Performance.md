## Introduction

性能调优集中在 `postgresql.conf` 的内存、WAL/Checkpoint、Vacuum 与日志参数，再结合 `pg_stat_*` 监控定位瓶颈。本文给出关键参数模板、监控指标与诊断方法（详见 [Storage](/docs/CS/DB/PostgreSQL/Storage.md)、[WAL](/docs/CS/DB/PostgreSQL/WAL.md)、[Vacuum](/docs/CS/DB/PostgreSQL/Vacuum.md)）。

| 项 | 值 |
| :--- | :--- |
| 版本基线 | PostgreSQL 18 |
| 核实日期 | 2026-10-15 |

## Key Parameters

```ini
# 连接
max_connections = 200
listen_addresses = '0.0.0.0'

# 内存
shared_buffers = 8GB                  # 物理内存的 ~25%
work_mem = 64MB                       # 每个查询每操作符的临时内存
maintenance_work_mem = 1GB             # VACUUM / CREATE INDEX
huge_pages = try

# WAL / Checkpoint
wal_level = replica
wal_compression = zstd
max_wal_size = 4GB
checkpoint_timeout = 15min
checkpoint_completion_target = 0.9

# Vacuum / Autovacuum
autovacuum = on
autovacuum_vacuum_scale_factor = 0.05
autovacuum_analyze_scale_factor = 0.025

# 慢查询日志
log_min_duration_statement = 1s
log_lock_waits = on
log_temp_files = 0
```

> [!NOTE]
>
> `work_mem` 是"每操作符每查询"的内存，复杂查询（多 hash/sort 节点）可放大数倍——设过大在高并发下会撑爆内存。嵌套循环里每个 inner 节点都独立分配。

## Monitoring Metrics

| 视图 | 用途 |
| :--- | :--- |
| `pg_stat_statements` | TOP-N 慢 SQL、总耗时、缓冲命中（需启用扩展） |
| `pg_stat_activity` | 当前连接、等待事件、正在执行的 SQL |
| `pg_stat_bgwriter` | checkpoint / 后台写脏页统计 |
| `pg_stat_database` | 库级提交/回滚/冲突/块读写 |
| `pg_stat_user_tables` | 表级 live/dead tuple、seq scan 次数 |

```sql
-- 最耗时的 SQL
SELECT query, calls, total_exec_time, mean_exec_time
  FROM pg_stat_statements
 ORDER BY total_exec_time DESC LIMIT 10;
```

## Diagnostics

- 表膨胀：`n_dead_tup` 排行（见 [Vacuum](/docs/CS/DB/PostgreSQL/Vacuum.md)）
- 连接风暴：高 `max_connections` + 高并发时 backend 私有内存线性增长，应在前端加连接池（见 [HA](/docs/CS/DB/PostgreSQL/HA.md)）
- 索引缺失：`pg_stat_user_tables.seq_scan` 异常高且 `n_live_tup` 大

## Links

- [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)
- [Storage](/docs/CS/DB/PostgreSQL/Storage.md)
- [WAL](/docs/CS/DB/PostgreSQL/WAL.md)
- [Vacuum](/docs/CS/DB/PostgreSQL/Vacuum.md)
- [HA](/docs/CS/DB/PostgreSQL/HA.md)
- [MySQL Optimization](/docs/CS/DB/MySQL/Optimization.md)

## References

1. [PostgreSQL 官方文档: Resource Consumption](https://www.postgresql.org/docs/current/runtime-config-resource.html)
2. [PostgreSQL 官方文档: Monitoring](https://www.postgresql.org/docs/current/monitoring.html)
3. [MySQL Optimization](/docs/CS/DB/MySQL/Optimization.md)
