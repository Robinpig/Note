## Introduction

[Remote](/docs/CS/Distributed/Tracing/Prometheus/Remote.md) 讲 Prometheus 的数据外泄与外灌通道：Remote Write 发送端（WAL watcher → 队列分片）、Remote Write 接收端（v1/v2 协议）、Remote Read 客户端与服务端。这是 Prometheus 接入 Thanos/Mimir/VictoriaMetrics 等长期存储的统一接口。

> [!NOTE]
> 源码级笔记。代码事实基于 `prometheus/prometheus` **v3.16.0**（commit `e2e28adeee2c5883d000fc82aca6008cfbf7e96d`）。讲解直接贴真实源码，路径相对仓库根，不再标注行号。

## 组装位置

`cmd/prometheus/main.go` 里 remote storage 与本地 TSDB 被组合成 fanout（详见 [Storage](/docs/CS/Distributed/Tracing/Prometheus/Storage.md)），remote 同时承担写转发与读回填两个角色：

```go
// cmd/prometheus/main.go
	var (
		localStorage  = &readyStorage{stats: tsdb.NewDBStats()}
		scraper       = &readyScrapeManager{}
		remoteStorage = remote.NewStorage(logger.With("component", "remote"), prometheus.DefaultRegisterer, localStorage.StartTime, localStoragePath, time.Duration(cfg.RemoteFlushDeadline), scraper, cfg.scrape.EnableTypeAndUnitLabels)
		fanoutStorage = storage.NewFanout(logger, localStorage, remoteStorage)
	)
```

## 发送端：WriteStorage 与多队列

每条 `remote_write` 配置按内容哈希成一个独立队列，配置热更新时只增删有变化的队列：

```go
// storage/remote/write.go — WriteStorage.ApplyConfig
	newQueues := make(map[string]*QueueManager)
	newHashes := []string{}
	for _, rwConf := range conf.RemoteWriteConfigs {
		hash, err := toHash(rwConf)
		if err != nil {
			return err
		}

		// Don't allow duplicate remote write configs.
		if _, ok := newQueues[hash]; ok {
			return fmt.Errorf("duplicate remote write configs are not allowed, found duplicate for URL: %s", rwConf.URL)
		}

		// Set the queue name to the config hash if the user has not set
		// a name in their remote write config so we can still differentiate
		// between queues that have the same remote write endpoint.
		name := hash[:6]
		if rwConf.Name != "" {
			name = rwConf.Name
		}
```

数据来源是**对本机 WAL 的 tailing**：`wlog.Watcher` 监听 WAL 目录新写入，回放出 `record.RefSample`/`RefSeries` 等记录喂给 `QueueManager`。所以 remote write 不占用 scrape 路径，也不需要额外存储——本机写什么，队列就转发什么：

```go
// storage/remote/write.go — WriteStorage 结构
type WriteStorage struct {
	logger *slog.Logger
	reg    prometheus.Registerer
	mtx    sync.Mutex

	watcherMetrics    *wlog.WatcherMetrics
	liveReaderMetrics *wlog.LiveReaderMetrics
	externalLabels    labels.Labels
	dir               string
	queues            map[string]*QueueManager
	samplesIn         *ewmaRate
	flushDeadline     time.Duration
	interner          *pool
	scraper           ReadyScrapeManager
	quit              chan struct{}
```

## 队列分片

`QueueManager` 内部由 `shards` 结构管理 N 条队列，每条队列一个缓冲 channel + 一组 HTTP 连接：

```go
// storage/remote/queue_manager.go
type shards struct {
	mtx sync.RWMutex // With the WAL, this is never actually contended.

	qm     *QueueManager
	queues []*queue
	// So we can accurately track how many of each are lost during shard shutdowns.
	enqueuedSamples    atomic.Int64
	enqueuedExemplars  atomic.Int64
	enqueuedHistograms atomic.Int64

	// Emulate a wait group with a channel and an atomic int, as you
	// cannot select on a wait group.
	done    chan struct{}
	running atomic.Int32

	// Soft shutdown context will prevent new enqueues and deadlocks.
	softShutdown chan struct{}

	// Hard shutdown context is used to terminate outgoing HTTP connections
	// after giving them a chance to terminate.
	hardShutdown                    context.CancelFunc
	samplesDroppedOnHardShutdown    atomic.Uint32
	exemplarsDroppedOnHardShutdown  atomic.Uint32
	histogramsDroppedOnHardShutdown atomic.Uint32
	metadataDroppedOnHardShutdown   atomic.Uint32
}
```

关停分两阶段：soft shutdown 先停止入队、排干积压；超时后 hard shutdown 直接断连接、计数丢弃样本。分片数按吞吐动态伸缩（`calculateDesiredShards` 的 EWMA 算法与「落后超 10s 禁止降分片」约束见 [Tsdb](/docs/CS/Distributed/Tracing/Prometheus/Tsdb.md)）。

## 接收端：v1 与 v2

`write_handler.go` 同时接受两种协议。v1 全量写入，失败即整体 400/500，无部分写语义；v2 才引入 partial write + 响应统计头：

