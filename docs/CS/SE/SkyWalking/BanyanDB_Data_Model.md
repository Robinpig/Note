# BanyanDB Data Model: Measure / Stream / Trace

## Introduction

数据模型是 BanyanDB 区别于通用时序库的核心：它不是一个统一的"表"，而是针对 APM 三类访问模式分别设计的资源——`Measure`（指标）、`Stream`（日志/事件）、`Trace`（调用链），外加 `Property`（KV）。本页聚焦数据模型的**运行时语义**（entity 如何标识 series、tag 与 field 的查询差异、measure 的更新与 index_mode 引擎切换、stream/trace 的特殊性、索引粒度三方对比），schema 对象的字段定义见 [BanyanDB_Metadata](/docs/CS/SE/SkyWalking/BanyanDB_Metadata.md)。权威描述见 `docs/concept/data-model.md`。

## 1. 逻辑层级

数据按 `Group` 组织（`docs/concept/data-model.md:13-24`）：一个 Group 的 `catalog` 固定其容纳的资源类型（`MEASURE` / `STREAM` / `TRACE` / `PROPERTY`），并携带 `shard_num`、`segment_interval`、`ttl` 等物理选项。Group 是最小物理结构管理单元，不是资源隔离边界。`Measure` 之下还可挂 `TopNAggregation`（data-model.md:21）。

## 2. Tag 与 Field：查询语义的分水岭

`Measure` 的每个数据点由 **tags + fields** 组成（measure 包注释：`measure.go:18-20`，"Each data point contains tags and fields"）：

- **Tag**：KV 对，可被 `IndexRule` 索引，用于查询过滤；相同 tag 值可分组为 `tag_families`（逻辑 + 物理分组，data-model.md:102）。
- **Field**：仅 `Measure` 拥有，是数据点的实际度量值；**查询禁止按 field 值过滤**，只能对其做聚合（data-model.md:116-117）。这一约束把"可索引的维度"与"可聚合的指标"在模型层就分离开。

| 维度 | Tag | Field（仅 Measure） |
| --- | --- | --- |
| 是否可索引 | 是（IndexRule 绑定） | 否 |
| 是否可过滤 | 是（WHERE） | 否（仅聚合函数输入） |
| 编码方向 | 同 series 内压缩 | 同 series 内编码压缩（GORILLA/ZSTD 提示） |
| 是否分组 | 归入 tag_families | 无 |

## 3. Entity → Series：运行时标识

一组 tag 组合成 **`entity`**，指向一条具体的时间序列（data-model.md:112）。`pkg/pb/v1/series.go` 给出运行时实现：`Series.Marshal()` 把 entity 的 tag 值序列化进 `Buffer`，再用 `convert.Hash` 生成标识（:48-55）：

```go
func (s *Series) Marshal() error {
    ...
    s.ID = common.SeriesID(convert.Hash(s.Buffer))   // series.go:55
}
```

即 **seriesID = hash(entity tag 值)**。相同 entity → 相同 seriesID → 归入同一条 series；相同 `entity(series_id) + timestamp` 的数据点可**更新**（measure.go:18-20，"could be updated by one with the identical entity(series_id) and timestamp"）。写入时 tag/field 的运行时载体是 `nameValue`（name + value/valueArr + valueType，对象池化 `nameValuePool`，`banyand/measure/datapoints.go:41-56`）。

`sharding_key` 可选（data-model.md:114）；未配置时系统默认用 `entity` 做分片键——这正是 [BanyanDB](/docs/CS/SE/SkyWalking/BanyanDB.md) §2.1 的 sharding key = `name + entity`。

## 4. Measure：指标与 index_mode 引擎开关

`Measure`（data-model.md:62-193）面向按固定 `interval` 到达的数据点，`interval` 隐含同 series 内数据按等间隔分布（:133）。两个关键开关：

- **`index_mode`**（data-model.md:135 / :137）：`false` 时值以列式 part 落 TSDB 引擎；`true` 时**不写任何列式 part**，整条数据点作为文档存进 inverted index，此时 entity 是唯一键、`timestamp`/`version` 为公共 tag。文档强调这是"同一 schema、同一 Write/Query RPC 背后的整个存储引擎切换开关"，且一旦有数据即不可变。这把"列式 TSDB"与"纯倒排文档"两种引擎统一在同一数据模型之下（[BanyanDB_TSDB_Engine](/docs/CS/SE/SkyWalking/BanyanDB_TSDB_Engine.md) 详述列式侧）。
- **`TopNAggregation`**（data-model.md:158-193）：在**写入阶段**预计算 top/bottom，`counters_number`（默认 1000）与 `lru_size` 控制内存；查询时直接取，远快于查询期 `top()` 聚合。它是近似实现（[BanyanDB_Index](/docs/CS/SE/SkyWalking/BanyanDB_Index.md) 的 TopN 索引来源）。

