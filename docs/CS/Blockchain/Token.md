## Introduction

链上代币不是"币"的实体，而是**账本中的一条记录**：一个合约维护 `地址 → 余额` 的映射，并提供转账、授权等标准接口。代币的价值来自共识、现金流、治理权或使用权，而不是代码本身——任何人都能发行代币，但不代表任何人有义务接受它。

这一页讲代币标准、DeFi 原语、稳定币、代币经济与合规。合约实现细节见 [Smart Contract](/docs/CS/Blockchain/SmartContract.md)，攻击面见 [Security](/docs/CS/Blockchain/Security.md)。

## Fungible Tokens: ERC-20

ERC-20 是最基础的同质化代币标准，定义了六个函数与两个事件：

```solidity
function totalSupply() external view returns (uint256);
function balanceOf(address account) external view returns (uint256);
function transfer(address to, uint256 amount) external returns (bool);
function approve(address spender, uint256 amount) external returns (bool);
function transferFrom(address from, address to, uint256 amount) external returns (bool);
function allowance(address owner, address spender) external view returns (uint256);

event Transfer(address indexed from, address indexed to, uint256 value);
event Approval(address indexed owner, address indexed spender, uint256 value);
```

**授权模型**是 DeFi 的基础，也是最大的风险来源：用户 `approve` 某个合约可以花自己的代币，若合约有漏洞或恶意，额度内资产会被转走。常见改进：

- **`increaseAllowance` / `decreaseAllowance`**：规避"先改额度再转账"的竞态；
- **EIP-2612 `permit`**：用签名一次性授权，省掉一笔 approve 交易；
- **无限授权**：方便但危险，钱包应提示并支持一键撤销；
- **非标准行为**：转账扣税（fee-on-transfer）、余额 rebasing、转账回调（ERC-777 的 `tokensToSend`/`tokensReceived`）都会破坏集成方假设，ERC-777 的回调曾导致重入漏洞。

ERC-20 的"标准"其实很宽松：返回值、事件、精度（decimals）都有实现差异，集成方必须做兼容处理。

## NFTs: ERC-721 and ERC-1155

- **ERC-721**：每个 token 有唯一 `tokenId`，`ownerOf` 查询所有者，`tokenURI` 指向元数据（通常是 IPFS/Arweave 上的 JSON），`safeTransferFrom` 会调用接收方回调；
- **ERC-1155**：一个合约管理多种 token（同质化 + 非同质化），批量转账，适合游戏道具；
- **元数据**：链上存储成本高，多数 NFT 只把元数据哈希或 URI 上链，图片与属性存在链下。**"链上 NFT"通常只指所有权，不指内容**；
- **版税（ERC-2981）**：只是"建议版税"，市场可以忽略；强制执行需要市场白名单或链上转移限制；
- **灵魂绑定（SBT）**：不可转让的代币，用于身份、证书、声誉；
- **Token Bound Accounts（ERC-6551）**：让 NFT 拥有自己的合约账户，可持有资产、参与治理。

NFT 的稀缺性由合约与社区共识共同定义，代码只保证"唯一性"与"转移规则"，不保证价值。

## Vaults and Yield Tokens

**ERC-4626** 把"生息金库"标准化：用户存入资产获得份额（shares），份额价值随策略收益增长。

- 存款：`deposit(assets)` → 铸造 shares；
- 取款：`redeem(shares)` → 返回 assets；
- 份额价格 = `totalAssets / totalSupply`，需防范通胀攻击（首次存款者操纵份额价格）；
- 适用于借贷池、流动性质押、收益聚合器、RWA 金库。

标准化让聚合器可以统一接入不同协议，但也把"策略风险"隐藏在份额价格里：用户看到的 APY 可能来自杠杆、期限错配或补贴，而不是可持续收益。

## DeFi Primitives

- **AMM（自动做市商）**：用流动性池替代订单簿。恒定乘积 `x * y = k` 是最基础模型，Uniswap v3 引入集中流动性，把资金集中在价格区间提高资本效率；
- **借贷**：超额抵押借贷（Aave、Compound），清算人用折扣价偿还债务并获得抵押品，依赖预言机价格；
- **稳定币**：见下节；
- **衍生品**：永续合约、期权、合成资产，依赖资金费率与预言机；
- **流动性质押（LST）**：质押 ETH 获得可流通凭证（stETH、rETH），把质押流动性释放出来；
- **再质押（restaking）**：把 LST 再次用于其他协议的安全，收益叠加、风险传染；
- **聚合器与路由**：把多笔交易拆到不同协议，优化滑点与手续费。

DeFi 的可组合性让这些原语可以嵌套：抵押品 → 借贷 → 再质押 → 加杠杆。嵌套提高了资本效率，也让单点故障沿调用链传播。每个原语的风险来源、MEV 与 RWA 的完整版图见 [DeFi and NFT](/docs/CS/Blockchain/Web3/DeFi_and_NFT.md)。

## Stablecoins

稳定币是链上经济的计价单位，按锚定机制分类：

