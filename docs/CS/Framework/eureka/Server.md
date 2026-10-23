> [!NOTE]
> 源码基于 Netflix/eureka **v1.10.19**（完整索引见 [目录索引](/docs/CS/Framework/eureka/README.md)）。**注意修正一处常见误传**：老版本文档里的 `new DiscoveryClient(applicationInfoManager, eurekaClientConfig, getTransportClientFactories(), getDiscoveryClientOptionalArgs())` 与带 `EurekaServerHttpClientFactory` 的 5 参 `PeerAwareInstanceRegistryImpl` 在 1.10 已不存在，实际只有 2 参/4 参构造。

## Introduction

Eureka Server 有两条启动路径，最终都收敛到同一套组件装配：

| 部署形态                       | 入口                                  | 触发方式                                                |
| :------------------------- | :---------------------------------- | :-------------------------------------------------- |
| 裸 war / Servlet 容器         | `com.netflix.eureka.EurekaBootStrap` | 实现 `ServletContextListener`，容器启动即 `contextInitialized` |
| Spring Cloud（`@EnableEurekaServer`） | `EurekaServerBootstrap` + `EurekaServerInitializerConfiguration` | `SmartLifecycle#start()` 里另起线程调用               |

本页只讲「组件怎么装起来、定时器怎么起」，具体的数据逻辑分散在 [registry](/docs/CS/Framework/eureka/registry.md)、[cache](/docs/CS/Framework/eureka/cache.md)、[self preservation](/docs/CS/Framework/eureka/self_preservation.md)、[replication](/docs/CS/Framework/eureka/replication.md) 四篇。

## EurekaBootStrap

```java
public class EurekaBootStrap implements ServletContextListener {
    @Override
    public void contextInitialized(ServletContextEvent event) {
        try {
            initEurekaEnvironment();
            initEurekaServerContext();
            ServletContext sc = event.getServletContext();
            sc.setAttribute(EurekaServerContext.class.getName(), serverContext);
        } catch (Throwable e) {
            logger.error("Cannot bootstrap eureka server :", e);
            throw new RuntimeException("Cannot bootstrap eureka server :", e);
        }
    }
}
```

`initEurekaEnvironment()` 做的是 Archaius 的 deployment context 设置，用 double check 的写法把 datacenter / environment 灌进配置实例（缺省落到 `default` / `test`）。

核心在第二步：

```java
protected void initEurekaServerContext() throws Exception {
    EurekaServerConfig eurekaServerConfig = new DefaultEurekaServerConfig();

    // 向后兼容：V1 形状的实例信息转换器
    JsonXStream.getInstance().registerConverter(new V1AwareInstanceInfoConverter(), XStream.PRIORITY_VERY_HIGH);
    XmlXStream.getInstance().registerConverter(new V1AwareInstanceInfoConverter(), XStream.PRIORITY_VERY_HIGH);

    ServerCodecs serverCodecs = new DefaultServerCodecs(eurekaServerConfig);

    ApplicationInfoManager applicationInfoManager = null;
    // Server 自身也是一个 Eureka Client —— 这是 syncUp() 与 peer 发现的前提
    if (eurekaClient == null) {
        EurekaInstanceConfig instanceConfig = isCloud(ConfigurationManager.getDeploymentContext())
                ? new CloudInstanceConfig()
                : new MyDataCenterInstanceConfig();
        applicationInfoManager = new ApplicationInfoManager(
                instanceConfig, new EurekaConfigBasedInstanceInfoProvider(instanceConfig).get());
        EurekaClientConfig eurekaClientConfig = new DefaultEurekaClientConfig();
        eurekaClient = new DiscoveryClient(applicationInfoManager, eurekaClientConfig);
    } else {
        applicationInfoManager = eurekaClient.getApplicationInfoManager();
    }

    PeerAwareInstanceRegistry registry;
    if (isAws(applicationInfoManager.getInfo())) {
        registry = new AwsInstanceRegistry(eurekaServerConfig, eurekaClient.getEurekaClientConfig(), serverCodecs, eurekaClient);
        awsBinder = new AwsBinderDelegate(...);
        awsBinder.start();
    } else {
        registry = new PeerAwareInstanceRegistryImpl(eurekaServerConfig, eurekaClient.getEurekaClientConfig(), serverCodecs, eurekaClient);
    }

    PeerEurekaNodes peerEurekaNodes = getPeerEurekaNodes(registry, eurekaServerConfig, eurekaClient.getEurekaClientConfig(), serverCodecs, applicationInfoManager);
    serverContext = new DefaultEurekaServerContext(eurekaServerConfig, serverCodecs, registry, peerEurekaNodes, applicationInfoManager);

    EurekaServerContextHolder.initialize(serverContext);
    serverContext.initialize();

    // 从邻居节点搬运注册信息
    int registryCount = registry.syncUp();
    registry.openForTraffic(applicationInfoManager, registryCount);

    EurekaMonitors.registerAllStats();
}
```

