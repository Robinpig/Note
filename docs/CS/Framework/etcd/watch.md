# Watch: Event Streaming

## Introduction

etcd 的 Watch 是「gRPC 双向流 + MVCC 状态机」的组合：client 在一个 stream 上创建任意多个 watcher，`serverWatchStream` 用 `recvLoop` 收 create / cancel 控制消息、用 `sendLoop` 推事件；真正的事件匹配与可靠性由 `watchableStore` 负责，它把 watcher 分成 synced / unsynced / victims 三类分别处理。状态机如何产生事件见 [MVCC](/docs/CS/Framework/etcd/MVCC.md)，revision 被压缩后的处置见 [troubleshooting](/docs/CS/Framework/etcd/troubleshooting.md)。

> 版本基线：etcd 3.7.4（commit 2e8a5c99，Go 1.26）。以下片段均取自该 tag。

四个从源码核验出来的反直觉点：

- **接收事件的 channel 缓冲默认是 128，不是旧资料里的 1024**：`chanBufLen = 128`，且它是变量不是常量（便于测试调整）。buffer 满了**不丢事件**，而是把 watcher 移进 `victims` 异步重试。
- **`watcher` 结构体定义在 `watchable_store.go` 而不是 `watcher.go`**：它多了独立的 `startRev` 字段，事件类型也换成了 `[]*mvccpb.Event` 与 `mvccpb.Event_PUT` / `mvccpb.Event_DELETE` 枚举。
- **synced / unsynced 的判定不是「有没有指定版本号」**：源码条件是 `startRev > currentRev || startRev == 0` 进 synced，其余进 unsynced。
- **事件批次限制的是「不同 revision 数」不是事件条数**：`eventBatch.add` 用 `watchBatchMaxRevs = 1000` 计数，超出后记下 `moreRev` 留给下一批，而不是截断事件列表。

## From v2 Polling to v3 Streaming

v2 用 HTTP/1.x 长轮询，每个 watcher 一条 TCP 连接，历史事件放在容量 1000 的环形窗口里——3.7.4 仍保留这段实现：

```go
type EventHistory struct {
	Queue      eventQueue
	StartIndex uint64
	LastIndex  uint64
	rwl        sync.RWMutex
}
```

v3 把事件历史搬进 bbolt（由 MVCC 的 revision 增量承载），并把连接模型换成 HTTP/2 gRPC 双向流：一个 TCP 连接可承载多个 gRPC Stream，一个 Stream 可承载多个 watcher。`serverWatchStream` 同时持有 gRPC stream 与一个 `mvcc.WatchStream`：

```go
type serverWatchStream struct {
	lg *zap.Logger

	clusterID int64
	memberID  int64

	maxRequestBytes uint

	sg        apply.RaftStatusGetter
	watchable mvcc.WatchableKV
	ag        AuthGetter

	gRPCStream  pb.Watch_WatchServer
	watchStream mvcc.WatchStream
	ctrlStream  chan *pb.WatchResponse

	// mu protects progress, prevKV, fragment
	mu sync.RWMutex
	// tracks the watchID that stream might need to send progress to
	progress map[mvcc.WatchID]bool
	// record watch IDs that need return previous key-value pair
	prevKV map[mvcc.WatchID]bool
	// records fragmented watch IDs
	fragment map[mvcc.WatchID]bool

	// closec indicates the stream is closed.
	closec chan struct{}

	// wg waits for the send loop to complete
	wg sync.WaitGroup
}
```

`Watch` 里起两个 goroutine：`sendLoop` 推事件与 created / canceled 控制消息，`recvLoop` 解析 create / cancel / progress 请求；控制消息走独立的 `ctrlStream`（容量 16），避免被事件流阻塞。

## WatchableStore: Two Groups and Victims

`watchableStore` 嵌在 `store` 之上，核心状态是两组 watcher 加一组 victim 批次：

