

## Introduction



## Processor 对象池




SynchronizedStack 用**普通 `int` 索引 + `synchronized` 方法**维护一个 `Object[]` 栈，目标是「尽量不产生垃圾」而不是「无锁」。栈顶索引不是 `AtomicInteger`，`push`/`pop`/`clear`/`setLimit` 全部是同步方法（`util/collections/SynchronizedStack.java:90`、`:110`、`:122`、`:136`）；它靠「对象池本来就只在回收路径上被零散访问」这一前提换取实现简单，而**不是**靠 CAS。

池大小由 `processorCache` 属性配置，默认 200（`AbstractProtocol.java:192`）。每个 Processor 绑定一对 Request/Response，实现请求上下文复用。

### SynchronizedStack

This is intended as a (mostly) GC-free alternative to [java.util.concurrent.ConcurrentLinkedQueue](/docs/CS/Java/JDK/Collection/Queue.md?id=concurrentlinkedqueue) when the requirement is to create a pool of re-usable objects with no requirement to shrink the pool. 
The aim is to provide the bare minimum of required functionality as quickly as possible with minimum garbage.

字段与「满」的语义（`util/collections/SynchronizedStack.java`）：

```java
    public static final int DEFAULT_SIZE = 128;      // :31
    private static final int DEFAULT_LIMIT = -1;     // :36
    private int size;                                // :41
    private int limit;                               // :46  -1 表示不设上限
    private int index = -1;                          // :51  普通 int，不是 AtomicInteger
    private Object[] stack;                          // :56

    public synchronized boolean push(T obj) {        // :90
        index++;
        if (index == size) {
            if (limit == -1 || size < limit) {
                expand();
            } else {
                index--;
                return false;                        // 池已满，归还方拿不到位置
            }
        }
        stack[index] = obj;
```

两个容易被略过的点：

1. **`push` 会返回 false**，因此「归还对象」这件事必须能失败。调用方（processor 回收路径）拿回 false 时直接丢弃对象，让 GC 处理——所以 `limit` 一旦设小，行为是「静默退化成一个不缓存对象的容器」，而不是阻塞或报错。
2. **无界时它永不收缩**（`limit == -1` 的分支只 `expand()`）。这就是类注释里那句「no requirement to shrink the pool」的真实代价：峰值连接数会被池长期记住。想避免这种内存驻留，只能靠 `processorCache` 显式设上限。

## Delay analysis

only analysis request header, delay analysis request body

## daemon Thread

Start the background thread that will periodically check for session timeouts.

```java
 protected void threadStart() {
        if (backgroundProcessorDelay > 0
                && (getState().isAvailable() || LifecycleState.STARTING_PREP.equals(getState()))
                && (backgroundProcessorFuture == null || backgroundProcessorFuture.isDone())) {
            if (backgroundProcessorFuture != null && backgroundProcessorFuture.isDone()) {
                // There was an error executing the scheduled task, get it and log it
                try {
                    backgroundProcessorFuture.get();
                } catch (InterruptedException | ExecutionException e) {
                    log.error(sm.getString("containerBase.backgroundProcess.error"), e);
                }
            }
            backgroundProcessorFuture = Container.getService(this).getServer().getUtilityExecutor()
                    .scheduleWithFixedDelay(new ContainerBackgroundProcessor(),
                            backgroundProcessorDelay, backgroundProcessorDelay,
                            TimeUnit.SECONDS);
        }
    }
```


Private runnable class to invoke the backgroundProcess method of this container and its children after a fixed delay.
```java
protected class ContainerBackgroundProcessor implements Runnable {

    @Override
    public void run() {
        processChildren(ContainerBase.this);
    }

    protected void processChildren(Container container) {
        ClassLoader originalClassLoader = null;

        try {
            if (container instanceof Context) {
                Loader loader = ((Context) container).getLoader();
                // Loader will be null for FailedContext instances
                if (loader == null) {
                    return;
                }

                // Ensure background processing for Contexts and Wrappers
                // is performed under the web app's class loader
                originalClassLoader = ((Context) container).bind(false, null);
            }
            container.backgroundProcess();
            Container[] children = container.findChildren();
            for (Container child : children) {
                if (child.getBackgroundProcessorDelay() <= 0) {
                    processChildren(child);
                }
            }
        } catch (Throwable t) {
            ExceptionUtils.handleThrowable(t);
            log.error(sm.getString("containerBase.backgroundProcess.error"), t);
        } finally {
            if (container instanceof Context) {
                ((Context) container).unbind(false, originalClassLoader);
            }
        }
    }
}
```

