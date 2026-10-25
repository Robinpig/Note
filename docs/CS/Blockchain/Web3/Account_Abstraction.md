## Introduction

传统以太坊账户（EOA）的验证逻辑写死在协议里：一条 secp256k1 签名、一个自增 nonce、gas 必须用 ETH 支付。这意味着私钥一旦丢失账户就没了，也无法批量操作、无法让别人代付、无法设置权限分级。**账户抽象（Account Abstraction, AA）**的目标是把"什么算有效授权"从协议规则变成可编程逻辑，让账户像合约一样可以定义自己的验证方式。

这不只是体验优化，而是信任模型的迁移：**签名验证从协议层下沉到合约层**。协议保证 EOA 签名不可绕过；账户抽象之后，安全性由账户合约与其模块的代码质量决定。前置知识见 [EVM](/docs/CS/Blockchain/Ethereum/EVM.md)，账户与密钥基础见 [Identity and Wallet](/docs/CS/Blockchain/Web3/Identity_and_Wallet.md)。

## ERC-4337 Flow

ERC-4337 不修改共识层，而是在协议外搭一整套并行设施：

```
用户签 UserOperation → 提交到 alt mempool → Bundler 打包 → EntryPoint.handleOps()
                                                              ├─ Account.validateUserOp()   验证
                                                              ├─ Paymaster.validatePaymasterUserOp()  代付
                                                              └─ Account.execute()         执行
```

四个角色：

- **UserOperation**：描述"账户想做什么"的结构化意图，不是交易。包含 sender、nonce、callData、gas 参数与签名；
- **EntryPoint**：全网共享的单例合约，负责验证、执行与 gas 结算。它是唯一被账户信任的调用方——合约账户只接受来自自己认可 EntryPoint 的调用；
- **Bundler**：链下服务，收集 UserOperation、模拟验证、打包成一笔普通交易提交上链，并垫付 gas 后结算；
- **Paymaster**：可选的 gas 支付合约，可以代用户付费，或让用户用 ERC-20 付费，从而实现"首次使用无需先持有 ETH"；
- **Factory**：用 CREATE2 部署账户合约，因此账户地址可以在部署前就算出来（反事实地址），用户先收款再部署。

EntryPoint 以不可变合约部署，升级靠"在新地址部署新版本"。已部署的主要版本：

| 版本 | 地址 | 说明 |
| --- | --- | --- |
| v0.6 | `0x5FF1...2789` | 初版规范 |
| v0.7 | `0x0000...a032` | UserOperation 字段打包，gas 显著下降 |
| v0.8 | `0x4337...f108` | 过渡版本 |
| v0.9 | `0x4337...d009` | 官方仓库当前最新版本（2026 年中），与 v0.7/v0.8 的账户与 paymaster 接口 ABI 兼容 |

版本碎片化是 AA 的现实成本：**账户、bundler、paymaster、factory 必须指向同一个 EntryPoint 版本**，跨版本提交 UserOperation 会失效。EntryPoint 地址本身参与操作哈希计算，因此它不只是路由，还是安全上下文的一部分。

为防止 bundler 被 DoS，规范对验证阶段做了严格限制：验证期间只能访问与 `sender` 关联的存储槽、禁用部分不确定性的 opcode、并且验证 gas 有上限。违反约束的 UserOperation 会被 bundler 直接丢弃。

## Modular Accounts

早期每个钱包厂商自己实现一套账户与插件，模块无法跨账户复用。两个标准试图统一插件接口：

- **ERC-7579**（Rhinestone、Biconomy、ZeroDev、OKX 等提出，**minimal** 路线）：只规定模块互操作所需的最小接口——`installModule` / `uninstallModule` / `isModuleInstalled`，模块分四类：

| 类型 | 职责 | 典型实现 |
| --- | --- | --- |
| Validator | 判断签名/操作是否被授权 | 多签、passkey、session key、 guardian 恢复 |
| Executor | 以账户身份发起调用 | 自动定投、订阅扣款、AI agent 预算 |
| Fallback | 处理账户原生不支持的 selector | 兼容旧接口、扩展 ABI |
| Hook | 执行前后插入检查 | 限额、黑名单、时间锁冷却 |

