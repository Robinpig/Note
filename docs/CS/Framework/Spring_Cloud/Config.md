## Introduction

PropertySource

用于定位 Environment 的（可能远程的）属性源的策略。
除非实现意图阻止应用程序启动，否则不应失败。

```java
public interface PropertySourceLocator {
    PropertySource<?> locate(Environment environment);
}
```

## Spring Cloud Config Server

Spring Cloud Config Server 为外部配置（键值对或等效的 YAML 内容）提供基于 HTTP 资源的 API。
该服务器可以通过 @EnableConfigServer 注解嵌入到 Spring Boot 应用程序中。

## Spring Cloud Config Client

## Zookeeper

数据，例如配置数据。Spring Cloud Zookeeper Config 是 Config Server 和 Client 的替代方案。
配置在特殊的 "bootstrap" 阶段加载到 Spring Environment 中。
配置默认存储在 /config 命名空间下。
根据应用程序名称和活动 profile 创建多个 PropertySource 实例，模拟 Spring Cloud Config 的属性解析顺序。

```java
public class ZookeeperPropertySourceLocator implements PropertySourceLocator {
    @Override
    public PropertySource<?> locate(Environment environment) {
        if (environment instanceof ConfigurableEnvironment) {
            ConfigurableEnvironment env = (ConfigurableEnvironment) environment;

            List<String> profiles = Arrays.asList(env.getActiveProfiles());

            ZookeeperPropertySources sources = new ZookeeperPropertySources(properties, log);
            this.contexts = sources.getAutomaticContexts(profiles);

            CompositePropertySource composite = new CompositePropertySource("zookeeper");

            for (String propertySourceContext : this.contexts) {
                PropertySource<CuratorFramework> propertySource = sources.createPropertySource(propertySourceContext, true, this.curator);
                composite.addPropertySource(propertySource);
            }

            return composite;
        }
        return null;
    }
}
```

```java

@Configuration(proxyBeanMethods = false)
@ConditionalOnZookeeperEnabled
@ConditionalOnProperty(value = "spring.cloud.zookeeper.config.enabled", matchIfMissing = true)
public class ZookeeperConfigAutoConfiguration {
    @Configuration(proxyBeanMethods = false)
    @ConditionalOnClass(RefreshEndpoint.class)
    @ConditionalOnProperty(name = "spring.cloud.zookeeper.config.watcher.enabled", matchIfMissing = true)
    protected static class ZkRefreshConfiguration {

        @Bean
        @ConditionalOnBean(ZookeeperPropertySourceLocator.class)
        public ConfigWatcher propertySourceLocatorConfigWatcher(ZookeeperPropertySourceLocator locator,
                                                                CuratorFramework curator) {
            return new ConfigWatcher(locator.getContexts(), curator);
        }

        @Bean
        @ConditionalOnMissingBean(ZookeeperPropertySourceLocator.class)
        public ConfigWatcher configDataConfigWatcher(CuratorFramework curator, Environment env) {
            List<String> contexts = env.getProperty("spring.cloud.zookeeper.config.property-source-contexts",
                    List.class, Collections.emptyList());
            return new ConfigWatcher(contexts, curator);
        }

    }
}
```

```java
public class ConfigWatcher
        implements Closeable, TreeCacheListener, ApplicationEventPublisherAware {
    @PostConstruct
    public void start() {
        if (this.running.compareAndSet(false, true)) {
            this.caches = new HashMap<>();
            for (String context : this.contexts) {
                if (!context.startsWith("/")) {
                    context = "/" + context;
                }
                try {
                    TreeCache cache = TreeCache.newBuilder(this.source, context).build();
                    cache.getListenable().addListener(this);
                    cache.start();
                    this.caches.put(context, cache);
                    // no race condition since ZookeeperAutoConfiguration.curatorFramework
                    // calls curator.blockUntilConnected
                } catch (KeeperException.NoNodeException e) {
                    // no node, ignore
                } catch (Exception e) {
                    log.error("Error initializing listener for context " + context, e);
                }
            }
        }
    }

    @Override
    public void childEvent(CuratorFramework client, TreeCacheEvent event)
            throws Exception {
        TreeCacheEvent.Type eventType = event.getType();
        if (eventType == NODE_ADDED || eventType == NODE_REMOVED
                || eventType == NODE_UPDATED) {
            this.publisher
                    .publishEvent(new RefreshEvent(this, event, getEventDesc(event)));
        }
    }
}
```

