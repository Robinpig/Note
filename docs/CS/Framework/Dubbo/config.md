## Introduction



Dubbo应用的启动过程DefaultApplicationDeployer的initialize() 方法的全生命周期， 在初始化方法中通过调用 `startConfigCenter()` 方法来启动配置中心的加载。





```java
private void startConfigCenter() {

    // load application config
    configManager.loadConfigsOfTypeFromProps(ApplicationConfig.class);

    // try set model name
    if (StringUtils.isBlank(applicationModel.getModelName())) {
        applicationModel.setModelName(applicationModel.tryGetApplicationName());
    }

    // load config centers
    configManager.loadConfigsOfTypeFromProps(ConfigCenterConfig.class);

    useRegistryAsConfigCenterIfNecessary();

    // check Config Center
    Collection<ConfigCenterConfig> configCenters = configManager.getConfigCenters();
    if (CollectionUtils.isEmpty(configCenters)) {
        ConfigCenterConfig configCenterConfig = new ConfigCenterConfig();
        configCenterConfig.setScopeModel(applicationModel);
        configCenterConfig.refresh();
        ConfigValidationUtils.validateConfigCenterConfig(configCenterConfig);
        if (configCenterConfig.isValid()) {
            configManager.addConfigCenter(configCenterConfig);
            configCenters = configManager.getConfigCenters();
        }
    } else {
        for (ConfigCenterConfig configCenterConfig : configCenters) {
            configCenterConfig.refresh();
            ConfigValidationUtils.validateConfigCenterConfig(configCenterConfig);
        }
    }

    if (CollectionUtils.isNotEmpty(configCenters)) {
        CompositeDynamicConfiguration compositeDynamicConfiguration = new CompositeDynamicConfiguration();
        for (ConfigCenterConfig configCenter : configCenters) {
            // Pass config from ConfigCenterBean to environment
            environment.updateExternalConfigMap(configCenter.getExternalConfiguration());
            environment.updateAppExternalConfigMap(configCenter.getAppExternalConfiguration());

            // Fetch config from remote config center
            compositeDynamicConfiguration.addConfiguration(prepareEnvironment(configCenter));
        }
        environment.setDynamicConfiguration(compositeDynamicConfiguration);
    }
}
```





出于兼容性目的，如果没有明确指定配置中心，并且registryConfig的UseAConfigCenter为null或true，请使用registry作为默认配置中心 调用方法useRegistryAsConfigCenterIfNecessary()来处理逻辑 



```java
private void useRegistryAsConfigCenterIfNecessary() {
    // we use the loading status of DynamicConfiguration to decide whether ConfigCenter has been initiated.
    if (environment.getDynamicConfiguration().isPresent()) {
        return;
    }

    if (CollectionUtils.isNotEmpty(configManager.getConfigCenters())) {
        return;
    }

    // load registry
    configManager.loadConfigsOfTypeFromProps(RegistryConfig.class);

    List<RegistryConfig> defaultRegistries = configManager.getDefaultRegistries();
    if (defaultRegistries.size() > 0) {
        defaultRegistries.stream()
                .filter(this::isUsedRegistryAsConfigCenter)
                .map(this::registryAsConfigCenter)
                .forEach(configCenter -> {
                    if (configManager.getConfigCenter(configCenter.getId()).isPresent()) {
                        return;
                    }
                    configManager.addConfigCenter(configCenter);
                    logger.info("use registry as config-center: " + configCenter);
                });
    }
}
```

is

```java
private boolean isUsedRegistryAsCenter(
        RegistryConfig registryConfig,
        Supplier<Boolean> usedRegistryAsCenter,
        String centerType,
        Class<?> extensionClass) {
    final boolean supported;

    Boolean configuredValue = usedRegistryAsCenter.get();
    if (configuredValue != null) { // If configured, take its value.
        supported = configuredValue.booleanValue();
    } else { // Or check the extension existence
        String protocol = registryConfig.getProtocol();
        supported = supportsExtension(extensionClass, protocol);
        if (logger.isInfoEnabled()) {
            logger.info(format(
                    "No value is configured in the registry, the %s extension[name : %s] %s as the %s center",
                    extensionClass.getSimpleName(),
                    protocol,
                    supported ? "supports" : "does not support",
                    centerType));
        }
    }

    if (logger.isInfoEnabled()) {
        logger.info(format(
                "The registry[%s] will be %s as the %s center",
                registryConfig, supported ? "used" : "not used", centerType));
    }
    return supported;
}
```

