## Introduction

Transport 层决定"用什么系统调用把字节搬到 Socket 上"。Netty 的 `Channel` / `EventLoop` 抽象与具体 IO 多路复用机制解耦，因此同一份 pipeline 代码可以跑在 NIO、epoll、kqueue、io_uring 四种实现上——差别只在 `Channel` 类型与 `EventLoopGroup` 的构造方式。

本文以 **Netty 4.2**（最新 GA 4.2.19.Final，2026-10-06）源码为准。4.2 在这一层做了自 Netty 4.0 以来最大的一次重构：**把 IO 多路复用的循环从 `EventLoop` 里抽出来，抽象成 `IoHandler`**，这是理解 4.2 transport 的第一件事。

## IoHandler Abstraction

4.1 时代每个 transport 都要自己实现一个 `EventLoop` 子类并重写 `run()`——NIO 的 select 循环、epoll 的 `epoll_wait` 循环、kqueue 的 `kevent` 循环，三份几乎同构的代码。4.2 把它收敛成一个接口：

```java
public interface IoHandler {
    int run(IoHandlerContext context);
    void initialize();
    void prepareToDestroy();
    void destroy();
    IoRegistration register(IoHandle handle) throws IOException;
    void wakeup();
    boolean isCompatible(Class<?> handleType);
}
```

配套的两个接口：

- `IoHandle extends AutoCloseable`：能被注册到 `IoHandler` 上的对象（Channel 的底层句柄）
- `IoRegistration`：`submit(IoOps)` 提交关注事件，取代 4.1 里直接操作 `SelectionKey.interestOps` / `epoll_ctl` 的方式

事件循环本体变成通用的 `SingleThreadIoEventLoop`，它只负责"跑任务 + 调 `ioHandler.run(context)`"，不再知道底层是 select 还是 epoll_wait。

### Core Quartet

IoHandler 抽象由四对标记接口组成，每对是一组"前置声明 → 后置通知"：

| 接口 | 生产者/消费者 | 谁实现 | 作用 |
| :--- | :--- | :--- | :--- |
| `IoHandle` | 事件消费者 | `AbstractNioUnsafe`（Channel 内部类） | 被 IoHandler 注册、接收 `handle(IoRegistration, IoEvent)` 回调 |
| `IoOps` | 前置声明 | `NioIoOps` / `EpollIoOps` / `KQueueIoOps` / `IoUringIoOps` | "我想监听哪些事件"（io_uring 除外，见下文） |
| `IoEvent` | 后置通知 | `NioIoEvent` / `EpollIoEvent` / `KQueueIoEvent` / `IoUringIoEvent` | "实际发生了哪些事件" |
| `IoRegistration` | 桥梁 | `DefaultNioRegistration` / `DefaultEpollIoRegistration` / `DefaultKqueueIoRegistration` / `DefaultIoUringIoRegistration` | `submit(IoOps)` 改兴趣、`cancel()` 注销、`attachment()` 拿底层对象 |

四者的调用时序：

```
Channel.doRegister()
  → SingleThreadIoEventLoop.register(IoHandle)
    → NioIoHandler.register(IoHandle) → 返回 IoRegistration
  → Channel 存下 volatile IoRegistration

Channel 侧随时 submit：
  → registration.submit(NioIoOps.READ) → key.interestOps(OP_READ)

IoHandler 侧 run() select 到就绪：
  → ((DefaultNioRegistration) key.attachment()).handle(readyOps)
    → IoHandle.handle(registration, NioIoOps.eventOf(readyOps))
      → AbstractNioUnsafe.handle() → dispatch CONNECT / WRITE / READ_AND_ACCEPT
```

#### IoHandle

`AbstractNioUnsafe implements NioIoHandle`——Channel 的 `unsafe()` 对象就是 IoHandle，不需要中间包装。handle() 的分发顺序有讲究：

```java
@Override
public void handle(IoRegistration registration, IoEvent event) {
    NioIoOps nioReadyOps = ((NioIoEvent) event).ops();
    // 1. 先 finishConnect，否则 NIO 会抛 NotYetConnectedException
    if (nioReadyOps.contains(NioIoOps.CONNECT)) {
        removeAndSubmit(NioIoOps.CONNECT);
        unsafe().finishConnect();
    }
    // 2. 再 WRITE，优先清空写队列释放内存
    if (nioReadyOps.contains(NioIoOps.WRITE)) {
        forceFlush();
    }
    // 3. 最后 READ_AND_ACCEPT
    if (nioReadyOps.contains(NioIoOps.READ_AND_ACCEPT) || nioReadyOps.equals(NioIoOps.NONE)) {
        read();
    }
}
```

`NioIoHandle` 只比 `IoHandle` 多一个 `selectableChannel()` getter，把 `SelectableChannel` 暴露给 `DefaultNioRegistration` 去调 `register(selector, ops, attachment)`。

#### NioIoOps

`NioIoOps` 把 `SelectionKey.OP_*` 四个位封装成不可变对象，220 行代码里有 8 个预定义常量 + 一套位操作：

```java
public static final NioIoOps NONE = new NioIoOps(0);
public static final NioIoOps ACCEPT = new NioIoOps(SelectionKey.OP_ACCEPT);
public static final NioIoOps CONNECT = new NioIoOps(SelectionKey.OP_CONNECT);
public static final NioIoOps WRITE = new NioIoOps(SelectionKey.OP_WRITE);
public static final NioIoOps READ = new NioIoOps(SelectionKey.OP_READ);
public static final NioIoOps READ_AND_ACCEPT = new NioIoOps(OP_READ | OP_ACCEPT);
public static final NioIoOps READ_AND_WRITE = new NioIoOps(OP_READ | OP_WRITE);
```

位操作：`contains(ops)` = `(this & ops) != 0`，`with(ops)` = OR，`without(ops)` = AND-NOT。

