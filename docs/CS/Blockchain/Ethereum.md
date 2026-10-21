## Introduction

Ethereum（以太坊）由 Vitalik Buterin 等人在 2013 年提出，2015 年上线。它的核心创新不是"另一种币"，而是**图灵完备的链上执行环境**：任何人都可以部署一段确定性程序（智能合约），由全网节点执行，执行结果与状态变化被共识确认。

这使以太坊从"电子现金"变成"世界计算机 / 状态机"：代币、借贷、交易、身份、NFT、Rollup 都建立在同一个状态与执行层上。代价是复杂度、状态膨胀与攻击面显著大于比特币。区块与状态的基础见 [Architecture](/docs/CS/Blockchain/Architecture.md)。

## Account Model

以太坊用**账户**代替 UTXO。每个地址有四个字段：

| 字段 | 含义 |
| --- | --- |
| nonce | EOA 为已发送交易数，合约账户为已创建合约数 |
| balance | 余额（wei，1 ETH = 10^18 wei） |
| storageRoot | 合约存储的 Merkle Patricia Trie 根 |
| codeHash | 合约字节码哈希（EOA 为空代码哈希） |

两类账户：

- **EOA（外部拥有账户）**：由私钥控制，只能发起交易；
- **合约账户**：由代码控制，执行由其他交易或合约调用触发。

合约地址由 `keccak256(rlp(sender, nonce))[12:]` 决定（CREATE），或用 `keccak256(0xff ++ sender ++ salt ++ keccak256(init_code))[12:]` 决定（CREATE2，EIP-1014），后者让地址在部署前就可预测。

账户模型让"余额"成为全局状态的一部分，表达力强、编程直观，但引入三个问题：**nonce 顺序依赖**（交易必须按序执行）、**状态膨胀**（每个账户的存储永久存在）、**重入风险**（合约调用合约可能改变状态）。

## Transactions

一笔交易包含 `nonce`、`gasLimit`、`to`、`value`、`data`、费用参数与签名。交易类型（EIP-2718 封装）持续演进：

| 类型 | 引入 | 关键字段 | 用途 |
| --- | --- | --- | --- |
| 0 Legacy | 创世 | `gasPrice` | 传统交易 |
| 1 Access List | EIP-2930 / Berlin | `accessList` | 预声明访问的存储，降低冷访问成本 |
| 2 Dynamic Fee | EIP-1559 / London | `maxFeePerGas`、`maxPriorityFeePerGas` | 基础费 + 小费 |
| 3 Blob | EIP-4844 / Dencun | `blobVersionedHashes`、`maxFeePerBlobGas` | Rollup 发布数据 |
| 4 Set Code | EIP-7702 / Pectra | `authorizationList` | EOA 临时委托给智能合约代码 |

**EIP-1559** 把费用拆成两部分：协议计算的 `baseFee`（销毁）与用户给验证者的小费 `priorityFee`。`baseFee` 随区块利用率自动升降，目标是区块 gas 的一半：拥堵时上升、空闲时下降。销毁机制让 ETH 在需求高时通缩。

**EIP-155**（chainId 重放保护）让签名绑定链 ID，防止跨链重放；这是所有现代交易的前提。

## Gas and Execution

Gas 是执行资源的计价单位：

- 每个操作码有固定或动态成本，存储写入、内存扩张、外部调用最贵；
- 用户设置 `gasLimit`，未用完的部分退还，执行失败（revert/out of gas）时已消耗的 gas 不退；
- 验证者按 gas 打包交易，区块 gas limit 由验证者投票调整；
- **退款（refund）**：清理存储可返还部分 gas，上限为交易消耗的 1/5（EIP-3529），防止退款被滥用。

执行由 [EVM](/docs/CS/Blockchain/Ethereum/EVM.md) 完成：沙箱、确定性、按 gas 计量、状态变更在交易结束时原子提交或回滚。合约之间的调用是同步的，一个交易内的所有调用共享同一个 gas 池与状态上下文。

## Consensus

以太坊最初使用 PoW（Ethash），2020 年 12 月上线信标链，2022 年 9 月 **The Merge** 后完全转为 PoS：

- 验证者质押 32 ETH（Pectra 后单验证者有效余额上限提升到 2048 ETH）；
- 每 12 秒一个 slot，32 个 slot 一个 epoch（约 6.4 分钟）；
- 每个 epoch 对 checkpoint 投票，2/3 以上质押加权即**合理化**，连续两个 epoch 合理化即**最终化**（约 12.8 分钟）；
- 作恶（双重投票、环绕投票）会被罚没；
- 最终化区块的回滚需要至少 1/3 质押被罚没，成本极高。

