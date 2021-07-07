## Introduction

[NACOS-DISCOVERY-QUICK-START](https://github.com/nacos-group/nacos-spring-boot-project/blob/master/NACOS-DISCOVERY-QUICK-START.md)


#### NacosDiscoveryAutoConfiguration
```java
@ConditionalOnProperty(name = NacosDiscoveryConstants.ENABLED, matchIfMissing = true)
@ConditionalOnMissingBean(name = DISCOVERY_GLOBAL_NACOS_PROPERTIES_BEAN_NAME)
@EnableNacosDiscovery
@EnableConfigurationProperties(value = NacosDiscoveryProperties.class)
@ConditionalOnClass(name = "org.springframework.boot.context.properties.bind.Binder")
public class NacosDiscoveryAutoConfiguration {

	@Bean
	public NacosDiscoveryAutoRegister discoveryAutoRegister() {
		return new NacosDiscoveryAutoRegister();
	}

}
```

#### NacosDiscoveryAutoRegister
`NamingService::registerInstance()`

```java
@Component
public class NacosDiscoveryAutoRegister
        implements ApplicationListener<WebServerInitializedEvent> {

    private static final Logger logger = LoggerFactory
            .getLogger(NacosDiscoveryAutoRegister.class);

    @NacosInjected
    private NamingService namingService;

    @Autowired
    private NacosDiscoveryProperties discoveryProperties;

	@Value("${spring.application.name:}")
	private String applicationName;

    @Override
    public void onApplicationEvent(WebServerInitializedEvent event) {

        if (!discoveryProperties.isAutoRegister()) {
            return;
        }

        Register register = discoveryProperties.getRegister();

        if (StringUtils.isEmpty(register.getIp())) {
            register.setIp(NetUtils.localIP());
        }

        if (register.getPort() == 0) {
            register.setPort(event.getWebServer().getPort());
        }

        register.getMetadata().put("preserved.register.source", "SPRING_BOOT");

        register.setInstanceId("");

        String serviceName = register.getServiceName();

        if (StringUtils.isEmpty(serviceName)){
            if (StringUtils.isEmpty(applicationName)){
                throw new AutoRegisterException("serviceName notNull");
            }
            serviceName = applicationName;
        }

        try {
            namingService.registerInstance(serviceName, register.getGroupName(),
                    register);
            logger.info("Finished auto register service : {}, ip : {}, port : {}",
                    serviceName, register.getIp(), register.getPort());
        } catch (NacosException e) {
            throw new AutoRegisterException(e);
        }
    }

}
```

#### registerInstance
If you'd like to use "Service Registry" features, NamingService is a core service interface to get or publish config, you could use "Dependency Injection" to inject NamingService instance in your Spring Beans.
And [Dubbo](/docs/CS/Java/Dubbo/registry.md?id=NacosRegistry) wrapped it

```java
    @Override
    public void registerInstance(String serviceName, String groupName, Instance instance) throws NacosException {

        if (instance.isEphemeral()) {
            BeatInfo beatInfo = new BeatInfo();
            beatInfo.setServiceName(NamingUtils.getGroupedName(serviceName, groupName));
            beatInfo.setIp(instance.getIp());
            beatInfo.setPort(instance.getPort());
            beatInfo.setCluster(instance.getClusterName());
            beatInfo.setWeight(instance.getWeight());
            beatInfo.setMetadata(instance.getMetadata());
            beatInfo.setScheduled(false);
            beatInfo.setPeriod(instance.getInstanceHeartBeatInterval());

            beatReactor.addBeatInfo(NamingUtils.getGroupedName(serviceName, groupName), beatInfo);
        }

        serverProxy.registerService(NamingUtils.getGroupedName(serviceName, groupName), groupName, instance);
    }

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

##### BeatTask

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


##### registerService
```java
public void registerService(String serviceName, String groupName, Instance instance) throws NacosException {

        NAMING_LOGGER.info("[REGISTER-SERVICE] {} registering service {} with instance: {}",
            namespaceId, serviceName, instance);

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

        reqAPI(UtilAndComs.NACOS_URL_INSTANCE, params, HttpMethod.POST);

    }
```