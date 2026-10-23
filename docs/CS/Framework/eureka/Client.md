> [!NOTE]
> 源码基于 Netflix/eureka **v1.10.19**（完整索引见 [目录索引](/docs/CS/Framework/eureka/README.md)），主文件为 `eureka-client/src/main/java/com/netflix/discovery/DiscoveryClient.java`。契约侧见 [REST API](/docs/CS/Framework/eureka/rest_api.md)，可靠性装配见 [Transport](/docs/CS/Framework/eureka/transport.md)。

## Introduction

Eureka Client 是一个内嵌到业务进程里的守护线程集合：注册自己、维持心跳、定时拉取注册表、按需重新注册、下线时注销。`EurekaClient` 接口的实现类 `DiscoveryClient` 因此在构造阶段就把线程池和定时任务全部起起来，任何一个环节卡住都会直接影响业务进程的健康。

它承担的六件事：

- 向 Server 注册（`register()`）
- 每 30 秒续约（`HeartbeatThread` → `renew()`）
- 每 30 秒拉取注册表（`CacheRefreshThread` → `refreshRegistry()` → `fetchRegistry()`）
- 本地实例信息变化时重新注册（`InstanceInfoReplicator`）
- 优雅下线时注销（`shutdown()` → `unregister()`）
- 提供本地缓存的查询给上层负载均衡（VIP 索引、zone 过滤、shuffle）

## Construction

构造流程（精简版，保留真实代码骨架）：

```java
@Inject
DiscoveryClient(ApplicationInfoManager applicationInfoManager, EurekaClientConfig config,
                TransportClientFactories transportClientFactories, AbstractDiscoveryClientOptionalArgs args,
                Provider<BackupRegistry> backupRegistryProvider, EndpointRandomizer endpointRandomizer) {
    if (args != null) { /* 健康检查 / 监听器 / preRegistrationHandler */ }

    localRegionApps.set(new Applications());
    fetchRegistryGeneration = new AtomicLong(0);

    // 既不注册也不拉取 —— 纯旁路模式，直接返回
    if (!config.shouldRegisterWithEureka() && !config.shouldFetchRegistry()) {
        scheduler = null; heartbeatExecutor = null; cacheRefreshExecutor = null; eurekaTransport = null;
        DiscoveryManager.getInstance().setDiscoveryClient(this);
        DiscoveryManager.getInstance().setEurekaClientConfig(config);
        initTimestampMs = System.currentTimeMillis();
        return;   // no need to setup up an network tasks and we are done
    }

    try {
        // default size of 2 - 1 each for heartbeat and cacheRefresh
        scheduler = Executors.newScheduledThreadPool(2, ...);   // 线程前缀 DiscoveryClient-%d

        heartbeatExecutor = new ThreadPoolExecutor(1, clientConfig.getHeartbeatExecutorThreadPoolSize(),
                0, TimeUnit.SECONDS, new SynchronousQueue<Runnable>(), ...);   // DiscoveryClient-HeartbeatExecutor-%d

        cacheRefreshExecutor = new ThreadPoolExecutor(1, clientConfig.getCacheRefreshExecutorThreadPoolSize(),
                0, TimeUnit.SECONDS, new SynchronousQueue<Runnable>(), ...);   // DiscoveryClient-CacheRefreshExecutor-%d

        eurekaTransport = new EurekaTransport();
        scheduleServerEndpointTask(eurekaTransport, args);   // 构建解析器 + 装饰器链，见 transport.md
    } catch (Throwable e) {
        throw new RuntimeException("Failed to initialize DiscoveryClient!", e);
    }

    if (clientConfig.shouldFetchRegistry()) {
        boolean primaryFetchRegistryResult = fetchRegistry(false);
        // 失败时退到 backup registry（若配置了 shouldEnforceFetchRegistryAtInit 则直接抛 IllegalStateException）
    }

    if (this.preRegistrationHandler != null) {
        this.preRegistrationHandler.beforeRegistration();
    }
    if (clientConfig.shouldRegisterWithEureka() && clientConfig.shouldEnforceRegistrationAtInit()) {
        if (!register()) {
            throw new IllegalStateException("Registration error at startup. Invalid server response.");
        }
    }

    initScheduledTasks();
    DiscoveryManager.getInstance().setDiscoveryClient(this);
    initTimestampMs = System.currentTimeMillis();
    initRegistrySize = this.getApplications().size();
    registrySize.set(initRegistrySize);
}
```

注意 `SynchronousQueue` 是「直传」队列：线程数达到上限后新任务会被 **拒绝**而不是排队，这就是为什么 `heartbeat-executor-thread-pool-size`（Spring Cloud 默认 2）理论上够用——心跳和拉注册表各自只需要一个并发。

