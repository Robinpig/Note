## Introduction

Dubbo 发起远程调用的时候，主要工作流程可以分为消费端和服务端两个部分。

Dubbo 在服务调用链路中提供了丰富的扩展点，覆盖了负载均衡方式、选址前后的拦截器、服务端处理拦截器等



消费端的工作流程如下：

- 通过 Stub 接收来自用户的请求，并且封装在 `Invocation` 对象中
- 将 `Invocation` 对象传递给 `ClusterFilter`（**扩展点**）做选址前的请求预处理，如请求参数的转换、请求日志记录、限流等操作都是在此阶段进行的
- 将 `Invocation` 对象传递给 `Cluster`（**扩展点**）进行集群调用逻辑的决策，如快速失败模式、安全失败模式等决策都是在此阶段进行的

- - `Cluster` 调用 `Directory` 获取所有可用的服务端地址信息
  - `Directory` 调用 `StateRouter`（**扩展点**，推荐使用） 和 `Router`（**扩展点**） 对服务端的地址信息进行路由筛选，此阶段主要是从全量的地址信息中筛选出本次调用允许调用到的目标，如基于打标的流量路由就是在此阶段进行的
  - `Cluster` 获得从 `Directory` 提供的可用服务端信息后，会调用 `LoadBalance` （**扩展点**）从多个地址中选择出一个本次调用的目标，如随机调用、轮询调用、一致性哈希等策略都是在此阶段进行的
  - `Cluster` 获得目标的 `Invoker` 以后将 `Invocation` 传递给对应的 `Invoker`，并等待返回结果，如果出现报错则执行对应的决策（如快速失败、安全失败等）

- 经过上面的处理，得到了带有目标地址信息的 `Invoker`，会再调用 `Filter`（**扩展点**）进行选址后的请求处理（由于在消费端侧创建的 `Filter` 数量级和服务端地址量级一致，如无特殊需要建议使用 `ClusterFilter`进行扩展拦截，以提高性能）
- 最后 `Invocation` 会被通过网络发送给服务端



服务端的工作流程如下：

- 服务端通信层收到请求以后，会将请求传递给协议层构建出 `Invocation`
- 将 `Invocation` 对象传递给 `Filter` （**扩展点**）做服务端请求的预处理，如服务端鉴权、日志记录、限流等操作都是在此阶段进行的
- 将 `Invocation` 对象传递给动态代理做真实的服务端调用





消费者创建的第一步就是先进行消费者信息的配置对应类型为ReferenceConfig


DefaultModuleDeployer的referServices


```java
private void referServices() {
    configManager.getReferences().forEach(rc -> {
        try {
            ReferenceConfig<?> referenceConfig = (ReferenceConfig<?>) rc;
            if (!referenceConfig.isRefreshed()) {
                referenceConfig.refresh();
            }

            if (rc.shouldInit()) {
                if (referAsync || rc.shouldReferAsync()) {
                    ExecutorService executor = executorRepository.getServiceReferExecutor();
                    CompletableFuture<Void> future = CompletableFuture.runAsync(
                            () -> {
                                try {
                                    referenceCache.get(rc, false);
                                } catch (Throwable t) {
                                    logger.error(
                                            CONFIG_FAILED_EXPORT_SERVICE,
                                            "",
                                            "",
                                            "Failed to async export service config: " + getIdentifier()
                                                    + " , catch error : " + t.getMessage(),
                                            t);
                                }
                            },
                            executor);

                    asyncReferringFutures.add(future);
                } else {
                    referenceCache.get(rc, false);
                }
            }
        } catch (Throwable t) {
            logger.error(
                    CONFIG_FAILED_REFERENCE_MODEL,
                    "",
                    "",
                    "Model reference failed: " + getIdentifier() + " , catch error : " + t.getMessage(),
                    t);
            referenceCache.destroy(rc);
            throw t;
        }
    });
}
```

