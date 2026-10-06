## Introduction

Higress 是阿里巴巴开源的云原生 API 网关，内核基于 Istio 与 Envoy，以 Wasm 插件（Go / Rust / JS）扩展能力，提供开箱即用的控制台与数十个通用插件。它诞生于阿里内部，用于解决 Tengine reload 影响长连接、以及对 gRPC / Dubbo 流量负载均衡能力不足的问题；阿里云基于 Higress 构建了云原生 API 网关产品（为企业客户提供 99.99% 网关高可用保障）。Higress 已于 2023 年进入 CNCF 沙箱（CNCF Sandbox），最新开源稳定线为 **2.2.x**。

> [!NOTE]
> 版本线：截至 2026 年，开源稳定线为 **2.2.x**（最新 2.2.4，2026-08 发布）；2.2.2（2026-05）新增 AWS Bedrock 直连与 vLLM 支持，2.1.x 起控制台支持 AI 流量入口管理，2.2.x 增加对 CNCF AI 基础设施（如 LLM-D）的集成。社区版免费且开源，企业版仅 patch 节奏不同（major/minor 对齐，patch 不保证逐版本对齐）。Higress 当前已支持 100+ 主流大模型统一接入。

Higress 在 [Spring Cloud Alibaba](/docs/CS/Framework/Spring_Cloud/Alibaba.md) 体系中是**推荐的云原生网关**，可作为 [Spring Cloud Gateway](/docs/CS/Framework/Spring_Cloud/gateway.md) 的替代。它与 [Nacos](/docs/CS/Framework/nacos/Nacos.md)、[Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)、[Sentinel](/docs/CS/Framework/Sentinel/Sentinel.md) 等微服务技术栈深度集成，可直接从注册中心发现服务并路由。

### 三种网关角色

- **AI 网关**：以统一协议接入国内外主流大模型，提供 AI 可观测、多模型负载均衡 / 兜底、AI token 限流、AI 缓存等能力；并可作为 MCP Server 的托管网关，为工具调用提供统一鉴权、限流与审计。
- **Kubernetes Ingress 控制器**：兼容 nginx ingress controller 的多数 annotation，并规划平滑迁移到 Gateway API。
- **微服务网关**：从 Nacos、ZooKeeper、Consul、Eureka 等注册中心发现服务，深度对接 Dubbo / Nacos / Sentinel。

### 架构：控制面与数据面

Higress 采用**三平面**架构，控制面与数据面分离，二者通过 xDS 协议通信：

- **Console（管理面）**：可视化 UI，后端为 Java / SpringBoot 服务，前端为 Node.js 应用。
- **Controller（控制面，higress-controller）**：含两个容器组件。
  - `higress-core` 监听 Kubernetes API，把 Ingress、Higress CRD 翻译为 Istio API 对象（VirtualService / DestinationRule / Gateway / EnvoyFilter）。
  - `pilot` 是 Istio `istiod` 的 pilot 模块 fork，把 Istio API 对象转换为 xDS 资源并推送给数据面。
- **Gateway（数据面，higress-gateway）**：内嵌 Envoy 代理，真正执行请求转发、Wasm 插件、路由、限流、认证。

Higress 复用 Istio 的 **xDS 协议**、K8s CRD 配置存储机制以及多注册中心的服务发现能力，因此所有配置以 CRD 形式落于 Kubernetes etcd，无需外部数据库。配置流转如下：

| 配置来源 | 转换产物 | 下发通道 |
| --- | --- | --- |
| Ingress / Gateway API / Istio API | VirtualService / DestinationRule / Gateway | xDS（gRPC 流） |
| Higress CRD：McpBridge / WasmPlugin / Http2Rpc | EnvoyFilter / ServiceEntry | xDS（gRPC 流） |
| Ingress annotation | 等价 Istio 配置 | xDS（gRPC 流） |

`McpBridge` 用于**解耦核心网关与具体注册中心**：把 Nacos / Consul / DNS 等注册源转换为 Istio 的 `ServiceEntry`。`WasmPlugin Controller` 把 Higress 的 WasmPlugin 映射到 Istio WasmPlugin，支持 global / route 两种作用域。

