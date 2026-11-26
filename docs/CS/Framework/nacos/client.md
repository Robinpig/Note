# Nacos Client SDK and Best Practices

## Introduction

Nacos 客户端要理解三件事：**接入模型**（namespace / group / dataId）、**连接方式**（2.x 起以 gRPC 长连接为主通道）、**监听与轮询的取舍**。服务端端口派生见 [JRaft](/docs/CS/Framework/nacos/jraft.md)。

> 版本基线：Nacos 3.2.4（commit 2c587c0）。SDK 相关片段取自 `api` / `client` 模块；Go SDK 与 Spring Cloud Alibaba 属独立仓库，以官方文档为准。

反直觉点：

- 客户端**主通道不是 8848**：配置监听与服务订阅都走 gRPC（9848，`server.port + 1000`），HTTP 只承担一次性读写与兜底。
- `getAllInstances(serviceName)` 默认 `subscribe=true`，读的是**本地缓存**（由推送维护），不是每次打服务端；想要绕过缓存得显式传 `false`。
- **Spring Cloud Alibaba 2025.1.x 已正式移除 `bootstrap.yml`**，必须改用 `spring.config.import=nacos:`；继续写 bootstrap 配置不会生效。
- Nacos 自身**没有内置细粒度 QPS 限流**，限流与黑名单都在前置 Nginx 做（见 [Tuning](/docs/CS/Framework/nacos/tuning.md)）。

## SDK Family and the Entry Point

Java 侧统一入口是 `NacosFactory`。它本身只是一层门面，把创建动作转给 `ConfigFactory` / `NamingFactory`，并顺带暴露 3.x 新增的分布式锁入口：

```java
public class NacosFactory {
    
    public static ConfigService createConfigService(Properties properties) throws NacosException {
        return ConfigFactory.createConfigService(properties);
    }
    
    public static ConfigService createConfigService(String serverAddr) throws NacosException {
        return ConfigFactory.createConfigService(serverAddr);
    }
    
    public static NamingService createNamingService(String serverAddr) throws NacosException {
        return NamingFactory.createNamingService(serverAddr);
    }
    
    public static NamingService createNamingService(Properties properties) throws NacosException {
        return NamingFactory.createNamingService(properties);
    }
    
    public static LockService createLockService(Properties properties) throws NacosException {
        return NacosLockFactory.createLockService(properties);
    }
}
```

`createLockService` 是 3.x 新能力（分布式锁走 CP / JRaft），旧教程里通常不会出现。Go 生态的官方客户端是独立仓库 `github.com/nacos-group/nacos-sdk-go/v2`（Go ≥ 1.15、Nacos ≥ 2.x），其中 `ServerConfig.GrpcPort` 默认也是 `server.port + 1000`；它不在 Nacos server 源码树内，版本节奏与 Java SDK 独立。

> [!WARNING]
> 客户端与服务端**大版本必须匹配**（2.x 客户端连 2.x/3.x，1.x 客户端连 1.x）。1.x 走 HTTP 长轮询，2.x 起改 gRPC，协议不兼容时表现为启动报协议错或监听收不到推送。

## Java SDK: ConfigService

接口契约在 `api/src/main/java/com/alibaba/nacos/api/config/ConfigService.java`。3.2.0 新增的 `getConfigWithResult` 会连 MD5 一起返回，配合 `publishConfigCas` 做乐观并发写：

```java
@Since("0.2.0")
String getConfig(String dataId, String group, long timeoutMs) throws NacosException;

@Since("3.2.0")
default ConfigQueryResult getConfigWithResult(String dataId, String group, long timeoutMs)
    throws NacosException {
    // Default implementation returns content only, without MD5
    String content = getConfig(dataId, group, timeoutMs);
    return new ConfigQueryResult(content, null);
}

@Since("1.1.0")
String getConfigAndSignListener(String dataId, String group, long timeoutMs, Listener listener)
    throws NacosException;

@Since("0.2.0")
void addListener(String dataId, String group, Listener listener) throws NacosException;

@Since("0.2.0")
boolean publishConfig(String dataId, String group, String content) throws NacosException;

@Since("2.0.0")
boolean publishConfigCas(String dataId, String group, String content, String casMd5)
    throws NacosException;
```