SimpleReferenceCache是一个用于缓存引用ReferenceConfigBase的util工具类
ReferenceConfigBase是一个重对象，对于频繁创建ReferenceConfigBase的框架来说，有必要缓存这些对象。 如果需要使用复杂的策略，可以实现并使用自己的ReferenceConfigBase缓存 这个Cache是引用服务的开始如果我们想在代码中自定义一些服务引用的逻辑，可以直接创建SimpleReferenceCache类型对象然后调用其get方法进行引用服务
在获取服务对象之外包装了一层缓存。如果出现了异常则执行referenceCache的destroy方法进行销毁引用配置



```java
public <T> T get(String key) {
    List<ReferenceConfigBase<?>> referenceConfigBases = referenceKeyMap.get(key);
    if (CollectionUtils.isNotEmpty(referenceConfigBases)) {
        return (T) referenceConfigBases.get(0).get();
    }
    return null;
}
```

```java
public <T> T get(ReferenceConfigBase<T> rc, boolean check) {
    String key = generator.generateKey(rc);
    Class<?> type = rc.getInterfaceClass();

    boolean singleton = rc.getSingleton() == null || rc.getSingleton();
    T proxy = null;
    // Check existing proxy of the same 'key' and 'type' first.
    if (singleton) {
        proxy = get(key, (Class<T>) type);
    } else {
        logger.warn(
                CONFIG_API_WRONG_USE,
                "",
                "",
                "Using non-singleton ReferenceConfig and ReferenceCache at the same time may cause memory leak. "
                        + "Call ReferenceConfig#get() directly for non-singleton ReferenceConfig instead of using ReferenceCache#get(ReferenceConfig)");
    }

    if (proxy == null) {
        List<ReferenceConfigBase<?>> referencesOfType = ConcurrentHashMapUtils.computeIfAbsent(
                referenceTypeMap, type, _t -> Collections.synchronizedList(new ArrayList<>()));
        referencesOfType.add(rc);
        List<ReferenceConfigBase<?>> referenceConfigList = ConcurrentHashMapUtils.computeIfAbsent(
                referenceKeyMap, key, _k -> Collections.synchronizedList(new ArrayList<>()));
        referenceConfigList.add(rc);
        proxy = rc.get(check);
    }

    return proxy;
}
```



使用了享元模式（其实就是先查缓存，缓存不存在则创建对象存入缓存）来进行引用对象的管理这样一个过程，这里一共有两个缓存对象referencesOfType和referenceConfigList key分别为引用类型和引用的服务的key，值是引用服务的基础配置对象列表List<ReferenceConfigBase>



```java
@Override
@Transient
public T get(boolean check) {
    if (destroyed) {
        throw new IllegalStateException("The invoker of ReferenceConfig(" + url + ") has already destroyed!");
    }

    if (ref == null) {
        if (getScopeModel().isLifeCycleManagedExternally()) {
            // prepare model for reference
            getScopeModel().getDeployer().prepare();
        } else {
            // ensure start module, compatible with old api usage
            getScopeModel().getDeployer().start();
        }

        init(check);
    }

    return ref;
}
```



```java
protected synchronized void init(boolean check) {
    if (initialized && ref != null) {
        return;
    }
    try {
        if (!this.isRefreshed()) {
            this.refresh();
        }
        // auto detect proxy type
        String proxyType = getProxy();
        if (StringUtils.isBlank(proxyType) && DubboStub.class.isAssignableFrom(interfaceClass)) {
            setProxy(CommonConstants.NATIVE_STUB);
        }

        // init serviceMetadata
        initServiceMetadata(consumer);

        serviceMetadata.setServiceType(getServiceInterfaceClass());
        // TODO, uncomment this line once service key is unified
        serviceMetadata.generateServiceKey();

        Map<String, String> referenceParameters = appendConfig();

        ModuleServiceRepository repository = getScopeModel().getServiceRepository();
        ServiceDescriptor serviceDescriptor;
        if (CommonConstants.NATIVE_STUB.equals(getProxy())) {
            serviceDescriptor = StubSuppliers.getServiceDescriptor(interfaceName);
            repository.registerService(serviceDescriptor);
            setInterface(serviceDescriptor.getInterfaceName());
        } else {
            serviceDescriptor = repository.registerService(interfaceClass);
        }
        consumerModel = new ConsumerModel(
                serviceMetadata.getServiceKey(),
                proxy,
                serviceDescriptor,
                getScopeModel(),
                serviceMetadata,
                createAsyncMethodInfo(),
                interfaceClassLoader);

        // Compatible with dependencies on ServiceModel#getReferenceConfig() , and will be removed in a future
        // version.
        consumerModel.setConfig(this);

        repository.registerConsumer(consumerModel);

        serviceMetadata.getAttachments().putAll(referenceParameters);

        ref = createProxy(referenceParameters);

        serviceMetadata.setTarget(ref);
        serviceMetadata.addAttribute(PROXY_CLASS_REF, ref);

        consumerModel.setDestroyRunner(getDestroyRunner());
        consumerModel.setProxyObject(ref);
        consumerModel.initMethodModels();

        if (check) {
            checkInvokerAvailable(0);
        }
    } catch (Throwable t) {
        logAndCleanup(t);

        throw t;
    }
    initialized = true;
}
```
createProxy

