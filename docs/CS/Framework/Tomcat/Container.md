## Introduction

本篇讲容器四件套（Engine / Host / Context / Wrapper）在 Tomcat 11.0.26 里的**实现机制**，不复述概念定义（定义与类图见 [Tomcat](/docs/CS/Framework/Tomcat/Tomcat.md)），也不重复 `LifecycleBase` 的模板方法流程（见 [Start](/docs/CS/Framework/Tomcat/Start.md)）。聚焦四件事：`ContainerBase` 到底持有什么、子容器增删与生命周期如何递归、请求路径上的名字→容器解析由谁承担、`backgroundProcess` 在容器树上的调度拓扑。

行号引用一律相对 `org/apache/catalina/`，例如 `core/ContainerBase.java:135` 指 `org/apache/catalina/core/ContainerBase.java` 第 135 行，基线 11.0.26。

## Ownership of components

`ContainerBase` 的字段表比任何架构图都可靠，但它的覆盖面远小于「容器有那些组件」这句话给人的印象——**Mapper、Manager、Loader、Resources 都不在 `ContainerBase` 上**：

| 组件 | 实际持有者 | 位置 | 是否向上继承 |
| :--- | :--- | :--- | :--- |
| 子容器集合 | `ContainerBase.children` | `core/ContainerBase.java:135` | 否 |
| Pipeline | `ContainerBase.pipeline`（final，构造即 `new StandardPipeline(this)`） | `core/ContainerBase.java:201` | 否 |
| Realm | `ContainerBase.realm` | `core/ContainerBase.java:207` | 是，`getRealm()` 逐级上溯 |
| Cluster | `ContainerBase.cluster` | `core/ContainerBase.java:176` | 是，`getCluster()` 逐级上溯 |
| parentClassLoader | `ContainerBase.parentClassLoader` | `core/ContainerBase.java:195` | 是，最终回落 `getSystemClassLoader()` |
| AccessLog | `ContainerBase.accessLog`（扫描 pipeline 得出） | `core/ContainerBase.java:237` | 是，`logAccess()` 向父级回溯 |
| Manager（会话） | `StandardContext.manager` | `core/StandardContext.java:403` | 只有 Context 有 |
| Loader（类加载） | `StandardContext.loader` | `core/StandardContext.java:390` | 只有 Context 有 |
| Mapper / MapperListener | `StandardService` | `core/StandardService.java:103,109` | 与容器树平行，不属于任何容器 |

两个 `getXxx()` / `getXxxInternal()` 的区分容易被忽略：公开方法是**带继承语义**的视图（`core/ContainerBase.java:479-494`、`317-333`），`Internal` 变体只返回本容器直接挂载的组件（`502-510`、`341-349`）。`startInternal` 一律用 `Internal` 变体（`719-726`）——否则父容器已启动过的 Realm 会在每个子容器 start 时被重复 start。

`setRealm()` / `setCluster()` 的写法是同一套模式：**写锁内只换引用并调 `setContainer(this)`，stop 旧组件与 start 新组件全部放到锁外**（`core/ContainerBase.java:513-553`、`353-392`）。因为生命周期方法可能回调本容器（例如 Realm 启动时读 `getContainer()`），持锁调用会自锁。

`StandardEngine` 在此之上补了一个兜底：`getRealm()` 若为空则当场 `setRealm(new NullRealm())`（`core/StandardEngine.java:91-101`），所以全树任何层级 `getRealm()` 都不返回 null。

## Child container map and names

```java
    /**
     * The child Containers belonging to this Container, keyed by name.
     */
    protected final HashMap<String,Container> children = new HashMap<>();
    private final ReadWriteLock childrenLock = new ReentrantReadWriteLock();
```

普通 `HashMap` + `ReentrantReadWriteLock`，而不是 `ConcurrentHashMap`：读多写少但要保证 `findChildren()` 快照一致性（`core/ContainerBase.java:618-625`）。同一把锁的选择在 `listeners` 上反过来——那里是 `CopyOnWriteArrayList`，源码注释给出理由：监听器回调里可能增删自己或其他监听器，读写锁会死锁（`core/ContainerBase.java:155-159`）。

