## Introduction

Java 三大 Web 容器（Tomcat / Jetty / Undertow）的对比资料绝大多数停在两个问题上：「谁快」和「谁省内存」。这两个问题都没有稳定答案——它们都是同一代 benchmark 的产物，而三家的线程模型这些年各自改了两到三轮。

真正决定选型的是另外三个维度，且都能从源码里读出确定答案：

1. **Servlet 依赖在架构里的位置**——决定你能不能把它当纯 HTTP 库用、以及规范升级时它怎么变。
2. **线程与「切换时机」的所有权**——决定阻塞代码会不会打死事件循环、以及虚拟线程能不能救你。
3. **版本线怎么切**——决定升级是换 jar 还是换编程模型。

> [!NOTE]
> 第一性的选型问题是：**你的应用里阻塞调用有多普遍**。全是 JDBC / 远程 RPC / 文件 IO，就选把线程成本做得最低的那个；真能做到端到端非阻塞，才轮到比谁的单位连接开销小。

## Version baseline

三家版本均为 2026-10 从 Maven Central `<release>` 实测，字节码基线从各自主构件 `.class` 头 8 字节读出。

| 维度 | Tomcat | Jetty | Undertow |
| :-- | :-- | :-- | :-- |
| 当前版本 | 11.0.26 | 12.1.14 | core 2.4.4.Final / servlet 2.3.26.Final |
| 并行版本线 | 9.0.x、10.1.x、11.0.x 三线 | 12.0.x（安全）+ 12.1.x（特性），另有 ee8/ee9/ee10/ee11 四层 | 单线 2.x，**不存在 3.x** |
| 字节码基线 | Java 17（major 61） | Java 17（major 61） | core Java 17（61）、servlet **Java 11（55）** |
| Servlet 层 | 6.1（`jakarta.servlet`） | ee10 = 6.0 / ee11 = 6.1 双栈并存 | `jakarta.*`，但**未追平 Servlet 6.1** |
| 模块版本一致性 | 全线统一（catalina/coyote/jasper 同为 11.0.26） | 全线统一（含 ee10/ee11/http2/websocket） | **core 与 servlet 脱节一个 minor 线** |
| 维护方 | Apache 软件基金会 | Eclipse 基金会 | Red Hat / JBoss |

两点值得单独强调。**Undertow 的 core 与 servlet 模块不同步发布**，且连字节码基线都不一致（servlet 仍停在 Java 11），所以「升 Undertow」实际是升两条独立节奏；**Jetty 的 eeNN 分层意味着规范代次是正交维度**，同一进程里可以 ee10 与 ee11 应用并置，这是另外两家没有的形态。

## Where the Servlet dependency sits

三家恰好构成一条光谱的三个刻度：

| | Tomcat | Jetty 12 | Undertow |
| :-- | :-- | :-- | :-- |
| 核心是否引用 Servlet API | 是，Catalina 直接实现 | **编译期禁止**：`jetty-server/module-info.java` 不 `requires jakarta.servlet` | 完全不知道 Servlet 存在 |
| Servlet 以什么形态存在 | 与容器同时进内核 | 叠在核心之上的 `ee10`/`ee11` 模块 | 叠在核心之上的 `undertow-servlet` 部署器 |
| 挂载点 | `CoyoteAdapter` 把协议层对象适配成 Servlet 请求 | `ServletContextHandler` 覆写核心 `ContextHandler.wrapRequest` | `ServletInitialHandler implements HttpHandler`，`start()` 返回一个 handler |
| 不用 Servlet 时的代价 | 仍带整个 Catalina | 只用核心，无 Servlet 依赖 | 只用核心 |
| JSP | 内置 Jasper | 需外部 jasper 适配模块 | 无，独立 `jastow` 构件线 |

**结论：Jetty 12 与 Undertow 都能做到「HTTP 服务器里没有 Servlet 类型」，Tomcat 不能。** 差别在语义上而非包大小：Jetty 是靠 module-info 把这件事变成编译期约束（想违规就编译不过），Undertow 是因为核心从来只做 exchange 抽象。Tomcat 的代价是每次 Jakarta EE 代次跃迁都要整体重编（10.x 的 `javax` → `jakarta` 迁移即为此），好处是「一个 jar 什么都有」的部署便利。

深入：[Jetty EeLayer](/docs/CS/Framework/Jetty/EeLayer.md)、[Undertow Servlet](/docs/CS/Framework/Undertow/Servlet.md)、[Tomcat Container](/docs/CS/Framework/Tomcat/Container.md)。

## Threading model and switch point

这是三家差异最大、也最容易被旧资料误导的一维。

