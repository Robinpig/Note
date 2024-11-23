## Introduction

Eureka is a RESTful (Representational State Transfer) service that is primarily used in the AWS cloud for the purpose of discovery, load balancing and failover of middle-tier servers. It plays a critical role in Netflix mid-tier infra.

We call this service, the **Eureka Server**. 
Eureka also comes with a Java-based client component,the **Eureka Client**, which makes interactions with the service much easier.
The client also has a built-in load balancer that does basic round-robin load balancing.

To include Eureka Server in your project, use the starter with a group ID of `org.springframework.cloud` and an artifact ID of `spring-cloud-starter-netflix-eureka-server`.

When the Eureka server comes up, it tries to get all of the instance registry information from a neighboring node. If there is a problem getting the information from a node, the server tries all of the peers before it gives up. If the server is able to successfully get all of the instances, it sets the renewal threshold that it should be receiving based on that information. If any time, the renewals falls below the percent configured for that value (below 85% within 15 mins), the server stops expiring instances to protect the current instance registry information.

In Netflix, the above safeguard is called as `self-preservation` mode and is primarily used as a protection in scenarios where there is a network partition between a group of clients and the Eureka Server.
In the case of network outages between peers, following things may happen.

* The heartbeat replications between peers may fail and the server detects this situation and enters into a self-preservation mode protecting the current state.
* Registrations may happen in an orphaned server and some clients may reflect new registrations while the others may not.

The situation autocorrects itself after the network connectivity is restored to a stable state.
When the peers are able to communicate fine, the registration information is automatically transferred to the servers that do not have them.
The bottom line is, during the network outages, the server tries to be as resilient as possible,
but there is a possibility of clients having different views of the servers during that time.

In these scenarios, the server tries to protect the information it already has. There may be scenarios in case of a mass outage that this may cause the clients to get the instances that do not exist anymore. The clients must make sure they are resilient to eureka server returning an instance that is non-existent or un-responsive. The best protection in these scenarios is to timeout quickly and try other servers.

### Directory

eureka分为以下几个部分

- server
- client




## Beat

InstanceResource.renewLease()

Eureka client needs to renew the lease by sending heartbeats every 30 seconds. The renewal informs the Eureka server that the instance is still alive. 
If the server hasn't seen a renewal for 90 seconds, it removes the instance out of its registry. 
It is advisable not to change the renewal interval since the server uses that information to determine if there is a wide spread problem with the client to server communication.

### Fetch Registry
Eureka clients fetches the registry information from the server and caches it locally. After that, the clients use that information to find other services. This information is updated periodically (every 30 seconds) by getting the delta updates between the last fetch cycle and the current one. The delta information is held longer (for about 3 mins) in the server, hence the delta fetches may return the same instances again. The Eureka client automatically handles the duplicate information.

After getting the deltas, Eureka client reconciles the information with the server by comparing the instance counts returned by the server and if the information does not match for some reason, the whole registry information is fetched again. Eureka server caches the compressed payload of the deltas, whole registry and also per application as well as the uncompressed information of the same. The payload also supports both JSON/XML formats. Eureka client gets the information in compressed JSON format using jersey apache client.

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
Eureka client sends a cancel request to Eureka server on shutdown. This removes the instance from the server's instance registry thereby effectively taking the instance out of traffic.
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
All operations from Eureka client may take some time to reflect in the Eureka servers and subsequently in other Eureka clients. This is because of the caching of the payload on the eureka server which is refreshed periodically to reflect new information. Eureka clients also fetch deltas periodically. Hence, it may take up to 2 mins for changes to propagate to all Eureka clients.
## Cluster Sync

Registers the information about the InstanceInfo and replicates this information to all peer eureka nodes.
If this is replication event from other replica nodes then it is not replicated.

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

Replicates all instance changes to peer eureka nodes except for replication traffic to this node.

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

Get the list of all eureka service urls from properties file for the eureka client to talk to.

Region Zone

1 application 1 region, multiple zones

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

CircularQueue delegate a **[ArrayBlockingQueue](/docs/CS/Java/JDK/Collection/Queue.md?id=ArrayBlockingQueue)** and override offer method.

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