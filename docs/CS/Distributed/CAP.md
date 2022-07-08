## Introduction

It is impossible for a distributed computer system to simultaneously provide all three of the following guarantees:

- **Consistency**: all nodes see the same data at the same time
- **Availability**: Node failures do not prevent other survivors from continuing to operate (a guarantee that every request receives a response about whether it succeeded or failed)
- **Partition tolerance**: the system continues to operate despite arbitrary partitioning due to network failures (e.g., message loss)

A distributed system can satisfy any two of these guarantees at the same time but not all three.
We would like to achieve both consistency and availability while tolerating network partitions.
The network can get split into several parts where processes are not able to communicate with each other: some of the messages sent between partitioned nodes won’t reach their destinations.

Availability requirement is impossible to satisfy in an asynchronous system, and we cannot implement a system that simultaneously guarantees both availability and consistency in the presence of network partitions [GILBERT02].
We can build systems that guarantee strong consistency while providing best effort availability, or guarantee availability while providing best effort consistency [GILBERT12].
Best effort here implies that if everything works, the system will not purposefully violate any guarantees, but guarantees are allowed to be weakened and violated in the case of network partitions.

An example of a CP system is an implementation of a consensus algorithm, requiring a majority of nodes for progress: always consistent, but might be unavailable in the case of a network partition.
A database always accepting writes and serving reads as long as even a single replica is up is an example of an AP system, which may end up losing data or serving inconsistent results.

PACELEC conjecture [ABADI12], an extension of CAP, states that in presence of network partitions there’s a choice between consistency and availability (PAC).
Else (E), even if the system is running normally, we still have to make a choice between latency and consistency.

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


PACELC

PRAM Theorem:
Impossible for sequentially consistent system to always provide low latency

FLP: No deterministic 1-crash-robust consensus algorithm exists with asynchronous communication.



[A Critique of the CAP Theorem](https://www.cl.cam.ac.uk/research/dtg/www/files/publications/public/mk428/cap-critique.pdf)

[CAP Twelve Years Later:How the “Rules” Have Changed](https://www.anantjain.dev/aeb39daf1c8c1360d401e8afe84a00b7/cap-annotated.pdf)
