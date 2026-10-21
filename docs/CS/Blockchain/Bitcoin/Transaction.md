## Introduction

比特币没有账户余额，只有**未花费交易输出（UTXO, Unspent Transaction Output）**。一笔交易声明"我要花掉哪些旧输出、生成哪些新输出"，全节点检查输入是否存在、是否未被花费、签名是否有效，通过后删除旧输出、写入新输出。这个模型决定了比特币的验证方式、手续费计算、隐私特性与钱包架构。

这一页按"结构 → 脚本 → 签名 → 升级 → 费用"的顺序讲透交易，配合 [Architecture](/docs/CS/Blockchain/Architecture.md) 的状态模型对比阅读。

## UTXO Model

UTXO 是比特币的"硬币"：每个输出有唯一标识 `txid:vout`、一个金额、一段锁定脚本。交易在链上的生命周期：

1. 创建时作为某笔交易的输出存在，进入 UTXO 集合；
2. 被后续交易引用为输入后，标记为已花费并从 UTXO 集合移除；
3. 找零会生成新的输出，继续留在集合中。

对钱包而言，可用余额 = **自己控制的 UTXO 金额之和**。发送时钱包需要选择若干 UTXO 作为输入，找零回自己的地址，这个选择过程叫 **coin selection**。UTXO 越多，交易输入越多、手续费越高，因此钱包会做 UTXO 整理（consolidation）。

UTXO 模型的性质：

- **天然并行验证**：只要两笔交易不引用同一输出，就可独立验证；
- **无重放**：输出只能被花费一次，不存在账户 nonce 概念；
- **隐私较弱**：输入之间的关联会暴露"这些币属于同一个人"；
- **拼装复杂**：需要凑输入、算找零、处理粉尘输出。

## Transaction Structure

```
version
vin_count
  ┌ prev_txid (32B)
  │ prev_vout (4B)
  │ scriptSig (可变长)
  │ sequence (4B)
  └ ...
vout_count
  ┌ value (8B, 单位 satoshi)
  │ scriptPubKey (可变长)
  └ ...
witness (仅 SegWit 交易)
locktime (4B)
```

- **value**：以 satoshi 计（1 BTC = 10^8 sat），整数运算避免浮点误差；
- **sequence**：历史上用于交易替换，现在主要承载相对时间锁（BIP68）；
- **locktime**：绝对时间锁，交易在指定高度/时间之前不能上链；
- **witness**：SegWit 引入的独立数据结构，存放签名等解锁数据。

交易费不是字段，而是**输入总额减去输出总额**。这个设计让手续费可以被矿工直接"找零"给自己（coinbase），无需额外记账。

## Script

每个输出的 `scriptPubKey` 是锁定条件，花费时在 `scriptSig`/witness 中提供解锁数据。脚本是**栈式、从左到右执行、无循环、非图灵完备**的语言，刻意保证停机与可静态分析。

最经典的 P2PKH 锁定脚本：

```
OP_DUP OP_HASH160 <pubKeyHash> OP_EQUALVERIFY OP_CHECKSIG
```

解锁脚本提供 `<signature> <pubKey>`，执行过程：复制公钥 → 哈希 → 与锁定值比较 → 用公钥验证签名。P2SH 把复杂脚本的哈希放进输出，花费时才揭示脚本：

```
OP_HASH160 <scriptHash> OP_EQUAL
```

标准脚本类型：

| 类型 | 锁定形式 | 地址前缀 | 说明 |
| --- | --- | --- | --- |
| P2PK | `<pubKey> OP_CHECKSIG` | 无 | 早期直接付公钥 |
| P2PKH | 公钥哈希 + CHECKSIG | `1...` | 最经典 |
| P2SH | 脚本哈希 | `3...` | 多签、时间锁 |
| P2WPKH | `OP_0 <20B hash>` | `bc1q...` | 原生 SegWit |
| P2WSH | `OP_0 <32B hash>` | `bc1q...` | 复杂见证脚本 |
| P2TR | `OP_1 <32B tweaked key>` | `bc1p...` | Taproot |

**表达力的取舍**：比特币脚本没有状态、没有循环、不能任意读写存储，所以无法实现以太坊式的通用合约。但时间锁（`OP_CHECKLOCKTIMEVERIFY`、`OP_CHECKSEQUENCEVERIFY`）、多签、哈希锁（`OP_SHA256` + `OP_EQUALVERIFY`）足以支撑支付通道、原子交换、托管等协议，这些正是闪电网络的基础。

`OP_RETURN` 是唯一被标准性允许的"数据载体"，用于把少量数据（如哈希、协议标记）写进链上，不占用 UTXO 集合。Ordinals 铭文则绕过了 `OP_RETURN` 的限制，把数据写入 Taproot 见证字段，引发了区块空间用途的争论。

## Signatures

比特币使用 secp256k1 曲线：

- **ECDSA**：早期唯一选择，签名是 DER 编码的 `(r, s)`。BIP62/146 要求 `s` 取低半区（low-S）以消除签名延展性；`SIGHASH` 标志决定签名覆盖交易哪些部分；
- **Schnorr**（BIP340）：Taproot 引入，签名固定 64 字节，可聚合（MuSig2），原生支持批量验证，且没有 ECDSA 的延展性问题；
- **SIGHASH 类型**：`ALL`（默认，覆盖全部输入输出）、`NONE`（不签输出）、`SINGLE`（只签对应序号的输出）、`ANYONECANPAY`（只签自己的输入）。组合使用可实现协作者追加输入、部分签名等协议。

