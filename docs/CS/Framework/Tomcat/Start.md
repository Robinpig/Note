## Introduction

Tomcat startup using two classes in the `org.apache.catalina.startup` package, Catalina and Bootstrap.
The Catalina class is used to start and stop a Server object as well as parse the Tomcat configuration file, server.xml.
The Bootstrap class is the entry point that creates an instance of Catalina and calls its methods.
In theory, these two classes could have been merged.
However, to support more than one mode of running Tomcat, a number of bootstrap classes are provided.
For example, the aforementioned Bootstrap class is used for running Tomcat as a stand-alone application.

For user's convenience, Tomcat also comes with the batch files and shell scripts to start and stop the servlet container easily.
With the help of these batch files and shell scripts, the user does not need to remember the options for the java program to run the Bootstrap class.
Instead, he/she can just run the appropriate batch file or shell script.

本页按 **Tomcat 11.0.26** 重写。启动链路的结构多年未变（Bootstrap 反射驱动 Catalina，Catalina 驱动 Lifecycle 状态机），但四处细节已经与旧资料对不上：`Bootstrap.main` 从 if 链改成了 `switch` 且新增 `startd`/`stopd`/`configtest` 命令；`Catalina.load()` 的 server.xml 解析被抽成 `parseServerXml(boolean)` 并支持预编译的生成代码；`StandardServer.initInternal` 里成段的 `ExtensionValidator` 循环随该类一起消失；`Reloader` 接口删除、`reloadable` 归属 Context。逐条对照见 [Version_Migration](/docs/CS/Framework/Tomcat/Version_Migration.md)。

## Lifecycle

Common interface for component life cycle methods.
Catalina components may implement this interface (as well as the appropriate interface(s) for the functionality they support) in order to *provide a consistent mechanism to start and stop the component*.

The valid state transitions for components that support Lifecycle are:

```
            start()
  -----------------------------
  |                           |
  | init()                    |
 NEW -»-- INITIALIZING        |
 | |           |              |     ------------------«-----------------------
 | |           |auto          |     |                                        |
 | |          \|/    start() \|/   \|/     auto          auto         stop() |
 | |      INITIALIZED --»-- STARTING_PREP --»- STARTING --»- STARTED --»---  |
 | |         |                                                            |  |
 | |destroy()|                                                            |  |
 | --»-----«--    ------------------------«--------------------------------  ^
 |     |          |                                                          |
 |     |         \|/          auto                 auto              start() |
 |     |     STOPPING_PREP ----»---- STOPPING ------»----- STOPPED -----»-----
 |    \|/                               ^                     |  ^
 |     |               stop()           |                     |  |
 |     |       --------------------------                     |  |
 |     |       |                                              |  |
 |     |       |    destroy()                       destroy() |  |
 |     |    FAILED ----»------ DESTROYING ---«-----------------  |
 |     |                        ^     |                          |
 |     |     destroy()          |     |auto                      |
 |     --------»-----------------    \|/                         |
 |                                 DESTROYED                     |
 |                                                               |
 |                            stop()                             |
 ----»-----------------------------»------------------------------

```

Any state can transition to FAILED.

- Calling start() while a component is in states STARTING_PREP, STARTING or STARTED has no effect.
- Calling start() while a component is in state NEW will cause init() to be called immediately after the start() method is entered.
- Calling stop() while a component is in states STOPPING_PREP, STOPPING or STOPPED has no effect.
- Calling stop() while a component is in state NEW transitions the component to STOPPED.
  This is typically encountered when a component fails to start and does not start all its sub-components.
  When the component is stopped, it will try to stop all sub-components - even those it didn't start.

这张状态图来自 `LifecycleBase` 的 javadoc，在 11 仍是权威版本。但要配合 11 `stop()` 里新增的两个守卫一起读，见 [stopInternal](/docs/CS/Framework/Tomcat/Start.md?id=stopinternal)。

