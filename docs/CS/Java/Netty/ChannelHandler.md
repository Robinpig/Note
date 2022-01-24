## Introduction







## ChannelPipeline



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
// Returns a new {@link DefaultChannelPipeline} instance.
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



### addFirst

we set the EventExecutorGroup of our workerThreadPoolExecutor for business.

```java
@Override
public final ChannelPipeline addFirst(EventExecutorGroup group, String name, ChannelHandler handler) {
    final AbstractChannelHandlerContext newCtx;
    synchronized (this) {
        checkMultiplicity(handler); // check if !h.isSharable() && h.added
        name = filterName(name, handler);

        newCtx = newContext(group, name, handler);

        addFirst0(newCtx);

        // If the registered is false it means that the channel was not registered on an eventLoop yet.
        // In this case we add the context to the pipeline and add a task that will call
        // ChannelHandler.handlerAdded(...) once the channel is registered.
        if (!registered) {
            newCtx.setAddPending();
            callHandlerCallbackLater(newCtx, true);
            return this;
        }

        EventExecutor executor = newCtx.executor();
        if (!executor.inEventLoop()) {
            callHandlerAddedInEventLoop(newCtx, executor);
            return this;
        }
    }
    callHandlerAdded0(newCtx);
    return this;
}

```



### fireChannelActive

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

/**
 * In HeadContext
 */
private void readIfIsAutoRead() {
    if (channel.config().isAutoRead()) {
        channel.read();
    }
}
```





```java
// AbstractChannelHandlerContext#disconnect()
@Override
public ChannelFuture disconnect(final ChannelPromise promise) {
    if (!channel().metadata().hasDisconnect()) {
        // Translate disconnect to close if the channel has no notion of disconnect-reconnect.
        // So far, UDP/IP is the only transport that has such behavior.
        return close(promise);
    }
    if (isNotValidPromise(promise, false)) {
        // cancelled
        return promise;
    }

    final AbstractChannelHandlerContext next = findContextOutbound(MASK_DISCONNECT);
    EventExecutor executor = next.executor();
    if (executor.inEventLoop()) {
        next.invokeDisconnect(promise);
    } else {
        safeExecute(executor, new Runnable() {
            @Override
            public void run() {
                next.invokeDisconnect(promise);
            }
        }, promise, null, false);
    }
    return promise;
}
```



## inbound

from head -> tail



```java
// DefaultChannelPipeline
@Override
public final ChannelPipeline fireChannelRead(Object msg) {
  AbstractChannelHandlerContext.invokeChannelRead(head, msg);
  return this;
}

// AbstractChannelHandlerContext
@Override
public ChannelHandlerContext fireChannelRead(final Object msg) {
  invokeChannelRead(findContextInbound(MASK_CHANNEL_READ), msg);
  return this;
}

static void invokeChannelRead(final AbstractChannelHandlerContext next, Object msg) {
    final Object m = next.pipeline.touch(ObjectUtil.checkNotNull(msg, "msg"), next);
    EventExecutor executor = next.executor();
    if (executor.inEventLoop()) {
        next.invokeChannelRead(m);
    } else {
        executor.execute(new Runnable() {
            @Override
            public void run() {
                next.invokeChannelRead(m);
            }
        });
    }
}


private void invokeChannelRead(Object msg) {
  if (invokeHandler()) {
    try {
      ((ChannelInboundHandler) handler()).channelRead(this, msg);
    } catch (Throwable t) {
      invokeExceptionCaught(t);
    }
  } else {
    fireChannelRead(msg);
  }
}
```



Makes best possible effort to detect if ChannelHandler.handlerAdded(ChannelHandlerContext) was called yet. If not return false and if called or could not detect return true. If this method returns false we will not invoke the ChannelHandler but just forward the event. This is needed as DefaultChannelPipeline may already put the ChannelHandler in the linked-list but not called ChannelHandler.handlerAdded(ChannelHandlerContext).

```java
private boolean invokeHandler() {
    // Store in local variable to reduce volatile reads.
    int handlerState = this.handlerState;
    return handlerState == ADD_COMPLETE || (!ordered && handlerState == ADD_PENDING);
}
```





```java
// AbstractChannelHandlerContext
@Override
public ChannelHandlerContext fireChannelRead(final Object msg) {
  invokeChannelRead(findContextInbound(MASK_CHANNEL_READ), msg);
  return this;
}

