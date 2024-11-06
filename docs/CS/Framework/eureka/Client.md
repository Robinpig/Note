## Introduction



## Start
start -> registry -> getEurekaClient -> init

-> notify -> register in a single scheduler

创建eurekaClient
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

### client::start

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

## Links
- [Eureka](/docs/CS/Framework/eureka/Eureka.md)