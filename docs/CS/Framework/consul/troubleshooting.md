## Introduction

本篇汇总 Consul 生产常见故障，每类给出**症状 → 原因 → 修复**。对标 etcd 的 [troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md)。

## Diagnostic Command Cheatsheet

排障第一步永远是"看清状态"，下面几条命令能覆盖八成问题：

| 命令 | 看什么 | 典型异常 |
| :--- | :--- | :--- |
| `consul members` | gossip 成员与状态 | 出现 `failed` 或数量忽增忽减 → gossip 分区（第 2 节） |
| `consul members -detailed` | 成员 + 网络坐标 | 坐标偏移大 → 跨 AZ 延迟高 |
| `consul operator raft list-peers` | Raft peer 集 | peer 少于预期 → 有 server 被 Autopilot 清理 |
| `consul status` | 当前 leader（HTTP `/v1/status/leader`） | 返回空 → 失去 quorum，写不可用（第 1 节） |
| `consul operator autopilot health` | `Healthy` / `FailureTolerance` | `Healthy=false` → 落后日志超 `max_trailing_logs` |
| `consul catalog services` | 目录内容 | 服务数骤减 → 反熵未同步或健康检查批量失败 |
| `consul agent services` | 本 agent 注册的服务与检查 | 检查 `Status=critical` → 该实例已被摘流 |
| `consul monitor` | 实时事件流（join/leave/fail） | 持续刷 `failed` → 定位反复掉线的节点 |
| `consul snapshot save <file>` | 备份 Raft 状态 | 备份前先确认 leader 存在（见 [Cluster](/docs/CS/Framework/consul/cluster.md)） |

## 1. Quorum Loss → Cluster Read-Only

- **症状**：API 返回 "No cluster leader" / 写报 500；`/v1/status/leader` 为空。
- **原因**：超过 `(n-1)/2` 个 server 同时down（如 3 节点丢 2 个）；或剩余 server 间 RPC（8300）不通。
- **修复**：恢复足够 server 在线；确认 8300 互通；不要强行 `-bootstrap` 多个节点（会脑裂）。能用 `consul operator raft list-peers` 看 peer 集。实在无法恢复需用 `consul snapshot restore` 或 `raft` 目录恢复（见 [Cluster](/docs/CS/Framework/consul/cluster.md)）。

## 2. Gossip Partitioning (LAN / WAN)

- **症状**：`serfLAN_members` 波动、节点在 `alive/suspect/failed` 间跳；server 被反复移出投票圈。
- **原因**：跨 AZ RTT 超预算（平均 >50ms / p99 >100ms）、8301/8302 被防火墙拦、UDP 丢包。
- **修复**：放开 8301/8302（TCP+UDP）入出站；跨 AZ 收敛 server；调 `serf_lan` 重传；查 NAT/负载均衡是否引入额外 RTT（见 [Serf](/docs/CS/Framework/consul/serf.md) 与 [Tuning](/docs/CS/Framework/consul/tuning.md)）。

## 3. ACL Token Issues

- **症状**：API 返回 403 `Permission denied`；DNS 发现突然失效（默认 token 无读权限）；`initial_management` 丢失无法引导。
- **原因**：`default_policy` 切 `deny` 但没发对应 token；`acl_datacenter` 各节点不一致；token 缓存（`acl.*_ttl` 30s）未刷新。
- **修复**：确认 `acl_datacenter` 全集群一致；给 agent 配 `acl.tokens.agent` / `acl.tokens.default`（DNS 需 service 读）；紧急用 `initial_management` 令牌；等 30s 缓存失效或重启 agent。详见 [Security](/docs/CS/Framework/consul/security.md)。

## 4. Service Mesh / xDS Connection Failure

- **症状**：sidecar 起不来、`8502` xDS 拉不到配置、服务间 mTLS 握手失败。
- **原因**：`primary_datacenter` 未设（CA 根缺失）；gRPC 8502/8503 被拦；Envoy 版本不兼容（2.0 需 Envoy 1.37.x）；ACL 缺 `mesh:write`（2.0.4 起附 EnvoyExtension 需它）。
- **修复**：确认主 DC 与 CA 复制正常；放开 8502/8503；对齐 Envoy 版本；补 `mesh:write` 权限。详见 [Mesh](/docs/CS/Framework/consul/mesh.md)。

