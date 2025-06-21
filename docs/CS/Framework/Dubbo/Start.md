## Introduction





## start

如果按完整服务启动与订阅的顺序我们可以归结为以下6点:

- 导出服务(提供者)
  - 服务提供方通过指定端口对外暴露服务
- 注册服务(提供者)
  - 提供方向注册中心注册自己的信息
- (服务发现)-订阅服务(消费者)
  - 服务调用方通过注册中心订阅自己感兴趣的服务
- (服务发现)-服务推送(消费者)
  - 注册中心向调用方推送地址列表
- 调用服务(消费者调用提供者)
  - 调用方选择一个地址发起RPC调用
- 监控服务
  - 服务提供方和调用方的统计数据由监控模块收集展示

上面的完整的服务启动订阅与调用流程不仅仅适用于Dubbo 同样也适用于其他服务治理与发现的模型, 一般服务发现与服务调用的思路就是这样的,我们将以上内容扩展,暴漏服务可以使用http,tcp,udp等各种协议,注册服务可以注册到Redis,Dns,Etcd,Zookeeper等注册中心中,订阅服务可以主动去注册中心查询服务列表,服务发现可以让注册中心将服务数据动态推送给消费者.Dubbo其实就是基于这种简单的服务模型来扩展出各种功能的支持,来满足服务治理的各种场景,了解了这里可能各位同学就想着自行开发一个简单的微服务框架了。

##### **Spring Boot**

伴随着SpringBoot容器的启动，Dubbo 主要是做了如下几件事情:

- 将解析属性配置的class 和解析注解（@Service、@Reference等等）配置的class 注册到beanDefinitionMap
- 将解析后的配置类（AnnotationAttributes）和Dubbo的@Service服务，注册到beanDefinitionMap
- 当Spring创建Bean、填充属性时，对@Reference 注解标注的属性做注入（inject）
- 通过监听ContextRefreshedEvent事件，调用DubboBootstrap 启动器，暴露@Service 服务到注册中心

DubboConfigConfigurationRegistrar 用于将不同的属性加载到不同的配置文件中
registerBeans 方法最终通过 ConfigurationBeanBindingsRegister 将解析之后的配置类注册到BeanDefinitionMap
最终在Spring 容器中他们会被初始化成若干对象，例如：dubbo:registry 会转换成org.apache.dubbo.config.RegistryConfig#0


DubboComponentScanRegistrar 主要是用来将ServiceAnnotationBeanPostProcessor 注册到BeanDefinitionMap 中。
在Spring调用BeanFactory相关的后置处理器（invokeBeanFactoryPostProcessors）时，会使用ServiceAnnotationBeanPostProcessor 将@DubboService相关注解注册到BeanDefinitionMap

在 ServiceAnnotationBeanPostProcessor 中，真正做注解解析注册的是他的父类ServiceClassPostProcessor
在ServiceClassPostProcessor 中，它注册了一个dubbo监听器，用于监听Spring容器的刷新、关闭事件，同时也将@DubboService 注解的类注册到了BeanDefinitionMap 中.

伴随着Spring 容器的启动，在invokeBeanFactoryPostProcessors阶段我们注册了dubbo相关的组件到IOC，在finishBeanFactoryInitialization(beanFactory) Dubbo的组件被初始化、实例化，最后Dubbo通过监听Spring事件的方式完成启动器的调用、服务导出等操作

DubboBootstrap 的启动是通过监听Spring事件实现的。Spring会在容器Refresh 的最后一步发送一个事件ContextRefreshedEvent，表示容器刷新完毕

对于ContextRefreshedEvent 事件的监听，最终调用了dubboBootstrap.start() 方法


```java

```

所有的功能都是由导出服务(提供者)开始的,只有提供者先提供了服务才可以有真正的服务让消费者调用

来看一个Provider的启动:

```java
public class Application {

    private static final String REGISTRY_URL = "zookeeper://127.0.0.1:2181";

    public static void main(String[] args) {
        startWithBootstrap();
    }

    private static void startWithBootstrap() {
        ServiceConfig<DemoServiceImpl> service = new ServiceConfig<>();
        service.setInterface(DemoService.class);
        service.setRef(new DemoServiceImpl());

        DubboBootstrap bootstrap = DubboBootstrap.getInstance();
        bootstrap
                .application(new ApplicationConfig("dubbo-demo-api-provider"))
                .registry(new RegistryConfig(REGISTRY_URL))
                .protocol(new ProtocolConfig(CommonConstants.DUBBO, -1))
                .service(service)
                .start()
                .await();
    }
}
```



### DubboBootstrap

Dubbo3 往云原生的方向走自然要针对云原生应用的应用启动，应用运行，应用发 布等信息做一些建模，这个 DubboBootstrap 就是用来启动 Dubbo 服务的。类似 于 Netty 的 Bootstrap 类型和 ServerBootstrap 启动器





通过调用静态方法 getInstance()获取单例实例。之所以设计为单例，是因为 Dubbo 中的一些类(如 ExtensionLoader)只为每个进程设计一个实例

instanceMap设计为Map<ApplicationModel, DubboBootstrap>类型, 意味着可以为多个应用程序模型创建不同的启动器,启动多个服务

```java
public final class DubboBootstrap {
 
    private static final ConcurrentMap<ApplicationModel, DubboBootstrap> instanceMap = new ConcurrentHashMap<>();
    private static volatile DubboBootstrap instance;   
    
    public static DubboBootstrap getInstance() {
            if (instance == null) {
                synchronized (DubboBootstrap.class) {
                    if (instance == null) {
                        instance = DubboBootstrap.getInstance(ApplicationModel.defaultModel());
                    }
                }
            }
            return instance;
        }
    
    public static DubboBootstrap getInstance(ApplicationModel applicationModel) {
        return ConcurrentHashMapUtils.computeIfAbsent(
                instanceMap, applicationModel, _k -> new DubboBootstrap(applicationModel));
    }
}
```



构造器

