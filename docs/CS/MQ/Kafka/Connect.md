## Introduction

Kafka Connect 是 Apache Kafka 生态中**在 Kafka 与外部数据存储之间搬数据的可扩展运行时**：它提供统一的 API 与集群化的 worker 进程，让你用现成的 **connector 插件**（而非手写的 Producer/Consumer）把数据库、对象存储、消息系统、数据湖等接入 Kafka。典型用途：CDC（变更数据捕获）把 MySQL binlog 流入 Kafka，或把 Kafka 主题落盘到 S3 / Elasticsearch。

## 核心概念

- **Connector**：逻辑作业，描述「从哪到哪」（如 `SourceConnector` 读外部系统写 Kafka，`SinkConnector` 读 Kafka 写外部系统）。配置驱动，无需写代码。
- **Task**：Connector 的并行执行单元；Connector 把工作拆成若干 Task 分发到 worker，实现水平扩展与容错（Task 失败由框架重调度）。
- **Worker**：运行 Connector/Task 的进程，有两种模式：
  - **Standalone**：单进程跑全部，适合边缘/简单场景。
  - **Distributed**：多 worker 组成集群，REST API 提交配置，任务自动均衡与故障转移（生产首选）。
- **Converter**：决定数据在 Kafka 里的序列化形态（Avro / JSON / Protobuf），常配合 Schema Registry 做 schema 演进。
- **Offset / Exactly-once**：源端用 offset 记录消费位点支持断点续传；新版支持 exactly-once 语义（基于事务），避免重放导致重复。

## 与 Kafka 其他组件的边界

| 组件 | 角色 | 何时用 |
|---|---|---|
| Producer/Consumer | 应用直接读写 | 业务代码内集成 |
| Kafka Connect | 系统间批量/增量同步 | 把 DB/存储/SAAS 接进 Kafka |
| Kafka Streams | 流内计算转换 | 主题间做实时聚合/Join |

Connect 解决「管道」，Streams 解决「处理」，二者常串联：Connect 把源吸入 → Streams 计算 → Connect 把结果下沉。

## Links

- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)
- [Kafka Streams](/docs/CS/MQ/Kafka/Streams.md)
- [MQ](/docs/CS/MQ/MQ.md)

## References

- [Kafka Connect Documentation](https://kafka.apache.org/documentation/#connect)
- [Kafka Connect Deep Dive – Configuration and Operations](https://www.confluent.io/blog/kafka-connect-deep-dive-configuring-and-operating/)
