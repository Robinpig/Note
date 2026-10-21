## Introduction

本篇拆解 ES 的线程池模型：24 个内置池的分工、队列拒绝策略（429 从哪来）、协调与执行的线程分离，以及背压的两条独立路径。

**版本基线：Elasticsearch 9.5.5**。下文 `server/...` 路径相对源码根（tag `v9.5.5`），可逐条反查；`p` = `EsExecutors.allocatedProcessors`（即 `node.processors`，默认取 CPU 核数，`EsExecutors.java:82-84`）。

> [!IMPORTANT]
> **先打破四个直觉**：① `listener`/`bulk`/`index`/`percolate`/`suggest`/`search_throttled` 这些 6.x 时代的池**在 9.x 全部不存在**；② 队列满**不是** caller-runs，有界 fixed 池直接抛 `EsRejectedExecutionException`（映射 429）；③ search 的协调/reduce 跑在独立的 **`search_coordination`** 池，不是 `search` 池；④ bulk 429 通常不是 `write` 队列打满（它的队列深达 max(750p,10000)），而是 coordinating 层的 indexing pressure。

## 池清单：24 个

注册表在 `server/.../threadpool/DefaultBuiltInExecutorBuilders.java`，名称枚举 `ThreadPool.Names`（`server/.../threadpool/ThreadPool.java:78-148`）。

### 写入链路

| 池 | 类型 | 线程数 | 队列 |
| ---- | ---- | ---- | ---- |
| `write` | fixed | p | **max(750p, 10000)** |
| `write_coordination` | fixed | p | 10000 |
| `system_write` / `system_write_coordination` | fixed | halfProcMaxAt5 | 1000 |

`write` 是主分片上真正执行 Lucene 写的池（`TransportWriteAction.java:99` 传 DIRECT，由 `executor(IndexShard)` 落到 `Names.WRITE`）。`write_coordination` 做 transport 线程之后的分片路由/压缩（`TransportAbstractBulkAction.java:123-124,163-164`）：在 IO 线程快速检查 indexing pressure 后 fork 过来，避免阻塞 netty。`system_*` 三个池服务系统索引（`.kibana`、安全索引等）的隔离。

### 查询链路

| 池 | 类型 | 线程数 | 队列 |
| ---- | ---- | ---- | ---- |
| `search` | fixed | (3p/2)+1 | size×1000 |
| `search_coordination` | fixed | (p+1)/2 | 1000 |
| `get` | fixed | (3p/2)+1 | 1000 |
| `auto_complete` | fixed | max(p/4,1) | 100 |

**执行与协调分离**：数据节点上的 query/fetch 阶段用 `search` 池（`SearchQueryThenFetchAsyncAction.java:711`）；协调节点的 rewrite、reduce、remote 响应用 `search_coordination`（`TransportSearchAction.java:773,1370,1483`，`CanMatchPreFilterSearchPhase.java:246` 断言当前线程即该池）。分页深的大查询 reduce 慢不会占满执行池，反之亦然。

### 集群与管理

| 池 | 类型 | 线程数 | 队列 |
| ---- | ---- | ---- | ---- |
| `cluster_coordination` | fixed | **1** | 无界 |
| `management` | scaling | 1 – boundedBy(p,1,5) | 无界 |
| `flush` | scaling | 1 – halfProcMaxAt5 | 无界 |
| `refresh` | scaling | 1 – halfProcMaxAt10 | 无界 |
| `warmer` | scaling | 1 – halfProcMaxAt5 | 无界 |
| `merge` | scaling | 1 – p | 无界 |
| `force_merge` | fixed | max(1, p/8) | 无界 |
| `snapshot` | scaling | 1 – 10 | 无界 |
| `snapshot_meta` | scaling | 1 – min(3p,50) | 无界 |
| `fetch_shard_started` / `fetch_shard_store` | scaling | 1 – 2p | 无界 |
| `generic` | scaling | 4 – boundedBy(4p,128,512) | 无界 |
| `analyze` | fixed | 1 | 16 |
| `system_read` / `system_critical_read` | fixed | halfProcMaxAt5 | 2000 |
| `system_critical_write` | fixed | halfProcMaxAt5 | 1500 |

两个值得注意的点：

- `merge` 池**仅当 `indices.merge.scheduler.use_thread_pool=true`（默认）时才注册**（`DefaultBuiltInExecutorBuilders.java` 条件注册），旧 merge scheduler 路径下不存在这个池（详见 Merge 篇）；
- `halfProcMaxAt5` = boundedBy((p+1)/2, 1, 5)，`halfProcMaxAt10` = boundedBy((p+1)/2, 1, 10)（`ThreadPool.java:679-685`）——小机器上缩、大机器上封顶 5/10。

## 三种 executor 与拒绝策略

`EsExecutors.newFixed`（`server/.../common/util/concurrent/EsExecutors.java:201-247`）：

```java
if (queueCapacity < 0) {
    queue = ConcurrentCollections.newBlockingQueue();
    rejectedExecutionHandler = new RejectOnShutdownOnlyPolicy();   // 无界：仅 shutdown 后拒绝
} else {
    queue = new SizeBlockingQueue<>(..., queueCapacity);
    rejectedExecutionHandler = new EsAbortPolicy();                 // 有界：满即抛
}
```

| executor | 队列 | 满时行为 |
| ---- | ---- | ---- |
| fixed（有界） | SizeBlockingQueue | **`EsAbortPolicy` 抛 `EsRejectedExecutionException`**（`EsAbortPolicy.java:14-35`） |
| fixed（`queue_size=-1`） | 无界 LinkedBlockingQueue | `RejectOnShutdownOnlyPolicy`，仅 shutdown 拒绝 |
| scaling | 无界 LinkedTransferQueue | `ForceQueuePolicy`（实际不拒绝，generic 池注释 "This pool does not reject any task"） |

