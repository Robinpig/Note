## Introduction

Dubbo 消费者侧调用链上有一层「框架接口基座」：`Directory` 从注册中心拿到全量 Invoker 并按方法过滤，`RouterChain` 把一组路由规则串成责任链，`Cluster` 把 Directory 合并成一个虚拟 Invoker 并套上容错策略，`LoadBalance` 在过滤后的候选里挑一个，`Configurator` 把 `override://` 规则合并进 URL。这几个接口构成 `dubbo-cluster` 模块的骨架，理解它们等于拿到了读源码的钥匙。

大多数人第一次读 `dubbo-cluster` 会栽在同一个坑里：**路由有两套并行的接口，而且 3.x 的主入口已经改名了**。老资料里 `ConditionRouter` / `TagRouter` / `ScriptRouter` / `ServiceRouter` 是 3.0 之前的类名，3.x 全部改名为 `*StateRouter`，取而代之的是 `@since 3.0` 的 `StateRouter` 接口——它返回 `BitList` 而非 `RouterResult`，还多了 `notify` / `buildSnapshot` / `setNextRouter`。而承载路由链的 `RouterChain` 在 3.x 被彻底重写：它不再持有路由列表，而是持有 **main / backup 两条 `SingleRouterChain`** 做读写锁热切换。旧笔记里那段 `buildChain(URL)` + `private RouterChain(URL)` 的代码，实际对应的是 3.x 新增的内层类 `SingleRouterChain`——这是**分层**不是替代，两者至今共存。

本篇定位是**接口基座**：只讲这些接口的签名、协作关系与实现清单。路由规则语法（条件路由的四种分隔符、标签路由的 force 语义、Mesh 规则）在 [Router](/docs/CS/Framework/Dubbo/Router.md)，负载均衡算法（预热权重、滑动窗口、一致性哈希）在 [LoadBalance](/docs/CS/Framework/Dubbo/LoadBalance.md)，这两篇不重复。

> [!NOTE]
> 版本基线：Apache Dubbo **3.3.6**，本文所有代码块与行号均逐文件核对自源码 tag `dubbo-3.3.6`。

## ClusterInvoker

`ClusterInvoker` 是 RPC 代理在消费者侧最终引用到的 Invoker 类型——代理对象里持有的就是它。它内部持有一个 `Directory`，`Cluster.join()` 返回的就是它。

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/ClusterInvoker.java:34-57
public interface ClusterInvoker<T> extends Invoker<T> {

    URL getRegistryUrl();

    Directory<T> getDirectory();

    boolean isDestroyed();

    default boolean isServiceDiscovery() {
        Directory<T> directory = getDirectory();
        if (directory == null) {
            return false;
        }
        return directory.isServiceDiscovery();
    }

    default boolean hasProxyInvokers() {
        Directory<T> directory = getDirectory();
        if (directory == null) {
            return false;
        }
        return !directory.isEmpty();
    }
}
```

后两个 `default` 方法都是纯委托：`isServiceDiscovery()` 问 Directory 自己是不是应用级发现（`ServiceDiscoveryRegistryDirectory` 返回 true），`hasProxyInvokers()` 就是 `!directory.isEmpty()`。它们的用处是让上层容错策略不必依赖 `Directory` 的具体实现就能判断「当前有没有可用地址」。

> [!TIP]
> `getRegistryUrl()` 与 `getUrl()` 不是一回事：前者是注册中心 URL（`registry://host:port/xxx`），后者是合并后的消费端 URL。`AbstractLoadBalance#getWeight` 在 3.3.6 里会优先取 `ClusterInvoker#getRegistryUrl()` 来读权重相关配置，正是因为这个区分。

## Cluster

`Cluster` 是容错策略的 SPI 入口，默认 `failover`。它的 `join` 把一个 Directory「捏」成虚拟 Invoker。

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/Cluster.java:34-61
@SPI(Cluster.DEFAULT)
public interface Cluster {

    String DEFAULT = "failover";

    @Adaptive
    <T> Invoker<T> join(Directory<T> directory, boolean buildFilterChain) throws RpcException;

    static Cluster getCluster(ScopeModel scopeModel, String name) {
        return getCluster(scopeModel, name, true);
    }

    static Cluster getCluster(ScopeModel scopeModel, String name, boolean wrap) {
        if (StringUtils.isEmpty(name)) {
            name = Cluster.DEFAULT;
        }
        return ScopeModelUtil.getApplicationModel(scopeModel)
                .getExtensionLoader(Cluster.class)
                .getExtension(name, wrap);
    }
}
```

两处 3.x 变化值得单独点出。

第一，`join` 多了 `boolean buildFilterChain` 参数，控制是否在 ClusterInvoker 外层再套一层 Filter 链。`ReferenceConfig#createInvoker` 里三种调用方式各不相同：

| 场景 | 参数 | 出处 |
|---|---|---|
| 单 URL、非注册中心（直连） | `getCluster(scopeModel, Cluster.DEFAULT)` + `join(dir, true)` | `ReferenceConfig.java:677-678` |
| 多注册中心 | `getCluster(registryUrl.getScopeModel(), cluster, false)` + `join(dir, false)` | `ReferenceConfig.java:701-702` |
| 多 URL 直连 | `getCluster(scopeModel, cluster)` + `join(dir, true)` | `ReferenceConfig.java:710-711` |

第二，`getCluster` 的**首参变成了 `ScopeModel`**。3.x 所有扩展加载都挂在 ScopeModel 树上，静态的 `ExtensionLoader.getExtensionLoader(Cluster.class)` 已在 3.3.6 标记 `@Deprecated`（`ExtensionLoader.java:241-244`），内部转发到 `ApplicationModel.defaultModel().getDefaultModule()`——那是个隐式默认值，多应用场景下会拿到错的 ExtensionLoader。

### Built-in Cluster Extension List

`dubbo-cluster/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.rpc.cluster.Cluster` 共 11 行：

```properties
# dubbo-cluster/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.rpc.cluster.Cluster
mock=org.apache.dubbo.rpc.cluster.support.wrapper.MockClusterWrapper
scope=org.apache.dubbo.rpc.cluster.support.wrapper.ScopeClusterWrapper
failover=org.apache.dubbo.rpc.cluster.support.FailoverCluster
failfast=org.apache.dubbo.rpc.cluster.support.FailfastCluster
failsafe=org.apache.dubbo.rpc.cluster.support.FailsafeCluster
failback=org.apache.dubbo.rpc.cluster.support.FailbackCluster
forking=org.apache.dubbo.rpc.cluster.support.ForkingCluster
available=org.apache.dubbo.rpc.cluster.support.AvailableCluster
mergeable=org.apache.dubbo.rpc.cluster.support.MergeableCluster
broadcast=org.apache.dubbo.rpc.cluster.support.BroadcastCluster
zone-aware=org.apache.dubbo.rpc.cluster.support.registry.ZoneAwareCluster
```

`mock` 和 `scope` 是 Wrapper 型扩展，包在真正的 Cluster 外面。`ZoneAwareCluster` 在 3.3.6 已被极简化——`doJoin` 只有一行 `return new ZoneAwareClusterInvoker<>(directory);`（`ZoneAwareCluster.java:29-31`），没有 `@Activate` 也没有自定义 `doInvoke`，真正的区域容错逻辑在 `ZoneAwareClusterInvoker` 里。

> [!WARNING]
> 广为流传的两个 Cluster 扩展在 3.3.6 **不存在**：`FailZoneAwareCluster`（区域容错由 `zone-aware` 承担）与 `HealthCheckCluster`（健康检查由 `active-limit` Filter 承担），全仓库 grep 零匹配。另外扩展列表里**没有 `migration`**——`MigrationInvoker` 是 `MigrationClusterInvoker` 的实现，由 `RegistryProtocol#doRefer` 内部创建（`RegistryProtocol.java:578-594`），不是 Cluster SPI 项。

## Router

`Router` 是 2.7 引入的路由接口，3.3.6 里仍然保留（**接口本身没有标 `@Deprecated`**），但它的三参 `route` 已经标了 `@Deprecated`，主入口是四参重载。

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/Router.java:35-74（节选）
public interface Router extends Comparable<Router> {

    int DEFAULT_PRIORITY = Integer.MAX_VALUE;

    URL getUrl();

    @Deprecated
    default <T> List<Invoker<T>> route(List<Invoker<T>> invokers, URL url, Invocation invocation) throws RpcException {
        return null;
    }

    default <T> RouterResult<Invoker<T>> route(
            List<Invoker<T>> invokers, URL url, Invocation invocation, boolean needToPrintMessage) throws RpcException {
        return new RouterResult<>(route(invokers, url, invocation));
    }
```

四参版本返回 `RouterResult<Invoker<T>>`，比裸 `List` 多两个信息：`isNeedContinueRoute()`（是否继续跑后面的路由）与 `getMessage()`（路由说明，如 `use router branch a`）。`SingleRouterChain` 正是靠 `isNeedContinueRoute()` 实现短路。

尾部成员：`notify(List)`（地址变更通知）、`isRuntime()`、`isForce()`、`getPriority()`、`stop()`（3.x 新增，`RouterChain#destroy` 逐个调它释放路由内部资源）、`compareTo`（按 `priority` 升序，数值小的先跑）。

### RouterFactory and CacheableRouterFactory

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/RouterFactory.java:36-47
@SPI
public interface RouterFactory {

