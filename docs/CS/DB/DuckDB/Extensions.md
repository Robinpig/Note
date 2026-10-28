## Introduction

DuckDB 的核心二进制刻意保持轻量：JSON、Parquet、HTTPS、Iceberg、时区这些能力**全部以扩展形态存在**。理解扩展机制是排查「某个函数不存在」「某个格式读不了」类问题的总入口。本页讲清扩展的三种形态（内置 / 可安装 / 社区）、加载语义、支持分级与签名机制，并列出 2.0 的核心扩展全景。

## Mechanism

扩展是动态加载的二进制模块，注入新函数、新类型、新文件格式乃至新语法。生命周期分两步，语义不同：

1. **安装（INSTALL）**：下载扩展二进制 + 元数据到本地扩展目录，验证签名。**只发生一次**，落盘。
2. **加载（LOAD）**：把二进制加载进运行中的 DuckDB 实例。**每次重启都要重来**——已安装 ≠ 已加载。

```sql
INSTALL AND LOAD spatial;        -- 一步到位
SELECT extension_name, installed, loaded, install_mode FROM duckdb_extensions();  -- 状态查询
UPDATE EXTENSIONS;               -- 全部已安装扩展升到最新
```

第三种路径是 **autoload**：多数核心扩展在用到的瞬间自动安装 + 加载。例如直接 `SELECT * FROM 'https://.../weather.csv'`，DuckDB 会自己装上 `httpfs`，无需任何 `INSTALL`。autoload 只覆盖核心扩展；不能 autoload 的扩展（会大改实例行为的，如 `ducklake`、`quack`）会在报错信息里点名，显式安装即可。

### Built-In Extensions

发行版二进制**静态链接**了少量内置扩展，开箱即用。最重要的一個是 `core_functions`——大部分标量与聚合函数由它提供，标准发行版（CLI 等）默认加载；最小化嵌入（自己编译、不加载任何扩展）可能需要显式 `LOAD core_functions;`，否则连 `sum()` 都找不到，`ducklake` 等扩展也会报 `Referenced table "system" not found!`。查内置清单：

```sql
SELECT extension_name FROM duckdb_extensions() WHERE install_mode = 'STATICALLY_LINKED';
```

哪些能力是内置的**随发行版而异**（Python 轮子、CLI、Wasm 各有取舍），部署到非常规环境时这第一条命令就是答案。

## Support Tiers

扩展分三级，直接决定「出问题有没有人管」：

| 级 | 范围 | 支持 |
| :--- | :--- | :--- |
| Primary | `parquet`、`json`、`icu`、`httpfs` 等 | 社区支持覆盖 |
| Secondary | 大多数 DuckDB 团队维护的扩展（`spatial`、`iceberg`、`ducklake`、`quack`……） | best-effort，但仍频繁修 bug、随版本发布 |
| Community | 第三方贡献，经中心仓库构建、签名、分发 | 无官方支持承诺 |

社区扩展的安装要显式指定仓库：`INSTALL tarfs FROM community;`。

## Signing and Custom Repositories

扩展二进制带**签名**，安装时验证——这是扩展分发安全模型的核心。2.0 引入**自定义扩展仓库**：组织可以用自己的密钥签名内部扩展，建仓时 DuckDB 会 pin 这把密钥，之后只信任该仓库里此密钥签名的二进制。对信创 / 内网环境，这条比功能本身更重要：镜像一个 `extensions.duckdb.org` 到内网 + 自签名扩展，是离线部署的标准姿势。`core` 仓库有官方镜像 `extensions.duckdb-backup.org`，主站不可用时自动回退。

## Core Extensions (2.0)

按用途分组，完整列表以 `duckdb.org/docs/2.0/core_extensions/overview.html` 为准：

| 组 | 扩展 |
| :--- | :--- |
| 格式读写 | `parquet`、`json`、`avro`、`excel`（.xlsx）、`encodings`（1000+ 字符集读 CSV）、`vortex`、`lance`、`delta` |
| 湖仓与目录 | `iceberg`、`ducklake`、`unity_catalog` |
| 远程与云 | `httpfs`（HTTP/S3）、`aws`、`azure` |
| 领域能力 | `spatial`（地理空间）、`icu`（时区/日历/排序）、`inet`（IP 类型）、`fts`（全文检索）、`vss`（向量相似度检索） |
| 外部数据库 | `postgres`、`mysql`、`sqlite`、`odbc` |
| 协议与云服务 | `quack`（DuckDB 远程协议）、`motherduck`（MotherDuck 云连接） |
| 基准与工具 | `tpch`、`tpcds`（数据生成 + 查询）、`autocomplete`（CLI 补全）、`ui`（本地 UI）、`sirius`（GPU 加速执行，third party，coming soon） |
| 兼容 | `legacy_parser`（旧 PostgreSQL 派生解析器） |

两个版本相关的事实：**macOS Intel（`osx_amd64`）在被淘汰**——2.0 的核心扩展仍为该平台构建，社区扩展已停止，2.1 起彻底放弃；`iceberg` 这类活跃扩展的更新频率高于 DuckDB 本身，`UPDATE EXTENSIONS;` 应进常规运维。

## Links

- [DuckDB](/docs/CS/DB/DuckDB/DuckDB.md)
- [Ecosystem](/docs/CS/DB/DuckDB/Ecosystem.md)
- [Operations](/docs/CS/DB/DuckDB/Operations.md)
- [Type System](/docs/CS/DB/DuckDB/Type_System.md)
- [SQLite Configuration](/docs/CS/DB/SQLite/Configuration.md)

## References

1. [DuckDB Extensions Overview](https://duckdb.org/docs/2.0/extensions/overview.html)
2. [DuckDB Core Extensions List](https://duckdb.org/docs/2.0/core_extensions/overview.html)
3. [DuckDB Extension Distribution and Signing](https://duckdb.org/docs/2.0/extensions/extension_distribution.html)
4. [DuckDB Community Extensions](https://duckdb.org/community_extensions/)