事件常量在 11 一共 **13 个**（`Lifecycle.java`）：`BEFORE_INIT_EVENT` / `AFTER_INIT_EVENT` / `BEFORE_START_EVENT` / `START_EVENT` / `AFTER_START_EVENT` / `BEFORE_STOP_EVENT` / `STOP_EVENT` / `AFTER_STOP_EVENT` / `BEFORE_DESTROY_EVENT` / `AFTER_DESTROY_EVENT` / `PERIODIC_EVENT` / `CONFIGURE_START_EVENT` / `CONFIGURE_STOP_EVENT`。旧资料里「six events」的说法早已过时。

The most important methods in Lifecycle are start and stop.
A component provides implementations of these methods so that its parent component can start and stop it.
Listeners are attached via `addLifecycleListener` and notified on every transition; `findLifecycleListeners()` 仍然存在（`Lifecycle.java:184`）。

## Bootstrap

Tomcat supports multiple styles of configuration and startup - the most common and stable is server.xml-based, implemented in `org.apache.catalina.startup.Bootstrap`.

Start entrance:

```shell
startup.sh -> catalina.sh start -> java org.apache.catalina.startup.Bootstrap start
```

1. [invoke Catalina](/docs/CS/Framework/Tomcat/Start.md?id=invoke-catalina)
2. invoke [org.apache.catalina.startup.Catalina#load()](/docs/CS/Framework/Tomcat/Start.md?id=load) and [org.apache.catalina.startup.Catalina#start](/docs/CS/Framework/Tomcat/Start.md?id=start) by Reflection

```java
// Bootstrap.java:443 起
public static void main(String[] args) {

    synchronized (daemonLock) {
        if (daemon == null) {
            // Don't set daemon until init() has completed
            Bootstrap bootstrap = new Bootstrap();
            try {
                bootstrap.init();
            } catch (Throwable t) {
                handleThrowable(t);
                log.error("Init exception", t);
                return;
            }
            daemon = bootstrap;
        } else {
            // When running as a service the call to stop will be on a new
            // thread so make sure the correct class loader is used to
            // prevent a range of class not found exceptions.
            Thread.currentThread().setContextClassLoader(daemon.catalinaLoader);
        }
    }

    try {
        String command = "start";
        if (args.length > 0) {
            command = args[args.length - 1];
        }

        switch (command) {
            case "startd":
                args[args.length - 1] = "start";
                daemon.load(args);
                daemon.start();
                break;
            case "stopd":
                args[args.length - 1] = "stop";
                daemon.stop();
                break;
            case "start":
                daemon.setAwait(true);
                daemon.load(args);
                daemon.start();
                if (null == daemon.getServer()) {
                    System.exit(1);
                }
                break;
            case "stop":
                daemon.stopServer(args);
                break;
            case "configtest":
                daemon.load(args);
                if (null == daemon.getServer()) {
                    System.exit(1);
                }
                System.exit(0);
                break;
            default:
                log.warn("Bootstrap: command \"" + command + "\" does not exist.");
                break;
        }
    } catch (Throwable t) {
        // Unwrap the Exception for clearer error reporting
        Throwable throwable = t;
        if (throwable instanceof InvocationTargetException && throwable.getCause() != null) {
            throwable = throwable.getCause();
        }
        handleThrowable(throwable);
        log.error("Error running command", throwable);
        System.exit(1);
    }
}
```

旧摘录里那段 `if (command.equals("start"))` 是反编译产物，11 的真实结构是 `switch`，共六个分支。关键差异在 `startd` / `stopd` 这对新命令：

- `start`（`catalina.sh start` 走这条）：`setAwait(true)` 让主线程阻塞在 `await()` 上等关闭命令——这是前台运行。
- `startd`：**不设 await**，`load + start` 后 main 直接返回，进程靠非 daemon 线程存活。Windows 服务与某些容器集成用它，因为宿主自己负责进程生命周期，不需要 Tomcat 再占一个前台线程。
- `stopd`：`daemon.stop()` 直接停 daemon 实例（服务模式，同一个 JVM 里操作）；`stop` 则是 `stopServer(args)`——**跨进程**，通过向 shutdown 端口发命令停掉另一个 Tomcat 实例。
- `configtest`：只 `load` 不 `start`，校验 server.xml 后退出，返回码 0/1。

注意 `command` 取的是 `args[args.length - 1]`——最后一个参数才是命令，前面都是传给 Catalina 的参数（`Bootstrap.load(String[])` 会把它们原样反射传给 `Catalina.load(String[])`，用于 `-config` 等选项）。

Bootstrap 里所有对 Catalina 的调用（`load`/`start`/`stop`/`stopServer`/`setAwait`）都是**反射**，因为 Catalina 类是在 `catalinaLoader` 里加载的，而 Bootstrap 本身在 system classloader 上——两个世界之间唯一合法的桥就是反射加 `setParentClassLoader(sharedLoader)`，见下一节。

### invoke Catalina

Initialize daemon.

[initClassLoaders](/docs/CS/Framework/Tomcat/ClassLoader.md?id=initclassloaders)

```java
// Bootstrap.java:65 起
public void init() throws Exception {

    initClassLoaders();

    Thread.currentThread().setContextClassLoader(catalinaLoader);

    // Load our startup class and call its process() method
    if (log.isTraceEnabled()) {
        log.trace("Loading startup class");
    }
    Class<?> startupClass = catalinaLoader.loadClass("org.apache.catalina.startup.Catalina");
    Object startupInstance = startupClass.getConstructor().newInstance();

    // Set the shared extensions class loader
    if (log.isTraceEnabled()) {
        log.trace("Setting startup class properties");
    }
    String methodName = "setParentClassLoader";
    Class<?>[] paramTypes = new Class[1];
    paramTypes[0] = Class.forName("java.lang.ClassLoader");
    Object[] paramValues = new Object[1];
    paramValues[0] = sharedLoader;
    Method method = startupInstance.getClass().getMethod(methodName, paramTypes);
    method.invoke(startupInstance, paramValues);

    catalinaDaemon = startupInstance;
}
```

与旧摘录相比，`SecurityClassLoad.securityClassLoad(catalinaLoader)` 这一行**消失了**——它的历史使命是在 SecurityManager 下预加载安全相关类以避免运行期 `doPrivileged`，SM 移除后该类连同调用一起删除（`startup/SecurityClassLoad.java` 在 11 源码树里已不存在）。

这段代码浓缩了 Tomcat 启动的类加载设计，对照 [ClassLoader](/docs/CS/Framework/Tomcat/ClassLoader.md?id=initclassloaders) 读：

1. `initClassLoaders()` 建 common/server/shared 三个 loader。
2. **主线程的 TCCL 切到 `catalinaLoader`**——之后所有没有显式指定 loader 的加载都落在容器这一侧。
3. `Catalina` 类由 `catalinaLoader.loadClass(...)` 加载，而不是 `Class.forName`：显式指定 loader，绕开调用方的 classloader。
4. `setParentClassLoader(sharedLoader)` 通过**反射**调用——Bootstrap 不能静态引用 Catalina 的任何类型。

### load

```java
// Catalina.java:166 起
public void load() {

    if (loaded) {
        return;
    }
    // No load retry after a failure
    loaded = true;

    long t1 = System.nanoTime();

    // Before digester - it may be needed
    initNaming();

    // Parse main server.xml
    parseServerXml(true);
    Server s = getServer();
    if (s == null) {
        return;
    }

    getServer().setCatalina(this);
    getServer().setCatalinaHome(Bootstrap.getCatalinaHomeFile());
    getServer().setCatalinaBase(Bootstrap.getCatalinaBaseFile());

    // Stream redirection
    initStreams();

    // Start the new server
    try {
        getServer().init();
    } catch (LifecycleException e) {
        if (throwOnInitFailure) {
            throw new Error(e);
        } else {
            log.error(sm.getString("catalina.initError"), e);
        }
    }

    if (log.isInfoEnabled()) {
        log.info(sm.getString("catalina.init",
                Long.toString(TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - t1))));
    }
}
```

三个变化：

1. **`initDirs()` 没有了**。旧版 load() 的第一行是它（创建 catalina.home/base 临时目录），现在这部分职责上移到了 Bootstrap 的静态初始化，load() 直接从 `Bootstrap.getCatalinaHomeFile()` 取。
2. **`ConfigFileLoader.setSource(...)` + `configFile()` + Digester 那一大段被抽成 `parseServerXml(boolean)`**（`:648`）。参数 `start` 决定用 `createStartDigester()` 还是 `createStopDigester()`——stop 路径也解析 server.xml（只为找到 shutdown 端口），用更小的规则集。更重要的是这个方法里藏着一条**生成代码路径**：`useGeneratedCode`/`generateCode` 时，Digester 的解析规则会被预编译成 `ServerXml` / `ServerXmlStop` 类（`Catalina.generateLoader()` 会把 `DigesterGeneratedCodeLoader` 写成 .java 文件），启动时直接调编译产物跳过 Digester 的反射规则匹配。这是近年 Tomcat 提速启动的官方手段，默认关闭。
3. **init 失败的处理收敛到一个字段**。旧版是内联 `Boolean.getBoolean("org.apache.catalina.startup.EXIT_ON_INIT_FAILURE")`，11 改成可设置的受保护字段：

```java
// Catalina.java:140
protected boolean throwOnInitFailure = Boolean.getBoolean("org.apache.catalina.startup.EXIT_ON_INIT_FAILURE");
```

默认 `false`：`getServer().init()` 失败只 `log.error`，进程继续活着但 `getServer()` 为 null（`Bootstrap.main` 的 `start` 分支会因此 `System.exit(1)`）。设为 true 时直接 `throw new Error(e)` 进程即死——容器管理器（systemd/K8s）依赖这个语义才能感知启动失败并重启。同一个系统属性还会被 `Connector` 的构造函数读取并传给 `LifecycleBase.setThrowOnFailure()`（`Connector.java:119`、`:134`），所以「初始化失败要不要抛」是贯穿三层的一个开关。

#### initInternal

Template method pattern

Prepare the component for starting. This method should perform any initialization required post object creation.
The following LifecycleEvents will be fired in the following order:

1. INIT_EVENT: On the successful completion of component initialization.

```java
// LifecycleBase.java
@Override
public final synchronized void init() throws LifecycleException {
    if (!state.equals(LifecycleState.NEW)) {
        invalidTransition(BEFORE_INIT_EVENT);
    }

    try {
        setStateInternal(LifecycleState.INITIALIZING, null, false);
        initInternal();
        setStateInternal(LifecycleState.INITIALIZED, null, false);
    } catch (Throwable t) {
        handleSubClassException(t, "lifecycleBase.initFail", toString());
    }
}
```

`handleSubClassException` 里有一个不起眼但贯穿全局的开关：`throwOnFailure` 默认 **true**（`LifecycleBase.java:61`），即组件失败默认向上抛；`Connector` 构造时会按 `EXIT_ON_INIT_FAILURE` 系统属性覆盖它（`Connector.java:119`）。所以「init 失败进程要不要死」由三个层次共同决定：组件默认抛 → Catalina 按开关决定吞还是抛 Error → Bootstrap 里 `getServer() == null` 兜底退出。

`StandardServer.initInternal` 在 11 **大幅缩水**——旧摘录里那段遍历 `URLClassLoader` 找 jar、调 `ExtensionValidator.addSystemResource(f)` 的整块循环随 `ExtensionValidator` 类一起消失了（该类做的是可选扩展/依赖 jar 的校验，早年的可选包机制早已经无人使用）：

```java
// core/StandardServer.java
protected void initInternal() throws LifecycleException {

    super.initInternal();

    // Register global String cache
    // Note although the cache is global, if there are multiple Servers
    // present in the JVM (may happen when embedding) then the same cache
    // will be registered under multiple names
    onameStringCache = register(new StringCache(), "type=StringCache");

    // Register the MBeanFactory
    MBeanFactory factory = new MBeanFactory();
    factory.setContainer(this);
    onameMBeanFactory = register(factory, "type=MBeanFactory");

    // Register the naming resources
    globalNamingResources.init();

    // Initialize our defined Services
    for (Service service : findServices()) {
        service.init();
    }
}
```

旧摘录里的 `reconfigureUtilityExecutor(...)` 与 `register(utilityExecutor, "type=UtilityExecutor")` 也不再出现在这里——共享的调度线程池 `utilityExecutor`（默认 `utilityThreads = 2`，`StandardServer.java:179`）改由 StandardServer 的属性 setter 路径创建（`:398`），init 阶段只负责注册 MBean 与初始化 naming 资源和 services。

### start

Start Flow:

1. start Server
2. start Service
3. start [Connector](/docs/CS/Framework/Tomcat/Connector.md)
4. register [Shutdown Hooks](/docs/CS/Java/JDK/JVM/destroy.md?id=shutdown-hooks)

```java
// Catalina.java
public void start() {

    if (getServer() == null) {
        load();
    }

    if (getServer() == null) {
        log.fatal(sm.getString("catalina.noServer"));
        return;
    }

    long t1 = System.nanoTime();

    // Start the new server
    try {
        getServer().start();
    } catch (LifecycleException e) {
        log.fatal(sm.getString("catalina.serverStartFail"), e);
        try {
            getServer().destroy();
        } catch (LifecycleException e1) {
            log.debug(sm.getString("catalina.destroyFail"), e1);
        }
        return;
    }

    if (log.isInfoEnabled()) {
        log.info(sm.getString("catalina.startup",
                Long.toString(TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - t1))));
    }

    if (generateCode) {
        // Generate loader which will load all generated classes
        generateLoader();
    }

    // Register shutdown hook
    if (useShutdownHook) {
        if (shutdownHook == null) {
            shutdownHook = new CatalinaShutdownHook();
        }
        Runtime.getRuntime().addShutdownHook(shutdownHook);

        // If JULI is being used, disable JULI's shutdown hook since
        // shutdown hooks run in parallel and log messages may be lost
        // if JULI's hook completes before the CatalinaShutdownHook()
        LogManager logManager = LogManager.getLogManager();
        if (logManager instanceof ClassLoaderLogManager) {
            ((ClassLoaderLogManager) logManager).setUseShutdownHook(false);
        }
    }

    if (await) {
        await();
        stop();
    }
}
```

start 失败会**先 destroy 再返回**（`:serverStartFail` 那段）——这是 11 明确写出的语义：start 到一半失败，已经起来的子组件要拆干净，而不是留着半死状态。注释还解释了关闭 JULI 自己的 shutdown hook 的原因：**JVM 的 shutdown hook 是并行执行的**，如果 JULI 先跑完，CatalinaShutdownHook 期间的日志就丢了——所以注册自己的 hook 时必须禁用 JULI 的（stop 时再恢复，见 [ShutdownHook](/docs/CS/Framework/Tomcat/Start.md?id=shutdownhook)）。

`await` 为 true 时主线程阻塞在 `getServer().await()`（监听 shutdown 端口），收到关闭命令后 `stop()`。这就是 `start` 与 `startd` 两个命令的真实分岔点。

#### startInternal

Prepare for the beginning of active use of the public methods other than property getters/setters and life cycle methods of this component.
The following LifecycleEvents will be fired in the following order:

1. BEFORE_START_EVENT: At the beginning of the method. It is as this point the state transitions to LifecycleState.STARTING_PREP.
2. START_EVENT: During the method once it is safe to call start() for any child components.
   It is at this point that the state transitions to LifecycleState.STARTING and that the public methods other than property getters/setters and life cycle methods may be used.
3. AFTER_START_EVENT: At the end of the method, immediately before it returns. It is at this point that the state transitions to LifecycleState.STARTED.

```java
// LifecycleBase.java
@Override
public final synchronized void start() throws LifecycleException {

    if (LifecycleState.STARTING_PREP.equals(state) || LifecycleState.STARTING.equals(state) ||
            LifecycleState.STARTED.equals(state)) {
        return;
    }

    if (state.equals(LifecycleState.NEW)) {
        init();
    } else if (state.equals(LifecycleState.FAILED)) {
        stop();
    } else if (!state.equals(LifecycleState.INITIALIZED) &&
            !state.equals(LifecycleState.STOPPED)) {
        invalidTransition(BEFORE_START_EVENT);
    }

    try {
        setStateInternal(LifecycleState.STARTING_PREP, null, false);
        startInternal();
        if (state.equals(LifecycleState.FAILED)) {
            // This is a 'controlled' failure. The component put itself into the
            // FAILED state so call stop() to complete the clean-up.
            stop();
        } else if (!state.equals(LifecycleState.STARTING)) {
            // Shouldn't be necessary but acts as a check that sub-classes are
            // doing what they are supposed to.
            invalidTransition(AFTER_START_EVENT);
        } else {
            setStateInternal(LifecycleState.STARTED, null, false);
        }
    } catch (Throwable t) {
        // This is an 'uncontrolled' failure so put the component into the
        // FAILED state and throw an exception.
        handleSubClassException(t, "lifecycleBase.startFail", toString());
    }
}
```

模板方法的两个失败路径值得对照：「受控失败」（子类自己把自己置为 FAILED，模板负责调 stop() 收尾）与「非受控失败」（异常冒上来，`handleSubClassException` 置 FAILED 并按 `throwOnFailure` 决定抛还是记）。

##### StandardService

```java
// core/StandardService.java
protected void startInternal() throws LifecycleException {

    if (log.isInfoEnabled()) {
        log.info(sm.getString("standardService.start.name", this.name));
    }
    setState(LifecycleState.STARTING);

    // Start our defined Container first
    if (engine != null) {
        engine.start();
    }

    for (Executor executor : findExecutors()) {
        executor.start();
    }

    mapperListener.start();

    // Start our defined Connectors second
    for (Connector connector : findConnectors()) {
        // If it has already failed, don't try and start it
        if (connector.getState() != LifecycleState.FAILED) {
            connector.start();
        }
    }
}
```

与旧摘录相比：`synchronized (engine)`、`synchronized (connectorsLock)` 两把锁没了，`executors.start()` 改成逐个遍历 `findExecutors()`，connectors 也改成逐个遍历。**最值得注意的是启动顺序与旧注释的说法相反**：engine（容器树）先起，connector 最后——「先有处理能力再开监听端口」，connector 打开端口的瞬间请求就能被处理，容器必须已经就绪。`connector.getState() != FAILED` 的跳过逻辑意味着**单个 connector 起不来不会拖垮整个 Service**。

对应地，`stopInternal()` 的顺序完全镜像：先对每个 connector `closeServerSocketGraceful()` + `awaitConnectionsClose(gracefulStopAwaitMillis)`，再 pause，再逐层 stop——优雅停机的细节在 [Connector 的摘流一节](/docs/CS/Framework/Tomcat/Connector.md)与 [故障处理](/docs/CS/Framework/Tomcat/Tomcat.md?id=fault-handling)。

##### StandardContext

在 startInternal 里 fire 了 ServletContextListener

```java
// core/StandardContext.java:4105 起
public boolean listenerStart() {
    //...
    Object instances[] = getApplicationLifecycleListeners();
    //...
    for (Object instance : instances) {
        if (!(instance instanceof ServletContextListener listener)) {
            continue;
        }
        try {
            fireContainerEvent("beforeContextInitialized", listener);
            if (noPluggabilityListeners.contains(listener)) {
                listener.contextInitialized(tldEvent);
            } else {
                listener.contextInitialized(event);
            }
            fireContainerEvent("afterContextInitialized", listener);
        } catch (Throwable t) {
            ExceptionUtils.handleThrowable(t);
            fireContainerEvent("afterContextInitialized", listener);
            getLogger().error(sm.getString("standardContext.listenerStart", instance.getClass().getName()), t);
            ok = false;
        }
    }
    return ok;
}
```

11 的两处细节：`instance instanceof ServletContextListener listener` 用了模式匹配（旧的强制转型写法没了）；catch 里**也会触发 `afterContextInitialized` 事件**，保证监听器事件序列对称——依赖这个事件做清理的代码在 listener 抛异常时也能收到通知。

tomcat首先会加载进ContextLoaderListener

这里可以通过 Spring MVC 的 [ContextLoaderListener](/docs/CS/Framework/Spring/MVC.md?id=contextloaderlistener) 进行初始化

#### stopInternal

Gracefully terminate the active use of the public methods other than property getters/setters and life cycle methods of this component.

- Once the STOP_EVENT is fired, the public methods other than property getters/setters and life cycle methods should not be used.
  The following LifecycleEvents will be fired in the following order:
- BEFORE_STOP_EVENT: At the beginning of the method. It is at this point that the state transitions to LifecycleState.STOPPING_PREP.
- STOP_EVENT: During the method once it is safe to call stop() for any child components.
  It is at this point that the state transitions to LifecycleState.STOPPING and that the public methods other than property getters/setters and life cycle methods may no longer be used.
- AFTER_STOP_EVENT: At the end of the method, immediately before it returns.
  It is at this point that the state transitions to LifecycleState.STOPPED.

Note that if transitioning from LifecycleState.FAILED then the three events above will be fired
but the component will transition directly from LifecycleState.FAILED to LifecycleState.STOPPING, bypassing LifecycleState.STOPPING_PREP

```java
// LifecycleBase.java
@Override
public final synchronized void stop() throws LifecycleException {

    if (LifecycleState.STOPPING_PREP.equals(state) || LifecycleState.STOPPING.equals(state) ||
            LifecycleState.STOPPED.equals(state)) {

        if (log.isDebugEnabled()) {
            Exception e = new LifecycleException();
            log.debug(sm.getString("lifecycleBase.alreadyStopped", toString()), e);
        } else if (log.isInfoEnabled()) {
            log.info(sm.getString("lifecycleBase.alreadyStopped", toString()));
        }

        return;
    }

    if (state.equals(LifecycleState.INITIALIZED)) {
        return;
    }

    if (state.equals(LifecycleState.NEW)) {
        state = LifecycleState.STOPPED;
        return;
    }

    if (!state.equals(LifecycleState.STARTED) && !state.equals(LifecycleState.FAILED)) {
        invalidTransition(BEFORE_STOP_EVENT);
    }

    try {
        if (state.equals(LifecycleState.FAILED)) {
            // Don't transition to STOPPING_PREP as that would briefly mark the
            // component as available but do ensure the BEFORE_STOP_EVENT is
            // fired
            fireLifecycleEvent(BEFORE_STOP_EVENT, null);
        } else {
            setStateInternal(LifecycleState.STOPPING_PREP, null, false);
        }

        stopInternal();

        // Shouldn't be necessary but acts as a check that sub-classes are
        // doing what they are supposed to.
        if (!state.equals(LifecycleState.STOPPING) && !state.equals(LifecycleState.FAILED)) {
            invalidTransition(AFTER_STOP_EVENT);
        }

        setStateInternal(LifecycleState.STOPPED, null, false);
    } catch (Throwable t) {
        handleSubClassException(t, "lifecycleBase.stopFail", toString());
    } finally {
        if (this instanceof Lifecycle.SingleUse) {
            // Complete stop process first
            setStateInternal(LifecycleState.STOPPED, null, false);
            destroy();
        }
    }
}
```

> [!WARNING]
>
> 上面这段在 11.0.26 里与旧摘录的差异不在主链路，而在**两类早退守卫**：其一，`STOPPING_PREP/STOPPING/STOPPED` 状态下重复 stop 不再静默返回，而是 debug（附一个新建的异常栈）或 info 打一条 `lifecycleBase.alreadyStopped`；其二，新增 `if (state.equals(LifecycleState.INITIALIZED)) { return; }`——init 过但没 start 的组件 stop 是 no-op。这两条守卫直接影响嵌入场景：引擎/connector 在半初始化状态被停止时不会再抛 `invalidTransition`。

`finally` 里的 `Lifecycle.SingleUse` 分支值得知道：标记为单次使用的组件（如内嵌场景的一次性 Server）stop 完成后立刻 destroy，避免「停了但没释放」的中间状态。

## ShutdownHook

`CatalinaShutdownHook` 是 Catalina 的内部类，本质只有一件事：调 `Catalina.stop()`。

```java
// Catalina.java:1110 起
protected class CatalinaShutdownHook extends Thread {

    @Override
    public void run() {
        try {
            if (getServer() != null) {
                Catalina.this.stop();
            }
        } catch (Throwable ex) {
            ExceptionUtils.handleThrowable(ex);
            log.error(sm.getString("catalina.shutdownHookFail"), ex);
        } finally {
            // If JULI is used, shut JULI down *after* the server shuts down
            // so log messages aren't lost
            LogManager logManager = LogManager.getLogManager();
            if (logManager instanceof ClassLoaderLogManager) {
                ((ClassLoaderLogManager) logManager).shutdown();
            }
        }
    }
}
```

围绕它有一套容易被忽略的协调逻辑，全部源于 **JVM 的 shutdown hook 是并行执行的**：

- 注册时（`Catalina.start()`）：`addShutdownHook(shutdownHook)` 之后立刻 `((ClassLoaderLogManager) logManager).setUseShutdownHook(false)` 禁用 JULI 自己的 hook——否则 JULI 可能在 Catalina 停完之前就关掉日志系统，停机过程的日志全部丢失。
- 正常 `stop()`（`Catalina.java:930` 起）：**先 `removeShutdownHook(shutdownHook)` 再停 server**，注释明写「so that server.stop() doesn't get invoked twice」；随后把 JULI 的 hook 重新 `setUseShutdownHook(true)`。
- hook 自身的 finally 里最后调 `ClassLoaderLogManager.shutdown()`——顺序是「server 停干净之后才关日志」。

所以日志丢失问题的完整答案是双向的：正常停机走 removeHook + 手动恢复；异常停机（kill）走 hook，但 JULI 的 hook 已被禁用，由 CatalinaShutdownHook 的 finally 亲自关日志。

## Links

- [Tomcat](/docs/CS/Framework/Tomcat/Tomcat.md)
- [ClassLoader](/docs/CS/Framework/Tomcat/ClassLoader.md)
- [Connector](/docs/CS/Framework/Tomcat/Connector.md)
- [Deployment](/docs/CS/Framework/Tomcat/Deployment.md)

## References

1. [Tomcat 11.0 API: Bootstrap](https://tomcat.apache.org/tomcat-11.0-doc/api/org/apache/catalina/startup/Bootstrap.html)
2. [Tomcat 高并发之道原理拆解与性能调优 - 码哥字节](https://mp.weixin.qq.com/s?__biz=MzkzMDI1NjcyOQ==&mid=2247487712&idx=1&sn=a77efe0871bf0c5d1dc9d0a3ae138d5e&source=41#wechat_redirect)
