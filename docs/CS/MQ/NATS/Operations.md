## Introduction

把 NATS 从「跑起来」推到「运维得住」，要解决的是六个问题：**资源要多大**、**配置怎么管**、**运行时上限是多少**、**怎么观测**、**怎么滚动升级**、**怎么硬化**。

这六件事在 NATS 上有共同的特点：几乎所有配置项集中在一个 `.conf` 文件里，server 是**单一二进制 + 单一进程**，集群、JetStream、MQTT、WebSocket 都只是这个进程上的配置项。因此运维面没有「组件间的版本错配」这一类问题，取而代之的是**对默认值的无知** —— 大量行为由默认值决定，不看配置参考就会在生产上撞上 1MB payload 上限、64K 连接上限、2 分钟 lame duck 这些硬边界。

> 版本基线：**nats-server v2.15.1**，发布于 2026-10-09（v2.15.0 于 2026-09 发布，2.14.8 是并行维护分支）。
> 身份与权限模型不在本篇范围，归 Security 分册。

## Sizing and Resources

四个维度，各有各的瓶颈来源。

### CPU

NATS 的 CPU 成本主要花在**协议解析、subject 匹配、路由扇出**三处，而不是磁盘 IO。因此：

- **消息体大小几乎不影响 CPU**（只是搬运字节），**订阅数量与扇出宽度才影响**。一个 subject 被 1000 个订阅者匹配，比 1000 个 subject 各 1 个订阅者更省 CPU，因为后者的匹配表更大。
- **JetStream 的 CPU 成本远高于 Core NATS**：写入要落盘、要做 Raft 复制、要做 ack 跟踪。
- CPU 打满时的表现是**连接延迟上升**而不是丢消息 —— server 不会因为算不过来而偷偷丢数据。

### Memory

Core NATS 的常驻内存很小（官方口径约 15MB 量级），内存几乎全被**待投递消息**和**订阅状态**占用：

- **pending buffer**：server 为某个订阅者缓存、但客户端还没取走的消息，这是内存消耗的主要来源，也是 `max_pending` 存在的理由。
- **慢消费者**是内存爆炸的头号原因。默认 `no_fast_producer_stall` 为 `false`，意味着 server **会阻塞快生产者**而不是把消息丢给慢消费者 —— 数据安全，但快生产者的延迟会被拖垮。

### Disk

只有 JetStream 用磁盘，存储根目录由 `store_dir` 指定，每个 stream 是一个目录：

```conf
jetstream {
  store_dir: "/var/lib/nats/jetstream"
}
```

| 部署形态 | 磁盘放大系数 | 说明 |
| -------- | ------------ | ---- |
| Core NATS | 0 | 完全不落盘（语义边界见 [Core NATS 路由层](/docs/CS/MQ/NATS/Core_NATS.md)） |
| JetStream `R=1` | 1x | 单副本，无 HA |
| JetStream `R=3` | 3x | 三个副本各占一份完整数据 |

**R3 的真实代价是 3 倍磁盘 + 3 倍写入带宽 + 3 倍 fsync 压力**，而且三副本必须放在**不同节点**上，否则拿不到节点级容错，只拿到了进程级容错。规划磁盘时按 3x 再乘以保留策略（limits / interest 的消息保留量）来算，不要按逻辑数据量算。

### File Descriptors

