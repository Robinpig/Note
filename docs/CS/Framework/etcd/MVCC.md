# MVCC: The Multiversion State Machine

## Introduction

etcd v3 不是“把全部数据加载进内存”的内存数据库。它把**用户 key 的 revision 代际索引**放在内存，把**每个 revision 的完整 `mvccpb.KeyValue`** 持久化在 backend 的 bbolt 文件中；尚未提交的 backend 写缓冲还会叠加在 bbolt 视图之上。内存占用主要由 key、revision 链表、索引和缓冲决定，而不是全部历史 value。

etcd v2 则是内存数据库：整个 store 由大锁保护，持久化主要依赖把内存状态序列化为快照。它的读写锁竞争明显，watch 又只保留固定长度的历史事件窗口；写请求较多或网络抖动时，窗口淘汰会迫使客户端重新全量拉取。v3 用 MVCC 同时解决了历史版本、多 key 事务和 watch 回放问题。

> [!NOTE]
> 本篇以 **etcd v3.7.2** 为源码基线。跨模块的 `Propose → Raft → Apply → MVCC` 顺序见 [Core_Mechanisms](/docs/CS/Framework/etcd/Core_Mechanisms.md)；这里只展开状态机内部的数据模型、事务与可见性边界。

## Components

MVCC 把一次键空间变更拆成四种职责：

| 组件 | 保存什么 | 不负责什么 |
| :--- | :--- | :--- |
| `store` | `currentRev`、`compactMainRev`、事务生命周期与 revision 分配 | Raft 日志复制、客户端等待 |
| `treeIndex` | 用户 key 到 revision 代际的 B-tree 索引，以及每个 key 的 generation / revision 链表 | 不保存完整历史 value，也不是磁盘指针表 |
| `backend` | bbolt 中的 revision → 完整 `mvccpb.KeyValue`，以及尚未提交的写缓冲 | 不替 Raft 决定提交顺序 |
| `watchableStore` | watcher 分组、最新事件发布、历史回放与 victim 重试 | 不改变 MVCC 的原子提交边界 |

用户数据位于 backend 的 `key` bucket：**磁盘 key 是 revision，磁盘 value 是完整的 `mvccpb.KeyValue`**。`meta` bucket 保存 compact、consistent index 等元数据；lease、alarm、member、auth 等模块也写入同一个 bbolt 文件，但使用各自的 bucket。

## Revision Model

一次原子事务只推进一次 main revision；同一事务中的多个变更使用 sub 排序：

```text
Raft entry  ──apply──>  MVCC write txn  ──>  main = currentRev + 1
                                          sub = 0, 1, 2, ...
```

- `revision` 在 **apply 阶段**分配，不在 API 或 Propose 阶段分配。
- 空 store 恢复后 `currentRev = 1`、`compactMainRev = -1`，因此第一次写得到 `(2, 0)`。
- 一个 Txn 修改 3 个 key，它们共享 main，sub 依次为 `0/1/2`；没有实际变更的 Txn 不推进 `currentRev`。
- `sub` 是存储层事务内顺序，不直接暴露在 `KeyValue.ModRevision` 中；后者只表示 main revision。

正常 revision 编码为 `main(8, big-endian) + '_' + sub(8, big-endian)`，共 17 字节；tombstone 在尾部追加 `'t'`，共 18 字节。编码细节见 [boltdb](/docs/CS/Framework/etcd/boltdb.md)。

```go
// server/storage/mvcc/kvstore_txn.go:174-184, 204-207
func (s *store) Write(trace *traceutil.Trace) TxnWrite {
    s.mu.RLock()
    tx := s.b.BatchTx()
    tx.LockInsideApply()
    tw := &storeTxnWrite{
        storeTxnCommon: storeTxnCommon{s, tx, 0, 0, trace},
        tx:             tx,
        beginRev:       s.currentRev,
        changes:        make([]*mvccpb.KeyValue, 0, 4),
    }
    return newMetricsTxnWrite(tw)
}

func (tw *storeTxnWrite) Put(key, value []byte, lease lease.LeaseID) int64 {
    tw.put(key, value, lease)
    return tw.beginRev + 1
}
```

