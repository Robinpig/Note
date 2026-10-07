## Introduction

Consul 的运维可观测性来自 **telemetry**（指标导出）+ **健康检查端点** + **agent 缓存**。本篇给出关键指标表与告警项，对标 etcd 的 [monitoring](/docs/CS/Framework/etcd/monitoring.md)。

## Telemetry Export

- 两种后端：**statsd**（push，默认）与 **prometheus**（pull，推荐）。Prometheus 通过 agent 的 `/v1/agent/metrics?format=prometheus` 暴露（1.4+ 通用，当前 2.0 默认启用该端点）。
- 配置：`telemetry { prometheus_retention_time = "24h" }` 控制本地缓存时长；`metrics_prefix` 可改前缀（默认 `consul`）。

## Key Metrics Table

| 指标前缀 | 关注点 | 告警建议 |
| :--- | :--- | :--- |
| `consul_raft_*` | `raft_commitTime`（提交延迟）、`raft_leader_lastContact`（leader 最近联系，应 < `last_contact_threshold` 200ms）、`raft_state`（leader/follower）、`raft_fsm_*` | leader 切换频繁、commitTime 持续高 → 查磁盘 / 网络 |
| `consul_serf_*` / `consul_memberlist_*` | `serfLAN_members` / `serfWAN_members`（成员数）、`memberlist_probe`（探测耗时）、`memberlist_degraded` | 成员数骤减、probe 耗时超 RTT 预算 → gossip 分区 |
| `consul_catalog_*` | `catalog_nodes`（节点数）、`catalog_services`（服务数）、`catalog_service_node_healthy`（健康实例数） | 健康实例归零 → 检查失败导致流量被摘除 |
| `consul_http_*` | `http_request_duration_seconds`（API 延迟）、`http_request_total`（按 status 分） | 5xx 升高、P99 超阈值 |
| `consul_runtime_*` | `runtime_alloc_bytes`、`runtime_num_goroutines`、`runtime_gc_pause_ns` | 内存持续增长 / goroutine 泄漏 |
| `consul_server_*` | `consul_server_is_leader`（1=leader）、`consul_server_bootstrap`（异常为 1） | leader 频繁易主 |
| `consul_autopilot_*` | `consul_autopilot_failure_tolerance`（还能丢几个 server） | `FailureTolerance` 下降预警 |

> [!TIP]
> 真正反映"集群还能不能写"的是 `consul_server_is_leader` + `consul_autopilot_failure_tolerance` + `raft_leader_lastContact`。绿灯（health 页 200）不等于能写——务必监控这三个而非只看存活。

## Health Check Endpoint

| 端点 | 用途 | ACL |
| :--- | :--- | :--- |
| `/v1/status/leader` | 当前 leader 地址，空表示无主 | 无 |
| `/v1/operator/autopilot/health` | 整体 `Healthy`、各 server `Voter`/`Healthy`、`FailureTolerance` | `operator:read` |
| `/v1/agent/health` | 本 agent 健康（不依赖 leader） | 无 |
| `/v1/status/peers` | Raft peer 列表 | 无 |

2.0 起健康检查语义沿用：写路径依赖 leader，读（目录）可走本地 stale。

## Agent Cache

client agent 缓存 catalog / health 结果（[Discovery](/docs/CS/Framework/consul/discovery.md) 的 stale 读）。缓存降低 server 压力，但 ACL 缓存受 `acl.*_ttl`（默认 30s）约束——ACL 变更最多 30s 后生效。监控 agent 的缓存命中与反熵同步延迟可提前发现"发现结果陈旧"。

## Suggested Alert Items

1. **无 leader / leader 频繁易主**：写不可用，查 [Raft](/docs/CS/Framework/consul/raft.md) 与磁盘 IO。
2. **`FailureTolerance` 下降**：有 server 被 Autopilot 挡在投票圈外（常因 `max_trailing_logs` 超限），查慢节点。
3. **gossip 成员数突变 / probe 超时**：[Serf](/docs/CS/Framework/consul/serf.md) 分区，查跨 AZ RTT。
4. **健康实例数归零**：检查配置错误导致批量失败，流量被全摘。
5. **内存 / goroutine 持续增长**：可能泄漏，配合 snapshot 体积一起看。

## Links

- [Consul（架构与启动流程）](/docs/CS/Framework/consul/Consul.md)
- [Raft（共识）](/docs/CS/Framework/consul/raft.md)
- [Serf（成员发现）](/docs/CS/Framework/consul/serf.md)
- [Troubleshooting（故障排查）](/docs/CS/Framework/consul/troubleshooting.md)
- [Tuning（调优）](/docs/CS/Framework/consul/tuning.md)
- [etcd monitoring](/docs/CS/Framework/etcd/monitoring.md)

## References

1. [Consul Telemetry](https://developer.hashicorp.com/consul/docs/observability/telemetry)
2. [Consul Metrics](https://developer.hashicorp.com/consul/docs/observability/metrics)
3. [Consul Health Checks (agent)](https://developer.hashicorp.com/consul/api-docs/agent/check)
