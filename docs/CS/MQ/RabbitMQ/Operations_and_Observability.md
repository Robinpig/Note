## Introduction

RabbitMQ 的可观测性分两套：**Prometheus 插件**面向生产环境的长期指标采集，**management 插件**面向管理与低频诊断。本篇给出这两条采集路径的端点语义、指标族清单、健康检查的分级用法，以及日常运维 CLI 的分工。

> [!NOTE]
> **版本基线**：4.4.0（2026-10-20 发布，社区支持至 2027-07-31）。上一系列 4.3.x 最新补丁 4.3.6（2026-09-16，社区支持至 2027-01-31）。
>
> 官方推荐生产环境用 **Prometheus 插件 + Prometheus + Grafana**；management 插件的定位是管理与低频诊断，不是指标平台。

## Prometheus Endpoints

`rabbitmq_prometheus` 插件默认监听**专用 TCP 端口 15692**（不是 management 的 15672）：

```bash
rabbitmq-plugins enable rabbitmq_prometheus
curl {hostname}:15692/metrics
```

端口与监听地址可配：

```ini
prometheus.tcp.port = 15692
prometheus.tcp.ip = 0.0.0.0
```

确认实际绑定：

```bash
rabbitmq-diagnostics -s listeners
```

```text
Interface: [::], port: 15692, protocol: http/prometheus, purpose: Prometheus exporter API over HTTP
```

### Three Endpoints

| 端点 | 默认返回 | 粒度 | 查询参数 |
| --- | --- | --- | --- |
| `/metrics` | **聚合指标** | 按指标名聚合，响应大小基本恒定 | 无专用参数 |
| `/metrics/per-object` | 始终逐对象 | 所有实体 | 无专用参数 |
| `/metrics/detailed` | **默认不返回任何指标** | 按需逐对象 | `family`、`vhost`、`queue` |

关键配置项及其默认值：

```ini
prometheus.return_per_object_metrics = false
```

这个开关**只影响 `/metrics`**：设 true 会让 `/metrics` 改为返回逐对象指标，响应可能非常大，只适合连接数与队列数都很少的环境。`/metrics/per-object` 与 `/metrics/detailed` **不受它影响**。

> [!TIP]
> 生产环境的推荐配置是保持 `return_per_object_metrics = false`，让 `/metrics` 走聚合；只有确实需要对象级数据时，才给**特定 Prometheus target** 配 `metrics_path: /metrics/per-object`，而不是全局打开。

### Detailed Endpoint

`/metrics/detailed` 需要显式传参才会返回指标：

| 参数 | 数量 | 语义 |
| --- | --- | --- |
| `family` | 零个或多个 | 指定指标族；**不指定则默认不返回任何指标** |
| `vhost` | 零个或多个 | 只返回指定 vhost 中的队列与 exchange 相关指标 |
| `queue` | **最多一个** | 正则表达式，仅返回名称匹配的队列，可与 `vhost` 组合 |

示例：

```text
GET /metrics/detailed?vhost=vhost-1&vhost=vhost-2&family=queue_coarse_metrics&family=queue_consumer_count
GET /metrics/detailed?family=queue_coarse_metrics&queue=^orders-
GET /metrics/detailed?family=queue_coarse_metrics&vhost=production&queue=^orders-
```

`/metrics/detailed` 使用的指标名前缀是 **`rabbitmq_detailed_`**，而其他端点用 **`rabbitmq_`** —— 所以它可以和 `/metrics` 并存使用，不会因指标名冲突影响依赖其他端点的工具。

只取队列消息量与消费者数时，与「先拉完整 `/metrics/per-object` 再筛」相比效率最高可提升约 **60 倍**。

### Metric Families

常用指标族（可用于 `family` 参数）：

| 类别 | 指标族 |
| --- | --- |
| 节点 | `node_coarse_metrics`、`node_metrics`、`node_persister_metrics` |
| 队列 | `queue_coarse_metrics`、`queue_delivery_metrics`、`queue_consumer_count`、`queue_metrics` |
| Exchange | `exchange_metrics`、`queue_exchange_metrics` |
| 连接与 channel | `connection_coarse_metrics`、`connection_metrics`、`channel_metrics`、`channel_process_metrics` |
| Raft | `ra_metrics`（WAL、快照、checkpoint、选举与提交延迟） |
| 认证 | `auth_attempt_metrics`、`auth_attempt_detailed_metrics` |
| 流 | `stream_consumer_metrics`（每个 stream consumer 的 max offset lag） |

> [!WARNING]
> **`vhost_status`、`exchange_names`、`exchange_bindings` 是 cluster-wide 指标，不是节点级指标。**
> Prometheus 应对**每个节点分别抓取**，集群级指标由 Prometheus 侧聚合计算；但这三个指标**不得再跨节点二次聚合** —— 否则会重复计数。

### Collection Interval

生产环境推荐 **30 秒**采集间隔，合适范围 30–60 秒；Prometheus exporter API 可按 15–30 秒抓取。开发环境需要近实时可用 5 秒，但不应低于 5 秒。

速率类指标的窗口应**至少覆盖 4 个采集周期**，以容忍竞态与抓取失败。

## Management Plugin

```bash
rabbitmq-plugins enable rabbitmq_management
curl -u {username}:{password} {hostname}:15672/api/overview
```

management 插件的短板是写明的：与被监控系统耦合深、节点 RAM 占用更高、**只保存近期数据**（数小时而非数天或数月）、UI 相对基础。

> [!TIP]
> 判断该用哪套：**要长期留存 + 高基数对象级告警 → Prometheus；要看拓扑、导出 definitions、做日常管理操作 → management**。两者不是二选一，生产环境通常是 management 开着做管理、Prometheus 开着做采集。

