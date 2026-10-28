## Introduction

RabbitMQ 同时说多种协议语，但它们并不共享实现路径。AMQP 0-9-1 是核心协议且被 RabbitMQ 多处扩展；AMQP 1.0 自 4.0 起成为 core protocol，与 0-9-1 **线级完全不共享**；MQTT / STOMP / Streams 是插件提供的独立入口；WebSocket 是传输层叠加。本篇给出这张协议地图与各协议的关键差异。

## Protocol

| 协议 | 状态 | 关键说明 |
| --- | --- | --- |
| **AMQP 0-9-1** | 核心协议 | 被 RabbitMQ 多处扩展 |
| **AMQP 1.0** | 4.0 起成为 core protocol | 与 0-9-1 **线级完全不共享** |
| **MQTT** | 插件 | 原生支持 3.1 / 3.1.1 / 5.0 |
| **STOMP** | 插件 | 内部代理到 AMQP 0-9-1 |
| **Streams protocol** | 插件 | 官方强烈推荐 |
| **WebSocket** | AMQP 1.0 / MQTT / STOMP over WebSocket | 4.3 加了 Origin 校验 |
| **HTTP** | management 插件 | 仅诊断/低量消息，**无可靠投递** |

> [!TIP]
> STOMP 在 4.3 改用 **exclusive queue** —— 因为 transient non-exclusive 队列被默认禁用了。

**4.4 的 STOMP 变化**：改为**独立协议实现**（不再只是代理到 AMQP 0-9-1 的薄层），并调整了 `max_connections` 等配置项。

### AMQP 1.0 in 4.4

4.4.0 给 AMQP 1.0 加了两项能力：

**Connection Uniqueness** —— 客户端可以请求某个 **container ID 的独占所有权**。冲突时服务端要么拒绝新连接、要么关闭已有连接，取决于客户端的请求方式。这是 AMQP 1.0 Connection Uniqueness 协议扩展。

**Deferred message** —— quorum queue 的延迟投递，只在 AMQP 1.0 上可用，需要 `x-opt-deferral-token` annotation（最长 256 字节）。详见[队列类型](/docs/CS/MQ/RabbitMQ/Queue_Types.md)。

### AMQP 1.0 in 4.3

Rejected outcome 含队列名与拒绝原因（`queue: <name>` / `reason: maxlen | unavailable`）；Single Active Consumer 状态变化用 flow frame 通知；重复 link handle 返回 `handle-in-use`。

### AMQP 0-9-1 Headers No Longer Parsed in 4.4

4.4.0 起，以下 AMQP 0-9-1 消息头**不再被解析**：`x-amqp-1.0-properties`、`x-amqp-1.0-app-properties`、`x-amqp-1.0-message-annotations`、`x-amqp-1.0-footer`，以及 `x-basic-delivery-mode`、`x-basic-priority`、`x-basic-expiration`。

这不影响正常业务消息（4.0 起就没有代码再写这些头），但**存量消息**（3.13 及更早节点写入且此后未读）上的这些头会失去特殊含义。详见[升级到 4.4](/docs/CS/MQ/RabbitMQ/Upgrading_to_4_4.md)。

### WebSocket Origin Validation

4.3 起 WebSocket 接入增加了 **Origin 校验**（`strict_origin_validation`），用于防止浏览器端的跨站 WebSocket 连接。4.4 调整了这项行为。

各协议入口对应的插件归属见[插件生态](/docs/CS/MQ/RabbitMQ/Plugins_and_Ecosystem.md)。


## Links

- [RabbitMQ（总览）](/docs/CS/MQ/RabbitMQ.md)
- [RabbitMQ 的插件生态](/docs/CS/MQ/RabbitMQ/Plugins_and_Ecosystem.md)
- [AMQP 0-9-1 协议结构与工作流（Spring AMQP 侧）](/docs/CS/Framework/Spring/AMQP.md)

## References

- https://www.rabbitmq.com/docs/protocol
- https://www.rabbitmq.com/docs/queues
- https://www.rabbitmq.com/docs/mqtt
- https://www.rabbitmq.com/docs/stomp