## Response Metadata

`ResponseHeader.Revision` 是请求执行时 KV store 的 revision，不等于返回 key 自身的 `ModRevision`。普通读响应的 header 表示读取快照；watch progress 响应的 header 表示进度，后续事件 revision 更高。
etcd 的 MVCC 状态机由两半拼成：内存里的 `treeIndex`（B 树，保存用户 key → revision 的映射）与磁盘上的 bbolt（保存 revision → `KeyValue`）。一次读先在内存索引里把 key 翻成 revision，再回 bbolt 取增量；一次写生成全局递增的 `(Main, Sub)` revision，把 `KeyValue` 写进 bbolt 的 `key` bucket，同时更新内存索引。配额与压缩围绕这套增量结构设计，apply 细节见 [request](/docs/CS/Framework/etcd/request.md)。

> 版本基线：etcd 3.7.4（commit 2e8a5c99，Go 1.26）。以下片段均取自该 tag。

四个从源码核验出来的反直觉点：

- **`store` 不再直接暴露 ReadTx / BatchTx / Buffer 三件套**：3.7.4 的 `store` 嵌入 `ReadView` / `WriteView` 两个接口，写事务用 `LockInsideApply()`，后台提交走 `LockOutsideApply()`，读事务则分 `ReadTx` 与 `ConcurrentReadTx` 两种模式。
- **`treeIndex` 是泛型 B 树**：字段是 `tree *btree.BTree[*keyIndex]`；`keyIndex` 用一组 `generations` 记录「创建 → 删除 → 再创建」的多段历史，删除不是抹掉数据，而是打 tombstone 并开启新 generation。
- **revision 是二元组且有明确字节编码**：`(Main, Sub)` 被编码成 8 字节大端 Main + `_` + 8 字节大端 Sub，tombstone 再追加一个 `'t'` 标记字节；同一 Main 下的不同 Sub 属于同一个原子事务。
- **读不总是打到 bbolt**：`baseReadTx.UnsafeRange` 先查内存 `buf`，命中即返回；`ConcurrentReadTx` 会复制一份 buffer 快照，让只读负载与正在阻塞的写并发。

## Why MVCC Replaced v2

etcd v2 是整库大锁的内存数据库，读锁与写锁互相阻塞；watch 依赖滑动窗口，容量固定 1000，写多或网络抖动时事件丢失，client 只能全量拉取，进而产生 expensive request 甚至雪崩。3.7.4 仍保留 v2 的实现代码，`EventHistory` 就是那个环形窗口：

```go
type EventHistory struct {
	Queue      eventQueue
	StartIndex uint64
	LastIndex  uint64
	rwl        sync.RWMutex
}
```

`KeyValue` 同时携带业务值与版本元数据：
窗口容量由 `newWatchHub(1000)` 固定；`addEvent` 把新事件插进队列后更新 `StartIndex` / `LastIndex`，超出容量即淘汰最旧事件。v3 把历史版本落到 bbolt，watch 从「最近 1000 条」变成「从指定 revision 到当前 revision 的全部增量」，可靠性不再受窗口大小限制，见 [watch](/docs/CS/Framework/etcd/watch.md)。

## Revision and Bucket Key

`Revision` 是 `(Main, Sub)` 二元组；`BucketKey` 在它之上加一个 `tombstone` 标志。bbolt 的 key 就是编码后的 `BucketKey`：