共识细节（验证者生命周期、分叉选择、MEV-Boost、弱主观性）见 [Beacon Chain](/docs/CS/Blockchain/Ethereum/Beacon.md)，机制原理见 [PoS](/docs/CS/Distributed/Consensus/PoS.md)。

## Data Availability

Rollup 需要把交易数据发布到 L1，才能让任何人重建 L2 状态。calldata 长期是 Rollup 的主要成本，于是有了 **EIP-4844（proto-danksharding）**：

- 交易可以附带 **blob**，每个 128 KiB，内容不进入 EVM 执行，只做 KZG 承诺；
- blob 有独立的 gas 市场，价格与执行 gas 解耦；
- blob 数据约 18 天后删除，归档由外部负责；
- Fusaka 引入 **PeerDAS**，节点只需下载部分列并抽样验证，使 blob 数量可以继续提升而不压垮全节点带宽。

这是"Rollup 为中心"路线的关键基础设施，详见 [Layer 2](/docs/CS/Blockchain/Layer2.md) 与 [Architecture](/docs/CS/Blockchain/Architecture.md)。

## Clients and Interface

The Merge 把客户端拆成两层：

- **执行客户端**：Geth、Nethermind、Besu、Erigon、Reth，负责交易池、EVM 执行、状态与 JSON-RPC；
- **共识客户端**：Prysm、Lighthouse、Teku、Nimbus、Lodestar，负责 PoS 共识、区块 Gossip、验证者管理；
- **Engine API**：两层之间通过认证的 JSON-RPC 通信，共识层把执行负载交给执行层验证；
- **JSON-RPC / GraphQL**：钱包与 DApp 的入口，常见方法有 `eth_call`、`eth_sendRawTransaction`、`eth_getLogs`；
- **索引与查询**：链上不适合复杂查询，The Graph、Subgraph、自建索引器是标配。

多客户端实现是以太坊抗单点故障的核心策略：任一客户端出现共识 bug，只要多数验证者运行其他实现，链就不会分裂。

## Ecosystem

- **代币标准**：ERC-20、ERC-721、ERC-1155、ERC-4626，见 [Token](/docs/CS/Blockchain/Token.md)；
- **DeFi**：AMM、借贷、稳定币、衍生品、流动性质押、再质押；
- **NFT 与链上艺术**：元数据、版税、链上/链下存储；
- **DAO 与治理**：代币投票、委托人、金库、时间锁；
- **Layer 2**：Optimistic Rollup、ZK Rollup、Validium，见 [Layer 2](/docs/CS/Blockchain/Layer2.md)；
- **账户抽象**：EIP-4337 与 EIP-7702，让钱包支持社交恢复、批量交易、代付 gas。

## Key Limitations

- **状态膨胀**：全节点状态持续增长，无状态化与状态过期仍在研究中；
- **L1 吞吐有限**：区块 gas limit 与 12 秒 slot 决定 L1 只能承载结算与高价值交易；
- **MEV**：区块构建者与搜索者的利润分配影响用户与共识去中心化；
- **L2 碎片化**：多条 Rollup 之间的流动性与用户体验割裂，跨链桥是主要风险点；
- **升级复杂**：硬分叉需要协调多个客户端与生态，EIP 的讨论周期以年计；
- **合约风险**：代码即法律，漏洞不可撤销，见 [Security](/docs/CS/Blockchain/Security.md)。

## Reading Path

- 执行模型与 gas：[EVM](/docs/CS/Blockchain/Ethereum/EVM.md)；
- 共识与质押：[Beacon Chain](/docs/CS/Blockchain/Ethereum/Beacon.md)；
- 合约开发与升级：[Smart Contract](/docs/CS/Blockchain/SmartContract.md)；
- 扩容与 Rollup：[Layer 2](/docs/CS/Blockchain/Layer2.md)；
- 代币与 DeFi：[Token](/docs/CS/Blockchain/Token.md)。

## Links

- [Blockchain](/docs/CS/Blockchain/Blockchain.md)
- [EVM](/docs/CS/Blockchain/Ethereum/EVM.md)
- [Beacon Chain](/docs/CS/Blockchain/Ethereum/Beacon.md)
- [Smart Contract](/docs/CS/Blockchain/SmartContract.md)
- [Layer 2](/docs/CS/Blockchain/Layer2.md)
- [PoS](/docs/CS/Distributed/Consensus/PoS.md)

## References

1. [Ethereum Whitepaper](https://ethereum.org/en/whitepaper/)
2. [Ethereum Yellow Paper](https://ethereum.github.io/yellowpaper/paper.pdf)
3. [EIP-1559: Fee Market Change](https://eips.ethereum.org/EIPS/eip-1559)
4. [EIP-4844: Shard Blob Transactions](https://eips.ethereum.org/EIPS/eip-4844)
5. [EIP-7702: Set EOA Account Code](https://eips.ethereum.org/EIPS/eip-7702)
