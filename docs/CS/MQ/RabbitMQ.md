## Introduction

RabbitMQ 是用 Erlang/OTP 编写的一个开源消息代理（broker），以**队列模型**为中心：消息先进交换机（exchange），由交换机路由到一个或多个队列，消费者从队列取走。它不以吞吐量为首要目标，而是靠 **AMQP 协议的表达能力 + 灵活路由** 在金融、订单这类需要复杂路由规则的场景里占有一席之地。

> [!NOTE]
> **版本基线：4.4.0**（2026-10-20 发布，社区支持至 2027-07-31，商业支持至 2028-10-31）。上一系列 4.3.x 最新补丁 4.3.6（2026-09-16，社区支持至 2027-01-31）。4.2 与 4.1 的社区支持均已终止。
>
> 4.3 是一次地基级大版本：4.3.0（2026-04-23）把元数据存储从 Mnesia 换成 **Khepri**（Raft），移除 CQv1 存储引擎与全部网络分区处理策略，最低要求 **Erlang/OTP 27.0**。4.4.0 在此之上把 quorum queue 补齐成完整的延迟与重排机制，并完整支持 Erlang/OTP 28 与 29。
>
> 本库所有默认值与行为均以 `rabbitmq-server` 源码常量（`deps/rabbit/src/`）与官方文档核实，不是从博客或记忆推的。

四条最容易记错的主线，先摆在这里，每一条都在下方对应分册展开：

1. **RabbitMQ 的 exchange 不止四种** —— 4.x 有 4 个 core 类型 + 2 个 core 内的 `x-*` 类型 + 至少 5 个插件类型。
2. **元数据复制与消息复制是两套系统** —— Khepri 要求集群多数派在线才能写拓扑，quorum queue 是每队列一个独立 Raft 组且始终经 leader，stream 更是可以直接从任意 replica 读。
3. **「存在」不等于「生效」** —— `global_qos` 在 schema 里还在但已 `denied_by_default`；`x-max-priority` 在 quorum queue 上不报错但被静默忽略；`disk_free_limit` 之外的四档 watermark 根本不存在。
4. **计数基准在 4.3 变过** —— delivery-limit 从 `acquired-count` 改为 `delivery-count`，`basic.nack` 不再消耗它。

## Positioning and Trade-offs

| | RabbitMQ 4.4 | Kafka 4.3 | RocketMQ 5.5 |
| --- | --- | --- | --- |
| 模型 | **队列**（消费即出队） | 分区日志（按 offset 读） | 队列 / 分区日志 |
| 路由能力 | **最强**（exchange + binding + header 匹配） | 几乎无（只有分区选择） | Tag / SQL92 |
| 吞吐 | 低（单条消息优化，不支持批量） | **极高**（批量 + 顺序写） | 高 |
| 存储 | 内存优先，空间不足才落盘 | 磁盘顺序写 | mmap commitlog |
| 消费位点 | **无**（投递即移除，不能重放） | 有 offset | 有位点 |
| 扩展方式 | 纵向（换更强硬件） | 加 partition | 加 broker，topic 多也不掉性能 |

**选择 RabbitMQ 的判据**：业务需要按内容路由（同一 topic 下不同下游只收自己关心的消息）、需要 header 过滤、需要低延迟的短平快任务分发、队列数量可控。**不该选它的判据**：需要高吞吐、需要重放历史、需要海量 topic。

> [!TIP]
> 它的路由能力有代价：每条消息都要过 exchange 路由 + binding 匹配，而 Kafka/RocketMQ 走的是分区直连。这也是它吞吐上不去的根本原因，而非单纯的实现效率问题 —— 详见[架构与运行时模型](/docs/CS/MQ/RabbitMQ/Architecture_and_Runtime.md)里的消息路径分析。

## Where to Start

RabbitMQ 的知识面比看起来宽，但真正需要先想清楚的是**三个问题**：消息怎么路由过去、消息放在哪种队列里、消息怎么被确认和丢弃。这三条链对应三篇入口：