```go
type Revision struct {
	// Main is the main revision of a set of changes that happen atomically.
	Main int64
	// Sub is the sub revision of a change in a set of changes that happen
	// atomically. Each change has different increasing sub revision in that
	// set.
	Sub int64
}

func (a Revision) GreaterThan(b Revision) bool {
	if a.Main > b.Main {
		return true
	}
	if a.Main < b.Main {
		return false
	}
	return a.Sub > b.Sub
}

// BucketKey indicates modification of the key-value space.
// The set of changes that share same main revision changes the key-value space atomically.
type BucketKey struct {
	Revision
	tombstone bool
}

func BucketKeyToBytes(rev BucketKey, bytes []byte) []byte {
	binary.BigEndian.PutUint64(bytes, uint64(rev.Main))
	bytes[8] = '_'
	binary.BigEndian.PutUint64(bytes[9:], uint64(rev.Sub))
	if rev.tombstone {
		switch len(bytes) {
		case revBytesLen:
			bytes = append(bytes, markTombstone)
		case markedRevBytesLen:
			bytes[markBytePosition] = markTombstone
		}
	}
	return bytes
}
```

- `CreateRevision` 在当前 generation 首次创建时确定，后续更新沿用。
- `ModRevision` 是最后一次修改的 main revision。
- `Version` 在同一 generation 内逐次递增；delete 后重新创建会从 1 开始。
- delete 事件的 `KeyValue` 只带 key 与修改 revision，不保留原 value；`PrevKv` 是否返回由请求选项决定。

## Read Path

`ReadTx` 在一次读取开始时固定 `compactMainRev` 与 `currentRev`。只读请求使用 `ConcurrentReadTx()` 复制读缓冲，减少与正在提交的 backend 写事务之间的阻塞。

1. 请求 revision 大于快照 `currentRev` 时返回 `ErrFutureRev`；`rev <= 0` 先归一为 `currentRev`，归一后小于 `compactMainRev` 才返回 `ErrCompacted`。
2. `treeIndex` 按用户 key 范围和目标 revision 选出每个 key 对应的 revision。
3. backend 的 `UnsafeRange` 先查写缓冲，未命中再查 bbolt，并合并结果；单 key 查询强制 `limit = 1`，避免缓冲与磁盘中的同一记录重复。
4. 将完整 value 反序列化为 `mvccpb.KeyValue`，返回时 header 携带读取快照的 revision。

```go
// server/storage/mvcc/kvstore_txn.go:108-150（节选）
revpairs, total := tr.s.kvindex.Revisions(key, end, rev, int(ro.Limit), ro.WithTotalCount)
// ...
for i, revpair := range revpairs[:len(kvs)] {
    revBytes = RevToBytes(revpair, revBytes)
    _, vs := tr.tx.UnsafeRange(schema.Key, revBytes, nil, 0)
    // ...
    kv := &mvccpb.KeyValue{}
    if err := proto.Unmarshal(vs[0], kv); err != nil {
        tr.s.lg.Fatal("failed to unmarshal mvccpb.KeyValue", zap.Error(err))
    }
    kvs[i] = kv
}
```

这里有两个容易混淆的“范围扫描”：**用户 key / 前缀查询**由 treeIndex 定位；**watch 历史回放**按 backend 的 revision 区间扫描。后者不是因为 revision 排序就能直接回答任意用户前缀查询。

## Write Path

写事务固定 `beginRev = currentRev`，每次 put / delete 都使用 `beginRev + 1` 作为 main，以 `len(changes)` 作为 sub：

```go
// server/storage/mvcc/kvstore_txn.go:223-261（节选）
rev := tw.beginRev + 1
// ...
idxRev := Revision{Main: rev, Sub: int64(len(tw.changes))}
ibytes = RevToBytes(idxRev, ibytes)

kv := &mvccpb.KeyValue{
    Key:            key,
    Value:          value,
    CreateRevision: c,
    ModRevision:    rev,
    Version:        ver,
    Lease:          int64(leaseID),
}

d, err := proto.Marshal(kv)
// ...
tw.tx.UnsafeSeqPut(schema.Key, ibytes, d)
tw.s.kvindex.Put(key, idxRev)
tw.changes = append(tw.changes, kv)
```

