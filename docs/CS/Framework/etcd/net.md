# etcd Network Layer: Raft Transport and Peer Communication

## Introduction

etcd 成员之间的 Raft 消息不走客户端端口（默认 2379），而是走 peer 端口（默认 2380）上的一套独立 HTTP 服务。这套服务的实现集中在 `server/etcdserver/api/rafthttp/`，包注释一句话说清定位：`// Package rafthttp implements HTTP transportation layer for raft pkg.`。它是 [raft](/docs/CS/Framework/etcd/raft.md) 里 `raft.Node` 与 [etcd](/docs/CS/Framework/etcd/etcd.md) 里 `EtcdServer` 之间的胶水层：上接 `Ready()` 驱动的 Raft 状态机，下接 HTTP 长连接与一次性 POST。

按旧版印象去源码里搜函数名，是读这一篇最容易踩的坑。三点先放在前面，均为 3.7.4 源码核验所得：

- **`raftpb.Message` 已全面指针化。** `Raft` 接口是 `Process(ctx context.Context, m *raftpb.Message) error`，`Transporter.Send` 是 `Send(m []*raftpb.Message)`，peer 的收发通道是 `chan *raftpb.Message`。任何还写 `raftpb.Message` 值类型的示例代码都停留在 3.4 及更早。同时 `snap.Message` 是 struct（内嵌 `*raftpb.Message`、`io.ReadCloser`、`TotalSize`），`SendSnapshot` 收 `*snap.Message`。
- **消息类型定义已外置。** `MsgApp` / `MsgHeartbeat` / `MsgVote` / `MsgSnap` / `MsgProp` 全部来自独立模块 `go.etcd.io/raft/v3/raftpb`（`go.mod` 声明 `go.etcd.io/raft/v3 v3.7.0`）。在 etcd 主仓库里找不到 `raftpb` 目录——去主仓库搜这些枚举会白跑。
- **读写驱动入口换了模型。** 3.5 之前 `rafthttp.Transport` 自己起 `readMessages` / `sendMessages` 两个后台 goroutine 主动泵消息；这两个函数在 3.7.4 已不存在（全仓库 0 命中）。消息由 `raftNode.start` 在 `case rd := <-r.Ready():` 分支里经 `r.transport.Send(r.processMessages(rd.Messages))` 被动交出。3.5 时代的 `peerHandler` 类型也已不存在，peer 侧的角色是 `Peer` 接口与 `peer` 实现，由 `startPeer` 创建。

> 版本基线：etcd 3.7.4（commit 2e8a5c99，Go 1.26）。以下片段均取自该 tag；Raft 自 3.7 起外置为独立 module `go.etcd.io/raft/v3` v3.7.0。双通道架构本身与 3.5 一脉相承，变的只是签名与入口，不是设计。

> [!NOTE]
> 本篇只讲 peer 端口（2380）上的 Raft 传输。客户端端口（2379）上的对外入口见 [gateway](/docs/CS/Framework/etcd/gateway.md)，`Ready` 的消费与线性读见 [raft](/docs/CS/Framework/etcd/raft.md)。

## Why Split Stream and Pipeline Channels

动机只有一个：**消息体积差了几个数量级，传输策略必须分开**。心跳消息（`MsgHeartbeat`）只有几十到几百字节，而快照（`MsgSnap`）小至几 KB、大至几 GB。`http.go` 的注释专门解释了为什么快照的元数据信封上限单独放宽到 64 MB，而真正的 DB 快照是流式传输的：

```go
// server/etcdserver/api/rafthttp/http.go
// snapshotLimitByte limits the size of the raft snapshot *message*
// (metadata plus the small membership blob embedded in
// raftpb.Snapshot.Data). It does NOT bound the actual database
// snapshot, which is streamed separately as the rest of the request
// body (see snapshotHandler.ServeHTTP and SaveDBFrom) and can be
// arbitrarily large.
snapshotLimitByte = 64 * 1024 * 1024
```

- **Stream 通道**：维护 HTTP 长连接，传输小而频繁的消息（`MsgApp`、`MsgHeartbeat`、`MsgVote`）。节点启动后主动向每个对端建立，连接一旦建立就长期复用。
- **Pipeline 通道**：每次发一个 HTTP POST，请求结束即关连接——`peer.go` 顶部注释明确写"连接必须被杀掉，否则会被 http 包塞回连接池"，只用来传大而低频的消息（`MsgSnap`）。

`peer.pick` 把这条规则写成了代码：快照永远走 pipeline，绝不占用 stream——因为一个 1 GB 的快照会把长连接卡住几分钟。

```go
// server/etcdserver/api/rafthttp/peer.go
func (p *peer) pick(m *raftpb.Message) (writec chan<- *raftpb.Message, picked string) {
	var ok bool
	// Considering MsgSnap may have a big size, e.g., 1G, and will block
	// stream for a long time, only use one of the N pipelines to send MsgSnap.
	if isMsgSnap(m) {
		return p.pipeline.msgc, pipelineMsg
	} else if writec, ok = p.msgAppV2Writer.writec(); ok && isMsgApp(m) {
		return writec, streamAppV2
	} else if writec, ok = p.writer.writec(); ok {
		return writec, streamMsg
	}
	return p.pipeline.msgc, pipelineMsg
}
```

