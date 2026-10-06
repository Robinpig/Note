## Introduction

Dubbo 3.3 的可观测性（metrics + tracing）统一建立在 Micrometer Observation 之上，配置项多、默认值分散，且不少二手文章把「文档描述」当成「源码行为」。本文从源码层面澄清三个最常见的误解：

- **「有个 `dubbo.metrics.enable` 总开关」**——不成立。`MetricsConfig` 里**没有**这个名字，只有 `enableJvm` / `enableThreadpool` / `enableRegistry` / `enableMetadata` / `enableNetty` / `enableRpc` / `enableCollectorSync` / `enableMetricsInit` 这类分项开关；是否启用指标体系的**总闸**是「classpath 上有没有 Micrometer」，由 `MetricsSupportUtil.isSupportMetrics()` 判定。
- **「Prometheus 抓取默认端口 20888」**——不成立。`MetricsConstants.java:90` 确实定义了 `PROMETHEUS_DEFAULT_METRICS_PORT = 20888`，但它是**死常量**，定义后再无任何主源码引用；`dubbo-metrics-prometheus` 里**没有 HTTP exporter**，实际导出走的是 **QoS 命令 `metrics`**（默认 QoS 端口 22222）。把 20888 写进 Prometheus 抓取配置会抓不到数据。
- **「Dubbo 有 `TracingFilter`」**——不成立。全树检索 `TracingFilter` 只命中 `FutureContext.java:96,110` 的 javadoc 示例，**没有这个类**。实际埋点是 provider 侧 `ObservationReceiverFilter` 与 consumer 侧 `ObservationSenderFilter`。

版本基线：Apache Dubbo **3.3.6**，源码 tag `dubbo-3.3.6`。本文所有默认值、类名、SPI 注册均取自该 tag 的源码文件；「不存在」的结论均在同一棵源码树上做过全量检索。

## Metrics 模块结构与启用条件

### 子模块清单

`dubbo-metrics/` 下有 9 个子模块，职责按「采集」与「导出」分离：

| 模块 | 职责 |
| :--- | :--- |
| `dubbo-metrics-api` | 采集器接口与报告接口（`MetricsCollector`、`MetricsReporter` 等） |
| `dubbo-metrics-default` | 默认采集器集合 + 默认 reporter |
| `dubbo-metrics-prometheus` | Prometheus reporter 与 QoS 命令 |
| `dubbo-metrics-event` | 指标事件模型（`MetricsKey`、`MetricsLevel`、`TimePair`） |
| `dubbo-metrics-metadata` | 元数据指标采集器 |
| `dubbo-metrics-netty` | Netty 指标采集器（`NettyMetricsCollector`、`NettyEvent`） |
| `dubbo-metrics-registry` | 注册中心指标采集器 |
| `dubbo-metrics-config-center` | 配置中心指标采集器 |
| `dubbo-tracing` | 链路追踪（见下文，注意它在 `dubbo-metrics/` 下） |

采集器接口位于 `dubbo-metrics-api/.../metrics/collector`，主要有 `MetricsCollector`、`ApplicationMetricsCollector`、`ServiceMetricsCollector`、`MethodMetricsCollector`、`CombMetricsCollector`，另有 `stat` 子包放统计模型。

### 启用条件：classpath 判定，而非总开关

> [!WARNING]
> 打假：**不存在 `dubbo.metrics.enable` 这个总开关。** 在 `MetricsConfig` 里检索 `enable` 前缀，得到的是 `enableJvm` / `enableThreadpool` / `enableRegistry` / `enableMetadata` / `enableNetty` / `enableRpc` / `enableCollectorSync` / `enableMetricsInit` 这些分项。「用 `dubbo.metrics.enable=true` 开启指标」是错的。

是否启用指标体系的判定写死在工具类里，判据是**类路径上是否存在 Micrometer 类**：

```java
// dubbo-metrics/dubbo-metrics-api/.../metrics/utils/MetricsSupportUtil.java:21-33
public static boolean isSupportMetrics() {
    return isClassPresent("io.micrometer.core.instrument.MeterRegistry");
}

public static boolean isSupportPrometheus() {
    return isClassPresent("io.micrometer.prometheus.PrometheusConfig")
            && isClassPresent("io.prometheus.client.exporter.BasicAuthHttpConnectionFactory")
            && isClassPresent("io.prometheus.client.exporter.HttpConnectionFactory")
            && isClassPresent("io.prometheus.client.exporter.PushGateway");
}
```

