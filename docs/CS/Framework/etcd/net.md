## Introduction

etcd 成员之间的 Raft 消息不走客户端端口（默认 2379），而是走 peer 端口（默认 2380）上的一套独立 HTTP 服务。这套服务的完整实现只有一个包：`server/etcdserver/api/rafthttp/`，包注释一句话说清定位——`// Package rafthttp implements HTTP transportation layer for raft pkg.`（`doc.go:15`）。它是 [raft.md](/docs/CS/Framework/etcd/raft.md) 里 `raft.Node` 与 [etcd.md](/docs/CS/Framework/etcd/etcd.md) 里 `EtcdServer` 之间的胶水层：上接 `Ready()` 驱动的 Raft 状态机，下接 HTTP 长连接与一次性 POST。

这一篇最容易踩坑的地方，是**按旧版 etcd 的印象去源码里搜函数名**。3.7.2 有三处反直觉：

- **`raftpb.Message` 已全面指针化。** `Send` 的签名是 `Send(m []*raftpb.Message)`（`transport.go:58`），`Raft.Process` 是 `Process(ctx context.Context, m *raftpb.Message) error`（`transport.go:37`），peer 的收发通道是 `chan *raftpb.Message`。任何还写着 `raftpb.Message` 值类型的示例代码都停留在 3.4 及更早。同时 `snap.Message` 也从接口变成了 **struct**（`server/etcdserver/api/snap/message.go:34`，内嵌 `*raftpb.Message` 与一个 `io.ReadCloser`），所以 `SendSnapshot` 的签名是 `SendSnapshot(m *snap.Message)`（`transport.go:61`）。
- **消息类型已经外置，`rafthttp` 里找不到它们的定义。** `MsgApp` / `MsgHeartbeat` / `MsgVote` / `MsgSnap` / `MsgProp` 全部来自独立模块 `go.etcd.io/raft/v3/raftpb`（`go.mod:37` 声明 `go.etcd.io/raft/v3 v3.7.0`）。在 etcd 主仓库里 `find -type d -name raftpb` 是零命中——去主仓库找这些枚举会白跑。
- **读写入口换了驱动模型。** 3.5 之前 `rafthttp.Transport` 自己起了 `readMessages` / `sendMessages` 两个后台 goroutine 主动泵消息；3.7.2 里这两个函数**已不存在**（全仓库 0 命中），消息由 `raftNode.start` 在 `case rd := <-r.Ready():` 分支里被动交出，入口是 `r.transport.Send(r.processMessages(rd.Messages))`（`server/etcdserver/raft.go:242`）。同理，3.5 时代的 `peerHandler` 类型也已不存在，peer 侧的角色是 `Peer` 接口（`peer.go:63`）与 `peer` 实现（`peer.go:101`），由 `startPeer`（`peer.go:131`）创建。

> [!NOTE]
> **版本基线**：全文行号与签名取自 **etcd v3.7.2**（`server/etcdserver/api/rafthttp/`，16 个非测试文件）。核对方式为逐条打开源码确认，凡结论均附 `文件:行号`；未在源码中找到的符号会显式标注"查不到"，不做记忆推断。3.7.2 的双通道架构本身与 3.5 一脉相承，**变的只是签名与入口，不是设计**。

## Why Split Stream and Pipeline Channels

动机只有一个：**消息体积差了几个数量级，传输策略必须分开**。心跳消息（`MsgHeartbeat`）只有几十到几百字节，而快照（`MsgSnap`）小至几 KB、大至几 GB（`http.go:46-55` 的注释解释了为什么快照的元数据上限单独放宽到 64 MB，而真正的 DB 快照是流式传输的）。

- **Stream 通道**：维护 HTTP 长连接，传输小而频繁的消息（`MsgApp`、`MsgHeartbeat`、`MsgVote`）。它在节点启动后**主动**向集群中每个对端建立，连接一旦建立就长期复用。
- **Pipeline 通道**：每次发一个 HTTP POST，请求结束即关连接（`peer.go:38-40` 明确写"连接必须被杀掉，否则会被 http 包塞回连接池"），只用来传大而低频的消息（`MsgSnap`）。

`peer.go:92-99` 的 `pick` 把这条规则写成了代码：快照**永远**走 pipeline，绝不占用 stream——因为一个 1 GB 的快照会把长连接卡住几分钟。

