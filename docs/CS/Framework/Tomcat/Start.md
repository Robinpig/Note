## Introduction

Tomcat 使用 `org.apache.catalina.startup` 包中的两个类来启动：Catalina 和 Bootstrap。
Catalina 类用于启动和停止 Server 对象，以及解析 Tomcat 配置文件 server.xml。
Bootstrap 类是入口点，它创建 Catalina 实例并调用其 process 方法。
理论上，这两个类可以合并，但为了支持多种运行 Tomcat 的模式，提供了多个 bootstrap 类。
例如，前述的 Bootstrap 类用于将 Tomcat 作为独立应用程序运行。

为方便用户，Tomcat 还附带了批处理文件和 shell 脚本，可以轻松启动和停止 servlet 容器。
借助这些批处理文件和 shell 脚本，用户无需记住运行 Bootstrap 类的 java.exe 选项，只需运行相应的批处理文件或 shell 脚本即可。

## Lifecycle

组件生命周期方法的通用接口。
Catalina 组件可以实现此接口（以及它们所支持功能的适当接口），以**提供一致的方式来启动和停止组件**。

支持 Lifecycle 的组件的有效状态转换如下：

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

任何状态都可以转换为 FAILED。

- 当组件处于 STARTING_PREP、STARTING 或 STARTED 状态时调用 start() 无效。
- 当组件处于 NEW 状态时调用 start() 会在进入 start() 方法后立即调用 init()。
- 当组件处于 STOPPING_PREP、STOPPING 或 STOPPED 状态时调用 stop() 无效。
- 当组件处于 NEW 状态时调用 stop() 会将组件转换为 STOPPED。
  这通常发生在组件启动失败且未启动所有子组件时。
  当组件停止时，它会尝试停止所有子组件——即使那些未启动的。

Lifecycle 中最重要的方法是 start 和 stop。
组件提供这些方法的实现，以便其父组件可以启动和停止它。
另外三个方法——addLifecycleListener、findLifecycleListeners 和 removeLifecycleListener——与监听器相关。
组件可以有对该组件中发生的事件感兴趣的监听器。
当事件发生时，对该事件感兴趣的监听器将收到通知。
Lifecycle 实例可以触发的六个事件的名称在接口的 public static final Strings 中定义。

## Bootstrap

Tomcat 支持多种配置和启动方式——最常见和稳定的是基于 server.xml 的方式，在 `org.apache.catalina.startup.Bootstrap` 中实现。

启动入口：

```shell
startup.sh -> catalina.sh start ->java -jar org.apache.catalina.startup.Bootstrap.main()
```

