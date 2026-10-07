## Introduction


## 逻辑时钟（Logical Clocks）

### 偏序（Partial Ordering）

***时钟条件（Clock Condition）***。
对任意事件 a、b：若 a → b，则 C(a) < C(b)。

- C1. 若 a 与 b 是进程 $P_i$ 中的事件，且 a 先于 b，则 $C_i(a) < C_i(b)$。
- C2. 若 a 是进程 $P_i$ 发送消息、b 是进程 $P_j$ 接收该消息，则 $C_i(a) < C_i(b)$。

为保证时钟系统满足时钟条件，我们确保其满足条件 C1 与 C2。条件 C1 很简单；进程只需遵循如下实现规则（**IR1**）：

- 每个进程 $P_i$ 在任意两个连续事件之间递增 $C_i$。

为满足条件 C2，我们要求每条消息 m 携带时间戳 $T_m$，其值等于消息发送时刻。进程收到带时间戳 $T_m$ 的消息后，必须将其时钟推进到晚于 $T_m$。更准确地说，我们有如下规则（**IR2**）。

- 若事件 a 是进程 $P_i$ 发送消息 m，则消息 m 携带时间戳 $T_m = C_i(a)$。
- 进程 $P_j$ 收到消息 m 时，将 $C_j$ 设为不小于其当前值且大于 $T_m$。

### 全序（Total Ordering）

我们首先假设，对任意两个进程 $P_i$ 与 $P_j$，从 $P_i$ 发往 $P_j$ 的消息按发送顺序被接收。此外，假设每条消息最终都会被收到。（引入消息编号与消息确认协议可避免这些假设。）我们还假设进程能直接向其他任一进程发送消息。

显然，任何完全基于 $\xi$ 中事件、且**不以任何方式将这些事件与 $\xi$ 中其他事件关联**的算法，都无法保证请求 A 排在请求 B 之前。

算法定义的全序有一定任意性。若它与系统用户所感知的先后顺序不一致，就可能产生异常行为。这可以通过使用适当同步的物理时钟来避免。

> THEOREM.
> Assume a strongly connected graph of processes with diameter d which always obeys rules IR 1' and IR2'.
> Assume that for any message m, #m --< # for some constant g, and that for all t > to: (a) PC 1 holds.
> (b) There are constants ~" and ~ such that every ~- seconds a message with an unpredictable delay less than ~ is sent over every arc.
> Then PC2 is satisfied with • = d(2x~- +~) for all t > to + Td, where the approximations assume # + ~<< z.

## 向量时钟（Vector Clocks）

