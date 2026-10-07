## Introduction

etcd 的监控数据全部由**客户端端口**（默认 2379）自己吐出，不需要 sidecar 或 exporter——这一点和 Redis、MySQL 不同。etcd 同时把 Raft 内部状态（任期、提交索引、提案失败数）和存储引擎状态（boltdb 提交耗时、WAL fsync 耗时、db 大小）打成 Prometheus 格式暴露出来，这些指标与 [raft](/docs/CS/Framework/etcd/raft.md) 的状态机是一一对应的：leader 频繁切换、proposals 积压、apply 变慢，都能在指标上找到先行信号。

这一篇按"端点 → 指标 → 阈值 → 典型故障"组织，核心是一张**阈值速查表**：etcd 官方维护了一套默认告警规则（`contrib/mixin/alerts/alerts.libsonnet`），本文所有数字都取自其中，是官方认可的判定标准而非经验值。

打破直觉的地方有三点，都与"版本"有关：

1. **指标定义分散在 17 个 `metrics.go` 里**，不在某个统一的 `pkg/metrics` 包下——按包名去找 collector 会扑空。
2. **3.7 的调试端点不必靠开 debug 日志**。`--log-level=debug` 会带来性能降级与日志膨胀，而 `--enable-pprof` 能在不打开 debug 日志的前提下单独开放 `/debug/pprof`。
3. **3.7 的分布式追踪 flag 已经去掉了 `experimental-` 前缀**，而官方文档页面至今仍在写旧名字——照文档抄会得到 `unknown flag`。

> [!NOTE]
> **版本基线**：etcd **3.7.2**（`api/version/version.go` → `Version = "3.7.2"`）。本文所有 flag 均以 `server/embed/config.go` 在 3.7.2 下的实际注册名为准，告警阈值取自 3.7.2 的 `contrib/mixin/alerts/alerts.libsonnet`。特别注意 3.7 相对早期版本在可观测性上有实质增补（`--enable-pprof`、`--metrics basic|extensive`、分布式追踪 flag 改名），旧资料在这些点上普遍过时。

## Debug endpoint

### pprof: Two Ways to Enable

`/debug/pprof` 是标准 Go runtime profiling 端点，可分析 CPU、heap、mutex 与 goroutine 占用。3.7.2 里有**两条**开启路径：

```go
// 位置：server/embed/etcd.go:739-744
if cfg.EnablePprof || cfg.LogLevel == "debug" {
    sctx.registerPprof()
}
if cfg.LogLevel == "debug" {
    sctx.registerTrace()
}
```

两者的关系是**或**，且只有 pprof 是"或"进来的：

| 方式 | flag | `/debug/pprof` | `/debug/requests` | 生产可用 |
| :--- | :--- | :--- | :--- | :--- |
| 调试日志 | `--log-level=debug` | 有 | 有 | **不建议** |
| 专用开关 | `--enable-pprof`（默认 false，`config.go:734`） | 有 | **无** | 可短期开启 |

> [!TIP]
> **`--enable-pprof` 是 3.7 新增的、也是更安全的路径。** 旧资料只说"要开 `/debug` 就设 `--log-level=debug`"，这在生产上等于为了拿一次 profiling 付出一整轮的性能降级 + 日志膨胀的代价。`/debug/requests`（gRPC trace）仍然**只**在 `LogLevel == "debug"` 时注册，没有独立开关——这是它与 pprof 的关键差别。

```shell
$ go tool pprof http://localhost:2379/debug/pprof/profile
Fetching profile from http://localhost:2379/debug/pprof/profile
Please wait... (30s)
Saved profile in /home/etcd/pprof/pprof.etcd.localhost:2379.samples.cpu.001.pb.gz
Entering interactive mode (type "help" for commands)
(pprof) top10
310ms of 480ms total (64.58%)
Showing top 10 nodes out of 157 (cum >= 10ms)
    flat  flat%   sum%        cum   cum%
  130ms 27.08% 27.08%      130ms 27.08%  runtime.futex
    70ms 14.58% 41.67%       70ms 14.58%  syscall.Syscall
    20ms  4.17% 45.83%       20ms  4.17%  github.com/coreos/etcd/vendor/golang.org/x/net/http2/hpack.huffmanDecode
    20ms  4.17% 50.00%       20ms  4.17%  runtime.pcvalue
```