private AbstractChannelHandlerContext findContextInbound(int mask) {
    AbstractChannelHandlerContext ctx = this;
    EventExecutor currentExecutor = executor();
    do {
        ctx = ctx.next;
    } while (skipContext(ctx, currentExecutor, mask, MASK_ONLY_INBOUND));
    return ctx;
}

private static boolean skipContext(
  AbstractChannelHandlerContext ctx, EventExecutor currentExecutor, int mask, int onlyMask) {
  // Ensure we correctly handle MASK_EXCEPTION_CAUGHT which is not included in the MASK_EXCEPTION_CAUGHT
  return (ctx.executionMask & (onlyMask | mask)) == 0 ||
    // We can only skip if the EventExecutor is the same as otherwise we need to ensure we offload
    // everything to preserve ordering.
    //
    // See https://github.com/netty/netty/issues/10067
    (ctx.executor() == currentExecutor && (ctx.executionMask & mask) == 0);
}
```



### HeadContext



```java
final class HeadContext extends AbstractChannelHandlerContext
        implements ChannelOutboundHandler, ChannelInboundHandler {

    private final Unsafe unsafe;

    HeadContext(DefaultChannelPipeline pipeline) {
        super(pipeline, null, HEAD_NAME, HeadContext.class);
        unsafe = pipeline.channel().unsafe();
        setAddComplete();
    }

  final boolean setAddComplete() {
    for (;;) {
      int oldState = handlerState;
      if (oldState == REMOVE_COMPLETE) {
        return false;
      }
      // Ensure we never update when the handlerState is REMOVE_COMPLETE already.
      // oldState is usually ADD_PENDING but can also be REMOVE_COMPLETE when an EventExecutor is used that is not
      // exposing ordering guarantees.
      if (HANDLER_STATE_UPDATER.compareAndSet(this, oldState, ADD_COMPLETE)) {
        return true;
      }
    }
  }
}
```



```java
@Override
public void bind(
        ChannelHandlerContext ctx, SocketAddress localAddress, ChannelPromise promise) {
    unsafe.bind(localAddress, promise);
}
```



```java
@Override
public void channelRead(ChannelHandlerContext ctx, Object msg) {
    ctx.fireChannelRead(msg);
}

@Override
public void channelReadComplete(ChannelHandlerContext ctx) {
    ctx.fireChannelReadComplete();

    readIfIsAutoRead();
}

private void readIfIsAutoRead() {
    if (channel.config().isAutoRead()) {
        channel.read();
    }
}
```

Make sure use same EventLoop
```java
abstract class AbstractChannelHandlerContext implements ChannelHandlerContext, ResourceLeakHint {
    static void invokeChannelRead(final AbstractChannelHandlerContext next, Object msg) {
        final Object m = next.pipeline.touch(ObjectUtil.checkNotNull(msg, "msg"), next);
        EventExecutor executor = next.executor();
        if (executor.inEventLoop()) {
            next.invokeChannelRead(m);
        } else {
            executor.execute(new Runnable() {
                @Override
                public void run() {
                    next.invokeChannelRead(m);
                }
            });
        }
    }
}
```


```java
// HeadContext
public void channelRead(ChannelHandlerContext ctx, Object msg) {
    ctx.fireChannelRead(msg);
}
```


```java
abstract class AbstractChannelHandlerContext implements ChannelHandlerContext, ResourceLeakHint {
    public ChannelHandlerContext fireChannelRead(final Object msg) {
        invokeChannelRead(findContextInbound(MASK_CHANNEL_READ), msg);
        return this;
    }

