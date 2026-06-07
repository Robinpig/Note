## Introduction

与事务支持类似，[缓存抽象](https://docs.spring.io/spring-framework/docs/current/reference/html/integration.html#cache)允许以最小的代码影响一致地使用各种缓存解决方案。
与 Spring 框架中的其他服务一样，缓存服务是一种抽象（非缓存实现），需要使用实际的存储来缓存数据——即，
抽象让你不必编写缓存逻辑，但不提供实际的数据存储。
该抽象由 `org.springframework.cache.Cache` 和 `org.springframework.cache.CacheManager` 接口实现。

Spring 提供了该抽象的几种实现：[JDK java.util.concurrent.ConcurrentMap](/docs/CS/Java/JDK/Collection/Map.md?id=ConcurrentHashMap) 缓存、Ehcache 2.x、Gemfire 缓存、Caffeine 和符合 JSR-107 的缓存（例如 Ehcache 3.x）。

要使用缓存抽象，你需要处理两个方面：

- 缓存声明：确定需要缓存的方法及其策略。
- 缓存配置：存储数据和读取数据的后端缓存。

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

Cacheable 不支持设置过期时间。

许多扩展通过覆盖 KeyGenerator 和 CacheManager 来解析键和获取时间。

## Interceptor

用于声明式缓存管理的 AOP Alliance MethodInterceptor，使用通用的 Spring 缓存基础设施（org.springframework.cache.Cache）。
CacheInterceptor 简单地在正确的顺序中调用相关的超类方法。
CacheInterceptors 是线程安全的。

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

实现 Cache。

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

## Summary

TODO: Cache Consistency

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
