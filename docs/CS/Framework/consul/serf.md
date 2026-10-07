## Introduction

Consul 用 **Serf**（HashiCorp 基于 SWIM 算法实现的 gossip 库）做成员发现、故障检测与事件广播。它和 [Raft](/docs/CS/Framework/consul/raft.md) 是两套独立机制：Raft 管"状态一致"，Serf 管"谁在集群里、谁挂了"。这是 etcd（静态 peer 列表）和 ZooKeeper（静态 peer 列表）都没有的原生能力——也是 Consul 能平滑扩缩 server、做跨数据中心联邦的基础。

## Two Sets of gossip Pools

Consul 维护**两套独立的 Serf 池**：

- **LAN 池**：同数据中心内所有 agent（server + client）互相 gossip，负责节点加入 / 离开、故障检测、反熵（anti-entropy）同步。
- **WAN 池**：仅 server 之间跨数据中心 gossip，用于多 DC 联邦（[Gateway](/docs/CS/Framework/consul/gateway.md) 详述）。`serf_wan` 设为 `-1` 会直接禁用 WAN 联邦（不推荐）。

端口：LAN `8301`（TCP+UDP）、WAN `8302`（TCP+UDP）。阻塞这两个端口的入/出站都会扰乱 gossip 导致集群不稳。

## Failure Detection (SWIM)

Serf 采用 SWIM（Scalable Weakly-consistent Infection-style Process Group Membership）风格的探测：

- 每个节点周期性向随机选中的对端发 **probe**；未收到 ack 则进入 **suspicion**（怀疑）状态，经 `suspicion_mult` × 探测间隔后如果仍无确认，标记 `failed`。
- 探测失败不立即删除成员，而是先怀疑，避免网络抖动造成误删——比"超时即删"更稳。
- 节点状态机会经历 `alive → suspect → failed / left`，相关信息通过 gossip 扩散到全集群。

> [!TIP]
> gossip 对延迟敏感：官方参考架构要求同 DC 内 **平均 RTT < 50ms、p99 RTT < 100ms**。跨可用区部署时若 RTT 过高，会出现频繁 `suspicion`、server 被误判 failed、进而触发 Raft 重选。此时应调 `serf_lan` 重传或把 server 收敛到更近的 AZ（见 [Tuning](/docs/CS/Framework/consul/tuning.md)）。

## Network Coordinates

Serf 顺带估算各节点的**网络坐标**（基于 Vivaldi 算法的分布式 RTT 模型），Consul 据此能：

- 在 DNS / 健康查询里返回**最近的实例**（按估算 RTT 排序）；
- 故障时 failover 到"下一个最近的 DC"，实现本 DC 优先的就近路由（[Consul](/docs/CS/Framework/consul/Consul.md) 的多数据中心段有叙述）。

这是 etcd / ZooKeeper 完全不具备的原生能力——它们要么靠外部 LB，要么靠人工选址。

## Encryption: Symmetric Keyring

LAN / WAN gossip 流量可用**对称密钥环**加密（`encrypt` 配置，Base64 编码的 16 字节密钥，`consul keygen` 生成）。特性：

- 集群所有节点必须共享同一把（或兼容的）密钥才能通信；
- 密钥自动写入 `-data-dir` 并在重启时加载，因此只在首次启动时提供一次即可；
- 支持 **keyring 多密钥轮换**：`consul keyring -install <new>` 安装、`-use <new>` 切换、`-remove <old>` 移除，实现零停机轮转；
- `disable-keyring-file` 可禁止落盘（重启需重新 `-encrypt`）。

> [!WARNING]
> gossip 加密只是"链路对称加密 + 认证"，**不等于 ACL 授权**。任何拿到密钥的节点都能加入集群并读 catalog。真正的访问控制仍靠 [Security](/docs/CS/Framework/consul/security.md) 的 ACL + mTLS。

## Comparison with etcd / ZooKeeper

| 维度 | Consul（Serf） | etcd | ZooKeeper |
| :--- | :--- | :--- | :--- |
| 成员发现 | gossip 自动（LAN+WAN） | 静态 peer 列表 | 静态 peer 列表 |
| 故障检测 | SWIM（怀疑→失败） | 心跳超时 | 心跳超时 |
| 跨 DC | WAN gossip 原生 | 需外部复制 | 无 |
| 就近路由 | 网络坐标估算 RTT | 无 | 无 |
| 加密 | gossip keyring | TLS（需显式配） | SASL / TLS |

Consul 用"gossip 管成员、Raft 管状态"的解耦，换来了比 etcd/ZooKeeper 更顺滑的扩缩容与多活 DC；代价是要同时运维两套通道，且 gossip 对网络延迟敏感（见 [Troubleshooting](/docs/CS/Framework/consul/troubleshooting.md) 的 gossip 分区段）。

## Links

- [Consul（架构与启动流程）](/docs/CS/Framework/consul/Consul.md)
- [Raft（共识）](/docs/CS/Framework/consul/raft.md)
- [Gateway（网关与联邦）](/docs/CS/Framework/consul/gateway.md)
- [Security（安全）](/docs/CS/Framework/consul/security.md)
- [Troubleshooting（故障排查）](/docs/CS/Framework/consul/troubleshooting.md)
- [etcd 横向对照](/docs/CS/Framework/etcd/compare.md)

## References

1. [Consul Gossip Protocol](https://developer.hashicorp.com/consul/docs/concept/gossip)
2. [Serf Project](https://www.serf.io/)
3. [Consul Reference Architecture (ports)](https://developer.hashicorp.com/consul/docs/install/ports)
