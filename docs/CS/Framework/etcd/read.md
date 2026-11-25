# Linearizable Reads and ReadIndex

## Introduction

etcd 的服务端读路径，是把外置 raft 的 ReadIndex 确认接到 `Range` / 只读 `Txn` 上的胶水层：先与集群「对账」拿到一个已提交 index，再等本地状态机 apply 到该 index，最后读 MVCC 快照。Raft 侧如何消费 `Ready` 与转发 `ReadState` 见 [raft](/docs/CS/Framework/etcd/raft.md)，状态机侧的 revision 见 [MVCC](/docs/CS/Framework/etcd/MVCC.md)。

> 版本基线：etcd 3.7.4（commit 2e8a5c99，Go 1.26）。以下片段均取自该 tag。

四个先要纠正的点：

- **入口已从 `EtcdServer` 迁到独立包**：3.7.4 调的是 `s.read.LinearizableReadNotify(ctx)`，方法定义在 `server/etcdserver/read/read.go`；旧资料里的 `s.linearizableReadNotify` 与 `v3_server.go` 里的 `linearizableReadLoop` 均已不存在，且两个关键方法**导出为大写**。
- **`requestCurrentIndex` 多了一个 term 内首提交等待**：除了 8 字节 requestID 匹配与 500ms 重试，它还监听 `FirstCommitInTermNotify()`——新 leader 在本 term 首次提交 noop 之前不能回答线性读。
- **批量聚合是设计核心**：`waitC` 容量 1 且用非阻塞 `select` + `default`，唯一一个 `LinearizableReadLoop` 换掉 notifier 后一次性放行所有等待者，把「每次读走一次 Raft 心跳」的代价摊薄。
- **serializable 读不是「错误数据」**：它只保证可能落后一个 apply 延迟；只读 `Txn` 与 `Range` 共用同一套判断。

## Two Read Modes: Serializable vs Linearizable

`RangeRequest.Serializable` 直接决定走不走 ReadIndex。默认 `false`，即线性读：

```go
func (s *EtcdServer) Range(ctx context.Context, r *pb.RangeRequest) (*pb.RangeResponse, error) {
	// ... 省略 tracing 与 expensive request 告警 ...
	if !r.Serializable {
		err = s.read.LinearizableReadNotify(ctx)
		trace.Step("agreement among raft nodes before linearized reading")
		if err != nil {
			return nil, err
		}
	}
	chk := func(ai *auth.AuthInfo) error {
		return s.authStore.IsRangePermitted(ai, r.Key, r.RangeEnd)
	}

	get := func() { resp, _, err = txn.Range(ctx, s.Logger(), s.KV(), r, true) }
	if serr := s.doSerialize(ctx, chk, get); serr != nil {
		err = serr
		return nil, err
	}
	return resp, err
}
```

- **Linearizable（`Serializable=false`）**：先 `LinearizableReadNotify` 与集群对账，保证读到最新已提交数据；代价是一次 ReadIndex 往返（leader 心跳 + 等 apply）。
- **Serializable（`Serializable=true`）**：跳过对账，直接在 `doSerialize` 里读本地 MVCC 状态机，延迟低但不加重 leader 负担，代价是可能读到稍旧的数据。

只读事务走同一分支：`Txn` 先判断 `txn.IsTxnReadonly(r)`，若 `!txn.IsTxnSerializable(r)` 也调 `LinearizableReadNotify`，随后用 `txn.Txn(...)` 读快照：

```go
	if readOnly {
		if !txn.IsTxnSerializable(r) {
			err := s.read.LinearizableReadNotify(ctx)
			trace.Step("agreement among raft nodes before linearized reading")
			if err != nil {
				return nil, err
			}
		}
		var resp *pb.TxnResponse
		var err error
		chk := func(ai *auth.AuthInfo) error {
			return apply2.CheckTxnAuth(s.authStore, ai, s.lessor, r)
		}
		// ... 省略 expensive request 告警 ...
		get := func() {
			resp, _, err = txn.Txn(ctx, s.Logger(), r, s.Cfg.ServerFeatureGate.Enabled(features.TxnModeWriteWithSharedBuffer), s.KV(), s.lessor, false)
		}
		if serr := s.doSerialize(ctx, chk, get); serr != nil {
			return nil, serr
		}
		return resp, err
	}
```

> [!NOTE]
> serializable 读适合监控读取、最终一致即可的业务、或扛大量读压力的场景；要求强一致（例如读刚写下去的配置）必须用默认的 linearizable。注意 3.7.4 的实际取数入口是 `txn.Range` / `txn.Txn`，不是旧笔记里的 `applyV3Base.Range`。

## The Read Package and Its Narrow Interface

`Read` 持有 server 句柄与一个只暴露两个方法的 `raftInterface`——与算法相关的接触面被压到最小：

