## Introduction

Application performance monitor tool for distributed systems, especially designed for microservices, cloud native and container-based (Kubernetes) architectures.

## Architecture

从逻辑上讲，SkyWalking分为四个部分：探针，平台后端，存储和UI

- 探针收集数据并重新格式化以符合SkyWalking的要求（不同的探针支持不同的来源）。
- 平台后端，支持数据聚合，分析并驱动从探针到UI的流程。该分析包括SkyWalking本机跟踪和度量，第三方，包括 Istio 和 Envoy 遥测，Zipkin跟踪格式等。您甚至可以通过使用针对本机度量的Observability Analysis Language和针对扩展度量的Meter System来定制聚合和分析。
- 存储设备通过开放/可插入的界面存储 SkyWalking 数据。您可以选择现有的实现，例如 ElasticSearch，H2或由 Sharding-Sphere 管理的 MySQL 集群，也可以实现自己的实现。
- UI是一个高度可定制的基于Web的界面，允许 SkyWalking 最终用户可视化和管理SkyWalking数据


对于Java语言程序，SkyWalking探针使用 [Java Agent](/docs/CS/Java/JDK/Agent.md) 来实现




## Links

- [Tracing](/docs/CS/Distributed/Tracing/Tracing.md)

## References

1. [SkyWalking中文站](https://skywalking.apache.org/zh/)