```go
// server/etcdserver/api/rafthttp/peer.go:337
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

优先级是：**快照 → pipeline**；**`MsgApp` → 专用优化流 `msgAppV2Writer`**；**其余 → 通用流 `writer`**；流不可用（`writec()` 返回 `working == false`，见 `stream.go:310`）时兜底 pipeline。这也解释了 peer 结构体里为什么有**两个** `streamWriter`：普通流与 MsgApp 优化流各一个。

### Four HTTP Paths

接收侧由 `Transport.Handler()`（`transport.go:158-168`）注册四个前缀（常量在 `http.go:58-66`）：

| 路径 | 常量 | Handler | 作用 |
| :--- | :--- | :--- | :--- |
| `/raft` | `RaftPrefix` | `pipelineHandler` | 收 pipeline POST 消息 |
| `/raft/stream/` | `RaftStreamPrefix+"/"` | `streamHandler` | 挂载 streamWriter 的长连接 |
| `/raft/snapshot` | `RaftSnapshotPrefix` | `snapshotHandler` | 收快照 |
| `/raft/probing` | `ProbingPrefix` | `probing.NewHandler()` | 网络延迟探测（喂 `etcd_network_peer_round_trip_time_seconds`） |

```go
// server/etcdserver/api/rafthttp/transport.go:158
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

`Transport` 定义在 `transport.go:98-132`，是 `Transporter` 接口（`transport.go:43-90`）的唯一实现。字段按用途分四组：

```go
// server/etcdserver/api/rafthttp/transport.go:98
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
	// When an error is received from ErrorC, user should stop raft state
	// machine and thus stop the Transport.
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
> `TLSInfo` 的类型 `transport.TLSInfo` 来自 **`go.etcd.io/etcd/client/pkg/v3/transport`**（import 在 `transport.go:28`），**不在** `server/` 下，也**不在** `pkg/transport/`——3.7.2 顶层没有 `pkg/transport/` 这个目录（`ls` 报 No such file or directory）。旧文章写的 `pkg/transport` 是 3.3/3.4 时代的路径。同理 `stats` 指的是 `server/v3/etcdserver/api/v2stats`（peer 端口的流量统计，与 v2 数据统计同名但不同物）。

`Start()`（`transport.go:134-156`）做三件事：建两个 `http.RoundTripper`、初始化 `remotes`/`peers` 两张表、建两个 prober。

```go
// server/etcdserver/api/rafthttp/transport.go:134
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

两个 RoundTripper 是**分开构造**的（`newStreamRoundTripper` 在 `util.go:59`，`NewRoundTripper` 在 `util.go:47`），因为长连接需要连接池复用与不同的超时策略。`DialRetryFrequency` 落在 Transport 上，但注释说"每个 peer 一个独立限流器"——实际限流器建在 `startPeer` 里给两个 `streamReader`（`peer.go:216`、`peer.go:227`），默认值 `rate.Every(100ms)` 意味着**每个 reader 每秒最多重拨 10 次**。

### Send: Dispatch Downstream to Peer or Remote

`Send` 收到一批消息后逐条查表（`transport.go:176-210`）：先看 `peers`，再看 `remotes`，都没有就丢弃并打 Debug 日志。这里有两个容易忽略的细节：

```go
// server/etcdserver/api/rafthttp/transport.go:176
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

一是 `m.GetTo() == 0` 的消息被**静默丢弃**——这是 raft 库主动丢弃消息的约定，不是 bug。二是 `peers` 与 `remotes` 的区别：`peer` 是正式成员，双通道齐全；`remote`（`remote.go:24`，由 `Transport.AddRemote` 在 `transport.go:263` 创建）**只有 pipeline**（`startRemote` 只起了 `pipeline`，没有 streamWriter），存在的唯一目的是让新加入的成员能追进度，成员转正后就不再用了。

> [!TIP]
> `remote.send`（`remote.go:54`）的注释与 `peer.send` 不同：它区分 "overloaded network"（连接仍活跃但缓冲满）与普通丢弃两种措辞，因为 remote 没有 stream 通道，缓冲更容易打满。

### AddPeer: The Sole Creation Point for Peer

```go
// server/etcdserver/api/rafthttp/transport.go:296
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

三个要点：`t.peers == nil` 说明 `Start()` 没跑或 `Stop()` 已执行，直接 **panic**——`Start` 必须先于其他方法调用；重复 AddPeer 幂等返回；建完 peer 还要把它注册到**两个** prober 上，这样 `/raft/probing` 端点才能持续测量到该 peer 的 RTT。

