## Introduction

`treeIndex` 是 etcd v3 **内存中的键索引模块**，负责把用户 key 映射到它的最新 `revision`（版本号）。它基于 Google 开源的 [btree](https://github.com/google/btree) 内存 B-tree 库实现：treeIndex **只保存 key 与其 revision 的映射**，真正的 value 数据持久化在 [boltdb](/docs/CS/Framework/etcd/boltdb.md) 的事务里。

这与 etcd v2 / ZooKeeper 的「全量数据驻留内存」形成对比——v3 把索引与值分离，显著降低了内存占用，使 etcd 能支撑更大数据集。

## Key Design

- **key → revision 映射**：每次写（put/delete）都产生一个全局单调递增的 `revision = (main, sub)`，treeIndex 记录 key 当前指向的 revision，以及历史 revision 链表（用于 MVCC 多版本读与 watch 回溯）。
- **多版本（MVCC）**：读取指定 `revision` 时，treeIndex 先查到 revision，再拿它去 boltdb 取对应 value；删除用「 tombstone（墓碑）」标记而非物理擦除，便于保留历史与范围 watch。
- **范围与前缀查询**：B-tree 天然支持 `range` / `prefix` 遍历，配合 boltdb 的 B+Tree 实现高效的范围扫描。
- **内存与持久分离**：treeIndex 在内存、重启后由 boltdb 回放重建；boltdb 提供磁盘持久与事务隔离。

## Collaboration with Other Components

- 写路径：API 层 → [MVCC](/docs/CS/Framework/etcd/MVCC.md) 分配 revision → treeIndex 更新映射 → boltdb 写值 → [raft](/docs/CS/Framework/etcd/raft.md) 复制日志。
- 读路径：treeIndex 定位 revision → boltdb 取 value；历史读走多版本链表。
- watch：以 revision 为游标，treeIndex + MVCC 能精确推送「某 key 自从某 revision 之后的变更」。

## Links

- [etcd](/docs/CS/Framework/etcd/etcd.md)
- [boltdb](/docs/CS/Framework/etcd/boltdb.md)
- [MVCC](/docs/CS/Framework/etcd/MVCC.md)
- [raft](/docs/CS/Framework/etcd/raft.md)

## References

- [etcd v3 architecture and MVCC design](https://etcd.io/docs/v3.5/learning/)
- [google/btree - in-memory B-tree for Go](https://github.com/google/btree)
