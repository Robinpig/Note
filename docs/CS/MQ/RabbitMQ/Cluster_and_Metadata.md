## Introduction

RabbitMQ 4.3 起元数据存储从 Mnesia 换成 Khepri（Raft），这是理解 4.x 集群行为的钥匙：集群要求多数节点在线才能接受拓扑变更，少数派侧的操作直接超时，没有网络分区处理策略可选。本篇展开 Khepri 的一致性语义、vhost 与各复制层的分工、节点加入与移除、磁盘与内存阈值，以及跨集群搬消息的 Federation 与 Shovel 的语义差异。

## Cluster and Metadata

### Khepri: Architectural Change in 4.3

4.3 起**Khepri 成为唯一的元数据存储**，彻底替代 Mnesia（自动迁移，一次性操作）。它的 Raft 语义决定了集群行为：

- **需要多数节点在线**才能接受写/删/成员变更 —— 不只是网络分区，多数节点停机也一样
- **脑裂时少数派侧操作直接超时**，没有 pause/autoheal 可选
- 该策略**不可配置**，是 Raft 算法本身的设计

> [!WARNING]
> **一致性有真实差异**：Khepri 在**多数节点**提交即返回，Mnesia 是全部节点。所以拓扑变更后立刻从另一节点发布，消息**不保证被路由**。官方给的缓解手段是启动时声明拓扑后注入 1–2 秒暂停、用静态拓扑、或单连接。
>
> 读取按组件分两类：多数读走本地 cache（最终一致）；**线性一致读走 leader**，新 leader 选出前会暂停。

### Relationship with vhost

| 组件 | 说明 |
| --- | --- |
| **元数据（Khepri）** | vhost/队列/exchange/binding/权限/策略 —— Raft 复制，**多数派才能写** |
| **quorum queue** | 队列消息 —— 独立 Raft 组，始终经 leader |
| **stream** | 队列消息 —— 独立 Raft 组，consumer **可从任意 replica 读**，不受 leader 切换影响 |
| **经典镜像队列** | 4.0 已移除 |

### Node Join and Removal

- **加入**：peer discovery 自动，或 `cluster_formation.peer_discovery_backend` 配置；空白节点「加入第一个可达 peer 的集群」
- **移除**：在**仍存在的成员**上执行 `rabbitmqctl forget_cluster_node`
- **重置过的节点必须先从集群移除**，否则会成为幽灵成员
- 未知节点清理默认**仅告警**（`only_log_warning = true`）；改成 `false` 会强制清理，但**清理后无法再 rejoined**
- 4.3 的 `forget_cluster_node` 行为变更：先移除 quorum/stream 成员，再离开元数据集群

### Disk and Memory Thresholds

> [!IMPORTANT]
> **4.3 没有四档 watermark**，只有两个单阈值：

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `disk_free_limit` | **50 000 000 字节（50 MB）** | 支持绝对值与相对 RAM（`{mem_relative, 2.0}`），同设则 absolute 优先 |
| `vm_memory_high_watermark` | 示例 0.6 | 相对值 |

已失效的配置：`vm_memory_high_watermark_paging_ratio` 与 `memory_monitor_interval` 都标注 **DEPRECATED，4.0 起不再使用**；`vm_memory_low_watermark` 在 4.3 **根本不存在**。

**文件描述符**：官方不给固定推荐值，规则是**连接数 × 1.5**（如支撑 10 万连接则设 15 万）。提高 OS 上限时**必须同步提高 `ERL_MAX_PORTS`**，检查用 `rabbitmqctl eval 'erlang:system_info(port_limit).'`。

> [!NOTE]
> 阈值、文件描述符预算与 Prometheus 采集的具体配置已移到[运维与可观测性](/docs/CS/MQ/RabbitMQ/Operations_and_Observability.md)，本篇只保留集群语义部分。

### Federation and Shovel

两者都用于跨集群搬消息，但语义不同：

