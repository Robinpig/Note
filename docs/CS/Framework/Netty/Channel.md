## Introduction

Channel 是网络通信的载体，提供 register / bind / connect / read / write / close 等异步 API。Netty 的 Channel 以 JDK `SelectableChannel` 为基础做了更高层的抽象：状态机、生命周期回调、Pipeline、Unsafe 等。

本文以 **Netty 4.2.19.Final** 源码为准。4.2 在 transport 层做了自 4.0 以来最大的一次重构：把 IO 多路复用循环从 EventLoop 抽到 IoHandler、注册路径从直接操作 `SelectionKey` 改成 IoRegistration/IoOps 抽象——这些变化都直接影响 Channel 的实现。

### Channel Hierarchy

`AbstractChannel` 是整个家族的基类，派生出 `AbstractNioChannel`（NIO / epoll / kqueue / io_uring 共通父类）和其它 IO 模型子类。常用实现：

- `NioServerSocketChannel` / `NioSocketChannel` —— NIO TCP
- `EpollServerSocketChannel` / `EpollSocketChannel` —— Linux epoll
- `KQueueServerSocketChannel` / `KQueueSocketChannel` —— macOS / BSD kqueue
- `IoUringServerSocketChannel` / `IoUringSocketChannel` —— Linux io_uring
- `NioDatagramChannel` —— UDP

> [!WARNING]
>
> OIO（`io.netty.channel.socket.oio`，基于 `java.net.Socket` 的同步 IO）整个包自 4.1 起 `@Deprecated`。4.2 中 `NioEventLoopGroup` / `EpollEventLoopGroup` / `KQueueEventLoopGroup` / `IoUringEventLoopGroup` 也全部 `@Deprecated`，统一改用 `MultiThreadIoEventLoopGroup` + `IoHandlerFactory`——见 [EventLoop](/docs/CS/Framework/Netty/EventLoop.md) 与 [Transport](/docs/CS/Framework/Netty/Transport.md)。

## Channel

`Channel extends AttributeMap, ChannelOutboundInvoker, Comparable<Channel>`。

4.2 一个重要变化：接口中 **I/O 操作方法从 abstract 改成了 default 方法**——全部委托给 `ChannelPipeline`：

```java
// ChannelOutboundInvoker 默认实现（4.2 新增 default）
default ChannelFuture writeAndFlush(Object msg) {
    return pipeline().writeAndFlush(msg);
}
default ChannelFuture close() {
    return pipeline().close();
}
// 同理：write() / read() / flush() / bind() / connect() / disconnect() / deregister()
// 也包括 getOption() / setOption() / alloc() —— 全部 default 委托
```

这样做的好处：新 transport 实现 Channel 时**不需要再覆盖这些 outbound 方法**（它们本来就该走 pipeline），子类只需实现 Unsafe 里的 transport-specific 方法。接口的职责被收缩为"状态查询 + outbound 委托 + unsafe 入口"。

核心状态方法（仍为 abstract，由 AbstractChannel 实现）：

| 方法 | 语义 |
| :--- | :--- |
| `id()` | ChannelId（唯一标识，toString 里会输出） |
| `eventLoop()` | 注册到的 EventLoop，未注册时抛 `IllegalStateException` |
| `isOpen()` | 底层 fd 是否打开 |
| `isRegistered()` | 是否已向 EventLoop 注册 |
| `isActive()` | 是否已连接/绑定（具体语义 transport 自定） |
| `isWritable()` | 写缓冲水位是否低于 `WriteBufferWaterMark` 下限 |

### writability 三件套

4.2 中 `isWritable()`、`bytesBeforeUnwritable()`、`bytesBeforeWritable()` 三个也变成了 default，委托给 `unsafe().outboundBuffer()`：

```java
default boolean isWritable() {
    ChannelOutboundBuffer buf = unsafe().outboundBuffer();
    return buf != null && buf.isWritable();
}
default long bytesBeforeUnwritable() {
    ChannelOutboundBuffer buf = unsafe().outboundBuffer();
    return buf != null ? buf.bytesBeforeUnwritable() : 0;
}
default long bytesBeforeWritable() {
    ChannelOutboundBuffer buf = unsafe().outboundBuffer();
    return buf != null ? buf.bytesBeforeWritable() : Long.MAX_VALUE;
}
```

