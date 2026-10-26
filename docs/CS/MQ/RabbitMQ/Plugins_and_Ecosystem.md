## Introduction

RabbitMQ 的能力面分两层：**core broker** 与**插件**。core 负责队列类型、路由、DLX、存储与元数据（Khepri），这些是「消息怎么存、怎么到」的问题；插件负责「多一种协议进来、多一套指标出去、多一条链路把消息搬到别的集群」。

本篇只写插件这一层，版本基线 **RabbitMQ 4.4.0**（2026-10-20 发布，社区支持至 2027-07-31；商业支持至 2028-10-31），对照 **4.3.6**（2026-09-16，社区支持至 2027-01-31）。core 侧的队列语义、路由规则、Khepri 集群行为不在此重复，见 [RabbitMQ 主笔记](/docs/CS/MQ/RabbitMQ.md)。

> [!NOTE]
> 本篇提到的插件名分三类出处：**官方 plugins 页**（[rabbitmq.com/docs/plugins](https://www.rabbitmq.com/docs/plugins)）的 tier 1 / Tanzu / 已废弃三张表原文；**4.4.0 release notes** 原文；以及 **v4.4.0 源码树 `deps/` 目录**（用 GitHub contents API 按 tag 列出，57 个子目录）。凡是官方页面没给出的端口、配置键、默认值，本篇都标注了出处或直接写「官方文档未给出」。

## What Plugins Actually Are

官方一句话定义：插件扩展 core broker 的功能，方式是「支持更多协议、系统状态监控、额外的 AMQP 0-9-1 exchange 类型、节点联邦」，而其中相当一部分**就随 core 发行版一起分发**，只是默认不启用。

三条工程事实决定了插件在 RabbitMQ 里的位置：

| 事实 | 含义 |
| :--- | :--- |
| 插件以 `.ez` 归档分发，内含编译后的代码模块与元数据 | 插件不是源码级扩展，是「可插拔的 Erlang application」 |
| 插件在**节点启动时**或**运行时用 CLI 触发**时激活 | 启动即生效靠 `enabled_plugins` 文件，运行时生效靠 `rabbitmq-plugins enable` |
| 内置插件目录随版本变（路径里带版本号），第三方插件目录应另设 | 「装第三方插件」和「升级 RabbitMQ」是两件事，别共用目录 |

官方对内置目录的措辞是 built-in plugin directory "by definition version-independent: its contents will change from release to release"——它随发行版变、路径也可能变，所以官方明确**不建议**往内置目录里塞第三方插件。正确姿势是另建一个不含版本号的目录，并把它加进 `PLUGINS_DIR`（Linux/macOS/BSD 用冒号分隔，Windows PowerShell 用分号）。

```bash
# /etc/rabbitmq/rabbitmq-env.conf：冒号分隔的插件目录列表
PLUGINS_DIR="/usr/lib/rabbitmq/plugins:/usr/lib/rabbitmq/lib/rabbitmq_server-4.4.0/plugins"
```

## Enabling and Disabling

四个命令覆盖了日常全部场景：

```bash
# 启用 / 禁用
rabbitmq-plugins enable <plugin-name>
rabbitmq-plugins disable <plugin-name>

# 列出本地插件与启用状态
rabbitmq-plugins list
rabbitmq-plugins list -s                 # 去掉顶部图例
rabbitmq-plugins list --formatter=json    # 机器可读
```

不带 `-s` 时输出顶部有一段 marker 说明（各符号代表什么）；做巡检脚本时用 `-s` 或 `--formatter=json`，别去解析带图例的输出。

`-n` 可以指定**任意节点**执行，不一定是本机：

```bash
rabbitmq-plugins -n rabbit@node-b enable rabbitmq_prometheus
```

这是集群运维的关键动作：**插件可以在节点 A 上启用、在节点 B 上禁用**，两者不必是同一台机器。

## The enabled_plugins File

离线启用是部署自动化的正解。官方原话：如果节点还没起来就要求先启用插件「not always practical or operator-friendly」，此时用 `--offline`：

```bash
rabbitmq-plugins enable --offline rabbitmq_management rabbitmq_shovel
```

`--offline` 的行为是**不联系任何节点**，直接改写 `enabled_plugins` 文件。这个文件：

- 是一个 **Erlang term 文件**，内容为单个列表
- **结尾的点不能省**——它是语法的一部分
- 依赖**不写进文件**；插件自己在依赖元数据里声明，激活时会被优先启用
- 位于**节点数据目录**或 **`/etc`** 下（与配置文件同处），路径可用环境变量 `RABBITMQ_ENABLED_PLUGINS_FILE` 覆盖
- 部署自动化生成的这个文件，**必须对本机 RabbitMQ 节点可读写**

```erlang
%% enabled_plugins 的内容形态
[rabbitmq_management,rabbitmq_management_agent,rabbitmq_shovel].
```

> [!WARNING]
> **改这个文件必须重启节点才生效。** 这与对运行中节点执行 `rabbitmq-plugins disable` 完全不同——后者不需要重启。反过来，禁用插件的离线做法是「从列表里删掉它 + 重启节点」。

查这个文件与插件目录的真实路径，别猜：

```bash
rabbitmq-plugins directories -s
# => Plugin archives directory: /path/to/rabbitmq/plugins
# => Plugin expansion directory: /path/to/node/node-plugins-expand
# => Enabled plugins file: /path/to/enabled_plugins
```

第一行是第三方插件目录，第二行是随发行版分发、随版本变化的目录，第三行就是 `enabled_plugins` 的位置。

### Two Traps of the Offline Path

**其一，CLI 与 server 用了不同安装。** 二进制包装的 server + 包管理器装的 CLI 属于两套安装，各有各的 `enabled_plugins` 文件，于是启用直接报错：

```text
{:enabled_plugins_mismatch, '/path/to/installation1/etc/rabbitmq/enabled_plugins', '/path/to/installation2/etc/rabbitmq/enabled_plugins'}
```

第一个路径是 `rabbitmq-plugins` 用的，第二个是目标节点用的。`rabbitmq-plugins directories -s` 能看出实际用的是哪一套。

**其二，隐式依赖的插件，其 CLI 命令不会被发现。** 命令发现时 CLI 会查 `enabled_plugins` 文件；如果某插件只是作为依赖被隐式启用（没有出现在文件里），**它提供的 CLI 命令就不会被列出**。想用某个插件附带的 CLI 命令，就得把它显式写进 `enabled_plugins`。

> [!TIP]
> 插件装不上、启不来，官方统计的绝大多数原因是**文件系统权限不足**——插件归档目录、插件展开目录对「跑 node 的那个 OS 用户」可读可写。外加插件目录路径不一致、CLI 与 server 的 enabled plugins 文件不一致、插件未声明对 core 的依赖、插件版本与 core 不兼容。

## Plugin Tiers

### Tier 1: Shipped With the Distribution

用标准发行包安装时，这些插件**不需要另行安装**，但**必须 enable 才能用**。

| 插件 | 定位 | 什么场景该开 |
| :--- | :--- | :--- |
| `rabbitmq_auth_backend_ldap` | 用外部 LDAP 服务器做认证与授权 | 账号已在 AD/OpenLDAP，机器人账号想统一托管 |
| `rabbitmq_auth_backend_oauth2` | OAuth 2.0 协议做认证与授权 | 接入 IdP，走 OIDC discovery |
| `rabbitmq_auth_backend_http` | 用外部 HTTP API 做认证与授权 | 已有自研账号服务 |
| `rabbitmq_auth_mechanism_ssl` | SASL EXTERNAL + TLS(x509) 客户端证书 | 内部服务网格 mTLS，不想发密码 |
| `rabbitmq_consistent_hash_exchange` | 一致性哈希 exchange（`x-consistent-hash`） | 绑定队列要按 routing key 稳定取模 |
| `rabbitmq_federation` | 跨 WAN / 跨管理域伸缩 | 跨机房消费，本地保留一份热数据 |
| `rabbitmq_federation_management` | 在 management API/UI 展示 federation 状态 | 配合 `rabbitmq_management`；异构集群里应装在与管理插件相同的节点上 |
| `rabbitmq_jms_topic_exchange` | 供 RabbitMQ JMS 客户端使用的特殊 exchange 类型 | 客户端是 RabbitMQ JMS client |
| `rabbitmq_management` | HTTP 管理/监控 API + 浏览器 UI | 日常运维与指标采集的默认入口 |
| `rabbitmq_management_agent` | 节点侧统计采集 | **只在部分节点装了 management 时，也必须在所有集群节点上 enable**，否则部分节点的统计不会被采集 |
| `rabbitmq_mqtt` | MQTT 5 与 3.1.1 | IoT 设备接入 |
| `rabbitmq_prometheus` | Prometheus 监控支持 | 已有 Prometheus 栈，要抓 `/metrics` |
| `rabbitmq_sharding` | 分片队列 | 官方提示：**考虑改用 streams 与 partitioned streams**，同一批用例但用 Stream 客户端库效率高得多 |
| `rabbitmq_shovel` | 把一个 broker 的队列 shovel 到另一个 broker 的 exchange | 跨集群、跨产品搬运消息 |
| `rabbitmq_shovel_management` | 在 management API/UI 展示 shovel 状态 | 配合 `rabbitmq_management`；异构集群里装在与管理插件相同的节点上 |
| `rabbitmq_stomp` | STOMP 协议支持 | 遗留 STOMP 客户端 |
| `rabbitmq_tracing` | 给 management 插件加消息追踪，把 firehose 日志写成多种格式 | 排查「消息到底有没有发出去」 |
| `rabbitmq_trust_store` | 客户端 x509 证书信任库 | 内部 CA 签发的客户端证书 |
| `rabbitmq_web_stomp` | STOMP-over-WebSocket 桥，把 `rabbitmq_stomp` 暴露给浏览器 | 浏览器端消费 |
| `rabbitmq_web_mqtt` | MQTT-over-WebSocket 桥，把 `rabbitmq_mqtt` 暴露给浏览器 | 浏览器端消费 |
| `rabbitmq_web_stomp_examples` | 给 `rabbitmq_web_stomp` 附带的 echo 服务与画布协作示例 | 演示用，**不要上生产** |
| `rabbitmq_web_mqtt_examples` | 给 `rabbitmq_web_mqtt` 附带的 echo 服务与画布协作示例 | 演示用，**不要上生产** |

> [!IMPORTANT]
> 这张表是**精选清单，不是发行版里全部的插件**。至少三个反例：官方 plugins 页自己的示例就用 `rabbitmq_peer_discovery_k8s`（enable 示例）和 `rabbitmq_top`（disable 示例）——两者都随发行版分发；`rabbitmq_stream` 更是官方单独开了一页（stream 协议页）说明「The Stream plugin is included in the RabbitMQ distribution」，并给出 `rabbitmq-plugins enable rabbitmq_stream`。**别把「官方 tier 1 表里没有」当成「这个插件不存在」。**

### Beyond the Official Table: What the Source Tree Ships

按 tag `v4.4.0` 列 `deps/` 目录（57 个子目录）能看出发行版实际打包的插件集合，比官方 tier 1 表长。下面这些在 4.4.0 源码树里有对应插件目录，但官方 plugins 页的 tier 1 表未列出：

| 插件目录 | 说明 |
| :--- | :--- |
| `rabbitmq_stream` | stream 协议插件，官方有独立文档页；默认 TCP 端口 5552（官方 TLS 示例用 5551） |
| `rabbitmq_top` | 官方 plugins 页的 disable 示例即此插件 |
| `rabbitmq_peer_discovery_k8s` / `rabbitmq_peer_discovery_consul` / `rabbitmq_peer_discovery_etcd` / `rabbitmq_peer_discovery_aws` | 官方 plugins 页的 enable 示例即 `rabbitmq_peer_discovery_k8s` |
| `rabbitmq_auth_backend_cache` | 认证后端缓存；4.4.0 release notes 有「Auth Backend Cache Plugin」条目，修的是同凭据重连时缓存不命中、给 LDAP 之类后端加压的问题 |
| `rabbitmq_auth_backend_internal_loopback` | 只允许 loopback 连接的内部认证后端；其 README 写明「As of 4.1.1, this plugin is distributed with RabbitMQ」 |
| `rabbitmq_random_exchange` | Makefile 里 PROJECT_DESCRIPTION 为 "RabbitMQ Random Exchange"，源码含 `rabbit_exchange_type_random.erl` |
| `rabbitmq_recent_history_exchange` | PROJECT_DESCRIPTION "RabbitMQ Recent History Exchange"，源码含 `rabbit_exchange_type_recent_history.erl` |
| `rabbitmq_event_exchange` | PROJECT_DESCRIPTION "Event Exchange Type"，源码含 `rabbit_exchange_type_event.erl` 与 `rabbit_event_exchange_decorator.erl` |
| `rabbitmq_federation_prometheus` / `rabbitmq_shovel_prometheus` | Makefile 描述分别是 "Exposes rabbitmq_federation metrics to Prometheus" 与 "Exposes rabbitmq_shovel metrics to Prometheus" |
| `rabbitmq_stream_management` | PROJECT_DESCRIPTION "RabbitMQ Stream Management" |
| `rabbitmq_web_dispatch` | PROJECT_DESCRIPTION "RabbitMQ Web Dispatcher"；其 README 自述是 Cowboy 之上的一层薄封装，让多个应用按 URL path 前缀共用同一批 Cowboy listener（management / web-stomp / web-mqtt 都走它） |

> [!NOTE]
> 上表**只列插件名与源码里能验证的事实**，不给它们编造配置键与默认值——这些插件多数没有独立官方文档页，官方 plugins 页也没给它们的条目。

### Tanzu RabbitMQ Only

以下是商业版（Tanzu RabbitMQ）专属，开源发行版没有：

| 插件 / Erlang application | 定位 |
| :--- | :--- |
| `inet_tcp_compress_dist` | 集群内压缩，显著降低节点间流量 |
| `rabbitmq_distributed_shovel` | `rabbitmq_shovel` 的替代：把 shovel 分布到所有集群节点，shovel 数量多时扩展性与容错更好 |
| `rabbitmq_schema_definition_sync` | Warm Standby Replication 的一部分，用 AMQP 1.0 把 schema 定义从上游主集群持续复制到下游备集群 |
| `rabbitmq_warm_standby` | 跨数据中心 Warm Standby Replication 的统一管理与 API |
| `rabbitmq_web_amqp` | AMQP 1.0 over WebSocket，让浏览器应用用 AMQP 1.0 通信 |
| `rabbitmq_web_amqp_examples` | 浏览器端 AMQP 1.0 over WebSocket 的基础示例 |

### Discontinued

官方明确：以下两个插件**已停止发行，也不再由 core 团队维护**——`rabbitmq_auth_backend_amqp`、`rabbitmq_management_visualiser`。见到老运维手册里还在 enable 这两个，就是过期文档。

### Community Plugins

官方团队为社区贡献的插件提供**精选插件的二进制下载**（community plugins 页面）；更多插件在 GitHub、GitLab、Bitbucket 等处。装第三方插件的坑集中在四处：插件目录不对、CLI 与 server 用的不是同一个插件目录、CLI 与 server 用的不是同一个 enabled plugins 文件、插件没声明对 core 的依赖、插件版本与 core 不兼容。

## The 4.4 Lineup: What Moved Into Core

这一节是本篇最需要小心的部分，因为**官方 release notes 在 4.3.0 与 4.4.0 里对同一件事各说了一遍**。

4.4.0 release notes 原文：

> `x-modulus-hash` exchange routing is now stable: assuming a topology that does not change, messages carrying the same routing key are now routed to the same bound destination.
> Note: the exchange type has been moved from `rabbitmq_sharding` to the core, so it is now available even when said plugin is not enabled.
> GitHub issue: #15849

按源码与 4.3.0 release notes 核对，实际落地时间比这条 notes 更早：

| 核对项 | 结果 |
| :--- | :--- |
| v4.2.0 `deps/rabbit/src/rabbit_exchange_type_modulus_hash.erl` | 不存在；类型由插件侧 `rabbitmq_sharding` 的 `rabbit_sharding_exchange_type_modulus_hash.erl` 提供 |
| v4.3.0 同路径 | **存在**，且 `deps/rabbitmq_sharding/src/` 下已无该 exchange 类型文件 |
| 4.3.0 release notes | 已宣布「moved into the core and reworked to provide stable message routing …including between node restarts」，引用的 PR 编号同为 **#15849** |
| v4.3.0 与 v4.4.0 的 core 实现 | 两份 `rabbit_exchange_type_modulus_hash.erl` **逐字节相同**（diff 无差异） |

所以准确说法是：**`x-modulus-hash` 在 4.3.0 就已移入 core 并重写为稳定路由**，4.4.0 的 release notes 把它重新表述了一遍（同一 PR）。落到运维上：**不启用 `rabbitmq_sharding` 也能用 `x-modulus-hash`**，这一点在 4.3 与 4.4 上都成立。

「稳定」到底改了什么，看源码最清楚。core 版（4.3.0 起）先把候选目标排序再取模：

```erlang
route(#exchange{name = Name}, Msg, _Options) ->
    Destinations = rabbit_router:match_routing_key(Name, ['_']),
    case length(Destinations) of
        0 -> [];
        Len ->
            %% We sort to guarantee stable routing after node restarts.
            DestinationsSorted = lists:sort(Destinations),
            Hash = erlang:phash2(mc:routing_keys(Msg), ?PHASH2_RANGE),
            Destination = lists:nth(Hash rem Len + 1, DestinationsSorted),
            [Destination]
    end.
```

4.2.x 的插件版没有这次排序，直接在未排序的匹配结果上取 `lists:nth(hash_mod(Routes, N), Qs)`。**排序前后差的是「绑定目标的枚举顺序」**——顺序一变，取模结果就变，同一条 routing key 就会落到不同的队列。core 版把顺序固定下来，于是「拓扑不变 ⇒ 同一 routing key ⇒ 同一目标」成立，且跨节点重启也成立。

> [!WARNING]
> 这次移动对**既有部署是行为变更**：如果生产里用的是 4.2.x 的 `rabbitmq_sharding` 插件版 `x-modulus-hash`，升级到 4.3+ 后同一个 routing key 的落点会变（因为排序规则不同）。分片队列的消费者分布会重新洗牌。**升级前先把绑定关系和消费组对应关系记下来**，别等到半夜消息分布变了才发现。

### Other 4.4 Plugin-Relevant Changes

4.4.0 的改动大量落在插件层，release notes 也按插件分了节：

| 归属 | 变化 |
| :--- | :--- |
| **core** | quorum queue 支持延迟消息：`x-opt-delivery-time`（Unix epoch 毫秒）——AMQP 1.0 客户端设为 message annotation，AMQP 0-9-1 客户端设为 `long` header；消息立即路由入队，到点才交付。AMQP 1.0 consumer 还可在 `modified` outcome 的 annotation 里设它来延迟重投 |
| **core** | AMQP 1.0 客户端可请求 container ID 的 sole（独占）所有权，冲突时按客户端请求拒绝新连接或关闭旧连接（AMQP 1.0 Connection Uniqueness 扩展）；新增 `rabbitmqctl sole_connection_status` 与 `rabbitmqctl sole_connection_force_delete` |
| **STOMP 插件** | STOMP 现在是**独立协议**，不再构建在 AMQP 0-9-1 之上（继 AMQP 1.0、MQTT 之后） |
| **MQTT 插件** | 新增 `mqtt.max_connections`；MQTT 5.0 的 `Receive Maximum = 0` 按协议规范被拒；retained message store 新增 per-vhost 限制 `mqtt.retained_message_store.max_messages`（默认 100000）与 `mqtt.retained_message_store.max_size_bytes`（默认 1073741824，即 1 GiB），可改为 `infinity` |
| **STOMP 插件** | 新增 `stomp.max_connections` |
| **Stream 插件** | 新增 `stream.max_connections` 与 `stream.max_super_stream_partitions` |
| **Web MQTT / Web STOMP 插件** | 新增 `web_mqtt.strict_origin_validation` / `web_stomp.strict_origin_validation`；`allow_origins` 新增值 `same_origin`；`web_mqtt.hsts.policy` / `web_stomp.hsts.policy` 可配 HSTS |
| **Management 插件** | 新增 `GET /api/init` 端点（减少 UI 的阻塞请求）；新增 `management.headers.referrer_policy`；支持 HTTP 类协议的多个 listener；修复 HTTP API 不返回 blocked consumer 状态 |
| **OAuth 2 插件** | OIDC discovery 响应改为按 OpenID Connect Discovery 1.0 §4.3 严格校验；OAuth 2.0 scope 支持正则提取 |
| **Consistent Hashing Exchange 插件** | 修复对空数组 header 做哈希时路由失败 |
| **Shovel 插件** | 多个 AMQP 1.0 相关的 shovel 缺陷修复（乱序 confirm 导致重复投递、拒绝/释放时源端不 settle、超过 40 亿次投递后 settle 异常），以及 `src-delete-after` 传超量、`starting` 状态删除后残留状态 |

> [!WARNING]
> **OIDC discovery 校验变严是一次可观测的破坏性变更。** 4.4.0 的 breaking changes 里明写：identity provider 若提供非 HTTPS（`http://`）端点，或其 `issuer` claim 与 discovery 端点不匹配，升级后 discovery 校验会失败。非合规 IdP（比如 Cloud Foundry UAA）必须在升级**前**把 `auth_oauth2.discovery.verify_issuer` 或 `auth_oauth2.discovery.verify_https_endpoints` 设为 `false`。

## Core vs Plugin: Where the Line Sits

判断一个需求「要不要开插件」，先看它在不在 core 里：

| 能力 | 归属 | 备注 |
| :--- | :--- | :--- |
| classic / quorum / stream 三种队列类型 | core | stream **不需要** AMQP 1.0 客户端 |
| quorum queue 延迟消息与延迟投递（4.4 起） | core | `x-opt-delivery-time` |
| AMQP 1.0 connection uniqueness（4.4 起） | core | sole connection |
| `x-modulus-hash` exchange（4.3 起） | core | 不需要启用 `rabbitmq_sharding` |
| `x-local-random` exchange | core | 本节点内随机投递 |
| DLX、at-least-once 死信、delivery limit | core | |
| Khepri 元数据存储与集群成员 | core | 4.3.0 起是唯一元数据存储 |
| Prometheus 指标 | `rabbitmq_prometheus` | **所有节点**都要启用；默认专用端口 15692 |
| HTTP 管理 API 与浏览器 UI | `rabbitmq_management` | 默认 `http://node-hostname:15672/`；可只装在部分节点，UI/API 仍能看全集群 |
| 节点级统计采集 | `rabbitmq_management_agent` | management 只装部分节点时，它**必须装全部节点** |
| MQTT / STOMP 协议入口 | `rabbitmq_mqtt` / `rabbitmq_stomp` | 默认 1883 / 61613 |
| 浏览器直连 | `rabbitmq_web_mqtt` / `rabbitmq_web_stomp` | 默认 15675 / 15674；依赖对应的协议插件 |
| 跨集群搬消息 | `rabbitmq_shovel` / `rabbitmq_federation` | shovel 无条件搬，federation 仅在上游无本地 consumer 时搬 |
| 外部认证后端 | `rabbitmq_auth_backend_ldap` / `_oauth2` / `_http` / `rabbitmq_auth_mechanism_ssl` | |
| 一致性哈希路由 | `rabbitmq_consistent_hash_exchange` | `x-consistent-hash` |
| firehose 追踪（`rabbitmqctl trace_on`） | core | 走 `amq.rabbitmq.trace` topic exchange；状态不持久 |
| 把追踪消息抓下来存成文件 | `rabbitmq_tracing` | 在 core tracer 之上加 GUI，可写 text 或 JSON 文件 |

端口一律以官方各插件文档页为准，官方 plugins 页本身不给端口表。

## Operational Traps

**management 装一半是最经典的事故。** management 插件可以只装在集群的一部分节点上，连上其中任一个都能看到全集群信息——这让人以为「装一个就够了」。但要采集**所有**集群节点的指标，`rabbitmq_management_agent` 必须**在每个节点**上都启用。没启的节点，其指标不会被采集，UI 上表现为「某个节点的队列数、消息数是空的或不更新」。**management 与 management_agent 是两件事，只装前者不装后者，等于装了监控但漏了数据源。**

**federation_management 与 shovel_management 装错节点也会「看起来没生效」。** 这两个插件只在配合 `rabbitmq_management` 时才有意义，官方明确：异构集群里应装在与 `rabbitmq_management` 相同的节点上。装在另一批节点上，UI 里就是看不到状态。

**sharding 插件官方劝退。** 官方 plugins 页对 `rabbitmq_sharding` 的说明里带一条 tip：考虑改用 streams 与 partitioned streams，它们覆盖同一批用例，但用 RabbitMQ Stream 协议客户端库效率高得多。分片队列的语义是「用一个逻辑队列换并行度，牺牲全序」——如果你的消费者本来就要并发，这个取舍在 quorum queue 上也能做。

**firehose 有性能代价。** 官方 firehose 页写得很直白：关闭时对性能无影响，**开启后性能会下降**，因为要额外生成并路由通知消息。而且 firehose 状态**不持久**，节点重启后默认回到关闭。`rabbitmq_tracing` 是在这个 tracer 之上加了 GUI，能把追踪到的消息写成 text 或 JSON 文件——用来定位「消息发没发出去、到没到 consumer」很好用，但别长期开着。

**插件是「装上就多一条路径」。** 每开一个协议入口就多一个攻击面与一套连接管理逻辑：WebSocket 桥（15674/15675）把协议直接暴露给浏览器，默认用户 `guest`/`guest` 只允许从 localhost 连，官方明确建议生产环境另建用户。

> [!TIP]
> 插件审计清单：① 每个启用插件是否在**每个**该启的节点上都启了；② management 与 management_agent 是否都启、是否覆盖全部节点；③ `enabled_plugins` 文件是否与实际运行的节点一致（`rabbitmq-plugins directories -s` 对一下）；④ 有没有 demo/示例插件（`rabbitmq_web_stomp_examples`、`rabbitmq_web_mqtt_examples`、`rabbitmq_web_amqp_examples`）混进了生产；⑤ 第三方插件目录是否与内置目录分离。

## Links

- [RabbitMQ 协议层：AMQP 0-9-1 / AMQP 1.0 / MQTT / STOMP](/docs/CS/MQ/RabbitMQ/Protocol.md)
- [RabbitMQ exchange 与路由](/docs/CS/MQ/RabbitMQ/Exchange_and_Routing.md)
- [RabbitMQ 集群与元数据（Khepri）](/docs/CS/MQ/RabbitMQ/Cluster_and_Metadata.md)
- [RabbitMQ 安全模型与认证后端](/docs/CS/MQ/RabbitMQ/Security_and_Access_Control.md)
- [AMQP 0-9-1 协议结构与工作流（Spring AMQP 侧）](/docs/CS/Framework/Spring/AMQP.md)

## References

- https://www.rabbitmq.com/docs/plugins
- https://www.rabbitmq.com/docs/prometheus
- https://www.rabbitmq.com/docs/management
- https://www.rabbitmq.com/docs/mqtt
- https://www.rabbitmq.com/docs/stomp
- https://www.rabbitmq.com/docs/web-mqtt
- https://www.rabbitmq.com/docs/web-stomp
- https://www.rabbitmq.com/docs/stream
- https://www.rabbitmq.com/docs/firehose
- https://www.rabbitmq.com/community-plugins
- https://www.rabbitmq.com/release-information
- https://github.com/rabbitmq/rabbitmq-server/releases/tag/v4.4.0
- https://github.com/rabbitmq/rabbitmq-server/tree/v4.4.0/deps
- https://github.com/rabbitmq/rabbitmq-server/blob/v4.4.0/deps/rabbit/src/rabbit_exchange_type_modulus_hash.erl
