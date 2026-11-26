# Compact

## Introduction

> [!NOTE]
> 本篇以 **etcd v3.7.2** 为源码基线。compact 回收的是 MVCC 历史版本，不是 Raft log snapshot，也不会直接缩小 bbolt 文件。

Compact（压缩）负责回收 [MVCC](/docs/CS/Framework/etcd/MVCC.md) 不断累积的历史版本占用的空间。etcd 保留每个 key 的完整修改历史，若不定期压缩，[boltdb](/docs/CS/Framework/etcd/boltdb.md) 的 db 文件会持续膨胀直至触发 `NOSPACE` alarm。压缩既可由客户端 API 人工发起，也可配置为自动周期/按版本执行。

> 版本基线：etcd 3.7.4（commit 2e8a5c99，Go 1.26）。以下片段均取自该 tag。

从源码核实的关键点：

- **压缩是异步的**：接口先更新服务端的 `compactMainRev` 并把耗时任务放进 FIFO 队列，后台依次执行；客户端收到 `Compacted revision N` 并不代表磁盘空间已释放。
- **`compact` 只删逻辑条目，不缩文件**：删除的 page 进 bbolt freelist 等待复用，db 文件大小不变，必须再 `defrag` 才归还磁盘（见 [boltdb](/docs/CS/Framework/etcd/boltdb.md) 的 freelist 段）。
- **3.7 的 revision 已重构**：`revision{main,sub}` → `Revision{Main,Sub}`、`revToBytes` → `RevToBytes`，压缩代码里用 `BytesToRev` / `RevToBytes` 与 `schema.Key` bucket。

## Manifestation and Errors

