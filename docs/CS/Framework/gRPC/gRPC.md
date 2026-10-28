## Introduction

[gRPC](https://grpc.io/) 是 CNCF 孵化项目，一套跨语言的高性能 RPC 框架。它的主张很直接：服务方用 Protocol Buffers 定义一份接口契约，工具链为各语言生成客户端 stub 与服务端骨架，调用方写出来的代码看起来就是一次普通的方法调用，底下由框架负责连接管理、编码、流控、超时传播与状态映射。

这套思路并非新发明——它正是 [RPC](/docs/CS/Distributed/RPC/RPC.md) 概念模型里 **client stub / server stub + marshalling** 那一套的工业化实现。区别在于 gRPC 把当年只能靠论文描述的部分做成了可插拔的运行时组件：传输层绑定 HTTP/2，编码层绑定 Protobuf，负载均衡与命名解析可替换，认证、健康检查、追踪都有标准接口。

## Why HTTP/2

选择 HTTP/2 而不是自定义 TCP 协议，是 gRPC 最关键的取舍。它换来了三样东西：

- **多路复用**：一条 TCP 连接上并发跑多个流（stream），彻底摆脱 HTTP/1.1 的队头阻塞与连接池爆炸问题。一次 RPC 对应一个 stream，请求头、消息体、状态分别落在 HEADERS 帧、DATA 帧与 trailer 上。
- **头部压缩**：HPACK 压缩元数据，短请求场景下元数据开销显著下降。
- **标准化的流控与优先级**：把背压交给传输层，而不是每个 RPC 框架各造一套。

代价是调试门槛变高——线上抓包看到的是二进制帧，必须靠 `grpcurl` 之类工具或服务端日志才能还原语义。取舍的边界很清楚：跨组织、跨语言的内部服务通信里，互通性远比"协议够不够简单"重要。

与之相对，[Thrift](/docs/CS/Distributed/RPC/Thrift.md) 走的是自带完整软件栈的路线（Transport / Protocol / Processor / Server 四层均可替换），[Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md) 则把重心放在 Java 生态的服务治理上。

## Architecture

gRPC 的分层可以粗分为三段，各语言实现在命名上略有出入，但职责一致：

- **Stub 层**：由 `.proto` 生成。客户端 stub 把方法调用转成「方法名 + 请求消息」，服务端 stub（骨架）负责反向还原并派发到业务实现。
- **Channel 层**：客户端的核心抽象，代表到某个目标的虚拟连接。它持有命名解析器（name resolver）、负载均衡策略（LB policy）与一组 subchannel，连接建立、重连、健康检查都收在这一层。
- **Transport 层**：HTTP/2 帧的读写、流控窗口、keepalive。Go 实现走 `net/http2`，Java 实现有 Netty / OkHttp / Binder 等多种 transport。

三层的具体帧格式、状态码语义与编解码细节见 [Architecture](/docs/CS/Framework/gRPC/Architecture.md)。

## Communication Patterns

gRPC 定义了四种通信模式，区别只在「请求是不是流」「响应是不是流」：

| 模式 | 请求 | 响应 | 典型场景 |
| :--- | :--- | :--- | :--- |
| Unary | 单条 | 单条 | 普通的请求-响应 |
| Server streaming | 单条 | 流 | 订阅推送、大结果集分批下发 |
| Client streaming | 流 | 单条 | 大文件上传、批量写入 |
| Bidirectional streaming | 流 | 流 | 实时双向通信、代理隧道 |

流式是 gRPC 相对传统 RPC 最有价值的扩展，也正好补上了 [RPC.md](/docs/CS/Distributed/RPC/RPC.md) 里提到的一个老问题：一次性返回全部结果会让客户端长时间空等。流控窗口、取消传播与 deadline 语义见 [Streaming](/docs/CS/Framework/gRPC/Streaming.md)。

## Ecosystem

框架本身只解决"怎么调用"，生产环境还需要周边能力：

- **拦截器**（interceptor / middleware）：认证、日志、限流、链路追踪的注入点，等价于服务端框架的 Filter。
- **命名与负载均衡**：DNS、xDS（Envoy 的控制面协议）、grpclb。xDS 是 gRPC 接入服务网格的关键。
- **可观测性**：内建的 channelz、与 OpenTelemetry 的集成，配合 [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md) 等后端。
- **网关转译**：`grpc-gateway` 依据 `google.api.http` 注解生成反向代理，让同一份实现同时暴露 gRPC 与 HTTP/JSON。

详见 [Ecosystem](/docs/CS/Framework/gRPC/Ecosystem.md)。

## Version Baseline

gRPC 各语言实现共享同一套 minor.point 版本号，便于对照：

| 组件 | 版本 | 日期 |
| :--- | :--- | :--- |
| gRPC C core | 1.84.0 | 2026-09-10 |
| grpc-java | 1.84.0 | 2026-09-01 |
| grpc-go | 1.84.0 | 2026-09-17 |
| protoc-gen-go-grpc | 1.6.2 | 2026-05-07 |
| Protocol Buffers (protoc) | 36.2 | 2026-09-17 |

grpc-go v1.84.0 的 `go.mod` 声明 **`go 1.25.0`**。Protobuf 侧当前活跃支持 36.x，其中 Edition 2026 需要 protoc 36.0 及以上（2026-08-20 发布），此前 Edition 2024 需 32.0、Edition 2023 需 27.0。

官方支持的语言共 13 个：C#/.NET、C++、Dart、Go、Java、Kotlin、Node、Objective-C、PHP、Python、Ruby、Rust、Swift。

## Links

- [RPC](/docs/CS/Distributed/RPC/RPC.md) — 概念模型的源头：stub、编组、绑定与异常语义
- [gRPC Architecture](/docs/CS/Framework/gRPC/Architecture.md) — HTTP/2 帧映射、Channel 与编解码
- [gRPC Streaming](/docs/CS/Framework/gRPC/Streaming.md) — 四种流模式、流控与超时传播
- [gRPC Ecosystem](/docs/CS/Framework/gRPC/Ecosystem.md) — 拦截器、服务发现与负载均衡、可观测性
- [Protocol Buffers](/docs/CS/Distributed/RPC/ProtoBuf.md) — gRPC 默认的 IDL 与编码格式
- [Marshalling](/docs/CS/Distributed/RPC/Marshalling.md) — 序列化兼容性问题的一般讨论

## References

1. [gRPC](https://grpc.io/)
2. [Supported languages | gRPC](https://grpc.io/docs/languages/)
3. [gRPC Core: Remote Procedure Calls on the Web](https://www.youtube.com/watch?v=yG5Ur2RqPCw)
4. [grpc/grpc-go](https://github.com/grpc/grpc-go)
5. [gRPC-Java v1.84.0 Released](https://groups.google.com/g/grpc-io/c/tndfJa2o8xs)
6. [Protocol Buffers Version Support](https://protobuf.dev/support/version-support/)
7. [gRFC: gRPC over HTTP/2](https://github.com/grpc/grpc/blob/master/doc/PROTOCOL-HTTP2.md)
