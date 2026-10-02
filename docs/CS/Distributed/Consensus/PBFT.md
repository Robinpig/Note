## Introduction

PBFT（Practical Byzantine Fault Tolerance）由 Castro 与 Liskov 于 1999 年提出，是第一个能在实际系统中使用的**拜占庭容错**状态机复制协议。
它解决的问题比 [Raft](/docs/CS/Distributed/Consensus/Raft.md)/[Paxos](/docs/CS/Distributed/Consensus/Paxos.md) 更难：
后两者只容忍**崩溃故障**（节点要么正常、要么停机），而 PBFT 容忍节点发送任意、矛盾甚至恶意的消息，即 [Byzantine](/docs/CS/Distributed/Byzantine.md) 故障。

容错门限：节点总数 `n`、拜占庭节点数 `f` 满足 **`n ≥ 3f + 1`** 时协议安全（safety）。
直觉是需要 2f+1 的诚实多数，而在三阶段提交里还要能区分「真的有 2f+1」与「f 个节点撒谎 + 网络分区」，因此比崩溃容错的多数派多预留一份冗余。

## Roles

- **Primary（主节点）**：每个 view 有一个，负责给客户端请求分配序号并驱动协议；其余节点为 **backups（副本）**。
- **View（视图）**：一次「谁当 primary」的任期，概念上类似 Raft 的 term。primary 由 `viewNumber mod n` 轮换确定。
- 所有副本执行相同的状态机：只要大家以相同顺序执行相同请求，状态就保持一致（状态机复制）。

## Three Phases

一个请求在正常情况下经过三阶段达成一致：

1. **Pre-prepare**：primary 给请求分配序号 `n`，广播 `<<PRE-PREPARE,v,n,d>,m>`（v 是视图号，d 是请求摘要）。
   副本接受的前提是视图一致、序号在窗口内、且同一序号没有收到不同摘要。
2. **Prepare**：接受 pre-prepare 的副本向所有人广播 `PREPARE(v,n,d,i)`。当一个节点收到（含自己）**2f+1** 条与 pre-prepare 匹配的 prepare，
   就在日志中把该消息标记为 **prepared**——这保证即使 primary 被换掉，该序号的分配也已被诚实节点见证。
3. **Commit**：随后节点广播 `COMMIT(v,n,d,i)`。当收到 **2f+1** 条匹配的 commit，标记为 **committed-local**，此时可以确定
   「在所有诚实节点上该请求最终都会被提交」，于是按序号执行并把结果返回客户端。

客户端需要从 **f+1 个不同副本**收到相同结果，才能确认这不是某个拜占庭节点编造的回复。

```
client   primary(0)      backups 1..n-1
  | req --->|
  |         |-- pre-prepare ---------->|
  |         |<-- prepare (多播) ------->|   (凑齐 2f+1 → prepared)
  |         |-- commit (多播) -------->|   (凑齐 2f+1 → committed → 执行)
  |<-------- reply (f+1 份相同) --------|
```

## View Change

当 primary 疑似故障（请求迟迟不被分配序号、或发出矛盾消息）时，副本触发 **view change** 切换到下一任 primary，这是 PBFT 的 liveness 机制：

- 超时未推进的副本广播 `VIEW-CHANGE(v+1, ...)`，其中携带自己日志中已 prepared 的最高水位证明（稳定检查点与在途 prepared 集合）；
- 新 primary 收集到 **2f+1** 份 view-change 后，汇总出不会丢失已提交请求的新视图日志，广播 `NEW-VIEW`；
- 新视图里各节点据此重建 pre-prepare，保证**已 committed 的请求跨视图不丢、不乱序**。

这与 Raft 选举新 leader 后靠已提交日志对齐跟随者是同一目标，但要在有 f 个节点可能伪造日志证明的前提下成立，因此证书需要 2f+1 与水位（checkpoint）机制配合，消息与状态开销也更大。

## Trade-offs

| 维度 | PBFT | Raft/Paxos（崩溃容错） | [PoW](/docs/CS/Distributed/Consensus/PoW.md)（Nakamoto） |
| --- | --- | --- | --- |
| 故障模型 | 拜占庭（恶意） | 仅崩溃 | 拜占庭（开放成员） |
| 容错门限 | n ≥ 3f+1 | 多数派 n ≥ 2f+1 | 算力占比 > 50% 攻击 |
| 消息复杂度 | 主流程 O(n²) 多播 | O(n)（leader 单播） | 区块 Gossip |
| 成员规模 | 小（几~几十节点） | 中 | 无许可、可极大 |
| 终结性 | 提交即确定终结 | leader 确认即确定 | 概率性，随确认数收敛 |
| 典型场景 | 联盟链、许可 BFT | etcd/[ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md) 类元数据 | 公有链 |

PBFT 的主要短板是 **O(n²) 通信量**与需要固定的成员集合/配置，因此它主导**联盟链与许可链**（如早期 Hyperledger Fabric、各种 BFT 变体），
难以直接扩展到无许可、上千节点的公网；后续 HotStuff 等通过线性视图切换与流水线把复杂度降下来。

## Links

- [Consensus](/docs/CS/Distributed/Consensus/Consensus.md)
- [Byzantine Generals](/docs/CS/Distributed/Byzantine.md)
- [Raft](/docs/CS/Distributed/Consensus/Raft.md)
- [Paxos](/docs/CS/Distributed/Consensus/Paxos.md)
- [PoW](/docs/CS/Distributed/Consensus/PoW.md)

## References

1. [Practical Byzantine Fault Tolerance (Castro, Liskov, OSDI 1999)](https://www.scs.stanford.edu/nyu/03sp/sched/bfs.pdf)
2. [Practical Byzantine Fault Tolerance and Proactive Recovery](https://www.microsoft.com/en-us/research/wp-content/uploads/2017/01/p398-castro-bft-tocs.pdf)