| 特性 | Shovel | Queue Federation |
| --- | --- | --- |
| 移动条件 | **无条件移动** | **仅当上游无本地consumer 时** |
| 方向 | 始终单向 | 可双向或多向（N 个集群） |
| 定义方式 | dynamic（runtime parameter，推荐）或 static（`advanced.config`） | upstream + policy |
| 变更生效 | dynamic 随时增删，无需重启 | policy 动态 |

选型判据：**要「消费者在哪边消息就在哪边」用 federation；无条件搬运、跨协议、跨产品用 shovel**。

> [!WARNING]
> **static shovel 与 dynamic shovel 的默认ack-mode 不同**，这是最隐蔽的一个坑：
> - **dynamic**（runtime parameter，推荐）默认 **`on-confirm`** → at-least-once
> - **static**（`advanced.config`）默认 **`no_ack`** → **at-most-once，可能丢消息**，且无任何告警
>
> 三个合法值：`on-confirm`（等publisher confirm）/ `on-publish`（重发即ack）/ `no-ack`（收到即ack）。
>
> 另一个坑：被目标端 reject 的消息，AMQP 0-9-1 与 local shovel 会**重新入队**，但 **AMQP 1.0 shovel 直接丢弃**。

**Federation 的已知局限**：一个集群同时只能应用一条 policy，N 条同优先级 policy 中**随机选一条** —— 启用 federation 的 policy **不保证是生效的那条**。缓解办法是显式区分优先级、避免 `--apply-to all`、用 dedicated policy。

**4.2 新增 `local` shovel**：不用任何协议，直接用内部 API 在本集群内消费/发布，只能用于声明它的那个集群。

**4.4 的 shovel 变化**：AMQP 1.0 shovel 的一个修复 —— 被目标端 reject 的消息，AMQP 0-9-1 与 local shovel 会**重新入队**，而 **AMQP 1.0 shovel 此前直接丢弃**；4.4 修复了这个行为差异。

> [!WARNING]
> **4.3.6 起 shovel / federation 的 direct 连接也受 `channel_max_per_node` 限制** —— 此前认为该限制只作用于网络连接的说法已过时。这条会在节点连接数较高时表现为 shovel / federation 静默失败或建链失败。

### New in 4.4: Availability Zone-Aware Placement

4.4 引入 quorum queue 的**可用区感知成员放置**，让成员跨可用区分布而非随机分布：

| 位置 | 键 | 默认 |
| --- | --- | --- |
| Policy | `member-placement-tag` | 未配置时不启用 |
| `rabbitmq.conf` | `quorum_queue.member_placement_tag` | 未配置时不启用 |

配合 leader locator（`client-local` / `balanced`）使用，详见[队列类型](/docs/CS/MQ/RabbitMQ/Queue_Types.md)。

### Enterprise Cross-Cluster Features

4.4 在商业版（VMware Tanzu RabbitMQ）中加入了两项跨集群能力，开源版没有：

- **exchange federation v2** —— federation 从「队列级」扩展到 exchange 级；
- **distributed shovel** —— 把 shovel 分布到所有集群节点，可扩展性与容错更好（开源版的 shovel 是单点的）。

配套还有 **Warm Standby Replication**（`rabbitmq_warm_standby` + `rabbitmq_schema_definition_sync`）：用 AMQP 1.0 持续把 schema 定义从上游主集群复制到一个或多个下游备集群。


## Links

- [RabbitMQ（总览）](/docs/CS/MQ/RabbitMQ.md)
- [RabbitMQ 的运维与可观测性](/docs/CS/MQ/RabbitMQ/Operations_and_Observability.md)
- [RabbitMQ 的插件生态](/docs/CS/MQ/RabbitMQ/Plugins_and_Ecosystem.md)
- [副本与共识机制](/docs/CS/Distributed/Replica.md)

## References

- https://www.rabbitmq.com/docs/cluster-formation
- https://www.rabbitmq.com/docs/metadata-store/everyday-operations
- https://www.rabbitmq.com/docs/partitions
- https://www.rabbitmq.com/docs/federation
- https://www.rabbitmq.com/docs/shovel
