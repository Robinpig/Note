## Introduction

The [Spring Framework](https://spring.io/projects/spring-framework) provides a comprehensive programming and configuration model for *modern Java-based enterprise applications* - on any kind of deployment platform. makes programming Java quicker, easier, and safer for everybody.
Spring’s focus on speed, simplicity, and productivity has made it the world's most popular Java framework.

## Version Baseline

Spring 家族当前基线是 **Framework 7 / Boot 4** 这一代（Boot 4.0 于 2025-11 GA，4.1 于 2026-06 GA）。本目录所有笔记的 API、配置项与默认行为描述均以此为准：

| 组件 | 当前版本 | 关键点 |
| :-- | :-- | :-- |
| Spring Framework | **7.0.9** | Java 17 基线，全面拥抱 JDK 25；Kotlin 2.2 |
| Spring Boot | **4.1.1** | 自动配置拆分为 70+ 模块，starter 大量改名 |
| Spring Security | **7.1.1** | 多因素认证（MFA）；Spring Authorization Server 并入本项目 |
| Spring Data | **2025.1.x**（Data JPA 4.0.7） | 为符合条件的 repository 查询生成构建期编译实现 |
| Spring Batch | **6.0.5** | 默认改为内存 JobRepository，续跑需显式引 JDBC starter |
| Spring Integration | **7.1.1** | 各模块按 input / output 重新分包 |
| Spring AMQP | **4.1.1** | Jackson 3 消息转换器改名；新增 AMQP 1.0 客户端模块 |
| Spring for Apache Kafka | **4.1.1** | 新增 Share Consumer（Kafka Queues） |
| Spring Cloud | **2025.1**（Oakwood） | 各子项目统一到 5.0.0，基于 Framework 7 / Boot 4 |
| Hibernate ORM | **7.4.11** | Jakarta Persistence 3.2；不再允许重新关联游离实体 |
| Jakarta EE | **11** | Servlet 6.1、WebSocket 2.2、Validation 3.1、Persistence 3.2 |
| JSON 处理 | **Jackson 3** | 包名 `com.fasterxml.jackson` → `tools.jackson` |
| JDK | **17 最低** | 21 / 25 为推荐运行时 |

> [!TIP]
> 上表版本号取自各项目官方仓库的最新 release tag（2026-10 核对）。实际项目里子项目的确切版本由所用 Boot 版本的依赖管理（BOM）决定，以 `spring-boot-dependencies` 为准，不要照抄表格里的数字去写构建文件。

会被业务代码直接感知的破坏性变更：

- **starter 改名**：`spring-boot-starter-web` → `spring-boot-starter-webmvc`，`spring-boot-starter-aop` → `spring-boot-starter-aspectj`，`spring-boot-starter-oauth2-*` → `spring-boot-starter-security-oauth2-*`，`spring-boot-starter-web-services` → `spring-boot-starter-webservices`。旧名保留但已弃用。
- **测试依赖拆分**：单个 `spring-boot-starter-test` 不再覆盖一切，Web 层测试需另加 `spring-boot-starter-webmvc-test`；迁移期可用 `spring-boot-starter-classic` / `spring-boot-starter-test-classic` 兜底。
- **Jackson 3**：`ObjectMapper` 由 `JsonMapper` 取代，日期默认序列化为 ISO-8601 字符串而非时间戳。
- **`javax.annotation` / `javax.inject` 注解不再支持**，改用 `jakarta.annotation` / `jakarta.inject`。
- **`RestTemplate` 进入退场流程**：7.1 弃用、8.0 移除，新代码统一用 `RestClient`。
- **`AntPathMatcher`** 在 HTTP 请求映射场景弃用，改用 `PathPattern`。
- **不再支持 Undertow**（尚未兼容 Jakarta Servlet 6.1）。
- **Actuator 的 `enabled` 换成 `access`**：`management.endpoint.<id>.enabled` 已移除，改用 `management.endpoint.<id>.access`（`none` / `read-only` / `unrestricted`）与 `management.endpoints.access.default`；自定义端点的写操作在只读配置下会返回 405 而非报错。详见 [Actuator](/docs/CS/Framework/Spring_Boot/actuator.md?id=endpoint-access-model)。
- **Actuator 健康检查包搬迁**：`Health` / `HealthIndicator` / `Status` 从 `org.springframework.boot.actuate.health` 迁到 `org.springframework.boot.health.contributor`。

7.0 新增、值得单独一提的能力：JSpecify 空安全注解（取代 `org.springframework.lang` 下的 JSR-305 注解）、MVC 与 WebFlux 的 API 版本化、`spring-core` 内建的 Retry（`@Retryable` / `@ConcurrencyLimit`）、`@ImportHttpServices` HTTP 接口分组注册、`BeanRegistrar` 编程式 Bean 注册。

## Architecture

At its core, Spring offers a *container*, often referred to as the *Spring application context*, that creates and manages application components.
These components, or beans, are wired together inside the Spring application context to make a complete application.

The act of wiring beans together is based on a pattern known as *dependency injection*(DI).
Rather than have components create and maintain the life cycle of other beans that they depend on, a dependency-injected application relies on a separate entity(the container) to create and maintain all components and inject those into the beans that need them.
This is done typically through constructor arguments or property accessor methods.

Historically, the way you would guide Spring’s application context to wire beans together was with one or more XML files that described the components and their relationship to other components.
In recent versions of Spring, however, a Java-based configuration is more common.

Java-based configuration offers several benefits over XML-based configuration, including greater type safety and improved refactorability.
Even so, explicit configuration with either Java or XML is necessary only if Spring is unable to automatically configure the components.

Automatic configuration has its roots in the Spring techniques known as autowiring and component scanning.
With component scanning, Spring can automatically discover components from an application’s classpath and create them as beans in the Spring application context.
With autowiring, Spring automatically injects the components with the other beans that they depend on.

More recently, with the introduction of [Spring Boot](/docs/CS/Framework/Spring_Boot/Spring_Boot.md), automatic configuration has gone well beyond component scanning and autowiring.
Spring Boot is an extension of the Spring Framework that offers several productivity enhancements.
The most well known of these enhancements is autoconfiguration, where Spring Boot can make reasonable guesses at what components need to be configured and wired together, based on entries in the classpath, environment variables, and other factors.

### Core

Foremost amongst these is the Spring Framework’s [Inversion of Control (IoC)](/docs/CS/Framework/Spring/IoC.md) container. 
A thorough treatment of the Spring Framework’s IoC container is closely followed by comprehensive coverage of Spring’s [Aspect-Oriented Programming (AOP)](/docs/CS/Framework/Spring/AOP.md) technologies.

Spring’s [Resource](/docs/CS/Framework/Spring/Resource.md) abstraction (`org.springframework.core.io.Resource` / `ResourceLoader`) provides a uniform way to access low-level resources (classpath, filesystem, URL, `ServletContext`).

[SpEL](/docs/CS/Framework/Spring/SpEL.md)（`spring-expression`）是框架内的表达式语言，`@Value("#{...}")`、`@Cacheable` 的 key 条件、`@PreAuthorize` 的权限表达式都由它求值；注意与属性占位符 `${...}` 是两套不同机制。

[Validation](/docs/CS/Framework/Spring/Validation.md) 提供两层校验：Spring 自身的 `Validator` 接口，以及基于 Jakarta Validation 的声明式注解校验（分组、级联、方法校验），并与 MVC 数据绑定打通。

[AOT](/docs/CS/Framework/Spring/AOT.md) processing can be used to optimize your application ahead-of-time. It is typically used for native image deployment using GraalVM.



### Web

Spring comes with a powerful web framework known as [Spring MVC](/docs/CS/Framework/Spring/MVC.md).
At the center of Spring MVC is the concept of a *controller*, a class that handles requests and responds with information of some sort.
In the case of a browser-facing application, a controller responds by optionally populating model data and passing the request on to a view to produce HTML that’s returned to the browser.

[Spring WebFlux](/docs/CS/Framework/Spring/webflux.md) web frameworks.
响应式编程范式（Reactive Streams、Reactor、背压）与架构理念见 [Reactive](/docs/CS/Framework/Spring/Reactive.md)。

[统一异常处理](/docs/CS/Framework/Spring/Exception.md)：`@ControllerAdvice` + `@ExceptionHandler` 集中处理控制器异常，Spring 6 起支持 RFC 9457 的 `ProblemDetail` 标准错误响应；容器级异常（404 等）由 `/error` 端点兜底。

[OpenAPI / springdoc](/docs/CS/Framework/Spring/OpenAPI.md)：运行时扫描控制器与校验注解，自动生成 OpenAPI 契约并渲染 Swagger UI，产出可用于生成客户端、契约测试与网关校验。

[WebSocket 与 STOMP](/docs/CS/Framework/Spring/WebSocket.md)：服务端双向推送。`WebSocketHandler` 处理原生连接，`@EnableWebSocketMessageBroker` + `@MessageMapping` 提供 STOMP 消息语义；集群部署需改用 relay broker。

### Data Access

[Spring Data](/docs/CS/Framework/Spring/Data.md) 提供统一的 Repository 抽象与异常体系转换（`DataAccessException` / `SQLErrorCodeSQLExceptionTranslator`），各存储由独立子项目适配。

Spring Data’s mission is to provide a familiar and consistent,  Spring-based programming model for data access while still retaining the special traits of the underlying data store.

It makes it easy to use data access technologies, relational and  non-relational databases, map-reduce frameworks, and cloud-based data  services. This is an umbrella project which contains many subprojects  that are specific to a given database.

- [Spring Data Commons](https://github.com/spring-projects/spring-data-commons) - Core Spring concepts underpinning every Spring Data module.
- [Spring Data JDBC](https://spring.io/projects/spring-data-jdbc) - Spring Data repository support for JDBC.
- [Spring Data R2DBC](https://spring.io/projects/spring-data-r2dbc) - Spring Data repository support for R2DBC.
- [Spring Data JPA](https://spring.io/projects/spring-data-jpa) - Spring Data repository support for JPA.
- [Spring Data KeyValue](https://github.com/spring-projects/spring-data-keyvalue) - `Map` based repositories and SPIs to easily build a Spring Data module for key-value stores.
- [Spring Data LDAP](https://spring.io/projects/spring-data-ldap) - Spring Data repository support for [Spring LDAP](https://github.com/spring-projects/spring-ldap).
- [Spring Data MongoDB](https://spring.io/projects/spring-data-mongodb) - Spring based, object-document support and repositories for MongoDB.
- [Spring Data Redis](https://spring.io/projects/spring-data-redis) - Easy configuration and access to Redis from Spring applications.
- [Spring Data REST](https://spring.io/projects/spring-data-rest) - Exports Spring Data repositories as hypermedia-driven RESTful resources.
- [Spring Data for Apache Cassandra](https://spring.io/projects/spring-data-cassandra) - Easy configuration and access to Apache Cassandra or large scale, highly available, data oriented Spring applications.
- [Spring Data for Apache Geode](https://spring.io/projects/spring-data-geode) - Easy configuration and access to Apache Geode for highly consistent, low latency, data oriented Spring applications.

### Integration

Spring Framework’s integration with a number of technologies.

#### REST Clients

Spring Framework 提供四种调用 REST 端点的方式，当前推荐顺序如下：

- [RestClient](/docs/CS/Framework/Spring/RestClient.md)：Spring 6.1 引入的同步客户端，fluent API + 函数式请求定制，**7.x 的新代码首选**。
- WebClient：非阻塞、响应式，基于 Reactor，支持同步/异步/流式与背压；Boot 4 起有独立 starter。
- HTTP Interface：声明式 Java 接口 + 注解，由框架生成代理（Spring 6）；7.0 增加 `@ImportHttpServices` 分组注册。
- `RestTemplate`：最初的同步模板方法客户端。5.0 起进入维护模式，**7.1 弃用、8.0 移除**，仅存量代码继续使用。

Callback interface that can be used to customize the ClientHttpRequest sent from a RestTemplate.
```java
@FunctionalInterface
public interface RestTemplateRequestCustomizer<T extends ClientHttpRequest> {
	void customize(T request);

}
```

- [Spring Modulith](/docs/CS/Framework/Spring/Modulith.md)：用包结构表达单体内部的模块边界，并由工具验证可见性、提供可靠事件发布与架构文档生成。
- [数据库迁移](/docs/CS/Framework/Spring/Migration.md)：Flyway / Liquibase 管理 schema 版本演进。

#### Task Execution and Scheduling

[Task Execution and Scheduling](/docs/CS/Framework/Spring/Task.md)

#### Messages and Integration

- [Spring AMQP](/docs/CS/Framework/Spring/AMQP.md)：RabbitMQ 的 Spring 侧整合。`RabbitTemplate` 发送、`@RabbitListener` 接收、`RabbitAdmin` 声明式拓扑。
- [Spring Integration](/docs/CS/Framework/Spring/Integration.md)：企业集成模式（EIP）实现。用 Message / Channel / Endpoint 三件套把过滤、转换、路由、拆分、聚合编排成流水线，两端用适配器对接外部系统。
- [Spring Batch](/docs/CS/Framework/Spring/Batch.md)：批处理。Job / Step / Chunk 模型 + `JobRepository` 元数据实现断点续跑与防重。
- [Spring Kafka](/docs/CS/Framework/Spring/Kafka.md)：Kafka 客户端整合。`KafkaTemplate` 发送、`@KafkaListener` 消费，容器负责位点提交（`AckMode`）、重试与错误处理（`DefaultErrorHandler` + 死信，或 `@RetryableTopic` 非阻塞重试）；4.0 起支持 Share Consumer 的队列语义。

#### Cache Abstraction

[Cache Abstraction](/docs/CS/Framework/Spring/Cache.md)

### Security

[Spring Security](/docs/CS/Framework/Spring/Security.md) 为 Spring 应用提供认证（Authentication）与授权（Authorization）能力，Servlet 侧基于 Filter 链实现，方法侧基于 AOP 拦截。
其 OAuth2 Client / Resource Server 支持见 [Spring OAuth](/docs/CS/Framework/Spring/OAuth.md)；集群会话共享见 [Spring Session](/docs/CS/Framework/Spring/Session.md)。

#### AI

[Spring AI](/docs/CS/Framework/Spring/AI.md) 将 Spring 生态的可移植性与模块化设计原则带入 AI 应用开发，提供 ChatClient、Advisors、Tool Calling、RAG、MCP 等统一抽象，屏蔽底层模型厂商差异。

### Test

[Testing](/docs/CS/Framework/Spring/Test.md)：TestContext 框架、上下文缓存、事务回滚、MockMvc。

Boot 侧的切片测试与模块化 test starter 见 [Spring Boot 测试](/docs/CS/Framework/Spring_Boot/Test.md)。

`SpringProperties.setProperty(String key, String value)` 可在测试里以编程方式设置 Spring 全局属性（等价于 classpath 根部的 `spring.properties`），例如切换 `spring.test.extension.context.scope`。

## Deploy

### Dockerfile

Boot 4 的基线是 Java 17（推荐 21/25），镜像应选用对应 JDK：

```dockerfile
FROM eclipse-temurin:25-jre
ARG JAR_FILE=target/*.jar
COPY ${JAR_FILE} app.jar
ENTRYPOINT ["java","-jar","/app.jar"]
```

### K8s

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: taco-cloud-deploy
  labels:
    app: taco-cloud
spec:
  replicas: 3
  selector:
    matchLabels:
      app: taco-cloud
  template:
    metadata:
      labels:
        app: taco-cloud
  spec:
    containers:
    - name: taco-cloud-container
      image: tacocloud/tacocloud:latest
```

优雅停机（配合 K8s 的 `preStop` 与 readiness 探针）：

```yaml
server:
  shutdown: graceful
spring:
  lifecycle:
    timeout-per-shutdown-phase: 30s
```

### war

传统容器部署需继承 `SpringBootServletInitializer` 并把内嵌容器依赖标为 `provided`。

## Links

- [Spring 目录索引（按层导航）](/docs/CS/Framework/Spring/README.md)
- [Spring Transaction](/docs/CS/Framework/Spring/Transaction.md)
- [Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md)
- [SPI](/docs/CS/Framework/Spring/SPI.md)
- [Event](/docs/CS/Framework/Spring/Event.md)
- [JPA](/docs/CS/Framework/Spring/JPA.md)


## References

1. [Spring中文网](https://springdoc.cn/)
