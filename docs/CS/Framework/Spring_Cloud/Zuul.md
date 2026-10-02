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

由于 Zuul 1 的阻塞模型在高并发长连接下的局限，以及 Netflix 进入维护模式，Spring 官方在 Spring Cloud Gateway 中用 `Route + Predicate + Filter` 的响应式模型（Reactor + Netty）取代了它，并提供更好的异步、背压与可扩展性。新项目应选 Gateway，Zuul 主要出现在存量 Spring Cloud Netflix 系统中。

## Links

- [Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md)
- [Spring Cloud Gateway](/docs/CS/Framework/Spring_Cloud/gateway.md)
- [Hystrix](/docs/CS/Framework/Spring_Cloud/Hystrix.md)
- [Ribbon](/docs/CS/Framework/Spring_Cloud/Ribbon.md)
- [Eureka](/docs/CS/Framework/eureka/Eureka.md)

## References

1. [Netflix Zuul Wiki](https://github.com/Netflix/zuul/wiki)
2. [Spring Cloud Netflix - Zuul (legacy reference archive)](https://docs.spring.io/spring-cloud-netflix/docs/2.2.x/reference/html/#router-and-filter-zuul)
3. [Zuul 2 announcement](https://netflixtechblog.com/zuul-2-the-netflix-journey-to-asynchronous-non-blocking-systems-45947377fb5c)
