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