### SocketChannel 读写字节路径

子类实现的三个抽象"真正搬字节"的方法（与 4.1 相比没本质变化）：

```java
// NioSocketChannel —— 读
@Override
protected int doReadBytes(ByteBuf byteBuf) throws Exception {
    RecvByteBufAllocator.Handle allocHandle = unsafe().recvBufAllocHandle();
    allocHandle.attemptedBytesRead(byteBuf.writableBytes());
    return byteBuf.writeBytes(javaChannel(), allocHandle.attemptedBytesRead());
}

// NioSocketChannel —— 写
@Override
protected int doWriteBytes(ByteBuf buf) throws Exception {
    return buf.readBytes(javaChannel(), buf.readableBytes());
}
@Override
protected long doWriteFileRegion(FileRegion region) throws Exception {
    return region.transferTo(javaChannel(), region.transferred());
}
```

### ServerSocketChannel accept

```java
// NioServerSocketChannel —— doReadMessages
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
        try { ch.close(); } catch (Throwable t2) {
            logger.warn("Failed to close a socket.", t2);
        }
    }
    return 0;
}
```

注意：4.2 中 `doWrite()`（单写/批量写）、`doReadBytes()` / `doWriteBytes()` 这些**不叫 doRead / doWrite**——`Unsafe.read()` / `Unsafe.flush()` 才是对外的调度入口，它们内部循环调用 `doReadBytes` / `doWriteBytes`。

## Unsafe

`Channel.Unsafe` 是 Channel 内部专属的 transport 操作接口，**所有方法都必须在 EventLoop 线程调用**（localAddress / remoteAddress / closeForcibly / register / deregister / voidPromise 例外）。4.2 中接口定义本身没有大改动，但 `AbstractUnsafe` 基类的 register 实现**完全重写**以适配 IoHandler 抽象。

### AbstractUnsafe.register（4.2 新增 contextExecutor 清理）

```java
@Override
public final void register(EventLoop eventLoop, final ChannelPromise promise) {
    ObjectUtil.checkNotNull(eventLoop, "eventLoop");
    if (isRegistered()) {
        promise.setFailure(new IllegalStateException("registered to an event loop already"));
        return;
    }
    if (!isCompatible(eventLoop)) {
        promise.setFailure(new IllegalStateException(
                "incompatible event loop type: " + eventLoop.getClass().getName()));
        return;
    }
    AbstractChannel.this.eventLoop = eventLoop;

    // 4.2 新增：遍历 pipeline 清掉跨 eventLoop 注册的 contextExecutor
    AbstractChannelHandlerContext context = pipeline.tail;
    do {
        context.contextExecutor = null;
        context = context.prev;
    } while (context != null);

    if (eventLoop.inEventLoop()) {
        register0(promise);
    } else {
        eventLoop.execute(new Runnable() {
            @Override public void run() { register0(promise); }
        });
    }
}
```

### register register0 doRegister 4.2 IoHandler 化

`AbstractUnsafe.register` 是所有 bootstrap 最终落地的注册入口。4.2 在 `register0()` 里加了一层**嵌套 Promise**——因为 `doRegister()` 在 4.2 变成了异步的（IoHandler 注册返回的是 Future）：

```java
private void register0(ChannelPromise promise) {
    if (!promise.setUncancellable() || !ensureOpen(promise)) {
        return;
    }
    ChannelPromise registerPromise = newPromise();  // ← 4.2 新增中间 Promise
    boolean firstRegistration = neverRegistered;
    registerPromise.addListener(future -> {
        if (future.isSuccess()) {
            neverRegistered = false;
            registered = true;
            pipeline.invokeHandlerAddedIfNeeded();
            safeSetSuccess(promise);
            pipeline.fireChannelRegistered();
            if (isActive()) {
                if (firstRegistration) {
                    pipeline.fireChannelActive();
                } else if (config().isAutoRead()) {
                    beginRead();
                }
            }
        } else {
            close(newPromise());  // 失败直接 close 防 FD leak
            closeFuture.setClosed();
            safeSetFailure(promise, future.cause());
        }
    });
    doRegister(registerPromise);
}
```

