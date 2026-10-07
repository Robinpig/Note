## Introduction

`go.etcd.io/etcd/embed`（3.5 起位于 `server/embed` module，旧版是 `go.etcd.io/etcd/embed`）把 etcd 作为**库**嵌入 Go 程序，而不是依赖外部 `etcd` 二进制。典型场景：单元测试里起一个内存/临时目录的 etcd、把 etcd 作为单二进制应用的内置存储、或简化部署。

etcd.md 的启动流程里只把 `embed.StartEtcd` / `embed.Config` 当成调用点出现（[etcd.md](/docs/CS/Framework/etcd/etcd.md) 的 `startEtcd` 段），没有系统讲生命周期与字段。本文补全。所有字段名与默认值均取自 `server/embed/config.go`（v3.5.34）。

## Lifecycle

最小可用形态：

```go
import "go.etcd.io/etcd/server/v3/embed"

cfg := embed.NewConfig()
cfg.Dir = "/tmp/etcd-data"           // 数据目录（含 member/snap、member/wal、member/snap/db）
e, err := embed.StartEtcd(cfg)
if err != nil { /* ... */ }
defer e.Close()                      // 必须，否则 goroutine / 文件句柄泄漏

// e.Server 是 *etcdserver.EtcdServer，可拿到 KV / Cluster / Lease / Auth 等子服务
kv := e.Server.KV()                  // 进程内直接调用，无需走网络
```

关键事实（来自 `server/embed/etcd.go`）：

- `func StartEtcd(inCfg *Config) (e *Etcd, err error)`（第 112 行）。它**非阻塞返回**：内部另起 goroutine 启动 server、client/peer listeners、raft；返回时 etcd 还在拉起，需等 `e.Server.ReadyNotify()` 或监听 `e.ServerReadyC()` 确认可服务。
- `e.Server` 字段是 `*etcdserver.EtcdServer`（第 260 行 `e.Server = etcdserver.NewServer(srvcfg)`），是访问存储与集群状态的入口。
- `func (e *Etcd) Close()`（第 400 行）**幂等**：内部用计数器防止重复关闭；它会停掉 raft、listeners、并 `e.Server.Cleanup()`。
- 启动失败时会自动 `e.Close()` 回滚已建资源（第 125–129 行），所以调用方拿到 `err` 后不必再 Close。

> [!WARNING]
> `StartEtcd` 返回成功 ≠ etcd 已可服务。集群模式下还要等选主与 peer 连通；单节点 `ClusterState="new"` 也建议等 `e.Server.ReadyNotify()`。测试里直接 `defer e.Close()` 即可，但业务进程要监听 ready 信号再接流量。

## Config Key Fields

`embed.Config` 是裸 etcd 全部启动参数的结构镜像。以下按"集群 / 时序 / 容量 / 安全"分组，默认值均来自 `config.go` 常量：

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
| `InitialClusterToken` | `--initial-cluster-token` | 集群 ID 盐 |
| `ClusterState` | `--initial-cluster-state` | `new` / `existing` |

### Timing (Strongly Related to Raft Election)

| 字段 | flag | 默认 | 约束 |
| :--- | :--- | :--- | :--- |
| `TickMs` | `--heartbeat-interval` | **100** ms | 必须 > 0 |
| `ElectionMs` | `--election-timeout` | **1000** ms | 必须 ≥ `5 × TickMs`，上限 `maxElectionMs = 50000` ms |

源码里 `Verify()` 的检查（第 718–728 行）：`TickMs==0` / `ElectionMs==0` 报错；`5*TickMs > ElectionMs` 报错；`ElectionMs > 50000` 报错。这组约束与 [etcd.md](/docs/CS/Framework/etcd/etcd.md) Tuning 段讲的心跳/选举调优一致，只是这里从配置校验角度再次确认。

### Capacity and Backend