- **ERC-6900**（Alchemy 提出，**prescriptive** 路线）：额外规定严格的存储布局与模块依赖清单，规范性强但灵活性低。

现实结果是最小接口路线胜出：ERC-7579 成为新建智能账户的默认选择，老牌账户（如 Safe）通过适配器支持。账户内部多用 ERC-7201 命名空间存储，避免模块之间的存储槽冲突。

模块生态的关键风险是**供应链**：模块以账户的完整权限运行，恶意 validator 可以授权任何操作，恶意 executor 可以转走资产。行业做法是模块注册表（如 Rhinestone 的注册表）配合具名审计方的证明，账户可配置"只接受持有指定审计方证明的模块"。

## EIP-7702

ERC-4337 要求用户迁移到新账户；EIP-7702 走另一条路：**让现有 EOA 直接获得智能账户能力**。

- 引入交易类型 `0x04`（Set Code Transaction），携带 `authorization_list`；
- EOA 持有者签署一条授权，声明把本账户的执行委托给某个合约地址；
- 协议把 `0xef0100 || address`（23 字节委托指示符）写入该 EOA 的 code 字段；
- 此后任何对该 EOA 的调用都执行被委托合约的逻辑，但**存储、地址、余额和 nonce 语义保持不变**；
- 委托持续有效，直到再次授权新目标（包括授权到零地址以退回普通 EOA），因此可以撤销；
- 每条授权约 12,500 gas（授权到尚不存在的账户另计约 25,000）。

EIP-7702 随 **Pectra** 升级于 2025 年 5 月 7 日（epoch 364032）在主网激活，兼容现有 4337 基础设施：paymaster、bundler、智能账户实现基本可以复用。

安全上它是双刃剑：

- **私钥泄露的后果被放大**：攻击者不只转走现有余额，还能把账户委托给"清扫合约"，使此后任何转入的资金被自动转走，用户救不回来；
- **跨链授权**：`chain_id = 0` 的授权在多条链上同时有效，一次签名影响所有链，因此逐链授权是更安全的默认；
- **委托目标必须可信**：只委托给已审计、已验证源码、被广泛使用的实现，并在重新委托前检查存储槽兼容性；
- **旧假设失效**：EIP-7702 之后，"地址没有 code"不再等价于"这是一个人而非合约"，依赖该判断的合约逻辑需要重写。

钱包侧的缓解措施包括委托警告、实现合约白名单与一键撤销工具，但这些是 UI 层面约定，不是协议强制。

## Passkeys and Secure Enclaves

助记词是 Web3 最大的体验障碍，也是最集中的单点故障。替代方案是用设备里的安全芯片（Apple Secure Enclave、Android Keystore、FIDO2/WebAuthn 硬件钥匙）签名：

- 这些芯片用的是 **secp256r1（P-256）** 曲线，与以太坊原生的 **secp256k1** 不兼容；
- 纯 Solidity 实现 P-256 验签约需 20 万~33 万 gas，远高于 21,000 的基础转账成本，无法实用；
- **RIP-7212** 定义了位于 `0x100` 的 P256VERIFY 预编译（约 3,450 gas），先在多条 L2 上落地；
- **EIP-7951** 把同接口带到以太坊 L1，定价 6,900 gas（高于 RIP-7212 以防滥用，并修复了一个边界 bug），随 **Fusaka** 升级于 2025 年 12 月 3 日（slot 13,164,544）激活。

结果是"刷脸建钱包"成为可能：私钥由设备安全芯片生成且不可导出，账户由合约验证 WebAuthn 签名。代价是**身份与设备绑定**——设备丢失要靠社交恢复或云端密钥同步兜底，而这又引入了对厂商的依赖。

## Native Account Abstraction

以太坊是"EOA + 合约账户"的双轨制，AA 是后加的一层；另一类链从一开始就只有合约账户：

