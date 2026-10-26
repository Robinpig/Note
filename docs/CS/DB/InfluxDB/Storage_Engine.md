## Introduction

InfluxDB 3 的存储层是 FDAP 栈的落地：内存里是 Apache Arrow 列式，落盘是 Apache Parquet 文件，对象存储是唯一（或主要）的持久层。3.11 起 Enterprise 换上了全新的 upgraded storage engine（内部代号 PachaTree），与 Core 的纯 Parquet 路线并存。本页讲文件布局、压缩编码、compaction 策略与查询剪枝。

## Core Parquet Path

Core 的持久化路径就是 Arrow buffer 直接序列化：每个 measurement 在内存里维护 Arrow RecordBatch，snapshot 时按 `(tag set, timestamp)` 排序后写成 Parquet 文件上传对象存储。

Parquet 文件内部布局：

- tag 列、各 field 列、timestamp 列各自独立存放；
- 行按 `(tag set, timestamp)` 排序，相同 tag 组合的序列连续排列，利于时间范围扫描与字典压缩；
- 文件级时间范围元数据让 Querier **在读之前**就能跳过不匹配的文件。

## Enterprise Upgraded Storage Engine

Enterprise 从 3.11 起默认使用新存储引擎（2026-10 的 3.12 持续增强），迁移与运行机制：

- **新集群默认启用**：存储模式持久化在 catalog 里，新集群建 catalog 时直接标记为新引擎，无用户可见的开关；
- **存量集群迁移**：`--upgrade-pacha-tree`（环境变量 `INFLUXDB3_UPGRADE_PACHA_TREE`）把 catalog 切到 hybrid 模式并开始迁移；进入迁移态后永远跑新引擎，没有回头路；
- **Core 保持 Parquet-only**——这是 Core 与 Enterprise 在存储层最大的分界。

与 Core Parquet 的差异：

| 维度 | Core Parquet | Enterprise upgraded engine |
| :-- | :-- | :-- |
| 持久化格式 | Apache Parquet | 自研时序列式格式（导出仍为 Parquet） |
| 排序键 | tag set + timestamp | column family key + series key + timestamp |
| 二级 compaction | 无 | L1 / L2 两级，time-disjoint 布局 |
| 单序列长期索引 | 有限（数天内） | 内置索引，月/年级历史查询 |
| 执行计划节点 | DataFusion 原生 | `PachaTreeWindowExec` / `PachaTreeBufferExec` |

Cloud Serverless / Cloud Dedicated / Clustered 与 Core 一致用 Parquet；Enterprise 的 compacted 数据导出为 Parquet，Spark、DuckDB、Snowflake 或一个 pandas 脚本可以直接读同一份文件，不需要 ETL 管道。

## Compression

列式存储按数据类型分别选编码，而不是全局统一：

| 数据 | 编码 |
| :-- | :-- |
| timestamp | delta-delta run-length encoding |
| float | Gorilla（XOR 浮点压缩） |
| 低基数字符串 | dictionary encoding |

时序数据的时间戳高度规律、浮点值变化缓慢、tag 值高度重复——三种编码各打各的点。官方口径是相比 1.x/2.x 的 TSM 存储成本降低 90% 以上。

## Compaction

摄入产生的小文件不合并，长范围查询就要 open 成千上万个文件。Compactor 的职责就是持续把小文件合并成大 generation：

- **Core**：单节点 compaction，Querier 扫描时触发后台合并，输出覆盖对象存储上的原路径。
- **Enterprise Parquet 引擎**：compaction 吞吐受限于单 hot-tail L1 run set，leading-edge 上同时只有一个 compaction job。
- **Enterprise upgraded engine（3.11 起默认）**：time-disjoint 两级 compaction + overlapping-L1 leading-edge 并行，多个 L1 job 可同时服务 leading edge，摄入吞吐与 compactor 调节解耦。
- **3.12 distributed compaction**：compaction 可以水平扩展，加节点直接提升 compaction 吞吐；`--compactor-import-batch-size` 控制 bulk import 单批合并规模（默认 4GB，上限为 `--compactor-input-size-budget` 的四分之一）。

一个集群里 compact 模式的节点只能有一个（见 [Architecture](/docs/CS/DB/InfluxDB/Architecture.md) 的 server modes）。

## Query Pruning

三层剪枝保证查询不读无关数据，一层比一层细：

1. **文件级**：Parquet 文件的时间范围元数据，跳过整个不匹配文件。
2. **Row group 级**：每个 row group 带 min/max 统计，跳过无法匹配的 row group。
3. **Predicate pushdown**：DataFusion 把 `WHERE` 条件下推到 Arrow / Parquet 读取层，只拉需要的列与行。

Enterprise 新引擎多两层：

4. **Field family pruning**：过滤器能保证无关的 field family 整块跳过，`cpu::usage_user` 与 `mem::free` 的查询互不干扰。
5. **Scan predicate pushdown**：跨单 field family 扫描、union 路径、dedup 与 gap-leaf 扫描、时间谓词全链路下推。

## System Tables

查询存储自身状态用 `system.*` 表。Parquet 路线上常用 `system.parquet_files`（每张表一个行，列出文件）；upgraded engine 上是一整套 `pt_` 前缀表：

| 表 | 内容 |
| :-- | :-- |
| `system.pt_shards` | 分片布局 |
| `system.pt_compaction_files` | compaction 输入输出文件 |
| `system.pt_storage_snapshots` | snapshot 清单 |
| `system.pt_storage_checkpoints` | 检查点 |
| `system.pt_storage_run_set_indexes` | run set 索引 |
| `system.pt_ingest_wal` / `system.pt_ingest_files` | 摄入侧 WAL 与文件（3.12 起带 node_id / node_name 列） |

## Links

- [InfluxDB 枢纽](/docs/CS/DB/InfluxDB/InfluxDB.md)
- [Architecture](/docs/CS/DB/InfluxDB/Architecture.md)
- [Data_Model](/docs/CS/DB/InfluxDB/Data_Model.md)
- [WAL](/docs/CS/DB/Concept/WAL.md)
- [LSM Tree](/docs/CS/Algorithms/tree/LSM.md)

## References

1. [InfluxDB 3 Clustered Storage Engine Internals](https://docs.influxdata.com/influxdb3/clustered/reference/internals/storage-engine/)
2. [InfluxDB 3 Enterprise Release Notes](https://docs.influxdata.com/influxdb3/enterprise/release-notes/)
3. [Architecture Overview of InfluxDB 3](https://www.influxdata.com/learn/architecture-overview-of-influxdb-3)
4. [What's New in InfluxDB 3.12](https://www.influxdata.com/blog/influxdb-3-12)
