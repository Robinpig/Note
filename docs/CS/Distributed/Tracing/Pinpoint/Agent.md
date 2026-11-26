## Introduction

本篇聚焦 **Pinpoint 探针（pinpoint-agent）侧** 的实现机理：它如何在不改业务代码的前提下，把一次分布式请求还原成 Span 树，以及 TraceContext 与跨进程传播的真实行为。服务端运行期（Collector 接收、采样、落库）与存储模型见 [Pinpoint Collector 接收与落库](/docs/CS/Distributed/Tracing/Pinpoint/Collector.md) 与 [Pinpoint 存储模型](/docs/CS/Distributed/Tracing/Pinpoint/Storage.md)。代码事实基于 Pinpoint v4.0.1 源码（`pinpoint-4.0.1/`），讲解直接贴真实源码，不标注行号。

## Bytecode Instrumentation

Pinpoint 的「零侵入」完全建立在 **Java 字节码增强** 之上，挂载链路见 [Pinpoint](/docs/CS/Distributed/Tracing/Pinpoint.md) 枢纽页的 *Agent Bootstrap (source)*：

- 挂载方式：JVM 启动参数 `-javaagent:/opt/pinpoint/pinpoint-bootstrap.jar -Dpinpoint.agentId=order-1 -Dpinpoint.applicationName=order-service`，重启生效。
- 底层机制：JVM 启动后 `PinpointBootStrap.premain` → `PinpointStarter` 用隔离的 `PinpointClassLoader` 反射启动 `DefaultAgent`，最终在 `DefaultApplicationContext` 构造器里注册字节码改写器（完整链路见 [Pinpoint](/docs/CS/Distributed/Tracing/Pinpoint.md) 枢纽页 *Agent Bootstrap (source)* 段）。挂载的关键一行在 `agent-module/profiler/.../context/module/DefaultApplicationContext.java`：

```java
        this.classFileTransformer = injector.getInstance(ClassFileTransformer.class);
        this.dynamicTransformTrigger = injector.getInstance(DynamicTransformTrigger.class);

        ClassFileTransformer classFileTransformer = wrap(this.classFileTransformer);
        final JvmVersion version = JvmUtils.getVersion();
        if (version.onOrAfter(JvmVersion.JAVA_9)) {
            // Java 9+ 走 module 适配后挂载
            // ...
            instrumentation.addTransformer(classFileTransformer, true);
        } else {
            instrumentation.addTransformer(classFileTransformer, true);
        }
```

第二个参数 `true` = 允许 retransform。
- 分发与改写：类被加载时，JVM 回调 `DefaultClassFileTransformerDispatcher.transform(...)`（`agent-module/profiler/src/main/java/com/navercorp/pinpoint/profiler/transformer/DefaultClassFileTransformerDispatcher.java`），按类名路由给对应 plugin 注册的 transformer，再由 `BaseClassFileTransformer` 借助 **ASM**（`agent-module/profiler/.../instrument/ASMClass*` 系列）在方法前后插入「前置 / 后置钩子」，捕获耗时、异常、参数与返回值：

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

- 插件体系：每个框架支持是一个 plugin jar，经 Java SPI `ServiceLoader.load(ProfilerPlugin.class, classLoader)` 发现（`agent-module/plugins-loader/src/main/java/com/navercorp/pinpoint/loader/plugins/profiler/ProfilerPluginLoader.java`），由 `ProfilerPlugin.setup(...)` 声明要拦截的类与方法（如 Tomcat、Spring MVC controller、HttpClient.execute、Dubbo、gRPC、JDBC、Kafka、RabbitMQ）。新增埋点只需写插件，不碰业务代码：

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

代价与风险：官方宣称开销为**低个位数百分比（约 3%）**。但字节码增强的固有风险是——一旦 Pinpoint agent 自身出问题，可能连带影响宿主应用；自 v4 起虽 Collector 可收 OTLP，但 **agent 自身不是 OTel SDK**，技术选型后绑定仍较深。

## Trace Context & Lifecycle

一次 trace 的生灭由 `TraceContext` 统一管理（位于 `agent-module/profiler/src/main/java/com/navercorp/pinpoint/profiler/context/DefaultTraceContext.java`），各方法都是对内部 `traceFactory` 的转发：

```java
    @Override
    public Trace disableSampling() {
        // return null; is bug. #93
        return traceFactory.disableSampling();
    }
    // ...
    @Override
    public Trace continueTraceObject(final TraceId traceId) {
        return traceFactory.continueTraceObject(traceId);
    }


    @Override
    public Trace continueTraceObject(Trace trace) {
        return traceFactory.continueTraceObject(trace);
    }

    @Override
    public Trace newTraceObject() {
        return traceFactory.newTraceObject();
    }

    @Override
    public Trace newTraceObject(String urlPath) {
        return traceFactory.newTraceObject(urlPath);
    }

    @InterfaceAudience.LimitedPrivate("vert.x")
    @Override
    public Trace newAsyncTraceObject() {
        return traceFactory.newAsyncTraceObject();
    }
    // ...
    @Override
    public Trace removeTraceObject() {
        return removeTraceObject(true);
    }

    @Override
    public Trace removeTraceObject(boolean closeUnsampledTrace) {
        final Trace trace = traceFactory.removeTraceObject();
        // ...
    }
```

