## Introduction

RPC（Remote Procedure Call）是一种「让远程调用看起来像本地调用」的进程间通信范式。它的透明性靠 **stub**（客户端/服务端桩）和**编组（marshalling）**实现：调用方只写一个普通函数调用，参数收集、网络传输、结果解包全由桩自动完成，业务代码无需感知网络。

本目录覆盖 RPC 的概念模型、序列化这一横切支柱，以及与之相对的 [RESTful](/docs/CS/Distributed/RPC/RESTful.md) 风格。具体的 RPC 框架实现（gRPC、Dubbo、Kitex 等）按仓库约定放在 `CS/Framework/` 下，入口见后。

## Membership Navigation

- [RPC](/docs/CS/Distributed/RPC/RPC.md) — 概念模型（client/server stub、透明性）、参数传递与引用、绑定（binding）、重复执行语义、孤儿等异常场景，以及主流框架对照。
- [Marshalling](/docs/CS/Distributed/RPC/Marshalling.md) — 序列化/编码格式与向前向后兼容性，是 RPC 的底层支柱。
- [Protocol Buffers](/docs/CS/Distributed/RPC/ProtoBuf.md) — Google 的接口描述语言 + 二进制编码，强 schema、前后兼容靠字段编号。
- [Thrift](/docs/CS/Distributed/RPC/Thrift.md) — Facebook 开源并捐赠给 ASF 的跨语言 RPC + 序列化框架，IDL 同时定义接口与类型，四层架构可正交替换。
- [RESTful](/docs/CS/Distributed/RPC/RESTful.md) — 与 RPC 相对的资源风格，以 HTTP 动词 + URI 表达状态转移。
- [Fury](/docs/CS/Distributed/RPC/Fury.md) — JIT 编译 + 元数据共享的高性能序列化；项目已更名为 Apache Fory。

## Framework Implementations

概念模型之外，真正落地的是框架。按仓库约定它们位于 `CS/Framework/`：

- [gRPC](/docs/CS/Framework/gRPC/gRPC.md) — 绑定 HTTP/2 + Protobuf 的现代 RPC 框架，跨语言支持最广。细分为三册：
    - [gRPC Architecture](/docs/CS/Framework/gRPC/Architecture.md) — HTTP/2 帧映射、Length-Prefixed Message、metadata 与状态码。
    - [gRPC Streaming](/docs/CS/Framework/gRPC/Streaming.md) — 四种通信模式、流控窗口与 BDP 动态调整、超时与取消传播。
    - [gRPC Ecosystem](/docs/CS/Framework/gRPC/Ecosystem.md) — 拦截器、命名解析与负载均衡策略、xDS proxyless 网格、可观测性、grpc-gateway 转译。
- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md) — 阿里巴巴的 Java RPC 与服务治理框架，含 Triple 协议以兼容 gRPC。
- [Kitex](/docs/CS/Framework/kitex.md) — 字节跳动开源的 Go RPC 框架，默认 Thrift + [Netpoll](/docs/CS/Framework/Netpoll.md)。

## Relationship Axes

RPC 的「透明」承诺在跨语言、跨故障域时会被打破：异构机器的字节序/对齐、引用参数的拷贝、网络分区下的超时与重试，都要求程序员显式处理。这恰好是 [RPC.md](/docs/CS/Distributed/RPC/RPC.md) 里那组经典问题的由来——它们不是实现缺陷，而是分布式与本地计算在语义上的根本差异（同一组论点在 Waldo 等人的《A Note on Distributed Computing》中被系统阐述）。

由此可以把本目录的笔记排成一条递进的链条：**概念模型**解释"透明性是什么、在哪里破裂" → **Marshalling** 解释"数据在线上长什么样、能否平滑演进" → **各序列化实现**（Protobuf / Thrift / Fury）给出不同取舍 → **RESTful** 提供另一种以资源为中心的交互风格 → **框架**（gRPC / Dubbo / Kitex）把这些横切问题用 stub 与运行时自动挡掉。

## Links

- [Distributed Systems](/docs/CS/Distributed/Distributed.md) — RPC 在「进程通信、故障模型」全局中的位置
- [gRPC](/docs/CS/Framework/gRPC/gRPC.md) — 基于 HTTP/2 + ProtoBuf 的现代 RPC 框架
- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md) — 阿里巴巴的 Java RPC 与服务治理框架
- [Kitex](/docs/CS/Framework/kitex.md) — Go 生态的 RPC 框架
- [Marshalling](/docs/CS/Distributed/RPC/Marshalling.md) — 序列化与兼容性通论
