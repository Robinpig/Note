## Introduction

## ProtocolHandler

Create a new ProtocolHandler for the given protocol.

```
// Connector
// Defaults to using HTTP/1.1 NIO implementation.
public Connector() {
  this("HTTP/1.1");
}

public Connector(String protocol) {
  p = ProtocolHandler.create(protocol);
}
```



Combine IO and protocol

- org.apache.coyote.http11.Http11NioProtocol
- org.apache.coyote.http11.Http11Nio2Protocol
- org.apache.coyote.ajp.AjpNioProtocol
- org.apache.coyote.ajp.AjpNio2Protocol

```java
// ProtocolHandler
public static ProtocolHandler create(String protocol)
        throws ClassNotFoundException, InstantiationException, IllegalAccessException,
        IllegalArgumentException, InvocationTargetException, NoSuchMethodException, SecurityException {
    if (protocol == null || "HTTP/1.1".equals(protocol)
            || org.apache.coyote.http11.Http11NioProtocol.class.getName().equals(protocol)) {
        return new org.apache.coyote.http11.Http11NioProtocol();
    } else if ("AJP/1.3".equals(protocol)
            || org.apache.coyote.ajp.AjpNioProtocol.class.getName().equals(protocol)) {
        return new org.apache.coyote.ajp.AjpNioProtocol();
    } else {
        // Instantiate protocol handler
        Class<?> clazz = Class.forName(protocol);
        return (ProtocolHandler) clazz.getConstructor().newInstance();
    }
}
```

default use HTTP1.1 NioEndpoint

```java
// Http11NioProtocol
public Http11NioProtocol() {
    super(new NioEndpoint());
}
```


### NioEndPoint

NIO tailored thread pool, providing the following services:

1. Socket acceptor thread, default 1, accept new Channel then turn to Poller
2. Socket poller thread, default 1, use Selector, get Ready Channel from Channel array，wrap a SocketProcessor to Executor
3. Worker threads pool call SocketProcessor.run(), default 10
4. LimitLatch maxConnection = 10000

Start the NIO endpoint, creating acceptor, poller threads and [executor](/docs/CS/Java/Tomcat/threads.md?id=ThreadPoolExecutor).

```java
public class NioEndpoint extends AbstractJsseEndpoint<NioChannel,SocketChannel> {
    @Override
    public void startInternal() throws Exception {

        if (!running) {
            running = true;
            paused = false;

            if (socketProperties.getProcessorCache() != 0) {
                processorCache = new SynchronizedStack<>(SynchronizedStack.DEFAULT_SIZE,
                        socketProperties.getProcessorCache());
            }
            if (socketProperties.getEventCache() != 0) {
                eventCache = new SynchronizedStack<>(SynchronizedStack.DEFAULT_SIZE,
                        socketProperties.getEventCache());
            }
            if (socketProperties.getBufferPool() != 0) {
                nioChannels = new SynchronizedStack<>(SynchronizedStack.DEFAULT_SIZE,
                        socketProperties.getBufferPool());
            }

            // Create worker collection
            if (getExecutor() == null) {
                createExecutor();
            }

            initializeConnectionLatch();

            // Start poller thread
            poller = new Poller();
            Thread pollerThread = new Thread(poller, getName() + "-ClientPoller");
            pollerThread.setPriority(threadPriority);
            pollerThread.setDaemon(true);
            pollerThread.start();

            startAcceptorThread();
        }
    }

    protected void startAcceptorThread() {
        acceptor = new Acceptor<>(this); // set endpoint
        String threadName = getName() + "-Acceptor";
        acceptor.setThreadName(threadName);
        Thread t = new Thread(acceptor, threadName);
        t.setPriority(getAcceptorThreadPriority());
        t.setDaemon(getDaemon());
        t.start();
    }
}
```

##### bind

```java
public class NioEndpoint extends AbstractJsseEndpoint<NioChannel,SocketChannel> {
    public void bind() throws Exception {
        this.initServerSocket();
        this.setStopLatch(new CountDownLatch(1));
        this.initialiseSsl();
        this.selectorPool.open(this.getName());
    }

    protected void initServerSocket() throws Exception {
        if (!this.getUseInheritedChannel()) {
            this.serverSock = ServerSocketChannel.open();
            this.socketProperties.setProperties(this.serverSock.socket());
            InetSocketAddress addr = new InetSocketAddress(this.getAddress(), this.getPortWithOffset());
            this.serverSock.socket().bind(addr, this.getAcceptCount());
        } else {
            Channel ic = System.inheritedChannel();
            if (ic instanceof ServerSocketChannel) {
                this.serverSock = (ServerSocketChannel) ic;
            }

            if (this.serverSock == null) {
                throw new IllegalArgumentException(sm.getString("endpoint.init.bind.inherited"));
            }
        }

        this.serverSock.configureBlocking(true);
    }
}
```

#### LimitLatch

LimitLatch like [CountDownLatch](/docs/CS/Java/JDK/Concurrency/CountDownLatch.md) extends [AQS](/docs/CS/Java/JDK/Concurrency/AQS.md)

```java
public abstract class AbstractEndpoint<S,U> {
  
    public void setMaxConnections(int maxCon) {
        this.maxConnections = maxCon;
        LimitLatch latch = this.connectionLimitLatch;
        if (latch != null) {
            // Update the latch that enforces this
            if (maxCon == -1) {
                releaseConnectionLatch();
            } else {
                latch.setLimit(maxCon);
            }
        } else if (maxCon > 0) {
            initializeConnectionLatch();
        }
    }
  
    protected LimitLatch initializeConnectionLatch() {
        if (maxConnections == -1) {
            return null;
        }
        if (connectionLimitLatch == null) {
            connectionLimitLatch = new LimitLatch(getMaxConnections());
        }
        return connectionLimitLatch;
    }
}
```

Shared latch that allows the latch to be acquired a limited number of times after which all subsequent requests to acquire the latch will be placed in a FIFO queue until one of the shares is returned.

```java
public class LimitLatch {

    public LimitLatch(long limit) {
        this.limit = limit;
        this.count = new AtomicLong(0);
        this.sync = new Sync();
    }
}
```

Sync extends AQS

countUpOrAwait

