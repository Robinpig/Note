## Introduction

Spring Session 解决的是分布式 / 集群部署下的**会话共享**问题，并把 session 管理从 Servlet 容器（Tomcat、Jetty 的内存 `HttpSession`）中解耦出来：
"Spring Session makes it trivial to support clustered sessions without being tied to an application container specific solution."

在单体、单实例时代，`HttpSession` 由 Web 容器保存在本地内存里即可。一旦一个服务横向扩成多个实例、由负载均衡器分发请求，就必须解决“下一次请求落到另一台机器时还能不能读到同一份 session”的问题。

## Cluster Session Strategies

业界常见三种集群会话方案：

| 方案 | 做法 | 缺点 |
| ---- | ---- | ---- |
| Sticky Session（会话保持） | 负载均衡器按 JSESSIONID / cookie 把同一用户始终路由到同一实例 | 实例宕机会话即丢；负载不均；扩缩容/迁移不友好 |
| Session Replication（会话复制） | 容器之间互相同步 session（如 Tomcat cluster） | 网络与内存开销随实例数平方级增长，规模一大不可行 |
| Centralized Session（集中式存储） | session 统一存到 Redis / JDBC / Hazelcast 等外部存储，所有实例共享 | 多一次外部存储访问；这正是 Spring Session 的方案 |

集中式存储兼顾了水平扩展与可靠性，是微服务主流做法。

## Principle: Filter + Request Wrapper

Spring Session 的核心机制是 Servlet 规范里的 **Filter 拦截 + 请求包装（装饰器模式）**：

1. `DelegatingFilterProxy` / `springSessionRepositoryFilter` 拦截所有请求。
2. 它把原始 `HttpServletRequest` 包装成 `SessionRepositoryRequestWrapper`。
3. 包装类重写了 `getSession()`：返回的不是容器的 `HttpSession`，而是 Spring Session 自己的 `HttpSessionWrapper`，背后由 `SessionRepository` 从 Redis 等存储读写。

于是业务代码照常调用 `request.getSession()`，完全无感知，但 session 的存取已经“偷梁换柱”地交给了 Spring 和外部存储，与具体 Web 容器无关。

响应时通过 `SessionCookieHttpSessionIdResolver`（默认 cookie 名 `SESSION`）把 session id 写回客户端。

## Storage

Spring Session 按底层存储提供不同模块：

- **Spring Session Redis**（最常用）：`spring-session-data-redis`，用 Redis hash/string 存 session，支持过期、`@EnableRedisHttpSession`，可配置 Redis 的 key 命名空间与 flush 模式。
- **Spring Session JDBC**：`spring-session-jdbc`，存入关系库表（`SPRING_SESSION` / `SPRING_SESSION_ATTRIBUTES`）。
- **Spring Session Hazelcast / MongoDB** 等：对应 `SessionRepository` 实现。

Spring Boot 自动配置下，引入 `spring-session-data-redis` 并提供 `RedisConnectionFactory` 后，设置 store-type 即可启用：

```yaml
spring:
  session:
    store-type: redis
    timeout: 30m
  data:
    redis:
      host: localhost
      port: 6379
```

### Redis Session 结构要点

- session 以 `spring:session:sessions:<id>` 存储，属性序列化到 hash；
- 另用一个有序集合记录过期时间，后台任务清理，因此 TTL 不是完全精确依赖 Redis key 过期；
- 默认 JDK 序列化，跨语言/可读性差，可切换为 `GenericJackson2JsonRedisSerializer`（注意需为多态类型保留 class 信息）。

## Spring Session 与安全

Spring Security 默认基于 `HttpSession` 保存 `SecurityContext`，接入 Spring Session 后登录态也随之集中化，天然支持集群下的登录共享。
还可以用 Spring Session 做 WebSocket（`WebSocket Session`）与 HTTP session 的关联，让长连接复用同一份会话。

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [Spring Security](/docs/CS/Framework/Spring/Security.md)
- [Spring Cache](/docs/CS/Framework/Spring/Cache.md)
- [Spring Boot](/docs/CS/Framework/Spring_Boot/Spring_Boot.md)

## References

1. [Spring Session Reference](https://docs.spring.io/spring-session/reference/)
2. [Spring Session - Redis](https://docs.spring.io/spring-session/reference/guides/boot-redis.html)
