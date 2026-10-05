## Introduction

**客户端负载均衡**：每个调用方自己持有服务实例列表，并在本地完成选实例的动作——与集中式网关 / 服务端 LB 相对。它的好处是少一跳网络、无单点；代价是选型策略库要被每个客户端依赖引入。

Spring Cloud LoadBalancer（SCL）是 [Ribbon](/docs/CS/Framework/Spring_Cloud/Ribbon.md) 的替代品，从 Spring Cloud 2020.0 起成为官方默认。它建立在 Reactor 之上，契约接口是 `ReactiveLoadBalancer`：

```java
public interface ReactiveLoadBalancer<T> {

	Publisher<Response<T>> choose(Request request);

	// 顺序保证交由实现决定，调用方不该假设轮询
}
```

面向服务实例的 Reactor 实现体接口为 `ReactorServiceInstanceLoadBalancer`，内置的算法类都实现它。

> [!NOTE]
> Spring Cloud LoadBalancer 5.0（2025.1 Oakwood）新增两项能力：支持**按 API 版本**选择实例（与 Framework 7 的 API 版本化打通），以及为 **Spring HTTP Interface Client** 提供自动配置——声明式接口客户端同样自动享受负载均衡，不必再手工包装。

## 内置算法

| 实现 | 行为 |
| :-- | :-- |
| `RoundRobinLoadBalancer` | **默认**。内部保存一个 `AtomicInteger` position，按次序循环取模挑选。无需额外状态，适合实例规格一致的场景 |
| `RandomLoadBalancer` | 在实例列表里随机挑一台。实例数多时分布与轮询接近，但不保证均匀 |
| `WeightedServiceInstanceListSupplier` | 严格说不是算法而是前置筛选：按元数据 `weight` 决定权重分布（`configurations=weighted`） |

切换算法即替换 Bean：

```java
// 注意：这个类不要标 @Configuration，也不要落在组件扫描路径里
public class CustomLoadBalancerConfiguration {

	@Bean
	ReactorLoadBalancer<ServiceInstance> randomLoadBalancer(Environment env,
			LoadBalancerClientFactory factory) {
		String name = env.getProperty(LoadBalancerClientFactory.PROPERTY_NAME);
		return new RandomLoadBalancer(
				factory.getLazyProvider(name, ServiceInstanceListSupplier.class), name);
	}
}
```

> [!WARNING]
> 上面这个"不要标 `@Configuration`、要放在组件扫描之外"的要求**不是风格而是机制**：`LoadBalancerClientFactory` 为每个 serviceId 建独立子上下文，配置类若被主上下文扫到就会变成全局配置，所有服务的负载均衡策略串在一起。这是 SCL 最常见的踩坑点，症状是"明明只配了 A 服务，B 服务的策略也变了"。

## ServiceInstanceListSupplier

**实例从哪里来**（supplier）与**怎么选**（load balancer）是两个正交的关注点。SCL 用一层套一层的 `ServiceInstanceListSupplier` 装饰器表达前者：

```java
ServiceInstanceListSupplier.builder()
        .withDiscoveryClient()     // 从注册中心拉
        .withCaching()             // 加缓存
        .withHealthChecks()        // 按健康状态过滤
        .build(context);
```

### 各层职责