```java
protected void countUpOrAwaitConnection() throws InterruptedException {
    if (maxConnections==-1) {
        return;
    }
    LimitLatch latch = connectionLimitLatch;
    if (latch!=null) {
        latch.countUpOrAwait();
    }
}

public void countUpOrAwait() throws InterruptedException {
    sync.acquireSharedInterruptibly(1);
}


@Override
protected int tryAcquireShared(int ignored) {
    long newCount = count.incrementAndGet();
    if (!released && newCount > limit) {
        // Limit exceeded
        count.decrementAndGet();
        return -1;
    } else {
        return 1;
    }
}
```

##### countDownConnection

```java
protected long countDownConnection() {
        if (maxConnections==-1) {
            return -1;
        }
        LimitLatch latch = connectionLimitLatch;
        if (latch!=null) {
            return latch.countDown();
        } else {
            return -1;
        }
    }


public long countDown() {
    sync.releaseShared(0);
    return getCount();
}

@Override
protected boolean tryReleaseShared(int arg) {
    count.decrementAndGet();
    return true;
}
```

### Acceptor

call in Endpoint

- if we have reached max connections, wait
- Accept the next incoming connection from the server socket
- [setSocketOptions()](/docs/CS/Java/Tomcat/Connector.md?id=setSocketOptions) will hand the socket off to an appropriate processor if successful

```java
package org.apache.tomcat.util.net;

public class Acceptor<U> implements Runnable {
    @Override
    public void run() {

        int errorDelay = 0;

        try {
            // Loop until we receive a shutdown command
            while (!stopCalled) {

                // Loop if endpoint is paused
                while (endpoint.isPaused() && !stopCalled) {
                    state = AcceptorState.PAUSED;
                    try {
                        Thread.sleep(50);
                    } catch (InterruptedException e) {
                        // Ignore
                    }
                }

                if (stopCalled) {
                    break;
                }
                state = AcceptorState.RUNNING;

                try {
                    //if we have reached max connections, wait
                    endpoint.countUpOrAwaitConnection();

                    // Endpoint might have been paused while waiting for latch
                    // If that is the case, don't accept new connections
                    if (endpoint.isPaused()) {
                        continue;
                    }

                    U socket = null;
                    try {
                        // Accept the next incoming connection from the server
                        // socket
                        socket = endpoint.serverSocketAccept();
                    } catch (Exception ioe) {
                        // We didn't get a socket
                        endpoint.countDownConnection();
                        if (endpoint.isRunning()) {
                            // Introduce delay if necessary
                            errorDelay = handleExceptionWithDelay(errorDelay);
                            // re-throw
                            throw ioe;
                        } else {
                            break;
                        }
                    }
                    // Successful accept, reset the error delay
                    errorDelay = 0;

                    // Configure the socket
                    if (!stopCalled && !endpoint.isPaused()) {
                        // setSocketOptions() will hand the socket off to
                        // an appropriate processor if successful
                        if (!endpoint.setSocketOptions(socket)) {
                            endpoint.closeSocket(socket);
                        }
                    } else {
                        endpoint.destroySocket(socket);
                    }
                } catch (Throwable t) {
                    ExceptionUtils.handleThrowable(t);
                    String msg = sm.getString("endpoint.accept.fail");
                    // APR specific.
                    // Could push this down but not sure it is worth the trouble.
                    if (t instanceof Error) {
                        Error e = (Error) t;
                        if (e.getError() == 233) {
                            // Not an error on HP-UX so log as a warning
                            // so it can be filtered out on that platform
                            // See bug 50273
                        }
                    }
                }
            }
        } finally {
            stopLatch.countDown();
        }
        state = AcceptorState.ENDED;
    }
}
```

### setSocketOptions

Process the specified connection.

call [register](/docs/CS/Java/Tomcat/Connector.md?id=register)

```java
// NioEndpoint
@Override
protected boolean setSocketOptions(SocketChannel socket) {
    NioSocketWrapper socketWrapper = null;
    try {
        // Allocate channel and wrapper
        NioChannel channel = null;
        if (nioChannels != null) {
            channel = nioChannels.pop();
        }
        if (channel == null) {
            SocketBufferHandler bufhandler = new SocketBufferHandler(
                    socketProperties.getAppReadBufSize(),
                    socketProperties.getAppWriteBufSize(),
                    socketProperties.getDirectBuffer());
            if (isSSLEnabled()) {
                channel = new SecureNioChannel(bufhandler, this);
            } else {
                channel = new NioChannel(bufhandler);
            }
        }
        NioSocketWrapper newWrapper = new NioSocketWrapper(channel, this);
        channel.reset(socket, newWrapper);
        connections.put(socket, newWrapper);
        socketWrapper = newWrapper;

        // Set socket properties
        // Disable blocking, polling will be used
        socket.configureBlocking(false);
        if (getUnixDomainSocketPath() == null) {
            socketProperties.setProperties(socket.socket());
        }

        socketWrapper.setReadTimeout(getConnectionTimeout());
        socketWrapper.setWriteTimeout(getConnectionTimeout());
        socketWrapper.setKeepAliveLeft(NioEndpoint.this.getMaxKeepAliveRequests());
        poller.register(socketWrapper);
        return true;
    } catch (Throwable t) {
        ExceptionUtils.handleThrowable(t);
        try {
            log.error(sm.getString("endpoint.socketOptionsError"), t);
        } catch (Throwable tt) {
            ExceptionUtils.handleThrowable(tt);
        }
        if (socketWrapper == null) {
            destroySocket(socket);
        }
    }
    // Tell to close the socket if needed
    return false;
}
```

### register

Registers a newly created socket with the poller.

events is a SynchronizedQueue

```java
public class NioEndpoint extends AbstractJsseEndpoint<NioChannel,SocketChannel> {

    private final SynchronizedQueue<PollerEvent> events =
            new SynchronizedQueue<>();
  
    public void register(final NioSocketWrapper socketWrapper) {
        socketWrapper.interestOps(SelectionKey.OP_READ);//this is what OP_REGISTER turns into.
        PollerEvent event = null;
        if (eventCache != null) {
            event = eventCache.pop();
        }
        if (event == null) {
            event = new PollerEvent(socketWrapper, OP_REGISTER);
        } else {
            event.reset(socketWrapper, OP_REGISTER);
        }
        addEvent(event);
    }

    private void addEvent(PollerEvent event) {
        events.offer(event);
        if (wakeupCounter.incrementAndGet() == 0) {
            selector.wakeup();
        }
    }
}
```

### SynchronizedQueue

This is intended as a (mostly) GC-free alternative to [java.util.concurrent.ConcurrentLinkedQueue](/docs/CS/Java/JDK/Collection/Queue.md?id=ConcurrentLinkedQueue)
when the requirement is to create an unbounded queue with no requirement to shrink the queue.
The aim is to provide the bare minimum of required functionality as quickly as possible with minimum garbage.

