## Introduction

Druid 的存储可以用一句话概括：**按时间切分的不可变列存分片**。一个数据源（datasource）在时间轴上被切成若干区间（interval），每个区间一个或多个分片（segment）；分片内部按列组织，字符串列做字典编码 + 位图倒排，数值列直接压缩存储。这个设计把「分析型查询」的两种主要操作——按维度过滤、按度量聚合——都压到了最低的 I/O 上：只读查询涉及的列，只扫该列的位图与字典。本页讲清分片从数据源到文件的层级、列内部的三件套、压缩选择、格式版本的单向门，以及摄取期预计算（rollup 与 projections）的边界。分片在集群里的生命周期（加载、压实、淘汰）在 [Data_Management](/docs/CS/DB/Druid/Data_Management.md)。

## Hierarchy: Datasource, Interval, Segment

```
datasource（逻辑表，如 "wikipedia"）
  └── interval（时间区间，如 2026-10-01/2026-10-02，粒度由 segmentGranularity 决定）
        └── segment（不可变文件目录，如 wikipedia_2026-10-01T00:00:00.000Z_2026-10-02T00:00:00.000Z_v3_0）
              ├── version.bin        4 字节格式版本（v9 = 0x09）
              ├── meta.smoosh        其他 smoosh 文件的目录（文件名 + 偏移）
              ├── XXXXX.smoosh       拼接后的列数据，单文件 ≤ 2 GB（mmap ByteBuffer 上限）
              └── index.drd          段级元数据（schema、区间、分片规格、负载规格……）
```

- **段 ID = `datasource_intervalStart_intervalEnd_version_partitionNum`**。`version` 不是格式版本而是数据版本：同一区间重新入数（reindex、compaction、REPLACE）会分配递增版本号，新旧版本短暂共存后旧的被卸载——这就是 Druid 的 MVCC。
- **一个区间多个段 = 一个 block**。除线性分片（linear shardSpec）外，block 必须完整加载查询才能完成，否则查询等待——这是「查询偶发变慢」的常见嫌疑。
- **空区间不产生段**；查询遇到没有段的时间范围直接返回空，不报错。

## Column Layout

分片文件是列式的：每列独立存储，查询跳过不需要的列。列分三类——时间戳（`__time`，必有的第一分区键）、维度（dimension，可过滤/分组）、度量（metric，可聚合）。

### The Dimension Triple

每个字符串维度列由三个数据结构组成：

```
1. Dictionary  值 → 整数 ID 的映射（{"Justin Bieber": 0, "Ke$ha": 1}）
2. List        每行的值，用字典 ID 表示（[0, 0, 1, 1]）
3. Bitmap      每个字典值一个位图，标记哪些行含该值（value="Ke$ha": [0,0,1,1]），即倒排索引
```

- **过滤只碰位图**：`WHERE page = 'Ke$ha'` 等价于取该值的位图，与/或/非都是位图运算，与数据量基本无关。
- **聚合可绕开 List**：只按过滤条件聚合度量的查询（timeseries/topN 的纯过滤形态）可以不读 List，直接对命中的行做算术聚合。
- **位图体积 ≈ 行数 × 基数**：每列一个位图，高基数列（用户 ID）的位图稀疏但可压缩；这就是为什么「高基数维度即席 groupBy」在 Druid 上是强项，也是为什么段大小必须盯紧。
- **多值列（multi-value）**：一行可含一个字符串数组，List 对应项是数组，位图中该行有 n 个非零位。多值语义影响去重计数与分组结果，SQL 侧常用 `UNNEST` 摊平。

### Null and Missing Columns

- **字符串 null 固定在字典 ID 0**：只要该列在任何行出现过 null，null 就占字典首位并有对应位图——这是「过滤 IS NULL 与过滤空串结果不同」的根源。
- **数值列有独立 null 位图**，用于聚合时跳过 null 行与 null 匹配过滤。
- **schema 可以跨段不一致**：同一数据源的段可以有不同的列集合。缺列的行为有两种口径——默认模式下查询表现得像该列全为空值，SQL 兼容模式（`SQLCompatibleNullHandling`）下像全为 null。同一个查询换台集群跑出不同 null 语义，往往是这个配置不同。

