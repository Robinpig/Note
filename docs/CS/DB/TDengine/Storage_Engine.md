## Introduction

一个 vnode 的持久化状态由三部分组成：**WAL**（可靠性）、**META/TDB**（元数据）、**TSDB**（时序数据本体）。官方对 vnode 的定位是"数据存储、查询和备份的基本单元"，每个 vnode "可视为一个独立的数据库"——三部分都按 vnode 隔离，落盘路径也按 vnode 组织。

写入路径是一条经典的 WAL → MemTable → 磁盘管线，但时序数据部分没有用 B+Tree 而是 LSM，原因官方说得很直白：时序数据量大、写入持续，B+Tree 树高会随数据量快速增长，读写性能急剧下降。本页把这条路径和四层缓存讲清楚。

## Write Path

一次写入在 vnode 内经过四步：

1. **预处理**：保证多副本间数据一致（vgroup 内 Raft 复制的前置）。
2. **写 WAL**：先落日志保持久化。
3. **写 MemTable**：进入内存结构。
4. **后台刷盘**：内存池占用达到阈值时，后台线程把已写入数据刷到 META 和 TSDB，并在内存里标记对应 WAL 号已落盘。

WAL 行为由建库参数控制：`WAL_LEVEL` 默认 **1 = 写 WAL 但不 fsync**（数据在文件系统缓存，掉电丢最近写入）；`WAL_LEVEL 2` 才 fsync，配合 `WAL_FSYNC_PERIOD`（默认 3000 ms，范围 [0, 180000]，0 表示每次写立即落盘）。WAL 顺序追加、依赖文件系统缓存，这也是传输侧 `compressMsgSize` 之外写入性能的主要杠杆。

## MemTable：红黑树 + 跳表的双层索引

MemTable 里数据按 **(ts, version) 元组**排序（内存与数据文件中一致），索引分两层：

| 结构 | 索引对象 | 复杂度 |
| :-- | :-- | :--- |
| **红黑树** | 不同表（子表）之间的数据 | 查询/插入/删除 O(log n) |
| **跳表（SkipList）** | 同一张表内按时间排序的数据 | O(log n)，快速定位时间范围 |

这个结构直接服务一设备一表模型：跨表定位走红黑树，表内时间范围扫描走跳表，两层都不需要全局有序。

## META：TDB B+Tree

元数据存储引擎叫 **TDB**，TDengine 自研的 B+Tree 引擎，为读多写少设计。组成：

- **内置 Cache** + TDB 存储主文件 + TDB 日志文件；先写 Cache，Cache 内存不足时从 vnode 内存池申请。
- **原子性**：修改已有数据页前，先把未变更的数据页写进 TDB 日志文件备份，保证掉电等故障下的更新原子性。
- **多 B+Tree 组织**：一个 vnode 内建多个 B+Tree 存不同维度的索引（超级表名、schema、tag schema、子表名、子表 tag、tag 索引等），由根页号为 1 的索引 B+Tree 统一索引。
- **溢出页**：Key/Value 均可变长，超页数据用 overflow page 容纳；为保证 B+Tree **扇出至少为 4**，TDB 限制非溢出页中 Key/Value 最大长度。

元数据缓存大小由建库参数 `PAGES`（默认 256）和 `PAGESIZE`（默认 4 KB）决定——`PAGESIZE × PAGES` 即每 vnode 元数据缓存占用，默认约 1 MB。

## TSDB：数据文件组与五类文件

TSDB 按**时间范围**把数据文件切成多个**数据文件组**（data file group），查询时按所查时间范围直接算出文件组号，跳过无关文件。文件组内有五类文件：

| 文件 | 内容 |
| :-- | :--- |
| **head** | 时序数据文件的 **BRIN（Block Range Index）**：每个数据块的时间范围、偏移、长度；BRIN 记录本身按列压缩 |
| **data** | 真正的时序数据，以数据块组织，**每个数据块只含一个子表**的数据、块内列式存储、按列用不同压缩算法 |
| **sma** | 预计算结果：各列的 **sum / min / max**，查询引擎可直接利用，避免读原始数据（SQL 侧的 TSMA 见 [SQL](/docs/CS/DB/TDengine/SQL.md)） |
| **tomb** | 删除记录，元组为 `(suid, uid, start_timestamp, end_timestamp, version)` |
| **stt** | 落盘（landing）后残留的**碎片数据**，下次落盘时与内存新数据合并成更大数据块再写 data file |

