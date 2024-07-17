## Introduction

名字里带有Acceptor的线程负责接收浏览器的连接请求。
名字里带有Poller的线程，其实内部是个Selector，负责侦测IO事件。
精选留言 (13)  写留言名字里带有Catalina-exec的是工作线程，负责处理请求。
名字里带有 Catalina-utility的是Tomcat中的工具线程，主要是干杂活，比如在后台定期检查
Session是否过期、定期检查Web应用是否更新（热部署热加载）、检查异步Servlet的连接是否
过期等等。

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


与JDK ThreadPoolExecutor不同的是 在抛出RejectedExecutionException后会再次尝试任务入队

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

继承自无界队列LinkedBlockingQueue的TaskQueue需要自己维护offer的处理
因为默认线程池使用无界队列是无法创建非核心线程的

当前线程数大于核心线程数、小于最大线程数，并且已提交的任务个数大于当前线程数
时，也就是说线程不够用了，但是线程数又没达到极限，会去创建新的线程 这样能做到eager thread pool 尽快创建非核心线程

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
        //提交任务数小于当前线程数 入队 此时线程数还未到最大
        if (parent.getSubmittedCount()<=(parent.getPoolSize())) {
            return super.offer(o);
        }
        //提交任务数大于当前线程数 当前线程数小于最大线程数 允许创建新线程
        if (parent.getPoolSize()<parent.getMaximumPoolSize()) {
            return false;
        }
        //if we reached here, we need to add it to the queue
        return super.offer(o);
    }

    @Override
    public int remainingCapacity() {
        if (forcedRemainingCapacity != null) {
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

- [Tomcat](/docs/CS/Framework/Tomcat/Tomcat.md)
