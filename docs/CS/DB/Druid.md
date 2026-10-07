## Introduction

[Apache Druid](https://druid.apache.org/) 是面向**实时分析（OLAP）**的分布式数据存储，为大规模数据集上的快速切片（slice-and-dice）查询设计。典型场景：实时摄取、低延迟即席查询、高可用。

## Core Concepts

- **Datasource**：逻辑表，按时间分区。
- **Segment**：Druid 最小存储/分发单位——按时间分片 + 列存（dictionary encoding + bitmap 倒排），不可变、可复制。
- **Rollup**：摄取时按维度聚合（可选），预计算降低存储与查询量。
- **Timestamp**：一级分区键，强时间序。

## Architecture (Multi-Role)

- **Overlord**：接收摄取任务（indexing task）并分配。
- **MiddleManager / Peon**：执行摄取 task，生成 Segment。
- **Historical**：加载并提供已成型 Segment 的查询（从深度存储拉取后缓存）。
- **Broker**：接收查询，路由到相关 Historical/MiddleManager 并合并结果。
- **Coordinator**：管理 Segment 在 Historical 上的分布与负载均衡（基于深度存储 S3/HDFS）。
- **Router**（可选）：查询统一入口。

## Ingestion

- **实时**：Kafka Indexing Service（原生 Kafka 消费，偏向 exactly-once）。
- **批**：Hadoop/Spark 任务生成 Segment；也支持 Kafka 实时 + 批回补。

## Comparison

- vs [ClickHouse](/docs/CS/DB/ClickHouse.md)：Druid 偏实时摄取 + 多角色弹性；ClickHouse 偏极速扫描 + 简单部署。
- vs Pinot：架构相近，Pinot 与 Kafka 耦合更深。

## Links

- [ClickHouse](/docs/CS/DB/ClickHouse.md)
- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)

## References

- [Apache Druid Documentation](https://druid.apache.org/docs/)
