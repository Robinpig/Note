# Task



## Async

### TaskExecutor

#### Abstraction

Executors are the JDK name for the concept of thread pools. The “executor” naming is due to the fact that there is no guarantee that the underlying implementation is actually a pool. An executor may be single-threaded or even synchronous. Spring’s abstraction hides implementation details between the Java SE and Java EE environments.

Spring’s `TaskExecutor` interface is identical to the `java.util.concurrent.Executor` interface. In fact, originally, **its primary reason for existence was to abstract away the need for Java 5 when using thread pools**. The interface has a single method (`execute(Runnable task)`) that accepts a task for execution based on the semantics and configuration of the thread pool.

```java
@FunctionalInterface
public interface TaskExecutor extends Executor {
   @Override
   void execute(Runnable task);
}
```

The `TaskExecutor` was originally created to give other Spring components an abstraction for thread pooling where needed. Components such as the `ApplicationEventMulticaster`, JMS’s `AbstractMessageListenerContainer`, and Quartz integration all use the `TaskExecutor` abstraction to pool threads. However, if your beans need thread pooling behavior, you can also use this abstraction for your own needs.



#### Types

Spring includes a number of pre-built implementations of `TaskExecutor`. In all likelihood, you should never need to implement your own. The variants that Spring provides are as follows:

- `SyncTaskExecutor`: This implementation does not run invocations asynchronously. Instead, each invocation takes place in the calling thread. It is primarily used in situations where multi-threading is not necessary, such as in simple test cases.
- `SimpleAsyncTaskExecutor`: This implementation does not reuse any threads. Rather, it starts up a new thread for each invocation. However, it does support a concurrency limit that blocks any invocations that are over the limit until a slot has been freed up. If you are looking for true pooling, see `ThreadPoolTaskExecutor`, later in this list.
- `ConcurrentTaskExecutor`: This implementation is an adapter for a `java.util.concurrent.Executor` instance. There is an alternative (`ThreadPoolTaskExecutor`) that exposes the `Executor` configuration parameters as bean properties. There is rarely a need to use `ConcurrentTaskExecutor` directly. However, if the `ThreadPoolTaskExecutor` is not flexible enough for your needs, `ConcurrentTaskExecutor` is an alternative.
- `ThreadPoolTaskExecutor`: This implementation is most commonly used. It exposes bean properties for configuring a `java.util.concurrent.ThreadPoolExecutor` and wraps it in a `TaskExecutor`. If you need to adapt to a different kind of `java.util.concurrent.Executor`, we recommend that you use a `ConcurrentTaskExecutor` instead.
- `WorkManagerTaskExecutor`: This implementation uses a CommonJ `WorkManager` as its backing service provider and is the central convenience class for setting up CommonJ-based thread pool integration on WebLogic or WebSphere within a Spring application context.
- `DefaultManagedTaskExecutor`: This implementation uses a JNDI-obtained `ManagedExecutorService` in a JSR-236 compatible runtime environment (such as a Java EE 7+ application server), replacing a CommonJ WorkManager for that purpose.






### Async



**The default advice mode for processing `@Async` annotations is `proxy`** which allows for interception of calls through the proxy only. Local calls within the **same class cannot get intercepted** that way. For a more advanced mode of interception, consider switching to `aspectj` mode in combination with compile-time or load-time weaving.

### Example

```java
@Configuration
@EnableAsync
public class AppConfig {
}
```



Even methods that return a value can be invoked asynchronously. However, such methods are required to have a `Future`-typed return value. This still provides the benefit of asynchronous execution so that the caller can perform other tasks prior to calling `get()` on that `Future`. The following example shows how to use `@Async` on a method that returns a value:

```java
@Async
Future<String> returnSomething(int i) {
    // this will be run asynchronously
}
```



### Implementations

#### EnableAsync

The mode attribute controls how advice is applied: 

