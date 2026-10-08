## Introduction

Apache HBase 是构建在 [HDFS](/docs/CS/Framework/Hadoop/HDFS.md) 之上的开源分布式**宽表（column-family）NoSQL 数据库**，补齐的是 Hadoop 生态里「海量数据的**低延迟随机读写**」这一格：Hive 走 [MapReduce](/docs/CS/Framework/Hadoop/MapReduce.md) 做高延迟离线分析，HBase 提供在线点查与按 RowKey 的范围扫描。

它是 Google [Bigtable](/docs/CS/Distributed/Bigtable.md) 论文的开源实现，组件一一对应：GFS → HDFS，Chubby（锁与协调）→ [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)，Master / Tablet Server → HMaster / HRegionServer，Tablet → Region。存储引擎侧它与 LevelDB、RocksDB、Cassandra 同属 **LSM 谱系**（见 [LSM Tree](/docs/CS/Algorithms/tree/LSM.md)）。

> [!NOTE]
> 版本口径：Maven Central 上 `org.apache.hbase:hbase` 的 release 已到 **3.0.0**（2.x 线仍在维护，2.6 系列已到 2.6.7），但生产集群以 2.x 为主体。两代在**客户端依赖**与**部分默认值**上不同，本页凡涉及具体默认值均以源码常量标注所属分支，不以手册正文为准——官方 `book.html` 当前是 4.0.0-alpha-1-SNAPSHOT 的开发版文档，正文数字存在滞后（下文 `hbase.client.scanner.caching` 就是一例）。

## Data Model

HBase 的数据模型是稀疏、多维、有序的 map，逻辑坐标即 `Map<RowKey, Map<ColumnFamily, Map<Qualifier, Map<Timestamp, Value>>>>`：

- **Row（行）**：以 **RowKey** 唯一标识，表内所有行按 RowKey **字典序全局有序**存储。这是 HBase 最重要的性质——它同时是范围扫描快的原因、二级索引弱的根因，以及 RowKey 设计成为核心课题的由来。
- **Column Family（列族）**：建表时预定义，数量少且固定（如 `info`、`addr`）。**物理上一个列族就是一个 Store、一组独立文件**，因此列族划分就是物理布局划分。
- **Column Qualifier（列限定符）**：列族下的列，**无需预定义、可动态增减**，空列不占空间，所以表是稀疏的。
- **Timestamp / Version**：每个 cell 按时间戳保留多版本，列族默认 `VERSIONS => 1`。
- **Cell**：由 `(rowkey, column family, qualifier, timestamp)` 定位，值是无类型 `byte[]`。

列族（column family）不等于列式存储（column store）。宽表把「同一行、同一列族」的数据存在一起，面向按行取；OLAP 列存把「同一列、跨行」的值压缩在一起，面向扫描聚合。两者的取舍见下文 Comparison 一节，混用这两个概念是最常见的表述错误。

建表时的列族默认值（`ColumnFamilyDescriptorBuilder`，branch-2.6 与 branch-3.0 一致）：

| 属性 | 默认值 | 含义与代价 |
| :--- | :--- | :--- |
| `BLOOMFILTER` | `ROW` | 默认就开行级 Bloom，不是关闭 |
| `BLOCKSIZE` | `65536`（64 KB） | HFile 块大小，决定读粒度与索引开销 |
| `DATA_BLOCK_ENCODING` | `NONE` | 3.0 的枚举为 `NONE/PREFIX/DIFF/FAST_DIFF`，2.6 还含 `PREFIX_TREE`（3.0 已移除） |
| `COMPRESSION` | `NONE` | 生产上几乎必改 SNAPPY/ZSTD |
| `VERSIONS` | `1` | 多版本直接放大读路径要扫的文件数 |
| `IN_MEMORY` | `false` | 仅对极少数量小的元数据表有意义 |
| `IS_MOB` / `MOB_THRESHOLD` | `false` / `102400`（100 KB） | 见下 |