    private AbstractChannelHandlerContext findContextInbound(int mask) {
        AbstractChannelHandlerContext ctx = this;
        EventExecutor currentExecutor = executor();
        do {
            ctx = ctx.next;
        } while (skipContext(ctx, currentExecutor, mask, MASK_ONLY_INBOUND));
        return ctx;
    }
}
```


## outbound

tail -> head
### TailContext



```java
// A special catch-all handler that handles both bytes and messages.
final class TailContext extends AbstractChannelHandlerContext implements ChannelInboundHandler {

    TailContext(DefaultChannelPipeline pipeline) {
        super(pipeline, null, TAIL_NAME, TailContext.class);
        setAddComplete();
    }
}
```



Called once a message hit the end of the ChannelPipeline without been handled by the user in ChannelInboundHandler.channelRead(ChannelHandlerContext, Object). 
This method is responsible to call **ReferenceCountUtil.release(Object)** on the given msg at some point.

```java
 @Override
        public void channelRead(ChannelHandlerContext ctx, Object msg) {
            onUnhandledInboundMessage(ctx, msg);
        }

 protected void onUnhandledInboundMessage(ChannelHandlerContext ctx, Object msg) {
        onUnhandledInboundMessage(msg);
        if (logger.isDebugEnabled()) {
            logger.debug("Discarded message pipeline : {}. Channel : {}.",
                         ctx.pipeline().names(), ctx.channel());
        }
    }

