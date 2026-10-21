## Introduction

本篇拆解 ES 的段合并、store 与磁盘交互：段从产生到合并的策略参数、9.x 更换的 merge 调度器、shard 的磁盘布局与 HybridDirectory。

**版本基线：Elasticsearch 9.5.5**（Lucene 10.5.1）。Lucene 的 `TieredMergePolicy`/`LogByteSizeMergePolicy` 内部实现不在 ES 仓库，本篇只覆盖 ES 侧配置桥；下文 `server/...` 路径相对源码根（tag `v9.5.5`）。

> [!IMPORTANT]
> **先打破四个直觉**：① **默认 merge scheduler 已换成 `ThreadPoolMergeScheduler`**（跑在 node 级 merge 线程池），Lucene `ConcurrentMergeScheduler` 的 ES 子类已弃用；② time-based 索引（mapping 含 `@timestamp`）默认用 **`LogByteSizeMergePolicy`** 而非 Tiered；③ `_forcemerge` 的 `max_num_segments` 默认是 **-1**（等于 `maybeMerge`，不强制降段数）；④ store 默认类型既不是纯 mmap 也不是 NIOFS，是 **HybridDirectory**（按文件扩展名分流到 mmap/directio/NIOFS）。

## 段合并策略：两个 policy

ES 侧持有两个 Lucene policy 实例（`server/.../index/MergePolicyConfig.java:106-112`），按索引类型选择（`:162-203`）：

```java
private final TieredMergePolicy tieredMergePolicy = new TieredMergePolicy();
private final LogByteSizeMergePolicy timeBasedMergePolicy = new LogByteSizeMergePolicy();

UNSET {
    MergePolicy getMergePolicy(MergePolicyConfig config, boolean isTimeBasedIndex) {
        if (isTimeBasedIndex) { return config.timeBasedMergePolicy; }
        else { return config.tieredMergePolicy; }
    }
}
```

`isTimeBasedIndex` 判定：mapping 存在 timestamp 字段类型（`IndexShard.java:4000` `getTimestampFieldType() != null`）。**日志/TSDS 类索引因此默认就走 LogByteSizeMergePolicy**，按字节大小而非段数组织 tier，更适合时序写模式。

关键参数（默认值与定义处，`MergePolicyConfig.java:119-273`）：

| 参数 | 默认 | 生效对象 |
| ---- | ---- | ---- |
| `index.merge.policy.type` | UNSET | 显式选 TIERED / TIME_BASED |
| `index.merge.policy.floor_segment` | 16mb | 两者 |
| `index.merge.policy.max_merge_at_once` | 16 | Tiered |
| `index.merge.policy.segments_per_tier` | 8.0 | Tiered |
| `index.merge.policy.deletes_pct_allowed` | 20.0 | Tiered |
| `index.merge.policy.expunge_deletes_allowed` | 10.0 | Tiered（`setForceMergeDeletesPctAllowed`） |
| `index.merge.policy.merge_factor` | **32**（Lucene 默认 8，ES 特意改大） | LogByteSize |
| `index.merge.policy.max_merged_segment` | **0（占位）** → node 级 5gb/100gb | 两者 |
| `indices.merge.policy.max_merged_segment` | 5gb | Tiered 真实默认 |
| `indices.merge.policy.max_time_based_merged_segment` | 100gb | LogByteSize 真实默认 |
| `index.compound_format` | 1gb | 两者 |
| `index.merge.policy.max_merge_at_once_explicit` | 30 | **V9 弃用 no-op**（`IndexSettingDeprecatedInV9AndRemovedInV10`，update consumer 是 `ignored -> {}`，`IndexSettings.java:1647`） |

索引级 `max_merged_segment=0` 表示「未设置」，回退 node 级默认（`MergePolicyConfig.java:332-341`）——只写「默认 5gb」会漏掉 time-based 的 100gb。

## merge 调度器：9.x 换了默认实现

`InternalEngine` 的选择逻辑（`InternalEngine.java:3511-3522`）：有 `ThreadPoolMergeExecutorService` 就用 `EngineThreadPoolMergeScheduler`，否则用 `EngineConcurrentMergeScheduler`。

**默认路径**（`server/.../index/engine/ThreadPoolMergeScheduler.java:46-52` 类注释 "This is the default merge scheduler in Elasticsearch"）：

