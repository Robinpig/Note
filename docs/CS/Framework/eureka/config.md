> [!NOTE]
> 本页两张表分别给出**两套默认值**：Netflix 原生 `DefaultEurekaClientConfig` / `DefaultEurekaServerConfig`（v1.10.19）与 Spring Cloud Netflix（`EurekaClientConfigBean` / `EurekaInstanceConfigBean` / `EurekaServerConfigBean`，5.x）。二者并不总是一致，差异项已单列——生产上真正生效的是 Spring Cloud 那一列（如果你用的不是 Spring Cloud，则用 Netflix 那一列）。

## Introduction

Eureka 的配置分三块命名空间：`eureka.instance.*`（我作为实例上报什么）、`eureka.client.*`（我怎么连 Server、多久拉一次）、`eureka.server.*`（Server 自己的剔除与缓存策略）。

**映射机制**：Spring Cloud 并不做 camelCase 转换，而是让 `EurekaClientConfigBean` 之类的类直接实现 Netflix 的接口（`EurekaClientConfig` / `EurekaServerConfig` / `CloudEurekaInstanceConfig`），字段名与接口方法名一致，然后靠 Spring Boot relaxed binding 绑定 `eureka.client.<prop>`。差异只在前缀：Netflix 原生 key 形如 `eureka.<prop>`，Spring Cloud 用 `eureka.client.<prop>` / `eureka.server.<prop>`。少数派生项（`instance-id`、URL 补尾斜杠、`appname` 回填 `spring.application.name`）是例外。

## Instance

| 属性                                        | Netflix 原生 | Spring Cloud | 说明                                                     |
| :---------------------------------------- | :--------- | :----------- | :----------------------------------------------------- |
| `eureka.instance.lease-renewal-interval-in-seconds`     | 30 | 30 | 续约间隔。**不要随便改大**——[自我保护阈值](/docs/CS/Framework/eureka/self_preservation.md)按 30s 折算 fleet 期望值 |
| `eureka.instance.lease-expiration-duration-in-seconds`  | 90 | 90 | 租约时长；实际过期窗口是它的**两倍**（`renew()` 的历史 bug，见 [registry](/docs/CS/Framework/eureka/registry.md?id=lease)） |
| `eureka.instance.prefer-ip-address`                     | — | false | K8s / 多网卡环境常开                                          |
| `eureka.instance.instance-id`                           | — | `hostname:appName:instanceId/port` 表达式 | 默认由 `IdUtils` 生成，容器环境建议显式指定               |
| `eureka.instance.hostname`                              | — | `InetUtils.findFirstNonLoopbackHostInfo()` | |
| `eureka.instance.initial-status`                        | — | `UP` | 若 `instance-enabled-onit=false`，实际以 `STARTING` 注册，就绪后才转 `UP` |
| `eureka.instance.non-secure-port` / `secure-port`       | — | 80 / 443（运行时被 `server.port` 覆盖） | |
| `eureka.instance.appname`                               | — | `unknown` → `spring.application.name` | 不设 `spring.application.name` 会注册成 `UNKNOWN` |
| `eureka.instance.health-check-url-path` / `status-page-url-path` | — | `/actuator/health` / `/actuator/info` | 依赖 Actuator 暴露对应端点 |

## Client

