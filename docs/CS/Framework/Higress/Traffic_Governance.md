## Introduction

这一页管"流量进来以后怎么被处置"：限流、灰度、路由匹配、重写、重试与容灾。Higress 在这块的真实形态不是"一个大而全的路由 DSL"，而是**三套并存的入口**——Ingress annotation、专门的 Wasm 插件、以及控制台路由层。三套的能力边界不同、字段名不通用，选错入口比配错字段更常见。服务从哪来（注册中心、McpBridge、HTTP 转 Dubbo）在 [Service Discovery](/docs/CS/Framework/Higress/Service_Discovery.md)。

## Rate Limiting

两个限流插件共享"按 key 分组"的抽象，但**配置面完全不对称**，把集群版的字段搬到本地版会带一堆无效字段：

| | `key-rate-limit` | `cluster-key-rate-limit` |
| --- | --- | --- |
| 阶段 / priority | 默认阶段 / 10 | 默认阶段 / 20 |
| 顶层字段 | `limit_by_header`、`limit_by_param`、`limit_keys` **只有这三个** | `rule_name`、`global_threshold`、`rule_items`、`show_limit_quota_header`、`rejected_code`、`rejected_msg`、`redis` |
| key 来源 | URL 参数、请求头**两种**（正文没有 consumer / cookie / IP） | **9 种** `limit_by_*` + `limit_keys` |
| 被拒响应 | 配置表里没有 `rejected_code` / `rejected_msg`，默认行为文档未写 | `rejected_code` 默认 **429**、`rejected_msg` 默认 `Too many requests`、`show_limit_quota_header` 默认 false（开后有 `X-RateLimit-Limit` / `X-RateLimit-Remaining`） |
| 阈值粒度 | `query_per_second` / `minute` / `hour` / `day` 四选一 | 同 |

集群版才是"全局一致"的那个，官方定位逐字是"适用于需要跨多个 Higress Gateway 实例进行全局一致速率限制的场景"。9 个 key 维度：`limit_by_header` / `limit_by_param` / `limit_by_consumer`（按 consumer 名，无需实际值，写成 `''`）/ `limit_by_cookie`，以及逐键分别计数的 `limit_by_per_header` / `per_param` / `per_consumer` / `per_cookie` / `per_ip`——**不存在裸 `limit_by_ip`**，IP 维度只有 per_ip，取值 `from-header-<名>`（如 `from-header-x-forwarded-for`）或 `from-remote-addr`。`limit_keys[].key` 支持 `regexp:^d.*`、`*`、`1.1.1.0/24`、`0.0.0.0/0`。两条顺序规则：`global_threshold` 与 `rule_items` 二选一；**`rule_items` 按排列顺序匹配，命中第一条后后续规则被忽略**。

Redis 侧有两个真实踩坑点。第一，`redis.service_name` 要求**带服务类型的完整 FQDN**（`my-redis.dns`、`redis.my-ns.svc.cluster.local`，官方示例一律写 `redis.static`）——Redis 必须**先作为服务来源注册进 Higress**才能被限流插件用，不是任意网络地址（原因见 [Wasm Development](/docs/CS/Framework/Higress/Wasm_Development.md) 的 cluster 寻址）。第二，**`service_port` 的默认值按服务类型分叉：static 类型默认 80，其它服务类型默认 6379**，所以照抄 `redis.static` 而不写端口，连的是 80。

> [!WARNING]
> 两条经常被写成事实、但**官方正文里找不到**的说法：① "本地限流配 100 QPS、3 副本实际放行约 300 QPS"——两个限流插件正文都没有副本数、倍数或放大的任何表述，"多副本线性放大"是推论不是文档结论；② `key-rate-limit` 的"本地 / 单实例"定性**只出现在文档索引条目名《基于 Key 的本地限流》里**，页面正文没有出现"本地"二字。真要写"每实例限流"，官方口径来自另外三个 annotation：`higress.io/route-limit-rps` / `higress.io/route-limit-rpm` 逐字写着"该 Ingress 定义的路由在**每个网关实例上**每秒/每分钟最大请求次数"，且瞬时最大值要乘 `higress.io/route-limit-burst-multiplier`（**默认 5**）。这个默认 5 倍的瞬时放大，比"×副本数"更容易被读者误算。

