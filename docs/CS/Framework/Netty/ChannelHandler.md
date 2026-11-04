## Introduction

ChannelPipeline 是 Netty 的核心编排组件：入站事件（读、连接、active 等）从 HeadContext 向后传播到 TailContext；出站事件（write、flush、connect 等）从 TailContext 向前传播到 HeadContext。Pipeline 本身是一个双向链表，每个节点是 `AbstractChannelHandlerContext`——它既包裹用户实现的 `ChannelHandler`，又携带事件路由所需的执行器与类型掩码。

本文以 **Netty 4.2.19.Final** 源码为准。

## DefaultChannelPipeline

`Channel.pipeline()` 返回的实现。构造时就带着两个内置节点：

```java
protected DefaultChannelPipeline(Channel channel) {
    this.channel = ObjectUtil.checkNotNull(channel, "channel");
    succeededFuture = new SucceededChannelFuture(channel, null);
    voidPromise = new VoidChannelPromise(channel, true);
    tail = new TailContext(this);
    head = new HeadContext(this);
    head.next = tail;
    tail.prev = head;
}
```

### HeadContext

HeadContext 是 pipeline 里唯一一个**既实现 Inbound 又实现 Outbound** 的 handler：

- **Inbound 侧**：`channelActive` / `channelReadComplete` 末尾调 `readIfIsAutoRead()`（autoRead=true 时自动 beginRead）；`channelRegistered` 里调 `invokeHandlerAddedIfNeeded()`——把 channel 注册前挂起的 `handlerAdded` 回调链一次性触发（见 callHandlerAddedForAllHandlers）
- **Outbound 侧**：全部直接转 `unsafe.xxx()`——它是 pipeline 与 transport 层的最后一环
- `channelUnregistered` 里判断 `!channel.isOpen()` 则调 `destroy()` 清理全部 handler（destroyUp / destroyDown 两段式遍历）

### TailContext

纯 Inbound。所有未被用户 handler 消费的事件在这里兜底：`channelRead` → `onUnhandledInboundMessage`（warn + release）；`exceptionCaught` → `onUnhandledInboundException`（warn + release）；`userEventTriggered` → 只 release 不 log（因为 user event 可能是多余的）。

### destroy（两段式遍历）

```java
private synchronized void destroy() {
    destroyUp(head.next, false);     // 先正向下遍历到 tail
}
private void destroyUp(AbstractChannelHandlerContext ctx, boolean inEventLoop) { ... }
private void destroyDown(Thread currentThread, AbstractChannelHandlerContext ctx, boolean inEventLoop) {
    // 然后反向上从 tail.prev 遍历到 head
    ctx = ctx.prev;
    // atomicRemoveFromHandlerList(ctx) —— handlerRemoved 里可能又 remove 或 replace 了别的 handler，必须用 CAS 跳过已经被移除的
    // callHandlerRemoved0(ctx)
}
```

两段式遍历（up→down）是为了 **handlerRemoved 里注册的新事件能被前向处理完再 remove**——Issue #3156。`atomicRemoveFromHandlerList` 用 CAS，因为回调里别的 handlerRemoved 可能先把当前 ctx 从链里摘掉。

## ChannelHandler 添加与回调时机

### addFirst 的三种路径

```java
public final ChannelPipeline addFirst(EventExecutorGroup group, String name, ChannelHandler handler) {
    final AbstractChannelHandlerContext newCtx;
    synchronized (this) {
        checkMultiplicity(handler);      // ① sharable 检查
        name = filterName(name, handler); // ② 唯一性 + 自动命名
        newCtx = newContext(group, name, handler);
        addFirst0(newCtx);                // ③ 链表插入
        if (!registered) {
            newCtx.setAddPending();
            callHandlerCallbackLater(newCtx, true); // ④ 挂起：注册后再触发
            return this;
        }
        EventExecutor executor = newCtx.executor();
        if (!executor.inEventLoop()) {
            callHandlerAddedInEventLoop(newCtx, executor); // ⑤ 跨 executor：任务形式
            return this;
        }
    }
    callHandlerAdded0(newCtx); // ⑥ 同 executor 同步
    return this;
}
```

三条路径的语义：
- **未注册 channel**：handlerAdded 回调不立刻执行，`callHandlerCallbackLater` 把 ctx 扔进 `pendingHandlerCallbackHead` 链，等 HeadContext.channelRegistered 触发时一次性执行 `callHandlerAddedForAllHandlers`（必须在 synchronized 外跑，否则 handlerAdded 里再 add handler 会死锁）
- **已注册 + 同线程**：`callHandlerAdded0` 同步执行
- **已注册 + 跨 executor**：包装成 Runnable 扔进 ctx.executor.execute；RejectedExecutionException 时 warn + 直接 remove（`atomicRemoveFromHandlerList` + `ctx.setRemoved()`），不丢 handler 到悬空状态

