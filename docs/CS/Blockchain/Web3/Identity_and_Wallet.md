## Introduction

Web3 的身份体系与 Web2 有根本差异：Web2 里账号由平台颁发、由平台注销，身份是**数据库里的一行**；Web3 里身份是**一对密钥**，谁掌握私钥谁就是这个地址。这一变化带来了可携带与可组合，也带来了不可撤销、不可找回、隐私全暴露。

理解这一层是理解钱包、登录、授权、声誉与合规的起点。账户的可编程化（社交恢复、批量交易、代付 gas）见 [Account Abstraction](/docs/CS/Blockchain/Web3/Account_Abstraction.md)，密钥与合约层面的攻击面见 [Security](/docs/CS/Blockchain/Security.md)。

## Keys and Addresses

一条以太坊账户的诞生过程：

```
随机熵(128~256 bit) → BIP-39 助记词 → BIP-32 种子 → BIP-44 派生路径 → 私钥 → 公钥 → 地址
m / 44' / 60' / 0' / 0 / index
```

- **私钥**：256 位随机数，是身份的全部。助记词只是它的可书写编码；
- **公钥**：由私钥经 secp256k1 椭圆曲线乘法得到，可公开；
- **地址**：`keccak256(公钥)[12:]` 取后 20 字节，EIP-55 用大小写混合编码提供校验和；
- **派生**：BIP-32 的分层确定性（HD）结构让一个助记词管理任意多地址，`44'` 是 BIP-44 用途字段、`60'` 是以太坊的币种编号。

由此推出两条硬约束：**备份 = 备份助记词，备份地址毫无意义**；**助记词泄露 = 身份彻底丢失，链上没有任何申诉通道**。

## Wallet Types

钱包的本质不是"存币"，而是**管理密钥并对交易签名**。资产始终在链上，钱包只持有签名能力。

| 形态 | 密钥位置 | 优势 | 主要风险 |
| --- | --- | --- | --- |
| 软件钱包（浏览器/移动） | 设备本地，keystore 加密 | 方便、免费、生态兼容最好 | 设备被控、钓鱼签名、恶意依赖 |
| 硬件钱包 | 安全芯片内，永不导出 | 签名需物理确认，隔离网络攻击 | 供应链、固件、盲签（看不清签了什么） |
| 多签合约 | 多个独立密钥，M-of-N | 无单点，适合金库与组织 | 合约风险、协调成本、链上手续费高 |
| MPC / TSS | 密钥分片分散持有，签名时协同计算 | 无完整私钥出现，可做密钥轮换 | 分片方合谋、供应商闭源、恢复依赖厂商 |
| 智能账户 | 合约定义验证逻辑 | 社交恢复、批量、权限分级 | 合约漏洞、模块供应链，见账户抽象分册 |

选择钱包的判断标准不是"哪个更安全"的绝对排序，而是**威胁模型**：防范设备被控选硬件钱包，防范内部作恶选多签，防范单点丢失选 MPC 或智能账户的社交恢复。

## Wallet Connection

DApp 与钱包之间的连接靠一组约定，而不是账号密码：

- **EIP-1193**：页面注入 provider（`window.ethereum`）的标准接口，是所有钱包交互的地基；
- **EIP-6963**：多钱包发现协议。过去多个钱包争抢同一个 `window.ethereum` 导致互相覆盖，6963 让每个钱包广播自己的身份，页面可以列出全部已安装钱包让用户选；
- **WalletConnect**：扫码/深链把移动端钱包与桌面 DApp 连起来，通过中继服务器转发加密会话消息；
- **EIP-5792**：钱包向 DApp 暴露"批量调用、代付、能力查询"的统一 RPC，让前端不必关心对方是 EOA 还是智能账户。

连接层的安全问题常被忽视：**"连接钱包"本身不授权任何资产转移**，真正的风险在后续的签名与授权请求。绝大多数盗币来自用户签了一个含义不清的结构化数据或授予了无限额度，而不是连接动作本身，攻击手法与防护见 [Security](/docs/CS/Blockchain/Security.md)。

## Sign-In and Authorization

- **EIP-191**：`personal_sign` 的原始签名格式，只签字节串，人类不可读，是钓鱼的高发区；
- **EIP-712**：类型化结构化数据签名。钱包可以把域名、字段名、数值展示出来，让用户知道自己在签什么，是登录与授权的主流格式；
- **SIWE（EIP-4361）**：用 712 签名登录的标准消息格式，包含域名、地址、nonce、过期时间与声明 URI，把"签名"变成"可验证的登录凭证"，服务端验签后签发会话；
- **EIP-1271**：合约账户的签名验证接口。智能账户没有私钥，合约签名必须由合约自己的逻辑确认，因此服务端验签必须支持 1271，否则智能账户用户无法登录。

授权（allowance）是另一个独立风险面：ERC-20 的 `approve` 一旦给出无限额度，被授权合约可以在任何时候转走该代币。EIP-2612 的 `permit` 与 Permit2 把授权改成带过期时间的签名，缓解"授权即永久"的问题，但**定期清理授权**仍是必要的卫生习惯。

## Naming and Resolution

地址不可读，命名层负责把它变成人类可识别的标识：

