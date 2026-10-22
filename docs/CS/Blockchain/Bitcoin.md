## Introduction

Bitcoin（比特币）是 2008 年化名为中本聪的作者在白皮书《Bitcoin: A Peer-to-Peer Electronic Cash System》中提出的去中心化电子现金系统，2009 年 1 月上线。它要解决的核心问题是**不经过任何金融机构，如何在点对点网络中防止电子货币被双花（double-spending）**。答案是：用工作量证明让节点对交易历史达成概率一致。

比特币是区块链的第一个成功实现，也是设计上最克制的一个：它没有通用智能合约、没有账户余额、没有图灵完备脚本。所有工程选择都围绕"让任何人都能低成本验证"展开。这种克制反而使它成为最稳定、最去中心化的公链。一般结构见 [Blockchain](/docs/CS/Blockchain/Blockchain.md) 与 [Architecture](/docs/CS/Blockchain/Architecture.md)。

## Design Overview

比特币的骨架可以拆成五个部件，每个部件都对应一种明确的安全目标：

- **UTXO 账本**：余额不是数字，而是一组未花费输出。交易消耗输入、创建输出，验证只需检查输入存在且未被花费——[Transaction](/docs/CS/Blockchain/Bitcoin/Transaction.md)；
- **脚本**：每个输出带一段锁定脚本，花费时提供解锁脚本。脚本是栈式、无循环、非图灵完备的，刻意限制表达力以降低验证复杂度与攻击面；
- **PoW 挖矿**：矿工竞争寻找满足难度目标的区块头哈希，最长累计工作量链代表权威历史——[Mining](/docs/CS/Blockchain/Bitcoin/Mining.md)；
- **P2P 网络**：交易与区块通过 gossip 传播，全节点独立验证并转发——[P2P Network](/docs/CS/Blockchain/Bitcoin/P2P.md)；
- **钱包与密钥**：所有权完全由私钥决定，没有账户、没有找回机制——[Wallet](/docs/CS/Blockchain/Bitcoin/Wallet.md)。

这五个部件共同构成"验证而非信任"的系统：矿工不拥有你的币，节点不接受不合规的块，钱包不托管资产（除非你选择托管服务）。

## Monetary Policy

比特币的货币政策写死在共识规则里，不依赖任何机构：

| 参数 | 值 |
| --- | --- |
| 总量上限 | 约 2100 万 BTC |
| 初始区块奖励 | 50 BTC |
| 减半周期 | 每 210,000 个区块（约 4 年） |
| 当前区块奖励 | 3.125 BTC（2024 年 4 月减半后） |
| 下一次减半 | 约 2028 年，降至 1.5625 BTC |
| 出块目标 | 10 分钟 |
| 全部挖完 | 约 2140 年 |

减半是通缩压力的来源，也是矿工经济模型的核心变量：随着区块奖励衰减，**手续费必须逐渐接过安全预算**。这条曲线是否成立，是比特币长期安全性的最大争议之一——如果链上交易需求不足，矿工收入下降，算力可能集中或萎缩。

总量上限意味着比特币更像"数字黄金"而不是通胀型货币；它的支付属性依赖 Layer 2，见 [Lightning Network](/docs/CS/Blockchain/Bitcoin/Lightning.md)。

## Transactions

交易的本质是"**一组输入 + 一组输出**"：输入引用之前交易的未花费输出（UTXO），输出写明收款地址与金额。每笔交易必须满足 `sum(inputs) >= sum(outputs)`，差额是矿工手续费。

比特币地址不是账户，而是**锁定脚本的编码**。常见类型：

- **P2PKH**：付到公钥哈希，最经典的 `1...` 地址；
- **P2SH**：付到脚本哈希，支持多签等复杂脚本，`3...` 地址；
- **P2WPKH / P2WSH**：SegWit 原生地址，`bc1q...`，签名数据享受见证折扣；
- **P2TR**：Taproot 地址，`bc1p...`，支持 Schnorr 签名与 MAST。

交易结构、脚本、SegWit、Taproot、手续费机制的完整说明见 [Transaction](/docs/CS/Blockchain/Bitcoin/Transaction.md)。

## Mining and Consensus

矿工做三件事：从内存池选交易打包、构造 coinbase 交易（出块奖励 + 手续费）、不断变换 nonce 求满足难度目标的区块头哈希：

```
SHA256D(blockHeader) < target        # target 越小越难
```

难度每 2016 个区块按全网算力调整一次，目标是把平均出块时间维持在 10 分钟。算力只是概率，矿池把一个区块的奖励按提交的部分工作量（share）分给矿工。

PoW 的机制、最长链原则、51% 攻击与自私挖矿的经济分析见 [PoW](/docs/CS/Distributed/Consensus/PoW.md) 与 [Mining](/docs/CS/Blockchain/Bitcoin/Mining.md)。比特币的共识选择可以概括为：**用能源换取无准入网络中可验证的稀缺性**，代价是吞吐与能耗。

## Network and Confirmation