从这个真实采样能读出 etcd 的典型 CPU 分布：`runtime.futex`（线程同步等待）与 `syscall.Syscall`（系统调用）合计占比很高，说明 etcd 的 CPU 开销大头在**等待与系统调用**而非业务计算。当 futex 占比异常高，通常指向 Raft 内部锁竞争或 goroutine 调度问题。

### gRPC trace

`/debug/requests` 端点直接在浏览器里给出 gRPC trace 与性能统计，无需 pprof（但需 `--log-level=debug`）：

```
When	Elapsed (s)
2017/08/18 17:34:51.999317 	0.000244 	/etcdserverpb.KV/Range
17:34:51.999382 	 .    65 	... RPC: from 127.0.0.1:47204 deadline:4.999377747s
17:34:51.999395 	 .    13 	... recv: key:"abc"
17:34:51.999499 	 .   104 	... OK
17:34:51.999535 	 .    36 	... sent: header:<cluster_id:14841639068965178418 member_id:10276657743932975437 revision:15 raft_term:17 > kvs:<key:"abc" create_revision:6 mod_revision:14 version:9 value:"asda" > count:1
```

注意 `sent` 行回传的 header 里有 `cluster_id` / `member_id` / `revision` / `raft_term`——这四个值是排查"请求落到哪个集群、哪个任期"的关键线索。

同源的 `/debug/events` 与它一起注册（`server/embed/serve.go:558-562`），dump 的是 etcd 内部事件流。

## Metrics endpoint

`/metrics` 在客户端端口上默认暴露，也可以用 `--listen-metrics-urls` 额外开放到其他地址：

```shell
$ curl -L http://localhost:2379/metrics | grep -v debugging # debugging_ 前缀是不稳定指标
```

`etcd_debugging_*` 前缀的指标官方明确标注为**不稳定**，跨版本会变，grep 时排除掉。

> [!NOTE]
> 找指标定义时不要指望某个统一的 collector 包。3.7.2 里指标定义**分散在 17 个 `metrics.go`**：`server/etcdserver/metrics.go`、`server/etcdserver/{apply,txn,read}/metrics.go`、`server/etcdserver/api/{v3rpc,v2store,membership,rafthttp,snap,etcdhttp}/metrics.go`、`server/storage/{metrics.go,mvcc,backend,wal}/metrics.go`、`server/lease/metrics.go`、`server/auth/metrics.go`、`server/proxy/grpcproxy/metrics.go`。

### Metrics Detail Level: --metrics

3.7 新增 `--metrics`，控制导出指标的详细程度（`config.go:737`，默认 `basic`）：

```shell
--metrics=basic      # 默认
--metrics=extensive # 额外导出服务端 gRPC 直方图
```

```go
// 位置：server/etcdserver/api/v3rpc/grpc.go:101-106
if metricsServerCached == nil {
    var mopts []grpc_prometheus.ServerMetricsOption
    if metricType == "extensive" {
        mopts = append(mopts, grpc_prometheus.WithServerHandlingTimeHistogram())
    }
    metricsServerCached = grpc_prometheus.NewServerMetrics(mopts...)
```

> [!WARNING]
> **这条直接决定 `etcdGRPCRequestsSlow` 告警能不能用。** 该告警的表达式依赖 `grpc_server_handling_seconds_bucket`，而这个直方图**只有在 `--metrics=extensive` 时才注册**。用默认的 `basic`，这条 critical 告警会因指标不存在而**永远不触发**——不报警不等于没问题。
>
> 另外注意 `metricsServerCached` 是包级变量，一旦初始化就固化：运行期改这个 flag 无效，必须重启。

```go
// 位置：server/embed/etcd.go:871-875
func (e *Etcd) serveMetrics() (err error) {
	if len(e.cfg.ListenMetricsUrls) > 0 {
		metricsMux := http.NewServeMux()
		etcdhttp.HandleMetrics(metricsMux)
		etcdhttp.HandleHealth(e.cfg.logger, metricsMux, e.Server)
```

同一个 `metricsMux` 上同时挂载了 `/metrics` 与 `/health`——这就是"配了 `--listen-metrics-urls` 的地址也会响应 `/health`"的代码依据。

> [!WARNING]
> **这两个端点都不受 v3 RBAC 保护。** `auth enable` 之后 KV 数据受认证管控，但 `/metrics`、`/health` 走的是这条独立的 HTTP handler（见 [security](/docs/CS/Framework/etcd/security.md)）。把它们放到独立地址上是好事，但**必须确认那个地址的访问控制到位**——用 `--listen-metrics-urls` 做网络隔离时，隔离的力度取决于防火墙/安全组，而不是 etcd 自己。

