## Introduction

一个 PostgreSQL 实例由共享内存与多个后台进程协作构成。`postgres` 进程派生出 `postmaster` 主进程，以及若干 worker / 后台进程。本文覆盖进程模型、共享内存与数据目录结构（源码级细节见 [PostgreSQL Internals](/docs/CS/DB/PostgreSQL/Internals.md)）。

| 项 | 值 |
| :--- | :--- |
| 版本基线 | PostgreSQL 18 |
| 连接模型 | one-process-per-connection（多进程） |
| 核实日期 | 2026-10-15 |

## Process Model

| 进程 | 作用 |
| :--- | :--- |
| postmaster | 主进程，监听连接、派生 backend |
| backend | 每个客户端连接对应一个后端进程 |
| WAL writer | 刷 WAL 缓冲到磁盘 |
| Checkpointer | 周期性做 checkpoint（见 [WAL](/docs/CS/DB/PostgreSQL/WAL.md)） |
| Autovacuum launcher + workers | 自动 VACUUM / ANALYZE（见 [Vacuum](/docs/CS/DB/PostgreSQL/Vacuum.md)） |
| Background writer | 将脏页刷到磁盘 |
| Stats collector | 收集会话/表/索引统计信息 |
| Logical replication launcher | 逻辑复制 worker 派生器 |
| Archiver | WAL 归档 |

> [!NOTE]
>
> 多进程模型稳定性高、调试简单，但连接数膨胀时内存吃紧——每个 backend 私有的 relcache/syscache 与 MemoryContext 会随连接数线性增长。高并发前务必在前面加 [连接池（pgbouncer）](/docs/CS/DB/PostgreSQL/HA.md)。

## Shared Memory

- **shared_buffers**：缓存表与索引的数据页，推荐设为系统内存的 25%（见 [Storage](/docs/CS/DB/PostgreSQL/Storage.md)）
- **WAL buffers**：WAL 日志的环形缓冲
- **CLOG buffers**：事务提交状态缓冲（见 [Transaction](/docs/CS/DB/PostgreSQL/Transaction.md)）
- **lock space**：锁管理器内存（见 [Lock](/docs/CS/DB/PostgreSQL/Lock.md)）
- **predicate locks**：可串行化隔离级别的谓词锁

## Data Directory Structure

```
$PGDATA/
├── base/<dboid>/         # 普通表与索引的数据文件（按 relfilenode 命名）
├── global/               # 集群级系统表
├── pg_wal/               # WAL 日志（PG 10 前为 pg_xlog）
├── pg_xact/              # 事务提交状态（PG 10 前为 pg_clog）
├── pg_multixact/         # 多事务状态
├── pg_subtrans/          # 子事务状态
├── pg_stat/              # 统计信息
├── pg_snapshots/         # 导出快照
├── pg_notify/            # LISTEN/NOTIFY 队列
├── pg_serial/            # 序列
├── pg_twophase/          # 两阶段事务状态
├── pg_replslot/          # 复制槽
├── pg_dynshmem/          # 动态共享内存
├── postgresql.conf       # 主配置
├── pg_hba.conf           # 客户端认证
└── pg_ident.conf         # 用户映射
```

## Background Workers

`src/backend/postmaster/` 与 `src/backend/storage/bgworker/` 提供通用 worker 框架，启动顺序在 `PostmasterMain` 中：先启动 startup 回放（崩溃恢复），再 fork 自定义 `bgworkers`。除内置 bgwriter/checkpointer/autovacuum/逻辑复制 launcher 外，用户可用 `RegisterBackgroundWorker` / `RegisterDynamicBackgroundWorker` 注册自定义 worker。

## Links

- [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)
- [PostgreSQL Internals](/docs/CS/DB/PostgreSQL/Internals.md)
- [Storage](/docs/CS/DB/PostgreSQL/Storage.md)
- [WAL](/docs/CS/DB/PostgreSQL/WAL.md)
- [Vacuum](/docs/CS/DB/PostgreSQL/Vacuum.md)
- [HA](/docs/CS/DB/PostgreSQL/HA.md)

## References

1. [PostgreSQL 官方文档: Server Configuration](https://www.postgresql.org/docs/current/runtime-config.html)
2. [PostgreSQL 官方文档: The Database Cluster](https://www.postgresql.org/docs/current/creating-cluster.html)