- If the mode is AdviceMode.PROXY (the default), then the other attributes control the behavior of the proxying. Please note that proxy mode allows for interception of calls through the proxy only; local calls within the same class cannot get intercepted that way.
- Note that if the mode is set to AdviceMode.ASPECTJ, then the value of the proxyTargetClass attribute will be ignored. Note also that in this case the spring-aspects module JAR must be present on the classpath, with compile-time weaving or load-time weaving applying the aspect to the affected classes. There is no proxy involved in such a scenario; local calls will be intercepted as well.

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



#### Inject TaskExecutors from AsyncConfigurer

```java
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
         case PROXY://actually use CglibAopProxy
            return new String[] {ProxyAsyncConfiguration.class.getName()};
         case ASPECTJ:
            return new String[] {ASYNC_EXECUTION_ASPECT_CONFIGURATION_CLASS_NAME};
         default:
            return null;
      }
   }

}

//ProxyAsyncConfiguration
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

//AbstractAsyncConfiguration.java Collect any {@link AsyncConfigurer} beans through autowiring.
@Autowired(required = false)
void setConfigurers(Collection<AsyncConfigurer> configurers) {
   if (CollectionUtils.isEmpty(configurers)) {
      return;
   }
   if (configurers.size() > 1) {
      throw new IllegalStateException("Only one AsyncConfigurer may exist");
   }
   AsyncConfigurer configurer = configurers.iterator().next();
   this.executor = configurer::getAsyncExecutor;
   this.exceptionHandler = configurer::getAsyncUncaughtExceptionHandler;
}
```



#### AsyncAnnotationBeanPostProcessor