```java
public class SynchronizedQueue<T> {

    public static final int DEFAULT_SIZE = 128;

    private Object[] queue;
    private int size;
    private int insert = 0;
    private int remove = 0;

    public SynchronizedQueue() {
        this(DEFAULT_SIZE);
    }

    public SynchronizedQueue(int initialSize) {
        queue = new Object[initialSize];
        size = initialSize;
    }

    public synchronized boolean offer(T t) {
        queue[insert++] = t;

        // Wrap
        if (insert == size) {
            insert = 0;
        }

        if (insert == remove) {
            expand();
        }
        return true;
    }

    public synchronized T poll() {
        if (insert == remove) {
            // empty
            return null;
        }

        @SuppressWarnings("unchecked")
        T result = (T) queue[remove];
        queue[remove] = null;
        remove++;

        // Wrap
        if (remove == size) {
            remove = 0;
        }

        return result;
    }

    private void expand() {
        int newSize = size * 2;
        Object[] newQueue = new Object[newSize];

        System.arraycopy(queue, insert, newQueue, 0, size - insert);
        System.arraycopy(queue, 0, newQueue, size - insert, insert);

        insert = size;
        remove = 0;
        queue = newQueue;
        size = newSize;
    }

    public synchronized int size() {
        int result = insert - remove;
        if (result < 0) {
            result += size;
        }
        return result;
    }

    public synchronized void clear() {
        queue = new Object[size];
        insert = 0;
        remove = 0;
    }
}
```

## Poller

call in NioEndpoint

```java
public class Poller implements Runnable {

    private Selector selector;
    private final SynchronizedQueue<PollerEvent> events =
            new SynchronizedQueue<>();

    private volatile boolean close = false;
    // Optimize expiration handling
    private long nextExpiration = 0;

    private AtomicLong wakeupCounter = new AtomicLong(0);

    private volatile int keyCount = 0;

    public Poller() throws IOException {
        this.selector = Selector.open();
    }
}
```

### run

The background thread that adds sockets to the Poller,
checks the poller for triggered events and hands the associated socket off to an appropriate [processor](/docs/CS/Java/Tomcat/Connector.md?id=SocketProcessor) as events occur.

```java
public class Poller implements Runnable {
    @Override
    public void run() {
        // Loop until destroy() is called
        while (true) {

            boolean hasEvents = false;

            try {
                if (!close) {
                    hasEvents = events();
                    if (wakeupCounter.getAndSet(-1) > 0) {
                        // If we are here, means we have other stuff to do
                        // Do a non blocking select
                        keyCount = selector.selectNow();
                    } else {
                        keyCount = selector.select(selectorTimeout);
                    }
                    wakeupCounter.set(0);
                }
                if (close) {
                    events();
                    timeout(0, false);
                    try {
                        selector.close();
                    } catch (IOException ioe) {
                        log.error(sm.getString("endpoint.nio.selectorCloseFail"), ioe);
                    }
                    break;
                }
                // Either we timed out or we woke up, process events first
                if (keyCount == 0) {
                    hasEvents = (hasEvents | events());
                }
            } catch (Throwable x) {
                ExceptionUtils.handleThrowable(x);
                log.error(sm.getString("endpoint.nio.selectorLoopError"), x);
                continue;
            }

            Iterator<SelectionKey> iterator =
                    keyCount > 0 ? selector.selectedKeys().iterator() : null;
            // Walk through the collection of ready keys and dispatch
            // any active event.
            while (iterator != null && iterator.hasNext()) {
                SelectionKey sk = iterator.next();
                iterator.remove();
                NioSocketWrapper socketWrapper = (NioSocketWrapper) sk.attachment();
                // Attachment may be null if another thread has called
                // cancelledKey()
                if (socketWrapper != null) {
                    processKey(sk, socketWrapper);
                }
            }

            // Process timeouts
            timeout(keyCount, hasEvents);
        }

        getStopLatch().countDown();
    }
}
```

#### events

Processes events in the event queue of the Poller.

```java
public boolean events() {
    boolean result = false;

    PollerEvent pe = null;
    for (int i = 0, size = events.size(); i < size && (pe = events.poll()) != null; i++ ) {
        result = true;
        NioSocketWrapper socketWrapper = pe.getSocketWrapper();
        SocketChannel sc = socketWrapper.getSocket().getIOChannel();
        int interestOps = pe.getInterestOps();
        if (sc == null) {
            log.warn(sm.getString("endpoint.nio.nullSocketChannel"));
            socketWrapper.close();
        } else if (interestOps == OP_REGISTER) {
            try {
                sc.register(getSelector(), SelectionKey.OP_READ, socketWrapper);
            } catch (Exception x) {
                log.error(sm.getString("endpoint.nio.registerFail"), x);
            }
        } else {
            final SelectionKey key = sc.keyFor(getSelector());
            if (key == null) {
                // The key was cancelled (e.g. due to socket closure)
                // and removed from the selector while it was being
                // processed. Count down the connections at this point
                // since it won't have been counted down when the socket
                // closed.
                socketWrapper.close();
            } else {
                final NioSocketWrapper attachment = (NioSocketWrapper) key.attachment();
                if (attachment != null) {
                    // We are registering the key to start with, reset the fairness counter.
                    try {
                        int ops = key.interestOps() | interestOps;
                        attachment.interestOps(ops);
                        key.interestOps(ops);
                    } catch (CancelledKeyException ckx) {
                        cancelledKey(key, socketWrapper);
                    }
                } else {
                    cancelledKey(key, socketWrapper);
                }
            }
        }
        if (running && !paused && eventCache != null) {
            pe.reset();
            eventCache.push(pe);
        }
    }

    return result;
}
```

#### processKey

