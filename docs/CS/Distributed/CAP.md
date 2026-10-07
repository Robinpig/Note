## Introduction

分布式计算机系统不可能同时提供以下三项保证：

- **一致性（Consistency）**：所有节点在同一时刻看到相同的数据（实际上指[线性一致性](/docs/CS/Distributed/Distributed.md?id=linearizability)）
- **可用性（Availability）**：节点的失效不会导致其他存活节点无法继续工作（即每个请求都能得到关于成功或失败的响应）
- **分区容错（Partition tolerance）**：尽管因网络故障（例如消息丢失）而产生任意分区，系统仍能继续运行

一个分布式系统在同一时刻最多只能满足其中两项保证，无法三者兼得。
我们希望在容忍网络分区的同时，既能保证一致性又能保证可用性。
网络可能被分割成若干部分，进程之间无法相互通信：分区节点之间发送的某些消息无法送达目的地。

理解 CAP 最简单的方式是想象位于分区两侧的两个节点。
只要允许至少一个节点更新状态，节点间就会变得不一致，从而放弃了 C。
同理，如果选择保持一致性，分区的一侧必须表现得如同不可用，从而放弃了 A。
只有当节点能够相互通信时，才可能同时保留一致性和可用性，也就意味着放弃了 P。
普遍的看法是，对于广域网系统，设计者无法放弃 P，因而不得不在 C 与 A 之间艰难取舍。
从某种意义上说，NoSQL 运动就是关于优先可用性、次之一致性的选择；
而遵循 ACID 特性（原子性、一致性、隔离性、持久性）的数据库则相反。

> 选择可用性而非一致性，是一个业务决策，而非技术决策。  -- Coda Hale



## BASE

ACID 与 BASE 代表了在一致性—可用性光谱两端的两套设计哲学。
ACID 特性关注一致性，是数据库的传统做法。

虽然这两个术语更像是助记符而非精确定义，但 BASE 这个缩写（排在后面）稍微别扭一些：Basically Available、Soft state、Eventually consistent（基本可用、软状态、最终一致）。
软状态与最终一致是在存在分区时依然表现良好的技术，因此有助于提升可用性。
CAP 与 ACID 之间的关系更复杂且常被误解，部分原因是 ACID 中的 C 和 A 与 CAP 中同样的字母含义不同，部分原因是选择可用性只影响 ACID 保证中的一部分。
ACID 的四大特性是：

- 原子性（Atomicity，A）。所有系统都能从原子操作中受益。当关注可用性时，分区两侧仍应使用原子操作。此外，更高级别的原子操作（ACID 所暗示的那种）实际上简化了恢复。
- 一致性（Consistency，C）。在 ACID 中，C 表示事务保持所有数据库规则，例如唯一键约束。相反，CAP 中的 C 仅指单副本一致性（single-copy consistency），它是 ACID 一致性的严格子集。ACID 一致性也无法在分区间保持——分区恢复需要重建 ACID 一致性。更一般地说，在分区期间维持不变量可能不可能，因此需要仔细考虑禁止哪些操作，以及如何在恢复期间重建不变量。
- 隔离性（Isolation，I）。隔离性是 CAP 定理的核心：如果系统要求 ACID 隔离，那么在分区期间它最多只能在一侧运行。可串行性（Serializability）通常需要通信，因此在分区时会失败。在分区期间，通过分区恢复时的补偿，可以采用更弱的正确性定义。
- 持久性（Durability，D）。与原子性一样，没有理由放弃持久性，尽管开发者可能因代价高昂而选择通过软状态（BASE 风格）来避免需要它。一个微妙之处在于，在分区恢复期间，有可能回滚那些在操作时不经意违反不变量的持久化操作。然而，在恢复时，给定双方的持久化历史，这类操作可以被检测并纠正。一般而言，在分区两侧各自运行 ACID 事务会让恢复更容易，并提供一个补偿事务框架，可用于从分区中恢复。

在异步系统中，可用性要求不可能被满足，而且我们无法实现一个在网络分区存在时同时保证可用性与一致性的系统 [GILBERT02]。
我们可以构建在提供尽力可用性（best effort availability）的同时保证强一致性的系统，或在提供尽力一致性（best effort consistency）的同时保证可用性的系统。
这里的“尽力”意味着：只要一切正常，系统不会故意违反任何保证，但在发生网络分区时，允许保证被弱化甚至破坏。

CP 系统的一个例子是共识（Consensus）算法的实现，需要多数节点才能推进：始终一致，但在网络分区时可能不可用。
一个只要还有单个副本存活就始终接受写入并提供读取的数据库，是 AP 系统的例子，它可能最终丢失数据或返回不一致的结果。

### Eventual Consistency

