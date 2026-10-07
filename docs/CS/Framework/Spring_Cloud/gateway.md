## Introduction

Spring Cloud Gateway 是 Spring Cloud 的 API 网关实现，定位是 Netflix Zuul 的替代品：

| | Zuul 1 | Spring Cloud Gateway |
| :-- | :-- | :-- |
| IO 模型 | 同步阻塞（Servlet，一请求一线程） | 响应式（WebFlux + Netty）或 Servlet 两种 |
| 集成范围 | Spring Cloud Netflix | Spring Cloud 一等公民 |
| 状态 | 自 Spring Cloud 2020.0（Ilford）起从 Netflix 集成中移除 | 现行推荐 |

### Two Flavors of 5.x

Gateway 5.0（Spring Cloud 2025.1 Oakwood / Boot 4）把网关拆成**两个独立实现**，一个应用只能选其一：

| flavor | 运行时 | 路由定义 | starter |
| :-- | :-- | :-- | :-- |
| 响应式（WebFlux） | Netty，事件循环 | YAML `routes:` 或 `RouteLocator` DSL | `spring-cloud-starter-gateway-server-webflux` |
| Servlet（WebMVC） | Tomcat，阻塞模型 | 函数式 `RouterFunction` bean 或 YAML | `spring-cloud-starter-gateway-server-webmvc` |

> [!WARNING]
> 升级到 5.x 时 artifact 名与配置根路径都变了，**照抄旧教程里的 `spring.cloud.gateway.routes` 会静默失效**：
>
> | 旧（3.x / 4.x） | 新（5.x） |
> | :-- | :-- |
> | `spring-cloud-starter-gateway` | `spring-cloud-starter-gateway-server-webflux` |
> | `spring-cloud-starter-gateway-mvc` | `spring-cloud-starter-gateway-server-webmvc` |
> | `spring.cloud.gateway.routes` | `spring.cloud.gateway.server.webflux.routes` |
> | `spring.cloud.gateway.mvc.routes` | `spring.cloud.gateway.server.webmvc.routes` |

### How it works

