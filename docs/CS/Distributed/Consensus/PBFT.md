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

## Fault Tolerance Bound

为什么恰好是 `n ≥ 3f + 1`？论证建立在**法定多数（quorum）必然相交**之上：每个阶段里节点只有在看到 `2f+1` 张匹配消息（一个 quorum certificate，QC）后才会行动。两个这样的法定多数必然至少重叠一个诚实节点：

```
|Q1 ∩ Q2| = (2f+1) + (2f+1) - n = 4f + 2 - n
```

要让重叠 ≥ 1（即诚实节点不可能被两份互相矛盾的"同一序号真相"误导），需 `4f+2 - n ≥ 1` → `n ≤ 4f+1` → 取整得 `n ≥ 3f+1`。等价的直觉是：在 `f` 个拜占庭节点存在时，`2f+1` 是"仍至少含一个诚实节点的最小多数"（`2f+1 - f = f+1 ≥ 1`），而两个这样的多数必须相交——这正是一张 prepared / committed 证书能在全网 unambiguously 成立的原因。

这比崩溃容错严格更强：崩溃故障下非故障节点永远诚实、不会投出矛盾票，因此简单多数 `n ≥ 2f+1` 即可。

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

## Checkpoint and Garbage Collection

副本会持续累积 pre-prepare/prepare/commit 消息日志。为限制内存占用并让落后节点追平，PBFT 周期性地安装一个 **stable checkpoint（稳定检查点）**：

- 每完成 `K` 个请求（如 100），副本计算自身应用状态的摘要并广播 `CHECKPOINT(n, d, i)`。
- 当收集到 `2f+1` 张对同一 `n`、同一摘要的 `CHECKPOINT` 后，该检查点成为**稳定**的——全网就"序号 `n` 之前的状态"达成一致。

**低/高水位** `h` 与 `H = h + L`（`L` 为 `K` 的整数倍，如 2K）界定活跃窗口：

- `h` = 最新稳定检查点的序号（low water mark）。
- primary 不得为超过 `H` 的序号分配编号（high water mark）。副本一旦推进到 `H` 就停止发放更大序号，直到 `h` 前移——防止快副本无限领先、日志膨胀。

稳定检查点之后、所有低于 `h` 的消息日志都可被丢弃（**garbage collection**）。晚加入或掉队的节点通过 **state transfer（状态迁移）** 向对等方索取"最新稳定检查点 + 其上日志"，从而在不必重放整段历史的前提下重新加入共识。

## Optimizations

- **认证信道 vs 数字签名**：原协议对每条消息使用数字签名以保证不可抵赖。在固定成员的许可场景里，点对点**认证信道上的 MAC** 便宜得多（如 BFT-SMaRt 的默认做法），代价是非抵赖性变弱——节点无法向第三方证明"某节点说过某话"。
- **请求批处理（batching）**：primary 可把多个客户端请求聚成单个 pre-prepare、共用一个摘要，把 O(n²) 多播成本摊到整批上，吞吐可数量级提升。
- **应答缓存 / 幂等**：副本把每条应答绑定单调递增的每客户端 `sequence number` 并缓存最近结果；客户端超时时重发会被直接从缓存应答，无需重新执行，使重传安全。

## Message Complexity

单条请求在正常路径上的消息量：

| 阶段 | 发出条数（全网） | 说明 |
| --- | --- | --- |
| pre-prepare | 1 | 仅 primary 广播一次 |
| prepare | `n − 1` 个发送方 × 广播 ≈ `n(n − 1)` 次传递 | 每个 backup 各发 1 条 |
| commit | `n − 1` 个发送方 × 广播 ≈ `n(n − 1)` 次传递 | 同上 |
| reply | `f + 1` 份（客户端收集） | 仅回客户端 |

合计约 `2n² − 2n + 1`，即 **O(n²)**；对比 [Raft](/docs/CS/Distributed/Consensus/Raft.md) 的 leader 单播 + 心跳为 **O(n)**。这是 PBFT 难以扩展到上百节点的根本原因。视图切换时每个副本都要携带在途日志证明广播 `VIEW-CHANGE`，最坏同样 O(n²) 甚至更重——也正是 HotStuff、SBFT 把视图切换与证书做成**线性**的主要动机。

## Relation to Viewstamped Replication

PBFT 不是凭空而来，它与 **Viewstamped Replication（VR）** 结构同构：

