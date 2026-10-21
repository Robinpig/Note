## Introduction

零知识证明（Zero-Knowledge Proof, ZKP）让证明者（prover）向验证者（verifier）证明"某个陈述为真"，而不泄露陈述之外的任何信息。在区块链里，它解决了一个核心矛盾：**如何在不重新执行全部计算的前提下，验证计算结果是正确的**。

这让 ZK 同时服务三个方向：**扩容**（Rollup 把执行压缩成短证明）、**隐私**（证明交易合法但不暴露金额与地址）、**互操作**（轻客户端用证明验证另一条链的状态）。这一页讲原理、主流证明系统、zkEVM 分类与工程取舍；Rollup 的工程结构见 [Layer 2](/docs/CS/Blockchain/Layer2.md)。

## Definitions

一个零知识证明系统必须满足三条性质：

- **完备性（completeness）**：陈述为真时，诚实的证明者总能让验证者接受；
- **可靠性（soundness）**：陈述为假时，任何证明者（包括作恶者）都无法让验证者接受，除非以极小概率；
- **零知识性（zero-knowledge）**：验证者从证明中得不到除"陈述为真"之外的任何信息。

技术上说，ZKP 证明的是 **NP 陈述**：存在一个证据（witness）`w`，使得关系 `R(x, w)` 成立。实际系统把计算编译成**算术电路**，证明"我知道一组输入，使得电路输出为 1"。

```
陈述 x： "我知道 w，使得 R(x, w) = 1"
证明 π： 不泄露 w，但让验证者相信 x 成立
```

**简洁性（succinctness）**：证明大小与验证时间远小于重新执行计算，通常是 `O(log n)` 或常数级。这是 ZK 能用于扩容的关键。

## Interactive to Non-Interactive

最早的零知识证明是交互式的：证明者与验证者多轮挑战-应答。区块链要求**任何人都能独立验证、且证明可以被写入链上**，因此需要非交互式证明：

- **Fiat-Shamir 变换**：用哈希函数把交互式挑战替换成"对公开信息的哈希"，把多轮交互压成一条消息；
- **风险**：哈希输入必须包含所有上下文（陈述、承诺、参数），否则存在"弱 Fiat-Shamir"攻击，攻击者可伪造证明；
- **可信设置**：部分系统需要一次性生成公共参数，若参数生成者保留"有毒废料"，就能伪造证明。

非交互式证明的验证成本决定了它能否上链：Groth16 的链上验证只需约 20 万 gas 量级，而 STARK 的验证成本更高但无需可信设置。

## SNARK Families

| 系统 | 可信设置 | 证明大小 | 验证成本 | 特点 |
| --- | --- | --- | --- | --- |
| Groth16 | 每电路一次 | 极小（约 200 B） | 很低 | 最广泛用于 Rollup |
| PLONK | 通用、可更新 | 小 | 低 | 自定义门、生态成熟 |
| Halo2 | 无 | 中 | 中 | IPA 承诺，无需可信设置 |
| STARK | 无 | 大（数十 KB） | 较高 | 哈希基、透明、抗量子 |
| Bulletproofs | 无 | `O(log n)` | 较高 | 范围证明，Monero 使用 |

- **Groth16**：基于双线性配对，证明最小、验证最便宜，但每个电路都要单独的可信设置，电路改动就要重做 ceremony；
- **PLONK**：用通用可信设置（一次 Powers of Tau 可供所有电路使用），支持自定义门与查找表；
- **Halo2**：用内积论证（IPA）替代配对，彻底去掉可信设置，代价是证明稍大、验证稍慢；
- **STARK**：用哈希与 FRI 做低度测试，完全透明、抗量子，证明大但证明生成快，适合高吞吐场景；
- **Bulletproofs**：无信任设置、证明随电路规模对数增长，但验证是线性的，适合范围证明而非通用计算。

选择取决于约束：要最小验证成本选 Groth16；要可升级、免 ceremony 选 PLONK/Halo2；要抗量子与透明选 STARK。

## Trusted Setup

Groth16 与部分 PLONK 实现需要**公共参考串（CRS）**：