[Eventually Consistent - Revisited](https://www.allthingsdistributed.com/2008/12/eventually_consistent.html)


## PACELEC

PACELEC 猜想是 CAP 的扩展，它指出在网络分区存在时，要在一致性与可用性之间做选择（PAC）；
否则（E），即便系统正常运行，我们仍须在延迟与一致性之间做选择。

延迟—一致性权衡（ELC）仅当数据被复制时才相关。

Dynamo、Cassandra、Riak 的默认版本是 PA/EL 系统，即如果发生分区，优先保证可用性；在没有分区时，优先保证低延迟。

完全 ACID 的系统（VoltDB、H-Store、Megastore）以及 BigTable、HB 等是 PC/EC 系统，即优先保证一致性，放弃可用性与延迟。

MongoDB 可被归类为 PA/EC 系统。

[Consistency Tradeoffs in Modern Distributed Database System Design](https://www.cs.umd.edu/~abadi/papers/abadi-pacelc.pdf)

Dynamo、Cassandra、Riak 的默认版本是 PA/EL 系统：如果发生分区，它们为可用性放弃一致性；在正常操作时，它们为更低延迟放弃一致性。


## Trade-offs

正如“CAP 困惑”边栏所解释的，“三选二”的观点在多个方面具有误导性。

- 首先，由于分区很少发生，当系统未分区时，几乎没有理由放弃 C 或 A。
- 其次，C 与 A 之间的选择可能在同一个系统内以极细的粒度多次发生；不仅子系统可以做出不同选择，而且该选择可以随操作甚至所涉及的具体数据或用户而变化。
- 最后，这三项特性都比二元（binary）更具连续性。可用性显然是从 0% 到 100% 连续的，但一致性也有许多级别，甚至分区也有细微差别，包括系统内部对于“是否存在分区”的分歧。

探索这些细微差别需要突破传统的分区处理方式，这是根本性的挑战。
由于分区很少发生，CAP 应该允许在大多数时候达到完美的 C 和 A，但当分区出现或被感知时，采取一种检测分区并显式处理它的策略才是正道。
该策略应包含三个步骤：检测分区、进入显式分区模式以限制某些操作、启动恢复过程以恢复一致性并补偿分区期间所犯的错误。

在操作层面，CAP 的本质发生在超时期间——这是程序必须做出根本性决策的时期，即分区决策（partition decision）：

- 取消操作从而降低可用性，或
- 继续执行操作从而冒不一致的风险。

通过重试通信以实现一致性（例如通过 Paxos 或两阶段提交）只是推迟了决策。
程序迟早必须做出决策；无限重试通信本质上就是在 C 与 A 之间选择了 C。

因此，从实用角度看，分区是对通信的时间界限。
未能在时间界限内达成一致意味着发生了分区，从而对该操作要在 C 与 A 之间做出选择。
这些概念抓住了关于延迟的核心设计问题：双方是否在没有通信的情况下继续推进？

这种实用观点带来几个重要推论。

- 第一，不存在全局的分区概念，因为某些节点可能检测到分区，而其他节点可能没有。
- 第二，节点可以检测到分区并进入分区模式——这是优化 C 和 A 的核心部分。
- 最后，这种观点意味着设计者可以根据目标响应时间有意设置时间界限；界限更紧的系统可能更频繁地进入分区模式，甚至在网络只是缓慢而非真正分区时。

有时为了避免跨广域维护一致性的高延迟，放弃强 C 是有意义的。

对设计者而言，最具挑战的情况是如何缓解分区对一致性和可用性的影响。
核心思想是显式地管理分区，不仅包括检测，还包括具体的恢复过程，以及针对分区期间可能被破坏的所有不变量的计划。
这种管理方式包含三个步骤：

- 检测分区的开始，
- 进入可能限制某些操作的显式分区模式，
- 在通信恢复时启动分区恢复。

最后一步旨在恢复一致性，并补偿程序在系统分区期间所犯的错误。

> [!TIP]
>
> CAP 中的一致性（Consistency）定义与 [ACID](/docs/CS/SE/Transaction.md?id=acid) 所定义的一致性截然不同。
> ACID 一致性描述事务一致性：事务将数据库从一个有效状态带到另一个有效状态，保持所有数据库不变量（如唯一性约束与参照完整性）。
> 在 CAP 中，它意味着操作是原子的（操作整体成功或失败）且一致的（操作绝不会使数据处于不一致状态）。

RPO

Recovery Point Objective（恢复点目标）

RTO

Recovery Time Objective（恢复时间目标）

更多权衡 L vs. C

低延迟：向少于法定人数（quorum）的节点发起请求？
– 2PC：写入 N，读取 1
– RAFT：写入 ⌊N/2⌋ + 1，读取 ⌊N/2⌋ + 1
– 通用：|W| + |R| > N

L 与 C 根本上对立
– “C” = 线性一致性（linearizability）、顺序一致性（sequential）、可串行性（serializability）（详见后文）

PRAM 定理：
顺序一致（sequentially consistent）的系统不可能始终提供低延迟

FLP：在异步通信下，不存在确定性的、能容忍一次崩溃的共识（Consensus）算法。

[Eventually Consistent Register Revisited](https://www.researchgate.net/publication/284096787_Eventually_Consistent_Register_Revisited)

[Life beyond Distributed Transactions: an Apostate’s Opinion](https://www.ics.uci.edu/~cs223/papers/cidr07p15.pdf)


## Links

- [Distributed Systems](/docs/CS/Distributed/Distributed.md)

## References

1. [A Critique of the CAP Theorem](https://www.cl.cam.ac.uk/research/dtg/www/files/publications/public/mk428/cap-critique.pdf)
2. [CAP Twelve Years Later:How the “Rules” Have Changed](https://www.anantjain.dev/aeb39daf1c8c1360d401e8afe84a00b7/cap-annotated.pdf)
3. [CAP Theorem: Revisited](https://robertgreiner.com/cap-theorem-revisited/)
4. [You Can’t Sacrifice Partition Tolerance](https://codahale.com/you-cant-sacrifice-partition-tolerance/)
5. [Brewer’s Conjecture and the Feasibility of Consistent, Available, Partition-Tolerant Web Services](https://www.comp.nus.edu.sg/~gilbert/pubs/BrewersConjecture-SigAct.pdf)
6. [A plain english introduction to CAP Theorem](https://ksat.me/a-plain-english-introduction-to-cap-theorem)
7. [Brewer’s Conjecture and the Feasibility of Consistent, Available, Partition-Tolerant Web](https://www.comp.nus.edu.sg/~gilbert/pubs/BrewersConjecture-SigAct.pdf)