```java
// Poller
protected void processKey(SelectionKey sk, NioSocketWrapper socketWrapper) {
    try {
        if (close) {
            cancelledKey(sk, socketWrapper);
        } else if (sk.isValid()) {
            if (sk.isReadable() || sk.isWritable()) {
                if (socketWrapper.getSendfileData() != null) {
                    processSendfile(sk, socketWrapper, false);
                } else {
                    unreg(sk, socketWrapper, sk.readyOps());
                    boolean closeSocket = false;
                    // Read goes before write
                    if (sk.isReadable()) {
                        if (socketWrapper.readOperation != null) {
                            if (!socketWrapper.readOperation.process()) {
                                closeSocket = true;
                            }
                        } else if (socketWrapper.readBlocking) {
                            synchronized (socketWrapper.readLock) {
                                socketWrapper.readBlocking = false;
                                socketWrapper.readLock.notify();
                            }
                        } else if (!processSocket(socketWrapper, SocketEvent.OPEN_READ, true)) {
                            closeSocket = true;
                        }
                    }
                    if (!closeSocket && sk.isWritable()) {
                        if (socketWrapper.writeOperation != null) {
                            if (!socketWrapper.writeOperation.process()) {
                                closeSocket = true;
                            }
                        } else if (socketWrapper.writeBlocking) {
                            synchronized (socketWrapper.writeLock) {
                                socketWrapper.writeBlocking = false;
                                socketWrapper.writeLock.notify();
                            }
                        } else if (!processSocket(socketWrapper, SocketEvent.OPEN_WRITE, true)) {
                            closeSocket = true;
                        }
                    }
                    if (closeSocket) {
                        cancelledKey(sk, socketWrapper);
                    }
                }
            }
        } else {
            // Invalid key
            cancelledKey(sk, socketWrapper);
        }
    } catch (CancelledKeyException ckx) {
        cancelledKey(sk, socketWrapper);
    } catch (Throwable t) {
        ExceptionUtils.handleThrowable(t);
        log.error(sm.getString("endpoint.nio.keyProcessingError"), t);
    }
}
```

#### processSocket

Process the given SocketWrapper with the given status.
Used to trigger processing as if the Poller (for those endpoints that have one) selected the socket.

```java
public abstract class AbstractEndpoint<S,U> {
    public boolean processSocket(SocketWrapperBase<S> socketWrapper,
                                 SocketEvent event, boolean dispatch) {
        try {
            if (socketWrapper == null) {
                return false;
            }
            SocketProcessorBase<S> sc = null;
            if (processorCache != null) {
                sc = processorCache.pop();
            }
            if (sc == null) {
```

create SocketProcessor

```java
                sc = createSocketProcessor(socketWrapper, event);
            } else {
                sc.reset(socketWrapper, event);
            }
```

execute SocketProcessor in workers

```java
            Executor executor = getExecutor();
            if (dispatch && executor != null) {
                executor.execute(sc);
            } else {
                sc.run();
            }
        } catch (RejectedExecutionException ree) {
            getLog().warn(sm.getString("endpoint.executor.fail", socketWrapper), ree);
            return false;
        } catch (Throwable t) {
            ExceptionUtils.handleThrowable(t);
            // This means we got an OOM or similar creating a thread, or that
            // the pool and its queue are full
            getLog().error(sm.getString("endpoint.process.fail"), t);
            return false;
        }
        return true;
    }
}
```

#### SocketProcessor

`SocketProcessor` is the equivalent of the Worker, but will simply use in an external Executor thread pool.

```java
protected class SocketProcessor extends SocketProcessorBase<NioChannel> {

    public SocketProcessor(SocketWrapperBase<NioChannel> socketWrapper, SocketEvent event) {
        super(socketWrapper, event);
    }

    @Override
    protected void doRun() {
        /*
         * Do not cache and re-use the value of socketWrapper.getSocket() in
         * this method. If the socket closes the value will be updated to
         * CLOSED_NIO_CHANNEL and the previous value potentially re-used for
         * a new connection. That can result in a stale cached value which
         * in turn can result in unintentionally closing currently active
         * connections.
         */
        Poller poller = NioEndpoint.this.poller;
        if (poller == null) {
            socketWrapper.close();
            return;
        }

        try {
            int handshake = -1;
            try {
                if (socketWrapper.getSocket().isHandshakeComplete()) {
                    // No TLS handshaking required. Let the handler
                    // process this socket / event combination.
                    handshake = 0;
                } else if (event == SocketEvent.STOP || event == SocketEvent.DISCONNECT ||
                        event == SocketEvent.ERROR) {
                    // Unable to complete the TLS handshake. Treat it as
                    // if the handshake failed.
                    handshake = -1;
                } else {
                    handshake = socketWrapper.getSocket().handshake(event == SocketEvent.OPEN_READ, event == SocketEvent.OPEN_WRITE);
                    // The handshake process reads/writes from/to the
                    // socket. status may therefore be OPEN_WRITE once
                    // the handshake completes. However, the handshake
                    // happens when the socket is opened so the status
                    // must always be OPEN_READ after it completes. It
                    // is OK to always set this as it is only used if
                    // the handshake completes.
                    event = SocketEvent.OPEN_READ;
                }
            } catch (IOException | CancelledKeyException ckx) {
                handshake = -1;
            }
            if (handshake == 0) {
                SocketState state = SocketState.OPEN;
```

Process the request from this socket, call `AbstractProtocol.process()` -> [Processor.process()](/docs/CS/Java/Tomcat/Connector.md?id=Processor)

```java
                if (event == null) {
                    state = getHandler().process(socketWrapper, SocketEvent.OPEN_READ);
                } else {
                    state = getHandler().process(socketWrapper, event);
                }
                if (state == SocketState.CLOSED) {
                    poller.cancelledKey(getSelectionKey(), socketWrapper);
                }
            } else if (handshake == -1) {
                getHandler().process(socketWrapper, SocketEvent.CONNECT_FAIL);
                poller.cancelledKey(getSelectionKey(), socketWrapper);
            } else if (handshake == SelectionKey.OP_READ) {
                socketWrapper.registerReadInterest();
            } else if (handshake == SelectionKey.OP_WRITE) {
                socketWrapper.registerWriteInterest();
            }
        } catch (CancelledKeyException cx) {
            poller.cancelledKey(getSelectionKey(), socketWrapper);
        } catch (VirtualMachineError vme) {
            ExceptionUtils.handleThrowable(vme);
        } catch (Throwable t) {
            log.error(sm.getString("endpoint.processing.fail"), t);
            poller.cancelledKey(getSelectionKey(), socketWrapper);
        } finally {
            socketWrapper = null;
            event = null;
            //return to cache
            if (running && !paused && processorCache != null) {
                processorCache.push(this);
            }
        }
    }
}
```

## process

### Processor

Adapters for transform request/response

AbstractProcessorLight is a light-weight abstract processor implementation that is intended as a basis for all Processor implementations from the light-weight upgrade processors to the HTTP/AJP processors.

