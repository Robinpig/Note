## Introduction

It is impossible for a distributed computer system to simultaneously provide all three of the following guarantees:

- **Consistency**: all nodes see the same data at the same time
- **Availability**: Node failures do not prevent other survivors from continuing to operate (a guarantee that every request receives a response about whether it succeeded or failed)
- **Partition tolerance**: the system continues to operate despite arbitrary partitioning due to network failures (e.g., message loss)

A distributed system can satisfy any two of these guarantees at the same time but not all three.
We would like to achieve both consistency and availability while tolerating network partitions.
The network can get split into several parts where processes are not able to communicate with each other: some of the messages sent between partitioned nodes won’t reach their destinations.

The easiest way to understand CAP is to think of two nodes on opposite sides of a partition.
Allowing at least one node to update state will cause the nodes to become inconsistent, thus forfeiting C.
Likewise, if the choice is to preserve consistency, one side of the partition must act as if it is unavailable, thus forfeiting A.
Only when nodes communicate is it possible to preserve both consistency and availability, thereby forfeiting P.
The general belief is that for wide-area systems, designers cannot forfeit P and therefore have a difficult choice between C and A.
In some sense, the NoSQL movement is about creating choices that focus on availability first and consistency second; databases that adhere to ACID properties (atomicity, consistency, isolation, and durability) do the opposite.

> The choice of availability over consistency is a business choice, not a technical one.    -- Coda Hale

## BASE

ACID and BASE represent two design philosophies at opposite ends of the consistency-availability spectrum.
The ACID properties focus on consistency and are the traditional approach of databases.

Although both terms are more mnemonic than precise, the BASE acronym (being second) is a bit more awkward: Basically Available, Soft state, Eventually consistent.
Soft state and eventual consistency are techniques that work well in the presence of partitions and thus promote availability.
The relationship between CAP and ACID is more complex and often misunderstood, in part because the C and A in ACID represent different concepts than the same letters in CAP and in part because choosing availability affects  only some of the ACID guarantees.
The four ACID properties are:

- Atomicity (A).
  All systems benefit from atomic operations.
  When the focus is availability, both sides of a partition should still use atomic operations.
  Moreover, higher-level atomic operations(the kind that ACID implies) actually simplify recovery.
- Consistency (C).
  In ACID, the C means that a transaction preserves all the database rules, such as unique keys.
  In contrast, the C in CAP refers only to single‐copy consistency, a strict subset of ACID consistency.
  ACID consistency also cannot be maintained across partitions—partition recovery will need to restore ACID consistency.
  More generally, maintaining invariants during partitions might be impossible, thus the need for careful thought about which operations to disallow and how to restore invariants during recovery.
- Isolation (I).
  Isolation is at the core of the CAP theorem: if the system requires ACID isolation, it can operate on at most one side during a partition.
  Serializability requires communication in general and thus fails across partitions.
  Weaker definitions of correctness are viable across partitions via compensation during partition recovery.
- Durability (D). As with atomicity, there is no reason to forfeit durability, although the developer might choose to avoid needing it via soft state (in the style of BASE) due to its expense.
  A subtle point is that, during partition recovery, it is possible to reverse durable operations that unknowingly violated an invariant during the operation.
  However, at the time of recovery, given a durable history from both sides, such operations can be detected and corrected.
  In general, running ACID transactions on each side of a partition makes recovery easier and enables a framework for compensating transactions that can be used for recovery from a partition.

Availability requirement is impossible to satisfy in an asynchronous system, and we cannot implement a system that simultaneously guarantees both availability and consistency in the presence of network partitions [GILBERT02].
We can build systems that guarantee strong consistency while providing best effort availability, or guarantee availability while providing best effort consistency [GILBERT12].
Best effort here implies that if everything works, the system will not purposefully violate any guarantees, but guarantees are allowed to be weakened and violated in the case of network partitions.

An example of a CP system is an implementation of a consensus algorithm, requiring a majority of nodes for progress: always consistent, but might be unavailable in the case of a network partition.
A database always accepting writes and serving reads as long as even a single replica is up is an example of an AP system, which may end up losing data or serving inconsistent results.

### Eventually Consistent

