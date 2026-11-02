## Introduction

Transport 层决定"用什么系统调用把字节搬到 Socket 上"。Netty 的 `Channel` / `EventLoop` 抽象与具体 IO 多路复用机制解耦，因此同一份 pipeline 代码可以跑在 NIO、epoll、kqueue、[io_uring](/docs/CS/Framework/Netty/ioUring.md) 四种实现上——差别只在 `Channel` 类型与 `EventLoopGroup` 的构造方式。

本文以 **Netty 4.2**（最新 GA 4.2.19.Final）源码为准。4.2 在这一层做了自 Netty 4.0 以来最大的一次重构：**把 IO 多路复用的循环从 `EventLoop` 里抽出来，抽象成 `IoHandler`**，这是理解 4.2 transport 的第一件事。

## IoHandler Abstraction

4.1 时代每个 transport 都要自己实现一个 `EventLoop` 子类并重写 `run()`——NIO 的 select 循环、epoll 的 `epoll_wait` 循环、kqueue 的 `kevent` 循环，三份几乎同构的代码。4.2 把它收敛成一个接口：

```java
// 源码：transport/src/main/java/io/netty/channel/IoHandler.java:33-86
public interface IoHandler {

    default void initialize() { }                             // 启动前初始化（可选实现）

    int run(IoHandlerContext context);                        // 跑一轮 IO，返回本轮处理过的 IoHandle 数

    default void prepareToDestroy() { }                       // destroy() 之前调用，可能调用多次
    default void destroy() { }

    IoRegistration register(IoHandle handle) throws Exception;// 注意签名是 Exception，不是 IOException

    void wakeup();                                           // 唤醒阻塞中的 IO（无布尔参数）

    boolean isCompatible(Class<? extends IoHandle> handleType);
}
```

除 `wakeup()` 与 `isCompatible(Class)` 之外的所有方法，**必须**在实现了 `ThreadAwareExecutor` 的托管线程上执行，且不应由用户代码直接调用（源码：`IoHandler.java:22-24`）。

配套的两个接口：

- `IoHandle extends AutoCloseable`：能被注册到 `IoHandler` 上的对象（Channel 的底层句柄），收到事件时回调 `void handle(IoRegistration registration, IoEvent ioEvent)`（源码：`transport/src/main/java/io/netty/channel/IoHandle.java:27,36`）
- `IoRegistration`：`long submit(IoOps ops)` 提交关注事件，取代 4.1 里直接操作 `SelectionKey.interestOps` / 调 `epoll_ctl` 的方式；另有 `isValid()` 与 `boolean cancel()`（源码：`transport/src/main/java/io/netty/channel/IoRegistration.java:37,45,52`）

生命周期与阻塞决策由第三个接口 `IoHandlerContext` 提供（`canBlock()` / `delayNanos(long)` / `deadlineNanos()` / `shouldReportActiveIoTime()` / `reportActiveIoTime(long)`），由外层 `SingleThreadIoEventLoop` 实现（源码：`transport/src/main/java/io/netty/channel/IoHandlerContext.java:26`）。

事件循环本体变成通用的 `SingleThreadIoEventLoop`，它只负责"跑任务 + 调 `ioHandler.run(context)`"，不再知道底层是 select 还是 epoll_wait。

### Migration

4.2 中所有 transport-specific 的 `EventLoopGroup` 均已 `@Deprecated`，Javadoc 一律指向 `MultiThreadIoEventLoopGroup` + 对应 `IoHandler.newFactory()`：

```java
// 源码：transport-classes-epoll/src/main/java/io/netty/channel/epoll/EpollEventLoopGroup.java:37-40
/**
 * @deprecated Use {@link MultiThreadIoEventLoopGroup} with {@link EpollIoHandler#newFactory()}.
 */
@Deprecated
public final class EpollEventLoopGroup extends MultiThreadIoEventLoopGroup {
```

```java
// 源码：transport/src/main/java/io/netty/channel/nio/NioEventLoopGroup.java:40-43
/**
 * @deprecated Use {@link MultiThreadIoEventLoopGroup} with {@link NioIoHandler#newFactory()}.
 */
@Deprecated
public class NioEventLoopGroup extends MultiThreadIoEventLoopGroup implements IoEventLoopGroup {
```

```java
// 源码：transport-classes-kqueue/src/main/java/io/netty/channel/kqueue/KQueueEventLoopGroup.java:39-42
/**
 * @deprecated Use {@link MultiThreadIoEventLoopGroup} with {@link KQueueIoHandler#newFactory()}.
 */
@Deprecated
public final class KQueueEventLoopGroup extends MultiThreadIoEventLoopGroup {
```

新写法统一走 `MultiThreadIoEventLoopGroup` + `IoHandlerFactory`：

```java
EventLoopGroup group = new MultiThreadIoEventLoopGroup(NioIoHandler.newFactory());
// epoll：EpollIoHandler.newFactory()
// kqueue：KQueueIoHandler.newFactory()
// io_uring：IoUringIoHandler.newFactory()
```

四个 `newFactory()` 的真实签名（均已逐条比对 4.2.19 源码）：

