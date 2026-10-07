## Introduction

Dubbo 的配置体系是「多来源叠加 + 逐层覆盖」的模型：同一个配置项可能同时出现在 JVM 启动参数、环境变量、配置中心、Spring 配置文件、注解和 `dubbo.properties` 里，最终生效的是优先级最高的那一个来源。理清这个顺序，是排查「我明明配了却不生效」的唯一办法。

而流传最广的那张优先级图是**错的**，这是本文要破除的第一个直觉：

- 常见说法把 `dubbo.properties` 排在 API / 注解之上，实际上 **`dubbo.properties` 是全链路中优先级最低的一档**，注解与 API 设置的 `AbstractConfig` 会覆盖它。
- 常见说法也漏掉了 `EnvironmentConfiguration`——**环境变量**（Kubernetes 里注入配置的主要方式）排在第二位，仅次于 `-D` 系统属性。

本文基于 Apache Dubbo **3.3.6** 官方源码，优先级顺序直接引用 `Environment` 的装配代码，不做凭印象的排序。

## Configuration Source and Priority

配置源的装配顺序写在 `Environment` 里，源码注释本身就是权威答案：

```java
// dubbo-common/.../common/config/Environment.java:186-201
// The sequence would be: SystemConfiguration -> EnvironmentConfiguration -> AppExternalConfiguration ->
// ExternalConfiguration  -> AppConfiguration -> AbstractConfig -> PropertiesConfiguration
Configuration instanceConfiguration = new ConfigConfigurationAdapter(config, prefix);
CompositeConfiguration compositeConfiguration = new CompositeConfiguration();
compositeConfiguration.addConfiguration(systemConfiguration);
compositeConfiguration.addConfiguration(environmentConfiguration);
compositeConfiguration.addConfiguration(appExternalConfiguration);
compositeConfiguration.addConfiguration(externalConfiguration);
compositeConfiguration.addConfiguration(appConfiguration);
compositeConfiguration.addConfiguration(instanceConfiguration);
compositeConfiguration.addConfiguration(propertiesConfiguration);
```

`CompositeConfiguration` 的语义是「先加入的优先」，因此**真实优先级从高到低**是：

| 顺序 | 配置源 | 来源说明 | 典型载体 |
| :--- | :--- | :--- | :--- |
| 1 | `SystemConfiguration` | JVM 系统属性 | `-Ddubbo.protocol.port=20881` |
| 2 | `EnvironmentConfiguration` | 操作系统环境变量 | `DUBBO_PROTOCOL_PORT`（K8s ConfigMap/Secret 注入） |
| 3 | `AppExternalConfiguration` | 配置中心下发的**应用级**配置 | Nacos / ZooKeeper 中「应用名」维度 |
| 4 | `ExternalConfiguration` | 配置中心下发的**全局级**配置 | 配置中心全局维度 |
| 5 | `AppConfiguration` | 本地应用配置 | Spring `application.yml` / `@PropertySource` |
| 6 | `AbstractConfig` 实例 | API / 注解 / XML 显式设置 | `new ApplicationConfig()`、`@DubboService`、`dubbo:service` |
| 7 | `PropertiesConfiguration` | `dubbo.properties` | classpath 根的 `dubbo.properties` |

三个 `InmemoryConfiguration` 的命名也印证了配置中心两级结构的划分：

```java
// Environment.java:87-89
this.externalConfiguration    = new InmemoryConfiguration("ExternalConfig");
this.appExternalConfiguration = new InmemoryConfiguration("AppExternalConfig");
this.appConfiguration         = new InmemoryConfiguration("AppConfig");
```

两个配置源的取数逻辑各有特点：`SystemConfiguration` 只读系统属性（`SystemConfiguration.java:27-28` 直接 `System.getProperty(key)`）；`EnvironmentConfiguration` 除了读环境变量，还会做多种 key 形式的归一化（`EnvironmentConfiguration.java:33-51`），这也是为什么 `dubbo.protocol.port` 与 `DUBBO_PROTOCOL_PORT` 都能被识别。

> [!TIP]
> 生产上最实用的推论：想临时压掉配置中心下发的值做验证，用 `-D` 启动参数即可，它比配置中心优先；想固化一版默认值给所有环境，写 `dubbo.properties` 是一档兜底，但**任何注解 / API 的显式设置都会覆盖它**，不要用它来做「强制值」。

