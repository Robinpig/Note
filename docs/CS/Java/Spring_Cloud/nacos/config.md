## Overview




### Example

```java
public static void main(String[] args) throws NacosException, InterruptedException {
        Properties properties = new Properties();
        properties.put("serverAddr", "xxx.xxx.xxx.xxx:8848");
        String dataId = "info";
        ConfigService configService = new NacosConfigService(properties);
        String defaultGroup = "DEFAULT_GROUP";
        String config = configService.getConfig(dataId, defaultGroup, 5000);
        System.out.println(config);
        configService.addListener(dataId, defaultGroup, new Listener() {
            @Override
            public Executor getExecutor() {
                return null;
            }

            @Override
            public void receiveConfigInfo(String s) {
                System.out.println("Config has been changed! :" + s);
            }
        });

        TimeUnit.MINUTES.sleep(5);
    }
```

## Config Refresh

### PropertySourceLocator
1. init [ConfigService](/docs/CS/Java/Spring_Cloud/nacos/config.md?id=ConfigService)
2. merge configurations

```java
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(name = "spring.cloud.nacos.config.enabled", matchIfMissing = true)
public class NacosConfigBootstrapConfiguration {
    //...
    
    @Bean
    public NacosPropertySourceLocator nacosPropertySourceLocator(
            NacosConfigManager nacosConfigManager) {
        return new NacosPropertySourceLocator(nacosConfigManager);
    }
}

public class NacosPropertySourceLocator implements PropertySourceLocator {
    @Override
    public PropertySource<?> locate(Environment env) {
        nacosConfigProperties.setEnvironment(env);
        ConfigService configService = nacosConfigManager.getConfigService();

        if (null == configService) {
            log.warn("no instance of config service found, can't load config from nacos");
            return null;
        }
        long timeout = nacosConfigProperties.getTimeout();
        nacosPropertySourceBuilder = new NacosPropertySourceBuilder(configService,
                timeout);
        String name = nacosConfigProperties.getName();

        String dataIdPrefix = nacosConfigProperties.getPrefix();
        if (StringUtils.isEmpty(dataIdPrefix)) {
            dataIdPrefix = name;
        }

        if (StringUtils.isEmpty(dataIdPrefix)) {
            dataIdPrefix = env.getProperty("spring.application.name");
        }

        CompositePropertySource composite = new CompositePropertySource(
                NACOS_PROPERTY_SOURCE_NAME);

        loadSharedConfiguration(composite);
        loadExtConfiguration(composite);
        loadApplicationConfiguration(composite, dataIdPrefix, nacosConfigProperties, env);
        return composite;
    }
}
```


### ConfigService

execute by executorService run [LongPollingRunnable](/docs/CS/Java/Spring_Cloud/nacos/Nacos.md?id=LongPollingRunnable)

```java
public class NacosConfigService implements ConfigService {
    
    private ClientWorker worker;

    @Override
    public void addListener(String dataId, String group, Listener listener) throws NacosException {
        worker.addTenantListeners(dataId, group, Arrays.asList(listener));
    }

    public ClientWorker(final HttpAgent agent, final ConfigFilterChainManager configFilterChainManager,
                        final Properties properties) {
        this.agent = agent;
        this.configFilterChainManager = configFilterChainManager;

        // Initialize the timeout parameter

        init(properties);

        this.executor = Executors.newScheduledThreadPool(1, new ThreadFactory() {
            @Override
            public Thread newThread(Runnable r) {
                Thread t = new Thread(r);
                t.setName("com.alibaba.nacos.client.Worker." + agent.getName());
                t.setDaemon(true);
                return t;
            }
        });

        this.executorService = Executors
                .newScheduledThreadPool(Runtime.getRuntime().availableProcessors(), new ThreadFactory() {
                    @Override
                    public Thread newThread(Runnable r) {
                        Thread t = new Thread(r);
                        t.setName("com.alibaba.nacos.client.Worker.longPolling." + agent.getName());
                        t.setDaemon(true);
                        return t;
                    }
                });

        this.executor.scheduleWithFixedDelay(new Runnable() {
            @Override
            public void run() {
                try {
                    checkConfigInfo();
                } catch (Throwable e) {
                    LOGGER.error("[" + agent.getName() + "] [sub-check] rotate check error", e);
                }
            }
        }, 1L, 10L, TimeUnit.MILLISECONDS);
    }
    
    public void checkConfigInfo() {
        // Dispatch tasks.
        int listenerSize = cacheMap.size();
        // Round up the longingTaskCount.
        int longingTaskCount = (int) Math.ceil(listenerSize / ParamUtil.getPerTaskConfigSize());
        if (longingTaskCount > currentLongingTaskCount) {
            for (int i = (int) currentLongingTaskCount; i < longingTaskCount; i++) {
                // The task list is no order.So it maybe has issues when changing.
                executorService.execute(new LongPollingRunnable(i));
            }
            currentLongingTaskCount = longingTaskCount;
        }
    }
}
```
#### LongPollingRunnable