> 编码提示的真相：schema 里的 `encoding_method=GORILLA` / `compression_method=ZSTD` 只是** schema 级 hint**（data-model.md:131 注）。实际磁盘编码由值类型与数据形状决定——`INT`/`FLOAT` 走 delta / delta-of-delta / const + zigzag-varint（float 先转 decimal-int mantissa+exponent），非数值列走 dictionary/plain；ZSTD 按大小阈值（≥128 字节）通用应用。详见 [BanyanDB_Columnar_Encoding](/docs/CS/SE/SkyWalking/BanyanDB_Columnar_Encoding.md)。

## 5. Stream：高吞吐、无 Field

`Stream`（data-model.md:195-199）与 Measure 共享 tag 编码/压缩（delta / dictionary + zstd），但**弃用 field**——它面向日志、事件等高吞吐写入，查询价值在 tag 而非度量值。其索引粒度不同于 Measure（见 §7）。

## 6. Trace：按 trace_id 聚合的 Span 树

`Trace`（data-model.md:201-254）是分布式追踪专用模型：不像 Stream 那样独立存元素，而是**围绕 trace 组织**——每个 trace 由共享同一 `trace_id` 的多个 span 组成。定义上**无 tag families**，是 flat tag 列表；三个特殊 tag 名字段必填：`trace_id_tag_name`（按它分组 span）、`span_id_tag_name`（span 唯一标识）、`timestamp_tag_name`（span 时间戳，:228-230）。每个写入的数据点即一个 span，引擎自动按 trace_id 归组；查询响应返回含同 trace 全部 span 的 `Trace` 对象，且每个 span 还携带 raw `span` 二进制字段（:252）。

## 7. 索引粒度三方对比

`Measure` / `Stream` / `Trace` 的索引目标层级截然不同（data-model.md:380-410）：

| 类型 | 索引粒度 | 性能 | 灵活性 |
| --- | --- | --- | --- |
| **Measure** | 每个 series（基于 entity）；每个索引值须代表唯一 seriesID | 快（series 级定位） | 弱：索引非 entity tag 需谨慎 |
| **Stream** | 每个 element（seriesID + timestamp） | 慢于 Measure（element 级） | 强：可索引任意 tag 值 |
| **Trace** | 每个 element 的 TREE 索引，按 int64 tag 值有序 | 数值 tag 高效有序检索 | 限 `TREE` + int64/timestamp tag，不支持 inverted/skipping |

`IndexRule.Type` 三选一（data-model.md:349）：`TYPE_INVERTED`（measure tag，查询性能优）、`TYPE_SKIPPING`（stream tag，空间优先）、`TYPE_TREE`（trace，int64 排序键）。`IndexRuleBinding` 把规则绑定到 subject 并带时间窗 `begin_at`/`expire_at`（不重叠，data-model.md:336）。

## 8. Property：非时序 KV

`Property`（data-model.md:256-293）是 `group`/`name`/`id` 三级键的可变文档，用分布式 inverted index 支撑 tag 查询；**无时间戳/segment 维度**，`ttl` 不适用；更新按 `ModRevision` last-writer-wins，删除为软删除（tombstone，merge 时惰性回收）。它也是 schema 元数据自身的存储载体（[BanyanDB_Metadata](/docs/CS/SE/SkyWalking/BanyanDB_Metadata.md) §2.2）。

## 9. 与 SkyWalking 的映射

在 [Storage_Abstraction](/docs/CS/SE/SkyWalking/Storage_Abstraction.md) 中，OAP 的 `BanyanDBIndexInstaller` 把 OAP `Model` 落为 BanyanDB schema：指标/度量 → `Measure`（含 interval 与 GORILLA/ZSTD 字段）；日志与部分 trace 元素 → `Stream`；span/trace 拓扑 → `Trace`（或 stream）；维度与标签 → tag / tag_families；可聚合值 → field。理解本页的 entity/series、tag/field、index_mode 与索引粒度，是读懂 OAP 经 BanyanDB 客户端 `client.define` 落库的前提。

## Links

- [BanyanDB](/docs/CS/SE/SkyWalking/BanyanDB.md)
- [BanyanDB_Metadata](/docs/CS/SE/SkyWalking/BanyanDB_Metadata.md)
- [Storage_Abstraction](/docs/CS/SE/SkyWalking/Storage_Abstraction.md)
- [BanyanDB_TSDB_Engine](/docs/CS/SE/SkyWalking/BanyanDB_TSDB_Engine.md)
- [BanyanDB_Index](/docs/CS/SE/SkyWalking/BanyanDB_Index.md)
- [SkyWalking](/docs/CS/SE/SkyWalking/SkyWalking.md)

## References

- `docs/concept/data-model.md`（数据模型权威描述，含索引粒度对比）
- `banyand/measure/measure.go`（measure 包注释：tags+fields、interval、可更新语义）
- `banyand/measure/datapoints.go`（写入时 `nameValue` 运行时载体与对象池）
- `pkg/pb/v1/series.go`（entity → seriesID 的 `convert.Hash` 生成）
- `api/proto/banyandb/database/v1/schema.proto`（Measure/Stream/Trace/FieldSpec/IndexRule 定义）
