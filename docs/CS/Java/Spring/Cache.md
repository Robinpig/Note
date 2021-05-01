# Cache



org.springframework.cache.Cache` and `org.springframework.cache.CacheManager



Spring provides a few implementations of that abstraction: 

1. JDK `java.util.concurrent.ConcurrentMap`
2. Ehcache
3. Gemfire cache
4. Caffeine
5. JSR-107



Enabling Caching Annotations

It is important to note that even though declaring the cache annotations does not automatically trigger their actions - like many things in Spring, the feature has to be declaratively enabled (which means if you ever suspect caching is to blame, you can disable it by removing only one configuration line rather than all the annotations in your code).

To enable caching annotations add the annotation `@EnableCaching` to one of your `@Configuration` classes:

```java
@Configuration
@EnableCaching
public class AppConfig {
}
```