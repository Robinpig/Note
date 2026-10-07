## Introduction

Spring Framework 的缓存抽象（见 [Spring Cache](/docs/CS/Framework/Spring/Cache.md)）只定义 `Cache` / `CacheManager` 接口与 `@Cacheable` 那层 AOP，**不提供实际存储**。Boot 的价值就在于：根据 classpath 上出现了哪个缓存库，自动装配一个可用的 `CacheManager`。

触发条件是**必须先用 `@EnableCaching` 打开缓存**——因为这会在容器里注册一个 `CacheAspectSupport` Bean，而 `CacheAutoConfiguration` 的条件正是 `@ConditionalOnBean(CacheAspectSupport.class)`。没有这一行，整套自动配置都不会生效。

```java
@AutoConfiguration(afterName = {
        "org.springframework.boot.data.couchbase.autoconfigure.DataCouchbaseAutoConfiguration",
        "org.springframework.boot.data.redis.autoconfigure.DataRedisAutoConfiguration",
        "org.springframework.boot.hazelcast.autoconfigure.HazelcastAutoConfiguration",
        "org.springframework.boot.hibernate.autoconfigure.HibernateJpaAutoConfiguration" })
@ConditionalOnClass(CacheManager.class)
@ConditionalOnBean(CacheAspectSupport.class)
@ConditionalOnMissingBean(value = CacheManager.class, name = "cacheResolver")
@EnableConfigurationProperties(CacheProperties.class)
@Import({ CacheAutoConfiguration.CacheConfigurationImportSelector.class,
          CacheAutoConfiguration.CacheManagerEntityManagerFactoryDependsOnConfiguration.class })
public final class CacheAutoConfiguration {
}
```

> [!NOTE]
> Boot 4 模块化后有两处搬迁：`CacheAutoConfiguration` 的包名从 `org.springframework.boot.autoconfigure.cache` 改为 **`org.springframework.boot.cache.autoconfigure`**（`CacheManagerCustomizer`、`CacheProperties` 等一并迁移），依赖后置特化类也从 `CacheManagerEntityManagerFactoryDependsOnPostProcessor` 更名为 `CacheManagerEntityManagerFactoryDependsOnConfiguration`。另外注意 `afterName` 用的是**字符串全限定名**而非 class 字面量——这是 Boot 4 模块化的直接产物：自动配置模块之间不再有编译期依赖。

### starter Does Not Contain a Cache Implementation

`spring-boot-starter-cache` 依赖树只有三项：`spring-boot-starter`、自动配置模块 `spring-boot-cache`、`spring-context-support`（`CaffeineCacheManager`、`JCacheCacheManager` 这些实现类的家）。

它**不带任何一种具体缓存库**。想用 Redis 当缓存，工程里还必须单独引 `spring-boot-starter-data-redis`；想用 Caffeine 就要引 Caffeine。

> [!WARNING]
> 这是"配了半天不生效"的高频原因：只引了 starter，classpath 上没有任何第三方缓存库，于是 Boot 回落到默认的 `ConcurrentMapCacheManager`（JVM 内存），本地跑得通、上了集群发现每个实例各缓存各的。**没有任何报错提示你落到了本地 Map**。想知道实际装配了哪个 provider，`/actuator/conditions` 或者让 container 打出 `CacheManager` 的实际类型即可确认。

## Provider Detection Order

容器里没有自定义 `CacheManager`、也没有名为 `cacheResolver` 的 `CacheResolver` 时，Boot 按**固定顺序**检测：

1. **Generic** —— 上下文里存在至少一个 `Cache` Bean 时，把所有这些 Bean 包成一个 Manager
2. **JCache（JSR-107）** —— classpath 上有 `CachingProvider`（EhCache 3、Hazelcast、Infinispan 等）
3. **Hazelcast**
4. **Infinispan**
5. **Couchbase**
6. **Redis**
7. **Caffeine**
8. **Cache2k**
9. **Simple** —— 兜底的 `ConcurrentMapCacheManager`

对应的枚举就是 `CacheType`：

```java
public enum CacheType {
   GENERIC, JCACHE, EHCACHE, HAZELCAST, INFINISPAN,
   COUCHBASE, REDIS, CAFFEINE, SIMPLE, NONE
}
```

