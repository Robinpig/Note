# BanyanDB Metadata and Schema Coordination

## Introduction

BanyanDB 的元数据（Metadata）是一组描述"数据如何组织、索引、分布"的 schema 对象，包括 `Group`、`Measure`、`Stream`、`Trace`、`IndexRule`、`IndexRuleBinding`、`TopNAggregation`、`Property`。它们既是存储引擎（[BanyanDB_TSDB_Engine](/docs/CS/SE/SkyWalking/BanyanDB_TSDB_Engine.md)）的建表依据，也是 [BanyanDB_Data_Model](/docs/CS/SE/SkyWalking/BanyanDB_Data_Model.md) 的物理承载。本页深挖 schema 对象的 protobuf 定义、schema 注册与同步机制、节点发现，以及 v0.11.0 引入的 schema 一致性屏障。在 SkyWalking 体系中，OAP 通过 `BanyanDBIndexInstaller` 经客户端 `client.define` 把这些 schema 落到 BanyanDB（见 [Storage_Abstraction](/docs/CS/SE/SkyWalking/Storage_Abstraction.md)）。

## 1. Schema 对象模型（protobuf 定义）

所有 schema 实体的核心定义集中在 `api/proto/banyandb/database/v1/schema.proto` 与 `api/proto/banyandb/common/v1/common.proto`。

### 1.1 Group：资源容器与分布策略

`Group`（`common.proto:254-268`）是资源的命名空间，承载 `catalog`（数据类型：CATALOG_MEASURE / STREAM / TRACE）与 `resource_opts`（`ResourceOpts`，`common.proto:259-260`）。`ResourceOpts` 的关键字段：

- `shard_num`（common.proto:88 / :121）：该 group 的 shard 数，决定数据分布粒度（见 [BanyanDB](/docs/CS/SE/SkyWalking/BanyanDB.md) §2.1 的 sharding）。
- `replicas`（common.proto:112-116，约束 `lte: 16`）：`0` 表示无副本，`1` 表示主 shard + 1 副本。注意：这与 clustering 文档"无应用级复制"并不矛盾——BanyanDB 仍把数据持久性委托底层存储，此 `replicas` 仅参与 shard→node 的 `replica_id` 映射（`node = (shard_index + replica_id) % node_count`）。

### 1.2 Measure / Stream / Trace：三类时序资源

| 字段 | Measure（schema.proto:142-167） | Stream（schema.proto:63-78） | Trace（schema.proto:316-350） |
| --- | --- | --- | --- |
| 定位 | 数据点（指标） | 流式数据（trace/log） | trace/span 专用资源 |
| `tag_families` | 1–32 个，用于过滤（:147-150） | 1–32 个（:68-71） | 由 `TraceTagSpec` 描述（:324-327） |
| `fields` | `FieldSpec` 列表，度量值（:152） | 无 field，值即 tag | 无 field |
| `entity` | 必填，`tag_names` 生成 series 并分片（:154） | 必填（:73） | 由 `trace_id_tag_name`/`span_id_tag_name`/`timestamp_tag_name` 表达（:328-347） |
| 时间语义 | `interval`（数据点频率，:155-157） | 无固定间隔 | 由 `timestamp_tag_name` |
| 特殊 | `index_mode`（仅存索引不存数据，:160-162）、`sharding_key`（TopN 数据分布，:163-164） | — | — |

`Entity`（`schema.proto:80-92`）是可生成 series 并参与分片的 tag 组合（最多 64 个），其 hash 决定 sharding key；多 entity 用 `|` 拼接（见 [BanyanDB](/docs/CS/SE/SkyWalking/BanyanDB.md) §2.1）。

### 1.3 FieldSpec：字段级编码与压缩

`FieldSpec`（`schema.proto:127-140`）定义了值字段的存储策略，是列式引擎（[BanyanDB_Columnar_Encoding](/docs/CS/SE/SkyWalking/BanyanDB_Columnar_Encoding.md)）的输入：

