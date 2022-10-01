## Introduction

Consensus is a fundamental problem in fault-tolerant distributed systems.
Consensus is usually expressed in terms of agreement among a set of processes.
Consensus involves multiple servers agreeing on values. Once they reach a decision on a value, that decision is final.
Typical consensus algorithms make progress when any majority of their servers is available; for example, a cluster of 5 servers can continue to operate even if 2 servers fail.
If more servers fail, they stop making progress (but will never return an incorrect result).

Consensus typically arises in the context of replicated state machines, a general approach to building fault-tolerant systems.
Each server has a state machine and a log. The state machine is the component that we want to make fault-tolerant, such as a hash table.
It will appear to clients that they are interacting with a single, reliable state machine, even if a minority of the servers in the cluster fail.
Each state machine takes as input commands from its log. In our hash table example, the log would include commands like set x to 3.
A consensus algorithm is used to agree on the commands in the servers' logs.
The consensus algorithm must ensure that if any state machine applies set x to 3 as the nth command, no other state machine will ever apply a different nth command.
As a result, each state machine processes the same series of commands and thus produces the same series of results and arrives at the same series of states.

A fundamental problem in distributed computing and multi-agent systems is to achieve overall system reliability in the presence of a number of faulty processes.
This often requires coordinating processes to reach consensus, or agree on some data value that is needed during computation.
Example applications of consensus include agreeing on what transactions to commit to a database in which order, state machine replication, and atomic broadcasts.
Real-world applications often requiring consensus include cloud computing, clock synchronization, PageRank, opinion formation, smart power grids, state estimation, control of UAVs (and multiple robots/agents in general), load balancing, blockchain, and others.

For example, some possible uses of consensus are:

- deciding whether or not to commit a transaction to a database
- synchronising clocks by agreeing on the current time
- agreeing to move to the next stage of a distributed algorithm (this is the famous replicated state machine approach)
- electing a leader node to coordinate some higher-level protocol

## Consistency Model

There is some similarity between distributed consistency models and the hierarchy of [transaction isolation levels](/docs/CS/Transaction.md?id=Isolation-Levels).
But while there is some overlap, they are mostly independent concerns: transaction isolation is primarily about avoiding race conditions due to concurrently executing transactions,
whereas distributed consistency is mostly about coordinating the state of replicas in the face of delays and faults.

A consistency model is a set of histories.