| Transport  | 静态工厂签名                                                                          | 源码                                                                                                 |
| :--------- | :------------------------------------------------------------------------------ | :------------------------------------------------------------------------------------------------- |
| NIO        | `newFactory()` / `newFactory(SelectorProvider)` / `newFactory(SelectorProvider, SelectStrategyFactory)` | `transport/src/main/java/io/netty/channel/nio/NioIoHandler.java:776,786,797`                        |
| epoll      | `newFactory()` / `newFactory(int maxEvents, SelectStrategyFactory)`               | `transport-classes-epoll/src/main/java/io/netty/channel/epoll/EpollIoHandler.java:98,105`            |
| kqueue     | `newFactory()` / `newFactory(int maxEvents, SelectStrategyFactory)`               | `transport-classes-kqueue/src/main/java/io/netty/channel/kqueue/KQueueIoHandler.java:108,115`        |
| io_uring   | `newFactory()` / `newFactory(int ringSize)` / `newFactory(IoUringIoHandlerConfig)` | `transport-classes-io_uring/src/main/java/io/netty/channel/uring/IoUringIoHandler.java:815,826,838`  |

三者返回的都是 `io.netty.channel.IoHandlerFactory`，它是函数式接口，唯一方法为 `IoHandler newHandler(ThreadAwareExecutor ioExecutor)`（源码：`transport/src/main/java/io/netty/channel/IoHandlerFactory.java:23,31`），因此也可以自己写 lambda 替换。

> [!NOTE]
>
> epoll / kqueue / io_uring 的 `newFactory(...)` 会在**构造工厂时**就调用 `Epoll.ensureAvailability()` / `KQueue.ensureAvailability()` / `IoUring.ensureAvailability()`（源码：`EpollIoHandler.java:107`、`KQueueIoHandler.java:117`、`IoUringIoHandler.java:839`），所以原生库缺失或内核过低是"创建 group 时立刻抛 `UnsatisfiedLinkError` / `UnsupportedOperationException`"，而不是等 bind 时才炸。NIO 无此检查（JDK 自带，必然可用）。

> [!NOTE]
>
> `MultiThreadIoEventLoopGroup` **没有静态 `create(...)` 工厂方法**，直接用构造器即可。4.2.19 中它有 7 个 public 重载构造器（`transport/src/main/java/io/netty/channel/MultiThreadIoEventLoopGroup.java:43-124`）：`(IoHandlerFactory)`、`(int nThreads, IoHandlerFactory)`、`(ThreadFactory, IoHandlerFactory)`、`(Executor, IoHandlerFactory)`、`(int, Executor, IoHandlerFactory)`、`(int, ThreadFactory, IoHandlerFactory)`、`(int, Executor, EventExecutorChooserFactory, IoHandlerFactory)`。`new MultiThreadIoEventLoopGroup(factory)` 直接转发为 `this(0, ioHandlerFactory)`（源码：`:43-45`）——`nThreads == 0` 时使用默认线程数 `DEFAULT_EVENT_LOOP_THREADS`（CPU 核数 × 2）。单线程侧的 `IoEventLoop` 由 protected 的 `newChild(...)` 通过 `new SingleThreadIoEventLoop(this, executor, ioHandlerFactory)` 创建（源码：`:212-214`）。
>
> 传 `AutoScalingEventExecutorChooserFactory` 可启用基于利用率的自动扩缩容（源码：`:31-36`）。

```java
// 源码：transport/src/main/java/io/netty/channel/nio/NioEventLoop.java:44-45
@Deprecated
public final class NioEventLoop extends SingleThreadIoEventLoop {
```

它已被缩到 233 行，只剩 4 个 public 实例方法，全部是委派：

| 方法                                                                          | 行号    | 委派目标                                            |
| :-------------------------------------------------------------------------- | :---- | :---------------------------------------------- |
| `SelectorProvider selectorProvider()`                                         | `:67`  | `((NioIoHandler) ioHandler()).selectorProvider()` |
| `void register(SelectableChannel ch, int interestOps, NioTask<?> task)`       | `:76`  | 注册用户自定义 `NioTask`，内部仍走 `ioHandler()`           |
| `void rebuildSelector()`                                                      | `:144` | `((NioIoHandler) ioHandler()).rebuildSelector0()` |
| `int registeredChannels()` / `Iterator<Channel> registeredChannelsIterator()` | `:158` / `:163` | `NioIoHandler` 的注册集合                           |

**`NioEventLoop#run` 与 `#processSelectedKeys` 已不存在**，全部迁到 `NioIoHandler`。

> [!NOTE]
>
> 4.1 里 `NioEventLoop` 是"线程 + Selector + 任务队列"三合一的主体（约 800 行）；4.2 把它拆成「`SingleThreadIoEventLoop` 管线程与任务队列」＋「`NioIoHandler` 管 Selector」，`NioEventLoop` 退化成只剩类型信息与几个委派方法。所以看到 4.1 教程里的 `NioEventLoop#run()` 时，在 4.2 应该去看 `NioIoHandler#run(IoHandlerContext)`。
>
> 另：`MultiThreadIoEventLoopGroup` 存在，但**不存在** `MultiThreadIoEventLoop` 这个类；单线程侧的类名是 `SingleThreadIoEventLoop`。

## NIO

### Select Loop

`NioIoHandler#run(IoHandlerContext)` 的签名与 4.1 不同，返回 int 表示本轮处理的就绪数。4.2 的 `BUSY_WAIT` 分支**直接穿透到 `SELECT`**（NIO 不支持忙等），且 `CONTINUE` 分支要先补一次 `reportActiveIoTime(0)` 再返回：

