## Introduction

DuckDB 的持久化形态是「一个 `.duckdb` 文件 + 一个 `.wal` 预写日志」。本页讲清这个文件格式的内部：二进制头、存储版本表、行组与块的组织、十种压缩编码，以及 2.0 带来的格式断点。全部数字以 `src/include/duckdb/storage/storage_info.hpp` 与官方 storage 文档为准（2026-10 核实于 main 分支）。

## File Header

DuckDB 文件以一个二进制头开始，依次是：

1. `uint64_t` —— 主头校验和（main header checksum）
2. 4 个魔术字节 —— `DUCK`
3. `uint64_t` —— 存储版本号

一个容易踩的细节：**2.0.0 格式的文件在文件头位置写的是 `999`（十六进制 `e7 03`）而不是真实存储版本 69**，真实版本只记录在数据库头部内部。因此判断一个文件由哪个版本写成，不能只读文件头，正确做法是只读挂载后查 `duckdb_databases()`：

```python
con = duckdb.connect()
con.execute("ATTACH 'file.db' AS file_db (READ_ONLY)")
con.execute("SELECT tags['storage_version'] FROM duckdb_databases() WHERE database_name = 'file_db'").fetchone()[0]
```

## Storage Versions

存储格式有自己的版本线，与 DuckDB 版本多对一映射：

| 存储版本 | DuckDB 版本 |
| :--- | :--- |
| 69 | 2.0.x |
| 68 | 1.5.x |
| 67 | 1.4.x |
| 66 | 1.3.x |
| 65 | 1.2.x |
| 64 | 0.9.x、0.10.x、1.0.x、1.1.x |
| 51 | 0.8.x |
| 43 | 0.7.x |

兼容性策略分两个方向，且 **2.0 是分水岭**：

- **向后兼容**：0.10 是首个支持向后兼容的版本，此后目标是「任何更新版本都能读旧文件」——用户无需关心文件由谁写入。0.10~1.5 期间这条一直成立。
- **向前兼容**：历来只是 best effort。0.9 曾「部分」读得动 0.10 的文件。
- **2.0 起双向规则改写**：**2.0 之前的版本读不了 2.0 创建的文件**（1.5.6 报 `IO Error: Trying to read a database file with version number 69, but we can only read versions between 64 and 68`）；而 2.0 读写旧文件时，会保留这些文件对旧版本的可读性。也就是说升级不可逆，回退必须先导出。

控制写出版本的三个入口：

```sql
ATTACH 'file.db' (STORAGE_VERSION 'v1.2.0');   -- 生成旧版本可读的文件
SET storage_compatibility_version = 'v1.4.0';  -- 等价配置项
duckdb -storage-version v1.2.0 my.duckdb       -- CLI 参数
```

跨大版本迁移的标准路径：旧版 `EXPORT DATABASE 'tmp'` → 新版 `IMPORT DATABASE 'tmp'`；同大版本降格式用 `COPY FROM DATABASE`。

## Row Groups and Blocks

表数据水平切成**行组（row group）**——与 Parquet 的 row group 同构，是并行处理与压缩的基本单位。源码常量（`storage_info.hpp`）：

| 常量 | 值 | 含义 |
| :--- | :--- | :--- |
| `DEFAULT_ROW_GROUP_SIZE` | 122,880 行 | 默认行组大小，`ATTACH ... (ROW_GROUP_SIZE 16384)` 可调 |
| `DEFAULT_BLOCK_ALLOC_SIZE` | 262,144 B（256 KB） | 默认块分配大小，块头另占 8 B |
| `FILE_HEADER_SIZE` | 4096 B | 文件头大小（4 KB，与扇区对齐） |
| `MAX_ROW_GROUP_SIZE` | 2^30 行 | 行组上限 |

行组内按列存：每个列段（column segment）独立选择压缩编码，段内再按 block 落盘。这也是为什么 DuckDB 的 `.duckdb` 文件对「宽表 + 稀疏访问」友好——没被查询的列段连解压都不需要。

