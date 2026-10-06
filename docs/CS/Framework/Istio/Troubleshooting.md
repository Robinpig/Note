# Istio 运行时排障命令集

## Introduction

Istio 的排障困难不在于命令少，而在于**命令分属三个层次且很容易互相替代失败**。`istioctl analyze` 是静态配置分析，它不接触 Envoy；`istioctl proxy-config` 读的是数据面实际生效的配置，它不判断这份配置是否符合预期；`istioctl proxy-status` 读的是控制面视角的同步状态，它不解释「为什么没同步」。

新手上最常见的两个误区：CI 里跑 `istioctl analyze -o json` 却拿不到失败退出码（**只有 `-o log` 才计算退出码**）；以及以为 `istioctl proxy-config` 能改配置（**它没有任何 mutate 路径**）。

本文所有命令、参数、默认值核实自 `istio-1.31.1` tag 源码（`istioctl/cmd/root.go`、`istioctl/pkg/**`），并与 `pilot/` 下的判��逻辑对照。基线：Istio **1.31.1**。

## 三个层次的分工

| 层次 | 命令 | 数据来源 | 能回答 | 不能回答 |
| :-- | :-- | :-- | :-- | :-- |
| **静态配置** | `analyze` | K8s API（或纯文件） | 配置是否合法、有无冲突 | 运行时行为、是否真生效 |
| **xDS 同步** | `proxy-status` | **控制面** istiod | 代理是否收到配置、多久收敛 | 配置内容对不对 |
| **数据面实况** | `proxy-config`、`authz check` | Envoy **config_dump** | Envoy 里实际是什么 | 是否符合预期 |
| **现场快照** | `bug-report` | 两者 + 日志 | 打包给上游/存档 | — |

选层的判据：症状是「配置写错了」→ 静态；症状是「改了没生效」→ 先 sync 后 dump；症状是「要发给厂商」→ bug-report。

## 完整命令清单（1.31.1，以源码为准）

**顶层**：`kube-inject`、`proxy-config`(pc)、`admin`、`uninstall`、`waypoint`、`ztunnel-config`、`analyze`、`dashboard`、`manifest`、`install`、`upgrade`、`bug-report`、`tag`、`create-remote-secret`、`clusters`(remote-clusters)、`collateral`、`validate`、`options`、`version`、`proxy-status`(ps)、`experimental`(x/exp)

**`istioctl experimental` 下**：`version`(legacy)、`proxy-status`(legacy)、`injector`、`authz`、`metrics`(m)、`describe`(des)、`config`、`workload`、`internal-debug`、`precheck`、`envoy-stats`(es)、`check-inject`

> [!WARNING]
> **确认不存在于 1.31 的命令**（全仓库 grep 无匹配，不是废弃而是从未存在）：`postcheck`、`wait`、`proxy-assert`、`envoy`（旧 `x envoy`）、`x benchmark`。
>
> `istioctl x wait` 曾与 `PILOT_ENABLE_CONFIG_DISTRIBUTION_TRACKING` 一起在 1.31 被**移除**（releasenote 明写「Removed the experimental PILOT_ENABLE_CONFIG_DISTRIBUTION_TRACKING feature flag and corresponding istioctl experimental wait command」）。
>
> **`istioctl completion` 不是独立命令**——`istioctl/pkg/completion` 只提供 flag 补全回调函数。
>
> **`authz` 在顶层是占位桩**：执行返回 error「authz is experimental. Use `istioctl experimental authz`」。

## `analyze`：静态检查

参数（`analyze.go:338-373`）：

| 参数 | 默认 | 说明 |
| :-- | :-- | :-- |
| `-A/--all-namespaces` | — | 全命名空间 |
| `-f/--filename` | — | 纯文件模式（配 `--use-kube=false`） |
| `-o/--output` | **`log`** | `log` / `json` / `yaml` |
| `-k/--use-kube` | **true** | 关掉则只读文件不连集群 |
| `--failure-threshold` | **`Error`** | **达此严重级则退出码非 0** |
| `--output-threshold` | **`Info`** | 控制显示门槛 |
| `--suppress` / `-S` | — | 压制已知噪声 |
| `--timeout` | **30s** | |
| `--ignore-unknown` | false | 文件解析失败时是否继续 |
| `-L/--list-analyzers` | — | 列出全部分析器 |
| `-R/--recursive` | **已废弃，硬编码 true** | flag 描述里写明 `[Removed]` |

严重级只有三档：`Info` / `Warning` / `Error`。

