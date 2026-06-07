## Introduction

Spring Application Events 是由 Spring 框架触发的事件。
它们旨在用于需要感知环境变化的应用的开发中。
Spring Application Events 允许开发者创建能够实时响应应用环境变化的应用。

Spring Application Events 基于 Observer 模式的概念。
Observer 模式是一种设计模式，其中一个对象能够观察另一个对象的状态并做出相应反应。对于 Spring Application Events，观察者是应用，被观察的对象是应用环境。

## ApplicationEvent

```java
public abstract class ApplicationEvent extends EventObject {
    private final long timestamp;

    public ApplicationEvent(Object source) {
        super(source);
        this.timestamp = System.currentTimeMillis();
    }
}
```

标准上下文事件：

- ContextRefreshedEvent
- ContextStartedEvent
- ContextStoppedEvent
- ContextClosedEvent

## multicastEvent
支持 [Async](/docs/CS/Framework/Spring/Task.md)
```java
public class SimpleApplicationEventMulticaster extends AbstractApplicationEventMulticaster {
    public void multicastEvent(ApplicationEvent event, @Nullable ResolvableType eventType) {
        ResolvableType type = (eventType != null ? eventType : ResolvableType.forInstance(event));
        Executor executor = getTaskExecutor();
        for (ApplicationListener<?> listener : getApplicationListeners(event, type)) {
            if (executor != null && listener.supportsAsyncExecution()) {
                try {
                    executor.execute(() -> invokeListener(listener, event));
                } catch (RejectedExecutionException ex) {
                    // Probably on shutdown -> invoke listener locally instead
                    invokeListener(listener, event);
                }
            } else {
                invokeListener(listener, event);
            }
        }
    }
    private void doInvokeListener(ApplicationListener listener, ApplicationEvent event) {
        try {
            listener.onApplicationEvent(event);
        }
        catch (ClassCastException ex) {
            // ...
        }
    }
}
```

## EventPublisher

```java
@FunctionalInterface
public interface ApplicationEventPublisher {
	default void publishEvent(ApplicationEvent event) {
		publishEvent((Object) event);
	}

	void publishEvent(Object event);

}
```
### publishEvent

```java
protected void initApplicationEventMulticaster() {
		ConfigurableListableBeanFactory beanFactory = getBeanFactory();
		if (beanFactory.containsLocalBean(APPLICATION_EVENT_MULTICASTER_BEAN_NAME)) {
			this.applicationEventMulticaster =
					beanFactory.getBean(APPLICATION_EVENT_MULTICASTER_BEAN_NAME, ApplicationEventMulticaster.class);
			if (logger.isTraceEnabled()) {
				logger.trace("Using ApplicationEventMulticaster [" + this.applicationEventMulticaster + "]");
			}
		}
		else {
			this.applicationEventMulticaster = new SimpleApplicationEventMulticaster(beanFactory);
			beanFactory.registerSingleton(APPLICATION_EVENT_MULTICASTER_BEAN_NAME, this.applicationEventMulticaster);
			if (logger.isTraceEnabled()) {
				logger.trace("No '" + APPLICATION_EVENT_MULTICASTER_BEAN_NAME + "' bean, using " +
						"[" + this.applicationEventMulticaster.getClass().getSimpleName() + "]");
			}
		}
	}
    
```

```java
public abstract class AbstractApplicationContext extends DefaultResourceLoader
        implements ConfigurableApplicationContext {
    protected void publishEvent(Object event, @Nullable ResolvableType typeHint) {
        ResolvableType eventType = null;

        // Decorate event as an ApplicationEvent if necessary
        ApplicationEvent applicationEvent;
        if (event instanceof ApplicationEvent applEvent) {
            applicationEvent = applEvent;
            eventType = typeHint;
        } else {
            ResolvableType payloadType = null;
            if (typeHint != null && ApplicationEvent.class.isAssignableFrom(typeHint.toClass())) {
                eventType = typeHint;
            } else {
                payloadType = typeHint;
            }
            applicationEvent = new PayloadApplicationEvent<>(this, event, payloadType);
        }

        // Determine event type only once (for multicast and parent publish)
        if (eventType == null) {
            eventType = ResolvableType.forInstance(applicationEvent);
            if (typeHint == null) {
                typeHint = eventType;
            }
        }

        // Multicast right now if possible - or lazily once the multicaster is initialized
        if (this.earlyApplicationEvents != null) {
            this.earlyApplicationEvents.add(applicationEvent);
        } else if (this.applicationEventMulticaster != null) {
            this.applicationEventMulticaster.multicastEvent(applicationEvent, eventType);
        }

        // Publish event via parent context as well...
        if (this.parent != null) {
            if (this.parent instanceof AbstractApplicationContext abstractApplicationContext) {
                abstractApplicationContext.publishEvent(event, typeHint);
            } else {
                this.parent.publishEvent(event);
            }
        }
    }
}
```

## EventListener

```java
@FunctionalInterface
public interface ApplicationListener<E extends ApplicationEvent> extends EventListener {
    void onApplicationEvent(E event);

    default boolean supportsAsyncExecution() {
        return true;
    }

    static <T> ApplicationListener<PayloadApplicationEvent<T>> forPayload(Consumer<T> consumer) {
        return event -> consumer.accept(event.getPayload());
    }
}
```

## SpringApplicationEvent

Spring Boot 提供了几个预定义的 ApplicationEvents，它们与 SpringApplication 的生命周期相关。

```java
public abstract class SpringApplicationEvent extends ApplicationEvent {

	private final String[] args;

	public SpringApplicationEvent(SpringApplication application, String[] args) {
		super(application);
		this.args = args;
	}

	public SpringApplication getSpringApplication() {
		return (SpringApplication) getSource();
	}

	public final String[] getArgs() {
		return this.args;
	}
}
```

> [!TIP]
>
> Some events are actually triggered before the ApplicationContext is created, so you cannot register a listener on those as a @Bean.
> You can register them with the SpringApplication.addListeners(… ) method or the SpringApplicationBuilder.listeners(… ) method.
>
> If you want those listeners to be registered automatically, regardless of the way the application is created,
> you can add a META-INF/spring.factories file to your project and reference your listener(s) by using the org.springframework.context.ApplicationListener key,
> as shown in the following example:
>
> org.springframework.context.ApplicationListener=com.example.project.MyListener

应用事件按以下顺序发送：

1. `ApplicationStartingEvent` 在运行开始时但在任何处理之前发送，除��监听器和初始化器的注册。
2. `ApplicationEnvironmentPreparedEvent` 在上下文中使用的 `Environment` 已知但上下文尚未创建时发送。
3. `ApplicationPreparedEvent` 在 [refresh](/docs/CS/Framework/Spring/IoC.md?id=refresh) 开始之前但在 bean 定义加载之后发送。
4. `ApplicationStartedEvent` 在上下文刷新之后、任何应用和命令行运行器被调用之前发送。
5. `ApplicationReadyEvent` 在任何应用和命令行运行器被调用之后发送。表示应用已准备好处理请求。
6. `ApplicationFailedEvent` 在启动时出现异常时发送。

## Implementations

ZuulRefreshListener

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
