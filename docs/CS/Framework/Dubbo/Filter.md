## Introduction

Filter 是 Dubbo 里最「平」的一个扩展点：协议层 `ProtocolFilterWrapper` 在 `export` / `refer` 时把一组 `Filter` 串成一条链，包在 `Invoker` 外面。它要回答的问题只有一个——**在调用真正发出前后，能插哪些逻辑。**

但关于 Filter 的流传说法，几乎每一条都能写错：

1. **「`Filter` 就是 `javax.servlet` 里的那种过滤器」**——概念像，机制完全不像。Servlet Filter 由容器构造、管理生命周期、决定是否放行下一个 filter；Dubbo 的 `Filter` 是纯 SPI 实现，链的组装由 `DefaultFilterChainBuilder` 完成，且**每个 `Invoker` 实例各持有一条链**（实例级），不是全局一条。
2. **「Dubbo 有个 `FutureFilter` 能把异步调用转成同步」**——3.3.6 的 `dubbo-rpc-api/.../rpc/filter/` 下**没有 `FutureFilter`**，`META-INF/dubbo/internal/org.apache.dubbo.rpc.Filter` 的 18 行里也没有它。它已被移除。
3. **「自定义 Filter 默认排在内置 Filter 之后」**——结论偶然成立，理由是错的。真实规则是**按 `@Activate` 的 `order` 升序排**，与「内置 / 自定义」这个身份无关。内置 Filter 的 `order` 大多是负数（`AdaptiveLoadBalanceFilter` -200000、`EchoFilter` -110000、`ClassLoaderFilter` -30000、`GenericFilter` -20000），而自定义 Filter 不写 `order` 就是 `0`（`Activate.java:93`），所以看起来像是「排在内置之后」。
4. **「`ConsumerContextFilter` 在 `dubbo-rpc-api` 里」**——它在 **`dubbo-cluster`**，包路径 `org.apache.dubbo.rpc.cluster.filter.support`，实现的是 `ClusterFilter` 而不是 `Filter`。

本文版本基线：Apache Dubbo **3.3.6**，所有代码块与扩展名清单均逐文件核对自源码 tag `dubbo-3.3.6`。本篇的 `Filter` 接口、3.x 双链结构图、`ProtocolFilterWrapper` 与 `buildInvokerChain` 四节已按 3.3.6 **逐字核对，与源码完全一致**，未作改动。`ClusterFilter` 侧的完整扩展点全景见 [Consumer](/docs/CS/Framework/Dubbo/Consumer.md?id=consumer-side-extension-point-overview)。

```java
@SPI(scope = ExtensionScope.MODULE)
public interface Filter extends BaseFilter {}
```



Starting from 3.0, Filter on consumer side has been refactored. There are two different kinds of Filters working at different stages of an RPC request. 
1. Filter. Works at the instance level, each Filter is bond to one specific Provider instance(invoker). 
2. ClusterFilter. Newly introduced in 3.0, intercepts request before Loadbalancer picks one specific Filter(Invoker).

Filter Chain in 3.x
```
 *                                          -> Filter -> Invoker
 *
 * Proxy -> ClusterFilter -> ClusterInvoker -> Filter -> Invoker
 *
 *                                          -> Filter -> Invoker
```

Filter Chain in 2.x 

```
*                            Filter -> Invoker
*
* Proxy -> ClusterInvoker -> Filter -> Invoker
*
*                            Filter -> Invoker
```

Filter的总体结构






### Built-in Filter List

3.3.6 的 `dubbo-rpc-api` 注册了 **18 个** Filter 扩展名。这是 SPI 文件的全文：