## Health check

健康检查端点分两代，语义不同：

| 端点 | 引入版本 | 语义 |
| :--- | :--- | :--- |
| `/health` | v3.3.0 | 只反映能否响应；`--listen-metrics-urls` 上的地址也响应此端点 |
| `/livez` | v3.5.12 | 进程是否存活，是否需要重启 |
| `/readyz` | v3.5.12 | 进程是否**已就绪**接收流量 |

`/health` 存在的意义是：主端点配了双向 TLS（mTLS）时，负载均衡器或监控服务没有客户端证书，仍然需要一个无认证的探活入口。

`/livez` 与 `/readyz` 拆分的设计来自 KEP（`sig-etcd/4331-livez-readyz`）——把"该重启"和"能接流量"两件事分开，避免流量被打进正在恢复的节点。

加 `verbose` 参数可展开各子检查项：

```bash
$ curl -k http://localhost:2379/readyz?verbose
[+]data_corruption ok
[+]serializable_read ok
[+]linearizable_read ok
ok
```

反过来，`?exclude=` 可以排除特定检查项，用于区分"是数据损坏还是只是磁盘慢"：

```bash
curl -k http://localhost:2379/readyz?exclude=data_corruption
```

> [!TIP]
> `data_corruption` 这一项对排查 [boltdb](/docs/CS/Framework/etcd/boltdb.md) 损坏特别有用——它是唯一能在不重启进程的前提下确认数据文件是否健康的内置手段。

## Prometheus

直接抓 etcd 集群端点即可：

```yaml
global:
  scrape_interval: 10s
scrape_configs:
  - job_name: test-etcd
    static_configs:
    - targets: ['10.240.0.32:2379','10.240.0.33:2379','10.240.0.34:2379']
```

> [!NOTE]
> 官方提醒：默认告警规则是按**单个集群**写的，生产环境要给 `job` 标签加上集群唯一标识，否则多集群环境里规则会互相串扰。

Grafana 侧导入官方默认 dashboard（`etcd.io/docs/v3.7/op-guide/grafana.json`）即可，但要注意数据源名要一致：Prometheus 数据源命名为 `my-etcd` 时，dashboard JSON 里的 `datasource` 字段值也要改成 `my-etcd`。

## Key Metrics and Thresholds

下表全部来自官方默认告警规则（3.7.2 的 `contrib/mixin/alerts/alerts.libsonnet`），**阈值与持续时间都是官方值**：

| 指标 | 含义 | warning | critical |
| :--- | :--- | :--- | :--- |
| `etcd_server_leader_changes_seen_total` | leader 切换次数，15 分钟内 >= 4 次即异常 | 持续 5m | — |
| `etcd_server_proposals_failed_total` | 提案失败速率 | > 5/15m，持续 15m | — |
| `etcd_network_peer_round_trip_time_seconds` | 成员间 RTT，p99 | > 0.15s，持续 10m | — |
| `etcd_disk_wal_fsync_duration_seconds` | WAL fsync p99 | > 0.5s，持续 10m | > 1s，持续 10m |
| `etcd_disk_backend_commit_duration_seconds` | boltdb 提交 p99 | > 0.25s，持续 10m | — |
| `grpc_server_handling_seconds`（unary，p99，排除 Defragment） | 请求延迟 | — | > 0.15s，持续 10m |
| `grpc_server_handled_total` 失败占比 | 失败率 | > 1%，持续 10m | > 5%，持续 5m |
| `etcd_mvcc_db_total_size_in_bytes` / `etcd_server_quota_backend_bytes` | 空间占用比 | — | > 95%，持续 10m |

失败率被计入告警的 gRPC code 集合是固定的（`alerts.libsonnet:73`）：

```text
Unknown | FailedPrecondition | ResourceExhausted | Internal | Unavailable | DataLoss | DeadlineExceeded
```

`OK` / `Canceled` / `InvalidArgument` / `NotFound` / `AlreadyExists` 等不算失败——**`InvalidArgument` 大量出现通常意味着客户端调用姿势有问题，而不是 etcd 故障**。

另有几条拓扑与容量类告警：

