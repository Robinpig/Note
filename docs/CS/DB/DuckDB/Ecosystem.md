## Introduction

DuckDB 的生态位可以一句话说完：**它是数据湖与本地文件之上的 SQL 引擎**。文件不是「导入后才能查」的客体，而是查询计划里的一等表源——`SELECT * FROM 'data.parquet'` 直接跑，`read_parquet(['a.parquet', 'b.parquet'])` 一把多文件 union，`s3://` 路径配上 `httpfs` 就是远程扫描。本页覆盖四层：本地文件格式、对象存储、湖仓表格式（Iceberg / DuckLake / Delta / Lance / Vortex）、以及反向的外部数据库 scanner。

## Local File Formats

三种主力格式的读法完全同构——文件名、`read_*` 函数、`COPY` 三条路：

```sql
SELECT * FROM 'test.csv';                       -- 文件名即表
SELECT * FROM read_csv('test.csv', header = false);
COPY tbl FROM 'test.csv' (HEADER false);
SELECT * FROM 'test.parquet';                   -- Parquet 同理
SELECT * FROM read_json('test.json');           -- JSON 同理
```

- **CSV 嗅探**：不指定 schema 时，CSV 读取器自动探测分隔符、有无表头、每列类型（含日期、布尔、NULL 表示），连压缩文件（`test.csv.gz`）都能直接读。探测规则可逐项覆盖。
- **虚拟列**：1.3.0 起 CSV/JSON/Parquet 读取器都支持 `filename` 虚拟列（行来自哪个文件）与 `file_index`（多文件读取时的零基序号）——「哪批数据有问题」这类问题靠它们回溯。
- **相对路径**：以 `file_search_path` 配置的「根目录」展开，未设置则以工作目录为基。
- **Appender**：C/C++/Go/Java/Julia/Node.js/Python/Rust 的 Appender API 绕过 SQL 直接批量灌行，比逐条 `INSERT` 快一个量级（`INSERT` 有显著的每行开销，只适合原型）。
- **写出**：`COPY (SELECT ...) TO 'out.parquet'`（或 CSV/JSON），格式由扩展名或 `FORMAT` 推断。

## Object Storage

`httpfs`（Primary 级）提供 HTTP(S) 与 S3 读写，`aws` / `azure` 分别补上 SDK 级能力与 Azure Blob 文件系统抽象。凭证不写进 SQL，走 secret 管理：

```sql
CREATE SECRET s3_secret (TYPE s3, KEY_ID '...', SECRET '...', REGION 'us-east-1');
SELECT count(*) FROM read_parquet('s3://bucket/lineitem/*.parquet');
```

2.0 的异步 I/O 主要服务这一层：远程读取的多个请求同时压在飞，与 morsel 并行叠加，官方称对 S3 类存储的查询提速显著。生产部署注意 `enable_external_access` 与 secret 的作用域——多租户嵌入场景应显式关掉外部访问。

## Lakehouse Table Formats

这是 2.0 叙事里变化最大的一块，三条路线并存。

### Apache Iceberg

`iceberg` 扩展支持两种用法，边界必须分清：

- **裸表直读**：`iceberg_scan('data/iceberg/lineitem_iceberg', allow_moved_paths = true)` 指向表的元数据路径即可读，**无需 catalog、只读**。也可以直接指定某个 manifest 文件。时间旅行用 `snapshot_from_id` / `snapshot_from_timestamp` 参数；元数据与快照用 `iceberg_metadata` / `iceberg_snapshots` 函数检视。直读的限制：需要 version hint 或显式版本号（除非开启版本猜测），且元数据只支持 gzip 压缩。
- **REST catalog 管理**：`ATTACH 'warehouse' AS my_catalog (TYPE iceberg, SECRET ..., URI 'https://catalog.example.com')` 之后，catalog 就像普通 DuckDB 数据库：`catalog.schema.table` 直接查、直接写（`INSERT`、`UPDATE`、`DELETE`、`MERGE INTO`、分区与 schema 演进见官方 Writing to Iceberg 页）。时间旅行在表上用 `AT (VERSION => ...)` / `AT (TIMESTAMP => ...)`。多数 catalog 走 OAuth2，凭证存 secret。

