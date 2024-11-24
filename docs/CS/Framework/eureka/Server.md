## Introduction





编译测试

<!-- tabs:start -->


###### **改动后**

```java
public class EurekaClientServerRestIntegrationTest {
    private static void startServer() throws Exception {
        server = new Server(8080);

        WebAppContext webAppCtx = new WebAppContext(new File("./src/main/webapp").getAbsolutePath(), "/");
        webAppCtx.setDescriptor(new File("./src/main/webapp/WEB-INF/web.xml").getAbsolutePath());
        webAppCtx.setResourceBase(new File("./src/main/resources").getAbsolutePath());
        webAppCtx.setClassLoader(Thread.currentThread().getContextClassLoader());
        server.setHandler(webAppCtx);
        server.start();

        eurekaServiceUrl = "http://localhost:8080/v2";
    }
}
```

###### **改动前**

原有实现是在war包上进行
```java
public class EurekaClientServerRestIntegrationTest {
    private static void startServer() throws Exception {
        File warFile = findWar();

        server = new Server(8080);

        WebAppContext webapp = new WebAppContext();
        webapp.setContextPath("/");
        webapp.setWar(warFile.getAbsolutePath());
        server.setHandler(webapp);

        server.start();

        eurekaServiceUrl = "http://localhost:8080/v2";
    }
}
```

<!-- tabs:end -->


## start

Eureka Server首先是个web容器

- EurekaServerBootstrap是在 Spring Cloud 启动 eureka server 的类
- EurekaBootStrap 是用来启动 eureka server 的类 EurekaBootStrap 实现了 ServletContextListener，在容器启动的时候就会调用 EurekaBootStrap#contextInitialized 从而完成对 Eureka 核心组件的初始化




### EurekaServerBootstrap

EurekaServer在SpringCloud中的启动分析与 [EurekaBootStrap](/docs/CS/Framework/eureka/Server.md?id=EurekaBootStrap) 类似

@EnableEurekaServer开启 使用自动配置EurekaServerAutoConfiguration
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
                this.publish(new EurekaRegistryAvailableEvent(this.getEurekaServerConfig()));
                this.running = true;
                this.publish(new EurekaServerStartedEvent(this.getEurekaServerConfig()));
            } catch (Exception var2) {
            }

        })).start();
    }


}
```

#### initEurekaServerContext

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


      // Copy registry from neighboring eureka node
      int registryCount = this.registry.syncUp();
      this.registry.openForTraffic(this.applicationInfoManager, registryCount);

      // Register all monitoring statistics.
      EurekaMonitors.registerAllStats();
   }
}
```

### EurekaBootStrap


Initializes Eureka, including syncing up with other Eureka peers and publishing the registry.
```java
public abstract class EurekaBootStrap implements ServletContextListener {
    @Override
    public void contextInitialized(ServletContextEvent event) {
        try {
            initEurekaEnvironment();
            initEurekaServerContext();

            ServletContext sc = event.getServletContext();
            sc.setAttribute(EurekaServerContext.class.getName(), serverContext);
        } catch (Throwable e) {
            logger.error("Cannot bootstrap eureka server :", e);
            throw new RuntimeException("Cannot bootstrap eureka server :", e);
        }
    }
}
```

Double check 的单例配置

```java
public abstract class EurekaBootStrap implements ServletContextListener {
    protected void initEurekaEnvironment() throws Exception {
        String dataCenter = ConfigurationManager.getConfigInstance().getString(EUREKA_DATACENTER);
        if (dataCenter == null) {
            ConfigurationManager.getConfigInstance().setProperty(ARCHAIUS_DEPLOYMENT_DATACENTER, DEFAULT);
        } else {
            ConfigurationManager.getConfigInstance().setProperty(ARCHAIUS_DEPLOYMENT_DATACENTER, dataCenter);
        }
        String environment = ConfigurationManager.getConfigInstance().getString(EUREKA_ENVIRONMENT);
        if (environment == null) {
            ConfigurationManager.getConfigInstance().setProperty(ARCHAIUS_DEPLOYMENT_ENVIRONMENT, TEST);
        }
    }
}
```