```java
private T createProxy(Map<String, String> referenceParameters) {
    urls.clear();

    meshModeHandleUrl(referenceParameters);

    if (StringUtils.isNotEmpty(url)) {
        // user specified URL, could be peer-to-peer address, or register center's address.
        parseUrl(referenceParameters);
    } else {
        // if protocols not in jvm checkRegistry
        aggregateUrlFromRegistry(referenceParameters);
    }
    createInvoker();

    if (logger.isInfoEnabled()) {
        logger.info("Referred dubbo service: [" + referenceParameters.get(INTERFACE_KEY) + "]."
                    + (ProtocolUtils.isGeneric(referenceParameters.get(GENERIC_KEY))
                       ? " it's GenericService reference"
                       : " it's not GenericService reference"));
    }

    URL consumerUrl = new ServiceConfigURL(
        CONSUMER_PROTOCOL,
        referenceParameters.get(REGISTER_IP_KEY),
        0,
        referenceParameters.get(INTERFACE_KEY),
        referenceParameters);
    consumerUrl = consumerUrl.setScopeModel(getScopeModel());
    consumerUrl = consumerUrl.setServiceModel(consumerModel);
    MetadataUtils.publishServiceDefinition(consumerUrl, consumerModel.getServiceModel(), getApplicationModel());

    // create service proxy
    return (T) proxyFactory.getProxy(invoker, ProtocolUtils.isGeneric(generic));
}
```

```java
private void createInvoker() {
    if (urls.size() == 1) {
        URL curUrl = urls.get(0);
        invoker = protocolSPI.refer(interfaceClass, curUrl);
        // registry url, mesh-enable and unloadClusterRelated is true, not need Cluster.
        if (!UrlUtils.isRegistry(curUrl) && !curUrl.getParameter(UNLOAD_CLUSTER_RELATED, false)) {
            List<Invoker<?>> invokers = new ArrayList<>();
            invokers.add(invoker);
            invoker = Cluster.getCluster(getScopeModel(), Cluster.DEFAULT)
                    .join(new StaticDirectory(curUrl, invokers), true);
        }
    } else {
        List<Invoker<?>> invokers = new ArrayList<>();
        URL registryUrl = null;
        for (URL url : urls) {
            // For multi-registry scenarios, it is not checked whether each referInvoker is available.
            // Because this invoker may become available later.
            invokers.add(protocolSPI.refer(interfaceClass, url));

            if (UrlUtils.isRegistry(url)) {
                // use last registry url
                registryUrl = url;
            }
        }

        if (registryUrl != null) {
            // registry url is available
            // for multi-subscription scenario, use 'zone-aware' policy by default
            String cluster = registryUrl.getParameter(CLUSTER_KEY, ZoneAwareCluster.NAME);
            // The invoker wrap sequence would be: ZoneAwareClusterInvoker(StaticDirectory) ->
            // FailoverClusterInvoker
            // (RegistryDirectory, routing happens here) -> Invoker
            invoker = Cluster.getCluster(registryUrl.getScopeModel(), cluster, false)
                    .join(new StaticDirectory(registryUrl, invokers), false);
        } else {
            // not a registry url, must be direct invoke.
            if (CollectionUtils.isEmpty(invokers)) {
                throw new IllegalArgumentException("invokers == null");
            }
            URL curUrl = invokers.get(0).getUrl();
            String cluster = curUrl.getParameter(CLUSTER_KEY, Cluster.DEFAULT);
            invoker =
                    Cluster.getCluster(getScopeModel(), cluster).join(new StaticDirectory(curUrl, invokers), true);
        }
    }
}
```


