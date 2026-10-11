## Introduction

Milvus 的「存算分离」不是一句口号，而是落到三类互不相同的持久化载体上：一条只追加的 WAL 承接所有数据与元数据变更，封口后的 segment 以列式文件躺在对象存储上，而「谁有哪些 segment、文件叫什么名字」这类元数据压在 etcd 或 TiKV 的 KV 上。三者的写放大特征、容量上限和一致性协议完全不同，把它们混在一起讨论就会得出错误的运维结论。

本篇只讲**文件与 IO 抽象**：一个 segment 在对象存储上究竟产出哪些文件、binlog 与 manifest 两套引擎的物理结构差在哪、哪些字节进了 etcd、以及为什么 etcd 装不下大对象。封口由谁触发、什么时候触发归 [Write Path](/docs/CS/DB/Milvus/Write_Path.md)；封口后文件如何被合并与回收归 [Compaction and Lifecycle](/docs/CS/DB/Milvus/Compaction_and_Lifecycle.md)；索引类型与参数归 [Index and Vector Engine](/docs/CS/DB/Milvus/Index_and_Vector_Engine.md)。

需要先纠正一个常见误解：v3.0.1 里并存的不止两套引擎，而是**三个 storage version 常量**——`internal/storage/rw.go` 定义 `StorageV1 = 0`、`StorageV2 = 2`、`StorageV3 = 3`。V1 是 2.0 时代的逐事件 binlog；V2 是 milvus-storage packed writer 直接产 Parquet；V3 才是在 V2 之上叠加 loon 事务化 manifest。目录名 `internal/storagev2/` 同时承载 V2 与 V3 两条路径，不能望文生义地以为它等于 V3。

## Three-Tier Storage Model

| 层 | 承载内容 | 载体 | 写入方 | 读取方 |
| :--- | :--- | :--- | :--- | :--- |
| WAL 层 | 全部数据与元数据变更日志：消息、TimeTick、checkpoint | Kafka / Pulsar / Woodpecker / RocksMQ | Proxy 把 DML 转成 WAL 消息，`walimpls` 追加 | StreamingNode 的 flusher 落盘；msgdispatcher 的唯一生产消费者是 QueryNode |
| Segment 层 | 封口段数据：insert log、delta log、stats log、索引文件、manifest | 对象存储，S3 / MinIO / GCS / Azure / 本地 posix | 3.0 起**唯一落盘路径是 StreamingNode flusher**；索引文件由 DataNode 本地构建写出 | QueryNode 加载 sealed segment；compaction 读写 |
| 元数据层 | collection、schema、field、partition、segment 引用、binlog 路径列表、索引、checkpoint、权限 | etcd 或 TiKV | MixCoord 的 RootCoord / DataCoord / QueryCoord / StreamingCoord 角色 | 各协调角色 + WatchKV 订阅 |

代码归属：WAL 在 `pkg/streaming/walimpls/`，Segment 在 `internal/storage/` 与 `internal/storagev2/`，元数据在 `internal/kv/` 与 `internal/metastore/`。

## Segment Files on Object Storage

以对象存储 `rootPath` 为前缀，所有路径由 `pkg/util/metautil` 构造，路径段一律是十进制 ID，目录名常量在 `pkg/common`：

| 目录前缀 | 内容 | 路径粒度 |
| :--- | :--- | :--- |
| `insert_log` | 字段数据 binlog | `insert_log/{collectionID}/{partitionID}/{segmentID}/{fieldID}/{logID}` |
| `delta_log` | 删除条目，主键加时间戳 | `delta_log/{collectionID}/{partitionID}/{segmentID}/{logID}`，**无 fieldID** |
| `stats_log` | `PrimaryKeyStats`，主键布隆过滤器 | 带 fieldID |
| `bm25_stats` | 全文检索 BM25 统计 | 带 fieldID |
| `index_files` / `index_v1` | 段索引文件，前者是旧版 build 根目录布局，后者是当前 collection 根目录布局 | 带 buildID |
| `part_stats` / `analyze_stats` | clustering 后的 partition stats；分析产物，子目录 `offset_mapping`、`centroids` | segment 维度 / 带 fieldID |
| `text_log` / `json_key_index_log` / `json_stats` | 全文索引、JSON 索引、JSON 键统计 | 带 fieldID 与 buildID |

