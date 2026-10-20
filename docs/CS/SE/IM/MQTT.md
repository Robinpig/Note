## Introduction

MQTT（Message Queuing Telemetry Transport）是一种基于 TCP 的**轻量发布/订阅消息传输协议**。它 1999 年由 IBM 的 Andy Stanford-Clark 与 Arlen Nipper 设计，最初的用途是通过卫星链路监控输油管道——"极小带宽、网络时断时续、端上资源受限"这三个约束塑造了它的全部设计，也解释了为什么二十多年后它会成为物联网与移动长连接场景的默认候选。

标准化路径是：3.1.1 于 2014 年 10 月 29 日成为首个 OASIS 标准版本，2016 年被 ISO/IEC 采纳为 ISO/IEC 20922；5.0 于 2019 年 3 月 7 日发布，在保持轻量的前提下补上了错误上报、请求/响应与可扩展性。

## Publish / Subscribe Model

客户端之间不直接通信，全部经由中心节点 **broker**：发布方把消息打上 topic 发出，broker 负责投递给所有订阅了该 topic 的订阅方。

- **Topic** 是分层的字符串，如 `building/floor2/temperature`，层级分隔符为 `/`；
- **通配符**：`+` 匹配单层，`#` 匹配余下所有层级。订阅 `building/+/temperature` 能收到所有楼层的温度，订阅 `building/#` 则收到整棵树。

这层间接带来的好处是发布方不需要知道谁在听（解耦与多播都免费得到），代价是单点 broker 必须自己做高可用与水平扩展——这也是 IM 场景落地时最先遇到工程量的一处，见 [IM](/docs/CS/SE/IM/IM.md)。

## QoS

MQTT 中的 QoS 指的是发布者与订阅者之间消息传递的保证级别。它提供三个服务级别：

- QoS 0 – 最多交付一次
- QoS 1 – 至少交付一次
- QoS 2 – 只交付一次

其中，使用 QoS 0 可能丢失消息，使用 QoS 1 可以保证收到消息，但消息可能重复，使用 QoS 2 可以保证消息既不丢失也不重复。QoS 等级从低到高，不仅意味着消息可靠性的提升，也意味着传输复杂程度的提升。

对应的握手开销值得注意：**QoS 0 是发后不管**（无确认报文）；QoS 1 需要接收方回 `PUBACK`，发送方未收到则重发，因此重复必然发生；QoS 2 走 `PUBLISH → PUBREC → PUBREL → PUBCOMP` 四步握手，靠两阶段确认实现去重，代价是每条消息四个报文。选型时的经验是把 QoS 当成**每条消息**的属性而不是全局配置——传感器采样用 0，控制指令用 1，只有确实无法容忍重复的记账类消息才用 2。

## Session, Keep Alive and Special Messages

- **Keep Alive**：连接空闲时靠 `PINGREQ` / `PINGRESP` 维持链路并发现死连接，这也是移动端心跳开销的下限来源。
- **会话（Session）**：3.1.1 用 `Clean Session` 标志决定重连后是否沿用旧会话（含未确认的 QoS 1/2 消息与订阅关系）；5.0 将其拆成 `Clean Start` 与 `Session Expiry Interval`，可以更精细地控制"离线消息保留多久"。**若按 clean session 连接，离线期间的消息不会被保留**——这一点常被误认为是丢消息 bug。
- **保留消息（Retained Message）**：broker 为每个 topic 保留最后一条带保留标志的消息，新订阅者一上来就能拿到当前状态，而不必等下一次发布。
- **遗嘱消息（Last Will and Testament）**：连接建立时预先登记一条消息，客户端**异常**断开时由 broker 代为发布，常用于下发"某人离线"的状态。

## Relation to IM

MQTT 头部开销小、弱网容忍度高、天然支持离线消息，因此常被用作 IM 的长连接协议之一。但它也有明确的适用边界：协议本身**没有好友关系、离线消息存储策略、多端同步、消息漫游**这些 IM 语义，这些都要在 broker 之上自己补齐；一旦需要精细化地控制超时重传与弱网策略，很多团队最终会转向自研长连接。选型取舍见 [IM](/docs/CS/SE/IM/IM.md) 与 [闲鱼 IM](/docs/CS/SE/IM/闲鱼IM.md)。

## Links

- [IM](/docs/CS/SE/IM/IM.md)
- [闲鱼 IM](/docs/CS/SE/IM/闲鱼IM.md)
- [DTIM](/docs/CS/SE/IM/DTIM.md)
- [Client](/docs/CS/SE/IM/Client.md)

## References

1. [MQTT Version 5.0 — OASIS Standard](https://docs.oasis-open.org/mqtt/mqtt/v5.0/mqtt-v5.0.html)
2. [MQTT Version 3.1.1 — OASIS Standard](https://docs.oasis-open.org/mqtt/mqtt/v3.1.1/os/mqtt-v3.1.1-os.html)
