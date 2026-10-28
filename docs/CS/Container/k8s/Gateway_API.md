## Introduction

[Ingress](/docs/CS/Container/k8s/Ingress.md) 把七层路由抽象成了一个 API 对象，但它有两个结构性缺陷：**配置表达力靠 annotation 无限膨胀**（每个 Controller 自己一套，不可移植），以及**基础设施路由与应用路由混在同一个对象里**（平台团队与应用团队抢同一个 YAML）。Gateway API 是 Kubernetes SIG Network 给出的官方继任者：它不定义"哪个控制器怎么实现"，只定义一套**可移植的路由 API**，把角色、协议、匹配语义全部标准化，控制器降级成背后的实现细节。

> [!IMPORTANT]
> **版本基线：Gateway API v1.6.3**（2026-10-06 发布，v1.7.0 尚处 RC）。本篇的 GA / 实验通道划分以 v1.6 为准；具体字段的支持级别以官方 spec 与 release notes 现场核对。

## Three Resources, Three Roles

Gateway API 的核心设计是**按组织角色拆资源**，四个 CRD 各归其主：

| 资源 | 属主 | 决定什么 |
| :--- | :--- | :--- |
| `GatewayClass` | 集群运维 | 用哪个控制器实现（类比 StorageClass 与 provisioner） |
| `Gateway` | 平台团队 | 监听哪些端口 / 协议 / 主机名，TLS 证书，允许哪些命名空间的 Route 挂入（`allowedRoutes`） |
| `Route`（HTTPRoute 等） | 应用团队 | 匹配规则与后端权重，只写自己命名空间内的路由 |
| `ReferenceGrant` | 后端命名空间属主 | 显式授权别的命名空间把流量引到自己这里的 Service |

一次请求的生效链路是：`Gateway` 声明监听 → `Route` 通过 `parentRefs` 挂到 Gateway → 匹配 `rules` → 按 `backendRefs` 转发。角色分离的直接收益是**权限可以真拆开**：给开发者开 HTTPRoute 的创建权限，把 Gateway/GatewayClass 锁给平台团队，多团队集群里互不踩脚。Ingress 时代这靠"约定谁改哪个文件"维持，Gateway API 把它变成了 API 语义。

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: shared-gw
  namespace: infra
spec:
  gatewayClassName: istio            # 或 envoy / cilium / nginx 等实现
  listeners:
    - name: https
      protocol: HTTPS
      port: 443
      hostname: "*.example.com"
      tls:
        mode: Terminate
        certificateRefs: [{ name: wildcard-tls }]
      allowedRoutes:
        namespaces:
          from: Selector
          selector: { matchLabels: { gw-access: "true" } }
```

## Route Types and What Is GA

Gateway API 每版发布**两套 CRD 通道**：`standard`（GA/Beta，承诺稳定，生产可用）与 `experimental`（alpha，允许破坏性变更，manifest 要锁版本）。自 v1.3 起实验资源统一使用 `X` 前缀并归入独立的 `gateway.networking.x-k8s.io` API 组，v1.6 进一步把实验面整体迁入该组——**标准与实验的边界一目了然，晋升到标准通道时需以标准名重建资源**。

按 v1.6 的口径，标准通道里的 GA 资源随版本逐步扩大：

- **v1.0.0**（2023-10）：`Gateway` / `GatewayClass` / `HTTPRoute` GA——核心类型落地即 GA，这是它区别于多数 K8s 子项目的地方；
- **v1.1.0**（2024-05）：`GRPCRoute` GA（按 service/method 匹配，gRPC 原生路由），**GAMMA**（Gateway API for Mesh Management，同一套 API 管网格内东西向流量）进入标准通道；
- **v1.2.0**（2024-11）：HTTPRoute `timeouts` GA；
- **v1.3.0**（2025-04）：按百分比 `RequestMirror` GA；实验面开始 X 前缀化；
- **v1.4.0**（2025-10）：`BackendTLSPolicy` GA、**named rules** GA、`supportedFeatures` 进入 GatewayClass status；
- **v1.5.0**（2026-02）：`TLSRoute` 与 `XListenerSet`（ListenerSet）GA；
- **v1.6.0**（2026-06）：`TCPRoute` / `UDPRoute` GA，四层补齐；`BackendTLSPolicy` 可用于全部路由类型。

仍在实验通道的：Mesh 高级形态、`CORS`、`externalAuth` filter、`XBackendTrafficPolicy`、会话保持（session persistence）、重试预算等。安装时**只装其中一套**，混装不被支持；且 CRD 版本必须与控制器版本匹配，否则遇到不认识的字段直接 schema 报错。

```bash
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.6.3/standard-install.yaml
# 验证装的是哪一版
kubectl get crd gateways.gateway.networking.k8s.io \
  -o jsonpath='{.metadata.annotations.gateway\.networking\.k8s\.io/bundle-version}'