**是列存**，而且是两个维度的列存：文件维度上 `insert_log` 按 fieldID 切文件，一个字段一个 log 文件；文件内部是 Arrow RecordBatch 经 Parquet 写出。删除走独立的 `delta_log`，它按 segment 而非 field 组织，因此删除条目天然是跨字段的。V3 引擎改按 column group 分组后，字段与文件的对应关系不再是一比一。

## Storage V1 Binlog Physical Layout

文件骨架是「magic number + 版本 + 一串事件」，由 `internal/storage/binlog_writer.go` 写出：

| 结构 | 字段 | 说明 |
| :--- | :--- | :--- |
| `MagicNumber` | `int32 = 0xfffabc` | 文件头，`binlog_writer.go` 常量 |
| `baseEventHeader` | `Timestamp`、`TypeCode`、`EventLength`、`NextPosition` | `event_header.go`；`descriptorEventHeader` 与 `eventHeader` 都是它的别名 |
| `Timestamp` | `typeutil.Timestamp` | 由 `tsoutil.ComposeTS` 生成的 TSO 混合逻辑时间戳 |

事件类型枚举在 C++ 侧 `EventType`：`DescriptorEvent`、`InsertEvent`、`DeleteEvent`、`IndexFileEvent`，以及 `CreateCollectionEvent` / `DropCollectionEvent` / `CreatePartitionEvent` / `DropPartitionEvent` 四类 DDL 事件。全库统一小端字节序，`common.Endian` 即 `binary.LittleEndian`。

payload 由 `NativePayloadWriter` 写，压缩配置固定为 `parquet.WithCompression(compress.Codecs.Zstd)` 加 `parquet.WithCompressionLevel(3)`。`internal/storage/compress/zstd.go` 注册了一个受并发限制的自定义 zstd codec，注释说明动机是避免序列化时占用过多内存——压缩级别与 codec 都不可配置，这是 v1 的硬编码取舍。

切文件的粒度由 size 配置决定：

| 配置键 | 默认值 | 语义 |
| :--- | :--- | :--- |
| `dataNode.segment.insertBufSize` | `16777216` | 段内单个 binlog 在内存中缓冲的上限，超过即刷到对象存储；导出到 milvus.yaml 且 `PanicIfEmpty` |
| `dataNode.segment.binlog.maxsize` | `67108864` | 按键名为单个 binlog 文件上限；未导出到 milvus.yaml，源码未附 Doc 说明其与实际刷盘的关系 |
| `common.indexSliceSize` | `16` | 索引切片大小，单位 MB |

## Storage V2 and V3 Manifest Engine

V3 的布局是**版本化 manifest 加列组**，一个数据集固定五个子目录：

```
base_dir/
├── _metadata/manifest-{version}.avro    # 版本从 1 递增，最新由扫描目录得出
├── _data/{group_id}_{uuid}.{format}     # 列组数据文件
├── _delta/                              # 删除日志
├── _stats/                              # 布隆过滤器、BM25 等统计
└── _index/                              # HNSW、IVF、bitmap 等索引
```

manifest 用 Apache Avro 二进制编码，头部是 `MAGIC int32 = 0x4D494C56` 加 `VERSION int32`，当前取值 1 或 2；version 1 记录 `column_groups`、`delta_logs`、`stats`。每个 column group 三元组是 `columns`、`files`、`format`。支持的格式：

| format | 说明 |
| :--- | :--- |
| `parquet` | Apache Parquet 列式格式 |
| `vortex` | Vortex 压缩格式 |
| `lance` | Lance 格式，**只读** |
| `binary` | 原始二进制 |

列组切分策略默认全开，且都可在运行时刷新：