`EsAbortPolicy` 唯一例外：`AbstractRunnable.isForceExecution()` 为 true 的系统关键任务会 `forcePut` 强插（如刷新 metadata）。

### 429 的来源

`ExceptionsHelper.status()`（`server/.../ExceptionsHelper.java:80-93`）把 `EsRejectedExecutionException` 映射为 `RestStatus.TOO_MANY_REQUESTS`。bulk 的 429 = bulk 子请求在 `write`（或 `write_coordination`）池被 `EsAbortPolicy` 拒绝。

> [!TIP]
> 排 bulk 429 时别只看 `_cat/thread_pool` 的 write 队列：`write` 队列默认 max(750p,10000)，通常先打满的是 **indexing pressure**（协调节点对内存中已排队索引字节的限制，`TransportAbstractBulkAction` 的 pressure 检查），或 `indexing_pressure.memory.limit`（默认堆 10%？以 `IndexingPressureSettings` 为准）。两者都会在进入 write 池前就拒绝。

## 调整规则与硬限

`thread_pool.<name>.{size,queue_size}`（`FixedExecutorBuilder.java:119-128`）：

- `queue_size`：`Setting.intSetting` 三参版，**无 min/max 校验**；`-1` = 无界。scaling 池不注册 queue_size，只有 `core`(min 0)/`max`(min 1)/`keep_alive`；
- `size`：min 1；max = `applyHardSizeLimit`（`ExecutorBuilder.java:42-53`）——`write`/`write_coordination`/`system_write`/`system_write_coordination`/`system_critical_write` 硬限 **1+p**，其余 `Integer.MAX_VALUE`。

即：可以调大任何池的 size，但写类池超过核数会被拒绝（防止写并发超过分片串行化能力带来无谓的上下文切换）。

## 背压的两条独立路径

线程池队列之外，ES 还有一条**与线程池完全无关**的背压：传输层断路器。

`network.breaker.inflight_requests`（limit 100%、overhead 2.0，`HierarchyCircuitBreakerService.java:125-137`）的申请**不在任何 ES 线程池里**，而在 netty IO 线程同步进行：

- 传输层：`InboundAggregator.java:208-225` 按请求体 `contentLength` 调 `addEstimateBytesAndMaybeBreak`，随 message close 链释放（`:227-244`）；
- HTTP 层：`RestController.java:564-572` 同样在入口申请。

设计含义：大请求（深聚合、大 bulk）在**读入字节时**就被拒，不会占用任何线程池资源——这与「线程池队列满」是两道独立的闸门，排 429/资源问题时需要分别确认是哪一道。

## 诊断与关闭

- `_tasks`（`RestListTasksAction.java:44-47`）列出注册任务；**只有 `CancellableTask` 子类可取消**（`BulkRequest`、`SearchTask`、`ReplicationTask` 等，`TaskManager.java:168-177`），普通任务只能观察；
- search slow log：`index.search.slowlog.threshold.query/fetch.{warn,info,debug,trace}` 共 8 个设置，**默认全 -1（禁用）**（`server/.../index/SearchSlowLog.java:58-113`）。不存在 6.x 的单值 `threshold.query`；
- 优雅关闭顺序（`Node.java:463-606`）：先停 HTTP/快照/coordinator/transport，**IndicesService 最后停**（`:501-503` 注释：要等 scroll searcher、recovery 等资源释放），线程池用平滑 `shutdown()`，`awaitClose(timeout)` 超时才 `shutdownNow()`（`:624-632`，注释引用 LUCENE-7248：立即 shutdown 可能破坏进行中的 Lucene 操作）。

## 陷阱清单

| 说法 / 做法 | 9.5.5 真相 |
| ---- | ---- |
| `listener`/`bulk`/`index`/`percolate`/`suggest`/`search_throttled` 池 | 全部不存在（`ThreadPool.Names` 无匹配） |
| 队列满是 caller-runs / 无界等待 | 有界 fixed 池 `EsAbortPolicy` 直接抛 → 429；scaling 池才实际不拒绝 |
| search reduce 用 search 池 | 协调/reduce 用 `search_coordination`；`search` 只跑数据节点 query/fetch |
| bulk 429 = write 队列满 | write 队列 max(750p,10000)；先查 indexing pressure 与 inflight breaker |
| `thread_pool.*.queue_size` 有校验范围 | 无 min/max；有硬限的是 `size`（write 类 ≤ 1+p） |
| inflight breaker 在线程池里申请 | 在 netty IO 线程/HTTP 入口按字节数申请，与线程池独立 |
| `index.search.slowlog.threshold.query: 10s` | 只有 warn/info/debug/trace 四级且默认全 -1 |
| 调大 `write` 池提升写吞吐 | 写串行化在分片级；写类池 size 硬限 1+p，超过被拒 |

## Links

- [Elasticsearch（枢纽页）](/docs/CS/Framework/ES/ES.md)
- [Replication：写入与复制协议](/docs/CS/Framework/ES/Replication.md)
- [Search Internals：搜索内部机制](/docs/CS/Framework/ES/Search_Internals.md)
- [Merge：段合并与 store](/docs/CS/Framework/ES/Merge.md)
- [Troubleshooting：排障](/docs/CS/Framework/ES/Troubleshooting.md)

## References

1. [Elasticsearch Reference - Thread Pool settings](https://www.elastic.co/guide/en/elasticsearch/reference/current/modules-threadpool.html)
2. [elastic/elasticsearch v9.5.5 源码](https://github.com/elastic/elasticsearch/tree/v9.5.5)