AbstractNioChannel 的 `doRegister()` 实现（4.2 重写）：

```java
@Override
protected void doRegister(ChannelPromise promise) {
    assert registration == null;
    ((IoEventLoop) eventLoop()).register((AbstractNioUnsafe) unsafe())
        .addListener(f -> {
            if (f.isSuccess()) {
                registration = (IoRegistration) f.getNow();
                promise.setSuccess();
            } else {
                promise.setFailure(f.cause());
            }
        });
}
```

4.1 → 4.2 的关键差异：

| 维度 | 4.1 | 4.2 |
| :--- | :--- | :--- |
| `doRegister` 阻塞性 | 同步返回（SelectionKey 立即可用） | 异步 Promise（IoHandler 线程上完成） |
| Attachment | `javaChannel().register(selector, 0, this)`，attachment 是 Netty Channel | `NioIoHandler.register(unsafe)` 返回 `DefaultNioRegistration`；`selectionKey()` 标 `@Deprecated`，替代是 `registration().attachment()` |
| 注册桥接 | 无中间层 | `AbstractNioChannel.registration` 字段（`volatile IoRegistration`），submit / cancel 全部委托它 |
| 跨 eventLoop 重新注册 | 无清理 | 4.2 新增：`register()` 遍历 pipeline 清 `contextExecutor = null` |

### handle(IoRegistration, IoEvent) — 4.2 新增核心回调

IoHandler 侧 select 到就绪事件时，回调 `NioIoHandle.handle(...)`：

```java
@Override
public void handle(IoRegistration registration, IoEvent event) {
    NioIoOps nioReadyOps = ((NioIoEvent) event).ops();
    // 1. 先 finishConnect —— 否则 JDK NIO 会抛 NotYetConnectedException
    if (nioReadyOps.contains(NioIoOps.CONNECT)) {
        removeAndSubmit(NioIoOps.CONNECT);
        unsafe().finishConnect();
    }
    // 2. 再 WRITE —— 优先清空写队列释放内存
    if (nioReadyOps.contains(NioIoOps.WRITE)) {
        forceFlush();
    }
    // 3. 最后 READ_AND_ACCEPT（READ_AND_ACCEPT 或 NONE，NONE 是 workaround JDK 空轮询）
    if (nioReadyOps.contains(NioIoOps.READ_AND_ACCEPT) || nioReadyOps.equals(NioIoOps.NONE)) {
        read();
    }
}
```

跨 transport 注册路径与状态维护的完整链条在 [Transport](/docs/CS/Framework/Netty/Transport.md) 的 IoHandler 抽象章节。

### addAndSubmit / removeAndSubmit（4.2 新增）

`AbstractNioChannel` 的两个 protected 辅助方法，封装 Ops 位操作：

```java
protected void addAndSubmit(NioIoOps addOps) {
    int interestOps = selectionKey().interestOps();
    if (!addOps.isIncludedIn(interestOps)) {
        registration().submit(NioIoOps.valueOf(interestOps).with(addOps));
    }
}
protected void removeAndSubmit(NioIoOps removeOps) {
    int interestOps = selectionKey().interestOps();
    if (removeOps.isIncludedIn(interestOps)) {
        registration().submit(NioIoOps.valueOf(interestOps).without(removeOps));
    }
}
```

这两个方法内部用 `selectionKey().interestOps()` 读当前兴趣位，用 `registration().submit(...)` 写新位——epoll/kqueue/io_uring 的实现把 submit 委托给各自 registration 的状态机/changeList/SQE 入队，Channel 代码不感知差异。

### beginRead

调用 readPending 置位 + addAndSubmit 注册读 ops：

```java
@Override
protected void doBeginRead() throws Exception {
    IoRegistration registration = this.registration;
    if (registration == null || !registration.isValid()) {
        return;
    }
    readPending = true;
    addAndSubmit(readOps);  // readOps 是构造器传入的 NioIoOps.valueOf(readInterestOp)
}
```