- **ENS（Ethereum Name Service）**：`alice.eth` → 地址、头像、社交账号、内容哈希。结构上分三层——Registry 记录名字的所有者与解析器，Registrar 负责注册与续费规则，Resolver 负责具体的解析逻辑；反向解析则把地址映射回一个"主名"（primary name），让钱包显示名字而不是十六进制串；
- **CCIP-Read（EIP-3668）**：允许解析过程去链下取数再由合约验证，使 ENS 能解析 L2 或其它链上的数据，是跨链身份的关键机制；
- **ENSv2**：对协议的自底向上重写。核心是**层级式注册表**（每个名字拥有自己的子注册表，子名称管理可以逐级下放）与**基于角色的权限**（把记录更新、解析设置、所有权管理拆成不同角色）。项目原计划跑在名为 Namechain 的专用 L2 上，2026 年 2 月改为直接部署在以太坊主网，理由是 L1 的 gas 成本已低到不值得再维护一条链。2026 年 10 月社区提出了在主网激活 ENSv2 的可执行提案草案，内容为冻结 v1 新注册、把解析切换到 v2、把 Labs 持有的管理角色移交 DAO，并调整了宽限期与定价；该提案需经 DAO 投票。

命名层的价值不在"好记"，而在**它是唯一被广泛集成的人类可读身份层**。风险也随之集中：名字的到期、注册商的权限、解析器的可信度，都直接决定了别人在钱包里看到的是谁。

## Decentralized Identity and Credentials

链上地址是**标识符**而不是**身份**。把学历、KYC、会员、雇佣关系等声明附加到身份上，需要另一套标准：

- **DID（W3C Decentralized Identifiers）**：一种不依赖中心化注册机构的可解析标识符规范，DID 文档里放公钥与服务端点，验证方按文档验签；
- **可验证凭证（Verifiable Credentials）**：签发方对主体做出可密码学验证的声明，持有方自己保管凭证，验证方只需验证签名与签发方，不接触签发方系统；
- **选择性披露与 ZK**：把"我满足某条件"与"我的具体数据"分离，用零知识证明只证明条件成立，见 [Zero-Knowledge Proof](/docs/CS/Blockchain/ZKProof.md)；
- **链上证明（Attestation）**：EAS 这类协议把任意结构化声明写成链上/链下可验证的记录，用于证明"某个地址曾被某个主体认证过"。

这些标准的共同价值是**把"平台证明你是谁"换成"任何验证方都能独立核验一份凭证"**。落地难点不在密码学，而在签发方的可信度与吊销机制：凭证签发方本身仍是中心化的，谁有权宣布一份凭证作废是尚未统一的工程问题。

## Reputation and Social Graph

没有平台账号，声誉需要重新构建。链上可用的信号包括：

- **交易与持仓历史**：可验证但极易被女巫攻击（批量地址自造历史）；
- **POAP / 徽章**：出席证明与成就凭证，成本低于交易历史，但同样可批量领取；
- **SBT（不可转移代币）**：把凭证做成不可转让的 NFT，防止声誉被买卖；代价是丢失即无法找回，因此现实做法常附带恢复机制；
- **社交图谱**：Farcaster、Lens 这类协议把账号、关注关系与内容做成可携带的数据层，客户端可以替换但图谱随用户迁移。其架构取舍是"身份与关系在链上、内容在链下 hub 或 L2"，以平衡可携带性与成本。

声誉系统真正的难点是**抗女巫**：一旦声誉可以换来空投或权限，它就成为被批量制造的目标。因此多数协议最终还是要引入某种身份证明（Proof of Humanity），而这又把中心化的验证方请回了系统里。

## Privacy Loss

公链默认全透明：任何地址的余额、交易对手、合约交互全部可查。后果是：

- **地址聚类**：交易所提现、找零地址、gas 支付来源都会把多个地址关联到同一实体；
- **去匿名化**：一旦某个地址与真实身份（交易所 KYC、ENS 资料、线下收款）产生一次关联，其全部历史与未来行为都被回溯；
- **不可逆**：历史无法删除，"换个地址"只能切断未来，且换地址的过程本身可能被追踪；
- **隐私工具的合规困境**：混币器能切断关联，但也因此成为制裁与执法的重点对象；较新的思路是"合规隐私"——用零知识证明证明资金来源不属于已知非法集合，而不公开具体路径。

因此 Web3 身份的正确心智模型是：**地址是假名（pseudonymous），不是匿名（anonymous）**。设计系统时要默认"所有链上行为最终都会被关联到真人"。可选的隐私技术与各辖区合规约束见 [Privacy and Compliance](/docs/CS/Blockchain/Web3/Privacy_and_Compliance.md)。

## Links

- [Web3](/docs/CS/Blockchain/Web3.md)
- [Account Abstraction](/docs/CS/Blockchain/Web3/Account_Abstraction.md)
- [Security](/docs/CS/Blockchain/Security.md)
- [Ethereum](/docs/CS/Blockchain/Ethereum.md)
- [Zero-Knowledge Proof](/docs/CS/Blockchain/ZKProof.md)
- [Token](/docs/CS/Blockchain/Token.md)

## References

1. [EIP-4361: Sign-In with Ethereum](https://eips.ethereum.org/EIPS/eip-4361)
2. [EIP-712: Typed Structured Data Hashing and Signing](https://eips.ethereum.org/EIPS/eip-712)
3. [EIP-1271: Standard Signature Validation Method for Contracts](https://eips.ethereum.org/EIPS/eip-1271)
4. [EIP-6963: Multi Injected Provider Discovery](https://eips.ethereum.org/EIPS/eip-6963)
5. [EIP-3668: CCIP Read](https://eips.ethereum.org/EIPS/eip-3668)
6. [W3C Decentralized Identifiers (DIDs) v1.0](https://www.w3.org/TR/did-core/)
7. [W3C Verifiable Credentials Data Model 2.0](https://www.w3.org/TR/vc-data-model-2.0/)
8. [ENS Documentation](https://docs.ens.domains/)
9. [The ENS App and Explorer Are Now in Beta](https://ens.domains/blog/post/ensv2-beta-public-testing)
10. [BIP-39: Mnemonic code for generating deterministic keys](https://github.com/bitcoin/bips/blob/master/bip-0039.mediawiki)
