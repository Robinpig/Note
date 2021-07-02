
## Introduction



An ExecutorService for running ForkJoinTasks. A ForkJoinPool provides the entry point for submissions from non-ForkJoinTask clients, as well as management and monitoring operations.
A ForkJoinPool differs from other kinds of ExecutorService mainly by virtue of employing work-stealing: all threads in the pool attempt to find and execute tasks submitted to the pool and/or created by other active tasks (eventually blocking waiting for work if none exist). This enables efficient processing when most tasks spawn other subtasks (as do most ForkJoinTasks), as well as when many small tasks are submitted to the pool from external clients. Especially when setting asyncMode to true in constructors, ForkJoinPools may also be appropriate for use with event-style tasks that are never joined. All worker threads are initialized with Thread.isDaemon set true.
A static commonPool() is available and appropriate for most applications. The common pool is used by any ForkJoinTask that is not explicitly submitted to a specified pool. Using the common pool normally reduces resource usage (its threads are slowly reclaimed during periods of non-use, and reinstated upon subsequent use).
For applications that require separate or custom pools, a ForkJoinPool may be constructed with a given target parallelism level; by default, equal to the number of available processors. The pool attempts to maintain enough active (or available) threads by dynamically adding, suspending, or resuming internal worker threads, even if some tasks are stalled waiting to join others. However, no such adjustments are guaranteed in the face of blocked I/O or other unmanaged synchronization. The nested ForkJoinPool.ManagedBlocker interface enables extension of the kinds of synchronization accommodated. The default policies may be overridden using a constructor with parameters corresponding to those documented in class ThreadPoolExecutor.
In addition to execution and lifecycle control methods, this class provides status check methods (for example getStealCount) that are intended to aid in developing, tuning, and monitoring fork/join applications. Also, method toString returns indications of pool state in a convenient form for informal monitoring.
As is the case with other ExecutorServices, there are three main task execution methods summarized in the following table. These are designed to be used primarily by clients not already engaged in fork/join computations in the current pool. The main forms of these methods accept instances of ForkJoinTask, but overloaded forms also allow mixed execution of plain Runnable- or Callable- based activities as well. However, tasks that are already executing in a pool should normally instead use the within-computation forms listed in the table unless using async event-style tasks that are not usually joined, in which case there is little difference among choice of methods.
Summary of task execution methods

Call from non-fork/join clients
Call from within fork/join computations
Arrange async execution
execute(ForkJoinTask)
ForkJoinTask.fork
Await and obtain result
invoke(ForkJoinTask)
ForkJoinTask.invoke
Arrange exec and obtain Future
submit(ForkJoinTask)
ForkJoinTask.fork (ForkJoinTasks are Futures)
The parameters used to construct the common pool may be controlled by setting the following system properties:
java.util.concurrent.ForkJoinPool.common.parallelism - the parallelism level, a non-negative integer
java.util.concurrent.ForkJoinPool.common.threadFactory - the class name of a ForkJoinPool.ForkJoinWorkerThreadFactory. The system class loader is used to load this class.
java.util.concurrent.ForkJoinPool.common.exceptionHandler - the class name of a Thread.UncaughtExceptionHandler. The system class loader is used to load this class.
java.util.concurrent.ForkJoinPool.common.maximumSpares - the maximum number of allowed extra threads to maintain target parallelism (default 256).
If no thread factory is supplied via a system property, then the common pool uses a factory that uses the system class loader as the thread context class loader. In addition, if a SecurityManager is present, then the common pool uses a factory supplying threads that have no Permissions enabled. Upon any error in establishing these settings, default parameters are used. It is possible to disable or limit the use of threads in the common pool by setting the parallelism property to zero, and/or using a factory that may return null. However doing so may cause unjoined tasks to never be executed.
Implementation notes: This implementation restricts the maximum number of running threads to 32767. Attempts to create pools with greater than the maximum number result in IllegalArgumentException.
This implementation rejects submitted tasks (that is, by throwing RejectedExecutionException) only when the pool is shut down or internal resources have been exhausted.
Since:
1.7
