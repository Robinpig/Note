## Introduction

挖矿是比特币把"出块权"变成"可验证的稀缺资源"的机制。矿工消耗电力计算哈希，竞争成为下一个区块的提议者；谁先找到满足难度目标的区块头，谁就获得该区块的 coinbase 奖励与手续费。这个过程的本质不是"解数学题换钱"，而是**用外部成本为无准入网络提供 Sybil 抵抗与历史不可篡改性**。

共识层面的完整论证见 [PoW](/docs/CS/Distributed/Consensus/PoW.md)；这一页讲比特币挖矿的工程实现：区块怎么组装、难度怎么调整、奖励怎么分配、矿池与算力集中带来什么问题。

## Block Template

矿工从 mempool 中挑选交易，构造候选区块：

1. **选择交易**：按 sat/vB 从高到低打包，直到达到区块权重上限（4,000,000 weight units），同时满足 sigops 等限制；
2. **构造 coinbase**：第一笔交易，包含区块奖励、手续费、区块高度（BIP34，用于唯一性）以及矿工自定义的 extranonce；
3. **计算 Merkle 根**：对交易列表做 Merkle 树；
4. **填充区块头**：`version`、`prevHash`、`merkleRoot`、`timestamp`、`nBits`、`nonce`；
5. **穷举 nonce**：从 0 到 2^32-1 尝试，找到使 `SHA256D(header) < target` 的值。

4 字节 nonce 很快耗尽，矿工会修改 **extranonce**（coinbase 中的自由字段）或时间戳，从而改变 Merkle 根，获得新的搜索空间。ASIC 内部也常滚动 nonce 与 Merkle 分支，实现持续哈希。

coinbase 有 **100 个区块的成熟期**，防止在链重组时把不存在的奖励花掉。

## Proof of Work Mechanics

```
blockHash = SHA256(SHA256(header))
valid     = blockHash <= target
```

- **target** 由 `nBits` 紧凑编码，越小越难；
- **difficulty** 是相对难度 1 目标的比值：`difficulty = difficulty_1_target / target`，其中 `difficulty_1_target = 0x00000000FFFF0000...`；
- 全网的期望出块时间约为 `difficulty * 2^32 / hashrate`（比特币每约 2^32 次哈希期望命中一次难度 1）。

时间戳规则：必须大于过去 11 个区块时间戳的中位数（MTP），且不超过节点调整后网络时间 2 小时。这条规则防止矿工随意操纵时间，但也允许一定误差。

## Difficulty Adjustment

每 **2016 个区块**（约两周）调整一次难度：

```
newTarget = oldTarget * actualTimespan / 1209600      # 1209600 秒 = 2 周
```

实际耗时被钳制在原目标的 1/4 到 4 倍之间，防止算力骤变导致难度剧烈震荡。调整的目标是让平均出块间隔保持 **10 分钟**。

这是负反馈控制：算力上升 → 出块变快 → 难度上调 → 出块变慢；算力下降则相反。调整周期内的算力波动会造成出块间隔忽快忽慢，这是协议允许的"粗糙"。

## Block Reward and Fees

矿工收入 = **区块补贴 + 交易手续费**：

- 补贴从 50 BTC 开始，每 210,000 个区块减半，当前为 3.125 BTC；
- 手续费取决于区块空间需求，波动极大；
- 补贴约占矿工收入的大部分，但随着减半推进，手续费占比必须上升，否则安全预算不足。

这带来一个结构性张力：**手续费市场越拥堵，矿工收入越高；但用户体验越差**。Layer 2 把大量支付移出主链，长期看会降低主链手续费收入，却又依赖主链的安全性。这个循环是比特币经济模型中最难解的问题之一。

## Mining Hardware

挖矿硬件的演进是一条"专用化"曲线：

| 阶段 | 硬件 | 能效 |
| --- | --- | --- |
| 2009–2010 | CPU | 极低 |
| 2010–2011 | GPU | 数十倍提升 |
| 2011–2013 | FPGA | 更高能效 |
| 2013 至今 | ASIC | J/TH 量级，持续迭代 |