delete 使用带 tombstone 标记的 revision key，value 只序列化 `Key`；随后调用 `kvindex.Tombstone` 开启新的 generation。整个事务的变更先累积在 `changes`，供 watch 在提交边界发布事件。

## Commit Boundary

“提交”在 etcd 中至少有三层，不能混用：

| 边界 | 含义 | 保证 |
| :--- | :--- | :--- |
| Raft commit | entry 已被多数派复制，获得全局顺序 | 尚不代表本地状态机已应用 |
| MVCC `TxnWrite.End` | 推进 `currentRev` 并发布本次事务的可见状态 | 同事务变更对外原子可见 |
| backend commit / WAL sync | bbolt 事务或 WAL 真正落盘 | 决定 crash 后的持久状态 |

普通 put 只进入 backend 写缓冲，不必每次都立即提交 bbolt；达到 batch limit 才提交。**只要本批存在 delete，就必须在解锁时提交**，否则后续请求可能从 bbolt 读到 stale value，破坏线性一致性。put 有覆盖在 bbolt 之上的读缓冲，delete 没有等价的安全读取路径。

```go
// server/storage/mvcc/kvstore_txn.go:209-220
func (tw *storeTxnWrite) End() {
    if len(tw.changes) != 0 {
        tw.s.revMu.Lock()
        tw.s.currentRev++
    }
    tw.tx.Unlock()
    if len(tw.changes) != 0 {
        tw.s.revMu.RUnlock()
    }
    tw.s.mu.RUnlock()
}
```

watchable store 在底层 `TxnWrite.End()` **之前**调用 `notify`，并在整个过程中持有 watchable store 锁，避免异步发布方看到 revision 已推进但 watcher 状态尚未准备好的半完成状态：

```go
// server/storage/mvcc/watchable_store_txn.go（节选）
tw.s.mu.Lock()
tw.s.notify(rev, evs)
tw.TxnWrite.End()
tw.s.mu.Unlock()
```

因此，watch 事件的产生与 MVCC 可见性属于同一个原子边界，但网络发送可以滞后；发送阻塞由 victim 机制处理，不回滚写事务。

## Restore

启动或恢复 backend 时，etcd 从 `key` bucket 按 revision 顺序扫描，解析完整 `mvccpb.KeyValue` 重建 treeIndex，并恢复 key 与 lease 的关联。历史 value 不是“相对上一版本的增量”，每个 revision 都保存独立完整的值。

恢复同时读取 finished / scheduled compact revision：

- `finishedCompact` 恢复逻辑压缩水位；若扫描到的最大 revision 更小，`currentRev` 不能低于它。
- 若上次在删除最新 tombstone 后、写入 finished 水位前崩溃，`scheduledCompact` 防止 revision 回退。
- `scheduledCompact > finishedCompact` 时重新调度压缩，继续完成上次未完成的工作。

## Put Example
`ResponseHeader.Revision` 是请求 apply 后的当前 revision；`KeyValue.CreateRevision` / `ModRevision` / `Version` 分别记录最近创建、最近修改与修改次数，删除会把 `Version` 归零。

## treeIndex and keyIndex

`index` 接口把「key → revision」的查询能力定死，`treeIndex` 是它在内存里的实现：

```go
type index interface {
	Get(key []byte, atRev int64) (rev, created Revision, ver int64, err error)
	Range(key, end []byte, atRev int64, limit int, withTotalCount bool) (keys [][]byte, modifies, creates []Revision, versions []int64, totalCount int)
	Revisions(key, end []byte, atRev int64, limit int, withTotalCount bool) ([]Revision, int)
	CountRevisions(key, end []byte, atRev int64) int
	Put(key []byte, rev Revision)
	Tombstone(key []byte, rev Revision) error
	Compact(rev int64) map[Revision]struct{}
	Keep(rev int64) map[Revision]struct{}
	Equal(b index) bool

	Insert(ki *keyIndex)
	KeyIndex(ki *keyIndex) *keyIndex
}

type treeIndex struct {
	sync.RWMutex
	tree *btree.BTree[*keyIndex]
	lg   *zap.Logger
}

func (ti *treeIndex) Put(key []byte, rev Revision) {
	keyi := &keyIndex{key: key}

	ti.Lock()
	defer ti.Unlock()
	okeyi, ok := ti.tree.Get(keyi)
	if !ok {
		keyi.put(ti.lg, rev.Main, rev.Sub)
		ti.tree.ReplaceOrInsert(keyi)
		return
	}
	okeyi.put(ti.lg, rev.Main, rev.Sub)
}
```

