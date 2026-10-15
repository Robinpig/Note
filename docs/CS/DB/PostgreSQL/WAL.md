## Introduction

WAL（Write-Ahead Log）是 PG 的预写日志，核心语义是"先写日志再写数据"：任何数据页修改必须先持久化对应 WAL record，才能把脏页刷回。崩溃恢复只需重放最后一个 checkpoint 之后的 WAL。本文覆盖 LSN、Checkpoint、WAL 记录结构、资源管理器、归档与 PITR、崩溃恢复，以及同步提交级别。

| 项 | 值 |
| :--- | :--- |
| 版本基线 | PostgreSQL 18 |
| WAL 段大小 | 16 MB（默认） |
| 核实日期 | 2026-10-15 |

## LSN

LSN（Log Sequence Number）是 64 位单调递增偏移量，唯一标识 WAL 中一个字节位置。`pg_lsn` 类型显示为 `XX/YY`（逻辑号/段内偏移）。

```sql
SELECT pg_current_wal_lsn();
SELECT pg_walfile_name(pg_current_wal_lsn());
```

每条 WAL 记录都有自己的创建 LSN，崩溃恢复时通过比较 LSN 决定从何处开始 redo。数据页 Header 的 `pd_lsn` 记录该页最新 WAL 位置，redo 时只重放 `pd_lsn` 之后的记录。

## Checkpoint

由独立的 `checkpointer` 后台进程周期性触发（`checkpoint_timeout` 默认 5min、`max_wal_size` 阈值）：

- 把所有脏页刷到磁盘
- 把 redo 起点（`pg_control` 中的 `checkPoint`）写入控制文件
- 崩溃恢复时只需重放最后一个 checkpoint 之后的 WAL
- 按热度刷脏：usage_count 低的冷脏页优先刷盘

## WAL File Naming

WAL 文件位于 `pg_wal/`（PG 10 前为 `pg_xlog/`），默认每段 16 MB。文件名是 24 个十六进制字符，由三个字段拼接：

```
00000001 00000000 00000004
└─ timeline ┘ └─ logId ─┘ └─ logSegNo ┘
```

- timeline：TimeLineID，从 1 起，一次 promote 增加 1
- logId：逻辑日志号，PG 18 几乎固定为 0
- logSegNo：段号，从 0 起递增

## XLogRecord Structure

```
XLogRecord {
    xl_prev     64-bit  // 上一条 record 的 LSN（反向链表）
    xl_xid      32-bit  // 事务 ID
    xl_tot_len  32-bit  // 整条 record 长度
    xl_len      32-bit  // main_data 长度
    xl_info     16-bit  // flags（含 RMGR ID）
    xl_rmid     8-bit   // 资源管理器 ID
    xl_crc      32-bit  // CRC32C 校验
}
```

## Resource Manager (RMGR)

`src/backend/access/transam/rmgr.c` 维护一张数组，注册所有 RMGR：

| RMGR ID | 模块 | 作用 |
| :--- | :--- | :--- |
| `RM_XACT_ID` | xact.c | 事务提交/回滚 |
| `RM_SMGR_ID` | smgr | 表创建/截断 |
| `RM_HEAP_ID` | heap | DML/事务/INPLACE/REWRITE |
| `RM_HEAP2_ID` | heap2 | freeze 等 |
| `RM_BTREE_ID` | nbtree | 索引插入/分裂/删除 |
| `RM_LOGICALMSG_ID` | logical | 逻辑解码自定义消息 |

> [!NOTE]
>
> XLog == WAL：`XLog` 是历史命名，代码层继续沿用 XLog 字样，对外统一叫 WAL。

## Crash Recovery

`StartupXLOG`（启动期执行）：读 `pg_control` 找到最新 checkpoint → 从 redo 起点重放 WAL → 应用 ReorderBuffer 逻辑消息 → 完成一致点后切换正常模式。

## WAL Archiving and PITR

```ini
wal_level = replica            # 或 logical
archive_mode = on
archive_command = 'test ! -f /pgbackup/%f && cp %p /pgbackup/%f'
```

基于完整 base backup + 归档 WAL，可实现 PITR：

```bash
pg_basebackup -D /backup/base -Ft -z -P
# 恢复时设置 recovery_target_time = '2026-09-12 14:00:00+08'
```

> [!NOTE]
>
> `archive_command` 留空 + 第三方工具（pgBackRest、barman、wal-g）是更常见做法。`wal_level = logical` 是逻辑复制的前提（见 [Replication](/docs/CS/DB/PostgreSQL/Replication.md)）。

## Synchronous Commit Levels

`synchronous_commit` 控制事务提交时 WAL 刷盘的严格程度：

| 值 | 语义 |
| :--- | :--- |
| `off` | 不等待 WAL 落盘（异步，可能丢最近事务） |
| `local` | 等本地 WAL 落盘 |
| `on`（默认） | 等本地刷盘 + 同步备确认收到 |
| `remote_write` | 等同步备写到 OS 缓存 |
| `remote_apply` | 等同步备已 apply |

## Links

- [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)
- [PostgreSQL Internals](/docs/CS/DB/PostgreSQL/Internals.md)
- [Storage](/docs/CS/DB/PostgreSQL/Storage.md)
- [MVCC](/docs/CS/DB/PostgreSQL/MVCC.md)
- [Backup](/docs/CS/DB/PostgreSQL/Backup.md)
- [MySQL binlog](/docs/CS/DB/MySQL/binlog.md)

## References

1. [PostgreSQL 官方文档: WAL](https://www.postgresql.org/docs/current/wal.html)
2. [PostgreSQL 官方文档: Continuous Archiving and PITR](https://www.postgresql.org/docs/current/continuous-archiving.html)
3. [MySQL binlog](/docs/CS/DB/MySQL/binlog.md)
