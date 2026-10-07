## Introduction

RPC（Remote Procedure Call）是一种「让远程调用看起来像本地调用」的进程间通信范式。它的透明性靠 **stub**（客户端/服务端桩）和**编组（marshalling）**实现：调用方只写一个普通函数调用，参数收集、网络传输、结果解包全由桩自动完成，业务代码无需感知网络。

本目录覆盖 RPC 的概念模型、代表性框架，以及序列化这一横切支柱。注意 RPC 与 [RESTful](/docs/CS/Distributed/RPC/RESTful.md) 是两种相对立的远程交互风格：前者以「动作/操作」为中心，后者以「资源」为中心。

## Membership Navigation

- [RPC](/docs/CS/Distributed/RPC/RPC.md) — 概念模型（client/server stub、透明性）、参数传递与引用、绑定（binding）、重复执行语义、孤儿等异常场景。
- [Marshalling](/docs/CS/Distributed/RPC/Marshalling.md) — 序列化/编码格式与向前向后兼容性，是 RPC 的底层支柱。
- [Protocol Buffers](/docs/CS/Distributed/RPC/ProtoBuf.md) — Google 的接口描述语言 + 二进制编码，强 schema、前后兼容靠字段编号。
- [Thrift](/docs/CS/Distributed/RPC/Thrift.md) — Facebook 开源的跨语言 RPC + 序列化框架，IDL 同时定义接口与类型。
- [RESTful](/docs/CS/Distributed/RPC/RESTful.md) — 与 RPC 相对的资源风格，以 HTTP 动词 + URI 表达状态转移。
- [Fury](/docs/CS/Distributed/RPC/Fury.md) — JIT 编译 + 元数据共享的高性能序列化，主打极致吞吐与低延迟。

## Relationship Axes

RPC 的「透明」承诺在跨语言、跨故障域时会被打破：异构机器的字节序/对齐、引用参数的拷贝、网络分区下的超时与重试，都要求程序员显式处理。框架（gRPC、Dubbo、Kitex、Thrift）的价值就在于把这些横切问题用 stub 自动挡掉，而 [Marshalling](/docs/CS/Distributed/RPC/Marshalling.md) 决定了数据在线上长什么样、能否平滑演进。

## Links

- [Distributed Systems](/docs/CS/Distributed/Distributed.md) — RPC 在「进程通信、故障模型」全局中的位置
- [gRPC](/docs/CS/Framework/gRPC/gRPC.md) — 基于 HTTP/2 + ProtoBuf 的现代 RPC 框架
- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md) — 阿里巴巴的 Java RPC 与服务治理框架
