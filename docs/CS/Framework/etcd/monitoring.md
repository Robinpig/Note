# Monitoring

## Introduction

etcd 的监控数据全部由**客户端端口**（默认 2379）自己吐出，不需要 sidecar 或 exporter——这一点和 Redis、MySQL 不同。它把 Raft 内部状态（任期、提交索引、提案失败数）与存储引擎状态（boltdb 提交耗时、WAL fsync 耗时、db 大小）打成 Prometheus 格式暴露出来，与 [raft](/docs/CS/Framework/etcd/raft.md) 状态机一一对应：leader 频繁切换、proposals 积压、apply 变慢都能找到先行信号。

> 版本基线：etcd 3.7.4（commit 2e8a5c99，Go 1.26）。flag 注册名取自 `server/embed/config.go`，告警阈值取自 `contrib/mixin/alerts/alerts.libsonnet`。

从源码核实的反直觉点：

- **指标定义分散在多个 `metrics.go`**，不在统一的 `pkg/metrics` 包下——按包名找 collector 会扑空。
- **`--metrics` 默认 `basic` 不导出 gRPC 直方图**，导致 `etcdGRPCRequestsSlow` 这条 critical 告警**静默失效**。
- **3.7 的分布式追踪 flag 已去掉 `experimental-` 前缀**，官方文档页面至今仍写旧名，照抄会 `unknown flag`。

## Debug Endpoint

### pprof: Two Ways to Enable

`/debug/pprof` 是标准 Go runtime profiling 端点，可分析 CPU、heap、mutex、goroutine 占用。3.7.4 里有两条开启路径，关系是"或"，且只有 pprof 是"或"进来的——`registerTrace` 仍只在 debug 日志时注册：

```go
// server/embed/etcd.go
if cfg.EnablePprof || cfg.LogLevel == "debug" {
	sctx.registerPprof()
}
if cfg.LogLevel == "debug" {
	sctx.registerTrace()
}
```

| 方式 | flag | `/debug/pprof` | `/debug/requests` | 生产可用 |
| :--- | :--- | :--- | :--- | :--- |
| 调试日志 | `--log-level=debug` | 有 | 有 | **不建议** |
| 专用开关 | `--enable-pprof`（默认 false） | 有 | **无** | 可短期开启 |

> [!TIP]
> `--enable-pprof` 是更安全的路径。旧资料只说"设 `--log-level=debug`"，这在生产上等于为拿一次 profiling 付出整轮性能降级 + 日志膨胀。`/debug/requests`（gRPC trace）仍**只**在 debug 日志时注册，没有独立开关。

```shell
$ go tool pprof http://localhost:2379/debug/pprof/profile
(pprof) top10
```

典型 CPU 分布里 `runtime.futex`（线程同步等待）与 `syscall.Syscall` 占比很高，说明 etcd 的 CPU 开销大头在**等待与系统调用**而非业务计算。futex 异常高通常指向 Raft 内部锁竞争或 goroutine 调度问题。

同源的 `/debug/events` 与 `/debug/requests` 一起注册，dump 内部事件流。`sent` 行回传的 header 里有 `cluster_id` / `member_id` / `revision` / `raft_term`——排查"请求落到哪个集群、哪个任期"的关键线索。

## Metrics Endpoint

`/metrics` 在客户端端口默认暴露，也可用 `--listen-metrics-urls` 额外开放到其他地址：

```shell
$ curl -L http://localhost:2379/metrics | grep -v debugging  # debugging_ 前缀不稳定
```

`--metrics` 控制导出详细程度（默认 `basic`），它决定是否注册服务端 gRPC 直方图：

```go
// server/etcdserver/api/v3rpc/grpc.go
func getServerMetrics(metricType string, lg *zap.Logger) *grpc_prometheus.ServerMetrics {
	if metricsServerCached == nil {
		var mopts []grpc_prometheus.ServerMetricsOption
		if metricType == "extensive" {
			mopts = append(mopts, grpc_prometheus.WithServerHandlingTimeHistogram())
		}
		metricsServerCached = grpc_prometheus.NewServerMetrics(mopts...)
	}
	// ... 省略：prometheus.Register
	return metricsServerCached
}
```

