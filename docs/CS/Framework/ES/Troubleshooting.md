## Introduction

本篇讲 Elasticsearch 的生产排障：堆内存治理、熔断器、OOM、分片未分配（unassigned）与集群健康判定。

**版本基线：Elasticsearch 9.5.5**（Lucene 10.5.1）。所有默认值均标注 `文件:行号`，可回源码反查。

> [!IMPORTANT]
> **先打破四个直觉**：① 写路径是 **Lucene 先写、translog 后写**——与广为流传的「先写 translog 保证不丢」叙述相反；② 父熔断器默认是 **95%** 堆（不是 70%），因为 `use_real_memory` 默认 true；③ fielddata 熔断默认 **40%**（不是 60%）；④ 官方堆上限是 **31GB**（不是 32GB）。

事实来源：Elasticsearch 源码 v9.5.5（`elastic/elasticsearch` tag `v9.5.5`）。

## 写路径：顺序决定排障方向

`InternalEngine.java:1310-1325` 的 index 主流程：

```java
if (plan.indexIntoLucene || plan.addStaleOpToTranslogToLucene) {
    indexResult = indexIntoLucene(index, plan);
} else { ... }
if (index.origin().isFromTranslog() == false) {
    final Translog.Location location;
    if (indexResult.getResultType() == Result.Type.SUCCESS) {
        location = translog.add(new Translog.Index(index, indexResult));
    } ...
```

即：**文档先进 Lucene IndexWriter 的内存缓冲（`indexWriter.addDocument`），Lucene 返回成功后才 `translog.add()`**。这个顺序影响两件事：

- 节点宕机恢复时，translog 里有的操作必然已在 Lucene 里（或随 Lucene 一起丢失），恢复只需重放「translog 有、Lucene 没有」的部分，不会出现两份；
- 「写成功但数据搜不到」的第一排查方向是 refresh（默认 1s），而不是 translog。

写串行化不靠 IndexShard 级互斥锁，而是三层机制叠加：engine 层 per-UID 锁（`InternalEngine.java:1243-1246` `versionMap.acquireLock(index.uid())`）+ 主分片生成 seq-no（`:1203-1207`）+ 同一 shard 的 bulk 单线程顺序执行。**同一文档的高频更新仍会互相排队**，这是「单分片单线程写」说法的准确版本。

## 熔断器（Circuit Breakers）

ES 用熔断器防止单类操作吃光堆。9.5.5 的内置熔断器只有 **4 个**（`common/breaker/CircuitBreaker.java:27-45` 的四个名字符串常量）：

| 熔断器 | 默认 limit | overhead | 定义处 |
| ---- | ---- | ---- | ---- |
| `parent`（总） | **95%** 堆（`use_real_memory=true`）/ 70%（关闭时） | — | `indices/breaker/HierarchyCircuitBreakerService.java:64-83` |
| `fielddata` | **40%** 堆 | 1.03 | 同上 `:85-97` |
| `request` | **60%** 堆 | 1.0 | 同上 `:105-117` |
| `inflight_requests` | **100%** 堆 | 2.0 | 同上 `:125-137` |

- `indices.breaker.total.use_real_memory` 默认 **true**（`:64-69`），此时按真实内存占用估算，总熔断为 95%；关闭后回到 70% 的旧口径；
- overhead 是「估算值 × 系数」的安全冗余（fielddata 结构难精确估算，所以乘 1.03）；
- 子熔断器统一由 `ChildMemoryCircuitBreaker` 实现，**不存在**独立的 `FielddataCircuitBreaker` / `RequestCircuitBreaker` 类（全仓零命中）；
- 超过熔断时请求直接返回 `circuit_breaking_exception`；G1 下还会先尝试触发一次 GC 再判定（`HierarchyCircuitBreakerService.java:510-535`）。

> [!WARNING]
> 两个最常见的写错数字：父熔断默认 **95%**（不是 70%——70% 是关闭真实内存统计时的旧口径）；fielddata 熔断 **40%**（60% 是 request 熔断器的值）。按 70%/60% 估算堆预算会系统性偏乐观。

## 堆治理：31GB 与自动计算

