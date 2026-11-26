# Nacos Monitoring

## Introduction

Nacos 的监控分两类：**Server 自身指标**（JVM / HTTP / gRPC / 配置 / 服务发现）与**健康检查端点**（liveness / readiness）。前者经 Spring Boot Actuator 暴露为 Prometheus 格式，后者给 LB / K8s 探针用。

> 版本基线：Nacos 3.2.4（commit 2c587c0）。片段取自 `prometheus` / `core` / `client` 模块；Nacos server 自身指标由 Micrometer 暴露，Go SDK 侧不在本仓库。

反直觉点：

- 默认 `application.properties` 里 Actuator 暴露是**注释状态**，不显式开启 `/actuator/prometheus` 就是 404。
- 3.x 支持**反向集成**——Prometheus 可以把 Nacos 当服务发现源（`http_sd_configs`），这件事由独立的 `prometheus` 应用完成，不是 Actuator 上的路径。
- v3 的 `/listener` 是**管理员查「谁在监听」**，不是 HTTP 长轮询端点；3.x 里 HTTP 长轮询已是死代码。
- 客户端指标只有 4 个，早期文档常见的 `configListenSize` / `subServiceCount` / `pubServiceCount` 在 3.2.4 全树 0 命中。

## Enable Metrics Exposure

每个 Nacos Server 节点在 `application.properties` 开启：

```properties
management.endpoints.web.exposure.include=prometheus
```

重启后访问 `http://{host}:8848/nacos/actuator/prometheus`。`/nacos` 前缀来自默认 `nacos.server.contextPath`，改过上下文路径就同步调整。端口 / 路径变化也要改 Prometheus 的 `targets` 与 `metrics_path`：

```yaml
scrape_configs:
  - job_name: nacos
    metrics_path: /nacos/actuator/prometheus
    static_configs:
      - targets: [10.0.0.1:8848, 10.0.0.2:8848, 10.0.0.3:8848]
```

## Prometheus Service Discovery (reverse integration)

`prometheus` 模块是一个**独立 Spring Boot 应用**（`PrometheusApp`），对外提供 Prometheus HTTP Service Discovery：

```java
@EnableScheduling
@SpringBootApplication(scanBasePackages = {"com.alibaba.nacos"})
public class PrometheusApp {
    
    public static void main(String[] args) {
        SpringApplication.run(PrometheusApp.class, args);
    }
}
```

它返回的是「Nacos 里注册了谁」，与前面「Nacos 自己跑得怎么样」是两件事。三个端点由 `ApiConstants` 定义：

```java
public static final String PROMETHEUS_CONTROLLER_PATH = "/prometheus";

public static final String PROMETHEUS_CONTROLLER_NAMESPACE_PATH =
    "/prometheus/namespaceId/{namespaceId}";

public static final String PROMETHEUS_CONTROLLER_SERVICE_PATH =
    "/prometheus/namespaceId/{namespaceId}/service/{service}";
```

全量端点先遍历所有 namespace 的单例服务，再取实例，最后交给 `PrometheusUtils.assembleArrayNodes` 组装成 HTTP SD 的 JSON 数组：

```java
@Since("2.2.0")
@GetMapping(value = ApiConstants.PROMETHEUS_CONTROLLER_PATH,
    produces = "application/json; charset=UTF-8")
public ResponseEntity<String> metric() throws NacosException {
    ArrayNode arrayNode = JacksonUtils.createEmptyArrayNode();
    Set<Instance> targetSet = new HashSet<>();
    Set<String> allNamespaces = serviceManager.getAllNamespaces();
    for (String namespace : allNamespaces) {
        Set<Service> singletons = serviceManager.getSingletons(namespace);
        for (Service service : singletons) {
            
            List<? extends Instance> instances = instanceServiceV2.listAllInstances(namespace,
                service.getGroupedServiceName());
            
            targetSet.addAll(instances);
            
        }
    }
    
    PrometheusUtils.assembleArrayNodes(targetSet, arrayNode);
    return ResponseEntity.ok().body(arrayNode.toString());
}
```