```go
func NewRead(server server, raft raftInterface) *Read {
	return &Read{
		server:   server,
		raft:     raft,
		waitC:    make(chan struct{}, 1),
		notifier: newNotifier(),
	}
}

type Read struct {
	server server
	raft   raftInterface
	mux    sync.RWMutex
	// read routine notifies etcd server that it waits for reading by sending an empty struct to
	// waitC
	waitC chan struct{}
	// notifier is used to notify the read routine that it can process the request
	// when there is no error
	notifier *notifier
}

type server interface {
	LeaderChanged() <-chan struct{}
	Stopping() <-chan struct{}
	Logger() *zap.Logger
	AppliedIndex() uint64
	ApplyWait(deadline uint64) <-chan struct{}
	NextRequestID() uint64
	RequestTimeout() time.Duration
	FirstCommitInTermNotify() <-chan struct{}
	Done() <-chan struct{}
}

type raftInterface interface {
	ReadState() <-chan raft.ReadState
	ReadIndex(ctx context.Context, rctx []byte) error
}
```

对应实现：`raftNode.ReadState()` 返回 `r.readStateC`，`ReadIndex` 是内嵌 `raft.Node` 的方法。notifier 用 `close(ch)` 一次性广播：

```go
type notifier struct {
	c   chan struct{}
	err error
}

func newNotifier() *notifier {
	return &notifier{
		c: make(chan struct{}),
	}
}

func (nc *notifier) notify(err error) {
	nc.err = err
	close(nc.c)
}
```

## Notify and the Single Loop

`LinearizableReadNotify` 只往 `waitC` 塞一个信号（非阻塞，满了就跳过），然后等当前 notifier：

```go
func (r *Read) LinearizableReadNotify(ctx context.Context) error {
	r.mux.RLock()
	nc := r.notifier
	r.mux.RUnlock()

	// signal linearizable loop for current notify if it hasn't been already
	select {
	case r.waitC <- struct{}{}:
	default:
	}

	// wait for read state notification
	select {
	case <-nc.c:
		return nc.err
	case <-ctx.Done():
		return ctx.Err()
	case <-r.server.Done():
		return errors.ErrStopped
	}
}
```

循环体每次先换一个新 notifier，再取 read index，等 `appliedIndex >= confirmedIndex` 后 `nr.notify(nil)` 一次性放行这一批读：

```go
func (r *Read) LinearizableReadLoop() {
	for {
		leaderChangedNotifier := r.server.LeaderChanged()
		select {
		case <-leaderChangedNotifier:
			continue
		case <-r.waitC:
		case <-r.server.Stopping():
			return
		}

		// as a single loop is can unlock multiple reads, it is not very useful
		// to propagate the trace from Txn or Range.
		_, trace := traceutil.EnsureTrace(context.Background(), r.server.Logger(), "linearizableReadLoop")

		nextnr := newNotifier()
		r.mux.Lock()
		nr := r.notifier
		r.notifier = nextnr
		r.mux.Unlock()

		confirmedIndex, err := r.requestCurrentIndex(leaderChangedNotifier)
		if isStopped(err) {
			return
		}
		if err != nil {
			nr.notify(err)
			continue
		}

		trace.Step("read index received")

		trace.AddField(traceutil.Field{Key: "readStateIndex", Value: confirmedIndex})

		appliedIndex := r.server.AppliedIndex()
		trace.AddField(traceutil.Field{Key: "appliedIndex", Value: strconv.FormatUint(appliedIndex, 10)})

		if appliedIndex < confirmedIndex {
			select {
			case <-r.server.ApplyWait(confirmedIndex):
			case <-r.server.Stopping():
				return
			}
		}
		// unblock all l-reads requested at indices before confirmedIndex
		nr.notify(nil)
		trace.Step("applied index is now lower than readState.Index")

		trace.LogAllStepsIfLong(100 * time.Millisecond)
	}
}
```

`ApplyWait` 由 apply 路径的 `applyWait.Trigger(ep.appliedi)` 唤醒，这条线把 [raft](/docs/CS/Framework/etcd/raft.md) 的 apply 循环和读路径接在一起。

## requestCurrentIndex: Matching, Retry and First Commit

`requestID` 是 8 字节大端整数，写进 `ReadState.RequestCtx` 做匹配；曾超时请求的迟到响应会被 `slowReadIndex` 计数并忽略，继续等当前请求。

