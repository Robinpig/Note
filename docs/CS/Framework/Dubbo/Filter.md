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


### AccessLogFilter


AccessLogFilter 是一个日志过滤器 记录服务请求日志 虽然默认 @Activate 但需要手动开启日志打印


AccessLogFilter 构造函数

### ExecuteLimiter


### ClassLoaderFilter


切换当前工作线程的类加载器到接口的类加载器 以便和接口的类加载器上下文要求











## Links

- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)