## Introduction

HBase 的读路径是「内存 + 若干不可变文件」的归并：MemStore 与各 HFile 借索引与 Bloom 跳过无关文件，再按时间戳与 tombstone 归并。本页覆盖读放大来源、Bloom filter、BlockCache 两种实现（Lru / Bucket / Combined）、scanner caching 与超时重试，以及列族数量对读的连锁影响。写路径与 compaction 见 [Write Path](/docs/CS/DB/HBase/Write_Path.md) 与 [Compaction](/docs/CS/DB/HBase/Compaction.md)。

## Read Path and Caching

一次 Get 要问的地方是「内存 + 若干不可变文件」：MemStore → 各 HFile（借索引与 Bloom 跳过），再按时间戳与删除标记归并。所以**读放大 = 未合并的 HFile 数**，compaction 策略直接决定 P99。

- **Bloom filter** 默认列族级开启 `ROW`（按行判断该不该扫这个文件），按列访问的表可设 `ROWCOL`。索引块有 interleaved 与 compound 两种布局，compound 更省内存且可缓存，配 `hfile.block.bloom.cacheonwrite`（默认 `false`）在写 HFile 时就把 Bloom 块塞进缓存。
- **BlockCache** 缓存 HFile 数据块与索引，`hfile.block.cache.size` 默认 **0.4（40% 最大堆）**，官方要求「至少能装下 storefile 索引」，设 0 关掉的后果是索引读全打 HDFS。堆大时可换/叠加 **off-heap BucketCache**（需显式配置，默认不启用），目的是把缓存从 GC 的爆炸半径里拿出来。
- **扫描** 靠 `hbase.client.scanner.caching` 决定一次 RPC 取多少行、`hbase.client.scanner.timeout.period`（默认 60000 ms）是 RegionServer 侧 scanner 的租约，长扫描必须 `setCaching` 否则租约到期重来。
- **超时与重试**：`hbase.rpc.timeout` 默认 60000 ms 限单次 RPC，`hbase.client.operation.timeout` 默认 1200000 ms 限整个阻塞操作，其下按 `hbase.client.pause`（默认 100 ms）退避重试，上限 `hbase.client.retries.number` = **15**。

> [!NOTE]
> 两处手册与源码不一致，写调优文档时以源码为准：① `hbase.client.scanner.caching` 的正文叙述仍写「默认 100」，但 `HConstants.DEFAULT_HBASE_CLIENT_SCANNER_CACHING` 在 branch-2.4/2.6/3.0 里都是 `Integer.MAX_VALUE`；② 版本号取 Maven Central 的 release，不要照抄 `book.html`——它当前是 4.0.0-alpha-1-SNAPSHOT。这正是「官方文档可能过时于源码」的教科书例子：**判断默认值要读常量定义，不是读说明文字**。

**列族数量影响读**：不同列族物理分离，一次跨列族读要走多组文件，写则共享一次 WAL。所以列族要少（常见 1~3 个），把「总是一起取出的列」放同一列族，把「访问模式/生命周期/TTL 不同」的列拆开。把列族当宽表列数玩（几十上百个列族）会同时恶化 MemStore 内存、文件数和扫描成本。

## BlockCache

读路径要问的地方是「内存 + 若干不可变文件」。BlockCache 就是缓存这些 HFile 数据块 / 索引块的那层，决定 P99 读延迟的下限。HBase 提供两种实现，2.0 起不再用「L1/L2」这种说法：

| 实现 | 位置 | 角色 |
| :--- | :--- | :--- |
| `LruBlockCache` | JVM 堆内（on-heap） | 原始实现，三段优先级 LRU（single / multi / in-memory）；catalog 表等 `IN_MEMORY` 列族走最高优先级，最后才被逐出 |
| `BucketCache` | 通常堆外（off-heap），也支持 heap / file(mmap) / pmem | 主要把 DATA 块搬出堆，避免 GC 爆炸半径；固定大小 bucket，空间不足可从其它 bucket 借，利用率高于被废弃的 SlabCache |
| `CombinedBlockCache` | — | BucketCache 启用时的**两层编排**：DATA 块放 BucketCache，**INDEX / BLOOM 块留在 LruBlockCache**。一次随机读要先在 Lru 找到 index、再去 Bucket 取 data |

> [!WARNING]
> `SlabCache` 在 0.98 之后已不建议使用——它固定大小内存导致实际利用率低，且仍受 LRU 在堆内 GC 碎片之苦。不要在新集群上配它。`BucketCache` 走堆外时，`-XX:MaxDirectMemorySize` 必须比 `hbase.bucketcache.size` 大，否则堆外内存申请会失败。

配置面：`hfile.block.cache.size`（默认 **0.4**，即 40% 最大堆，是 Lru 的份额；设 0 则索引读全打 HDFS）、`hbase.bucketcache.ioengine`（offheap / file / heap）、`hbase.bucketcache.size`、`hbase.bucketcache.combinedcache.enabled`。计算可用缓存总量：`RS 数 × 堆大小 × hfile.block.cache.size × 0.99`（最后 0.99 是 LRU 的 evict 触发负载因子）。堆大、数据集远超内存时，还可开 `hbase.block.data.cachecompressed`（HBASE-11331，压缩态缓存；SNAPPY 下吞吐 +50%、均值延迟 -30%，但 GC +80%、CPU +2%）——**默认关闭**，对能装进缓存的小数据集收益有限。

## Links

- [HBase](/docs/CS/DB/HBase/HBase.md)
- [Write Path](/docs/CS/DB/HBase/Write_Path.md)
- [Compaction](/docs/CS/DB/HBase/Compaction.md)
- [LSM Tree](/docs/CS/Algorithms/tree/LSM.md)

## References

1. [Apache HBase Reference Guide](https://hbase.apache.org/book.html)
2. [Apache HBase RegionServer (BlockCache)](https://hbase.apache.org/docs/architecture/regionserver/)
