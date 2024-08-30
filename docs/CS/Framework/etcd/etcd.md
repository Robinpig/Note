## Introduction

etcd is a distributed reliable key-value store for the most critical data of a distributed system, with a focus on being:

* *Simple*: well-defined, user-facing API (gRPC)
* *Secure*: automatic TLS with optional client cert authentication
* *Fast*: benchmarked 10,000 writes/sec
* *Reliable*: properly distributed using Raft

etcd is written in Go and uses the [Raft](/docs/CS/Distributed/Raft.md) consensus algorithm to manage a highly-available replicated log.
etcd 通过 Raft 协议进行 leader 选举和数据备份，对外提供高可用的数据存储，能有效应对网络问题和机器故障带来的数据丢失问题。
同时它还可以提供服务发现、分布式锁、分布式数据队列、分布式通知和协调、集群选举等功能

etcd 是 Kubernetes 的后端唯一存储实现


## Architecture


etcd 整体架构如下图所示：


<div style="text-align: center;">

![Fig.1. Queue](img/Architecture.png)

</div>

<p style="text-align: center;">
Fig.1. Architecture
</p>

从大体上可以将其划分为以下 4 个模块：



- http：负责对外提供 http 访问接口和 http client
- raft 状态机：根据接受的 raft 消息进行状态转移，调用各状态下的动作。
- wal 日志存储：持久化存储日志条目。
- kv 数据存储：kv 数据的存储引擎，v3 支持不同的后端存储，当前采用 boltdb。通过 boltdb 支持事务操作。




相对于 v2，v3 的主要改动点为：

1. 使用 grpc 进行 peer 之间和与客户端之间通信；
2. v2 的 store 是在内存中的一棵树，v3 采用抽象了一个 kvstore，支持不同的后端存储数据库。增强了事务能力。
3. 去除单元测试代码，etcd v2 的代码行数约 40k，v3 的代码行数约 70k。
4. 2.3 典型内部处理流程
5. 我们将上面架构图的各个部分进行编号，以便下文的处理流程介绍中，对应找到每个流程处理的组件位置。





EtcdServer:是整个 etcd 节点的功能的入口，包含 etcd 节点运行过程中需要的大部分成员。



raftNode 是 Raft 节点，维护 Raft 状态机的步进和状态迁移





## 消息处理

消息入口

一个 etcd 节点运行以后，有 3 个通道接收外界消息，以 kv 数据的增删改查请求处理为例，介绍这 3 个通道的工作机制。

1. client 的 http 调用：会通过注册到 http 模块的 keysHandler 的 ServeHTTP 方法处理。解析好的消息调用 EtcdServer 的 Do()方法处理。(图中 2)
2. client 的 grpc 调用：启动时会向 grpc server 注册 quotaKVServer 对象，quotaKVServer 是以组合的方式增强了 kvServer 这个数据结构。grpc 消息解析完以后会调用 kvServer 的 Range、Put、DeleteRange、Txn、Compact 等方法。kvServer 中包含有一个 RaftKV 的接口，由 EtcdServer 这个结构实现。所以最后就是调用到 EtcdServer 的 Range、Put、DeleteRange、Txn、Compact 等方法。(图中 1)
3. 节点之间的 grpc 消息：每个 EtcdServer 中包含有 Transport 结构，Transport 中会有一个 peers 的 map，每个 peer 封装了节点到其他某个节点的通信方式。包括 streamReader、streamWriter 等，用于消息的发送和接收。streamReader 中有 recvc 和 propc 队列，streamReader 处理完接收到的消息会将消息推到这连个队列中。由 peer 去处理，peer 调用 raftNode 的 Process 方法处理消息。(图中 3、4)



EtcdServer 消息处理

对于客户端消息，调用到 EtcdServer 处理时，一般都是先注册一个等待队列，调用 node 的 Propose 方法，然后用等待队列阻塞等待消息处理完成。Propose 方法会往 propc 队列中推送一条 MsgProp 消息。 对于节点间的消息，raftNode 的 Process 是直接调用 node 的 step 方法，将消息推送到 node 的 recvc 或者 propc 队列中。 可以看到，外界所有消息这时候都到了 node 结构中的 recvc 队列或者 propc 队列中。(图中 5)



node 处理消息