```java
private DubboBootstrap(ApplicationModel applicationModel) {
    this.applicationModel = applicationModel;
    configManager = applicationModel.getApplicationConfigManager();
    environment = applicationModel.modelEnvironment();

    executorRepository = ExecutorRepository.getInstance(applicationModel);
    applicationDeployer = applicationModel.getDeployer();
    // listen deploy events
    applicationDeployer.addDeployListener(new DeployListenerAdapter<ApplicationModel>() {
        @Override
        public void onStarted(ApplicationModel scopeModel) {
            notifyStarted(applicationModel);
        }

        @Override
        public void onStopped(ApplicationModel scopeModel) {
            notifyStopped(applicationModel);
        }

        @Override
        public void onFailure(ApplicationModel scopeModel, Throwable cause) {
            notifyStopped(applicationModel);
        }
    });
    // register DubboBootstrap bean
    applicationModel.getBeanFactory().registerBean(this);
}
```



DubboBootstrap的application方法设置一个应用程序配置ApplicationConfig对象

```java
 public DubboBootstrap application(ApplicationConfig applicationConfig) {
        //将启动器构造器中初始化的默认应用程序模型对象传递给配置对象
        applicationConfig.setScopeModel(applicationModel);
        //将配置信息添加到配置管理器中
        configManager.setApplication(applicationConfig);
        return this;
    }
```

ConfigManager配置管理器

### ApplicationDeployer

来看DubboBootstrap的start()方法:

DubboBootstrap借助DeployerDeployer来启动和发布服务,发布器的启动过程包含了启动配置中心,加载配置,启动元数据中心,启动服务等操作都是比较重要又比较复杂的过程

```java
public DubboBootstrap start() {
        //调用重载的方法进行启动参数代表是否等待启动结束
        this.start(true);
        return this;
    }

public DubboBootstrap start(boolean wait) {
    Future future = applicationDeployer.start();
    if (wait) {
        try {
            future.get();
        } catch (Exception e) {
            throw new IllegalStateException("await dubbo application start finish failure", e);
        }
    }
    return this;
}
```



发布器包含

- 应用发布器ApplicationDeployer用于初始化并启动应用程序实例
- 模块发布器ModuleDeployer 模块（服务）的导出/引用服务

两种发布器有各自的接口，他们都继承了抽象的发布器AbstractDeployer 封装了一些公共的操作比如状态切换，状态查询的逻辑

### ApplicationDeployer::start



initialize包含注册中心和元数据中心等初始化 而doStart 是服务的

```java
public Future start() {
    synchronized (startLock) {
        if (isStopping() || isStopped() || isFailed()) {
            throw new IllegalStateException(getIdentifier() + " is stopping or stopped, can not start again");
        }

        try {
            // maybe call start again after add new module, check if any new module
            boolean hasPendingModule = hasPendingModule();

            if (isStarting()) {
                // currently, is starting, maybe both start by module and application
                // if it has new modules, start them
                if (hasPendingModule) {
                    startModules();
                }
                // if it is starting, reuse previous startFuture
                return startFuture;
            }

            // if is started and no new module, just return
            if (isStarted() && !hasPendingModule) {
                return CompletableFuture.completedFuture(false);
            }

            // pending -> starting : first start app
            // started -> starting : re-start app
            onStarting();

            initialize();

            doStart();
        } catch (Throwable e) {
            onFailed(getIdentifier() + " start failure", e);
            throw e;
        }

        return startFuture;
    }
}
```

### initialize



```java
@Override
public void initialize() {
    if (initialized) {
        return;
    }
    // Ensure that the initialization is completed when concurrent calls
    synchronized (startLock) {
        if (initialized) {
            return;
        }
        onInitialize();

        // register shutdown hook
        registerShutdownHook();

        startConfigCenter();

        loadApplicationConfigs();

        initModuleDeployers();

        initMetricsReporter();

        initMetricsService();

        // @since 2.7.8
        startMetadataCenter();

        initialized = true;
    }
}
```



Dubbo 配置加载大概分为两个阶段
- 第一阶段为 DubboBootstrap 初始化之前，在 Spring context 启动时解析处理 XML 配置/注解配置/Java-config 或者是执行 API 配置代码，创建 config bean 并且加入到 ConfigManager 中。 
- 第二阶段为 DubboBootstrap 初始化过程，从配置中心读取外部配置，依次处 理实例级属性配置和应用级属性配置，最后刷新所有配置实例的属性，也就是 属性覆盖


发生属性覆盖可能有两种情况，并且二者可能是会同时发生的：
- 不同配置源配置了相同的配置项。
- 相同配置源，但在不同层次指定了相同的配置项。

属性覆盖处理流程： 按照优先级从高到低依次查找，如果找到此前缀开头的属性，则选定使用这个前缀 提取属性，忽略后面的配置。


DubboBootstrap 就是用来启动 Dubbo 服务的。类似 于 Netty 的 Bootstrap 类型和 ServerBootstrap 启动器


Dubbo 的 bootstrap 类为啥要用单例模式。 通过调用静态方法 getInstance()获取单例实例。之所以设计为单例，是因为 Dubbo 中的一些类（如 ExtensionLoader）只为每个进程设计一个实例。



[DefaultApplicationDeployer.startConfigCenter()](/docs/CS/Framework/Dubbo/Start.md)


通过 ls / 查看根目录，我们发现 Dubbo 注册了两个目录，/dubbo 和 /services 目录：
Dubbo 3.x 推崇的一个应用级注册新特性，在不改变任何 Dubbo 配置的情况下，可以兼 容一个应用从 2.x 版本平滑升级到 3.x 版本，这个新特性主要是为了将来能支持十万甚至百万 的集群实例地址发现，并且可以与不同的微服务体系实现地址发现互联互通
增加了对services目录下的应用级注册功能

你可以通过在提供方设置 dubbo.application.register-mode 属性来自由控制

- interface：只接口级注册。 
- instance：只应用级注册。 
- all：接口级注册、应用级注册都会存在，同时也是默认值。

Consumer

可以考虑在消费方的 Dubbo XML 配置文件中，为 DemoFacade 服务添加 check="false" 的属性，来达到启动不检查服务的目的，


dubbo目录下各服务注册里有consumer
所以通过一个 interface，我们就能从注 册中心查看有哪些提供方应用节点、哪些消费方应用节点。

在消费方侧也存在如何抉择的问题，到 底是订阅接口级注册信息，还是订阅应用级注册信息呢

其实 Dubbo 也为我们提供了过渡的兼容方案，你可以通过在消费方设置 dubbo.application.service-discovery.migration 属性来兼容新老订阅方案

