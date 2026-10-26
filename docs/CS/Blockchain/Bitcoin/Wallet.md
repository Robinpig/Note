## Introduction

比特币的所有权完全由**私钥**定义：谁能对一笔 UTXO 提供有效签名，谁就能花掉它。钱包不是"存币的地方"，而是**密钥管理器 + 交易构造器**——币始终在链上，钱包只负责派生地址、组装交易、签名与广播。

这一页讲密钥与地址的编码、分层确定性钱包、多签与描述符、签名与自托管实践。理解这些，才能理解"交易所里的 BTC"和"自己钱包里的 BTC"根本不是一回事。

## Keys and Addresses

- **曲线**：secp256k1，私钥是 256 位整数，公钥是曲线上的点；
- **压缩公钥**：33 字节（前缀 + x 坐标），现代钱包默认；
- **地址**：不是公钥本身，而是公钥或脚本的哈希编码，隐藏公钥并缩短长度。

常见地址类型：

| 类型 | 编码 | 前缀 | 锁定脚本 |
| --- | --- | --- | --- |
| P2PKH | Base58Check | `1...` | `HASH160(pubkey)` |
| P2SH | Base58Check | `3...` | `HASH160(script)` |
| P2WPKH | bech32 | `bc1q...` | `0 <HASH160(pubkey)>` |
| P2WSH | bech32 | `bc1q...` | `0 <SHA256(script)>` |
| P2TR | bech32m | `bc1p...` | `1 <tweaked x-only pubkey>` |

**WIF**（Wallet Import Format）是私钥的 Base58 编码，便于导入导出；现代钱包更常用助记词或描述符，而不是 WIF。

地址只负责"收"，不负责"找回"。把地址给出去是安全的，把私钥/助记词给出去等于把资产给出去。

## HD Wallets

分层确定性钱包（HD Wallet）用一个种子派生无限多密钥，避免"每收一笔就备份一次"：

- **BIP39**：把 128–256 位熵编码成 12–24 个助记词，并附带校验和；助记词本质是种子的人类可读表示；
- **BIP32**：从种子派生主密钥，再按路径派生子密钥。路径形如 `m / purpose' / coin_type' / account' / change / index`，带 `'` 的是硬化派生（不能由父公钥推出子公钥）；
- **常用路径**：BIP44 `m/44'/0'/0'`（P2PKH）、BIP49 `m/49'/0'/0'`（P2SH-P2WPKH）、BIP84 `m/84'/0'/0'`（P2WPKH）、BIP86 `m/86'/0'/0'`（P2TR）；
- **xpub / xprv**：扩展公钥可派生出所有子地址，适合 watch-only 钱包；但它也会暴露整条分支的隐私，不能随意分享；
- **备份**：种子 + 派生路径 + 地址类型共同决定资产归属。**只备份助记词、不记录路径与脚本类型，可能找不回资产**。

现代钱包更推荐用**输出脚本描述符（Output Script Descriptor）** 完整描述"如何派生与锁定"，它比"助记词 + 路径约定"更无歧义，也是 Bitcoin Core 导入钱包的标准方式。

## Multisig and Script Policies

多签把控制权拆分到多把钥匙：

- **`m-of-n`**：如 2-of-3，任意 2 把钥匙即可花费，单把钥匙丢失或被盗都不致命；
- **地址形式**：传统 P2SH 多签、P2WSH 多签、Taproot 多签（MuSig2 聚合为单签名，链上更省费且不暴露阈值）；
- **Miniscript**：在比特币脚本之上提供可组合、可分析、可验证的策略语言，把"2-of-3 且 6 个月后可恢复"这类策略表达成标准描述符；
- **PSBT（BIP174）**：部分签名交易格式，让离线签名、硬件钱包、多方协作签名有统一的交换格式。

多签是机构和高级用户的事实标准：它把"单点故障"从密钥转移到了流程设计——流程设计错（如所有钥匙放在同一地点）等于没有多签。

## Signing

