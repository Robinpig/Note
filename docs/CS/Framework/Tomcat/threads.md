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

[prestart All CoreThreads](/docs/CS/Java/JDK/Concurrency/ThreadPoolExecutor.md?id=prestartcorethread)

```properties
server.tomcat.max-threads=xx
```

11.0.26 的 `startInternal` 只剩四步，旧笔记里那段 `if (prestartminSpareThreads)` 已经不存在了：

```java
// StandardThreadExecutor.java:122-131 (11.0.26)
protected void startInternal() throws LifecycleException {

    taskqueue = new TaskQueue(maxQueueSize);
    TaskThreadFactory tf = new TaskThreadFactory(namePrefix, daemon, getThreadPriority());
    executor = new ThreadPoolExecutor(getMinSpareThreads(), getMaxThreads(), maxIdleTime, TimeUnit.MILLISECONDS,
            taskqueue, tf);
    executor.setThreadRenewalDelay(threadRenewalDelay);
    taskqueue.setParent(executor);

    setState(LifecycleState.STARTING);
}
```

`prestartminSpareThreads` 属性被整体删除，但**核心线程预启动并没有消失**——它下沉进了线程池构造函数，变成无条件执行：

```java
// util/threads/ThreadPoolExecutor.java:1082-1089
this.corePoolSize = corePoolSize;
this.maximumPoolSize = maximumPoolSize;
this.workQueue = workQueue;
this.keepAliveTime = unit.toNanos(keepAliveTime);
this.threadFactory = threadFactory;
this.handler = handler;

prestartAllCoreThreads();
```

因此「配置 `<Executor>` 后进程启动就有 minSpareThreads 个线程」在 11 里仍然是对的，只是**不再可关**。判断依据也随之改变：想看预启动行为要读 `ThreadPoolExecutor` 构造函数，而不是在 `StandardThreadExecutor` 里找一个已经不存在的开关。同理 `threadRenewalDelay`（`:98`）现在是唯一的构造后调优项，它服务于线程替换（renew）而非池大小。

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

## Virtual threads

11.0.26 里虚拟线程是 `createExecutor()` 的一个分支，而不是新的 endpoint：

```java
// util/net/AbstractEndpoint.java:1934-1945
public void createExecutor() {
    internalExecutor = true;
    if (getUseVirtualThreads()) {
        executor = new VirtualThreadExecutor(getName() + "-virt-");
    } else {
        TaskQueue taskqueue = new TaskQueue(maxQueueSize);
        TaskThreadFactory tf = new TaskThreadFactory(getName() + "-exec-", daemon, getThreadPriority());
        executor = new ThreadPoolExecutor(getMinSpareThreads(), getMaxThreads(), getThreadsMaxIdleTime(),
                TimeUnit.MILLISECONDS, taskqueue, tf);
        taskqueue.setParent((ThreadPoolExecutor) executor);
    }
}
```

`useVirtualThreads` 默认 `false`（`:1094`，setter `:1101`）。开启后**上面整节讲的 `TaskQueue`、`maxThreads`、`minSpareThreads`、`maxQueueSize` 全部失效**——因为不再有池，也就没有「队列满了再扩线程」这套语义，线程名从 `Catalina-exec-N` 变成 `Catalina-virt-N`。

实现刻意走反射，以便同一份二进制在低于虚拟线程要求的 JRE 上仍可加载：

```java
// util/threads/VirtualThreadExecutor.java:32-58
public class VirtualThreadExecutor extends AbstractExecutorService {

    private final CountDownLatch shutdown = new CountDownLatch(1);

    private final JreCompat jreCompat = JreCompat.getInstance();

    private Object threadBuilder;

    public VirtualThreadExecutor(String namePrefix) {
        threadBuilder = jreCompat.createVirtualThreadBuilder(namePrefix);
    }

    @Override
    public void execute(Runnable command) {
        if (isShutdown()) {
            throw new RejectedExecutionException(
                    sm.getString("virtualThreadExecutor.taskRejected", command.toString(), this.toString()));
        }
        jreCompat.threadBuilderStart(threadBuilder, command);
    }
```

字段类型是 `Object threadBuilder` 而不是 `Thread.Builder`，这是「Tomcat 11 的 Java 基线是 17，而虚拟线程要 21」这个矛盾的解法：基线以下不报错，只是这个开关不可用。

`server.xml` 里还可以显式声明一个虚拟线程执行器（给 `<Connector executor="...">` 用），它走另一个类：

```java
// catalina/core/StandardVirtualThreadExecutor.java:38
public class StandardVirtualThreadExecutor extends LifecycleMBeanBase implements Executor {
```

两者的区别值得记住：`AbstractEndpoint` 内置的是 `util` 里那个（生命周期归 endpoint），而声明式的 `StandardVirtualThreadExecutor` 是 `org.apache.catalina.Executor`，受容器生命周期与 JMX 管理，可以被多个 connector 共享。

⚠️ 网上常见的 `protocolHandlerVirtualThreadExecutorDefault` 这个属性名在 11.0.26 的 catalina 与 coyote 源码里**零命中**，不要按它去配。判断属性是否存在，用 `grep -rn "<属性名>" java/org/apache/tomcat/` 或直接查 11.0 的 config 文档，比查博客可靠。

调优上的真实取舍：虚拟线程消除了「工作线程池排队」这一层，但**没有**消除 `maxConnections`（它限制的是已接受的连接，见 [Connector](/docs/CS/Framework/Tomcat/Connector.md)），也没有让 `LimitLatch` 失效。用 `-virt-` 线程名去 jstack/JFR 里确认这条路是否真的生效，比读配置更可靠。与 Jetty 的做法差异见 [Jetty Threading](/docs/CS/Framework/Jetty/Threading.md)。

## Links

- [Tomcat](/docs/CS/Framework/Tomcat/Tomcat.md)
- [Version_Migration](/docs/CS/Framework/Tomcat/Version_Migration.md)

