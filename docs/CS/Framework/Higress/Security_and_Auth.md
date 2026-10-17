## Introduction

Higress 的"安全网关"角色由三块拼成：认证鉴权插件族、防护插件族、证书与传输安全。这一页最容易写错的不是某个字段，而是**归类**——"所有认证插件都用同一套 consumer 模型"这句话会被官方文档直接证伪（六个走、三个不走），"WAF 依赖 ModSecurity"也不成立（实现底座是 Coraza）。插件的阶段与优先级全表在 [Plugin System](/docs/CS/Framework/Higress/Plugin_System.md)，本页只解释这些顺序造成的安全后果。

## Consumer Model

`consumers` + `allow` + `global_auth` 这套模型**只覆盖 6 个插件**：`basic-auth`、`key-auth`、`hmac-auth`、`hmac-auth-apisix`、`jwt-auth`、`oauth`。它的结构是"凭证声明在实例 / 全局级，授权写在路由 / 域名级"：

```yaml
# 全局 / 实例级：只放凭证与开关
global_auth: false        # true = 所有访问网关的请求都需携带有效认证信息，未认证请求直接被拒绝
consumers:
  - name: app-a           # consumer 名称，被 allow 引用
    credential: <该 consumer 的访问凭证>
---
# 路由 / 域名级：只放 allow
allow: [app-a]
```

> [!WARNING]
> **路由级配置里没有 `consumers`**。凭证只在实例 / 全局级声明，把 `consumers` 写进 `matchRules.config` 是错的——插件使用简介对此有明确区分。**`oidc`、`opa`、`ext-auth` 三个认证插件完全不走这套模型**（三页均无 `consumers` / `allow` / `global_auth`）：`oidc` 用 oauth2-proxy 风格的会话与 cookie 配置，`opa` 用 `serviceSource` 指向外部策略服务 + `policy` 决定放行，`ext-auth` 用 `match_type: whitelist|blacklist` + `match_list`。

各插件在 `consumers[]` 内的凭证字段名不同，这是抄配置时的主要摩擦点：

| 插件 | `consumers[]` 字段 | 其它关键字段与默认值 |
| --- | --- | --- |
| `basic-auth` | `name`、`credential`（`user:pass` 串） | 仅 `global_auth` + `consumers` + `allow` |
| `key-auth` | `name`、`credential` | `keys`（API Key 来源字段名，可为 URL 参数或 header）、`in_query` 默认 true、`in_header` 默认 true（两者至少一个为 true） |
| `hmac-auth` | `name`、`key`（从 `x-ca-key` 提取）、`secret` | `date_offset`（秒，按请求头 `Date` 判偏移，**这就是它的防重放手段**）；签名材料走 `x-ca-key` / `x-ca-signature` 等头 |
| `hmac-auth-apisix` | `name`（默认取 access_key）、`access_key`、`secret_key` | `allowed_algorithms` 默认 `["hmac-sha1","hmac-sha256","hmac-sha512"]`、`clock_skew` 默认 300 秒、`signed_headers`、`validate_request_body` 默认 false、`hide_credentials` 默认 false、`anonymous_consumer`（配置后**允许匿名绕过认证**）。定位是"完全兼容 APISIX HMAC 插件的配置与签名算法"，用于把 APISIX 客户端直接迁过来 |
| `jwt-auth` | `name`、`jwks`（RFC7517 JSON 串）、`issuer` | `claims_to_headers[]`（把 payload 字段塞进请求头给后端）、`from_headers` 默认 `{name: Authorization, value_prefix: "Bearer "}`、`from_params` 默认 `access_token`、`from_cookies`、`clock_skew_seconds` 默认 60、`keep_token` 默认 true |
| `oauth` | `name`、`client_id`、`client_secret` | `issuer` 默认 `Higress-Gateway`、`auth_path` 默认 `/oauth2/token`（**路由级要确保先匹配到该路由**）、`token_ttl` 默认 7200 秒、`global_credentials` 默认 true（允许任意路由签发的凭证）、`auth_header_name` 默认 `Authorization` |

