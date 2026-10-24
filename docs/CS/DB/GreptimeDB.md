## Introduction

GreptimeDB 是开源可观测数据库，把 metrics、logs、traces 三种信号放进同一个列式引擎与共享 SQL 层。它既可以单机运行在本地存储上，也可以分布式部署、持久化到对象存储（S3、GCS、Azure Blob、OSS），把计算与存储按相互独立的规模伸缩。GreptimeDB 不是通用事务数据库——它的存储、索引、TTL、查询路径从一开始就是为 append-heavy、time-indexed 的负载（可观测性、IoT、时序分析）设计的。

当前稳定版本是 **v1.2.0**（2026-09-08 发布；v1.0 GA 于 2026-04 发布）。v1.2 的重点特性：

- **JSON2 类型**：为结构相似、查询只命中少数路径的日志 / trace / agent 事件设计——对用户仍是一个完整 JSON 对象，对存储与查询引擎则是可按路径裁剪的结构化列（嵌套路径访问、列表下标、Pipeline 转换），新表须 `append_mode`。
- **Import/Export V2**：并行导入导出、进度显示、断点续传。
- **Prometheus Remote Write v2**：支持常规 metric 样本接入。
- **Splunk HEC** 摄入路径：兼容 Splunk HTTP Event Collector 的采集端可直接写入。
- Flow 运行状态查询（`SHOW FLOW STATUS` / `information_schema.flow_statistics`）。

> [!NOTE]
> GreptimeDB 的「统一」发生在引擎、存储、查询层，**不是**强迫 metrics、logs、traces 共享同一张表、同一个 schema。每种信号仍然可以用独立的表——各自拥有不同的主键、索引、TTL、compaction 策略和存储位置。

## Architecture

GreptimeDB 采用 client/server 模型。单机模式下一个进程承担全部数据库职责；分布式模式拆成四个组件：

| 组件 | 职责 |
| :-- | :-- |
| **Metasrv** | 管理 catalog、schema、table、Region 路由、procedure 与调度元数据。单机模式用本地元数据代替。 |
| **Frontend** | 接受客户端协议请求、鉴权、规划分布式查询，基于 Metasrv 的元数据把读写路由到对应 Datanode。 |
| **Datanode** | 托管 Region、执行读写、记录 WAL、跑 compaction，把数据文件持久化到本地或对象存储。 |
| **Flownode**（可选） | 运行 Flow 计算任务——连续聚合并物化到 sink 表。 |

### Write Path

1. 客户端通过受支持的摄入协议发送数据（Prometheus remote write、OTLP、Loki、ES Bulk、MySQL/PG SQL、HTTP/gRPC）。
2. Frontend 从 Metasrv 解析目标表与 Region 路由。
3. Frontend 把请求拆片，逐行转发到持有目标 Region 的 Datanode。
4. Datanode 写入内存 memtable 与 WAL，后续 flush 把不可变 SST 文件落到配置的存储后端。

### Query Path

1. 客户端提交 SQL、PromQL（TelemetryQL）或 Jaeger 兼容 API 查询。
2. Frontend 规划查询并分发到持有相关 Region 的 Datanode。
3. Datanode 读内存数据与持久文件，本地缓存命中则走缓存，同时应用时间范围剪枝、row-group 统计剪枝与索引过滤，返回局部结果。
4. Frontend 汇总结果并返回客户端。

### Flow Path（可选）

Flow 把 source 表上的流式计算结果物化到 sink 表。根据模式不同，Frontend 要么把写入 mirror 到 Flownode（streaming），要么 Flownode 自己回查 source 表（batching）。sink 表拥有独立的 schema、TTL、索引和存储位置——Flow 只负责计算，不改变任何表的存储策略。

## Query Engine

GreptimeDB 的查询引擎构建在 **Apache DataFusion** 之上，而不是自研一套执行框架。DataFusion 提供逻辑 / 物理计划接口、优化器框架与执行运行时；GreptimeDB 在它之上叠加自己的查询语言 planner、storage-aware 优化规则、自定义 plan 节点与分布式执行。整个技术栈都是 Apache 项目：

| 层 | 选型 | 角色 |
| :-- | :-- | :-- |
| 文件 / 索引格式 | **Apache Parquet** | 列式落盘，同时承载索引格式 |
| 内存表示 | **Apache Arrow** | record batch 贯穿协议层、计算层、内存缓存层 |
| 查询执行 | **Apache DataFusion** | 逻辑 / 物理计划、优化器、向量化执行运行时 |
| 存储访问 | **Apache OpenDAL** | 屏蔽 S3 / GCS / Azure Blob / OSS / 本地盘的差异 |

