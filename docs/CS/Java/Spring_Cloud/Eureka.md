## Introduction

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
2. notify [StatusChangeListener](/docs/CS/Java/Spring_Cloud/Eureka.md?id=Status-Change)

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

1. schedule 2 therads
2. heartbeat 1 thread
3. cacheRefresh 1 thread
4. fetchRegistry
5. initScheduledTasks
    - schedule CacheRefreshThread to refreshRegistry
    - shceule heatBeatTask
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

```java
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
```

### CircularQueue

Delegate a **[ArrayBlockingQueue](/docs/CS/Java/JDK/Collection/Queue.md?id=ArrayBlockingQueue)** and override offer method.

```java
static class CircularQueue<E> extends AbstractQueue<E> {
    private final ArrayBlockingQueue<E> delegate;
    private final int capacity;

    public CircularQueue(int capacity) {
        this.capacity = capacity;
        this.delegate = new ArrayBlockingQueue(capacity);
    }

    // discard first node
    public boolean offer(E e) {
        while(!this.delegate.offer(e)) {
            this.delegate.poll();
        }
        return true;
    }
...
}
```

### RateLimitingFilter
