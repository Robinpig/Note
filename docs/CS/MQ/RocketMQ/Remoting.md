## Introduction

Remoting 是 RocketMQ 自研的**远程通信基础模块**（`rocketmq-remoting`），NameServer、Broker、Producer、Consumer 之间的所有 RPC（注册路由、发消息、拉消息、心跳）都构建在它之上。它基于 Netty 实现长连接 + 自定义私有协议，用一个统一的请求/响应抽象把"同步调用、异步调用、单向发送"三种语义收口。RocketMQ 5.x 新增了 gRPC 协议（Proxy 层），但存量内核仍然是 Remoting。

## Core Classes

| 组件 | 职责 |
|------|------|
| RemotingService | 顶层接口：启动/关闭、注册请求处理器（registerProcessor） |
| RemotingServer | 服务端：监听端口、管理连接、按请求 code 分发到 NettyRequestProcessor |
| RemotingClient | 客户端：连接维护、路由表（brokerAddr→channel）、三种调用方式 |
| NettyRemotingServer / NettyRemotingClient | 上述接口的 Netty 实现 |
| NettyConnectManageHandler | ChannelDuplexHandler：管理连接生命周期（连接建立、断开、空闲检测、自动重连） |
| NettyServerHandler / NettyClientHandler | 业务入站处理：解码 RemotingCommand、分发 processor 或唤醒响应等待方 |
| RemotingCommand | 统一报文：请求/响应共用，含 code、language、opaque、remark、extFields、body |

## Protocol and Codec

- 报文 = 4 字节大端长度 + 序列化头（header length + header bytes）+ body；长度字段最高位标记序列化类型（JSON / RocketMQ 序列化），第二个字节位掩码标记压缩、请求/响应、oneway；
- 解码器在拆包时严格校验长度上限，防止半包/粘包和非法大包；
- body 大时可选压缩（zip），压缩阈值可配。

## How Requests and Responses Are Paired: opaque + responseTable

客户端发请求时分配自增 `opaque`（请求 ID），把 `ResponseFuture` 放进 `responseTable`（并发 map）：

- **invokeSync**：在 ResponseFuture 上 `CountDownLatch.await(timeout)`，响应回来时 NettyClientHandler 按 opaque 找到 future、放结果并 countDown；
- **invokeAsync**：future 持有回调，响应到达或超时由线程池执行 invokeCallback；
- **invokeOneway**：不登记 future、不等响应，写完即返回（心跳等场景）。

这是"单条 TCP 长连接多路复用"的经典实现，和 Dubbo 的 request/response id、Kafka 协议的 correlationId 同源。

## Connection Management (NettyConnectManageHandler)

- 客户端与每个 Broker/NameServer 维持长连接，channel 事件（CONNECT/CLOSE/IDLE）触发 `ChannelEventListener` 更新路由表；
- 空闲检测靠 Netty 的 IdleStateHandler，超时未读写则关连接并由 ScanResponseTable/重连任务重建；
- 服务端侧记录每个 channel 的客户端版本、心跳时间，过期连接清理；
- 顺序消息/事务消息等场景还会对 channel 做 hash 选择（同一队列固定连接）。

## Thread Model

服务端收到请求后不在 Netty IO 线程做业务：按请求 code 注册不同 processor，每个 processor 可挂独立线程池（send/consumer/poll/heartbeat 分开隔离），避免慢操作拖垮整个 broker 的 IO——线程池隔离思想，对照 [Bulkhead](/docs/CS/SE/CircuitBreaker.md) 与 [Netty](/docs/CS/Framework/Netty/Netty.md) 的 EventLoop 分工。

## Relationship with 5.x/gRPC

RocketMQ 5.x 引入无状态 Proxy，对外提供标准 gRPC（多语言友好、云原生），Proxy 内部仍可通过 Remoting 与 Broker 通信；同时保留私有协议客户端的兼容。选型上，新多语言客户端走 gRPC，存量 Java 生态仍是 Remoting。

## Links

- [RocketMQ](/docs/CS/MQ/RocketMQ/RocketMQ.md)
- [Broker](/docs/CS/MQ/RocketMQ/Broker.md)
- [Namesrv](/docs/CS/MQ/RocketMQ/Namesrv.md)
- [Producer](/docs/CS/MQ/RocketMQ/Producer.md)
- [Netty](/docs/CS/Framework/Netty/Netty.md)

## References

1. [RocketMQ 官方文档 - architecture](https://rocketmq.apache.org/docs/)
2. [RocketMQ 源码：rocketmq-remoting 模块](https://github.com/apache/rocketmq/tree/develop/remoting)
