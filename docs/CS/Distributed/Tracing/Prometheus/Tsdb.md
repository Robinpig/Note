## Introduction

[TSDB](/docs/CS/Distributed/Tracing/Prometheus/Tsdb.md) 讲 Prometheus 自带时序数据库的实现：内存 Head、WAL、块（Block）与压缩（Compaction），以及 Remote Write 的队列分片。Prometheus 的「单机自治、不依赖分布式存储」完全建立在它之上。

> [!NOTE]
> 源码级笔记。代码事实基于 `prometheus/prometheus` **v3.16.0**（commit `e2e28adeee2c5883d000fc82aca6008cfbf7e96d`）。讲解直接贴真实源码，路径相对仓库根，不再标注行号。

## Block 模型与默认参数

数据按时间切成块（Block），每块是一个自包含目录：`chunks/`（样本段文件）、`index`（倒排索引）、`meta.json`。当前数据在内存 Head 中，超过块时长后压缩成持久块。关键默认值都写在源码常量里：

```go
// tsdb/db.go
DefaultBlockDuration = int64(2 * time.Hour / time.Millisecond)

// tsdb/chunks/chunks.go — Head 的 mmap chunk 段文件上限
DefaultChunkSegmentSize = 512 * 1024 * 1024

// tsdb/wlog/wlog.go — WAL 段文件大小
DefaultSegmentSize = 128 * 1024 * 1024 // DefaultSegmentSize is 128 MB.

// tsdb/head.go — stripeSeries 的哈希分片数
DefaultStripeSize = 1 << 14
```

`validateOpts` 里还定义了块的层级结构——块范围从 `MinBlockDuration`（2h）开始按 3 倍指数增长，共 10 层，这正是「两小时块 → 六小时块 → …… 逐级压缩」的来源：

```go
	if len(rngs) == 0 {
		// Start with smallest block duration and create exponential buckets until the exceed the
		// configured maximum block duration.
		rngs = ExponentialBlockRanges(opts.MinBlockDuration, 10, 3)
	}
```

## Open：启动与 WAL 回放

`tsdb.Open` → `open` 是完整启动流程：建目录、加 lockfile（防双开）、初始化压缩器、回放 WAL 重建 Head。注释明确写了职责：

```go
// open returns a new DB in the given directory.
// It initializes the lockfile, WAL, compactor, and Head (by replaying the WAL), and runs the database.
// It is not safe to open more than one DB in the same directory.
func open(dir string, l *slog.Logger, r prometheus.Registerer, opts *Options, rngs []int64, stats *DBStats) (_ *DB, returnedErr error) {
	if err := os.MkdirAll(dir, 0o777); err != nil {
		return nil, err
	}
	// ...
}
```

`main.go` 侧用一个 `readyStorage` 包装 TSDB：`Open` 在后台 goroutine 里跑（WAL 回放可能很慢），Web API 先返回 503 直到 `Set(db)` 就绪——这就是重启 Prometheus 后页面一直显示「Starting up / TSDB not ready」的原因。

## Head：内存中的写入面

`Head` 是所有写入的入口。核心结构（节选）：

```go
type Head struct {
	chunkRange     atomic.Int64
	numSeries      atomic.Uint64
	numStaleSeries atomic.Uint64
	// ...
	minTime, maxTime         atomic.Int64 // Current min and max of the samples included in the head.
	minValidTime             atomic.Int64 // Mint allowed to be added to the head. It shouldn't be lower than the maxt of the last persisted block.
	lastWALTruncationTime    atomic.Int64
	lastMemoryTruncationTime atomic.Int64
	lastSeriesID             atomic.Uint64
	// ...
	wal, wbl        *wlog.WL
	// ...
	// All series addressable by their ID or hash.
	series *stripeSeries

	walExpiriesMtx sync.Mutex
	walExpiries    map[chunks.HeadSeriesRef]int64 // Series no longer in the head, and what time they must be kept until.
	// ...
}
```

要点：`series` 用 stripeSeries（16384 个分片锁）按 ID 和哈希双索引；`wal` 是顺序预写日志，`wbl` 是乱序样本专用的第二本日志（Out-of-Order Buffer Log）；`minValidTime` 保证 Head 不接受比最后一个持久块更早的样本。

## 写入路径：WAL 先行

Appender 是两阶段事务。`Commit` 时**先写 WAL，再落内存**——WAL 写失败则整体 Rollback，内存不产生任何变更：