### Query Lifecycle

1. SQL、PromQL 或日志查询的 planner 通过 catalog 解析表，产出一条 DataFusion **逻辑计划**。
2. GreptimeDB 的优化规则与 DataFusion 的规则一起运行：规范化表达式与类型、重写时间范围操作、把 projection 与 filter 下推到 scan、必要时引入分布式 plan 节点。
3. 物理计划把优化后的逻辑计划转成流式算子；GreptimeDB 再应用 scan 并行度、排序、分布式执行等物理规则。
4. 执行时 Arrow record batch 沿物理计划被拉取（pull-based），存储 scan 收到 projection 与谓词，下游算子消费这个流而**不先把完整结果物化**。

`EXPLAIN` 看逻辑 / 物理计划，`EXPLAIN ANALYZE` 会真正执行并报告每个步骤的运行时耗时——这是从 SQL 生态直接复用的能力。

### SQL and PromQL Unification

PromQL 不是被「翻译成 SQL 字符串」，而是被 TelemetryQL（TQL）封装后，**把 PromQL 语义映射到 SQL / 数据湖模型**（二元算子 → JOIN，range vector → 数组切片，聚合 → `GROUP BY + 聚合函数`），最终落到与 SQL 同一个中间表示（IR / 逻辑计划）。在这个层面已经无法区分某一步来自 SQL 还是 PromQL，因此两者可以在一条查询里无缝混合——用 CTE 写 PromQL、再用 SQL 过滤与聚合：

```sql
WITH tql_data (ts, val) AS (
    TQL EVAL (0, 40, '10s') metric
),
filtered AS (
    SELECT * FROM tql_data WHERE val > 5
)
SELECT count(*) FROM filtered;
```

这个统一带来的额外收益是：可以直接复用成熟 SQL 优化器（自动重写低效查询、拒绝可能拖垮系统的查询），并开箱获得分布式执行。

### Distributed Execution

分布式模式下，查询分两段：**Frontend 规划 cluster-wide 查询，Datanode 执行 Region-local 子计划**。`MergeScan` 是这两段之间的边界——Frontend 把查询拆成各 Region 的子计划下发，Datanode 本地执行后把局部结果返回，Frontend 在 MergeScan 之上完成跨 Region 的归并、排序与最终聚合。

## Data Model

GreptimeDB 用带时间索引的关系表做统一可观测数据模型。表中每列的角色分为三类：

| 角色 | 声明方式 | 语义 |
| :-- | :-- | :-- |
| **Tag** | `PRIMARY KEY (...)` | 参与主键、把相关行分组。对 metrics 来说就是 label；允许为 NULL；可选（append-only 日志表可以没有主键列）。 |
| **Timestamp** | `TIME INDEX (col)` | 每张表必须且只能有一个时间索引。记录事件或采样时间，帮助按时间组织数据、支持高效时间范围查询。非空。 |
| **Field** | 剩余列 | 存测量值、日志内容、trace 属性或其他值。支持 numeric、string、JSON、timestamp 等类型，允许 NULL。 |

数据在持久化时按 `(primary key, timestamp)` 排序——同一组 tag 上的多个时间戳连续存放，利于局部性与压缩。append-only 表禁用去重与删除标记，没有主键时按 timestamp 排序。

```sql
-- Metrics 表：host 资源指标
CREATE TABLE system_metrics (
    host     STRING,
    idc      STRING,
    cpu_util   DOUBLE,
    memory_util DOUBLE,
    disk_util  DOUBLE,
    ts          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(host, idc),
    TIME INDEX(ts)
);

-- Logs 表：append-only、无主键
CREATE TABLE access_logs (
    access_time TIMESTAMP TIME INDEX,
    remote_addr STRING,
    http_status STRING,
    http_method STRING,
    request     STRING
) WITH ('append_mode' = 'true');
```

### JSON and JSON2

日志、trace、agent 事件这类 JSON 大多结构相似、查询只命中少数路径。GreptimeDB 提供两种 JSON 处理：

