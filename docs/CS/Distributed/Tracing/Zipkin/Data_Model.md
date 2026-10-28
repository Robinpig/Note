## Introduction

本篇描述 [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md) 的 **v2 数据模型**：一条 Trace 由共享同一 `traceId` 的若干 Span 构成树状结构，Span 间靠 `parentId` 串联。理解字段语义是正确埋点与解读 UI 时间轴的前提。

## Trace and Span Tree

- **Trace**：一次完整请求的 span 集合，由 `traceId` 唯一标识。推荐 128-bit（32 位十六进制），兼容 64-bit（16 位十六进制）。
- **Span**：一个工作单元（一次 RPC、一次 DB 调用、一段本地处理）。除 `id`、`traceId` 外，`parentId` 为空表示它是 **root span**，非空表示它是父 span 的子节点。由此 span 自然组成一棵**因果树**。

```
        [Span A]  root (traceId=T, parentId=null)
            │
     ┌──────┴──────┐
  [Span B]      [Span C]   (parentId = A.id)
     │
  [Span D]                  (parentId = B.id)
```

Zipkin 通过 `traceId` + `spanId` **合并**来自不同进程、共享同一 ID 的 span 片段（见下方 Merge 章节），因此对同一 RPC，客户端与服务端各报一段、最终拼成一条完整 span。

## Span JSON Model

v2 中一个 span 的 JSON 形态（摘自给 Zipkin API 的示例）：

```json
[
  {
    "id": "352bff9a74ca9ad2",
    "traceId": "5af7183fb1d4cf5f",
    "parentId": "6b221d5bc9e6496c",
    "name": "get /api",
    "timestamp": 1556604172355737,
    "duration": 1431,
    "kind": "SERVER",
    "localEndpoint": { "serviceName": "backend", "ipv4": "192.168.99.1", "port": 3306 },
    "remoteEndpoint": { "ipv4": "172.19.0.2", "port": 58648 },
    "tags": { "http.method": "GET", "http.path": "/api" }
  }
]
```

字段语义：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string(hex) | Span ID（必填），64-bit 十六进制 |
| `traceId` | string(hex) | Trace ID（必填），64 或 128-bit 十六进制 |
| `parentId` | string(hex) | 父 span ID，root span 缺省 |
| `name` | string | 操作名，如 `get /api`、SQL 语句摘要 |
| `timestamp` | int(μs) | span 起始时间，**epoch 微秒**（不是毫秒） |
| `duration` | int(μs) | span 持续时间，微秒 |
| `kind` | enum | `CLIENT` / `SERVER` / `PRODUCER` / `CONSUMER` |
| `localEndpoint` | object | 本端服务：`serviceName` / `ipv4` / `ipv6` / `port` |
| `remoteEndpoint` | object | 对端服务，结构同 `localEndpoint` |
| `tags` | map<string,string> | 键值标签，如 `http.method`、`error` |
| `annotations` | list | 带时间戳的事件，见下 |
| `debug` / `shared` | bool | 调试标记 / 服务端共享标记（见下） |

序列化的权威字段清单见 `zipkin2.Span` 的 `serialized-form`（字段：`traceId, id, parentId, name, timestamp, duration, kind, localEndpoint, remoteEndpoint, tags, annotations, flags`）。

## Timestamps and Duration

Zipkin 中所有时间戳都是 **epoch 微秒**（而非毫秒），且存为 64-bit 有符号整数（负值非法）。`timestamp` 与 `duration` **只应由启动该 span 的主机设置**——最常见的合并场景就是客户端（`cs`/`cr`）与服务端（`sr`/`ss`）各报一段、共享同一 spanId。

微秒粒度并非为了追求纳秒精度，而是为了：与 duration 同单位、计算更简单；span 自身的记录开销往往就有微秒量级，更高分辨率反而有误导性。

## Annotations

`annotations` 是一组 `{timestamp, value}` 事件，用于标记 span 生命周期中的关键时刻。RPC 场景的标准注解：

| 注解 | 含义 | 方向 |
| --- | --- | --- |
| `cs` | Client Send | 客户端发起请求 |
| `sr` | Server Receive | 服务端收到请求 |
| `ss` | Server Send | 服务端返回响应 |
| `cr` | Client Receive | 客户端收到响应 |

由此可算出：`sr - cs` = 网络延迟，`ss - sr` = 服务端处理耗时，`cr - cs` = 总耗时。消息队列场景另用 `ws`（Wire Send，生产者发往 broker）与 `wr`（Wire Receive，消费者从 broker 取出）。

## Kind

`kind` 是 v2 对「cs/sr」模型的精练：用单个 span 的 `kind` 表达它在一次交互中的角色，配合 `timestamp` + `duration` 表达起止，而不必再显式写 `cs`/`sr` 注解。

- **CLIENT**：发起了一次出站请求（如 HTTP 客户端、RPC stub）。
- **SERVER**：处理了一次入站请求（如 HTTP handler、RPC 实现）。
- **PRODUCER**：把消息发往消息队列（与 `remoteEndpoint` 指向 broker）。
- **CONSUMER**：从消息队列消费消息。

## Shared and Debug

- **shared**：当同一 `spanId` 同时出现在客户端与服务端时，服务端那条记录置 `shared=true`，表明它与客户端的 span 是「同一段」的共享视图，UI 据此只渲染一次。
- **debug**：由 B3 的 `X-B3-Flags: 1` 触发，强制该 trace 被采样并尽量保证送达 collector 层，用于临时排查问题。

## Links

- [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md) — 枢纽页
- [Zipkin Architecture](/docs/CS/Distributed/Tracing/Zipkin/Architecture.md) — span 生命周期与合并流程
- [Zipkin Transport](/docs/CS/Distributed/Tracing/Zipkin/Transport.md) — B3 传播如何携带这些 ID
- [Tracing](/docs/CS/Distributed/Tracing/Tracing.md) — OpenTracing 数据模型对照
- [Jaeger](/docs/CS/Distributed/Tracing/Jaeger.md) — Jaeger 的 span 模型

## References

1. [Zipkin API v2](https://zipkin.io/zipkin-api/#/default/post_spans) — span 模型与示例
2. [zipkin2.Span serialized form](https://zipkin.io/zipkin/3.0.0/zipkin/serialized-form.html) — 序列化字段清单
3. [Instrumenting a library](https://zipkin.io/pages/instrumenting) — 时间戳、注解与 span 合并规则