> See [How It Works](https://cloud.spring.io/spring-cloud-static/spring-cloud-gateway/2.2.2.RELEASE/reference/html/#gateway-how-it-works)

![Spring Cloud Gateway works](https://cloud.spring.io/spring-cloud-static/spring-cloud-gateway/2.2.2.RELEASE/reference/html/images/spring_cloud_gateway_diagram.png)

## AutoConfiguration

Injected Beans will be used in [handle](/docs/CS/Framework/Spring_Cloud/gateway.md?id=handle):

- [RoutePredicateHandlerMapping](/docs/CS/Framework/Spring_Cloud/gateway.md?id=predicate)
- [FilteringWebHandler](/docs/CS/Framework/Spring_Cloud/gateway.md?id=filter)

```java
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(
    name = {"spring.cloud.gateway.enabled"},
    matchIfMissing = true
)
@EnableConfigurationProperties
@AutoConfigureBefore({HttpHandlerAutoConfiguration.class, WebFluxAutoConfiguration.class})
@AutoConfigureAfter({GatewayLoadBalancerClientAutoConfiguration.class, GatewayClassPathWarningAutoConfiguration.class})
@ConditionalOnClass({DispatcherHandler.class})
public class GatewayAutoConfiguration {
    @Bean
    public FilteringWebHandler filteringWebHandler(List<GlobalFilter> globalFilters) {
        return new FilteringWebHandler(globalFilters);
    }

    @Bean
    public RoutePredicateHandlerMapping routePredicateHandlerMapping(
            FilteringWebHandler webHandler, RouteLocator routeLocator,
            GlobalCorsProperties globalCorsProperties, Environment environment) {
        return new RoutePredicateHandlerMapping(webHandler, routeLocator,
                globalCorsProperties, environment);
    }
}
```

```java

@Configuration(
    proxyBeanMethods = false
)
@ConditionalOnClass({LoadBalancerClient.class, RibbonAutoConfiguration.class, DispatcherHandler.class})
@AutoConfigureAfter({RibbonAutoConfiguration.class})
@EnableConfigurationProperties({LoadBalancerProperties.class})
public class GatewayLoadBalancerClientAutoConfiguration {
    public GatewayLoadBalancerClientAutoConfiguration() {
    }

    @Bean
    @ConditionalOnBean({LoadBalancerClient.class})
    @ConditionalOnMissingBean({LoadBalancerClientFilter.class, ReactiveLoadBalancerClientFilter.class})
    @ConditionalOnEnabledGlobalFilter
    public LoadBalancerClientFilter loadBalancerClientFilter(LoadBalancerClient client, LoadBalancerProperties properties) {
        return new LoadBalancerClientFilter(client, properties);
    }
}
```

## handle

See [Webflux Handle](/docs/CS/Framework/Spring/webflux.md?id=handle)

```java
public class RoutePredicateHandlerMapping extends AbstractHandlerMapping {
    @Override
    protected Mono<?> getHandlerInternal(ServerWebExchange exchange) {
        // don't handle requests on management port if set and different than server port
        if (this.managementPortType == DIFFERENT && this.managementPort != null
                && exchange.getRequest().getURI().getPort() == this.managementPort) {
            return Mono.empty();
        }
        exchange.getAttributes().put(GATEWAY_HANDLER_MAPPER_ATTR, getSimpleName());

        return lookupRoute(exchange)
                .flatMap((Function<Route, Mono<?>>) r -> {
                    exchange.getAttributes().remove(GATEWAY_PREDICATE_ROUTE_ATTR);
                    exchange.getAttributes().put(GATEWAY_ROUTE_ATTR, r);
                    return Mono.just(webHandler);
                }).switchIfEmpty(Mono.empty().then(Mono.fromRunnable(() -> {
                    exchange.getAttributes().remove(GATEWAY_PREDICATE_ROUTE_ATTR);
                })));
    }
}
```

#### lookupRoute

```java
public class RoutePredicateHandlerMapping extends AbstractHandlerMapping {
    protected Mono<Route> lookupRoute(ServerWebExchange exchange) {
        return this.routeLocator.getRoutes()
                // individually filter routes so that filterWhen error delaying is not a problem
                .concatMap(route -> Mono.just(route).filterWhen(r -> {
                    // add the current route we are testing
                    exchange.getAttributes().put(GATEWAY_PREDICATE_ROUTE_ATTR, r.getId());
                    return r.getPredicate().apply(exchange);
                })
                        // instead of immediately stopping main flux due to error, log and swallow it
                        .doOnError(e -> logger.error("Error applying predicate for route: " + route.getId(), e))
                        .onErrorResume(e -> Mono.empty()))
                // .defaultIfEmpty() put a static Route not found or .switchIfEmpty().switchIfEmpty(Mono.<Route>empty().log("noroute"))
                .next()
                .map(route -> {
                    validateRoute(route, exchange);
                    return route;
                });
    }
}
```

## Predicate


```java
@FunctionalInterface
public interface RoutePredicateFactory<C> extends ShortcutConfigurable, Configurable<C> {

    String PATTERN_KEY = "pattern";

    // useful for javadsl
    default Predicate<ServerWebExchange> apply(Consumer<C> consumer) {
        C config = newConfig();
        consumer.accept(config);
        beforeApply(config);
        return apply(config);
    }

    default AsyncPredicate<ServerWebExchange> applyAsync(Consumer<C> consumer) {
        C config = newConfig();
        consumer.accept(config);
        beforeApply(config);
        return applyAsync(config);
    }

    default Class<C> getConfigClass() {
        throw new UnsupportedOperationException("getConfigClass() not implemented");
    }

    @Override
    default C newConfig() {
        throw new UnsupportedOperationException("newConfig() not implemented");
    }

    default void beforeApply(C config) {
    }

    Predicate<ServerWebExchange> apply(C config);

    default AsyncPredicate<ServerWebExchange> applyAsync(C config) {
        return toAsyncPredicate(apply(config));
    }

    default String name() {
        return NameUtils.normalizeRoutePredicateName(getClass());
    }
}
```

## Filter

Contract to allow a `WebFilter` to delegate to the next in the chain.

```java
public interface GatewayFilterChain {

	Mono<Void> filter(ServerWebExchange exchange);

}
```

```java
public class FilteringWebHandler implements WebHandler {

    private final List<GatewayFilter> globalFilters;

    @Override
    public Mono<Void> handle(ServerWebExchange exchange) {
        Route route = exchange.getRequiredAttribute(GATEWAY_ROUTE_ATTR);
        List<GatewayFilter> gatewayFilters = route.getFilters();

        List<GatewayFilter> combined = new ArrayList<>(this.globalFilters);
        combined.addAll(gatewayFilters);
        // TODO: needed or cached?
        AnnotationAwareOrderComparator.sort(combined);

        return new DefaultGatewayFilterChain(combined).filter(exchange);
    }

    @Override
    public Mono<Void> filter(ServerWebExchange exchange) {
        return Mono.defer(() -> {
            if (this.index < filters.size()) {
                GatewayFilter filter = filters.get(this.index);
                DefaultGatewayFilterChain chain = new DefaultGatewayFilterChain(this,
                        this.index + 1);
                return filter.filter(exchange, chain);
            }
            else {
                return Mono.empty(); // complete
            }
        });
    }
}
```


## RequestRateLimiter

`RequestRateLimiter` 是内置的限流 GatewayFilter，默认实现是基于 Redis + Lua 脚本的令牌桶（`RedisRateLimiter`），需要引入 `spring-boot-starter-data-redis-reactive`：

```yaml
spring:
  cloud:
    gateway:
      server:
        webflux:
          routes:
            - id: rate_limited
              uri: http://downstream
              filters:
                - name: RequestRateLimiter
                  args:
                    redis-rate-limiter.replenishRate: 10   # 令牌补充速率（个/秒）
                    redis-rate-limiter.burstCapacity: 20   # 桶容量，即允许的突发量
                    key-resolver: "#{@userKeyResolver}"    # 限流维度
```

`key-resolver` 引用容器里的 `KeyResolver` bean，决定"按什么维度限流"——按用户、按 IP、按 API 路径各不相同；`burstCapacity` 设为 0 可直接拒绝全部请求，用于紧急熔断。

## Links

- [Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md?id=api-gateway)
- [Spring Webflux](/docs/CS/Framework/Spring/webflux.md)
- [Spring MVC](/docs/CS/Framework/Spring/MVC.md)
- [统一异常处理](/docs/CS/Framework/Spring/Exception.md)
- [Spring Security](/docs/CS/Framework/Spring/Security.md)
- [Higress](/docs/CS/Framework/Higress/Higress.md)