> [!NOTE]
> 顺序不是随意排的：**排在前面的优先**。同时引入 JCache 实现与 Caffeine 时，实际用的是 JCache——很可能不是想要的结果。想锁死就显式指定 `spring.cache.type`，别依赖 classpath 巧合。

```yaml
spring:
  cache:
    type: caffeine
    cache-names: users, orders
    caffeine:
      spec: maximumSize=10000,expireAfterWrite=10m
```

`CacheConfigurationImportSelector` 根据 `CacheType` 从一份映射表里挑出对应的 `*CacheConfiguration` 导入，这就是不同 provider 各自装配逻辑的切换开关。

## Simple Fallback

```java
@Configuration(proxyBeanMethods = false)
@ConditionalOnMissingBean(CacheManager.class)
@Conditional(CacheCondition.class)
class SimpleCacheConfiguration {

   @Bean
   ConcurrentMapCacheManager cacheManager(CacheProperties cacheProperties,
         CacheManagerCustomizers cacheManagerCustomizers) {
      ConcurrentMapCacheManager cacheManager = new ConcurrentMapCacheManager();
      List<String> cacheNames = cacheProperties.getCacheNames();
      if (!cacheNames.isEmpty()) {
         cacheManager.setCacheNames(cacheNames);
      }
      return cacheManagerCustomizers.customize(cacheManager);
   }
}
```

官方注释直接点明了它的定位：`SimpleCacheConfiguration` 是 "Simplest cache configuration, usually used as a fallback."——适合起步、本地验证，**不建议用于生产**。它没有任何容量上限与过期策略，缓存只增不减，长时间运行会内存泄漏。

通过 `spring.cache.cache-names` 预设名字可以约束它的缓存范围（Simple provider 下的动态创建会失败），这也是让缓存行为可预测的一个手段。

## Customize CacheManager

```java
@Configuration(proxyBeanMethods = false)
public class MyCacheConfig {

	@Bean
	CacheManagerCustomizer<ConcurrentMapCacheManager> cacheManagerCustomizer() {
		return cacheManager -> cacheManager.setAllowNullValues(false);
	}
}
```

> [!WARNING]
> customizer 的**泛型参数决定了它是否被调用**：上例的 `CacheManagerCustomizer<ConcurrentMapCacheManager>` 只在自动装配出来的是 `ConcurrentMapCacheManager` 时才执行。实际装配成了 Caffeine 的话它会被**完全跳过**，且不会有任何提示。多个 customizer 用 `@Order` 排序。

需要更强的控制力（例如给不同 cache 配不同的 TTL）时，直接自己定义 `CacheManager` Bean——注意这会让 `@ConditionalOnMissingBean(CacheManager.class)` 失效，整套自动配置自动退出，此时 `spring.cache.*` 下的配置**一律不再生效**。

## Annotation Semantics

缓存抽象提供五个核心注解（定义在 [Spring Cache](/docs/CS/Framework/Spring/Cache.md)，Boot 只负责自动装配 provider）：

- `@Cacheable`：方法结果按 key 缓存；命中则直接返回缓存、不执行方法体。支持 `key`、`condition`（缓存前判断）、`unless`（缓存后排除，如 `#result == null`）、`cacheManager`、`cacheResolver`、`sync`。
- `@CachePut`：**总是执行方法体**并把返回值写入缓存（用于"更新后同步缓存"），不读缓存。它与 `@Cacheable` 语义互斥——同一方法上同时标两者时，`@CachePut` 先写、`@Cacheable` 后读，容易踩坑，不要混用。
- `@CacheEvict`：清除缓存。默认在方法**成功返回后**执行；`allEntries=true` 清空整个缓存（批量失效）；`beforeInvocation=true` 改为方法执行前失效（方法抛异常也清）。
- `@Caching`：一个方法上组合多个 `@Cacheable`/`@CachePut`/`@CacheEvict`（同一类型注解不能重复，用 `@Caching` 包一层）。
- `@CacheConfig`：类级注解，统一该类所有缓存操作的 `cacheNames`、`keyGenerator`、`cacheManager`，减少重复配置。

## sync Cache-Breaking Protection and Custom key/cache Parsing

