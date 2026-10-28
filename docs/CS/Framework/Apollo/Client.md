# Apollo Client

## Introduction

Apollo 客户端是整个体系里「离业务最近」的一层，它的设计目标文档写得很直白：**服务不可用时应用不能挂**。因此客户端的本地行为（本地文件缓存、定时拉取兜底）和服务端行为（长轮询通知）一样重要。本文覆盖 Java 客户端的启动参数、接入形态与 API 面，基线为 `apolloconfig/apollo-java`（客户端 tag 至 v2.5.0）；推送时序的完整机制见 [Config Push](/docs/CS/Framework/Apollo/Config_Push.md)。

## Artifacts and Runtime

| 制品 | 用途 |
| :-- | :-- |
| `com.ctrip.framework.apollo:apollo-client` | 核心客户端，不依赖任何框架，可在任意 Java 运行时工作（服务端 JDK 17+，客户端 Java 1.8+） |
| `com.ctrip.framework.apollo:apollo-client-config-data` | Spring Boot 2.4+ 的 Config Data Loader 集成，**已包含 `apollo-client`**，官方当前推荐 |

运行时要求 Java 1.8+；对 Spring / Spring Boot 环境有额外支持（下述两种路线）。

## Mandatory: app.id and Meta Server

客户端启动只需要两样东西：**我是谁（app.id）**、**去哪找 Config Service（apollo.meta）**。两者的解析都是多来源优先级链，排错时先看这两条链断在哪一级。

`app.id` 优先级（高 → 低）：

1. Java System Property：`-Dapp.id=YOUR-APP-ID`
2. 操作系统环境变量：`APP_ID=YOUR-APP-ID`
3. Spring Boot `application.properties`：`app.id=...`
4. classpath `/META-INF/app.properties`：`app.id=...`

`apollo.meta` 优先级（高 → 低）：

1. Java System Property：`-Dapollo.meta=http://...`
2. Spring Boot `application.properties` / `bootstrap.properties`：`apollo.meta=...`
3. 操作系统环境变量：`APOLLO_META=http://...`
4. `server.properties`（Mac/Linux 默认 `/opt/settings/server.properties`，Windows `C:\opt\settings\server.properties`）
5. classpath `/META-INF/app.properties`
6. Java System Property `${env}_meta`（如 `-Ddev_meta=http://config-service-url`）
7. 操作系统环境变量 `${ENV}_META`（如 `DEV_META=...`，全大写、`_` 分隔）
8. classpath 或 Spring Boot 配置目录下的 `apollo-env.properties`
9. 以上都失败时兜底 `http://apollo.meta`

要**绕过 Meta Server 直接指定 Config Service**（Docker / K8s 常见）：`-Dapollo.config-service=http://config-service-url:port`（1.9.0+，旧名 `apollo.configService`），或环境变量 `APOLLO_CONFIG_SERVICE`。

## Optional: env, cluster, access key, label

**env**（DEV / FAT / UAT / PRO，大小写不敏感）：`-Denv=DEV` > 环境变量 `ENV=DEV` > `server.properties` 的 `env=DEV`。官方内置四种环境；自定义环境名有强制转换（`PROD` → `PRO`、`FWS` → `FAT`）。

**cluster**（优先级从高到低）：`apollo.cluster` > `idc` > `default`。即 `-Dapollo.cluster=SomeCluster` 优先于 `-Didc=xxx`（或 `server.properties` 的 `idc=`），都没有则归入 `default` 集群。

**access key**（1.6.0+，服务端为应用开启后客户端必须带对，否则 Config Service 返回 **HTTP 401**）：`-Dapollo.access-key.secret=...`（1.9.0+，旧名 `apollo.accesskey.secret`）> Spring Boot properties > 环境变量 `APOLLO_ACCESS_KEY_SECRET` > `/META-INF/app.properties`。

> [!TIP]
>
> 开启 access key 的**正确顺序**：先在 Portal 生成密钥并给所有客户端实例配上，再在 Portal 启用。反过来会先把在线客户端锁在门外。

**label**（2.0.0+）：`-Dapollo.label=YOUR-APOLLO-LABEL`，附加在实例上的标签，供灰度规则按标签匹配——IP 不固定的场景（如 Kubernetes Pod）用它替代 IP 灰度。

## Local File Cache

客户端把从服务端取到的配置在本地文件系统缓存一份，服务不可用或网络不通时**从本地恢复配置，不影响应用运行**：

