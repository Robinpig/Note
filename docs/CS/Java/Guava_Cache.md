## Introduction



Cache

LocalManualCache


CacheBuilder


## Evict

maxCapacity
expire


RemovalListener


```java
public static LoadingCache<String, String> cache = CacheBuilder.newBuilder()
        .maximumSize(20)
        .expireAfterAccess(20, TimeUnit.MINUTES)
        .removalListener(new RemovalListener<String, String>() {

            @Override
            public void onRemoval(RemovalNotification<String, String> notification) {
                log.info("evict cache " + notification.getKey() + "-" + notification.getValue());
            }
        })
        .build(new CacheLoader<String, String>() {
            @Override
            public String load(String key) throws Exception {
                log.info("load cache " + key);
                return "test_" + key;
            }
        });
```

recordStats

- hitRate
- averageLoadPenalty
- evictionCount


## Links

- [JCache](/docs/CS/Java/JCache.md)