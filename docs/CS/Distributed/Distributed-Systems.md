## Introduction

A distributed system is one in which components located at networked computers communicate and coordinate their actions only by passing messages.
This definition leads to the following especially significant characteristics of distributed systems: concurrency of components, lack of a global clock and independent failures of components.

Resources sharing as a main motivation for constructing distributed systems.
Resources may be managed by servers and accessed by clients or they may be encapsulated as objects and accessed by other client objects.

The challenges arising from the construction of distributed systems are the heterogeneity of their components, openness (which allows components to be added or replaced),
security, scalability – the ability to work well when the load or the number of users increases – failure handling, concurrency of components, transparency and providing quality of service.

[The 8 Fallacies of Distributed Computing](http://en.wikipedia.org/wiki/Fallacies_of_distributed_computing) are as follows:

1. The network is reliable
2. Latency is zero
3. Bandwidth is infinite
4. The network is secure
5. Topology doesn't change
6. There is one administrator
7. Transport cost is zero
8. The network is homogeneous

Notes on Data Base Operating Systems

The Two Generals Problem is provably unsolvable.

[The Byzantine Generals Problem](https://www.microsoft.com/en-us/research/uploads/prod/2016/12/The-Byzantine-Generals-Problem.pdf)

[A Critique of the CAP Theorem](https://www.cl.cam.ac.uk/research/dtg/www/files/publications/public/mk428/cap-critique.pdf)

[CAP Twelve Years Later:How the “Rules” Have Changed](https://www.anantjain.dev/aeb39daf1c8c1360d401e8afe84a00b7/cap-annotated.pdf)

[Consistency Tradeoffs in Modern Distributed Database System Design](https://www.cs.umd.edu/~abadi/papers/abadi-pacelc.pdf)

The default versions of Dynamo, Cassandra, and Riak are PA/EL systems: if a partition occurs, they give up consistency for availability, and under normal operation they give up consistency for lower latency.

### Consistency Model

> link [Jepsen Consistency Models](https://jepsen.io/consistency)

[Highly Available Transactions: Virtues and Limitations](http://www.vldb.org/pvldb/vol7/p181-bailis.pdf)

[Consistency in Non-Transactional Distributed Storage Systems](https://arxiv.org/pdf/1512.00168.pdf)

[Linearizability: A Correctness Condition for Concurrent Objects](https://cs.brown.edu/~mph/HerlihyW90/p463-herlihy.pdf)

Viotti and Vukolić rephrase this definition in terms of three set-theoretic constraints on histories:

- SingleOrder (there exists some total order of operations)
- RealTime (consistent with the real time bound)
- RVal (obeying the single-threaded laws of the associated object’s datatype)

[How to Make a Multiprocessor Computer That Correctly Executes Multiprocess Progranms](https://www.microsoft.com/en-us/research/uploads/prod/2016/12/How-to-Make-a-Multiprocessor-Computer-That-Correctly-Executes-Multiprocess-Programs.pdf)

Linearizability is one of the strongest single-object consistency models, and implies that every operation appears to take place atomically, in some order, consistent with the real-time ordering of those operations: e.g.,
if operation A completes before operation B begins, then B should logically take effect after A.

Viotti and Vukolić decompose sequential consistency into three properties:

- SingleOrder (there exists some total order of operations)
- PRAM
- RVal (the order must be consistent with the semantics of the datatype)

[Causal memory: definitions, implementation, and programming](https://www.cs.tau.ac.il/~orilahav/seminar18/causal.pdf)

Causal consistency captures the notion that causally-related operations should appear in the same order on all processes—though processes may disagree about the order of causally independent operations.

If you need total availability, you’ll have to give up causal (and read-your-writes), but can still obtain writes follow reads, monotonic reads, and monotonic writes.

NFS

Network File System

Two Generals’ Problem

One of the most prominent descriptions of an agreement in a distributed system is a thought experiment widely known as the *Two Generals’ Problem*.
This thought experiment shows that it is impossible to achieve an agreement between two parties if communication is asynchronous in the presence of link failures.

FLP Impossibility

Paper [Impossibility of Distributed Consensuswith One Faulty Process](https://dl.acm.org/doi/pdf/10.1145/3149.214121) assumes that processing is entirely asynchronous; there’s no shared notion of time between the processes.
Algorithms in such systems cannot be based on timeouts, and there’s no way for a process to find out whether the other process has crashed or is simply running too slow.
Given these assumptions, there exists no protocol that can guarantee consensus in a bounded time. No completely asynchronous consensus algorithm can tolerate the unannounced crash of even a single remote process.

If we do not consider an upper time bound for the process to complete the algorithm steps, process failures can’t be reliably detected, and there’s no deterministic algorithm to reach a consensus.
It means that we cannot always reach consensus in an asynchronous system in bounded time.
In practice, systems exhibit at least some degree of synchrony, and the solution to this problem requires a more refined model.

It is not always possible to solve a consensus problem in an asynchronous model.
Moreover, designing an efficient synchronous algorithm is not always achievable, and for some tasks the practical solutions are more likely to be time-dependent [Efficiency of Synchronous Versus Asynchronous Distributed Systems](https://dl.acm.org/doi/pdf/10.1145/2402.322387).

Failure Models

Crash Faults

Omission Faults

This model assumes that the process skips some of the algorithm steps, or is not able to execute them, or this execution is not visible to other participants, or it cannot send or receive messages to and from other participants.

Omission fault captures network partitions between the processes caused by faulty network links, switch failures, or network congestion.
Network partitions can be represented as omissions of messages between individual processes or process groups.
A crash can be simulated by completely omitting any messages to and from the process.

Arbitrary Faults

## Failure Detection

Terms such as dead, failed, and crashed are usually used to describe a process that has stopped executing its steps completely.
Terms such as unresponsive, faulty, and slow are used to describe suspected processes, which may actually be dead.

Failures may occur on the link level (messages between processes are lost or delivered slowly), or on the process level (the process crashes or is running slowly), and slowness may not always be distinguishable from failure.
This means there’s always a trade-off between wrongly suspecting alive processes as dead (producing false-positives), and delaying marking an unresponsive process as dead, giving it the benefit of doubt and expecting it to respond eventually (producing false-negatives).

A failure detector is a local subsystem responsible for identifying failed or unreachable processes to exclude them from the algorithm and guarantee liveness while preserving safety.

Liveness and safety are the properties that describe an algorithm’s ability to solve a specific problem and the correctness of its output.
More formally, liveness is a property that guarantees that a specific intended event must occur. For example, if one of the processes has failed, a failure detector must detect that failure.
Safety guarantees that unintended events will not occur.
For example, if a failure detector has marked a process as dead, this process had to be, in fact, dead.
From a practical perspective, excluding failed processes helps to avoid unnecessary work and prevents error propagation and cascading failures, while reducing availability when excluding potentially suspected alive processes.

[Proving the Correctness of Multiprocess Programs](http://www.cis.umassd.edu/~hxu/courses/cis481/references/Lamport-1977.pdf)

[Group membership failure detection: a simple protocol and its probabilistic analysis](https://iopscience.iop.org/article/10.1088/0967-1846/6/3/301/pdf)

[Unreliable failure detectors for reliable distributed systems](https://dl.acm.org/doi/pdf/10.1145/226643.226647)

Failure-detection algorithms should exhibit several essential properties.

- First of all, every nonfaulty member should eventually notice the process failure, and the algorithm should be able to make progress and eventually reach its final result.
  This property is called *completeness*.
- We can judge the quality of the algorithm by its efficiency: how fast the failure detector can identify process failures.
- Another way to do this is to look at the accuracy of the algorithm: whether or not the process failure was precisely detected.
  In other words, an algorithm is not accurate if it falsely accuses a live process of being failed or is not able to detect the existing failures.

We can think of the relationship between efficiency and accuracy as a tunable parameter: a more efficient algorithm might be less precise, and a more accurate algorithm is usually less efficient.
It is provably impossible to build a failure detector that is both accurate and efficient.
At the same time, failure detectors are allowed to produce false-positives (i.e., falsely identify live processes as failed and vice versa).

Failure detectors are an essential prerequisite and an integral part of many consensus and atomic broadcast algorithms.

Many distributed systems implement failure detectors by using heartbeats.
This approach is quite popular because of its simplicity and strong completeness.
Algorithms we discuss here assume the absence of Byzantine failures: processes do not attempt to intentionally lie about their state or states of their neighbors.

We will cover several algorithms for failure detection, each using a different approach: some focus on detecting failures by direct communication,
some use broadcast or gossip for spreading the information around, and some opt out by using quiescence (in other words, absence of communication) as a means of propagation.
We now know that we can use heartbeats or pings, hard deadlines, or continuous scales. Each one of these approaches has its own upsides: simplicity, accuracy, or precision.

### Heartbeats and Pings

We can query the state of remote processes by triggering one of two periodic processes:

- We can trigger a ping, which sends messages to remote processes, checking if they are still alive by expecting a response within a specified time period.
- We can trigger a heartbeat when the process is actively notifying its peers that it’s still running by sending messages to them.

We’ll use pings as an example here, but the same problem can be solved using heartbeats, producing similar results.
Each process maintains a list of other processes (alive, dead, and suspected ones) and updates it with the last response time for each process.
If a process fails to respond to a ping message for a longer time, it is marked as suspected.

Many failure-detection algorithms are based on heartbeats and timeouts.
For example, Akka, a popular framework for building distributed systems, has an implementation of a deadline failure detector, which uses heartbeats and reports a process failure if it has failed to register within a fixed time interval.

This approach has several potential downsides: its precision relies on the careful selection of ping frequency and timeout, and it does not capture process visibility from the perspective of other processes (see “Outsourced Heartbeats”).

#### Timeout-Free Failure Detector

Some algorithms avoid relying on timeouts for detecting failures.
For example, Heartbeat, a timeout-free failure detector [AGUILERA97], is an algorithm that only counts heartbeats and allows the application to detect process failures based on the data in the heartbeat counter vectors.
Since this algorithm is timeout-free, it operates under asynchronous system assumptions.”

#### Outsourced Heartbeats

An alternative approach, used by the Scalable Weakly Consistent Infection-style Process Group Membership Protocol (SWIM) [GUPTA01] is to use outsourced heartbeats to improve reliability using information about the process liveness from the perspective of its neighbors.
This approach does not require processes to be aware of all other processes in the network, only a subset of connected peers.”

### Phi-Accural Failure Detector

Instead of treating node failure as a binary problem, where the process can be only in two states: up or down, a phi-accrual (φ-accrual) failure detector [HAYASHIBARA04] has a continuous scale, capturing the probability of the monitored process’s crash. It works by maintaining a sliding window, collecting arrival times of the most recent heartbeats from the peer processes. This information is used to approximate arrival time of the next heartbeat, compare this approximation with the actual arrival time, and compute the suspicion level φ: how certain the failure detector is about the failure, given the current network conditions.

The algorithm works by collecting and sampling arrival times, creating a view that can be used to make a reliable judgment about node health.
It uses these samples to compute the value of φ: if this value reaches a threshold, the node is marked as down.
This failure detector dynamically adapts to changing network conditions by adjusting the scale on which the node can be marked as a suspect.

From the architecture perspective, a phi-accrual failure detector can be viewed as a combination of three subsystems:

- Monitoring
  Collecting liveness information through pings, heartbeats, or request-response sampling.
- Interpretation
  Making a decision on whether or not the process should be marked as suspected.
- Action
  A callback executed whenever the process is marked as suspected.

### Gossip and Failure Detection

Another approach that avoids relying on a single-node view to make a decision is a gossip-style failure detection service [VANRENESSE98], which uses gossip (see “Gossip Dissemination”) to collect and distribute states of neighboring processes.

Each member maintains a list of other members, their heartbeat counters, and timestamps, specifying when the heartbeat counter was incremented for the last time.
Periodically, each member increments its heartbeat counter and distributes its list to a random neighbor.
Upon the message receipt, the neighboring node merges the list with its own, updating heartbeat counters for the other neighbors.

Nodes also periodically check the list of states and heartbeat counters. If any node did not update its counter for long enough, it is considered failed.
This timeout period should be chosen carefully to minimize the probability of false-positives.
How often members have to communicate with each other (in other words, worst-case bandwidth) is capped, and can grow at most linearly with a number of processes in the system.

This way, we can detect crashed nodes, as well as the nodes that are unreachable by any other cluster member. This decision is reliable, since the view of the cluster is an aggregate from multiple nodes.
If there’s a link failure between the two hosts, heartbeats can still propagate through other processes.
Using gossip for propagating system states increases the number of messages in the system, but allows information to spread more reliably.

### Reversing Failure Detection Problem Statement

Since propagating the information about failures is not always possible, and propagating it by notifying every member might be expensive, one of the approaches,
called FUSE (failure notification service) [DUNAGAN04], focuses on reliable and cheap failure propagation that works even in cases of network partitions.

To detect process failures, this approach arranges all active processes in groups. If one of the groups becomes unavailable, all participants detect the failure.
In other words, every time a single process failure is detected, it is converted and propagated as a group failure. This allows detecting failures in the presence of any pattern of disconnects, partitions, and node failures.

Processes in the group periodically send ping messages to other members, querying whether they’re still alive.
If one of the members cannot respond to this message because of a crash, network partition, or link failure, the member that has initiated this ping will, in turn, stop responding to ping messages itself.

All failures are propagated through the system from the source of failure to all other participants. Participants gradually stop responding to pings, converting from the individual node failure to the group failure.

Here, we use the absence of communication as a means of propagation. An advantage of using this approach is that every member is guaranteed to learn about group failure and adequately react to it.
One of the downsides is that a link failure separating a single process from other ones can be converted to the group failure as well, but this can be seen as an advantage, depending on the use case.
Applications can use their own definitions of propagated failures to account for this scenario.

## Leader Election

Synchronization can be quite costly: if each algorithm step involves contacting each other participant, we can end up with a significant communication overhead.
This is particularly true in large and geographically distributed networks.
To reduce synchronization overhead and the number of message round-trips required to reach a decision, some algorithms rely on the existence of the leader (sometimes called coordinator) process, responsible for executing or coordinating steps of a distributed algorithm.

Generally, processes in distributed systems are uniform, and any process can take over the leadership role.
Processes assume leadership for long periods of time, but this is not a permanent role. Usually, the process remains a leader until it crashes.
After the crash, any other process can start a new election round, assume leadership, if it gets elected, and continue the failed leader’s work.

The liveness of the election algorithm guarantees that most of the time there will be a leader, and the election will eventually complete (i.e., the system should not be in the election state indefinitely).

Ideally, we’d like to assume safety, too, and guarantee there may be at most one leader at a time, and completely eliminate the possibility of a split brain situation (when two leaders serving the same purpose are elected but unaware of each other).
However, in practice, many leader election algorithms violate this agreement.

Leader processes can be used, for example, to achieve a total order of messages in a broadcast.
The leader collects and holds the global state, receives messages, and disseminates them among the processes.
It can also be used to coordinate system reorganization after the failure, during initialization, or when important state changes happen.

Election is triggered when the system initializes, and the leader is elected for the first time, or when the previous leader crashes or fails to communicate.
Election has to be deterministic: exactly one leader has to emerge from the process. This decision needs to be effective for all participants.

Even though leader election and distributed locking (i.e., exclusive ownership over a shared resource) might look alike from a theoretical perspective, they are slightly different.
If one process holds a lock for executing a critical section, it is unimportant for other processes to know who exactly is holding a lock right now, as long as the liveness property is satisfied (i.e., the lock will be eventually released, allowing others to acquire it).
In contrast, the elected process has some special properties and has to be known to all other participants, so the newly elected leader has to notify its peers about its role.

If a distributed locking algorithm has any sort of preference toward some process or group of processes, it will eventually starve nonpreferred processes from the shared resource, which contradicts the liveness property.
In contrast, the leader can remain in its role until it stops or crashes, and long-lived leaders are preferred.

Having a stable leader in the system helps to avoid state synchronization between remote participants, reduce the number of exchanged messages, and drive execution from a single process instead of requiring peer-to-peer coordination.
One of the potential problems in systems with a notion of leadership is that the leader can become a bottleneck.
To overcome that, many systems partition data in non-intersecting independent replica sets (see “Database Partitioning”). Instead of having a single system-wide leader, each replica set has its own leader.
One of the systems that uses this approach is [Spanner]().

Because every leader process will eventually fail, failure has to be detected, reported, and reacted upon: a system has to elect another leader to replace the failed one.

Some algorithms, such as [ZAB](), [Multi-Paxos](), or [Raft](), use temporary leaders to reduce the number of messages required to reach an agreement between the participants.
However, these algorithms use their own algorithm-specific means for leader election, failure detection, and resolving conflicts between the competing leader processes.

### Bully Algorithm

One of the leader election algorithms, known as the bully algorithm, uses process ranks to identify the new leader.
Each process gets a unique rank assigned to it. During the election, the process with the highest rank becomes a leader [MOLINA82].

This algorithm is known for its simplicity. The algorithm is named bully because the highest-ranked node “bullies” other nodes into accepting it.
It is also known as monarchial leader election: the highest-ranked sibling becomes a monarch after the previous one ceases to exist.

One of the apparent problems with this algorithm is that it violates the safety guarantee (that at most one leader can be elected at a time) in the presence of network partitions.
It is quite easy to end up in the situation where nodes get split into two or more independently functioning subsets, and each subset elects its leader. This situation is called split brain.

Another problem with this algorithm is a strong preference toward high-ranked nodes, which becomes an issue if they are unstable and can lead to a permanent state of reelection.
An unstable high-ranked node proposes itself as a leader, fails shortly thereafter, wins reelection, fails again, and the whole process repeats.
This problem can be solved by distributing host quality metrics and taking them into consideration during the election.

### Next-In-Line Failover

There are many versions of the bully algorithm that improve its various properties. For example, we can use multiple next-in-line alternative processes as a failover to shorten reelections [GHOLIPOUR09].

Each elected leader provides a list of failover nodes.
When one of the processes detects a leader failure, it starts a new election round by sending a message to the highest-ranked alternative from the list provided by the failed leader.
If one of the proposed alternatives is up, it becomes a new leader without having to go through the complete election round.

If the process that has detected the leader failure is itself the highest ranked process from the list, it can notify the processes about the new leader right away.

### Candidate/Ordinary Optimization

Another algorithm attempts to lower requirements on the number of messages by splitting the nodes into two subsets, candidate and ordinary, where only one of the candidate nodes can eventually become a leader [MURSHED12].

The ordinary process initiates election by contacting candidate nodes, collecting responses from them, picking the highest-ranked alive candidate as a new leader, and then notifying the rest of the nodes about the election results.

To solve the problem with multiple simultaneous elections, the algorithm proposes to use a tiebreaker variable δ, a process-specific delay, varying significantly between the nodes, that allows one of the nodes to initiate the election before the other ones.
The tiebreaker time is generally greater than the message round-trip time. Nodes with higher priorities have a lower δ, and vice versa.

### Invitation Algorithm

An invitation algorithm allows processes to “invite” other processes to join their groups instead of trying to outrank them.
This algorithm allows multiple leaders by definition, since each group has its own leader.

Each process starts as a leader of a new group, where the only member is the process itself.
Group leaders contact peers that do not belong to their groups, inviting them to join.
If the peer process is a leader itself, two groups are merged. Otherwise, the contacted process responds with a group leader ID, allowing two group leaders to establish contact and merge groups in fewer steps.

Since groups are merged, it doesn’t matter whether the process that suggested the group merge becomes a new leader or the other one does.
To keep the number of messages required to merge groups to a minimum, a leader of a larger group can become a leader for a new group.
This way only the processes from the smaller group have to be notified about the change of leader.

Similar to the other discussed algorithms, this algorithm allows processes to settle in multiple groups and have multiple leaders.
The invitation algorithm allows creating process groups and merging them without having to trigger a new election from scratch, reducing the number of messages required to finish the election.

### Ring Algorithm

In the ring algorithm [CHANG79], all nodes in the system form a ring and are aware of the ring topology (i.e., their predecessors and successors in the ring).
When the process detects the leader failure, it starts the new election. The election message is forwarded across the ring: each process contacts its successor (the next node closest to it in the ring).
If this node is unavailable, the process skips the unreachable node and attempts to contact the nodes after it in the ring, until eventually one of them responds.

Nodes contact their siblings, following around the ring and collecting the live node set, adding themselves to the set before passing it over to the next node,
similar to the failure-detection algorithm described in “Timeout-Free Failure Detector”, where nodes append their identifiers to the path before passing it to the next node.

[The Implementation of Reliable Distributed Multiprocess Systems](https://www.microsoft.com/en-us/research/uploads/prod/2016/12/The-Implementation-of-Reliable-Distributed-Multiprocess-Systems.pdf)

[Using Time Instead of Timeout for Fault-Tolerant Distributed Systems](https://www.microsoft.com/en-us/research/uploads/prod/2016/12/using-time-Copy.pdf)

[Synchronizing Clocks in the Presence of Faults](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/12/Synchronizing-Clocks-in-the-Presence-of-Faults.pdf)

[Byzantine Clock Synchronization](https://www.microsoft.com/en-us/research/uploads/prod/2016/12/Byzantine-Clock-Synchronization.pdf)


## Links

- [Operating Systems](/docs/CS/OS/OS.md)

## References

1. [Distributed Systems Concepts and Design Fifth Edition](https://www.cdk5.net/wp/)
2. [Mixu has a delightful book on distributed systems with incredible detail.](http://book.mixu.net/distsys/)
3. [Jeff Hodges has some excellent, production-focused advice.](https://www.somethingsimilar.com/2013/01/14/notes-on-distributed-systems-for-young-bloods/)
4. [The Fallacies of Distributed Computing is a classic text on mistaken assumptions we make designing distributed systems.](http://www.rgoarchitects.com/Files/fallacies.pdf)
5. [Christopher Meiklejohn has a list of key papers in distributed systems.](http://christophermeiklejohn.com/distributed/systems/2013/07/12/readings-in-distributed-systems.html)
6. [Dan Creswell has a lovely reading list.](https://dancres.github.io/Pages/)
