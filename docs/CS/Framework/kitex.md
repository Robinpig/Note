## Introduction

[Kitex](https://www.cloudwego.io/zh/docs/kitex/) 是字节跳动开源的 **Go 微服务 RPC 框架**（CloudWeGo 生态），2021 年开源，
在字节内部承载了大规模的微服务调用。它默认使用 [Thrift](/docs/CS/Distributed/RPC/Thrift.md) 作为 IDL 与编解码（也支持 [Protobuf](/docs/CS/Distributed/RPC/ProtoBuf.md)），
网络层默认基于同属 CloudWeGo 的 [Netpoll](/docs/CS/Framework/Netpoll.md)（epoll/kqueue 的 NIO 库），以高吞吐、低延迟、可扩展为设计目标。

在 [RPC 框架谱系](/docs/CS/Distributed/RPC/RPC.md)里，它与 [gRPC](/docs/CS/Framework/gRPC/gRPC.md)（多语言、HTTP/2 + Protobuf）、
[Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)（Java 生态）定位相近，区别是 Kitex 专注 Go、默认 Thrift、网络层自研，并深度贴合字节的服务治理体系。

## Architecture

一次调用的分层：

```
业务代码（client / server handler）
   │  生成的 kitex_gen 代码（编解码、client/service 桩）
IDL Layer（Thrift / Protobuf，thriftgo / protoc 插件生成代码）
   │
Kitex Core：endpoint middleware 链（追踪/熔断/限流/重试/埋点）
   │
Transport：Netpoll（默认，NIO） / 标准库 net（BIO，可切换）
   │
注册中心 / 配置中心 / 监控（可插拔）
```

- **IDL 优先**：写 `.thrift`/`.proto`，用 kitex 工具生成 client、server、序列化代码（`kitex_gen`），调用像本地方法。
- **Endpoint Middleware 链**：框架与业务治理逻辑以中间件形式串成责任链，类似 [Netty](/docs/CS/Framework/Netty/Netty.md) 的 ChannelPipeline，
  内置或通过插件接入服务发现、负载均衡、熔断、限流、重试、[分布式追踪](/docs/CS/Distributed/Tracing/Tracing.md)、监控埋点。
- **自研网络层 Netpoll**：RPC 处理逻辑较重、不能串行处理 I/O，而 Go 标准库 `net` 是 BIO，每连接一个 goroutine 在海量连接下调度成本高；
  Netpoll 用事件驱动 + 连接管理替代之，Kitex 与 HTTP 框架 Hertz 都构建其上。

## Features

- **多协议与传输**：Thrift（默认，含 Kitex 自研的带元信息传输协议 TTHeader）、gRPC/Protobuf，可在同端口做多协议探测；支持连接多路复用（mux）、长连接池。
- **服务治理**：客户端侧服务发现与负载均衡、超时控制、重试、备份请求、熔断、限流、会话/粒度级治理，均设计为可插拔扩展。
- **泛化调用（Generic Call）**：无需生成的 stub、不依赖具体 IDL 类型即可发起调用，适合网关、测试平台等不能依赖每个服务 SDK 的场景，动机见 [RPC 泛化调用](/docs/CS/Distributed/RPC/RPC.md?id=泛化调用)。
- **可扩展性**：几乎所有横切能力（registry、loadbalance、circuit breaker、tracer、transporter、codec）都以接口暴露，方便对接自研基础设施。

## Compare

| 维度 | Kitex | gRPC | Dubbo |
| --- | --- | --- | --- |
| 语言 | 以 Go 为核心 | 多语言（最广） | Java 为主（Go 等有移植） |
| IDL/编码 | Thrift 默认，也支持 Protobuf | Protobuf | 接口/多协议（Triple、Dubbo 协议） |
| 传输 | Netpoll（NIO）/net，自研传输 | HTTP/2 | HTTP/2、TCP 长连接 |
| 流式 | 支持 gRPC streaming（proto 下） | 原生强项 | Triple 支持 |
| 生态 | CloudWeGo（Netpoll/Hertz） | CNCF、跨语言生态 | 阿里 Spring 生态 |
| 典型场景 | Go 微服务、超大规模 RPC | 跨语言、云原生、开放 | Java 微服务 |

选型上：纯 Go、追求极致性能且接受 Thrift/CloudWeGo 生态时 Kitex 合适；需要多语言互通与标准化流式调用优先 gRPC；
Java/Spring 体系内 Dubbo 更顺。

## Links

- [RPC](/docs/CS/Distributed/RPC/RPC.md)
- [Netpoll](/docs/CS/Framework/Netpoll.md) — Kitex 默认网络层
- [Thrift](/docs/CS/Distributed/RPC/Thrift.md)
- [Protocol Buffers](/docs/CS/Distributed/RPC/ProtoBuf.md)
- [gRPC](/docs/CS/Framework/gRPC/gRPC.md)
- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)

## References

1. [Kitex 官方文档](https://www.cloudwego.io/zh/docs/kitex/)
2. [Kitex (GitHub - cloudwego/kitex)](https://github.com/cloudwego/kitex)
