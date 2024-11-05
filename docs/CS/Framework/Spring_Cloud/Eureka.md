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

## Servcer Initialization

The class that kick starts the eureka server.
The eureka server is configured by using the configuration EurekaServerConfig specified by eureka.server.props in the classpath. 
The eureka client component is also initialized by using the configuration EurekaInstanceConfig specified by eureka.client.props. 
If the server runs in the AWS cloud, the eureka server binds it to the elastic ip as specified.

```java
public abstract class EurekaBootStrap implements ServletContextListener {
    protected void initEurekaServerContext() throws Exception {
        EurekaServerConfig eurekaServerConfig = new DefaultEurekaServerConfig();

        // For backward compatibility
        JsonXStream.getInstance().registerConverter(new V1AwareInstanceInfoConverter(), XStream.PRIORITY_VERY_HIGH);
        XmlXStream.getInstance().registerConverter(new V1AwareInstanceInfoConverter(), XStream.PRIORITY_VERY_HIGH);

        ServerCodecs serverCodecs = new DefaultServerCodecs(eurekaServerConfig);

        ApplicationInfoManager applicationInfoManager = null;

        if (eurekaClient == null) {
            EurekaInstanceConfig instanceConfig = isCloud(ConfigurationManager.getDeploymentContext())
                    ? new CloudInstanceConfig()
                    : new MyDataCenterInstanceConfig();

            applicationInfoManager = new ApplicationInfoManager(
                    instanceConfig, new EurekaConfigBasedInstanceInfoProvider(instanceConfig).get());

            EurekaClientConfig eurekaClientConfig = new DefaultEurekaClientConfig();
            eurekaClient = new DiscoveryClient(applicationInfoManager, eurekaClientConfig, getTransportClientFactories(),
                    getDiscoveryClientOptionalArgs());
        } else {
            applicationInfoManager = eurekaClient.getApplicationInfoManager();
        }

        EurekaServerHttpClientFactory eurekaServerHttpClientFactory = getEurekaServerHttpClientFactory();

        PeerAwareInstanceRegistry registry;
        if (isAws(applicationInfoManager.getInfo())) {
            registry = new AwsInstanceRegistry(
                    eurekaServerConfig,
                    eurekaClient.getEurekaClientConfig(),
                    serverCodecs,
                    eurekaClient, eurekaServerHttpClientFactory
            );
            awsBinder = new AwsBinderDelegate(eurekaServerConfig, eurekaClient.getEurekaClientConfig(), registry, applicationInfoManager);
            awsBinder.start();
        } else {
            registry = new PeerAwareInstanceRegistryImpl(
                    eurekaServerConfig,
                    eurekaClient.getEurekaClientConfig(),
                    serverCodecs,
                    eurekaClient, eurekaServerHttpClientFactory
            );
        }

        PeerEurekaNodes peerEurekaNodes = getPeerEurekaNodes(
                registry,
                eurekaServerConfig,
                eurekaClient.getEurekaClientConfig(),
                serverCodecs,
                applicationInfoManager
        );

        serverContext = new DefaultEurekaServerContext(
                eurekaServerConfig,
                serverCodecs,
                registry,
                peerEurekaNodes,
                applicationInfoManager
        );

        EurekaServerContextHolder.initialize(serverContext);

        serverContext.initialize();
        logger.info("Initialized server context");

        // Copy registry from neighboring eureka node
        int registryCount = registry.syncUp();
        registry.openForTraffic(applicationInfoManager, registryCount);

        // Register all monitoring statistics.
        EurekaMonitors.registerAllStats();
    }
}
```