`AbstractProcessorLight.process()`
-> [Http11Processor.service()](/docs/CS/Java/Tomcat/Connector.md?id=Http11Processor)
-> [CoyoteAdapter.service()](/docs/CS/Java/Tomcat/Connector.md?id=CoyoteAdapter)
-> [StandardWrapperValve.invoke()](/docs/CS/Java/Tomcat/Connector.md?id=invoke)

#### Http11Processor

```java

public class Http11Processor extends AbstractProcessor {
    @Override
    public SocketState service(SocketWrapperBase<?> socketWrapper)
            throws IOException {
        RequestInfo rp = request.getRequestProcessor();
        rp.setStage(org.apache.coyote.Constants.STAGE_PARSE);

        // Setting up the I/O
        setSocketWrapper(socketWrapper);

        // Flags
        keepAlive = true;
        openSocket = false;
        readComplete = true;
        boolean keptAlive = false;
        SendfileState sendfileState = SendfileState.DONE;

        while (!getErrorState().isError() && keepAlive && !isAsync() && upgradeToken == null &&
                sendfileState == SendfileState.DONE && !protocol.isPaused()) {

            // Parsing the request header
            try {
                if (!inputBuffer.parseRequestLine(keptAlive, protocol.getConnectionTimeout(),
                        protocol.getKeepAliveTimeout())) {
                    if (inputBuffer.getParsingRequestLinePhase() == -1) {
                        return SocketState.UPGRADING;
                    } else if (handleIncompleteRequestLineRead()) {
                        break;
                    }
                }

                // Process the Protocol component of the request line
                // Need to know if this is an HTTP 0.9 request before trying to
                // parse headers.
                prepareRequestProtocol();

                if (protocol.isPaused()) {
                    // 503 - Service unavailable
                    response.setStatus(503);
                    setErrorState(ErrorState.CLOSE_CLEAN, null);
                } else {
                    keptAlive = true;
                    // Set this every time in case limit has been changed via JMX
                    request.getMimeHeaders().setLimit(protocol.getMaxHeaderCount());
                    // Don't parse headers for HTTP/0.9
                    if (!http09 && !inputBuffer.parseHeaders()) {
                        // We've read part of the request, don't recycle it
                        // instead associate it with the socket
                        openSocket = true;
                        readComplete = false;
                        break;
                    }
                    if (!protocol.getDisableUploadTimeout()) {
                        socketWrapper.setReadTimeout(protocol.getConnectionUploadTimeout());
                    }
                }
            } catch (IOException e) {
                setErrorState(ErrorState.CLOSE_CONNECTION_NOW, e);
                break;
            } catch (Throwable t) {
                ExceptionUtils.handleThrowable(t);
                UserDataHelper.Mode logMode = userDataHelper.getNextMode();
                if (logMode != null) {
                    String message = sm.getString("http11processor.header.parse");
                    switch (logMode) {
                        case INFO_THEN_DEBUG:
                            message += sm.getString("http11processor.fallToDebug");
                            //$FALL-THROUGH$
                        case INFO:
                            log.info(message, t);
                            break;
                        case DEBUG:
                            log.debug(message, t);
                    }
                }
                // 400 - Bad Request
                response.setStatus(400);
                setErrorState(ErrorState.CLOSE_CLEAN, t);
            }

            // Has an upgrade been requested?
            if (isConnectionToken(request.getMimeHeaders(), "upgrade")) {
                // Check the protocol
                String requestedProtocol = request.getHeader("Upgrade");

                UpgradeProtocol upgradeProtocol = protocol.getUpgradeProtocol(requestedProtocol);
                if (upgradeProtocol != null) {
                    if (upgradeProtocol.accept(request)) {
                        // Create clone of request for upgraded protocol
                        Request upgradeRequest = null;
                        try {
                            upgradeRequest = cloneRequest(request);
                        } catch (ByteChunk.BufferOverflowException ioe) {
                            response.setStatus(HttpServletResponse.SC_REQUEST_ENTITY_TOO_LARGE);
                            setErrorState(ErrorState.CLOSE_CLEAN, null);
                        } catch (IOException ioe) {
                            response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
                            setErrorState(ErrorState.CLOSE_CLEAN, ioe);
                        }

                        if (upgradeRequest != null) {
                            // Complete the HTTP/1.1 upgrade process
                            response.setStatus(HttpServletResponse.SC_SWITCHING_PROTOCOLS);
                            response.setHeader("Connection", "Upgrade");
                            response.setHeader("Upgrade", requestedProtocol);
                            action(ActionCode.CLOSE, null);
                            getAdapter().log(request, response, 0);

                            // Continue processing using new protocol
                            InternalHttpUpgradeHandler upgradeHandler =
                                    upgradeProtocol.getInternalUpgradeHandler(socketWrapper, getAdapter(), upgradeRequest);
                            UpgradeToken upgradeToken = new UpgradeToken(upgradeHandler, null, null, requestedProtocol);
                            action(ActionCode.UPGRADE, upgradeToken);
                            return SocketState.UPGRADING;
                        }
                    }
                }
            }

            if (getErrorState().isIoAllowed()) {
                // Setting up filters, and parse some request headers
                rp.setStage(org.apache.coyote.Constants.STAGE_PREPARE);
                try {
                    prepareRequest();
                } catch (Throwable t) {
                    ExceptionUtils.handleThrowable(t);
                    // 500 - Internal Server Error
                    response.setStatus(500);
                    setErrorState(ErrorState.CLOSE_CLEAN, t);
                }
            }

            int maxKeepAliveRequests = protocol.getMaxKeepAliveRequests();
            if (maxKeepAliveRequests == 1) {
                keepAlive = false;
            } else if (maxKeepAliveRequests > 0 &&
                    socketWrapper.decrementKeepAlive() <= 0) {
                keepAlive = false;
            }
```

Process the request in the [adapter](/docs/CS/Java/Tomcat/Connector.md?id=CoyoteAdapter)