两个语义澄清：`jwt-auth` 与"安全能力里的内置 JWT 校验"的区别在于插件**额外提供调用方身份识别**，可对不同调用方配置不同凭证；`oauth` 是 **Higress 自己当授权服务器签票**（OAuth2 Access Token 签发，token 本体是 JWT、遵循 RFC9068），不是对接外部 IdP——对接外部 IdP 是 `oidc` 的活。

错误码值得单独核对，因为它决定客户端能不能区分"没带凭证"与"没权限"：`basic-auth` / `key-auth` 是 `401`（未提供 / 无效凭证）与 `403 Unauthorized consumer`（调用方无权限），`key-auth` 另有一条 `401 Muti API key found`（官方拼写如此）。`hmac-auth` 更细：`401 Invalid Key`、`401 Empty Signature`、`400 Invalid Signature`、`400 Invalid Content-MD5`、`400 Invalid Date`（超过 `date_offset`）、`413 Request Body Too Large`（**Body 上限 32 MB**）。

## External Auth Engines

`ext-auth` 的实现参考 Envoy 原生 `ext_authz` filter，且**只覆盖了对接 HTTP 服务的那部分能力**。核心字段：`http_service`（必填，含 `endpoint_mode: envoy|forward_auth`（默认 envoy）、`endpoint.service_name`（带服务类型的完整 FQDN，如 `ext-auth.dns`）、`service_port` 默认 80、`service_host`、`timeout` 默认 1000ms、`authorization_request` / `authorization_response`）、`match_type` + `match_list`（每项 `match_rule_domain` 支持 `*.bar.com`、`match_rule_path`、`match_rule_type`）、以及三个失败语义开关：`failure_mode_allow`（默认 false，授权服务不可达或返回 5xx 时是否放行）、`failure_mode_allow_header_add`、`status_on_error`（默认 403）。

`opa` 把 Open Policy Agent 作为外部策略引擎，字段是 **camelCase**——`policy`、`timeout`、`serviceSource`（取值 `k8s,nacos,ip,route`）、`host`、`serviceName`、`servicePort`、`namespace` 全是。全站其它插件用 snake_case，**照抄邻居插件的风格写 opa 会静默不生效**。

`oidc` 是 oauth2-proxy 风格的字段表（英文 Option / Type / Description / Default）：`cookie_name` 默认 `_oauth2_proxy`、`provider` 默认 `oidc`、`oidc_issuer_url`、`client_id` / `client_secret`、`cookie_secret`（base64）、`cookie_expire` 默认 `168h0m0s`、`cookie_secure` / `cookie_httponly` 默认 true、`cookie_samesite`、`cookie_csrf_per_request` 默认 false、`cookie_csrf_expire` 默认 `15m`、`pass_authorization_header` 默认 true（以 Bearer 形式把 ID Token 传给上游）。它额外强调 CSRF 防御，并支持 OIDC 的 Logout Endpoint 与 Refresh Token。

## WAF and Request Defense

**WAF 的实现底座是 Coraza，不是 ModSecurity 本体**。最佳实践页的原文是"WAF 插件基于 Higress Wasm Go SDK 以及 **Coraza** 实现，遵循 ModSecurity 定义的 **Phase** 规范"，插件页则说"实现了基于 ModSecurity 的规则防护引擎，支持 OWASP CRS"——准确的说法是**兼容 ModSecurity 的 SecLang 规则语法与 Phase 规范**。配置只有两个字段：

```yaml
useCRS: true                                   # 默认 false！不写就等于没有 OWASP 规则集
secRules:
  - "SecRuleEngine DetectionOnly"              # 先观察不拦截
  - "SecRuleRemoveById 10"                     # 精准摘除误拦规则
  - "SecRule REQUEST_URI \"@streq /admin\" \"id:101,phase:1,t:lowercase,deny\""
```

三条实操要点：**`useCRS` 默认 false**，只装插件不写这个字段，等于只有用户自定义规则、没有基础防护；上线顺序是 `DetectionOnly` 观察 → 用 `SecRuleRemoveById` 摘误拦 → 再 `SecRuleEngine On`；支持路由级 / 域名级细粒度防护。效果评测官方推荐 **GoTestWAF**（API / OWASP 攻击模拟工具，支持 REST、GraphQL、gRPC、WebSocket、SOAP、XMLRPC），并指出 benchmark 里的 `paranoia` 是防护等级、**数值越大正确拦截与误拦截都同时增加**（CRS 版本、paranoia 可配字段与得分数值本次未取到可读数字，不写具体值）。