- **zkSync Era / Starknet**：没有 EOA 与合约账户之分，每个账户都是合约，自带 `validate` 与 `execute`，签名方案、nonce 规则、gas 支付都由账户自己定义；
- **影响**：这些链上"账户抽象"不是一个特性，而是默认工作方式；代价是账户合约的 gas 开销与开发模型与以太坊不同，工具链不能直接照搬。

以太坊 L1 的长期方向是把更多账户能力下沉到协议（如 7702 已经做的），但原生 AA 尚未成为协议目标，现阶段工程上仍以 4337 + 7702 + 7579 的组合为主。

## Capability Discovery

DApp 不该假设用户用的是 EOA 还是智能账户。相关接口：

- **EIP-5792**：钱包向 DApp 暴露能力（`wallet_sendCalls` 批量调用、`wallet_getCapabilities` 查询是否支持代付/批量/原子性），前端据此决定交互方式；
- **EIP-7677**：DApp 与 paymaster 之间的标准交互，用于获取代付所需的上下文参数；
- **EIP-1271**：合约账户签名验证，服务端登录验签必须支持，见身份分册。

这套接口的意义是**让应用与账户形态解耦**：前端只描述意图，由钱包决定如何执行。

## Risk Model

账户抽象把安全边界从"保管好私钥"扩展到一整条链：

1. **账户合约与模块**：`validateUserOp` 是新的安全边界，必须按最高标准审计；模块以账户完整权限运行；
2. **EntryPoint 与 bundler**：EntryPoint 是被信任的全局单例，bundler 可以审查或延迟打包，memPool 的可用性依赖少数服务商；
3. **Paymaster**：代付方可以审查交易、随时停止服务，用户的"无 gas 体验"绑定在某个运营方身上；
4. **委托与恢复**：7702 的委托目标、社交恢复的 guardian 集合，都是新的攻击面；
5. **可移植性**：账户标准仍在演进，EntryPoint 与模块版本碎片化，账户迁移能力弱于资产迁移。

结论是：**AA 用合约风险换取了体验与可恢复性**。对新手与高频交互场景这个交换通常划算；对长期不动的大额资产，简单、无升级、无模块的方案往往更稳。

## Links

- [Web3](/docs/CS/Blockchain/Web3.md)
- [Identity and Wallet](/docs/CS/Blockchain/Web3/Identity_and_Wallet.md)
- [EVM](/docs/CS/Blockchain/Ethereum/EVM.md)
- [Ethereum](/docs/CS/Blockchain/Ethereum.md)
- [Smart Contract](/docs/CS/Blockchain/SmartContract.md)
- [Security](/docs/CS/Blockchain/Security.md)

## References

1. [EIP-4337: Account Abstraction Using Alt Mempool](https://eips.ethereum.org/EIPS/eip-4337)
2. [EIP-7702: Set EOA account code](https://eips.ethereum.org/EIPS/eip-7702)
3. [EIP-7951: Precompile for secp256r1 Curve Support](https://eips.ethereum.org/EIPS/eip-7951)
4. [RIP-7212: secp256r1 Precompile](https://github.com/ethereum/RIPs/blob/master/RIPS/rip-7212.md)
5. [ERC-7579: Minimal Modular Smart Accounts](https://ercs.ethereum.org/ERCS/erc-7579)
6. [ERC-6900: Modular Smart Contract Accounts and Plugins](https://ercs.ethereum.org/ERCS/erc-6900)
7. [ERC-7201: Namespaced Storage Layout](https://ercs.ethereum.org/ERCS/erc-7201)
8. [EIP-5792: Wallet Function Call API](https://eips.ethereum.org/EIPS/eip-5792)
9. [ERC-6551: Non-fungible Token Bound Accounts](https://ercs.ethereum.org/ERCS/erc-6551)
10. [Fusaka Mainnet Announcement](https://blog.ethereum.org/2025/11/06/fusaka-mainnet-announcement)
11. [Ethereum Pectra Upgrade](https://ethereum.org/en/roadmap/pectra/)