1. check failover config
2. longPoll check server config
```java
class LongPollingRunnable implements Runnable {
        private int taskId;

        public LongPollingRunnable(int taskId) {
            this.taskId = taskId;
        }

    @Override
    public void run() {

        List<CacheData> cacheDatas = new ArrayList<CacheData>();
        List<String> inInitializingCacheList = new ArrayList<String>();
        try {
            // check failover config
            for (CacheData cacheData : cacheMap.values()) {
                if (cacheData.getTaskId() == taskId) {
                    cacheDatas.add(cacheData);
                    try {
                        checkLocalConfig(cacheData);
                        if (cacheData.isUseLocalConfigInfo()) {
                            cacheData.checkListenerMd5();
                        }
                    } catch (Exception e) {
                        LOGGER.error("get local config info error", e);
                    }
                }
            }

            // check server config
            List<String> changedGroupKeys = checkUpdateDataIds(cacheDatas, inInitializingCacheList);

            for (String groupKey : changedGroupKeys) {
                String[] key = GroupKey.parseKey(groupKey);
                String dataId = key[0];
                String group = key[1];
                String tenant = null;
                if (key.length == 3) {
                    tenant = key[2];
                }
                try {
                    ConfigResponse response = getServerConfig(dataId, group, tenant, 3000L);
                    CacheData cache = cacheMap.get(GroupKey.getKeyTenant(dataId, group, tenant));
                    cache.setContent(response.getContent());
                    cache.setEncryptedDataKey(response.getEncryptedDataKey());
                    if (null != response.getConfigType()) {
                        cache.setType(response.getConfigType());
                    }
                } catch (NacosException ioe) {
                    // log
                }
            }
            for (CacheData cacheData : cacheDatas) {
                if (!cacheData.isInitializing() || inInitializingCacheList
                        .contains(GroupKey.getKeyTenant(cacheData.dataId, cacheData.group, cacheData.tenant))) {
                    cacheData.checkListenerMd5();
                    cacheData.setInitializing(false);
                }
            }
            inInitializingCacheList.clear();

            executorService.execute(this);

        } catch (Throwable e) {
            // If the rotation training task is abnormal, the next execution time of the task will be punished
            executorService.schedule(this, taskPenaltyTime, TimeUnit.MILLISECONDS);
        }
    }
}
```


### Refresh Listener

Register listeners for Publish RefreshEvent to [Spring RefreshEventListener](/docs/CS/Java/Spring/IoC.md?id=EventListener).

```java
public class NacosContextRefresher
        implements ApplicationListener<ApplicationReadyEvent>, ApplicationContextAware {
    @Override
    public void onApplicationEvent(ApplicationReadyEvent event) {
        // many Spring context
        if (this.ready.compareAndSet(false, true)) {
            this.registerNacosListenersForApplications();
        }
    }


    private void registerNacosListenersForApplications() {
        if (isRefreshEnabled()) {
            for (NacosPropertySource propertySource : NacosPropertySourceRepository.getAll()) {
                if (!propertySource.isRefreshable()) {
                    continue;
                }
                String dataId = propertySource.getDataId();
                registerNacosListener(propertySource.getGroup(), dataId);
            }
        }
    }

    private void registerNacosListener(final String groupKey, final String dataKey) {
        String key = NacosPropertySourceRepository.getMapKey(dataKey, groupKey);
        Listener listener = listenerMap.computeIfAbsent(key,
                lst -> new AbstractSharedListener() {
                    @Override
                    public void innerReceive(String dataId, String group,
                                             String configInfo) {
                        refreshCountIncrement();
                        nacosRefreshHistory.addRefreshRecord(dataId, group, configInfo);
                        // todo feature: support single refresh for listening
                        applicationContext.publishEvent(new RefreshEvent(this, null, "Refresh Nacos config"));
                    }
                });
        try {
            configService.addListener(dataKey, groupKey, listener);
        }
        catch (NacosException e) {
            log.warn(String.format(
                    "register fail for nacos listener ,dataId=[%s],group=[%s]", dataKey,
                    groupKey), e);
        }
    }
}
```


## Server Config



## Summary

1. use ScheduledThreadPool.scheduleWithFixedDelay and longPoll



## Links

- [Nacos](/docs/CS/Java/Spring_Cloud/nacos/Nacos.md)


## References
1. [Listen for configurations](https://nacos.io/en-us/docs/open-api.html)