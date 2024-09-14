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

public enum CacheType {
   GENERIC,
   JCACHE,
   EHCACHE,
   HAZELCAST,
   INFINISPAN,
   COUCHBASE,
   REDIS,
   CAFFEINE,
   SIMPLE,
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

- [Spring Cache](/docs/CS/Framework/Spring/Cache.md)