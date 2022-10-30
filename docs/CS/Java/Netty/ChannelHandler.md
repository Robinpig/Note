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

## ChannelHandler

Handles an I/O event or intercepts an I/O operation, and forwards it to its next handler in its ChannelPipeline.

**Sub-types**

ChannelHandler itself does not provide many methods, but you usually have to implement one of its subtypes:

- ChannelInboundHandler to handle inbound I/O events, and
- ChannelOutboundHandler to handle outbound I/O operations.

Alternatively, the following adapter classes are provided for your convenience:

- ChannelInboundHandlerAdapter to handle inbound I/O events,
- ChannelOutboundHandlerAdapter to handle outbound I/O operations, and
- ChannelDuplexHandler to handle both inbound and outbound events

For more information, please refer to the documentation of each subtype.

**The context object**

A ChannelHandler is provided with a ChannelHandlerContext object.
A ChannelHandler is supposed to interact with the ChannelPipeline it belongs to via a context object.
Using the context object, the ChannelHandler can pass events upstream or downstream, modify the pipeline dynamically, or store the information (using AttributeKeys) which is specific to the handler.

**State management**

A ChannelHandler often needs to store some stateful information. The simplest and recommended approach is to use member variables:

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

**Using AttributeKeys**

Although it's recommended to use member variables to store the state of a handler, for some reason you might not want to create many handler instances.
In such a case, you can use AttributeKeys which is provided by ChannelHandlerContext:

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

Now that the state of the handler is attached to the ChannelHandlerContext, you can add the same handler instance to different pipelines:

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

In the example above which used an AttributeKey, you might have noticed the `@Sharable` annotation.

If a ChannelHandler is annotated with the `@Sharable` annotation, it means you can create an instance of the handler just once and add it to one or more ChannelPipelines multiple times without a race condition.

If this annotation is not specified, you have to create a new handler instance every time you add it to a pipeline because it has unshared state such as member variables.

