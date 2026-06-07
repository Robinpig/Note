## Introduction

## Logical Clocks

### Partial Ordering

***Clock Condition***。
对于任意事件 a, b：如果 a -> b，则 C(a) < C(b)。

- C1。
  如果 a 和 b 是进程 $P_i$ 中的事件，且 a 在 b 之前发生，则 $C_i(a) < C_i(b)$。
- C2。
  如果 a 是进程 $P_i$ 发送消息的事件，b 是进程 $P_j$ 接收该消息的事件，则 $C_i(a) < C_i(b)$。

为了保证时钟系统满足 Clock Condition，我们将确保它满足条件 C1 和 C2。

条件 C1 很简单；进程只需遵守以下实现规则 (**IR1**)：

- 每个进程 $P_i$ 在两个连续事件之间递增 $C_i$。

为了满足条件 C2，我们要求每条消息 m 包含一个时间戳 $T_m$，等于消息发送的时间。
收到时间戳为 $T_m$ 的消息后，进程必须将其时钟推进到晚于 $T_m$ 的时间。
更准确地说，我们有以下规则 (**IR2**)。

- 如果事件 a 是进程 $P_i$ 发送消息 m，则消息 m 包含时间戳 $T_m = C_i(a)$。
- 接收到消息 m 后，进程 $P_j$ 将 $C_j$ 设置为大于或等于其当前值且大于 $T_m$ 的值。

### Totally

我们首先假设对于任意两个进程 $P_i$ 和 $P_j$，从 $P_i$ 发送到 $P_j$ 的消息按照发送顺序被接收。
此外，我们假设每条消息最终都会被收到。（这些假设可以通过引入消息编号和消息确认协议来避免。）
我们还假设一个进程可以直接向其他每个进程发送消息。

显然，仅基于 $\xi$ 中事件的算法，且 **不以任何方式将这些事件与 $\xi$ 中的其他事件关联**，无法保证请求 A 在请求 B 之前被排序。

算法定义的全序有些任意。
如果它偏离了系统用户感知的排序，可能会产生异常行为。
这可以通过使用适当同步的物理时钟来防止。

> THEOREM。
> 假设一个直径为 d 的强连通进程图，始终遵守规则 IR 1' 和 IR2'。
> 假设对于任何消息 m，#m --< # 对于某个常数 g，且对于所有 t > to：(a) PC1 成立。
> (b) 存在常数 ~" 和 ~，使得每 ~ 秒在每条边上发送一条不可预测延迟小于 ~ 的消息。
> 则 PC2 在 t > to + Td 时满足，• = d(2x~- +~)，其中近似假设 # + ~<< z。

## Vector Clocks

