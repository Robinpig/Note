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
