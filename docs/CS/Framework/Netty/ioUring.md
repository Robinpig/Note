## Introduction

io_uring 是 Linux 内核提供的**真异步** IO 接口，也是 Netty 4.2.19 中正式包 `io.netty.channel.uring` 的原生传输后端。本文聚焦 io_uring 的内核模型、它与 epoll Reactor 的本质差异，以及 Netty 在 `IoHandler` 抽象下如何接入 SQ/CQ。所有结论以本地仓库 `netty-4.2.19.Final` 源码为准。

> [!NOTE]
>
> 4.1 时代 io_uring 是独立孵化器项目（包名 `io.netty.incubator.channel.uring`）；4.2 把它收编进主线正式包 `io.netty.channel.uring`，且**只保留 `IoHandler` 形态**——整个包里既没有 `IoUringEventLoopGroup` 也没有 `IoUringEventLoop`（源码：`transport-classes-io_uring/.../IoUringIoHandler.java:54`，且目录清单中无上述类）。循环本体复用 transport 模块的 `SingleThreadIoEventLoop`（已在 EventLoop.md 核对），io_uring 只提供 `IoUringIoHandler` 这一 `IoHandler` 后端实现。

### Kernel Model: SQ and CQ

io_uring 的核心是一对用户态与内核**共享内存**的环形队列：

- **Submission Queue (SQ)**：用户态写入、内核消费。每个槽位是一个 **SQE（Submission Queue Entry，64 字节）**，描述一次异步操作（`IORING_OP_READ` / `IORING_OP_WRITEV` / `IORING_OP_ACCEPT` / `IORING_OP_CONNECT` / `IORING_OP_TIMEOUT` 等）。
- **Completion Queue (CQ)**：内核写入、用户态消费。每个槽位是一个 **CQE（Completion Queue Entry）**，回报操作的完成结果与返回值（`res`）及标志（`flags`）。

```java
// 源码：transport-classes-io_uring/src/main/java/io/netty/channel/uring/SubmissionQueue.java:33-49
static final int SQE_SIZE = 64;
// SQE 字段偏移：opcode(0) flags(1) ioprio(2,u16) fd(4,s32) ... user_data(32) ...
private static final int SQE_USER_DATA_FIELD = 32;

// 源码：transport-classes-io_uring/src/main/java/io/netty/channel/uring/CompletionQueue.java:33-35
// CQE 字段偏移：user_data(0,8B) res(8,4B) flags(12,4B)
private static final int CQE_USER_DATA_FIELD = 0;
private static final int CQE_RES_FIELD = 8;
private static final int CQE_FLAGS_FIELD = 12;
```

Netty 用 `VarHandle` 直接读写与内核共享的 `ByteBuffer`（khead/ktail/kflags/submissionQueueArray / completionQueueArray），避免每次 ring 操作都走 JNI：

```java
// 源码：transport-classes-io_uring/src/main/java/io/netty/channel/uring/SubmissionQueue.java:53-89
private static final VarHandle INT_HANDLE =
        MethodHandles.byteBufferViewVarHandle(int[].class, ByteOrder.nativeOrder());
private final ByteBuffer kHead;   // 内核可见的 head 指针
private final ByteBuffer kTail;   // 内核可见的 tail 指针
private final ByteBuffer submissionQueueArray;  // SQE 数组，用户态与内核共享
```

关键收益：**提交与收割无需每次都陷入系统调用**。用户态把若干 SQE 填进 SQ，再调用一次 `io_uring_enter(2)` 即可批量提交并（可选地）等待 CQE，内核把完成结果写回 CQ。Netty 的 `SubmissionQueue.submit()` / `submitAndGet()` / `submitAndGetNow()` 最终都落到 `Native.ioUringEnter(...)`，并用 `IORING_ENTER_GETEVENTS` 标志在一次系统调用里同时完成"提交 + 收割"：

