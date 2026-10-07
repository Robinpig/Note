## Introduction

PoS（Proof of Stake，权益证明）是一种用**质押资本**来约束提案权、从而在**无许可（permissionless）**网络中达成拜占庭共识的机制。它是 PoW 之后最主流的区块链共识家族，核心思想是用「锁仓 stake」替代「烧电算力」作为 Sybil 防御与出块权重来源。

与 [PoW](/docs/CS/Distributed/Consensus/PoW.md) 用算力竞争出块不同，PoS 按节点质押的代币数量（或币龄）成比例地分配出块/投票权，并以**罚没（slashing）**机制惩罚作恶，弥补了 PoW 天然不具备的「作恶可被追责」特性。在 [Consensus](/docs/CS/Distributed/Consensus/Consensus.md) 的「许可 vs 无许可」坐标里，PoS 与 PoW 同属无许可阵营，但把成本从外部能源迁移到了链内经济头寸。

## Idea

- **出块/投票权与 stake 成正比**：节点锁定一定数量的代币作为抵押，抵押越多，被选中提议下一个区块的概率越高（或投票权重越大）。这把「谁能影响共识」从外部算力转化为链内经济头寸。
- **Validator 替代 Miner**：参与者称为 validator（验证者）而非 miner；要成为 validator 通常需质押最低门槛（如以太坊需 32 ETH）。
- **Slashing（罚没）**：若 validator 表现出可被惩罚的行为（如在同一高度对两个冲突区块投票、或长期离线），协议会没收其部分或全部质押。这是 PoS 解决「nothing-at-stake」的关键装置——作恶有真实经济代价。

## Key Differences from PoW

| 维度 | PoW | PoS |
| --- | --- | --- |
| 提案权来源 | 算力（外部、可消耗的能源） | stake（链内、锁定的资本） |
| 抗 Sybil | 成本 = 电费/硬件 | 成本 = 质押资本的机会成本 |
| 攻击代价 | 需掌握 >50% 算力 | 需掌握 >1/3（BFT 类）或 >50%（链选类）stake，且攻击会自损质押价值 |
| 能耗 | 极高 | 极低 |
| Nothing-at-stake | 不存在（算力只能投一条链） | 原生存在，靠 slashing 化解 |

## Nothing-at-stake Problem

PoW 中矿工的算力物理上只能用于一条链，因此在分叉时理性选择是「全力以赴押注一条」。PoS 里 validator 的 stake 可以同时投在多套历史上而几乎零成本——若在每条分叉上都投票，无论哪条最终胜出都能获得奖励，于是没有动机去收敛到单一历史，这会导致共识无法稳定。解决手段：

- **Slashing**：对「双重投票 / 环绕投票」等可归因的恶意行为进行罚没；
- **Finality gadget**：引入明确的终结点（如 Casper FFG 的 checkpoint 投票），越过终结点的回滚需罚没大量 stake，使攻击代价陡增。

## Mainstream Implementations

- **Peercoin（2012）**：最早的 PoS 加密货币之一（Sunny King 等），以「币龄（coin age）」加权出块权，是最早尝试用 stake 替代算力的方案。
- **Nxt（2013）**：纯 PoS，出块权完全由账户余额随机抽签决定，无 PoW 预热阶段。
- **以太坊 Casper**：以太坊从 PoW 迁移到 PoS 的路线，分 Casper FFG（叠加在 PoW 上的 finality gadget）与 2022 年的 The Merge（完全转 PoS）。validator 需质押 32 ETH，作恶触发 slashing。
- **Cardano Ouroboros**：IOHK / Charles Hoskinson 团队提出的、首个被形式化证明安全的 PoS 协议族（Ouroboros / Praos / Genesis），采用基于时间的 slot/epoch 与可验证随机函数（VRF）选 leader。
- **Tendermint / CometBFT**：BFT-style PoS，validator 集合固定且需 2/3 投票达成共识，提供即时最终性（PBFT 思路 + stake 权重），是 Cosmos 等链的基础。

## Links

- [Consensus](/docs/CS/Distributed/Consensus/Consensus.md) — 共识问题形式化与 FLP 不可能性
- [PoW](/docs/CS/Distributed/Consensus/PoW.md) — 无许可网络的工作量证明（PoS 的前身与对照）
- [PBFT](/docs/CS/Distributed/Consensus/PBFT.md) — 许可式拜占庭容错，与 BFT-style PoS 思路相通
- [Byzantine Generals](/docs/CS/Distributed/Byzantine.md)
- [Blockchain](/docs/CS/Blockchain/Blockchain.md)

## References

1. [Bitcoin: A Peer-to-Peer Electronic Cash System](https://bitcoin.org/bitcoin.pdf)
2. [Casper the Friendly Finality Gadget](https://arxiv.org/abs/1710.09437)
3. [Ouroboros: A Provably Secure Proof-of-Stake Blockchain Protocol](https://eprint.iacr.org/2016/889.pdf)
4. [The latest gossip on BFT consensus（Tendermint）](https://arxiv.org/abs/1807.04938)
