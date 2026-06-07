## Introduction

我们来讨论一下 Spring Boot 是如何启动的。


```
┌─────────────────────────────────────────────────────────────┐
│                    1. SpringApplication初始化                │
│  - 推断Web应用类型（Servlet/Reactive/None）                  │
│  - 加载ApplicationContextInitializer                        │
│  - 加载ApplicationListener                                  │
│  - 推断主类（Main Class）                                    │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    2. 启动准备阶段                          │
│  - 创建StopWatch（启动计时器）                              │
│  - 配置Headless属性                                         │
│  - 启动监听器（SpringApplicationRunListeners）               │
│  - 准备环境（Environment）                                   │
│  - 创建ApplicationContext                                   │
│  - 准备上下文（prepareContext）                              │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    3. 刷新上下文阶段                        │
│  - refreshContext() → AbstractApplicationContext.refresh()  │
│  - BeanFactoryPostProcessor执行                             │
│  - BeanPostProcessor注册                                    │
│  - 自动配置核心：@EnableAutoConfiguration                    │
│  - 内嵌Web容器启动（ServletWebServerApplicationContext）    │
│  - 国际化、事件监听器初始化                                  │
│  - 所有单例Bean初始化                                        │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    4. 启动完成阶段                          │
│  - afterRefresh()回调                                       │
│  - 发布ApplicationReadyEvent事件                            │
│  - 执行ApplicationRunner/CommandLineRunner                  │
│  - 返回ApplicationContext                                    │
└─────────────────────────────────────────────────────────────┘
```

## Entrance

```java
@SpringBootApplication
public class Application {

	public static void main(String[] args) {
		SpringApplication.run(Application.class, args);
	}

}
```

SpringApplication.run()

```
public static ConfigurableApplicationContext run(Class<?>[] primarySources, String[] args) {
   return new SpringApplication(primarySources).run(args);
}
```

## new SpringApplication instance

创建一个新的 SpringApplication 实例。应用上下文将从指定的主 sources 中加载 beans（详见类级别文档）。可以在调用 run(String...) 之前自定义该实例。

1. deduceFromClasspath
2. load ApplicationContextInitializer
3. load ApplicationListener
4. deduceMainApplicationClass


getSpringFactoriesInstances方法是SpringBoot的核心SPI机制，它从META-INF/spring.factories文件中加载指定类型的实现类
这种机制使得SpringBoot具有极高的可扩展性，开发者也可以通过自定义spring.factories来注入自己的扩展点

```java
public SpringApplication(ResourceLoader resourceLoader, Class<?>... primarySources) {
   this.resourceLoader = resourceLoader;
   this.primarySources = new LinkedHashSet<>(Arrays.asList(primarySources));
   this.webApplicationType = WebApplicationType.deduceFromClasspath();
   setInitializers((Collection) getSpringFactoriesInstances(ApplicationContextInitializer.class));
   setListeners((Collection) getSpringFactoriesInstances(ApplicationListener.class));
   this.mainApplicationClass = deduceMainApplicationClass();
}
```

deduceFromClasspath

```java
static WebApplicationType deduceFromClasspath() {
   if (ClassUtils.isPresent(WEBFLUX_INDICATOR_CLASS, null) && !ClassUtils.isPresent(WEBMVC_INDICATOR_CLASS, null)
         && !ClassUtils.isPresent(JERSEY_INDICATOR_CLASS, null)) {
      return WebApplicationType.REACTIVE;
   }
   for (String className : SERVLET_INDICATOR_CLASSES) {
      if (!ClassUtils.isPresent(className, null)) {
         return WebApplicationType.NONE;
      }
   }
   return WebApplicationType.SERVLET;
}
```

## run