- **ECDSA**：签名覆盖 `SIGHASH` 指定的交易部分；`k` 必须随机且不可预测，RFC6979 用确定性方式生成以避免随机数复用导致私钥泄露；
- **Schnorr**：BIP340 使用辅助随机数增强侧信道防护，签名固定 64 字节，支持密钥聚合；
- **签名请求**：硬件钱包应显示收款地址、金额、手续费；盲签（不显示内容）是重大风险；
- **离线签名**：PSBT 在联网机与离线机之间传递，私钥永不接触网络。

签名是不可撤销的授权。钓鱼攻击通常不是"破解私钥"，而是诱导用户签一笔自己看不懂的交易，或把资产授权给恶意合约。

## Custody Models

| 模式 | 私钥位置 | 风险 |
| --- | --- | --- |
| 交易所/托管 | 平台 | 平台跑路、被盗、冻结 |
| 热钱包 | 联网设备 | 恶意软件、钓鱼、设备丢失 |
| 硬件钱包 | 专用设备 | 供应链篡改、固件漏洞、种子泄露 |
| 多签金库 | 多地点/多主体 | 流程错误、共谋、继承困难 |
| 纸钱包/脑钱包 | 离线 | 易丢失、易被猜测，已不推荐 |

自托管的要点不是"买一个硬件钱包"，而是完整的**威胁模型与恢复计划**：

- 种子离线备份，多地存放，防止火灾/水灾/被盗同时发生；
- 助记词不要拍照、不要存云盘、不要输入任何网站；
- 使用 passphrase（BIP39 可选口令）时，必须同时备份口令，否则种子也救不回；
- 提前设计继承方案：家人需要知道资产存在、如何恢复，但不能提前拿到钥匙；
- 定期演练恢复流程——没演练过的备份等于没有备份。

## Privacy Practices

- **每次收款用新地址**：HD 钱包自动派生，避免地址复用；
- **Coin control**：手动选择 UTXO，避免把不同来源的币混在一笔交易里；
- **PayJoin**：收款方也提供输入，打破"共同输入 = 同一人"的启发式；
- **Silent Payments**：扫描链上支付，用一次性地址接收，无需交互且不暴露关联；
- **避免 KYC 关联**：交易所提币地址与链上活动关联会削弱隐私，但这涉及合规取舍；
- **地址投毒**：攻击者发送 0 金额交易，伪造相似地址出现在交易历史中，诱导用户复制错误地址。转账前务必核对完整地址。

## Operational Risks

- **固件与供应链**：只从官方渠道购买硬件钱包，验证固件签名，警惕预置种子/改装设备；
- **多签的恢复演练**：至少一次完整的"丢失一把钥匙后恢复"演练；
- **闪电网络备份**：通道状态备份（SCB）能在节点丢失后恢复资金，但无法恢复历史；详见 [Lightning Network](/docs/CS/Blockchain/Bitcoin/Lightning.md)；
- **量子威胁**：secp256k1 的离散对数在足够大的量子计算机面前可被 Shor 算法破解。已暴露公钥的地址（复用地址、Taproot 密钥路径）风险更高，未花费的 P2PKH 输出相对安全。迁移方案仍在讨论，属于长期风险而非近期危机。

## Links

- [Bitcoin](/docs/CS/Blockchain/Bitcoin.md)
- [Transaction](/docs/CS/Blockchain/Bitcoin/Transaction.md)
- [Lightning Network](/docs/CS/Blockchain/Bitcoin/Lightning.md)
- [Security](/docs/CS/Blockchain/Security.md)
- [Blockchain](/docs/CS/Blockchain/Blockchain.md)
- [Architecture](/docs/CS/Blockchain/Architecture.md)

## References

1. [BIP32: Hierarchical Deterministic Wallets](https://github.com/bitcoin/bips/blob/master/bip-0032.mediawiki)
2. [BIP39: Mnemonic Code for Generating Deterministic Keys](https://github.com/bitcoin/bips/blob/master/bip-0039.mediawiki)
3. [BIP174: Partially Signed Bitcoin Transaction Format](https://github.com/bitcoin/bips/blob/master/bip-0174.mediawiki)
4. [BIP352: Silent Payments](https://github.com/bitcoin/bips/blob/master/bip-0352.mediawiki)
5. [Mastering Bitcoin: Keys and Addresses](https://github.com/bitcoinbook/bitcoinbook)