熔断与过载保护这一侧，文档能落到实证的是**重试与容灾**而不是某个熔断开关：`nginx.ingress.kubernetes.io/proxy-next-upstream-tries`（默认 3 次）、`-timeout`、`proxy-next-upstream`（默认 `"error,timeout"`，合法值 `error` / `timeout` / `invalid_header` / `http_xxx` 如 `http_502` / `non_idempotent` / `off`——**默认对非幂等的 POST、PATCH 不重试**，要配 `non_idempotent` 才打开）。容灾靠 `default-backend`（无可用节点时自动转发）配 `custom-http-errors`（命中指定状态码再转）；**一条行为差异必须记住：转发至容灾服务时请求的 Path 会被重写为 `/`**（官方注明与 ingress-nginx 保持一致），业务侧若依赖 path 会莫名 404。至于 Sentinel 体系与集群流控，官方仅在场景描述里写"深度集成了 Dubbo、Nacos、Sentinel 等微服务技术栈"，**没有给出配置面**，具体接入方式与熔断语义不要在本子树里写成事实；通用方法学见 [Sentinel](/docs/CS/Framework/Sentinel/Sentinel.md) 与 [TrafficManagement](/docs/CS/Framework/Istio/TrafficManagement.md)。

## Routing Primitives

Ingress 原生能落地的匹配维度其实很少：**域名**（`rules[].host`）、**路径**（`path` + `pathType`，取值 `Exact` / `Prefix` / `ImplementationSpecific`）。方法、header、query、cookie 这些维度在 Higress 里不是 Ingress 字段，而是通过 canary annotation 与 `traffic-tag` 实现的。

`ImplementationSpecific` 是使用正则捕获组重写的**必要前提**：

```yaml
# 剥掉 /v1 前缀
metadata:
  annotations:
    higress.io/rewrite-target: /$2
spec:
  rules:
  - http:
      paths:
      - path: /v1(/|$)(.*)
        pathType: ImplementationSpecific
```

换前缀写 `/$v2/$2`；改转发时的 Host 用 `higress.io/upstream-vhost`。权重路由的原生入口是 `canary-weight`（0~100 整数）+ `canary-weight-total`（默认 100），也就是"多个 Ingress 共享同一 host/path、各带权重"。

后端协议用 `nginx.ingress.kubernetes.io/backend-protocol` 指定，默认 HTTP，支持 HTTP、HTTP2、HTTPS、GRPC、GRPCS（**不支持 AJP 和 FCGI**）。一条能省配置的机制：后端 K8s Service 的 **Port Name 定义为 `grpc` 或 `http2` 时，Higress 会自动用 GRPC / HTTP2，无需再写这个 annotation**。gRPC 路由的最小配置就是这一行加普通 Ingress（验证用 `grpcurl -plaintext -authority foo.com 127.0.0.1:80 list`）。

后端走 HTTPS 需要四个 annotation 组合，且有一条硬约束：`backend-protocol: "HTTPS"` + `proxy-ssl-secret: "default/gateway-cert"`（格式 `namespace/secret-name`）+ `proxy-ssl-name`（后端校验用的 SNI）+ `proxy-ssl-server-name: "on"`；**必须同时另建一个 CA 证书 Secret，名字是 `proxy-ssl-secret` 的值加 `-cacert` 后缀**（如 `gateway-cert-cacert`），官方写"否则会报错"。注意网关侧监听仍是 HTTP 80——TLS 只发生在网关到后端这一段。

Higress 自有的、nginx 侧没有对应的路由增强 annotation：`higress.io/timeout`（**单位秒**，且官方强调"超时设置作用在**应用层，非传输层 TCP**"）、`higress.io/request-header-control-add` / `-update` / `-remove` 与 response 侧同名共 6 条（add 是拼接、update 是覆盖；单个写 `Key Value`，多个用 yaml `|` 每行一对；remove 单个写 `Key`、多个逗号分隔）、流量镜像 `higress.io/mirror-target-service`（格式 `namespace/name:port`，namespace 默认取 Ingress 所在、port 默认第一个端口）与 `higress.io/mirror-percentage`（0~100，默认 100）、TLS 版本 `higress.io/tls-min-protocol-version`（默认 TLSv1.0）与 `higress.io/tls-max-protocol-version`（默认 TLSv1.3）。

四层路由是唯一必须走 Gateway API 的场景：`global.enableGatewayAPI` 默认 false、需预装 Gateway API CRD，然后用 `TCPRoute` 而不是任何 annotation。它还有两条硬约束——**该文档明确"不适用于版本 ≥ 2.2.0 且 < 2.2.4"**，且 `TCPRoute` 的 apiVersion 随版本分档（≥ 2.2.4 + Gateway API 1.6.0 用 `gateway.networking.k8s.io/v1`；< 2.2.4 + ≤ 1.4.0 用 `v1alpha2`）；配完 Gateway 资源还不够，**必须手工 `kubectl edit service higress-gateway -n higress-system` 在 `spec.ports` 里加对应端口**（默认只有 80 的 `http2` 与 443 的 `https`），否则流量根本进不到网关。

## Gray Release

三条路，解决的问题不同：