- 通过 **Powers of Tau** 多方计算 ceremony 生成，只要有一个参与者诚实销毁其随机数，参数就是安全的；
- "有毒废料"若被保留，持有者可伪造任意证明；
- 通用设置可复用于不同电路，但 Groth16 的电路特定设置不能复用；
- 可信设置是**一次性信任**，不是持续信任；但 ceremony 的组织、参与方与验证过程需要透明可审计。

## Recursion and Folding

证明系统的一大工程突破是**递归证明**：用一个证明去证明"另一个证明是有效的"。

- **IVC（增量可验证计算）**：把长计算拆成多步，每步生成一个证明，下一步证明"上一步的证明 + 本步计算"正确；
- **证明聚合**：把多个 Rollup 批次的证明聚合成一个，降低 L1 验证成本；
- **折叠方案（folding）**：Nova、HyperNova 等不生成完整证明，而是把多个实例"折叠"成一个待证明实例，大幅降低中间开销；
- **应用**：zkEVM 的分段证明、跨链轻客户端、可验证机器学习。

递归让证明系统的成本可以随计算量**次线性**增长，是 ZK Rollup 能处理大规模执行的基础。

## zkEVM Taxonomy

把 EVM 执行放进 ZK 电路，难点在于 EVM 的复杂语义（栈、内存、存储、gas、预编译）与证明系统的约束。Vitalik 提出四类划分：

- **Type 1**：完全等价于以太坊，可直接验证 L1 区块，兼容性最好、证明成本最高；
- **Type 2**：完全 EVM 等价，内部表示可不同，几乎兼容所有工具；
- **Type 3**：几乎等价，牺牲少量边缘语义换取性能；
- **Type 4**：只保证高级语言层面等价，把 Solidity 编译到自定义电路，兼容性最差、效率最高。

另一条路线是 **zkVM**：直接证明 RISC-V 等通用指令集的执行（RISC Zero、SP1），开发者用 Rust 写程序即可，代价是证明开销高于专用电路。两条路线在"兼容性 vs 效率"上做不同取舍。

## Applications

- **ZK Rollup**：证明状态转换正确，L1 只验证证明，见 [Layer 2](/docs/CS/Blockchain/Layer2.md)；
- **隐私支付**：Zcash 的 shielded 交易、混币协议，隐藏发送方、接收方与金额；
- **身份与凭证**：证明"年龄大于 18""属于某个组织"而不暴露具体信息（Semaphore、zkCredential）；
- **轻客户端**：用证明验证另一条链的共识或状态，替代信任中继；
- **可验证计算**：外包计算并证明结果正确，适用于 AI 推理、数据市场；
- **游戏与投票**：隐藏手牌、匿名投票、可验证随机性。

## Costs and Limits

- **证明时间**：复杂电路可能需要数分钟到数小时，GPU/ASIC 加速与分布式证明是主要优化方向；
- **证明内存**：大电路需要大量内存，限制了单机规模；
- **验证 gas**：链上验证成本决定 Rollup 的经济性；
- **电路正确性**：电路约束不足（underconstrained）会让攻击者伪造证明，是 ZK 项目最常见的安全事故；
- **可信设置**：ceremony 的组织与审计成本；
- **量子威胁**：基于配对的 SNARK 会被 Shor 算法攻破，基于哈希的 STARK 相对安全；
- **不是万能**：ZK 证明"计算正确"，不证明"数据可用"；数据可用性仍需 L1 或 DA 层保证。

## Links

- [Layer 2](/docs/CS/Blockchain/Layer2.md)
- [Blockchain](/docs/CS/Blockchain/Blockchain.md)
- [Ethereum](/docs/CS/Blockchain/Ethereum.md)
- [Security](/docs/CS/Blockchain/Security.md)
- [Architecture](/docs/CS/Blockchain/Architecture.md)
- [Smart Contract](/docs/CS/Blockchain/SmartContract.md)

## References

1. [STARKs, Part I: Proofs with Polynomials](https://vitalik.eth.limo/general/2017/11/09/starks_part_1.html)
2. [The PLONK Paper](https://eprint.iacr.org/2019/953)
3. [STARKs, Part 3: Into the Weeds](https://vitalik.eth.limo/general/2018/07/21/starks_part_3.html)
4. [Nova: Recursive Zero-Knowledge Arguments from Folding Schemes](https://eprint.iacr.org/2021/370)
5. [The Different Types of ZK-EVMs](https://vitalik.eth.limo/general/2022/08/04/zkevm.html)