### backgroundProcess
Execute a periodic task, such as reloading, etc. 
This method will be invoked inside the classloading context of this container. Unexpected throwables will be caught and logged.

```java
public abstract class ContainerBase extends LifecycleMBeanBase
        implements Container {
    
    @Override
    public void backgroundProcess() {

        if (!getState().isAvailable()) {
            return;
        }

        Cluster cluster = getClusterInternal();
        if (cluster != null) {
            try {
                cluster.backgroundProcess();
            } catch (Exception e) {
                log.warn(sm.getString("containerBase.backgroundProcess.cluster",
                        cluster), e);
            }
        }
        Realm realm = getRealmInternal();
        if (realm != null) {
            try {
                realm.backgroundProcess();
            } catch (Exception e) {
                log.warn(sm.getString("containerBase.backgroundProcess.realm", realm), e);
            }
        }
        Valve current = pipeline.getFirst();
        while (current != null) {
            try {
                current.backgroundProcess();
            } catch (Exception e) {
                log.warn(sm.getString("containerBase.backgroundProcess.valve", current), e);
            }
            current = current.getNext();
        }
        fireLifecycleEvent(Lifecycle.PERIODIC_EVENT, null);
    }
}
```
#### hotswap

```java
public class StandardContext extends ContainerBase
        implements Context, NotificationEmitter {

    @Override
    public void backgroundProcess() {

        if (!getState().isAvailable()) {
            return;
        }

        Loader loader = getLoader();
        if (loader != null) {
            try {
                loader.backgroundProcess();
            } catch (Exception e) {
                log.warn(sm.getString(
                        "standardContext.backgroundProcess.loader", loader), e);
            }
        }
        Manager manager = getManager();
        if (manager != null) {
            try {
                manager.backgroundProcess();
            } catch (Exception e) {
                log.warn(sm.getString(
                        "standardContext.backgroundProcess.manager", manager),
                        e);
            }
        }
        WebResourceRoot resources = getResources();
        if (resources != null) {
            try {
                resources.backgroundProcess();
            } catch (Exception e) {
                log.warn(sm.getString(
                        "standardContext.backgroundProcess.resources",
                        resources), e);
            }
        }
        InstanceManager instanceManager = getInstanceManager();
        if (instanceManager != null) {
            try {
                instanceManager.backgroundProcess();
            } catch (Exception e) {
                log.warn(sm.getString(
                        "standardContext.backgroundProcess.instanceManager",
                        resources), e);
            }
        }
        super.backgroundProcess();
    }
}
```

## Buffer


ByteBuffer 管理策略


Tomcat 8.0 及之前：使用全局 NioBufferPool 缓存 DirectByteBuffer。

Tomcat 8.5+：移除全局池，改为 Per-Socket 局部复用 + 严格 recycle()。原因是：

- 全局池在多线程下易成为竞争热点
- 现代 JVM（G1/ZGC）对短期对象回收已高度优化
- DirectByteBuffer 分配成本下降，但 clear() 复用仍必要

## Links

- [Tomcat](/docs/CS/Framework/Tomcat/Tomcat.md)
- [Connector](/docs/CS/Framework/Tomcat/Connector.md)
- [threads](/docs/CS/Framework/Tomcat/threads.md)
- [Container](/docs/CS/Framework/Tomcat/Container.md)
- [ClassLoader](/docs/CS/Framework/Tomcat/ClassLoader.md)
- [Version_Migration](/docs/CS/Framework/Tomcat/Version_Migration.md)

## References

- [Tomcat 11.0 API: SynchronizedStack](https://tomcat.apache.org/tomcat-11.0-doc/api/org/apache/tomcat/util/collections/SynchronizedStack.html)
