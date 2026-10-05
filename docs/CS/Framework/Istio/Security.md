## Introduction

Istio 的安全模型可以拆成三件事：**身份（谁在调用）**、**加密（通道是否可信）**、**授权（允许做什么）**。本篇按这三个维度展开，并把官方文档里没有、但能从 env var 参考页与源码确认的默认值标出来——证书轮转比例这类参数流传的错误值最多。

> [!NOTE]
> 版本基线：Istio **1.31.1**（2026-09-21），支持 K8s 1.32~1.36。安全相关默认值来自 `pilot-agent` env var 参考页、`security.istio.io/v1` API 参考页与 1.31 change notes。

## mTLS：PeerAuthentication

### 三种模式

| 模式 | 官方描述 |
| :-- | :-- |
| `UNSET` | 「Inherit from parent, if has one. Otherwise treated as `PERMISSIVE`」 |
| `DISABLE` | 「Connection is not tunneled」 |
| `PERMISSIVE` | 「Connection can be either plaintext or mTLS tunnel」 |
| `STRICT` | 「Connection is an mTLS tunnel (TLS with client cert must be presented)」 |

**mesh 级默认 = `PERMISSIVE`**（三处官方明文确认）。运维文档表述：「proxies are configured in permissive mode by default, meaning they will accept both mutual TLS and plaintext traffic」。

### 层级与覆盖规则

- 作用域由 `metadata.namespace` 决定：root namespace（默认 `istio-system`）= mesh 级，其他 namespace = 该命名空间内。
- **优先级取最窄，不叠加**：workload-specific → namespace-wide → mesh-wide。
- **数量限制**：全网格最多 1 条 mesh-wide；每 namespace 最多 1 条 namespace-wide。配置多条时「**Istio ignores the newer policies**」；多条 workload-specific 同时匹配时**取最旧的一条**。
- 对比：**RequestAuthentication 无此限制**，所有匹配策略会被合并。
- ⚠️ **root namespace 中带 selector 的 PeerAuthentication 会被忽略**（这与 AuthorizationPolicy 的 selector 语义不同）。

`portLevelMtls` 的端口指**工作负载端口，不是 K8s Service 端口**（官方原文强调两次），且**仅在指定 workload selector 时生效**。

> [!NOTE]
> **ambient 模式差异**：安全由 ztunnel 节点代理透明启用，因此 **`DISABLE` 模式不被支持**。`STRICT` 在此仍有用——确保绕过网格的连接不可能发生。

> [!WARNING]
> **PeerAuthentication 的 API 参考页字段表只列 `selector` / `mtls` / `portLevelMtls`，没有 `targetRefs`**（RequestAuthentication 与 AuthorizationPolicy 才有）。按 API 页现状，PeerAuthentication 应只用 `selector`。

### AuthorizationPolicy 对 mTLS 的硬依赖

以下字段**必须先开 mTLS**：`source.principals`/`notPrincipals`、`source.namespaces`/`notNamespaces`。

官方警告：强烈建议这些字段始终配合 `STRICT` 使用，「to avoid potential unexpected requests rejection or **policy bypass** when plain text traffic is used with the permissive mutual TLS mode」——**在 PERMISSIVE 下用这些字段等于可被绕过**。

## 证书与身份

### 签发流程

1. `istiod` 提供 gRPC 服务接收 CSR；
2. Istio agent 生成私钥与 CSR 并携带凭证发往 istiod；
3. istiod 内 CA 校验凭证并签发；
4. Envoy 通过 **Envoy SDS API** 向同容器内的 agent 索取证书与私钥；
5. agent 通过 SDS 下发；
6. **agent 监控证书过期并周期性轮转**。

格式为 X.509 证书，SDS 管道为本地 UDS（`customSDSPath`），不经 istiod 转发——这是 `pilot-agent` 断连时已有连接仍能维持证书的原因。

### SPIFFE 与 SPIRE 的澄清

这是最容易搞错的一点：

