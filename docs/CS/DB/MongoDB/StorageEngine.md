## Introduction

WiredTiger 自 3.2 起是 MongoDB 的默认存储引擎，4.2 之后 MMAPv1 被彻底移除，它成了唯一的生产选择（企业版另有 in-memory 与 encrypted 引擎）。它的几个设计选择直接塑造了 MongoDB 的行为：**文档级并发**、**更新不做原地修改**、**checkpoint + journal 双保险**、**索引与数据都是 B-tree**。

## On-Disk Layout

一个 `dbPath` 下的关键文件：

```text
WiredTiger              连接级元数据
WiredTiger.turtle       引擎元数据（版本、checkpoint 列表）
WiredTiger.wt           metadata 表
collection-*.wt         集合数据文件
index-*.wt              索引文件
journal/WiredTigerLog.* 预写日志
diagnostic.data/        FTDC 指标（MongoDB 层）
```

每个集合与每个索引各有独立的 B-tree 文件。MongoDB 的命名空间、集合选项、索引定义存在 WiredTiger 的 metadata 表里，`_mdb_catalog` 不是独立文件。

## Write Path

一次更新不会在原页上改字节，而是：

1. 在缓存中找到目标文档，生成新的 **WT_UPDATE** 版本，挂到该键的更新链上；
2. 写 journal（默认每 100ms 刷盘一次，文件约 100MB 轮转）；
3. 脏页由淘汰线程在后台做 **reconciliation**：把更新链合并成新的页镜像，压缩后写回磁盘；
4. 每 60 秒做一次 **checkpoint**：把所有文件的快照一致落盘，更新 `WiredTiger.turtle` 的 checkpoint 列表；
5. 崩溃恢复时从最近一个有效 checkpoint 开始，用 journal 重放其后的修改。

因此 MongoDB 的持久化语义是"journal 落盘即持久"，而不是"checkpoint 落盘才持久"。`j: true` 控制的就是 journal 的刷盘确认。

更新链意味着**同一文档的并发写会串行化**：后到的写检测到冲突会返回 `WriteConflict`，由事务层重试。

## Read Path and Concurrency

读路径不需要加读锁：

- 读操作取一个快照（snapshot），在快照可见的版本上读；
- 页面被读取时用 **hazard pointer** 钉住，保证淘汰线程不会在读取期间回收它；
- 缓存未命中时从磁盘读页、解压、放入 cache；
- 读到的文档版本由快照与事务时间戳决定，不会被并发写撕裂。

这带来"读不阻塞写、写不阻塞读"的特性，也是 MongoDB 单文档原子性的基础：一篇文档的所有字段更新作为一个版本链节点提交。

`BLink-Tree` 里对比过 WiredTiger 与其它 B-tree 变体的差异：它的读路径依赖 hazard pointer 与页级 latch 的配合，而非全局读写锁。

## Cache and Eviction

WiredTiger 内部缓存默认 **50% × (RAM − 1GB)**，且不低于 256MB。缓存里存的是解压后的 B-tree 页，磁盘上是压缩页，操作系统的 page cache 还会缓存压缩页。

淘汰机制：

- 缓存使用率达到 **80%** 时淘汰线程开始工作；
- 接近 **95%** 时应用线程也被拉进来做淘汰，表现为请求延迟抖动；
- 脏页比例有更激进的阈值，避免 checkpoint 时集中刷盘；
- 淘汰不是 LRU 逐出，而是先 reconciliation 把脏页写成新页，再释放旧页。

这解释了两个常见现象：**工作集超过缓存后延迟上升但不报错**；**写入突增时出现周期性卡顿**（应用线程参与淘汰 + checkpoint）。

## Compression

| 对象 | 默认压缩 | 可选 |
| :--- | :--- | :--- |
| 集合数据 | snappy 块压缩 | zstd、zlib、none |
| 索引 | 前缀压缩 | 可关闭 |
| journal | snappy | 可配置 |
| 时间序列集合 | zstd（列式桶） | |

块压缩以 CPU 换磁盘与 IO：zstd 压缩率更高但更耗 CPU，snappy 是默认平衡点。索引的前缀压缩对长字符串键收益明显。

## Transactions and Timestamps

WiredTiger 本身提供带时间戳的 MVCC，MongoDB 在其上实现：

- 每次写分配一个 **cluster time**（逻辑时间，混合物理时钟与计数器）；
- 副本集多数派确认后推进 **majority commit point**；
- `readConcern: "majority"` 只返回在 majority commit point 之前的数据；
- 多文档事务在提交时统一分配提交时间戳，使所有修改原子可见。

存储层只负责"按时间戳存版本"，跨节点的一致性由复制层负责，见 [Replication](/docs/CS/DB/MongoDB/Replication.md) 与 [Transaction](/docs/CS/DB/MongoDB/Transaction.md)。

## Collections, Indexes, and Clustered Storage

- 普通集合：`_id` 是唯一索引，文档按记录 ID 存放，`_id` 与物理位置无强关联。
- **聚簇集合**（5.3+）：文档按 `_id` 顺序物理存放，范围扫描与 `_id` 点查更快；一个集合只能有一个聚簇索引，且创建后不可更改。
- 索引：独立 B-tree，叶子指向记录 ID；多键索引为数组元素展开多条键。
- 时间序列集合：底层是列式分桶存储，9.0 起改为单一命名空间内的桶存储，不再是"可写非物化视图"。

## Operational Knobs

| 参数 | 作用 |
| :--- | :--- |
| `storage.wiredTiger.engineConfig.cacheSizeGB` | 内部缓存大小 |
| `storage.journal.commitIntervalMs` | journal 刷盘间隔，默认 100ms |
| `storage.wiredTiger.collectionConfig.blockCompressor` | 集合压缩算法 |
| `storage.wiredTiger.indexConfig.prefixCompression` | 索引前缀压缩开关 |
| `storage.wiredTiger.engineConfig.directoryForIndexes` | 索引与数据分目录存放 |

调优经验：不要为了"多用内存"把 cache 调到接近总内存，操作系统 page cache 同样重要；容器环境必须显式设置 cache 上限，否则按宿主机内存计算会 OOM。

## Links

- [MongoDB](/docs/CS/DB/MongoDB/MongoDB.md)
- [Architecture](/docs/CS/DB/MongoDB/Architecture.md)
- [Transaction](/docs/CS/DB/MongoDB/Transaction.md)
- [Replication](/docs/CS/DB/MongoDB/Replication.md)
- [WAL](/docs/CS/DB/Concept/WAL.md)
- [BLink-Tree](/docs/CS/DB/Concept/BLink-Tree.md)

## References

- [WiredTiger Storage Engine](https://www.mongodb.com/docs/manual/core/wiredtiger/)
- [Journaling](https://www.mongodb.com/docs/manual/core/journaling/)
- [WiredTiger Cache Tuning](https://source.wiredtiger.com/develop/tune_cache.html)
- [MongoDB Storage Engines](https://www.mongodb.com/docs/manual/core/storage-engines/)
