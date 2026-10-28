## Introduction

流式是 gRPC 相对传统 RPC 最有价值的扩展。传统 RPC 里，客户端发起调用后必须等到服务端把结果集全部算完才能收到第一条数据——对大结果集或长时间任务，客户端在这段时间里完全空等。gRPC 借 HTTP/2 的流（stream）把这个约束拆掉了：请求和响应各自可以是单条消息，也可以是一条消息序列。

## Four Communication Patterns

四种模式只是「请求是否成流」×「响应是否成流」的笛卡尔积，IDL 里的差别仅在于是否加 `stream` 关键字：

```protobuf
service RouteGuide {
  rpc GetFeature(Point) returns (Feature) {}                          // Unary
  rpc ListFeatures(Rectangle) returns (stream Feature) {}             // Server streaming
  rpc RecordRoute(stream Point) returns (RouteSummary) {}             // Client streaming
  rpc RouteChat(stream RouteNote) returns (stream RouteNote) {}       // Bidirectional
}
```

| 模式 | 请求 | 响应 | 典型场景 |
| :--- | :--- | :--- | :--- |
| Unary | 单条 | 单条 | 普通请求-响应，绝大多数调用 |
| Server streaming | 单条 | 流 | 订阅推送、大结果集分批下发、进度回报 |
| Client streaming | 流 | 单条 | 大文件分块上传、批量写入、流式聚合 |
| Bidirectional | 流 | 流 | 实时双向通信、代理隧道、语音流 |

双向流里，请求流与响应流**相互独立**：客户端可以在还没发完请求时就收到响应，两边各自的结束由各自的 END_STREAM 决定。这跟 HTTP/1.1 的请求-响应严格交替完全不同。

## Flow Control

背压由 HTTP/2 的流控承担，gRPC 不另造一套。核心是两级窗口：

- **Stream 级**：单个 RPC 的窗口，防止一条流吃满缓冲区。
- **Connection 级**：整条 TCP 连接的窗口，防止一条连接拖垮对端。

发送方每发出一字节就扣减窗口，接收方消费后发 `WINDOW_UPDATE` 归还额度；窗口耗尽时发送方必须停等。初始窗口取 HTTP/2 规范默认值 **65535 字节**。

在这个基础上，gRPC 实现（Go / C++）还做了 **BDP 动态窗口**：周期性发送 BDP ping 测量带宽延迟积（Bandwidth-Delay Product），据此上调流控窗口。这一层不是 HTTP/2 规范内容，而是 gRPC 的性能优化——长肥管道（高带宽 × 高延迟）场景下，固定 64 KiB 窗口会成为吞吐瓶颈，动态窗口能让窗口跟链路容量匹配。

> [!WARNING]
>
> 规范里"建议 8 KiB"与实际默认值并不一致，别照抄规范数值去判断线上行为。以 grpc-go v1.84.0 `internal/transport/defaults.go` 实测，头部列表大小默认是 **16 MiB**（`defaultClientMaxHeaderListSize` / `defaultServerMaxHeaderListSize`），而 `upcomingDefaultHeaderListSize = 8 << 10`（8 KiB）只是"计划中的默认值"——说明官方准备收紧，但当前版本尚未生效。

## Timeout and Cancellation

超时通过请求头的 `grpc-timeout` 传递，格式是最多 8 位的十进制正整数加单位：

| 单位 | 字符 | 单位 | 字符 |
| :--- | :--- | :--- | :--- |
| Hour | `H` | Millisecond | `m` |
| Minute | `M` | Microsecond | `u` |
| Second | `S` | Nanosecond | `n` |

注意大小写敏感：`M` 是分钟、`m` 是毫秒，写错会让超时差六个数量级。

几个语义要点：

- deadline 是**绝对值**，`grpc-timeout` 只是把它编码成相对值在线上传输；跨多跳调用时由每一跳重新计算，不是简单透传。
- 省略 `grpc-timeout` 时，服务端应假定无限超时。客户端可以按部署要求自行下发默认最小超时。
- 客户端取消会沿 HTTP/2 的 RST_STREAM 传播到服务端，服务端 handler 能从 context 观察到取消——这正是 [RPC](/docs/CS/Distributed/RPC/RPC.md) 里"孤儿（orphan）"问题的现代解答：框架提供了取消通道，但业务代码仍要主动检查。