名字在四层的含义不同，`children` 的 key 就是它：Host 用（小写化的）域名，Context 用路径或 `##name`（部署期临时名），Wrapper 用 servlet-name。`getLogName()` 沿 `getParent()` 逐级拼接并把空名替换为 `/`、`##` 前缀补 `/`（`core/ContainerBase.java:293-313`），`toString()` 则递归父级生成 `StandardEngine[engine].StandardHost[localhost]...` 形式（`1108-1121`）——日志与 JMX ObjectName 的可读性都来自这两个方法。

## Boundaries of addChild and removeChild

`addChild` 的顺序值得逐行看（`core/ContainerBase.java:559-588`）：

1. 写锁内查重（同名直接 `IllegalArgumentException`）→ `child.setParent(this)` → 入表；
2. 锁外 `fireContainerEvent(ADD_CHILD_EVENT, child)`；
3. 锁外 `child.start()`，条件是父容器 `isAvailable()` 或处于 `STARTING_PREP`，且 `startChildren` 为真；失败包成 `IllegalStateException`。

第 2、3 步在锁外是刻意的，源码注释写明 start 很慢且持锁会引发别处问题。**事件先于 start**，这正是 [Valve](/docs/CS/Framework/Tomcat/Valve.md) 之外另一条装配通道——`MapperListener` 靠这个事件在子容器已启动的情况下补登记。

`removeChild` 是反向的：先 `stop()`，再 `destroy()`（若子容器已处于 `DESTROYING` 则跳过，避免 `destroyInternal` 触发的回调重入，`core/ContainerBase.java:649-658`），最后才摘表并 `fireContainerEvent(REMOVE_CHILD_EVENT)`。**摘表放最后**意味着 stop 期间 `findChild()` 仍能查到该容器。

四层的约束靠覆写实现，报错类型并不统一：

| 容器 | 覆写 | 允许的子容器 | 额外动作 |
| :--- | :--- | :--- | :--- |
| Engine | `core/StandardEngine.java:158-166` | 仅 `Host`，否则 `IllegalArgumentException` | `setParent()` 直接抛异常，Engine 必须是根（`175-180`） |
| Host | `core/StandardHost.java:662-674` | 仅 `Context` | 给子 Context 挂 `MemoryLeakTrackingListener`；`path` 为空时从 `docBase` 反推 |
| Context | `core/StandardContext.java:2814-2845` | 仅 `Wrapper` | 子节点名为 `jsp` 时先摘掉继承自全局 web.xml 的旧 Wrapper，并把它的 mappings 转交给新的 |
| Wrapper | `core/StandardWrapper.java:516-520` | 无 | 抛 `IllegalStateException`（接口 javadoc 建议的是 `IllegalArgumentException`，实现没照做） |

Wrapper 侧还有一条：`setParent()` 要求父必须是 `Context`，并顺带从 Context 继承 `swallowOutput` 与 `unloadDelay`（`core/StandardWrapper.java:334-346`）。

## Lifecycle recursion

`ContainerBase.startInternal()`（`core/ContainerBase.java:711-766`）的顺序是这份清单，值得注意的是**子容器在 pipeline 之前启动**：

| 步骤 | 内容 | 位置 |
| :--- | :--- | :--- |
| 1 | `reconfigureStartStopExecutor(getStartStopThreads())` | `:714` |
| 2 | start 本容器的 Cluster、Realm（Internal 变体） | `:719-726` |
| 3 | 把每个子容器的 `start()` 提交给 `startStopExecutor`，逐个 `Future.get()` 收结果 | `:729-748` |
| 4 | 有失败则合并成 `MultiThrowable` 抛出 | `:735-752` |
| 5 | start pipeline（含 basic valve） | `:754-757` |
| 6 | `setState(LifecycleState.STARTING)` | `:759` |
| 7 | 若 `backgroundProcessorDelay > 0`，只挂一个每 60 s 跑一次的 monitor，**不直接起后台线程** | `:761-765` |