```java
// 源码：transport-classes-io_uring/src/main/java/io/netty/channel/uring/SubmissionQueue.java:278-288
private int submit(int toSubmit, int minComplete, int flags) {
    INT_HANDLE.setRelease(kTail, 0, tail);          // 推进 tail，内核即看到新 SQE
    int ret = ioUringEnter(toSubmit, minComplete, flags);
    head = (int) INT_HANDLE.getVolatile(kHead, 0);  // 读回 head，回收已消费的 SQE
    ...
}
```

`RingBuffer` 把 SQ 与 CQ 打包在一起，由 `Native.createRingBuffer(...)` 创建（源码：`RingBuffer.java:19-30`、`IoUringIoHandler.java:112`）：

```java
// 源码：transport-classes-io_uring/src/main/java/io/netty/channel/uring/RingBuffer.java:19-30
final class RingBuffer {
    private final SubmissionQueue ioUringSubmissionQueue;
    private final CompletionQueue ioUringCompletionQueue;
    ...
}
```

### True Async vs epoll Reactor

epoll 是**就绪通知**模型（Reactor）：`epoll_wait` 只告诉你"某个 fd 可读/可写"，真正的数据搬运仍需用户线程**同步**执行 `read`/`write` 系统调用，在内核态与用户态之间拷贝字节——它依然是同步 IO。

io_uring 是 **Proactor** 风格：用户态提交 IO 请求（SQE）后，由内核异步完成数据搬运，当 CQE 回来时数据已经就绪（或已写入完成），回调里直接拿到结果，无需再发一次同步 `read`/`write`。结合 EventLoop.md 的归类，io_uring 是 Netty 在 Linux 上"真异步"的落地。

### Netty Integration

`IoUringIoHandler implements IoHandler`（源码：`IoUringIoHandler.java:54`），是 io_uring 的 `IoHandler` 后端。它封装了 SQ/CQ 的提交与收割：

```java
// 源码：transport-classes-io_uring/src/main/java/io/netty/channel/uring/IoUringIoHandler.java:166-198
@Override
public int run(IoHandlerContext context) {
    SubmissionQueue submissionQueue = ringBuffer.ioUringSubmissionQueue();
    CompletionQueue completionQueue = ringBuffer.ioUringCompletionQueue();
    if (!completionQueue.hasCompletions() && context.canBlock()) {
        ...
        submitAndWaitWithTimeout(submissionQueue, false, timeoutNanos); // 一次 enter 提交+等 CQE
    } else {
        submitAndClearNow(submissionQueue);
    }
    ...
    ioCompletions = processCompletionsAndHandleOverflow(submissionQueue, completionQueue, completionCallback);
    return ioCompletions;
}
```

CQE 回收时按 `user_data` 反查注册表并回调到 `IoUringIoHandle.handle(...)`：

```java
// 源码：transport-classes-io_uring/src/main/java/io/netty/channel/uring/IoUringIoHandler.java:295-325
private boolean handle(int res, int flags, long udata, ByteBuffer extraCqeData) {
    ...
    int id = UserData.decodeId(udata);
    byte op = UserData.decodeOp(udata);
    ...
    DefaultIoUringIoRegistration registration = registrations.get(id);
    ...
    registration.handle(res, flags, op, userData, extraCqeData);  // 最终 → IoUringIoHandle.handle(...)
}
```

各 Channel 把 read/write/accept/connect 映射成对应的 SQE（`IoUringIoOps`），通过 `IoRegistration.submit(IoOps)` 入队：