`keyIndex` 的历史不是一条扁平数组，而是按「generation」分段：tombstone 结束当前 generation 并开一个空的新 generation，compact 会从最老的 generation 开始裁掉过期版本。

```go
// For example: put(1.0);put(2.0);tombstone(3.0);put(4.0);tombstone(5.0) on key "foo"
// generate a keyIndex:
// key:     "foo"
// modified: 5
// generations:
//
//	{empty}
//	{4.0, 5.0(t)}
//	{1.0, 2.0, 3.0(t)}
type keyIndex struct {
	key         []byte
	modified    Revision // the main rev of the last modification
	generations []generation
}

// put puts a revision to the keyIndex.
func (ki *keyIndex) put(lg *zap.Logger, main int64, sub int64) {
	rev := Revision{Main: main, Sub: sub}

	if !rev.GreaterThan(ki.modified) {
		lg.Panic(
			"'put' with an unexpected smaller revision",
			zap.Int64("given-revision-main", rev.Main),
			zap.Int64("given-revision-sub", rev.Sub),
			zap.Int64("modified-revision-main", ki.modified.Main),
			zap.Int64("modified-revision-sub", ki.modified.Sub),
		)
	}
	if len(ki.generations) == 0 {
		ki.generations = append(ki.generations, generation{})
	}
	g := &ki.generations[len(ki.generations)-1]
	if len(g.revs) == 0 { // create a new key
		keysGauge.Inc()
		g.created = rev
	}
	g.revs = append(g.revs, rev)
	g.ver++
	ki.modified = rev
}
```

## Store, ReadView and WriteView

`store` 把读、写视图作为匿名字段嵌进来，并用 `revMu` 保护 `currentRev` 与 `compactMainRev`：

```go
type store struct {
	ReadView
	WriteView

	cfg StoreConfig

	// mu read locks for txns and write locks for non-txn store changes.
	mu sync.RWMutex

	b       backend.Backend
	kvindex index

	le lease.Lessor

	// revMuLock protects currentRev and compactMainRev.
	// Locked at end of write txn and released after write txn unlock lock.
	// Locked before locking read txn and released after locking.
	revMu sync.RWMutex
	// currentRev is the revision of the last completed transaction.
	currentRev int64
	// compactMainRev is the main revision of the last compaction.
	compactMainRev int64

	fifoSched schedule.Scheduler
	// ... 省略 stopc / lg / hashes 字段 ...
}
```

`ReadView` / `WriteView` 只是把 `KV` 接口拆成两半，便于 `watchableStore` 替换实现（写事务末尾才能发 watch 事件）：

```go
type readView struct{ kv KV }

func (rv *readView) FirstRev() int64 {
	return rv.kv.FirstRev()
}

func (rv *readView) Rev() int64 {
	return rv.kv.Rev()
}

func (rv *readView) Range(ctx context.Context, key, end []byte, ro RangeOptions) (r *RangeResult, err error) {
	return rv.kv.Range(ctx, key, end, ro)
}

type writeView struct{ kv KV }

func (wv *writeView) DeleteRange(key, end []byte) (n, rev int64) {
	return wv.kv.DeleteRange(key, end)
}

func (wv *writeView) Put(key, value []byte, lease lease.LeaseID) (rev int64) {
	return wv.kv.Put(key, value, lease)
}
```

## Read Path: Buffer Before Bolt

