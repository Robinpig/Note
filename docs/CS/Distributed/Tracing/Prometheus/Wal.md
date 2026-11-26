## Introduction

[Wal](/docs/CS/Distributed/Tracing/Prometheus/Wal.md) 讲 Prometheus TSDB 的预写日志：WAL 段文件与页面帧格式、记录类型编码、Checkpoint、Head 启动回放链，以及 Agent 模式下的精简回放。TSDB 的「先写日志再进内存」全靠它兜底。

> [!NOTE]
> 源码级笔记。代码事实基于 `prometheus/prometheus` **v3.16.0**（commit `e2e28adeee2c5883d000fc82aca6008cfbf7e96d`）。讲解直接贴真实源码，路径相对仓库根，不再标注行号。注意 v3.16 里 WAL 包已从早期的 `tsdb/wal` 更名为 `tsdb/wlog`，记录编码独立在 `tsdb/record` 包，老资料里的路径已失效。

## 段文件与页面帧

WAL 落盘为一个段文件序列（`wal/000000`、`wal/000001`……），默认段大小 128MB。写入侧的核心结构是 `WL`：内部维护一个当前页 `page`（pageSize 32KB），记录先填进页、页满才刷盘，批量样本因此合并成一次顺序写：

```go
// tsdb/wlog/wlog.go
const (
	snappyMask  = 1 << 3
	zstdMask    = 1 << 4
	recTypeMask = snappyMask - 1
)

type recType uint8

const (
	recPageTerm recType = 0 // Rest of page is empty.
	recFull     recType = 1 // Full record.
	recFirst    recType = 2 // First fragment of a record.
	recMiddle   recType = 3 // Middle fragments of a record.
	recLast     recType = 4 // Final fragment of a record.
)
```

每条记录写入前先压缩（snappy/zstd 由 `--storage.tsdb.wal-compression-type` 控制），压缩后若无收益直接回退原文——小记录压缩反而变大是个常见坑，源码里显式处理了：

```go
// tsdb/wlog/wlog.go — WL.log
	// Compress the record before calculating if a new segment is needed.
	finalCompression := w.compress
	enc, err := compression.Encode(w.compress, rec, w.cEnc)
	if err != nil {
		return err
	}
	if w.compress != compression.None {
		savedBytes := len(rec) - len(enc)

		// Even if the compression was applied, skip it, if there's no benefit
		// in the WAL record size (we have a choice). For small records e.g. snappy
		// compression can yield larger records than the uncompressed.
		if savedBytes <= 0 {
			enc = rec
			finalCompression = compression.None
			savedBytes = 0
		}
		w.metrics.recordBytesSaved.WithLabelValues(w.compress).Add(float64(savedBytes))
	}
```

单条记录不允许跨段——装不下就立刻切新段，这让「读某段 = 拿到完整记录」成为可能：

```go
// tsdb/wlog/wlog.go — WL.log
	// If the record is too big to fit within the active page in the current
	// segment, terminate the active segment and advance to the next one.
	// This ensures that records do not cross segment boundaries.
	left := w.page.remaining() - recordHeaderSize                                   // Free space in the active page.
	left += (pageSize - recordHeaderSize) * (w.pagesPerSegment() - w.donePages - 1) // Free pages in the active segment.

	if len(enc) > left {
		if _, err := w.nextSegment(true); err != nil {
			return err
		}
	}
```

## 记录类型

一条 WAL 记录首字节的高位是压缩标记，低位是记录类型。`tsdb/record` 包定义了全部类型：