```go
type watchableStore struct {
	*store

	// mu protects watcher groups and batches. It should never be locked
	// before locking store.mu to avoid deadlock.
	mu sync.RWMutex

	// victims are watcher batches that were blocked on the watch channel
	victims []watcherBatch
	victimc chan struct{}

	// contains all unsynced watchers that needs to sync with events that have happened
	unsynced watcherGroup

	// contains all synced watchers that are in sync with the progress of the store.
	// The key of the map is the key that the watcher watches on.
	synced watcherGroup

	stopc chan struct{}
	wg    sync.WaitGroup
}
```

启动时会挂两个常驻循环，分别负责历史事件与慢 watcher：

```go
func New(lg *zap.Logger, b backend.Backend, le lease.Lessor, cfg StoreConfig) WatchableKV {
	s := newWatchableStore(lg, b, le, cfg)
	s.wg.Add(2)
	go s.syncWatchersLoop()
	go s.syncVictimsLoop()
	return s
}
```

> [!WARNING]
> 事件 channel 容量是 `chanBufLen = 128`（`// non-const so modifiable by tests`），不是一些文章里的 1024。`watcher.send` 用 `select { case w.ch <- wr: return true; default: return false }` 做非阻塞投递，返回 false 就转 victim，绝不阻塞写事务。

## Synced vs Unsynced

新 watcher 的归类只看 `startRev` 与当前 revision 的关系；synced 分支还会把 `minRev` 钳到 `currentRev + 1`，表示「只关心之后的新事件」：

```go
func (s *watchableStore) watch(key, end []byte, startRev int64, id WatchID, ch chan<- WatchResponse, fcs ...FilterFunc) (*watcher, cancelFunc) {
	wa := &watcher{
		key:      key,
		end:      end,
		startRev: startRev,
		minRev:   startRev,
		id:       id,
		ch:       ch,
		fcs:      fcs,
	}

	s.mu.Lock()
	s.revMu.RLock()
	synced := startRev > s.store.currentRev || startRev == 0
	if synced {
		wa.minRev = s.store.currentRev + 1
		if startRev > wa.minRev {
			wa.minRev = startRev
		}
		s.synced.add(wa)
	} else {
		slowWatcherGauge.Inc()
		s.unsynced.add(wa)
	}
	s.revMu.RUnlock()
	s.mu.Unlock()

	watcherGauge.Inc()

	return wa, func() { s.cancelWatcher(wa) }
}
```

`WatchResponse` 是 server 内部类型（不是 protobuf 生成物），`Revision` 对正常响应等于事件里最后一条的 `ModRevision`，对 unsynced 的补发响应则大于它：

```go
type WatchResponse struct {
	// WatchID is the WatchID of the watcher this response sent to.
	WatchID WatchID

	// Events contains all the events that needs to send.
	Events []*mvccpb.Event

	// Revision is the revision of the KV when the watchResponse is created.
	// For a normal response, the revision should be the same as the last
	// modified revision inside Events. For a delayed response to a unsynced
	// watcher, the revision is greater than the last modified revision
	// inside Events.
	Revision int64

	// CompactRevision is set when the watcher is cancelled due to compaction.
	CompactRevision int64
}
```

## Notify: The Fast Path

写事务结束时把 changes 转成事件，并在 `watchableStore` 锁内同步调用 `notify`——这保证异步检查当前 revision 时变更已可见：

```go
func (tw *watchableStoreTxnWrite) End() {
	changes := tw.Changes()
	if len(changes) == 0 {
		tw.TxnWrite.End()
		return
	}

	rev := tw.Rev() + 1
	evs := make([]*mvccpb.Event, len(changes))
	for i, change := range changes {
		evs[i] = &mvccpb.Event{Kv: changes[i]}
		if change.CreateRevision == 0 {
			evs[i].Type = mvccpb.Event_DELETE
			evs[i].Kv.ModRevision = rev
		} else {
			evs[i].Type = mvccpb.Event_PUT
		}
	}

	// end write txn under watchable store lock so the updates are visible
	// when asynchronous event posting checks the current store revision
	tw.s.mu.Lock()
	tw.s.notify(rev, evs)
	tw.TxnWrite.End()
	tw.s.mu.Unlock()
}

type watchableStoreTxnWrite struct {
	TxnWrite
	s *watchableStore
}

func (s *watchableStore) Write(trace *traceutil.Trace) TxnWrite {
	return &watchableStoreTxnWrite{s.store.Write(trace), s}
}
```

