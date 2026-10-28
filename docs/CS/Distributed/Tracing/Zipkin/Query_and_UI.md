## Introduction

本篇展开 [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md) 的**读取侧**：Query Service 提供的 REST API，以及 Web UI 的三类核心视图。API 基址为 `localhost:9411/api/v2`，其主要消费者是 Web UI，也可被外部工具直接调用。

## Query Service API

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `POST` | `/api/v2/spans` | 接收一批 span（JSON / protobuf），`202 Accepted` |
| `GET` | `/api/v2/services` | 列出所有被追踪服务名 |
| `GET` | `/api/v2/spans?serviceName=` | 列出某服务的 span 名 |
| `GET` | `/api/v2/traces` | 按 service / operation / tag / annotation / 时间范围 / duration 检索 trace |
| `GET` | `/api/v2/trace/{traceId}` | 按 traceId 点查一条 trace |
| `GET` | `/api/v2/traceMany` | 批量点查多条 traceId |
| `GET` | `/api/v2/dependencies?endTs=&lookback=` | 服务间依赖链接（需依赖聚合，见 [Collector and Storage](/docs/CS/Distributed/Tracing/Zipkin/Collector_and_Storage.md)） |
| `GET` | `/api/v2/autocompleteKeys` / `/autocompleteValues` | 自动补全的 tag key / value，加速检索框输入 |

检索接口支持的过滤维度包括：服务名、span 名（operation）、标签（`tagKey=tagValue`）、注解（`annotationQuery`）、时间起止（`endTs` / `lookback`）、最小耗时（`minDuration`）等。当 `SEARCH_ENABLED=false` 时，检索接口仅能按 traceId 点查，其余过滤不可用。

## Web UI

Web UI 是一个轻量单页应用，三大核心视图：

1. **Trace 列表检索**：按服务、操作名、tag、耗时区间、时间范围查询，列出命中的 trace 及其关键摘要（总耗时、span 数、是否有错误）。
2. **Trace 详情时间轴（瀑布图）**：把一条 trace 的所有 span 按服务分组、沿时间轴铺开，清晰暴露「哪个 span 最慢、哪个报错、调用嵌套关系」——这是定位延迟瓶颈的主界面。
3. **依赖图（Dependency diagram）**：汇总「各应用间有多少被追踪的请求流经」，可识别聚合行为，包括错误路径与对**过时服务**的调用。

UI 还会对检索结果做简单聚合，例如「某服务占用的时间占比」「操作是否失败」，对应其首页说明的定位能力。

## Example: Query a Trace by ID

```bash
# 按 traceId 点查一条 trace（返回 span 数组的 JSON）
curl 'http://localhost:9411/api/v2/trace/5af7183fb1d4cf5f'

# 按服务 + 最小耗时检索最近一小时的 trace
curl 'http://localhost:9411/api/v2/traces?serviceName=backend&minDuration=100000&lookback=3600000'
```

## Links

- [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md) — 枢纽页
- [Zipkin Collector and Storage](/docs/CS/Distributed/Tracing/Zipkin/Collector_and_Storage.md) — 检索开关与依赖聚合
- [Zipkin Data Model](/docs/CS/Distributed/Tracing/Zipkin/Data_Model.md) — 返回的 span 字段
- [Jaeger](/docs/CS/Distributed/Tracing/Jaeger.md) — Jaeger query + UI 对照

## References

1. [Zipkin API v2](https://zipkin.io/zipkin-api/#/default/post_spans) — 完整端点与请求/响应模型
2. [Zipkin](https://zipkin.io/) — 官方站点与 UI 说明