`store.Read` 在 `ConcurrentReadTxMode` 下取一个带 buffer 快照的读事务，否则复用 backend 的共享 `readTx`：

```go
func (s *store) Read(mode ReadTxMode, trace *traceutil.Trace) TxnRead {
	s.mu.RLock()
	s.revMu.RLock()
	// For read-only workloads, we use shared buffer by copying transaction read buffer
	// for higher concurrency with ongoing blocking writes.
	// For write/write-read transactions, we use the shared buffer
	// rather than duplicating transaction read buffer to avoid transaction overhead.
	var tx backend.ReadTx
	if mode == ConcurrentReadTxMode {
		tx = s.b.ConcurrentReadTx()
	} else {
		tx = s.b.ReadTx()
	}

	tx.RLock() // RLock is no-op. concurrentReadTx does not need to be locked after it is created.
	firstRev, rev := s.compactMainRev, s.currentRev
	s.revMu.RUnlock()
	return newMetricsTxnRead(&storeTxnRead{storeTxnCommon{s, tx, firstRev, rev, trace}, tx})
}
```

一次 `Range` 先用内存索引把 key 翻成 revision 列表，再交给 backend 的 `UnsafeRange` 取 value；后者先查 `buf`，不足部分才用 bbolt cursor 补：

```go
func (baseReadTx *baseReadTx) UnsafeRange(bucketType Bucket, key, endKey []byte, limit int64) ([][]byte, [][]byte) {
	if endKey == nil {
		// forbid duplicates for single keys
		limit = 1
	}
	if limit <= 0 {
		limit = math.MaxInt64
	}
	if limit > 1 && !bucketType.IsSafeRangeBucket() {
		panic("do not use unsafeRange on non-keys bucket")
	}
	keys, vals := baseReadTx.buf.Range(bucketType, key, endKey, limit)
	if int64(len(keys)) == limit {
		return keys, vals
	}
	// find/cache bucket
	bn := bucketType.ID()
	baseReadTx.txMu.RLock()
	bucket, ok := baseReadTx.buckets[bn]
	baseReadTx.txMu.RUnlock()
	lockHeld := false
	if !ok {
		baseReadTx.txMu.Lock()
		lockHeld = true
		bucket = baseReadTx.tx.Bucket(bucketType.Name())
		baseReadTx.buckets[bn] = bucket
	}

	// ignore missing bucket since may have been created in this batch
	if bucket == nil {
		if lockHeld {
			baseReadTx.txMu.Unlock()
		}
		return keys, vals
	}
	if !lockHeld {
		baseReadTx.txMu.Lock()
	}
	c := bucket.Cursor()
	baseReadTx.txMu.Unlock()

	k2, v2 := unsafeRange(c, key, endKey, limit-int64(len(keys)))
	return append(k2, keys...), append(v2, vals...)
}
```

`concurrentReadTx` 的 `RLock` 是空操作，`RUnlock` 只做 `txWg.Done()`——它靠复制 buffer 而不是持锁来避免阻塞写：

```go
type concurrentReadTx struct {
	baseReadTx
}

func (rt *concurrentReadTx) Lock()   {}
func (rt *concurrentReadTx) Unlock() {}

// RLock is no-op. concurrentReadTx does not need to be locked after it is created.
func (rt *concurrentReadTx) RLock() {}

// RUnlock signals the end of concurrentReadTx.
func (rt *concurrentReadTx) RUnlock() { rt.txWg.Done() }
```

## Write Path: Put

写事务的 `Put` 只记录 change 并返回 `beginRev + 1`；真正落库在内部的 `put`：先从索引拿旧 lease，用 `(rev, len(changes))` 生成 Sub，序列化 `KeyValue` 后 `UnsafeSeqPut` 到 `schema.Key` bucket，再更新 `treeIndex`。

