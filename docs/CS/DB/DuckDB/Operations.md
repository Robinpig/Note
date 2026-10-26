## Introduction

DuckDB 以进程内形态为默认，但 2.0 之后「服务器」补齐了：Quack 协议让一个 DuckDB 实例服务其他 DuckDB 实例，`CONNECT` 语句进一步统一远程入口。本页讲部署与运维的三件事：客户端 API 的支持分层、Quack 客户端/服务器的正确打开方式、配置旋钮与并发模型，最后是导入导出与跨版本迁移的标准路径。

## Client APIs

十一门客户端共享同一份磁盘格式与 SQL 语义，差异只在惯用法与支持分级：

| 客户端 | 维护方 | 分级 | 备注 |
| :--- | :--- | :--- | :--- |
| C | 核心团队 | Primary | 引擎本体 |
| CLI | 核心团队 | Primary | `duckdb` 单二进制，2.0 加 `-serve` / `-connect` / agent mode |
| Python | 核心团队 | Primary | relational API、replacement scan、直查 pandas/Polars |
| R | Kirill Müller | Primary | 社区主力接口 |
| Java (JDBC) | 核心团队 | Primary | JDBC 驱动，Spring 生态直连 |
| Go | 核心团队 | Primary | database/sql + 原生 API |
| Node.js (node-neo) | Jeff Raymakers | Primary | 新一代 Node 绑定 |
| ODBC | 核心团队 | Primary | BI 工具接入面 |
| Rust | 核心团队 | Primary | `duckdb` crate |
| WebAssembly | 核心团队 | Primary | 浏览器内 DuckDB，扩展集受限 |
| C++ | 核心团队 | Secondary | — |
| ADBC (Arrow) | 核心团队 | Secondary | Arrow Database Connectivity |
| C# (.NET) | 第三方 | Secondary | 版本跟随慢一拍 |

选型规则：Primary 客户端优先拿到新特性且有社区支持；Secondary 有特性但无支持承诺；Tertiary 无任何保证。**核心版本发布 ≠ 所有语言绑定同步就绪**——2.0 发布时官方即提醒部分客户端与扩展可能稍后跟进，嵌入式升级要逐个验证绑定版本。

## Quack: DuckDB as a Server

Quack 是 DuckDB 的原氏客户端/服务器协议，1.5.3 引入，2.0 打磨成熟（性能与稳定性大幅改进）。特殊之处在于**两端都是完整的 DuckDB 实例**：客户端访问远程库的同时，也能在本地跑计算。

```sql
-- 服务器端
CALL quack_serve(token = 'my_token');          -- 默认只听 localhost
CREATE TABLE events (date DATE, name VARCHAR);
INSERT INTO events VALUES ('2027-04-07', 'DuckCon #8');

-- 客户端
ATTACH 'quack:localhost' AS qk (TOKEN 'my_token');
CONNECT qk;                                     -- 2.0 新语句：把会话切到远程库
SELECT * FROM events;
```

运维要点：

- CLI 有快捷方式：`duckdb -serve` 起服务，`duckdb -connect` 直连。
- **默认只监听 localhost**。要对外提供服务，正确姿势是服务保持 localhost + 前面架 TLS 终止的反向代理；`allow_other_hostname` 选项把服务直接暴露，仅供测试。
- `CONNECT` 不限于 Quack：也支持 Postgres/MySQL 远程库，且 2.0 的 remote pushdown 优化器会把查询推到远端执行，而不是拉全表回来。
- 多进程写 `.duckdb` 文件在 2.0 前不支持、2.0 起经 Quack 解决；要稳定方案用 DuckLake + PostgreSQL 目录（见 [Ecosystem](/docs/CS/DB/DuckDB/Ecosystem.md)）。

## Configuration

旋钮不多，但默认值全是「单机交互式」假设，部署时必须过一遍：

