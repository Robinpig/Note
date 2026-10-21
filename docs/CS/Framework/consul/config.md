## Introduction

Consul 用 **HCL**（也接受 JSON）描述配置：`consul agent -config-file=<f>` 读单个文件，或 `-config-dir=<dir>` 合并目录下所有 `.hcl`/`.json`（按字母序，后加载覆盖前）。本篇按子系统罗列最常用的 HCL 参数与三类典型组合；逐项默认值与全量字段以官方 [Agent Configuration](https://developer.hashicorp.com/consul/docs/reference/configuration) 为准。集群引导/备份/升级见 [Cluster](/docs/CS/Framework/consul/cluster.md)，安全细节见 [Security](/docs/CS/Framework/consul/security.md)，调优项见 [Tuning](/docs/CS/Framework/consul/tuning.md)。

> [!NOTE]
> 版本事实：2.0.x 当前主线（2.0.4，2026-09-09）。2.0.0 把默认 HTTP 读超时提高到 15 分钟、Go 升到 1.26，配置项总体向后兼容。

## Key Parameters by Group

| 分组 | 参数 | 默认 / 常见 | 说明 |
| :--- | :--- | :--- | :--- |
| 基础 | `node_name` | 主机名 | agent 在 catalog 中的节点名 |
| 基础 | `datacenter` | `dc1` | 数据中心名；同 DC 内必须一致 |
| 基础 | `data_dir` | — | Raft 日志 / 快照 / agent 状态存放处，放低延迟磁盘 |
| 基础 | `bind_addr` | `0.0.0.0` | 绑定的内部通信地址（通常用内网 IP） |
| 基础 | `advertise_addr` | `bind_addr` | 通告给其他节点的地址（跨网段/NAT 时设） |
| 基础 | `client_addr` | `127.0.0.1` | DNS/HTTP/gRPC 监听地址；要远程访问需放开 |
| Server | `server` | `false` | `true` 即以 server 模式启动 |
| Server | `bootstrap_expect` | 0 | 期望 server 数（3/5）；达到即自动引导 |
| Server | `retry_join` | — | 启动时尝试加入的 server 地址列表（支持云自动发现） |
| Raft | `raft_multiplier` | `5` | 缩放 Raft 心跳/选举节拍，调小更激进、调大更省 |
| Raft | `raft_snapshot_threshold` | `16384` | 两次快照间最少提交条目数 |
| Serf | `retry_join_wan` | — | 跨 DC 加入 WAN gossip 池 |
| Serf | `serf_lan_reconnect_timeout` | — | LAN 重连窗口（跨 AZ 可调大） |
| ACL | `acl.enabled` | `false` | 是否启用 ACL（生产必须 `true`） |
| ACL | `acl.default_policy` | `allow` | `deny` 更严；已运行集群先 `allow` 过渡再切 |
| ACL | `acl.tokens` | — | 内置/主 token、agent/recovery token 配置 |
| ACL | `acl.datacenter` | — | 存放 ACL 权威状态的 DC（通常 `primary_datacenter`） |
| Connect | `connect.enabled` | `false` | 开启服务网格（Envoy sidecar） |
| Connect | `connect.ca_provider` | `consul` | 内置 CA；也可接 Vault/PKI |
| TLS | `auto_encrypt` | `false` | agent 自动向 server 申请并轮换 TLS 证书 |
| 加密 | `encrypt` | — | gossip 对称密钥（64 位 base64，由 `consul keygen` 生成） |
| 遥测 | `telemetry.prometheus_retention_time` | — | Prometheus 指标保留时长（设 >0 开启拉取端点） |
| 遥测 | `telemetry.dogstatsd_addr` | — | 走 statsd / DogStatsD 上报 |

> [!WARNING]
> `bootstrap_expect` 与旧式 `-bootstrap` 不能混用：集群内出现多个自选举的 `-bootstrap` 节点会脑裂。现代做法一律用 `bootstrap_expect` 自动引导。引导完成后**不要再**带 `-bootstrap` 启动。

## Recipe 1: Single DC, 3 Servers

最小生产可用单 DC（每 server 节点一份，仅 `advertise_addr` / `node_name` 不同）：

```hcl
node_name  = "consul-s1"
datacenter = "dc1"
data_dir   = "/opt/consul/data"
bind_addr  = "10.0.0.11"
advertise_addr = "10.0.0.11"
client_addr = "0.0.0.0"

server             = true
bootstrap_expect   = 3
retry_join         = ["10.0.0.11", "10.0.0.12", "10.0.0.13"]

# 轻量 client 把 server 段删掉、server=false 即可，同 retry_join
```

client 节点：`server = false`，其余 `datacenter` / `retry_join` 一致即可水平扩展。

## Recipe 2: ACL Deny-by-Default + TLS

先 `consul acl bootstrap` 拿到主 token，再把默认策略切到 `deny`：

```hcl
datacenter = "dc1"
server      = true
bootstrap_expect = 3
retry_join  = ["10.0.0.11", "10.0.0.12", "10.0.0.13"]

acl {
  enabled        = true
  default_policy = "deny"        # 先 allow 过渡，令牌分发完再切 deny
  enable_token_persistence = true
}

auto_encrypt {
  allow_tls = true               # agent 自动申请 TLS 证书
}

# gossip 对称加密（consul keygen 生成）
encrypt = "<64-bit-base64-key>"
```

> [!TIP]
> 已运行集群**不要直接**把 `default_policy` 从 `allow` 切到 `deny`——会瞬间拒绝所有既有调用。正确顺序：启用 ACL → 配策略与令牌并分发 → 确认业务都带上 token → 再切 `deny`。

## Recipe 3: WAN Federation (Multi-DC)

每个 DC 独立配置，server 通过 `retry_join_wan` 互联：

```hcl
datacenter = "dc2"
server      = true
bootstrap_expect = 3
retry_join      = ["10.1.0.11", "10.1.0.12", "10.1.0.13"]
retry_join_wan  = ["10.0.0.11", "10.0.0.12", "10.0.0.13"]  # 指向 dc1 的 server

primary_datacenter = "dc1"      # ACL / connect CA 权威源，所有 DC 必须一致
```

各 DC 是独立 Raft 组 + 独立 catalog，server 间经 WAN gossip（`8302`）互联；目录读默认本地、写落本地 DC，跨 DC 经 gateway / `/v1/catalog/datacenters` 聚合（见 [Gateway](/docs/CS/Framework/consul/gateway.md)）。

## Links

- [Consul（枢纽）](/docs/CS/Framework/consul/Consul.md)
- [Cluster（集群运维）](/docs/CS/Framework/consul/cluster.md)
- [Security（安全）](/docs/CS/Framework/consul/security.md)
- [Tuning（调优）](/docs/CS/Framework/consul/tuning.md)
- [Architecture（架构深潜）](/docs/CS/Framework/consul/architecture.md)
- [Troubleshooting（故障排查）](/docs/CS/Framework/consul/troubleshooting.md)
- [etcd 配置对照](/docs/CS/Framework/etcd/etcd.md)

## References

1. [Consul Agent Configuration](https://developer.hashicorp.com/consul/docs/reference/configuration)
2. [Consul ACL Configuration](https://developer.hashicorp.com/consul/docs/security/acl/acl-system)
3. [Consul Encryption](https://developer.hashicorp.com/consul/docs/security/encryption)
4. [Consul WAN Federation](https://developer.hashicorp.com/consul/docs/datacenters/wan-federation)
