## Introduction

[RocksDB](http://rocksdb.org/) 由 Facebook 基于 Google [LevelDB](/docs/CS/DB/LevelDB/LevelDB.md)（Sanjay Ghemawat & Jeff Dean）扩展而来，是嵌入式 **LSM-tree** KV 存储，为 MyRocks、TiDB、Kafka Streams、CockroachDB 等提供本地状态存储。

## 存储结构（LSM）

- **MemTable**：内存中可变有序结构（跳过表/skiplist），写先入 MemTable 并写 **WAL**（预写日志，崩溃恢复用）。
- **SSTable（SST）**：不可变有序磁盘文件。MemTable 写满后 flush 成 L0 SST。
- **分层（Level）**：L0 文件间 key 区间可能重叠；L1+ 每层按 key 范围分区、层内不重叠，容量按约 10× 扩张。

## Compaction

- **Leveled**：每层与下一层重叠区间做 merge，读放大低、写放大高（约 10×）。
- **Tiered（Universal）**：合并同层多个文件，写放大低、读放大高、空间放大高。
- 目标：回收过期版本/删除（tombstone）、维持有序、控制读放大。

## 关键优化

- **Bloom Filter**：跳过必然不含 key 的 SST，降低读放大。
- **Column Family**：多列族共享 WAL/MemTable 但独立 SST 与 compaction，类比多张表。
- **Block Cache / Row Cache**：缓存数据块与 KV。
- **Snapshot / SequenceNumber**：MVCC 多版本，支持快照读。

## Links

- [LevelDB](/docs/CS/DB/LevelDB/LevelDB.md)
- [DataBases](/docs/CS/DB/DB.md)
- [LSM-Tree](/docs/CS/Algorithms/tree/LSM.md)

## References

- [RocksDB Wiki](https://github.com/facebook/rocksdb/wiki)
- [RocksDB: A Persistent Key-Value Store for Flash and RAM Storage](http://www.cs.cmu.edu/~pavlo/courses/fall2013/static/papers/1611_2_dong.pdf)
