## Introduction

反向代理赛道已经分化成四代形态：**C 语言事件驱动服务器**（nginx/HAProxy）、**Go 运行时集成**（Caddy）、**xDS 动态数据平面**（Envoy）、**Rust 框架**（Pingora）。它们不是简单的竞争关系——定位差异比性能差异更重要：nginx 是「高性能瑞士军刀」，HAProxy 是「负载均衡专家」，Envoy 是「服务网格数据平面」，Caddy 是「零配置自动 HTTPS」，Pingora 是「自建代理的框架而非产品」。

版本基线（2026-10 核实）：nginx **1.31.6** mainline / **1.30.5** stable；Envoy **1.39.2**；HAProxy **3.4.6**（LTS 3.4，2026-06 发布，引入 dynamic backends）；Caddy **2.11.4**；Pingora **0.9.0**。网关侧：Traefik Proxy **3.7.13**（2026-09-04）、Apache APISIX **3.18.0**（2026-08-20）、Kong Gateway **3.16**（LTS 3.14，2026-04）、Higress **2.2.4**（2026-08，阿里开源 / CNCF 沙箱，Envoy 内核云原生网关）。

## 一屏对比

| 维度 | nginx | HAProxy | Envoy | Caddy | Pingora |
| :-- | :-- | :-- | :-- | :-- | :-- |
| 语言 | C | C | C++ | Go | Rust |
| 形态 | 服务器 | 服务器 | 服务器 | 服务器 | **库/框架** |
| 并发模型 | 多 worker 进程 × epoll | 单进程多线程 × epoll（1.8+ 默认多线程） | 多 worker 线程 × epoll | goroutine × netpoll | 多线程 tokio 异步运行时 |
| 配置 | 静态文件 + reload | 静态文件 + 无缝 reload；3.4 起动态后端（CLI/API） | **xDS API 全动态** | Caddyfile / JSON API 热载 | Rust 代码定义 |
| TLS | 成熟，会话复用/OCSP | 成熟 | 成熟 | **ACME 自动签发续期内置** | OpenSSL/BoringSSL/rustls 可选 |
| HTTP/3 | 1.25+（逐年强化） | 实验 | 生产级 | 实验 | 计划中（0.9 未含） |
| 动态上游 | resolver + zone（受限） | DNS/静态；3.4 dynamic backends | **原生**（EDS/CDS） | 反向适配器 | 代码定义 |
| 扩展机制 | C 模块 / Lua（OpenResty） | Lua / SPOE | C++ filter / WASM | Go 插件（需自编译） | Rust trait（最灵活） |
| 典型定位 | Web 服务器 + 反代 + 边缘 | 四层/七层负载均衡 | Service Mesh 数据面 / API 网关底座 | 自托管反代 / 内网服务 | CDN 边缘 / 自研代理 |

## 架构差异的深层原因

### nginx：多进程 + 无锁 accept

master fork 出 N 个 worker，共享监听 fd，靠 `EPOLLEXCLUSIVE`/`SO_REUSEPORT` 解决惊群（历史演进见 [Event](/docs/CS/CN/nginx/event.md)）。进程隔离换来**一个 worker 崩溃不影响其它**，代价是跨 worker 状态必须走共享内存（limit_req、cache 都如此）。配置是**编译进内存的静态结构**，变更靠 fork 新 worker 的 reload——这是它动态性弱、稳定性强的根源。

### HAProxy：单进程多线程 + stick tables

1.8 起默认多线程（`nbthread`），事件驱动内核与 nginx 同源，但**单进程内聚合所有状态**——stick tables（会话粘滞表、限流计数器）天然全进程共享，这是它做精细限流/会话保持的结构性优势。reload 用「新进程继承监听 fd + 老进程排空」模型（与 nginx 热升级同思路，但常态化为 `master-worker` 常驻）。3.4 的 dynamic backends 把「加后端不 reload」从 Plus 版特性拉平到开源。

### Envoy：线程模型 + 全动态

单进程多线程（worker 线程数 = 核数），每个 worker 独立跑完整 filter chain。**一切皆 xDS**：CDS/EDS/LDS/RDS 集群发现、监听器、路由全部通过 gRPC 订阅推送，控制面（Istio 等）变更秒级生效、无需进程操作。代价是配置模型复杂、内存开销高、排障链路长。它是为「大规模微服务 + 服务网格」设计的，单机反代场景是杀鸡用牛刀。