两点要说明：

- **`isSupportMetrics()` 的判据只有一个类**：只要 classpath 上有 `io.micrometer.core.instrument.MeterRegistry`（即引入了 `micrometer-core`），指标采集就具备启动条件。
- **`isSupportPrometheus()` 是 4 个类的与运算**，不止 `PrometheusConfig`。除了 Micrometer 的 Prometheus 绑定，还要求 Prometheus Java client 的 `PushGateway` 等类在场。只引入一半依赖会导致 Prometheus 协议被判为不可用。

### 分项开关与默认值

`MetricsConfig` 的分项开关是「在已启用指标的前提下」控制各采集器是否工作：

```java
// dubbo-common/src/main/java/org/apache/dubbo/config/MetricsConfig.java:34-113（节选）
private String protocol;
private Boolean enableJvm;
private Boolean enableThreadpool;
private Boolean enableRegistry;
private Boolean enableMetadata;
private Boolean exportMetricsService;
private Boolean enableNetty;
private Boolean enableMetricsInit;
private Boolean enableCollectorSync;
private Integer collectorSyncPeriod;
@Nested private PrometheusConfig prometheus;
@Nested private AggregationConfig aggregation;
@Nested private HistogramConfig histogram;
private String exportServiceProtocol;
private Integer exportServicePort;
private Boolean useGlobalRegistry;
private Boolean enableRpc;
private String rpcLevel;   // "SERVICE" or "METHOD"，默认 METHOD
```

其中两个开关在初始化时被显式赋予 `true` 兜底：

```java
// dubbo-config/dubbo-config-api/.../deploy/DefaultApplicationDeployer.java:401-404（节选）
collector.setThreadpoolCollectEnabled(
        Optional.ofNullable(metricsConfig.getEnableThreadpool()).orElse(true));
collector.setMetricsInitEnabled(
        Optional.ofNullable(metricsConfig.getEnableMetricsInit()).orElse(true));
```

即 `enableThreadpool` 与 `enableMetricsInit` 的**默认值是 `true`**（未配置时启用），其余分项未配置时由各自 `Optional.ofNullable(...).orElse(...)` 语义决定。

## 默认协议推导与 exporter 现状

### `dubbo.metrics.protocol` 没有硬编码默认常量

协议不是写死的常量，而是**运行时推导**：未显式配置时，有 Prometheus 依赖就选 `prometheus`，否则选 `default`。

```java
// dubbo-config/dubbo-config-api/.../deploy/DefaultApplicationDeployer.java:392-398（节选）
if (PROTOCOL_PROMETHEUS.equals(metricsConfig.getProtocol()) && !MetricsSupportUtil.isSupportPrometheus()) {
    return;
}
if (StringUtils.isBlank(metricsConfig.getProtocol())) {
    metricsConfig.setProtocol(
            MetricsSupportUtil.isSupportPrometheus() ? PROTOCOL_PROMETHEUS : PROTOCOL_DEFAULT);
}
```

再往下，`MetricsReporterFactory` 的 SPI 只有两个扩展名，决定了「导出到哪」：

```properties
# dubbo-metrics/dubbo-metrics-api/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.metrics.report.MetricsReporterFactory
default=org.apache.dubbo.metrics.report.DefaultMetricsReporterFactory
prometheus=org.apache.dubbo.metrics.prometheus.PrometheusMetricsReporterFactory
```

> [!NOTE]
> 推导逻辑还有一个副作用：当协议不是 `default` 时，`DefaultApplicationDeployer` 会**额外再初始化一个 default reporter**（源码注释 "If the protocol is not the default protocol, the default protocol is also initialized."）。这是为了让 QoS 查询与 Prometheus 导出能同时工作，不是配置错误。

### 打假：20888 是死常量，导出走 QoS