优先级是：**快照 → pipeline**；**`MsgApp` → 专用优化流 `msgAppV2Writer`**；**其余 → 通用流 `writer`**；流不可用（`writec()` 返回 `working == false`）时兜底 pipeline。这也解释了 peer 结构体里为什么有**两个** `streamWriter`：普通流与 MsgApp 优化流各一个。

### Four HTTP Paths

接收侧由 `Transport.Handler()` 注册四个前缀（常量定义在 `http.go`）：

| 路径 | 常量 | Handler | 作用 |
| :--- | :--- | :--- | :--- |
| `/raft` | `RaftPrefix` | `pipelineHandler` | 收 pipeline POST 消息 |
| `/raft/stream/` | `RaftStreamPrefix+"/"` | `streamHandler` | 挂载 streamWriter 的长连接 |
| `/raft/snapshot` | `RaftSnapshotPrefix` | `snapshotHandler` | 收快照 |
| `/raft/probing` | `ProbingPrefix` | `probing.NewHandler()` | 网络延迟探测（喂 `etcd_network_peer_round_trip_time_seconds`） |

```go
// server/etcdserver/api/rafthttp/transport.go
func (t *Transport) Handler() http.Handler {
	pipelineHandler := newPipelineHandler(t, t.Raft, t.ClusterID)
	streamHandler := newStreamHandler(t, t, t.Raft, t.ID, t.ClusterID)
	snapHandler := newSnapshotHandler(t, t.Raft, t.Snapshotter, t.ClusterID)
	mux := http.NewServeMux()
	mux.Handle(RaftPrefix, pipelineHandler)
	mux.Handle(RaftStreamPrefix+"/", streamHandler)
	mux.Handle(RaftSnapshotPrefix, snapHandler)
	mux.Handle(ProbingPrefix, probing.NewHandler())
	return mux
}
```

## Transport: The Holder of the Entire Network Layer

`Transport` 是 `Transporter` 接口的唯一实现，字段按用途分四组：

```go
// server/etcdserver/api/rafthttp/transport.go
type Transport struct {
	Logger *zap.Logger

	DialTimeout time.Duration // maximum duration before timing out dial of the request
	// DialRetryFrequency defines the frequency of streamReader dial retrial attempts;
	// a distinct rate limiter is created per every peer (default value: 10 events/sec)
	DialRetryFrequency rate.Limit

	TLSInfo transport.TLSInfo // TLS information used when creating connection

	ID          types.ID   // local member ID
	URLs        types.URLs // local peer URLs
	ClusterID   types.ID   // raft cluster ID for request validation
	Raft        Raft       // raft state machine, to which the Transport forwards received messages and reports status
	Snapshotter *snap.Snapshotter
	ServerStats *stats.ServerStats // used to record general transportation statistics
	// LeaderStats records transportation statistics with followers when
	// performing as leader in raft protocol
	LeaderStats *stats.LeaderStats
	// ErrorC is used to report detected critical errors, e.g.,
	// the member has been permanently removed from the cluster
	ErrorC chan error

	streamRt   http.RoundTripper // roundTripper used by streams
	pipelineRt http.RoundTripper // roundTripper used by pipelines

	mu      sync.RWMutex         // protect the remote and peer map
	remotes map[types.ID]*remote // remotes map that helps newly joined member to catch up
	peers   map[types.ID]Peer    // peers map

	pipelineProber probing.Prober
	streamProber   probing.Prober
}
```

> [!WARNING]
> `TLSInfo` 的类型 `transport.TLSInfo` 来自 `go.etcd.io/etcd/client/pkg/v3/transport`，**不在** `server/` 下，3.7.4 顶层也没有 `pkg/transport/` 目录——旧文章写的 `pkg/transport` 是 3.3/3.4 时代的路径。同理 `stats` 指的是 `server/v3/etcdserver/api/v2stats`（peer 端口的流量统计，与 v2 数据统计同名但不同物）。

`Start()` 做三件事：建两个 `http.RoundTripper`、初始化 `remotes` / `peers` 两张表、建两个 prober。

```go
// server/etcdserver/api/rafthttp/transport.go
func (t *Transport) Start() error {
	var err error
	t.streamRt, err = newStreamRoundTripper(t.TLSInfo, t.DialTimeout)
	if err != nil {
		return err
	}
	t.pipelineRt, err = NewRoundTripper(t.TLSInfo, t.DialTimeout)
	if err != nil {
		return err
	}
	t.remotes = make(map[types.ID]*remote)
	t.peers = make(map[types.ID]Peer)
	t.pipelineProber = probing.NewProber(t.pipelineRt)
	t.streamProber = probing.NewProber(t.streamRt)

	// If client didn't provide dial retry frequency, use the default
	// (100ms backoff between attempts to create a new stream),
	// so it doesn't bring too much overhead when retry.
	if t.DialRetryFrequency == 0 {
		t.DialRetryFrequency = rate.Every(100 * time.Millisecond)
	}
	return nil
}
```

两个 RoundTripper 是**分开构造**的（`newStreamRoundTripper` 与 `NewRoundTripper` 都在 `util.go`），因为长连接需要连接池复用与不同的超时策略。`DialRetryFrequency` 落在 Transport 上，但注释说"每个 peer 一个独立限流器"——实际限流器建在 `startPeer` 里给两个 `streamReader`（各 `rate.NewLimiter(t.DialRetryFrequency, 1)`），默认值 `rate.Every(100ms)` 意味着每个 reader 每秒最多重拨 10 次。