### Caddy：Go 运行时 + 自动证书

Go 的 netpoll（epoll/kqueue 封装）+ goroutine，单二进制、内存安全。最大差异化是 **ACME 客户端内置**：站点名写进 Caddyfile，签发/续期/重定向 80 端口全自动化——nginx 需要 certbot + 定时任务 + reload 编排的整套流程，Caddy 是零配置。性能低于 nginx/HAProxy（GC、goroutine 调度开销），但 self-hosting 场景足够。

### Pingora：框架不是服务器

Cloudflare 开源的 Rust 框架（0.9.0，2026-09），支撑其 CDN 每秒数千万请求。**它不提供开箱即用的二进制**——你用 Rust 实现 `ProxyHttp` trait 写出自己的代理，再编译。价值主张：内存安全替代 C/C++ 写的代理 + 多线程无惊群（线程间共享监听，连接均匀分配，冷连接转移）。适合「要自研代理/网关、且愿意维护 Rust 代码」的团队；不是 nginx 的 drop-in 替代品。

## 网关与 Ingress 侧：Traefik / APISIX / Kong / Higress

上面五个是「代理/负载均衡」视角，但近两年真正的战场在 **Kubernetes 入口**。2025-11-11 Kubernetes 社区官宣、并于 **2026-03 正式退役 ingress-nginx**，把这个位置空了出来——这直接推着网关产品改路线。Higress 作为阿里开源、CNCF 沙箱的 Envoy 内核云原生网关，正好踩中「K8s Ingress + 微服务网关 + AI 网关」三合一的空白，并可作为 Spring Cloud Gateway 的替代。

| 维度 | Traefik Proxy | Apache APISIX | Kong Gateway | NGINX Gateway Fabric | Higress |
| :-- | :-- | :-- | :-- | :-- | :-- |
| 当前版本 | **3.7.13** | **3.18.0** | **3.16**（LTS 3.14） | F5 维护 | **2.2.4**（2026-08） |
| 语言/底座 | Go | OpenResty（nginx + LuaJIT） | OpenResty | nginx | Go + **Envoy（Istio 内核）**，Wasm 插件（Go/Rust/JS） |
| 配置模型 | **自动发现**（K8s CRD / Docker / Consul…）provider 机制 | etcd + Admin API（声明式） | DB-less 声明式 / DB-backed | Gateway API | K8s CRD + **xDS（Istio API）**；兼容 Ingress annotation；规划 Gateway API |
| 定位 | 云原生入口 + API 网关 | 高性能 API 网关 + AI Gateway | API 网关 + AI 连接层 | nginx 官方 Gateway API 实现 | 云原生 API 网关 / **Spring Cloud Alibaba 推荐网关** / AI 网关 / 微服务网关（Nacos/Dubbo） |
| ingress-nginx 迁移 | **3.7 起 GA**：支持 85 条 ingress-nginx 注解（覆盖 90%+），含 `configuration-snippet` 等片段注解的**白名单解析**与 ModSecurity 接入 | Ingress Controller 2.2.0 独立版本节奏 | 走 Ingress Controller | 不适用（本就 Gateway API） | 兼容 nginx ingress 多数 annotation；规划平滑迁移到 Gateway API |
| 动态性 | 天生的（provider 监听资源变化，无需 reload） | 天生的（etcd watch，Admin API 热更新） | 天生的 | Gateway API 声明式 | xDS 全动态（配置经 xDS 下发，无需 reload） |
| 扩展 | Go 中间件（需自编译） / WASM | **Lua 插件 + 多语言 Plugin Runner**（Java/Go/Python sidecar） | Lua 插件（PDK） | nginx 模块 | Wasm 插件（Go/Rust/JS 多语言），经 WasmPlugin CRD，热更新 |

**怎么选**：如果团队已在 K8s 里、且原来用 ingress-nginx，最省事的路线是 **Traefik 3.7**（它把「annotation 兼容 + WAF 平迁」当成主卖点，迁移成本最低）或直接跳到 **Gateway API**（Traefik / APISIX / NGINX Gateway Fabric 都已支持）；如果是「非 K8s 的自建 API 网关」、需要细粒度插件与 Kong 生态，选 **Kong** 或 **APISIX**。