| 配置 | 默认 | 说明 |
| :--- | :--- | :--- |
| `threads`（`worker_threads`） | CPU 核数 | 工作线程数；容器里先按 cgroup quota 收紧 |
| `memory_limit`（`max_memory`） | 物理内存 80% | 超限触发 out-of-core spill |
| `preserve_insertion_order` | `true` | 保序；关掉可提速但无 `ORDER BY` 时行序不保证 |
| `enable_external_access` | `true` | 是否允许访问外部状态（安装扩展、`COPY`、CSV 读取、replacement scan）；多租户嵌入应关闭 |
| `checkpoint_threshold`（`wal_autocheckpoint`） | 16 MiB | WAL 自动 checkpoint 阈值 |
| `home_directory` | 空 | 实例主目录，相对路径与扩展默认位置都相对它 |
| `extension_directory` | — | **已废弃**，改用 `extension_directories` |
| `storage_compatibility_version` | latest | 写出的存储格式版本，`'v1.4.0'` 可产出旧版可读文件 |

查询用 `SELECT current_setting('threads')` 或 `duckdb_settings()` 表；Python 侧在 `config={...}` 里传。`file_search_path` 决定相对路径的展开根。

## Concurrency and File Locks

并发模型是理解一切部署事故的钥匙：

- **一个进程读写，多个进程只读**（`access_mode='READ_ONLY'`）。读写模式下，进程内多个写线程靠 **MVCC + 乐观并发控制**协作：无写冲突时并发写全部成功；**追加（append）永不冲突**，即使同一张表；两个线程改同一行，后者报 `Transaction conflict: cannot update a table that has been altered!`，标准对策是重跑事务。
- **文件锁**：DuckDB 用文件锁仲裁访问权。共享目录（跨操作系统的不同文件系统、NAS）上要格外小心——锁语义依赖底层文件系统，网络存储上的行为不在保证范围内。
- 单写者模型的理由是**进程内缓存**：数据页、函数指针、catalog 常驻 RAM，不必每次查询回磁盘——这正是分析型负载想要的。

## Import, Export and Migration

- **批量导入**：`COPY tbl FROM 'data.csv'` / `read_parquet` / Appender API；小数据用 `INSERT`。
- **导出**：`COPY (query) TO 'out.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)`；整库导出 `EXPORT DATABASE 'dir'`（schema + 数据）。
- **跨大版本迁移**：旧版 `EXPORT DATABASE` → 新版 `IMPORT DATABASE`。**2.0 之前的版本打不开 2.0 新建的文件**，生产升级的稳妥顺序是：影子环境验证 → 显式 `storage_compatibility_version` 双写过渡 → 全量导出重建，细节见 [Storage_Format](/docs/CS/DB/DuckDB/Storage_Format.md)。
- **备份**：文件级拷贝即可（`.duckdb` + 无残留 `.wal` 时是自洽快照）；在线备份走在线备份 API 或 `VACUUM INTO` 式的一致性导出。

## Links

- [DuckDB](/docs/CS/DB/DuckDB/DuckDB.md)
- [Architecture](/docs/CS/DB/DuckDB/Architecture.md)
- [Ecosystem](/docs/CS/DB/DuckDB/Ecosystem.md)
- [Storage Format](/docs/CS/DB/DuckDB/Storage_Format.md)
- [WAL](/docs/CS/DB/Concept/WAL.md)

## References

1. [DuckDB Clients Overview](https://duckdb.org/docs/2.0/clients/overview.html)
2. [DuckDB Concurrency](https://duckdb.org/docs/current/connect/concurrency.html)
3. [DuckDB Configuration Overview](https://duckdb.org/docs/2.0/configuration/overview.html)
4. [Quack: The DuckDB Client-Server Protocol](https://duckdb.org/2026/05/12/quack-the-duckdb-client-server-protocol)
5. [Announcing DuckDB 2.0.0 LTS](https://duckdb.org/2026/10/21/announcing-duckdb-200)