```java
@Singleton
public class PeerAwareInstanceRegistryImpl extends AbstractInstanceRegistry implements PeerAwareInstanceRegistry {
    @Override
    public void openForTraffic(ApplicationInfoManager applicationInfoManager, int count) {
        // Renewals happen every 30 seconds and for a minute it should be a factor of 2.
        this.expectedNumberOfClientsSendingRenews = count;
        updateRenewsPerMinThreshold();
        logger.info("Got {} instances from neighboring DS node", count);
        logger.info("Renew threshold is: {}", numberOfRenewsPerMinThreshold);
        this.startupTime = System.currentTimeMillis();
        if (count > 0) {
            this.peerInstancesTransferEmptyOnStartup = false;
        }
        DataCenterInfo.Name selfName = applicationInfoManager.getInfo().getDataCenterInfo().getName();
        boolean isAws = Name.Amazon == selfName;
        if (isAws && serverConfig.shouldPrimeAwsReplicaConnections()) {
            logger.info("Priming AWS connections for all replicas..");
            primeAwsReplicas(applicationInfoManager);
        }
        applicationInfoManager.setInstanceStatus(InstanceStatus.UP);
        super.postInit();
    }
}
```
evict Timer启动 60s一次 淘汰90s*2时间内未续期的服务实例
```java

   protected void postInit() {
      renewsLastMin.start();
      if (evictionTaskRef.get() != null) {
         evictionTaskRef.get().cancel();
      }
      evictionTaskRef.set(new EvictionTask());
      evictionTimer.schedule(evictionTaskRef.get(),
              serverConfig.getEvictionIntervalTimerInMs(),
              serverConfig.getEvictionIntervalTimerInMs());
   }
```

```java
class EvictionTask extends TimerTask {
   @Override
   public void run() {
      try {
         long compensationTimeMs = getCompensationTimeMs();
         logger.info("Running the evict task with compensationTime {}ms", compensationTimeMs);
         evict(compensationTimeMs);
      } catch (Throwable e) {
         logger.error("Could not run the evict task", e);
      }
   }
}
```
evict 从registry缓存中获取注册实例信息 判断过期加入expiredLeases中 最后随机(Knuth shuffle algorithm)从过期列表淘汰
```java
public void evict(long additionalLeaseMs) {
   // We collect first all expired items, to evict them in random order. For large eviction sets,
   // if we do not that, we might wipe out whole apps before self preservation kicks in. By randomizing it,
   // the impact should be evenly distributed across all applications.
   List<Lease<InstanceInfo>> expiredLeases = new ArrayList<>();
   for (Entry<String, Map<String, Lease<InstanceInfo>>> groupEntry : registry.entrySet()) {
      Map<String, Lease<InstanceInfo>> leaseMap = groupEntry.getValue();
      if (leaseMap != null) {
         for (Entry<String, Lease<InstanceInfo>> leaseEntry : leaseMap.entrySet()) {
            Lease<InstanceInfo> lease = leaseEntry.getValue();
            if (lease.isExpired(additionalLeaseMs) && lease.getHolder() != null) {
               expiredLeases.add(lease);
            }
         }
      }
   }

   // To compensate for GC pauses or drifting local time, we need to use current registry size as a base for
   // triggering self-preservation. Without that we would wipe out full registry.
   int registrySize = (int) getLocalRegistrySize();
   int registrySizeThreshold = (int) (registrySize * serverConfig.getRenewalPercentThreshold());
   int evictionLimit = registrySize - registrySizeThreshold;

   int toEvict = Math.min(expiredLeases.size(), evictionLimit);
   if (toEvict > 0) {
      logger.info("Evicting {} items (expired={}, evictionLimit={})", toEvict, expiredLeases.size(), evictionLimit);

      Random random = new Random(System.currentTimeMillis());
      for (int i = 0; i < toEvict; i++) {
         // Pick a random item (Knuth shuffle algorithm)
         int next = i + random.nextInt(expiredLeases.size() - i);
         Collections.swap(expiredLeases, i, next);
         Lease<InstanceInfo> lease = expiredLeases.get(i);

         String appName = lease.getHolder().getAppName();
         String id = lease.getHolder().getId();
         EXPIRED.increment();
         internalCancel(appName, id, false);
      }
   }
}
```

## Service Registry

start -> registry -> getEurekaClient -> init

-> notify -> register in a single scheduler

### AutoConfiguration

