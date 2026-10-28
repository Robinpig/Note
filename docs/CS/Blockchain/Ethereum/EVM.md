## Introduction

EVM（Ethereum Virtual Machine）是以太坊的执行引擎：一个**确定性、沙箱化、按 gas 计量**的栈式虚拟机。所有节点对同一笔交易执行同一段字节码，必须得到完全相同的结果；任何不确定的行为（随机数、时间、外部 IO）都被排除或通过协议参数注入。

理解 EVM 是理解 gas 成本、合约漏洞、Rollup 兼容性与账户抽象的前提。合约语言与工程实践见 [Smart Contract](/docs/CS/Blockchain/SmartContract.md)，账户与交易层见 [Ethereum](/docs/CS/Blockchain/Ethereum.md)。

## Machine Model

EVM 有六个数据区域：

| 区域 | 特性 | 生命周期 |
| --- | --- | --- |
| Stack | 最多 1024 项，每项 256 位，只能操作栈顶附近 | 调用内 |
| Memory | 字节寻址、按 32 字节字扩展、初始为 0 | 调用内 |
| Storage | 256 位键值对，持久化到账户 | 永久 |
| Calldata | 只读输入数据 | 调用内 |
| Returndata | 最近一次外部调用的返回数据 | 调用内 |
| Transient Storage | EIP-1153 引入，交易结束清空 | 交易内 |

EVM 是**256 位字长**的：地址、金额、哈希片段都用 32 字节表示。这简化了密码学运算，却让 32 位/64 位整数运算在链上变得昂贵，合约必须小心处理溢出（Solidity 0.8+ 默认检查）。

栈深限制 1024，编译器需要把复杂表达式拆成多次栈操作；内存扩展成本按二次方增长：

```
memory_cost(words) = 3 * words + words² / 512
```

这防止合约用少量 gas 申请巨量内存。

## Execution Context and Calls

合约之间的交互通过调用指令完成：

- **CALL**：调用另一合约，切换存储上下文，可携带 value；
- **STATICCALL**：只读调用，禁止状态修改（EIP-214）；
- **DELEGATECALL**：在**当前合约的存储上下文**中执行对方代码，是代理模式的基础；
- **CALLCODE**：已废弃，语义类似 delegatecall 但 value 语义不同。

调用时 gas 转发遵循 **63/64 规则**（EIP-150）：最多转发剩余 gas 的 63/64，保留 1/64 给调用方处理失败。这防止被调用方耗尽全部 gas 导致调用方无法回滚。

一次交易内的所有调用共享状态，任一调用 revert 会回滚整棵调用树的状态变更（但已消耗的 gas 不退）。这个"全有或全无"的原子性既是可组合性的来源，也是重入攻击的土壤。

## Gas

Gas 是防止无限循环与资源滥用的核心机制。主要成本：

| 操作 | Gas | 说明 |
| --- | --- | --- |
| 交易基础费 | 21000 | 每笔交易固定 |
| calldata | 4 / 16 per byte | 零字节 / 非零字节 |
| SLOAD | 100 warm / 2100 cold | EIP-2929 冷热访问 |
| SSTORE | 20000 / 2900 / 2900 | 0→非0 / 非0→非0 / 非0→0 |
| CALL | 700 + 2600 cold + 9000 value | 冷账户访问另计 |
| CREATE | 32000 + 200/byte | 部署代码按字节计费 |
| LOG | 375 + 375/topic + 8/byte | 事件日志 |
| Memory | 二次方增长 | 见上 |

- **冷/热访问**：同一交易内首次访问账户或存储槽是冷访问（2100/2600），之后变热（100）。EIP-2930 的 access list 允许预先声明，降低冷访问开销；
- **退款**：清除存储可退还 gas，但退款上限为交易消耗的 1/5（EIP-3529），防止"边写边删"套利；
- **calldata 与 blob**：calldata 便宜是 Rollup 的基础；Pectra 的 EIP-7623 为 calldata 设置最低计价，压缩其成本优势，引导 Rollup 转向 blob；
- **合约大小上限**：运行时代码 24 KiB（EIP-170），初始化代码 48 KiB（EIP-3860），推动库拆分与代理模式。

Gas 价格由 EIP-1559 的基础费 + 小费决定，用户在 `maxFeePerGas` 内竞价。gas 既是成本，也是安全边界：任何可能无限循环的操作都必须有 gas 上限。

## Storage and State Layout

合约存储是一个从 256 位键到 256 位值的映射，**不可枚举**。Solidity 的布局规则：

- 定长变量按声明顺序从 slot 0 开始，能放进同一 32 字节槽的变量会打包；
- 动态数组的槽存长度，元素从 `keccak256(slot)` 开始；
- `mapping` 的槽本身为空，值位于 `keccak256(key . slot)`；
- 继承按 C3 线性化顺序排列，`immutable` 存在代码中而非存储。

这些规则在写代理合约时至关重要：**升级后的实现合约必须保持存储布局兼容**，否则旧数据会被解释成新变量。EIP-1967 规定实现地址存放在特定哈希槽（如 `keccak256("eip1967.proxy.implementation") - 1`），避免与业务变量冲突。

存储写入是链上最贵的操作。优化思路通常是：打包变量、减少写入次数、用事件代替链上状态（当状态不被合约读取时）、用 Merkle 证明或链下索引替代全量存储。

## Contract Creation and Bytecode

部署合约时，交易携带**初始化代码**，EVM 执行它并返回**运行时代码**：