| 告警名 | 触发条件 | 含义 |
| :--- | :--- | :--- |
| `etcdMembersDown` | 实例 down 或 peer 发送失败率 > 1%，持续 20m | 成员失联 |
| `etcdInsufficientMembers` | 存活成员数 < 多数派，持续 3m | **已失去 quorum**，写入不可用 |
| `etcdNoLeader` | `etcd_server_has_leader == 0`，持续 1m | 无 leader |
| `etcdDatabaseQuotaLowSpace` | 占用 > 95%，持续 10m | 触发 NOSPACE，写入将被拒绝 |
| `etcdExcessiveDatabaseGrowth` | 线性外推 4 小时后超配额，持续 10m | 增长过快，需提前 defrag |
| `etcdDatabaseHighFragmentationRatio` | 实际使用 < 50% 且 > 100 MB，持续 10m | 碎片化，需要 defrag 回收 |

`etcdInsufficientMembers` 的表达式是 `存活数 < (总数 + 1) / 2`，即严格多数派——这条告警意味着集群已经**不能写了**，是最高优先级。

> [!TIP]
> 告警规则里的 `for` 时长（持续时间）与阈值同等重要。比如 leader 切换是"15 分钟窗口内 >= 4 次"**且**"持续 5m"才报——只满足前者是正常的抖动。两个条件是 `and` 关系，改规则时别只改一半。

## Space and Fragmentation

两个 db 大小指标必须分清，它们回答的是不同问题：

| 指标 | 含义 | 变化时机 |
| :--- | :--- | :--- |
| `etcd_mvcc_db_total_size_in_bytes` | 磁盘上的实际占用，**含空闲页** | 每次写/commit 增长 |
| `etcd_mvcc_db_total_size_in_use_in_bytes` | [compact](/docs/CS/Framework/etcd/compact.md) 之后真正在用的空间 | 随 [MVCC](/docs/CS/Framework/etcd/MVCC.md) 压缩下降 |

官方对碎片化的判定是"使用率 < 50% 且绝对值 > 100 MB"，这个双重条件很重要：只小集群数据少时比例会天然偏低，硬套 50% 会产生大量误报。

碎片率的另一个隐含性质：**`in_use` 只在接近 `total` 时才会继续增长**，所以一旦写满触发 NOSPACE alarm，仅靠 compact 不能恢复，必须再做 defrag 才会真正释放磁盘。

> [!NOTE]
> `etcd_debugging_mvcc_db_total_size_in_bytes` 自 v3.4 起已改名为 `etcd_mvcc_db_total_size_in_bytes`。旧告警规则或旧文档里若还引用 `etcd_debugging_` 那个名字，在 3.7 上会取不到数据。

## Distributed tracing

基于 OpenTelemetry 的分布式追踪自 v3.5 起引入。**3.7 已去掉 flag 名的 `experimental-` 前缀**，这是相对旧资料最容易踩的坑。

```shell
--enable-distributed-tracing=true
--distributed-tracing-address="localhost:4317"   # 收集器地址
--distributed-tracing-service-name="etcd"         # 全集群必须一致
--distributed-tracing-instance-id="etcd-1"        # 建议设置且集群内唯一
--distributed-tracing-sampling-rate=0             # 每百万 span 采样数，默认 0
```

五个 flag 在 3.7.2 的注册位置（`server/embed/config.go:739-743`）：

| flag | 类型与默认值 | 位置 |
| :--- | :--- | :--- |
| `--enable-distributed-tracing` | bool，默认 `false` | `config.go:739` |
| `--distributed-tracing-address` | string | `config.go:740` |
| `--distributed-tracing-service-name` | string，默认 `etcd` | `config.go:741` |
| `--distributed-tracing-instance-id` | string，**无默认值** | `config.go:742` |
| `--distributed-tracing-sampling-rate` | int，默认 `0` | `config.go:743` |

> [!WARNING]
> **官方 v3.7 文档页面至今仍写着 `--experimental-enable-distributed-tracing` 这类旧名字**（抓取该页确认其 Distributed tracing 一节全是 `experimental-` 前缀），而 3.7.2 源码里 `experimental-distributed-tracing` **零命中**。照官方文档抄会得到 `unknown flag` 启动失败。**以源码为准，不要以文档页为准**——这是"存在 ≠ 仍是原语义"之外的另一类漂移：文档滞后于代码。
>
> 另注意 `--distributed-tracing-instance-id` 的源码注释写明 "There is no default value set"，与另两个 flag 不同——不设就没有实例维度，所有 span 会挤在一起。

> [!WARNING]
> 官方实测该项开销约为 **2%~4% CPU**。默认采样率为 0（不采样），开启前要评估这个成本。