- VR 由 Oki & Liskov 于 1988 年提出，Liskov & Cowling 在 2012 年给出清晰重述；它是一个**崩溃容错（CFT）**的状态机复制协议：primary/backup + view + view change + 日志复制，容错 `n ≥ 2f + 1`，复杂度 O(n)。
- PBFT 可视为"**拜占庭化了的 VR**"：把故障模型从"节点只崩溃"换成"节点任意作恶"，于是 (1) 容错从 `2f + 1` 提升到 `3f + 1`；(2) 增加 pre-prepare 阶段以让"primary 分配的全局序号"被诚实副本显式见证；(3) 用 2f+1 证书替代简单多数派。
- Liskov 后来也承认，二者本质是**同一套复制协议、换了不同的故障模型**。这解释了为什么经典 CFT 复制（VR / Paxos / Raft）与 BFT 复制一脉相承——差异主要在故障模型与 quorum 大小，而非核心骨架。详见 [Byzantine Generals](/docs/CS/Distributed/Byzantine.md) 与 [Consensus](/docs/CS/Distributed/Consensus/Consensus.md)。

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

## From PBFT to Modern BFT

PBFT 的 O(n²) 视图切换是它主要的扩展天花板。后续协议保留三阶段内核、但削减视图切换开销：

| 协议 | 关键改进 | 视图切换复杂度 | 代表场景 |
| --- | --- | --- | --- |
| PBFT | 基线：三阶段 + 2f+1 证书 | O(n²)（每副本广播 view-change） | 联盟链、存储复制 |
| BFT-SMaRt | 主驱动 + MAC 优化、流水线 | 接近 O(n) | Java 库、企业系统 |
| Tendermint / CometBFT | 锁定 + 提交两轮、链状打包 | O(n) 每轮 | Cosmos 生态 |
| HotStuff | 门限签名、线性视图切换、流水线 | O(n) 且轮次常数 | Diem/Libra、部分联盟链 |
| SBFT | collector + 门限签名、乐观快路径、双模视图切换 | O(n) | 大规模去中心化信任（200+ 副本） |

HotStuff 的突破在于把"收集 2f+1 张签名"换成**门限签名（threshold signature）**：任一法定多数聚合成单条短证书，使视图切换与正常提交都只需 O(n) 消息、常数轮次，从而把 PBFT 家族带入可上百节点的范围。**SBFT**（Gueta et al., DSN 2019）沿同一思路用 collector 收集 + 门限签名把证书聚合成单条短证明，并引入乐观快路径（fast path）与首个正确的**双模视图切换**（快/慢路径无需真正切视图即可切换），在 200+ 副本、f=64 的部署上实测吞吐约为高度优化 PBFT 的 2 倍。

另一条增强线是 **Proactive Recovery**（Castro & Liskov, TOCS 2002，见 References）：周期性刷新副本的密钥与内存状态，把"被攻破节点"的破坏窗口限制在一个 checkpoint 周期内，使 PBFT 能容忍**自适应移动攻击**（攻击者逐个攻破节点），而不只是静态的 f 个故障。

## Links

- [Consensus](/docs/CS/Distributed/Consensus/Consensus.md)
- [Byzantine Generals](/docs/CS/Distributed/Byzantine.md)
- [Raft](/docs/CS/Distributed/Consensus/Raft.md)
- [Paxos](/docs/CS/Distributed/Consensus/Paxos.md)
- [PoW](/docs/CS/Distributed/Consensus/PoW.md)

## References

1. [Practical Byzantine Fault Tolerance (Castro, Liskov, OSDI 1999)](https://www.scs.stanford.edu/nyu/03sp/sched/bfs.pdf)
2. [Practical Byzantine Fault Tolerance and Proactive Recovery (Castro, Liskov, TOCS 2002)](https://www.microsoft.com/en-us/research/wp-content/uploads/2017/01/p398-castro-bft-tocs.pdf)
3. [HotStuff: BFT Consensus in the Lens of Blockchain (Yin, Malkhi, Reiter, Gueta, Abraham, PODC 2019)](https://arxiv.org/abs/1803.05069)
4. [Viewstamped Replication Revisited (Liskov, Cowling, MIT-CSAIL-TR-2012-021)](https://www.pmg.csail.mit.edu/papers/vr-revisited.pdf)
5. [State Machine Replication for the Masses with BFT-SMART (Bessani, Sousa, Alchieri, DSN 2014)](https://doi.org/10.1109/DSN.2014.43)
6. [SBFT: A Scalable and Decentralized Trust Infrastructure (Gueta et al., DSN 2019)](https://doi.org/10.1109/DSN.2019.00063)
7. [Tendermint: Consensus without Mining (Kwon, 2014)](https://tendermint.com/static/docs/tendermint.pdf)