```go
// tsdb/record/record.go
type Type uint8

const (
	// Unknown is returned for unrecognised WAL record types.
	Unknown Type = 255
	// Series is used to match WAL records of type Series.
	Series Type = 1
	// Samples is used to match WAL records of type Samples.
	Samples Type = 2
	// Tombstones is used to match WAL records of type Tombstones.
	Tombstones Type = 3
	// Exemplars is used to match WAL records of type Exemplars.
	Exemplars Type = 4
	// MmapMarkers is used to match OOO WBL records of type MmapMarkers.
	MmapMarkers Type = 5
	// Metadata is used to match WAL records of type Metadata.
	Metadata Type = 6
	// HistogramSamples is used to match WAL records of type Histograms.
	HistogramSamples Type = 7
	// FloatHistogramSamples is used to match WAL records of type Float Histograms.
	FloatHistogramSamples Type = 8
	// CustomBucketsHistogramSamples is used to match WAL records of type Histogram with custom buckets.
	CustomBucketsHistogramSamples Type = 9
	// CustomBucketsFloatHistogramSamples is used to match WAL records of type Float Histogram with custom buckets.
	CustomBucketsFloatHistogramSamples Type = 10
	// SamplesV2 is an enhanced sample record with an encoding scheme that allows storing float samples with timestamp and an optional ST per sample.
	SamplesV2 Type = 11
	// HistogramSamplesV2 is an enhanced histogram record that supports start time per sample.
	HistogramSamplesV2 Type = 12
	// FloatHistogramSamplesV2 is an enhanced float histogram record that supports start time per sample.
	FloatHistogramSamplesV2 Type = 13
	// MinValidTime is used to match checkpoint records that carry the mint a WAL truncation
	// used. It is only ever written into checkpoints, never into a live WAL segment.
	MinValidTime Type = 14
)
```

关键设计：**Series 记录只在首次出现时写**，之后所有 Samples 记录只带一个 uint64 的 `HeadSeriesRef` 引用它。两种记录解耦，正是 WAL 高压缩率的来源：

```go
// tsdb/record/record.go
// RefSeries is the series labels with the series ID.
type RefSeries struct {
	Ref    chunks.HeadSeriesRef
	Labels labels.Labels
}

// RefSample is a timestamp/st/value struct associated with a reference to a series.
// TODO(beorn7): Perhaps make this "polymorphic", including histogram and float-histogram pointers? Then get rid of RefHistogramSample.
type RefSample struct {
	Ref   chunks.HeadSeriesRef
	ST, T int64
	V     float64
}
```

## Checkpoint

Checkpoint 把多个段折叠成一个目录 `checkpoint.NNNN`，只保留 `keep(id)` 为真的 series 及其后继记录。旧于 `mint` 的样本被丢弃，之后 `Truncate(i)` 删掉已覆盖的段文件。`writeMinValidTime` 时会把 `mint` 作为第一条记录写进 checkpoint——这样重启恢复时不依赖磁盘块的元数据：

```go
// tsdb/wlog/checkpoint.go — Checkpoint
	if writeMinValidTime {
		// Persist mint as the checkpoint's first record, so a restart can recover it without
		// depending on whether any block on disk happens to reflect it: a block produced by
		// CompactSelectedSeries or CompactStaleHead is deliberately excluded from that search,
		// and a truncation whose range had nothing left to write never produces a block at all.
		//
		// mint by itself is only guaranteed to be the highest ever used within this process:
		// the guard that makes truncateWAL's calls strictly increasing lives in memory
		// (Head.lastWALTruncationTime) and resets on every restart, so a later checkpoint
		// could otherwise persist a lower mint than an earlier one already did. Read back
		// whatever the previous checkpoint recorded and keep the higher of the two, so the
		// persisted value never regresses across restarts.
		persistedMinValidTime := mint
		previous, ok, err := ReadMinValidTime(w.Dir())
		if err != nil {
			return nil, fmt.Errorf("read previous min valid time: %w", err)
		}
		if ok && previous > persistedMinValidTime {
			persistedMinValidTime = previous
		}
		var minValidTimeEnc record.Encoder
		if err := cp.Log(minValidTimeEnc.MinValidTime(persistedMinValidTime, nil)); err != nil {
			return nil, fmt.Errorf("write min valid time record: %w", err)
		}
	}
```

主循环按记录类型解码、原地过滤不需要的 series：