### Send: Dispatch Downstream to Peer or Remote

`Send` 收到一批消息后逐条查表：先看 `peers`，再看 `remotes`，都没有就打 Debug 日志后丢弃。

```go
// server/etcdserver/api/rafthttp/transport.go
func (t *Transport) Send(msgs []*raftpb.Message) {
	for _, m := range msgs {
		if m.GetTo() == 0 {
			// ignore intentionally dropped message
			continue
		}
		to := types.ID(m.GetTo())

		t.mu.RLock()
		p, pok := t.peers[to]
		g, rok := t.remotes[to]
		t.mu.RUnlock()

		if pok {
			if isMsgApp(m) {
				t.ServerStats.SendAppendReq(proto.Size(m))
			}
			p.send(m)
			continue
		}

		if rok {
			g.send(m)
			continue
		}
		// ... 未知目标，打 Debug 日志后丢弃
	}
}
```

两个容易被忽略的细节：一是 `m.GetTo() == 0` 的消息被**静默丢弃**，这是 raft 库主动丢弃消息的约定，不是 bug；二是 `peer` 与 `remote` 的区别——`peer` 是正式成员，双通道齐全；`remote` 只有 pipeline（由 `startRemote` 创建，没有 streamWriter），存在的唯一目的是让新加入的成员追进度，转正后就不再用了。

> [!TIP]
> `remote.send` 的日志措辞与 `peer.send` 不同：它区分 "overloaded network"（连接仍活跃但缓冲满）与普通丢弃，因为 remote 没有 stream 通道，缓冲更容易打满。

### AddPeer: The Sole Creation Point for Peer

```go
// server/etcdserver/api/rafthttp/transport.go
func (t *Transport) AddPeer(id types.ID, us []string) {
	t.mu.Lock()
	defer t.mu.Unlock()

	if t.peers == nil {
		panic("transport stopped")
	}
	if _, ok := t.peers[id]; ok {
		return
	}
	urls, err := types.NewURLs(us)
	if err != nil {
		if t.Logger != nil {
			t.Logger.Panic("failed NewURLs", zap.Strings("urls", us), zap.Error(err))
		}
	}
	fs := t.LeaderStats.Follower(id.String())
	t.peers[id] = startPeer(t, urls, id, fs)
	addPeerToProber(t.Logger, t.pipelineProber, id.String(), us, RoundTripperNameSnapshot, rttSec)
	addPeerToProber(t.Logger, t.streamProber, id.String(), us, RoundTripperNameRaftMessage, rttSec)
	// ... 打 "added remote peer" 日志
}
```

三个要点：`t.peers == nil` 说明 `Start()` 没跑或 `Stop()` 已执行，直接 **panic**——`Start` 必须先于其他方法调用；重复 AddPeer 幂等返回；建完 peer 还要把它注册到**两个** prober 上，这样 `/raft/probing` 端点才能持续测量到该 peer 的 RTT。启动顺序由 [embed](/docs/CS/Framework/etcd/embed.md) 的生命周期保证。

## Peer and startPeer

`Peer` 接口只有 6 个方法，注意**全是小写**——它是 rafthttp 包内部的约定，不对外暴露：

```go
// server/etcdserver/api/rafthttp/peer.go
type Peer interface {
	// send sends the message to the remote peer. The function is non-blocking
	// and has no promise that the message will be received by the remote.
	// When it fails to send message out, it will report the status to underlying
	// raft.
	send(m *raftpb.Message)

	// sendSnap sends the merged snapshot message to the remote peer. Its behavior
	// is similar to send.
	sendSnap(m *snap.Message)

	// update updates the urls of remote peer.
	update(urls types.URLs)

	// attachOutgoingConn attaches the outgoing connection to the peer for
	// stream usage. After the call, the ownership of the outgoing
	// connection hands over to the peer.
	attachOutgoingConn(conn *outgoingConn)
	// activeSince returns the time that the connection with the peer becomes active.
	activeSince() time.Time
	// stop performs any necessary finalization and terminates the peer elegantly.
	stop()
}
```

接口上方的注释是理解双通道设计的最佳说明：stream 是常开的 long-polling 接收连接，**除通用流外还有一个专发 MsgApp 的优化流**（MsgApp 占全部消息的绝大部分），且**只有 leader 用它**；pipeline 是一串 HTTP 客户端，**仅在流尚未建立时使用**。

`peer` 结构体的字段几乎就是双通道架构的数据结构化表达：

```go
// server/etcdserver/api/rafthttp/peer.go
type peer struct {
	lg *zap.Logger

	localID types.ID
	// id of the remote raft peer node
	id types.ID

	r Raft

	status *peerStatus

	picker *urlPicker

	msgAppV2Writer *streamWriter
	writer         *streamWriter
	pipeline       *pipeline
	snapSender     *snapshotSender // snapshot sender to send v3 snapshot messages
	msgAppV2Reader *streamReader
	msgAppReader   *streamReader

	recvc chan *raftpb.Message
	propc chan *raftpb.Message

	mu     sync.Mutex
	paused bool

	cancel context.CancelFunc
	stopc  chan struct{}
}
```

