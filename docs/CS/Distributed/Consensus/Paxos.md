## Introduction

Paxos 是一族用于达成共识的分布式算法。

## Basic-Paxos

Paxos 定义了三种角色：**proposer**、**acceptor** 和 **learner**。每个节点可以承担多种角色，甚至全部角色。

- **Proposer** Proposer 可以提议一个值。
- **Acceptor** Acceptor 以某种方式合作选择一个被提议的值。
- **Learner** Learner 可以了解已选择的值。

假设节点之间可以通过发送消息进行通信。
我们使用常用的异步、**非拜占庭模型**，其中：

- 代理以任意速度运行，可能因停止而失败，并可能重启。
  由于所有代理可能在值被选择后失败并重启，除非失败的代理能记住某些信息并重启，否则不可能有解决方案。
- 消息传递可能任意延迟、重复和丢失，但不会被破坏。

假设有一组进程可以提议值。
共识算法确保从提议的值中选择唯一的一个值。
如果没有提议值，则不应选择任何值。
如果已选择某个值，进程应能够了解已选择的值。

共识的安全性要求是：

- 只有被提议的值才能被选择，
- 只选择一个值，并且
- 进程永远不会得知一个值已被选择，除非它确实被选择了。

### Choosing a Value

单个 acceptor 并不令人满意，因为 acceptor 的失败会使任何进一步进展变得不可能。
我们使用多个 acceptor 代理，而非单个 acceptor。
Proposer 向一组 acceptor 发送提议的值。
为了确保只选择一个值，我们可以让足够大的集合由任意多数代理组成。

Paxos 节点必须知道多数是多少个 acceptor。

算法分为以下两个阶段。

|             | proposer                                                                                                                                                                                                                                                                                                                                  | acceptor                                                                                                                                                                                                                                                                                                        |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Phase 1** | Proposer 选择一个提案编号 n，并向多数 acceptor 发送带有编号 n 的 prepare 请求。                                                                                                                                                                                                                                                              | 如果 acceptor 收到编号 n 大于它已响应的任何 prepare 请求的编号的 prepare 请求，则它承诺不再接受任何编号小于 n 的提案，并以它已接受的编号最高的提案（如果有）响应请求。 |
| **Phase 2** | 如果 proposer 从多数 acceptor 收到对其编号为 n 的 prepare 请求的响应，则它向这些 acceptor 中的每一个发送一个 accept 请求，提案编号为 n，值为 v，其中 v 是响应中编号最高的提案的值，或者如果响应未报告任何提案，则是任意值。 | 如果 acceptor 收到编号为 n 的提案的 accept 请求，则它接受该提案，除非它已经响应了编号大于 n 的 prepare 请求。                                                                                                                                       |

Proposer 可以提出多个提案，只要它对每个提案都遵循算法即可。
它可以在协议进行到一半时随时放弃提案。（即使提案的请求和/或响应可能在提案被放弃很久之后才到达目的地，正确性仍然得到维护。）
如果某个 proposer 已开始尝试发出编号更高的提案，那么放弃当前提案可能是个好主意。
因此，如果 acceptor 因已收到编号更高的 prepare 请求而忽略 prepare 或 accept 请求，那么它可能应该通知 proposer，proposer 随后应放弃其提案。
这是一种不影响正确性的性能优化。

### Learning a Chosen Value

要了解一个值已被选择，learner 必须发现某个提案已被多数 acceptor 接受。

Acceptor 可以将其接受响应给一组特定的 distinguished learner，每个 distinguished learner 随后可以在值被选择时通知所有 learner。
使用更大的 distinguished learner 集合提供了更高的可靠性，但代价是更大的通信复杂度。

由于消息丢失，可能值已被选择但没有 learner 知道。
Learner 可以询问 acceptor 它们接受了哪些提案，但 acceptor 的失败可能使得无法知道是否有多数接受了特定提案。
在这种情况下，learner 只有在新的提案被选择时才能知道选择了什么值。
如果 learner 需要知道某个值是否已被选择，它可以让 proposer 使用上述算法发出一个提案。

如果系统的足够部分（proposer、acceptor 和通信网络）正常工作，则可以通过选举单个 distinguished proposer 来实现活性。
FLP 意味着，用于选举 proposer 的可靠算法必须使用随机性或实时性——例如，使用超时。
然而，无论选举成功与否，安全性都得到保证。

在正常操作中，单个服务器被选为 leader，它在共识算法的所有实例中担任 distinguished proposer（唯一尝试发出提案的 proposer）。

在 Paxos 共识算法中，要提议的值直到阶段 2 才被选择。
在完成 proposer 算法的阶段 1 后，要么要提议的值已确定，要么 proposer 可以自由提议任何值。

这种对系统正常操作的讨论假设始终有一个单一的 leader，除了当前 leader 失败和选举新 leader 之间的短暂时期。
在异常情况下，leader 选举可能会失败。
如果没有服务器担任 leader，则不会提议新命令。如果多个服务器认为自己是 leader，那么它们可以在共识算法的同一个实例中提议值，这可能会阻止任何值被选择。
然而，安全性得以保持——两个不同的服务器永远不会对第 i 个状态机命令选择的值产生分歧。选举单一 leader 只是为了确保进展。