## 3.7 Impact of Feature Gate

3.7 引入统一 feature gate（`server/features/etcd_features.go`），其中两项会改变可观测到的行为：

| gate | 阶段 | 默认 | 影响 |
| :--- | :--- | :--- | :--- |
| `StopGRPCServiceOnDefrag` | alpha | false | defrag 期间是否停止 gRPC 服务——直接影响 `etcdGRPCRequestsSlow`（它排除了 `Defragment` 方法）与 defrag 期间的请求表现 |
| `FastLeaseKeepAlive` | beta | **true** | 续租跳过等待 applied index，改变 [lease](/docs/CS/Framework/etcd/lease.md) 续租的延迟特征 |

排查指标异常但找不到配置改动时，值得确认一下相关 gate 的状态。

## Pitfall List

> [!WARNING]
> 这一篇里最容易让人排错方向的几点：

1. **分布式追踪的 5 个 flag 在 3.7 没有 `experimental-` 前缀** —— 正确写法是 `--enable-distributed-tracing` 等。官方 v3.7 文档页仍写旧名，照抄会 `unknown flag`。
2. **`--metrics` 默认 `basic` 时不导出 gRPC 直方图** —— `etcdGRPCRequestsSlow`（critical）依赖的 `grpc_server_handling_seconds_bucket` 因此不存在，该告警**静默失效**。需要它就得设 `--metrics=extensive`。
3. **`--metrics` 运行期改无效** —— `metricsServerCached` 是包级变量，初始化即固化，必须重启。
4. **`--enable-pprof` 与 `--log-level=debug` 不等价** —— 前者只开 `/debug/pprof`，后者额外开 `/debug/requests` 和 `/debug/events`。要 gRPC trace 只能开 debug 日志；要 pprof 用专用 flag 即可，不必付日志膨胀的代价。
5. **collector 不在统一包里** —— 指标定义分散在 17 个 `metrics.go`，不存在 `pkg/metrics` 这个目录。
6. **`etcd_debugging_*` 前缀不稳定** —— 官方标注跨版本会变，grep 与告警规则里都要排除；`etcd_debugging_mvcc_db_total_size_in_bytes` 更是已在 v3.4 改名。
7. **改了 `for` 持续时间等于改了告警语义** —— 官方规则里阈值与持续时间是 `and` 关系，只调一个会显著改变告警触发频率。
8. **`etcd_debugging_auth_revision` 能验证鉴权配置是否已全节点生效** —— 权限改动后各节点该值应当收敛，不一致说明 apply 落后（见 [security](/docs/CS/Framework/etcd/security.md)）。
9. **`etcdInsufficientMembers` 触发时集群已不能写** —— 它不是"预警"而是"已故障"，处置顺序与其它告警不同（见 [troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md)）。
10. **`--listen-metrics-urls` 会同时开放 `/health`** —— 这个端点**不受 RBAC 保护**，绑到内部地址时要确认网络隔离到位。

## Links

- [raft（共识模块）](/docs/CS/Framework/etcd/raft.md)
- [troubleshooting（常见故障排查）](/docs/CS/Framework/etcd/troubleshooting.md)
- [cluster（集群运维与备份恢复）](/docs/CS/Framework/etcd/cluster.md)
- [compact（历史版本压缩）](/docs/CS/Framework/etcd/compact.md)
- [boltdb（底层存储引擎）](/docs/CS/Framework/etcd/boltdb.md)
- [security（鉴权与 auth revision 指标）](/docs/CS/Framework/etcd/security.md)

## References

1. [etcd Documentation - Monitoring](https://etcd.io/docs/v3.7/op-guide/monitoring/)
2. [etcd Documentation - FAQ](https://etcd.io/docs/v3.7/faq/)
3. [etcd contrib/mixin 默认告警规则（v3.7.2）](https://github.com/etcd-io/etcd/blob/v3.7.2/contrib/mixin/alerts/alerts.libsonnet)
4. [etcd 默认 Grafana dashboard](https://etcd.io/docs/v3.7/op-guide/grafana.json)
5. [etcd server/embed/config.go — 可观测性相关 flag 注册](https://github.com/etcd-io/etcd/blob/v3.7.2/server/embed/config.go)
6. [KEP-2571 etcd livez and readyz endpoints](https://github.com/kubernetes/enhancements/tree/master/keps/sig-etcd/4331-livez-readyz)
