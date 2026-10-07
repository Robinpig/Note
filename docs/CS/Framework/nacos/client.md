# Nacos Client SDK and Best Practices

## Introduction

Nacos 提供多语言 SDK，但生产主力是 **Java SDK**（核心包 `nacos-client`）与 **Spring Cloud Alibaba** 封装。客户端要理解三件事：**接入模型（namespace / group / dataId）**、**连接方式（2.x 起 gRPC 长连接）**、**监听 vs 轮询**。

Nacos 服务端端口派生在 [JRaft](/docs/CS/Framework/nacos/jraft.md) 已列：SDK 默认连 **9848（gRPC，`server.port + 1000`）**，旧版 1.x 走 HTTP 8848 长轮询。客户端与服务端**大版本必须匹配**（2.x 客户端连 2.x/3.x 服务端，1.x 客户端连 1.x），否则协议不兼容。

## Java SDK：ConfigService

`ConfigService` 管配置中心的读写与监听：

```java
Properties props = new Properties();
props.put("serverAddr", "127.0.0.1:8848");
props.put("namespace", "dev");           // 对应控制台 namespace（tenant_id）
ConfigService configService = NacosFactory.createConfigService(props);

// 读
String content = configService.getConfig("example.yaml", "DEFAULT_GROUP", 5000);

// 写
configService.publishConfig("example.yaml", "DEFAULT_GROUP", "key: value");

// 监听（2.x 走 gRPC 推送，不是轮询）
configService.addListener("example.yaml", "DEFAULT_GROUP", new Listener() {
    @Override public void receiveConfigInfo(String config) { /* 配置变更 */ }
    @Override public Executor getExecutor() { return null; }
});
```

要点：

- `getConfig(dataId, group, timeoutMs)` 的 `timeoutMs` 是等待超时，不是「缓存过期」。
- `publishConfig` 返回 `boolean`，失败（如容量超限、鉴权拒绝）直接抛 / 返 false。
- **`addListener` 是推送语义**：2.x 客户端与服务端建立 gRPC 长连接，配置变更由服务端主动推；1.x 才是 HTTP 长轮询（每 30s 阻塞一次）。不要自己写「定时 getConfig 轮询」——既浪费配额又慢。

## Java SDK：NamingService

`NamingService` 管服务注册与发现：

```java
NamingService naming = NacosFactory.createNamingService(props);

// 注册（默认 ephemeral=true → 走 Distro/AP）
naming.registerInstance("order-service", "127.0.0.1", 8080);
// 持久实例：显式 ephemeral=false → 走 JRaft/CP
naming.registerInstance("order-service", Instance.builder()
        .ip("127.0.0.1").port(8080).ephemeral(false).build());

// 发现
List<Instance> all = naming.getAllInstances("order-service");
List<Instance> healthy = naming.selectInstances("order-service", true);

// 订阅（推送模式）
naming.subscribe("order-service", event -> {
    // InstancesChangeEvent：实例列表变化
});
```

关键区分：

- `ephemeral=true`（默认）→ **临时实例**，心跳保活，走 Distro（AP），宕机 / 断网会被摘除，见 [Registry](/docs/CS/Framework/nacos/registry.md)。
- `ephemeral=false` → **持久实例**，注册写 JRaft（CP），落库，重启不丢，但写代价更高。
- `selectInstances(..., healthy)` 只返回健康实例；`subscribe` 是长连接推送，优于定时 `getAllInstances` 轮询。

## namespace / group / dataId Model

| 维度 | 含义 | 典型用法 |
| :-- | :-- | :-- |
| `namespace` | 租户隔离（对应 `tenant_id`） | 一套 Nacos 多环境：dev / test / prod |
| `group` | 配置 / 服务分组 | 一个应用 / 一个模块一组 |
| `dataId` | 具体配置标识 | `order-service.yaml` |

三者唯一确定一条配置。`namespace` 是强隔离（不同 namespace 互不可见），`group` 是同 namespace 内的逻辑分组。生产约定：**namespace 按环境、group 按应用、dataId 按文件**。

## Connection and Reconnection

- `serverAddr` 可填多个（逗号分隔），对应集群成员；客户端对**每个节点建立 gRPC 长连接**，自动探活。
- 节点宕机 / 网络抖动时 SDK **自动重连**其他节点，业务无感；若全部不可达，读本地缓存（启动时 `namingLoadCacheAtStart=true` 可预载缓存）、写则失败。
- 防火墙必须放行 **9848（gRPC 客户端）** 与 **9849（gRPC 服务端）**，否则出现「能调 OpenAPI 但 SDK 注册不了 / 监听收不到推送」的典型故障，见 [Troubleshooting](/docs/CS/Framework/nacos/troubleshooting.md)。
- `failFast`（部分场景 `namingLoadCacheAtStart` / `configLongPoll` 相关）控制启动时连不上是否直接失败；线上建议开启以便快速暴露配置错误，而非静默用旧值。

## Spring Cloud Alibaba

Spring 生态通过 `spring-cloud-starter-alibaba-nacos-config` 与 `spring-cloud-starter-alibaba-nacos-discovery` 接入：

```yaml
spring:
  cloud:
    nacos:
      config:
        server-addr: 127.0.0.1:8848
        namespace: dev
        group: DEFAULT_GROUP
        file-extension: yaml
      discovery:
        server-addr: 127.0.0.1:8848
        namespace: dev
```

- 配置通过 `@NacosValue("${key:default}")` 或 Spring `@Value` + `@RefreshScope` 注入，变更自动刷新。
- 版本兼容是高频坑：**Spring Boot 3 必须配兼容的 Spring Cloud Alibaba 版本**（如 2022.0.0.0 / 2023.x 系列），且**Nacos 客户端与服务端大版本要严格匹配**，否则启动报协议错或监听失效。升级 Nacos 服务端时一并核对 SCA 版本矩阵。
- 2.4+ 的 Spring Boot 用 `spring.config.import=nacos:...` 引入 Nacos 配置；旧版用 `bootstrap.yml`。

## Best Practices

- **用监听 / 订阅，不要轮询**。`addListener` / `subscribe` 是推送，成本低、时延小；自己定时拉等于退化成 1.x 长轮询且易触发限流。
- **namespace 按环境隔离**，避免 dev 配置误推到 prod。
- **配置发布走 CI**，不手改控制台；利用 `his_config_info` 历史做回滚。
- **临时实例优先**（默认），只有「宕机也不能丢注册信息」的强一致诉求才用持久实例（写经 JRaft，代价高）。
- **客户端缓存兜底**：关键配置开启本地缓存，Nacos 全挂时仍能以最后已知值启动。
- **监控客户端指标**：`nacos_monitor{name='configListenSize'}`、`subServiceCount` / `pubServiceCount`、`nacos_client_request_seconds_*` 可观测客户端负载（见 [Monitoring](/docs/CS/Framework/nacos/monitoring.md)）。

## Links

- [Nacos](/docs/CS/Framework/nacos/Nacos.md)
- [Config](/docs/CS/Framework/nacos/config.md)
- [Registry](/docs/CS/Framework/nacos/registry.md)
- [nacos-spring](/docs/CS/Framework/nacos/nacos-spring.md)
- [Spring Cloud Alibaba](/docs/CS/Framework/Spring_Cloud/Alibaba.md)
- [Troubleshooting](/docs/CS/Framework/nacos/troubleshooting.md)

## References

- <https://nacos.io/docs/v3.0/guide/user/sdk/java-sdk/>
- <https://spring.io/projects/spring-cloud-alibaba>
- <https://nacos.io/docs/latest/manual/user/quick-start/>
