## Introduction

大数据是指数量巨大且迅速增长的数据，这些数据过于庞大和复杂，传统的数据处理工具难以管理。这些数据存在多种形式，包括结构化（例如表格）、半结构化（例如 JSON、XML）和非结构化（例如文本、图像、视频）。随着设备、传感器、在线服务和数字平台的爆发式增长，数据的生成速度前所未有。这种增长使得组织必须采用先进的工具和技术来有效地捕获、存储、分析和利用这些数据



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
