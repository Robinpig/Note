## Introduction

本目录是 [Loki](/docs/CS/Distributed/Tracing/Loki.md) 的源码级分册。主入口负责数据模型、组件概览与 LogQL；这里把「一条日志如何被接收、定位、读取，以及故障时到底还剩下什么」展开到实现层。

全部机制以 **Loki v3.7.10** 为基线，tag 指向 commit `c792f58577a46c64b0a8e808d7c643ed0e8c5e83`。文中默认值均指未显式覆盖配置时的行为；Loki 4.0 的 Kafka、DataObjects 与新一代查询引擎属于已公布演进方向。v3.7.10 已有部分默认关闭的实验代码，但不能把新架构当作默认生产能力。

## Write Becomes Storage

写入链路的核心不是「收到请求即入库」，而是「达到写入 quorum 后进入内存与 WAL，再异步形成 chunk 和索引」。[Write Path](/docs/CS/Distributed/Tracing/Loki/Write_Path.md) 从 `/loki/api/v1/push` 出发，经过 distributor 的校验、限流和一致性哈希，进入 ingester 的 stream/chunk 生命周期，最后追踪 WAL、flush 与非原子上传。

理解这一段的关键是三个时间点：HTTP 成功返回时数据已经到达多少个 ingester；ingester 写入 WAL 意味着什么；chunk 与 TSDB index 分别何时进入对象存储。它们不是同一个持久化承诺。

## Storage Makes Queries Possible

日志正文并不直接参与索引定位。[Storage](/docs/CS/Distributed/Tracing/Loki/Storage.md) 先拆开三层格式：对象存储里的 chunk envelope、chunk 内部的 block 与 structured metadata 符号表、只保存 labels 和 chunk 引用的 TSDB series。查询器正是沿着 `matchers -> postings -> series -> ChunkMeta -> ChunkRef -> object key` 找到正文。

这一段还解释 schema v13 为什么同时意味着 chunk V4、TSDB FormatV3 与 24 小时索引周期，以及 compactor 如何把多租户索引压缩成 per-tenant TSDB、执行 retention 和删除请求。index gateway 只服务索引，不代理 chunk 正文。

## Query Is a Pipeline of Elimination

[Query Path](/docs/CS/Distributed/Tracing/Loki/Query_Path.md) 把一次查询拆成排队、时间切分、fingerprint keyspace 分片、索引定位、chunk 拉取与解码、LogQL pipeline、结果合并。优化大多是「提前排除不可能命中的 chunk」或「减少重复解压」，而不是改变日志语义。

Bloom filter 是其中最容易被误解的一层：v3.7.10 中它仍为实验特性，索引的是 structured metadata，不是任意日志正文；误报只会多扫 chunk，不会漏数。查询前端、scheduler、querier 和 LogQL engine 的职责也不能混为一层。

## Failure Defines the Real Contract

[Consistency](/docs/CS/Distributed/Tracing/Loki/Consistency.md) 讨论 ring、RF/quorum、zone-aware replication、WAL 故障窗口、读取 quorum、多租户 limits 与删除生命周期。Loki 提供的是复制、quorum 与失败检测语义，不是 Raft 式跨副本强一致，也不是 exactly-once 日志管道。

部署形态也属于一致性边界：monolithic 把主体组件放进一个进程，但 bloom 构建与查询不支持 single-binary；SSD 拆成 write/read/backend，但已在 v3.7.10 文档中标记弃用；microservices 提供最细的扩缩容粒度，同时带来最高的运维复杂度。

## Links

- [Tracing](/docs/CS/Distributed/Tracing/Tracing.md)
- [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md)
- [Grafana Tempo](/docs/CS/Distributed/Tracing/Tempo.md)
- [Grafana Alloy](/docs/CS/Distributed/Tracing/Alloy.md)
- [Distributed Systems](/docs/CS/Distributed/Distributed.md)

## References

1. [Loki architecture](https://grafana.com/docs/loki/latest/get-started/architecture/)
2. [Loki components](https://grafana.com/docs/loki/latest/get-started/components/)
3. [Loki deployment modes](https://grafana.com/docs/loki/latest/get-started/deployment-modes/)
4. [Loki v3.7.10 source](https://github.com/grafana/loki/tree/v3.7.10)
5. [Loki v3.7.10 release](https://github.com/grafana/loki/releases/tag/v3.7.10)
6. [Grafana Labs acquires Logline](https://grafana.com/blog/grafana-labs-acquires-logline/)
7. [Inside Loki's new architecture for faster logging at petabyte](https://grafana.com/blog/grafanacon-2026-on-demand-sessions-are-now-available#inside-lokis-new-architecture-for-faster-logging-at-petabyte)