```properties
# dubbo-rpc/dubbo-rpc-api/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.rpc.Filter
echo=org.apache.dubbo.rpc.filter.EchoFilter
generic=org.apache.dubbo.rpc.filter.GenericFilter
genericimpl=org.apache.dubbo.rpc.filter.GenericImplFilter
token=org.apache.dubbo.rpc.filter.TokenFilter
accesslog=org.apache.dubbo.rpc.filter.AccessLogFilter
classloader=org.apache.dubbo.rpc.filter.ClassLoaderFilter
classloader-callback=org.apache.dubbo.rpc.filter.ClassLoaderCallbackFilter
context=org.apache.dubbo.rpc.filter.ContextFilter
exception=org.apache.dubbo.rpc.filter.ExceptionFilter
executelimit=org.apache.dubbo.rpc.filter.ExecuteLimitFilter
deprecated=org.apache.dubbo.rpc.filter.DeprecatedFilter
compatible=org.apache.dubbo.rpc.filter.CompatibleFilter
timeout=org.apache.dubbo.rpc.filter.TimeoutFilter
tps=org.apache.dubbo.rpc.filter.TpsLimitFilter
profiler-server=org.apache.dubbo.rpc.filter.ProfilerServerFilter
adaptiveLoadBalance=org.apache.dubbo.rpc.filter.AdaptiveLoadBalanceFilter
active-limit=org.apache.dubbo.rpc.filter.ActiveLimitFilter
rpc-exception=org.apache.dubbo.rpc.filter.RpcExceptionFilter
```

`dubbo-cluster` 侧另有一个 `Filter` 实现，注意它注册的扩展名带 `callback-` 前缀：

```properties
# dubbo-cluster/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.rpc.Filter
callback-consumer-context=org.apache.dubbo.rpc.cluster.filter.support.CallbackConsumerContextFilter
```

相对旧版本，3.3.6 **新增**了 5 个：`classloader-callback`、`profiler-server`、`adaptiveLoadBalance`、`active-limit`、`rpc-exception`。

### order Sorting Mechanism

链上 Filter 的先后**只由 `@Activate` 的 `order` 决定**，比较由 `ActivateComparator` 完成。它挂在 `ExtensionLoader` 的实例字段上（`activateComparator`，`ExtensionLoader.java:158`），构造入参是 `ExtensionDirector`（多模块场景下是 `List<ExtensionDirector>`）。

排序分两段，**`before` / `after` 优先于 `order`**：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/support/ActivateComparator.java:111-123
            return a1.order > a2.order ? 1 : -1;
        }

        // In order to avoid the problem of inconsistency between the loading order of two filters
        // in different loading scenarios without specifying the order attribute of the filter,
        // when the order is the same, compare its filterName
        if (a1.order > a2.order) {
            return 1;
        } else if (a1.order == a2.order) {
            return o1.getSimpleName().compareTo(o2.getSimpleName()) > 0 ? 1 : -1;
        } else {
            return -1;
        }
