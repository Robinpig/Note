## Introduction

Consul 的**网关**与**多数据中心联邦**是它"跨机房原生"能力的落地。etcd 是单一 Raft 组、跨 DC 需外部复制；ZooKeeper 无跨 DC 概念；Consul 则把 mesh gateway / WAN federation 做成一等能力。本篇覆盖四种网关与两种联邦形态。

## Mesh Gateway (Service Mesh Cross-DC)

mesh gateway 让跨数据中心的服务网格流量走 WAN，而**不必把每个 sidecar 暴露到公网**：

- 部署在 DC 边界，作为进出本 DC 的网格流量汇聚点；
- 两种模式（[mesh](/docs/CS/Framework/consul/mesh.md) 的 xDS 由它中继）：
  - **local 模式**：本 DC 的 sidecar 先把流量发到本地 mesh gateway，再由本地 gateway 转发到远端 gateway（远端也落地到 local gateway，再到目标 sidecar）；
  - **remote 模式**：sidecar 直连远端 mesh gateway（需网络可达）；
- WAN federation **用 mesh gateway 时**：server 只接受来自本地 mesh gateway 的 WAN Serf（8302）与 Server RPC（8300）流量，入站永远经由本地 gateway——更安全。

## Ingress Gateway (North-South Inbound)

ingress gateway 把**外部流量引入**服务网格：经典场景是"公网 / 外部调用方 → ingress gateway → 网格内服务"，统一走 mTLS + 意图校验。与 API gateway 区别：ingress 偏"进网格"，API gateway 偏"对外暴露北向 API + L7 路由"。

## Terminating Gateway (Egress to External)

terminating gateway 让网格内服务**安全访问网格外的存量系统**（如未接入 Consul 的传统数据库、第三方 API）：由 gateway 代理出站、统一 TLS 与 ACL，存量系统无需改造。2.0 起其上游 TLS 改为 SDS 动态证书，可热更新无需重启。

## API Gateway (Northbound L7)

Consul 自带 **API gateway**（与主线同版本发布，非独立组件）：对外暴露北向 HTTP/TCP API，支持 L7 路由、TLS（2.0 起支持 listener 级 SDS 证书 + 路由级 SDS 覆盖）、限流（Enterprise 有 `rate-limit` 配置项做全局 RPC 限流）。可与 `service-router` / `service-splitter` 联动做金丝雀。2.0.3/2.0.4 修复了 api-gateway / terminating-gateway 的路径规范化（CVE-2024-10005，防 L7 意图 RBAC 绕过）。

## WAN Federation: Two Forms

跨 DC 联邦本质是把各 DC 的 catalog 连通，两种实现：

| 形态 | 机制 | 入站来源 | 适用 |
| :--- | :--- | :--- | :--- |
| **WAN gossip 联邦** | server 间 `serf_wan`（8302）直连 | 各 DC server 互访 8302/8300 | 网络扁平、DC 间可直接互通 |
| **Mesh gateway 联邦** | `primary_gateways` 发现本地 gateway，流量经 gateway | 永远来自本地 mesh gateway | 跨云 / 公网 / 网络隔离 |

- `primary_datacenter`：权威 DC，持有 ACL 与 connect CA 根；所有 DC 必须就此达成一致（[Security](/docs/CS/Framework/consul/security.md) 详述）。
- `primary_gateways`：从属 DC 用来发现主 DC mesh gateway 的地址列表，配合 `primary_gateways_interval`（默认 30s）周期性发现。
- 各 DC 是**独立 Raft 组 + 独立 catalog**；数据**不**自动跨 DC 复制。目录读默认本地（stale），跨 DC 查询经 `/v1/catalog/datacenters` 聚合或 gateway 转发。

> [!TIP]
> 与 etcd 对比：etcd 跨数据中心需要外部异步复制（如机架间、集群间），Consul 把"多活 DC + 就近 failover"做成一等能力。代价是 Consul 的跨 DC 一致性弱——各 DC 自己一致，不保证全局线性（见 [Consul](/docs/CS/Framework/consul/Consul.md) 多数据中心段）。

## Links

- [Consul（架构与启动流程）](/docs/CS/Framework/consul/Consul.md)
- [Mesh（服务网格）](/docs/CS/Framework/consul/mesh.md)
- [Serf（成员发现）](/docs/CS/Framework/consul/serf.md)
- [Security（安全）](/docs/CS/Framework/consul/security.md)
- [Cluster（集群运维）](/docs/CS/Framework/consul/cluster.md)
- [etcd 横向对照](/docs/CS/Framework/etcd/compare.md)

## References

1. [Consul Mesh Gateways](https://developer.hashicorp.com/consul/docs/connect/gateways/mesh-gateway)
2. [Consul Ingress Gateways](https://developer.hashicorp.com/consul/docs/connect/gateways/ingress-gateway)
3. [Consul Terminating Gateways](https://developer.hashicorp.com/consul/docs/connect/gateways/terminating-gateway)
4. [Consul API Gateway](https://developer.hashicorp.com/consul/docs/api-gateway)
5. [Consul WAN Federation](https://developer.hashicorp.com/consul/docs/connect/federation)
