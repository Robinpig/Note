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



## DiscoveryClient

```java
// org.springframework.cloud.client.discovery.EnableDiscoveryClient
@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
@Documented
@Inherited
@Import(EnableDiscoveryClientImportSelector.class)
public @interface EnableDiscoveryClient {

	// If true, the ServiceRegistry will automatically register the local server.
	boolean autoRegister() default true;

}
```

```java

/**
 * Represents read operations commonly available to discovery services such as Netflix
 * Eureka or consul.io.
 */
public interface DiscoveryClient extends Ordered {

	/**
	 * Default order of the discovery client.
	 */
	int DEFAULT_ORDER = 0;

	/**
	 * A human-readable description of the implementation, used in HealthIndicator.
	 * @return The description.
	 */
	String description();

	/**
	 * Gets all ServiceInstances associated with a particular serviceId.
	 * @param serviceId The serviceId to query.
	 * @return A List of ServiceInstance.
	 */
	List<ServiceInstance> getInstances(String serviceId);

	/**
	 * @return All known service IDs.
	 */
	List<String> getServices();

	/**
	 * Can be used to verify the client is valid and able to make calls.
	 * <p>
	 * A successful invocation with no exception thrown implies the client is able to make
	 * calls.
	 * <p>
	 * The default implementation simply calls {@link #getServices()} - client
	 * implementations can override with a lighter weight operation if they choose to.
	 */
	default void probe() {
		getServices();
	}

	/**
	 * Default implementation for getting order of discovery clients.
	 * @return order
	 */
	@Override
	default int getOrder() {
		return DEFAULT_ORDER;
	}

}
```


```java

/**
 * A DiscoveryClient implementation for Eureka.
 */
public class EurekaDiscoveryClient implements DiscoveryClient {

	public static final String DESCRIPTION = "Spring Cloud Eureka Discovery Client";

	private final EurekaClient eurekaClient;

	private final EurekaClientConfig clientConfig;

	@Deprecated
	public EurekaDiscoveryClient(EurekaInstanceConfig config, EurekaClient eurekaClient) {
		this(eurekaClient, eurekaClient.getEurekaClientConfig());
	}

	public EurekaDiscoveryClient(EurekaClient eurekaClient,
			EurekaClientConfig clientConfig) {
		this.clientConfig = clientConfig;
		this.eurekaClient = eurekaClient;
	}

	@Override
	public String description() {
		return DESCRIPTION;
	}

	@Override
	public List<ServiceInstance> getInstances(String serviceId) {
		List<InstanceInfo> infos = this.eurekaClient.getInstancesByVipAddress(serviceId,
				false);
		List<ServiceInstance> instances = new ArrayList<>();
		for (InstanceInfo info : infos) {
			instances.add(new EurekaServiceInstance(info));
		}
		return instances;
	}

	@Override
	public List<String> getServices() {
		Applications applications = this.eurekaClient.getApplications();
		if (applications == null) {
			return Collections.emptyList();
		}
		List<Application> registered = applications.getRegisteredApplications();
		List<String> names = new ArrayList<>();
		for (Application app : registered) {
			if (app.getInstances().isEmpty()) {
				continue;
			}
			names.add(app.getName().toLowerCase());

		}
		return names;
	}

	@Override
	public int getOrder() {
		return clientConfig instanceof Ordered ? ((Ordered) clientConfig).getOrder()
				: DiscoveryClient.DEFAULT_ORDER;
	}

	/**
	 * An Eureka-specific {@link ServiceInstance} implementation. Extends
	 * {@link org.springframework.cloud.netflix.eureka.EurekaServiceInstance} for
	 * backwards compatibility.
	 *
	 * @deprecated In favor of
	 * {@link org.springframework.cloud.netflix.eureka.EurekaServiceInstance}.
	 */
	@Deprecated
	public static class EurekaServiceInstance
			extends org.springframework.cloud.netflix.eureka.EurekaServiceInstance {

		public EurekaServiceInstance(InstanceInfo instance) {
			super(instance);
		}

	}

}
```

Define a simple interface over the current DiscoveryClient implementation. This interface does NOT try to clean up the current client interface for eureka 1.x. Rather it tries to provide an easier transition path from eureka 1.x to eureka 2.x. EurekaClient API contracts are: - provide the ability to get InstanceInfo(s) (in various different ways) - provide the ability to get data about the local Client (known regions, own AZ etc) - provide the ability to register and access the healthcheck handler for the client
```java
@ImplementedBy(DiscoveryClient.class)
public interface EurekaClient extends LookupService {


}
```



The class that is instrumental for interactions with Eureka Server.
Eureka Client is responsible for a) Registering the instance with Eureka Server b) Renewalof the lease with Eureka Server c) Cancellation of the lease from Eureka Server during shutdown
d) Querying the list of services/instances registered with Eureka Server

Eureka Client needs a configured list of Eureka Server java.net.URLs to talk to.These java.net.URLs are typically amazon elastic eips which do not change. All of the functions defined above fail-over to other java.net.URLs specified in the list in the case of failure.

```java
// com.netflix.discovery.DiscoveryClient
@Singleton
public class DiscoveryClient implements EurekaClient {}
```

finally, init the schedule tasks (e.g. cluster resolvers, heartbeat, instanceInfo replicator, fetch
`com.netflix.discovery.DiscoveryClient#initScheduledTasks()`



### register
```java
// com.netflix.discovery.DiscoveryClient
/**
 * Register with the eureka service by making the appropriate REST call.
 */
boolean register() throws Throwable {
    logger.info(PREFIX + "{}: registering service...", appPathIdentifier);
    EurekaHttpResponse<Void> httpResponse;
    try {
        httpResponse = eurekaTransport.registrationClient.register(instanceInfo);
    } catch (Exception e) {
        logger.warn(PREFIX + "{} - registration failed {}", appPathIdentifier, e.getMessage(), e);
        throw e;
    }
    if (logger.isInfoEnabled()) {
        logger.info(PREFIX + "{} - registration status: {}", appPathIdentifier, httpResponse.getStatusCode());
    }
    return httpResponse.getStatusCode() == Status.NO_CONTENT.getStatusCode();
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



###  CircularQueue

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




