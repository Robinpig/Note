## Introduction

本篇拆解 Elasticsearch 的写入链路与主从复制协议：一个 bulk 请求从协调节点到 Lucene 落盘的完整路径，以及 ES 如何在「默认不等副本」的前提下保证分布式写正确性。

**版本基线：Elasticsearch 9.5.5**。下文 `server/...` 路径均相对源码根（`elastic/elasticsearch` tag `v9.5.5`），可逐条反查。

> [!IMPORTANT]
> **先打破四个直觉**：① 主分片上 bulk **不按文档 id 去重、不排序、不合并**——严格按请求顺序逐条执行（6.x 时代的行为早已改变）；② 写路径是 **Lucene 先写、translog 后写**，不是「先写 translog 保不丢」；③ `index.translog.retention.size/age` 在 8.0 起**已移除**，设了直接报错；④ `index.translog.flush_threshold_size` 默认是 **10GB**，不是 512MB。

## 协调节点：bulk 的分片分组

`BulkOperation.doRun()`（`server/.../action/bulk/BulkOperation.java:212`）按 cluster state 把 bulk 拆成分片级请求：

```java
// BulkOperation.java:312-389 groupRequestsByShards
Map<ShardId, List<BulkItemRequest>> requestsByShard = new HashMap<>();
...
shardId = docWriteRequest.route(indexRouting);          // :366 路由计算
requestsByShard.computeIfAbsent(new ShardId(concreteIndex, shardId), ...);  // :369-373
```

每个 ShardId 构造一个 `BulkShardRequest` 发往 `TransportShardBulkAction`（`BulkOperation.java:420-473`）。**分组只按分片，不按文档 id**：同一 doc 在 bulk 里出现多次（如 index + delete）不会合并，而是各自分配独立 seq_no 按序执行——这是「bulk 内后一条覆盖前一条」的实现方式，依赖的是 seq_no 顺序而非任何去重逻辑。

## 主分片：ReplicationOperation 调用链

写请求到达主分片后的完整链路（`TransportReplicationAction.java`）：

```
ReroutePhase（:912-1224，按 routing 定位 primary 节点）
 → AsyncPrimaryAction.doRun（:497-548）
     ① primary 身份校验：shardRouting.primary() == false → RetryOnPrimaryException（:514-515）
     ② term 校验：actualTerm != primaryRequest.getPrimaryTerm() → ShardNotFoundException（:526-535）
 → executePrimaryRequest（:611-657）→ new ReplicationOperation<>(...).execute()
 → ReplicationOperation.execute()（:110-141）
     checkActiveShardCount() → primary.perform() → handlePrimaryResult()
 → performOnReplicas（:249-275）：每个副本一个 RetryableAction（:345-372）
 → runPostReplicationActions（:200-228）→ AsyncAfterWriteAction（TransportWriteAction.java:376-484，refresh/fsync）
```

### 成功条件：默认只等主分片

`ReplicationOperation.checkActiveShardCount`（`ReplicationOperation.java:482-514`）调用 `ActiveShardCount.enoughShardsActive`（`ActiveShardCount.java:188-208`），而 `index.write.wait_for_active_shards` 默认 `"1"`（`IndexMetadata.java:484-490`）——**默认配置下主分片本地写完就向客户端返回成功，副本尚未确认**。副本 ACK 只统计进响应的 `successfulShards` 与失败列表，副本落后/失败会把副本标记为 stale，由后续 recovery 修补。

强一致写法：请求级 `?wait_for_active_shards=all`（或 `2`/`quorum`），或索引级改设置。

## 并发正确性三件套

### seq_no：单调序号

由主分片 engine 在写路径上分配：`InternalEngine.generateSeqNoForOperationOnPrimary`（`InternalEngine.java:1203-1207`）→ `localCheckpointTracker.generateSeqNo()`。副本通过 `_seq_no` 判断「这条操作我处理过没有」，也是复制乱序/重传的去重键。

### primary_term：防旧主复活

`_primary_term` 随每次主分片提升而递增。副本收到写请求时校验（`IndexShard.java:4297-4306`）：

```java
if (opPrimaryTerm < getOperationPrimaryTerm()) {
    throw new IllegalStateException("... operation primary term [" + opPrimaryTerm + "] is too old ...");
}
```

网络分区后旧主（term 较小）上的写会被副本以「term 太旧」拒绝——这是 7.x 之后取代 `minimum_master_nodes` 的脑裂防护核心。

### in-sync allocation IDs

`ReplicationTracker`（`server/.../index/seqno/ReplicationTracker.java`）维护 in-sync 副本集合：

- `updateFromMaster`（`:1158-1219`）：按 cluster state version 顺序应用 master 下发的集合，移除不再 in-sync 的条目；
- `markAllocationIdAsInSync`（`:1248-1300`）：local checkpoint 未达 global checkpoint 时进 `pendingInSync` 等待；
- `computeGlobalCheckpoint`（`:1357-1378`）：有 pendingInSync 或副本 checkpoint 为 UNASSIGNED 时 global checkpoint **不前进**——这保证「已确认可读的序号」不被过快推进。