签名只证明"私钥持有者授权了这笔交易"，不证明"这笔交易是安全的"。地址投毒、恶意合约授权（在以太坊更常见）、钓鱼签名请求，都是签名之外的社会工程问题。

## SegWit

SegWit（BIP141/143，2017 年激活）解决了两个问题：

1. **交易延展性（malleability）**：ECDSA 签名可被第三方轻微修改而不失效，导致 `txid` 变化，破坏依赖未确认交易的协议（如闪电网络）。SegWit 把签名移出 `txid` 的计算范围；
2. **区块容量**：引入"权重"概念，见证数据按 1/4 计费。

```
weight = base_size * 3 + total_size
vsize  = ceil(weight / 4)
区块上限 = 4,000,000 weight units
```

见证折扣使同样字节的签名数据只占 1/4 权重，等效容量提升到约 1.5–2 MB。地址编码使用 bech32（BIP173），具备纠错与更低的哈希冲突风险。

SegWit 是软分叉：旧节点把 P2WPKH 输出视为"任何人都能花"，但仍然接受这些交易，只是无法验证见证规则。这种兼容性是比特币升级的标准模式。

## Taproot

Taproot（BIP340/341/342，2021 年 11 月激活）是 SegWit v1，把 Schnorr 签名、MAST 与密钥聚合组合起来：

- **密钥路径花费**：把脚本树根" tweak"进公钥，正常情况只需一个 Schnorr 签名，链上看起来与普通支付无异；
- **脚本路径花费**：只有走非默认分支时才揭示脚本与 Merkle 路径，未使用的分支保持隐私；
- **MAST**：脚本树只承诺实际存在的分支，降低复杂脚本的链上成本；
- **MuSig2**：多签在链上聚合为单个公钥、单个签名，既省费又隐藏参与方数量。

Taproot 让"复杂条件支付"在外观上与普通支付不可区分，是隐私与效率的显著改进。闪电网络的 Taproot 通道、DLC（离散对数合约）都建立在其上。

## Fees

手续费由市场决定，矿工按 **sat/vB** 排序打包：

- **费率估算**：钱包根据 mempool 近期区块的费率分布给出目标确认时间的费率；
- **RBF（BIP125）**：用更高手续费的版本替换未确认交易，要求原交易标记 `sequence < 0xfffffffe` 并支付更高的绝对费用；
- **CPFP**：子交易支付高费率，带动父交易一起被矿工选中；
- **包中继（package relay）**：允许父子交易作为整体中继与验证，解决"父交易费率太低无法单独进入 mempool"的问题；
- **TRUC/v3 交易**：限制未确认后代数量，配合临时锚点（ephemeral anchor）实现更可预测的费用追加；
- **粉尘阈值**：低于经济阈值的输出（P2PKH 约 546 sat，P2WPKH 约 294 sat）会被标准性规则拒绝，因为花费它的成本高于其价值。

常见输入/输出体积（用于估算）：

| 类型 | 输入 vsize | 输出 vsize |
| --- | --- | --- |
| P2PKH | ~148 vB | ~34 vB |
| P2WPKH | ~68 vB | ~31 vB |
| P2TR | ~57.5 vB | ~43 vB |

一笔 1 输入 2 输出的 P2WPKH 交易约 141 vB；费率为 10 sat/vB 时手续费约 1410 sat。费率高峰期（如铭文热潮）可达数百 sat/vB，这也是 Layer 2 存在的直接动力。

## Safety Notes

- **找零地址与地址复用**：复用地址会泄露关联性；现代钱包每次派生新地址；
- **手续费替换攻击**：RBF 允许替换，收款方应以足够确认数作为最终性；
- **粉尘攻击**：攻击者向大量地址发送小额 UTXO，诱导钱包把它们花掉以关联身份；钱包应隔离或冻结可疑 UTXO；
- **历史漏洞**：2010 年的数值溢出漏洞（CVE-2010-5139）曾凭空产生 1844 亿 BTC，几小时内通过软分叉回滚；此后金额与脚本规则被严格审计；
- **签名前核对**：硬件钱包屏幕上的收款地址与金额是最后防线，务必逐字核对。

## Links

- [Bitcoin](/docs/CS/Blockchain/Bitcoin.md)
- [Wallet](/docs/CS/Blockchain/Bitcoin/Wallet.md)
- [Mining](/docs/CS/Blockchain/Bitcoin/Mining.md)
- [Lightning Network](/docs/CS/Blockchain/Bitcoin/Lightning.md)
- [Architecture](/docs/CS/Blockchain/Architecture.md)
- [Blockchain](/docs/CS/Blockchain/Blockchain.md)

## References

1. [Bitcoin Developer Guide: Transactions](https://developer.bitcoin.org/devguide/transactions.html)
2. [BIP141: Segregated Witness](https://github.com/bitcoin/bips/blob/master/bip-0141.mediawiki)
3. [BIP340: Schnorr Signatures](https://github.com/bitcoin/bips/blob/master/bip-0340.mediawiki)
4. [BIP341: Taproot](https://github.com/bitcoin/bips/blob/master/bip-0341.mediawiki)
5. [BIP125: Opt-in Full Replace-by-Fee](https://github.com/bitcoin/bips/blob/master/bip-0125.mediawiki)