注意 `readOps` 在 4.2 变成 `NioIoOps`（不再是裸 int），构造时 `readInterestOp`（int）和 `readOps`（NioIoOps）两个字段都存了。

### close

4.2 中 `close(ChannelPromise)` 基本骨架没变，但有几处关键更新：

```java
@Override
public void close(final ChannelPromise promise) {
    assertEventLoop();
    ClosedChannelException ex = StacklessClosedChannelException.newInstance(AbstractChannel.class, "...");
    close(promise, ex, ex);
}
```

- **`StacklessClosedChannelException`**：4.2 引入的"无栈"异常，`ClosedChannelException` 不再分配完整栈帧，减少高频 close 场景的分配开销。
- 内部 `close(...)` 逻辑与 4.1 一致：`closeInitiated` CAS、outboundBuffer 置 null、`prepareToClose()` 钩子（子类返回 Executor 时 close 在那个 executor 执行）、inFlush0 里 `invokeLater` 延迟 fireChannelInactiveAndDeregister。
- `AbstractNioChannel.doClose()` 在 4.2 里**不再关 socket**——只清 `connectPromise` / `connectTimeoutFuture`；真正的 `javaChannel().close()` 交给 `AbstractNioChannel.doDeregister()` 在注册取消时调用。这是为了让 `SO_LINGER` half-closure 场景能先 shutdown 再让内核自动关 fd。

### shutdownOutput（4.2 新增）

优雅写半关闭：

```java
public final void shutdownOutput(final ChannelPromise promise) {
    assertEventLoop();
    if (!promise.setUncancellable()) return;
    final ChannelOutboundBuffer outboundBuffer = this.outboundBuffer;
    if (outboundBuffer == null) { promise.setFailure(new ClosedChannelException()); return; }
    this.outboundBuffer = null;

    final Throwable shutdownCause = cause == null ?
            new ChannelOutputShutdownException("Channel output shutdown") :
            new ChannelOutputShutdownException("Channel output shutdown", cause);
    try {
        doShutdownOutput();
        promise.setSuccess();
    } catch (Throwable err) {
        promise.setFailure(err);
    } finally {
        buffer.failFlushed(cause, false);
        buffer.close(cause, true);
        pipeline.fireUserEventTriggered(ChannelOutputShutdownEvent.INSTANCE);
    }
}
```

源码注释明确前提：SO_LINGER 场景下不能在 shutdownOutput 里做 `doDeregister()`，因为 FIN_WAIT2 状态的侧还要继续收 `CLOSE_WAIT` 侧发来的数据。

### finishConnect

```java
// AbstractNioChannel$AbstractNioUnsafe
@Override
public final void finishConnect() {
    assert eventLoop().inEventLoop();
    try {
        boolean wasActive = isActive();
        doFinishConnect();
        fulfillConnectPromise(connectPromise, wasActive);
    } catch (Throwable t) {
        fulfillConnectPromise(connectPromise, annotateConnectException(t, requestedRemoteAddress));
    } finally {
        if (connectTimeoutFuture != null) {
            connectTimeoutFuture.cancel(false);
        }
        connectPromise = null;
    }
}

private void fulfillConnectPromise(ChannelPromise promise, boolean wasActive) {
    if (promise == null) return;  // 用户已 cancel
    boolean active = isActive();
    boolean promiseSet = promise.trySuccess();
    if (!wasActive && active) {
        pipeline().fireChannelActive();  // 无论成功失败，channelActive 都应触发
    }
    if (!promiseSet) {
        close(voidPromise());  // 用户取消了 → close
    }
}
```

注释解释了一个微妙设计：`trySuccess()` 会返回 false 如果用户已经取消连接；无论 promise 是否被取消，`channelActive` 事件都必须触发（"what happened is what happened"）——因为 socket 确实连接成功了，用户只是不想等了。

### flush0 / forceFlush

```java
// 4.2 NioUnsafe 新增
@Override
protected final void flush0() {
    if (!isFlushPending()) {
        super.flush0();
    }
}
private boolean isFlushPending() {
    return registration.isValid() && NioIoOps.WRITE.isIncludedIn(
            ((SelectionKey) registration.attachment()).interestOps());
}
```