静态块构造一个 `NioIoEvent[] EVENTS` 数组（size = `OP_READ|OP_ACCEPT|OP_CONNECT|OP_WRITE` + 1 = 15），把 8 种常见组合一次性塞进各自索引位，`eventOf(int value)` 先查数组命中再 fallback 新建——这是 `NioIoHandler.processSelectedKeys()` 热路径上的快速对象获取。

#### IoRegistration

`DefaultNioRegistration` 持有 `SelectionKey` + `AtomicBoolean canceled`：

```java
@Override
public long submit(IoOps ops) {
    if (!isValid()) return -1;
    int v = ((NioIoOps) ops).value;
    key.interestOps(v);  // 一行——NIO 下 IoRegistration 就是对 SelectionKey 的薄封装
    return v;
}
```

`attachment()` 直接返回 `key.attachment()`——注册时 `DefaultNioRegistration` 自己就是 attachment（NioIoHandler.register 调 `selectableChannel.register(selector, ops, this)`），所以 attachment() 拿到的是 `DefaultNioRegistration` 自身。native 传输的 registration 完全不同（epoll 的状态机、kqueue 的 changeList 批处理、io_uring 的双路 submit），见 [IoOps and IoEvent Across Transports](?id=ioops-and-ioevent-across-transports) 与下文各 transport 章节。

#### AbstractNioChannel 如何驱动 submit

`AbstractNioChannel` 把 `IoRegistration` 存在一个 `volatile` 字段里（L61），两个辅助方法封装了 submit 调用：

```java
protected void addAndSubmit(NioIoOps addOps) {
    int interestOps = selectionKey().interestOps();  // attachment() 取出的 SelectionKey
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

这两个方法是 4.2 新增的——4.1 里各处直接调 `SelectionKey.interestOps(...)`，现在全部委托给 registration。好处是 epoll 的状态机逻辑被注册层隔离，Channel 代码只看 IoOps 抽象。

#### Registration Flow

注册本身发生在 `AbstractNioChannel.doRegister()`（4.2 重写）：

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

调用链：`IoEventLoop.register(IoHandle)` → `SingleThreadIoEventLoop.registerForIo0(handle, promise)` → `ioHandler.register(handle)` → `NioIoHandler.register(handle)` 创建 `DefaultNioRegistration` 并调 `selectableChannel.register(selector, NONE, this)` → 返回的 IoRegistration 被存进 Channel 的 volatile 字段。回调里还需要调 `handle.registered()`。

`NioEventLoop.register(...)` 也 `@Deprecated` 了，4.2 里只留下一个委派到 `super.register(unsafe())` 的壳。

#### IoOps and IoEvent Across Transports

`IoOps` 在四个 transport 里有三种完全不同的形态，差异直接来自底层系统调用模型：

| Transport | IoOps 形态 | 设计要点 |
| :--- | :--- | :--- |
| NIO | 位掩码（`SelectionKey.OP_*`） | 8 个预定义常量 + `EVENTS[]` 缓存热路径对象 |
| epoll | 位掩码（native `EPOLL*` 常量） | 与 NIO 同构，但常量来自 native lib，且 `EPOLLOUT` 兼作 connect 完成通知 |
| kqueue | **kevent 四元组**（filter/flags/fflags/data） | 不是位掩码；每个 filter 独立注册一条 kevent |
| io_uring | **完整 SQE 镜像**（13 字段） | 不是"兴趣声明"而是"操作本身"——completion-based 模型 |

`EpollIoOps` 与 `NioIoOps` 最像，但有两点不同。其一，类加载即绑定 native 库——静态块首行必须是 `Epoll.ensureAvailability()`，加载失败整个类不可用。其二，常量集来自 `Native` 类：`EPOLLIN` / `EPOLLOUT` / `EPOLLERR` / `EPOLLRDHUP` / `EPOLLET`，其中 `EPOLLOUT` 的注释明确写了它既是 writable again 也是 **connect 完成**的通知；`EPOLLRDHUP` 是 NIO 拿不到的半关闭通知。另有三个 package-private 组合掩码（`EPOLL_ERR_OUT_MASK = ERR|OUT` 等）供内部快速判定。`EVENTS` 数组的 size 是 `all.value + 2`（`all = OUT|IN|ERR|RDHUP`，**不含 `EPOLLET`**——ET 是修饰位，不参与就绪事件组合）。

kqueue 是另一套模型：kqueue 不是"一个 fd 一个兴趣位掩码"，而是"每个 filter（`EVFILT_READ` / `EVFILT_WRITE`）各注册一条 kevent"。所以 `KQueueIoOps`（94 行）直接镜像 `struct kevent` 的字段，**没有预定义常量、没有位运算、没有缓存数组**，只有一个工厂方法：

```java
public static KQueueIoOps newOps(short filter, short flags, int fflags) {
    return new KQueueIoOps(filter, flags, fflags, 0);
}
```

io_uring 走得更远。io_uring 不是 readiness 模型——提交的不是"我对读感兴趣"，而是"请执行一次 recv"，完成时回一个 CQE。`IoUringIoOps`（506 行）因此是 64 字节 `io_uring_sqe` 结构体的完整镜像（`opcode` / `flags` / `ioPrio` / `fd` / `union1`~`union6` / `len` / `userData` / `personality` 共 13 个字段），每个 opcode 对应一个静态工厂，javadoc 逐条链到 liburing.h 行号：

```java
static IoUringIoOps newAccept(int fd, byte flags, int acceptFlags, short ioPrio, ...);
static IoUringIoOps newConnect(int fd, byte flags, long remoteMemoryAddress, short data);
static IoUringIoOps newPollAdd(int fd, byte flags, int mask, int len, short data);
static IoUringIoOps newAsyncCancel(byte flags, long userData, short data); // userData 是上次 submit 的返回值
```

`IoEvent` 侧同样是"就绪通知 vs 完成通知"的分野。`NioIoEvent` / `EpollIoEvent` 只是包一层 ops；`KQueueIoEvent` 镜像 kevent 结果六字段（`ident` / `filter` / `flags` / `fflags` / `data` / `udata`）；`IoUringIoEvent` 是 CQE 镜像（`res` 系统调用返回值、`flags`、`opcode`、`userData`），另有仅 `IORING_SETUP_CQE32` 模式下非空的 `extraCqeData`——它映射共享完成队列内存，**不得在 `handle()` 之外持有引用**。kqueue 与 io_uring 的 event 对象都由 registration 持有一个实例、通过包私有 `update(...)` 原地复用，事件分派热路径零分配。

### IoHandlerContext

`SingleThreadIoEventLoop` 实现了 `IoHandlerContext`，给 IoHandler 暴露三个时间相关的方法：

```java
private final IoHandlerContext context = new IoHandlerContext() {
    @Override
    public boolean canBlock() {
        return !hasTasks() && !wakenUp.get();
    }
    @Override
    public long delayNanos(long currentTimeNanos) {
        ScheduledFutureTask<?> f = nextScheduledTask();
        if (f == null) return Long.MAX_VALUE;
        return f.delayNanos(currentTimeNanos);
    }
    @Override
    public long deadlineNanos() {
        ScheduledFutureTask<?> f = nextScheduledTask();
        return f == null ? -1 : f.deadlineNanos();
    }
};
```

#### delayNanos 与调度任务 deadline 联动

4.2 新增的 `select(context, oldWakenUp)` 内部通过 `context.delayNanos(currentTimeNanos)` 获取下一个调度任务的剩余时间，用它算出 select 超时时间上限：

```java
// NioIoHandler#select —— 4.2 核心循环
private void select(IoHandlerContext runner, boolean oldWakenUp) throws IOException {
    long delayNanos = runner.delayNanos(System.nanoTime());
    long selectDeadLineNanos = Long.MAX_VALUE;
    if (delayNanos != Long.MAX_VALUE) {
        selectDeadLineNanos = currentTimeNanos + delayNanos;
    }
    for (;;) {
        long timeoutMillis;
        if (delayNanos != Long.MAX_VALUE) {
            long millisBeforeDeadline = millisBeforeDeadline(selectDeadLineNanos, currentTimeNanos);
            if (millisBeforeDeadline <= 0) {
                // 调度任务到期了，必须立即返回让 EventLoop 去跑定时任务
                selector.selectNow();
                break;
            }
            timeoutMillis = millisBeforeDeadline; // 不超过 deadline
        } else {
            timeoutMillis = 0; // 无定时任务，完全阻塞（0 在 NIO 里表示无限等待）
        }
        if (!runner.canBlock() && wakenUp.compareAndSet(false, true)) {
            // 有未执行的任务或刚被唤醒，立即返回
            selector.selectNow();
            break;
        }
        int selectedKeys = selector.select(timeoutMillis);
        if (selectedKeys != 0 || wakenUp.get() || !runner.canBlock()) {
            break; // 有就绪事件 / 被唤醒 / 有任务要跑
        }
        ...空轮询重建检测...
    }
}
```

4.1 里 `NioEventLoop.select(timeoutMillis)` 超时由 `taskQueue.poll(timeout, NANOSECONDS)` 自己算，EventLoop 要同时管理 selector 阻塞和定时任务；4.2 把"下一个定时任务什么时候到期"的决策收进 `IoHandlerContext.delayNanos()`，由 EventLoop 算好传给 IoHandler，IoHandler 只负责用这个值约束 select 超时。这样定时任务临近到期时 select 会以短超时甚至立即返回，EventLoop 主循环拿到控制权后先跑任务再回来跑 IO。

### Migration

4.2 中所有 transport-specific 的 `EventLoopGroup` 均已 `@Deprecated`：

```java
/**
 * @deprecated Use {@link MultiThreadIoEventLoopGroup} with {@link EpollIoHandler#newFactory()}.
 */
