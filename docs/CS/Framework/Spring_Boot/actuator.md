## Introduction

The spring-boot-actuator module provides all of Spring Boot’s production-ready features.
The recommended way to enable the features is to add a dependency on the `spring-boot-starter-actuator` starter.

```groovy
dependencies {
    implementation 'org.springframework.boot:spring-boot-starter-actuator'
}
```

> [!NOTE]
> Boot 4 把原来单体式的 actuator 拆成了更细的模块，**若干常用类型换了包**。升级时按编译报错改 import 即可，但要知道这不是自己写错了：
>
> | 类型 | Boot 3 / 3.5 | Boot 4 |
> | :-- | :-- | :-- |
> | `Health` / `HealthIndicator` / `Status` / `AbstractHealthIndicator` | `org.springframework.boot.actuate.health` | `org.springframework.boot.health.contributor` |
> | `HealthEndpoint` | `org.springframework.boot.actuate.health` | `org.springframework.boot.health.actuate.endpoint` |
> | `EndpointRequest`（端点鉴权匹配器） | `org.springframework.boot.actuate.autoconfigure.security.servlet` | `org.springframework.boot.security.autoconfigure.actuate.web.servlet` |
> | `MeterRegistryCustomizer` | `org.springframework.boot.actuate.autoconfigure.metrics` | `org.springframework.boot.micrometer.metrics.autoconfigure` |
>
> 端点注解（`@Endpoint` / `@ReadOperation` / `@Selector`）、`InfoContributor`、`httpexchanges` 相关类型**未搬家**。starter 名 `spring-boot-starter-actuator` 也没变。

## 端点访问模型

Boot 4 用**访问级别（access）**取代了旧的 `enabled` 开关，这是本轮升级最容易踩的一处。

### 从 enabled 到 access

旧写法 `management.endpoint.<id>.enabled=true` 在 3.4 已弃用、4.0 起移除，改用三档访问级别：

| 级别 | 含义 |
| :-- | :-- |
| `none` | 完全不可访问，端点 Bean 会**整个从应用上下文移除**（即旧 `enabled=false` 的效果） |
| `read-only` | 只允许 `@ReadOperation`（或 `GET` / `HEAD`），写与删除返回 405 |
| `unrestricted` | 读写删除全放行 |

```properties
# 默认：除 shutdown、heapdump 外全部 unrestricted
management.endpoints.access.default=unrestricted

# 想改成"默认拒绝、逐个放行"的 opt-in 模式
management.endpoints.access.default=none
management.endpoint.loggers.access=read-only

# 全局封顶，优先级高于 default 与单个端点配置
management.endpoints.access.max-permitted=read-only
```

> [!TIP]
> `max-permitted` 是**上限**而非默认值：设为 `read-only` 后，即便某个端点被单独配成 `unrestricted`，也会被压回只读。生产环境设它是性价比最高的一条配置——防止日后新增端点意外带出写操作。

### 可用 = 允许访问 + 暴露

这是两个独立维度，端点只有在**两者都满足**时才可用：

- **访问（access）** —— 上面那套，决定端点 Bean 是否存在于容器；
- **暴露（exposure）** —— 决定它是否挂到 HTTP / JMX 上对外可见。

默认 HTTP 与 JMX **都只暴露 `health`**：

```properties
management.endpoints.web.exposure.include=health,info,prometheus,metrics
management.endpoints.web.exposure.exclude=env,beans,configprops,heapdump,threaddump
```

`exclude` 优先级高于 `include`；`*` 在 YAML 里有特殊含义，**必须加引号**。

## 内置端点

技术无关的端点：

| ID | 用途 | 前置条件 |
| :-- | :-- | :-- |
| `health` | 健康状态 | — |
| `info` | 应用自定义信息 | — |
| `beans` | 容器内全部 Bean 清单 | — |
| `conditions` | 自动配置的匹配/不匹配判定及原因 | — |
| `configprops` | 全部 `@ConfigurationProperties`（脱敏） | — |
| `env` | `Environment` 中的属性（脱敏） | — |
| `mappings` | 全部请求映射路径 | Web 应用 |
| `metrics` | Micrometer 指标 | — |
| `loggers` | 查看并**运行时修改**日志级别 | — |
| `caches` | 缓存实例 | — |
| `scheduledtasks` | 定时任务清单 | — |
| `startup` | 启动过程各步骤耗时 | 需配置 `BufferingApplicationStartup` |
| `threaddump` | 线程转储 | — |
| `httpexchanges` | 最近 100 次 HTTP 请求-响应交换 | 需 `HttpExchangeRepository` Bean |
| `flyway` / `liquibase` | 数据库迁移状态 | 对应迁移工具 |
| `quartz` | Quartz 任务 | — |
| `sessions` | 会话查询与失效 | Servlet + Spring Session |
| `integrationgraph` | Spring Integration 图 | `spring-integration-core` |
| `auditevents` | 审计事件 | `AuditEventRepository` Bean |
| `sbom` | 软件物料清单 | CycloneDX 等 |
| `shutdown` | 优雅关闭（**默认不可访问**） | jar 包部署 |

