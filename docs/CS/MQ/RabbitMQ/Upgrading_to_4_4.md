## Introduction

从 4.3 到 4.4，RabbitMQ 的重心从「换掉元数据存储」转向「把 quorum queue 做成完整的消息延迟与重排机制」。4.3.0（2026-04-23）做的是地基工程：移除 Mnesia 与 CQv1、引入 Khepri、要求 Erlang/OTP 27；4.4.0（2026-10-20）在同一个 Khepri 基础上叠加了业务能力。

本篇面向两种读者：正在 3.x / 4.0 上跑、准备跳到 4.x 的运维（看 **Breaking Changes** 与 **Removed**）；以及已经在 4.3 上跑、想用上 4.4 新能力的开发者（看 **Quorum Queue 新能力**）。

> [!NOTE]
> **版本基线**：4.4.0（2026-10-20 发布，社区支持至 2027-07-31，商业支持至 2028-10-31）。上一系列 4.3.x 最新补丁 4.3.6（2026-09-16，社区支持至 2027-01-31）。4.2 与 4.1 的社区支持均已终止。
>
> 4.4.0 是**特性版本**，不是补丁版本。4.3.x 的最后一个补丁是 4.3.6；4.4 系列的后续补丁（4.4.1+）尚未发布。

## Breaking Changes

### Erlang Version Requirement

4.3.0 起最低要求 **Erlang/OTP 27.0**；4.4.0 **完整支持 Erlang/OTP 28 与 29**（含滚动升级场景）。

> [!WARNING]
> **同时升 RabbitMQ 与 Erlang 的顺序有讲究**：官方明确建议，若要把 RabbitMQ 升到 4.4.0 且同时把 Erlang 升到 28+，**应先升到 4.3.7 或更高的 4.3.x 补丁**——那些补丁同时支持这两个 Erlang 系列，且使用的元数据存储版本保证互操作。跳过这一步的典型症状是节点加入集群时元数据版本不兼容。
>
> 反过来说：**4.3.6 并不支持 Erlang 28/29 的完整场景**，它是 4.3.7 引入的（见 4.4.0 release notes 的升级前置条件说明）。

### AMQP 0-9-1 Headers Are No Longer Parsed

4.4.0 起，以下 AMQP 0-9-1 消息头**不再被解析**：

- `x-amqp-1.0-properties`
- `x-amqp-1.0-app-properties`
- `x-amqp-1.0-message-annotations`
- `x-amqp-1.0-footer`

同理，`x-basic-delivery-mode`、`x-basic-priority`、`x-basic-expiration` 也不再解析。

这两组头的存在意义很窄：3.13 及更早版本用它们携带「经 AMQP 1.0 接收到的消息」的 AMQP 1.0 段落；从 4.0 起就没有任何代码再写这些头了。所以**只有「被 3.13 或更早节点存入、且此后一直没被读过」的消息才会带着它们**，这类消息仍会被投递，但这些头会像普通 `x-` 头一样被转换，而**不会还原成 AMQP 1.0 的 sections**。

> [!TIP]
> 这是一条**数据面兼容性问题，不是配置问题**：队列里的存量消息能被读出来，但 4.3 节点写的这些头在 4.4 节点上不再有特殊含义。若业务逻辑依赖 `x-basic-priority` 恢复优先级，迁移前需要确认消息来源节点版本。

### OpenID Connect Discovery Validation Tightened

4.4.0 对 OIDC discovery 响应做了更严格的校验。以下两种情况会在升级后**校验失败**：

- IdP 提供的是非 HTTPS（`http://`）端点；
- `issuer` claim 与实际用于获取 discovery 文档的端点不匹配。

已知影响 **Cloud Foundry UAA**——它的 issuer 是 token endpoint 的 URL，而不是 discovery endpoint 的前缀。

升级前需设置：

```ini
auth_oauth2.discovery.verify_issuer = false
auth_oauth2.discovery.verify_https_endpoints = false
```