- 默认路径：Mac/Linux `/opt/data/{appId}/config-cache/`，Windows `C:\opt\data\{appId}\config-cache\`（需确保目录存在且有读写权限）。
- 文件名：`{appId}+{cluster}+{namespace}.properties`，内容为 properties 格式，如 `100004458+default+application.properties`。
- 自定义路径优先级：`-Dapollo.cache-dir=...`（1.9.0+，旧名 `apollo.cacheDir`）> Spring Boot properties > 环境变量 `APOLLO_CACHE_DIR` > `server.properties`。

两个进阶用法：

- **Kubernetes**：可启用 configMap 缓存进一步提高可用性。
- **灾备**：Config Service 全挂需要扩容新机时，可先把存量机器缓存路径下的配置拷贝到新机相同路径，新机启动即可带着旧配置起来，再去连服务端。

## Spring Integration

**路线一：传统 bootstrap 方式**——`apollo.bootstrap.enabled=true`（注入默认 `application` namespace）、`apollo.bootstrap.namespaces=application,FX.apollo,application.yml`（注入多个）；`apollo.bootstrap.eagerLoad.enabled=true`（1.2.0+）可把加载提前到日志系统初始化之前。

**路线二：Config Data Loader（Spring Boot 2.4+，官方推荐）**——引入 `apollo-client-config-data`，用 `spring.config.import` 声明：

```properties
spring.config.import=apollo://                    # 默认 application
spring.config.import=apollo://application
spring.config.import=apollo://your-namespace
spring.config.import=apollo://namespace3, apollo://namespace2, apollo://namespace1
```

注意 `spring.config.import` 是**从后往前**加载，顺序语义与 `apollo.bootstrap.namespaces` 相反。

**注解方式**（不依赖 Spring Boot 自动配置）：

```java
@EnableApolloConfig                              // 默认 application namespace
@EnableApolloConfig({"FX.apollo", "application.yml"})
@EnableApolloConfig(order = 2)
// 2.4.0+ 多 appId：一个进程读多个应用的配置
@EnableApolloConfig(value = {"FX.apollo", "application.yml"},
    multipleConfigs = {@MultipleConfig(appid = "ORDER_SERVICE", namespaces = {"ORDER.apollo"})})
```

## Programmatic API

```java
// 1. 拿 Config：每个 namespace 单例、永不为 null
Config appConfig = ConfigService.getAppConfig();              // 默认 application namespace
Config someConfig = ConfigService.getConfig("FX.apollo");     // 指定 namespace（含公共 namespace）
Config crossApp = ConfigService.getConfig("ORDER_SERVICE", "ORDER.apollo"); // 2.4.0+ 跨 appId

// 2. 监听变更
appConfig.addChangeListener(event -> {
    for (String key : event.changedKeys()) {
        ConfigChange change = event.getChange(key);
        // change.getPropertyName() / getOldValue() / getNewValue() / getChangeType()
    }
});

// 3. 非 properties / yaml 的 namespace（xml / json）走 ConfigFile
ConfigFile file = ConfigService.getConfigFile("test", ConfigFileFormat.XML);
```

注解糖：`@ApolloConfig` 注入 `Config`（`@ApolloConfig("application.yml")` 指定 namespace）；`@ApolloConfigChangeListener` 标注监听方法，可指定 namespace 数组。

`@Value("${someKey:someDefaultValue}")` 的占位符从 **v0.10.0** 起支持运行时自动更新（冒号后为默认值）；关闭方式：System Property `apollo.autoUpdateInjectedSpringProperties=false` 或 `META-INF/app.properties` 同名配置。

> [!WARNING]
>
> **非 properties、非 yaml/yml 格式的 namespace（xml、json 等）不支持和 Spring 整合**——Spring 只吃 key-value 与 yaml 两种形态，xml/json 必须走 `ConfigService.getConfigFile`。

## Ecosystem and Monitoring

- **官方 SDK**：Java、.Net。
- **第三方 SDK**：Golang、Python、NodeJS、PHP、C、Rust；**HTTP API**（经 Portal）供非 JVM 语言直接接入，细节见 [Portal](/docs/CS/Framework/Apollo/Portal.md) 的 Open API 一节。
- **监控**：2.4.0 起提供 `ConfigMonitor` API，可经 JMX / Prometheus 观测客户端的配置加载与推送情况（界面截图见官方文档「客户端使用监控」）。

## Links

- [Apollo](/docs/CS/Framework/Apollo/Apollo.md)
- [Config Push](/docs/CS/Framework/Apollo/Config_Push.md)
- [Namespace](/docs/CS/Framework/Apollo/Namespace.md)
- [Spring Cloud Config](/docs/CS/Framework/Spring_Cloud/Config.md)
- [Spring Boot](/docs/CS/Framework/Spring_Boot/Spring_Boot.md)

## References

- <https://www.apolloconfig.com/#/en/client/java-sdk-user-guide>
- <https://www.apolloconfig.com/#/en/design/apollo-introduction>
- <https://github.com/apolloconfig/apollo-java>
