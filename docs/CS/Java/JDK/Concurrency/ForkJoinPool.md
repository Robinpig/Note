
## Introduction



An ExecutorService for running ForkJoinTasks. A ForkJoinPool provides the entry point for submissions from non-ForkJoinTask clients, as well as management and monitoring operations.
A ForkJoinPool differs from other kinds of ExecutorService mainly by virtue of employing work-stealing: all threads in the pool attempt to find and execute tasks submitted to the pool and/or created by other active tasks (eventually blocking waiting for work if none exist). This enables efficient processing when most tasks spawn other subtasks (as do most ForkJoinTasks), as well as when many small tasks are submitted to the pool from external clients. Especially when setting asyncMode to true in constructors, ForkJoinPools may also be appropriate for use with event-style tasks that are never joined. All worker threads are initialized with Thread.isDaemon set true.
A static commonPool() is available and appropriate for most applications. The common pool is used by any ForkJoinTask that is not explicitly submitted to a specified pool. Using the common pool normally reduces resource usage (its threads are slowly reclaimed during periods of non-use, and reinstated upon subsequent use).
For applications that require separate or custom pools, a ForkJoinPool may be constructed with a given target parallelism level; by default, equal to the number of available processors. The pool attempts to maintain enough active (or available) threads by dynamically adding, suspending, or resuming internal worker threads, even if some tasks are stalled waiting to join others. However, no such adjustments are guaranteed in the face of blocked I/O or other unmanaged synchronization. The nested ForkJoinPool.ManagedBlocker interface enables extension of the kinds of synchronization accommodated. The default policies may be overridden using a constructor with parameters corresponding to those documented in class ThreadPoolExecutor.
In addition to execution and lifecycle control methods, this class provides status check methods (for example getStealCount) that are intended to aid in developing, tuning, and monitoring fork/join applications. Also, method toString returns indications of pool state in a convenient form for informal monitoring.
As is the case with other ExecutorServices, there are three main task execution methods summarized in the following table. These are designed to be used primarily by clients not already engaged in fork/join computations in the current pool. The main forms of these methods accept instances of ForkJoinTask, but overloaded forms also allow mixed execution of plain Runnable- or Callable- based activities as well. However, tasks that are already executing in a pool should normally instead use the within-computation forms listed in the table unless using async event-style tasks that are not usually joined, in which case there is little difference among choice of methods.
Summary of task execution methods

|  | Call from non-fork/join clients | Call from within fork/join computations |
| --- | --- | --- |
| Arrange async execution | execute(ForkJoinTask) | ForkJoinTask.fork |
| Await and obtain result | invoke(ForkJoinTask) | ForkJoinTask.invoke |
| Arrange exec and obtain Future | submit(ForkJoinTask) | ForkJoinTask.fork (ForkJoinTasks are Futures) |


The parameters used to construct the common pool may be controlled by setting the following system properties:
1. java.util.concurrent.ForkJoinPool.common.parallelism - the parallelism level, a non-negative integer
2. java.util.concurrent.ForkJoinPool.common.threadFactory - the class name of a ForkJoinPool.ForkJoinWorkerThreadFactory. The system class loader is used to load this class.
3. java.util.concurrent.ForkJoinPool.common.exceptionHandler - the class name of a Thread.UncaughtExceptionHandler. The system class loader is used to load this class.
4. java.util.concurrent.ForkJoinPool.common.maximumSpares - the maximum number of allowed extra threads to maintain target parallelism (default 256).

If no thread factory is supplied via a system property, then the common pool uses a factory that uses the system class loader as the thread context class loader. In addition, if a SecurityManager is present, then the common pool uses a factory supplying threads that have no Permissions enabled. Upon any error in establishing these settings, default parameters are used. It is possible to disable or limit the use of threads in the common pool by setting the parallelism property to zero, and/or using a factory that may return null. However doing so may cause unjoined tasks to never be executed.

**Implementation notes**: This implementation restricts the maximum number of running threads to 32767. Attempts to create pools with greater than the maximum number result in IllegalArgumentException.
This implementation rejects submitted tasks (that is, by throwing RejectedExecutionException) only when the pool is shut down or internal resources have been exhausted.



### commonPool

Returns the common pool instance. This pool is statically constructed; its run state is unaffected by attempts to shutdown or shutdownNow. However this pool and any ongoing processing are automatically terminated upon program System.exit. Any program that relies on asynchronous task processing to complete before program termination should invoke commonPool().awaitQuiescence, before exit.

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

init commonPool in static
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