**值的大小**：HBase 常规读写路径为**小于 100 KB 的 value** 优化。存图片、文档这类中等对象应开 MOB（`IS_MOB => true`），让大 value 落到独立的 MobFile，避免把 HFile 与索引撑爆——把 10 MB 的 cell 塞进普通列族，等于让 BlockCache 和 compaction 陪葬。

## Architecture

- **HMaster**：管元数据与调度（建表/删表、列族变更、Region 分配与迁移、负载均衡），**不参与实际数据读写**，所以 Master 宕机不影响在线读写，只短时影响管理操作。
- **HRegionServer**：工作节点，服务多个 Region，承接客户端读写、flush、compaction、WAL。
- **Region**：一张表按 RowKey 范围水平切分成多个 Region，是分布式与负载均衡的单位；一个 Region 内按列族拆成多个 **Store**，每个 Store = MemStore + 若干 HFile。
- **hbase:meta**：系统表，记录「哪个 RowKey 落在哪个 RegionServer 的哪个 Region」，客户端查一次后在本地缓存路由。
- **分裂由 RegionServer 自己完成**，Master 不参与：RS 把父 Region 下线、一分为二、在**父 Region 所在节点**打开两个子 Region 并写回 `hbase:meta`，最后才向 Master 上报。也就是说分裂是本地事件，代价是一次短暂的 region offline。
- **Region 数量要克制**：官方建议单表/单集群维持「少量大 Region」——20~200 个、每个 5~20 GB，实践中**约 100 个 Region / RegionServer** 效果最好。原因很硬：MSLAB 每个 MemStore 预留 2 MB 堆内缓冲，1000 个 Region × 2 个列族 ≈ 3.9 GB 堆还没装数据。
- **自动治理**：`hbase.normalizer.period`（默认 300000 ms）由 `hbase.normalizer.split.enabled` / `hbase.normalizer.merge.enabled`（均默认 `true`）控制，Master 周期性拆分过小 / 合并过大的相邻 Region。

```
Client --(2.x: 读 ZK 定位 meta / 3.0+: RPC 问 Master)--> hbase:meta --> HRegionServer
HRegionServer -> Region -> Store(per CF) -> MemStore + HFile
持久化 -> HDFS(HFile, WAL)；协调与选举 -> ZooKeeper；元数据与调度 -> HMaster
```

> [!WARNING]
> **客户端与 ZooKeeper 的关系在 3.0.0 变了**。2.x 默认以 ZooKeeper 为事实来源，客户端启动前必须知道 `hbase.zookeeper.quorum`，靠读 znode 拿 Master 地址与 meta 位置。**3.0.0 起默认连接注册方式（connection registry，2.5.0 引入）改为 RPC 实现**：客户端改为联系 Master 的 RPC 端点，配置项换成 `hbase.masters`，ZooKeeper 退化为集群内部依赖。把「HBase 客户端必须能访问 ZK」当恒真命题写进设计文档，在 3.x 上是错的。

## RowKey Design

RowKey 是 HBase 唯一的查询主键，也是唯一的分区键，三件事同时压在这一个字段上：分布是否均匀、前缀扫描是否可用、能否定位到单 Region。

**热点（hotspotting）** 是头号故障模式：大量读写集中打到某一个 Region（进而某一个节点），该 Region 成为瓶颈甚至不可用，同时拖垮同机其它 Region。典型成因是**单调递增 RowKey**——用时间戳或自增 ID 打头时，一整批写入的 key 全落在最后一个 Region 上；导入进程还会步调一致地把当前 Region 打满再整体移到下一个，集群里其余节点全程闲置。

官方给出的四类缓解手段：

| 手法 | 做法 | 代价 |
| :--- | :--- | :--- |
| **Salting** | 在 key 前加随机/散列前缀，前缀取值数对应希望打散的 Region 数 | 彻底打乱语义顺序，读时必须显式带上前缀或全扫 N 份，无法前缀扫描 |
| **哈希 / 取反** | 用 `Hash(key)` 或固定长度摘要做前缀（如按天聚合时用「实体 + `Long.MAX_VALUE - ts`」让最新数据排在前面） | 仍是散列分区，牺牲范围查询；与 [分区策略](/docs/CS/Distributed/Partition.md)里哈希分区的取舍同源 |
| **复合前缀** | 把基数高、天然均匀的字段（用户 ID、设备 ID）拼在前面，时间戳放后面 | 需要按查询模式设计，拼错等于把热点搬到另一个字段 |
| **预分裂 presplitting** | 建表时给出显式分裂点或按均匀分布预分裂，空表就有多个 Region | 要求事先知道 key 分布；否则只是把空 Region 摊平 |

