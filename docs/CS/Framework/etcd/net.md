## Introduction


在etcd中有多种消息类型，不同类型的消息所能携带的数据大小也不尽相同，其中快照相关消息的数据量就比较大，小至几KB，大至几 GB都是有可能的，而Leader节点到Follower节点之间的心跳消息一般只有几十到几百个字节。因此，etcd 的网络层会创建两个消息传输通道：Stream消息通道和Pipeline消息通道。


这两种消息通道的主要区别在于：
Stream消息通道维护的HTTP长连接，主要负责传输数据量较小、发送比较频繁的消息，例如，前面介绍的MsgApp消息、MsgHeartbeat消息、MsgVote消息等；而 Pipeline 消息通道在传输数据完成后会立即关闭连接，主要负责传输数据量较大、发送频率较低的消息，例如，MsgSnap消息等

Stream消息通道是节点启动后，主动与集群中的其他节点建立的。每个Stream消息通道有2个关联的后台goroutine，其中一个用于建立关联的HTTP连接，并从连接上读取数据，然后将这些读取到的数据反序列化成Message实例，传递到etcd-raft模块中进行处理。另外一个后台goroutine会读取etcd-raft模块返回的消息数据并将其序列化，最后写入Stream消息通道


在启动 http.Server 时会通过rafthttp.Transporter.Handler（）方法为指定的URL路径添加相应的Handler实例，其中“/raft/stream/”路径对应的Handler为streamHandler类型，它负责处理Stream消息通道 上 的 请 求 。 相 同 的 “ ， /raft” 路 径 对 应 的 Handler 为pipelineHandler 类 型 ， 它 负 责 处 理 Pipeline 通 道 上 的 请 求 ，“/raft/snapshot”路径对应的Handler为snapshotHandler类型，它负责处理Pipeline通道上的请求

rafthttp.Transporter 接口，它是rafthttp包的核心接口之一，它定义了etcd网络层的核心功能
```go
type Transporter interface {
    Start() error
    Handler() http.Handler
    Send(m []raftpb.Message)
    SendSnapshot(m snap.Message)
    AddRemote(id types.ID, urls []string)
    AddPeer(id types.ID, urls []string)
    RemovePeer(id types.ID)
    RemoveAllPeers()
    UpdatePeer(id types.ID, urls []string)
    ActiveSince(id types.ID) time.Time
    ActivePeers() int
    Stop()
}
```

```go
type Raft interface {
    Process(ctx context.Context, m raftpb.Message) error
    IsIDRemoved(id uint64) bool
    ReportUnreachable(id uint64)
    ReportSnapshot(id uint64, status raft.SnapshotStatus)
}
```
rafthttp.Transport是rafthttp.Transporter接口具体实现


```go
// Transport implements Transporter interface. It provides the functionality
// to send raft messages to peers, and receive raft messages from peers.
// User should call Handler method to get a handler to serve requests
// received from peerURLs.
// User needs to call Start before calling other functions, and call
// Stop when the Transport is no longer used.
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
    // LeaderStats is used to record transportation statistics with followers when
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



```go
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

Transport.Handler()方法主要负责创建 Steam 消息通道和Pipeline 消息通道用到的 Handler实例，并注册到相应的请求路径上