要点：

- `getConfig(dataId, group, timeoutMs)` 的 `timeoutMs` 是**读超时**，不是「缓存过期」。
- `getConfigAndSignListener` 把「首次拉取」与「注册监听」合并成一次原子操作，避免两步之间漏掉变更；官方注释也建议优先用它替代「先 get 再 addListener」。
- `addListener` 是**推送语义**：gRPC 长连接下由服务端主动推；不要自己写定时 `getConfig` 轮询，既浪费配额又慢。`Listener.getExecutor()` 可给回调指定线程池，返回 `null` 则在主回调线程执行，重回调会阻塞其它配置推送。

典型用法：

```java
Properties props = new Properties();
props.put("serverAddr", "127.0.0.1:8848");
props.put("namespace", "dev");           // 对应控制台 namespace（tenant_id）
ConfigService configService = NacosFactory.createConfigService(props);

String content = configService.getConfigAndSignListener("example.yaml", "DEFAULT_GROUP", 5000,
    new Listener() {
        @Override public void receiveConfigInfo(String config) { /* 配置变更 */ }
        @Override public Executor getExecutor() { return null; }
    });

configService.publishConfig("example.yaml", "DEFAULT_GROUP", "key: value");
```

## Java SDK: NamingService

接口在 `api/src/main/java/com/alibaba/nacos/api/naming/NamingService.java`。注意 `getAllInstances` / `selectInstances` 都有 `boolean subscribe` 重载，默认走订阅缓存：

```java
void registerInstance(String serviceName, String ip, int port) throws NacosException;

void registerInstance(String serviceName, Instance instance) throws NacosException;

List<Instance> getAllInstances(String serviceName) throws NacosException;

List<Instance> getAllInstances(String serviceName, boolean subscribe) throws NacosException;

List<Instance> selectInstances(String serviceName, boolean healthy) throws NacosException;

void subscribe(String serviceName, EventListener listener) throws NacosException;
```

关键区分：

- `ephemeral=true`（默认）→ **临时实例**，心跳保活，走 Distro（AP），宕机 / 断网会被摘除，见 [Registry](/docs/CS/Framework/nacos/registry.md)。
- `ephemeral=false` → **持久实例**，注册写 JRaft（CP），落库，重启不丢，但写代价更高。
- `selectInstances(..., healthy)` 只返回健康实例；`subscribe` 是长连接推送，优于定时 `getAllInstances` 轮询。

典型用法：

```java
NamingService naming = NacosFactory.createNamingService(props);

naming.registerInstance("order-service", "127.0.0.1", 8080);
naming.registerInstance("order-service", Instance.builder()
        .ip("127.0.0.1").port(8080).ephemeral(false).build());

List<Instance> healthy = naming.selectInstances("order-service", true);
naming.subscribe("order-service", event -> {
    // InstancesChangeEvent：实例列表变化
});
```

## namespace / group / dataId Model

| 维度 | 含义 | 典型用法 |
| :-- | :-- | :-- |
| `namespace` | 租户隔离（对应 `tenant_id`） | 一套 Nacos 多环境：dev / test / prod |
| `group` | 配置 / 服务分组 | 一个应用 / 一个模块一组 |
| `dataId` | 具体配置标识 | `order-service.yaml` |

三者唯一确定一条配置。`namespace` 是强隔离（不同 namespace 互不可见），`group` 是同 namespace 内的逻辑分组。生产约定：**namespace 按环境、group 按应用、dataId 按文件**。

## Connection and Reconnection

- `serverAddr` 可填多个（逗号分隔），客户端对**每个节点建立 gRPC 长连接**，自动探活。
- 节点宕机 / 网络抖动时 SDK **自动重连**其他节点；全部不可达时读本地缓存（`namingLoadCacheAtStart=true` 可预载），写则失败。
- 防火墙必须放行 **9848（gRPC 客户端）** 与 **9849（gRPC 集群间）**，否则出现「能调 OpenAPI 但 SDK 注册不了 / 监听收不到推送」的典型故障，见 [Troubleshooting](/docs/CS/Framework/nacos/troubleshooting.md)。

