## Introduction

所有区块链共享同一套骨架：**区块 + 哈希指针 + 交易集合 + 共识定序**。不同的链在区块头字段、状态模型、证明结构上做出不同取舍，但解决的问题一致——如何让一个不断增长的历史，既能被任何人独立验证，又能抵抗篡改与伪造。

这一页讲清六个所有链都要面对的结构性问题：区块里放什么、Merkle 树为什么是标配、状态如何被承诺、分叉如何收敛、轻客户端如何验证、数据如何保证可得。具体链的实现见 [Bitcoin](/docs/CS/Blockchain/Bitcoin.md) 与 [Ethereum](/docs/CS/Blockchain/Ethereum.md)。

## Block Anatomy

区块由**区块头**与**区块体**组成。区块体是交易列表（以太坊还包括提款、执行负载等），区块头是固定大小、被反复哈希的元数据。比特币区块头恰好 80 字节：

| 字段 | 大小 | 作用 |
| --- | --- | --- |
| version | 4 B | 协议版本与软分叉信号位 |
| prevBlockHash | 32 B | 指向前一区块，构成链 |
| merkleRoot | 32 B | 区块内交易的承诺 |
| timestamp | 4 B | 出块时间（秒级 Unix 时间） |
| nBits | 4 B | 当前难度目标 `target` 的紧凑编码 |
| nonce | 4 B | PoW 随机数 |

以太坊的区块头复杂得多，因为它承诺的不只是交易，还有**执行结果**：`parentHash`、`stateRoot`、`transactionsRoot`、`receiptsRoot`、`logsBloom`、`gasLimit`/`gasUsed`、`baseFeePerGas`、`withdrawalsRoot`、`blobGasUsed`/`excessBlobGas`、`parentBeaconBlockRoot`，Pectra 之后还加入 `requestsHash`。字段变多的根本原因是：以太坊要让轻客户端仅凭区块头就能校验状态与收据，而不必重放全部交易。

区块头小是刻意的设计。它让**轻客户端**可以只下载几十 GB 的头链而非数百 GB 的全量数据，也是 PoW 与 PoS 共识只对区块头做哈希的前提。

## Hash Linking and Tamper Evidence

哈希指针是链式结构的本质：`blockHash = H(header)`，下一块的 `prevBlockHash` 指向它。由此得到两个性质：

- **篡改传播**：修改第 N 块的任何交易会改变其 Merkle 根，从而改变块哈希，导致 N+1 之后的指针全部失配，必须重算所有后续区块；
- **不可伪造**：攻击者不仅要重算哈希，还要让新链在共识规则下被网络接受——PoW 要重做工作量，PoS 要控制足够权益并承担罚没。

严格说，区块链提供的是**可检测的篡改**（任何节点都能发现失配）与**高成本的篡改**（重写需要压倒性资源），而不是物理上不可删除。全节点保存的是自己验证过的最重链，历史可以被重写，只是代价高昂。

## Merkle Trees

区块内交易数量可达数千笔，逐笔哈希进区块头会让头变得巨大。Merkle 树用二叉树把 `n` 笔交易压缩成 32 字节根：

```
                 root = H(H12 || H34)
                /                    \
          H12 = H(H1||H2)        H34 = H(H3||H4)
          /          \            /          \
       H1=H(tx1)  H2=H(tx2)   H3=H(tx3)  H4=H(tx4)
```

要证明 `tx3` 在块中，只需提供 `H4`、`H12` 和根，验证者自行计算 `H(H12 || H(H3 || H4))` 是否等于根。证明大小是 `O(log n)`——3000 笔交易只需约 12 个哈希（约 384 字节）。

Merkle 树还带来两个工程好处：

- **并行性**：子树可以并行计算；
- **增量更新**：新增交易只需重算路径上的节点。

比特币的 Merkle 树有一个历史遗留缺陷：重复最后一项以补齐奇数层，且不区分叶子与内部节点的哈希域，理论上存在"不同交易集合得到相同根"的构造（CVE-2012-2459），实际利用价值有限但提醒我们**承诺结构必须做域分离**。以太坊的 Merkle Patricia Trie 用不同的节点前缀解决了类似问题。

### Merkle Patricia Trie

以太坊不只要承诺"交易集合"，还要承诺**全局状态**（每个账户的余额、nonce、代码、存储）。它使用 16 叉的 Merkle Patricia Trie：

- 每个账户以 `keccak256(address)` 为键，路径按 nibble 展开；
- 节点分 branch（16 个子指针）、extension（压缩公共前缀）、leaf（值）三类；
- 根哈希写入区块头，任何账户状态变化都会改变从该叶到根的路径，产生新的 `stateRoot`；
- 证明某个账户的状态，只需提供路径上的兄弟节点。

代价是更新与证明的常数开销大，且状态树越深证明越长。以太坊的长期路线是迁移到 Verkle 树（更短的证明、支持无状态验证），但迁移涉及共识与客户端的协同，属于多年期工程。

## State Transition

区块链可以视为**复制的状态机**：`state_{n+1} = apply(state_n, block_n)`。共识负责给区块定序，执行负责状态转移。状态如何表示，决定了验证与编程模型：

| 维度 | UTXO | 账户 |
| --- | --- | --- |
| 状态表示 | 未花费输出集合 | 全局账户映射 |
| 交易语义 | 消耗输入、创建输出 | 从发送方扣款、向接收方加款 |
| 并行验证 | 天然可并行（输入互斥即可） | 依赖 nonce，顺序执行 |
| 重放防护 | 输出只能被花费一次 | 账户 nonce 单调递增 |
| 合约表达力 | 脚本受限（非图灵完备） | 通用虚拟机 |
| 状态增长 | UTXO 集合，可剪枝 | 全局状态，难以剪枝 |

