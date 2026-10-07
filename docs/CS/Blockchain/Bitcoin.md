## Introduction

Bitcoin（比特币）是 2008 年化名为中本聪的作者在白皮书《Bitcoin: A Peer-to-Peer Electronic Cash System》中提出的去中心化电子现金系统，2009 年上线。它要解决的核心问题是**不经过任何金融机构，如何在点对点网络中防止电子货币被双花（double-spending）**。答案是：用工作量证明让节点对交易历史（区块链）达成概率一致。区块链的一般结构见 [Blockchain](/docs/CS/Blockchain/Blockchain.md)。

## Transactions and Scripts

- 交易的本质是"**一组输入 + 一组输出**"：输入引用之前交易的未花费输出（UTXO），输出写明收款地址与金额；
- 每个 UTXO 带一段锁定脚本（Script，栈式、非图灵完备、无循环），花费它必须提供解锁脚本（签名）。常见形式是 P2PKH（付到公钥哈希）、P2SH、SegWit（隔离见证，签名数据移出交易体，修复签名延展性并提高容量）；
- 账户模型是 **UTXO 模型**（一组可花费硬币），不是以太坊式的账户余额模型；好处是易并行验证、没有重放概念，代价是复杂交易拼装麻烦。

## Mining and PoW

矿工做三件事：从内存池选交易打包、构造 coinbase 交易（出块奖励，目前 6.25 BTC，每 21 万个区块约 4 年减半）、不断变换 nonce 求满足难度目标的区块头哈希：

```
SHA256D(blockHeader) < target        # target 越小越难
```

难度每 2016 个区块按全网算力调整一次，目标是把平均出块时间维持在 10 分钟。算力只是概率，矿池把一个区块的奖励按提交的部分工作量（share）分给矿工。PoW 的机制、最长链原则与 51% 攻击分析见 [PoW](/docs/CS/Distributed/Consensus/PoW.md)。

## Network and Confirmation

- 交易/区块通过 gossip 在全节点间传播；SPV 轻节点只同步区块头，用 Merkle 路径验证交易包含性；
- **确认数 = 交易所在区块之后又接续的区块数**。接收方等待 6 个确认（约 1 小时）是经验上的安全惯例：攻击者要回滚交易就得重做这些区块的 PoW，代价随确认数指数增长；
- 分叉时节点遵循最长累计工作量链，短链上的交易回到内存池等待重新打包。

## Key Limitations

- **7 TPS 左右**、10 分钟出块——这是安全模型刻意选择的结果，不是工程缺陷；
- 能源消耗与算力集中化（矿场/矿池）是持续争议；
- 地址伪匿名而非匿名：链上图分析可聚类地址，混币/隐私币是应对方向；
- 交易费市场：区块容量有限（SegWit 后约 1–2MB 权重），拥堵时费率飙升；
- 扩展路线：隔离见证 + 闪电网络（Layer 2 支付通道，链下高频小额交易）。

## Links

- [Blockchain](/docs/CS/Blockchain/Blockchain.md)
- [Web3](/docs/CS/Blockchain/Web3.md)
- [PoW](/docs/CS/Distributed/Consensus/PoW.md)
- [Byzantine 问题](/docs/CS/Distributed/Consensus/PBFT.md)

## References

1. [Bitcoin: A Peer-to-Peer Electronic Cash System](https://bitcoin.org/bitcoin.pdf)
2. [Bitcoin Developer Reference](https://developer.bitcoin.org/reference/intro.html)