`assembleArrayNodes` 把实例 metadata 提升为 Prometheus label（键里的 `.` 与 `-` 被替换成 `_`）：

```java
public static void assembleArrayNodes(Set<Instance> targetSet, ArrayNode arrayNode) {
    Map<String, List<Instance>> groupingInsMap =
        targetSet.stream().collect(groupingBy(Instance::getClusterName));
    groupingInsMap.forEach((key, value) -> {
        for (Instance instance : value) {
            ObjectNode jsonNode = assembleInstanceToArrayNode(key, instance);
            arrayNode.add(jsonNode);
        }
    });
}
```

消费侧用 `http_sd_configs`：

```yaml
scrape_configs:
  - job_name: nacos-sd
    http_sd_configs:
      - url: http://10.0.0.1:8848/prometheus/namespaceId/public
        refresh_interval: 30s
```

> [!NOTE]
> `PrometheusController` 带 `@ConditionalOnProperty(name = "nacos.prometheus.metrics.enabled", havingValue = "true")`，**必须显式开启**才注册。它还有自己的 `PrometheusAuthFilter` 与 `PrometheusSecurityConfiguration`——开鉴权后这些端点同样要过鉴权，不是在 Nacos 主端口上顺带开放的路径。

## Key Metrics

指标名带 Micrometer 类型后缀（timer 通常导出 `_seconds_count` / `_seconds_sum`），排障先搜基名再看 label。

**配置中心（module=config）**

| 指标 | 含义 |
| :-- | :-- |
| `nacos_monitor{module="config",name="getConfig"}` | 配置查询统计 |
| `nacos_monitor{module="config",name="publish"}` | 配置发布统计 |
| `nacos_monitor{module="config",name="configCount"}` | 配置总数 |
| `nacos_monitor{module="config",name="notifyTask"}` | 配置通知任务堆积 |
| `nacos_monitor{module="config",name="notifyClientTask"}` | 客户端通知任务堆积 |
| `nacos_monitor{module="config",name="dumpTask"}` | 配置落盘任务堆积 |
| `nacos_timer{module="config",name="notifyRt"}` | 通知时延 |
| `nacos_timer{module="config",name="dumpRt"}` | 落盘时延 |

**服务发现（module=naming）**：`serviceCount`、`ipCount`、`subscriberCount`、`totalPush`、`failedPush`、`avgPushCost`、`maxPushCost`（均挂在 `nacos_monitor` 上）。

**核心与异常**：`nacos_monitor{module="core",name="longConnection"}` 是各模块 gRPC 长连接数；`nacos_monitor_summary` 汇总 Raft read index / leader read / apply；`nacos_exception{name=...}` 覆盖 `db` / `configNotify` / `unhealth` / `disk` / `leaderSendBeatFailed`。

**请求与 JVM**：`http_server_requests_seconds`、`grpc_server_requests`（带 requestClass / success / errorCode / module）、`grpc_server_executor`（active / pool / queued）、`system_cpu_usage`、`jvm_memory_used_bytes`、`jvm_gc_pause_seconds_*`。

**客户端侧**：`client/src/main/java/com/alibaba/nacos/client/monitor/MetricsMonitor.java` 只注册了三个 Collector——一个 Gauge（`nacos_monitor`，两个 label 组合）、一个 Histogram（`nacos_client_request`）、一个 Counter（`nacos_client_naming_request_failed_total`）：

