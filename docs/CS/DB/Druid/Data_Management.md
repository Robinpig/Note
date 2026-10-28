## Introduction

分片一旦写进深存储，Druid 的日常工作就变成了「把它们管好」：**哪些段加载到哪些 Historical（负载规则）、哪些段该淘汰（kill 规则）、太碎的段怎么合并（压实）、坏了的数据怎么换版本（reindex）**。这套机制全部由 Coordinator 驱动，配置形态是「规则（rules）+ 动态配置（dynamic configuration）」，可以在线改、秒级生效——不需要重启集群。这是 Druid 运维面的主战场，也是 [Operations](/docs/CS/DB/Druid/Operations.md) 排障时最常翻的一页。

## Load Rules and Kill Rules

Coordinator 按数据源上的两组规则做决策，规则按顺序匹配、命中即停：

- **负载规则（load rules）**：决定段加载到哪里、加载几份。常用规则：

| 规则 | 行为 |
| :--- | :--- |
| `loadForever` | 永远加载（默认） |
| `dropByRule` / `dropBeforeByRule` | 命中年龄/区间条件的段直接淘汰（最常见保留策略） |
| `interval` | 只对指定时间区间生效 |
| `tieredReplicants` | 指定 tier 与副本数，如 `{"hot": 2, "_default_tier": 1}` |
| `broadcast` | 每个 Historical 都加载一份（小维表的热数据场景） |

- **淘汰规则（kill rules）**：Coordinator 周期性扫描 unused/overshadowed 段并生成 kill 任务删除。30.0.0 改了默认值：`druid.coordinator.kill.period` 默认跟随 `indexingPeriod`（此前固定 P1D），`killTaskSlotRatio` 默认 1.0 → 0.1（kill 任务默认只占一个任务槽，不再吃光槽位）。**kill 任务只在显式指定时才把底层段标记为 unused**——这是「删了数磁盘不缩」的第一嫌疑。

规则经 `/druid/coordinator/v1/rules` API 管理，Web 控制台的 Datasources 视图可以直接编辑。

## Tiering and Query Routing

- **Historical tier**：节点按 `druid.server.tier` 分组，常见 `hot`（SSD、大内存）/ `_default_tier`（廉价存储）分层；负载规则决定段副本落在哪些 tier。**注意 tier 的两种语境**：Historical tier 管数据分布，lookup 的 tier 是另一套（见 [Extensions](/docs/CS/DB/Druid/Extensions.md)），互不相干。
- **Broker 侧 tier 选择**：`druid.broker.select.tier` 决定查询优先打哪些优先级的节点；37.0.0 新增两种策略实现——`strict`（只选优先级匹配的节点）与 `pooled`（跨优先级池化选择，提升可用性）。37.0.0 还允许对实时服务器单独配置 tier 选择（`druid.broker.realtime.select.tier` / `balancer.type`）。
- **QoS 与优先级**：查询上下文 `priority` + Broker 的 laning 机制让高优先级查询先跑；37.0.0 的查询黑名单则提供「按数据源/类型/上下文一键掐掉坏查询」的刹车。

## Compaction

段碎（一个区间多个小段、同维度组合多行未合并）会拖慢加载与查询，压实就是把它们重写成更优形态。37.0.0 是压实的换代节点：

| 形态 | 状态 | 要点 |
| :--- | :--- | :--- |
| Coordinator-issued 压实（老） | 已退役 | 任务前缀 `coordinator-issued`，配置在 Coordinator 动态配置里 |
| **Compaction supervisor** | **37.0.0 GA，推荐默认** | 任务前缀 `auto`；跑在 Overlord 上，可用 native 或 MSQ 压实引擎；31.0.0 引入（compaction scheduler） |
| Minor compaction | 37.0.0 引入，实验性 | 只压新摄入的碎段；已压实段升级时只更新元数据不重压；策略 `mostFragmentedFirst` + 行数/字节阈值 |
| Cascading reindexing | 37.0.0 引入，实验性 | 按数据年龄分层配置：如 90 天前的数据从小时段滚成天段、改压缩、删行、换 rollup 粒度；必须配 compaction supervisor + MSQ 引擎 |

