## Introduction

A distributed system is one in which components located at networked computers communicate and coordinate their actions only by passing messages.
This definition leads to the following especially significant characteristics of distributed systems: concurrency of components, lack of a global clock and independent failures of components.


Resources sharing as a main motivation for constructing distributed systems. 
Resources may be managed by servers and accessed by clients or they may be encapsulated as objects and accessed by other client objects.

The challenges arising from the construction of distributed systems are the heterogeneity of their components, openness (which allows components to be added or replaced), 
security, scalability – the ability to work well when the load or the number of users increases – failure handling, concurrency of components, transparency and providing quality of service.



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


## Links

- [Operating Systems](/docs/CS/OS/OS.md)


## References

1. [Distributed Systems Concepts and Design Fifth Edition](https://www.cdk5.net/wp/)