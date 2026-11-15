## Introduction

[Pinpoint](https://pinpoint-apm.github.io/pinpoint/) 是由韩国 **NAVER** 开源（Apache 2.0）的**应用性能管理（APM）平台**，受 Google Dapper 论文启发，2011 年前后起步、2015 年左右开源。与 [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md) / [Jaeger](/docs/CS/Distributed/Tracing/Jaeger.md) 这类「纯追踪后端」不同，Pinpoint 从设计上就是 **全栈 APM**——通过 Java 字节码插桩自动捕获调用链、应用拓扑、性能指标与调用栈，无需改动业务代码，与 [SkyWalking](/docs/CS/Distributed/Tracing/SkyWalking.md) 的定位最为接近。

逻辑上分为 **Agent（探针）/ Collector（采集器）/ Web（控制台）** 三段，存储以 **HBase** 为链路主存、**Pinot**（v3.0 起）承载指标与 Inspector 分析。理解 Pinpoint 最关键的一点：它的原生探针说 **Pinpoint 私有协议**，但 **v4.0.1 起 Collector 也内置 OTLP 接收器**（见下方 *OpenTelemetry & OTLP (v4 新增)* 段）——因此「能不能接 OTLP」在新版已不是非黑即白。

> [!NOTE]
> 源码级笔记。代码事实基于 `pinpoint-apm/pinpoint` **v4.0.1**（tag `v4.0.1`，commit `a7410bb`，"4.0.1 release"），浅克隆于本地 `pinpoint-4.0.1/`。下面讲解直接贴真实源码，路径相对仓库根，不再标注行号。

各分册展开：

- [Pinpoint Agent 机理](/docs/CS/Distributed/Tracing/Pinpoint/Agent.md) — 字节码插桩（premain 链路 / ASM·Javassist / 插件体系）、TraceContext 与跨进程传播
- [Pinpoint Collector 接收与落库](/docs/CS/Distributed/Tracing/Pinpoint/Collector.md) — gRPC `SpanService` 接收、OTLP 接收器、元数据常量去重、HBase 写路径
- [Pinpoint 存储模型](/docs/CS/Distributed/Tracing/Pinpoint/Storage.md) — HBase 主存（Trace / AgentInfo / ApplicationIndex 表）、v3.0 的 Pinot + Kafka 指标链路、v4 的 OTLP→HBase 落地

## Architecture

Pinpoint 是经典的 collector-agent 模型：插桩应用通过 gRPC 把遥测数据发往集中式存储与可视化层。组件交互如下：

```
Instrumented JVM (Java Agent: pinpoint-bootstrap.jar)
   │  gRPC :9991-9993  (旧版 Thrift / UDP 异步上报)
   ▼
┌──────────────────────────────────────────────┐
│         Pinpoint Collector (可水平扩展集群)   │
│   sampling · 常量表去重 · 归一化 · 持久化     │
└───────────────────────┬──────────────────────┘
                        │
             ┌──────────┴───────────┐
             ▼                      ▼
        HBase (Trace /          Pinot (Metric /
        元数据, +ZooKeeper)    Inspector, via Kafka)
             ▲
             │  读取
        Pinpoint Web (:8080, React frontend)
```

- **Agent**：以 `-javaagent:pinpoint-bootstrap.jar` 挂载的 Java agent，启动时通过 `java.lang.instrument.Instrumentation` + ASM / Javassist 改写字节码，插件化拦截 Tomcat / Jetty / Spring MVC / HttpClient / Dubbo / gRPC / JDBC / Kafka 等调用。JDK 8+ 兼容，官方宣称资源开销个位数百分比（约 3%）。
- **Collector**：通过 gRPC（默认端口 9991–9993）接收 Spans / Stats / Agent 信息；负责采样、数据归一化、常量表去重与落库；无状态、可水平扩展；ZooKeeper 既供 HBase 也供 collector 发现 agent。
- **Web**：`pinpoint-web`（API 后端）+ `pinpoint-web-frontend`（React 仪表盘）渲染 ServerMap / Scatter / CallStack / Inspector；默认端口 8080。
- **Storage**：HBase 为链路主存；v3.0 起指标与 Inspector 统计改落 **Pinot**（OLAP），经 **Kafka** 流式摄入——这是阅读新版安装文档最容易忽略的变化。

### Agent Bootstrap (source)

挂载链路完全由 Java agent 的 `premain` 驱动，核心类均位于 `agent-module/bootstraps/bootstrap/`。

入口 `agent-module/bootstraps/bootstrap/src/main/java/com/navercorp/pinpoint/bootstrap/PinpointBootStrap.java`：`premain` 先做启动态守卫（`LoadState`，防止 agent 被加载两次），再进入实例方法 `start()`：

```java
public class PinpointBootStrap {

    private static final BootLogger logger = BootLogger.getLogger(PinpointBootStrap.class);

    private static final LoadState STATE = new LoadState();

    public static void premain(String agentArgs, Instrumentation instrumentation) {

        if (DisableOptions.isBootDisabled()) {
            if (logger.isWarnEnabled()) {
                logger.warn("PinPoint is disabled via Env/Property.");
            }
            return;
        }

        final boolean success = STATE.start();
        if (!success) {
            logger.warn("pinpoint-bootstrap already started. skipping agent loading.");
            return;
        }

        PinpointBootStrap bootStrap = new PinpointBootStrap(agentArgs, instrumentation);
        bootStrap.start();

    }
    // ...
    private void start() {
        // ...
        final Map<String, String> agentArgsMap = argsToMap(agentArgs);

        final ClassPathResolver classPathResolver = new AgentDirBaseClassPathResolver(agentPath);

        final AgentDirectory agentDirectory = resolveAgentDir(classPathResolver);
        // ...
        BootDir bootDir = agentDirectory.getBootDir();
        appendToBootstrapClassLoader(instrumentation, bootDir);

        ClassLoader parentClassLoader = getParentClassLoader();
        PinpointStarter bootStrap = new PinpointStarter(instrumentation, parentClassLoader, agentArgsMap, agentDirectory);
        if (!bootStrap.start()) {
            logPinpointAgentLoadFail();
        }
    }
```

`start()` 做了两件铺垫：把 agent 自身 jar 追加到 bootstrap classloader（`appendToBootstrapClassLoader`），再以自定义父加载器构造 `PinpointStarter`。同一包下的 `PinpointStarter.java` 承接真正的启动：用工厂 `PinpointClassLoaderFactory.createClassLoader`（反射调用）建出**隔离的 `PinpointClassLoader`**，经 `AgentBootLoader.boot(option)` 反射实例化真正的 agent（默认 `com.navercorp.pinpoint.profiler.DefaultAgent`），再反射调用其 `start()` 与 `registerStopHandler()`：

```java
    boolean start() {

        try {
            final Properties properties = loadProperties();

            if (DisableOptions.isDisabled(properties::getProperty, DisableOptions.CONFIG)) {
                this.logger.warn("value of disable property is not false, pinpoint.disable=true");
                return false;
            }

            // this is the library list that must be loaded
            URL[] urls = resolveLib(agentDirectory);
            final ClassLoader agentClassLoader = createClassLoader("pinpoint.agent", urls, parentClassLoader, properties);
            // ...

            AgentBootLoader agentBootLoader = new AgentBootLoader(agentType.getClassName(), agentClassLoader);
            logger.info(String.format("pinpoint agent [%s] starting...", agentType));

            final List<Path> pluginJars = agentDirectory.getPlugins();
            AgentOption option = createAgentOption(
                    instrumentation,
                    properties,
                    agentArgs,
                    agentDirectory.getAgentDirPath(),
                    pluginJars,
                    agentDirectory.getBootDir().getJarPath());
            Object agent = agentBootLoader.boot(option);
            Class<?> agentClazz = agent.getClass();
            agentClazz.getMethod("start").invoke(agent);
            agentClazz.getMethod("registerStopHandler").invoke(agent);
            logger.info("pinpoint agent started normally.");
        } catch (Exception e) {
            // unexpected exception that did not be checked above
            logger.warn("pinpoint start failed.", e);
            return false;
        }
        return true;
    }
```

`DefaultAgent.start()`（`agent-module/profiler/src/main/java/com/navercorp/pinpoint/profiler/DefaultAgent.java`）只是切状态并委托 `applicationContext.start()`。**真正的字节码挂钩在 `DefaultApplicationContext` 的构造器里**（`agent-module/profiler/.../context/module/DefaultApplicationContext.java`）：从 Guice injector 拿到 `ClassFileTransformer` 分发器，最终 `instrumentation.addTransformer(classFileTransformer, true)` 完成挂载——第二个参数 `true` 即允许 retransform：

```java
        final Module applicationContextModule = moduleFactory.newModule(agentOption);
        this.injector = Guice.createInjector(Stage.PRODUCTION, applicationContextModule);

        this.profilerConfig = injector.getInstance(ProfilerConfig.class);

        this.instrumentEngine = injector.getInstance(InstrumentEngine.class);

        this.classFileTransformer = injector.getInstance(ClassFileTransformer.class);
        this.dynamicTransformTrigger = injector.getInstance(DynamicTransformTrigger.class);

        ClassFileTransformer classFileTransformer = wrap(this.classFileTransformer);
        final JvmVersion version = JvmUtils.getVersion();
        if (version.onOrAfter(JvmVersion.JAVA_9)) {
            // ...
            instrumentation.addTransformer(classFileTransformer, true);
        } else {
            instrumentation.addTransformer(classFileTransformer, true);
        }
```

> 隔离 classloader + 反射启动的设计，使 agent 的类（包括 Guice、ASM 等）与业务应用完全隔离，互不污染——这是 Pinpoint 与很多「直接往 app classpath 塞 agent 依赖」方案的关键差异。

## Plugin System (source)

插桩能力以 **plugin jar + Java SPI** 方式扩展，新增框架支持不必改 Pinpoint 内核：

- 每个 plugin 在 `META-INF/services/com.navercorp.pinpoint.bootstrap.plugin.ProfilerPlugin` 声明实现类；agent 启动时由 `ProfilerPluginLoader` 经 Java SPI 发现并加载，实现极简（`agent-module/plugins-loader/src/main/java/com/navercorp/pinpoint/loader/plugins/profiler/ProfilerPluginLoader.java`）：

```java
public class ProfilerPluginLoader implements PinpointPluginLoader<ProfilerPlugin> {

    @Override
    public List<ProfilerPlugin> load(ClassLoader classLoader) {
        List<ProfilerPlugin> profilerPlugins = new ArrayList<>();
        ServiceLoader<ProfilerPlugin> serviceLoader = ServiceLoader.load(ProfilerPlugin.class, classLoader);
        for (ProfilerPlugin profilerPlugin : serviceLoader) {
            profilerPlugins.add(profilerPlugin);
        }
        return profilerPlugins;
    }
}
```

- plugin 实现 `ProfilerPlugin.setup(ProfilerPluginSetupContext)`（接口见 `bootstrap-core/.../bootstrap/plugin/ProfilerPlugin.java`），通过 `PluginInstrumentContext` 声明要拦截的类/方法，并绑定 `AroundInterceptor` 等拦截器。
- 类真正被加载时，JVM 回调分发器 `DefaultClassFileTransformerDispatcher.transform(...)`（`agent-module/profiler/src/main/java/com/navercorp/pinpoint/profiler/transformer/DefaultClassFileTransformerDispatcher.java`）：先过滤掉 bootstrap/Pinpoint 自身类与不可修改类，再用 `TransformerRegistry.findTransformer(classLoader, internalName, classFileBuffer)` 按类名路由到对应 plugin 注册的 transformer，最后交给 `BaseClassFileTransformer` 用 ASM 改写（`agent-module/profiler/.../instrument/ASMClass*` 系列）：

```java
    @Override
    public byte[] transform(ClassLoader classLoader, String classInternalName, Class<?> classBeingRedefined, ProtectionDomain protectionDomain, byte[] classFileBuffer) throws IllegalClassFormatException {
        if (!classLoaderFilter.accept(classLoader, classInternalName, classBeingRedefined, protectionDomain, classFileBuffer)) {
            return null;
        }

        final String internalName = lambdaClassFileResolver.resolve(classLoader, classInternalName, protectionDomain, classFileBuffer);
        if (internalName == null) {
            return null;
        }
        if (!pinpointClassFilter.accept(classLoader, internalName, classBeingRedefined, protectionDomain, classFileBuffer)) {
            return null;
        }

        final ClassFileTransformer dynamicTransformer = dynamicTransformerRegistry.getTransformer(classLoader, internalName);
        if (dynamicTransformer != null) {
            return baseClassFileTransformer.transform(classLoader, internalName, classBeingRedefined, protectionDomain, classFileBuffer, dynamicTransformer);
        }

        if (!unmodifiableFilter.accept(classLoader, internalName, classBeingRedefined, protectionDomain, classFileBuffer)) {
            return null;
        }

        final ClassFileTransformer transformer = this.transformerRegistry.findTransformer(classLoader, internalName, classFileBuffer);
        if (transformer == null) {
            return null;
        }

        return baseClassFileTransformer.transform(classLoader, internalName, classBeingRedefined, protectionDomain, classFileBuffer, transformer);
    }
```

社区 plugin 覆盖最全（Tomcat、Jetty、Spring MVC、HttpClient3/4、google-httpclient、Dubbo、gRPC、JDBC、Kafka、RabbitMQ、ActiveMQ 等，均位于 `agent-module/plugins/`）。

## Trace Data Model

Pinpoint 用三段式 ID 还原分布式事务的 Span 树：

- **TransactionId（TX_ID）**：格式 `agentId^startTime^sequence`，由 `TransactionIdUtils.formatString(...)` 拼出，全局唯一标识一次分布式事务（`commons-profiler/src/main/java/com/navercorp/pinpoint/common/profiler/util/TransactionIdUtils.java`）：

```java
public final class TransactionIdUtils {
    // value is displayed as html - should not use html syntax
    public static final char TRANSACTION_ID_DELIMITER_CHAR = '^';
    public static final String TRANSACTION_ID_DELIMITER = "" + TRANSACTION_ID_DELIMITER_CHAR;
    public static final int NULL = -1;
    // ...
    public static String formatString(String agentId, long agentStartTime, long transactionSequence) {
        Objects.requireNonNull(agentId, "agentId");

        return agentId +
                TRANSACTION_ID_DELIMITER_CHAR +
                agentStartTime +
                TRANSACTION_ID_DELIMITER_CHAR +
                transactionSequence;
    }
```

- **SpanId / ParentSpanId**：`DefaultTraceId` 持有 `transactionId + transactionUId + spanId + parentSpanId + flags`；子节点 ID 由 `getNextTraceId()` → `SpanId.nextSpanID(spanId, parentSpanId)` 生成；`parentSpanId == SpanId.NULL` 表示根（`agent-module/profiler/.../context/id/DefaultTraceId.java` 与 `bootstrap-core/.../bootstrap/context/SpanId.java`）：

```java
public class DefaultTraceId implements TraceId {

    private final TransactionId transactionId;
    private final TransactionUId transactionUId;

    private final long parentSpanId;
    private final long spanId;
    private final short flags;
    // ...
    public TraceId getNextTraceId() {
        return new DefaultTraceId(transactionId, transactionUId, spanId, SpanId.nextSpanID(spanId, parentSpanId), flags);
    }
    // ...
    public boolean isRoot() {
        return this.parentSpanId == SpanId.NULL;
    }
```

```java
public class SpanId {

    public static final long NULL = -1;
    // ...
    public static long nextSpanID(long spanId, long parentSpanId) {
        final Random seed = getRandom();

        long newId = createSpanId(seed);
        while (newId == spanId || newId == parentSpanId) {
            newId = createSpanId(seed);
        }
        return newId;
    }
}
```
- **SpanEvent**：方法级粒度事件（入口、RPC 调用、DB 访问等），构成 Span 内的瀑布。

跨进程传播通过在 HTTP 头里注入多个字段完成，字段名定义在枚举 `Header`（`bootstrap-core/src/main/java/com/navercorp/pinpoint/bootstrap/context/Header.java`）：

```java
public enum Header {

    HTTP_TRACE_ID("Pinpoint-TraceID"),
    HTTP_SPAN_ID("Pinpoint-SpanID"),
    HTTP_PARENT_SPAN_ID("Pinpoint-pSpanID"),
    HTTP_SAMPLED("Pinpoint-Sampled"),
    HTTP_FLAGS("Pinpoint-Flags"),
    HTTP_PARENT_APPLICATION_NAME("Pinpoint-pAppName"),
    HTTP_PARENT_APPLICATION_TYPE("Pinpoint-pAppType"),
    HTTP_PARENT_APPLICATION_NAMESPACE("Pinpoint-pAppNamespace"),
    HTTP_HOST("Pinpoint-Host"),
    HTTP_PARENT_SERVICE_NAME("Pinpoint-pServiceName");
    // ...
}
```

即 `Pinpoint-TraceID` / `Pinpoint-SpanID` / `Pinpoint-pSpanID` / `Pinpoint-Sampled` / `Pinpoint-Flags` 以及父应用元数据 `Pinpoint-pAppName` / `Pinpoint-pAppType` 等。下游 `DefaultTraceContext.createTraceId(...)` 从请求头还原出子 `TraceId`（`agent-module/profiler/src/main/java/com/navercorp/pinpoint/profiler/context/DefaultTraceContext.java`）：

```java
    @Override
    public int cacheApi(final MethodDescriptor methodDescriptor) {
        return this.apiMetaDataService.cacheApi(methodDescriptor);
    }

    @Override
    public int cacheString(final String value) {
        return this.stringMetaDataService.cacheString(value);
    }

    @Override
    public TraceId createTraceId(final String transactionId, final long parentSpanId, final long spanId, final short flags) {
        Objects.requireNonNull(transactionId, "transactionId");
        // TODO Should handle exception when parsing failed.
        return traceIdFactory.continueTraceId(transactionId, parentSpanId, spanId, flags);
    }
```

与 [SkyWalking](/docs/CS/Distributed/Tracing/SkyWalking/Agent.md) 的 `sw8` 对比：SkyWalking 把父服务 / 父实例 / 父端点 / 目标地址一并编码进传播头，使 OAP 无需额外 join 即可直接还原拓扑；Pinpoint 则靠 `agentId` 推导服务身份，更像「增强版 Dapper」。

## OpenTelemetry & OTLP (v4 新增)

**v4.0.1 起 Pinpoint Collector 已能接收 OTLP**，不再是「纯私有协议」：

- `otlptrace/otlptrace-collector` 模块提供 OTLP trace 接收能力：`OtlpTraceController`（HTTP/JSON 入口，`otlptrace/.../collector/controller/OtlpTraceController.java`）与 gRPC 入口 `GrpcOtlpTraceService`（`.../collector/service/GrpcOtlpTraceService.java`）。
- 接收后的 OTLP span 经 `HbaseOtlpTraceService`（`.../collector/service/HbaseOtlpTraceService.java`）写入 HBase，复用与 Pinpoint 原生 trace 相同的存储模型；另有 `LinkIndexTraceService` 处理链路索引。
- 同理存在 `otlpmetric` / `otlplog` 模块，对应指标与日志的 OTLP 摄入。

因此决策口径应修正为：**Collector 侧可 ingest OTLP**（兼容 OTel SDK / 网关导出），但 **Pinpoint 的原生 Java agent 仍走私有 Pinpoint 协议**（字节码插桩产出 Pinpoint 自有 span 模型，不是 OTel SDK）。这与 [SkyWalking](/docs/CS/Distributed/Tracing/SkyWalking.md)「agent 与 OTLP 双轨」的路线趋同，但 Pinpoint 的 agent 端并未采用 OTel SDK。新项目若已全面采用 OTel SDK 且希望 vendor-neutral，仍优先 [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md) + OTel-native 后端；但若要「仅靠 agent 拿到 New Relic 级调用树 + 又能收 OTLP」，v4 的 Pinpoint 已经够用。

## Observability Views

四个招牌视图（都从 HBase / Pinot 读取后渲染）：

- **ServerMap**：自动发现的服务调用拓扑，箭头带错误率与吞吐。
- **Scatter**：每个请求是一个点，横轴时间、纵轴耗时；框选慢请求即可展开其调用树。
- **CallStack**：单事务的调用树（SpanEvent 瀑布），用于定位「哪个方法慢」。
- **Inspector**：单实例资源与指标下钻（v3 起数据来自 Pinot）。

## Relationship to OpenTelemetry

见上方 *OpenTelemetry & OTLP (v4 新增)* 段：v4.0.1 的 Collector 已内置 OTLP 接收器（gRPC + HTTP/JSON → HBase），但 Pinpoint 原生 agent 仍说私有协议。在「新项目要不要上 Pinpoint」的决策里，若团队已采用 OTel SDK 希望 vendor-neutral 逃生通道，应优先 [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md) + OTel-native 后端；若更看重「零侵入 Java 调用树 + 顺带收 OTLP」，v4 的 Pinpoint 是合理候选。Pinpoint 的适用场景仍是：**大量 Java 服务、希望仅靠 agent 拿到 New Relic 级的调用树、且愿意运维 HBase**。

## Links

- [SkyWalking](/docs/CS/Distributed/Tracing/SkyWalking.md) — 同为全栈 APM，支持 OTel、默认 BanyanDB
- [SkyWalking Agent 机理](/docs/CS/Distributed/Tracing/SkyWalking/Agent.md) — 对照 EntrySpan 复用与 sw8 传播
- [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md) / [Jaeger](/docs/CS/Distributed/Tracing/Jaeger.md) — 纯追踪后端对照
- [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md) — Pinpoint v4 可 ingest OTLP 的对照基准
- [CAT](/docs/CS/Distributed/Tracing/CAT.md) — 同为国产/全栈 APM，但走「全量指标 + 采样链路」路线
- [Pinpoint Collector 接收与落库](/docs/CS/Distributed/Tracing/Pinpoint/Collector.md) — gRPC SpanService / OTLP 接收器 / HBase 写路径

## References

- Pinpoint 官方文档（Tech Details / Architecture）：https://pinpoint-apm.github.io/pinpoint/
- Pinpoint GitHub（v4.0.1 tag）：https://github.com/pinpoint-apm/pinpoint/releases/tag/v4.0.1
- DeepWiki — Pinpoint System Architecture：https://deepwiki.com/pinpoint-apm/pinpoint/3-system-architecture