```java
public class EurekaClientAutoConfiguration {

    @Bean
    @ConditionalOnBean(AutoServiceRegistrationProperties.class)
    @ConditionalOnProperty(
            value = "spring.cloud.service-registry.auto-registration.enabled",
            matchIfMissing = true)
    public EurekaAutoServiceRegistration eurekaAutoServiceRegistration(
            ApplicationContext context, EurekaServiceRegistry registry,
            EurekaRegistration registration) {
        return new EurekaAutoServiceRegistration(context, registry, registration);
    }

    @Bean(destroyMethod = "shutdown")
    @ConditionalOnMissingBean(value = EurekaClient.class,
            search = SearchStrategy.CURRENT)
    @org.springframework.cloud.context.config.annotation.RefreshScope
    @Lazy
    public EurekaClient eurekaClient(ApplicationInfoManager manager,
                                     EurekaClientConfig config, EurekaInstanceConfig instance,
                                     @Autowired(required = false) HealthCheckHandler healthCheckHandler) {
        // If we use the proxy of the ApplicationInfoManager we could run into a
        // problem
        // when shutdown is called on the CloudEurekaClient where the
        // ApplicationInfoManager bean is
        // requested but wont be allowed because we are shutting down. To avoid this
        // we use the
        // object directly.
        ApplicationInfoManager appManager;
        if (AopUtils.isAopProxy(manager)) {
            appManager = ProxyUtils.getTargetObject(manager);
        }
        else {
            appManager = manager;
        }
        CloudEurekaClient cloudEurekaClient = new CloudEurekaClient(appManager,
                config, this.optionalArgs, this.context);
        cloudEurekaClient.registerHealthCheck(healthCheckHandler);
        return cloudEurekaClient;
    }
}
```

### start

SmartLifeCycle in Spring refresh

```java
public class EurekaAutoServiceRegistration implements AutoServiceRegistration,
		SmartLifecycle, Ordered, SmartApplicationListener {
  
    private AtomicBoolean running = new AtomicBoolean(false);

    private int order = 0;

    private AtomicInteger port = new AtomicInteger(0);

    private ApplicationContext context;

    private EurekaServiceRegistry serviceRegistry;

    private EurekaRegistration registration;

    @Override
    public void start() {
        // only set the port if the nonSecurePort or securePort is 0 and this.port != 0

        // only initialize if nonSecurePort is greater than 0 and it isn't already running
        // because of containerPortInitializer below
        if (!this.running.get() && this.registration.getNonSecurePort() > 0) {

            this.serviceRegistry.register(this.registration);

            this.context.publishEvent(new InstanceRegisteredEvent<>(this,
                    this.registration.getInstanceConfig()));
            this.running.set(true);
        }
    }
}
```

#### registry

1. init DiscoveryClient
2. notify [StatusChangeListener](/docs/CS/Framework/Spring_Cloud/Eureka.md?id=Status-Change)

> [!NOTE]
>
> StatusChangeListener is implemented by Anonymous in DiscoveryClient.

```java
public class EurekaServiceRegistry implements ServiceRegistry<EurekaRegistration> {

    @Override
    public void register(EurekaRegistration reg) {
        maybeInitializeClient(reg);

        reg.getApplicationInfoManager()
                .setInstanceStatus(reg.getInstanceConfig().getInitialStatus());

        reg.getHealthCheckHandler().ifAvailable(healthCheckHandler -> reg
                .getEurekaClient().registerHealthCheck(healthCheckHandler));
    }

    private void maybeInitializeClient(EurekaRegistration reg) {
        // force initialization of possibly scoped proxies
        reg.getApplicationInfoManager().getInfo();
        reg.getEurekaClient().getApplications();
    }
}
```

##### getEurekaClient

```java
public class EurekaRegistration implements Registration {
    private final EurekaClient eurekaClient;
  
    public CloudEurekaClient getEurekaClient() {
        if (this.cloudEurekaClient.get() == null) {
            this.cloudEurekaClient.compareAndSet(null, getTargetObject(eurekaClient, CloudEurekaClient.class));
        }
        return this.cloudEurekaClient.get();
    }
  
}
```

##### notify

```java
public class ApplicationInfoManager {
    public synchronized void setInstanceStatus(InstanceStatus status) {
        InstanceStatus next = instanceStatusMapper.map(status);
        if (next == null) {
            return;
        }

        InstanceStatus prev = instanceInfo.setStatus(next);
        if (prev != null) {
            for (StatusChangeListener listener : listeners.values()) {
                listener.notify(new StatusChangeEvent(prev, next));
            }
        }
    }
}
```

### init

1. schedule 2 threads
2. heartbeat 1 thread
3. cacheRefresh 1 thread
4. fetchRegistry
5. initScheduledTasks
   - schedule CacheRefreshThread to refreshRegistry
   - schedule heatBeatTask
   - registerStatusChangeListener