    @Adaptive(CommonConstants.PROTOCOL_KEY)
    Router getRouter(URL url);
}
```

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/CacheableRouterFactory.java:29-38
public abstract class CacheableRouterFactory implements RouterFactory {
    private ConcurrentMap<String, Router> routerMap = new ConcurrentHashMap<>();

    @Override
    public Router getRouter(URL url) {
        return ConcurrentHashMapUtils.computeIfAbsent(routerMap, url.getServiceKey(), k -> createRouter(url));
    }

    protected abstract Router createRouter(URL url);
}
```

`CacheableRouterFactory` 按 `serviceKey` 缓存，保证「每个服务每种 Router 只创建一个实例」——Router 实例内部持有规则状态，规则热更新靠 `notify` 而不是重建实例。

> [!WARNING]
> 3.3.6 的 `META-INF` 目录下**没有 `org.apache.dubbo.rpc.cluster.RouterFactory` 这个 SPI 文件**，`CacheableRouterFactory` 在主源码树里**没有任何子类**。也就是说 legacy `Router` 是一套「接口还在、默认实现已清空」的兼容层：`SingleRouterChain.routers` 运行时通常是空列表，真正干活的全在 `StateRouter` 链上。想自定义路由，3.x 应实现 `StateRouter` 而不是 `Router`。

## StateRouter

`StateRouter` 是 `@since 3.0` 新增的路由接口，也是 3.x 的主入口。它与 legacy `Router` 的差异不只是改名，而是**换了返回类型**：`route` 返回 `BitList<Invoker<T>>`，过滤靠位运算而非重建 List。

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/router/state/StateRouter.java:37-108（节选）
public interface StateRouter<T> {

    URL getUrl();

    BitList<Invoker<T>> route(
            BitList<Invoker<T>> invokers,
            URL url,
            Invocation invocation,
            boolean needToPrintMessage,
            Holder<RouterSnapshotNode<T>> nodeHolder)
            throws RpcException;

    boolean isRuntime();

    boolean isForce();

    void notify(BitList<Invoker<T>> invokers);

    String buildSnapshot();

    default void stop() {
        // do nothing by default
    }

    void setNextRouter(StateRouter<T> nextRouter);
}
```

逐项对照 legacy `Router`，差异集中在五点：

| 维度 | `Router` | `StateRouter` |
|---|---|---|
| 返回类型 | `List<Invoker<T>>` / `RouterResult<Invoker<T>>` | `BitList<Invoker<T>>` |
| 排序依据 | `getPriority()` + `Comparable` | **无 `getPriority`**，顺序由链的组装顺序决定 |
| 链式协作 | 无 | `setNextRouter(StateRouter)` |
| 规则变更感知 | `notify(List)` | `notify(BitList)` |
| 治理可观测 | 无 | `buildSnapshot()` 返回路由快照 |

`Holder<RouterSnapshotNode<T>> nodeHolder` 是给路由快照用的输出参数——框架在 `buildRouterSnapshot` 里传入一个持有根节点的 Holder，每个 StateRouter 被调用时往 Holder 里挂自己的节点，返回时 Holder 又指回父节点，从而把整条链的输入输出织成一棵树。`AbstractStateRouter#route`（`AbstractStateRouter.java:94-150`）已把这套机制封装好，自定义路由继承它实现 `doRoute` 即可。

其中有一处关键语义值得记住：`invokers.and(routeResult)` 做的是**交集**而非替换（见下方 `AbstractStateRouter.java:126-136`）——`doRoute` 可以只返回「新增的」BitList，框架会自动与原始列表取交，路由实现因此只需关注自己要放行的下标。另一处是 `shouldFailFast` 为 true 时结果为空就**不再往下传**，直接终止整条链。

### StateRouterFactory

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/router/state/StateRouterFactory.java:24-35
@SPI
public interface StateRouterFactory {
    /**
     * @since 3.0
     */
    @Adaptive(CommonConstants.PROTOCOL_KEY)
    <T> StateRouter<T> getRouter(Class<T> interfaceClass, URL url);
}
```

比 `RouterFactory` 多一个 `Class<T> interfaceClass` 首参——条件路由要按接口名组织规则 key，工厂必须知道接口。

内置实现注册在 `dubbo-cluster/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.rpc.cluster.router.state.StateRouterFactory`，共 8 项：

```properties
# dubbo-cluster/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.rpc.cluster.router.state.StateRouterFactory
mock=org.apache.dubbo.rpc.cluster.router.mock.MockStateRouterFactory
condition=org.apache.dubbo.rpc.cluster.router.condition.ConditionStateRouterFactory
service=org.apache.dubbo.rpc.cluster.router.condition.config.ServiceStateRouterFactory
app=org.apache.dubbo.rpc.cluster.router.condition.config.AppStateRouterFactory
provider-app=org.apache.dubbo.rpc.cluster.router.condition.config.ProviderAppStateRouterFactory
standard-mesh-rule=org.apache.dubbo.rpc.cluster.router.mesh.route.StandardMeshRuleRouterFactory
script-app=org.apache.dubbo.rpc.cluster.router.script.config.AppScriptRouterFactory
tag=org.apache.dubbo.rpc.cluster.router.tag.TagStateRouterFactory
```

`mock` / `condition` / `tag` 对应老资料里的 `MockRouter` / `ConditionRouter` / `TagRouter`；`script-app` 对应老的 `ScriptRouter`。规则语法见 [Router](/docs/CS/Framework/Dubbo/Router.md?id=registry-of-built-in-routing-implementations)。

### BitList

`BitList` 是 `@since 3.0` 为路由专门造的数据结构（`BitList.java:55`，`extends AbstractList<E> implements Cloneable`）。它的注释里给了个例子：

```
 * originList:  A  B  C  D  E             (5 elements)
 * rootSet:     x  v  x  v  v
 * 0  1  0  1  1             (5 elements)
 * tailList:                   F  G  H    (3 elements)
 * resultList:     B     D  E  F  G  H    (6 elements)
```

三个部分的分工：

- `originList`（`volatile List<E>`）：全量原始列表，引用不变，路由过程中只读。
- `rootSet`（`BitSet`）：哪些下标存活。`clone()` 是位拷贝（`BitSet#clone`），`and` / `or` 是位运算（`:123`、`:131`）。
- `tailList`：地址列表**增长**时新追加的元素。位图无法表达「超出原长度的下标」，所以新元素直接进 `tailList`，`add(E)` 会在 `tailList == null` 时惰性创建它（`:208`）。

常用方法：`emptyList()`（`:178`，全局共享单例）、`and` / `or`、`clone()`（`:556`）、`cloneToArrayList()`（`:546`，转回普通 List 给 legacy Router 用）、`getOriginList()`（`:96`，用于判断「是不是同一份原始列表」）。

> [!TIP]
> `getOriginList()` 不只是调试用。`RouterChain` 判断「这次调用该用 main 链还是 backup 链」靠的就是**比较两个 BitList 的 `originList` 引用是否相同**（`RouterChain.java:110`）；`SingleRouterChain#route` 也用它做一致性校验，不一致直接抛 `IllegalStateException("reject to route, because the invokers has changed.")`（`SingleRouterChain.java:139-146`）。这是双链设计能保证正确性的基础。

## RouterChain

3.3.6 里 `RouterChain` 与 `SingleRouterChain` **共存且分层**：`RouterChain` 是外层容器，只管「用哪条链」；`SingleRouterChain` 是内层实现，管「路由怎么跑」。

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/RouterChain.java:47-56
    private volatile SingleRouterChain<T> mainChain;
    private volatile SingleRouterChain<T> backupChain;
    private volatile SingleRouterChain<T> currentChain;

