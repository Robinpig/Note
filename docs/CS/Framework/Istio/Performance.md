# Istio 性能调优

## Introduction

这一篇要先把一件事说清楚：**关于 Istio 性能，官方给出的量化数据极少，而且比你想象的少得多。** 性能页整页 130 行里，没有「降低延迟的建议」章节，没有 P90/P99 的数值表格（只有两张位图），没有 mTLS 的 CPU 开销数字，没有日志级别的影响数字，连「telemetry filter 有多少开销」都只有一句定性的 "moderate impact"。

所以调优必须建立在**源码事实上**而不是"调大数字试试"上。本文标注了每条结论的出处，包括「官方未给出量化数据」的地方——那些地方恰恰是最容易被编造的地方。

版本基线：**Istio 1.31.1**（2026-09-21 发布）。性能数据来源：官方 performance 页（`/v1.31/docs/ops/deployment/performance-and-scalability/`）+ `istio-1.31.1` tarball 源码 Grep。

> [!WARNING]
> **官方性能页在 `/v1.31/` 路径下依然标注「Performance summary for Istio 1.24」。** 三个标题硬编码 1.24，配图文件名是 `istio-1.24.0-fortio-90.png` / `-99.png`。
>
> 即：**1.31 文档站的资源与延迟数字是 1.24 实测数据的沿用，不是 1.31 重新测量。** 引用时必须标注 1.24。

## 官方数据（标注 1.24）

测试条件：1000 http req/s、1 KB payload。

| 组件 | vCPU | 内存 | 条件 |
| :-- | :-- | :-- | :-- |
| 单 sidecar proxy | ≈ **0.20** | 60 MB | 2 worker threads |
| 单 waypoint proxy | ≈ **0.25** | 60 MB | 2 worker threads |
| 单 ztunnel proxy | ≈ **0.06** | 12 MB | 未标注线程数 |

> [!IMPORTANT]
> **waypoint 单实例比 sidecar 更贵**（0.25 vs 0.20 vCPU）。ambient 省的是**代理数量**（N 个 sidecar → 1 个共享 waypoint），不是单实例开销。这与「ambient 更省资源」的直觉相反，值得在容量规划时说清楚。

内存规律（官方原话）：「The memory consumption of the proxy depends on the **total configuration state** the proxy holds. A large number of listeners, clusters, and routes can increase memory usage.」

即**代理内存主要由配置量决定**——这是 `Sidecar` 收敛与配置拆分最重要的理论依据。

延迟对比只有四个系列定义（`no mesh` / `ambient: L4` / `ambient: L4+L7` / `sidecar`），**数值只在位图里，文本中不存在**。测试环境：5 台 M3 Large 裸金属 + Flannel，http/1.1、1 KB payload、500/750/1000/1250/1500 RPS、**4 client connections**、**2 proxy workers**、**mutual TLS enabled**（CNCF Community Infrastructure Lab，官方注明「Different hardware will give different values」）。

> [!NOTE]
> **不要在笔记里填任何具体延迟毫秒数**——官方文本里没有，只能读图。

延迟机制上有一条值得引用的说明：Envoy 在响应发回客户端**之后**才收集 raw telemetry，该时间不计入单请求总耗时，但因 worker 仍被占用会推高**下一个请求的排队等待**——所以它影响的是平均与尾延迟，而非单请求延迟。

## 最核心的调优项：CPU limit 决定 worker 线程数

这是本篇最实用、也最容易踩的一条。

`concurrency` **没有静态默认值**。`DefaultProxyConfig()` 不设置该字段，实际逻辑在 `pilot/cmd/pilot-agent/config/config.go:63-84`：

```go
// Concurrency wasn't explicitly set
if proxyConfig.Concurrency == nil {
    // We want to detect based on CPU limit configured. If we are running on a 100 core machine, but with
    // only 2 CPUs allocated, we want to have 2 threads, not 100, or we will get excessively throttled.
    if CPULimit != 0 {
        proxyConfig.Concurrency = wrapperspb.Int32(int32(CPULimit))
    }
}
```