```java
protected <T> Invoker<T> interceptInvoker(ClusterInvoker<T> invoker, URL url, URL consumerUrl) {
    List<RegistryProtocolListener> listeners = findRegistryProtocolListeners(url);
    if (CollectionUtils.isEmpty(listeners)) {
        return invoker;
    }

    for (RegistryProtocolListener listener : listeners) {
        listener.onRefer(this, invoker, consumerUrl, url);
    }
    return invoker;
}
```


MigrationRuleHandler

```java
@Activate
public class MigrationRuleListener implements RegistryProtocolListener, ConfigurationListener {
    @Override
    public void onRefer(
        RegistryProtocol registryProtocol, ClusterInvoker<?> invoker, URL consumerUrl, URL registryURL) {
        MigrationRuleHandler<?> migrationRuleHandler =
        ConcurrentHashMapUtils.computeIfAbsent(handlers, (MigrationInvoker<?>) invoker, _key -> {
            ((MigrationInvoker<?>) invoker).setMigrationRuleListener(this);
            return new MigrationRuleHandler<>((MigrationInvoker<?>) invoker, consumerUrl);
        });

        migrationRuleHandler.doMigrate(rule);
    }
}
```
这个代码做了判断的逻辑分别对应了Dubbo3消费者迁移的一个状态逻辑： 三种状态分别如下枚举类型： 当前共存在三种状态，
- FORCE_INTERFACE（强制接口级）
- APPLICATION_FIRST（应用级优先）
- FORCE_APPLICATION（强制应用级）

我们可以看到默认情况下都会走APPLICATION_FIRST（应用级优先）的策略

```java
public synchronized void doMigrate(MigrationRule rule) {
    if (migrationInvoker instanceof ServiceDiscoveryMigrationInvoker) {
        refreshInvoker(MigrationStep.FORCE_APPLICATION, 1.0f, rule);
        return;
    }

    // initial step : APPLICATION_FIRST
    MigrationStep step = MigrationStep.APPLICATION_FIRST;
    float threshold = -1f;

    try {
        step = rule.getStep(consumerURL);
        threshold = rule.getThreshold(consumerURL);
    } catch (Exception e) {
        logger.error(
                REGISTRY_NO_PARAMETERS_URL, "", "", "Failed to get step and threshold info from rule: " + rule, e);
    }

    if (refreshInvoker(step, threshold, rule)) {
        // refresh success, update rule
        setMigrationRule(rule);
    }
}
```


```java
private boolean refreshInvoker(MigrationStep step, Float threshold, MigrationRule newRule) {
    if (step == null || threshold == null) {
        throw new IllegalStateException("Step or threshold of migration rule cannot be null");
    }
    MigrationStep originStep = currentStep;

    if ((currentStep == null || currentStep != step) || !currentThreshold.equals(threshold)) {
        boolean success = true;
        switch (step) {
            case APPLICATION_FIRST:
                migrationInvoker.migrateToApplicationFirstInvoker(newRule);
                break;
            case FORCE_APPLICATION:
                success = migrationInvoker.migrateToForceApplicationInvoker(newRule);
                break;
            case FORCE_INTERFACE:
            default:
                success = migrationInvoker.migrateToForceInterfaceInvoker(newRule);
        }

        if (success) {
            setCurrentStepAndThreshold(step, threshold);
            logger.info(
                    "Succeed Migrated to " + step + " mode. Service Name: " + consumerURL.getDisplayServiceKey());
            report(step, originStep, "true");
        } else {
            // migrate failed, do not save new step and rule
            logger.warn(
                    INTERNAL_ERROR,
                    "unknown error in registry module",
                    "",
                    "Migrate to " + step + " mode failed. Probably not satisfy the threshold you set " + threshold
                            + ". Please try re-publish configuration if you still after check.");
            report(step, originStep, "false");
        }

        return success;
    }
    // ignore if step is same with previous, will continue override rule for MigrationInvoker
    return true;
}
```



