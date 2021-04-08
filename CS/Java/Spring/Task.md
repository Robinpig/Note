# Task

## TaskExecutor

### Abstraction

Executors are the JDK name for the concept of thread pools. The “executor” naming is due to the fact that there is no guarantee that the underlying implementation is actually a pool. An executor may be single-threaded or even synchronous. Spring’s abstraction hides implementation details between the Java SE and Java EE environments.

Spring’s `TaskExecutor` interface is identical to the `java.util.concurrent.Executor` interface. In fact, originally, its primary reason for existence was to abstract away the need for Java 5 when using thread pools. The interface has a single method (`execute(Runnable task)`) that accepts a task for execution based on the semantics and configuration of the thread pool.

The `TaskExecutor` was originally created to give other Spring components an abstraction for thread pooling where needed. Components such as the `ApplicationEventMulticaster`, JMS’s `AbstractMessageListenerContainer`, and Quartz integration all use the `TaskExecutor` abstraction to pool threads. However, if your beans need thread pooling behavior, you can also use this abstraction for your own needs.



### Types

Spring includes a number of pre-built implementations of `TaskExecutor`. In all likelihood, you should never need to implement your own. The variants that Spring provides are as follows:

- `SyncTaskExecutor`: This implementation does not run invocations asynchronously. Instead, each invocation takes place in the calling thread. It is primarily used in situations where multi-threading is not necessary, such as in simple test cases.
- `SimpleAsyncTaskExecutor`: This implementation does not reuse any threads. Rather, it starts up a new thread for each invocation. However, it does support a concurrency limit that blocks any invocations that are over the limit until a slot has been freed up. If you are looking for true pooling, see `ThreadPoolTaskExecutor`, later in this list.
- `ConcurrentTaskExecutor`: This implementation is an adapter for a `java.util.concurrent.Executor` instance. There is an alternative (`ThreadPoolTaskExecutor`) that exposes the `Executor` configuration parameters as bean properties. There is rarely a need to use `ConcurrentTaskExecutor` directly. However, if the `ThreadPoolTaskExecutor` is not flexible enough for your needs, `ConcurrentTaskExecutor` is an alternative.
- `ThreadPoolTaskExecutor`: This implementation is most commonly used. It exposes bean properties for configuring a `java.util.concurrent.ThreadPoolExecutor` and wraps it in a `TaskExecutor`. If you need to adapt to a different kind of `java.util.concurrent.Executor`, we recommend that you use a `ConcurrentTaskExecutor` instead.
- `WorkManagerTaskExecutor`: This implementation uses a CommonJ `WorkManager` as its backing service provider and is the central convenience class for setting up CommonJ-based thread pool integration on WebLogic or WebSphere within a Spring application context.
- `DefaultManagedTaskExecutor`: This implementation uses a JNDI-obtained `ManagedExecutorService` in a JSR-236 compatible runtime environment (such as a Java EE 7+ application server), replacing a CommonJ WorkManager for that purpose.
- 

## TaskScheduler

### Abstraction

In addition to the `TaskExecutor` abstraction, Spring 3.0 introduced a `TaskScheduler` with a variety of methods for scheduling tasks to run at some point in the future. The following listing shows the `TaskScheduler` interface definition:

```java
public interface TaskScheduler {

    ScheduledFuture schedule(Runnable task, Trigger trigger);

    ScheduledFuture schedule(Runnable task, Instant startTime);

    ScheduledFuture schedule(Runnable task, Date startTime);

    ScheduledFuture scheduleAtFixedRate(Runnable task, Instant startTime, Duration period);

    ScheduledFuture scheduleAtFixedRate(Runnable task, Date startTime, long period);

    ScheduledFuture scheduleAtFixedRate(Runnable task, Duration period);

    ScheduledFuture scheduleAtFixedRate(Runnable task, long period);

    ScheduledFuture scheduleWithFixedDelay(Runnable task, Instant startTime, Duration delay);

    ScheduledFuture scheduleWithFixedDelay(Runnable task, Date startTime, long delay);

    ScheduledFuture scheduleWithFixedDelay(Runnable task, Duration delay);

    ScheduledFuture scheduleWithFixedDelay(Runnable task, long delay);
}
```

The simplest method is the one named `schedule` that takes only a `Runnable` and a `Date`. That causes the task to run once after the specified time. All of the other methods are capable of scheduling tasks to run repeatedly. The fixed-rate and fixed-delay methods are for simple, periodic execution, but the method that accepts a `Trigger` is much more flexible.

### implementations

