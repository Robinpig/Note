## Introduction

[Spring Framework](https://spring.io/projects/spring-framework) 为*现代基于 Java 的企业级应用*提供了全面的编程和配置模型——可在任何部署平台上使用。
它使 Java 编程对每个人都更快、更简单、更安全。
Spring 专注于速度、简洁和生产力，使其成为全球最流行的 Java 框架。

## Architecture

Spring 的核心提供了一个*容器*，通常称为 *Spring 应用上下文*，用于创建和管理应用组件。
这些组件（或称为 beans）在 Spring 应用上下文中被装配在一起，构成一个完整的应用。

装配 beans 的行为基于一种称为 *Dependency Injection*（依赖注入，DI）的模式。
在依赖注入的应用中，组件不需要创建和维护其所依赖的其他 bean 的生命周期，而是依赖一个独立的实体（容器）来创建和维护所有组件，并将这些组件注入到需要它们的 bean 中。
这通常通过构造函数参数或属性访问器方法来完成。

历史上，指导 Spring 应用上下文装配 beans 的方式是使用一个或多个 XML 文件来描述组件及其与其他组件的关联关系。
然而，在较新版本的 Spring 中，基于 Java 的配置更为常见。

基于 Java 的配置相比 XML 配置有几个优点，包括更强的类型安全性和更好的重构支持。
即便如此，只有当 Spring 无法自动配置组件时，才需要使用 Java 或 XML 进行显式配置。

自动配置源于 Spring 的 autowiring（自动装配）和 component scanning（组件扫描）技术。
通过组件扫描，Spring 可以自动从应用的 classpath 发现组件，并将其创建为 Spring 应用上下文中的 beans。
通过自动装配，Spring 自动将组件所依赖的其他 bean 注入到这些组件中。

随着 [Spring Boot](/docs/CS/Framework/Spring_Boot/Spring_Boot.md) 的引入，自动配置已远远超出了组件扫描和自动装配的范畴。
Spring Boot 是 Spring Framework 的扩展，提供了多项生产力增强功能。
其中最著名的增强功能是自动配置，Spring Boot 可以根据 classpath、环境变量和其他因素中的条目，合理推测需要配置和装配哪些组件。

### Core

其中最重要的是 Spring Framework 的 [Inversion of Control (IoC)](/docs/CS/Framework/Spring/IoC.md) 容器。
在对 Spring Framework 的 IoC 容器进行全面介绍之后，紧接着是对 Spring 的 [Aspect-Oriented Programming (AOP)](/docs/CS/Framework/Spring/AOP.md) 技术的全面覆盖。

[AOT](/docs/CS/Framework/Spring/AOT.md) 处理可用于提前优化应用，通常用于使用 GraalVM 进行原生镜像部署。

### Web

Spring 带有一个强大的 Web 框架，称为 [Spring MVC](/docs/CS/Framework/Spring/MVC.md)。
Spring MVC 的核心是 *controller* 的概念，它是一个处理请求并返回信息的类。
对于面向浏览器的应用，控制器通过可选地填充模型数据并将请求传递给视图来生成返回给浏览器的 HTML。

[Spring WebFlux](/docs/CS/Framework/Spring/webflux.md) Web 框架。

### Data Access

Spring Data 的使命是在保留底层数据存储特殊性的同时，为数据访问提供熟悉且一致的基于 Spring 的编程模型。

它使数据访问技术、关系型和非关系型数据库、map-reduce 框架以及基于云的数据服务的使���变得更加容易。
这是一个包含许多特定于某个数据库的子项目的总括项目。

- [Spring Data Commons](https://github.com/spring-projects/spring-data-commons) - 支撑每个 Spring Data 模块的核心 Spring 概念。
- [Spring Data JDBC](https://spring.io/projects/spring-data-jdbc) - 用于 JDBC 的 Spring Data 仓库支持。
- [Spring Data R2DBC](https://spring.io/projects/spring-data-r2dbc) - 用于 R2DBC 的 Spring Data 仓库支持。
- [Spring Data JPA](https://spring.io/projects/spring-data-jpa) - 用于 JPA 的 Spring Data 仓库支持。
- [Spring Data KeyValue](https://github.com/spring-projects/spring-data-keyvalue) - 基于 `Map` 的仓库和 SPI，用于轻松构建键值存储的 Spring Data 模块。
- [Spring Data LDAP](https://spring.io/projects/spring-data-ldap) - 用于 [Spring LDAP](https://github.com/spring-projects/spring-ldap) 的 Spring Data 仓库支持。
- [Spring Data MongoDB](https://spring.io/projects/spring-data-mongodb) - 基于 Spring 的 MongoDB 对象文档支持和仓库。
- [Spring Data Redis](https://spring.io/projects/spring-data-redis) - 在 Spring 应用中轻松配置和访问 Redis。
- [Spring Data REST](https://spring.io/projects/spring-data-rest) - 将 Spring Data 仓库导出为超媒体驱动的 RESTful 资源。
- [Spring Data for Apache Cassandra](https://spring.io/projects/spring-data-cassandra) - 为 Apache Cassandra 或大规模、高可用、面向数据的 Spring 应用提供轻松配置和访问。
- [Spring Data for Apache Geode](https://spring.io/projects/spring-data-geode) - 为 Apache Geode 提供轻松配置和访问，用于高一致性、低延迟、面向数据的 Spring 应用。

### Integration

Spring Framework 与多种技术的集成。

#### REST Clients

Spring Framework 提供了两种调用 REST 端点的选择：

- RestTemplate：原始的 Spring REST 客户端，具有同步的模板方法 API。
- WebClient：一种非阻塞、响应式替代方案，支持同步和异步以及流式场景。

可用于自定义从 RestTemplate 发送的 ClientHttpRequest 的回调接口。
```java
@FunctionalInterface
public interface RestTemplateRequestCustomizer<T extends ClientHttpRequest> {
	void customize(T request);

}
```

#### Task Execution and Scheduling

[Task Execution and Scheduling](/docs/CS/Framework/Spring/Task.md)

#### Cache Abstraction

[Cache Abstraction](/docs/CS/Framework/Spring/Cache.md)

[Spring Security](/docs/CS/Framework/Spring/Security.md)

#### AI

[Spring AI](/docs/CS/Framework/Spring/AI.md)

### Test

[Testing](/docs/CS/Framework/Spring/Test.md)

SpringProperties

`SpringProperties.setProperty(String key, String value)`

## Deploy

### Dockerfile

```dockerfile
FROM openjdk:11.0.12-jre
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

server:
shutdown: graceful

### war

## Links

- [Spring Boot](/docs/CS/Framework/Spring_Boot/Spring_Boot.md)
- [Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md)

## References

1. [Spring中文网](https://springdoc.cn/)