4.3 的管理 UI 新增了 **Linter**（评估配置、提示反模式）。

管理 API 的认证走的是 management 插件自己的用户体系，与 AMQP 侧的资源权限是两套，详见[安全与访问控制](/docs/CS/MQ/RabbitMQ/Security_and_Access_Control.md)。

## Health Checks

`rabbitmq-diagnostics` 提供分级健康检查。**层级越高，检查越全面、越具侵入性、误报概率越高** —— 高层级不等于「更好」，应按需求选。

| Stage | 检查内容 | 代表命令 |
| --- | --- | --- |
| 1 | Runtime 存活 + CLI 能通过 Erlang cookie 认证连接节点 | `rabbitmq-diagnostics -q ping` |
| 2 | Stage 1 + 节点基础运行信息 | `rabbitmq-diagnostics -q status` |
| 3 | Stage 2 + application 运行状态 + 本地资源告警 | `check_running`、`check_local_alarms` |
| 4 | Stage 3 + 所有 listener 的临时 TCP 连通性 | `listeners`、`check_port_connectivity` |
| 5 | Stage 4 + virtual host 依赖状态 | `check_virtual_hosts` |

Stage 1、2 除升级与维护窗口外误报概率接近 0；Stage 3 在内存接近高水位时明显增加误报；Stage 4 在升级维护期增加；Stage 5 在 CPU 负载很高的系统中可能增加。

常用组合：

```bash
rabbitmq-diagnostics -q check_running && rabbitmq-diagnostics -q check_local_alarms
```

只有两项都成功，整体退出码才为 0。

内存详细分解：

```bash
rabbitmq-diagnostics -q memory_breakdown --unit "MB"
```

### Deprecated Check

```bash
# DO NOT USE
rabbitmq-diagnostics node_health_check
```

这个旧版统一健康检查在现代版本中已是 no-op，并计划移除。它要求所有连接、队列 leader replica 与 channel 都输出指标 —— 在连接或队列数量很大时资源消耗高、易误报，且**不适合作为 readiness probe**（它隐含假设节点已完全启动）。

> [!TIP]
> **Kubernetes readiness probe 的官方建议**：在 AMQP TCP 端口上配 `readinessProbe`，**不配 `livenessProbe`**。避免用假定节点已完成启动并重新加入集群的检查 —— 滚动重启期间存在 peer syncing，CLI 每次 probe 都加入又离开 Erlang distribution，开销与误报都不划算。

## CLI Toolkit

| 工具 | 用途 | 随 server 安装 | 认证方式 |
| --- | --- | --- | --- |
| `rabbitmqctl` | 通用管理：停节点、看状态与有效配置、管 vhost / 用户 / 权限 / policy、列 queue / connection / channel / exchange / consumer、管集群成员 | 是 | Erlang cookie |
| `rabbitmq-diagnostics` | 状态检查、健康检查、故障诊断 | 是 | Erlang cookie |
| `rabbitmq-upgrade` | 升级前 / 中 / 后的操作 | 是 | Erlang cookie |
| `rabbitmq-queues` | 维护复制队列（尤其 quorum queue 副本） | 是 | Erlang cookie |
| `rabbitmq-streams` | 管理 RabbitMQ Streams 的副本 | 是 | Erlang cookie |
| `rabbitmqadmin` | 通过 HTTP API 执行常见管理操作 | **否**（需单独下载的原生二进制） | HTTP Basic Auth |

`rabbitmqadmin` 只提供 Management UI / HTTP API 中常用操作的一个子集，**不是 `rabbitmqctl` 的替代品**；它只需开放 HTTP API 端口即可远程使用。

> [!NOTE]
> 插件可以提供自己的 CLI 命令。插件必须被**显式启用**其命令才会被发现 —— 即使插件作为依赖被隐式启用，只要没写进 enabled plugins file，它的 CLI 命令也不会被发现。

## Resource Thresholds

> [!IMPORTANT]
> **4.3 起没有四档 watermark，只有两个单阈值**：

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `disk_free_limit` | **50 000 000 字节（50 MB）** | 支持绝对值与相对 RAM（`{mem_relative, 2.0}`）；同设则 absolute 优先 |
| `vm_memory_high_watermark` | 示例 0.6 | 相对值 |

已失效的配置：`vm_memory_high_watermark_paging_ratio` 与 `memory_monitor_interval` 都标注 **DEPRECATED，4.0 起不再使用**；`vm_memory_low_watermark` 在 4.3 **根本不存在**。

**文件描述符**：官方不给固定推荐值，规则是**连接数 × 1.5**（如支撑 10 万连接则设 15 万）。提高 OS 上限时**必须同步提高 `ERL_MAX_PORTS`**，检查用：

```bash
rabbitmqctl eval 'erlang:system_info(port_limit).'
```

## Links

- [RabbitMQ（总览）](/docs/CS/MQ/RabbitMQ.md)
- [RabbitMQ 的集群与元数据](/docs/CS/MQ/RabbitMQ/Cluster_and_Metadata.md)
- [RabbitMQ 的插件生态](/docs/CS/MQ/RabbitMQ/Plugins_and_Ecosystem.md)
- [RabbitMQ 的升级到 4.4](/docs/CS/MQ/RabbitMQ/Upgrading_to_4_4.md)

## References

- https://www.rabbitmq.com/docs/monitoring
- https://www.rabbitmq.com/docs/prometheus
- https://www.rabbitmq.com/docs/cli
- https://www.rabbitmq.com/docs/management
- https://www.rabbitmq.com/docs/cluster-formation