in-sync 集合**完全由 master 侧 allocation 决策经 cluster state 下发**，没有任何 `index.allocation*` 设置能控制它。

## noop：副本的「已处理」应答

副本收到主分片转发的操作时，若 local checkpoint 已覆盖该 seq_no（乱序/重传场景），不重复写 Lucene，而是记录 noop 应答：

- 主分片侧：`TransportShardBulkAction.performOnReplica` 对**失败但带 seqNo** 的响应调 `replica.markSeqNoAsNoop`（`TransportShardBulkAction.java:808-847` → `IndexShard.java:1247-1259`）；
- engine 侧：`InternalEngine.applyNoOpToLucene`（`:2549-2586`）先 `hasBeenProcessedBefore`（`:3756-3766`，即 `localCheckpointTracker.hasProcessed(op.seqNo())`）判定，已处理则跳过 Lucene 写入。

noop 与 `wait_for_active_shards` **无关**——后者只数 routing table 里的 active shard。另有一类 noop 是 update 场景：`TransportShardBulkAction.executeBulkItemRequest` 检测到脚本未产生变化时 `markOperationAsNoOp`（`:485-490`），这类请求**根本不会转发给副本**。

## Lucene 与 translog 的写序

`InternalEngine.index` 主流程（`InternalEngine.java:1310-1325`）：

```java
if (plan.indexIntoLucene || plan.addStaleOpToLucene) {
    indexResult = indexIntoLucene(index, plan);      // 先进 IndexWriter 内存缓冲
} else { ... }
if (index.origin().isFromTranslog() == false) {
    if (indexResult.getResultType() == Result.Type.SUCCESS) {
        location = translog.add(new Translog.Index(index, indexResult));  // Lucene 成功后才写 translog
    } ...
```

顺序不可颠倒的原因：translog 是 Lucene 操作的**记录**，恢复时只需重放「translog 有、Lucene 没有」的操作；若 translog 先写而 Lucene 失败，恢复时会重放一条从未进入 Lucene 的操作，反而要多做一次幂等处理。写串行化靠三层叠加而非分片级互斥锁：engine 层 per-UID 锁（`versionMap.acquireLock`，`InternalEngine.java:1243-1246`）+ 主分片 seq-no + 同 shard bulk 单线程执行。

## translog 的内部结构与保留

Checkpoint 字段（`server/.../index/translog/Checkpoint.java:32-41`）：`offset、numOps、generation、minSeqNo、maxSeqNo、globalCheckpoint、minTranslogGeneration、trimmedAboveSeqNo`（当前格式 V4）。Snapshot 只是迭代接口（`Translog.java:1121-1155`，`totalOperations/skippedOperations/next`）。

- **fsync 策略**：`TranslogWriter.syncUpTo`（`TranslogWriter.java:534-595`）仅当 `lastSyncedCheckpoint.offset < offset` 或 global checkpoint 前进且 `syncNeeded()` 时才 `channel.force(false)`；新 generation 创建时 `Checkpoint.write(..., force(true))` 全量刷盘。`durability=REQUEST`（默认）每请求 fsync；`ASYNC` 时由 `IndexService.AsyncTranslogFSync` 按 `sync_interval`（默认 5s）周期 fsync；
- **trim 策略**：`Translog.trimUnreferencedReaders`（`:2270-2323`）的最小保留 generation = `min(deletionPolicy.getMinTranslogGenRequiredByLocks(), minGenerationForSeqNo(localCheckpointOfSafeCommit + 1))`（`:2325-2343`）——只受 retention lock 与安全提交约束，**没有任何 size/age 阈值**；
- **generation 滚动**：`index.translog.generation_threshold_size` 默认 **64MB**（`IndexSettings.java:424-426`），超过即 `rollGeneration`（`Translog.java:2234-2258`：关旧 writer 为 reader、写 commit checkpoint、开新 writer）。

> [!WARNING]
> `index.translog.retention.size` / `retention.age` **已移除**：8.0+ 创建的索引设置即抛 `IllegalArgumentException`（`MetadataCreateIndexService.java:2187-2206`）。旧教程「调大 translog 保留」在 9.x 无效。

## flush 的触发条件（比想象的少）

`IndexShard.afterWriteOperation`（`IndexShard.java:4434-4464`）在写后检查，flush 的实际触发源有五处：

| 触发源 | 阈值 | 定义处 |
| ---- | ---- | ---- |
| translog 字节超限 | `index.translog.flush_threshold_size` 默认 **10GB**（且不超过磁盘总量 1%） | `IndexSettings.java:375-391,1957-1970` |
| 距上次 flush 超时 | `index.translog.flush_threshold_age` 默认 **1m** | `IndexSettings.java:393-406` |
| 大 merge 之后 | `index.flush_after_merge` 默认 **512MB** | `IndexSettings.java:411-418` |
| 版本表内存回收 | `reclaimVersionMapMemory` 达半个 flush 阈值 | `InternalEngine.java:2724-2740` |
| shard 长期不活跃 | `indices.memory.shard_inactive_time` 默认 **5m** 驱动 `flushOnIdle` | `IndexingMemoryController.java:75-81` |