```java
@Override
public void migrateToApplicationFirstInvoker(MigrationRule newRule) {
    CountDownLatch latch = new CountDownLatch(0);
    refreshInterfaceInvoker(latch);
    refreshServiceDiscoveryInvoker(latch);

    // directly calculate preferred invoker, will not wait until address notify
    // calculation will re-occurred when address notify later
    calcPreferredInvoker(newRule);
}
```






```java
protected void refreshInterfaceInvoker(CountDownLatch latch) {
    clearListener(invoker);
    if (needRefresh(invoker)) {
        if (logger.isDebugEnabled()) {
            logger.debug("Re-subscribing interface addresses for interface " + type.getName());
        }

        if (invoker != null) {
            invoker.destroy();
        }
        invoker = registryProtocol.getInvoker(cluster, registry, type, url);
    }
    setListener(invoker, () -> {
        latch.countDown();
        if (reportService.hasReporter()) {
            reportService.reportConsumptionStatus(reportService.createConsumptionReport(
                    consumerUrl.getServiceInterface(),
                    consumerUrl.getVersion(),
                    consumerUrl.getGroup(),
                    "interface"));
        }
        if (step == APPLICATION_FIRST) {
            calcPreferredInvoker(rule);
        }
    });
}
```

```java
protected void refreshServiceDiscoveryInvoker(CountDownLatch latch) {
    clearListener(serviceDiscoveryInvoker);
    if (needRefresh(serviceDiscoveryInvoker)) {
        if (logger.isDebugEnabled()) {
            logger.debug("Re-subscribing instance addresses, current interface " + type.getName());
        }

        if (serviceDiscoveryInvoker != null) {
            serviceDiscoveryInvoker.destroy();
        }
        serviceDiscoveryInvoker = registryProtocol.getServiceDiscoveryInvoker(cluster, registry, type, url);
    }
    setListener(serviceDiscoveryInvoker, () -> {
        latch.countDown();
        if (reportService.hasReporter()) {
            reportService.reportConsumptionStatus(reportService.createConsumptionReport(
                    consumerUrl.getServiceInterface(), consumerUrl.getVersion(), consumerUrl.getGroup(), "app"));
        }
        if (step == APPLICATION_FIRST) {
            calcPreferredInvoker(rule);
        }
    });
}
```



currentAvailableInvoker是后期服务调用使用的Invoker对象


```java
private synchronized void calcPreferredInvoker(MigrationRule migrationRule) {
    if (serviceDiscoveryInvoker == null || invoker == null) {
        return;
    }
    Set<MigrationAddressComparator> detectors = ScopeModelUtil.getApplicationModel(
                    consumerUrl == null ? null : consumerUrl.getScopeModel())
            .getExtensionLoader(MigrationAddressComparator.class)
            .getSupportedExtensionInstances();
    if (CollectionUtils.isNotEmpty(detectors)) {
        // pick preferred invoker
        // the real invoker choice in invocation will be affected by promotion
        if (detectors.stream()
                .allMatch(
                        comparator -> comparator.shouldMigrate(serviceDiscoveryInvoker, invoker, migrationRule))) {
            this.currentAvailableInvoker = serviceDiscoveryInvoker;
        } else {
            this.currentAvailableInvoker = invoker;
        }
    }
}
```



## Filter

拦截器可以实现服务提供方和服务消费方调用过程拦截，Dubbo 本身的大多功能均基于此扩展点实现，每次远程方法执行，该拦截都会被执行，请注意对性能的影响。 
其中在消费端侧，`ClusterFilter` 用于选址前的拦截和 `Filter` 用于选址后的拦截。如无特殊需要使用 `ClusterFilter` 进行扩展拦截，以提高性能

