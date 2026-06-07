## Introduction

Eureka 是一个基于 RESTful（Representational State Transfer）的服务，主要用于 AWS 云环境中的中间层服务发现、负载均衡和故障转移。它在 Netflix 中间件基础设施中扮演着关键角色。

Eureka 还附带了一个基于 Java 的客户端组件，即 **Eureka Client**，它使与服务交互变得更加容易。
该客户端还内置了一个负载均衡器，可执行基本的轮询负载均衡。

当 Eureka 服务器启动时，它会尝试从相邻节点获取所有实例注册信息。
如果从某个节点获取信息时出现问题，服务器会尝试所有对等节点，直到放弃。
如果服务器成功获取所有实例，它会根据这些信息设置应接收的续约阈值。
如果任何时刻续约数量低于配置的百分比阈值（15 分钟内低于 85%），服务器会停止过期实例，以保护当前的实例注册信息。

在 Netflix 中，上述保护机制称为**自我保护**模式，主要用于一组客户端与 Eureka Server 之间发生网络分区的情况。
在对等节点之间发生网络故障时，可能发生以下情况：

* 对等节点间的心跳复制可能会失败，服务器检测到这种情况后进入自我保护模式，保护当前状态。
* 注册可能发生在孤立的服务器上，某些客户端可能看到新的注册信息，而其他客户端可能看不到。

网络连接恢复稳定后，情况会自动纠正。
当对等节点能够正常通信时，注册信息会自动传输给那些缺少该信息的服务器。
总之，在网络故障期间，服务器会尽可能地保持弹性，
但在此期间客户端的服务器视图可能不一致。

在这种情况下，服务器会尽力保护已有的信息。
在大规模故障的情况下，这可能导致客户端获取到已不存在的实例。
客户端必须确保能够应对 eureka server 返回不存在或无响应的实例的情况。
最好的保护策略是快速超时并尝试其他服务器。

eureka 分为以下几个部分

- [server](/docs/CS/Framework/eureka/Server.md)
- [client](/docs/CS/Framework/eureka/Client.md)

## Beat

InstanceResource.renewLease()

Eureka client 需要每 30 秒通过发送心跳来续约租期。续约通知 Eureka server 该实例仍然存活。
如果服务器在 90 秒内未收到续约，则会从注册表中移除该实例。
不建议更改续约间隔，因为服务器会利用该信息判断客户端到服务器的通信是否存在广泛问题。

### Fetch Registry
Eureka client 从服务器获取注册表信息并在本地缓存。
之后, 客户端使用这些信息查找其他服务。
这些信息通过获取上次获取周期与当前周期之间的增量更新来定期更新（每 30 秒）。
增量信息在服务端保留较长时间（约 3 分钟），因此增量获取可能会返回相同的实例。
Eureka client 会自动处理重复信息。

获取增量后，Eureka client 通过比较服务器返回的实例数量来与服务器核对信息，如果因某些原因信息不匹配，
则会重新获取完整的注册表信息。
Eureka server 缓存增量、完整注册表以及单个应用的压缩负载，同时也缓存相同信息的未压缩版本。
负载支持 JSON/XML 格式。Eureka client 使用 jersey apache client 以压缩 JSON 格式获取信息。

## Cache

```java
public class ResponseCacheImpl implements ResponseCache {
    private final ConcurrentMap<Key, ResponseCacheImpl.Value> readOnlyCacheMap = new ConcurrentHashMap();
    private final LoadingCache<Key, ResponseCacheImpl.Value> readWriteCacheMap;

   private TimerTask getCacheUpdateTask() {
      return new TimerTask() {
         @Override
         public void run() {
            for (Key key : readOnlyCacheMap.keySet()) {
               try {
                  CurrentRequestVersion.set(key.getVersion());
                  Value cacheValue = readWriteCacheMap.get(key);
                  Value currentCacheValue = readOnlyCacheMap.get(key);
                  if (cacheValue != currentCacheValue) {
                     readOnlyCacheMap.put(key, cacheValue);
                  }
               } catch (Throwable th) {
                  logger.error("Error while updating the client cache from response cache for key {}", key.toStringCompact(), th);
               } finally {
                  CurrentRequestVersion.remove();
               }
            }
         }
      };
   }
}
```

