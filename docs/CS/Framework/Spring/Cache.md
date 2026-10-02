## Introduction

Similar to the transaction support, the [caching abstraction](https://docs.spring.io/spring-framework/docs/current/reference/html/integration.html#cache) allows consistent use of various caching solutions with minimal impact on the code.
As with other services in the Spring Framework, the caching service is an abstraction (not a cache implementation) and requires the use of actual storage to store the cache data — that is, 
the abstraction frees you from having to write the caching logic but does not provide the actual data store. 
This abstraction is materialized by the `org.springframework.cache.Cache` and `org.springframework.cache.CacheManager` interfaces.

Spring provides a few implementations of that abstraction: [JDK java.util.concurrent.ConcurrentMap](/docs/CS/Java/JDK/Collection/Map.md?id=concurrenthashmap) based caches, Ehcache 2.x, Gemfire cache, Caffeine, and JSR-107 compliant caches (such as Ehcache 3.x).

To use the cache abstraction, you need to take care of two aspects:

- Caching declaration: Identify the methods that need to be cached and their policy.
- Cache configuration: The backing cache where the data is stored and from which it is read.



## Quick Start

### EnableCaching

```java
package org.springframework.cache.annotation;

@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
@Documented
@Import(CachingConfigurationSelector.class)
public @interface EnableCaching {
    
   boolean proxyTargetClass() default false;

   AdviceMode mode() default AdviceMode.PROXY;

   int order() default Ordered.LOWEST_PRECEDENCE;

}
```




### CacheManager



```java
public interface CacheManager {
    
   @Nullable
   Cache getCache(String name);

   Collection<String> getCacheNames();

}

public abstract class AbstractCacheManager implements CacheManager, InitializingBean {

    private final ConcurrentMap<String, Cache> cacheMap = new ConcurrentHashMap<>(16);

    private volatile Set<String> cacheNames = Collections.emptySet();

    // Early cache initialization on startup

    @Override
    public void afterPropertiesSet() {
        initializeCaches();
    }
    
    public void initializeCaches() {
        Collection<? extends Cache> caches = loadCaches();

        synchronized (this.cacheMap) {
            this.cacheNames = Collections.emptySet();
            this.cacheMap.clear();
            Set<String> cacheNames = new LinkedHashSet<>(caches.size());
            for (Cache cache : caches) {
                String name = cache.getName();
                this.cacheMap.put(name, decorateCache(cache));
                cacheNames.add(name);
            }
            this.cacheNames = Collections.unmodifiableSet(cacheNames);
        }
    }
}

```
#### getCache

```java
public abstract class AbstractCacheManager implements CacheManager, InitializingBean {
    @Override
    @Nullable
    public Cache getCache(String name) {
        // Quick check for existing cache...
        Cache cache = this.cacheMap.get(name);
        if (cache != null) {
            return cache;
        }

        // The provider may support on-demand cache creation...
        Cache missingCache = getMissingCache(name);
        if (missingCache != null) {
            // Fully synchronize now for missing cache registration
            synchronized (this.cacheMap) {
                cache = this.cacheMap.get(name);
                if (cache == null) {
                    cache = decorateCache(missingCache);
                    this.cacheMap.put(name, cache);
                    updateCacheNames(name);
                }
            }
        }
        return cache;
    }
}
```

### Cacheable

Cacheable not support to set expire time.

Many extensions resolve keys and get time by override the KeyGenerator and CacheManger.

### 注解声明式缓存

Spring 提供五个缓存注解：

| 注解 | 作用 |
|---|---|
| `@Cacheable` | 方法执行前查缓存，命中则直接返回；未命中才执行方法并缓存结果 |
| `@CachePut` | **始终执行方法**，并把结果放入缓存，用于缓存更新，不优化方法调用路径 |
| `@CacheEvict` | 触发缓存回收，可按 key 或清空整个 cache |
| `@Caching` | 在方法上叠加多个缓存操作（多个 `@Cacheable`/`@CacheEvict`） |
| `@CacheConfig` | 类级别抽取公共设置（cacheNames、keyGenerator、cacheManager） |

`@Cacheable` 可以声明多个 cache 名，执行方法前会逐个检查，任一命中即返回，其余缓存也会被补上该值：

```java
@Cacheable({"books", "isbns"})
public Book findBook(ISBN isbn) { ... }
```

#### Key 生成

默认的 `SimpleKeyGenerator` 规则：无参 → `SimpleKey.EMPTY`；单参 → 该参数本身；多参 → 包含全部参数的 `SimpleKey`。参数需要有正确的 `hashCode()`/`equals()`。

多参数但只有部分适合做缓存 key 时，用 SpEL 显式指定：

```java
@Cacheable(cacheNames = "books", key = "#isbn")
public Book findBook(ISBN isbn, boolean checkWarehouse, boolean includeUsed) { ... }

@Cacheable(cacheNames = "books", key = "#isbn.rawNumber")
public Book findBook(ISBN isbn) { ... }
```

也可以实现 `org.springframework.cache.interceptor.KeyGenerator` 并通过 `keyGenerator = "myKeyGenerator"` 指定。注意 `key` 与 `keyGenerator` 互斥，同时设置会抛异常。

#### 条件缓存

- `condition`：方法执行**前**求值，为 false 则完全不走缓存（既不查也不存）。
- `unless`：方法执行**后**求值（可用 `#result`），为 true 则不缓存本次结果。

```java
@Cacheable(cacheNames = "book", key = "#name",
           condition = "#name.length() < 32", unless = "#result.hardback")
public Book findBook(String name) { ... }
```

`#result` 指向业务实体本身而非 `Optional` 包装器；返回值可能为 null 时用安全导航 `#result?.field`。常用 SpEL 上下文还有 `#root.methodName`、`#root.target`、`#root.args[0]`、`#root.caches[0].name`。

#### 同步加载

默认缓存抽象不加锁，并发下同一 key 可能被多个线程重复计算。`sync = true` 让底层 Cache 提供方在计算期间锁定该条目（核心框架自带的 CacheManager 均支持）：

```java
@Cacheable(cacheNames = "foos", sync = true)
public Foo executeExpensiveOperation(String id) { ... }
```

#### CachePut 与 CacheEvict 的注意点

- 不要在同一方法上混用 `@CachePut` 与 `@Cacheable`：后者会跳过方法执行，前者强制执行，语义冲突。
- `@CacheEvict(allEntries = true)` 一次清空整个缓存区，此时指定的 key 会被忽略；`beforeInvocation = true` 让回收发生在方法执行之前（默认成功执行后才回收，方法被缓存跳过或抛异常则不回收）。`void` 方法可以配合 `@CacheEvict` 使用（只作触发器），但不能配 `@Cacheable`。

### JCache (JSR-107)

Spring 也支持标准 JSR-107 注解（`@CacheResult`、`@CachePut`、`@CacheRemove`、`@CacheKey` 等），通过 `@EnableCaching` 自动启用，语义与 Spring 原生注解相近但不完全相同（如 JCache 没有 `sync`，key 用 `@CacheKey` 标注参数）。

## Interceptor


AOP Alliance MethodInterceptor for declarative cache management using the common Spring caching infrastructure (org.springframework.cache.Cache).
CacheInterceptor simply calls the relevant superclass methods in the correct order.
CacheInterceptors are thread-safe.

```java
public class CacheInterceptor extends CacheAspectSupport implements MethodInterceptor, Serializable {

	@Override
	@Nullable
	public Object invoke(final MethodInvocation invocation) throws Throwable {
		Method method = invocation.getMethod();

		CacheOperationInvoker aopAllianceInvoker = () -> {
			try {
				return invocation.proceed();
			}
			catch (Throwable ex) {
				throw new CacheOperationInvoker.ThrowableWrapper(ex);
			}
		};

		try {
			return execute(aopAllianceInvoker, invocation.getThis(), method, invocation.getArguments());
		}
		catch (CacheOperationInvoker.ThrowableWrapper th) {
			throw th.getOriginal();
		}
	}

    @Nullable
    protected Object execute(CacheOperationInvoker invoker, Object target, Method method, Object[] args) {
        // Check whether aspect is enabled (to cope with cases where the AJ is pulled in automatically)
        if (this.initialized) {
            Class<?> targetClass = getTargetClass(target);
            CacheOperationSource cacheOperationSource = getCacheOperationSource();
            if (cacheOperationSource != null) {
                Collection<CacheOperation> operations = cacheOperationSource.getCacheOperations(method, targetClass);
                if (!CollectionUtils.isEmpty(operations)) {
                    return execute(invoker, method,
                            new CacheOperationContexts(operations, method, args, target, targetClass));
                }
            }
        }

        return invoker.invoke();
    }

    @Nullable
    private Object execute(final CacheOperationInvoker invoker, Method method, CacheOperationContexts contexts) {
        // Special handling of synchronized invocation
        if (contexts.isSynchronized()) {
            CacheOperationContext context = contexts.get(CacheableOperation.class).iterator().next();
            if (isConditionPassing(context, CacheOperationExpressionEvaluator.NO_RESULT)) {
                Object key = generateKey(context, CacheOperationExpressionEvaluator.NO_RESULT);
                Cache cache = context.getCaches().iterator().next();
                try {
                    return wrapCacheValue(method, handleSynchronizedGet(invoker, key, cache));
                }
                catch (Cache.ValueRetrievalException ex) {
                    // Directly propagate ThrowableWrapper from the invoker,
                    // or potentially also an IllegalArgumentException etc.
                    ReflectionUtils.rethrowRuntimeException(ex.getCause());
                }
            }
            else {
                // No caching required, only call the underlying method
                return invokeOperation(invoker);
            }
        }


        // Process any early evictions
        processCacheEvicts(contexts.get(CacheEvictOperation.class), true,
                CacheOperationExpressionEvaluator.NO_RESULT);

        // Check if we have a cached item matching the conditions
        Cache.ValueWrapper cacheHit = findCachedItem(contexts.get(CacheableOperation.class));

        // Collect puts from any @Cacheable miss, if no cached item is found
        List<CachePutRequest> cachePutRequests = new LinkedList<>();
        if (cacheHit == null) {
            collectPutRequests(contexts.get(CacheableOperation.class),
                    CacheOperationExpressionEvaluator.NO_RESULT, cachePutRequests);
        }

        Object cacheValue;
        Object returnValue;

        if (cacheHit != null && !hasCachePut(contexts)) {
            // If there are no put requests, just use the cache hit
            cacheValue = cacheHit.get();
            returnValue = wrapCacheValue(method, cacheValue);
        }
        else {
            // Invoke the method if we don't have a cache hit
            returnValue = invokeOperation(invoker);
            cacheValue = unwrapReturnValue(returnValue);
        }

        // Collect any explicit @CachePuts
        collectPutRequests(contexts.get(CachePutOperation.class), cacheValue, cachePutRequests);

        // Process any collected put requests, either from @CachePut or a @Cacheable miss
        for (CachePutRequest cachePutRequest : cachePutRequests) {
            cachePutRequest.apply(cacheValue);
        }

        // Process any late evictions
        processCacheEvicts(contexts.get(CacheEvictOperation.class), false, cacheValue);

        return returnValue;
    }
}
```


### Cache

Implement Cache.

```java
public interface Cache {
    
   String getName();

   Object getNativeCache();

   @Nullable
   <T> T get(Object key, @Nullable Class<T> type);
   
   void put(Object key, @Nullable Object value);

   @Nullable
   default ValueWrapper putIfAbsent(Object key, @Nullable Object value) {
      ValueWrapper existingValue = get(key);
      if (existingValue == null) {
         put(key, value);
      }
      return existingValue;
   }

   void evict(Object key);

   default boolean evictIfPresent(Object key) {
      evict(key);
      return false;
   }

   void clear();

   default boolean invalidate() {
      clear();
      return false;
   }
}
```

## Storage Backends

缓存抽象本身不提供存储，需要配置具体的 `CacheManager`：

| 后端 | 说明 |
|---|---|
| JDK `ConcurrentMap` | `ConcurrentMapCacheManager`，内存 Map，无 TTL/淘汰，仅适合开发测试 |
| [Caffeine](/docs/CS/Java/JDK/Collection/Map.md) | Guava Cache 的 Java 8+ 继任者，高性能、支持大小/时间/引用淘汰，生产默认选择 |
| Ehcache 2.x / 3.x | 2.x 有专用集成；3.x 走 JSR-107 |
| JSR-107 兼容实现 | 符合 JCache 标准的任意 provider（Ehcache 3、Hazelcast、Infinispan 等） |
| GemFire / 分布式缓存 | 适合多节点共享缓存的场景 |

Spring Boot 下只要引入对应 starter 并配 `spring.cache.type`/`spring.cache.cache-names` 即可自动装配。

> 抽象不为多线程/多进程做特殊处理，一致性由具体实现负责。多进程部署时，要么接受各节点独立副本，要么配置额外的传播/失效机制（或直接用分布式缓存）。经典的 get-if-absent-then-put 流程默认无锁，可能并发加载同一 key；需要防击穿用上面提到的 `sync = true`。

关于 TTL/TTI/淘汰策略：Spring 抽象不提供统一 API，这些特性由具体后端配置（如 Caffeine spec、Ehcache XML）。

## Summary

TODO: Cache Consistency


## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [Redis](/docs/CS/DB/Redis/Redis.md)
- [Task](/docs/CS/Framework/Spring/Task.md)

## References

- [Spring Framework Reference - Cache Abstraction](https://docs.spring.io/spring-framework/reference/integration/cache.html)
- [JCache (JSR-107)](https://www.jcp.org/en/jsr/detail?id=107)
- [阿里云 SCA 学习站 - 缓存抽象](https://sca.aliyun.com/learn/spring/integration/cache/)
