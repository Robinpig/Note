## Introduction

比特币没有服务器，所有节点通过一套无许可的 P2P 协议互相发现、交换交易与区块。网络层决定了三件事：**新交易多久传遍全网、区块多快到达矿工、节点如何在不信任对端的前提下完成同步**。它也决定了隐私与抗审查能力——一个被日蚀攻击隔离的节点，看到的"全网"其实是攻击者伪造的。

这一页讲比特币 P2P 的协议消息、区块传播优化、初始同步、内存池策略、轻客户端与网络隐私。

## Node Roles

| 角色 | 保存数据 | 作用 |
| --- | --- | --- |
| 全节点 | 全部区块 + 当前 UTXO | 独立验证全部规则，是信任的最小单位 |
| 剪枝全节点 | 近期区块 + UTXO | 验证能力相同，不保留完整历史 |
| 归档节点 | 全部区块 + 全部历史状态 | 区块浏览器、分析、历史查询 |
| SPV 轻节点 | 区块头 | 用 Merkle 证明验证交易，信任最长链 |
| 矿工节点 | 全节点 + 挖矿逻辑 | 构造区块模板并搜索 PoW |

全节点是比特币安全模型的基石：**只有自己验证过的链才值得信任**。钱包连接第三方 RPC 时，实际上信任了对方对链状态的陈述——这是大多数用户的安全短板。

## Wire Protocol

节点间通过明文或加密（BIP324 v2 transport）TCP 连接交换消息，核心流程：

- **握手**：`version` / `verack`，交换协议版本、服务位、高度、时间；
- **发现**：`addr` / `addrv2`（BIP155，支持 Tor/I2P 地址），节点维护 addrman 地址管理器；
- **公告**：`inv`（我有这些 tx/block 的哈希）、`getdata`（请求内容）、`notfound`；
- **区块**：`getheaders` / `headers`（先同步头链）、`getblocks`、`block`；
- **交易**：`tx`、`mempool`（请求内存池）、`feefilter`（告知最低费率，减少无效公告）；
- **其他**：`ping`/`pong` 保活与延迟测量，`sendheaders` 偏好头公告，`wtxidrelay` 支持见证交易中继。

节点默认维持约 8 个出站全中继连接、若干区块专用连接（block-relay-only，不公告交易，降低日蚀风险），以及少量 feeler 连接探测地址可达性。

## Block Propagation

区块传播速度直接影响孤块率与手续费收入。优化手段：

- **紧凑区块（BIP152）**：发送区块头 + 短交易 ID，接收方用本地 mempool 重建区块，缺失部分再请求。高带宽模式下几乎零延迟；
- **headers-first 同步**：先同步区块头链，再并行下载区块体，防止被无效链拖慢；
- **FIBRE / 专用中继**：矿池间的低延迟中继网络，减少孤块；
- **Erlay（BIP330）**：用集合调和替代逐条 `inv` 公告，大幅降低节点间的交易公告带宽，提案仍在推进中。

孤块（orphan/stale block）指被发现但未进入主链的块。孤块率越高，矿工越倾向加入大矿池或使用专用中继，进一步加剧中心化。

## Initial Block Download

新节点首次同步（IBD）需要下载数百 GB 数据：

- **headers-first**：先验证头链的工作量与难度调整，再下载区块体；
- **assumevalid**：默认跳过对历史区块签名的验证（仅信任硬编码的区块哈希），大幅缩短同步时间，但降低了对远古历史的验证强度；
- **assumeutxo**：下载 UTXO 集快照，先可用后验证，适合快速启动；
- **检查点**：硬编码在客户端中，用于防止极深分叉与加速同步，但**不改变共识规则**；
- **剪枝模式**：同步完成后删除旧区块体，只保留 UTXO 与近期区块，磁盘占用可降到数 GB。

同步是一场"验证 vs 时间"的权衡。对绝大多数用户而言，同步一个全节点仍是验证链状态最可靠的方式。