| | Tomcat 11.0.26 | Jetty 12.1.14 | Undertow 2.4.4 |
| :-- | :-- | :-- | :-- |
| 接连接 | Acceptor 线程 + `LimitLatch`（`maxConnections` 默认 **8192**，`AbstractEndpoint:1016`） | acceptor **默认恒为 1 个**，且是提交到 Executor 的任务（`AbstractConnector:199-204`、`:321-330`） | XNIO 独立 `XNIO-1 Accept` 线程（`NioXnioWorker:84-119`） |
| 事件循环 | Poller（`-Poller` 线程，`NioEndpoint:541`） | selectors，数量 `max(1, min(cpus/2, threads/16))`（`SelectorManager:70-79`） | IO 线程 `max(cpus, 2)`（`Undertow:447-449`） |
| 工作线程 | processor 池，`maxThreads` 200 + `TaskQueue` 的「先扩线程后入队」技巧 | `QueuedThreadPool` 默认 200 + `AdaptiveExecutionStrategy`（旧名 EatWhatYouKill） | worker = `ioThreads * 8`，由 XNIO 的 `EnhancedQueueExecutor` 承载 |
| 谁决定 handler 跑在哪 | processor 状态机（协程式 `action` 循环） | **事件方法返回 `Runnable`**，调用方就地决定；`_handling` CAS 决定要不要让出（`HttpConnection:416-452`） | **集中一处**：handler 栈返回时由 `Connectors.executeRootHandler` 看 `FLAG_DISPATCHED` 决定（`:319-351`） |
| 阻塞代码的后果 | 占住工作线程，池满即排队 | 占住 QTP 线程；策略会尽量把生产交回别的线程 | 裸 core 会**占住 IO 线程**；Servlet 层已默认 dispatch 到 worker |
| 虚拟线程 | 有：`useVirtualThreads`（`AbstractEndpoint:1094`，默认 false）→ `VirtualThreadExecutor`，线程名 `-virt-` | 有：`VirtualThreadPool` + `VirtualThreads.Configurable`（**没有** `VirtualThreadExecutor` 这个类） | **无**：core 2.4.4 全镜像 `virtualthread` 零命中 |

三条判断：

第一，**「Jetty 的 acceptor 数量按 CPU 推导」已经不成立**，12 里默认恒为 1，CPU 只用来给越界配置打 WARN；Undertow 的 `max(cpus,2)` 说的是 IO 线程而非 accept 线程。带着旧公式去调参，会得出完全错误的容量结论。

第二，虚拟线程这一行是**当前最实用的分岔**。Tomcat 与 Jetty 都给了官方逃生口（各自实现不同：Tomcat 走 `JreCompat` 反射以保持基线以下可加载，Jetty 走 `VirtualThreads` 探测 + 可替换的 `ThreadPool` 实现），而 Undertow 没有——它的答复是「别在 IO 线程上阻塞」。若技术栈是阻塞 JDBC 且并发高，Undertow 需要自己配足 worker 线程，而另两家可以一行配置换掉整个池。

第三，Undertow「Servlet 请求默认不在 IO 线程」这一点常被忽略，却是它作为 Boot/WildFly 内层能稳定服务混合负载的原因（`ServletInitialHandler:176`）。

深入：[Tomcat threads](/docs/CS/Framework/Tomcat/threads.md)、[Jetty Threading](/docs/CS/Framework/Jetty/Threading.md)、[Undertow XNIO](/docs/CS/Framework/Undertow/XNIO.md)、[Undertow Exchange](/docs/CS/Framework/Undertow/Exchange.md)。

## Extension points and wiring

| | Tomcat | Jetty 12 | Undertow |
| :-- | :-- | :-- | :-- |
| 单位抽象 | `Valve`（挂在 `Pipeline`，按容器层级装配） | `Handler`（树形，`Sequence`/`Singleton`/`Wrapper`） | `HttpHandler`（单方法接口 + `HandlerWrapper`） |
| 顺序控制 | `StandardPipeline.addValve` **只能插到 basic 之前**，无前插 API | `insertHandler` / `relinkHandlers`，`setHandler` 误用会 WARN | 自己 new 出 wrapper 链，无注册表 |
| 声明式配置 | `server.xml` + Digester | `XmlConfiguration`（DTD 仍停在 `configure_10_0`）+ 发行版 `jetty-start` 的 module/ini | `Predicate` DSL（`PredicatedHandlersParser` 递归下降 + ServiceLoader 扩展） |
| 生命周期托管 | `LifecycleBase` 状态机 + MBean | `ContainerLifeCycle` bean 管理（AUTO 托管启发式） | 无统一容器模型，靠 `Undertow.start()/stop()` |
| 典型可观测扩展 | `AccessLogValve` 家族、`HealthCheckValve` | `StatisticsHandler`、`ConnectionStatistics`、`CustomRequestLog` | `ConnectorStatisticsImpl` + `ENABLE_STATISTICS`（默认 false） |