| 配置键 | 默认值 | 语义 |
| :--- | :--- | :--- |
| `common.storage.stv2.splitSystemColumn.enabled` | `true` | 把系统列单独拆成列组 |
| `common.storage.stv2.splitSystemColumn.includePK` | `true` | 主键是否计入系统列策略 |
| `common.storage.stv2.splitSystemColumn.includePartitionKey` | `true` | 分区键计入，未导出到 milvus.yaml |
| `common.storage.stv2.splitSystemColumn.includeClusteringKey` | `true` | clustering key 计入，未导出 |
| `common.storage.stv2.splitByAvgSize.enabled` | `true` | 按平均行大小切列组 |
| `common.storage.stv2.splitByAvgSize.threshold` | `1024` | 阈值，单位字节；Go 侧对应常量 `ColumnGroupSizeThreshold = 1024` |

提交是**事务化**的：Go 侧经 cgo FFI 调 C++ 的 loon，`internal/storagev2/packed/manifest_commit.go` 的 `CommitManifestUpdates` 走 `loon_transaction_begin` / `apply` / `commit`，采用 OVERWRITE resolve 语义，效果是读快照不变、并发写安全。这正是 v1 逐事件 binlog 给不了的能力，也是引入 manifest 的根本动因：列裁剪、谓词下推、原子提交三件事都需要一个「描述数据集由哪些文件组成」的显式快照。冲突重试上限由 `common.storage.manifestTransactionRetryLimit` 控制，默认 `10`。读写缓冲常量在 `internal/storagev2/packed/constant.go`：写与读各 32 MB，分片上传 10 MB；字段 ID 通过 Arrow metadata 键 `PARQUET:field_id` 落进 Parquet schema。

## Engine Selection and Default Values

**没有全量切换到 V3**。版本记录在每个 segment 的元数据上，读路径三版并存以兼容既有数据，写路径按下列配置决定：

| 配置键 | 默认值 | 语义 |
| :--- | :--- | :--- |
| `common.storageType` | `remote` | 取值 `local` / `remote`；`minio` 已废弃改用 `remote` |
| `common.storage.useLoonFFI` | `false` | 是否走 loon V3 manifest 路径，`refreshable`，首次引入于 2.6.7 |
| `common.storage.enableGrowingSourceFlush` | `false` | QueryNode growing source 经 StorageV3 manifest 落盘，3.0.0 新增 |
| `metastore.type` | `etcd` | 取值 `etcd` / `tikv` |
| `metastore.maxEtcdTxnNum` | `64` | 单个 etcd 事务的最大 op 数 |
| `localStorage.path` | `/var/lib/milvus/data/` | 查询期本地缓存目录 |

版本推断的实际逻辑在 `writeBufferBase.resolveNewGrowingSegmentStorageVersion`：若 segment 上报的已是 `StorageV2` 或 `StorageV3` 则直接采用；若是 `StorageV1` 且流式服务开启，**直接报错** `missing storage version for streaming growing segment`——因为 3.0 起流式服务恒开；只有在非流式的遗留分支里才会推断，默认推断为 `StorageV2`，仅当 schema 含 TEXT 字段或 `useLoonFFI` 为真时推断为 `StorageV3`。也就是说 **TEXT 字段是当前唯一会强制把段推到 V3 的隐式条件**。存量段的升级由 DataCoord 的 `compaction_policy_storage_version.go` 读同一个 `UseLoonFFI` 开关来决定，触发与调度细节归 Compaction。

## Object Storage Abstraction

`internal/storage/remote_chunk_manager.go` 分两层：

| 抽象 | 关键方法 | 角色 |
| :--- | :--- | :--- |
| `ObjectStorage` | `GetObject`、`PutObject`、`StatObject`、`WalkWithObjects`、`RemoveObject`、`CopyObjectCrossBucket` | 单个后端的原语，`GetObject` 带 `offset` 与 `size` 即 range read |
| `ChunkManager` | 由 `RemoteChunkManager` 实现 | 面向 bucket 与 rootPath 的分块语义 |