- **Istio 采用 SPIFFE 的 ID 格式标准，但签发者默认是 Istio 自带的 CA（Citadel 内嵌于 istiod），不是 SPIRE。**
- SPIFFE ID 格式：`spiffe://<trust.domain>/ns/<namespace>/sa/<service-account>`，Istio 要求所有注册遵循此 pattern。
- `AuthorizationPolicy.source.principals` 的写法是**去掉 `spiffe://` 前缀**：`"<TRUST_DOMAIN>/ns/<NAMESPACE>/sa/<SERVICE_ACCOUNT>"`，如 `"cluster.local/ns/default/sa/productpage"`。

**SPIRE 不是内置组件，必须独立安装**，且**未查到 `PILOT_ENABLE_SPIRE` 之类的开关型 feature flag**。机制是**约定优于配置**：通过 SPIFFE CSI driver 把 UDS socket 挂进 sidecar/gateway 容器（默认路径 `/run/secrets/workload-spiffe-uds`），Istio agent 探测到即改从 SPIRE 取身份（相关变量 `WORKLOAD_IDENTITY_SOCKET_FILE`，默认 `socket`）。

SPIRE 集成的两个硬前提：

- SPIRE 与 Istio **必须配置完全相同的 trust domain**；
- sidecar 与 gateway **必须预先在 SPIRE 注册**，否则无法达到 READY（`cannot get identities, and therefore cannot reach READY status`）。

官方推荐用 **SPIFFE CSI driver** 而非 `hostMounts`（后者「is a larger security risk」）。

### 证书轮转参数

| 变量 | 默认值 | 说明 |
| :-- | :-- | :-- |
| `SECRET_TTL` | `24h0m0s` | agent 请求的证书生命周期 |
| `SECRET_GRACE_PERIOD_RATIO` | **`0.5`** | 轮转宽限比例 |
| `SECRET_GRACE_PERIOD_RATIO_JITTER` | `0.01` | 比例随机抖动，**避免大规模代理同时续期**（~15 分钟 / 24 小时） |
| `TRUST_DOMAIN` | `cluster.local` | SPIFFE 证书信任域 |
| `WORKLOAD_RSA_KEY_SIZE` | `2048` | 工作负载证书 RSA 密钥长度 |
| `TOKEN_AUDIENCES` | `istio-ca` | 校验 JWT audience 以签发证书 |

> [!WARNING]
> **轮转提前量默认是生命周期的 0.5（24h 证书约在 12h 处开始轮转），不是网上流传的 0.8。** 官方 env var 参考页明确为 `0.5`；源码 `security/pkg/nodeagent/cache/secretcache.go` 的 `rotateTime()` 计算 `ExpireTime -（graceRatio+jitter）× 证书生命周期`，jitter 双向随机。`pkg/security/security.go` 中的注释示例为「at 0.10 and 1 hour TTL, we would refresh 6 minutes before expiration」。

**TTL 上限 90 天**：「Values over 90 days will not be accepted」。istiod 可通过 `proxyMetadata.SECRET_TTL` 覆盖。

### 外部 CA 与根证书

- 默认 Istio CA 自签根证书；`meshConfig.caAddresses` 可指向外部 CA（如 `istio-csr`）。
- `meshConfig.caCertificates` 为 `CertificateData[]`，可含 `pem` 或 `spiffeBundleUrl`；istiod 自动把 `cacerts` Secret（插件证书）或 `istio-ca-secret`（自签）加入信任锚。
- `CA.requestTimeout` 默认 `10s`；`CA.istiodSide` 默认 `true`。
- 1.31 修复（SEC-10）：CA 根证书由文件提供时，istiod 现在会在证书轮换后**重新加载根证书**。

## 信任域

- 配置位置：`meshConfig.trustDomain`（另有 `trustDomainAliases`）。`cluster.local` 这个默认值来自 pilot-agent `TRUST_DOMAIN`，MeshConfig 参考页本身未声明默认值。
- `trustDomainAliases` 可让多个域下的同名身份视为同一身份：`trustDomain: td1` + `["td2","td3"]` → `td1|td2|td3` 视为同一身份。

**1.31 新增** `AuthorizationPolicy.Source.trustDomains` / `notTrustDomains`：