```go
func (a *headAppenderBase) Commit() (err error) {
	if a.closed {
		return ErrAppenderClosed
	}

	h := a.head
	// ...

	if err := a.log(); err != nil {
		_ = a.Rollback() // Most likely the same error will happen again.
		return fmt.Errorf("write to WAL: %w", err)
	}

	if h.writeNotified != nil {
		h.writeNotified.Notify()
	}
	// ...
}
```

`log()` 按「series 定义 → metadata → float 样本 → 直方图 → exemplar」的固定顺序编码记录并逐条写入 WAL。exemplar 放在最后有明确注释：保证远端写入方先见到样本（建序列）再见到 exemplar，否则 exemplar 会因序列缺失被拒收：

```go
// log writes all headAppender's data to the WAL.
func (a *headAppenderBase) log() error {
	if a.head.wal == nil {
		return nil
	}
	// ...
	if len(a.seriesRefs) > 0 {
		rec = enc.Series(a.seriesRefs, buf)
		buf = rec[:0]

		if err := a.head.wal.Log(rec); err != nil {
			return fmt.Errorf("log series: %w", err)
		}
	}
	for _, b := range a.batches {
		// ...
		// It's important to do (float) Samples before histogram samples
		// to end up with the correct order.
		if len(b.floats) > 0 {
			rec = enc.Samples(b.floats, buf)
			// ...
			if err := a.head.wal.Log(rec); err != nil {
				return fmt.Errorf("log samples: %w", err)
			}
		}
		// ...
		// Exemplars should be logged after samples (float/native histogram/etc),
		// otherwise it might happen that we send the exemplars in a remote write
		// batch before the samples, which in turn means the exemplar is rejected
		// for missing series, since series are created due to samples.
		if len(b.exemplars) > 0 {
			rec = enc.Exemplars(exemplarsForEncoding(b.exemplars), buf)
			// ...
			if err := a.head.wal.Log(rec); err != nil {
				return fmt.Errorf("log exemplars: %w", err)
			}
		}
	}
	return nil
}
```

WAL 记录的编码是紧凑二进制（`record.Encoder`），`wlog.WL` 把记录追加进 128MB 的段文件；每个样本在 Head 内存中只保存压缩 chunk（XOR/XOR2 编码），chunk 通过 mmap 的 chunkDiskMapper 段文件（512MB 上限）持久化——WAL 负责「崩溃后重建索引与引用」，mmap chunks 负责「chunk 数据本身不重算」。

## 压缩：Head 变块

块边界一到，`DB.CompactHead` 把 RangeHead 里的样本写成持久块，然后截断 WAL：

```go
func (db *DB) CompactHead(head *RangeHead) error {
	db.cmtx.Lock()
	defer db.cmtx.Unlock()

	if err := db.compactHead(head); err != nil {
		return fmt.Errorf("compact head: %w", err)
	}

	if err := db.head.truncateWAL(head.BlockMaxTime()); err != nil {
		return fmt.Errorf("WAL truncation: %w", err)
	}
	return nil
}
```

真正的块写出在 `LeveledCompactor.Write`（`tsdb/compact.go`）：按块范围把样本写入新的 chunks 段与 index，产出带 ULID 的块目录，随后 `reloadBlocks` 把新块挂进查询集合。已压缩的大块之间还会继续按指数层级两两合并，直到超过 `MaxBlockDuration`；合并期间查询靠 `blockQuerier` 的并集透明兼容。

乱序样本走独立路径：`OutOfOrderTimeWindow` 窗口内的晚到样本写入 `wbl` 与 mmap OOO chunks，`CompactOOOHead` 单独把它们压成块。超过窗口的样本直接拒绝（`ErrTooOldSample`）。

## 查询路径

`DB.Querier(mint, maxt)` 返回一个聚合多个 block querier 与 Head querier 的 `MergeSeriesSet` 查询器——查询方（PromQL 引擎、Federate）不需要知道数据在内存还是哪个块里。Federate 端点就是最直白的读路径示例：