### checkMultiplicity

```java
private static void checkMultiplicity(ChannelHandler handler) {
    if (handler instanceof ChannelHandlerAdapter) {
        ChannelHandlerAdapter h = (ChannelHandlerAdapter) handler;
        if (!h.isSharable() && h.added) {
            throw new IllegalStateException(
                    h.getClass().getName() + " is not a @Sharable handler, so can't be added or removed multiple times.");
        }
    }
}
```

`ChannelHandlerAdapter` 基类提供 `@Sharable` 注解（运行时反射读）和 `boolean added` 标记。每个 Channel 用的 handler 实例默认只能 add 到一个 pipeline；`@Sharable` 才能跨 Channel 复用。

### invokeHandlerAddedIfNeeded（4.2 新增）

```java
// HeadContext.channelRegistered 触发
private void invokeHandlerAddedIfNeeded() {
    assert channel.eventLoop().inEventLoop();
    if (!handlerAdded) {
        handlerAdded = true;
        callHandlerAddedForAllHandlers();
    }
}
```

4.2 把"注册前挂起的 handlerAdded 回调"的触发时机从 `AbstractChannel.register0()` 挪到了 HeadContext.channelRegistered——更合理的位置：它是 pipeline 自身事件链路的一部分，而非 Channel 注册流程的附属。

## ChannelHandlerContext

`AbstractChannelHandlerContext` 是 pipeline 双向链表的节点：

```java
// 关键字段（4.2）
private final DefaultChannelPipeline pipeline;
private final String name;
private final boolean ordered;             // executor 是否 OrderedEventExecutor
private final int executionMask;            // 表示实现了哪些 handler 方法的位图

final EventExecutor childExecutor;          // addXxx(group, ...) 传入的 executor
EventExecutor contextExecutor;              // 运行时缓存的 executor —— 4.2 新增
private Tasks invokeTasks;                  // invokeWrite / invokeFlush 等 Runnable 池 —— 4.2 新增
private volatile int handlerState = INIT;   // INIT → ADD_PENDING → ADD_COMPLETE / REMOVE_COMPLETE（4.2 新增）
```

### executor() 缓存（4.2 优化）

```java
@Override
public EventExecutor executor() {
    EventExecutor ex = contextExecutor;
    if (ex == null) {
        contextExecutor = ex = childExecutor != null ? childExecutor : channel().eventLoop();
    }
    return ex;
}
```

热路径上避免每次都做 `childExecutor != null ? childExecutor : channel().eventLoop()` 的链式依赖读取。**deregister 时必须清 null**（Channel.md `AbstractUnsafe.register` 里也有对应的遍历清理）。

### handlerState 状态机

```java
private static final int INIT = 0;
private static final int ADD_PENDING = 1;
private static final int ADD_COMPLETE = 2;
private static final int REMOVE_COMPLETE = 3;
```

`setAddComplete` 用 CAS：**只能从 INIT/ADD_PENDING 进入 ADD_COMPLETE**——如果 CAS 发现 `REMOVE_COMPLETE`，说明 handlerRemoved 已经被触发过（非 OrderedEventExecutor 的竞态），此时 setAddComplete 返回 false，后续流程跳过。

## ChannelInitializer —— 一次性 init 后自摘除

`ChannelInitializer<C extends Channel>` 是 Bootstrap 提供的抽象 handler，用户继承实现 `initChannel(C ch)`，Bootstrap 在 Channel 注册到 EventLoop 后自动调用，调用完立刻从 pipeline 自摘除。

**必须标 `@Sharable`**（源码类级别就有）——Bootstrap / ServerBootstrap 会把同一个 ChannelInitializer 实例复用到**每一个新建的 Channel** 上。initMap（`ConcurrentHashMap.newKeySet()`）就是为这种共享设计的：用 Set 跟踪已经 init 过哪些 ChannelHandlerContext，防止重入。

### 两条触发路径