## Three Configuration Forms

按使用方式，Dubbo 配置可以归为三类，它们最终都会被归一化成 `AbstractConfig` 的子类实例：

| 形态 | 写法 | 适用场景 |
| :--- | :--- | :--- |
| API 配置 | `new ServiceConfig<>()`、`new ApplicationConfig()` 显式编程 | 框架集成、测试 |
| 注解配置 | `@DubboService`、`@DubboReference`、`@EnableDubbo` | Spring Boot 业务代码 |
| XML 配置 | `<dubbo:service>`、`<dubbo:reference>` | 传统 Spring 工程、需要集中管理时 |

无论用哪种形态，配置项最终的载体都是 `AbstractConfig` 的字段（如 `ProtocolConfig.port`、`ApplicationConfig.name`）。配置项 key 的命名规则是「`dubbo.` + 模块名 + `-` + 连字符化字段名」，例如 `dubbo.application.name`、`dubbo.application.serialize-check-status`。

## ConfigManager and Configuration Loading

配置的管理者是 `ConfigManager`（应用级）与 `ModuleConfigManager`（模块级）：

```java
// dubbo-common/.../config/context/ConfigManager.java:53
public class ConfigManager extends AbstractConfigManager implements ApplicationExt {
```

> [!WARNING]
> 3.3.6 里**没有 `DefaultConfigManager`，也没有 `DefaultConfigurationFactory`**。这两个类名在旧版本文章里很常见，但当前源码中配置管理器就是具体类 `ConfigManager` / `ModuleConfigManager`，配置源的装配在 `Environment` 里完成。按旧类名去搜源码会一无所获。

`ConfigManager` 的加载入口按配置类型逐个处理，顺序本身也构成一种依赖关系（应用信息最先，协议与注册中心其次）：

```java
// ConfigManager.java（loadConfigs，节选）
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

注意 `ConfigCenterConfig` 那一行被注释掉了——配置中心必须在「加载其它配置之前」就先启动，所以它的加载不在这里，而在部署器启动流程的最前面（见下一节）。`refreshAll()` 负责把动态来源刷新回各个 `AbstractConfig`：

```java
// ConfigManager.java（refreshAll，节选）
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
```

## Startup Chain of the Configuration Center

配置中心的加载是整个启动流程的第一步，入口是 `DefaultApplicationDeployer.initialize()` 调用的 `startConfigCenter()`：

```java
// dubbo-config/dubbo-config-api/.../deploy/DefaultApplicationDeployer.java（startConfigCenter，节选）
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
    ...
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

这段代码正好解释了优先级表里 `AppExternalConfiguration` / `ExternalConfiguration` 两档的来源——它们就是配置中心拉回来的两份配置，分别写入 `updateAppExternalConfigMap` 与 `updateExternalConfigMap`。

**应用名必须在配置中心加载之前确定**，因为应用级配置（AppExternal）是按应用名订阅的。源码里那句注释 "application config has load before starting config center" 就是这个约束。

### Use the Registry as a Configuration Center

出于兼容性考虑，如果没有显式配置配置中心、且注册中心未禁止，Dubbo 会把注册中心直接当配置中心用：

