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

`ApplicationListener<E>` 只能按**事件类型**匹配一个具体类，且必须做成 Bean 注册进容器。注解式的 `@EventListener` 更灵活：任意 Bean 的任意方法都能成为监听器，参数类型即事件类型，无需实现接口。

```java
@Component
class OrderListener {

    @EventListener
    public void on(OrderPlaced event) {
        // 参数类型决定监听哪种事件
    }
}
```

### Conditions and Order

`condition` 接受一段 SpEL，返回 `false` 则跳过。可用变量包括事件本身（`#root.event` 或直接用属性名）与方法参数（`#root.args` / `#p0` / `#a0`）：

```java
@EventListener(condition = "#event.amount > 1000")
public void on(OrderPlaced event) { /* 只处理大额订单 */ }
```

多个监听同一事件的方法用 `@Order`（或实现 `Ordered`）定义先后，数值小的先执行。但**不要把顺序当成编排手段**——监听器之间应该彼此无感知，需要严格先后时应显式调用。

### Async Execution

事件默认是**同步**的：监听器在 `publishEvent` 的调用线程上执行，抛出的异常会回传给发布者（进而可能回滚事务）。两种异步化方式：

| 方式 | 做法 | 影响面 |
| :-- | :-- | :-- |
| 逐个方法 `@Async` | 在监听器方法上加 `@Async` 并指定 `Executor` | 只影响该方法，边界清晰，推荐 |
| 全局 multicaster | 定义名为 `applicationEventMulticaster` 的 Bean 并 `setTaskExecutor` | **一改全改**，容器内所有事件都变异步 |

```java
@Async("domainEventExecutor")
@EventListener
public void on(OrderPlaced event) { /* 在另一个线程上执行 */ }
```

> [!WARNING]
> 一旦事件异步化，监听器里的异常**不再传播**给发布者，只能通过 `AsyncUncaughtExceptionHandler`（实现 `AsyncConfigurer`）或 multicaster 的 `ErrorHandler` 捕获。同时线程绑定的事务上下文、`SecurityContext`、MDC 都不会自动传递过去。

### Generic Events

`PayloadApplicationEvent<T>` 携带了 `ResolvableType`，因此 `ApplicationListener<PayloadApplicationEvent<OrderPlaced>>` 这类带泛型的声明能精确匹配。自定义事件若本身是泛型类（`EntityCreated<Order>`），需要实现 `ResolvableTypeProvider` 主动报告真实类型，否则会因类型擦除导致所有泛型实例互相串台：

```java
public class EntityCreated<T> implements ResolvableTypeProvider {

    private final T entity;

    @Override
    public ResolvableType getResolvableType() {
        return ResolvableType.forClassWithGenerics(getClass(), entity.getClass());
    }
}
```

## @TransactionalEventListener

普通 `@EventListener` 在事务**内部**同步执行：监听器能看到未提交的数据，监听器抛异常也会导致整个事务回滚。很多时候这不是想要的——发通知、写审计、推 MQ 都应该在数据**确实提交成功**之后才发生。

`@TransactionalEventListener` 把投递时机绑定到事务的某个阶段：

| 阶段 | 触发点 | 典型用途 | 仍在事务内 |
| :-- | :-- | :-- | :-- |
| `BEFORE_COMMIT` | 提交前 | 提交前的最后校验或补全写入，异常可阻断提交 | 是 |
| `AFTER_COMMIT`（默认） | 提交成功后 | 发消息、清缓存、通知外部系统 | 否 |
| `AFTER_ROLLBACK` | 回滚后 | 补偿、清理失败现场 | 否 |
| `AFTER_COMPLETION` | 无论提交或回滚 | 资源回收 | 否 |

```java
@Component
class OrderNotificationListener {

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    public void on(OrderPlaced event) {
        // 只有订单事务真的提交成功，才会走到这里
    }
}
```

### Silently Discarded When No Transaction

`fallbackExecution` 默认 **false**：事件发布处若没有活动事务，监听器**根本不会执行，而且没有任何报错**。这是该注解最高频的使用事故——本地跑通（外层有事务），某个非事务入口调用时行为悄悄消失。

```java
@TransactionalEventListener(phase = AFTER_COMMIT, fallbackExecution = true)
public void on(OrderPlaced event) { /* 有事务则提交后执行，无事务则立即执行 */ }
```

> [!WARNING]
> `fallbackExecution = true` 会让同一个监听器在两条代码路径上拥有**不同语义**：从事务入口进来是"提交后"，从非事务入口进来是"立即"。同一笔业务可能因此先后不一致，除非明确接受这种二分，否则宁可要求调用方补上事务边界。

### AFTER_COMMIT Is Not a New Transaction

提交完成后事务资源可能仍未完全释放，此时在监听器里直接写库，"改动不会提交"——它表面上能执行 SQL，实际参与的是一个已经完成的连接。需要在提交后写入，应显式开新事务：

