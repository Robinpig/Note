# gRPC Streaming: Patterns, Flow Control and Cancellation

## Introduction

流式是 gRPC 相对传统 RPC 最有价值的扩展：传统 RPC 必须等服务方把结果集全部算完才能收到第一条数据，而 gRPC 借 HTTP/2 的 stream 把请求和响应各自拆成"单条消息"或"消息序列"。一次 RPC 的完整帧序列见 [Architecture](/docs/CS/Framework/gRPC/Architecture.md)；本文以 grpc-java 1.75.0 为准，讲清四种模式的帧序列、背压与取消语义。

> 版本基线：grpc-java 1.75.0（commit 3abc0e6）。默认值均取自该 tag 源码；不是 grpc-go 的数字。

三个反直觉点：

- **双向流两个方向独立**：请求流与响应流各自用自己的 END_STREAM 结束，客户端可以没发完请求就收到响应。
- **初始窗口 1 MiB（Java）**：不是 HTTP/2 规范默认 65535 字节，也不是 grpc-go 的数字；且默认开 BDP 自动调优。
- **客户端 keepalive 默认关闭**：长连接场景必须显式开启，否则空闲连接会被中间设备回收。

## Four Communication Patterns

四种模式是「请求是否成流」×「响应是否成流」的笛卡尔积，IDL 差别仅在 `stream` 关键字：

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
| Unary | 单条 | 单条 | 普通请求-响应 |
| Server streaming | 单条 | 流 | 订阅推送、大结果集分批下发 |
| Client streaming | 流 | 单条 | 大文件上传、批量写入、流式聚合 |
| Bidirectional | 流 | 流 | 实时双向通信、代理隧道、语音流 |

`MethodDescriptor.MethodType` 在 stub 生成代码里确定类型（UNARY / SERVER_STREAMING / CLIENT_STREAMING / BIDI_STREAMING），它驱动 `ClientCallImpl.sendMessage` 的 flush 策略和 `ServerCallImpl.closeInternal` 的"OK 但无消息"校验。

## Flow Control: Two Levels Plus request(n)

背压由三层叠加，gRPC 不另造传输层流控：

1. **HTTP/2 stream 级窗口**：单 RPC，防止一条流吃满缓冲。
2. **HTTP/2 connection 级窗口**：整条 TCP 连接，防止一条连接拖垮对端。
3. **应用层消息计数**：`request(n)` 控制投递多少条消息给应用。

Java Netty 的初始窗口是 1 MiB（`NettyChannelBuilder.DEFAULT_FLOW_CONTROL_WINDOW = 1024*1024`），并默认开启 BDP（带宽延迟积）自动调优——窗口随链路容量动态上调，上限 8 MiB。注意两个设置入口语义相反：`initialFlowControlWindow()` 开启调优、`flowControlWindow()` 关闭调优（详见 [FlowControl](/docs/CS/Framework/gRPC/FlowControl.md)）。

> [!WARNING]
> 早期笔记写"初始窗口 65535 字节（HTTP/2 默认）"是照抄规范的错误。实测 grpc-java 1.75.0 是 **1 MiB + BDP 调优**；grpc-go 的 header 上限是 16 MiB 而 Java 是 8 KiB——跨语言对照务必看实现源码，别抄规范数值。

## Timeout and Cancellation

超时通过 `grpc-timeout` 传递，编码规则是"贪心精度"（`2s → 2000000u`），见 [ContextDeadline](/docs/CS/Framework/gRPC/ContextDeadline.md)。单位大小写敏感：`M` 分钟、`m` 毫秒、`S` 秒、`n` 纳秒、`u` 微秒、`H` 小时。

几个语义要点：

- deadline 是**绝对值**，`grpc-timeout` 只是相对编码；每跳重新计算，不是透传。
- 客户端取消沿 RST_STREAM 传播到服务端；服务端 handler 从 Context 观察取消——但**业务代码要主动检查**，框架只提供通道。
- 服务端 `ServerStreamCancellationListener` 只在 DEADLINE_EXCEEDED 时主动 `stream.cancel`，客户端取消已由 RST_STREAM 完成（见 [ServerCallChain](/docs/CS/Framework/gRPC/ServerCallChain.md)）。

## Keepalive Defaults (grpc-java)

| 参数 | 默认值 | 源码常量 |
| :--- | :--- | :--- |
| 客户端 keepalive 间隔 | 关闭（`Long.MAX_VALUE`） | `KEEPALIVE_TIME_NANOS_DISABLED` |
| 客户端 ping 超时 | 20s | `DEFAULT_KEEPALIVE_TIMEOUT_NANOS` |
| 服务端 keepalive 间隔 | 2h | `DEFAULT_SERVER_KEEPALIVE_TIME_NANOS` |
| 服务端 ping 超时 | 20s | `DEFAULT_SERVER_KEEPALIVE_TIMEOUT_NANOS` |

客户端 keepalive 默认不开启；服务端有强制最小 ping 间隔策略，过于频繁的对端会被 GOAWAY。`MaxConnectionIdle` / `MaxConnectionAge` / `MaxConnectionAgeGrace` 默认也都是 infinity（不主动回收）。

## Error Handling in Streams

流上错误一律走 trailer，不占 HTTP 状态码：

- `grpc-status`：十进制 ASCII 状态码，无前导零。
- `grpc-message`：UTF-8 后再百分号编码；解码遇非法序列不得报错，最坏保留原百分号形式。
- `grpc-status-details-bin`：仅非 OK 允许，Base64 编码的 `google.rpc.Status`，内部码不得与 `grpc-status` 冲突。

响应两形态：正常路径 Response-Headers + 消息 + Trailers；Trailers-Only 用于立即失败。**状态必须出现在 Trailers 中，即使 OK。** 完整码表见 [Status](/docs/CS/Framework/gRPC/Status.md)。

## Links

- [gRPC](/docs/CS/Framework/gRPC/gRPC.md) — 枢纽：架构与纠偏
- [Framing](/docs/CS/Framework/gRPC/Framing.md) — 流消息如何定界
- [ClientCallChain](/docs/CS/Framework/gRPC/ClientCallChain.md) — sendMessage 的 flush 差异
- [FlowControl](/docs/CS/Framework/gRPC/FlowControl.md) — 窗口、BDP 与 request(n) 详解
- [ContextDeadline](/docs/CS/Framework/gRPC/ContextDeadline.md) — 超时编码与取消传播
- [HTTP](/docs/CS/CN/HTTP/HTTP.md) — HTTP/2 流与流控基础

## References

- [grpc-java v1.75.0 NettyChannelBuilder.java](https://github.com/grpc/grpc-java/blob/v1.75.0/netty/src/main/java/io/grpc/netty/NettyChannelBuilder.java)
- [grpc-java v1.75.0 GrpcUtil.java](https://github.com/grpc/grpc-java/blob/v1.75.0/core/src/main/java/io/grpc/internal/GrpcUtil.java)
- [gRFC: gRPC over HTTP/2](https://github.com/grpc/grpc/blob/master/doc/PROTOCOL-HTTP2.md)
- [gRPC Core Concepts - RPC life cycle](https://grpc.io/docs/what-is-grpc/core-concepts/)
- [RFC 7540 §6.9 - WINDOW_UPDATE](https://datatracker.ietf.org/doc/rfc7540/)
