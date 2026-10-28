## Introduction

消费侧的三件事决定了一个消费者会不会把 broker 拖垮：`prefetch` 决定一次投递多少、`consumer_timeout` 决定卡住多久算超时、ack/nack 的 `multiple` 参数决定一次确认覆盖多宽的范围。本篇展开这三处的具体行为与各自的失效模式，其中 `multiple=true` 的语义是最容易造成生产事故的一个细节。

## Consumption and Flow Control

### prefetch

AMQP 规范层默认 **0 = 无限**（不限流）。这是**服务端**配置键 `default_consumer_prefetch` 的默认值，源码是 `{false, 0}`。

- **`prefetch_size != 0` 不支持**，直接报错
- `global_qos` 已 deprecated，4.3 起 `denied_by_default`

> [!TIP]
> prefetch 是 RabbitMQ 最有效的背压手段。配合 `x-single-active-consumer`（classic 与 quorum 均支持，默认 false）可以实现「一份顺序消费 + 多份并发处理」的组合。

> [!IMPORTANT]
> **quorum queue 不支持 global QoS** —— 从启用 global QoS 的 channel 消费 quorum queue 会返回 **channel error**，必须用 per-consumer QoS / prefetch。这不是「不推荐」，是**用不了**。

prefetch 的实际执行者是 channel 的 **limiter 进程**（独立于 channel，见[架构与运行时模型](/docs/CS/MQ/RabbitMQ/Architecture_and_Runtime.md)）。它按 channel 与所有消费队列共享的状态调解投递 —— 所以**多个队列的消费者其实在竞争同一个 channel 的投递能力**，prefetch 设大了会同时放大所有队列的未确认消息数。

### consumer_timeout

默认 `1800000` ms（30 分钟），**单位是毫秒**，schema 只校验正整数不校验下限。每 1 分钟周期性检查一次，**低于 1 分钟不支持、低于 5 分钟不推荐**。

超时后的行为按协议分叉：

| 协议 | 超时后 |
| --- | --- |
| AMQP 0-9-1（支持 `consumer_cancel_notify`） | 取消该 consumer，消息回队 |
| AMQP 0-9-1（不支持） | **channel 以 `PRECONDITION_FAILED` 关闭**，该 channel 上**所有 consumer 的所有未确认消息全部回队** |
| AMQP 1.0 | `DISPOSITION(state=released)`，不 detach link |
| MQTT | 结束该订阅 |

超时**只增加 `acquired-count`，不消耗 `delivery-limit`**。

配置层级（4.3 起 quorum queue 支持 per-queue 覆盖）：

| 位置 | 键 |
| --- | --- |
| `rabbitmq.conf`（全局） | `consumer_timeout` |
| `advanced.config` | `rabbit.consumer_timeout`（默认 `undefined`，即禁用全局超时） |
| Policy | `consumer-timeout` |
| 队列参数 | `x-consumer-timeout` |
| AMQP 1.0 consumer 级 | `rabbitmq:consumer-timeout` |
| AMQP 0-9-1 consumer 级 | `x-consumer-timeout` |

> [!WARNING]
> **classic queue 与 stream 从 4.3 起永不评估 consumer timeout** —— 给它们配了不会生效，监控不到任何超时。这不是客户端 bug，是配置无效。
>
> 另外在 `advanced.config` 里把它设成 `undefined` 等于禁用，官方**不推荐**。

**`consumer_disconnected_timeout`** 是另一条独立机制：消费者所在节点因网络分区等原因不可达时，quorum queue 在该时长后退回该消费者持有的消息。默认 **60 000 ms**（60 秒）。

> [!WARNING]
> **schema 注释是过时的** —— `rabbit.schema` 的示例注释写 `10000`，**源码两处默认都是 `60_000`**。照注释改成 10000 是把 60s 调小 6 倍，会导致分区恢复时消息被过快重投。
>
> 另有一条同样常被误传的：`max_ack_rtt` **根本不存在** —— 全树 grep 0 命中，不是合法 schema 键。真实机制就是 `consumer_timeout` + `consumer_disconnected_timeout` 这一对。

### Multiple Parameter Pitfall of nack/ack

这是最容易造成生产事故的一个细节。源码 `collect_acks` 遍历的是**channel 级** `unacked_message_q`，**不是某个 consumer 的队列**：

- `multiple=true` + tag=N → 确认该 **channel** 上所有 tag ≤ N 的消息，**跨 consumer、跨 queue**
- `multiple=true` + tag=0 → 确认该 channel 上**一切**（源码注释显式标注这是 AMQP 0-9-1 规范特例）

```erlang
%% The special case for 0 comes from the AMQP 0-9-1 spec: if the multiple field
%% is set to 1 (true), and the delivery tag is 0, this indicates
%% acknowledgement of all outstanding messages (by a client).
collect_acks(UAMQ, 0, true) ->
    {lists:reverse(?QUEUE:to_list(UAMQ)), ?QUEUE:new()};
```

> [!WARNING]
> 同一 channel 上开多个 consumer 时，误用 `multiple` 会**连带确认其他 consumer 的消息**。settle 顺序是 oldest-first（tag 升序）。

### Delivery Counters

quorum queue 上有两个计数 header，语义不同：

| Header | 含义 |
| --- | --- |
| `x-delivery-count` | 实际**失败**投递次数，`delivery-limit` 以此为基准 |
| `x-acquired-count` | 消息被**分配**给 consumer 的次数 |

建议用 `x-acquired-count` 统计「消息可能被消费者看到的次数」；但它表示「已分配」，**不保证消费者实际处理了该消息**。

### Delayed Retry on Return

quorum queue 的延迟重试把「返回消息」与「延迟」解耦：由 `x-delayed-retry-type` 决定哪些返回会被延迟，`x-delayed-retry-min` / `-max` 决定延迟区间。

退避公式：

```text
delay = min(min_delay * delivery_count, max_delay)
```

由于 **`basic.nack` 与 `modified(delivery-failed=false)` 不增加 delivery-count**，它们的延迟**不会随重试次数增长** —— 只有真正失败（`reject`、`modified(delivery-failed=true)`、崩溃、连接丢失）才会让延迟按倍数拉长。

> [!TIP]
> 4.4 提供了另一条路：AMQP 1.0 consumer 可在 `modified` outcome 的 annotations 里显式设置 `x-opt-delivery-time`（绝对时间戳，毫秒），**它优先于线性退避计算结果**。需要精确控制「什么时候再给我」时用这个，而不是调 min/max 系数。

消息最终被丢弃还是转入死信，由[消息生命周期与死信](/docs/CS/MQ/RabbitMQ/Message_Lifetime_and_DLX.md)里的 TTL 与 DLX 规则决定。


## Links

- [RabbitMQ（总览）](/docs/CS/MQ/RabbitMQ.md)
- [RabbitMQ 的队列类型](/docs/CS/MQ/RabbitMQ/Queue_Types.md)
- [RabbitMQ 的架构与运行时模型](/docs/CS/MQ/RabbitMQ/Architecture_and_Runtime.md)
- [AMQP 0-9-1 协议结构与工作流（Spring AMQP 侧）](/docs/CS/Framework/Spring/AMQP.md)

## References

- https://www.rabbitmq.com/docs/consumers
- https://www.rabbitmq.com/docs/confirms
- https://www.rabbitmq.com/docs/quorum-queues
