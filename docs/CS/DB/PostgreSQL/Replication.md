## Introduction

PostgreSQL 提供两类复制：物理流复制（WAL 字节级、实例级）与逻辑复制（按表、基于 WAL 解码）。本文覆盖物理备、同步复制、复制槽、逻辑复制与解码流程，以及逻辑复制的限制。

| 项 | 值 |
| :--- | :--- |
| 版本基线 | PostgreSQL 18 |
| 核实日期 | 2026-10-15 |

## Physical Streaming Replication

主库通过 WAL 流式复制把 WAL 推到 standby，备库持续 apply。备库配置：

```ini
# standby postgresql.conf
primary_conninfo = 'host=primary port=5432 user=repl password=...'
hot_standby = on
```

```bash
# 基础备份：pg_basebackup（PG 15+ 内置复制槽）
pg_basebackup -h primary -D /var/lib/pgsql/data -U repl -P -Xs -R
# -R 自动生成 standby.signal 与 primary_conninfo
```

`primary_slot_name` / `max_slot_wal_keep_size` 用于主备解耦，防止主库 WAL 被早期回收。

### Synchronous Replication

```ini
# primary
synchronous_standby_names = 'FIRST 1 (s1, s2)'  # 至少 1 个同步备
synchronous_commit = on
```

同步级别由 `synchronous_commit`（见 [WAL](/docs/CS/DB/PostgreSQL/WAL.md)）与 `synchronous_standby_names` 共同决定。`FIRST n` / `ANY n` 控制"几个备确认即可提交"。

## Logical Replication

```ini
wal_level = logical
max_replication_slots = 10
max_wal_senders = 10
```

```sql
-- 发布端
CREATE PUBLICATION pub_orders FOR TABLE orders;
-- 订阅端
CREATE SUBSCRIPTION sub_orders
  CONNECTION 'host=primary port=5432 dbname=app'
  PUBLICATION pub_orders;
```

逻辑复制可用于跨版本升级、选择性表复制、零停机迁移。

### Logical Decoding

WAL → `XLogReadRecord` → 各 RMGR 的 `decode` 回调 → `ReorderBuffer` 按事务 ID 与 LSN 重新排序 → `pgoutput` 插件翻译为 protobuf → 订阅端 apply。实现在 `src/backend/replication/logical/`（`decode.c`/`worker.c`/`tablesync.c`）。

### Limitations

> [!NOTE]
>
> 逻辑复制的已知限制：
> - 只复制表（DDL 不复制，加列/改类型需手动在两端执行并刷新 publication）
> - 序列（sequence）不复制，备库序列不会推进
> - 被复制表需有主键或唯一复制标识（`REPLICA IDENTITY`）
> - 大事务在提交前不向订阅端 apply（decoding 在提交后开始）

## Replication Slots

复制槽（`pg_replication_slots`）防止主库回收备库尚未消费的 WAL：

- 物理槽：对应一个物理备
- 逻辑槽：对应一个 logical decoding 消费者

> [!WARNING]
>
> 未被消费的复制槽会无限堆积 WAL，撑爆 `pg_wal`——监控 `pg_replication_slots.confirmed_flush_lsn` 与 `pg_wal` 体积是运维必做项。

## Cascading and External Tools

- 级联复制：standby 可作为上游继续向更下层 standby 推送（减少主库 wal sender 压力）
- `pglogical`：第三方逻辑复制扩展，支持多主、DDL 复制、冲突解决等增强

## Links

- [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)
- [PostgreSQL Internals](/docs/CS/DB/PostgreSQL/Internals.md)
- [WAL](/docs/CS/DB/PostgreSQL/WAL.md)
- [Backup](/docs/CS/DB/PostgreSQL/Backup.md)
- [MySQL replica](/docs/CS/DB/MySQL/replica.md)

## References

1. [PostgreSQL 官方文档: Replication](https://www.postgresql.org/docs/current/replication.html)
2. [PostgreSQL 官方文档: Logical Replication](https://www.postgresql.org/docs/current/logical-replication.html)
3. [MySQL replica](/docs/CS/DB/MySQL/replica.md)