```

完整规则：

1. 先解析双方的 `@Activate`，拿到 `before` / `after` / `order`（`ActivateComparator.java:145-168`）。类上没有 `@Activate` 注解时，`order` 取默认值 `0`。
2. 若任一方声明了 `before` / `after`，先按**扩展名**做定向比较（`:72-110`）：`before` 里含对方扩展名则排前面，`after` 里含对方则排后面；此时**忽略 `order`**。
3. 都没声明 `before` / `after`，或定向比较未得出结论时，按 `order` **升序**（数值小的排前面，`:111` 与 `:117`）。
4. `order` 完全相同，则按**类名 `getSimpleName()` 的字典序**兜底（`:120`）——这是为了避免两个没写 `order` 的 Filter 在不同加载场景下顺序不一致。

`buildInvokerChain` 拿到 `getActivateExtension` 返回的**升序**列表后，是**从后往前**包装的（`for (int i = filters.size() - 1; i >= 0; i--)`），所以最终链上的执行顺序与列表顺序**一致**：列表第一个是最外层。

> [!TIP]
>
> `@Activate` 的 `order` 默认值是 `0`（`Activate.java:93`）。想插到内置 Filter 之前就写比 -30000 更小的负数，想追加到最后就写正数。只写 `group` 不写 `order` 的 Filter 统一按 `0` 参与排序，再按类名字典序排。

### Quick Reference of Built-in Filter order

| Filter | 扩展名 | group | order | 证据 |
|---|---|---|---|---|
| `AdaptiveLoadBalanceFilter` | `adaptiveLoadBalance` | CONSUMER | -200000 | `AdaptiveLoadBalanceFilter.java:48-51` |
| `EchoFilter` | `echo` | PROVIDER | -110000 | `EchoFilter.java:33` |
| `ClassLoaderFilter` | `classloader` | PROVIDER | -30000 | `ClassLoaderFilter.java:34` |
| `GenericFilter` | `generic` | PROVIDER | -20000 | `GenericFilter.java:74` |
| `GenericImplFilter` | `genericimpl` | CONSUMER | 20000 | `GenericImplFilter.java:57` |
| `ContextFilter` | `context` | PROVIDER | `Integer.MIN_VALUE` | `ContextFilter.java:63` |
| `ProfilerServerFilter` | `profiler-server` | PROVIDER | `Integer.MIN_VALUE` | `ProfilerServerFilter.java:45` |
| `ClassLoaderCallbackFilter` | `classloader-callback` | PROVIDER | `Integer.MAX_VALUE` | `ClassLoaderCallbackFilter.java:33` |
| `AccessLogFilter` | `accesslog` | PROVIDER | 未声明（按 0） | `AccessLogFilter.java:72` |
| `ExceptionFilter` | `exception` | PROVIDER | 未声明（按 0） | `ExceptionFilter.java:49` |
| `TimeoutFilter` | `timeout` | PROVIDER | 未声明（按 0） | `TimeoutFilter.java:38` |
| `TokenFilter` | `token` | PROVIDER | 未声明（按 0） | `TokenFilter.java:38` |
| `TpsLimitFilter` | `tps` | PROVIDER | 未声明（按 0） | `TpsLimitFilter.java:40` |
| `ExecuteLimitFilter` | `executelimit` | PROVIDER | 未声明（按 0） | `ExecuteLimitFilter.java:40` |
| `ActiveLimitFilter` | `active-limit` | CONSUMER | 未声明（按 0） | `ActiveLimitFilter.java:45` |
| `DeprecatedFilter` | `deprecated` | CONSUMER | 未声明（按 0） | `DeprecatedFilter.java:42` |
| `RpcExceptionFilter` | `rpc-exception` | CONSUMER | 未声明（按 0） | `RpcExceptionFilter.java:35` |
| `CompatibleFilter` | `compatible` | —— | 无 `@Activate`，标 `@Deprecated` | `CompatibleFilter.java:48-49` |

> [!WARNING]
>
> **`ExecuteLimitFilter` 与 `TpsLimitFilter` 的 `@Activate` 里根本没有 `order` 属性**——只有 `group` + `value`。它们不是 `order = -1`，也不是任何其他数值，就是没写。要控制这两个 Filter 的位置只能靠 `before` / `after`。





服务暴露与引用会使用 Protocol 层 ProtocolFilterWrapper 实现了 FilterChain 的组装


```java
@Activate(order = 100)
public class ProtocolFilterWrapper implements Protocol {

    private final Protocol protocol;

    @Override
    public <T> Exporter<T> export(Invoker<T> invoker) throws RpcException {
        if (UrlUtils.isRegistry(invoker.getUrl())) {
            return protocol.export(invoker);
        }
        FilterChainBuilder builder = getFilterChainBuilder(invoker.getUrl());
        return protocol.export(builder.buildInvokerChain(invoker, SERVICE_FILTER_KEY, CommonConstants.PROVIDER));
    }

    @Override
    public <T> Invoker<T> refer(Class<T> type, URL url) throws RpcException {
        if (UrlUtils.isRegistry(url)) {
            return protocol.refer(type, url);
        }
        FilterChainBuilder builder = getFilterChainBuilder(url);
        return builder.buildInvokerChain(protocol.refer(type, url), REFERENCE_FILTER_KEY, CommonConstants.CONSUMER);
    }

    private <T> FilterChainBuilder getFilterChainBuilder(URL url) {
        return ScopeModelUtil.getExtensionLoader(FilterChainBuilder.class, url.getScopeModel())
                .getDefaultExtension();
    }

}
```

#### buildInvokerChain
```java

@Activate
public class DefaultFilterChainBuilder implements FilterChainBuilder {

