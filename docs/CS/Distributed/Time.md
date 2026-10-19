## Introduction

## Physical Clocks

物理时钟是分布式系统中"真实时间"的来源。每个节点有独立的本地时钟（通常基于石英晶体振荡器），存在**时钟漂移（clock drift）**——即便初始对齐，不同节点也会因频率偏差逐渐产生偏差。物理时钟同步的目标是把所有节点的本地时间与权威时间源（如 UTC）对齐，并量化**不确定性界限（uncertainty bound）**。它是理解后续逻辑时钟、以及一致性模型中"实时边界"的前置。

### 同步算法

- **Cristian's Algorithm（1989, F. Cristian）**：客户端向时间服务器发请求，服务器返回带时间戳 T 的应答；客户端据往返延迟 RTT 估计偏移，将本地时钟设为 `T + RTT/2`，误差界为 `±(RTT/2 − min)`。前提是 RTT 主要由对称网络延迟构成，适合有可信时间源的场景。
- **Berkeley Algorithm（1989, Gusella & Zatti）**：由一台主节点（time daemon）轮询各从节点，收集它们的本地时间后计算**平均值**，再分别通知每个从节点应调整的偏移量（可为正/负）。适合**无外部 UTC 源**的内网，主节点本身不要求最准，只负责汇聚。
- **Schneider 框架（1987）**：《Synchronizing Clocks in the Presence of Faults》将前两者统一为**收敛（convergent）/ 收敛非中断（convergent non-interrupting）**算法族，并给出在存在崩溃/拜占庭故障时的同步边界，是后续容错时钟同步的理论基础。

### 协议与精度

| 协议 | 标准 | 精度量级 | 机制要点 |
| --- | --- | --- | --- |
| NTP | RFC 5905 | ~1 ms（LAN）/ ~10–100 ms（WAN） | 分层 stratum 模型，基于 Cristian 式 RTT 修正，纯软件 |
| PTP | IEEE 1588 | ~100 ns（亚微秒） | **硬件时间戳**（网卡/交换机打戳），主从同步，金融/电信/工业场景 |

### 不确定性界限与 TrueTime

纯软件同步（NTP）误差可达毫秒级，不足以支撑"全局事件真实先后"的判断。Spanner 的 **TrueTime** 用**原子钟 + GPS** 提供物理时间区间 `[earliest, latest]`，任何时间戳都带置信区间 `ε`；事务提交前必须经历"不确定性等待（commit wait）"——直到 `earliest > commit_ts`——从而保证外部一致性（external consistency）。这把"物理时钟 + 误差界"工程化，是 HLC 之外的另一条路线（见下节）。

## Logical Clocks

### Partial Ordering

***时钟条件（Clock Condition）***。
对任意事件 a、b：若 a → b，则 C(a) < C(b)。

- C1. 若 a 与 b 是进程 $P_i$ 中的事件，且 a 先于 b，则 $C_i(a) < C_i(b)$。
- C2. 若 a 是进程 $P_i$ 发送消息、b 是进程 $P_j$ 接收该消息，则 $C_i(a) < C_i(b)$。

为保证时钟系统满足时钟条件，我们确保其满足条件 C1 与 C2。条件 C1 很简单；进程只需遵循如下实现规则（**IR1**）：

- 每个进程 $P_i$ 在任意两个连续事件之间递增 $C_i$。

为满足条件 C2，我们要求每条消息 m 携带时间戳 $T_m$，其值等于消息发送时刻。进程收到带时间戳 $T_m$ 的消息后，必须将其时钟推进到晚于 $T_m$。更准确地说，我们有如下规则（**IR2**）。

- 若事件 a 是进程 $P_i$ 发送消息 m，则消息 m 携带时间戳 $T_m = C_i(a)$。
- 进程 $P_j$ 收到消息 m 时，将 $C_j$ 设为不小于其当前值且大于 $T_m$。

### Total Ordering

我们首先假设，对任意两个进程 $P_i$ 与 $P_j$，从 $P_i$ 发往 $P_j$ 的消息按发送顺序被接收。此外，假设每条消息最终都会被收到。（引入消息编号与消息确认协议可避免这些假设。）我们还假设进程能直接向其他任一进程发送消息。

显然，任何完全基于 $\xi$ 中事件、且**不以任何方式将这些事件与 $\xi$ 中其他事件关联**的算法，都无法保证请求 A 排在请求 B 之前。

算法定义的全序有一定任意性。若它与系统用户所感知的先后顺序不一致，就可能产生异常行为。这可以通过使用适当同步的物理时钟来避免。

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