```shell
--metrics=basic      # 默认
--metrics=extensive # 额外导出服务端 gRPC 直方图
```

> [!WARNING]
> **这条直接决定 `etcdGRPCRequestsSlow` 告警能不能用。** 该告警依赖 `grpc_server_handling_seconds_bucket`，而这个直方图**只有 `--metrics=extensive` 时才注册**。用默认 `basic`，critical 告警会因指标不存在而**永远不触发**——不报警不等于没问题。
>
> 另外 `metricsServerCached` 是**包级变量**，初始化即固化：运行期改 flag 无效，必须重启。

`serveMetrics` 把 `/metrics` 与 `/health` 挂在同一 mux 上，这就是"配了 `--listen-metrics-urls` 的地址也响应 `/health`"的代码依据：

```go
// server/embed/etcd.go
func (e *Etcd) serveMetrics() (err error) {
	if len(e.cfg.ListenMetricsUrls) > 0 {
		metricsMux := http.NewServeMux()
		etcdhttp.HandleMetrics(metricsMux)
		etcdhttp.HandleHealth(e.cfg.logger, metricsMux, e.Server)
		// ... 省略：启动 http server
	}
}
```

> [!WARNING]
> **这两个端点都不受 v3 RBAC 保护。** `auth enable` 后 KV 数据受认证管控，但 `/metrics`、`/health` 走独立 HTTP handler（见 [security](/docs/CS/Framework/etcd/security.md)）。必须确认那个地址的访问控制到位——隔离力度取决于防火墙/安全组，而不是 etcd 自己。

## Health Check

健康检查端点分两代，语义不同：

| 端点 | 引入版本 | 语义 |
| :--- | :--- | :--- |
| `/health` | v3.3.0 | 只反映能否响应；`--listen-metrics-urls` 地址也响应 |
| `/livez` | v3.5.12 | 进程是否存活、是否需要重启 |
| `/readyz` | v3.5.12 | 进程是否已就绪接收流量 |

`/health` 存在的意义是：主端点配双向 TLS（mTLS）时，LB/监控没有客户端证书，仍需一个无认证探活入口。`/livez` 与 `/readyz` 的拆分来自 KEP（`sig-etcd/4331-livez-readyz`），把"该重启"和"能接流量"分开，避免流量打进正在恢复的节点。

```bash
$ curl -k http://localhost:2379/readyz?verbose
[+]data_corruption ok
[+]serializable_read ok
[+]linearizable_read ok
ok
```

`?exclude=data_corruption` 可排除特定项，用于区分"数据损坏还是只是磁盘慢"。`data_corruption` 是唯一能在不重启进程前提下确认 [boltdb](/docs/CS/Framework/etcd/boltdb.md) 数据文件是否健康的内置手段。

## Prometheus

直接抓各成员端点即可：

```yaml
global:
  scrape_interval: 10s
scrape_configs:
  - job_name: test-etcd
    static_configs:
    - targets: ['10.240.0.32:2379','10.240.0.33:2379','10.240.0.34:2379']
```

> [!NOTE]
> 默认告警规则按**单个集群**写，生产要给 `job` 标签加集群唯一标识，否则多集群环境规则会互相串扰。Grafana 导入官方 dashboard 时，数据源名要与 JSON 里的 `datasource` 字段一致。

## Key Metrics and Thresholds

下表全部来自官方默认告警规则（`contrib/mixin/alerts/alerts.libsonnet`），**阈值与持续时间都是官方值**：