```go
func (tw *storeTxnWrite) Put(key, value []byte, lease lease.LeaseID) int64 {
	tw.put(key, value, lease)
	return tw.beginRev + 1
}

func (tw *storeTxnWrite) put(key, value []byte, leaseID lease.LeaseID) {
	rev := tw.beginRev + 1
	c := rev
	oldLease := lease.NoLease

	// if the key exists before, use its previous created and
	// get its previous leaseID
	_, created, ver, err := tw.s.kvindex.Get(key, rev)
	if err == nil {
		c = created.Main
		oldLease = tw.s.le.GetLease(lease.LeaseItem{Key: string(key)})
		tw.trace.Step("get key's previous created_revision and leaseID")
	}
	ibytes := NewRevBytes()
	idxRev := Revision{Main: rev, Sub: int64(len(tw.changes))}
	ibytes = RevToBytes(idxRev, ibytes)

	ver = ver + 1
	kv := &mvccpb.KeyValue{
		Key:            key,
		Value:          value,
		CreateRevision: c,
		ModRevision:    rev,
		Version:        ver,
		Lease:          int64(leaseID),
	}

	d, err := proto.Marshal(kv)
	if err != nil {
		tw.storeTxnCommon.s.lg.Fatal(
			"failed to marshal mvccpb.KeyValue",
			zap.Error(err),
		)
	}

	tw.trace.Step("marshal mvccpb.KeyValue")
	tw.tx.UnsafeSeqPut(schema.Key, ibytes, d)
	tw.s.kvindex.Put(key, idxRev)
	tw.changes = append(tw.changes, kv)
	tw.trace.Step("store kv pair into bolt db")

	if oldLease == leaseID {
		tw.trace.Step("attach lease to kv pair")
		return
	}
	// ... 省略旧 lease Detach 与新 lease Attach ...
	tw.trace.Step("attach lease to kv pair")
}
```

`End()` 只在真有 change 时推进 `currentRev`，并在 `revMu` 保护下解锁 batchTx——这样新读事务不会在写回完成前打开：

```go
func (tw *storeTxnWrite) End() {
	// only update index if the txn modifies the mvcc state.
	if len(tw.changes) != 0 {
		// hold revMu lock to prevent new read txns from opening until writeback.
		tw.s.revMu.Lock()
		tw.s.currentRev++
	}
	tw.tx.Unlock()
	if len(tw.changes) != 0 {
		tw.s.revMu.Unlock()
	}
	tw.s.mu.RUnlock()
}
```

<div style="text-align: center;">

![put](img/put-server.png)

</div>

<p style="text-align: center;">Fig.1. put</p>

一次 `put hello world` 的顺序是：

1. gRPC `KVServer` 完成鉴权、请求大小与配额检查，注册 request ID 对应的 waiter，然后向 Raft Propose。
2. Raft 将 entry 复制到多数派并提交；本节点按日志顺序 apply。
3. MVCC 此时才分配 `(main, sub)`，更新 backend 缓冲与 treeIndex，记录 `changes`。
4. watchable `End` 在锁内先 `notify`，再调用底层 `End` 推进 `currentRev`；随后返回 apply 路径并唤醒 waiter。
5. backend 按批处理策略提交；WAL / Raft 持久化与 snapshot 安全边界由上层协调。

NOSPACE 的一个关键细节是：quota applier 先执行 Put，再根据入口空间预算返回 `ErrNoSpace`，所以触发配额的写可能已经生效；NOSPACE Alarm 本身也要经 Raft apply，成员才进入拒绝后续写入的状态。请求超时同样只清理 waiter，不撤回已提交 entry。详细入口、限流和告警顺序见 [request](/docs/CS/Framework/etcd/request.md) 与 [troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md)。

## Links

- [treeIndex（用户 key 与 revision 代际索引）](/docs/CS/Framework/etcd/treeIndex.md)
- [read（线性读如何等待 apply）](/docs/CS/Framework/etcd/read.md)
- [watch（事件发布、历史回放与 victim）](/docs/CS/Framework/etcd/watch.md)
- [concurrency（STM 的 readSet 依赖 revision）](/docs/CS/Framework/etcd/concurrency.md)