| 类型 | 代表 | 锚定方式 | 主要风险 |
| --- | --- | --- | --- |
| 法币抵押 | USDT、USDC | 银行储备 1:1 | 储备透明度、托管与监管冻结 |
| 加密抵押 | DAI、LUSD | 超额抵押加密资产 | 抵押品暴跌、清算拥堵、预言机 |
| 算法稳定币 | 历史 UST | 算法与姊妹代币调节 | 死亡螺旋，UST 2022 崩溃 |
| 收益型稳定币 | USDe 等 | 抵押品收益 + 对冲 | 对冲对手方、资金费率、托管 |

稳定币的核心问题是**信任锚**：法币抵押信任发行方与银行，加密抵押信任清算机制与预言机，算法稳定币信任市场激励。没有免费的稳定。

监管正在收紧：储备审计、发行许可、KYC/AML、跨境支付规则都在逐步落地，见下文合规部分。

## Tokenomics

代币经济设计回答四个问题：

1. **代币有什么用**：支付、治理、质押、折扣、积分，还是纯投机？
2. **供应如何变化**：固定上限、通胀、销毁、回购；
3. **如何分配**：团队、投资人、社区、金库，解锁与归属（vesting）如何安排；
4. **价值如何捕获**：手续费分成、回购销毁、质押收益，还是只有治理权？

常见陷阱：

- **高 FDV、低流通**：少量流通盘支撑高估值，解锁期到来时持续抛压；
- **不可持续的补贴**：用代币补贴流动性，补贴停止后 TVL 迅速流失；
- **治理代币无现金流**：投票权与实际控制权分离，治理沦为形式；
- **veToken 锁仓**：延长锁仓换取投票权与收益，牺牲流动性并加剧治理集中。

投票权如何变成可执行的决策，取决于治理流水线：委托、提案门槛、法定人数、时间锁与执行层多签，见 [DAO](/docs/CS/Blockchain/Web3/DAO.md)。

代币价格不是协议健康的指标。看 TVL、真实收入、用户留存与治理参与度，比看市值更有意义。

## Market Structure and MEV

- **DEX 与 CEX**：链上撮合透明但受 MEV 影响，中心化交易所流动性好但有托管风险；
- **MEV**：搜索者通过抢跑、尾随、三明治攻击获取排序价值，用户承担滑点；
- **PBS**：提议者-构建者分离把区块构建外包，缓解验证者中心化但引入中继信任；
- **流动性提供**：LP 赚取手续费，承担无常损失（impermanent loss）与 MEV 被提取的风险；
- **预言机**：价格源决定清算与衍生品结算，单一来源是系统性风险。

## Legal and Compliance

- **证券属性**：多数司法辖区用"投资合同"标准判断代币是否属于证券，取决于销售方式、预期收益与依赖他人努力；
- **MiCA**：欧盟加密资产市场监管框架自 2024 年起分阶段适用，对稳定币发行、交易平台、托管与披露提出要求；
- **KYC/AML**：中心化交易所与托管商普遍执行，DeFi 前端与钱包面临越来越大的合规压力；
- **税务**：交易、质押收益、空投、跨链转移的税务处理因辖区而异；
- **制裁**：地址黑名单与协议层冻结（如稳定币发行方）是现实存在的中心化干预手段。

主要辖区的稳定币立法（储备要求、付息禁令、发牌制度）与建设者尽调清单见 [Privacy and Compliance](/docs/CS/Blockchain/Web3/Privacy_and_Compliance.md)。

## Design Pitfalls

- **不要用 ERC-20 表示"股份"或"债权"**，除非法律结构清晰；
- **授权最小化**：只授权必要额度，使用 `permit` 时注意签名重放与过期时间；
- **兼容非标准代币**：用 `safeTransfer` 封装，检查返回值与实际到账金额；
- **避免 rebasing 代币做抵押**：余额变化会破坏会计与清算；
- **可升级代币的权力**：铸造、冻结、黑名单权限必须多签 + 时间锁，并公开披露；
- **经济模型审计**：代码审计不能替代代币经济与博弈分析。

## Links

- [Smart Contract](/docs/CS/Blockchain/SmartContract.md)
- [Ethereum](/docs/CS/Blockchain/Ethereum.md)
- [Web3](/docs/CS/Blockchain/Web3.md)
- [Security](/docs/CS/Blockchain/Security.md)
- [Layer 2](/docs/CS/Blockchain/Layer2.md)
- [Blockchain](/docs/CS/Blockchain/Blockchain.md)

## References

1. [EIP-20: Token Standard](https://eips.ethereum.org/EIPS/eip-20)
2. [EIP-721: Non-Fungible Token Standard](https://eips.ethereum.org/EIPS/eip-721)
3. [EIP-4626: Tokenized Vault Standard](https://eips.ethereum.org/EIPS/eip-4626)
4. [EIP-2612: Permit Extension for ERC-20](https://eips.ethereum.org/EIPS/eip-2612)
5. [MiCA Regulation Overview](https://www.esma.europa.eu/esmas-activities/digital-finance-and-innovation/markets-crypto-assets-regulation-mica)