这是本文最重要的打假点。

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/constants/MetricsConstants.java:74,90-96
String PROMETHEUS_EXPORTER_METRICS_PORT_KEY = "prometheus.exporter.metrics.port";
int PROMETHEUS_DEFAULT_METRICS_PORT = 20888;
String PROMETHEUS_DEFAULT_METRICS_PATH = "/metrics";
int PROMETHEUS_DEFAULT_PUSH_INTERVAL = 30;
String PROMETHEUS_DEFAULT_JOB_NAME = "default_dubbo_job";
```

对整棵源码树检索 `PROMETHEUS_DEFAULT_METRICS_PORT` 与 `PROMETHEUS_EXPORTER_METRICS_PORT_KEY`，**命中只有常量定义自身**，没有任何生产代码读取它们。`dubbo-metrics-prometheus` 模块的全部文件是：

```properties
# dubbo-metrics/dubbo-metrics-prometheus/src/main 目录清单
.../prometheus/NopPrometheusMetricsReporter.java
.../prometheus/PrometheusMetricsReporter.java
.../prometheus/PrometheusMetricsReporterCmd.java
.../prometheus/PrometheusMetricsReporterFactory.java
.../resources/META-INF/dubbo/internal/org.apache.dubbo.metrics.report.MetricsReporterFactory
.../resources/META-INF/dubbo/internal/org.apache.dubbo.qos.api.BaseCommand
```

**没有任何 `HttpServer` / `HttpExporter` / Netty HTTP 服务**。导出的真实通道是一个 QoS 命令：

```java
// dubbo-metrics/dubbo-metrics-prometheus/.../prometheus/PrometheusMetricsReporterCmd.java:37-38
@Cmd(name = "metrics", summary = "reuse qos report")
public class PrometheusMetricsReporterCmd implements BaseCommand {
```

它从 registry 里 `scrape()` 出文本格式，通过 QoS telnet 通道返回：

```java
// dubbo-metrics/dubbo-metrics-prometheus/.../prometheus/PrometheusMetricsReporter.java:67-68
public String getResponse() {
    return prometheusRegistry.scrape();
}
```

> [!WARNING]
> **很多文章写「Prometheus 抓 `http://<host>:20888/metrics`」，这在 3.3.6 源码上不成立。** `20888` 是定义了却无人使用的常量，模块里没有监听该端口的 HTTP 服务。正确做法是让 Prometheus 通过 **QoS 端口（默认 22222）** 执行 `metrics` 命令拉取，或使用 Pushgateway 推送。若一定要走 HTTP 拉取，需要自己写一个薄薄的 Exporter 把 QoS 的 `metrics` 输出暴露出去。

### Pushgateway 推送（默认关闭）

推送模式默认关闭，由配置显式打开：

```java
// dubbo-metrics/dubbo-metrics-prometheus/.../prometheus/PrometheusMetricsReporter.java:71-79（节选）
private void schedulePushJob() {
    boolean pushEnabled = url.getParameter(PROMETHEUS_PUSHGATEWAY_ENABLED_KEY, false);
    if (pushEnabled) {
        String baseUrl = url.getParameter(PROMETHEUS_PUSHGATEWAY_BASE_URL_KEY);
        String job = url.getParameter(PROMETHEUS_PUSHGATEWAY_JOB_KEY, PROMETHEUS_DEFAULT_JOB_NAME);
        int pushInterval =
                url.getParameter(PROMETHEUS_PUSHGATEWAY_PUSH_INTERVAL_KEY, PROMETHEUS_DEFAULT_PUSH_INTERVAL);
        ...
    }
}
```

- `prometheus.pushgateway.enabled` 默认 `false`（`MetricsConstants.java:78`）。
- 推送到 job `default_dubbo_job`，间隔 `30` 秒（`PROMETHEUS_DEFAULT_PUSH_INTERVAL`），支持 basic auth。
- 推送模式适合短生命周期任务或无法被 Prometheus 主动抓取的实例。

## 指标采集器清单

采集器通过 `org.apache.dubbo.metrics.collector.MetricsCollector` 的 SPI 注册，按模块分组：

| 模块 | 注册文件中的扩展名 → 实现 |
| :--- | :--- |
| `dubbo-metrics-default` | `default-collector` → `DefaultMetricsCollector`；`aggregateMetricsCollector` → `AggregateMetricsCollector`；`configCenterMetricsCollector` → `ConfigCenterMetricsCollector`；`histogramMetricsCollector` → `HistogramMetricsCollector` |
| `dubbo-metrics-registry` | `registry-collector` → `RegistryMetricsCollector` |
| `dubbo-metrics-metadata` | `metadata-collector` → `MetadataMetricsCollector` |

> [!NOTE]
> `dubbo-metrics-default` 的 SPI 文件里除了 `MetricsCollector`，还注册了 `ClusterFilter`、`Filter`、`ScopeModelInitializer`、`MetricsService`、`MetricsReporterFactory` 等多个 SPI。采集能力是靠这些入口把事件喂进采集器的，`DefaultMetricsCollector` 只是聚合点之一。

## Tracing

### 模块位置与依赖结构

Tracing 位于 **`dubbo-metrics/dubbo-tracing`**，不是顶层 `dubbo-tracing/`。它内部把 Brave 与 OTel 放在**同一个模块的两个包**里：

```properties
# 包结构（dubbo-metrics/dubbo-tracing/src/main/java/org/apache/dubbo/tracing/）
tracer/TracerProviderFactory.java
tracer/TracerProvider.java
tracer/PropagatorProviderFactory.java
tracer/brave/BraveProvider.java
tracer/brave/BravePropagatorProvider.java
tracer/otel/OpenTelemetryProvider.java
tracer/otel/OTelPropagatorProvider.java
filter/ObservationReceiverFilter.java
filter/ObservationSenderFilter.java
```

> [!WARNING]
> 打假：**不存在 `dubbo-tracing-brave` / `dubbo-tracing-otel` 独立模块。** Brave 与 OTel 是同一模块内的两个包 `org.apache.dubbo.tracing.tracer.brave` 与 `...tracer.otel`，由工厂按 classpath 二选一（OTel 优先）：

```java
// dubbo-metrics/dubbo-tracing/.../tracing/tracer/TracerProviderFactory.java:27-38（节选）
public static TracerProvider getProvider(ApplicationModel applicationModel, TracingConfig tracingConfig) {
    // If support OTel firstly, return OTel, then Brave.
    if (ObservationSupportUtil.isSupportOTelTracer()) {
        return new OpenTelemetryProvider(applicationModel, tracingConfig);
    }

    if (ObservationSupportUtil.isSupportBraveTracer()) {
        return new BraveProvider(applicationModel, tracingConfig);
    }

    return null;
}
```

同一时刻只会启用一种实现：classpath 同时存在两者时是 **OTel 优先**。

### `dubbo.tracing.enabled` 默认 false

```java
// dubbo-common/src/main/java/org/apache/dubbo/config/TracingConfig.java:33-36
/**
 * Indicates whether the feature is enabled (default is false).
 */
private Boolean enabled = false;
```

配置前缀常量在 Spring Boot 侧定义：

```java
// dubbo-spring-boot-project/.../observability/ObservabilityUtils.java:29
public static final String DUBBO_TRACING_PREFIX = DUBBO_PREFIX + PROPERTY_NAME_SEPARATOR + "tracing";
```

Spring Boot 自动配置由一个条件注解控制：

```java
// dubbo-spring-boot-project/.../observability/annotation/ConditionalOnDubboTracingEnable.java:41
@ConditionalOnProperty(prefix = ObservabilityUtils.DUBBO_TRACING_PREFIX, name = "enabled")
```

> [!NOTE]
> `@ConditionalOnProperty` 未写 `havingValue` / `matchIfMissing`，因此等价于 `matchIfMissing=false`：**不显式配 `dubbo.tracing.enabled=true` 就不装 tracing 相关 Bean**。裸 Dubbo（非 Spring Boot）则由 `DefaultApplicationDeployer.initObservationRegistry()` 里的 `configOptional.get().getEnabled()` 判断，同样默认关闭。

### 打假：不存在 TracingFilter

埋点是两个 Filter，分别注册在两个不同的 SPI 上：

```properties
# dubbo-metrics/dubbo-tracing/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.rpc.Filter
observationreceiver=org.apache.dubbo.tracing.filter.ObservationReceiverFilter
```

```properties
# dubbo-metrics/dubbo-tracing/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.rpc.cluster.filter.ClusterFilter
observationsender=org.apache.dubbo.tracing.filter.ObservationSenderFilter
```

| Filter | SPI 类型 | 扩展名 | 侧 |
| :--- | :--- | :--- | :--- |
| `ObservationReceiverFilter` | `org.apache.dubbo.rpc.Filter` | `observationreceiver` | Provider（收请求、起服务端 span） |
| `ObservationSenderFilter` | `org.apache.dubbo.rpc.cluster.filter.ClusterFilter` | `observationsender` | Consumer（发请求、起客户端 span） |

> [!WARNING]
> 全树检索 `TracingFilter` 只命中 `dubbo-rpc/dubbo-rpc-api/.../rpc/FutureContext.java:96,110` 的 javadoc 示例代码，**这个类不存在**。任何「自定义 `TracingFilter`」的教程在 3.3.6 上都无法照抄；要扩展埋点应基于 Micrometer 的 `ObservationHandler` / `ObservationRegistry`，或自行实现 `Filter`。

### ObservationRegistry 接入

`DefaultApplicationDeployer` 在启动时尝试初始化 ObservationRegistry：

```java
// dubbo-config/dubbo-config-api/.../deploy/DefaultApplicationDeployer.java:434-455（节选）
private void initObservationRegistry() {
    if (!ObservationSupportUtil.isSupportObservation()) {
        if (logger.isDebugEnabled()) {
            logger.debug("Not found micrometer-observation or plz check the version of micrometer-observation version if already introduced, need > 1.10.0");
        }
        return;
    }
    if (!ObservationSupportUtil.isSupportTracing()) {
        ...
        return;
    }
    Optional<TracingConfig> configOptional = configManager.getTracing();
    if (!configOptional.isPresent() || !configOptional.get().getEnabled()) {
        return;
    }

    DubboObservationRegistry dubboObservationRegistry =
            new DubboObservationRegistry(applicationModel, configOptional.get());
    dubboObservationRegistry.initObservationRegistry();
}
```

真正的注册逻辑有一个「**优先复用外部 registry**」的语义：

```java
// dubbo-metrics/dubbo-tracing/.../tracing/DubboObservationRegistry.java:57-88（节选）
public void initObservationRegistry() {
    // If get ObservationRegistry.class from external(eg Spring.), use external.
    ObservationRegistry externalObservationRegistry =
            applicationModel.getBeanFactory().getBean(ObservationRegistry.class);
    if (externalObservationRegistry != null) {
        if (logger.isDebugEnabled()) {
            logger.debug("ObservationRegistry.class from external is existed.");
        }
        return;
    }
    ...
    TracerProvider tracerProvider = TracerProviderFactory.getProvider(applicationModel, tracingConfig);
    ...
    ObservationRegistry registry = ObservationRegistry.create();
    ...
}
```

结论：**如果容器（如 Spring Boot Actuator / Micrometer Tracing 自动配置）已经注册了一个 `ObservationRegistry` Bean，Dubbo 直接复用它，不再自建**。这保证 Dubbo 的 span 与应用其他埋点共享同一套 registry 与 exporter。

## Micrometer Observation 统一模型

Dubbo 3.3 的可观测性收敛到 Micrometer Observation 这一层，metrics 与 tracing **共用同一个 `ObservationRegistry`**：

```dot
digraph observation {
  rankdir=LR;
  node [shape=box, fontname="Helvetica"];
  REQ [label="Dubbo 调用 (Provider/Consumer)"];
  FILTER [label="Observation*Filter\n(起 Observation)"];
  REG [label="ObservationRegistry\n(外部优先，否则自建)"];
  METRICS [label="MeterRegistry\n(Micrometer -> Prometheus/default)"];
  TRACE [label="Tracer\n(OTel / Brave, 二选一)"];
  REQ -> FILTER -> REG;
  REG -> METRICS [label="metrics"];
  REG -> TRACE [label="tracing"];
}
```

这套模型是 **3.2 之后的重要变化**：在此之前 metrics 与 tracing 各自为政；3.3 起二者由同一次 Observation 派生出指标与 span，语义一致性更好。前提是 classpath 上有 `micrometer-observation`（`ObservationSupportUtil.isSupportObservation()`，源码注释要求版本 > 1.10.0），且 tracing 需要额外的 `micrometer-tracing`（`isSupportTracing()`）。

## 默认值汇总表

| 项 | 默认值 | 来源 | 备注 |
| :--- | :--- | :--- | :--- |
| 指标总开关 | classpath 有 `MeterRegistry` 即启用 | `MetricsSupportUtil.isSupportMetrics()` | 无 `dubbo.metrics.enable` |
| `dubbo.metrics.protocol` | 有 Prometheus 则 `prometheus`，否则 `default` | `DefaultApplicationDeployer.java:392-398` | 运行时推导 |
| `enableThreadpool` | `true` | `DefaultApplicationDeployer.java:401-402` | 未配置即启用 |
| `enableMetricsInit` | `true` | `DefaultApplicationDeployer.java:403-404` | 未配置即启用 |
| `rpcLevel` | `METHOD` | `MetricsConfig.java:113` | 可选 `SERVICE` |
| `prometheus.exporter.metrics.port` | `20888`（**死常量**） | `MetricsConstants.java:74,90` | 无代码使用 |
| `prometheus.exporter.metrics.path` | `/metrics` | `MetricsConstants.java:92` | 未被 HTTP exporter 使用 |
| `prometheus.pushgateway.enabled` | `false` | `MetricsConstants.java:78` / `PrometheusMetricsReporter.java:72` | 默认关闭 |
| `prometheus.pushgateway.push.interval` | `30` 秒 | `MetricsConstants.java:94` | |
| `prometheus.pushgateway.job` | `default_dubbo_job` | `MetricsConstants.java:96` | |
| 指标导出通道 | QoS 命令 `metrics` | `PrometheusMetricsReporterCmd.java:37` | QoS 默认端口 22222 |
| `dubbo.tracing.enabled` | `false` | `TracingConfig.java:34` | 需显式开启 |
| tracer 实现选择 | OTel 优先，其次 Brave | `TracerProviderFactory.java:29-35` | classpath 决定 |
| ObservationRegistry | 复用外部，否则 `ObservationRegistry.create()` | `DubboObservationRegistry.java:57-88` | 外部（如 Spring）优先 |

## 陷阱清单

| 直觉写法 / 印象 | 源码实际 | 后果 |
| :--- | :--- | :--- |
| 「`dubbo.metrics.enable=true` 开启指标」 | 无此总开关，靠 classpath Micrometer 判定 | 配置不生效 |
| 「Prometheus 抓 `:20888/metrics`」 | 20888 是死常量，无 HTTP exporter | 抓不到数据 |
| 「引入 `micrometer-prometheus` 就能出指标」 | `isSupportPrometheus()` 还要 Prometheus client 的 `PushGateway` 等类 | 协议被回退为 `default` |
| 「tracing 默认开启」 | `dubbo.tracing.enabled` 默认 `false` | 没有 span 却不报错 |
| 「自定义 `TracingFilter` 扩展埋点」 | 该类不存在，只有 `ObservationReceiverFilter` / `ObservationSenderFilter` | 编译不过 |
| 「Brave 与 OTel 需要装不同模块」 | 同一模块两个包，classpath 二选一（OTel 优先） | 找错依赖 |
| 「Dubbo 自建 ObservationRegistry」 | 有外部 Bean 时直接复用 | 与 Spring 埋点割裂的预期落空 |
| 「Pushgateway 默认开启」 | 默认 `false` | 以为在推送其实没推 |
| 「tracing 模块在顶层 `dubbo-tracing/`」 | 在 `dubbo-metrics/dubbo-tracing` | 依赖坐标写错 |

## Links

- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)
- [Consumer](/docs/CS/Framework/Dubbo/Consumer.md)
- [Tracing](/docs/CS/Distributed/Tracing/Tracing.md)
- [performance](/docs/CS/OS/Linux/performance.md)
- [Observability](/docs/CS/Framework/Istio/Observability.md)

## References

1. [Apache Dubbo 可观测性官方文档](https://cn.dubbo.apache.org/zh-cn/overview/mannual/java-sdk/reference-manual/observability/)
2. [Micrometer Observation 官方文档](https://docs.micrometer.io/micrometer/reference/observation.html)
3. [dubbo-metrics 源码](https://github.com/apache/dubbo/tree/3.3/dubbo-metrics)