| Supplier | 职责 | builder 方法 |
| :-- | :-- | :-- |
| `DiscoveryClientServiceInstanceListSupplier` | 从 classpath 上的 `DiscoveryClient` 拉取实例 | `.withDiscoveryClient()` |
| `StaticServiceInstanceListSupplier` | 不经注册中心，用静态列表（`spring.cloud.discovery.client.simple.instances`） | — |
| `CachingServiceInstanceListSupplier` | 缓存上层结果，classpath 有 Caffeine 则用它，否则 `DefaultLoadBalancerCache` | `.withCaching()` |
| `HealthCheckServiceInstanceListSupplier` | 定时探活，只返回健康实例；**全部不健康时返回全部** | `.withHealthChecks()` / `.withBlockingHealthChecks()` |
| `ZonePreferenceServiceInstanceListSupplier` | 优先同 zone 实例；本 zone 无实例则退回全部 | `.withZonePreference()` |
| `WeightedServiceInstanceListSupplier` | 按元数据 `weight` 加权 | `.withWeighted()` |
| `SubsetServiceInstanceListSupplier` | 每个客户端只看固定子集，避免大规模集群下所有客户端缓存全量实例 | `.withSubset()` |
| `HintBasedServiceInstanceListSupplier` | 按请求方 hint（`X-SC-LB-Hint` 头 / 元数据）选实例 | `.withHints()` |
| `SameInstancePreferenceServiceInstanceListSupplier` | 优先复用上次选中的实例（Zookeeper `StickyRule` 的替代品） | `.withSameInstancePreference()` |
| `RequestBasedStickySessionServiceInstanceListSupplier` | 按 cookie（`sc-lb-instance-id`）粘到固定实例 | `.withRequestBasedStickySession()` |

### 顺序有讲究

> [!WARNING]
> `withCaching()` **必须紧跟在从网络取实例的那一层之后、任何过滤层之前**。写反的后果是"缓存的是已过滤后的结果"：zone 变化、健康状态变化都无法反映到缓存里，且 TTL 到期前一直错下去——同样是不报错只失效的一类问题。

另外一个容易重复的点：`HealthCheckServiceInstanceListSupplier` 自身基于 Reactor `Flux#replay()` 做了缓存，套了它之后**不必再套 `withCaching()`**。

不想写 Bean 时，用属性直接选预置组合：

```yaml
spring:
  cloud:
    loadbalancer:
      configurations: health-check   # weighted / zone-preference / same-instance-preference
                                     # request-based-sticky-session / subset / api-version
```

### Zone 感知的两个坑

1. **zone 来源**：客户端侧 zone 由各 `DiscoveryClient` 的特定配置决定（如 Eureka 是 `eureka.instance.metadata-map.zone`）。目前**只有 Eureka 会自动把 zone 传给 LoadBalancer**，[Consul](/docs/CS/Framework/Spring_Cloud/Consul.md)、[Nacos](/docs/CS/Framework/nacos/Nacos.md) 等需要手工设置 `spring.cloud.loadbalancer.zone`。不设的话 zone 为 null，该 supplier 直接返回全部实例——**配了 `zone-preference` 却毫无效果是常见现象**。
2. **实例侧 zone** 取自 `ServiceInstance` 元数据里 key 为 `zone` 的值，注册时要把 zone 写进 tags / metadata。

## 按服务定制

```java
@Configuration
@LoadBalancerClient(value = "store-service", configuration = StoreLoadBalancerConfig.class)
public class MyConfiguration {

	@Bean
	@LoadBalanced
	WebClient.Builder loadBalancedWebClientBuilder() {
		return WebClient.builder();
	}
}
```

`LoadBalancerClientFactory` 为每个 serviceId 创建**独立的 Spring 子上下文**（默认懒加载，首次请求时初始化）。可用 `spring.cloud.loadbalancer.eager-load.clients` 预加载以避免首请求慢。

单客户端属性覆盖写在 `spring.cloud.loadbalancer.clients.<clientId>.*` 下，client 级优先于全局；但以下四项**只能全局设置**，不提供反向覆盖：

- `spring.cloud.loadbalancer.enabled`
- `spring.cloud.loadbalancer.retry.enabled`
- `spring.cloud.loadbalancer.cache.enabled`
- `spring.cloud.loadbalancer.stats.micrometer.enabled`

> [!TIP]
> AOT / GraalVM 原生镜像自 4.0.0 起支持，但**必须显式声明 serviceId**（通过 `@LoadBalancerClient` 的 `value`/`name`，或 `eager-load.clients`）。原生镜像跑不通动态创建子上下文，没有显式声明就会出现"运行时报找不到 LoadBalancer client"。

## 自定义策略：金丝雀路由

