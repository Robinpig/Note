## Introduction

Spark SQL 处理的是**带 schema 的分布式数据**（DataFrame / Dataset），与底层 [RDD](/docs/CS/Framework/Spark/RDD.md) 的关系是：用户写 SQL 或 DataFrame 变换 → 交给 **Catalyst 优化器**生成逻辑与物理计划 → 用 **Tungsten**（堆外内存 + 代码生成）执行 → 最终仍然落到 RDD 上的 task。

相比手写 RDD，它的优势来自"看得懂数据"：有 schema 就能做列裁剪、谓词下推、选择更优的 join 策略，还能在运行中用真实统计修正计划。

## Catalyst 优化流程

```
SQL / DataFrame
  → Unresolved Logical Plan（语法树，未解析表名列）
  → Analysis（查 Catalog，解析类型与列，类型校验）
  → Logical Optimization（规则优化 RBO）
  → Physical Planning（按策略生成候选物理计划，用代价模型挑选）
  → Code Generation（whole-stage codegen，折叠成 Java 方法）
  → RDD[InternalRow] 执行
```

逻辑优化阶段常见规则：谓词下推、列裁剪、常量折叠、分区裁剪、limit 下推、聚合下推、子查询消除等。物理阶段则是"同一算子多种实现"的选择（如 join 的四种实现、聚合的 hash / sort 两条路）。

## Tungsten：执行侧的两板斧

- **堆外二进制格式**（`UnsafeRow`）与页式内存管理，绕开 JVM 对象开销与 GC（详见 [Memory](/docs/CS/Framework/Spark/Memory.md)）；
- **Whole-stage codegen**：把 Filter → Project → Scan 这样一串算子编译成一个方法，消除虚函数调用与迭代器开销。`explain()` 里看到的 `WholeStageCodegen (n)` 就是它；如果计划里没有 `*`（星号）标记，通常说明有 UDF 打断了代码融合。

## Adaptive Query Execution（AQE）

Catalyst 在**执行前**规划，只能依赖统计信息；AQE 则在 **shuffle 边界**用真实数据重新规划。Spark 3.2 起默认开启（`spark.sql.adaptive.enabled=true`）。三板斧：

| 能力 | 作用 | 参数 |
| ---- | ---- | ---- |
| 合并小分区 | 按 map 输出真实大小把相邻小分区合并到目标大小，避免大量碎片 task | `spark.sql.adaptive.coalescePartitions.enabled` |
| 倾斜 join 处理 | 检测到远超中位数的分区后拆分，并复制另一侧数据 | `spark.sql.adaptive.skewJoin.enabled` |
| Join 策略降级 | 运行中发现一侧被过滤得很小，把 SortMergeJoin 换成 BroadcastHashJoin，省掉一次 shuffle | 随 AQE 自动生效 |

实践含义：**可以把 `spark.sql.shuffle.partitions` 设得偏大**（让 AQE 去收缩），而不是费劲猜一个准确值。局限是 AQE 只在 shuffle 边界生效，源端的分区倾斜它无能为力（见 [Shuffle](/docs/CS/Framework/Spark/Shuffle.md)）。

## Join 策略怎么选

| 策略 | 触发条件 | 特点 |
| ---- | ---- | ---- |
| BroadcastHashJoin | 一侧小于 `spark.sql.autoBroadcastJoinThreshold`（默认 10MB） | 把小表广播，无 shuffle，最快 |
| ShuffleHashJoin | 两侧都可哈希、无排序需求 | 需要 shuffle，内存构建 hash 表 |
| SortMergeJoin | 默认兜底，尤其大表 join 大表 | 两侧排序后归并，稳定但需 shuffle 与排序 |
| BroadcastNestedLoopJoin | 非等值 join 且一侧小 | 笛卡尔式，代价随小表规模平方增长 |

调优抓手：让小表真的"小"（先过滤再 join）、适当上调广播阈值、必要时手动 `/*+ BROADCAST(t) */`。

## 统计信息与 CBO

物理计划挑选依赖统计信息。默认使用基于文件大小与行数的启发式；开启 **CBO**（`spark.sql.cbo.enabled=true`）后，需要先 `ANALYZE TABLE ... COMPUTE STATISTICS` 收集统计，才能让代价估计更准（如 join 顺序选择）。没有统计信息时，CBO 只是个开关，不会凭空变准。

## Spark 4.x 的 SQL 变化

以 4.0（4.x 首个版本）为代表：

| 变化 | 说明 |
| ---- | ---- |
| **ANSI SQL 模式默认开启** | 溢出、类型转换等行为更严格；不兼容时可用 `spark.sql.ansi.enabled=false` 回退 |
| **VARIANT 数据类型** | 原生处理半结构化 JSON，不用再全靠字符串解析 |
| **SQL 用户定义函数（SQL UDF）** | 直接在 SQL 里定义可复用函数，能被优化器看到 |
| **PIPE 语法** | 用 `\|>` 串联 SQL 变换，写长链路更顺手 |
| **字符串排序规则（collation）** | `COLLATE` 属性支持语言/大小写/重音敏感规则 |
| **会话变量、脚本化 SQL** | 支持控制流，便于把过程逻辑搬进 SQL |
| **Spark Connect 成熟** | 客户端-服务端解耦架构，Python/Java API 基本对齐，另有轻量客户端与多语言客户端 |
| **默认 JDK 17、Scala 2.13** | JDK 8/11 与 Scala 2.12 支持已移除 |

## 存储与读写

- 数据源走 **DataSource V2** 接口（Spark 3.x 起主推），支持列裁剪、谓词下推到存储层；
- 列式格式（Parquet / ORC）天然配合列裁剪与向量化读取，是数仓场景的默认选择；
- 分区表 + 分区裁剪（静态 + 动态 DPP）是降低扫描量的主要手段；
- Spark 4.0 起 `CREATE TABLE` 不写 `USING` 时默认使用 `spark.sql.sources.default` 指定的 provider（不再是硬编码 Hive）。

## Links

- [RDD](/docs/CS/Framework/Spark/RDD.md)
- [Shuffle](/docs/CS/Framework/Spark/Shuffle.md)
- [Memory](/docs/CS/Framework/Spark/Memory.md)
- [Streaming](/docs/CS/Framework/Spark/Streaming.md)
- [Spark](/docs/CS/Framework/Spark/Spark.md)

## References

1. [Spark Release 4.0.0（SQL / Spark Connect / ANSI / VARIANT 等）](https://spark.apache.org/releases/spark-release-4-0-0.html)
2. [Spark Docs - SQL Performance Tuning（AQE 自 3.2.0 起默认启用）](https://spark.apache.org/docs/latest/sql-performance-tuning.html)
3. [Spark Docs - Adaptive Query Execution](https://spark.apache.org/docs/latest/sql-performance-tuning.html#adaptive-query-execution)
