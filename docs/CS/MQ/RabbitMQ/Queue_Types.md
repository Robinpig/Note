## Introduction

RabbitMQ 4.4 只注册了三种队列类型：`classic`、`quorum`、`stream`。三者的定位完全不同：classic 是默认的单副本队列，quorum 是基于 Raft 的复制队列（官方推荐），stream 是为大吞吐追加写设计的日志型队列。本篇展开三种类型的选型判据、quorum queue 的 Raft 语义与 4.3/4.4 新增能力、stream 的特性边界。

## Queue Types

4.4 只注册了三种队列类型（`rabbit_queue_type.erl` 从 registry 读取）：

| 类型 | 定位 | 复制 | 典型用途 |
| --- | --- | --- | --- |
| `classic` | **默认**，单副本 | 无（4.0 已移除经典镜像队列） | 一般业务队列 |
| `quorum` | **Raft 复制**，推荐 | 是 | 需要可靠复制的业务消息 |
| `stream` | 大吞吐追加写 | 是（本身就是 quorum 系统） | 日志/埋点、大流量管道 |

> [!IMPORTANT]
> `x-queue-version` **只接受 2** —— CQv1 存储引擎已在 4.3 彻底移除，源码树里连v1 文件都没有了。声明 v1 会得到 `unsupported queue version`。而 `x-queue-type: classic` 显式声明**仍然合法**。

### Queue Type Selection

- **默认选 quorum**：复制、内存开销可控、4.3 新增延迟重试。代价是 inherently 更高的延迟与更重的磁盘 I/O。
- **classic 的唯一实质优势**：支持 `x-max-priority`（上限 **255**）与 `auto-delete`。**默认消息优先级是 0**。
- **stream 只在纯追加场景选**：它**不支持** 非持久化、独占、TTL、队列长度限制（改用 retention）、消息优先级、DLX、队列过期（`x-expires`）。

消息从入队到出队的完整规则链在[消息生命周期与死信](/docs/CS/MQ/RabbitMQ/Message_Lifetime_and_DLX.md)，消费侧确认与流控在[消费与流控](/docs/CS/MQ/RabbitMQ/Consumption_and_Flow_Control.md)。

> [!WARNING]
> **不要相信任何"quorum 比 classic 快 N 倍"的说法** —— 4.3 官方文档**没有给出任何量化数字**，只有定性表述，且其对比对象是 4.0 已移除的 classic mirrored queues，不是普通 classic queue。

### Raft Semantics of Quorum Queue

- 成员数默认 **3**（`quorum_cluster_size`），容忍 1 节点故障
- **性能在成员数 > 5 时明显下降**，官方**不建议超过 7 个节点**
- 投递给消费者的消息**始终走 leader**，leader 切换期间消费者收不到新消息
- 消息元数据**≥ 32 bytes/条**；设 TTL 时每条额外 +16 bytes
- WAL 默认最大 **512 MiB**，建议节点内存 ≥ 3× 有效 WAL 大小（高吞吐 4×）

4.3 新增的 quorum 能力：

| 能力 | 配置键 |
| --- | --- |
| **严格优先级**（固定 0–31） | 无需配置，`priority` 属性直接生效 |
| **延迟重试 + backoff** | `x-delayed-retry-type` / `-min` / `-max`（或 policy 同名键），type 取 `disabled`/`all`/`failed`/`returned` |
| **consumer timeout** | `x-consumer-timeout` 或 policy `consumer-timeout` |
| 连接断开超时 | `consumer_disconnected_timeout`（默认 **60 000 ms**） |

延迟重试的 backoff 公式是 `delay = min(min_delay * delivery_count, max_delay)`。

`x-delayed-retry-type` 的四个取值语义取决于 `delivery-count` 是否增加：

| 取值 | 语义 |
| --- | --- |
| `disabled` | 禁用延迟重试（默认） |
| `all` | 所有被返回的消息都延迟，**无论 delivery-count 是否增加** |
| `failed` | 仅延迟 delivery-count **已增加**的消息 |
| `returned` | 仅延迟 delivery-count **未增加**的消息 |

启用延迟重试时**必须提供 `x-delayed-retry-min`**（源码 `rabbit_quorum_queue.erl` 的 `arguments` 白名单里三个键都在，但 min 无默认值）。

> [!WARNING]
> **quorum 会静默忽略 `x-max-priority`** —— 从 classic 迁移时若保留该参数，不报错也不生效。另外 `max-priority` 对 quorum 是 **unsupported policy**（用 policy 设置会报错，用 x-arg 设置只是静默忽略）。未设 `priority` 的消息在 quorum 视为 **4**、在 classic 视为 **0**，迁移会让优先级分布发生变化。

