## Introduction

过去短暂的互联网历史大致分为两个时期：Web 1.0 与 Web 2.0。

- **Web 1.0（约 1990–2004）**：只读。网站是静态页面，用户消费内容，几乎不参与生产；
- **Web 2.0（2004 年至今）**：可读可写。社交媒体平台让用户生产内容、参与交互，平台通过广告与数据变现；
- **Web 3.0（2014 年提出）**：可读、可写、**可拥有**。用区块链、密码学与代币把数据、身份与资产的所有权交还给用户。

2014 年以太坊推出后不久，联合创始人 Gavin Wood 提出"Web 3.0"的设想。Web3 的核心不是"更快的网页"，而是**把平台对身份、数据和价值的控制权，替换成用户可验证、可携带、可组合的所有权**。

## From Read to Own

Web 2.0 的根本矛盾是：**用户生产内容，平台拥有内容**。平台掌握账号、数据、推荐算法与支付通道，用户离开平台就失去社交关系与作品；平台可以封号、改规则、单方面分成。

Web3 的解法是把"所有权"写进密码学与共识：

- **账号即密钥**：身份不再由平台颁发，而是由私钥控制；
- **资产即代币**：余额、门票、会员资格、积分都是链上可验证的条目；
- **数据可携带**：应用状态公开可读，用户可以把资产与身份带到其他应用；
- **规则可验证**：智能合约的执行逻辑公开，平台不能暗中改规则；
- **可组合**：不同协议可以像积木一样互相调用，形成开放的应用网络。

这不是"去中心化一切"，而是**在关键环节移除单点控制**。Web3 应用仍可能依赖中心化服务器、RPC、前端托管与稳定币发行方，去中心化程度需要逐项评估。

## Core Principles

尽管很难对 Web3 做出严格定义，但它是在几项核心原则的指引下创建的：

- **Web3 是去中心化的**：大部分互联网不是由中心化实体控制和拥有的，而是由构建者和用户分配所有权；
- **Web3 无需许可**：每个人都有参与 Web3 的平等权限，没有人被排除在外；
- **Web3 具有原生支付功能**：它使用加密货币进行线上消费和汇款，而不是依赖传统银行或第三方支付机构过时的基础设施；
- **Web3 去信任**：它通过激励措施和经济机制运转，而不是依赖受信任的第三方。

这些原则是方向而非事实。现实中每条都可以被削弱：排序器可能中心化、前端可能被封锁、治理可能被巨鲸控制、稳定币可能被冻结。**判断一个 Web3 项目，要看去中心化发生在哪一层、信任假设是什么**。

## Identity and Ownership

所有权的第一步是身份：Web2 里账号是数据库里的一行，Web3 里身份是一对密钥。这个转换带来了可携带与可组合——同一个地址可以在不同应用间保留资产、声誉与权限；也带来了不可撤销与隐私泄漏——私钥丢失即身份丢失，地址一旦与真人关联，全部历史都会暴露。

这一层包含密钥与地址派生、钱包形态、钱包连接与签名标准、命名与解析、可验证凭证与声誉系统，以及"地址是假名而非匿名"这个必须内化的前提。让账户可编程（社交恢复、批量交易、代付 gas）则是账户抽象的工作：EIP-4337 引入 UserOperation、EntryPoint 与 Paymaster，EIP-7702 让现有 EOA 直接获得智能账户能力，ERC-7579 统一模块化接口。详见 [Identity and Wallet](/docs/CS/Blockchain/Web3/Identity_and_Wallet.md) 与 [Account Abstraction](/docs/CS/Blockchain/Web3/Account_Abstraction.md)。

## Governance

有了资产与权限，就需要决定谁改规则。DAO 把成员、投票与金库写进合约：治理代币或凭证定义投票权，提案经投票后由时间锁延迟执行，资金由多签或治理合约控制，链下签名投票（如 Snapshot）降低成本但依赖多签落地。

DAO 的常见问题是投票率低、投票权集中在巨鲸与托管方、闪电贷治理攻击、执行层多签成为真实单点，以及无实体状态下成员可能承担连带责任。因此现实中的 DAO 正在回补应急机制与法律外壳（LLC、基金会、协会），**把管理规则公开化、可审计化，但并没有消除治理本身**。详见 [DAO](/docs/CS/Blockchain/Web3/DAO.md)。

## Applications