> [!WARNING]
> **退出码的坑：`-o json` / `-o yaml` 时不计算失败退出码。** 源码 `analyze.go:325-331` 的 `errorIfMessagesExceedThreshold` **仅在 `msgOutputFormat == formatting.LogFormat` 时调用**。
>
> **CI 里用 `istioctl analyze -o json` 会丢掉全部失败信号**——JSON 照样输出，但退出码永远是 0。要拿失败信号又想要机器可读输出，正确做法是跑两次：`-o log` 取退出码，`-o json` 取内容。

> [!NOTE]
> **`--suppress` 按「诊断消息码 = 资源名」，不是规则名。** 格式 `IST0102=DestinationRule primary-dr.default`，可重复；资源名支持 `*` 通配（`IST0102=DestinationRule *.default`）。按 `=` 切分必须正好两段，否则报错；消息码非法时**仅告警不失败**。

**它明确不查什么**：不接触 Envoy、不读 config_dump、不看 xDS 同步状态。`--ambient` 标志在 1.31 的 analyze 中**不存在**。

## `proxy-status`：看收敛

参数（`proxystatus.go:190-199`）：`-o/--output`（默认 `table`）、`-v/--verbosity`（**0=默认，1=显示所有 xDS 类型**）、`-f/--file`（Envoy config dump JSON，**`-` 表示 stdin**）、`--proxy-admin-port`（默认 **15000**）、`--revision`。

> [!WARNING]
> **1.31 的默认输出格式变了，与官方文档不一致。** 默认（`verbosity=0`）表头是 `NAME CLUSTER ISTIOD VERSION SUBSCRIBED TYPES`，`SUBSCRIBED TYPES` 渲染成 `count (CDS,LDS,...)`，**不再逐列打印 CDS/LDS/EDS/RDS 状态**。只有 `-v 1` 才回到逐类型列。
>
> 官方 VM 调试页示例仍是旧的 `NAME CDS LDS EDS RDS ISTIOD VERSION` 格式——**文档滞后于代码**，以源码为准。

状态判定（`pilot/pkg/xds/statusgen.go:195-206`，判的是 istiod 侧 `WatchedResource`）：

```
LastError != ""         → ERROR
NonceSent == ""         → NOT SENT
NonceSent == NonceAcked → SYNCED
否则                     → STALE
```

- 非核心类型缺失显示 **`IGNORED`**
- `STALE` 会**附带距上次更新的时长**，如 `STALE (10s)`

> [!TIP]
> **收敛的读法就是看括号里的时长是否持续增长。** `STALE (10s)` 之后再看一次变 `STALE (25s)`，说明 istiod 推了但 Envoy 一直不 ACK——问题在数据面（配置被拒、插件崩溃、agent 卡住），而不在控制面。

其他要点：指定 ztunnel pod 时会直接输出「Sync diff is not available for ztunnel pod」并返回；带 pod 参数时走 istiod `TypeDebugConfigDump` 做 **sync diff**（istiod 视角 vs Envoy 实际 config_dump），需能访问该 pod 的 admin 端口。**数据源是控制面，不读 pod。**

## `proxy-config`：读数据面实况

`Short` 明确标注 **`[kube only]`**。父命令 flag：`-o/--output`（默认 `short`）、`--proxy-admin-port`（默认 15000）。

实际注册的 **11 个**子命令：

| Use | 别名 | 备注 |
| :-- | :-- | :-- |
| `cluster` | `clusters`, `c` | `--fqdn` / `--direction` / `--subset` / `--port` |
| `all` | `a` | |
| `listener` | `listeners`, `l` | |
| `log` | `o` | 见下 |
| `route` | `routes`, `r` | `--name`、`--verbose`（**默认 true**） |
| `bootstrap` | `b` | |
| `endpoint` | `endpoints`, `ep` | |
| `eds` | — | |
| `secret` | `secrets`, `s` | |
| `rootca-compare` | `rc` | 两 pod 参数 |
| `ecds` | `ec` | Wasm 扩展配置 |

> [!WARNING]
> **不存在** `wasm`、`config`、`metrics`、`stats`、`list`。想看 Wasm 插件用 **`ecds`**；Envoy 指标在 `istioctl x envoy-stats`。
>
> **`-o file` 改配置不可行。** 所有子命令都是「拉 dump → 过滤 → 打印」，`RunE` 里只有 `PrintXxxSummary`/`PrintXxxDump`，**没有任何 mutate/patch 路径**。`-o` 只接受 `json|yaml|short`，**不接受文件路径**——要落盘只能用 shell 重定向 `>`。

目标语法 `<type>/<name>[.<namespace>]`，如 `deployment/productpage-v1`。

读 dump 时用的 mask：`all` 用 `?mask=dynamic_active_clusters,dynamic_warming_clusters,static_clusters`；`secret` 用 `?mask=dynamic_active_secrets,dynamic_warming_secrets`；`eds` 用 `?include_eds=true`。

