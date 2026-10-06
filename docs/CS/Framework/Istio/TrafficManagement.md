# Istio 流量治理

## Introduction

流量治理是 Istio 最常用、也最容易被「二手博客写法」坑的一块。流传最广的一批错误认知包括：`faultInjection` 字段名、`weight` 必须加起来等于 100、「熔断会把不健康实例从 EDS 里摘掉」、`backoff` 是带 `baseInterval` 的对象——这些在 1.31 里**全都不成立**，而且其中几处写错会被 CRD schema 直接拒绝，表现为「配置就是不生效」。

版本基线：**Istio 1.31.1**（2026-09-21 发布），官方支持 Kubernetes **1.32 ~ 1.36**。以下字段名、默认值与限制逐条核实自 `istio/api` 与 `istio/istio` 的 `release-1.31` 分支 proto/CRD 源码及 `pilot/` 下的翻译代码；官方未给出的一律标注「未查到」。

## 治理能力的归属：两个 CRD 的分工

| CRD | 回答的问题 | 典型字段 |
| :-- | :-- | :-- |
| `VirtualService` | **怎么分流、怎么处理请求**（L7 逻辑） | `http[].match` / `route` / `weight` / `timeout` / `retries` / `fault` / `mirror` / `redirect` / `rewrite` |
| `DestinationRule` | **连接对端时怎么连、怎么选、怎么熔断**（策略） | `trafficPolicy.loadBalancer` / `connectionPool` / `outlierDetection` / `tls` / `retryBudget` |

一句话记法：**`VirtualService` 决定「去哪个 subset、带什么条件」，`DestinationRule` 决定「这个 subset 内部怎么选实例、连不上怎么办」。**

## 流量分割：金丝雀与 A/B

### `weight` 的真实语义是相对比例

```yaml
apiVersion: networking.istio.io/v1
kind: DestinationRule
metadata:
  name: reviews
spec:
  host: reviews
  subsets:
  - name: v1
    labels:
      version: v1
  - name: v3
    labels:
      version: v3
---
apiVersion: networking.istio.io/v1
kind: VirtualService
metadata:
  name: reviews
spec:
  hosts:
  - reviews
  http:
  - route:
    - destination:
        host: reviews
        subset: v1
      weight: 50
    - destination:
        host: reviews
        subset: v3
      weight: 50
```

> [!WARNING]
> **「weight 之和必须为 100」不成立。** proto 原文的语义是相对比例：`weight / (sum of all weights)`。校验代码只做两件事——`weight < 0` 报错；**仅当 `len(weights) > 1 && totalWeight == 0`** 才报错。所以 `50/50`、`7/3`、`100/1` 都可以。
>
> **「不写 weight 默认 1.0」也不成立。** `weight` 是 `int32`，CRD 里**没有 `default` 关键字**，不写就是 Go 零值 **0**。单 destination 规则下不写 weight 之所以等效于 100%，是因为 `len(weights)==1` 时 total=0 不报错且该 destination 独占——**不是默认值是 1.0**。
>
> 这个零值在多目标下就有害：**多 destination 规则里不写 weight 等于权重 0**，会被 `route.go` 的 `if len(in.Route) != 1` 分支直接丢弃、不生成 cluster。

`weight: 0` 本身是合法的，proto 明确「will not receive any traffic」；但同样是多目标时会被丢弃。

### 金丝雀 vs A/B：机制不同

| 模式 | 机制 | 特征 |
| :-- | :-- | :-- |
| **金丝雀** | 同一 `route[]` 内按 `weight` 随机分流 | 无 `match` 条件，靠 Envoy 随机选 cluster |
| **A/B（按 header）** | 多条规则顺序匹配 + catch-all 兜底 | 第一条带 `match` 命中即返回 |

A/B 官方示例（bookinfo）：

```yaml
http:
- match:
  - headers:
      end-user:
        exact: jason
  route:
  - destination:
      host: reviews
      subset: v2
- route:
  - destination:
      host: reviews
      subset: v1
```

这与「route 匹配是纯顺序优先、无精确优先」的既有认知一致：concepts 页原文「Routing rules are evaluated in sequential order from top to bottom, with the first rule in the virtual service definition being given highest priority」。