As with Spring’s `TaskExecutor` abstraction, the primary benefit of the `TaskScheduler` arrangement is that an application’s scheduling needs are decoupled from the deployment environment. This abstraction level is particularly relevant when deploying to an application server environment where threads should not be created directly by the application itself. For such scenarios, Spring provides a `TimerManagerTaskScheduler` that delegates to a CommonJ `TimerManager` on WebLogic or WebSphere as well as a more recent `DefaultManagedTaskScheduler` that delegates to a JSR-236 `ManagedScheduledExecutorService` in a Java EE 7+ environment. Both are typically configured with a JNDI lookup.

Whenever external thread management is not a requirement, a simpler alternative is a local `ScheduledExecutorService` setup within the application, which can be adapted through Spring’s `ConcurrentTaskScheduler`. As a convenience, Spring also provides a `ThreadPoolTaskScheduler`, which internally delegates to a `ScheduledExecutorService` to provide common bean-style configuration along the lines of `ThreadPoolTaskExecutor`. These variants work perfectly fine for locally embedded thread pool setups in lenient application server environments, as well — in particular on Tomcat and Jetty.



## Trigger

The `Trigger` interface is essentially inspired by JSR-236 which, as of Spring 3.0, was not yet officially implemented. The basic idea of the `Trigger` is that execution times may be determined based on past execution outcomes or even arbitrary conditions. If these determinations do take into account the outcome of the preceding execution, that information is available within a `TriggerContext`. The `Trigger` interface itself is quite simple, as the following listing shows:

```java
public interface Trigger {

    Date nextExecutionTime(TriggerContext triggerContext);
}
```

The `TriggerContext` is the most important part. It encapsulates all of the relevant data and is open for extension in the future, if necessary. The `TriggerContext` is an interface (a `SimpleTriggerContext` implementation is used by default). The following listing shows the available methods for `Trigger` implementations.

```java
public interface TriggerContext {

    Date lastScheduledExecutionTime();

    Date lastActualExecutionTime();

    Date lastCompletionTime();
}
```

### Implementations

Spring provides two implementations of the `Trigger` interface. The most interesting one is the `CronTrigger`. It enables the scheduling of tasks based on cron expressions. For example, the following task is scheduled to run 15 minutes past each hour but only during the 9-to-5 “business hours” on weekdays:

```java
scheduler.schedule(task, new CronTrigger("0 15 9-17 * * MON-FRI"));
```

The other implementation is a `PeriodicTrigger` that accepts a fixed period, an optional initial delay value, and a boolean to indicate whether the period should be interpreted as a fixed-rate or a fixed-delay. Since the `TaskScheduler` interface already defines methods for scheduling tasks at a fixed rate or with a fixed delay, those methods should be used directly whenever possible. The value of the `PeriodicTrigger` implementation is that you can use it within components that rely on the `Trigger` abstraction. For example, it may be convenient to allow periodic triggers, cron-based triggers, and even custom trigger implementations to be used interchangeably. Such a component could take advantage of dependency injection so that you can configure such `Triggers` externally and, therefore, easily modify or extend them.





## Async



The default advice mode for processing `@Async` annotations is `proxy` which allows for interception of calls through the proxy only. Local calls within the **same class cannot get intercepted** that way. For a more advanced mode of interception, consider switching to `aspectj` mode in combination with compile-time or load-time weaving.



### @EnableAsync

```java
@Target({ElementType.TYPE})
@Retention(RetentionPolicy.RUNTIME)
@Documented
@Import({AsyncConfigurationSelector.class})
public @interface EnableAsync {
    Class<? extends Annotation> annotation() default Annotation.class;

    boolean proxyTargetClass() default false;

    AdviceMode mode() default AdviceMode.PROXY;

    int order() default 2147483647;
}
```

```java
/**
 * Selects which implementation of {@link AbstractAsyncConfiguration} should
 * be used based on the value of {@link EnableAsync#mode} on the importing
 * {@code @Configuration} class.
 *
 * @author Chris Beams
 * @author Juergen Hoeller
 * @since 3.1
 * @see EnableAsync
 * @see ProxyAsyncConfiguration
 */
public class AsyncConfigurationSelector extends AdviceModeImportSelector<EnableAsync> {

   private static final String ASYNC_EXECUTION_ASPECT_CONFIGURATION_CLASS_NAME =
         "org.springframework.scheduling.aspectj.AspectJAsyncConfiguration";


   /**
    * Returns {@link ProxyAsyncConfiguration} or {@code AspectJAsyncConfiguration}
    * for {@code PROXY} and {@code ASPECTJ} values of {@link EnableAsync#mode()},
    * respectively.
    */
   @Override
   @Nullable
   public String[] selectImports(AdviceMode adviceMode) {
      switch (adviceMode) {
         case PROXY:
            return new String[] {ProxyAsyncConfiguration.class.getName()};
         case ASPECTJ:
            return new String[] {ASYNC_EXECUTION_ASPECT_CONFIGURATION_CLASS_NAME};
         default:
            return null;
      }
   }

}
```