两个易忽略的点：

1. **Server 里嵌了一个 `DiscoveryClient`**。它不是装饰器而是刚需：`syncUp()` 要用它去邻居节点拉全量注册表；AWS 场景下 EIP 绑定也依赖它的 `ApplicationInfoManager`。
2. `serverContext.initialize()` 必须在 `syncUp()` **之前**，因为前者把 `PeerEurekaNodes` 与各种 Timer 起起来，后者才谈得上搬数据。

### DefaultEurekaServerContext.initialize

```java
@Singleton
public class DefaultEurekaServerContext implements EurekaServerContext {
    @PostConstruct
    @Override
    public void initialize() {
        peerEurekaNodes.start();
        try {
            registry.init(peerEurekaNodes);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }
}
```

`peerEurekaNodes.start()` 先解析一次 peer URL，然后起名为 `Eureka-PeerNodesUpdater` 的守护线程，按 `peerEurekaNodesUpdateIntervalMs`（**10 分钟**）周期性刷新，节点可以热插拔。

`registry.init()` 做四件事：

```java
@Override
public void init(PeerEurekaNodes peerEurekaNodes) throws Exception {
    this.numberOfReplicationsLastMin.start();
    this.peerEurekaNodes = peerEurekaNodes;
    initializedResponseCache();
    scheduleRenewalThresholdUpdateTask();
    initRemoteRegionRegistry();
}
```

即：复制速率统计开始、初始化[响应缓存](/docs/CS/Framework/eureka/cache.md)、启动 15 分钟的阈值更新任务、初始化 remote region 拉取器。

## EurekaServerBootstrap

Spring Cloud 版本不再读 Archaius 配置文件（`initEurekaEnvironment` 那套被 Spring `Environment` 取代），组件由 IoC 注入，但后面几步完全一致：

```java
public class EurekaServerBootstrap {
    public void contextInitialized(ServletContext context) {
        try {
            initEurekaServerContext();
            context.setAttribute(EurekaServerContext.class.getName(), this.serverContext);
        } catch (Throwable e) {
            log.error("Cannot bootstrap eureka server :", e);
            throw new RuntimeException("Cannot bootstrap eureka server :", e);
        }
    }

    protected void initEurekaServerContext() throws Exception {
        JsonXStream.getInstance().registerConverter(new V1AwareInstanceInfoConverter(), XStream.PRIORITY_VERY_HIGH);
        XmlXStream.getInstance().registerConverter(new V1AwareInstanceInfoConverter(), XStream.PRIORITY_VERY_HIGH);

        if (isAws(this.applicationInfoManager.getInfo())) {
            this.awsBinder = new AwsBinderDelegate(this.eurekaServerConfig, this.eurekaClientConfig, this.registry, this.applicationInfoManager);
            this.awsBinder.start();
        }

        EurekaServerContextHolder.initialize(this.serverContext);

        int registryCount = this.registry.syncUp();
        this.registry.openForTraffic(this.applicationInfoManager, registryCount);

        EurekaMonitors.registerAllStats();
    }
}
```

触发方是 `EurekaServerInitializerConfiguration`（`SmartLifecycle`，phase 0、order 1），它 `start()` 时起新线程避免阻塞 Spring 容器刷新线程，完成后发布 `EurekaRegistryAvailableEvent` 与 `EurekaServerStartedEvent`。更多 Spring 侧装配细节见 [Spring Cloud](/docs/CS/Framework/eureka/spring_cloud.md)。

## syncUp and openForTraffic

```java
@Override
public int syncUp() {
    int count = 0;
    for (int i = 0; ((i < serverConfig.getRegistrySyncRetries()) && (count == 0)); i++) {
        if (i > 0) {
            try {
                Thread.sleep(serverConfig.getRegistrySyncRetryWaitMs());
            } catch (InterruptedException e) {
                logger.warn("Interrupted during registry transfer..");
                break;
            }
        }
        Applications apps = eurekaClient.getApplications();
        for (Application app : apps.getRegisteredApplications()) {
            for (InstanceInfo instance : app.getInstances()) {
                try {
                    if (isRegisterable(instance)) {
                        register(instance, instance.getLeaseInfo().getDurationInSecs(), true);
                        count++;
                    }
                } catch (Throwable t) {
                    logger.error("During DS init copy", t);
                }
            }
        }
    }
    return count;
}
```

