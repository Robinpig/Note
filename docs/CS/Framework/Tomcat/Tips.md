## SynchronizedStack

这旨在作为 [java.util.concurrent.ConcurrentLinkedQueue](/docs/CS/Java/JDK/Collection/Queue.md?id=ConcurrentLinkedQueue) 的（几乎）无 GC 替代方案，适用于需要创建可复用对象池且无需收缩池的场景。
目标是尽可能快地提供最低限度的必要功能，同时产生最少的垃圾。

这是一个无界栈，依赖于 maxConnection。

```java
public class SynchronizedStack<T> {

    public static final int DEFAULT_SIZE = 128;
    private static final int DEFAULT_LIMIT = -1;
}
```

## Delay analysis

仅分析请求头，延迟分析请求体。

## daemon Thread

启动后台线程，定期检查 session 超时。

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

用于在固定延迟后调用此容器及其子容器的 backgroundProcess 方法的私有 runnable 类。

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

执行周期性任务，例如重新加载等。
此方法将在该容器的类加载上下文中调用。意外的 throwable 将被捕获并记录。

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