> [!NOTE]
> **「蓝绿部署」在 istio.io 1.31 中没有独立文档**——`/docs/tasks/traffic-management/continuous-blue-green-deployment/` 返回 404，概念页也不出现 "blue-green" 字样。蓝绿其实就是 weight 的极端值（100/0 切换）或 header 路由。
>
> **cookie 路由官方也无示例**——cookie 本质是 header，用 `match[].headers.cookie.regex` 即可，但 concepts 页的 cookie 只出现在 `consistentHash` 说明里。

### `match[].headers` 的三个细节

`headers` 是 `map<string, StringMatch>`，**header 名直接作为 map key，没有 `name` 字段**：

```yaml
match:
- headers:
    x-request-id:
      exact: "abc"
    myheader: {}          # 空 match = 仅检查存在性
```

- `exact` / `prefix` / `regex` 是 **oneof 互斥**（CRD 用 CEL 强制）。
- **不存在 `present` 字段**——存在性检查的写法是**空 match `{}`**。
- **key 必须小写并用连字符**（proto：*"The header keys must be lowercase and use hyphen as the separator, e.g. x-request-id."*），校验代码会对非法名字告警。**value 区分大小写**（`exact`/`prefix`），`regex` 可用 RE2 内联 `(?i)` 做不敏感匹配。
- `withoutHeaders` 语法相同但语义相反；其 `regex: "*"` 被源码**特判**为「存在即匹配」（注释明确「`*` is NOT a RE2 style regex, it will be translated to present_match」）。

`match` 与 `weight` **可以同时存在**且是标准用法——校验函数 `validateHTTPRouteMatchRequest` 与 `validateHTTPRouteDestinations` 相互独立，没有互斥规则。

## 熔断与连接池

### 1.31 没有迁移 CRD 路径

先澄清一个常见疑问：`TrafficPolicy` **仍是 `DestinationRule.spec.trafficPolicy` 的嵌套 message，不是独立 CRD**。1.31 的 CRD 清单里**不存在** `trafficpolicies` 资源。所谓「旧字段」`loadBalancer.simple` / `outlierDetection.*` / `connectionPool.tcp.maxConnections` **均未标记 deprecated**，全是现行字段。

```yaml
trafficPolicy:
  loadBalancer: {...}
  connectionPool:
    tcp: {...}
    http: {...}
  outlierDetection: {...}
  tls: {...}
  portLevelSettings: []
  tunnel: {...}
  proxyProtocol: {...}
  retryBudget: {...}
```

### connectionPool 默认值：几乎全是不限制

| 字段 | 实际运行时默认 | 备注 |
| :-- | :-- | :-- |
| `tcp.maxConnections` | `2^32-1`（MaxUint32） | 不限制 |
| `tcp.connectTimeout` | **10s** | |
| `tcp.idleTimeout` | **1 hour** | `0s` = 禁用 |
| `tcp.maxConnectionDuration` | 无上限 | 不设即无限制 |
| `http.http1MaxPendingRequests` | `2^32-1` | 不限制 |
| `http.http2MaxRequests` | `2^32-1` | 不限制 |
| `http.maxRequestsPerConnection` | **0 = 不限**（上限 2^29） | **设为 1 = 禁用 keep-alive** |
| `http.maxRetries` | `2^32-1` | **不是 Envoy 默认的 3** |
| `http.idleTimeout` | 1 hour | |
| `http.maxConcurrentStreams` | `2^31-1` | |
| `http.h2UpgradePolicy` | `DEFAULT` | |

`http.maxRetries` 之所以不用 Envoy 的 3，源码注释解释了原因：pod 滚动更新时 endpoint 被批量终止，3 不足以覆盖，**熔断会先于 xDS 下发触发**，导致客户端 503。

> [!WARNING]
> **显式写 `0` 与不写完全等价。** `http1MaxPendingRequests`、`http2MaxRequests`、`maxRetries`、`maxConnections` 的翻译条件都是 `if X > 0`。源码留了 FIXME：「zero is a valid value if explicitly set, otherwise we want to use the default」——这是 Istio 侧已知的未决问题。**要限制必须写正数。**

`maxConnections` 是**每实例**上限（Envoy 的 circuit breaker threshold 按 upstream host 分别计数），`maxConnections: 100` 意味着每个 endpoint 100 条连接。