在 Dubbo 3 中，`Filter` 和 `ClusterFilter` 的接口签名被统一抽象到 `BaseFilter` 中，开发者可以分别实现 `Filter` 或 `ClusterFilter` 的接口来实现自己的拦截器。
如果需要拦截返回状态，可以直接实现 `BaseFilter.Listener` 的接口，Dubbo 将自动识别，并进行调用



```java
package org.apache.dubbo.rpc;

public interface BaseFilter {
    
    Result invoke(Invoker<?> invoker, Invocation invocation) throws RpcException;

    interface Listener {

        void onResponse(Result appResponse, Invoker<?> invoker, Invocation invocation);

        void onError(Throwable t, Invoker<?> invoker, Invocation invocation);
    }
}
```

```java
package org.apache.dubbo.rpc;

@SPI(scope = ExtensionScope.MODULE)
public interface Filter extends BaseFilter {
}
```

```java
package org.apache.dubbo.rpc.cluster.filter;

@SPI(scope = ExtensionScope.MODULE)
public interface ClusterFilter extends BaseFilter {
}
```

特别的，如果需要在 Consumer 侧生效 `Filter` 或 `ClusterFilter`，需要增加 `@Activate` 注解，并且需要指定 `group` 的值为 `consumer`。

@Activate(group = CommonConstants.CONSUMER)

如果需要在 Provider 侧生效 `Filter` 或 `ClusterFilter`，需要增加 `@Activate` 注解，并且需要指定 `group` 的值为 `provider`。

@Activate(group = CommonConstants.PROVIDER)



路由选址提供从多个服务提供方中选择**一批**满足条件的目标提供方进行调用的能力。 Dubbo 的路由主要需要实现 3 个接口，分别是负责每次调用筛选的 `route` 方法，负责地址推送后缓存的 `notify` 方法，以及销毁路由的 `stop` 方法。 在 Dubbo 3 中推荐实现 `StateRouter` 接口，能够提供高性能的路由选址方式



```java
package org.apache.dubbo.rpc.cluster.router.state;

public interface StateRouter<T> {

    BitList<Invoker<T>> route(BitList<Invoker<T>> invokers, URL url, Invocation invocation,
                     boolean needToPrintMessage, Holder<RouterSnapshotNode<T>> nodeHolder) throws RpcException;

    void notify(BitList<Invoker<T>> invokers);

    void stop();
}
```



```java
package org.apache.dubbo.rpc.cluster;

public interface Router extends Comparable<Router> {

    @Deprecated
    List<Invoker<T>> route(List<Invoker<T>> invokers, URL url, Invocation invocation) throws RpcException;
    
    <T> RouterResult<Invoker<T>> route(List<Invoker<T>> invokers, URL url, Invocation invocation,
                                                     boolean needToPrintMessage) throws RpcException;

    <T> void notify(List<Invoker<T>> invokers);

    void stop();
}
```

集群规则提供在有多个服务提供方时进行结果聚合、容错等能力

```java
package org.apache.dubbo.rpc.cluster.support;

public abstract class AbstractClusterInvoker<T> implements ClusterInvoker<T> {
    
    protected abstract Result doInvoke(Invocation invocation, List<Invoker<T>> invokers,
                                       LoadBalance loadbalance) throws RpcException;
}
```

负载均衡提供从多个服务提供方中选择**一个**目标提供方进行调用的能力。

```java
package org.apache.dubbo.rpc.cluster;

public interface LoadBalance {
    
    <T> Invoker<T> select(List<Invoker<T>> invokers, URL url, Invocation invocation) throws RpcException;
}
```











## Timeout



```java
public class DefaultFuture extends CompletableFuture<Object> {
    public static DefaultFuture newFuture(Channel channel, Request request, int timeout, ExecutorService executor) {
        final DefaultFuture future = new DefaultFuture(channel, request, timeout);
        future.setExecutor(executor);
        // timeout check
        timeoutCheck(future);
        return future;
    }

    private static void timeoutCheck(DefaultFuture future) {
        TimeoutCheckTask task = new TimeoutCheckTask(future.getId());
        future.timeoutCheckTask = TIME_OUT_TIMER.get().newTimeout(task, future.getTimeout(), TimeUnit.MILLISECONDS);
    }
}
```

