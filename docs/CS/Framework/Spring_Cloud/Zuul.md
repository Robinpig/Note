## Introduction

[Zuul](https://github.com/Netflix/zuul) 是 Netflix 开源的 **L7 边缘网关（edge service / API Gateway）**，位于所有外部请求与后端微服务之间，提供动态路由、监控、弹性（限流/熔断）、安全鉴权、灰度、压测注入等横切能力。

Spring Cloud Netflix 曾把 Zuul 1 深度集成为 `@EnableZuulProxy`，但它从 Spring Cloud 2020.0（Ilford）起被移除，官方推荐改用基于 Netty、全异步的 [Spring Cloud Gateway](/docs/CS/Framework/Spring_Cloud/gateway.md)。理解 Zuul 的过滤器模型仍是理解网关模式的基础。

## Zuul 1 vs Zuul 2

| 维度 | Zuul 1 | Zuul 2 |
| ---- | ---- | ---- |
| IO 模型 | 同步阻塞，基于 Servlet，一请求一线程 | 全异步，基于 Netty，事件驱动 |
| 长连接 / 吞吐 | 线程数受连接数制约 | 少量线程扛大量连接，支持 HTTP/2、WebSocket |
| Spring Cloud 集成 | `spring-cloud-netflix-zuul`（已移除） | 官方未深度集成，主推 Gateway |
| 关系 | 早期默认网关 | Netflix 自研演进；Spring 阵营选择了 Gateway |

两者都采用相同的**过滤器链**核心思想，差别主要在 IO 模型。

## Filter Chain

Zuul 的核心是一条按阶段组织的过滤器链，每个过滤器是一个 `ZuulFilter`，由 `FilterProcessor` / ZuulFilter Runner 在请求生命周期对应时机调用。过滤器按类型（`filterType`）分为四类：

- **Pre（pre routing）**：路由到源服务**之前**执行。典型：鉴权、参数校验、限流、埋点、选择路由集群。
- **Routing（routing）**：实际把请求**转发**给源服务的阶段，可使用 Apache HttpClient（Zuul 1）或 Netty（Zuul 2）发送。
- **Post（post routing）**：拿到源服务响应**之后**执行。典型：统一响应头、指标统计、日志、压缩。
- **Error**：上述任意阶段抛异常时执行，用于兜底错误处理与标准化错误响应。

一个请求的生命周期大致是：`pre → routing → post`，中途任意阶段出错都进入 `error`，error 处理完通常还会回到 `post` 输出响应。

自定义过滤器继承 `ZuulFilter`，实现四个方法：

```java
@Component
public class AuthPreFilter extends ZuulFilter {

    @Override
    public String filterType() { return PRE_TYPE; }   // pre / route / post / error

    @Override
    public int filterOrder() { return 0; }            // 同类型内的执行顺序

    @Override
    public boolean shouldFilter() { return true; }    // 是否对当前请求生效

    @Override
    public Object run() {
        RequestContext ctx = RequestContext.getCurrentContext();
        HttpServletRequest req = ctx.getRequest();
        String token = req.getHeader("Authorization");
        if (!isValid(token)) {
            ctx.setSendZuulResponse(false);           // 不再路由
            ctx.setResponseStatusCode(401);
        }
        return null;
    }
}
```

`RequestContext` 基于 `ThreadLocal`（Zuul 1），在同一条过滤器链里共享请求状态、路由目标与响应。

### Built-in Filters

开箱就有的一批过滤器撑起了 Zuul 的默认行为。知道它们的 `type` 与 `order`，自定义过滤器才知道该插在哪个位置：

| Order | Filter | 类型 | 作用 |
| :-- | :-- | :-- | :-- |
| -3 | `ServletDetectionFilter` | pre | 探测请求是否走 Spring DispatcherServlet |
| -2 | `Servlet30WrapperFilter` | pre | 包装请求以适配 Servlet 3.0 的多部分请求 |
| -1 | `FormBodyWrapperFilter` | pre | 包装表单请求体，供下游读取 |
| 1 | `DebugFilter` | pre | 配合 `zuul.debug.request` 打调试信息 |
| 5 | `PreDecorationFilter` | pre | **决定路由目标**：根据路由表算出 serviceId / URL，写入 Context 供 route 阶段使用 |
| 10 | `RibbonRoutingFilter` | route | 走 Ribbon + Hystrix 转发到 serviceId（有注册中心时的默认） |
| 100 | `SimpleHostRoutingFilter` | route | 用 Apache HttpClient 直接转发到 URL（配 `url` 而非 `serviceId` 时） |
| 500 | `SendForwardFilter` | route | 转发到本地 `forward:` 地址 |
| 0 | `SendErrorFilter` | error | 把异常写成 `/error` 响应 |
| 1000 | `SendResponseFilter` | post | 把路由拿到的响应写回客户端 |

于是"我要在鉴权通过后才做XXX"这类需求，pre 过滤器的 order 应该落在 **5 之后**（否则还没算出路由目标）、**10 之前**（否则已经开始转发）。

### @EnableZuulProxy vs @EnableZuulServer

- `@EnableZuulProxy`：完整版，额外装配 Ribbon 路由、`Hystrix` 命令包裹、服务发现集成——绝大多数场景用这个。
- `@EnableZuulServer`：精简版，**不含** Ribbon / Hystrix 那一层，只提供基础路由（适合 Zuul 前面已有 LB 的场景）。

两者配置的差别源于 `@ConditionalOnBean(ZuulProxyMarkerConfiguration.Marker.class)`：Proxy 版标记了一个 marker bean，从而激活 Ribbon 与 Hystrix 相关的自动配置。

## Routing & Integration

Zuul 1 与 Netflix 其他组件天然协作：

- 结合 [Ribbon](/docs/CS/Framework/Spring_Cloud/Ribbon.md) 做客户端负载均衡（按 serviceId 从注册中心选实例）；
- 结合 [Hystrix](/docs/CS/Framework/Spring_Cloud/Hystrix.md) 对路由做熔断降级（每个路由一个 Hystrix command）；
- 结合服务发现（[Eureka](/docs/CS/Framework/eureka/Eureka.md) / [Consul](/docs/CS/Framework/Spring_Cloud/Consul.md)）实现按服务名动态路由。

路由配置示例（遗留风格）：

```yaml
zuul:
  routes:
    users:
      path: /users/**
      serviceId: user-service
```

## Zuul vs Gateway

由于 Zuul 1 的阻塞模型在高并发长连接下的局限，以及 Netflix 进入维护模式，Spring 官方在 [Spring Cloud Gateway](/docs/CS/Framework/Spring_Cloud/gateway.md) 中用 `Route + Predicate + Filter` 的响应式模型（Reactor + Netty）取代了它，并提供更好的异步、背压与可扩展性。新项目应选 Gateway，Zuul 主要出现在存量 Spring Cloud Netflix 系统中。

### 模型对照

| 维度 | Zuul 1 | Spring Cloud Gateway |
| ---- | ---- | ---- |
| IO 模型 | 同步阻塞，Servlet，一请求一线程 | 异步非阻塞，Netty + Reactor |
| 核心抽象 | `ZuulFilter`（pre / route / post / error） | `Route` = `Predicate` + `Filter` 链 |
| 路由粒度 | 路径前缀 → serviceId 或 URL | 谓词组合（Path / Header / Method / Query / Weight…） |
| 过滤器作用域 | 全局；靠 `shouldFilter()` 自行判断 | GlobalFilter（全局）与 GatewayFilter（按路由绑定） |
| 请求上下文 | `RequestContext`（**ThreadLocal**） | `ServerWebExchange`（不依赖线程局部变量） |
| 负载均衡 | 内嵌 Ribbon | [LoadBalancer](/docs/CS/Framework/Spring_Cloud/LoadBalancer.md)，`lb://` scheme |
| 熔断降级 | 内嵌 Hystrix | Resilience4j / CircuitBreaker 抽象 |
| 限流 | 需自行实现 | 内建 `RequestRateLimiter` |

> [!NOTE]
> `RequestContext` 依赖 ThreadLocal 是 Zuul 1 最深的模型约束：它在异步场景（异步 Servlet、自定义线程池、响应式调用）里会**静默丢失上下文**。Gateway 用 `ServerWebExchange` 传递状态，不存在这个问题。这也是 Zuul 没能通过简单改造演进下去、必须重写的原因之一。

### 过滤器迁移映射

| Zuul 写法 | Gateway 对应 |
| ---- | ---- |
| pre filter（鉴权、限流、埋点） | `GlobalFilter` 或按路由的 `GatewayFilter`，用 `Ordered` 控制顺序 |
| route filter（自定义转发逻辑） | 通常**不需要**：`NettyRoutingFilter` 已负责转发，只有非 HTTP 传输才下沉定制 |
| post filter（加响应头、改响应体） | `ModifyResponseBodyGatewayFilterFactory` / `AddResponseHeaderGatewayFilterFactory` |
| error filter | `ErrorWebExceptionHandler`，或用 `ProblemDetail` 统一错误响应 |
| `zuul.routes.<id>.path` / `serviceId` | `spring.cloud.gateway.server.webflux.routes[].predicates: Path=...` + `uri: lb://<serviceId>` |
| `zuul.routes.<id>.url`（直连） | `uri: http://host:port` |

> [!WARNING]
> Gateway 5.x 的配置根路径已改名（`spring.cloud.gateway.server.webflux.routes`），旧前缀**不会报错也不会生效**。把 Zuul 配置迁移过来时若发现路由全部不生效，先查是不是照抄了老教程的前缀。

### Zuul 与 Nginx 的关系

两者常被混为一谈，实则层次不同：**Nginx 是进程外的反向代理 / LB**，走的是传输层—应用层之间的转发；**Zuul 是进程内的边缘服务**，跑在 JVM 里，因此天然能访问 Spring 的上下文（配置、服务发现、认证信息）。典型部署是 Nginx 在最外层扛连接与 TLS，Zuul 在内层做业务相关的横切。Gateway 承接的是 Zuul 的这一层，而不是 Nginx 那一层。

## Links

- [Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md)
- [统一异常处理与 ProblemDetail](/docs/CS/Framework/Spring/Exception.md)
- [Spring MVC](/docs/CS/Framework/Spring/MVC.md)

## References

1. [Netflix Zuul Wiki](https://github.com/Netflix/zuul/wiki)
2. [Spring Cloud Netflix - Zuul (legacy reference archive)](https://docs.spring.io/spring-cloud-netflix/docs/2.2.x/reference/html/#router-and-filter-zuul)
3. [Zuul 2 announcement](https://netflixtechblog.com/zuul-2-the-netflix-journey-to-asynchronous-non-blocking-systems-45947377fb5c)
