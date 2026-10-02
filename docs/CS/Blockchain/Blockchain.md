## Introduction

区块链（Blockchain）是一种**去中心化的分布式账本**：交易被打包成区块，每个区块用密码学哈希指向前一个区块，形成链式结构；数据在对等网络中多副本复制，由共识算法决定哪个版本的链是权威的，篡改历史需要重做后续所有区块的工作量证明并控制多数网络，成本极高。它把"信任中心化机构"替换成"信任密码学 + 多数节点共识"。

## 数据结构

```
区块 N                     区块 N+1
┌──────────────────┐      ┌──────────────────┐
│ Block Header     │      │ Block Header     │
│  prevHash ──────────────┤  prevHash        │
│  merkleRoot      │      │  merkleRoot      │
│  nonce / 难度     │      │  nonce / 难度     │
│  时间戳           │      │  时间戳           │
├──────────────────┤      ├──────────────────┤
│ 交易 tx1 tx2 ...  │      │ 交易 tx1 tx2 ...  │
└──────────────────┘      └──────────────────┘
```

- **哈希链**：`blockHash = H(prevHash || txRoot || nonce ...)`，任何一笔旧交易被改动都会让后续所有哈希失配；
- **Merkle 树**：把区块内交易组织成二叉哈希树，根哈希放进区块头。轻节点（SPV）只需区块头 + 一条 Merkle 路径就能证明某笔交易在区块中，不必存全量交易；
- 哈希函数（比特币双 SHA-256）的抗碰撞性保证"找到同哈希的不同数据"计算上不可行。

## 共识：为什么账本不会分叉失控

没有中心服务器，网络中谁都能广播交易、节点同时收到不同顺序——必须有机制让全网对"下一个区块"达成一致：

- **PoW（工作量证明）**：[Bitcoin](/docs/CS/Blockchain/Bitcoin.md) 采用，矿工解哈希难题竞争出块，最长链代表最多累计工作量，概率最终一致，见 [PoW](/docs/CS/Distributed/Consensus/PoW.md)；
- **PoS（权益证明）**：以太坊转 PoS 后按质押权益选择出块者，不烧电；
- 传统分布式系统的确定性共识（[PBFT](/docs/CS/Distributed/Consensus/PBFT.md)、[Raft](/docs/CS/Distributed/Consensus/Raft.md)）在许可链（Hyperledger Fabric）中使用——它们解决的是已知成员的拜占庭容错，与公链"任意节点可加入"的开放假设不同。

公链共识本质是"经济博弈 + 密码学"：51% 攻击、自私挖矿都是激励层问题，而不只是算法问题。

## 关键性质与代价

| 性质 | 实现方式 |
|------|---------|
| 不可篡改 | 哈希链 + 重做工作量的成本 |
| 去中心化 | P2P 网络、无准入、多副本 |
| 匿名（伪名） | 地址由公钥推导，不直接绑定身份 |
| 可验证 | 全节点独立执行脚本验证每笔交易 |
| 最终性 | 概率最终性（PoW），区块确认数越多越安全 |

代价也同样突出：吞吐低（比特币 7 TPS 量级）、出块延迟（分钟级）、能耗（PoW）、存储增长（全节点）、交易不可逆（汇错无法回滚）、分叉期的双花风险。这也是 Layer2（闪电网络）、PoS、分片等扩展路线存在的原因。

## 生态分层

- **Layer 1**：公链本身（Bitcoin、Ethereum）；
- **Layer 2**：建在 L1 之上的扩展网络（Rollup、状态通道），把大量交易在链下处理后把结果提交主链；
- **智能合约**：以太坊引入的链上可执行代码（Solidity/EVM），催生 DeFi、NFT；应用与所有权叙事见 [Web3](/docs/CS/Blockchain/Web3.md)；
- 不要把"区块链"等同于"发币"：联盟链在供应链金融、存证、跨境支付等场景只使用其多方共享账本与可审计性。

## Links

- [Bitcoin](/docs/CS/Blockchain/Bitcoin.md)
- [Web3](/docs/CS/Blockchain/Web3.md)
- [PoW 共识](/docs/CS/Distributed/Consensus/PoW.md)
- [PBFT](/docs/CS/Distributed/Consensus/PBFT.md)
- [Raft](/docs/CS/Distributed/Consensus/Raft.md)

## References

1. [Blockchain Consensus Algorithms: A Survey](https://arxiv.org/pdf/2001.07091)
2. [Bitcoin: A Peer-to-Peer Electronic Cash System](https://bitcoin.org/bitcoin.pdf)