**`connectionPool.http.proxyProtocol` 不存在**——PROXY protocol 只在顶层 `trafficPolicy.proxyProtocol.version`（默认 `V1`）。

### outlierDetection 的默认值与两个隐式联动

| 字段 | 文档默认 | 实际行为 |
| :-- | :-- | :-- |
| `consecutive5xxErrors` | **5** | 设 0 = 禁用 |
| `consecutiveGatewayErrors` | 禁用 / 0 | |
| `consecutiveLocalOriginFailures` | 5 | **仅当 `splitExternalLocalOriginErrors: true` 才生效**（双重条件） |
| `splitExternalLocalOriginErrors` | `false` | false 时完全不生效 |
| `interval` | **10s** | |
| `baseEjectionTime` | **30s** | **实际驱逐时长 = 30s × 该 host 已驱逐次数**（递增） |
| `maxEjectionPercent` | **10%** | |
| `minHealthPercent` | **0%** | 见下方联动 |
| `outlierDetectionHttpErrorCodes` | 不设 = 仅 5xx | 取值范围 [100,599] |

字段间的**官方明示关系**：

> "Because the errors counted by `consecutiveGatewayErrors` are also included in `consecutive5xxErrors`, if the value of `consecutiveGatewayErrors` is greater than or equal to the value of `consecutive5xxErrors`, `consecutiveGatewayErrors` will have no effect."

即 `consecutiveGatewayErrors` 设得比 `consecutive5xxErrors` 大就完全无效。

**隐式联动一：配了 outlierDetection 就自动开启地域感知 failover。** `OutlierDetection` message 头部注释：

> "Istio's default mesh configuration enables locality load balancing (`localityLbSetting.enabled: true`). As a result, configuring `OutlierDetection` in a `DestinationRule` will **automatically activate locality-aware failover behavior** — Envoy uses the outlier detection state to determine when endpoints are unhealthy and should be failed over to the next locality. To suppress this implicit failover, explicitly set `localityLbSetting.enabled: false`."

**隐式联动二：`minHealthPercent` 会被无条件下发。** 源码 `if minHealthPercent >= 0` **总是**设置 `CommonLbConfig.HealthyPanicThreshold`，注释解释：Envoy 的 panic threshold 默认 50，Istio 主动覆盖为 **0**，因为「it is not typically applicable in k8s environments with few pods per service」。

`consecutiveErrors` 是 **`$hide_from_docs` + `deprecated`** 的旧字段。

### 熔断在哪一侧执行：客户端侧

源码 `applyTrafficPolicy` 里，`applyOutlierDetection` 与 `applyLoadBalancer` 都被包在 `if opts.direction != model.TrafficDirectionInbound` 条件内，而 `applyConnectionPool` 在 if 之外（注释：*"Connection pool settings are applicable for both inbound and outbound clusters."*）。

结论：

- **连接池 / 熔断阈值**：inbound + outbound **都下发**。
- **异常点检测（outlierDetection）与 LB**：**仅 outbound（客户端侧）下发**。

即异常检测由**发起调用的一方**（ingress gateway / 源工作负载的 sidecar / waypoint）执行，服务端 sidecar 不参与。

**被摘除的 endpoint 只在 LB 池内排除，不从 EDS 摘除。** Envoy outlier detection 是**集群内部**的 host 状态机，`ejected_hosts` 只作用于 LB 选择，不修改 EDS 成员。

> [!NOTE]
> **1.31 起 Istio 默认把 unhealthy endpoint 也发到 EDS**（带健康状态标记，让 Envoy 自行按比例规避），**除非**你在 `DestinationRule` 里显式设了 `outlierDetection.minHealthPercent > 0`——只有那时 Istio 才在 EDS 层面过滤掉 unhealthy endpoint。可用 `PILOT_AUTO_SEND_UNHEALTHY_ENDPOINTS=false` 关闭。这是 1.31 对异常检测行为影响最大的一条变更。

## 重试与超时

### `retries.attempts` 不含初始请求

| 字段 | 默认值 | 说明 |
| :-- | :-- | :-- |
| `attempts` | API 无默认（0）；**运行时 2** | 整块省略 → 走 `meshConfig.defaultHttpRetryPolicy` |
| `retryOn`（运行时） | `connect-failure,refused-stream,unavailable,cancelled,retriable-status-codes` | |
| `perTryTimeout` | = route 的 `timeout`；若 route 也无 → 无超时 | MUST ≥ 1ms |
| `backoff` | 25ms（指数退避 base interval） | **是 Duration，不是对象** |
| `retryIgnorePreviousHosts` | `true` | |