- `encoding_method`：当前仅 `ENCODING_METHOD_GORILLA`（schema.proto:116-119，即 Gorilla/xor 浮点编码）。
- `compression_method`：当前仅 `COMPRESSION_METHOD_ZSTD`（schema.proto:121-124）。
- `field_type`：`STRING` / `INT` / `DATA_BINARY` / `FLOAT`（:108-114）。

### 1.4 IndexRule / IndexRuleBinding：索引驱动

- `IndexRule`（`schema.proto:203-246`）：声明基于哪些 `tags` 建索引，索引 `Type` 三选一——`TYPE_INVERTED`（倒排，可配 `analyzer`：`standard`/`simple`/`keyword`/`url` 做全文分词，:233-241）、`TYPE_SKIPPING`（跳跃/稀疏索引）、`TYPE_TREE`（树索引，层级数据）。`no_sort` 标记是否用于排序。
- `IndexRuleBinding`（`schema.proto:264-290`）：把若干 `rules` 桥接到一个 `Subject`（catalog + stream/measure 名），并带**时间有效期** `begin_at` / `expire_at`（:281-285），灵活控制索引的生成窗口。

### 1.5 TopNAggregation：离线 TopN 预聚合

`TopNAggregation`（`schema.proto:170-199`）基于 `source_measure`，按 `field_name` 排序（`field_value_sort`：ASC=bottomN、DESC=topN、UNSPECIFIED=both，:182-185），按 `group_by_tag_names` 分桶，`counters_number`（默认 1000）与 `lru_size` 控制内存占用。它是 [BanyanDB_Index](/docs/CS/SE/SkyWalking/BanyanDB_Index.md) 中 TopN 索引的数据来源。

### 1.6 Property：用户 KV 数据

`Property`（`schema.proto:292-302`）是用户自定义 KV，无时间 segment（磁盘布局为 `<group>/shard-<shard_id>/`，见 [BanyanDB](/docs/CS/SE/SkyWalking/BanyanDB.md) §2.1），也是 schema 元数据自身的存储载体（见 §2）。

## 2. Schema 注册、存储与同步

### 2.1 SchemaRegistryService（RPC 面）

schema 的 CRUD 由 `database/v1/rpc.proto` 中的 `GroupRegistryService`、`MeasureRegistryService` 等 gRPC 服务提供。关键设计：**写操作响应携带 `mod_revision`**（如 `GroupRegistryServiceCreateResponse.mod_revision`，rpc.proto:379 / :388；删除响应带 `delete_time` 与 tombstone 的 `mod_revision`，:411-413）。该修订号是 §3 一致性屏障的基础。

### 2.2 存储后端：property + gossip（默认，无 etcd）

`banyand/metadata/service/server.go` 的 `FlagSet` 明示（:84-89）：

- `--schema-registry-mode` 默认 `metadata.RegistryModeProperty`（"property-based storage"）—— **默认 property 模式，无外部 etcd 依赖**。
- `--node-discovery-mode` 默认 `metadata.NodeDiscoveryModeNone`。
- `--has-meta-role` 默认 `true`（"Whether this data node runs the schema server. Only effective in property schema registry mode."）。

尽管 `Role` 枚举保留 `ROLE_META=1`（database.proto:31），当前默认部署中 schema 服务内嵌于 data node（`server.go:97-99` 依据 `hasMetaRole` 返回 `ROLE_META` 或 `ROLE_UNSPECIFIED`），通过 **property 协议**在节点间同步。

`schemaserver` 包（`banyand/metadata/schema/schemaserver/service.go`）即该协议的实现："a standalone gRPC server for schema property management"（:18）。其同步链路：

- 底层 KV 是 `banyand/property/db`（service.go:44）+ gossip 传播 `banyand/property/gossip`（:45）。
- `RegisterGossip(messenger gossip.Messenger)`（:72 / :130-131）：schema 变更经 **gossip** 在集群节点间传播，无需中心协调。
- `watcherManager`（:84 / :208）：向各 data node 的内存缓存推送 schema 变更通知（watch 机制）。
- 数据落盘目录：`.../data`、`.../snapshots`、`.../repair`（:232-234），其中 `repair` 对应 `RepairService`（schema 修复，见 `docs/concept/property-repair.md`）。