**一、canary annotation，路由级切流。** 家族共 7 条：`canary`、`canary-by-header`、`canary-by-header-value`（精确）、`canary-by-header-pattern`（正则）、`canary-by-cookie`、`canary-weight`、`canary-weight-total`。官方明确 **`higress.io` 与 `nginx.ingress.kubernetes.io` 两个前缀是等价的**，可按使用习惯任选。两条常见误解：只配 `canary-by-header` 时 header 值**必须是 `always`** 才进灰度（要自定义值得再配 `-by-header-value`）；`canary-by-cookie` **根本不支持自定义值，只能 `always`**。多种方式的优先级官方给的是 **Header > Cookie > 权重**，并声明灰度支持多个版本服务、无上限。

**二、`traffic-tag`，只染色不决策**（默认阶段、priority 400）。定位是"根据权重或特定请求内容**通过添加特定请求头的方式**对请求流量进行染色"，转发决策交给下游消费这个 header 的路由规则或全链路灰度。顶层 `conditionGroups` / `weightGroups` / `defaultTagKey` / `defaultTagVal`（后两者**当且仅当同时配置**才生效）。条件算子 7 个：`equal`、`not_equal`、`prefix`、`in`、`not_in`、`regex`、`percentage`；`conditionType` 3 个：`header`、`parameter`、`cookie`；组合逻辑 `logic` 取 `and` / `or`，**官方原文强调必须为小写字母**；`regex` 用的是 **RE2** 引擎。`value` 字段是**数组**，即使 `equal` 也要写成 `- bar`，且只有 `in` / `not_in` 支持多值。

```yaml
defaultTagKey: x-mse-tag
defaultTagVal: base
conditionGroups:
  - headerName: x-mse-tag
    headerValue: gray
    logic: and
    conditions:
      - conditionType: header
        key: role
        operator: in
        value: [user, viewer, editor]
```

`percentage` 与 `weight` 的区别是这里最容易用错的一处：percentage 的原理是 `hash(get(key)) % 100 < value`，**对同一键值多次匹配结果幂等**；weight 是随机权重分布，**同一请求多次匹配可能命中不同结果**。想做"同一用户恒定灰度"必须用 percentage 而不是 weight。染色的 header 惯例是 `x-mse-tag`，值 `gray` / `blue` / `base`；`weightGroups` 权重总和按 100 计，未配置的权重区间不添加 header。

**三、`frontend-gray`，前端资源版本重写**（认证阶段、priority 450）。它归在 transformation 分类下，做的是 OSS / CDN 场景下的前端版本灰度，与 `traffic-tag` 的"加个 header"不是一类东西。字段 `grayKey`（用户唯一标识，可来自 Cookie 或 Header）、`graySubKey`（身份是 JSON 嵌套时取内层字段）、`rules`（必填）、`rewrite`（必填）、`baseDeployment`、`grayDeployments`；`{version}` 是**保留占位符**，运行时被 `baseDeployment.version` 或 `grayDeployments[].version` 替换；`indexRouting` / `fileRouting` 都是前缀匹配。后端染色在这页：非 CDN 部署时加 `x-higress-tag`，`backendVersion` 字段会在 XHR / Fetch 请求上添加 `x-mse-tag` 传给后端。

**OpenKruise Rollout 联动**是第四条，但它是"由外而内"的：用户只声明 `Rollout` CRD（`rollouts.kruise.io/v1alpha1`），Kruise Rollout 通过 hook 修改 Deployment 的 `Pause` 暂停滚动发布，每批次为正式 Ingress 生成对应的**灰度 Ingress**并配置灰度流量策略，Higress 监听 Ingress 变化实时改路由，回滚时灰度 Ingress 自动下线。Higress 的接入开关只有一处：`spec.strategy.canary.trafficRoutings[].ingress.classType: higress`。安装 `helm install kruise-rollout openkruise/kruise-rollout --version 0.3.0-rc.0`，另需 `kubectl-kruise`。引用批次数时要小心：该页金丝雀示例只有 2 个 step，正文却写"一共分为 3 批"（最后一批隐式为全量）。

## Nginx Annotation Compatibility