其余防护插件，注意它们的阶段与归类都不是直觉那样：

| 插件 | 阶段 / priority | 关键字段与默认值 |
| --- | --- | --- |
| `ip-restriction` | 认证阶段 / 210 | `ip_source_type`（默认 `origin-source` 取对端 socket IP，可选 header 方式）、`ip_header_name`（header 方式默认 `x-forwarded-for`）、`allow` / `deny`（默认 `[]`）、`status` 默认 **403**、`message` 默认 `Your IP address is blocked.` |
| `bot-detect` | 授权阶段 | `allow` / `deny` 都是 User-Agent 正则列表，`blocked_code` 默认 403、`blocked_message`。**两者都不配时才执行默认爬虫判断逻辑**；`allow` 的语义是"放行原本会命中默认逻辑的请求"、`deny` 是"追加判断逻辑"，与"allow=白名单"的直觉有偏差 |
| `request-block` | 鉴权阶段 | `block_urls`（子串）/ `block_exact_urls`（精确）/ `block_regexp_urls`（正则）/ `block_headers` / `block_bodies` 五项至少配一项；`blocked_code` 默认 403、`blocked_message`、`case_sensitive` 默认 **true** |
| `cors` | 授权阶段 | `allow_origins` 默认 `*`（格式 `scheme://host:port`）、`allow_origin_patterns`（用 `*` 匹配域名或端口）、`allow_methods` 默认 `GET, PUT, POST, DELETE, PATCH, OPTIONS`、`allow_headers`、`expose_headers`、`allow_credentials` 默认 **false**、`max_age` 默认 86400 |
| `replay-protection` | 认证阶段 / **800** | `force_nonce` 默认 true、`nonce_header` 默认 `X-Higress-Nonce`、`nonce_ttl` 默认 900 秒、`nonce_min_length` 8 / `nonce_max_length` 128、`reject_code` 默认 **429**（不是 403）、`reject_msg` 默认 `Replay Attack Detected`、`validate_base64` 默认 false、`redis` **必填** |
| `request-validation` | 默认阶段（归在 **traffic** 目录） | `header_schema` / `body_schema`（JSON Schema）、`rejected_code` 默认 403、`rejected_msg`、`enable_swagger` 默认 false、`enable_oas3` 默认 false |
| `custom-response` | 归在 **transformation** 目录 | `status_code` 默认 200、`headers`（array of string，`key=value` 形式）、`body`、`enable_on_status`（匹配原始状态码才生成，不填则不判断） |

`replay-protection` 与 `hmac-auth` 都叫"防重放"，但实现完全不同：前者**强依赖 Redis** 记录 nonce（`redis.service_name` 必填、`service_port` 默认 6379、`timeout` 默认 1000ms、`database` 默认 0），后者只靠 `date_offset` + `Date` 头。优先级数值还揭示一件反直觉的事：`replay-protection`（800）在认证阶段排在所有认证插件（310~360）之后，而 `ip-restriction`（210）也在它们之后——**安全动作的实际顺序按 priority 数值排，不按"插件名所属类别"排**，写"先 IP 再认证"这类直觉顺序前要先回优先级表核。

## Certificates and TLS

自动签发证书是 Higress 的**真实能力且默认开启**，配置在独立的 ConfigMap `higress-https`（`namespace: higress-system`，`data.cert`）里：

```yaml
automaticHttps: true          # 是否通过 ACME Issuer 签发证书
renewBeforeDays: 30           # 默认 30，最大值 90
fallbackForInvalidSecret: false   # ingress TLS 里写的 secretName 不存在时，按域名在 credentialConfig 里匹配
acmeIssuer:
  - name: letsencrypt         # 当前只支持这一个 issuer
    email: <通知邮箱>
credentialConfig:
  - tlsIssuer: letsencrypt    # 填了它，domains 只能一个且不能泛域名
    domains: [foo.com]
    tlsSecret: foo-com-secret
```

Helm 侧等价开关是 `higress-core.controller.automaticHttps.enabled`（默认 true）与 `.automaticHttps.email`（**为空时系统随机生成邮箱地址**）。