stt 文件的配置策略官方给了明确分界：**表少、写频率高**的场景只维护一个 stt 文件（合并出大块，避免 data file 碎片化）；**表多、写频率低**的场景配多个 stt 文件（同一超级表下所有子表累计数据量可观，多 stt 合并同样能出大块）。

数据块内的行编码有两种格式：

- **Tuple 编码**：非稀疏场景，基于 schema 偏移直接访问列数据，O(1)。
- **Key-Value 编码**：稀疏场景（schema 数千列但每行有值列很少），用 offset 数组索引各列——offset 值全 < 256 用 `uint8_t`，全 < 65,536 用 `uint16_t`，否则 `uint32_t`。牺牲访问速度换空间。

## Distribution：一致性哈希

表（子表）在 vnode 间的分布由**一致性哈希**决定（官方架构原话：the distribution of tables on vnodes is determined by consistent hashing），不对外暴露表名哈希细节。一个数据库建多少个 vnode 由建库 `VGROUPS` 决定，vgroup 数量决定并行度与再平衡粒度——扩缩容的本质就是 vnode/vgroup 的迁移，由 mnode 调度。

## Compaction

TSDB 的后台合并发生在两个层面：LSM 通用的**数据文件合并**（减少文件数量、提升查询性能），以及 **stt 碎片合并**（落盘时把残留碎片与新数据合成大块）。由于 data file 的数据块以子表为单位，合并天然不会产出跨子表的大块——"一设备一表"的边界同时成了 compaction 边界。企业版另有 `COMPACT_INTERVAL`/`COMPACT_TIME_RANGE`/`COMPACT_TIME_OFFSET` 精细控制，社区版没有。

## Cache：四层

| 层 | 参数 | 默认 | 说明 |
| :-- | :-- | :--- | :--- |
| **写缓存** | `BUFFER` / `VGROUPS` | 256 MB/vnode | 时间驱动（write-driven）缓存管理：优先把新写入留在缓存，达到阈值批量刷最早的数据——和传统 read-driven 相反，是为 IoT "只关心最新状态" 的负载设计的 |
| **读缓存** | `CACHEMODEL` / `CACHESIZE` | **`none` / 1 MB** | `last_row`（每子表最新行）、`last_value`（每列最新非空值）、`both`。官方明确说有了它不必再集成 Redis |
| **元数据缓存** | `PAGES` / `PAGESIZE` | 256 页 × 4 KB | TDB 的页缓存 |
| **文件系统缓存** | `WAL_LEVEL` / `WAL_FSYNC_PERIOD` | 1 / 3000 ms | WAL 顺序追加吃 fs cache，fsync 决定何时真正落盘 |

读缓存有两个不显然的实现细节：**`CACHEMODEL != none` 时每个 vnode 会额外拉起一个持久化 RocksDB 实例**做 last cache（内存 LRU 未命中或重启后由它兜底），参数 `sLastCache*` 写在 `taos.cfg`（dnode 级）且**惰性生效，改完要重启 dnode**；**`CACHESIZE` 在内存 LRU 与 RocksDB block cache 之间对半分**（各一半），所以总占用约等于 `CACHESIZE` 而不是两倍，且只有 `ALTER DATABASE ... CACHESIZE` 能在线调整。运行态可通过系统表 `INS_LAST_CACHE_STATS` 按 vgroup 观察。

## Links

- [TDengine](/docs/CS/DB/TDengine.md)
- [Architecture](/docs/CS/DB/TDengine/Architecture.md)
- [Compression](/docs/CS/DB/TDengine/Compression.md)
- [Data_Model](/docs/CS/DB/TDengine/Data_Model.md)
- [WAL](/docs/CS/DB/WAL.md)
- [LSM Tree](/docs/CS/Algorithms/tree/LSM.md)

## References

1. [技术内幕：存储引擎](https://docs.tdengine.com/internals/storage/)
2. [技术内幕：数据缓存](https://docs.tdengine.com/internals/cache/)
3. [TDengine SQL：CREATE DATABASE 参数](https://docs.taosdata.com/reference/taos-sql/database/)
