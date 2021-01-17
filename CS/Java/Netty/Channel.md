# Channel

![Channel](https://github.com/Robinpig/Note/raw/master/images/Netty/Channel.png)



## AbstraceChannel

### Constructor

```java
/**
 * Creates a new instance.
 *
 * @param parent
 *        the parent of this channel. {@code null} if there's no parent.
 */
protected AbstractChannel(Channel parent) {
    this.parent = parent;
    id = newId();
    unsafe = newUnsafe();
    pipeline = newChannelPipeline();
}
```



### register( )

```java
@Override
public final void register(EventLoop eventLoop, final ChannelPromise promise) {
    if (eventLoop == null) {
        throw new NullPointerException("eventLoop");
    }
    if (isRegistered()) {
        promise.setFailure(new IllegalStateException("registered to an event loop already"));
        return;
    }
    if (!isCompatible(eventLoop)) {
        promise.setFailure(
                new IllegalStateException("incompatible event loop type: " + eventLoop.getClass().getName()));
        return;
    }

    AbstractChannel.this.eventLoop = eventLoop;

    if (eventLoop.inEventLoop()) {
        register0(promise);
    } else {
        try {
            eventLoop.execute(new Runnable() {
                @Override
                public void run() {
                    register0(promise);
                }
            });
        } catch (Throwable t) {
            logger.warn(
                    "Force-closing a channel whose registration task was not accepted by an event loop: {}",
                    AbstractChannel.this, t);
            closeForcibly();
            closeFuture.setClosed();
            safeSetFailure(promise, t);
        }
    }
}

private void register0(ChannelPromise promise) {
    try {
        // check if the channel is still open as it could be closed in the mean time when the register
        // call was outside of the eventLoop
        if (!promise.setUncancellable() || !ensureOpen(promise)) {
            return;
        }
        boolean firstRegistration = neverRegistered;
        doRegister();
        neverRegistered = false;
        registered = true;

        // Ensure we call handlerAdded(...) before we actually notify the promise. This is needed as the
        // user may already fire events through the pipeline in the ChannelFutureListener.
        pipeline.invokeHandlerAddedIfNeeded();

        safeSetSuccess(promise);
        pipeline.fireChannelRegistered();
        // Only fire a channelActive if the channel has never been registered. This prevents firing
        // multiple channel actives if the channel is deregistered and re-registered.
        if (isActive()) {
            if (firstRegistration) {
                pipeline.fireChannelActive();
            } else if (config().isAutoRead()) {
                // This channel was registered before and autoRead() is set. This means we need to begin read
                // again so that we process inbound data.
                //
                // See https://github.com/netty/netty/issues/4805
                beginRead();
            }
        }
    } catch (Throwable t) {
        // Close the channel directly to avoid FD leak.
        closeForcibly();
        closeFuture.setClosed();
        safeSetFailure(promise, t);
    }
}
```



beginRead( )

```java
@Override
public final void beginRead() {
    assertEventLoop();

    if (!isActive()) {
        return;
    }

    try {
        doBeginRead();
    } catch (final Exception e) {
        invokeLater(new Runnable() {
            @Override
            public void run() {
                pipeline.fireExceptionCaught(e);
            }
        });
        close(voidPromise());
    }
}

@Override
protected void doBeginRead() throws Exception {
    // Channel.read() or ChannelHandlerContext.read() was called
    final SelectionKey selectionKey = this.selectionKey;
    if (!selectionKey.isValid()) {
        return;
    }

    readPending = true;

    final int interestOps = selectionKey.interestOps();
    if ((interestOps & readInterestOp) == 0) {
        selectionKey.interestOps(interestOps | readInterestOp);
    }
}
```



doRegister( )

```java
@Override
protected void doRegister() throws Exception {
    boolean selected = false;
    for (;;) {
        try {
            selectionKey = javaChannel().register(eventLoop().unwrappedSelector(), 0, this);
            return;
        } catch (CancelledKeyException e) {
            if (!selected) {
                // Force the Selector to select now as the "canceled" SelectionKey may still be
                // cached and not removed because no Select.select(..) operation was called yet.
                eventLoop().selectNow();
                selected = true;
            } else {
                // We forced a select operation on the selector before but the SelectionKey is still cached
                // for whatever reason. JDK bug ?
                throw e;
            }
        }
    }
}
```



## ChannelPipeline



### fireChannelActive( )

```java
@Override
public final ChannelPipeline fireChannelActive() {
    AbstractChannelHandlerContext.invokeChannelActive(head);
    return this;
}

static void invokeChannelActive(final AbstractChannelHandlerContext next) {
    EventExecutor executor = next.executor();
    if (executor.inEventLoop()) {
        next.invokeChannelActive();
    } else {
        executor.execute(new Runnable() {
            @Override
            public void run() {
                next.invokeChannelActive();
            }
        });
    }
}

static void invokeChannelActive(final AbstractChannelHandlerContext next) {
    EventExecutor executor = next.executor();
    if (executor.inEventLoop()) {
        next.invokeChannelActive();
    } else {
        executor.execute(new Runnable() {
            @Override
            public void run() {
                next.invokeChannelActive();
            }
        });
    }
}
```



```java
@Override
public void channelActive(ChannelHandlerContext ctx) {
    ctx.fireChannelActive();

    readIfIsAutoRead();
}
```

```
private void readIfIsAutoRead() {
    if (channel.config().isAutoRead()) {
        channel.read();
    }
}
```





### Pipeline

```java
 /**
  *                                                 I/O Request
  *                                            via {@link Channel} or
  *                                        {@link ChannelHandlerContext}
  *                                                      |
  *  +---------------------------------------------------+---------------+
  *  |                           ChannelPipeline         |               |
  *  |                                                  \|/              |
  *  |    +---------------------+            +-----------+----------+    |
  *  |    | Inbound Handler  N  |            | Outbound Handler  1  |    |
  *  |    +----------+----------+            +-----------+----------+    |
  *  |              /|\                                  |               |
  *  |               |                                  \|/              |
  *  |    +----------+----------+            +-----------+----------+    |
  *  |    | Inbound Handler N-1 |            | Outbound Handler  2  |    |
  *  |    +----------+----------+            +-----------+----------+    |
  *  |              /|\                                  .               |
  *  |               .                                   .               |
  *  | ChannelHandlerContext.fireIN_EVT() ChannelHandlerContext.OUT_EVT()|
  *  |        [ method call]                       [method call]         |
  *  |               .                                   .               |
  *  |               .                                  \|/              |
  *  |    +----------+----------+            +-----------+----------+    |
  *  |    | Inbound Handler  2  |            | Outbound Handler M-1 |    |
  *  |    +----------+----------+            +-----------+----------+    |
  *  |              /|\                                  |               |
  *  |               |                                  \|/              |
  *  |    +----------+----------+            +-----------+----------+    |
  *  |    | Inbound Handler  1  |            | Outbound Handler  M  |    |
  *  |    +----------+----------+            +-----------+----------+    |
  *  |              /|\                                  |               |
  *  +---------------+-----------------------------------+---------------+
  *                  |                                  \|/
  *  +---------------+-----------------------------------+---------------+
  *  |               |                                   |               |
  *  |       [ Socket.read() ]                    [ Socket.write() ]     |
  *  |                                                                   |
  *  |  Netty Internal I/O Threads (Transport Implementation)            |
  *  +-------------------------------------------------------------------+
  */
```



newChannelPipeline 

AbstractChannel Constructor init ChannelPipeline

```java
/**
 * Returns a new {@link DefaultChannelPipeline} instance.
 */
protected DefaultChannelPipeline newChannelPipeline() {
    return new DefaultChannelPipeline(this);
}

protected DefaultChannelPipeline(Channel channel) {
    this.channel = ObjectUtil.checkNotNull(channel, "channel");
    succeededFuture = new SucceededChannelFuture(channel, null);
    voidPromise =  new VoidChannelPromise(channel, true);

    tail = new TailContext(this);
    head = new HeadContext(this);

    head.next = tail;
    tail.prev = head;
}

TailContext(DefaultChannelPipeline pipeline) {
    super(pipeline, null, TAIL_NAME, TailContext.class);
    setAddComplete();
}

HeadContext(DefaultChannelPipeline pipeline) {
    super(pipeline, null, HEAD_NAME, HeadContext.class);
    unsafe = pipeline.channel().unsafe();
    setAddComplete();
}
```



## Unsafe

```java
/**
 * {@link Unsafe} implementation which sub-classes must extend and use.
 */
protected abstract class AbstractUnsafe implements Unsafe {

}
```



### read( )

```java
  @Override
    public void read() {
        assert eventLoop().inEventLoop();
        final ChannelConfig config = config();
        final ChannelPipeline pipeline = pipeline();
        final RecvByteBufAllocator.Handle allocHandle = unsafe().recvBufAllocHandle();
        allocHandle.reset(config);

        boolean closed = false;
        Throwable exception = null;
        try {
            try {
                do {
                    int localRead = doReadMessages(readBuf);
                    if (localRead == 0) {
                        break;
                    }
                    if (localRead < 0) {
                        closed = true;
                        break;
                    }

                    allocHandle.incMessagesRead(localRead);
                } while (allocHandle.continueReading());
            } catch (Throwable t) {
                exception = t;
            }

            int size = readBuf.size();
            for (int i = 0; i < size; i ++) {
                readPending = false;
                pipeline.fireChannelRead(readBuf.get(i));
            }
            readBuf.clear();
            allocHandle.readComplete();
            pipeline.fireChannelReadComplete();

            if (exception != null) {
                closed = closeOnReadError(exception);

                pipeline.fireExceptionCaught(exception);
            }

            if (closed) {
                inputShutdown = true;
                if (isOpen()) {
                    close(voidPromise());
                }
            }
        } finally {
            // Check if there is a readPending which was not processed yet.
            // This could be for two reasons:
            // * The user called Channel.read() or ChannelHandlerContext.read() in channelRead(...) method
            // * The user called Channel.read() or ChannelHandlerContext.read() in channelReadComplete(...) method
            //
            // See https://github.com/netty/netty/issues/2254
            if (!readPending && !config.isAutoRead()) {
                removeReadOp();
            }
        }
    }
}

@Override
protected int doReadMessages(List<Object> buf) throws Exception {
    SocketChannel ch = SocketUtils.accept(javaChannel());

    try {
        if (ch != null) {
            buf.add(new NioSocketChannel(this, ch));
            return 1;
        }
    } catch (Throwable t) {
        logger.warn("Failed to create a new channel from an accepted socket.", t);

        try {
            ch.close();
        } catch (Throwable t2) {
            logger.warn("Failed to close a socket.", t2);
        }
    }

    return 0;
}
```