### What goroutines startPeer Starts

`startPeer` 是初始化总入口，按顺序做四件事，每件都伴随后台 goroutine：

1. 建 `peerStatus`（RTT 与最后活跃时间）与 `urlPicker`（多 peerURL 轮换）。
2. 建并启动 `pipeline`（`pipeline.start()`，内部起 `connPerPipeline = 4` 个 `handle` goroutine）。
3. 起**两个消费 goroutine**，分别读 `recvc` 与 `propc`。
4. 建两个 `streamReader` 并 `start()`（各起一个 `run` goroutine）；两个 `streamWriter` 在结构体字面量里就已通过 `startStreamWriter` 启动（各起一个 `run` goroutine）。

拆开数，一个 peer 运行期共有这些常驻 goroutine：2 个 writer + 2 个 reader + 4 个 pipeline handler + 1 个 snapshotSender（`sendSnap` 里 `go p.snapSender.send(m)` 按需起）+ 2 个 recvc / propc 消费器。

**`recvc` 与 `propc` 必须分成两个 goroutine**，源码注释讲得很直接：

```go
// server/etcdserver/api/rafthttp/peer.go
	// r.Process might block for processing proposal when there is no leader.
	// Thus propc must be put into a separate routine with recvc to avoid blocking
	// processing other raft messages.
	go func() {
		for {
			select {
			case mm := <-p.propc:
				if err := r.Process(ctx, mm); err != nil {
					if t.Logger != nil {
						t.Logger.Warn("failed to process Raft message", zap.Error(err))
					}
				}
			case <-p.stopc:
				return
			}
		}
	}()
```

原因是 `r.Process` 处理提案时可能阻塞（无 leader 时要等），若两个 channel 共用一个 goroutine，一条卡住的提案会把心跳、投票响应的处理一起拖死。缓冲区大小也按这个前提定：`recvc` 是 `recvBufSize = 4096`，`propc` 是 `maxPendingProposals = 4096`（注释论证"一次 leader 选举最多 1 秒、并发提案者少于 4096"所以够用）。

### send: Non-Blocking Delivery, Drop When Full

```go
// server/etcdserver/api/rafthttp/peer.go
func (p *peer) send(m *raftpb.Message) {
	p.mu.Lock()
	paused := p.paused
	p.mu.Unlock()

	if paused {
		return
	}

	writec, name := p.pick(m)
	select {
	case writec <- m:
	default:
		p.r.ReportUnreachable(m.GetTo())
		if isMsgSnap(m) {
			p.r.ReportSnapshot(m.GetTo(), raft.SnapshotFailure)
		}
		if p.lg != nil {
			p.lg.Warn(
				"dropped internal Raft message since sending buffer is full",
				// ... 省略 message-type / local-member-id / remote-peer-id 等字段
			)
		}
		sentFailures.WithLabelValues(types.ID(m.GetTo()).String()).Inc()
	}
}
```

`select` 带 `default` 是**故意的**：队列满时立刻丢，绝不阻塞 Raft 主循环。丢弃会通过 `ReportUnreachable` 反馈给 raft 状态机，raft 层面再决定是否重试或推进 commit。`p.paused` 由 `Pause()` / `Resume()` 控制，用于测试时静默掐流——注意 `Pause` 也会连带 pause 两个 reader。`isMsgApp` / `isMsgSnap` 是两个只有一行的辅助函数，用 `GetType()` 而非直接取字段：

```go
// server/etcdserver/api/rafthttp/peer.go
func isMsgApp(m *raftpb.Message) bool { return m.GetType() == raftpb.MsgApp }

func isMsgSnap(m *raftpb.Message) bool { return m.GetType() == raftpb.MsgSnap }
```

## Stream Channel

核心是**两对** reader / writer，通过 HTTP 长连接对接：

- **发送侧 `streamWriter`**：本端是 HTTP **响应**的写入方。`streamHandler.ServeHTTP` 收到对端的 GET 请求后，把 `outgoingConn`（内嵌 `io.Writer` + `http.Flusher` + `io.Closer`）通过 `p.attachOutgoingConn(conn)` 交给对应 writer。
- **接收侧 `streamReader`**：本端是 HTTP **请求**的发起方，主动 GET 对端的 `/raft/stream/{type}/{localID}`，然后从响应体里循环解码。

`startStreamWriter` 只是装配并 `go w.run()`，真正的逻辑在 `run()`。它是一个四路 `select`：

| 分支 | 行为 |
| :--- | :--- |
| `heartbeatc`（`ConnReadTimeout/3` 的 ticker） | 发**链路层**心跳，保活连接 |
| `msgc` | 编码真消息；攒批（`len(msgc)==0` 或 `batched > streamBufSize/2` 时才 Flush） |
| `connc` | 对端刚挂上来的新连接：换 encoder、置 `working = true`、激活 `heartbeatc` 与 `msgc` |
| `stopc` | 关闭连接、退出 |

链路层心跳是理解 stream 的关键一环：

```go
// server/etcdserver/api/rafthttp/stream.go
// linkHeartbeatMessage is a special message used as heartbeat message in
// link layer. It never conflicts with messages from raft because raft
// doesn't send out messages without From and To fields.
var (
	linkHeartbeatMessage = raftpb.Message{Type: raftpb.MsgHeartbeat.Enum()}
	linkHeartbeatSize    = proto.Size(&linkHeartbeatMessage)
)

func isLinkHeartbeatMessage(m *raftpb.Message) bool {
	return m.GetType() == raftpb.MsgHeartbeat && m.GetFrom() == 0 && m.GetTo() == 0
}
```