FORCE_INTERFACE：只订阅消费接口级信息。 APPLICATION_FIRST：注册中心有应用级注册信息则订阅应用级信息，否则订阅接口级信 息，起到了智能决策来兼容过渡方案。 FORCE_APPLICATION：只订阅应用级信息

不过总有调用不顺畅的时候，尤其是在提供方服务有点耗时的情况下，你可能会遇到这样的异 常信息

源码中默认的超时时间，可以从这段代码中查看，是 1000ms：

除了网络抖动影响调用，更多时候可能因为有些服务器故障了，比如消费方调着调着，提供方 突然就挂了，消费方如果换台提供方，继续重试调用一下也许就正常了，所以你可以继续设置failover容错策略
常用容错策略有

### doStart

发布服务 先启动内部服务，再启动外部服务 不论是内部服务还是外部服务调用的代码逻辑都是模块发布器 ModuleDeployer 的 start()方法，

```java
private void doStart() {
    startModules();
}

private void startModules() {
    // ensure init and start internal module first
    prepareInternalModule();

    // filter and start pending modules, ignore new module during starting, throw exception of module start
    for (ModuleModel moduleModel : applicationModel.getModuleModels()) {
        if (moduleModel.getDeployer().isPending()) {
        moduleModel.getDeployer().start();
        }
    }
}
```




容错设置帮我们尽可能保障服务稳定调用，但调用也有流量高低之分，流量低的时候可能你发 现不了什么特殊情况，一旦流量比较高，你可能会发现提供方总是有那么几台服务器流量特别 高，另外几个服务器流量特别低。 这是因为 Dubbo 默认使用的是 loadbalance="random" 随机类型的负载均衡策略，为了尽 可能雨露均沾调用到提供方各个节点，你可以继续设置 loadbalance="roundrobin" 来进 行轮询调用


Dubbo 线程池总数默认是固定的，200 个，

采用上下文对象来存储，那异步化的结果也就毋庸置疑存储在上下文对象中。

Dubbo 异步实现原理

首先，还是定义线程池对象，在 Dubbo 中 RpcContext.startAsync 方法意味着异步模式的开 启：

最终是通过 CAS 原子性的方式创建了一个 java.util.concurrent.CompletableFuture 对象，这个对象就存储在当前的上下文 org.apache.dubbo.rpc.RpcContextAttachment 对象中。

asyncContext 富含上下文信息，只需要把这个所谓的 asyncContext 对象传入到子线程 中，然后将 asyncContext 中的上下文信息充分拷贝到子线程中，这样，子线程处理所需要的 任何信息就不会因为开启了异步化处理而缺失

Dubbo 用 asyncContext.write 写入异步结果，通过 write 方法的查看，最终我们的异步化结果 是存入了 java.util.concurrent.CompletableFuture 对象中，这样拦截处只需要调用 java.util.concurrent.CompletableFuture#get(long timeout, TimeUnit unit) 方法就可以很轻松地 拿到异步化结果了。


日志追踪 使用FIlter
隐式传递trace id 到rpc context中

```java
@Override
public Future start() throws IllegalStateException {
    // initialize，maybe deadlock applicationDeployer lock & moduleDeployer lock
    applicationDeployer.initialize();

    return startSync();
}
```



```java
private synchronized Future startSync() throws IllegalStateException {
    if (isStopping() || isStopped() || isFailed()) {
        throw new IllegalStateException(getIdentifier() + " is stopping or stopped, can not start again");
    }

    try {
        if (isStarting() || isStarted()) {
            return startFuture;
        }

        onModuleStarting();

        initialize();

        // export services
        exportServices();

        // prepare application instance
        // exclude internal module to avoid wait itself
        if (moduleModel != moduleModel.getApplicationModel().getInternalModule()) {
            applicationDeployer.prepareInternalModule();
        }

        // refer services
        referServices();

        // if no async export/refer services, just set started
        if (asyncExportingFutures.isEmpty() && asyncReferringFutures.isEmpty()) {
            // publish module started event
            onModuleStarted();

            // register services to registry
            registerServices();

            // check reference config
            checkReferences();

            // complete module start future after application state changed
            completeStartFuture(true);
        } else {
            frameworkExecutorRepository.getSharedExecutor().submit(() -> {
                try {
                    // wait for export finish
                    waitExportFinish();
                    // wait for refer finish
                    waitReferFinish();

                    // publish module started event
                    onModuleStarted();

                    // register services to registry
                    registerServices();

                    // check reference config
                    checkReferences();
                } catch (Throwable e) {
                    logger.warn(
                            CONFIG_FAILED_WAIT_EXPORT_REFER,
                            "",
                            "",
                            "wait for export/refer services occurred an exception",
                            e);
                    onModuleFailed(getIdentifier() + " start failed: " + e, e);
                } finally {
                    // complete module start future after application state changed
                    completeStartFuture(true);
                }
            });
        }

    } catch (Throwable e) {
        onModuleFailed(getIdentifier() + " start failed: " + e, e);
        throw e;
    }

    return startFuture;
}
```



## Config

Enables Dubbo components as Spring Beans, equals `DubboComponentScan` and `EnableDubboConfig` combination.

**Note**: `EnableDubbo` must base on Spring Framework 4.2 and above

```java
@Target({ElementType.TYPE})
@Retention(RetentionPolicy.RUNTIME)
@Inherited
@Documented
@EnableDubboConfig
@DubboComponentScan
public @interface EnableDubbo {
    
    @AliasFor(annotation = DubboComponentScan.class, attribute = "basePackages")
    String[] scanBasePackages() default {};

    @AliasFor(annotation = DubboComponentScan.class, attribute = "basePackageClasses")
    Class<?>[] scanBasePackageClasses() default {};

    @AliasFor(annotation = EnableDubboConfig.class, attribute = "multiple")
    boolean multipleConfig() default true;

}
```

### Registrar

registerBeanDefinitions