```java
@Sharable
public abstract class ChannelInitializer<C extends Channel> extends ChannelInboundHandlerAdapter {

    private final Set<ChannelHandlerContext> initMap = ConcurrentHashMap.newKeySet();

    protected abstract void initChannel(C ch) throws Exception;

    // 路径 ①：handlerAdded 里触发（主要路径）
    @Override
    public void handlerAdded(ChannelHandlerContext ctx) throws Exception {
        if (ctx.channel().isRegistered()) {
            if (initChannel(ctx)) {
                removeState(ctx);
            }
        }
    }

    // 路径 ②：channelRegistered 里触发（fallback）
    @Override
    public final void channelRegistered(ChannelHandlerContext ctx) throws Exception {
        if (initChannel(ctx)) {
            ctx.pipeline().fireChannelRegistered();  // 补事件：handlerAdded 没调用过 channelRegistered
            removeState(ctx);
        } else {
            ctx.fireChannelRegistered();  // 正常 forward
        }
    }
}
```

注释说明为什么两条路径：`handlerAdded` 里 init 的好处是如果 initChannel 里**又加了另一个 ChannelInitializer**，所有 handler 都按正确顺序 add；但如果 channel 注册时 handler 才 add（例如 `addHandlerLater` 路径），就需要 channelRegistered 兜底。

### initChannel —— 防重入 + finally 移除

```java
private boolean initChannel(ChannelHandlerContext ctx) throws Exception {
    if (initMap.add(ctx)) {               // ① add 成功 → 第一次处理这个 ctx
        try {
            initChannel((C) ctx.channel());  // ② 用户实现
        } catch (Throwable cause) {
            exceptionCaught(ctx, cause);      // ③ 默认 close channel
        } finally {
            if (!ctx.isRemoved()) {
                ctx.pipeline().remove(this); // ④ 自摘除
            }
        }
        return true;
    }
    return false;  // ⑤ initMap 已存在 → 重入 → 不再 init
}
```

四个关键点：
- **initMap.add(ctx)** 是防重入哨兵——一个 ChannelInitializer 实例可能被 Bootstrap 复用到多个 Channel，但每个 ctx 只走一次 init
- **finally 里 remove(this)**——保证无论 init 抛异常还是正常返回，ChannelInitializer 都从 pipeline 里消失。留在 pipeline 里没意义了（它的所有 handlerAdded 回调都执行完了）
- **ctx.isRemoved() 检查**——ctx 在 offloaded EventExecutor 上可能已经被 remove 过了（handlerRemoved 里也会 remove），再 remove 会抛异常
- **exceptionCaught 默认 close channel**——init 阶段任何 handler 初始化失败，这个 Channel 直接废掉

### removeState 里的异步 ctx 清理

```java
private void removeState(final ChannelHandlerContext ctx) {
    if (ctx.isRemoved()) {
        initMap.remove(ctx);
    } else {
        // offloaded EventExecutor 场景下 ctx 移除可能还在排队
        ctx.executor().execute(() -> initMap.remove(ctx));
    }
}
```

注释明确前提：用户给 ChannelInitializer 配了自定义 EventExecutor（`pipeline.addLast(executor, new MyInit())`）时，handlerRemoved 回调不在 EventLoop 线程——此时 `ctx.isRemoved()` 返回 false（还没跑到 remove 那步），在 ctx.executor 上 execute 一次清理就一定能成功。

**ChannelInitializer 生命周期时序总结**：

```
Bootstrap.init(channel)
  → pipeline.addLast(new ChannelInitializer() { initChannel(ch) { ... } })
  → group.register(channel)
  → AbstractChannel.AbstractUnsafe.register0 → SingleThreadIoEventLoop.registerForIo0 → NioIoHandler.register
  → HeadContext.channelRegistered → callHandlerAddedForAllHandlers → handlerAdded(ChannelInitializer ctx)
  → ctx.channel().isRegistered() = true → initChannel(ChannelInitializer ctx)
  → initChannel((C) ctx.channel()) [用户实现]
  → finally: ctx.pipeline().remove(ChannelInitializer)  // 自摘除
  → channelRead / channelActive / ... → pipeline 里已经没有 ChannelInitializer 了
```



4.1 里 skipContext 的唯一条件是"目标 handler 不实现当前事件类型"；4.2 加了 executor 条件：

```java
private static boolean skipContext(
        AbstractChannelHandlerContext ctx, EventExecutor currentExecutor, int mask, int onlyMask) {
    // ① handler 本身不处理这类事件
    return (ctx.executionMask & (onlyMask | mask)) == 0 ||
        // ② handler 处理，但 executor 与当前不同 → 不能跳过，需要 offload 到它自己的 executor 以保序
        //    见 https://github.com/netty/netty/issues/10067
        (ctx.executor() == currentExecutor && (ctx.executionMask & mask) == 0);
}
```

