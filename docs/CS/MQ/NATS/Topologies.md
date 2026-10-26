## Introduction

NATS 的部署形态可以排成一条演进链：**单节点 → 集群 → 超级集群 → leaf 边缘**。四者不是四个"可选方案"，而是同一套协议在规模与距离上的四次扩展，每一级只多引入一个概念。

选型时真正起决定作用的不是"要不要多节点"，而是三个维度：

| 维度 | 问的问题 |
| :--- | :--- |
| **谁拨号** | 谁是主动向外拨号的一方？route 与 gateway 都由本端主动发起，leaf 更是只有出向能力 |
| **连的是谁** | 连的是**单个 server**（server-to-server）还是**整个集群**（cluster-to-cluster）？ |
| **跨链路要不要身份** | 跨链路是否需要 domain / account 隔离，才能共享同一份 subject 空间？ |

一个直观的判断法：**同机房内的多台机器用 route 组成 cluster；跨机房用 gateway 把两个 cluster 连成 supercluster；车间 / 边缘机房用 leaf 挂回中心 hub。** 三条链路的语义、故障模型、运维手段完全不同，不能互相替代。

本篇讲**部署形态**本身：每种形态怎么配、链路怎么建、哪些方向不能搞反。集群内部的 Raft 复制与 quorum 语义属于另一篇 [Clustering](/docs/CS/MQ/NATS/Clustering.md?id=raft-groups-and-leaders)；stream / consumer 的存储与 ACK 语义也不在这里展开。

## The Four Shapes

```dot
digraph NATS_Topologies {
    rankdir=TB;
    node [shape=box, style=rounded];

    subgraph cluster_single {
        label="Single Node";
        SN [label="nats-server\n4222"];
    }

    subgraph cluster_east {
        label="Cluster (east)";
        E1 [label="n1-east\n4222 / 6222"];
        E2 [label="n2-east\n4222 / 6222"];
        E3 [label="n3-east\n4222 / 6222"];
        E1 -> E2 [label="route"];
        E2 -> E3 [label="route"];
        E1 -> E3 [label="route"];
    }

    subgraph cluster_west {
        label="Cluster (west)";
        W1 [label="n1-west\n4222 / 6222"];
        W2 [label="n2-west\n4222 / 6222"];
        W1 -> W2 [label="route"];
    }

    subgraph cluster_edge {
        label="Edge (leaf)";
        F1 [label="factory-1\nleaf node"];
    }

    SN -> E1 [style=dashed, label="scale out"];
    E1 -> W1 [label="gateway 7222\ncluster-to-cluster"];
    F1 -> E1 [label="leaf 7422\nserver-to-server"];
}
```

四种形态的对照：

| 形态 | 链路 | 拨号方 | 典型场景 |
| :--- | :--- | :--- | :--- |
| 单节点 | 无 | — | 开发、单机 agent、边缘单点 |
| 集群 | route 6222 | 两端互拨 | 同机房 / 同可用区的多节点高可用 |
| 超级集群 | gateway 7222 | 各集群互拨 | 跨地域 / 跨云的多集群 |
| leaf 边缘 | leafnode 7422 | **只有边缘侧** | 工厂、车间、弱网分支接入中心 hub |

注意最后一行：**单节点并不比集群弱在"功能"，只是弱在"容错"**。单节点的 Core NATS 与集群里的 Core NATS 语义完全一致（语义边界见 [Core NATS 路由层](/docs/CS/MQ/NATS/Core_NATS.md)）；区别只在某台机器挂掉时，你有多少冗余。

集群里 server 之间没有中心协调者，彼此是**对等**的：没有哪台是其它 server 依赖的单点。消息经 route 到达某台 server 后，交给本机 client 就结束，**不再往下转发**——因为一跳总能到达任何人。

一个容易忽略的连带效应：**client 端也能自动发现集群其余成员**。server 在连接时通过 INFO 消息把其它 server 的 client URL 一并告知 client。于是客户端配置里只写一个地址也能 failover：目标 server 挂掉时，客户端从那条 INFO 里拿到备选地址重连——**集群买到的正是"一台 server 挂掉是一次重连，不是一次中断"**。

有一个开关能关掉这件事：`no_advertise: true` 会让 server 不再广播 peer，客户端就只能用你手写的那几个 URL。默认是关掉的（也就是默认会广播）。

### Server Count

集群的 **server 台数该取奇数**——这条只在有复制时才有意义，但代价是实打实的：

