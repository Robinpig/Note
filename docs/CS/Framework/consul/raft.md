## Introduction

Consul 把全局状态（catalog、KV、ACL、服务网格证书）的一致性交给 **Raft** 保证，但 Raft 只在 **server agent** 之间运行——client agent 不参与投票，只把写请求转发给 server。这与 etcd（etcd-raft）、Nacos（JRaft）是同类机制，但 Consul 额外叠加了 HashiCorp 的 **Autopilot** 来自动化 Raft 运维，并配合 Serf 做成员发现（见 [Serf](/docs/CS/Framework/consul/serf.md)）。

> [!NOTE]
> 版本事实：2.0.x 当前主线（2.0.4，2026-09-09；2.0 分支 2026-05-24 GA），维护线 1.22.x / 1.21.x。Raft 相关参数自 1.x 起稳定，下文默认值以 1.21+/2.0 为准。

## 角色与选举

- Consul server 内部维护一个标准 Raft 状态机：一个 **leader** 负责处理所有写（服务注册、KV 写、ACL 变更、connect CA 操作），follower 复制日志并响应读。
- Leader 选举依赖 `raft_protocol`（Raft 协议版本，v3 起支持 `server_stabilization_time` 等 Autopilot 特性）。新 server 加入后需先通过 Autopilot 的**稳定期**才能成为 voting member。
- 集群规模建议 **3 或 5** 个 server（奇数，容忍 `(n-1)/2` 故障）；不要为"高可用"堆到 7+，会拖慢提交。

## 持久化：LogStore 与 SnapshotStore

server 的状态以 **WAL（append-only 轮转日志，LogStore）+ 快照（SnapshotStore）** 持久化在 `-data-dir`。关键参数：

| 参数 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `raft_snapshot_threshold` | **16384**（自 1.1.0；更早为 8192） | 两次快照间最少 Raft 提交条目数；调大可减少磁盘 IO 但拉长恢复 replay |
| `raft_snapshot_interval` | 默认约 5s（由 raft 内部节拍决定） | server 周期性检查是否该落快照 |
| `raft_multiplier` | **5** | 把 Raft 节拍按倍数缩放，调小更激进（更快心跳/选举，吃 CPU），调大更省心跳 |

快照与日志均存于 `-data-dir` 下的 `raft/` 子目录；WAL 与快照建议放低延迟磁盘（见 [Tuning](/docs/CS/Framework/consul/tuning.md)）。**WAN 各 DC 独立一套 Raft**，互不复用日志。

## Autopilot：自动化 Raft 运维

Autopilot（1.4+ 通用，部分特性仅 Enterprise）降低运维误操作风险。默认配置（来自 `/v1/operator/autopilot/configuration`）：

| 参数 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `cleanup_dead_servers` | **true** | 周期性 + 新 server 加入时自动移除死节点 |
| `last_contact_threshold` | **200ms** | server 超过该时长未与 leader 联系即判不健康 |
| `max_trailing_logs` | **250** | 落后 leader 超过该日志数即判不健康（不提升为 voter） |
| `min_quorum` | 0（无默认） | 低于该健康 server 数时 Autopilot 停止清理死节点 |
| `server_stabilization_time` | **10s** | 新 server 需持续健康该时长才成为 voting member |

> [!TIP]
> `max_trailing_logs` 默认只有 **250**——慢 server（磁盘 IO 差、网络抖动）容易"落后超限"被长期挡在投票圈外，表现为 `FailureTolerance` 下降、`/v1/operator/autopilot/health` 中 `Healthy=false`。这类问题优先查磁盘与跨 AZ 延迟，而非盲目加节点。

### 健康检查与升级就绪

leader 周期性对每个 server 跑内部健康检查，判定条件：

1. Serf 状态为 `alive`；
2. 距上次与 leader 联系 < `last_contact_threshold`（200ms）；
3. 本节点 Raft term 与 leader 一致；
4. 落后日志数 ≤ `max_trailing_logs`（250）。

`/v1/operator/autopilot/health` 返回 `Healthy`、`FailureTolerance`（还能丢几个 server）、各 server 的 `Voter` / `Healthy`。Enterprise 还有 `RedundancyZoneTag`（冗余区，每区最多一个 voter）与自动升级迁移（`DisableUpgradeMigration`）。

### 配置生效方式

Autopilot 参数仅在**引导期**从配置文件读取；引导后修改必须用 `consul operator autopilot set-config` 或 `PUT /v1/operator/autopilot/configuration`，且配置会存入 Raft 数据库——意味着它**包含在 `consul snapshot` 里**，跨 DC 各 DC 独立。

## 与 etcd / ZooKeeper / Nacos 对照

| 维度 | Consul | etcd | ZooKeeper | Nacos |
| :--- | :--- | :--- | :--- | :--- |
| 共识 | Raft（仅 server） | etcd-raft | Zab | JRaft（配置侧） |
| 成员发现 | Serf gossip | 无（静态 peer） | 无（静态 peer） | Distro / Raft |
| 自动化运维 | Autopilot | 需外部 operator | 需手动 | 需手动 |
| 线性一致读开关 | 不暴露（KV 默认走 Raft，目录可 stale） | linearizable / serializable | sync() 强制 | 配置默认 CP |
| 多数据组 | 每 DC 独立 Raft | 单 Raft 组 | 单 Zab 组 | 单 JRaft 组（可分片） |

Consul 把"成员发现"与"共识"拆成两套协议是最显著的架构差异：Raft 管状态一致，Serf 管"谁还活着、谁新加入"，二者解耦让扩缩 server、跨 DC 联邦都更平滑。代价是运维面比 etcd（单二进制、静态 peer）宽——要同时看护 Raft 与 gossip 两套通道（见 [Troubleshooting](/docs/CS/Framework/consul/troubleshooting.md)）。

## Links

- [Consul（架构与启动流程）](/docs/CS/Framework/consul/Consul.md)
- [Serf（成员发现）](/docs/CS/Framework/consul/serf.md)
- [Troubleshooting（故障排查）](/docs/CS/Framework/consul/troubleshooting.md)
- [Cluster（集群运维）](/docs/CS/Framework/consul/cluster.md)
- [Tuning（调优）](/docs/CS/Framework/consul/tuning.md)
- [etcd 横向对照](/docs/CS/Framework/etcd/compare.md)

## References

1. [Consul Consensus Protocol (Raft)](https://developer.hashicorp.com/consul/docs/concept/consul-internals/consensus)
2. [Consul Autopilot](https://developer.hashicorp.com/consul/docs/guides/autopilot)
3. [Autopilot Operator HTTP API](https://developer.hashicorp.com/consul/api-docs/operator/autopilot)
