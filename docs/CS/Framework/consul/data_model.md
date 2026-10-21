## Introduction

Consul 的状态由"强一致 KV"和"服务目录（catalog）"两套存储组成，外加会话（session）机制把它们串起来做分布式锁/信号量。本篇讲清 catalog 的内部结构、agent 本地注册与 server 目录的**分离**、反熵（anti-entropy）如何对账，以及 session 的语义。KV 命令行与 API 见 [KV](/docs/CS/Framework/consul/kv.md)，注册与发现流程见 [Discovery](/docs/CS/Framework/consul/discovery.md)，架构背景见 [Architecture](/docs/CS/Framework/consul/architecture.md)。

> [!NOTE]
> 版本事实：catalog / session 语义自 1.x 起稳定，2.0 无破坏性变化；下文以 1.17+ / 2.0 为准。

## Catalog: Node / Service / Check

catalog 是 server 维护的全局注册表，由三类对象构成，关系为 **node ⊃ service ⊃ check**：

- **Node（节点）**：一个被 Consul 认知的物理/虚拟主机，含 `NodeID`、地址、元数据（tagged addresses）。节点由 agent 注册产生。
- **Service（服务）**：挂在某个 node 下的服务实例，含服务名、监听端口、tag、健康检查引用。同一个服务名可在多 node 上有多个实例。
- **Check（健康检查）**：挂在某 node 或某 service 下，类型覆盖 `script` / `http` / `tcp` / `grpc` / `ttl`。检查失败的服务实例会从 DNS / 健康查询中被剔除。

catalog 与"本地 agent 注册"**分离**：服务由 agent 上报后 server 确认进 catalog；**单个 agent 挂了不影响 catalog 中已由 server 确认的服务**——这与 etcd 那种"进程退出 key 即删"的 lease 模型截然不同（etcd 对比见 [etcd read](/docs/CS/Framework/etcd/read.md)）。

## Agent Registration vs Server Catalog

```dot
digraph catalog_sync {
  rankdir=LR;
  node [shape=box, style="rounded,filled", fontname="Helvetica"];
  edge [color="#555", fontsize=10];

  local [label="Agent 本地注册表\nservices/checks 配置", fillcolor="#eef3fb"];
  ae [label="反熵\n(anti-entropy)", fillcolor="#fdeccb"];
  cat [label="Server Catalog\n(经 Raft 持久化)", fillcolor="#d6ead0"];

  local -> ae [label="周期同步"];
  ae -> cat [label="对账/上报"];
  cat -> ae [label="状态反馈"];
}
```

- agent 启动时从配置文件 / API 载入本地要注册的服务与检查，存于**本地注册表**。
- **反熵（anti-entropy）**：client agent 周期性把本地注册表与 server catalog 对账——本地有而 catalog 缺的，上报注册；catalog 有而本地已删的，反注册；不一致的，修正。因此即使 agent 短暂失联，catalog 仍保留最后已知状态，直到健康检查超时把它标记为 critical 再剔除。
- 反熵与 gossip 解耦：成员存活由 Serf 管，服务/检查状态由反熵 + 健康检查管（见 [Serf](/docs/CS/Framework/consul/serf.md)）。

## Sessions

session 是 KV 之上的**租约/锁**机制（类似 etcd 的 lease，但语义更偏"锁"），把若干 key 绑定到一个 session 上：

| 字段 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `LockDelay` | **15s** | 锁释放后的一段"保护期"，防止脑裂时旧持有者立刻重新加锁（默认 15s，可调） |
| `TTL` | 0（禁用） | session 存活上限；`TTL` 内未续约则 session 失效 |
| `Behavior` | `release` | session 失效时 key 的处置：`release`（释放锁/信号量，key 保留）或 `delete`（直接删除 key） |

基于 session 可实现：

- **分布式锁**：以 `acquire` 语义把 key 绑到 session；持有者宕机 / TTL 过期 → session 失效 → 锁按 `Behavior` 释放（默认 `release`），其他竞争者 `acquire` 成功。`LockDelay` 避免释放瞬间旧主重入。
- **分布式信号量 / leader 选举**：多个竞争者抢同一把"锁"，抢到的即 leader；leader 用 `TTL` 心跳保活，掉线即让位。
- **临时键（ephemeral key）**：`Behavior=delete` 的 session 绑定的 key，session 失效即删除——类似 etcd 的 lease 临时键。

> [!TIP]
> session 的 `TTL` 与 KV 的"租约"容易混淆：Consul 没有 etcd 那种独立的、可脱离 key 存在的 lease 对象；session 就是 KV 锁/临时键的载体。需要"key 随进程生死"用 `Behavior=delete` 的 session 即可。

## KV vs Catalog Boundary

| 维度 | KV | Catalog |
| :--- | :--- | :--- |
| 模型 | 扁平 key-value，单值 ≤ 512KB | 结构化 node/service/check 关系表 |
| 版本历史 | 无（仅 `ModifyIndex` 当前版本） | 无 |
| 典型用途 | 配置、锁、信号量、feature flag | 服务注册与发现、健康状态 |
| 绑定 session | 支持（锁/临时键） | 不直接支持 |
| 读一致性 | 默认 Raft 一致 | 默认本地缓存 stale，可 `?consistent` |

二者都跑在 Raft 之上、强一致，但 catalog 是为"服务拓扑"量身的结构化视图，KV 是通用键值；不要把"服务注册"塞进 KV——catalog 自带健康过滤与 DNS 映射，KV 没有。

## Links

- [Consul（枢纽）](/docs/CS/Framework/consul/Consul.md)
- [KV（存储）](/docs/CS/Framework/consul/kv.md)
- [Discovery（服务发现）](/docs/CS/Framework/consul/discovery.md)
- [Architecture（架构深潜）](/docs/CS/Framework/consul/architecture.md)
- [Serf（成员发现）](/docs/CS/Framework/consul/serf.md)
- [Troubleshooting（故障排查）](/docs/CS/Framework/consul/troubleshooting.md)
- [etcd read（线性/串行读）](/docs/CS/Framework/etcd/read.md)

## References

1. [Consul Catalog](https://developer.hashicorp.com/consul/docs/architecture/consul-architecture-catalog)
2. [Consul Sessions](https://developer.hashicorp.com/consul/api-docs/session)
3. [Consul Anti-entropy](https://developer.hashicorp.com/consul/docs/architecture/anti-entropy)
4. [Consul KV](https://developer.hashicorp.com/consul/docs/commands/kv)