Issue #10067 的场景：pipeline 里有跨 executor 的 handler，若它被跳过上一个非空 handler 的 offload 任务，事件顺序就乱了。

### 事件传播三步曲

以 `fireChannelActive`（入站）为例，三步固定：

```java
@Override
public ChannelHandlerContext fireChannelActive() {
    AbstractChannelHandlerContext next = findContextInbound(MASK_CHANNEL_ACTIVE); // ① 找下一个能处理的 ctx
    EventExecutor executor = next.executor();
    if (executor.inEventLoop()) {                    // ② executor 检查
        if (next.invokeHandler()) {                  // ③ 执行（区分 HeadContext / Duplex / Adapter / Interface）
            try {
                final ChannelHandler handler = next.handler();
                final DefaultChannelPipeline.HeadContext headContext = pipeline.head;
                if (handler == headContext) {
                    headContext.channelActive(next);
                } else if (handler instanceof ChannelInboundHandlerAdapter) {
                    ((ChannelInboundHandlerAdapter) handler).channelActive(next);
                } else {
                    ((ChannelInboundHandler) handler).channelActive(next);
                }
            } catch (Throwable t) {
                next.invokeExceptionCaught(t);
            }
        } else {
            next.fireChannelActive();  // invokeHandler 返回 false = handler 未 handlerAdded
        }
    } else {
        next.executor().execute(this::fireChannelActive);  // 跨 executor 递归 offload
    }
    return this;
}
```

4.2 源码注释里有 **"DON'T CHANGE"** 警告：ChannelDuplexHandler 同时实现 Inbound / Outbound 两个接口，若走 instanceof ChannelInboundHandler 的通用分支，JDK 的接口检查开销会被放大——所以特意把 HeadContext 和 Adapter 提前分支。

### Write 与 Flush（出站三步曲 + WriteTask）

```java
void write(Object msg, boolean flush, ChannelPromise promise) {
    if (validateWrite(msg, promise)) {
        final AbstractChannelHandlerContext next = findContextOutbound(
                flush ? MASK_WRITE | MASK_FLUSH : MASK_WRITE);
        final Object m = pipeline.touch(msg, next);
        EventExecutor executor = next.executor();
        if (executor.inEventLoop()) {
            // 同 executor 直接调 handler.write / handler.flush
            ...
        } else {
            // 跨 executor → Recycler.get() 拿 WriteTask（Issue #8343 失败时 cancel 递减 pendingBytes）
            final WriteTask task = WriteTask.newInstance(this, m, promise, flush);
            if (!safeExecute(executor, task, promise, m, !flush)) {
                task.cancel();  // 失败时必须减计数器并 recycle
            }
        }
    }
}
```

4.2 里 `WriteTask` 用 `Recycler` 池化，flush 任务也复用 `Tasks` 单例里的 `flushTask` / `readTask` / `fireChannelReadCompleteTask` / `fireChannelWritabilityChangedTask`——避免热路径上反复 new Runnable。

## ChannelOutboundBuffer

write 进 pipeline 后，最终落在 HeadContext.write → `unsafe.write(msg, promise)` → `AbstractChannel.AbstractUnsafe.write(...)`：

```java
@Override
public final void write(Object msg, ChannelPromise promise) {
    assertEventLoop();
    ChannelOutboundBuffer outboundBuffer = this.outboundBuffer;
    if (outboundBuffer == null) {  // 已 close
        ReferenceCountUtil.release(msg);
        safeSetFailure(promise, newClosedChannelException(...));
        return;
    }
    int size;
    try {
        msg = filterOutboundMessage(msg);          // heap → direct
        size = pipeline.estimatorHandle().size(msg); // 估算字节数
    } catch (Throwable t) {
        ReferenceCountUtil.release(msg);
        safeSetFailure(promise, t);
        return;
    }
    outboundBuffer.addMessage(msg, size, promise); // 入队
}
```

**只 write 不 flush，数据只在 buffer 里排队。** flush 才是真正触发 `doWrite()` 的动作。

### Entry 结构（96B / 条）

```java
// 每条排队消息被包成一个 Entry
static final int CHANNEL_OUTBOUND_BUFFER_ENTRY_OVERHEAD =
        SystemPropertyUtil.getInt("io.netty.transport.outboundBufferEntrySizeOverhead", 96);
```