## 5. Snapshot Restore Failure

- **症状**：`consul snapshot restore` 报错、恢复后数据缺失。
- **原因**：从异版本 / 异 DC 的快照恢复（ACL 令牌、connect CA 都含在快照里，跨 DC 错配会乱）；恢复时集群状态不一致。
- **修复**：优先同 DC 同大版本恢复；恢复前停写、确认 leader 稳定；WAN 各 DC **分别**备份分别恢复（见 [Cluster](/docs/CS/Framework/consul/cluster.md)）。

## 6. Clock Skew

- **症状**：TLS 证书校验失败、session / 检查 TTL 判断异常、日志时间错乱难排查。
- **原因**：节点未同步 NTP，偏移大。
- **修复**：全集群启用 NTP；Consul 虽不强制时钟同步，但证书与 TTL 依赖合理时钟。

## 7. KV Value Too Large

- **症状**：`consul kv put` 报值超限。
- **原因**：单 value 超过 **512KB** 限制。
- **修复**：大对象外置对象存储，KV 只存指针/元数据。详见 [KV](/docs/CS/Framework/consul/kv.md)。

## 8. Leader Flapping (Frequent Leadership Changes)

- **症状**：`raft_leader_lastContact` 抖动、`consul_server_is_leader` 频繁翻转。
- **原因**：磁盘 IO 慢（WAL 落盘延迟）、`raft_multiplier` 过小致心跳过激、`max_trailing_logs` 被频繁触及、网络抖动。
- **修复**：`-data-dir` 换低延迟磁盘；适当调大 `raft_multiplier`；查 Autopilot 健康（`max_trailing_logs` 默认 250，落后即挡投票）。详见 [Raft](/docs/CS/Framework/consul/raft.md) 与 [Tuning](/docs/CS/Framework/consul/tuning.md)。

## 9. Upgrade / Rollback

- **症状**：升级后 server 无法加入、raft protocol 不兼容。
- **原因**：跨大版本直升、raft protocol 版本跳变、BSL 许可变化未评估。
- **修复**：走 Autopilot 滚动（先升 follower）；`raft_protocol` 按官方升级指南逐级升；跨 1.x→2.0 重点看 BSL 与配置兼容性。详见 [Cluster](/docs/CS/Framework/consul/cluster.md)。

## 10. Client Cannot Join ("No known Consul servers")

- **症状**：client agent 启动后持续重试，日志反复出现 `No known Consul servers`；`consul members` 只有自己。
- **原因**：`retry_join` 地址不可达，或 8301（LAN gossip）/ 8300（RPC）被防火墙拦；`datacenter` 与 server 不一致（gossip 池按 DC 隔离）；server 侧还在等 `bootstrap_expect` 凑齐、尚未选出 leader。
- **修复**：核对所有节点 `datacenter` 一致；放开 8300 / 8301（TCP+UDP）；确认 server 集群已选主（`consul status` 有输出）后再启动 client；用 `consul join <server_addr>` 手动入群，再 `consul members` 验证。配置写法见 [Config](/docs/CS/Framework/consul/config.md)。

## Links

- [Consul（架构与启动流程）](/docs/CS/Framework/consul/Consul.md)
- [架构深潜](/docs/CS/Framework/consul/architecture.md)
- [数据模型](/docs/CS/Framework/consul/data_model.md)
- [配置参考](/docs/CS/Framework/consul/config.md)
- [Raft（共识）](/docs/CS/Framework/consul/raft.md)
- [Serf（成员发现）](/docs/CS/Framework/consul/serf.md)
- [KV（存储）](/docs/CS/Framework/consul/kv.md)
- [Security（安全）](/docs/CS/Framework/consul/security.md)
- [Mesh（服务网格）](/docs/CS/Framework/consul/mesh.md)
- [Cluster（集群运维）](/docs/CS/Framework/consul/cluster.md)
- [etcd troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md)

## References

1. [Consul Troubleshooting](https://developer.hashicorp.com/consul/docs/troubleshoot)
2. [Consul Outage Recovery](https://developer.hashicorp.com/consul/docs/guides/outage)
3. [Consul Upgrade](https://developer.hashicorp.com/consul/docs/upgrade)
