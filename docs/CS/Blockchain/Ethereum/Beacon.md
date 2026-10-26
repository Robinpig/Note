## Introduction

信标链（Beacon Chain）是以太坊的共识层：它不执行交易，只负责**验证者管理、区块提议、投票与最终性**。2020 年 12 月独立上线，2022 年 9 月 **The Merge** 后接管执行层的共识，以太坊从此完全转为 PoS。

这一页讲验证者经济、slot/epoch 时间结构、分叉选择与最终性、MEV 与质押生态。执行层见 [Ethereum](/docs/CS/Blockchain/Ethereum.md)，PoS 的一般原理见 [PoS](/docs/CS/Distributed/Consensus/PoS.md)。

## Validators

成为验证者的门槛是**向存款合约质押 32 ETH**：

- **激活队列**：新验证者按队列逐步激活，防止验证者集合突变；
- **退出队列**：主动退出同样排队，防止大规模同时退出；
- **有效余额（effective balance）**：决定投票权重与收益，以 1 ETH 为粒度；
- **提款凭证**：`0x00` 为 BLS 凭证（旧式，需先转换），`0x01` 为执行层地址，`0x02` 为 Pectra 引入的复利凭证，支持有效余额最高 2048 ETH；
- **罚没（slashing）**：双重投票、环绕投票等可证明的作恶会被罚没部分质押并强制退出；
- **离线惩罚**：普通离线只扣少量收益；若全网长时间无法最终化，会触发**不活跃泄漏（inactivity leak）**，离线验证者的余额被二次方加速扣除。

验证者不是"矿工"：他们不竞争算力，而是被伪随机选中提议区块或加入委员会投票。作恶的代价是已质押的资本，而不是电费。

## Slots and Epochs

```
Slot:   12 秒
Epoch:  32 个 slot = 6.4 分钟
Finality: 2 个 epoch ≈ 12.8 分钟
```

每个 slot 有一个被选中的**提议者**，负责构造并广播区块；同时有一个**委员会**（至少 128 个验证者）对区块投票（attestation）。委员会在每个 epoch 重新洗牌，攻击者无法提前确定并贿赂固定成员。

- **证明（attestation）**：包含对源 checkpoint、目标 checkpoint 与当前链头的投票；
- **同步委员会（sync committee）**：512 个验证者组成，约每 27 小时轮换，为轻客户端提供签名聚合；
- **RANDAO**：用验证者提交的随机数异或生成不可预测的提议者选择；
- **提议者加权**：被选中的概率与有效余额成正比。

时间结构是 PoS 的核心：它把"出块"从概率事件变成确定性排班，从而消除了 PoW 的孤块竞争与算力浪费。

## Fork Choice and Finality

以太坊的共识是两层的：

1. **LMD-GHOST**：选择"最新消息驱动的最重子树"，即拥有最多验证者投票的链头。它负责在分叉时快速收敛；
2. **Casper FFG**：对 epoch 边界（checkpoint）投票。当 2/3 以上质押权重投票支持某个 checkpoint，它被**合理化（justified）**；当连续两个 epoch 都被合理化，前一个被**最终化（finalized）**。

- **最终性**：被最终化的区块不可回滚，除非至少 1/3 质押被罚没；
- **分叉选择**：GHOST 从最后一个最终化 checkpoint 出发，向最重子树延伸；
- **提议者 boost**：提议者在自己 slot 内的区块获得临时加权，减少"提议者因网络延迟错过"的概率；
- **重组**：正常情况下 1–2 个 slot 内稳定，罕见的深度重组会引发社区调查。

这与 PoW 的"概率最终性"不同：PoS 提供**确定性最终性**，代价是引入了弱主观性与长程攻击的新问题。

## Weak Subjectivity

PoS 的新节点不能像 PoW 那样只凭创世块与最长链独立判断——攻击者可以构造一条从创世开始的长链，其中包含大量已退出验证者的旧签名（**长程攻击**）。因此 PoS 需要**弱主观性检查点**：