其它约束：

- **长度**：RowKey 是 `byte[]`，会被复制进 meta、Bloom filter、每个 KV 的 key。业务上「越短越好」，定长优于变长，能用 `long`/`int` 二进制就别用字符串。
- **不可更新**：改 RowKey 只能「读旧行 → 写新行 → 删旧行」，删掉的行只留 tombstone，要等 major compaction 才真正消失，所以高频改主键的场景本身就不该用 HBase。
- **二级索引**：HBase 自身不提供。补偿办法是三类——① 用 Phoenix（或 Trafodion）在表上建**全局 / 本地索引**，把索引写成另一张 HBase 表；② 自建**异构索引表**，索引表 RowKey 用查询维度、value 存主表 RowKey，写入时双写或用 Coprocessor / [canal](/docs/CS/DB/canal.md) 异步同步；③ 把非主键维度倒排到 [Elasticsearch](/docs/CS/Framework/ES/ES.md)，ES 出 RowKey、HBase 取明细。三类都逃不过索引与主数据的一致性维护。

## Write Path and Compaction

写路径（LSM 的写优化本质）：

1. 先顺序追加 **WAL**（HLog，落在 HDFS）保证宕机可回放；
2. 再写入内存中按 key 有序的 **MemStore**，写请求即返回；
3. Region 的 MemStore 达到 `hbase.hregion.memstore.flush.size`（默认 128 MB）后 **flush 成不可变 HFile**；
4. Store 里 HFile 数达到 `hbase.hstore.compactionThreshold`（默认 **3**）触发 **minor compaction**，单次最多合并 `hbase.hstore.compaction.max`（默认 **10**）个文件，扫描批大小 `hbase.hstore.compaction.kv.max` 默认 10；
5. **major compaction** 把一个 Store 的文件合成一个，并清除删除标记与过期版本，默认周期 `hbase.hregion.majorcompaction` = **604800000 ms，即 7 天**（配 `hbase.hregion.majorcompaction.jitter` = 0.50 打散，避免全体同时开跑）。

> [!WARNING]
> 「HBase 默认一天一次 major compaction」是流传很久的旧事实。`hbase.hregion.majorcompaction` 的默认值在 **branch-2.4、branch-2.6、branch-3.0 三处源码里都是 7 天**，要按业务低峰控制节奏就把周期项设为 0 关掉自动触发、改用外部 cron 或 `major_compact` 手工调度。

写侧的背压与保护：

- 同一个 Store 的 HFile 数超过 `hbase.hstore.blockingStoreFiles`（默认 **16**）就**阻塞该 Region 的更新**，直到 compaction 追上来或超过 `hbase.hstore.blockingWaitTime`（默认 90000 ms）后自行解除。写入突然卡住，先看这个。
- MemStore 涨到 `hbase.hregion.memstore.block.multiplier`（默认 **4**）× flush 阈值时同样阻塞更新；全局 MemStore 上限 `hbase.regionserver.global.memstore.size` 默认 **0.4（40% 堆）**，撞到就强制 flush 并阻塞。
- compaction 本身被限速：默认的 `PressureAwareCompactionThroughputController` 在忙时把总吞吐压到 `hbase.hstore.compaction.throughput.lower.bound`（默认 50 MB/s）。
- **删除 = 写 tombstone**，不立即抹除，只在 major compaction 时真正清除。大量删除或大量过期版本会让读路径反复跳过墓碑，因此「先大删再查」的性能塌方是结构性的（与 [Lucene 段合并的删除标记](/docs/CS/Framework/ES/Lucene.md)同源，都是不可变文件 + 后台合并）。
- 批量写入用 **BufferedMutator**（旧 `HTable` 的 `setAutoFlush(false)` + `write buffer`），攒够再一次 RPC；`hbase.client.write.buffer` 是它的默认缓冲大小（2 MB）。
- **WAL 可以按 Mutation 跳过**：`Mutation.setDurability(Durability.SKIP_WAL)`，枚举取值为 `USE_DEFAULT / SKIP_WAL / ASYNC_WAL / SYNC_WAL / FSYNC_WAL`。但**没有「按表关闭 WAL」的开关**，且官方明确警告：除批量导入外关 WAL 就是拿数据换吞吐，RegionServer 崩了这段数据永久丢失。