2.0 格式对宽表专门做了**列元数据惰性加载**：打开数据库时不再 eagerly 读全部列的元数据，大索引、宽表的打开时间与内存占用随之下降。

## Compression

压缩是 DuckDB 存储层的显学：**轻量级、按列段自动选择、默认只对持久化文件生效**（内存库要显式 `ATTACH ... (COMPRESS)`）。可用的编码取决于存储版本，用旧格式时部分编码不可用。十种编码按性质分三组：

| 组 | 编码 | 说明 |
| :--- | :--- | :--- |
| 通用 | Constant / RLE / Bit Packing / Frame of Reference | 常量、游程、位压缩、参考帧（减公共基值） |
| 字典 | Dictionary / **DICT_FSST** | 字典编码；FSST 是 VLDB 2020 的快速静态符号表，2.0 起 DICT_FSST 成为字符串列默认 |
| 浮点/科学 | Chimp / Patas / ALP | Chimp、Patas（VLDB 2022）、ALP（SIGMOD 2024，自适应无损浮点） |
| 兜底 | Zstd | 通用压缩，1.2.0 引入 |

官方给的磁盘占用参考（粗估）：**100 GB 未压缩 CSV → 约 25 GB `.duckdb`；100 GB Parquet → 约 120 GB `.duckdb`**。后一个数字常被误读为「DuckDB 压缩不如 Parquet」——Parquet 已是压缩态列存，而 `.duckdb` 以随机读与更新友好为第一目标，实际占用取决于数据类型与分布。行删除记录在 2.0 也更紧凑，读取时的损坏校验更强。

## WAL and Checkpoint

持久库伴随一个 `.wal` 文件：所有修改先写 WAL（append-only、顺序写），再由后台线程把数据合并进主文件并推进检查点。相关旋钮只有一个常用：

- `checkpoint_threshold`（别名 `wal_autocheckpoint`）：WAL 达到多大自动 checkpoint，**默认 16 MiB**。小写入多的负载会看到 `.wal` 反复涨落，属正常；调大可以摊薄 checkpoint 频率，代价是崩溃恢复时间变长。

干净关闭的数据库不应残留 `.wal`；崩溃后重开时 WAL 自动重放恢复。与 SQLite 的 WAL 不同，DuckDB 的 WAL 不参与并发读快照（并发控制在 [Operations](/docs/CS/DB/DuckDB/Operations.md) 的单写者模型里解决），它只承担崩溃恢复这一件事。

## Reading Foreign Files

判断一个 `.duckdb` 文件能否被某个 DuckDB 版本打开，记住一条规则：**存储版本号 ≤ 该版本映射表的上限即可**。1.5.x 上限 68，2.0.x 上限 69；拿 1.5.6 开 2.0 的文件必然报错，且报错信息里的版本区间就是答案。文件的真实存储版本用 `duckdb_databases()` 的 `tags['storage_version']` 查，别信文件头（2.0 写的头是 `999`）。

## Links

- [DuckDB](/docs/CS/DB/DuckDB.md)
- [Architecture](/docs/CS/DB/DuckDB/Architecture.md)
- [Operations](/docs/CS/DB/DuckDB/Operations.md)
- [WAL](/docs/CS/DB/WAL.md)
- [Table Format](/docs/CS/BigData/Table_Format.md)

## References

1. [DuckDB Internals – Storage Versions and Format](https://duckdb.org/docs/2.0/internals/storage.html)
2. [duckdb/duckdb – storage_info.hpp](https://github.com/duckdb/duckdb/blob/main/src/include/duckdb/storage/storage_info.hpp)
3. [DuckDB Configuration Overview](https://duckdb.org/docs/2.0/configuration/overview.html)
4. [Announcing DuckDB 2.0.0 LTS](https://duckdb.org/2026/10/21/announcing-duckdb-200)