### VM 上必须用 `--file`

VM 不在 K8s 里，`proxy-config` 无法通过 API 找 pod，只能读本地 config dump：

```bash
curl -s localhost:15000/config_dump | istioctl pc clusters --file -
curl -s localhost:15000/config_dump | istioctl pc secret   --file -
```

### 改日志级别

`--level` 取值 7 档：`trace` / `debug` / `info` / `warning`（输入 `warn` 亦可）/ `error` / `critical` / `off`。

格式 `[<logger>:]<level>,...`；不带 logger 前缀即改所有活跃 logger。特殊 logger 名 `level` 代表全局级别。支持 `ns::logger:level` 形式。

- `-r/--reset` 重置为默认；**默认级别是 `warning`**，会先尝试从 `istio-sidecar-injector` ConfigMap 读 `logLevel`，读不到回退 warning 并告警
- `--level` 不能与 `--reset` 组合
- **`--tail` 与 `--path` 不存在于 `proxy-config log`**（只注册了 `--reset`、`--selector`、`--level`）

> [!IMPORTANT]
> **这里改的是 Envoy 的日志，不是 Istio 的。** 本命令走 Envoy admin `/logging` API，用的是 Envoy 的 7 档级别。Istio 自身（pilot-agent / istiod）的日志是另一套 `--log_output_level`（形如 `dns:debug`），VM 上的改法是：
> ```bash
> echo 'ISTIO_AGENT_FLAGS="--log_output_level=dns:debug --proxyLogLevel=debug"' \
>   >> /var/lib/istio/envoy/cluster.env && systemctl restart istio
> ```

## `x authz check`：验证策略是否真到 Envoy

`istioctl authz check <pod>`（支持 `-f` 读本地 config dump）**直接检查 Envoy 实际生效的 AuthorizationPolicy**。

这在「istiod 说策略下发成功、但行为不对」的场景特别有用——它读的是数据面而非控制面。

## `x describe`：资源关系梳理

子命令只有 `pod`（别名 `po`）与 `service`，两者都标 **`[kube-only]`**。参数：`--ignoreUnmeshed`、`--proxy-admin-port`。**无 `-v` 等级参数**（与 proxy-status 不同）。

关键点：**控制面与数据面都读**——走 K8s API 取 Pod/Service/ConfigMap(MeshConfig) 并分析关联的 VirtualService/DestinationRule/Sidecar/Gateway/AuthorizationPolicy，同时抓 live Envoy config_dump 做对比。

> [!WARNING]
> **不支持 ambient**（全文无 waypoint/ztunnel 处理逻辑）。ambient 排障用 `istioctl ztunnel-config`，详见 [Ambient](/docs/CS/Framework/Istio/Ambient.md)。

## `x metrics`：从 Prometheus 查服务指标

> [!IMPORTANT]
> **它不是从控制面读 istiod 指标，而是查 Prometheus。** 实现：找 `app.kubernetes.io/name=prometheus` 的 pod → 端口转发 9090 → 用 PromQL 查询。

查的是 `istio_requests_total`（`reporter="destination"`）与 `istio_request_duration_milliseconds` 的 p50/p90/p99，**全部是服务端视角**，窗口 1 分钟（`-d/--duration` 可调）。支持 `workload.namespace` 形式。

所以它**查不到**控制面指标（`pilot_*`）——那些要用 `istioctl x envoy-stats` 或直接查 istiod。

## `bug-report`：抓现场

关键参数：`-c/--kubeconfig`、`--context`、`--filename`、`--dry-run`、`--proxy-admin-port`（默认 15000）、`--full-secrets`、`--istio-namespace`（默认 `istio-system`）、`--timeout`（**默认 30 分钟**）、`--include` / `--exclude` / `--start-time` / `--end-time` / `--duration`、`--dir`、**`--output-dir`（无 `-o` 简写）**、`--rq-concurrency`（0 → 默认 32）、`--tail`（0=无限）、`--skip-cluster-dump`、`--skip-analyze`、`--skip-proxy-debug`、`--skip-netstat`、`--skip-coredumps`。

> [!WARNING]
> **`--run-gofmt` / `--all` / `--enable-istioctl` 与 `-o` 简写都不存在**（grep 全仓库无匹配）。
>
> **1.31 已改用 k8s API 收集**（`bugreport.go:121-145` 直接构造 `kube.NewCLIClient` + `GetClusterResources`），不再依赖 `kubectl` 子进程。
>
> 产物固定名 **`bug-report.tar.gz`**。超时不丢弃已抓内容——仍保存 archive 并打印提示。

