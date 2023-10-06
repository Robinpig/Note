## Introduction



Auto-configuration for the cache abstraction. Creates a CacheManager if necessary when caching is enabled via `@EnableCaching`.
Cache store can be auto-detected or specified explicitly via configuration.

```java
package org.springframework.boot.autoconfigure.cache;

@Configuration(proxyBeanMethods = false)
@ConditionalOnClass(CacheManager.class)
@ConditionalOnBean(CacheAspectSupport.class)
@ConditionalOnMissingBean(value = CacheManager.class, name = "cacheResolver")
@EnableConfigurationProperties(CacheProperties.class)
@AutoConfigureAfter({ CouchbaseAutoConfiguration.class, HazelcastAutoConfiguration.class,
      HibernateJpaAutoConfiguration.class, RedisAutoConfiguration.class })
@Import({ CacheConfigurationImportSelector.class, CacheManagerEntityManagerFactoryDependsOnPostProcessor.class })
public class CacheAutoConfiguration {
}
```





```java
package org.springframework.boot.autoconfigure.cache;

/**
 * Supported cache types (defined in order of precedence).
 */
public enum CacheType {

   /**
    * Generic caching using 'Cache' beans from the context.
    */
   GENERIC,

   /**
    * JCache (JSR-107) backed caching.
    */
   JCACHE,

   /**
    * EhCache backed caching.
    */
   EHCACHE,

   /**
    * Hazelcast backed caching.
    */
   HAZELCAST,

   /**
    * Infinispan backed caching.
    */
   INFINISPAN,

   /**
    * Couchbase backed caching.
    */
   COUCHBASE,

   /**
    * Redis backed caching.
    */
   REDIS,

   /**
    * Caffeine backed caching.
    */
   CAFFEINE,

   /**
    * Simple in-memory caching.
    */
   SIMPLE,

   /**
    * No caching.
    */
   NONE

}
```



default `ConcurrentMapCacheManager`

```java

package org.springframework.boot.autoconfigure.cache;

/**
 * Simplest cache configuration, usually used as a fallback.
 *
 * @author Stephane Nicoll
 */
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


## Links

- [Spring Cache](/docs/CS/Java/Spring/Cache.md)