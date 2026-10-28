## Introduction

Druid 的查询面是「一套 SQL 方言 + 三套执行引擎」：SQL 基于 Apache Calcite 做解析与计划，落到三选一的引擎上——传统 **native** 引擎（Broker scatter/gather，查询推给 Historical 单线程执行）、**MSQ task 引擎**（多阶段查询跑在摄取任务里，35.0.0 起为核心能力）、实验性的 **Dart** 引擎（Broker 当控制器、Historical 多线程当 worker）。原生 JSON 查询 API 保留六种查询类型，SQL 层把它们重写成物理计划。本页按「查什么 → 怎么跑 → 怎么加速」展开：查询类型与 SQL 能力、三引擎的分工、join 的两条路、缓存与近似聚合。集群侧的缓存与分片加载见 [Data_Management](/docs/CS/DB/Druid/Data_Management.md)。

## Native Query Types

原生 JSON API 的查询类型（`/druid/v2/sql` 之下的 SQL 查询最终也编译成这些）：

| 类型 | 用途 | 备注 |
| :--- | :--- | :--- |
| `timeseries` | 按时间桶聚合（GROUP BY 时间 + 度量） | 看板主力；结果按时间有序 |
| `topN` | 按度量排序取前 N 个维度值 | 对每个时间桶各取 TopN |
| `groupBy` | 任意维度组合的精确分组聚合 | 高基数下比 topN 重；Dart 的强项 |
| `scan` | 扫描行（SELECT 列投影） | 34.0.0 起 SQL 的 scan 形态改走 groupBy 规划 |
| `search` | 按维度子串/包含过滤 | `useIndexes` 走倒排；`auto` 策略已在 29.0.0 移除 |
| `timeBoundary` / `segmentMetadata` / `datasourceMetadata` | 元数据类：数据最小/最大时间、段 schema、行数估计 | 不扫数据 |

`sql` 与 `explain` 是另外两个「类型」：前者走 SQL 层，后者返回计划（`EXPLAIN PLAN FOR`）。SQL 结果可按 `rowsPerPage` 分页（29.0.0 起 MSQ 引擎支持）。

## The SQL Layer

- **基于 Apache Calcite**（28.0.0 从 1.21 升到 1.35）：SQL 被解析成关系代数再改写成原生查询或 MSQ 计划。32.0.0 起 ANSI SQL 兼容收口，三个 legacy 开关（`useDefaultValueForNull`、`useStrictBooleans`、`useThreeValueLogicForNativeFilters`）被移除，设旧值直接启动失败。
- **窗口函数 31.0.0 GA**（此前要 `enableWindowing`），native 与 MSQ 引擎都支持；聚合函数出现在窗口子句里会被 guardrail 拦掉。29.0.0 起支持实验性的 `PIVOT`/`UNPIVOT` 与 RANGE 窗口。
- **数据类型**：Druid 自有类型体系（LONG/DOUBLE/FLOAT/STRING/COMPLEX/ARRAY 等），SQL 层有到标准 SQL 类型的映射；`INFORMATION_SCHEMA` 自 26.0.0 起改用 SQL 数字类型、列编号 1-based。ARRAY 列自 22.x 引入，31.0.0 起 `arrayIngestMode` 默认 `array`（原 `mvd`，`none` 移除）——摄取侧的多值列现在统一按数组处理。
- **UDF/表达式**：SQL 内置大量标量函数；38.0.0 新增 `now()`（返回当前 epoch 毫秒，非确定性，会破坏摄取幂等，慎用在 INSERT 里）。

## Three Engines

| 维度 | native | MSQ task | Dart |
| :--- | :--- | :--- | :--- |
| 执行位置 | Historical/实时任务上各执行一段，Broker 合并 | 摄取任务（Peon/worker pod）里多 stage 执行 | Broker 调度、Historical 多线程执行 |
| 并行模型 | 段级 scatter，段内单线程 | stage 级多 worker + shuffle | worker 多线程 + 内存 shuffle |
| 擅长 | 高 QPS 固定形状看板查询 | 大 join（broadcast）、高基数 groupBy、SQL 摄取 | 大 join（并行 sort-merge）、高基数精确 groupBy/count distinct |
| 状态 | GA，默认 | 35.0.0 起核心能力 | 31.0.0 引入，**实验性** |
| 入口 | `engine` 缺省 / 控制台 SQL native | `engine='msq-task'` / 控制台 SQL task | `engine='msq-dart'` / 控制台 SQL Dart |