```java
@Target({ElementType.TYPE})
@Retention(RetentionPolicy.RUNTIME)
@Inherited
@Documented
@Import(DubboConfigConfigurationRegistrar.class)
public @interface EnableDubboConfig {

    boolean multiple() default true;

}

public class DubboConfigConfigurationRegistrar implements ImportBeanDefinitionRegistrar, ApplicationContextAware {

    private ConfigurableApplicationContext applicationContext;

    @Override
    public void registerBeanDefinitions(AnnotationMetadata importingClassMetadata, BeanDefinitionRegistry registry) {

        AnnotationAttributes attributes = AnnotationAttributes.fromMap(
                importingClassMetadata.getAnnotationAttributes(EnableDubboConfig.class.getName()));

        boolean multiple = attributes.getBoolean("multiple");

        // Single Config Bindings
        registerBeans(registry, DubboConfigConfiguration.Single.class);

        if (multiple) { // Since 2.6.6 https://github.com/apache/dubbo/issues/3193
            registerBeans(registry, DubboConfigConfiguration.Multiple.class);
        }

        // Since 2.7.6
        registerCommonBeans(registry);
    }
}
```



### ServiceClassPostProcessor

```java
public class ServiceClassPostProcessor implements BeanDefinitionRegistryPostProcessor, EnvironmentAware,
        ResourceLoaderAware, BeanClassLoaderAware {

    private static final List<Class<? extends Annotation>> serviceAnnotationTypes = asList(
            // @since 2.7.7 Add the @DubboService , the issue : https://github.com/apache/dubbo/issues/6007
            DubboService.class,
            // @since 2.7.0 the substitute @com.alibaba.dubbo.config.annotation.Service
            Service.class,
            // @since 2.7.3 Add the compatibility for legacy Dubbo's @Service , the issue : https://github.com/apache/dubbo/issues/4330
            com.alibaba.dubbo.config.annotation.Service.class
    );


    @Override
    public void postProcessBeanDefinitionRegistry(BeanDefinitionRegistry registry) throws BeansException {

        // @since 2.7.5
        registerInfrastructureBean(registry, DubboBootstrapApplicationListener.BEAN_NAME, DubboBootstrapApplicationListener.class);

        Set<String> resolvedPackagesToScan = resolvePackagesToScan(packagesToScan);

        if (!CollectionUtils.isEmpty(resolvedPackagesToScan)) {
            registerServiceBeans(resolvedPackagesToScan, registry);
        }
    }
}
```

#### registerServiceBeans

```java
private void registerServiceBeans(Set<String> packagesToScan, BeanDefinitionRegistry registry) {

    DubboClassPathBeanDefinitionScanner scanner =
            new DubboClassPathBeanDefinitionScanner(registry, environment, resourceLoader);

    BeanNameGenerator beanNameGenerator = resolveBeanNameGenerator(registry);

    scanner.setBeanNameGenerator(beanNameGenerator);

    // refactor @since 2.7.7
    serviceAnnotationTypes.forEach(annotationType -> {
        scanner.addIncludeFilter(new AnnotationTypeFilter(annotationType));
    });

    for (String packageToScan : packagesToScan) {
        // Registers @Service Bean first
        scanner.scan(packageToScan);
        // Finds all BeanDefinitionHolders of @Service whether @ComponentScan scans or not.
        Set<BeanDefinitionHolder> beanDefinitionHolders =
                findServiceBeanDefinitionHolders(scanner, packageToScan, registry, beanNameGenerator);
        if (!CollectionUtils.isEmpty(beanDefinitionHolders)) {
            for (BeanDefinitionHolder beanDefinitionHolder : beanDefinitionHolders) {
                registerServiceBean(beanDefinitionHolder, registry, scanner);
            }
        } else {}
	}
}

private BeanNameGenerator resolveBeanNameGenerator(BeanDefinitionRegistry registry) {
    BeanNameGenerator beanNameGenerator = null;

    if (registry instanceof SingletonBeanRegistry) {
        SingletonBeanRegistry singletonBeanRegistry = SingletonBeanRegistry.class.cast(registry);
        beanNameGenerator = (BeanNameGenerator) singletonBeanRegistry.getSingleton(CONFIGURATION_BEAN_NAME_GENERATOR);
    }

    if (beanNameGenerator == null) {
        beanNameGenerator = new AnnotationBeanNameGenerator();
    }
    return beanNameGenerator;
}
```




## Provider

### doExport


Invoked after publish ContextRefreshedEvent in [Spring finishRefresh](/docs/CS/Framework/Spring/IoC.md?id=finishRefresh)

```java
public class DubboBootstrapApplicationListener extends OnceApplicationContextEventListener implements Ordered {

    @Override
    public void onApplicationContextEvent(ApplicationContextEvent event) {
        if (DubboBootstrapStartStopListenerSpringAdapter.applicationContext == null) {
            DubboBootstrapStartStopListenerSpringAdapter.applicationContext = event.getApplicationContext();
        }
        if (event instanceof ContextRefreshedEvent) {
            onContextRefreshedEvent((ContextRefreshedEvent) event);
        } else if (event instanceof ContextClosedEvent) {
            onContextClosedEvent((ContextClosedEvent) event);
        }
    }

    private void onContextRefreshedEvent(ContextRefreshedEvent event) {
        dubboBootstrap.start();
    }
}
```


```java
// ServiceConfig#doExport()
protected synchronized void doExport() {
    if (exported) {
        return;
    }
    exported = true;

    if (StringUtils.isEmpty(path)) {
        path = interfaceName;
    }
    doExportUrls();
    bootstrap.setReady(true);
}
```
#### doExportUrls

```java
private void doExportUrls() {
  ServiceRepository repository = ApplicationModel.getServiceRepository();
  ServiceDescriptor serviceDescriptor = repository.registerService(getInterfaceClass());
  repository.registerProvider(
    getUniqueServiceName(),
    ref,
    serviceDescriptor,
    this,
    serviceMetadata
  );

  List<URL> registryURLs = ConfigValidationUtils.loadRegistries(this, true);

  int protocolConfigNum = protocols.size();
  for (ProtocolConfig protocolConfig : protocols) {
    String pathKey = URL.buildKey(getContextPath(protocolConfig)
                                  .map(p -> p + "/" + path)
                                  .orElse(path), group, version);
    // In case user specified path, register service one more time to map it to path.
    repository.registerService(pathKey, interfaceClass);
    doExportUrlsFor1Protocol(protocolConfig, registryURLs, protocolConfigNum);
  }
}

```

##### doExportUrlsFor1Protocol

export either local or remote, not both