默认 `max_connections` 是 **64K**，意味着单进程可能持有 6 万多个客户端连接，每个连接至少一个 socket fd，此外还有 subject 订阅状态、JetStream 文件等。因此 fd 上限必须显著高于 64K（systemd 下用 `LimitNOFILE` 固化，见 [Hardening](#hardening)）。fd 上限不足时的表现是 server **启动即报错退出**，而不是运行中才失败 —— 这是少数「配置错误会立刻暴露」的场景。

## Configuration Management

### Include Blocks

大规模部署不要把配置写成一个巨型文件。NATS 支持 `include`，可以按 account、按 region 分块：

```
# nats-server.conf
include "accounts/acct_orders.conf"
include "accounts/acct_billing.conf"
include "regions/us-east.conf"
include "regions/eu-west.conf"
```

分块的收益是**权限与审阅粒度**：每个 account 的配置单独成文件，谁改哪个租户的权限一目了然；不同 region 的差异（TLS 证书路径、JetStream 副本落点）互不干扰。

### Hot Reload with SIGHUP

配置变更用 `SIGHUP` 热加载，**零停机，客户端不需要重连**：

```bash
kill -HUP "$(pidof nats-server)"    # 发送 SIGHUP 触发热加载
systemctl reload nats-server         # 用 systemd 管理时的等价写法
```

热加载是 NATS 运维面最实用的一个能力：改权限、改 JetStream limits 都不需要断流，因此可以放心地把「改配置」做成低风险的日常操作。

### Reloadable vs Not

配置参考表里每个选项都标注了是否 Reloadable。**大多数项可 reload，但有几项标了 No，改了必须重启**：

| 配置项 | 可否热加载 | 说明 |
| ------ | ---------- | ---- |
| `max_pending` / `max_connections` / `write_timeout` / `max_subscriptions` | **No** | 改了仍按旧值运行，必须安排重启窗口 |
| 权限 / user / account 列表 | Yes | 新连接按新规则，老连接保持原权限直到重连 |
| JetStream 配置 | Yes | 大多数 limits 可在线调整 |
| TLS 证书 | Yes | 换证书无需重启 |

`max_subscriptions` 尤其值得注意：默认 `0` 表示不限订阅数，把它从 0 改成有限值是一次**不可热加载**的变更。而默认值是「不限」，很多团队直到出问题才发现这个上限原本不存在。

> [!TIP]
> 权限变更热加载后，**已连接的客户端仍保持原有权限**，新规则对已有连接的约束要到该连接重建才生效。紧急收回权限时，光 reload 不够。

## Server Configuration Defaults

这是本篇最有价值的部分 —— 下面每一个默认值都会在生产上成为硬边界，且**默认值与直觉经常不一致**。

### Core Limits

| 配置项 | 默认值 | 说明 |
| ------ | ------ | ---- |
| `port` | `4222` | 客户端监听端口 |
| `max_payload` | **1MB** | 单条消息上限。可调到 64MB，但官方**不建议超过 8MB**，且**必须 ≤ `max_pending`** |
| `max_pending` | **64MB** | 单客户端 pending buffer 上限 |
| `max_connections` | **64K** | 最大客户端连接数 |
| `max_control_line` | **4KB** | 控制协议行长度上限 |
| `max_subscriptions` | **0** | 0 表示不限订阅数 |
| `max_closed_clients` | `10000` | `/connz` 保留的已关闭连接数 |
| `max_traced_msg_len` | `0` | 不限制追踪 payload 长度 |

`max_payload` 的 1MB 默认值是最常被撞的一条。它和 `max_pending` 的关系是**约束关系而非独立关系** —— 把 `max_payload` 调到 64MB 而 `max_pending` 还是 64MB，配置本身就是无效的，官方文档明确要求 `max_payload` 必须不超过 `max_pending`。

### Timeouts and Liveness

| 配置项 | 默认值 | 说明 |
| ------ | ------ | ---- |
| `ping_interval` | `2m` | server 主动 ping 客户端的间隔 |
| `ping_max` | `2` | 连续未回应几次 ping 后断开客户端 |
| `write_deadline` | `10s` | 单次写操作的 deadline |
| `write_timeout` | `default` | 写超时策略的取值 |
| `connect_error_reports` | `3600` | 连接错误上报频率（秒） |
| `reconnect_error_reports` | `1` | 重连错误上报频率（秒） |

`ping_interval` + `ping_max` 合起来定义了「多久判定客户端已死」：**默认约 4 分钟**（2 分钟一次 ping，连续 2 次不回应才断开）。这与 TCP keepalive 是两套独立的机制，做连接数规划时不要把它们混为一谈。

### Feature Toggles and Metadata

| 配置项 | 默认值 | 说明 |
| ------ | ------ | ---- |
| `no_fast_producer_stall` | **false** | 默认**会阻塞快生产者**，而不是把消息丢给慢消费者 |
| `no_header_support` | 未设置（默认不关闭） | 置为启用则**关闭消息头支持** |
| `disable_sublist_cache` | 未设置（默认不关闭） | 置为启用则**关闭订阅缓存** |
| `feature_flags` | 空 | 切换尚未默认开启的特性 |
| `proxy_protocol` | `false` | 是否接受 PROXY protocol 头 |
| `ocsp` | `true` | 证书撤销检查（OCSP） |
| `lame_duck_duration` | **2m** | lame duck 排空时长，**最少 30s** |
| `lame_duck_grace_period` | **10s** | 进入 lame duck 后到真正关闭客户端连接之间的等待 |
| `server_metadata` | 可加任意 kv | 附加到 `/varz` 的自定义元信息 |

`no_fast_producer_stall` 的默认值是 NATS **at-most-once 语义的直接体现**：宁可阻塞发送方，也不丢消息。代价是**一个慢消费者能拖慢整条链路上的快生产者**。如果业务上更接受「丢给慢消费者」，把这个开关打开 —— 但要清楚这等于主动放弃了投递保证。

`server_metadata` 值得利用：把环境名、集群角色、变更批次号写进去，`/varz` 就成了自描述的节点卡片，排障时不用再翻 CMDB。

## Monitoring

### Monitoring Endpoint

server 有一个**独立的 HTTP 监控接口**，默认端口 **8222**，与客户端端口完全分开：

```
http: 8222              # 或 http_port: 8222
https_port: 8222        # 走 HTTPS
http_base_path: "/"     # 基路径
```

各端点覆盖了不同层面的运行状态：

| 端点 | 观测内容 |
| ---- | -------- |
| `/varz` | server 基本信息，含 `max_payload`、`max_connections`、`max_subscriptions` 等**运行时上限**，以及 `server_tags` |
| `/connz` | 客户端连接列表，含已关闭连接（保留 `max_closed_clients` 条） |
| `/routez` | cluster route 状态 |
| `/subsz` | 订阅列表与 interest 统计 |
| `/leafz` | leafnode 连接；**v2.15.1 起会报告该连接是否使用 WebSockets** |
| `/gatewayz` | gateway 状态 |
| `/accountz` | 账号维度统计；**v2.15.1 修复了 per-account route 的入站消息/字节被重复计数** |
| `/jsz` | JetStream 状态 |
| `/healthz` | 健康检查 |

`/varz` 会把**运行时生效的上限值**（而不是配置里的字面值）报出来，因此它是「配置到底生效没有」的第一手证据。`/subsz` 的 interest 统计用来发现「有发布者没订阅者」这类静默丢消息的现场。

### CLI

`nats` CLI 自带监控子命令，不必自己写 HTTP 客户端：

```bash
nats server report                       # 拉取一份完整运行报告
nats sub "orders.>" --count 10           # 查看某个 subject 的订阅与流量
nats server ping server-1 server-2       # 观察集群拓扑
```

### Alerts

值得设告警的几条：

| 指标 | 来源 | 典型阈值 |
| ---- | ---- | -------- |
| 连接数逼近上限 | `/varz` 的 `max_connections` vs `/connz` 实际连接数 | 达到上限 70% |
| 订阅数逼近上限 | `/varz` 的 `max_subscriptions` | 视配置，默认为不限 |
| pending 积压 | `/connz` 的各连接 pending 字节 | 持续增长不回落 |
| JetStream 副本不齐 | `/jsz` | 任一 stream 的 replica 少于预期 |

> [!NOTE]
> `/accountz` 在 v2.15.1 之前存在 per-account route 入站消息/字节**重复计数**的问题 —— 用它做流量同比环比时，跨 2.15.0 边界的数据不可比。
## Lame Duck and Rolling Upgrades

### The Mechanism

向 server 发送 **SIGUSR2**，它就进入 **lame duck mode**：停止接受新连接、优雅排空已有连接，然后退出。目的是在滚动升级时不丢流。

```bash
kill -SIGUSR2 "$(pidof nats-server)"    # 让 server 进入 lame duck，优雅退出
```

排空节奏由 `lame_duck_duration`（默认 2m，最少 30s）与 `lame_duck_grace_period`（默认 10s）两个参数决定，取值见 [Feature Toggles and Metadata](#feature-toggles-and-metadata)。

### State Flow

```dot
digraph NATS_Lame_Duck {
    rankdir=LR;
    node [shape=box, style=rounded];

    Running  [label="Running\n正常服务\n接受新连接"];
    Ducking  [label="Lame Duck\n停止接受新连接\n排空已有连接"];
    Grace    [label="Grace Period\n等待 10s\n保留连接余量"];
    Draining [label="Draining\n已有连接排空"];
    Exited   [label="Exited\n进程退出"];

    Newer [label="New Version\n新版本 server 加入集群"];
    Clients [label="Clients\n客户端重连到新成员"];

    Running -> Ducking [label="SIGUSR2"];
    Ducking -> Grace [label="lame_duck_duration 计时"];
    Grace -> Draining [label="grace 到期"];
    Draining -> Exited [label="连接清空 / duration 到期"];
    Exited -> Newer [label="升级器拉起新版本"];
    Newer -> Clients [label="客户端自动重连"];
}
```

### Rolling Upgrade Order

一次安全的滚动升级的时序是：**逐个**把旧版本成员置为 lame duck（`SIGUSR2`），等待其排空退出；退出后拉起新版本；客户端**自动重连**到仍在集群中的成员，因此只要**同时在线的成员数 ≥ 集群法定规模**，业务无感；逐台重复直到全部升级完成。

关键约束是**不要同时对多个成员发 SIGUSR2**。集群的路由与 JetStream 的 Raft quorum 都依赖存活成员，同时退出会导致路由重建甚至 quorum 短暂丢失。

## Upgrading to 2.15

### Recommended Starting Point

官方强烈建议**至少从 v2.14.7 升到 2.15.x**。原因不是 2.15 多了什么功能，而是 **2.15 重写了 metalayer 的期望状态模型** —— 这是一层内部机制改造，直接后果是**混版本期间行为不确定**。从更早的版本（例如 2.9、2.10）直接跳到 2.15.x，等于同时跨过了中间多个版本的模型变更，官方没有承诺这种跨度下的一致性。

### Mixed-version Constraints

混版本运行期间的操作禁区：

| 操作 | 混版本期间 | 原因 |
| ---- | ---------- | ---- |
| 创建 / 删除 stream、consumer | **可以照常** | — |
| stream / consumer **scale**（改副本数） | **避免触发** | 会 stall |
| stream / consumer **move**（迁移落点） | **避免触发** | 会 stall |

也就是说：**读和写是安全的，改拓扑是危险的**。滚动升级期间发现副本数配错了不要在线改 —— 先全部升到 2.15.x，再做 scale / move。

### js_raft_delete_range

`js_raft_delete_range` 是一个 feature flag，属于 2.15 重写的 metalayer 期望状态模型的一部分。它的启用与否直接影响 **Raft 层区间删除**的行为，属于需要在上线前确认默认取值的那一类 flag。`feature_flags` 配置项就是切换这类尚未默认开启的特性的入口。

> [!WARNING]
> 升级前把目标版本的 feature flag 列表拉出来逐条对照，不要假设「上一版的默认还是这一版的默认」。这是 2.15 升级最容易踩的坑。

### js_ack_fc_v2 in 2.16

**`js_ack_fc_v2` 在 2.15 保持 2.14 的默认（v1 格式），2.16 才切到 v2。** 这意味着：

- 升到 **2.15.x 是安全的**，ack 与 flow control 的 subject 格式不变。
- 但如果**账号 import/export 或 subject 权限里含有 `$JS.ACK.<stream>.>` / `$JS.FC.<stream>.>`**（或者更细粒度的变体），那么**在升 2.16 之前必须先改** —— v2 格式与 v1 不兼容，权限规则与 import/export 映射都要改成 v2 的写法，否则升级后 ack 通道直接失效。

这条是「今天升 2.15 没有问题，但半年后升 2.16 会炸」的典型。排查动作是全量 grep 配置与代码里的 `$JS.ACK.` / `$JS.FC.` 字面量：

```bash
grep -rn '\$JS\.\(ACK\|FC\)\.' /etc/nats/ ./config/ 2>/dev/null
```

### JetStream Consumer Limit

`streams` 的 `max_consumers` **默认 1000**，可在 server 级调整：

```
jetstream {
  limits {
    default_max_consumers: 1000
  }
}
```

设成 `-1` 恢复为不限。默认值 1000 意味着「一个 stream 上挂超过 1000 个 consumer」在默认配置下会失败 —— 这个上限经常在接入大量临时 consumer 时才被发现。

### 2.15.1 Fixes

2.15.1 是补丁版本，值得直接上。代表性的修复：

| 修复 | 影响面 |
| ---- | ------ |
| TLS certificate pin 在配置 reload 后校验的是**正确的 pin** | 证书固定 + 热加载的场景 |
| leafnode 连接进 auth callout 时 **TLS 状态可用** | leafnode + auth callout 组合 |
| remote proxy 支持 `https://` proxy URL | 走 HTTPS 代理出网 |
| legacy `$GR.` reply 前缀在 client 入口保留 | 用到该前缀的旧客户端 |
| MQTT packet length **提早按 `max_payload` 校验** | MQTT 接入面 |

## Kubernetes Deployment

### Helm Chart

官方 Helm chart 装 NATS。集群模式用 `cluster` 块声明 route，JetStream 用 `jetstream` 块开启，账号用 `accounts` 块声明：

```yaml
# values.yaml 的核心片段
config:
  cluster:
    name: nats
    port: 6222
  jetstream:
    enabled: true
    storeDir: /data/jetstream
  accounts:
    orders:
      users:
        - user: orders-app
          password: orders-secret
```

### NACK CRDs

**NACK**（NATS Application Controller）让 stream / consumer 变成 K8s 资源，用 CRD 声明，控制器负责把期望状态落到集群：

```yaml
apiVersion: "k8s.nats.io/v1alpha1"
kind: Stream
metadata:
  name: orders
spec:
  subjects: ["orders.>"]
  retention: Limits
  storage: File
  replicas: 3
---
apiVersion: "k8s.nats.io/v1alpha1"
kind: Consumer
metadata:
  name: orders-billing
spec:
  stream: orders
  durable: billing
  ack_policy: explicit
```

**用 CRD 而不是 `nats` CLI 去建 stream/consumer**，收益是：期望状态落在 K8s 里（可以 `kubectl apply`、可以 `git diff`、可以回滚），而不是变成集群里的手工状态。CLI 建出来的东西在控制器眼里是「漂移」，随时可能被覆盖。

### StatefulSet

JetStream 需要稳定的存储与稳定的网络标识，因此用的是 **StatefulSet 三副本**（配合 Raft 的 `R=3`）：

| 要素 | 三副本方案的原因 |
| ---- | -------------- |
| StatefulSet 而非 Deployment | 每副本需要稳定 PVC（`store_dir` 落在本地卷） |
| 副本数 3 | Raft quorum 需要多数派存活才能提交写入 |
| PodDisruptionBudget | 滚动更新时保证不少于 2 个 Pod 存活 |
| 反亲和 | 三副本必须落在不同节点，否则拿不到节点级容错 |

`R=3` 配三副本是有意义的组合：**同时容忍一个节点宕机和一个 Pod 被驱逐**。把三个副本调度到同一台机器上，等于花了 3 倍存储却只拿到 1 倍可用性。

## Hardening

### TLS and Monitoring Port Isolation

**主端口、leafnode、gateway、cluster route、MQTT、WebSocket 各自有独立的 TLS 段落**，要逐段开启，不要只保护主端口。`ocsp` 默认已开，负责证书撤销检查。

**监控端口默认不带认证**，而它暴露的是连接清单、订阅清单、账号统计，等同于一张完整的拓扑图。因此不要把 8222 暴露到公网或不受信网段，限制 `http` 只监听本地或管理网段：

```
http: "127.0.0.1:8222"
```

需要远程采集时，用 sidecar 或本机 agent 拉取，不要直接把 8222 暴露出去。

### systemd Unit

systemd 负责进程守护、重启与资源限制：

```ini
# /etc/systemd/system/nats.service
[Unit]
Description=NATS Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=nats
Group=nats
ExecStart=/usr/local/bin/nats-server -c /etc/nats/nats-server.conf
ExecReload=/bin/kill -HUP $MAINPID
KillSignal=SIGTERM
LimitNOFILE=65536
Restart=on-failure
RestartSec=5s
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true

[Install]
WantedBy=multi-user.target
```

几个要点：

- **`ExecReload` 用 SIGHUP** —— `systemctl reload nats-server` 走热加载，不重启进程。
- **`KillSignal=SIGTERM`** 是正常退出信号，与 lame duck 的 **SIGUSR2** 是两回事：`systemctl stop` 走 SIGTERM，不是排空。
- **`LimitNOFILE`** 必须高于 `max_connections`（默认 64K）留出余量，否则 fd 耗尽时 server 无法接受连接。
- **`ProtectSystem=strict`** 之类沙箱选项生效的前提是 **`store_dir` 落在允许写的路径上**，配置 JetStream 时要同步放开。

```bash
systemctl daemon-reload && systemctl enable --now nats-server
systemctl reload nats-server          # 热加载配置
```

## Pitfalls

- **不知道 `max_payload` 默认只有 1MB**：超过就是断连，且错误信息不直观。调大它时必须同步确认 `max_pending` —— 官方要求 `max_payload` ≤ `max_pending`，把 payload 调到 64MB 而 `max_pending` 还是 64MB 是无效配置。
- **`max_subscriptions` 默认 0（不限）**：改成有限值是不可热加载的项，需要重启窗口。`max_connections`、`max_pending`、`write_timeout` 同理。
- **以为热加载会立刻收回权限**：reload 后**已有连接保持原权限**，紧急收回权限需要主动断开连接。
- **同时对多个成员发 SIGUSR2**：会导致路由重建、quorum 短暂丢失。必须逐台滚动。
- **忘了 `lame_duck_duration` 最少 30s**：排空窗口太短，长连接上的流量会被截断。
- **混版本期间做 scale / move**：会 stall。创建和删除可以照常。
- **升 2.16 前没改 `$JS.ACK.` / `$JS.FC.` 权限**：v2 格式不兼容，ack 通道会失效。升 2.15 本身是安全的。
- **`default_max_consumers` 默认 1000**：stream 上挂超过 1000 个 consumer 会失败，需要显式调整。
- **8222 监控口直接暴露**：无认证的拓扑泄露。
- **JetStream 三副本调度到同一节点**：3 倍存储只换来 1 倍可用性。
- **用 `nats` CLI 手工建 stream**：会与 NACK 的期望状态冲突，控制器随时覆盖；声明式资源一律走 CRD。**K8s 上用 Deployment 而不是 StatefulSet** 同样有坑：PVC 无法稳定绑定，`store_dir` 的数据生命周期失控。

## Links

- [NATS 总纲](/docs/CS/MQ/NATS.md)
- [Security](/docs/CS/MQ/NATS/Security.md)
- [Clustering](/docs/CS/MQ/NATS/Clustering.md)
- [Topologies](/docs/CS/MQ/NATS/Topologies.md)
- [MQ 总纲](/docs/CS/MQ/MQ.md)
- [Helm](/docs/CS/Container/k8s/Helm.md)

## References

1. [NATS 官方文档 - Configuration](https://docs.nats.io/running-a-nats-service/configuration/configuration)
2. [NATS 官方文档 - Lame Duck Mode](https://docs.nats.io/running-a-nats-service/configuration/lame_duck_mode)
3. [NATS 官方文档 - Deployment](https://docs.nats.io/learn/deployment/)
4. [NATS 官方文档 - Monitoring](https://docs.nats.io/learn/monitoring)
5. [NATS 官方文档 - Upgrade to 2.15](https://docs.nats.io/release-notes/upgrade-to-2.15)
6. [nats-io/nats-server - Releases](https://github.com/nats-io/nats-server/releases)