node 启动时会启动一个协程，处理 node 的各个队列中的消息，当然也包括 recvc 和 propc 队列。从 propc 和 recvc 队列中拿到消息，会调用 raft 对象的 Step 方法，raft 对象封装了 raft 的协议数据和操作，其对外的 Step 方法是真正 raft 协议状态机的步进方法。当接收到消息以后，根据协议类型、Term 字段做相应的状态改变处理，或者对选举请求做相应处理。对于一般的 kv 增删改查数据请求消息，会调用内部的 step 方法。



内部的 step 方法是一个可动态改变的方法，将随状态机的状态变化而变化。当状态机处于 leader 状态时，该方法就是 stepLeader；当状态机处于 follower 状态时，该方法就是 stepFollower；当状态机处于 Candidate 状态时，该方法就是 stepCandidate。leader 状态会直接处理 MsgProp 消息。将消息中的日志条目存入本地缓存。follower 则会直接将 MsgProp 消息转发给 leader，转发的过程是将先将消息推送到 raft 的 msgs 数组中。 node 处理完消息以后，要么生成了缓存中的日志条目，要么生成了将要发送出去的消息。缓存中的日志条目需要进一步处理(比如同步和持久化)，而消息需要进一步处理发送出去。



处理过程还是在 node 的这个协程中，在循环开始会调用 newReady，将需要进一步处理的日志和需要发送出去的消息，以及状态改变信息，都封装在一个 Ready 消息中。Ready 消息会推行到 readyc 队列中。(图中 5)



raftNode 的处理

raftNode 的 start()方法另外启动了一个协程，处理 readyc 队列(图中 6)。

取出需要发送的 message，调用 transport 的 Send 方法并将其发送出去(图中 4)。

调用 storage 的 Save 方法持久化存储日志条目或者快照(图中 9、10)，更新 kv 缓存。

另外需要将已经同步好的日志应用到状态机中，让状态机更新状态和 kv 存储，通知等待请求完成的客户端。因此需要将已经确定同步好的日志、快照等信息封装在一个 apply 消息中推送到 applyc 队列。

 

EtcdServer 的 apply 处理

EtcdServer 会处理这个 applyc 队列，会将 snapshot 和 entries 都 apply 到 kv 存储中去(图中 8)。



最后调用 applyWait 的 Trigger，唤醒客户端请求的等待线程，返回客户端的请求。






## Network

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

## Serve

Serve accepts incoming connections on the Listener l, creating a new service goroutine for each.
The service goroutines read requests and then call srv.Handler to reply to them.

HTTP/2 support is only enabled if the Listener returns *tls.Conn connections and they were configured with "h2" in the TLS Config.NextProtos.

Serve always returns a non-nil error and closes l.
After Shutdown or Close, the returned error is ErrServerClosed.

```go
func (srv *Server) Serve(l net.Listener) error {
	if fn := testHookServerServe; fn != nil {
		fn(srv, l) // call hook with unwrapped listener
	}

	origListener := l
	l = &onceCloseListener{Listener: l}
	defer l.Close()

	if err := srv.setupHTTP2_Serve(); err != nil {
		return err
	}

	if !srv.trackListener(&l, true) {
		return ErrServerClosed
	}
	defer srv.trackListener(&l, false)

	baseCtx := context.Background()
	if srv.BaseContext != nil {
		baseCtx = srv.BaseContext(origListener)
		if baseCtx == nil {
			panic("BaseContext returned a nil context")
		}
	}

	var tempDelay time.Duration // how long to sleep on accept failure

	ctx := context.WithValue(baseCtx, ServerContextKey, srv)
	for {
		rw, err := l.Accept()
		if err != nil {
			select {
			case <-srv.getDoneChan():
				return ErrServerClosed
			default:
			}
			if ne, ok := err.(net.Error); ok && ne.Temporary() {
				if tempDelay == 0 {
					tempDelay = 5 * time.Millisecond
				} else {
					tempDelay *= 2
				}
				if max := 1 * time.Second; tempDelay > max {
					tempDelay = max
				}
				srv.logf("http: Accept error: %v; retrying in %v", err, tempDelay)
				time.Sleep(tempDelay)
				continue
			}
			return err
		}
		connCtx := ctx
		if cc := srv.ConnContext; cc != nil {
			connCtx = cc(connCtx, rw)
			if connCtx == nil {
				panic("ConnContext returned nil")
			}
		}
		tempDelay = 0
		c := srv.newConn(rw)
		c.setState(c.rwc, StateNew, runHooks) // before Serve can return
		go c.serve(connCtx)
	}
}
```
Accept
```go
func (ln stoppableListener) Accept() (c net.Conn, err error) {
	connc := make(chan *net.TCPConn, 1)
	errc := make(chan error, 1)
	go func() {
		tc, err := ln.AcceptTCP()
		if err != nil {
			errc <- err
			return
		}
		connc <- tc
	}()
	select {
	case <-ln.stopc:
		return nil, errors.New("server stopped")
	case err := <-errc:
		return nil, err
	case tc := <-connc:
		tc.SetKeepAlive(true)
		tc.SetKeepAlivePeriod(3 * time.Minute)
		return tc, nil
	}
}
```