```go
// tsdb/wlog/checkpoint.go — Checkpoint 主循环
	for r.Next() {
		series, samples, histogramSamples, floatHistogramSamples, tstones, exemplars, metadata = series[:0], samples[:0], histogramSamples[:0], floatHistogramSamples[:0], tstones[:0], exemplars[:0], metadata[:0]

		// We don't reset the buffer since we batch up multiple records
		// before writing them to the checkpoint.
		// Remember where the record for this iteration starts.
		start := len(buf)
		rec := r.Record()

		switch dec.Type(rec) {
		case record.Series:
			series, err = dec.Series(rec, series)
			if err != nil {
				return nil, fmt.Errorf("decode series: %w", err)
			}
			// Drop irrelevant series in place.
			repl := series[:0]
			for _, s := range series {
				if keep(s.Ref) {
					repl = append(repl, s)
				}
			}
```

## Head 启动回放链

`Head.Init` 的回放顺序是固定的四步：**chunk 快照 → mmap chunks → checkpoint → WAL 段**，每一步失败都能退回下一步（快照坏了重放 WAL，mmap 段坏了删掉重建）：

```go
// tsdb/head.go — Head.Init
func (h *Head) Init(minValidTime int64) error {
	h.minValidTime.Store(minValidTime)
	defer h.resetWLReplayResources()
	defer func() {
		h.postings.EnsureOrder(h.opts.WALReplayConcurrency)
	}()
	defer h.gc() // After loading the wal remove the obsolete data from the head.
```

开启了 `EnableMemorySnapshotOnShutdown` 时优先加载 chunk 快照，但快照有效性有一个反直觉判定——**WAL 落后于快照才信任快照，WAL 更新说明快照过期**：

```go
// tsdb/head.go — Head.Init
		loadSnapshot := true
		if h.wal != nil {
			_, endAt, err := wlog.Segments(h.wal.Dir())
			if err != nil {
				return fmt.Errorf("finding WAL segments: %w", err)
			}

			_, idx, _, err := LastChunkSnapshot(h.opts.ChunkDirRoot)
			if err != nil && !errors.Is(err, record.ErrNotFound) {
				h.logger.Error("Could not find last snapshot", "err", err)
			}

			if err == nil && endAt < idx {
				loadSnapshot = false
				h.logger.Warn("Last WAL file is behind snapshot, removing snapshots")
				if err := DeleteChunkSnapshots(h.opts.ChunkDirRoot, math.MaxInt, math.MaxInt); err != nil {
					h.logger.Error("Error while deleting snapshot directories", "err", err)
				}
			}
		}
```

随后先回填 checkpoint，再从 checkpoint 之后逐段回放：

```go
// tsdb/head.go — Head.Init
	checkpointReplayStart := time.Now()
	// Backfill the checkpoint first if it exists.
	dir, startFrom, err := wlog.LastCheckpoint(h.wal.Dir())
	if err != nil && !errors.Is(err, record.ErrNotFound) {
		return fmt.Errorf("find last checkpoint: %w", err)
	}

	// Find the last segment.
	_, endAt, e := wlog.Segments(h.wal.Dir())
	if e != nil {
		return fmt.Errorf("finding WAL segments: %w", e)
	}
```

v3.16 还加了**快速启动**：正常关机时把 `lastSeriesID` 写进 series state 文件，重启直接恢复，跳过 WAL 全量扫描；异常关机才扫描 WAL 找回最大 series ID：

```go
// tsdb/head.go — Head.Init
	if h.opts.EnableFastStartup {
		state, err := h.readSeriesStateFile()
		if err != nil && !os.IsNotExist(err) {
			h.logger.Warn("Failed to read series state file, skipping the fast startup", "err", err)
		}
		if err == nil {
			if state.CleanShutdown {
				h.lastSeriesID.Store(state.LastSeriesID)
				h.logger.Info("Fast startup: clean shutdown detected, restored last series ID", "last_series_id", state.LastSeriesID)
			} else {
				h.logger.Info("Fast startup: unclean shutdown detected, performing WAL scan", "from_segment", state.LastWALSegment, "to_segment", endAt)
				id, scanErr := h.findLastSeriesID(state, endAt)
				if scanErr != nil {
					h.logger.Error("Fast startup: WAL scan failed, skipping fast startup", "err", scanErr)
				} else {
					h.lastSeriesID.Store(id)
					h.logger.Info("Fast startup: WAL scan completed", "last_series_id", id)
				}
			}
		}
	}
```

## 并发回放

