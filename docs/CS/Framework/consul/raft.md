## Introduction

Consul 把全局状态（catalog、KV、ACL、服务网格证书）的一致性交给 **Raft** 保证，但 Raft 只在 **server agent** 之间运行——client agent 不参与投票，只把写请求转发给 server。这与 etcd（etcd-raft）、Nacos（JRaft）是同类机制，但 Consul 额外叠加 **Autopilot** 自动化 Raft 运维，并配合 Serf 做成员发现（见 [Serf](/docs/CS/Framework/consul/serf.md)）。本文源码核自 **v2.1.0**。

> [!WARNING]
> 2.x 关键变化：① Raft 日志存储新增 **WAL 后端**（`raft-wal`），全新数据目录默认用 WAL 并开启日志校验；旧 `raft.db` 存在时自动回退 BoltDB。② Autopilot 核心循环**外置为独立库** `hashicorp/raft-autopilot`，`agent/consul/autopilot.go` 只剩 delegate 与装配。③ 一致性读统一收进 `agent/blockingquery` 包，`inconsistentLeaderCheck` 已不存在。

## Setup: LogStore, SnapshotStore and Bootstrap

`setupRaft` 在 `agent/consul/server.go`。日志后端选择逻辑是理解 2.x 存储的第一步：

```go
		// Only use WAL if there is no existing raft.db, even if it's enabled.
		if s.config.LogStoreConfig.Backend == LogStoreBackendDefault && !boltFileExists {
			s.config.LogStoreConfig.Backend = LogStoreBackendWAL
			if !s.config.LogStoreConfig.Verification.Enabled {
				s.config.LogStoreConfig.Verification.Enabled = true
				s.config.LogStoreConfig.Verification.Interval = 1 * time.Minute
			}
			if err = initWAL(); err != nil {
				return err
			}
		} else if s.config.LogStoreConfig.Backend == LogStoreBackendWAL && !boltFileExists {
			if err = initWAL(); err != nil {
				return err
			}
		} else {
			if s.config.LogStoreConfig.Backend == LogStoreBackendWAL {
				// User configured the new storage, but still has old raft.db. Warn
				// them!
				s.logger.Warn("BoltDB file raft.db found, IGNORING raft_logstore.backend which is set to 'wal'")
			}
			s.config.LogStoreConfig.Backend = LogStoreBackendBoltDB
			// Create the backend raft store for logs and stable storage.
			store, err := raftboltdb.New(raftboltdb.Options{
				BoltOptions: &bbolt.Options{
					NoFreelistSync: s.config.LogStoreConfig.BoltDB.NoFreelistSync,
				},
				Path: boltDBFile,
			})
```

`agent/consul/server.go`

要点：WAL 目录为 `-data-dir/raft/wal`，BoltDB 文件为 `raft/raft.db`；选 WAL 时自动开启每分钟一次的**日志校验**（`raft-wal/verifier`，检测日志损坏）。之后 LogStore 包一层内存 `raft.NewLogCache(512, log)` 提升follower 追日志性能，快照走 `raft.NewFileSnapshotStoreWithLogger(path, 2, ...)`（保留 2 份快照）。

关键默认值（`agent/consul/config.go`）：

```go
	// Check every 5 seconds to see if there are enough new entries for a snapshot, can be overridden
	conf.RaftConfig.SnapshotInterval = 30 * time.Second

	// Snapshots are created every 16384 entries by default, can be overridden
	conf.RaftConfig.SnapshotThreshold = 16384
```

`agent/consul/config.go`

节拍参数不在 Consul 侧硬编码，而是 `raft.DefaultConfig()` 基准值（选举 1s / 心跳 1s / leader lease 500ms）乘以 `performance.raft_multiplier`（默认 5，上限 10）后注入：

```go
	consulRaftElectionTimeout := b.durationVal("consul.raft.election_timeout", c.Consul.Raft.ElectionTimeout) * time.Duration(performanceRaftMultiplier)
	consulRaftHeartbeatTimeout := b.durationVal("consul.raft.heartbeat_timeout", c.Consul.Raft.HeartbeatTimeout) * time.Duration(performanceRaftMultiplier)
	consulRaftLeaderLeaseTimeout := b.durationVal("consul.raft.leader_lease_timeout", c.Consul.Raft.LeaderLeaseTimeout) * time.Duration(performanceRaftMultiplier)
```

