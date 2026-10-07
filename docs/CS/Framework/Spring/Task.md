## Introduction

Spring 对其它分布式任务调度框架大多采用 processor 接口方案：用户通过继承接口实现调度任务，或使用框架提供的方法注解，由框架自动生成代理 processor。

## Async

### TaskExecutor



#### Abstraction

`Executors` 是 JDK 对线程池概念的命名。“executor” 这个叫法源于底层实现未必真的是池——它可能是单线程的，甚至是同步执行的。Spring 的抽象把 Java SE 与 Java EE 环境下的实现细节屏蔽掉。

Spring 的 `TaskExecutor` 接口与 `java.util.concurrent.Executor` 接口完全一致。实际上它最初存在的首要理由，就是在用到线程池时**屏蔽对 Java 5 的依赖**。该接口只有一个方法 `execute(Runnable task)`，按照线程池的语义与配置接收一个待执行任务。

```java
@FunctionalInterface
public interface TaskExecutor extends Executor {
   @Override
   void execute(Runnable task);
}
```

TaskExecutor 最初是为 Spring 其它组件提供线程池抽象而创建的。像 `ApplicationEventMulticaster`、JMS 的 `AbstractMessageListenerContainer`、以及 Quartz 集成等组件都用 `TaskExecutor` 抽象来做线程池。不过，如果你的 bean 也需要线程池行为，同样可以用这个抽象。



 
Spring 内置了若干 `TaskExecutor` 实现，绝大多数情况下你都不需要自己实现。Spring 提供的变体如下：

- `SyncTaskExecutor`：不异步执行，每次调用都在调用线程内完成。主要用于不需要多线程的场景，例如简单测试用例。
- `SimpleAsyncTaskExecutor`：不复用线程，每次调用都启动一个新线程。但它支持并发上限，超过上限的调用会被阻塞直到有空闲槽位。如果需要真正的池化，请看本列表后面的 `ThreadPoolTaskExecutor`。
- `ConcurrentTaskExecutor`：对 `java.util.concurrent.Executor` 实例的适配器。另有 `ThreadPoolTaskExecutor` 把 Executor 的配置参数以 bean 属性的形式暴露出来。直接用 `ConcurrentTaskExecutor` 的情况很少；但若 `ThreadPoolTaskExecutor` 不够灵活，`ConcurrentTaskExecutor` 可以作为替代。
- `ThreadPoolTaskExecutor`：最常用。它把 `java.util.concurrent.ThreadPoolExecutor` 的配置以 bean 属性形式暴露，并包装成 `TaskExecutor`。如果你要适配其它类型的 `java.util.concurrent.Executor`，建议改用 `ConcurrentTaskExecutor`。
- `WorkManagerTaskExecutor`：以 CommonJ `WorkManager` 作为底层服务提供者，是在 WebLogic / WebSphere 的 Spring 应用上下文里搭建 CommonJ 线程池集成的核心便捷类。
- `DefaultManagedTaskExecutor`：在兼容 JSR-236 的运行环境（如 Java EE 7+ 应用服务器）里通过 JNDI 获取 `ManagedExecutorService` 来使用，以此取代 CommonJ 的 WorkManager。


从TaskExecutionProperties和TaskExecutionAutoConfiguration两个配置类我们看到
Spring自动装载的ThreadPoolTaskExecutor线程池对象的参数：核心线程数=8；最大线程数=Integer.MAX_VALUE；队列大小=Integer.MAX_VALUE

如果在使用 Async 注解时没有指定自定义的线程池会出现以下几种情况：
- 当 Spring 容器中有且仅有一个 TaskExecutor 实例时，Spring 会用这个线程池来处理 Async 注解的异步任务，这可能会踩坑，如果这个 TaskExecutor 实例是第三方 jar 引入的，可能会出现很诡异的问题。
- Spring 创建一个核心线程数=8、最大线程数=Integer.MAX_VALUE、队列大小=Integer.MAX_VALUE 的线程池来处理 Async 注解的异步任务，这时候也可能会踩坑，由于线程池参数设置不合理，核心线程数=8，队列大小过大，如果有大批量并发任务，可能会出现 OOM。
- Spring 创建 SimpleAsyncTaskExecutor 实例来处理 Async 注解的异步任务，SimpleAsyncTaskExecutor 不是一个好的线程池实现类，SimpleAsyncTaskExecutor 根据需要在当前线程或者新线程中执行异步任务。如果当前线程已经有空闲线程可用，任务将在当前线程中执行，否则将创建一个新线程来执行任务。由于这个线程池没有线程管理的能力，每次提交任务都实时创建新城，所以如果任务量大，会导致性能下降



### 虚拟线程