- merge 执行委托给 node 级共享线程池 `ThreadPool.Names.MERGE`（`ThreadPoolMergeExecutorService.java:245-246`）；
- 自带两个 Lucene 版没有的能力：**磁盘水位阻塞 merge**（`indices.merge.disk.watermark.high` 默认取 flood-stage watermark 即 95%，`:89-116`；检查间隔 `indices.merge.disk.check_interval` 5s）与 **IO 自适应限速**（5MB/s–10GB/s，初值 20MB/s，`:181-189`）；
- 并发控制自己实现：`runningMergeTasks.size() < getMaxThreadCount()` 决定 RUN/BACKLOG（`:322-340`）。

旧路径 `ElasticsearchConcurrentMergeScheduler`（extends Lucene `ConcurrentMergeScheduler`）已 `@Deprecated`，只能通过同样 deprecated 的 `indices.merge.scheduler.use_thread_pool=false` 回退（`ThreadPoolMergeScheduler.java:64-69`）。

调度参数（`server/.../index/MergeSchedulerConfig.java:46-65`，均为 index 级 dynamic）：

| 参数 | 默认 |
| ---- | ---- |
| `index.merge.scheduler.max_thread_count` | `max(1, availableProcessors/2)`（与 `node.processors` 无关） |
| `index.merge.scheduler.max_merge_count` | `max_thread_count + 5` |
| `index.merge.scheduler.auto_throttle` | true |

9.5.5 新增 clamp：生效线程数 = `min(requested, maxMergeCount)`（`MergeSchedulerConfig.java:128-136`）。

## force merge：默认不降段数

`ForceMergeRequest.Defaults`（`server/.../action/admin/indices/forcemerge/ForceMergeRequest.java:35-43`）：

```java
public static final int MAX_NUM_SEGMENTS = -1;              // 不是 1
public static final boolean ONLY_EXPUNGE_DELETES = false;
public static final boolean FLUSH = true;
```

执行语义（`InternalEngine.java:3025-3081`）：

- `maxNumSegments=-1`（默认）→ `indexWriter.maybeMerge()`，**只触发常规 merge 判断，不保证降到任何段数**；
- `maxNumSegments>0` → `forceMerge(n, true)`，第二个参数 true = **阻塞直到完成**，HTTP 请求不会提前返回；
- `only_expunge_deletes=true` → `forceMergeDeletes(true)`，只清理死文档；与 `max_num_segments` 互斥（`ForceMergeRequest.java:167-172`）；
- flush 默认 true：force merge 后 flush + refresh。

线程池：协调走 `MANAGEMENT`，每 shard 实际执行在 `FORCE_MERGE` 池（`TransportForceMergeAction.java:67,108`）。forced merge 经 scheduler 但 **IO 不限流**（仅 `mergeMaxNumSegments == -1` 的常规 merge 才 auto-throttle，`ThreadPoolMergeScheduler.java:277-278`），同一 engine 由 `optimizeLock` 保证串行。

## store：磁盘布局与目录类型

### 布局

```
${data.paths}/indices/{index-uuid}/{shardId}/index      ← Lucene 段文件
${data.paths}/indices/{index-uuid}/{shardId}/translog  ← translog
```

（`NodeEnvironment.java:122-136` + `ShardPath.java:32-33`；自定义 shard 数据路径时 `shardStatePath` 与 `dataPath` 分离。）

锁分两层：进程内 `InternalShardLock`（`Semaphore(1)` + 引用计数，`NodeEnvironment.java:875-917`，超时抛 `ShardLockObtainFailedException`）+ 每 data path 的 OS 级 `node.lock` 文件（`:186`，防止同路径被两个节点挂载）。Store 构造接收 `ShardLock`，关闭时释放（`Store.java:487-492`）。

### 默认目录类型：HybridDirectory

`IndexModule.defaultStoreType`（`server/.../index/IndexModule.java:490-496`）：`allow_mmap && 64bit JRE` → **HYBRIDFS**，否则 NIOFS。`node.store.allow_mmap` 默认 **true**（`IndexModule.java:107`），所以默认就是 hybridfs。

`FsDirectoryFactory.java:107-116` 的 hybridfs 分支：Lucene `FSDirectory.open` 按平台选定主目录（64 位 Linux 上是 `MMapDirectory`），ES 包装成 `HybridDirectory extends NIOFSDirectory`，内部持有 MMapDirectory + DirectIODirectory 两个 delegate，按**文件扩展名**与 IOContext hint 分流。可选 type：`hybridfs/niofs/mmapfs/simplefs/fs`（`IndexModule.java:446-451`）；`allow_mmap=false` 时显式选 mmapfs/hybridfs 会抛异常（`:612-614`）。