### New in 4.4: Three Kinds of Message Delay

4.4 给 quorum queue 加了两种延迟机制，与 4.3 的 delayed retry 构成三种。它们的核心差别在**谁决定延迟、何时决定、消息等在哪**：

| 机制 | 谁决定 | 何时决定 | 消息等待在何处 | 可用版本 |
| --- | --- | --- | --- | --- |
| **Delayed message** | 生产者 | 生产者发送时 | 队列内，到期才对 consumer 可见 | 4.4 新增 |
| **Delayed retry** | 消费者 | 消费者 settle 时 | 队列内，到期才对 consumer 可见 | 4.3 起 |
| **Deferred message** | 消费者 | 消费者 settle 时 | 队列内，需 consumer 用 deferral token 显式取回 | 4.4 新增 |

**Delayed message** 由生产者设定未来投递时间，**路由与入队立即发生** —— 消息立即路由、立即入队、立即计入队列长度上限，只有到达该时间点才对 consumer 可见。

- AMQP 1.0 客户端用 message annotation `x-opt-delivery-time`（Unix epoch **毫秒**）；
- AMQP 0-9-1 客户端用 long header `x-opt-delivery-time`；
- **无需任何插件、exchange 类型或额外队列参数** —— 任何 quorum queue 都支持；
- AMQP 1.0 consumer 还可在 `modified` outcome 的 annotations 里设置 `x-opt-delivery-time` 来延迟重投，**它优先于线性退避计算结果**。

> [!TIP]
> 与 delayed retry 的关键差别在**确认时机**：delayed message 是「先入队、到期才可见」，所以生产者立刻就拿到 publisher confirm —— 目标 quorum queue 复制成功即确认，**不存在后续 RabbitMQ 内部重新发布可能失败的问题**（目标队列不可用或已达长度上限都不会导致确认丢失）。

**Deferred message** 解决的是「消息本身没坏，只是来得太早」的场景，例如需要按序处理的账户事件流。AMQP 1.0 的 message properties 提供 `group-id` 与 `group-sequence` 用于排序；若多个生产者发送同一账户的事件，consumer 可能先收到 event 5 再收到 event 4 —— 延迟重试在这里不适用，因为 consumer 不知道 event 4 何时会到，只知道自己认得出那一刻。

4.4 的做法：consumer 用**自己提供的 deferral token**（例如 `account-7:5`）挂起消息，之后用同一 token 显式取回。token 可从消息本身推导，consumer **不需要记住 broker 分配的序号**。这实现了 Resequencer 集成模式，**不需要任何外部存储**。

取回时有安全网：deferral 时提供的 delivery time 到期后，若被等待的消息始终没来，被挂起的消息会**重新变为可用**，由 consumer 决定如何处理缺口。

其它用途：人工审批（human-in-the-loop）、等待外部回调的长业务流程。

> [!IMPORTANT]
> Deferred message **只在 AMQP 1.0 上可用**。需要设置 `x-opt-deferral-token` annotation（字符串，最长 **256 字节**）。

### New in 4.4: Availability Zone-Aware Placement

4.4 引入可用区感知的成员放置：

| 位置 | 键 | 默认 |
| --- | --- | --- |
| Policy | `queue-leader-locator` | `client-local` |
| Policy | `member-placement-tag` | 未配置时不启用 AZ 感知放置 |
| `rabbitmq.conf` | `queue_leader_locator` | `client-local` |
| `rabbitmq.conf` | `quorum_queue.member_placement_tag` | 未配置时不启用 AZ 感知放置 |

支持的 leader locator：

- **`client-local`**（默认）：优先选择声明客户端所在的节点；
- **`balanced`**：队列总数**少于 1000** 时选择 leader 数量最少的节点；**超过 1000** 时随机选择。

> [!TIP]
> 「超过 1000 就随机」这个阈值意味着：**在队列数破千的集群里 `balanced` 实际退化成随机分配 leader**，别指望它做负载均衡。

### Raft Tuning Parameters

4.3 起，quorum queue 的 Raft 参数可通过 `rabbitmq.conf` 的 `quorum_queue.*` 命名空间配置：