```go
// storage/remote/write_handler.go — writeHandler.Store
	wr := remoteapi.NewWriteResponse()
	if msgType == remoteapi.WriteV1MessageType {
		// PRW 1.0 flow has different proto message and no partial write handling.
		var req prompb.WriteRequest
		if err := proto.Unmarshal(body, &req); err != nil {
			// TODO(bwplotka): Add more context to responded error?
			h.logger.Error("Error decoding v1 remote write request", "protobuf_message", msgType, "err", err.Error())
			wr.SetStatusCode(http.StatusBadRequest)
			return wr, err
		}
		if err = h.write(r.Context(), &req); err != nil {
			switch {
			case errors.Is(err, storage.ErrOutOfOrderSample), errors.Is(err, storage.ErrOutOfBounds), errors.Is(err, storage.ErrDuplicateSampleForTimestamp), errors.Is(err, storage.ErrTooOldSample):
				// Indicated an out-of-order sample is a bad request to prevent retries.
				wr.SetStatusCode(http.StatusBadRequest)
				return wr, err
			case isHistogramValidationError(err):
				wr.SetStatusCode(http.StatusBadRequest)
				return wr, err
			default:
				wr.SetStatusCode(http.StatusInternalServerError)
				return wr, err
			}
		}
		return wr, nil
	}
```

写入路径统一走 `AppenderV2` 接口 + Commit/Rollback 事务模型（与本地 scrape 采集同一条抽象），v1 侧对非法标签的 series 是**跳过计数**而非报错：

```go
// storage/remote/write_handler.go — writeHandler.write
	appV2 := h.appendableV2.AppenderV2(ctx)
	defer func() {
		if err != nil {
			_ = appV2.Rollback()
			return
		}
		err = appV2.Commit()
		if err != nil {
			h.samplesAppendedWithoutMetadata.Add(float64(samplesAppended))
		}
	}()
```

v2 的显著差异是响应必须带 `X-Prometheus-Remote-Write-Written-*` 统计头（`respStats`），发送端借此做精准重试。

## 读端：Remote Read

读侧有两个面。客户端 `read.go` 的 querier 在 fanout 里作为 secondary，先做**本地优先裁剪**——查询区间若完全落在本地 TSDB 覆盖范围内，直接跳过远端：

```go
// storage/remote/read.go — sampleAndChunkQueryableClient.preferLocalStorage
func (c *sampleAndChunkQueryableClient) preferLocalStorage(mint, maxt int64) (cmaxt int64, noop bool, err error) {
	localStartTime, err := c.callback()
	if err != nil {
		return 0, false, err
	}
	cmaxt = maxt

	// Avoid queries whose time range is later than the first timestamp in local DB.
	if mint > localStartTime {
		return 0, true, nil
	}
	// Query only samples older than the first timestamp in local DB.
	if maxt > localStartTime {
		cmaxt = localStartTime
	}
	return cmaxt, false, nil
}
```

服务端 `read_handler.go` 支持两种响应：非流式原始 sample 与流式 XOR chunk（`Content-Type: application/x-streamed-protobuf; proto=prometheus.ChunkedReadResponse`），后者避免大区间查询在服务端物化整个 sample 数组。另外 `requiredMatchers` 机制允许读客户端声明「必须包含某 label 等值匹配」，不满足直接返回空集而不发请求——这是 Thanos/Mimir 分桶过滤的接入点。

```go
// storage/remote/read.go — querier.Select
func (q *querier) Select(ctx context.Context, sortSeries bool, hints *storage.SelectHints, matchers ...*labels.Matcher) storage.SeriesSet {
	if len(q.requiredMatchers) > 0 {
		// Copy to not modify slice configured by user.
		requiredMatchers := append([]*labels.Matcher{}, q.requiredMatchers...)
		for _, m := range matchers {
			for i, r := range requiredMatchers {
				if m.Type == labels.MatchEqual && m.Name == r.Name && m.Value == r.Value {
					// Requirement matched.
					requiredMatchers = append(requiredMatchers[:i], requiredMatchers[i+1:]...)
					break
				}
			}
			if len(requiredMatchers) == 0 {
				break
			}
		}
		if len(requiredMatchers) > 0 {
			return storage.NoopSeriesSet()
		}
	}
```

## Links

- [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md)
- [Storage](/docs/CS/Distributed/Tracing/Prometheus/Storage.md)
- [Tsdb](/docs/CS/Distributed/Tracing/Prometheus/Tsdb.md)
- [Wal](/docs/CS/Distributed/Tracing/Prometheus/Wal.md)
- [Mimir](/docs/CS/Distributed/Tracing/Mimir.md)
- [Loki](/docs/CS/Distributed/Tracing/Loki.md)

## References

- https://github.com/prometheus/prometheus/blob/v3.16.0/storage/remote/write.go
- https://github.com/prometheus/prometheus/blob/v3.16.0/storage/remote/queue_manager.go
- https://prometheus.io/docs/specs/prw/remote_write_spec/
- https://prometheus.io/docs/specs/prw/remote_write_spec_2_0/
