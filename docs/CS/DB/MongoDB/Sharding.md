## Introduction

分片是 MongoDB 的水平扩展手段：把集合按 **shard key** 切成 chunk，分布到多个 shard 副本集上，由 `mongos` 负责路由与归并。它解决的是单机放不下的数据量或写入吞吐，代价是运维复杂度、跨分片查询以及"shard key 选错后长期还债"。

## Cluster Components

```text
client → mongos × N
              ├── config server replica set（元数据）
              ├── shard A（replica set）
              ├── shard B（replica set）
              └── shard C（replica set）
```

- **shard**：存数据，每个 shard 必须是副本集。
- **mongos**：无状态路由，缓存路由表；不存业务数据，结果归并与排序在它这层完成。
- **config server**：存 `config` 库（shards、chunks、collections、databases、settings），必须部署为 CSRS。
- 8.0 起可以部署 **config shard**：config server 同时承担 shard 角色，省去一组独立节点；可用 `transitionFromDedicatedConfigServer` / `transitionToDedicatedConfigServer` 切换。

客户端必须连 `mongos`。8.0 起直连 shard 只能执行白名单命令，8.3 起 DDL 与 `applyOps` 只允许走 `mongos`。

## Shard Key

shard key 是文档中的一个或一组字段，决定文档落在哪个 chunk。选型看三个维度：

| 维度 | 含义 | 反例 |
| :--- | :--- | :--- |
| 基数（Cardinality） | 不同取值的数量 | 布尔字段、状态枚举 |
| 频率（Frequency） | 单个取值出现的比例 | 99% 文档同城，形成热点 |
| 单调性（Monotonicity） | 是否随时间单调递增 | ObjectId、自增 ID、时间戳 |

单调递增的键（如 `_id`）在**范围分片**下会把新写入集中到最后一个 chunk，形成写热点；**哈希分片**打散写入，但范围查询会退化为广播。

选型建议：

- 写入密集且无明显范围查询 → 哈希分片，或"低基数前缀 + 高基数后缀"的复合键；
- 有明显时间范围查询 → 范围分片，键里带时间但前置高基数维度；
- 查询必须带 shard key 或复合 shard key 前缀，才能定向路由；
- 分片键一旦选定，代价很高：4.2 起可更新文档的 shard key 值，5.0 起可 `reshardCollection` 换键，8.0 起可 `unshardCollection` 退回不分片。

```javascript
// 哈希分片：写均匀，范围查询会广播
sh.shardCollection("app.events", { uid: "hashed" })

// 范围分片：支持范围查询，注意热点
sh.shardCollection("app.orders", { tenantId: 1, createdAt: 1 })
```

对已有数据的集合分片，必须先有以 shard key 为前缀的索引；对空集合分片，MongoDB 会自动建索引。

## Chunks and Balancer

- chunk 默认 **128MB**，按 shard key 的区间划分（哈希分片按哈希值区间）。
- 当 chunk 超过阈值会拆分（split）；拆分只改元数据，不搬数据。
- **balancer** 在后台把 chunk 从多的 shard 迁到少的 shard；迁移过程是"复制 + 追增量 + 切换元数据 + 删除源数据"。
- 迁移会占用源/目标 shard 的 IO 与网络，建议设置 balancer 窗口避开高峰。
- 7.0 起 **AutoMerger** 默认开启，自动合并满足条件的相邻 chunk，减少元数据膨胀。
- 7.2 起，对空集合做哈希分片默认"每个 shard 一个 chunk"（此前是两个）。

## Query Routing

| 查询条件 | 路由方式 |
| :--- | :--- |
| 含完整 shard key | 定向到单个 shard |
| 含 shard key 前缀 | 定向到少量 shard |
| 不含 shard key | 广播到所有 shard（scatter/gather） |
| 带排序/分页 | 各 shard 局部排序，`mongos` 归并 |

聚合管道会被拆成"shard 段 + merge 段"：过滤、局部 `$group` 下沉到 shard，全局 `$group`、`$sort`、`$limit` 在 `mongos` 合并。`$lookup` 5.1 起支持分片集合，但被连接集合不按外键分片时仍可能广播。

## Resharding and Unsharding

- **5.0 `reshardCollection`**：在线更换 shard key，后台复制数据并追增量，完成后原子切换元数据。
- **8.0 `moveCollection`**：把未分片集合整体搬到指定 shard。
- **8.0 `unshardCollection`**：把已分片集合收拢到单个 shard，退回未分片状态。
- **8.0 `sh.shardAndDistributeCollection()`**：分片后立即按同一键 reshard，快速把数据摊开，不必等 balancer 慢慢搬。

这些操作都会产生大量 IO，且 reshard 需要目标 shard 有足够空间。

## Zones

zone 用于让特定 shard key 区间落在指定 shard 上，典型场景是**多地域数据驻留**：按 `region` 建 zone，把欧盟数据固定在欧盟机房。

```javascript
sh.addShardToZone("shardEU", "EU")
sh.updateZoneKeyRange("app.users", { region: "EU", _id: MinKey }, { region: "EU", _id: MaxKey }, "EU")
```

zone 的区间必须基于 shard key 字段（复合键要包含前缀）。定义 zone 前先想清楚未来是否会扩展地域。

## Transactions and Consistency

分片事务 4.2 起支持，由各 shard 的副本集事务 + `mongos` 协调的两阶段提交完成：

- 跨 shard 事务需要 `readConcern: "snapshot"` 才能保证同一快照；
- 提交需要 config server 与参与 shard 的多数派确认；
- 事务期间若发生 chunk 迁移，可能因元数据变化而中止，需要重试；
- 5.1 起加入 shard 的集群必须设置 Cluster Wide Write Concern（CWWC），否则 shard 启动/加入失败。

## Pitfalls

| 问题 | 原因 | 处理 |
| :--- | :--- | :--- |
| 写热点 | 单调 shard key + 范围分片 | 改哈希/复合键，或 reshard |
| 广播查询 | 查询不带 shard key | 补 shard key 前缀条件或调整键 |
| Jumbo chunk | chunk 超过大小且无法拆分（如单键值过大） | 拆分键或调整 shard key |
| 迁移抖动 | balancer 在业务高峰搬运 | 设置窗口、限流 |
| 孤儿文档 | 迁移中断留下的旧副本 | 用 `cleanupOrphaned` 清理 |
| 元数据膨胀 | chunk 过多且不合并 | AutoMerger、调整 chunk 大小 |

## Links

- [MongoDB](/docs/CS/DB/MongoDB.md)
- [Architecture](/docs/CS/DB/MongoDB/Architecture.md)
- [Replication](/docs/CS/DB/MongoDB/Replication.md)
- [Transaction](/docs/CS/DB/MongoDB/Transaction.md)
- [Shard](/docs/CS/DB/Shard.md)

## References

- [Sharding](https://www.mongodb.com/docs/manual/sharding/)
- [Choose a Shard Key](https://www.mongodb.com/docs/manual/core/sharding-choose-a-shard-key/)
- [Sharded Cluster Balancer](https://www.mongodb.com/docs/manual/core/sharding-balancer-administration/)
- [Config Shard](https://www.mongodb.com/docs/manual/core/config-shard/)