`loadWAL` 不是单线程顺序回放：解码 goroutine 逐条记录解出后按 **seriesRef 分片**发给多个 `walSubsetProcessor` worker 并行建 series、写 chunk——不同 series 互不依赖，天然可并行：

```go
// tsdb/head_wal.go — Head.loadWAL
	// Start workers that each process samples for a partition of the series ID space.
	var (
		wg             sync.WaitGroup
		concurrency    = h.opts.WALReplayConcurrency
		processors     = make([]walSubsetProcessor, concurrency)
		exemplarsInput chan record.RefExemplar

		shards          = make([][]record.RefSample, concurrency)
		histogramShards = make([][]histogramRecord, concurrency)

		decoded                      = make(chan any, 10)
		decodeErr, seriesCreationErr error
	)
```

解码侧按记录类型分发（注意 Samples 与 SamplesV2 走同一个 case）：

```go
// tsdb/head_wal.go — Head.loadWAL 解码循环
		for r.Next() {
			switch dec.Type(r.Record()) {
			case record.Series:
				series := h.wlReplaySeriesPool.Get()[:0]
				series, err = dec.Series(r.Record(), series)
				if err != nil {
					decodeErr = &wlog.CorruptionErr{
						Err:     fmt.Errorf("decode series: %w", err),
						Segment: r.Segment(),
						Offset:  r.Offset(),
					}
					return
				}
				decoded <- series
			case record.Samples, record.SamplesV2:
				samples := h.wlReplaySamplesPool.Get()[:0]
				samples, err = dec.Samples(r.Record(), samples)
```

## Agent 模式的 WAL

Agent 模式没有 Head、没有块，只有「WAL → Remote Write」一条路。`tsdb/agent` 包的 DB 极简：series 索引用 stripeSeries，ref 用原子计数器自增：

```go
// tsdb/agent/db.go — agent.Open
	// remote_write expects WAL to be stored in a "wal" subdirectory of the main storage.
	dir = filepath.Join(dir, "wal")

	w, err := wlog.NewSize(l, reg, dir, opts.WALSegmentSize, opts.WALCompression)
	if err != nil {
		return nil, fmt.Errorf("creating WAL: %w", err)
	}

	db := &DB{
		logger: l,
		opts:   opts,
		rs:     rs,

		wal:    w,
		locker: locker,

		nextRef: atomic.NewUint64(0),
		series:  newStripeSeries(opts.StripeSize),
		deleted: make(map[chunks.HeadSeriesRef]deletedRefMeta),
```

回放失败时直接走 `WL.Repair` 修段（从损坏点截断到下一条完整记录），主程序装配处的切换在 `cmd/prometheus/main.go`：agent 模式 `agent.Open` 后调用 `db.SetWriteNotified(remoteStorage)`——**每条 WAL 写入完成直接通知 remote 队列读取**，这就是 Agent 的实时转发通道。

```go
// cmd/prometheus/main.go — agent 分支
			db, err := agent.Open(
				logger,
				prometheus.DefaultRegisterer,
				remoteStorage,
				localStoragePath,
				&opts,
			)
			if err != nil {
				return fmt.Errorf("opening storage failed: %w", err)
			}
			// ...
			localStorage.Set(db, 0)
			db.SetWriteNotified(remoteStorage)
			close(dbOpen)
```

## Links

- [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md)
- [Tsdb](/docs/CS/Distributed/Tracing/Prometheus/Tsdb.md)
- [Scrape](/docs/CS/Distributed/Tracing/Prometheus/Scrape.md)
- [Chunk](/docs/CS/Distributed/Tracing/Prometheus/Chunk.md)
- [Remote](/docs/CS/Distributed/Tracing/Prometheus/Remote.md)
- [Loki](/docs/CS/Distributed/Tracing/Loki.md)

## References

- https://github.com/prometheus/prometheus/tree/v3.16.0/tsdb/wlog
- https://github.com/prometheus/prometheus/blob/v3.16.0/tsdb/record/record.go
- https://github.com/prometheus/prometheus/blob/v3.16.0/tsdb/head_wal.go
- https://prometheus.io/docs/prometheus/latest/storage/