if remote:

1. use [ProxyFactory](/docs/CS/Framework/Dubbo/Start.md?id=proxy) wrap Invoker
2. may export no registries
3. may only injvm
4. add monitor
5. export registry



```java
// ServiceConfig
private void doExportUrlsFor1Protocol(ProtocolConfig protocolConfig, List<URL> registryURLs, int protocolConfigNum) {
    String name = protocolConfig.getName();
    if (StringUtils.isEmpty(name)) {
        name = DUBBO;
    }

    Map<String, String> map = new HashMap<String, String>();
    map.put(SIDE_KEY, PROVIDER_SIDE);

    ServiceConfig.appendRuntimeParameters(map);
    AbstractConfig.appendParameters(map, getMetrics());
    AbstractConfig.appendParameters(map, getApplication());
    AbstractConfig.appendParameters(map, getModule());
    // remove 'default.' prefix for configs from ProviderConfig
    // appendParameters(map, provider, Constants.DEFAULT_KEY);
    AbstractConfig.appendParameters(map, provider);
    AbstractConfig.appendParameters(map, protocolConfig);
    AbstractConfig.appendParameters(map, this);
    MetadataReportConfig metadataReportConfig = getMetadataReportConfig();
    if (metadataReportConfig != null && metadataReportConfig.isValid()) {
        map.putIfAbsent(METADATA_KEY, REMOTE_METADATA_STORAGE_TYPE);
    }
    if (CollectionUtils.isNotEmpty(getMethods())) {
        for (MethodConfig method : getMethods()) {
            AbstractConfig.appendParameters(map, method, method.getName());
            String retryKey = method.getName() + RETRY_SUFFIX;
            if (map.containsKey(retryKey)) {
                String retryValue = map.remove(retryKey);
                if (FALSE_VALUE.equals(retryValue)) {
                    map.put(method.getName() + RETRIES_SUFFIX, ZERO_VALUE);
                }
            }
            List<ArgumentConfig> arguments = method.getArguments();
            if (CollectionUtils.isNotEmpty(arguments)) {
                for (ArgumentConfig argument : arguments) {
                    // convert argument type
                    if (argument.getType() != null && argument.getType().length() > 0) {
                        Method[] methods = interfaceClass.getMethods();
                        // visit all methods
                        if (methods.length > 0) {
                            for (int i = 0; i < methods.length; i++) {
                                String methodName = methods[i].getName();
                                // target the method, and get its signature
                                if (methodName.equals(method.getName())) {
                                    Class<?>[] argtypes = methods[i].getParameterTypes();
                                    // one callback in the method
                                    if (argument.getIndex() != -1) {
                                        if (argtypes[argument.getIndex()].getName().equals(argument.getType())) {
                                            AbstractConfig
                                                    .appendParameters(map, argument, method.getName() + "." + argument.getIndex());
                                        } else {
                                            throw new IllegalArgumentException("");
                                        }
                                    } else {
                                        // multiple callbacks in the method
                                        for (int j = 0; j < argtypes.length; j++) {
                                            Class<?> argclazz = argtypes[j];
                                            if (argclazz.getName().equals(argument.getType())) {
                                                AbstractConfig.appendParameters(map, argument, method.getName() + "." + j);
                                                if (argument.getIndex() != -1 && argument.getIndex() != j) {
                                                    throw new IllegalArgumentException("");
                        }		}		}		}		}		}		}
                    } else if (argument.getIndex() != -1) {
                        AbstractConfig.appendParameters(map, argument, method.getName() + "." + argument.getIndex());
                    } else {throw new IllegalArgumentException("");}
            }		}
        } // end of methods for
    }

    if (ProtocolUtils.isGeneric(generic)) {
        map.put(GENERIC_KEY, generic);
        map.put(METHODS_KEY, ANY_VALUE);
    } else {
        String revision = Version.getVersion(interfaceClass, version);
        if (revision != null && revision.length() > 0) {
            map.put(REVISION_KEY, revision);
        }

        String[] methods = Wrapper.getWrapper(interfaceClass).getMethodNames();
        if (methods.length == 0) {
            map.put(METHODS_KEY, ANY_VALUE);
        } else {
            map.put(METHODS_KEY, StringUtils.join(new HashSet<String>(Arrays.asList(methods)), ","));
        }
    }

    /**
     * Here the token value configured by the provider is used to assign the value to ServiceConfig#token
     */
    if (ConfigUtils.isEmpty(token) && provider != null) {
        token = provider.getToken();
    }

    if (!ConfigUtils.isEmpty(token)) {
        if (ConfigUtils.isDefault(token)) {
            map.put(TOKEN_KEY, UUID.randomUUID().toString());
        } else {
            map.put(TOKEN_KEY, token);
        }
    }
    //init serviceMetadata attachments
    serviceMetadata.getAttachments().putAll(map);

    // export service
    String host = findConfigedHosts(protocolConfig, registryURLs, map);
    Integer port = findConfigedPorts(protocolConfig, name, map, protocolConfigNum);
    URL url = new URL(name, host, port, getContextPath(protocolConfig).map(p -> p + "/" + path).orElse(path), map);

    // You can customize Configurator to append extra parameters
    if (ExtensionLoader.getExtensionLoader(ConfiguratorFactory.class)
            .hasExtension(url.getProtocol())) {
        url = ExtensionLoader.getExtensionLoader(ConfiguratorFactory.class)
                .getExtension(url.getProtocol()).getConfigurator(url).configure(url);
    }

    String scope = url.getParameter(SCOPE_KEY);
    // don't export when none is configured
    if (!SCOPE_NONE.equalsIgnoreCase(scope)) {

        // export to local if the config is not remote (export to remote only when config is remote)
        if (!SCOPE_REMOTE.equalsIgnoreCase(scope)) {
            exportLocal(url);
        }
        // export to remote if the config is not local (export to local only when config is local)
        if (!SCOPE_LOCAL.equalsIgnoreCase(scope)) {
            if (CollectionUtils.isNotEmpty(registryURLs)) {
                for (URL registryURL : registryURLs) {
                    if (SERVICE_REGISTRY_PROTOCOL.equals(registryURL.getProtocol())) {
                        url = url.addParameterIfAbsent(SERVICE_NAME_MAPPING_KEY, "true");
                    }

                    //if protocol is only injvm ,not register
                    if (LOCAL_PROTOCOL.equalsIgnoreCase(url.getProtocol())) {
                        continue;
                    }
                    url = url.addParameterIfAbsent(DYNAMIC_KEY, registryURL.getParameter(DYNAMIC_KEY));
                    URL monitorUrl = ConfigValidationUtils.loadMonitor(this, registryURL);
                    if (monitorUrl != null) {
                        url = url.addParameterAndEncoded(MONITOR_KEY, monitorUrl.toFullString());
                    }

                    // For providers, this is used to enable custom proxy to generate invoker
                    String proxy = url.getParameter(PROXY_KEY);
                    if (StringUtils.isNotEmpty(proxy)) {
                        registryURL = registryURL.addParameter(PROXY_KEY, proxy);
                    }

                    Invoker<?> invoker = PROXY_FACTORY.getInvoker(ref, (Class) interfaceClass,
                            registryURL.addParameterAndEncoded(EXPORT_KEY, url.toFullString()));
                    DelegateProviderMetaDataInvoker wrapperInvoker = new DelegateProviderMetaDataInvoker(invoker, this);

                    Exporter<?> exporter = PROTOCOL.export(wrapperInvoker);
                    exporters.add(exporter);
                }
            } else { // no registries
                Invoker<?> invoker = PROXY_FACTORY.getInvoker(ref, (Class) interfaceClass, url);
                DelegateProviderMetaDataInvoker wrapperInvoker = new DelegateProviderMetaDataInvoker(invoker, this);

                Exporter<?> exporter = PROTOCOL.export(wrapperInvoker);
                exporters.add(exporter);
            }

            MetadataUtils.publishServiceDefinition(url);
        }
    }
    this.urls.add(url);
}
```



