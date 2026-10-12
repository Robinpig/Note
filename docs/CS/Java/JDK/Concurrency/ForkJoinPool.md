
## Introduction



用于运行 ForkJoinTask 的 ExecutorService。
ForkJoinPool 提供了来自非 ForkJoinTask 客户端的提交入口，以及管理与监控操作。

ForkJoinPool 与其他类型的 ExecutorService 的主要区别在于采用了工作窃取（work-stealing）：
池中所有线程都会尝试查找并执行提交到池中的任务，以及/或由其他活跃任务创建的任务（若暂时没有任务，则最终会阻塞等待工作）。
当大多数任务会派生出其他子任务（大多数 ForkJoinTask 都是如此），以及当外部客户端向池中提交大量小任务时，这种方式能够实现高效处理。
尤其当构造时将 asyncMode 设为 true 时，ForkJoinPool 也适合用于那些从不 join 的事件式任务。所有工作线程在初始化时都将 Thread.isDaemon 设为 true。

静态方法 commonPool() 可用且适用于大多数应用。任何未显式提交到指定池的 ForkJoinTask 都会使用公共池。
使用公共池通常能减少资源占用（其线程在非使用期间会被缓慢回收，并在后续使用时重新启用）。

对于需要独立或自定义池的应用，可以通过给定的目标并行度（parallelism）级别来构造 ForkJoinPool；默认情况下该级别等于可用处理器的数量。
即使某些任务因等待 join 其他任务而停滞，池也会通过动态添加、挂起或恢复内部工作线程，尽量维持足够数量的活跃（或可用）线程。
然而，在面对阻塞 I/O 或其他不受管理的同步时，无法保证一定能够进行此类调整。

嵌套接口 ForkJoinPool.ManagedBlocker 可用于扩展所支持的同步种类。
默认策略可以通过带有参数的构造器来覆盖，这些参数对应于 ThreadPoolExecutor 类文档中描述的那些。
除了执行与生命周期控制方法外，本类还提供了一些状态检查方法（例如 getStealCount），用于辅助开发、调优和监控 fork/join 应用。

此外，toString 方法会以便于非正式监控的形式返回池状态的指示信息。
与其他 ExecutorService 一样，主要有三种任务执行方法，如下表所示。
这些方法主要面向当前并未参与本池 fork/join 计算的客户端。

这些方法的主要形式接受 ForkJoinTask 实例，但其重载形式也允许混合执行普通的基于 Runnable 或 Callable 的活动。
不过，已经在池中执行的任务通常应使用表中列出的"计算内部"形式，
除非使用的是通常不 join 的异步事件式任务，此时选择哪种方法差别不大。


任务执行方法汇总：

|  | 来自非 fork/join 客户端的调用 | 在 fork/join 计算内部的调用 |
| --- | --- | --- |
| 安排异步执行 | execute(ForkJoinTask) | ForkJoinTask.fork |
| 等待并获取结果 | invoke(ForkJoinTask) | ForkJoinTask.invoke |
| 安排执行并获取 Future | submit(ForkJoinTask) | ForkJoinTask.fork（ForkJoinTasks 即 Futures） |


构造公共池所用的参数可通过设置以下系统属性来控制：
1. java.util.concurrent.ForkJoinPool.common.parallelism —— 并行度（parallelism）级别，一个非负整数
2. java.util.concurrent.ForkJoinPool.common.threadFactory —— 一个 ForkJoinPool.ForkJoinWorkerThreadFactory 的类名，使用系统类加载器加载该类。
3. java.util.concurrent.ForkJoinPool.common.exceptionHandler —— 一个 Thread.UncaughtExceptionHandler 的类名，使用系统类加载器加载该类。
4. java.util.concurrent.ForkJoinPool.common.maximumSpares —— 为维持目标并行度所允许保留的额外线程的最大数量（默认 256）。

如果未通过系统属性提供线程工厂，公共池会使用以系统类加载器作为线程上下文类加载器的工厂。此外，若存在 SecurityManager，公共池会使用提供"无任何启用权限"线程的工厂。在建立这些设置时一旦发生任何错误，就会使用默认参数。通过将 parallelism 属性设为 0 和/或使用可能返回 null 的工厂，可以禁用或限制公共池中线程的使用；但这样做可能导致未被 join 的任务永远无法执行。

**实现说明**：本实现将最大运行线程数限制为 32767。尝试创建超过该上限的池会导致 IllegalArgumentException。
本实现仅在池被关闭或内部资源已耗尽时，才会拒绝已提交的任务（即通过抛出 RejectedExecutionException）。



## CommonPool

返回公共池实例。该池是静态构造的；其运行状态不受 shutdown 或 shutdownNow 调用的影响。不过，该池以及任何正在进行的处理都会在程序 System.exit 时自动终止。任何依赖异步任务处理在程序终止前完成的应用，都应在退出前调用 commonPool().awaitQuiescence。

