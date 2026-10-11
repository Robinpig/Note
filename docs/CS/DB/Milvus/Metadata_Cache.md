## Introduction

一次请求进入 Proxy 的查询或写入队列之前，至少要回答四个彼此独立的问题：这个 collection 的 schema 长什么样、目标 partition 的 id 是多少、每个 VChannel 的 shard leader 在哪台 QueryNode、collection 的 consistency level 与 UpdateTimestamp 是什么。这些事实全部存在 RootCoord 的元数据表里，而 Proxy 是**无状态**的接入层——如果每个请求都去 MixCoord 做一次 `DescribeCollection`，RPC 放大与 RootCoord 压力都不可接受。于是 Proxy 在本地维护两层缓存：元数据缓存 `metacache.MetaCache` 与 shard leader 缓存 `shardclient.Manager`。

缓存一旦存在，分布式系统最经典的难题随之而来：**DDL 之后，怎样让所有 Proxy 立刻看到新事实**。Milvus 的答案不是给条目加版本号让读方比对，也不是让 Proxy 去 watch 元数据存储——而是**显式广播失效**：RootCoord 在元数据落地后，通过一次独立的 RPC fan-out 通知每个在线 Proxy「清掉这个 collection」。缓存条目本身不自带新鲜度判断，新鲜度由「失效必达」这一外部事件保证。

两条缓存线的失效语义并不对称：元数据缓存按 db/name 与 id 精细清理，shard leader 缓存的失效则由 QueryCoord 侧的 leader 变化观察器与 Proxy 自身的错误驱动。它们共用同一个推送通道 `proxyClientManager`。

本篇边界：一致性等待与 tSafe 水位见 [Query Path](/docs/CS/DB/Milvus/Query_Path.md)；DDL 回调框架与 schema 演进见 [Schema and DDL](/docs/CS/DB/Milvus/Schema_and_DDL.md)；DDL 消息在 WAL 上的原子广播见 [WAL and StreamingNode](/docs/CS/DB/Milvus/WAL_and_StreamingNode.md)；跨集群复制时元数据变更如何随 CDC 传递见 [CDC and Replication](/docs/CS/DB/Milvus/CDC_and_Replication.md)。

## What the Proxy Caches

`metacache.MetaCache` 是 3.0 重写过的实现：主存储只有一张以 collection id 为键的表，其余都是可以随时丢弃的提示。

| 缓存对象 | key | 回源 RPC | 失效动作 |
| :--- | :--- | :--- | :--- |
| collection 主条目 CollectionInfo：schema、VChannel/PChannel 列表、consistency level、aliases、properties、NumPartitions | collection id | `DescribeCollection` | 统一 eviction 例程删除 |
| name hint | db + collection 名 | 随主条目 fill 时写入 | 随主条目一起删 |
| alias hint | db + alias | 同上，只写条目自身声明的 aliases | 随主条目一起删，无 id 广播时 `RemoveAliasHolders` 兜底 |
| 分区列表 PartitionInfos | collection id | `ShowPartitions` | 整表丢弃，以 collection 为单位 |
| database 元数据 DatabaseInfo | db 名 | `DescribeDatabase` | `RemoveDatabase` 或 `RemoveDatabaseInfo` |
| shard leaders | collection id | `GetShardLeaders` | `InvalidateShardLeaderCache` |
| ID 批量分配 | 本地指针 idStart/idCount | `AllocID` | 耗尽自动续，无需失效 |

几个关键设计：

- **只有主条目是事实，hints 是提示**。`collections` map 条目的存活即存在；name/alias hint 在每次读时都要对主条目做标量校验，因此陈旧 hint 最坏只是多一次 describe，永远不会读出错误事实——这让 hint 的清理可以全部做到 O(1)。
- **没有 TTL、没有容量上限、没有后台 GC**。正确性完全依赖失效事件，不依赖过期时间。分区的值一旦构建即不可变、按指针分发，失效时直接 delete 即可。
- **miss 由 singleflight 合并**。同一个 key 的并发 miss 只发一次 `DescribeCollection`；以 alias 寻址时按真名落地缓存。fill 保留调用方 context，MetaCache 自身不设更短的 deadline。
- **旧 rootcoord 的 id-only describe 不落缓存**。响应缺少 DBName 时条目无法归属数据库，这类响应只直通返回。
- **ID 分配也走同一缓存**。`AllocID` 一次向 RootCoord 申请 1,000,000 个 id，本地递增发放，耗尽再续——这是缓存里唯一的「批量型」对象。

观测面有 `ProxyCacheStatsCounter`（按 caller 统计 hit/miss）与 `ProxyUpdateCacheLatency`（fill 耗时）。

## Invalidation Broadcast

失效的触发点不在 Proxy，而在 RootCoord 的 DDL ack callback：每条 DDL 消息在 prepare 阶段就把 `CacheExpirations` 放进消息头（`getCacheExpireForCollection` 收集 collection 真名一条，外加每个 alias 各一条），等 WAL 广播完成、元数据落盘之后，`DDLCallback.ExpireCaches` 逐条处理过期项——为每条生成一个 TSO，再经 `ExpireMetaCache` 调 `ProxyClientManager.InvalidateCollectionMetaCache`。