#### initEurekaServerContext

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
        // init DiscoveryClient
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
                    eurekaClient,
                    eurekaServerHttpClientFactory
            );
            awsBinder = new AwsBinderDelegate(eurekaServerConfig, eurekaClient.getEurekaClientConfig(), registry, applicationInfoManager);
            awsBinder.start();
        } else {
            registry = new PeerAwareInstanceRegistryImpl(
                    eurekaServerConfig,
                    eurekaClient.getEurekaClientConfig(),
                    serverCodecs,
                    eurekaClient,
                    eurekaServerHttpClientFactory
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

        // Copy registry from neighboring eureka node
        int registryCount = registry.syncUp();
        registry.openForTraffic(applicationInfoManager, registryCount);

        // Register all monitoring statistics.
        EurekaMonitors.registerAllStats();
    }
}
```

init DiscoveryClient



create PeerAwareInstanceRegistry


init PeerEurekaNodes


#### initialize
init EurekaServerContext

```java
@Singleton
public class DefaultEurekaServerContext implements EurekaServerContext {
    @PostConstruct
    @Override
    public void initialize() {
        peerEurekaNodes.start();
        try {
            registry.init(peerEurekaNodes);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }
}
```


```java
public abstract class PeerEurekaNodes {
    public void start() {
        taskExecutor = Executors.newSingleThreadScheduledExecutor(
                new ThreadFactory() {
                    @Override
                    public Thread newThread(Runnable r) {
                        Thread thread = new Thread(r, "Eureka-PeerNodesUpdater");
                        thread.setDaemon(true);
                        return thread;
                    }
                }
        );
        try {
            updatePeerEurekaNodes(resolvePeerUrls());
            Runnable peersUpdateTask = new Runnable() {
                @Override
                public void run() {
                    try {
                        updatePeerEurekaNodes(resolvePeerUrls());
                    } catch (Throwable e) {
                        logger.error("Cannot update the replica Nodes", e);
                    }

                }
            };
            taskExecutor.scheduleWithFixedDelay(
                    peersUpdateTask,
                    serverConfig.getPeerEurekaNodesUpdateIntervalMs(),
                    serverConfig.getPeerEurekaNodesUpdateIntervalMs(),
                    TimeUnit.MILLISECONDS
            );
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
        for (PeerEurekaNode node : peerEurekaNodes) {
            logger.info("Replica node URL:  {}", node.getServiceUrl());
        }
    }
}
```


初始化了缓存信息

```java
@Singleton
public class PeerAwareInstanceRegistryImpl extends AbstractInstanceRegistry implements PeerAwareInstanceRegistry {
    @Override
    public void init(PeerEurekaNodes peerEurekaNodes) throws Exception {
        this.numberOfReplicationsLastMin.start();
        this.peerEurekaNodes = peerEurekaNodes;
        initializedResponseCache();
        scheduleRenewalThresholdUpdateTask();
        initRemoteRegionRegistry();
    }
}
```

##### initializedResponseCache

ResponseCacheImpl 初始化

- 在 ResponseCacheImpl 初始化的时候通过 [ConcurrentHashMap](/docs/CS/Java/JDK/Collection/Map.md?id=ConcurrentHashMap) 构建一级只读缓存 readOnlyCacheMap；
- 通过 [Guava]() 创建的 readWriteCacheMap expire timeout = 180s
- readOnlyCacheMap 会通过定时任务 TimerTask 从 readWriteCacheMap 构建二级读写缓存进行比对更新(每 30 秒执行一次)
- 在 ResponseCacheImpl 中还提供了 invalidate 方法进行手动过期，当 Eureka Server 发生了服务注册、下线、故障会自动过期该缓存

```java
// AbstractInstanceRegistry
@Override
public synchronized void initializedResponseCache() {
    if (responseCache == null) {
        responseCache = new ResponseCacheImpl(serverConfig, serverCodecs, this);
    }
}

// ResponseCacheImpl
public class ResponseCacheImpl implements ResponseCache {
    private final ConcurrentMap<Key, Value> readOnlyCacheMap = new ConcurrentHashMap<Key, Value>();
    private final java.util.Timer timer = new java.util.Timer("Eureka-CacheFillTimer", true);