```java
/**
 * Common (static) pool. Non-null for public use unless a static
 * construction exception, but internal usages null-check on use
 * to paranoically avoid potential initialization circularities
 * as well as to simplify generated code.
 */
static final ForkJoinPool common;

public static ForkJoinPool commonPool() {
        // assert common != null : "static init error";
        return common;
    }
```

在静态初始化块中初始化 commonPool
```java
static {
        try {
            MethodHandles.Lookup l = MethodHandles.lookup();
            CTL = l.findVarHandle(ForkJoinPool.class, "ctl", long.class);
            MODE = l.findVarHandle(ForkJoinPool.class, "mode", int.class);
            QA = MethodHandles.arrayElementVarHandle(ForkJoinTask[].class);
        } catch (ReflectiveOperationException e) {
            throw new ExceptionInInitializerError(e);
        }

        // Reduce the risk of rare disastrous classloading in first call to
        // LockSupport.park: https://bugs.openjdk.java.net/browse/JDK-8074773
        Class<?> ensureLoaded = LockSupport.class;

        int commonMaxSpares = DEFAULT_COMMON_MAX_SPARES;
        try {
            String p = System.getProperty
                ("java.util.concurrent.ForkJoinPool.common.maximumSpares");
            if (p != null)
                commonMaxSpares = Integer.parseInt(p);
        } catch (Exception ignore) {}
        COMMON_MAX_SPARES = commonMaxSpares;

        defaultForkJoinWorkerThreadFactory =
            new DefaultForkJoinWorkerThreadFactory();
        modifyThreadPermission = new RuntimePermission("modifyThread");

        common = AccessController.doPrivileged(new PrivilegedAction<>() {
            public ForkJoinPool run() {
                return new ForkJoinPool((byte)0); }});

        COMMON_PARALLELISM = Math.max(common.mode & SMASK, 1);
    }
```

```java
    /**
     * Constructor for common pool using parameters possibly
     * overridden by system properties
     */
    private ForkJoinPool(byte forCommonPoolOnly) {
        int parallelism = -1;
        ForkJoinWorkerThreadFactory fac = null;
        UncaughtExceptionHandler handler = null;
        try {  // ignore exceptions in accessing/parsing properties
            String pp = System.getProperty
                ("java.util.concurrent.ForkJoinPool.common.parallelism");
            if (pp != null)
                parallelism = Integer.parseInt(pp);
            fac = (ForkJoinWorkerThreadFactory) newInstanceFromSystemProperty(
                "java.util.concurrent.ForkJoinPool.common.threadFactory");
            handler = (UncaughtExceptionHandler) newInstanceFromSystemProperty(
                "java.util.concurrent.ForkJoinPool.common.exceptionHandler");
        } catch (Exception ignore) {
        }

        if (fac == null) {
            if (System.getSecurityManager() == null)
                fac = defaultForkJoinWorkerThreadFactory;
            else // use security-managed default
                fac = new InnocuousForkJoinWorkerThreadFactory();
        }
        if (parallelism < 0 && // default 1 less than #cores
            (parallelism = Runtime.getRuntime().availableProcessors() - 1) <= 0)
            parallelism = 1;
        if (parallelism > MAX_CAP)
            parallelism = MAX_CAP;

        long c = ((((long)(-parallelism) << TC_SHIFT) & TC_MASK) |
                  (((long)(-parallelism) << RC_SHIFT) & RC_MASK));
        int b = ((1 - parallelism) & SMASK) | (COMMON_MAX_SPARES << SWIDTH);
        int n = (parallelism > 1) ? parallelism - 1 : 1;
        n |= n >>> 1; n |= n >>> 2; n |= n >>> 4; n |= n >>> 8; n |= n >>> 16;
        n = (n + 1) << 1;

        this.workerNamePrefix = "ForkJoinPool.commonPool-worker-";
        this.workQueues = new WorkQueue[n];
        this.factory = fac;
        this.ueh = handler;
        this.saturate = null;
        this.keepAlive = DEFAULT_KEEPALIVE;
        this.bounds = b;
        this.mode = parallelism;
        this.ctl = c;
    }
```

## workQueue


```java
public <T> T invoke(ForkJoinTask<T> task) {
    if (task == null)
        throw new NullPointerException();
    externalSubmit(task);
    return task.join();
}
```



## fork

若适用，则安排当前任务所在池异步执行该任务；若当前并不在 ForkJoinPool 中，则使用 ForkJoinPool.commonPool() 执行。 
虽然并不强制，但多次 fork 同一个任务（除非它已完成并重新初始化）属于使用错误。 
此后对该任务状态或其操作数据的修改，未必能被执行它的线程之外的其他线程一致地观察到，
除非在此之前调用了 join 或相关方法，或者 isDone 返回了 true。

```java
public final ForkJoinTask<V> fork() {
    Thread t;
    if ((t = Thread.currentThread()) instanceof ForkJoinWorkerThread)
        ((ForkJoinWorkerThread)t).workQueue.push(this);
    else
        ForkJoinPool.common.externalPush(this);
    return this;
}
```



## join

在计算完成时返回其结果。该方法与 get() 的不同之处在于：异常完成会抛出 RuntimeException 或 Error，
而不是 ExecutionException；并且调用线程被中断时，该方法不会因抛出 InterruptedException 而突然返回。