> [!WARNING]
> **`attempts` 不含初始请求。** proto 原文一字不改：*"The maximum possible number of requests made will be 1 + `attempts`."* → `attempts: 3` = 最多 **4 次**请求。
>
> **`attempts: 0` 是「完全禁用重试」，不是「用默认值」。** 显式写 0 走 `if in.Attempts <= 0 { return nil }` 返回 nil。真正的默认 2 来自 `retries` 整块**被省略**时的 fallback。
>
> **`backoff` 不是 `baseInterval` 的父对象**——它是单个 Duration。传 `backoff: 2s` 而非 `backoff: {baseInterval: 2s}`。

> [!WARNING]
> **`retryOn` 的运行时默认值比文档多一项。** proto 注释与 MeshConfig 注释都写 `connect-failure,refused-stream,unavailable,cancelled`，但源码常量 `defaultRetryOn` 实际是 `connect-failure,refused-stream,unavailable,cancelled,retriable-status-codes`（多 `retriable-status-codes`）。**以运行时为准。**

`retryOn` 的完整可取值在 **Envoy 官方文档**（Istio 侧只给默认值 + 外链，未列全）：`5xx`、`gateway-error`、`reset`、`reset-before-request`、`connect-failure`、`envoy-ratelimited`、`retriable-4xx`、`refused-stream`、`retriable-status-codes`、`retriable-headers`、`http3-post-connect-failure`。

Istio 有一个便利行为：`parseRetryOn` 会把逗号串里**能解析为合法 HTTP 状态码的项**剥离到 Envoy 的 `RetriableStatusCodes`，若用户只填了状态码而未含 `retriable-status-codes`，Istio 会**自动追加**该 policy 名。所以 `retryOn: "503,reset"` 是合法有效的。

另有两个 1.31 运行时细节：`HostSelectionRetryMaxAttempts: 5`（无论 `attempts` 写多少，单 host 最多试 5 次才切下一个）；**一致性哈希场景下默认不带 `RetryHostPredicate`**（源码注释：*"When Consistent Hashing is enabled, we don't want to use other hosts during retries."*），即不会跳到其他 host。

### `timeout` 与 `perTryTimeout`

| | `timeout` | `perTryTimeout` |
| :-- | :-- | :-- |
| 作用域 | **整个请求（含所有重试）** | **单次尝试**（含首次调用） |
| 不写时 | **无超时（0）** | 默认 = 同 route 的 `timeout`；若也无 → 同样无超时 |
| 约束 | MUST ≥ 1ms（CRD CEL 校验） | MUST ≥ 1ms；且必须 < 全局 timeout，否则被 Envoy 忽略 |

**Istio 默认禁用 Envoy 的 HTTP 请求超时**——CRD 注释「default is disabled」，concepts 页也明文「The Envoy timeout for HTTP requests is disabled in Istio by default」。源码 `setTimeout` 设 `Notimeout = durationpb.New(0)`；**连没有 VirtualService 时的兜底路由 `BuildDefaultHTTPOutboundRoute` 也是 0**。gRPC 侧 `MaxGrpcTimeout` 同样设 0（`grpc-timeout` 头不被使用）。

Envoy 对 timeout 的语义值得记住（避免超时/重试组合的指数爆炸）：

> "The route timeout **includes** all retries. Thus if the request timeout is set to 3s, and the first request attempt takes 2.7s, the retry (including back-off) has .3s to complete. This is by design to avoid an exponential retry/timeout explosion."

退避算法是**全抖动**（fully jittered）指数退避：base interval 25ms 时，第 1 次重试延迟在 0~24ms，第 2 次 0~74ms，第 3 次 0~174ms；上限是 base 的 10 倍（250ms）。

### `retryHostPredicate` 不存在于 Istio API

1.31 CRD 中 `retryHostPredicate` 出现次数为 **0**。它是 Envoy 侧 `RetryPolicy.RetryHostPredicate` 的概念，Istio 通过 `retryIgnorePreviousHosts` 布尔开关**间接**控制（true → 填入 `RetryPreviousHosts` predicate；false → 置空）。