第 3、4 步合起来解释了一个常见现象：一台机器上 30 个 webapp，只挂掉 1 个时其他仍然正常完成初始化，错误在末尾一次性聚合抛出。

第 1 步是并行启动的开关：`startStopThreads` 默认 1（`core/ContainerBase.java:244`），此时 executor 是 `InlineExecutorService`——`submit()` 在当前栈上直接跑，等价串行；设为 `>1` 时改为向 `Server` 申请共享工具线程池，并**顺手把 `Server.utilityThreads` 调到同一数量**（`core/ContainerBase.java:689-701`）。也就是说 Engine/Host 上的 `startStopThreads` 会重定义整个进程的后台调度池，而那个池默认只有 2 个线程（`core/StandardServer.java:179`、`403`）。

`stopInternal()`（`:776-828`）是镜像但**顺序相反**：取消 monitor → `threadStop()` → `setState(STOPPING)` → stop pipeline → 并发 stop 子容器 → stop Realm/Cluster → `startStopExecutor.shutdownNow()`。先停 pipeline 再停子容器，意味着 stop 一开始请求就被挡在容器之外。`destroyInternal()`（`:830-858`）除销毁 Realm/Cluster/pipeline 外还做两件事：把所有子容器 `removeChild`，以及**若还有父容器则主动 `parent.removeChild(this)`**（`:853-855`），保证被直接 destroy 的容器不会在父表里留尸体。

## Two name-to-container resolutions

同一棵容器树有两套寻址路径，混淆它们是读 Tomcat 源码最常见的弯路。

第一套是**静态寻址**：`findChild(name)` 走 `children`（`core/ContainerBase.java:604-614`），供管理代码与 JMX 用，与 URL 无关。

第二套是**请求寻址**，由 `Mapper` 承担。`Mapper` 挂在 `StandardService` 上（`core/StandardService.java:103`），`CoyoteAdapter.postParseRequest` 通过 `connector.getService().getMapper().map(serverName, decodedURI, version, request.getMappingData())` 调用它（`connector/CoyoteAdapter.java:700`）。映射结果写进 `MappingData`，而 `Request.getHost()` / `getContext()` / `getWrapper()` 只是 `mappingData` 的三个字段的视图（`connector/Request.java:614,659,785`）。**所以四层 basic valve 都不做映射**，它们只从 `mappingData` 取下一级容器再进它的 pipeline——链路细节见 [Connector](/docs/CS/Framework/Tomcat/Connector.md)。

`Mapper` 内部结构是三级有序数组：`MappedHost[]` → `ContextList`/`MappedContext` → `ContextVersion[]` → `MappedWrapper[]`，查找用二分（`mapper/Mapper.java:1151` 起的 `find()`、`1306` 起的 `exactFind()`）。中间那层 `ContextVersion` 是并行部署（同一 `contextPath` 多版本共存）的根基：`versions` 数组按注册顺序排列，`map()` 默认返回最后一个即最新版本（`mapper/Mapper.java:820-837`）。

`Mapper` 的数据全部来自容器树的事件推送，登记方是同样挂在 Service 上的 `MapperListener`（`core/StandardService.java:109`）。它在 start 时把自己注册成 Engine 的 `ContainerListener` 与 `LifecycleListener`（`mapper/MapperListener.java:482-483`），随后按下表翻译事件：

| 容器侧动作 | 事件 | MapperListener 处理 |
| :--- | :--- | :--- |
| `addChild` 且子容器已可用 | `ADD_CHILD_EVENT` | 立即按 Host / Context / Wrapper 补登记（`mapper/MapperListener.java:141-159`） |
| Host 增删别名 | `Host.ADD_ALIAS_EVENT` | `mapper.addHostAlias()`（`:164-169`） |
| Wrapper 增删 URL pattern | `Wrapper.ADD_MAPPING_EVENT` | `mapper.addWrapper(...)`，并识别 `jsp` + `/*` 的 wildcard（`:170-184`） |
| Context 增删 welcome file | `Context.ADD_WELCOME_FILE_EVENT` | `mapper.addWelcomeFile()`（`:200-214`） |
| Context start / stop | 生命周期事件 | `addContextVersion()`（`:372`）/ `unregisterContext()`（`:384-405`） |

