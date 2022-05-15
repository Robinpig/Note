## Introduction

Using RxJava.


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

Used to wrap code that will execute potentially risky functionality (typically meaning a service call over the network) with fault and latency tolerance, statistics and performance metrics capture, circuit breaker and bulkhead functionality. 
This command is essentially a blocking command but provides an Observable facade if used with observe().

```java
public abstract class HystrixCommand<R> extends AbstractCommand<R> implements HystrixExecutable<R>, HystrixInvokableInfo<R>, HystrixObservable<R> {
    
}
```

#### Setter

Fluent interface for arguments to the HystrixCommand constructor.
The required arguments are set via the 'with' factory method and optional arguments via the 'and' chained methods.

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

Invokes necessary method of HystrixExecutable or HystrixObservable for specified execution type:

- ExecutionType.SYNCHRONOUS -> HystrixExecutable.execute()
- ExecutionType.ASYNCHRONOUS -> HystrixExecutable.queue()
- ExecutionType.OBSERVABLE -> depends on specify observable execution mode: 
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

All of them call [toObservable](/docs/CS/Java/Spring_Cloud/Hystrix.md?id=execute) finally.
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


Default TryableSemaphoreNoOp using threads in Hystrix, or else in calling thread.

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


#### Semaphore

Semaphore that only supports tryAcquire and never blocks and that supports a dynamic permit count.

Using [AtomicInteger](/docs/CS/Java/JDK/Concurrency/Atomic.md) increment/decrement instead of [java.util.concurrent.Semaphore](/docs/CS/Java/JDK/Concurrency/Semaphore.md) since we don't need blocking and need a custom implementation to get the dynamic permit count and
since AtomicInteger achieves the same behavior and performance without the more complex implementation of the actual Semaphore class using [AbstractQueueSynchronizer](/docs/CS/Java/JDK/Concurrency/AQS.md).

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

Circuit-breaker logic that is hooked into HystrixCommand execution and will stop allowing executions if failures have gone past the defined threshold.
It will then allow single retries after a defined sleepWindow until the execution succeeds at which point it will again close the circuit and allow executions again.

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

- [Spring Cloud](/docs/CS/Java/Spring_Cloud/Spring_Cloud.md?id=circuit-breaker)