## References

- [etcd v3.7.2 - MVCC transaction implementation](https://github.com/etcd-io/etcd/blob/v3.7.2/server/storage/mvcc/kvstore_txn.go)
- [etcd v3.7.2 - revision encoding](https://github.com/etcd-io/etcd/blob/v3.7.2/server/storage/mvcc/revision.go)
- [etcd v3.7.2 - key index](https://github.com/etcd-io/etcd/blob/v3.7.2/server/storage/mvcc/key_index.go)
- [etcd v3.7.2 - backend read transaction](https://github.com/etcd-io/etcd/blob/v3.7.2/server/storage/backend/read_tx.go)
- [etcd v3.7.2 - backend batch transaction](https://github.com/etcd-io/etcd/blob/v3.7.2/server/storage/backend/batch_tx.go)
- [etcd v3.7.2 - watch transaction publication](https://github.com/etcd-io/etcd/blob/v3.7.2/server/storage/mvcc/watchable_store_txn.go)
- [etcd v3.7.2 - MVCC restore and compaction metadata](https://github.com/etcd-io/etcd/blob/v3.7.2/server/storage/mvcc/kvstore.go)
## Quota, Alarm and Compaction

bbolt 只有一个 `key` bucket 承载所有用户数据，etcd 不做分片。配额常量定义了软默认与建议上限：

```go
const (
	// DefaultQuotaBytes is the number of bytes the backend Size may
	// consume before exceeding the space quota.
	DefaultQuotaBytes = int64(2 * 1024 * 1024 * 1024) // 2GB
	// MaxQuotaBytes is the maximum number of bytes suggested for a backend
	// quota. A larger quota may lead to degraded performance.
	MaxQuotaBytes = int64(8 * 1024 * 1024 * 1024) // 8GB
)
```

超限不是单纯拒绝请求：接入层 `qa.check` 会发一条 `NOSPACE` alarm，经 Raft 同步并持久化；apply 路径每条命令都会检查告警并拒绝写入。因此**调大 `quota-backend-bytes` 不会立即恢复写入**，必须 `etcdctl alarm disarm`，详见 [troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md)。

compact 负责回收历史版本：它把过期 revision 从 `treeIndex` 与 bbolt 中裁掉，但只是把空间标记为 Free 供后续复用，**不会缩小 db 文件**；要真正回收磁盘得跑 defrag，它会重写整个 db，对服务影响较大，不建议在生产频繁执行。配额设为 `0` 走 2GB 默认，设为负数则禁用配额，可能让 db 失控。

## Links

- [etcd（总览与架构）](/docs/CS/Framework/etcd/etcd.md)
- [treeIndex（内存索引与 generation）](/docs/CS/Framework/etcd/treeIndex.md)
- [boltdb（底层存储结构）](/docs/CS/Framework/etcd/boltdb.md)
- [compact（历史版本回收）](/docs/CS/Framework/etcd/compact.md)
- [lease（Put 时的 Attach / Detach）](/docs/CS/Framework/etcd/lease.md)
- [concurrency（STM 的 revision 依赖）](/docs/CS/Framework/etcd/concurrency.md)

## References

1. [etcd v3.7.4 源码（server/storage/mvcc/revision.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/storage/mvcc/revision.go)
2. [etcd v3.7.4 源码（server/storage/mvcc/index.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/storage/mvcc/index.go)
3. [etcd v3.7.4 源码（server/storage/mvcc/kvstore.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/storage/mvcc/kvstore.go)
4. [etcd v3.7.4 源码（server/storage/mvcc/kvstore_txn.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/storage/mvcc/kvstore_txn.go)
5. [etcd v3.7.4 源码（server/storage/backend/read_tx.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/storage/backend/read_tx.go)
6. [etcd v3.7.4 源码（server/storage/quota.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/storage/quota.go)
