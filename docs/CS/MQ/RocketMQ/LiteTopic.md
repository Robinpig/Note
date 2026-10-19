## Introduction

LiteTopic 是 RocketMQ **5.5.0** 引入的新消息模型（RIP-83「Lite Topic: A New Message Model」，PR #9800），发布说明对它的一句话定性是 **"This version introduces Lite Mode, a lightweight subscription mechanism designed for AI scenarios"** —— 面向 AI Agent 会话、异步任务与海量轻量订阅。

版本门槛写在官方文档的兼容性表里：**Server 5.5.0 起，客户端 gRPC SDK 5.1.0 起**。也就是说这套模型只在新协议栈上可用，Remoting 老客户端不在支持范围。

## Why LiteTopic Is Needed

会话型负载把传统 topic / group 模型的三个隐含假设同时打破了：

- **通道数量可控** —— 每个 Agent 会话各占一个 topic，topic 元数据会巨量膨胀，注册与推送成本随通道数上升。
- **扫描是有界的** —— Broker 轮询全量 topic 检查有没有新消息，通道一多，无效扫描的 CPU 开销**线性增长**，而绝大多数通道本来就是空闲的。
- **主题预先定义** —— 会话在运行时才出现，无法提前建 topic；而 group 模型天生是「一组消费者分摊一个主题」，不适合「每个会话独占一个通道」。

因此 LiteTopic 不是「更轻的 topic」，而是把**通道的分配与回收从用户侧移到 Broker 侧**。

## Model: Parent Topic Plus Child Channels

官方定义：LiteTopic 是**单个父 topic 内的轻量、临时子通道**，「You can create millions of fine-grained message channels -- one per session, task, or user -- without the resource overhead of separate topics」；每个 LiteTopic 是父 topic 内**自动管理的二级容器**，自带有序队列、生命周期与订阅范围，用于按会话 / 任务 / 用户这类「同一业务逻辑下的不同子类」分组消息。

> [!WARNING]
> 官方同时给出了代价，且这一条最容易被宣传语丢掉：**每个 LiteTopic 默认只有一个 queue** —— 「which limits per-channel TPS but enables ordered consumption and fine-grained subscription control」。
>
> 它换到的是「**海量通道 + 通道内有序**」，不是「海量并行分区」。把它当成分区数的替代品来扩并发是误用。

父 topic 需建成 Lite 类型，并在创建时设置过期值；TTL 约束与参数上限见官方 Parameter limits 一节。

## Implementation Traces

以下线索来自 5.5.0 / 5.5.1 的发布说明条目（**条目级证据，未逐项回源码核实**），但足以看出实现取向：

- 压在 **POP 无状态消费**之上 —— 修复项里出现 `PopLiteLongPollingService#cleanUnusedResource`，说明长轮询与通道清理是绑在一起的。
- ConsumeQueue 走 **RocksDB** 路径（提交「Improve PopLite: rename RocksDB CQ path and schedule autoClean」）—— 用 KV 存储承接海量通道的队列索引，而不是继续堆文件，这正是「元数据膨胀」那条动机的直接回应。
- 5.5.1 补上**通配订阅**与 consumer suspend。
- 配额护栏存在：`ResponseCode.LITE_SUBSCRIPTION_QUOTA_EXCEEDED = 2018`（见 [RocketMQ 5.x](/docs/CS/MQ/RocketMQ/RocketMQ5.md)）—— 有显式配额码，意味着海量通道仍需按租户/命名空间限额，不是无限开。

## Unverified

- LiteTopic 与 DLedger / Controller、与分层存储（`tieredstore`）的交互，未核实。
- 单个父 topic 下 LiteTopic 的实际容量上限、`autoClean` 的触发条件与默认 TTL 数值，本次未取到官方明确表述，不写具体数字。
- 官方文档没有 Lite Mode 的性能对比数据（只有「reduced resource consumption」的定性说法），不要引用第三方跑分替代。

## Links

- [RocketMQ](/docs/CS/MQ/RocketMQ/RocketMQ.md)
- [RocketMQ 5.x](/docs/CS/MQ/RocketMQ/RocketMQ5.md)
- [Consumer](/docs/CS/MQ/RocketMQ/Consumer.md)
- [MQ](/docs/CS/MQ/MQ.md)
- [未来发展方向](/docs/CS/MQ/Future.md?id=consumer-shapes-change-ai-era-workloads)

## References

1. [Apache RocketMQ 5.5.0 Release Notes](https://github.com/apache/rocketmq/releases/tag/rocketmq-all-5.5.0)
2. [RocketMQ LiteTopic](https://rocketmq.apache.org/docs/domainModel/03litetopic)
