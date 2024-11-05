## Introduction



## start

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

#### contextInitialized
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

#### initialize



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



## Links
- [Eureka](/docs/CS/Framework/eureka/Eureka.md)