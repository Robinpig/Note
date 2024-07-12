## Introduction

[NACOS-DISCOVERY-QUICK-START](https://github.com/nacos-group/nacos-spring-boot-project/blob/master/NACOS-DISCOVERY-QUICK-START.md)

## Service Registry


#### AutoConfiguration
```java
@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties
@ConditionalOnNacosDiscoveryEnabled
@ConditionalOnProperty(
        value = {"spring.cloud.service-registry.auto-registration.enabled"},
        matchIfMissing = true
)
@AutoConfigureAfter({AutoServiceRegistrationConfiguration.class, AutoServiceRegistrationAutoConfiguration.class, NacosDiscoveryAutoConfiguration.class})
public class NacosServiceRegistryAutoConfiguration {
    
}
```

Override [Spring Cloud register](/docs/CS/Java/Spring_Cloud/Spring_Cloud.md?id=AbstractAutoServiceRegistration)

```java
public class NacosServiceRegistry implements ServiceRegistry<Registration> {
    @Override
    public void register(Registration registration) {
        NamingService namingService = namingService();
        String serviceId = registration.getServiceId();
        String group = nacosDiscoveryProperties.getGroup();

        Instance instance = getNacosInstanceFromRegistration(registration);

        try {
            namingService.registerInstance(serviceId, group, instance);
        } catch (Exception e) {
           // log
        }
    }
}
```

### NamingService

Get NamingService by Constructor.newInstance(properties);

1. HostReactor schedule updateTask every 10s
2. BeatReactor schedule BeatTask
```java
public class NacosNamingService implements NamingService {
    public NacosNamingService(Properties properties) throws NacosException {
        init(properties);
    }

    private void init(Properties properties) throws NacosException {
        ValidatorUtils.checkInitParam(properties);
        this.namespace = InitUtils.initNamespaceForNaming(properties);
        InitUtils.initSerialization();
        initServerAddr(properties);
        InitUtils.initWebRootContext(properties);
        initCacheDir();
        initLogName(properties);

        this.serverProxy = new NamingProxy(this.namespace, this.endpoint, this.serverList, properties);
        this.beatReactor = new BeatReactor(this.serverProxy, initClientBeatThreadCount(properties));
        this.hostReactor = new HostReactor(this.serverProxy, beatReactor, this.cacheDir, isLoadCacheAtStart(properties),
                isPushEmptyProtect(properties), initPollingThreadCount(properties));
    }
}
```


### registerInstance

If you'd like to use "Service Registry" features, NamingService is a core service interface to get or publish config, 
you could use "Dependency Injection" to inject NamingService instance in your Spring Beans.

And [Dubbo](/docs/CS/Java/Dubbo/registry.md?id=NacosRegistry) wrapped it.

1. schedule BeatTask
2. registerService

```java
public class NacosNamingService implements NamingService {
    @Override
    public void registerInstance(String serviceName, String groupName, Instance instance) throws NacosException {
        NamingUtils.checkInstanceIsLegal(instance);
        String groupedServiceName = NamingUtils.getGroupedName(serviceName, groupName);
        if (instance.isEphemeral()) {
            BeatInfo beatInfo = beatReactor.buildBeatInfo(groupedServiceName, instance);
            beatReactor.addBeatInfo(groupedServiceName, beatInfo);
        }
        serverProxy.registerService(groupedServiceName, groupName, instance);
    }
}
```

#### addBeatInfo

```java
public void addBeatInfo(String serviceName, BeatInfo beatInfo) {
        NAMING_LOGGER.info("[BEAT] adding beat: {} to beat map.", beatInfo);
        String key = buildKey(serviceName, beatInfo.getIp(), beatInfo.getPort());
        BeatInfo existBeat = null;
        //fix #1733
        if ((existBeat = dom2Beat.remove(key)) != null) {
        existBeat.setStopped(true);
        }
        dom2Beat.put(key, beatInfo);
        executorService.schedule(new BeatTask(beatInfo), beatInfo.getPeriod(), TimeUnit.MILLISECONDS);
        MetricsMonitor.getDom2BeatSizeMonitor().set(dom2Beat.size());
}
```

call [Server beat](/docs/CS/Java/Spring_Cloud/nacos/registry.md?id=server-beat).

```java
class BeatTask implements Runnable {

        BeatInfo beatInfo;

        public BeatTask(BeatInfo beatInfo) {
            this.beatInfo = beatInfo;
        }

        @Override
        public void run() {
            if (beatInfo.isStopped()) {
                return;
            }
            long nextTime = beatInfo.getPeriod();
            try {
                JSONObject result = serverProxy.sendBeat(beatInfo, BeatReactor.this.lightBeatEnabled);
                long interval = result.getIntValue("clientBeatInterval");
                boolean lightBeatEnabled = false;
                if (result.containsKey(CommonParams.LIGHT_BEAT_ENABLED)) {
                    lightBeatEnabled = result.getBooleanValue(CommonParams.LIGHT_BEAT_ENABLED);
                }
                BeatReactor.this.lightBeatEnabled = lightBeatEnabled;
                if (interval > 0) {
                    nextTime = interval;
                }
                int code = NamingResponseCode.OK;
                if (result.containsKey(CommonParams.CODE)) {
                    code = result.getIntValue(CommonParams.CODE);
                }
                if (code == NamingResponseCode.RESOURCE_NOT_FOUND) {
                    Instance instance = new Instance();
                    instance.setPort(beatInfo.getPort());
                    instance.setIp(beatInfo.getIp());
                    instance.setWeight(beatInfo.getWeight());
                    instance.setMetadata(beatInfo.getMetadata());
                    instance.setClusterName(beatInfo.getCluster());
                    instance.setServiceName(beatInfo.getServiceName());
                    instance.setInstanceId(instance.getInstanceId());
                    instance.setEphemeral(true);
                    try {
                        serverProxy.registerService(beatInfo.getServiceName(),
                            NamingUtils.getGroupName(beatInfo.getServiceName()), instance);
                    } catch (Exception ignore) {
                    }
                }
            } catch (NacosException ne) {
                NAMING_LOGGER.error("[CLIENT-BEAT] failed to send beat: {}, code: {}, msg: {}",
                    JSON.toJSONString(beatInfo), ne.getErrCode(), ne.getErrMsg());

            }
            executorService.schedule(new BeatTask(beatInfo), nextTime, TimeUnit.MILLISECONDS);
        }
    }
```


#### registerService

AbstractNamingClientProxy
1. NamingHttpClientProxy
2. NamingGrpcClientProxy

```java
public void registerService(String serviceName, String groupName, Instance instance) throws NacosException {

        final Map<String, String> params = new HashMap<String, String>(9);
        params.put(CommonParams.NAMESPACE_ID, namespaceId);
        params.put(CommonParams.SERVICE_NAME, serviceName);
        params.put(CommonParams.GROUP_NAME, groupName);
        params.put(CommonParams.CLUSTER_NAME, instance.getClusterName());
        params.put("ip", instance.getIp());
        params.put("port", String.valueOf(instance.getPort()));
        params.put("weight", String.valueOf(instance.getWeight()));
        params.put("enable", String.valueOf(instance.isEnabled()));
        params.put("healthy", String.valueOf(instance.isHealthy()));
        params.put("ephemeral", String.valueOf(instance.isEphemeral()));
        params.put("metadata", JSON.toJSONString(instance.getMetadata()));

        reqAPI(UtilAndComs.NACOS_URL_INSTANCE, params, HttpMethod.POST); // url = /nacos/v1/ns/instance

    }
```

##### reqApi

Random for load balance

use NacosRestTemplate call [Server register](/docs/CS/Java/Spring_Cloud/nacos/registry.md?id=server-Register) in `callServer`.


```java
 public String reqApi(String api, Map<String, String> params, Map<String, String> body, List<String> servers,
            String method) throws NacosException {
        params.put(CommonParams.NAMESPACE_ID, getNamespaceId());
        
        NacosException exception = new NacosException();
        
        if (StringUtils.isNotBlank(nacosDomain)) {
            for (int i = 0; i < maxRetry; i++) {
                try {
                    return callServer(api, params, body, nacosDomain, method);
                } catch (NacosException e) {
                    exception = e;
                }
            }
        } else {
            Random random = new Random(System.currentTimeMillis());
            int index = random.nextInt(servers.size());
            
            for (int i = 0; i < servers.size(); i++) {
                String server = servers.get(index);
                try {
                    return callServer(api, params, body, server, method);
                } catch (NacosException e) {
                    exception = e;
                }
                index = (index + 1) % servers.size();
            }
        }
        throw new NacosException(exception.getErrCode(),
                "failed to req API:" + api + " after all servers(" + servers + ") tried: " + exception.getMessage());
}
```

## Server Register


##### **InstanceController**

```java
// com.alibaba.nacos.naming.controllers.InstanceController /v1/ns/instance
@CanDistro
@PostMapping
@TpsControl(pointName = "NamingInstanceRegister", name = "HttpNamingInstanceRegister")
@Secured(action = ActionTypes.WRITE)
public String register(HttpServletRequest request) throws Exception {

    final String namespaceId = WebUtils.optional(request, CommonParams.NAMESPACE_ID,
            Constants.DEFAULT_NAMESPACE_ID);
    final String serviceName = WebUtils.required(request, CommonParams.SERVICE_NAME);
    NamingUtils.checkServiceNameFormat(serviceName);

    final Instance instance = HttpRequestInstanceBuilder.newBuilder()
            .setDefaultInstanceEphemeral(switchDomain.isDefaultInstanceEphemeral()).setRequest(request).build();

    getInstanceOperator().registerInstance(namespaceId, serviceName, instance);
    NotifyCenter.publishEvent(new RegisterInstanceTraceEvent(System.currentTimeMillis(),
            NamingRequestUtil.getSourceIpForHttpRequest(request), false, namespaceId,
            NamingUtils.getGroupName(serviceName), NamingUtils.getServiceName(serviceName), instance.getIp(),
            instance.getPort()));
    return "ok";
}
```

##### **InstanceControllerV2**
```java
@CanDistro
@PostMapping
@TpsControl(pointName = "NamingInstanceRegister", name = "HttpNamingInstanceRegister")
@Secured(action = ActionTypes.WRITE)
public Result<String> register(InstanceForm instanceForm) throws NacosException {
    // check param
    instanceForm.validate();
    checkWeight(instanceForm.getWeight());
    // build instance
    Instance instance = buildInstance(instanceForm);
    instanceServiceV2.registerInstance(instanceForm.getNamespaceId(), buildCompositeServiceName(instanceForm),
            instance);
    NotifyCenter.publishEvent(
            new RegisterInstanceTraceEvent(System.currentTimeMillis(), NamingRequestUtil.getSourceIp(), false,
                    instanceForm.getNamespaceId(), instanceForm.getGroupName(), instanceForm.getServiceName(),
                    instance.getIp(), instance.getPort()));
    return Result.success("ok");
}
```


```java
// ServiceManager
public void registerInstance(String namespaceId, String serviceName, Instance instance) throws NacosException {
    
    createEmptyService(namespaceId, serviceName, instance.isEphemeral());
    
    Service service = getService(namespaceId, serviceName);
    
    addInstance(namespaceId, serviceName, instance.isEphemeral(), instance);
}
```
### createService

Create service if not exist.
```java
public void createServiceIfAbsent(String namespaceId, String serviceName, boolean local, Cluster cluster)
        throws NacosException {
    Service service = getService(namespaceId, serviceName);
    if (service == null) {
        
        Loggers.SRV_LOG.info("creating empty service {}:{}", namespaceId, serviceName);
        service = new Service();
        service.setName(serviceName);
        service.setNamespaceId(namespaceId);
        service.setGroupName(NamingUtils.getGroupName(serviceName));
        // now validate the service. if failed, exception will be thrown
        service.setLastModifiedMillis(System.currentTimeMillis());
        service.recalculateChecksum();
        if (cluster != null) {
            cluster.setService(service);
            service.getClusterMap().put(cluster.getName(), cluster);
        }
        service.validate(); // validate service name & cluster name is mathch 0-9a-zA-Z- 
        
        putServiceAndInit(service);
        if (!local) {
            addOrReplaceService(service);
        }
    }
}
```

#### putServiceAndInit

```java
    private void putServiceAndInit(Service service) throws NacosException {
        putService(service);
        service = getService(service.getNamespaceId(), service.getName());
        service.init();
        consistencyService
        .listen(KeyBuilder.buildInstanceListKey(service.getNamespaceId(), service.getName(), true), service);
        consistencyService
        .listen(KeyBuilder.buildInstanceListKey(service.getNamespaceId(), service.getName(), false), service);
    }    

    public void init() {
        HealthCheckReactor.scheduleCheck(clientBeatCheckTask);
        for (Map.Entry<String, Cluster> entry : clusterMap.entrySet()) {
            entry.getValue().setService(this);
            entry.getValue().init();
        }
    }
```

#### addInstance

Add instance to service.

```java
public void addInstance(String namespaceId, String serviceName, boolean ephemeral, Instance... ips)
        throws NacosException {
    
    String key = KeyBuilder.buildInstanceListKey(namespaceId, serviceName, ephemeral);
    
    Service service = getService(namespaceId, serviceName);
    
    synchronized (service) {
        List<Instance> instanceList = addIpAddresses(service, ephemeral, ips);
        
        Instances instances = new Instances();
        instances.setInstanceList(instanceList);
        
        consistencyService.put(key, instances);
    }
}
```


## Server Beat

1. if getInstance == null, register instance
2. getService and hanle beat
3. return result

```java
@CanDistro
@PutMapping("/beat")
@Secured(parser = NamingResourceParser.class, action = ActionTypes.WRITE)
public ObjectNode beat(HttpServletRequest request) throws Exception {
    
    ObjectNode result = JacksonUtils.createEmptyJsonNode();
    result.put(SwitchEntry.CLIENT_BEAT_INTERVAL, switchDomain.getClientBeatInterval());
    
    String beat = WebUtils.optional(request, "beat", StringUtils.EMPTY);
    RsInfo clientBeat = null;
    if (StringUtils.isNotBlank(beat)) {
        clientBeat = JacksonUtils.toObj(beat, RsInfo.class);
    }
    String clusterName = WebUtils
            .optional(request, CommonParams.CLUSTER_NAME, UtilsAndCommons.DEFAULT_CLUSTER_NAME);
    String ip = WebUtils.optional(request, "ip", StringUtils.EMPTY);
    int port = Integer.parseInt(WebUtils.optional(request, "port", "0"));
    if (clientBeat != null) {
        if (StringUtils.isNotBlank(clientBeat.getCluster())) {
            clusterName = clientBeat.getCluster();
        } else {
            // fix #2533
            clientBeat.setCluster(clusterName);
        }
        ip = clientBeat.getIp();
        port = clientBeat.getPort();
    }
    String namespaceId = WebUtils.optional(request, CommonParams.NAMESPACE_ID, Constants.DEFAULT_NAMESPACE_ID);
    String serviceName = WebUtils.required(request, CommonParams.SERVICE_NAME);
    NamingUtils.checkServiceNameFormat(serviceName);
    BeatInfoInstanceBuilder builder = BeatInfoInstanceBuilder.newBuilder();
    builder.setRequest(request);
    int resultCode = getInstanceOperator()
            .handleBeat(namespaceId, serviceName, ip, port, clusterName, clientBeat, builder);
    result.put(CommonParams.CODE, resultCode);
    result.put(SwitchEntry.CLIENT_BEAT_INTERVAL,
            getInstanceOperator().getHeartBeatInterval(namespaceId, serviceName, ip, port, clusterName));
    result.put(SwitchEntry.LIGHT_BEAT_ENABLED, switchDomain.isLightBeatEnabled());
    return result;
}
```

### handleBeat

```java
    // com.alibaba.nacos.naming.core.InstanceOperatorServiceImpl
    @Override
    public int handleBeat(String namespaceId, String serviceName, String ip, int port, String cluster,
            RsInfo clientBeat, BeatInfoInstanceBuilder builder) throws NacosException {
        com.alibaba.nacos.naming.core.Instance instance = serviceManager
                .getInstance(namespaceId, serviceName, cluster, ip, port);
        
        if (instance == null) {
            if (clientBeat == null) {
                return NamingResponseCode.RESOURCE_NOT_FOUND;
            }
            
            instance = parseInstance(builder.setBeatInfo(clientBeat).setServiceName(serviceName).build());
            serviceManager.registerInstance(namespaceId, serviceName, instance);
        }
        
        Service service = serviceManager.getService(namespaceId, serviceName);
        
        serviceManager.checkServiceIsNull(service, namespaceId, serviceName);
        
        if (clientBeat == null) {
            clientBeat = new RsInfo();
            clientBeat.setIp(ip);
            clientBeat.setPort(port);
            clientBeat.setCluster(cluster);
        }
        service.processClientBeat(clientBeat);
        return NamingResponseCode.OK;
    }
```



## Links

- [Nacos](/docs/CS/Java/Spring_Cloud/nacos/Nacos.md)