```go
func (r *Read) requestCurrentIndex(leaderChangedNotifier <-chan struct{}) (uint64, error) {
	requestIDs := map[uint64]struct{}{}
	requestID := r.server.NextRequestID()
	requestIDs[requestID] = struct{}{}
	err := r.sendReadIndex(requestID)
	if err != nil {
		return 0, err
	}

	lg := r.server.Logger()
	errorTimer := time.NewTimer(r.server.RequestTimeout())
	defer errorTimer.Stop()
	retryTimer := time.NewTimer(readIndexRetryTime)
	defer retryTimer.Stop()

	firstCommitInTermNotifier := r.server.FirstCommitInTermNotify()

	for {
		select {
		case rs := <-r.raft.ReadState():
			// Check again if leader changed as when multiple channels are ready, select picks randomly.
			select {
			case <-leaderChangedNotifier:
				readIndexFailed.Inc()
				return 0, errors.ErrLeaderChanged
			default:
			}
			responseID := uint64(0)
			if len(rs.RequestCtx) == 8 {
				responseID = binary.BigEndian.Uint64(rs.RequestCtx)
			}
			if _, ok := requestIDs[responseID]; !ok {
				// a previous request might time out. now we should ignore the response of it and
				// continue waiting for the response of the current requests.
				lg.Warn(
					"ignored out-of-date read index response; local node read indexes queueing up and waiting to be in sync with leader",
					zap.Uint64("received-request-id", responseID),
				)
				slowReadIndex.Inc()
				continue
			}
			return rs.Index, nil
		case <-leaderChangedNotifier:
			readIndexFailed.Inc()
			// return a retryable error.
			return 0, errors.ErrLeaderChanged
		case <-firstCommitInTermNotifier:
			firstCommitInTermNotifier = r.server.FirstCommitInTermNotify()
			lg.Info("first commit in current term: resending ReadIndex request")
			requestID = r.server.NextRequestID()
			requestIDs[requestID] = struct{}{}
			err := r.sendReadIndex(requestID)
			if err != nil {
				return 0, err
			}
			retryTimer.Reset(readIndexRetryTime)
			continue
		case <-retryTimer.C:
			lg.Warn(
				"waiting for ReadIndex response took too long, retrying",
				zap.Uint64("sent-request-id", requestID),
				zap.Duration("retry-timeout", readIndexRetryTime),
			)
			requestID = r.server.NextRequestID()
			requestIDs[requestID] = struct{}{}
			err := r.sendReadIndex(requestID)
			if err != nil {
				return 0, err
			}
			retryTimer.Reset(readIndexRetryTime)
			continue
		case <-errorTimer.C:
			lg.Warn(
				"timed out waiting for read index response (local node might have slow network)",
				zap.Duration("timeout", r.server.RequestTimeout()),
			)
			slowReadIndex.Inc()
			return 0, errors.ErrTimeout
		case <-r.server.Stopping():
			return 0, errors.ErrStopped
		}
	}
}
```

发送侧把 requestID 编码进 `rctx` 后调外置 raft 的 `ReadIndex`，遇到 `raft.ErrStopped` 直接透传：

```go
func (r *Read) sendReadIndex(requestIndex uint64) error {
	ctxToSend := uint64ToBigEndianBytes(requestIndex)

	cctx, cancel := context.WithTimeout(context.Background(), r.server.RequestTimeout())
	err := r.raft.ReadIndex(cctx, ctxToSend)
	cancel()
	if errorspkg.Is(err, raft.ErrStopped) {
		return err
	}
	if err != nil {
		lg := r.server.Logger()
		lg.Warn("failed to get read index from Raft", zap.Error(err))
		readIndexFailed.Inc()
		return err
	}
	return nil
}

func uint64ToBigEndianBytes(number uint64) []byte {
	byteResult := make([]byte, 8)
	binary.BigEndian.PutUint64(byteResult, number)
	return byteResult
}
```

| select 分支 | 处理 |
| :--- | :--- |
| `ReadState()` 且 requestID 匹配 | 返回 `rs.Index` 作为 `confirmedIndex` |
| `ReadState()` 但 ID 不匹配 | 判为旧请求迟到响应，计数后继续等 |
| `leaderChangedNotifier` | 返回可重试的 `ErrLeaderChanged` |
| `firstCommitInTermNotifier` | 换新 requestID 重发 ReadIndex |
| `retryTimer`（500ms） | 重发，防 leader 漏回 |
| `errorTimer`（请求超时） | 返回 `ErrTimeout` |

> [!NOTE]
> `FirstCommitInTermNotify` 的语义在 `EtcdServer` 上写得很直白：新 term 的第一条 entry 提交前，leader 不能回答任何要求线性一致的读。这条通知由 apply 空 entry（noop）时触发，与 [lease](/docs/CS/Framework/etcd/lease.md) 的 `Promote` 是同一处逻辑。`ErrLeaderChanged` 是可重试错误，上层交给客户端的 immutable RPC 重试策略处理。

## Boundary with raft.md

| 层 | 讲什么 |
| :--- | :--- |
| [raft](/docs/CS/Framework/etcd/raft.md) | `Ready` 五步、`ReadStates` 只取最后一个并写入 `readStateC`、WAL 落盘 |
| 本文 | `Range` 何时触发、`LinearizableReadLoop` 如何聚合多读、`appliedIndex` 如何通过 `ApplyWait` 等待、leader 变更如何转成可重试错误 |

## Links

- [etcd（总览与架构）](/docs/CS/Framework/etcd/etcd.md)
- [request（get/put 消息处理全链路）](/docs/CS/Framework/etcd/request.md)
- [watch（与读共享的 MVCC 视图）](/docs/CS/Framework/etcd/watch.md)
- [client（读请求的重试语义）](/docs/CS/Framework/etcd/client.md)

## References

1. [etcd v3.7.4 源码（server/etcdserver/read/read.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/etcdserver/read/read.go)
2. [etcd v3.7.4 源码（server/etcdserver/read/util.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/etcdserver/read/util.go)
3. [etcd v3.7.4 源码（server/etcdserver/v3_server.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/etcdserver/v3_server.go)
4. [etcd v3.7.4 源码（server/etcdserver/server.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/etcdserver/server.go)