## Read Path and Caching

一次 Get 要问的地方是「内存 + 若干不可变文件」：MemStore → 各 HFile（借索引与 Bloom 跳过），再按时间戳与删除标记归并。所以**读放大 = 未合并的 HFile 数**，compaction 策略直接决定 P99。

- **Bloom filter** 默认列族级开启 `ROW`（按行判断该不该扫这个文件），按列访问的表可设 `ROWCOL`。索引块有 interleaved 与 compound 两种布局，compound 更省内存且可缓存，配 `hfile.block.bloom.cacheonwrite`（默认 `false`）在写 HFile 时就把 Bloom 块塞进缓存。
- **BlockCache** 缓存 HFile 数据块与索引，`hfile.block.cache.size` 默认 **0.4（40% 最大堆）**，官方要求「至少能装下 storefile 索引」，设 0 关掉的后果是索引读全打 HDFS。堆大时可换/叠加 **off-heap BucketCache**（需显式配置，默认不启用），目的是把缓存从 GC 的爆炸半径里拿出来。
- **扫描** 靠 `hbase.client.scanner.caching` 决定一次 RPC 取多少行、`hbase.client.scanner.timeout.period`（默认 60000 ms）是 RegionServer 侧 scanner 的租约，长扫描必须 `setCaching` 否则租约到期重来。
- **超时与重试**：`hbase.rpc.timeout` 默认 60000 ms 限单次 RPC，`hbase.client.operation.timeout` 默认 1200000 ms 限整个阻塞操作，其下按 `hbase.client.pause`（默认 100 ms）退避重试，上限 `hbase.client.retries.number` = **15**。

> [!NOTE]
> 两处手册与源码不一致，写调优文档时以源码为准：① `hbase.client.scanner.caching` 的正文叙述仍写「默认 100」，但 `HConstants.DEFAULT_HBASE_CLIENT_SCANNER_CACHING` 在 branch-2.4/2.6/3.0 里都是 `Integer.MAX_VALUE`；② 版本号取 Maven Central 的 release，不要照抄 `book.html`——它当前是 4.0.0-alpha-1-SNAPSHOT。这正是「官方文档可能过时于源码」的教科书例子：**判断默认值要读常量定义，不是读说明文字**。

**列族数量影响读**：不同列族物理分离，一次跨列族读要走多组文件，写则共享一次 WAL。所以列族要少（常见 1~3 个），把「总是一起取出的列」放同一列族，把「访问模式/生命周期/TTL 不同」的列拆开。把列族当宽表列数玩（几十上百个列族）会同时恶化 MemStore 内存、文件数和扫描成本。

## Region Splitting and Merge

默认分裂策略 `SteppingSplitPolicy` 的源码语义很能说明设计意图：当这个 RegionServer 上该表**只有一个 Region** 时，用 2× MemStore flush 阈值判定分裂，否则退回 `hbase.hregion.max.filesize`（10 GB）——让新表能快速铺开到集群，又不会一下子生成一堆小 Region。配合 `hbase.regionserver.regionSplitLimit`（默认 1000）为 RS 级分裂上限。

`hbase.hregion.max.filesize` 的两种判定方式：任一 Store 超限即分裂，或整个 Region 的文件求和超限（`hbase.hregion.split.overallfiles`，默认 `true`）。策略可换，全部挂在 `hbase.regionserver.regionSplitPolicy` 下：