```java
            if (getErrorState().isIoAllowed()) {
                try {
                    rp.setStage(org.apache.coyote.Constants.STAGE_SERVICE);
                    getAdapter().service(request, response);
                    // Handle when the response was committed before a serious
                    // error occurred.  Throwing a ServletException should both
                    // set the status to 500 and set the errorException.
                    // If we fail here, then the response is likely already
                    // committed, so we can't try and set headers.
                    if (keepAlive && !getErrorState().isError() && !isAsync() &&
                            statusDropsConnection(response.getStatus())) {
                        setErrorState(ErrorState.CLOSE_CLEAN, null);
                    }
                } catch (InterruptedIOException e) {
                    setErrorState(ErrorState.CLOSE_CONNECTION_NOW, e);
                } catch (HeadersTooLargeException e) {
                    log.error(sm.getString("http11processor.request.process"), e);
                    // The response should not have been committed but check it
                    // anyway to be safe
                    if (response.isCommitted()) {
                        setErrorState(ErrorState.CLOSE_NOW, e);
                    } else {
                        response.reset();
                        response.setStatus(500);
                        setErrorState(ErrorState.CLOSE_CLEAN, e);
                        response.setHeader("Connection", "close"); // TODO: Remove
                    }
                } catch (Throwable t) {
                    ExceptionUtils.handleThrowable(t);
                    log.error(sm.getString("http11processor.request.process"), t);
                    // 500 - Internal Server Error
                    response.setStatus(500);
                    setErrorState(ErrorState.CLOSE_CLEAN, t);
                    getAdapter().log(request, response, 0);
                }
            }

            // Finish the handling of the request
            rp.setStage(org.apache.coyote.Constants.STAGE_ENDINPUT);
            if (!isAsync()) {
                // If this is an async request then the request ends when it has
                // been completed. The AsyncContext is responsible for calling
                // endRequest() in that case.
                endRequest();
            }
            rp.setStage(org.apache.coyote.Constants.STAGE_ENDOUTPUT);

            // If there was an error, make sure the request is counted as
            // and error, and update the statistics counter
            if (getErrorState().isError()) {
                response.setStatus(500);
            }

            if (!isAsync() || getErrorState().isError()) {
                request.updateCounters();
                if (getErrorState().isIoAllowed()) {
                    inputBuffer.nextRequest();
                    outputBuffer.nextRequest();
                }
            }

            if (!protocol.getDisableUploadTimeout()) {
                int connectionTimeout = protocol.getConnectionTimeout();
                if (connectionTimeout > 0) {
                    socketWrapper.setReadTimeout(connectionTimeout);
                } else {
                    socketWrapper.setReadTimeout(0);
                }
            }

            rp.setStage(org.apache.coyote.Constants.STAGE_KEEPALIVE);

            sendfileState = processSendfile(socketWrapper);
        }

        rp.setStage(org.apache.coyote.Constants.STAGE_ENDED);

        if (getErrorState().isError() || (protocol.isPaused() && !isAsync())) {
            return SocketState.CLOSED;
        } else if (isAsync()) {
            return SocketState.LONG;
        } else if (isUpgrade()) {
            return SocketState.UPGRADING;
        } else {
            if (sendfileState == SendfileState.PENDING) {
                return SocketState.SENDFILE;
            } else {
                if (openSocket) {
                    if (readComplete) {
                        return SocketState.OPEN;
                    } else {
                        return SocketState.LONG;
                    }
                } else {
                    return SocketState.CLOSED;
                }
            }
        }
    }
}
```

#### CoyoteAdapter

get Valve by getPipeline().getFirst(), then Value.invoke()

```java
public class CoyoteAdapter implements Adapter {
    @Override
    public void service(org.apache.coyote.Request req, org.apache.coyote.Response res)
            throws Exception {

        Request request = (Request) req.getNote(ADAPTER_NOTES);
        Response response = (Response) res.getNote(ADAPTER_NOTES);

        if (request == null) {
            // Create objects
            request = connector.createRequest();
            request.setCoyoteRequest(req);
            response = connector.createResponse();
            response.setCoyoteResponse(res);

            // Link objects
            request.setResponse(response);
            response.setRequest(request);

            // Set as notes
            req.setNote(ADAPTER_NOTES, request);
            res.setNote(ADAPTER_NOTES, response);

            // Set query string encoding
            req.getParameters().setQueryStringCharset(connector.getURICharset());
        }

        if (connector.getXpoweredBy()) {
            response.addHeader("X-Powered-By", POWERED_BY);
        }

        boolean async = false;
        boolean postParseSuccess = false;

        req.getRequestProcessor().setWorkerThreadName(THREAD_NAME.get());

        try {
            // Parse and set Catalina and configuration specific
            // request parameters
            postParseSuccess = postParseRequest(req, request, res, response);
            if (postParseSuccess) {
                //check valves if we support async
                request.setAsyncSupported(
                        connector.getService().getContainer().getPipeline().isAsyncSupported());
```

Call the first [Valve.invoke()](/docs/CS/Java/Tomcat/Connector.md?id=invoke) of Pipeline

```java
                connector.getService().getContainer().getPipeline().getFirst().invoke(
                        request, response);
            }
            if (request.isAsync()) {
                async = true;
                ReadListener readListener = req.getReadListener();
                if (readListener != null && request.isFinished()) {
                    // Possible the all data may have been read during service()
                    // method so this needs to be checked here
                    ClassLoader oldCL = null;
                    try {
                        oldCL = request.getContext().bind(false, null);
                        if (req.sendAllDataReadEvent()) {
                            req.getReadListener().onAllDataRead();
                        }
                    } finally {
                        request.getContext().unbind(false, oldCL);
                    }
                }

                Throwable throwable =
                        (Throwable) request.getAttribute(RequestDispatcher.ERROR_EXCEPTION);

                // If an async request was started, is not going to end once
                // this container thread finishes and an error occurred, trigger
                // the async error process
                if (!request.isAsyncCompleting() && throwable != null) {
                    request.getAsyncContextInternal().setErrorState(throwable, true);
                }
            } else {
                request.finishRequest();
                response.finishResponse();
            }

        } catch (IOException e) {
            // Ignore
        } finally {
            AtomicBoolean error = new AtomicBoolean(false);
            res.action(ActionCode.IS_ERROR, error);

            if (request.isAsyncCompleting() && error.get()) {
                // Connection will be forcibly closed which will prevent
                // completion happening at the usual point. Need to trigger
                // call to onComplete() here.
                res.action(ActionCode.ASYNC_POST_PROCESS, null);
                async = false;
            }

            // Access log
            if (!async && postParseSuccess) {
                // Log only if processing was invoked.
                // If postParseRequest() failed, it has already logged it.
                Context context = request.getContext();
                Host host = request.getHost();
                // If the context is null, it is likely that the endpoint was
                // shutdown, this connection closed and the request recycled in
                // a different thread. That thread will have updated the access
                // log so it is OK not to update the access log here in that
                // case.
                // The other possibility is that an error occurred early in
                // processing and the request could not be mapped to a Context.
                // Log via the host or engine in that case.
                long time = System.nanoTime() - req.getStartTimeNanos();
                if (context != null) {
                    context.logAccess(request, response, time, false);
                } else if (response.isError()) {
                    if (host != null) {
                        host.logAccess(request, response, time, false);
                    } else {
                        connector.getService().getContainer().logAccess(
                                request, response, time, false);
                    }
                }
            }

            req.getRequestProcessor().setWorkerThreadName(null);

            // Recycle the wrapper request and response
            if (!async) {
                updateWrapperErrorCount(request, response);
                request.recycle();
                response.recycle();
            }
        }
    }
}
```