比特币选择 UTXO 是为了**验证简单、并行友好、无需全局状态**；以太坊选择账户是为了**可组合的智能合约**，代价是状态膨胀与顺序依赖。两套模型都能实现支付，但扩展方向完全不同。

## Forks and Reorganization

分叉是常态而非异常：两个矿工/验证者几乎同时出块，网络不同部分会短暂看到不同的链头。

- **临时分叉**：节点保留多条候选链，按共识规则选择主链。PoW 选**累计工作量最大**的链（不是简单的最长），PoS 用 LMD-GHOST 选票数最多的分支；
- **重组（reorg）**：当另一条分支胜出，节点回滚已应用的区块，把其中的交易放回内存池或重新广播；
- **确认深度**：`k` 个确认意味着攻击者需要重写 `k+1` 个块。比特币 6 个确认是经验值；以太坊在 PoS 下通常 1–2 个 slot 后不再重组，**最终性（finality）**约 2 个 epoch（约 12.8 分钟）后达成，被最终化的区块回滚需要至少 1/3 质押被罚没；
- **深度重组风险**：交易所通常按金额设置确认阈值；跨链桥必须等待足够确认或依赖最终性，否则会遭遇"充值后回滚"的双花攻击。

值得强调：**"确认"不是协议保证，而是概率/经济保证**。PoW 下每次确认把攻击成功概率减半量级；PoS 下最终性一旦达成则是确定性的，但代价是引入了弱主观性与长程攻击的新问题。

## Light Clients and Proofs

全节点验证一切但成本高，轻客户端只信任最少的数据。常见证明类型：

- **包含证明**：Merkle 路径证明"某交易/状态在某个根下"，SPV 钱包用它验证收款；
- **欺诈证明**：乐观地假设结果正确，给出挑战窗口，任何人可提交反证。Optimistic Rollup 与轻客户端桥常用；
- **有效性证明**：用零知识证明直接证明"状态转移正确"，验证成本远低于重算，见 [Zero-Knowledge Proof](/docs/CS/Blockchain/ZKProof.md)；
- **同步委员会**：以太坊轻客户端跟踪 512 个随机选出的验证者签名，用少量数据跟上链头，再配合执行层证明读取状态。

轻客户端的信任假设必须写清楚：SPV 信任"最长链"与足够的算力/质押；同步委员会信任 2/3 的委员会成员；zk 轻客户端信任电路与证明系统。**没有免费的验证**，只有把成本转移到不同角色。

## Data Availability

即使区块头有效，如果区块体数据被隐藏，外部无法重建状态，也无法发现作恶——这就是**数据可用性问题**。它和"数据存在"是两回事：可用性要求数据在需要时能被完整获取。

- **全节点广播**：最直接，但要求每个节点下载全部数据；
- **纠删码**：把 `n` 份数据编码成 `2n` 份，任意 `n` 份即可恢复，降低"必须拿到全部数据"的门槛；
- **数据可用性采样（DAS）**：轻节点随机采样若干块，若都可用则以高概率断定整块可用；
- **blob 与 PeerDAS**：以太坊 EIP-4844 把 L2 数据放进独立的 blob 空间（每个 blob 128 KiB，独立 gas 市场，约 18 天后删除），Fusaka 引入 PeerDAS，让节点只下载部分列并互相抽样验证，从根本上降低全节点的带宽门槛；
- **外部 DA 层**：Celestia、EigenDA、Avail 等把 DA 做成独立服务，Rollup 可把数据发布到这些层，用其安全假设换取更低成本。

数据可用性是 Rollup 安全模型的核心变量：数据在 L1 上，任何人都能重建状态并强制退出；数据只在链下，用户就要信任 DA 委员会。详见 [Layer 2](/docs/CS/Blockchain/Layer2.md)。

## Storage Growth

区块链只增不减，存储是长期成本：

- **归档节点**：保存全部历史状态与区块，用于区块浏览器、分析、RPC 历史查询；
- **全节点**：保存全部区块与当前状态，可裁剪历史状态；
- **剪枝节点**：删除旧状态，只保留最近若干块，无法回答历史查询；
- **历史过期（EIP-4444）**：让节点可以丢弃一年以前的区块体，由归档服务或门户网络提供历史，降低运行门槛；
- **无状态/弱状态**：用证明代替本地状态，让验证者不必保存完整状态，是以太坊 Verkle 路线的目标之一。

存储问题没有"免费"的解法：要么让少数节点承担历史（牺牲去中心化），要么用密码学证明把成本转移给证明者（增加计算），要么用经济激励让存档成为一门生意。

## Links

- [Blockchain](/docs/CS/Blockchain/Blockchain.md)
- [Bitcoin](/docs/CS/Blockchain/Bitcoin.md)
- [Ethereum](/docs/CS/Blockchain/Ethereum.md)
- [Layer 2](/docs/CS/Blockchain/Layer2.md)
- [Zero-Knowledge Proof](/docs/CS/Blockchain/ZKProof.md)
- [Security](/docs/CS/Blockchain/Security.md)

## References

1. [Bitcoin: A Peer-to-Peer Electronic Cash System](https://bitcoin.org/bitcoin.pdf)
2. [Ethereum Yellow Paper](https://ethereum.github.io/yellowpaper/paper.pdf)
3. [EIP-4844: Shard Blob Transactions](https://eips.ethereum.org/EIPS/eip-4844)
4. [EIP-4444: Bound Historical Data in Execution Clients](https://eips.ethereum.org/EIPS/eip-4444)
5. [Merkling in Ethereum](https://blog.ethereum.org/2015/11/15/merkling-in-ethereum)