| 操作        | Channel 方法                                   | 映射 opcode                       | 源码                                                            |
| :-------- | :------------------------------------------- | :------------------------------ | :------------------------------------------------------------- |
| accept    | `AbstractIoUringServerChannel`                | `IORING_OP_ACCEPT`              | `AbstractIoUringServerChannel.java:202-204`                    |
| connect   | `AbstractIoUringChannel.submitConnect(...)`   | `IORING_OP_CONNECT`             | `AbstractIoUringChannel.java:1293,1309`                         |
| read/recv | `AbstractIoUringStreamChannel.scheduleRead0`  | `IORING_OP_RECV`                | `AbstractIoUringStreamChannel.java:452-455`                     |
| write/send| `AbstractIoUringStreamChannel.scheduleWrite*` | `IORING_OP_SEND` / `IORING_OP_WRITEV` | `AbstractIoUringStreamChannel.java:285,331,391`     |

例如一次 `recv` 的提交路径：

```java
// 源码：transport-classes-io_uring/src/main/java/io/netty/channel/uring/AbstractIoUringStreamChannel.java:452-454
IoUringIoOps ops = IoUringIoOps.newRecv(fd, (byte) 0, ioPrio, recvFlags,
        IoUring.memoryAddress(byteBuf) + byteBuf.writerIndex(), byteBuf.writableBytes(), opsId);
readId = registration.submit(ops);   // → IoUringIoHandler.DefaultIoUringIoRegistration.submit → enqueueSqe
```

`registration.submit(...)` 最终把 SQE 写进 SQ（`IoUringIoHandler.java:600-645` 的 `submitFastPath0` / `submitSlowPath0` 调 `ringBuffer.ioUringSubmissionQueue().enqueueSqe(...)`），随后由 `run()` 统一 `io_uring_enter` 提交并收割。

### Enabling io_uring

`IoUringIoHandler` 提供三个 `newFactory` 重载，返回 `IoHandlerFactory`：

```java
// 源码：transport-classes-io_uring/src/main/java/io/netty/channel/uring/IoUringIoHandler.java:815-852
public static IoHandlerFactory newFactory() {
    return newFactory(new IoUringIoHandlerConfig());
}
public static IoHandlerFactory newFactory(int ringSize) { ... }              // :826
public static IoHandlerFactory newFactory(IoUringIoHandlerConfig config) {    // :838
    IoUring.ensureAvailability();
    ...
}
```

真实 Bootstrap 示例（类名已核对：`IoUringServerSocketChannel` 源码 `IoUringServerSocketChannel.java:27`，`IoUringSocketChannel` 源码 `IoUringSocketChannel.java:32`，二者分别 `implements ServerSocketChannel` / `SocketChannel`）：

```java
EventLoopGroup group = new MultiThreadIoEventLoopGroup(IoUringIoHandler.newFactory());
try {
    ServerBootstrap b = new ServerBootstrap();
    b.group(group)
     .channel(IoUringServerSocketChannel.class)   // 服务端
     .childHandler(new ChannelInitializer<SocketChannel>() {
         @Override
         protected void initChannel(SocketChannel ch) {
             // 实际类型为 IoUringSocketChannel，仍属于 SocketChannel
             ch.pipeline().addLast(new YourHandler());
         }
     });
    ChannelFuture f = b.bind(8080).sync();
    f.channel().closeFuture().sync();
} finally {
    group.shutdownGracefully();
}
```

### io_uring vs epoll

| 维度        | epoll（Reactor）                                  | io_uring（Proactor）                                       |
| :-------- | :---------------------------------------------- | :-------------------------------------------------------- |
| IO 模型     | 就绪通知；`epoll_wait` 后仍需同步 `read`/`write` 拷贝 | 内核异步完成；CQE 回执时数据已就绪，无需再发同步读写                    |
| 系统调用次数  | 至少两次语义：一次 `epoll_wait` 收割就绪 + 每次 `read`/`write` 各一次 | 提交与收割可合并到一次 `io_uring_enter`（批量 SQE/CQE）              |
| 文件 IO 真异步 | 不支持（文件 fd 永远"就绪"，epoll 无意义）              | 支持异步文件 `read`/`write`、`splice`、zero-copy send           |
| 批量/多 shot | `recvmmsg`/`sendmmsg`                            | multishot accept/recv（一次提交多次完成）、buffer ring              |
| 延迟/吞吐特征 | 成熟稳定，能力最全                                 | 系统调用开销更低、内核态完成度高，高并发网络与存储混合负载更具潜力              |
| 适用场景     | 通用 Linux 服务，追求稳定与功能齐全                     | 新内核（≥5.9）、能接受更高运维门槛、需要真异步/零拷贝的高性能服务           |
| 平台限制     | 仅 Linux                                        | 仅 Linux（且需 JDK 9+ 与配套 JNI 库）                          |

