## Introduction

PoW（Proof of Work，工作量证明）是一种用**计算成本**来约束提案权、从而在**无许可（permissionless）**网络中达成拜占庭共识的机制。
它最早用于反垃圾邮件（Hashcash），因 Bitcoin/Nakamoto 共识而广为人知。与 [PBFT](/docs/CS/Distributed/Consensus/PBFT.md) 这类
需要固定成员、靠多轮投票达成确定性一致的协议不同，PoW 允许任意节点随时加入退出，用算力竞争出块权，并以**最长链 + 概率收敛**给出最终性。

## Idea

核心是一道「难解但易验证」的密码学难题：

- 提案者（矿工）把待打包的交易、前一区块哈希等数据组成区块头，不断改变其中的随机数 `nonce`，对区块头做哈希（如 Bitcoin 的双 SHA-256）；
- 要求哈希结果小于当前网络目标值 `target`，即出现若干前导零。哈希是单向且分布均匀的，除了暴力枚举没有捷径；
- 谁先找到满足条件的 nonce，谁就有权发布该区块；其他节点一次哈希即可验证答案是否合法。

期望出块时间由全网总算力与难度 `difficulty` 的比值决定，协议周期性调整 target（Bitcoin 每 2016 个区块按实际耗时回调），把平均出块间隔稳定在约 10 分钟。

## Why It Gives Consensus

- **出块权与算力成正比，且要付出真实代价**（电力、硬件）。要持续制造一条被大家接受的替代历史，攻击者必须重做这些区块的工作量证明，成本与其掌握的算力成比例。
- **链选规则：最重/最长链**。节点总是在累计工作量最多的链上延伸。一笔交易所在区块之后又叠上 k 个区块，要回滚它就得在私下重做这 k+1 个区块的 PoW 并赶上诚实链，成功概率随 k 指数衰减。
- **概率最终性**：PoW 不存在「一旦提交永不可改」的确定性终结，交易确认数越多越安全。理论上掌握超过 **50%** 总算力者可重写近期历史（51% 攻击 / double spend），但无法伪造他人签名、也无法凭空铸造不属于他的币。

这与状态机复制里「多数票」的安全论证不同：PBFT 安全依赖诚实节点超过 2/3，PoW 安全依赖恶意算力不占多数，且确认是概率而非瞬时确定的。

## Trade-offs

| 维度 | PoW | PBFT | Raft/Paxos |
| --- | --- | --- | --- |
| 网络类型 | 无许可、匿名可加入 | 许可、成员固定 | 许可、成员可知 |
| 抗拜占庭 | 是（成本约束） | 是（n≥3f+1） | 否，仅崩溃容错 |
| 终结性 | 概率性，随确认数收敛 | 确定 | 确定 |
| 吞吐/延迟 | 低（出块间隔 + 多确认） | 中，O(n²) 通信 | 高 |
| 资源代价 | 极高能耗 | 主要为通信开销 | 低 |
| 典型系统 | Bitcoin、早期 Ethereum | 联盟链/许可 BFT | etcd、[ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md) |

PoW 的代价是**能耗与吞吐瓶颈**：为把无许可网络下的分叉竞争压到可控，只能故意放慢出块、限制区块大小，
因此每秒交易量远低于中心化或许可链系统。这也催生了 PoS（Proof of Stake，以质押资本替代烧电算力）等后继机制。

## Links

- [Consensus](/docs/CS/Distributed/Consensus/Consensus.md)
- [PBFT](/docs/CS/Distributed/Consensus/PBFT.md)
- [Byzantine Generals](/docs/CS/Distributed/Byzantine.md)
- [Raft](/docs/CS/Distributed/Consensus/Raft.md)
- [Bitcoin](/docs/CS/Blockchain/Bitcoin.md) / [Blockchain](/docs/CS/Blockchain/Blockchain.md)

## References

1. [Bitcoin: A Peer-to-Peer Electronic Cash System](https://bitcoin.org/bitcoin.pdf)
2. [Hashcash - A Denial of Service Counter-Measure](http://www.hashcash.org/papers/hashcash.pdf)
