## Introduction

ApplicationEvent

```java
public abstract class ApplicationEvent extends EventObject {
    private final long timestamp;

    public ApplicationEvent(Object source) {
        super(source);
        this.timestamp = System.currentTimeMillis();
    }
}
```

EventListener
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


SpringApplicationEvent
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

## Links