## Peer and startPeer

`Peer` 接口（`peer.go:63-91`）只有 7 个方法，注意**全是小写**——它是 rafthttp 包内部的约定，不对外暴露：

```go
// server/etcdserver/api/rafthttp/peer.go:63
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
	// connection hands over to the peer. The peer will close the connection
	// when it is no longer used.
	attachOutgoingConn(conn *outgoingConn)
	// activeSince returns the time that the connection with the
	// peer becomes active.
	activeSince() time.Time
	// stop performs any necessary finalization and terminates the peer
	// elegantly.
	stop()
}
```

接口文档里 `peer.go:92-99` 那段注释是理解双通道设计的最佳说明：stream 是常开的 long-polling 接收连接，**除通用流外还有一个专发 MsgApp 的优化流**（因为 MsgApp 占全部消息的绝大部分），且**只有 leader 用它**；pipeline 是一串 HTTP 客户端，**仅在流尚未建立时使用**。

`peer` 结构体（`peer.go:101-129`）的字段几乎就是双通道架构的数据结构化表达：

```go
// server/etcdserver/api/rafthttp/peer.go:101
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

	cancel context.CancelFunc // cancel pending works in go routine created by peer.
	stopc  chan struct{}
}
```

### What goroutines startPeer Starts

`startPeer`（`peer.go:131-234`）是初始化的总入口。它按顺序做了四件事，每件都伴随后台 goroutine：

1. 建 `peerStatus`（`peer_status.go`，RTT 与最后活跃时间）与 `urlPicker`（多 peerURL 轮换）。
2. 建并启动 `pipeline`（`pipeline.start()`，内部起 `connPerPipeline = 4` 个 `handle` goroutine，`pipeline.go:37`、`:64-79`）。
3. 起**两个消费 goroutine**，分别读 `recvc` 与 `propc`。
4. 建两个 `streamReader` 并 `start()`（各起一个 `run` goroutine）；两个 `streamWriter` 在结构体字面量里就已通过 `startStreamWriter` 启动（各起一个 `run` goroutine，`stream.go:140-157`）。

拆开数，一个 peer 在运行期共有这些常驻 goroutine：2 个 writer + 2 个 reader + 4 个 pipeline handler + 1 个 snapshotSender（`peer.go:268` 的 `sendSnap` 里 `go p.snapSender.send(m)` 按需起）+ 2 个 recvc/propc 消费器。

**`recvc` 与 `propc` 必须分成两个 goroutine**，源码注释（`peer.go:181-183`）讲得很直接：

```go
// server/etcdserver/api/rafthttp/peer.go:174
	ctx, cancel := context.WithCancel(context.Background())
	p.cancel = cancel
	go func() {
		for {
			select {
			case mm := <-p.recvc:
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

	// r.Process might block for processing proposal when there is no leader.
	// Thus propc must be put into a separate routine with recvc to avoid blocking
	// processing other raft messages.
	go func() {
		for {
			select {
			case mm := <-p.propc:
				if err := r.Process(ctx, mm); err != nil {
					// ... 同上
				}
			case <-p.stopc:
				return
			}
		}
	}()
```

原因是 `r.Process` 在处理提案时可能阻塞（无 leader 时要等），如果两个 channel 共用一个 goroutine，一条卡住的提案会把心跳、投票响应的处理一起拖死。缓冲区大小也是按这个前提定的：`recvc` 是 `recvBufSize = 4096`（`peer.go:43`），`propc` 是 `maxPendingProposals = 4096`（`peer.go:50`，注释论证了"一次 leader 选举最多 1 秒、并发提案者少于 4096"所以够用）。

### send: Non-Blocking Delivery, Drop When Full

```go
// server/etcdserver/api/rafthttp/peer.go:236
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
				zap.String("message-type", m.GetType().String()),
				zap.String("local-member-id", p.localID.String()),
				// ... from / remote-peer-id / remote-peer-name（name 即 pick 返回的通道名）
			)
		}
		sentFailures.WithLabelValues(types.ID(m.GetTo()).String()).Inc()
	}
}
```

`select` 带 `default` 是**故意的**：队列满时立刻丢，绝不阻塞 Raft 主循环。丢弃会通过 `ReportUnreachable` 反馈给 raft 状态机，raft 层面再决定是否重试或推进 commit。`p.paused` 由 `Pause()`/`Resume()`（`peer.go:297`/`:306`）控制，用于测试时静默掐流——注意 `Pause` 也会连带 pause 两个 reader。

