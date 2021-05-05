# Eureka



web.xml



### EurekaBootStrap

```java
public class EurekaBootStrap implements ServletContextListener {
    private static final Logger logger = LoggerFactory.getLogger(EurekaBootStrap.class);
    private static final String TEST = "test";
    private static final String ARCHAIUS_DEPLOYMENT_ENVIRONMENT = "archaius.deployment.environment";
    private static final String EUREKA_ENVIRONMENT = "eureka.environment";
    private static final String CLOUD = "cloud";
    private static final String DEFAULT = "default";
    private static final String ARCHAIUS_DEPLOYMENT_DATACENTER = "archaius.deployment.datacenter";
    private static final String EUREKA_DATACENTER = "eureka.datacenter";
    protected volatile EurekaServerContext serverContext;
    protected volatile AwsBinder awsBinder;
    private EurekaClient eurekaClient;

    public EurekaBootStrap() {
        this((EurekaClient)null);
    }

    public EurekaBootStrap(EurekaClient eurekaClient) {
        this.eurekaClient = eurekaClient;
    }

    public void contextInitialized(ServletContextEvent event) {
        try {
            this.initEurekaEnvironment();
            this.initEurekaServerContext();
            ServletContext sc = event.getServletContext();
            sc.setAttribute(EurekaServerContext.class.getName(), this.serverContext);
        } catch (Throwable var3) {
            logger.error("Cannot bootstrap eureka server :", var3);
            throw new RuntimeException("Cannot bootstrap eureka server :", var3);
        }
    }

    protected void initEurekaEnvironment() throws Exception {
        logger.info("Setting the eureka configuration..");
        String dataCenter = ConfigurationManager.getConfigInstance().getString("eureka.datacenter");
        if (dataCenter == null) {
            logger.info("Eureka data center value eureka.datacenter is not set, defaulting to default");
            ConfigurationManager.getConfigInstance().setProperty("archaius.deployment.datacenter", "default");
        } else {
            ConfigurationManager.getConfigInstance().setProperty("archaius.deployment.datacenter", dataCenter);
        }

        String environment = ConfigurationManager.getConfigInstance().getString("eureka.environment");
        if (environment == null) {
            ConfigurationManager.getConfigInstance().setProperty("archaius.deployment.environment", "test");
            logger.info("Eureka environment value eureka.environment is not set, defaulting to test");
        }

    }

    protected void initEurekaServerContext() throws Exception {
        EurekaServerConfig eurekaServerConfig = new DefaultEurekaServerConfig();
        JsonXStream.getInstance().registerConverter(new V1AwareInstanceInfoConverter(), 10000);
        XmlXStream.getInstance().registerConverter(new V1AwareInstanceInfoConverter(), 10000);
        logger.info("Initializing the eureka client...");
        logger.info(eurekaServerConfig.getJsonCodecName());
        ServerCodecs serverCodecs = new DefaultServerCodecs(eurekaServerConfig);
        ApplicationInfoManager applicationInfoManager = null;
        Object registry;
        if (this.eurekaClient == null) {
            registry = this.isCloud(ConfigurationManager.getDeploymentContext()) ? new CloudInstanceConfig() : new MyDataCenterInstanceConfig();
            applicationInfoManager = new ApplicationInfoManager((EurekaInstanceConfig)registry, (new EurekaConfigBasedInstanceInfoProvider((EurekaInstanceConfig)registry)).get());
            EurekaClientConfig eurekaClientConfig = new DefaultEurekaClientConfig();
            this.eurekaClient = new DiscoveryClient(applicationInfoManager, eurekaClientConfig);
        } else {
            applicationInfoManager = this.eurekaClient.getApplicationInfoManager();
        }

        if (this.isAws(applicationInfoManager.getInfo())) {
            registry = new AwsInstanceRegistry(eurekaServerConfig, this.eurekaClient.getEurekaClientConfig(), serverCodecs, this.eurekaClient);
            this.awsBinder = new AwsBinderDelegate(eurekaServerConfig, this.eurekaClient.getEurekaClientConfig(), (PeerAwareInstanceRegistry)registry, applicationInfoManager);
            this.awsBinder.start();
        } else {
            registry = new PeerAwareInstanceRegistryImpl(eurekaServerConfig, this.eurekaClient.getEurekaClientConfig(), serverCodecs, this.eurekaClient);
        }

        PeerEurekaNodes peerEurekaNodes = this.getPeerEurekaNodes((PeerAwareInstanceRegistry)registry, eurekaServerConfig, this.eurekaClient.getEurekaClientConfig(), serverCodecs, applicationInfoManager);
        this.serverContext = new DefaultEurekaServerContext(eurekaServerConfig, serverCodecs, (PeerAwareInstanceRegistry)registry, peerEurekaNodes, applicationInfoManager);
        EurekaServerContextHolder.initialize(this.serverContext);
        this.serverContext.initialize();
        logger.info("Initialized server context");
        int registryCount = ((PeerAwareInstanceRegistry)registry).syncUp();
        ((PeerAwareInstanceRegistry)registry).openForTraffic(applicationInfoManager, registryCount);
        EurekaMonitors.registerAllStats();
    }

    protected PeerEurekaNodes getPeerEurekaNodes(PeerAwareInstanceRegistry registry, EurekaServerConfig eurekaServerConfig, EurekaClientConfig eurekaClientConfig, ServerCodecs serverCodecs, ApplicationInfoManager applicationInfoManager) {
        PeerEurekaNodes peerEurekaNodes = new PeerEurekaNodes(registry, eurekaServerConfig, eurekaClientConfig, serverCodecs, applicationInfoManager);
        return peerEurekaNodes;
    }

    public void contextDestroyed(ServletContextEvent event) {
        try {
            logger.info("{} Shutting down Eureka Server..", new Date());
            ServletContext sc = event.getServletContext();
            sc.removeAttribute(EurekaServerContext.class.getName());
            this.destroyEurekaServerContext();
            this.destroyEurekaEnvironment();
        } catch (Throwable var3) {
            logger.error("Error shutting down eureka", var3);
        }

        logger.info("{} Eureka Service is now shutdown...", new Date());
    }

    protected void destroyEurekaServerContext() throws Exception {
        EurekaMonitors.shutdown();
        if (this.awsBinder != null) {
            this.awsBinder.shutdown();
        }

        if (this.serverContext != null) {
            this.serverContext.shutdown();
        }

    }

    protected void destroyEurekaEnvironment() throws Exception {
    }

    protected boolean isAws(InstanceInfo selfInstanceInfo) {
        boolean result = Name.Amazon == selfInstanceInfo.getDataCenterInfo().getName();
        logger.info("isAws returned {}", result);
        return result;
    }

    protected boolean isCloud(DeploymentContext deploymentContext) {
        logger.info("Deployment datacenter is {}", deploymentContext.getDeploymentDatacenter());
        return "cloud".equals(deploymentContext.getDeploymentDatacenter());
    }
}
```



- EurekaServerConfig
- EurekaInstanceConfig
- EurekaClientConfig



### DiscoveryClient



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



###  CircularQueue

Delegate a **[ArrayBlockingQueue](/docs/CS/Java/JDK/Collection/BlockingQueue.md)** and override offer method.

```java
static class CircularQueue<E> extends AbstractQueue<E> {
    private final ArrayBlockingQueue<E> delegate;
    private final int capacity;

    public CircularQueue(int capacity) {
        this.capacity = capacity;
        this.delegate = new ArrayBlockingQueue(capacity);
    }

    public Iterator<E> iterator() {
        return this.delegate.iterator();
    }

    public int size() {
        return this.delegate.size();
    }

    public boolean offer(E e) {
        while(!this.delegate.offer(e)) {
            this.delegate.poll();
        }
        return true;
    }

    public E poll() {
        return this.delegate.poll();
    }

    public E peek() {
        return this.delegate.peek();
    }

    public void clear() {
        this.delegate.clear();
    }

    public Object[] toArray() {
        return this.delegate.toArray();
    }
}
```



### RateLimitingFilter