- 交易/区块通过 gossip 在全节点间传播；SPV 轻节点只同步区块头，用 Merkle 路径验证交易包含性；
- **确认数 = 交易所在区块之后又接续的区块数**。接收方等待 6 个确认（约 1 小时）是经验上的安全惯例：攻击者要回滚交易就得重做这些区块的 PoW，代价随确认数指数增长；
- 分叉时节点遵循最长累计工作量链，短链上的交易回到内存池等待重新打包；
- 大额入账应按金额提高确认阈值；跨链桥与交易所尤其要防范"充值确认后回滚"的双花。

网络层细节（区块传播、紧凑区块、mempool 策略、隐私）见 [P2P Network](/docs/CS/Blockchain/Bitcoin/P2P.md)。

## Wallets and Custody

比特币没有"账号找回"。私钥即所有权，签名即授权：

- **自托管**：软件钱包、硬件钱包、纸钱包，用户独自承担备份与安全责任；
- **多签**：`m-of-n` 脚本把控制权分散到多把钥匙，适合机构金库与联合托管；
- **托管**：交易所与托管商持有私钥，用户持有的是债权而非链上资产；
- **备份**：助记词、描述符、PSBT 工作流，以及继承方案，都是自托管必须提前设计的部分。

密钥、地址、HD 钱包与签名流程见 [Wallet](/docs/CS/Blockchain/Bitcoin/Wallet.md)。

## Forks and Governance

比特币没有"官方"开发组织，协议演进靠 BIP（Bitcoin Improvement Proposal）流程与粗糙共识：

- **软分叉**：收紧规则，旧节点仍接受新块，如 P2SH（2012）、SegWit（2017）、Taproot（2021）；
- **硬分叉**：放宽规则，旧节点拒绝新块，需要全网协调，如 2017 年的 Bitcoin Cash 分裂；
- **区块大小战争**：2015–2017 年围绕扩容路线分裂出 BCH，最终主链选择 SegWit + Layer 2 路线；
- **UASF**：用户激活软分叉，展示节点经济权重对矿工的反制。

治理的默认状态是"什么都不改"：任何有争议的改动都可能造成链分裂与社区撕裂。这既是保守，也是比特币稳定性的来源。

## Ecosystem and Use Cases

- **价值存储**：机构配置、ETF、企业资产负债表；
- **支付**：Layer 2 闪电网络承担高频小额支付，主链承担结算；
- **铭文与 Runes**：2023 年 Ordinals 把数据写入见证字段，2024 年 Runes 协议带动手续费市场，也引发"区块空间该不该用于非金融数据"的争论；
- **侧链与桥**：Liquid、Rootstock 等提供更快的执行或隐私能力，但引入新的信任假设；
- **监管与合规**：KYC/AML、旅行规则、税务申报，链上分析公司通过地址聚类追踪资金。

## Key Limitations

- **7 TPS 左右**、10 分钟出块——这是安全模型刻意选择的结果，不是工程缺陷；
- 能源消耗与算力集中化（矿场/矿池）是持续争议；
- 地址伪匿名而非匿名：链上图分析可聚类地址，混币/隐私币是应对方向；
- 交易费市场：区块容量有限（SegWit 后约 1–2MB 权重），拥堵时费率飙升；
- 扩展路线：隔离见证 + 闪电网络（Layer 2 支付通道，链下高频小额交易）；
- 脚本表达力有限，复杂金融逻辑需要额外协议或侧链，且更容易出现实现漏洞。

## Reading Path

- 想理解"钱怎么在链上表示"：读 [Transaction](/docs/CS/Blockchain/Bitcoin/Transaction.md)；
- 想理解"谁在出块、为什么安全"：读 [Mining](/docs/CS/Blockchain/Bitcoin/Mining.md) 与 [PoW](/docs/CS/Distributed/Consensus/PoW.md)；
- 想理解"交易怎么传播、节点怎么同步"：读 [P2P Network](/docs/CS/Blockchain/Bitcoin/P2P.md)；
- 想自托管资产：读 [Wallet](/docs/CS/Blockchain/Bitcoin/Wallet.md)；
- 想理解小额支付与扩容：读 [Lightning Network](/docs/CS/Blockchain/Bitcoin/Lightning.md) 与 [Layer 2](/docs/CS/Blockchain/Layer2.md)。

## Links

- [Blockchain](/docs/CS/Blockchain/Blockchain.md)
- [Transaction](/docs/CS/Blockchain/Bitcoin/Transaction.md)
- [Mining](/docs/CS/Blockchain/Bitcoin/Mining.md)
- [P2P Network](/docs/CS/Blockchain/Bitcoin/P2P.md)
- [Wallet](/docs/CS/Blockchain/Bitcoin/Wallet.md)
- [Lightning Network](/docs/CS/Blockchain/Bitcoin/Lightning.md)

## References

1. [Bitcoin: A Peer-to-Peer Electronic Cash System](https://bitcoin.org/bitcoin.pdf)
2. [Bitcoin Developer Reference](https://developer.bitcoin.org/reference/intro.html)
3. [BIP Index](https://github.com/bitcoin/bips)
4. [Mastering Bitcoin](https://github.com/bitcoinbook/bitcoinbook)