它**类型是 `MsgHeartbeat`，但 `From` 和 `To` 都是 0**——正常 Raft 消息不会没有收发方，所以这种消息必然来自链路层而非 raft。`streamWriter` 定时发它（编码时 `proto.Clone(&linkHeartbeatMessage)`），`streamReader.decodeLoop` 收到就 `continue` 丢掉。这解释了为什么 peer 之间需要两套流：`linkHeartbeatMessage` 在每条流上独立保活，某条流断了不影响其他。

> [!NOTE]
> 连接是**单向使用**的：writer 侧靠对端的 GET 请求驱动，reader 侧靠自己的 GET 请求驱动。每个 peer 之间实际有 2 条本端 reader→对端 writer 的 HTTP 请求（`/raft/stream/message` 与 `/raft/stream/msgapp`），加上对端对称发来的 2 条，共 4 条长连接。stream 类型只有两种（`streamTypeMessage`、`streamTypeMsgAppV2`），端点路径由 `streamType.endpoint()` 生成：

```go
// server/etcdserver/api/rafthttp/stream.go
func (t streamType) endpoint(lg *zap.Logger) string {
	switch t {
	case streamTypeMsgAppV2:
		return path.Join(RaftStreamPrefix, "msgapp")
	case streamTypeMessage:
		return path.Join(RaftStreamPrefix, "message")
	default:
		if lg != nil {
			lg.Panic("unhandled stream type", zap.String("stream-type", t.String()))
		}
		return ""
	}
}
```

`streamReader.run` 是个 dial-解码-重试循环，退避由 `cr.rl.Wait(cr.ctx)` 控制，退出条件有三类：`io.EOF`（对端正常关闭）与 `transport.IsClosedConnError`（连接被关）都**不算故障**，只有其他错误才 `deactivate`。

`decodeLoop` 里有一处影响正确性的分派：收到 `MsgProp` 走 `propc`、其余走 `recvc`——这正是 `startPeer` 要起两个消费 goroutine 的另一半原因。两者缓冲区满时都是**丢**，日志措辞区分 "internal"（连接活跃）与"overloaded network"（连接已断）。

```go
// server/etcdserver/api/rafthttp/stream.go
		if isLinkHeartbeatMessage(m) {
			// raft is not interested in link layer heartbeat message, so we should ignore it.
			continue
		}

		recvc := cr.recvc
		if m.GetType() == raftpb.MsgProp {
			recvc = cr.propc
		}

		select {
		case recvc <- m:
		default:
			// ... 缓冲区满，按连接活跃度打不同日志，recvFailures.Inc()
		}
```

`dial` 里有一整套 HTTP 状态码到 Go 错误的映射，这是排障时对照日志的字典：

| 响应 | 含义与动作 |
| :--- | :--- |
| `200` | 成功，返回 `resp.Body` 交给 `decodeLoop` |
| `410 Gone` | 自己已被移出集群 → `reportCriticalError(errMemberRemoved, cr.errorc)` |
| `404` | 对端不认识本节点的 ID（版本不匹配或进度落后太多） |
| `412 Precondition Failed` | 读 body 文本比对：`errIncompatibleVersion` 或 `ErrClusterIDMismatch` |
| 其他 | `unhandled http status %d` |

握手头在 `dial` 里设置：`X-Server-From`、`X-Server-Version`、`X-Min-Cluster-Version`、`X-Etcd-Cluster-ID`、`X-Raft-To`。`X-Raft-To` 是防串线的关键——服务端会校验它等于自己的 ID，不匹配返回 412。

## Pipeline Channel

结构简单得多：一个 `msgc` 缓冲 + 4 个 `handle` goroutine + 每次一个 POST。

```go
// server/etcdserver/api/rafthttp/pipeline.go
const (
	connPerPipeline = 4
	// pipelineBufSize is the size of pipeline buffer, which helps hold the
	// temporary network latency.
	// The size ensures that pipeline does not drop messages when the network
	// is out of work for less than 1 second in good path.
	pipelineBufSize = 64
)

func (p *pipeline) start() {
	p.stopc = make(chan struct{})
	p.msgc = make(chan *raftpb.Message, pipelineBufSize)
	p.wg.Add(connPerPipeline)
	for i := 0; i < connPerPipeline; i++ {
		go p.handle()
	}
	// ... 打 "started HTTP pipelining with remote peer"
}
```

缓冲只有 64 是有注释解释的：`pipelineBufSize` 只需保证"网络卡顿不超过 1 秒时不丢消息"，因为 pipeline 本身是兜底路径，丢消息的代价由 raft 层重试承担。

`handle` 是发送主循环。相比 3.5 旧代码，有三处现代化差异：`pbutil.MustMarshal(&m)` 变成 `pbutil.MustMarshalMessage(m)`，`m.Size()` 变成 `proto.Size(m)`，`m.Type == raftpb.MsgApp` 变成 `isMsgApp(m)`。

