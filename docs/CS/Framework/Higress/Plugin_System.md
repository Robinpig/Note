## Introduction

Higress 的扩展能力全部收敛到一个模型：**插件是 Envoy HTTP filter 链里的一个 Wasm 模块，由 `WasmPlugin` CRD 声明、以 OCI 镜像分发、经 ECDS 热加载**。这一页管四件事——官方插件到底有多少、作用域为什么有两套口径、多个插件同时存在时谁先跑、以及"不重启就换插件"是怎么做到的。写插件本身在 [Wasm Development](/docs/CS/Framework/Higress/Wasm_Development.md)。

## The Official Inventory

官方[插件市场页](https://higress.ai/plugins/)自标 **"共 41 款插件 覆盖 5 个分类"**，与文档站索引 `user/plugins/**` 的 41 条一一对应（`intro` 与 `custom` 是使用说明页，不计入）。因此旧口径"50+ 官方内置插件"应改为 **41**。

| 分类 | 数量 | 插件 |
| --- | --- | --- |
| AI | 17 | api-provider：`ai-cache`、`ai-prompt-decorator`、`ai-proxy`、`ai-security-guard`；api-consumer：`ai-data-masking`、`ai-quota`、`ai-token-ratelimit`；api-dev：`ai-agent`、`ai-json-resp`、`ai-prompt-template`、`ai-search`；api-o11y：`ai-statistics`、`geo-ip`；others：`ai-history`、`ai-intent`、`ai-rag`、`ai-transformer` |
| 认证鉴权 | 9 | `basic-auth`、`ext-auth`、`hmac-auth`、`hmac-auth-apisix`、`jwt-auth`、`key-auth`、`oauth`、`oidc`、`opa` |
| 安全防护 | 6 | `bot-detect`、`cors`、`ip-restriction`、`replay-protection`、`request-block`、`waf` |
| 流量管理 | 4 | `cluster-key-rate-limit`、`key-rate-limit`、`request-validation`、`traffic-tag` |
| 请求转换 | 5 | `cache-control`、`custom-response`、`de-graphql`、`frontend-gray`、`transformer` |

三条按目录归类时会踩空的地方：`request-validation` 在 **traffic** 目录而不是 security；`custom-response` 与 `frontend-gray` 在 **transformation**；`geo-ip` 归在 AI 分类（路径 `api-o11y`）而不是安全。分类只是文档站的信息架构，**不代表执行时机**——时机看下一节。

还有一条比清单本身更重要：**文档站索引不等于插件全集**。`ai-load-balancer` 是真实存在的 wasm-go 插件，但它的文档页取不到正文、`llms.txt` 里也没有条目，属于"只有仓库 README、没有文档站页面"的那一类。用索引当权威清单会系统性漏能力（详见 [AI Gateway](/docs/CS/Framework/Higress/AI_Gateway.md)）。

## Two Scope Systems

"作用域有几级"这个问题有两个答案，因为它们说的是两套东西：

**控制台口径是三级**：全局（插件市场）、域名级（域名管理 → 策略）、路由级（路由配置 → 策略），生效优先级 **路由级 > 域名级 > 全局**，且"对于没有匹配到具体路由或域名的请求才会生效全局配置"。一般插件的路由 / 域名级配置字段与全局配置字段**完全一样**；认证类插件是例外——全局级只放 Consumer 凭证与是否开启全局认证，路由 / 域名级只放 `allow`（详见 [Security and Auth](/docs/CS/Framework/Higress/Security_and_Auth.md)）。

**CRD 口径多出一级 service**。`WasmPlugin` 在 Higress 侧（`extensions.higress.io/v1alpha1`）扩展的字段，[插件使用简介](https://higress.ai/docs/latest/user/plugins/intro/)的字段表只列了两个：`defaultConfig`（"插件默认配置，全局生效于没有匹配具体域名和路由配置的请求"）与 `matchRules`。但生效原理页的样例里出现了第三种匹配键：

```yaml
matchRules:
  - service: [echo-server.higress-course.svc.cluster.local]
    config:
      ...
```

把转换后的形态摊开看得更清楚。`convertIstioWasmPlugin`（`pkg/ingress/config/ingress_config.go`）会生成 Istio `WasmPlugin`，其 `pluginConfig` 内出现 `_rules_` 列表，匹配键有三个：`_match_domain_`（域名，支持通配）、`_match_route_`（格式 `命名空间/Ingress名称`）、`_match_service_`（服务，支持通配）。运行时插件在 `OnHttpRequestHeaders` 阶段按当前请求的 `:authority` / `route_name` / `cluster_name` 取对应级别配置（`plugins/wasm-go/pkg/matcher/rule_matcher.go` 的 `GetMatchConfig`）。

> [!NOTE]
> 两条容易漏掉的规则：① **多条 `matchRules` 按数组书写顺序优先匹配**，不是按特异性；官方建议把 `ingress` 匹配放在 `domain` 之前，控制台就是这么做的。② `configDisable` 与 `defaultConfigDisable` **确实存在**（Go SDK 原理页的 basic-auth 样例里真实出现，分别关闭某条规则与默认配置），但 `intro` 页的字段表没列——引用出处要用后者。

## Phase and Priority Registry

插件链的顺序由 `WasmPlugin` **顶层**的 `phase` 与 `priority` 决定（注意不是 `matchRules` 项内字段）。`phase` 四个取值对应四个插入点：`UNSPECIFIED_PHASE`（插件过滤器链末端）、`AUTHN`（Istio 认证过滤器之前）、`AUTHZ`（认证之后、授权之前）、`STATS`（授权之后、统计之前）；**同 phase 下 priority 越大越靠前**。

下面这张表是全子树共用的判读件，其它页引用而不重述：

| 插件 | 阶段 | priority |
| --- | --- | --- |
| `ai-cache` | 认证阶段 | 10 |
| `ip-restriction` | 认证阶段 | 210 |
| `key-auth` | 认证阶段 | 310 |
| `basic-auth` | 认证阶段 | 320 |
| `hmac-auth` / `hmac-auth-apisix` | 认证阶段 | 330 |
| `jwt-auth` | 认证阶段 | 340 |
| `oauth` / `oidc` | 认证阶段 | 350 |
| `ext-auth` | 认证阶段 | 360 |
| `frontend-gray` | 认证阶段 | 450 |
| `replay-protection` | 认证阶段 | 800 |
| `ai-data-masking` | 认证阶段 | 991 |
| `key-rate-limit` | 默认阶段 | 10 |
| `cluster-key-rate-limit` | 默认阶段 | 20 |
| `mcp-server` | 默认阶段 | 30 |
| `ai-proxy` | 默认阶段 | 100 |
| `ai-statistics` | 默认阶段 | 200 |
| `opa` | 默认阶段 | 225 |
| `ai-security-guard` | 默认阶段 | 300 |
| `traffic-tag` | 默认阶段 | 400 |
| `ai-token-ratelimit` | 默认阶段 | 600 |
| `ai-quota` | 默认阶段 | 750 |
| `custom-response` | AUTHN | 200 |

这张表解释了三件反直觉的事：`ai-cache`（认证阶段 10）早于所有默认阶段的限流与配额插件，**缓存命中可以完全绕过 `ai-token-ratelimit` 与 `ai-quota`**；`ai-data-masking` 排在认证阶段末尾（991），所以它在鉴权与内容安全之后才脱敏；`frontend-gray` 名字在"转换"分类里，却跑在认证阶段 450。写任何"某插件一定生效"的结论前，先回这张表核对它和谁抢顺序。

## Hot Reload via ECDS

热更新的完整链路九步，关键是**Envoy 收到的不是插件配置，而是一个订阅桩**：

1. `WasmPlugin` 资源更新 → 2. Higress Core 转成 Istio `WasmPlugin` → 3. MCP over XDS 推给 Discovery → 4. 经 Pilot Agent 走 ADS/LDS 下发 → 5. **Envoy 通过 ECDS（Extension Config Discovery Service）订阅插件配置**，Listener 里只有 `config_discovery` → 6. Pilot Agent 拦截 ECDS 响应，按 OCI 配置从 Registry Hub 拉镜像 → 7. 解压 wasm 到本地 → 8. 把 ECDS 响应里的地址改写成本地路径 → 9. Envoy 加载本地 wasm 文件。

官方对结果的表述是"Wasm 插件是通过 OCI 实现了 wasm 文件更新，直接热加载，不会导致任何连接中断，业务流量完全无损"。Envoy 侧每个插件条目的形态是 `config_discovery` + `default_config: Composite` + `apply_default_config_without_warming: true`，`type_urls` 含 `envoy.filters.http.wasm.v3.Wasm` 与 `composite.v3.Composite`。插件链生成的 filter 名形如 `higress-system.custom-response`、`higress-system.wasm-keyauth`。

**分发规范**。wasm 镜像是普通 OCI 分布格式，文件与 media type 一一对应：`spec.yaml` → `application/vnd.module.wasm.spec.v1+yaml`、`README.md` → `...doc.v1+markdown`（多语言 `README_{lang}.md` → `...doc.v1.{lang}+markdown`）、`icon.png` → `...icon.v1+png`，且 **`plugin.wasm` 必须放在镜像最后一层**（该层用 `application/vnd.oci.image.layer.v1.tar+gzip`）。`spec.yaml` 元数据里带 `phase`、`priority` 与 `configSchema`（仅支持 OpenAPI 3.0.0 Schema）。也支持 `url` 直接指向 http(s) 的 `.wasm` 文件，前提是 Gateway 容器内能访问该 URL；自签证书场景要在 Gateway 容器设 `WASM_INSECURE_REGISTRIES=*`。

**官方插件地址**。清单在 `higress-console` 仓库的 `backend/sdk/src/main/resources/plugins/plugins.properties`，稳定 tag 统一 `1.0.0`、开发版 `latest`；示例形态 `oci://higress-registry.cn-hangzhou.cr.aliyuncs.com/plugins/request-block:1.0.0`。用 `latest` 时"插件有任意配置更新就会自动拉取最新版本"。换到私有仓库是改 Console 容器的环境变量 `HIGRESS_ADMIN_WASM_PLUGIN_CUSTOM_IMAGE_URL_PATTERN`（占位符 `${name}` / `${version}`），Nacos 3.x 的 MCP 注册中心另有一个 `MCP_SERVER_WASM_IMAGE_URL`；各形态的写法与转义细节见 [Deployment and Ops](/docs/CS/Framework/Higress/Deployment_and_Ops.md)。

## Inspecting the Plugin Chain

两个命令能回答"我的配置到底变成什么了"，分别打在控制面和数据面：

```bash
# 控制面：看 higress-core 生成的配置（转换后的 WasmPlugin / _rules_ 就在这份输出里）
kubectl exec <higress-controller-pod> -c higress-core -n higress-system -- \
  curl http://127.0.0.1:8888/debug/configz?pretty

# 数据面：看 Envoy 实际加载的过滤器链与相对顺序
kubectl exec <higress-gateway-pod> -n higress-system -- \
  curl http://127.0.0.1:15000/config_dump
```

`config_dump` 里能直接看到 wasm 插件被插在 `envoy.filters.http.cors`、`envoy.filters.http.rbac`、`envoy.filters.http.local_ratelimit`、`envoy.filters.http.fault`、`envoy.filters.http.router` 这些原生过滤器之间——这也是"为什么某些安全语义与 Envoy 原生不一致"的答案。四层排障链（8888 → 15014 → 15000）的完整走法在 [Deployment and Ops](/docs/CS/Framework/Higress/Deployment_and_Ops.md)。

## Links

- [Wasm Development](/docs/CS/Framework/Higress/Wasm_Development.md)
- [Architecture](/docs/CS/Framework/Higress/Architecture.md)
- [Security and Auth](/docs/CS/Framework/Higress/Security_and_Auth.md)
- [AI Gateway](/docs/CS/Framework/Higress/AI_Gateway.md)
- [WasmPlugin](/docs/CS/Framework/Istio/WasmPlugin.md)
- [Higress](/docs/CS/Framework/Higress/Higress.md)

## References

- [Wasm 插件使用简介](https://higress.ai/docs/latest/user/plugins/intro/)
- [Wasm 插件原理](https://higress.ai/docs/latest/user/plugins/wasm-dev/wasm15/)
- [Wasm 生效原理](https://higress.ai/docs/latest/user/plugins/wasm-dev/wasm19/)
- [Wasm 插件镜像规范](https://higress.ai/docs/latest/user/wasm-image-spec/)
- [Higress 插件市场](https://higress.ai/plugins/)
- [使用 HTTP/HTTPS 协议加载 Wasm 插件](https://higress.ai/docs/latest/ops/how-tos/load-wasm-with-http/)
- [修改内置插件镜像地址](https://higress.ai/docs/latest/ops/how-tos/builtin-plugin-url/)
