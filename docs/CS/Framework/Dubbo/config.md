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

## @Parameter Annotation and append* Concatenation

配置项到底怎么变成 URL 上的 `key=value`？答案是 `AbstractConfig` 的一对静态工具方法 `appendParameters` / `appendAttributes`，以及贯穿其上的 `@Parameter` 注解。

`@Parameter`（`dubbo-common/.../config/support/Parameter.java`）只有六个属性，**没有 `order`**（排序不靠它）：

| 属性 | 默认 | 含义 |
| :--- | :--- | :--- |
| `key()` | `""` | 写入 URL 时的参数名；为空则用 getter 名推导 |
| `required()` | `false` | `true` 时该值为空则抛 "xxx == null" |
| `excluded()` | `false` | `true` 时 `appendParameters` 直接跳过（不进 URL） |
| `escaped()` | `false` | `true` 时对值做 `URL.encode` |
| `attribute()` | `true` | `false` 时 `refresh()` / `getMetadata()` / `equals()` / `toString()` 忽略该字段 |
| `append()` | `false` | `true` 时不覆盖而是逗号拼接并去重 |

`appendParameters` 与 `appendAttributes` 都委托给 `appendParameters0(..., boolean asParameters)`（`AbstractConfig.java:182-271`）：

- `appendParameters(..., prefix)` → `asParameters = true`：遍历 getter，跳过 `@Parameter.excluded()` 的；key 优先取 `parameter.key()`，否则 `calculatePropertyFromGetter(name)`（getter 名 → 属性名）；`escaped()` 做 `URL.encode`；`append()` 把新值用 `","` 拼到已有值后并 `splitToSet` 去重（`AbstractConfig.java:231-238`）；`prefix` 非空时 key 变为 `prefix + "." + key`。
- `appendAttributes(..., prefix)` → `asParameters = false`：只保留 `@Parameter.attribute() == true` 的字段，key 经 `StringUtils.convertToSplitName` 转成 **kebab-case**（如 `myField` → `my-field`，`:221-223`）。
- 嵌套 getter（`isNestedGetter`）会**递归**下钻，前缀累加 `prefix + "." + fieldName`（`:261-265`）；`getParameters()` 这类 `Map` getter 的内容会被整体并入 URL（用户自定义 `<dubbo:parameter>` 即走此路，`:247-260`）。

> [!TIP]
> 这两个方法解释了「为什么有些字段出现在 URL、有些不出现」：`executes` / `actives` / `token` 等带 `@Parameter` 会进 URL；而纯 Java 对象字段（`returnType == Object.class`）会被跳过（`:200-202`）。排查「某个配置没传到对端」时，先看它有没有 `@Parameter`、有没有被 `excluded`。

### refresh(): Overriding Fields from Configuration Sources

`AbstractConfig.refresh()`（`AbstractConfig.java:718-737`）是「七档优先级真正落到字段上」的入口。`needRefresh` 为真时它走 `refreshWithPrefixes(getPrefixes(), getConfigMode())`：

```java
// dubbo-common/src/main/java/org/apache/dubbo/config/AbstractConfig.java:739-756
protected void refreshWithPrefixes(List<String> prefixes, ConfigMode configMode) {
    Environment environment = getScopeModel().modelEnvironment();
    List<Map<String, String>> configurationMaps = environment.getConfigurationMaps();
    // 按优先级顺序找第一个命中子属性的 prefix
    String preferredPrefix = null;
    for (String prefix : prefixes) {
        if (ConfigurationUtils.hasSubProperties(configurationMaps, prefix)) {
            preferredPrefix = prefix; break;
        }
    }
    if (preferredPrefix == null) preferredPrefix = prefixes.get(0);
    Collection<Map<String, String>> instanceConfigMaps =
            environment.getConfigurationMaps(this, preferredPrefix);
    Map<String, String> subProperties =
            ConfigurationUtils.getSubProperties(instanceConfigMaps, preferredPrefix);
    ...
    assignProperties(this, environment, subProperties, subPropsConfiguration, configMode);
}
```

要点：