```go
// server/etcdserver/api/rafthttp/pipeline.go
func (p *pipeline) handle() {
	defer p.wg.Done()

	for {
		select {
		case m := <-p.msgc:
			start := time.Now()
			err := p.post(pbutil.MustMarshalMessage(m))
			end := time.Now()

			if err != nil {
				p.status.deactivate(failureType{source: pipelineMsg, action: "write"}, err.Error())
				if isMsgApp(m) && p.followerStats != nil {
					p.followerStats.Fail()
				}
				p.raft.ReportUnreachable(m.GetTo())
				if isMsgSnap(m) {
					p.raft.ReportSnapshot(m.GetTo(), raft.SnapshotFailure)
				}
				sentFailures.WithLabelValues(types.ID(m.GetTo()).String()).Inc()
				continue
			}

			p.status.activate()
			if isMsgApp(m) && p.followerStats != nil {
				p.followerStats.Succ(end.Sub(start))
			}
			if isMsgSnap(m) {
				p.raft.ReportSnapshot(m.GetTo(), raft.SnapshotFinish)
			}
			sentBytes.WithLabelValues(types.ID(m.GetTo()).String()).Add(float64(proto.Size(m)))
		case <-p.stopc:
			return
		}
	}
}
```

`post` 是真正发 HTTP 的地方，POST 到 `RaftPrefix`（即 `/raft`），Content-Type 是 `application/protobuf`。它起了一个**看门狗 goroutine**：`done` 通道正常返回时 `cancel()`，`p.stopc` 关闭时先 `waitSchedule()`（就是 `runtime.Gosched()`）再 `cancel`——给其他 goroutine 一个被调度的机会，否则正在写的请求会泄漏。

```go
// server/etcdserver/api/rafthttp/pipeline.go
	resp, err := p.tr.pipelineRt.RoundTrip(req)
	done <- struct{}{}
	if err != nil {
		p.picker.unreachable(u)
		return err
	}
	defer resp.Body.Close()
	b, err := io.ReadAll(resp.Body)
	if err != nil {
		p.picker.unreachable(u)
		return err
	}

	err = checkPostResponse(p.tr.Logger, resp, b, req, p.peerID)
	if err != nil {
		p.picker.unreachable(u)
		// errMemberRemoved is a critical error since a removed member should
		// always be stopped. So we use reportCriticalError to report it to errorc.
		if errors.Is(err, errMemberRemoved) {
			reportCriticalError(err, p.errorc)
		}
		return err
	}
```

两处现代化改写值得点名，因为它们是"读旧代码判断新行为"最容易踩的坑：`ioutil.ReadAll` 已改为 `io.ReadAll`；`if err == errMemberRemoved` 已改为 `if errors.Is(err, errMemberRemoved)`——用 `==` 比较 error 在包装场景下会失效，新代码用 `errors.Is` 才能正确穿透。`picker.unreachable(u)` 在每条失败路径上都被调用：`urlPicker` 据此把该 endpoint 标记为不可用，后续 `pick()` 优先选其他 peerURL。多个 peerURL 的高可用部署见 [cluster](/docs/CS/Framework/etcd/cluster.md) 的成员管理一节。

### Snapshot Uses an Independent Path

快照**不走 pipeline 的 post**，而是 `snapshotSender`。`peer.sendSnap` 只是 `go p.snapSender.send(m)`，真正的发送 POST 到 `RaftSnapshotPrefix`（`/raft/snapshot`），Content-Type 是 `application/octet-stream`，body 由 `createSnapBody` 从 `snap.Message` 里流出。

> [!TIP]
> 快照为什么要单独一个 sender 而不塞进 pipeline？因为 `snap.Message` 内嵌的是 `io.ReadCloser` 而不是 `[]byte`——源码注释写明 "This avoid copying the entire snapshot into a byte array, which consumes a lot of memory"。若走 pipeline 就得先全量读进内存，一个几 GB 的快照会直接把进程打爆。流式发送是唯一可行方案。

```go
// server/etcdserver/api/snap/message.go
// Message is a struct that contains a raft Message and a ReadCloser. The type
// of raft message MUST be MsgSnap, which contains the raft meta-data and an
// additional data []byte field that contains the snapshot of the actual state
// machine.
// Message contains the ReadCloser field for handling large snapshot. This avoid
// copying the entire snapshot into a byte array, which consumes a lot of memory.
type Message struct {
	*raftpb.Message
	ReadCloser io.ReadCloser
	TotalSize  int64
	closeC     chan bool
}
```

注意 3.7 相比旧版多了 `TotalSize` 字段，`NewMessage` 里由 `int64(proto.Size(rs)) + rcSize` 算出，用于发送时的流量统计。

## Handler Implementation and Message Codec

三个 Handler 都在 `http.go`，共同的骨架是：校验 HTTP 方法 → 校验集群兼容性（`checkClusterCompatibilityFromHeader`，比对 `X-Etcd-Cluster-ID` 与 `X-Server-Version`）→ `addRemoteFromRequest`（顺手把对端登记进 remotes）→ 解码 → `Raft.Process` → 写状态码。

### pipelineHandler

限制单次读 64 KB（`connReadLimitByte`），超了会截断——因为 pipeline 传的都是小消息，64 KB 足够且能避免底层读超时。

