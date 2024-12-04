## Introduction

在QuorumPeerMain::runFromConfig的启动中初始化了Communication layer并设置到QuorumPeer

createFactory

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
        return serverCnxnFactory;
    } catch (Exception e) {
        throw ioe;
    }
}
```

ServerCnxnFactory 实例化之后会依次调用 configure和startup函数 这将取决于具体的实现类型


Zookeeper作为一个服务器,自然要与客户端进行网络通信,如何高效的与客户端进行通信,让网络IO不成为ZooKeeper的瓶颈是ZooKeeper急需解决的问题,ZooKeeper中使用ServerCnxnFactory管理与客户端的连接,从系统属性zookeeper.serverCnxnFactory中获取配置 其有两个实现, 
- 一个是NIOServerCnxnFactory,使用 Java原生NIO实现 默认实现 不支持ssl
- 一个是NettyServerCnxnFactory,使用 Netty实现 ;


> In versions 3.5+, a ZooKeeper server can use Netty instead of NIO (default option) by setting the environment variable zookeeper.serverCnxnFactory to org.apache.zookeeper.server.NettyServerCnxnFactory; for the client, set zookeeper.clientCnxnSocket to org.apache.zookeeper.ClientCnxnSocketNetty.

使用ServerCnxn代表一个客户端与服务端的连接





```java
private void startServerCnxnFactory() {
    if (cnxnFactory != null) {
        cnxnFactory.start();
    }
    if (secureCnxnFactory != null) {
        secureCnxnFactory.start();
    }
}
```


```java
public abstract class ServerCnxnFactory {
    public abstract void startup(ZooKeeperServer zkServer, boolean startServer) throws IOException, InterruptedException;
}
```

```java
public class NIOServerCnxnFactory extends ServerCnxnFactory {
    @Override
    public void startup(ZooKeeperServer zks, boolean startServer) throws IOException, InterruptedException {
        start();
        setZooKeeperServer(zks);
        if (startServer) {
            zks.startdata();
            zks.startup();
        }
    }
}
```



## NIO

NIOServerCnxnFactory implements a multi-threaded ServerCnxnFactory using NIO non-blocking socket calls. 
Communication between threads is handled via queues. 
- 1 accept thread, which accepts new connections and assigns to a selector thread 
- 1-N selector threads, each of which selects on 1/ N of the connections.
  The reason the factory supports more than one selector thread is that with large numbers of connections, select() itself can become a performance bottleneck. 
- 0-M socket I/ O worker threads, which perform basic socket reads and writes. 
  If configured with 0 worker threads, the selector threads do the socket I/ O directly. 
- 1 connection expiration thread, which closes idle connections; this is necessary to expire connections on which no session is established. 

Typical (default) thread counts are: on a 32 core machine, 1 accept thread, 1 connection expiration thread, 4 selector threads, and 64 worker threads.



可以看出,ZooKeeper中对线程需要处理的工作做了更细的拆分.其认为在有大量客户端连接的情况下, `selector.select()` 会成为性能瓶颈,因此其将 `selector.select()` 拆分出来,交由 `selector thread` 处理. 线程间通信





### configure

```java
@Override
public void configure(InetSocketAddress addr, int maxcc, int backlog, boolean secure) throws IOException {
    if (secure) {
        throw new UnsupportedOperationException("SSL isn't supported in NIOServerCnxn");
    }
    configureSaslLogin();

    maxClientCnxns = maxcc;
    initMaxCnxns();
    sessionlessCnxnTimeout = Integer.getInteger(ZOOKEEPER_NIO_SESSIONLESS_CNXN_TIMEOUT, 10000);
    // We also use the sessionlessCnxnTimeout as expiring interval for
    // cnxnExpiryQueue. These don't need to be the same, but the expiring
    // interval passed into the ExpiryQueue() constructor below should be
    // less than or equal to the timeout.
    cnxnExpiryQueue = new ExpiryQueue<>(sessionlessCnxnTimeout);
    expirerThread = new ConnectionExpirerThread();

    int numCores = Runtime.getRuntime().availableProcessors();
    // 32 cores sweet spot seems to be 4 selector threads
    numSelectorThreads = Integer.getInteger(
        ZOOKEEPER_NIO_NUM_SELECTOR_THREADS,
        Math.max((int) Math.sqrt((float) numCores / 2), 1));
    if (numSelectorThreads < 1) {
        throw new IOException("numSelectorThreads must be at least 1");
    }

    numWorkerThreads = Integer.getInteger(ZOOKEEPER_NIO_NUM_WORKER_THREADS, 2 * numCores);
    workerShutdownTimeoutMS = Long.getLong(ZOOKEEPER_NIO_SHUTDOWN_TIMEOUT, 5000);

    String logMsg = "Configuring NIO connection handler with "
        + (sessionlessCnxnTimeout / 1000) + "s sessionless connection timeout, "
        + numSelectorThreads + " selector thread(s), "
        + (numWorkerThreads > 0 ? numWorkerThreads : "no") + " worker threads, and "
        + (directBufferBytes == 0 ? "gathered writes." : ("" + (directBufferBytes / 1024) + " kB direct buffers."));
    LOG.info(logMsg);
    for (int i = 0; i < numSelectorThreads; ++i) {
        selectorThreads.add(new SelectorThread(i));
    }

    listenBacklog = backlog;
    this.ss = ServerSocketChannel.open();
    ss.socket().setReuseAddress(true);
    LOG.info("binding to port {}", addr);
    if (listenBacklog == -1) {
        ss.socket().bind(addr);
    } else {
        ss.socket().bind(addr, listenBacklog);
    }
    if (addr.getPort() == 0) {
        // We're likely bound to a different port than was requested, so log that too
        LOG.info("bound to port {}", ss.getLocalAddress());
    }
    ss.configureBlocking(false);
    acceptThread = new AcceptThread(ss, addr, selectorThreads);
}
```

start


```java
public class NIOServerCnxnFactory extends ServerCnxnFactory {
    @Override
    public void start() {
        stopped = false;
        if (workerPool == null) {
            workerPool = new WorkerService("NIOWorker", numWorkerThreads, false);
        }
        for (SelectorThread thread : selectorThreads) {
            if (thread.getState() == Thread.State.NEW) {
                thread.start();
            }
        }
        // ensure thread is started once and only once
        if (acceptThread.getState() == Thread.State.NEW) {
            acceptThread.start();
        }
        if (expirerThread.getState() == Thread.State.NEW) {
            expirerThread.start();
        }
    }
}
```



### Queue



SelectorThread.acceptedQueue

acceptedQueue是LinkedBlockingQueue类型的, 在selector thread中.其中包含了accept thread接收的客户端连接,由selector thread负责将客户端连接注册到selector上,监听OP_READ和OP_WRITE.

SelectorThread.updateQueue

updateQueue和acceptedQueue一样,也是LinkedBlockingQueue类型的,在selector thread中.但是要说明白该队列的作用,就要对Java NIO的实现非常了解了. _Java NIO使用epoll（Linux中）系统调用,且是水平触发,也即若selector.select()发现socketChannel中有事件发生,比如有数据可读, 只要没有将这些数据从socketChannel读取完毕,下一次selector.select()还是会检测到有事件发生,直至数据被读取完毕. ZooKeeper一直认为selector.select()是性能的瓶颈,为了提高selector.select()的性能,避免上述水平触发模式的缺陷,ZooKeeper在处理IO的过程中, 会让socketChannel不再监听OP_READ和OP_WRITE事件,这样就可以减轻selector.select()的负担. 

此时便出现一个问题,IO处理完毕后,如何让socketChannel再监听OP_READ和OP_WRITE事件? 有的小伙伴可能认为这件事情非常容易,worker thread处理IO结束后,直接调用key.interestOps(OP_READ & OP_WRITE)不就可以了吗? 事情并没有这简单,是因为selector.select()是在selector thread中执行的, 若在 selector.select()的过程中 ,worker thread调用了 key.interestOps(OP_READ & OP_WRITE) , 可能会阻塞selector.select() .
ZooKeeper为了追求性能的极致,设计为由selector thread调用key.interestOps(OP_READ & OP_WRITE), 因此worker thread就需在IO处理完毕后告诉selector thread该socketChannel可以去监听OP_READ和OP_WRITE事件了, updateQueue就是存放那些需要监听OP_READ和OP_WRITE事件



socketChannel.NIOServerCnxn.outgoingBuffers

outgoingBuffers存放待发送给客户端的响应数据. 注:既然key.interestOps(OP_READ & OP_WRITE)会阻塞selector.select(),那么accepted.register(selector, SelectionKey.OP_READ) 也会阻塞selector.select(), 因此接收到的客户端连接注册到selector上也要在selector thread上执行,这也是acceptedQueue存在的理由



### AcceptThread

```java
private class AcceptThread extends AbstractSelectThread {
        private final ServerSocketChannel acceptSocket;
        private final SelectionKey acceptKey;
        private final RateLogger acceptErrorLogger = new RateLogger(LOG);
        private final Collection<SelectorThread> selectorThreads;
        private Iterator<SelectorThread> selectorIterator;
        private volatile boolean reconfiguring = false;
        
