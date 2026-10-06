## Introduction

[Pulsar](https://pulsar.apache.org) is a distributed pub-sub messaging platform with a very flexible messaging model and an intuitive client API.

> 版本基线：**4.2.4**（tag `v4.2.4`，当前稳定版，2026-08-03 发布）。另有里程碑版 `v5.0.0-M1/M2`（2026-06/09），**里程碑版不是生产可用基线**。
> 依赖 BookKeeper **4.17.3**（根 `pom.xml:185`）。
> ⚠️ 4.x 相对 2.x/3.x 有**大量类删除与包路径迁移**（geo-replication、pulsar-streams、`enableIdempotence` 均已移除），照旧资料写必错 —— 逐条对照见 [BookKeeper](/docs/CS/MQ/Pulsar/BookKeeper.md) 与 [集群复制与分层存储](/docs/CS/MQ/Pulsar/Cluster.md) 的对照表。

## 主题导航

Pulsar 的独特之处在于**计算与存储彻底分离**：Broker 无状态，数据落到 BookKeeper ledger，元数据落到 metadata store。这个分层决定了它几乎所有能力（多租户、细粒度扩容、unload）的形态。

理解存储要落到 entry 与 cursor 两级 —— 见 [BookKeeper 存储层](/docs/CS/MQ/Pulsar/BookKeeper.md)；理解集群要抓住 bundle 切分与独立 LoadManager —— 见 [集群复制与分层存储](/docs/CS/MQ/Pulsar/Cluster.md)；Functions 与事务在 [Functions 与事务](/docs/CS/MQ/Pulsar/Functions.md)。

## Architecture

At the highest level, a Pulsar instance is composed of one or more Pulsar clusters.

In a Pulsar cluster:

- One or more brokers handles and load balances incoming messages from producers, dispatches messages to consumers, communicates with the Pulsar configuration store to handle various coordination tasks, stores messages in BookKeeper instances (aka bookies), and more.
- [BookKeeper](/docs/CS/Framework/BooKeeper/BooKeeper.md) cluster consisting of one or more bookies handles persistent storage of messages.
- **Metadata store** cluster specific to that cluster handles coordination tasks.

The diagram below illustrates a Pulsar cluster:

![Pulsar](./img/Architecture.png)

> [!WARNING]
> 4.2.4 的元数据存储不再强依赖 ZooKeeper：`MetadataStoreFactoryImpl.java:66-73` 注册了 `memory` / `rocksdb` / `etcd` / `oxia` / `zk` **五个 provider**，可用 `metadataStoreUrl` 显式选择（4.x 新增 etcd 与 Oxia）。
> 但**无配置时默认回退仍是 ZK**（`:97`）—— 「Pulsar 默认用 RocksDB 存元数据」不成立。

## Model

### Topic

PartitionedTopic

- NonPartitionedTopic -- only one partition

Persistent

```java
package org.apache.pulsar.broker.service;

public class ServerCnx extends PulsarHandler implements TransportCnx {
  @Override
  protected void handleLookup(CommandLookupTopic lookup) {
    final long requestId = lookup.getRequestId();
    final boolean authoritative = lookup.isAuthoritative();

    // use the connection-specific listener name by default.
    final String advertisedListenerName =
            lookup.hasAdvertisedListenerName() && StringUtils.isNotBlank(lookup.getAdvertisedListenerName())
                    ? lookup.getAdvertisedListenerName() : this.listenerName;

    TopicName topicName = validateTopicName(lookup.getTopic(), requestId, lookup);
    if (topicName == null) {
      return;
    }

    final Semaphore lookupSemaphore = service.getLookupRequestSemaphore();
    if (lookupSemaphore.tryAcquire()) {
      isTopicOperationAllowed(topicName, TopicOperation.LOOKUP, authenticationData, originalAuthData).thenApply(
              isAuthorized -> {
                if (isAuthorized) {
                  lookupTopicAsync(getBrokerService().pulsar(), topicName, authoritative,
                          getPrincipal(), getAuthenticationData(),
                          requestId, advertisedListenerName).handle((lookupResponse, ex) -> {
                    if (ex == null) {
                      ctx.writeAndFlush(lookupResponse);
                    } else {
                      // it should never happen
                      log.warn("[{}] lookup failed with error {}, {}", remoteAddress, topicName,
                              ex.getMessage(), ex);
                      ctx.writeAndFlush(newLookupErrorResponse(ServerError.ServiceNotReady,
                              ex.getMessage(), requestId));
                    }
                    lookupSemaphore.release();
                    return null;
                  });
                } else {
                  final String msg = "Proxy Client is not authorized to Lookup";
                  log.warn("[{}] {} with role {} on topic {}", remoteAddress, msg, getPrincipal(), topicName);
                  ctx.writeAndFlush(newLookupErrorResponse(ServerError.AuthorizationError, msg, requestId));
                  lookupSemaphore.release();
                }
                return null;
              }).exceptionally(ex -> {
        logAuthException(remoteAddress, "lookup", getPrincipal(), Optional.of(topicName), ex);
        final String msg = "Exception occurred while trying to authorize lookup";
        ctx.writeAndFlush(newLookupErrorResponse(ServerError.AuthorizationError, msg, requestId));
        lookupSemaphore.release();
        return null;
      });
    } else {
      ctx.writeAndFlush(newLookupErrorResponse(ServerError.TooManyRequests,
              "Failed due to too many pending lookup requests", requestId));
    }
  }
}
```


```java
public class LookupProxyHandler {
    public void handleLookup(CommandLookupTopic lookup) {
        long clientRequestId = lookup.getRequestId();
        if (lookupRequestSemaphore.tryAcquire()) {
            try {
                lookupRequests.inc();
                String serviceUrl = getBrokerServiceUrl(clientRequestId);
                if (serviceUrl != null) {
                    performLookup(clientRequestId, lookup.getTopic(), serviceUrl, false, 10);
                }
            } finally {
                lookupRequestSemaphore.release();
            }
        } else {
            rejectedLookupRequests.inc();
            proxyConnection.ctx().writeAndFlush(Commands.newLookupErrorResponse(ServerError.ServiceNotReady,
                    throttlingErrorMessage, clientRequestId));
        }

    }

    private void performLookup(long clientRequestId, String topic, String brokerServiceUrl, boolean authoritative,
                               int numberOfRetries) {
        if (numberOfRetries == 0) {
            proxyConnection.ctx().writeAndFlush(Commands.newLookupErrorResponse(ServerError.ServiceNotReady,
                    "Reached max number of redirections", clientRequestId));
            return;
        }

        URI brokerURI;
        try {
            brokerURI = new URI(brokerServiceUrl);
        } catch (URISyntaxException e) {
            proxyConnection.ctx().writeAndFlush(
                    Commands.newLookupErrorResponse(ServerError.MetadataError, e.getMessage(), clientRequestId));
            return;
        }

        InetSocketAddress addr = InetSocketAddress.createUnresolved(brokerURI.getHost(), brokerURI.getPort());
        proxyConnection.getConnectionPool().getConnection(addr).thenAccept(clientCnx -> {
            // Connected to backend broker
            long requestId = proxyConnection.newRequestId();
            ByteBuf command;
            command = Commands.newLookup(topic, authoritative, requestId);

            clientCnx.newLookup(command, requestId).whenComplete((r, t) -> {
                if (t != null) {
                    log.warn("[{}] Failed to lookup topic {}: {}", clientAddress, topic, t.getMessage());
                    proxyConnection.ctx().writeAndFlush(
                            Commands.newLookupErrorResponse(getServerError(t), t.getMessage(), clientRequestId));
                } else {
                    String brokerUrl = connectWithTLS ? r.brokerUrlTls : r.brokerUrl;
                    if (r.redirect) {
                        // Need to try the lookup again on a different broker
                        performLookup(clientRequestId, topic, brokerUrl, r.authoritative, numberOfRetries - 1);
                    } else {
                        // Reply the same address for both TLS non-TLS. The reason
                        // is that whether we use TLS
                        // and broker is independent of whether the client itself
                        // uses TLS, but we need to force the
                        // client
                        // to use the appropriate target broker (and port) when it
                        // will connect back.
                        proxyConnection.ctx().writeAndFlush(Commands.newLookupResponse(brokerUrl, brokerUrl, true,
                                LookupType.Connect, clientRequestId, true /* this is coming from proxy */));
                    }
                }
                proxyConnection.getConnectionPool().releaseConnection(clientCnx);
            });
        }).exceptionally(ex -> {
            // Failed to connect to backend broker
            proxyConnection.ctx().writeAndFlush(
                    Commands.newLookupErrorResponse(getServerError(ex), ex.getMessage(), clientRequestId));
            return null;
        });
    }
}
```

Ledger Fragment

Bundle -> multi-topics

```java
public class BundleData {
  // Short term data for this bundle. The time frame of this data is
  // determined by the number of short term samples
  // and the bundle update period.
  private TimeAverageMessageData shortTermData;

  // Long term data for this bundle. The time frame of this data is determined
  // by the number of long term samples
  // and the bundle update period.
  private TimeAverageMessageData longTermData;

  // number of topics present under this bundle
  private int topics;
}
```

#### CompactedTopic

view to latest messages of topic keys.
though append null like delete

## Brokers

The Pulsar message broker is a stateless component that's primarily responsible for running two other components:

* An HTTP server that exposes a REST API for both administrative tasks and [topic lookup](https://pulsar.apache.org/docs/next/concepts-clients#client-setup-phase) for producers and consumers.
* The producers connect to the brokers to publish messages and the consumers connect to the brokers to consume the messages.
* A dispatcher, which is an asynchronous TCP server over a custom binary protocol used for all data transfers

Messages are typically dispatched out of a [managed ledger](https://pulsar.apache.org/docs/next/concepts-architecture-overview#managed-ledgers) cache for the sake of performance, *unless* the backlog exceeds the cache size.
If the backlog grows too large for the cache, the broker will start reading entries from BookKeeper.

Finally, to support geo-replication on global topics, the broker manages replicators that tail the entries published in the local region and republish them to the remote region using the Pulsar Java client library.

## Clusters

A Pulsar instance consists of one or more Pulsar  *clusters* . Clusters, in turn, consist of:

* One or more Pulsar [brokers](https://pulsar.apache.org/docs/next/concepts-architecture-overview#brokers)
* A ZooKeeper quorum used for cluster-level configuration and coordination
* An ensemble of bookies used for [persistent storage](https://pulsar.apache.org/docs/next/concepts-architecture-overview#persistent-storage) of messages

Clusters can replicate among themselves using [geo-replication](https://pulsar.apache.org/docs/next/concepts-replication).XCon

> For a guide to managing Pulsar clusters, see the [clusters](https://pulsar.apache.org/docs/next/admin-api-clusters) guide.

## Metadata store

The Pulsar metadata store maintains all the metadata of a Pulsar cluster, such as topic metadata, schema, broker load data, and so on.

In a Pulsar instance:

* A configuration store quorum stores configuration for tenants, namespaces, and other entities that need to be globally consistent.
* Each cluster has its own metadata store that stores cluster-specific configuration and coordination such as which brokers are responsible for which topics as well as ownership metadata, broker load reports, BookKeeper ledger metadata, and more.

> [!TIP]
> 4.2.4 的 metadata store 是可插拔的（`pulsar-metadata` 模块，`MetadataStoreFactoryImpl.java:66-73`）：
>
> | scheme | 实现 | 适用场景 |
> | ------ | ---- | -------- |
> | `zk:` | `ZKMetadataStore` | 生产集群（**无配置时的默认回退**）|
> | `rocksdb:` | `RocksdbMetadataStore` | 单机（standalone）|
> | `etcd:` | `EtcdMetadataStore` | 4.x 新增 |
> | `oxia:` | `OxiaMetadataStoreProvider` | 4.x 新增 |
> | `memory:` | `LocalMemoryMetadataStore` | 测试 |
>
> 配置项 `metadataStoreUrl`（`ServiceConfiguration.java:139`，**默认 null**）经 `getMetadataStoreUrl()`（`:4134-4143`）三级回退：显式 URL → 已废弃的 `zookeeperServers` → 空串。
> BookKeeper 自己的元数据可独立配置（`bookkeeperMetadataServiceUri`，`:2031`，默认空），未设置时与 Pulsar **共享同一 MetadataStore 实例**。

> [!WARNING]
> 术语纠正：BookKeeper 4.17.3 中**没有 "fragment" 这个概念**，实际术语是 **`segment`**。层级是 **ledger → segment（副本集合变更记录）→ entry**。详见 [BookKeeper 存储层](/docs/CS/MQ/Pulsar/BookKeeper.md)。

## Configuration store

The configuration store maintains all the configurations of a Pulsar instance, such as clusters, tenants, namespaces, partitioned topic-related configurations, and so on.
A Pulsar instance can have a single local cluster, multiple local clusters, or multiple cross-region clusters. Consequently, the configuration store can share the configurations across multiple clusters under a Pulsar instance.

配置项为 `configurationMetadataStoreUrl`（`ServiceConfiguration.java:168`）与 `configurationStoreServers`（`:161`），解析优先级见 `:4153-4156`（前者优先，回落后者）。

> [!WARNING]
> **4.2.4 已移除内置的跨地域复制与备份**：`pulsar-replication` 模块、`PulsarGeoReplicationGroupCoordinator`、`PulsarBackup` / `PulsarClientBackup`、配置 `backupVersion` 全部零命中。跨集群/跨地域复制需外部方案（如 MirrorMaker），备份需靠 BookKeeper 层能力。

## Persistent storage

Pulsar provides guaranteed message delivery for applications. If a message successfully reaches a Pulsar broker, it will be delivered to its intended target.

This guarantee requires that non-acknowledged messages are stored durably until they can be delivered to and acknowledged by consumers. This mode of messaging is commonly called  *persistent messaging* .
In Pulsar, N copies of all messages are stored and synced on disk, for example, 4 copies across two servers with mirrored [RAID](https://en.wikipedia.org/wiki/RAID) volumes on each server.

### Apache BookKeeper

Pulsar uses a system called [Apache BookKeeper](http://bookkeeper.apache.org/) for persistent message storage.
BookKeeper is a distributed [write-ahead log](https://en.wikipedia.org/wiki/Write-ahead_logging) (WAL) system that provides several crucial advantages for Pulsar:

* It enables Pulsar to utilize many independent logs, called [ledgers](https://pulsar.apache.org/docs/next/concepts-architecture-overview#ledgers). Multiple ledgers can be created for topics over time.
* It offers very efficient storage for sequential data that handles entry replication.
* It guarantees read consistency of ledgers in the presence of various system failures.
* It offers even distribution of I/O across bookies.
* It's horizontally scalable in both capacity and throughput. Capacity can be immediately increased by adding more bookies to a cluster.
* Bookies are designed to handle thousands of ledgers with concurrent reads and writes.
* By using multiple disk devices---one for journal and another for general storage--bookies can isolate the effects of reading operations from the latency of ongoing write operations.

In addition to message data, *cursors* are also persistently stored in BookKeeper.
Cursors are [subscription](https://pulsar.apache.org/docs/next/reference-terminology#subscription) positions for [consumers](https://pulsar.apache.org/docs/next/reference-terminology#consumer).
BookKeeper enables Pulsar to store consumer position in a scalable fashion.

At the moment, Pulsar supports persistent message storage. This accounts for the `persistent` in all topic names. Here's an example:

```http
persistent://my-tenant/my-namespace/my-topic
```

> Pulsar also supports ephemeral ([non-persistent](https://pulsar.apache.org/docs/next/concepts-messaging.md#non-persistent-topics.md)) message storage.

You can see an illustration of how brokers and bookies interact in the diagram below:

### Ledgers

A ledger is an append-only data structure with a single writer that is assigned to multiple BookKeeper storage nodes, or bookies. Ledger entries are replicated to multiple bookies.
Ledgers themselves have very simple semantics:

* A Pulsar broker can create a ledger, append entries to the ledger, and close the ledger.
* After the ledger has been closed---either explicitly or because the writer process crashed---it can then be opened only in read-only mode.
* Finally, when entries in the ledger are no longer needed, the whole ledger can be deleted from the system (across all bookies).

#### Ledger read consistency

The main strength of Bookkeeper is that it guarantees read consistency in ledgers in the presence of failures.
Since the ledger can only be written to by a single process, that process is free to append entries very efficiently, without need to obtain consensus.
After a failure, the ledger will go through a recovery process that will finalize the state of the ledger and establish which entry was last committed to the log.
After that point, all readers of the ledger are guaranteed to see the exact same content.

#### Managed ledgers

Given that Bookkeeper ledgers provide a single log abstraction, a library was developed on top of the ledger called the *managed ledger* that represents the storage layer for a single topic.
A managed ledger represents the abstraction of a stream of messages with a single writer that keeps appending at the end of the stream and multiple cursors that are consuming the stream, each with its own associated position.

Internally, a single managed ledger uses multiple BookKeeper ledgers to store the data. There are two reasons to have multiple ledgers:

1. After a failure, a ledger is no longer writable and a new one needs to be created.
2. A ledger can be deleted when all cursors have consumed the messages it contains. This allows for periodic rollover of ledgers.

### Journal storage

In BookKeeper, *journal* files contain BookKeeper transaction logs.
Before making an update to a [ledger](https://pulsar.apache.org/docs/next/concepts-architecture-overview#ledgers), a bookie needs to ensure that a transaction describing the update is written to persistent (non-volatile) storage.
A new journal file is created once the bookie starts or the older journal file reaches the journal file size threshold (configured using the [`journalMaxSizeMB`](https://pulsar.apache.org/docs/next/reference-configuration.md#bookkeeper) parameter).

## Pulsar proxy

One way for Pulsar clients to interact with a Pulsar cluster is by connecting to Pulsar message brokers directly.
In some cases, however, this kind of direct connection is either infeasible or undesirable because the client doesn't have direct access to broker addresses.
If you're running Pulsar in a cloud environment or on [Kubernetes](https://kubernetes.io/) or an analogous platform, for example, then direct client connections to brokers are likely not possible.

The **Pulsar proxy** provides a solution to this problem by acting as a single gateway for all of the brokers in a cluster.
If you run the Pulsar proxy (which, again, is optional), all client connections with the Pulsar cluster will flow through the proxy rather than communicating with brokers.

> For the sake of performance and fault tolerance, you can run as many instances of the Pulsar proxy as you'd like.

Architecturally, the Pulsar proxy gets all the information it requires from ZooKeeper.
When starting the proxy on a machine, you only need to provide metadata store connection strings for the cluster-specific and instance-wide configuration store clusters.
Here's an example:

```bash
cd /path/to/pulsar/directory
bin/pulsar proxy \
--metadata-store zk:my-zk-1:2181,my-zk-2:2181,my-zk-3:2181 \
--configuration-metadata-store zk:my-zk-1:2181,my-zk-2:2181,my-zk-3:2181
```

> #### Pulsar proxy docs[](https://pulsar.apache.org/docs/next/concepts-architecture-overview#pulsar-proxy-docs "Direct link to heading")
>
> For documentation on using the Pulsar proxy, see the [Pulsar proxy admin documentation](https://pulsar.apache.org/docs/next/administration-proxy).

Some important things to know about the Pulsar proxy:

* Connecting clients don't need to provide *any* specific configuration to use the Pulsar proxy.
* You won't need to update the client configuration for existing applications beyond updating the IP used for the service URL (for example if you're running a load balancer over the Pulsar proxy).
* [TLS encryption](https://pulsar.apache.org/docs/next/security-tls-transport) and [authentication](https://pulsar.apache.org/docs/next/security-tls-authentication) is supported by the Pulsar proxy

## Client

Client instances are thread-safe and can be reused for managing multiple Producer, Consumer and Reader instances.

```java
PulsarClient client = PulsarClient.builder()                             
                            .serviceUrl("pulsar://broker:6650")                             
                            .build();

```

```java

public class PulsarClientImpl implements PulsarClient {

    protected final ClientConfigurationData conf;
    private LookupService lookup;
    private final ConnectionPool cnxPool;
    @Getter
    private final Timer timer;
    private boolean needStopTimer;
    private final ExecutorProvider externalExecutorProvider;
    private final ExecutorProvider internalExecutorService;
    private final boolean createdEventLoopGroup;
    private final boolean createdCnxPool;

    private final AtomicReference<State> state = new AtomicReference<>();
    // These sets are updated from multiple threads, so they require a threadsafe data structure
    private final Set<ProducerBase<?>> producers = Collections.newSetFromMap(new ConcurrentHashMap<>());
    private final Set<ConsumerBase<?>> consumers = Collections.newSetFromMap(new ConcurrentHashMap<>());

    private final AtomicLong producerIdGenerator = new AtomicLong();
    private final AtomicLong consumerIdGenerator = new AtomicLong();
    private final AtomicLong requestIdGenerator
            = new AtomicLong(ThreadLocalRandom.current().nextLong(0, Long.MAX_VALUE/2));

    protected final EventLoopGroup eventLoopGroup;
    private final MemoryLimitController memoryLimitController;
}
```

## Transaction

事务协调器由 `pulsar-transaction/coordinator` 模块实现，**默认关闭**（`transactionCoordinatorEnabled = false`，`ServiceConfiguration.java:3756`）。启用后提供 7 态状态机 `Transaction.State`（`OPEN` → `COMMITTING`/`ABORTING` → `COMMITTED`/`ABORTED`，另有 `ERROR` / `TIME_OUT`），提交时向 ledger 追加 commit marker。

> [!IMPORTANT]
> **普通非事务订阅是 at-least-once，不是 exactly-once。** `readPosition` 在「读」时推进而非 ack 时，投递后崩溃会从 `markDeletePosition` 重读导致重复。
>
> 4.x 中**幂等开关本身已被删除** —— `enableIdempotence` API 与配置字段均零命中，改为 `ProducerAccessMode`（`Shared` 默认 / `Exclusive` / `ExclusiveWithFencing` / `WaitForExclusive`），去重由 `brokerDeduplicationEnabled`（默认 false）+ namespace/topic 策略驱动。
>
> 细节见 [Functions 与事务](/docs/CS/MQ/Pulsar/Functions.md)。

## Links

- [MQ](/docs/CS/MQ/MQ.md)
- [BookKeeper 存储层](/docs/CS/MQ/Pulsar/BookKeeper.md)
- [集群复制与分层存储](/docs/CS/MQ/Pulsar/Cluster.md)
- [Functions 与事务](/docs/CS/MQ/Pulsar/Functions.md)
- [Broker](/docs/CS/MQ/Pulsar/Broker.md)
- [BookKeeper](/docs/CS/Framework/BooKeeper/BooKeeper.md)

## References