## Keepalive

keepalive 的默认配置常被误解。以 grpc-go v1.84.0 `internal/transport/defaults.go` 实测：

| 参数 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `defaultClientKeepaliveTime` | `infinity` | **客户端 keepalive 默认关闭** |
| `defaultClientKeepaliveTimeout` | 20s | ping 超时 |
| `defaultServerKeepaliveTime` | 2h | 服务端 ping 间隔 |
| `defaultServerKeepaliveTimeout` | 20s | ping 超时 |
| `defaultKeepalivePolicyMinTime` | 5min | 服务端强制的最小 ping 间隔 |
| `defaultMaxStreamsClient` | 100 | 客户端最大并发流 |
| `defaultWriteQuota` | 64 KiB | 单流可调度的数据量 |
| `maxWindowSize` | `math.MaxInt32` | 流控窗口上限 |

两点值得留意：一是客户端 keepalive **默认不开启**（`Time` 为 infinity），需要保持长连接活性时必须显式配置；二是服务端有 `defaultKeepalivePolicyMinTime` 兜底，ping 过于频繁的对端会被判违规并断开——`MaxConnectionIdle` / `MaxConnectionAge` / `MaxConnectionAgeGrace` 三者默认也都是 infinity，即默认不主动回收连接。

## Error Handling

流上的错误一律走 trailer，不占用 HTTP 状态码：

- `grpc-status`：状态码，十进制 ASCII 字符串、无前导零。
- `grpc-message`：Unicode 错误描述，UTF-8 后再百分号编码。解码遇到非法序列时不得报错或丢弃，最坏情况保留原始百分号形式。
- `grpc-status-details-bin`：仅当状态非 OK 时允许出现，携带 Base64 编码的 `google.rpc.Status`；其中的状态码不得与 `grpc-status` 冲突，消费方必须校验。

响应端有两种形态：正常路径是 Response-Headers + 消息 + Trailers；**Trailers-Only** 用于立即失败，把状态直接放进唯一的 HEADERS 帧，少一次往返。无论哪种，**状态必须出现在 Trailers 中**，即使状态码是 OK。

规范还要求实现容忍坏部署：响应里出现非 200 的 HTTP 状态、非 gRPC content-type、或缺失 `grpc-status` 时，都必须合成一个状态上抛给应用层，而不是让调用挂死。

## Links

- [gRPC](/docs/CS/Framework/gRPC/gRPC.md) — 框架总览与版本基线
- [gRPC Architecture](/docs/CS/Framework/gRPC/Architecture.md) — 帧映射、状态码与 codec
- [gRPC Ecosystem](/docs/CS/Framework/gRPC/Ecosystem.md) — 拦截器与服务发现
- [RPC](/docs/CS/Distributed/RPC/RPC.md) — 超时、孤儿与重复执行语义的概念源头
- [Nginx gRPC](/docs/CS/CN/nginx/grpc.md) — 反向代理侧的 gRPC 配置与限制
- [HTTP](/docs/CS/CN/HTTP/HTTP.md) — HTTP/2 流与流控基础

## References

1. [gRFC: gRPC over HTTP/2](https://github.com/grpc/grpc/blob/master/doc/PROTOCOL-HTTP2.md)
2. [gRPC Core Concepts - RPC life cycle](https://grpc.io/docs/what-is-grpc/core-concepts/)
3. [grpc-go internal/transport/defaults.go](https://github.com/grpc/grpc-go/blob/master/internal/transport/defaults.go)
4. [grpc-go internal/transport/bdp_estimator.go](https://github.com/grpc/grpc-go/blob/master/internal/transport/bdp_estimator.go)
5. [RFC 7540 §6.9 - WINDOW_UPDATE](https://datatracker.ietf.org/doc/rfc7540/)
6. [gRFC A6: Client Retries](https://github.com/grpc/grpc/blob/master/doc/connection-backoff.md)