另有 `CrossBucketCopier` 独立接口承载跨桶复制。后端按 `objectstorage.Config` 的 `CloudProvider` 分派：Azure 走 `newAzureObjectStorageWithConfig`，GCP 原生走 `newGcpNativeObjectStorageWithConfig`，其余走 MinIO 即 S3 兼容路径；`pkg/objectstorage/` 下另有 `aliyun`、`huawei`、`tencent`、`gcp` 子包与 `options.go` 的 `Config`。本地模式是 `local_chunk_manager.go` 的 posix 实现。C++ 侧经 `InitRemoteArrowFileSystem` 访问同一份对象存储，避免两套客户端语义漂移。range read 是整个抽象的价值所在：查询不需要下载整个 binlog，只需读出命中的列与行组——这与 [HBase](/docs/CS/DB/HBase.md) 把 HFile 放 HDFS 上按需读取的思路同源，只是 Milvus 走对象存储 HTTP API 而非文件系统 `pread`。

## Metadata KV Layer

接口分层在 `pkg/kv/kv.go`：`BaseKV → TxnKV → MetaKv → WatchKV`，逐层叠加事务、CAS 与 watch；`reliable_write_meta_kv.go` 提供幂等可靠写。实现在 `internal/kv/` 下三个子包：`etcd/etcd_kv.go`、`tikv/txn_tikv.go`、`mem/mem_kv.go`。

上层是 Catalog 抽象（`internal/metastore/catalog.go`），按角色切分：`RootCoordCatalog`、`DataCoordCatalog`、`QueryCoordCatalog`、`StreamingCoordCataLog`、`StreamingNodeCataLog`，kv 实现位于 `internal/metastore/kv/<role>/`，protobuf 到数据模型的转换在 `internal/metastore/model/`。

key 空间是 `<rootPath>/meta/<role-前缀>/<实体>/<ID>`，RootCoord 前缀为 `ComponentPrefix = "root-coord"`：

| 前缀 | 内容 |
| :--- | :--- |
| `root-coord/collection/{collectionID}` | collection 元数据，带 dbID 时另有变体 |
| `root-coord/partitions/{collectionID}/{partitionID}`、`root-coord/fields/{collectionID}/{fieldID}` | 分区、字段，逐字段一个 key |
| `root-coord/aliases`、`/functions`、`/struct-array-fields`、`/snapshots` | 别名、函数、结构体数组字段、快照 |
| `root-coord/credential/users`、`root-coord/roles`、`/credential/user-role-mapping`、`/grantee-privileges` | RBAC |
| `datacoord-meta/s`、`/binlog`、`/deltalog`、`/statslog`、`/bm25log` | segment 引用与其文件路径列表 |
| `datacoord-meta/channel-cp`、`/compaction-task`、`/import-job`、`/partition-stats`、`/analyze-task`、`/snapshot` | channel checkpoint 与各任务态 |

TSO 也在这一层：`internal/tso/` 的 `timestampOracle` 通过 load / save / `UpdateTimestamp` 把物理时间定期落 etcd，配合 `GlobalTSOAllocator`。etcd 侧另有 `requestTimeout: 10000` 与默认开启的鉴权；`metastore.type` 选 `tikv` 时**仍需一个 etcd 做服务发现**，且 TiKV 的 key 布局多一层子路径，`rootPath` 分别拼 `metaSubPath` 与 `kvSubPath` 得 metaRootPath 与 kvRootPath，etcd 对应的是常量 `meta`。

## Etcd Capacity and Quota Risk

etcd 是 Raft 复制 KV：每次写要走一轮共识、落盘、并推给所有 watcher；它的后端有容量配额，单个 value 与单个事务的体积也都有上限。这些上限属于 etcd 自身配置，Milvus 侧不定义它们，只通过 `metastore.maxEtcdTxnNum` 默认 64 限制单事务 op 数，把一次逻辑变更拆成多笔 `Txn`。

于是风险很具体：**segment 数量多、字段多，etcd 里那些 value 就跟着膨胀**。`datacoord-meta/binlog` 之类的 key 存的是 binlog 路径列表，一个有几千个字段级 log 的大段，其列表本身就会撑出接近上限的 value；DDL 与 checkpoint 更新又会把整个 value 重新推一遍 Raft。RootCoord 的 `legacy_snapshot_gc.go` 存在本身就是证据——快照机制需要一个专门的 GC，而它同样按 `MaxEtcdTxnNum` 分批删除。