This annotation is provided for documentation purpose, just like [the JCIP annotations](http://www.javaconcurrencyinpractice.com/annotations/doc/).

**Additional resources worth reading**

Please refer to the ChannelHandler, and ChannelPipeline to find out more about inbound and outbound operations, what fundamental differences they have, how they flow in a pipeline, and how to handle the operation in your application.

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

### inbound

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

#### HeadContext

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

#### SimpleChannelInboundHandler

release automatically

### outbound

tail -> head

#### TailContext

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

##### addMessage

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

##### addFlush

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

#### flush

ChannelDuplexHandler which consolidates Channel.flush() / ChannelHandlerContext.flush() operations
(which also includes Channel.writeAndFlush(Object) / Channel.writeAndFlush(Object, ChannelPromise)
and ChannelOutboundInvoker.writeAndFlush(Object) / ChannelOutboundInvoker.writeAndFlush(Object, ChannelPromise)).

Flush operations are generally speaking expensive as these may trigger a syscall on the transport level.
Thus it is in most cases (where write latency can be traded with throughput) a good idea to try to minimize flush operations as much as possible.

If a read loop is currently ongoing, flush(ChannelHandlerContext) will not be passed on to the next ChannelOutboundHandler in the ChannelPipeline,
as it will pick up any pending flushes when channelReadComplete(ChannelHandlerContext) is triggered.
If no read loop is ongoing, the behavior depends on the consolidateWhenNoReadInProgress constructor argument:

- if false, flushes are passed on to the next handler directly;
- if true, the invocation of the next handler is submitted as a separate task on the event loop. Under high throughput,
  this gives the opportunity to process other flushes before the task gets executed, thus batching multiple flushes into one.

If explicitFlushAfterFlushes is reached the flush will be forwarded as well (whether while in a read loop, or while batching outside of a read loop).

If the Channel becomes non-writable it will also try to execute any pending flush operations.

> The FlushConsolidationHandler should be put as first ChannelHandler in the ChannelPipeline to have the best effect.

```java
public class FlushConsolidationHandler extends ChannelDuplexHandler {
    private final int explicitFlushAfterFlushes;
    private final boolean consolidateWhenNoReadInProgress;
    private final Runnable flushTask;


    @Override
    public void flush(ChannelHandlerContext ctx) throws Exception {
        if (readInProgress) {
            // If there is still a read in progress we are sure we will see a channelReadComplete(...) call. Thus
            // we only need to flush if we reach the explicitFlushAfterFlushes limit.
            if (++flushPendingCount == explicitFlushAfterFlushes) {
                flushNow(ctx);
            }
        } else if (consolidateWhenNoReadInProgress) {
            // Flush immediately if we reach the threshold, otherwise schedule
            if (++flushPendingCount == explicitFlushAfterFlushes) {
                flushNow(ctx);
            } else {
                scheduleFlush(ctx);
            }
        } else {
            // Always flush directly
            flushNow(ctx);
        }
    }

    private void scheduleFlush(final ChannelHandlerContext ctx) {
        if (nextScheduledFlush == null) {
            // Run as soon as possible, but still yield to give a chance for additional writes to enqueue.
            nextScheduledFlush = ctx.channel().eventLoop().submit(flushTask);
        }
    }

    @Override
    public void channelReadComplete(ChannelHandlerContext ctx) throws Exception {
        // This may be the last event in the read loop, so flush now!
        resetReadAndFlushIfNeeded(ctx);
        ctx.fireChannelReadComplete();
    }
  
    private void resetReadAndFlushIfNeeded(ChannelHandlerContext ctx) {
        readInProgress = false;
        flushIfNeeded(ctx);
    }
}
```

## Frame detection

ByteToMessageDecoder decodes bytes in a stream-like fashion from one ByteBuf to an other Message type.

Generally frame detection should be handled earlier in the pipeline by adding a `DelimiterBasedFrameDecoder`, `FixedLengthFrameDecoder`, `LengthFieldBasedFrameDecoder`, or `LineBasedFrameDecoder`.

If a custom frame decoder is required, then one needs to be careful when implementing one with ByteToMessageDecoder. Ensure there are enough bytes in the buffer for a complete frame by checking ByteBuf.readableBytes().
If there are not enough bytes for a complete frame, return without modifying the reader index to allow more bytes to arrive.

To check for complete frames without modifying the reader index, use methods like ByteBuf.getInt(int). One MUST use the reader index when using methods like ByteBuf.getInt(int).
For example calling in.getInt(0) is assuming the frame starts at the beginning of the buffer, which is not always the case. Use in.getInt(in.readerIndex()) instead.

> [!TIP]
> Be aware that sub-classes of ByteToMessageDecoder MUST NOT annotated with <font color='red'>@Sharable</font>.
>
> Some methods such as <font color='red'>ByteBuf.readBytes(int)</font> will cause a memory leak if the returned buffer is not released or added to the out List.
> Use derived buffers like <font color='blue'>ByteBuf.readSlice(int)</font> to avoid leaking memory.

channelRead -> callDecode -> decodeRemovalReentryProtection -> decode

### cumulate

cumulate before callDecode

```java
 public interface Cumulator {
        /**
         * Cumulate the given {@link ByteBuf}s and return the {@link ByteBuf} that holds the cumulated bytes.
         * The implementation is responsible to correctly handle the life-cycle of the given {@link ByteBuf}s and so
         * call {@link ByteBuf#release()} if a {@link ByteBuf} is fully consumed.
         */
        ByteBuf cumulate(ByteBufAllocator alloc, ByteBuf cumulation, ByteBuf in);
}
```

- memcopy default
- composite

MessageToMessageDecoder decodes from one message to an other message.

## Traffic

- ChannelTrafficShapingHandler
- GlobalTrafficShapingHandler
- GlobalChannelTrafficShapingHandler

set autoRead = false and schedule ReopenReadTimerTask

```java
public abstract class AbstractTrafficShapingHandler extends ChannelDuplexHandler {
  @Override
  public void channelRead(final ChannelHandlerContext ctx, final Object msg) throws Exception {
    long size = calculateSize(msg);
    long now = TrafficCounter.milliSecondFromNano();
    if (size > 0) {
      // compute the number of ms to wait before reopening the channel
      long wait = trafficCounter.readTimeToWait(size, readLimit, maxTime, now);
      wait = checkWaitReadTime(ctx, wait, now);
      if (wait >= MINIMAL_WAIT) { // At least 10ms seems a minimal
        // time in order to try to limit the traffic
        // Only AutoRead AND HandlerActive True means Context Active
        Channel channel = ctx.channel();
        ChannelConfig config = channel.config();

        if (config.isAutoRead() && isHandlerActive(ctx)) {
          config.setAutoRead(false);
          channel.attr(READ_SUSPENDED).set(true);
          // Create a Runnable to reactive the read if needed. If one was create before it will just be
          // reused to limit object creation
          Attribute<Runnable> attr = channel.attr(REOPEN_TASK);
          Runnable reopenTask = attr.get();
          if (reopenTask == null) {
            reopenTask = new ReopenReadTimerTask(ctx);
            attr.set(reopenTask);
          }
          ctx.executor().schedule(reopenTask, wait, TimeUnit.MILLISECONDS);
        }
      }
    }
    informReadOperation(ctx, now);
    ctx.fireChannelRead(msg);
  }
}
```

## Idle

### IdleStateHandler

IdleStateHandler triggers an IdleStateEvent when a Channel has not performed read, write, or both operation for a while.

Supported idle states:


| Property       | Meaning                                                                                                                                                                      |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| readerIdleTime | an IdleStateEvent whose state is IdleState.READER_IDLE will be triggered when no read was performed for the specified period of time.<br />Specify 0 to disable.             |
| writerIdleTime | an IdleStateEvent whose state is IdleState.WRITER_IDLE will be triggered when no write was performed for the specified period of time.<br />Specify 0 to disable.            |
| allIdleTime    | an IdleStateEvent whose state is IdleState.ALL_IDLE will be triggered when neither read nor write was performed for the specified period of time.<br />Specify 0 to disable. |

```java
public class IdleStateHandler extends ChannelDuplexHandler {
    public IdleStateHandler(
            long readerIdleTime, long writerIdleTime, long allIdleTime,
            TimeUnit unit) {
        this(false, readerIdleTime, writerIdleTime, allIdleTime, unit);
    }

    // This method will be invoked only if this handler was added before channelActive() event is fired.
    private void initialize(ChannelHandlerContext ctx) {
      // Avoid the case where destroy() is called before scheduling timeouts.
      // See: https://github.com/netty/netty/issues/143
      switch (state) {
        case 1:
        case 2:
          return;
        default:
          break;
      }
  
      state = 1;
      initOutputChanged(ctx);
  
      lastReadTime = lastWriteTime = ticksInNanos();
      if (readerIdleTimeNanos > 0) {
        readerIdleTimeout = schedule(ctx, new ReaderIdleTimeoutTask(ctx),
                readerIdleTimeNanos, TimeUnit.NANOSECONDS);
      }
      if (writerIdleTimeNanos > 0) {
        writerIdleTimeout = schedule(ctx, new WriterIdleTimeoutTask(ctx),
                writerIdleTimeNanos, TimeUnit.NANOSECONDS);
      }
      if (allIdleTimeNanos > 0) {
        allIdleTimeout = schedule(ctx, new AllIdleTimeoutTask(ctx),
                allIdleTimeNanos, TimeUnit.NANOSECONDS);
      }
    }
}
```

override userEventTriggered method and reply IdleStateEvent


| IdleState   | Task                  | Handler            | Handler Description                                                                  |
| ------------- | ----------------------- | -------------------- | -------------------------------------------------------------------------------------- |
| READER_IDLE | ReaderIdleTimeoutTask | ReadTimeoutHandler | Raises a ReadTimeoutException when no data was read within a certain period of time. |
| WRITER_IDLE | WriterIdleTimeoutTask |                    |                                                                                      |
| ALL_IDLE    | AllIdleTimeoutTask    |                    |                                                                                      |

WriteTimeoutHandler Raises a WriteTimeoutException when a write operation cannot finish in a certain period of time.

### WriteTimeoutHandler

## Filter

## Log

- The default factory is *Slf4JLoggerFactory*.
- If SLF4J is not available, *Log4JLoggerFactory* is used.
- If Log4J is not available, *JdkLoggerFactory* is used.
-

You can change it to your preferred logging framework before other Netty classes are loaded: `InternalLoggerFactory.setDefaultFactory(Log4JLoggerFactory.INSTANCE)`;

> [!NOTE]
>
> The new default factory is effective only for the classes which were loaded after the default factory is changed.
> Therefore, setDefaultFactory(InternalLoggerFactory) should be called as early as possible and shouldn't be called more than once.

## Links

- [Netty](/docs/CS/Java/Netty/Netty.md)