```java
// DefaultApplicationDeployer.java（useRegistryAsConfigCenterIfNecessary，节选）
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

「这个注册中心能不能当配置中心」不是靠协议名硬编码判断的，而是**扫描扩展实现是否存在**：

```java
// DefaultApplicationDeployer.java（isUsedRegistryAsCenter，节选）
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
        ...
    }
    ...
    return supported;
}
```

判据是「该协议的 `DynamicConfigurationFactory` 扩展是否存在」。ZooKeeper 之所以天然支持，是因为它注册了对应工厂：

```properties
# dubbo-configcenter-zookeeper 的 org.apache.dubbo.common.config.configcenter.DynamicConfigurationFactory
zookeeper=org.apache.dubbo.configcenter.support.zookeeper.ZookeeperDynamicConfigurationFactory
```

由注册中心生成的 `ConfigCenterConfig` 会继承注册中心的地址、组、用户名密码等，并被标记为**非最高优先级**：

```java
// DefaultApplicationDeployer.java（registryAsConfigCenter，节选）
private ConfigCenterConfig registryAsConfigCenter(RegistryConfig registryConfig) {
    String protocol = registryConfig.getProtocol();
    Integer port = registryConfig.getPort();
    URL url = URL.valueOf(registryConfig.getAddress(), registryConfig.getScopeModel());
    String id = "config-center-" + protocol + "-" + url.getHost() + "-" + port;
    ConfigCenterConfig cc = new ConfigCenterConfig();
    cc.setId(id);
    ...
    cc.setHighestPriority(false);
    return cc;
}
```

## dubbo.properties Load Path

`dubbo.properties` 的默认文件名只有一个，**就是 classpath 根目录下的 `dubbo.properties`**：

```java
// dubbo-common/.../constants/CommonConstants.java:64
String DEFAULT_DUBBO_PROPERTIES = "dubbo.properties";
```

```java
// dubbo-common/.../utils/ConfigUtils.java:166-174
String path = SystemPropertyConfigUtils.getSystemProperty(DUBBO_PROPERTIES_KEY);
if (StringUtils.isEmpty(path)) {
    path = System.getenv(DUBBO_PROPERTIES_KEY);
    if (StringUtils.isEmpty(path)) {
        path = CommonConstants.DEFAULT_DUBBO_PROPERTIES;
    }
}
return ConfigUtils.loadProperties(classLoaders, path, false, true);
```

`ConfigUtils.loadProperties` 通过 `ClassLoaderResourceLoader.loadResources(fileName, ...)` 从 classpath 加载（`:240`、`:266`）。路径可以用 `dubbo.config.properties.file` 覆盖（系统属性或环境变量均可）。

> [!WARNING]
> **`classpath:/META-INF/dubbo/dubbo.properties` 并不是 Dubbo 的默认查找路径。** 这个路径字符串只出现在 `dubbo-spring-boot-*` 的测试用例 `@PropertySource` 里（如 `CompatibleDubboAutoConfigurationTest.java:44`），不构成框架行为。把配置文件放到 `META-INF/dubbo/` 下**不会被自动加载**，这是很常见的误配。

## Common Configuration Pitfalls

| 现象 | 原因 | 处理 |
| :--- | :--- | :--- |
| 注解配了但没生效 | 误以为 `dubbo.properties` 优先级更高 | 按优先级表逐档排查，properties 是最低档 |
| K8s 环境变量注入不生效 | 环境变量优先级其实很高（第 2 位），但 key 命名不符合归一化规则 | 用 `DUBBO_PROTOCOL_PORT` 这类大写连字符形式 |
| 配置中心改了不生效 | 优先级低于 `-D` 或注解 | 注意 `-D` 最高，注解高于 properties 与配置中心之下的本地配置 |
| 应用级配置订阅不到 | 应用名未在配置中心加载前确定 | 确保 `dubbo.application.name` 在启动最早期可得 |
| 配置文件放 `META-INF/dubbo/` 无效 | 该路径不是默认查找路径 | 放到 classpath 根，或用 `dubbo.config.properties.file` 指定 |
| 找不到 `DefaultConfigManager` | 该类在当前版本不存在 | 看 `ConfigManager` / `ModuleConfigManager` / `Environment` |

## Links

- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)
- [Start](/docs/CS/Framework/Dubbo/Start.md)
- [registry](/docs/CS/Framework/Dubbo/registry.md)
- [Metadata](/docs/CS/Framework/Dubbo/Metadata.md)
- [SPI](/docs/CS/Framework/Dubbo/SPI.md)
- [Governance](/docs/CS/Framework/Dubbo/Governance.md)

## References

1. [Dubbo 配置项参考手册](https://cn.dubbo.apache.org/zh-cn/overview/mannual/java-sdk/reference-manual/config/properties/)
2. [Dubbo 配置中心官方文档](https://cn.dubbo.apache.org/zh-cn/overview/mannual/java-sdk/reference-manual/config-center/)
3. [dubbo-common config 源码](https://github.com/apache/dubbo/tree/3.3/dubbo-common/src/main/java/org/apache/dubbo/common/config)
