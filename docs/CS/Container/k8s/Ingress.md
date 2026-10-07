## Introduction

[Service](/docs/CS/Container/k8s/Service.md) 解决的是集群内服务发现与**四层**流量转发，但它有个硬伤：**只认 IP + 端口，不懂域名、URI 路径、Host 头**。当多个业务共用集群、需要按域名路由、统一 HTTPS 证书、统一限流、灰度发布时，单纯用 LoadBalancer/NodePort 就很笨重——这就是 Ingress 要解决的问题。

Ingress 把七层（HTTP/HTTPS）路由规则抽象成一个 K8s API 对象：

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: web-ingress
spec:
  ingressClassName: nginx
  tls:
  - hosts: [example.com]
    secretName: example-tls          # TLS 证书放在 Secret 中
  rules:
  - host: api.example.com
    http:
      paths:
      - path: /users
        pathType: Prefix
        backend:
          service:
            name: user-service
            port: { number: 80 }
      - path: /orders
        pathType: Prefix
        backend:
          service:
            name: order-service
            port: { number: 80 }
```

## Why Ingress Is Needed

先看纯 Service 对外暴露的原生方案——**每个业务单独创建一个 LoadBalancer Service**：

```
user-service  → LoadBalancer → 公网IP1:80
order-service → LoadBalancer → 公网IP2:80
pay-service   → LoadBalancer → 公网IP3:80
```

三个问题：

1. **成本昂贵**：微服务一多就是十几个公网 IP、十几个 SLB 实例，云厂商按实例/带宽计费，成本直接翻倍；
2. **证书与策略分散**：每个 LB 单独配 HTTPS 证书、限流、安全策略，证书过期要改 N 次，极易漏配；
3. **缺少 HTTP 语义**：四层转发读不到 Host 域名和 URI 路径，做不到 `api.example.com/users` 与 `/orders` 的分流。

引入 Ingress 后收敛为**单入口**：

```
1 个 LoadBalancer → Ingress Controller（Nginx/Traefik）
        ├─ api.example.com/users  → user-service
        ├─ api.example.com/orders → order-service
        └─ api.example.com/pay    → pay-service
```

只需 1 个云 LB、1 个公网 IP 收敛所有 HTTP 流量，域名、证书、限流、跨域、灰度、日志都在网关层统一管理。

## Ingress ≠ Ingress Controller

这是最容易混淆的一点：**Ingress 资源本身只是一份声明式路由表，不会做任何流量转发**。真正干活的是 Ingress Controller——一个反向代理守护进程，它 watch Ingress/Service/EndpointSlice 对象，把规则翻译成自身的配置并热加载：

| Controller | 数据面 | 特点 |
|-----------|--------|------|
| ingress-nginx | Nginx / OpenResty | 事实标准，Lua 动态配置 |
| Traefik | 自研 Go 代理 | 云原生友好，配置简单 |
| APISIX / Kong | OpenResty / Nginx | 插件生态丰富，偏 API 网关定位 |
| Envoy 系（Istio IngressGateway、Contour、Emissary） | Envoy | 与服务网格衔接，支持 L7 高级能力 |
| 云厂商 ALB/SLB Controller | 云 LB | 直接把规则下发到云负载均衡 |

没有安装 Controller 的集群里创建 Ingress，会一直处于无 `ADDRESS` 的空转状态。

## Path Matching: pathType

`pathType` 决定路径如何匹配，生产中最容易踩坑的字段之一：

| 取值 | 语义 | 例子 |
|------|------|------|
| `Prefix` | 按 `/` 分段的**元素级前缀**匹配 | `/user` 命中 `/user`、`/user/`、`/user/list`，**不命中** `/userabc` |
| `Exact` | 完全精确匹配（含大小写） | `/user` 命中 `/user`，不命中 `/user/`、`/user/list` |
| `ImplementationSpecific` | 由 Controller 自行实现 | 行为不可移植，**不推荐生产使用** |

易错点在于 `Prefix` 不是"纯字符串前缀"：官方语义要求按路径元素（segment）边界匹配，所以 `/user` 不会误命中 `/userabc`。但部分 Controller（尤其 ingress-nginx 早期版本）在 `ImplementationSpecific` 下退化为字符串前缀匹配，曾导致 `/user` 意外命中 `/userabc` 而串流量——统一显式声明 `pathType: Prefix` 是规避该问题的标准做法。

## Traffic Path

以 ingress-nginx 为例（NodePort 暴露方式）：

```
Client → Node:NodePort → ingress-nginx Pod (Nginx) → Service → Pod
                                ↑
                     watch Ingress 生成 nginx.conf 并热加载