Java 21 的虚拟线程（Virtual Threads）在 Framework 7 / Boot 4 中已是一等公民，一行配置即可让 Web 请求处理、`@Async` 执行、任务调度全部跑在虚拟线程上：

```properties
spring.threads.virtual.enabled=true
```

开启后 Spring 会换上 `VirtualThreadTaskExecutor` 等实现，业务代码无需改动。虚拟线程把"线程即昂贵资源"的假设取消了，让阻塞式编程在高并发下重新可行；但仍需注意两点：`synchronized` 块可能造成载体线程 pinning，以及 `ThreadLocal` 的滥用（可考虑 `ScopedValue`）。

与虚拟线程配套的声明式并发限制由 `@ConcurrencyLimit` 提供（Framework 7 从 Spring Retry 收编进来），用于限制某方法的并发执行数，避免下游被打爆。

### Async



处理 `@Async` 注解的**默认 advice 模式是 `proxy`**，这意味着只有经由代理发起的调用才会被拦截。**同一个类内部的本地调用无法被这种方式拦截**。若需要更高级的拦截（包括内部调用），可切换到 `aspectj` 模式，配合编译期织入或加载期织入使用。

### Example

```java
@Configuration
@EnableAsync
public class AppConfig {
}
```



即便是有返回值的方法也能异步调用。不过这类方法的返回值类型必须是 `Future`。这仍然带来异步执行的好处——调用方可以在调用该 `Future` 的 `get()` 之前先去做别的事。下面这个例子演示了如何在有返回值的方法上使用 `@Async`：

```java
@Async
Future<String> returnSomething(int i) {
    // this will be run asynchronously
}
```



### Implementations

#### EnableAsync

mode 属性控制 advice 的施加方式：

- 若 mode 为 AdviceMode.PROXY（默认），其余属性控制代理的行为。注意代理模式下只有经由代理的调用会被拦截；同一个类内部的本地调用无法被这种方式拦截。
- 若 mode 设为 AdviceMode.ASPECTJ，则 proxyTargetClass 属性的值会被忽略。此时 classpath 上必须存在 spring-aspects 模块 JAR，并由编译期织入或加载期织入把切面作用到受影响的类上。这种场景下没有代理，本地调用也会被拦截。

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

*Bean 后置处理器：为任何在类或方法级别标注了 Async 注解的 bean 自动施加异步调用行为，做法是向暴露出来的代理（既可以是已有的 AOP 代理，也可以是新生成的、实现了目标所有接口的代理）追加一个对应的 AsyncAnnotationAdvisor。*

*重写来自 **BeanFactoryAware** 的 setBeanFactory 方法*

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

***通过 Async 注解激活异步方法执行的 Advisor。** 该注解既可用于实现类的方法级与类型级，也可用于服务接口。*
*该 advisor 也能识别 EJB 3.1 的 javax.ejb.Asynchronous 注解，把它当作 Spring 自己的 Async 一样处理。此外，还可以通过 **"asyncAnnotationType" 属性**指定一个自定义的异步注解类型。*

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

*getDefaultExecutor 会在容器里查找唯一的 TaskExecutor bean，否则查找名为 "taskExecutor" 的 Executor bean。若两者都无法解析，该实现返回 null。*

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

*AOP Alliance 的 MethodInterceptor，使用给定的 **AsyncTaskExecutor** 异步处理方法调用。通常与 **org.springframework.scheduling.annotation.Async** 注解配合使用。*
*就目标方法签名而言，任何参数类型都支持；但返回值类型被限定为 void 或 java.util.concurrent.Future。在后一种情况下，代理返回的 Future 句柄是一个真正的异步 Future，可用于追踪异步方法的执行结果。不过由于目标方法需要实现同样的签名，它只能返回一个临时的 Future 句柄把返回值透传过去（类似 Spring 的 **org.springframework.scheduling.annotation.AsyncResult** 或 EJB 3.1 的 javax.ejb.AsyncResult）。*
*当返回类型是 **java.util.concurrent.Future** 时，执行期间抛出的任何异常都能被调用方获取并处理；而 void 返回类型下异常无法回传，此时可以注册一个 **AsyncUncaughtExceptionHandler** 来处理这类异常。*

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

*确定执行给定方法时要使用的具体 executor，最好返回一个 AsyncListenableTaskExecutor 实现。*

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

[CompletableFuture.supplyAsync()](/docs/CS/Java/JDK/Concurrency/Future.md?id=completablefuture)

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

除了 `TaskExecutor` 抽象，Spring 3.0 还引入了 `TaskScheduler`，它提供多种把任务安排在未来某个时刻运行的方法。下面的清单展示了 `TaskScheduler` 接口定义：

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