下面是一个完整的自定义实现——按请求 Header 里的流量标记把测试流量导向金丝雀节点（示例中其他部分省略，重点在 `choose` 与 `getInstanceResponse` 两段）：

```java
@Slf4j
public class CanaryRule implements ReactorServiceInstanceLoadBalancer {

	private final ObjectProvider<ServiceInstanceListSupplier> serviceInstanceListSupplierProvider;
	private final String serviceId;
	private final AtomicInteger position = new AtomicInteger(0);

	@Override
	public Mono<Response<ServiceInstance>> choose(Request request) {
		ServiceInstanceListSupplier supplier = serviceInstanceListSupplierProvider
				.getIfAvailable(NoopServiceInstanceListSupplier::new);
		return supplier.get(request).next()
				.map(instances -> getInstanceResponse(request, instances));
	}

	private Response<ServiceInstance> getInstanceResponse(Request request,
			List<ServiceInstance> instances) {
		if (CollectionUtils.isEmpty(instances)) {
			log.warn("No instance available for {}", serviceId);
			return new EmptyResponse();
		}

		// 从 WebClient 请求的 Header 中取流量标记
		DefaultRequestContext context = (DefaultRequestContext) request.getContext();
		RequestData requestData = (RequestData) context.getClientRequest();
		HttpHeaders headers = requestData.getHeaders();
		String trafficVersion = headers.getFirst(TRAFFIC_VERSION);

		List<ServiceInstance> candidates;
		if (StringUtils.isBlank(trafficVersion)) {
			// 正式流量：剔除所有带流量标记的金丝雀节点
			candidates = instances.stream()
					.filter(e -> !e.getMetadata().containsKey(TRAFFIC_VERSION))
					.collect(Collectors.toList());
		} else {
			// 测试流量：只保留元数据标记匹配的节点
			candidates = instances.stream()
					.filter(e -> StringUtils.equalsIgnoreCase(
							e.getMetadata().get(TRAFFIC_VERSION), trafficVersion))
					.collect(Collectors.toList());
		}
		return getRoundRobinInstance(candidates);
	}

	private Response<ServiceInstance> getRoundRobinInstance(List<ServiceInstance> instances) {
		if (instances.isEmpty()) {
			log.warn("No servers available for service: {}", serviceId);
			return new EmptyResponse();
		}
		int pos = Math.abs(this.position.incrementAndGet());
		return new DefaultResponse(instances.get(pos % instances.size()));
	}
}
```

两点值得留意：

- **这套 `RequestData` 取 Header 的写法只对 WebClient 有效**。`RestTemplate` 走的是 `HttpRequest` 上下文，Feign / `RestClient` 又是另一套，需要各自适配。这也是"WebClient 上调通了、别处不生效"的原因。
- 空列表必须返回 `EmptyResponse` 而不是抛异常——异常会让上层重试逻辑误判为调用失败。

## 可观测性

```yaml
spring:
  cloud:
    loadbalancer:
      stats:
        micrometer:
          enabled: true    # 暴露 loadbalancer.requests 等指标
```

产生的指标可与 Micrometer Tracing 联动，在一次链路里看到"选了哪个实例、花了多久"。

若调用链涉及重试，链路能否连贯取决于是否使用框架自动装配的客户端 Builder（参见 [链路追踪](/docs/CS/Framework/Spring_Cloud/Sleuth.md)）。

## Links

- [Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md)
- [Ribbon](/docs/CS/Framework/Spring_Cloud/Ribbon.md)
- [Spring Cloud OpenFeign](/docs/CS/Framework/Spring_Cloud/Feign.md)
- [Consul](/docs/CS/Framework/Spring_Cloud/Consul.md)
- [Nacos](/docs/CS/Framework/nacos/Nacos.md)

## References

1. [Spring Cloud Commons - LoadBalancer Reference](https://docs.spring.io/spring-cloud-commons/reference/spring-cloud-commons/loadbalancer.html)
2. [Spring Cloud LoadBalancer Reference](https://docs.spring.io/spring-cloud-loadbalancer/reference/)
