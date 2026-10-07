## Introduction

[Spring Cloud Alibaba](https://sca.aliyun.com/) 是阿里巴巴开源的微服务组件与 Spring Cloud 之间的**适配层**。它本身不重复造轮子，而是把 Nacos、Sentinel、Seata、RocketMQ、SchedulerX 这些组件包装成 Spring Boot starter + 自动配置，让它们用起来和 Spring Cloud 原生组件一样——加依赖、写配置、`@Autowired` 就能用。

理解它的定位要抓住一点：**Spring Cloud 定义了一套微服务能力的接口契约**（服务发现 `DiscoveryClient`、配置、熔断、负载均衡…），至于底层用 Eureka 还是 Nacos、用 Hystrix 还是 Sentinel，是可以替换的。Spring Cloud Alibaba 提供的正是"另一种实现"。

```text
业务代码
   ↓  依赖 Spring Cloud 的抽象
DiscoveryClient / LoadBalancer / CircuitBreaker / ConfigDataResource
   ↓  由谁实现？
Nacos · Sentinel · Seata · RocketMQ      ← Spring Cloud Alibaba
Eureka · Consul · Resilience4j · Kafka   ← Spring Cloud 原生 / 其它厂商
```

> [!NOTE]
> **分工**：本文讲 Spring Cloud Alibaba 这层的版本、装配选型与迁移；各组件本身的原理见各自的笔记——[Nacos](/docs/CS/Framework/nacos/Nacos.md)、[Sentinel](/docs/CS/Framework/Sentinel/Sentinel.md)、[Seata](/docs/CS/Framework/Seata/Seata.md)、[RocketMQ](/docs/CS/MQ/RocketMQ/RocketMQ.md)。

## Version Matrix

Spring Cloud Alibaba 的版本号与 Spring Cloud 的发布列车严格绑定，**务必按官方对照表选**，混搭会在自动配置阶段各种奇怪地失效。

官方给定的是：

| Spring Cloud Alibaba | Spring Cloud | Spring Boot |
| ---- | ---- | ---- |
| **2025.1.0.0** | 2025.1.0 | **4.0.0** |
| 2025.0.0.0 | 2025.0.0 | 3.5.0 |

对应的内部组件版本：

| Spring Cloud Alibaba | Sentinel | Nacos | RocketMQ | SchedulerX | Seata |
| ---- | ---- | ---- | ---- | ---- | ---- |
| 2025.1.0.0 | 1.8.9 | 3.1.1 | 5.3.1 | 1.13.3 | 2.5.0 |
| 2025.0.0.0 | 1.8.9 | 3.0.3 | 5.3.1 | 1.13.1 | 2.5.0 |

> [!NOTE]
> **Boot 版本**：上表 2025.1.0.0 锁定 Spring Boot **4.0.0** 作为发布基线；其依赖管理（`spring-cloud-alibaba-dependencies`）后续已把 `spring-boot`  bump 到 **4.1.0**，与当前 Boot 4.1.x 基线一致。新项目直接引 4.1.x 即可，无需刻意降回 4.0.0。

> [!TIP]
> 命名规律：**2025.1.x 分支适配 Boot 4 + Cloud 2025.1**（即当前基线），2025.0.x 适配 Boot 3.5 + Cloud 2025.0。网上有些文章把 Sentinel 写成 2.0.0、Nacos Client 写成 3.0.0，与上表不符，应以官方版本说明为准。

## How to Introduce

Spring Cloud Alibaba 以 BOM 形式统一管理各组件版本，不要手工指定子组件版本：

```xml
<properties>
    <spring-cloud.version>2025.1.0</spring-cloud.version>
    <spring-cloud-alibaba.version>2025.1.0.0</spring-cloud-alibaba.version>
</properties>

<dependencyManagement>
    <dependencies>
        <dependency>
            <groupId>org.springframework.cloud</groupId>
            <artifactId>spring-cloud-dependencies</artifactId>
            <version>${spring-cloud.version}</version>
            <type>pom</type>
            <scope>import</scope>
        </dependency>
        <dependency>
            <groupId>com.alibaba.cloud</groupId>
            <artifactId>spring-cloud-alibaba-dependencies</artifactId>
            <version>${spring-cloud-alibaba.version}</version>
            <type>pom</type>
            <scope>import</scope>
        </dependency>
    </dependencies>
</dependencyManagement>
```

## Components and Responsibilities

| 组件 | 解决什么 | 常用 starter | 对应 Spring Cloud 原生替代 |
| ---- | ---- | ---- | ---- |
| **Nacos Discovery** | 服务注册与发现 | `spring-cloud-starter-alibaba-nacos-discovery` | Eureka / Consul / Zookeeper |
| **Nacos Config** | 集中配置、动态刷新 | `spring-cloud-starter-alibaba-nacos-config` | Spring Cloud Config |
| **Sentinel** | 流量控制、熔断降级、系统自适应保护 | `spring-cloud-starter-alibaba-sentinel` | Resilience4j |
| **Seata** | 分布式事务（AT / TCC / Saga / XA） | `spring-cloud-starter-alibaba-seata` | 无直接对应（自己做 Saga） |
| **RocketMQ** | 消息中间件（含 Stream binder） | `spring-cloud-starter-stream-rocketmq` | Kafka / RabbitMQ binder |
| **SchedulerX** | 分布式任务调度 | `spring-cloud-starter-alibaba-schedulerx` | 无（自建 Quartz 集群） |

### Wiring Essentials

- **Nacos Discovery**：starter 自动向 Nacos 注册服务实例、拉取服务列表，并使 Spring Cloud LoadBalancer 从中读取实例（见 [LoadBalancer](/docs/CS/Framework/Spring_Cloud/LoadBalancer.md)）。启用即 `@EnableDiscoveryClient`（多数版本已自动开启）。注册中心的原理见 [registry](/docs/CS/Framework/nacos/registry.md)。
- **Nacos Config**：优先 Boot 4 的 `spring.config.import` 方式接入（见下一节）。配置中心本身的推送机制见 [config](/docs/CS/Framework/nacos/config.md) 与 [ConfigServer](/docs/CS/Framework/nacos/ConfigServer.md)。
- **Sentinel**：starter 会自动为 MVC、WebFlux、Feign、RestTemplate、Gateway 注入埋点，使其受流控规则管辖。规则可以从控制台推送到本地，也可以托管到 Nacos 之类的外部数据源做持久化。限流算法本身见 [RateLimiter](/docs/CS/Framework/Sentinel/RateLimiter.md) 与 [CircuitBreaker](/docs/CS/Framework/Sentinel/CircuitBreaker.md)。
- **Seata**：靠数据源代理（`DataSourceProxy`）在本地事务里偷偷记录回滚日志，二阶段提交/回滚由 Seata Server（TC）协调。注意它会替换你的数据源 Bean，若项目里有多数据源或自定义数据源，需要留意整合方式。

## Ecosystem: Gateway and RPC

Spring Cloud Alibaba 主解决"注册 / 配置 / 流控 / 事务 / 消息"这一层；落到南北向流量入口与 RPC 协议，还有两个常被一起提及的阿里系项目。

### Higress (Cloud-Native Gateway)

Higress 是阿里巴巴开源、基于 Envoy 的云原生 API 网关（CNCF 沙箱项目），与 Nacos 服务发现、Dubbo、Kubernetes 深度集成。在 K8s 环境里它常作为**融合网关**——一个网关同时承担流量网关（替代 Nginx Ingress）与微服务网关（对接 Nacos 服务名做路由、限流、灰度），并可与 Spring Cloud Gateway 互为替代：传统虚拟机 + Spring Cloud 技术栈用 [gateway](/docs/CS/Framework/Spring_Cloud/gateway.md)，K8s 原生环境优先 Higress。

### Dubbo (RPC Framework)

Dubbo 是阿里的高性能 Java RPC 框架，Spring Cloud Alibaba 提供 `spring-cloud-starter-dubbo`（见 [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)），让 Dubbo 服务可以**复用 Spring Cloud 的服务发现（Nacos）与负载均衡**：Dubbo Provider / Consumer 也能注册进 Nacos、被 `DiscoveryClient` 看到。选型上它与 OpenFeign / RestTemplate 是不同风格的 RPC（Dubbo 用 Triple / gRPC 私有协议、强调服务治理），二者一般不同时作为主调用方式。

> [!WARNING]
> **商业云 SDK 已不在主 BOM**。早期（2.2.x 及以前）的 `spring-cloud-starter-alicloud-oss` / `-sms` / `-schedulerx` 等阿里云商业 SDK starter 已停止维护，Maven Central 停留在 `2.2.0.RELEASE`（6 年以上），**不在 2025.x 的 `spring-cloud-alibaba-dependencies` 里**，直接引用会因找不到版本而解析失败。需要 OSS / SMS 等能力时，直接引入阿里云官方 SDK（`com.aliyun` / `alibabacloud` 坐标），不要通过 Spring Cloud Alibaba 的 BOM 管理。

## Breaking Changes When Upgrading to 2025.1.0.0

这一代同步拥抱了 Boot 4 + Cloud 2025.1，主要变化：

### 1. `bootstrap.yml` Is No Longer Available

改动最大也最容易踩。过去把注册中心/配置中心地址写在 `bootstrap.yml` 里（因为它在主 application context 之前加载），现在必须由 `spring.config.import` 承担：

```yaml
# application.yml —— 新写法
spring:
  application:
    name: my-service
  config:
    import: nacos:my-service.yml?refreshEnabled=true
  cloud:
    nacos:
      config:
        server-addr: 127.0.0.1:8848
```

缺了 `spring.config.import` 会直接启动失败（这点的报错比较明确，算幸运的）。同时要从 pom 里删掉 `spring-cloud-starter-bootstrap`。

### 2. Sentinel Moves to Jackson 3

随 Boot 4 的默认 JSON 库迁移，Sentinel 侧的包名从 `com.fasterxml.jackson` 转到新的 Jackson 3 坐标。**直接引用了 Jackson 内部类的自定义序列化代码会编译失败**。同时新版针对响应式环境（WebFlux / Gateway 2025）改进了限流埋点，不再阻塞 event loop 线程。

### 3. Nacos 3.1.1 Security Enhancements

新增敏感字段脱敏：配置序列化时会自动遮蔽 `password`、`secret`、`token` 等关键字的值，避免高 verbosity 日志里泄露凭据——无需改代码。

### 4. Seata Supports Reactive Transactions

响应式流里线程会跳转，传统的 `ThreadLocal` 上下文传递失效。新版适配了 Reactor 的 `ContextView`，让事务 XID 能在响应式流中透传，从而在 WebFlux 应用里也能用 AT / TCC 模式。同时修了一批自动配置问题。

### 5. RocketMQ Module Adapts to Boot 4

通过 Spring Cloud Stream 的 RocketMQ binder 支持 Boot 4.0，并增强了对消费者优先级的细粒度控制。

> [!NOTE]
> 升级清单上还有两条经验项：JDK 需 ≥ 17（用虚拟线程建议 21+）；部分连接池（如老版本 Druid starter）与 Boot 4 有兼容性问题，必要时升级或换回 HikariCP。

## Selection Recommendations

| 场景 | 建议 |
| ---- | ---- |
| 已经深度使用 K8s | 服务发现可以直接用 K8s Service + Ingress，不必再上 Nacos discovery；配置则仍可用 Nacos Config 或 ConfigMap |
| 需要"注册 + 配置 + 动态规则"一体化控制台 | Nacos + Sentinel 的组合体验最好：规则可托管到 Nacos 持久化，控制台可视化 |
| 只要熔断限流、不想引中间件 | 直接用 [Resilience4j](/docs/CS/Framework/Spring_Cloud/Resilience4j.md)，无中心化依赖 |
| 强一致跨服务事务 | 优先考虑**能不能用事件 + 幂等 + 补偿规避**；确实绕不开才上 Seata（AT 模式对数据库有侵入） |
| RPC 而非 REST | 另有一条线：[Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)，服务治理模型与 Spring Cloud 不同，二者一般不同时作为主 RPC |
| 已在 Spring 原生生态 | 不必为了"国产化"替换：Eureka/Consul/Config/Resilience4j 与这套组件在这层是等价可替代关系 |

最后一点值得强调：**这一层的技术选型是低风险可替换的**。它只影响接入方式，不侵入业务代码——只要业务依赖的是 Spring Cloud 的抽象而非具体实现，换是哪一套组件都不需要改业务代码。反过来，如果换组件要改一堆业务代码，说明抽象被打破了，那才是真正的技术债。

## Links

- [Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md)
- [Nacos](/docs/CS/Framework/nacos/Nacos.md)
- [Sentinel](/docs/CS/Framework/Sentinel/Sentinel.md)
- [Seata](/docs/CS/Framework/Seata/Seata.md)
- [RocketMQ](/docs/CS/MQ/RocketMQ/RocketMQ.md)
- [Higress](/docs/CS/Framework/Higress/Higress.md)

## References

1. [Spring Cloud Alibaba 版本发布说明（官方）](https://sca.aliyun.com/en/docs/2025.x/overview/version-explain)
2. [Spring Cloud Alibaba 项目主页](https://sca.aliyun.com/)
3. [Spring Boot 4.0 Migration Guide](https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-4.0-Migration-Guide)
