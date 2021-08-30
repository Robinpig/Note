## Introduction





## Example



```xml
<dependency>
    <groupId>org.apache.tomcat.embed</groupId>
    <artifactId>tomcat-embed-core</artifactId>
    <version>10.0.8</version>
</dependency>
```

```java
public static void main(String[] args) throws LifecycleException {
    final Tomcat tomcat = new Tomcat();
    final Connector connector = new Connector();
    connector.setPort(8080);
    tomcat.setConnector(connector);
    tomcat.start();
    tomcat.getServer().await();
}
```



### Create Connector



Create a new ProtocolHandler for the given protocol.

- org.apache.coyote.http11.Http11NioProtocol
- org.apache.coyote.http11.Http11Nio2Protocol
- org.apache.coyote.ajp.AjpNioProtocol
- org.apache.coyote.ajp.AjpNio2Protocol

```java
// Connector
// Defaults to using HTTP/1.1 NIO implementation.
public Connector() {
  this("HTTP/1.1");
}

public Connector(String protocol) {
	...
  p = ProtocolHandler.create(protocol);
 	...
}

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

default use NioEndpoint

```java
// Http11NioProtocol
public Http11NioProtocol() {
    super(new NioEndpoint());
}
```



Endpoint 



```java
// HTTP/1.1 protocol implementation using NIO2. 
public class Http11Nio2Protocol extends AbstractHttp11JsseProtocol<Nio2Channel> {    

	public Http11Nio2Protocol() {        super(new Nio2Endpoint());    }  
  ...
}

/** * Abstract the protocol implementation, including threading, etc. 
* Processor is single threaded and specific to stream-based protocols, 
* will not fit Jk protocols like JNI. 
*/
public class Http11NioProtocol extends AbstractHttp11JsseProtocol<NioChannel> {    
	public Http11NioProtocol() {        super(new NioEndpoint());    }
	...
}
```



NIO tailored thread pool, providing the following services:

1. Socket acceptor thread, default 1
2. Socket poller thread, default 1
3. Worker threads pool, default 10


When switching to Java 5, there's an opportunity to use the virtual machine's thread pool.

```java
public class NioEndpoint extends AbstractJsseEndpoint<NioChannel,SocketChannel> {}
```







Here are the difference between different version

```java
// 10.0.8 need to setConnector manually
public void start() throws LifecycleException {
    this.getServer();
    this.server.start();
}

// 8.5.32 auto create Connector
public void start() throws LifecycleException {
    this.getServer();
    this.getConnector();
    this.server.start();
}
```



```java


public Server getServer() {
  if (this.server != null) {
    return this.server;
  } else {
    System.setProperty("catalina.useNaming", "false");
    this.server = new StandardServer();
    this.initBaseDir();
    ConfigFileLoader.setSource(new CatalinaBaseConfigurationSource(new File(this.basedir), (String)null));
    this.server.setPort(-1);
    Service service = new StandardService();
    service.setName("Tomcat");
    this.server.addService(service);
    return this.server;
  }
}
```



call init order

1. StandardServer 
2. NamingRespurcesImpl 
3. StandardService 
4. MapperListener
5. Connector

```java
// LifecycleBase
@Override
public final synchronized void init() throws LifecycleException {
    if (!state.equals(LifecycleState.NEW)) {
        invalidTransition(Lifecycle.BEFORE_INIT_EVENT);
    }

    try {
        setStateInternal(LifecycleState.INITIALIZING, null, false);
        initInternal();
        setStateInternal(LifecycleState.INITIALIZED, null, false);
    } catch (Throwable t) {
        handleSubClassException(t, "lifecycleBase.initFail", toString());
    }
}
```



call `AbstractProtocol#init()`

```java
// Connector
@Override
protected void initInternal() throws LifecycleException {

    super.initInternal();
		...
    try {
        protocolHandler.init(); // default AbstractHttp11Protocol
    } catch (Exception e) {
        throw new LifecycleException(
                sm.getString("coyoteConnector.protocolHandlerInitializationFailed"), e);
    }
}
```









NOTE: There is no maintenance of state or checking for valid transitions within this class. It is expected that the connector will maintain state and prevent invalid state transitions.