ASIC 只能算 SHA-256，退出挖矿后几乎没有其他用途，因此硬件投资是**沉没成本**，矿工必须持续挖矿回收。能效（J/TH）决定电费占比，电价与场地散热（风冷、水冷、浸没式）决定边际成本。矿场倾向靠近廉价电力：水电丰水期、弃风弃光、伴生气、电网调峰。

## Mining Pools

单个矿工独立出块的概率极低，于是有了矿池：矿工把算力接入矿池，按提交的 share（部分工作量证明）分配收益。

常见分配模式：

- **PPS**：按 share 立即支付固定报酬，矿池承担出块波动风险；
- **FPPS**：PPS + 手续费收益分成；
- **PPLNS**：按最近 N 个 share 分配，矿工与矿池共担波动；
- **PPS+**：补贴按 PPS、手续费按 PPLNS。

矿池带来的风险是**算力集中**：少数矿池控制了大部分算力，理论上可以协调发动 51% 攻击或审查交易。实际上矿工可以随时切换矿池，且矿池并不直接控制矿工的行为，但"算力寡头"仍是比特币去中心化的主要担忧之一。

**Stratum V2** 引入 job negotiation，让矿工（而非矿池）决定区块模板，缓解"矿池决定交易选择"的中心化问题；同时支持算力加密与更高效的二进制协议。

## Attacks and Economics

- **51% 攻击**：掌握多数算力者可重组近期区块、双花、审查交易，但**不能盗取他人币**（没有私钥）、不能凭空增发（其他节点会拒绝）；
- **自私挖矿**（Eyal & Sirer, 2014）：矿工隐藏区块、延迟公布，诱导他人浪费算力，在特定条件下可获得超过算力占比的收益；
- **芬尼攻击（Finney）**：矿工预先挖出一个含自己交易的区块，先向商家付款（未确认），再广播预挖区块覆盖，完成双花；
- **区块扣留攻击**：矿池内恶意矿工提交无效 share 但不公布有效区块，损害矿池收益；
- **交易审查**：大矿池可以选择不打包某些交易，但其他矿工仍可能打包，除非审查者掌握绝对多数；
- **费用狙击**：矿工为获取更高手续费而重组最近的区块，难度越高越不划算。

确认数的意义正在于此：**每多一个确认，重组成本翻倍量级**。交易所、桥、大额收款应根据金额设置阈值，而不是机械地等 6 个确认。

## Energy and Externalities

PoW 的能耗常被拿来与中小国家相比。更准确的评估框架是：

- **能源来源**：矿场追逐廉价电力，常与弃电、伴生气、需求响应结合，可再生占比的估算因口径而异；
- **电网调节**：可中断的矿场可以在用电高峰停机、低谷开机，部分矿区参与需求响应；
- **电子垃圾**：ASIC 迭代快、专用性强，报废处理是真实的环境成本；
- **替代方案**：PoS 用资本替代能源，能耗低几个数量级，但引入了不同的安全假设与中心化风险。

能耗是否"值得"，取决于你如何为"无准入网络中的抗审查结算层"定价。这是一个价值判断，而不是纯技术问题。

## Links

- [Bitcoin](/docs/CS/Blockchain/Bitcoin.md)
- [Transaction](/docs/CS/Blockchain/Bitcoin/Transaction.md)
- [P2P Network](/docs/CS/Blockchain/Bitcoin/P2P.md)
- [PoW](/docs/CS/Distributed/Consensus/PoW.md)
- [Security](/docs/CS/Blockchain/Security.md)
- [Blockchain](/docs/CS/Blockchain/Blockchain.md)

## References

1. [Bitcoin: A Peer-to-Peer Electronic Cash System](https://bitcoin.org/bitcoin.pdf)
2. [Majority is not Enough: Bitcoin Mining is Vulnerable](https://arxiv.org/abs/1311.0243)
3. [BIP152: Compact Block Relay](https://github.com/bitcoin/bips/blob/master/bip-0152.mediawiki)
4. [Stratum V2 Specification](https://stratumprotocol.org/)