- **JSON（JSONB）**：把整个对象编码成 JSONB 二进制值，结构完整，适合低频整读或 schema 难预测的数据。
- **JSON2**（v1.2 补齐）：对用户仍是一个完整 JSON 对象，对存储 / 查询引擎则是**可按路径裁剪的结构化列**——嵌套字段用点路径像普通列一样访问（`attrs.http.status::BIGINT`），列表用下标访问，未命中路径的数据在读取时不被拉起，省下存储带宽与计算。新表带 JSON2 列须 `append_mode`。

```sql
CREATE TABLE application_logs (
    ts   TIMESTAMP TIME INDEX,
    attrs JSON2
) WITH ('append_mode' = 'true');

INSERT INTO application_logs VALUES (1, '{"http":{"status":200,"path":"/api/orders"}}');

SELECT attrs.http.status::BIGINT AS status,
       json_get(attrs, 'http.path')::STRING AS path
FROM application_logs;
```

### Merge Modes

有主键的表可以配置 merge mode，决定同一 `(primary key, timestamp)` 上多行怎么合并：

- `last_row`（默认）—— 保留最新一行（按写入顺序）。
- `last_value` —— 对每个 field 独立保留最新值。
- 其他模式（`overwrite`, `ignore` 等）用于特定场景。

append-only 表不适用 merge mode——写入就是追加，不做去重。

## Mito Storage Engine

Mito 是 GreptimeDB 默认的存储引擎，一个**面向时序负载的 [LSM Tree](/docs/CS/Algorithms/tree/LSM.md)** 变体，不是通用嵌入式存储库。它与 Cassandra 风格的宽列存储类似，但在数据模型、SST 格式和 compaction 策略上有时序化设计。

与 Mito 并存的可选引擎是 **Metric Engine**（v0.12 引入）：专门针对纯 metrics 负载优化，更省存储，建表时通过 engine 选项选择；Mito 是覆盖 metrics / logs / traces / 宽事件的通用引擎。本文以 Mito 为主展开。

### Engine Architecture

```
  WAL          Memtables          SST Files (Parquet)     Manifest
  ┌─┐         ┌────────────┐      ┌────┐ ┌────┐        ┌───────┐
  │ │──flush──▶ │ mutable  │─────▶│ SST│ │ SST│ ───────▶│ meta  │
  │ │           │  frozen  │      └────┘ └────┘        └───────┘
  └─┘           └────────────┘
                   ▲                  ▲
                   └─ compactor ──────┘
                     合并小 SST
```

组件说明：

