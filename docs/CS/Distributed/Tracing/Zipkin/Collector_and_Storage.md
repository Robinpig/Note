## Introduction

本篇展开 [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md) 的服务端：**Collector** 如何接收并校验 span，以及 **Storage** 这个可插拔存储抽象背后的后端选型与运维取舍。

## Collector

当追踪数据抵达 Zipkin collector 守护进程（openzipkin/zipkin 里与 storage / query / UI 同处一个进程）后，它会：

1. **接收**：支持 HTTP（`POST /api/v2/spans`）、Kafka、RabbitMQ、Scribe 等通道。
2. **校验**：检查 span 结构合法性（如 `traceId` / `id` 非空、`timestamp` 单位正确）。
3. **建立索引**：写入可被检索的索引，供 Query Service 按 service / operation / tag / 时间范围过滤。
4. **持久化**：交给 `StorageComponent` 落到所选后端。

collector 本身**无状态、可水平扩展**——但在 `zipkin-server` 单进程模型中，扩展意味着整体扩容多个 server 实例，而非单独扩 collector。

## Storage

Zipkin 把存储做成**可插拔抽象 `StorageComponent`**：写路径与读路径都由它封装，后端可替换。原生与社区支持的后端：

| 后端 | 定位 | 备注 |
| --- | --- | --- |
| **内存（in-memory）** | 默认，零配置 | 重启即丢，仅适合演示与本地开发 |
| **Cassandra** | Twitter 内部原始选型 | 写入扩展性强、schema 灵活，运维较重 |
| **Elasticsearch** | 生产常用 | 检索能力强、生态成熟（v7/v8 线） |
| **MySQL** | 简单上手 | **v1 组件**，schema 直白、字段即列、可做 ad-hoc SQL 查询，但**不为性能设计**，数据量大后查询会退化到秒级；用 MySQL 5.6+ 特性，实测基于 MariaDB 10.11 |

其它后端可能以第三方扩展形式提供。后端选择由环境变量驱动，例如 `STORAGE_TYPE=elasticsearch` 配合 `ES_HOSTS`、`STORAGE_TYPE=cassandra3` 配合 `CASSANDRA_CONTACT_POINTS`、`STORAGE_TYPE=mysql` 配合 `MYSQL_HOST` 等。

### Search Toggle

`SEARCH_ENABLED=false`（即 `StorageComponent.Builder.searchEnabled(false)`）可**关闭检索索引**：此时 trace 只能按 `traceId` 点查（`GET /trace/{traceId}`），无法按 service / tag / duration 检索。关闭检索可以**降低存储成本、提升写入吞吐**，前提是存在其它发现 traceId 的途径（如日志里带 traceId）。这适用于「只在线排查已知 traceId」的高写入场景。

### Dependency Aggregation

Zipkin 的依赖图（哪些服务调用了哪些服务、调用量与错误量）来自**离线聚合任务**：按时间窗口扫描 span，计算服务对的 `callCount` / `errorCount`，产出 `DependencyLink`。MySQL 后端**不**需要该 job（schema 直接支持），但 Cassandra / Elasticsearch 通常需要周期性运行 `zipkin-dependencies` 作业来填充依赖数据、加速 `/dependencies` 查询。

## Operational Notes

- 从源码运行 `zipkin-server` 需 **JDK 17+**；官方镜像 `openzipkin/zipkin` 与 `ghcr.io/openzipkin/zipkin` 已包含运行环境。
- 版本基线：**3.6.x（3.6.1，2026-04）**；另有 `zipkin-slim` 精简镜像（不含某些 collector 依赖）与 Helm Chart（`helm repo add zipkin https://zipkin.io/zipkin-helm`）。
- 内存后端在重启后数据全失；生产应选持久化后端并配置合理的采样与 `SEARCH_ENABLED`。

## Links

- [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md) — 枢纽页与 Quickstart
- [Zipkin Architecture](/docs/CS/Distributed/Tracing/Zipkin/Architecture.md) — 组件与数据流
- [Zipkin Query and UI](/docs/CS/Distributed/Tracing/Zipkin/Query_and_UI.md) — 检索 API 与依赖图
- [Jaeger](/docs/CS/Distributed/Tracing/Jaeger.md) — Jaeger 存储后端对照

## References

1. [Zipkin — Storage](https://github.com/openzipkin/zipkin) — 后端与 `StorageComponent` 说明
2. [Zipkin Docker image](https://hub.docker.com/r/openzipkin/zipkin) — 环境变量与存储配置
3. [zipkin-dependencies](https://github.com/openzipkin/zipkin-dependencies) — 依赖聚合作业