if has Registry

### RegistryProtocol

TODO, replace RegistryProtocol completely in the future.

doLocalExport by actual Protocol, such as `DubboProtocol`

closure by `ExporterChangeableWrapper`

```java
// RegistryProtocol#export()
@Override
public <T> Exporter<T> export(final Invoker<T> originInvoker) throws RpcException {
    URL registryUrl = getRegistryUrl(originInvoker);
    // url to export locally
    URL providerUrl = getProviderUrl(originInvoker);

    // Subscribe the override data
    // FIXME When the provider subscribes, it will affect the scene : a certain JVM exposes the service and call
    //  the same service. Because the subscribed is cached key with the name of the service, it causes the
    //  subscription information to cover.
    final URL overrideSubscribeUrl = getSubscribedOverrideUrl(providerUrl);
    final OverrideListener overrideSubscribeListener = new OverrideListener(overrideSubscribeUrl, originInvoker);
    overrideListeners.put(overrideSubscribeUrl, overrideSubscribeListener);

    providerUrl = overrideUrlWithConfig(providerUrl, overrideSubscribeListener);
    // export invoker
    final ExporterChangeableWrapper<T> exporter = doLocalExport(originInvoker, providerUrl);

    // url to registry
    final Registry registry = getRegistry(originInvoker);
    final URL registeredProviderUrl = getUrlToRegistry(providerUrl, registryUrl);

    // decide if we need to delay publish
    boolean register = providerUrl.getParameter(REGISTER_KEY, true);
    if (register) {
        registry.register(registeredProviderUrl);
    }

    // register stated url on provider model
    registerStatedUrl(registryUrl, registeredProviderUrl, register);


    exporter.setRegisterUrl(registeredProviderUrl);
    exporter.setSubscribeUrl(overrideSubscribeUrl);

    // Deprecated! Subscribe to override rules in 2.6.x or before.
    registry.subscribe(overrideSubscribeUrl, overrideSubscribeListener);

    notifyExport(exporter);
    //Ensure that a new exporter instance is returned every time export
    return new DestroyableExporter<>(exporter);
}
```



#### doLocalExport

```java
// RegistryProtocol#doLocalExport()
@SuppressWarnings("unchecked")
private <T> ExporterChangeableWrapper<T> doLocalExport(final Invoker<T> originInvoker, URL providerUrl) {
    String key = getCacheKey(originInvoker);

    return (ExporterChangeableWrapper<T>) bounds.computeIfAbsent(key, s -> {
        Invoker<?> invokerDelegate = new InvokerDelegate<>(originInvoker, providerUrl);
        return new ExporterChangeableWrapper<>((Exporter<T>) protocol.export(invokerDelegate), originInvoker);
    });
}
```



`DubboProtocol#export()` -> openServer ->createServer ->  Exchangers.bind() -> HeaderExchangeServer -> Transporters.bind() -> NettyTransporter -> new NettyServer() -> doOpen -> `ServerBootstrap#bind()`

```java
@Override
public <T> Exporter<T> export(Invoker<T> invoker) throws RpcException {
    URL url = invoker.getUrl();

    // export service.
    String key = serviceKey(url);
    DubboExporter<T> exporter = new DubboExporter<T>(invoker, key, exporterMap);
    exporterMap.addExportMap(key, exporter);

    //export an stub service for dispatching event
    Boolean isStubSupportEvent = url.getParameter(STUB_EVENT_KEY, DEFAULT_STUB_EVENT);
    Boolean isCallbackservice = url.getParameter(IS_CALLBACK_SERVICE, false);
    if (isStubSupportEvent && !isCallbackservice) {
        String stubServiceMethods = url.getParameter(STUB_EVENT_METHODS_KEY);
        if (stubServiceMethods == null || stubServiceMethods.length() == 0) {}
    }

    openServer(url);
    optimizeSerialization(url);

    return exporter;
}
```



### exportLocal

```java
/** ServiceConfig#exportLocal()
 * always export injvm
 */
private void exportLocal(URL url) {
    URL local = URLBuilder.from(url)
            .setProtocol(LOCAL_PROTOCOL)
            .setHost(LOCALHOST_VALUE)
            .setPort(0)
            .build();
    Exporter<?> exporter = PROTOCOL.export(
            PROXY_FACTORY.getInvoker(ref, (Class) interfaceClass, local));
    exporters.add(exporter);
}

// InjvmProtocol#export()
@Override
public <T> Exporter<T> export(Invoker<T> invoker) throws RpcException {
  String serviceKey = invoker.getUrl().getServiceKey();
  InjvmExporter<T> tInjvmExporter = new InjvmExporter<>(invoker, serviceKey, exporterMap);
  exporterMap.addExportMap(serviceKey, tInjvmExporter);
  return tInjvmExporter;
}
```