| 键 | 默认值 |
| --- | --- |
| `quorum_queue.segment_max_size_bytes` | **64 000 000（64 MiB）** |
| `quorum_queue.segment_max_entries` | **4096** |
| `quorum_queue.wal_max_size_bytes` | **536 870 912（512 MiB）** |
| `quorum_queue.wal_max_entries` | **500 000** |
| `quorum_queue.wal_max_batch_size` | **4096** |
| `quorum_queue.wal_compute_checksums` | **true** |
| `quorum_queue.segment_compute_checksums` | **true** |
| `quorum_queue.max_append_entries_rpc_batch_size` | **16** |
| `quorum_queue.compress_mem_tables` | **true** |
| `quorum_queue.snapshot_chunk_size` | **1 000 000（1 MB）** |
| `quorum_queue.commands_soft_limit` | **32**（channel 进入流控前允许的未确认消息数上限） |

### Continuous Membership Reconciliation

CMR 让 quorum queue 的成员数随集群规模自动对齐：

| `rabbitmq.conf` 键 | 默认值 |
| --- | --- |
| `quorum_queue.continuous_membership_reconciliation.enabled` | **false** |
| `quorum_queue.continuous_membership_reconciliation.target_group_size` | 无默认值 |
| `quorum_queue.continuous_membership_reconciliation.auto_remove` | **false** |
| `quorum_queue.continuous_membership_reconciliation.interval` | **3 600 000 ms（60 分钟）** |
| `quorum_queue.continuous_membership_reconciliation.trigger_interval` | **10 000 ms（10 秒）** |

> [!WARNING]
> CMR **不能替代显式成员管理**。永久移除且无法恢复的节点通常仍需显式处理 —— 节点或成员故障本身**不会触发 CMR 自动扩容**。新节点加入集群后也不会自动承载已有的 quorum queue 成员，需显式添加或启用 CMR。

### Quorum Queue Limitations

明确不支持的：

- **非持久队列** —— quorum queue 始终 durable；
- **exclusive queue** —— 不支持 `exclusive=true`；
- **server-named queue** —— 不支持由服务端自动生成名字；
- **global QoS** —— 不支持 channel 级全局 prefetch，从启用 global QoS 的 channel 消费 quorum queue 会返回 channel error，**必须用 per-consumer QoS**；
- **exclusive consumer** —— 需要单消费者消费请用 Single Active Consumer；
- **`x-overflow: reject-publish-dlx`** —— 不支持。

其他值得知道的限制：

- `reject-publish` **不是严格上限** —— 队列可能至少超出限制 1 条，超出数量与通知 channel 时仍在途的消息数有关，不适合要求精确上限的场景；
- 使用任意消息 TTL 时每条消息额外约 **16 bytes** 内存开销；
- 返回并重新入队的消息**不保留原优先级**，按返回时的原始顺序重排；
- **少于 3 个节点无法完整获得容错保证**（3 成员队列至少需 2 个节点在线）；偶数成员数不能充分利用成员分布，建议用奇数；
- quorum queue 把队列名转换成 Erlang atom，高 churn 场景可能触及默认 **500 万** atom 上限；
- quorum queue **始终把消息持久化到磁盘**，即使消息 delivery mode 为 transient（但转入 DLX 的消息保留原始 delivery mode）。

> [!TIP]
> 官方明确**不建议**用于：临时队列 / exclusive queue、高频创建删除队列、要求最低延迟的场景、未使用 publisher confirms 或 manual acknowledgements 的应用、**超长积压队列（例如 5M+ 消息）**、大规模 fanout。需要复制 + 可重复读取的 fanout 场景，RabbitMQ Streams 更合适。

### Poison Message and delivery-limit

`delivery-limit` 默认 **20**（源码常量 `DEFAULT_DELIVERY_LIMIT`），`-1` 可禁用；policy 与 x-arg 同时为正时取 **min**。

达到上限后的行为：**有 DLX 则死信，无 DLX 则直接丢弃**。

> [!WARNING]
> 4.3 起判定基准从 `acquired-count` 改为 **`delivery-count`**。后果是 `basic.nack` 与 `modified(delivery-failed=false)` **不消耗** delivery-limit —— 可以无限返回。只有 `reject`、`modified(delivery-failed=true)`、连接/channel 崩溃才计入。照 3.x/4.0 的 acquired-count 心智模型算出的重投次数在 4.3 是错的。
>
> 4.4 的变化：**`delivery-limit` 的 policy 变更现在对已存在的 quorum queue 生效** —— 此前 delivery limit 无法通过 policy 更新。
>
> 另一个 4.3 起的坑：`prefetch > 1` 时，若一批未确认消息被整体重复 requeue，delivery limit 机制可能**一次丢弃该批中的所有未确认消息**。所以 quorum queue 应当配置 DLX，避免超限消息被无意丢弃。

