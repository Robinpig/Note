## Introduction

dPoW（Delayed Proof of Work，延迟工作量证明）是 Komodo 项目设计的一种**安全机制**，本质上是 PoW 共识算法的修改版：它借用比特币（及其后莱特币）区块链的算力（hashpower）来为自身及其它接入链增强安全性。严格来说，dPoW 不算一种独立的出块共识，而是一层"安全即服务"（Blockchain Security Service）——让新建链无需自建庞大算力，也能获得等价于安全链的抗 51% 攻击能力。

## Core Idea: Reusing the Computing Power of the Security Chain

新建的 PoW 链往往因算力（hashrate）太小而易受 51% 攻击：矿工倾向于把机器投向已 established 的大链以保收益，小链的 P2P 网络根本不足以抵御攻击者。dPoW 的思路是"不自己堆算力，而是回收（recycle）安全链的庞大算力"——通过**公证（notarization）**把受保护链的区块哈希备份到一条更强壮的链（Bitcoin / Litecoin）账本上。一旦备份完成，要回滚受保护链的历史，就必须先攻破那条更强壮的链，而后者算力高到不可行。

## Notarization Process

由 Komodo 社区选举产生的**公证员节点（Notary Nodes）**网络执行（规模约 64 个，每年部分席位由社区以 stake-weighted 方式选举产生），大约每 10 分钟一轮，借助 `OP_RETURN` 交易（一种只往账本写入少量数据、不转移资金的特殊交易）完成，分三步：

1. **正向公证**：公证员节点把每条 dPoW 受保护链的、约 10 分钟前（确保已被该链网络确认有效）的区块哈希，通过一笔 KMD 链交易写入 **KMD 链**。
2. **跨链公证**：再把 KMD 链的区块哈希通过 `OP_RETURN` 写入 **LTC 链（早期为 BTC）**。由于第一步已把各受保护链的哈希都汇聚到 KMD 链，这一步单一公证即可把安全性延伸到 Komodo 及所有使用 dPoW 的链。
3. **回公证（back-notarization）**：把公证结果写回各受保护链，告知"哪个区块已被公证"。此后网络拒绝接受对任何已公证区块及其之前区块的重组（reorganization）。

> 公证完成后，dPoW 受保护链的历史即变为**完全不可变**；相当于每次公证都"重置"了最长链规则的起点——网络不会再接受从被公证区块更早位置分叉的最长链，哪怕它确实最长。

## Safety Analysis

- 攻击者若要篡改或破坏某条 dPoW 受保护链的历史，必须**同时攻破 Litecoin 网络与 Komodo 网络**（早期为 Bitcoin + Komodo），才能抹除被公证的区块哈希。单条小链的算力根本不足以对抗。
- 因此 dPoW 把"小链的安全"等价于"安全链的安全"，以极低成本为接入链提供极高安全水位，黑客需要先压倒两条大链才能动摇任意一条小链。

## Comparison of dPoW and PoW

| 维度 | PoW | dPoW |
| --- | --- | --- |
| 安全来源 | 自身算力（hashrate） | 复用 Bitcoin / Litecoin 的算力 |
| 小链安全性 | 算力小则脆弱，易遭 51% 攻击 | 借大链算力，小链也获高安全 |
| 51% 攻击成本 | 取决于自身算力 | 需攻破两条链，成本极高 |
| 出块方式 | 自身挖矿竞争 | 自身挖矿 + 周期公证 |
| 定位 | 出块共识算法 | 叠加于 PoW/PoS 的安全服务 |

## Shortcomings / Limitations

- 只有采用 PoW 或 PoS 的区块链，才能叠加这种安全算法——dPoW 依赖一条已有安全链作为公证目标，无法凭空为链提供算力。
- 在"公证员激活（Notaries Active）"模式下，必须校准不同节点（公证员节点或正常节点）之间的哈希率，否则哈希率间的差异会被放大、引发失衡。

## Mainstream Implementations

dPoW 由 Komodo 提出，并作为 Blockchain Security Service 对外开放，任何基于 **UTXO 模型**的独立区块链都可接入。已接入的项目包括 Komodo（KMD）自身、SmartFi、Pirate Chain、Gleec、Einsteinium 等数十个。

## Links

- [Proof of Work](/docs/CS/Distributed/Consensus/PoW.md) — dPoW 借其算力增强安全
- [Proof of Stake](/docs/CS/Distributed/Consensus/PoS.md) — 另一类无许可共识
- [Consensus](/docs/CS/Distributed/Consensus/Consensus.md) — 共识算法总入口（含 blockchain 段）
- [Byzantine Generals](/docs/CS/Distributed/Byzantine.md) — 区块链要解决的拜占庭问题

## References

1. [51% Attack Security: Delayed Proof of Work (dPoW)](https://komodoplatform.com/delayed-proof-of-work/)
2. [Komodo's Holds Second Annual Notary Node Election](https://blog.komodoplatform.com/en/second-annual-notary-node-election/)
3. [Delayed Proof of Work Explained | Binance Academy](https://academy.binance.com/da-DK/articles/delayed-proof-of-work-explained)