`EurekaTransport` 内部持有两个独立的 client：`registrationClient`（注册/心跳/下线，指向写able endpoint）与 `queryClient`（拉注册表），两者都从同一条 [resolver/decorator 链](/docs/CS/Framework/eureka/transport.md)生成。

## Fetch Registry

```java
private boolean fetchRegistry(boolean forceFullRegistryFetch) {
    try {
        Applications applications = getApplications();
        if (clientConfig.shouldDisableDelta()
                || (clientConfig.getRegistryRefreshSingleVipAddress() != null && !clientConfig.getRegistryRefreshSingleVipAddress().isEmpty())
                || forceFullRegistryFetch
                || (applications == null)
                || (applications.getRegisteredApplications().size() == 0)
                || (applications.getVersion() == -1)) // 老客户端不支持 delta
        {
            getAndStoreFullRegistry();
        } else {
            getAndUpdateDelta(applications);
        }
        applications.setAppsHashCode(applications.getReconcileHashCode());
        logTotalInstances();
    } catch (Throwable e) {
        logger.info(PREFIX + "{} - was unable to refresh its cache! ...", appPathIdentifier,
                clientConfig.getRegistryFetchIntervalSeconds(), e.getMessage());
        return false;
    }
    // Notify about cache refresh before updating the instance remote status
    onCacheRefreshed();
    // Update remote status based on refreshed data held in the cache
    updateInstanceRemoteStatus();
    return true;
}
```

全量拉取会做一件事：**过滤 + 打散**。

```java
private void shuffleAndFilterInstances(Map<String, VipIndexSupport> srcMap, boolean filterUpInstances) {
    Random shuffleRandom = new Random();
    for (Map.Entry<String, VipIndexSupport> entries : srcMap.entrySet()) {
        VipIndexSupport vipIndexSupport = entries.getValue();
        AbstractQueue<InstanceInfo> vipInstances = vipIndexSupport.instances;
        final List<InstanceInfo> filteredInstances;
        if (filterUpInstances) {
            filteredInstances = vipInstances.stream()
                    .filter(ii -> ii.getStatus() == InstanceStatus.UP)
                    .collect(Collectors.toCollection(() -> new ArrayList<>(vipInstances.size())));
        } else {
            filteredInstances = new ArrayList<>(vipInstances);
        }
        Collections.shuffle(filteredInstances, shuffleRandom);
        vipIndexSupport.vipList.set(filteredInstances);
        vipIndexSupport.roundRobinIndex.set(0);
    }
}
```

即：**按 VIP 建索引 → 过滤掉非 `UP` 实例 → 随机打散**。这一步是 Eureka 版「客户端负载均衡」的全部：调用方之后只需在打散后的列表上轮转，天然获得分散效果，不需要服务端参与。

### 增量合并 updateDelta

```java
private void getAndUpdateDelta(Applications applications) throws Throwable {
    long currentUpdateGeneration = fetchRegistryGeneration.get();
    Applications delta = null;
    EurekaHttpResponse<Applications> httpResponse = eurekaTransport.queryClient.getDelta(remoteRegionsRef.get());
    if (httpResponse.getStatusCode() == Status.OK.getStatusCode()) {
        delta = httpResponse.getEntity();
    }

    if (delta == null) {
        getAndStoreFullRegistry();          // 拿不到增量就退化为全量
    } else if (fetchRegistryGeneration.compareAndSet(currentUpdateGeneration, currentUpdateGeneration + 1)) {
        String reconcileHashCode = "";
        if (fetchRegistryUpdateLock.tryLock()) {
            try {
                updateDelta(delta);
                reconcileHashCode = getReconcileHashCode(applications);
            } finally {
                fetchRegistryUpdateLock.unlock();
            }
        } else {
            logger.warn("Cannot acquire update lock, aborting getAndUpdateDelta");
        }
        // There is a diff in number of instances for some reason
        if (!reconcileHashCode.equals(delta.getAppsHashCode()) || clientConfig.shouldLogDeltaDiff()) {
            reconcileAndLogDifference(delta, reconcileHashCode);   // this makes a remoteCall
        }
    } else {
        logger.warn("Not updating application delta as another thread is updating it already");
    }
}
```

`updateDelta(delta)` 根据 `ActionType`（`ADDED` / `MODIFIED` / `DELETED`）增删改本地 Applications；注意 `DELETED` 分支在实例数归零时会把整个 Application 一并移除。

### 增量拉取与 reconcile