- **`sync = true`**：并发未命中时只放行一个线程回源、其余共享结果，避免缓存击穿（同一 key 被大量并发打到 DB）。限制：仅对**单个缓存**生效、不能配合 `unless`、且只有部分 provider（如 ConcurrentMap、Redis 的事务型实现）真正支持。
- **`keyGenerator`**：实现 `KeyGenerator` 自定义 key 生成策略（如统一加业务前缀、对复杂参数做哈希），用 `keyGenerator = "myKeyGenerator"` 引用。比 `@Cacheable(key = "...")` 的 SpEL 更灵活，但失去可读性，慎用。
- **`cacheResolver`**：实现 `CacheResolver` 动态决定"这次操作落到哪些缓存"，粒度比 `cacheManager` 更细。自定义后 `@ConditionalOnMissingBean(name = "cacheResolver")` 的自动配置会退出。

## Relationship with Transactions

缓存切面的执行时机容易被误解：

- `@Cacheable` 命中时方法体**不执行**，自然不会进事务；未命中时方法执行、事务照常，方法**返回后**才写缓存。
- `@CacheEvict` 默认在方法**成功返回后**清除。如果方法在事务里、且事务**回滚**，默认情况下缓存清除**不会回滚**——即"事务回退了，但缓存已被清掉"，下次读取会回源得到一个回滚前不该存在的值。

> [!WARNING]
> 经典坑：在 `@Transactional` 方法上用 `@CacheEvict`，方法因异常回滚，但缓存已清。若要求"事务提交后才清缓存"，需把清除逻辑移到事务边界之外，或依赖 provider 的事务型缓存支持。反之，`@CachePut` 写入也可能在事务回滚后留下脏缓存。

- 因此**缓存与数据库的一致性**不能靠注解自动保证，跨事务的写后读一致性通常需要把清除放在事务提交之后，或在 service 层手动编排。

## Differentiate TTL by Cache (Redis as Example)

`spring.cache.redis.*` 只能给**所有** Redis 缓存设同一套默认 TTL。要给不同缓存设不同过期时间，需要自定义 `RedisCacheManager`：

```java
@Bean
RedisCacheManager cacheManager(RedisConnectionFactory factory) {
    RedisCacheConfiguration base = RedisCacheConfiguration.defaultCacheConfig()
            .entryTtl(Duration.ofMinutes(10));

    Map<String, RedisCacheConfiguration> per = Map.of(
        "users",  base.entryTtl(Duration.ofHours(1)),
        "orders", base.entryTtl(Duration.ofMinutes(5)));

    return RedisCacheManager.builder(factory)
            .cacheDefaults(base)
            .withInitialCacheConfigurations(per)
            .build();
}
```

一旦自己定义了 `CacheManager` Bean，Boot 的 `CacheAutoConfiguration` 因 `@ConditionalOnMissingBean(CacheManager.class)` 整体退出，`spring.cache.*` 下的统一配置不再生效——TTL 与命名空间全交给上面的代码。

## Several Common Pitfalls

- **`@EnableCaching` 不要加在主应用类上**：官方明确提醒，这会让缓存成为强制特性，跑测试时也不得不装配缓存（很多由此产生的 "No cache named XXX could not be found" 测试报错都源于此）。单独放一个 `@Configuration` 类更干净。
- **自调用失效**：同一个类里的方法调用自己带 `@Cacheable` 的方法，走的是 this 引用而非代理，缓存不生效。这是 Spring AOP 的通用约束，与 [AOP](/docs/CS/Framework/Spring/AOP.md) 里的注意事项同源。
- **Redis 做缓存时的分工**：`spring.data.redis.*` 管**连接**，`spring.cache.*` 管**缓存行为**。连不上 Redis 查前者，缓存的值不对查后者——两摊事不要混在一起排。
- **`null` 值**：默认情况下缓存 `null` 会被当成"不存在"反复回源（Redis 等实现无法区分"值为 null"与"key 不存在"）。确定要缓存空结果时才配 `allowNullValues`。

## Links

- [Spring Cache](/docs/CS/Framework/Spring/Cache.md)
- [Spring Boot](/docs/CS/Framework/Spring_Boot/Spring_Boot.md)
- [AOP](/docs/CS/Framework/Spring/AOP.md)
- [Spring Boot Actuator](/docs/CS/Framework/Spring_Boot/actuator.md)

## References

1. [Spring Boot Reference - Caching](https://docs.spring.io/spring-boot/reference/io/caching.html)
2. [CacheAutoConfiguration Javadoc (4.1)](https://docs.spring.io/spring-boot/4.1/api/java/org/springframework/boot/cache/autoconfigure/CacheAutoConfiguration.html)