1.5.3 起 Iceberg 能力密集增强（该补丁版被官方称 "not an ordinary patch release"）。与 DuckLake 之间有 `iceberg_to_ducklake` 函数做**元数据级复制**——把挂接的 Iceberg catalog 变成 DuckLake 表来查，数据文件不动。

### DuckLake

`ducklake` 扩展是 DuckDB 基金会的**自研湖仓格式**：数据文件（Parquet）放对象存储，**目录（catalog）本身是一个 SQL 数据库**（可以是 DuckDB、PostgreSQL、SQLite），用 SQL 表记录 schema、快照、文件清单。1.1 随 DuckDB 2.0 发布；规范与实现在 2026-04 已按生产可用发布 v1.0。

```sql
ATTACH 'ducklake:metadata.ducklake' AS my_ducklake (DATA_PATH 'data_files');
USE my_ducklake;
FROM ducklake_snapshots('my_ducklake');         -- 快照历史（含时间、作者、commit message）
SELECT * FROM ducklake_table_insertions('my_ducklake', 'main', 'events', 1, 5);  -- 增量行
CALL ducklake_expire_snapshots('my_ducklake', older_than => now() - INTERVAL 30 DAY);
CALL ducklake_merge_adjacent_files('my_ducklake');   -- 合并小文件
```

对多进程并发写，官方指路是 **DuckLake + PostgreSQL 目录**：多个 DuckDB 实例通过中心 PostgreSQL catalog 协调，实现同一数据库的并发读写——这补上了 `.duckdb` 单文件「单写者进程」的最大短板。元数据表位于 `__ducklake_metadata_<name>` catalog，可当普通表查。

### Delta Lake 与新兴列格式

`delta` 扩展读写 Delta Lake；`lance`（Lance，ML 数据格式）、`vortex`（Vortex，Apache DataFusion 生态的新列格式）为第三方维护。这些格式的共同点是「元数据描述一批列存文件」，DuckDB 对它们一律用同一套 pushdown 式扫描框架接入。

## External Database Scanners

反向的一层：把别的数据库当表源。`postgres`、`mysql`、`sqlite` 扩展（外加 `odbc`）让 DuckDB 直接查询外部库：

```sql
ATTACH 'host=pg user=... dbname=...' AS pg (TYPE postgres);
SELECT * FROM pg.public.events WHERE ts > now() - INTERVAL 1 DAY;
```

典型用法有两类：**周期性 ETL**（把 OLTP 库的数据拉进 DuckDB / Parquet 做分析）与**联邦查询**（跨库 join 一次）。2.0 的 `CONNECT` 语句与 remote pushdown 优化器甚至能把查询推到远端 Postgres/MySQL 上执行，只取回结果。`sqlite_scanner` 与 [SQLite](/docs/CS/DB/SQLite.md) 的互通也走这条路。

## MotherDuck

MotherDuck 是 DuckDB 团队参与的云托管服务（`motherduck` 扩展接入）：本地 DuckDB 会话里 `ATTACH 'md:'` 即可查询云端库，把「本地 + 云」当成一个命名空间。对不想自建 Quack 服务器、又要多人共享同一份数据的团队，这是官方路径；自建路径见 [Operations](/docs/CS/DB/DuckDB/Operations.md) 的 Quack 一节。

## Links

- [DuckDB](/docs/CS/DB/DuckDB/DuckDB.md)
- [Extensions](/docs/CS/DB/DuckDB/Extensions.md)
- [Storage Format](/docs/CS/DB/DuckDB/Storage_Format.md)
- [Table Format](/docs/CS/BigData/Table_Format.md)
- [Lakehouse](/docs/CS/BigData/Lakehouse.md)

## References

1. [DuckDB Importing Data Overview](https://duckdb.org/docs/2.0/data/overview.html)
2. [DuckDB Iceberg Extension Overview](https://duckdb.org/docs/2.0/core_extensions/iceberg/overview.html)
3. [DuckDB DuckLake Extension](https://duckdb.org/docs/2.0/core_extensions/ducklake.html)
4. [DuckLake Documentation](https://ducklake.select/docs/stable/duckdb/introduction)
5. [New DuckDB-Iceberg Features in v1.5.3](https://duckdb.org/2026/05/29/new-duckdb-iceberg-features-in-v153)
