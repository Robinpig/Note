## Introduction

大数据技术演进里最反直觉的一件事是：**绕了一圈，最后所有人都在写 SQL**。MapReduce 曾要求把逻辑拆成 map 与 reduce 两个函数，Pig 用脚本语言描述数据流，Spark 早期以 RDD 的函数式 API 为卖点——但最终留在生产里的，绝大多数是 SQL 或者能用 SQL 表达的声明式流水线。

原因不复杂：**SQL 把"怎么算"交给了引擎**，于是优化可以做一次、惠及所有查询；而手写代码把执行计划钉死了，优化只能靠人。当一个组织的查询有成千上万条时，这个差别是决定性的。

这一层的产品叫 SQL-on-Hadoop / SQL-on-lakehouse 引擎，它们的差别不在 SQL 方言（大同小异），而在**执行模型**：算得快还是算得稳。

> [!NOTE]
> 版本口径：[Hive](/docs/CS/DB/Hive/Hive.md) **4.2.1**（执行引擎收敛为 Tez 唯一，CBO 由 Apache Calcite 驱动，4.0 升 1.25、4.1 升 1.33）、Spark **4.2.0**、[Flink](/docs/CS/Framework/Flink/Flink.md) **2.3.0**、Trino **483**（2026-07-17）。

## Two Execution Models

引擎的选择本质上是在两个不兼容的目标之间做取舍：**单次查询快**，还是**失败能低成本恢复**。

| | 批处理型（Hive / Spark SQL） | MPP 型（Trino / Impala） |
| :--- | :--- | :--- |
| 中间结果 | 落盘，stage 间物化 | 内存流水线，不落盘 |
| 容错 | 重算失败的分区 / stage | 失败就重跑整个查询 |
| 单次延迟 | 秒到分钟 | 亚秒到秒 |
| 数据规模上限 | 极大（磁盘兜底） | 受集群内存约束 |
| 典型负载 | ETL、大表 join、全量回溯 | 即席探索、BI 报表 |

这不是优劣问题，而是**容错与延迟的交换**。批处理落盘是为了让失败只重算一小段（[Spark](/docs/CS/Framework/Spark/Spark.md) 靠 RDD 血统重算，见 [RDD](/docs/CS/Framework/Spark/RDD.md)）；MPP 不落盘换来了流水线并行，代价是任何失败都从头再来。

[Flink](/docs/CS/Framework/Flink/Flink.md) SQL 是第三类：**流 SQL**。它的查询是常驻的、结果持续更新，输入是无界流。SQL 语法与前两者接近（都是 Calcite / SQL 标准方言），但语义不同——`SELECT` 在流上的含义是"对流做持续转换"，聚合是有状态的增量计算，详见 [Table SQL](/docs/CS/Framework/Flink/Table_SQL.md)。

## The Lineage

- **Hive**：第一个把 SQL 带到 Hadoop 上的引擎，把 SQL 编译成 MapReduce 作业。它的历史价值在于证明了 SQL 在大数据上可行，代价是慢（每个 stage 都要读写 HDFS）。4.x 的执行引擎已收敛为 **Tez 唯一**（Hive on Spark 移除、on MR 弃用），配合 LLAP 常驻守护做缓存，详见 [Execution Engines](/docs/CS/DB/Hive/Execution_Engines.md)。
- **Spark SQL**：用内存计算 + 代码生成把交互式查询拉到可用区间，同时保留批处理级的容错。它是"两头都还行"的折中，也是使用率最高的一档。
- **Trino / Presto / Impala**：为交互式而生的 MPP 引擎，不存数据、只做联邦查询，见 [Presto](/docs/CS/DB/Presto.md)。Impala 是 C++ 实现、绑定 HDFS/HBase 生态的同类方案。
- **Flink SQL**：流与批统一的 SQL，是流批一体落到业务侧的接口。

自带存储的 OLAP 引擎（[ClickHouse](/docs/CS/DB/ClickHouse.md)、[Doris](/docs/CS/DB/Doris.md)、[Druid](/docs/CS/DB/Druid/Druid.md)）不在这个谱系里：它们是"存算一体的分析型数据库"，数据是自己的格式与副本管理，查询快是因为数据布局为查询服务，而不是因为它们读了湖上的 Parquet。

## Query Optimization

三件套几乎出现在所有现代引擎里，只是成熟度不同。