> [!WARNING]
> 控制面里的 `istio` 是在原生 Istio 基础上改造的 fork，与独立安装的 Istio 并不等价。若需要使用 Istio 原生的服务网格能力，建议单独安装 Istio，而非依赖 Higress 内置的 fork。

### 部署与配置入口

- **Helm 安装**：`helm repo add higress.io https://higress.cn/helm-charts` 后 `helm install higress -n higress-system higress.io/higress --create-namespace`；本地测试（Kind 等）加 `--set global.local=true`。
- **Docker 一键体验**：`docker run -d --rm --name higress -p 8001:8001 -p 8080:8080 -p 8443:8443 higress/all-in-one:latest`，其中 8001 为控制台、8080 为 HTTP 入口、8443 为 HTTPS 入口。
- **配置优先级**：插件配置分 global / domain / route / service 多层级，细粒度覆盖粗粒度，规则匹配顺序为 Domain → Ingress → Default（路由级 > 域名级 > 全局级）。典型用法是全局开启 JWT 认证（`global_auth: false` 避免健康检查也被拦截），再在路由级按需覆盖。

### AI 网关（深化）

Higress 把 AI 流量作为一等公民，核心能力包括：

- **多模型统一接入**：对 OpenAI 兼容接口及主流大模型提供统一网关入口，屏蔽厂商鉴权与接口差异，便于快速切换与多活；支持模型负载均衡与 Fallback 提升可靠性。
- **Token 流量管理**：除传统 QPS 限流外，提供基于 Token 消耗的配额管理与限流（ai-token-ratelimit），结合 API Key 池轮询与消费者鉴权，防止模型过载并管控客户端额度。
- **语义缓存（ai-cache）**：基于语义相似度缓存 LLM 响应，相同或近似 prompt 直接从缓存返回，将延迟从秒级降到毫秒级并显著降本。
- **MCP 统一管理**：支持 HTTP 到 MCP 的协议转换，以及原生 MCP 服务的代理，把分散的工具能力收敛为统一入口；`openapi-to-mcpserver` 工具可将任意 OpenAPI 规范在数分钟内转为远程 MCP Server 插件。MCP 工具调用复用与 LLM API 相同的鉴权、限流与审计日志。
- **AI 内容安全（ai-security-guard）**：提示词注入检测、敏感内容识别、数据脱敏，支持 block / mask / audit 三种风险处置动作。

内置 AI 插件（部分）如下：

| 插件 | 作用 |
| --- | --- |
| ai-proxy | 统一对接 OpenAI / 通义千问 / Claude 等所有 LLM 厂商，协议转换 + 负载均衡 |
| ai-cache | LLM 响应缓存，支持语义缓存与精确匹配 |
| ai-token-ratelimit | 基于 Token 的限流，按 API Key / IP / Consumer 精确控制消耗 |
| ai-load-balancer | LLM 感知负载均衡（KV Cache 亲和、vLLM metrics、最小请求数） |
| ai-security-guard | AI 输入 / 输出安全防护 |
| ai-quota | AI 配额管理（按时间 / 总量限制） |
| ai-rag | 检索增强生成，对接知识库 |
| model-router | 按请求特征路由到不同模型 |

### 限流与流量治理

Higress 提供从单机到集群的多层次限流，覆盖「防过载」与「配额管理」两类诉求：