## Consul


```java
@Configuration(proxyBeanMethods = false)
@ConditionalOnConsulEnabled
@ConditionalOnProperty(name = "spring.cloud.consul.config.enabled", matchIfMissing = true)
@EnableConfigurationProperties
public class ConsulConfigAutoConfiguration {

	/**
	 * Name of the config watch task scheduler bean.
	 */
	public static final String CONFIG_WATCH_TASK_SCHEDULER_NAME = "configWatchTaskScheduler";

	@Configuration(proxyBeanMethods = false)
	@ConditionalOnClass(RefreshEndpoint.class)
	@ConditionalOnProperty(name = "spring.cloud.consul.config.watch.enabled", matchIfMissing = true)
	protected static class ConsulRefreshConfiguration {

		@Bean
		@ConditionalOnBean(ConsulConfigIndexes.class)
		public ConfigWatch configWatch(ConsulConfigProperties properties, ConsulConfigIndexes indexes,
				ConsulClient consul, @Qualifier(CONFIG_WATCH_TASK_SCHEDULER_NAME) TaskScheduler taskScheduler) {
			return new ConfigWatch(properties, consul, indexes.getIndexes(), taskScheduler);
		}

		@Bean(name = CONFIG_WATCH_TASK_SCHEDULER_NAME)
		public TaskScheduler configWatchTaskScheduler() {
			return new ThreadPoolTaskScheduler();
		}

	}

}
```

Spring 的 TaskScheduler 接口的标准实现，包装了本地的 ScheduledThreadPoolExecutor，并为其提供所有适用的配置选项。
默认的调度线程数为 1；
```java
public class ConfigWatch implements ApplicationEventPublisherAware, SmartLifecycle {
    @Override
    public void start() {
        if (this.running.compareAndSet(false, true)) {
            this.watchFuture = this.taskScheduler.scheduleWithFixedDelay(this::watchConfigKeyValues,
                    this.properties.getWatch().getDelay());
        }
    }

    @Timed("consul.watch-config-keys")
    public void watchConfigKeyValues() {
        if (!this.running.get()) {
            return;
        }
        for (String context : this.consulIndexes.keySet()) {

            // turn the context into a Consul folder path (unless our config format
            // are FILES)
            if (this.properties.getFormat() != FILES && !context.endsWith("/")) {
                context = context + "/";
            }

            try {
                Long currentIndex = this.consulIndexes.get(context);
                if (currentIndex == null) {
                    currentIndex = -1L;
                }

                // use the consul ACL token if found
                String aclToken = this.properties.getAclToken();
                if (ObjectUtils.isEmpty(aclToken)) {
                    aclToken = null;
                }

                Response<List<GetValue>> response = this.consul.getKVValues(context, aclToken,
                        new QueryParams(this.properties.getWatch().getWaitTime(), currentIndex));

                // if response.value == null, response was a 404, otherwise it was a
                // 200, reducing churn if there wasn't anything
                if (response.getValue() != null && !response.getValue().isEmpty()) {
                    Long newIndex = response.getConsulIndex();

                    if (newIndex != null && !newIndex.equals(currentIndex)) {
                        // don't publish the same index again, don't publish the first
                        // time (-1) so index can be primed
                        if (!this.consulIndexes.containsValue(newIndex) && !currentIndex.equals(-1L)) {
                            RefreshEventData data = new RefreshEventData(context, currentIndex, newIndex);
                            this.publisher.publishEvent(new RefreshEvent(this, data, data.toString()));
                        }
                        this.consulIndexes.put(context, newIndex);
                    }
                }
            }
            catch (Exception e) {
                // only fail fast on the initial query, otherwise just log the error
                if (this.firstTime && this.properties.isFailFast()) {
                    ReflectionUtils.rethrowRuntimeException(e);
                }
            }
        }
        this.firstTime = false;
    }
}

/**
 * Consul watch properties.
 */
public static class Watch {

    /**
     * The number of seconds to wait (or block) for watch query, defaults to 55. Needs
     * to be less than default ConsulClient (defaults to 60). To increase ConsulClient
     * timeout create a ConsulClient bean with a custom ConsulRawClient with a custom
     * HttpClient.
     */
    private int waitTime = 55;

    /** If the watch is enabled. Defaults to true. */
    private boolean enabled = true;

    /** The value of the fixed delay for the watch in millis. Defaults to 1000. */
    private int delay = 1000;
}
```