        public AcceptThread(ServerSocketChannel ss, InetSocketAddress addr, Set<SelectorThread> selectorThreads) throws IOException {
            super("NIOServerCxnFactory.AcceptThread:" + addr);
            this.acceptSocket = ss;
            this.acceptKey = acceptSocket.register(selector, SelectionKey.OP_ACCEPT);
            this.selectorThreads = Collections.unmodifiableList(new ArrayList<SelectorThread>(selectorThreads));
            selectorIterator = this.selectorThreads.iterator();
        }

        public void run() {
            try {
                while (!stopped && !acceptSocket.socket().isClosed()) {
                    try {
                        select();
                    } catch (RuntimeException e) {
                        LOG.warn("Ignoring unexpected runtime exception", e);
                    } catch (Exception e) {
                        LOG.warn("Ignoring unexpected exception", e);
                    }
                }
            } finally {
                closeSelector();
                // This will wake up the selector threads, and tell the
                // worker thread pool to begin shutdown.
                if (!reconfiguring) {
                    NIOServerCnxnFactory.this.stop();
                }
                LOG.info("accept thread exitted run method");
            }
        }
        }
```



select

```java
private void select() {
    try {
        selector.select();

        Iterator<SelectionKey> selectedKeys = selector.selectedKeys().iterator();
        while (!stopped && selectedKeys.hasNext()) {
            SelectionKey key = selectedKeys.next();
            selectedKeys.remove();

            if (!key.isValid()) {
                continue;
            }
            if (key.isAcceptable()) {
                if (!doAccept()) {
                    // If unable to pull a new connection off the accept
                    // queue, pause accepting to give us time to free
                    // up file descriptors and so the accept thread
                    // doesn't spin in a tight loop.
                    pauseAccept(10);
                }
            } else {
                LOG.warn("Unexpected ops in accept select {}", key.readyOps());
            }
        }
    } catch (IOException e) {
        LOG.warn("Ignoring IOException while selecting", e);
    }
}
```



### SelectorThread

SelectorThread SelectorThread从AcceptThread接收新接收的连接，并负责选择连接之间的I/O准备情况。 这个线程是唯一一个对选择器执行 **非线程安全或潜在阻塞调用的线程** (注册新连接和读写操作)。 将一个连接分配给一个SelectorThread是永久的，并且只有一个SelectorThread会与这个连接交互。 有1-N个SelectorThreads，连接平均分配在SelectorThreads之间。

如果有一个工作线程池，当一个连接有I/O来执行时，SelectorThread通过清除它感兴趣的操作将它从选择中删除，并安排I/O由工作线程处理。

当工作完成时，连接被放置在就绪队列上，以恢复其感兴趣的操作并恢复选择。

如果没有工作线程池，SelectorThread将直接执行I/O操作

```java
public class SelectorThread extends AbstractSelectThread {