- **本地限流（key-rate-limit）**：每个 Gateway Pod 独立计数，零延迟、无外部依赖；缺点是总限流随 Pod 副本数线性放大（例如配置 100 QPS、3 副本实际放行约 300 QPS）。适合粗粒度保护、抗突发流量。
- **集群限流（cluster-key-rate-limit）**：基于 Redis 的全局一致限流，适合精确控制 API 调用配额（如免费用户每日 1000 次）。支持两种模式：规则级全局阈值（global_threshold）与 Key 级动态限流（按 URL 参数、请求头、客户端 IP、Consumer 名称或 Cookie 取值分组）。任一规则命中即拒绝，默认返回 429（Too many requests）。
- **Sentinel 流控**：Higress 提供 Sentinel 集成能力，可对接 Sentinel Dashboard 与 Token Server 实现集群流控（Cluster Flow Control），适合已有 Sentinel 体系、需要动态规则与熔断降级的团队。
- **灰度与流量打标**：`traffic-tag` 插件按 header / 参数 / Cookie 匹配（支持 equal、prefix、in、regex、percentage 等算子与 and / or 组合）或按权重（weightGroups）为请求染色，配合下游路由规则实现金丝雀发布；`frontend-gray` 面向前端灰度。同时兼容 nginx ingress 的 canary 注解（`higress.io/canary`、`higress.io/canary-weight`、`nginx.ingress.kubernetes.io/canary-by-header`），并可与 OpenKruise Rollout 联动做渐进式发布。
- **熔断**：基于 Envoy 的异常点检测（Outlier Detection）实现后端实例自动熔断与驱逐，结合本地限流做粗粒度保护、集群限流做细粒度配额，形成「本地防 DDoS + 集群管配额」的双层防护。

### 服务发现与 RPC 路由

Higress 支持从多种注册中心发现后端服务：Nacos、Consul、ZooKeeper、Eureka、Kubernetes、DNS。对于 Dubbo 等 RPC 协议，通过 **Http2Rpc CRD** 完成 HTTP 到 RPC 的服务发现与协议转换，使网关侧以标准 HTTP 路由即可把流量导向 Dubbo Triple（基于 HTTP/2）接口。与 Nacos / Dubbo / Sentinel 的深度对接使 Higress 在 Alibaba 微服务栈中可同时承担流量网关、微服务网关与安全网关（三网关合一）。

### 配置示例：Nacos 服务发现与路由

下面给出一段最小可运行配置：先用 McpBridge 把 Nacos 2.x（gRPC）注册中心接入，再用 Ingress 把流量路由到注册在 Nacos 上的 `user-center` 服务，最后用 WasmPlugin 对该路由开启 Key 认证。

```yaml
# 1) 服务来源：对接 Nacos 2.x
apiVersion: networking.higress.io/v1
kind: McpBridge
metadata:
  name: default
  namespace: higress-system
spec:
  registries:
    - name: my-nacos
      type: nacos2            # Nacos 2.x，基于 gRPC，变更感知更快
      domain: 127.0.0.1
      port: 8848
      nacosNamespaceId: d8ac64f3-xxxx-xxxx-xxxx-47a814ecf358
      nacosGroups:
        - DEFAULT_GROUP
---
# 2) 路由：把 / 转发到 Nacos 上的 user-center 服务
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: user
  namespace: default
  annotations:
    higress.io/destination: "user-center.DEFAULT-GROUP.d8ac64f3-xxxx-xxxx-xxxx-47a814ecf358.nacos"
spec:
  rules:
    - http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              resource:
                apiGroup: networking.higress.io
                kind: McpBridge
                name: default
---
# 3) 插件：对该网关开启 Key 认证
apiVersion: extensions.istio.io/v1alpha1
kind: WasmPlugin
metadata:
  name: key-auth
  namespace: higress-system
spec:
  selector:
    matchLabels:
      higress: higress-system-higress-gateway
  pluginConfig:
    consumers:
      - name: app-a
        key: abc123
  url: oci://higress-registry.cn-hangzhou.cr.aliyuncs.com/plugins/key-auth:1.0.0
```

> [!NOTE]
> Ingress 中 `higress.io/destination` 的格式为 `服务名.服务分组.命名空间ID.nacos`，下划线会按 DNS 规则转换为连字符。Spring Cloud 微服务无需改造即可接入，相比 Spring Cloud Gateway / Zuul 等传统 Java 网关性能高出 2 倍以上。

### 插件体系与扩展

Higress 提供 50+ 官方内置 Wasm 插件，覆盖 AI、认证、安全、流量管理、转换五大类。插件以 Go / Rust / JS 编写并编译为 Wasm 模块，通过 WasmPlugin CRD 引用，运行于 Envoy 数据面的 Wasm 沙箱中（安全隔离 + 热更新，不重启网关即可生效）。