`Wrapper` 层的匹配优先级在 `internalMapWrapper()`（`mapper/Mapper.java:853` 起）：精确匹配 → 最长路径前缀 → 扩展名 → 默认 servlet。

## Context load sequence

`StandardContext.startInternal()`（`core/StandardContext.java:4388` 起）是整棵树里最长的一段启动逻辑，挑出与容器机制相关的节点：

| 阶段 | 内容 | 位置 |
| :--- | :--- | :--- |
| 资源 | 无 `WebResourceRoot` 时建 `StandardRoot` 并 start | `:4419-4427` |
| 类加载 | `getLoader() == null` 时补 `WebappLoader`，继承 `delegate` | `:4430-4434` |
| 子容器 | 未可用的 Wrapper 逐个 `child.start()`（绕开 `ContainerBase` 的并发路径） | `:4526-4531` |
| Pipeline | start 本容器 pipeline | `:4533-4536` |
| 会话 | Manager 为空时按 Cluster + `distributable` 决定用哪个实现 | `:4540-4560` |
| 实例化设施 | `InstanceManager` 缺省为 `DefaultInstanceManager`，同时写进 ServletContext 并绑定到 Webapp 类加载器 | `:4583-4587`、`4712-4719` |
| 过滤器 | `filterStart()` | `:4642-4646` |
| 预加载 | `loadOnStartup(findChildren())` | `:4650-4654` |
| 后台 | `super.threadStart()` | `:4657` |

第 3 行背后的事实是：**四类容器里只有 `StandardContext` 重写了启停且不回调 `super.startInternal()` / `super.stopInternal()`**（Engine `core/StandardEngine.java:201`、Host `core/StandardHost.java:794`、Wrapper `core/StandardWrapper.java:1186`、`:1225` 都回调了；Context 只在 `initInternal` `:5590` 与 `destroyInternal` `:4953` 回调）。后果有三个，都只能从「没走父类那段代码」推出来：

- 子 Wrapper 的启动发生在当前线程（`:4526-4531` 的 `for` 循环），Context 上的 `startStopThreads` 实际无意义——`reconfigureStartStopExecutor()` 只在 `ContainerBase.startInternal()` 里被调用；Wrapper 通常早已在 `addChild` 阶段被自动启动（`core/ContainerBase.java:582-584` 允许 `STARTING_PREP` 状态下启动子容器，而 `ContextConfig` 正是在这个阶段解析 web.xml）。
- Realm 由 Context 自己启动（`:4499-4503`），而 **Cluster 不在这里启动**，它依赖父容器的递归或 `setCluster()` 的即时启动。
- `setState(STARTING)` 的位置也不同：Context 在整段逻辑的最后（`:4697`），失败路径显式 `setState(FAILED)`（`:4689`）。

## Wrapper hosts Servlets

Wrapper 与上层最大的差别是它**只有一个实例**：`instance` 是 `volatile Servlet`（`core/StandardWrapper.java:123`），`allocate()`（`:568-612`）在双检锁里 `loadServlet()` + `initServlet()`，并用 `countAllocated` 计数（`:111`）。`loadServlet()`（`:735` 起）不自己 `Class.forName`，而是取父 Context 的 `InstanceManager.newInstance(servletClass)`（`:756-758`）——DI 注入与 `ContainerServlet` 回调都发生在这条统一路径上（`:783-789`）。

Wrapper 自带一个三态可用性字段 `available`（`:101`）：0 表示可用，`Long.MAX_VALUE` 表示永久不可用，中间值是「某个时间点后才恢复」。

| 触发 | 结果 | 位置 |
| :--- | :--- | :--- |
| `startInternal()` | `setAvailable(0L)` | `:1188` |
| `stopInternal()` | `setAvailable(Long.MAX_VALUE)` | `:1209` |
| `init()` 抛 `UnavailableException`（非永久） | `now + unavailableSeconds*1000`，秒数非正时兜底 60 s | `:887-901` |
| 永久不可用或加载失败 | `Long.MAX_VALUE` | `:890-892` |