由于服务端的增量条目只保留 3 分钟（[registry](/docs/CS/Framework/eureka/registry.md?id=delta-队列)），断网或长时间暂停后必然丢变更。兜底机制是双方的 **`appsHashCode` 摘要比对**：客户端合并后重算本地摘要，与服务端摘要不一致就丢弃本地缓存重新全量拉取，同时用 `reconcileAndLogDifference()` 打出差异明细（排查注册表漂移最有效的日志）。

## initScheduledTasks

```java
private void initScheduledTasks() {
    if (clientConfig.shouldFetchRegistry()) {
        int registryFetchIntervalSeconds = clientConfig.getRegistryFetchIntervalSeconds();
        int expBackOffBound = clientConfig.getCacheRefreshExecutorExponentialBackOffBound();
        cacheRefreshTask = new TimedSupervisorTask("cacheRefresh", scheduler, cacheRefreshExecutor,
                registryFetchIntervalSeconds, TimeUnit.SECONDS, expBackOffBound, new CacheRefreshThread());
        scheduler.schedule(cacheRefreshTask, registryFetchIntervalSeconds, TimeUnit.SECONDS);
    }

    if (clientConfig.shouldRegisterWithEureka()) {
        int renewalIntervalInSecs = instanceInfo.getLeaseInfo().getRenewalIntervalInSecs();
        int expBackOffBound = clientConfig.getHeartbeatExecutorExponentialBackOffBound();
        heartbeatTask = new TimedSupervisorTask("heartbeat", scheduler, heartbeatExecutor,
                renewalIntervalInSecs, TimeUnit.SECONDS, expBackOffBound, new HeartbeatThread());
        scheduler.schedule(heartbeatTask, renewalIntervalInSecs, TimeUnit.SECONDS);

        instanceInfoReplicator = new InstanceInfoReplicator(
                this, instanceInfo, clientConfig.getInstanceInfoReplicationIntervalSeconds(), 2);   // burstSize

        statusChangeListener = new ApplicationInfoManager.StatusChangeListener() {
            @Override
            public String getId() { return "statusChangeListener"; }
            @Override
            public void notify(StatusChangeEvent statusChangeEvent) {
                instanceInfoReplicator.onDemandUpdate();
            }
        };
        if (clientConfig.shouldOnDemandUpdateStatusChange()) {
            applicationInfoManager.registerStatusChangeListener(statusChangeListener);
        }
        instanceInfoReplicator.start(clientConfig.getInitialInstanceInfoReplicationIntervalSeconds());
    }
}
```

`TimedSupervisorTask` 是「带超时守护 + 指数退避」的包装器：

```java
public class TimedSupervisorTask extends TimerTask {
    @Override
    public void run() {
        Future<?> future = null;
        try {
            future = executor.submit(task);
            future.get(timeoutMillis, TimeUnit.MILLISECONDS);   // block until done or timeout
            delay.set(timeoutMillis);      // 成功则复位
            successCounter.increment();
        } catch (TimeoutException e) {
            timeoutCounter.increment();
            long currentDelay = delay.get();
            long newDelay = Math.min(maxDelay, currentDelay * 2);   // 超时翻倍，上限 maxDelay
            delay.compareAndSet(currentDelay, newDelay);
        } catch (RejectedExecutionException e) {
            rejectedCounter.increment();
        } finally {
            if (future != null) { future.cancel(true); }
            if (!scheduler.isShutdown()) {
                scheduler.schedule(this, delay.get(), TimeUnit.MILLISECONDS);
            }
        }
    }
}
```

`maxDelay = timeoutMillis * expBackOffBound`（默认 10 倍）。这个设计让 Server 故障时客户端自动降频，恢复后又立刻回到 30s——**看到日志里心跳间隔翻倍不用担心，那是预期行为**。

## InstanceInfoReplicator

负责「本地实例信息变了就重新注册」这条旁路：健康检查改变了 `InstanceInfo`（如 IP、端口、metadata、health check URL）时，会以 token bucket 限流的方式触发一次 `register()`。

