## Introduction



## Logical Clocks

### Partial Ordering

***Clock Condition***.
For any events a, b: if a-> b then C(a) < C(b).

- C1.
  If a and b are events in process $P_i$, and a comes before b, then $C_i(a) < C_i(b)$.
- C2.
  If a is the sending of a message by process $P_i$ and b is the receipt of that message by process $P_j$, then $C_i(a) < C_i(b)$.

To guarantee that the system of clocks satisfies the Clock Condition, we will insure that it satisfies conditions C1 and C2.

Condition C 1 is simple; the processes need only obey the following implementation rule(**IR1**):

- Each process $P_i$ increments $C_i$ between any two successive events.

To meet condition C2, we require that each message m contain a timestamp $T_m$ which equals the time at which the message was sent.
Upon receiving a message timestamped $T_m$, a process must advance its clock to be later than $T_m$.
More precisely, we have the following rule(**IR2**).

- If event a is the sending of a message m by process $P_i$, then the message m contains a timestamp $T_m= C_i(a)$.
- Upon receiving a message m, process $P_j$ sets $C_j$ greater than or equal to its present value and greater than $T_m$.

### Totally

We assume first of all that for any two processes $P_i$ and $P_j$, the messages sent from $P_i$ to $P_j$ are received in the same order as they are sent.
Moreover, we assume that every message is eventually received. (These assumptions can be avoided by introducing message numbers and message acknowledgment protocols.)
We also assume that a process can send messages directly to every other process.

It is obvious that no algorithm based entirely upon events in $\xi$, and which **does not relate those events in any way with the other events** in $\xi$, can guarantee that request A is ordered before request B.

The total ordering defined by the algorithm is somewhat arbitrary.
It can produce anomalous behavior if it disagrees with the ordering perceived by the system's users.
This can be prevented by the use of properly synchronized physical clocks.

> THEOREM.
> Assume a strongly connected graph of processes with diameter d which always obeys rules IR 1' and IR2'.
> Assume that for any message m, #m --< # for some constant g, and that for all t > to: (a) PC 1 holds.
> (b) There are constants ~" and ~ such that every ~- seconds a message with an unpredictable delay less than ~ is sent over every arc.
> Then PC2 is satisfied with • = d(2x~- +~) for all t > to + Td, where the approximations assume # + ~<< z.

## Vector Clocks

[Virtual Time and Global States of Distributed Systems](https://www.vs.inf.ethz.ch/publ/papers/VirtTimeGlobStates.pdf)

[Timestamps in Message-Passing Systems That Preserve the Partial Ordering](https://cs.nyu.edu/~apanda/classes/fa21/papers/fidge88timestamps.pdf)

[Why Vector Clocks Are Hard](https://riak.com/posts/technical/why-vector-clocks-are-hard/index.html)

## Hybrid Logical Clocks

## Links

- [Distributed Systems](/docs/CS/Distributed/Distributed_Systems.md)

## References

1. [Time, Clocks, and the Ordering of Events in a Distributed System](https://www.microsoft.com/en-us/research/uploads/prod/2016/12/Time-Clocks-and-the-Ordering-of-Events-in-a-Distributed-System.pdf)
2. [Standard for a Precision Clock Synchronization Protocol for Networked Measurement and Control Systems]()
3. [The Implementation of Reliable Distributed Multiprocess Systems](https://www.microsoft.com/en-us/research/uploads/prod/2016/12/The-Implementation-of-Reliable-Distributed-Multiprocess-Systems.pdf)
4. [Using Time Instead of Timeout for Fault-Tolerant Distributed Systems](https://www.microsoft.com/en-us/research/uploads/prod/2016/12/using-time-Copy.pdf)
5. [Synchronizing Clocks in the Presence of Faults](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/12/Synchronizing-Clocks-in-the-Presence-of-Faults.pdf)
6. [Byzantine Clock Synchronization](https://www.microsoft.com/en-us/research/uploads/prod/2016/12/Byzantine-Clock-Synchronization.pdf)
7. [An Overview of Clock Synchronization.](https://www.researchgate.net/publication/221655803_An_Overview_of_Clock_Synchronization)