## Spring Cloud Alibaba

Spring 生态通过 `spring-cloud-starter-alibaba-nacos-config` 与 `spring-cloud-starter-alibaba-nacos-discovery` 接入。当前主流矩阵是 **Spring Cloud Alibaba 2025.1.0.0**（配套 Spring Boot 4.x / Spring Cloud 2025.1.x，内置 Nacos Client 3.1.1；2025.0.x 仍是 3.0.3 + Boot 3.5）。

```yaml
spring:
  application:
    name: order-service
  cloud:
    nacos:
      config:
        server-addr: 127.0.0.1:8848
        namespace: dev
        group: DEFAULT_GROUP
      discovery:
        server-addr: 127.0.0.1:8848
        namespace: dev
  config:
    import:
      - nacos:order-service.yaml              # 拉不到直接启动失败（fail-fast）
      - optional:nacos:common.yaml?group=DEFAULT_GROUP
      - optional:nacos:shared.yaml?refreshEnabled=false
```

> [!WARNING]
> 2025.1.x **正式移除 Spring Cloud Bootstrap**：`bootstrap.yml` / `bootstrap.properties` 不再被支持，必须全部迁入 `spring.config.import`；若引入了 config starter 却没写 `nacos:` 条目，启动会报 `The spring.config.import property is missing a nacos: entry`。仅 2025.0.x 还保留兼容。不要再把 `@NacosValue` 当成 SCA 注入方式——它是 `nacos-spring` 项目的注解（见 [nacos-spring](/docs/CS/Framework/nacos/nacos-spring.md)），SCA 侧用 Spring `@Value` / `@ConfigurationProperties` 配合 `@RefreshScope`。

SCA 还提供两个默认关闭的健康指示器：`spring.cloud.nacos.config.health-indicator.enabled=true` 与 `spring.cloud.nacos.discovery.health-indicator.enabled=true`。**不要**在把 `/actuator/health` 当 K8s liveness probe 时打开它们——网络抖动会把健康状态打成 DOWN，触发大规模 Pod 重启。

## Best Practices

- **用监听 / 订阅，不要轮询**。`addListener` / `getConfigAndSignListener` / `subscribe` 是推送，成本低、时延小。
- **namespace 按环境隔离**，避免 dev 配置误推到 prod；配置发布走 CI，不手改控制台，利用 `his_config_info` 历史回滚。
- **临时实例优先**（默认），只有「宕机也不能丢注册信息」才用持久实例（写经 JRaft）。
- **客户端缓存兜底**：关键配置开启本地缓存，Nacos 全挂时仍能以最后已知值启动。
- **监控客户端指标**（3.2.4 `client/monitor/MetricsMonitor.java`，只有这几个，见 [Monitoring](/docs/CS/Framework/nacos/monitoring.md)）：`nacos_monitor{module="config",name="listenConfigCount"}`、`nacos_monitor{module="naming",name="serviceInfoMapSize"}`、`nacos_client_request{module,method,url,code}`、`nacos_client_naming_request_failed_total{module,req_class,res_status,res_code,err_class}`。早期文档里的 `configListenSize` / `subServiceCount` / `pubServiceCount` 在 3.x 已不存在。

## Links

- [Nacos](/docs/CS/Framework/nacos/Nacos.md)
- [Config](/docs/CS/Framework/nacos/config.md)
- [Registry](/docs/CS/Framework/nacos/registry.md)
- [nacos-spring](/docs/CS/Framework/nacos/nacos-spring.md)
- [Spring Cloud Alibaba](/docs/CS/Framework/Spring_Cloud/Alibaba.md)
- [Troubleshooting](/docs/CS/Framework/nacos/troubleshooting.md)

## References

- <https://nacos.io/docs/latest/manual/user/java-sdk/usage/>
- <https://github.com/nacos-group/nacos-sdk-go>
- <https://github.com/alibaba/spring-cloud-alibaba/releases/tag/2025.1.0.0>
- <https://github.com/spring-cloud-alibaba-group/spring-cloud-alibaba-group.github.io/blob/main/src/content/docs/2025.x/en/user-guide/nacos/advanced-guide.md>