[Virtual Time and Global States of Distributed Systems](https://www.vs.inf.ethz.ch/publ/papers/VirtTimeGlobStates.pdf)

[Timestamps in Message-Passing Systems That Preserve the Partial Ordering](https://cs.nyu.edu/~apanda/classes/fa21/papers/fidge88timestamps.pdf)

[Why Vector Clocks Are Hard](https://riak.com/posts/technical/why-vector-clocks-are-hard/index.html)

## Hybrid Logical Clocks

## Total Order Broadcast

在容错分布式计算中，atomic broadcast 或 total order broadcast 是一种广播，其中多进程系统中所有正确的进程接收相同的消息集合，且顺序相同；即相同的消息序列。
之所以称为"原子"广播，是因为它要么最终在所有参与者处正确完成，要么所有参与者中止且无副作用。原子广播是一种重要的分布式计算原语。

原子广播协议通常需要满足以下属性：

- Validity：如果正确的参与者广播了一条消息，那么所有正确的参与者最终都会收到它。
- Uniform Agreement：如果一个正确的参与者收到了一条消息，那么所有正确的参与者最终都会收到该消息。
- Uniform Integrity：每条消息最多被每个参与者接收一次，并且仅当它之前被广播过。
- Uniform Total Order：消息在数学意义上是全序的；即，如果任何正确的参与者先收到消息 1 后收到消息 2，那么每个其他正确的参与者必须在收到消息 2 之前收到消息 1。

注意，total order 不等同于 FIFO 顺序，FIFO 要求如果进程在发送消息 2 之前发送了消息 1，那么所有参与者必须在收到消息 2 之前收到消息 1。
它也不等同于"因果顺序"，如果消息 2 "依赖于"或"发生在"消息 1 之后，那么所有参与者必须在收到消息 1 之后才收到消息 2。
虽然 total order 是一个强大且有用的条件，但它只要求所有参与者以相同顺序接收消息，并不对该顺序施加其他约束。

例如，给定自然数 7, 8, 1, 4, 5，我们可以序列化为 1<4<5<7<8。换句话说，自然数是全序的。
那么集合 {b, d}, {d, d}, {z, b} 呢？它们无法被序列化。换句话说，这些集合不是全序的。

状态机复制需要操作的全序。

### Equivalent to consensus

为了满足原子广播的条件，参与者必须有效地"同意"消息接收的顺序。
从故障中恢复的参与者，在其他参与者已经"同意"了一个顺序并开始接收消息后，必须能够了解并遵守已同意的顺序。
这些考虑表明，在存在崩溃故障的系统中，原子广播和 [consensus](/docs/CS/Distributed/Consensus/Consensus.md) 是等价的问题。

- 可以通过原子广播一个值来由进程提议该值进行共识，并且进程可以通过选择其原子接收的第一条消息的值来决定一个值。
  因此，共识可以简化为原子广播。
- 相反，一组参与者可以通过先就第一条接收的消息达成共识，然后就下一条消息达成共识，依此类推，直到所有消息都被接收，从而实现原子广播。
  因此，原子广播简化为共识。

请记住，total order broadcast 要求消息按相同顺序恰好传递一次给所有节点。
仔细想想，这等同于执行多轮共识：在每一轮中，节点提议它们想要发送的下一条消息，然后决定在全序中下一条要传递的消息。
因此，total order broadcast 等同于重复的多轮共识（每轮共识决策对应一次消息传递）：
- 由于共识的 agreement 属性，所有节点决定传递相同的消息且顺序相同。
- 由于 integrity 属性，消息不会被重复。
- 由于 validity 属性，消息不会被破坏或凭空捏造。
- 由于 termination 属性，消息不会丢失。

Viewstamped Replication、Raft 和 Zab 直接实现了 total order broadcast，因为这比重复执行多轮一次一个值的共识更高效。
对于 Paxos，这种优化称为 Multi-Paxos。

## Links

- [Distributed Systems](/docs/CS/Distributed/Distributed)

## References

1. [Time, Clocks, and the Ordering of Events in a Distributed System](https://www.microsoft.com/en-us/research/uploads/prod/2016/12/Time-Clocks-and-the-Ordering-of-Events-in-a-Distributed-System.pdf)
2. [Standard for a Precision Clock Synchronization Protocol for Networked Measurement and Control Systems]()
3. [The Implementation of Reliable Distributed Multiprocess Systems](https://www.microsoft.com/en-us/research/uploads/prod/2016/12/The-Implementation-of-Reliable-Distributed-Multiprocess-Systems.pdf)
4. [Using Time Instead of Timeout for Fault-Tolerant Distributed Systems](https://www.microsoft.com/en-us/research/uploads/prod/2016/12/using-time-Copy.pdf)
5. [Synchronizing Clocks in the Presence of Faults](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/12/Synchronizing-Clocks-in-the-Presence-of-Faults.pdf)
6. [Byzantine Clock Synchronization](https://www.microsoft.com/en-us/research/uploads/prod/2016/12/Byzantine-Clock-Synchronization.pdf)
7. [An Overview of Clock Synchronization.](https://www.researchgate.net/publication/221655803_An_Overview_of_Clock_Synchronization)
8. [Total Order Broadcast and Multicast Algorithms: Taxonomy and Survey](https://csis.pace.edu/~marchese/CS865/Papers/defago_200356.pdf)
9. [Atomic Broadcasts and Consensus: A Survey](https://www.net.in.tum.de/fileadmin/TUM/NET/NET-2020-11-1/NET-2020-11-1_19.pdf)