> 「A list of trust domains derived from the peer certificate. Can be exact, prefix, suffix and presence. **This field requires mTLS enabled** and is the same as the `source.trustDomain` attribute. If not set, any trust domain is allowed.」

与 `principals`/`namespaces` 等字段是 **AND** 关系。

### 多网格的信任约束

> [!WARNING]
> 跨 mesh（不同 CA）**必须交换信任 bundle**，且官方明确不提供工具：「Istio does not provide any tooling to exchange trust bundles across meshes. You can exchange the trust bundles either manually or automatically using a protocol such as **SPIFFE Trust Domain Federation**」。

multi-network 场景还有一条硬约束：「Istio only supports cross-network communication to workloads with an Istio proxy. This is due to the fact that Istio exposes services at the Ingress Gateway with **TLS pass-through**, which enables mTLS directly to the workload.」无 proxy 的工作负载会被过滤（`Istio filters out-of-network endpoints for proxyless services`）。

`ClusterTrustBundle`（`certificates.k8s.io/v1alpha1`）可让控制面自动校验 mTLS 对端证书。

## AuthorizationPolicy

### 四种 action

官方枚举：`ALLOW`（默认）、`DENY`、`AUDIT`、**`CUSTOM`**。

**求值顺序**（官方 5 步）：

1. 有 `CUSTOM` 匹配 → 交由扩展求值，deny 则拒；
2. 有 `DENY` 匹配 → 拒；
3. 该工作负载**无任何 ALLOW 策略** → 放行；
4. 有 `ALLOW` 匹配 → 放行；
5. 否则拒。

> [!NOTE]
> `AUDIT` 不影响放行/拒绝，仅打标；**必须额外配置插件才会真正审计**——「The request will not be audited if there are no such supporting plugins enabled.」

### 匹配维度

`from[].source`：`principals`、`requestPrincipals`、`namespaces`、`serviceAccounts`（格式 `<namespace>/<serviceaccount>`，**不允许通配符 `*`，且不能与 `principals`/`namespaces` 同时设置**）、`ipBlocks`、`remoteIpBlocks`（取自 `X-Forwarded-For` 或 proxy protocol，需配 `meshConfig.gatewayTopology.numTrustedProxies`）、`trustDomains`/`notTrustDomains`（1.31 新增）。

`to[].operation`：`hosts`（大小写不敏感，**仅 HTTP**）、`ports`、`methods`（**gRPC 恒为 `POST`**）、`paths`（gRPC 为 `/package.service/method`）。

匹配语义：`from`/`to` 未设则不限制；`Source`/`Operation` 内部字段 AND；一条 rule 内至少一个 source + 至少一个 operation + 全部 `when` 匹配才算命中；`rules` 整体为 OR。

> [!WARNING]
> **`rules` 不设 = 永不匹配**，等价于对该工作负载**默认拒绝**（若 action 为 ALLOW）。这是从「全部放行」切到「白名单」时最常见的静默失效。

CEL 条件 `when` 的键如 `request.headers[x]`、`request.auth.claims[groups]`、`source.namespace`、`source.principal`、`destination.port`、`connection.sni`。字符串通配：`abc*` 前缀、`*abc` 后缀、`*` 存在性、`abc` 精确。

> [!NOTE]
> **waypoint 场景必须用 `targetRefs`，`selector` 会被忽略**——「Waypoint proxies are required to use this field for policies to apply; `selector` policies will be ignored.」

### CUSTOM action 的真实依赖（常见误解）

`CUSTOM` **不依赖 SPIRE**，而是依赖 MeshConfig 中 `extensionProviders` 声明的外部授权扩展：

- `provider.name` 「Must be used only with CUSTOM action」，且**每 workload 最多 1 个 extension provider**。
- 官方明确：「Currently, **the only supported extension provider type is the Envoy ext_authz provider**. The external authorizer must implement the corresponding Envoy ext_authz check API.」
- 扩展在原生 ALLOW/DENY 之前**独立**求值，但「a request is allowed **if and only if** all the actions return allow」——**扩展不能绕过 ALLOW/DENY 结论**。