[Virtual Time and Global States of Distributed Systems](https://www.vs.inf.ethz.ch/publ/papers/VirtTimeGlobStates.pdf)

[Timestamps in Message-Passing Systems That Preserve the Partial Ordering](https://cs.nyu.edu/~apanda/classes/fa21/papers/fidge88timestamps.pdf)

[Why Vector Clocks Are Hard](https://riak.com/posts/technical/why-vector-clocks-are-hard/index.html)

## 混合逻辑时钟（Hybrid Logical Clocks）


## 全序广播（Total Order Broadcast）

在容错分布式计算中，原子广播（atomic broadcast）或全序广播（total order broadcast）是指：在多进程系统中，所有正确进程以相同顺序收到同一组消息，即相同的消息序列。该广播被称为“原子”是因为它要么在所有参与者处最终正确完成，要么所有参与者无副作用地中止。原子广播是重要的分布式计算原语。

原子广播协议通常要求以下性质：

- 有效性（Validity）：若某正确参与者广播了一条消息，则所有正确参与者最终都会收到它。
- 统一一致（Uniform Agreement）：若某一正确参与者收到某消息，则所有正确参与者最终都会收到该消息。
- 统一完整（Uniform Integrity）：每条消息至多被每个参与者接收一次，且仅当它此前已被广播。
- 统一全序（Uniform Total Order）：消息在数学意义下被全序排列；即若任一正确参与者先收到消息 1、后收到消息 2，则其他每个正确参与者都必须先于消息 2 收到消息 1。

注意，全序不等价于 FIFO 顺序——FIFO 要求若某进程先发送消息 1 后发送消息 2，则所有参与者必须先于消息 2 收到消息 1。它也不等价于“因果顺序（causal order）”：若消息 2“依赖于”或“晚于”消息 1，则所有参与者必须在收到消息 1 之后收到消息 2。全序虽是一个强且有用的条件，但只要求所有参与者以相同顺序收到消息，并不对该顺序施加其他约束。

例如，给定自然数 7、8、1、4、5，我们可以将其序列化为 1<4<5<7<8。换言之，自然数是全序的。接下来看集合 {b, d}、{d, d}、{z, b} 呢？它们无法被序列化。换言之，这些集合不是全序的。

状态机复制（State machine replication）要求操作的全序。


### 等价于共识（Equivalent to consensus）

为使原子广播的条件得以满足，参与者必须在消息的接收顺序上有效“达成一致（agree）”。当其他参与者已“达成一致”的顺序并开始接收消息后，从故障中恢复的参与者必须能够学习并遵从该已达成一致的顺序。这些考量表明：在存在崩溃故障的系统中，原子广播与 [consensus](/docs/CS/Distributed/Consensus/Consensus.md) 是等价的问题。

- 进程可通过原子广播某值来将其作为共识（Consensus）的提案，而进程可通过选取其原子收到的第一条消息的值来决策。因此，共识可归约为原子广播。
- 反之，一组参与者可通过对“第一条要接收的消息”达成共识来进行原子广播，接着对下一条消息达成共识，依此类推，直到所有消息都被接收。因此，原子广播可归约为共识。

记住，全序广播要求消息以相同顺序、恰好一次地投递到所有节点。细想之下，这等价于执行若干轮共识：每一轮中，节点提出它想发送的下一消息，然后就全序中下一要投递的消息做出决策。因此，全序广播等价于反复多轮共识（每次共识决策对应一次消息投递）：

- 由于共识的一致性（agreement）性质，所有节点决定以相同顺序投递相同消息。
- 由于完整性（integrity）性质，消息不会被重复。
- 由于有效性（validity）性质，消息不会被损坏，也不会凭空捏造。
- 由于终止性（termination）性质，消息不会丢失。

Viewstamped Replication、Raft、Zab 直接实现全序广播，因为这比反复进行一轮只决定一个值的共识更高效。在 Paxos 中，这种优化称为 Multi-Paxos。

## Links

- [Distributed Systems](/docs/CS/Distributed/Distributed.md)

## References

1. [Time, Clocks, and the Ordering of Events in a Distributed System](https://www.microsoft.com/en-us/research/uploads/prod/2016/12/Time-Clocks-and-the-Ordering-of-Events-in-a-Distributed-System.pdf)
2. [Standard for a Precision Clock Synchronization Protocol for Networked Measurement and Control Systems]()
3. [The Implementation of Reliable Distributed Multiprocess Systems](https://www.microsoft.com/en-us/research/uploads/prod/2016/12/The-Implementation-of-Reliable-Distributed-Multiprocess-Systems.pdf)
4. [Using Time Instead of Timeout for Fault-Tolerant Distributed Systems](https://www.microsoft.com/en-us/research/uploads/prod/2016/12/using-time-Copy.pdf)
5. [Synchronizing Clocks in the Presence of Faults](https://www.microsoft.com/en-us/research/uploads/prod/2016/12/Synchronizing-Clocks-in-the-Presence-of-Faults.pdf)
6. [Byzantine Clock Synchronization](https://www.microsoft.com/en-us/research/uploads/prod/2016/12/Byzantine-Clock-Synchronization.pdf)
7. [An Overview of Clock Synchronization.](https://www.researchgate.net/publication/221655803_An_Overview_of_Clock_Synchronization)
8. [Total Order Broadcast and Multicast Algorithms: Taxonomy and Survey]()https://csis.pace.edu/~marchese/CS865/Papers/defago_2003_56.pdf
9. [Atomic Broadcasts and Consensus: A Survey](https://www.net.in.tum.de/fileadmin/TUM/NET/NET-2020-11-1/NET-2020-11-1_19.pdf)