    @SuppressWarnings({"rawtypes", "unchecked"})
    public static <T> RouterChain<T> buildChain(Class<T> interfaceClass, URL url) {
        SingleRouterChain<T> chain1 = buildSingleChain(interfaceClass, url);
        SingleRouterChain<T> chain2 = buildSingleChain(interfaceClass, url);
        return new RouterChain<>(new SingleRouterChain[] {chain1, chain2});
    }
```

注意 `buildChain` 建的是**两条**独立的链（各自独立加载扩展），不是同一条链的引用。构造器强制校验长度：

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/RouterChain.java:83-90
    public RouterChain(SingleRouterChain<T>[] chains) {
        if (chains.length != 2) {
            throw new IllegalArgumentException("chains' size should be 2.");
        }
        this.mainChain = chains[0];
        this.backupChain = chains[1];
        this.currentChain = this.mainChain;
    }
```

两条链的内容在 `buildSingleChain` 里装配：

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/RouterChain.java:58-81
    public static <T> SingleRouterChain<T> buildSingleChain(Class<T> interfaceClass, URL url) {
        ModuleModel moduleModel = url.getOrDefaultModuleModel();

        List<RouterFactory> extensionFactories =
                moduleModel.getExtensionLoader(RouterFactory.class).getActivateExtension(url, ROUTER_KEY);

        List<Router> routers = extensionFactories.stream()
                .map(factory -> factory.getRouter(url))
                .sorted(Router::compareTo)
                .collect(Collectors.toList());

        List<StateRouter<T>> stateRouters =
                moduleModel.getExtensionLoader(StateRouterFactory.class).getActivateExtension(url, ROUTER_KEY).stream()
                        .map(factory -> factory.getRouter(interfaceClass, url))
                        .collect(Collectors.toList());

        boolean shouldFailFast = Boolean.parseBoolean(
                ConfigurationUtils.getProperty(moduleModel, Constants.SHOULD_FAIL_FAST_KEY, "true"));

        RouterSnapshotSwitcher routerSnapshotSwitcher =
                ScopeModelUtil.getFrameworkModel(moduleModel).getBeanFactory().getBean(RouterSnapshotSwitcher.class);

        return new SingleRouterChain<>(routers, stateRouters, shouldFailFast, routerSnapshotSwitcher);
    }
```

与旧版笔记相比的差异：`buildChain` 多了接口 Class 参数、内部建两条链、构造器从 `private RouterChain(URL)` 变为 `public RouterChain(SingleRouterChain[])` 且强制 2 条；`invokers` 从 `List` 换成 `BitList`；新增 `headStateRouter` 串链、`shouldFailFast` 开关（配置项 `dubbo.router.should-fail-fast`，默认 `true`，见 `Constants.java:138`）、`RouterSnapshotSwitcher`；`route` 已 `@Deprecated`（`:119-122`）。

### Dual-Chain Hot Switching

`setInvokers(BitList, Runnable switchAction)` 是双链机制的核心（`RouterChain.java:128-210`）。地址列表更新时不能直接改正在被使用的链，否则正在执行的调用会读到半更新状态。做法是「切到备用链 → 慢慢更新主链 → 切换引用 → 慢慢更新备用链」：

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/RouterChain.java:128-165（节选）
    public synchronized void setInvokers(BitList<Invoker<T>> invokers, Runnable switchAction) {
        try {
            // Lock to prevent directory continue list
            lock.writeLock().lock();

            // Switch to back up chain. Will update main chain first.
            currentChain = backupChain;
        } finally {
            lock.writeLock().unlock();
        }

        try {
            // Lock main chain to wait all invocation end
            // To wait until no one is using main chain.
            mainChain.getLock().writeLock().lock();

            // refresh
            mainChain.setInvokers(invokers);
        } catch (Throwable t) {
            logger.error(LoggerCodeConstants.INTERNAL_ERROR, "", "", "Error occurred when refreshing router chain.", t);
            throw t;
        } finally {
            mainChain.getLock().writeLock().unlock();
        }

        // Set the reference of newly invokers to temp variable.
        notifyingInvokers.set(invokers);
```

四步的关键点：

1. `currentChain = backupChain` 在写锁内完成，读锁保护的调用方看不到中间态。
2. 更新 main 链时先拿 main 链自己的写锁，**等所有正在用 main 链的调用跑完**。这就是双链的全部意义：新链要等到「没人用旧链」才安全替换。
3. `notifyingInvokers` 记录新列表的引用，然后执行 `switchAction`（由 Directory 提供的切换回调，把 Directory 内部的 Invoker 引用也换掉）。
4. 再取写锁把 `currentChain` 换回 main 链，清空 `notifyingInvokers`，最后更新 backup 链。

`getSingleChain(URL, BitList, Invocation)`（`:100-114`）解决的是第 3 步窗口期的问题：此时 `currentChain` 是 backup 链，但已经切到新列表的调用应该走 main 链。判断依据就是 `availableInvokers.getOriginList() == notifying.getOriginList()`——引用相同说明调用方拿到的是新列表，那它就该用已经刷新的 main 链。

`destroy()`（`:212-223`）的顺序值得留意：先销毁 backup 链、切 `currentChain` 到 backup、再销毁 main 链，保证销毁过程中仍有可用链。

### SingleRouterChain

内层实现。字段与旧笔记那段代码几乎一一对应，但 invokers 换成了 `BitList`，并多了 `headStateRouter` 与 StateRouter 链：

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/SingleRouterChain.java:55-79（节选）
    private volatile BitList<Invoker<T>> invokers = BitList.emptyList();
    private volatile List<Router> routers = Collections.emptyList();
    private volatile List<Router> builtinRouters = Collections.emptyList();
    private volatile StateRouter<T> headStateRouter;
    private volatile List<StateRouter<T>> stateRouters;

    /**
     * Should continue route if current router's result is empty
     */
    private final boolean shouldFailFast;

    private final RouterSnapshotSwitcher routerSnapshotSwitcher;

