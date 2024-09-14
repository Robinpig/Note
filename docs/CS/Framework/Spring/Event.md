## Introduction

Spring Application Events are events that are triggered by the Spring framework.
They are designed to be used in the development of applications that need to be aware of changes in the environment.
Spring Application Events allow developers to create applications that can respond to changes in the application environment in real time.

Spring Application Events are based on the concept of the Observer pattern.
The Observer pattern is a design pattern in which an object is able to observe the state of another object and react accordingly. In the case of Spring Application Events, the observer is the application and the object being observed is the application environment.

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

Standard Context Events:

- ContextRefreshedEvent
- ContextStartedEvent
- ContextStoppedEvent
- ContextClosedEvent

## multicastEvent
support [Async](/docs/CS/Framework/Spring/Task.md)
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

Spring Boot provides several predefined ApplicationEvents that are tied to the lifecycle of a SpringApplication.

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

Application events are sent in the following order, as your application runs:

1. An `ApplicationStartingEvent` is sent at the start of a run but before any processing, except for the registration of listeners and initializers.
2. An `ApplicationEnvironmentPreparedEvent` is sent when the `Environment` to be used in the context is known but before the context is created.
3. An `ApplicationPreparedEvent` is sent just before the [refresh](/docs/CS/Framework/Spring/IoC.md?id=refresh) is started but after bean definitions have been loaded.
4. An `ApplicationStartedEvent` is sent after the context has been refreshed but before any application and command-line runners have been called.
5. An `ApplicationReadyEvent` is sent after any application and command-line runners have been called. It indicates that the application is ready to service requests.
6. An `ApplicationFailedEvent` is sent if there is an exception on startup.


## Implementations

ZuulRefreshListener

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)