*Bean post-processor that automatically applies asynchronous invocation behavior to any bean that carries the Async annotation at class or method-level by adding a corresponding AsyncAnnotationAdvisor to the exposed proxy (either an existing AOP proxy or a newly generated proxy that implements all of the target's interfaces).*

*override setBeanFactory method from **BeanFactoryAware***

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



#### AsyncAnnotationAdvisor

***Advisor that activates asynchronous method execution through the Async annotation.** This annotation can be used at the method and type level in implementation classes as well as in service interfaces.*
*This advisor detects the EJB 3.1 javax.ejb.Asynchronous annotation as well, treating it exactly like Spring's own Async. Furthermore, a custom async annotation type may get **specified through the "asyncAnnotationType" property**.*

```java
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

protected Advice buildAdvice(
      @Nullable Supplier<Executor> executor, @Nullable Supplier<AsyncUncaughtExceptionHandler> exceptionHandler) {

   AnnotationAsyncExecutionInterceptor interceptor = new AnnotationAsyncExecutionInterceptor(null);
   interceptor.configure(executor, exceptionHandler);
   return interceptor;
}
```

##### setAsyncAnnotationType

*Set the 'async' annotation type.*
*The default async annotation type is the Async annotation, as well as the EJB 3.1 javax.ejb.Asynchronous annotation (if present).*
*This setter property exists so that developers can provide their own (non-Spring-specific) annotation type to indicate that a method is to be executed asynchronously.*

```java
public void setAsyncAnnotationType(Class<? extends Annotation> asyncAnnotationType) {
   Assert.notNull(asyncAnnotationType, "'asyncAnnotationType' must not be null");
   Set<Class<? extends Annotation>> asyncAnnotationTypes = new HashSet<>();
   asyncAnnotationTypes.add(asyncAnnotationType);
   this.pointcut = buildPointcut(asyncAnnotationTypes);
}
```



#### AnnotationAsyncExecutionInterceptor

*getDefaultExecutor searches for a unique TaskExecutor bean in the context, or for an Executor bean named "taskExecutor" otherwise.If neither of the two is resolvable, this implementation will return null.*

```java
/**
 * Configure this aspect with the given executor and exception handler suppliers,
 * applying the corresponding default if a supplier is not resolvable.
 */
public void configure(@Nullable Supplier<Executor> defaultExecutor,
      @Nullable Supplier<AsyncUncaughtExceptionHandler> exceptionHandler) {
 
   this.defaultExecutor = new SingletonSupplier<>(defaultExecutor, () -> getDefaultExecutor(this.beanFactory));
   this.exceptionHandler = new SingletonSupplier<>(exceptionHandler, SimpleAsyncUncaughtExceptionHandler::new);
}
```



#### AsyncExecutionInterceptor

*AOP Alliance MethodInterceptor that processes method invocations asynchronously, using a given **AsyncTaskExecutor**. Typically used with the **org.springframework.scheduling.annotation.Async** annotation.*
*In terms of target method signatures, any parameter types are supported. However, the return type is constrained to either void or java.util.concurrent.Future. In the latter case, the Future handle returned from the proxy will be an actual asynchronous Future that can be used to track the result of the asynchronous method execution. However, since the target method needs to implement the same signature, it will have to return a temporary Future handle that just passes the return value through (like Spring's **org.springframework.scheduling.annotation.AsyncResult** or EJB 3.1's javax.ejb.AsyncResult).*
*When the return type is **java.util.concurrent.Future**, any exception thrown during the execution can be accessed and managed by the caller. With void return type however, such exceptions cannot be transmitted back. In that case an **AsyncUncaughtExceptionHandler** can be registered to process such exceptions.*

```java
public class AsyncExecutionInterceptor extends AsyncExecutionAspectSupport implements MethodInterceptor, Ordered {}
```



#### invoke

`CglibMethodInvocation extends ReflectiveMethodInvocation`, `CglibMethodInvocation#invokeJoinpoint()` gives a marginal performance improvement versus using reflection to invoke the target when invoking public methods.

```java
//AsyncExecutionInterceptor#invoke()
@Override
@Nullable
public Object invoke(final MethodInvocation invocation) throws Throwable {
   Class<?> targetClass = (invocation.getThis() != null ? AopUtils.getTargetClass(invocation.getThis()) : null);
   Method specificMethod = ClassUtils.getMostSpecificMethod(invocation.getMethod(), targetClass);
   final Method userDeclaredMethod = BridgeMethodResolver.findBridgedMethod(specificMethod);

  //determineAsyncExecutor, assertNotNull omission
   AsyncTaskExecutor executor = determineAsyncExecutor(userDeclaredMethod);

  //wrap Callable
   Callable<Object> task = () -> {
      try {
        // use CglibMethodInvocation#invokeJoinpoint() to improve performance
         Object result = invocation.proceed();
         if (result instanceof Future) {
            return ((Future<?>) result).get();
         }
      }
      catch (ExecutionException ex) {
         handleError(ex.getCause(), userDeclaredMethod, invocation.getArguments());
      }
      catch (Throwable ex) {
         handleError(ex, userDeclaredMethod, invocation.getArguments());
      }
      return null;
   };
	
  //submit Callable
   return doSubmit(task, executor, invocation.getMethod().getReturnType());
}
```



#### determineAsyncExecutor

*Determine the specific executor to use when executing the given method. Should preferably return an AsyncListenableTaskExecutor implementation.*

```java
//AsyncExecutionAspectSupport#determineAsyncExecutor()
private final Map<Method, AsyncTaskExecutor> executors = new ConcurrentHashMap(16);
@Nullable
protected AsyncTaskExecutor determineAsyncExecutor(Method method) {
    AsyncTaskExecutor executor = (AsyncTaskExecutor)this.executors.get(method);//1. from cache
    if (executor == null) {
        String qualifier = this.getExecutorQualifier(method);
        Executor targetExecutor;
        if (StringUtils.hasLength(qualifier)) {
          	//2. use qualifier from beanFactory
            targetExecutor = this.findQualifiedExecutor(this.beanFactory, qualifier);
        } else {
            targetExecutor = (Executor)this.defaultExecutor.get();//3. use defaultExecutor
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

##### getDefaultExecutor

*This implementation searches for a unique org.springframework.core.task.TaskExecutor bean in the context, or for an Executor bean named "`taskExecutor`" otherwise. If neither of the two is resolvable (e.g. if no BeanFactory was configured at all), this implementation falls back to a newly created **SimpleAsyncTaskExecutor** instance for local use if no default could be found.*

```java
//AsyncExecutionInterceptor#getDefaultExecutor()
@Override
@Nullable
protected Executor getDefaultExecutor(@Nullable BeanFactory beanFactory) {
   Executor defaultExecutor = super.getDefaultExecutor(beanFactory);
   return (defaultExecutor != null ? defaultExecutor : new SimpleAsyncTaskExecutor());
}
```



#### doSubmit

*Delegate for actually executing the given task with the chosen executor.*

```java
//AsyncExecutionAspectSupport#doSubmit()
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






### How to use owner TaskExecutor?

1. Implement **AsyncConfigurer**
2. **extends **AsyncConfigurerSupport
3. **Configure **TaskExecutor**







## Schedule

### TaskScheduler

#### Abstraction

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

#### implementations

As with Spring’s `TaskExecutor` abstraction, the primary benefit of the `TaskScheduler` arrangement is that an application’s scheduling needs are decoupled from the deployment environment. This abstraction level is particularly relevant when deploying to an application server environment where threads should not be created directly by the application itself. For such scenarios, Spring provides a `TimerManagerTaskScheduler` that delegates to a CommonJ `TimerManager` on WebLogic or WebSphere as well as a more recent `DefaultManagedTaskScheduler` that delegates to a JSR-236 `ManagedScheduledExecutorService` in a Java EE 7+ environment. Both are typically configured with a JNDI lookup.

Whenever external thread management is not a requirement, a simpler alternative is a local `ScheduledExecutorService` setup within the application, which can be adapted through Spring’s `ConcurrentTaskScheduler`. As a convenience, Spring also provides a `ThreadPoolTaskScheduler`, which internally delegates to a `ScheduledExecutorService` to provide common bean-style configuration along the lines of `ThreadPoolTaskExecutor`. These variants work perfectly fine for locally embedded thread pool setups in lenient application server environments, as well — in particular on Tomcat and Jetty.



### Trigger

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

#### Implementations

Spring provides two implementations of the `Trigger` interface. The most interesting one is the `CronTrigger`. It enables the scheduling of tasks based on cron expressions. For example, the following task is scheduled to run 15 minutes past each hour but only during the 9-to-5 “business hours” on weekdays:

```java
scheduler.schedule(task, new CronTrigger("0 15 9-17 * * MON-FRI"));
```

The other implementation is a `PeriodicTrigger` that accepts a fixed period, an optional initial delay value, and a boolean to indicate whether the period should be interpreted as a fixed-rate or a fixed-delay. Since the `TaskScheduler` interface already defines methods for scheduling tasks at a fixed rate or with a fixed delay, those methods should be used directly whenever possible. The value of the `PeriodicTrigger` implementation is that you can use it within components that rely on the `Trigger` abstraction. For example, it may be convenient to allow periodic triggers, cron-based triggers, and even custom trigger implementations to be used interchangeably. Such a component could take advantage of dependency injection so that you can configure such `Triggers` externally and, therefore, easily modify or extend them.



### Schedule

#### Example

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



#### Implementations

EnableScheduling import SchedulingConfiguration

#### SchedulingConfiguration

```java
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

***Bean post-processor that registers methods annotated with @Scheduled to be invoked by a TaskScheduler according to the "fixedRate", "fixedDelay", or "cron" expression provided via the annotation.***
This post-processor is automatically registered by Spring's <task:annotation-driven> XML element, and also by the @EnableScheduling annotation.
Autodetects any SchedulingConfigurer instances in the container, allowing for customization of the scheduler to be used or for fine-grained control over task registration (e.g. registration of Trigger tasks. See the @EnableScheduling javadocs for complete usage details.



##### postProcessAfterInitialization

*Implement postProcessAfterInitialization from BeanPostProcessor*

```java
@Override
public Object postProcessAfterInitialization(Object bean, String beanName) {
   if (bean instanceof AopInfrastructureBean || bean instanceof TaskScheduler ||
         bean instanceof ScheduledExecutorService) {
      // Ignore AOP infrastructure such as scoped proxies.
      return bean;
   }

   Class<?> targetClass = AopProxyUtils.ultimateTargetClass(bean);
   if (!this.nonAnnotatedClasses.contains(targetClass) &&
         AnnotationUtils.isCandidateClass(targetClass, Arrays.asList(Scheduled.class, Schedules.class))) {
      Map<Method, Set<Scheduled>> annotatedMethods = MethodIntrospector.selectMethods(targetClass,
            (MethodIntrospector.MetadataLookup<Set<Scheduled>>) method -> {
               Set<Scheduled> scheduledAnnotations = AnnotatedElementUtils.getMergedRepeatableAnnotations(
                     method, Scheduled.class, Schedules.class);
               return (!scheduledAnnotations.isEmpty() ? scheduledAnnotations : null);
            });
      if (annotatedMethods.isEmpty()) {
         this.nonAnnotatedClasses.add(targetClass);
         if (logger.isTraceEnabled()) {
            logger.trace("No @Scheduled annotations found on bean class: " + targetClass);
         }
      }
      else {
         // Non-empty set of methods
         annotatedMethods.forEach((method, scheduledAnnotations) ->
               scheduledAnnotations.forEach(scheduled -> processScheduled(scheduled, method, bean)));
         if (logger.isTraceEnabled()) {
            logger.trace(annotatedMethods.size() + " @Scheduled methods processed on bean '" + beanName +
                  "': " + annotatedMethods);
         }
      }
   }
   return bean;
}
```



##### processScheduled

*Process the given @Scheduled method declaration on the given bean.*

```java
protected void processScheduled(Scheduled scheduled, Method method, Object bean) {
   try {
      Runnable runnable = createRunnable(bean, method);
      boolean processedSchedule = false;
      String errorMessage =
            "Exactly one of the 'cron', 'fixedDelay(String)', or 'fixedRate(String)' attributes is required";

      Set<ScheduledTask> tasks = new LinkedHashSet<>(4);

      // Determine initial delay
      long initialDelay = scheduled.initialDelay();
      String initialDelayString = scheduled.initialDelayString();
      if (StringUtils.hasText(initialDelayString)) {
         Assert.isTrue(initialDelay < 0, "Specify 'initialDelay' or 'initialDelayString', not both");
         if (this.embeddedValueResolver != null) {
            initialDelayString = this.embeddedValueResolver.resolveStringValue(initialDelayString);
         }
         if (StringUtils.hasLength(initialDelayString)) {
            try {
               initialDelay = parseDelayAsLong(initialDelayString);
            }
            catch (RuntimeException ex) {
               throw new IllegalArgumentException(
                     "Invalid initialDelayString value \"" + initialDelayString + "\" - cannot parse into long");
            }
         }
      }

      // Check cron expression
      String cron = scheduled.cron();
      if (StringUtils.hasText(cron)) {
         String zone = scheduled.zone();
         if (this.embeddedValueResolver != null) {
            cron = this.embeddedValueResolver.resolveStringValue(cron);
            zone = this.embeddedValueResolver.resolveStringValue(zone);
         }
         if (StringUtils.hasLength(cron)) {
            Assert.isTrue(initialDelay == -1, "'initialDelay' not supported for cron triggers");
            processedSchedule = true;
            if (!Scheduled.CRON_DISABLED.equals(cron)) {
               TimeZone timeZone;
               if (StringUtils.hasText(zone)) {
                  timeZone = StringUtils.parseTimeZoneString(zone);
               }
               else {
                  timeZone = TimeZone.getDefault();
               }
               tasks.add(this.registrar.scheduleCronTask(new CronTask(runnable, new CronTrigger(cron, timeZone))));
            }
         }
      }

      // At this point we don't need to differentiate between initial delay set or not anymore
      if (initialDelay < 0) {
         initialDelay = 0;
      }

      // Check fixed delay
      long fixedDelay = scheduled.fixedDelay();
      if (fixedDelay >= 0) {
         Assert.isTrue(!processedSchedule, errorMessage);
         processedSchedule = true;
         tasks.add(this.registrar.scheduleFixedDelayTask(new FixedDelayTask(runnable, fixedDelay, initialDelay)));
      }
      String fixedDelayString = scheduled.fixedDelayString();
      if (StringUtils.hasText(fixedDelayString)) {
         if (this.embeddedValueResolver != null) {
            fixedDelayString = this.embeddedValueResolver.resolveStringValue(fixedDelayString);
         }
         if (StringUtils.hasLength(fixedDelayString)) {
            Assert.isTrue(!processedSchedule, errorMessage);
            processedSchedule = true;
            try {
               fixedDelay = parseDelayAsLong(fixedDelayString);
            }
            catch (RuntimeException ex) {
               throw new IllegalArgumentException(
                     "Invalid fixedDelayString value \"" + fixedDelayString + "\" - cannot parse into long");
            }
            tasks.add(this.registrar.scheduleFixedDelayTask(new FixedDelayTask(runnable, fixedDelay, initialDelay)));
         }
      }

      // Check fixed rate
      long fixedRate = scheduled.fixedRate();
      if (fixedRate >= 0) {
         Assert.isTrue(!processedSchedule, errorMessage);
         processedSchedule = true;
         tasks.add(this.registrar.scheduleFixedRateTask(new FixedRateTask(runnable, fixedRate, initialDelay)));
      }
      String fixedRateString = scheduled.fixedRateString();
      if (StringUtils.hasText(fixedRateString)) {
         if (this.embeddedValueResolver != null) {
            fixedRateString = this.embeddedValueResolver.resolveStringValue(fixedRateString);
         }
         if (StringUtils.hasLength(fixedRateString)) {
            Assert.isTrue(!processedSchedule, errorMessage);
            processedSchedule = true;
            try {
               fixedRate = parseDelayAsLong(fixedRateString);
            }
            catch (RuntimeException ex) {
               throw new IllegalArgumentException(
                     "Invalid fixedRateString value \"" + fixedRateString + "\" - cannot parse into long");
            }
            tasks.add(this.registrar.scheduleFixedRateTask(new FixedRateTask(runnable, fixedRate, initialDelay)));
         }
      }

      // Check whether we had any attribute set
      Assert.isTrue(processedSchedule, errorMessage);

      // Finally register the scheduled tasks
      synchronized (this.scheduledTasks) {
         Set<ScheduledTask> regTasks = this.scheduledTasks.computeIfAbsent(bean, key -> new LinkedHashSet<>(4));
         regTasks.addAll(tasks);
      }
   }
   catch (IllegalArgumentException ex) {
      throw new IllegalStateException(
            "Encountered invalid @Scheduled method '" + method.getName() + "': " + ex.getMessage());
   }
}
```

*Create a Runnable for the given bean instance, calling the specified scheduled method.*

```java
protected Runnable createRunnable(Object target, Method method) {
   Assert.isTrue(method.getParameterCount() == 0, "Only no-arg methods may be annotated with @Scheduled");
   Method invocableMethod = AopUtils.selectInvocableMethod(method, target.getClass());
   return new ScheduledMethodRunnable(target, invocableMethod);
}
```



cannot be invoke:

- private 
- static
- instanceof SpringProxy

```java
public static Method selectInvocableMethod(Method method, @Nullable Class<?> targetType) {
   if (targetType == null) {
      return method;
   }
   Method methodToUse = MethodIntrospector.selectInvocableMethod(method, targetType);
   if (Modifier.isPrivate(methodToUse.getModifiers()) && !Modifier.isStatic(methodToUse.getModifiers()) &&
         SpringProxy.class.isAssignableFrom(targetType)) {
      throw new IllegalStateException(String.format(
            "Need to invoke method '%s' found on proxy for target class '%s' but cannot " +
            "be delegated to target bean. Switch its visibility to package or protected.",
            method.getName(), method.getDeclaringClass().getSimpleName()));
   }
   return methodToUse;
}
```



## References

- [Spring 5.2.x doc](https://docs.spring.io/spring-framework/docs/5.2.x/spring-framework-reference/integration.html#scheduling)