**Undertow 的 predicate DSL 是三家里独一份**：把「条件 + 动作」写成字符串并在运行时重扫（`PredicatesHandler` 的 `CURRENT_POSITION`/`DONE`/`RESTART` 三 attachment 实现可重入两遍扫描），代价是这类逻辑脱离了类型检查。Jetty 的差别在于它是唯一把「handler 是否允许阻塞」编码成类型（`InvocationType`）并据此决定调度行为的容器。

## Selection tendencies

| 场景 | 倾向 | 依据 |
| :-- | :-- | :-- |
| 传统 Servlet/JSP 单体、要「一个包跑起来」 | Tomcat | 规范完整度最高，JSP/Cluster/Realm 全内置 |
| Spring Boot（当前代次） | Tomcat 默认，Jetty 可选 | Boot 4 已不再支持 Undertow（见 [WebFlux](/docs/CS/Framework/Spring/webflux.md) 的口径） |
| 阻塞式业务 + JDK 21+ + 高并发 | Tomcat 或 Jetty | 两家都有官方虚拟线程开关；Undertow 无 |
| 需要同一进程并存两种 Jakarta EE 代次 | Jetty | ee10 / ee11 模块平行镜像 |
| 只要一个嵌入式 HTTP 库、自己写 handler | Undertow | 核心无 Servlet 概念，`Undertow.builder()` 即可用 |
| WildFly / 受管 Java EE 应用服务器内部 | Undertow | 它的实际部署形态 |
| 端到端真非阻塞（流式、背压、大量下游） | Jetty 或 Undertow | 事件驱动抽象更贴近该模型（`Content.Source` 的 read/demand、exchange 的 conduit） |

## Trap list

这些是「凭旧印象写必错」的具体位置，全部已在源码上复核：

- Tomcat：`AbstractJsseEndpoint` 与 APR connector 已从 coyote 消失；`maxConnections` 10000 是已删 APR 的默认值（现为 8192）；HTTP/2 server push 移除；`prestartminSpareThreads` 属性删除（预启动改为构造函数里无条件执行）；SecurityManager 分支整体不存在；`protocolHandlerVirtualThreadExecutorDefault` 这个常被引用的属性名零命中。见 [Version_Migration](/docs/CS/Framework/Tomcat/Version_Migration.md)。
- Jetty：`ParseResult`/`ParseState` 在 12 已删除；`EatWhatYouKill` 改名 `AdaptiveExecutionStrategy`；`HandlerContainer` 退化成空标记接口；`selectKeepAlive` 不存在；HTTP/2 artifact 在 12.1 从 `http2-server` 改名为 `jetty-http2-server`（旧坐标最新只到 11.0.26，拿它会掉回 Jetty 11）；`module`/`start.d` 属于发行版启动器而非库。
- Undertow：`NextHandler`、`exchange.complete()`、`CompleteState` 三个名字都不存在；`protocols/http/HttpRequestParser` 已被手写 `RequestParser` 取代；`DeploymentManager.create()` 不再是正确入口；`DeploymentInfo.setStatisticsEnabled` 不存在（只剩 `setMetricsCollector`）；`org.xnio.Options.MAX_PARAMETERS` 在 XNIO 3.8 已无；jboss-threads 3.x 无 `FixedSizeThreadPool`；ALPN 只剩 JDK 与 OpenSSL 两个提供方（`JettyAlpnProvider` 时代结束）。

## Links

- [Tomcat](/docs/CS/Framework/Tomcat/Tomcat.md)
- [Jetty](/docs/CS/Framework/Jetty/Jetty.md)
- [Undertow](/docs/CS/Framework/Undertow/Undertow.md)
- [Jetty Threading](/docs/CS/Framework/Jetty/Threading.md)
- [Undertow Exchange](/docs/CS/Framework/Undertow/Exchange.md)
- [Tomcat Version_Migration](/docs/CS/Framework/Tomcat/Version_Migration.md)

## References

- [Apache Tomcat 版本对照](https://tomcat.apache.org/whichversion.html)
- [Eclipse Jetty 文档](https://jetty.org/docs/)
- [Undertow 官方站点](https://undertow.io/)
- [Jakarta EE 11 规范](https://jakarta.ee/release/11/)