1. [invoke Catalina](/docs/CS/Framework/Tomcat/Start.md?id=invoke-Catalina)
2. 通过反射调用 [org.apache.catalina.startup.Catalina#load()](/docs/CS/Framework/Tomcat/Start.md?id=load) 和 [org.apache.catalina.startup.Catalina#start](/docs/CS/Framework/Tomcat/Start.md?id=start)

```java
//Bootstrap.java
public static void main(String[] args) {
    synchronized(daemonLock) {
        if (daemon == null) {
            Bootstrap bootstrap = new Bootstrap();

            try {
                bootstrap.init();
            } catch (Throwable var5) {
                handleThrowable(var5);
                var5.printStackTrace();
                return;
            }

            daemon = bootstrap;
        } else {
            Thread.currentThread().setContextClassLoader(daemon.catalinaLoader);
        }
    }

    try {
        String command = "start";
       if (command.equals("start")) {
            daemon.setAwait(true);
            daemon.load(args);
            daemon.start();
            if (null == daemon.getServer()) {
                System.exit(1);
            }
        } 
       // ...
    } catch (Throwable var7) {
        // ...
    }

}
```

### invoke Catalina

初始化 daemon。

[initClassLoaders](/docs/CS/Framework/Tomcat/ClassLoader.md?id=initClassLoaders)

```java
//Bootstrap.java
public void init() throws Exception {

    initClassLoaders();

    Thread.currentThread().setContextClassLoader(catalinaLoader);

    SecurityClassLoad.securityClassLoad(catalinaLoader);

    // Load our startup class and call its process() method
    Class<?> startupClass = catalinaLoader.loadClass("org.apache.catalina.startup.Catalina");
    Object startupInstance = startupClass.getConstructor().newInstance();

    // Set the shared extensions class loader
    String methodName = "setParentClassLoader";
    Class<?> paramTypes[] = new Class[1];
    paramTypes[0] = Class.forName("java.lang.ClassLoader");
    Object paramValues[] = new Object[1];
    paramValues[0] = sharedLoader;
    Method method = startupInstance.getClass().getMethod(methodName, paramTypes);
    method.invoke(startupInstance, paramValues);

    catalinaDaemon = startupInstance;
}
```

### load

```java
//org.apache.catalina.startup.Catalina.java
public void load() {

    if (loaded) {
        return;
    }
    loaded = true;

    long t1 = System.nanoTime();

    initDirs();

    // Before digester - it may be needed
    initNaming();

    // Set configuration source
    ConfigFileLoader.setSource(new CatalinaBaseConfigurationSource(Bootstrap.getCatalinaBaseFile(), getConfigFile()));
    File file = configFile();

    // Create and execute our Digester
    Digester digester = createStartDigester();

    try (ConfigurationSource.Resource resource = ConfigFileLoader.getSource().getServerXml()) {
        InputStream inputStream = resource.getInputStream();
        InputSource inputSource = new InputSource(resource.getURI().toURL().toString());
        inputSource.setByteStream(inputStream);
        digester.push(this);
        digester.parse(inputSource);
    } catch (Exception e) {
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
        if (Boolean.getBoolean("org.apache.catalina.startup.EXIT_ON_INIT_FAILURE")) {
            throw new java.lang.Error(e);
        } else {
        }
    }

    long t2 = System.nanoTime();
}
```

#### initInternal

模板方法模式。

为组件启动做准备。此方法应在对象创建后执行任何所需的初始化。将按以下顺序触发 LifecycleEvents：

1. INIT_EVENT：组件初始化成功完成后触发。

```java
// LifecycleBase
@Override
public final synchronized void init() throws LifecycleException {
    if (!state.equals(LifecycleState.NEW)) {
        invalidTransition(Lifecycle.BEFORE_INIT_EVENT);
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

```java
//StanardServer
protected void initInternal() throws LifecycleException {
    super.initInternal();
    this.reconfigureUtilityExecutor(getUtilityThreadsInternal(this.utilityThreads));
    this.register(this.utilityExecutor, "type=UtilityExecutor");
    this.onameStringCache = this.register(new StringCache(), "type=StringCache");
    MBeanFactory factory = new MBeanFactory();
    factory.setContainer(this);
    this.onameMBeanFactory = this.register(factory, "type=MBeanFactory");
    this.globalNamingResources.init();
    if (this.getCatalina() != null) {
        for(ClassLoader cl = this.getCatalina().getParentClassLoader(); cl != null && cl != ClassLoader.getSystemClassLoader(); cl = cl.getParent()) {
            if (cl instanceof URLClassLoader) {
                URL[] urls = ((URLClassLoader)cl).getURLs();
                URL[] var4 = urls;
                int var5 = urls.length;

                for(int var6 = 0; var6 < var5; ++var6) {
                    URL url = var4[var6];
                    if (url.getProtocol().equals("file")) {
                        try {
                            File f = new File(url.toURI());
                            if (f.isFile() && f.getName().endsWith(".jar")) {
                                ExtensionValidator.addSystemResource(f);
                            }
                        } catch (URISyntaxException var9) {
                        } catch (IOException var10) {
                        }
                    }
                }
            }
        }
    }

    Service[] var11 = this.services;
    int var12 = var11.length;

    for(int var13 = 0; var13 < var12; ++var13) {
        Service service = var11[var13];
        service.init();
    }

}
```

### start

启动流程：

1. 启动 Server
2. 启动 Service
3. 启动 [Connector](/docs/CS/Framework/Tomcat/Connector.md)
4. 注册 [Shutdown Hooks](/docs/CS/Java/JDK/JVM/destroy.md?id=shutdown-hooks)

```java
//org.apache.catalina.startup.Catalina.java
public void start() {
    if (this.getServer() == null) {
        this.load();
    }

    if (this.getServer() == null) {
        log.fatal(sm.getString("catalina.noServer"));
    } else {
        long t1 = System.nanoTime();

        try {
            this.getServer().start();
        } catch (LifecycleException var6) {
            try {
                this.getServer().destroy();
            } catch (LifecycleException var5) {
            }
            return;
        }

        if (this.generateCode) {
            this.generateLoader();
        }

        if (this.useShutdownHook) {
            if (this.shutdownHook == null) {
                this.shutdownHook = new Catalina.CatalinaShutdownHook();
            }

            Runtime.getRuntime().addShutdownHook(this.shutdownHook);
            LogManager logManager = LogManager.getLogManager();
            if (logManager instanceof ClassLoaderLogManager) {
                ((ClassLoaderLogManager)logManager).setUseShutdownHook(false);
            }
        }

        if (this.await) {
            this.await();
            this.stop();
        }

    }
}
```

#### startInternal

为此组件公开方法（属性 getter/setter 和生命周期方法除外）的活跃使用做好准备。
在利用该组件的任何公开方法（属性 getter/setter 和生命周期方法除外）之前，应先调用此方法。
将按以下顺序触发 LifecycleEvents：

1. BEFORE_START_EVENT：在方法开始时触发。此时状态转换为 LifecycleState.STARTING_PREP。
2. START_EVENT：在方法执行过程中，当可以安全地对任何子组件调用 start() 时触发。此时状态转换为 LifecycleState.STARTING，公开方法（属性 getter/setter 和生命周期方法除外）可以开始使用。
3. AFTER_START_EVENT：在方法结束时，即将返回之前触发。此时状态转换为 LifecycleState.STARTED。

```java
// LifecycleBase
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
        invalidTransition(Lifecycle.BEFORE_START_EVENT);
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
            invalidTransition(Lifecycle.AFTER_START_EVENT);
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

##### StandardService

```java
public class StandardService extends LifecycleMBeanBase implements Service {
  protected void startInternal() throws LifecycleException {

    this.setState(LifecycleState.STARTING);
    synchronized (this.engine) {
      this.engine.start();
    }

    synchronized (this.executors) {
      executors.start();
    }

    this.mapperListener.start();
    synchronized (this.connectorsLock) {
      connectors.start();
    }
  }
}
```

##### StandardContext

在 startInternal 里触发了 ServletContextListener。

```java
public boolean listenerStart() {
        //...
        Object instances[] = getApplicationLifecycleListeners();
        //...
        for (Object instance : instances) {
            ServletContextListener listener = (ServletContextListener) instance;
            try {
                fireContainerEvent("beforeContextInitialized", listener);
                if (noPluggabilityListeners.contains(listener)) {
                    listener.contextInitialized(tldEvent);
                } else {
                    listener.contextInitialized(event);
                }
                fireContainerEvent("afterContextInitialized", listener);
            } catch (Throwable t) {
                //...
            }
        }
        return ok;

    }
```

Tomcat 首先会加载进 ContextLoaderListener。

这里可以通过 Spring MVC 的 [ContextLoaderListener](/docs/CS/Framework/Spring/MVC.md?id=ContextLoaderListener) 进行初始化。

#### stopInternal

优雅地终止此组件公开方法（属性 getter/setter 和生命周期方法除外）的活跃使用。

- 一旦触发 STOP_EVENT，公开方法（属性 getter/setter 和生命周期方法除外）不应再被使用。将按以下顺序触发 LifecycleEvents：
- BEFORE_STOP_EVENT：在方法开始时触发。此时状态转换为 LifecycleState.STOPPING_PREP。
- STOP_EVENT：在方法执行过程中，当可以安全地对任何子组件调用 stop() 时触发。此时状态转换为 LifecycleState.STOPPING，公开方法（属性 getter/setter 和生命周期方法除外）不再可用。
- AFTER_STOP_EVENT：在方法结束时，即将返回之前触发。此时状态转换为 LifecycleState.STOPPED。

注意，如果从 LifecycleState.FAILED 转换，上述三个事件仍会触发，但组件会直接从 LifecycleState.FAILED 转换为 LifecycleState.STOPPING，跳过 LifecycleState.STOPPING_PREP。

```java
// LifecycleBase
@Override
public final synchronized void stop() throws LifecycleException {

    if (LifecycleState.STOPPING_PREP.equals(state) || LifecycleState.STOPPING.equals(state) ||
            LifecycleState.STOPPED.equals(state)) {
        return;
    }

    if (state.equals(LifecycleState.NEW)) {
        state = LifecycleState.STOPPED;
        return;
    }

    if (!state.equals(LifecycleState.STARTED) && !state.equals(LifecycleState.FAILED)) {
        invalidTransition(Lifecycle.BEFORE_STOP_EVENT);
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
            invalidTransition(Lifecycle.AFTER_STOP_EVENT);
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

## ShutdownHook

CatalinaShutdownHook

## Links

- [Tomcat](/docs/CS/Framework/Tomcat/Tomcat.md)

## References

1. [Tomcat 高并发之道原理拆解与性能调优 - 码哥字节](https://mp.weixin.qq.com/s?__biz=MzkzMDI1NjcyOQ==&mid=2247487712&idx=1&sn=a77efe0871bf0c5d1dc9d0a3ae138d5e&source=41#wechat_redirect)
2. [How to Install Apache Tomcat 9](https://www3.ntu.edu.sg/home/ehchua/programming/howto/Tomcat_HowTo.html)
