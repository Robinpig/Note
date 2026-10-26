## Introduction

本篇展开 [SkyWalking](/docs/CS/Distributed/Tracing/SkyWalking.md) 的**读取侧**：OAP 通过 **GraphQL** 暴露查询能力（基址 `:12800`），以及 Web UI 的几类核心视图——拓扑图、追踪详情、指标仪表盘与告警。UI 端口 8080，向后端的 12800 发起 GraphQL 查询。

## GraphQL Query

SkyWalking 没有像 Zipkin 那样的 REST 检索端点，而是通过 **GraphQL** 提供查询（`query` provider，基址 `http://oap:12800/graphql`）。典型查询包括：

- **拓扑**：获取服务 / 实例 / 端点之间的依赖节点与边。
- **追踪**：按 `traceId` 点查，或按服务 / 端点 / 时间范围 / 耗时检索 trace 列表（分页、条件过滤）。
- **指标**：读取 OAL 产出的指标时间序列，支持 `duration`、标签过滤与 `percentile2` 的多标签取值。
- **日志 / 事件 / profiling**：各自的 GraphQL query 类型。

除 GraphQL，12800 上还提供 **PromQL** 与 **LogQL** 兼容查询（由 `promql` / `logql` provider 提供），便于与 Prometheus / Loki 生态互操作。

## UI Views

Web UI 围绕「对象层级」组织视图，核心有四类：

1. **拓扑图（Topology）**：把 Service / Instance / Endpoint 的依赖以图呈现，节点可下钻到指标；这是 SkyWalking 相比纯追踪系统最突出的视图。配合 **Service Hierarchy**，可同时看业务层与基础设施层拓扑。
2. **追踪详情（Trace / Segment）**：一条 trace 的所有 Segment 沿时间轴铺开，暴露「哪个 Span 最慢、哪个报错、调用嵌套关系」——定位延迟瓶颈的主界面。
3. **指标仪表盘（Metrics）**：按 Service / Instance / Endpoint 展示 OAL 指标（响应时间、CPM、成功率、百分位延迟、Apdex、热力图等）。
4. **日志 / 告警**：日志与 trace 上下文绑定后可联动查看；告警列表与钩子推送对应。

UI 历史上是 **booster-ui**（React）；**v11 起引入下一代 Horizon UI**，原生支持 SkyWalking 的层级与拓扑模型（v10 部分支持）。

## Example: Query a Trace via GraphQL

```graphql
query {
  trace(traceId: "1-xxxxx") {
    spans {
      traceId segmentId spanId parentSpanId
      serviceCode endpointName startTime duration
      type peer
    }
  }
}
```

实际请求发往 `POST http://oap:12800/graphql`，body 为上面的 GraphQL 查询。

## Links

- [SkyWalking](/docs/CS/Distributed/Tracing/SkyWalking.md) — 枢纽页
- [SkyWalking OAP Backend and Storage](/docs/CS/Distributed/Tracing/SkyWalking/Collector_and_Storage.md) — 指标来源与告警
- [SkyWalking Data Model](/docs/CS/Distributed/Tracing/SkyWalking/Data_Model.md) — 返回的 Span / Segment 字段
- [SkyWalking Internals](/docs/CS/Distributed/Tracing/SkyWalking/Internals.md) — 拓扑边的推导与聚合来源
- [Zipkin Query and UI](/docs/CS/Distributed/Tracing/Zipkin/Query_and_UI.md) — REST API 对照
- [Grafana](/docs/CS/Distributed/Tracing/Grafana.md) — 也可通过 SkyWalking Grafana 插件在 Grafana 看拓扑

## References

1. [SkyWalking UI](https://skywalking.apache.org/docs/main/next/en/ui/README/) — UI 视图说明
2. [Backend setup](https://skywalking.apache.org/docs/main/next/en/setup/backend/backend-setup/) — GraphQL 端口与 UI
3. [GraphQL query protocol](https://skywalking.apache.org/docs/main/next/en/api/query-protocol/) — 查询协议