两种 provider 类型：`envoyExtAuthzGrpc`（含 `port`）与 `envoyExtAuthzHttp`（含 `includeRequestHeadersInCheck`、`headersToUpstreamOnAllow`、`headersToDownstreamOnAllow/Deny`、`failureModeAllow`）。外部授权器可部署在网格内独立 Pod / 同 Pod sidecar / 网格外（后者需 `ServiceEntry` 注册）。

与 SPIRE 的真实关联点：若用 SPIRE 替换身份来源，ext_authz 看到的 principal 形态会随之变化（形如 `principal:"spiffe://cluster.local/ns/foo/sa/curl"`），但 CUSTOM 本身不要求 SPIRE。

### 被拒时的返回

返回 **HTTP 403**，响应体 `RBAC: access denied`（`content-length: 19`、`content-type: text/plain`）；访问日志 `response_code:403`、`response_flags` 含 `UAEX`、`response_code_details` 形如 `rbac_access_denied_matched_policy[ns/policy-name]`；debug 日志 `enforced denied, matched policy ns[default]-policy[test]-rule[0]`。

> [!NOTE]
> 上述细节来自阿里云 ASM 官方文档的实机访问日志与 Istio 官方外授权任务示例输出；**istio.io 文档中未找到「403 + `RBAC: access denied`」的成文规格**。

### 官方明示的能力限制

- **授权策略只支持入站流量，不支持出站**。
- **不支持 server-first TCP 协议**（MySQL/PostgreSQL 等服务端先发数据的协议）：首包未经访问控制检查直达客户端，**故不应在此类协议的首包中携带敏感数据**。
- `hosts`/`notHosts` 在 sidecar 上基本无意义（sidecar 转发给应用时不使用 `Host` 头，客户端可用任意 IP+Host 绕过），应主要在 **gateway** 上使用；且 Istio 会为 hostname 生成 `example.com` 与 `example.com:*` **两条**配置，精确匹配需同时列出两者。
- 路径归一化（`meshConfig.pathNormalization.normalization`，支持 `NONE`/`BASE`/`MERGE_SLASHES`/`DECODE_AND_MERGE_SLASHES`）会影响策略匹配结果。
- 推荐 **`ALLOW-with-positive-matching`** 与 **`DENY-with-negative-matching`** 模式：失配最坏结果是 403 拒绝而非策略绕过。

## JWT：RequestAuthentication

### 字段与验证

- `jwtRules[].issuer`：`iss` 不匹配则拒。
- `audiences[]`：**「The service name will be accepted if audiences is empty.」**
- `jwksUri`：公钥集 URL（遵循 OpenID Discovery），**可选**（可从 issuer 的 OpenID Discovery 或 issuer 邮箱域名推断）；**`jwksUri` 与 `jwks` 二者只能用其一**。
- `jwks`：直接内联 JWKS。
- 位置类：`fromHeaders`（默认 `Authorization`，`prefix: "Bearer "`）、`fromParams`、`fromCookies`。
- `timeout`：JWKS 拉取超时**默认 `5s`**，由 `PILOT_JWT_ENABLE_REMOTE_JWKS` 控制是否启用远程解析器。
- `spaceDelimitedClaims`：默认仅 `scope` 与 `permission` claim 按空格拆分。

> [!WARNING]
> **「多个位置的 token 不受支持」**——「Requests with multiple tokens (at different locations) are not supported, the output principal of such requests is undefined.」

### 与授权策略配合

- `requestPrincipals` 格式 `"<ISS>/<SUB>"`，如 `"example.com/sub-1"`，等价于 `request.auth.principal` 属性。
- **RequestAuthentication 本身不做强制**：无凭证的请求会被接受，只是没有已认证身份。官方推荐范式是 `RequestAuthentication` 定规则 + `AuthorizationPolicy` 用 `requestPrincipals: ["*"]` 强制必须携带有效 JWT。
- 按 issuer 区分：`requestPrincipals: ["issuer-foo/*"]` 配合 `hosts` 做差异化要求。
- CEL 直接读 claim：`when: [{key: request.auth.claims[groups], values: [...]}]`。
- **JWT claim 路由（Experimental）**：`VirtualService` 中用 `@request.auth.claims.sub` 前缀匹配内部 metadata，**仅支持在 Gateway 上**。