| 类别 | 代表插件 |
| --- | --- |
| 认证 | basic-auth、key-auth、hmac-auth、jwt-auth、oidc、oauth2、ext-auth、opa |
| 安全 | waf（ModSecurity + OWASP CRS）、cors、ip-restriction、bot-detect、request-block、replay-protection、geo-ip |
| 流量管理 | key-rate-limit、cluster-key-rate-limit（基于 Redis 的集群限流）、custom-response、traffic-tag（灰度打标）、request-validation、transformer、cache-control、frontend-gray |
| AI | ai-proxy、ai-cache、ai-token-ratelimit、ai-security-guard、ai-rag、model-router 等（见上节） |

自定义插件开发使用 `wasm-go`（Go SDK）、Rust SDK 或 JS，编译产物经 `WasmPlugin` CRD 部署，支持 global / domain / route / service 作用域与细粒度匹配规则。

### 可观测性

Higress 提供 Metrics / Logging / Tracing 三大支柱，均通过 Helm values 与 `higress-config` ConfigMap 配置，同时作用于控制面与数据面：

- **指标（Metrics）**：Gateway Pod 在 15020 端口暴露 Prometheus 指标（`/stats/prometheus`，另含 15090），配合 `prometheus.io/scrape`、`prometheus.io/port`、`prometheus.io/path` 注解即可被自动抓取。资源受限环境可开 `LITE_METRICS=on` 精简指标基数。关键 AI 指标包括 `higress_ai_token_count`（按 provider / route 的输入输出 Token）、`higress_ai_cache_hit_ratio`（语义缓存命中率）、`higress_ai_fallback_count`（模型兜底次数）、`higress_ai_provider_request_duration_ms`（各供应商延迟）。
- **日志（Logging）**：默认输出结构化 JSON 访问日志；启用 AI 统计插件后，访问日志会注入 `input_token`、`output_token`、`llm_service_duration`、`llm_first_token_duration`（TTFT，流式首 Token 时延）、`ai_log` 等字段，便于按模型 / 路由核算成本。
- **追踪（Tracing）**：支持 Skywalking、Zipkin、OpenTelemetry 三种后端，采样率默认 100%，通过生成 `custom_bootstrap.json` 挂载到网关生效。
- **零停机更新**：配置变更经 xDS 动态下发，Envoy 在工作线程动态生效，无需 reload / 重启；Wasm 插件也支持热更新，流量无损。运维侧提供 `hgctl` CLI（install / config 等子命令）检视网关内部状态。

### 安全能力

Higress 内置完善的认证、防护与 WAF 能力，开箱即用：

| 能力 | 代表插件 |
| --- | --- |
| 认证 | key-auth、basic-auth、hmac-auth、jwt-auth、oidc、oauth2、ext-auth（对接外部鉴权）、opa（Open Policy Agent） |
| 防护 | waf（基于 ModSecurity + OWASP CRS）、cors、ip-restriction、bot-detect、request-block、replay-protection（防重放）、geo-ip |
| 请求治理 | request-validation（参数校验）、transformer（请求 / 响应转换）、cache-control |

证书方面支持对接 Let's Encrypt 自动签发与续签免费证书；安全插件与认证插件均支持 global / domain / route / service 多作用域，可与限流、灰度策略在同一路由上叠加生效。

### 与 Spring Cloud Gateway 的取舍

- Higress 基于 Envoy 数据面，原生擅长长连接、gRPC / Dubbo 等 RPC 流量与高性能转发；Spring Cloud Gateway 基于 Spring WebFlux，更贴合 Spring 生态、上手简单。
- 若网关需同时承载 AI 流量、K8s Ingress、以及 Dubbo / gRPC 等 RPC 协议，Higress 的一体化能力更契合；纯 Spring HTTP 微服务场景用 Spring Cloud Gateway 亦可。

> [!NOTE]
> 性能上，Higress 基于 Envoy C++ 内核，相比 Spring Cloud Gateway / Zuul 等 Java 网关吞吐高 2 倍以上，且彻底摆脱 nginx reload 对长连接的损耗——配置变更毫秒级生效、业务无感，在阿里双十一等数十万级 QPS 场景生产验证；在支持非特权端口的内核（>= 4.11.0）上以非 root（UID 1337）运行。

