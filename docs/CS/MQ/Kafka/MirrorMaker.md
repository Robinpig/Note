## Introduction

Kafka 的镜像功能可以维护现有 Kafka 集群的副本。下图展示了如何使用 _MirrorMaker_ 工具将源 Kafka 集群镜像到目标（镜像）Kafka 集群。
该工具使用 Kafka consumer 从源集群消费消息，并通过嵌入式 Kafka producer 将这些消息重新发布到本地（目标）集群。

## References
1. [Kafka mirroring (MirrorMaker)](https://cwiki.apache.org/confluence/pages/viewpage.action?pageId=27846330)