```java
/**
 * {@code @Configuration} class that registers the Spring infrastructure beans necessary
 * to enable proxy-based asynchronous method execution.
 *
 * @author Chris Beams
 * @author Stephane Nicoll
 * @author Juergen Hoeller
 * @since 3.1
 * @see EnableAsync
 * @see AsyncConfigurationSelector
 */
@Configuration
@Role(BeanDefinition.ROLE_INFRASTRUCTURE)
public class ProxyAsyncConfiguration extends AbstractAsyncConfiguration {

   @Bean(name = TaskManagementConfigUtils.ASYNC_ANNOTATION_PROCESSOR_BEAN_NAME)
   @Role(BeanDefinition.ROLE_INFRASTRUCTURE)
   public AsyncAnnotationBeanPostProcessor asyncAdvisor() {
      Assert.notNull(this.enableAsync, "@EnableAsync annotation metadata was not injected");
      AsyncAnnotationBeanPostProcessor bpp = new AsyncAnnotationBeanPostProcessor();
      bpp.configure(this.executor, this.exceptionHandler);
      Class<? extends Annotation> customAsyncAnnotation = this.enableAsync.getClass("annotation");
      if (customAsyncAnnotation != AnnotationUtils.getDefaultValue(EnableAsync.class, "annotation")) {
         bpp.setAsyncAnnotationType(customAsyncAnnotation);
      }
      bpp.setProxyTargetClass(this.enableAsync.getBoolean("proxyTargetClass"));
      bpp.setOrder(this.enableAsync.<Integer>getNumber("order"));
      return bpp;
   }

}
```



```java
@Override
public void setBeanFactory(BeanFactory beanFactory) {
   super.setBeanFactory(beanFactory);

   AsyncAnnotationAdvisor advisor = new AsyncAnnotationAdvisor(this.executor, this.exceptionHandler);
   if (this.asyncAnnotationType != null) {
      advisor.setAsyncAnnotationType(this.asyncAnnotationType);
   }
   advisor.setBeanFactory(beanFactory);
   this.advisor = advisor;
}
```

```java
/**
 * Create a new {@code AsyncAnnotationAdvisor} for the given task executor.
 * @param executor the task executor to use for asynchronous methods
 * (can be {@code null} to trigger default executor resolution)
 * @param exceptionHandler the {@link AsyncUncaughtExceptionHandler} to use to
 * handle unexpected exception thrown by asynchronous method executions
 * @since 5.1
 * @see AnnotationAsyncExecutionInterceptor#getDefaultExecutor(BeanFactory)
 */
@SuppressWarnings("unchecked")
public AsyncAnnotationAdvisor(
      @Nullable Supplier<Executor> executor, @Nullable Supplier<AsyncUncaughtExceptionHandler> exceptionHandler) {

   Set<Class<? extends Annotation>> asyncAnnotationTypes = new LinkedHashSet<>(2);
   asyncAnnotationTypes.add(Async.class);
   try {
      asyncAnnotationTypes.add((Class<? extends Annotation>)
            ClassUtils.forName("javax.ejb.Asynchronous", AsyncAnnotationAdvisor.class.getClassLoader()));
   }
   catch (ClassNotFoundException ex) {
      // If EJB 3.1 API not present, simply ignore.
   }
   this.advice = buildAdvice(executor, exceptionHandler);
   this.pointcut = buildPointcut(asyncAnnotationTypes);
}
```



```java
protected Advice buildAdvice(
      @Nullable Supplier<Executor> executor, @Nullable Supplier<AsyncUncaughtExceptionHandler> exceptionHandler) {

   AnnotationAsyncExecutionInterceptor interceptor = new AnnotationAsyncExecutionInterceptor(null);
   interceptor.configure(executor, exceptionHandler);
   return interceptor;
}
```



