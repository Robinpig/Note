## Introduction

区块链（Blockchain）是一种**去中心化的分布式账本**：交易被打包成区块，每个区块用密码学哈希指向前一个区块，形成链式结构；数据在对等网络中多副本复制，由共识算法决定哪个版本的链是权威的。篡改历史需要重写后续所有区块并控制多数网络资源，成本极高。它把"信任中心化机构"替换成"信任密码学 + 多数节点共识"。

理解区块链的关键是先看清它替代了什么：传统账本里，写权限属于一个可信主体，用户只能事后审计；区块链把写权限交给一套公开规则，让互不信任的参与者共同维护同一份历史。代价是性能、隐私、可升级性和治理复杂度。**它不是更快的数据库，而是一种在信任缺位时仍能达成一致的组织方式**。

## Trust Model

区块链解决的不是"存储"问题，而是**在没有可信第三方时，多个互不信任的主体如何对同一份状态历史达成一致**。这个前提决定了它的全部设计取舍：

- **开放准入**：任何节点可以匿名加入、同步、验证，因此不能用"已知成员 + 投票"的 BFT 协议直接扩展到公网；
- **激励相容**：参与者不一定诚实，但必须让"作恶成本 > 作恶收益"，共识因此带有经济博弈成分；
- **可验证而非可信任**：每个全节点独立执行并验证全部规则，任何不遵守规则的块都会被拒绝；
- **不可篡改靠代价**：不是物理不可删，而是改写历史需要付出比诚实维护更高的资源成本。

如果系统里存在一个所有人都信任的运营方，或者参与者集合固定且互相认识，那么数据库加审计日志通常是更便宜、更快的选择，详见 [Comparison](/docs/CS/Blockchain/Comparison.md)。

## Data Structure

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

区块头很小、区块体很大，这个分离是轻客户端、证明系统和数据可用性采样的共同基础。以太坊还把"状态根"放进区块头，使账户状态也可以被证明，代价是状态树的维护成本高得多。细节见 [Architecture](/docs/CS/Blockchain/Architecture.md)。

## Consensus and Finality

没有中心服务器，网络中谁都能广播交易、节点同时收到不同顺序——必须有机制让全网对"下一个区块"达成一致：

- **PoW（工作量证明）**：[Bitcoin](/docs/CS/Blockchain/Bitcoin.md) 采用，矿工解哈希难题竞争出块，最长链代表最多累计工作量，概率最终一致，见 [PoW](/docs/CS/Distributed/Consensus/PoW.md)；
- **PoS（权益证明）**：以太坊转 PoS 后按质押权益选择出块者，不烧电，并用罚没与终局性 gadget 给出确定性终结，见 [PoS](/docs/CS/Distributed/Consensus/PoS.md)；
- **BFT 类共识**：传统分布式系统的确定性共识（[PBFT](/docs/CS/Distributed/Consensus/PBFT.md)、[Raft](/docs/CS/Distributed/Consensus/Raft.md)）在许可链中使用——它们解决的是已知成员的拜占庭容错，与公链"任意节点可加入"的开放假设不同。

两种最终性要分清：**概率最终性**（PoW，确认数越多越安全，理论上可回滚）与**确定性最终性**（BFT 类、PoS 的 finality gadget，一旦终结就不可回滚）。公链共识本质是"经济博弈 + 密码学"：51% 攻击、自私挖矿都是激励层问题，而不只是算法问题。

## Execution and State

账本只记录"谁转给谁多少"时，状态模型相对简单；一旦要在链上运行通用程序，就需要明确的状态与执行模型：

- **UTXO 模型**：比特币把余额表示为一组未花费输出，交易消耗旧输出、产生新输出，验证可并行、天然防重放，但复杂合约拼装困难，见 [Transaction](/docs/CS/Blockchain/Bitcoin/Transaction.md)；
- **账户模型**：以太坊维护全局账户状态（余额、nonce、代码、存储），交易按顺序改变状态，表达力强但引入状态膨胀与顺序依赖，见 [Ethereum](/docs/CS/Blockchain/Ethereum.md)；
- **智能合约**：部署在链上的确定性程序，由虚拟机沙箱执行、按 gas 计量，规则公开且不可单方修改，见 [Smart Contract](/docs/CS/Blockchain/SmartContract.md)。

状态机复制是共同本质：所有节点从相同初始状态出发，按相同顺序执行相同交易，得到相同结果。共识负责定序，执行负责转移状态。

## Scaling

公链的性能瓶颈来自共识与数据复制，而不是 CPU：每个全节点都要下载、验证、存储全部数据，因此提高吞吐会直接抬高节点门槛、损害去中心化。扩展路线因此分两层：

- **Layer 1**：更大的区块、更好的编码、分片、数据可用性采样，属于"改底层"；
- **Layer 2**：把执行搬到链下或独立链，只把结果与数据提交回主链，包括状态通道、侧链、Rollup，见 [Layer 2](/docs/CS/Blockchain/Layer2.md)；
- **密码学加速**：用零知识证明把"重复执行"压缩成"验证一个短证明"，把验证成本与计算量解耦，见 [Zero-Knowledge Proof](/docs/CS/Blockchain/ZKProof.md)。