这正是三层模型的设计动机：行的字节永远不进 etcd。把大对象塞进 etcd 的后果不是「慢一点」，而是配额打满后集群拒绝写入、compaction 跟不上导致 defrag 抖动、watch 风暴放大成协调角色集体不可用。当元数据规模确实需要横向扩展时，正解是 `metastore.type: tikv` 而不是调大 etcd——milvus.yaml 对 TiKV 的注释原话即是「metadata size requires better horizontal scalability」时的好选择。这一层与 [RocksDB](/docs/CS/DB/RocksDB/RocksDB.md) 的 LSM 写放大权衡是同一类问题，只是 etcd 的 Raft 复制把它放大了。

## Reducing Remote Reads on the Query Side

对象存储的每次 GET 都是网络往返，加载路径因此叠了几层本地化手段。索引参数本身归 [Index and Vector Engine](/docs/CS/DB/Milvus/Index_and_Vector_Engine.md)，这里只记文件与 IO 抽象：

| 配置键 | 默认值 | 语义 |
| :--- | :--- | :--- |
| `localStorage.path` | `/var/lib/milvus/data/` | 检索期把远端数据落到本地，避免重复访问 MinIO / S3；注释警告事后改会影响旧数据可读 |
| `queryNode.segcore.storageV2.cellTargetSizeBytes` | `4194304` | 缓存单元目标字节数，Parquet row group 贪心打包进 cell，cell 不跨文件边界——批 IO 大小与缓存粒度的折中 |
| `queryNode.mmap.vectorField` | `true` | 向量原始数据走 mmap |
| `queryNode.mmap.vectorIndex` / `scalarField` / `scalarIndex` | `false` | 默认不 mmap |
| `queryNode.mmap.jsonShredding` | `true` | JSON stats 走 mmap；`growingMmapEnabled` 默认 `false`，开了省内存但受影响段延迟略升 |
| `queryNode.cache.readAheadPolicy` | `willneed` | chunk cache 的预读策略 |
| `common.loadTransientBudgetBytes` | `0` | 进程级瞬态内存预算，同时门控标量索引 V3 流式与 storage v2/v3 字段加载；0 为不限 |
| `common.storage.iops.initialRate` | `2000` | Lance AIMD 限流器的初始对象存储请求速率，用于 External Table 读 |

mmap 的实现是 C++ 侧 `MmapChunkManager` 配 Go 侧 `InitMmapManager`，落在 `internal/util/initcore/`，内核层机制见 [mmap](/docs/CS/OS/Linux/mm/mmap.md)。V3 路径下缓存单元与 row group 对齐，这让「一次预取正好是一个可独立淘汰的列片段」成为可能，是 manifest 引擎除原子提交外的第二个收益。

## Links

- [Milvus](/docs/CS/DB/Milvus/Milvus.md)
- [Write Path](/docs/CS/DB/Milvus/Write_Path.md)
- [Compaction and Lifecycle](/docs/CS/DB/Milvus/Compaction_and_Lifecycle.md)
- [Index and Vector Engine](/docs/CS/DB/Milvus/Index_and_Vector_Engine.md)
- [WAL and StreamingNode](/docs/CS/DB/Milvus/WAL_and_StreamingNode.md)
- [etcd](/docs/CS/Framework/etcd/README.md)

## References

- [Milvus Storage Manifest Format design doc](https://github.com/milvus-io/milvus/blob/v3.0.1/docs/design-docs/design_docs/20260226-manifest-format.md)
- [milvus-io/milvus-storage](https://github.com/milvus-io/milvus-storage)
- [milvus.yaml at v3.0.1](https://github.com/milvus-io/milvus/blob/v3.0.1/configs/milvus.yaml)
- [internal/storage/rw.go at v3.0.1](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/storage/rw.go)
- [internal/storage/remote_chunk_manager.go at v3.0.1](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/storage/remote_chunk_manager.go)
- [internal/storagev2/packed/manifest_commit.go at v3.0.1](https://github.com/milvus-io/milvus/blob/v3.0.1/internal/storagev2/packed/manifest_commit.go)