- **入口新建**：`newTraceObject()` / `newTraceObject(String urlPath)` 向 `traceFactory` 申请一条新 trace；异步分支有 `newAsyncTraceObject()`。
- **跨进程续接**：下游收到 `Pinpoint-TraceID` 等头后，`continueTraceObject(TraceId)` / `continueTraceObject(Trace)` 基于入参重建子 trace；`createTraceId(txId, parentSpanId, spanId, flags)` 内部经 `traceIdFactory.continueTraceId(...)` 把头字段解析成子 `TraceId`：

```java
    @Override
    public TraceId createTraceId(final String transactionId, final long parentSpanId, final long spanId, final short flags) {
        Objects.requireNonNull(transactionId, "transactionId");
        // TODO Should handle exception when parsing failed.
        return traceIdFactory.continueTraceId(transactionId, parentSpanId, spanId, flags);
    }
```

- **结束**：请求完成时 `removeTraceObject()` 关闭 trace 并触发异步上报；`disableSampling()` 用于采样丢弃的链路。
- **ID 模型**：`DefaultTraceId`（`agent-module/profiler/.../context/id/DefaultTraceId.java`）持有 `transactionId + transactionUId + spanId + parentSpanId + flags`；子 ID 由 `getNextTraceId()` → `SpanId.nextSpanID(spanId, parentSpanId)` 生成；`parentSpanId == SpanId.NULL` 即根：

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

`transactionId` 的 `agentId^startTime^seq` 串由 `TransactionIdUtils.formatString(...)` 拼出（`commons-profiler/src/main/java/com/navercorp/pinpoint/common/profiler/util/TransactionIdUtils.java`）：

```java
    public static final char TRANSACTION_ID_DELIMITER_CHAR = '^';
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

## Trace Context Propagation

一次跨服务调用的还原过程（以 TomcatA → TomcatB 为例）：

1. 请求到达 **TomcatA**，Pinpoint Agent 签发 TraceId：`TX_ID = TomcatA^TIME^1`，`SpanId = 10`，`ParentSpanId = -1`（根）。
2. 拦截到 `HttpClient.execute()` 时，创建子 TraceId：在原 TX_ID 基础上 `SpanId = 20`、`ParentSpanId = 10`，并把三段 ID 写入 HTTP 头。字段名见枚举 `Header`（`bootstrap-core/src/main/java/com/navercorp/pinpoint/bootstrap/context/Header.java`）：
   - `Pinpoint-TraceID = "TomcatA^TIME^1"`
   - `Pinpoint-SpanID = "20"`
   - `Pinpoint-pSpanID = "10"`
   - `Pinpoint-Sampled` / `Pinpoint-Flags`（采样与标志位）等

   传播头在源码里就是这个枚举：

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
3. **TomcatB** 从请求头读到 TraceID，识别到自己是一个子节点，经 `DefaultTraceContext.continueTraceObject(...)` 沿用同一 TX_ID、`SpanId = 20`、`ParentSpanId = 10`。
4. 请求完成，两端 Agent 各自把 trace 数据异步发给 Collector 落 HBase；UI 按树排序还原调用栈。

注意 SpanId 是**节点内局部序号**，跨进程的父子关系完全靠 `ParentSpanId` 串联——这与 SkyWalking 把「父服务 / 父实例 / 父端点」编码进 `sw8` 头、让后端免 join 直接建拓扑的思路不同，Pinpoint 更依赖 `agentId` 推导服务身份（见 [SkyWalking Agent 机理](/docs/CS/Distributed/Tracing/SkyWalking/Agent.md) 的 `sw8` 对照）。

## Sampling

Agent 侧即支持采样（与 [SkyWalking 的两级采样](/docs/CS/Distributed/Tracing/SkyWalking/Sampling.md) 类似，agent 端先削减量），Collector 端再做二次采样与常量表去重。常量表（如 SQL 模板、API 路径）不随 span 写原文：agent 通过 `DefaultTraceContext.cacheApi(MethodDescriptor)` / `cacheString(String)` 把高基数字符串归一成整数 ID（`apiMetaDataService` / `stringMetaDataService`），span 只带 ID，服务端再落元数据表回查：

```java
    @Override
    public int cacheApi(final MethodDescriptor methodDescriptor) {
        return this.apiMetaDataService.cacheApi(methodDescriptor);
    }

    @Override
    public int cacheString(final String value) {
        return this.stringMetaDataService.cacheString(value);
    }
```

这既压缩了 HBase 行体积，也把「去重」做在了写入之前。

## Links

- [Pinpoint Collector 接收与落库](/docs/CS/Distributed/Tracing/Pinpoint/Collector.md) — gRPC SpanService / OTLP 接收 / HBase 写路径
- [Pinpoint 存储模型](/docs/CS/Distributed/Tracing/Pinpoint/Storage.md) — HBase / Pinot 落库与运维权重
- [SkyWalking Agent 机理](/docs/CS/Distributed/Tracing/SkyWalking/Agent.md) — 同为字节码插桩，对照 EntrySpan 复用与 sw8 传播
- [Pinpoint](/docs/CS/Distributed/Tracing/Pinpoint.md) — 枢纽页：三段式架构、插件体系与四大视图

## References

- Pinpoint Tech Details（Agent / Plugin）：https://pinpoint-apm.github.io/pinpoint/
- DeepWiki — Pinpoint Agent Module：https://deepwiki.com/pinpoint-apm/pinpoint/3-system-architecture
- Pinpoint v4.0.1 源码（tag `v4.0.1`，commit `a7410bb`）：https://github.com/pinpoint-apm/pinpoint/releases/tag/v4.0.1