链路是：Pod annotation `sidecar.istio.io/proxyCPU` → 写入容器 `limits.cpu` → Downward API 以 `divisor: "1"`（**向上取整**）读出 `ISTIO_CPU_LIMIT` → concurrency 取该值。

**所以 `proxyCPU: 4000m` → concurrency = 4；`proxyCPU: 2500m` → concurrency = 3**（官方 release note 原文举例）。

> [!WARNING]
> **`concurrency=0` 是危险值。** 若最终 concurrency 为 0 且 `CPULimit < runtime.NumCPU()`，pilot-agent 会打 warning：「concurrency is set to 0, which will use a **thread per CPU on the host**. However, CPU limit is set lower. This is not recommended and may lead to performance issues.」
>
> 即：**在 100 核机器上只给 2 核 limit 而 concurrency=0，Envoy 会起 100 个线程** ——严重 throttling。

> [!IMPORTANT]
> **1.31 起这段逻辑在 sidecar 与各类 gateway 间统一了**（`releasenotes/notes/fix-concurrency.yaml`）：
> - 之前：sidecar 走这段逻辑（但 CPU limit 识别有时不准）；**gateway 从不自动适配**
> - 现在：两者统一，`ProxyConfig.Concurrency` 优先，未设则按 CPU limit 推导
> - 要恢复旧 gateway 行为（用满所有核）可设 `concurrency: 0`，但**官方建议改为直接取消 CPU limits**

**调优实操**：给 sidecar 设 CPU limit 时必须同时想清楚线程数。CPU limit 设 1 核但实际需要吞吐时，线程数会被限死；不设 limit 又会让 concurrency 跟随宿主机核数（在大核机器上线程过多）。两者都要成对考虑。

## 启动与优雅停机

| 参数 | 1.31 状态 | 默认 |
| :-- | :-- | :-- |
| `holdApplicationUntilProxyStarts` | **已 deprecated**，仍生效 | **false** |
| `terminationDrainDuration` | 有效 | **5s** |
| `drainDuration` | 有效 | **45s** |
| `waitForProxyReady` | **1.31.1 完全不存在**（全仓零命中） | — |

`holdApplicationUntilProxyStarts` 判断逻辑是两处 `GetValue().GetValue()`（meshConfig 级或 `values.global.proxy` 级），皆未配置即 false。设为 true 时把 proxy 容器**排到最后**并注入 `postStart` 阻塞 hook，使应用容器在 Envoy 就绪前不启动——缩短「应用已启动但代理未就绪」窗口，代价是 Pod 就绪变慢。**官方未给出任何量化影响数据。**

> [!WARNING]
> **两个 drain duration 极易混淆**：
> - `drainDuration` = **45s**，Envoy `/drain_listeners` 的时长
> - `terminationDrainDuration` = **5s**，agent 侧等待 drain 完成的时长，超时则强制退出（日志 `Graceful termination period is %v, starting...`）
>
> 注入时若等于默认值会被剔除（写不写默认值等价）。

## 不要收紧熔断阈值

Istio 把 4 个 circuit breaker 阈值**全部设为 `MaxUint32`**（等于取消限制），源码注释解释了原因（`cluster_traffic_policy.go:472-483`）：

> "Envoy defaults this value to 3, however that has shown to be **insufficient during periods of pod churn** (e.g. rolling updates), where multiple endpoints in a cluster are terminated. In these scenarios the circuit breaker can **kick in before Pilot is able to deliver an updated endpoint list** to Envoy, leading to **client-facing 503s**."

> [!IMPORTANT]
> **这是全篇最有价值的调优洞察**：熔断阈值**不是** Istio 场景下的默认瓶颈。盲目收紧会在 Pod 滚动更新期间引发 503——因为熔断基于本地观测，比 istiod 下发新 endpoint 列表更快。
>
> 真正的瓶颈通常是 **worker 线程数与 CPU limit**。

补充语义：

