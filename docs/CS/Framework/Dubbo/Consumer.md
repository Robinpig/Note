## Introduction



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