| 策略 | 语义 |
| :--- | :--- |
| `SteppingSplitPolicy` | **默认**，见上 |
| `ConstantSizeRegionSplitPolicy` | 固定阈值，到点就切，Region 少时切得太早 |
| `IncreasingToUpperBoundRegionSplitPolicy` | 阈值随 RS 上的 Region 数递增，1.x 时代默认 |
| `KeyPrefixRegionSplitPolicy` | 按 RowKey 前缀长度切，保证同前缀的数据不劈进两个 Region——与 RowKey 前缀设计配套 |
| `DelimitedKeyPrefixRegionSplitPolicy` | 在指定分隔符处切，适合「实体:子键」型 key |
| `BusyRegionSplitPolicy` | 按繁忙度切热点 Region，配合热点治理 |
| `DisabledRegionSplitPolicy` | 关闭自动分裂，**且连手工分裂也一并拦下** |

分裂流程见上文 Architecture 一节：RS 本地完成、子 Region 先开在父 Region 所在节点、写回 `hbase:meta` 后才上报 Master。反方向的**在线合并**（`merge_region`）用来收拾预分裂过碎或删除导致的碎 Region，由 RegionNormalizer 自动化（见 Architecture 一节）。

## In Memory Compaction

**Accordion**，2.0 引入：把 LSM 的合并思想搬进 MemStore，数据还在 RAM 时就消除冗余版本与重复，从而降低 flush 频次、写放大和磁盘足迹。它是列族属性 `IN_MEMORY_COMPACTION`，四个取值：

| 取值 | 行为 |
| :--- | :--- |
| `NONE` | 不做内存合并（默认） |
| `BASIC` | 维护 flush 管道到阈值再落盘；不做真合并，但把数据从 `ConcurrentSkipListMap` 挪进更紧凑的内存结构，吞吐受益 |
| `EAGER` | BASIC 之上真正执行内存合并，套用与 HFile 相同的规则清版本/重复/TTL 过期 |
| `ADAPTIVE` | 按数据里重复 cell 的占比自适应选择索引压缩或数据压缩；**实验性** |

系统表的 memstore 官方建议直接设 `BASIC` / `EAGER`。同一条线上的配套变化：2.0 起 MSLAB 的 chunk pool 默认开启（`hbase.hregion.memstore.chunkpool.maxsize` 默认 1.0，此前为 0.0，即 on-heap MemStore 不用 chunk pool）。

## WAL and MultiWAL

WAL 有三种 provider：`asyncfs`（默认，日志里能看到 `AsyncFSWALProvider`）、`filesystem`、`multiwal`——最后一个由多个 asyncfs / filesystem 实例组成，用多管道摊薄单个 WAL 的写入串行化。WAL 压缩默认关闭（`hbase.regionserver.wal.enablecompression` 默认 `false`），开启后 tag 压缩随之启用。同一个 RegionServer 的并发写汇入同一条 WAL 管道顺序追加，故障恢复时按 Region 重放，这就是「已确认的写」在 RS 崩溃后仍可见的机制来源（见下文 Consistency and Transactions 一节）。

另有一条容易漏的时间线：**2.4.0 为 `hbase:meta` 表引入了异步 WAL 复制**，让 meta 自身的可用性方案与普通表对齐（3.0 延续）。

## Coprocessors

Coprocessor 把用户代码注入 RegionServer / Master 进程，分两类：

- **Observer**：钩子。拦截读写、flush、compaction、WAL、Master 管理操作等事件点（`RegionObserver` / `RegionServerObserver` / `MasterObserver` / `WALObserver`），用于权限校验、二级索引维护、行级安全这类「随写随做」的逻辑。
- **Endpoint**：自定义 RPC 服务。客户端把聚合计算下推到数据所在节点执行，避免把全表拉回客户端。

装载点在 `hbase.coprocessor.region.classes`（「region observer 或 endpoint，默认加载到所有表，按声明顺序调用」）与 `hbase.coprocessor.master.classes` 等，另有表级/列族级属性。