### Cancel
Eureka client 在关闭时向 Eureka server 发送取消请求。这会从服务器的实例注册表中移除该实例，从而有效地将其从流量中移除。
```java
@Configuration(proxyBeanMethods = false)
	@ConditionalOnMissingRefreshScope
	protected static class EurekaClientConfiguration {

   @Autowired
   private ApplicationContext context;

   @Autowired(required = false)
   private AbstractDiscoveryClientOptionalArgs<?> optionalArgs;

   @Bean(destroyMethod = "shutdown")
   @ConditionalOnMissingBean(value = EurekaClient.class, search = SearchStrategy.CURRENT)
   public EurekaClient eurekaClient(ApplicationInfoManager manager, EurekaClientConfig config,
                                    TransportClientFactories<?> transportClientFactories) {
      return new CloudEurekaClient(manager, config, transportClientFactories, this.optionalArgs, this.context);
   }
}
```
### Time Lag
Eureka client 的所有操作可能需要一些时间才能在 Eureka server 以及其他 Eureka client 上反映出来。这是因为 Eureka server 上的负载缓存会定期刷新以更新新信息。Eureka client 也定期获取增量。因此，更改传播到所有 Eureka client 可能需要长达 2 分钟的时间。
## Cluster Sync

将 InstanceInfo 信息注册到本地，并将此信息复制到所有对等 Eureka 节点。
如果这是来自其他副本节点的复制事件，则不再复制。

```java
@Singleton
public class PeerAwareInstanceRegistryImpl extends AbstractInstanceRegistry implements PeerAwareInstanceRegistry {
   @Override
   public void register(final InstanceInfo info, final boolean isReplication) {
      int leaseDuration = Lease.DEFAULT_DURATION_IN_SECS;
      if (info.getLeaseInfo() != null && info.getLeaseInfo().getDurationInSecs() > 0) {
         leaseDuration = info.getLeaseInfo().getDurationInSecs();
      }
      super.register(info, leaseDuration, isReplication);
      replicateToPeers(Action.Register, info.getAppName(), info.getId(), info, null, isReplication);
   }

   
}
```

### Replica

将所有实例变更复制到对等 Eureka 节点，但不包括发往本节点的复制流量。

```java
@Singleton
public class PeerAwareInstanceRegistryImpl extends AbstractInstanceRegistry implements PeerAwareInstanceRegistry {

   private void replicateToPeers(Action action, String appName, String id,
                                 InstanceInfo info /* optional */,
                                 InstanceStatus newStatus /* optional */, boolean isReplication) {
      Stopwatch tracer = action.getTimer().start();
      try {
         if (isReplication) {
            numberOfReplicationsLastMin.increment();
         }
         // If it is a replication already, do not replicate again as this will create a poison replication
         if (peerEurekaNodes == Collections.EMPTY_LIST || isReplication) {
            return;
         }

         for (final PeerEurekaNode node : peerEurekaNodes.getPeerEurekaNodes()) {
            // If the url represents this host, do not replicate to yourself.
            if (peerEurekaNodes.isThisMyUrl(node.getServiceUrl())) {
               continue;
            }
            replicateInstanceActionsToPeers(action, appName, id, info, newStatus, node);
         }
      } finally {
         tracer.stop();
      }
   }
   
   private void replicateInstanceActionsToPeers(Action action, String appName,
                                                String id, InstanceInfo info, InstanceStatus newStatus,
                                                PeerEurekaNode node) {
      try {
         InstanceInfo infoFromRegistry;
         CurrentRequestVersion.set(Version.V2);
         switch (action) {
            case Cancel:
               node.cancel(appName, id);
               break;
            case Heartbeat:
               InstanceStatus overriddenStatus = overriddenInstanceStatusMap.get(id);
               infoFromRegistry = getInstanceByAppAndId(appName, id, false);
               node.heartbeat(appName, id, infoFromRegistry, overriddenStatus, false);
               break;
            case Register:
               node.register(info);
               break;
            case StatusUpdate:
               infoFromRegistry = getInstanceByAppAndId(appName, id, false);
               node.statusUpdate(appName, id, newStatus, infoFromRegistry);
               break;
            case DeleteStatusOverride:
               infoFromRegistry = getInstanceByAppAndId(appName, id, false);
               node.deleteStatusOverride(appName, id, infoFromRegistry);
               break;
         }
      } catch (Throwable t) {
         logger.error("Cannot replicate information to {} for action {}", node.getServiceUrl(), action.name(), t);
      } finally {
         CurrentRequestVersion.remove();
      }
   }
}
```

## EndpointUtils

从属性文件中获取所有 Eureka 服务 URL 列表，供 Eureka client 使用。

Region Zone

1 个 application 对应 1 个 region，多个 zones