`retryRemoteLocalities` 则是真实存在的 Istio 字段：设为 true 时下发 Envoy `RetryPriority: envoy.retry_priorities.previous_priorities`，实现「重试到其他 locality」。

## 故障注入

字段名是 **`http[].fault`**——**`faultInjection` 从来不是合法字段**，写了会被 CRD schema 以 unknown field 拒绝。

```yaml
http:
- fault:
    delay:
      percentage:
        value: 0.1      # [0.0, 100.0] double
      fixedDelay: 5s
    abort:
      percentage:
        value: 0.1
      httpStatus: 400
  route:
  - destination:
      host: reviews
      subset: v1
```

| 字段 | 状态 |
| :-- | :-- |
| `fault.delay.fixedDelay` | 存在，MUST ≥ 1ms |
| `fault.delay.exponentialDelay` | **存在但未实现**——`$hide_from_docs`，翻译时打 warn 并**静默丢弃整个 delay** |
| `fault.delay.percentage` | 现行，double，可表达 0.1% |
| `fault.delay.percent` | `deprecated = true`（int32），`percentage` 优先 |
| `fault.abort.httpStatus` | 与 `grpcStatus`、`http2Error` 构成 oneof |
| `fault.abort.grpcStatus` | 填大写名字如 `UNAVAILABLE`，**不是数字 14** |
| `fault.abort.http2Error` | **字段存在但 webhook 直接拒绝**：`HTTP/2 abort fault injection not supported yet` |
| `fault.abort.percent` | **已被删除**（proto `reserved 1; reserved "percent";`） |
| `fault.delay.httpDelay` / `grpcDelay` | **1.31 中不存在**（全 CRD grep = 0） |

必须有 `delay` 或 `abort` 或两者，否则报 `HTTP fault injection must have an abort and/or a delay`。两者**相互独立**，可同时指定。

### 与超时重试的关系：是运行时行为，不是校验

官方原文：

> "Fault injection policy to apply on HTTP traffic **at the client side**. **Note that timeouts or retries will not be enabled when faults are enabled on the client side.**"

> [!IMPORTANT]
> 1.31 的 webhook **完全不检查** fault 与 timeout/retries 的共存——`validateHTTPRouteConflict` 逐条列举了所有互斥组合，**不含此项**。配置会被接受、但客户端侧启用 fault 时另两者不生效。所以故障注入测试要用独立的 VirtualService。
>
> **至于「为什么」未查到官方解释**——proto 注释、istio.io 参考页、fault-injection task 页、concepts 页均未给出原因，此处不做推测。

## 流量镜像

1.31 有**三套**镜像字段（不是两个）：

| 字段 | 类型 | 语义 |
| :-- | :-- | :-- |
| `http[].mirror` | `Destination` | **单个**镜像目标 |
| `http[].mirrors` | `[]HTTPMirrorPolicy` | **多个**目标，每项带自己的 `destination` + `percentage` |
| `http[].mirrorPercentage` | `Percent{double value}` | 只控制 `mirror` 字段 |
| `http[].mirrorPercent` | UInt32Value | `$hide_from_docs` + `deprecated`，使用会触发 webhook warning |

`mirror` 与 `mirrors` **不能同时使用** → `HTTP route cannot contain both mirror and mirrors`。

- **不写 `mirrorPercentage` = 镜像 100% 流量**（官方文档与 task 页均明确）。`mirrors[]` 每项的 `percentage` 缺省同样是 100%。
- **显式写 0 是不镜像**：`MirrorPercent()` 源码中 `value > 0` 才生成策略。
- **镜像请求是 fire-and-forget**：官方原文「these requests are mirrored as "fire and forget", which means that the responses are discarded」；参考页补充「sidecar/gateway **will not wait** for the mirrored cluster to respond」。

> [!NOTE]
> **Istio 未暴露任何镜像超时配置项。** 源码 `TranslateRequestMirrorPolicy` 只设 4 个字段（`Cluster` / `RuntimeFraction` / `TraceSampled=false` / `DisableShadowHostSuffixAppend`），**无 timeout**。也未查到任何 `PILOT_ENABLE_*` 相关的镜像超时开关。
>
> 另一个细节：`DISABLE_SHADOW_HOST_SUFFIX` 环境变量**默认为 `true`**，即 1.31 **默认关闭** `-shadow` 后缀追加（task 文档描述的是旧行为）。