```

生产环境通常在 Controller 前面还有一个云 LB 或四层 LB 挂公网 IP；用 `LoadBalancer` 类型的 Service 暴露 ingress-nginx 是最省心的组合。

## Canary Release

Ingress 的另一大价值是**灰度发布**：先切一小部分真实流量到新版本，观测错误率、延迟、CPU，没问题再逐步放大，异常立刻切回老版本。对比"直接全量发布"——一旦有 bug 就是 **100% 用户受影响**，金丝雀只把 5%/10% 流量交给新版本，故障影响面极小。

> 名字来源：早年矿工带金丝雀下矿井，金丝雀对毒气更敏感，中毒先预警，从而保护矿工。

### Strategy A: Split Traffic by Weight (Most Common)

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: api-canary-ingress
  annotations:
    nginx.ingress.kubernetes.io/canary: "true"
    nginx.ingress.kubernetes.io/canary-weight: "10"   # 10% 流量到新版本
spec:
  rules:
  - host: api.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: new-api-svc        # 新版本 Service
            port: { number: 80 }
```

按随机比例切流量，必须与新版本的 Service/Deployment 一起部署；调整 `canary-weight` 数值即可逐级放量（10 → 30 → 50 → 100）。

### Strategy B: Targeted Split by Header/Cookie

```yaml
metadata:
  annotations:
    nginx.ingress.kubernetes.io/canary: "true"
    nginx.ingress.kubernetes.io/canary-by-header: "X-Canary"
    nginx.ingress.kubernetes.io/canary-by-header-value: "test"
```

联调测试时请求带上 `X-Canary: test` 就走新版本，普通用户继续走老版本，**完全不影响真实客户**。另有 `canary-by-cookie` 按 Cookie 分流，适合按用户维度灰度。

金丝雀与 [Deployment 滚动更新](/docs/CS/Container/k8s/K8s.md)解决的不是同一个问题：滚动更新是**替换**（新版本最终会全量接管），金丝雀是**分流验证**（可长期停在某个比例，也可随时回滚）。

## Relationship with Service / Gateway API

| 组件 | 层级 | 能力 | 适合场景 |
|------|------|------|---------|
| Service (ClusterIP) | 四层 | 服务发现、TCP 负载 | 集群内微服务互调 |
| Service (LoadBalancer) | 四层 | 公网 TCP 入口 | 非 HTTP 业务（MySQL、TCP 长连接） |
| Ingress | 七层 HTTP/HTTPS | 域名、路径、证书、限流、灰度 | Web、API、前端公网业务 |

- Gateway API 是 Ingress 的下一代标准：把"谁配路由（HTTPRoute）"与"谁来承载（Gateway）"解耦，支持角色分离，正逐步取代 Ingress API 的新需求场景。当前稳定版为 **v1.6.2**（2026-09），其中 Gateway / GatewayClass / HTTPRoute 已在 v1.0.0 获得 GA 的 v1 API，GAMMA（服务网格支持）自 v1.1.0 起进入标准通道。Gateway API CRD 需自行单独安装，不由任何网格或网关项目代管。
- ingress-nginx 已于 **2026-03 终止维护**（仓库转只读，已有部署不被破坏），迁移方向是 Gateway API。各网关实现的迁移成本与状态见 [Istio](/docs/CS/Framework/Istio/Envoy.md) 的网关生态横评；`Higress`、`Traefik`、`APISIX` 等实现均已提供 Gateway API 支持。

## Links

- [K8s](/docs/CS/Container/k8s/K8s.md)
- [Service](/docs/CS/Container/k8s/Service.md)
- [kube-proxy](/docs/CS/Container/k8s/kube-proxy.md)
- [K8s 网络](/docs/CS/Container/k8s/net.md)
- [Scaling](/docs/CS/Container/k8s/Scaling.md)
- [Nginx](/docs/CS/CN/nginx/nginx.md)

## References

1. [Ingress Controllers - Kubernetes Docs](https://kubernetes.io/docs/concepts/services-networking/ingress-controllers/)
1. [8 K8s 流量网关 —— Ingress：域名路由](https://mp.weixin.qq.com/s/UeJc6En__g9yRg3nTorcSQ)