通过 `endpoint status` 取当前 revision，再 `etcdctl compact` 发起压缩：

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
# 取当前 revision
$ rev=$(etcdctl endpoint status --write-out="json" | egrep -o '"revision":[0-9]*' | egrep -o '[0-9].*')
$ etcdctl compact $rev
Compacted revision 9
```

服务端对压缩点的两种非法输入有明确哨兵错误，定义在 `server/storage/mvcc/kvstore.go`：

```go
var (
	ErrCompacted = errors.New("mvcc: required revision has been compacted")
	ErrFutureRev = errors.New("mvcc: required revision is a future revision")
)
```

经 gRPC 包装后，客户端看到的是带 `etcdserver: mvcc:` 前缀、`codes.OutOfRange` 的 `ErrGRPCCompacted`（详见 [troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md)）：

```shell
# 压缩一个已压缩的版本号
$ etcdctl compact $rev
Error: etcdserver: mvcc: required revision has been compacted
# 压缩一个比当前最大版本还大的版本号
$ etcdctl compact 12
Error: etcdserver: mvcc: required revision is a future revision
```

## The Compaction Pipeline

请求进入后：KV Server 把 Compact 打包成提案交给 Raft；提交后 apply 模块调 MVCC 的 `Compact`。核心是 `scheduleCompaction`（`server/storage/mvcc/kvstore_compaction.go`）——先用内存索引算出需保留的 revision 集合 `keep`，再分批扫描 bbolt 的 key bucket 删除不在 keep 里的条目：

```go
func (s *store) scheduleCompaction(compactMainRev, prevCompactRev int64) (KeyValueHash, error) {
	totalStart := time.Now()
	keep := s.kvindex.Compact(compactMainRev)
	indexCompactionPauseMs.Observe(float64(time.Since(totalStart) / time.Millisecond))

	end := make([]byte, 8)
	binary.BigEndian.PutUint64(end, uint64(compactMainRev+1))

	batchNum := s.cfg.CompactionBatchLimit
	h := newKVHasher(prevCompactRev, compactMainRev, keep)
	last := make([]byte, 8+1+8)
	for {
		tx := s.b.BatchTx()
		tx.LockOutsideApply()
		keys, values := tx.UnsafeRange(schema.Key, last, end, int64(batchNum))
		for i := range keys {
			rev := BytesToRev(keys[i])
			if _, ok := keep[rev]; !ok {
				tx.UnsafeDelete(schema.Key, keys[i])
				keyCompactions++
			}
			h.WriteKeyValue(keys[i], values[i])
		}
		// ... 省略：未满批次则提交、写 finishedCompact、返回 hash
	}
}
```

`batchNum` 即 `--compaction-batch-limit`，控制每批删除多少条目，避免一次长事务阻塞 apply。`newKVHasher` 计算压缩前后的一致性哈希，供 [monitoring](/docs/CS/Framework/etcd/monitoring.md) 的 compact hash 校验使用。

## keyIndex Compaction

`keep` 集合来自 `treeIndex.Compact`，它遍历每个 `keyIndex` 调 `compact`（`server/storage/mvcc/key_index.go`）。注意 3.7 把压缩拆成了 `compact` / `keep` / `doCompact`：`doCompact` 从最新往回走（`generation.walk` 是降序），把"≤ atRev 的最大那个 revision"放进 `available`：

```go
func (ki *keyIndex) doCompact(atRev int64, available map[Revision]struct{}) (genIdx int, revIndex int) {
	// walk until reaching the first revision smaller or equal to "atRev",
	// and add the revision to the available map
	f := func(rev Revision) bool {
		if rev.Main <= atRev {
			available[rev] = struct{}{}
			return false
		}
		return true
	}
	// ... 省略：按 generation 逐代 walk，定位保留位置
}
```

`compact` 用 `doCompact` 的结果裁剪 `generations`：删掉压缩点之前的历史版本，若某代被清空则整代移除：

```go
func (ki *keyIndex) compact(lg *zap.Logger, atRev int64, available map[Revision]struct{}) {
	genIdx, revIndex := ki.doCompact(atRev, available)

	g := &ki.generations[genIdx]
	if !g.isEmpty() {
		if revIndex != -1 {
			g.revs = g.revs[revIndex:]
		}
	}
	// remove the previous generations.
	ki.generations = ki.generations[genIdx:]
}
```

"留一个"策略很关键：压缩后 key 仍可读到不早于 `atRev` 的最新状态，不必立刻从索引删除。若 `atRev` 恰好是 tombstone，`keep` 方法会跳过它（与 `compact` 行为不同），以保证 hash 与历史版本一致。

## Auto Compaction

生产应配置自动压缩，避免人工介入：

```shell
--auto-compaction-mode=periodic --auto-compaction-retention=1h
# 或
--auto-compaction-mode=revision --auto-compaction-retention=1000
```

两种模式的实际触发时机与直觉不同（详见 [troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md)）：

- `revision` 模式按数量保留，检查周期固定为 5 分钟，每次压到 `最新 revision - retention`，**不是**到阈值立即压缩。
- `periodic` 模式把窗口切成 10 份、每份记一个 revision，**首次压缩发生在满一个完整周期之后**，之后按 1/10 周期滑动。设 `10h` 不是"10 小时才动一次"，而是"首次 10 小时后，此后每小时一次"。

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
- [MVCC](/docs/CS/Framework/etcd/MVCC.md)
- [boltdb](/docs/CS/Framework/etcd/boltdb.md)
- [treeIndex](/docs/CS/Framework/etcd/treeIndex.md)
- [troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md)
- [tuning](/docs/CS/Framework/etcd/tuning.md)
- [concurrency](/docs/CS/Framework/etcd/concurrency.md)

## References

1. [etcd v3.7.4 源码（server/storage/mvcc/kvstore_compaction.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/storage/mvcc/kvstore_compaction.go)
2. [etcd v3.7.4 源码（server/storage/mvcc/key_index.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/storage/mvcc/key_index.go)
3. [etcd v3.7.4 源码（server/storage/mvcc/kvstore.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/storage/mvcc/kvstore.go)
4. [etcd Documentation - Maintenance](https://etcd.io/docs/v3.7/op-guide/maintenance/)