| 台数 | 多数派 | 可容忍故障数 |
| :--- | :--- | :--- |
| 2 | 2 | 0 |
| 3 | 2 | 1 |
| 4 | 3 | 1 |

**4 台与 3 台的容错能力相同**，多出来的那台只增加成本，不增加可用性；2 台则一台挂掉就失去多数派，等于没有 HA。纯路由用途（不带 JetStream 复制）时台数随意，但**一旦要复制 stream，就该取奇数**。

## Routes vs Gateways

route 与 gateway 都是 server 之间的连接，但**它们对"对方是什么"的假设完全不同**：

| | route | gateway |
| :--- | :--- | :--- |
| 连接的粒度 | **server-to-server** | **cluster-to-cluster** |
| 假设的距离 | 近（同机房 / 同可用区） | 远（跨地域 / 跨云） |
| 拓扑 | 全互联 mesh，gossip 自动补齐 | 每台 server 对远端集群各开**一条**连接 |
| 发现方式 | gossip | 也 gossip，seed 部分远端集群即可 |
| 额外能力 | 无 | geo-affinity 地理亲和 |

**不要用 route 跨区。** route mesh 是全互联的：三台机器就是三条双向链路，十台机器就是每台连其余九台。放到跨地域环境里，这个连接数乘上 RTT 与带宽成本，会把跨区带宽吃干。更重要的是 route 假设链路便宜且稳定——它没有跨 WAN 的流量治理手段，不做地理亲和，不会因为本地有订阅者就优先本地消费。

gateway 的连接模型则克制得多：**每台 server 只开一条到对方集群的连接**，而不是像 route 那样对每个远端 server 都开一条。远端集群有多少台机器都不影响本端的连接数。

```conf
# n1-east：east 集群的一员
server_name: n1-east
listen: 0.0.0.0:4222

cluster {
  name: east
  listen: 0.0.0.0:6222
  routes: [
    nats://n2-east:6222,
    nats://n3-east:6222
  ]
}

gateway {
  name: east
  listen: 0.0.0.0:7222
  gateways: [
    {
      name: west
      urls: [
        nats://n1-west:7222,
        nats://n2-west:7222
      ]
    }
  ]
}
```

`gateway { name }` 标识的是**集群**，必须与 `cluster { name }` **完全一致**。不一致时 server 直接**拒绝启动**，报 `cluster name conflicts between cluster and gateway definitions`。改集群名时这是一处容易漏改的地方。

`gateways` 数组里的每一项都要写远端集群的**准确名字**（`name`）和它的 gateway 监听地址（`urls`）。同一集群的三台 server 用**完全相同**的这段配置——包括 `name` 和 `gateways` 列表；把自己这一项写进 `gateways` 会被自动忽略。

`urls` 不必列出对端每一台 server——seed 部分地址即可，其余通过 gateway 之间的 gossip 自动发现。列全的好处是某台对端挂了还有别的可连。

## Supercluster and Geo-Affinity

两个 cluster 通过 gateway 连起来之后，就组成了 **supercluster**：全局一张 subject 空间，任一节点发布，任一集群的订阅者都能收到。

### Interest-Driven Forwarding

**gateway 只转发对端有 interest 的消息**——对端没有任何订阅者，一条消息都不会跨 gateway。这是跨 WAN 部署便宜的**根本原因**，也是评估 supercluster 带宽成本时最该先确认的一件事：

- 某个 subject 只有 east 侧订阅 → 流量**完全不跨区**。
- 某个 subject 两侧都订阅 → 每次发布走一次跨区链路。

所以"跨区流量大"通常不是 gateway 的问题，而是 **subject 划分**的问题。把只被本地消费的数据放进会被远端订阅的 subject，或让消费者订阅一个过宽的通配符（`>`），都会无谓地把流量拉过 WAN。

### Geo-Affinity

geo-affinity 是 supercluster 的**流量路由偏好**：queue group 与 request 流量**优先本地 worker**，本地没有可用订阅者时才跨 gateway。

它依赖 queue group。普通的 `publish` / `subscribe` 没有"选一个 worker"的语义，queue group 才有。多个远端集群都有 worker 时，NATS 只挑**一个**跨过去——保证一条消息只到达一个 worker，而不是在每个集群各发一份。

这带来一条部署纪律：**每个 region 都要有自己那份 worker**。把所有 worker 集中在一个 region、让另一个 region 发布，稳态流量就会持续跨 gateway，geo-affinity 形同虚设。

## Leaf Nodes