```java
// 源码：transport/src/main/java/io/netty/channel/nio/NioIoHandler.java:419-469
public int run(IoHandlerContext context) {
    int handled = 0;
    try {
        try {
            switch (selectStrategy.calculateStrategy(selectNowSupplier, !context.canBlock())) {
                case SelectStrategy.CONTINUE:
                    if (context.shouldReportActiveIoTime()) {
                        context.reportActiveIoTime(0); // Report zero as we did no I/O.
                    }
                    return 0;

                case SelectStrategy.BUSY_WAIT:
                    // fall-through to SELECT since the busy-wait is not supported with NIO

                case SelectStrategy.SELECT:
                    select(context, wakenUp.getAndSet(false));
                    if (wakenUp.get()) {
                        selector.wakeup();
                    }
                    // fall through
                default:
            }
        } catch (IOException e) {
            rebuildSelector0();
            handleLoopException(e);
            return 0;
        }
        // ... processSelectedKeys()
        return handled;
    }
}
```

注意这里**没有** 4.1 式的 `fallthrough` 布尔标志：靠 Java 的 switch 穿透语义直接落到 `SELECT` 分支。

空轮询（JDK epoll bug）的防护常量：

```java
// 源码：transport/src/main/java/io/netty/channel/nio/NioIoHandler.java:66-88
private static final int MIN_PREMATURE_SELECTOR_RETURNS = 3;
private static final int SELECTOR_AUTO_REBUILD_THRESHOLD;

static {
    int selectorAutoRebuildThreshold = SystemPropertyUtil.getInt("io.netty.selectorAutoRebuildThreshold", 512);
    if (selectorAutoRebuildThreshold < MIN_PREMATURE_SELECTOR_RETURNS) {
        selectorAutoRebuildThreshold = 0;
    }
    SELECTOR_AUTO_REBUILD_THRESHOLD = selectorAutoRebuildThreshold;
}
```

触发重建的条件：

```java
// 源码：transport/src/main/java/io/netty/channel/nio/NioIoHandler.java:697-701
} else if (SELECTOR_AUTO_REBUILD_THRESHOLD > 0 &&
        selectCnt >= SELECTOR_AUTO_REBUILD_THRESHOLD) {
    selector = selectRebuildSelector(selectCnt);
    selectCnt = 1;
    break;
}
```

即连续 512 次 `select()` 立即返回就认为 Selector 已损坏，重建并把旧 Selector 上的 key 全部迁移过去。把阈值设为小于 `MIN_PREMATURE_SELECTOR_RETURNS`（3）等价于关闭该保护。

> [!NOTE]
>
> 4.1 的 `unexpectedSelectorWakeup()` 方法在 4.2 中已删除，重建判定改为 `selectCnt` 内联计数；`rebuildSelector0()` 也从 `NioEventLoop` 搬到了 `NioIoHandler`（源码：`NioIoHandler.java:747`），`NioEventLoop#rebuildSelector()` 只是委派过去（源码：`NioEventLoop.java:144-154`）。

### SelectedKeys Optimization

JDK 的 `Selector.selectedKeys()` 返回 `Set<SelectionKey>`，遍历需要创建 Iterator 且有哈希探测成本。Netty 用反射把这两个字段换成自己的数组实现：

```java
// 源码：transport/src/main/java/io/netty/channel/nio/NioIoHandler.java:63-64,101
private static final boolean DISABLE_KEY_SET_OPTIMIZATION =
        SystemPropertyUtil.getBoolean("io.netty.noKeySetOptimization", false);
private SelectedSelectionKeySet selectedKeys;
```

处理时逐个置 null 以便 GC：

```java
// 源码：transport/src/main/java/io/netty/channel/nio/NioIoHandler.java:569-571
final SelectionKey k = selectedKeys.keys[i];
// null out entry in the array to allow to have it GC'ed once the Channel close, See #2363
selectedKeys.keys[i] = null;
processSelectedKey(k);
```

反射替换的逻辑写在 `NioIoHandler#openSelector()`（源码：`transport/src/main/java/io/netty/channel/nio/NioIoHandler.java:143`），4.1 时它位于 `NioEventLoop`。

### Read / Write

```java
// 源码：transport/src/main/java/io/netty/channel/socket/nio/NioSocketChannel.java:347-351
protected int doReadBytes(ByteBuf byteBuf) throws Exception {
    final RecvByteBufAllocator.Handle allocHandle = unsafe().recvBufAllocHandle();
    allocHandle.attemptedBytesRead(byteBuf.writableBytes());
    return byteBuf.writeBytes(javaChannel(), allocHandle.attemptedBytesRead());
}
```

写侧统一转成 `ByteBuffer[]` 再交给 JDK：

```java
// 源码：transport/src/main/java/io/netty/channel/socket/nio/NioSocketChannel.java:391-398
int maxBytesPerGatheringWrite = ((NioSocketChannelConfig) config).getMaxBytesPerGatheringWrite();
ByteBuffer[] nioBuffers = in.nioBuffers(1024, maxBytesPerGatheringWrite);
int nioBufferCnt = in.nioBufferCount();
// Always use nioBuffers() to workaround data-corruption. See https://github.com/netty/netty/issues/2761
switch (nioBufferCnt) {
    case 0:  writeSpinCount -= doWrite0(in); break;
    case 1:  /* javaChannel().write(buffer) */ break;
    default: /* javaChannel().write(nioBuffers, 0, nioBufferCnt) */ break;
}
```

`writeSpinCount` 默认 **16**（源码：`transport/src/main/java/io/netty/channel/DefaultChannelConfig.java:65`）。用尽预算后走 `incompleteWrite(writeSpinCount < 0)`（源码：`AbstractNioByteChannel.java:299`）：

- 为 `true`（内核暂不可写）→ `setOpWrite()`
- 为 `false`（数据没发完但 Socket 仍可写）→ `clearOpWrite()`

