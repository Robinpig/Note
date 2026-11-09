# BanyanDB: A Native Observability Database

## Introduction

BanyanDB 是 Apache 为可观测性数据（Metrics、Tracing、Logging）设计的**原生时序数据库**，最初为 [Apache SkyWalking](https://github.com/apache/skywalking) 量身打造。在 BanyanDB 出现之前，SkyWalking 采用的通用数据库（Elasticsearch、JDBC 关系库）对 APM 数据模型——尤其是 trace 与 log——并不理想，存在性能与资源利用率的改进空间。BanyanDB 以 [RUM Conjecture](http://daslab.seas.harvard.edu/rum-conjecture/)（读成本 / 更新成本 / 内存开销的权衡）为指导，组合多种访问方法构建综合 APM 数据库。

仓库 module 路径为 `github.com/apache/skywalking-banyandb`，Go 1.26，本文深挖基于 HEAD `6550b2f`（2026-11-06，commit *"feat(measure): stream query results between liaison and data nodes, acknowledge writes per batch"*）。在 SkyWalking 体系中，BanyanDB 是 OAP 的存储后端之一（与 ES / JDBC 并列），由 `BanyanDBIndexInstaller` 经客户端 `client.define` 建立原生 measure / stream 模型（详见 [Storage_Abstraction](/docs/CS/SE/SkyWalking/Storage_Abstraction.md)）。

本页是 BanyanDB 深挖系列的枢纽，覆盖整体架构、节点角色与启动装配、分布式拓扑，并导航到各子系统深挖笔记。

## 1. 节点角色与启动装配

### 1.1 三种运行时角色

BanyanDB 的进程按角色组织，角色由 protobuf 枚举 `databasev1.Role` 表达（`api/proto/banyandb/database/v1/database.proto:30-33`）：

| 枚举 | 值 | 含义 |
| --- | --- | --- |
| `ROLE_UNSPECIFIED` | 0 | 未指定 |
| `ROLE_META` | 1 | 保留；当前默认**不启用**独立 meta 节点（元数据经 property 协议内建同步，见 §2.4） |
| `ROLE_DATA` | 2 | 数据节点 |
| `ROLE_LIAISON` | 3 | 入口 / 路由节点 |

三种角色的职责（`docs/concept/clustering.md` §1）：

- **Data Node**：持有全部原始时序数据、元数据与索引数据；负责本地查询执行；还承担 TopN 聚合等计算任务（§1.1）。
- **Liaison Node**：无状态网关，负责把流量路由到 Data Node；提供认证、TTL 等安全服务；承担分布式查询的 **reduce** 阶段（§1.3）。
- **Standalone**：把 Liaison + Data + Schema Registry 三合一进单进程，部署 / 测试最简（§1.4）。`svc_standalone.go:263-265` 的 `Role()` 返回 `ROLE_DATA`，但其 `PreRun` 同时向 `metaSvc` 注册 data / liaison / schema-snapshot collector（`svc_standalone.go:315-320`），证实三合一。

运行时角色在代码中由 `Service.Role()` 返回：`svc_standalone.go:263-265` 为 `ROLE_DATA`，`svc_liaison.go:146-148` 为 `ROLE_LIAISON`；`pkg/run.Group.Run` 收集去重后打印 `"the node will run as"`（`run.go:359-386`）。

### 1.2 模块装配框架 pkg/run

服务可执行入口极薄：`banyand/cmd/server/main.go:29-34` 仅 `cmdsetup.NewRoot(new(signal.Handler)).Execute()`。真正的生命周期由 `pkg/run` 基于 [`oklog/run`](https://github.com/oklog/run) 的 `Group` 管理，**确定性三阶段**（`run.go:323-456`，注释在 :328-347）：

1. **Config phase（串行）**：各模块 `FlagSet()` 收集 flags（`run.go:221-261`）→ 解析 → `Validate()`；任一失败即停（:300-315）。
2. **PreRunner phase（串行）**：各 `PreRun(ctx)`；任一失败即停（:393-403）。
3. **Service phase（并发）**：各 `Serve()` 在独立 goroutine 运行（:413-452）；一旦某个返回，即对所有模块触发 `GracefulStop()`（:446-451）。

阶段单元通过接口识别并经 `Group.Register` 自动归类（`run.go:149-175`）：`Unit`（`Name()`）、`Config`（`FlagSet`/`Validate`）、`PreRunner`（`PreRun`）、`Service`（`Serve`/`GracefulStop`）、`Role`（`Role()`）。这与 SkyWalking OAP 的 `Module/Provider/Service` 三元模型（`Module_System.md`）异曲同工，但更轻量、无跨模块依赖拓扑排序。

### 1.3 按角色构建 Group（pkg/cmdsetup）

`pkg/cmdsetup` 按命令行选定的角色构建对应的 `Group` 并注册各数据类型的服务：

- **data**：`data.go:114-115` 用 `measure.NewDataSVC` / `stream.NewDataSVC` / `trace.NewDataSVC` 构造 `dataGroup` 并 `Register`。
- **liaison**：`liaison.go:150-151` 用 `measure/stream/trace.NewLiaison` + `logging.NewLiaisonService` 构造 `liaisonGroup`。节点间通信分两层 pub/sub 客户端：`pub.New(metaSvc, ROLE_LIAISON)`（tier1，liaison↔liaison，:56）与 `pub.New(metaSvc, ROLE_DATA)`（tier2，liaison→data，:57）；路由由 `measureDataNodeSel` 等 `node.Selector` 承担（:70-85）。
- **standalone**：`standalone.go:118-120` 用 `measure/stream/trace.NewStandalone` 构造 `standaloneGroup`。

值得注意的是，每种数据类型（measure / stream / trace）都提供**三个角色变体**（`NewDataSVC` / `NewLiaison` / `NewStandalone`），存储引擎代码（block / part / tstable / flusher / merger / gc / scan）是 per-type 各自实现，而非统一抽象层——这是 BanyanDB 作为"原生 APM 存储"的核心设计选择。

## 2. 分布式拓扑（clustering.md）

### 2.1 数据分布与 Sharding

数据分布由 group 的 `shard_num` 与各资源的 `entity` 决定（clustering.md §5.2）：

- **Sharding key** = 资源 `name` + `entity`。例如 `service_cpm:frontend`（measure）或 `system_log:frontend|10.0.0.1`（stream，多 entity 用 `|` 拼接）；实体值中的 `:` / `|` 需转义。
- 按 sharding key 的 hash 落入 group 的 `shard_num` 个 shard 之一。
- **Liaison 用确定性 round-robin 动态计算 shard→node 映射**：`node = (shard_index + replica_id) % node_count`（clustering.md:122）。不维护显式 shard 分配表，节点增删自动重算，简化扩容。

磁盘布局（clustering.md:66）：时序资源按 `<group>/<segment>/shard-<shard_id>/<part>/`，其中 `segment` 是时间桶，支撑 retention 策略；Property 数据无时间 segment，按 `<group>/shard-<shard_id>/` 直接组织。

### 2.2 Replication：无应用级复制

**关键设计取舍**（clustering.md §5.1）：BanyanDB **不做应用级 replication**，将持久性委托给底层存储系统（Google Compute Persistent Disk、Amazon S3 等）。文档从可靠性（11 个 9 的持久性）、扩展性（随数据增长自动扩展）、复杂度（复制逻辑由存储系统抽象）三方面论证。这与多数分布式 TSDB（如带副本的 Cassandra 系）不同，换来架构简化与磁盘 / 运维成本节省。

### 2.3 写入与查询路径

- **写入**（clustering.md §5.3）：User → Liaison（无状态，按 entity 识别目标 Data Nodes，分发写请求）→ Data Nodes 各自写入其 shard。
- **查询**（clustering.md §6）：User → Liaison（构建分布式查询）→ **访问所有** Data Nodes 并行执行本地查询计划 → 汇总返回。与写入不同，查询**不依赖 shard 映射信息**，Liaison 直接访问全部 Data Node；因查询负载通常远低于写入（文档举例时间序列库写:读 ≈ 100:1），此简化对扩容友好。
- **measure 聚合下推**：data node 执行本地 **map** 阶段，liaison 执行 **reduce** 阶段，跨 shard 结果正确且限制网络原始数据量（clustering.md §1.3，详见 `docs/concept/distributed-measure-aggregation.md`）。
- **Failover**（clustering.md §7）：Data Node 故障时，Liaison 路由到持有同 shard 的其他节点（依赖底层存储复制）；触发 failover 的写请求会被拒绝，客户端应重试。

### 2.4 Schema Registry 与节点发现

- **Schema Registry**（clustering.md §1.2、§3.1）：维护集群高层元数据——所有节点、所有数据库 schema、Group 配置（`shard_num`、`replicas`）、Data Node 注册信息。默认 **`property` 模式**，通过内部 property-based 协议在节点间同步，**无需外部依赖**（无 etcd 外部服务）。这纠正了一个常见误解：BanyanDB 早期版本依赖 etcd，当前版本默认已改为内建 property 同步。
- **节点发现**（clustering.md §2）：通过配置的 discovery 机制（`none` / `dns` / `file`）实现；节点启动时向 discovery 注册，Liaison 据此路由。

## 3. 存储引擎设计哲学

BanyanDB 的存储引擎围绕"为 APM 数据模式分别优化"展开：

- **Per-type 列式 TSDB**：measure / stream / trace 各自独立实现 `block_writer` / `block_reader` / `flusher` / `merger` / `gc` / `scan_*`，无统一数据抽象层。每类数据的访问模式（measure 的定点更新 + 预聚合、stream 的字符串排序、trace 的 span 树）得到针对性优化。
- **列式 block**：每个 block 是一批**按时间排序**的数据点，列式组织为 `tagFamilies`（列族）+ `field`（`measure/block.go:41-49`）。约束 `maxBlockLength=8192`（每 block 最多数据点）、`maxUncompressedBlockSize=2 MiB`、`defaultFlushTimeout=5s`、`defaultSyncInterval=30s`（`measure/measure.go:41-50`）。
- **LSM 风格落盘**：memtable → `part` → `tstable`（SSTable 等价）→ `flusher`（刷盘）→ `merger`（compaction）→ `gc`（retention 清理）→ `snapshot`（一致读视图）。
- **索引与向量化查询**：由 `IndexRule` 驱动的 inverted / posting 索引（见 [BanyanDB_Index](/docs/CS/SE/SkyWalking/BanyanDB_Index.md)）；查询走 vectorized 执行与 scan 路径 v2（零拷贝快路径 + 行合并，见 [BanyanDB_Query_Engine](/docs/CS/SE/SkyWalking/BanyanDB_Query_Engine.md)）。

## 4. 子系统深挖导航

| 主题 | 笔记 |
| --- | --- |
| 元数据与 Schema 协调（property 同步 / registry / discovery） | [BanyanDB_Metadata](/docs/CS/SE/SkyWalking/BanyanDB_Metadata.md) |
| 数据模型：Measure / Stream / Trace | [BanyanDB_Data_Model](/docs/CS/SE/SkyWalking/BanyanDB_Data_Model.md) |
| 列式 TSDB 引擎（block/part/tstable/flush/merge/gc） | [BanyanDB_TSDB_Engine](/docs/CS/SE/SkyWalking/BanyanDB_TSDB_Engine.md) |
| 列式编码与压缩 | [BanyanDB_Columnar_Encoding](/docs/CS/SE/SkyWalking/BanyanDB_Columnar_Encoding.md) |
| 索引子系统（inverted/posting/LSM/TopN） | [BanyanDB_Index](/docs/CS/SE/SkyWalking/BanyanDB_Index.md) |
| 写入路径（含 per-batch ack） | [BanyanDB_Write_Path](/docs/CS/SE/SkyWalking/BanyanDB_Write_Path.md) |
| 查询引擎（BYDBQL + 分布式 + vectorized） | [BanyanDB_Query_Engine](/docs/CS/SE/SkyWalking/BanyanDB_Query_Engine.md) |

## Links

- [SkyWalking](/docs/CS/SE/SkyWalking/SkyWalking.md)
- [Storage_Abstraction](/docs/CS/SE/SkyWalking/Storage_Abstraction.md)
- [BanyanDB_Metadata](/docs/CS/SE/SkyWalking/BanyanDB_Metadata.md)
- [BanyanDB_Data_Model](/docs/CS/SE/SkyWalking/BanyanDB_Data_Model.md)
- [BanyanDB_TSDB_Engine](/docs/CS/SE/SkyWalking/BanyanDB_TSDB_Engine.md)
- [BanyanDB_Query_Engine](/docs/CS/SE/SkyWalking/BanyanDB_Query_Engine.md)

## References

- `docs/concept/clustering.md`（架构权威描述）
- `docs/concept/data-model.md`、`docs/concept/tsdb.md`、`docs/concept/storage-and-format.md`
- `api/proto/banyandb/database/v1/database.proto`（Role 枚举）
- `banyand/measure/svc_standalone.go`、`banyand/measure/svc_liaison.go`
- `pkg/run/run.go`（模块生命周期框架）
- `pkg/cmdsetup/{data,liaison,standalone}.go`（角色装配）