设计动机：mmap 读段文件零拷贝、吃 page cache，但 (a) 并发 mmap 计数受 `vm.max_map_count` 限制，(b) 部分文件（如 `.cfs` 之外的元数据）mmap 收益低。hybrid 只对高频读的段文件用 mmap，其余走 NIOFS，并可用 `index.store.preload` 预热扩展名列表。DirectIO 相关：`index.store.fs.directio_async_prefetch_limit` 默认 64（0–256，`FsDirectoryFactory.java:77-86`）。

### 快照如何读不可变段

快照持有 `IndexCommitRef` 引用计数，保证 commit 引用的段文件不被 merge 删除（`SnapshotShardContextHelper.java:76` → `IndexShard.acquireIndexCommitForSnapshot`，`IndexShard.java:1724`）。段不可变性（见 Lucene 篇）是快照「不锁写」的前提。

## 关键默认值表

| 配置/常量 | 默认值 | 定义处 |
| ---- | ---- | ---- |
| merge policy（普通索引） | Lucene TieredMergePolicy | `MergePolicyConfig.java:107,184-186` |
| merge policy（time-based） | Lucene LogByteSizeMergePolicy | `MergePolicyConfig.java:112,183` |
| `index.merge.policy.merge_factor` | 32（LogByteSize） | `MergePolicyConfig.java:151` |
| `indices.merge.policy.max_merged_segment` | 5gb / 100gb | `MergePolicyConfig.java:122,135` |
| `index.merge.scheduler.max_thread_count` | max(1, cores/2) | `MergeSchedulerConfig.java:46-52` |
| `index.merge.scheduler.max_merge_count` | threads+5 | `MergeSchedulerConfig.java:53-59` |
| `indices.merge.scheduler.use_thread_pool` | true（deprecated 开关） | `ThreadPoolMergeScheduler.java:64-69` |
| `indices.merge.disk.check_interval` | 5s | `ThreadPoolMergeExecutorService.java:78-83` |
| merge IO 限速 | 5MB/s – 10GB/s（初值 20MB/s） | `:181-189` |
| `_forcemerge` max_num_segments / flush | -1 / true | `ForceMergeRequest.java:36-38` |
| `index.store.type` | 空 → hybridfs | `IndexModule.java:113-117,490-496` |
| `node.store.allow_mmap` | true | `IndexModule.java:107` |
| `index.store.fs.fs_lock` | native | `FsDirectoryFactory.java:69-75` |
| `index.store.fs.directio_async_prefetch_limit` | 64 | `FsDirectoryFactory.java:77-86` |

## 陷阱清单

| 说法 / 做法 | 9.5.5 真相 |
| ---- | ---- |
| 默认 merge scheduler 是 ConcurrentMergeScheduler | 默认是 `ThreadPoolMergeScheduler`（merge 线程池 + 磁盘阻塞 + IO 限速）；旧版已 @Deprecated |
| 所有索引默认 TieredMergePolicy | time-based 索引默认 LogByteSizeMergePolicy（merge_factor 32） |
| `max_merge_at_once_explicit` 可调 force merge 并发 | V9 起弃用 no-op，不桥接任何 Lucene 参数 |
| `max_merged_segment` 默认 5gb | 索引级默认 0 占位；真实默认 node 级 5gb / time-based 100gb |
| `_forcemerge` 默认合到 1 段 | 默认 `max_num_segments=-1`（maybeMerge）；要降段必须显式传 1 |
| force merge 异步返回 | `forceMerge(n, true)` 阻塞直到完成 |
| store 默认纯 mmap / 纯 NIOFS | 默认 HybridDirectory，按文件扩展名分流 mmap/NIOFS/DirectIO |
| `indices.store.throttle` 调 merge IO | 已移除；限流在 merge scheduler（auto throttle）与 recovery（`indices.recovery.max_bytes_per_sec`） |
| `node.store.allow_mmap` / `index.store.type` 已移除 | 都存在且默认 true / hybridfs |

## Links

- [Elasticsearch（枢纽页）](/docs/CS/Framework/ES/ES.md)
- [Lucene：倒排、段与分片](/docs/CS/Framework/ES/Lucene.md)
- [Replication：写入与复制协议](/docs/CS/Framework/ES/Replication.md)
- [Troubleshooting：排障](/docs/CS/Framework/ES/Troubleshooting.md)
- [Thread Pools：线程池模型](/docs/CS/Framework/ES/Thread_Pools.md)

## References

1. [Elasticsearch Reference - Merge policy settings](https://www.elastic.co/guide/en/elasticsearch/reference/current/index-modules-merge.html)
2. [Elasticsearch Reference - Store settings / mmapfs](https://www.elastic.co/guide/en/elasticsearch/reference/current/index-modules-store.html)
3. [elastic/elasticsearch v9.5.5 源码](https://github.com/elastic/elasticsearch/tree/v9.5.5)
