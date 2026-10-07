## Introduction

Paxos 是 Lamport 提出的一族分布式共识算法，用于让一组节点就某个值达成一致。它包含单值 Paxos（Basic Paxos）与多值 Paxos（Multi-Paxos）等变体，是后续 Raft、ZAB 等算法的理论源头，但工程上以「难理解」著称。

## Basic-Paxos

Paxos 定义了三个角色：*proposers*（提议者）、*acceptors*（接受者）、*learners*（学习者）。每个节点可同时承担多个角色，甚至全部。

- **Proposers**：提出候选值。
- **Acceptors**：协作从多个提案中选出一个。
- **Learners**：得知最终被选中的值。

Paxos 假设节点通过消息通信，采用经典的**非拜占庭异步模型**：

- 节点以任意速度运行，可能因停机而失效，也可能重启。由于所有节点都可能在某个值被选中后失效并重启，除非某个节点能记住它已接受/已选定的值，否则无解。
- 消息可任意延迟、重复、丢失，但不会被篡改（非拜占庭）。

假设一组进程可提出值。共识算法保证在被提出的多个值中只选出一个；若无人提值，则不选任何值；一旦某值被选中，进程应能学习到该值。

共识的安全要求：

- 只有被提出过的值才能被选中；
- 至多一个值被选中；
- 一个进程绝不会「学到」某个值被选中，除非它确实被选中了。

### Choosing a Value

单一接受者无法满足要求——它一旦失效，整个系统便无法推进。因此使用多个接受者：提议者把候选值发给一组接受者。为保证只选中一个值，我们让「足够大的接受者集合」等于任意多数派（majority）。

Paxos 节点必须知道「多数派」是多少个接受者。算法分两个阶段运行：

| | proposer | acceptor |
| --- | --- | --- |
| **Phase 1** | 提议者选一个提案编号 n，向多数派接受者发送编号为 n 的 prepare 请求。 | 若接受者收到的 prepare 请求编号 n 大于它已响应的任何 prepare 请求，则回应一个承诺：不再接受编号小于 n 的任何提案，并返回它已接受过的编号最大的提案（若有）。 |
| **Phase 2** | 若提议者收到多数派对 prepare(n) 的回应，则向这些接受者发送 accept 请求，提案编号为 n、值为 v；v 取回应中编号最大的已接受提案的值，若回应均未报告任何提案则可为任意值。 | 若接受者收到编号为 n 的 accept 请求，除非它已回应过编号大于 n 的 prepare 请求，否则接受该提案。 |

一个提议者可以发起多个提案，只要对每个提案都遵循上述算法。它也可以在中途随时放弃某个提案（正确性不受影响，即使该提案的请求/响应在放弃后很久才到达）。若已有其它提议者开始发起编号更高的提案，放弃当前提案通常是明智之举。因此，若接受者因已收到更高编号的 prepare 而忽略某个 prepare/accept 请求，它应通知提议者，让其放弃——这是一个不影响正确性的性能优化。

### Learning a Chosen Value

学习者要知道某个值被选中，必须发现该值已被多数派接受。

接受者可以把它们的接受结果回报给一组「指定的学习者」，由其中任一学习者在该值被选中时通知所有学习者。指定的学习者越多，可靠性越高，但通信开销也越大。

由于消息可能丢失，某个值可能已被选中却没有任何学习者知晓。学习者可以主动向接受者询问它们接受了哪些提案，但接受者失效时可能无法确定多数派是否接受了某个提案；此时学习者只能等下一个提案被选中时才能得知。若学习者必须知道某值是否已选中，可让一个提议者发起新提案（沿用上述算法）。

只要系统足够多部分（提议者、接受者、网络）正常工作，通过选出一个唯一的 distinguished proposer（主提议者），即可实现活性。FLP 表明：选举这样的提议者必然依赖随机性或真实时间（如超时），但无论选举成功与否，安全性始终成立。

在正常操作中，系统选出一个 leader，它在所有共识实例中充当 distinguished proposer（唯一发起提案者）。

Basic-Paxos 中，要决定的值在 phase 2 才被选定。提议者完成 phase 1 后，要么值已确定，要么可以自由提议任意值。

上述正常操作假设总有一个 leader，仅在当前 leader 失效与新 leader 选出的短暂窗口内例外。异常情况下 leader 选举可能失败：若无节点充当 leader，则不会有新命令被提议；若多个节点自认 leader，它们会在同一共识实例中各提各的值，可能导致没有任何值被选中。但安全性仍被保持——两个不同的服务器绝不会对「第 i 条状态机命令选中的值」产生分歧。选出单一 leader 只是为了推进，而非为了安全。

由于 leader 失效与重新选举应是罕见事件，执行一条状态机命令（即对命令/值达成共识）的有效代价，就等于只执行共识算法的 phase 2。可以证明，Basic-Paxos 的 phase 2 是在存在故障情况下达成一致代价的理论下界，因此 Paxos 本质上是最优的。

Paxos 节点必须是**持久化**的：它们不能忘记自己接受过什么。

一次 Paxos 运行只达成一个共识；一旦达成共识，无法再推进到下一个共识。