## Mempool Policy

内存池不是共识的一部分，而是**节点对"哪些未确认交易值得中继"的本地策略**。策略差异会导致交易传播不一致，因此 Bitcoin Core 的策略事实上成为行业标准：

- **最低中继费率**：默认 1 sat/vB，低于此费率的交易不会被转发；
- **内存池容量**：默认约 300 MB，满时按费率淘汰；
- **过期时间**：默认 336 小时（约两周）；
- **祖先/后代限制**：防止超长交易链占用内存；
- **RBF 策略**：BIP125 替换需支付更高绝对费用与增量费用；
- **包中继与 TRUC/v3**：让父子包整体进入 mempool，支持可靠的费用追加；
- **粉尘规则**：拒绝经济上不合理的微小输出。

**共识规则决定"什么算有效"，策略决定"什么会被转发"**。矿工可以不打包符合共识但不合策略的交易；用户也可以直接提交给矿工。混淆两者是常见的误解来源。

## Light Clients

SPV 钱包不下载区块体，只验证区块头与 Merkle 证明：

- **BIP37 布隆过滤器**：钱包向对端发送过滤器，请求匹配的交易；隐私差（过滤器泄露地址）、已被多数节点默认关闭；
- **BIP157/158 紧凑区块过滤器**：节点为每个区块生成过滤器，钱包下载过滤器后自行匹配，再请求区块。隐私更好，是 Neutrino 等轻客户端的基础；
- **同步委员会**：以太坊轻客户端用委员会签名跟踪链头，比特币没有等价机制。

SPV 的安全假设是"最长链背后有足够算力"，它无法验证共识规则的全部细节（如通胀、签名规则），因此适合小额钱包，不适合交易所与桥。

## Network Privacy

比特币的隐私泄漏主要发生在网络层与链上分析的交界处：

- **地址复用**：同一地址多次收款会把交易关联起来；
- **找零识别**：启发式规则（找零地址类型、金额、序列号）可推断资金流向；
- **共同输入假设**：一笔交易的所有输入通常属于同一钱包；
- **IP 关联**：节点广播交易时暴露源 IP，可通过监听节点把交易与 IP 关联；
- **日蚀攻击**：攻击者占满目标节点的连接槽，使其只看到攻击者伪造的视图，可用于双花或拒绝服务；
- **BGP 劫持**：路由层劫持可把矿池流量导向攻击者，历史上多次发生。

缓解手段：Tor/I2P、Dandelion++（提案，未被 Core 采用）、**PayJoin（BIP78）** 打破共同输入假设、**Silent Payments（BIP352）** 用一次性地址接收且无需交互、以及使用自己的全节点广播交易。

## Links

- [Bitcoin](/docs/CS/Blockchain/Bitcoin.md)
- [Mining](/docs/CS/Blockchain/Bitcoin/Mining.md)
- [Transaction](/docs/CS/Blockchain/Bitcoin/Transaction.md)
- [Wallet](/docs/CS/Blockchain/Bitcoin/Wallet.md)
- [Architecture](/docs/CS/Blockchain/Architecture.md)
- [Security](/docs/CS/Blockchain/Security.md)

## References

1. [Bitcoin Developer Guide: P2P Network](https://developer.bitcoin.org/devguide/p2p_network.html)
2. [BIP152: Compact Block Relay](https://github.com/bitcoin/bips/blob/master/bip-0152.mediawiki)
3. [BIP157: Client Side Block Filtering](https://github.com/bitcoin/bips/blob/master/bip-0157.mediawiki)
4. [BIP324: Version 2 P2P Encrypted Transport](https://github.com/bitcoin/bips/blob/master/bip-0324.mediawiki)
5. [Eclipse Attacks on Bitcoin's Peer-to-Peer Network](https://www.usenix.org/conference/usenixsecurity15/technical-sessions/presentation/heilman)