```java
class InstanceInfoReplicator implements Runnable {
    InstanceInfoReplicator(DiscoveryClient discoveryClient, InstanceInfo instanceInfo,
                           int replicationIntervalSeconds, int burstSize) {
        this.scheduler = Executors.newScheduledThreadPool(1, ...);   // DiscoveryClient-InstanceInfoReplicator-%d
        this.rateLimiter = new RateLimiter(TimeUnit.MINUTES);
        this.replicationIntervalSeconds = replicationIntervalSeconds;
        this.burstSize = burstSize;
        this.allowedRatePerMinute = 60 * this.burstSize / this.replicationIntervalSeconds;
    }

    public boolean onDemandUpdate() {
        if (rateLimiter.acquire(burstSize, allowedRatePerMinute)) {
            if (!scheduler.isShutdown()) {
                scheduler.submit(() -> {
                    Future latestPeriodic = scheduledPeriodicRef.get();
                    if (latestPeriodic != null && !latestPeriodic.isDone()) {
                        latestPeriodic.cancel(false);      // 取消即将到期的周期任务，避免重复注册
                    }
                    InstanceInfoReplicator.this.run();
                });
                return true;
            }
        }
        return false;
    }

    public void run() {
        try {
            discoveryClient.refreshInstanceInfo();
            Long dirtyTimestamp = instanceInfo.isDirtyWithTime();
            if (dirtyTimestamp != null) {
                discoveryClient.register();
                instanceInfo.unsetIsDirty(dirtyTimestamp);
            }
        } finally {
            Future next = scheduler.schedule(this, replicationIntervalSeconds, TimeUnit.SECONDS);
            scheduledPeriodicRef.set(next);
        }
    }
}
```

默认 `burstSize = 2`、`replicationIntervalSeconds = 30`，于是 `allowedRatePerMinute = 4`——**每分钟最多 4 次按需重注册**，防止健康检查抖动把注册请求打爆服务端。`RateLimiter` 是基于 token bucket 的实现，单位可为 SECONDS/MINUTES。

## 续约与重注册

```java
boolean renew() {
    EurekaHttpResponse<InstanceInfo> httpResponse;
    try {
        httpResponse = eurekaTransport.registrationClient.sendHeartBeat(
                instanceInfo.getAppName(), instanceInfo.getId(), instanceInfo, null);
        if (httpResponse.getStatusCode() == Status.NOT_FOUND.getStatusCode()) {
            REREGISTER_COUNTER.increment();
            long timestamp = instanceInfo.setIsDirtyWithTime();
            boolean success = register();
            if (success) {
                instanceInfo.unsetIsDirty(timestamp);
            }
            return success;
        }
        return httpResponse.getStatusCode() == Status.OK.getStatusCode();
    } catch (Throwable e) {
        logger.error(PREFIX + "{} - was unable to send heartbeat!", appPathIdentifier, e);
        return false;
    }
}
```

404 在 Eureka 里不是错误而是协议指令：Server 用它表达「我这儿没有你，请重新注册」（见 [REST API](/docs/CS/Framework/eureka/rest_api.md?id=renew-endpoint)），常见于 Server 重启或实例已被剔除的场景。

## Shutdown

```java
public synchronized void shutdown() {
    if (isShutdown.compareAndSet(false, true)) {
        if (statusChangeListener != null && applicationInfoManager != null) {
            applicationInfoManager.unregisterStatusChangeListener(statusChangeListener.getId());
        }
        cancelScheduledTasks();
        if (applicationInfoManager != null
                && clientConfig.shouldRegisterWithEureka()
                && clientConfig.shouldUnregisterOnShutdown()) {
            applicationInfoManager.setInstanceStatus(InstanceStatus.DOWN);
            unregister();                       // DELETE /apps/{appName}/{id}
        }
        if (eurekaTransport != null) {
            eurekaTransport.shutdown();
        }
        heartbeatStalenessMonitor.shutdown();
        registryStalenessMonitor.shutdown();
        Monitors.unregisterObject(this);
    }
}
```

Spring Cloud 侧由 `EurekaAutoServiceRegistration`（`SmartLifecycle`）衔接：容器刷新完成后才把状态置为初始值并通过 `EurekaServiceRegistry#register` 注册 HealthCheck；容器关闭时走上面的 `shutdown()`。**被 `kill -9` 的应用是走不到这里的**——这正是需要 3~5 分钟才能感知它的原因，见 [cache](/docs/CS/Framework/eureka/cache.md?id=感知时延的完整推导)。

## Links

- [Eureka](/docs/CS/Framework/eureka/Eureka.md)
- [Registry](/docs/CS/Framework/eureka/registry.md)
- [REST API](/docs/CS/Framework/eureka/rest_api.md)
- [Transport](/docs/CS/Framework/eureka/transport.md)
- [Config](/docs/CS/Framework/eureka/config.md)
- [Spring Cloud](/docs/CS/Framework/eureka/spring_cloud.md)

## References

1. [Netflix/eureka · DiscoveryClient](https://github.com/Netflix/eureka/blob/v1.10.19/eureka-client/src/main/java/com/netflix/discovery/DiscoveryClient.java)
2. [Netflix/eureka · InstanceInfoReplicator](https://github.com/Netflix/eureka/blob/v1.10.19/eureka-client/src/main/java/com/netflix/discovery/InstanceInfoReplicator.java)