Higress 能从 ingress-nginx 平滑迁移，靠的就是这张表——[兼容说明页](https://higress.ai/docs/latest/user/annotation/)开篇的事实是"常见的 Nginx Ingress Controller 引入了 100 多个 Annotation……目前 Higress 已经全面兼容了大部分"（**官方没给确切条数与百分比，不要写成"支持 X 条 / Y%"**）。

**支持度只有三档，不存在独立的"不支持清单"**：`兼容` / `部分兼容`（逐条写明不支持什么）/ `Higress 扩展`。唯一的废止说明是一条：Basic 认证那组能力"已经被 Basic auth 插件替代，**2.0.0 版本后不再支持**"（`auth-type` 家族，表格里仍标"兼容"）。**作用域也分三档且语义特指**：`Ingress` = 仅当前 Ingress 定义的路由规则；`域名` = 所有 Ingress 上出现的**相同 Host**；`服务` = 所有 Ingress 上出现的**相同 Service**。

"部分兼容"的逐条限制是最该抄进笔记的一半：

| annotation | 官方限制原文 |
| --- | --- |
| `backend-protocol` | 不支持 AJP 和 FCGI |
| `load-balance` | 不支持 ewma 算法；合法值只有 `round_robin` / `least_conn` / `random`，**配成 ewma 会静默回退 round_robin** |
| `upstream-hash-by` | 暂不支持 Nginx 变量与常量的组合使用；只支持 `$request_uri`、`$host`、`$remote_addr`、`$http_headerName`、`$arg_varName` |
| `affinity-mode` | 暂不支持 persistent 模式，只支持 `balanced`（`affinity` 本身只支持 `cookie`） |
| `auth-type` | 暂只支持 Basic |
| `auth-tls-secret` | Secret 名字格式必须是 `<该域名证书所在的 secret 的名字>-cacert` |
| `custom-http-errors` | 行为差异：转发至容灾服务时 Path 被重写为 `/` |
| `ssl-redirect` / `force-ssl-redirect` | 行为差异：**Higress 对这两个注解不区分对待**，都是强制 HTTP 重定向到 HTTPS（nginx 语义里两者本有区别） |

一处官方自相矛盾要带着走：`higress.io/ssl-cipher` 的多值分隔符，兼容矩阵页写"英文**逗号**分隔"、高阶治理用例页写"多个英文**冒号**分隔"，且矩阵页说它"仅 TLSv1.0–1.2 生效"。同页两处 `zkServicesPath`（表格复数）与 `zkServicePath`（示例单数）也不一致。这两处**不要在笔记里断言单一写法**。

迁移期还有一个开关级注意点：`global.enableStatus` 默认 true 会**回写 Ingress 的 status 字段**，官方为避免覆盖从 Nginx Ingress 迁过来的入口 IP，建议迁移期设为 false。为什么值得从 ingress-nginx 迁走，见 [Nginx Compare](/docs/CS/CN/nginx/compare.md)；通用 Ingress 机制见 [Ingress](/docs/CS/Container/k8s/Ingress.md)。

## Unverified

四项未核到一手出处，不写成事实：Envoy 异常点检测（Outlier Detection）在 Higress 侧的暴露入口——文档没有对应页面或字段；`higress.io/load-balance` 与 `consistenthash` 之类取值只在搜索结果正文读到、未在文档页二次核对；HTTP Method / query 作为路由匹配条件是否有独立的字段级入口（只能落到 canary 与 `traffic-tag` 两条路径上，控制台路由表单的全量匹配条件无法从文档站核实）；同一 Ingress 内是否存在原生 weighted routing 字段（官方做法是"多 Ingress + `canary-weight`"）；`canary-weight-total` 在多个灰度 Ingress 下的分母作用域。

## Links

- [Service Discovery](/docs/CS/Framework/Higress/Service_Discovery.md)
- [Plugin System](/docs/CS/Framework/Higress/Plugin_System.md)
- [AI Gateway](/docs/CS/Framework/Higress/AI_Gateway.md)
- [Nginx Compare](/docs/CS/CN/nginx/compare.md)
- [TrafficManagement](/docs/CS/Framework/Istio/TrafficManagement.md)
- [Higress](/docs/CS/Framework/Higress/Higress.md)

## References

- [Nginx Ingress Annotation 兼容说明](https://higress.ai/docs/latest/user/annotation/)
- [通过 Ingress Annotation 实现高阶流量治理](https://higress.ai/docs/latest/user/annotation-use-case/)
- [基于 Key 的本地限流](https://higress.ai/docs/latest/user/plugins/traffic/key-rate-limit/)
- [基于 Key 集群限流](https://higress.ai/docs/latest/user/plugins/traffic/cluster-key-rate-limit/)
- [流量染色](https://higress.ai/docs/latest/user/plugins/traffic/traffic-tag/)
- [前端灰度](https://higress.ai/docs/latest/user/plugins/transformation/frontend-gray/)
- [通过 OpenKruise Rollout 实现灰度发布](https://higress.ai/docs/latest/user/kruise-rollout/)
- [配置 TCP 四层路由](https://higress.ai/docs/latest/ops/how-tos/tcp-route/)
- [配置路由指向 HTTPS 服务](https://higress.ai/docs/latest/ops/how-tos/https-upstream/)
- [配置路由指向 gRPC 服务](https://higress.ai/docs/latest/ops/how-tos/grpc-upstream/)