    private final int id;
    private final Queue<SocketChannel> acceptedQueue;
    private final Queue<SelectionKey> updateQueue;

    public SelectorThread(int id) throws IOException {
        super("NIOServerCxnFactory.SelectorThread-" + id);
        this.id = id;
        acceptedQueue = new LinkedBlockingQueue<>();
        updateQueue = new LinkedBlockingQueue<>();
    }
}
```

run

```java
public void run() {
    try {
        while (!stopped) {
            try {
                select();
                processAcceptedConnections();
                processInterestOpsUpdateRequests();
            } catch (RuntimeException e) {
                LOG.warn("Ignoring unexpected runtime exception", e);
            } catch (Exception e) {
                LOG.warn("Ignoring unexpected exception", e);
            }
        }

        // Close connections still pending on the selector. Any others
        // with in-flight work, let drain out of the work queue.
        for (SelectionKey key : selector.keys()) {
            NIOServerCnxn cnxn = (NIOServerCnxn) key.attachment();
            if (cnxn.isSelectable()) {
                cnxn.close(ServerCnxn.DisconnectReason.SERVER_SHUTDOWN);
            }
            cleanupSelectionKey(key);
        }
        SocketChannel accepted;
        while ((accepted = acceptedQueue.poll()) != null) {
            fastCloseSock(accepted);
        }
        updateQueue.clear();
    } finally {
        closeSelector();
        // This will wake up the accept thread and the other selector
        // threads, and tell the worker thread pool to begin shutdown.
        NIOServerCnxnFactory.this.stop();
        LOG.info("selector thread exitted run method");
    }
}
```

针对SelectorThread我们一共看3个操作,这3个操作通过while来做无限循环，

在while无限循环中, 线程的主循环在连接上选择()并分派准备好的I/O工作请求，然后注册所有等待的新接受的连接并更新队列上的任何感兴趣的操作。

- **select();** 分派准备好的I/O工作请求
- **processAcceptedConnections();** 处理accept线程新分派的连接, 
  - 将新连接注册到selector上;
  - 包装为NIOServerCnxn后注册到NIOServerCnxnFactory中
- **processInterestOpsUpdateRequests();** 更新updateQueue中连接的监听事件



从acceptedQueue 获取连接注册OP_READ事件到Selector上

```java
private void processAcceptedConnections() {
    SocketChannel accepted;
    while (!stopped && (accepted = acceptedQueue.poll()) != null) {
        SelectionKey key = null;
        try {
            key = accepted.register(selector, SelectionKey.OP_READ);
            NIOServerCnxn cnxn = createConnection(accepted, key, this);
            key.attach(cnxn);
            addCnxn(cnxn);
        } catch (IOException e) {
            // register, createConnection
            cleanupSelectionKey(key);
            fastCloseSock(accepted);
        }
    }
}
```

```java
protected NIOServerCnxn createConnection(SocketChannel sock, SelectionKey sk, SelectorThread selectorThread) throws IOException {
    return new NIOServerCnxn(zkServer, sock, sk, this, selectorThread);
}
```



NIOServerCnxn 构造器

```java
public NIOServerCnxn(ZooKeeperServer zk, SocketChannel sock, SelectionKey sk, NIOServerCnxnFactory factory, SelectorThread selectorThread) throws IOException {
    super(zk);
    this.sock = sock;
    this.sk = sk;
    this.factory = factory;
    this.selectorThread = selectorThread;
    if (this.factory.login != null) {
        this.zooKeeperSaslServer = new ZooKeeperSaslServer(factory.login);
    }
    sock.socket().setTcpNoDelay(true);
    /* set socket linger to false, so that socket close does not block */
    sock.socket().setSoLinger(false, -1);
    sock.socket().setKeepAlive(clientTcpKeepAlive);
    InetAddress addr = ((InetSocketAddress) sock.socket().getRemoteSocketAddress()).getAddress();
    addAuthInfo(new Id("ip", addr.getHostAddress()));
    this.sessionTimeout = factory.sessionlessCnxnTimeout;
}
```



processInterestOpsUpdateRequests()方法： 前面我们说过处理IO事件时候会停止订阅事件，IO处理完毕之后则获取updateQueue中连接的监听事件来订阅interestOps

```java
private void processInterestOpsUpdateRequests() {
    SelectionKey key;
    while (!stopped && (key = updateQueue.poll()) != null) {
        if (!key.isValid()) {
            cleanupSelectionKey(key);
        }
        NIOServerCnxn cnxn = (NIOServerCnxn) key.attachment();
        if (cnxn.isSelectable()) {
            key.interestOps(cnxn.getInterestOps());
        }
    }
}
```



IOWorkRequest处理IO事件发生时机当SocketChannel上有数据可读时,worker thread调用NIOServerCnxn.doIO()进行读操作

粘包拆包问题 处理读事件比较麻烦的问题就是通过TCP发送的报文会出现粘包拆包问题,Zookeeper为了解决此问题,在设计通信协议时将报文分为3个部分:

- 请求头和请求体的长度(4个字节)
- 请求头
- 请求体

注:

1. 请求头和请求体也细分为更小的部分,但在此不做深入研究,只需知道请求的前4个字节是请求头和请求体的长度即可.
2. 将请求头和请求体称之为payload 在报文头增加了4个字节的长度字段,表示整个报文除长度字段之外的长度.服务端可根据该长度将粘包拆包的报文分离或组合为完整的报文.





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
        LOG.warn(
            "Connection request from old client {}; will be dropped if server is in r-o mode",
            cnxn.getRemoteSocketAddress());
    }

    if (!request.getReadOnly() && this instanceof ReadOnlyZooKeeperServer) {
        String msg = "Refusing session request for not-read-only client " + cnxn.getRemoteSocketAddress();
        LOG.info(msg);
        throw new CloseRequestException(msg, ServerCnxn.DisconnectReason.NOT_READ_ONLY_CLIENT);
    }
    if (request.getLastZxidSeen() > zkDb.dataTree.lastProcessedZxid) {
        String msg = "Refusing session(0x"
                     + Long.toHexString(sessionId)
                     + ") request for client "
                     + cnxn.getRemoteSocketAddress()
                     + " as it has seen zxid 0x"
                     + Long.toHexString(request.getLastZxidSeen())
                     + " our last zxid is 0x"
                     + Long.toHexString(getZKDatabase().getDataTreeLastProcessedZxid())
                     + " client must try another server";

        LOG.info(msg);
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
        LOG.debug(
            "Client attempting to establish new session: session = 0x{}, zxid = 0x{}, timeout = {}, address = {}",
            Long.toHexString(id),
            Long.toHexString(request.getLastZxidSeen()),
            request.getTimeOut(),
            cnxn.getRemoteSocketAddress());
    } else {
        validateSession(cnxn, sessionId);
        LOG.debug(
            "Client attempting to renew session: session = 0x{}, zxid = 0x{}, timeout = {}, address = {}",
            Long.toHexString(sessionId),
            Long.toHexString(request.getLastZxidSeen()),
            request.getTimeOut(),
            cnxn.getRemoteSocketAddress());
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
        LOG.warn("CancelledKeyException causing close of session: 0x{}", Long.toHexString(sessionId));

        LOG.debug("CancelledKeyException stack trace", e);

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

- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)







## References

1. [Reactor网络IO - Thinking In Code](https://www.ktyhub.com/zh/chapter_zookeeper/14-reactor-io/)