若服务器集合会变化，则必须有一种方式确定由哪些服务器来实现哪些共识实例。最简单的做法是通过状态机自身：把当前服务器集合作为状态的一部分，用普通状态机命令来变更它。通过让第 i 个状态机命令执行后的状态来指定第 i+α 个共识实例的服务器集合，leader 可以超前 α 条命令，从而支持任意复杂的重配置算法。

[Revisiting the Paxos algorithm](http://citeseer.ist.psu.edu/viewdoc/download;jsessionid=C6EF80E450719CD5457C0E85CCDD0999?doi=10.1.1.44.5607&rep=rep1&type=pdf)

[Brewer’s conjecture and the feasibility of consistent, available, partition-tolerant web services](https://users.ece.cmu.edu/~adrian/731-sp04/readings/GL-cap.pdf)

## Multi-Paxos

### Algorithmic Challenges

Multi-Paxos 在工程落地时要解决几类问题，下面挑最关键的几个展开。

#### Master leases

Distinguished proposer（leader）的稳定性决定了协议能否长期高效推进。Master lease 是一种常见优化：leader 向 acceptors 申请一段时间内的"主租约"，在租约有效期内其他节点不得发起新的 proposal，从而省去每次 value 都要重跑 phase-1 的 prepare 开销；租约到期前需续约，过期则允许重新竞选。它本质是"用时间边界换通信量"，但要小心时钟漂移与租约长度对可用性的影响。

#### Epoch numbers

从 master replica 收到请求到该请求真正更新底层数据库的期间，该 replica 可能已失去 master 身份，甚至可能失去后又重新获得。我们需要一种机制来可靠检测 master turnover，并在必要时中止操作。

> 解决办法是引入一个全局 epoch number，语义如下：若 master replica 上两次请求拿到的 epoch number 相同，当且仅当该 replica 在这两次请求之间持续保持 master 身份。

#### Group membership

实际系统必须能处理副本集合的变化，这被称为 group membership 问题。

#### Snapshots

反复应用共识算法来维护复制日志，会导致日志无限增长，带来两个问题：需要无界的磁盘空间；更糟的是，恢复中的副本必须重放可能很长的日志才能追上其它副本，导致恢复时间无界。

由于日志通常是对某个数据结构施加操作序列，并通过重放隐式表示该数据结构的持久化形态，问题就转化为：为该数据结构寻找另一种持久化表示。最直接的机制是把数据结构本身持久化（snapshot），此后到达当前状态所需的操作日志便不再必要。例如数据结构在内存中，则序列化到磁盘即为快照；若在磁盘上，则快照可能只是其磁盘副本。

副本的持久化状态由此包含一份日志与一份快照，二者须保持一致。日志完全由框架控制，而快照格式由应用定义。快照机制中几个值得关注的点：

- 快照与日志须相互一致：每个快照都需记录它与故障容错日志的相对位置信息。
- 生成快照需要时间，某些场景下无法在快照期间冻结副本日志。
- 快照本身可能失败。
- 追赶（catch-up）期间，副本会尝试获取缺失的日志记录。
- 需要一种机制来定位最近的快照。

与单值 Paxos 一样，Multi-Paxos 也衍生出针对不同故障模型与部署形态的变体，常见的有：

- **Disk Paxos**：将 acceptor 状态放在磁盘，可容忍接受者内存丢失。
- **Cheap Paxos**：用少量辅助节点降低多数派所需的全量节点数。

## Fast Paxos

Fast Paxos 由 Lamport 提出，旨在通过让 acceptor 在 fast round 里直接接受提案、减少到达一致所需的消息延迟（理想情况下只需 1 轮而非 2 轮）。它在 phase-2 引入 "any" 值协调以处理冲突，代价是安全性论证更复杂、需要更大的 quorum。

- **EPaxos（Egalitarian Paxos）**：由 CMU/IBM Research 提出，是一种无主（leaderless）、对网络延迟不敏感的共识。每个副本都可独立发起提案，通过依赖图的「序贯化」在乱序提交时仍能保证一致性，特别适合跨地域部署。

## Vertical Paxos

Vertical Paxos 是 Paxos 家族的一个变体，将共识协议拆分为两部分：稳态协议（steady state protocol）与重配置协议（reconfiguration protocol）。

- **Flexible Paxos**：放宽了「phase-1 quorum 与 phase-2 quorum 必须相交」的经典约束，允许二者分别选取，只要它们的交集非空即可，从而在不牺牲安全性的前提下提升灵活性。
- **CASPaxos**：一种无领袖（leaderless）、基于 Paxos 的共识方案，用「状态机复制 + 因果收敛」的思路实现集群成员的动态变更，适合强一致的配置存储。
- **Mencius**：由微软研究院提出，针对多节点/多核场景优化吞吐的 Paxos 变体，通过让不同的 leader 轮流负责不同实例来消除冲突。

## Links

- [Consensus](/docs/CS/Distributed/Consensus/Consensus.md)
- [Raft](/docs/CS/Distributed/Consensus/Raft.md) — 以可理解性为设计目标的崩溃容错共识，Paxos 之后的主流落地选择

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
