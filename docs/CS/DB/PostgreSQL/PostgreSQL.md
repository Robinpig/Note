## Introduction

[PostgreSQL](https://www.postgresql.org/)（简称 Postgres）是一个功能强大的开源对象关系型数据库系统，以其稳定性、丰富的 SQL 兼容性和可扩展性著称。自 1996 年从加州大学伯克利分校的 POSTGRES 项目演化而来，PG 经过近 30 年的持续演进，被广泛认为是开源 OLTP 数据库中"最像 Oracle"的代表。

核心特性：

- 完整的 ACID 事务、严格的 SQL 标准兼容（支持 CTE、窗口函数、UPSERT、MERGE 等）
- 多版本并发控制（MVCC），读写不阻塞，写不阻塞读
- 丰富的索引类型：B-Tree、Hash、GiST、SP-GiST、GIN、BRIN
- 强大的扩展机制（extension）：PostGIS、pgvector、pg_stat_statements、TimescaleDB 等
- 物理流复制 + 逻辑复制，原生支持主备、同步复制、级联
- 程序语言扩展：PL/pgSQL、PL/Python、PL/Perl、PL/Tcl 等
- 表继承、声明式分区表、行级安全（RLS）、JSON/JSONB、生成列

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

### 包管理器

```bash
# Debian/Ubuntu
sudo apt install postgresql postgresql-contrib

# RHEL/Fedora
sudo dnf install postgresql-server postgresql-contrib
sudo postgresql-setup --initdb
sudo systemctl enable postgresql --now
```

### 源码编译

源码编译可指定 segment size、block size、WAL block size 等底层参数，方便定制化。

```dockerfile
FROM centos:7

RUN mv /etc/yum.repos.d/CentOS-Base.repo /etc/yum.repos.d/CentOS-Base.repo_bak
RUN curl -o /etc/yum.repos.d/CentOS-Base.repo https://mirrors.aliyun.com/repo/Centos-7.repo

RUN yum clean all && rm -rf /var/cache/yum/
RUN yum makecache && yum update -y

RUN yum install -y wget gcc gdb bison flex perl readline-devel zlib-devel \
                   perl-Test-Harness make systemd-devel libicu-devel

RUN useradd -m postgres && mkdir -p /home/postgres/data /home/postgres/init \
    && chown -R postgres:postgres /home/postgres

RUN mkdir /pg && cd /pg && \
    wget https://ftp.postgresql.org/pub/source/v17.4/postgresql-17.4.tar.gz && \
    tar -xf postgresql-17.4.tar.gz

RUN cd postgresql-17.4 && ./configure --enable-debug \
    --datadir=/home/postgres/init \
    --with-pgport=5432 \
    --prefix=/usr/local/pgsql \
    --with-systemd \
    --with-segsize=16 \
    --with-blocksize=8 \
    --with-wal-blocksize=8

RUN make -j8 && make install

USER postgres
RUN /usr/local/pgsql/bin/initdb -D /home/postgres/data
```

systemd 单元文件 `/etc/systemd/system/postgresql.service`：

```ini
[Unit]
Description=PostgreSQL database server
Documentation=man:postgres(1)
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
User=postgres
ExecStart=/usr/local/pgsql/bin/postgres -D /home/postgres/data
ExecReload=/bin/kill -HUP $MAINPID
KillMode=mixed
KillSignal=SIGINT

[Install]
WantedBy=multi-user.target
```

```shell
systemctl enable postgresql --now
```

> 生产环境建议优先使用发行版仓库中的稳定大版本（如 17），仅在需要实验新特性或内核级定制时自编译。

## Architecture

一个 PostgreSQL 实例由共享内存与多个后台进程协作构成。`postgres` 进程派生出一个 `postmaster` 主进程，以及若干 worker / 后台进程：

| 进程 | 作用 |
| --- | --- |
| postmaster | 主进程，监听连接、派生 backend |
| backend | 每个客户端连接对应一个后端进程（one-process-per-connection 模型） |
| WAL writer | 刷 WAL 缓冲到磁盘 |
| Checkpointer | 周期性做 checkpoint |
| Autovacuum launcher + workers | 自动 VACUUM / ANALYZE |
| Background writer | 将脏页刷到磁盘 |
| Stats collector | 收集会话/表/索引的统计信息 |
| Logical replication launcher | 逻辑复制 worker 派生器 |
| Archiver | WAL 归档 |

### 共享内存

- **shared_buffers**：缓存表与索引的数据页，PG 推荐设为系统内存的 25%
- **WAL buffers**：WAL 日志的环形缓冲
- **CLOG buffers**：事务提交状态缓冲
- **lock space**：锁管理器内存
- **predicate locks**：可串行化隔离级别的谓词锁

### 数据目录结构

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

## Storage

### Heap / Page 布局

默认存储引擎（Heap）的页面默认大小为 8 KB（编译期可通过 `--with-blocksize` 调整到 1/2/4/8/16/32 KB）。

```
+-----------+----------------+---------------+
|   Header  |   ItemPointer  |   Free Space  |
|  24 byte  |      Array     |               |
+-----------+----------------+---------------+ <-- lower
|                                                 |
|              Tuple Data                          |
|                                                 |
+-------------------------------------------------+ <-- upper
|   Special Space (索引相关)                          |
+-------------------------------------------------+
```

- Header 中包含 `pd_lsn`（页面最新 WAL LSN）、`pd_checksum`（可选）、`pd_lower`、`pd_upper`、`pd_special`
- Tuple 由 HeapTupleHeaderData（包含 `t_xmin`、`t_xmax`、`t_infomask`、`t_ctid` 等）和用户数据组成

### TOAST

超出行存储边界（默认约 2 KB）的字段会被自动拆出存到 TOAST 表，原始行只留指针。支持的存储策略可在 `ALTER TABLE ... SET STORAGE` 中设置：

- PLAIN：禁止压缩/行外
- EXTENDED：先压缩，超大再行外（默认）
- MAIN：先尝试不压缩，超大再行外
- EXTERNAL：不压缩，超大行外

### FSM / VM

- **FSM**（Free Space Map）：记录每个表文件每个页面的空闲空间大小，用于 INSERT/CTID 指针选择
- **VM**（Visibility Map）：记录每个页面上所有 tuple 是否对所有事务可见，加速 `VACUUM` 与索引-only scan

### Full Page Writes

PG 默认开启 `full_page_writes`：每次 checkpoint 后第一次修改某页时把整页写入 WAL。目的是防止在崩溃恢复时遇到半写的"撕裂页"。代价是 WAL 翻倍，常通过开启压缩（如 `wal_compression=zstd`）缓解。

## WAL & Crash Recovery

WAL（Write-Ahead Log）是 PG 的预写日志，主键字面含义：**先写日志再写数据**。任何数据页的修改，必须先把对应的 WAL record 持久化到磁盘，才能把脏页刷回。

### LSN

LSN（Log Sequence Number）是 64 位单调递增偏移量，唯一标识 WAL 中一个字节位置。`pg_lsn` 类型显示为 `XX/YY`（逻辑号/段内偏移）。

```sql
SELECT pg_current_wal_lsn();
SELECT pg_walfile_name(pg_current_wal_lsn());
```

### Checkpoint

- `checkpoint_timeout`（默认 5min）和 `max_wal_size` 触发 checkpoint
- Checkpoint 把所有脏页刷到磁盘，并把 redo 起点（`pg_control` 中的 `checkPoint`）写入控制文件
- 崩溃恢复时只需重放最后一个 checkpoint 之后的 WAL

### WAL Archiving & PITR

```ini
# postgresql.conf
wal_level = replica            # 或 logical
archive_mode = on
archive_command = 'test ! -f /pgbackup/%f && cp %p /pgbackup/%f'
```

`archive_command` 留空 + 第三方备份工具（pgBackRest、barman、wal-g）是更常见的做法。基于完整 base backup + 归档的 WAL，可以实现 PITR（Point-In-Time Recovery）：

```bash
pg_basebackup -D /backup/base -Ft -z -P
# 恢复时设置 recovery_target_time = '2026-09-12 14:00:00+08'
```

## MVCC

PG 通过在每行上保存 `xmin`（插入事务 ID）和 `xmax`（删除/更新事务 ID）实现多版本并发控制。一个事务的快照记录了当时活跃的 xid 列表，决定哪些行对它可见：

- 行 `xmin` 在快照中已提交且不在活跃集合 → 该行可见
- 行 `xmax` 未提交或属于当前事务 → 仍可见
- 行 `xmax` 已提交 → 不可见（被删除或被新版本替代，UPDATE 在 PG 中是 DELETE + INSERT）

`t_xmin` 和 `t_xmax` 占 4 字节，xid 范围 32 位（2^31 × 2），理论上每 2^31 个事务会发生回卷——PG 通过 `freeze` 机制（VACUUM FREEZE / autovacuum / `VACUUM FREEZE`）将老的 xid 替换为 `FrozenTransactionId`（2）避免回卷。

可见性判断需要读 CLOG（事务提交状态文件），因此 CLOG 必须先于数据页 fsync。

## Transaction

PG 默认隔离级别为 **Read Committed**，可通过语句或参数切换为 Repeatable Read、Serializable。

| 隔离级别 | 现象 |
| --- | --- |
| Read Uncommitted | 等价 Read Committed（PG 实现不会读到未提交数据） |
| Read Committed | 语句级快照，可能遇到不可重复读 / 幻读 |
| Repeatable Read | 事务级快照 |
| Serializable | 基于 SSI（Serializable Snapshot Isolation） |

### 子事务

> **存储引擎只有 redolog 没有 undo log**——子事务的实现是通过分配一个新的事务 ID；
> 子事务还可以继续创建子事务，构成一个树状结构。

PG 用 `pg_subtrans`（共享子事务状态文件）和 Xact 嵌套栈来维护父-子事务关系。SAVEPOINT、嵌套过程、PL/pgSQL 异常处理、JDBC 嵌套保存点都会创建子事务。

> JDBC 驱动配置了 `autosave` 需要同时配置 `cleanup_savepoints`，否则会引起性能问题——autosave 在每条语句前后插入 SAVEPOINT / RELEASE，频繁落盘 `pg_subtrans`；指定 `cleanup_savepoints` 让驱动在语句结束后一次性删除。

```java
// JDBC 示例：避免每语句 SAVEPOINT
conn.setAutoCommit(true);                  // 不开启 autosave
// 如必须使用 SAVEPOINT：
((PgConnection) conn).setAutosave(Autosave.ALWAYS);
// 推荐配合 cleanup_savepoints
((PgConnection) conn).setAutosave(Autosave.ALWAYS);
// 使用 SAVEPOINT 时务必在 finally 中 RELEASE，否则子事务堆积
```

## Index

PG 在 Heap 之上支持丰富的索引类型：

| 索引 | 默认 | 适合场景 |
| --- | --- | --- |
| B-Tree | ✅ 默认 | 范围查询、排序、等值匹配；几乎所有 OLTP 场景 |
| Hash | 否 | 仅等值；极少使用（无 WAL 写入、不能 REINDEX CONCURRENTLY 旧版） |
| GiST | 否 | 几何、IP、范围、全文搜索、hstore |
| SP-GiST | 否 | 大稀疏空间、电话号码、IP |
| GIN | 否 | JSONB、数组、tsvector（倒排索引） |
| BRIN | 否 | 时序、地理大表（块级摘要） |

```sql
-- 复合索引，列顺序遵循"等值在前、范围在后"
CREATE INDEX idx_orders_tenant_status_created
  ON orders (tenant_id, status, created_at DESC);

-- 部分索引：过滤活跃订单
CREATE INDEX idx_orders_open ON orders (created_at)
  WHERE status = 'OPEN';

-- 表达式索引
CREATE INDEX idx_users_lower_email ON users (lower(email));

-- 包含列（Index-Only Scan）
CREATE INDEX idx_orders_tenant_id ON orders (tenant_id) INCLUDE (status, created_at);

-- GIN 加速 JSONB 查询
CREATE INDEX idx_orders_attrs_gin ON orders USING GIN (attrs jsonb_path_ops);
```

## SQL

### psql 常用命令

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

### EXPLAIN

```sql
EXPLAIN (ANALYZE, BUFFERS, VERBOSE)
SELECT * FROM orders WHERE tenant_id = $1 AND created_at > now() - interval '1 day';
```

关注点：

- `Seq Scan` vs `Index Scan` / `Index Only Scan`
- `Buffers: shared hit=N` vs `read=N`：hit 说明走共享缓存
- 实际行数（`rows=N`）与估算（EXPLAIN）和统计值（ANALYZE 后）
- 节点耗时及 `* Execution time`

## Replication

### 物理流复制

主备：`primary` 通过 WAL 流式复制把 WAL 推到 `standby`，备库持续 apply。备库可配：

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

`primary_slot_name` / `max_slot_wal_keep_size` 用于主备解耦防止主库 WAL 被早期回收。

同步复制：

```ini
# primary
synchronous_standby_names = 'FIRST 1 (s1, s2)'  # 至少 1 个同步备
synchronous_commit = on
```

### 逻辑复制

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

## Backup

| 方式 | 工具 | 特点 |
| --- | --- | --- |
| 逻辑备份 | `pg_dump` / `pg_dumpall` | 单库/全局；可选择性 |
| 并行逻辑备份 | `pg_dump -j N` | 大库加速 |
| 物理热备 | `pg_basebackup` | 整库一致快照 |
| 增量 + 归档 | pgBackRest / barman / wal-g | 工业级 PITR |

```bash
pg_dump -Fc -j 4 -d appdb -f appdb.dump
pg_restore -d appdb -j 4 appdb.dump
```

## Extensions

```sql
-- 查看可用扩展
SELECT * FROM pg_available_extensions WHERE name LIKE 'pg%';

-- 常用扩展
CREATE EXTENSION pg_stat_statements;     -- SQL 执行统计
CREATE EXTENSION pgcrypto;                -- 加密函数
CREATE EXTENSION uuid-ossp;               -- UUID
CREATE EXTENSION pg_trgm;                 -- 模糊匹配 GIN 索引
CREATE EXTENSION citext;                  -- 不区分大小写文本
CREATE EXTENSION hstore;                  -- 键值对类型
CREATE EXTENSION postgis;                 -- 地理空间
CREATE EXTENSION vector;                  -- pgvector 向量检索
```

## Performance Tuning

`postgresql.conf` 关键参数：

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

调优建议：

- 高并发应用前接入 [pgbouncer](https://www.pgbouncer.org/) 等连接池，避免 backend 进程过度膨胀
- 监控 `pg_stat_statements`，定位 TOP-N 慢 SQL
- 监控表膨胀：`SELECT relname, pg_size_pretty(pg_relation_size(oid)), n_live_tup, n_dead_tup FROM pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT 10;`
- 大表更新频繁场景关闭 autovacuum 并改自定义 vacuum 窗口，或反过来上调 `autovacuum_vacuum_scale_factor`

## Engine Alternatives

### OrioleDB

[OrioleDB](https://www.orioledata.com/) 是 PG 兼容的新型存储引擎，由 Alexander Korotkov 等核心贡献者主导，目标解决 Heap 引擎的表膨胀问题。它：

- 采用 undo log 而非原地 UPDATE，去掉 MVCC tuple 的版本冗余
- 内建覆盖索引（covering）机制
- 无 free space map，依靠 undo 列表管理空间

### 其他存储/分发扩展

- [Citus](https://www.citusdata.com/)：分布式 / 多租户分片
- [TimescaleDB](https://www.timescale.com/)：时序优化
- [PGlite](https://github.com/electric-sql/pglite)：WASM 中运行的 PG（嵌入式 / 浏览器）

## Links

- [Database 综述](/docs/CS/DB/DB.md)
- [B-Link Tree](/docs/CS/Algorithms/tree/B_Link_Tree.md)
- [PostgreSQL Internals（源码分析）](/docs/CS/DB/PostgreSQL/Internals.md)

## References

1. [PostgreSQL 官方文档](https://www.postgresql.org/docs/current/)
2. [PGlite - Postgres in WASM](https://github.com/electric-sql/pglite)
3. [从源码编译安装 PostgreSQL 16.x](https://blog.frognew.com/2023/11/install-postgresql-16-from-source-code.html)
4. [OrioleDB](https://www.orioledata.com/)
5. [pgBackRest](https://pgbackrest.org/)