## 重定向与重写

### `redirect` 的 7 个字段

| 字段 | 说明 |
| :-- | :-- |
| `uri` | 替换整个 path（无论原 URI 是精确还是前缀匹配）；**与 `prefixRewrite` 互斥** |
| `authority` | 覆盖 Authority/Host |
| `port` | 覆盖端口 |
| `derivePort` | `FROM_PROTOCOL_DEFAULT`（HTTP→80，HTTPS→443）/ `FROM_REQUEST_PORT`；与 `port` 构成 oneOf |
| `scheme` | 覆盖 scheme；不设则沿用 |
| `redirectCode` | **默认 301** |
| `prefixRewrite` | **1.31 新增**（Issue #47500/#47777/#52521）：替换已匹配的前缀，与 `uri` 互斥 |

> [!WARNING]
> `prefixRewrite` 在 change-notes 与 istio.io 参考页里写作 **`prefix_rewrite`**（snake_case），但 **CRD/proto 中实际是 `prefixRewrite`**（camelCase，CRD 全文 grep `prefix_rewrite` = 0）。Istio CRD 一律 camelCase。

### `rewrite` 与 `RegexRewrite` 的真实字段名

`HTTPRewrite` 字段：`uri` / `authority` / `uriRegexRewrite`。

> [!WARNING]
> **`uriRegexRewrite` 的子字段是 `match` 与 `rewrite`，不是 `regex` / `replacement`。** 这是名字起得反直觉的地方，也是网络流传写法的主要错误来源。

| 字段 | 说明 |
| :-- | :-- |
| `uriRegexRewrite.match` | RE2 风格正则 |
| `uriRegexRewrite.rewrite` | 替换串，**可在其中用 `\1` `\2` 引用捕获组** |

官方示例（verbatim）：路径 `/service/update/v1/api` 配 `match: "^/service/([^/]+)(/.*)$"`、`rewrite: "/customprefix/\2/\1"` → 变成 `/customprefix/v1/api/update`；大小写不敏感用内联 `(?i)`。

`rewrite` 与 `redirect` **互斥**（报 `HTTP route rule cannot contain both rewrite and redirect`），且 rewrite 在转发前执行。

另有一个 1.31 行为：`rewrite.uri == "/"` 且 VS 处于 gateway semantics 时，会被翻译成正则 `^<prefix>(/?)(.*)` → `/\2` 以剥离前缀，而非普通 prefixRewrite。

## 完整的互斥矩阵

源码 `validateHTTPRouteConflict` 的实际规则：

| 组合 | 结果 |
| :-- | :-- |
| `route` + `redirect` | 报错 `HTTP route cannot contain both route and redirect` |
| `route` + `directResponse` | 报错 |
| `redirect` + `rewrite` | 报错 |
| `redirect` + `fault` | 报错 |
| `directResponse` + `fault` | 报错 |
| `directResponse` + `rewrite` | 报错 |
| `mirror` + `mirrors` | 报错 |
| 四者全空 | 报错 `HTTP route, redirect or direct_response is required` |
| delegate 根路由指定 `route` | 报错 `root HTTP route %s must not specify route` |
| `match` + `weight` | **合法**（标准用法） |
| `fault` + `timeout`/`retries` | **webhook 不报错**，但运行时 timeout/retry 不生效 |

## 限流：Istio 没有原生 API

明确核实：**Istio 无论 1.31 还是此前都没有原生的限流 CRD**（社区项目 `istio-ratelimit-operator` 是自建的，非官方）。官方 rate limit task 页原文：

> "Rate limits as described in this document are implemented using the **EnvoyFilter API**. **EnvoyFilter exposes internal implementation details that may change at any time. Please use extreme caution, especially around upgrades.**"

| 方案 | 载体 | 说明 |
| :-- | :-- | :-- |
| **本地限流** | `EnvoyFilter` 注入 `envoy.filters.http.local_ratelimit`（`context: SIDECAR_INBOUND` 或 `GATEWAY`） | token_bucket 三参数；超限返回 **429** |
| **全局限流** | `EnvoyFilter` 注入 `envoy.filters.http.ratelimit`（`context: GATEWAY`）+ **外部 gRPC rate limit service** | 官方示例用 `ratelimit.default.svc.cluster.local:8081` |
| `LocalRatelimit` CRD | **不存在** | 1.31 CRD 清单中无此资源 |

