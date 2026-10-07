## Introduction

[CloudEvents](https://cloudevents.io/) 是 CNCF 的事件元数据**规范**（已进入 Serverless WG 标准），用一组通用格式描述事件数据，让不同服务、平台、系统之间的事件可以互通。它本身不是消息队列、也不是事件总线，而是"事件信封（envelope）"的统一约定：没有它，Kafka 事件、对象存储回调、Webhook、消息推送各有各的字段名（event id 放哪、时间叫什么、来源怎么标），每个消费者都要为每个来源写适配。

## Envelope Structure

一个 CloudEvent 包含必需属性、可选属性和业务载荷 `data`：

| 属性 | 必需 | 含义 |
|------|------|------|
| `specversion` | ✔ | 规范版本，如 `1.0` |
| `id` | ✔ | 事件唯一标识（生产者保证，结合 source 全局唯一） |
| `source` | ✔ | 事件产生方 URI（如 `/clusters/eu/prod/storage`） |
| `type` | ✔ | 事件类型（如 `com.example.order.created`） |
| `time` | | 发生时间（RFC3339） |
| `datacontenttype` | | data 的内容类型（application/json 等） |
| `subject` | | 事件主体（如对象 key、订单 id） |
| `dataschema` | | data 的 schema 地址 |
| `data` / `data_base64` | | 业务数据（文本/结构化或二进制） |

JSON 示例（结构化模式，整个事件就是一条 JSON 消息）：

```json
{
  "specversion": "1.0",
  "id": "a1b2-...",
  "source": "/payment-service",
  "type": "com.shop.order.paid",
  "time": "2026-09-18T10:00:00+08:00",
  "subject": "order/1001",
  "datacontenttype": "application/json",
  "data": { "orderId": "1001", "amount": 199.00 }
}
```

## Two Binding Modes

- **结构化（Structured content）**：元数据与 data 放在同一个编码里（如整条 JSON 消息发到 Kafka/HTTP body）；
- **二进制（Binary content）**：data 保持原生格式放在消息体，元数据映射成传输层头——HTTP 用 `ce-id`、`ce-source` 等前缀头，Kafka 用消息头。二进制模式不改动原有 payload，适合数据已经是 Protobuf 等二进制格式的场景。

规范还定义了 Protobuf/Avro 编码和 HTTP、AMQP、MQTT、Webhook 等协议绑定。

## What Problem It Solves

- **可移植性**：同一套事件处理逻辑不随云厂商事件格式而变，Knative Eventing、EventBridge、各 FaaS 触发器都以它为通用输入；
- **可观测与审计**：统一 id/source/time 后，跨系统追踪一条业务事件有了公共字段（可与 traceparent 扩展结合，见 [分布式链路追踪](/docs/CS/Distributed/Tracing/Tracing.md)）；
- **消费路由**：按 `type` 订阅、按 `source` 过滤，网关不必解析每类业务 data；
- 与 [Kafka Streams](/docs/CS/MQ/Kafka/Streams.md)、事件驱动架构的关系：CloudEvents 定义事件长什么样，流处理/消息系统负责怎么传、怎么算。

## Links

- [Cloud Native](/docs/CS/Cloud/Cloud.md)
- [Serverless](/docs/CS/SE/Serverless.md)
- [Kafka Streams](/docs/CS/MQ/Kafka/Streams.md)

## References

1. [CloudEvents 官方规范 v1.0](https://github.com/cloudevents/spec/blob/v1.0.2/cloudevents/spec.md)
2. [CNCF CloudEvents](https://cloudevents.io/)