- **MSQ 不是插件而是核心**：35.0.0 起从 `druid.extensions.loadList` 删掉 `druid-multi-stage-query`，否则未来版本无法启动。SQL-based ingestion（`INSERT INTO ... SELECT` / `REPLACE`）就长在 MSQ 上。
- **Dart 的并发旋钮**：`druid.msq.dart.controller.concurrentQueries`（Broker 侧，默认 1）、`druid.msq.dart.worker.concurrentQueries`（Historical 侧，默认等于 merge buffer 数）、`druid.msq.dart.worker.heapFraction`（默认 0.35）。38.0.0 起支持 worker 段预取（`segmentLoadAheadCount`）与后台拉取云存储输入文件（`backgroundFetchExternalFiles`，默认开）。36.0.0 起 Dart 有查询报告（`/druid/v2/sql/queries/<id>/reports`），37.0.0 起有 `sys.queries` 系统表（默认关，`druid.sql.planner.enableSysQueriesTable=true` 开启）。
- **查询上下文是一等公民**：`priority`（优先级，配合 laning）、`timeout`、`useCache`、`realtimeSegmentsMode`（38.0.0 取代 `realtimeSegmentsOnly`，取值 `include`/`exclude`/`exclusive`，用于蓝绿部署时只查新副本）等。Broker 侧 37.0.0 起还支持动态查询黑名单（`queryBlocklist`，按数据源/查询类型/上下文匹配，无需重启）。

## Joins

Druid 的 join 分两个时代：

- **查询时 broadcast join（默认）**：`sqlJoinAlgorithm=broadcast`（缺省即此）。维表（右表）被广播到执行侧装进内存，主表逐行探测；要求所有非 base 输入合计不超过广播表体积上限（超了报 `BroadcastTablesTooLarge`）。只支持 LEFT/INNER/CROSS 且连接条件必须是等值。
- **sort-merge join**：`sqlJoinAlgorithm=sortMerge`，两侧按键哈希分区 + 排序后归并，无总规模上限，但单键数据量有上限（超了报 `TooManyRowsWithSameKey`）；支持 LEFT/RIGHT/INNER/FULL/CROSS。MSQ 与 Dart 都能用，Dart 以并行 sort-merge 见长。
- **lookup join**：小维表可以注册成 lookup（经 Coordinator API 管理），查询时当内存字典用，不走 join 引擎——星型模型的标准姿势。
- **查询计划器只是建议执行**：`sqlJoinAlgorithm` 是 hint，规划器在明显不合适时会忽略；33.0.0 起 `useMaxMemoryEstimates` 对 MSQ 固定为 `false`（更准的堆估算）。

## Caching

三层缓存决定了「重复查询快不快」：

1. **段级结果缓存**（per-segment result cache）：Broker/Historical 上按段缓存中间/最终结果，看板查询重复提交时直接命中；查询上下文 `useCache=false` 可关。
2. **段元数据缓存**（Broker 上）：缓存从 Coordinator 拉来的段清单，避免每次查 `sys.segments` 都走一轮。37.0.0 起默认开启，Overlord 侧配套增量缓存（`useIncrementalCache` 默认 `ifSynced`：成为 leader 后先同步一次元数据库才提供读）。
3. **摄取期的预聚合**（rollup/projections）：见 [Storage_Format](/docs/CS/DB/Druid/Storage_Format.md)——最彻底的「缓存」是不算。

缓存是正确性的大坑：**段更新（新版本）会使旧缓存失效**，而缓存按段 ID 维度管理，这是版本号存在的另一个理由。

## Approximate Aggregation

高基数去数是 Druid 的传统艺业，核心是用 sketch 换内存：

- **DataSketches 扩展（`druid-datasketches`）**：theta sketch（集合运算）、HLL sketch（超大规模去重）、quantiles sketch（分位数）、ArrayOfDoublesSketch。支持在摄取时直接存 sketch 中间态（`finalizeAggregations=false`），查询时再终结——省一次聚合。
- **`druid-histogram` 扩展已废弃**，请迁到 datasketches quantiles；contrib 侧另有 `druid-ddsketch`、`druid-momentsketch`、`druid-tdigestsketch`、`druid-spectator-histogram`（29.0.0 引入）等近似直方图/分位数实现，`druid-exact-count-bitmap` 提供基于 Roaring 的精确去重（吃内存，慎用）。
- **25.0.0 的行为收口**：HLL/quantiles 的终结规则与 theta 对齐——查询最外层、或作为表达式/后聚合输入时不再自动终结；要旧行为设 `sqlFinalizeOuterSketches=true`。
- **近似聚合的语义差异**（相对误差、可合并性、能否做集合交并）要在选型时对齐，别把 theta 当精确去重报数。

## Links

- [Druid](/docs/CS/DB/Druid/Druid.md)
- [Storage Format](/docs/CS/DB/Druid/Storage_Format.md)
- [Ingestion](/docs/CS/DB/Druid/Ingestion.md)
- [Extensions](/docs/CS/DB/Druid/Extensions.md)
- [Index](/docs/CS/DB/Concept/Index.md)

## References

1. [Druid Querying: Native queries](https://druid.apache.org/docs/latest/querying/native-queries/)
2. [Druid SQL](https://druid.apache.org/docs/latest/querying/sql/)
3. [Multi-stage query engine reference](https://druid.apache.org/docs/latest/multi-stage-query/reference/)
4. [SQL queries using the Dart engine](https://druid.apache.org/docs/latest/querying/dart)
5. [Druid 31.0.0 Release Notes](https://druid.apache.org/docs/31.0.0/release-info/release-notes)