由于 leader 失败和选举新 leader 应该是罕见事件，执行状态机命令（即对命令/值达成共识）的有效成本仅是执行共识算法阶段 2 的成本。
可以证明，Paxos 共识算法的阶段 2 具有在存在故障的情况下达成一致的任何算法的最小可能成本。
因此，Paxos 算法本质上是最优的。

Paxos 节点必须是持久的：它们不能忘记自己接受了什么。

一次 Paxos 运行旨在达成单个共识。
一旦达成共识，它就不能进展到另一个共识。

如果服务器集合可以更改，那么必须有某种方式来确定哪些服务器实现了共识算法的哪些实例。
最简单的方法是通过状态机本身。
当前的服务器集合可以作为状态的一部分，并通过普通的状态机命令进行更改。
我们可以允许 leader 领先 α 个命令，方法是让执行共识算法第 $i + \alpha$ 个实例的服务器集合由执行第 i 个状态机命令后的状态指定。
这允许实现任意复杂的重配置算法。

[Revisiting the Paxos algorithm](http://citeseer.ist.psu.edu/viewdoc/download;jsessionid=C6EF80E450719CD5457C0E85CCDD0999?doi=10.1.1.44.5607&rep=rep1&type=pdf)

[Brewer's conjecture and the feasibility of consistent, available, partition-tolerant web services](https://users.ece.cmu.edu/~adrian/731-sp04/readings/GL-cap.pdf)

## Multi-Paxos

### Algorithmic Challenges

**Epoch numbers**

从 master 副本收到请求到该请求导致底层数据库更新之间，该副本可能已失去 master 状态。
它甚至可能已失去 master 状态并重新获得。
我们需要一种机制来可靠地检测 master 变更，并在必要时中止操作。

> 我们通过引入一个全局 epoch number 解决了这个问题，其语义如下。
> 在 master 副本处对 epoch number 的两次请求收到相同的值，当且仅当该副本在两次请求之间的时间间隔内持续担任 master。

**Group membership**

实际系统必须能够处理副本集合的变化。
这被称为 group membership 问题。

**Snapshots**

重复应用共识算法来创建复制日志将导致日志不断增长。
这有两个问题：需要无限量的磁盘空间；更糟的是，可能导致无限长的恢复时间，因为恢复中的副本必须重放可能很长的日志才能完全赶上其他副本。

由于日志通常是应用于某些数据结构的操作序列，因此隐式地（通过重放）代表了该数据结构的一种持久形式，
问题在于为当前的数据结构找到另一种持久表示。
一个显而易见的机制是直接持久化——或者说快照——数据结构，此时不再需要导致当前数据结构状态的日志。
例如，如果数据结构保存在内存中，我们通过将其序列化到磁盘来创建快照。
如果数据结构保存在磁盘上，快照可能只是它的磁盘副本。

副本的持久状态现在包括一个日志和一个快照，必须一致地维护它们。
日志完全在框架的控制之下，而快照格式是特定于应用程序的。
快照机制的某些方面特别值得关注：

- 快照和日志需要相互一致。每个快照需要包含关于其内容相对于容错日志的位置信息。
- 创建快照需要时间，在某些情况下我们不能在创建快照时冻结副本的日志。
- 创建快照可能失败。
- 在追赶过程中，副本将尝试获取缺失的日志记录。
- 我们需要一种机制来定位最近的快照。

Database transactions

Cascade

- Disk Paxos
- Cheap Paxos

## Fast Paxos

- EPaxos

## Vertical Paxos

Vertical Paxos 是 Paxos 算法族的一个变体。
它将共识协议分为两部分，即稳态协议和重配置协议。

- Flexible Paxos
- CASPaxos
- Mencius

## Links

- [Consensus](/docs/CS/Distributed/Consensus/Consensus.md)

## References

1. [The Part-Time Parliament](https://www.microsoft.com/en-us/research/uploads/prod/2016/12/The-Part-Time-Parliament.pdf)
2. [Paxos Made Simple](https://www.microsoft.com/en-us/research/uploads/prod/2016/12/paxos-simple-Copy.pdf)
3. [Paxos Made Live - An Engineering Perspective](https://www.cs.albany.edu/~jhh/courses/readings/chandra.podc07.paxos.pdf)
4. [The Paxos Algorithm](https://www.youtube.com/watch?v=d7nAGI_NZPk&ab_channel=GoogleTechTalks)
5. [Consensus Protocols: Paxos](https://www.the-paper-trail.org/post/2009-02-03-consensus-protocols-paxos/)
6. [Viewstamped Replication: A New Primary Copy Method to Support Highly-Available Distributed Systems](https://pmg.csail.mit.edu/papers/vr.pdf)
7. [Fast Paxos](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/tr-2005-112.pdf)
8. [Cheap Paxos](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/web-dsn-submission.pdf)
9. [Generalized Consensus and Paxos](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/tr-2005-33.pdf)
10. [Vertical Paxos and Primary-Backup Replication](https://www.microsoft.com/en-us/research/wp-content/uploads/2009/05/podc09v6.pdf)
11. [Implementing Replicated Logs with Paxos](https://ongardie.net/static/raft/userstudy/paxos.pdf)
12. [Paxos Made Moderately Complex](https://paxos.systems/)
