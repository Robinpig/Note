# TreeIndex

## Introduction

`treeIndex` 是 etcd v3 **内存中的键索引模块**，负责把用户 key 映射到它的 revision 代际信息。它基于 Google 开源的 [btree](https://github.com/google/btree) 内存 B-tree 库实现：treeIndex **只保存 key 与 revision 链表等索引结构**，真正的 value 数据持久化在 [boltdb](/docs/CS/Framework/etcd/boltdb.md) 的事务里；它不是指向磁盘 value 的指针表。
`treeIndex` 是 etcd v3 进程内的键索引，把用户 key 映射到它当前可见的 `Revision`，底层是 Google btree 库的一棵内存 B-tree。value 本身不在内存——它持久化在 [boltdb](/docs/CS/Framework/etcd/boltdb.md) 里，`treeIndex` 只负责"由 key 快速定位 revision"。这与 v2 / ZooKeeper 的全量数据驻留内存形成对比，也是 v3 能支撑更大数据集的原因。

> 版本基线：etcd 3.7.4（commit 2e8a5c99，Go 1.26）。以下片段均取自该 tag。

几个从源码核实出来的反直觉点：

- **btree 在 3.7 已泛型化**：类型是 `*btree.BTree[*keyIndex]`，比较器是一个闭包 `aki.Less(bki)`，不再是非泛型的 `btree.BTree` 加 `Item` 接口。
- **revision 类型已大写导出**：3.7 里是 `Revision{Main, Sub}`、`RevToBytes`，旧的 `revision{main, sub}` / `revToBytes` 在 3.7 主仓库已不存在（见 [boltdb](/docs/CS/Framework/etcd/boltdb.md)）。
- **`Get` 返回四元组**：`(modified, created Revision, ver int64, err error)`，历史读与删除语义都压在 `keyIndex.get` 里，`treeIndex` 自身只做索引定位。

## In-Memory B-Tree

`treeIndex` 的结构定义在 `server/storage/mvcc/index.go`。注意锁、泛型树与 logger 三个字段——`Put` 写时持写锁、`Get` 读时持读锁，树本身不是并发安全的：

```go
type treeIndex struct {
	sync.RWMutex
	tree *btree.BTree[*keyIndex]
	lg   *zap.Logger
}

func newTreeIndex(lg *zap.Logger) index {
	return &treeIndex{
		tree: btree.New(32, func(aki *keyIndex, bki *keyIndex) bool {
			return aki.Less(bki)
		}),
		lg: lg,
	}
}
```

`btree.New` 的第一个参数 32 是节点的最小度（min degree），决定每个节点的关键字范围；第二个参数是泛型比较闭包。树里存的是 `*keyIndex`，即"一个用户 key 对应一个节点"，节点内部再挂多代 revision 链。

## Put and Get

`Put` 的逻辑很薄：先造一个只含 key 的探针 `keyi`，树里没有就 `put` 出新节点并插入，有就在原节点上 `put`。真正的版本追加在 `keyIndex.put` 里完成：

```go
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

`Get` 只加读锁，然后转给 `unsafeGet`——后者用同一个探针取节点，命中则调 `keyi.get`，未命中返回 `ErrRevisionNotFound`：

```go
func (ti *treeIndex) Get(key []byte, atRev int64) (modified, created Revision, ver int64, err error) {
	ti.RLock()
	defer ti.RUnlock()
	return ti.unsafeGet(key, atRev)
}

func (ti *treeIndex) unsafeGet(key []byte, atRev int64) (modified, created Revision, ver int64, err error) {
	keyi := &keyIndex{key: key}
	if keyi = ti.keyIndex(keyi); keyi == nil {
		return Revision{}, Revision{}, 0, ErrRevisionNotFound
	}
	return keyi.get(ti.lg, atRev)
}
```

> [!NOTE]
> `Get` 的 `atRev` 是 MVCC 历史读的关键：它决定从 `keyIndex` 的哪一代、哪个版本取值。`atRev=0` 表示读最新，具体挑选逻辑在 `keyIndex.get` 里按 `generation` 的 `revs` 做二分/遍历，不在 `treeIndex` 这一层。

## Revisions and Range

范围查询的入口是 `Revisions`：精确查（`end==nil`）直接返回单个 revision；范围查走 `unsafeVisit` 按 key 升序遍历 B-tree，对每个命中的 `keyIndex` 取指定 revision：

```go
func (ti *treeIndex) Revisions(key, end []byte, atRev int64, limit int, withTotalCount bool) (revs []Revision, totalCount int) {
	ti.RLock()
	defer ti.RUnlock()

	if end == nil {
		rev, _, _, err := ti.unsafeGet(key, atRev)
		if err != nil {
			return nil, 0
		}
		return []Revision{rev}, 1
	}
	ti.unsafeVisit(key, end, func(ki *keyIndex) bool {
		reachedLimit := limit > 0 && len(revs) >= limit
		if reachedLimit && !withTotalCount {
			return false
		}
		if rev, _, _, err := ki.get(ti.lg, atRev); err == nil {
			if !reachedLimit {
				revs = append(revs, rev)
			}
			totalCount++
		}
		return true
	})
	return revs, totalCount
}
```

`limit` 与 `withTotalCount` 是 3.7 的签名——即使达到 limit，`withTotalCount=true` 仍会继续数完总数，这正是 `Range` 请求既要分页又要返回 `count` 的实现方式。

## keyIndex and Generations

树里的每个节点是 `keyIndex`：一个 key、最后修改的 `modified`、以及若干代 `generations`。删除会在当前代末尾追加 tombstone 版本并新建空代，所以"删除后重新 put 同名 key"会进入新的一代，`version` 从 1 重新计数：

```go
type keyIndex struct {
	key         []byte
	modified    Revision // the main rev of the last modification
	generations []generation
}

// generation contains multiple revisions of a key.
type generation struct {
	ver     int64
	created Revision // when the generation is created (put in first revision).
	revs    []Revision
}
```

`Compact` 不直接删节点，而是算出"每个 key 在压缩点需要保留哪些 revision"的 keep 集合返回给调用方，由 [compact](/docs/CS/Framework/etcd/compact.md) 去 bbolt 里删除对应条目——内存索引与磁盘数据严格分工：

```go
func (ti *treeIndex) Compact(rev int64) map[Revision]struct{} {
	// ... 省略：遍历所有 keyIndex，调用 ki.compact 收集 keep 集合
	available := make(map[Revision]struct{})
	// ... 完全压缩掉的 key 从树中删除
	return available
}
```

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
- **写路径**：API 层 → [MVCC](/docs/CS/Framework/etcd/MVCC.md) 分配 revision → `treeIndex.Put` 更新 key→revision → boltdb 写值 → [raft](/docs/CS/Framework/etcd/raft.md) 复制日志。内存索引与 bbolt 写入在 `storeTxnWrite.put` 同一函数内完成，保证一致。
- **读路径**：`Revisions` 从内存拿到候选 revision 列表，再逐个到 bbolt 点查 value；历史读通过 `atRev` 定位到旧版本。
- **watch**：以 revision 为游标，配合 MVCC 能精确推送"某 key 自某 revision 之后的变更"。
- **重启重建**：`treeIndex` 不持久化；进程重启后由 bbolt 里的 key bucket 回放重建（见 [cluster](/docs/CS/Framework/etcd/cluster.md) 的磁盘布局）。

## Links

- [boltdb](/docs/CS/Framework/etcd/boltdb.md)
- [MVCC](/docs/CS/Framework/etcd/MVCC.md)
- [compact](/docs/CS/Framework/etcd/compact.md)
- [raft](/docs/CS/Framework/etcd/raft.md)
- [cluster](/docs/CS/Framework/etcd/cluster.md)

## References

1. [etcd v3.7.4 源码（server/storage/mvcc/index.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/storage/mvcc/index.go)
2. [etcd v3.7.4 源码（server/storage/mvcc/key_index.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/storage/mvcc/key_index.go)
3. [google/btree — 泛型 B-tree for Go](https://github.com/google/btree)