TimeoutCheckTask

无论是何种调用，都会经过这个定时器的检测，**超时即调用失败，一次 RPC 调用的失败，必须以客户端收到失败响应为准*

```java
private static class TimeoutCheckTask implements TimerTask {

    private final Long requestID;

    TimeoutCheckTask(Long requestID) {
        this.requestID = requestID;
    }

    @Override
    public void run(Timeout timeout) {
        DefaultFuture future = DefaultFuture.getFuture(requestID);
        if (future == null || future.isDone()) {
            return;
        }

        ExecutorService executor = future.getExecutor();
        if (executor != null && !executor.isShutdown()) {
            executor.execute(() -> notifyTimeout(future));
        } else {
            notifyTimeout(future);
        }
    }

    private void notifyTimeout(DefaultFuture future) {
        // create exception response.
        Response timeoutResponse = new Response(future.getId());
        // set timeout status.
        timeoutResponse.setStatus(future.isSent() ? Response.SERVER_TIMEOUT : Response.CLIENT_TIMEOUT);
        timeoutResponse.setErrorMessage(future.getTimeoutMessage(true));
        // handle response.
        DefaultFuture.received(future.getChannel(), timeoutResponse, true);
    }
}
```

header

```java
final class HeaderExchangeChannel implements ExchangeChannel {
    @Override
    public CompletableFuture<Object> request(Object request, int timeout, ExecutorService executor)
    throws RemotingException {
        if (closed) {
            throw new RemotingException(
                this.getLocalAddress(),
                null,
                "Failed to send request " + request + ", cause: The channel " + this + " is closed!");
        }
        Request req;
        if (request instanceof Request) {
            req = (Request) request;
        } else {
            // create request.
            req = new Request();
            req.setVersion(Version.getProtocolVersion());
            req.setTwoWay(true);
            req.setData(request);
        }
        DefaultFuture future = DefaultFuture.newFuture(channel, req, timeout, executor);
        try {
            channel.send(req);
        } catch (RemotingException e) {
            future.cancel();
            throw e;
        }
        return future;
    }
}
```



heart

```java
public class HeaderExchangeClient implements ExchangeClient {

    private final Client client;
    private final ExchangeChannel channel;

    public static GlobalResourceInitializer<HashedWheelTimer> IDLE_CHECK_TIMER = new GlobalResourceInitializer<>(
        () -> new HashedWheelTimer(
            new NamedThreadFactory("dubbo-client-heartbeat-reconnect", true),
            1,
            TimeUnit.SECONDS,
            TICKS_PER_WHEEL),
        HashedWheelTimer::stop);

    private ReconnectTimerTask reconnectTimerTask;
    private HeartbeatTimerTask heartBeatTimerTask;
    private final int idleTimeout;

    public HeaderExchangeClient(Client client, boolean startTimer) {
        Assert.notNull(client, "Client can't be null");
        this.client = client;
        this.channel = new HeaderExchangeChannel(client);

        if (startTimer) {
            URL url = client.getUrl();
            idleTimeout = getIdleTimeout(url);
            startReconnectTask(url);
            startHeartBeatTask(url);
        } else {
            idleTimeout = 0;
        }
    }
}
```



`HeaderExchangeServer` 服务端同样开起了定时器，服务端的逻辑和客户端几乎一致



```java
public class HeaderExchangeServer implements ExchangeServer {

    protected final ErrorTypeAwareLogger logger = LoggerFactory.getErrorTypeAwareLogger(getClass());

    private final RemotingServer server;

    private final AtomicBoolean closed = new AtomicBoolean(false);

    public static GlobalResourceInitializer<HashedWheelTimer> IDLE_CHECK_TIMER = new GlobalResourceInitializer<>(
        () -> new HashedWheelTimer(
            new NamedThreadFactory("dubbo-server-idleCheck", true), 1, TimeUnit.SECONDS, TICKS_PER_WHEEL),
        HashedWheelTimer::stop);

    private CloseTimerTask closeTimer;

    public HeaderExchangeServer(RemotingServer server) {
        Assert.notNull(server, "server == null");
        this.server = server;
        startIdleCheckTask(getUrl());
    }
}
```