```java
// com.netflix.discovery.endpoint.EndpointUtils
public static Map<String, List<String>> getServiceUrlsMapFromConfig(EurekaClientConfig clientConfig, String instanceZone, boolean preferSameZone) {
        Map<String, List<String>> orderedUrls = new LinkedHashMap<>();
        String region = getRegion(clientConfig); // only 1 region
        String[] availZones = clientConfig.getAvailabilityZones(clientConfig.getRegion());
        if (availZones == null || availZones.length == 0) {
            availZones = new String[1];
            availZones[0] = DEFAULT_ZONE;
        }
        int myZoneOffset = getZoneOffset(instanceZone, preferSameZone, availZones);

        String zone = availZones[myZoneOffset];
        List<String> serviceUrls = clientConfig.getEurekaServerServiceUrls(zone);
        if (serviceUrls != null) {
            orderedUrls.put(zone, serviceUrls);
        }
        int currentOffset = myZoneOffset == (availZones.length - 1) ? 0 : (myZoneOffset + 1);
        while (currentOffset != myZoneOffset) {
            zone = availZones[currentOffset];
            serviceUrls = clientConfig.getEurekaServerServiceUrls(zone);
            if (serviceUrls != null) {
                orderedUrls.put(zone, serviceUrls);
            }
            if (currentOffset == (availZones.length - 1)) {
                currentOffset = 0;
            } else {
                currentOffset++;
            }
        }

        if (orderedUrls.size() < 1) {
            throw new IllegalArgumentException("DiscoveryClient: invalid serviceUrl specified!");
        }
        return orderedUrls;
    }
```

### PeerAwareInstanceRegistry

```java
@Inject
public PeerAwareInstanceRegistryImpl(EurekaServerConfig serverConfig, EurekaClientConfig clientConfig, ServerCodecs serverCodecs, EurekaClient eurekaClient) {
    super(serverConfig, clientConfig, serverCodecs);
    this.eurekaClient = eurekaClient;
    this.numberOfReplicationsLastMin = new MeasuredRate(60000L);
    this.instanceStatusOverrideRule = new FirstMatchWinsCompositeRule(new InstanceStatusOverrideRule[]{new DownOrStartingRule(), new OverrideExistsRule(this.overriddenInstanceStatusMap), new LeaseExistsRule()});
}
```

### AbstractInstanceRegistry

*recentCanceledQueue and recentRegisteredQueue are use a capacity **1000 CircularQueue***

CircularQueue 委托了一个 **[ArrayBlockingQueue](/docs/CS/Java/JDK/Collection/Queue.md?id=ArrayBlockingQueue)** 并重写了 offer 方法。

```java
public abstract class AbstractInstanceRegistry implements InstanceRegistry {
   // CircularQueues here for debugging/statistics purposes only
   private final CircularQueue<Pair<Long, String>> recentRegisteredQueue;
   private final CircularQueue<Pair<Long, String>> recentCanceledQueue;
   private ConcurrentLinkedQueue<RecentlyChangedItem> recentlyChangedQueue = new ConcurrentLinkedQueue<RecentlyChangedItem>();

   protected AbstractInstanceRegistry(EurekaServerConfig serverConfig, EurekaClientConfig clientConfig, ServerCodecs serverCodecs) {
      this.overriddenInstanceStatusMap = CacheBuilder.newBuilder().initialCapacity(500).expireAfterAccess(1L, TimeUnit.HOURS).build().asMap();
      this.recentlyChangedQueue = new ConcurrentLinkedQueue();
      this.readWriteLock = new ReentrantReadWriteLock();
      this.read = this.readWriteLock.readLock();
      this.write = this.readWriteLock.writeLock();
      this.lock = new Object();
      this.deltaRetentionTimer = new Timer("Eureka-DeltaRetentionTimer", true);
      this.evictionTimer = new Timer("Eureka-EvictionTimer", true);
      this.evictionTaskRef = new AtomicReference();
      this.allKnownRemoteRegions = EMPTY_STR_ARRAY;
      this.serverConfig = serverConfig;
      this.clientConfig = clientConfig;
      this.serverCodecs = serverCodecs;
      this.recentCanceledQueue = new AbstractInstanceRegistry.CircularQueue(1000);
      this.recentRegisteredQueue = new AbstractInstanceRegistry.CircularQueue(1000);
      this.renewsLastMin = new MeasuredRate(60000L);
      this.deltaRetentionTimer.schedule(this.getDeltaRetentionTask(), serverConfig.getDeltaRetentionTimerIntervalInMs(), serverConfig.getDeltaRetentionTimerIntervalInMs());
   }
}
```

## Tuning

Eureka1.0 存在问题
1. 订阅者获取的服务信息是全量的 对内存压力大 在多数据中心部署时订阅者其实只需要获取同数据中心的即可
2. 订阅者定时pull 实时性不够好 且存在空pull浪费
3. Eureka Server的peer节点对每个写请求都会转发到其它的peer节点 对于不断增加的写请求只能通过提高配置来解决

Eureka2.0改进
1. pull模式转向push 实现更小粒度 服务按需订阅的功能
2. 读写分离 写集群相对稳定，无需经常扩容；读集群可以按需扩容以提高数据推送能力
3. 新增审计日志的功能和功能更丰富的Dashboard

# Links

- [Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md?id=service-registry)

## References

1. [Eureka Service源码流程图](https://www.processon.com/view/5f2dfff05653bb1b6117809a)