flush 完成后滚 translog generation 并 trim（`InternalEngine.flushHoldingLock`，`:2785-2842`）。**不存在 `index.flush_after_inactive`**——shard 空闲 flush 是 node 级 memory controller 驱动的。

refresh 的定时调度同样没有独立服务类：`IndexService.AsyncRefreshTask`（`IndexService.java:1262-1281`）跑在 `REFRESH` 线程池，按 `index.refresh_interval`（默认 1s）执行 `shard.scheduledRefresh`。

## Lucene 侧的 ES 配置

`InternalEngine.getIndexWriterConfig`（`InternalEngine.java:3323-3392`）传给 Lucene 的关键参数：

| 参数 | ES 侧默认 | 来源 |
| ---- | ---- | ---- |
| RAM buffer | `indices.memory.index_buffer_size` = **堆的 10%**（下限 48MB） | `IndexingMemoryController.java:48-63`，经 `EngineConfig.java:215-229` 动态管理 |
| similarity | **BM25，k1=1.2、b=0.75、discountOverlaps=true** | `SimilarityProviders.java:256-263`，实现是 ES 自己的 `LegacyBM25Similarity` |
| codec | `default` → Lucene104 BEST_SPEED | `CodecService.java:38,50-57` |
| merge policy | 普通索引 TieredMergePolicy；**time-based 索引 LogByteSizeMergePolicy** | `MergePolicyConfig.java:162-203`（详见 Merge 篇） |
| soft deletes | `iwc.setSoftDeletesField(Lucene.SOFT_DELETES_FIELD)` | `InternalEngine.java:3334` |

## 更新与删除的落地形态

- `_update` 是 get-modify-index 三步：`UpdateHelper.prepare`（`server/.../action/update/UpdateHelper.java:63-93`）先 get（带 `if_seq_no`/`if_primary_term`），不存在走 upsert（强制 `create(true)`，`:115-176`），有 doc 走合并（`:197-250`），有 script 走脚本（`:257-337`），最终都转成带乐观锁的 index 请求；
- **删除不是从段里抹掉**：`InternalEngine.deleteInLucene`（`:2351-2399`）生成带 `_tombstone` 字段 + `SOFT_DELETES_FIELD` 的墓碑文档，经 `IndexWriter.softUpdateDocument` 写入。所谓「`.liv` 标记删除」是 Lucene 段内 live-docs 文件，与 ES 墓碑是两层机制——ES 的软删除墓碑还要靠 merge 时按保留策略清理（`SoftDeletesRetentionMergePolicy`）；
- by-query 批量操作从搜索 hit 取 `_seq_no`/`_primary_term` 设为 `if_seq_no`/`if_primary_term`（`TransportUpdateByQueryAction.java:190-199`、`AsyncDeleteByQueryAction.java:73-80`），冲突计入 version conflicts 统计而非失败。

## 陷阱清单

| 说法 / 做法 | 9.5.5 真相 |
| ---- | ---- |
| bulk 单分片按 doc id 去重/合并 | 不去重不排序，按请求顺序逐条执行、各自分配 seq_no |
| 先写 translog 再写 Lucene | 相反：Lucene 先成功，才 `translog.add()` |
| `index.translog.retention.size/age` 可调 | 8.0 起移除，8.0+ 索引设了直接报错 |
| flush_threshold_size 默认 512MB | **10GB**，且不超过磁盘总量 1% |
| `index.flush_after_inactive` | 不存在；shard 空闲 flush 由 `indices.memory.shard_inactive_time`（5m）驱动 |
| 写成功=副本已同步 | `wait_for_active_shards` 默认 1，只等主分片 |
| `TRANLOG_NOOP` 常量 | 不存在；noop 是 `Translog.NoOp`/`Engine.NoOp` |
| `.liv` 是 ES 的删除机制 | `.liv` 是 Lucene 段内 live-docs；ES 墓碑是 `_tombstone`+SOFT_DELETES 文档 |
| 旧主复活会写入成功 | primary_term 校验拒绝旧 term 的写（`IndexShard.java:4297-4306`） |
| BM25 是 Lucene 默认参数 | ES 用仓库内 `LegacyBM25Similarity`（k1=1.2/b=0.75/discountOverlaps=true） |

## Links

- [Elasticsearch（枢纽页）](/docs/CS/Framework/ES/ES.md)
- [Mapping：数据模型与字段映射](/docs/CS/Framework/ES/Mapping.md)
- [Lucene：倒排、段与分片](/docs/CS/Framework/ES/Lucene.md)
- [Merge：段合并与 store](/docs/CS/Framework/ES/Merge.md)
- [Thread Pools：线程池模型](/docs/CS/Framework/ES/Thread_Pools.md)

## References

1. [Elasticsearch Reference - Distributed read/write](https://www.elastic.co/guide/en/elasticsearch/reference/current/docs-replication.html)
2. [elastic/elasticsearch v9.5.5 源码](https://github.com/elastic/elasticsearch/tree/v9.5.5)