混合逻辑时钟（HLC, Hybrid Logical Clocks，Kulkarni et al., CIDR 2014）用一个 **(物理分量 pt, 逻辑分量 l)** 的二元组，既保留 Lamport 逻辑时钟的**因果性**，又让时间戳贴近真实物理时间——解决了纯逻辑时钟"不可读"、纯物理时钟"有误差且难保证因果"的两难。CockroachDB、MongoDB、TiKV 的 MVCC 事务时间戳都基于 HLC。

### 结构

HLC 记作 `hlc.j = (pt.j, l.j)`：
- `pt.j`：节点 j 的物理分量，是"本地墙上时钟与已见过的最大物理时间"的上限；
- `l.j`：逻辑分量，仅在"物理分量持平"时进位，用于在同一物理毫秒内区分因果顺序。

### 更新规则

- **本地事件 / 发送消息**（令 `pt'.j` 为发送前本地墙上时钟读取）：
  - 若 `pt'.j = pt.j`：`l'.j = l.j + 1`
  - 否则：`l'.j = 0`，且 `pt'.j = pt.j`
- **接收消息**（消息携带发送方 HLC `(pt.m, l.m)`，本地新读 `pt'.j`）：
  - `pt'.j = max(pt.j, pt.m, pt'.j)`
  - 若取 max 后物理分量仍等于 `pt.j`（即与本地持平）：`l'.j = max(l.j, l.m) + 1`
  - 否则（物理分量前进了）：`l'.j = 0`

### 关键性质

1. **因果关系可判**：若 `a → b`，则 `hlc(a) < hlc(b)`（字典序），与 Lamport 时钟一致。
2. **有界贴近物理时间**：`pt.j ≤ real_time + ε`，其中 `ε` 是系统允许的最大消息延迟上界；因此 HLC 始终 ≥ 真实物理时间，又不会比它超前超过 `ε`。这让 HLC 既能排序因果，又能被"大致当作时间戳"读取。

### 与 TrueTime 的关系

| 维度 | HLC | TrueTime |
| --- | --- | --- |
| 时间来源 | 软件混合（本地时钟 + 逻辑进位） | 硬件（原子钟 + GPS）置信区间 |
| 输出 | 单点时间戳 `(pt, l)` | 区间 `[earliest, latest]` |
| 因果保证 | 由逻辑分量严格保证 | 由 commit wait 等待 `ε` 隐式保证 |
| 依赖 | 无需特殊硬件 | 需可信硬件时钟源 |
| 代表系统 | CockroachDB / MongoDB / TiKV | Spanner |

二者都试图在"分布式无全局物理时钟"与"业务需要可排序的时间"之间架桥：HLC 用软件逼近，TrueTime 用硬件兜底。

## Total Order Broadcast

在容错分布式计算中，原子广播（atomic broadcast）或全序广播（total order broadcast）是指：在多进程系统中，所有正确进程以相同顺序收到同一组消息，即相同的消息序列。该广播被称为“原子”是因为它要么在所有参与者处最终正确完成，要么所有参与者无副作用地中止。原子广播是重要的分布式计算原语。

原子广播协议通常要求以下性质：

- 有效性（Validity）：若某正确参与者广播了一条消息，则所有正确参与者最终都会收到它。
- 统一一致（Uniform Agreement）：若某一正确参与者收到某消息，则所有正确参与者最终都会收到该消息。
- 统一完整（Uniform Integrity）：每条消息至多被每个参与者接收一次，且仅当它此前已被广播。
- 统一全序（Uniform Total Order）：消息在数学意义下被全序排列；即若任一正确参与者先收到消息 1、后收到消息 2，则其他每个正确参与者都必须先于消息 2 收到消息 1。

注意，全序不等价于 FIFO 顺序——FIFO 要求若某进程先发送消息 1 后发送消息 2，则所有参与者必须先于消息 2 收到消息 1。它也不等价于“因果顺序（causal order）”：若消息 2“依赖于”或“晚于”消息 1，则所有参与者必须在收到消息 1 之后收到消息 2。全序虽是一个强且有用的条件，但只要求所有参与者以相同顺序收到消息，并不对该顺序施加其他约束。

例如，给定自然数 7、8、1、4、5，我们可以将其序列化为 1<4<5<7<8。换言之，自然数是全序的。接下来看集合 {b, d}、{d, d}、{z, b} 呢？它们无法被序列化。换言之，这些集合不是全序的。

状态机复制（State machine replication）要求操作的全序。


### Equivalent to Consensus

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
10. [Logical Physical Clocks and Consistent Snapshots in Globally Distributed Databases (Kulkarni et al., CIDR 2014)]()