| 指标 | 含义 | warning | critical |
| :--- | :--- | :--- | :--- |
| `etcd_server_leader_changes_seen_total` | leader 切换次数，15 分钟内 >= 4 次 | 持续 5m | — |
| `etcd_server_proposals_failed_total` | 提案失败速率 | > 5/15m，持续 15m | — |
| `etcd_network_peer_round_trip_time_seconds` | 成员间 RTT p99 | > 0.15s，持续 10m | — |
| `etcd_disk_wal_fsync_duration_seconds` | WAL fsync p99 | > 0.5s，持续 10m | > 1s，持续 10m |
| `etcd_disk_backend_commit_duration_seconds` | boltdb 提交 p99 | > 0.25s，持续 10m | — |
| `grpc_server_handling_seconds`（unary p99，排除 Defragment） | 请求延迟 | — | > 0.15s，持续 10m |
| `grpc_server_handled_total` 失败占比 | 失败率 | > 1%，持续 10m | > 5%，持续 5m |
| `etcd_mvcc_db_total_size_in_bytes` / `etcd_server_quota_backend_bytes` | 空间占用比 | — | > 95%，持续 10m |

失败率计入告警的 gRPC code 集合固定，直接写在规则里：

```text
Unknown | FailedPrecondition | ResourceExhausted | Internal | Unavailable | DataLoss | DeadlineExceeded
```

`OK` / `Canceled` / `InvalidArgument` / `NotFound` / `AlreadyExists` 不算失败——**`InvalidArgument` 大量出现通常意味着客户端调用姿势有问题，而非 etcd 故障**。

拓扑与容量类告警：

| 告警名 | 触发条件 | 含义 |
| :--- | :--- | :--- |
| `etcdMembersDown` | 实例 down 或 peer 发送失败率 > 1%，持续 20m | 成员失联 |
| `etcdInsufficientMembers` | 存活成员数 < 多数派，持续 3m | **已失去 quorum**，写入不可用 |
| `etcdNoLeader` | `etcd_server_has_leader == 0`，持续 1m | 无 leader |
| `etcdDatabaseQuotaLowSpace` | 占用 > 95%，持续 10m | 触发 NOSPACE，写入被拒 |
| `etcdExcessiveDatabaseGrowth` | 线性外推 4 小时后超配额，持续 10m | 增长过快，需提前 defrag |
| `etcdDatabaseHighFragmentationRatio` | 实际使用 < 50% 且 > 100 MB，持续 10m | 碎片化，需 defrag 回收 |

`etcdInsufficientMembers` 的判据是严格多数派——这条告警意味着集群已经**不能写了**，是最高优先级（见 [troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md)）。

> [!TIP]
> 告警规则里的 `for` 时长与阈值同等重要。比如 leader 切换是"15 分钟窗口内 >= 4 次"**且**"持续 5m"才报——只满足前者是正常抖动。两个条件是 `and` 关系，改规则时别只改一半。

## Space and Fragmentation

两个 db 大小指标回答不同问题：

| 指标 | 含义 | 变化时机 |
| :--- | :--- | :--- |
| `etcd_mvcc_db_total_size_in_bytes` | 磁盘实际占用，**含空闲页** | 每次写/commit 增长 |
| `etcd_mvcc_db_total_size_in_use_in_bytes` | [compact](/docs/CS/Framework/etcd/compact.md) 后真正在用的空间 | 随 [MVCC](/docs/CS/Framework/etcd/MVCC.md) 压缩下降 |

官方对碎片化的判定是"使用率 < 50% 且绝对值 > 100 MB"，双重条件很重要：小集群数据少时比例天然偏低，硬套 50% 会产生大量误报。一旦写满触发 NOSPACE，仅靠 compact 不能恢复，必须再做 defrag 才会真正释放磁盘（见 [boltdb](/docs/CS/Framework/etcd/boltdb.md) 的 freelist 段）。

> [!NOTE]
> `etcd_debugging_mvcc_db_total_size_in_bytes` 自 v3.4 起已改名为 `etcd_mvcc_db_total_size_in_bytes`。旧告警规则若还引用 `debugging_` 名字，在 3.7 上取不到数据。

## Distributed Tracing

基于 OpenTelemetry 的分布式追踪自 v3.5 引入，**3.7 已去掉 flag 名的 `experimental-` 前缀**（源码字段也改为 `DistributedTracingAddress` 等非 Experimental 名）：