### Pipeline-Valve

#### invoke

Below StandardWrapperValve does:

1. Create the [filter chain](/docs/CS/Java/Tomcat/Connector.md?id=createFilterChain) for this request
2. Invoke the servlet we are managing in [doFilter](/docs/CS/Java/Tomcat/Connector.md?id=doFilter), respecting the rules regarding servlet lifecycle and SingleThreadModel support.

```java
final class StandardWrapperValve extends ValveBase {
    public final void invoke(Request request, Response response)
            throws IOException, ServletException {

        // Initialize local variables we may need
        boolean unavailable = false;
        Throwable throwable = null;
        // This should be a Request attribute...
        long t1 = System.currentTimeMillis();
        requestCount.incrementAndGet();
        StandardWrapper wrapper = (StandardWrapper) getContainer();
        Servlet servlet = null;
        Context context = (Context) wrapper.getParent();

        // Check for the application being marked unavailable
        if (!context.getState().isAvailable()) {
            response.sendError(HttpServletResponse.SC_SERVICE_UNAVAILABLE,
                    sm.getString("standardContext.isUnavailable"));
            unavailable = true;
        }

        // Check for the servlet being marked unavailable
        if (!unavailable && wrapper.isUnavailable()) {
            container.getLogger().info(sm.getString("standardWrapper.isUnavailable",
                    wrapper.getName()));
            long available = wrapper.getAvailable();
            if ((available > 0L) && (available < Long.MAX_VALUE)) {
                response.setDateHeader("Retry-After", available);
                response.sendError(HttpServletResponse.SC_SERVICE_UNAVAILABLE,
                        sm.getString("standardWrapper.isUnavailable",
                                wrapper.getName()));
            } else if (available == Long.MAX_VALUE) {
                response.sendError(HttpServletResponse.SC_NOT_FOUND,
                        sm.getString("standardWrapper.notFound",
                                wrapper.getName()));
            }
            unavailable = true;
        }

        // Allocate a servlet instance to process this request
        try {
            if (!unavailable) {
                servlet = wrapper.allocate();
            }
        } catch (UnavailableException e) {
            container.getLogger().error(
                    sm.getString("standardWrapper.allocateException",
                            wrapper.getName()), e);
            long available = wrapper.getAvailable();
            if ((available > 0L) && (available < Long.MAX_VALUE)) {
                response.setDateHeader("Retry-After", available);
                response.sendError(HttpServletResponse.SC_SERVICE_UNAVAILABLE,
                        sm.getString("standardWrapper.isUnavailable",
                                wrapper.getName()));
            } else if (available == Long.MAX_VALUE) {
                response.sendError(HttpServletResponse.SC_NOT_FOUND,
                        sm.getString("standardWrapper.notFound",
                                wrapper.getName()));
            }
        } catch (ServletException e) {
            container.getLogger().error(sm.getString("standardWrapper.allocateException",
                    wrapper.getName()), StandardWrapper.getRootCause(e));
            throwable = e;
            exception(request, response, e);
        } catch (Throwable e) {
            ExceptionUtils.handleThrowable(e);
            container.getLogger().error(sm.getString("standardWrapper.allocateException",
                    wrapper.getName()), e);
            throwable = e;
            exception(request, response, e);
            servlet = null;
        }

        MessageBytes requestPathMB = request.getRequestPathMB();
        DispatcherType dispatcherType = DispatcherType.REQUEST;
        if (request.getDispatcherType() == DispatcherType.ASYNC) dispatcherType = DispatcherType.ASYNC;
        request.setAttribute(Globals.DISPATCHER_TYPE_ATTR, dispatcherType);
        request.setAttribute(Globals.DISPATCHER_REQUEST_PATH_ATTR,
                requestPathMB);
        // Create the filter chain for this request
        ApplicationFilterChain filterChain =
                ApplicationFilterFactory.createFilterChain(request, wrapper, servlet);

        // Call the filter chain for this request
        // NOTE: This also calls the servlet's service() method
        Container container = this.container;
        try {
            if ((servlet != null) && (filterChain != null)) {
                // Swallow output if needed
                if (context.getSwallowOutput()) {
                    try {
                        SystemLogHandler.startCapture();
                        if (request.isAsyncDispatching()) {
                            request.getAsyncContextInternal().doInternalDispatch();
                        } else {
                            filterChain.doFilter(request.getRequest(),
                                    response.getResponse());
                        }
                    } finally {
                        String log = SystemLogHandler.stopCapture();
                        if (log != null && log.length() > 0) {
                            context.getLogger().info(log);
                        }
                    }
                } else {
                    if (request.isAsyncDispatching()) {
                        request.getAsyncContextInternal().doInternalDispatch();
                    } else {
                        filterChain.doFilter
                                (request.getRequest(), response.getResponse());
                    }
                }

            }
        } catch (ClientAbortException | CloseNowException e) {
            if (container.getLogger().isDebugEnabled()) {
                container.getLogger().debug(sm.getString(
                        "standardWrapper.serviceException", wrapper.getName(),
                        context.getName()), e);
            }
            throwable = e;
            exception(request, response, e);
        } catch (IOException e) {
            container.getLogger().error(sm.getString(
                    "standardWrapper.serviceException", wrapper.getName(),
                    context.getName()), e);
            throwable = e;
            exception(request, response, e);
        } catch (UnavailableException e) {
            container.getLogger().error(sm.getString(
                    "standardWrapper.serviceException", wrapper.getName(),
                    context.getName()), e);
            //            throwable = e;
            //            exception(request, response, e);
            wrapper.unavailable(e);
            long available = wrapper.getAvailable();
            if ((available > 0L) && (available < Long.MAX_VALUE)) {
                response.setDateHeader("Retry-After", available);
                response.sendError(HttpServletResponse.SC_SERVICE_UNAVAILABLE,
                        sm.getString("standardWrapper.isUnavailable",
                                wrapper.getName()));
            } else if (available == Long.MAX_VALUE) {
                response.sendError(HttpServletResponse.SC_NOT_FOUND,
                        sm.getString("standardWrapper.notFound",
                                wrapper.getName()));
            }
            // Do not save exception in 'throwable', because we
            // do not want to do exception(request, response, e) processing
        } catch (ServletException e) {
            Throwable rootCause = StandardWrapper.getRootCause(e);
            if (!(rootCause instanceof ClientAbortException)) {
                container.getLogger().error(sm.getString(
                        "standardWrapper.serviceExceptionRoot",
                        wrapper.getName(), context.getName(), e.getMessage()),
                        rootCause);
            }
            throwable = e;
            exception(request, response, e);
        } catch (Throwable e) {
            ExceptionUtils.handleThrowable(e);
            container.getLogger().error(sm.getString(
                    "standardWrapper.serviceException", wrapper.getName(),
                    context.getName()), e);
            throwable = e;
            exception(request, response, e);
        } finally {
            // Release the filter chain (if any) for this request
            if (filterChain != null) {
                filterChain.release();
            }

            // Deallocate the allocated servlet instance
            try {
                if (servlet != null) {
                    wrapper.deallocate(servlet);
                }
            } catch (Throwable e) {
                ExceptionUtils.handleThrowable(e);
                container.getLogger().error(sm.getString("standardWrapper.deallocateException",
                        wrapper.getName()), e);
                if (throwable == null) {
                    throwable = e;
                    exception(request, response, e);
                }
            }

            // If this servlet has been marked permanently unavailable,
            // unload it and release this instance
            try {
                if ((servlet != null) &&
                        (wrapper.getAvailable() == Long.MAX_VALUE)) {
                    wrapper.unload();
                }
            } catch (Throwable e) {
                ExceptionUtils.handleThrowable(e);
                container.getLogger().error(sm.getString("standardWrapper.unloadException",
                        wrapper.getName()), e);
                if (throwable == null) {
                    exception(request, response, e);
                }
            }
            long t2 = System.currentTimeMillis();

            long time = t2 - t1;
            processingTime += time;
            if (time > maxTime) maxTime = time;
            if (time < minTime) minTime = time;
        }
    }
}
```

