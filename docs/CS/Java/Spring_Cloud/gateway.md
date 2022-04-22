## Introduction



|       | Zuul | Gateway                            |
| ----- | ---- | ---------------------------------- |
| basic |      | webflux, only support spring cloud |
|       |      |                                    |
|       |      |                                    |


### How it works

> See [How It Works](https://cloud.spring.io/spring-cloud-static/spring-cloud-gateway/2.2.2.RELEASE/reference/html/#gateway-how-it-works)

![Spring Cloud Gateway works](https://cloud.spring.io/spring-cloud-static/spring-cloud-gateway/2.2.2.RELEASE/reference/html/images/spring_cloud_gateway_diagram.png)

## AutoConfiguration

GatewayAutoConfiguration

```java

@Configuration(
    proxyBeanMethods = false
)
@ConditionalOnProperty(
    name = {"spring.cloud.gateway.enabled"},
    matchIfMissing = true
)
@EnableConfigurationProperties
@AutoConfigureBefore({HttpHandlerAutoConfiguration.class, WebFluxAutoConfiguration.class})
@AutoConfigureAfter({GatewayLoadBalancerClientAutoConfiguration.class, GatewayClassPathWarningAutoConfiguration.class})
@ConditionalOnClass({DispatcherHandler.class})
public class GatewayAutoConfiguration {
    public GatewayAutoConfiguration() {
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

See [Webflux Handle](/docs/CS/Java/Spring/webflux.md?id=handle)

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


## Links

- [Spring Cloud](/docs/CS/Java/Spring_Cloud/Spring_Cloud.md?id=gateway)
- [Spring Webflux](/docs/CS/Java/Spring/webflux.md)