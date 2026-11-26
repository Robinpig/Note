# Embed

## Introduction

`go.etcd.io/etcd/server/v3/embed`（3.5 起位于 `server/embed` module，旧版是 `go.etcd.io/etcd/embed`）把 etcd 作为**库**嵌入 Go 程序，而不是依赖外部二进制。典型场景：单测里起一个临时目录的 etcd、把 etcd 作为单二进制应用的内置存储、或简化部署。

etcd 枢纽只保留版本与导航；启动链细节在 [boot](/docs/CS/Framework/etcd/boot.md)。本文补全 embed 的生命周期与字段，所有字段名与默认值以 **v3.7.2** 的 `server/embed/config.go` 为准。
> 版本基线：etcd 3.7.4（commit 2e8a5c99，Go 1.26）。以下字段名与默认值取自该 tag 的 `server/embed/config.go` / `etcd.go`。

从源码核实的反直觉点：

- **`StartEtcd` 非阻塞返回**：内部另起 goroutine 拉起 server/listeners/raft，返回时 etcd 可能还没加入集群，须等 `e.Server.ReadyNotify()` 或 `e.ServerReadyC()`。
- **`StartEtcd` 失败时自动回滚**：defer 里会 `e.Close()` 并置 `e=nil`，调用方拿到 `err` 后不必再 Close。
- **`--snapshot-count` 默认已是 10000**（3.6 起从 100000 降下），不再是旧资料的 100000。

## Lifecycle

最小可用形态：

```go
import "go.etcd.io/etcd/server/v3/embed"

cfg := embed.NewConfig()
cfg.Dir = "/tmp/etcd-data"      // 数据目录（含 member/snap、member/wal、member/snap/db）
e, err := embed.StartEtcd(cfg)
if err != nil { /* ... */ }
defer e.Close()                 // 必须，否则 goroutine / 文件句柄泄漏

kv := e.Server.KV()             // e.Server 是 *etcdserver.EtcdServer，可进程内直接调用
```

`StartEtcd` 的签名与失败回滚逻辑（`server/embed/etcd.go`）：

- `func StartEtcd(inCfg *Config) (e *Etcd, err error)`（`server/embed/etcd.go:110`）。它同步完成参数校验、listener 配置、`NewServer` 与 `Server.Start()`，返回时相关 goroutine 已启动，但**不保证已加入集群或可服务**；需等 `e.Server.ReadyNotify()` 或监听 `e.ServerReadyC()`。
- `e.Server` 字段是 `*etcdserver.EtcdServer`（`:260` 赋值），是访问存储与集群状态的入口。
- `func (e *Etcd) Close()`（`:414`）**不是幂等操作**：`closeOnce` 只保护 `stopc` 的关闭，listeners、clients、`Server.Stop()` 与 `errc` 等清理步骤每次调用都会执行，重复关闭可能 panic。每个实例只调用一次。
- 启动失败时，defer 会回滚已建资源并调用 `e.Close()`（`:117-129`），随后把返回的 `e` 置为 `nil`；调用方拿到 `err` 后不必再 Close。
```go
func StartEtcd(inCfg *Config) (e *Etcd, err error) {
	if err = inCfg.Validate(); err != nil {
		return nil, err
	}
	serving := false
	e = &Etcd{cfg: *inCfg, stopc: make(chan struct{})}
	cfg := &e.cfg
	defer func() {
		if e == nil || err == nil {
			return
		}
		if !serving {
			for _, sctx := range e.sctxs {
				sctx.close()
			}
		}
		e.Close()
		e = nil
	}()
	// ... 省略：configurePeerListeners / configureClientListeners / 装配 ServerConfig
}
```

装配好 `ServerConfig` 后调 `etcdserver.NewServer(srvcfg)` 拿 `e.Server`，再依次 `e.Server.Start()`、`servePeers()`、`serveClients()`、`serveMetrics()`：

```go
	if e.Server, err = etcdserver.NewServer(srvcfg); err != nil {
		return e, err
	}
	// newly started member does not need corruption check
	if memberInitialized && srvcfg.InitialCorruptCheck {
		if err = e.Server.CorruptionChecker().InitialCheck(); err != nil {
			e.Server.Cleanup()
			e.Server = nil
			return e, err
		}
	}
	e.Server.Start()

	if err = e.servePeers(); err != nil { return e, err }
	if err = e.serveClients(); err != nil { return e, err }
	if err = e.serveMetrics(); err != nil { return e, err }
	serving = true
	return e, nil
}
```

> [!WARNING]
> `StartEtcd` 返回成功 ≠ 已可服务。集群模式还要等选主与 peer 连通；单节点 `ClusterState="new"` 也建议等 `e.Server.ReadyNotify()`。业务进程要监听 ready 信号再接流量。