这个扩展是否支持的逻辑判断是这样的扫描扩展类 看一下当前扩展类型是否有对应协议的扩展 比如在扩展文件里面这样配置过后是支持的 protocol=xxxImpl 配置中心的动态配置的扩展类型为 org.apache.dubbo.common.config.configcenter.DynamicConfigurationFactory



zookeeper协议肯定是支持的因为zookeeper协议实现了这个动态配置工厂 ,这个扩展类型为ZookeeperDynamicConfigurationFactory代码位置在dubbo-configcenter-zookeeper包中的org.apache.dubbo.common.config.configcenter.DynamicConfigurationFactory扩展配置中内容为

```properties
zookeeper=org.apache.dubbo.configcenter.support.zookeeper.ZookeeperDynamicConfigurationFactory
```



```java
private ConfigCenterConfig registryAsConfigCenter(RegistryConfig registryConfig) {
    String protocol = registryConfig.getProtocol();
    Integer port = registryConfig.getPort();
    URL url = URL.valueOf(registryConfig.getAddress(), registryConfig.getScopeModel());
    String id = "config-center-" + protocol + "-" + url.getHost() + "-" + port;
    ConfigCenterConfig cc = new ConfigCenterConfig();
    cc.setId(id);
    cc.setScopeModel(applicationModel);
    if (cc.getParameters() == null) {
        cc.setParameters(new HashMap<>());
    }
    if (CollectionUtils.isNotEmptyMap(registryConfig.getParameters())) {
        cc.getParameters().putAll(registryConfig.getParameters()); // copy the parameters
    }
    cc.getParameters().put(CLIENT_KEY, registryConfig.getClient());
    cc.setProtocol(protocol);
    cc.setPort(port);
    if (StringUtils.isNotEmpty(registryConfig.getGroup())) {
        cc.setGroup(registryConfig.getGroup());
    }
    cc.setAddress(getRegistryCompatibleAddress(registryConfig));
    cc.setNamespace(registryConfig.getGroup());
    cc.setUsername(registryConfig.getUsername());
    cc.setPassword(registryConfig.getPassword());
    if (registryConfig.getTimeout() != null) {
        cc.setTimeout(registryConfig.getTimeout().longValue());
    }
    cc.setHighestPriority(false);
    return cc;
}
```





```java
public class ConfigManager extends AbstractConfigManager implements ApplicationExt {
@Override
public void refreshAll() {
    // refresh all configs here
    getApplication().ifPresent(ApplicationConfig::refresh);
    getMonitor().ifPresent(MonitorConfig::refresh);
    getMetrics().ifPresent(MetricsConfig::refresh);
    getTracing().ifPresent(TracingConfig::refresh);
    getSsl().ifPresent(SslConfig::refresh);

    getProtocols().forEach(ProtocolConfig::refresh);
    getRegistries().forEach(RegistryConfig::refresh);
    getConfigCenters().forEach(ConfigCenterConfig::refresh);
    getMetadataConfigs().forEach(MetadataReportConfig::refresh);
}
}
```



loadApplicationConfigs

```java
@Override
public void loadConfigs() {
    // application config has load before starting config center
    // load dubbo.applications.xxx
    loadConfigsOfTypeFromProps(ApplicationConfig.class);

    // load dubbo.monitors.xxx
    loadConfigsOfTypeFromProps(MonitorConfig.class);

    // load dubbo.metrics.xxx
    loadConfigsOfTypeFromProps(MetricsConfig.class);

    // load dubbo.tracing.xxx
    loadConfigsOfTypeFromProps(TracingConfig.class);

    // load multiple config types:
    // load dubbo.protocols.xxx
    loadConfigsOfTypeFromProps(ProtocolConfig.class);

    // load dubbo.registries.xxx
    loadConfigsOfTypeFromProps(RegistryConfig.class);

    // load dubbo.metadata-report.xxx
    loadConfigsOfTypeFromProps(MetadataReportConfig.class);

    // config centers has bean loaded before starting config center
    // loadConfigsOfTypeFromProps(ConfigCenterConfig.class);

    refreshAll();

    checkConfigs();

    // set model name
    if (StringUtils.isBlank(applicationModel.getModelName())) {
        applicationModel.setModelName(applicationModel.getApplicationName());
    }
}
```


## Links

- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)