## Introduction

ZooKeeper is a centralized service for maintaining configuration information, naming, providing distributed synchronization, and providing group services.

All of these kinds of services are used in some form or another by distributed applications.
Each time they are implemented there is a lot of work that goes into fixing the bugs and race conditions that are inevitable.
Because of the difficulty of implementing these kinds of services, applications initially usually skimp on them, which make them brittle in the presence of change and difficult to manage.
Even when done correctly, different implementations of these services lead to management complexity when the applications are deployed.

ZooKeeper aims at distilling the essence of these different services into a very simple interface to a centralized coordination service.
The service itself is distributed and highly reliable.
Consensus, group management, and presence protocols will be implemented by the service so that the applications do not need to implement them on their own.
Application specific uses of these will consist of a mixture of specific components of Zoo Keeper and application specific conventions.

**ZooKeeper provides a per client guarantee of FIFO execution of requests and linearizability for all requests that change the ZooKeeper state.**
To guarantee that update operations satisfy linearizability, Zookeeper implements a leader-based atomic broadcast protocol, called **Zab**.

In ZooKeeper, servers process read operations locally, and we do not use Zab to totally order them.

Caching data on the client side is an important technique to increase the performance of reads.
For example, it is useful for a process to cache the identifier of the current leader instead of probing ZooKeeper every time it needs to know the leader.
ZooKeeper uses a watch mechanism to enable clients to cache data without managing the client cache directly.
With this mechanism, a client can watch for an update to a given data object, and receive a notification upon an update.
Chubby manages the client cache directly.

ZooKeeper provides to its clients the abstraction of a set of data nodes (znodes), organized according to a hierarchical name space.

ZooKeeper also has the following two liveness and durability guarantees: if a majority of ZooKeeper servers are active and communicating the service will be available;
and if the ZooKeeper service responds successfully to a change request, that change persists across any number of failures as long as a quorum of servers is eventually able to recover.

### ZooKeeper guarantees

ZooKeeper has two basic ordering guarantees:

- **Linearizable writes:** all requests that update the state of ZooKeeper are serializable and respect precedence;
- **FIFO client order:** all requests from a given client are executed in the order that they were sent by the client.

ecause only update requests are Alinearizable, ZooKeeper processes read requests locally at each replica.
This allows the service to scale linearly as servers are added to the system.

ZooKeeper is very fast and very simple. Since its goal, though, is to be a basis for the construction of more complicated services, such as synchronization, it provides a set of guarantees. These are:

* Sequential Consistency - Updates from a client will be applied in the order that they were sent.
* Atomicity - Updates either succeed or fail. No partial results.
* Single System Image - A client will see the same view of the service regardless of the server that it connects to. i.e., a client will never see an older view of the system even if the client fails over to a different server with the same session.
* Reliability - Once an update has been applied, it will persist from that time forward until a client overwrites the update.
* Timeliness - The clients view of the system is guaranteed to be up-to-date within a certain time bound.

## Data Model

ZooKeeper has a hierarchal name space, much like a distributed file system.
The only difference is that each node in the namespace can have data associated with it as well as children.
It is like having a file system that allows a file to also be a directory.
Paths to nodes are always expressed as canonical, absolute, slash-separated paths; there are no relative reference.

ZooKeeper's Hierarchical Namespace

