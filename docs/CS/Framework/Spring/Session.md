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

1. `DelegatingFilterProxy`（bean 名 `springSessionRepositoryFilter`）拦截所有请求，订单足够靠前以保证先于业务读写 session 执行。
2. 它把原始 `HttpServletRequest` 包装成 `SessionRepositoryRequestWrapper`，把响应包装成 `SessionRepositoryResponseWrapper`。
3. 包装类重写了 `getSession()`：返回的不是容器的 `HttpSession`，而是 Spring Session 自己的 `HttpSessionAdapter`，背后由 `SessionRepository` 从 Redis 等存储读写。

于是业务代码照常调用 `request.getSession()`，完全无感知，但 session 的存取已经"偷梁换柱"地交给了 Spring 和外部存储，与具体 Web 容器无关。

响应时用 `HttpSessionIdResolver` 把 session id 写回客户端，默认实现是 cookie（名为 `SESSION`）。

### 写回时机：flushMode 与 saveMode

两个容易混淆的配置，管的是"什么时候把 session 写回存储"：

| 配置 | 取值 | 含义 |
| ---- | ---- | ---- |
| `flushMode` | `ON_SAVE`（默认） | 请求结束前才一次性写回。中途改了 session 不写 |
| | `IMMEDIATE` | 每次 `setAttribute` 立即写回。可靠但写放大明显 |
| `saveMode` | `ON_SET_ATTRIBUTE`（默认） | 属性发生变化才写 |
| | `ON_GET_ATTRIBUTE` | 连读取都触发写——用于需要刷新过期时间的场景（如登录后要看活跃度） |
| | `ALWAYS` | 无条件写 |

> [!WARNING]
> 典型的静默 Bug 是**分布式下 session 属性更新丢失**：两个请求并发修改同一 session，默认的 `ON_SAVE` 让后完成的那次整体覆盖前者。这类问题不会报错，只会表现为"偶发的登录态/购物车内容回滚"。session 一旦承担写状态，就要按共享可变状态来审视，必要时换成把状态放到 DB / Redis 自己维护的数据结构里。

### Session ID 的传递载体

默认用 cookie（`CookieHttpSessionIdResolver`）。移动端 / 前后端分离场景常用 Header：

```java
@Bean
HttpSessionIdResolver httpSessionIdResolver() {
    return HeaderHttpSessionIdResolver.xAuthToken();  // 头名 X-Auth-Token
}
```

同理也支持自定义 cookie 名、SameSite、domain。注意改成 Header 之后，**浏览器不再自动携带**，所有客户端代码必须显式带上这个头。

## Storage

Spring Session 按底层存储提供不同模块，Boot 下由 `spring.session.store-type` 选择：

| store-type | 模块 | 说明 |
| ---- | ---- | ---- |
| `redis` | `spring-session-data-redis` | 最常用。`RedisIndexedSessionRepository`（支持按 principal 查询该用户的所有 session）或轻量的 `RedisSessionRepository` |
| `jdbc` | `spring-session-jdbc` | 表 `SPRING_SESSION` / `SPRING_SESSION_ATTRIBUTES`，适合已有关系库、不想多引入 Redis 的系统 |
| `hazelcast` | `spring-session-hazelcast` | 内存网格，本地进程性访问快 |
| `mongodb` | `spring-session-data-mongodb` | 文档型存储 |
| `none` | — | 关闭 Spring Session，退回容器原生 session |

```yaml
spring:
  session:
    store-type: redis
    timeout: 30m
    redis:
      flush-mode: on_save
      save-mode: on_set_attribute
      namespace: spring:session       # Redis key 前缀
  data:
    redis:
      host: localhost
      port: 6379
```

> [!NOTE]
> `RedisIndexedSessionRepository` 依赖 Redis **keyspace notification** 做过期事件清理（另有一个 key 维护"用户 → sessionId"索引）。Redis 侧若禁用该特性（`notify-keyspace-events` 未开启），过期 session 不会被及时清理，表现为 Redis 里 key 持续堆积。这在托管 Redis（云厂商默认常关）上很常见。

### Redis Session 结构要点

- session 以 `spring:session:sessions:<id>` 存储，属性序列化到 hash；
- 另用一个有序集合记录过期时间，后台任务清理，因此 TTL 不是完全精确依赖 Redis key 过期；
- session id 本身是 base64 编码的 UUID，写到 cookie 里要注意别让网关/中间件截断。

### 序列化选型

默认 **JDK 序列化**：同版本应用集群可用，但跨语言读不了、类名或字段变更会导致反序列化失败、且二进制不可读难以排障。