## Consumer

### createProxy

all of scenarios need to create [Proxy](/docs/CS/Framework/Dubbo/Start.md?id=proxy) :

1. shouldJvmRefer
2. one registry
3. multiple registries
4. Cluster

```java
// ReferenceConfig
@SuppressWarnings({"unchecked", "rawtypes", "deprecation"})
private T createProxy(Map<String, String> map) {
    if (shouldJvmRefer(map)) {	// injvm or same JVM
        URL url = new URL(LOCAL_PROTOCOL, LOCALHOST_VALUE, 0, interfaceClass.getName()).addParameters(map);
        invoker = REF_PROTOCOL.refer(interfaceClass, url);
    } else {
        urls.clear();
        if (url != null && url.length() > 0) { // user specified URL, could be peer-to-peer address, or register center's address.
            String[] us = SEMICOLON_SPLIT_PATTERN.split(url);
            if (us != null && us.length > 0) {
                for (String u : us) {
                    URL url = URL.valueOf(u);
                    if (StringUtils.isEmpty(url.getPath())) {
                        url = url.setPath(interfaceName);
                    }
                    if (UrlUtils.isRegistry(url)) {
                        urls.add(url.addParameterAndEncoded(REFER_KEY, StringUtils.toQueryString(map)));
                    } else {
                        urls.add(ClusterUtils.mergeUrl(url, map));
                    }
                }
            }
        } else { // assemble URL from register center's configuration
            // if protocols not injvm checkRegistry
            if (!LOCAL_PROTOCOL.equalsIgnoreCase(getProtocol())) {
                checkRegistry();
                List<URL> us = ConfigValidationUtils.loadRegistries(this, false);
                if (CollectionUtils.isNotEmpty(us)) {
                    for (URL u : us) {
                        URL monitorUrl = ConfigValidationUtils.loadMonitor(this, u);
                        if (monitorUrl != null) {
                            map.put(MONITOR_KEY, URL.encode(monitorUrl.toFullString()));
                        }
                        urls.add(u.addParameterAndEncoded(REFER_KEY, StringUtils.toQueryString(map)));
                    }
                }
                if (urls.isEmpty()) {
                    throw new IllegalStateException("");
                }
            }
        }

        if (urls.size() == 1) {
            invoker = REF_PROTOCOL.refer(interfaceClass, urls.get(0));
        } else {
            List<Invoker<?>> invokers = new ArrayList<Invoker<?>>();
            URL registryURL = null;
            for (URL url : urls) {
                // For multi-registry scenarios, it is not checked whether each referInvoker is available.
                // Because this invoker may become available later.
                invokers.add(REF_PROTOCOL.refer(interfaceClass, url));

                if (UrlUtils.isRegistry(url)) {
                    registryURL = url; // use last registry url
                }
            }

            if (registryURL != null) { // registry url is available
                // for multi-subscription scenario, use 'zone-aware' policy by default
                String cluster = registryURL.getParameter(CLUSTER_KEY, ZoneAwareCluster.NAME);
                // The invoker wrap sequence would be: ZoneAwareClusterInvoker(StaticDirectory) -> FailoverClusterInvoker(RegistryDirectory, routing happens here) -> Invoker
                invoker = Cluster.getCluster(cluster, false).join(new StaticDirectory(registryURL, invokers));
            } else { // not a registry url, must be direct invoke.
                String cluster = CollectionUtils.isNotEmpty(invokers)
                        ?
                        (invokers.get(0).getUrl() != null ? invokers.get(0).getUrl().getParameter(CLUSTER_KEY, ZoneAwareCluster.NAME) :
                                Cluster.DEFAULT)
                        : Cluster.DEFAULT;
                invoker = Cluster.getCluster(cluster).join(new StaticDirectory(invokers));
            }
        }
    }
    URL consumerURL = new URL(CONSUMER_PROTOCOL, map.remove(REGISTER_IP_KEY), 0, map.get(INTERFACE_KEY), map);
    MetadataUtils.publishServiceDefinition(consumerURL);

    // create service proxy
    return (T) PROXY_FACTORY.getProxy(invoker, ProtocolUtils.isGeneric(generic));
}
```



### refer

```java
// RegistryProtocol
@Override
@SuppressWarnings("unchecked")
public <T> Invoker<T> refer(Class<T> type, URL url) throws RpcException {
    url = getRegistryUrl(url);
    Registry registry = getRegistry(url); // getRegistry
    if (RegistryService.class.equals(type)) {
        return proxyFactory.getInvoker((T) registry, type, url);
    }

    // group="a,b" or group="*"
    Map<String, String> qs = StringUtils.parseQueryString(url.getParameterAndDecoded(REFER_KEY));
    String group = qs.get(GROUP_KEY);
    if (group != null && group.length() > 0) {
        if ((COMMA_SPLIT_PATTERN.split(group)).length > 1 || "*".equals(group)) {
            return doRefer(Cluster.getCluster(MergeableCluster.NAME), registry, type, url, qs);
        }
    }

    Cluster cluster = Cluster.getCluster(qs.get(CLUSTER_KEY));
    return doRefer(cluster, registry, type, url, qs);
}


protected <T> Invoker<T> doRefer(Cluster cluster, Registry registry, Class<T> type, URL url, Map<String, String> parameters) {
  URL consumerUrl = new URL(CONSUMER_PROTOCOL, parameters.remove(REGISTER_IP_KEY), 0, type.getName(), parameters);
  ClusterInvoker<T> migrationInvoker = getMigrationInvoker(this, cluster, registry, type, url, consumerUrl);
  return interceptInvoker(migrationInvoker, url, consumerUrl);
}
```





