## Introduction

公链的吞吐瓶颈不在 CPU，而在**复制与验证**：每个全节点都要下载、执行、存储全部数据，提高吞吐会直接抬高节点门槛，损害去中心化。Layer 2 的思路是把这个矛盾拆开——**L1 负责共识、结算与数据可用性，L2 负责执行与扩容**。

"Layer 2"不是单一技术，而是一组安全假设各异的方案：状态通道、侧链、Plasma、Rollup、Validium。判断一个 L2 是否真正继承 L1 的安全性，关键看两件事：**状态转换是否可被 L1 验证**、**数据是否在 L1 可得**。

## Scaling Trade-offs

扩容绕不开一个不可能三角：**去中心化、安全性、可扩展性**。实际工程中更准确的表述是"在给定安全假设下能买到多少吞吐"：

- **提高 L1 容量**：增大区块、优化执行、分片、数据可用性采样。改动共识，影响所有节点，进展慢；
- **链下执行**：把计算移出 L1，只提交结果或证明。计算可以无限扩展，但结算与数据仍受 L1 限制；
- **链下数据**：把数据也移出 L1（Validium、外部 DA），成本最低，但引入新的信任假设；
- **密码学压缩**：用有效性证明压缩执行，用 KZG/纠删码压缩数据。

所有 L2 都在"执行放哪里、数据放哪里、证明用什么"这三个维度上做选择。

## State and Payment Channels

通道是最早的 L2：参与方把资金锁进多签，链下不断更新状态，只在关闭时上链。

- **支付通道**：只支持转账，比特币闪电网络是代表，见 [Lightning Network](/docs/CS/Blockchain/Bitcoin/Lightning.md)；
- **状态通道**：支持任意状态更新（如游戏、棋盘），需要参与方持续在线并交换签名；
- **优点**：即时、低费、隐私好（中间状态不上链）；
- **缺点**：只适合固定参与方、资金锁定、需要在线或瞭望塔、路由流动性管理复杂。

通道无法支持"向任意新用户转账"的开放场景，这是它未能成为通用扩容方案的根本原因。

## Sidechains and Plasma

**侧链**是独立的区块链，有自己的共识与验证者，通过双向桥与主链连接：

- 优点：可以自由设计共识与虚拟机，吞吐高；
- 缺点：安全性独立于主链，桥的信任假设是单点；侧链验证者作恶或停摆，用户资产可能被冻结或盗取。

**Plasma** 是早期的链下扩容方案：把子链状态根提交到主链，用户可用 Merkle 证明退出。它面临**数据扣留攻击**——运营方隐藏区块数据，用户无法构造退出证明；**大规模退出**也会压垮主链。Plasma 基本被 Rollup 取代，但其"退出机制"思想保留在 Rollup 的逃生舱设计中。

## Rollups

Rollup 是目前的主流路线。核心结构：

1. 用户在 L2 发起交易，由 **Sequencer** 排序执行；
2. L2 状态根与交易数据（或数据承诺）定期提交到 L1 的 Rollup 合约；
3. L1 合约根据证明或挑战窗口确认状态转换；
4. 用户可通过 L1 合约存入/提取资产，L1 是最终仲裁者。

Rollup 的关键在于**数据发布到 L1**：任何人都能下载数据、重建 L2 状态、独立验证。如果数据不在 L1，Rollup 就退化成了 Validium。

### Optimistic Rollup

- 默认假设状态转换正确，提交后进入**挑战窗口**（通常 7 天）；
- 任何人发现错误可提交**欺诈证明（fraud proof）**，通过交互式二分定位错误指令，在 L1 上裁决；
- 优点：EVM 兼容性好、证明成本低；
- 缺点：提款慢（等挑战期）、需要诚实观察者在线、欺诈证明系统复杂；
- 代表：Arbitrum（BoLD 协议）、Optimism/Base（OP Stack）、Blast 等。

"7 天"是安全参数，不是技术限制。快速提款通常依赖第三方流动性桥，用户把"等待"换成"信任第三方"。

### ZK Rollup

- 每个批次附带**有效性证明（validity proof）**，L1 合约验证证明通过才接受状态根；
- 优点：提款快（无需挑战期）、安全性只依赖密码学、轻客户端友好；
- 缺点：证明生成成本高、EVM 兼容性难、证明系统复杂；
- 代表：zkSync Era、Starknet、Scroll、Linea、Polygon zkEVM、Taiko（based）。

ZK Rollup 的证明开销与计算量相关，因此对高频简单交易更划算；复杂合约的证明成本仍是瓶颈。原理见 [Zero-Knowledge Proof](/docs/CS/Blockchain/ZKProof.md)。

### Validium and Optimium

- **Validium**：有效性证明上链，但数据存储在链下（DAC 或外部 DA），成本更低，风险是数据不可得导致用户无法退出；
- **Optimium**：乐观证明 + 链下数据，名字不统一，本质是"数据不在 L1 的乐观方案"；
- **选择判据**：应用能否接受"数据委员会作恶/失联"的风险。支付、交易类应用通常要求数据在 L1；游戏、社交等高吞吐低价值场景可能接受 Validium。