推荐换成 JSON，只需注册一个**名字必须叫 `springSessionDefaultRedisSerializer`** 的 Bean（这个名字是框架约定的查找键，改名无效）：

```java
@Bean
RedisSerializer<Object> springSessionDefaultRedisSerializer() {
    return RedisSerializer.json();   // Jackson + 开启默认类型信息
}
```

> [!WARNING]
> **Jackson 3 迁移要点**：Boot 4 一代默认用 Jackson 3（`tools.jackson`），Spring Data Redis 4.0 起已把带 "2" 的序列化器标为废弃（`@Deprecated(since="4.0", forRemoval=true)`），对应关系为 `GenericJackson2JsonRedisSerializer` → **`GenericJacksonJsonRedisSerializer`**、`Jackson2JsonRedisSerializer` → **`JacksonJsonRedisSerializer`**。
>
> 换的时候要留意两点：一是 **JSON 反序列化需要类型信息**，默认类型信息未开启时会把对象还原成 `LinkedHashMap`，取字段时抛 `ClassCastException`；二是已有 Redis 里的存量会话是按旧格式写的，**灰度期必须兼容读写，否则升级瞬间所有在线用户被踢下线**。稳妥做法是先用新的 namespace 双写一段时间，或直接接受一次全量登出。

## Spring Session 与安全

Spring Security 默认基于 `HttpSession` 保存 `SecurityContext`，接入 Spring Session 后登录态也随之集中化，天然支持集群下的登录共享。

### 会话创建策略

```java
http.sessionManagement(session -> session
        .sessionCreationPolicy(SessionCreationPolicy.STATELESS));
```

四个取值：`ALWAYS` / `IF_REQUIRED`（默认，需要时才建）/ `NEVER`（不主动建，有则用）/ `STATELESS`（既不建也不用，会跳过 `HttpSessionSecurityContextRepository` 等会话相关 filter）。

注意这套策略**只约束 Spring Security 自己**，不约束业务代码——应用照样可以 `getSession()` 创建会话。`STATELESS` 配 JWT/OAuth2 时常见，此时 Spring Session 基本无用武之地。

### 并发会话控制

限制同一账号同时在线的会话数：

```java
http.sessionManagement(session -> session
        .sessionConcurrency(concurrency -> concurrency
                .maximumSessions(1)
                .maxSessionsPreventsLogin(true)     // 达到上限时拒绝新登录（默认 false：踢掉旧的）
                .expiredUrl("/login?expired")));
```

要点：

- 必须注册 `HttpSessionEventPublisher`，否则 session 销毁时 `SessionRegistry` 收不到通知，计数只增不减——表现为"用着用着就登不上去了，且重启前无法恢复"。
- 默认的 `SessionRegistryImpl` 是**内存实现**。集群下每个实例各存一份计数，`maximumSessions(1)` 在 N 个实例上实际允许 N 个会话。要真正跨实例生效必须换成基于 Spring Session / Redis 的存储实现。
- `maxSessionsPreventsLogin` 为 false（默认）时新登录会踢掉旧会话，旧会话的用户下次请求被导向 `expiredUrl`。

> [!NOTE]
> Security 6.5 起提供了函数式重载 `maximumSessions(SessionLimit)`，可以按 authentication 动态返回上限（例如管理员不限、普通用户限 1），替代过去只能写死整数的做法。

### WebSocket 关联

Spring Session 还能把 HTTP session 与 WebSocket 会话关联起来，让长连接复用同一份登录态。做法是让 `WebSocketHandshakeInterceptor` 在握手阶段从 HTTP session 取出认证信息，效果是 STOMP 的 `@MessageMapping` 方法里能拿到同一个 Principal。

这里有个容易忽略的安全点：WebSocket **握手走 HTTP**，因此能用 cookie 带 session；一旦握手完成进入消息阶段，就不再依赖 cookie，所以**鉴权必须在握手时做完**，事后没有补票机会。详见 [WebSocket 与 STOMP](/docs/CS/Framework/Spring/WebSocket.md)。

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [Spring Security](/docs/CS/Framework/Spring/Security.md)
- [Spring Boot](/docs/CS/Framework/Spring_Boot/Spring_Boot.md)
- [Spring Cache](/docs/CS/Framework/Spring/Cache.md)

## References

1. [Spring Session Reference](https://docs.spring.io/spring-session/reference/)
2. [Spring Session - Redis](https://docs.spring.io/spring-session/reference/guides/boot-redis.html)
