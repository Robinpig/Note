## Introduction

本篇给 Consul server / client 的调优清单，对标 etcd 的 [tuning](/docs/CS/Framework/etcd/tuning.md)。多数默认值已足够生产，下面列出**真正值得调**的项及其权衡。

## Raft Related

| 参数 | 默认 | 调优建议 |
| :--- | :--- | :--- |
| `raft_multiplier` | **5** | 把 Raft 节拍（心跳/选举超时）按倍数缩放。调小（如 1）更激进、故障切换更快，但吃更多 CPU/网络；跨高延迟 DC 可调大降低心跳开销 |
| `raft_snapshot_threshold` | **16384**（1.1.0+） | 两次快照间最少提交条目。繁忙集群 IO 高可调大（减快照频率），但恢复 replay 更长、raft.db 更占空间 |
| `raft_snapshot_interval` | 内部节拍（约 5s 一检） | 一般不动；与 threshold 共同决定快照频率 |

`-data-dir` 必须放**低延迟磁盘**（WAL 同步写），且目录需支持文件锁（VirtualBox 共享盘不合适）。WAL 与快照同目录，建议单独挂载 SSD。

## Serf / gossip

- 跨可用区 / 高延迟网络调 `serf_lan` 重传参数，降低误 suspicion；
- WAN 池只在多 DC 启用；单 DC 可设 `serf_wan=-1`（会禁用 WAN 联邦，不推荐除非确不需要）；
- gossip 对延迟敏感：同 DC RTT 控在平均 <50ms / p99 <100ms，否则 server 被反复移出投票圈（[Serf](/docs/CS/Framework/consul/serf.md)）。

## Encryption and Certificates

- `encrypt`（gossip keyring）首次启动提供一次即可，后续自动加载；需轮转用 `consul keyring` 多密钥流程；
- 生产启用 `auto_encrypt`（agent 自动向 server 要 TLS）或手工分发 cert；**注意 `auto_config` 与 `auto_encrypt.tls` 不能同时开**；
- gRPC xDS 优先用 `8503`（TLS）而非明文 `8502`。

## ACL Cache

- `acl.policy_ttl` / `role_ttl` / `token_ttl` 默认 **30s**——缓存不主动失效，ACL 变更最多 30s 后生效；
- 调小（如 10s）变更更及时但增刷新压力；调大减压力但 ACL 收敛慢；
- `acl.down_policy` 默认 `extend-cache`：主 DC 不可达时复用缓存，避免全拒。

## Resource Sizing

- 官方建议 ≥2 核；RAM 约为**工作集的 2–4 倍**（catalog / KV / 会话越多越吃内存）；
- 写等多数节点落盘同步；读吃 CPU 与内存；
- 监控 `consul_runtime_alloc_bytes` 与 goroutine，防泄漏；
- sidecar（Envoy）按业务 QPS 预留资源（[Mesh](/docs/CS/Framework/consul/mesh.md)）。

## Client Cache (Reduce Server Pressure)

- 读多写少、可容忍短暂陈旧的发现场景，开 agent 缓存（默认开启，走 stale 读）；
- 需要强一致时显式 `?consistent` 或 SDK `AllowStale=false`。

## HTTP Timeout (2.0 Change)

- 2.0.0 起 agent 默认 `read_timeout` / `write_timeout` 提到 **15 分钟**（原 30 秒），避免长轮询阻塞查询被超时打断；`read_header_timeout`（10s）与 `idle_timeout`（120s）仍防 Slowloris；
- 均由 `http_config` 块可调，无需为长轮询单独 hack。

## Server Count Principle

- 3（小集群）或 5（生产）；**不要为"高可用"堆到 7+**——更多 voter 拖慢 Raft 提交、放大快照广播；
- 跨机房容错靠**多 DC 联邦**（[Gateway](/docs/CS/Framework/consul/gateway.md)），而非单 DC 加 server。

## Tuning Comparison with etcd

| 项 | Consul | etcd |
| :--- | :--- | :--- |
| 心跳/选举节奏 | `raft_multiplier` | `heartbeat-interval`/`election-timeout` |
| 快照频率 | `raft_snapshot_threshold`(16384) | `--snapshot-count`(100000 Raft 层) |
| 客户端缓存 | agent stale 读（默认） | `--consistency` serializable |
| 多 DC | WAN 联邦 / mesh gateway | 外部复制 |

## Links

- [Consul（架构与启动流程）](/docs/CS/Framework/consul/Consul.md)
- [Raft（共识）](/docs/CS/Framework/consul/raft.md)
- [Serf（成员发现）](/docs/CS/Framework/consul/serf.md)
- [Security（安全）](/docs/CS/Framework/consul/security.md)
- [Cluster（集群运维）](/docs/CS/Framework/consul/cluster.md)
- [etcd tuning](/docs/CS/Framework/etcd/tuning.md)

## References

1. [Consul Agent Configuration (raft)](https://developer.hashicorp.com/consul/docs/reference/agent/configuration-file/raft)
2. [Consul Performance](https://developer.hashicorp.com/consul/docs/guides/performance)
3. [Consul Reference Architecture](https://developer.hashicorp.com/consul/docs/guides/deployment)