```java
@Nullable
protected AsyncTaskExecutor determineAsyncExecutor(Method method) {
    AsyncTaskExecutor executor = (AsyncTaskExecutor)this.executors.get(method);
    if (executor == null) {
        String qualifier = this.getExecutorQualifier(method);
        Executor targetExecutor;
        if (StringUtils.hasLength(qualifier)) {
            targetExecutor = this.findQualifiedExecutor(this.beanFactory, qualifier);
        } else {
            targetExecutor = (Executor)this.defaultExecutor.get();
        }

        if (targetExecutor == null) {
            return null;
        }

        executor = targetExecutor instanceof AsyncListenableTaskExecutor ? (AsyncListenableTaskExecutor)targetExecutor : new TaskExecutorAdapter(targetExecutor);
        this.executors.put(method, executor);
    }

    return (AsyncTaskExecutor)executor;
}
```

```java
/**
 * Delegate for actually executing the given task with the chosen executor.
 * @param task the task to execute
 * @param executor the chosen executor
 * @param returnType the declared return type (potentially a {@link Future} variant)
 * @return the execution result (potentially a corresponding {@link Future} handle)
 */
@Nullable
protected Object doSubmit(Callable<Object> task, AsyncTaskExecutor executor, Class<?> returnType) {
   if (CompletableFuture.class.isAssignableFrom(returnType)) {
      return CompletableFuture.supplyAsync(() -> {
         try {
            return task.call();
         }
         catch (Throwable ex) {
            throw new CompletionException(ex);
         }
      }, executor);
   }
   else if (ListenableFuture.class.isAssignableFrom(returnType)) {
      return ((AsyncListenableTaskExecutor) executor).submitListenable(task);
   }
   else if (Future.class.isAssignableFrom(returnType)) {
      return executor.submit(task);
   }
   else {
      executor.submit(task);
      return null;
   }
}
```

@Async

```java
@Target({ElementType.TYPE, ElementType.METHOD})
@Retention(RetentionPolicy.RUNTIME)
@Documented
public @interface Async {
    String value() default "";
}
```



Even methods that return a value can be invoked asynchronously. However, such methods are required to have a `Future`-typed return value. This still provides the benefit of asynchronous execution so that the caller can perform other tasks prior to calling `get()` on that `Future`. The following example shows how to use `@Async` on a method that returns a value:

```java
@Async
Future<String> returnSomething(int i) {
    // this will be run asynchronously
}
```



## Schedule



### Example

Enables Spring's scheduled task execution capability. To be used on @Configuration classes as follows:

```java
   @Configuration
   @EnableScheduling
   public class AppConfig {
       // various @Bean definitions
   }
```

This enables detection of @Scheduled annotations on any Spring-managed bean in the container. For example, given a class MyTask


```java
public class MyTask {
   @Scheduled(fixedRate=1000)
   public void work() {
       // task execution logic
   }
}
```



### Implementations

EnableScheduling import SchedulingConfiguration

#### SchedulingConfiguration

```java
/**
 * {@code @Configuration} class that registers a {@link ScheduledAnnotationBeanPostProcessor}
 * bean capable of processing Spring's @{@link Scheduled} annotation.
 *
 * <p>This configuration class is automatically imported when using the
 * {@link EnableScheduling @EnableScheduling} annotation. See
 * {@code @EnableScheduling}'s javadoc for complete usage details.
 *
 * @author Chris Beams
 * @since 3.1
 * @see EnableScheduling
 * @see ScheduledAnnotationBeanPostProcessor
 */
@Configuration
@Role(BeanDefinition.ROLE_INFRASTRUCTURE)
public class SchedulingConfiguration {

   @Bean(name = TaskManagementConfigUtils.SCHEDULED_ANNOTATION_PROCESSOR_BEAN_NAME)
   @Role(BeanDefinition.ROLE_INFRASTRUCTURE)
   public ScheduledAnnotationBeanPostProcessor scheduledAnnotationProcessor() {
      return new ScheduledAnnotationBeanPostProcessor();
   }

}
```



#### ScheduledAnnotationBeanPostProcessor

Bean post-processor that registers methods annotated with @Scheduled to be invoked by a TaskScheduler according to the "fixedRate", "fixedDelay", or "cron" expression provided via the annotation.
This post-processor is automatically registered by Spring's <task:annotation-driven> XML element, and also by the @EnableScheduling annotation.
Autodetects any SchedulingConfigurer instances in the container, allowing for customization of the scheduler to be used or for fine-grained control over task registration (e.g. registration of Trigger tasks. See the @EnableScheduling javadocs for complete usage details.



## References

- [Spring 5.2.x doc](https://docs.spring.io/spring-framework/docs/5.2.x/spring-framework-reference/integration.html#scheduling)