    /**
     * build consumer/provider filter chain
     */
    @Override
    public <T> Invoker<T> buildInvokerChain(final Invoker<T> originalInvoker, String key, String group) {
        Invoker<T> last = originalInvoker;
        URL url = originalInvoker.getUrl();
        List<ModuleModel> moduleModels = getModuleModelsFromUrl(url);
        List<Filter> filters;
        if (moduleModels != null && moduleModels.size() == 1) {
            filters = ScopeModelUtil.getExtensionLoader(Filter.class, moduleModels.get(0))
                    .getActivateExtension(url, key, group);
        } else if (moduleModels != null && moduleModels.size() > 1) {
            filters = new ArrayList<>();
            List<ExtensionDirector> directors = new ArrayList<>();
            for (ModuleModel moduleModel : moduleModels) {
                List<Filter> tempFilters = ScopeModelUtil.getExtensionLoader(Filter.class, moduleModel)
                        .getActivateExtension(url, key, group);
                filters.addAll(tempFilters);
                directors.add(moduleModel.getExtensionDirector());
            }
            filters = sortingAndDeduplication(filters, directors);

        } else {
            filters = ScopeModelUtil.getExtensionLoader(Filter.class, null).getActivateExtension(url, key, group);
        }

        if (!CollectionUtils.isEmpty(filters)) {
            for (int i = filters.size() - 1; i >= 0; i--) {
                final Filter filter = filters.get(i);
                final Invoker<T> next = last;
                last = new CopyOfFilterChainNode<>(originalInvoker, next, filter);
            }
            return new CallbackRegistrationInvoker<>(last, filters);
        }

        return last;
    }

}
```




## Filters

内置 Filter 除了 CompatibleFilter 之外 都使用了 @Activate 注解 即默认激活

### AccessLogFilter


AccessLogFilter 是一个日志过滤器 记录服务请求日志 虽然默认 @Activate 但需要手动开启日志打印


AccessLogFilter

```java
@Activate(group = PROVIDER)
public class AccessLogFilter implements Filter {

    private final ConcurrentMap<String, Queue<AccessLogData>> logEntries = new ConcurrentHashMap<>();

    private final AtomicBoolean scheduled = new AtomicBoolean();
    private ScheduledFuture<?> future;
}
```
在第一次调用请求时 通过对 scheduled 的 CAS判断 初始化定时任务到共享线程池中

> 早期版本是直接创建线程池 3.0版本进行global executor service management

> [!WARNING]
>
> 下面这段 `logScheduled` 字段属于**早期版本（3.0 之前）**，**3.3.6 的 `AccessLogFilter` 里没有这个字段**。3.3.6 用 `FrameworkExecutorRepository` 拿共享线程池，不自己建池。紧邻其上的 `logEntries` / `scheduled` / `future` 三个字段则与 3.3.6 逐字一致。

```java
// 早期版本 AccessLogFilter，3.3.6 已不存在此字段
    private final ScheduledExecutorService logScheduled = Executors.newScheduledThreadPool(2, new NamedThreadFactory("Dubbo-Access-Log", true));

```

另外注意 `ACCESS_LOG_KEY` 常量**不在 `AccessLogFilter` 类内**，而在 `org.apache.dubbo.rpc.Constants`：`String ACCESS_LOG_KEY = "accesslog"`（`Constants.java:63`），使用处是 `AccessLogFilter.java:109` 的 `invoker.getUrl().getParameter(Constants.ACCESS_LOG_KEY)`。相关还有 `ACCESS_LOG_FIXED_PATH_KEY = "accesslog.fixed.path"`（`Constants.java:65`）。





### ExecuteLimitFilter

限制服务方法最大并发数


```java
@Activate(group = CommonConstants.PROVIDER, value = EXECUTES_KEY)
public class ExecuteLimitFilter implements Filter, Filter.Listener {

    private static final String EXECUTE_LIMIT_FILTER_START_TIME = "execute_limit_filter_start_time";

    @Override
    public Result invoke(Invoker<?> invoker, Invocation invocation) throws RpcException {
        URL url = invoker.getUrl();
        String methodName = RpcUtils.getMethodName(invocation);
        int max = url.getMethodParameter(methodName, EXECUTES_KEY, 0);
        if (!RpcStatus.beginCount(url, methodName, max)) {
            throw new RpcException(
                    RpcException.LIMIT_EXCEEDED_EXCEPTION,
                    "Failed to invoke method " + RpcUtils.getMethodName(invocation) + " in provider " + url
                            + ", cause: The service using threads greater than <dubbo:service executes=\"" + max
                            + "\" /> limited.");
        }

        invocation.put(EXECUTE_LIMIT_FILTER_START_TIME, System.currentTimeMillis());
        try {
            return invoker.invoke(invocation);
        } catch (Throwable t) {
            if (t instanceof RuntimeException) {
                throw (RuntimeException) t;
            } else {
                throw new RpcException("unexpected exception when ExecuteLimitFilter", t);
            }
        }
    }
}
```

URL statistics.
```java
public class RpcStatus {

