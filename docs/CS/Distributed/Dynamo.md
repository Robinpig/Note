## Introduction

亚马逊的电子商务系统由众多服务组成，这些服务相互通信，以提供丰富的功能集。每个服务都运行着自己独立的 Dynamo 实例，并基于以下一组假设运行：

* 数据访问与更新通过基于键值（key-value）的查询模型完成。这简化了 Dynamo 的接口，因为它不再需要提供跨多张表执行 join 的复杂查询模型。
* 对于 Dynamo 节点上存储的数据，在一致性上做了妥协。使用 Dynamo 作为存储层的应用不再追求严格一致性，而是采用最终一致性（eventual consistency）模型。
* 在冲突解决时，写操作被赋予更高优先级。由于延迟要求严苛，写请求会在不解决冲突的情况下被处理，与某个 key 相关的所有冲突状态都会被保留。冲突解决发生在读时，依据某策略（如 last-write-wins，最后写入获胜），或者把解决逻辑移到客户端一侧。
* 系统中的每个 Dynamo 节点都与同系统的其它节点完全相同。这意味着不存在承担额外职责的主节点（master node）。相比典型的主从（master-replica）模型，这让系统中节点的维护容易得多。

在逐一探讨这些挑战时，请牢记并体会 Dynamo 所提供的简洁接口，即 `GET(key)` 与 `PUT(key, context, object)`，正是这种简洁性在解决这一系列挑战中起到了关键作用。`context` 包含了关于 `object` 版本的一些元数据。