`agent/config/builder.go`

依赖版本（`go.mod`）：`hashicorp/raft v1.8.0`、`raft-boltdb/v2 v2.4.2`、`raft-wal v0.5.0`、`raft-autopilot v0.1.6`。

### Bootstrap

`bootstrap_expect` 的自动引导不发生在 `setupRaft`，而是在 serf 事件处理里：每有 server 加入 LAN，`maybeBootstrap` 检查 voter 数是否达标，达标即 `raft.BootstrapCluster`：

```go
	// Skip if we haven't met the minimum expect count.
	if voters < s.config.BootstrapExpect {
		return
	}
	...
	future := s.raft.BootstrapCluster(configuration)
	if err := future.Error(); err != nil {
		s.logger.Error("Failed to bootstrap cluster", "error", err)
	}
```

`agent/consul/server_serf.go`

Quorum 丢失后的恢复走 `peers.json`：`setupRaft` 启动时检测该文件并 `raft.ReadConfigJSON` 强制重置集群配置。

## Write Path: Apply and FSM

所有写端点（如 `Catalog.Register`）先 `ForwardRPC` 把写请求转给 leader（2.x 的 leader 转发统一为 `ForwardRPC`，内部 `forwardRequestToLeader`，等价旧版 VerifyLeader 语义），leader 上经 `raftApply` 编码为 MessagePack 后提交：

```go
func (s *Server) raftApplyEncoded(t structs.MessageType, buf []byte) (any, error) {
	// Warn if the command is very large
	if n := len(buf); n > raftWarnSize {
		s.rpcLogger().Warn("Attempting to apply large raft entry", "size_in_bytes", n)
	}

	var chunked bool
	var future raft.ApplyFuture
	switch {
	case len(buf) <= raft.SuggestedMaxDataSize || t != structs.KVSRequestType:
		future = s.raft.Apply(buf, enqueueLimit)
	default:
		chunked = true
		future = raftchunking.ChunkingApply(buf, nil, enqueueLimit, s.raft.ApplyLog)
	}
	...
}
```

`agent/consul/rpc.go`

两个细节：① 大于 `SuggestedMaxDataSize` 的 KV 写走 `raftchunking.ChunkingApply` 分片提交（单条 Raft 日志有大小上限）；② 入队等待上限 `enqueueLimit = 30s`。FSM 外层包着 `ChunkingFSM` + 日志校验 shim，`Apply` 按命令注册表分发（见枢纽页），最终落到 memdb state store 的事务写。

## Read Consistency

三档读一致性（详见枢纽页 Read Path）中，consistent 模式在 v2.1.0 的实现是 `VerifyLeader` + 就绪轮询：

```go
func (s *Server) consistentReadWithContext(ctx context.Context) error {
	defer metrics.MeasureSince([]string{"rpc", "consistentRead"}, time.Now())
	future := s.raft.VerifyLeader()
	if err := future.Error(); err != nil {
		return err // fail fast if leader verification fails
	}

	if s.isReadyForConsistentReads() {
		return nil
	}
	// Poll until the context reaches its deadline, or for RPCHoldTimeout if the
	// context has no deadline.
	...
}
```

`agent/consul/rpc.go`

stale 读的准入判断则简单得多——本机 raft 曾与 leader 有过联系即可：

```go
// canServeReadRequest determines if the request is a stale read request and
// the current node can safely process that request.
func (s *Server) canServeReadRequest(info structs.RPCInfo) bool {
	// Check if we can allow a stale read, ensure our local DB is initialized
	return info.IsRead() && info.AllowStaleRead() && !s.raft.LastContact().IsZero()
}
```

`agent/consul/rpc.go`

注意：**KV 写本身走 Raft 线性化，但目录/KV 读默认并不强制线性一致**——想读"刚刚写"的结果必须显式 `?consistent`，或用 agent cache 的 `?cached` 换取可用性。

## Autopilot

2.x 中 Autopilot 的核心循环（稳定 server 判定、死节点清理、`MaxTrailingLogs` 检查、promoter 策略）已外置为 `hashicorp/raft-autopilot` 库，Consul 仓库只保留 delegate 与装配：

```go
	s.autopilot = autopilot.New(
		s.raft,
		apDelegate,
		autopilot.WithLogger(s.logger),
		autopilot.WithReconcileInterval(config.AutopilotInterval),
		autopilot.WithUpdateInterval(config.ServerHealthInterval),
		autopilot.WithPromoter(s.autopilotPromoter()),
		autopilot.WithReconciliationDisabled(),
	)
```

