## Introduction

Amazon’s e-commerce system comprising on many services that communicate with each other to provide a rich set of functionalities.
Each service runs it’s own instance of Dynamo and operates under a set of assumptions which are as follows:

* Data access & update is done via a key-value based query model.
  This simplifies the interface for Dynamo as now it doesn’t need to provide complex query model that performs joins over multiple tables.
* There is a compromise on consistency of data stored on Dynamo nodes. Instead of strict consistency, applications using Dynamo as storage layer work with an eventual consistency model.
* Writes are given a higher priority in case of conflict resolution. With tight latency requirements, write requests are processed without resolving the conflict and all the conflicting states related to a key are preserved.
  Conflict resolution happens at read time based on policy such as last-write-wins or the resolution logic is moved to the client side.
* Every Dynamo node in a system is identical to other nodes in the same system.
  This means that there is no master node with extra responsibilities.
  This makes maintenance of nodes in a system much easier as compared to a typical master-replica model.

Going through each of these challenges, remember and try to appreciate the simple interface that Dynamo provides i.e.
`GET(key) & PUT(key, context, object)` as its simplicity plays a key role in solving these set of challenges. The `context` includes some metadata about the version of the `object`.

* Partitioning: In order to continue scaling the storage system, Dynamo needs to partition data over multiple nodes once the node reaches a certain threshold in terms of capacity.
  In order to perform this partitioning, Dynamo relies upon [Consistent Hashing](https://distributed-computing-musings.com/2022/01/partitioning-consistent-hashing/).
  Basic implementation of consistent hashing poses problems with non-uniform data distribution.
  Therefore Dynamo makes use of virtual nodes on top of consistent hashing ring in order to distribute data more uniformly across the ring.
* Replication: As high availability is a key requirement for Dynamo, any key that is persisted in the storage layer is stored across `N` nodes.
  This replication is performed by a coordinator that stores the key in node assigned to key in the ring according to consistent hashing algorithm and additionally replicate it to `N - 1` nodes in clockwise direction in the ring.
  The list of these `N` nodes responsible for storing the key is known as  *preference list* .
* Data Versioning: Dynamo focusses on providing eventual consistency and therefore a scenario where a `put()` operation succeeds without the update being persisted on all nodes is possible.
  Also Dynamo considers failure as a normal scenario and considers failures as an event rather than an exceptional state.
  These failures can be node failures or even partition failures due to network outage. Dynamo persists every update associated with a key even in state of failure and makes use of [vector clocks](https://distributed-computing-musings.com/2022/05/vector-clocks-keeping-time-in-check/) to find the correct ordering of updates associated with a key.
  This vector clock is used to find the causality among updates happening on a key on multiple nodes or partitions.
* Executing Database Operations: Any read/write operation in Dynamo is handled by a node also known as coordinator node.
  This node is the first accessible node among the top `N` nodes in *preference list* (Discussed in replication section).
  To perform the read/write operation coordinator node communicates with all `N` nodes in the* preference list. *Any node that is experiencing an outage or is unaccessible due to network failure is skipped.
  To maintain consistency, Dynamo uses a [quorum based approach](https://distributed-computing-musings.com/2022/01/replication-maintaining-a-quorum/) where it consists of two configurable parameters `R & W.`
  To maintain the quorum, `R` & `W` are set so that `R + W > N.`
* Handling Temporary Failures: Using a traditional quorum based approach, Dynamo runs a risk of sacrificing the availability of its storage system.
  The requirements for quorum can be broken in case nodes inside the *preference list *goes down or nodes in the list are unreachable due to partition failure.
  To overcome this, Dynamo makes use of [Sloppy Quorum &amp; Hinted hand-off.](https://distributed-computing-musings.com/2022/05/sloppy-quorum-and-hinted-handoff-quorum-in-the-times-of-failure/) Doing this all read & writes are performed on first `N` healthy nodes which may not be necessarily first `N` nodes on the hash ring.
* Handling Permanent Failures: Hinted handoff has an edge case where the node with hinted message might go down permanently before it has transmitted the message to original node. In this case we run into the risk of compromising the durability of our storage system.
  This might have a cascading effect where we end up with inconsistent data and might not realize the out of sync state before it is too late. To overcome this Dynamo makes use of [Merkle tree](https://en.wikipedia.org/wiki/Merkle_tree) which is an anti-entropy protocol.
  Merkle tree is also a well known concept in blockchain technology.
  Dynamo uses Merkle tree to detect inconsistencies among replica nodes and stop the spread of outdated data among replica nodes.
* Membership & Failure Detection: Dynamo uses a [gossip-based protocol](https://en.wikipedia.org/wiki/Gossip_protocol#:~:text=A%20gossip%20protocol%20or%20epidemic,all%20members%20of%20a%20group.) to provide a consistent view of nodes in the system to other nodes.
  So whenever a new node is added to the system or a node goes down, other nodes in the system communicate using this protocol to figure out the state of nodes in the storage system.
  The gossip based mechanism is also useful for failure detection. Information about nodes that are marked as failed is propagated to other nodes which can use this information to avoid unnecessary communication during database operations.

On a high-level, Dynamo comprises of three main components which are request coordination, membership & failure detection and local persistence engine.

## Learnings

There are a certain set of learnings that have come from building Dynamo and which has led to adding more improvements in the design of this data store.
Some of these learnings are as below:

* Though the primary focus of Dynamo is on availability, performance is also of essence at Amazon’s scale.
  Certain applications might have higher requirements for performance when dealing with critical user facing flow.
  Dynamo caters to this by providing an option to compromise on durability of data in exchange of an elevated performance.
  It is done by providing an in-memory buffer which stores the client updates and is written to storage layer at regular intervals.
  This also improves the read performance as now application will first read from this buffer and then route the request to storage if record is not found in buffer.
  This elevates the performance as now each update is not required to be persisted on disk in order to send a successful response
  but at the same time introduces a new set of challenges in terms of durability as now the node which holds the buffer can go down before the changes are persisted on storage node.
* Dynamo uses consistent hashing to store data across a set of nodes.
  With time these nodes can encounter an imbalance in traffic they are processing and this needs to be kept in check to maintain the overall health of system.
  Dynamo has provided a threshold percentage for load on any node and if a node crosses this threshold in terms of traffic it is serving then it is marked as out of balance.
  Dynamo’s partitioning methodology has evolved over time with focus towards distributing data across the nodes as evenly as possible.
* Some applications might require stronger hold on the consistency guarantees and therefore Dynamo provides the control of data consistency to developers by making `N, R & W `of the storage system configurable.
  So if your application requires strong consistency and you are ok with compromising the write traffic then you can set `W=N & R=1` as an extreme measure.
  Now an update needs to be posted on all nodes before you can send a successful response to client.
  On other extreme if you are ok stale results but want to make your write requests as fast as possible then you can set `W=1` so that write succeeds if it has been persisted on even a single node.
  All this control is with the developer so that they can update it on need to need basis.

## Links

## References

1. [Dynamo: Amazon’s Highly Available Key-value Store](https://www.allthingsdistributed.com/files/amazon-dynamo-sosp2007.pdf)
2. [Paper Notes: Dynamo – Amazon’s Highly Available Key-value Store](https://distributed-computing-musings.com/2022/05/paper-notes-dynamo-amazons-highly-available-key-value-store/)