## Data Availability

Rollup 的成本大头是数据发布。演进路径：

- **calldata**：最初把交易数据写进 calldata，成本随 L1 gas 波动；
- **blob（EIP-4844）**：独立 gas 市场，每个 blob 128 KiB，约 18 天后删除；Dencun 初始目标 3 个、上限 6 个 blob/块，Pectra 提升到目标 6、上限 9；
- **PeerDAS（Fusaka）**：节点只下载部分列并抽样验证，使 blob 数量可以继续提升；
- **外部 DA 层**：Celestia、EigenDA、Avail 提供更便宜的 DA，代价是引入额外的信任假设（委员会、质押、抽样）；
- **DAC**：许可制数据可用性委员会，成本最低、信任最集中。

**数据可用性是 Rollup 安全模型的分水岭**：数据在 L1，用户可以无须信任任何人地重建状态并强制退出；数据在链下，用户就必须信任 DA 提供方。

## Bridges

桥连接两条链，是跨链资产的入口，也是历史上损失最集中的地方：

- **锁定-铸造（lock-and-mint）**：源链锁定资产，目标链铸造映射资产。信任点是托管方或验证者集合；
- **销毁-铸造**：适用于原生多链资产，需协议层支持；
- **轻客户端桥**：在目标链验证源链共识（如 zk 轻客户端），信任假设最弱，但实现复杂、成本高；
- **流动性网络**：做市商在两侧提供流动性，用户跨链实际上是"卖一边、买一边"，信任做市商；
- **意图桥（intent-based）**：用户表达目标，求解器竞争完成，体验好但引入求解器信任与 MEV。

桥的风险在于**安全假设的叠加**：两条链各自的安全 + 桥验证者的安全 + 合约实现的安全。任何一层被攻破，资产都可能被盗。详见 [Security](/docs/CS/Blockchain/Security.md)。

## Trust and Maturity

L2Beat 等社区用"阶段（Stage）"衡量 Rollup 的成熟度：

- **Stage 0**：训练轮，升级由团队多签控制，用户依赖运营方；
- **Stage 1**：有可用的欺诈/有效性证明，升级需较长延迟，但有安全委员会兜底；
- **Stage 2**：无需许可的证明者/挑战者，升级权限最小化或完全移除。

大多数 L2 仍在 Stage 0–1。判断一个 L2 是否"真正 L2"，应看：

- 状态转换是否可被 L1 验证（证明或挑战）；
- 数据是否在 L1 可得；
- 升级密钥由谁控制、有无时间锁；
- Sequencer 是否可审查交易、用户能否强制通过 L1  inclusion；
- 是否有**逃生舱（escape hatch）**：Sequencer 停摆时用户能否自行退出。

**中心化 Sequencer 是当前 L2 的普遍现状**：它带来低延迟与低费用，也带来审查、抢跑与单点故障风险。Based Rollup、共享排序（shared sequencing）与强制包含列表是去中心化排序的探索方向。

## UX and Fragmentation

- **提款延迟**：Optimistic Rollup 的 7 天等待催生了第三方快速桥；
- **跨链体验**：多条 L2 之间的资产分散，用户需要在不同网络间切换；
- **流动性碎片化**：同一资产在 L1 与多条 L2 上割裂，做市与借贷深度分散；
- **互操作协议**：跨链消息标准（如 ERC-7683 意图标准）、共享排序、链抽象；
- **费用抽象**：用 ERC-20 支付 gas、Paymaster 代付，降低新用户门槛。

扩容的终点不只是"更高 TPS"，而是"用户感知不到链的存在"。这需要钱包、桥、排序、DA 的协同，而不是单点突破。排序之外的链下依赖（RPC、索引器、存储、预言机、前端托管）构成另一条信任链，见 [Infrastructure](/docs/CS/Blockchain/Web3/Infrastructure.md)。

## Links

- [Blockchain](/docs/CS/Blockchain/Blockchain.md)
- [Ethereum](/docs/CS/Blockchain/Ethereum.md)
- [Zero-Knowledge Proof](/docs/CS/Blockchain/ZKProof.md)
- [Lightning Network](/docs/CS/Blockchain/Bitcoin/Lightning.md)
- [Architecture](/docs/CS/Blockchain/Architecture.md)
- [Security](/docs/CS/Blockchain/Security.md)

## References

1. [Ethereum Rollup-centric Roadmap](https://ethereum-magicians.org/t/a-rollup-centric-ethereum-roadmap/4698)
2. [EIP-4844: Shard Blob Transactions](https://eips.ethereum.org/EIPS/eip-4844)
3. [L2BEAT: Rollup Stages](https://l2beat.com/stages)
4. [Optimistic Rollup vs ZK Rollup](https://vitalik.eth.limo/general/2021/01/05/rollup.html)
5. [EIP-7691: Blob Throughput Increase](https://eips.ethereum.org/EIPS/eip-7691)