```go
func (h *Handler) federation(w http.ResponseWriter, req *http.Request) {
	// ...
	q, err := h.localStorage.Querier(mint, maxt)
	if err != nil {
		federationErrors.Inc()
		if errors.Is(err, tsdb.ErrNotReady) {
			http.Error(w, err.Error(), http.StatusServiceUnavailable)
			return
		}
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	defer q.Close()

	vec := make(promql.Vector, 0, 8000)

	hints := &storage.SelectHints{Start: mint, End: maxt}

	var sets []storage.SeriesSet
	for _, mset := range matcherSets {
		s := q.Select(ctx, true, hints, mset...)
		sets = append(sets, s)
	}

	set := storage.NewMergeSeriesSet(sets, 0, storage.ChainedSeriesMerge)
	// ...
}
```

## Remote Write：队列与动态分片

Remote Write 是存储层的出口组件：`storage/remote.WriteStorage` 实现 `storage.Appender`，抓取与规则评估的样本经由它转发到远端。它内部为每条 `remote_write` 配置维护一个 `QueueManager`：样本先进 WAL 式的分片队列，shard goroutine 批量转成 `prompb.TimeSeries` 发送。

分片数不是拍脑袋定的，`calculateDesiredShards` 用 EWMA 统计进出速率与发送耗时动态重分片——积压越多、单样本耗时越长，需要的 shard 越多；落后超过 10 秒时禁止降分片（防止越缩越堵）：

```go
func (t *QueueManager) calculateDesiredShards() int {
	// ...
	// We use the number of incoming samples as a prediction of how much work we
	// will need to do next iteration.  We add to this any pending samples
	// (received - send) so we can catch up with any backlog. We use the average
	// outgoing batch latency to work out how many shards we need.
	var (
		dataInRate      = t.dataIn.rate() + t.dataInExpanded.rate()
		dataOutRate     = t.dataOut.rate()
		dataKeptRatio   = dataOutRate / (t.dataDropped.rate() + dataOutRate)
		dataOutDuration = t.dataOutDuration.rate() / float64(time.Second)
		dataPendingRate = dataInRate*dataKeptRatio - dataOutRate
		highestSent     = t.metrics.highestSentTimestamp.Get()
		highestRecv     = t.highestRecvTimestamp.Get()
		delay           = max(highestRecv-highestSent, 0) // Delay must never be negative.
		dataPending     = delay * dataInRate * dataKeptRatio
	)

	if dataOutRate <= 0 {
		return t.numShards
	}

	var (
		// When behind we will try to catch up on 5% of samples per second.
		backlogCatchup = 0.05 * dataPending
		// Calculate Time to send one sample, averaged across all sends done this tick.
		timePerSample = dataOutDuration / dataOutRate
		desiredShards = timePerSample * (dataInRate*dataKeptRatio + backlogCatchup)
	)
	// ...
	// Changes in the number of shards must be greater than shardToleranceFraction.
	var (
		lowerBound = float64(t.numShards) * (1. - shardToleranceFraction)
		upperBound = float64(t.numShards) * (1. + shardToleranceFraction)
	)
	// ...
	desiredShards = math.Ceil(desiredShards) // Round up to be on the safe side.
	if lowerBound <= desiredShards && desiredShards <= upperBound {
		return t.numShards
	}

	numShards := int(desiredShards)
	// Do not downshard if we are more than ten seconds back.
	if numShards < t.numShards && delay > 10.0 {
		t.logger.Debug("Not downsharding due to being too far behind")
		// ...
	}
	// ...
}
```

样本从 Head 到远端的完整链路：抓取/规则的 `Appender.Commit` → Head WAL watcher 读 WAL 记录 → `QueueManager.Append` 进分片队列 → shard 批量发送。这意味着 remote write 的时延下限受 WAL watcher 轮询间隔影响，且远端故障时队列会积压直到 `max_samples_per_send`/`capacity` 上限触发丢弃计数。

## Links

- [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md)
- [Scrape](/docs/CS/Distributed/Tracing/Prometheus/Scrape.md)
- [PromQL Engine](/docs/CS/Distributed/Tracing/Prometheus/Promql.md)
- [Rules](/docs/CS/Distributed/Tracing/Prometheus/Rules.md)
- [Deploy](/docs/CS/Distributed/Tracing/Prometheus/Deploy.md)

## References

1. [prometheus/prometheus v3.16.0 source](https://github.com/prometheus/prometheus/tree/v3.16.0)
2. [TSDB format documentation](https://github.com/prometheus/prometheus/blob/main/docs/storage.md)
3. [Streaming remote write server implementation](https://prometheus.io/docs/prometheus/latest/storage/#remote-storage-integrations)