```java
package com.netflix.discovery;

@Singleton
public class DiscoveryClient implements EurekaClient {


    @Inject
    DiscoveryClient(ApplicationInfoManager applicationInfoManager, EurekaClientConfig config, AbstractDiscoveryClientOptionalArgs args,
                    Provider<BackupRegistry> backupRegistryProvider, EndpointRandomizer endpointRandomizer) {
  
        InstanceInfo myInfo = applicationInfoManager.getInfo();
  
        try {
            // default size of 2 - 1 each for heartbeat and cacheRefresh
            scheduler = Executors.newScheduledThreadPool(2,
                    new ThreadFactoryBuilder()
                            .setNameFormat("DiscoveryClient-%d")
                            .setDaemon(true)
                            .build());

            heartbeatExecutor = new ThreadPoolExecutor(
                    1, clientConfig.getHeartbeatExecutorThreadPoolSize(), 0, TimeUnit.SECONDS,
                    new SynchronousQueue<Runnable>(),
                    new ThreadFactoryBuilder()
                            .setNameFormat("DiscoveryClient-HeartbeatExecutor-%d")
                            .setDaemon(true)
                            .build()
            );  // use direct handoff

            cacheRefreshExecutor = new ThreadPoolExecutor(
                    1, clientConfig.getCacheRefreshExecutorThreadPoolSize(), 0, TimeUnit.SECONDS,
                    new SynchronousQueue<Runnable>(),
                    new ThreadFactoryBuilder()
                            .setNameFormat("DiscoveryClient-CacheRefreshExecutor-%d")
                            .setDaemon(true)
                            .build()
            );  // use direct handoff

            eurekaTransport = new EurekaTransport();
            scheduleServerEndpointTask(eurekaTransport, args);

        } catch (Throwable e) {
            throw new RuntimeException("Failed to initialize DiscoveryClient!", e);
        }

        if (clientConfig.shouldFetchRegistry()) {
            try {
                boolean primaryFetchRegistryResult = fetchRegistry(false);
                // backup
            } catch (Throwable th) {
                throw new IllegalStateException(th);
            }
        }

        // finally, init the schedule tasks (e.g. cluster resolvers, heartbeat, instanceInfo replicator, fetch
        initScheduledTasks();
    }
}
```

#### TimedSupervisorTask

increment currentDelay * 2 if timeout, otherwise set default 30s

```java
public class TimedSupervisorTask extends TimerTask {
    @Override
    public void run() {
        Future<?> future = null;
        try {
            future = executor.submit(task);
            threadPoolLevelGauge.set((long) executor.getActiveCount());
            future.get(timeoutMillis, TimeUnit.MILLISECONDS);  // block until done or timeout
            delay.set(timeoutMillis);
            threadPoolLevelGauge.set((long) executor.getActiveCount());
            successCounter.increment();
        } catch (TimeoutException e) {
            timeoutCounter.increment();

            long currentDelay = delay.get();
            long newDelay = Math.min(maxDelay, currentDelay * 2);
            delay.compareAndSet(currentDelay, newDelay);

        } catch (RejectedExecutionException e) {
            rejectedCounter.increment();
        } catch (Throwable e) {
            throwableCounter.increment();
        } finally {
            if (future != null) {
                future.cancel(true);
            }

            if (!scheduler.isShutdown()) {
                scheduler.schedule(this, delay.get(), TimeUnit.MILLISECONDS);
            }
        }
    }
}
```

### DiscoveryClient

Define a simple interface over the current DiscoveryClient implementation.
This interface does NOT try to clean up the current client interface for eureka 1.x.
Rather it tries to provide an easier transition path from eureka 1.x to eureka 2.x.

EurekaClient API contracts are:

- provide the ability to get InstanceInfo(s) (in various different ways)
- provide the ability to get data about the local Client (known regions, own AZ etc)
- provide the ability to register and access the healthcheck handler for the client

```java
@ImplementedBy(DiscoveryClient.class)
public interface EurekaClient extends LookupService {


}
```

The class that is instrumental for interactions with Eureka Server.
Eureka Client is responsible for

- Registering the instance with Eureka Server
- Renewalof the lease with Eureka Server
- Cancellation of the lease from Eureka Server during shutdown
- Querying the list of services/instances registered with Eureka Server

Eureka Client needs a configured list of Eureka Server java.net.URLs to talk to.These java.net.URLs are typically amazon elastic eips which do not change.
All of the functions defined above fail-over to other java.net.URLs specified in the list in the case of failure.