这与 [BanyanDB](/docs/CS/SE/SkyWalking/BanyanDB.md) §2.4 的描述完全呼应：默认 property 模式，通过内部 property-based 协议同步，**无需外部依赖**——早期版本的 etcd 方案已被取代。

### 2.3 节点发现

节点启动后向 discovery 服务注册，Liaison 据此路由。支持三种模式（`banyand/metadata/discovery/` 子目录）：`none`（standalone）、`dns`（DNS 记录）、`file`（文件列表）。默认 `none`（service/server.go:85）。

## 3. Schema 一致性：最终一致与 Revision Gate

BanyanDB 是**最终一致性系统**（docs/interacting/schema-consistency/overview.md:3）：schema 变更由 schema server 接受、持久化后，**异步传播**到各 data node 的内存缓存。多数请求可容忍传播延迟，但 read-after-write、delete-then-recreate、多阶段滚动发布等场景需要观测并门控传播。v0.11.0 引入的客户端可观测面（`overview.md`）：

- **响应字段**：`mod_revision`（变更后修订号）、`delete_time`（tombstone 时间）、`created_at`、`group_statuses`（每 group 的查询门控结果）。
- **请求字段**：`Metadata.mod_revision`（写门控，0 跳过）、`group_mod_revisions`（查询门控）。
- **Barrier RPCs**（`SchemaBarrierService`）：`AwaitRevisionApplied(min_revision, timeout)` 等所有节点缓存观察到 `>= min_revision`；`AwaitSchemaApplied(keys, min_revisions, timeout)` 等指定 schema 到达修订；`AwaitSchemaDeleted(keys, timeout)` 等 tombstone 传播完成。
- **状态码**：`STATUS_EXPIRED_SCHEMA`（修订落后于缓存，客户端刷新重试）、`STATUS_SCHEMA_NOT_APPLIED`（修订超前，未传播，调 `AwaitRevisionApplied` 后重试）。

所有门控均为 **opt-in**：不设置 `mod_revision`（或填 0）即回落到旧行为，无拒绝、无等待（`overview.md:49`），保证向后兼容。

## 4. 与 SkyWalking OAP 的衔接

OAP 的 `BanyanDBIndexInstaller extends ModelInstaller` 在 `prepare()` 阶段经 BanyanDB 客户端 `client.define(trace/stream/measure)` 把 OAP 的 `Model`/`@Column` 映射为上述 schema 对象（measure 对应指标、stream 对应日志/部分 trace、trace 对应 span）。理解本页的 `Measure`/`Stream`/`IndexRule` 定义，是读懂 OAP 存储抽象层落库逻辑的前提。

## Links

- [BanyanDB](/docs/CS/SE/SkyWalking/BanyanDB.md)
- [SkyWalking](/docs/CS/SE/SkyWalking/SkyWalking.md)
- [Storage_Abstraction](/docs/CS/SE/SkyWalking/Storage_Abstraction.md)
- [BanyanDB_Data_Model](/docs/CS/SE/SkyWalking/BanyanDB_Data_Model.md)
- [BanyanDB_Index](/docs/CS/SE/SkyWalking/BanyanDB_Index.md)
- [BanyanDB_TSDB_Engine](/docs/CS/SE/SkyWalking/BanyanDB_TSDB_Engine.md)

## References

- `api/proto/banyandb/common/v1/common.proto`（Group / ResourceOpts）
- `api/proto/banyandb/database/v1/schema.proto`（Measure/Stream/Trace/IndexRule/IndexRuleBinding/TopNAggregation/Property）
- `api/proto/banyandb/database/v1/database.proto`（Role 枚举）
- `api/proto/banyandb/database/v1/rpc.proto`（SchemaRegistryService / mod_revision）
- `banyand/metadata/service/server.go`（schema-registry-mode 默认 property）
- `banyand/metadata/schema/schemaserver/service.go`（property + gossip 同步）
- `docs/interacting/schema-consistency/overview.md`（最终一致性与 Barrier RPCs）
- `docs/concept/clustering.md`、`docs/concept/property-repair.md`