> [!NOTE]
>
> 4.2 里这两个方法**不再直接改 `SelectionKey.interestOps`**，而是拿 `IoRegistration` 后 `addAndSubmit(NioIoOps.WRITE)` 与 `removeAndSubmit(NioIoOps.WRITE)`（源码：`AbstractNioByteChannel.java:335-345`、`:347-356`、`NioIoOps.java:45`）。这是 `IoHandle` / `IoRegistration` 抽象落地的直接体现——transport 只声明意图（我要关注 WRITE），由 `NioIoHandler` 翻译成 JDK 的 interestOps 修改。

### Limits

NIO 的短板不在性能而在**能力**：JDK `SocketChannel` 没有暴露 `TCP_CORK`、`TCP_NOTSENT_LOWAT`、`SO_BUSY_POLL`、`sendmmsg` 这类 Linux 特有选项（见下文 `### EpollChannelOption`）；读数据必须经 `ByteBuffer` 中转；JDK Selector 自身有空轮询的历史 bug。

## epoll

### Event Loop

`EpollEventLoop` 在 4.2 同样 `@Deprecated` 且不含任何 `epoll_wait` 逻辑，只剩两个委派方法：

```java
// 源码：transport-classes-epoll/src/main/java/io/netty/channel/epoll/EpollEventLoop.java:33-34
@Deprecated
public class EpollEventLoop extends SingleThreadIoEventLoop {
    // 类体内只有下面两个委派方法，无任何 epoll_wait 逻辑
    @Override
    public int registeredChannels() {
        return ((EpollIoHandler) ioHandler()).numRegisteredChannels();
    }

    @Override
    public Iterator<Channel> registeredChannelsIterator() {
        return ((EpollIoHandler) ioHandler()).registeredChannelsList().iterator();
    }
}
```

真正的循环在 `EpollIoHandler#run`：

```java
// 源码：transport-classes-epoll/src/main/java/io/netty/channel/epoll/EpollIoHandler.java:487-500
if (strategy > 0) {
    int packed;
    if (context.shouldReportActiveIoTime()) {
        long activeIoStartTimeNanos = System.nanoTime();
        packed = processReady(events, strategy);
        long activeIoEndTimeNanos = System.nanoTime();
        context.reportActiveIoTime(activeIoEndTimeNanos - activeIoStartTimeNanos);
    } else {
        packed = processReady(events, strategy);
    }
    handled = packed >>> 1;
    if ((packed & 1) != 0) {
        prevDeadlineNanos = NONE;
    }
}
```

`Native.epollWait` 的返回值被打包成一个 long：高 32 位是就绪数、低位标记 timerfd 是否被触发（`strategy = Native.epollReady(result)`、`prevDeadlineNanos = Native.epollTimerWasUsed(result) ? curDeadlineNanos : NONE`，源码：`EpollIoHandler.java:473-474`）。

事件数组容量：

```java
// 源码：transport-classes-epoll/src/main/java/io/netty/channel/epoll/EpollIoHandler.java:127-131
if (maxEvents == 0) {
    allowGrowing = true;
    events = new EpollEventArray(4096);
} else {
    allowGrowing = false;
    events = new EpollEventArray(maxEvents);
}
```

默认 4096 且**可随负载翻倍增长**（`allowGrowing && strategy == events.length()` 时 `events.increase()`，源码：`:505`）。注意 `EpollIoHandler.newFactory()` 走的就是 `maxEvents = 0`（源码：`:98-99`），所以默认路径是"4096 起、可增长"。

### Registration

注册对象是 `EpollIoHandler` 的私有内部类 `DefaultEpollIoRegistration`，内部是 `Pending → Added → Cancelled` 状态机；`submit(IoOps)` 按当前状态走 `epollCtlAdd` / `epollCtlMod` / `epollCtlDel`。`IoOps` 的实现 `EpollIoOps` 用常量描述 EPOLLIN / EPOLLOUT / EPOLLERR / EPOLLRDHUP 等位（源码：`transport-classes-epoll/src/main/java/io/netty/channel/epoll/EpollIoOps.java:35-50`），另有一个 `NONE`（`:58`）用于"什么都不关注"。

### Read Loop

```java
// 源码：transport-classes-epoll/src/main/java/io/netty/channel/epoll/AbstractEpollChannel.java:259-261
final boolean shouldBreakEpollInReady(ChannelConfig config) {
    return socket.isInputShutdown() && (inputClosedSeenErrorOnRead || !isAllowHalfClosure(config));
}
```

（注意 epoll 侧方法名是 `shouldBreakEpollInReady`，NIO 与 kqueue 侧叫 `shouldBreakReadReady`，见下文 `## kqueue`。）

循环继续条件用"读满即可能还有"的启发式：

```java
// 源码：transport-classes-epoll/src/main/java/io/netty/channel/epoll/EpollRecvByteAllocatorHandle.java:48-67
boolean maybeMoreDataToRead() {
    return lastBytesRead() == attemptedBytesRead();
}

@Override
public final boolean continueReading() {
    // We must override the supplier which determines if there maybe more data to read.
    return continueReading(defaultMaybeMoreDataSupplier);
}
```

kqueue 侧同样有 `KQueueRecvByteAllocatorHandle.maybeMoreDataToRead()`（源码：`KQueueRecvByteAllocatorHandle.java:36`），只是 continueReading 的条件换成了 `readEOF`。

> [!NOTE]
>
> 4.2 中 `epollInReadyRunnablePending` 字段**已完全移除**，"边缘触发下必须循环读到 EAGAIN"的旧逻辑被上述启发式统一取代。

### Edge vs Level Triggered