1. getRunListeners and starting
2. prepareEnvironment
3. configureIgnoreBeanInfo
4. createApplicationContext
5. getSpringFactoriesInstances -> [SpringFactoriesLoader.loadSpringFactories()](/docs//CS/Framework/Spring_Boot/Start.md?id=LoadFactories)
6. prepareContext
7. refreshContext
8. afterRefresh
9. listeners started
10. callRunners
11. listeners running

```java
public ConfigurableApplicationContext run(String... args) {
   ConfigurableApplicationContext context = null;
   Collection<SpringBootExceptionReporter> exceptionReporters = new ArrayList<>();
   configureHeadlessProperty();
   
  SpringApplicationRunListeners listeners = getRunListeners(args);
   listeners.starting();
   try {
      ApplicationArguments applicationArguments = new DefaultApplicationArguments(args);
      ConfigurableEnvironment environment = prepareEnvironment(listeners, applicationArguments);
      configureIgnoreBeanInfo(environment);
      Banner printedBanner = printBanner(environment);
      context = createApplicationContext();
      exceptionReporters = getSpringFactoriesInstances(SpringBootExceptionReporter.class,
            new Class[] { ConfigurableApplicationContext.class }, context);
      prepareContext(context, environment, listeners, applicationArguments, printedBanner);
      refreshContext(context);
      afterRefresh(context, applicationArguments);

      if (this.logStartupInfo) {
         new StartupInfoLogger(this.mainApplicationClass).logStarted(getApplicationLog(), stopWatch);
      }
   
      listeners.started(context);
      callRunners(context, applicationArguments);
   }
   catch (Throwable ex) {
      handleRunFailure(context, ex, exceptionReporters, listeners);
      throw new IllegalStateException(ex);
   }

   try {
      listeners.running(context);
   }
   catch (Throwable ex) {
      handleRunFailure(context, ex, exceptionReporters, null);
      throw new IllegalStateException(ex);
   }
   return context;
}
```

### getRunListeners


- `SpringFactoriesLoader.loadFactoryNames(type, classLoader)`
  - 使用给定的 class loader 从 {@value #FACTORIES_RESOURCE_LOCATION} 加载给定类型的工厂实现的全限定类名。
- `AnnotationAwareOrderComparator.sort(instances)`
  - 使用默认的 AnnotationAwareOrderComparator 对给定列表进行排序。针对大小为 0 或 1 的列表优化以跳过排序，避免不必要的数组提取。


*AnnotationAwareOrderComparator* 是 *OrderComparator* 的扩展，支持 Spring 的 org.springframework.core.Ordered 接口以及 @Order 和 @Priority 注解，Ordered 实例提供的 order 值会覆盖静态定义的注解值（如果有）。

```java
private SpringApplicationRunListeners getRunListeners(String[] args){
        Class<?>[]types=new Class<?>[]{SpringApplication.class,String[].class };
        return new SpringApplicationRunListeners(logger,
        getSpringFactoriesInstances(SpringApplicationRunListener.class,types,this,args));
        }
private<T> Collection<T> getSpringFactoriesInstances(Class<T> type,Class<?>[]parameterTypes,Object...args){
        ClassLoader classLoader=getClassLoader();
        // Use names and ensure unique to protect against duplicates
        Set<String> names=new LinkedHashSet<>(SpringFactoriesLoader.loadFactoryNames(type,classLoader));
        List<T> instances=createSpringFactoriesInstances(type,parameterTypes,classLoader,args,names);
        AnnotationAwareOrderComparator.sort(instances); // sort
        return instances;
        }

@SuppressWarnings("unchecked")
private<T> List<T> createSpringFactoriesInstances(Class<T> type,Class<?>[]parameterTypes,
        ClassLoader classLoader,Object[]args,Set<String> names){
        List<T> instances=new ArrayList<>(names.size());
        for(String name:names){
        try{
        Class<?> instanceClass=ClassUtils.forName(name,classLoader);
        Assert.isAssignable(type,instanceClass);
        Constructor<?> constructor=instanceClass.getDeclaredConstructor(parameterTypes);
        T instance=(T)BeanUtils.instantiateClass(constructor,args);
        instances.add(instance);
        }
        catch(Throwable ex){
        throw new IllegalArgumentException("Cannot instantiate "+type+" : "+name,ex);
        }
        }
        return instances;
        }
        
```



`创建 ApplicationStartingEvent 并使用给定事件调用给定监听器。`

### prepareEnvironment

```java
private ConfigurableEnvironment prepareEnvironment(SpringApplicationRunListeners listeners,
			ApplicationArguments applicationArguments) {
		// Create and configure the environment
		ConfigurableEnvironment environment = getOrCreateEnvironment();
		configureEnvironment(environment, applicationArguments.getSourceArgs());
		ConfigurationPropertySources.attach(environment);
		listeners.environmentPrepared(environment);
		bindToSpringApplication(environment);
		if (!this.isCustomEnvironment) {
			environment = new EnvironmentConverter(getClassLoader()).convertEnvironmentIfNecessary(environment,
					deduceEnvironmentClass());
		}
		ConfigurationPropertySources.attach(environment);
		return environment;
	}
```

### configureIgnoreBeanInfo

```java
private void configureIgnoreBeanInfo(ConfigurableEnvironment environment) {
   if (System.getProperty(CachedIntrospectionResults.IGNORE_BEANINFO_PROPERTY_NAME) == null) {
      Boolean ignore = environment.getProperty("spring.beaninfo.ignore", Boolean.class, Boolean.TRUE);
      System.setProperty(CachedIntrospectionResults.IGNORE_BEANINFO_PROPERTY_NAME, ignore.toString());
   }
}
```

### createApplicationContext

用于创建 *ApplicationContext* 的策略方法。默认情况下，该方法会优先使用任何显式设置的应用上下文或应用上下文类，然后回退到合适的默认值。

```java
protected ConfigurableApplicationContext createApplicationContext() {
	Class<?> contextClass = this.applicationContextClass;
	if (contextClass == null) {
		try {
			switch (this.webApplicationType) {
			case SERVLET:
				contextClass = Class.forName(DEFAULT_SERVLET_WEB_CONTEXT_CLASS);
				break;
			case REACTIVE:
				contextClass = Class.forName(DEFAULT_REACTIVE_WEB_CONTEXT_CLASS);
				break;
			default:
				contextClass = Class.forName(DEFAULT_CONTEXT_CLASS);
			}
		}
		catch (ClassNotFoundException ex) {
			throw new IllegalStateException(
					"Unable create a default ApplicationContext, please specify an ApplicationContextClass", ex);
		}
	}
	return (ConfigurableApplicationContext) BeanUtils.instantiateClass(contextClass);
}
```

```java
/**
 * Sets the type of Spring {@link ApplicationContext} that will be created. If not
 * specified defaults to {@link #DEFAULT_SERVLET_WEB_CONTEXT_CLASS} for web based
 * applications or {@link AnnotationConfigApplicationContext} for non web based
 * applications.
 * @param applicationContextClass the context class to set
 */
public void setApplicationContextClass(Class<? extends ConfigurableApplicationContext> applicationContextClass) {
   this.applicationContextClass = applicationContextClass;
   this.webApplicationType = WebApplicationType.deduceFromApplicationContext(applicationContextClass);
}

static WebApplicationType deduceFromApplicationContext(Class<?> applicationContextClass) {
		if (isAssignable(SERVLET_APPLICATION_CONTEXT_CLASS, applicationContextClass)) {
			return WebApplicationType.SERVLET;
		}
		if (isAssignable(REACTIVE_APPLICATION_CONTEXT_CLASS, applicationContextClass)) {
			return WebApplicationType.REACTIVE;
		}
		return WebApplicationType.NONE;
	}
```


### loadFactories

在 AutoConfigurationImportSelector 类中，**getAutoConfigurationEntry** 方法加载配置。

通过 **SpringFactoriesLoader** 从 `META-INF/spring.factories` 获取资源。

```java
//Return the AutoConfigurationEntry based on the AnnotationMetadata of the importing @Configuration class.
protected AutoConfigurationEntry getAutoConfigurationEntry(AnnotationMetadata annotationMetadata) {
   AnnotationAttributes attributes = getAttributes(annotationMetadata);
   List<String> configurations = getCandidateConfigurations(annotationMetadata, attributes);
   configurations = removeDuplicates(configurations);
   Set<String> exclusions = getExclusions(annotationMetadata, attributes);
   configurations.removeAll(exclusions);
   configurations = getConfigurationClassFilter().filter(configurations);
   fireAutoConfigurationImportEvents(configurations, exclusions);
   return new AutoConfigurationEntry(configurations, exclusions);
}

protected List<String> getCandidateConfigurations(AnnotationMetadata metadata, AnnotationAttributes attributes) {
        List<String> configurations = SpringFactoriesLoader.loadFactoryNames(getSpringFactoriesLoaderFactoryClass(),
        getBeanClassLoader());
        return configurations;
}

  public static List<String> loadFactoryNames(Class<?> factoryType, @Nullable ClassLoader classLoader) {
    String factoryTypeName = factoryType.getName();
    return (List) loadSpringFactories(classLoader).getOrDefault(factoryTypeName, Collections.emptyList());
  }

  private static Map<String, List<String>> loadSpringFactories(@Nullable ClassLoader classLoader) {
		MultiValueMap<String, String> result = cache.get(classLoader);
		if (result != null) {
			return result;
		}

		try {
			Enumeration<URL> urls = (classLoader != null ?
					classLoader.getResources(FACTORIES_RESOURCE_LOCATION) :
					ClassLoader.getSystemResources(FACTORIES_RESOURCE_LOCATION));
			result = new LinkedMultiValueMap<>();
			while (urls.hasMoreElements()) {
				URL url = urls.nextElement();
				UrlResource resource = new UrlResource(url);
				Properties properties = PropertiesLoaderUtils.loadProperties(resource);
				for (Map.Entry<?, ?> entry : properties.entrySet()) {
					String factoryTypeName = ((String) entry.getKey()).trim();
					for (String factoryImplementationName : StringUtils.commaDelimitedListToStringArray((String) entry.getValue())) {
						result.add(factoryTypeName, factoryImplementationName.trim());
					}
				}
			}
			cache.put(classLoader, result);
			return result;
		}
		catch (IOException ex) {
			throw new IllegalArgumentException("Unable to load factories from location [" +
					FACTORIES_RESOURCE_LOCATION + "]", ex);
		}
	}
```


### prepareContext

```java
private void prepareContext(ConfigurableApplicationContext context, ConfigurableEnvironment environment,
      SpringApplicationRunListeners listeners, ApplicationArguments applicationArguments, Banner printedBanner) {
   context.setEnvironment(environment);
   postProcessApplicationContext(context);
   applyInitializers(context);
   listeners.contextPrepared(context);
   if (this.logStartupInfo) {
      logStartupInfo(context.getParent() == null);
      logStartupProfileInfo(context);
   }
   // Add boot specific singleton beans
   ConfigurableListableBeanFactory beanFactory = context.getBeanFactory();
   beanFactory.registerSingleton("springApplicationArguments", applicationArguments);
   if (printedBanner != null) {
      beanFactory.registerSingleton("springBootBanner", printedBanner);
   }
   if (beanFactory instanceof DefaultListableBeanFactory) {
      ((DefaultListableBeanFactory) beanFactory)
            .setAllowBeanDefinitionOverriding(this.allowBeanDefinitionOverriding);
   }
   if (this.lazyInitialization) {
      context.addBeanFactoryPostProcessor(new LazyInitializationBeanFactoryPostProcessor());
   }
   // Load the sources
   Set<Object> sources = getAllSources();
   Assert.notEmpty(sources, "Sources must not be empty");
   load(context, sources.toArray(new Object[0]));
   listeners.contextLoaded(context);
}
```

### postProcessApplicationContext

`对 ApplicationContext 应用任何相关的后处理。子类可以根据需要应用额外的处理。`

```java
protected void postProcessApplicationContext(ConfigurableApplicationContext context) {
   if (this.beanNameGenerator != null) {
      context.getBeanFactory().registerSingleton(AnnotationConfigUtils.CONFIGURATION_BEAN_NAME_GENERATOR,
            this.beanNameGenerator);
   }
   if (this.resourceLoader != null) {
      if (context instanceof GenericApplicationContext) {
         ((GenericApplicationContext) context).setResourceLoader(this.resourceLoader);
      }
      if (context instanceof DefaultResourceLoader) {
         ((DefaultResourceLoader) context).setClassLoader(this.resourceLoader.getClassLoader());
      }
   }
   if (this.addConversionService) {
      context.getBeanFactory().setConversionService(ApplicationConversionService.getSharedInstance());
   }
}
```

### applyInitializers

在上下文刷新之前应用所有 ApplicationContextInitializers。

```java
@SuppressWarnings({ "rawtypes", "unchecked" })
protected void applyInitializers(ConfigurableApplicationContext context) {
   for (ApplicationContextInitializer initializer : getInitializers()) {
      Class<?> requiredType = GenericTypeResolver.resolveTypeArgument(initializer.getClass(),
            ApplicationContextInitializer.class);
      Assert.isInstanceOf(requiredType, context, "Unable to call initializer.");
      initializer.initialize(context);
   }
}
```

### load

`将 beans 加载到应用上下文中。`

```java
protected void load(ApplicationContext context, Object[] sources) {
   if (logger.isDebugEnabled()) {
      logger.debug("Loading source " + StringUtils.arrayToCommaDelimitedString(sources));
   }
   BeanDefinitionLoader loader = createBeanDefinitionLoader(getBeanDefinitionRegistry(context), sources);
   if (this.beanNameGenerator != null) {
      loader.setBeanNameGenerator(this.beanNameGenerator);
   }
   if (this.resourceLoader != null) {
      loader.setResourceLoader(this.resourceLoader);
   }
   if (this.environment != null) {
      loader.setEnvironment(this.environment);
   }
   loader.load();
}
```

### listeners.contextLoaded

`添加将在上下文事件（如上下文刷新和关闭）时收到通知的 ApplicationListeners。注意，如果上下文尚未激活，在此注册的任何 ApplicationListener 将在刷新时应用；如果上下文已激活，则将与当前事件多播器动态应用。`

### refreshContext

see [AbstractApplicationContext#refresh()](/docs/CS/Framework/Spring/IoC.md?id=refresh),

在 `onRefresh` 中创建 webServer

```java
// ServletWebServerApplicationContext
@Override
protected void onRefresh() {
   super.onRefresh();
   try {
      createWebServer();
   }
   catch (Throwable ex) {
      throw new ApplicationContextException("Unable to start web server", ex);
   }
}
```

在 `finishRefresh` 中启动 webServer

```java
// org.springframework.boot.web.servlet.context.WebServerStartStopLifecycle
class WebServerStartStopLifecycle implements SmartLifecycle {
  @Override
	public void start() {
		this.webServer.start();
		this.running = true;
		this.applicationContext
				.publishEvent(new ServletWebServerInitializedEvent(this.webServer, this.applicationContext));
	}
}
```

`org.springframework.boot.web.server.WebServer` 是一个简单接口，代表一个完全配置好的 web 服务器（例如 Tomcat、Jetty、Netty）。允许启动和停止服务器。

### afterRefresh

`不执行任何操作`

### listeners.started

`上下文已刷新，应用已启动，但 CommandLineRunners 和 ApplicationRunners 尚未被调用。`

### callRunners

`运行 ApplicationRunner 和 CommandLineRunner`

```java
private void callRunners(ApplicationContext context, ApplicationArguments args) {
   List<Object> runners = new ArrayList<>();
   runners.addAll(context.getBeansOfType(ApplicationRunner.class).values());
   runners.addAll(context.getBeansOfType(CommandLineRunner.class).values());
   AnnotationAwareOrderComparator.sort(runners);
   for (Object runner : new LinkedHashSet<>(runners)) {
      if (runner instanceof ApplicationRunner) {
         callRunner((ApplicationRunner) runner, args);
      }
      if (runner instanceof CommandLineRunner) {
         callRunner((CommandLineRunner) runner, args);
      }
   }
}
```

### listeners.running

```java
void running(ConfigurableApplicationContext context) {
   for (SpringApplicationRunListener listener : this.listeners) {
      listener.running(context);
   }
}
```

## Links

- [Spring Boot](/docs/CS/Framework/Spring_Boot/Spring_Boot.md)
