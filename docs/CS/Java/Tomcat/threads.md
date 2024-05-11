## Introduction


## StandardThreadExecutor

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

[prestart All CoreThreads](/docs/CS/Java/JDK/Concurrency/ThreadPoolExecutor.md?id=prestartCoreThread)

```properties
server.tomcat.max-threads=xx
```

```java
// StandardThreadExecutor
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

## ThreadPoolExecutor

`org.apache.tomcat.util.threads.ThreadPoolExecutor`

Same as a java.util.concurrent.ThreadPoolExecutor but implements a much more efficient getSubmittedCount() method, to be used to properly handle the work queue. 
If a RejectedExecutionHandler is not specified a default one will be configured and that one will always throw a RejectedExecutionException

### getSubmittedCount

The number of tasks submitted but not yet finished. 
This includes tasks in the queue and tasks that have been handed to a worker thread but the latter did not start executing the task yet. 
This number is always greater or equal to getActiveCount().

```java
    // org.apache.tomcat.util.threads.ThreadPoolExecutor
    private final AtomicInteger submittedCount = new AtomicInteger(0);
```

createExecutor by Endpoint

### execute

Executes the given command at some time in the future. 
The command may execute in a new thread, in a pooled thread, or in the calling thread, at the discretion of the Executor implementation. 
- If no threads are available, it will be added to the work queue. 
- **If the work queue is full, the system will wait for the specified time and it throw a RejectedExecutionException if the queue is still full after that.**

```java
public class ThreadPoolExecutor extends java.util.concurrent.ThreadPoolExecutor {
    public void execute(Runnable command, long timeout, TimeUnit unit) {
        submittedCount.incrementAndGet();
        try {
            super.execute(command);
        } catch (RejectedExecutionException rx) {
            if (super.getQueue() instanceof TaskQueue) {
                final TaskQueue queue = (TaskQueue) super.getQueue();
                try {
                    if (!queue.force(command, timeout, unit)) {
                        submittedCount.decrementAndGet();
                        throw new RejectedExecutionException(sm.getString("threadPoolExecutor.queueFull"));
                    }
                } catch (InterruptedException x) {
                    submittedCount.decrementAndGet();
                    throw new RejectedExecutionException(x);
                }
            } else {
                submittedCount.decrementAndGet();
                throw rx;
            }

        }
    }
} 
```

### TaskQueue

As task queue specifically designed to run with a thread pool executor. 
The task queue is optimised to properly utilize threads within a thread pool executor. 
If you use a normal queue, the executor will spawn threads when there are idle threads and you wont be able to force items onto the queue itself.

**If we have less threads than maximum force creation of a new thread.**

```java
public class TaskQueue extends LinkedBlockingQueue<Runnable> {
    @Override
    public boolean offer(Runnable o) {
        //we can't do any checks
        if (parent==null) {
            return super.offer(o);
        }
        //we are maxed out on threads, simply queue the object
        if (parent.getPoolSize() == parent.getMaximumPoolSize()) {
            return super.offer(o);
        }
        //we have idle threads, just add it to the queue
        if (parent.getSubmittedCount()<=(parent.getPoolSize())) {
            return super.offer(o);
        }
        //if we have less threads than maximum force creation of a new thread
        if (parent.getPoolSize()<parent.getMaximumPoolSize()) {
            return false;
        }
        //if we reached here, we need to add it to the queue
        return super.offer(o);
    }

    @Override
    public int remainingCapacity() {
        if (forcedRemainingCapacity != null) {
            // ThreadPoolExecutor.setCorePoolSize checks that
            // remainingCapacity==0 to allow to interrupt idle threads
            // I don't see why, but this hack allows to conform to this
            // "requirement"
            return forcedRemainingCapacity.intValue();
        }
        return super.remainingCapacity();
    }

    public boolean force(Runnable o, long timeout, TimeUnit unit) throws InterruptedException {
        if (parent == null || parent.isShutdown()) throw new RejectedExecutionException(sm.getString("taskQueue.notRunning"));
        return super.offer(o,timeout,unit); //forces the item onto the queue, to be used if the task is rejected
    }
}
```

## Links

- [Tomcat](/docs/CS/Java/Tomcat/Tomcat.md)