```go
// server/etcdserver/api/rafthttp/http.go
	var m raftpb.Message
	if err := proto.Unmarshal(b, &m); err != nil {
		h.lg.Warn(
			"failed to unmarshal Raft message",
			// ... 省略 local-member-id / error 等字段
		)
		http.Error(w, "error unmarshalling raft message", http.StatusBadRequest)
		recvFailures.WithLabelValues(r.RemoteAddr).Inc()
		return
	}

	receivedBytes.WithLabelValues(types.ID(m.GetFrom()).String()).Add(float64(len(b)))

	if err := h.r.Process(context.TODO(), &m); err != nil {
		var writerErr writerToResponse
		switch {
		case errors.As(err, &writerErr):
			writerErr.WriteTo(w)
		default:
			// ... 省略日志与 Flush
			// disconnect the http stream
			panic(err)
		}
		return
	}

	// Write StatusNoContent header after the message has been processed by
	// raft, which facilitates the client to report MsgSnap status.
	w.WriteHeader(http.StatusNoContent)
```

注意 `var m raftpb.Message` 是**值**（栈上分配，反序列化填充），但 `Process` 传的是 `&m`——这正是"指针化"在过渡处的形状：值到指针的转换点就在这里。`panic(err)` 是刻意为之：注释写明 "disconnect the http stream"，用 panic 强制中断这条连接。

### streamHandler

`ServeHTTP` 只做 GET，然后按路径末段（`msgapp` 或 `message`）判定流类型，再从 `path.Base` 解析出对端 ID。它是**唯一会阻塞到连接关闭**的 Handler：末尾 `p.attachOutgoingConn(conn)` 后 `<-c.closeNotify()`，把这条 HTTP 请求"占"住当长连接用。`peerGetter` 接口（`Get(id types.ID) Peer`）由 `Transport` 自己实现，所以 handler 能通过它拿到对端 peer 并把连接挂上去。

### snapshotHandler

`ServeHTTP` 开头有一段长注释解释它的容错设计：如果发送方进程暴死而不关 TCP 连接，handler 会一直等请求体，直到 TCP keepalive 在几分钟后发现连接已断。这是可接受的，因为快照走独立 TCP 连接、其他快照仍能被收到，且这种情况极少发生。

关键点：它用 `messageDecoder.decodeLimit(snapshotLimitByte)` 解码而非 `proto.Unmarshal`，上限放宽到 64 MB——因为 raft 消息信封里嵌了快照元数据与成员信息；**真正的 DB 快照是请求体的剩余部分**，由 `h.snapshotter.SaveDBFrom(r.Body, m.Snapshot.Metadata.GetIndex())` 流式落盘。解完码还要校验 `m.GetType() != raftpb.MsgSnap` 就拒收。

### Codec

| 编解码器 | 文件 | 线格式 | 用在哪 |
| :--- | :--- | :--- | :--- |
| `messageEncoder` / `messageDecoder` | `msg_codec.go` | 8 字节大端长度前缀 + protobuf | 通用 stream（`/raft/stream/message`） |
| `msgAppV2Encoder` / `msgAppV2Decoder` | `msgappv2_codec.go` | 自定义紧凑格式 | MsgApp 优化流（`/raft/stream/msgapp`） |

通用格式就是标准"长度前缀 + protobuf"，`decode` 的默认上限是 512 MB（`readBytesLimit`），超限返回 `ErrExceedSizeLimit`。

MsgApp 优化格式才是 rafthttp 里唯一"自己造轮子"的地方，三种首字节：

| 首字节 | 常量 | 含义 | 后续内容 |
| :--- | :--- | :--- | :--- |
| `0x00` | `msgTypeLinkHeartbeat` | `linkHeartbeatMessage` | 无 |
| `0x01` | `msgTypeAppEntries` | `AppEntries` | entries 长度 + 各 entry 长度与数据 + commit index |
| `0x02` | `msgTypeApp` | `MsgApp` | 编码后消息长度 + 消息体 |

`AppEntries` 之所以能省掉 index / term，是因为它只在 Raft 的 replicate 状态发送，此时 index 与 term 完全可预测——编码器用 `enc.index == m.GetIndex() && enc.term == m.GetLogTerm() && m.GetLogTerm() == m.GetTerm()` 判定能否退化到紧凑形式。写缓冲区预分配 1 MB（`msgAppV2BufSize`）。

## Message Type Attribution

这是 3.7 之后最需要更新的一张认知表。**所有消息类型都在外部模块 `go.etcd.io/raft/v3/raftpb` 里**，etcd 主仓库没有 `raftpb` 目录。

| 类型 | 语义 | rafthttp 里的处理方式 |
| :--- | :--- | :--- |
| `MsgApp` | 日志复制 | 走 MsgApp 优化流；stream 不可用时降级 pipeline |
| `MsgHeartbeat` | 心跳 / 提交位点推进 | 走通用流；`From==To==0` 时是链路层心跳 |
| `MsgSnap` | 快照 | **强制** pipeline（pick 层）/ 独立 sender；接收在 snapshotHandler |
| `MsgProp` | 提案 | 收到后转 `propc` 通道 |
| `MsgVote` / `MsgVoteResp` | 投票 | rafthttp **不区分**，走通用流 |
| `MsgAppResp` | 复制响应 | 不区分，走通用流 |

两点值得说明：

