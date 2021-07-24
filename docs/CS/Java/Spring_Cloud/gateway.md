## gateway vs Zuul



|       | Zuul | Gateway                            |
| ----- | ---- | ---------------------------------- |
| basic |      | webflux, only support spring cloud |
|       |      |                                    |
|       |      |                                    |




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


LoadBalancerClientFilter

DispatcherHandler



### RoutePredicate



RoutePredicateHandlerMapping#lookupRoute()