**共同趋势**：各家在 2026 年都把重心压到 **AI Gateway**——Traefik Hub 3.20 加了 token 级限流与配额、并行 LLM 护栏；APISIX 3.18 修的是 AI 代理的协议转换（Anthropic ↔ OpenAI）与流式语义；Kong 则把 AI Gateway 拆成独立产品线；**Higress 更是把 AI 流量作为一等公民**（ai-proxy / ai-cache / ai-token-ratelimit / MCP 托管网关），是这一波 AI 网关趋势的先行者。也就是说，**「反向代理 + 插件」的基本盘已经稳定，增量都在 LLM 流量的治理上**（成本、限流、协议适配、内容安全）。这一点值得单独记一笔：它意味着选型时要看的已经不只是 QPS 和延迟，还有「能不能按 token 计数、能不能处理 SSE 流式响应、能不能做协议转换」。

## 选型速查

| 场景 | 推荐 | 理由 |
| :-- | :-- | :-- |
| 传统 Web 服务器/反代/静态+缓存 | **nginx** | 生态、文档、运维经验最厚 |
| 纯四层 LB、精细限流、会话粘滞 | **HAProxy** | stick tables、健康检查、连接排队 |
| K8s 服务网格 / 大规模动态路由 | **Envoy** | xDS 全动态、网格生态（Istio 数据面） |
| 内网/自托管、自动 HTTPS | **Caddy** | 零配置证书 |
| 自研边缘代理、内存安全优先级高 | **Pingora** | Rust 框架，Cloudflare 同源 |
| API 网关（认证/插件生态） | [Kong](/docs/CS/CN/nginx/Kong.md) / APISIX | 都基于 OpenResty，插件即 Lua |
| K8s 入口（原 ingress-nginx 用户） | **Traefik 3.7** 或直接 Gateway API | 注解兼容 + WAF 平迁，迁移成本最低 |
| LLM/AI 流量治理 | Traefik Hub / APISIX 3.18 / Kong AI Gateway / **Higress** | 按 token 限流、SSE 流式、协议转换；Higress 把 AI 流量做一等公民 |
| 阿里微服务体系 / Spring Cloud Alibaba 栈 | **Higress** | 与 Nacos / Dubbo / Sentinel 原生集成，三网关合一，性能高于 Java 网关 2 倍+ |
| 既要 K8s Ingress 又要 AI 网关 + 微服务网关 | **Higress** | Envoy 内核高性能 + Wasm 插件热更新 + AI 流量原生支持 |

迁移相关：K8s 社区的 ingress-nginx 已于 2026-03 退役，Ingress 场景的迁移方向见 [Practice 的 Kubernetes 一节](/docs/CS/CN/nginx/practice.md?id=kubernetes：ingress-nginx-已退役)。

## Links

- [nginx](/docs/CS/CN/nginx/nginx.md) — 本文 nginx 侧事实的出处
- [Event](/docs/CS/CN/nginx/event.md) — 惊群问题在不同代理里的解法对照
- [OpenResty](/docs/CS/CN/nginx/OpenResty.md) — nginx 可编程化的路线
- [Kong](/docs/CS/CN/nginx/Kong.md) — nginx 生态的网关形态
- [Practice](/docs/CS/CN/nginx/practice.md) — ingress-nginx 退役后的迁移路径
- [Load Balance](/docs/CS/CN/Load%20Balance.md) — 负载均衡通用概念
- [Higress](/docs/CS/Framework/Higress/Higress.md) — 阿里开源、Envoy 内核的云原生 API 网关

## References

- <https://nginx.org/en/>
- <https://www.haproxy.org/>
- <https://www.envoyproxy.io/>
- <https://caddyserver.com/>
- <https://github.com/cloudflare/pingora>
- <https://doc.traefik.io/traefik/>
- <https://apisix.apache.org/>
- <https://docs.konghq.com/gateway/>
- <https://gateway-api.sigs.k8s.io/>
- <https://higress.io/> — Higress 官网
- <https://github.com/alibaba/higress> — Higress 源码