![ZooKeeper's Hierarchical Namespace](https://zookeeper.apache.org/doc/current/images/zknamespace.jpg)

### ZNodes

Unlike files in file systems, znodes are not designed for general data storage.
Instead, znodes map to abstractions of the client application, typically corresponding to meta-data used for coordination purposes.

Although znodes have not been designed for general data storage, ZooKeeper does allow clients to store some information that can be used for meta-data or configuration in a distributed computation.
For example, in a leader-based application, it is useful for an application server that is just starting to learn which other server is currently the leader.
To accomplish this goal, we can have the current leader write this information in a known location in the znode space.

Znodes also have associated meta-data with time stamps and version counters, which allow clients to track changes to znodes and execute conditional updates based on the version of the znode.

Unlike standard file systems, each node in a ZooKeeper namespace can have data associated with it as well as children.
It is like having a file-system that allows a file to also be a directory.
(ZooKeeper was designed to store coordination data: status information, configuration, location information, etc., so the data stored at each node is usually small, in the byte to kilobyte range.)
We use the term znode to make it clear that we are talking about ZooKeeper data nodes.

Znodes maintain a stat structure that includes version numbers for data changes, ACL changes, and timestamps, to allow cache validations and coordinated updates.
Each time a znode's data changes, the version number increases.
For instance, whenever a client retrieves data it also receives the version of the data.

The data stored at each znode in a namespace is read and written atomically. Reads get all the data bytes associated with a znode and a write replaces all the data.
Each node has an Access Control List (ACL) that restricts who can do what.

ZooKeeper also has the notion of ephemeral nodes. These znodes exists as long as the session that created the znode is active. When the session ends the znode is deleted.

Container node

TTL time to live

### Watches

Clients can set watches on znodes.
Changes to that znode trigger the watch and then clear the watch. When a watch triggers, ZooKeeper sends the client a notification.

**New in 3.6.0:** Clients can also set permanent, recursive watches on a znode that are not removed when triggered and that trigger for changes on the registered znode as well as any children znodes recursively.

ZooKeeper also has the notion of ephemeral nodes.
These znodes exists as long as the session that created the znode is active.
When the session ends the znode is deleted. Because of this behavior ephemeral znodes are not allowed to have children.

### Guarantees

ZooKeeper is very fast and very simple. Since its goal, though, is to be a basis for the construction of more complicated services, such as synchronization, it provides a set of guarantees. These are:

- Sequential Consistency - Updates from a client will be applied in the order that they were sent.
- Atomicity - Updates either succeed or fail. No partial results.
- Single System Image - A client will see the same view of the service regardless of the server that it connects to. i.e., a client will never see an older view of the system even if the client fails over to a different server with the same session.
- Reliability - Once an update has been applied, it will persist from that time forward until a client overwrites the update.
- Timeliness - The clients view of the system is guaranteed to be up-to-date within a certain time bound.

The consistency guarantees of ZooKeeper lie between sequential consistency and linearizability.
Write operations in ZooKeeper are linearizable. In other words, each write will appear to take effect atomically at some point between when the client issues the request and receives the corresponding response.
Read operations in ZooKeeper are not linearizable since they can return potentially stale data.
This is because a read in ZooKeeper is not a quorum operation and a server will respond immediately to a client that is performing a read.
ZooKeeper does this because it prioritizes performance over consistency for the read use case.

### Simple API

One of the design goals of ZooKeeper is providing a very simple programming interface. As a result, it supports only these operations:

- *create* : creates a node at a location in the tree
- *delete* : deletes a node
- *exists* : tests if a node exists at a location
- *get data* : reads the data from a node
- *set data* : writes data to a node
- *get children* : retrieves a list of children of a node
- *sync* : waits for data to be propagated

## Implementation

![The components of the ZooKeeper service](./img/components.png)

## Atomic Broadcast

At the heart of ZooKeeper is an atomic messaging system that keeps all of the servers in sync.

**All requests that update ZooKeeper state are forwarded to the leader.**
The leader executes the request and broadcasts the change to the ZooKeeper state through [Zab](/docs/CS/Java/ZooKeeper/Zab.md), an atomic broadcast protocol.
The server that receives the client request responds to the client when it delivers the corresponding state change.
Zab uses by default simple majority quorums to decide on a proposal, so Zab and thus ZooKeeper can only work if a majority of servers are correct (i.e., with $2f + 1$ server we can tolerate $f$ failures).

Read requests are handled locally at each server.
Each read request is processed and tagged with a zxid that corresponds to the last transaction seen by the server.
This zxid defines the partial order of the read requests with respect to the write requests.
By processing reads locally, we obtain excellent read performance because it is just an in-memory operation on the local server, and there is no disk activity or agreement protocol to run.
This design choice is key to achieving our goal of excellent performance with read-dominant workloads.

One drawback of using fast reads is not guaranteeing precedence order for read operations.
That is, a read operation may return a stale value, even though a more recent update to the same znode has been committed.
Not all of our applications require precedence order, but for applications that do require it, we have implemented sync.
This primitive executes asynchronously and is ordered by the leader after all pending writes to its local replica.
To guarantee that a given read operation returns the latest updated value, a client calls sync followed by the read operation.

The FIFO order guarantee of client operations together with the global guarantee of sync enables the result of the read operation to reflect any changes that happened before the sync was issued.
In our implementation, we do not need to atomically broadcast sync as we use a leader-based algorithm, and we simply place the sync operation at the end of the queue of requests between the leader and the server executing the call to sync.
In order for this to work, the follower must be sure that the leader is still the leader.
If there are pending transactions that commit, then the server does not suspect the leader.
If the pending queue is empty, the leader needs to issue a null transaction to commit and orders the sync after that transaction.
This has the nice property that when the leader is under load, no extra broadcast traffic is generated.
In our implementation, timeouts are set such that leaders realize they are not leaders before followers abandon them, so we do not issue the null transaction.

ZooKeeper servers process requests from clients in FIFO order.
Responses include the zxid that the response is relative to.
Even heartbeat messages during intervals of no activity include the last zxid seen by the server that the client is connected to.
If the client connects to a new server, that new server ensures that its view of the ZooKeeper data is at least as recent as the view of the client by checking the last zxid of the client against its last zxid.
If the client has a more recent view than the server, the server does not reestablish the session with the client until the server has caught up.
The client is guaranteed to be able to find another server that has a recent view of the
system since the client only sees changes that have been
replicated to a majority of the ZooKeeper servers. This
behavior is important to guarantee durability.

To detect client session failures, ZooKeeper uses timeouts.
The leader determines that there has been a failure if no other server receives anything from a client session within the session timeout.
If the client sends requests frequently enough, then there is no need to send any other message.
Otherwise, the client sends heartbeat messages during periods of low activity.
If the client cannot communicate with a server to send a request or heartbeat, it connects to a different ZooKeeper server to re-establish its session.
To prevent the session from timing out, the ZooKeeper client library sends a heartbeat after the session has been idle for s=3 ms and switch to a new server if it has not heard from a server for 2s=3 ms, where s is the session timeout in milliseconds.

### Guarantees, Properties, and Definitions

The specific guarantees provided by the messaging system used by ZooKeeper are the following:

- Reliable delivery
  If a message, m, is delivered by one server, it will be eventually delivered by all servers.
- Total order
  If a message is delivered before message b by one server, a will be delivered before b by all servers. If a and b are delivered messages, either a will be delivered before b or b will be delivered before a.
- Causal order
  If a message b is sent after a message a has been delivered by the sender of b, a must be ordered before b. If a sender sends c after sending b, c must be ordered after b.

Our protocol assumes that we can construct point-to-point FIFO channels between the servers.
While similar services usually assume message delivery that can lose or reorder messages, our assumption of FIFO channels is very practical given that we use TCP for communication.
Specifically we rely on the following property of TCP:

- Ordered delivery
  Data is delivered in the same order it is sent and a message m is delivered only after all messages sent before m have been delivered. (The corollary to this is that if message m is lost all messages after m will be lost.)
- No message after close
  Once a FIFO channel is closed, no messages will be received from it.

FLP proved that consensus cannot be achieved in asynchronous distributed systems if failures are possible.
To ensure we achieve consensus in the presence of failures we use timeouts. However, we rely on times for liveness not for correctness.
So, if timeouts stop working (clocks malfunction for example) the messaging system may hang, but it will not violate its guarantees.

When describing the ZooKeeper messaging protocol we will talk of packets, proposals, and messages:

- *Packet*a sequence of bytes sent through a FIFO channel
- *Proposal*a unit of agreement. Proposals are agreed upon by exchanging packets with a quorum of ZooKeeper servers.
  Most proposals contain messages, however the NEW_LEADER proposal is an example of a proposal that does not correspond to a message.
- *Message*a sequence of bytes to be atomically broadcast to all ZooKeeper servers. A message put into a proposal and agreed upon before it is delivered.

As stated above, ZooKeeper guarantees a total order of messages, and it also guarantees a total order of proposals.
ZooKeeper exposes the total ordering using a ZooKeeper transaction id (zxid). All proposals will be stamped with a zxid when it is proposed and exactly reflects the total ordering.
Proposals are sent to all ZooKeeper servers and committed when a quorum of them acknowledge the proposal. If a proposal contains a message, the message will be delivered when the proposal is committed.
Acknowledgement means the server has recorded the proposal to persistent storage.
Our quorums have the requirement that any pair of quorum must have at least one server in common.
We ensure this by requiring that all quorums have size (n/2+1) where n is the number of servers that make up a ZooKeeper service.

The zxid has two parts: the epoch and a counter. In our implementation the zxid is a 64-bit number.
We use the high order 32-bits for the epoch and the low order 32-bits for the counter.
Because it has two parts represent the zxid both as a number and as a pair of integers, (epoch, count). The epoch number represents a change in leadership.
Each time a new leader comes into power it will have its own epoch number.
We have a simple algorithm to assign a unique zxid to a proposal: the leader simply increments the zxid to obtain a unique zxid for each proposal.
Leadership activation will ensure that only one leader uses a given epoch, so our simple algorithm guarantees that every proposal will have a unique id.

## Messaging

ZooKeeper messaging consists of two phases:

- *Leader activation*
  In this phase a leader establishes the correct state of the system and gets ready to start making proposals.
- *Active messaging*
  In this phase a leader accepts messages to propose and coordinates message delivery.

All proposals have a unique zxid, so unlike other protocols, we never have to worry about two different values being proposed for the same zxid;
followers (a leader is also a follower) see and record proposals in order; proposals are committed in order; there is only one active leader at a time since followers only follow a single leader at a time;
a new leader has seen all committed proposals from the previous epoch since it has seen the highest zxid from a quorum of servers;
any uncommitted proposals from a previous epoch seen by a new leader will be committed by that leader before it becomes active.


Isn't this just Multi-Paxos? No, Multi-Paxos requires some way of assuring that there is only a single coordinator. 
We do not count on such assurances. Instead we use the leader activation to recover from leadership change or old leaders believing they are still active.

Isn't this just Paxos? 
Your active messaging phase looks just like phase 2 of Paxos? Actually, to us active messaging looks just like 2 phase commit without the need to handle aborts. 
Active messaging is different from both in the sense that it has cross proposal ordering requirements. If we do not maintain strict FIFO ordering of all packets, it all falls apart. 
Also, our leader activation phase is different from both of them. In particular, our use of epochs allows us to skip blocks of uncommitted proposals and to not worry about duplicate proposals for a given zxid.


#### Leader Activation

Leader activation includes leader election.
We currently have two leader election algorithms in ZooKeeper: LeaderElection and FastLeaderElection (AuthFastLeaderElection is a variant of FastLeaderElection that uses UDP and allows servers to perform a simple form of authentication to avoid IP spoofing).
ZooKeeper messaging doesn't care about the exact method of electing a leader has long as the following holds:

- The leader has seen the highest zxid of all the followers.
- A quorum of servers have committed to following the leader.

Of these two requirements only the first, the highest zxid amoung the followers needs to hold for correct operation.
The second requirement, a quorum of followers, just needs to hold with high probability.
We are going to recheck the second requirement, so if a failure happens during or after the leader election and quorum is lost, we will recover by abandoning leader activation and running another election.

After leader election a single server will be designated as a leader and start waiting for followers to connect.
The rest of the servers will try to connect to the leader.
The leader will sync up with followers by sending any proposals they are missing, or if a follower is missing too many proposals, it will send a full snapshot of the state to the follower.

There is a corner case in which a follower that has proposals, U, not seen by a leader arrives.
Proposals are seen in order, so the proposals of U will have a zxids higher than zxids seen by the leader.
The follower must have arrived after the leader election, otherwise the follower would have been elected leader given that it has seen a higher zxid.
Since committed proposals must be seen by a quorum of servers, and a quorum of servers that elected the leader did not see U, the proposals of you have not been committed, so they can be discarded.
When the follower connects to the leader, the leader will tell the follower to discard U.

A new leader establishes a zxid to start using for new proposals by getting the epoch, e, of the highest zxid it has seen and setting the next zxid to use to be (e+1, 0), after the leader syncs with a follower, it will propose a NEW_LEADER proposal.
Once the NEW_LEADER proposal has been committed, the leader will activate and start receiving and issuing proposals.

It all sounds complicated but here are the basic rules of operation during leader activation:

- A follower will ACK the NEW_LEADER proposal after it has synced with the leader.
- A follower will only ACK a NEW_LEADER proposal with a given zxid from a single server.
- A new leader will COMMIT the NEW_LEADER proposal when a quorum of followers have ACKed it.
- A follower will commit any state it received from the leader when the NEW_LEADER proposal is COMMIT.
- A new leader will not accept new proposals until the NEW_LEADER proposal has been COMMITED.

If leader election terminates erroneously, we don't have a problem since the NEW_LEADER proposal will not be committed since the leader will not have quorum. When this happens, the leader and any remaining followers will timeout and go back to leader election.

#### Active Messaging

Leader Activation does all the heavy lifting. Once the leader is coronated he can start blasting out proposals.
As long as he remains the leader no other leader can emerge since no other leader will be able to get a quorum of followers.
If a new leader does emerge, it means that the leader has lost quorum, and the new leader will clean up any mess left over during her leadership activation.

ZooKeeper messaging operates similar to a classic two-phase commit.

All communication channels are FIFO, so everything is done in order.
Specifically the following operating constraints are observed:

- The leader sends proposals to all followers using the same order.
  Moreover, this order follows the order in which requests have been received.
  Because we use FIFO channels this means that followers also receive proposals in order.
- Followers process messages in the order they are received.
  This means that messages will be ACKed in order and the leader will receive ACKs from followers in order, due to the FIFO channels.
  It also means that if message $m$ has been written to non-volatile storage, all messages that were proposed before $m$ have been written to non-volatile storage.
- The leader will issue a COMMIT to all followers as soon as a quorum of followers have ACKed a message.
  Since messages are ACKed in order, COMMITs will be sent by the leader as received by the followers in order.
- COMMITs are processed in order. Followers deliver a proposals message when that proposal is committed.

### Quorums

Atomic broadcast and leader election use the notion of quorum to guarantee a consistent view of the system. 
By default, ZooKeeper uses majority quorums, which means that every voting that happens in one of these protocols requires a majority to vote on. One example is acknowledging a leader proposal: 
the leader can only commit once it receives an acknowledgement from a quorum of servers.

If we extract the properties that we really need from our use of majorities, we have that we only need to guarantee that groups of processes used to validate an operation by voting (e.g., acknowledging a leader proposal) pairwise intersect in at least one server. 
Using majorities guarantees such a property. However, there are other ways of constructing quorums different from majorities. 
For example, we can assign weights to the votes of servers, and say that the votes of some servers are more important. 
To obtain a quorum, we get enough votes so that the sum of weights of all votes is larger than half of the total sum of all weights.

A different construction that uses weights and is useful in wide-area deployments (co-locations) is a hierarchical one. 
With this construction, we split the servers into disjoint groups and assign weights to processes. 
To form a quorum, we have to get a hold of enough servers from a majority of groups G, such that for each group g in G, the sum of votes from g is larger than half of the sum of weights in g. 
Interestingly, this construction enables smaller quorums. If we have, for example, 9 servers, we split them into 3 groups, and assign a weight of 1 to each server, then we are able to form quorums of size 4. 
Note that two subsets of processes composed each of a majority of servers from each of a majority of groups necessarily have a non-empty intersection. 
It is reasonable to expect that a majority of co-locations will have a majority of servers available with high probability.

With ZooKeeper, we provide a user with the ability of configuring servers to use majority quorums, weights, or a hierarchy of groups.

## Recipes

- Configuration Management
- Rendezvous
- Group Membership
- Simple Locks
- Read/Write Locks

The replicated database is an **in-memory** database containing the entire data tree.
Each znode in the tree stores a maximum of 1MB of data by default, but this maximum value is a configuration parameter that can be changed in specific cases.
For recoverability, we efficiently log updates to disk, and we force writes to be on the disk media before they are applied to the in-memory database.
In fact, as Chubby, we keep a replay log (a write-ahead log, in our case) of committed operations and generate periodic snapshots of the in-memory database.

Every ZooKeeper server services clients. Clients connect to exactly one server to submit its requests.
As we noted earlier, read requests are serviced from the local replica of each server database.
Requests that change the state of the service, write requests, are processed by an agreement protocol.

As part of the agreement protocol write requests are forwarded to a single server, called the leader1.
The rest of the ZooKeeper servers, called followers, receive message proposals consisting of state changes from the leader and agree upon state changes.

Since the messaging layer is atomic, we guarantee that the local replicas never diverge, although at any point in time some servers may have applied more transactions than others.
Unlike the requests sent from clients, the transactions are *idempotent*.
When the leader receives a write request, it calculates what the state of the system will be when the write is applied and transforms it into a transaction that captures this new state.
The future state must be calculated because there may be outstanding transactions that have not yet been applied to the database.
For example, if a client does a conditional setData and the version number in the request matches the future version number of the znode being updated, the service generates a setDataTXN that contains the new data, the new version number, and updated time stamps.
If an error occurs, such as mismatched version numbers or the znode to be updated does not exist, an errorTXN is generated instead.

During normal operation Zab does deliver all messages in order and exactly once, but since Zab does not
persistently record the id of every message delivered,
Zab may redeliver a message during recovery. Because
we use idempotent transactions, multiple delivery is acceptable as long as they are delivered in order. In fact,
ZooKeeper requires Zab to redeliver at least all messages
that were delivered after the start of the last snapshot.

### Barriers

Barriers are implemented in ZooKeeper by designating a barrier node. The barrier is in place if the barrier node exists. Here's the pseudo code:

1. Client calls the ZooKeeper API's **exists()** function on the barrier node, with *watch* set to true.
2. If **exists()** returns false, the barrier is gone and the client proceeds
3. Else, if **exists()** returns true, the clients wait for a watch event from ZooKeeper for the barrier node.
4. When the watch event is triggered, the client reissues the **exists( )** call, again waiting until the barrier node is removed.

#### Double Barriers

Double barriers enable clients to synchronize the beginning and the end of a computation.
When enough processes have joined the barrier, processes start their computation and leave the barrier once they have finished.

### Queues

To implement a distributed queue in ZooKeeper, first designate a znode to hold the queue, the queue node.
The distributed clients put something into the queue by calling create() with a pathname ending in "queue-", with the *sequence* and *ephemeral* flags in the create() call set to true.
Because the *sequence* flag is set, the new pathname will have the form  *path-to-queue-node* /queue-X, where X is a monotonic increasing number.
A client that wants to be removed from the queue calls ZooKeeper's **getChildren( )** function, with *watch* set to true on the queue node, and begins processing nodes with the lowest number.
The client does not need to issue another **getChildren( )** until it exhausts the list obtained from the first **getChildren( )** call.
If there are no children in the queue node, the reader waits for a watch notification to check the queue again.

#### Priority Queues

To implement a priority queue, you need only make two simple changes to the generic queue recipe.

- First, to add to a queue, the pathname ends with "queue-YY" where YY is the priority of the element with lower numbers representing higher priority (just like UNIX).
- Second, when removing from the queue, a client uses an up-to-date children list meaning that the client will invalidate previously obtained children lists if a watch notification triggers for the queue node.

### Locks

Fully distributed locks that are globally synchronous, meaning at any snapshot in time no two clients think they hold the same lock.
These can be implemented using ZooKeeper. As with priority queues, first define a lock node.

Here are a few things to notice:

- The removal of a node will only cause one client to wake up since each node is watched by exactly one client. In this way, you avoid the herd effect.
- There is no polling or timeouts.
- Because of the way you implement locking, it is easy to see the amount of lock contention, break locks, debug locking problems, etc.

### Two-phased Commit

A two-phase commit protocol is an algorithm that lets all clients in a distributed system agree either to commit a transaction or abort.

In ZooKeeper, you can implement a two-phased commit by having a coordinator create a transaction node, say "/app/Tx", and one child node per participating site, say "/app/Tx/s_i".
When coordinator creates the child node, it leaves the content undefined. Once each site involved in the transaction receives the transaction from the coordinator, the site reads each child node and sets a watch.
Each site then processes the query and votes "commit" or "abort" by writing to its respective node.
Once the write completes, the other sites are notified, and as soon as all sites have all votes, they can decide either "abort" or "commit". Note that a node can decide "abort" earlier if some site votes for "abort".

An interesting aspect of this implementation is that the only role of the coordinator is to decide upon the group of sites, to create the ZooKeeper nodes, and to propagate the transaction to the corresponding sites.
In fact, even propagating the transaction can be done through ZooKeeper by writing it in the transaction node.

There are two important drawbacks of the approach described above. One is the message complexity, which is O(n²). The second is the impossibility of detecting failures of sites through ephemeral nodes.
To detect the failure of a site using ephemeral nodes, it is necessary that the site create the node.

To solve the first problem, you can have only the coordinator notified of changes to the transaction nodes, and then notify the sites once coordinator reaches a decision.
Note that this approach is scalable, but it's is slower too, as it requires all communication to go through the coordinator.

To address the second problem, you can have the coordinator propagate the transaction to the sites, and have each site creating its own ephemeral node.

### Leader Election

A simple way of doing leader election with ZooKeeper is to use the *SEQUENCE|EPHEMERAL* flags when creating znodes that represent "proposals" of clients.
The idea is to have a znode, say "/election", such that each znode creates a child znode "/election/n_" with both flags SEQUENCE|EPHEMERAL.
With the sequence flag, ZooKeeper automatically appends a sequence number that is greater that any one previously appended to a child of "/election".
The process that created the znode with the smallest appended sequence number is the leader.

To avoid the herd effect, it is sufficient to watch for the next znode down on the sequence of znodes.
If a client receives a notification that the znode it is watching is gone, then it becomes the new leader in the case that there is no smaller znode.
Note that this avoids the herd effect by not having all clients watching the same znode.

## Logging

Zookeeper uses slf4j as an abstraction layer for logging.

## Dynamic Reconfiguration

**Note:** Starting with 3.5.3, the dynamic reconfiguration feature is disabled by default, and has to be explicitly turned on via [reconfigEnabled](https://zookeeper.apache.org/doc/r3.8.0/zookeeperAdmin.html#sc_advancedConfiguration) configuration option.

## Links

- [Chubby](/docs/CS/Distributed/Chubby.md)

## References

1. [ZooKeeper: Wait-free coordination for Internet-scale systems](https://www.usenix.org/legacy/event/atc10/tech/full_papers/Hunt.pdf)
2. [How to do distributed locking](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html)
3. [Distributed Locks are Dead; Long Live Distributed Locks!](https://hazelcast.com/blog/long-live-distributed-locks/)
4. [ZooKeeper Programmer's Guide](https://zookeeper.apache.org/doc/current/zookeeperProgrammers.html)
5. [Dynamic Reconfiguration of Primary/Backup Clusters](https://www.usenix.org/system/files/conference/atc12/atc12-final74.pdf)
