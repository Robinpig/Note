## Introduction

Column Family（列族）是 RocksDB 相对 LevelDB 最重要的结构性增量：**一个数据库实例内部划分出多个互相独立的键空间**，每个列族有自己的 memtable、自己的 SST 文件集合与层级、自己的 compaction 参数，但**共享同一份 WAL、同一组后台线程、同一个写限速器**。它替代了「为每张表开一个 RocksDB 实例」的做法——后者会把 WAL、线程池、缓存全部复制一遍。

默认列族的名字就是字面量 `default`（`include/rocksdb/db.h:64` 的 `kDefaultColumnFamilyName`）。所有 API 都以 `ColumnFamilyHandle` 为参数入口，`DB` 上的读写方法带 handle 的重载即落到指定列族。

## What Is Shared and What Is Isolated

官方 wiki 的 Implementation 一节把边界说得很干脆：**列族共享 WAL，不共享 memtable 与 table 文件**。展开成运维语言：

| 维度 | 归属 | 后果 |
| :--- | :--- | :--- |
| WAL | 共享 | 一个 `WriteBatch` 跨多列族的写入只需一次日志追加即可原子提交 |
| memtable / immutable memtable | 每列族独立 | 内存占用 = `列族数 × write_buffer_size × max_write_buffer_number` |
| SST 与层级结构 | 每列族独立 | `num_levels`、压实风格、压缩方式都可按列族不同 |
| `ColumnFamilyOptions` | 每列族独立 | 这是列族存在的核心理由 |
| `WriteController` | **全实例共享** | 一个列族触发写停顿，全实例一起被限速或停写 |
| 后台线程池（`max_background_jobs`） | 共享 | 列族多而后台线程少时，flush/compaction 会互相排队 |
| `SuperVersion` | 每列族一份 | 读路径按列族取视图（`column_family.h:207`） |

实现上 `ColumnFamilySet`（`column_family.h:761`）持有全部 `ColumnFamilyData`（:299）以及共享的 `write_controller_`，这张对象图就是「多列族一套基础设施」的物化。

## WAL Retention and the Cost of Many Column Families

WAL 不能随单个列族 flush 就删除。规则是：**任一列族 flush 时都会新建一个 WAL，而旧 WAL 只有在所有列族都已 flush 之后才能删掉**。

于是出现了很反直觉的现象：一个几乎不写、memtable 常年不满的「冷列族」，会一直钉住它之后产生的所有 WAL，让磁盘日志占用持续增长。RocksDB 的兜底是 `max_total_wal_size`：默认为 0 时取动态值 `Σ(write_buffer_size × max_write_buffer_number) × 4`，**且只在列族数 > 1 时生效**（`options.h:808-828`），超阈值就强制 flush 那些落后的列族来回收日志。

这条机制的运维含义很直接：**不要为「逻辑分组」随手开几百个列族**。列族数量要按「需要不同调参/不同生命周期」来划分，而不是按表数量线性铺开。

## Metadata and Open Cost

列族的增删都是 `VersionEdit` 里的记录（`kColumnFamily = 200`、`kColumnFamilyAdd = 201`、`kColumnFamilyDrop = 202`，`version_edit.h:37-77`），文件归属也逐条记在 MANIFEST 里。列族多 → edit 多 → 打开时需要重放的 MANIFEST 更长。v11 里 MANIFEST 的滚动大小已与「压缩后估计大小」联动（`max_manifest_file_size` 变为下限、新增 `max_manifest_space_amp_pct = 500`，`options.h:1015/1094`），但**列族数量对启动时间的影响依然存在**，冷热分层明显时应考虑拆实例而不是拆列族。

删除列族（`DB::DropColumnFamily`）只是让键空间不再可见，其 SST 文件要等 obsolete 文件清理流程释放；这也意味着「删列族」不会立刻回收磁盘。

## Opening and Enumerating

打开带列族的库必须显式给出描述符列表：`DB::Open(db_options, path, column_family_descriptors, handles, dbptr)`；只想打开部分列族时配 `create_missing_column_families = false`（`options.h:595`）。写 batch 时若引用了不存在的列族，`WriteOptions::ignore_missing_column_families = false` 会让写入直接失败（:2541）——这个默认值是对的，静默丢写比报错危险得多。

Secondary Instance 有一个列族特有的限制：**主实例之后新建的列族会被 secondary 忽略**（`db.h:268-272`），所以动态加列族的场景不能用 secondary 做只读副本。

跨列族的顺序读另有 `MultiScan`（`include/rocksdb/multi_scan.h`，10.5 起持续调整契约），它把多个列族的迭代器合并成一个有序游标。

## Guidelines

- **按调参需求分组，而不是按业务表分组**：同一列族共享一套 compaction/压缩/过滤器参数，把访问模式相近的数据放一起才划算。
- **给冷列族单独安排 flush**：否则它拖住 WAL 的行为会让日志目录看起来「莫名其妙地涨」。
- **写停顿排查要先定位列族**：症状是全实例变慢，根因往往只有一个列族压实跟不上（见 [Write_Path](/docs/CS/DB/RocksDB/Write_Path.md) 的 stall 归因表）。
- **列族极多时考虑拆实例**：共享 WAL 与共享线程池在列族数上千时会互相拖累，而 MANIFEST 重放也会拉长启动时间。

## Links

- [RocksDB](/docs/CS/DB/RocksDB/RocksDB.md)
- [Write Path](/docs/CS/DB/RocksDB/Write_Path.md)
- [Compaction](/docs/CS/DB/RocksDB/Compaction.md)
- [Read Path](/docs/CS/DB/RocksDB/Read_Path.md)
- [Transactions](/docs/CS/DB/RocksDB/Transactions.md)

## References

1. [RocksDB Wiki: Column Families](https://github.com/facebook/rocksdb/wiki/Column-Families)
2. [RocksDB source: column_family.h](https://github.com/facebook/rocksdb/blob/v11.8.1/db/column_family.h)
