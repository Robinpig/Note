## Introduction

大数据处理计算模式

- batch
- stream
- interactive
- graph

batch

MapReduce Spark Hive Flink Pig

Stream
Storm Spark Streaming Flink Samza

Interactive
Presto
Impala
Druid
Drill

Graph
Giraph
Graphx
Gelly

流计算和批计算区别


|             | Batch        | Streaming |
|-------------|--------------|-----------|
| Latency     | high         | low       |
| Data volume | Large chunks | Real-time |
| Complexity  | low          | high      |
| Use cases           |     Scenarios where data can be processed in intervals without immediate action.          |   Scenarios requiring real-time insights and immediate action.        |
|             |              |           |



流式计算 实时低延迟 数据动态无边界 任务持续运行
批计算本身是特殊的流计算




## Links

- [Hadoop](/docs/CS/Framework/Hadoop/Hadoop.md)