- 自动堆计算封顶 **31GB**（`distribution/tools/server-cli/.../MachineDependentHeap.java:37` `MAX_HEAP_SIZE = GB * 31`），DATA 节点取机器内存 50%、MASTER_ONLY 取 60%，都受此上限约束；
- 31GB 是为 JVM 压缩普通对象指针（compressed oops）留余量——堆超过约 32GB 时指针压缩失效，同等数据内存占用反而上升；
- **留在堆外的才是大头**：Lucene 段文件由操作系统 page cache 承接（`NodeEnvironment.java:228` 用 `FSDirectory`），doc_values 按需加载；这也是「ES 要吃一半机器内存给 OS cache」的由来；
- `text` 字段的 `fielddata` 默认 **false**（`TextFieldMapper.java:291`）——它把倒排结构装进堆，是堆内存第一嫌疑对象；排序/聚合优先用 doc_values。

## OOM：退出码与排查

`ElasticsearchUncaughtExceptionHandler.java:29-41`：致命未捕获异常会主动停机并区分退出码：

| 异常 | 退出码 |
| ---- | ---- |
| `OutOfMemoryError` | **127** |
| `InternalError` | 128 |
| `StackOverflowError` | 126 |

jvm.options 默认带 `-XX:+HeapDumpOnOutOfMemoryError`（`distribution/src/config/jvm.options:84`），堆转储会落在 logs 目录——**OOM 后第一动作是拿 dump，而不是先扩容**。

经典 OOM 模式（对照历史案例）：

1. **大字段误配全文类型**：把不需要分词的大字段配成 `text`，高并发写入时段合并/索引开销放大——改 `keyword` 或 `index: false`（正解见 Mapping 篇，注意 `not_analyzed` 已非法）；
2. **fielddata 被无意打开**：对 text 字段排序/聚合触发 fielddata 加载进堆——检查 `fielddata: true` 的字段，改用 `.keyword` 或 doc_values；
3. **深分页/大聚合**：`from+size` 或大 bucket 聚合在协调节点堆归并——用 search_after/PIT 替代深翻页（见 Query DSL 篇）；
4. **请求体过大**：request 熔断（60%）拦截前，聚合请求的中间结构先撑爆堆——拆分请求。

## 分片未分配（unassigned）

`UnassignedInfo.java:99-183` 的 19 种原因枚举（节选最常遇到的）：

| Reason | 典型场景 |
| ---- | ---- |
| `NODE_LEFT` | 持有分片的节点离开集群（宕机/重启/网络分区） |
| `CLUSTER_RECOVERED` | 集群重启后的恢复态 |
| `ALLOCATION_FAILED` | 分配被决策器拒绝（磁盘水位、规则不匹配等） |
| `PRIMARY_FAILED` | 主分片所在节点故障，正在提升副本 |
| `REPLICA_ADDED` | 副本数被调大，新副本尚未同步 |
| `INDEX_REOPENED` / `INDEX_CLOSED` | 索引关闭/重开 |
| `FORCED_EMPTY_PRIMARY` | 手工指定以空主分片恢复（**有数据丢失风险**） |

关键默认值：`index.unassigned.node_left.delayed_timeout` 默认 **1 分钟**（stateless 模式 10 秒，`UnassignedInfo.java:81-89`）——节点离开后分片不会立即重分配，等超时确认节点真的走了；`cluster.info.update.interval` 默认 **30 秒**（`InternalClusterInfoService.java:80-86`），是分配决策刷新集群磁盘/负载信息的节奏。

诊断与处置：

```shell
# 为什么没分配（直接给出原因与决策器意见）
GET /_cluster/allocation/explain

# 所有未分配分片一览
GET /_cat/shards?v&h=index,shard,prirep,state,unassigned.reason

# 手工重试失败分配
POST /_cluster/reroute?retry_failed=true

# 确认数据已丢时，强制以空主分片拉起（最后手段）
POST /_cluster/reroute
{
  "commands": [{ "allocate_empty_primary": { "index": "lost-index", "shard": 0, "node": "node-1", "accept_data_loss": true } }]
}
```

分配命令实现在 `cluster/routing/allocation/command/`（`AllocateEmptyPrimaryAllocationCommand`、`AllocateStalePrimaryAllocationCommand`、`MoveAllocationCommand` 等），**`allocate_empty_primary` 必须显式 `accept_data_loss: true`**——没有这个确认，ES 拒绝执行「明知丢数据」的恢复。