> [!WARNING]
> 三条限制必须和这个能力一起写：① **当前仅对 Ingress 模式生效，Gateway API 暂不支持**（文档原文），而 Gateway API 本身默认就是关闭的（`global.enableGatewayAPI` 默认 false）；② **泛域名与 ACME 互斥**——`tlsIssuer: letsencrypt` 时 `domains` 只能填一个且不能是泛域名，且 `tlsSecret` 不能是已存在的、非 Higress 创建的自动证书；只有**不填** `tlsIssuer` 时才能用泛域名批量管理 secret；③ 另有 `higress-console.certmanager.enabled` 默认 false，不要把它当成 ACME 的开关。

其余证书与 TLS 事实：证书来源还可以是普通 K8s TLS Secret（Ingress 的 `secretName` + `fallbackForInvalidSecret` 兜底匹配）；域名级 TLS 版本用 `higress.io/tls-min-protocol-version`（默认 TLSv1.0）与 `higress.io/tls-max-protocol-version`（默认 TLSv1.3），`nginx.ingress.kubernetes.io/ssl-cipher` 仅 TLSv1.0–1.2 生效；`ssl-redirect` 与 `force-ssl-redirect` 在 Higress 里**不区分对待**，都是强制 HTTP → HTTPS。网关到后端的 mTLS 走 `proxy-ssl-secret` + **必须存在同名字加 `-cacert` 的 CA Secret**（`auth-tls-secret` 侧同样是 `<名字>-cacert` 格式且被标为"部分兼容"），具体 annotation 组合在 [Traffic Governance](/docs/CS/Framework/Higress/Traffic_Governance.md)。信任域由 `higress-core.meshConfig.trustDomain` 决定（默认 `cluster.local`，用于生成服务证书与 JWT Token），`higress-core.pilot.jwksResolverExtraRootCA` 可让 pilot 解析 JWKS URI 时额外信任一个 PEM 根证书。

关于凭据，本子树只记录机制不记录值：服务发现认证用 `authSecretName` 指向 `higress-system` 下的 Secret（nacos 存 `nacosUsername` / `nacosPassword`，consul 存 `consulToken`）；Docker Compose 的 `-k/--data-enc-key` **长度必须 32 个字符**，未设置则自动生成随机密钥，**集群部署时必须显式设置**，否则各节点密钥不一致。

## Unverified

`ext-auth` 的 `authorization_request` / `authorization_response` 子字段全集（是否含 `withRequestBody`、maxRequestBytes、allowed_headers 等 Envoy 同名概念的确切字段名）；CRS 版本号、`paranoia level` 的可配字段与默认等级、GoTestWAF 得分数值；`oidc` 是否也支持 consumer / allow 式的按调用方授权；mTLS 服务网格侧的证书轮转细节（`trustDomain` 已核实，其下的证书生命周期未核实）。

## Links

- [Plugin System](/docs/CS/Framework/Higress/Plugin_System.md)
- [Traffic Governance](/docs/CS/Framework/Higress/Traffic_Governance.md)
- [Architecture](/docs/CS/Framework/Higress/Architecture.md)
- [AI Gateway](/docs/CS/Framework/Higress/AI_Gateway.md)
- [Istio Security](/docs/CS/Framework/Istio/Security.md)
- [Higress](/docs/CS/Framework/Higress/Higress.md)

## References

- [Wasm 插件使用简介](https://higress.ai/docs/latest/user/plugins/intro/)
- [Key 认证](https://higress.ai/docs/latest/user/plugins/authentication/key-auth/)
- [JWT 认证](https://higress.ai/docs/latest/user/plugins/authentication/jwt-auth/)
- [OIDC 认证](https://higress.ai/docs/latest/user/plugins/authentication/oidc/)
- [外部认证](https://higress.ai/docs/latest/user/plugins/authentication/ext-auth/)
- [OPA](https://higress.ai/docs/latest/user/plugins/authentication/opa/)
- [WAF](https://higress.ai/docs/latest/user/plugins/security/waf/)
- [开启 WAF 防护的最佳实践](https://higress.ai/docs/latest/user/waf/)
- [防重放攻击](https://higress.ai/docs/latest/user/plugins/security/replay-protection/)
- [全局配置说明](https://higress.ai/docs/latest/user/configmap/)
