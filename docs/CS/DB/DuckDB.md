## Introduction

DuckDB 是一个**进程内（in-process）的 OLAP 数据库管理系统**：没有守护进程、没有监听端口，应用把它当库链接进进程，用 SQL 直接查询本地文件、Parquet 数据集乃至对象存储上的数据。官方给自己的定位是 "the SQLite for analytics"——与 SQLite 解决「单个应用在一台设备上的本地数据存储」同构，只是负载从点查换成整列聚合。它的查询语言刻意贴近 PostgreSQL，因此从 Postgres 生态迁移几乎没有语法成本。

三条常被忽略的底色：**MIT 许可、由独立的 DuckDB Foundation 治理**（不在任何单一云厂商手里）；**执行内核是向量化的**（vectorized execution），这是它与 SQLite 这类行式引擎的本质分野；**扩展即架构**——JSON、Parquet、Iceberg、HTTPS 读取这些能力全部以扩展形态动态加载，核心二进制保持轻量。

本页是 DuckDB 的**枢纽页**：只放定位、架构总览、选型与最要紧的几条反直觉事实；执行格式、存储格式、类型系统、扩展机制、数据生态、部署运维七个方向各有分册展开。版本锚点 **2.0.0 LTS（代号 Cinnamon Teal，2026-10-21）**，存储格式版本 **69**；上一个 LTS 是 **1.4.x（Andium）**，支持至 2026-11-17，1.5 的支持被延长到 2027-03 之后。所有结论以 duckdb.org 官方文档、发布公告与源码为准。

## Architecture

一次查询在 DuckDB 内部走完七段流水线，全程没有网络边界（Quack 协议除外，见 [Operations](/docs/CS/DB/DuckDB/Operations.md)）：

```
SQL 文本
  │
  ▼
Parser ── 2.0 起默认 PEG 解析器（可扩展），1.5 起 opt-in；legacy_parser 扩展保留旧语法
  │  产出 SQLStatement / QueryNode / TableRef / ParsedExpression（无类型、不查 catalog）
  ▼
Binder ── 解析 catalog、绑定表与列、解析类型、抽取聚合/窗口函数
  │
  ▼
Logical Planner ── 生成 LogicalOperator 逻辑查询树
  ▼
Optimizer ── Expression Rewriter / Filter Pushdown / Join Order（DPhyp 动态规划）/ CSE / IN 重写
  ▼
Column Binding Resolver ── 列引用解析成 DataChunk 中的下标
  ▼
Physical Plan Generator ── 逻辑树转 PhysicalOperator 树
  ▼
Execution ── push-based 向量化执行：DataChunk 沿算子树向下推
```

- **Parser 不认识数据库**：它只把文本变成语法树，表不存在、列类型未定都不报错；一切在 Binder 解决。2.0 的 PEG 解析器是「extensible SQL parser」的落地——语法本身可以用 SQL 语句扩展。
- **执行是 push-based 向量化**：所有算子按固定 2048 行一批的 Vector 处理，DataChunk（一组 Vector）从算子树顶端向下推。压缩态（dictionary、constant）的 Vector 可以一路推进执行层而不物化，这是 DuckDB 吞吐的重要来源。细节见 [Execution_Engine](/docs/CS/DB/DuckDB/Execution_Engine.md)。
- **存储按行组（row group）组织**：默认每 122,880 行一个行组，块（block）默认 256 KB，压缩只在持久化文件上默认开启。细节见 [Storage_Format](/docs/CS/DB/DuckDB/Storage_Format.md)。
- **扩展是加载功能的主要方式**：`core_functions`（内置、默认加载）提供大部分标量与聚合函数，其余能力按需 `INSTALL`/`LOAD` 或 autoload。细节见 [Extensions](/docs/CS/DB/DuckDB/Extensions.md)。
- **2.0 起内存数据库也能落盘**：持久库与内存库都支持 spilling，超过 `memory_limit` 的工作负载可以 out-of-core 完成。

## Map of This Section

七个分册对应七类问题，也对应使用 DuckDB 时七种不同的翻车方式：

- **[Architecture](/docs/CS/DB/DuckDB/Architecture.md)**——「它到底是什么形状」。进程内设计、七段编译执行流水线、push-based 向量化、out-of-core 与异步 I/O，以及与「Duck Stack」（Quack / DuckLake / Iceberg）的边界。理解所有其他分册的地图。
- **[Storage_Format](/docs/CS/DB/DuckDB/Storage_Format.md)**——「文件里到底有什么」。`DUCK` 文件头、存储版本表（64→69）、行组与块、十种压缩编码、WAL 与 checkpoint，以及 2.0「旧版读不了新文件」这条单向门。要敢把 DuckDB 当数据交换格式、或评估多进程共享文件的风险，从这页读起。
- **[Execution_Engine](/docs/CS/DB/DuckDB/Execution_Engine.md)**——「快从哪来」。Vector 与五种向量格式、`string_t` 内联、嵌套类型的向量布局、morsel 级并行、优化器规则清单。慢查询调优与阅读源码的唯一入口。
- **[Type_System](/docs/CS/DB/DuckDB/Type_System.md)**——「为什么语义和 Postgres 不完全一样」。HUGEINT/BIGNUM 等宽整型、七种嵌套类型、2.0 的 VARIANT、MAP/STRUCT/UNION 的大小写规则，以及「更新嵌套列 = 先删后插」撞上 ART 索引约束的坑。
- **[Extensions](/docs/CS/DB/DuckDB/Extensions.md)**——「功能从哪来」。安装/加载/autoload 三态、内置（statically linked）与可安装两类、primary/secondary/community 三级支持、签名与自定义仓库（2.0）。几乎所有「某个函数不存在」的问题都收敛到这页。
- **[Ecosystem](/docs/CS/DB/DuckDB/Ecosystem.md)**——「数据从哪来、到哪去」。直接查 CSV/JSON/Parquet、`filename` 虚拟列、对象存储、Iceberg 的两种用法（`iceberg_scan` 裸读与 REST catalog 读写）、DuckLake 的 SQL 目录、Delta/Lance/Vortex 与跨库 scanner。
- **[Operations](/docs/CS/DB/DuckDB/Operations.md)**——「怎么部署、怎么排障」。十一门客户端 API 的支持分层、Quack 客户端/服务器（`quack_serve`、`CONNECT`、`-serve`/`-connect`）、配置旋钮（`threads`/`memory_limit`/`checkpoint_threshold`）、单写者并发模型与文件锁、导入导出与跨大版本迁移。