| 属性                                                   | Netflix 原生 | Spring Cloud | 说明                                              |
| :--------------------------------------------------- | :--------- | :----------- | :---------------------------------------------- |
| `eureka.client.registry-fetch-interval-seconds`        | 30         | 30           | 注册表拉取周期，直接决定[感知时延](/docs/CS/Framework/eureka/cache.md?id=感知时延的完整推导) |
| `eureka.client.instance-info-replication-interval-seconds` | 30     | 30           | `InstanceInfoReplicator` 周期                     |
| `eureka.client.initial-instance-info-replication-interval-seconds` | 40 | 40 | 首次注册延迟，给应用留出初始化时间                  |
| `eureka.client.register-with-eureka` / `fetch-registry` | true / true | true / true | 纯消费者可关 `register-with-eureka`；但不要两个都关（否则 client 退化） |
| `eureka.client.disable-delta`                          | false      | false        | 关闭增量退化每次全量；排查注册表不一致时可临时打开               |
| `eureka.client.g-zip-content`                          | —          | true         | 请求 gzip（Spring Cloud 扩展）                        |
| `eureka.client.fetch-remote-regions-registry`          | null       | null         | 多 region 才用                                     |
| `eureka.client.prefer-same-zone-eureka`                | true       | true         | zone 亲和开关                                       |
| `eureka.client.service-url.defaultZone`                | —          | `http://localhost:8761/eureka/` | **务必显式覆盖**，否则会打向 localhost |
| `eureka.client.eureka-server-connect-timeout-seconds` / `read-timeout-seconds` | 5 / 8 | 5 / 8 | |
| `eureka.client.eureka-server-total-connections` / `per-host` | 200 / 50 | 200 / 50 | |
| `eureka.client.eureka-connection-idle-timeout-seconds` | **45**     | **30**       | 差异项                                              |
| `eureka.client.heartbeat-executor-thread-pool-size`    | **5**      | **2**        | 差异项                                              |
| `eureka.client.cache-refresh-executor-thread-pool-size` | **5**     | **2**        | 差异项                                              |
| `*.-exponential-back-off-bound`                        | 10         | 10           | `TimedSupervisorTask` 超时后 delay 翻倍的上限倍数         |
| `eureka.client.healthcheck.enabled`                    | —          | **false**    | 只有设为 true 才会把 Spring `HealthIndicator` 的状态上报为 Eureka 状态 |
| `eureka.client.should-unregister-on-shutdown`          | true       | true         | 决定 `shutdown()` 是否发 DELETE                        |
| `eureka.client.tls.*`                                  | —          | 见下          | 5.x 起支持                                          |

传输层参数（`eureka.client.transport.*`）见 [Transport](/docs/CS/Framework/eureka/transport.md?id=transport-config)，其中 `sessionedClientReconnectIntervalSeconds` 默认 1200s、`asyncResolverRefreshIntervalMs` 默认 300000ms。

TLS：`eureka.client.tls.enabled`（默认 false）+ keyStore / trustStore 等，绑定自 spring-cloud-commons 的 `TlsProperties`，默认 store type 按扩展名推断（`p12`/`pfx` → PKCS12，`jks` → JKS）。

## Server