> [!WARNING]
> 两个版本断点：**2.0 起**只实现 `RegionObserver` 不再足够——必须同时实现 `RegionCoprocessor` 并提供 `getRegionObserver()` 返回自身；**3.0 移除了 `hbase-protocol` 模块**，旧 Coprocessor Endpoint 的 protobuf 依赖随之断掉，升级前要重编译。Phoenix 的二级索引维护与查询下推正是构建在这套机制之上。

## Cluster Replication

跨集群复制把源集群 WAL 中的编辑**异步**投递到 peer 集群，开关在列族级：`REPLICATION_SCOPE`（默认 `0` 关闭，设正整数开启）。它是**最终一致**的，主备之间存在可见性延迟；「写入顺序」在复制场景是正确性问题——官方明确建议开复制就用**串行复制**（HBASE-9465，2.0 之后进入 2.x），保证 Mutation 按提交顺序到达 peer。

典型用途是异地容灾、就近读与双活写入。它和前文 Region 副本的「Async WAL Replication」不是一回事：后者是**集群内**把主 Region 的写同步给同数据的副本 Region（数据文件共享、无额外存储），前者是**跨集群**的数据分发。

## Security and Quotas

- **认证**：集群对接 Kerberos；2.x 起授权开关 `hbase.security.authorization` **默认为 `false`**，只开认证不开授权时所有用户实际都是 superuser。
- **两层授权**：表/列族/列级 ACL 管「能不能读这张表」；cell 级 **Visibility Labels** 管「这个 cell 谁能看」（如打上 `top-secret` 标签、只授予特定组）。labels 的实现依赖 HFile v3 的 per-cell **Tags**——这也是下文 HFile Format 一节把 v3 当作 2.0+ 分水岭的原因。
- **配额**：`hbase.quota.enabled` 默认关闭，开启后可按用户/表/namespace 做 `THROTTLE`（区分 READ / WRITE 或合计），限流粒度到 sec / min / hour / day。
- **多租户**：namespace 隔离表组，配 ACL 与配额构成租户边界。

## HFile Format

HFile 是 LSM 在 HDFS 上的落地文件格式，血统可查：源自 Bigtable 论文的 SSTable 设计与 Hadoop 的 TFile。版本演进里两条硬事实：**v2 于 0.92 引入**（inline blocks）；**2.0+ 只能写 v3，v2 只读不写**，升级时若 `hbase-site.xml` 里残留 `hfile.format.version=2` 会导致 RegionServer 起不来。

v3 的关键增量是 **per-cell Tags**：每个 cell 可以挂任意 tag（cell 级 TTL、visibility labels、MOB 引用都靠它）。格式本身与 Data Model 一节的默认值互为表里：`BLOCKSIZE` 决定数据块粒度与索引开销，块级压缩（`COMPRESSION`）与 KV 前缀编码（`DATA_BLOCK_ENCODING`）是两个正交的层，前者压 value、后者压相邻 key 的重复前缀。排查时可用 `hbase hfile` 把文件内容文本化。

## Operations and Repair Tools

- **HBCK1 只读化**：自 2.0 起 `hbck` 是只读诊断工具，它读不懂 hbase2 的内部状态，修复必须换 **HBCK2**（独立发布的 operator 工具集）。
- **HBCK Report**：Master UI 上的不一致报告自 2.0.6 / 2.1.6 / 2.2.1 起可用，定位孤儿目录等状态。
- 修复动作前先跑 CatalogJanitor（shell `catalogjanitor_run`）确认 `hbase:meta` 本身健康——meta 不健康时一切「修复」都是在放大损坏。

## Version Notes

2.x 为主体、3.0 开始铺开的当下，本页涉及的版本断点汇总：

| 事项 | 2.x | 3.0 |
| :--- | :--- | :--- |
| 客户端引导 | 必须配 `hbase.zookeeper.quorum`，读 ZK 拿 Master 与 meta 位置 | 默认 RPC connection registry，配 `hbase.masters`，不再依赖 ZK |
| Coprocessor | `hbase-protocol` 在位，旧 CPEP 可用 | `hbase-protocol` 模块移除，CPEP 需重编译 |
| 数据块编码 | 枚举含 `PREFIX_TREE` | 移除 `PREFIX_TREE`（枚举编号 1 不再占用） |