## Config Key Fields

`embed.Config` 是裸 etcd 启动参数的结构镜像，默认值来自 config.go 常量。按"集群 / 时序 / 容量 / 安全"分组：

### Cluster and Network

| 字段 | flag | 说明 |
| :--- | :--- | :--- |
| `Dir` | `--data-dir` | 数据根目录 |
| `WalDir` | `--wal-dir` | WAL 独立目录（与 Dir 分离可上 SSD 提速） |
| `ListenClientUrls` | `--listen-client-urls` | 监听客户端 gRPC/HTTP |
| `ListenPeerUrls` | `--listen-peer-urls` | 监听 peer（Raft） |
| `AdvertiseClientUrls` | `--advertise-client-urls` | 对外宣告的客户端地址 |
| `AdvertisePeerUrls` | `--advertise-peer-urls` | 对外宣告的 peer 地址 |
| `InitialCluster` | `--initial-cluster` | `name=peerURL` 列表 |
| `ClusterState` | `--initial-cluster-state` | `new` / `existing` |

### Timing

| 字段 | flag | 默认 | 约束 |
| :--- | :--- | :--- | :--- |
| `TickMs` | `--heartbeat-interval` | **100** ms | 必须 > 0 |
| `ElectionMs` | `--election-timeout` | **1000** ms | 必须 ≥ 5×TickMs，上限 `maxElectionMs = 50000` ms |

源码里 `Verify()` 检查：`TickMs==0` / `ElectionMs==0` 报错；`5*TickMs > ElectionMs` 报错；`ElectionMs > 50000` 报错。这组约束与 [tuning](/docs/CS/Framework/etcd/tuning.md) 的心跳/选举调优一致，只是这里从配置校验角度再次确认。
`Validate()` 的检查（`server/embed/config.go`）：

```go
if cfg.TickMs == 0 {
	return fmt.Errorf("--heartbeat-interval must be >0 (set to %dms)", cfg.TickMs)
}
if cfg.ElectionMs == 0 {
	return fmt.Errorf("--election-timeout must be >0 (set to %dms)", cfg.ElectionMs)
}
if 5*cfg.TickMs > cfg.ElectionMs {
	return fmt.Errorf("--election-timeout[%vms] should be at least as 5 times as --heartbeat-interval[%vms]", cfg.ElectionMs, cfg.TickMs)
}
if cfg.ElectionMs > maxElectionMs {
	return fmt.Errorf("--election-timeout[%vms] is too long, and should be set less than %vms", cfg.ElectionMs, maxElectionMs)
}
```

这组约束与 [tuning](/docs/CS/Framework/etcd/tuning.md) 的心跳/选举调优一致，只是这里从配置校验角度再次确认。

### Capacity and Backend

| 字段 | flag | 默认 | 说明 |
| :--- | :--- | :--- | :--- |
| `MaxTxnOps` | `--max-txn-ops` | **128** (`DefaultMaxTxnOps`) | 单事务最大操作数 |
| `MaxRequestBytes` | `--max-request-bytes` | **1.5 MiB** (`DefaultMaxRequestBytes = 1.5*1024*1024`) | 单请求最大字节 |
| `SnapshotCount` | `--snapshot-count` | **10000** (`etcdserver.DefaultSnapshotCount`) | 距上次落盘快照的 applied 差值超过该值时触发 |
| `QuotaBackendBytes` | `--quota-backend-bytes` | 2 GiB（8 GiB 为建议上限） | boltdb 配额，超限触发 NOSPACE（见 [troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md)） |
| `BackendBatchInterval` | `--backend-batch-interval` | 0（etcd 内部约 100ms 批处理） | 后端事务提交前最大等待 |
| `MaxRequestBytes` | `--max-request-bytes` | **1.5 MiB** (`DefaultMaxRequestBytes`) | 单请求最大字节 |
| `SnapshotCount` | `--snapshot-count` | **10000** (`etcdserver.DefaultSnapshotCount`) | 每多少条 Raft entry 做一次快照 |
| `QuotaBackendBytes` | `--quota-backend-bytes` | 2 GiB（上限 8 GiB，建议 8 GiB） | boltdb 配额，超限触发 NOSPACE（见 [troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md)） |
| `BackendBatchInterval` | `--backend-batch-interval` | 0（内部约 100ms 批处理） | 后端事务提交前最大等待 |
| `BackendBatchLimit` | `--backend-batch-limit` | 10000 | 后端事务提交前最大操作数 |
| `MaxSnapFiles` | `--max-snapshots` | **5** | 保留快照文件数 |
| `MaxWalFiles` | `--max-wals` | **5** | 保留 WAL 文件数 |

