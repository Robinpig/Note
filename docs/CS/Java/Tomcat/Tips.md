

## SynchronizedStack

This is intended as a (mostly) GC-free alternative to [java.util.concurrent.ConcurrentLinkedQueue](/docs/CS/Java/JDK/Collection/Queue.md?id=ConcurrentLinkedQueue) when the requirement is to create a pool of re-usable objects with no requirement to shrink the pool. 
The aim is to provide the bare minimum of required functionality as quickly as possible with minimum garbage.

This is a unbound stack and depended on maxConnection.

```java
public class SynchronizedStack<T> {

    public static final int DEFAULT_SIZE = 128;
    private static final int DEFAULT_LIMIT = -1;
}
```

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

