## Introduction

> [!NOTE]
> 本篇以 **etcd v3.7.2** 为源码基线。compact 回收的是 MVCC 历史版本，不是 Raft log snapshot，也不会直接缩小 bbolt 文件。


可以通过client API发起人工的压缩(Compact)操作，也可以配置自动压缩策略。在自动压缩策略中，你可以根据你的业务场景选择合适的压缩模式。目前etcd支持两种压缩模式，分别是时间周期性压缩和版本号压缩

通过API发起一个Compact请求后，KV Server收到Compact请求提交到Raft模块处理，在Raft模块中提交后，Apply模块就会通过MVCC模块的Compact接口执行此压缩任务。

Compact接口首先会更新当前server已压缩的版本号，并将耗时昂贵的压缩任务保存到FIFO队列中异步执行。压缩任务执行时，它首先会压缩treeIndex模块中的keyIndex索引，其次会遍历boltdb中的key，删除已废弃的key

## Compaction Phases

v3.7.2 把一次 compaction 拆成逻辑水位、索引压缩、物理删除和完成标记四个阶段：

1. **Advance Logical Watermark**：在 `revMu` 保护下检查目标 revision，更新内存 `compactMainRev`，把 scheduled compact revision 写入 meta bucket，并立即 `ForceCommit`。从这一刻起，早于该水位的读会被拒绝，即使历史记录尚未删完。
2. **Compact Tree Index**：FIFO scheduler 调用 `kvindex.Compact`，裁剪每个 key 不再需要的 revision 代际，并计算出必须保留的 revision 集合 `keep`。
3. **Delete Backend Revisions**：按 revision 顺序分批扫描 `key` bucket，删除不在 `keep` 中的记录；每批完成后 `ForceCommit` 并按配置让出执行时间。
4. **Mark Finished**：最后一批同时写入 finished compact revision，表示物理阶段已完成。

```go
// server/storage/mvcc/kvstore.go:197-221（节选）
compactMainRev := s.compactMainRev
s.compactMainRev = rev

SetScheduledCompact(s.b.BatchTx(), rev)
// ensure that desired compaction is persisted
s.b.ForceCommit()
```

逻辑水位先推进、物理删除后完成，因此 compaction 期间仍可能需要等待后台任务。`compactMainRev` 也是 watch 判断历史是否可读的依据。

## Crash Recovery

恢复时同时读取 scheduled 与 finished 两个水位，并且**值和是否存在标记都必须一致**，才认为上次 compaction 已完成：

```go
// server/storage/mvcc/kvstore.go:224-232
func (s *store) checkPrevCompactionCompleted() bool {
    tx := s.b.ReadTx()
    tx.RLock()
    defer tx.RUnlock()
    scheduledCompact, scheduledCompactFound := UnsafeReadScheduledCompact(tx)
    finishedCompact, finishedCompactFound := UnsafeReadFinishedCompact(tx)
    return scheduledCompact == finishedCompact && scheduledCompactFound == finishedCompactFound
}
```

这组元数据还防止 revision 回退：如果最新记录是 tombstone，而进程在物理删除后、写 finished 水位前崩溃，重启后仅扫描剩余记录会得到偏小的 `currentRev`。restore 用 scheduled revision 兜底，并在 `scheduledCompact > finishedCompact` 时重新调度压缩。

```go
// server/storage/mvcc/kvstore.go:376-385（节选）
if s.currentRev < s.compactMainRev {
    s.currentRev = s.compactMainRev
}
// ...
if s.currentRev < scheduledCompact {
    s.currentRev = scheduledCompact
}
```

## Physical Compaction and Defrag

`CompactionRequest.Physical` 仍通过 Raft 进入 apply；返回前等待物理阶段 channel `Physc`，随后在 backend exchange 锁保护下 `ForceCommit`，确保 finished 水位落盘，避免 crash 后误判为未完成并重复压缩。

这里的 “physical” 指**完成 revision 记录的物理删除**，不等于 defrag：

| 操作 | 删除历史记录 | 把空闲页还给文件系统、缩小 db 文件 |
| :--- | :---: | :---: |
| MVCC compact | 是 | 否 |
| defrag | 否，只重建已有数据 | 是 |

compact 删除的 bbolt 页进入 freelist，供后续写入复用；文件大小通常保持不变。需要缩小磁盘占用时另行执行 defrag，并逐节点评估阻塞影响。

以先通过endpoint status命令获取etcd当前版本号，然后再通过etcdctl compact命令发起压缩操作即可。
```shell
# 获取etcd当前版本号
$ rev=$(etcdctl endpoint status --write-out="json" | egrep -o '"revision":[0-9]*' | egrep -o '[0-9].*')
$ echo $rev
9
# 执行压缩操作，指定压缩的版本号为当前版本号
$ etcdctl compact $rev
Compacted revision 9
```
如果你压缩命令传递的版本号小于等于当前etcd server记录的压缩版本号，etcd server会返回已压缩错误(“mvcc: required revision has been compacted”)给client。如果版本号大于当前etcd server最新的版本号，etcd server则返回一个未来的版本号错误给client(“mvcc: required revision is a future revision”)
```shell
# 压缩一个已经压缩的版本号
$ etcdctl compact $rev
Error: etcdserver: mvcc: required revision has been compacted
# 压缩一个比当前最大版号大的版本号
$ etcdctl compact 12
Error: etcdserver: mvcc: required revision is a future revision
```

## Links

- [Core_Mechanisms（compaction 的持久化与恢复顺序）](/docs/CS/Framework/etcd/Core_Mechanisms.md)
- [etcd](/docs/CS/Framework/etcd/etcd.md)
- [troubleshooting（NOSPACE 处置）](/docs/CS/Framework/etcd/troubleshooting.md)
- [tuning（--auto-compaction-mode / --quota-backend-bytes）](/docs/CS/Framework/etcd/tuning.md)
- [concurrency（STM readSet 受历史压缩影响）](/docs/CS/Framework/etcd/concurrency.md)

## References

- [etcd v3.7.2 - MVCC compaction scheduling and restore](https://github.com/etcd-io/etcd/blob/v3.7.2/server/storage/mvcc/kvstore.go)
- [etcd v3.7.2 - physical compaction implementation](https://github.com/etcd-io/etcd/blob/v3.7.2/server/storage/mvcc/kvstore_compaction.go)
- [etcd v3.7.2 - key index compaction](https://github.com/etcd-io/etcd/blob/v3.7.2/server/storage/mvcc/key_index.go)
- [etcd v3.7.2 - Compaction RPC](https://github.com/etcd-io/etcd/blob/v3.7.2/server/etcdserver/v3_server.go)
