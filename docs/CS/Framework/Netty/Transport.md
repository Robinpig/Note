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

注意这里**没有** 4.1 式的 `fallthrough` 布尔标志：靠 Java 的 switch 穿透语义直接落到 `SELECT` 分支。select 循环如何用 `context.delayNanos()` 约束阻塞超时、与 EventLoop 定时任务队列联动——见 [IoHandlerContext](?id=iohandlercontext)。

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

`IoOps` 的实现 `EpollIoOps` 用常量描述 EPOLLIN / EPOLLOUT / EPOLLERR / EPOLLRDHUP 等位（源码：`transport-classes-epoll/src/main/java/io/netty/channel/epoll/EpollIoOps.java:35-50`），另有一个 `NONE`（`:58`）用于"什么都不关注"。

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
