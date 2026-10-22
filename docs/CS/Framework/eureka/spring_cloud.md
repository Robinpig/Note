> [!NOTE]
> 源码事实以 spring-cloud/spring-cloud-netflix **main（5.1.0-SNAPSHOT，commit `97b250c`）** 为准；版本矩阵参考 Maven Central 上的 GA 版本。源码既可本地阅读也可在 GitHub 上查：<https://github.com/spring-cloud/spring-cloud-netflix>。

## Introduction

Netflix 的 Eureka 本身只是一个 jar + Jersey 资源类，Spring Cloud Netflix（SCN）负责把它「Spring 化」：把 `PeerAwareInstanceRegistry` 换成 Spring Bean 版本以发布应用事件，把 war 里的 `web.xml` 换成 Servlet 3 的 Filter 注册，把 Archaius 配置换成 relaxed binding 的 `@ConfigurationProperties`。自 Spring Cloud 2020 起，同一仓库里的 Ribbon / Hystrix / Zuul 等模块已陆续移除，**Eureka 是当年整个 Netflix OSS 集成里唯一保留下来的部分**。

## Version Matrix

| Spring Cloud Netflix | 发布日期       | 依赖的 Spring Boot  | 依赖的 Eureka |
| :------------------- | :----------- | :--------------- | :---------- |
| `5.0.3`（最新 GA）      | 2026-10-22   | 4.0.8            | `2.0.6`     |
| `5.0.0`              | 2025-11-24   | 4.0.x            | `2.0.x`     |
| `4.3.3`              | 2026-06-11   | 3.5.13           | `2.0.x`     |
| `4.x` 起              | —            | 3.x              | `2.0.x`（jakarta） |

`spring-cloud-netflix-dependencies/pom.xml` 直接写死 `<eureka.version>2.0.6</eureka.version>`，并同时管理 `eureka-core-jersey3` / `eureka-client-jersey3`。也就是说：**从引入 Spring Boot 3 那一刻起，你用的已经是 jakarta 迁移版的 Eureka**，`javax.ws.rs` 栈的 1.10.x 不会再被拉进来。仓库构建要求 JDK 17。

> [!NOTE]
> 这里再次提醒那个常见的混淆：2.0.x 是 **jakarta 移植**，不是 2015 年宣传的那次重写（后者在 `2.x-archive` 分支），详见 [总纲的版本线一节](/docs/CS/Framework/eureka/Eureka.md?id=版本线与两个-20)。

## Server Side

### @EnableEurekaServer 是纯粹的条件开关

```java
@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
@Documented
@Import(EurekaServerMarkerConfiguration.class)
public @interface EnableEurekaServer {
}
```

它本身不注册任何 Bean，只是导入一个 `Marker` 空类。`EurekaServerAutoConfiguration` 上写着 `@ConditionalOnBean(EurekaServerMarkerConfiguration.Marker.class)`——这样在纯客户端应用里即使 classpath 上有 server jar 也不会误装配。

### EurekaServerAutoConfiguration

关键 Bean：

| Bean                            | 作用                                                                                     |
| :----------------------------- | :------------------------------------------------------------------------------------- |
| `jerseyFilterRegistration`     | 把 Jersey 的 `ServletContainer` 注册成 `FilterRegistrationBean`，`urlPatterns = EurekaConstants.DEFAULT_PREFIX + "/*"`，order `LOWEST_PRECEDENCE`（**这是 `/eureka/` 前缀的来源**） |
| `eurekaVersionFilterRegistration`（order 0） | 把非 `/eureka/v2` 且非静态资源的 URI 重写为 `/eureka/v2/...`，兼容旧路径 |
| `jerseyApplication`            | 返回 `ResourceConfig`，扫描 `com.netflix.discovery` / `com.netflix.eureka` 下带 `@Path`、`@Provider` 的类，并用 hk2 的 `SpringIntoHK2Bridge` 把 Spring BeanFactory 桥接为 Jersey 的依赖注入源 |
| `eurekaController`             | Dashboard 的 Spring MVC 控制器，`@ConditionalOnProperty("eureka.dashboard.enabled", matchIfMissing = true)`，映射路径 `${eureka.dashboard.path:/}` |
| `peerAwareInstanceRegistry`    | 返回 SCN 的 `InstanceRegistry`（见下）                                                        |

也就是说 Spring Cloud 里既没有 `web.xml`（那是裸 war 的做法，见 [REST API](/docs/CS/Framework/eureka/rest_api.md?id=filters-and-codecs)），也没有 `EurekaBootStrap`；启动由 `EurekaServerInitializerConfiguration` 承担：它 `implements ServletContextAware, SmartLifecycle, Ordered`（phase 0，order 1），`start()` 里**另起线程**调用 `eurekaServerBootstrap.contextInitialized(servletContext)`，随后依次发布 `EurekaRegistryAvailableEvent` 与 `EurekaServerStartedEvent`。之后的流程与裸 Server 一致，见 [Server](/docs/CS/Framework/eureka/Server.md)。

### InstanceRegistry 的事件桥接

