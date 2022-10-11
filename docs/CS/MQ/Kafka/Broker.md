## Introduction


### ISR



## Controller

It is also important to optimize the leadership election process as that is the critical window of unavailability.
A naive implementation of leader election would end up running an election per partition for all partitions a node hosted when that node failed.
As discussed above in the section on replication, Kafka clusters have a special role known as the "controller" which is responsible for managing the registration of brokers.
If the controller detects the failure of a broker, it is responsible for electing one of the remaining members of the ISR to serve as the new leader.
The result is that we are able to batch together many of the required leadership change notifications which makes the election process far cheaper and faster for a large number of partitions.
If the controller itself fails, then another controller will be elected.

QuorumController implements the main logic of the KRaft (Kafka Raft Metadata) mode controller.
The node which is the leader of the metadata log becomes the active controller.
All other nodes remain in standby mode. Standby controllers cannot create new metadata log entries.
They just replay the metadata log entries that the current active controller has created.
The QuorumController is **single-threaded**. A single event handler thread performs most operations.
This avoids the need for complex locking.
The controller exposes an *asynchronous, futures-based API* to the world.
This reflects the fact that the controller may have several operations in progress at any given point.
The future associated with each operation will not be completed until the results of the operation have been made durable to the metadata log.

1. Register Brokers
2. Register Topics
3. load Balance

### quorum replace zookeeper

why

1. 强依赖 维护困难
2. Zookeeper CP 影响性能

[KIP-500: Replace ZooKeeper with a Self-Managed Metadata Quorum](https://cwiki.apache.org/confluence/display/KAFKA/KIP-500%3A+Replace+ZooKeeper+with+a+Self-Managed+Metadata+Quorum)

We would like to remove this dependency on ZooKeeper.
This will enable us to manage metadata in a more scalable and robust way, enabling support for more partitions.
It will also simplify the deployment and configuration of Kafka.

#### Metadata as an Event Log

We often talk about the benefits of managing state as a stream of events.
A single number, the offset, describes a consumer's position in the stream.
Multiple consumers can quickly catch up to the latest state simply by replaying all the events newer than their current offset.
The log establishes a clear ordering between events, and ensures that the consumers always move along a single timeline.

However, although our users enjoy these benefits, Kafka itself has been left out.  We treat changes to metadata as isolated changes with no relationship to each other.
When the controller pushes out state change notifications (such as LeaderAndIsrRequest) to other brokers in the cluster, it is possible for brokers to get some of the changes, but not all.
Although the controller retries several times, it eventually give up.  This can leave brokers in a divergent state.

Worse still, although ZooKeeper is the store of record, the state in ZooKeeper often doesn't match the state that is held in memory in the controller.
For example, when a partition leader changes its ISR in ZK, the controller will typically not learn about these changes for many seconds.
There is no generic way for the controller to follow the ZooKeeper event log.
Although the controller can set one-shot watches, the number of watches is limited for performance reasons.
When a watch triggers, it doesn't tell the controller the current state-- only that the state has changed.
By the time the controller re-reads the znode and sets up a new watch, the state may have changed from what it was when the watch originally fired.
If there is no watch set, the controller may not learn about the change at all.  In some cases, restarting the controller is the only way to resolve the discrepancy.

Rather than being stored in a separate system, metadata should be stored in Kafka itself.  This will avoid all the problems associated with discrepancies between the controller state and the Zookeeper state.
Rather than pushing out notifications to brokers, brokers should simply consume metadata events from the event log.  This ensures that metadata changes will always arrive in the same order.
Brokers will be able to store metadata locally in a file.  When they start up, they will only need to read what has changed from the controller, not the full state.
This will let us support more partitions with less CPU consumption.

#### The Controller Quorum

The controller nodes comprise a Raft quorum which manages the metadata log.  This log contains information about each change to the cluster metadata.  Everything that is currently stored in ZooKeeper, such as topics, partitions, ISRs, configurations, and so on, will be stored in this log.

Using the Raft algorithm, the controller nodes will elect a leader from amongst themselves, without relying on any external system.  The leader of the metadata log is called the active controller.  The active controller handles all RPCs made from the brokers.  The follower controllers replicate the data which is written to the active controller, and serve as hot standbys if the active controller should fail.  Because the controllers will now all track the latest state, controller failover will not require a lengthy reloading period where we transfer all the state to the new controller.

Just like ZooKeeper, Raft requires a majority of nodes to be running in order to continue running.  Therefore, a three-node controller cluster can survive one failure.  A five-node controller cluster can survive two failures, and so on.

Periodically, the controllers will write out a snapshot of the metadata to disk.  While this is conceptually similar to compaction, the code path will be a bit different because we can simply read the state from memory rather than re-reading the log from disk.

#### Broker Metadata Management

Instead of the controller pushing out updates to the other brokers, those brokers will fetch updates from the active controller via the new MetadataFetch API.

A MetadataFetch is similar to a fetch request.  Just like with a fetch request, the broker will track the offset of the last updates it fetched, and only request newer updates from the active controller.

The broker will persist the metadata it fetched to disk.  
This will allow the broker to start up very quickly, even if there are hundreds of thousands or even millions of partitions.
(Note that since this persistence is an optimization, we can leave it out of the first version, if it makes development easier.)

Most of the time, the broker should only need to fetch the deltas, not the full state.  
However, if the broker is too far behind the active controller, or if the broker has no cached metadata at all, the controller will send a full metadata image rather than a series of deltas.



## Membership



### ZooKeeper





### KRaft



## Links

- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)