#### createFilterChain

Construct a FilterChain implementation that will wrap the execution of the specified servlet instance.

```java
public final class ApplicationFilterFactory {
    public static ApplicationFilterChain createFilterChain(ServletRequest request,
                                                           Wrapper wrapper, Servlet servlet) {

        // Create and initialize a filter chain object
        ApplicationFilterChain filterChain = null;
        if (request instanceof Request) {
            Request req = (Request) request;
            if (Globals.IS_SECURITY_ENABLED) {
                // Security: Do not recycle
                filterChain = new ApplicationFilterChain();
            } else {
                filterChain = (ApplicationFilterChain) req.getFilterChain();
                if (filterChain == null) {
                    filterChain = new ApplicationFilterChain();
                    req.setFilterChain(filterChain);
                }
            }
        } else {
            // Request dispatcher in use
            filterChain = new ApplicationFilterChain();
        }

        filterChain.setServlet(servlet);
        filterChain.setServletSupportsAsync(wrapper.isAsyncSupported());

        // Acquire the filter mappings for this Context
        StandardContext context = (StandardContext) wrapper.getParent();
        FilterMap filterMaps[] = context.findFilterMaps();

        // Acquire the information we will need to match filter mappings
        DispatcherType dispatcher =
                (DispatcherType) request.getAttribute(Globals.DISPATCHER_TYPE_ATTR);

        String requestPath = null;
        Object attribute = request.getAttribute(Globals.DISPATCHER_REQUEST_PATH_ATTR);
        if (attribute != null) {
            requestPath = attribute.toString();
        }

        String servletName = wrapper.getName();

        // Add the relevant path-mapped filters to this filter chain
        for (FilterMap filterMap : filterMaps) {
            if (!matchDispatcher(filterMap, dispatcher)) {
                continue;
            }
            if (!matchFiltersURL(filterMap, requestPath)) {
                continue;
            }
            ApplicationFilterConfig filterConfig = (ApplicationFilterConfig)
                    context.findFilterConfig(filterMap.getFilterName());
            if (filterConfig == null) {
                // FIXME - log configuration problem
                continue;
            }
            filterChain.addFilter(filterConfig);
        }

        // Add filters that match on servlet name second
        for (FilterMap filterMap : filterMaps) {
            if (!matchDispatcher(filterMap, dispatcher)) {
                continue;
            }
            if (!matchFiltersServlet(filterMap, servletName)) {
                continue;
            }
            ApplicationFilterConfig filterConfig = (ApplicationFilterConfig)
                    context.findFilterConfig(filterMap.getFilterName());
            if (filterConfig == null) {
                // FIXME - log configuration problem
                continue;
            }
            filterChain.addFilter(filterConfig);
        }

        // Return the completed filter chain
        return filterChain;
    }
}
```

#### doFilter

Invoke the next filter in this chain, passing the specified request and response.
If there are no more filters in this chain, invoke the [service()](/docs/CS/Java/Tomcat/Connector.md?id=service) method of the servlet itself.

```java
public final class ApplicationFilterChain implements FilterChain {
    @Override
    public void doFilter(ServletRequest request, ServletResponse response)
            throws IOException, ServletException {

        if (Globals.IS_SECURITY_ENABLED) {
            final ServletRequest req = request;
            final ServletResponse res = response;
            // ignore try block
            java.security.AccessController.doPrivileged(
                    (java.security.PrivilegedExceptionAction<Void>) () -> {
                        internalDoFilter(req, res);
                        return null;
                    }
            );
            // ...
        } else {
            internalDoFilter(request, response);
        }
    }

    private void internalDoFilter(ServletRequest request,
                                  ServletResponse response)
            throws IOException, ServletException {

        // Call the next filter if there is one
        // ignore try block
        ApplicationFilterConfig filterConfig = filters[pos++];
        Filter filter = filterConfig.getFilter();
        // ...
        filter.doFilter(request, response, this);
```

We fell off the end of the chain -- call the [servlet.service()](/docs/CS/Java/JDK/Servlet.md?id=service) instance ignore try block

```java
        servlet.service(request, response);
    }
}
```

## Links

- [Tomcat](/docs/CS/Java/Tomcat/Tomcat.md)

## References

1. [Tomcat 中的 NIO 源码分析](https://www.javadoop.com/post/tomcat-nio)