- 新节点必须从一个近期可信的 checkpoint 同步（checkpoint sync），而不是从创世重放；
- "可信"来自社区共识、区块浏览器、客户端内置的检查点；
- 验证者退出后有**提款延迟**，期间仍可能被罚没，降低"退出后作恶"的收益。

弱主观性不是缺陷，而是 PoS 安全模型的固有部分：**新节点的信任起点是社会共识，而不是纯密码学**。

## MEV and Block Building

区块中的交易排序可以产生价值（套利、清算、三明治攻击），这部分价值称为 **MEV（Maximal Extractable Value）**。以太坊的应对是**提议者-构建者分离（PBS）**：

- **搜索者**：发现套利机会，构造交易包；
- **构建者**：竞价打包区块，把交易包组装成完整区块；
- **中继**：在提议者与构建者之间传递区块，保证提议者看不到完整内容也能安全签名；
- **提议者**：选择出价最高的区块头签名，获得 MEV 分成。

MEV-Boost 是目前的事实标准实现，但它是**协议外**的：依赖中继的信任假设，且可能导致构建者中心化与交易审查。协议内的 ePBS 与 FOCIL（强制包含列表）是后续演进方向。

MEV 不是 bug，而是"谁有权决定顺序"的经济体现。它影响用户成本、验证者收益与抗审查性。

## Withdrawals and Staking

- **Capella（2023-04）**：开放质押提款，验证者可将余额提取到执行层地址；提款由协议自动扫描处理，无需逐个发起交易；
- **流动性质押（LST）**：用户把 ETH 存入协议，获得可流通的质押凭证（如 stETH、rETH），牺牲部分收益换取流动性；
- **质押池**：交易所与托管商的集合质押，降低门槛但增加中心化；
- **再质押（restaking）**：把已质押的 ETH 或其 LST 再次用于其他协议的安全（如 EigenLayer），收益叠加但风险传染；
- **质押集中度**：单一实体或 LST 占比过高会削弱抗审查与共识安全，客户端多样性（执行层 + 共识层）同样关键。

验证者收益 = 协议发行 + 优先费 + MEV。发行量随总质押量调整，质押越多，单验证者收益率越低。

## Risks

- **罚没**：配置错误、密钥重复使用（同一密钥跑两个节点）会导致 slashing；
- **密钥管理**：验证者密钥在线，必须与提款密钥分离，提款密钥离线保存；
- **MEV 审查**：部分中继会过滤特定交易，长期影响抗审查性；
- **客户端 bug**：多数验证者运行同一客户端时，一个共识 bug 可能导致大规模罚没或链分裂；
- **流动性风险**：LST 的赎回依赖协议与二级市场，极端行情下可能折价；
- **再质押风险**：多层协议叠加罚没条件，风险传染难以评估。

## Links

- [Ethereum](/docs/CS/Blockchain/Ethereum.md)
- [PoS](/docs/CS/Distributed/Consensus/PoS.md)
- [EVM](/docs/CS/Blockchain/Ethereum/EVM.md)
- [Security](/docs/CS/Blockchain/Security.md)
- [Layer 2](/docs/CS/Blockchain/Layer2.md)
- [Blockchain](/docs/CS/Blockchain/Blockchain.md)

## References

1. [Combining GHOST and Casper](https://arxiv.org/abs/2003.03011)
2. [Casper the Friendly Finality Gadget](https://arxiv.org/abs/1710.09437)
3. [Ethereum Proof-of-Stake Consensus Specifications](https://github.com/ethereum/consensus-specs)
4. [EIP-7251: Increase the MAX_EFFECTIVE_BALANCE](https://eips.ethereum.org/EIPS/eip-7251)
5. [MEV-Boost Repository](https://github.com/flashbots/mev-boost)
