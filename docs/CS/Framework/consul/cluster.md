## Introduction

Consul 集群由 **server**（参与 Raft）与 **client**（轻量转发代理）组成，原生多数据中心。本篇覆盖规模、引导、参考架构、备份恢复与升级，对标 etcd 的 [cluster](/docs/CS/Framework/etcd/cluster.md)。

## Server / Client 模式

- **Server**：参与 Raft、持有 catalog、响应 RPC 与查询；生产建议 **3（小）或 5（生产）** 个，奇数，容忍 `(n-1)/2` 故障。不要堆到 7+（拖慢提交）。
- **Client**：业务机器上跑，把注册 / 检查 / 查询转发给 server，自身不参与 Raft；可水平扩展、数量无限制。

## 引导与加入

| 参数 / 命令 | 用途 |
| :--- | :--- |
| `-server` | 以 server 模式启动 |
| `-bootstrap-expect=<n>` | 期望 server 数，达到即自动引导选主（不能与旧 `-bootstrap` 同用） |
| `-retry-join=<addr>` | 启动时尝试加入，失败重试（支持云自动发现 `provider=aws` 等） |
| `-retry-join-wan=<addr>` | 跨 DC 加入 WAN 池 |
| `-datacenter=<dc>` | 数据中心名，默认 `dc1` |

> [!WARNING]
> 每个 DC 最多一个 `-bootstrap` 节点；集群引导后不应再带 `-bootstrap`（多个自选举会脑裂）。现代做法用 `-bootstrap-expect` 自动引导，避免手动 bootstrap。

## 参考架构与网络约束

- **规模**：3/5 server；client 不限。
- **gossip 延迟预算**：同 DC 平均 RTT < **50ms**、p99 RTT < **100ms**（仅 gossip 受此约束；RPC / HTTP / xDS / DNS 不受）。超预算会频繁 suspicion、server 被误判 failed（见 [Serf](/docs/CS/Framework/consul/serf.md)）。
- **防火墙**：同 DC 必须放行 8300（RPC）、8301（LAN）、8302（WAN，仅多 DC）、8500（HTTP）、8600（DNS）；跨 DC 额外放行 8302。sidecar 需放开 21000–21255（见 [Consul 端口](https://developer.hashicorp.com/consul/docs/install/ports)）。

## 备份与恢复

- `consul snapshot save <file>`：对 Raft 状态做快照，**含 KV + catalog + ACL + connect CA 令牌**；
- `consul snapshot restore <file>`：恢复（需 leader 稳定、尽量同 DC 同大版本）；
- **WAN 各 DC 独立**，需分别备份分别恢复——快照不跨 DC 合并；
- 快照含 ACL token，妥善保管（权限 `0600`）。

> [!TIP]
> "health 页 200"不等于能写。备份前先确认 `consul operator autopilot health` 的 `Healthy=true` 且 `FailureTolerance` 正常，再做快照，避免备份到不一致状态。

## 滚动升级

- 走 **Autopilot**（见 [Raft](/docs/CS/Framework/consul/raft.md)）：先升 follower，再升 leader（Autopilot 自动稳选）；
- `raft_protocol` 按官方升级指南逐级升，勿跨多版本跳；
- 跨 **1.x → 2.0** 重点评估 BSL 许可变化与配置兼容性（2.0.0 把默认 HTTP 读超时提到 15 分钟、go 升到 1.26）；
- Enterprise 有自动升级迁移（`UpgradeVersionTag` / `DisableUpgradeMigration`）。

## ACL 复制与多租户

- 从属 DC 默认只复制 ACL **策略与角色**；`enable_token_replication` 才复制令牌（会丢失已有全局令牌，谨慎）；
- `primary_datacenter` 是 ACL 与 connect CA 的权威源，所有 DC 必须一致（[Security](/docs/CS/Framework/consul/security.md)）；
- 多租户：namespaces（1.7+，Enterprise 正式）/ admin partitions（Enterprise，1.17+ 强化）。

## 与 etcd 对照

| 维度 | Consul | etcd |
| :--- | :--- | :--- |
| 节点角色 | server + client | 全 peer（无轻量 client） |
| 多 DC | 原生 WAN 联邦 | 需外部复制 |
| 引导 | `-bootstrap-expect` 自动 | `--initial-cluster` 静态 |
| 备份 | `consul snapshot` | `etcdctl snapshot` |
| 自动化运维 | Autopilot | 需外部 operator |

Consul 的 client/server 分离 + 自动引导 + Autopilot，运维面比 etcd 静态 peer 宽但自动化更高；etcd 更精简、与 K8s 集成更深。

## Links

- [Consul（架构与启动流程）](/docs/CS/Framework/consul/Consul.md)
- [Raft（共识）](/docs/CS/Framework/consul/raft.md)
- [Serf（成员发现）](/docs/CS/Framework/consul/serf.md)
- [Security（安全）](/docs/CS/Framework/consul/security.md)
- [Troubleshooting（故障排查）](/docs/CS/Framework/consul/troubleshooting.md)
- [Tuning（调优）](/docs/CS/Framework/consul/tuning.md)
- [etcd cluster](/docs/CS/Framework/etcd/cluster.md)

## References

1. [Consul Reference Architecture](https://developer.hashicorp.com/consul/docs/guides/deployment)
2. [Consul Agent Configuration (bootstrap)](https://developer.hashicorp.com/consul/docs/reference/agent/configuration-file/bootstrap)
3. [Consul Snapshot](https://developer.hashicorp.com/consul/api-docs/snapshot)
4. [Consul Upgrade](https://developer.hashicorp.com/consul/docs/upgrade)