> [!WARNING]
> **istio.io 全站未提及 Higress**。Higress 是基于 Istio 的独立网关产品，其 `extensions.higress.io/v1alpha1 WasmPlugin` 限流插件**不是 Istio 官方方案**——引用时必须说清这层区别。

## 1.31 变更补遗

除已知的 `zoneAwareLbSetting` / `defaultTrafficPolicy` / `ALLOW_ANY_DYNAMIC_DNS` 外：

**新增**

- `HTTPRedirect.prefixRewrite`（前缀感知的重定向重写）
- `connectionPool.http.http2KeepAlive.{interval,timeout}`（上游连接的 HTTP/2 PING）
- `RetryBudget.budgetInterval`——**默认 0ms** = 仅计入在途请求（保持既有行为）
- `ProxyConfig.connectionSettings`——listener buffer 上限、**HTTP 超时**、HTTP/2 设置、路径/header 规范化，含面向 gateway 的 `EDGE` profile
- `EnvoyFilter` 的 `MERGE_AND_REPLACE_LIST` 补丁操作——list 字段**整体替换**而非追加
- `istio.io/ignore-policy-attachment` 注解——在 `BackendTLSPolicy`/`XBackendTrafficPolicy` 上阻止 Istio 翻译该策略

**变更**

- `zoneAwareLbSetting` 需配 `ISTIO_META_ENABLE_SELF_DISCOVERY: "true"` 才能注入 self-discovery `local_cluster`；**仅 sidecar 模式支持，ambient 不支持**；且 `enabled: false` 现在会显式下发 `routing_enabled: 0%`（此前是 no-op，Envoy 会回落默认 100% 而意外启用）
- `ALLOW_ANY_DYNAMIC_DNS` 的枚举值是 **3**（**2 是 reserved**，原 `VIRTUAL_SERVICE_ONLY`）；**仅 sidecar 模式，Sidecar CRD 不支持**
- 多集群 `PreferSameZone` 顺序变为：Network+Region+Zone → Network+Region → Network → Region+Zone → Zone → 无匹配

**修复**

- `meshConfig.defaultHttpRetryPolicy` 现在适用于 **waypoint 的 inbound 路由**（此前不生效，Issue #60682）
- 无 VirtualService 时 waypoint 上 `consistentHash` 失效（Envoy 收到 `RING_HASH` 但 inbound route 缺 `hash_policy`，退化为随机后端，破坏会话粘性，Issue #61045）
- `DestinationRule` 与 Gateway API backend policy 冲突时**按字段优先**，与创建顺序无关（Issue #60358）
- `istio.io/vs` 的 metadata-only 变更（Helm annotation、Argo CD label、last-applied-configuration）曾触发全量 XDS push，1.31 恢复为只对 spec 或 `istio.io` label/annotation 变更 push

> [!NOTE]
> **1.31 change-notes 中没有** traffic splitting、circuit breaking/connectionPool 语义、fault injection、mirroring、local rate limit、timeout 的任何变更条目——这些领域是安静的，语义变化主要来自历史累积。

## 已废弃 / 易混淆字段速查

