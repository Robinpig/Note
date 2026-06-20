## Introduction

Similar to the transaction support, the [caching abstraction](https://docs.spring.io/spring-framework/docs/current/reference/html/integration.html#cache) allows consistent use of various caching solutions with minimal impact on the code.
As with other services in the Spring Framework, the caching service is an abstraction (not a cache implementation) and requires the use of actual storage to store the cache data — that is, 
the abstraction frees you from having to write the caching logic but does not provide the actual data store. 
This abstraction is materialized by the `org.springframework.cache.Cache` and `org.springframework.cache.CacheManager` interfaces.

Spring provides a few implementations of that abstraction: [JDK java.util.concurrent.ConcurrentMap](/docs/CS/Java/JDK/Collection/Map.md?id=ConcurrentHashMap) based caches, Ehcache 2.x, Gemfire cache, Caffeine, and JSR-107 compliant caches (such as Ehcache 3.x).

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

## Summary

TODO: Cache Consistency


## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)