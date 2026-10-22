## Introduction

本页是 ZooKeeper 服务端**网络层**的汇总与对比页。ZooKeeper 有两套客户端连接实现：

- **NIO（默认）**：`NIOServerCnxnFactory`，基于 Java NIO `Selector` 的单线程 IO 多路复用——源码深潜见 **[NIO](/docs/CS/Framework/ZooKeeper/NIO.md)**。
- **Netty**：`NettyServerCnxnFactory`，基于 Netty 的事件驱动实现（本页覆盖）。

两者由系统属性 `zookeeper.serverCnxnFactory` 决定（默认 NIO）。启动时 `QuorumPeerMain::runFromConfig` 调用 `createFactory()` 实例化：

```java
public static ServerCnxnFactory createFactory() throws IOException {
    String serverCnxnFactoryName = System.getProperty(ZOOKEEPER_SERVER_CNXN_FACTORY);
    if (serverCnxnFactoryName == null) {
        serverCnxnFactoryName = NIOServerCnxnFactory.class.getName();
    }
    try {
        ServerCnxnFactory serverCnxnFactory = (ServerCnxnFactory) Class.forName(serverCnxnFactoryName)
                                                                       .getDeclaredConstructor()
                                                                       .newInstance();
```

### 页内导航

- **NIO 实现** → 独立页 [NIO](/docs/CS/Framework/ZooKeeper/NIO.md)（configure / Queue / AcceptThread / SelectorThread / doIO）
- **[Netty 实现](#netty)** —— `NettyServerCnxnFactory`（本节）
- **[NIO vs Netty 对比](#comparsion)** —— 线程模型、粘包拆包、写事件、直接内存等维度
- **[processConnectRequest](#processconnectrequest) / [handle](#handle)** —— 连接建立与 Quorum 连接（选主端口）处理

> [!NOTE]
> 客户端连接的处理链（`ConnectRequest` → 会话建立 → 请求进入 pipeline）见 [pipeline](/docs/CS/Framework/ZooKeeper/pipeline.md)；会话语义见 [Session](/docs/CS/Framework/ZooKeeper/Session.md)。

## Netty





```java
public class NettyServerCnxnFactory extends ServerCnxnFactory {
    @Override
    public void start() {
        if (listenBacklog != -1) {
            bootstrap.option(ChannelOption.SO_BACKLOG, listenBacklog);
        }
        LOG.info(“binding to port {}”, localAddress);
        parentChannel = bootstrap.bind(localAddress).syncUninterruptibly().channel();
        // Port changes after bind() if the original port was 0, update
        // localAddress to get the real port.
        localAddress = (InetSocketAddress) parentChannel.localAddress();
        LOG.info(“bound to port {}”, getLocalPort());
    }
}
```

## Comparsion

简单比较

| ***不同点\*** | ***NIO\***                                                   | ***Netty\***                                                 |
| :------------ | :----------------------------------------------------------- | :----------------------------------------------------------- |
| accept事件    | 启动1个accept thread                                         | boss group处理accept事件,默认启动1个线程                     |
| select()      | 启动select thread                                            | 添加handler时调用addLast(EventExecutorGroup, ChannelHandler…),则handler处理IO事件会在EventExecutorGroup中进行 |
| 网络IO        | 启动worker thread                                            | 启动work group处理网络IO,默认启动核心数∗2核心数∗2个线程      |
| 处理读事件    | 在worker thread中调用NIOServerCnxn.doIO()处理                | 在handler中处理读事件                                        |
| 粘包拆包      | 通过lenBuffer和incomingBuffer解决该问题,代码很复杂           | 插入处理粘包拆包的handler即可                                |
| 处理写事件    | 执行FinalRP.processRequest()的线程与worker thread通过NIOServerCnxn.outgoingBuffers进行通信,由worker thread批量写 | netty天生支持异步写,若当前线程为EventLoop线程,则将待写入数据存放到ChannelOutboundBuffer中.若当前线程不是EventLoop线程,构造写任务添加至EventLoop任务队列中 |
| 直接内存      | 使用ThreadLocal的直接内存                                    | 记不太清楚netty中如何使用直接内存了,但netty支持直接内存,且使用较为方便 |
| 处理连接关闭  | 启动connection expiration thread管理连接                     | 在handler中处理连接                                          |

## processConnectRequest 





```java
@SuppressFBWarnings(value = "IS2_INCONSISTENT_SYNC", justification = "the value won't change after startup")
public void processConnectRequest(ServerCnxn cnxn, ConnectRequest request) throws IOException, ClientCnxnLimitException {
    LOG.debug(
        "Session establishment request from client {} client's lastZxid is 0x{}",
        cnxn.getRemoteSocketAddress(),
        Long.toHexString(request.getLastZxidSeen()));

    long sessionId = request.getSessionId();
    int tokensNeeded = 1;
    if (connThrottle.isConnectionWeightEnabled()) {
        if (sessionId == 0) {
            if (localSessionEnabled) {
                tokensNeeded = connThrottle.getRequiredTokensForLocal();
            } else {
                tokensNeeded = connThrottle.getRequiredTokensForGlobal();
            }
        } else {
            tokensNeeded = connThrottle.getRequiredTokensForRenew();
        }
    }

    if (!connThrottle.checkLimit(tokensNeeded)) {
        throw new ClientCnxnLimitException();
    }
    ServerMetrics.getMetrics().CONNECTION_TOKEN_DEFICIT.add(connThrottle.getDeficit());
    ServerMetrics.getMetrics().CONNECTION_REQUEST_COUNT.add(1);

    if (!cnxn.protocolManager.isReadonlyAvailable()) {
    }

    if (!request.getReadOnly() && this instanceof ReadOnlyZooKeeperServer) {
        String msg = "Refusing session request for not-read-only client " + cnxn.getRemoteSocketAddress();
        LOG.info(msg);
        throw new CloseRequestException(msg, ServerCnxn.DisconnectReason.NOT_READ_ONLY_CLIENT);
    }
    if (request.getLastZxidSeen() > zkDb.dataTree.lastProcessedZxid) {
        throw new CloseRequestException(msg, ServerCnxn.DisconnectReason.CLIENT_ZXID_AHEAD);
    }
    int sessionTimeout = request.getTimeOut();
    byte[] passwd = request.getPasswd();
    int minSessionTimeout = getMinSessionTimeout();
    if (sessionTimeout < minSessionTimeout) {
        sessionTimeout = minSessionTimeout;
    }
    int maxSessionTimeout = getMaxSessionTimeout();
    if (sessionTimeout > maxSessionTimeout) {
        sessionTimeout = maxSessionTimeout;
    }
    cnxn.setSessionTimeout(sessionTimeout);
    // We don't want to receive any packets until we are sure that the
    // session is setup
    cnxn.disableRecv();
    if (sessionId == 0) {
        long id = createSession(cnxn, passwd, sessionTimeout);
    } else {
        validateSession(cnxn, sessionId);
        if (serverCnxnFactory != null) {
            serverCnxnFactory.closeSession(sessionId, ServerCnxn.DisconnectReason.CLIENT_RECONNECT);
        }
        if (secureServerCnxnFactory != null) {
            secureServerCnxnFactory.closeSession(sessionId, ServerCnxn.DisconnectReason.CLIENT_RECONNECT);
        }
        cnxn.setSessionId(sessionId);
        reopenSession(cnxn, sessionId, passwd, sessionTimeout);
        ServerMetrics.getMetrics().CONNECTION_REVALIDATE_COUNT.add(1);

    }
}
```





### doIO

```java
void doIO(SelectionKey k) throws InterruptedException {
    try {
        if (!isSocketOpen()) {
            LOG.warn("trying to do i/o on a null socket for session: 0x{}", Long.toHexString(sessionId));

            return;
        }
        if (k.isReadable()) {
            int rc = sock.read(incomingBuffer);
            if (rc < 0) {
                try {
                    handleFailedRead();
                } catch (EndOfStreamException e) {
                    // no stacktrace. this case is very common, and it is usually not a problem.
                    LOG.info("{}", e.getMessage());
                    // expecting close to log session closure
                    close(e.getReason());
                    return;
                }
            }
            if (incomingBuffer.remaining() == 0) {
                boolean isPayload;
                if (incomingBuffer == lenBuffer) { // start of next request
                    incomingBuffer.flip();
                    isPayload = readLength(k);
                    incomingBuffer.clear();
                } else {
                    // continuation
                    isPayload = true;
                }
                if (isPayload) { // not the case for 4letterword
                    readPayload();
                } else {
                    // four letter words take care
                    // need not do anything else
                    return;
                }
            }
        }
        if (k.isWritable()) {
            handleWrite(k);

            if (!initialized && !getReadInterest() && !getWriteInterest()) {
                throw new CloseRequestException("responded to info probe", DisconnectReason.INFO_PROBE);
            }
        }
    } catch (CancelledKeyException e) {
        close(DisconnectReason.CANCELLED_KEY_EXCEPTION);
    } catch (CloseRequestException e) {
        // expecting close to log session closure
        close();
    } catch (EndOfStreamException e) {
        LOG.warn("Unexpected exception", e);
        // expecting close to log session closure
        close(e.getReason());
    } catch (ClientCnxnLimitException e) {
        // Common case exception, print at debug level
        ServerMetrics.getMetrics().CONNECTION_REJECTED.add(1);
        LOG.warn("Closing session 0x{}", Long.toHexString(sessionId), e);
        close(DisconnectReason.CLIENT_CNX_LIMIT);
    } catch (IOException e) {
        LOG.warn("Close of session 0x{}", Long.toHexString(sessionId), e);
        close(DisconnectReason.IO_EXCEPTION);
    }
}
```



sendBuffer

待发送的数据添加到outgoingBuffers

```java
public void sendBuffer(ByteBuffer... buffers) {
    synchronized (outgoingBuffers) {
        for (ByteBuffer buffer : buffers) {
            outgoingBuffers.add(buffer);
        }
        outgoingBuffers.add(packetSentinel);
    }
    requestInterestOpsUpdate();
}
```



NIOServerCnxnFactory中设置了ThreadLocal的DirectByteBuffer 容量默认64k

## handle

```java
private void handleConnection(Socket sock, DataInputStream din) throws IOException {
    Long sid = null, protocolVersion = null;
    MultipleAddresses electionAddr = null;

    try {
        protocolVersion = din.readLong();
        if (protocolVersion >= 0) { // this is a server id and not a protocol version
            sid = protocolVersion;
        } else {
            try {
                InitialMessage init = InitialMessage.parse(protocolVersion, din);
                sid = init.sid;
                if (!init.electionAddr.isEmpty()) {
                    electionAddr = new MultipleAddresses(init.electionAddr,
                            Duration.ofMillis(self.getMultiAddressReachabilityCheckTimeoutMs()));
                }
                LOG.debug("Initial message parsed by {}: {}", self.getMyId(), init.toString());
            } catch (InitialMessage.InitialMessageException ex) {
                LOG.error("Initial message parsing error!", ex);
                closeSocket(sock);
                return;
            }
        }

        if (sid == QuorumPeer.OBSERVER_ID) {
            /*
             * Choose identifier at random. We need a value to identify
             * the connection.
             */
            sid = observerCounter.getAndDecrement();
            LOG.info("Setting arbitrary identifier to observer: {}", sid);
        }
    } catch (IOException e) {
        LOG.warn("Exception reading or writing challenge", e);
        closeSocket(sock);
        return;
    }

    // do authenticating learner
    authServer.authenticate(sock, din);
    //If wins the challenge, then close the new connection.
    if (sid < self.getMyId()) {
        /*
         * This replica might still believe that the connection to sid is
         * up, so we have to shut down the workers before trying to open a
         * new connection.
         */
        SendWorker sw = senderWorkerMap.get(sid);
        if (sw != null) {
            sw.finish();
        }

        /*
         * Now we start a new connection
         */
        LOG.debug("Create new connection to server: {}", sid);
        closeSocket(sock);

        if (electionAddr != null) {
            connectOne(sid, electionAddr);
        } else {
            connectOne(sid);
        }

    } else if (sid == self.getMyId()) {
        // we saw this case in ZOOKEEPER-2164
        LOG.warn("We got a connection request from a server with our own ID. "
                 + "This should be either a configuration error, or a bug.");
    } else { // Otherwise start worker threads to receive data.
        SendWorker sw = new SendWorker(sock, sid);
        RecvWorker rw = new RecvWorker(sock, din, sid, sw);
        sw.setRecv(rw);

        SendWorker vsw = senderWorkerMap.get(sid);

        if (vsw != null) {
            vsw.finish();
        }

        senderWorkerMap.put(sid, sw);

        queueSendMap.putIfAbsent(sid, new CircularBlockingQueue<>(SEND_CAPACITY));

        sw.start();
        rw.start();
    }
}
```



```java
synchronized boolean connectOne(long sid, MultipleAddresses electionAddr) {
    if (senderWorkerMap.get(sid) != null) {
        LOG.debug("There is a connection already for server {}", sid);
        if (self.isMultiAddressEnabled() && electionAddr.size() > 1 && self.isMultiAddressReachabilityCheckEnabled()) {
            // since ZOOKEEPER-3188 we can use multiple election addresses to reach a server. It is possible, that the
            // one we are using is already dead and we need to clean-up, so when we will create a new connection
            // then we will choose an other one, which is actually reachable
            senderWorkerMap.get(sid).asyncValidateIfSocketIsStillReachable();
        }
        return true;
    }

    // we are doing connection initiation always asynchronously, since it is possible that
    // the socket connection timeouts or the SSL handshake takes too long and don't want
    // to keep the rest of the connections to wait
    return initiateConnectionAsync(electionAddr, sid);
}
```



```java
public boolean initiateConnectionAsync(final MultipleAddresses electionAddr, final Long sid) {
    if (!inprogressConnections.add(sid)) {
        // simply return as there is a connection request to
        // server 'sid' already in progress.
        LOG.debug("Connection request to server id: {} is already in progress, so skipping this request", sid);
        return true;
    }
    try {
        connectionExecutor.execute(new QuorumConnectionReqThread(electionAddr, sid));
        connectionThreadCnt.incrementAndGet();
    } catch (Throwable e) {
        // Imp: Safer side catching all type of exceptions and remove 'sid'
        // from inprogress connections. This is to avoid blocking further
        // connection requests from this 'sid' in case of errors.
        inprogressConnections.remove(sid);
        LOG.error("Exception while submitting quorum connection request", e);
        return false;
    }
    return true;
}
```

异步


```java
private class QuorumConnectionReqThread extends ZooKeeperThread {
    final MultipleAddresses electionAddr;
    final Long sid;
    QuorumConnectionReqThread(final MultipleAddresses electionAddr, final Long sid) {
        super("QuorumConnectionReqThread-" + sid);
        this.electionAddr = electionAddr;
        this.sid = sid;
    }

    @Override
    public void run() {
        try {
            initiateConnection(electionAddr, sid);
        } finally {
            inprogressConnections.remove(sid);
        }
    }

}
```
First we create the socket, perform SSL handshake and authentication if needed.
Then we perform the initiation protocol.
If this server has initiated the connection, then it gives up on the connection if it loses challenge. Otherwise, it keeps the connection.

```java
public void initiateConnection(final MultipleAddresses electionAddr, final Long sid) {
    Socket sock = null;
    try {
        if (self.isSslQuorum()) {
            sock = self.getX509Util().createSSLSocket();
        } else {
            sock = SOCKET_FACTORY.get();
        }
        setSockOpts(sock);
        sock.connect(electionAddr.getReachableOrOne(), cnxTO);
        if (sock instanceof SSLSocket) {
            SSLSocket sslSock = (SSLSocket) sock;
            sslSock.startHandshake();
            LOG.info("SSL handshake complete with {} - {} - {}",
                     sslSock.getRemoteSocketAddress(),
                     sslSock.getSession().getProtocol(),
                     sslSock.getSession().getCipherSuite());
        }

        LOG.debug("Connected to server {} using election address: {}:{}",
                  sid, sock.getInetAddress(), sock.getPort());
    } catch (X509Exception e) {
        LOG.warn("Cannot open secure channel to {} at election address {}", sid, electionAddr, e);
        closeSocket(sock);
        return;
    } catch (UnresolvedAddressException | IOException e) {
        LOG.warn("Cannot open channel to {} at election address {}", sid, electionAddr, e);
        closeSocket(sock);
        return;
    }

    try {
        startConnection(sock, sid);
    } catch (IOException e) {
        LOG.error(
          "Exception while connecting, id: {}, addr: {}, closing learner connection",
          sid,
          sock.getRemoteSocketAddress(),
          e);
        closeSocket(sock);
    }
}
```



start

这里判断如果对方server的

当出现如下报错时 代表该机器无法与其它

> Have smaller server identifier, so dropping the connection

需要检查连接配置

例如是否是host配置问题导致无法和其它机器通信

或者是myid最小的机器 需要重启全部机器 从小到大

```java
private boolean startConnection(Socket sock, Long sid) throws IOException {
    DataOutputStream dout = null;
    DataInputStream din = null;
    LOG.debug("startConnection (myId:{} --> sid:{})", self.getMyId(), sid);
    try {
        // Use BufferedOutputStream to reduce the number of IP packets. This is
        // important for x-DC scenarios.
        BufferedOutputStream buf = new BufferedOutputStream(sock.getOutputStream());
        dout = new DataOutputStream(buf);

        // Sending id and challenge

        // First sending the protocol version (in other words - message type).
        // For backward compatibility reasons we stick to the old protocol version, unless the MultiAddress
        // feature is enabled. During rolling upgrade, we must make sure that all the servers can
        // understand the protocol version we use to avoid multiple partitions. see ZOOKEEPER-3720
        long protocolVersion = self.isMultiAddressEnabled() ? PROTOCOL_VERSION_V2 : PROTOCOL_VERSION_V1;
        dout.writeLong(protocolVersion);
        dout.writeLong(self.getMyId());

        // now we send our election address. For the new protocol version, we can send multiple addresses.
        Collection<InetSocketAddress> addressesToSend = protocolVersion == PROTOCOL_VERSION_V2
                ? self.getElectionAddress().getAllAddresses()
                : Arrays.asList(self.getElectionAddress().getOne());

        String addr = addressesToSend.stream()
                .map(NetUtils::formatInetAddr).collect(Collectors.joining("|"));
        byte[] addr_bytes = addr.getBytes();
        dout.writeInt(addr_bytes.length);
        dout.write(addr_bytes);
        dout.flush();

        din = new DataInputStream(new BufferedInputStream(sock.getInputStream()));
    } catch (IOException e) {
        LOG.warn("Ignoring exception reading or writing challenge: ", e);
        closeSocket(sock);
        return false;
    }

    // authenticate learner
    QuorumPeer.QuorumServer qps = self.getVotingView().get(sid);
    if (qps != null) {
        // TODO - investigate why reconfig makes qps null.
        authLearner.authenticate(sock, qps.hostname);
    }

    // If lost the challenge, then drop the new connection
    if (sid > self.getMyId()) {
        LOG.info("Have smaller server identifier, so dropping the connection: (myId:{} --> sid:{})", self.getMyId(), sid);
        closeSocket(sock);
        // Otherwise proceed with the connection
    } else {
        LOG.debug("Have larger server identifier, so keeping the connection: (myId:{} --> sid:{})", self.getMyId(), sid);
        SendWorker sw = new SendWorker(sock, sid);
        RecvWorker rw = new RecvWorker(sock, din, sid, sw);
        sw.setRecv(rw);

        SendWorker vsw = senderWorkerMap.get(sid);

        if (vsw != null) {
            vsw.finish();
        }

        senderWorkerMap.put(sid, sw);

        queueSendMap.putIfAbsent(sid, new CircularBlockingQueue<>(SEND_CAPACITY));

        sw.start();
        rw.start();

        return true;

    }
    return false;
}
```

## Links

- [NIO（默认实现源码深潜）](/docs/CS/Framework/ZooKeeper/NIO.md)
- [ZooKeeper（概念枢纽）](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)
- [请求处理链 pipeline](/docs/CS/Framework/ZooKeeper/pipeline.md)
- [Session（连接与会话）](/docs/CS/Framework/ZooKeeper/Session.md)
- [Election（Quorum 连接与选主通信）](/docs/CS/Framework/ZooKeeper/Election.md)
- [客户端 client](/docs/CS/Framework/ZooKeeper/client.md)

## References

1. [ZooKeeper Programmer's Guide](https://zookeeper.apache.org/doc/current/zookeeperProgrammers.html)
2. [Netty 官方文档](https://netty.io/)
