> [!NOTE]
> 源码事实基于 Netflix/eureka **v1.10.19**，主要文件为 `eureka-core/src/main/java/com/netflix/eureka/registry/ResponseCacheImpl.java` 与同目录下的 `Key.java`。

## Introduction

Eureka Server 的读（客户端拉注册表）远比写（注册/续约/下线）频繁，而序列化整张注册表又是昂贵操作。因此在真正的注册表之上套了**两层缓存**：一层是可读写的 Guava `LoadingCache`，一层是只读的 `ConcurrentHashMap`，两者由后台 Timer 单向同步。加上客户端本地的那份缓存，构成了一条「**三级缓存链**」——它直接决定了服务上线/下线在多长时间内被其他人感知。

## Two-Level Cache

```java
// registry/ResponseCacheImpl.java
public class ResponseCacheImpl implements ResponseCache {
    private final ConcurrentMap<Key, Value> readOnlyCacheMap = new ConcurrentHashMap<Key, Value>();
    private final LoadingCache<Key, Value> readWriteCacheMap;
    private final java.util.Timer timer = new java.util.Timer("Eureka-CacheFillTimer", true);

    ResponseCacheImpl(EurekaServerConfig serverConfig, ServerCodecs serverCodecs, AbstractInstanceRegistry registry) {
        this.readWriteCacheMap =
                CacheBuilder.newBuilder()
                        .initialCapacity(serverConfig.getInitialCapacityOfResponseCache())   // 1000
                        .expireAfterWrite(serverConfig.getResponseCacheAutoExpirationInSeconds(), TimeUnit.SECONDS) // 180s
                        .build(new CacheLoader<Key, Value>() {
                            @Override
                            public Value load(Key key) throws Exception {
                                Value value = generatePayload(key);   // 真正序列化 registry
                                return value;
                            }
                        });

        if (shouldUseReadOnlyResponseCache) {     // eureka.server.use-read-only-response-cache，默认 true
            timer.schedule(getCacheUpdateTask(), new Date(...aligned...), responseCacheUpdateIntervalMs); // 30s
        }
    }
}
```

| 缓存层                | 数据结构 / 失效方式                       | 刷新机制                                                                     |
| :----------------- | :-------------------------------- | :----------------------------------------------------------------------- |
| `readWriteCacheMap` | Guava `LoadingCache`，`expireAfterWrite` 180s | 被动：命中未过期则直出；过期或被写路径 `invalidate` 后在下次读时同步 `generatePayload()` 重建 |
| `readOnlyCacheMap`  | `ConcurrentHashMap`，永不过期           | 主动：`Eureka-CacheFillTimer` 每 `responseCacheUpdateIntervalMs`（30s）用 readWrite 的值覆盖自身（不同才写） |

写路径结束后 [registry](/docs/CS/Framework/eureka/registry.md) 会调用 `invalidateCache(appName, vip, svip)`，它只失效 `readWriteCacheMap`；**`readOnlyCacheMap` 无法被主动失效**，只能等下一轮 30s 的回填任务。这是整个链路里最容易被人忽略的一环。

## Key Dimensions

缓存 Key 不是一个字符串，而是五个维度的组合（`registry/Key.java`）：

| 维度             | 取值                                     | 说明                                              |
| :------------- | :------------------------------------- | :---------------------------------------------- |
| `EntityType`   | `Application` / `VIP` / `SVIP`          | 按应用名、虚拟地址、安全虚拟地址三种视图分别缓存                         |
| `KeyType`      | `JSON` / `XML`                         | 不同 wire format 各一份                              |
| `Version`      | `V1` / `V2`                            | 由 `CurrentRequestVersion` 决定，兼容老形状（V1AwareInstanceInfoConverter 做转换） |
| `EurekaAccept` | `full` / `compact`                     | `full` 给 Server 间同步与老 client，`compact` 给新 client |
| `regions`      | 字符串数组                                  | 按请求的 region 组合分桶                                |

`Value` 在构造时就把 gzip 与非 gzip 两份字节都算好，客户端来的请求按 `Accept-Encoding` 取对应版本。

## Read Path