## Nacos

```java
/**
 * @author xiaojing
 * @author freeman
 */
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(name = "spring.cloud.nacos.config.enabled", matchIfMissing = true)
public class NacosConfigBootstrapConfiguration {

    @Bean
    @ConditionalOnMissingBean
    public NacosConfigProperties nacosConfigProperties() {
        return new NacosConfigProperties();
    }

    @Bean
    @ConditionalOnMissingBean
    public NacosConfigManager nacosConfigManager(
            NacosConfigProperties nacosConfigProperties) {
        return new NacosConfigManager(nacosConfigProperties);
    }

    @Bean
    public NacosPropertySourceLocator nacosPropertySourceLocator(
            NacosConfigManager nacosConfigManager) {
        return new NacosPropertySourceLocator(nacosConfigManager);
    }
}
```

```java
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(name = "spring.cloud.nacos.config.enabled", matchIfMissing = true)
public class NacosConfigAutoConfiguration {
    @Bean
    public NacosContextRefresher nacosContextRefresher(
            NacosConfigManager nacosConfigManager,
            NacosRefreshHistory nacosRefreshHistory) {
        // Consider that it is not necessary to be compatible with the previous
        // configuration
        // and use the new configuration if necessary.
        return new NacosContextRefresher(nacosConfigManager, nacosRefreshHistory);
    }
}
```
在应用程序启动时，NacosContextRefresher 为所有应用程序级别的 dataId 添加 nacos 监听器，当数据发生变化时，监听器将刷新配置。
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
            for (NacosPropertySource propertySource : NacosPropertySourceRepository
                    .getAll()) {
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
                        NacosSnapshotConfigManager.putConfigSnapshot(dataId, group,
                                configInfo);
                        applicationContext.publishEvent(
                                new RefreshEvent(this, null, "Refresh Nacos config"));
                        if (log.isDebugEnabled()) {
                            log.debug(String.format(
                                    "Refresh Nacos config group=%s,dataId=%s,configInfo=%s",
                                    group, dataId, configInfo));
                        }
                    }
                });
        try {
            configService.addListener(dataKey, groupKey, listener);
        } catch (NacosException e) {
            // log
        }
    }
}
```

```java
public class ClientWorker implements Closeable {
    
}
```


```java
    public class ConfigRpcTransportClient extends ConfigTransportClient {
    @Override
    public void executeConfigListen() throws NacosException {

        Map<String, List<CacheData>> listenCachesMap = new HashMap<>(16);
        Map<String, List<CacheData>> removeListenCachesMap = new HashMap<>(16);
        long now = System.currentTimeMillis();
        boolean needAllSync = now - lastAllSyncTime >= ALL_SYNC_INTERNAL;
        for (CacheData cache : cacheMap.get().values()) {
            synchronized (cache) {
                checkLocalConfig(cache);

                // check local listeners consistent.
                if (cache.isConsistentWithServer()) {
                    cache.checkListenerMd5();
                    if (!needAllSync) {
                        continue;
                    }
                }

                // If local configuration information is used, then skip the processing directly.
                if (cache.isUseLocalConfigInfo()) {
                    continue;
                }

                if (!cache.isDiscard()) {
                    List<CacheData> cacheDatas = listenCachesMap.computeIfAbsent(String.valueOf(cache.getTaskId()),
                            k -> new LinkedList<>());
                    cacheDatas.add(cache);
                } else {
                    List<CacheData> cacheDatas = removeListenCachesMap.computeIfAbsent(
                            String.valueOf(cache.getTaskId()), k -> new LinkedList<>());
                    cacheDatas.add(cache);
                }
            }

        }

        //execute check listen ,return true if has change keys.
        boolean hasChangedKeys = checkListenCache(listenCachesMap);

        //execute check remove listen.
        checkRemoveListenCache(removeListenCachesMap);

        if (needAllSync) {
            lastAllSyncTime = now;
        }
        //If has changed keys,notify re sync md5.
        if (hasChangedKeys) {
            notifyListenConfig();
        }

    }
}   
```

## Links

- [Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md?id=Cloud-configuration)
