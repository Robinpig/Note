## Introduction

[Index](/docs/CS/Distributed/Tracing/Prometheus/Index.md) 讲 Prometheus TSDB 的倒排索引：index 文件的物理布局、MemPostings 内存索引、postings 交集与合并算法，以及查询从 label matcher 到 series 的完整路径。PromQL 的 label 过滤性能全压在这层。

> [!NOTE]
> 源码级笔记。代码事实基于 `prometheus/prometheus` **v3.16.0**（commit `e2e28adeee2c5883d000fc82aca6008cfbf7e96d`）。讲解直接贴真实源码，路径相对仓库根，不再标注行号。

## index 文件布局

每个持久块目录下有一个 `index` 文件，魔数与格式版本：

```go
// tsdb/index/index.go
const (
	// MagicIndex 4 bytes at the head of an index file.
	MagicIndex = 0xBAAAD700
	// HeaderLen represents number of bytes reserved of index for header.
	HeaderLen = 5

	// FormatV1 represents version 1 of index.
	FormatV1 = 1
	// FormatV2 represents version 2 of index.
	FormatV2 = 2
	// FormatV3 represents version 3 of index.
	FormatV3 = 3

	indexFilename = "index"

	seriesByteAlign = 16
)
```

Writer 按 stage 串行产出四段内容：symbols（符号表）→ series（label + chunk 引用）→ label indices + postings（倒排表）→ TOC（各段偏移目录）。stage 机的定义：

```go
// tsdb/index/index.go
type indexWriterStage uint8

const (
	idxStageNone indexWriterStage = iota
	idxStageSymbols
	idxStageSeries
	idxStageDone
)
```

文件有明确的尺寸上限，写超即报错——postings offset 表必须能装进 4 字节长度前缀：

```go
// tsdb/index/index.go
// ErrPostingsOffsetTableTooLarge is returned when the postings offset table length
// would exceed 4 bytes (table would exceed the 4GB limit).
var ErrPostingsOffsetTableTooLarge = errors.New("length size exceeds 4 bytes")

// ErrIndexExceeds64GiB is returned when the index file would exceed the 64GiB limit.
var ErrIndexExceeds64GiB = errors.New("exceeding max size of 64GiB")

// ErrSymbolTableTooLarge is returned when the symbol table size exceeds 4 bytes (4GiB limit).
var ErrSymbolTableTooLarge = fmt.Errorf("symbol table size exceeds %d bytes", uint32(math.MaxUint32))
```

校验用 CRC32 Castagnoli 多项式（TSDB 各处统一），写符号表时还会回头回填长度与哈希。

## MemPostings：内存倒排

Head 里的倒排索引是 `MemPostings`，两级 map：`m[标签名][标签值] → seriesRef 列表`。WAL 回放期间用 `NewUnorderedMemPostings` 建立无序列表，回放完 `EnsureOrder` 一次性并发排序：

```go
// tsdb/index/postings.go
type MemPostings struct {
	mtx sync.RWMutex

	// m holds the postings lists for each label-value pair, indexed first by label name, and then by label value.
	//
	// mtx must be held when interacting with m (the appropriate one for reading or writing).
	// It is safe to retain a reference to a postings list after releasing the lock.
	//
	// BUG: There's currently a data race in addFor, which might modify the tail of the postings list:
	// https://github.com/prometheus/prometheus/issues/15317
	m map[string]map[string][]storage.SeriesRef

	// lvs holds the label values for each label name.
	// lvs[name] is essentially an unsorted append-only list of all keys in m[name]
	// mtx must be held when interacting with lvs.
	// Since it's append-only, it is safe to read the label values slice after releasing the lock.
	lvs map[string][]string

	ordered bool
}
```

所有 series 的 postings 有专门的全集 key：`__name__=""`（`AllPostingsKey`），即按「标签名存在性」取全量。

## 交集与合并

查询 `foo="bar" AND baz="qux"` 就是两个 postings 列表求交集。`Intersect` 是逐个推进、落后者 Seek 追齐的算法：

```go
// tsdb/index/postings.go
func (it *intersectPostings) Next() bool {
	// Move forward the first Postings and take its value as the target to match.
	if !it.postings[0].Next() {
		return false
	}
	target := it.postings[0].At()
	allEqual := true
	for _, p := range it.postings[1:] { // Now move forward all the other ones and check if they match.
		if !p.Next() {
			return false
		}
		at := p.At()
		if at > target { // This one is past the target, so pick up a new target to Seek at the end.
			target = at
			allEqual = false
		} else if at < target { // This one needs to Seek to the target, but carry on with other postings in case they have an even higher target.
			allEqual = false
		}
	}
	if allEqual {
		it.current = target
		return true
	}
	return it.Seek(target)
}
```

`Seek` 端同样是一次多路对齐循环——只要有一个列表推出更大的值，所有列表都朝新目标推进：

```go
// tsdb/index/postings.go
func (it *intersectPostings) Seek(target storage.SeriesRef) bool {
	for {
		allEqual := true
		for _, p := range it.postings {
			if !p.Seek(target) {
				return false
			}
			if p.At() > target {
				target = p.At()
				allEqual = false
			}
		}

		// if all p.At() are all equal, we found an intersection.
		if allEqual {
			it.current = target
			return true
		}
	}
}
```

并集 `Merge[T Postings]` 是泛型多路归并。Practical 细节：`Intersect` 若传入列表里出现空 postings 直接短路返回空，避免无谓的对象分配。

## 查询路径：从 matcher 到 series

块的查询入口 `NewBlockQuerier`。读路径把 index postings、tombstones、chunk reader 串起来：

```go
// tsdb/querier.go
type blockQuerier struct {
	block BlockReader

	mint, maxt int64
	// ...
}
```

系列集合经过 tombstone 过滤（`populateWithDelGenericSeriesIterator` 处理 `populate` + `deleted` 两个集合），最终吐出 `blockSeriesSet`。若查询侧要的是原始 chunk（`/api/v1/query_exemplars` 或 `chunk` 查询），走 `NewBlockChunkQuerier` 的平行路径，避免把 chunk 展开成 sample。

## 删除与 tombstones

`MemPostings.Delete` 处理系列删除后的倒排收缩：先拿写锁，把受影响 label 的 postings 列表原地重写（repl 模式，与 checkpoint 过滤同一写法），再等读方释放锁：

```go
// tsdb/index/postings.go
func (p *MemPostings) Delete(deleted map[storage.SeriesRef]struct{}, affected map[labels.Label]struct{}) {
```

tombstones（`tsdb/tombstones` 包）以 stone 区间形式持久在每个块里，查询时 `DeletedIterator` 包装原始 iterator，命中删除区间的 sample 直接跳过——这也是「通过 API 删除不会立即移除数据，压缩时才物理生效」的实现位置。

## Links

- [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md)
- [Tsdb](/docs/CS/Distributed/Tracing/Prometheus/Tsdb.md)
- [Promql](/docs/CS/Distributed/Tracing/Prometheus/Promql.md)
- [Wal](/docs/CS/Distributed/Tracing/Prometheus/Wal.md)
- [Chunk](/docs/CS/Distributed/Tracing/Prometheus/Chunk.md)

## References

- https://github.com/prometheus/prometheus/blob/v3.16.0/tsdb/index/index.go
- https://github.com/prometheus/prometheus/blob/v3.16.0/tsdb/index/postings.go
- https://github.com/prometheus/prometheus/blob/v3.16.0/tsdb/querier.go
- https://ganeshvernekar.com/blog/prometheus-tsdb-the-head-block/