```java
private static final Gauge NACOS_MONITOR_GAUGE =
    Gauge.build().name("nacos_monitor").labelNames("module", "name")
        .help("nacos_monitor").register();

private static final Histogram NACOS_CLIENT_REQUEST_HISTOGRAM = Histogram.build()
    .labelNames("module", "method", "url", "code").name("nacos_client_request")
    .help("nacos_client_request")
    .register();

private static final Counter NACOS_CLIENT_NAMING_REQUEST_FAILED_TOTAL = Counter.build()
    .name("nacos_client_naming_request_failed_total")
    .help("nacos_client_naming_request_failed_total")
    .labelNames("module", "req_class", "res_status", "res_code", "err_class").register();

public static Gauge.Child getServiceInfoMapSizeMonitor() {
    return NACOS_MONITOR_GAUGE.labels("naming", "serviceInfoMapSize");
}

public static Gauge.Child getListenConfigCountMonitor() {
    return NACOS_MONITOR_GAUGE.labels("config", "listenConfigCount");
}
```

> [!WARNING]
> 正确的客户端指标写法是 `listenConfigCount`（配置监听数）与 `serviceInfoMapSize`（服务缓存数）；`configListenSize` / `subServiceCount` / `pubServiceCount` 在 3.2.4 源码里不存在。

> [!WARNING]
> Server 侧 `MetricsMonitor` 里仍有 `longPolling` 字段，但**实际恒为 0**：v1 长轮询路由常量虽保留，`config` 模块已无对应 controller 映射；唯一的 `@GetMapping("/listener")` 在 `ConfigControllerV3`，语义是管理员查询「哪些客户端在监听」。所以这条指标不要拿来做告警，见 [Config Push](/docs/CS/Framework/nacos/config-push.md)。

## 3.x Health Check Interface

`ServerStateController` 把三个探针放在统一上下文 `/v3/admin/core/state` 下，liveness 恒返回 ok，readiness 则真正调用模块健康检查器：

```java
@RestController
@RequestMapping(NACOS_ADMIN_CORE_CONTEXT_V3 + "/state")
public class ServerStateController {
    
    @Since("3.0.0")
    @GetMapping("/liveness")
    public Result<String> liveness() {
        return Result.success("ok");
    }
    
    @Since("3.0.0")
    @GetMapping("/readiness")
    public Result<String> readiness() throws NacosException {
        ReadinessResult result = ModuleHealthCheckerHolder.getInstance().checkReadiness();
        if (result.isSuccess()) {
            return Result.success("ok");
        }
        return Result.failure(result.getResultMessage());
    }
}
```

`NACOS_ADMIN_CORE_CONTEXT_V3 = NACOS_SERVER_VERSION_V3 + "/admin/core"`，即 `/v3/admin/core`。完整端点表：

| 端点 | 用途 |
| :-- | :-- |
| `/nacos/v3/admin/core/state` | Server 状态总览 |
| `/nacos/v3/admin/core/state/liveness` | 存活探针 |
| `/nacos/v3/admin/core/state/readiness` | 就绪探针 |
| `/v3/console/health/liveness` | 独立 Console 存活 |
| `/v3/console/health/readiness` | 独立 Console 就绪 |

## Suggested Alert Items

- **`notifyTask` / `dumpTask` 持续上涨**：配置变更堆积，DB 写慢或磁盘 IO 瓶颈。
- **`failedPush` 升高 / `avgPushCost` 变大**：服务发现推送跟不上，客户端连接多或网络差 → 看 `longConnection` 与 `grpc_server_executor` 队列。
- **`nacos_exception{name="db"}` 非零**：MySQL 连接 / 慢 SQL / 锁问题。
- **Leader 频繁切换**：CP 侧 JRaft 端口 7848 不通或节点抖动，见 [JRaft](/docs/CS/Framework/nacos/jraft.md)。
- **`longConnection` 逼近单机上限**（8C16G 约 9000，运维经验值而非源码常量）：需扩容或在前置 Nginx 限流（见 [Tuning](/docs/CS/Framework/nacos/tuning.md)）。

## Links

- [Nacos](/docs/CS/Framework/nacos/Nacos.md)
- [JRaft](/docs/CS/Framework/nacos/jraft.md)
- [Config Push](/docs/CS/Framework/nacos/config-push.md)
- [Troubleshooting](/docs/CS/Framework/nacos/troubleshooting.md)

## References

- <https://nacos.io/docs/latest/manual/admin/monitor/>