    private final ReadWriteLock lock = new ReentrantReadWriteLock();
```

三个 List 字段的分工与旧版笔记一致（`invokers` 全量地址、`routers` 每次 `route://` 变化重建、`builtinRouters` 常驻不删），另外多了 StateRouter 链与 `shouldFailFast` / 快照开关。

StateRouter 链的组装（`:95-104`）：从尾部往前串，每个 StateRouter 的 `nextRouter` 指向下一个，最后一个指向 `TailStateRouter` 单例。`TailStateRouter` 的 `route` 直接原样返回入参（`TailStateRouter.java:51-54`），`setNextRouter` 是空实现——它就是链的终点哨兵。

`simpleRoute` 的执行顺序（`SingleRouterChain.java:162-197`）：先 StateRouter 链（一次 `headStateRouter.route(...)` 走完整条链），再 legacy Router 链（`for (Router router : routers)` 逐个调四参 `route`，用 `RouterResult#isNeedContinueRoute()` 短路）。注意 legacy 段开头有一句注释 `// Copy resultInvokers to a arrayList. BitList not support`——`RouterResult` 里装的是 `List`，所以进入 legacy 链前必须 `cloneToArrayList()`。

`route` 入口先做一致性校验（`:139-146`）：`invokers.getOriginList() != availableInvokers.getOriginList()` 就抛异常。这是双链正确性的最后一道防线——如果调用方手里的地址列表和 Router 链持有的不是同一份，说明切换时序出了问题，宁可失败也不能用错的规则过滤。

`setInvokers` 同时通知两类路由（`:313-318`）：

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/SingleRouterChain.java:313-318
    public void setInvokers(BitList<Invoker<T>> invokers) {
        this.invokers = (invokers == null ? BitList.emptyList() : invokers);
        routers.forEach(router -> router.notify(this.invokers));
        stateRouters.forEach(router -> router.notify(this.invokers));
    }
```

## Directory

`Directory` 是注册中心地址列表的容器。它继承 `Node`，3.3.6 有 13 个方法（旧笔记只覆盖了 7 个）。

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/Directory.java:35-72（节选）
public interface Directory<T> extends Node {

    Class<T> getInterface();

    List<Invoker<T>> list(Invocation invocation) throws RpcException;

    List<Invoker<T>> getAllInvokers();

    URL getConsumerUrl();

    boolean isDestroyed();

    default boolean isEmpty() {
        return CollectionUtils.isEmpty(getAllInvokers());
    }

    default boolean isServiceDiscovery() {
        return false;
    }

    void discordAddresses();

    RouterChain<T> getRouterChain();
```

`getRouterChain()` 是 Directory 与路由体系的直接关联点——路由链由 Directory 持有，并在地址变更时驱动 `setInvokers`。漏掉这个方法，就看不出「谁负责在地址更新时刷新路由规则」。

剩下三个 Invoker 生命周期方法（`Directory.java:80/89/96`）加一个 `isNotificationReceived()` default。`addInvalidateInvoker` 与 `addDisabledInvoker` 的区别是**会不会自动恢复**：前者的 javadoc 写「进重连任务队列，重连成功或下次地址刷新通知就回来」；后者写「只在服务下线通知时用，要等地址刷新通知才移除」。方法名里的 `discordAddresses()` 是源码里的拼写错误（少了个 `s`，本意是 discard），照抄时不要顺手改。

## Configurator

`Configurator` 把 `override://` 规则合并进 URL，实现类在 `cluster/configurator/override/` 与 `cluster/configurator/absent/` 两个子包下，但**接口本身在 `cluster` 包根目录**（`Configurator.java:37`），不是 `configurator` 包。

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/Configurator.java:70-84
    static Optional<List<Configurator>> toConfigurators(List<URL> urls) {
        if (CollectionUtils.isEmpty(urls)) {
            return Optional.empty();
        }

        ConfiguratorFactory configuratorFactory = urls.get(0)
                .getOrDefaultApplicationModel()
                .getExtensionLoader(ConfiguratorFactory.class)
                .getAdaptiveExtension();

        List<Configurator> configurators = new ArrayList<>(urls.size());
        for (URL url : urls) {
            if (EMPTY_PROTOCOL.equals(url.getProtocol())) {
                configurators.clear();
                break;
            }
```

工厂获取方式与旧版不同：不是 `ExtensionLoader.getExtensionLoader(ConfiguratorFactory.class)`，而是**从第一个 URL 拿 ApplicationModel 再取 ExtensionLoader**（`:75-78`）。这是 3.x ScopeModel 化的统一套路——扩展加载必须绑定到正确的模型实例上。

`EMPTY_PROTOCOL`（`empty://`）是一个特殊分支：遇到它就清空已收集的 configurator 并 break，语义是「清空所有 override 规则」。任何一段 `override://` 规则里出现 `empty://` 都会把整批规则清掉。

排序规则（`Configurator.java:105-119`，与旧版逐字一致）：先按 host 字典序，host 相同再按 `priority` 参数。注释说明意图是「指定了具体 IP 的规则优先于 `0.0.0.0` 的全局规则」。

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/ConfiguratorFactory.java:28-38
@SPI
public interface ConfiguratorFactory {

    @Adaptive(CommonConstants.PROTOCOL_KEY)
    Configurator getConfigurator(URL url);
}
```

SPI 文件 `org.apache.dubbo.rpc.cluster.ConfiguratorFactory` 只有两项：`override` 与 `absent`。

## LoadBalance

`LoadBalance` 接口在 `org.apache.dubbo.rpc.cluster`（cluster 包根），实现类在 `cluster.loadbalance` 子包。

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/LoadBalance.java:36-48
@SPI(RandomLoadBalance.NAME)
public interface LoadBalance {

    /**
     * select one invoker in list.
     */
    @Adaptive("loadbalance")
    <T> Invoker<T> select(List<Invoker<T>> invokers, URL url, Invocation invocation) throws RpcException;
}
```

内置扩展注册在 `dubbo-cluster/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.rpc.cluster.LoadBalance`：

```properties
# dubbo-cluster/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.rpc.cluster.LoadBalance
random=org.apache.dubbo.rpc.cluster.loadbalance.RandomLoadBalance
roundrobin=org.apache.dubbo.rpc.cluster.loadbalance.RoundRobinLoadBalance
leastactive=org.apache.dubbo.rpc.cluster.loadbalance.LeastActiveLoadBalance
consistenthash=org.apache.dubbo.rpc.cluster.loadbalance.ConsistentHashLoadBalance
shortestresponse=org.apache.dubbo.rpc.cluster.loadbalance.ShortestResponseLoadBalance
adaptive=org.apache.dubbo.rpc.cluster.loadbalance.AdaptiveLoadBalance
```

> [!WARNING]
> SPI 文件路径是 `...rpc.cluster.LoadBalance`，**不是** `...rpc.cluster.loadbalance.LoadBalance`。SPI 文件名按接口的 FQN 命名，实现类在哪个包不影响文件位置。按「实现类所在包」去找这个文件会扑空。

各算法的实现细节（预热权重公式、`ShortestResponse` 的滑动窗口、`ConsistentHash` 的虚拟节点）在 [LoadBalance](/docs/CS/Framework/Dubbo/LoadBalance.md)，本篇不重复。

## Cluster Implementation Semantics

`Cluster.join` 只负责「把 Directory 包成 Invoker」，真正的容错语义在各自的 `*ClusterInvoker.doInvoke` 里。11 个扩展名（含两个 Wrapper）对应的 Invoker 与行为如下，全部按源码逐条核对：

| 扩展名 (SPI) | Invoker 类 | 语义 | 重试/重复行为 | 典型场景 |
|---|---|---|---|---|
| `failover` | `FailoverClusterInvoker` | 失败换一个 Provider 重试 | 最多 `retries+1` 次（含首次）；**业务异常 `e.isBiz()` 不重试**，直接抛出（`FailoverClusterInvoker.java:103-106`） | 读操作、幂等写 |
| `failfast` | `FailfastClusterInvoker` | 只调一次，失败立即抛异常 | 无重试 | 非幂等写 |
| `failsafe` | `FailsafeClusterInvoker` | 失败吞掉，返回空 `Result` | 无重试 | 审计日志等可丢操作 |
| `failback` | `FailbackClusterInvoker` | 失败记入后台定时重试 | `HashedWheelTimer`（`RETRY_FAILED_PERIOD=5s`）异步重试 `retries` 次，调用侧立即返回空（`FailbackClusterInvoker.java:59,136-139`） | 通知类消息 |
| `forking` | `ForkingClusterInvoker` | 并发调 `forks` 个 Provider，取第一个成功 | 并发 `forks` 个（`FORKS_KEY`/`DEFAULT_FORKS`），用共享线程池 `FrameworkExecutorRepository#getSharedExecutor()`（`ForkingClusterInvoker.java:62-67`） | 实时性要求高的读 |
| `broadcast` | `BroadcastClusterInvoker` | 逐个调**全部** Provider | 失败数达 `broadcast.fail.percent`（默认 100，即任一失败即抛）阈值才中断（`BroadcastClusterInvoker.java:64-106`） | 广播通知 |
| `available` | `AvailableClusterInvoker` | 取第一个 `isAvailable()` 的 Provider | **不走 LoadBalance**，顺序遍历 | 只需可用即可 |
| `mergeable` | `MergeableClusterInvoker` | 跨 group 调用并合并结果 | 无 group 合并时退化为单 group 调用；合并走 `Merger` SPI（`MERGER_KEY`）（`MergeableClusterInvoker.java:71-90`） | 分组聚合结果 |
| `zone-aware` | `ZoneAwareClusterInvoker` | 多注册中心选址 | `preferred=true` 注册中心 → 同 zone → 跨注册中心 LoadBalance → 首个可用（`ZoneAwareClusterInvoker.java:69-123`） | 多注册中心/单元化 |
| `mock` | `MockClusterInvoker`（Wrapper 内） | 降级 | `fail`/`force` 两种模式（见 [MockClusterInvoker](#mockclusterinvoker)） | 降级 |
| `scope` | `ScopeClusterInvoker`（Wrapper 内） | 按 ScopeModel 路由 | 包装真实 Cluster | 多应用隔离 |

`failover` 的调用次数是**本地方法参数 + 1**，且支持通过 attachment 里的 `retries` 临时覆盖（`FailoverClusterInvoker.java:129-142` 的 `calculateInvokeTimes`）：

```java
// dubbo-cluster/.../support/FailoverClusterInvoker.java:129-142
private int calculateInvokeTimes(String methodName) {
    int len = getUrl().getMethodParameter(methodName, RETRIES_KEY, DEFAULT_RETRIES) + 1;
    RpcContext rpcContext = RpcContext.getClientAttachment();
    Object retry = rpcContext.getObjectAttachment(RETRIES_KEY);
    if (retry instanceof Number) {
        len = ((Number) retry).intValue() + 1;
        rpcContext.removeAttachment(RETRIES_KEY);
    }
    if (len <= 0) { len = 1; }
    return len;
}
```

> [!TIP]
> `retries` 配置的是「额外重试次数」，实际最多调用 `retries + 1` 个 Provider；把它设成 0 仍会调用一次（不会零次调用）。

## AbstractClusterInvoker Template Method

所有 Cluster Invoker 都继承 `AbstractClusterInvoker`（它实现 `ClusterInvoker` 接口），核心是一个模板方法 + 一个 `select` 选址辅助。

`invoke`（入口，`AbstractClusterInvoker.java:344-370`）的固定流程：

```
checkWhetherDestroyed()         // 已 destroy 抛异常
  → list(invocation)            // 委托 Directory.list → RouterChain 路由，拿到候选 BitList
  → checkInvokers(...)          // 空则抛 NO_INVOKER_AVAILABLE_AFTER_FILTER
  → initLoadBalance(...)        // 按方法级 loadbalance 参数取 LoadBalance 扩展
  → doInvoke(...)               // 抽象方法，由具体容错策略实现
```

`select`（`AbstractClusterInvoker.java:155-185`）在 `doInvoke` 里被反复调用，**它的职责是「避免重复选到同一 invoker」**，而非单纯做负载均衡：

- **sticky（粘性）**：读方法参数 `CLUSTER_STICKY_KEY`（默认 `DEFAULT_CLUSTER_STICKY` = false）。若开启且 `stickyInvoker` 仍在候选里且可用，直接返回它（`AbstractClusterInvoker.java:164-176`）。`stickyInvoker` 是字段级缓存，记下上一次选中的 invoker。
- **selected 去重**：`doSelect`（`:187-240`）先 `loadbalance.select(...)`，若选中的 invoker 在 `selected` 列表里或不可用时，调用 `reselect`（`:254-328`）从「未选过的 + 可用的」里再挑一个；`reselect` 最多看 `reselectCount` 个（配置项 `RESELECT_COUNT`，默认 `DEFAULT_RESELECT_COUNT`），防止候选很多时长时间 hang。
- `availableCheck`（`CLUSTER_AVAILABLE_CHECK_KEY`）为 true 时，选到不可用的 invoker 会 `invalidateInvoker` 把它丢进 Directory 的无效列表（`AbstractClusterInvoker.java:336-342`）。

也就是说 **LoadBalance 只负责「按权重/策略挑一个」，重复规避与粘性由 `AbstractClusterInvoker.select` 在它外层兜住**，二者解耦——这正是 Dubbo 集群层的核心设计理念：容错策略（谁失败、怎么重试）与选址算法（挑谁）各自独立演进。

## MockClusterInvoker

`mock` 是 Wrapper 型扩展（`MockClusterWrapper`），它把真实 Invoker 包一层 `MockClusterInvoker`（`support/wrapper/MockClusterInvoker.java:48`）。降级触发取决于方法级 `MOCK_KEY`：

- **无 mock 配置**：直接走真实 invoker（`MockClusterInvoker.java:105-107`）。
- **`force.*`（以 `FORCE_KEY` 开头）**：跳过真实调用，直接 `doMockInvoke`（`:108-118`）——强制降级。
- **`fail.*`（普通 mock 值）**：先调真实 invoker，仅当返回/抛出**非业务**异常（`e.isBiz()` 为 false）时才 `doMockInvoke`（`:119-149`）；业务异常照常抛出。
- `doMockInvoke`（`:155-186`）通过 `selectMockInvoker` 给 invocation 打 `INVOCATION_NEED_MOCK=true` attachment，让 `Directory.list` 返回 mock invoker 列表；若取不到则用 `new MockInvoker(...)` 兜底。

> [!NOTE]
> `MockClusterInvoker` 实现的是 `ClusterInvoker` 接口而非继承 `AbstractClusterInvoker`——它不参与 `list→route→loadbalance` 模板，而是直接持有被包装的 invoker，是「Wrapper 在最外层做降级」的特例。

## Cluster Interceptor Chain

老资料里的 `ClusterInterceptor`（`cluster/interceptor/ClusterInterceptor.java`）在 **3.3.6 已标 `@Deprecated`**，且只在 `CLUSTER_INTERCEPTOR_COMPATIBLE_KEY`（默认 `"false"`）开启时才装配（`AbstractCluster.java:45-55,188-204`），通过 `InterceptorInvokerNode` 走 `before/intercept/after/Listener.onError`——这是 2.7.x 的兼容路径。

真正的消费侧拦截链由 `AbstractCluster.join` → `buildClusterInterceptors`（`AbstractCluster.java:45-75`）构建，分两层：

1. **`ClusterFilter` 链**：`ClusterFilterInvoker` 用 `FilterChainBuilder`（默认 `DefaultFilterChainBuilder`）把激活的 `ClusterFilter` 串起来，SPI 名 `reference.filter`、group `consumer`。3.3.6 内置实现有 `ConsumerContextFilter`、`ConsumerClassLoaderFilter`、`MetricsConsumerFilter`、`RouterSnapshotFilter`（`cluster/filter/support/`）。
2. **`InvocationInterceptorBuilder` 链**：`InvocationInterceptorInvoker` 用 `InvocationInterceptorBuilder` 构建（`INVOCATION_INTERCEPTOR_KEY`）。

> [!WARNING]
> 老资料写的 `ConsumerContextClusterInterceptor` 在 3.3.6 **不存在**——承担「把消费端上下文塞进 invocation」职责的现在是 `ClusterFilter` 实现 `ConsumerContextFilter`，不是 `ClusterInterceptor` 子类。自定义扩展应实现 `ClusterFilter` 而非已废弃的 `ClusterInterceptor`。

## RegistryDirectory Refresh Mechanism

`RegistryDirectory`（`dubbo-registry/dubbo-registry-api/.../integration/RegistryDirectory.java`）是 `Directory` 的注册中心实现，它的 `notify` 是「地址变更如何刷新 invoker 列表」的总入口。

`notify(List<URL>)`（`:200-236`）先把推送 URL 按 `judgeCategory` 分成三类——`CONFIGURATORS_CATEGORY` / `ROUTERS_CATEGORY` / `PROVIDERS_CATEGORY`；configurators 经 `Configurator.toConfigurators` 合并、routers 经 `toRouters` 重建（2.6.x 兼容开关 `ENABLE_26X_CONFIGURATION_LISTEN` 默认开）；provider URL 再经 `AddressListener` 扩展点预处理，最后 `refreshOverrideAndInvoker` → `refreshInvoker` → `toInvokers`。

`toInvokers(Map, List<URL>)`（`:451-518`）的刷新规则是「**按未合并的 provider URL 做缓存 key，参数变了才重新 refer**」：

```java
// dubbo-registry/.../integration/RegistryDirectory.java:451-485（节选）
private Map<URL, Invoker<T>> toInvokers(Map<URL, Invoker<T>> oldUrlInvokerMap, List<URL> urls) {
    // ...
    for (URL providerUrl : urls) {
        URL url = mergeUrl(providerUrl);                 // 合并消费端参数
        // 缓存 key 用未合并的 providerUrl，与消费侧参数无关
        Invoker<T> invoker = oldUrlInvokerMap == null ? null : oldUrlInvokerMap.remove(url);
        if (invoker == null) {                           // 不在缓存里才重新 refer
            // ... enabled / disabled 判断 ...
            if (enabled) {
                invoker = protocol.refer(serviceType, url);
            }
        }
        newUrlInvokerMap.put(url, invoker);
    }
    return newUrlInvokerMap;
}
```

两个值得记住的边界（`refreshInvoker`，`:274-312`）：

- 收到单个 `empty://` 协议 URL 时，置 `forbidden=true` 并 `destroyAllInvokers()`——即「禁用该服务全部地址」。
- 收到**空列表**（`Collections.emptyList()`）且本地 `cachedInvokerUrls` 非空时，触发「空保护」，沿用上次缓存的地址，不立即清空——避免注册中心瞬时抖动把可用 Provider 全部摘掉。

刷新完 invoker 列表后，`RouterChain#setInvokers` 被调用来驱动路由链热切换（见上文 [RouterChain](#routerchain) 的双链机制）。

## AbstractClusterInvoker Core Code

`AbstractClusterInvoker` 是模板方法基类（`AbstractClusterInvoker.java:62`）。它的 `invoke` 是 ClusterInvoker 调用总入口，四个固定步骤与 `select`/`doSelect` 的去重逻辑如下。

`invoke`（`AbstractClusterInvoker.java:344-370`）依次做四件事：

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/support/AbstractClusterInvoker.java:344-370
public Result invoke(final Invocation invocation) throws RpcException {
    checkWhetherDestroyed();                       // 1. 已 destroy 抛 "is now destroyed"
    List<Invoker<T>> invokers = list(invocation);  // 2. 委托 Directory.list → RouterChain 路由
    checkInvokers(invokers, invocation);           // 3. 空则抛 NO_INVOKER_AVAILABLE_AFTER_FILTER
    LoadBalance loadbalance = initLoadBalance(invokers, invocation); // 4. 按方法级 loadbalance 取扩展
    return doInvoke(invocation, invokers, loadbalance);             // 抽象方法，具体容错策略实现
}
```

`initLoadBalance`（`AbstractClusterInvoker.java:466-478`）取 LoadBalance 的方式：候选非空时取「第一个 invoker 的 URL」的方法级 `loadbalance` 参数（默认 `DEFAULT_LOADBALANCE`=random），空时直接取默认扩展——即 LoadBalance 实例挂在候选列表首 invoker 的配置上。

`select`（`AbstractClusterInvoker.java:155-185`）负责「避免重复选到同一 invoker」，而非做负载均衡：

```java
// AbstractClusterInvoker.java:155-185（节选）
protected Invoker<T> select(LoadBalance loadbalance, Invocation invocation,
        List<Invoker<T>> invokers, List<Invoker<T>> selected) throws RpcException {
    // sticky：读方法参数 CLUSTER_STICKY_KEY，默认 DEFAULT_CLUSTER_STICKY=false
    boolean sticky = invokers.get(0).getUrl().getMethodParameter(methodName, CLUSTER_STICKY_KEY, DEFAULT_CLUSTER_STICKY);
    if (stickyInvoker != null && !invokers.contains(stickyInvoker)) stickyInvoker = null; // 已不在候选则清空
    if (sticky && stickyInvoker != null && (selected == null || !selected.contains(stickyInvoker))) {
        if (availableCheck && stickyInvoker.isAvailable()) return stickyInvoker;          // 粘性命中直接返回
    }
    Invoker<T> invoker = doSelect(loadbalance, invocation, invokers, selected);            // 否则走 doSelect
    if (sticky) stickyInvoker = invoker;                                                 // 记下本次选中
    return invoker;
}
```

`doSelect`（`AbstractClusterInvoker.java:187-240`）先让 LoadBalance 挑一个，再判定「是否在 `selected` 里 / 不可用」：

```java
// AbstractClusterInvoker.java:187-240（节选）
Invoker<T> invoker = loadbalance.select(invokers, getUrl(), invocation);  // ① 全量候选交给 LoadBalance
boolean isSelected = selected != null && selected.contains(invoker);      // 已被本次调用选过
boolean isUnavailable = availableCheck && !invoker.isAvailable() && getUrl() != null;
if (isUnavailable) invalidateInvoker(invoker);                            // 不可用则丢进 Directory 无效列表
if (isSelected || isUnavailable) {
    Invoker<T> rInvoker = reselect(loadbalance, invocation, invokers, selected, availableCheck); // ② 重选
    if (rInvoker != null) invoker = rInvoker;
    else { // ③ 兜底：取 invokers 中 index+1 的那个，避免碰撞
        int index = invokers.indexOf(invoker);
        invoker = invokers.get((index + 1) % invokers.size());
    }
}
```

关键点（修正「LoadBalance 看到 selected/available 集合」的常见误解）：**LoadBalance 拿到的永远是原始全量 `invokers` 列表**，`selected` 去重与可用性过滤发生在它外层的 `reselect`（`AbstractClusterInvoker.java:254-328`）。`reselect` 会新建一个 `reselectInvokers`（排除 `selected` 与不可用者），再把这个**收窄后的候选列表**交给 `loadbalance.select(...)`（`:306`、`:323`）——这才是「selected/available 集合」真正作用于选址的地方，而不是通过 `BitList.clone/subList` 传进 LoadBalance。

`reselect` 里 `reselectCount` 限量逻辑：配置项 `RESELECT_COUNT`，默认 `DEFAULT_RESELECT_COUNT=10`（`CommonConstants.java:527`）。候选数 ≥ `reselectCount` 时只随机挑 `reselectCount` 个（`:274-302`），防止候选极多时长时间 hang。`availableCheck` 为 true 时选到不可用 invoker 会走 `invalidateInvoker`（`AbstractClusterInvoker.java:336-342`）→ `getDirectory().addInvalidateInvoker(invoker)`，交由后台 `connectivityExecutor` 重连任务处理。

## Failover Cluster Retry Loop

`FailoverClusterInvoker.doInvoke`（`FailoverClusterInvoker.java:59-127`）是「失败换 Provider 重试」的完整实现，与上文已写的 `calculateInvokeTimes` 一一呼应：

```java
// dubbo-cluster/.../support/FailoverClusterInvoker.java:59-127（节选）
public Result doInvoke(Invocation invocation, List<Invoker<T>> invokers, LoadBalance loadbalance) {
    List<Invoker<T>> copyInvokers = invokers;
    int len = calculateInvokeTimes(methodName);            // = retries+1（含首次），attachment 可临时覆盖
    RpcException le = null;                                // last exception
    List<Invoker<T>> invoked = new ArrayList<>(copyInvokers.size()); // 已选 invoker，传给 select 去重
    Set<String> providers = new HashSet<>(len);
    for (int i = 0; i < len; i++) {
        if (i > 0) {                                       // 重试前重新 list，避免候选漂移
            checkWhetherDestroyed();
            copyInvokers = list(invocation);
            checkInvokers(copyInvokers, invocation);
        }
        Invoker<T> invoker = select(loadbalance, invocation, copyInvokers, invoked); // 去重选新 Provider
        invoked.add(invoker);
        boolean success = false;
        try {
            Result result = invokeWithContext(invoker, invocation);
            success = true;
            return result;                                  // 成功即返回
        } catch (RpcException e) {
            if (e.isBiz()) throw e;                         // 业务异常不重试，直接抛出
            le = e;                                         // 非业务异常：记 last exception，进入下一轮
        } catch (Throwable e) {
            le = new RpcException(e.getMessage(), e);
        } finally {
            if (!success) providers.add(invoker.getUrl().getAddress()); // 累计失败 Provider 地址
        }
    }
    throw new RpcException(le.getCode(), "...Tried " + len + " times...", le.getCause() != null ? le.getCause() : le);
}
```

三个源码级细节：① 每次重试（i>0）都重新 `list(invocation)` 拿最新候选，注释明确「若 invokers 变了，invoked 也会失真」；② 业务异常 `e.isBiz()` 立即 `throw`，**不打入重试循环**；③ 循环结束仍未成功，抛出携带 `le`（最后一次异常）与失败 Provider 列表的 `RpcException`。`len` 由 `calculateInvokeTimes` 决定（上文已贴 `:129-142`），`retries` 配的是「额外重试次数」，实际最多调 `retries+1` 个 Provider。

## Failfast & Failsafe Code

这两个策略是 `doInvoke` 的极简分支，都只调一次，差异在异常处理。

`FailfastClusterInvoker.doInvoke`（`FailfastClusterInvoker.java:44-64`）只选一个直接调，任何异常（非业务异常包装成 `RpcException`）立即抛出：

```java
// dubbo-cluster/.../support/FailfastClusterInvoker.java:44-64（节选）
public Result doInvoke(Invocation invocation, List<Invoker<T>> invokers, LoadBalance loadbalance) {
    Invoker<T> invoker = select(loadbalance, invocation, invokers, null); // selected 传 null，不去重
    try {
        return invokeWithContext(invoker, invocation);
    } catch (Throwable e) {
        if (e instanceof RpcException && ((RpcException) e).isBiz()) throw (RpcException) e; // 业务异常原样抛
        throw new RpcException(... "Failfast invoke providers ..." ..., e.getCause() != null ? e.getCause() : e);
    }
}
```

`FailsafeClusterInvoker.doInvoke`（`FailsafeClusterInvoker.java:49-63`）同样只调一次，但失败只记日志、返回空 `Result`：

```java
// dubbo-cluster/.../support/FailsafeClusterInvoker.java:49-63
public Result doInvoke(Invocation invocation, List<Invoker<T>> invokers, LoadBalance loadbalance) {
    try {
        Invoker<T> invoker = select(loadbalance, invocation, invokers, null);
        return invokeWithContext(invoker, invocation);
    } catch (Throwable e) {
        logger.error(CLUSTER_ERROR_RESPONSE, "Failsafe for provider exception", "", "Failsafe ignore exception: " + e.getMessage(), e);
        return AsyncRpcResult.newDefaultAsyncResult(null, null, invocation); // 吞掉异常，返回空结果
    }
}
```

## Failback Timer Retry

`FailbackClusterInvoker` 首次调用失败不抛，而是把任务丢进 `HashedWheelTimer` 后台定时重试，调用侧立即返回空 `Result`。

核心常量与定时器创建（`FailbackClusterInvoker.java:59-99`）：

```java
// dubbo-cluster/.../support/FailbackClusterInvoker.java:59-99（节选）
private static final long RETRY_FAILED_PERIOD = 5;          // 重试周期（秒）
public FailbackClusterInvoker(Directory<T> directory) {
    super(directory);
    int retriesConfig = getUrl().getParameter(RETRIES_KEY, DEFAULT_FAILBACK_TIMES); // 默认 DEFAULT_FAILBACK_TIMES=3
    if (retriesConfig < 0) retriesConfig = DEFAULT_FAILBACK_TIMES;
    int failbackTasksConfig = getUrl().getParameter(FAIL_BACK_TASKS_KEY, DEFAULT_FAILBACK_TASKS);
    ...
    retries = retriesConfig; failbackTasks = failbackTasksConfig;
}
private void addFailed(...) {
    if (failTimer == null) {
        synchronized (this) {
            if (failTimer == null) {
                failTimer = new HashedWheelTimer(
                    new NamedThreadFactory("failback-cluster-timer", true), // 守护线程
                    1, TimeUnit.SECONDS,   // tickDuration=1s
                    32,                    // ticksPerWheel=32
                    failbackTasks);        // maxPendingTimeouts
            }
        }
    }
    RetryTimerTask retryTimerTask = new RetryTimerTask(loadbalance, invocation, invokers, lastInvoker, retries, RETRY_FAILED_PERIOD, consumerUrl);
    failTimer.newTimeout(retryTimerTask, RETRY_FAILED_PERIOD, TimeUnit.SECONDS); // 5s 后触发
}
```

`doInvoke`（`FailbackClusterInvoker.java:117-141`）用 `invokeWithContextAsync`（因后台重试会清 `ServiceContext`），失败且 `retries>0` 时 `addFailed`，无论成败都返回空 `Result`。`RetryTimerTask.run`（`FailbackClusterInvoker.java:190-218`）每次重试时以 `Collections.singletonList(lastInvoker)` 作为 `selected` 去重选新 invoker；若 `++retriedTimes >= retries` 则放弃，否则 `rePut(timeout)` 把自己重新塞回 `HashedWheelTimer` 再等一个 `RETRY_FAILED_PERIOD`（5s）。即：后台按 5s 间隔最多重试 `retries`（默认 3）次。

## Forking Concurrent Invoke

`ForkingClusterInvoker` 并发调 `forks` 个 Provider，取第一个成功返回的，用共享线程池而非自建池。

线程池来源与并发收集（`ForkingClusterInvoker.java:62-115`）：

```java
// dubbo-cluster/.../support/ForkingClusterInvoker.java:62-115（节选）
executor = directory.getUrl().getOrDefaultFrameworkModel()
        .getBeanFactory().getBean(FrameworkExecutorRepository.class)
        .getSharedExecutor();                       // 共享线程池，非 Forking 自建

public Result doInvoke(Invocation invocation, List<Invoker<T>> invokers, LoadBalance loadbalance) {
    final int forks = getUrl().getParameter(FORKS_KEY, DEFAULT_FORKS); // DEFAULT_FORKS=2（Constants.java:25）
    final int timeout = getUrl().getParameter(TIMEOUT_KEY, DEFAULT_TIMEOUT);
    if (forks <= 0 || forks >= invokers.size()) selected = invokers;  // forks 越界则全发
    else { while (selected.size() < forks) {                         // 用 select 避免重复选同一 invoker
        Invoker<T> invoker = select(loadbalance, invocation, invokers, selected);
        if (!selected.contains(invoker)) selected.add(invoker);
    }}
    final BlockingQueue<Object> ref = new LinkedBlockingQueue<>(1);    // 容量 1，仅收第一个结果/异常
    selected.forEach(invoker -> CompletableFuture.supplyAsync(() -> {
        if (ref.size() > 0) return null;                             // 已有结果则后续线程直接放弃
        return invokeWithContextAsync(invoker, invocation, consumerUrl);
    }, executor).whenComplete((v, t) -> {
        if (t == null) ref.offer(v);                                 // 成功：offer 结果
        else if (count.incrementAndGet() >= selected.size()) ref.offer(t); // 全部失败：offer 异常
    }));
    Object ret = ref.poll(timeout, TimeUnit.MILLISECONDS);            // 阻塞等第一个到达，超时抛 RpcException
    ...
}
```

要点：① `forks` 默认 `DEFAULT_FORKS=2`，若 `forks<=0` 或 `>=invokers.size()` 则向全部 Provider 发；② `BlockingQueue` 容量固定为 1，先到者（成功结果或「全部失败标志」异常）写入，后续线程通过 `ref.size()>0` 短路；③ 主线程 `ref.poll(timeout, MILLISECONDS)` 阻塞等第一个结果，超时抛异常；④ 用 `FrameworkExecutorRepository#getSharedExecutor()` 共享线程池，并在 `finally` 清 `ClientAttachment`。

## Broadcast Percent Threshold

`BroadcastClusterInvoker` 逐个调**全部** Provider，但**不是**「任一失败即抛」——失败数达到 `broadcast.fail.percent` 阈值才中断并抛出。

阈值计算与循环（`BroadcastClusterInvoker.java:44-126`）：

```java
// dubbo-cluster/.../support/BroadcastClusterInvoker.java:44-126（节选）
private static final String BROADCAST_FAIL_PERCENT_KEY = "broadcast.fail.percent";
private static final int MAX_BROADCAST_FAIL_PERCENT = 100;
private static final int MIN_BROADCAST_FAIL_PERCENT = 0;

int broadcastFailPercent = url.getParameter(BROADCAST_FAIL_PERCENT_KEY, MAX_BROADCAST_FAIL_PERCENT); // 默认 100
if (broadcastFailPercent < 0 || broadcastFailPercent > 100) broadcastFailPercent = 100; // 越界重置为 100
// 可容忍失败数：ceil 语义用整数除法，total*percent/100
int failThresholdIndex = invokers.size() * broadcastFailPercent / MAX_BROADCAST_FAIL_PERCENT;
int failIndex = 0;
for (int i = 0, invokersSize = invokers.size(); i < invokersSize; i++) {
    Invoker<T> invoker = invokers.get(i);
    try {
        result = invokeWithContext(invoker, subInvocation);
        if (null != result && result.hasException()) { exception = getRpcException(result.getException()); failIndex++;
            if (failIndex == failThresholdIndex) break; }             // 达到阈值才 break
    } catch (Throwable e) {
        exception = getRpcException(e); failIndex++;
        if (failIndex == failThresholdIndex) break;                   // 达到阈值才 break
    }
}
if (exception != null) throw exception;                              // 有异常（且循环结束）才抛
return result;
```

计算语义：`failThresholdIndex = total * failPercent / 100`。`failPercent=100`（默认）时 `failThresholdIndex = total`，即**所有** Provider 都失败才会抛（任一失败只是记录，不中断）；`failPercent=0` 时 `failThresholdIndex=0`，第一个失败即 `failIndex==0==failThresholdIndex` 而 break 并抛出。注意临界判断是 `failIndex == failThresholdIndex`（等于而非大于等于），且每个 invoker 都先建 `RpcInvocation` 子调用（`subInvocation`）并 `copyObjectAttachments`，在 `finally` 里对非末次调用 `restoreContext.restore()` 还原 `RpcContext`。

## Mergeable & Merger SPI

`MergeableClusterInvoker.doInvoke`（`MergeableClusterInvoker.java:62-199`）按 `MERGER_KEY` 决定行为：无 merger 退化成单 group 调用；有 merger 则并发调各 group 再合并。

```java
// dubbo-cluster/.../support/MergeableClusterInvoker.java:62-199（节选）
String merger = getUrl().getMethodParameter(invocation.getMethodName(), MERGER_KEY);
if (ConfigUtils.isEmpty(merger)) {                 // 无 merger：退化，遍历 invokers 找第一个 available 调
    for (final Invoker<T> invoker : invokers) {
        if (invoker.isAvailable()) { try { return invokeWithContext(invoker, invocation); }
            catch (RpcException e) { if (e.isNoInvokerAvailableAfterFilter()) continue; else throw e; } }
    }
    return invokeWithContext(invokers.iterator().next(), invocation);
}
// 有 merger：按 serviceKey 分组并发调，结果异步收集
Map<String, Result> results = new HashMap<>();
for (final Invoker<T> invoker : invokers) {
    RpcInvocation subInvocation = new RpcInvocation(invocation, invoker);
    subInvocation.setAttachment(Constants.ASYNC_KEY, "true");         // 强制异步，并发执行
    results.put(invoker.getUrl().getServiceKey(), invokeWithContext(invoker, subInvocation));
}
... // 阻塞取各 Result（Integer.MAX_VALUE ms），异常记日志但不中断，正常结果入 resultList
if (merger.startsWith(".")) {                    // ".methodName" 形式：反射调返回类型上的合并方法
    merger = merger.substring(1);
    Method method = returnType.getMethod(merger, returnType);
    ...
    result = method.invoke(resultList.remove(0).getValue(), r.getValue()); // 逐个归约
} else {                                         // SPI 名形式：走 Merger 扩展
    Merger resultMerger;
    if (ConfigUtils.isDefault(merger))            // "*" 默认：按返回类型自动匹配 MergerFactory.getMerger(returnType)
        resultMerger = applicationModel.getBeanFactory().getBean(MergerFactory.class).getMerger(returnType);
    else                                         // 否则按名字取 Merger SPI 扩展
        resultMerger = applicationModel.getExtensionLoader(Merger.class).getExtension(merger);
    result = resultMerger.merge(rets.toArray((Object[]) Array.newInstance(returnType, 0)));
}
```

`Merger` 接口极简（`Merger.java:21-25`）：`@SPI public interface Merger<T> { T merge(T... items); }`。`MergerFactory.getMerger(returnType)`（`MergerFactory.java:55-68`）按返回类型的**实际泛型实参**在 `MERGER_CACHE` 里查对应 Merger；若 `returnType.isArray()` 则统一回落到 `ArrayMerger.INSTANCE`。

`Merger` SPI 文件 `dubbo-cluster/.../META-INF/dubbo/internal/org.apache.dubbo.rpc.cluster.Merger` 共 **11 项**，逐行如下：

| SPI key | 实现类 | 合并类型 |
|---|---|---|
| `map` | `org.apache.dubbo.rpc.cluster.merger.MapMerger` | `Map` |
| `set` | `org.apache.dubbo.rpc.cluster.merger.SetMerger` | `Set` |
| `list` | `org.apache.dubbo.rpc.cluster.merger.ListMerger` | `List` |
| `byte` | `org.apache.dubbo.rpc.cluster.merger.ByteArrayMerger` | `byte[]` |
| `char` | `org.apache.dubbo.rpc.cluster.merger.CharArrayMerger` | `char[]` |
| `short` | `org.apache.dubbo.rpc.cluster.merger.ShortArrayMerger` | `short[]` |
| `int` | `org.apache.dubbo.rpc.cluster.merger.IntArrayMerger` | `int[]` |
| `long` | `org.apache.dubbo.rpc.cluster.merger.LongArrayMerger` | `long[]` |
| `float` | `org.apache.dubbo.rpc.cluster.merger.FloatArrayMerger` | `float[]` |
| `double` | `org.apache.dubbo.rpc.cluster.merger.DoubleArrayMerger` | `double[]` |
| `boolean` | `org.apache.dubbo.rpc.cluster.merger.BooleanArrayMerger` | `boolean[]` |

即：`map/set/list` 三类集合合并器 + 8 种基本类型数组合并器，共 11 项（源码树 `merger/` 下另有 `ArrayMerger`（数组总入口，非 SPI 直列）等内部类）。

## ZoneAware Multi-Registry

`ZoneAwareClusterInvoker`（`ZoneAwareClusterInvoker.java:67-124`）在多注册中心场景下选「哪个注册中心的 ClusterInvoker」来发请求，四级优先级：

```java
// dubbo-cluster/.../support/registry/ZoneAwareClusterInvoker.java:67-124（节选）
public Result doInvoke(Invocation invocation, List<Invoker<T>> invokers, LoadBalance loadbalance) {
    // ① preferred=true 的注册中心优先级最高
    for (Invoker<T> invoker : invokers) {
        ClusterInvoker<T> ci = (ClusterInvoker<T>) invoker;
        if (ci.isAvailable() && ci.getRegistryUrl().getParameter(PREFERRED_KEY, false))
            return ci.invoke(invocation);
    }
    // ② 同 zone：取 REGISTRY_ZONE attachment（或 ZoneDetector 探测），挑同 zone 注册中心
    String zone = rpcContext.getAttachment(REGISTRY_ZONE);
    String force = rpcContext.getAttachment(REGISTRY_ZONE_FORCE);
    if (StringUtils.isEmpty(zone) && zoneDetector != null) {
        zone = zoneDetector.getZoneOfCurrentRequest(invocation);
        force = zoneDetector.isZoneForcingEnabled(invocation, zone);
    }
    if (StringUtils.isNotEmpty(zone)) {
        for (Invoker<T> invoker : invokers) {
            ClusterInvoker<T> ci = (ClusterInvoker<T>) invoker;
            if (ci.isAvailable() && zone.equals(ci.getRegistryUrl().getParameter(ZONE_KEY)))
                return ci.invoke(invocation);
        }
        if (StringUtils.isNotEmpty(force) && "true".equalsIgnoreCase(force))
            throw new IllegalStateException("No registry instance in zone ..."); // force 且无同 zone 可用则抛
    }
    // ③ 跨注册中心 LoadBalance（注册中心权重计入）
    Invoker<T> balancedInvoker = select(loadbalance, invocation, invokers, null);
    if (balancedInvoker != null && balancedInvoker.isAvailable()) return balancedInvoker.invoke(invocation);
    // ④ 兜底：首个 available 的注册中心
    for (Invoker<T> invoker : invokers) {
        ClusterInvoker<T> ci = (ClusterInvoker<T>) invoker;
        if (ci.isAvailable()) return ci.invoke(invocation);
    }
    throw new RpcException("No provider available in " + invokers);
}
```

注意 `invokers` 里每个元素本身是一个 `ClusterInvoker`（多注册中心时，`RegistryProtocol` 把每个注册中心包成一个 ClusterInvoker 再聚合成 List 传入），所以 `doInvoke` 是在「注册中心 ClusterInvoker」之间选址，选中的那个再由其内部 `invoke` 走自己的容错策略。`zoneDetector` 默认取 `ZoneDetector` 扩展的 `"default"` 实现（构造器 `:58-63`）。

## Directory Routing Entry

`AbstractDirectory.list`（`AbstractDirectory.java:200-253`）是「候选列表如何过路由」的总入口。它先把 `validInvokers`（已初始化）或 `invokers` 做 `clone()` 防篡改，取 `RouterChain` 的 `singleChain`，再委托 `doList`：

```java
// dubbo-cluster/.../directory/AbstractDirectory.java:200-253（节选）
public List<Invoker<T>> list(Invocation invocation) throws RpcException {
    if (destroyed) throw new RpcException("Directory ... already destroyed ...");
    BitList<Invoker<T>> availableInvokers;
    SingleRouterChain<T> singleChain = null;
    try {
        if (routerChain != null) routerChain.getLock().readLock().lock();
        availableInvokers = invokersInitialized ? validInvokers.clone() : invokers.clone(); // clone 防 doList 修改
        if (routerChain != null) {
            singleChain = routerChain.getSingleChain(getConsumerUrl(), availableInvokers, invocation); // 双链择一
            singleChain.getLock().readLock().lock();
        }
    } finally { if (routerChain != null) routerChain.getLock().readLock().unlock(); }
    List<Invoker<T>> routedResult = doList(singleChain, availableInvokers, invocation); // 抽象，子类实现
    if (routedResult.isEmpty()) logger.warn(... "No provider available after connectivity filter ...");
    return Collections.unmodifiableList(routedResult);                                 // 返回不可变 List
}

// doList 是抽象方法（AbstractDirectory.java:568-570）
protected abstract List<Invoker<T>> doList(
        SingleRouterChain<T> singleRouterChain, BitList<Invoker<T>> invokers, Invocation invocation) throws RpcException;
```

也就是说：**`list` 不自己调 `RouterChain.route`，而是把 `singleChain` 与 `BitList` 候选交给子类 `doList`，路由在 `doList` 内发生**。`StaticDirectory.doList`（`StaticDirectory.java:122-141`）展示了最简单形态——直连/多 URL 场景，`doList` 直接让 `singleRouterChain.route(...)` 过滤（无注册中心则原样返回 `invokers`）：

```java
// dubbo-cluster/.../directory/StaticDirectory.java:122-141（节选）
protected List<Invoker<T>> doList(SingleRouterChain<T> singleRouterChain, BitList<Invoker<T>> invokers, Invocation invocation) {
    if (singleRouterChain != null) {
        try {
            List<Invoker<T>> finalInvokers = singleRouterChain.route(getConsumerUrl(), invokers, invocation); // 返回 List
            return finalInvokers == null ? BitList.emptyList() : finalInvokers;
        } catch (Throwable t) {
            logger.error(CLUSTER_FAILED_SITE_SELECTION, "Failed to execute router", "", "...", t);
            return BitList.emptyList();
        }
    }
    return invokers; // 无路由链：直连场景原样返回
}
```

`StaticDirectory` 与 `RegistryDirectory` 的区别：前者在构造器里 `setInvokers(new BitList<>(invokers))`（`StaticDirectory.java:67`），地址是调用方显式传入的固定集合（直连 / 多 URL），没有注册中心订阅与 `notify` 刷新；后者由注册中心 `notify` 驱动 `toInvokers`/`refreshInvoker` 动态刷新（见上文 [RegistryDirectory Refresh Mechanism](#registrydirectory-refresh-mechanism)）。两者都继承 `AbstractDirectory`，共用 `list → doList → singleRouterChain.route` 这条路由入口。

## Migration Cluster

双注册中心（接口级→应用级）迁移类**不在 `dubbo-cluster` 模块**，而在 `dubbo-registry/dubbo-registry-api` 模块：`MigrationClusterInvoker` 是接口（`dubbo-registry-api/.../migration/MigrationClusterInvoker.java:29`），真正实现是 `MigrationInvoker`。它由 `RegistryProtocol#doRefer` 内部创建（并非 Cluster SPI 项，与 [Cluster](#cluster-implementation-semantics) 篇 Pitfall #17 一致）。

`MigrationInvoker.invoke`（`MigrationInvoker.java:284-312`）把调用在「老（接口级 `invoker`）」与「新（应用级 `serviceDiscoveryInvoker`）」两套 invoker 之间按 migration step 路由，step 常量来自 `MigrationStep` 枚举（`MigrationStep.java:19-22`），仅三个：`FORCE_INTERFACE`、`APPLICATION_FIRST`、`FORCE_APPLICATION`（**没有** `APPLICATION_ONLY` / `INSTANCE_FIRST`）：

```java
// dubbo-registry-api/.../migration/MigrationInvoker.java:284-312（节选）
public Result invoke(Invocation invocation) throws RpcException {
    if (currentAvailableInvoker != null) {
        if (step == APPLICATION_FIRST) {
            // 按 promotion 比例随机：未达阈值则回退到接口级 invoker
            if (promotion < 100 && ThreadLocalRandom.current().nextDouble(100) > promotion)
                return invoker.invoke(invocation);             // 老（接口级）
            return decideInvoker().invoke(invocation);          // 新（应用级），按可用性决策
        }
        return currentAvailableInvoker.invoke(invocation);
    }
    switch (step) {
        case APPLICATION_FIRST:   currentAvailableInvoker = decideInvoker(); break;          // 双模式，按比例/可用
        case FORCE_APPLICATION:   currentAvailableInvoker = serviceDiscoveryInvoker; break;  // 强制新（应用级）
        case FORCE_INTERFACE:     // default
        default:                  currentAvailableInvoker = invoker; break;                  // 强制老（接口级）
    }
    return currentAvailableInvoker.invoke(invocation);
}
```

`decideInvoker()`（`MigrationInvoker.java:314-323`）在 `APPLICATION_FIRST` 下做可用性兜底：当前若是应用级且可用则保留，否则回退到接口级 `invoker`。即迁移过程通过 `step` 在「老接口发现」与「新应用级服务发现」之间平滑切换，`FORCE_INTERFACE` 为默认（保持旧行为）。

## Pitfall List

| # | 说法 | 3.3.6 事实 |
|---|---|---|
| 1 | `RouterChain` 已被 `SingleRouterChain` 取代 | **共存分层**。`RouterChain` 持 main/backup 双链做热切换，`SingleRouterChain` 是内层实现（`RouterChain.java:44`、`SingleRouterChain.java:50`） |
| 2 | `RouterChain.buildChain(URL)` | 签名是 `buildChain(Class<T>, URL)`，且内部建**两条**链（`:52-56`） |
| 3 | `RouterChain` 持有 `List<Invoker<T>>` | 持有 `BitList<Invoker<T>>`（`SingleRouterChain.java:56`） |
| 4 | `Cluster.join(Directory)` 单参 | 多 `boolean buildFilterChain`（`Cluster.java:48`） |
| 5 | `Cluster.getCluster(name)` | 首参是 `ScopeModel`；静态 `ExtensionLoader.getExtensionLoader(Class)` 已 `@Deprecated`（`Cluster.java:50-61`） |
| 6 | `Configurator` 在 `cluster.configurator` 包 | 接口在 `cluster` 包根（`Configurator.java:37`），子包只放实现类 |
| 7 | `Configurator.toConfigurators` 用静态 `ExtensionLoader` | 改为 `urls.get(0).getOrDefaultApplicationModel().getExtensionLoader(...)`（`:75-78`） |
| 8 | `Router` 接口已 `@Deprecated` | 接口**没有**标 `@Deprecated`，只有三参 `route` 标了（`Router.java:55`） |
| 9 | `Router.route` 三参是主入口 | 三参已 `@Deprecated`，主入口是四参返回 `RouterResult`（`:71-74`） |
| 10 | `Router` 没有 `stop()` | 有，`Router.java:109-111`，由 `RouterChain#destroy` 调用 |
| 11 | `ClusterInvoker` 只有 3 个方法 | 还有 `isServiceDiscovery()` / `hasProxyInvokers()` 两个 default（`ClusterInvoker.java:42-56`） |
| 12 | `Directory` 就那几个方法 | 13 个，含 `getRouterChain()` 与三个 Invoker 生命周期方法（`Directory.java:62-100`） |
| 13 | `StateRouter` 有 `getPriority()` | **没有**（`StateRouter.java:39-109`） |
| 14 | 存在 `StateRouterChain` 类 | **不存在**，链载体仍是 `RouterChain` / `SingleRouterChain` |
| 15 | `StateRouter` 自身是独立 SPI | SPI 文件名是 `...router.state.StateRouterFactory`，加载的是工厂而非 `StateRouter` |
| 16 | `StateRouter` 有 `isPool` 之类方法 | 全仓库无匹配 |
| 17 | Cluster 扩展含 `migration` / `FailZoneAwareCluster` / `HealthCheckCluster` | 11 项扩展中**都没有**；`MigrationInvoker` 不是 Cluster SPI 项 |
| 18 | `LoadBalance` SPI 文件在 `...cluster.loadbalance` 下 | 在 `...rpc.cluster.LoadBalance`（按接口 FQN 命名） |
| 19 | legacy `Router` 有内置实现 | 3.3.6 主源码树里 `RouterFactory` **没有 SPI 文件**，`CacheableRouterFactory` **没有子类**，运行时 `routers` 通常为空 |
| 20 | `Directory#discordAddresses` 拼写正确 | 源码即拼作 `discord`（少一个 s），`Directory.java:70` |

## Links

- [Router](/docs/CS/Framework/Dubbo/Router.md)
- [LoadBalance](/docs/CS/Framework/Dubbo/LoadBalance.md)
- [Consumer](/docs/CS/Framework/Dubbo/Consumer.md)
- [Filter](/docs/CS/Framework/Dubbo/Filter.md)
- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)

## References

- [Apache Dubbo 源码 tag dubbo-3.3.6](https://github.com/apache/dubbo/tree/dubbo-3.3.6)
- [RouterChain.java](https://github.com/apache/dubbo/blob/dubbo-3.3.6/dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/RouterChain.java)
- [SingleRouterChain.java](https://github.com/apache/dubbo/blob/dubbo-3.3.6/dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/SingleRouterChain.java)
- [StateRouter.java](https://github.com/apache/dubbo/blob/dubbo-3.3.6/dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/router/state/StateRouter.java)
- [BitList.java](https://github.com/apache/dubbo/blob/dubbo-3.3.6/dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/router/state/BitList.java)
- [Directory.java](https://github.com/apache/dubbo/blob/dubbo-3.3.6/dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/Directory.java)
- [AbstractClusterInvoker.java](https://github.com/apache/dubbo/blob/dubbo-3.3.6/dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/support/AbstractClusterInvoker.java)
- [FailoverClusterInvoker.java](https://github.com/apache/dubbo/blob/dubbo-3.3.6/dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/support/FailoverClusterInvoker.java)
- [ForkingClusterInvoker.java](https://github.com/apache/dubbo/blob/dubbo-3.3.6/dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/support/ForkingClusterInvoker.java)
- [BroadcastClusterInvoker.java](https://github.com/apache/dubbo/blob/dubbo-3.3.6/dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/support/BroadcastClusterInvoker.java)
- [FailbackClusterInvoker.java](https://github.com/apache/dubbo/blob/dubbo-3.3.6/dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/support/FailbackClusterInvoker.java)
- [ZoneAwareClusterInvoker.java](https://github.com/apache/dubbo/blob/dubbo-3.3.6/dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/support/registry/ZoneAwareClusterInvoker.java)
- [MockClusterInvoker.java](https://github.com/apache/dubbo/blob/dubbo-3.3.6/dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/support/wrapper/MockClusterInvoker.java)
- [AbstractCluster.java](https://github.com/apache/dubbo/blob/dubbo-3.3.6/dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/support/wrapper/AbstractCluster.java)
- [ClusterInterceptor.java](https://github.com/apache/dubbo/blob/dubbo-3.3.6/dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/interceptor/ClusterInterceptor.java)
- [RegistryDirectory.java](https://github.com/apache/dubbo/blob/dubbo-3.3.6/dubbo-registry/dubbo-registry-api/src/main/java/org/apache/dubbo/registry/integration/RegistryDirectory.java)