推送通道是**独立 RPC fan-out**，不是让 Proxy 消费 WAL：Proxy 从未消费 WAL 里的 DDL 消息（msgdispatcher 的唯一生产消费者是 QueryNode），失效靠 RootCoord 逐 Proxy 主动调用 `Proxy.InvalidateCollectionMetaCache`。fan-out 以 errgroup 并发发出并等待全部返回；`ErrNodeNotFound`（Proxy 已下线）与 `ErrServiceUnimplemented` 被容忍——下线的 Proxy 本就没有缓存可清——其余错误汇聚后返回给 ack callback。

Proxy 收到请求后按消息类型分派，**按 key 清而不是全量清**：

| 请求携带的 MsgType | Proxy 侧动作 |
| :--- | :--- |
| DropCollection / RenameCollection / CreateAlias / AlterAlias / DropAlias | `InvalidateCollectionMeta` 清主条目与 hints；alias 操作附带清 alias hint，而无目标 id 触发的全库扫描**显式排除 DropAlias**——它本就没有 id，属常态而非异常 |
| LoadCollection / ReleaseCollection | 按 collectionID 清主条目；collection load 到 100% 后 QueryCoord 也会主动发一次此类失效 |
| CreatePartition / DropPartition | `RemovePartition`：丢弃整张分区列表并连带清主条目，因为 NumPartitions 已变；空 partition name 直接拒绝 |
| DropDatabase | `RemoveDatabase` 清全库条目，外加 `shardMgr.RemoveDatabase` |
| AlterDatabase | `RemoveDatabaseInfo`：只清数据库级元数据，不碰 collection 条目 |
| AlterCollection / AlterCollectionField | `InvalidateCollectionMeta` 清主条目与 hints |
| 其它 / 未知类型 | 防御性走 `InvalidateCollectionMeta` |

`InvalidateCollectionMeta` 先把请求里的名字与 id 解析成一组待删 id，再逐个 evict——顺序很重要，因为 evict 会删掉条目的 name/alias hints，而同一请求的另一个目标可能还要靠这些 hints 定位。统一的 eviction 例程 `evictCollectionEntryLocked` 一次删掉主条目与它名下的 name hint、声明过的 alias hint、分区列表；对 DropCollection 一类操作，Proxy 同时还会 `InvalidateShardLeaderCache(collectionID)`。失效路径上原则不发起任何 RPC（分区失效仅用本地 hints 解析 id）；只有 DropDatabase 与**非 DropAlias** 的无 id 广播会付 O(N) 扫描，后者是注释里明确标注的**永久安全网**（兼容旧 rootcoord 与元数据不一致），不是升级期临时代码。

## Why No Version Numbers

v3.0.1 的缓存条目没有版本号，也不做时间戳比较。支撑这个简化的是一条排空不变量：fill 全程持有 `fillMu` 读锁（RPC、写回、结果投递、singleflight 清理），而失效持有 `fillMu` 写锁，因此一次失效必然先排空所有 in-flight fill。配合 RootCoord「先落盘再广播」的顺序，效果是：失效前已在途的 fill 读到旧快照，但它的结果在失效完成前已投递并被清理；失效后发起的 fill 读到的必然是 post-DDL 状态。旧版本里 per-collection 的 version floor 已删除，请求里携带的 TSO 只是 MsgBase 时间戳，不参与比较。缓存 hit 完全不碰 `fillMu`，fill 之间也互不阻塞。

## Life of One AlterCollection

以 `AlterCollection` 为例，把整条缓存旅程按时间串一遍：

1. Proxy 的 DDL 任务经 `ddQueue` 串行进入 RootCoord；prepare 阶段生成 DDL 消息，消息头里放好 `CacheExpirations`——collection 真名一条（MsgType_AlterCollection），每个 alias 各一条（MsgType_AlterAlias）。
2. 消息经 WAL 广播框架持久化并等待流转完成（原子性语义见 [WAL and StreamingNode](/docs/CS/DB/Milvus/WAL_and_StreamingNode.md)）。
3. ack callback `alterCollectionV2AckCallback` 依次：`meta.AlterCollection` 把新元数据落盘 → 刷新 DataCoord 的缓存 schema（先于索引元数据可见，避免对没有新字段 binlog 的段调度构建）→ 索引联动 → 若改名或跨库则刷新各 Proxy 的 RBAC policy cache。
4. 最后 `ExpireCaches`：解析过期项、生成 TSO，构造 `InvalidateCollMetaCacheRequest`（携带 db、真名或 alias、collectionID、TSO、MsgType）。
5. RPC fan-out：并发通知全部在线 Proxy；`Proxy.InvalidateCollectionMetaCache` 走上面的 switch——本例是 `InvalidateCollectionMeta` 加 shard leader 缓存失效。
6. Proxy 侧持 `fillMu` 写锁排空在途 fill，evict 主条目、hints 与分区列表。此后任何命中该 collection 的请求都是 miss。
7. 下一次请求 miss，singleflight 触发 `DescribeCollection` 拿到 post-DDL 的 schema（含新字段、新 alias 列表），连同新写的 name hint 与 alias hint 一起落缓存。