Serve a new connection.

```go

func (c *conn) serve(ctx context.Context) {
	c.remoteAddr = c.rwc.RemoteAddr().String()
	ctx = context.WithValue(ctx, LocalAddrContextKey, c.rwc.LocalAddr())
	var inFlightResponse *response
	defer func() {
		if err := recover(); err != nil && err != ErrAbortHandler {
			const size = 64 << 10
			buf := make([]byte, size)
			buf = buf[:runtime.Stack(buf, false)]
			c.server.logf("http: panic serving %v: %v\n%s", c.remoteAddr, err, buf)
		}
		if inFlightResponse != nil {
			inFlightResponse.cancelCtx()
		}
		if !c.hijacked() {
			if inFlightResponse != nil {
				inFlightResponse.conn.r.abortPendingRead()
				inFlightResponse.reqBody.Close()
			}
			c.close()
			c.setState(c.rwc, StateClosed, runHooks)
		}
	}()

	if tlsConn, ok := c.rwc.(*tls.Conn); ok {
		tlsTO := c.server.tlsHandshakeTimeout()
		if tlsTO > 0 {
			dl := time.Now().Add(tlsTO)
			c.rwc.SetReadDeadline(dl)
			c.rwc.SetWriteDeadline(dl)
		}
		if err := tlsConn.HandshakeContext(ctx); err != nil {
			// If the handshake failed due to the client not speaking
			// TLS, assume they're speaking plaintext HTTP and write a
			// 400 response on the TLS conn's underlying net.Conn.
			if re, ok := err.(tls.RecordHeaderError); ok && re.Conn != nil && tlsRecordHeaderLooksLikeHTTP(re.RecordHeader) {
				io.WriteString(re.Conn, "HTTP/1.0 400 Bad Request\r\n\r\nClient sent an HTTP request to an HTTPS server.\n")
				re.Conn.Close()
				return
			}
			c.server.logf("http: TLS handshake error from %s: %v", c.rwc.RemoteAddr(), err)
			return
		}
		// Restore Conn-level deadlines.
		if tlsTO > 0 {
			c.rwc.SetReadDeadline(time.Time{})
			c.rwc.SetWriteDeadline(time.Time{})
		}
		c.tlsState = new(tls.ConnectionState)
		*c.tlsState = tlsConn.ConnectionState()
		if proto := c.tlsState.NegotiatedProtocol; validNextProto(proto) {
			if fn := c.server.TLSNextProto[proto]; fn != nil {
				h := initALPNRequest{ctx, tlsConn, serverHandler{c.server}}
				// Mark freshly created HTTP/2 as active and prevent any server state hooks
				// from being run on these connections. This prevents closeIdleConns from
				// closing such connections. See issue https://golang.org/issue/39776.
				c.setState(c.rwc, StateActive, skipHooks)
				fn(c.server, tlsConn, h)
			}
			return
		}
	}

	// HTTP/1.x from here on.

	ctx, cancelCtx := context.WithCancel(ctx)
	c.cancelCtx = cancelCtx
	defer cancelCtx()

	c.r = &connReader{conn: c}
	c.bufr = newBufioReader(c.r)
	c.bufw = newBufioWriterSize(checkConnErrorWriter{c}, 4<<10)

	for {
		w, err := c.readRequest(ctx)
		if c.r.remain != c.server.initialReadLimitSize() {
			// If we read any bytes off the wire, we're active.
			c.setState(c.rwc, StateActive, runHooks)
		}
		if err != nil {
			const errorHeaders = "\r\nContent-Type: text/plain; charset=utf-8\r\nConnection: close\r\n\r\n"

			switch {
			case err == errTooLarge:
				// Their HTTP client may or may not be
				// able to read this if we're
				// responding to them and hanging up
				// while they're still writing their
				// request. Undefined behavior.
				const publicErr = "431 Request Header Fields Too Large"
				fmt.Fprintf(c.rwc, "HTTP/1.1 "+publicErr+errorHeaders+publicErr)
				c.closeWriteAndWait()
				return

			case isUnsupportedTEError(err):
				// Respond as per RFC 7230 Section 3.3.1 which says,
				//      A server that receives a request message with a
				//      transfer coding it does not understand SHOULD
				//      respond with 501 (Unimplemented).
				code := StatusNotImplemented

				// We purposefully aren't echoing back the transfer-encoding's value,
				// so as to mitigate the risk of cross side scripting by an attacker.
				fmt.Fprintf(c.rwc, "HTTP/1.1 %d %s%sUnsupported transfer encoding", code, StatusText(code), errorHeaders)
				return

			case isCommonNetReadError(err):
				return // don't reply

			default:
				if v, ok := err.(statusError); ok {
					fmt.Fprintf(c.rwc, "HTTP/1.1 %d %s: %s%s%d %s: %s", v.code, StatusText(v.code), v.text, errorHeaders, v.code, StatusText(v.code), v.text)
					return
				}
				publicErr := "400 Bad Request"
				fmt.Fprintf(c.rwc, "HTTP/1.1 "+publicErr+errorHeaders+publicErr)
				return
			}
		}

		// Expect 100 Continue support
		req := w.req
		if req.expectsContinue() {
			if req.ProtoAtLeast(1, 1) && req.ContentLength != 0 {
				// Wrap the Body reader with one that replies on the connection
				req.Body = &expectContinueReader{readCloser: req.Body, resp: w}
				w.canWriteContinue.setTrue()
			}
		} else if req.Header.get("Expect") != "" {
			w.sendExpectationFailed()
			return
		}

		c.curReq.Store(w)

		if requestBodyRemains(req.Body) {
			registerOnHitEOF(req.Body, w.conn.r.startBackgroundRead)
		} else {
			w.conn.r.startBackgroundRead()
		}

		// HTTP cannot have multiple simultaneous active requests.[*]
		// Until the server replies to this request, it can't read another,
		// so we might as well run the handler in this goroutine.
		// [*] Not strictly true: HTTP pipelining. We could let them all process
		// in parallel even if their responses need to be serialized.
		// But we're not going to implement HTTP pipelining because it
		// was never deployed in the wild and the answer is HTTP/2.
		inFlightResponse = w
		serverHandler{c.server}.ServeHTTP(w, w.req)
		inFlightResponse = nil
		w.cancelCtx()
		if c.hijacked() {
			return
		}
		w.finishRequest()
		if !w.shouldReuseConnection() {
			if w.requestBodyLimitHit || w.closedRequestBodyEarly() {
				c.closeWriteAndWait()
			}
			return
		}
		c.setState(c.rwc, StateIdle, runHooks)
		c.curReq.Store((*response)(nil))

		if !w.conn.server.doKeepAlives() {
			// We're in shutdown mode. We might've replied
			// to the user without "Connection: close" and
			// they might think they can send another
			// request, but such is life with HTTP/1.1.
			return
		}

		if d := c.server.idleTimeout(); d != 0 {
			c.rwc.SetReadDeadline(time.Now().Add(d))
			if _, err := c.bufr.Peek(4); err != nil {
				return
			}
		}
		c.rwc.SetReadDeadline(time.Time{})
	}
}
```

