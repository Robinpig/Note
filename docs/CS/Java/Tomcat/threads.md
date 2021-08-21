## Introduction


### StandardThreadExecutor
```java
// StandardThreadExecutor

// max number of threads
protected int maxThreads = 200;

// min number of threads
protected int minSpareThreads = 25;

// idle time in milliseconds 60s
protected int maxIdleTime = 60000;

// The maximum number of elements that can queue up before we reject them
protected int maxQueueSize = Integer.MAX_VALUE;
```


```java
// StandardThreadExecutor


/**
 * Start the component and implement the requirements
 * of {@link org.apache.catalina.util.LifecycleBase#startInternal()}.
 */
@Override
protected void startInternal() throws LifecycleException {

    taskqueue = new TaskQueue(maxQueueSize);
    TaskThreadFactory tf = new TaskThreadFactory(namePrefix,daemon,getThreadPriority());
    executor = new ThreadPoolExecutor(getMinSpareThreads(), getMaxThreads(), maxIdleTime, TimeUnit.MILLISECONDS,taskqueue, tf);
    executor.setThreadRenewalDelay(threadRenewalDelay);
    if (prestartminSpareThreads) {
        executor.prestartAllCoreThreads();
    }
    taskqueue.setParent(executor);

    setState(LifecycleState.STARTING);
}
```

### ThreadPoolExecutor

`org.apache.tomcat.util.threads.ThreadPoolExecutor`

Same as a java.util.concurrent.ThreadPoolExecutor but implements a much more efficient getSubmittedCount() method, to be used to properly handle the work queue. If a RejectedExecutionHandler is not specified a default one will be configured and that one will always throw a RejectedExecutionException

```java
// org.apache.tomcat.util.threads.ThreadPoolExecutor
    /**
     * The number of tasks submitted but not yet finished. This includes tasks
     * in the queue and tasks that have been handed to a worker thread but the
     * latter did not start executing the task yet.
     * This number is always greater or equal to {@link #getActiveCount()}.
     */
    private final AtomicInteger submittedCount = new AtomicInteger(0);
```

createExecutor by Endpoint