`isMsgApp` / `isMsgSnap` 是两个只有一行的辅助函数（`peer.go:351`、`:353`），用 `GetType()` 而非直接取字段。

## Stream Channel

全在 `stream.go`（718 行）。核心是**两对** reader/writer，通过 HTTP 长连接对接：

- **发送侧 `streamWriter`**：本端是 HTTP **响应**的写入方。`streamHandler.ServeHTTP` 收到对端的 GET 请求后，把 `outgoingConn`（`stream.go:107`，内嵌 `io.Writer` + `http.Flusher` + `io.Closer`）通过 `p.attachOutgoingConn(conn)` 交给对应 writer。
- **接收侧 `streamReader`**：本端是 HTTP **请求**的发起方，主动 GET 对端的 `/raft/stream/{type}/{localID}`，然后从响应体里循环解码。

`startStreamWriter`（`stream.go:140-157`）只是装配并 `go w.run()`，真正的逻辑在 `run()`（`stream.go:159-309`）。它是一个四路 `select`：

| 分支 | 行为 |
| :--- | :--- |
| `heartbeatc`（`ConnReadTimeout/3` 的 ticker） | 发**链路层**心跳，保活连接 |
| `msgc` | 编码真消息；攒批（`len(msgc)==0` 或 `batched > streamBufSize/2` 时才 Flush） |
| `connc` | 对端刚挂上来的新连接：换 encoder、置 `working = true`、激活 `heartbeatc` 与 `msgc` |
| `stopc` | 关闭连接、退出 |

链路层心跳是理解 stream 的关键一环。`stream.go:98-105`：

```go
// server/etcdserver/api/rafthttp/stream.go:98
var (
	linkHeartbeatMessage = raftpb.Message{Type: raftpb.MsgHeartbeat.Enum()}
	linkHeartbeatSize    = proto.Size(&linkHeartbeatMessage)
)

func isLinkHeartbeatMessage(m *raftpb.Message) bool {
	return m.GetType() == raftpb.MsgHeartbeat && m.GetFrom() == 0 && m.GetTo() == 0
}
```

它**类型是 `MsgHeartbeat`，但 `From` 和 `To` 都是 0**——正常 Raft 消息不会没有收发方，所以这种消息必然来自链路层而非 raft。`streamWriter` 定时发它，`streamReader.decodeLoop` 收��它就 `continue` 丢掉（`stream.go:513-518`）。这解释了为什么 peer 之间需要两套流：`linkHeartbeatMessage` 在每条流上独立保活，某条流断了不影响其他。

> [!NOTE]
> 连接是**单向使用**的：writer 侧靠对端的 GET 请求驱动，reader 侧靠自己的 GET 请求驱动。所以每个 peer 之间实际有 2 条 reader→writer 的 HTTP 请求（`/raft/stream/message` 与 `/raft/stream/msgapp`），加上对端对称发来的 2 条，共 4 条长连接。stream 类型只有两种（`streamTypeMessage`、`streamTypeMsgAppV2`，`stream.go:41-45`），端点路径由 `streamType.endpoint()`（`stream.go:70`）生成。

`streamReader.run`（`stream.go:395-467`）是个 dial-解码-重试循环，退避由 `cr.rl.Wait(cr.ctx)` 控制（`stream.go:445`），退出条件有三类（`stream.go:434-443`）：`io.EOF`（对端正常关闭）与 `transport.IsClosedConnError`（连接被关）都**不算故障**，只有其他错误才 `deactivate`。

`decodeLoop`（`stream.go:470-558`）里有一处影响正确性的分派（`stream.go:522-526`）：

```go
// server/etcdserver/api/rafthttp/stream.go:522
		recvc := cr.recvc
		if m.GetType() == raftpb.MsgProp {
			recvc = cr.propc
		}

		select {
		case recvc <- m:
		default:
			// ... 丢弃并 recvFailures.Inc()
		}
```

收到 `MsgProp` 走 `propc`、其余走 `recvc`——这正是 `startPeer` 要起两个消费 goroutine 的另一半原因。两者缓冲区满时都是**丢**，日志措辞区分 "internal"（连接活跃）与"overloaded network"（连接已断）。

`dial`（`stream.go:568-677`）里有一整套 HTTP 状态码到 Go 错误的映射，这是排障时对照日志的字典：

