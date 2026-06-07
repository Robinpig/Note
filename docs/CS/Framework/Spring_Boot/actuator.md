
## Introduction

spring-boot-actuator 模块提供了 Spring Boot 的所有生产就绪功能。
启用这些功能的推荐方式是添加对 `spring-boot-starter-actuator` Starter 的依赖。

```groovy
dependencies {
    implementation 'org.springframework.boot:spring-boot-starter-actuator'
}
```




Actuator 端点让你监控应用并与之交互。
每个端点都可以启用或禁用，并通过 HTTP 或 JMX 暴露（使其可远程访问）。
端点只有在同时启用和暴露时才被视为可用。内置端点仅在可用时才会被自动配置。

要更改暴露哪些端点，请使用以下特定于技术的 include 和 exclude 属性。
include 属性列出了要暴露的端点的 ID。
* 可用于选择所有端点。
```properties
management.endpoints.web.exposure.include=*
```





注入 `HttpTraceRepository`，从 `/actuator/httptrace` 获取 cookie

```java
@Bean
@ConditionalOnMissingBean(HttpTraceRepository.class)
public HttpTraceRepository traceRepository(){
    return new InMemoryHttpTraceRepository();

}
```



从 `/actuator/env` 获取数据源 URL

从 `/actuator/heapdump` 获取所有信息

```
jhat heapdump
```

数据源位于 `org.springframework.boot.autoconfigure.jdbc.DataSourceProperties` 实例中