- `getPrefixes()` 返回的优先级本身也分层，例如 `ServiceConfig` 含 `dubbo.service`、`dubbo.provider`、`dubbo.application`——同名属性按这个顺序挑**第一个命中**的 prefix 去覆盖（`AbstractConfig.java:744-753`）。这层「prefix 优先级」叠加在 `Environment` 的「七档来源优先级」之上，二者共同决定最终值。
- `environment.getConfigurationMaps()` 返回的正是 [Configuration Source and Priority](/docs/CS/Framework/Dubbo/config.md?id=configuration-source-and-priority) 里那七档（按高到低排列），所以 `-Ddubbo.service.xxx` 能覆盖 API `new ServiceConfig().setXxx()` 的原因就在这里：高优先级的 `SystemConfiguration` 子属性先被 `assignProperties` 写回字段。
- `refresh()` 由 `ServiceConfig.export()` / `ReferenceConfig.get()` 在 `postProcessRefresh()` 钩子里触发（详见 [ServiceConfig](/docs/CS/Framework/Dubbo/ServiceConfig.md) 的 export 流程），确保暴露/引用前字段已被配置中心 / `-D` 刷新。

## Configuration Lookup and Validation Internals

### CompositeConfiguration: First-Hit Short-Circuit Lookup

七档优先级的真正落地在 `CompositeConfiguration.getInternalProperty()`，它是一个**短路遍历**，不是 map 合并：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/config/CompositeConfiguration.java:78-95
public Object getInternalProperty(String key) {
    for (Configuration config : configList) {          // :79 按加入顺序
        try {
            Object value = config.getProperty(key);    // :81
            if (!ConfigurationUtils.isEmptyValue(value)) {
                return value;                          // :83 命中即返回，后续源不再读
            }
        } catch (Exception e) {
            logger.error(...);                         // :85-92 单源异常被吞，继续下一档
        }
    }
    return null;                                       // :94 全落空返回 null
}
```

要点：

- `CompositeConfiguration` **只重写了 `getInternalProperty`**，没有重写 `getProperty`——后者是 `Configuration` 接口的 default 方法，最终仍回到 `getInternalProperty`，`null` 时用调用方给的默认值兜底。因此"后加入覆盖先加入"的 map 合并语义**不成立**：后续源的同类 key 根本不会被读。
- "空"的判定是 `ConfigurationUtils.isEmptyValue`：`null` **或** `String` 且 `isBlank` 都算空。所以 `-Ddubbo.protocol.port=`（空串）**不会**短路，会继续降到下一档——空值等价于没配。
- 单个配置源抛异常不会中断查找，只打一条 error 日志继续下一档。

> [!WARNING]
> `Environment.getConfiguration()`（`Environment.java:209-221`）只装了 **6 档**，**缺少 `AbstractConfig` 实例档**。运行期通过 `environment.getConfiguration()` 取 `dubbo.*` 时，注解 / API 显式设置的值不会出现在这里——只有 `getPrefixedConfiguration(config, prefix)` 与 `getConfigurationMaps(config, prefix)` 才是完整七档。

> [!TIP]
> `addConfigurationFirst`（`CompositeConfiguration.java:69-71`）和 `dynamicIncluded`（`:41`）在 3.3.6 主代码里**没有任何调用点**，只有单元测试使用。想插队到 `SystemConfiguration` 之前，目前没有生产级入口。

### ConfigValidator: Where Validation Actually Happens

3.3.6 的校验是**接口 + 单一实现**：接口 `org.apache.dubbo.config.context.ConfigValidator` 只有 `void validate(AbstractConfig config)`，实现是 `DefaultConfigValidator`（`dubbo-config-api/.../config/utils/DefaultConfigValidator.java`），内部按类型分派到 `ConfigValidationUtils`。**不存在** `DubboConfigValidator` 或 `AbstractConfigValidator`。

校验有**两个时机**，且都不是「export 之前单独调一次」：

| 时机 | 调用链 | 校验对象 |
| :--- | :--- | :--- |
| 启动加载期 | `ConfigManager.loadConfigs()` → `refreshAll()` → `checkDefaultAndValidateConfigs()` → `getConfigValidator().validate(config)`（`AbstractConfigManager.java:626-630`） | `ApplicationConfig`、`ProtocolConfig`、`RegistryConfig`、`MonitorConfig`、`MetricsConfig`、`TracingConfig`、`SslConfig` |
| refresh 尾部 | `AbstractConfig.refresh()` → `postProcessRefresh()` → `ConfigValidationUtils.validateServiceConfig(this)`（`ServiceConfig.java:542`） | `ServiceConfig` / `ReferenceConfig` 及其聚合的 registries、protocols |

具体校验项（均在 `dubbo-config-api/.../config/utils/ConfigValidationUtils.java`）：

- **`ApplicationConfig.name` 必填**：`isValid()` 就是 `!StringUtils.isEmpty(name)`（`ApplicationConfig.java:657-661`），不满足直接抛 `No application config found or it's not a valid config!`。
- **端口**：`ProtocolConfig` **没有端口范围校验**（`validateProtocolConfig` 只 check name/host/contextpath/扩展点）。唯一的端口检查是 `ConfigManager` 里的**重复端口冲突**（`Duplicated port used by protocol configs`，`ConfigManager.java:340-353`）。**没有 `qos.port` 冲突检测**，qos 端口只是从 url parameter 取值。
- **`RegistryConfig.address`**：`validateRegistryConfig` **不校验 address**，空 address 会被兜成 `ANYHOST_VALUE`。真正的「必须有注册中心」报错在引用侧（`No such any registry to reference`）。
- **格式校验**：`checkProperty(property, value, maxlength, pattern)`，长度上限 200，正则见 `PATTERN_NAME` 等。

