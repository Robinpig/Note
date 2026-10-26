## Introduction

闪电网络（Lightning Network）是比特币的 Layer 2 支付协议：把资金锁进**双向支付通道**，双方在链下不断更新余额，只在开通道与关通道时上链。它把"每笔支付都要全网广播、等区块确认"的模式，换成"链下即时清算、链上只做最终结算"。

目标不是替代主链，而是**把主链的有限区块空间用于结算，把高频小额支付移到链下**。代价是流动性管理、在线要求与新的攻击面。一般 Layer 2 原理见 [Layer 2](/docs/CS/Blockchain/Layer2.md)。

## Payment Channels

一条通道的生命周期：

1. **开通道**：双方共同构造一笔 funding 交易，把 BTC 锁进一个 2-of-2 多签输出，上链确认；
2. **链下更新**：双方签署新的"承诺交易（commitment transaction）"，重新分配通道内余额。旧状态被撤销，但不上链；
3. **支付**：A 向 B 支付，本质是双方同意把余额向 B 倾斜，并签名新的承诺交易；
4. **关通道**：任一方广播最新承诺交易，等待 CSV 时间锁后取回余额；或双方协作关闭，立即结算。

关键机制：

- **撤销（revocation）**：每次更新时，旧承诺交易的撤销密钥被交给对方。若一方广播旧状态，对方可以用撤销密钥构造**惩罚交易**，拿走其全部余额；
- **HTLC（哈希时间锁合约）**：跨通道支付的条件支付。收款方揭示原像即可取款，否则超时退款；
- **CLTV / CSV**：HTLC 的绝对超时与承诺交易的相对时间锁，保证"先结算下游、再结算上游"的顺序；
- **瞭望塔（watchtower）**：代替离线用户监控链上，发现旧状态广播时及时提交惩罚交易。

通道内的"余额"不是链上账户，而是双方对最新承诺交易的共识。任何一方消失，另一方仍可广播最新状态取回资金——只要还保留着数据。

## Routing

单条通道容量有限，支付需要沿多跳路径转发：

- **源路由**：付款方构造完整路径，用 Sphinx 洋葱包逐跳加密，中间节点只知道上一跳与下一跳；
- **gossip**：公开通道的容量、费率、时间锁参数通过 gossip 传播，节点维护通道图并计算路由；
- **转发费**：每跳收取 `base_fee + amount * fee_rate`，通常以 ppm 计；
- **失败处理**：路径某跳余额不足或节点离线，返回错误并尝试替代路径；
- **多路径支付（MPP）**：把一笔支付拆成多份沿不同路径发送，提高成功率；
- **原子性**：所有分片要么全部成功，要么全部失败，依赖 HTLC 的哈希锁与超时链。

路由的核心约束是**流动性分布**：通道容量不等于可转发金额，资金必须恰好在正确的一侧。这使得"收付款"并不对称：收款需要入站流动性，付款需要出站流动性。

## Invoices and Protocols

- **BOLT11**：传统发票，包含金额、支付哈希、过期时间、路由提示，一次性使用；
- **BOLT12 Offers**：可复用报价，支持定期订阅、 blinded paths（隐藏收款节点身份）、更小的二维码；
- **LNURL**：基于 HTTP 的交互协议，支持闪电地址、登录认证、提现等；
- **Keysend**：无需发票的直接支付，用 TLV 附带自定义数据；
- **BOLT 规范族**：BOLT1–BOLT12 分别定义基础协议、通道、点对点、洋葱路由、发票、应用层等。

BOLT12 与 blinded paths 解决了 BOLT11 的两个痛点：发票不可复用、收款节点身份暴露。它们也是"闪电网络能否支持订阅式支付"的关键。

## Channel Upgrades

- **Anchor outputs**：承诺交易预留小额输出，允许在关通道时用 CPFP 追加手续费，解决预置费率不准导致通道卡死的问题；
- **Simple Taproot Channels**：用 Taproot 与 MuSig2 让合作关闭看起来像普通支付，降低费用并提升隐私；
- **Dual Funding**：双方都可出资，开通道不再由单方承担；
- **Splicing**：在不关通道的情况下增减资金，避免流动性碎片化；
- **Liquidity Ads**：节点公开出售入站流动性，形成流动性市场；
- **Trampoline Routing**：把长路径拆成若干段，由中继节点代算路由，降低轻客户端负担；
- **Async Payments**：为离线收款方缓存支付，改善移动端体验。

这些升级大多需要双方（甚至全网）支持，部署是渐进且碎片化的——这是闪电网络"协议正确但体验难做"的根源之一。

## Liquidity Management

闪电网络最现实的工程问题是流动性：

- **入站流动性**：别人能付给你的额度，新节点默认没有，需要购买、swap 或让别人向自己开通道；
- **出站流动性**：你能付出去的额度，由通道本地余额决定；
- **再平衡**：通过循环支付、 submarine swap（链上/链下互换）、splicing 调整两侧余额；
- **通道储备**：协议要求每方保留约 1% 的余额，防止一方把通道花空后无法支付关闭费用；
- **最小通道容量**：过小的通道不经济，路由费无法覆盖链上开闭成本。

对商户而言，收款通道会逐渐"耗尽"入站流动性，需要持续的流动性运营。这也是托管型闪电钱包（牺牲自托管换取体验）流行的原因。

## Risks and Limits

- **在线要求**：收款方需在线或委托瞭望塔，否则可能错过 HTLC 结算或被广播旧状态；
- **资本锁定**：通道内资金无法同时用于其他用途，机会成本高；
- **通道卡死**：费率估算错误或对手方不合作时，强制关闭可能耗时数天；
- **通道拥堵攻击（jamming）**：攻击者用大量小额 HTLC 占满通道流动性，成本极低，是未完全解决的 DoS 问题；
- **隐私**：洋葱路由保护路径，但通道容量与时间模式仍可被分析；blinded paths 改善收款隐私；
- **托管风险**：托管钱包用户并不真正持有通道，平台跑路即损失；
- **备份**：静态通道备份（SCB）可在节点丢失后恢复资金，但无法恢复通道历史与未结算支付。

## Ecosystem

- **实现**：LND（Go）、Core Lightning（C）、Eclair（Scala）、LDK（Rust 库）；
- **钱包**：Phoenix、Breez、Zeus、Strike 等，自托管与托管模式并存；
- **基础设施**：流动性服务商、瞭望塔、通道市场、LSP（Lightning Service Provider）规范；
- **应用**：小额支付、打赏、流媒体按秒计费、跨境汇款、交易所充提。

闪电网络证明了"链下状态通道"在支付场景可行，但它不是通用计算方案。需要通用合约时，Rollup 是更合适的方向，见 [Layer 2](/docs/CS/Blockchain/Layer2.md)。

## Links

- [Bitcoin](/docs/CS/Blockchain/Bitcoin.md)
- [Transaction](/docs/CS/Blockchain/Bitcoin/Transaction.md)
- [Wallet](/docs/CS/Blockchain/Bitcoin/Wallet.md)
- [Layer 2](/docs/CS/Blockchain/Layer2.md)
- [Security](/docs/CS/Blockchain/Security.md)
- [Blockchain](/docs/CS/Blockchain/Blockchain.md)

## References

1. [The Bitcoin Lightning Network: Scalable Off-Chain Instant Payments](https://lightning.network/lightning-network-paper.pdf)
2. [Lightning Network Specifications (BOLTs)](https://github.com/lightning/bolts)
3. [BOLT12: Offers](https://github.com/lightning/bolts/blob/master/12-offer-encoding.md)
4. [Mastering the Lightning Network](https://github.com/lnbook/lnbook)
