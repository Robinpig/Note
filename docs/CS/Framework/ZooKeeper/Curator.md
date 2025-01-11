## Introduction

Apache Curator is a Java/JVM client library for [Apache ZooKeeper](https://zookeeper.apache.org/), a distributed coordination service. It includes a high level API framework and utilities to make using Apache ZooKeeper much easier and more reliable. It also includes recipes for common use cases and extensions such as service discovery and a Java 8 asynchronous DSL.

> Curator uses [Fluent Style](https://en.wikipedia.org/wiki/Fluent_interface).

Curator connection instances (CuratorFramework) are allocated from the `CuratorFrameworkFactory`. You only need one CuratorFramework object for each ZooKeeper cluster you are connecting to.
This will create a connection to a ZooKeeper cluster using default values.
The only thing that you need to specify is the retry policy.
The client must be started (and closed when no longer needed).

```java
RetryPolicy retryPolicy = new ExponentialBackoffRetry(1000, 3)
CuratorFramework client = CuratorFrameworkFactory.newClient(zookeeperConnectionString, retryPolicy);
client.start();CuratorFrameworkFactory.newClient(zookeeperConnectionString, retryPolicy
```

## Recipes

### Distributed Lock

```java
InterProcessMutex lock = new InterProcessMutex(client, lockPath);
if (lock.acquire(maxWait, waitUnit)) {
    try {
        // do some work inside of the critical section here
    } finally {
        lock.release();
    }
}
```


#### InterProcessMutex

```java
public class InterProcessMutex implements InterProcessLock, Revocable<InterProcessMutex> {
    private final LockInternals internals;
    private final String basePath;

    private final ConcurrentMap<Thread, LockData> threadData = Maps.newConcurrentMap();

    private static final String LOCK_NAME = "lock-";


    public boolean acquire(long time, TimeUnit unit) throws Exception {
        return internalLock(time, unit);
    }

    private boolean internalLock(long time, TimeUnit unit) throws Exception {
        /*
           Note on concurrency: a given lockData instance
           can be only acted on by a single thread so locking isn't necessary
        */

        Thread currentThread = Thread.currentThread();

        LockData lockData = threadData.get(currentThread);
        if (lockData != null) {
            // re-entering
            lockData.lockCount.incrementAndGet();
            return true;
        }

        String lockPath = internals.attemptLock(time, unit, getLockNodeBytes());
        if (lockPath != null) {
            LockData newLockData = new LockData(currentThread, lockPath);
            threadData.put(currentThread, newLockData);
            return true;
        }

        return false;
    }
}
```
这里两个核心的方法是 createsTheLock() 和 internalLockLoop()


```java
String attemptLock(long time, TimeUnit unit, byte[] lockNodeBytes) throws Exception {
    final long startMillis = System.currentTimeMillis();
    final Long millisToWait = (unit != null) ? unit.toMillis(time) : null;
    final byte[] localLockNodeBytes = (revocable.get() != null) ? new byte[0] : lockNodeBytes;
    int retryCount = 0;

    String ourPath = null;
    boolean hasTheLock = false;
    boolean isDone = false;
    while (!isDone) {
        isDone = true;

        try {
            ourPath = driver.createsTheLock(client, path, localLockNodeBytes);
            hasTheLock = internalLockLoop(startMillis, millisToWait, ourPath);
        } catch (KeeperException.NoNodeException e) {
            // gets thrown by StandardLockInternalsDriver when it can't find the lock node
            // this can happen when the session expires, etc. So, if the retry allows, just try it all again
            if (client.getZookeeperClient()
                    .getRetryPolicy()
                    .allowRetry(
                            retryCount++,
                            System.currentTimeMillis() - startMillis,
                            RetryLoop.getDefaultRetrySleeper())) {
                isDone = false;
            } else {
                throw e;
            }
        }
    }

    if (hasTheLock) {
        return ourPath;
    }

    return null;
}
```




```java
@Override
public String createsTheLock(CuratorFramework client, String path, byte[] lockNodeBytes) throws Exception {

    CreateMode createMode = CreateMode.EPHEMERAL_SEQUENTIAL;
    String sequence = getSortingSequence();
    if (sequence != null) {
        path += sequence;
        createMode = CreateMode.EPHEMERAL;
    }
    String ourPath;
    if (lockNodeBytes != null) {
        ourPath = client.create()
                .creatingParentContainersIfNeeded()
                .withProtection()
                .withMode(createMode)
                .forPath(path, lockNodeBytes);
    } else {
        ourPath = client.create()
                .creatingParentContainersIfNeeded()
                .withProtection()
                .withMode(createMode)
                .forPath(path);
    }
    return ourPath;
}
```
返回的临时有序节点的路径会作为参数传递给 internalLockLoop() 方法。每个线程创建好临时有序节点后，还需要判断它所创建的临时有序节点是否是当前最小的节点

```java
private boolean internalLockLoop(long startMillis, Long millisToWait, String ourPath) throws Exception {
    boolean haveTheLock = false;
    try {
        if (revocable.get() != null) {
            client.getData().usingWatcher(revocableWatcher).forPath(ourPath);
        }

        while ((client.getState() == CuratorFrameworkState.STARTED) && !haveTheLock) {
            List<String> children = getSortedChildren();
            String sequenceNodeName = ourPath.substring(basePath.length() + 1); // +1 to include the slash

            PredicateResults predicateResults = driver.getsTheLock(client, children, sequenceNodeName, maxLeases);
            if (predicateResults.getsTheLock()) {
                haveTheLock = true;
            } else {
                String previousSequencePath = basePath + "/" + predicateResults.getPathToWatch();

                synchronized (this) {
                    try {
                        // use getData() instead of exists() to avoid leaving unneeded watchers which is a type of
                        // resource leak
                        client.getData().usingWatcher(watcher).forPath(previousSequencePath);
                        if (millisToWait != null) {
                            millisToWait -= (System.currentTimeMillis() - startMillis);
                            startMillis = System.currentTimeMillis();
                            if (millisToWait <= 0) {
                                break;
                            }

                            wait(millisToWait);
                        } else {
                            wait();
                        }
                    } catch (KeeperException.NoNodeException e) {
                        // it has been deleted (i.e. lock released). Try to acquire again
                    }
                }
            }
        }
    } catch (Exception e) {
        ThreadUtils.checkInterrupted(e);
        deleteOurPathQuietly(ourPath, e);
        throw e;
    }
    if (!haveTheLock) {
        deleteOurPath(ourPath);
    }
    return haveTheLock;
}
```
判断当前节点是否是持有锁的节点，在不同锁类型（如读写锁和互斥锁）的判断是不同的，因此 getsTheLock 方法有着不同的实现


```java
@Override
public PredicateResults getsTheLock(
        CuratorFramework client, List<String> children, String sequenceNodeName, int maxLeases) throws Exception {
    int ourIndex = children.indexOf(sequenceNodeName);
    validateOurIndex(sequenceNodeName, ourIndex);

    boolean getsTheLock = ourIndex < maxLeases;
    String pathToWatch = getsTheLock ? null : children.get(ourIndex - maxLeases);

    return new PredicateResults(pathToWatch, getsTheLock);
}
```


```java
@Override
public void release() throws Exception {
    /*
       Note on concurrency: a given lockData instance
       can be only acted on by a single thread so locking isn't necessary
    */

    Thread currentThread = Thread.currentThread();
    LockData lockData = threadData.get(currentThread);
    if (lockData == null) {
        throw new IllegalMonitorStateException("You do not own the lock: " + basePath);
    }

    int newLockCount = lockData.lockCount.decrementAndGet();
    if (newLockCount > 0) {
        return;
    }
    if (newLockCount < 0) {
        throw new IllegalMonitorStateException("Lock count has gone negative for lock: " + basePath);
    }
    try {
        internals.releaseLock(lockData.lockPath);
    } finally {
        threadData.remove(currentThread);
    }
}
```

```java
final void releaseLock(String lockPath) throws Exception {
    client.removeWatchers();
    revocable.set(null);
    deleteOurPath(lockPath);
}
```


### Leader Election

```java
LeaderSelectorListener listener = new LeaderSelectorListenerAdapter() {
    public void takeLeadership(CuratorFramework client) throws Exception {
        // this callback will get called when you are the leader
        // do whatever leader work you need to and only exit
        // this method when you want to relinquish leadership
    }
}

LeaderSelector selector = new LeaderSelector(client, path, listener);
selector.autoRequeue();  // not required, but this is behavior that you will probably expect
selector.start();
```



## Service Discovery

ServiceInstance

A service instance is represented by the class: `ServiceInstance`.
 ServiceInstances have a name, id, address, port and/or ssl port, and an optional payload (user defined). 



ServiceProvider

The main abstraction class is ServiceProvider. 
It encapsulates the discovery service for a particular named service along with a provider strategy. 
A provider strategy is a scheme for selecting one instance from a set of instances for a given service. 
There are three bundled strategies: Round Robin, Random and Sticky (always selects the same one).

ServiceDiscovery

In order to allocate a ServiceProvider, you must have a ServiceDiscovery. It is created by a ServiceDiscoveryBuilder.

You must call start() on the object and, when done with it, call close().

Service Cache

Each of the above query methods calls ZooKeeper directly. 
If you need more than occasional querying of services you can use the ServiceCache. 
It caches in memory the list of instances for a particular service. 
It uses a Watcher to keep the list up to date.

You allocate a ServiceCache via the builder returned by `ServiceDiscovery.serviceCacheBuilder()`. The ServiceCache object must be started by calling start() and, when done, you should call close(). 

```xml
<!-- https://mvnrepository.com/artifact/org.apache.curator/curator-x-discovery -->
<dependency>
    <groupId>org.apache.curator</groupId>
    <artifactId>curator-x-discovery</artifactId>
</dependency>

```

## Links

- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)