1. 若已完成，则直接返回
2. 若不是 ForkJoinWorkerThread 实例，则调用 externalAwaitDone
3. 否则调用 awaitJoin

```java
public final V join() {
    int s;
    if (((s = doJoin()) & ABNORMAL) != 0)
        reportException(s);
    return getRawResult();
}

private int doJoin() {
  int s; Thread t; ForkJoinWorkerThread wt; ForkJoinPool.WorkQueue w;
  return (s = status) < 0 ? s :
  ((t = Thread.currentThread()) instanceof ForkJoinWorkerThread) ?
    (w = (wt = (ForkJoinWorkerThread)t).workQueue).
    tryUnpush(this) && (s = doExec()) < 0 ? s :
  wt.pool.awaitJoin(w, this, 0L) :
  externalAwaitDone();
}
```

仅当给定任务位于当前栈顶时才将其弹出。

```java
final boolean tryUnpush(ForkJoinTask<?> task) {
    boolean popped = false;
    int s, cap; ForkJoinTask<?>[] a;
    if ((a = array) != null && (cap = a.length) > 0 &&
        (s = top) != base &&
        (popped = QA.compareAndSet(a, (cap - 1) & --s, task, null)))
        TOP.setOpaque(this, s);
    return popped;
}
```



```java
final int doExec() {
    int s; boolean completed;
    if ((s = status) >= 0) {
        try {
            completed = exec();
        } catch (Throwable rex) {
            completed = false;
            s = setExceptionalCompletion(rex);
        }
        if (completed)
            s = setDone();
    }
    return s;
}
```



```java
final int awaitJoin(WorkQueue w, ForkJoinTask<?> task, long deadline) {
    int s = 0;
    int seed = ThreadLocalRandom.nextSecondarySeed();
    if (w != null && task != null &&
        (!(task instanceof CountedCompleter) ||
         (s = w.helpCC((CountedCompleter<?>)task, 0, false)) >= 0)) {
        w.tryRemoveAndExec(task);
        int src = w.source, id = w.id;
        int r = (seed >>> 16) | 1, step = (seed & ~1) | 2;
        s = task.status;
        while (s >= 0) {
            WorkQueue[] ws;
            int n = (ws = workQueues) == null ? 0 : ws.length, m = n - 1;
            while (n > 0) {
                WorkQueue q; int b;
                if ((q = ws[r & m]) != null && q.source == id &&
                    q.top != (b = q.base)) {
                    ForkJoinTask<?>[] a; int cap, k;
                    int qid = q.id;
                    if ((a = q.array) != null && (cap = a.length) > 0) {
                        ForkJoinTask<?> t = (ForkJoinTask<?>)
                            QA.getAcquire(a, k = (cap - 1) & b);
                        if (q.source == id && q.base == b++ &&
                            t != null && QA.compareAndSet(a, k, t, null)) {
                            q.base = b;
                            w.source = qid;
                            t.doExec();
                            w.source = src;
                        }
                    }
                    break;
                }
                else {
                    r += step;
                    --n;
                }
            }
            if ((s = task.status) < 0)
                break;
            else if (n == 0) { // empty scan
                long ms, ns; int block;
                if (deadline == 0L)
                    ms = 0L;                       // untimed
                else if ((ns = deadline - System.nanoTime()) <= 0L)
                    break;                         // timeout
                else if ((ms = TimeUnit.NANOSECONDS.toMillis(ns)) <= 0L)
                    ms = 1L;                       // avoid 0 for timed wait
                if ((block = tryCompensate(w)) != 0) {
                    task.internalWait(ms);
                    CTL.getAndAdd(this, (block > 0) ? RC_UNIT : 0L);
                }
                s = task.status;
            }
        }
    }
    return s;
}
```



```java
private int externalAwaitDone() {
    int s = tryExternalHelp();
    if (s >= 0 && (s = (int)STATUS.getAndBitwiseOr(this, SIGNAL)) >= 0) {
        boolean interrupted = false;
        synchronized (this) {
            for (;;) {
                if ((s = status) >= 0) {
                    try {
                        wait(0L);
                    } catch (InterruptedException ie) {
                        interrupted = true;
                    }
                }
                else {
                    notifyAll();
                    break;
                }
            }
        }
        if (interrupted)
            Thread.currentThread().interrupt();
    }
    return s;
}
```


## Links

- [AQS](/docs/CS/Java/JDK/Concurrency/AQS.md)
- [Atomic](/docs/CS/Java/JDK/Concurrency/Atomic.md)
- [Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
- [CountDownLatch](/docs/CS/Java/JDK/Concurrency/CountDownLatch.md)
- [CyclicBarrier](/docs/CS/Java/JDK/Concurrency/CyclicBarrier.md)
- [Exchanger](/docs/CS/Java/JDK/Concurrency/Exchanger.md)

## References
1. [A Java Fork/Join Framework - Doug Lea](http://gee.cs.oswego.edu/dl/papers/fj.pdf)