finally, init the schedule tasks (e.g. cluster resolvers, heartbeat, instanceInfo replicator, fetch
`com.netflix.discovery.DiscoveryClient#initScheduledTasks()`

#### Status Change

```java
public static interface StatusChangeListener {
    public void notify(StatusChangeEvent statusChangeEvent) {
        DiscoveryClient.this.instanceInfoReplicator.onDemandUpdate();
    }
}

class InstanceInfoReplicator implements Runnable {
  
    private final ScheduledExecutorService scheduler; // singleThread
  
    public boolean onDemandUpdate() {
        if (rateLimiter.acquire(burstSize, allowedRatePerMinute)) {
            if (!scheduler.isShutdown()) {
                scheduler.submit(new Runnable() {
                    @Override
                    public void run() {
                        Future latestPeriodic = scheduledPeriodicRef.get();
                        if (latestPeriodic != null && !latestPeriodic.isDone()) {
                            latestPeriodic.cancel(false);
                        }

                        InstanceInfoReplicator.this.run();
                    }
                });
                return true;
            } else {
                return false;
            }
        } else {
            return false;
        }
    }

    public void run() {
        try {
            discoveryClient.refreshInstanceInfo();

            Long dirtyTimestamp = instanceInfo.isDirtyWithTime();
            if (dirtyTimestamp != null) {
                discoveryClient.register();
                instanceInfo.unsetIsDirty(dirtyTimestamp);
            }
        } catch (Throwable t) {
        } finally {
            Future next = scheduler.schedule(this, replicationIntervalSeconds, TimeUnit.SECONDS);
            scheduledPeriodicRef.set(next);
        }
    }
}
```

#### register

```java
public class DiscoveryClient implements EurekaClient {
    /**
     * Register with the eureka service by making the appropriate REST call.
     */
    boolean register() throws Throwable {
        EurekaHttpResponse<Void> httpResponse;
        try {
            httpResponse = eurekaTransport.registrationClient.register(instanceInfo);
        } catch (Exception e) {
            throw e;
        }

        return httpResponse.getStatusCode() == Status.NO_CONTENT.getStatusCode();
    }
}  
```

### Server addInstance

```java
@Produces({"application/xml", "application/json"})
public class ApplicationResource {
    @POST
    @Consumes({"application/json", "application/xml"})
    public Response addInstance(InstanceInfo info,
                                @HeaderParam(PeerEurekaNode.HEADER_REPLICATION) String isReplication) {
        logger.debug("Registering instance {} (replication={})", info.getId(), isReplication);
        // validate that the instanceinfo contains all the necessary required fields
        if (isBlank(info.getId())) {
            return Response.status(400).entity("Missing instanceId").build();
        } else if (isBlank(info.getHostName())) {
            return Response.status(400).entity("Missing hostname").build();
        } else if (isBlank(info.getIPAddr())) {
            return Response.status(400).entity("Missing ip address").build();
        } else if (isBlank(info.getAppName())) {
            return Response.status(400).entity("Missing appName").build();
        } else if (!appName.equals(info.getAppName())) {
            return Response.status(400).entity("Mismatched appName, expecting " + appName + " but was " + info.getAppName()).build();
        } else if (info.getDataCenterInfo() == null) {
            return Response.status(400).entity("Missing dataCenterInfo").build();
        } else if (info.getDataCenterInfo().getName() == null) {
            return Response.status(400).entity("Missing dataCenterInfo Name").build();
        }

        // handle cases where clients may be registering with bad DataCenterInfo with missing data
        DataCenterInfo dataCenterInfo = info.getDataCenterInfo();
        if (dataCenterInfo instanceof UniqueIdentifier) {
            String dataCenterInfoId = ((UniqueIdentifier) dataCenterInfo).getId();
            if (isBlank(dataCenterInfoId)) {
                boolean experimental = "true".equalsIgnoreCase(serverConfig.getExperimental("registration.validation.dataCenterInfoId"));
                if (experimental) {
                    String entity = "DataCenterInfo of type " + dataCenterInfo.getClass() + " must contain a valid id";
                    return Response.status(400).entity(entity).build();
                } else if (dataCenterInfo instanceof AmazonInfo) {
                    AmazonInfo amazonInfo = (AmazonInfo) dataCenterInfo;
                    String effectiveId = amazonInfo.get(AmazonInfo.MetaDataKey.instanceId);
                    if (effectiveId == null) {
                        amazonInfo.getMetadata().put(AmazonInfo.MetaDataKey.instanceId.getName(), info.getId());
                    }
                } else {
                    logger.warn("Registering DataCenterInfo of type {} without an appropriate id", dataCenterInfo.getClass());
                }
            }
        }

        registry.register(info, "true".equals(isReplication));
        return Response.status(204).build();  // 204 to be backwards compatible
    }
}
```


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

#### register info

```java
public void register(InstanceInfo registrant, int leaseDuration, boolean isReplication) {
        read.lock();
        try {
            Map<String, Lease<InstanceInfo>> gMap = registry.get(registrant.getAppName());
            REGISTER.increment(isReplication);
            if (gMap == null) {
                final ConcurrentHashMap<String, Lease<InstanceInfo>> gNewMap = new ConcurrentHashMap<String, Lease<InstanceInfo>>();
                gMap = registry.putIfAbsent(registrant.getAppName(), gNewMap);
                if (gMap == null) {
                    gMap = gNewMap;
                }
            }
            Lease<InstanceInfo> existingLease = gMap.get(registrant.getId());
            // Retain the last dirty timestamp without overwriting it, if there is already a lease
            if (existingLease != null && (existingLease.getHolder() != null)) {
                Long existingLastDirtyTimestamp = existingLease.getHolder().getLastDirtyTimestamp();
                Long registrationLastDirtyTimestamp = registrant.getLastDirtyTimestamp();
                logger.debug("Existing lease found (existing={}, provided={}", existingLastDirtyTimestamp, registrationLastDirtyTimestamp);

                // this is a > instead of a >= because if the timestamps are equal, we still take the remote transmitted
                // InstanceInfo instead of the server local copy.
                if (existingLastDirtyTimestamp > registrationLastDirtyTimestamp) {
                    logger.warn("There is an existing lease and the existing lease's dirty timestamp {} is greater" +
                            " than the one that is being registered {}", existingLastDirtyTimestamp, registrationLastDirtyTimestamp);
                    logger.warn("Using the existing instanceInfo instead of the new instanceInfo as the registrant");
                    registrant = existingLease.getHolder();
                }
            } else {
                // The lease does not exist and hence it is a new registration
                synchronized (lock) {
                    if (this.expectedNumberOfClientsSendingRenews > 0) {
                        // Since the client wants to register it, increase the number of clients sending renews
                        this.expectedNumberOfClientsSendingRenews = this.expectedNumberOfClientsSendingRenews + 1;
                        updateRenewsPerMinThreshold();
                    }
                }
                logger.debug("No previous lease information found; it is new registration");
            }
            Lease<InstanceInfo> lease = new Lease<>(registrant, leaseDuration);
            if (existingLease != null) {
                lease.setServiceUpTimestamp(existingLease.getServiceUpTimestamp());
            }
            gMap.put(registrant.getId(), lease);
            recentRegisteredQueue.add(new Pair<Long, String>(
                    System.currentTimeMillis(),
                    registrant.getAppName() + "(" + registrant.getId() + ")"));
            // This is where the initial state transfer of overridden status happens
            if (!InstanceStatus.UNKNOWN.equals(registrant.getOverriddenStatus())) {
                logger.debug("Found overridden status {} for instance {}. Checking to see if needs to be add to the "
                                + "overrides", registrant.getOverriddenStatus(), registrant.getId());
                if (!overriddenInstanceStatusMap.containsKey(registrant.getId())) {
                    logger.info("Not found overridden id {} and hence adding it", registrant.getId());
                    overriddenInstanceStatusMap.put(registrant.getId(), registrant.getOverriddenStatus());
                }
            }
            InstanceStatus overriddenStatusFromMap = overriddenInstanceStatusMap.get(registrant.getId());
            if (overriddenStatusFromMap != null) {
                logger.info("Storing overridden status {} from map", overriddenStatusFromMap);
                registrant.setOverriddenStatus(overriddenStatusFromMap);
            }

            // Set the status based on the overridden status rules
            InstanceStatus overriddenInstanceStatus = getOverriddenInstanceStatus(registrant, existingLease, isReplication);
            registrant.setStatusWithoutDirty(overriddenInstanceStatus);

            // If the lease is registered with UP status, set lease service up timestamp
            if (InstanceStatus.UP.equals(registrant.getStatus())) {
                lease.serviceUp();
            }
            registrant.setActionType(ActionType.ADDED);
            recentlyChangedQueue.add(new RecentlyChangedItem(lease));
            registrant.setLastUpdatedTimestamp();
            invalidateCache(registrant.getAppName(), registrant.getVIPAddress(), registrant.getSecureVipAddress());
            logger.info("Registered instance {}/{} with status {} (replication={})",
                    registrant.getAppName(), registrant.getId(), registrant.getStatus(), isReplication);
        } finally {
            read.unlock();
        }
    }
```

#### replicateToPeers
```java
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
```


```java
public class PeerEurekaNode {
    public void register(final InstanceInfo info) throws Exception {
        long expiryTime = System.currentTimeMillis() + getLeaseRenewalOf(info);
        batchingDispatcher.process(
                taskId("register", info),
                new InstanceReplicationTask(targetHost, Action.Register, info, null, true) {
                    public EurekaHttpResponse<Void> execute() {
                        return replicationClient.register(info);
                    }
                },
                expiryTime
        );
    }
}
```

## Server


```java
@Configuration(
    proxyBeanMethods = false
)
@Import({EurekaServerInitializerConfiguration.class})
@ConditionalOnBean({EurekaServerMarkerConfiguration.Marker.class})
@EnableConfigurationProperties({EurekaDashboardProperties.class, InstanceRegistryProperties.class, EurekaProperties.class})
@PropertySource({"classpath:/eureka/server.properties"})
public class EurekaServerAutoConfiguration implements WebMvcConfigurer {
    
}
```


```java

@Configuration(
    proxyBeanMethods = false
)
public class EurekaServerInitializerConfiguration implements ServletContextAware, SmartLifecycle, Ordered {
    @Autowired
    private EurekaServerConfig eurekaServerConfig;
    private ServletContext servletContext;
    @Autowired
    private ApplicationContext applicationContext;
    @Autowired
    private EurekaServerBootstrap eurekaServerBootstrap;
    private boolean running;
    private final int order = 1;

    public void start() {
        (new Thread(() -> {
            try {
                this.eurekaServerBootstrap.contextInitialized(this.servletContext);
                log.info("Started Eureka Server");
                this.publish(new EurekaRegistryAvailableEvent(this.getEurekaServerConfig()));
                this.running = true;
                this.publish(new EurekaServerStartedEvent(this.getEurekaServerConfig()));
            } catch (Exception var2) {
                log.error("Could not initialize Eureka servlet context", var2);
            }

        })).start();
    }


}
```
从其它peer同步注册信息

开启定时evict任务
```java
public class EurekaServerBootstrap {
   public void contextInitialized(ServletContext context) {
      try {
         initEurekaServerContext();

         context.setAttribute(EurekaServerContext.class.getName(), this.serverContext);
      }
      catch (Throwable e) {
         log.error("Cannot bootstrap eureka server :", e);
         throw new RuntimeException("Cannot bootstrap eureka server :", e);
      }
   }

   protected void initEurekaServerContext() throws Exception {
      // For backward compatibility
      JsonXStream.getInstance().registerConverter(new V1AwareInstanceInfoConverter(), XStream.PRIORITY_VERY_HIGH);
      XmlXStream.getInstance().registerConverter(new V1AwareInstanceInfoConverter(), XStream.PRIORITY_VERY_HIGH);

      if (isAws(this.applicationInfoManager.getInfo())) {
         this.awsBinder = new AwsBinderDelegate(this.eurekaServerConfig, this.eurekaClientConfig, this.registry,
                 this.applicationInfoManager);
         this.awsBinder.start();
      }

      EurekaServerContextHolder.initialize(this.serverContext);

      log.info("Initialized server context");

      // Copy registry from neighboring eureka node
      int registryCount = this.registry.syncUp();
      this.registry.openForTraffic(this.applicationInfoManager, registryCount);

      // Register all monitoring statistics.
      EurekaMonitors.registerAllStats();
   }
}
```


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
3. Eureka Server的peer节点需要存储全量数据 内存压力大 写请求容易达到峰值


Eureka2.0改进
1. pull模式转向push 实现更小粒度的订阅
2. 读写分离
## Links

- [Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md?id=service-registry)

## References

1. [Eureka Service源码流程图](https://www.processon.com/view/5f2dfff05653bb1b6117809a)