- **`consecutive5xxErrors > 0` 时，Istio 把该事件的 enforcing percentage 强制设为 100%**（命中 N 次即 100% 生效）
- **成功率型熔断被强制禁用**（`EnforcingSuccessRate = 0`）——Istio 不支持基于成功率的异常检测
- `baseEjectionTime` Istio 侧**仅透传**给 Envoy，源码未见乘数累加；「每次驱逐时长递增」是 **Envoy 自身**的行为
- `maxEjectionPercent` 仅在 `> 0` 时下发，**唯一可被完全省略的字段**（默认 0 时不覆盖 Envoy 默认 10）。源码没有把它写成「特殊处理」，那是我先前的误解
- **`minHealthPercent` 只要定义了 `outlierDetection` 就无条件覆盖** panic threshold：条件是 `>= 0` 而非 `!= nil`，且它是 `int32` 非指针 → 默认 0 生效时把 Envoy 的 50 覆盖为 0

> [!NOTE]
> **`outlierDetection` 与地域感知 failover 是隐式联动的。** proto 注释：配置 `OutlierDetection` 会**自动激活 locality-aware failover**（Envoy 用异常检测状态决定何时切到下一个 locality）。要抑制须显式设 `localityLbSetting.enabled: false`。

## 负载均衡与预热

- `localityLbSetting` **默认启用**（`mesh.go:85-87`）
- `warmupDurationSecs` **确认 deprecated**（`cluster_traffic_policy.go:423`），但代码保留兼容分支，**仍可生效**
- 新式 `warmup` 默认值：`aggression` = **1.0**（线性爬坡）、`minimumPercent` = **10%**（对齐 Envoy 默认）
- **ZAR（Zone-Aware Routing）默认开启**；`zoneAwareLbSetting.enabled: false` 会显式下发 `routing_enabled: 0%` 来抑制 Envoy 的内建行为
- `DestinationRule` 里的 `localityLbSetting` **覆盖** mesh 级设置

> [!NOTE]
> **`adaptiveConcurrency` 在 Istio 侧没有 API。** 全仓唯一命中是 `filter_types.gen.go:130` 的自动生成全量 filter 类型导入清单——**不是** Istio 对它的启用或推荐。`ProxyConfig` / `Telemetry` 都没有对应字段。要用只能通过 `EnvoyFilter` 手动 patch，且**官方未给出任何性能数据或推荐**。

## DNS 代理

> [!IMPORTANT]
> **`ISTIO_META_DNS_CAPTURE` 默认 `false`**（常被搞反）。源码注册：`env.Register("ISTIO_META_DNS_CAPTURE", false, ...)`。它只出现在 **preview profile**，default/stable 都不含。

实际生效还需三个 DNS 开关同时满足，否则**静默关闭**并打警告（`capture/run.go:236-241`）：`REDIRECT_DNS` 开启、`CAPTURE_ALL_DNS` 或提供了 `DNSServersV4/V6` 非空。

| 项 | 默认值 |
| :-- | :-- |
| `DNS_PROXY_ADDR` | `localhost:15053` |
| `ISTIO_META_ENABLE_DNS_SERVER` | `false`（启动 DNS server 但不自动捕获） |
| `DNS_FORWARD_PARALLEL` | `false` |
| `meshConfig.dnsRefreshRate` | **60s** |

`dnsRefreshRate` 提到 60s 的原因写在注释里：Envoy 不遵守 RFC2308 的负缓存 TTL，提高它是为了避免压垮 DNS 服务器。

> [!WARNING]
> **`DNS_CAPTURE_POLICY` 在 1.31.1 不存在**（全仓零命中）。**agent DNS 缓存大小也没有暴露可调项**（`pkg/dns/client/` 下 grep `cacheSize` 零命中）。
>
> 同样**不存在**的：`ISTIO_META_HTTP10`、`ISTIO_META_FALLBACK_LEGACY_ISTIO_MUX_ENABLED`（均为 Go 文件零命中）。

## 控制面调优

### 配置规模：4M 是硬边界

`pilot_xds_config_size_bytes` 的 buckets 注释（`pilot/pkg/xds/monitoring.go:110-112`）直接给出了判断依据：

