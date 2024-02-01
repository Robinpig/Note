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
3. An `ApplicationPreparedEvent` is sent just before the refresh is started but after bean definitions have been loaded.
4. An `ApplicationStartedEvent` is sent after the context has been refreshed but before any application and command-line runners have been called.
5. An `ApplicationReadyEvent` is sent after any application and command-line runners have been called. It indicates that the application is ready to service requests.
6. An `ApplicationFailedEvent` is sent if there is an exception on startup.

## Links

- [Spring](/docs/CS/Java/Spring/Spring.md)