```java
public class InstanceRegistry extends PeerAwareInstanceRegistryImpl implements ApplicationContextAware {
    @Override
    public void register(InstanceInfo info, int leaseDuration, boolean isReplication) {
        super.register(info, leaseDuration, isReplication);
        publishEvent(new EurekaInstanceRegisteredEvent(this, info, leaseDuration, isReplication));
    }
    // cancel / renew / statusUpdate 同理
}
```

SCN 继承 Netflix 的注册表实现，目的只有一个：把注册、续约、下线这些动作翻译成 Spring 的 `ApplicationEvent`（`EurekaInstanceRegisteredEvent` / `EurekaInstanceRenewedEvent` / `EurekaInstanceCanceledEvent`），让业务代码可以用 `@EventListener` 感知上下游变化。

另外 Spring Cloud 给了两个兜底参数（`InstanceRegistryProperties`）：`eureka.instance.registry.default-open-for-traffic-count`（默认 1）与 `expected-number-of-clients-sending-renews`（默认 1）。它们会在 `openForTraffic()` 里代替 0 参与[自我保护阈值](/docs/CS/Framework/eureka/self_preservation.md)的初始化——这也是 Spring Cloud 单机启动时 `Renews threshold` 显示 1 而不是 0 的原因。

## Client Side

`EurekaClientAutoConfiguration` 提供的核心 Bean：`EurekaClientConfigBean`、`EurekaInstanceConfigBean`、`EurekaServiceRegistry`、`EurekaAutoServiceRegistration`、`EurekaClient`（内嵌 `EurekaClientConfiguration` / `RefreshableEurekaClientConfiguration` 两套），以及 `serviceregistry` 包下的 `EurekaRegistration`、`EurekaPauseHandler` 与健康检查 Bean。这套 `ServiceRegistry` 抽象是 Spring Cloud Commons 定义的通用契约，同一套 API 也能驱动 Consul、Nacos、Zookeeper，因此迁移时上层代码基本不用改。

值得注意的默认值差异与实际行为：[config](/docs/CS/Framework/eureka/config.md)

- `service-url.defaultZone` 默认 `http://localhost:8761/eureka/`——**生产必须覆盖**；
- `eureka.client.healthcheck.enabled` 默认 false，开了才会把 Actuator 健康态映射为 Eureka 状态（映射到 out of service / down）；
- 心跳与缓存刷新的线程池默认是 **2**（Netflix 原生是 5）；
- 5.x 起支持 `eureka.client.tls.*`（keyStore / trustStore / enabled），走 spring-cloud-commons 的 `TlsProperties`。

与负载均衡侧的衔接：Eureka 提供 VIP（逻辑服务名），由 Feign 或 Spring Cloud LoadBalancer 解析，详见 [LoadBalancer](/docs/CS/Framework/Spring_Cloud/LoadBalancer.md)、[Feign](/docs/CS/Framework/Spring_Cloud/Feign.md)、[网关](/docs/CS/Framework/Spring_Cloud/gateway.md)。

## Migration

Spring Cloud 官方文档并未把 Eureka 标记为 deprecated，但它已不是推荐起点。常见去向：

| 目标                                | 适用场景                     | 改动面                                             |
| :-------------------------------- | :----------------------- | :---------------------------------------------- |
| [Nacos](/docs/CS/Framework/nacos/Nacos.md)     | 想顺带拿配置中心、需要秒级推送、中文生态     | 换 starter + 配置；注册/订阅模型由拉转推，客户端容忍度假设要改           |
| [Consul](/docs/CS/Framework/consul/Consul.md) | Spring 生态原生、CP、自带健康检查    | 换 starter + `spring.cloud.consul.*`              |
| Kubernetes Service / DNS          | 已全部容器化，不想额外维护注册中心        | 去掉 client，改 [Spring Cloud Kubernetes](/docs/CS/Container/k8s/Service.md) 或由网关直接对接，`McpBridge` 见 [Higress 服务发现](/docs/CS/Framework/Higress/Service_Discovery.md) |

迁移期通常需要双注册（同时保留两套 client）或一个双向同步组件；因为 Eureka 是拉模型而 Nacos/Consul 多为推/长轮询，务必先把下游的「拿到失效实例」假设改掉——Eureka 时代遗留的大量「重试 + 熔断」代码在迁移后可能显得多余，而在迁移过程中它们反而是保命配置。

## Links

- [Eureka](/docs/CS/Framework/eureka/Eureka.md)
- [Config](/docs/CS/Framework/eureka/config.md)
- [Server](/docs/CS/Framework/eureka/Server.md)
- [Client](/docs/CS/Framework/eureka/Client.md)
- [Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md)
- [Spring Cloud Alibaba](/docs/CS/Framework/Spring_Cloud/Alibaba.md)

## References

1. [Spring Cloud Netflix](https://github.com/spring-cloud/spring-cloud-netflix)
2. [spring-cloud-starter-netflix-eureka-client 版本列表](https://repo1.maven.org/maven2/org/springframework/cloud/spring-cloud-starter-netflix-eureka-client/)
3. [Spring Cloud Netflix 参考文档](https://docs.spring.io/spring-cloud-netflix/reference/)
