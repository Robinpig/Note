# MVCC: The Multiversion State Machine

## Introduction

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