> [!NOTE]
> `SnapshotCount=10000` 是 **Raft 层**的落盘快照阈值：`appliedi - diskSnapshotIndex > SnapshotCount` 时才触发，因此实际是超过 10000 条而非恰好第 10000 条。3.6 起默认值从 100000 降到 10000，v3.7.2 保持该值。它不等于 V2 后端快照逻辑，也不控制 MVCC 历史；后者靠 [compact](/docs/CS/Framework/etcd/compact.md) 的 compact/defrag。
> `SnapshotCount=10000` 是 **Raft 层**快照频率（压缩 raft log），3.6 起从 100000 降下。MVCC 历史靠 [compact](/docs/CS/Framework/etcd/compact.md) 的 compact/defrag 回收，两者不是一回事——调 `--snapshot-count` 改的是 Raft 日志而非 MVCC 历史。

### Security and Compaction

- `ClientTLSInfo` / `PeerTLSInfo`（`transport.TLSInfo`）：客户端/peer 的 TLS 材料（见 [security](/docs/CS/Framework/etcd/security.md)）。
- `AuthToken` / `AuthTokenTTL`：认证 token 类型与 TTL。
- `AutoCompactionMode` / `AutoCompactionRetention`：`periodic`（如 `1h`）或 `revision`（如 `1000`）。
- `ExperimentalEnableLeaseCheckpoint` 是旧版配置名；3.7.2 使用 `LeaseCheckpoint` / `LeaseCheckpointPersist` feature gate，二者均为 alpha 且**默认关闭**（见 [lease](/docs/CS/Framework/etcd/lease.md)）。
- `EnableLeaseCheckpoint`：leader 定期向 follower 发 checkpoint，防止 leader 切换时剩余 TTL 被重置（3.6 起默认开启）。
- `ExperimentalInitialCorruptCheck`：启动即做一次损坏检查（见 [troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md) 的 corrupt 段）。

## Common Pitfalls

1. **必须 `Close()`** —— `StartEtcd` 起的 goroutine 不会自动回收，测试与长期服务都要 `defer e.Close()`，否则文件锁与 boltdb 句柄泄漏。
2. **data-dir 单例** —— 同一 `Dir` 不能被两个实例同时打开（boltdb 文件锁）。测试用 `t.TempDir()`；复用目录要先确保上一个实例已 `Close()`。
3. **import 路径随版本变** —— 3.5 起 embed 在 `server/embed` module（`go.etcd.io/etcd/server/v3/embed`），旧文档的 `go.etcd.io/etcd/embed` 已失效，go.mod 要带 `server/v3`。
4. **端口冲突** —— 默认 client `http://localhost:2379`、peer `http://localhost:2380`；并发起多个实例要改端口或只用单节点。
5. **配置先 `Validate()`** —— 交给 `StartEtcd` 前可先 `cfg.Validate()` 提前暴露心跳/选举比例、目录权限等错误，而不是启动跑到一半才崩。

## Links

- [etcd（启动流程里的 embed 调用点）](/docs/CS/Framework/etcd/etcd.md)
- [Core_Mechanisms（backend、WAL 与 snapshot 的持久边界）](/docs/CS/Framework/etcd/Core_Mechanisms.md)
- [cluster（数据目录布局 member/snap、member/wal）](/docs/CS/Framework/etcd/cluster.md)
- [boltdb（后端存储引擎）](/docs/CS/Framework/etcd/boltdb.md)

## References

1. [etcd v3.7.2 - StartEtcd and lifecycle](https://github.com/etcd-io/etcd/blob/v3.7.2/server/embed/etcd.go)
2. [etcd v3.7.2 - Config fields and defaults](https://github.com/etcd-io/etcd/blob/v3.7.2/server/embed/config.go)
3. [Embedding etcd in a Go Application](https://etcd.io/docs/v3.7/dev-guide/golang_embed_pkg/)
- [etcd](/docs/CS/Framework/etcd/etcd.md)
- [cluster](/docs/CS/Framework/etcd/cluster.md)
- [boltdb](/docs/CS/Framework/etcd/boltdb.md)
- [troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md)
- [security](/docs/CS/Framework/etcd/security.md)
- [tuning](/docs/CS/Framework/etcd/tuning.md)

## References

1. [etcd v3.7.4 源码（server/embed/etcd.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/embed/etcd.go)
2. [etcd v3.7.4 源码（server/embed/config.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/embed/config.go)
3. [etcd Documentation - Embedded etcd](https://etcd.io/docs/v3.7/integrations/embed/)