- **路由**决定了「同一个业务事件的不同下游怎么各取所需」—— RabbitMQ 的核心卖点，四种 core 类型只是起点，还有 `x-*` 类型、插件类型、Alternate Exchange、exchange-to-exchange binding。
- **队列类型**决定了「可靠性与吞吐的取舍点在哪」—— classic / quorum / stream 三者的能力边界互不重叠，quorum 上还有一整套 4.x 新增的延迟与优先级机制。
- **投递确认与生命周期**决定了「出问题时消息去哪、谁来重试」—— prefetch、consumer_timeout、`multiple` 参数的语义、TTL、DLX、delivery-limit，这几处的失效模式是生产事故的主要来源。

集群与元数据是第四个必须单独理解的面：4.3 换成 Khepri 之后，「集群要几个节点在线才能改拓扑」这个问题有了与 3.x 完全不同的答案。而安全、插件、运维、升级则是横切面。

## The Section Map

- **[架构与运行时模型](/docs/CS/MQ/RabbitMQ/Architecture_and_Runtime.md)** —— Erlang/OTP 进程模型：connection / channel / reader / writer / limiter / 队列进程各自负责什么，以及为什么这决定了 `multiple` 的语义、prefetch 的位置、以及吞吐的天花板。想理解「为什么是这样」而不是「是什么」，从这篇开始。
- **[Exchange 与路由](/docs/CS/MQ/RabbitMQ/Exchange_and_Routing.md)** —— 4.4 的 exchange 类型全集、routing key 匹配规则、topic 通配符的边界、headers 的四个 `x-match` 取值、Alternate Exchange 与 exchange-to-exchange binding。
- **[队列类型](/docs/CS/MQ/RabbitMQ/Queue_Types.md)** —— classic / quorum / stream 的选型判据、quorum 的 Raft 语义与 4.3/4.4 新增能力、stream 的特性矩阵。
- **[消费与流控](/docs/CS/MQ/RabbitMQ/Consumption_and_Flow_Control.md)** —— prefetch、consumer_timeout、ack/nack 的 `multiple` 参数、delivery-limit 与毒消息处理。
- **[消息生命周期与死信](/docs/CS/MQ/RabbitMQ/Message_Lifetime_and_DLX.md)** —— 两种 TTL 方式、DLX 与死信头、at-least-once 死信、循环检测、`x-expires` 与 `auto-delete` 的差异。
- **[集群与元数据](/docs/CS/MQ/RabbitMQ/Cluster_and_Metadata.md)** —— Khepri 的一致性语义、vhost 与各复制层的分工、节点加入与移除、磁盘与内存阈值、Federation 与 Shovel。
- **[协议面](/docs/CS/MQ/RabbitMQ/Protocol.md)** —— AMQP 0-9-1 / AMQP 1.0 / MQTT / STOMP / Streams / WebSocket / HTTP 的地图与关键差异。
- **[安全与访问控制](/docs/CS/MQ/RabbitMQ/Security_and_Access_Control.md)** —— 认证与授权的分离、vhost 隔离、三项权限正则、topic permissions、用户 tags，以及 4.4.0 的两个 breaking change。
- **[插件生态](/docs/CS/MQ/RabbitMQ/Plugins_and_Ecosystem.md)** —— 插件启停机制、enabled_plugins 文件、Tier 1 / Tanzu / 已废弃清单，以及 core 与插件的边界。
- **[运维与可观测性](/docs/CS/MQ/RabbitMQ/Operations_and_Observability.md)** —— Prometheus 三端点语义与指标族、management 的定位、`rabbitmq-diagnostics` 的五级健康检查、CLI 工具分工、资源阈值。
- **[升级到 4.4](/docs/CS/MQ/RabbitMQ/Upgrading_to_4_4.md)** —— 4.4.0 的 breaking changes、quorum queue 新能力、4.3 的移除清单、升级检查表。