leaf node 是一个**主动向外拨号**的 NATS server，它桥接的是**跨连接的 subject interest**——hub 上订阅 `sensor.>` 的消费者，能收到接在 leaf 上、地址完全不同的边缘机器发布的 `sensor.*`。

方向是 leaf 的根本属性：

- **hub 侧**只负责**监听**：`leafnodes { listen: 7422 }`，等着被连。
- **leaf 侧**只负责**拨号**：`leafnodes { remotes: [ ... ] }`。

```conf
# 中心 hub：只听
server_name: hub-east
listen: 0.0.0.0:4222

leafnodes {
  listen: 0.0.0.0:7422
}
```

```conf
# 边缘 factory-1：只连
server_name: factory-1
listen: 0.0.0.0:4222

leafnodes {
  remotes: [
    {
      urls: [
        "nats-leaf://leaf-user:leaf-pass@hub-east:7422"
      ]
    }
  ]
}
```

**方向不能搞反。** leaf 只有出向能力：把 `listen` 放在边缘侧、指望 hub 来拨，连接永远建不起来——边缘侧既不知道 hub 的地址，也没有被拨的入口。反过来，把 `remotes` 写在 hub 上，让 hub 去拨边缘，也会得到一个语义完全不同的结构（hub 变成边缘的"下游"）。

leaf 可以有**多个 remotes**，同时桥接多个 NATS 系统；也可以自己再 `listen` 而成为下一级 hub——leaf link 可以组合成树。

`urls` 里写的是 hub 各台的 leafnode 监听地址，**列全可以多一条重连去处**。需要用户名 / 密码或 token 时，直接编码进 URL；URL scheme 用 `nats-leaf`（WebSocket 场景用 `ws`）。

### Account and Credentials

leaf 桥接的是 subject 空间，因此**账号必须对齐**。生产上 `remote` 里常用 `account` 指定本地账号、用 `credentials` 指定 `.creds` 文件证明身份，**两端指向同一个 account**，才能共享同一份隔离的 subject 空间：

```conf
leafnodes {
  remotes: [
    {
      urls: [
        "nats-leaf://leaf-user@hub-east:7422"
      ]
      account: "EDGE"
      credentials: "/etc/nats/edge-user.creds"
    }
  ]
}
```

用默认账号则**没有任何 subject 边界**——hub 上所有账号的消息，边缘侧都可能看到。

### Address Space Isolation

leaf 的 **local client 对 hub 不可见**：hub 只看到**一条** leaf 连接，边缘侧成百上千台机器全部隐藏在 leaf 之后。这是拓扑上的一层地址空间隔离，也带来两个后果：

1. hub 侧的监控与容量规划**看不到**边缘的真实连接数——边缘机器在 hub 眼里只是 leaf 的若干条 client 连接。
2. 边缘侧 client 的源地址对 hub 是 leaf 的地址，做 IP 白名单或审计时需要按 leaf 归集。

要分清两件事：**client 被隐藏是 leaf link 天生的属性**，而 **subject 空间的隔离是 account 决定的**——只有绑定到各自的 account、且该 account 只 import/export 了需要跨链路流通的 subject 时，边界才真正成立。用默认 account 时这条链路没有 subject 边界，interest 会像集群内的 route 一样自由穿过。

2.15 的两处相关变化：

- leafnode 的 `no_advertise` **不再包含 hub 自身的 listener**（此前会把 hub 自己的地址也带进去）。
- leafnode isolation（`request_isolation`，或 hub 端的 `isolate`）**跨集群节点现在正确生效**——此前只有当所有 leafnode 都连到同一个 hub 节点时隔离才正确。

## JetStream Domains

leaf 上的 JetStream 需要显式配置 **domain**，否则会与 hub 的 JetStream 冲突：

```conf
# 边缘 factory-1
jetstream {
  domain: "factory"
}

# 中心 hub-east
jetstream {
  domain: "east"
}
```

**不配 domain 时的实际行为不是"报错"，而是更麻烦的"悄悄合并"**：leaf 开启 JetStream 会**延伸 hub 的 JetStream**，而不是形成一个本地独立系统——stream 可能直接落在 hub 上。你以为在边缘做本地持久化，实际数据写进了中心机器。

domain 的作用是把 JetStream 的命名空间切分。配了 `factory` 与 `east` 两个 domain，两侧的 stream、consumer、API 各自独立。

跨 domain 管理可以借助 **system account 桥接**：把 system account 桥接到一个**不同 domain 的 leafnode** 之后，就能直接对 hub 指定 JetStream domain 来管理，不必把管理权限散到各处。

