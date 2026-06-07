## Introduction

[Hystrix](https://github.com/Netflix/Hystrix/wiki/) 是一个库，通过添加延迟容忍和容错逻辑，帮助你控制这些分布式服务之间的交互。
Hystrix 通过隔离服务之间的访问点、阻止级联故障以及提供回退选项来实现这一点，所有这些都能提高系统的整体弹性。


使用 RxJava。


## Command

```java
public class CommandActions {

    private final CommandAction commandAction;
    private final CommandAction fallbackAction;

    public CommandActions(Builder builder) {
        this.commandAction = builder.commandAction;
        this.fallbackAction = builder.fallbackAction;
    }
}
```


```java
abstract class AbstractCommand<R> implements HystrixInvokableInfo<R>, HystrixObservable<R> {
  protected final HystrixCircuitBreaker circuitBreaker;
  protected final HystrixThreadPool threadPool;
  protected final HystrixThreadPoolKey threadPoolKey;
  
}
```

### HystrixCommand

用于包装将要执行潜在有风险功能（通常意味着通过网络进行服务调用）的代码，提供容错和延迟容忍、统计和性能指标捕获、断路器和舱壁功能。
该命令本质上是一个阻塞式命令，但如果与 observe() 一起使用，则提供 Observable 外观。

```java
public abstract class HystrixCommand<R> extends AbstractCommand<R> implements HystrixExecutable<R>, HystrixInvokableInfo<R>, HystrixObservable<R> {
    
}
```

#### Setter

HystrixCommand 构造函数的参数的流式接口。
必需参数通过 'with' 工厂方法设置，可选参数通过 'and' 链式方法设置。

Example:
```java
Setter.withGroupKey(HystrixCommandGroupKey.Factory.asKey("GroupName")).andCommandKey(HystrixCommandKey.Factory.asKey("CommandName"));
```

```java
 final public static class Setter {

  protected final HystrixCommandGroupKey groupKey;
  protected HystrixCommandKey commandKey;
  protected HystrixThreadPoolKey threadPoolKey;
  protected HystrixCommandProperties.Setter commandPropertiesDefaults;
  protected HystrixThreadPoolProperties.Setter threadPoolPropertiesDefaults;
}
```

#### Aspect

```java
@Aspect
public class HystrixCommandAspect {
    @Pointcut("@annotation(com.netflix.hystrix.contrib.javanica.annotation.HystrixCommand)")

    public void hystrixCommandAnnotationPointcut() {
    }

    @Pointcut("@annotation(com.netflix.hystrix.contrib.javanica.annotation.HystrixCollapser)")
    public void hystrixCollapserAnnotationPointcut() {
    }

    @Around("hystrixCommandAnnotationPointcut() || hystrixCollapserAnnotationPointcut()")
    public Object methodsAnnotatedWithHystrixCommand(final ProceedingJoinPoint joinPoint) throws Throwable {
        Method method = getMethodFromTarget(joinPoint);
        if (method.isAnnotationPresent(HystrixCommand.class) && method.isAnnotationPresent(HystrixCollapser.class)) {
            throw new IllegalStateException("method cannot be annotated with HystrixCommand and HystrixCollapser " +
                    "annotations at the same time");
        }
        MetaHolderFactory metaHolderFactory = META_HOLDER_FACTORY_MAP.get(HystrixPointcutType.of(method));
        MetaHolder metaHolder = metaHolderFactory.create(joinPoint);
        HystrixInvokable invokable = HystrixCommandFactory.getInstance().create(metaHolder);
        ExecutionType executionType = metaHolder.isCollapserAnnotationPresent() ?
                metaHolder.getCollapserExecutionType() : metaHolder.getExecutionType();

        Object result;
        try {
            if (!metaHolder.isObservable()) {
                result = CommandExecutor.execute(invokable, executionType, metaHolder);
            } else {
                result = executeObservable(invokable, executionType, metaHolder);
            }
        } catch (HystrixBadRequestException e) {
            throw e.getCause();
        } catch (HystrixRuntimeException e) {
            throw hystrixRuntimeExceptionToThrowable(metaHolder, e);
        }
        return result;
    }
}
```
### Executor

根据指定的执行类型调用 HystrixExecutable 或 HystrixObservable 的必要方法：

- ExecutionType.SYNCHRONOUS -> HystrixExecutable.execute()
- ExecutionType.ASYNCHRONOUS -> HystrixExecutable.queue()
- ExecutionType.OBSERVABLE -> 取决于指定的 observable 执行模式：
    - ObservableExecutionMode.EAGER - HystrixObservable.observe(),
    - ObservableExecutionMode.LAZY - HystrixObservable.toObservable().
    
```java
public class CommandExecutor {
    
    public static Object execute(HystrixInvokable invokable, ExecutionType executionType, MetaHolder metaHolder) throws RuntimeException {
        Validate.notNull(invokable);
        Validate.notNull(metaHolder);

        switch (executionType) {
            case SYNCHRONOUS: {
                return castToExecutable(invokable, executionType).execute();
            }
            case ASYNCHRONOUS: {
                HystrixExecutable executable = castToExecutable(invokable, executionType);
                if (metaHolder.hasFallbackMethodCommand()
                        && ExecutionType.ASYNCHRONOUS == metaHolder.getFallbackExecutionType()) {
                    return new FutureDecorator(executable.queue());
                }
                return executable.queue();
            }
            case OBSERVABLE: {
                HystrixObservable observable = castToObservable(invokable);
                return ObservableExecutionMode.EAGER == metaHolder.getObservableExecutionMode() ? observable.observe() : observable.toObservable();
            }
            default:
                throw new RuntimeException("unsupported execution type: " + executionType);
        }
    }
}
```

它们最终都会调用 [toObservable](/docs/CS/Framework/Spring_Cloud/Hystrix.md?id=execute)。
```java
public ResponseType execute() {
        try {
            return queue().get();
        } catch (Throwable e) {
            if (e instanceof HystrixRuntimeException) {
                throw (HystrixRuntimeException) e;
            }
            // if we have an exception we know about we'll throw it directly without the threading wrapper exception
            if (e.getCause() instanceof HystrixRuntimeException) {
                throw (HystrixRuntimeException) e.getCause();
            }
            // we don't know what kind of exception this is so create a generic message and throw a new HystrixRuntimeException
            String message = getClass().getSimpleName() + " HystrixCollapser failed while executing.";
            logger.debug(message, e); // debug only since we're throwing the exception and someone higher will do something with it
            //TODO should this be made a HystrixRuntimeException?
            throw new RuntimeException(message, e);
        }
    }

public Future<ResponseType> queue() {
        return toObservable()
        .toBlocking()
        .toFuture();
        }
```

## execute

```java
abstract class AbstractCommand<R> implements HystrixInvokableInfo<R>, HystrixObservable<R> {
  
  public Observable<R> toObservable() {
    final Func0<Observable<R>> applyHystrixSemantics = new Func0<Observable<R>>() {
      @Override
      public Observable<R> call() {
        if (commandState.get().equals(CommandState.UNSUBSCRIBED)) {
          return Observable.never();
        }
        return applyHystrixSemantics(_cmd);
      }
    };
  }

  private Observable<R> applyHystrixSemantics(final AbstractCommand<R> _cmd) {
    // mark that we're starting execution on the ExecutionHook
    // if this hook throws an exception, then a fast-fail occurs with no fallback.  No state is left inconsistent
    executionHook.onStart(_cmd);

    /* determine if we're allowed to execute */
    if (circuitBreaker.allowRequest()) {
      final TryableSemaphore executionSemaphore = getExecutionSemaphore();
      final AtomicBoolean semaphoreHasBeenReleased = new AtomicBoolean(false);
      final Action0 singleSemaphoreRelease = new Action0() {
        @Override
        public void call() {
          if (semaphoreHasBeenReleased.compareAndSet(false, true)) {
            executionSemaphore.release();
          }
        }
      };

      final Action1<Throwable> markExceptionThrown = new Action1<Throwable>() {
        @Override
        public void call(Throwable t) {
          eventNotifier.markEvent(HystrixEventType.EXCEPTION_THROWN, commandKey);
        }
      };

      if (executionSemaphore.tryAcquire()) {
        try {
          /* used to track userThreadExecutionTime */
          executionResult = executionResult.setInvocationStartTime(System.currentTimeMillis());
          return executeCommandAndObserve(_cmd)
                  .doOnError(markExceptionThrown)
                  .doOnTerminate(singleSemaphoreRelease)
                  .doOnUnsubscribe(singleSemaphoreRelease);
        } catch (RuntimeException e) {
          return Observable.error(e);
        }
      } else {
        return handleSemaphoreRejectionViaFallback();
      }
    } else {
      return handleShortCircuitViaFallback();
    }
  }
}
```

### getExecution


Bulkhead Pattern

```properties
execution.isolation.strategy=Semaphore
```


默认使用 TryableSemaphoreNoOp，在 Hystrix 中使用线程，否则在调用线程中执行。

`execution.isolation.strategy`设置为THREAD时，command中的代码会放到线程池里执行，跟发起command调用的线程隔离开

> execution.isolation.strategy
>
> This property indicates which isolation strategy HystrixCommand.run() executes with, one of the following two choices:
>
> THREAD — it executes on a separate thread and concurrent requests are limited by the number of threads in the thread-pool SEMAPHORE — it executes on the calling thread and concurrent requests are limited by the semaphore count



优先采用HystrixThreadPoolKey来标识线程池，如果没有配置HystrixThreadPoolKey那么就使用HystrixCommandGroupKey来标识。command跟线程池的对应关系，就看HystrixCommandKey、HystrixThreadPoolKey、HystrixCommandGroupKey这三个参数的配置
```java
private static HystrixThreadPoolKey initThreadPoolKey(HystrixThreadPoolKey threadPoolKey, HystrixCommandGroupKey groupKey, String threadPoolKeyOverride) {
    if (threadPoolKeyOverride == null) {
        // we don't have a property overriding the value so use either HystrixThreadPoolKey or HystrixCommandGroup
        if (threadPoolKey == null) {
            /* use HystrixCommandGroup if HystrixThreadPoolKey is null */
            return HystrixThreadPoolKey.Factory.asKey(groupKey.name());
        } else {
            return threadPoolKey;
        }
    } else {
        // we have a property defining the thread-pool so use it instead
        return HystrixThreadPoolKey.Factory.asKey(threadPoolKeyOverride);
    }
}
```
Hystrix会保证同一个线程池标识只会创建一个线程池：

```java
    /* package */static HystrixThreadPool getInstance(HystrixThreadPoolKey threadPoolKey, HystrixThreadPoolProperties.Setter propertiesBuilder) {
        // get the key to use instead of using the object itself so that if people forget to implement equals/hashcode things will still work
        String key = threadPoolKey.name();

        // this should find it for all but the first time
        HystrixThreadPool previouslyCached = threadPools.get(key);
        if (previouslyCached != null) {
            return previouslyCached;
        }

        // if we get here this is the first time so we need to initialize
        synchronized (HystrixThreadPool.class) {
            if (!threadPools.containsKey(key)) {
                threadPools.put(key, new HystrixThreadPoolDefault(threadPoolKey, propertiesBuilder));
            }
        }
        return threadPools.get(key);
    }    /* package */static HystrixThreadPool getInstance(HystrixThreadPoolKey threadPoolKey, HystrixThreadPoolProperties.Setter propertiesBuilder) {
        // get the key to use instead of using the object itself so that if people forget to implement equals/hashcode things will still work
        String key = threadPoolKey.name();

        // this should find it for all but the first time
        HystrixThreadPool previouslyCached = threadPools.get(key);
        if (previouslyCached != null) {
            return previouslyCached;
        }

        // if we get here this is the first time so we need to initialize
        synchronized (HystrixThreadPool.class) {
            if (!threadPools.containsKey(key)) {
                threadPools.put(key, new HystrixThreadPoolDefault(threadPoolKey, propertiesBuilder));
            }
        }
        return threadPools.get(key);
    }
```
jdk在队列满了之后会创建线程执行新任务直到线程数量达到maximumPoolSize，而hystrix在队列满了之后直接拒绝新任务，maximumSize这项配置成了摆设。

原因就在于hystrix判断队列是否满是否要拒绝新任务，没有通过jdk线程池在判断，而是自己判断的

```java
public boolean isQueueSpaceAvailable() {
    if (queueSize <= 0) {
        // we don't have a queue so we won't look for space but instead
        // let the thread-pool reject or not
        return true;
    } else {
        return threadPool.getQueue().size() < properties.queueSizeRejectionThreshold().get();
    }
}

public Subscription schedule(Action0 action, long delayTime, TimeUnit unit) {
    if (threadPool != null) {
        if (!threadPool.isQueueSpaceAvailable()) {
            throw new RejectedExecutionException("Rejected command because thread-pool queueSize is at rejection threshold.");
        }
    }
    return worker.schedule(new HystrixContexSchedulerAction(concurrencyStrategy, action), delayTime, unit);
}
```



#### HystrixThreadPool

```java
public abstract class HystrixThreadPoolProperties {

  /* defaults */
  static int default_coreSize = 10;            // core size of thread pool
  static int default_maximumSize = 10;         // maximum size of thread pool
  static int default_keepAliveTimeMinutes = 1; // minutes to keep a thread alive
  static int default_maxQueueSize = -1;        // size of queue (this can't be dynamically changed so we use 'queueSizeRejectionThreshold' to artificially limit and reject)
  // -1 turns it off and makes us use SynchronousQueue
  static boolean default_allow_maximum_size_to_diverge_from_core_size = false; //should the maximumSize config value get read and used in configuring the threadPool
  //turning this on should be a conscious decision by the user, so we default it to false

  static int default_queueSizeRejectionThreshold = 5; // number of items in queue
  static int default_threadPoolRollingNumberStatisticalWindow = 10000; // milliseconds for rolling number
  static int default_threadPoolRollingNumberStatisticalWindowBuckets = 10; // number of buckets in rolling number (10 1-second buckets)
}
```

- 如果 maxQueueSize > 0 且 coreSize < maximumSize，则 poolSize 永远不会增加到 maximumSize 并拒绝新任务。最大值为 coreSize + maxQueueSize。
- 如果 maxQueueSize <= 0 且 coreSize < maximumSize，则 poolSize 会增加到 maximumSize 然后拒绝新任务。最大值为 maximumSize。




```java
 private class HystrixContextSchedulerWorker extends Worker {

  private final Worker worker;

  @Override
  public Subscription schedule(Action0 action, long delayTime, TimeUnit unit) {
    if (threadPool != null) {
      if (!threadPool.isQueueSpaceAvailable()) {
        throw new RejectedExecutionException("Rejected command because thread-pool queueSize is at rejection threshold.");
      }
    }
    return worker.schedule(new HystrixContexSchedulerAction(concurrencyStrategy, action), delayTime, unit);
  }
}
```

根据 queueSizeRejectionThreshold 设置判断线程池队列是否有可用空间。
请注意，queueSize 是 HystrixThreadPoolDefault 上的 final 实例变量，不会动态查找。
数据结构是静态的，所以这并不适合作为动态查找。
queueSizeRejectionThreshold 可以是动态的（最大为 queueSize），因此每次调用时仍应检查它。

如果使用 SynchronousQueue 实现（maxQueueSize <= 0），它始终返回 0 作为大小，因此这里始终返回 true。

```java
static class HystrixThreadPoolDefault implements HystrixThreadPool {
  @Override
  public boolean isQueueSpaceAvailable() {
    if (queueSize <= 0) {
      // we don't have a queue so we won't look for space but instead
      // let the thread-pool reject or not
      return true;
    } else {
      return threadPool.getQueue().size() < properties.queueSizeRejectionThreshold().get();
    }
  }
}
```

#### Semaphore

仅支持 tryAcquire 且永不阻塞的信号量，支持动态许可计数。

使用 [AtomicInteger](/docs/CS/Java/JDK/Concurrency/Atomic.md) 递增/递减，而不是 [java.util.concurrent.Semaphore](/docs/CS/Java/JDK/Concurrency/Semaphore.md)，因为我们不需要阻塞，并且需要自定义实现来获取动态许可计数。
由于 AtomicInteger 在不需要实际 Semaphore 类的更复杂实现（使用 [AbstractQueueSynchronizer](/docs/CS/Java/JDK/Concurrency/AQS.md)）的情况下，可以实现相同的行为和性能。

```java
static class TryableSemaphoreActual implements TryableSemaphore {
  protected final HystrixProperty<Integer> numberOfPermits;
  private final AtomicInteger count = new AtomicInteger(0);

  public TryableSemaphoreActual(HystrixProperty<Integer> numberOfPermits) {
    this.numberOfPermits = numberOfPermits;
  }

  @Override
  public boolean tryAcquire() {
    int currentCount = count.incrementAndGet();
    if (currentCount > numberOfPermits.get()) {
      count.decrementAndGet();
      return false;
    } else {
      return true;
    }
  }

  @Override
  public void release() {
    count.decrementAndGet();
  }

  @Override
  public int getNumberOfPermitsUsed() {
    return count.get();
  }
}
```


### Circuit Breaker

挂钩到 HystrixCommand 执行的断路器逻辑，如果失败次数超过定义的阈值，将停止允许执行。
然后，它会在定义的 sleepWindow 之后允许单次重试，直到执行成功，此时它将再次关闭电路并允许执行。

```java
public interface HystrixCircuitBreaker {

  public boolean allowRequest();

  public boolean isOpen();

  /* package */void markSuccess();
}
```


#### allowRequest


```java
static class HystrixCircuitBreakerImpl implements HystrixCircuitBreaker {
  @Override
  public boolean allowRequest() {
    if (properties.circuitBreakerForceOpen().get()) {
      // properties have asked us to force the circuit open so we will allow NO requests
      return false;
    }
    if (properties.circuitBreakerForceClosed().get()) {
      // we still want to allow isOpen() to perform it's calculations so we simulate normal behavior
      isOpen();
      // properties have asked us to ignore errors so we will ignore the results of isOpen and just allow all traffic through
      return true;
    }
    return !isOpen() || allowSingleTest();
  }

  public boolean allowSingleTest() {
    long timeCircuitOpenedOrWasLastTested = circuitOpenedOrLastTestedTime.get();
    // 1) if the circuit is open
    // 2) and it's been longer than 'sleepWindow' since we opened the circuit
    if (circuitOpen.get() && System.currentTimeMillis() > timeCircuitOpenedOrWasLastTested + properties.circuitBreakerSleepWindowInMilliseconds().get()) {
      // We push the 'circuitOpenedTime' ahead by 'sleepWindow' since we have allowed one request to try.
      // If it succeeds the circuit will be closed, otherwise another singleTest will be allowed at the end of the 'sleepWindow'.
      if (circuitOpenedOrLastTestedTime.compareAndSet(timeCircuitOpenedOrWasLastTested, System.currentTimeMillis())) {
        // if this returns true that means we set the time so we'll return true to allow the singleTest
        // if it returned false it means another thread raced us and allowed the singleTest before we did
        return true;
      }
    }
    return false;
  }

  public boolean isOpen() {
    if (circuitOpen.get()) {
      // if we're open we immediately return true and don't bother attempting to 'close' ourself as that is left to allowSingleTest and a subsequent successful test to close
      return true;
    }

    // we're closed, so let's see if errors have made us so we should trip the circuit open
    HealthCounts health = metrics.getHealthCounts();

    // check if we are past the statisticalWindowVolumeThreshold
    if (health.getTotalRequests() < properties.circuitBreakerRequestVolumeThreshold().get()) {
      // we are not past the minimum volume threshold for the statisticalWindow so we'll return false immediately and not calculate anything
      return false;
    }

    if (health.getErrorPercentage() < properties.circuitBreakerErrorThresholdPercentage().get()) {
      return false;
    } else {
      // our failure rate is too high, trip the circuit
      if (circuitOpen.compareAndSet(false, true)) {
        // if the previousValue was false then we want to set the currentTime
        circuitOpenedOrLastTestedTime.set(System.currentTimeMillis());
        return true;
      } else {
        // How could previousValue be true? If another thread was going through this code at the same time a race-condition could have
        // caused another thread to set it to true already even though we were in the process of doing the same
        // In this case, we know the circuit is open, so let the other thread set the currentTime and report back that the circuit is open
        return true;
      }
    }
  }
}
```


#### markSuccess

```java
static class HystrixCircuitBreakerImpl implements HystrixCircuitBreaker {
  
  public void markSuccess() {
    if (circuitOpen.get()) {
      if (circuitOpen.compareAndSet(true, false)) {
        //win the thread race to reset metrics
        //Unsubscribe from the current stream to reset the health counts stream.  This only affects the health counts view,
        //and all other metric consumers are unaffected by the reset
        metrics.resetStream();
      }
    }
  }
}
```




### executeCommand

```java
abstract class AbstractCommand<R> implements HystrixInvokableInfo<R>, HystrixObservable<R> {
  private Observable<R> executeCommandWithSpecifiedIsolation(final AbstractCommand<R> _cmd) {
    if (properties.executionIsolationStrategy().get() == ExecutionIsolationStrategy.THREAD) {
      // mark that we are executing in a thread (even if we end up being rejected we still were a THREAD execution and not SEMAPHORE)
      return Observable.defer(new Func0<Observable<R>>() {
        @Override
        public Observable<R> call() {
          executionResult = executionResult.setExecutionOccurred();
          if (!commandState.compareAndSet(CommandState.OBSERVABLE_CHAIN_CREATED, CommandState.USER_CODE_EXECUTED)) {
            return Observable.error(new IllegalStateException("execution attempted while in state : " + commandState.get().name()));
          }

          metrics.markCommandStart(commandKey, threadPoolKey, ExecutionIsolationStrategy.THREAD);

          if (isCommandTimedOut.get() == TimedOutStatus.TIMED_OUT) {
            // the command timed out in the wrapping thread so we will return immediately
            // and not increment any of the counters below or other such logic
            return Observable.error(new RuntimeException("timed out before executing run()"));
          }
          if (threadState.compareAndSet(ThreadState.NOT_USING_THREAD, ThreadState.STARTED)) {
            //we have not been unsubscribed, so should proceed
            HystrixCounters.incrementGlobalConcurrentThreads();
            threadPool.markThreadExecution();
            // store the command that is being run
            endCurrentThreadExecutingCommand = Hystrix.startCurrentThreadExecutingCommand(getCommandKey());
            executionResult = executionResult.setExecutedInThread();
            /**
             * If any of these hooks throw an exception, then it appears as if the actual execution threw an error
             */
            try {
              executionHook.onThreadStart(_cmd);
              executionHook.onRunStart(_cmd);
              executionHook.onExecutionStart(_cmd);
              return getUserExecutionObservable(_cmd);
            } catch (Throwable ex) {
              return Observable.error(ex);
            }
          } else {
            //command has already been unsubscribed, so return immediately
            return Observable.error(new RuntimeException("unsubscribed before executing run()"));
          }
        }
      }).doOnTerminate(new Action0() {
        @Override
        public void call() {
          if (threadState.compareAndSet(ThreadState.STARTED, ThreadState.TERMINAL)) {
            handleThreadEnd(_cmd);
          }
          if (threadState.compareAndSet(ThreadState.NOT_USING_THREAD, ThreadState.TERMINAL)) {
            //if it was never started and received terminal, then no need to clean up (I don't think this is possible)
          }
          //if it was unsubscribed, then other cleanup handled it
        }
      }).doOnUnsubscribe(new Action0() {
        @Override
        public void call() {
          if (threadState.compareAndSet(ThreadState.STARTED, ThreadState.UNSUBSCRIBED)) {
            handleThreadEnd(_cmd);
          }
          if (threadState.compareAndSet(ThreadState.NOT_USING_THREAD, ThreadState.UNSUBSCRIBED)) {
            //if it was never started and was cancelled, then no need to clean up
          }
          //if it was terminal, then other cleanup handled it
        }
      }).subscribeOn(threadPool.getScheduler(new Func0<Boolean>() {
        @Override
        public Boolean call() {
          return properties.executionIsolationThreadInterruptOnTimeout().get() && _cmd.isCommandTimedOut.get() == TimedOutStatus.TIMED_OUT;
        }
      }));
    } else {
      return Observable.defer(new Func0<Observable<R>>() {
        @Override
        public Observable<R> call() {
          executionResult = executionResult.setExecutionOccurred();
          if (!commandState.compareAndSet(CommandState.OBSERVABLE_CHAIN_CREATED, CommandState.USER_CODE_EXECUTED)) {
            return Observable.error(new IllegalStateException("execution attempted while in state : " + commandState.get().name()));
          }

          metrics.markCommandStart(commandKey, threadPoolKey, ExecutionIsolationStrategy.SEMAPHORE);
          // semaphore isolated
          // store the command that is being run
          endCurrentThreadExecutingCommand = Hystrix.startCurrentThreadExecutingCommand(getCommandKey());
          try {
            executionHook.onRunStart(_cmd);
            executionHook.onExecutionStart(_cmd);
            return getUserExecutionObservable(_cmd);  //the getUserExecutionObservable method already wraps sync exceptions, so this shouldn't throw
          } catch (Throwable ex) {
            //If the above hooks throw, then use that as the result of the run method
            return Observable.error(ex);
          }
        }
      });
    }
  }
}
```


## Summary

|               | Sentinel                                       | Hystrix                       |
| -------------- | ---------------------------------------------- | ----------------------------- |
| 隔离策略       | 信号量隔离                                     | 线程池隔离/信号量隔离         |
| 熔断降级策略   | 基于响应时间或失败比率                         | 基于失败比率                  |
| 实时指标实现   | 滑动窗口                                       | 滑动窗口（基于 RxJava）       |
| 规则配置       | 支持多种数据源                                 | 支持多种数据源                |
| 扩展性         | 多个扩展点                                     | 插件的形式                    |
| 基于注解的支持 | 支持                                           | 支持                          |
| 限流           | 基于 QPS，支持基于调用关系的限流               | 不支持                        |
| 流量整形       | 支持慢启动、匀速器模式                         | 不支持                        |
| 系统负载保护   | 支持                                           | 不支持                        |
| 控制台         | 开箱即用，可配置规则、查看秒级监控、机器发现等 | 不完善                        |
| 常见框架的适配 | Servlet、Spring Cloud、Dubbo、gRPC             | Servlet、Spring Cloud Netflix |


## Links

- [Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md?id=circuit-breaker)