资产与规则可编程之后，长出两类应用：DeFi 用合约替代金融中介（兑换、借贷、稳定币、衍生品、流动性质押、RWA），NFT 用合约定义唯一资产的所有权与流转规则（收藏品、游戏道具、会员凭证、创作者分成）。

它们的共同优势是**可组合**，共同风险是**风险沿依赖链传导**：接受某个凭证作抵押，就继承了该凭证发行方的风险；使用某个稳定币，就继承了发行方冻结地址的能力。评估任何链上收益，核心问题是它来自哪里、以及因此被动承担了哪些对手方风险。详见 [DeFi and NFT](/docs/CS/Blockchain/Web3/DeFi_and_NFT.md)。

## Infrastructure and Trust

应用之下是一层"链下基础设施"，它们往往比链本身更中心化：RPC 节点、索引器、内容寻址存储、预言机、跨链桥、排序器与前端托管。每一层都是一个"如果它作恶或宕机，会发生什么"的问题——**"链上去中心化、链下中心化"是 Web3 的常态**。

真正可操作的评估方式是画一张信任地图，逐行标注依赖、失败后果与可替换性，而不是争论"是否去中心化"。详见 [Infrastructure](/docs/CS/Blockchain/Web3/Infrastructure.md)。

## Limitations

- **用户体验**：助记词、gas、跨链切换、交易确认，门槛远高于 Web2；
- **可扩展性**：L1 吞吐有限，L2 缓解但带来碎片化；
- **隐私**：公链默认公开，地址关联可暴露全部历史，且历史无法删除；
- **监管**：证券属性、税务、KYC/AML、稳定币与制裁合规仍在快速演变，各辖区框架差异明显；
- **安全**：钓鱼、授权滥用、合约漏洞、桥攻击造成持续损失；
- **投机与叙事**：大量项目以"Web3"包装，实际没有去中心化或真实需求；
- **中心化回潮**：为追求体验，钱包、RPC、排序器、前端重新集中，形成新的中介；
- **可访问性**：网络拥堵时费用高昂，排除低收入用户。

前两项正在被工程进展缓解（账户抽象、blob 与数据可用性采样），后几项是结构性的，只能缓解不能消除。隐私与监管的成因、现行框架与尽调清单见 [Privacy and Compliance](/docs/CS/Blockchain/Web3/Privacy_and_Compliance.md)。

Web3 不是"取代 Web2"，而是**在特定场景（开放金融、数字所有权、跨组织协作）提供一种新的组织方式**。它更适合"需要可验证所有权与无许可组合"的应用，而不是所有互联网产品。

## Evaluation Checklist

判断一个 Web3 项目是否名副其实：

1. **资产与状态是否真的在链上**？还是只有一个数据库加代币？
2. **谁能升级合约**？多签、时间锁、治理，还是单一私钥？
3. **数据是否可用**？用户能否独立重建状态并退出？
4. **排序是否去中心化**？Sequencer 能否审查交易？
5. **前端与 RPC 是否单点**？服务商能否封锁访问？
6. **代币是否有真实用途**？还是纯治理/投机？
7. **治理是否可被少数人控制**？投票权分布如何？
8. **合规与法律结构是否清晰**？用户与成员承担什么责任？

## Links

- [Blockchain](/docs/CS/Blockchain/Blockchain.md)
- [Identity and Wallet](/docs/CS/Blockchain/Web3/Identity_and_Wallet.md)
- [Account Abstraction](/docs/CS/Blockchain/Web3/Account_Abstraction.md)
- [DeFi and NFT](/docs/CS/Blockchain/Web3/DeFi_and_NFT.md)
- [Infrastructure](/docs/CS/Blockchain/Web3/Infrastructure.md)
- [Security](/docs/CS/Blockchain/Security.md)

## References

1. [什么是 Web3？](https://ethereum.org/zh/web3/)
2. [Web3 Foundation](https://web3.foundation/)
3. [EIP-4361: Sign-In with Ethereum](https://eips.ethereum.org/EIPS/eip-4361)
4. [EIP-4337: Account Abstraction Using Alt Mempool](https://eips.ethereum.org/EIPS/eip-4337)
5. [EIP-7702: Set EOA account code](https://eips.ethereum.org/EIPS/eip-7702)
6. [W3C Decentralized Identifiers](https://www.w3.org/TR/did-core/)