行业当前的共识是 **rollup-centric**：L1 负责定序、结算与数据可用性，L2 负责执行与扩容。Rollup 的瓶颈随后转移到数据发布成本，于是有了 EIP-4844 的 blob 与 PeerDAS。

## Security and Economics

区块链的安全边界远不止共识算法：

- **共识层**：51% 攻击、自私挖矿、长程攻击、日蚀攻击，见 [Security](/docs/CS/Blockchain/Security.md)；
- **应用层**：重入、预言机操纵、闪电贷、权限配置错误，见 [DeFi and NFT](/docs/CS/Blockchain/Web3/DeFi_and_NFT.md)；
- **跨链层**：桥是历史上损失最集中的环节，锁仓-铸造模型把两条链的安全假设绑定在一起；
- **密钥层**：私钥泄露、钓鱼、供应链攻击无法靠协议挽回，见 [Wallet](/docs/CS/Blockchain/Bitcoin/Wallet.md)；
- **经济层**：MEV、流动性挖矿、治理攻击，把协议激励变成可套利的市场。

一个反复出现的教训是：**系统安全性等于最弱的那一环**，而不是共识算法那一段。审计、形式化验证、多签与时间锁只能降低概率，不能消除风险。

## Enterprise and Consortium

公链不是唯一形态。联盟链把准入、身份与隐私做成可配置项，用 BFT 类共识换取确定性与吞吐，适合供应链金融、贸易融资、存证、跨境支付等"多方共享账本"场景：

- 不发行代币、不需要无许可激励；
- 参与者身份已知，可以用 PBFT 及其变体做到秒级确定性最终性；
- 数据隐私靠通道、私有数据集合、交易隐私管理器实现。

Hyperledger Fabric、Hyperledger Besu、Corda 的差异与选型见 [Permissioned Blockchain](/docs/CS/Blockchain/Permissioned.md)。**不要把"区块链"等同于"发币"**，联盟链使用的是多方共享账本与可审计性，而非代币经济。

## Ecosystem

- **Layer 1**：公链本身（Bitcoin、Ethereum）；
- **Layer 2**：建在 L1 之上的扩展网络（Rollup、状态通道），把大量交易在链下处理后把结果提交主链；
- **智能合约**：以太坊引入的链上可执行代码（Solidity/EVM），催生 DeFi、NFT；
- **Token**：同质化代币、NFT、稳定币、生息凭证，是链上经济的记账单位，见 [Token](/docs/CS/Blockchain/Token.md)；
- **Web3**：钱包、身份、DAO、去中心化存储与索引，是应用层的组织方式，见 [Web3](/docs/CS/Blockchain/Web3.md)；
- **链下依赖**：RPC、索引器、存储、预言机、桥与前端托管，往往比链本身更中心化，见 [Infrastructure](/docs/CS/Blockchain/Web3/Infrastructure.md)。

## Reading Path

本子树按"基础 → 实例 → 执行 → 扩容 → 生态 → 安全"组织，建议顺序阅读：

- 先读 [Architecture](/docs/CS/Blockchain/Architecture.md)，建立区块、Merkle、状态、分叉、数据可用性的共同语言；
- 再看两个最典型的实例：[Bitcoin](/docs/CS/Blockchain/Bitcoin.md) 理解 UTXO 与 PoW 的极简设计，[Ethereum](/docs/CS/Blockchain/Ethereum.md) 理解账户模型、EVM 与 PoS；
- 接着读 [Smart Contract](/docs/CS/Blockchain/SmartContract.md) 与 [EVM](/docs/CS/Blockchain/Ethereum/EVM.md)，理解链上程序的执行与成本；
- 扩容读 [Layer 2](/docs/CS/Blockchain/Layer2.md) 与 [Zero-Knowledge Proof](/docs/CS/Blockchain/ZKProof.md)；
- 生态读 [Token](/docs/CS/Blockchain/Token.md) 与 [Web3](/docs/CS/Blockchain/Web3.md)；
- 落地与风险读 [Security](/docs/CS/Blockchain/Security.md)、[Permissioned Blockchain](/docs/CS/Blockchain/Permissioned.md) 与 [Comparison](/docs/CS/Blockchain/Comparison.md)。

## Links

- [Architecture](/docs/CS/Blockchain/Architecture.md)
- [Bitcoin](/docs/CS/Blockchain/Bitcoin.md)
- [Ethereum](/docs/CS/Blockchain/Ethereum.md)
- [Layer 2](/docs/CS/Blockchain/Layer2.md)
- [Security](/docs/CS/Blockchain/Security.md)
- [Comparison](/docs/CS/Blockchain/Comparison.md)

## References

1. [Bitcoin: A Peer-to-Peer Electronic Cash System](https://bitcoin.org/bitcoin.pdf)
2. [Ethereum Whitepaper](https://ethereum.org/en/whitepaper/)
3. [Blockchain Consensus Algorithms: A Survey](https://arxiv.org/pdf/2001.07091)
4. [Bitcoin Developer Guide](https://developer.bitcoin.org/devguide/)