`syncUp()` 是**空集群冷启动时的数据搬运**：它借用内嵌客户端已有的注册表缓存，向邻居逐个拉全量并以 `isReplication=true` 写本地（因此不会再转发给 peer）。注意 Spring Cloud 侧 `registry-sync-retries` 默认是 **0**，即只试一次。

随后 `openForTraffic(applicationInfoManager, count)`：把 `expectedNumberOfClientsSendingRenews` 设为 count → 重算阈值 → 记录 `startupTime` → AWS 场景下预热 replica 连接 → 把自身状态置为 `UP`（这一点很关键：Server 未 UP 时 `StatusFilter` 会对所有请求返回 307）→ 调用 `super.postInit()`。

`postInit()` 里起的就是剔除定时器：

```java
protected void postInit() {
    renewsLastMin.start();
    if (evictionTaskRef.get() != null) {
        evictionTaskRef.get().cancel();
    }
    evictionTaskRef.set(new EvictionTask());
    evictionTimer.schedule(evictionTaskRef.get(),
            serverConfig.getEvictionIntervalTimerInMs(),
            serverConfig.getEvictionIntervalTimerInMs());
}
```

MeasuredRate 的统计方式：

```java
public class MeasuredRate {
    private final AtomicLong lastBucket = new AtomicLong(0);
    private final AtomicLong currentBucket = new AtomicLong(0);

    public synchronized void start() {
        if (!isActive) {
            timer.schedule(new TimerTask() {
                @Override
                public void run() {
                    try {
                        // Zero out the current bucket.
                        lastBucket.set(currentBucket.getAndSet(0));
                    } catch (Throwable e) {
                        logger.error("Cannot reset the Measured Rate", e);
                    }
                }
            }, sampleInterval, sampleInterval);
            isActive = true;
        }
    }
}
```

## Timer Summary

| 定时器（线程名）                       | 周期    | 作用                                     | 配置项                                       |
| :------------------------------- | :---- | :------------------------------------- | :---------------------------------------- |
| `Eureka-EvictionTimer`           | 60 s  | 剔除过期租约                                 | `eviction-interval-timer-in-ms`            |
| `Eureka-DeltaRetentionTimer`     | 30 s  | 清理超过 3 分钟的增量条目                         | `delta-retention-timer-interval-ms`        |
| `Eureka-CacheFillTimer`          | 30 s  | readOnly 缓存回填                          | `response-cache-update-interval-ms`        |
| `Eureka-PeerNodesUpdater`        | 10 min | 刷新 peer 列表                            | `peer-eureka-nodes-update-interval-ms`     |
| renewal threshold（无名 Timer）      | 15 min | 重新评估期望续约数                              | `renewal-threshold-update-interval-ms`     |
| `MeasuredRate`（60s 采样窗口）         | 60 s  | 上一分钟续约计数                               | 固定，`new MeasuredRate(1000 * 60 * 1)`       |

全部是 daemon `Timer` / 单线程池，**任何一个 TimerTask 里出现未捕获异常都会让该定时器整体停摆**——这也是 GC 停顿或 OOM 之后 Server 行为诡异（不再剔除、缓存不刷新）的常见原因之一。

## Links

- [Eureka](/docs/CS/Framework/eureka/Eureka.md)
- [Registry](/docs/CS/Framework/eureka/registry.md)
- [Cache](/docs/CS/Framework/eureka/cache.md)
- [Self Preservation](/docs/CS/Framework/eureka/self_preservation.md)
- [Replication](/docs/CS/Framework/eureka/replication.md)
- [Spring Cloud](/docs/CS/Framework/eureka/spring_cloud.md)

## References

1. [Netflix/eureka · EurekaBootStrap](https://github.com/Netflix/eureka/blob/v1.10.19/eureka-core/src/main/java/com/netflix/eureka/EurekaBootStrap.java)
2. [Netflix/eureka · DefaultEurekaServerContext](https://github.com/Netflix/eureka/blob/v1.10.19/eureka-core/src/main/java/com/netflix/eureka/DefaultEurekaServerContext.java)