    private static final ConcurrentMap<String, RpcStatus> SERVICE_STATISTICS = new ConcurrentHashMap<>();

    private static final ConcurrentMap<String, ConcurrentMap<String, RpcStatus>> METHOD_STATISTICS =
            new ConcurrentHashMap<>();

    private final ConcurrentMap<String, Object> values = new ConcurrentHashMap<>();

    private final AtomicInteger active = new AtomicInteger();
    private final AtomicLong total = new AtomicLong();
    private final AtomicInteger failed = new AtomicInteger();
    private final AtomicLong totalElapsed = new AtomicLong();
    private final AtomicLong failedElapsed = new AtomicLong();
    private final AtomicLong maxElapsed = new AtomicLong();
    private final AtomicLong failedMaxElapsed = new AtomicLong();
    private final AtomicLong succeededMaxElapsed = new AtomicLong();

}
```


### ClassLoaderFilter


切换当前工作线程的类加载器到接口的类加载器 以便和接口的类加载器上下文一起工作
> 这里区分了 ServiceModel

```java
@Activate(group = CommonConstants.PROVIDER, order = -30000)
public class ClassLoaderFilter implements Filter, BaseFilter.Listener {

    @Override
    public Result invoke(Invoker<?> invoker, Invocation invocation) throws RpcException {
        ClassLoader stagedClassLoader = Thread.currentThread().getContextClassLoader();
        ClassLoader effectiveClassLoader;
        if (invocation.getServiceModel() != null) {
            effectiveClassLoader = invocation.getServiceModel().getClassLoader();
        } else {
            effectiveClassLoader = invoker.getClass().getClassLoader();
        }

        if (effectiveClassLoader != null) {
            invocation.put(STAGED_CLASSLOADER_KEY, stagedClassLoader);
            invocation.put(WORKING_CLASSLOADER_KEY, effectiveClassLoader);

            Thread.currentThread().setContextClassLoader(effectiveClassLoader);
        }
        try {
            return invoker.invoke(invocation);
        } finally {
            Thread.currentThread().setContextClassLoader(stagedClassLoader);
        }
    }
}
```

### ContextFilter

把当前执行线程的 `RpcContext` 填上正在服务的 invoker、invocation、本地端口与远端主机名，是 Provider 端「读上下文」的基础。它同时实现 `Filter.Listener`，在响应返回时清理。

```java
// dubbo-rpc/dubbo-rpc-api/src/main/java/org/apache/dubbo/rpc/filter/ContextFilter.java:63-69
@Activate(group = PROVIDER, order = Integer.MIN_VALUE)
public class ContextFilter implements Filter, Filter.Listener {
    private final Set<PenetrateAttachmentSelector> supportedSelectors;