| 字段 | flag | 默认 | 说明 |
| :--- | :--- | :--- | :--- |
| `MaxTxnOps` | `--max-txn-ops` | **128** (`DefaultMaxTxnOps`) | 单事务最大操作数 |
| `MaxRequestBytes` | `--max-request-bytes` | **1.5 MiB** (`DefaultMaxRequestBytes = 1.5*1024*1024`) | 单请求最大字节 |
| `SnapshotCount` | `--snapshot-count` | **100000** (`etcdserver.DefaultSnapshotCount`) | 每多少条 Raft  entry 做一次快照压缩 |
| `QuotaBackendBytes` | `--quota-backend-bytes` | 2 GiB（上限 8 GiB） | boltdb 配额，超限触发 NOSPACE（见 [troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md)） |
| `BackendBatchInterval` | `--backend-batch-interval` | 0（etcd 内部约 100ms 批处理） | 后端事务提交前最大等待 |
| `BackendBatchLimit` | `--backend-batch-limit` | 10000 | 后端事务提交前最大操作数 |
| `MaxSnapFiles` | `--max-snapshots` | **5** (`DefaultMaxSnapshots`) | 保留快照文件数 |
| `MaxWalFiles` | `--max-wals` | **5** (`DefaultMaxWALs`) | 保留 WAL 文件数 |

> [!NOTE]
> `SnapshotCount=100000` 是 **Raft 层**的快照频率（每 10 万条 entry 压缩一次 raft log）。etcd.md Tuning 段提到的"每 10,000 次变更做快照"是 **V2 后端**的旧值——V3（当前默认）走的是 100000 这条。两者不是一回事，调 `--snapshot-count` 时要清楚改的是 Raft 日志而非 MVCC 历史（MVCC 历史靠 [compact](/docs/CS/Framework/etcd/compact.md) 的 compact/defrag）。

### Security and Compaction

- `ClientTLSInfo` / `PeerTLSInfo`（`transport.TLSInfo`）：客户端/peer 的 TLS 材料。
- `AuthToken` / `AuthTokenTTL`：认证 token 类型与 TTL（见 [security](/docs/CS/Framework/etcd/security.md)）。
- `AutoCompactionMode` / `AutoCompactionRetention`：`periodic`（如 `1h`）或 `revision`（如 `1000`）。
- `ExperimentalEnableLeaseCheckpoint`：leader 定期向 follower 发 checkpoint，防止 leader 切换时剩余 TTL 被重置（3.6 起默认开启）。
- `ExperimentalInitialCorruptCheck`：启动即做一次损坏检查（见 [troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md) 的 corrupt 段）。

## Common Pitfalls

1. **必须 `Close()`**：`StartEtcd` 起的 raft/client/peer goroutine 不会随进程退出自动回收（除非进程退出）。测试与长期运行的服务都要 `defer e.Close()` 或显式关闭，否则文件锁（`fileutil`）与 boltdb 句柄泄漏。
2. **data-dir 单例**：同一 `Dir` 不能被两个 etcd 实例同时打开（boltdb 文件锁）。测试用 `t.TempDir()` 或随机目录；复用目录要先确保上一个实例已 `Close()`。
3. **import 路径随版本变**：3.5 起 embed 在 `server/embed` module（`go.etcd.io/etcd/server/v3/embed`），旧文档写的 `go.etcd.io/etcd/embed` 在 3.5+ 已失效。go.mod 要带 `server/v3`。
4. **端口冲突与绑定**：`ListenClientUrls` 默认 `http://localhost:2379`、`ListenPeerUrls` 默认 `http://localhost:2380`；测试并发起多个实例要改端口或只用单节点。
5. **配置先 `Verify()`**：把 `*Config` 交给 `StartEtcd` 前可先 `cfg.Verify()`（或 `cfg.Validate()`）提前暴露心跳/选举比例、目录权限等错误，而不是等启动跑到一半才崩。

## Links

- [etcd（启动流程里的 embed 调用点）](/docs/CS/Framework/etcd/etcd.md)
- [cluster（数据目录布局 member/snap、member/wal）](/docs/CS/Framework/etcd/cluster.md)
- [boltdb（后端存储引擎）](/docs/CS/Framework/etcd/boltdb.md)
- [troubleshooting（NOSPACE / corrupt）](/docs/CS/Framework/etcd/troubleshooting.md)
- [security（AuthToken / TLS）](/docs/CS/Framework/etcd/security.md)
- [compact（MVCC 历史压缩，区别于 SnapshotCount）](/docs/CS/Framework/etcd/compact.md)

## References

1. [etcd source - server/embed/etcd.go（StartEtcd / Close / Etcd 结构）](https://github.com/etcd-io/etcd/blob/v3.5.34/server/embed/etcd.go)
2. [etcd source - server/embed/config.go（Config 字段与默认值常量）](https://github.com/etcd-io/etcd/blob/v3.5.34/server/embed/config.go)
3. [etcd Documentation - Embd Etcd（集成示例）](https://etcd.io/docs/v3.5/integrations/embed/)