`notify` 只匹配 synced 组：投递成功的 watcher 继续留在 synced，失败的打 `victim` 标记并移出；无论成功与否都把 `minRev` 更新为 `rev + 1`。

```go
func (s *watchableStore) notify(rev int64, evs []*mvccpb.Event) {
	victim := make(watcherBatch)
	for w, eb := range newWatcherBatch(&s.synced, evs) {
		if eb.revs != 1 {
			s.store.lg.Panic(
				"unexpected multiple revisions in watch notification",
				zap.Int("number-of-revisions", eb.revs),
			)
		}
		if w.send(WatchResponse{WatchID: w.id, Events: eb.evs, Revision: rev}) {
			pendingEventsGauge.Add(float64(len(eb.evs)))
		} else {
			// move slow watcher to victims
			w.victim = true
			victim[w] = eb
			s.synced.delete(w)
			slowWatcherGauge.Inc()
		}
		// always update minRev
		// in case 'send' returns true and watcher stays synced, this is needed for Restore when all watchers become unsynced
		// in case 'send' returns false, this is needed for syncWatchers
		w.minRev = rev + 1
	}
	s.addVictim(victim)
}
```

`watcher.send` 先过 filter，再做非阻塞投递；如果所有事件都被过滤掉，当作「无事可做」返回 true：

```go
func (w *watcher) send(wr WatchResponse) bool {
	progressEvent := len(wr.Events) == 0

	if len(w.fcs) != 0 {
		ne := make([]*mvccpb.Event, 0, len(wr.Events))
		for i := range wr.Events {
			filtered := false
			for _, filter := range w.fcs {
				if filter(wr.Events[i]) {
					filtered = true
					break
				}
			}
			if !filtered {
				ne = append(ne, wr.Events[i])
			}
		}
		wr.Events = ne
	}
	// ... 省略 verify.Verify 的 startRev 断言 ...

	// if all events are filtered out, we should send nothing.
	if !progressEvent && len(wr.Events) == 0 {
		return true
	}
	select {
	case w.ch <- wr:
		return true
	default:
		return false
	}
}
```

## Slow Watchers and Historical Sync

`synced` 是快路径；另外两条路径处理「跟不上」的场景：

- **`syncVictimsLoop` / `moveVictims`**：反复重投 victim 里的批次；投成功的 watcher 按 `minRev` 与 `currentRev` 的关系回到 synced 或转入 unsynced，仍失败则留在 victim 等下一轮。
- **`syncWatchersLoop` / `syncWatchers`**：每 100ms 从 unsynced 里挑一批（上限 `maxWatchersPerSync = 512`），取其中最小 revision，从 bbolt 扫描 `[minRev, currentRev)` 的事件补发，完成后把 watcher 移到 synced。

```go
// syncWatchers syncs unsynced watchers by:
//  1. choose a set of watchers from the unsynced watcher group
//  2. iterate over the set to get the minimum revision and remove compacted watchers
//  3. use minimum revision to get all key-value pairs and send those events to watchers
//  4. remove synced watchers in set from unsynced group and move to synced group
func (s *watchableStore) syncWatchers() int {
	s.mu.Lock()
	defer s.mu.Unlock()

	if s.unsynced.size() == 0 {
		return 0
	}

	s.store.revMu.RLock()
	defer s.store.revMu.RUnlock()

	// in order to find key-value pairs from unsynced watchers, we need to
	// find min revision index, and these revisions can be used to
	// query the backend store of key-value pairs
	curRev := s.store.currentRev
	compactionRev := s.store.compactMainRev

	wg, minRev := s.unsynced.choose(maxWatchersPerSync, curRev, compactionRev)
	evs := rangeEvents(s.store.lg, s.store.b, minRev, curRev+1, wg)

	victims := make(watcherBatch)
	wb := newWatcherBatch(wg, evs)
	for w := range wg.watchers {
		if w.minRev < compactionRev {
			// Skip the watcher that failed to send compacted watch response due to w.ch is full.
			// Next retry of syncWatchers would try to resend the compacted watch response to w.ch
			continue
		}
		w.minRev = max(curRev+1, w.minRev)

		eb, ok := wb[w]
		if !ok {
			// bring un-notified watcher to synced
			s.synced.add(w)
			s.unsynced.delete(w)
			continue
		}
		// ... 省略更细的 moreRev / victim 分流 ...
		s.unsynced.delete(w)
	}
	s.addVictim(victims)

	vsz := 0
	for _, v := range s.victims {
		vsz += len(v)
	}
	slowWatcherGauge.Set(float64(s.unsynced.size() + vsz))

	return s.unsynced.size()
}
```

