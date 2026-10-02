## Introduction

Presto 是一个**分布式 SQL 查询引擎**，最初由 Facebook（现 Meta）为交互式分析 Hive/PB 级数据而开发（2012 年开源），定位是"不存数据、只做联邦查询计算"：通过 connector 插接异构数据源（Hive/Iceberg、MySQL、Kafka、ClickHouse、Elasticsearch 等），用一条 SQL 跨源 join，数据从源端拉取、在 Presto worker 的内存中流水线计算。它是 Ad-hoc 交互式分析与数据湖查询的经典引擎。

## 架构：MPP 但不存数据

```
            ┌──────────────┐
 SQL ──────► │ Coordinator  │ 解析/优化/生成 Stage 计划、调度 split
            └──────┬───────┘
        ┌──────────┼──────────┐
        ▼          ▼          ▼
    ┌───────┐  ┌───────┐  ┌───────┐
    │Worker │  │Worker │  │Worker │  并行执行 task / exchange 数据
    └───┬───┘  └───┬───┘  └───┬───┘
        ▼          ▼          ▼
   Hive/S3   MySQL/Kafka    ES ...   ← 通过 Connector 即席读取
```

- **Coordinator**：SQL 解析、成本优化、把计划切成 Stage/Task，向 worker 分发可并行的最小调度单元 **split**（如一个文件、一个分片）；
- **Worker**：执行扫描、聚合、join，Stage 之间通过 exchange 流式传输页面（page）；
- **无状态**：worker 不持久化数据（spill 到磁盘只是内存溢出保护），存储完全交给 connector 背后的系统——这与 [ClickHouse](/docs/CS/DB/ClickHouse.md)、[Doris](/docs/CS/DB/Doris.md) 这种"存算一体"的 MPP 库形成鲜明对比。

## 执行模型要点

- **流水线执行（pipeline）**：上游产出一页数据即可推给下游，不等整个 stage 完成，降低延迟；
- **向量化处理**：一批列值一起运算，减少虚函数与解释开销；
- **内存计算**：状态尽量放内存（哈希表、join build 侧），大查询可能 OOM，需要资源队列与 spill 策略；
- Stage 之间是 **stage 边界 shuffle**：聚合/join 需要重分区时走 exchange。

## 典型场景与边界

适合：数据湖上的交互式探索（Hive/Iceberg/Hudi + S3/HDFS）、跨源联邦查询（MySQL 事实表 join 维表）、BI 报表即席查询、ETL 批处理（CREATE TABLE AS）。

不适合：需要高并发点查（OLTP 是 MySQL 的领域）、需要强事务、亚毫秒级服务化查询（那是专门的 OLAP 存储或预聚合的场景）、复杂更新（Presto 不维护数据，写回依赖 connector 能力）。

## 版本与生态

- **PrestoDB**（Facebook/Presto Foundation）与 **Trino**（原 PrestoSQL，核心团队出走后的社区主线）两个分支协议/语法基本兼容，选型时 Trino 迭代更快、connector 生态更活跃；
- 同类引擎对照：Spark SQL 偏批处理与 ETL（同思路但 stage 落盘、面向大吞吐）、Impala（C++、Hadoop 生态）、StarRocks/Doris（存算一体 MPP）、[ClickHouse](/docs/CS/DB/ClickHouse.md)（单机向量化、单表聚合强）。

## Links

- [DataBases](/docs/CS/DB/DB.md)
- [ClickHouse](/docs/CS/DB/ClickHouse.md)
- [Doris](/docs/CS/DB/Doris.md)
- [HBase](/docs/CS/DB/HBase.md)
- [OLAP](/docs/CS/DB/DB.md?id=olap)

## References

1. [Presto: SQL on Everything（论文）](https://research.facebook.com/publications/presto-sql-on-everything/)
2. [Trino 官方文档](https://trino.io/docs/current/)