> [!WARNING]
> **这两个键是 4.4.0 新增的**（4.3.6 的 schema 中不存在）。因此「在旧版先关掉校验再升级」这条路会**因为配置了 schema 不认识的键而失败**。正确顺序是：**先升级**，若 discovery 校验报错，再加开关并重启。

### Management API: hash_password Endpoint Changed

```text
GET /api/auth/hash_password/{password}   →   POST /api/auth/hash_password
```

新端点接收 JSON body：

```json
{"password": "..."}
```

写自动化脚本时这是硬中断——旧端点在 4.4.0 上不再存在。

### Classic Queue On-Disk Format v2

classic queue 的共享消息存储新增了 **v2** 磁盘格式（`.sqs`）。新文件自动以 v2 写入，旧的 v1 文件（`.rdq`）原样保留。

> [!WARNING]
> **节点上存在 v2 文件后就不能降级到 4.3.x 或更早**。这条不可逆：一旦有新格式落盘，回滚路径就断了。降级前必须确认所有节点都没有 `.sqs` 文件。

### Other Breaking Notes

- **OpenID Connect** 之外，4.4.0 还调整了 management 插件的 `GET /api/init` 行为、STOMP 的连接限制（三个 `max_connections`）、MQTT 的 `retained_message_store` 两项默认值。
- **x-modulus-hash 路由变得稳定**：拓扑不变时，带同一 routing key 的消息现在会稳定路由到同一绑定目标（此前不保证）。这意味着**升级后同一 routing key 的落点可能与升级前不同** —— 对依赖 hash 分片做数据局部性的场景是需要评估的变更。

> [!NOTE]
> 官方 release notes 说 x-modulus-hash「已从 `rabbitmq_sharding` 移入 core」，但**源码显示 v4.3.0 就已移入**（4.3.0 的 notes 已宣布，PR 同为 #15849，4.3.0 与 4.4.0 的 core 实现逐字节相同）。对 4.2 → 4.3+ 的既有部署来说，这是一个行为变更：排序规则变了，同一 routing key 的落点会变。

## Quorum Queue New Capabilities

### Three Kinds of Message Delay

4.4 给 quorum queue 加了两种新的消息延迟机制，与 4.3 的 delayed retry 构成三种。它们的核心差别在**谁决定延迟、何时决定、消息等在哪**：

| 机制 | 谁决定 | 何时决定 | 消息等待在何处 | 可用版本 |
| --- | --- | --- | --- | --- |
| **Delayed message**（延迟消息） | 生产者 | 生产者发送时 | 队列内，到期才对 consumer 可见 | 4.4 新增 |
| **Delayed retry**（延迟重试） | 消费者 | 消费者 settle 时 | 队列内，到期才对 consumer 可见 | 4.3 起 |
| **Deferred message**（延迟投递） | 消费者 | 消费者 settle 时 | 队列内，需 consumer 用 deferral token 显式取回 | 4.4 新增 |

**Delayed message** 由生产者设定未来投递时间，路由与入队**立即发生**：

- 消息立即路由、立即入队、立即计入队列长度上限；
- 只有到达该时间点才对 consumer 可见；
- **无需任何插件、exchange 类型或额外队列参数** —— 任何 quorum queue 都支持。

AMQP 1.0 客户端用 message annotation 设置，AMQP 0-9-1 客户端用 long header：

```java
long deliveryTime = Instant.now().plus(Duration.ofMinutes(15)).toEpochMilli();
Message message = publisher.message(body)
    .annotation("x-opt-delivery-time", deliveryTime);
publisher.publish(message, context -> { /* confirmation */ });
```

**Deferred message** 解决的是「消息本身没坏，只是来得太早」的场景。AMQP 1.0 的 message properties 提供了 `group-id` 与 `group-sequence` 字段用于排序事件；若多个生产者发送同一账户的事件，consumer 可能先收到 event 5 再收到 event 4。延迟重试在这里不适用——consumer 并不知道 event 4 什么时候会到，只知道自己认得出那一刻。