**4.2 中 `EpollMode` 整个枚举已 `@Deprecated`，Netty 一律使用水平触发**：

```java
// 源码：transport-classes-epoll/src/main/java/io/netty/channel/epoll/EpollMode.java:23-35
/**
 * @deprecated Netty always uses level-triggered mode.
 */
@Deprecated
public enum EpollMode {
    EDGE_TRIGGERED,   // Use {@code EPOLLET} (edge-triggered).
    LEVEL_TRIGGERED   // Do not use {@code EPOLLET} (level-triggered).
}
```

```java
// 源码：transport-classes-epoll/src/main/java/io/netty/channel/epoll/EpollChannelConfig.java:185-203
@Deprecated
public EpollMode getEpollMode() {
    return EpollMode.LEVEL_TRIGGERED;
}

/** <strong>Be aware this config setting can only be adjusted before the channel was registered.</strong> */
@Deprecated
public EpollChannelConfig setEpollMode(EpollMode mode) {
    LOGGER.debug("Changing the EpollMode is not supported anymore, this is just a no-op");
    return this;
}
```

`epollInReady()`（源码：`AbstractEpollStreamChannel.java:750`）内部**没有任何 `getEpollMode()` 分支**。全包内 `getEpollMode()` 只剩两处，都在同样已废弃的 `spliceTo(...)` 里做前置校验（源码：`AbstractEpollStreamChannel.java:159-160,213`）。

> [!NOTE]
>
> `EPOLLET` 在 4.2.19 的 epoll 包中只剩三处：内部的 eventFd 与 timerFd 注册（源码：`EpollIoHandler.java:168,176`，注释明确说"It is important to use EPOLLET here as we only want to get the notification once per ..."），以及 `EpollIoOps` 里的常量定义（源码：`EpollIoOps.java:52`）。用户 Channel 一律水平触发，**没有任何系统属性能改回边缘触发**；`EpollChannelOption.EPOLL_MODE` 也只是 no-op 的废弃常量（源码：`EpollChannelOption.java:56-58`）。

### Write

分派逻辑先看 `ByteBuf` 是否有内存地址，有的话直接走 `IovArray` 路径，否则退回 `ByteBuffer[]`：

```java
// 源码：transport-classes-epoll/src/main/java/io/netty/channel/epoll/AbstractEpollStreamChannel.java:265-271
if (buf.hasMemoryAddress() || buf.nioBufferCount() == 1) {
    return doWriteBytes(in, buf);
} else {
    ByteBuffer[] nioBuffers = buf.nioBuffers();
    return writeBytesMultiple(in, nioBuffers, nioBuffers.length, readableBytes,
            config().getMaxBytesPerGatheringWrite());
}
```

单缓冲最终落到 `sendAddress` / `send`（源码：`:1063` 附近的 `doWriteBytes`）：

```java
// 源码：AbstractEpollStreamChannel.java（doWriteBytes）
if (buf.hasMemoryAddress()) {
    int localFlushedAmount = socket.sendAddress(buf.memoryAddress(), buf.readerIndex(), buf.writerIndex());
} else {
    final ByteBuffer nioBuf = ...;
    int localFlushedAmount = socket.send(nioBuf, nioBuf.position(), nioBuf.limit());
}
```

gathering write 走 `writev`：

```java
// 源码：AbstractEpollStreamChannel.java:303-318 走 IovArray（堆外地址直传，无需构造 ByteBuffer[]）
private int writeBytesMultiple(ChannelOutboundBuffer in, IovArray array) throws IOException {
    final long localWrittenBytes = socket.writevAddresses(array.memoryAddress(0), cnt);
    if (localWrittenBytes > 0) {
        adjustMaxBytesPerGatheringWrite(expectedWrittenBytes, localWrittenBytes, array.maxBytes());
        in.removeBytes(localWrittenBytes);
        return 1;
    }
    return WRITE_STATUS_SNDBUF_FULL;
}

// 源码：:334-348 走 ByteBuffer[] 路径
private int writeBytesMultiple(ChannelOutboundBuffer in, ByteBuffer[] nioBuffers, int nioBufferCnt, ...) {
    final long localWrittenBytes = socket.writev(nioBuffers, 0, nioBufferCnt, expectedWrittenBytes);
    ...
}
```

相比 NIO 的直接差异：

| 维度    | NIO                          | epoll                                       |
| :---- | :--------------------------- | :------------------------------------------ |
| 单缓冲写  | `ch.write(ByteBuffer)`       | `sendAddress` / `send`（可绕过 ByteBuffer 对象）  |
| 批量写   | `ch.write(ByteBuffer[], ...)`| `writev` / `writevAddresses`（IovArray 复用）   |
| 文件传输  | `FileChannel.transferTo`     | `sendFile` / `splice`（splice 到 pipe 再零拷贝） |
| 重试驱动  | `OP_WRITE` 兴趣集               | `setFlag(EPOLLOUT)` / `clearFlag(EPOLLOUT)` |
| UDP 批量 | 逐个收发                         | `sendmmsg` / `recvmmsg`                     |

### EpollChannelOption

```java
// 源码：transport-classes-epoll/src/main/java/io/netty/channel/epoll/EpollChannelOption.java:23-63
public final class EpollChannelOption<T> extends UnixChannelOption<T> {
```

4.2.19 中自有 20 个常量。注意这些常量的**静态类型都是 `ChannelOption<X>` 而非 `EpollChannelOption<X>`**（`valueOf(...)` 返回的是核心 `ChannelOption`），所以写法上和核心 `ChannelOption` 混用不会报类型错：