flush0 默认只在没有 OP_WRITE 兴趣集挂起时才真正 flush；若 OP_WRITE 已挂，说明上一次 flush 队列还没清完，就让 EpollIoHandler 的事件循环统一 forceFlush——避免重复 flush 造成 writeSpinCount 溢出。

## ChannelConfig

Channel 的配置接口，`AbstractChannel.config()` 返回的是子类实现（`NioSocketChannelConfig` / `EpollSocketChannelConfig` 等）。

4.2 中 `DefaultChannelConfig` 有两个关键变更：

### maxMessagesPerRead 已 Deprecated

```java
@Deprecated
int getMaxMessagesPerRead();           // 委托给 MaxMessagesRecvByteBufAllocator.maxMessagesPerRead()
@Deprecated
ChannelConfig setMaxMessagesPerRead(int maxMessagesPerRead);
```

读循环每次循环读多少条消息，统一交给 `MaxMessagesRecvByteBufAllocator.maxMessagesPerRead()`——读端配置和 ByteBuf 分配器不再解耦。

### maxMessagesPerWrite（4.2 新增）

配套引入的 `MAX_MESSAGES_PER_WRITE` 选项。`AbstractChannel.maxMessagesPerWrite()` 优先查 `DefaultChannelConfig`，否则读 option，默认 `Integer.MAX_VALUE`。影响写侧每次 flush 循环最多处理多少 Entry。

### WriteBufferWaterMark

水位线控制写缓冲溢出前 Channel.isWritable() 的切换：

```java
public final class WriteBufferWaterMark {
    private static final int DEFAULT_LOW_WATER_MARK = 32 * 1024;
    private static final int DEFAULT_HIGH_WATER_MARK = 64 * 1024;
    public static final WriteBufferWaterMark DEFAULT =
            new WriteBufferWaterMark(DEFAULT_LOW_WATER_MARK, DEFAULT_HIGH_WATER_MARK, false);
}
```

语义：排队字节数超过 `high` → `isWritable() = false`；降到 `low` 以下 → 重新变 true。两条边不相等是为了 hysteresis，防止在水位附近抖动。

### writeSpinCount

`DefaultChannelConfig.writeSpinCount` 默认 **16**，控制单次 flush 循环内 `doWrite` 最多重试多少次。exhaust 后走 `incompleteWrite(writeSpinCount < 0)`：负表示内核暂不可写，注册 OP_WRITE；零表示没发完但 socket 仍可写，丢一个 flushTask 稍后重试。

## Links

- [Netty](/docs/CS/Framework/Netty/Netty.md)
- [Transport 与 IoHandler 抽象](/docs/CS/Framework/Netty/Transport.md)
- [EventLoop 与线程模型](/docs/CS/Framework/Netty/EventLoop.md)
- [ChannelPipeline 与 Handler](/docs/CS/Framework/Netty/ChannelHandler.md)
- [ChannelOutboundBuffer 写背压](/docs/CS/Framework/Netty/ChannelHandler.md?id=channeloutboundbuffer)
- [Future and Promise](/docs/CS/Framework/Netty/Future.md)
- [Bootstrap](/docs/CS/Framework/Netty/Bootstrap.md)

## References

1. [Netty 4.2 Javadoc — Channel](https://netty.io/4.2/api/io/netty/channel/Channel.html)
2. [Netty 4.2 Javadoc — AbstractChannel](https://netty.io/4.2/api/io/netty/channel/AbstractChannel.html)
3. [Netty 4.2 Javadoc — AbstractNioChannel](https://netty.io/4.2/api/io/netty/channel/nio/AbstractNioChannel.html)
4. [Netty 4.2.0 release notes](https://netty.io/news/2025/04/03/4-2-0.html)
5. [Netty #4805 — autoRead on re-register](https://github.com/netty/netty/issues/4805)
6. [Netty #11981 — SO_LINGER half-closure shutdownOutput](https://github.com/netty/netty/issues/11981)
7. [Netty #17103 — clearReadPending race](https://github.com/netty/netty/issues/17103)