| 响应 | 含义与动作 |
| :--- | :--- |
| `200` | 成功，返回 `resp.Body` 交给 `decodeLoop` |
| `410 Gone` | 自己已被移出集群 → `reportCriticalError(errMemberRemoved, cr.errorc)` |
| `404` | 对端不认识本节点的 ID（版本不匹配或进度落后太多） |
| `412 Precondition Failed` | 读 body 文本比对：`errIncompatibleVersion` 或 `ErrClusterIDMismatch`（`http.go:64-65`） |
| 其他 | `unhandled http status %d` |

握手头在 `stream.go:592-599` 设置：`X-Server-From`、`X-Server-Version`、`X-Min-Cluster-Version`、`X-Etcd-Cluster-ID`、`X-Raft-To`。`X-Raft-To` 是防串线的关键——服务端会校验它等于自己的 ID（`http.go:434`），不匹配返回 412。

## Pipeline Channel

全在 `pipeline.go`（179 行），结构简单得多：一个 `msgc` 缓冲 + 4 个 `handle` goroutine + 每次一个 POST。

```go
// server/etcdserver/api/rafthttp/pipeline.go:64
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

`connPerPipeline = 4`、`pipelineBufSize = 64`（`pipeline.go:37`、`:42`）。缓冲只有 64 是有注释解释的：`pipelineBufSize` 只需保证"网络卡顿不超过 1 秒时不丢消息"，因为 pipeline 本身是兜底路径，丢消息的代价由 raft 层重试承担。

`handle`（`pipeline.go:94-129`）是发送主循环。相比原笔记，有三处现代化差异需要留意：`pbutil.MustMarshal(&m)` 变成了 `pbutil.MustMarshalMessage(m)`，`m.Size()` 变成了 `proto.Size(m)`，`m.Type == raftpb.MsgApp` 变成了 `isMsgApp(m)`（判定逻辑被抽成函数了）。

```go
// server/etcdserver/api/rafthttp/pipeline.go:94
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

`post`（`pipeline.go:134-176`）是真正发 HTTP 的地方，POST 到 `RaftPrefix`（即 `/raft`），Content-Type 是 `application/protobuf`。它起了一个**看门狗 goroutine**：`done` 通道正常返回时 `cancel()`，`p.stopc` 关闭时先 `waitSchedule()`（`pipeline.go:179`，就是 `runtime.Gosched()`）再 `cancel`——给其他 goroutine 一个被调度的机会，否则正在写的请求会泄漏。

```go
// server/etcdserver/api/rafthttp/pipeline.go:155
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

两处现代化改写值得点名，因为它们是"读旧代码判断新行为"最容易踩的坑：`ioutil.ReadAll` 已改为 `io.ReadAll`（`pipeline.go:158`）；`if err == errMemberRemoved` 已改为 `if errors.Is(err, errMemberRemoved)`（`pipeline.go:169`）——用 `==` 比较 error 在包装 error 的场景下会失效，新代码用 `errors.Is` 才能正确穿透。

`picker.unreachable(u)` 在每条失败路径上都被调用：`urlPicker` 据此把该 endpoint 标记为不可用，后续 `pick()` 会优先选其他 peerURL。多个 peerURL 是官方推荐的高可用部署形态（[cluster.md](/docs/CS/Framework/etcd/cluster.md) 的成员管理一节）。

### Snapshot Uses an Independent Path

快照**不走 pipeline 的 post**，而是 `snapshotSender`（`snapshot_sender.go`，199 行）。`peer.sendSnap`（`peer.go:268`）只是 `go p.snapSender.send(m)`，真正的发送在 `snapshot_sender.go:67`：POST 到 `RaftSnapshotPrefix`（`/raft/snapshot`），Content-Type 是 `application/octet-stream`，body 由 `createSnapBody`（`snapshot_sender.go:185`）从 `snap.Message` 里流出。

> [!TIP]
> 快照为什么要单独一个 sender 而不塞进 pipeline？因为 `snap.Message` 内嵌的是 `io.ReadCloser` 而不是 `[]byte`（`snap/message.go:34-40` 的注释："This avoid copying the entire snapshot into a byte array, which consumes a lot of memory"）。若走 pipeline 就得先全量读进内存，一个几 GB 的快照会直接把进程打爆。流式发送是**唯一**可行方案。

## Handler Implementation and Message Codec

三个 Handler 都在 `http.go`（543 行），共同的骨架是：校验 HTTP 方法 → 校验集群兼容性（`checkClusterCompatibilityFromHeader`，`http.go:471`，比对 `X-Etcd-Cluster-ID` 与 `X-Server-Version`）→ `addRemoteFromRequest`（`util.go:199`，顺手把对端登记进 remotes）→ 解码 → `Raft.Process` → 写状态码。

### pipelineHandler（`http.go:76-170`）

限制单次读 64 KB（`connReadLimitByte`，`http.go:45`），超了会截断——因为 pipeline 传的都是小消息，64 KB 足够且能避免底层读超时。

```go
// server/etcdserver/api/rafthttp/http.go:133
	var m raftpb.Message
	if err := proto.Unmarshal(b, &m); err != nil {
		h.lg.Warn("failed to unmarshal Raft message", /* ... */)
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
			h.lg.Warn("failed to process Raft message", /* ... */)
			http.Error(w, "error processing raft message", http.StatusInternalServerError)
			w.(http.Flusher).Flush()
			// disconnect the http stream
			panic(err)
		}
		return
	}

	// Write StatusNoContent header after the message has been processed by
	// raft, which facilitates the client to report MsgSnap status.
	w.WriteHeader(http.StatusNoContent)
