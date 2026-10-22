## Introduction

本页是 ZooKeeper 服务端 **NIO 网络层**的源码深潜。ZooKeeper 的客户端连接（默认 2181）由 `NIOServerCnxnFactory` 处理：它基于 Java NIO（`Selector`）实现单线程 Selector 模型，是 3.x 默认的连接实现（另一种是 Netty 版，见 [IO](/docs/CS/Framework/ZooKeeper/IO.md)）。

在 `QuorumPeerMain::runFromConfig` 启动中，会初始化通信层并设置到 `QuorumPeer`——`createFactory()` 依据系统属性 `zookeeper.serverCnxnFactory` 决定实例化 `NIOServerCnxnFactory` 还是 Netty 版（默认 NIO）。

### 页内导航

NIO 网络层按连接生命周期串联五个专题：

1. **[configure](#configure)** —— `NIOServerCnxnFactory.configure()`：创建 `Selector`、绑定监听 `ServerSocketChannel`、注册 `OP_ACCEPT`，并启动各线程。
2. **[Queue](#queue)** —— 队列语义：出站请求队列 `outgoingQueue`、待处理队列，以及 `NIOServerCnxn` 的直接内存缓冲（`incomingBuffer`/`lenBuffer`）如何解决粘包拆包。
3. **[AcceptThread](#acceptthread)** —— 接受连接线程：`accept()` 新连接、分配 `NIOServerCnxn`、注册读写事件、把连接加入 selector。
4. **[SelectorThread](#selectorthread)** —— **IO 多路复用核心**：单个线程 `select()` 就绪事件，分派给 `NIOServerCnxn.doIO()`；维护 `selectorQueue` 延迟注册队列（避免在 select 期间改注册集）。
5. **[doIO](#doio)** —— 读事件：拆包、调用 `processPacket` 解析请求（如 `ConnectRequest`）；写事件：把 `outgoingBuffers` 的待写数据批量刷到 socket（处理写事件与 `FinalRequestProcessor` 通过队列通信）。

> [!TIP]
> 关键设计：Selector 线程是单线程串行处理所有连接的 IO 事件，**同一连接的事件按请求顺序处理**，保证了客户端请求的 FIFO 顺序（见 [pipeline](/docs/CS/Framework/ZooKeeper/pipeline.md) 的请求处理链）。与 Netty 实现的对比见 [IO](/docs/CS/Framework/ZooKeeper/IO.md) 的 Comparison 一节。

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

start workerPool, selectorThreads、acceptThread and expirerThread


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


```java
private boolean doAccept() {
            boolean accepted = false;
            SocketChannel sc = null;
            try {
                sc = acceptSocket.accept();
                accepted = true;
                if (limitTotalNumberOfCnxns()) {
                    throw new IOException("Too many connections max allowed is " + maxCnxns);
                }
                InetAddress ia = sc.socket().getInetAddress();
                int cnxncount = getClientCnxnCount(ia);

                if (maxClientCnxns > 0 && cnxncount >= maxClientCnxns) {
                    throw new IOException("Too many connections from " + ia + " - max is " + maxClientCnxns);
                }

                sc.configureBlocking(false);

                // Round-robin assign this connection to a selector thread
                if (!selectorIterator.hasNext()) {
                    selectorIterator = selectorThreads.iterator();
                }
                SelectorThread selectorThread = selectorIterator.next();
                if (!selectorThread.addAcceptedConnection(sc)) {
                    throw new IOException("Unable to add connection to selector queue"
                                          + (stopped ? " (shutdown in progress)" : ""));
                }
                acceptErrorLogger.flush();
            } catch (IOException e) {
                // accept, maxClientCnxns, configureBlocking
                ServerMetrics.getMetrics().CONNECTION_REJECTED.add(1);
                acceptErrorLogger.rateLimitLog("Error accepting new connection: " + e.getMessage());
                fastCloseSock(sc);
            }
            return accepted;
        }
```


```java
   /**
         * Mask off the listen socket interest ops and use select() to sleep
         * so that other threads can wake us up by calling wakeup() on the
         * selector.
         */
        private void pauseAccept(long millisecs) {
            acceptKey.interestOps(0);
            try {
                selector.select(millisecs);
            } catch (IOException e) {
                // ignore
            } finally {
                acceptKey.interestOps(SelectionKey.OP_ACCEPT);
            }
        }

```


### SelectorThread

SelectorThread SelectorThread从AcceptThread接收新接收的连接，并负责选择连接之间的I/O准备情况。 这个线程是唯一一个对选择器执行 **非线程安全或潜在阻塞调用的线程** (注册新连接和读写操作)。 
将一个连接分配给一个SelectorThread是永久的，并且只有一个SelectorThread会与这个连接交互。
有1-N个SelectorThreads，连接平均分配在SelectorThreads之间。

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
ZooKeeper为了追求性能的极致,设计为由selector thread调用key.interestOps(OP_READ & OP_WRITE), 因此worker thread就需在IO处理完毕后告诉selector thread该socketChannel可以去监听OP_READ和OP_WRITE事件了, updateQueue就是存放那些需要监听OP_READ和OP_WRITE事件的


IOWorkRequest处理IO事件发生时机当SocketChannel上有数据可读时,worker thread调用NIOServerCnxn.doIO()进行读操作

粘包拆包问题 处理读事件比较麻烦的问题就是通过TCP发送的报文会出现粘包拆包问题,Zookeeper为了解决此问题,在设计通信协议时将报文分为3个部分:

- 请求头和请求体的长度(4个字节)
- 请求头
- 请求体

注:

1. 请求头和请求体也细分为更小的部分,但在此不做深入研究,只需知道请求的前4个字节是请求头和请求体的长度即可.
2. 将请求头和请求体称之为payload 在报文头增加了4个字节的长度字段,表示整个报文除长度字段之外的长度.服务端可根据该长度将粘包拆包的报文分离或组合为完整的报文.



```java
public class SelectorThread extends AbstractSelectThread {

    private void select() {
        try {
            selector.select();

            Set<SelectionKey> selected = selector.selectedKeys();
            ArrayList<SelectionKey> selectedList = new ArrayList<>(selected);
            Collections.shuffle(selectedList);
            Iterator<SelectionKey> selectedKeys = selectedList.iterator();
            while (!stopped && selectedKeys.hasNext()) {
                SelectionKey key = selectedKeys.next();
                selected.remove(key);

                if (!key.isValid()) {
                    cleanupSelectionKey(key);
                    continue;
                }
                if (key.isReadable() || key.isWritable()) {
                    handleIO(key);
                } else {
                    LOG.warn("Unexpected ops in select {}", key.readyOps());
                }
            }
        } catch (IOException e) {
            LOG.warn("Ignoring IOException while selecting", e);
        }
    }

    private void handleIO(SelectionKey key) {
        IOWorkRequest workRequest = new IOWorkRequest(this, key);
        NIOServerCnxn cnxn = (NIOServerCnxn) key.attachment();

        // Stop selecting this key while processing on its
        // connection
        cnxn.disableSelectable();
        key.interestOps(0);
        touchCnxn(cnxn);
        workerPool.schedule(workRequest);
    }
}
```

```java
public class WorkerService {
    public void schedule(WorkRequest workRequest, long id) {
        if (stopped) {
            workRequest.cleanup();
            return;
        }

        ScheduledWorkRequest scheduledWorkRequest = new ScheduledWorkRequest(workRequest);

        // If we have a worker thread pool, use that; otherwise, do the work
        // directly.
        int size = workers.size();
        if (size > 0) {
            try {
                // make sure to map negative ids as well to [0, size-1]
                int workerNum = ((int) (id % size) + size) % size;
                ExecutorService worker = workers.get(workerNum);
                worker.execute(scheduledWorkRequest);
            } catch (RejectedExecutionException e) {
                LOG.warn("ExecutorService rejected execution", e);
                workRequest.cleanup();
            }
        } else {
            // When there is no worker thread pool, do the work directly
            // and wait for its completion
            scheduledWorkRequest.run();
        }
    }
}
```
```java
private class ScheduledWorkRequest implements Runnable {
    private final WorkRequest workRequest;

    @Override
    public void run() {
        try {
            // Check if stopped while request was on queue
            if (stopped) {
                workRequest.cleanup();
                return;
            }
            workRequest.doWork();
        } catch (Exception e) {
            LOG.warn("Unexpected exception", e);
            workRequest.cleanup();
        }
    }
}
```

```java
 private class IOWorkRequest extends WorkerService.WorkRequest {
    public void doWork() throws InterruptedException {
        if (!key.isValid()) {
            selectorThread.cleanupSelectionKey(key);
            return;
        }

        if (key.isReadable() || key.isWritable()) {
            cnxn.doIO(key);

            // Check if we shutdown or doIO() closed this connection
            if (stopped) {
                cnxn.close(ServerCnxn.DisconnectReason.SERVER_SHUTDOWN);
                return;
            }
            if (!key.isValid()) {
                selectorThread.cleanupSelectionKey(key);
                return;
            }
            touchCnxn(cnxn);
        }

        // Mark this connection as once again ready for selection
        cnxn.enableSelectable();
        // Push an update request on the queue to resume selecting
        // on the current set of interest ops, which may have changed
        // as a result of the I/O operations we just performed.
        if (!selectorThread.addInterestOpsUpdateRequest(key)) {
            cnxn.close(ServerCnxn.DisconnectReason.CONNECTION_MODE_CHANGED);
        }
    }
}
```

```java
public class NIOServerCnxn extends ServerCnxn {
    void doIO(SelectionKey k) throws InterruptedException {
        try {
            if (k.isReadable()) {
                int rc = sock.read(incomingBuffer);
                if (rc < 0) {
                    try {
                        handleFailedRead();
                    } catch (EndOfStreamException e) {
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
        } catch (Throwable e) {
            close(DisconnectReason.IO_EXCEPTION);
        }
    }

    private void readPayload() throws IOException, InterruptedException, ClientCnxnLimitException {
        if (incomingBuffer.remaining() != 0) { // have we read length bytes?
            int rc = sock.read(incomingBuffer); // sock is non-blocking, so ok
            if (rc < 0) {
                handleFailedRead();
            }
        }

        if (incomingBuffer.remaining() == 0) { // have we read length bytes?
            incomingBuffer.flip();
            packetReceived(4 + incomingBuffer.remaining());
            if (!initialized) {
                readConnectRequest();
            } else {
                readRequest();
            }
            lenBuffer.clear();
            incomingBuffer = lenBuffer;
        }
    }

    private void readConnectRequest() throws IOException, ClientCnxnLimitException {
        if (!isZKServerRunning()) {
            throw new IOException("ZooKeeperServer not running");
        }
        BinaryInputArchive bia = BinaryInputArchive.getArchive(new ByteBufferInputStream(incomingBuffer));
        ConnectRequest request = protocolManager.deserializeConnectRequest(bia);
        zkServer.processConnectRequest(this, request);
        initialized = true;
    }

    protected void readRequest() throws IOException {
        RequestHeader h = new RequestHeader();
        ByteBufferInputStream.byteBuffer2Record(incomingBuffer, h);
        RequestRecord request = RequestRecord.fromBytes(incomingBuffer.slice());
        zkServer.processPacket(this, h, request);
    }
}
```

readRequest -> processPacket -> submitRequest -> enqueueRequest
```java

public class RequestThrottler extends ZooKeeperCriticalThread {
  private final LinkedBlockingQueue<Request> submittedRequests = new LinkedBlockingQueue<>();

  @Override
  public void run() {
    try {
      while (true) {
        if (killed) {
          break;
        }

        Request request = submittedRequests.take();
        // Throttling is disabled when maxRequests = 0
        if (maxRequests > 0) {
          while (!killed) {
            if (dropStaleRequests && request.isStale()) {
              // Note: this will close the connection
              dropRequest(request);
              request = null;
              break;
            }
            if (zks.getInProcess() < maxRequests) {
              break;
            }
            throttleSleep(stallTime);
          }
        }

        if (killed) {
          break;
        }

        // A dropped stale request will be null
        if (request != null) {
          if (request.isStale()) {
            ServerMetrics.getMetrics().STALE_REQUESTS.add(1);
          }
          final long elapsedTime = Time.currentElapsedTime() - request.requestThrottleQueueTime;
          ServerMetrics.getMetrics().REQUEST_THROTTLE_QUEUE_TIME.add(elapsedTime);
          if (shouldThrottleOp(request, elapsedTime)) {
            request.setIsThrottled(true);
          }
          zks.submitRequestNow(request);
        }
      }
    } catch (InterruptedException e) {
      LOG.error("Unexpected interruption", e);
    }
    int dropped = drainQueue();
    LOG.info("RequestThrottler shutdown. Dropped {} requests", dropped);
  }
}
```
调用processor chain处理
```java
public class ZooKeeperServer implements SessionExpirer, ServerStats.Provider {
    public void submitRequestNow(Request si) {
        if (firstProcessor == null) {
            synchronized (this) {
                try {
                    // Since all requests are passed to the request
                    // processor it should wait for setting up the request
                    // processor chain. The state will be updated to RUNNING
                    // after the setup.
                    while (state == State.INITIAL) {
                        wait(1000);
                    }
                } catch (InterruptedException e) {
                    LOG.warn("Unexpected interruption", e);
                }
                if (firstProcessor == null || state != State.RUNNING) {
                    throw new RuntimeException("Not started");
                }
            }
        }
        try {
            touch(si.cnxn);
            boolean validpacket = Request.isValid(si.type);
            if (validpacket) {
                setLocalSessionFlag(si);
                firstProcessor.processRequest(si);
                if (si.cnxn != null) {
                    incInProcess();
                }
            } else {
                requestFinished(si);
                new UnimplementedRequestProcessor().processRequest(si);
            }
        } catch (MissingSessionException e) {
            requestFinished(si);
        } catch (RequestProcessorException e) {
            requestFinished(si);
        }
    }
}
```

## Links

- [IO（Netty 实现与 NIO/Netty 对比）](/docs/CS/Framework/ZooKeeper/IO.md)
- [ZooKeeper（概念枢纽）](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)
- [请求处理链 pipeline](/docs/CS/Framework/ZooKeeper/pipeline.md)
- [Session（连接与会话）](/docs/CS/Framework/ZooKeeper/Session.md)
- [Election（Quorum 端口 3888 选主通信）](/docs/CS/Framework/ZooKeeper/Election.md)
- [客户端 client](/docs/CS/Framework/ZooKeeper/client.md)

## References

1. [ZooKeeper Programmer's Guide](https://zookeeper.apache.org/doc/current/zookeeperProgrammers.html)
2. [Netty 官方文档](https://netty.io/)