> `// Important boundaries: 10K, 1M, 4M, 10M, 40M`
> `// 4M default limit for gRPC, 10M config will start to strain system, 40M is likely upper-bound`

即 **4M = gRPC 默认上限，10M 开始有系统性压力，40M 是支持上界**。这个 4 MiB 就是 `ISTIO_GPRC_MAXRECVMSGSIZE`（`pilot/pkg/features/tuning.go:33-37`），也正是 ztunnel 重连 WDS 请求超限失败的同一个常量——`grpc.MaxRecvMsgSize(maxRecvMsgSize)` 应用在 istiod 的 gRPC server 上。

### 推送节流与并发

| 变量 | 默认值 | 作用 |
| :-- | :-- | :-- |
| `PILOT_DEBOUNCE_AFTER` | **100ms** | 配置事件去抖延迟，追加到推送前 |
| `PILOT_DEBOUNCE_MAX` | **10s** | 去抖上限 |
| `PILOT_ENABLE_EDS_DEBOUNCE` | **true** | 把 EDS 纳入去抖 |
| `PILOT_PUSH_THROTTLE` | `0` → 自动 `min(15+5*procs, 100)` | 推送并发上限 |
| `PILOT_MAX_REQUESTS_PER_SECOND` | `0.0` → 自动 `min(15+5*procs, 100.0)` | 每秒请求上限 |
| `ISTIO_GPRC_MAXSTREAMS` | **100000** | |
| `PILOT_XDS_CACHE_SIZE` | **60000** | XDS 缓存条目数 |
| `PILOT_XDS_CACHE_INDEX_CLEAR_INTERVAL` | **5s** | |
| `PILOT_XDS_CACHE_STATS` | **false** | 开启缓存效率指标 |
| `PILOT_STATUS_MAX_WORKERS` | **100** | |

`PILOT_ENABLE_EDS_DEBOUNCE` 是**延迟 vs 推送量**的直接权衡，原文：「EDS pushes may be delayed, but there will be fewer pushes. **By default this is enabled**」。

> [!NOTE]
> `PILOT_PUSH_THROTTLE` 的自动伸缩启发式注释给出了对照表：`1: 20` / `2: 25` / `4: 35` / `32: 100`——**1 核仅 20 并发推送，32 核封顶 100**。这是控制面横向扩容的主要依据。
>
> **`PILOT_DEBOUNCE_BEFORE` 不存在**（全仓 4 个命中全在 AFTER/MAX）。

`pilot_debounce_time` 的语义要读准：是「**首个**配置进入 debouncing 到合并推送入队」的延迟，**包含 pushContext 初始化时间**。

### 开关清单（逐个核实，区分已移除）

**真实存在**：

| 变量 | 默认 | 作用 |
| :-- | :-- | :-- |
| `PILOT_FILTER_GATEWAY_CLUSTER_CONFIG` | false | 只下发 gateway VS 引用的 cluster，**直接降低配置量** |
| `PILOT_ENABLE_XDS_CACHE` / `CDS` / `RDS` | true | 三层缓存（CDS/RDS 可单独关，便于隔离问题） |
| `PILOT_ENABLE_XDS_IDENTITY_CHECK` | **true** | 授权 XDS 客户端限制其作用域 |
| `PILOT_SCOPE_GATEWAY_TO_NAMESPACE` | false | gateway 只能选同 ns 的 gateway 资源 |
| `PILOT_ENABLE_REDIS_FILTER` | false | 注入 `redis_proxy` 过滤器 |
| `AMBIENT_SCOPED_ADDRESS_PUSHES` | **true** | Address 更新只推受影响的 waypoint；**关闭会导致全量 LDS/CDS/EDS 推送** |

> [!TIP]
> **`AMBIENT_SCOPED_ADDRESS_PUSHES` 是直接的推送量优化开关。** 它的说明原文：关闭后「every Address update triggers a full LDS/CDS/EDS push to all waypoints and an RDS push to all proxies」。

**1.31 已移除（不可当现存开关）**：