- **`MsgProp` 在 rafthttp 生产代码里是有一处引用的**（`decodeLoop` 里选 `propc` 通道），不是"只在测试文件出现"。真正只在测试文件出现的是 `MsgVote` / `MsgVoteResp`——因为投票消息由 raft 库内部直接发出，rafthttp 层的类型判断不需要关心它。
- **`MsgSnap` 走 pipeline 这条"事实"只在 `pick` 层面成立**。真正的快照数据由 `snapshotSender` 直接 POST 到 `/raft/snapshot`，根本不经过 `pick`。`pick` 里的 `isMsgSnap` 分支处理的是那些"类型是 MsgSnap 但没有独立 sender 可用"的边缘情形（例如 leader 刚切换时的在途消息）。

> [!WARNING]
> 3.7 的 rafthttp 里还有两类消息**不属于 raft**：`linkHeartbeatMessage`（链路层保活）与 `MsgUnreachable` 类错误反馈（`r.ReportUnreachable`）。前者不被 `Process` 消费，后者根本不走上行通道。

## Pitfall List

> [!WARNING]
> 这一节的每一条都对应"按旧版印象读 3.7 源码会得出的错误结论"。

1. **`raftpb.Message` 已是指针。** `Send` 收 `[]*raftpb.Message`，`Process` 收 `*raftpb.Message`，`recvc` / `propc` 是 `chan *raftpb.Message`。仍写值类型、`chan raftpb.Message`、`m raftpb.Message` 入参的代码片段一律过时。`snap.Message` 是 struct，`SendSnapshot` 收 `*snap.Message`。
2. **`readMessages` / `sendMessages` 不存在。** 全仓库 0 命中。3.7 的消息出入口是 `raftNode.start` 的 `case rd := <-r.Ready():` 与 `r.transport.Send(r.processMessages(rd.Messages))`，过滤逻辑在 `processMessages`。
3. **`peerHandler` 不存在。** peer 侧角色是 `Peer` 接口 / `peer` 实现，创建者是 `startPeer`，由 `Transport.AddPeer` 调用。`remote` 确实存在但它只有 pipeline。
4. **`pkg/transport` 不存在。** TLS 相关类型（`transport.TLSInfo`、`transport.IsClosedConnError`）在 `client/pkg/v3/transport`。
5. **raftpb 不在主仓库。** 找不到 `raftpb/` 目录不是环境问题，是架构：类型定义在外部模块 `go.etcd.io/raft/v3/raftpb`。
6. **`AddPeer` 在 `Start()` 之前调用会 panic。** 源码显式 `panic("transport stopped")`。
7. **pipeline 的错误比较已改为 `errors.Is`。** `if err == errMemberRemoved` 是 3.5 及之前的写法；`http.go` 也用 `errors.As` 取 `writerToResponse`。
8. **`ioutil` 已清零。** `pipeline.go` 与 `http.go` 都用 `io.ReadAll`，import 块里没有 `io/ioutil`。
9. **判定消息类型的 helper 优先于裸比较。** 有 `isMsgApp`、`isMsgSnap`、`isLinkHeartbeatMessage`，且全部走 `GetType()` / `GetFrom()` 这些 protoc-gen-go v2 的指针友好 getter，不是裸字段访问。
10. **丢包的默认行为是"静默"。** `peer.send` 与 `streamReader.decodeLoop` 队列满即丢，只在日志与指标上体现。排障要看 `etcd_network_peer_sent_failures_total` 与 `peer_received_failures_total`，而不是等报错。监控指标阈值见 [monitoring](/docs/CS/Framework/etcd/monitoring.md)。
11. **`MsgSnap` 走 pipeline 这条规则有例外路径。** `pick` 里的 `isMsgSnap` 分支与实际的 `snapshotSender` 是两条不同的发送路径，别以为所有快照都经过 `/raft`。
12. **`raftReadyHandler` 不在 raft.go。** 它定义在 `server/etcdserver/server.go`，是 `EtcdServer` 侧的回调集合（`getLead` / `updateLead` / `updateLeadership` / `updateCommittedIndex`），与 rafthttp 无关。

## Links

- [request（请求处理主路径）](/docs/CS/Framework/etcd/request.md)
- [watch（MVCC watch 与事件流）](/docs/CS/Framework/etcd/watch.md)
- [tuning（网络与性能调优）](/docs/CS/Framework/etcd/tuning.md)
- [troubleshooting（网络丢包与 RTT 排障）](/docs/CS/Framework/etcd/troubleshooting.md)

## References

1. [etcd v3.7.4 源码（server/etcdserver/api/rafthttp/transport.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/etcdserver/api/rafthttp/transport.go)
2. [etcd v3.7.4 源码（server/etcdserver/api/rafthttp/peer.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/etcdserver/api/rafthttp/peer.go)
3. [etcd v3.7.4 源码（server/etcdserver/api/rafthttp/stream.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/etcdserver/api/rafthttp/stream.go)
4. [etcd v3.7.4 源码（server/etcdserver/api/rafthttp/pipeline.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/etcdserver/api/rafthttp/pipeline.go)
5. [etcd v3.7.4 源码（server/etcdserver/api/rafthttp/http.go）](https://github.com/etcd-io/etcd/blob/v3.7.4/server/etcdserver/api/rafthttp/http.go)
6. [etcd Documentation - Runtime reconfiguration](https://etcd.io/docs/v3.5/op-guide/runtime-configuration/)