```

## HTTPRoute Mechanics Worth Knowing

`HTTPRoute` 是日常写得最多的资源，几个决定行为的字段：

- **`matches`**：`path`（`Exact` / `PathPrefix` / `RegularExpression`）、`header`、`method`、`query`。原生支持 header 匹配是 Ingress 时代的 annotation 重灾区，这里是一等公民。
- **`backendRefs[].weight`**：流量切分。整数，默认 1；**weight 0 保留引用但不分流量**——这正是"切流 0% 但不摘掉引用"的标准写法。
- **`filters`**：请求/响应处理链。`URLRewrite`、`RequestRedirect`、`RequestMirror`（按百分比镜像）、header 增删改。注意 `URLRewrite` 与 `RequestRedirect` 在同一 filter 链里**互斥**，控制器会直接拒绝。
- **`timeouts`**：`timeouts.request` 是客户端到响应的总预算，`timeouts.backendRequest` 是单次后端尝试预算，后者必须 ≤ 前者。
- **named rules（v1.4 起 GA）**：给 rule 起名，status 回报就能指出"这条请求归哪条 rule 管"。重叠前缀静默 fall through 是 Gateway API 最常见的排障痛点，named rules 是官方给出的解法。

一条必须记住的匹配语义：**每个请求只命中一条 rule**，重叠时走特异性最高的那条，其余静默不生效——没有"多规则累加"这回事。

## Common Gotchas

1. **Route 默认只认同命名空间。** Gateway 在 `infra`、HTTPRoute 在 `apps` 时，挂载静默失败，直到 `allowedRoutes.namespaces.from: All`（或 label selector）显式放行。排障先看 `status.parents[].conditions[type=Accepted]`，不要 `kubectl apply` 完就假定生效。
2. **跨命名空间后端要 ReferenceGrant。** 没有它，route 被接受但后端解析失败，表现为 500——错误发生在数据面而不是 API 面，最难查的一种。
3. **重叠规则只命中一条**（见上），灰度切分确认权重是否落在同一条 rule 的多个 backend 上，而不是分成两条 rule。
4. **CRD 与控制器的版本要匹配。** 用 v1.4 的 CRD 配只懂 v1.2 的控制器，遇到新字段直接 schema 错误。
5. **镜像与切分是两种语义。** `RequestMirror` 是 fire-and-forget 的旁路拷贝，不占 backendRefs 权重；灰度用 weight，流量复制用 mirror，别混。

## Implementations

Gateway API 只定 API，实现由各网关项目提供，选型时看官方 conformance 报告（实现方跑通过控测试并提交结果）：

| 实现 | 背景 | 适用 |
| :--- | :--- | :--- |
| Istio | 服务网格，ingress gateway + sidecar 双形态 | 已上网格，东西向 + 南北向统一 API |
| Envoy Gateway | Envoy 官方项目，Gateway API 原生构建 | 纯南北向，Envoy 数据面 |
| NGINX Gateway Fabric | ingress-nginx 的继任者 | 从 ingress-nginx 迁移 |
| Cilium | eBPF 数据面 | 网络与网关一体 |
| Kong / Traefik / Higress | API 网关系 | 插件、AI 网关等增值能力 |
| 云厂商控制器（ALB / GKE 等） | 托管 LB 直配 | 不想自己运维数据面 |

两个与生态有关的现状值得知道：**ingress-nginx 已于 2026-03 终止维护**（仓库只读），官方迁移方向就是 Gateway API，NGINX Gateway Fabric 是其替代实现；Higress、Traefik、APISIX 等均已提供 Gateway API 支持，细节见 [Istio 网关生态](/docs/CS/Framework/Istio/Envoy.md) 与 [Higress](/docs/CS/Framework/Higress/Higress.md)。本站对网关数据面实现（Envoy 配置、插件、AI 网关）的展开在那些专页，本页只讲 API 本身。

## Links

- [Ingress：七层路由的旧模型](/docs/CS/Container/k8s/Ingress.md)
- [K8s 总纲](/docs/CS/Container/k8s/K8s.md)
- [Service 与 kube-proxy：四层基座](/docs/CS/Container/k8s/Service.md)
- [Istio：服务网格与网关](/docs/CS/Framework/Istio/Istio.md)
- [Higress：AI 网关](/docs/CS/Framework/Higress/Higress.md)

## References

1. [Gateway API 官方站点](https://gateway-api.sigs.k8s.io/)
2. [kubernetes-sigs/gateway-api Releases](https://github.com/kubernetes-sigs/gateway-api/releases)
3. [Gateway API Conformance Reports](https://gateway-api.sigs.k8s.io/concepts/conformance/)
4. [GEP：Gateway Enhancement Proposal 流程](https://gateway-api.sigs.k8s.io/geps/)