## Shard Leader Cache

`shardclient.Manager` 缓存每个 collection 的「VChannel → leader 节点列表」（NodeInfo：nodeID/addr/serviceable），key 只用 collection id——源码注释记录了 issue #51533 的教训：不能用 name/alias 做 key，否则 alias 重指或跨库改名后可能把 A 的 leader 列表端给 B。刷新时向 MixCoord 调 `GetShardLeaders` 并带 `WithUnserviceableShards: true`，把尚未 serviceable 的 leader 也拿回来，由 Proxy 自行处置。

它的失效有三条路径：

- **QueryCoord 主动推送**。distHandler 每次从 QueryNode 拉取 leader view，发现 channel 换主就调 notifyFunc，即 `LeaderCacheObserver.RegisterEvent`；observer 在后台按批合并事件后向全部 Proxy 发 `InvalidateShardLeaderCache`。这是 balance 与故障转移后的收敛机制。
- **load/release 生命周期**。load、load config 变更（replica 数与资源组）、release 等 job 完成后，QueryCoord 直接发 `InvalidateShardLeaderCache` 或 `InvalidateCollectionMetaCache`。
- **Proxy 自我修复**。search / query / statistic 三个任务在收到 `NotShardLeader` 或 QueryNode RPC 错误时，都会 `InvalidateShardLeaderCache(collectionID)` 并重试——leader 迁移期间用户实际感受到的收敛靠的就是这条错误路径（与 [Query Path](/docs/CS/DB/Milvus/Query_Path.md) 里 leader 选择那半段接上）。

缓存只回答「谁是合法 leader」，负载均衡另有策略——由 LBPolicy 的 `selectNode` 在候选列表上选点；`GetReader` 与 `Shuffle` 这类打散接口在 v3.0.1 已无生产调用点，仅存于测试引用。`PurgeClient` 周期回收的是闲置到 60 分钟的 QueryNode 连接，与缓存无关；`RemoveDatabase` 在这个缓存上是 no-op，因为 DropDatabase 要求先清空数据库，逐 collection 的失效已经覆盖。

## Staleness Cost and Fallbacks

可以接受短暂陈旧，是因为 schema 与分区结构的变化是低频管理操作，而热路径只需要「把名字解析成 id、拿到 schema」，数据层面的一致性由 UpdateTimestamp / guaranteeTs 的可见性等待兜底（机制在 Query Path 篇）。反过来，确实不吃缓存的路径有两条：面向用户的 `DescribeCollection` / `DescribeDatabase` 直接调 MixCoord 拿最新事实；`GetShardLeaders` 支持 `withCache=false` 强制刷新。

失效失败或丢失的兜底分层：① 推送侧对下线 Proxy 容忍，其余错误上抛给 ack callback，让失效失败暴露在 DDL 路径上；② reader 侧的 hint 校验保证陈旧 hint 最多多一次 describe，不会读串目标；③ shard leader 侧由 `NotShardLeader` 错误驱动自愈，配合 QueryCoord 的观察器滚动修正。需要说明的是，v3.0.1 源码中未见对 `MetaCache` 的周期性全量校验或补偿扫描——如果一次 DDL 广播在所有重试窗口内都失败，该 Proxy 在下一个触及此 collection 的 DDL 广播到来之前会持续读到旧 schema。这条风险由 DDL 层的错误上报来暴露，而不是由缓存自身消化。

## Links

- [Milvus](/docs/CS/DB/Milvus/Milvus.md)
- [Query Path](/docs/CS/DB/Milvus/Query_Path.md)
- [Schema and DDL](/docs/CS/DB/Milvus/Schema_and_DDL.md)
- [WAL and StreamingNode](/docs/CS/DB/Milvus/WAL_and_StreamingNode.md)
- [Write Path](/docs/CS/DB/Milvus/Write_Path.md)
- [Distributed](/docs/CS/Distributed/Distributed.md)

## References

- [milvus-io/milvus v3.0.1 proxy metacache](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/proxy/metacache/meta_cache.go)
- [milvus-io/milvus v3.0.1 proxy invalidation handlers](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/proxy/impl.go)
- [milvus-io/milvus v3.0.1 proxy client manager](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/util/proxyutil/proxy_client_manager.go)
- [milvus-io/milvus v3.0.1 rootcoord expire cache](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/rootcoord/expire_cache.go)
- [milvus-io/milvus v3.0.1 rootcoord DDL callbacks](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/rootcoord/ddl_callbacks.go)
- [milvus-io/milvus v3.0.1 shard client manager](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/proxy/shardclient/manager.go)
- [milvus-io/milvus v3.0.1 leader cache observer](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/querycoordv2/observers/leader_cache_observer.go)