> Dubbo 在早期版本版本中使用的是 schedule 方案，在 2.7.x 中替换成了 HashedWheelTimer。

开启了两个定时器： `HeartbeatTimerTask`，`ReconnectTimerTask`

1. `HeartbeatTimerTask` 主要用于定时发送心跳请求

2. `ReconnectTimerTask` 主要用于心跳失败之后处理重连，断连的逻辑

```java
private void startHeartBeatTask(URL url) {
    if (!client.canHandleIdle()) {
        int heartbeat = getHeartbeat(url);
        long heartbeatTick = calculateLeastDuration(heartbeat);
        heartBeatTimerTask = new HeartbeatTimerTask(
                () -> Collections.singleton(this), IDLE_CHECK_TIMER.get(), heartbeatTick, heartbeat);
    }
}

 private void startReconnectTask(URL url) {
        if (shouldReconnect(url)) {
            long heartbeatTimeoutTick = calculateLeastDuration(idleTimeout);
            reconnectTimerTask = new ReconnectTimerTask(
                    () -> Collections.singleton(this),
                    IDLE_CHECK_TIMER.get(),
                    calculateReconnectDuration(url, heartbeatTimeoutTick),
                    idleTimeout);
        }
    }
```

### HeartbeatTimerTask

```java
public class HeartbeatTimerTask extends AbstractTimerTask {

    private static final ErrorTypeAwareLogger logger = LoggerFactory.getErrorTypeAwareLogger(HeartbeatTimerTask.class);

    private final int heartbeat;

    HeartbeatTimerTask(
        ChannelProvider channelProvider, HashedWheelTimer hashedWheelTimer, Long heartbeatTick, int heartbeat) {
        super(channelProvider, hashedWheelTimer, heartbeatTick);
        this.heartbeat = heartbeat;
    }

    @Override
    protected void doTask(Channel channel) {
        try {
            Long lastRead = lastRead(channel);
            Long lastWrite = lastWrite(channel);
            Long now = now();
            if ((lastRead != null && now - lastRead > heartbeat)
                || (lastWrite != null && now - lastWrite > heartbeat)) {
                Request req = new Request();
                req.setVersion(Version.getProtocolVersion());
                req.setTwoWay(true);
                req.setEvent(HEARTBEAT_EVENT);
                channel.send(req);
                if (logger.isDebugEnabled()) {
                    logger.debug("Send heartbeat to remote channel " + channel.getRemoteAddress()
                                 + ", cause: The channel has no data-transmission exceeds a heartbeat period: "
                                 + heartbeat + "ms");
                }
            }
        } catch (Throwable t) {
            logger.warn(
                TRANSPORT_FAILED_RESPONSE,
                "",
                "",
                "Exception when heartbeat to remote channel " + channel.getRemoteAddress(),
                t);
        }
    }
}
```

**Dubbo 采取的是双向心跳设计**，即服务端会向客户端发送心跳，客户端也会向服务端发送心跳，接收的一方更新 lastRead 字段，发送的一方更新 lastWrite 字段，超过心跳间隙的时间，便发送心跳请求给对端。这里的 lastRead/lastWrite 同样会被同一个通道上的普通调用更新，通过更新这两个字段，实现了只在连接空闲时才会真正发送空闲报文的机制

Dubbo 对于建立的每一个连接，同时在客户端和服务端开启了 2 个定时器，一个用于定时发送心跳，一个用于定时重连、断连，执行的频率均为各自检测周期的 1/3。定时发送心跳的任务负责在连接空闲时，向对端发送心跳包。定时重连、断连的任务负责检测 lastRead 是否在超时周期内仍未被更新，如果判定为超时，客户端处理的逻辑是重连，服务端则采取断连的措施




多注册中心的消费 是将每个注册中心封装成单独的 Invoker 再通过 StaticDirectory 保存所有的 Invoker 最终通过 Cluster 合并成一个 Invoker



## Links

- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)