protected void onUnhandledInboundMessage(Object msg) {
    try {
			// log
    } finally {
        ReferenceCountUtil.release(msg);
    }
}
```


#### addMessage
Add given message to this ChannelOutboundBuffer. The given ChannelPromise will be notified once the message was written.

```java
public final class ChannelOutboundBuffer {
    public void addMessage(Object msg, int size, ChannelPromise promise) {
        Entry entry = Entry.newInstance(msg, size, total(msg), promise);
        if (tailEntry == null) {
            flushedEntry = null;
        } else {
            Entry tail = tailEntry;
            tail.next = entry;
        }
        tailEntry = entry;
        if (unflushedEntry == null) {
            unflushedEntry = entry;
        }

        // increment pending bytes after adding message to the unflushed arrays.
        // See https://github.com/netty/netty/issues/1619
        incrementPendingOutboundBytes(entry.pendingSize, false);
    }
}
```
#### addFlush
Add a flush to this ChannelOutboundBuffer. This means all previous added messages are marked as flushed and so you will be able to handle them.


```java
public final class ChannelOutboundBuffer {
    public void addFlush() {
        // There is no need to process all entries if there was already a flush before and no new messages
        // where added in the meantime.
        //
        // See https://github.com/netty/netty/issues/2577
        Entry entry = unflushedEntry;
        if (entry != null) {
            if (flushedEntry == null) {
                // there is no flushedEntry yet, so start with the entry
                flushedEntry = entry;
            }
            do {
                flushed++;
                if (!entry.promise.setUncancellable()) {
                    // Was cancelled so make sure we free up memory and notify about the freed bytes
                    int pending = entry.cancel();
                    decrementPendingOutboundBytes(pending, false, true);
                }
                entry = entry.next;
            } while (entry != null);

            // All flushed so reset unflushedEntry
            unflushedEntry = null;
        }
    }
}
```

#### doWrite


```java
public class NioSocketChannel extends AbstractNioByteChannel implements io.netty.channel.socket.SocketChannel {
    protected void doWrite(ChannelOutboundBuffer in) throws Exception {
        SocketChannel ch = javaChannel();
        /*
         * Returns the maximum loop count for a write operation until WritableByteChannel.write(ByteBuffer) returns a non-zero value. 
         * It is similar to what a spin lock is used for in concurrency programming. 
         * It improves memory utilization and write throughput depending on the platform that JVM runs on. 
         * The default value is 16.
         */
        int writeSpinCount = config().getWriteSpinCount();
        do {
            if (in.isEmpty()) {
                // All written so clear OP_WRITE
                clearOpWrite();
                // Directly return here so incompleteWrite(...) is not called.
                return;
            }

            // Ensure the pending writes are made of ByteBufs only.
            int maxBytesPerGatheringWrite = ((NioSocketChannelConfig) config).getMaxBytesPerGatheringWrite();
            ByteBuffer[] nioBuffers = in.nioBuffers(1024, maxBytesPerGatheringWrite);
            int nioBufferCnt = in.nioBufferCount();

            // Always use nioBuffers() to workaround data-corruption.
            // See https://github.com/netty/netty/issues/2761
            switch (nioBufferCnt) {
                case 0:
                    // We have something else beside ByteBuffers to write so fallback to normal writes.
                    writeSpinCount -= doWrite0(in);
                    break;
                case 1: {
                    // Only one ByteBuf so use non-gathering write
                    // Zero length buffers are not added to nioBuffers by ChannelOutboundBuffer, so there is no need
                    // to check if the total size of all the buffers is non-zero.
                    ByteBuffer buffer = nioBuffers[0];
                    int attemptedBytes = buffer.remaining();
                    final int localWrittenBytes = ch.write(buffer);
                    if (localWrittenBytes <= 0) {
                        incompleteWrite(true);
                        return;
                    }
                    adjustMaxBytesPerGatheringWrite(attemptedBytes, localWrittenBytes, maxBytesPerGatheringWrite);
                    in.removeBytes(localWrittenBytes);
                    --writeSpinCount;
                    break;
                }
                default: {
                    // Zero length buffers are not added to nioBuffers by ChannelOutboundBuffer, so there is no need
                    // to check if the total size of all the buffers is non-zero.
                    // We limit the max amount to int above so cast is safe
                    long attemptedBytes = in.nioBufferSize();
                    final long localWrittenBytes = ch.write(nioBuffers, 0, nioBufferCnt);
                    if (localWrittenBytes <= 0) {
                        incompleteWrite(true);
                        return;
                    }
                    // Casting to int is safe because we limit the total amount of data in the nioBuffers to int above.
                    adjustMaxBytesPerGatheringWrite((int) attemptedBytes, (int) localWrittenBytes,
                            maxBytesPerGatheringWrite);
                    in.removeBytes(localWrittenBytes);
                    --writeSpinCount;
                    break;
                }
            }
        } while (writeSpinCount > 0);

        incompleteWrite(writeSpinCount < 0);
    }

}
```

flush

```java
protected abstract class AbstractUnsafe implements Unsafe {
    @Override
    public final void flush() {
        assertEventLoop();

        ChannelOutboundBuffer outboundBuffer = this.outboundBuffer;
        if (outboundBuffer == null) {
            return;
        }

        outboundBuffer.addFlush();
        flush0();
    }
}
```


## ChannelHandler



Handles an I/O event or intercepts an I/O operation, and forwards it to its next handler in its [`ChannelPipeline`](https://netty.io/4.1/api/io/netty/channel/ChannelPipeline.html).

**Sub-types**

[`ChannelHandler`](https://netty.io/4.1/api/io/netty/channel/ChannelHandler.html) itself does not provide many methods, but you usually have to implement one of its subtypes:

- [`ChannelInboundHandler`](https://netty.io/4.1/api/io/netty/channel/ChannelInboundHandler.html) to handle inbound I/O events, and
- [`ChannelOutboundHandler`](https://netty.io/4.1/api/io/netty/channel/ChannelOutboundHandler.html) to handle outbound I/O operations.



Alternatively, the following adapter classes are provided for your convenience:

- [`ChannelInboundHandlerAdapter`](https://netty.io/4.1/api/io/netty/channel/ChannelInboundHandlerAdapter.html) to handle inbound I/O events,
- [`ChannelOutboundHandlerAdapter`](https://netty.io/4.1/api/io/netty/channel/ChannelOutboundHandlerAdapter.html) to handle outbound I/O operations, and
- [`ChannelDuplexHandler`](https://netty.io/4.1/api/io/netty/channel/ChannelDuplexHandler.html) to handle both inbound and outbound events



For more information, please refer to the documentation of each subtype.

**The context object**

A [`ChannelHandler`](https://netty.io/4.1/api/io/netty/channel/ChannelHandler.html) is provided with a [`ChannelHandlerContext`](https://netty.io/4.1/api/io/netty/channel/ChannelHandlerContext.html) object. A [`ChannelHandler`](https://netty.io/4.1/api/io/netty/channel/ChannelHandler.html) is supposed to interact with the [`ChannelPipeline`](https://netty.io/4.1/api/io/netty/channel/ChannelPipeline.html) it belongs to via a context object. Using the context object, the [`ChannelHandler`](https://netty.io/4.1/api/io/netty/channel/ChannelHandler.html) can pass events upstream or downstream, modify the pipeline dynamically, or store the information (using [`AttributeKey`](https://netty.io/4.1/api/io/netty/util/AttributeKey.html)s) which is specific to the handler.

**State management**

A [`ChannelHandler`](https://netty.io/4.1/api/io/netty/channel/ChannelHandler.html) often needs to store some stateful information. The simplest and recommended approach is to use member variables:

```java
 public interface Message {
     // your methods here
 }

 public class DataServerHandler extends SimpleChannelInboundHandler<Message> {

     private boolean loggedIn;

      @Override
     public void channelRead0(ChannelHandlerContext ctx, Message message) {
         if (message instanceof LoginMessage) {
             authenticate((LoginMessage) message);
             loggedIn = true;
         } else (message instanceof GetDataMessage) {
             if (loggedIn) {
                 ctx.writeAndFlush(fetchSecret((GetDataMessage) message));
             } else {
                 fail();
             }
         }
     }
     ...
 }
 