过滤器语法 `ns/dep/pod/lbl=val/ann=val/cntr`，语义是「must be in (ns1 OR ns2) AND (dep1 OR ...)」，label/annotation 之外的 name 支持 `*` glob。

## `x precheck`：安装/升级前检查

`Short`：「Check whether Istio can safely be installed or **upgraded**」。

参数：`--skip-controlplane`、`--output-threshold`（**默认 `Warning`**，注意与 analyze 的 `Info` 不同）、`-o/--output`、`-f/--from-version`、`--revision`。

## 排障命令速查表

| 场景 | 命令 | 关键点 |
| :-- | :-- | :-- |
| 配置静态校验 | `istioctl analyze -A` | 只查配置；**CI 需保留 `-o log` 才有失败退出码** |
| 压制已知噪声 | `analyze -S "IST0102=DestinationRule primary-dr.default"` | 按**消息码=资源名**；资源名可 `*` |
| 全局 xDS 同步 | `istioctl proxy-status` | 1.31 默认列 `SUBSCRIBED TYPES`；收敛看 `STALE (Ns)` 时长是否增长 |
| 逐类型同步 | `istioctl proxy-status -v 1` | 恢复 CDS/LDS/EDS/RDS 逐列 |
| 单 proxy 差异 | `istioctl proxy-status <pod.ns>` | 走 sync diff（istiod 视角 vs 实际 dump） |
| VM 上的 proxy-status | `istioctl proxy-status -f -` | `--file -` 读 stdin；VM 无 k8s API |
| 查 VM 的 cluster | `curl -s localhost:15000/config_dump \| istioctl pc clusters --file -` | **VM 上必须 `--file`** |
| 查 VM 证书 | `curl -s localhost:15000/config_dump \| istioctl pc secret --file -` | 关注 `STATUS` / `VALID CERT` / `NOT AFTER` |
| 改 Envoy 日志级别 | `istioctl pc log <pod> --level http:debug,redis:debug` | 7 档；改的是 **Envoy**；无 `--tail`/`--path` |
| 重置日志级别 | `istioctl pc log <pod> -r` | 默认回退 `warning` |
| 策略是否真到 Envoy | `istioctl x authz check <pod>` | 读 Envoy 生效配置；支持 `-f` |
| 资源关系梳理 | `istioctl x describe pod <pod>` | 读 k8s API **+** live dump；kube-only、不支持 ambient |
| 服务 RED 指标 | `istioctl x metrics deploy/productpage` | **查 Prometheus**；server-side 视角；查不到 `pilot_*` |
| 抓现场 | `istioctl bug-report --outputDir ./out` | 已用 k8s API；产物 `bug-report.tar.gz`；`--output-dir` 无 `-o` |
| Wasm 插件状态 | `istioctl pc ecds <pod>` | 无 `pc wasm` 子命令 |
| ztunnel 排查 | `istioctl ztunnel-config workload/certificate/policy/connections` | 7 子命令，ambient 专用 |

## 默认值 / 阈值汇总

| 项 | 默认值 |
| :-- | :-- |
| 全局 `--proxy-admin-port` | **15000** |
| `proxy-status -o` / `-v` | `table` / `0` |
| `proxy-config -o` | `short` |
| `pc log -r` 默认级别 | `warning` |
| `pc route --verbose` | **true** |
| `analyze --failure-threshold` | **`Error`** |
| `analyze --output-threshold` / `--timeout` | `Info` / `30s` |
| `x precheck --output-threshold` | **`Warning`**（与 analyze 不同） |
| `x metrics -d` | `1m` |
| `bug-report --timeout` | **30m** |
| `bug-report --rq-concurrency` / `--tail` | 0 → 32 / 0（无限） |
| `x workload entry configure --tokenDuration` | **3600s** |
| `x workload entry configure --ingressService` | `istio-eastwestgateway` |
| `x workload group create --serviceAccount` | `default` |

## Links

- [Istio](/docs/CS/Framework/Istio/Istio.md)
- [Install](/docs/CS/Framework/Istio/Install.md)
- [Ambient](/docs/CS/Framework/Istio/Ambient.md)
- [Observability](/docs/CS/Framework/Istio/Observability.md)
- [VMWorkload](/docs/CS/Framework/Istio/VMWorkload.md)
- [Kubernetes 排障](/docs/CS/Container/k8s/K8s.md)

## References

- <https://istio.io/v1.31/docs/ops/diagnostic-tools/>
- <https://istio.io/v1.31/docs/ops/diagnostic-tools/virtual-machines/>
- <https://istio.io/v1.31/docs/reference/istioctl/>
- <https://api.github.com/repos/istio/istio/releases/latest>
