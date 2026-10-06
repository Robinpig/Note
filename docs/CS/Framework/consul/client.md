## Introduction

Consul 的接入极其多元：**无需私有 SDK**——普通 `dig` / `curl` / `consul` CLI 就能注册、发现、查状态。这与 ZooKeeper 的 Jute 私有协议、etcd 强依赖 gRPC 客户端（见 [etcd client](/docs/CS/Framework/etcd/client.md)）形成对比。本篇覆盖 go-client（官方 SDK）、DNS 调试、HTTP API、CLI 与服务注册。

## go-client（官方 SDK）

官方 `github.com/hashicorp/consul/api` 包按子系统拆分 client：

| 子 client | 用途 |
| :--- | :--- |
| `api.KV()` | KV 读写、CAS（`cas` 参数）、`acquire`/`release` 锁 |
| `api.Health()` | 带健康过滤的服务发现（`health.Service("web", &QueryOptions{PassingOnly:true})`） |
| `api.Catalog()` | 全量目录（不过滤健康） |
| `api.Agent()` | 本节点服务 / 检查注册、本 agent 视角 |
| `api.Session()` | 创建 / 销毁 session（锁、leader 选举） |
| `api.PreparedQuery()` | 命名查询 |

`api.DefaultConfig()` 默认连本机 `127.0.0.1:8500`（HTTP），设 `Scheme="https"` + `TLSConfig` 可走 8501。`QueryOptions{AllowStale:true}` 走 agent 缓存（[Discovery](/docs/CS/Framework/consul/discovery.md) 的 stale 读），`WaitIndex`+`WaitTime` 实现阻塞查询。

> [!TIP]
> 阻塞查询在 SDK 里用 `QueryOptions{WaitIndex: lastIndex, WaitTime: 5*time.Minute}`；Consul 2.0 起 agent 的 `read_timeout`/`write_timeout` 提到 **15 分钟**（原 30 秒），长轮询不再被超时打断。

## DNS 调试（无需 SDK）

```bash
dig @127.0.0.1 -p 8600 web.service.consul      # A 记录：健康实例
dig @127.0.0.1 -p 8600 web.service.consul SRV   # 含端口
dig @127.0.0.1 -p 8600 node.consul ANY          # 节点
```

把 `/etc/resolv.conf` 的 nameserver 指向 Consul agent 即可让业务零改造接入——这是 Consul 接入友好度的核心。

## HTTP API（curl）

```bash
curl localhost:8500/v1/catalog/services          # 全量服务列表
curl "localhost:8500/v1/health/service/web?passing"
curl localhost:8500/v1/kv/mykey?raw              # 读 KV
curl -X PUT localhost:8500/v1/kv/mykey -d 'val' # 写 KV
curl localhost:8500/v1/status/leader            # 当前 leader
```

读写需带 `X-Consul-Token` 头（ACL 开启后，见 [Security](/docs/CS/Framework/consul/security.md)）。

## CLI

```bash
consul members            # 集群成员（gossip 视角）
consul info               # 本 agent 运行时信息
consul kv get/put/delete  # KV 操作
consul catalog services   # 服务目录
consul operator raft list-peers   # Raft peer 集
consul snapshot save/restore <f>  # 快照（见 Cluster）
```

## 服务注册与检查

服务可在 agent 配置文件声明，或用 API/SDK 动态注册：

```json
{
  "service": {
    "name": "web",
    "port": 8080,
    "check": { "http": "http://localhost:8080/health", "interval": "10s" }
  }
}
```

检查失败会自动从 DNS / 健康查询剔除（[Discovery](/docs/CS/Framework/consul/discovery.md) 的健康检查段）。Sidecar（Envoy）注册还会占用 `21000–21255` 自动分配端口。

## 与 etcd clientv3 对照

| 维度 | Consul client | etcd clientv3 |
| :--- | :--- | :--- |
| 接入 | DNS / HTTP / gRPC / CLI | gRPC |
| 服务发现 | 原生 DNS + 健康过滤 | 无（需自拼） |
| KV 监听 | 阻塞查询（无历史） | watch（按 revision） |
| 锁 | session + `acquire` | lease + txn |
| 多语言 | HTTP/DNS 通用，go SDK 官方 | 各语言 gRPC SDK |

Consul 的"通用协议接入"让非 Go 技术栈、甚至无 SDK 的遗留系统都能用；etcd 则更适合"强一致 KV + 历史监听"的协调场景。选型见 [etcd 横向对照](/docs/CS/Framework/etcd/compare.md)。

## Links

- [Consul（架构与启动流程）](/docs/CS/Framework/consul/Consul.md)
- [KV（存储）](/docs/CS/Framework/consul/kv.md)
- [Discovery（服务发现）](/docs/CS/Framework/consul/discovery.md)
- [Security（安全）](/docs/CS/Framework/consul/security.md)
- [etcd client](/docs/CS/Framework/etcd/client.md)
- [Spring Cloud Consul](/docs/CS/Framework/Spring_Cloud/Consul.md)

## References

1. [Consul API Docs](https://developer.hashicorp.com/consul/api-docs)
2. [Consul Go Client (api)](https://github.com/hashicorp/consul/tree/main/api)
3. [Consul CLI](https://developer.hashicorp.com/consul/docs/commands)