### ServeHTTP

```go

func (sh serverHandler) ServeHTTP(rw ResponseWriter, req *Request) {
	handler := sh.srv.Handler
	if handler == nil {
		handler = DefaultServeMux
	}
	if req.RequestURI == "*" && req.Method == "OPTIONS" {
		handler = globalOptionsHandler{}
	}

	if req.URL != nil && strings.Contains(req.URL.RawQuery, ";") {
		var allowQuerySemicolonsInUse int32
		req = req.WithContext(context.WithValue(req.Context(), silenceSemWarnContextKey, func() {
			atomic.StoreInt32(&allowQuerySemicolonsInUse, 1)
		}))
		defer func() {
			if atomic.LoadInt32(&allowQuerySemicolonsInUse) == 0 {
				sh.srv.logf("http: URL query contains semicolon, which is no longer a supported separator; parts of the query may be stripped when parsed; see golang.org/issue/25192")
			}
		}()
	}

	handler.ServeHTTP(rw, req)
}
```

A Handler responds to an HTTP request.

ServeHTTP should write reply headers and data to the ResponseWriter and then return.
Returning signals that the request is finished; it is not valid to use the ResponseWriter or read from the Request.Body after or concurrently with the completion of the ServeHTTP call.

Depending on the HTTP client software, HTTP protocol version, and any intermediaries between the client and the Go server, it may not be possible to read from the Request.Body after writing to the ResponseWriter. Cautious handlers should read the Request.Body first, and then reply.