最简单的方法是名为 `schedule` 的那个，它只接收 `Runnable` 与 `Date`。
它使任务在指定时间之后运行一次。其余方法都能把任务安排成重复执行。fixed-rate 与 fixed-delay 方法用于简单的周期执行，而接受 `Trigger` 的方法要灵活得多。

#### implementations

与 Spring 的 `TaskExecutor` 抽象一样，`TaskScheduler` 机制的主要好处是让应用的调度需求与部署环境解耦。在应用服务器环境里线程不应由应用自身直接创建，这种抽象层级就显得尤为关键。针对这类场景，Spring 提供了 `TimerManagerTaskScheduler`（在 WebLogic / WebSphere 上委托给 CommonJ 的 `TimerManager`），以及较新的 `DefaultManagedTaskScheduler`（在 Java EE 7+ 环境里委托给 JSR-236 的 `ManagedScheduledExecutorService`）。两者通常都通过 JNDI 查找来配置。

若不需要外部线程管理，更简单的方式是在应用内部搭建一个本地 `ScheduledExecutorService`，并通过 Spring 的 `ConcurrentTaskScheduler` 适配它。作为便利，Spring 还提供了 `ThreadPoolTaskScheduler`，它在内部委托给 `ScheduledExecutorService`，从而提供类似 `ThreadPoolTaskExecutor` 的 bean 风格配置。这些变体在本地的嵌入式线程池场景里都很好用，在宽松的应用服务器环境（特别是 Tomcat 和 Jetty）下同样如此。


ThreadPoolTaskScheduler 默认线程数只有 1，多个定时任务会串行执行。而且它同时实现了 TaskExecutor，可能被 @Async 误用造成混淆。


### Trigger

`Trigger` 接口的灵感基本来自 JSR-236，而在 Spring 3.0 时该规范尚未正式实现。`Trigger` 的基本思想是：执行时间可以基于过往的执行结果、甚至任意条件来确定。如果这些判定确实参考了上一次执行的结果，那么相关信息可从 `TriggerContext` 中获取。`Trigger` 接口本身相当简单，如下所示：

```java
public interface Trigger {

    Date nextExecutionTime(TriggerContext triggerContext);
}
```

`TriggerContext` 是最关键的部分。它封装了所有相关数据，并预留了未来扩展的空间。`TriggerContext` 是一个接口（默认使用 `SimpleTriggerContext` 实现）。下面的清单展示了 `Trigger` 实现可用的那些方法。

```java
public interface TriggerContext {

    Date lastScheduledExecutionTime();

    Date lastActualExecutionTime();

    Date lastCompletionTime();
}
```

#### Implementations

Spring 提供了 `Trigger` 接口的两个实现。最有趣的是 `CronTrigger`，它基于 cron 表达式来安排任务。例如，下面这个任务被安排在每个小时过去 15 分钟后运行，但仅限于工作日的 9 点到 17 点“办公时间”：

```
scheduler.schedule(task, new CronTrigger("0 15 9-17 * * MON-FRI"));
```

另一个实现是 `PeriodicTrigger`，它接受一个固定周期、一个可选的初始延迟值，以及一个布尔值用于指明该周期应解释为 fixed-rate 还是 fixed-delay。由于 `TaskScheduler` 接口已经定义了以固定速率或固定延迟调度任务的方法，应优先直接使用那些方法。`PeriodicTrigger` 的价值在于你可以在依赖 `Trigger` 抽象的组件里使用它。例如，让周期触发器、基于 cron 的触发器、乃至自定义触发器实现可以互换使用会非常方便；这样的组件可以利用依赖注入，让你在外部配置这些 `Triggers`，从而轻松修改或扩展它们。



### Schedule

#### Example

启用 Spring 的定时任务执行能力，用在 `@Configuration` 类上，如下所示：

```java
   @Configuration
   @EnableScheduling
   public class AppConfig {
       // various @Bean definitions
   }
```

这会让容器里任意 Spring 管理的 bean 上的 `@Scheduled` 注解被扫描到。例如，给定一个 MyTask 类


```java
public class MyTask {
   @Scheduled(fixedRate=1000)
   public void work() {
       // task execution logic
   }
}
```

#### @Scheduled 参数语义

| 属性 | 含义 |
|---|---|
| `fixedRate` / `fixedRateString` | 固定**频率**：从每次任务**开始**计时，间隔到点就尝试触发；任务执行慢于周期时不会并发执行（默认单线程），表现为任务排队 |
| `fixedDelay` / `fixedDelayString` | 固定**延迟**：从每次任务**完成**到下一次开始之间等待 |
| `initialDelay` / `initialDelayString` | 首次执行前的等待毫秒数，只对 fixedRate/fixedDelay 生效 |
| `cron` | cron 表达式（秒 分 时 日 月 周），如 `"*/5 * * * * MON-FRI"`；值为 `"-"`（`Scheduled.CRON_DISABLED`）表示禁用 |
| `zone` | cron 解析所用时区，默认 JVM 默认时区 |