> [!WARNING]
> `checkProperty` 命中违规时**只 `logger.error`，不抛异常**。超长或含非法字符的配置不会中断启动，只会打一条日志——排查「配了但不生效 / 行为异常」时务必翻这段日志。

> [!WARNING]
> `validateMetricsConfig` / `validateTracingConfig` / `validateSslConfig` / `validateConsumerConfig` 是**空实现**，这几类配置当前不做任何校验。

> [!TIP]
> `@Parameter.required()` **只在拼 URL 时生效**（`AbstractConfig.java:244-245`），`refresh()` / `assignProperties` 完全不校验它——`assignProperties` 只消费 `@Parameter.attribute()`（`AbstractConfig.java:799-802`）。所以一个字段标了 `required=true` 但没设值，启动不会失败，而是在 `appendParameters` 阶段抛 `xxx == null`。

## Environment Variable Key Normalization

`EnvironmentConfiguration` 的归一化方向是「把 dubbo 的点分 key **反向大写化**去匹配 OS 环境变量」，共 5 次尝试（`EnvironmentConfiguration.java:33-51`）：

```java
String value = getenv().get(key);                                 // :37 原样直查
if (value != null) return value;
for (String candidateKey : generateCandidateEnvironmentKeys(key)) // :41 4 个候选
    ...
String osStyleKey = StringUtils.toOSStyleKey(key);                // :48 兜底
```

候选生成（`:53-74`，`LinkedHashSet` 去重保序）。以 `dubbo.protocol.port` 为例：

| 次序 | 变换 | 结果 | 行号 |
| :--- | :--- | :--- | :--- |
| 1 | `.`→`_`、`-`→`_`、大写 | `DUBBO_PROTOCOL_PORT` | `:56-61` |
| 2 | `.`→`_`、**删除** `-`、大写 | `DUBBO_PROTOCOL_PORT` | `:63-66` |
| 3 | 仅 `.`→`_`、大写（保留 `-`） | `DUBBO_PROTOCOL_PORT` | `:68-69` |
| 4 | 同 1 但**不**大写 | `dubbo_protocol_port` | `:71` |
| 兜底 | `toOSStyleKey` | `DUBBO_PROTOCOL_PORT` | `:48` + `StringUtils.java:1059-1065` |

兜底 `toOSStyleKey` 的规则（`StringUtils.java:1059-1065`）：`toUpperCase()` → 点转下划线 → **不以 `DUBBO_` 开头则补 `DUBBO_` 前缀**。它只处理点，**不处理连字符**。

> [!WARNING]
> 候选 4 是**未大写**的 `dubbo_protocol_port`（`:71`），Linux 下小写环境变量同样能命中——「环境变量必须全大写」这个直觉在 Dubbo 里不成立。另外连字符有两条路径：候选 1/4 转成 `_`，候选 2 **直接删除**（`:63-65`），所以 `qos-enable` 同时匹配 `DUBBO_APPLICATION_QOS_ENABLE` 与 `DUBBO_APPLICATION_QOSENABLE`。

> [!TIP]
> 兜底会自动补 `DUBBO_` 前缀，因此 key `protocol.port` 也能命中 `DUBBO_PROTOCOL_PORT`；但反过来，自定义的非 `dubbo` 前缀配置在环境变量里必须写成 `DUBBO_<你的key>` 才能被兜底路径识别。

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
- [Governance](/docs/CS/Framework/Dubbo/Governance.md)
- [ConfigCenter](/docs/CS/Framework/Dubbo/ConfigCenter.md)

## References

1. [Dubbo 配置项参考手册](https://cn.dubbo.apache.org/zh-cn/overview/mannual/java-sdk/reference-manual/config/properties/)
2. [Dubbo 配置中心官方文档](https://cn.dubbo.apache.org/zh-cn/overview/mannual/java-sdk/reference-manual/config-center/)
3. [dubbo-common config 源码](https://github.com/apache/dubbo/tree/3.3/dubbo-common/src/main/java/org/apache/dubbo/common/config)