### 1.31.1 的 JWKS 加固

修复 istiod 抓取 `jwksUri` 的 **SSRF 缺口**：默认在 dial 层阻断 link-local 与已知云元数据地址（如 `169.254.169.254`），并拒绝非合法 JWKS 响应；私有与 loopback 段仍可达，可用 `BLOCKED_CIDRS_IN_JWKS_URIS` 屏蔽。

1.31.1 同时修复：JWKS resolver 被强制 HTTP/1.1（自定义 `TLSClientConfig` 使 Go `net/http` 禁用自动 HTTP/2、ALPN 无法协商 h2）导致经 HTTP CONNECT 代理的抓取失败，现已重新启用 HTTP/2。

## TLS 与加密套件

- Istio 配置 **`TLSv1_2` 为客户端与服务端的最低 TLS 版本**，配 6 个套件（ECDHE-ECDSA/RSA-AES256-GCM-SHA384、ECDHE-ECDSA/RSA-AES128-GCM-SHA256、AES256-GCM-SHA384、AES128-GCM-SHA256）。
- `meshConfig.enableAutoMtls` 默认 `true`。
- `BackendTLSPolicy` 用于**服务端**侧 CA 引用；1.31.1 的 CVE（`GHSA-qm8v-g4f9-qhjx`，CVSS 6.8）正是它在 sidecar 上 CA 引用无法解析时 **fail open 降级为明文**。

### FIPS 140-3 与后量子（1.31 新增）

`COMPLIANCE_POLICY` 的合法值：`''`/unset（无额外限制）、`fips-140-2`、`fips-140-3`、`pqc`（**后量子安全，实验性**，强制 X25519MLKEM768 + TLS 1.3）。

`fips-140-3` 细节：强制 TLS v1.2 或 v1.3；TLS 1.2 用 `ECDHE_[RSA|ECDSA]_WITH_AES_*_GCM_SHA*`，TLS 1.3 用 AES-GCM；密钥协商限 **P-256 或 P-384**；Envoy 侧使用原生 `FIPS_202205` 合规策略。

构建要求：Go 组件必须 **Go 1.24+** 且以 `GOFIPS140=v1.0.0` 或更新已验证版本构建；**`GOEXPERIMENT=boringcrypto` 与该策略不兼容，必须停用**；经 Helm `env` 配置后 sidecar/gateway/istiod 自动注入 `GODEBUG=fips140=only`。

官方警告：「Setting compliance policy in the control plane is a **necessary but not sufficient** requirement to achieve compliance.」

## 其他安全能力

- **EnvoyFilter 扩展授权**：`INSERT_FIRST` 可插入 Lua filter 做路径归一化等预处理。1.31 加固（SEC-07）：限制 `EnvoyFilter.proxyVersion` 正则长度至 **1024 字符**，修复未限制长度导致 istiod 正则编译过度消耗内存与 CPU。
- **可观测端点 mTLS 化**（1.31 新增，TEL-05）：`ENVOY_SECURE_METRICS_PORT` 与 `ENVOY_SECURE_MERGED_METRICS_PORT` 创建**要求 mutual TLS 的静态 bootstrap listener**，使 Prometheus 可通过 mTLS 抓取指标。
- **CRL**：`ClusterTrustBundle` 支持证书吊销列表；1.31.1 修复无法清空 CRL（指定空串或删除 `ca-crl.pem`）。阿里云 ASM 1.29 已支持 ztunnel CRL 校验。

### 1.31 安全变更全景（change notes SEC-01~11）