@Deprecated
public final class EpollEventLoopGroup extends MultiThreadIoEventLoopGroup {
```

新写法统一走 `MultiThreadIoEventLoopGroup` + `IoHandlerFactory`：

```java
EventLoopGroup group = new MultiThreadIoEventLoopGroup(NioIoHandler.newFactory());
// epoll：EpollIoHandler.newFactory()
// kqueue：KQueueIoHandler.newFactory()
// io_uring：IoUringIoHandler.newFactory()
```

`NioEventLoop` 在 4.2 里被 `@Deprecated` 并缩到 233 行，`extends SingleThreadIoEventLoop`，只剩 `selectorProvider()` / `register(...)` / `rebuildSelector()` / `registeredChannels()` 几个委派方法。**`NioEventLoop#run` 与 `#processSelectedKeys` 已不存在**，全部迁到 `NioIoHandler`。

> [!NOTE]
>
> `MultiThreadIoEventLoopGroup` 存在，但**不存在** `MultiThreadIoEventLoop` 这个类；单线程侧的类名是 `SingleThreadIoEventLoop`。

## NIO

### Select Loop

`NioIoHandler#run(IoHandlerContext)` 的签名与 4.1 不同，返回 int 表示本轮处理的就绪数：

```java
public int run(IoHandlerContext context) {
    ...
    switch (selectStrategy.calculateStrategy(selectNowSupplier, !context.canBlock())) {
        case SelectStrategy.CONTINUE:
            return 0;
        case SelectStrategy.BUSY_WAIT:
            fallthrough = true;
            break;
        case SelectStrategy.SELECT:
            fallthrough = true;
            // fall-through
        default:
    }
    ...
}
```

select 循环如何用 `context.delayNanos()` 约束阻塞超时、与 EventLoop 定时任务队列联动——见 [IoHandlerContext](?id=iohandlercontext)。

空轮询（JDK epoll bug）的防护常量：

```java
private static final int MIN_PREMATURE_SELECTOR_RETURNS = 3;
private static final int SELECTOR_AUTO_REBUILD_THRESHOLD;

static {
    int threshold = SystemPropertyUtil.getInt("io.netty.selectorAutoRebuildThreshold", 512);
    if (threshold < MIN_PREMATURE_SELECTOR_RETURNS) {
        threshold = 0;
    }
    SELECTOR_AUTO_REBUILD_THRESHOLD = threshold;
}
```

触发重建的条件：

```java
} else if (SELECTOR_AUTO_REBUILD_THRESHOLD > 0 && selectCnt >= SELECTOR_AUTO_REBUILD_THRESHOLD) {
    selector = selectRebuildSelector(selectCnt);
    selectCnt = 1;
    break;
}
```

即连续 512 次 `select()` 立即返回就认为 Selector 已损坏，重建并把旧 Selector 上的 key 全部迁移过去（4.1 的 `unexpectedSelectorWakeup()` 方法在 4.2 已删除，改为内联计数）。

### SelectedKeys Optimization

JDK 的 `Selector.selectedKeys()` 返回 `Set<SelectionKey>`，遍历需要创建 Iterator 且有哈希探测成本。Netty 用反射把这两个字段换成自己的数组实现：

```java
private SelectedSelectionKeySet selectedKeys;

private static final boolean DISABLE_KEY_SET_OPTIMIZATION =
        SystemPropertyUtil.getBoolean("io.netty.noKeySetOptimization", false);
```

处理时逐个置 null 以便 GC：

```java
final SelectionKey k = selectedKeys.keys[i];
// null out entry in the array to allow to have it GC'ed once the Channel close, See #2363
selectedKeys.keys[i] = null;
processSelectedKey(k);
```

### Read / Write

```java
protected int doReadBytes(ByteBuf byteBuf) throws Exception {
    final RecvByteBufAllocator.Handle allocHandle = unsafe().recvBufAllocHandle();
    allocHandle.attemptedBytesRead(byteBuf.writableBytes());
    return byteBuf.writeBytes(javaChannel(), allocHandle.attemptedBytesRead());
}
```

写侧统一转成 `ByteBuffer[]` 再交给 JDK：

```java
int maxBytesPerGatheringWrite = ((NioSocketChannelConfig) config).getMaxBytesPerGatheringWrite();
ByteBuffer[] nioBuffers = in.nioBuffers(1024, maxBytesPerGatheringWrite);
int nioBufferCnt = in.nioBufferCount();
// Always use nioBuffers() to workaround data-corruption. See https://github.com/netty/netty/issues/2761
switch (nioBufferCnt) {
    case 0:  writeSpinCount -= doWrite0(in); break;
    case 1:  /* ch.write(buffer) */ break;
    default: /* ch.write(nioBuffers, 0, nioBufferCnt) */ break;
}
```

`writeSpinCount` 默认 **16**（`DefaultChannelConfig`）。用尽预算后走 `incompleteWrite(writeSpinCount < 0)`：负表示内核暂不可写，注册 `OP_WRITE` 等 EPOLLOUT 唤醒；零表示数据没发完但 Socket 仍可写，只丢一个 flushTask 稍后重试。

### Limits

NIO 的短板不在性能而在**能力**：JDK `SocketChannel` 没有暴露 `TCP_CORK`、`TCP_NOTSENT_LOWAT`、`SO_BUSY_POLL`、`sendmmsg` 这类 Linux 特有选项；读数据必须经 `ByteBuffer` 中转；JDK Selector 自身有空轮询的历史 bug。

## epoll

### Event Loop

`EpollEventLoop` 在 4.2 同样 `@Deprecated` 且不含任何 `epoll_wait` 逻辑：

```java
@Deprecated
public class EpollEventLoop extends SingleThreadIoEventLoop {

    @Override
    public int registeredChannels() {
        return ((EpollIoHandler) ioHandler()).numRegisteredChannels();
    }
}
```

真正的循环在 `EpollIoHandler#run`：

```java
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

`Native.epollWait` 的返回值被打包成一个 long：高 32 位是就绪数，低 8 位标记 timerfd 是否被触发（`epollReady(result) = (int)(result >>> 32)`、`epollTimerWasUsed(result) = (result & 0xff) != 0`）。

事件数组容量：

```java
if (maxEvents == 0) {
    allowGrowing = true;
    events = new EpollEventArray(4096);
} else {
    allowGrowing = false;
    events = new EpollEventArray(maxEvents);
}
```

默认 4096 且**可随负载翻倍增长**（`allowGrowing && strategy == events.length()` 时 `events.increase()`）。

### Wakeup and Timeout

epoll 侧的超时与唤醒不靠 `epoll_wait` 的 timeout 参数，而是两个额外 fd，都在 handler 构造时以 `EPOLLIN | EPOLLET` 注册（这是 `EPOLLET` 在主包中仅有的内部用途）：

- **eventFd**（唤醒）：`wakeup()` 就是 `Native.eventFdWrite(eventFd, 1L)`。写入后 `pendingWakeup=true`；下一轮若因某种原因没取到 eventFd 事件，用 1 秒兜底的 `epollWaitTimeboxed()` 再等一次，超时仍无则记 `Missed eventfd write (not seen after > 1 second)` 警告并清标志——防止一次丢失的 write 让 EventLoop 永久阻塞。
- **timerFd**（超时）：阻塞等待前比较 `context.deadlineNanos()` 与缓存的 `prevDeadlineNanos`。deadline 没变走 `epollWaitNoTimerChange()`（零系统调用调整）；变了才 arm timerFd（`epollWait(context, deadline)`，纳秒部分有 `MAX_SCHEDULED_TIMERFD_NS` 上限）。返回值打包进 long：高 32 位就绪数、低 8 位标记 timer 是否触发过（触发过则重置 `prevDeadlineNanos` 强制下轮重新 arm）。

`processReady` 的分派同样体现这个编码：普通 fd 事件 `result += 2`，timerFd 事件 `result |= 1`——所以 `packed >>> 1` 是就绪数、`packed & 1` 是 timer 标志，一个 int 同时载两种信息。

### Registration

注册对象是 `EpollIoHandler` 的私有内部类 `DefaultEpollIoRegistration`，核心是一个三态状态机：

```java
private enum RegistrationState {
    Pending,    // 尚未 epollCtlAdd
    Added,      // 已 epollCtlAdd
    Cancelled   // 已 epollCtlDel
}

@Override
public long submit(IoOps ops) {
    EpollIoOps epollIoOps = cast(ops);
    synchronized (this) {
        switch (state) {
            case Cancelled:
                return -1;
            case Pending:
                if (epollIoOps.value == EpollIoOps.NONE.value) {
                    return 0; // 还没 add 过，NONE 等于无操作
                }
                Native.epollCtlAdd(epollFd.intValue(), handle.fd().intValue(), epollIoOps.value);
                state = RegistrationState.Added;
                return epollIoOps.value;
            case Added:
                if (epollIoOps.value == EpollIoOps.NONE.value) {
                    // 必须真正 DEL：否则 EPOLLHUP / EPOLLERR 会永远触发通知
                    Native.epollCtlDel(epollFd.intValue(), handle.fd().intValue());
                    return 0;
                }
                Native.epollCtlMod(epollFd.intValue(), handle.fd().intValue(), epollIoOps.value);
                return epollIoOps.value;
            default:
                throw new IllegalStateException();
        }
    }
}
```

与 NIO 的 `DefaultNioRegistration` 对照，三个关键差异：

- **锁**：`submit` 整个方法体 `synchronized (this)`——NIO 的 `key.interestOps()` 由 Selector 内部锁保护，而 `epoll_ctl` 没有这层保证，registration 自己上锁。
- **attachment()** 返回的是 `nativeArrays`（native 事件数组等资源持有者），**不是 registration 自身**；就绪分派不靠 attachment 回捞，而是靠 handler 内一张 fd → registration 的 `registrations` map 直接查表。
- **cancel() 有 FD 复用防护**：先在 synchronized 块置 `Cancelled`，再按调用线程分流（EventLoop 线程内直接 `cancel0()`，否则 `executor.execute(this::cancel0)`）。`cancel0()` 从 map 按 fd 摘除时，如果摘出来的不是自己（fd 关闭后被内核复用给了新 Channel），要放回原 registration 并直接返回；`epollCtlDel` 也只在 fd 仍打开时调用——fd 关闭时内核会自动把它从 epoll 移除。

事件到达时把 native 位掩码还原成共享 ops 对象再回调（`eventOf` 命中 `EVENTS[]` 缓存，零分配）：

```java
void handle(long ev) {
    handle.handle(this, EpollIoOps.eventOf((int) ev));
}
```

#### Lazy Registration and Dispatch

`register()` 本身**不调任何 `epoll_ctl`**——只把 `DefaultEpollIoRegistration` 放进 `IntObjectHashMap`（初始容量 4096，以 fd 为键），并 assert 同 fd 的旧 registration 已失效（register 时的 FD 复用防护）。真正的 `epollCtlAdd` 推迟到第一次提交非 `NONE` 的 ops 才发生，与状态机的 `Pending` 初态对应。

就绪分派是 fd → registration 的查表（`registrations.get(fd)`），查不到说明 fd 已废弃但还留在 epoll 兴趣集里，此时**主动 `epollCtlDel` 清理**——否则这个僵尸 fd 的 HUP/ERR 事件会每轮都触发一次空分派：

```java
DefaultEpollIoRegistration registration = registrations.get(fd);
if (registration != null) {
    registration.handle(ev);
} else {
    // 收到已废弃 fd 的事件，从 epoll 集合移除；失败可忽略（fd 可能已关闭）
    Native.epollCtlDel(epollFd.intValue(), fd);
}
```

### Read Loop

```java
final boolean shouldBreakEpollInReady(ChannelConfig config) {
    return socket.isInputShutdown() && (inputClosedSeenErrorOnRead || !isAllowHalfClosure(config));
}
```

（注意 epoll 侧方法名是 `shouldBreakEpollInReady`，NIO 与 kqueue 侧叫 `shouldBreakReadReady`。）

循环继续条件用"读满即可能还有"的启发式：

```java
boolean maybeMoreDataToRead() {
    return lastBytesRead() == attemptedBytesRead();
}

@Override
public final boolean continueReading() {
    // We must override the supplier which determines if there maybe more data to read.
    return continueReading(defaultMaybeMoreDataSupplier);
}
```

> [!NOTE]
>
> 4.2 中 `epollInReadyRunnablePending` 字段**已完全移除**，"边缘触发下必须循环读到 EAGAIN"的旧逻辑被上述启发式统一取代。

### Edge vs Level Triggered

**4.2 中 `EpollMode` 整个枚举已 `@Deprecated`，Netty 一律使用水平触发**：

```java
/**
 * The epoll mode to use.
 *
 * @deprecated Netty always uses level-triggered mode.
 */
@Deprecated
public enum EpollMode {
    EDGE_TRIGGERED,
    LEVEL_TRIGGERED
}
```

```java
@Deprecated
public EpollMode getEpollMode() {
    return EpollMode.LEVEL_TRIGGERED;
}

@Deprecated
public EpollChannelConfig setEpollMode(EpollMode mode) {
    LOGGER.debug("Changing the EpollMode is not supported anymore, this is just a no-op");
    return this;
}
```

`epollInReady()` 内部**没有任何 `getEpollMode()` 分支**；`EPOLLET` 在整个 epoll 主包中只用于内部的 eventFd / timerFd 注册。**没有任何系统属性能改回边缘触发。**

### Write

单缓冲走 `sendAddress` / `send`：

```java
if (buf.hasMemoryAddress()) {
    int localFlushedAmount = socket.sendAddress(buf.memoryAddress(), buf.readerIndex(), buf.writerIndex());
} else {
    final ByteBuffer nioBuf = ...;
    int localFlushedAmount = socket.send(nioBuf, nioBuf.position(), nioBuf.limit());
}
```

gathering write 走 `writev`：

```java
final long localWrittenBytes = socket.writevAddresses(array.memoryAddress(0), cnt);
// 或
final long localWrittenBytes = socket.writev(nioBuffers, 0, nioBufferCnt, expectedWrittenBytes);
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

`public final class EpollChannelOption<T> extends UnixChannelOption<T>`，4.2 中自有 20 个常量：

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

另有从 `UnixChannelOption` 继承的 `SO_REUSEPORT`、`DOMAIN_SOCKET_READ_MODE`。

### Availability

`Epoll` 类只有一个开关 `io.netty.transport.noNative`（默认 false，epoll / kqueue / io_uring 共用）。不可用有两类原因：显式禁用，或静态块里 `Native.newEpollCreate()` / `newEventFd()` 抛异常（缺 JNI 库、glibc 版本过低、memlock 限制等）。诊断用 `Epoll.unavailabilityCause()`。

> [!WARNING]
>
> 官方 Linux 构建都链接 GLIBC，使用 musl libc 的发行版（Alpine）不被官方原生库支持，只能退回 NIO。

## kqueue

`KQueueIoHandler` 存在，`public final class KQueueIoHandler implements IoHandler`，用法与 epoll 对称：`new MultiThreadIoEventLoopGroup(KQueueIoHandler.newFactory())`。`KQueueEventLoopGroup` 保留但已 `@Deprecated`；**不存在 `KQueueEventLoop` 类**（包内只有 Group）。适用于 macOS / BSD。

kqueue 侧保留了 `shouldBreakReadReady()` 命名，与 epoll 的 `shouldBreakEpollInReady()` 不同。

### Registration via changeList

`DefaultKqueueIoRegistration` 的 `submit` **不立即做系统调用**，而是把 kevent 追加到 `changeList`（一个 native 内存的 `KQueueEventArray`），等下一轮 `Native.keventWait(kqueueFd, changeList, eventList, ...)` 时随 changelist 一起提交内核，返回后 `changeList.clear()`：

```java
@Override
public long submit(IoOps ops) {
    KQueueIoOps kQueueIoOps = cast(ops);
    if (!isValid()) return -1;
    if (executor.isExecutorThread(Thread.currentThread())) {
        evSet(filter, flags, fflags, data);
    } else {
        executor.execute(() -> evSet(filter, flags, fflags, data));
    }
    return 0; // kqueue 的 submit 返回值无语义
}

private void evSet(short filter, short flags, int fflags, long data) {
    if (cancellationPending) return;
    changeList.evSet(handle.ident(), filter, flags, fflags, data, id);
}
```

注意 `evSet` 最后一个参数：`udata` 固定写成 **registration id**——这是 kevent 返回时把事件路由回 registration 的凭据（`KQueueIoEvent.udata()`）。另外 `register()` 会拒绝 `KQUEUE_WAKE_UP_IDENT`，该 ident 保留给内部 wakeup user event。

`cancel()` 是两段式：CAS 置 `canceled` 后**不立刻从 registrations map 删除**，而是置 `cancellationPending` 并投入 `cancelledRegistrations` 队列，等本轮已取出的事件全部处理完再统一移除——否则已取出但尚未分派的事件会查到空注册。处于 `cancellationPending` 的 registration 对后续 `submit` / `handle` 都直接忽略。

### Wakeup via EVFILT_USER

kqueue 没有 eventfd / timerfd 这类额外 fd——它把 wakeup 本身建模成一个 **`EVFILT_USER` 类型的 kevent**，ident 固定为 0（`KQUEUE_WAKE_UP_IDENT`），构造时用一次 `Native.keventAddUserEvent(kqueueFd, 0)` 注册进去。`wakeup()` 就是对这张已注册 user event 的一次触发：`Native.keventTriggerUserEvent(kqueueFd, KQUEUE_WAKE_UP_IDENT)`。

这套模型的好处是：wakeup 事件直接走 `keventWait` 返回的 `eventList`，无需额外的事件源，所以 `processReady` 只需在 for 循环里判断 `filter == EVFILT_USER` 就知道这是内部唤醒还是 IO 事件——识别成本比 epoll 的 eventFd 分支还低，也没有 EPOLLET 的边缘触发残留问题。代价是注册时要把 ident=0 占死，`register()` 因此要显式拒绝 0 并断言"同 ident 复用必因 FD 关闭"。

`run()` 里有一个 NIO 4.1 就传下来、但 kqueue 侧更需要的 `wakenUp` 竞态修复：wakeup 必须在 **进入 `kqueueWait` 前** 置位（`WAKEN_UP_UPDATER.compareAndSet(this, 0, 1)`），否则任务队列在 `keventWait` 期间提交但 wakeup 写入晚于 wait 阻塞，会等到下一次定时超时才醒来。`run()` 拿到返回值后还会再检查一次 `if (wakenUp == 1) wakeup0()`，以覆盖"wait 刚返回就又有任务提交"的窄窗口。

`kqueueWait(context, oldWakeup)` 的 `oldWakeup` 参数就是为这层竞态防护准备的——若 wakeup 已在 wait 前发生且 `canBlock` 为 false，直接走 `kqueueWaitNow()` 零超时返回，避免在 `keventWait` 内部阻塞。另外 kqueue 不支持 `SelectStrategy.BUSY_WAIT`，源码里直接 fall-through 到 SELECT 分支；**eventList 也会 grow**，`strategy == eventList.capacity()` 时 `eventList.realloc(false)`，与 epoll 侧 `allowGrowing && strategy == events.length()` 同构但 API 名不同。

## io_uring

包路径 `io.netty.channel.uring`（4.1 时代是孵化器包 `io.netty.incubator.channel.uring`，4.2 已迁入正式包）。

```java
/**
 * io_uring is a high I/O performance scalable interface for fully asynchronous Linux syscalls.
 * While Netty 4.2 generally requires Java 8 or newer, this optional io_uring native transport
 * requires Java 9 or newer.
 */
package io.netty.channel.uring;
```

**4.2 中不存在 `IoUringEventLoopGroup` 或 `IoUringEventLoop`**——io_uring 只有 `IoHandler` 一条路：

```java
EventLoopGroup group = new MultiThreadIoEventLoopGroup(IoUringIoHandler.newFactory());
```

门槛与默认值：

| 项      | 值                                                                                                                         |
| :----- | :------------------------------------------------------------------------------------------------------------------------ |
| JDK    | 9+                                                                                                                        |
| 内核     | 代码硬下限 **5.9**（`Native.checkKernelVersion`，可用 `-Dio.netty.transport.iouring.enforceKernelVersion=false` 绕过）；README 推荐 **5.14** |
| ring 大小 | `DEFAULT_RING_SIZE = max(16, io.netty.iouring.ringSize)`，默认 **128**                                                        |
| iovec  | `io.netty.iouring.numElementsIoVec` 默认 `10 * IOV_MAX`                                                                      |

额外能力：buffer ring（`IoUringBufferRing`）、multishot accept/recv、zero-copy send（`IORING_SEND_ZC_SUPPORTED`）。这些是 epoll 拿不到的。

### Submission and Completion

io_uring 的 `IoRegistration.submit()` 返回值**有真实语义**（NIO 返回 ops 值、kqueue 恒返回 0）：它返回一个 long 型提交标识，之后传给 `IoUringIoOps.newAsyncCancel(userData)` 即可取消这次操作。`DefaultIoUringIoRegistration.submit` 内部有快慢两条路径：

```java
public long submit(IoOps ops) {
    IoUringIoOps ioOps = (IoUringIoOps) ops;
    if (!isValid()) return INVALID_ID;
    if ((ioOps.flags() & Native.IOSQE_CQE_SKIP_SUCCESS) != 0) {
        // 设计前提是每次提交至少回一个 CQE；SKIP_SUCCESS 只在失败时产生 CQE，不支持
        throw new IllegalArgumentException("IOSQE_CQE_SKIP_SUCCESS not supported");
    }
    long userData = ioOps.userData();
    if (canUseFastPath(userData)) {
        // userData 装得进 short：把 registrationId + opcode + data 打包进 SQE 的 user_data 字段
        long packedSeq = UserData.encode(id, ioOps.opcode(), (short) userData);
        ... enqueueSqe(..., packedSeq, ...);
        return packedSeq;
    }
    long token = pendingOps.nextToken(); // 否则走旁表慢速路径
    pendingOps.registerNormal(token, id, ioOps.opcode(), userData);
    ... enqueueSqe(..., token, ...);
    return token;
}
```

要点：

- **打包编码**：fast path 把 `registrationId + opcode + (short) userData` 三元组编码进 SQE 的 64 位 `user_data`，CQE 返回时一次解包即可路由，无需查表；userData 超出 short 范围才退化为 token + `pendingOps` 旁表。
- **registrationId 恒为正**：`nextRegistrationId()` 从 1 递增、到 `Integer.MAX_VALUE` 回绕到 1——正值用于区分普通 Channel 完成事件与内部 token（eventfd 读、ring 自身的超时 NOP 等）。
- **跨线程提交**：调用方不在 EventLoop 线程时 `executor.execute(...)` 转投后再 `enqueueSqe`；入队本身不触发 `io_uring_enter`，由 handler 主循环统一 submit。
- **cancel 延迟生效**：`cancel()` CAS 后若 `outstandingCompletions > 0`（还有未回收的 CQE），只置 `removeLater`，等完成事件全部 drain 才从 `registrations` map 移除——保证迟到的 CQE 仍能路由到正确的 registration。
- **attachment()** 返回 `IoUringIoHandler.this`——四种 transport 的 attachment 语义全不同：NIO 是 registration 自身，epoll / kqueue 是各自的 `nativeArrays`，io_uring 是 handler 本体。

#### UserData Encoding

fast path 的打包位布局（`UserData.encode`，注释里有 ASCII 图）：

```
 63             32 31      24 23      16 15       0
[      id        ][ unused ][   op    ][   data    ]
```

即 `(id << 32) | (op << 16) | data`。由于 `id` 恒为正（1..`Integer.MAX_VALUE`），编码结果的符号位恒 0——所以完成侧只需判断 **`udata >= 0` 即 fast path**，一次解包拿到 registrationId 直接查 `registrations` map，无需任何旁表。slow path 的 token 是 `Long.MIN_VALUE | sequence`（符号位置 1，恒负），内部保留值 `EVENTFD_TOKEN` / `RINGFD_TOKEN` 占用 sequence 1 和 2、普通提交从 3 开始递增——负数区间天然与 fast path 分区。

#### Completion Dispatch

每个 CQE 的分发顺序（`IoUringIoHandler.handle`）：

1. `udata == EVENTFD_TOKEN` → eventfd 读完成（wakeup 回执），清 `eventfdReadSubmitted` 并**重新提交下一次 eventfd 读**（重新 arm，等待下次 wakeup）。
2. `udata == RINGFD_TOKEN` → 内部超时 NOP 完成，直接忽略。
3. `udata >= 0` → fast path：解包出 id 查 map，registration 已取消则 debug 日志丢弃（迟到的 CQE）。
4. 其余 → slow path：`pendingOps.findSlot(udata)` 查旁表取 registrationId / op / userData，再经 `registrations` map 路由——与 fast path 走同一张 live 表，保证取消语义一致。旁表 `PendingOpMap` 是带墓碑的开放寻址哈希表，避免每完成一次就 boxing / 分配。

slow path 的槽位回收有一个 multishot 细节：**仅当 CQE 未置 `IORING_CQE_F_MORE`**（内核声明这个 SQE 不会再产出 CQE）才 `pendingOps.release(slot)`——multishot recv / poll 这类操作一个 token 对应一串 CQE，提前释放会把后续完成路由成"unknown sequence"。

#### Timeout SQE

io_uring 侧的阻塞超时**不用 `io_uring_enter` 的参数**，而是往 SQ 里追加一条 `IORING_OP_TIMEOUT`（`addTimeout(timeoutMemoryAddress, RINGFD_TOKEN)`），随 `submitAndGet()` 一起提交：

```java
timeoutMemory.putLong(KERNEL_TIMESPEC_TV_SEC_FIELD, seconds);
timeoutMemory.putLong(KERNEL_TIMESPEC_TV_NSEC_FIELD, nanoSeconds);
if (linkTimeout) {
    submissionQueue.addLinkTimeout(timeoutMemoryAddress, RINGFD_TOKEN);
} else {
    submissionQueue.addTimeout(timeoutMemoryAddress, RINGFD_TOKEN);
}
int submitted = submissionQueue.submitAndGet();
```

所有 add*Timeout 共用同一块 `timeoutMemory`——源码注释明确前提："只有紧随其后立刻 submit 才安全"，因为内核在 submit 后才把 timespec 视为 stable。run 循环的阻塞路径是：无完成事件且 `canBlock` → 先 `submitEventFdRead()` arm 好 wakeup 回执 → 再 `submitAndWaitWithTimeout(sq, false, context.delayNanos(...))`；已有完成事件则只 `submitAndClearNow` 不阻塞。完成侧每轮最多处理 128 批，期间检测 `IORING_SQ_CQ_OVERFLOW` 并 warn 提示调大 ring——CQ 溢出时内核会把事件攒着，延迟会毛刺化。

#### Buffer Ring

io_uring 独有的 **per‑kernel buffer pool**：handler 启动时从 `IoUringBufferRingConfig.getInternBufferRingConfigs()` 读配置，按每个 `bgId` 一次 `Native.ioUringRegisterBufRing(ringFd, bufferRingSize, bufferGroupId, flags)` 注册到内核，返回的内存地址由 `Buffer.wrapMemoryAddressWithNativeOrder` 包成 `IoUringBufferRing` 对象，放进 `registeredIoUringBufferRing` 映射里按 `bgId` 查找。

ring 的扩展语义：`IoUringBufferRingConfig` 构造器里 `batchSize = bufferRingSize / 2` 意味着 ring 扩张时**每次批增半容量**；`IOU_PBUF_RING_INC` 标志（4.2 提供 `IoUring.isRegisterBufferRingIncSupported()` 探测内核能力）切换"incremental" 模式——允许 ring 在运行时动态扩容/缩容，而不是一次注册定死。

`IoUringIoOps.newRecv(fd, flags, ioPrio, recvFlags, addr, length, data, bid)` 的重载末参是 buffer ID（short）。当提交 recv 类 SQE 时把 `IOSQE_BUFFER_SELECT` 塞进 `flags`，内核就会从指定 `bgId` 的 buffer ring 里自动分配一个 buffer 填充，CQE 附带分配到的 buffer ID；用户侧通过 `IoUringBufferRingAllocator` 回收这批 buffer。epoll / kqueue 只能让用户预分配好 `ByteBuffer` 交给 syscall，内核始终看不到 buffer pool 结构——这是 io_uring buffer ring 的独有序列号（zero-copy 接收减少一次用户态 buffer 拷贝）。

#### Zero‑Copy Send and Multishot

`IoUringIoOps` 提供两个额外发送工厂，epoll 侧都没有：

- `newSendZc(fd, memoryAddress, length, flags, data, zcFlags)` → `IORING_OP_SEND_ZC`，内核直接从用户指针 DMA 到网卡，省一次拷贝；handler 侧运行时探测 `IORING_SEND_ZC_SUPPORTED`，不支持则退回普通 send。
- `newSendmsgZc(fd, flags, msgFlags, address, data)` → `IORING_OP_SENDMSG_ZC`，zero‑copy 的 gather send。

multishot 不在工厂层——它是 **SQE 的 flags 位（`IOSQE_MULTISHOT`）**，由上层 Channel 代码在组装 ops 时加上。multishot 模式下内核会在一次 poll / accept / recv 上持续触发 CQE，直到显式关闭或达到上限，大幅减少"每来一个事件就一次 SQE 入队"的开销。源码注释 `IORING_CQE_F_MORE` 标志的语义直接联动：multishot 期间的 CQE 都带这个标志，直到最后一条不带；handler 侧的 slow path 槽位回收逻辑（**仅 `IORING_CQE_F_MORE` 未置位才 release**）就是为 multishot 一个 token 一串 CQE 的语义量身定做的。

内核能力探测贯穿全程：`IoUring.isSupported()`、`IoUring.isSendZcSupported()`、`IoUring.isRegisterBufferRingIncSupported()`、以及 handler 硬编码的内核版本下限（默认 5.9、推荐 5.14）。4.2 的设计取舍是**能力先编译进 Native 类，运行时探测失败就降级**，而非在编译时裁剪 API——这让同一份 Netty jar 可以跑在不同内核版本上。

## Choice

| Transport  | 平台           | 依赖             | 适用场景                             |
| :--------- | :----------- | :------------- | :------------------------------- |
| NIO        | 全平台          | 仅 JDK          | 默认选择、跨平台部署、musl 发行版              |
| epoll      | Linux        | `netty-transport-native-epoll` | 追求极限性能、需要 TCP_CORK/sendmmsg/splice |
| kqueue     | macOS / BSD  | `netty-transport-native-kqueue` | macOS 上替代 NIO                    |
| io_uring   | Linux 5.9+   | `netty-transport-native-io_uring` + JDK9+ | 新内核上进一步降低系统调用开销                 |

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
4. [Netty 4.2.0 release notes](https://netty.io/news/2025/04/03/4-2-0.html)
5. [io_uring 论文](https://kernel.dk/io_uring.pdf)