```
creation_code = init_code ++ runtime_code
执行 init_code → 返回 runtime_code → 存入 codeHash
```

- **CREATE**：地址由发送者与 nonce 决定，依赖部署顺序；
- **CREATE2**：地址由发送者、salt 与初始化代码哈希决定，可预测，适合状态通道、确定性部署与"反事实地址"；
- **最小代理（EIP-1167）**：用 45 字节的转发代码把调用委托给实现合约，大幅降低部署成本；
- **SELFDESTRUCT**：Cancun 的 EIP-6780 后，只有同一交易内创建的合约才能真正删除，旧合约只能转走余额；
- **EOF**：可扩展字节码格式讨论多年，2025 年 4 月被移出 Fusaka，此后随 Glamsterdam 推进；截至 2026 年 10 月主网仍未启用，部署前须核对当前硬分叉清单。

字节码在部署前会经过编译器优化，但**链上验证的是字节码，不是源码**。区块浏览器上的源码需要项目方提交并匹配，未验证合约无法直接审计。

## ABI, Events and Logs

- **ABI**：函数调用的编码规范。前 4 字节是 `keccak256("transfer(address,uint256)")` 的前缀（selector），参数按 32 字节对齐，动态类型用偏移量；
- **事件**：`LOG0`–`LOG4`，最多 4 个 topic（第一个通常是事件签名哈希），data 存非索引字段；
- **收据与 Bloom**：交易收据包含日志与状态，区块头有 Bloom 过滤器，轻客户端可快速判断区块是否包含某地址的事件；
- **索引**：日志适合"追加 + 按 topic 过滤"，不适合复杂查询；The Graph 等索引器把日志转成可查询的数据库。

事件比存储便宜得多（约 8 gas/byte 加基础费），因此"链上只存必要状态、事件记录历史"是常见设计。但事件不被合约读取，链上逻辑不能依赖事件。

## Precompiles

预编译合约是以太坊内置的高成本密码学/哈希操作，用原生代码实现，gas 远低于纯 EVM 实现：

| 地址 | 功能 |
| --- | --- |
| 0x01 | ecrecover（ECDSA 恢复） |
| 0x02 | SHA-256 |
| 0x03 | RIPEMD-160 |
| 0x04 | identity（数据复制） |
| 0x05 | modexp（模幂） |
| 0x06–0x08 | bn256 椭圆曲线运算与配对 |
| 0x09 | BLAKE2b F 压缩函数 |
| 0x0a | KZG point evaluation（blob 验证） |
| 0x0b–0x11 | BLS12-381 运算（Pectra） |
| 0x0100 | secp256r1 / P-256 签名验证（EIP-7951，Fusaka） |

预编译是以太坊"密码学能力"的边界：新的曲线或证明系统需要硬分叉加入预编译，否则只能靠昂贵的纯 EVM 实现，这也是 zk 应用与 L2 选择自定义预编译的原因。

## Account Abstraction

传统 EOA 的验证逻辑写死在协议里（ECDSA + nonce），无法支持社交恢复、批量交易、代付 gas。两条路线：

- **EIP-4337**：不改变协议，引入 `UserOperation`、`EntryPoint` 合约、Bundler、Paymaster、Smart Account。用户签的是 UserOperation，Bundler 打包上链，Paymaster 可代付 gas；
- **EIP-7702**：Pectra 引入，允许 EOA 签署授权，把执行委托给指定合约代码，同时保留 EOA 地址与余额。它让现有 EOA 也能获得智能账户能力，但引入了委托目标与存储语义的新风险。

账户抽象改善了用户体验，却把"签名验证"从协议层移到了合约层——**钱包安全从私钥保护扩展到合约审计**。完整的 UserOperation 生命周期、EntryPoint 版本、模块化账户（ERC-7579）与 Passkey 签名见 [Account Abstraction](/docs/CS/Blockchain/Web3/Account_Abstraction.md)。

## Determinism and Upgrades

EVM 的确定性依赖严格的规则：同一字节码、同一输入、同一状态、同一 gas limit，必须得到同一结果。因此：

- 不能使用真实随机数、系统时间、网络 IO；
- 区块时间、区块号、`blockhash` 等只能作为有限范围的输入；
- 客户端实现必须逐条对齐 gas 与边界行为，任何分歧都会导致共识分裂；
- 新操作码、新预编译、gas 重定价都需要硬分叉，且要考虑历史交易的重放兼容性。

这也解释了为什么 EVM 的演进如此保守：它不是普通软件，而是**全网共同执行的规范**。

## Links

- [Ethereum](/docs/CS/Blockchain/Ethereum.md)
- [Smart Contract](/docs/CS/Blockchain/SmartContract.md)
- [Beacon Chain](/docs/CS/Blockchain/Ethereum/Beacon.md)
- [Layer 2](/docs/CS/Blockchain/Layer2.md)
- [Token](/docs/CS/Blockchain/Token.md)
- [Architecture](/docs/CS/Blockchain/Architecture.md)

## References

1. [Ethereum Yellow Paper](https://ethereum.github.io/yellowpaper/paper.pdf)
2. [EVM Opcodes Reference](https://www.evm.codes/)
3. [EIP-2929: Gas Cost Increases for State Access Opcodes](https://eips.ethereum.org/EIPS/eip-2929)
4. [EIP-1153: Transient Storage Opcodes](https://eips.ethereum.org/EIPS/eip-1153)
5. [EIP-4337: Account Abstraction Using Alt Mempool](https://eips.ethereum.org/EIPS/eip-4337)