Web 应用额外提供：`heapdump`（堆转储，**默认不可访问**）、`logfile`（日志文件内容，支持 Range 头）、`prometheus`（Prometheus 抓取格式，需 `micrometer-registry-prometheus`）。

### 路径与发现页

默认基础路径 `/actuator`（`management.endpoints.web.base-path` 可改），`/actuator` 本身是发现页，列出所有已暴露端点的链接（`management.endpoints.web.discovery.enabled=false` 可关闭）。

CORS 默认关闭，配置 `management.endpoints.web.cors.allowed-origins` 后启用。

把管理流量与业务流量隔开很有必要：

```properties
management.server.port=8081      # 独立管理端口，独立连接器与线程池
```

这样业务请求与监控请求互不争抢连接，且该端口可以只对内网放通。

## 健康检查

### 内置健康指示器

Boot 按 classpath 自动装配：`DataSourceHealthIndicator`、`RedisHealthIndicator`、`RabbitHealthIndicator`、`KafkaHealthIndicator`、`DiskSpaceHealthIndicator`、`PingHealthIndicator`，以及 K8s 相关的 `LivenessStateHealthIndicator` / `ReadinessStateHealthIndicator`。

> [!WARNING]
> 内置指示器大多只验证**连通性**而非**可用性**。例如 AMQP 指示器只是连上 broker 读一个服务端属性就返回 UP，它不检查队列积压与消费者数量——"broker 可达 + 零消费者 + 队列积压两小时"依然是绿色的。真正关心的业务指标要自己写指示器。

### 自定义指示器

类名去掉 `HealthIndicator` 后缀即健康项的 id（`OrdersQueueHealthIndicator` → `ordersQueue`）：

```java
import org.springframework.boot.health.contributor.Health;
import org.springframework.boot.health.contributor.HealthIndicator;

@Component
public class OrdersQueueHealthIndicator implements HealthIndicator {

    @Override
    public Health health() {
        int pending = queueDepth();
        return pending > 1_000
                ? Health.down().withDetail("pending", pending).build()
                : Health.up().withDetail("pending", pending).build();
    }
}
```

响应式栈实现 `ReactiveHealthIndicator`，返回 `Mono<Health>`——注意它必须是**非阻塞**的，里面调阻塞客户端会毁掉事件循环。

Boot 4 的 `HealthContributor` 是密封接口，`HealthIndicator` 与 `CompositeHealthContributor` 是它的两个分支；后者可把若干检查聚合到一个父节点下，让 `/actuator/health` 返回一棵树。

### 详情展示与脱敏

```properties
management.endpoint.health.show-details=when-authorized   # always / never / when-authorized
management.endpoint.health.roles=ENDPOINT_ADMIN
management.endpoint.env.show-values=when-authorized       # 环境变量同理
```

`always` 会把数据库地址、中间件版本、异常堆栈暴露给任何能访问该端点的人，生产环境应使用 `when-authorized`。

### HTTP 状态码映射

整体状态与返回码的对应由 `HttpCodeStatusMapper` 决定，默认 `DOWN` / `OUT_OF_SERVICE` → 503，`UP` / `UNKNOWN` → 200。反过来，**不要用状态码判断细节**，看 `status` 字段。

## 健康组与 Kubernetes 探针

健康组（health group）把若干指示器打包成一个子路径：

```properties
management.endpoint.health.group.custom.include=db,redis,ordersQueue
```

访问 `/actuator/health/custom` 即只看这几项。K8s 探针正是基于两个内置组实现的：

```properties
management.endpoint.health.probes.enabled=true                 # 默认 false
management.endpoint.health.probes.add-additional-paths=true    # 额外在主端口暴露 /livez、/readyz
```

| 探针 | 路径 | 语义 | 失败后果 |
| :-- | :-- | :-- | :-- |
| Liveness | `/actuator/health/liveness`（或 `/livez`） | 进程是否卡死 | K8s **重启**容器 |
| Readiness | `/actuator/health/readiness`（或 `/readyz`） | 能否接收流量 | K8s **摘除**端点，不重启 |

> [!WARNING]
> 两者不能被混为一谈，这是最危险的误用：**liveness 绝不应依赖外部系统**。若把数据库检查放进 liveness，数据库抖动会让 K8s 重启**所有**实例，把局部故障放大成全面雪崩。依赖关系应放进 readiness。

关闭阶段的语义决定了优雅停机是否可行：进入 graceful shutdown 时 readiness 先转为 `REFUSING_TRAFFIC`，K8s 摘流量，应用再处理完存量请求——配合 `server.shutdown=graceful` 才能实现无损发布。

## HTTP 交换记录

旧的 `/actuator/httptrace` 与 `HttpTraceRepository` 在 Boot 3 已更名为 `httpexchanges` / `HttpExchangeRepository`：