```

注意 `var m raftpb.Message` 是**值**（栈上分配，反序列化填充），但 `Process` 传的是 `&m`——这正是"指针化"在过渡处的形状：值到指针的转换点就在这里。`panic(err)` 是刻意为之：注释写明"disconnect the http stream"，用 panic 强制中断这条连接。

### streamHandler（`http.go:336-469`）

`ServeHTTP` 只做 GET，然后按路径末段（`msgapp` 或 `message`）判定流类型，再从 `path.Base` 解析出对端 ID。它是**唯一会阻塞到连接关闭**的 Handler：末尾 `p.attachOutgoingConn(conn)` 后 `<-c.closeNotify()`（`http.go:463`），把这条 HTTP 请求"占"住当长连接用。

`peerGetter` 接口（`http.go:68`，`Get(id types.ID) Peer`）由 `Transport` 自己实现（`transport.go:170`），所以 handler 能通过它拿到对端 peer 并把连接挂上去。

### snapshotHandler（`http.go:172-334`）

`ServeHTTP` 在 `http.go:208`，开头有一段长注释解释它的容错设计（`http.go:200-206`）：如果发送方进程暴死而不关 TCP 连接，handler 会一直等请求体，直到 TCP keepalive 在几分钟后发现连接已断。这是可接受的，因为快照走独立 TCP 连接、其他快照仍能被收到，且这种情况极少发生。

关键点：它用 `messageDecoder.decodeLimit(snapshotLimitByte)` 解码而非 `proto.Unmarshal`，上限放宽到 64 MB（`snapshotLimitByte`，`http.go:55`）——因为 raft 消息信封里嵌了快照元数据与成员信息；**真正的 DB 快照是请求体的剩余部分**，由 `h.snapshotter.SaveDBFrom(r.Body, m.Snapshot.Metadata.GetIndex())`（`http.go:277`）流式落盘。解完码还要校验 `m.GetType() != raftpb.MsgSnap` 就拒收（`http.go:251`）。

### Codec

| 编解码器 | 文件 | 线格式 | 用在哪 |
| :--- | :--- | :--- | :--- |
| `messageEncoder` / `messageDecoder` | `msg_codec.go:30` / `:43` | 8 字节大端长度前缀 + protobuf | 通用 stream（`/raft/stream/message`） |
| `msgAppV2Encoder` / `msgAppV2Decoder` | `msgappv2_codec.go:66` / `:157` | 自定义紧凑格式 | MsgApp 优化流（`/raft/stream/msgapp`） |

通用格式就是标准"长度前缀 + protobuf"，`decode` 的默认上限是 512 MB（`readBytesLimit`，`msg_codec.go:48`），超限返回 `ErrExceedSizeLimit`。

MsgApp 优化格式才是 rafthttp 里唯一"自己造轮子"的地方。`msgappv2_codec.go:38-64` 有完整的数据格式表，三种首字节：

| 首字节 | 含义 | 后续内容 |
| :--- | :--- | :--- |
| `0x00` | `linkHeartbeatMessage` | 无 |
| `0x01` | `AppEntries` | entries 长度 + 各 entry 长度与数据 + commit index |
| `0x02` | `MsgApp` | 编码后消息长度 + 消息体 |

`AppEntries` 之所以能省掉 index/term，是因为它只在 Raft 的 replicate 状态发送，此时 index 与 term 完全可预测——编码器在 `msgappv2_codec.go:93` 用 `enc.index == m.GetIndex() && enc.term == m.GetLogTerm() && m.GetLogTerm() == m.GetTerm()` 判定能否退化到紧凑形式。写缓冲区预分配 1 MB（`msgAppV2BufSize`，`msgappv2_codec.go:36`）。

## Message Type Attribution

这是 3.7 之后最需要更新的一张认知表。**所有消息类型都在外部模块 `go.etcd.io/raft/v3/raftpb` 里**（`go.mod:37` 声明 `go.etcd.io/raft/v3 v3.7.0`），etcd 主仓库里没有 `raftpb` 目录。

| 类型 | 语义 | rafthttp 里的处理方式 | 生产代码引用点 |
| :--- | :--- | :--- | :--- |
| `MsgApp` | 日志复制 | 走 MsgApp 优化流；stream 不可用时降级 pipeline | `peer.go:351`（`isMsgApp`）、`http.go`（followerStats） |
| `MsgHeartbeat` | 心跳 / 提交位点推进 | 走通用流；`From==To==0` 时是链路层心跳 | `stream.go:99`、`:104`、`raft.go:385` |
| `MsgSnap` | 快照 | **强制** pipeline（发送）/ 独立 sender；接收在 snapshotHandler | `peer.go:353`、`http.go:251`、`raft.go:373` |
| `MsgProp` | 提案 | 收到后转 `propc` 通道 | `stream.go:525` |
| `MsgVote` / `MsgVoteResp` | 投票 | rafthttp **不区分**，走通用流 | 仅测试文件（`functional_test.go:73-74`） |
| `MsgAppResp` | 复制响应 | 不区分，走通用流 | `raft.go:366`（去重） |

两点值得说明：

- **`MsgProp` 在 rafthttp 生产代码里是有一处引用的**（`stream.go:525`，用于选 `propc` 通道），不是"只在测试文件出现"。真正只在测试文件出现的是 `MsgVote` / `MsgVoteResp`——因为投票消息由 raft 库内部直接发出，rafthttp 层的类型判断不需要关心它。
- **`MsgSnap` 走 pipeline 这个"事实"只在 `pick` 层面成立**。真正的快照数据由 `snapshotSender` 直接 POST 到 `/raft/snapshot`，根本不经过 `pick`。`pick` 里的 `isMsgSnap` 分支处理的是那些"类型是 MsgSnap 但没有独立 sender 可用"的边缘情形（例如 leader 刚切换时的在途消息）。

> [!WARNING]
> 3.7.2 的 rafthttp 里还有两类消息**不属于 raft**：`linkHeartbeatMessage`（链路层保活，见上文）与 `MsgUnreachable` 类错误反馈（`r.ReportUnreachable`，`transport.go:39`）。前者不被 `Process` 消费，后者根本不走上行通道。

## Pitfall List

> [!WARNING]
> 这一节的每一条都对应"按旧版印象读 3.7.2 源码会得出的错误结论"。

1. **`raftpb.Message` 已是指针。** `Send` 收 `[]*raftpb.Message`，`Process` 收 `*raftpb.Message`，`peer` 的 `recvc`/`propc` 是 `chan *raftpb.Message`。仍写 `raftpb.Message` 值类型、`chan raftpb.Message`、`m raftpb.Message` 入参的代码片段一律过时。同理 `snap.Message` 是 struct，`SendSnapshot` 收 `*snap.Message`。
2. **`readMessages` / `sendMessages` 不存在。** 全仓库 0 命中。3.7 的消息出入口是 `raftNode.start`（`server/etcdserver/raft.go:174`）里 `case rd := <-r.Ready():`（`raft.go:185`）与 `r.transport.Send(r.processMessages(rd.Messages))`（`raft.go:242`），过滤逻辑在 `processMessages`（`raft.go:357`）。"两个后台 goroutine 一读一写"这个**描述**仍然成立，但**函数名**全变了。
3. **`peerHandler` 不存在。** 3.7.2 的 peer 侧角色是 `Peer` 接口（`peer.go:63`）/ `peer` 实现（`peer.go:101`），创建者是 `startPeer`（`peer.go:131`），由 `Transport.AddPeer`（`transport.go:296`）调用。`remote` 确实存在（`remote.go:24`）但它只有 pipeline，不是双通道的创建者。
4. **`pkg/transport` 不存在。** 3.7.2 顶层无此目录。TLS 相关类型（`transport.TLSInfo`、`transport.IsClosedConnError`）在 `client/pkg/v3/transport`。
5. **raftpb 不在主仓库。** 找不到 `raftpb/` 目录不是环境问题，是架构：类型定义在外部模块 `go.etcd.io/raft/v3/raftpb`。
6. **`AddPeer` 在 `Start()` 之前调用会 panic。** `transport.go:302-304` 显式 `panic("transport stopped")`。启动顺序由 [embed.md](/docs/CS/Framework/etcd/embed.md) 的生命周期保证。
7. **pipeline 的错误比较已改为 `errors.Is`。** `if err == errMemberRemoved`（`pipeline.go:169`）是 3.5 及之前的写法，新代码用 `errors.Is`。同理 `http.go:151` 用 `errors.As` 取 `writerToResponse`。
8. **`ioutil` 已清零。** 3.7.2 的 `pipeline.go:158` 与 `http.go:122` 都用 `io.ReadAll`；`pipeline.go:29` 的 import 块里没有 `io/ioutil`。搜旧代码时别被 `ioutil` 的缺失误导成"读逻辑变了"。
9. **判定消息类型的 helper 优先于裸比较。** 3.7.2 有 `isMsgApp`（`peer.go:351`）、`isMsgSnap`（`peer.go:353`）、`isLinkHeartbeatMessage`（`stream.go:103`），且全部走 `GetType()`/`GetFrom()` 这些 **protoc-gen-go v2 的指针友好 getter**，不是裸字段访问。照着 `m.Type` 写会在 nil 判断上出错。
10. **丢包的默认行为是"静默"。** `peer.send`（`peer.go:244` 的 `select ... default`）与 `streamReader.decodeLoop`（`stream.go:528`）队列满即丢，只在日志与指标上体现。排障要看 `etcd_network_peer_sent_failures_total` 与 `peer_received_failures_total`（`metrics.go`），而不是等报错。
11. **`MsgSnap` 走 pipeline 这条规则有例外路径。** 见上文"消息类型归属"末尾——`pick` 里的 `isMsgSnap` 分支与实际的 `snapshotSender` 是两条不同的发送路径，别以为所有快照都经过 `/raft`。
12. **`raftReadyHandler` 不在 raft.go。** 它定义在 `server/etcdserver/server.go:748`，构造于 `server.go:766`，是 `EtcdServer` 侧的回调集合（`getLead`/`updateLead`/`updateLeadership`/`updateCommittedIndex`），与 rafthttp 无关。别在 rafthttp 里找。

## Links

- [raft（共识模块与 raftNode）](/docs/CS/Framework/etcd/raft.md)
- [etcd（启动流程与 EtcdServer）](/docs/CS/Framework/etcd/etcd.md)
- [monitoring（etcd_network_* 指标与阈值）](/docs/CS/Framework/etcd/monitoring.md)
- [cluster（多 peerURL 高可用部署）](/docs/CS/Framework/etcd/cluster.md)
- [gateway（peer 端口之外的对外入口）](/docs/CS/Framework/etcd/gateway.md)

## References

1. [etcd v3.7.2 rafthttp/transport.go](https://github.com/etcd-io/etcd/blob/v3.7.2/server/etcdserver/api/rafthttp/transport.go)
2. [etcd v3.7.2 rafthttp/peer.go](https://github.com/etcd-io/etcd/blob/v3.7.2/server/etcdserver/api/rafthttp/peer.go)
3. [etcd v3.7.2 rafthttp/stream.go](https://github.com/etcd-io/etcd/blob/v3.7.2/server/etcdserver/api/rafthttp/stream.go)
4. [etcd v3.7.2 rafthttp/pipeline.go](https://github.com/etcd-io/etcd/blob/v3.7.2/server/etcdserver/api/rafthttp/pipeline.go)
5. [etcd v3.7.2 rafthttp/http.go](https://github.com/etcd-io/etcd/blob/v3.7.2/server/etcdserver/api/rafthttp/http.go)
6. [etcd Documentation - Runtime reconfiguration](https://etcd.io/docs/v3.5/op-guide/runtime-configuration/)
