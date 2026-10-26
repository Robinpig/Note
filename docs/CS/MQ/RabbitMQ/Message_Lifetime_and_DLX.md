## Introduction

一条消息从进入队列到被丢弃，会经过若干道与「时间」和「失败」相关的规则：TTL 决定它活多久、dead-letter exchange 决定它失败后去哪、delivery-limit 决定重投多少次算放弃、`x-expires` 与 `auto-delete` 决定队列本身活多久。本篇展开这四组规则，并给出一个反直觉但极重要的结论：过期消息在到达队首之前不会释放资源。

## Message Lifetime and Dead-letter

### Two Types of TTL Approaches

| 方式 | 配置 | 说明 |
| --- | --- | --- |
| 按队列 | policy `message-ttl` / x-arg `x-message-ttl` | 非负整数，**毫秒** |
| 按消息 | AMQP 属性 `expiration` | 字符串形式的数字；两者同时存在取**较小值** |

`x-message-ttl = 0` → 消息到达队列即过期（除非能立即投递给 consumer），**不产生 `basic.return`**；若配了 DLX 则会死信。

> [!WARNING]
> **过期消息只在到达队首时才被丢弃**。这意味着：
> - 过期消息会**堆积在未过期消息后面**，占用的内存/磁盘**不释放**
> - 它们**照常计入队列统计**
> - 存在天然竞态：消息可能在写入 socket 后、到达 consumer 前才过期
>
> 所以「队列深度持续增长但 TTL 已过」是**正常行为，不是泄漏**。想让资源立即释放要么 purge，要么改用队列级 TTL。

**quorum queue 的 TTL 扫描覆盖所有优先级级别** —— 避免低优先级消息阻塞已过期的高优先级消息（这是 4.3 起的明确行为）。

**stream 队列不支持 TTL** —— 用 retention（`max-age` / `max-length-bytes`）替代，且 retention 按 segment 评估。

### Delayed Message as a Lifetime Mechanism

4.4 起 quorum queue 支持**生产者指定的未来投递时间**（`x-opt-delivery-time`，Unix epoch 毫秒）。它与 TTL 是两件不同的事：

| | TTL | Delayed message |
| --- | --- | --- |
| 方向 | 消息活**太久**后失效 | 消息**太早**时不可见 |
| 决定者 | 队列 / 消息属性 | **生产者** |
| 生效时机 | 到达队首时判定 | 到期后才对 consumer 可见 |
| 是否立即入队 | 是 | **是**（立即路由、立即入队、立即计入队列长度） |

两者可以叠加：一条消息可以既「24 小时后过期」，又「1 小时后才可投递」。

重投次数的判定与毒消息处理在[队列类型](/docs/CS/MQ/RabbitMQ/Queue_Types.md)里展开。

### DLX and Dead-letter Header

- DLX **就是普通 exchange**，按普通方式声明
- **x-arg 优先于 policy**
- 未设 `dead-letter-routing-key` → 使用消息原始的**全部** routing keys（含 CC，不含 BCC）
- 设了 → 改写为该 key，且 **`CC` header 被移除**
- **DLX 不存在 → 消息静默丢弃**（quorum 侧只打 WARN）
- 死信时TTL 被移除，防止在后续队列再次过期
- requeue 会**保留原始过期时间**
- reason 四值：`rejected`、`expired`、`maxlen`、`delivery_limit`

声明队列时需要同时具备：队列的 configure + 队列的 read + DLX 的 **write** 权限。

**quorum 的 at-least-once 死信**：

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `dead-letter-strategy` | `at-most-once` | 4.3 新增 at-least-once，保留消息直到目标确认 |
| `overflow` | `drop-head` | quorum **不支持** `reject-publish-dlx` |
| `max-length` / `max-length-bytes` | **无默认**（不设即不限） | `reject-publish` 也非严格上限，至少可能超出 1 条 |

> [!WARNING]
> **只配 `dead-letter-strategy: at-least-once` 而忘了改 `overflow=reject-publish`，会打 WARN 并静默回退为 at-most-once** —— 配置「看起来生效了」，实际保证等级低一档。从 at-least-once 切回 at-most-once 会**删除所有未被目标确认的死信**。

**at-least-once 的运行代价**（启用后要知道的事）：

| 现象 | 说明 |
| --- | --- |
| 死信消息仍属源队列 | 在目标队列确认前，死信仍是源队列的「live」消息，**计入队列长度等资源限制** |
| 目标不可用会堆积 | DLX 不存在、消息无法路由、目标队列不可用或拒绝消息时，源队列会积累大量死信 |
| 目标可能收到重复消息 | 内部死信消费者会**周期重试** |
| 每源队列一个内部消费者 | 该消费者与 quorum queue **leader 同节点**，并把死信消息体**保存在内存中** |
| 默认 prefetch 32 | 可通过 `rabbit` app 的 `dead_letter_worker_consumer_prefetch` 调整 |
| 额外开销 | at-least-once 会增加内存与 CPU 消耗 |

> [!IMPORTANT]
> 启用 at-least-once 需要**同时**满足三个条件：`dead-letter-strategy = at-least-once`、`overflow = reject-publish`、`dead-letter-exchange = <exchange>`，并**启用 `stream_queue` feature flag**。`drop-head` 与 at-least-once 不兼容。

### Dead-letter Loop Detection

有cycle 检测，但**只在「全自动循环」时丢弃消息**：循环路径上任何一次死信原因是 `rejected`（即客户端显式reject 过）就不丢，把打破循环的责任交给应用（`mc.erl:493-507`）。

### Difference Between x-expires and auto-delete

| 维度 | `x-expires` | `auto-delete` |
| --- | --- | --- |
| 触发条件 | 队列**未被使用**达指定时长 | 队列**曾有消费者、且最后一个消费者断开** |
| 粒度 | 毫秒，**必须正整数，不能为 0** | 即时 |
| 重新 declare | **续租** | 不适用 |
| `basic.get` | 会刷新 lease | 不适用 |
| 默认 | **无默认** | false |

**队列 TTL 只对 transient（非 durable）classic queue 有意义**，streams **不支持过期**。且队列整体到期时，里面的消息**不会死信**。


## Links

- [RabbitMQ（总览）](/docs/CS/MQ/RabbitMQ.md)
- [RabbitMQ 的队列类型](/docs/CS/MQ/RabbitMQ/Queue_Types.md)
- [死信队列与消息积压](/docs/CS/MQ/MQ.md?id=dead-letter-queues)

## References

- https://www.rabbitmq.com/docs/ttl
- https://www.rabbitmq.com/docs/dlx
- https://www.rabbitmq.com/docs/quorum-queues