| 变量 | 移除证据 |
| :-- | :-- |
| `PILOT_ENABLE_HEADLESS_SERVICE_POD_LISTENERS` | `releasenotes/notes/drop-headless.yaml` |
| `PILOT_ENABLE_CONFIG_DISTRIBUTION_TRACKING` | `releasenotes/notes/drop-distribution.yaml`（同时移除 `x wait` 命令） |
| `PILOT_DISABLE_GATEWAY_API_AUTOINSTALL` | **零命中，且无任何移除记录**——既非现存也非「已标记废弃」 |

> [!WARNING]
> `PILOT_ENABLE_HEADLESS_SERVICE_POD_LISTENERS` 在 `pilot/pkg/networking/core/tls.go:198` 的**注释**里仍被提及（写「enabled (by default)」）——属**过时注释残留**，容易误判为仍存在。

### `Sidecar` 收敛与 istiod 扩容

`Sidecar` 会收敛这 6 类配置：`Endpoints` / `ServiceEntry` / `VirtualService` / `DestinationRule` / `Sidecar` / `PeerAuthentication`。

`egress.hosts` 的 `~` 前缀**只作用于 namespace 段**（`/` 之前），host 必须严格 `namespace/dnsName`；`~` 后 ns 为空退化为 `*`。

> [!NOTE]
> **`~` 语法在 1.31.1 确实生效**（`sidecar.go:43,507-513`），但**未找到「1.31 新增」的 release note**。写「1.31.1 已支持」是有据的，写「1.31 新增」查不到出处。

官方对 `Sidecar` 的表述只有一句：`At large scale, **configuration scoping is highly recommended**.`

**istiod HPA 的默认指标是 CPU 利用率**（不是自定义指标）：`cpu.targetAverageUtilization` 默认 **80**，`autoscaleMin: 1` / `autoscaleMax: 5`。性能页**没有**提到 HPA 或任何指标名——HPA 模板来自 Helm chart。

> [!NOTE]
> `warmup` 之外的 `PILOT_CONVERT_SIDECAR_SCOPE_CONCURRENCY`（默认 1）已 deprecated。

## 日志级别

| 组件 | 默认 |
| :-- | :-- |
| sidecar / waypoint / ingress-gateway / egress-gateway | **`warning`** |
| ztunnel | **`info`** |

可选值：`trace|debug|info|warning|error|critical|off`。Pod annotation `sidecar.istio.io/logLevel` 可覆盖。

> [!NOTE]
> **官方未给出日志级别对性能的任何量化影响。** 唯一的官方表述是 telemetry filters（logging/tracing/metrics）「are known to have a **moderate impact**」——纯定性。
>
> **生产建议保持默认 `warning`**：这是唯一有官方背书的值。

追踪采样率同理——`PILOT_TRACE_SAMPLING` 默认 **1.0**（demo profile 为 100），但**官方没有给 1% 采样的性能影响数据**。不可编造「1% 采样节省 X% CPU」这类数字。

## 基准工具