> link [Jepsen Consistency Models](https://jepsen.io/consistency)

[Highly Available Transactions: Virtues and Limitations](http://www.vldb.org/pvldb/vol7/p181-bailis.pdf)

[Consistency in Non-Transactional Distributed Storage Systems](https://arxiv.org/pdf/1512.00168.pdf)

### Eventual Consistency

[Eventually Consistent - Revisited](https://www.allthingsdistributed.com/2008/12/eventually_consistent.html)

In “[Replication Lag](/docs/CS/Transaction.md?id=Replication-Lag)” we looked at some timing issues that occur in a replicated database.
If you look at two database nodes at the same moment in time, you’re likely to see different data on the two nodes, because write requests arrive on different nodes at different times.
These inconsistencies occur no matter what replication method the database uses (single-leader, multi-leader, or leaderless replication).

Most replicated databases provide at least eventual consistency, which means that if you stop writing to the database and wait for some unspecified length of time, then eventually all read requests will return the same value.
In other words, the inconsistency is temporary, and it eventually resolves itself (assuming that any faults in the network are also eventually repaired).
A better name for eventual consistency may be convergence, as we expect all replicas to eventually converge to the same value.

However, this is a very weak guarantee—it doesn’t say anything about when the replicas will converge.
Until the time of convergence, reads could return anything or nothing.
For example, if you write a value and then immediately read it again, there is no guarantee that you will see the value you just wrote, because the read may be routed to a different replica.

### Linearizability

In an eventually consistent database, if you ask two different replicas the same question at the same time, you may get two different answers. That’s confusing.
Wouldn’t it be a lot simpler if the database could give the illusion that there is only one replica (i.e., only one copy of the data)?
Then every client would have the same view of the data, and you wouldn’t have to worry about replication lag.

This is the idea behind *linearizability* (also known as *atomic consistency*, *strong consistency*, *immediate consistency*, or *external consistency*).
The basic idea is to make a system appear as if there were only one copy of the data, and all operations on it are atomic.
With this guarantee, even though there may be multiple replicas in reality, the application does not need to worry about them.

In a linearizable system, as soon as one client successfully completes a write, all clients reading from the database must be able to see the value just written.
Maintaining the illusion of a single copy of the data means guaranteeing that the value read is the most recent, up-to-date value, and doesn’t come from a stale cache or replica.
In other words, linearizability is a recency guarantee.

[Linearizability: A Correctness Condition for Concurrent Objects](https://cs.brown.edu/~mph/HerlihyW90/p463-herlihy.pdf)

Viotti and Vukolić rephrase this definition in terms of three set-theoretic constraints on histories:

- SingleOrder (there exists some total order of operations)
- RealTime (consistent with the real time bound)
- RVal (obeying the single-threaded laws of the associated object’s datatype)

[How to Make a Multiprocessor Computer That Correctly Executes Multiprocess Progranms](https://www.microsoft.com/en-us/research/uploads/prod/2016/12/How-to-Make-a-Multiprocessor-Computer-That-Correctly-Executes-Multiprocess-Programs.pdf)

Linearizability is one of the strongest single-object consistency models, and implies that every operation appears to take place atomically, in some order, consistent with the real-time ordering of those operations: e.g.,
if operation A completes before operation B begins, then B should logically take effect after A.

[Testing for Linearizability](http://www.cs.ox.ac.uk/people/gavin.lowe/LinearizabiltyTesting/paper.pdf)

[Faster linearizability checking via P-compositionality](https://arxiv.org/pdf/1504.00204.pdf)

#### Linearizability Versus Serializability

Linearizability is easily confused with [serializability](/docs/CS/Transaction.md?id=Serializability), as both words seem to mean something like “can be arranged in a sequential order.”
However, they are two quite different guarantees, and it is important to distinguish between them:

- Serializability is an isolation property of transactions, where every transaction may read and write multiple objects (rows, documents, records).
  It guarantees that transactions behave the same as if they had executed in some serial order (each transaction running to completion before the next transaction starts).
  It is okay for that serial order to be different from the order in which transactions were actually run.
- Linearizability is a recency guarantee on reads and writes of a register (an individual object).
  It doesn’t group operations together into transactions, so it does not prevent problems such as write skew (see “Write Skew and Phantoms” on page 246), unless you take additional measures such as materializing conflicts.

A database may provide both serializability and linearizability, and this combination is known as strict serializability or strong one-copy serializability (strong-1SR).
Implementations of serializability based on two-phase locking or actual serial execution are typically linearizable.
However, serializable snapshot isolation is not linearizable: by design, it makes reads from a consistent snapshot, to avoid lock contention between readers and writers.
The whole point of a consistent snapshot is that it does not include writes that are more recent than the snapshot, and thus reads from the snapshot are not linearizable.

#### Relying on Linearizability

##### Locking and leader election

A system that uses single-leader replication needs to ensure that there is indeed only
one leader, not several (split brain). One way of electing a leader is to use a lock: every
node that starts up tries to acquire the lock, and the one that succeeds becomes the
leader [14]. No matter how this lock is implemented, it must be linearizable: all nodes
must agree which node owns the lock; otherwise it is useless.
Coordination services like Apache ZooKeeper [15] and etcd [16] are often used to
implement distributed locks and leader election. They use consensus algorithms to
implement linearizable operations in a fault-tolerant way (we discuss such algorithms
later in this chapter, in “Fault-Tolerant Consensus” on page 364).iii There are still
many subtle details to implementing locks and leader election correctly (see for
example the fencing issue in “The leader and the lock” on page 301), and libraries like
Apache Curator [17] help by providing higher-level recipes on top of ZooKeeper.
However, a linearizable storage service is the basic foundation for these coordination
tasks.
Distributed locking is also used at a much more granular level in some distributed
databases, such as Oracle Real Application Clusters (RAC) [18]. RAC uses a lock per
disk page, with multiple nodes sharing access to the same disk storage system. Since
these linearizable locks are on the critical path of transaction execution, RAC deploy‐
ments usually have a dedicated cluster interconnect network for communication
between database nodes.

##### Constraints and uniqueness guarantees

Uniqueness constraints are common in databases: for example, a username or email
address must uniquely identify one user, and in a file storage service there cannot be
two files with the same path and filename. If you want to enforce this constraint as
the data is written (such that if two people try to concurrently create a user or a file
with the same name, one of them will be returned an error), you need linearizability.

This situation is actually similar to a lock: when a user registers for your service, you
can think of them acquiring a “lock” on their chosen username. The operation is also
very similar to an atomic compare-and-set, setting the username to the ID of the user
who claimed it, provided that the username is not already taken.
Similar issues arise if you want to ensure that a bank account balance never goes neg‐
ative, or that you don’t sell more items than you have in stock in the warehouse, or
that two people don’t concurrently book the same seat on a flight or in a theater.
These constraints all require there to be a single up-to-date value (the account bal‐
ance, the stock level, the seat occupancy) that all nodes agree on.
In real applications, it is sometimes acceptable to treat such constraints loosely (for
example, if a flight is overbooked, you can move customers to a different flight and
offer them compensation for the inconvenience). In such cases, linearizability may not be needed.

However, a hard uniqueness constraint, such as the one you typically find in rela‐
tional databases, requires linearizability. Other kinds of constraints, such as foreign
key or attribute constraints, can be implemented without requiring linearizability.

##### Cross-channel timing dependencies

#### Implementing Linearizable Systems

Now that we’ve looked at a few examples in which linearizability is useful, let’s think
about how we might implement a system that offers linearizable semantics.
Since linearizability essentially means “behave as though there is only a single copy of
the data, and all operations on it are atomic,” the simplest answer would be to really
only use a single copy of the data. However, that approach would not be able to toler‐
ate faults: if the node holding that one copy failed, the data would be lost, or at least
inaccessible until the node was brought up again.

The most common approach to making a system fault-tolerant is to use replication.
Let’s revisit the replication methods from Chapter 5, and compare whether they can
be made linearizable:
- Single-leader replication (potentially linearizable)
In a system with single-leader replication (see “Leaders and Followers” on page
152), the leader has the primary copy of the data that is used for writes, and the
followers maintain backup copies of the data on other nodes. If you make reads
from the leader, or from synchronously updated followers, they have the poten‐
tial to be linearizable.iv However, not every single-leader database is actually line‐
arizable, either by design (e.g., because it uses snapshot isolation) or due to
concurrency bugs [10].
Using the leader for reads relies on the assumption that you know for sure who
the leader is. As discussed in “The Truth Is Defined by the Majority” on page
300, it is quite possible for a node to think that it is the leader, when in fact it is
not—and if the delusional leader continues to serve requests, it is likely to violate
linearizability [20]. With asynchronous replication, failover may even lose com‐
mitted writes (see “Handling Node Outages” on page 156), which violates both
durability and linearizability.
- Consensus algorithms (linearizable)
Some consensus algorithms, which we will discuss later in this chapter, bear a
resemblance to single-leader replication. However, consensus protocols contain
measures to prevent split brain and stale replicas. Thanks to these details, con‐
sensus algorithms can implement linearizable storage safely. This is how Zoo‐
Keeper [21] and etcd [22] work, for example.
- Multi-leader replication (not linearizable)
Systems with multi-leader replication are generally not linearizable, because they
concurrently process writes on multiple nodes and asynchronously replicate
them to other nodes. For this reason, they can produce conflicting writes that
require resolution (see “Handling Write Conflicts” on page 171). Such conflicts
are an artifact of the lack of a single copy of the data.
- Leaderless replication (probably not linearizable)
For systems with leaderless replication (Dynamo-style; see “Leaderless Replica‐
tion” on page 177), people sometimes claim that you can obtain “strong consis‐
tency” by requiring quorum reads and writes (w + r > n). Depending on the exact configuration of the quorums, and depending on how you define strong consis‐
tency, this is not quite true.
“Last write wins” conflict resolution methods based on time-of-day clocks (e.g.,
in Cassandra; see “Relying on Synchronized Clocks” on page 291) are almost cer‐
tainly nonlinearizable, because clock timestamps cannot be guaranteed to be
consistent with actual event ordering due to clock skew. Sloppy quorums
(“Sloppy Quorums and Hinted Handoff” on page 183) also ruin any chance of
linearizability. Even with strict quorums, nonlinearizable behavior is possible, as
demonstrated in the next section

#### The CAP theorem

[CAP Theory](/docs/CS/Distributed/CAP.md)


### Sequential Consistency

Viotti and Vukolić decompose sequential consistency into three properties:

- SingleOrder (there exists some total order of operations)
- PRAM
- RVal (the order must be consistent with the semantics of the datatype)

### Causal consistency

[Causal memory: definitions, implementation, and programming](https://www.cs.tau.ac.il/~orilahav/seminar18/causal.pdf)

Causal consistency captures the notion that causally-related operations should appear in the same order on all processes—though processes may disagree about the order of causally independent operations.

If you need total availability, you’ll have to give up causal (and read-your-writes), but can still obtain writes follow reads, monotonic reads, and monotonic writes.

NFS

Network File System

## Problem description

The consensus problem requires agreement among a number of processes (or agents) for a single data value.
Some of the processes (agents) may fail or be unreliable in other ways, so consensus protocols must be fault tolerant or resilient.
The processes must somehow put forth their candidate values, communicate with one another, and agree on a single consensus value.

The consensus problem is a fundamental problem in control of multi-agent systems.
One approach to generating consensus is for all processes (agents) to agree on a majority value.
In this context, a majority requires at least one more than half of available votes (where each process is given a vote).
However, one or more faulty processes may skew the resultant outcome such that consensus may not be reached or reached incorrectly.

Protocols that solve consensus problems are designed to deal with limited numbers of faulty processes.
These protocols must satisfy a number of requirements to be useful. For instance, a trivial protocol could have all processes output binary value 1.
This is not useful and thus the requirement is modified such that the output must somehow depend on the input. That is, the output value of a consensus protocol must be the input value of some process.
Another requirement is that a process may decide upon an output value only once and this decision is irrevocable. A process is called correct in an execution if it does not experience a failure.
A consensus protocol tolerating halting failures must satisfy the following properties.

- **Termination**
  Eventually, every correct process decides some value.
- **Validity**
  The value that has been decided must have proposed by some process.
- **Agreement**
  Every correct process must agree on the same value.

A protocol that can correctly guarantee consensus amongst n processes of which at most t fail is said to be t-resilient.

In evaluating the performance of consensus protocols two factors of interest are running time and message complexity.
Running time is given in Big O notation in the number of rounds of message exchange as a function of some input parameters (typically the number of processes and/or the size of the input domain).
Message complexity refers to the amount of message traffic that is generated by the protocol.
Other factors may include memory usage and the size of messages.

We characterize it in terms of three classes of agents:

- **Proposers** A proposer can propose a value.
- **Acceptors** The acceptors cooperate in some way to choose a single proposed value.
- **Learners** A learner can learn what value has been chosen.

In the traditional statement, each process is a proposer, an acceptor, and a learner.
However, in a distributed client/server system, we can also consider the clients to be the proposers and learners, and the servers to be the acceptors.

The consensus problem is characterized by the following three requirements, where N is the number of acceptors and F is the number of acceptors that must be allowed to fail without preventing progress.

- **Nontriviality** Only a value proposed by a proposer can be learned.
- **Safety** At most one value can be learned.
- **Liveness** If a proposer p, a learner l, and a set of N − F acceptors are non-faulty and can communicate with one another, and if p proposes a value, then l will eventually learn a value.

Nontriviality and safety must be maintained even if at most M of the acceptors are malicious, and even if proposers are malicious.
By definition, a learner is non-malicious, so the conditions apply only to non-malicious learners.
A malicious acceptor by definition has failed, so the N − F acceptors in the liveness condition do not include malicious ones.
Note that M is the maximum number of failures under which safety is preserved, while F is the maximum number of failures under which liveness is ensured.
These parameters are, in principle, independent. Hitherto, the only cases considered have been M = 0 (non-Byzantine) and M = F (Byzantine).
If malicious failures are expected to be rare but not ignorable, we may assume 0 < M < F.
If safety is more important than liveness, we might assume F < M .

The classic Fischer, Lynch, Paterson result(**FLP**) implies that no purely asynchronous algorithm can solve consensus.
However, we interpret “can communicate with one another” in the liveness requirement to include a synchrony requirement.
Thus, nontriviality and safety must be maintained in any case; liveness is required only if the system eventually behaves synchronously.
Dwork, Lynch, and Stockmeyer([Consensus in the Presence of Partial Synchrony](https://dl.acm.org/doi/pdf/10.1145/42282.42283)) showed the existence of an algorithm satisfying these requirements.

Here are approximate lower-bound results for an asynchronous consensus algorithm. Their precise statements and proofs will appear later.

> **Approximate Theorem 1**
>
> If there are at least two proposers, or one malicious proposer, then N > 2F + M .

> **Approximate Theorem 2**
>
> If there are at least two proposers, or one malicious proposer, then there is at least a 2-message delay between the proposal of a value and the learning of that value.

> **Approximate Theorem 3**
>
> - If there are at least two proposers whose proposals can be learned with a 2-message delay despite the failure of Q acceptors, or there is one such possibly malicious proposer that is not an acceptor, then N > 2Q + F + 2M .
> - If there is a single possibly malicious proposer that is also an acceptor, and whose proposals can be learned with a 2-message delay despite the failure of Q acceptors, then N > max(2Q + F + 2M − 2, Q + F + 2M ).

These results are approximate because there are special cases in which the bounds do not hold.
For example, Approximate Theorem 1 does not hold in the case of three distinct processes: one process that is a proposer and an acceptor, one process that is an acceptor and a learner, and one process that is a proposer and a learner.
In this case, there is an asynchronous consensus algorithm with N = 2, F = 1, and M = 0.

The first theorem is fairly obvious when M = 0 and has been proved in several settings. For M = F, it was proved in the [original Byzantine agreement paper](https://lamport.azurewebsites.net/pubs/reaching.pdf).

## Models of computation

Varying models of computation may define a "consensus problem". Some models may deal with fully connected graphs, while others may deal with rings and trees.
In some models message authentication is allowed, whereas in others processes are completely anonymous. Shared memory models in which processes communicate by accessing objects in shared memory are also an important area of research.

### Communication channels with direct or transferable authentication

In most models of communication protocol participants communicate through authenticated channels.
This means that messages are not anonymous, and receivers know the source of every message they receive.
Some models assume a stronger, transferable form of authentication, where each message is signed by the sender, so that a receiver knows not just the immediate source of every message, but the participant that initially created the message.
This stronger type of authentication is achieved by digital signatures, and when this stronger form of authentication is available, protocols can tolerate a larger number of faults.

The two different authentication models are often called oral communication and written communication models.
In an oral communication model, the immediate source of information is known, whereas in stronger, written communication models, every step along the receiver learns not just the immediate source of the message, but the communication history of the message.

### Inputs and outputs of consensus

In the most traditional single-value consensus protocols such as Paxos, cooperating nodes agree on a single value such as an integer, which may be of variable size so as to encode useful metadata such as a transaction committed to a database.

A special case of the single-value consensus problem, called binary consensus, restricts the input, and hence the output domain, to a single binary digit {0,1}.
While not highly useful by themselves, binary consensus protocols are often useful as building blocks in more general consensus protocols, especially for asynchronous consensus.

In multi-valued consensus protocols such as Multi-Paxos and Raft, the goal is to agree on not just a single value but a series of values over time, forming a progressively-growing history.
While multi-valued consensus may be achieved naively by running multiple iterations of a single-valued consensus protocol in succession, many optimizations and other considerations such as reconfiguration support can make multi-valued consensus protocols more efficient in practice.

## Crash and Byzantine failures

There are two types of failures a process may undergo, a crash failure or a Byzantine failure.
A crash failure occurs when a process abruptly stops and does not resume.
Byzantine failures are failures in which absolutely no conditions are imposed.
For example, they may occur as a result of the malicious actions of an adversary.
A process that experiences a Byzantine failure may send contradictory or conflicting data to other processes, or it may sleep and then resume activity after a lengthy delay.
Of the two types of failures, Byzantine failures are far more disruptive.

Thus, a consensus protocol tolerating Byzantine failures must be resilient to every possible error that can occur.

A stronger version of consensus tolerating Byzantine failures is given by strengthening the Integrity constraint:

**Integrity**
If a correct process decides v, then v must have been proposed by some correct process.

### Asynchronous and synchronous systems

The consensus problem may be considered in the case of asynchronous or synchronous systems.
While real world communications are often inherently asynchronous, it is more practical and often easier to model synchronous systems, given that asynchronous systems naturally involve more issues than synchronous ones.

In synchronous systems, it is assumed that all communications proceed in rounds. In one round, a process may send all the messages it requires, while receiving all messages from other processes.
In this manner, no message from one round may influence any messages sent within the same round.

## FLP Impossibility

Paper [Impossibility of Distributed Consensuswith One Faulty Process](https://dl.acm.org/doi/pdf/10.1145/3149.214121) assumes that processing is entirely asynchronous; there’s no shared notion of time between the processes.
Algorithms in such systems cannot be based on timeouts, and there’s no way for a process to find out whether the other process has crashed or is simply running too slow.
Given these assumptions, there exists no protocol that can guarantee consensus in a bounded time.
No completely asynchronous consensus algorithm can tolerate the unannounced crash of even a single remote process.

If we do not consider an upper time bound for the process to complete the algorithm steps, process failures can’t be reliably detected, and there’s no deterministic algorithm to reach a consensus.
It means that we cannot always reach consensus in an asynchronous system in bounded time.
In practice, systems exhibit at least some degree of synchrony, and the solution to this problem requires a more refined model.

The FLP result is based on the asynchronous model, which is actually a class of models which exhibit certain properties of timing.
The main characteristic of asynchronous models is that there is no upper bound on the amount of time processors may take to receive, process and respond to an incoming message.
Therefore it is impossible to tell if a processor has failed, or is simply taking a long time to do its processing. The asynchronous model is a weak one, but not completely physically unrealistic.
We have all encountered web servers that seem to take an arbitrarily long time to serve us a page.
Now that mobile ad-hoc networks are becoming more and more pervasive, we see that devices in those networks may power down during processing to save battery, only to reappear later and continue as though nothing had happened.
This introduces an arbitrary delay which fits the asynchronous model.

It is not always possible to solve a consensus problem in an asynchronous model.
Moreover, designing an efficient synchronous algorithm is not always achievable, and for some tasks the practical solutions are more likely to be time-dependent [Efficiency of Synchronous Versus Asynchronous Distributed Systems](https://dl.acm.org/doi/pdf/10.1145/2402.322387).

- Failure Models
- Crash Faults
- Omission Faults

This model assumes that the process skips some of the algorithm steps, or is not able to execute them, or this execution is not visible to other participants, or it cannot send or receive messages to and from other participants.

Omission fault captures network partitions between the processes caused by faulty network links, switch failures, or network congestion.
Network partitions can be represented as omissions of messages between individual processes or process groups.
A crash can be simulated by completely omitting any messages to and from the process.

Arbitrary Faults

Avoid FLP:

- Fault Masking
- Failure Detectors
- Non-Determinism

In a fully asynchronous message-passing distributed system, in which at least one process may have a crash failure, it has been proven in the famous FLP impossibility result that a deterministic algorithm for achieving consensus is impossible.
This impossibility result derives from worst-case scheduling scenarios, which are unlikely to occur in practice except in adversarial situations such as an intelligent denial-of-service attacker in the network.
In most normal situations, process scheduling has a degree of natural randomness.

In an asynchronous model, some forms of failures can be handled by a synchronous consensus protocol.
For instance, the loss of a communication link may be modeled as a process which has suffered a Byzantine failure.

Randomized consensus algorithms can circumvent the FLP impossibility result by achieving both safety and liveness with overwhelming probability,
even under worst-case scheduling scenarios such as an intelligent denial-of-service attacker in the network.

### Failure Detectors

properties of failure detectors:

- Completeness
- Accuracy

Eventually Weakly Failure Detector

- Eventually Weakly Complete
- Eventually Weakly Accurate

## Permissioned versus permissionless consensus

Consensus algorithms traditionally assume that the set of participating nodes is fixed and given at the outset:
that is, that some prior (manual or automatic) configuration process has permissioned a particular known group of participants who can authenticate each other as members of the group.
In the absence of such a well-defined, closed group with authenticated members, a Sybil attack against an open consensus group can defeat even a Byzantine consensus algorithm,
simply by creating enough virtual participants to overwhelm the fault tolerance threshold.

A permissionless consensus protocol, in contrast, allows anyone in the network to join dynamically and participate without prior permission,
but instead imposes a different form of artificial cost or barrier to entry to mitigate the Sybil attack threat.
Bitcoin introduced the first permissionless consensus protocol using proof of work and a difficulty adjustment function, in which participants compete to solve cryptographic hash puzzles,
and probabilistically earn the right to commit blocks and earn associated rewards in proportion to their invested computational effort.
Motivated in part by the high energy cost of this approach, subsequent permissionless consensus protocols have proposed or adopted other alternative participation rules for Sybil attack protection,
such as proof of stake, proof of space, and proof of authority.

[On Optimal Probabilistic Asynchronous Byzantine Agreement]()

## Consensus Algorithms

### Replicated State Machines

Replicated state machines are typically implemented using a replicated log, as shown in Figure 1.
Each server stores a log containing a series of commands, which its state machine executes in order.
Each log contains the same commands in the same order, so each state machine processes the same sequence of commands.
Since the state machines are deterministic, each computes the same state and the same sequence of outputs.

<div style="text-align: center;">

![Fig.1. Replicated state machine architecture](./img/Replicated-State-Machine.png)

</div>

<p style="text-align: center;">

Fig.1. Replicated state machine architecture.
The consensus algorithm manages a replicated log containing state machine commands from clients.
The state machines process identical sequences of commands from the logs, so they produce the same outputs.

</p>

Keeping the replicated log consistent is the job of the consensus algorithm.
The consensus module on a server receives commands from clients and adds them to its log.
It communicates with the consensus modules on other servers to ensure that every log eventually contains the same requests in the same order, even if some servers fail.
Once commands are properly replicated, each server’s state machine processes them in log order, and the outputs are returned to clients.
As a result, the servers appear to form a single, highly reliable state machine.

### 2PC

Consensus is easy if there are no faults.

As its name suggests, 2PC operates in two distinct phases.

- The first proposal phase involves proposing a value to every participant in the system and gathering responses.
- The second commit-or-abort phase communicates the result of the vote to the participants and tells them either to go ahead and decide or abort the protocol.

The process that proposes values is called the coordinator, and does not have to be specially elected - any node can act as the coordinator if they want to and therefore initiate a round of 2PC.

There is a fly in 2PC’s ointment. If nodes are allowed to fail - if even a single node can fail - then things get a good deal more complicated.

2PC is still a very popular consensus protocol, because it has a low message complexity (although in the failure case, if every node decides to be the recovery node the complexity can go to $O(n^2)$.
A client that talks to the co-ordinator can have a reply in 3 message delays’ time. This low latency is very appealing for some applications.

However, the fact the 2PC can block on co-ordinator failure is a significant problem that dramatically hurts availability.
If transactions can be rolled back at any time, then the protocol can recover as nodes time out, but if the protocol has to respect any commit decisions as permanent, the wrong failure can bring the whole thing to a juddering halt.

The fundamental difficulty with 2PC is that, once the decision to commit has been made by the co-ordinator and communicated to some replicas, the replicas go right ahead and act upon the commit statement without checking to see if every other replica got the message.
Then, if a replica that committed crashes along with the co-ordinator, the system has no way of telling what the result of the transaction was (since only the co-ordinator and the replica that got the message know for sure).
Since the transaction might already have been committed at the crashed replica, the protocol cannot pessimistically abort - as the transaction might have had side-effects that are impossible to undo.
Similarly, the protocol cannot optimistically force the transaction to commit, as the original vote might have been to abort.

[Notes on Data Base Operating Systems](http://jimgray.azurewebsites.net/papers/dbos.pdf)

[A brief history of Consensus, 2PC and Transaction Commit](https://betathoughts.blogspot.com/2007/06/brief-history-of-consensus-2pc-and.html)

### 3PC

This problem is - mostly - circumvented by the addition of an extra phase to 2PC, unsurprisingly giving us a three-phase commit protocol.
The idea is very simple. We break the second phase of 2PC - ‘commit’ - into two sub-phases. The first is the ‘prepare to commit’ phase.
The co-ordinator sends this message to all replicas when it has received unanimous ‘yes’ votes in the first phase.
On receipt of this messages, replicas get into a state where they are able to commit the transaction - by taking necessary locks and so forth - but crucially do not do any work that they cannot later undo.
They then reply to the co-ordinator telling it that the ‘prepare to commit’ message was received.

The purpose of this phase is to communicate the result of the vote to every replica so that the state of the protocol can be recovered no matter which replica dies.

The last phase of the protocol does almost exactly the same thing as the original ‘commit or abort’ phase in 2PC.
If the co-ordinator receives confirmation of the delivery of the ‘prepare to commit’ message from all replicas, it is then safe to go ahead with committing the transaction.
However, if delivery is not confirmed, the co-ordinator cannot guarantee that the protocol state will be recovered should it crash (if you are tolerating a fixed number ff of failures, the co-ordinator can go ahead once it has received f+1f+1 confirmations).
In this case, the co-ordinator will abort the transaction.

If the co-ordinator should crash at any point, a recovery node can take over the transaction and query the state from any remaining replicas.
If a replica that has committed the transaction has crashed, we know that every other replica has received a ‘prepare to commit’ message (otherwise the co-ordinator wouldn’t have moved to the commit phase),
and therefore the recovery node will be able to determine that the transaction was able to be committed, and safely shepherd the protocol to its conclusion.
If any replica reports to the recovery node that it has not received ‘prepare to commit’, the recovery node will know that the transaction has not been committed at any replica, and will therefore be able either to pessimistically abort or re-run the protocol from the beginning.

So does 3PC fix all our problems? Not quite, but it comes close.
In the case of a network partition, the wheels rather come off - imagine that all the replicas that received ‘prepare to commit’ are on one side of the partition, and those that did not are on the other.
Then both partitions will continue with recovery nodes that respectively commit or abort the transaction, and when the network merges the system will have an inconsistent state.
So 3PC has potentially unsafe runs, as does 2PC, but will always make progress and therefore satisfies its liveness properties.
The fact that 3PC will not block on single node failures makes it much more appealing for services where high availability is more important than low latencies.

3PC in fact only works well in a synchronous network with crash-stop failures.

[NonBlocking Commit Protocols](https://www.cs.cornell.edu/courses/cs614/2004sp/papers/Ske81.pdf)

### Paxos

[Paxos](/docs/CS/Distributed/Paxos.md) is a family of distributed algorithms used to reach consensus.

### Raft

[Raft](/docs/CS/Distributed/Raft.md) is a consensus algorithm that is designed to be easy to understand.

### ZAB

### PBFT

Standard consensus algorithms won’t do as they themselves are not Byzantine fault tolerant.

[Practical Byzantine Fault Tolerance and Proactive Recovery](https://www.microsoft.com/en-us/research/wp-content/uploads/2017/01/p398-castro-bft-tocs.pdf)

[A Comparison of the Byzantine Agreement Problem and the Transaction Commit Problem](http://jimgray.azurewebsites.net/papers/tandemtr88.6_comparisonofbyzantineagreementandtwophasecommit.pdf)

## Links

- [Distributed Systems](/docs/CS/Distributed/Distributed_Systems.md)

## References

1. [How to Build a Highly Available System Using Consensus](https://www.microsoft.com/en-us/research/uploads/prod/1996/10/Acrobat-58-Copy.pdf)
2. [Uniform consensus is harder than consensus](https://infoscience.epfl.ch/record/88273/files/CBS04.pdf?version=1)
3. [Impossibility of Distributed Consensus with One Faulty Process](https://groups.csail.mit.edu/tds/papers/Lynch/jacm85.pdf)
4. [Lower Bounds for Asynchronous Consensus](http://lamport.azurewebsites.net/pubs/lower-bound.pdf)
5. [Lower Bounds for Asynchronous Consensus](http://lamport.azurewebsites.net/pubs/bertinoro.pdf)
6. [Consensus on Transaction Commit](https://www.microsoft.com/en-us/research/uploads/prod/2004/01/twophase-revised.pdf)