96 字节 overhead 是 Entry 对象的固定内存占用（Object header + 8 字段引用/promise/bufs 等），每条排队消息的总内存估算 = `size(msg) + 96`。高水位 `highWaterMark` / 低水位 `lowWaterMark` 控制的是 `totalPendingSize`（原子计数），超过 high → `isWritable() = false`，降到 low 以下才重新变 true（hysteresis 防抖动）。

### addMessage → 水位通知

```java
public void addMessage(Object msg, int size, ChannelPromise promise) {
    Entry entry = newEntry(msg, size, promise);
    ... // 链表 append
    incrementPendingOutboundBytes(entry.pendingSize, false); // invokeLater=false：立刻同步 decrement
}

private void incrementPendingOutboundBytes(long size, boolean invokeLater) {
    TOTAL_PENDING_SIZE_UPDATER.addAndGet(this, size);
    if (invokeLater && UNWRITABLE_UPDATER.compareAndSet(this, 0, 1)) {
        channel.pipeline().fireChannelWritabilityChanged();
    }
}
```

`UNWRITABLE_UPDATER` 是一个原子 int 标记——只有第一次越过 high water 时触发一次 `fireChannelWritabilityChanged()`（writable→unwritable 边沿）；回落到 low 以下时再触发一次相反方向。

### nioBuffers：批量 DirectByteBuffer 拼接

```java
public ByteBuffer[] nioBuffers(int maxCount, long maxBytes) {
    ByteBuffer[] nioBuffers = NIO_BUFFERS.get(threadLocalMap); // FastThreadLocal 缓存
    int nioBufferCount = nioBuffers(entry, buf, nioBuffers, 0, maxCount);
    // expandNioBufferArray 按需扩容
    return nioBuffers;
}
```

`NIO_BUFFERS` 是 `FastThreadLocal<ByteBuffer[]>`，每个 EventLoop 线程复用同一组 `ByteBuffer` 数组，`entry.bufs` 也在 Entry 上缓存（避免每次 `buf.nioBuffers()` 重新分配）。`nioBuffers(...)` 必须紧接着 `forEachFlushable(...)` 写调完 `removeBytes(...)` 或 `abort()` 才能再用——回调里可能改写了 entry 状态。

## Event Mask 与 Handler 类型

`executionMask = mask(handlerClass)` 在构造 ctx 时一次性算出，之后事件传播时只做位与判断：

```java
// 掩码常量
static final int MASK_CHANNEL_REGISTERED = 1;
static final int MASK_CHANNEL_UNREGISTERED = 1 << 1;
...共 10 个 inbound + 8 个 outbound = 18 个位
static final int MASK_ONLY_INBOUND  = 0x3FF;   // 低 10 位
static final int MASK_ONLY_OUTBOUND = 0xFFC00; // 高 18 位
```

**ChannelHandler 类型与掩码的对应关系**：
- `ChannelInboundHandlerAdapter` / `ChannelOutboundHandlerAdapter`：adapter 是接口的具体实现类，其 executionMask 由实际 override 哪些方法决定
- `ChannelDuplexHandler`：同时有 inbound + outbound 掩码，invokeWrite / invokeFlush 里它有单独的 instanceof 分支（4.2 特意，见上文 DON'T CHANGE 注释）
- HeadContext / TailContext：两个都用自身 class 算 mask（HeadContext 同时实现 Inbound + Outbound，TailContext 只 Inbound）

## Links

- [Netty Channel 与注册路径](/docs/CS/Framework/Netty/Channel.md)
- [Transport 与 IoHandler 抽象](/docs/CS/Framework/Netty/Transport.md)
- [EventLoop 与线程模型](/docs/CS/Framework/Netty/EventLoop.md)
- [Bootstrap 客户端与服务端启动](/docs/CS/Framework/Netty/Bootstrap.md)
- [AdaptivePoolingAllocator 与 ByteBuf 内存](/docs/CS/Framework/Netty/memory.md)
- [Future and Promise](/docs/CS/Framework/Netty/Future.md)

## References

1. [Netty 4.2 DefaultChannelPipeline source](https://github.com/netty/netty/blob/4.2/transport/src/main/java/io/netty/channel/DefaultChannelPipeline.java)
2. [Netty #10067 — skipContext must consider executor](https://github.com/netty/netty/issues/10067)
3. [Netty #3156 — destroy two-pass traversal](https://github.com/netty/netty/issues/3156)
4. [Netty #8343 — WriteTask cancel on RejectedExecution](https://github.com/netty/netty/issues/8343)
5. [OpenJDK JDK-8180450 — Duplex handler instanceof scalability](https://bugs.openjdk.org/browse/JDK-8180450)