官方只列三项，**全不含版本号**：[fortio.org](https://fortio.org/)（constant throughput load testing）、[nighthawk](https://github.com/envoyproxy/nighthawk)（基于 Envoy）、[isotope](https://github.com/istio/tools/tree/release-1.31/isotope)（合成应用，可配拓扑）。

`istioctl x benchmark` **不存在**。基准脚本在独立仓 `istio/tools`（`perf/benchmark`、`perf/load`），不在主仓 tarball 内。

## 官方推荐调优清单（含证据强度）

| # | 推荐项 | 证据 |
| :-- | :-- | :-- |
| 1 | 大规模场景启用 **configuration scoping** | 官方原文推荐，**无量化** |
| 2 | **增加 istiod 实例数**缩短配置下发时间 | 官方原文，**无量化** |
| 3 | CPU limit 与 worker 线程数**成对考虑**（1.31 起统一） | ✅ 有具体换算（2500m→3） |
| 4 | 避免 `concurrency=0` 配 CPU limit | 源码 warning，**无量化** |
| 5 | ztunnel `requests.cpu` 控制在 2 核以内 | ⚠️ 仅 2 核这个阈值 |
| 6 | ztunnel 内存按 ~200k pod / 100k 并发连接规划 | ✅ 有量化锚点 |
| 7 | 保持代理日志级别 `warning` | **仅定性**（moderate impact） |
| 8 | 关注 `pilot_xds_config_size_bytes`：**4M/10M/40M 三条边界** | ✅ 明确边界 |
| 9 | `AMBIENT_SCOPED_ADDRESS_PUSHES` 保持 `true` | 定性（关闭触发全量推送） |
| 10 | `PILOT_XDS_CACHE_STATS=true` 开启缓存可观测 | **无量化** |
| 11 | `PILOT_FILTER_GATEWAY_CLUSTER_CONFIG=true` 收敛 gateway cluster | **无量化** |
| 12 | **不要收紧熔断阈值** | ✅ 有源码注释说明 503 因果 |
| 13 | 用 `Sidecar` 收敛 egress 范围 | 官方推荐 + 源码确认收敛 6 类配置 |

## 官方未给量化数据的项（不可编造）

- 关闭 mTLS 能省多少 CPU
- telemetry filter（logging/tracing/metrics）的具体开销百分比
- 1% 追踪采样率的性能影响
- 日志级别对 CPU 的量化影响
- `holdApplicationUntilProxyStarts` 对启动时间的影响
- 延迟降低的具体建议清单（整页无此章节）
- 各 `PILOT_ENABLE_*` 开关的性能收益
- P90/P99 的具体数值（仅存在于位图）

## 排障速查

| 现象 | 先查 |
| :-- | :-- |
| sidecar CPU 高但吞吐上不去 | `limits.cpu` → `ISTIO_CPU_LIMIT` → concurrency 是否被限死；是否 `concurrency=0` 在大核机器上起过多线程 |
| 代理内存持续增长 | 配置量（listeners/clusters/routes 数），优先用 `Sidecar` 收敛 |
| 改配置后收敛慢 | `pilot_proxy_convergence_time` 区分控制面慢 vs 代理不 ACK；看 `pilot_debounce_time` |
| 配置推送量过大 | `pilot_xds_config_size_bytes` 是否接近 4M/10M；EDS 去抖是否开着 |
| Pod 滚动更新时出现 503 | **大概率是熔断阈值被收紧了**（Istio 默认是 MaxUint32 就是为避开这个） |
| 实例被驱逐后恢复很慢 | `baseEjectionTime` 只是基础时长，递增由 Envoy 实现；检查 `maxEjectionPercent` 是否被省略 |
| 控制面成为瓶颈 | `PILOT_PUSH_THROTTLE` 的自动值看 CPU 核数（1 核仅 20 并发）；HPA 默认按 CPU 80% |
| DNS 捕获不生效 | `ISTIO_META_DNS_CAPTURE` 默认 false，且需 `CAPTURE_ALL_DNS` 或提供 DNS server 列表，否则静默关闭 |
| ambient 推送全量 | 确认 `AMBIENT_SCOPED_ADDRESS_PUSHES` 未被设为 false |

## Links

- [Istio](/docs/CS/Framework/Istio/Istio.md)
- [Install](/docs/CS/Framework/Istio/Install.md)
- [Ambient](/docs/CS/Framework/Istio/Ambient.md)
- [Observability](/docs/CS/Framework/Istio/Observability.md)
- [TrafficManagement](/docs/CS/Framework/Istio/TrafficManagement.md)
- [Troubleshooting](/docs/CS/Framework/Istio/Troubleshooting.md)

## References

- <https://istio.io/v1.31/docs/ops/deployment/performance-and-scalability/>
- <https://istio.io/v1.31/docs/ops/configuration/mesh/configuration-scoping/>
- <https://istio.io/v1.31/news/releases/1.31.x/announcing-1.31/change-notes/>
- <https://github.com/istio/tools/tree/release-1.31>
- <https://api.github.com/repos/istio/istio/releases/latest>