[Eventually Consistent - Revisited](https://www.allthingsdistributed.com/2008/12/eventually_consistent.html)


## PACELEC

PACELEC conjecture an extension of CAP, states that in presence of network partitions there’s a choice between consistency and availability (PAC).
Else (E), even if the system is running normally, we still have to make a choice between latency and consistency.

The latency-consistency tradeoff (ELC) is relevant only when the data is replicated.

Default versions of Dynamo, Cassandra, and Riak were PA/EL systems, i.e., if a partition occurs, availability is prioritized. In the absence of partition, lower latency is prioritized.

Fully ACID systems (VoltDB, H-Store, and Megastore) and others like BigTable and HB are PC/EC, i.e., they prioritize consistency and give up availability and latency.

MongoDB can be classified as a PA/EC system.

[Consistency Tradeoffs in Modern Distributed Database System Design](https://www.cs.umd.edu/~abadi/papers/abadi-pacelc.pdf)



## Trade-off

As the “CAP Confusion” sidebar explains, the “2 of 3” view is misleading on several fronts.

- First, because partitions are rare, there is little reason to forfeit C or A when the system is not partitioned.
- Second, the choice between C and A can occur many times within the same system at very fine granularity; not only can subsystems make different choices, but the choice can change according to the operation or even the specific data or user involved.
- Finally, all three properties are more continuous than binary.
  Availability is obviously continuous from 0 to 100 percent, but there are also many levels of consistency, and even partitions have nuances, including disagreement within the system about whether a partition exists.

Exploring these nuances requires pushing the traditional way of dealing with partitions, which is the fundamental challenge.
Because partitions are rare, CAP should allow perfect C and A most of the time, but when partitions are present or perceived, a strategy that detects partitions and explicitly accounts for them is in order.
This strategy should have three steps: detect partitions, enter an explicit partition mode that can limit some operations, and initiate a recovery process to restore consistency and compensate for mistakes made during a partition.

Operationally, the essence of CAP takes place during a timeout, a period when the program must make a fundamental decision—the partition decision:

- cancel the operation and thus decrease availability, or
- proceed with the operation and thus risk inconsistency.

Retrying communication to achieve consistency, for example, via Paxos or a two-phase commit, just delays the decision.
At some point the program must make the decision; retrying communication indefinitely is in essence choosing C over A.

Thus, pragmatically, a partition is a time bound on communication.
Failing to achieve consistency within the time bound implies a partition and thus a choice between C and A for this operation.
These concepts capture the core design issue with regard to latency: are two sides moving forward without communication?

This pragmatic view gives rise to several important consequences.

- The first is that there is no global notion of a partition, since some nodes might detect a partition, and others might not.
- The second consequence is that nodes can detect a partition and enter a partition mode—a central part of optimizing C and A.
- Finally, this view means that designers can set time bounds intentionally according to target response times; systems with tighter bounds will likely enter partition mode more often and at times when the network is merely slow and not actually partitioned.

Sometimes it makes sense to forfeit strong C to avoid the high latency of maintaining consistency over a wide area.

The challenging case for designers is to mitigate a partition’s effects on consistency and availability.
The key idea is to manage partitions very explicitly, including not only detection, but also a specific recovery process and a plan for all of the invariants that might be violated during a partition.
This management approach has three steps:

- detect the start of a partition,
- enter an explicit partition mode that may limit some operations, and
- initiate partition recovery when communication is restored.

The last step aims to restore consistency and compensate for mistakes the program made while the system was partitioned.

> [!TIP]
>
> Consistency in CAP is defined quite differently from what [ACID](/docs/CS/Transaction.md?id=ACID) defines as consistency.
> ACID consistency describes transaction consistency: transaction brings the database from one valid state to another, maintaining all the database invariants (such as uniqueness constraints and referential integrity).
> In CAP, it means that operations are atomic (operations succeed or fail in their entirety) and consistent (operations never leave the data in an inconsistent state).

RPO

Recovery Point Objective

RTO

Recovery Time Objective

More trade-offs L vs. C

Low-latency: Speak to fewer than quorum of nodes?
– 2PC: write N, read 1
– RAFT: write ⌊N/2⌋ + 1, read ⌊N/2⌋ + 1
– General: |W| + |R| > N

L and C are fundamentally at odds
– “C” = linearizability, sequential, serializability (more later)


PRAM Theorem:
Impossible for sequentially consistent system to always provide low latency

FLP: No deterministic 1-crash-robust consensus algorithm exists with asynchronous communication.

[Eventually Consistent Register Revisited](https://www.researchgate.net/publication/284096787_Eventually_Consistent_Register_Revisited)

[Life beyond Distributed Transactions: an Apostate’s Opinion](https://www.ics.uci.edu/~cs223/papers/cidr07p15.pdf)


## Links

- [Distributed Systems](/docs/CS/Distributed/Distributed_Systems.md)

## References

1. [A Critique of the CAP Theorem](https://www.cl.cam.ac.uk/research/dtg/www/files/publications/public/mk428/cap-critique.pdf)
2. [CAP Twelve Years Later:How the “Rules” Have Changed](https://www.anantjain.dev/aeb39daf1c8c1360d401e8afe84a00b7/cap-annotated.pdf)