| 常量                              | 类型                          | 语义                        |
| :------------------------------ | :-------------------------- | :------------------------ |
| `TCP_CORK`                      | `Boolean`                   | 攒包，抑制部分发送                 |
| `TCP_NOTSENT_LOWAT`             | `Long`                      | 未发送字节水位                   |
| `TCP_KEEPIDLE` / `TCP_KEEPINTVL` / `TCP_KEEPCNT` | `Integer`    | keepalive 三参数              |
| `TCP_USER_TIMEOUT`              | `Integer`                   | TCP_USER_TIMEOUT          |
| `TCP_DEFER_ACCEPT`              | `Integer`                   | 延迟 accept 到有数据            |
| `TCP_QUICKACK`                  | `Boolean`                   | 关闭延迟 ACK                  |
| `TCP_MD5SIG`                    | `Map<InetAddress, byte[]>`  | TCP MD5 签名                |
| `TCP_FASTOPEN` / `TCP_FASTOPEN_CONNECT` | `Integer` / `Boolean` | **已 `@Deprecated`**，指向核心 `ChannelOption` 同名项 |
| `IP_FREEBIND`                   | `Boolean`                   | 允许 bind 非本地地址             |
| `IP_BIND_ADDRESS_NO_PORT`       | `Boolean`                   | bind 时不占端口                |
| `IP_TRANSPARENT` / `IP_RECVORIGDSTADDR` | `Boolean`         | 透明代理                      |
| `IP_MULTICAST_ALL`              | `Boolean`                   | 接收所有组播组                   |
| `SO_BUSY_POLL`                  | `Integer`                   | 忙轮询微秒数                    |
| `MAX_DATAGRAM_PAYLOAD_SIZE`     | `Integer`                   | 单数据报最大载荷                  |
| `UDP_GRO`                       | `Boolean`                   | UDP 通用接收卸载                |
| `EPOLL_MODE`                    | `EpollMode`                 | **已 `@Deprecated`**，no-op  |

另有从 `UnixChannelOption` 继承的 `SO_REUSEPORT`、`DOMAIN_SOCKET_READ_MODE`（源码：`transport-native-unix-common/src/main/java/io/netty/channel/unix/UnixChannelOption.java:21-23`）。

### Availability

三个原生 transport 共用一个总开关 `io.netty.transport.noNative`（默认 `false`），分别在 `Epoll.java:35`、`KQueue.java:32`、`IoUring.java:94` 读取。不可用有两类原因：显式禁用，或静态块里 `Native.newEpollCreate()` / `newEventFd()` 抛异常（缺 JNI 库、glibc 版本过低、memlock 限制等，源码：`Epoll.java:42-43`）。

诊断入口：

| Transport  | 可用性判定                   | 失败原因                          |
| :--------- | :----------------------- | :---------------------------- |
| epoll      | `Epoll.isAvailable()`    | `Epoll.unavailabilityCause()`  |
| kqueue     | `KQueue.isAvailable()`   | `KQueue.unavailabilityCause()` |
| io_uring   | `IoUring.isAvailable()`  | `IoUring.unavailabilityCause()` |

源码分别为 `Epoll.java:78,101`、`KQueue.java:66,89`、`IoUring.java:229,422`。

> [!WARNING]
>
> 官方 Linux 构建都链接 GLIBC，使用 musl libc 的发行版（Alpine）不被官方原生库支持，只能退回 NIO。

## kqueue

```java
// 源码：transport-classes-kqueue/src/main/java/io/netty/channel/kqueue/KQueueIoHandler.java:52
public final class KQueueIoHandler implements IoHandler {
```

用法与 epoll 对称：`new MultiThreadIoEventLoopGroup(KQueueIoHandler.newFactory())`。`KQueueEventLoopGroup` 保留但已 `@Deprecated`（源码：`KQueueEventLoopGroup.java:39-42`）；**4.2.19 中不存在 `KQueueEventLoop` 类**——kqueue 包内只有 Group，没有单线程 Loop。这与 epoll 不同：epoll 包保留了 `@Deprecated` 的 `EpollEventLoop`（源码：`transport-classes-epoll/src/main/java/io/netty/channel/epoll/EpollEventLoop.java:33-34`）。

可用性判定与 epoll 同构：`KQueue.isAvailable()` / `KQueue.unavailabilityCause()`，同样受 `io.netty.transport.noNative` 控制（源码：`KQueue.java:32,66,89`）。适用于 macOS / BSD。

kqueue 侧保留了 `shouldBreakReadReady()` 命名（源码：`AbstractKQueueChannel.java:329`），与 epoll 的 `shouldBreakEpollInReady()`（源码：`AbstractEpollChannel.java:259`）不同；NIO 侧也叫 `shouldBreakReadReady()`（源码：`AbstractNioByteChannel.java:91`）。

> [!NOTE]
>
> 这是 4.2 最容易误读的一处：kqueue 只有 `KQueueEventLoopGroup` 而没有 `KQueueEventLoop`，epoll 则两个都有（都已废弃）。真正承载 `kevent` 循环的是 `KQueueIoHandler`，它和 `KQueueEventLoop` 从不存在过。

## io_uring

包路径 `io.netty.channel.uring`（4.1 时代是孵化器包 `io.netty.incubator.channel.uring`，4.2 已迁入正式包）。io_uring 的内核模型、SQ/CQ 结构与 Netty 接入细节见 [io_uring](/docs/CS/Framework/Netty/ioUring.md)。