响应映射在 `StandardWrapperValve.checkWrapperAvailable()`：临时不可用 → 503 并写 `Retry-After`；永久不可用 → 404。`isUnavailable()`（`:397-407`）读的时候顺带把到期时间归零，因此恢复是被动的、无需后台任务。

`load-on-startup` 的排序语义在 `StandardContext.loadOnStartup()`（`core/StandardContext.java:4349-4383`）：用 `TreeMap<Integer,List<Wrapper>>` 按值升序，同值按 `findChildren()` 顺序；单个 servlet 初始化失败默认**不阻断** Context 启动，除非 `failCtxIfServletStartFails="true"`。

## backgroundProcess scheduling topology

`ContainerBase` 的周期任务有两个 future，容易只看一个就得出错误结论：

| future | 由谁排程 | 周期 | 干什么 |
| :--- | :--- | :--- | :--- |
| `monitorFuture` | `startInternal()` 且仅当 `backgroundProcessorDelay > 0` | 60 s | `ContainerBackgroundProcessorMonitor` → 容器仍可用则调 `threadStart()`（`:1128-1141`） |
| `backgroundProcessorFuture` | `threadStart()`（`:1078-1094`） | `backgroundProcessorDelay` 秒 | `ContainerBackgroundProcessor` → `processChildren(this)` 递归（`:1147-1195`） |

默认值决定了拓扑：`ContainerBase.backgroundProcessorDelay = -1`（`:142`），只有 `StandardEngine` 构造里写成 10（`core/StandardEngine.java:62`）。**因此正常情况下全树只有一条后台任务**，由 Engine 提交到 Server 的工具线程池，向下递归覆盖 Host/Context/Wrapper；`processChildren` 递归时对 `child.getBackgroundProcessorDelay() > 0` 的子容器直接跳过（`:1182`），留给它自己的线程。递归进入 Context 时先 `bind(null)` 把 TCCL 切到 Webapp 类加载器，退出时 `unbind`（`:1168-1193`）——这是「Wrapper 里的 `PeriodicEventListener` 能加载应用类」的前提。

`backgroundProcess()` 本体与各层覆写已在 [memory](/docs/CS/Framework/Tomcat/memory.md) 与 [Tomcat](/docs/CS/Framework/Tomcat/Tomcat.md) 贴过，这里只按分工归纳：

| 层级 / 组件 | 周期任务 | 位置 |
| :--- | :--- | :--- |
| `ContainerBase` | Cluster → Realm → **逐个 Valve** → `PERIODIC_EVENT` | `core/ContainerBase.java:924-957` |
| `StandardContext` | Loader / Manager / Resources / InstanceManager，最后 `super` | `core/StandardContext.java:4958-4997` |
| `StandardWrapper` | 实现了 `PeriodicEventListener` 的 servlet 回调 | `core/StandardWrapper.java:474-484` |
| `WebappLoader` | `reloadable` 且类文件变化 → `context.reload()` | `loader/WebappLoader.java:230` |
| `AccessLogValve` | 缓冲刷盘、按日轮转、`maxDays` 清理 | `valves/AccessLogValve.java:380-420` |
| `HostConfig` | 监听 `PERIODIC_EVENT` → `check()` 热部署 | `startup/HostConfig.java:284` |

两条推论：其一，Valve 的 `backgroundProcess()` 只在**其所属容器被递归覆盖到**时才执行，所以挂在自管 delay 的 Context 之外的 Valve 不会被漏掉，但反过来挂在一个 delay>0 的 Context 里的 Valve 也不会被 Engine 的递归看到；其二，`Server` 自己另有一条 `PERIODIC_EVENT` 源（`core/StandardServer.java:881-896`），与容器树那条互不相干。

## Pause and drain

Context 级摘流是「reload 期间不丢请求」的实现，链路跨四个文件，`StandardContext.setPaused()` 只是起点：