    ResponseCacheImpl(EurekaServerConfig serverConfig, ServerCodecs serverCodecs, AbstractInstanceRegistry registry) {
        this.serverCodecs = serverCodecs;
        this.shouldUseReadOnlyResponseCache = serverConfig.shouldUseReadOnlyResponseCache();
        this.registry = registry;

        long responseCacheUpdateIntervalMs = serverConfig.getResponseCacheUpdateIntervalMs();
        this.readWriteCacheMap =
                CacheBuilder.newBuilder().initialCapacity(serverConfig.getInitialCapacityOfResponseCache())
                        .expireAfterWrite(serverConfig.getResponseCacheAutoExpirationInSeconds(), TimeUnit.SECONDS)
                        .removalListener(new RemovalListener<Key, Value>() {
                            @Override
                            public void onRemoval(RemovalNotification<Key, Value> notification) {
                                Key removedKey = notification.getKey();
                                if (removedKey.hasRegions()) {
                                    Key cloneWithNoRegions = removedKey.cloneWithoutRegions();
                                    regionSpecificKeys.remove(cloneWithNoRegions, removedKey);
                                }
                            }
                        })
                        .build(new CacheLoader<Key, Value>() {
                            @Override
                            public Value load(Key key) throws Exception {
                                if (key.hasRegions()) {
                                    Key cloneWithNoRegions = key.cloneWithoutRegions();
                                    regionSpecificKeys.put(cloneWithNoRegions, key);
                                }
                                Value value = generatePayload(key);
                                return value;
                            }
                        });

        if (shouldUseReadOnlyResponseCache) {
            timer.schedule(getCacheUpdateTask(),
                    new Date(((System.currentTimeMillis() / responseCacheUpdateIntervalMs) * responseCacheUpdateIntervalMs)
                            + responseCacheUpdateIntervalMs),
                    responseCacheUpdateIntervalMs);
        }
        SpectatorUtil.monitoredValue("responseCacheSize", this, ResponseCacheImpl::getCurrentSize);
    }
}
```


当 Eureka Client 获取注册表的时候，首先会从只读缓存中获取数据
如果只读缓存为空就会从读写缓存中获取数据，并把读取到的值添加到只读缓存当中
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


#### sync registry

Copy registry from neighboring eureka node

```java
@Singleton
public class PeerAwareInstanceRegistryImpl extends AbstractInstanceRegistry implements PeerAwareInstanceRegistry {

    @Override
    public int syncUp() {
        // Copy entire entry from neighboring DS node
        int count = 0;

        for (int i = 0; ((i < serverConfig.getRegistrySyncRetries()) && (count == 0)); i++) {
            if (i > 0) {
                try {
                    Thread.sleep(serverConfig.getRegistrySyncRetryWaitMs());
                } catch (InterruptedException e) {
                    logger.warn("Interrupted during registry transfer..");
                    break;
                }
            }
            Applications apps = eurekaClient.getApplications();
            for (Application app : apps.getRegisteredApplications()) {
                for (InstanceInfo instance : app.getInstances()) {
                    try {
                        if (isRegisterable(instance)) {
                            register(instance, instance.getLeaseInfo().getDurationInSecs(), true);
                            count++;
                        }
                    } catch (Throwable t) {
                        logger.error("During DS init copy", t);
                    }
                }
            }
        }
        return count;
    }
}
```

开启心跳统计的定时任务

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
public abstract class AbstractInstanceRegistry implements InstanceRegistry {
    public void evict(long additionalLeaseMs) {
        logger.debug("Running the evict task");

        if (!isLeaseExpirationEnabled()) {
            logger.debug("DS: lease expiration is currently disabled.");
            return;
        }

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
}
```

判断是否允许expire
- 首先判断 Eureka Server 是否开启了自我保护机制 eureka.enableSelfPreservation 为 true 开启反之不开启。如果没有开启直接返回 true，可以进行服务过期处理。
- 然后判断每分钟期望的续约数(numberOfRenewsPerMinThreshold) 大于 0 并且实际每分钟的续约数(getNumOfRenewsInLastMin()) 大于每分钟期望的续约数(numberOfRenewsPerMinThreshold

```java
@Override
public boolean isLeaseExpirationEnabled() {
    if (!isSelfPreservationModeEnabled()) {
        // The self preservation mode is disabled, hence allowing the instances to expire.
        return true;
    }
    return numberOfRenewsPerMinThreshold > 0 && getNumOfRenewsInLastMin() > numberOfRenewsPerMinThreshold;
}
```


```java
protected void updateRenewsPerMinThreshold() {
    this.numberOfRenewsPerMinThreshold = (int) (this.expectedNumberOfClientsSendingRenews
            * (60.0 / serverConfig.getExpectedClientRenewalIntervalSeconds())
            * serverConfig.getRenewalPercentThreshold());
}
```

## serve

ServletContainer是 jersey 框架的核心处理类，每一个 Web 框架都会有一个前端处理器。统一接收并处理客户端的请求。类似于 Spring MVC 中的 DispatcherServlet
与 DispatcherServlet 是一个 Servlet 不同的是它既是一个 Servlet 同时也实现了 Filter


#### register monitor


## Links
- [Eureka](/docs/CS/Framework/eureka/Eureka.md)