## Compression

| 对象 | 默认 | 备选 |
| :--- | :--- | :--- |
| 时间戳/度量列的值块 | LZ4 | 段级 `indexSpec` 可切（含 ZSTD；38.0.0 起弃用 legacy v0.4–v0.7 ZSTD 帧） |
| 位图（维度列 + 数值 null） | Roaring | Concise（低基数更小但匹配多值时更慢） |
| 字符串编码 | front-coded，37.0.0 起默认 v1 | 26.0.0 引入 front-coded v0，与 25.x 不兼容 |

三个反直觉点：

- **压缩是段级的不是列级的**（`indexSpec` 对整个段生效），换了压缩 = reindex。
- **front-coded v1 在 37.0.0 成为默认**，从 26.x 直接跨版本升级的集群，字符串列读不了要 reindex。
- **31.0.0 起支持压缩列（compressed columns）与灵活段排序（flexible segment sorting）**，前者改变列在 smoosh 内的布局，后者允许自定义段内排序以提升特定查询模式。

## Segment Format Versions

- **当前默认格式是 v9**。`version.bin` 里就是 `0x09`。
- **v10 自 36.0.0 起实验性提供**（`druid.indexer.task.buildV10=true`），改进了 v9 的若干布局，**默认关闭且与旧格式互不兼容**：降级必须 reindex，`bin/dump-segment` 是检查段元数据的官方工具。
- 格式版本与数据版本（段 ID 里的 `vN`）是两回事：前者决定文件怎么读，后者决定哪份数据最新。

## Rollup and Projections

### Rollup

摄取时按维度组合预聚合（`granularitySpec.rollup = true`）：同一时间粒度 + 同一维度组合的行在入段前就被合成一行，度量按聚合器累加。这是 Druid「存储量远小于原始事件量」的主要原因，代价是丢失明细——**rollup 决策本质是明细与成本的交换，事后只能 reindex**。查询粒度（`queryGranularity`）可细于段粒度（`segmentGranularity`），反之不行。

### Projections（实验性）

31.0.0 引入的 projections 是段内的**预聚合视图**：摄取时按 `groupingColumns` 生成排好序的预聚合数据，与基础列共享字典等结构；查询时若匹配投影形状（分组列、过滤列、粒度）就自动改查投影，减少 I/O 与计算。两条边界：**目前只支持 JSON 系摄取**；**只服务 MSQ task 引擎与 Dart 引擎的查询**。控制开关是查询上下文 `useProjection` / `forceProjections` / `noProjections`。

## Sizing Rules of Thumb

- **段大小甜点区 300–700 MB**。超过优先调粗 `segmentGranularity`（小时→天），其次用 `partitionsSpec` 加分区（`targetRowsPerSegment` 建议从 500 万行起步）。
- 段太小的代价是元数据与加载开销爆炸；太大的代价是单段加载慢、查询并行度受限。
- 区间分配有一个 29.0.0 起的行为变化：请求粒度为月及以上且无法分配时，直接跳到按天分区，不再尝试周粒度（除非显式指定 `WEEK`）。

## Links

- [Druid](/docs/CS/DB/Druid/Druid.md)
- [Architecture](/docs/CS/DB/Druid/Architecture.md)
- [Data Management](/docs/CS/DB/Druid/Data_Management.md)
- [Query Engine](/docs/CS/DB/Druid/Query_Engine.md)
- [Table Format](/docs/CS/BigData/Table_Format.md)

## References

1. [Druid Design: Segments](https://druid.apache.org/docs/latest/design/segments)
2. [Druid Ingestion Spec: indexSpec](https://druid.apache.org/docs/latest/ingestion/ingestion-spec/#indexspec)
3. [Druid 31.0.0 Release Notes (storage improvements, projections)](https://druid.apache.org/docs/31.0.0/release-info/release-notes)
4. [Druid 36.0.0 Release Notes (V10 segment format)](https://druid.apache.org/docs/36.0.0/release-info/release-notes)