1. `paused` 是 `volatile boolean`（`core/StandardContext.java:439`），`setPaused()` 是**私有**方法（`:5506-5512`），唯一调用方是 `reload()`（`:3391-3423`）：置 true → `stop()` → `start()` → 置 false。
2. `Context` 接口对外只读：`getPaused()`（`Context.java:1472`、实现 `core/StandardContext.java:5292`）。
3. stop 触发生命周期事件，`MapperListener.unregisterContext()` 分叉：`getPaused()` 为真调 `mapper.pauseContextVersion(...)`，否则调 `removeContextVersion(...)`（`mapper/MapperListener.java:384-405`）。
4. `Mapper.pauseContextVersion()` 找到对应 `ContextVersion` 并 `markPaused()`（`mapper/Mapper.java:378-385`），标记位是 `ContextVersion` 上的 `volatile boolean paused`（`:1805`、`1838-1840`）。

效果分两处。`Mapper.internalMap()` 命中 context 后**跳过 wrapper 映射**（`mapper/Mapper.java:840-842`），于是 `mappingData.wrapper` 为空；`CoyoteAdapter` 发现映射到的 context 处于 paused，就 `Thread.sleep(1000)` → `mappingData.recycle()` → 再映射，把请求原地压在循环里直到新版本注册（`connector/CoyoteAdapter.java:782-793`）。`reload()` 的 javadoc 也特意提示了这段适配器代码的存在（`core/StandardContext.java:3388`）。

要区分两种「不再接新流量」：这条链路是**进程内 reload 的短暂阻塞**，对客户端表现为变慢；把会话作废并 307 重定向给负载均衡器是 [Valve](/docs/CS/Framework/Tomcat/Valve.md) 里 `LoadBalancerDrainingValve` 的职责。

## Loader and the container tree

`Loader` 只与 Context 有关系：`setLoader()` 在写锁内 `loader.setContext(this)`，锁外做旧 stop / 新 start（`core/StandardContext.java:1879-1917`），`destroyInternal()` 负责销毁（`:4939-4943`）。类加载器层次与 `delegate` 语义见 [ClassLoader](/docs/CS/Framework/Tomcat/ClassLoader.md)；容器侧只提供两个衔接点——`ContainerBase.parentClassLoader` 的逐级上溯（`core/ContainerBase.java:452-460`）与 TCCL 的绑定/解绑时机（Host 的 basic valve、后台递归的 `processChildren`）。

## What no longer exists in 11

搜源码时不要指望这些符号：`Globals.IS_SECURITY_ENABLED`、`AccessController.doPrivileged`、`PermissionCheck` 在 11.0.26 的 catalina 与 util 两棵树里已全部消失（SecurityManager 支持被移除），`ContainerBase` 相应地也没有 `stateInfo`/`AccessController` 包裹的分支。同样，`PipelineBase` 这个类名已不存在——`ContainerBase.pipeline` 直接是 `StandardPipeline`（`core/ContainerBase.java:201`），旧的 `PipelineBase` 实现细节都并进了它。

## Links

- [Tomcat](/docs/CS/Framework/Tomcat/Tomcat.md)
- [Valve](/docs/CS/Framework/Tomcat/Valve.md)
- [Connector](/docs/CS/Framework/Tomcat/Connector.md)
- [Start](/docs/CS/Framework/Tomcat/Start.md)
- [ClassLoader](/docs/CS/Framework/Tomcat/ClassLoader.md)
- [memory](/docs/CS/Framework/Tomcat/memory.md)

## References

1. [Tomcat 11.0 Configuration Reference: Engine](https://tomcat.apache.org/tomcat-11.0-doc/config/engine.html)
2. [Tomcat 11.0 Configuration Reference: Host](https://tomcat.apache.org/tomcat-11.0-doc/config/host.html)
3. [Tomcat 11.0 Configuration Reference: Context](https://tomcat.apache.org/tomcat-11.0-doc/config/context.html)
4. [Tomcat Cluster How-To](https://tomcat.apache.org/tomcat-11.0-doc/cluster-howto.html)
5. [ContainerBase Javadoc (11.0)](https://tomcat.apache.org/tomcat-11.0-doc/api/org/apache/catalina/core/ContainerBase.html)