```

Because the handler instance has a state variable which is dedicated to one connection, you have to create a new handler instance for each new channel to avoid a race condition where a unauthenticated client can get the confidential information:

```java
 // Create a new handler instance per channel.
 // See ChannelInitializer.initChannel(Channel).
 public class DataServerInitializer extends ChannelInitializer<Channel> {
      @Override
     public void initChannel(Channel channel) {
         channel.pipeline().addLast("handler", new DataServerHandler());
     }
 }

 
```

**Using [`AttributeKey`](https://netty.io/4.1/api/io/netty/util/AttributeKey.html)s**

Although it's recommended to use member variables to store the state of a handler, for some reason you might not want to create many handler instances. In such a case, you can use [`AttributeKey`](https://netty.io/4.1/api/io/netty/util/AttributeKey.html)s which is provided by [`ChannelHandlerContext`](https://netty.io/4.1/api/io/netty/channel/ChannelHandlerContext.html):

```java
 public interface Message {
     // your methods here
 }

  @Sharable
 public class DataServerHandler extends SimpleChannelInboundHandler<Message> {
     private final AttributeKey<Boolean> auth =
           AttributeKey.valueOf("auth");

      @Override
     public void channelRead(ChannelHandlerContext ctx, Message message) {
         Attribute<Boolean> attr = ctx.attr(auth);
         if (message instanceof LoginMessage) {
             authenticate((LoginMessage) o);
             attr.set(true);
         } else (message instanceof GetDataMessage) {
             if (Boolean.TRUE.equals(attr.get())) {
                 ctx.writeAndFlush(fetchSecret((GetDataMessage) o));
             } else {
                 fail();
             }
         }
     }
     ...
 }
 
```

Now that the state of the handler is attached to the [`ChannelHandlerContext`](https://netty.io/4.1/api/io/netty/channel/ChannelHandlerContext.html), you can add the same handler instance to different pipelines:

```java
 public class DataServerInitializer extends ChannelInitializer<Channel> {

     private static final DataServerHandler SHARED = new DataServerHandler();

      @Override
     public void initChannel(Channel channel) {
         channel.pipeline().addLast("handler", SHARED);
     }
 }
 