JDK 的口径是另一回事：JDK11 预支持自 2.3.0、JDK17 支持自 2.5.x（HBASE-22972 / HBASE-26038），生产选型前先核对所用 2.x 小版本与 Hadoop 的 JDK 兼容矩阵。

## Consistency and Transactions

- **单行强一致**：同一 RowKey 的读写是原子的，行内有 RegionServer 级锁；跨行/跨分区**没有原生多行事务**，只有跨行原子写（batch / `BufferedMutator`）带来的「逐行原子、整体非原子」语义。
- **CAS**：`checkAndPut` / `checkAndMutate` 提供「读到预期值才写」，是自实现乐观锁与状态机的基础，也是官方推荐的「HBase 上的事务边界」。
- **行级操作的实现套路**：需要跨行一致性时，业界做法是 ① 引外部事务框架（如 Tephra 一类，借助 ZooKeeper/协调器做事务日志与隔离）；② 把多行聚合到一行（用「事务行」存状态再幂等重放）；③ 迁到有 SQL 与跨行事务的引擎（[TiDB](/docs/CS/DB/TiDB.md)、[OceanBase](/docs/CS/DB/OceanBase.md)），HBase 只留作明细宽表。
- **Region 副本读**：`REGION_REPLICATION` 默认 **1**（一 Region 一副本）。调大后启用「Async WAL Replication」（HBase 1.1+，本质是集群内复制）：副本 Region 按主 Region 的提交顺序观察写入，数据文件与主副本共享、无额外存储开销，各副本自己维护内存态。代价是副本异步、有可见性延迟；`REGION_MEMSTORE_REPLICATION` 默认 `true`，关掉后副本只回收 flush/bulkload 事件，读到的数据可能比主副本更旧。
- **写侧顺序**：一个 RegionServer 的 WAL 是全局有序的，崩溃恢复按 WAL 重放，因此「已确认的写」在 RegionServer 故障后仍然可见；反过来 `SKIP_WAL` 就放弃了这个保证。
- **批量导入不要走正常写路径**：BulkLoad 直接在 MapReduce / Spark 侧生成符合表布局的 HFile，再 move 进表并通知 RegionServer 加载，绕开 WAL 与 MemStore，是 TB 级灌数唯一合理的做法。

## Comparison

### Hive versus MySQL

| | Hive | MySQL |
| :---: | :--- | :--- |
| 查询语言 | HQL | SQL |
| 数据存储 | HDFS | 磁盘上 |
| 执行 | MR | Executor |
| 延迟 | 高 | 低 |
| 处理规模 | 大 | 小 |
| 索引 | 分区与桶裁剪为主，无 OLTP 式行级索引 | 有复杂的索引 |

### Hive versus HBase

| | HBase | Hive |
| :--- | :--- | :--- |
| 类型 | 宽表（列族）NoSQL 数据库 | 数据仓库 |
| 内部机制 | 数据库引擎 | MR |
| 增删改查 | 都支持 | 只支持导入跟查询 |
| Schema | 只需预定义列族，列可动态修改 | 需要预先定义表格 |
| 应用场景 | 实时 | 离线 |
| 特点 | K-V | 类 SQL |

两者常见组合是 Hive 把 HBase 当外部表（`STORED BY 'org.apache.hadoop.hive.hbase.HBaseStorageHandler'`）：用 HBase 存明细并提供点查，用 Hive 出 SQL 做批量分析。反过来说，这两张对比表也界定了各自的边界——把它们当同一个东西替换，是选型阶段最常见的事故。

### MySQL versus HBase

| | HBase | MySQL |
| :--- | :--- | :--- |
| 数据库 | NoSQL 数据库 | 关系型数据库 |
| 存储 | 按列族分文件，族内按行存 KV | 行 |
| 数据量 | 大 | 小 |
| 结构操作 | 非结构化与结构化数据的插入修改查询等简单操作 | 结构化数据的复杂操作 |

