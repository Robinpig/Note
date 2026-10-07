## Introduction

共识（Consensus）是容错分布式系统的根本问题：一组节点必须对某个值或一串日志达成一致，且一旦决定就不可更改。它的典型落地是 **replicated state machine**——只要每个节点的状态机按相同顺序执行相同的命令日志，它们对外就表现为一个高可靠的状态机（即使少数节点失效）。

本目录按「容错模型」把共识算法分成两系：

- **崩溃容错（Crash Fault Tolerance）**：节点只会停机、不会作恶，只要多数派存活就能推进。代表是 Paxos、Raft，以及数据库事务里的 2PC/3PC。
- **拜占庭容错（Byzantine Fault Tolerance）**：节点可能任意发送矛盾数据（作恶或遭入侵）。代表是 PBFT，以及区块链用算力/S 权益换来的无许可共识（PoW/PoS）。

两条主线之外，[Consensus](/docs/CS/Distributed/Consensus/Consensus.md) 一文先把「共识问题」本身形式化（Termination / Validity / Agreement 三性质）、讲清 FLP 不可能性，再串起 2PC、3PC、Quorum NWR 这些基础构件，是其余各篇的上游概念页。

## Membership Navigation

- [Consensus](/docs/CS/Distributed/Consensus/Consensus.md) — 共识问题的定义、FLP 不可能性、2PC/3PC、Quorum NWR，以及「许可 vs 无许可」「崩溃容错 vs 拜占庭容错」的模型分野。
- [Paxos](/docs/CS/Distributed/Consensus/Paxos.md) — Lamport 的单值/多值共识家族，理论完备但工程上偏难理解，是后续一切的源头。
- [Raft](/docs/CS/Distributed/Consensus/Raft.md) — 以「可理解性」为设计目标的崩溃容错共识，把问题分解成 leader election、log replication、safety 三块。
- [PBFT](/docs/CS/Distributed/Consensus/PBFT.md) — 实用拜占庭容错，在作恶节点不超过 1/3 时仍能达成一致，是区块链之外最经典的 BFT 算法。
- [PoW](/docs/CS/Distributed/Consensus/PoW.md) — 无许可共识（Proof of Work），用算力成本对抗 Sybil 攻击，让开放网络也能达成弱一致。
- [PoS](/docs/CS/Distributed/Consensus/PoS.md) — 无许可共识（Proof of Stake），以质押资本替代烧电算力。
- [dPoW](/docs/CS/Distributed/Consensus/dPoW.md) — 延迟工作量证明（Delayed Proof of Work），借 Bitcoin/Litecoin 算力为小链提供抗 51% 攻击的安全服务。

## Relationship Axes

共识算法共同服务于三类场景：**leader election**（单主复制里避免脑裂）、**atomic commit**（跨节点事务要么全提交要么全回滚）、以及 replicated state machine 的日志对齐。选算法时先问两个前提：成员集合是否固定可认证（许可 vs 无许可）？节点是否会作恶（崩溃容错 vs 拜占庭容错）？前者决定了要不要额外引入 Sybil 防御，后者决定了能不能直接用 Paxos/Raft。

## Links

- [Distributed Systems](/docs/CS/Distributed/Distributed.md) — 共识在「一致性、复制、容错」全局中的位置
- [Byzantine Generals](/docs/CS/Distributed/Byzantine.md) — 拜占庭问题的形式化与边界
- [Blockchain](/docs/CS/Blockchain/Blockchain.md) — 无许可共识的规模化应用
