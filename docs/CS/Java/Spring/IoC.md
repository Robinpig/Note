# IoC

## Introduction

IoC(`Inversion of Control`) depends on DI(`Dependency Injection`) in Spring


##### 对象类型的管理

***singleton*** 负责它的整个生命周期
 ***prototype*** 只负责它的创建 之后不关心其销毁过程

#### IoC容器接口简析

![Ioc容器接口设计图](https://img-blog.csdnimg.cn/20191019085118543.png?x-oss-process=image/watermark,type_ZmFuZ3poZW5naGVpdGk,shadow_10,text_aHR0cHM6Ly9ibG9nLmNzZG4ubmV0L2d1amlhbmduYW4=,size_16,color_FFFFFF,t_70)IoC容器接口设计[1]

***第一条接口设计主线*** 从接口**BeanFactory**到**HierarchicalBeanFactory** 再到**ConfigurableBeanFactory** 是一条主要的BeanFactory设计路径

***第二条接口设计主线*** 以**ApplicationContext**应用上下文接口为核心的接口设计 这里涉及的主要接口设计有 从BeanFactory到**ListableBeanFactory** 再到ApplicationContext 再到常用的WebApplicationContext或者ConfigurableApplicationContext

## 重要API简析

> BeanFactory
>  ApplicationContext

#### BeanFactory

BeanFactory接口定义了IoC容器最基本的形式 并且提供了IoC容器所应该遵守的最基本的服务契约 这也是我们使用IoC容器所应遵守的最底层和最基本的编程规范 这些接口定义勾画出了IoC的基本轮廓

> **BeanFactory**与**FactoryBean**区别
>
> - **FactoryBean** 是一个Bean 能产生或者修饰对象生成的工厂Bean 实现与设计模式中的工厂模式和修饰器模式类似 注意和作为
> - **BeanFactory** 是Factory 也就是IoC容器或对象工厂  所有的Bean都是由BeanFactory（也就是IoC容器）来进行管理的

```java
public interface BeanFactory {

	String FACTORY_BEAN_PREFIX = "&";

	Object getBean(String name) throws BeansException;

	<T> T getBean(String name, Class<T> requiredType) throws BeansException;

	Object getBean(String name, Object... args) throws BeansException;

	<T> T getBean(Class<T> requiredType) throws BeansException;

	<T> T getBean(Class<T> requiredType, Object... args) throws BeansException;

	<T> ObjectProvider<T> getBeanProvider(Class<T> requiredType);

	<T> ObjectProvider<T> getBeanProvider(ResolvableType requiredType);

	boolean containsBean(String name);

	boolean isSingleton(String name) throws NoSuchBeanDefinitionException;

	boolean isPrototype(String name) throws NoSuchBeanDefinitionException;

	boolean isTypeMatch(String name, ResolvableType typeToMatch) throws NoSuchBeanDefinitionException;

	boolean isTypeMatch(String name, Class<?> typeToMatch) throws NoSuchBeanDefinitionException;

	@Nullable
	Class<?> getType(String name) throws NoSuchBeanDefinitionException;

	@Nullable
	Class<?> getType(String name, boolean allowFactoryBeanInit) throws NoSuchBeanDefinitionException;

	String[] getAliases(String name);

}
```

###### 接口方法

getBean()
 取得IoC容器中管理的Bean

containsBean()   	
 判断容器是否含有指定名字的Bean

isSingleton()
 isPrototype()

isTypeMatch()
 查询指定了名字的Bean的Class类型是否是特定的Class类型

getType()
 查询指定名字的Bean的Class类型

etAliases()
 查询指定了名字的Bean的所有别名 这些别名都是用户在BeanDefinition中定义的

#### ApplicationContext

应用上下文
 ![Beanfactory ](./images/BeanFactory.png)
 ApplicationContext继承接口图
 由上图可知ApplicationContext在BeanFactory 简单IoC容器的基础上 增加了许多面向框架的特性 同时对应用环境作了许多适配

> - **支持不同的信息源** 我们看到ApplicationContext扩展了MessageSource接口 这些信息源的扩展功能可以支持国际化的实现 为开发多语言版本的应用提供服务
> - **访问资源** 这一特性体现在对ResourceLoader和Resource的支持上 可以从不同地方得到Bean定义资源 灵活地定义Bean定义信息 尤其是从不同的I/O途径得到Bean定义信息
> - **支持应用事件** 继承了接口ApplicationEventPublisher 从而在上下文中引入了事件机制 这些事件和Bean的生命周期的结合为Bean的管理提供了便利
> - **其它附加服务** 这些服务使得基本IoC容器的功能更丰富

## IoC容器的初始化过程

### AbstractApplicationContext#refresh()

refresh()在ConfigurableApplicationContext接口声明
 启动包括**BeanDefinition的Resouce定位 载入和注册**
 BeanDefinition 是依赖反转模式中管理的对象依赖关系的数据抽象 也是容器实现依赖反转功能的核心数据结构
 以下是AbstractApplicationContext重写的refresh()

```java
// AbstractApplicationContext#refresh()
@Override
	public void refresh() throws BeansException, IllegalStateException {
		synchronized (this.startupShutdownMonitor) {
			// Prepare this context for refreshing.
			prepareRefresh();

			// Tell the subclass to refresh the internal bean factory.
			ConfigurableListableBeanFactory beanFactory = obtainFreshBeanFactory();

			// Prepare the bean factory for use in this context.
			prepareBeanFactory(beanFactory);

			try {
				// Allows post-processing of the bean factory in context subclasses.
				postProcessBeanFactory(beanFactory);

				// Invoke factory processors registered as beans in the context.
				invokeBeanFactoryPostProcessors(beanFactory);

				// Register bean processors that intercept bean creation.
				registerBeanPostProcessors(beanFactory);

				// Initialize message source for this context.
				initMessageSource();

				// Initialize event multicaster for this context.
				initApplicationEventMulticaster();

				// Initialize other special beans in specific context subclasses.
				onRefresh();

				// Check for listener beans and register them.
				registerListeners();

				// Instantiate all remaining (non-lazy-init) singletons.
				finishBeanFactoryInitialization(beanFactory);

				// Last step: publish corresponding event.
				finishRefresh();
			}

			catch (BeansException ex) {
				if (logger.isWarnEnabled()) {
					logger.warn("Exception encountered during context initialization - " +
							"cancelling refresh attempt: " + ex);
				}

				// Destroy already created singletons to avoid dangling resources.
				destroyBeans();

				// Reset 'active' flag.
				cancelRefresh(ex);

				// Propagate exception to caller.
				throw ex;
			}

			finally {
				// Reset common introspection caches in Spring's core, since we
				// might not ever need metadata for singleton beans anymore...
				resetCommonCaches();
			}
		}
	}
```

##### Resouce定位

Resource定位指的是BeanDefinition的资源定位 它由ResourceLoader通过统一的Resource接口来完成

在ApplicationContext实现容器下有ClassPathXml FileSystemXml等方式 但DefaultListableBeanFactory（以下简称DLBF）容器更为底层 需要自己定制方式

##### BeanDefinition的载入

loadBeanDefinitions()在AbstractRefreshableApplicationContext中声明 需要BeanDefinitionReader读取器的实现 在IoC容器中设置好读取器   启动委托读取器来完成BeanDefinition在IoC容器中的载入
 具体载入解析需根据实现方式解析XML或注解

##### 向IoC容器注册BeanDefinition

在DLBF中 是通过一个HashMap来持有载入的BeanDefinition的 如下所示

```java
/** Map of bean definition objects, keyed by bean name. */
	private final Map<String, BeanDefinition> beanDefinitionMap = new ConcurrentHashMap<>(256);
```

注册实现代码如下

```java
//---------------------------------------------------------------------
	// Implementation of BeanDefinitionRegistry interface
	//---------------------------------------------------------------------

	@Override
	public void registerBeanDefinition(String beanName, BeanDefinition beanDefinition)
			throws BeanDefinitionStoreException {

		Assert.hasText(beanName, "Bean name must not be empty");
		Assert.notNull(beanDefinition, "BeanDefinition must not be null");

		if (beanDefinition instanceof AbstractBeanDefinition) {
			try {
				((AbstractBeanDefinition) beanDefinition).validate();
			}
			catch (BeanDefinitionValidationException ex) {
				throw new BeanDefinitionStoreException(beanDefinition.getResourceDescription(), beanName,
						"Validation of bean definition failed", ex);
			}
		}

		BeanDefinition existingDefinition = this.beanDefinitionMap.get(beanName);
		if (existingDefinition != null) {
			if (!isAllowBeanDefinitionOverriding()) {
				throw new BeanDefinitionOverrideException(beanName, beanDefinition, existingDefinition);
			}
			else if (existingDefinition.getRole() < beanDefinition.getRole()) {
				// e.g. was ROLE_APPLICATION, now overriding with ROLE_SUPPORT or ROLE_INFRASTRUCTURE
				if (logger.isInfoEnabled()) {
					logger.info("Overriding user-defined bean definition for bean '" + beanName +
							"' with a framework-generated bean definition: replacing [" +
							existingDefinition + "] with [" + beanDefinition + "]");
				}
			}
			else if (!beanDefinition.equals(existingDefinition)) {
				if (logger.isDebugEnabled()) {
					logger.debug("Overriding bean definition for bean '" + beanName +
							"' with a different definition: replacing [" + existingDefinition +
							"] with [" + beanDefinition + "]");
				}
			}
			else {
				if (logger.isTraceEnabled()) {
					logger.trace("Overriding bean definition for bean '" + beanName +
							"' with an equivalent definition: replacing [" + existingDefinition +
							"] with [" + beanDefinition + "]");
				}
			}
			this.beanDefinitionMap.put(beanName, beanDefinition);
		}
		else {
			if (hasBeanCreationStarted()) {
				// Cannot modify startup-time collection elements anymore (for stable iteration)
				synchronized (this.beanDefinitionMap) {
					this.beanDefinitionMap.put(beanName, beanDefinition);
					List<String> updatedDefinitions = new ArrayList<>(this.beanDefinitionNames.size() + 1);
					updatedDefinitions.addAll(this.beanDefinitionNames);
					updatedDefinitions.add(beanName);
					this.beanDefinitionNames = updatedDefinitions;
					removeManualSingletonName(beanName);
				}
			}
			else {
				// Still in startup registration phase
				this.beanDefinitionMap.put(beanName, beanDefinition);
				this.beanDefinitionNames.add(beanName);
				removeManualSingletonName(beanName);
			}
			this.frozenBeanDefinitionNames = null;
		}

		if (existingDefinition != null || containsSingleton(beanName)) {
			resetBeanDefinition(beanName);
		}
	}
```

完成了BeanDefinition的注册 就完成了IoC容器的初始化过程建立了整个Bean的配置信息都在beanDefinitionMap里被检索和使用 容器的作用就是对这些信息进行处理和维护 这些信息是容器建立依赖反转的基础

# 依赖注入

依赖注入的过程触发事件

> 用户第一次向IoC容器索要Bean时
>  通过控制lazy-init属性来让容器完成对Bean的预实例化

DLBF的基类AbstractBeanFactory的getBean()中调用doGetBean() 之后会调用createBean 在这个过程中 Bean对象会依据BeanDefinition定义的要求生成  在AbstractAutowireCapableBeanFactory中实现了这个createBean,  createBean不但生成了需要的Bean 还对Bean初始化进行了处理  比如实现了在BeanDefinition中的init-method属性定义 Bean后置处理器等 下图就是依赖注入过程
 ![在这里插入图片描述](https://img-blog.csdnimg.cn/20191019112746693.png?x-oss-process=image/watermark,type_ZmFuZ3poZW5naGVpdGk,shadow_10,text_aHR0cHM6Ly9ibG9nLmNzZG4ubmV0L2d1amlhbmduYW4=,size_16,color_FFFFFF,t_70)
 依赖注入过程[1]

## 容器关闭

在容器要关闭时 也需要完成一系列的工作 这些工作在doClose（）方法中完成(AbstractApplicationContext声明）先发出容器关闭的信号 然后将Bean逐个关闭 最后关闭容器自身

```java
	protected void doClose() {
		// Check whether an actual close attempt is necessary...
		if (this.active.get() && this.closed.compareAndSet(false, true)) {
			if (logger.isDebugEnabled()) {
				logger.debug("Closing " + this);
			}

			LiveBeansView.unregisterApplicationContext(this);

			try {
				// Publish shutdown event.
				publishEvent(new ContextClosedEvent(this));
			}
			catch (Throwable ex) {
				logger.warn("Exception thrown from ApplicationListener handling ContextClosedEvent", ex);
			}

			// Stop all Lifecycle beans, to avoid delays during individual destruction.
			if (this.lifecycleProcessor != null) {
				try {
					this.lifecycleProcessor.onClose();
				}
				catch (Throwable ex) {
					logger.warn("Exception thrown from LifecycleProcessor on context close", ex);
				}
			}

			// Destroy all cached singletons in the context's BeanFactory.
			destroyBeans();

			// Close the state of this context itself.
			closeBeanFactory();

			// Let subclasses do some final clean-up if they wish...
			onClose();

			// Reset local application listeners to pre-refresh state.
			if (this.earlyApplicationListeners != null) {
				this.applicationListeners.clear();
				this.applicationListeners.addAll(this.earlyApplicationListeners);
			}

			// Switch to inactive.
			this.active.set(false);
		}
	}
```

## Bean生命周期

- Bean实例的创建
- 为Bean实例设置属性
- 调用Bean的初始化方法
- 应用可以通过IoC容器使用Bean
- 当容器关闭时 调用Bean的销毁方法

用户可声明Bean的init-method和destroy-method
 在调用Bean的初始化方法之前 会调用一系列的aware接口实现 把相关的BeanName BeanClassLoader  以及BeanFactoy注入到Bean中去 对invokeInitMethods的调用   启动afterPropertiesSet需要Bean实现InitializingBean的接口  对应的初始化处理可以在InitializingBean接口的afterPropertiesSet方法中实现 这里同样是对Bean的一个回调
 Bean的销毁过程 首先对postProcessBeforeDestruction进行调用 然后调用Bean的destroy方法 最后是对Bean的自定义销毁方法的调用
 ![在这里插入图片描述](https://img-blog.csdnimg.cn/20191019114800284.png?x-oss-process=image/watermark,type_ZmFuZ3poZW5naGVpdGk,shadow_10,text_aHR0cHM6Ly9ibG9nLmNzZG4ubmV0L2d1amlhbmduYW4=,size_16,color_FFFFFF,t_70)
 Bean生命周期图



## EventListener

EventPublisher

ApplicationListener