### Kernel and Prerequisites

io_uring 需要 Linux 内核支持。Netty 在静态初始化块里做可用性探测与版本校验：

```java
// 源码：transport-classes-io_uring/src/main/java/io/netty/channel/uring/Native.java:524-537
static void checkKernelVersion(String kernelVersion) {
    boolean enforceKernelVersion = SystemPropertyUtil.getBoolean(
            "io.netty.transport.iouring.enforceKernelVersion", true);
    boolean kernelSupported = checkKernelVersion(kernelVersion, 5, 9);
    if (!kernelSupported) {
        if (enforceKernelVersion) {
            throw new UnsupportedOperationException(
                    "you need at least kernel version 5.9, current kernel version: " + kernelVersion);
        } else {
            logger.debug("Detected kernel " + kernelVersion + " does not match minimum version of 5.9, " +
                    "trying to use io_uring anyway");
        }
    }
}
```

- **硬下限**：内核 **5.9**（源码 `Native.java:527`）。README 推荐 **5.14**（详见 Transport.md 的门槛表）。
- **JDK**：要求 **9+**（源码 `IoUring.java:100` 的 `PlatformDependent.javaVersion() >= 9` 判断）。
- **总开关**：`io.netty.transport.noNative` 统一控制（源码 `IoUring.java:94-96`）；可用 `IoUring.isAvailable()` / `IoUring.unavailabilityCause()` 探测（源码 `IoUring.java:229,422`）。
- **降级**：`newFactory(...)` 构造时就调用 `IoUring.ensureAvailability()`（源码 `IoUringIoHandler.java:839`），原生库缺失或内核过低会在"创建 group 时"立刻抛 `UnsatisfiedLinkError` / `UnsupportedOperationException`，而非等到 bind。

> [!NOTE]
>
> 某些受限或安全加固环境会**禁用 io_uring**（如容器 seccomp 策略、部分云厂商默认关闭 `io_uring_setup`）。Netty **不会**自动 fallback 到 epoll：`IoUringIoHandler` 不可用即直接抛错，需由业务侧按 `IoUring.isAvailable()` 自行选择 epoll 后端（源码：`IoUringIoHandler.java:97-101` 的 `IoUring.ensureAvailability()` 抛 `UnsatisfiedLinkError`）。许多高级特性（`acceptMultishotSupported`、`recvMultishotSupported`、`sendZcSupported`、`spliceSupported` 等）则在静态块里通过 `Native.ioUringProbe(...)` 探测，能力缺失时**自动降级**，无需用户开关（源码：`IoUring.java:112-138`）。

## Links

- [Netty](/docs/CS/Framework/Netty/Netty.md)
- [Transport 原生传输层](/docs/CS/Framework/Netty/Transport.md?id=io_uring)
- [EventLoop 与线程模型](/docs/CS/Framework/Netty/EventLoop.md)

## References

1. [io_uring 内核文档](https://docs.kernel.org/io_uring/)
2. [Netty 4.2 Javadoc - IoUringIoHandler](https://netty.io/4.2/api/io/netty/channel/uring/IoUringIoHandler.html)
3. [Netty native transports (wiki)](https://netty.io/wiki/native-transports.html)
4. [io_uring 论文](https://kernel.dk/io_uring.pdf)
