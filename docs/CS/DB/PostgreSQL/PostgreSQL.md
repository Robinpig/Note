## Introduction

[PostgreSQL](https://www.postgresql.org/)（简称 Postgres）是一个功能强大的开源对象关系型数据库系统，以其稳定性、丰富的 SQL 兼容性和可扩展性著称。自 1996 年从加州大学伯克利分校的 POSTGRES 项目演化而来，PG 经过近 30 年持续演进，被广泛认为是开源 OLTP 数据库中"最像 Oracle"的代表。

核心特性：

- 完整的 ACID 事务、严格的 SQL 标准兼容（支持 CTE、窗口函数、UPSERT、MERGE 等）
- 多版本并发控制（MVCC），读写不阻塞，写不阻塞读（见 [MVCC](/docs/CS/DB/PostgreSQL/MVCC.md)）
- 丰富的索引类型：B-Tree、Hash、GiST、SP-GiST、GIN、BRIN（见 [Index](/docs/CS/DB/PostgreSQL/Index.md)）
- 强大的扩展机制（extension）：PostGIS、pgvector、pg_stat_statements、TimescaleDB 等（见 [Extensions](/docs/CS/DB/PostgreSQL/Extensions.md)）
- 物理流复制 + 逻辑复制，原生支持主备、同步复制、级联（见 [Replication](/docs/CS/DB/PostgreSQL/Replication.md)）
- 程序语言扩展：PL/pgSQL、PL/Python、PL/Perl、PL/Tcl 等
- 表继承、声明式分区表、行级安全（RLS）、JSON/JSONB、生成列（见 [Partition](/docs/CS/DB/PostgreSQL/Partition.md)、[JSONB](/docs/CS/DB/PostgreSQL/JSONB.md)）

## Installation

### Docker

```bash
docker run -d --name postgres \
     -v pgdata_v18:/var/lib/postgresql \
     -p 5432:5432 \
     -e POSTGRES_PASSWORD=yourpassword \
     postgres:18
```

默认账号 `postgres`，默认数据库 `postgres`，默认端口 `5432`。

### Package Manager

```bash
# Debian/Ubuntu
sudo apt install postgresql postgresql-contrib

# RHEL/Fedora
sudo dnf install postgresql-server postgresql-contrib
sudo postgresql-setup --initdb
sudo systemctl enable postgresql --now
```

### Source Compilation

源码编译可指定 segment size、block size、WAL block size 等底层参数，方便定制化（见 [PostgreSQL Internals](/docs/CS/DB/PostgreSQL/Internals.md) 的 Build & Debug）。

> 生产环境建议优先使用发行版仓库中的稳定大版本（如 17），仅在需要实验新特性或内核级定制时自编译。

## Architecture Overview

一个 PG 实例由共享内存与多个后台进程协作构成：多进程模型（`postmaster` 派生 `backend`）、`shared_buffers` 缓存数据页、WAL 与 CLOG 缓冲、各类后台 worker（checkpointer/autovacuum/bgwriter/...）。数据与目录布局、连接模型代价见 [Architecture](/docs/CS/DB/PostgreSQL/Architecture.md)。

## Core Mechanisms

PG 的内部机制按子系统拆述，便于按需深入：

- 存储与 Buffer Pool：[Storage](/docs/CS/DB/PostgreSQL/Storage.md)
- 多版本与可见性：[MVCC](/docs/CS/DB/PostgreSQL/MVCC.md)
- 预写日志与崩溃恢复：[WAL](/docs/CS/DB/PostgreSQL/WAL.md)
- 事务、隔离级别与子事务：[Transaction](/docs/CS/DB/PostgreSQL/Transaction.md)
- 索引类型与 B-Tree：[Index](/docs/CS/DB/PostgreSQL/Index.md)
- 锁层级与 Fast Path：[Lock](/docs/CS/DB/PostgreSQL/Lock.md)
- VACUUM、autovacuum 与 freeze：[Vacuum](/docs/CS/DB/PostgreSQL/Vacuum.md)

## Replication, Backup and Extensions

- 物理/逻辑复制、复制槽：[Replication](/docs/CS/DB/PostgreSQL/Replication.md)
- 逻辑/物理备份与 PITR：[Backup](/docs/CS/DB/PostgreSQL/Backup.md)
- 扩展机制、hook 与 FDW：[Extensions](/docs/CS/DB/PostgreSQL/Extensions.md)
- psql、EXPLAIN 与 SQL 特性：[SQL](/docs/CS/DB/PostgreSQL/SQL.md)

## Operations and High Availability

- 调优参数与监控指标：[Performance](/docs/CS/DB/PostgreSQL/Performance.md)
- Patroni/repmgr 高可用、pgbouncer 连接池、监控：[HA](/docs/CS/DB/PostgreSQL/HA.md)

## Partitioning and Semi-Structured Data

- 声明式分区（range/list/hash、剪枝、维护）：[Partition](/docs/CS/DB/PostgreSQL/Partition.md)
- JSON/JSONB 存储差异与全文检索：[JSONB](/docs/CS/DB/PostgreSQL/JSONB.md)

## Engine Alternatives

### OrioleDB

[OrioleDB](https://www.orioledata.com/) 是 PG 兼容的新型存储引擎，由 Alexander Korotkov 等核心贡献者主导，目标解决 Heap 引擎的表膨胀问题。它：

- 采用 undo log 而非原地 UPDATE，去掉 MVCC tuple 的版本冗余
- 内建覆盖索引（covering）机制
- 无 free space map，依靠 undo 列表管理空间

### Other Storage/Distribution Extensions

- [Citus](https://www.citusdata.com/)：分布式 / 多租户分片
- [TimescaleDB](https://www.timescale.com/)：时序优化
- [PGlite](https://github.com/electric-sql/pglite)：WASM 中运行的 PG（嵌入式 / 浏览器）

## Version Notes

PG 的若干关键能力按版本逐步引入，影响"能用什么"的判断：

| 版本 | 关键能力 |
| :--- | :--- |
| 9.4 | `jsonb` 类型、逻辑解码基础 |
| 10 | 声明式分区、逻辑复制、`pg_basebackup -R` |
| 11 | LLVM JIT、存储过程（`CREATE PROCEDURE`）、并行分区扫描 |
| 12 | 内联 CTE、生成列（实验） |
| 13 | 并行 VACUUM、B-Tree 去重（`deduplicate_items`） |
| 14 | 流水线模式（pipeline）、并行查询增强 |
| 15 | `MERGE`、逻辑复制行列级过滤 |
| 16 | 逻辑复制订阅备库、`pg_stat_` 增强 |
| 17 | 增量备份（`pg_basebackup --incremental`）、JSONB 查询增强 |
| 18 | 当前写作基线（REL_18_STABLE） |

> [!NOTE]
>
> 版本断点以官方 release notes 为准；跨大版本升级前务必核对 `pg_upgrade` 兼容性与废弃特性。

## Links

- [Database 综述](/docs/CS/DB/DB.md)
- [PostgreSQL Internals（源码分析）](/docs/CS/DB/PostgreSQL/Internals.md)
- [B-Link Tree](/docs/CS/Algorithms/tree/B_Link_Tree.md)
- [MySQL Server](/docs/CS/DB/MySQL/MySQL.md)
- [Architecture](/docs/CS/DB/PostgreSQL/Architecture.md)
- [MVCC](/docs/CS/DB/PostgreSQL/MVCC.md)

## References

1. [PostgreSQL 官方文档](https://www.postgresql.org/docs/current/)
2. [PGlite - Postgres in WASM](https://github.com/electric-sql/pglite)
3. [OrioleDB](https://www.orioledata.com/)
4. [pgBackRest](https://pgbackrest.org/)