压实状态的存储也变了：37.0.0 起新增 `druid_indexingStates` 表，段里只存 `indexing_state_fingerprint` 引用（省元数据），旧字段 `storeCompactionStatePerSegment` 兼容保留。升级注意：compaction supervisor 需要 Overlord 上的增量段元数据缓存（`useIncrementalCache` 不能为 `never`）。

压实与流摄取可以并发（concurrent append and replace，31.0.0 GA）——**例行压实不再要求流任务停顿**，这是它相对老方案最大的运维收益。

## Reindexing and Updates

**Druid 没有行级更新**。「改数据」的合法姿势只有换版本分片：

- **`REPLACE` / reindex 任务**：读旧段（或外部源）→ 生成新 schema/新 rollup 的新版本段 → 新旧共存 → 旧的被 overshadow 后淘汰。多区间覆盖时**原子性只到单区间**，跨区间不保证原子。
- **compaction 是 reindex 的特例**：schema 不变、只合并碎段。
- **删除**：kill 任务删段，或 `REPLACE ... OVERWRITE WHERE` 按条件重写（37.0.0 的 cascading reindexing 把它做成了按年龄自动执行）。
- **并发安全**：`useConcurrentLocks`（31.0.0 GA 后自动判定为主）允许追加与替换对同一区间并发；29.0.0 修过「交错追加/替换任务导致追加数据丢失」的 bug，跨大版本升级时留意。

## Balancing and Segment Loading

- **均衡策略**：Coordinator 按 `cost` 策略（老 `cachingCost` 在 28.0.0 移除）决定段怎么在 Historical 间铺；加载有节流（`replicationThrottleLimit`，28.0.0 默认 500）与队列上限（`maxSegmentsInNodeLoadingQueue` 默认 500）。
- **加载模式**：27.0.0 起默认批采样（`useBatchedSegmentSampler` 相关配置在 27.0.0 移除，成为标准行为），28.0.0 起推荐 smart segment loading；33.0.0 改过段元数据缓存配置（降级前需设 `druid.manager.segments.useCache=false`）。
- **38.0.0 的加载加速**：`druid.segment.timeline.fastIntervalSearch=true` 用区间树在内存里维护段时间线，加速元数据检索（默认关）。
- **Historical 下线**：decommissioning 模式下 Coordinator 会把该节点的段优雅搬走后放行，控制台 Services 视图可见状态（37.0.0 起展示 cloning/turbo loading/decommissioning）。

## Retention in Practice

一套可落地的保留策略通常这样组合：热数据 7 天 `tieredReplicants` 双副本落 hot tier，30 天前 `dropBeforeByRule` 淘汰，外加每周 auto compaction 把小时段并成天段（数据老化后）。「保留多久」和「以什么形态保留」是两个正交决策——前者是 kill 规则，后者是 cascade 规则，别混在一条规则里写。

## Links

- [Druid](/docs/CS/DB/Druid/Druid.md)
- [Architecture](/docs/CS/DB/Druid/Architecture.md)
- [Storage Format](/docs/CS/DB/Druid/Storage_Format.md)
- [Ingestion](/docs/CS/DB/Druid/Ingestion.md)
- [Operations](/docs/CS/DB/Druid/Operations.md)

## References

1. [Data Retention and Lifecycle Rules](https://druid.apache.org/docs/latest/data-management/lifecycle/)
2. [Compaction](https://druid.apache.org/docs/latest/data-management/compaction)
3. [Druid 37.0.0 Release Notes](https://druid.apache.org/docs/37.0.0/release-info/release-notes)
4. [Druid 30.0.0 Release Notes](https://druid.apache.org/docs/30.0.0/release-info/release-notes)