| 编号 | 内容 |
| :-- | :-- |
| SEC-01 | 新增 `PILOT_ENABLE_STRICT_GATEWAY_MERGING`（**默认启用**），阻止 Istio `Gateway` 与受管 Gateway API `Gateway` 跨 namespace 合并 |
| SEC-02 | `AuthorizationPolicy.Source` 新增 `trustDomains`/`notTrustDomains` |
| SEC-03 | 新增 `fips-140-3` 合规策略 |
| SEC-04 | 新增 `PILOT_ENABLE_REMOTE_CREDENTIALS_CONTROLLER`（**默认 `true`**） |
| SEC-05 | 修复第 2 次及后续 Secret 轮换未触发证书重载（#59912） |
| SEC-06 | 修复 Gateway API 前端 mTLS 的 `Secret` CA 引用过去在 SDS 运行时被拒（#60277） |
| SEC-07 | 限制 `EnvoyFilter.proxyVersion` 正则长度至 1024 字符 |
| SEC-08 | 修复外部 SDS provider 的 gRPC authority 改用配置中的服务 hostname |
| SEC-09 | 修复 Gateway 外部 SDS 资源命名与回退（多 Gateway 可共用 provider 申请不同证书，#57080） |
| SEC-10 | 修复 istiod CA 根证书轮换后未重新加载 |
| SEC-11 | XDS api generator / MCP 配置服务端点**要求已验证的控制面身份**（此前任何能连 istiod XDS 端口的客户端都能读全网格配置） |

补充的策略正确性修复：TM-46 修复 east-west gateway 在目标 Service 有 L7 `AuthorizationPolicy` 时生成错误 deny-all RBAC filter 导致跨网络流量被误阻断（#60806）；TM-51 修复 ingress Gateway 在多集群场景绕过 waypoint 导致 **authorization policy 未执行**（#61092）——后者是典型的策略绕过类漏洞。

INS-08 修复 waypoint/kube-gateway workload socket 与 **SPIRE CSI driver 不兼容**（#60108）。

## 安全排障速查

| 症状 | 优先检查 |
| :-- | :-- |
| 策略配了但请求被拒 | 先确认 mTLS 模式——PERMISSIVE 下用 `principals`/`namespaces` 会被绕过；查访问日志 `rbac_access_denied_matched_policy[...]` |
| 切 STRICT 后大量 503 | 客户端未注入 sidecar 或用了 `DISABLE`；PERMISSIVE→STRICT 切换需配套处理无代理工作负载 |
| sidecar 一直不 READY（用了 SPIRE） | 工作负载是否已在 SPIRE 注册；trust domain 是否与 Istio 完全一致；UDS socket 是否挂进容器 |
| 授权突然对所有流量生效 | `rules` 未设置（= 永不匹配 = 默认拒绝） |
| waypoint 上策略不生效 | 是否用了 `selector`（waypoint 必须用 `targetRefs`） |
| 证书未按预期轮转 | 检查 `SECRET_GRACE_PERIOD_RATIO`（默认 0.5）与是否设了 `proxyMetadata.SECRET_TTL`；TTL 上限 90 天 |
| 大规模网格 istiod 内存高 | `ClusterTrustBundle` 轮换、`AuthorizationPolicy` 数量增长（1.31 已修 #61254 的 CPU 增长） |

## Links

- [Istio](/docs/CS/Framework/Istio/Istio.md)
- [Install](/docs/CS/Framework/Istio/Install.md)
- [Envoy](/docs/CS/Framework/Istio/Envoy.md)
- [ecosystem](/docs/CS/Framework/Istio/ecosystem.md)
- [Identity](/docs/CS/Container/k8s/Identity.md)
- [Spring Security](/docs/CS/Framework/Spring/Security.md)

## References

- <https://istio.io/latest/docs/concepts/security/>
- <https://istio.io/latest/docs/reference/config/security/peer_authentication/>
- <https://istio.io/latest/docs/reference/config/security/authorization-policy/>
- <https://istio.io/latest/docs/reference/config/security/request_authentication/>
- <https://istio.io/latest/docs/ops/integrations/spire/>
- <https://istio.io/latest/docs/reference/commands/pilot-agent/>
- <https://istio.io/latest/docs/ops/best-practices/security/>
- <https://istio.io/latest/news/releases/1.31.x/announcing-1.31/change-notes/>
- <https://istio.io/latest/news/releases/1.31.x/announcing-1.31.1/>