```java
// 源码：transport-classes-io_uring/src/main/java/io/netty/channel/uring/package-info.java:16-21
/**
 * <a href="https://kernel.dk/io_uring.pdf">io_uring</a> is a high I/O performance scalable interface for fully
 * asynchronous Linux syscalls. While Netty 4.2 generally requires Java 8 or newer, this optional io_uring native
 * transport requires Java 9 or newer.
 */
package io.netty.channel.uring;
```

**4.2.19 中不存在 `IoUringEventLoopGroup`，也不存在 `IoUringEventLoop`**——io_uring 只有 `IoHandler` 一条路。循环实现是 `public final class IoUringIoHandler implements IoHandler`（源码：`transport-classes-io_uring/src/main/java/io/netty/channel/uring/IoUringIoHandler.java:54`），**没有任何 `@Deprecated` 标注**：

```java
// 默认 ring size
EventLoopGroup group = new MultiThreadIoEventLoopGroup(IoUringIoHandler.newFactory());

// 只指定 ring size
EventLoopGroup group = new MultiThreadIoEventLoopGroup(IoUringIoHandler.newFactory(256));

// 完整配置：ring size / cq size / buffer ring / 工作线程池
IoUringBufferRingConfig bufRing = IoUringBufferRingConfig.builder()   // 静态工厂，非 new Builder()
        .bufferGroupId((short) 1)
        .bufferRingSize((short) 128)
        .allocator(new IoUringFixedBufferRingAllocator(4096))   // 或 new IoUringAdaptiveBufferRingAllocator()
        .build();
IoUringIoHandlerConfig config = new IoUringIoHandlerConfig()
        .setRingSize(256)
        .setBufferRingConfig(bufRing);
EventLoopGroup group = new MultiThreadIoEventLoopGroup(IoUringIoHandler.newFactory(config));
```

`IoUringBufferRingConfig` 的两个 public 构造器（4 参 / 6 参）在 4.2.19 中**都已 `@Deprecated`**，应改用 `IoUringBufferRingConfig.builder()`（源码：`IoUringBufferRingConfig.java:48-50`、`:68`、`:183-187`）。

`IoUringIoHandlerConfig` 的可调项（源码：`IoUringIoHandlerConfig.java:106-111`）：`ringSize`、`cqSize`、`maxBoundedWorker`、`maxUnboundedWorker`、`bufferRingConfigs`、`singleIssuer`（默认 `true`）。

可用性开关是 `IoUring.isAvailable()` / `IoUring.unavailabilityCause()`（源码：`IoUring.java:229,422`），和 `Epoll` 一样受 `io.netty.transport.noNative` 统一控制（源码：`IoUring.java:94-96`）。

> [!NOTE]
>
> io_uring 在 4.2.19 已是正式一等公民的原生传输模块（位于正式包 `io.netty.channel.uring`，`IoUringIoHandler` 是普通 `public final class`，非 `@Deprecated`、非 incubator 命名空间）。但它仍是**可选原生**依赖，不是像 NIO 那样零依赖开箱即用：必须提供配套 JNI 库，且运行时要求 **JDK 9+**（`package-info.java:18-19`，另见 `IoUring.java:100` 的 `PlatformDependent.javaVersion() >= 9` 判断）与 **Linux 内核 ≥ 5.9**（硬下限，源码：`transport-classes-io_uring/src/main/java/io/netty/channel/uring/Native.java:524-537`，可用 `-Dio.netty.transport.iouring.enforceKernelVersion=false` 绕过校验）。因此选型时它应被理解为「Linux 新内核上的高性能可选后端」，而非「实验性」占位。
>
> 4.1 时代 io_uring 是独立的孵化器项目，包名是 `io.netty.incubator.channel.uring`；4.2 把它收编进主线正式包 `io.netty.channel.uring`，且**只保留 `IoHandler` 形态**——这是可以在 4.2.19 源码中验证的：整个 `io.netty.channel.uring` 包里既没有 `IoUringEventLoopGroup` 也没有 `IoUringEventLoop`，更没有为 4.1 的旧 API 留兼容类。因此它和 epoll / kqueue 不同：**旧写法在 4.2 中根本没有对应的过时类可用**，必须直接按 `IoHandler` 写。

门槛与默认值：

| 项      | 值                                                                                                                         | 源码                                                     |
| :----- | :------------------------------------------------------------------------------------------------------------------------ | :----------------------------------------------------- |
| JDK    | 9+                                                                                                                        | `package-info.java:18-19`、`IoUring.java:100`           |
| 内核     | 代码硬下限 **5.9**（`Native.checkKernelVersion`，可用 `-Dio.netty.transport.iouring.enforceKernelVersion=false` 绕过）；README 推荐 **5.14** | `Native.java:524-537`、`transport-native-io_uring/README.md:8,10` |
| ring 大小 | `DEFAULT_RING_SIZE = max(16, io.netty.iouring.ringSize)`，默认 **128**                                                        | `IoUring.java:194`                                     |
| CQ 大小  | `DEFAULT_CQ_SIZE = max(DEFAULT_RING_SIZE, ...)`,可经 `IoUringIoHandlerConfig.setCqSize(...)` 覆盖                                    | `IoUring.java:210`、`IoUringIoHandlerConfig.java:107`    |
| iovec  | `io.netty.iouring.numElementsIoVec` 默认 `10 * IOV_MAX`（约 160 KB）                                                             | `IoUring.java:110-111`                                 |

额外能力（都是 epoll 拿不到的）：