```shell
--enable-distributed-tracing=true
--distributed-tracing-address="localhost:4317"
--distributed-tracing-service-name="etcd"         # 全集群必须一致
--distributed-tracing-instance-id="etcd-1"        # 源码注释：There is no default value set
--distributed-tracing-sampling-rate=0             # 每百万 span 采样数，默认 0
```

| flag | 默认值 |
| :--- | :--- |
| `--enable-distributed-tracing` | false |
| `--distributed-tracing-service-name` | `etcd` |
| `--distributed-tracing-instance-id` | 无默认值（不设则所有 span 挤在一起） |
| `--distributed-tracing-sampling-rate` | 0 |

> [!WARNING]
> 官方 v3.7 文档页面至今仍写 `--experimental-enable-distributed-tracing` 这类旧名，而 3.7.4 源码里 `experimental-distributed-tracing` **零命中**。照文档抄会 `unknown flag` 启动失败——**以源码为准**。官方实测该项开销约 2%~4% CPU，默认采样率 0（不采样），开启前要评估成本。

## Feature Gates

3.7 引入统一 feature gate（`server/features/etcd_features.go`），其中两项改变可观察到的行为：

| gate | 阶段 | 默认 | 影响 |
| :--- | :--- | :--- | :--- |
| `StopGRPCServiceOnDefrag` | alpha | false | defrag 期间是否停止 gRPC 服务——影响 defrag 期间的请求表现 |
| `FastLeaseKeepAlive` | beta | **true** | 续租跳过等待 applied index，改变 [lease](/docs/CS/Framework/etcd/lease.md) 续租的延迟特征 |

排查指标异常但找不到配置改动时，值得确认相关 gate 状态。

## Pitfall List

> [!WARNING]
> 这一篇最容易让人排错方向的几点。

1. **分布式追踪的 5 个 flag 在 3.7 没有 `experimental-` 前缀** —— 官方文档页仍写旧名，照抄会 `unknown flag`。
2. **`--metrics` 默认 `basic` 不导出 gRPC 直方图** —— `etcdGRPCRequestsSlow` 依赖的 bucket 不存在，告警静默失效；需要它就得设 `--metrics=extensive`。
3. **`--metrics` 运行期改无效** —— `metricsServerCached` 是包级变量，初始化即固化，必须重启。
4. **`--enable-pprof` 与 `--log-level=debug` 不等价** —— 前者只开 `/debug/pprof`，后者额外开 `/debug/requests` 和 `/debug/events`。
5. **collector 不在统一包里** —— 指标定义分散在多个 `metrics.go`，不存在 `pkg/metrics` 目录。
6. **`etcd_debugging_*` 前缀不稳定** —— 跨版本会变，grep 与告警规则都要排除。
7. **改了 `for` 持续时间等于改了告警语义** —— 阈值与持续时间是 `and` 关系，只调一个会显著改变触发频率。
8. **`--listen-metrics-urls` 会同时开放 `/health`** —— 该端点不受 RBAC 保护，绑到内部地址时要确认网络隔离到位。

## Links

- [raft](/docs/CS/Framework/etcd/raft.md)
- [troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md)
- [cluster](/docs/CS/Framework/etcd/cluster.md)
- [compact](/docs/CS/Framework/etcd/compact.md)
- [boltdb](/docs/CS/Framework/etcd/boltdb.md)
- [security](/docs/CS/Framework/etcd/security.md)

## References

1. [etcd v3.7.4 源码（contrib/mixin/alerts/alerts.libsonnet）](https://github.com/etcd-io/etcd/blob/v3.7.4/contrib/mixin/alerts/alerts.libsonnet)
2. [etcd v3.7.4 源码（server/embed/config.go — 可观测性 flag）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/embed/config.go)
3. [etcd v3.7.4 源码（server/embed/etcd.go — pprof/metrics 端点）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/embed/etcd.go)
4. [etcd Documentation - Monitoring](https://etcd.io/docs/v3.7/op-guide/monitoring/)
5. [KEP-4331 etcd livez and readyz endpoints](https://github.com/kubernetes/enhancements/tree/master/keps/sig-etcd/4331-livez-readyz)