## Common Pitfalls List

1. **`max_ack_rtt` 不存在** —— 网上流传的「quorum queue 有 `max_ack_rtt` 默认 30s」在 4.x 全树 grep **0 命中**，它不是合法 schema 键。真实机制是 `consumer_timeout`（30 min）+ `consumer_disconnected_timeout`（60 s）。
2. **`consumer_disconnected_timeout` 的 schema 注释是过时的** —— `rabbit.schema` 的示例注释写 `10000`，**源码两处默认都是 `60_000`**。照注释改成 10000 是把 60s 调小 6 倍，会导致分区恢复时消息被过快重投。
3. **`consumer_timeout` 单位是毫秒** —— 写成 `consumer_timeout = 30` 会得到 30 毫秒，且 schema 不校验下限，队列几乎必然持续超时。
4. **过期消息不释放资源** —— 过期消息只在到达队首时才被丢弃，会堆积在未过期消息后面并照常计入统计。队列深度持续增长但 TTL 已过是**正常行为，不是泄漏**。
5. **`multiple=true` 跨 consumer 生效** —— 确认的是**整个 channel** 上 tag ≤ N 的消息，跨 consumer、跨 queue。同一 channel 开多个 consumer 时是事故源。
6. **at-least-once 死信静默回退** —— 忘了配 `overflow=reject-publish` 就退回 at-most-once，且从 at-least-once 切回会**删除所有未被目标确认的死信**。
7. **static shovel 默认可能丢消息** —— `advanced.config` 里不写 `ack-mode` 就是 `no_ack`（at-most-once），且无任何告警。
8. **`x-max-priority` 在 quorum 上静默失效** —— 且未设 priority 的消息默认值不同（quorum 4 / classic 0），迁移会让优先级分布发生变化。
9. **delivery-limit 计数基准 4.3 变了** —— nack 与 `modified(delivery-failed=false)` 不再消耗它，可以无限返回。
10. **stream 不需要 AMQP 1.0 客户端** —— 但 AMQP 0-9-1 的复合 header 不会被转换。
11. **topic 超过 2 个 `#` 声明失败** —— 4.3 新增硬限制，超出即 `binding_invalid`。
12. **`x-match` 有 `all-with-x` / `any-with-x` 两个文档未提的取值** —— 不指定时等价 `all`。
13. **磁盘告警没有四档 watermark** —— 只有 `disk_free_limit` 单阈值；`vm_memory_low_watermark` 不存在。
14. **`4.3.6` 起 shovel/federation 的 direct 连接也受 `channel_max_per_node` 限制** —— 之前认为该限制只作用于网络连接已过时。
15. **`x-modulus-hash` 的落点在 4.2 → 4.3+ 之间变过** —— 排序规则改了，同一 routing key 的落点会变；4.4 起该路由才变为**稳定**。

## Links

- [消息系统（发布/订阅与消息代理）](/docs/CS/MQ/MQ.md?id=message-system)
- [消息代理与数据库的对比](/docs/CS/MQ/MQ.md?id=message-brokers)
- [消息投递语义（at-most-once / at-least-once / exactly-once）](/docs/CS/MQ/MQ.md?id=message-delivery-semantics)
- [死信队列与消息积压](/docs/CS/MQ/MQ.md?id=dead-letter-queues)
- [AMQP 0-9-1 协议结构与工作流（Spring AMQP 侧）](/docs/CS/Framework/Spring/AMQP.md)

## References

- https://www.rabbitmq.com/release-information
- https://www.rabbitmq.com/docs/quorum-queues
- https://www.rabbitmq.com/docs/consumers
- https://www.rabbitmq.com/docs/streams
- https://www.rabbitmq.com/docs/metadata-store/everyday-operations
- https://www.rabbitmq.com/docs/partitions
- https://github.com/rabbitmq/rabbitmq-server/releases/tag/v4.4.0