## 集群健康：红黄绿判定逻辑

`ClusterShardHealth.java:70-81,179-196` 的判定规则：

- **green**：主分片 active 且所有副本 active（active 数 = 总分片数）；
- **yellow**：主分片 active 但有副本未 active（可读可写、无冗余）；或主分片未 active 但**尚未发生失败分配**（`failedAllocations == 0` 且恢复源是本地分片/快照等）；
- **red**：主分片未 active 且已有失败分配记录。

索引级健康取其所有分片的最差值（`ClusterIndexHealth.java:103-111`）。**yellow 持续不转绿**的常见原因就是上面的 unassigned 清单：副本缺节点、磁盘水位超限、分配规则不匹配——用 `allocation/explain` 逐条看。

## 生命周期：ILM 与 DLM 并存

9.x 两套生命周期机制并存，不是替代关系：

| | ILM | DLM（data stream lifecycle） |
| ---- | ---- | ---- |
| 作用对象 | 普通索引（`index.lifecycle.name`） | data stream（`_data_stream/{name}/_lifecycle`） |
| 轮询间隔 | `indices.lifecycle.poll_interval` 默认 **10m**（`LifecycleSettings.java:37-43`） | `data_streams.lifecycle.poll_interval` 默认 **5m**（`DataStreamLifecycleService.java:126-132`） |
| rollover 条件 | `max_age`/`max_docs`/`max_size`/`max_primary_shard_size`；**`max_size` 已弃用**（推荐 `max_primary_shard_size`，`RestPutLifecycleAction.java:35-36`） | 同样支持条件滚动 + 保留期 `data_retention` |
| 保留期默认 | 策略里显式给 | 无（null = 永久保留，`DataStreamLifecycle.java:171`） |

治理日志索引的实践：缩短保留期（历史案例里把调用链从 7 天缩到 3 天）、调整分片数、扩容三件事的优先级，通常**保留期 > 分片规划 > 扩容**——前两者降的是持续成本，后者只是延缓。

## 陷阱清单

| 说法 / 做法 | 9.5.5 真相 |
| ---- | ---- |
| 先写 translog 再写 Lucene | 相反：Lucene 先成功，才 `translog.add()`（`InternalEngine.java:1310-1325`） |
| 父熔断默认 70% | `use_real_memory` 默认 true 时是 **95%** |
| fielddata 熔断默认 60% | **40%**（60% 是 request 熔断） |
| 官方堆上限 32GB | **31GB**（`MachineDependentHeap.java:37`） |
| text 字段默认可做聚合排序 | fielddata 默认 false；排序聚合走 doc_values 或 `.keyword` |
| 堆给大就能治 OOM | 段文件在 OS page cache、doc_values 在堆外；堆过大反而丢压缩指针，先看 dump 再谈扩容 |
| 分片 unassigned 立即重分配 | `node_left.delayed_timeout` 默认 1 分钟，等超时确认节点离开 |
| 分片丢了直接 reroute 拉起来 | `allocate_empty_primary` 必须 `accept_data_loss: true`，否则拒绝执行 |
| ILM 被 DLM 取代 | 并存；DLM 管 data stream，ILM 管普通索引，仅 `max_size` 条件弃用 |

## Links

- [Elasticsearch（枢纽页）](/docs/CS/Framework/ES/ES.md)
- [Install：安装与节点角色](/docs/CS/Framework/ES/Install.md)
- [Mapping：数据模型与字段映射](/docs/CS/Framework/ES/Mapping.md)
- [Query DSL：查询两阶段与分页](/docs/CS/Framework/ES/Query_DSL.md)
- [Lucene：倒排、段与分片](/docs/CS/Framework/ES/Lucene.md)

## References

1. [Elasticsearch Reference - Circuit Breaker](https://www.elastic.co/guide/en/elasticsearch/reference/current/circuit-breaker.html)
2. [Elasticsearch Reference - Cluster Allocation Explain](https://www.elastic.co/guide/en/elasticsearch/reference/current/cluster-allocation-explain.html)
3. [Elasticsearch Reference - Index Lifecycle Management](https://www.elastic.co/guide/en/elasticsearch/reference/current/index-lifecycle-management.html)
4. [elastic/elasticsearch v9.5.5 源码](https://github.com/elastic/elasticsearch/tree/v9.5.5)
