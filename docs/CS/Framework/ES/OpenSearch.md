## Introduction

OpenSearch 是一个开源的分布式搜索与分析套件，起源于 **2021 年 Elastic 的许可证变更**：Elastic 把 Elasticsearch 与 Kibana 从 Apache 2.0 改为 SSPL/Elastic License（不再是 OSI 开源许可），AWS 于是联合社区，基于 Elasticsearch **最后一个 Apache 2.0 版本 7.10.2** fork 出 OpenSearch（及对应的 OpenSearch Dashboards，即原 Kibana 的 fork），交由 Linux Foundation 旗下的 OpenSearch Software Foundation 治理。

它与 AWS 生态深度集成，是 Amazon OpenSearch Service（原 Amazon Elasticsearch Service）背后的引擎，也可在自建/K8s 上运行。

## What It Includes

- **OpenSearch**：搜索引擎本体（fork 自 ES 7.10.2），REST API、索引/分片/集群概念与早期 ES 高度一致。
- **OpenSearch Dashboards**：可视化前端（fork 自 Kibana）。
- 数据采集仍可对接 Logstash、Fluent Bit、OpenTelemetry Collector 等；也有 OpenSearch 提供的 Data Prepper 作为日志/追踪摄取管道。
- 开箱的安全插件（TLS、RBAC、字段级/文档级权限）、告警、异常检测、Index State Management、跨集群复制、SQL/PPL 查询语言等。

## Compatibility and Divergence

刚 fork 时 OpenSearch 与 ES 7.10.2 在线路协议上基本兼容（许多客户端可直接指向任一方），但经过数年独立演进，正如主笔记所述，**目前二者在 API、插件、默认配置和安全模型上已不再完全兼容**：

| 维度 | Elasticsearch（8.x） | OpenSearch（2.x） |
| ---- | ---- | ---- |
| 许可 | Elastic License v2 / SSPL（非传统开源），另有 AGPL 选项 | Apache 2.0（开源） |
| 版本基线 | 7.10 后持续闭源演进（向量搜索、ES|QL 等新特性） | 从 7.10.2 分叉独立演进 |
| 默认安全 | 8.x 默认开启 TLS 与认证 | 安全插件但配置模型不同 |
| 客户端/API | 新 API、新 DSL 各自扩展，存在差异 | 提供兼容模式（compatibility mode）模拟 7.10 行为 |
| 典型生态 | Elastic 官方 Stack、企业版特性 | AWS 服务、开源插件社区 |

实际迁移不能假设“无缝替换”，需要验证：DSL/查询行为、索引设置、分词/插件、客户端版本、安全配置、以及向量字段/聚合等特性差异。OpenSearch 的 Lucene/Segment 底层原理与 ES 一致，见 [Lucene](/docs/CS/Framework/ES/Lucene.md) 与 [Cluster](/docs/CS/Framework/ES/Cluster.md)。

## When to Choose

- 受合规/采购约束必须使用 Apache 2.0 真正开源协议，或深度使用 AWS 托管服务：倾向 OpenSearch。
- 依赖 Elastic 官方最新特性、企业支持与 Elastic Stack 全家桶：倾向 Elasticsearch。
- 两者都适用于全文检索、日志分析、可观测性与（近年的）向量/语义检索场景；选型时把许可证、运维托管、特性缺口与迁移成本一起评估。

## Links

- [Elasticsearch](/docs/CS/Framework/ES/ES.md)
- [Lucene](/docs/CS/Framework/ES/Lucene.md)
- [ES Cluster](/docs/CS/Framework/ES/Cluster.md)
- [Kibana（OpenSearch Dashboards 的对应物）](/docs/CS/Framework/ES/Kibana.md)

## References

1. [OpenSearch Official Site](https://opensearch.org/)
2. [Introducing OpenSearch (AWS, 2021)](https://aws.amazon.com/blogs/opensource/introducing-opensearch/)
3. [OpenSearch Documentation](https://docs.opensearch.org/)
4. [OpenSearch vs Elasticsearch compatibility](https://opensearch.org/docs/latest/tools/index/)