```java
@Transactional(propagation = Propagation.REQUIRES_NEW)   // 必须放在另一个 Bean 上，否则自调用不生效
public void createFor(OrderPlaced event) {
    repository.save(NotificationRequest.of(event));
}
```

`REQUIRES_NEW` 会额外占用一条数据库连接，连接池要按此容量规划。若要求"业务数据与待发消息同生共死"，正确解法不是事务监听器，而是**事务性发件箱（outbox）**：同一事务内写业务表与 outbox 表，再由独立投递器发出去——[Spring Modulith](/docs/CS/Framework/Spring/Modulith.md) 的 Event Publication Registry 正是这一模式的开箱实现。

### Incompatible with Reactive Transactions

事务事件依赖 `TransactionSynchronizationManager` 的**线程绑定**状态。响应式事务由 `ReactiveTransactionManager` 管理，状态存放在 Reactor `Context` 而非线程局部变量，因此从监听器视角看"没有活动事务"，`@TransactionalEventListener` 不会生效。响应式栈要用事务后回调，需自行在 `TransactionalOperator` 的 `doFinally` / `doOnSuccess` 上挂逻辑。

### Only Coordinates with PlatformTransactionManager

`@TransactionalEventListener` 只识别 `PlatformTransactionManager` 管理的事务；自己手写 JDBC `Connection#commit()`、或 `@Transactional` 因自调用/非 public 方法未生效时，同样会落入"无事务 → 静默丢弃"。

## @Async Combined with Transaction Events

"提交后 + 异步"是最常见的搭配——提交后不阻塞请求线程，又能保证数据可见：

```java
@Async("domainEventExecutor")
@TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
public void on(OrderPlaced event) { /* 提交成功后再异步处理 */ }
```

代价是可靠性：异步任务只存在于内存队列，JVM 崩溃即丢失。要求不丢就必须落库（outbox）或交给真正的消息中间件，详见 [Spring AMQP](/docs/CS/Framework/Spring/AMQP.md) 与 [Kafka](/docs/CS/Framework/Spring/Kafka.md)。

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

> [!NOTE]
> 这里用 `spring.factories` 是正确的：它注册的是**扩展点**（`ApplicationListener` 等），而不是自动配置。自动配置的注册文件在 Boot 3.0 已迁移到 `META-INF/spring/...AutoConfiguration.imports`，详见 [SPI](/docs/CS/Framework/Spring/SPI.md)。

Application events are sent in the following order, as your application runs:

1. An `ApplicationStartingEvent` is sent at the start of a run but before any processing, except for the registration of listeners and initializers.
2. An `ApplicationEnvironmentPreparedEvent` is sent when the `Environment` to be used in the context is known but before the context is created.
3. An `ApplicationPreparedEvent` is sent just before the [refresh](/docs/CS/Framework/Spring/IoC.md?id=refresh) is started but after bean definitions have been loaded.
4. An `ApplicationStartedEvent` is sent after the context has been refreshed but before any application and command-line runners have been called.
5. An `ApplicationReadyEvent` is sent after any application and command-line runners have been called. It indicates that the application is ready to service requests.
6. An `ApplicationFailedEvent` is sent if there is an exception on startup.


## Implementations

框架内部大量使用这套机制，读源码时可作为参照：

| 实现 | 作用 |
| :-- | :-- |
| `ZuulRefreshListener` | Spring Cloud Netflix 监听 `EnvironmentChangeEvent` / `RefreshEvent` 触发路由刷新 |
| `LoggingApplicationListener` | Boot 最早启动的监听器之一，在 `Environment` 就绪前就把日志系统装配好 |
| `EnvironmentPostProcessorApplicationListener` | 把 `EnvironmentPostProcessor` 的执行挂在 `ApplicationEnvironmentPreparedEvent` 上 |
| `ApplicationListenerMethodAdapter` | `@EventListener` 的运行时适配：把注解方法包成一个 `ApplicationListener` 实例 |
| `TransactionalApplicationListenerMethodAdapter` | 上者的子类，额外持有 `TransactionPhase` 与 `fallbackExecution`，在事务同步回调里投递 |

理解最后一条也就理解了事务事件的本质：**它不是一个独立的发布/订阅通道，而是一次"延迟到事务同步回调里再执行的普通事件投递"**。

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [Spring Transaction](/docs/CS/Framework/Spring/Transaction.md)
- [Spring Boot](/docs/CS/Framework/Spring_Boot/Spring_Boot.md)
- [Spring Boot 启动流程](/docs/CS/Framework/Spring_Boot/Start.md)

## References

- [Spring Framework - Standard and Custom Events](https://docs.spring.io/spring-framework/reference/core/beans/context-introduction.html)
- [TransactionalEventListener - Javadoc](https://docs.spring.io/spring-framework/javadoc-api/org/springframework/transaction/event/TransactionalEventListener.html)
- [Spring Boot - Application Events and Listeners](https://docs.spring.io/spring-boot/reference/features/spring-application.html)