**规则优化（RBO）**是确定性的改写：谓词下推、列裁剪、常量折叠、投影消除、`UNION` 合并。它不依赖任何统计信息，永远安全。

**代价优化（CBO）**要在多种等价计划里选最便宜的，核心难点是**基数估算**——预估每个算子输出多少行。join 顺序、join 类型（broadcast / shuffle / sort-merge）的选择全靠它。基数估算的质量直接取决于统计信息：行数、列的 distinct 值数（NDV）、直方图、null 比例、min/max。

> [!WARNING]
> CBO 只和统计信息一样好。**没有 `ANALYZE TABLE` 收集的统计，优化器就只能靠假设**，此时选出的 join 顺序可能比手写还差。这是"明明建了索引 / 分了区，查询还是慢"最常见的根因——不是引擎不行，是优化器在瞎猜。

**向量化执行**一次处理一批同列的值而非一行，摊薄解释开销并让编译器能生成 SIMD 指令。它与列存是共生关系，原理见 [Storage Format](/docs/CS/BigData/Storage_Format.md)。

**代码生成（codegen）**把一串算子编译成一段紧凑的字节码/机器码，消除算子间的虚函数调用与中间对象。Spark 的 whole-stage codegen 把整个 stage 的算子链编成一个函数，是它能在 JVM 上跑出接近 C++ 性能的关键；代价是编译本身耗时，极短查询可能反而不划算。

三者叠加时还有一个运行时的兜底：**自适应执行**在 stage 完成后用真实统计修正后续计划，动态改 join 策略、合并小分区、拆分倾斜分区（见 [Shuffle and Data Skew](/docs/CS/BigData/Shuffle.md)）。

## Federated vs Self-Contained

一个容易被忽略的分界：引擎**是否自带存储**。

- **联邦查询引擎**（Trino / Presto）不存任何数据，通过 connector 把异构数据源接成虚拟表。优势是零搬迁——跨 MySQL 与 S3 的 join 直接就能跑；代价是性能受限于远端数据源，且没有缓存与本地数据布局优化。
- **自带存储的引擎**（ClickHouse / Doris / Druid / Hive 托管表）数据在本引擎的格式与副本体系里，能靠排序键、物化视图、预聚合把查询压到极快；代价是数据要多存一份，且迁移成本高。

湖仓实践通常是**两者并用**：湖上放 Parquet + Iceberg 做统一底座，用 Trino / Spark SQL 做通用查询；把最热的、对延迟最敏感的那部分导入 ClickHouse 或 Doris 做加速层。判断标准很实际——如果某份数据每天被同一类查询反复扫几百次，就该进加速层；如果只是偶尔探索，留在湖上。

## How to Choose

| 需求 | 选择 |
| :--- | :--- |
| 离线 ETL、大表 join、需要强容错 | Spark SQL |
| 交互式即席探索、跨源联邦 | Trino / Presto |
| 实时流上做 SQL 转换 | Flink SQL |
| 已有 Hive 数仓、需要 ACID 与 HMS | Hive on Tez |
| 固定报表、亚秒级响应 | ClickHouse / Doris（作为加速层） |

多引擎并存是常态而非浪费：**它们共享同一份开放格式的数据**（见 [Storage Format](/docs/CS/BigData/Storage_Format.md) 与 [Table Format](/docs/CS/BigData/Table_Format.md)），这正是湖仓主张"开放存储"的意义——引擎可以换，数据不用动。

## Links

- [BigData](/docs/CS/BigData/BigData.md)
- [Shuffle and Data Skew](/docs/CS/BigData/Shuffle.md)
- [Lakehouse](/docs/CS/BigData/Lakehouse.md)
- [Presto](/docs/CS/DB/Presto.md)
- [Hive](/docs/CS/DB/Hive/Hive.md)
- [Spark SQL](/docs/CS/Framework/Spark/SQL.md)

## References

1. [Apache Calcite](https://calcite.apache.org/)
2. [Apache Spark SQL Performance Tuning](https://spark.apache.org/docs/latest/sql-performance-tuning.html)
3. [Trino Documentation](https://trino.io/docs/current/)
4. [Apache Hive - Cost-based optimization](https://cwiki.apache.org/confluence/display/Hive/Cost-based+optimization+in+Hive)
5. [Presto: SQL on Everything (IEEE Data Eng. Bull. 2019)](https://research.facebook.com/publications/presto-sql-on-everything/)
