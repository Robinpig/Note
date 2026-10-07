## Introduction

Consul 的安全体系由三层组成：**ACL**（授权，零信任默认收口）、**传输 TLS**（RPC / gossip / 网格 mTLS）、**Connect CA**（服务网格证书）。与 etcd 的 RBAC + mTLS（见 [etcd security](/docs/CS/Framework/etcd/security.md)）相比，Consul 的 ACL 体系最贴近"零信任网络"的默认收口，但**默认并不启用**——需要显式打开并按最小权限配置。

> [!WARNING]
> 关键事实更正：Consul 的 `acl.default_policy` **出厂默认是 `allow`**（未来大版本才计划改 `deny`），且 ACL **默认不启用**（`acl.enabled=false`）。生产环境务必在 `acl` 段设 `enabled=true` 并 `default_policy="deny"`，且 `primary_datacenter` 必须指定才能启用 ACL。本文此前在总文档里写成"默认 deny"是不准确的。

## ACL: Access Control

### Enablement and Default Policy

- `acl.enabled = true` 开启；`acl_datacenter` 指定 ACL 权威 DC（所有 server 与 client 必须就此达成一致，否则 API 转发异常）。
- `acl.default_policy`：`allow`（黑名单式，未禁即许）/ `deny`（白名单式，未许即拒）。**新 DC 直接设 `deny`**；已运行集群先保持 `allow`，待令牌分发完毕再切 `deny`，避免业务中断。
- `acl.down_policy`（ACL 解析失败时的降级）：`extend-cache`（默认）/ `allow` / `deny` / `async-cache`。

### Resource Model

ACL 规则作用于资源：`acl`、`agent`、`event`、`key`、`keyring`、`node`、`operator`、`query`、`service`、`session`。典型规则：

```hcl
service "web" {
  policy = "read"
}
key_prefix "config/" {
  policy = "write"
}
```

### Tokens and Roles

- **token**：实际携带动证的字符串；内置 `anonymous`（无 token 时使用）、`initial_management`（引导用管理令牌，1.11+ 取代旧 `master`）。
- **policy**：规则集合；**role**：一组 policy + service identity 的命名包，便于批量授权。
- `acl.tokens.agent` / `acl.tokens.default` 等特殊令牌供 agent 内部操作与 DNS 默认读使用。
- `acl.policy_ttl` / `role_ttl` / `token_ttl` 默认均为 **30s**——缓存不主动失效，故 ACL 变更最多 30s 后生效；调大减刷新、调小更及时但吃性能。

### Authentication Methods and Binding Rules

无需手工发令牌：Consul 支持 **kubernetes / aws-iam / gcp / jwt / oidc / azure** 认证方法，配合 **binding rules** 把外部身份自动映射成 Consul 策略/角色（如 K8s ServiceAccount → 某 namespace 的 service 读权限）。Enterprise 还支持 **Sentinel** 做带条件逻辑的策略。

### Multi-Tenancy: namespaces / partitions

- **namespaces**：Consul 1.7+ 引入，Enterprise 正式支持，用于同 DC 内逻辑隔离（CE 仅默认 namespace）。
- **admin partitions**：Enterprise 特性（Consul 1.17+ 强化），跨 DC 的更强隔离单元，所有 client 仍需访问各 server 的 LAN Serf（8301）。

## Transport TLS

| 通道 | 配置 / 端口 | 说明 |
| :--- | :--- | :--- |
| RPC（server 间 / client→server） | `ca_file` / `cert_file` / `key_file` | 内部 RPC 加密，建议启用 |
| HTTPS | `8501`（默认禁用） | HTTP API 的 TLS 版，CLI 自动改用 |
| gRPC TLS | `8503` | Envoy xDS 的 TLS 版（推荐优于 8502 明文） |
| gossip | `encrypt` 对称密钥环 | Serf 链路加密（见 [Serf](/docs/CS/Framework/consul/serf.md)） |
| `auto_encrypt` | agent 自动向 server 要 TLS 证书 | 免手工分发 cert |
| `auto_config` | client 启动向 server 拉配置（含 ACL token / TLS / gossip key） | 需冲突注意：`auto_config` 与 `auto_encrypt.tls` 不能同时开 |

> [!WARNING]
> gossip keyring 只是"链路对称加密 + 认证"，不等于授权。任何拿到密钥的节点都能加入并读 catalog——真正访问控制仍靠 ACL。2.0.4 还修了"无 ACL token 的 mTLS 客户端可用超大 MessagePack 头 OOM-kill server"的漏洞，务必升到修了该 CVE 的版本。

## Connect CA and Security Closure

服务网格的 mTLS 由 [Mesh](/docs/CS/Framework/consul/mesh.md) 的 connect CA 托管；网格内意图（intentions）默认 deny。CA provider 可选内置 / Vault / AWS-PCA / GCP / Azure / external。ACL 中涉及网格的权限为 `mesh:write`（2.0.4 起附加 EnvoyExtension 还需它）。

## Comparison with etcd / ZooKeeper / Nacos

| 维度 | Consul | etcd | ZooKeeper | Nacos |
| :--- | :--- | :--- | :--- | :--- |
| 授权 | ACL（默认 deny 推荐） | RBAC | digest / IP ACL | ACL + RBAC |
| 默认启用 | 否（需 `enabled=true`） | 否 | 否 | 2.4+ 需初始化 |
| 传输加密 | RPC TLS + gossip keyring | mTLS | SASL / TLS | 通常走 LB |
| 网格 mTLS | 原生 | 无 | 无 | 无 |

## Links

- [Consul（架构与启动流程）](/docs/CS/Framework/consul/Consul.md)
- [Serf（成员发现）](/docs/CS/Framework/consul/serf.md)
- [Mesh（服务网格）](/docs/CS/Framework/consul/mesh.md)
- [Cluster（集群运维）](/docs/CS/Framework/consul/cluster.md)
- [Troubleshooting（故障排查）](/docs/CS/Framework/consul/troubleshooting.md)
- [etcd security](/docs/CS/Framework/etcd/security.md)

## References

1. [Consul ACL System](https://developer.hashicorp.com/consul/docs/secure/acl)
2. [Consul ACL Best Practices](https://developer.hashicorp.com/consul/docs/secure/acl/best-practice)
3. [Consul Agent TLS Configuration](https://developer.hashicorp.com/consul/docs/secure/tls)
4. [Consul Connect CA](https://developer.hashicorp.com/consul/docs/connect/ca)