- **WAL** —— 保证尚未 flush 的数据耐久性。基于 `Log Store` API 实现，底层可以是本地磁盘、也可以是远程 Kafka（remote WAL）。还支持 Noop WAL（不保留、耐久性最弱）。通用机制见 [WAL](/docs/CS/DB/WAL.md)。
- **Memtables** —— 按时间索引路由到 mutable memtable；flush 时冻结旧 memtable、安装新的 mutable 集，把冻结集写成 SST。
- **SST** —— 不可变 memtable flush 后落到持久存储，每行按 `(primary key, timestamp)` 排序。
- **Compactor** —— 用 [TWCS](https://cassandra.apache.org/doc/latest/cassandra/operating/compaction/twcs.html) 策略（Time-Windowed Compaction Strategy），按时间窗口分组 SST、配合 TTL 清理过期数据。
- **Manifest** —— 记录 SST 元数据：文件级时间范围、行数、row-group 数、可用索引、主键范围。

### Region

数据以 **Region** 为逻辑隔离单元——一个 Region 内所有行共享同一个 schema。一张表的数据分布在一个或多个 Region 上；Metasrv 维护表到 Region 的路由。Region 同时是**调度单位与高可用单位**：分裂、迁移、故障恢复都以 Region 为粒度（见 Distributed Mechanism）。

### SST Data Layout

SST 文件底层使用 **Apache Parquet** 列式格式。除了用户声明的列，Mito 在每个 SST 里还额外维护三列内部元数据，供多读合并、去重、删除时使用：

| 内部列 | 含义 |
| :-- | :-- |
| `__primary_key` | 编码后的主键（tag 列） |
| `__sequence` | 行的序列号 |
| `__op_type` | 行的操作类型（put / delete） |

Parquet 的 row group 是独立读 / 跳过的最小单位，每个 row group 带列级 min/max 与 null count。Mito 还记录文件级统计——这些统计驱动 scan pruning（见下文）。

SST 格式有两种：`flat`（新表默认，适合各种主键基数，包括高基数）与 `primary_key`（兼容旧表的 legacy 格式）。

### Compaction: TWCS

Mito 的 compaction 采用 **TWCS（Time-Windowed Compaction Strategy）**，这是 Cassandra 同名的时序 compaction 策略在 Mito 上的落地。核心思想是**按时间窗口分组、窗口关闭后不再重写**：

1. 数据按时间被划分到一个个时间窗口（window）；窗口内持续写入、持续把小 SST 合并成更大的 SST，减少文件碎片与读放大。
2. 一个窗口「关闭」（超过了 `compaction.twcs.max_inactive_window_runs` 这类阈值、不再有活跃写入）后，该窗口内的 SST 被合并成少数几个大文件，之后**不再参与后续 compaction**——这把写放大压到最低，因为冷数据不会被反复重写。
3. TTL 到期时，整个过期窗口的文件可以直接整窗删除，不需要逐行 GC。

与通用 LSM 的 leveled compaction 相比，TWCS 的代价是：窗口内如果仍有乱序写入，合并收益有限；但它对「时间到了就不再变」的时序 / 日志负载几乎是最优解。可通过 `ALTER TABLE ... SET 'compaction.twcs.max_inactive_window_runs' = '6'` 等表参数调优。

### Scan Pruning

Mito 在读取时避免打开不可能匹配查询的数据，按从粗到细的顺序执行三层剪枝：

1. **时间范围剪枝** —— 文件与 memtable 的时间范围不与查询时间窗相交则跳过。对时序查询来说最便宜、也最有效。
2. **Row-group 统计剪枝** —— row group 的 min/max 统计能证明无行匹配则整组跳过。
3. **索引剪枝** —— 倒排索引、skipping index、全文索引提供更细粒度过滤，处理统计无法判定的谓词。索引本身的原理与选型见 [Indexing](#indexing)。

## Indexing

GreptimeDB 在存储引擎层构建并持久化多种索引，全部是 in-house 实现（向量索引除外）。索引服务于 Scan Pruning 的第三层——当时间范围与 row-group 统计无法判定某行是否匹配时，用索引做细粒度过滤。三类已 GA 的索引各有明确分工：

| 索引 | 创建方式 | 适用场景 | 实现 / 后端 |
| :-- | :-- | :-- | :-- |
| **Inverted Index**（倒排索引） | 列约束 `INVERTED INDEX` | 基于 tag 值的查找、字符串列过滤、标签列精确查询（如 `log_level`、`service`） | in-house |
| **Skipping Index**（跳数索引） | 列选项 `SKIPPING INDEX` | 数据分布稀疏的场景、大规模数据集中查低频值（如 `trace_id`、MAC 地址、IP） | in-house，type 仅 `BLOOM` |
| **Fulltext Index**（全文索引） | 列选项 `FULLTEXT INDEX` | 日志正文关键词检索、模式匹配、大规模文本过滤 | in-house，`bloom` 或 `tantivy` 后端 |
| **Vector Index**（向量索引） | — | 相似性查询 | **进行中** |

统一语法（v0.12 起三种索引创建语法被统一为列约束 / 列选项，并支持 `ALTER` 增减）：

```sql
CREATE TABLE IF NOT EXISTS system_metrics (
    host       STRING INVERTED INDEX,
    idc        STRING SKIPPING INDEX,
    cpu_util   DOUBLE,
    memory_util DOUBLE,
    desc2      STRING FULLTEXT INDEX WITH (analyzer = 'English', case_sensitive = 'false', backend = 'bloom'),
    ts         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(host, idc),
    TIME INDEX(ts)
);

-- 事后增减索引
ALTER TABLE monitor MODIFY COLUMN host SET INVERTED INDEX;
ALTER TABLE monitor MODIFY COLUMN host UNSET INVERTED INDEX;
```

各索引的可调参数：

- **Skipping Index**：`type` 目前仅 `BLOOM`（布隆过滤器）；`granularity` 控制每个索引块由多少行粒度组成（例如索引粒度 8192 行、granularity 为 4，则每个索引块覆盖 32768 行）。
- **Fulltext Index**：`analyzer` 支持 `English` / `Chinese`（默认 English）；`case_sensitive` 默认 `false`；`backend` 支持 `bloom` / `tantivy`（默认 bloom）。

> [!WARNING]
> **高基数陷阱**：GreptimeDB 内部大量操作围绕「时间线」（一个 `(primary key)` 对应一条时间序列）组织。高基数数据（如把 `user_id`、`trace_id` 放进主键）会同时造成两个问题——维护海量时间线推高内存、压低压缩效率；而 **倒排索引的体积会随基数剧烈膨胀**。稀疏、低频的等值查询应改用 **skipping index**（布隆过滤器），而不是倒排索引。

## Storage Location

GreptimeDB 的存储后端与引擎选择正交：Mito Engine 定义数据如何组织，local filesystem 或 object storage 只决定数据文件**落到哪里**。

| 状态类型 | 典型位置 | 持久性边界 |
| :-- | :-- | :-- |
| 持久数据文件（SST + 索引） | 本地文件系统 或 对象存储 | 对象存储需配版本控制 / 复制；本地文件需备份 |
| WAL | 本地 WAL / remote WAL / Noop | 接受但未 flush 的写入全靠 WAL 保护 |
| 元数据 | 单机本地 / Metasrv 集群 | 重建数据库状态必需，须持久化或复制 |
| 本地缓存 | Datanode 本地盘 | 随时可从持久数据重建，不算 durability 边界 |

**存算分离**是分布式部署的关键设计：SST 文件放到对象存储，Datanode 负责写入、compaction 与查询，本地磁盘只做缓存。计算与对象存储可以独立伸缩——扩容 Datanode 不需要搬迁任何持久数据文件。

支持的对象存储：Amazon S3 与 S3 兼容（MinIO、DigitalOcean Spaces、腾讯云 COS、百度 BOS）、Google Cloud Storage、Azure Blob Storage、阿里云 OSS。一张表可以通过 `storage` 选项选择配置好的 provider，实现冷 / 热数据分层（例如冷归档表落到便宜的 archive bucket）。

## Distributed Mechanism

分布式模式下，GreptimeDB 的可扩展性、可用性与一致性都围绕三个抽象展开：**Region**、**Metasrv 的共识与调度**、**Frontend 的路由**。

### Region Routing

Frontend 不直接硬编码「表 → 节点」的映射，而是从 Metasrv 拉取 **Region 路由表**并在本地**惰性缓存**（路由不常变，缓存足够）。

- **写入**路由到持有目标 Region 的 **leader（写入节点）**。
- **查询**可从 leader 或 **follower（只读节点）** 取数——Frontend 按优先级把只读请求分发到 follower，实现读写算力隔离。
- 若缓存的路由失效，Datanode 返回 `Invalid Route` 错误，Frontend 重新从 Metasrv 拉取最新路由并更新缓存。

### Metasrv and Consensus

Metasrv 必须选举出单个 leader（数据节点只向 leader 发心跳，便于基于全局信息做调度），并一致地存储 catalog / schema / Region 路由等元数据。GreptimeDB 的早期实现以 **etcd** 作为共识后端（也可接 zookeeper），只用到 etcd 的 Watch（选举）、KV（少量元数据）两类能力，不自定义 Raft 状态机；共识组件在设计上是**可插拔**的，未来可换更优实现。

### Procedure Framework

Region 的创建、分裂、迁移、表的创建等「集群级变更」都被建模为 **procedure**——由 Metasrv 协调、可重试、可恢复的长期任务。procedure 框架保证这些跨节点操作在失败后能从中断点继续，而不是留下半成品状态。Region 的再均衡（把热点 Region 从过载节点迁走）也通过 procedure 驱动。

### Region Split, Migration and Load Balancing

Region 是调度与高可用单位。当单个 Region 过大或节点负载不均时：

- **开源版**：Region 概念完整，但自动化重分区与 Region 负载均衡依赖基础调度，大规模再均衡通常需要手动介入或配合运维。
- **企业版**：提供 **automated repartitioning** 与 **region load balancing**，按需弹性重分区，把 Region 自动从热节点迁到冷节点。

### Failover and Availability

Datanode 故障后的可用性取决于三个因素的组合：**WAL 模式**、**Region 副本（leader / follower）**、**共享对象存储**。数据文件在对象存储上不依赖任何单台 Datanode，因此一台 Datanode 宕机，其 Region 由 follower 接管或重新分配即可，持久数据不丢。WAL 模式直接决定「尚未 flush 的写入」能扛多强故障：

| WAL 模式 | 耐久 / 可用性 | 代价 |
| :-- | :-- | :-- |
| 本地 WAL | 最弱——Datanode 故障可能丢未 flush 数据 | 最快、零额外依赖 |
| Remote WAL（Kafka） | 解耦——写入先到 Kafka，Datanode 故障可重放 | 引入 Kafka 依赖与运维 |
| Noop WAL | 无耐久保证 | 最快，仅适合可重放的导入场景 |

## Flow Computation

Flow 引擎让实时计算可以在写入数据流上连续执行，并把结果物化到 sink 表。它解决的典型问题：

- 仪表板与告警需要**现成聚合**，不想每次都扫原始 events。
- 数据降采样（downsampling），用 average pooling 等方式压缩存储体积。

### Programming Model

```
  source 表 ──▶ Flow 引擎 ──▶ sink 表
  (原始数据)    (EVAL INTERVAL)  (物化结果)
```

Flow 定义的核心是一条 `CREATE FLOW` SQL：source 表 → SQL 计算逻辑 → sink 表 + `EVAL INTERVAL`。source 与 sink 都是 GreptimeDB 内部的时序表，各自独立维护 schema、TTL、索引与存储位置。

```sql
CREATE FLOW http_status_count
SINK TO status_metrics
EVAL INTERVAL '10s'
AS
SELECT
    status_code,
    COUNT(*) AS count,
    date_bin('1 minute'::INTERVAL, timestamp) AS time_window
FROM access_logs
GROUP BY status_code, time_window;
```

1. source 表上的新写入被镜像（streaming）或定期拉取（batching）到 Flow 引擎。
2. Flow 执行 SQL 聚合，把结果写到 sink 表。
3. 查询仪表板时读 sink 表即可，不必再扫描原始 access_logs。

### Modes

- **Batching**（默认）—— 按 `EVAL INTERVAL` 定期从 source 表拉取并计算，适合聚合与 TQL 负载。
- **Streaming** —— 每条写入都镜像到 Flownode，适合简单、低延迟的非聚合转换。新负载不推荐。

生产案例：OceanBase Cloud 用 80+ 个 GreptimeDB 集群承载 300 TB 日志，Poizon 用 Flow 维持 10s / 1m / 10m 三级 rollup，把 P99 查询延迟从秒级压到毫秒级。

## Ingestion and Query Protocols

GreptimeDB 没有强迫用户替换采集 agent 或仪表板——它在写入侧兼容多个成熟协议、在读侧保留对应的查询接口：

| 方向 | 协议 / API | 说明 |
| :-- | :-- | :-- |
| **写入** | Prometheus Remote Write（v1 / v2） | metrics，客户端不需要改 |
| | OpenTelemetry OTLP/HTTP | metrics、logs、traces 全覆盖 |
| | Loki Push API | logs（写入兼容，但不提供 LogQL 查询） |
| | Elasticsearch Bulk API | 文档摄入（Bulk 接口，非完整 Query DSL） |
| | InfluxDB Line Protocol | 与 InfluxDB 写入格式兼容 |
| | Splunk HEC | 兼容 Splunk HTTP Event Collector（v1.2 新增） |
| | MySQL / PostgreSQL wire | 标准 SQL |
| | GreptimeDB gRPC / HTTP | 原生接口 |
| **查询** | SQL | 跨所有信号类型 |
| | PromQL（TelemetryQL） | 只对 metrics，可经 CTE 与 SQL 混合 |
| | Jaeger-compatible API | traces |
| | HTTP API | 原生查询与管理 |

Grafana 仪表板可以直接用 MySQL 数据源接 GreptimeDB，不需要额外的 datasource plugin。

## Observability 2.0 and Wide Events

GreptimeDB 的数据模型原生支持三种信号，但并不强制你按 pillars 拆分。**Observability 2.0** 是 GreptimeDB 主推的一种可观测性范式——在采集时保留完整宽事件（wide event），而不是预先决定每个字段怎么用。一次业务操作的完整上下文（用户 ID、trace_id、HTTP 属性、DB 查询、缓存操作、结果、耗时）都存成一张表的一行：

```
{
  "timestamp":  "2026-08-12T08:15:30Z",
  "method":     "POST",
  "path":       "/articles",
  "service":    "articles",
  "user_id":    "fdc4ddd4-...",
  "trace_id":   "4bf92f3577b34da6a3ce929d0e0e4736",
  "status_code": 201,
  "duration":   268,
  "db_query":   "INSERT INTO articles (...)"
}
```

事后分析时可以用 SQL 任意切片，也可以用 Flow 从同一批宽事件派生出仪表板需要的 metrics——这样就不需要提前决定「哪些字段要进哪个 pillar」。

宽事件 approach 的代价：更多字段 = 更大数据量、高基数（user_id、session_id）+ 长保留 = 更高成本。所以 GreptimeDB 允许原生 metrics/logs/traces 和宽事件并存——在成本和灵活性之间按场景选择。

## Comparison

| 维度 | GreptimeDB | InfluxDB 3.x | VictoriaMetrics | Prometheus + Loki |
| :-- | :-- | :-- | :-- | :-- |
| 信号覆盖 | metrics + logs + traces + 宽事件 | metrics + logs + traces | metrics only | metrics 单独 + logs 单独 |
| 存储引擎 | Mito（LSM + Parquet）+ 可选 Metric Engine | 自研 | 自研 LSM | 各自独立 |
| 查询引擎 | DataFusion + Arrow（SQL/PromQL 统一 IR） | DataFusion | 自研 | 各自独立 |
| 持久化 | 对象存储 / 本地 | 对象存储 / 本地 | 本地 | 各自独立 |
| 存算分离 | ✅ 原生 | ✅ | ❌ | 视部署 |
| 连续聚合 | Flow | Continuous Query | 无 | recording rules |
| 查询语言 | SQL + PromQL（可 CTE 混合） | SQL + InfluxQL | MetricsQL | PromQL + LogQL |
| 部署组件 | Metasrv + Frontend + Datanode + Flownode | 单进程 / 分布式 | 单进程 | 多组件 |

与 [InfluxDB](/docs/CS/DB/InfluxDB.md) 对比：两者都是时序 / 可观测性方向，但 InfluxDB 是**专用 TSDB 扩展**路径，GreptimeDB 是**从头按统一可观测设计**的单列式引擎；GreptimeDB 的对象存储原生支持、Flow 计算与 DataFusion 统一的 SQL/PromQL 查询是 InfluxDB 3.x 有对应但工程路径不同的特性。

## Links

- [DataBases](/docs/CS/DB/DB.md)
- [Timeseries](/docs/CS/DB/Timeseries.md)
- [InfluxDB](/docs/CS/DB/InfluxDB.md)
- [ClickHouse](/docs/CS/DB/ClickHouse.md)
- [Cassandra](/docs/CS/DB/Cassandra.md)
- [QuestDB](/docs/CS/DB/QuestDB.md)
- [IoTDB](/docs/CS/DB/IoTDB.md)
- [OpenTSDB](/docs/CS/DB/OpenTSDB.md)
- [LSM Tree](/docs/CS/Algorithms/tree/LSM.md)
- [WAL](/docs/CS/DB/WAL.md)

## References

1. [GreptimeDB Official Documentation](https://docs.greptime.com/)
2. [GreptimeDB v1.2.0 Release Notes](https://docs.greptime.com/release-notes/release-1-2-0/)
3. [GreptimeDB Query Engine (Contributor Guide)](https://docs.greptime.cn/en/contributor-guide/datanode/query-engine/)
4. [GreptimeDB Architecture](https://docs.greptime.com/user-guide/concepts/architecture/)
5. [GreptimeDB Data Model (Concepts)](https://docs.greptime.com/user-guide/concepts/data-model/)
6. [Metasrv Overview (Contributor Guide)](https://docs.greptime.com/zh/0.11/contributor-guide/metasrv/overview/)
7. [GreptimeDB 中文文档](https://docs.greptime.cn/)
8. [Why GreptimeDB](https://docs.greptime.com/user-guide/concepts/why-greptimedb/)
9. [Engage Prometheus in Rust (PromCon 2025)](https://greptime.com/blogs/2026-01-14-promcon-engage-prometheus-in-rust)
10. [OceanBase Cloud: GreptimeDB 300 TB 日志存储](https://greptime.com/blogs/2025-07-22-user-case-obcloud-log-management-greptimedb)
11. [Poizon: Flow 连续聚合实战](https://greptime.com/blogs/2025-05-06-poizon-observability-greptimedb-monitoring-use-case)
12. [Agent RCA Bench](https://rca-bench.greptime.com/) — 六模型对比 GreptimeDB vs Prometheus+Loki+Tempo
