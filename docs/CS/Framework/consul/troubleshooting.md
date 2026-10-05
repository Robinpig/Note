## Introduction

本篇汇总 Consul 生产常见故障，每类给出**症状 → 原因 → 修复**。对标 etcd 的 [troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md)。

## 1. Quorum 丢失 → 集群只读

- **症状**：API 返回 "No cluster leader" / 写报 500；`/v1/status/leader` 为空。
- **原因**：超过 `(n-1)/2` 个 server 同时down（如 3 节点丢 2 个）；或剩余 server 间 RPC（8300）不通。
- **修复**：恢复足够 server 在线；确认 8300 互通；不要强行 `-bootstrap` 多个节点（会脑裂）。能用 `consul operator raft list-peers` 看 peer 集。实在无法恢复需用 `consul snapshot restore` 或 `raft` 目录恢复（见 [Cluster](/docs/CS/Framework/consul/cluster.md)）。

## 2. Gossip 分区（LAN / WAN）

- **症状**：`serfLAN_members` 波动、节点在 `alive/suspect/failed` 间跳；server 被反复移出投票圈。
- **原因**：跨 AZ RTT 超预算（平均 >50ms / p99 >100ms）、8301/8302 被防火墙拦、UDP 丢包。
- **修复**：放开 8301/8302（TCP+UDP）入出站；跨 AZ 收敛 server；调 `serf_lan` 重传；查 NAT/负载均衡是否引入额外 RTT（见 [Serf](/docs/CS/Framework/consul/serf.md) 与 [Tuning](/docs/CS/Framework/consul/tuning.md)）。

## 3. ACL token 问题

- **症状**：API 返回 403 `Permission denied`；DNS 发现突然失效（默认 token 无读权限）；`initial_management` 丢失无法引导。
- **原因**：`default_policy` 切 `deny` 但没发对应 token；`acl_datacenter` 各节点不一致；token 缓存（`acl.*_ttl` 30s）未刷新。
- **修复**：确认 `acl_datacenter` 全集群一致；给 agent 配 `acl.tokens.agent` / `acl.tokens.default`（DNS 需 service 读）；紧急用 `initial_management` 令牌；等 30s 缓存失效或重启 agent。详见 [Security](/docs/CS/Framework/consul/security.md)。

## 4. 服务网格 / xDS 连接失败

- **症状**：sidecar 起不来、`8502` xDS 拉不到配置、服务间 mTLS 握手失败。
- **原因**：`primary_datacenter` 未设（CA 根缺失）；gRPC 8502/8503 被拦；Envoy 版本不兼容（2.0 需 Envoy 1.37.x）；ACL 缺 `mesh:write`（2.0.4 起附 EnvoyExtension 需它）。
- **修复**：确认主 DC 与 CA 复制正常；放开 8502/8503；对齐 Envoy 版本；补 `mesh:write` 权限。详见 [Mesh](/docs/CS/Framework/consul/mesh.md)。

## 5. Snapshot 恢复失败

- **症状**：`consul snapshot restore` 报错、恢复后数据缺失。
- **原因**：从异版本 / 异 DC 的快照恢复（ACL 令牌、connect CA 都含在快照里，跨 DC 错配会乱）；恢复时集群状态不一致。
- **修复**：优先同 DC 同大版本恢复；恢复前停写、确认 leader 稳定；WAN 各 DC **分别**备份分别恢复（见 [Cluster](/docs/CS/Framework/consul/cluster.md)）。

## 6. 时钟偏移

- **症状**：TLS 证书校验失败、session / 检查 TTL 判断异常、日志时间错乱难排查。
- **原因**：节点未同步 NTP，偏移大。
- **修复**：全集群启用 NTP；Consul 虽不强制时钟同步，但证书与 TTL 依赖合理时钟。

## 7. KV 值过大

- **症状**：`consul kv put` 报值超限。
- **原因**：单 value 超过 **512KB** 限制。
- **修复**：大对象外置对象存储，KV 只存指针/元数据。详见 [KV](/docs/CS/Framework/consul/kv.md)。

## 8. Leader flapping（频繁易主）

- **症状**：`raft_leader_lastContact` 抖动、`consul_server_is_leader` 频繁翻转。
- **原因**：磁盘 IO 慢（WAL 落盘延迟）、`raft_multiplier` 过小致心跳过激、`max_trailing_logs` 被频繁触及、网络抖动。
- **修复**：`-data-dir` 换低延迟磁盘；适当调大 `raft_multiplier`；查 Autopilot 健康（`max_trailing_logs` 默认 250，落后即挡投票）。详见 [Raft](/docs/CS/Framework/consul/raft.md) 与 [Tuning](/docs/CS/Framework/consul/tuning.md)。

## 9. 升级 / 回退

- **症状**：升级后 server 无法加入、raft protocol 不兼容。
- **原因**：跨大版本直升、raft protocol 版本跳变、BSL 许可变化未评估。
- **修复**：走 Autopilot 滚动（先升 follower）；`raft_protocol` 按官方升级指南逐级升；跨 1.x→2.0 重点看 BSL 与配置兼容性。详见 [Cluster](/docs/CS/Framework/consul/cluster.md)。

## Links

- [Consul（架构与启动流程）](/docs/CS/Framework/consul/Consul.md)
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