### Streams Queue

- **不需要 AMQP 1.0 客户端** —— 可以用 AMQP 0-9-1 客户端当普通队列用（只需用 consumer ack），也能绑定到任意 exchange
- 但官方**强烈推荐 stream protocol**（`rabbitmq_stream` 插件），因为只有它能拿到全部 stream 特性与最佳吞吐
- streams **内部以 AMQP 1.0 编码存储**，所以 AMQP 0-9-1 消息中 header 里的数组/表等复合值**不会被转换**（header 存为 application properties，只支持简单类型）
- 消费**必须设 QoS prefetch**，ack 机制推进 offset
- 默认 `x-stream-max-segment-size-bytes = 500000000`（500 MB），`x-stream-filter-size-bytes = 16`（16–255）
- ⚠️ 这两个参数**即使 policy 变更也不会应用到已存在的 stream**，只在**声明时**有 policy 才生效 → **只用 queue argument 配置**
- stream 是 quorum 系统，官方建议集群**各节点数一致**

**消费起点**由 consumer 参数 `x-stream-offset` 决定：

| 取值 | 语义 |
| --- | --- |
| `first` | 从日志中第一条可用消息开始 |
| `last` | 从最后写入的 chunk 开始（chunk 是 stream 的存储与传输单位，一批几条到几千条不等） |
| `next` | 与不指定相同 |
| 数值 | 精确 offset；不存在时**钳到日志开头或结尾** |
| 时间戳 | 按消息**到达时间**（非应用提供的时间戳）定位；钳到最近的 offset |
| 间隔 | 相对当前时间的字符串，格式同 `x-max-age` |

用 AMQP 0-9-1 时时间戳的精度是**秒**（POSIX time，1970-01-01 UTC 起的秒数）。由于 stream 按 chunk 切分且**同一 chunk 共享一个时间戳**，consumer 会附着在 chunk 边界上，因此可能收到发布时间略早于指定时间戳的消息。

**retention** 取代了 TTL 与队列长度限制，两个参数可组合：

| 参数 | 说明 |
| --- | --- |
| `max-age` | 单位支持 `Y` `M` `D` `h` `m` `s`（如 `7D`） |
| `max-length-bytes` | 日志总字节上限 |

> [!IMPORTANT]
> **retention 按 segment 逐个评估**，所以 segment size 是实际生效的第三个参数。**只要某个 segment 里至少有一条消息，stream 就总会留下至少一个 segment**。用 broker 提供的 offset 跟踪时，每个 consumer 的 offset 作为非消息数据持久化在 stream 内部。
>
> 另注意：`x-max-age` 与 `x-max-length-bytes` 是**可以由 policy 动态更新**的，且 **policy 优先于 queue argument** —— 这与上面 segment size / filter size 的行为相反。

### Classic Queue Feature Matrix

stream 的能力矩阵（官方对照表）：

| 特性 | classic | stream |
| --- | --- | --- |
| 非持久队列 | 支持 | **不支持** |
| 独占队列 | 支持 | **不支持** |
| 每消息持久化 | 每消息可选 | **始终** |
| 成员变更 | 不支持 | 手动 |
| TTL | 支持 | 不支持（改用 retention） |
| 队列长度限制 | 支持 | 不支持（改用 retention） |
| 消息常驻内存 | 视配置 | **从不** |
| 消息优先级 | 支持 | **不支持** |
| 消费者优先级 | 支持 | **不支持** |
| 死信 exchange | 支持 | **不支持** |
| 遵循 policy | 支持 | 支持（见 retention） |
| 响应内存告警 | 支持 | **不响应**（只用极少 RAM） |
| 毒消息处理 | 支持 | **不支持** |


## Links

- [RabbitMQ（总览）](/docs/CS/MQ/RabbitMQ.md)
- [RabbitMQ 的集群与元数据](/docs/CS/MQ/RabbitMQ/Cluster_and_Metadata.md)
- [RabbitMQ 的消费与流控](/docs/CS/MQ/RabbitMQ/Consumption_and_Flow_Control.md)
- [消息投递语义（at-most-once / at-least-once / exactly-once）](/docs/CS/MQ/MQ.md?id=message-delivery-semantics)

## References

- https://www.rabbitmq.com/docs/quorum-queues
- https://www.rabbitmq.com/docs/streams
- https://www.rabbitmq.com/docs/queues