## Applicable Scenarios

DuckDB 的甜点区可以用一句话概括：**数据在一台机器的磁盘或对象存储上，查询是聚合型的，且写入者是单个进程（或通过 Quack/DuckLake 协调的少数进程）**。

适合：

- **本地与边缘分析**：单机 TB 级以内的交互式 SQL，聚合、join、窗口函数开箱即用，不需要集群。
- **数据湖的查询引擎**：直接对 Parquet / Iceberg / CSV 数据集跑 SQL，`SELECT * FROM 's3://...'` 是常态用法；配合 DuckLake 可把对象存储变成可写湖仓。
- **嵌入式分析**：Python / R / Java / Go 进程内分析，pandas/Polars 数据框零拷贝经 Arrow 进出；`duckdb.sql("SELECT ... FROM df")` 直接查数据框。
- **ETL 与数据整理**：CSV/JSON 的嗅探式加载、格式互转（`COPY ... TO ... (FORMAT PARQUET)`）比通用工具快一个量级。
- **测试与原型**：`:memory:` 库 + TPC-H/TPC-DS 扩展（`dbgen`）几分钟搭出基准环境。

不适合：

- **高并发点查 OLTP**：为批量与分析优化，大量小事务不是设计目标；嵌套类型的「更新 = 删 + 插」语义也不适合高频改。
- **多进程写同一个 `.duckdb` 文件**：文件格式只支持单写者进程（2.0 前完全不支持多进程写；2.0 起多进程写经由 Quack）。稳定方案是 DuckLake + PostgreSQL 目录。
- **需要共享状态的多节点集群**：DuckDB 本身不做分片与共识，那是 TiDB/CockroachDB 的世界；它的答案是「单机够快 + 数据在湖上」。

| 条件 | 选择 |
| :--- | :--- |
| 查询以整列聚合为主，单机数据量可容纳 | DuckDB |
| 数据在对象存储上，要免搬运直接查 | DuckDB + Parquet/Iceberg |
| 多进程并发写同一份数据 | DuckLake + PostgreSQL 目录，或换客户端/服务器数据库 |
| 高并发点查、低延迟事务 | PostgreSQL / MySQL |

## Facts Worth Pinning Down

最容易被默认值与版本坑到的几条，完整清单散布在各分册：

1. **2.0 新建的文件，1.x 读不了**（报 `we can only read versions between 64 and 68`）。存储格式从 0.10 起向后兼容、2.0 起不再向前兼容；回退需求用 `SET storage_compatibility_version = 'v1.4.0'` 写旧格式。这是本库所有 DB 笔记里最硬的一条版本断点。
2. **默认 `threads` = CPU 核数、`memory_limit` = 物理内存 80%**。嵌入式场景里这两个默认值经常直接撞穿容器配额，部署时必须显式收紧。
3. **多进程写同一个 `.duckdb` 不被支持**（2.0 前完全不行，2.0 起走 Quack）；单进程内多写者靠 MVCC + 乐观并发控制，改同一行后者直接报 `Transaction conflict`，重跑即可。
4. **追加永不冲突**：同一张表上的并发 `INSERT`/`Appender` 不会冲突——这是它为批量加载优化的直接证据。
5. **WAL 自动 checkpoint 阈值只有 16 MiB**（`wal_autocheckpoint`），频繁小写入会看到 `.wal` 文件反复增长再被吸收，属正常行为。
6. **压缩只对持久化文件默认开启**；`:memory:` 库不压缩，除非 `ATTACH ... (COMPRESS)`。
7. **ICU 不再是库依赖**：2.0 起时区、日历、排序由 icu 扩展自包含实现（IANA 数据压缩至约 45 KB 内置），链接体积与许可顾虑一并消失。
8. **嵌套列更新 = DELETE + INSERT**：对带 ART 索引（主键/唯一约束）的表改嵌套列，可能触发意料之外的约束冲突。

## Links

- [SQLite](/docs/CS/DB/SQLite.md)
- [ClickHouse](/docs/CS/DB/ClickHouse.md)
- [DB](/docs/CS/DB/DB.md)
- [WAL](/docs/CS/DB/WAL.md)
- [Table Format](/docs/CS/BigData/Table_Format.md)

## References

1. [Announcing DuckDB 2.0.0 LTS "Cinnamon Teal"](https://duckdb.org/2026/10/21/announcing-duckdb-200)
2. [DuckDB Release Calendar](https://duckdb.org/release_calendar)
3. [DuckDB Documentation – Storage Versions and Format](https://duckdb.org/docs/2.0/internals/storage.html)
4. [DuckDB Documentation – Overview of Internals](https://duckdb.org/docs/2.0/internals/overview.html)
5. [DuckDB Documentation – Concurrency](https://duckdb.org/docs/current/connect/concurrency.html)
6. [duckdb/duckdb source: storage_info.hpp](https://github.com/duckdb/duckdb/blob/main/src/include/duckdb/storage/storage_info.hpp)