```java
// AbstractProtocol
@Override
public <T> Invoker<T> refer(Class<T> type, URL url) throws RpcException {
  return new AsyncToSyncInvoker<>(protocolBindingRefer(type, url));
}


protected abstract <T> Invoker<T> protocolBindingRefer(Class<T> type, URL url) throws RpcException;

// DubboProtocol
@Override
public <T> Invoker<T> protocolBindingRefer(Class<T> serviceType, URL url) throws RpcException {
  optimizeSerialization(url);

  // create rpc invoker.
  DubboInvoker<T> invoker = new DubboInvoker<T>(serviceType, url, getClients(url), invokers);
  invokers.add(invoker);

  return invoker;
}

private ExchangeClient[] getClients(URL url) {
  // whether to share connection
  int connections = url.getParameter(CONNECTIONS_KEY, 0);
  // if not configured, connection is shared, otherwise, one connection for one service
  if (connections == 0) {
    /*
             * The xml configuration should have a higher priority than properties.
             */
    String shareConnectionsStr = url.getParameter(SHARE_CONNECTIONS_KEY, (String) null);
    connections = Integer.parseInt(StringUtils.isBlank(shareConnectionsStr) ? ConfigUtils.getProperty(SHARE_CONNECTIONS_KEY,
                                                                                                      DEFAULT_SHARE_CONNECTIONS) : shareConnectionsStr);
    return getSharedClient(url, connections).toArray(new ExchangeClient[0]);
  } else {
    ExchangeClient[] clients = new ExchangeClient[connections];
    for (int i = 0; i < clients.length; i++) {
      clients[i] = initClient(url);
    }
    return clients;
  }

}

/**
 * Create new connection
 *
 * @param url
 */
private ExchangeClient initClient(URL url) {

    // client type setting.
    String str = url.getParameter(CLIENT_KEY, url.getParameter(SERVER_KEY, DEFAULT_REMOTING_CLIENT));

    url = url.addParameter(CODEC_KEY, DubboCodec.NAME);
    // enable heartbeat by default
    url = url.addParameterIfAbsent(HEARTBEAT_KEY, String.valueOf(DEFAULT_HEARTBEAT));

    // BIO is not allowed since it has severe performance issue.
    if (str != null && str.length() > 0 && !ExtensionLoader.getExtensionLoader(Transporter.class).hasExtension(str)) {
        throw new RpcException("Unsupported client type: " + str + "," +
                " supported client type is " +
                StringUtils.join(ExtensionLoader.getExtensionLoader(Transporter.class).getSupportedExtensions(), " "));
    }

    ExchangeClient client;
    try {
        // connection should be lazy
        if (url.getParameter(LAZY_CONNECT_KEY, false)) {
            client = new LazyConnectExchangeClient(url, requestHandler);

        } else {
            client = Exchangers.connect(url, requestHandler);
        }

    } catch (RemotingException e) {
        throw new RpcException("Fail to create remoting client for service(" + url + "): " + e.getMessage(), e);
    }

    return client;
}
```

## ProxyFactory

- javassist
- Cglib

```java
/**
 * ProxyFactory. (API/SPI, Singleton, ThreadSafe)
 */
@SPI("javassist")
public interface ProxyFactory {

    /**
     * create proxy.
     *
     * @param invoker
     * @return proxy
     */
    @Adaptive({PROXY_KEY})
    <T> T getProxy(Invoker<T> invoker) throws RpcException;

    /**
     * create proxy.
     *
     * @param invoker
     * @return proxy
     */
    @Adaptive({PROXY_KEY})
    <T> T getProxy(Invoker<T> invoker, boolean generic) throws RpcException;

    /**
     * create invoker.
     *
     * @param <T>
     * @param proxy
     * @param type
     * @param url
     * @return invoker
     */
    @Adaptive({PROXY_KEY})
    <T> Invoker<T> getInvoker(T proxy, Class<T> type, URL url) throws RpcException;

}
```





## Shutdown

destroy registries and protocols(servers then clients), wait for pending tasks completed.

优雅停机的实现

1. 收到信号 Spring触发容器销毁事件
2. provider 取消服务注册元信息
3. consumer 收到最新地址列表(不包含停机地址)
4. provider 对 Consumer 响应 Dubbo 协议发送readonly报文 通知 Consumer 服务不可用
5. provider 等待已经执行任务执行结束 并拒绝新任务执行

> 2.6.3 后修复了一些停机bug 原因为Spring也同时注册了 shutdown hooks 并发线程执行可能引用已销毁资源导致报错 例如Dubbo发现 Spring已经关闭上下文状态导致访问Spring资源报错

### Shutdown Hooks

The [shutdown hook](/docs/CS/Java/JDK/JVM/destroy.md?id=shutdown-hooks) thread to do the clean up stuff.
This is a **singleton** in order to ensure there is only one shutdown hook registered. 

Because ApplicationShutdownHooks use `java.util.IdentityHashMap` to store the shutdown hooks.

```java
public class DubboShutdownHook extends Thread {
    /**
     * Destroy all the resources, including registries and protocols.
     */
    public void destroyAll() {
        if (!destroyed.compareAndSet(false, true)) {
            return;
        }
        // destroy all the registries
        AbstractRegistryFactory.destroyAll();
        // destroy all the protocols
        ExtensionLoader<Protocol> loader = ExtensionLoader.getExtensionLoader(Protocol.class);
        for (String protocolName : loader.getLoadedExtensions()) {
            try {
                Protocol protocol = loader.getLoadedExtension(protocolName);
                if (protocol != null) {
                    protocol.destroy();
                }
            } catch (Throwable t) {
                logger.warn(t.getMessage(), t);
            }
        }
    }
}
```

### Spring Extension

```java
package org.apache.dubbo.config.spring.extension;
        
public class SpringExtensionFactory implements ExtensionFactory, Lifecycle {
    public static void addApplicationContext(ApplicationContext context) {
        CONTEXTS.add(context);
        if (context instanceof ConfigurableApplicationContext) {
            ((ConfigurableApplicationContext) context).registerShutdownHook();
            // see https://github.com/apache/dubbo/issues/7093
            DubboShutdownHook.getDubboShutdownHook().unregister();
        }
    }
}

public class DubboBootstrapApplicationListener implements ApplicationListener, ApplicationContextAware, Ordered {

    private void onContextClosedEvent(ContextClosedEvent event) {
        if (dubboBootstrap.getTakeoverMode() == BootstrapTakeoverMode.SPRING) {
            // will call dubboBootstrap.stop() through shutdown callback.
            DubboShutdownHook.getDubboShutdownHook().run();
        }
    }
}
```


## Links

- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)