4.4 的做法：consumer 用**自己提供的 deferral token**（例如 `account-7:5`）把消息挂起，之后用同一个 token 显式取回。因为 token 可以从消息本身推导出来，consumer **不需要记住 broker 分配的序号**。这实现了 Resequencer 集成模式，**不需要任何外部存储**。

取回时还有一个安全网：deferral 时提供的 delivery time 到期后，若 event 4 始终没来，event 5 会**重新变为可用**，由 consumer 决定如何处理这个缺口。

其它用途：人工审批（human-in-the-loop）、等待外部回调的长业务流程。

Deferred message **只在 AMQP 1.0 上可用**，需要设置两个 message annotation：

- `x-opt-deferral-token`：字符串，最长 **256 字节**。

### AMQP 1.0 Connection Uniqueness

AMQP 1.0 客户端现在可以请求某个 **container ID 的独占所有权**。发生冲突时，服务端要么拒绝新连接，要么关闭已有连接 —— 具体取决于客户端的请求方式。这是 AMQP 1.0 Connection Uniqueness 协议扩展。

### Other 4.4 Enhancements

| 变更 | 内容 |
| --- | --- |
| `x-name-prefix` 队列参数 | server-named queue 生成名字时使用的前缀，上限 **64 字节**，默认仍是 `amq.gen`；仅 AMQP 0-9-1 |
| Classic queue 压缩 | classic queue 的 compaction 效率提升 |
| `delivery-limit` policy 可动态生效 | 此前 delivery limit **无法通过 policy 更新**；4.4 起改 policy key 会对**已存在的** quorum queue 生效 |
| STOMP | 独立协议实现，配置项 `max_connections` 等有调整 |
| MQTT | `mqtt.retained_message_store` 两项默认值调整 |

### Availability Zone-Aware Member Placement

4.4 引入**可用区感知的成员放置**。相关的 policy key / 配置键：

| 位置 | 键 | 默认 |
| --- | --- | --- |
| Policy | `queue-leader-locator` | `client-local` |
| Policy | `member-placement-tag` | 未配置时不启用 |
| `rabbitmq.conf` | `queue_leader_locator` | `client-local` |
| `rabbitmq.conf` | `quorum_queue.member_placement_tag` | 未配置时不启用 |

支持的 leader locator：

- **`client-local`**（默认）：优先选择声明客户端所在的节点；
- **`balanced`**：队列总数**少于 1000** 时选择 leader 数量最少的节点；**超过 1000** 时随机选择。

> [!TIP]
> 「超过 1000 就随机」这个阈值意味着：**在队列数破千的集群里，`balanced` 实际退化成了随机分配 leader**，别指望它做负载均衡。

### Enterprise Features in Tanzu RabbitMQ

4.4 同时带来一批**只在商业版 VMware Tanzu RabbitMQ** 可用的能力（开源版没有）：quorum queue 的自动 leader 迁移、JMS topics over AMQP 1.0、AMQP JMS 客户端的 noLocal 订阅与 client ID 唯一性、exchange federation v2。

### Post-Quantum TLS and Erlang 29

4.4.0 的宣传点之一是 **Erlang 29 与后量子 TLS**支持。Erlang 29 的引入本身有前置条件（见上方 Breaking Changes 的升级顺序）。

## Removed in 4.3

> [!NOTE]
> 这一节记录 4.3 的移除项，因为**照着 3.x / 4.0 的资料配置会直接失败**，仍是当前最容易踩的坑。