### Capability Matrix

| | [HBase](/docs/CS/DB/HBase.md) | [Cassandra](/docs/CS/DB/Cassandra.md) | [MongoDB](/docs/CS/DB/MongoDB.md) | [ClickHouse](/docs/CS/DB/ClickHouse.md) | [TiDB](/docs/CS/DB/TiDB.md) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 模型 | 宽表（列族）KV | 宽表（列族）KV | 文档 | 列式 OLAP | KV + SQL 关系模型 |
| 一致性 | 单行强一致 | 可调一致性，默认最终 | 副本集可线性读 | 副本最终一致为主 | Raft 强一致 + MVCC |
| 跨行事务 | 无原生支持 | 无（单分区原子批处理） | 多文档事务（4.0+） | 弱 | 支持，分布式 ACID |
| 二级索引 | 无，靠索引表 / Phoenix | 有但弱，代价是写放大 | 丰富，任意字段建索引 | 排序键 + 跳数索引 | B+ 树 + 全局索引 |
| 点查延迟 | 低 | 低 | 低 | 不适用 | 低 |
| 大范围扫描 | 按 RowKey 前缀/范围 | 需分区键友好 | 需索引或集合扫描 | 极强 | 走 TiFlash 列存 |
| 写入吞吐 | 极高（LSM + 顺序 WAL） | 极高 | 中 | 高（批量为主） | 中高 |
| 扩容 | Region 自动分裂迁移 | 无中心，线性 | 分片需规划 | 分片 + 副本 | 自动 Region 调度 |
| 关键依赖 | HDFS + ZooKeeper | 自带 gossip + 提交日志 | oplog + 副本集 | 本地存储 | PD + TiKV + Raft |
| 典型定位 | 超宽画像/明细/时序在线存 | 多活写入 | 灵活 Schema 业务库 | 报表与行为分析 | OLTP 主库 |

选型上真正要记住的是两句话：**要跨行事务和任意条件查询，就不该选 HBase；要在几十亿行上按主键取宽行、写入千万级 QPS，其它几个都做不动。** 更多分区与索引层面的取舍见 [Partition](/docs/CS/Distributed/Partition.md)。

## When to Use

适合：表规模到百亿行/TB 级以上、按 RowKey 或其前缀做点查与范围扫描、高写入吞吐、稀疏宽表（画像、特征、订单明细、消息、时序）、需要在线读到 HDFS 上那份数据。

不适合：复杂 join 与任意列即席查询（无二级索引时非 RowKey 查询等于全表扫描）、多行事务、频繁改主键、以 value 大小计的中大对象（走 MOB 或直接放对象存储）、低峰期需要一次性全表扫的业务（那是 Hive/Spark 的活）。

## Links

- [Bigtable](/docs/CS/Distributed/Bigtable.md)
- [LSM Tree](/docs/CS/Algorithms/tree/LSM.md)
- [Partition](/docs/CS/Distributed/Partition.md)
- [HDFS](/docs/CS/Framework/Hadoop/HDFS.md)
- [Cassandra](/docs/CS/DB/Cassandra.md)
- [DataBases](/docs/CS/DB/DB.md)

## References

1. [Apache HBase Reference Guide](https://hbase.apache.org/book.html)
2. [Apache HBase HConstants](https://github.com/apache/hbase/blob/branch-3.0/hbase-common/src/main/java/org/apache/hadoop/hbase/HConstants.java)
3. [Apache HBase ColumnFamilyDescriptorBuilder](https://github.com/apache/hbase/blob/branch-3.0/hbase-client/src/main/java/org/apache/hadoop/hbase/client/ColumnFamilyDescriptorBuilder.java)
4. [Apache Phoenix](https://phoenix.apache.org/)
5. [Apache HBase Operator Tools - HBCK2](https://github.com/apache/hbase-operator-tools)
6. [Bigtable: A Distributed Storage System for Structured Data](https://research.google/pubs/bigtable-a-distributed-storage-system-for-structured-data/)