`agent/consul/autopilot.go`

默认策略（`agent/consul/config.go`，与 1.x 一致）：

| 参数 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `cleanup_dead_servers` | **true** | 自动移除死节点 |
| `last_contact_threshold` | **200ms** | 超 200ms 未与 leader 联系即不健康 |
| `max_trailing_logs` | **250** | 落后超 250 条日志即不健康 |
| `server_stabilization_time` | **10s** | 新 server 需持续健康 10s 才成 voter |
| `AutopilotInterval` | 10s | 对账周期 |
| `ServerHealthInterval` | 2s | 健康采样周期 |

> [!TIP]
> `max_trailing_logs` 默认只有 **250**——慢 server（磁盘 IO 差、跨 AZ 延迟）容易被长期挡在投票圈外，表现为 `/v1/operator/autopilot/health` 中 `Healthy=false`、`FailureTolerance` 下降。优先查磁盘与网络延迟，而非盲目加节点。

死节点清理的执行回调仍在 Consul 侧：

```go
func (d *AutopilotDelegate) RemoveFailedServer(srv *autopilot.Server) {
	serverEntMeta := structs.DefaultEnterpriseMetaInDefaultPartition()
	go func() {
		if err := d.server.RemoveFailedNode(srv.Name, false, serverEntMeta); err != nil {
			d.server.logger.Error("failed to remove server", "name", srv.Name, "id", srv.ID, "error", err)
		}
	}()
}
```

`agent/consul/autopilot.go`

Autopilot 配置存入 Raft（引导期可从文件读，之后必须 `consul operator autopilot set-config`），因此**包含在 snapshot 里**，跨 DC 各自独立。

## Comparison with etcd / ZooKeeper / Nacos

| 维度 | Consul | etcd | ZooKeeper | Nacos |
| :--- | :--- | :--- | :--- | :--- |
| 共识 | Raft（仅 server） | etcd-raft | Zab | JRaft（配置侧） |
| 日志存储 | WAL（默认）或 BoltDB | WAL | 内存 + 快照 | RocksDB |
| 成员发现 | Serf gossip | 无（静态 peer） | 无（静态 peer） | Distro / Raft |
| 自动化运维 | Autopilot（2.x 外置库） | 需外部 operator | 需手动 | 需手动 |
| 大写提交 | raftchunking 分片 | 单条限制 1.5MB | jute 上限 4MB（旧） | 无分片 |
| 多数据组 | 每 DC 独立 Raft | 单 Raft 组 | 单 Zab 组 | 单 JRaft 组（可分片） |

Consul 把"成员发现"与"共识"拆成两套协议是最显著的架构差异：Raft 管状态一致，Serf 管"谁还活着、谁新加入"，二者解耦让扩缩 server、跨 DC 联邦都更平滑。代价是运维面比 etcd 宽——要同时看护 Raft 与 gossip 两套通道（见 [Troubleshooting](/docs/CS/Framework/consul/troubleshooting.md)）。

## Links

- [Consul（枢纽与架构）](/docs/CS/Framework/consul/Consul.md)
- [Serf（成员发现）](/docs/CS/Framework/consul/serf.md)
- [KV（存储）](/docs/CS/Framework/consul/kv.md)
- [数据模型](/docs/CS/Framework/consul/data_model.md)
- [配置参考](/docs/CS/Framework/consul/config.md)
- [Cluster（集群运维）](/docs/CS/Framework/consul/cluster.md)
- [Troubleshooting（故障排查）](/docs/CS/Framework/consul/troubleshooting.md)
- [etcd 横向对照](/docs/CS/Framework/etcd/compare.md)

## References

1. [Consul Consensus Protocol (Raft)](https://developer.hashicorp.com/consul/docs/concept/consul-internals/consensus)
2. [hashicorp/raft-autopilot](https://github.com/hashicorp/raft-autopilot)
3. [hashicorp/raft-wal](https://github.com/hashicorp/raft-wal)
4. [hashicorp/consul v2.1.0 server.go](https://github.com/hashicorp/consul/blob/v2.1.0/agent/consul/server.go)
5. [Autopilot Operator HTTP API](https://developer.hashicorp.com/consul/api-docs/operator/autopilot)