| 项 | 状态 |
| --- | --- |
| Mnesia 元数据存储 | **4.3 完全移除** |
| 网络分区处理策略（`pause_minority` / `autoheal` 等） | 4.3 移除，**且配置键在 schema 中已完全不存在** |
| Classic Queue v1（`x-queue-version=1`） | 4.3 移除 |
| 经典镜像队列 | 4.0 移除 |
| `ram_node_type` | 4.3 移除 |
| `GET /api/auth` | 4.3 移除 |
| `rabbit_fifo_index` | 4.3 主状态机不再使用 |
| `global_qos` / `queue_master_locator` | 4.3 起 `denied_by_default` |
| `amqp_address_v1` / `amqp_filter_set_bug` | 4.3 起 `denied_by_default` |
| transient non-exclusive 队列 | 4.3 默认禁用 |
| Direct Reply-to 伪队列的 binding | 4.3 起被拒（此前静默接受） |
| 5 个 deprecated feature flag | 4.3 统一转为 `denied_by_default` |

> [!WARNING]
> **release notes 与源码不一致**：官方 4.3.0 release notes 说分区处理配置键「will be accepted by 4.3.0 nodes but won't have any effect」，但**源码实测已彻底移除** —— `rabbit.schema` 中无任何 `cluster_partition_handling` 映射，全树 grep 0 命中。写在 `rabbitmq.conf` 里不只是「无效」，可能导致配置校验失败。运维手册里「4.3 里保留这些键以备回退」的建议是错的。

**仍存在但已非元数据存储**：`rabbit_mnesia.erl` 源码文件还在（172 行），但它只提供 `is_virgin_node/0`、`dir/0` 等**迁移辅助函数**，另有 9 个 `*_m2k_converter.erl` 专用于 Mnesia → Khepri 数据迁移。

## Upgrade Checklist

按顺序执行，每步都留回滚余地：

1. **确认 Erlang 版本**。目标节点要满足 4.4 的最低要求（OTP 27+）；若要同时升 Erlang 28/29，先升到 4.3.7+。
2. **导出 definitions**（`rabbitmqctl export_definitions`）作为回滚前的拓扑快照；数据本身不在其中。
3. **逐节点滚动升级**到 4.4.0。Khepri 需要多数节点在线才能写拓扑，因此升级过程中**保持集群多数在线**，不要同时重启过半节点。
4. **升级后第一件事**：确认 `cluster_partition_handling` 等已移除的配置键不在 `rabbitmq.conf` 里（4.4 的 schema 同样不认识它们），否则节点起不来。
5. **检查 OIDC 集成**：若用 OAuth2/OIDC 且 IdP 是 Cloud Foundry UAA 或提供 http 端点，先按上文加 `verify_issuer` / `verify_https_endpoints` 开关，或确认升级后 discovery 校验通过。
6. **检查 management 脚本**：`GET /api/auth/hash_password/{password}` 换成 `POST /api/auth/hash_password`。
7. **检查 classic queue 是否产生了 `.sqs` 文件**：一旦产生，降级到 4.3.x 就不再可行。

> [!TIP]
> 第 3 步的「多数在线」不是客套话。Khepri 在**多数节点**提交即返回（Mnesia 是全部节点），拓扑变更后立刻从另一节点发布，消息**不保证被路由**。官方给的缓解手段是启动时声明拓扑后注入 1–2 秒暂停、用静态拓扑、或单连接。

## Links

- [RabbitMQ（总览）](/docs/CS/MQ/RabbitMQ.md)
- [RabbitMQ 的队列类型](/docs/CS/MQ/RabbitMQ/Queue_Types.md)
- [RabbitMQ 的集群与元数据](/docs/CS/MQ/RabbitMQ/Cluster_and_Metadata.md)
- [RabbitMQ 的插件生态](/docs/CS/MQ/RabbitMQ/Plugins_and_Ecosystem.md)
- [消息代理的演进方向](/docs/CS/MQ/Future.md)

## References

- https://www.rabbitmq.com/release-information
- https://github.com/rabbitmq/rabbitmq-server/releases/tag/v4.4.0
- https://www.rabbitmq.com/blog/2026/10/20/rabbitmq-4.4-release
- https://www.rabbitmq.com/docs/quorum-queues
- https://www.rabbitmq.com/docs/upgrade
- https://www.rabbitmq.com/docs/partitions