```java
import org.springframework.boot.actuate.web.exchanges.HttpExchangeRepository;
import org.springframework.boot.actuate.web.exchanges.InMemoryHttpExchangeRepository;

@Configuration
class HttpExchangeConfig {

    @Bean
    HttpExchangeRepository httpExchangeRepository() {
        return new InMemoryHttpExchangeRepository();   // 默认只保留最近 100 条
    }
}
```

```properties
management.endpoints.web.exposure.include=health,httpexchanges
management.httpexchanges.recording.include=TIME_TAKEN,REQUEST_HEADERS
```

它记录时间戳、principal、session、请求/响应头与耗时，对排查线上问题很有用，但**只应作为开发期手段**：内存环形缓冲有上限、多实例下不聚合、重启即丢。生产的可观测性应交给 Micrometer Tracing / OpenTelemetry，参见 [Sleuth 与链路追踪](/docs/CS/Framework/Spring_Cloud/Sleuth.md)。

## 自定义端点

`@Endpoint` 是技术无关的端点声明，`@WebEndpoint` 限定 Web 暴露，`@JmxEndpoint` 限定 JMX：

```java
@Component
@Endpoint(id = "features")
class FeaturesEndpoint {

    @ReadOperation
    public Map<String, Boolean> features() {
        return Map.of("newCheckout", toggle.isEnabled("newCheckout"));
    }

    @WriteOperation
    public void toggle(@Selector String name, boolean enabled) {
        toggle.set(name, enabled);
    }
}
```

`@ReadOperation` 映射 GET、`@WriteOperation` 映射 POST、`@DeleteOperation` 映射 DELETE；`@Selector` 用于声明路径变量（`/actuator/features/{name}`）。

> [!NOTE]
> 在 `management.endpoints.access.max-permitted=read-only` 或默认被判定为只读的配置下，自定义端点上的 `@WriteOperation` 会**返回 405 而不是报错**，很容易误以为代码没生效。需要写操作时显式放开：`management.endpoint.features.access=unrestricted`。

旧的 `@ControllerEndpoint` / `@ServletEndpoint` 已迁往 `@Endpoint` + 扩展类，新代码不要再用。

## 端点安全

Actuator 端点会泄露 Bean 结构、环境变量、配置属性，`heapdump` 更能直接导出内存中的密钥与用户数据。分三层防护：

**只暴露必要的** —— 用显式列表替代 `include=*`；`env`、`configprops`、`beans`、`heapdump`、`threaddump` 一律不暴露。

**用独立管理端口并限制网络可达** —— `management.server.port=8081` + 只对内网/集群放通。

**接入 Spring Security** —— 存在自定义 `SecurityFilterChain` 时 Boot 的自动保护会退避，需自己配一条链：

```java
import org.springframework.boot.security.autoconfigure.actuate.web.servlet.EndpointRequest;

@Bean
@Order(1)
SecurityFilterChain actuatorSecurity(HttpSecurity http) throws Exception {
    http.securityMatcher(EndpointRequest.toAnyEndpoint())
        .authorizeHttpRequests(auth -> auth
                .requestMatchers(EndpointRequest.to("health", "info")).permitAll()
                .anyRequest().hasRole("ENDPOINT_ADMIN"))
        .httpBasic(Customizer.withDefaults());
    return http.build();
}
```

用 `EndpointRequest` 而非硬编码 `/actuator/**`，这样改基础路径时安全策略不会失效。详见 [Spring Security](/docs/CS/Framework/Spring/Security.md)。

## 指标与 Prometheus

`/actuator/metrics` 提供交互式查询，`/actuator/prometheus` 提供抓取端点：

```properties
management.endpoints.web.exposure.include=health,info,prometheus
management.metrics.tags.application=${spring.application.name}
```

> [!WARNING]
> 最危险的指标问题是**标签基数爆炸**：把用户 ID、订单号、原始 URL 当作 tag，会让时间序列数量随请求量线性增长，最终拖垮 Prometheus。用 `MeterFilter` 做兜底，把 URI 归并为模板路径：
>
> ```java
> @Bean
> MeterFilter replaceUriTag() {
>     return MeterFilter.replaceTagValues("uri", uri -> uri.replaceAll("\\d+", "{id}"));
> }
> ```

## Links

- [Spring Boot](/docs/CS/Framework/Spring_Boot/Spring_Boot.md)
- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [Spring Security](/docs/CS/Framework/Spring/Security.md)
- [Spring Boot 启动流程](/docs/CS/Framework/Spring_Boot/Start.md)
- [Spring Cache](/docs/CS/Framework/Spring_Boot/cache.md)

## References

- [Spring Boot - Actuator Endpoints](https://docs.spring.io/spring-boot/reference/actuator/endpoints.html)
- [Spring Boot - Health Information](https://docs.spring.io/spring-boot/reference/actuator/health.html)
- [Spring Boot - Recording HTTP Exchanges](https://docs.spring.io/spring-boot/reference/actuator/http-exchanges.html)
- [Spring Boot - Metrics and Observability](https://docs.spring.io/spring-boot/reference/actuator/metrics.html)
- [Spring Boot - Kubernetes Probes](https://docs.spring.io/spring-boot/reference/actuator/cloud-foundry.html)