* 分区（Partitioning）：为了让存储系统持续扩展，当某个节点在容量上达到某一阈值后，Dynamo 需要把数据分区到多个节点上。为了完成这种分区，Dynamo 依赖 [Consistent Hashing](https://distributed-computing-musings.com/2022/01/partitioning-consistent-hashing/)。一致性哈希的基本实现会带来数据分布不均匀的问题，因此 Dynamo 在一致性哈希环之上使用虚拟节点（virtual node），以更均匀地在环上分布数据。
* 复制（Replication）：由于高可用是 Dynamo 的关键需求，任何持久化到存储层的 key 都会被存放在 `N` 个节点上。这一复制由一个协调者（coordinator）执行：它按照一致性哈希算法把 key 存到环上分配给该 key 的节点，并向环上顺时针方向的 `N - 1` 个节点再做复制。负责存储该 key 的这 `N` 个节点的列表被称为 *preference list*（偏好列表）。
* 数据版本化（Data Versioning）：Dynamo 关注提供最终一致性，因此可能出现某个 `put()` 操作成功、但更新尚未持久化到所有节点的情况。此外，Dynamo 把故障视为常态，把失败当作事件而非异常状态。这些故障可能是节点故障，也可能是因网络中断导致的分区故障。Dynamo 会持久化与某个 key 相关联的每一次更新（即便处于故障状态），并使用 [vector clocks](https://distributed-computing-musings.com/2022/05/vector-clocks-keeping-time-in-check/)（向量时钟）来寻找与该 key 相关联的更新的正确顺序。这个向量时钟被用来发现 key 在多个节点或分区上发生的更新之间的因果关系。
* 执行数据库操作（Executing Database Operations）：Dynamo 中的任意读/写操作都由某个节点（也称为协调者节点，coordinator node）处理。该节点是 *preference list* 中前 `N` 个节点里第一个可达的节点（见复制一节）。为执行读/写操作，协调者节点会与 *preference list* 中的所有 `N` 个节点通信，任何因故障或网络失败而不可达的节点都被跳过。为保持一致性，Dynamo 使用 [quorum based approach](https://distributed-computing-musings.com/2022/01/replication-maintaining-a-quorum/)（基于 quorum 的方法），其中包含两个可配置参数 `R` 与 `W`。为维持 quorum，将 `R` 与 `W` 设为满足 `R + W > N`。
* 处理临时故障（Handling Temporary Failures）：使用传统的基于 quorum 的方法，Dynamo 面临着牺牲其存储系统可用性的风险。当 *preference list* 中的节点宕机，或因分区故障导致列表中的节点不可达时，quorum 的要求就可能被破坏。为克服这一点，Dynamo 采用 [Sloppy Quorum &amp; Hinted hand-off.](https://distributed-computing-musings.com/2022/05/sloppy-quorum-and-hinted-handoff-quorum-in-the-times-of-failure/)（松散 quorum 与暗示转交）。这样，所有的读与写都在前 `N` 个健康节点上执行，这些节点未必是哈希环上的前 `N` 个节点。
* 处理永久故障（Handling Permanent Failures）：暗示转交（hinted handoff）存在一个边界情况——持有暗示消息的节点可能在把消息传给原节点之前就永久宕机。在这种情况下，我们面临损害存储系统持久性的风险。这可能产生级联效应：我们最终得到不一致的数据，并且在为时已晚之前都无法察觉这种失同步状态。为克服这一点，Dynamo 采用 [Merkle tree](https://en.wikipedia.org/wiki/Merkle_tree)（默克尔树），它是一种反熵（anti-entropy）协议。Merkle tree 在区块链技术中也是一个广为人知的概念。Dynamo 使用 Merkle tree 来检测副本节点之间的不一致，并阻止过时数据在副本节点间传播。
* 成员关系与故障检测（Membership & Failure Detection）：Dynamo 使用 [gossip-based protocol](https://en.wikipedia.org/wiki/Gossip_protocol#:~:text=A%20gossip%20protocol%20or%20epidemic,all%20members%20of%20a%20group.)（基于 gossip 的协议）来为系统中的其它节点提供一致的节点视图。因此，每当有新节点加入系统或某节点宕机，系统中的其它节点都会通过该协议来推断存储系统中各节点的状态。这种基于 gossip 的机制也有助于故障检测：被标记为故障的节点的信息会传播给其它节点，后者可据此避免在执行数据库操作时做不必要的通信。

从高层看，Dynamo 由三大核心组件构成：请求协调（request coordination）、成员关系与故障检测（membership & failure detection），以及本地持久化引擎（local persistence engine）。

## Lessons Learned

在构建 Dynamo 的过程中总结出了一系列经验，这些经验也促使我们在该数据存储的设计中加入了更多改进。其中部分经验如下：

* 尽管 Dynamo 的首要关注点是可用性，但在亚马逊的规模下，性能同样至关重要。某些应用在处理关键的用户面流程时，对性能有更高的要求。Dynamo 为此提供了一种选择：以牺牲数据持久性来换取更高的性能。具体做法是提供一个内存缓冲区，用于存储客户端的更新，并定期写入存储层。这同时也提升了读性能，因为应用会先从该缓冲区读取，若缓冲区中没有记录，再把请求路由到存储层。这提升了性能，因为现在每次更新无需持久化到磁盘就能返回成功响应；但与此同时，也带来了持久性方面的新挑战——持有缓冲区的节点可能在变更持久化到存储节点之前就宕机。
* Dynamo 使用一致性哈希把数据存储在一系列节点上。随着时间推移，这些节点处理的流量可能出现不均衡，需要加以控制以维持系统的整体健康。Dynamo 为任意节点的负载设定了一个阈值百分比，如果某个节点在它所服务的流量上超过该阈值，就会被标记为失衡。Dynamo 的分区方法随着时间不断演进，重点在于尽可能均匀地在节点间分布数据。
* 某些应用可能要求对一致性保证有更强的掌控，因此 Dynamo 把存储系统 `N, R & W` 的可配置性交给开发者，从而让开发者控制数据一致性。所以，如果你的应用需要强一致性、且可以接受牺牲写流量，你可以把 `W=N & R=1` 作为一个极端措施——此时更新必须先写入所有节点，才能向客户端返回成功响应。在另一极端，如果你可以接受陈旧结果、但希望写请求尽可能快，则可以把 `W=1`，这样只要更新持久化到哪怕单个节点，写操作就算成功。所有这些控制权都交给了开发者，让他们可以根据需要随时调整。

## Links

- [Distributed Systems](/docs/CS/Distributed/Distributed.md)
- [Partition](/docs/CS/Distributed/Partition.md) — 一致性哈希 + 虚拟节点分区
- [Consensus](/docs/CS/Distributed/Consensus/Consensus.md) — Quorum NWR 可调一致性
- [Time](/docs/CS/Distributed/Time.md) — 向量时钟做因果排序
- [Replica](/docs/CS/Distributed/Replica.md) — 多副本复制与 Sloppy Quorum
- [CAP](/docs/CS/Distributed/CAP.md) — 最终一致 / AP 取向

## References

1. [Dynamo: Amazon’s Highly Available Key-value Store](https://www.allthingsdistributed.com/files/amazon-dynamo-sosp2007.pdf)
2. [Paper Notes: Dynamo – Amazon’s Highly Available Key-value Store](https://distributed-computing-musings.com/2022/05/paper-notes-dynamo-amazons-highly-available-key-value-store/)