```java
Value getValue(final Key key, boolean useReadOnlyCache) {
    Value payload = null;
    try {
        if (useReadOnlyCache) {
            final Value currentPayload = readOnlyCacheMap.get(key);
            if (currentPayload != null) {
                payload = currentPayload;
            } else {
                payload = readWriteCacheMap.get(key);
                readOnlyCacheMap.put(key, payload);
            }
        } else {
            payload = readWriteCacheMap.get(key);
        }
    } catch (Throwable t) {
        logger.error("Cannot get value for key : {}", key, t);
    }
    return payload;
}
```

## 感知时延的完整推导

以「实例被 `kill -9`、没有发 DELETE」为例，从上一次成功续约（记时刻 T₀）到其它客户端彻底看不到它，中间要过五关：

| # | 环节                    | 默认耗时（最坏）                    | 原因                                                                                |
| - | :-------------------- | :------------------------- | :-------------------------------------------------------------------------------- |
| 1 | 租约过期                  | 180 s                      | `renew()` 把 `lastUpdateTimestamp` 设为 T₀+90，判定又是 `> lastUpdateTimestamp + duration`，即 T₀+180（那个 `2*duration` 的历史 bug） |
| 2 | EvictionTask 下一轮       | 60 s                       | `evict()` 由 `Eureka-EvictionTimer` 每 `evictionIntervalTimerInMs`=60s 触发一次             |
| 3 | readWrite 缓存重建         | ≈0（写路径 `invalidate` 主动失效） | `internalCancel` 末尾的 `invalidateCache` 直接删掉对应 Key                                 |
| 4 | readOnly 缓存回填          | 30 s                       | `readOnlyCacheMap` 只能等 `Eureka-CacheFillTimer` 的 30s 周期把它覆盖过去                      |
| 5 | 客户端下次增量拉取              | 30 s                       | `CacheRefreshThread` 每 `registryFetchIntervalSeconds`=30s 拉一次                        |
|   | **合计（最坏）**           | **约 300 s（5 分钟）**          | 平均而言约每步减半，典型落在 3~4 分钟                                                             |

> [!NOTE]
> 网络上流传最广的「90 + 90 + 30 = 210 秒」其实**少算了两步**：它没有计入 `EvictionTask` 的 60s 轮询间隔和 `readOnlyCacheMap` 的 30s 回填。若要得出 210s，必须同时满足「漏掉了 evict 周期」和「关闭了只读缓存」。真正能把时延压到秒级的手段，是客户端主动下线（DELETE，绕过 1~2 全部环节）或 Server 关闭只读缓存，详见 [Tuning](/docs/CS/Framework/eureka/tuning.md)。

对应的，如果是**优雅下线**，DELETE 会立即走到 `internalCancel`，链路只剩下第 4、5 步：约 30~60 秒。新实例上线同样受第 3~5 步影响，但因为注册时 `invalidateCache` 立即生效，通常 30~60s 内可见。

## Reconcile Safety Net

增量拉取天然存在「断线重连期间丢了中间变更」的风险（见 [registry](/docs/CS/Framework/eureka/registry.md?id=delta-队列) 的 3 分钟保留期）。补偿机制是双方都用 **`appsHashCode`** 做摘要：

- 服务端在返回 `Applications` 时附带全量应用的哈希；
- 客户端把本地增量合并结果重新算一次哈希，若与服务端的不一致（`reconcileHashCode != appsHashCode`），就丢弃本地缓存并退化为全量拉取 `getAndStoreFullRegistry()`；
- 无论是否一致，`reconcileAndLogDifference()` 都会按需打出差异日志，这是排查「注册表漂移」的第一个抓手。

## Links

- [Eureka](/docs/CS/Framework/eureka/Eureka.md)
- [Registry](/docs/CS/Framework/eureka/registry.md)
- [Server](/docs/CS/Framework/eureka/Server.md)
- [Client](/docs/CS/Framework/eureka/Client.md)
- [Tuning](/docs/CS/Framework/eureka/tuning.md)
- [Troubleshooting](/docs/CS/Framework/eureka/troubleshooting.md)

## References

1. [Netflix/eureka · ResponseCacheImpl](https://github.com/Netflix/eureka/blob/v1.10.19/eureka-core/src/main/java/com/netflix/eureka/registry/ResponseCacheImpl.java)
2. [Netflix/eureka · Key](https://github.com/Netflix/eureka/blob/v1.10.19/eureka-core/src/main/java/com/netflix/eureka/registry/Key.java)
