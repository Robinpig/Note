## Introduction


Dubbo 中的过滤器和 Web应用中的过滤器概念是一样的 提供了在服务调用前后插入自定义逻辑的途径
Filter 提供了 provider 和 consumer 调用过程的拦截



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






Dubbo 内置的 Filter有哪些





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

```java
    private final ScheduledExecutorService logScheduled = Executors.newScheduledThreadPool(2, new NamedThreadFactory("Dubbo-Access-Log", true));

```





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

### ExceptionFilter

### TimeoutFilter


### TokenFilter


### TpsLimitFilter


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



### FutureFilter








## 自定义Filter

自定义的 Filter 默认执行顺序在内置的 Filter 之后




## Links

- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)