如果 watcher 的 `minRev` 小于 `compactMainRev`，历史增量已被 compact 抹掉，server 返回 `ErrCompacted`（client 侧响应里体现为 `CompactRevision`）；client 必须重新取一次最新 revision 再建 watcher，不能带着旧 revision 无限重试。

## Event Batching and Matching

`watcherGroup` 用一张 map 管单 key watcher，用一棵区间树管范围 / 前缀 watcher；事件到达时先查 map，再查区间树：

```go
// watcherGroup is a collection of watchers organized by their ranges
type watcherGroup struct {
	// keyWatchers has the watchers that watch on a single key
	keyWatchers watcherSetByKey
	// ranges has the watchers that watch a range; it is sorted by interval
	ranges adt.IntervalTree
	// watchers is the set of all watchers
	watchers watcherSet
}
```

`eventBatch.add` 的关键在于按 revision 去重计数：同一 revision 的多个事件算一批，跨到新 revision 才 `revs++`；超过 `watchBatchMaxRevs` 后记录 `moreRev` 并停止追加，避免一批事件无限大：

```go
type eventBatch struct {
	// evs is a batch of revision-ordered events
	evs []*mvccpb.Event
	// revs is the minimum unique revisions observed for this batch
	revs int
	// moreRev is first revision with more events following this batch
	moreRev int64
}

func (eb *eventBatch) add(ev *mvccpb.Event) {
	if eb.revs > watchBatchMaxRevs {
		// maxed out batch size
		return
	}

	if len(eb.evs) == 0 {
		// base case
		eb.revs = 1
		eb.evs = append(eb.evs, ev)
		return
	}

	// revision accounting
	ebRev := eb.evs[len(eb.evs)-1].Kv.ModRevision
	evRev := ev.Kv.ModRevision
	if evRev > ebRev {
		eb.revs++
		if eb.revs > watchBatchMaxRevs {
			eb.moreRev = evRev
			return
		}
	}

	eb.evs = append(eb.evs, ev)
}
```

`newWatcherBatch` 做实际匹配：对每条事件，从 `watcherSetByKey` 找出监听该 key 的 watcher，只有 `ev.Kv.ModRevision >= w.minRev` 才加入批次，避免重复通知。

## Links

- [etcd（总览与架构）](/docs/CS/Framework/etcd/etcd.md)
- [read（与 watch 共享的 MVCC 视图）](/docs/CS/Framework/etcd/read.md)
- [compact（CompactRevision 的成因）](/docs/CS/Framework/etcd/compact.md)
- [client（断线重连与 revision 续传）](/docs/CS/Framework/etcd/client.md)

## References

1. [etcd v3.7.4 源码（server/storage/mvcc/watchable_store.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/storage/mvcc/watchable_store.go)
2. [etcd v3.7.4 源码（server/storage/mvcc/watchable_store_txn.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/storage/mvcc/watchable_store_txn.go)
3. [etcd v3.7.4 源码（server/storage/mvcc/watcher_group.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/storage/mvcc/watcher_group.go)
4. [etcd v3.7.4 源码（server/storage/mvcc/watcher.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/storage/mvcc/watcher.go)
5. [etcd v3.7.4 源码（server/etcdserver/api/v3rpc/watch.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/etcdserver/api/v3rpc/watch.go)
6. [etcd v3.7.4 源码（server/etcdserver/api/v2store/event_history.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/etcdserver/api/v2store/event_history.go)