Except for reading the body, handlers should not modify the provided Request.

If ServeHTTP panics, the server (the caller of ServeHTTP) assumes that the effect of the panic was isolated to the active request.
It recovers the panic, logs a stack trace to the server error log, and either closes the network connection or sends an HTTP/2 RST_STREAM, depending on the HTTP protocol.
To abort a handler so the client sees an interrupted response but the server doesn't log an error, panic with the value ErrAbortHandler.

```go
type Handler interface {
	ServeHTTP(ResponseWriter, *Request)
}
```

RoundTripper is an interface representing the ability to execute a single HTTP transaction, obtaining the Response for a given Request.

A RoundTripper must be safe for concurrent use by multiple goroutines.

RoundTrip executes a single HTTP transaction, returning a Response for the provided Request.

RoundTrip should not attempt to interpret the response.
In particular, RoundTrip must return err == nil if it obtained a response, regardless of the response's HTTP status code.
A non-nil err should be reserved for failure to obtain a response.
Similarly, RoundTrip should not attempt to handle higher-level protocol details such as redirects, authentication, or cookies.

RoundTrip should not modify the request, except for consuming and closing the Request's Body. RoundTrip may read fields of the request in a separate goroutine.
Callers should not mutate or reuse the request until the Response's Body has been closed.

RoundTrip must always close the body, including on errors, but depending on the implementation may do so in a separate goroutine even after RoundTrip returns.
This means that callers wanting to reuse the body for subsequent requests must arrange to wait for the Close call before doing so.

The Request's URL and Header fields must be initialized.

```go
type RoundTripper interface {

	RoundTrip(*Request) (*Response, error)
}
```

RoundTrip implements the RoundTripper interface.

For higher-level HTTP client support (such as handling of cookies and redirects), see Get, Post, and the Client type.

Like the RoundTripper interface, the error types returned by RoundTrip are unspecified.

```go
func (t *Transport) RoundTrip(req *Request) (*Response, error) {
return t.roundTrip(req)
}
```

## Peer

```go

type Peer interface {
	// send sends the message to the remote peer. 
	// The function is non-blocking and has no promise that the message will be received by the remote.
	// When it fails to send message out, it will report the status to underlying raft.
	send(m raftpb.Message)

	// sendSnap sends the merged snapshot message to the remote peer. Its behavior is similar to send.
	sendSnap(m snap.Message)

	// update updates the urls of remote peer.
	update(urls types.URLs)

	// attachOutgoingConn attaches the outgoing connection to the peer for
	// stream usage. After the call, the ownership of the outgoing
	// connection hands over to the peer. The peer will close the connection when it is no longer used.
	attachOutgoingConn(conn *outgoingConn)

	// activeSince returns the time that the connection with the peer becomes active.
	activeSince() time.Time

	// stop performs any necessary finalization and terminates the peer elegantly.
	stop()
}
```

## Links

- [K8s](/docs/CS/Container/K8s.md)


## References

1. [深入浅出 etcd 系列 part 1 – 解析 etcd 的架构和代码框架](https://www.infoq.cn/article/KO9B17UcPZAjbd8sdLi9?utm_source=related_read_bottom&utm_medium=article)