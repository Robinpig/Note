## Introduction

`treeIndex` 是 etcd v3 **内存中的键索引模块**，负责把用户 key 映射到它的 revision 代际信息。它基于 Google 开源的 [btree](https://github.com/google/btree) 内存 B-tree 库实现：treeIndex **只保存 key 与 revision 链表等索引结构**，真正的 value 数据持久化在 [boltdb](/docs/CS/Framework/etcd/boltdb.md) 的事务里；它不是指向磁盘 value 的指针表。

这与 etcd v2 / ZooKeeper 的「全量数据驻留内存」形成对比——v3 把索引与值分离，显著降低了内存占用，使 etcd 能支撑更大数据集。

## Key Design

- **key → revision 映射**：每次写（put/delete）都产生一个全局单调递增的 `revision = (main, sub)`，treeIndex 记录 key 当前指向的 revision，以及历史 revision 链表（用于 MVCC 多版本读与 watch 回溯）。
- **多版本（MVCC）**：读取指定 `revision` 时，treeIndex 先查到 revision，再拿它去 boltdb 取对应 value；删除用「 tombstone（墓碑）」标记而非物理擦除，便于保留历史与范围 watch。
- **范围与前缀查询**：B-tree 天然支持 `range` / `prefix` 遍历，配合 boltdb 的 B+Tree 实现高效的范围扫描。
- **内存与持久分离**：treeIndex 在内存、重启后由 boltdb 回放重建；boltdb 提供磁盘持久与事务隔离。

## Collaboration with Other Components

- 写路径：API → [Raft](/docs/CS/Framework/etcd/raft.md) propose / commit / apply → [MVCC](/docs/CS/Framework/etcd/MVCC.md) 在 apply 阶段分配 revision → backend buffer 与 treeIndex 同步更新 → 事务 End 推进 `currentRev` 并让变更可见。
- 读路径：treeIndex 定位 revision → backend 读缓冲 / boltdb 取 value；历史读走 revision 代际。
- watch：最新事件来自 apply 的 changes；落后 watcher 的历史回放按 revision 范围扫描 backend，再用 key / range 过滤，而不是用 treeIndex 逐 key 找历史。
- 前缀查询：用户 key 的 B-tree 负责高效定位 key 与 revision；backend 按 revision 排序服务的是历史区间扫描与 watch 回放。

## Links

- [Core_Mechanisms（跨层主链与 revision 边界）](/docs/CS/Framework/etcd/Core_Mechanisms.md)
- [etcd](/docs/CS/Framework/etcd/etcd.md)
- [watch（历史回放与事件发布）](/docs/CS/Framework/etcd/watch.md)
- [compact（revision 代际压缩）](/docs/CS/Framework/etcd/compact.md)

## References

- [etcd v3 architecture and MVCC design](https://etcd.io/docs/v3.5/learning/)
- [google/btree - in-memory B-tree for Go](https://github.com/google/btree)