| 能力                     | 常量 / 类                                                         | 源码                     |
| :--------------------- | :------------------------------------------------------------- | :--------------------- |
| buffer ring            | `IoUringBufferRing` / `IoUringBufferRingConfig`                 | `IoUringIoHandlerConfig.java:110` |
| multishot accept / recv | `acceptMultishotSupported` / `recvMultishotSupported`           | `IoUring.java:124-125`  |
| zero-copy send         | `IORING_SEND_ZC_SUPPORTED` / `sendmsgZcSupported`               | `IoUring.java:36,119-120` |
| splice                 | `spliceSupported`                                              | `IoUring.java:116`      |
| UDS 查询                 | `unixDomainSocketInqSupported`                                  | `IoUring.java:115`      |

这些特性都在静态块里通过 `Native.ioUringProbe(...)` 探测，能力缺失时自动降级，不需要用户开关。

## Choice

| Transport  | 平台                  | Maven 依赖                                | 运行时门槛                        | 4.2 推荐构造                                                       |
| :--------- | :------------------ | :-------------------------------------- | :-------------------------- | :------------------------------------------------------------- |
| NIO        | 全平台                 | 仅 `netty-transport`                      | 无                           | `new MultiThreadIoEventLoopGroup(NioIoHandler.newFactory())`      |
| epoll      | Linux                | `netty-transport-native-epoll`            | JNI 库可用                      | `new MultiThreadIoEventLoopGroup(EpollIoHandler.newFactory())`    |
| kqueue     | macOS / BSD          | `netty-transport-native-kqueue`           | JNI 库可用                      | `new MultiThreadIoEventLoopGroup(KQueueIoHandler.newFactory())`   |
| [io_uring](/docs/CS/Framework/Netty/ioUring.md)   | Linux                | `netty-transport-native-io_uring`         | JDK 9+ 且内核 ≥ 5.9（README 建议 5.14） | `new MultiThreadIoEventLoopGroup(IoUringIoHandler.newFactory())`  |

三个 Maven artifactId 均已核对 4.2.19 的 `transport-native-epoll/pom.xml:24`、`transport-native-kqueue/pom.xml:24`、`transport-native-io_uring/pom.xml:24`。此外原生传输还需要带 classifier 的 JNI 产物，classifier 由 os-maven-plugin 的 `os.detected.classifier` 属性注入（源码：`transport-native-epoll/pom.xml:93,139`），形如 `linux-x86_64` / `osx-aarch_64`；这也是 `netty-transport-native-epoll` 与 `netty-transport-classes-epoll` 分成两个构件的原因（后者是纯 Java 类，前者只装 JNI 库）。

性能与能力取舍：

| 维度       | NIO             | epoll                          | kqueue              | [io_uring](/docs/CS/Framework/Netty/ioUring.md)                             |
| :------- | :-------------- | :----------------------------- | :------------------ | :----------------------------------- |
| 系统调用/轮    | 1 次 `select`     | 1 次 `epoll_wait`               | 1 次 `kevent`         | 1 次 `io_uring_enter` 同时完成"提交 + 收割"（`SubmissionQueue.submitAndWait*`，源码 `SubmissionQueue.java:271-300`） |
| 就绪事件获取    | `SelectionKey` 迭代器 | `EpollEventArray`（数组，零迭代）         | `KQueueEventArray`  | 直接从 CQ ring 取 CQE（无就绪事件集对象）              |
| 批量收发      | 逐个             | `sendmmsg` / `recvmmsg`         | 逐个                  | multishot recv（一次提交多次收）                 |
| 零拷贝       | `transferTo`    | `sendFile` / `splice`           | 无                   | zero-copy send / buffer ring / splice   |
| 独有 TCP 选项 | 无              | `TCP_CORK`、`TCP_NOTSENT_LOWAT`、`SO_BUSY_POLL`、`TCP_MD5SIG` | 无                   | 同 epoll 体系                            |
| 门槛        | 零依赖            | JNI + glibc                    | JNI                 | JNI + JDK9+ + 内核 5.9+                |

结论：跨平台与 musl 发行版只能 NIO；Linux 上追求功能与吞吐选 epoll（成熟、能力最全）；内核足够新且能接受更高运维门槛时再上 io_uring；macOS/BSD 只有 kqueue 可选。

官方 wiki 的 `native-transports.html` 页面截至 4.2 已明显滞后（仍推荐废弃的 `EpollEventLoopGroup`，且完全未提 io_uring），选型时以 4.2 源码与 Javadoc 为准。

## Links

- [Netty](/docs/CS/Framework/Netty/Netty.md)
- [EventLoop 与线程模型](/docs/CS/Framework/Netty/EventLoop.md)
- [Channel](/docs/CS/Framework/Netty/Channel.md)
- [TCP Fast Open](/docs/CS/Framework/Netty/TPO.md)
- [Linux IO 多路复用](/docs/CS/OS/Linux/IO/multiplexing.md)
- [Linux TCP 实现](/docs/CS/OS/Linux/net/TCP/TCP.md)

## References

1. [Netty 4.2 Javadoc - IoHandler](https://netty.io/4.2/api/io/netty/channel/IoHandler.html)
2. [Netty 4.2 Javadoc - MultiThreadIoEventLoopGroup](https://netty.io/4.2/api/io/netty/channel/MultiThreadIoEventLoopGroup.html)
3. [Netty native transports (wiki)](https://netty.io/wiki/native-transports.html)
4. [Netty 4.2 Javadoc - IoUringIoHandler](https://netty.io/4.2/api/io/netty/channel/uring/IoUringIoHandler.html)
5. [Netty 4.2.0 release notes](https://netty.io/news/2025/04/03/4-2-0.html)
6. [io_uring 论文](https://kernel.dk/io_uring.pdf)