    public ContextFilter(ApplicationModel applicationModel) {
        ExtensionLoader<PenetrateAttachmentSelector> selectorExtensionLoader =
                applicationModel.getExtensionLoader(PenetrateAttachmentSelector.class);
        supportedSelectors = selectorExtensionLoader.getSupportedExtensionInstances();
    }
```

`order = Integer.MIN_VALUE` 是**有意的**：`ContextFilter` 要在链的最外层先把 `RpcContext` 建好，后面所有 Filter 才能读到上下文。它的构造器接 `ApplicationModel`，说明它需要读应用级扩展。

### ExceptionFilter

只挂在 Provider 端（`group = PROVIDER`，无 `order`），干两件事：把「接口签名里没声明的受检异常」以 ERROR 级别记到服务端日志；以及**把不属于 API 包的异常包成 `RuntimeException` 再抛给客户端**——框架只序列化外层异常并把 cause 转成字符串，避免客户端因反序列化失败而拿到一个完全无法解析的异常对象。

```java
// dubbo-rpc/dubbo-rpc-api/src/main/java/org/apache/dubbo/rpc/filter/ExceptionFilter.java:49
@Activate(group = CommonConstants.PROVIDER)
public class ExceptionFilter implements Filter, Filter.Listener {
```

包装时有三条**豁免**（`ExceptionFilter.java:93-110`）：接口与异常在同一个 jar 里则直接抛；异常类名以 `java.` / `javax.` / `jakarta.` 开头则直接抛；异常本身是 `RpcException` 则直接抛。只有「跨 jar 的自定义异常」才会被包成 `RuntimeException`。

### TimeoutFilter

**名字骗人：它在 3.3.6 只告警，不中断。** 类注释写得很直白：`Log any invocation timeout, but don't stop server from running`。

```java
// dubbo-rpc/dubbo-rpc-api/src/main/java/org/apache/dubbo/rpc/filter/TimeoutFilter.java:38-64
@Activate(group = CommonConstants.PROVIDER)
public class TimeoutFilter implements Filter, Filter.Listener {

    @Override
    public Result invoke(Invoker<?> invoker, Invocation invocation) throws RpcException {
        return invoker.invoke(invocation);
    }

    @Override
    public void onResponse(Result appResponse, Invoker<?> invoker, Invocation invocation) {
        Object obj = RpcContext.getServerAttachment().getObjectAttachment(TIME_COUNTDOWN_KEY);
        if (obj != null) {
            TimeoutCountDown countDown = (TimeoutCountDown) obj;
            if (countDown.isExpired()) {
                if (logger.isWarnEnabled()) {
                    logger.warn(PROXY_TIMEOUT_REQUEST, "", "",
                        "invoke timed out. method: " + RpcUtils.getMethodName(invocation) + " url is "
                                + invoker.getUrl() + ", invoke elapsed " + countDown.elapsedMillis() + " ms.");
                }
            }
        }
    }
```

`invoke` 直接透传，超时判定全在 `onResponse` 里靠 `TIME_COUNTDOWN_KEY` 附件完成，且**只打日志**。`onError` 是空实现。真正的超时判定与失败构造在客户端侧的 `DefaultFuture.TimeoutCheckTask`，见 [Consumer](/docs/CS/Framework/Dubbo/Consumer.md?id=timeout)。

### TokenFilter

Provider 端的服务令牌校验。比对的是 Provider URL 上配置的 `token` 与消费端 attachment 里带上来的 `remoteToken`，不一致直接抛 `RpcException`。注意它**只实现 `Filter`、不实现 `Listener`**——校验失败当场抛，没有「事后补救」这一步。

```java
// dubbo-rpc/dubbo-rpc-api/src/main/java/org/apache/dubbo/rpc/filter/TokenFilter.java:38-49
@Activate(group = CommonConstants.PROVIDER, value = TOKEN_KEY)
public class TokenFilter implements Filter {

    @Override
    public Result invoke(Invoker<?> invoker, Invocation inv) throws RpcException {
        String token = invoker.getUrl().getParameter(TOKEN_KEY);
        if (ConfigUtils.isNotEmpty(token)) {
            Class<?> serviceType = invoker.getInterface();
            String remoteToken = (String) inv.getObjectAttachmentWithoutConvert(TOKEN_KEY);
            if (!token.equals(remoteToken)) {
                throw new RpcException("Invalid token! Forbid invoke remote service " + serviceType + " method "
                        + RpcUtils.getMethodName(inv) + "() from consumer "
                        + RpcContext.getServiceContext().getRemoteHost() + " to provider "
```

用 `getObjectAttachmentWithoutConvert` 取值而非 `getAttachment`，避免字符串被框架转换后比对失真。

### TpsLimitFilter

Provider 端的**QPS 限流**。与 `ExecuteLimitFilter` 的「并发数」不同，它限的是**调用频次**：URL 上配 `tps`（默认 -1，即不限流）、可选配 `tps.interval` 作为统计窗口。限流器是 `DefaultTPSLimiter`。

```java
// dubbo-rpc/dubbo-rpc-api/src/main/java/org/apache/dubbo/rpc/filter/TpsLimitFilter.java:40-49
@Activate(group = CommonConstants.PROVIDER, value = TPS_LIMIT_RATE_KEY)
public class TpsLimitFilter implements Filter {

    private final TPSLimiter tpsLimiter = new DefaultTPSLimiter();

    @Override
    public Result invoke(Invoker<?> invoker, Invocation invocation) throws RpcException {
        if (!tpsLimiter.isAllowable(invoker.getUrl(), invocation)) {
            return AsyncRpcResult.newDefaultAsyncResult(
                    new RpcException(
```

超限时**不抛异常**，而是把异常包进 `AsyncRpcResult` 作为正常返回路径交回去（`:46-49`）。它也只实现 `Filter`，不实现 `Listener`。

> [!WARNING]
>
> `TpsLimitFilter` 与 `ExecuteLimitFilter` 的 `@Activate` **都没有 `order` 属性**——只有 `group` 与 `value`。想调它们在链上的位置只能靠 `before` / `after`。

### ActiveLimitFilter


```java
@Activate(group = CONSUMER, value = ACTIVES_KEY)
public class ActiveLimitFilter implements Filter, Filter.Listener {

    private static final String ACTIVE_LIMIT_FILTER_START_TIME = "active_limit_filter_start_time";

    @Override
    public Result invoke(Invoker<?> invoker, Invocation invocation) throws RpcException {
        URL url = invoker.getUrl();
        String methodName = RpcUtils.getMethodName(invocation);
        int max = invoker.getUrl().getMethodParameter(methodName, ACTIVES_KEY, 0);
        final RpcStatus rpcStatus = RpcStatus.getStatus(invoker.getUrl(), RpcUtils.getMethodName(invocation));
        if (!RpcStatus.beginCount(url, methodName, max)) {
            long timeout = invoker.getUrl().getMethodParameter(RpcUtils.getMethodName(invocation), TIMEOUT_KEY, 0);
            long start = System.currentTimeMillis();
            long remain = timeout;
            synchronized (rpcStatus) {
                while (!RpcStatus.beginCount(url, methodName, max)) {
                    try {
                        rpcStatus.wait(remain);
                    } catch (InterruptedException e) {
                        // ignore
                    }
                    long elapsed = System.currentTimeMillis() - start;
                    remain = timeout - elapsed;
                    if (remain <= 0) {
                        throw new RpcException(
                                RpcException.LIMIT_EXCEEDED_EXCEPTION,
                                "Waiting concurrent invoke timeout in client-side for service:  "
                                        + invoker.getInterface().getName()
                                        + ", method: " + RpcUtils.getMethodName(invocation) + ", elapsed: "
                                        + elapsed + ", timeout: " + timeout + ". concurrent invokes: "
                                        + rpcStatus.getActive()
                                        + ". max concurrent invoke limit: " + max);
                    }
                }
            }
        }

        invocation.put(ACTIVE_LIMIT_FILTER_START_TIME, System.currentTimeMillis());

        return invoker.invoke(invocation);
    }
}
```



### ConsumerContextFilter

**它不在 `dubbo-rpc-api`，而在 `dubbo-cluster`**，包路径 `org.apache.dubbo.rpc.cluster.filter.support`。更重要的是：**它实现的是 `ClusterFilter` 而不是 `Filter`**，所以压根不出现在上面那 18 个 `rpc.Filter` 扩展名里。

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/filter/support/ConsumerContextFilter.java:52
@Activate(group = CONSUMER, order = Integer.MIN_VALUE)
```

扩展名 `consumercontext`，注册在 `META-INF/dubbo/internal/org.apache.dubbo.rpc.cluster.filter.ClusterFilter`。它与 Provider 端的 `ContextFilter` 是一对：消费端选址**前**（`ClusterFilter` 阶段）把消费侧上下文写进 `RpcContext`，供日志与埋点使用。`order = Integer.MIN_VALUE` 同样是让它站在链的最外层。



### FutureFilter

> [!WARNING]
>
> **`FutureFilter` 在 3.3.6 中不存在，已被移除。** `dubbo-rpc-api/.../rpc/filter/` 下的 19 个类里没有它，18 个 `rpc.Filter` 扩展名里也没有 `future`。如果你在老文档或老代码里见到它，那是 2.x 的东西。

需要「异步转同步」语义时，3.3.6 的正规做法是直接用 `AsyncRpcResult` + `CompletableFuture`，而不是依赖这个已被移除的 Filter。








## Custom Filter

自定义 Filter **不存在「默认在内置之后」这条规则**，真实规则只有一条：**按 `@Activate` 的 `order` 升序排**（见 [order 排序机制](#order-排序机制)）。

之所以看起来像「在内置之后」，是个巧合：内置 Filter 的 `order` 大多是负数，而自定义 Filter 不写 `order` 就是默认 `0`（`Activate.java:93`），`0 > -30000`，排在后面。但只要你在自定义 Filter 上写 `@Activate(group = CONSUMER, order = -100000)`，它就会插到 `EchoFilter`（-110000）与 `ClassLoaderFilter`（-30000）之间——与它是不是自定义的毫无关系。

要可靠地控制位置，两种手段：

| 手段 | 写法 | 生效条件 |
|---|---|---|
| 指定序号 | `@Activate(group = CONSUMER, order = -100000)` | 双方都没写 `before` / `after` 时生效 |
| 定向插队 | `@Activate(group = CONSUMER, before = "classloader")` | **优先于 `order`**，直接按扩展名比较 |

`before` / `after` 里的名字是**扩展名**（SPI 文件的 key，如 `classloader`、`context`），不是类名。

> [!TIP]
>
> 消费者侧要拦截选址**之前**的逻辑（如统一参数转换、入口日志），应该实现 `ClusterFilter` 而不是 `Filter`。原因是消费端 `Filter` 的实例数量级等于服务端地址量级，每个 `Invoker` 各持一条链；而 `ClusterFilter` 每个集群一份。完整扩展点全景见 [Consumer](/docs/CS/Framework/Dubbo/Consumer.md?id=consumer-side-extension-point-overview)。

## Pitfall List

> [!WARNING]
>
> 这一节的每一条都对应一个「按旧文档写就会出错」的具体后果。

1. **`FutureFilter` 不存在**。3.3.6 已移除，写代码依赖它会编译失败。
2. **`ConsumerContextFilter` 在 `dubbo-cluster`，且是 `ClusterFilter`**。在 `dubbo-rpc-api` 的 `rpc/filter/` 下找它会找不到；把它当成普通 `Filter` 理解也会错。
3. **`TimeoutFilter` 只告警不中断**。它的 `invoke` 是直接透传（`TimeoutFilter.java:44-46`），超时失败由客户端 `DefaultFuture.TimeoutCheckTask` 判定并构造。看到 `timeout` 这个扩展名就以为「服务端会掐断超时请求」，会误判 Provider 侧行为。
4. **`ExecuteLimitFilter` / `TpsLimitFilter` 没有 `order` 属性**。不是 `order = -1`，是没写。按 `-1` 去推理它们的位置会算错。
5. **`AccessLogFilter` 的 `logScheduled` 字段在 3.3.6 已不存在**。3.3.6 走 `FrameworkExecutorRepository` 共享线程池。而且 `ACCESS_LOG_KEY` 常量在 `org.apache.dubbo.rpc.Constants` 里，不在 `AccessLogFilter` 类内。
6. **`CompatibleFilter` 是唯一没有 `@Activate` 的内置 Filter**，且已标 `@Deprecated`。扩展名 `compatible` 仍在 SPI 文件里，但不会被默认激活。
7. **`Filter` 的 SPI 默认作用域是 `MODULE`**（`@SPI(scope = ExtensionScope.MODULE)`，`Filter.java:68`），不是 `APPLICATION`。一个 `ModuleModel` 只能看到本模块内的 `Filter` 实现。
8. **`AccessLogFilter` 虽标了 `@Activate`，但日志默认不打印**，需要显式配 `accesslog` 才输出。
9. **`ExceptionFilter` 会改变异常类型**：跨 jar 的自定义异常会被包成 `RuntimeException` 抛回客户端，客户端 catch 原始异常类型会失败。JDK 异常、`RpcException`、与接口同 jar 的异常则原样抛。




## Links

- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)
- [Governance](/docs/CS/Framework/Dubbo/Governance.md)
- [Invocation](/docs/CS/Framework/Dubbo/Invocation.md)
- [Consumer](/docs/CS/Framework/Dubbo/Consumer.md)
- [Auth](/docs/CS/Framework/Dubbo/Auth.md)

## References

1. [Apache Dubbo 3.3.6 源码（tag dubbo-3.3.6）](https://github.com/apache/dubbo/tree/dubbo-3.3.6)
2. [dubbo-rpc-api filter 包源码](https://github.com/apache/dubbo/tree/dubbo-3.3.6/dubbo-rpc/dubbo-rpc-api/src/main/java/org/apache/dubbo/rpc/filter)
3. [ActivateComparator 源码](https://github.com/apache/dubbo/blob/dubbo-3.3.6/dubbo-common/src/main/java/org/apache/dubbo/common/extension/support/ActivateComparator.java)
4. [Dubbo 过滤器官方文档](https://cn.dubbo.apache.org/zh-cn/overview/core-features/filter/)
5. [Dubbo SPI 扩展点开发指南](https://cn.dubbo.apache.org/zh-cn/overview/mannual/java-sdk/reference-manual/architecture/dubbo-spi/)
