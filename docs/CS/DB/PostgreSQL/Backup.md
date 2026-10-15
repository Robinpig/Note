## Introduction

备份恢复策略分逻辑与物理两类：逻辑备份（pg_dump）灵活但慢，物理热备（pg_basebackup）快但整库一致，工业级 PITR 依赖归档 + 专用工具。本文对比各方案并给出选择建议。

| 项 | 值 |
| :--- | :--- |
| 版本基线 | PostgreSQL 18 |
| 核实日期 | 2026-10-15 |

## Backup Matrix

| 方式 | 工具 | 特点 |
| :--- | :--- | :--- |
| 逻辑备份 | `pg_dump` / `pg_dumpall` | 单库/全局；可选择性 |
| 并行逻辑备份 | `pg_dump -j N` | 大库加速 |
| 物理热备 | `pg_basebackup` | 整库一致快照 |
| 增量 + 归档 | pgBackRest / barman / wal-g | 工业级 PITR |

```bash
pg_dump -Fc -j 4 -d appdb -f appdb.dump
pg_restore -d appdb -j 4 appdb.dump
```

## Logical Backup (pg_dump)

- `pg_dump` 单库；`pg_dumpall` 含全局对象（角色、表空间）
- 自定义格式 `-Fc` 可被 `pg_restore` 选择性恢复
- `-j N` 并行导出/导入大库
- 一致性快照在事务内完成，不影响线上写入（除 `AccessExclusive` DDL）

## Physical Backup (pg_basebackup)

`pg_basebackup` 基于流复制协议复制数据目录，得到与源一致的物理副本：

```bash
pg_basebackup -h primary -D /backup/base -U repl -P -Ft -z
```

配合 WAL 归档（见 [WAL](/docs/CS/DB/PostgreSQL/WAL.md)）即可在恢复时做 PITR。

## Industrial Tools

- **pgBackRest**：支持全量/增量/差异备份、备份保留策略、并行、压缩、云存储后端；推荐用于大库与严格 RPO/RTO
- **barman**：物理备份 + 归档管理，支持 `rsync`/流复制两种获取 WAL 方式
- **wal-g**：现代化、轻量，深度集成对象存储（S3/GCS），常用于云原生环境

> [!NOTE]
>
> 备份有效性以"能否成功恢复"为准——定期做 restore 演练（restore drill）比备份本身更重要。

## Links

- [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)
- [WAL](/docs/CS/DB/PostgreSQL/WAL.md)
- [Replication](/docs/CS/DB/PostgreSQL/Replication.md)
- [MySQL binlog](/docs/CS/DB/MySQL/binlog.md)

## References

1. [PostgreSQL 官方文档: Backup and Restore](https://www.postgresql.org/docs/current/backup.html)
2. [pgBackRest](https://pgbackrest.org/)