| 流传写法 | 正确写法 | 状态 |
| :-- | :-- | :-- |
| `http[].faultInjection` | **`http[].fault`** | 字段名从来是 `fault` |
| `fault.delay.httpDelay` / `grpcDelay` | `fault.delay.fixedDelay` | 1.31 不存在 |
| `fault.abort.percent` | `fault.abort.percentage.value` | 已删除（`reserved`） |
| `fault.delay.percent` | `fault.delay.percentage.value` | deprecated，仍可用 |
| `fault.abort.http2Error` | — | 字段存在但 webhook 拒绝 |
| `uriRegexRewrite.regex` / `.replacement` | **`.match` / `.rewrite`** | 字段名从来是 match/rewrite |
| `retries.backoff.baseInterval` | `retries.backoff`（Duration） | 不是对象 |
| `retries.retryHostPredicate` | `retries.retryIgnorePreviousHosts` | 前者是 Envoy 内部概念 |
| `http[].mirrorPercent` | `http[].mirrorPercentage.value` | deprecated，触发 warning |
| `redirect.prefix_rewrite` | `redirect.prefixRewrite` | 文档写 snake_case，CRD 是 camelCase |
| `connectionPool.http.proxyProtocol` | `trafficPolicy.proxyProtocol.version` | HTTPSettings 下无此字段 |
| `outlierDetection.consecutiveErrors` | `consecutive5xxErrors` / `consecutiveGatewayErrors` | deprecated + 隐藏 |
| `loadBalancer.warmupDurationSecs` | `loadBalancer.warmup` | deprecated，与 `warmup` 互斥 |
| 「weight 必须和为 100」 | — | **不成立**，语义是 `w/Σw` |
| 「不写 weight 默认 1.0」 | — | **不成立**，零值是 0 |
| 「Istio 有原生限流 API」 | — | **不存在**，只有 EnvoyFilter + Envoy filter |

## 排障速查

| 现象 | 先查 |
| :-- | :-- |
| 配了没报错但不生效 | 是否写了 `faultInjection`（应为 `fault`）等已废弃字段，会被 CRD 拒绝 |
| 权重配了没分流 | 多 destination 下不写 `weight` 等于 0；`weight` 是相对比例不必凑 100 |
| subset 匹配不到 | `DestinationRule.host` 与 `VirtualService.hosts` 是否一致；subset 的 `labels` 是否真能选中 pod |
| 熔断没触发 | `consecutiveGatewayErrors` 是否 ≥ `consecutive5xxErrors`（会完全无效）；`consecutiveLocalOriginFailures` 是否少了 `splitExternalLocalOriginErrors: true` |
| 连接池限制不生效 | 是否写了 `0`（与不写等价）；`maxRequestsPerConnection: 1` 等于禁 keep-alive |
| 驱逐实例很快恢复 | `baseEjectionTime` 是**乘数**（30s × 已驱逐次数），会递增 |
| 重试不生效 | `attempts: 0` 是禁用而非默认；`fault` 同规则时会让 retry 失效（运行时行为） |
| 重试次数比预期多 | `attempts` 不含初始请求，`3` = 最多 4 次 |
| 改了 retryOn 没效果 | 运行时默认比文档多 `retriable-status-codes`；以运行时为准 |
| 超时没生效 | Istio 默认**禁用** HTTP 超时（0），必须显式写 `timeout` |
| 镜像没生效 | 不写 `mirrorPercentage` 是 100% 而非 0；显式 0 才关闭；`mirror` 与 `mirrors` 不能同用 |
| 正则重写不生效 | 字段是 `match` / `rewrite`，捕获组用 `\1` `\2` |
| 限流没生效 | Istio 无原生 API，需 `EnvoyFilter`；且官方明确警告其升级脆弱性 |
| 异常实例仍在 LB 池 | outlierDetection 只在 **outbound（客户端侧）** 生效；EDS 层过滤需 `minHealthPercent > 0` |

## Links

- [Istio](/docs/CS/Framework/Istio/Istio.md)
- [Envoy](/docs/CS/Framework/Istio/Envoy.md)
- [Security](/docs/CS/Framework/Istio/Security.md)
- [Observability](/docs/CS/Framework/Istio/Observability.md)
- [Spring Cloud Alibaba（含 Sentinel 限流对比）](/docs/CS/Framework/Spring_Cloud/Alibaba.md)
- [Resilience4j（应用层熔断重试对照）](/docs/CS/Framework/Spring_Cloud/Resilience4j.md)

## References

- <https://istio.io/latest/docs/concepts/traffic-management/>
- <https://istio.io/latest/docs/reference/config/networking/virtual-service/>
- <https://istio.io/latest/docs/reference/config/networking/destination-rule/>
- <https://istio.io/latest/docs/tasks/traffic-management/traffic-shifting/>
- <https://istio.io/latest/docs/tasks/traffic-management/mirroring/>
- <https://istio.io/latest/docs/tasks/traffic-management/rate-limit/>
- <https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/router_filter#x-envoy-retry-on>
- <https://istio.io/latest/news/releases/1.31.x/announcing-1.31/change-notes/>
- <https://api.github.com/repos/istio/istio/releases/latest>