## Cross-Region Data Copy

跨地域复制数据用 **mirror / source** 两条机制，配合 domain 隔离两侧的 JetStream：

| 机制 | 方向 | 语义 |
| :--- | :--- | :--- |
| **source** | 目标流从源流**拉取** | 目标流是源流的一个子集视图，可带 subject 过滤 |
| **mirror** | 源流**推送**到目标流 | 目标流是源流的完整副本 |

两侧的 JetStream 必须先靠 domain 隔开，否则 source / mirror 找不到对方、或互相递归。domain-prefixed 的 JetStream API 与 source 的重建检测（源流重建后自动从正确序列号重启 sourcing）见 [Clustering](/docs/CS/MQ/NATS/Clustering.md?id=stream-source-indexing)；mirror / source 的完整配置语义在 JetStream 分册展开。

方向选择上，**source 更适合"对方是权威源"的场景**（目标端可控地拉取），**mirror 更适合"权威在本地、要往外分发"的场景**。

### Backup and Restore

跨地域迁移的第三条路径是**备份 / 恢复**，2.15 的 **Stream backup and restore v2**（ADR-63）把备份格式换成**可被 NATS CLI 解析和操作的格式**，而不是磁盘上的原始格式：

- 备份产物不再是"某个版本的私有二进制"，而是 CLI 能直接读、能直接用于恢复的格式。
- **memory stream 也能备份 / 恢复**——此前 memory stream 的数据随进程消失，没有可迁移的载体。

这条路径适合"一次性把整份数据搬到另一个集群"，与 mirror / source 的持续同步是不同用途：前者是快照式迁移，后者是持续复制。

## Pitfalls

- **用 route 跨区**：route mesh 是全互联的，跨地域时连接数与带宽成本都会失控。跨区用 gateway。
- **gateway `name` 与 `cluster { name }` 不一致**：server 拒绝启动，报 `cluster name conflicts between cluster and gateway definitions`。改集群名时容易漏改 gateway 段。
- **gateway 名字拼错却"看起来能用"**：把 `gateways` 里的远端集群名拼错（例如写成 `wset`，实际是 `west`），该条目永远连不上，日志每次重试都报 `Failing connection to gateway "wset", remote gateway name is "west"`。但由于对端配置正确、**反向连接仍能建立**，supercluster 照样形成——于是"跨区发布成功"并不能证明你的配置是对的。必须逐台看日志里的这个错误串。
- **geo-affinity 只在本地存在 queue 订阅者时有效**：把所有 worker 集中在一个 region、让另一 region 发布，稳态流量就会持续跨 gateway。geo-affinity 不是跨区流量问题的通用解。
- **leaf 方向搞反**：把 `listen` 放在边缘侧、指望 hub 拨过来，永远连不上。leaf 只有出向能力。
- **leaf 未配 domain 就开 JetStream**：不会报错，而是悄悄延伸 hub 的 JetStream，stream 可能落在 hub 上。
- **leaf 两端 account 不对齐**：用默认账号则没有 subject 边界，边缘侧可能看到 hub 上所有账号的消息。
- **用通配符订阅拉高跨区流量**：gateway 只转发对端有 interest 的消息，一条过宽的 `>` 订阅足以让整个 subject 树跨 WAN。

## Links

- [NATS 总纲](/docs/CS/MQ/NATS.md)
- [集群与复制](/docs/CS/MQ/NATS/Clustering.md)
- [JetStream 持久化语义](/docs/CS/MQ/NATS/JetStream.md)
- [安全模型](/docs/CS/MQ/NATS/Security.md)
- [MQ 总纲](/docs/CS/MQ/MQ.md)
- [Kafka 多集群对照](/docs/CS/MQ/Kafka/Kafka.md?id=multiple-clusters)

## References

- NATS 官方文档 - Superclusters: https://docs.nats.io/learn/topologies/super-clusters
- NATS 官方文档 - Leaf Nodes: https://docs.nats.io/learn/topologies/leaf-nodes
- NATS 官方文档 - Gateways 配置: https://docs.nats.io/running-a-nats-service/configuration/gateways
- NATS 官方文档 - Leafnodes 配置: https://docs.nats.io/running-a-nats-service/configuration/leafnodes
- NATS 官方文档 - Clustering 配置: https://docs.nats.io/running-a-nats-service/configuration/clustering
- ADR-63 - Stream Backup and Restore v2: https://github.com/nats-io/nats-architecture-and-design/blob/main/adr/ADR-63.md
