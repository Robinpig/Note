## Introduction

Amazon 的电子商务系统由许多相互通信以提供丰富功能的服务组成。
每个服务运行自己的 Dynamo 实例，并基于以下一组假设运行：

* 数据访问和更新通过基于键值的查询模型完成。
  这简化了 Dynamo 的接口，因为它不需要提供执行多表连接操作的复杂查询模型。
* 对存储在 Dynamo 节点上的数据的一致性做出妥协。使用 Dynamo 作为存储层的应用程序使用最终一致性模型，而非严格一致性。
* 在冲突解决中，写入操作被赋予更高优先级。在严格的延迟要求下，写入请求在不解决冲突的情况下被处理，与某个键相关的所有冲突状态都被保留。
  冲突解决在读取时根据策略（如最后写入胜出）进行，或者解决逻辑被移到客户端。
* 系统中的每个 Dynamo 节点与同一系统中的其他节点完全相同。
  这意味着没有具有额外职责的主节点。
  与典型的主-副本模型相比，这使得系统中的节点维护更加容易。

回顾每个挑战时，请记住并欣赏 Dynamo 提供的简单接口，即 `GET(key) & PUT(key, context, object)`，其简单性在解决这些挑战中起到了关键作用。`context` 包含关于 `object` 版本的一些元数据。

* 分区：为了持续扩展存储系统，Dynamo 需要在节点达到容量阈值时将数据分区到多个节点。
  为了实现分区，Dynamo 依赖于 [一致性哈希](https://distributed-computing-musings.com/2022/01/partitioning-consistent-hashing/)。
  一致性哈希的基本实现对不均匀的数据分布存在一些问题。
  因此，Dynamo 在一致性哈希环上使用虚拟节点来更均匀地分布数据。
* 复制：由于高可用性是 Dynamo 的关键需求，持久化到存储层的任何键都存储在 `N` 个节点上。
  复制由协调器执行，该协调器根据一致性哈希算法将键存储在环中分配的节点上，并额外复制到环中顺时针方向的 `N-1` 个节点。
  负责存储该键的 `N` 个节点列表称为 **preference list**。
* 数据版本控制：Dynamo 侧重于提供最终一致性，因此可能出现 `put()` 操作成功但更新未持久化到所有节点的场景。
  同时，Dynamo 将故障视为正常情况，并将故障视为事件而非异常状态。
  这些故障可能是节点故障，也可能是网络中断导致的分区故障。Dynamo 即使在故障状态下也会持久化与键相关的每次更新，并使用 [vector clock](https://distributed-computing-musings.com/2022/05/vector-clocks-keeping-time-in-check/) 来找出与键相关的更新的正确顺序。
  Vector clock 用于发现在多个节点或分区上对某个键发生的更新之间的因果关系。
* 执行数据库操作：Dynamo 中的任何读写操作都由一个节点（也称为协调器节点）处理。
  该节点是 **preference list**（在复制部分讨论）中前 `N` 个节点中第一个可访问的节点。
  为了执行读写操作，协调器节点与 **preference list** 中的所有 `N` 个节点通信。任何发生故障或由于网络故障不可访问的节点将被跳过。
  为了维护一致性，Dynamo 使用 [基于 quorum 的方法](https://distributed-computing-musings.com/2022/01/replication-maintaining-a-quorum/)，包含两个可配置参数 `R` 和 `W`。
  为了维护 quorum，`R` 和 `W` 的设置满足 `R + W > N`。
* 处理临时故障：使用传统的基于 quorum 的方法，Dynamo 面临牺牲存储系统可用性的风险。
  当 **preference list** 中的节点宕机或由于分区故障不可达时，quorum 的要求可能被打破。
  为了克服这一点，Dynamo 使用 [Sloppy Quorum 和 Hinted hand-off](https://distributed-computing-musings.com/2022/05/sloppy-quorum-and-hinted-handoff-quorum-in-the-times-of-failure/)。这样一来，所有读写操作都在前 `N` 个健康节点上执行，这些节点不一定是哈希环上的前 `N` 个节点。
* 处理永久性故障：Hinted handoff 存在一个边界情况，即携带 hinted 消息的节点可能在将消息传输到原始节点之前永久宕机。在这种情况下，我们面临损害存储系统持久性的风险。
  这可能会产生级联效应，导致数据不一致，并且可能直到为时已晚才意识到数据不同步的状态。为了克服这一点，Dynamo 使用 [Merkle tree](https://en.wikipedia.org/wiki/Merkle_tree)，这是一种 anti-entropy 协议。
  Merkle tree 也是区块链技术中一个众所周知的概念。
  Dynamo 使用 Merkle tree 来检测副本节点之间的不一致性，并阻止过时数据在副本节点间传播。
* 成员管理和故障检测：Dynamo 使用 [基于 gossip 的协议](https://en.wikipedia.org/wiki/Gossip_protocol) 向其他节点提供系统中节点的一致视图。
  因此，每当新节点加入系统或节点宕机时，系统中的其他节点使用该协议进行通信，以确定存储系统中节点的状态。
  基于 gossip 的机制对于故障检测也很有用。被标记为故障的节点信息会传播到其他节点，以便在数据库操作期间避免不必要的通信。

从高层次来看，Dynamo 包含三个主要组件：请求协调、成员管理和故障检测，以及本地持久化引擎。

## Learnings

从构建 Dynamo 的过程中得到了一些经验教训，这些教训促使对该数据存储的设计进行了更多改进。
部分经验教训如下：

* 尽管 Dynamo 的主要关注点是可用性，但在 Amazon 的规模下，性能也同样重要。
  某些应用程序在处理关键用户面向流程时可能对性能有更高要求。
  Dynamo 通过提供以数据持久性换取更高性能的选项来满足这一需求。
  这通过提供内存缓冲区来实现，该缓冲区存储客户端更新，并定期写入存储层。
  这还提高了读取性能，因为应用程序将首先从此缓冲区读取，如果未找到记录，再将请求路由到存储。
  这提升了性能，因为每次更新不再需要持久化到磁盘才能发送成功响应，
  但同时也引入了持久性方面的新挑战，因为持有缓冲区的节点可能在更改持久化到存储节点之前宕机。
* Dynamo 使用一致性哈希将数据存储在一组节点上。
  随着时间的推移，这些节点处理流量可能出现不平衡，需要进行检查以维护系统的整体健康。
  Dynamo 为每个节点的负载设定了阈值百分比，如果节点在流量方面超过此阈值，则标记为不平衡。
  Dynamo 的分区方法随着时间的推移不断演进，重点是将数据尽可能均匀地分布在节点之间。
* 某些应用程序可能对一致性保证有更强的要求，因此 Dynamo 通过使存储系统的 `N`、`R` 和 `W` 可配置，将数据一致性的控制权交给开发者。
  因此，如果应用程序需要强一致性，并且可以接受写入流量受损，那么可以将 `W=N` 和 `R=1` 作为极端措施。
  这样一来，更新需要发布到所有节点才能向客户端发送成功响应。
  另一个极端是，如果能够接受过时结果，但希望写入请求尽可能快，可以将 `W=1`，这样只要写入选定节点就成功。
  所有这些控制权都交给开发者，以便他们可以根据需要随时更新。

## Links

## References

1. [Dynamo: Amazon's Highly Available Key-value Store](https://www.allthingsdistributed.com/files/amazon-dynamo-sosp2007.pdf)
2. [Paper Notes: Dynamo – Amazon's Highly Available Key-value Store](https://distributed-computing-musings.com/2022/05/paper-notes-dynamo-amazons-highly-available-key-value-store/)