### Wasm 插件开发实战

Higress 的插件用 Go / Rust / JS 编写、编译为 Wasm 模块，经 `WasmPlugin` CRD 引用，运行于 Envoy 数据面的 Wasm 沙箱中（内存安全隔离 + 热更新）。Go 开发基于 `wasm-go` SDK（封装了 Tetrate 的 proxy-wasm-go-sdk，利用 Go 1.18 泛型简化上下文处理）。

最小插件模板（Go 1.24 起已原生支持编译 Wasm，逻辑从 `main` 挪到 `init` 注册）：

```go
package main

import (
    "github.com/higress-group/wasm-go/pkg/wrapper"
    "github.com/higress-group/proxy-wasm-go-sdk/proxywasm"
    "github.com/higress-group/proxy-wasm-go-sdk/proxywasm/types"
    "github.com/tidwall/gjson"
)

func init() {
    wrapper.SetCtx(
        "my-plugin",
        wrapper.ParseConfig(parseConfig),
        wrapper.ProcessRequestHeaders(onHttpRequestHeaders),
    )
}

type MyConfig struct{ Enabled bool }

func parseConfig(json gjson.Result, config *MyConfig) error {
    config.Enabled = json.Get("enabled").Bool()
    return nil
}

func onHttpRequestHeaders(ctx wrapper.HttpContext, config MyConfig) types.Action {
    if config.Enabled {
        proxywasm.AddHttpRequestHeader("x-my-header", "hello")
    }
    return types.HeaderContinue
}
```

构建与部署三步：

```bash
# 1) 编译为 Wasm（Go 1.24 原生）
GOOS=wasip1 GOARCH=wasm go build -buildmode=c-shared -o main.wasm ./

# 2) 打包镜像
cat > Dockerfile <<'EOF'
FROM scratch
COPY main.wasm plugin.wasm
EOF
docker build -t my-registry/my-plugin:1.0.0 .

# 3) 下发 WasmPlugin
kubectl apply -f - <<'EOF'
apiVersion: extensions.istio.io/v1alpha1
kind: WasmPlugin
metadata:
  name: my-plugin
  namespace: higress-system
spec:
  selector:
    matchLabels:
      higress: higress-system-higress-gateway
  pluginConfig:
    enabled: true
  url: oci://my-registry/my-plugin:1.0.0
EOF
```

插件可挂载的执行阶段包括 `ProcessRequestHeaders` / `ProcessRequestBody` / `ProcessResponseHeaders` / `ProcessResponseBody` / `ProcessStreamDone`，天然支持 SSE 等流式报文的在途处理；借助 host 提供的 HTTP Client 与 Redis 调用能力，还能实现外部鉴权、有状态限流等复杂逻辑。

### 代码目录结构

- cmd：命令行参数解析等处理代码
- pkg/ingress：Ingress 资源转换为 Istio 资源等相关代码
- pkg/bootstrap：包括启动 gRPC / xDS / HTTP server 等的代码
- registry：实现对接多种注册中心进行服务发现的代码
- envoy：依赖的 envoy 仓库 commit
- istio：依赖的 istio 仓库 commit
- plugins：Higress 插件 SDK，以及官方内置插件代码（wasm-go 子目录为 Go 插件源码）
- script / docker：编译与镜像构建相关脚本

## Links

- [Istio](/docs/CS/Framework/Istio/Istio.md)
- [Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md)
- [gateway](/docs/CS/Framework/Spring_Cloud/gateway.md)
- [Spring Cloud Alibaba](/docs/CS/Framework/Spring_Cloud/Alibaba.md)
- [Nacos](/docs/CS/Framework/nacos/Nacos.md)
- [Sentinel](/docs/CS/Framework/Sentinel/Sentinel.md)

## References

- Higress GitHub 仓库：https://github.com/alibaba/higress
- 架构文档：https://github.com/alibaba/higress/blob/main/docs/architecture.md
- AI 网关产品页：https://higress.ai/ai-gateway
- 插件市场：https://higress.ai/en/plugins/
- 版本计划 / Roadmap：https://higress.io/docs/latest/overview/roadmap
