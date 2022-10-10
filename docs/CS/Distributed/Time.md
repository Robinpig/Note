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


## Total Order Broadcast

In fault-tolerant distributed computing, an atomic broadcast or total order broadcast is a broadcast where all correct processes in a system of multiple processes receive the same set of messages in the same order; that is, the same sequence of messages.
The broadcast is termed "atomic" because it either eventually completes correctly at all participants, or all participants abort without side effects. Atomic broadcasts are an important distributed computing primitive.

The following properties are usually required from an atomic broadcast protocol:

- Validity: if a correct participant broadcasts a message, then all correct participants will eventually receive it.
- Uniform Agreement: if one correct participant receives a message, then all correct participants will eventually receive that message.
- Uniform Integrity: a message is received by each participant at most once, and only if it was previously broadcast.
- Uniform Total Order: the messages are totally ordered in the mathematical sense; that is, if any correct participant receives message 1 first and message 2 second, then every other correct participant must receive message 1 before message 2.

Note that total order is not equivalent to FIFO order, which requires that if a process sent message 1 before it sent message 2, then all participants must receive message 1 before receiving message 2. 
It is also not equivalent to "causal order", where if message 2 "depends on" or "occurs after" message 1 then all participants must receive message 2 after receiving message 1. 
While a strong and useful condition, total order requires only that all participants receive the messages in the same order, but does not place other constraints on that order.

For example, what if the natural numbers 7, 8, 1, 4, and 5 are given? We can then serialize 1<4<5<7<8. In other words, the natural numbers are total order.
What about the sets {b, d}, {d,d} {z, b} next? They cannot be serialized. In other words, these sets are not in total order.

State machine replication requires the total order of operations.



### Equivalent to consensus

In order for the conditions for atomic broadcast to be satisfied, the participants must effectively "agree" on the order of receipt of the messages.
Participants recovering from failure, after the other participants have "agreed" an order and started to receive the messages, must be able to learn and comply with the agreed order. 
Such considerations indicate that in systems with crash failures, atomic broadcast and [consensus](/docs/CS/Distributed/Consensus.md) are equivalent problems.

A value can be proposed by a process for consensus by atomically broadcasting it, and a process can decide a value by selecting the value of the first message which it atomically receives.
Thus, consensus can be reduced to atomic broadcast.
<br>
Conversely, a group of participants can atomically broadcast messages by achieving consensus regarding the first message to be received, followed by achieving consensus on the next message, and so forth until all the messages have been received. 
Thus, atomic broadcast reduces to consensus.


Remember that total order broadcast requires messages to be delivered exactly once, in the same order, to all nodes. 
If you think about it, this is equivalent to performing several rounds of consensus: in each round, nodes propose the message that they want to send next, and then decide on the next message to be delivered in the total order.
So, total order broadcast is equivalent to repeated rounds of consensus (each consensus decision corresponding to one message delivery):
- Due to the agreement property of consensus, all nodes decide to deliver the same messages in the same order.
- Due to the integrity property, messages are not duplicated.
- Due to the validity property, messages are not corrupted and not fabricated out of thin air.
- Due to the termination property, messages are not lost.

Viewstamped Replication, Raft, and Zab implement total order broadcast directly, because that is more efficient than doing repeated rounds of one-value-at-a-time consensus. 
In the case of Paxos, this optimization is known as Multi-Paxos.

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
8. [Total Order Broadcast and Multicast Algorithms: Taxonomy and Survey]()https://csis.pace.edu/~marchese/CS865/Papers/defago_200356.pdf