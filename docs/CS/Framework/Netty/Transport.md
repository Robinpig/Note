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

### Registration

注册对象是 `EpollIoHandler` 的私有内部类 `DefaultEpollIoRegistration`，内部是 `Pending → Added → Cancelled` 状态机；`submit(IoOps)` 按当前状态走 `epollCtlAdd` / `epollCtlMod` / `epollCtlDel`。`IoOps` 实现 `EpollIoOps` 描述 EPOLLIN/OUT/ERR/RDHUP 等位。

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