`cron`、`fixedDelay`、`fixedRate` 三者**必须且只能指定一个**，否则启动报错（对应源码里的 `Exactly one of ...` 断言）。cron 触发不支持 initialDelay。

#### 启用方式

`@EnableScheduling` 负责扫描 `@Scheduled`，`@EnableAsync` 负责 `@Async`，两者独立，按需开启：

```java
@Configuration
@EnableAsync
@EnableScheduling
public class AppConfig { }
```

需要更细粒度控制时实现 `SchedulingConfigurer` / `AsyncConfigurer`，可以指定自定义的 `TaskScheduler` / `TaskExecutor`。



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

***Bean 后置处理器：把标注了 @Scheduled 的方法注册为由 TaskScheduler 按照注解提供的 "fixedRate"、"fixedDelay" 或 "cron" 表达式来调用。***
该后置处理器由 Spring 的 <task:annotation-driven> XML 元素自动注册，也由 @EnableScheduling 注解自动注册。
会自动发现容器里的任何 SchedulingConfigurer 实例，从而可以定制所使用的调度器，或对任务注册做细粒度控制（例如注册 Trigger 任务）。完整用法见 @EnableScheduling 的 javadoc。



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
      }
      else {
         // Non-empty set of methods
         annotatedMethods.forEach((method, scheduledAnnotations) ->
               scheduledAnnotations.forEach(scheduled -> processScheduled(scheduled, method, bean)));
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



无法被调用：

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

## Quartz Integration

对于需要持久化、misfire 处理、集群调度等复杂场景，Spring 提供了对 [Quartz](/docs/CS/Framework/Job/Quartz/Quartz.md) 的集成，核心是几个 `FactoryBean`：

- `JobDetailFactoryBean`：配置 Quartz 的 `JobDetail`（Job 类型、名称、组、是否持久化等）。
- `MethodInvokingJobDetailFactoryBean`：不需要写 Quartz Job 类，直接调用某个 Spring bean 的指定方法。
- `SchedulerFactoryBean`：在 Spring 容器中装配 Quartz `Scheduler`，注入 triggers、jobDetails、线程池、数据源（支持 JDBC JobStore 集群）。
- Trigger 用 `SimpleTriggerFactoryBean`（简单周期）或 `CronTriggerFactoryBean`（cron 表达式）。

注入关系是：JobDetail → Trigger（引用 JobDetail）→ Scheduler（聚合多个 Trigger）。Spring 还负责让 Job 实例能感知容器（`SchedulerContext`、Spring 管理的 JobFactory），从而在 Job 里注入 Spring bean。

轻量需求优先用 `@Scheduled`；需要调度信息持久化到数据库、应用重启后恢复、多节点抢占执行时再上 Quartz。

## Tuning


@Async 用 TaskExecutor，@Scheduled 用 TaskScheduler，两者相互独立，不要混用。

但是有一个问题就是 TaskScheduler 的默认实现 ThreadPoolTaskScheduler，它其实也实现了 TaskExecutor，所以在一些配置复杂的场景中，它可能会被当作 TaskExecutor 来使用。
我们要避免 @Async 底层实际使用 ThreadPoolTaskScheduler，导致出现预期之外的情况

### 异步失效

- 未使用@EnableAsync

@Async基于[AOP](/docs/CS/Framework/Spring/AOP.md)
- 函数access flag非 public
- 函数是 final 或者 static
- 当前类里其它方法内部调用

Spring相关
- 未被 Spring 管理
- @Async 方法返回值必须是 void 或者 Future

### 线程池

手动设置自定义的线程池

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [AOP](/docs/CS/Framework/Spring/AOP.md)
- [Transaction](/docs/CS/Framework/Spring/Transaction.md)
- [AOP](/docs/CS/Framework/Spring/AOP.md)
- [Transaction](/docs/CS/Framework/Spring/Transaction.md)
- [Scheduled Task](/docs/CS/SE/Scheduled_Task.md)

## References

- [Spring Framework 7.x 文档 - 任务执行与调度](https://docs.spring.io/spring-framework/reference/integration/scheduling.html)
- [浅析 Spring 中 Async 注解底层异步线程池原理｜得物技术](https://mp.weixin.qq.com/s/FySv5L0bCdrlb5MoSfQtAA)
- [阿里云 SCA 学习站 - 执行任务和任务计划](https://sca.aliyun.com/learn/spring/integration/scheduling/)