| 属性                                                | Netflix 原生 | Spring Cloud | 说明                                       |
| :------------------------------------------------ | :--------- | :----------- | :---------------------------------------- |
| `eureka.server.enable-self-preservation`            | true       | true         | 关闭后 `isLeaseExpirationEnabled()` 直接返回 true |
| `eureka.server.renewal-percent-threshold`           | 0.85       | 0.85         | 见[自我保护](/docs/CS/Framework/eureka/self_preservation.md)阈值公式 |
| `eureka.server.eviction-interval-timer-in-ms`       | 60000     | 60000        | 剔除任务周期                                    |
| `eureka.server.renewal-threshold-update-interval-ms` | 900000    | 900000       | 15 分钟                                      |
| `eureka.server.response-cache-update-interval-ms`   | 30000     | 30000        | readOnly 回填周期                              |
| `eureka.server.use-read-only-response-cache`        | true       | true         | **生产建议 false**，可省 30s 感知时延                |
| `eureka.server.response-cache-auto-expiration-in-seconds` | 180  | 180          | readWrite TTL                              |
| `eureka.server.retention-time-in-ms-in-delta-queue`  | 180000    | 180000       | 增量条目 3 分钟                                  |
| `eureka.server.delta-retention-timer-interval-ms`    | 30000     | 30000        | 清理周期                                       |
| `eureka.server.registry-sync-retries`               | **5**      | **0**        | **差异项**：Spring Cloud 默认不同步重试                |
| `eureka.server.registry-sync-retry-wait-ms`         | 30000     | 30000        |                                            |
| `eureka.server.peer-eureka-nodes-update-interval-ms` | 600000    | 600000       | 10 分钟                                      |
| `eureka.server.wait-time-in-ms-when-sync-empty`     | 300000    | 300000       | 5 分钟                                       |
| `eureka.server.max-threads-for-peer-replication`    | 20        | 20           | [复制](/docs/CS/Framework/eureka/replication.md) worker 数 |
| `eureka.server.max-elements-in-peer-replication-pool` | 10000    | 10000        | 队列上限，积压超限会被拒                              |
| `eureka.server.max-time-for-replication`            | 30000     | 30000        | 任务 TTL                                      |
| `eureka.server.number-of-replication-retries`       | 5         | 5            | **注意**：v1.10.19 执行路径并未读取该值，实际重试由 batcher 自己的退避策略决定 |
| `eureka.server.peer-node-connect-timeout-ms` / `read-timeout-ms` | — | 200 / 200 | Peer 复制的 HTTP 超时很激进 |
| `eureka.server.rate-limiter-enabled`                | false      | false        | 配套的 `throttleStandardClients` / `bloomSize`(10) / `registryFetchAverageRate`(500) / `fullFetchAverageRate`(100) |
| `eureka.server.sync-when-timestamp-differs`          | true      | true         | 决定续约时是否用 `lastDirtyTimestamp` 仲裁            |
| `eureka.dashboard.enabled` / `eureka.dashboard.path` | —         | true / `/`   | Dashboard 开关                                |

## Recipes

**开发环境（本地单机、求下线立刻生效）**

```yaml
eureka:
  server:
    enable-self-preservation: false
    eviction-interval-timer-in-ms: 5000
    use-read-only-response-cache: false
  instance:
    lease-renewal-interval-in-seconds: 5
    lease-expiration-duration-in-seconds: 10
  client:
    registry-fetch-interval-seconds: 5
    service-url:
      defaultZone: http://localhost:8761/eureka/
```

**生产<｜hy_place▁holder▁no▁813｜>（保留保护、压低感知时延）**

```yaml
eureka:
  server:
    enable-self-preservation: true
    use-read-only-response-cache: false        # 省掉 30s 回填
    eviction-interval-timer-in-ms: 30000       # 剔除更勤
    peer-eureka-nodes-update-interval-ms: 300000
  instance:
    lease-renewal-interval-in-seconds: 30
    prefer-ip-address: true
  client:
    registry-fetch-interval-seconds: 15        # 客户端感知减半
    healthcheck:
      enabled: true                            # 用 Actuator 健康状态作为上报状态
    service-url:
      defaultZone: http://peer1:8761/eureka/,http://peer2:8761/eureka/,http://peer3:8761/eureka/
```

更多取舍分析见 [Tuning](/docs/CS/Framework/eureka/tuning.md)，相关故障现象见 [Troubleshooting](/docs/CS/Framework/eureka/troubleshooting.md)。

## Links

- [Eureka](/docs/CS/Framework/eureka/Eureka.md)
- [Server](/docs/CS/Framework/eureka/Server.md)
- [Client](/docs/CS/Framework/eureka/Client.md)
- [Transport](/docs/CS/Framework/eureka/transport.md)
- [Tuning](/docs/CS/Framework/eureka/tuning.md)

## References

1. [Netflix/eureka · DefaultEurekaServerConfig](https://github.com/Netflix/eureka/blob/v1.10.19/eureka-core/src/main/java/com/netflix/eureka/DefaultEurekaServerConfig.java)
2. [Spring Cloud Netflix · EurekaClientConfigBean](https://github.com/spring-cloud/spring-cloud-netflix/blob/main/spring-cloud-netflix-eureka-client/src/main/java/org/springframework/cloud/netflix/eureka/EurekaClientConfigBean.java)
