## Introduction

[Elasticsearch](https://www.elastic.co/guide/en/elasticsearch/reference/current/index.html) 是 Elastic Stack 核心的分布式 RESTful 搜索与分析引擎：以 JSON 文档为中心，提供近实时（NRT）全文检索、相关性打分与聚合分析，通过分片/副本水平扩展。

> [!IMPORTANT]
> **版本基线：Elasticsearch 9.5.5**（2026-10 发布，内置 Lucene 10.5.1、OpenJDK 27）。本篇各子专题的默认值均以 9.5.5 源码为准并标注 `文件:行号`。旧资料里的以下说法已失效：`minimum_master_nodes`、`node.master`/`node.data` 布尔配置、`"index": "not_analyzed"`、`/index/type/id` 文档 API、主分片默认 5、堆上限 32GB。升级至少需要 8.19 才能与 9.x 互通（索引兼容下限 8.0.0）。

OpenSearch 起源于 2021 年 Elastic 的许可证变更，基于最后一个 Apache 2.0 版本 ES 7.10.2 fork，详见 [OpenSearch](/docs/CS/Framework/ES/OpenSearch.md)。

## 笔记导航

| 专题 | 内容 |
| ---- | ---- |
| [Install：安装与节点角色](/docs/CS/Framework/ES/Install.md) | 目录结构、Bundled JDK 27、JVM 与堆（自动配置上限 31GB）、启动配置默认值、14 种节点角色、集群形成与插件管理 |
| [Mapping：数据模型与字段映射](/docs/CS/Framework/ES/Mapping.md) | text vs keyword、`not_analyzed` 打假、动态映射四档、索引级默认值、translog 与刷新 |
| [Query DSL：查询与分页](/docs/CS/Framework/ES/Query_DSL.md) | Query Then Fetch（含 can_match 预过滤）、filter vs query、核心查询语义、路由、search_after/PIT |
| [Analyzer：分词体系](/docs/CS/Framework/ES/Analyzer.md) | Analyzer 三段组成、standard 停用词空集打假、内置清单、custom/normalizer、中文分词选型 |
| [Troubleshooting：排障](/docs/CS/Framework/ES/Troubleshooting.md) | 写路径顺序、熔断器默认值（95%/40%/60%）、OOM 退出码、unassigned 19 种原因、红黄绿判定、ILM/DLM |
| [Replication：写入与复制协议](/docs/CS/Framework/ES/Replication.md) | bulk 分片分组、ReplicationOperation 链路、seq_no/primary_term/in-sync、noop、translog 内部（checkpoint/trim/generation）、flush 五触发源、Lucene 侧 ES 配置 |
| [Search Internals：搜索内部机制](/docs/CS/Framework/ES/Search_Internals.md) | 分片 topN=from+size、reduce 与 batchedReduceSize、DFS 统计求和、11 个 fetch 子 phase 顺序、preference 5 种、scroll/PIT 内部、eager_global_ordinals 预热 |
| [Cluster State：集群状态与分配](/docs/CS/Framework/ES/Cluster_State.md) | publication 四级流水线、`_state` Lucene 持久化、join 与 voting config、21+ 个分配决策器清单、磁盘水位 85/90/95、failed allocation 线性重试 |
| [Merge：段合并与 store](/docs/CS/Framework/ES/Merge.md) | Tiered vs LogByteSize（time-based 默认）、merge 参数表、ThreadPoolMergeScheduler（9.x 新默认）、forcemerge 语义、磁盘布局与 HybridDirectory |
| [Thread Pools：线程池模型](/docs/CS/Framework/ES/Thread_Pools.md) | 24 个池清单、协调/执行分离、三种 executor 与拒绝策略、429 来源、inflight breaker 与线程池两条背压路径 |
| [Lucene：底层检索引擎](/docs/CS/Framework/ES/Lucene.md) | 倒排索引、不可变 segment、段合并、shard/segment 层级 |
| [Cluster：集群与选举](/docs/CS/Framework/ES/Cluster.md) | 分片/副本、发现与主节点选举、读写路径、Query Then Fetch |
| [Scripting / Painless](/docs/CS/Framework/ES/Script.md) | 脚本上下文、doc vs _source、编译缓存陷阱、runtime fields |
| [Kibana](/docs/CS/Framework/ES/Kibana.md) | 可视化、KQL、Dev Tools |
| [Beats / Filebeat](/docs/CS/Framework/ES/Beats.md) | 轻量采集、harvester/registry、背压 |
| [Logstash](/docs/CS/Framework/ES/Logstash.md) | pipeline、grok、持久化队列 |
| [OpenSearch](/docs/CS/Framework/ES/OpenSearch.md) | 许可分叉、与 ES 的兼容性差异 |

## Architecture

### 节点角色

9.x 角色定义在 `DiscoveryNodeRole.java:145-271`，共 14 种（默认节点是下述除 `voting_only`/`search` 外的合体；`node.master`/`node.data` 布尔配置已移除，统一走 `node.roles` 列表）：

| 角色 | 职责 | 资源画像 |
| ---- | ---- | ---- |
| `master`（m） | 集群管理：索引元数据、分片分配、选举 | CPU 要求高、内存要求低 |
| `data` + `data_content/hot/warm/cold/frozen`（d/s/h/w/c/f） | 存分片、执行 CRUD/搜索/聚合 | CPU、内存都要高 |
| `ingest`（i） | 入库前预处理（pipeline） | CPU 偏高 |
| `ml`（l）/ `transform`（t） | 机器学习 / 转换任务 | 按需 |
| `remote_cluster_client`（r） | 跨集群检索客户端 | 网络带宽高 |
| `voting_only`（v）/ `search`（S） | 仅投票 / 仅搜索（均非默认） | — |

生产常见拆法：独立 master 节点组（3 个）、hot/warm 分层 data 节点、协调负载由任意节点兼任（ES 没有独立 coordinating 角色，所有节点都能当协调节点）。详见 [Install](/docs/CS/Framework/ES/Install.md)。

### 日志采集链路

高可用场景不让业务系统直连 Logstash，而是日志先落本地文件：

```
业务写本地日志 -> Filebeat 采集 -> Kafka(缓冲削峰) -> Logstash(解析转换) -> Elasticsearch -> Kibana
```

Filebeat 用「背压敏感协议」按 Logstash 处理速率调整读取速度，下游拥塞时自动降速，未确认事件落队列；链路细节见 [Beats](/docs/CS/Framework/ES/Beats.md) 与 [Logstash](/docs/CS/Framework/ES/Logstash.md)。

### 典型应用场景

- **宽表 / 跨库 Join**：把多张业务表冗余进宽文档，一次检索替代跨库 join；
- **全文检索**：倒排索引 + BM25 相关性排序，见 [Lucene](/docs/CS/Framework/ES/Lucene.md) 与 [Query DSL](/docs/CS/Framework/ES/Query_DSL.md)；
- **日志与可观测性**：配合 Kibana/ILM/DLM 做留存治理，见 [Troubleshooting](/docs/CS/Framework/ES/Troubleshooting.md)；
- **向量检索**：9.x 的 kNN 搜索会强制走 DFS 打分（`TransportSearchAction.java:836-841`）。

## Links

- [Install：安装与节点角色](/docs/CS/Framework/ES/Install.md)
- [Mapping：数据模型与字段映射](/docs/CS/Framework/ES/Mapping.md)
- [Query DSL：查询与分页](/docs/CS/Framework/ES/Query_DSL.md)
- [Analyzer：分词体系](/docs/CS/Framework/ES/Analyzer.md)
- [Troubleshooting：排障](/docs/CS/Framework/ES/Troubleshooting.md)
- [Lucene：底层检索引擎](/docs/CS/Framework/ES/Lucene.md)

> 更深一层的机制拆解（写入复制、搜索内部、集群状态、段合并、线程池）见上方「笔记导航」表。

## References

1. [Elasticsearch Reference](https://www.elastic.co/guide/en/elasticsearch/reference/current/index.html)
2. [Elastic Stack 文档总入口](https://www.elastic.co/guide/index.html)
3. [elastic/elasticsearch v9.5.5 源码](https://github.com/elastic/elasticsearch/tree/v9.5.5)