```java
// AbstractProtocol
@Override
public void init() throws Exception {
    
  if (oname == null) {
        // Component not pre-registered so register it
        oname = createObjectName();
        if (oname != null) {
            Registry.getRegistry(null, null).registerComponent(this, oname, null);
        }
    }

    if (this.domain != null) {
        rgOname = new ObjectName(domain + ":type=GlobalRequestProcessor,name=" + getName());
        Registry.getRegistry(null, null).registerComponent(
                getHandler().getGlobal(), rgOname, null);
    }

    String endpointName = getName();
    endpoint.setName(endpointName.substring(1, endpointName.length()-1));
    endpoint.setDomain(domain);

    endpoint.init();
}

// AbstractEndpoint
public final void init() throws Exception {
  if (bindOnInit) {
    bindWithCleanup();
    bindState = BindState.BOUND_ON_INIT;
  }
  if (this.domain != null) {
    // Register endpoint (as ThreadPool - historical name)
    oname = new ObjectName(domain + ":type=ThreadPool,name=\"" + getName() + "\"");
    Registry.getRegistry(null, null).registerComponent(this, oname, null);

    ObjectName socketPropertiesOname = new ObjectName(domain +
                                                      ":type=ThreadPool,name=\"" + getName() + "\",subType=SocketProperties");
    socketProperties.setObjectName(socketPropertiesOname);
    Registry.getRegistry(null, null).registerComponent(socketProperties, socketPropertiesOname, null);

    for (SSLHostConfig sslHostConfig : findSslHostConfigs()) {
      registerJmx(sslHostConfig);
    }
  }
}

private void bindWithCleanup() throws Exception {
  try {
    bind();
  } catch (Throwable t) {
    // Ensure open sockets etc. are cleaned up if something goes
    // wrong during bind
    ExceptionUtils.handleThrowable(t);
    unbind();
    throw t;
  }
}

// NioEndpoint
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
      this.serverSock = (ServerSocketChannel)ic;
    }

    if (this.serverSock == null) {
      throw new IllegalArgumentException(sm.getString("endpoint.init.bind.inherited"));
    }
  }

  this.serverSock.configureBlocking(true);
}
```









Start the NIO endpoint, creating acceptor, poller threads and [executor](/docs/CS/Java/Tomcat/threads.md?id=ThreadPoolExecutor).

```java
// AbstractProtocol
@Override
public void start() throws Exception {
    endpoint.start();
    monitorFuture = getUtilityExecutor().scheduleWithFixedDelay(
            new Runnable() {
                @Override
                public void run() {
                    if (!isPaused()) {
                        startAsyncTimeout();
                    }
                }
            }, 0, 60, TimeUnit.SECONDS);
}
```



```java
// AbstractEndpoint
public final void start() throws Exception {
    if (bindState == BindState.UNBOUND) {
        bindWithCleanup();
        bindState = BindState.BOUND_ON_START;
    }
    startInternal();
}

// NioEndpoint
// Start the NIO endpoint, creating acceptor, poller threads.
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

```



### Acceptor

```java
// Acceptor
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
```



Process the specified connection.

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



Registers a newly created socket with the poller.

```java
// NioEndpoint
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
```

### Poller

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
...
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





The background thread that adds sockets to the Poller, checks the poller for triggered events and hands the associated socket off to an appropriate processor as events occur.

```java
// NioEndpoint$Poller
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
        timeout(keyCount,hasEvents);
    }

    getStopLatch().countDown();
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



```java
protected boolean process() {
    try {
        getEndpoint().getExecutor().execute(this);
        return true;
    } catch (RejectedExecutionException ree) {
        log.warn(sm.getString("endpoint.executor.fail", SocketWrapperBase.this) , ree);
    } catch (Throwable t) {
        ExceptionUtils.handleThrowable(t);
        // This means we got an OOM or similar creating a thread, or that
        // the pool and its queue are full
        log.error(sm.getString("endpoint.process.fail"), t);
    }
    return false;
}
```



## Reference

1. [Tomcat 中的 NIO 源码分析](https://www.javadoop.com/post/tomcat-nio)