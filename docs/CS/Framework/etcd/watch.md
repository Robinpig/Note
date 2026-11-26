# Watch: Event Streaming

## Introduction

> [!NOTE]
> 本篇以 **etcd v3.7.2** 为源码基线。`watchableStore` 的 channel 容量、批量同步和 victim 重试常量均以该版本为准；跨层的事件发布边界见 [MVCC](/docs/CS/Framework/etcd/MVCC.md)。

在etcd v2 Watch机制实现中，使用的是HTTP/1.x协议，实现简单、兼容性好，每个watcher对应一个TCP连接。client通过HTTP/1.1协议长连接定时轮询server，获取最新的数据变化事件。
然而当你的watcher成千上万的时，即使集群空负载，大量轮询也会产生一定的QPS，server端会消耗大量的socket、内存等资源，导致etcd的扩展性、稳定性无法满足Kubernetes等业务场景诉求
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
// server/storage/mvcc/watchable_store.go:542-572（节选）
type watcher struct {
    key []byte
    end []byte
type serverWatchStream struct {
	lg *zap.Logger

	clusterID int64
	memberID  int64

    // compacted is set when the watcher is removed because of compaction
    compacted bool
    // restore is true when a synced watcher is moved to unsynced after restore.
    restore bool

    startRev int64
    // minRev is the minimum revision update the watcher will accept
    minRev int64
    id     WatchID

    fcs []FilterFunc
    // The channel might be shared with other watchers in the same stream.
    ch chan<- WatchResponse
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

eventBatch.add添加Event实例
```go
func (eb *eventBatch) add(ev mvccpb.Event) {
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

WatchResponse表示一次响应


```go
type WatchResponse struct {
    Header *ResponseHeader `protobuf:"bytes,1,opt,name=header,proto3" json:"header,omitempty"`
    // watch_id is the ID of the watcher that corresponds to the response.
    WatchId int64 `protobuf:"varint,2,opt,name=watch_id,json=watchId,proto3" json:"watch_id,omitempty"`
    // created is set to true if the response is for a create watch request.
    // The client should record the watch_id and expect to receive events for
    // the created watcher from the same stream.
    // All events sent to the created watcher will attach with the same watch_id.
    Created bool `protobuf:"varint,3,opt,name=created,proto3" json:"created,omitempty"`
    // canceled is set to true if the response is for a cancel watch request.
    // No further events will be sent to the canceled watcher.
    Canceled bool `protobuf:"varint,4,opt,name=canceled,proto3" json:"canceled,omitempty"`
    // compact_revision is set to the minimum index if a watcher tries to watch
    // at a compacted index.
    //
    // This happens when creating a watcher at a compacted revision or the watcher cannot
    // catch up with the progress of the key-value store.
    //
    // The client should treat the watcher as canceled and should not try to create any
    // watcher with the same start_revision again.
    CompactRevision int64 `protobuf:"varint,5,opt,name=compact_revision,json=compactRevision,proto3" json:"compact_revision,omitempty"`
    // cancel_reason indicates the reason for canceling the watcher.
    CancelReason string `protobuf:"bytes,6,opt,name=cancel_reason,json=cancelReason,proto3" json:"cancel_reason,omitempty"`
    // framgment is true if large watch response was split over multiple responses.
    Fragment             bool            `protobuf:"varint,7,opt,name=fragment,proto3" json:"fragment,omitempty"`
    Events               []*mvccpb.Event `protobuf:"bytes,11,rep,name=events,proto3" json:"events,omitempty"`
    XXX_NoUnkeyedLiteral struct{}        `json:"-"`
    XXX_unrecognized     []byte          `json:"-"`
    XXX_sizecache        int32           `json:"-"`
}
```


## Watch Request Flow

当你通过etcdctl或API发起一个watch key请求的时候，etcd的gRPCWatchServer收到watch请求后，会创建一个serverWatchStream, 它负责接收client的gRPC Stream的create/cancel watcher请求(recvLoop goroutine)，并将从MVCC模块接收的Watch事件转发给client(sendLoop goroutine)。
当serverWatchStream收到create watcher请求后，serverWatchStream会调用MVCC模块的WatchStream子模块分配一个watcher id，并将watcher注册到MVCC的WatchableKV模块。
在etcd启动的时候，WatchableKV模块会运行syncWatchersLoop和syncVictimsLoop goroutine，分别负责不同场景下的事件推送，它们也是Watch特性可靠性的核心之一。
从架构图中你可以看到Watch特性的核心实现是WatchableKV模块


```go
type WatchableKV interface {
    KV
    Watchable
}
```

```shell
etcdctl watch hello -w=json –rev=1
```

Watch特性的核心实现模块是watchableStore watchableStore结构体完成了注册watcher实例、管理watcher实例，以及发送触发watcher之后的响应等核心功能
etcd根据不同场景将watcher分类，实现了轻重分离、低耦合。我首先给你介绍下synced watcher、unsynced watcher它们各自的含义。
synced watcher，顾名思义，表示此类watcher监听的数据都已经同步完毕，在等待新的变更。
如果你创建的watcher未指定版本号(默认0)、或指定的版本号大于etcd sever当前最新的版本号(currentRev)，那么它就会保存到synced watcherGroup中。watcherGroup负责管理多个watcher，能够根据key快速找到监听该key的一个或多个watcher。
unsynced watcher，表示此类watcher监听的数据还未同步完成，落后于当前最新数据变更，正在努力追赶。
如果你创建的watcher指定版本号小于etcd server当前最新版本号，那么它就会保存到unsynced watcherGroup中。比如我们的这个案例中watch带指定版本号1监听时，版本号1和etcd server当前版本之间的数据并未同步给你，因此它就属于此类。
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

接收 Watch 事件的 channel 由 `NewWatchStream` 创建，v3.7.2 默认 buffer 容量为 **128**（`chanBufLen`），不是旧笔记中的 1024。若 channel 已满，etcd 不会丢弃待发送事件，而是把 watcher 从 synced/unsynced 分组中移出，将 watcher 与事件批次保存为 victim，交给异步机制重试。

`notify` 在修改事务结束时同步调用，必须轻量、高性能且不阻塞，否则会严重影响集群写性能。
若网络波动、CPU 高负载等异常使 watcher 进入 victim 集合，WatchableKV 启动的两个异步 goroutine 中，`syncVictimsLoop` 负责推送慢 watcher 积压的事件。
其基本工作方式是遍历 victim 中的 watcher batch，尝试再次发送已计算好的响应；仍失败就保留在 victim 中等待下一轮。`syncVictimsLoop` 在没有 victim 时等待通知，有 victim 时使用 **10ms** timer 重试。

重试成功后，如果 `minRev <= currentRev`，说明可能仍有历史事件未推送，watcher 转入 unsynced；否则说明已追上当前 revision，转回 synced。若批次还有 `moreRev`，先更新 `minRev` 再做上述判断。

## Historical Replay

WatchableKV 模块的另一个 goroutine `syncWatchersLoop` 负责 unsynced watcher 的历史事件推送。v3.7.2 的默认周期为 **100ms**，每批最多选择 **512** 个 watcher（`maxWatchersPerSync`）。

它选出这批 watcher 的最小 `minRev`，固定当前 `curRev`，然后按 backend revision key 范围 `[minRev, curRev+1)` 扫描历史记录，将命中的用户 key 转换为 Event 后发送。扫描结束后，若还有更多事件则继续留在 unsynced，否则转入 synced。用户前缀过滤发生在把 revision 记录转换为 Event 之后，不是直接按用户 key 扫描 bbolt。

如果 `minRev < compactMainRev`，历史已不可读，server 发送带 `CompactRevision` 的取消响应；client 应重新拉取最新数据，再以新的 revision 创建 watch。channel 满时不会删除 watcher，下一轮会重试发送该压缩响应。创建 watch 时若传入负的 `StartRevision`，gRPC 层直接返回 `Created + Canceled`，原因放在 `CancelReason`；正常历史追赶遇到的压缩则设置 `CompactRevision` 与 `Canceled`。

backend 恢复时，`watchableStore.Restore` 把 synced watcher 移到 unsynced 并设置 `restore` 标记，使追赶逻辑可以处理恢复前记下的未来 revision，避免误 panic。

## Fast Event Matching
etcd 使用 map 记录监听单个 key 的 watcher。Watch 也支持 key 范围与前缀，因此 etcd 还用区间树保存监听区间；区间的 value 是共享该区间的 watcher 集合。事件产生时，先查单 key map，再查与事件 key 相交的所有区间，从这些区间取出 watcher 集合。

## Links

- [etcd](/docs/CS/Framework/etcd/etcd.md)
- [Core_Mechanisms（Apply → MVCC → Watch 的发布边界）](/docs/CS/Framework/etcd/Core_Mechanisms.md)
- [compact（历史水位与 CompactRevision）](/docs/CS/Framework/etcd/compact.md)
- [troubleshooting（revision 已被压缩导致 watch 失效）](/docs/CS/Framework/etcd/troubleshooting.md)

## References

- [etcd v3.7.2 - watchable store](https://github.com/etcd-io/etcd/blob/v3.7.2/server/storage/mvcc/watchable_store.go)
- [etcd v3.7.2 - watcher group](https://github.com/etcd-io/etcd/blob/v3.7.2/server/storage/mvcc/watcher_group.go)
- [etcd v3.7.2 - watch transaction publication](https://github.com/etcd-io/etcd/blob/v3.7.2/server/storage/mvcc/watchable_store_txn.go)
- [etcd v3.7.2 - gRPC watch server](https://github.com/etcd-io/etcd/blob/v3.7.2/server/etcdserver/api/v3rpc/watch.go)
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