```

**The `@Sharable` annotation**

In the example above which used an [`AttributeKey`](https://netty.io/4.1/api/io/netty/util/AttributeKey.html), you might have noticed the `@Sharable` annotation.

If a [`ChannelHandler`](https://netty.io/4.1/api/io/netty/channel/ChannelHandler.html) is annotated with the `@Sharable` annotation, it means you can create an instance of the handler just once and add it to one or more [`ChannelPipeline`](https://netty.io/4.1/api/io/netty/channel/ChannelPipeline.html)s multiple times without a race condition.

If this annotation is not specified, you have to create a new handler instance every time you add it to a pipeline because it has unshared state such as member variables.

This annotation is provided for documentation purpose, just like [the JCIP annotations](http://www.javaconcurrencyinpractice.com/annotations/doc/).

**Additional resources worth reading**

Please refer to the [`ChannelHandler`](https://netty.io/4.1/api/io/netty/channel/ChannelHandler.html), and [`ChannelPipeline`](https://netty.io/4.1/api/io/netty/channel/ChannelPipeline.html) to find out more about inbound and outbound operations, what fundamental differences they have, how they flow in a pipeline, and how to handle the operation in your application.



### LengthFieldBasedFrameDecoder

```java
// LengthFieldBasedFrameDecoder
@Override
protected final void decode(ChannelHandlerContext ctx, ByteBuf in, List<Object> out) throws Exception {
    Object decoded = decode(ctx, in);
    if (decoded != null) {
        out.add(decoded);
    }
}
```

lengthAdjustment



discardingTooLongFrame

tooLongFrameLength

bytesToDiscard



readableBytes < lengthFieldEndOffset, return null



### ChannelInitializer



#### initChannel

Only call by `handlerAdded` or `channelRegistered`.

Prevent multiple calls to initChannel().

```java
private boolean initChannel(ChannelHandlerContext ctx) throws Exception {
    if (initMap.add(ctx)) { // Guard against re-entrance.
        try {
            initChannel((C) ctx.channel());
        } catch (Throwable cause) {
            // Explicitly call exceptionCaught(...) as we removed the handler before calling initChannel(...).
            // We do so to prevent multiple calls to initChannel(...).
            exceptionCaught(ctx, cause);
        } finally {
            ChannelPipeline pipeline = ctx.pipeline();
            if (pipeline.context(this) != null) {
                pipeline.remove(this);
            }
        }
        return true;
    }
    return false;
}
```

Gets called after the ChannelHandler was added to the actual context and it's ready to handle events. If override this method ensure you call super!

```java
@Override
public void handlerAdded(ChannelHandlerContext ctx) throws Exception {
    if (ctx.channel().isRegistered()) {
        // This should always be true with our current DefaultChannelPipeline implementation.
        // The good thing about calling initChannel(...) in handlerAdded(...) is that there will be no ordering
        // surprises if a ChannelInitializer will add another ChannelInitializer. This is as all handlers will be added in the expected order.
        if (initChannel(ctx)) {
            // We are done with init the Channel, removing the initializer now.
            removeState(ctx);
        }
    }
}
```



Calls ChannelHandlerContext.fireChannelRegistered() to forward to the next ChannelInboundHandler in the ChannelPipeline. Sub-classes may override this method to change behavior.

```java
@Override
@SuppressWarnings("unchecked")
public final void channelRegistered(ChannelHandlerContext ctx) throws Exception {
    // Normally this method will never be called as handlerAdded(...) should call initChannel(...) and remove
    // the handler.
    if (initChannel(ctx)) {
        // we called initChannel(...) so we need to call now pipeline.fireChannelRegistered() to ensure we not
        // miss an event.
        ctx.pipeline().fireChannelRegistered();

        // We are done with init the Channel, removing all the state for the Channel now.
        removeState(ctx);
    } else {
        // Called initChannel(...) before which is the expected behavior, so just forward the event.
        ctx.fireChannelRegistered();
    }
}
```
