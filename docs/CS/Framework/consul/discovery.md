## Introduction

服务发现是 Consul 最核心的能力。服务注册并附带健康检查后，消费方有三种接入入口：**DNS**（无需 SDK，普通 `dig` 即可）、**HTTP API**、以及本地 **agent 缓存的 stale 读**。这比 etcd（必须 gRPC 客户端，见 [etcd client](/docs/CS/Framework/etcd/client.md)）和 ZooKeeper（Jute 私有协议）对业务更友好——也是 Consul "零改造接入"的来源。

## DNS Interface

Consul 内置 DNS 服务器（端口 `8600`，TCP+UDP），默认域为 `consul`：

- `<service>.service.consul`：返回健康实例的 A/AAAA 记录（多实例时随机/按网络坐标就近返回）；
- `<service>.service.<dc>.consul`：限定数据中心；
- `<node>.node.consul`：按节点名解析；
- `<query>.query.consul`：prepared query（带过滤逻辑的命名查询，见下）；
- SRV 记录还能返回端口。

业务容器只需把 `/etc/resolv.conf` 的 nameserver 指向 Consul agent（或经 `recursors` 上游转发），即可用标准 DNS 做服务发现，完全不需要 SDK。这是 Consul 相对 etcd 最大的接入友好度差异。

## HTTP API

| 端点 | 视角 | 用途 |
| :--- | :--- | :--- |
| `/v1/catalog/...` | 全量目录（server 权威） | 列出所有节点/服务，不含健康检查过滤 |
| `/v1/health/...` | 带健康过滤 | `health/service/<svc>` 只返回 passing 实例；支持 `passing`、`near`、`tag` |
| `/v1/agent/...` | 本 agent 视角 | 注册/反注册本节点服务、读本节点已知信息 |
| `/v1/agent/health` | 本 agent 健康检查 | 本地健康状态，不依赖 leader |

`/v1/health/service/<svc>?passing` 是服务发现最常用的查询——自动剔除检查失败实例，流量不再路由到它。

## Health Check

服务可挂多种检查，失败即从 DNS / 健康查询剔除：

- `script`：agent 周期性执行脚本（默认关闭，需显式 `enable_script_checks=true`，建议配合 ACL）；
- `http`：GET 指定 URL，按状态码判健康；
- `tcp`：尝试建立 TCP 连接；
- `grpc`：gRPC 健康检查协议；
- `ttl`：服务自己周期性 `PUT /v1/agent/check/pass|<id>`，超时未报则判失败（适合业务自证健康）。

> [!TIP]
> 检查失败只影响"发现结果"，**不自动重启/隔离进程**。需要自愈（如从负载摘除）要配合服务网格或外部编排。反熵（anti-entropy）由 agent 周期性把本地注册状态同步到 catalog（见 [Serf](/docs/CS/Framework/consul/serf.md)）。

## Agent Cache and Stale Reads

client agent 默认缓存 catalog 结果，本地查询走缓存——可用性高、但可能短暂陈旧（stale）。需要强一致时：

- 显式请求 leader 读（带一致性参数 `?consistent`，绕过缓存、强制走 leader）；
- 或接受 stale（默认）。

对比 etcd 的 `linearizable` / `serializable` 双读模型（[etcd read](/docs/CS/Framework/etcd/read.md)）——Consul 把"默认 AP 式可用"作为发现主路径，把强一致作为可选项，定位更偏"发现优先于严格一致"。

## Prepared Query (Named Query)

prepared query 是**带过滤逻辑的命名查询**：预先存好"查某服务 + 某 tag + 某数据中心 + 失败 fallback 到邻近 DC"的规则，业务用 `<query>.query.consul` 调用。适合把复杂发现逻辑（如多 DC 就近 failover）沉淀成可复用名字，而不是每个客户端写一堆过滤参数。

## Blocking Query

HTTP 带 `index` + `wait` 做长轮询（详见 [KV](/docs/CS/Framework/consul/kv.md) 的阻塞查询段）。服务列表 / 健康状态变更时服务端唤醒返回，省去客户端轮询。注意 Consul 不保留历史 revision，阻塞查询只给"当前最新状态 + 触发索引"，回溯需客户端自维护游标。

## Links

- [Consul（架构与启动流程）](/docs/CS/Framework/consul/Consul.md)
- [KV（存储）](/docs/CS/Framework/consul/kv.md)
- [Serf（成员发现）](/docs/CS/Framework/consul/serf.md)
- [Client（客户端）](/docs/CS/Framework/consul/client.md)
- [Mesh（服务网格）](/docs/CS/Framework/consul/mesh.md)
- [etcd client](/docs/CS/Framework/etcd/client.md)

## References

1. [Consul Service Discovery](https://developer.hashicorp.com/consul/docs/discovery)
2. [Consul Health Checks](https://developer.hashicorp.com/consul/api-docs/health)
3. [Consul DNS](https://developer.hashicorp.com/consul/docs/discovery/dns)
4. [Consul Prepared Query](https://developer.hashicorp.com/consul/api-docs/query)