```go
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
创建并启动对应节点的 Peer 实例


```go
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

    if t.Logger != nil {
        t.Logger.Info(
            "added remote peer",
            zap.String("local-member-id", t.ID.String()),
            zap.String("remote-peer-id", id.String()),
            zap.Strings("remote-peer-urls", us),
        )
    }
}
```
Peer
```go
type Peer interface {
    // send sends the message to the remote peer. The function is non-blocking
    // and has no promise that the message will be received by the remote.
    // When it fails to send message out, it will report the status to underlying
    // raft.
    send(m raftpb.Message)

    // sendSnap sends the merged snapshot message to the remote peer. Its behavior
    // is similar to send.
    sendSnap(m snap.Message)

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




peer is the representative of a remote raft node. Local raft node sends messages to the remote through peer.
Each peer has two underlying mechanisms to send out a message: stream and pipeline.
A stream is a receiver initialized long-polling connection, which is always open to transfer messages. Besides general stream, peer also has a optimized stream for sending msgApp since msgApp accounts for large part of all messages.
Only raft leader uses the optimized stream to send msgApp to the remote follower node.
A pipeline is a series of http clients that send http requests to the remote.
It is only used when the stream has not been established.
```go
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

    recvc chan raftpb.Message
    propc chan raftpb.Message

    mu     sync.Mutex
    paused bool

    cancel context.CancelFunc // cancel pending works in go routine created by peer.
    stopc  chan struct{}
}
```
rafthttp.peer.startPeer（）方法中完成了初始化的工作，同时也启动了关联的后台goroutine


```go
func startPeer(t *Transport, urls types.URLs, peerID types.ID, fs *stats.FollowerStats) *peer {
    if t.Logger != nil {
        t.Logger.Info("starting remote peer", zap.String("remote-peer-id", peerID.String()))
    }
    defer func() {
        if t.Logger != nil {
            t.Logger.Info("started remote peer", zap.String("remote-peer-id", peerID.String()))
        }
    }()

    status := newPeerStatus(t.Logger, t.ID, peerID)
    picker := newURLPicker(urls)
    errorc := t.ErrorC
    r := t.Raft
    pipeline := &pipeline{
        peerID:        peerID,
        tr:            t,
        picker:        picker,
        status:        status,
        followerStats: fs,
        raft:          r,
        errorc:        errorc,
    }
    pipeline.start()

    p := &peer{
        lg:             t.Logger,
        localID:        t.ID,
        id:             peerID,
        r:              r,
        status:         status,
        picker:         picker,
        msgAppV2Writer: startStreamWriter(t.Logger, t.ID, peerID, status, fs, r),
        writer:         startStreamWriter(t.Logger, t.ID, peerID, status, fs, r),
        pipeline:       pipeline,
        snapSender:     newSnapshotSender(t, picker, peerID, status),
        recvc:          make(chan raftpb.Message, recvBufSize),
        propc:          make(chan raftpb.Message, maxPendingProposals),
        stopc:          make(chan struct{}),
    }

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
                    if t.Logger != nil {
                        t.Logger.Warn("failed to process Raft message", zap.Error(err))
                    }
                }
            case <-p.stopc:
                return
            }
        }
    }()

    p.msgAppV2Reader = &streamReader{
        lg:     t.Logger,
        peerID: peerID,
        typ:    streamTypeMsgAppV2,
        tr:     t,
        picker: picker,
        status: status,
        recvc:  p.recvc,
        propc:  p.propc,
        rl:     rate.NewLimiter(t.DialRetryFrequency, 1),
    }
    p.msgAppReader = &streamReader{
        lg:     t.Logger,
        peerID: peerID,
        typ:    streamTypeMessage,
        tr:     t,
        picker: picker,
        status: status,
        recvc:  p.recvc,
        propc:  p.propc,
        rl:     rate.NewLimiter(t.DialRetryFrequency, 1),
    }

    p.msgAppV2Reader.start()
    p.msgAppReader.start()

    return p
}
```

Transport.Send（）方法就是通过调用peer.send()方法实现消息发送功能

```go
func (p *peer) send(m raftpb.Message) {
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
        p.r.ReportUnreachable(m.To)
        if isMsgSnap(m) {
            p.r.ReportSnapshot(m.To, raft.SnapshotFailure)
        }
        sentFailures.WithLabelValues(types.ID(m.To).String()).Inc()
    }
}

// pick picks a chan for sending the given message. The picked chan and the picked chan
// string name are returned.
func (p *peer) pick(m raftpb.Message) (writec chan<- raftpb.Message, picked string) {
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


```go
func (p *pipeline) start() {
    p.stopc = make(chan struct{})
    p.msgc = make(chan raftpb.Message, pipelineBufSize)
    p.wg.Add(connPerPipeline)
    for i := 0; i < connPerPipeline; i++ {
        go p.handle()
    }
}

func (p *pipeline) handle() {
	defer p.wg.Done()

	for {
		select {
		case m := <-p.msgc:
			start := time.Now()
			err := p.post(pbutil.MustMarshal(&m))
			end := time.Now()

			if err != nil {
				p.status.deactivate(failureType{source: pipelineMsg, action: "write"}, err.Error())

				if m.Type == raftpb.MsgApp && p.followerStats != nil {
					p.followerStats.Fail()
				}
				p.raft.ReportUnreachable(m.To)
				if isMsgSnap(m) {
					p.raft.ReportSnapshot(m.To, raft.SnapshotFailure)
				}
				sentFailures.WithLabelValues(types.ID(m.To).String()).Inc()
				continue
			}

			p.status.activate()
			if m.Type == raftpb.MsgApp && p.followerStats != nil {
				p.followerStats.Succ(end.Sub(start))
			}
			if isMsgSnap(m) {
				p.raft.ReportSnapshot(m.To, raft.SnapshotFinish)
			}
			sentBytes.WithLabelValues(types.ID(m.To).String()).Add(float64(m.Size()))
		case <-p.stopc:
			return
		}
	}
}
```

pipeline.post（）方法是真正完成消息发送的地方，其中会启动一个后台goroutine监听控制发送过程及获取发送结果



```go
// post POSTs a data payload to a url. Returns nil if the POST succeeds,
// error on any failure.
func (p *pipeline) post(data []byte) (err error) {
    u := p.picker.pick()
    req := createPostRequest(p.tr.Logger, u, RaftPrefix, bytes.NewBuffer(data), "application/protobuf", p.tr.URLs, p.tr.ID, p.tr.ClusterID)

    done := make(chan struct{}, 1)
    ctx, cancel := context.WithCancel(context.Background())
    req = req.WithContext(ctx)
    go func() {
        select {
        case <-done:
            cancel()
        case <-p.stopc:
            waitSchedule()
            cancel()
        }
    }()

    resp, err := p.tr.pipelineRt.RoundTrip(req)
    done <- struct{}{}
    if err != nil {
        p.picker.unreachable(u)
        return err
    }
    defer resp.Body.Close()
    b, err := ioutil.ReadAll(resp.Body)
    if err != nil {
        p.picker.unreachable(u)
        return err
    }

    err = checkPostResponse(p.tr.Logger, resp, b, req, p.peerID)
    if err != nil {
        p.picker.unreachable(u)
        // errMemberRemoved is a critical error since a removed member should
        // always be stopped. So we use reportCriticalError to report it to errorc.
        if err == errMemberRemoved {
            reportCriticalError(err, p.errorc)
        }
        return err
    }

    return nil
}
```

## Handler


pipelineHandler 中 实 现 了http.Server.Handler接口的ServeHTTP（）方法，也是其处理请求的核心方法。pipelineHandler.ServeHTTP（）方法通过读取对端节点发来的请求得到相应的消息实例，然后将其交给底层的 etcd-raft 模块进行处理


```go
func (h *pipelineHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
    if r.Method != "POST" {
        w.Header().Set("Allow", "POST")
        http.Error(w, "Method Not Allowed", http.StatusMethodNotAllowed)
        return
    }

    w.Header().Set("X-Etcd-Cluster-ID", h.cid.String())

    if err := checkClusterCompatibilityFromHeader(h.lg, h.localID, r.Header, h.cid); err != nil {
        http.Error(w, err.Error(), http.StatusPreconditionFailed)
        return
    }

    addRemoteFromRequest(h.tr, r)

    // Limit the data size that could be read from the request body, which ensures that read from
    // connection will not time out accidentally due to possible blocking in underlying implementation.
    limitedr := pioutil.NewLimitedBufferReader(r.Body, connReadLimitByte)
    b, err := ioutil.ReadAll(limitedr)
    if err != nil {
        http.Error(w, "error reading raft message", http.StatusBadRequest)
        recvFailures.WithLabelValues(r.RemoteAddr).Inc()
        return
    }

    var m raftpb.Message
    if err := m.Unmarshal(b); err != nil {)
        http.Error(w, "error unmarshalling raft message", http.StatusBadRequest)
        recvFailures.WithLabelValues(r.RemoteAddr).Inc()
        return
    }

    receivedBytes.WithLabelValues(types.ID(m.From).String()).Add(float64(len(b)))

    if err := h.r.Process(context.TODO(), m); err != nil {
        switch v := err.(type) {
        case writerToResponse:
            v.WriteTo(w)
        default:
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
}
```


```go
type streamHandler struct {
    lg         *zap.Logger
    tr         *Transport
    peerGetter peerGetter
    r          Raft
    id         types.ID
    cid        types.ID
}
```

streamHandler的核心也是ServeHTTP()方法
```go
func (h *streamHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
    if r.Method != "GET" {
        w.Header().Set("Allow", "GET")
        http.Error(w, "Method Not Allowed", http.StatusMethodNotAllowed)
        return
    }

    w.Header().Set("X-Server-Version", version.Version)
    w.Header().Set("X-Etcd-Cluster-ID", h.cid.String())

    if err := checkClusterCompatibilityFromHeader(h.lg, h.tr.ID, r.Header, h.cid); err != nil {
        http.Error(w, err.Error(), http.StatusPreconditionFailed)
        return
    }

    var t streamType
    switch path.Dir(r.URL.Path) {
    case streamTypeMsgAppV2.endpoint(h.lg):
        t = streamTypeMsgAppV2
    case streamTypeMessage.endpoint(h.lg):
        t = streamTypeMessage
    default:
        http.Error(w, "invalid path", http.StatusNotFound)
        return
    }

    fromStr := path.Base(r.URL.Path)
    from, err := types.IDFromString(fromStr)
    if err != nil {
        http.Error(w, "invalid from", http.StatusNotFound)
        return
    }
    if h.r.IsIDRemoved(uint64(from)) {
        http.Error(w, "removed member", http.StatusGone)
        return
    }
    p := h.peerGetter.Get(from)
    if p == nil {
        // This may happen in following cases:
        // 1. user starts a remote peer that belongs to a different cluster
        // with the same cluster ID.
        // 2. local etcd falls behind of the cluster, and cannot recognize
        // the members that joined after its current progress.
        if urls := r.Header.Get("X-PeerURLs"); urls != "" {
            h.tr.AddRemote(from, strings.Split(urls, ","))
        }
        http.Error(w, "error sender not found", http.StatusNotFound)
        return
    }

    wto := h.id.String()
    if gto := r.Header.Get("X-Raft-To"); gto != wto {
        http.Error(w, "to field mismatch", http.StatusPreconditionFailed)
        return
    }

    w.WriteHeader(http.StatusOK)
    w.(http.Flusher).Flush()

    c := newCloseNotifier()
    conn := &outgoingConn{
        t:       t,
        Writer:  w,
        Flusher: w.(http.Flusher),
        Closer:  c,
        localID: h.tr.ID,
        peerID:  from,
    }
    p.attachOutgoingConn(conn)
    <-c.closeNotify()
}
```
snapshotHandler.ServeHTTP（）方法除了读取对端节点发来的快照数据，还会在本地生成相应的快照文件，并将快照数据通过Raft接口传递给底层的etcd-raft模块进行处理ServeHTTP serves HTTP request to receive and process snapshot message.
If request sender dies without closing underlying TCP connection, the handler will keep waiting for the request body until TCP keepalive
finds out that the connection is broken after several minutes.
This is acceptable because
1. snapshot messages sent through other TCP connections could still be received and processed.
2. this case should happen rarely, so no further optimization is done.


```go

func (h *snapshotHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
    start := time.Now()

    if r.Method != "POST" {
        w.Header().Set("Allow", "POST")
        http.Error(w, "Method Not Allowed", http.StatusMethodNotAllowed)
        snapshotReceiveFailures.WithLabelValues(unknownSnapshotSender).Inc()
        return
    }

    w.Header().Set("X-Etcd-Cluster-ID", h.cid.String())

    if err := checkClusterCompatibilityFromHeader(h.lg, h.localID, r.Header, h.cid); err != nil {
        http.Error(w, err.Error(), http.StatusPreconditionFailed)
        snapshotReceiveFailures.WithLabelValues(unknownSnapshotSender).Inc()
        return
    }

    addRemoteFromRequest(h.tr, r)

    dec := &messageDecoder{r: r.Body}
    // let snapshots be very large since they can exceed 512MB for large installations
    m, err := dec.decodeLimit(snapshotLimitByte)
    from := types.ID(m.From).String()
    if err != nil {
        msg := fmt.Sprintf("failed to decode raft message (%v)", err)
        h.lg.Warn(
            "failed to decode Raft message",
            zap.String("local-member-id", h.localID.String()),
            zap.String("remote-snapshot-sender-id", from),
            zap.Error(err),
        )
        http.Error(w, msg, http.StatusBadRequest)
        recvFailures.WithLabelValues(r.RemoteAddr).Inc()
        snapshotReceiveFailures.WithLabelValues(from).Inc()
        return
    }

    msgSize := m.Size()
    receivedBytes.WithLabelValues(from).Add(float64(msgSize))

    if m.Type != raftpb.MsgSnap {
        h.lg.Warn(
            "unexpected Raft message type",
            zap.String("local-member-id", h.localID.String()),
            zap.String("remote-snapshot-sender-id", from),
            zap.String("message-type", m.Type.String()),
        )
        http.Error(w, "wrong raft message type", http.StatusBadRequest)
        snapshotReceiveFailures.WithLabelValues(from).Inc()
        return
    }

    snapshotReceiveInflights.WithLabelValues(from).Inc()
    defer func() {
        snapshotReceiveInflights.WithLabelValues(from).Dec()
    }()

    h.lg.Info(
        "receiving database snapshot",
        zap.String("local-member-id", h.localID.String()),
        zap.String("remote-snapshot-sender-id", from),
        zap.Uint64("incoming-snapshot-index", m.Snapshot.Metadata.Index),
        zap.Int("incoming-snapshot-message-size-bytes", msgSize),
        zap.String("incoming-snapshot-message-size", humanize.Bytes(uint64(msgSize))),
    )

    // save incoming database snapshot.

    n, err := h.snapshotter.SaveDBFrom(r.Body, m.Snapshot.Metadata.Index)
    if err != nil {
        msg := fmt.Sprintf("failed to save KV snapshot (%v)", err)
        h.lg.Warn(
            "failed to save incoming database snapshot",
            zap.String("local-member-id", h.localID.String()),
            zap.String("remote-snapshot-sender-id", from),
            zap.Uint64("incoming-snapshot-index", m.Snapshot.Metadata.Index),
            zap.Error(err),
        )
        http.Error(w, msg, http.StatusInternalServerError)
        snapshotReceiveFailures.WithLabelValues(from).Inc()
        return
    }

    receivedBytes.WithLabelValues(from).Add(float64(n))

    downloadTook := time.Since(start)
    h.lg.Info(
        "received and saved database snapshot",
        zap.String("local-member-id", h.localID.String()),
        zap.String("remote-snapshot-sender-id", from),
        zap.Uint64("incoming-snapshot-index", m.Snapshot.Metadata.Index),
        zap.Int64("incoming-snapshot-size-bytes", n),
        zap.String("incoming-snapshot-size", humanize.Bytes(uint64(n))),
        zap.String("download-took", downloadTook.String()),
    )

    if err := h.r.Process(context.TODO(), m); err != nil {
        switch v := err.(type) {
        // Process may return writerToResponse error when doing some
        // additional checks before calling raft.Node.Step.
        case writerToResponse:
            v.WriteTo(w)
        default:
            msg := fmt.Sprintf("failed to process raft message (%v)", err)
            h.lg.Warn(
                "failed to process Raft message",
                zap.String("local-member-id", h.localID.String()),
                zap.String("remote-snapshot-sender-id", from),
                zap.Error(err),
            )
            http.Error(w, msg, http.StatusInternalServerError)
            snapshotReceiveFailures.WithLabelValues(from).Inc()
        }
        return
    }

    // Write StatusNoContent header after the message has been processed by
    // raft, which facilitates the client to report MsgSnap status.
    w.WriteHeader(http.StatusNoContent)

    snapshotReceive.WithLabelValues(from).Inc()
    snapshotReceiveSeconds.WithLabelValues(from).Observe(time.Since(start).Seconds())
}
```





## Links

- [etcd](/docs/CS/Framework/etcd/etcd.md)

