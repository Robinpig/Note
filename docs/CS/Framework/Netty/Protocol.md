## Introduction

Protocol Support 层是在 [Pipeline](/docs/CS/Framework/Netty/ChannelHandler.md) 上叠加的一组开箱即用的 handler：TLS、HTTP/1.1、WebSocket、HTTP/2、HTTP/3。它们不参与 Reactor 线程模型，只是在入站方向把字节解成协议对象、出站方向反过来。

本文以 **Netty 4.2.19.Final**（git tag `netty-4.2.19.Final`，commit `64cc10f`）源码为准。模块划分：`handler`（`SslHandler` 在 `handler/src/main/java/io/netty/handler/ssl/`）、`codec-http`（`codec-http/src/main/java/io/netty/handler/codec/http/`）、`codec-http2`、`codec-http3`。

> [!NOTE]
>
> 4.2 把老 `netty-codec` jar 拆成了 `codec-base` + 若干子协议模块，但 HTTP 相关类的**包路径没有变**，仍是 `io.netty.handler.codec.http` / `io.netty.handler.codec.http.websocketx`。写代码时 import 不受影响，找源码时要去 `codec-http/` 而不是 `codec/`。

## TLS

### SslHandler

```java
public class SslHandler extends ByteToMessageDecoder implements ChannelOutboundHandler {
```

一个 handler 同时承担两个方向：入站继承 `ByteToMessageDecoder`（密文 → 明文），出站实现 `ChannelOutboundHandler`（明文 → 密文）。这意味着它天然享有 `ByteToMessageDecoder` 的累积与拆包能力——TLS 是 record 协议，密文侧必须先攒够一个完整 record 才能 `unwrap`。

### Inbound

```java
private void decodeJdkCompatible(ChannelHandlerContext ctx, ByteBuf in) throws NotSslRecordException {
    int packetLength = this.packetLength;
    if (packetLength > 0) {
        if (in.readableBytes() < packetLength) {
            return;
        }
    } else {
        final int readableBytes = in.readableBytes();
        if (readableBytes < SslUtils.SSL_RECORD_HEADER_LENGTH) {
            return;
        }
        packetLength = getEncryptedPacketLength(in, in.readerIndex(), true);
        if (packetLength == SslUtils.NOT_ENCRYPTED) {
            // Not an SSL/TLS packet
            throw new NotSslRecordException("not an SSL/TLS record: " + ByteBufUtil.hexDump(in));
        }
        if (packetLength == NOT_ENOUGH_DATA) {
            return;
        }
        if (packetLength > readableBytes) {
            this.packetLength = packetLength;
            return;
        }
    }
    this.packetLength = 0;
    try {
        final int bytesConsumed = unwrap(ctx, in, packetLength);
        if (bytesConsumed != packetLength && !engine.isInboundDone()) {
            throw new NotSslRecordException();
        }
    } catch (Throwable cause) {
        handleUnwrapThrowable(ctx, cause);
    }
}
```

### Cumulator Choice

`SslHandler` 是少见的**主动换掉默认 `Cumulator`** 的解码器（源码：`handler/src/main/java/io/netty/handler/ssl/SslHandler.java:499`）：

```java
// 源码：handler/src/main/java/io/netty/handler/ssl/SslHandler.java:497
engineType = SslEngineType.forEngine(engine);
this.startTls = startTls;
this.jdkCompatibilityMode = engineType.jdkCompatibilityMode(engine);
setCumulator(engineType.cumulator);
```

`SslEngineType` 枚举按引擎类型绑定不同的 `cumulator`（源码：`handler/src/main/java/io/netty/handler/ssl/SslHandler.java:200` 起）：

| 引擎                              | `wantsDirectBuffer` | `cumulator`            | `jdkCompatibilityMode` |
| :------------------------------ | :------------------ | :--------------------- | :--------------------- |
| `TCNATIVE`（`ReferenceCountedOpenSslEngine`） | `true`              | `COMPOSITE_CUMULATOR`  | `false`                |
| `CONSCRYPT`（`ConscryptAlpnSslEngine`）     | `true`              | `COMPOSITE_CUMULATOR`  | `false`                |
| `JDK`                           | `false`             | `MERGE_CUMULATOR`      | `true`                 |

源码注释解释了原因（`handler/src/main/java/io/netty/handler/ssl/SslHandler.java:406`）：JDK `SSLEngine` 的 `unwrap(ByteBuffer, ByteBuffer[])` 只吃**单个** `ByteBuffer`，所以必须用 `MERGE_CUMULATOR` 把密文合并成一块连续内存；而 `OpenSslEngine` 有 `unwrap(ByteBuffer[], ByteBuffer[])`，可以直接喂多块，于是用 `COMPOSITE_CUMULATOR` 省掉拷贝。详见 [编解码器体系 - Cumulator](/docs/CS/Framework/Netty/Codec.md?id=cumulator)。

这个选择也决定了入站代码走哪条分支（源码：`.../SslHandler.java:1435`）：JDK 兼容模式走 `decodeJdkCompatible`（先解析 record 头、凑够一个 record 再 unwrap），tcnative/conscrypt 走 `decodeNonJdkCompatible`（直接把全部可读字节喂给引擎）。

### Handshake State Machine

握手由 `SSLEngineResult.HandshakeStatus` 驱动。4.2.19 里有**两套**状态机，容易混淆：

| 方法                              | 位置                                     | 用途                                     |
| :------------------------------ | :------------------------------------- | :------------------------------------- |
| `wrap(ctx, inUnwrap)`           | `handler/.../SslHandler.java:847`      | 应用数据 + 握手数据的通用 wrap 循环，握手状态机在 `:1016` |
| `wrapNonAppData(ctx, inUnwrap)` | `handler/.../SslHandler.java:976`      | 只 wrap 握手数据（外部显式触发握手时用），状态机在 `:940`   |

本文讨论的是 **`wrap(...)` 里的那套**（源码：`handler/.../SslHandler.java:1016`）：

```java
// 源码：handler/src/main/java/io/netty/handler/ssl/SslHandler.java:1016
HandshakeStatus status = result.getHandshakeStatus();
switch (status) {
    case FINISHED:
        if (setHandshakeSuccess() && inUnwrap && !pendingUnencryptedWrites.isEmpty()) {
            wrap(ctx, true);
        }
        return false;
    case NEED_TASK:
        if (!runDelegatedTasks(inUnwrap)) {
            break outer;
        }
        break;
    case NEED_UNWRAP:
        if (inUnwrap || unwrapNonAppData(ctx) <= 0) {
            return false;
        }
        break;
    case NEED_WRAP:
        break;
    case NOT_HANDSHAKING:
        if (setHandshakeSuccess() && inUnwrap && !pendingUnencryptedWrites.isEmpty()) {
            wrap(ctx, true);
        }
        // Workaround for TLS False Start problem (issue #1108)
        if (!inUnwrap) {
            unwrapNonAppData(ctx);
        }
        return true;
    default:
        throw new IllegalStateException("Unknown handshake status: " + result.getHandshakeStatus());
}
if (result.bytesProduced() == 0 && status != HandshakeStatus.NEED_TASK) {
    break;
}
```

`NEED_TASK` 是关键分支：TLS 握手里有 RSA/ECDH 这类耗时计算，`SSLEngine` 把它作为 `Runnable` 交给调用方执行。字段名叫 **`delegatedTaskExecutor`**（源码：`handler/.../SslHandler.java:419`，注意不是 `delegatingTaskExecutor`），默认为 `ImmediateExecutor.INSTANCE`（源码：`...:465`）——**握手计算默认跑在 EventLoop 线程上**，大并发握手会拖慢同线程的其他连接，生产上应考虑专用 executor：

```java
// 源码：handler/src/main/java/io/netty/handler/ssl/SslHandler.java:461
public SslHandler(SSLEngine engine, boolean startTls) {
    this(engine, startTls, ImmediateExecutor.INSTANCE);
}
```

`runDelegatedTasks` 的实现（源码：`...:1662`）先判断 executor 是不是 `ImmediateExecutor`、或当前线程已在该 executor 上：是就**循环取完所有 task 同步执行**；否则提交给 executor 并 `return false`，由外层 `break outer` 退出循环，待任务完成后再继续，避免阻塞 EventLoop。

```java
// 源码：handler/src/main/java/io/netty/handler/ssl/SslHandler.java:1662
private boolean runDelegatedTasks(boolean inUnwrap) {
    if (delegatedTaskExecutor == ImmediateExecutor.INSTANCE || inEventLoop(delegatedTaskExecutor)) {
        // We should run the task directly in the EventExecutor thread and not offload at all. As we are on the
        // EventLoop we can just run all tasks at once.
        for (;;) {
            Runnable task = engine.getDelegatedTask();
            if (task == null) {
                return true;
            }
            setState(STATE_PROCESS_TASK);
            if (task instanceof AsyncRunnable) {
                ...
            }
            ...
        }
    }
    ...
}
```

4.2 在这里多了 `AsyncRunnable` 分支：支持异步执行的引擎（主要是 tcnative）可以把 task 提交到自己的线程池，通过 `AsyncTaskCompletionHandler` 回调决定是否 `resumeLater()`，从而不占住 EventLoop。

### Handshake Timeout

握手超时是 `SslHandler` 上的字段而非 `SslContext` 的配置（源码：`...:443`）：

```java
// 源码：handler/src/main/java/io/netty/handler/ssl/SslHandler.java:443
private volatile long handshakeTimeoutMillis = 10000;
```

注意这里是**字面量 10000**，没有对应的 `public static final` 常量（4.1 也没有）。改它走 `setHandshakeTimeout(long, TimeUnit)` / `setHandshakeTimeoutMillis(long)`（源码：`...:507` / `...:512`），`0` 表示不设超时。调度点在 `handshake(boolean flushAtEnd)`（源码：`...:2215`）：

```java
// 源码：handler/src/main/java/io/netty/handler/ssl/SslHandler.java:2248
final long handshakeTimeoutMillis = this.handshakeTimeoutMillis;
if (handshakeTimeoutMillis <= 0 || localHandshakePromise.isDone()) {
    return;
}
final ScheduledFuture<?> timeoutFuture = ctx.executor().schedule(new Runnable() { ... },
        handshakeTimeoutMillis, TimeUnit.MILLISECONDS);
```

用的是 `ctx.executor()`（该 Channel 绑定的 EventLoop）的定时任务，超时后回调里抛 `SslHandshakeTimeoutException`（源码：`...:2258`）。

### Outbound

明文不直接进 `ChannelOutboundBuffer`，而是先缓存在 `SslHandlerCoalescingBufferQueue pendingUnencryptedWrites`（初始容量 16）：

```java
private void wrapAndFlush(ChannelHandlerContext ctx) throws SSLException {
    if (pendingUnencryptedWrites.isEmpty()) {
        pendingUnencryptedWrites.add(Unpooled.EMPTY_BUFFER, ctx.newPromise());
    }
    if (!handshakePromise.isDone()) {
        setState(STATE_FLUSHED_BEFORE_HANDSHAKE);
    }
    try {
        wrap(ctx, false);
    } finally {
        forceFlush(ctx);
    }
}
```

**为什么每次 flush 都要 wrap 成独立的包**：TLS 是 record 协议，`SSLEngine.wrap()` 一次产出一个完整 TLS record；写入 `ChannelOutboundBuffer` 的必须是 record 边界对齐的数据，否则对端解析会错位。所以 outbound 循环是"每次 wrap 一个 record、逐个 `ctx.write`"，而不是把所有明文拼成一个大包。

`pendingUnencryptedWrites` 为空时仍补一个 `Unpooled.EMPTY_BUFFER`，目的是强制产出握手期间需要回写的握手数据（Finished / alert）。`forceFlush` 放在 `finally` 里，保证异常时已 wrap 的部分也能发出去。

### Config

| 项                          | 位置                                                    | 默认值                                       |
| :------------------------- | :---------------------------------------------------- | :---------------------------------------- |
| `handshakeTimeoutMillis`   | **`SslHandler`** 字段（不是 `SslContext`/`SslContextBuilder`），源码：`.../SslHandler.java:443` | **10000**（10 秒）；`0` 表示不设超时     |
| `startTls`                 | `SslHandler(SSLEngine engine, boolean startTls)`       | false；为 true 时首个写请求明文透传，之后才握手 |
| `delegatedTaskExecutor`    | `SslHandler(SSLEngine, boolean, Executor)`             | `ImmediateExecutor.INSTANCE`（当前 EventLoop 线程） |
| `MAX_PLAINTEXT_LENGTH`     | `.../SslHandler.java:197`                             | `16 * 1024`，单次 wrap 的明文上限              |
| SNI                        | `SslContext.newHandler(alloc, peerHost, peerPort)`      | 引擎构造期传入，`SslHandler` 里没有 SNI 相关代码    |

异步结果：`handshakeFuture()` 返回 `handshakePromise`，`sslCloseFuture()` 返回 `sslClosePromise`，两者都是 `LazyChannelPromise`。

### Engine

- JDK `SSLEngine`：JSSE 实现，走堆/直接 `ByteBuffer` 与 `SSLEngineResult` 状态机，零额外依赖
- `OpenSslEngine`：`io.netty.handler.ssl` 包内存在，JNI 直连 BoringSSL（netty-tcnative），支持 ALPN、OCSP、多证书凭据；可用性用 `OpenSsl.isAvailable()`，失败原因看 `OpenSsl.unavailabilityCause()`

`SslHandler` 通过 `engineType.wantsDirectBuffer` 与 `SslHandlerCoalescingBufferQueue` 适配两者的缓冲区偏好差异——后者在构造时按引擎偏好初始化（源码：`.../SslHandler.java:2123`）：

```java
// 源码：handler/src/main/java/io/netty/handler/ssl/SslHandler.java:2123
pendingUnencryptedWrites = new SslHandlerCoalescingBufferQueue(channel, 16, engineType.wantsDirectBuffer) {
    @Override
    protected int wrapDataSize() {
        return SslHandler.this.wrapDataSize;
    }
};
```

第三个参数 `preferDirect = engineType.wantsDirectBuffer`：JDK 引擎要堆 buffer（其内部按 `byte[]` 运算，给 direct 反而多一次堆→直接内存的拷贝，见 `.../SslHandler.java:358` 的注释），tcnative/conscrypt 要 direct。

### Pipeline Position and Cost

- **位置**：`SslHandler` 必须放在业务 handler 之前、尽量靠近 Head——它之下（更靠 Head 一侧）的数据必须是密文，之上（更靠 Tail 一侧）是明文。典型顺序是 `SslHandler` → `HttpServerCodec` → `HttpObjectAggregator` → 业务 handler。放在 codec 之后就完全失效了，因为此时 pipeline 里流动的已经是 `HttpObject` 而不是 `ByteBuf`。
- **握手开销**：一次完整 TLS 1.2 握手是 2-RTT，TLS 1.3 是 1-RTT（0-RTT 需会话复用）。握手里的非对称运算以 `Runnable` 形式从 `engine.getDelegatedTask()` 返回，默认在 EventLoop 线程上同步跑（见 [Handshake State Machine](/docs/CS/Framework/Netty/Protocol.md?id=handshake-state-machine)）。因此**握手风暴会直接转化为 EventLoop 停顿**——每个握手几毫秒的 RSA/ECDH，落在单线程 EventLoop 上会拖慢该线程上成百上千条已建连的 Channel。缓解手段是给 `SslHandler` 传专用 executor，或在接入层做握手卸载。
- **加解密开销**：稳态下每个 record 一次 `unwrap`/`wrap`，对称加密本身是 CPU 密集但在现代 CPU 上有 AES-NI 硬件加速，主要成本来自**缓冲区拷贝**：JDK 引擎路径下堆↔直接内存会各多一次拷贝，这也是 `SslHandlerCoalescingBufferQueue` 要按引擎偏好分配 buffer 的原因。要彻底消除这部分开销得上 tcnative（`COMPOSITE_CUMULATOR` + 直接内存）或 kTLS 之类的内核卸载。

### Handshake Trigger Flow

上面 [Handshake State Machine](#handshake-state-machine) 讲的是 `wrap` 内部的 `NEED_*` 状态循环，这里补上**握手由谁、何时发起**。入口有两个：

- `handlerAdded`：构造 `pendingUnencryptedWrites` 后立即判断 `channel.isActive()`（或 TCP Fast Open）。若已 active 则调用 `startHandshakeProcessing(active)`（源码：`handler/src/main/java/io/netty/handler/ssl/SslHandler.java:2120`、`:2137`）。
- `channelActive`：对**非 StartTLS** 的连接同样调用 `startHandshakeProcessing(true)`（源码：`.../SslHandler.java:2287`、`:2289`）。

`startHandshakeProcessing` 只在 client 模式（或已设 `STATE_NEEDS_FLUSH`）下真正触发，且同一连接只触发一次（源码：`.../SslHandler.java:2148`）。最终落点是 `handshake(boolean flushAtEnd)`：先 `engine.beginHandshake()`，再 `wrapNonAppData` 把 ClientHello / ServerHello 等握手记录写出去（源码：`.../SslHandler.java:2215`、`:2233`）：

```java
// 源码：handler/src/main/java/io/netty/handler/ssl/SslHandler.java:2233
engine.beginHandshake();
wrapNonAppData(ctx, false);
```

握手完成（wrap 循环里见到 `FINISHED` 或 `NOT_HANDSHAKING`）后，`setHandshakeSuccess()` 会 `fireUserEventTriggered(SslHandshakeCompletionEvent.SUCCESS)`（源码：`.../SslHandler.java:1983`）。**业务侧应在 `userEventTriggered` 里捕获 `SslHandshakeCompletionEvent`**：成功是 `SslHandshakeCompletionEvent.SUCCESS`，失败则是携带 `Throwable` 的 `SslHandshakeCompletionEvent(cause)`（源码：`.../SslHandler.java:731`、`:1410`、`:2045`）。握手超时则经 `applyHandshakeTimeout()` 抛 `SslHandshakeTimeoutException`（默认 10s，见上文 `### Handshake Timeout`）。

> [!NOTE]
>
> `SslHandshakeCompletionEvent` 是**唯一**可靠的握手结果通知机制。不要依赖「`channelActive` 之后就一定握手成功」——`channelActive` 只表示 TCP 连接通了，TLS 握手可能在其后才失败。另：`SslHandler.applicationProtocol()`（源码：`.../SslHandler.java:629`）返回协商出的应用协议名（见下节 ALPN），它本身**不是**握手完成的信号。

### ALPN

应用层协议协商（ALPN，RFC 7301）让客户端/服务端在 TLS 握手内就选定上层协议，避免额外的应用层探测往返。Netty 的配置入口是 `ApplicationProtocolConfig`，构造参数是「协议枚举 + 失败行为 + 候选协议列表」（源码：`handler/src/main/java/io/netty/handler/ssl/ApplicationProtocolConfig.java:49`）：

```java
// 源码：handler/src/main/java/io/netty/handler/ssl/ApplicationProtocolConfig.java:100
public enum Protocol { NONE, NPN, ALPN, NPN_AND_ALPN }
```

- `Protocol` 选 `ALPN`（NPN 是已废弃的旧方案）；`supportedProtocols` 的**顺序即偏好顺序**（先列优先）。
- 通过 `SslContextBuilder.applicationProtocolConfig(...)` 挂到 `SslContext`（源码：`.../SslContextBuilder.java:633`）。
- 协商结果用 `SslHandler.applicationProtocol()` 暴露，本质是取引擎的 `getNegotiatedApplicationProtocol()`（源码：`.../SslHandler.java:629`、`:635`）。
- 常用 ALPN 名：`h2`（HTTP/2 over TLS）、`http/1.1`（HTTP/1.1）。注意 **`h2c` 不是 ALPN 名**——它是明文升级 / prior-knowledge 的称谓，只出现在 h2c 升级流程（见 [HTTP/2 专题 - h2c Upgrade](/docs/CS/Framework/Netty/HTTP2.md?id=h2c-upgrade)），与 TLS ALPN 无关。

> [!NOTE]
>
> 各 `SslProvider` 对 ALPN 的支持不同：`SslProvider.isAlpnSupported(provider)` 中，JDK 走 `JdkAlpnApplicationProtocolNegotiator`，OpenSSL 系走 `OpenSsl.isAlpnSupported()`（源码：`handler/src/main/java/io/netty/handler/ssl/SslProvider.java:47`）。老版本 JDK（≤8）无原生 ALPN，需换 OpenSSL/Conscrypt 引擎。

### SslEngineType 与引擎取舍

引擎类型由 `SslHandler` 内部的 `SslEngineType` 枚举决定（源码：`handler/src/main/java/io/netty/handler/ssl/SslHandler.java:199`）。实际枚举值只有三个：

| 枚举值 | 对应引擎 | `wantsDirectBuffer` | `cumulator` | `jdkCompatibilityMode` |
| :--- | :--- | :--- | :--- | :--- |
| `TCNATIVE` | `ReferenceCountedOpenSslEngine`（netty-tcnative / BoringSSL） | `true` | `COMPOSITE_CUMULATOR` | `false` |
| `CONSCRYPT` | `ConscryptAlpnSslEngine`（Google Conscrypt / BoringSSL） | `true` | `COMPOSITE_CUMULATOR` | `true` |
| `JDK` | JSSE `SSLEngine` | `false` | `MERGE_CUMULATOR` | `true` |

`forEngine` 按实例类型分派（源码：`.../SslHandler.java:374`）：

```java
// 源码：handler/src/main/java/io/netty/handler/ssl/SslHandler.java:374
static SslEngineType forEngine(SSLEngine engine) {
    return engine instanceof ReferenceCountedOpenSslEngine ? TCNATIVE :
           engine instanceof ConscryptAlpnSslEngine ? CONSCRYPT : JDK;
}
```

> [!WARNING]
>
> 不要把 `SslEngineType`（运行期、随 `SSLEngine` 实例而定的内部枚举）与 `SslProvider`（构建期、在 `SslContextBuilder.sslProvider(...)` 指定的枚举）混为一谈。后者取值为 `JDK` / `OPENSSL` / `OPENSSL_REFCNT`（源码：`handler/src/main/java/io/netty/handler/ssl/SslProvider.java:27`），其中 `OPENSSL_REFCNT` 用 `ReferenceCounted` 取代 finalizer，标注了 `@UnstableApi`。换句话说：`SslProvider.OPENSSL` 构建出的 `SSLEngine` 在运行期仍然映射为 `SslEngineType.TCNATIVE`。

取舍要点：

- **JDK（JSSE）**：零额外依赖；现代 JDK（9+）支持 ALPN，但 `SSLEngine.unwrap` 只吃单个 `ByteBuffer` → 必须 `MERGE_CUMULATOR` 合并成连续内存；wrap 缓冲用堆内存且至少 `getPacketBufferSize()`（约 16KB）起步（源码：`.../SslHandler.java:345`、`:353`），缓冲更重、拷贝更多。
- **TCNATIVE（BoringSSL via JNI）**：`unwrap(ByteBuffer[], ByteBuffer[])` 支持 gather，可直接喂多块 → `COMPOSITE_CUMULATOR` 省拷贝；要 direct buffer；功能最全（ALPN、OCSP、会话票据、多证书凭据），性能最佳，但引入 native 依赖。
- **CONSCRYPT（BoringSSL，Google 维护）**：同样 `COMPOSITE_CUMULATOR` + direct，适合 Android / 不便用 JNI 的场景；注意其 `jdkCompatibilityMode` 返回 `true`（源码：`.../SslHandler.java:296`）。

### 加解密缓冲与内存开销

TLS 是 record 协议：一次 `wrap`/`unwrap` 都围绕一个完整 record。Netty 按引擎偏好分配临时 `ByteBuf`，与上文 [Cumulator Choice](#cumulator-choice) 的累积区选择相呼应：

- **出站 wrap**：`SslEngineType.allocateWrapBuffer` 按引擎估算输出大小分配。TCNATIVE 用 `allocator.directBuffer(engine.calculateOutNetBufSize(pendingBytes, numComponents))`（源码：`.../SslHandler.java:228`），JDK 用 `allocator.heapBuffer(Math.max(pendingBytes, getSession().getPacketBufferSize()))`（源码：`.../SslHandler.java:345`）——即便明文很小，最少也要一个 packet buffer（约 16KB）的堆空间。record 的 **padding / 加密膨胀** 由引擎内部计入 `calculateOutNetBufSize`，调用方无需手算。
- **入站 unwrap**：从累积区取可读字节，`engine.unwrap(...)` 解出明文写入一个输出 `ByteBuf`。TCNATIVE/CONSCRYPT 支持多 buffer 直接喂入（省一次合并拷贝），JDK 只能先 `MERGE_CUMULATOR` 合成单块再 `unwrap`（源码：`.../SslHandler.java:303` 的 `getUnwrapInputBuffer`）。JDK 22–24 还有一个针对 `bugs.openjdk.org/browse/JDK-8357268` 的 heap 拷贝 workaround（源码：`.../SslHandler.java:327`）。
- **溢出缓冲（overflow buffer）**：当一次 `unwrap` 产出的明文多于当前输出 buffer 容量，或 TLS 层需要缓存尚未凑齐一个 record 的密文时，`SslHandler` 会保留未消费输入 / 暂存部分输出，等待下个 `decode` 循环继续消化；这与 `ByteToMessageDecoder` 累积区的语义一致，是「密文必须攒够一个 record 才能 unwrap」的延续。
- **与 Codec 累积区的交互**：`SslHandler` 位于 codec 之下（更靠 Head），它向下发的是 record 边界对齐的密文，向上发的是解密后的明文 `ByteBuf`；其上的 `Http2FrameCodec` / `HttpServerCodec` 等再做自己的帧/消息累积。两层 cumulator 各管一段：TLS record 累积在 `SslHandler`（引擎类型决定 `MERGE`/`COMPOSITE`），应用层分帧累积在 codec。

### close_notify 与半关闭

TCP 的 `close()` 与 TLS 的 `close_notify` 是两件独立的事。`SslHandler` 拦截 `close`：

- `ChannelHandlerContext.close(promise)` → `closeOutboundAndChannel(ctx, promise, false)`（源码：`.../SslHandler.java:768`）。
- `closeOutbound0`：置 `STATE_OUTBOUND_CLOSED`、调 `engine.closeOutbound()`、`flush()`，即把 **TLS `close_notify` 告警**写出去并销毁引擎（源码：`.../SslHandler.java:690`）。**`closeOutbound()` 本身只发 `close_notify`，不会关闭底层 Channel**（源码：`.../SslHandler.java:664` 的 javadoc）。
- `safeClose` 处理两个超时（源码：`.../SslHandler.java:2295`）：`closeNotifyFlushTimeoutMillis`（默认 **3000** ms，源码：`:444`）——`close_notify` 未在时限内发完则强制 TCP 关闭；`closeNotifyReadTimeoutMillis`（默认 **0**，即禁用，源码：`:445`）——>0 时才等待对端的 `close_notify` 到齐再关，否则发完即关。
- `sslCloseFuture()` 返回 `sslClosePromise`（源码：`.../SslHandler.java:709`），在 inbound 侧 `close_notify` 收到、连接真正 SSL 关闭后完成，可用于精确感知「TLS 层已关」。

> `close()` 关闭的是 TCP 连接；`closeOutbound()` 关闭的是 TLS 会话（发 `close_notify`）。若只想优雅结束 TLS 但保留连接（如连接复用/重新协商），用 `closeOutbound()`；想彻底断开用 `Channel.close()`。

### 会话与票据复用

TLS 握手的最大代价是 1-RTT（TLS 1.2）甚至 2-RTT，且非对称运算重。会话复用能把后续握手降到 0-RTT / 1-RTT：

- **Session Cache**：`SslContextBuilder.sessionCacheSize(long)` / `sessionTimeout(long)`（源码：`handler/src/main/java/io/netty/handler/ssl/SslContextBuilder.java:642`、`:651`）把容量与超时传入底层 `SSLContext` / `SSL_CTX` 的会话缓存，命中缓存即跳过完整握手。
- **TLS Session Tickets**（无状态复用）：由 OpenSSL 系引擎支持，服务端用票据加密状态、客户端回带，省去服务端缓存；`OPENSSL_REFCNT` 还支持 `OpenSslCredential` 多证书 + 票据轮换（源码：`.../SslContextBuilder.java:524`）。
- **OCSP Stapling**：`SslContextBuilder.enableOcsp(boolean)`（源码：`.../SslContextBuilder.java:698`）在握手时由服务端附带 OCSP 响应，客户端免去做证书吊销查询。
- 配合上节 ALPN：`applicationProtocolConfig(...)` 也是 `SslContextBuilder` 的一环（源码：`.../SslContextBuilder.java:633`），三者常一起在构建 `SslContext` 时设好，再经 `SslContext.newHandler(...)` 产出带 SNI/引擎配置的 `SslHandler`。

## HTTP/1.1

### HttpServerCodec

```java
// 源码：codec-http/src/main/java/io/netty/handler/codec/http/HttpServerCodec.java:52
public final class HttpServerCodec extends CombinedChannelDuplexHandler<HttpRequestDecoder, HttpResponseEncoder>
        implements HttpServerUpgradeHandler.SourceCodec {
```

`CombinedChannelDuplexHandler` 把一对编解码器合并成一个 handler，只占 pipeline 一个位置。实际 init 的是它的两个私有内部类 `HttpServerRequestDecoder extends HttpRequestDecoder`（源码：`.../HttpServerCodec.java:261`）与 `HttpServerResponseEncoder extends HttpResponseEncoder`（源码：`.../HttpServerCodec.java:303`）。

默认常量定义在 `HttpObjectDecoder`，`HttpServerCodec` 用静态导入引用（源码：`codec-http/src/main/java/io/netty/handler/codec/http/HttpObjectDecoder.java:148`）：

```java
// 源码：codec-http/src/main/java/io/netty/handler/codec/http/HttpObjectDecoder.java:148
public static final int DEFAULT_MAX_INITIAL_LINE_LENGTH = 4096;
public static final int DEFAULT_MAX_HEADER_SIZE = 8192;
public static final boolean DEFAULT_CHUNKED_SUPPORTED = true;
public static final boolean DEFAULT_ALLOW_PARTIAL_CHUNKS = true;
public static final int DEFAULT_MAX_CHUNK_SIZE = 8192;
public static final boolean DEFAULT_VALIDATE_HEADERS = true;
public static final int DEFAULT_INITIAL_BUFFER_SIZE = 128;
public static final boolean DEFAULT_ALLOW_DUPLICATE_CONTENT_LENGTHS = false;
```

另有 `HttpServerCodec.DEFAULT_MAX_PIPELINE_DEPTH = 128`（源码：`codec-http/src/main/java/io/netty/handler/codec/http/HttpServerCodec.java:60`），限制 HTTP pipelining 的深度。

> [!NOTE]
>
> 该常量是**包私有** `static final int`（不是 `public`），外部代码引用不到，只能从 `HttpServerCodec(HttpDecoderConfig config, int maxPipelineDepth)` 传入。

`HttpObjectDecoder` 上还有几个容易漏的默认值（源码：`codec-http/src/main/java/io/netty/handler/codec/http/HttpObjectDecoder.java:148` 起）：

| 常量                                       | 值                                                                                 |
| :--------------------------------------- | :-------------------------------------------------------------------------------- |
| `DEFAULT_MAX_INITIAL_LINE_LENGTH`         | `4096`                                                                            |
| `DEFAULT_MAX_HEADER_SIZE`                 | `8192`                                                                            |
| `DEFAULT_MAX_CHUNK_SIZE`                  | `8192`                                                                            |
| `DEFAULT_CHUNKED_SUPPORTED`               | `true`                                                                            |
| `DEFAULT_ALLOW_PARTIAL_CHUNKS`            | `true`                                                                            |
| `DEFAULT_VALIDATE_HEADERS`                | `true`（**头部校验默认开启**，防 CWE-113 响应拆分）                                                |
| `DEFAULT_INITIAL_BUFFER_SIZE`             | `128`                                                                             |
| `DEFAULT_ALLOW_DUPLICATE_CONTENT_LENGTHS` | `false`                                                                           |
| `DEFAULT_STRICT_LINE_PARSING`             | `SystemPropertyUtil.getBoolean("io.netty.handler.codec.http.defaultStrictLineParsing", true)` |
| `RFC9112_TRANSFER_ENCODING`               | `SystemPropertyUtil.getBoolean("io.netty.handler.codec.http.rfc9112TransferEncoding", true)` |

后两个可用系统属性关掉，属于兼容老对端的逃生口，正常不应动。

### Decoder Config

4.2 推荐用 `HttpDecoderConfig` 构造（源码：`codec-http/src/main/java/io/netty/handler/codec/http/HttpServerCodec.java:181`），老的 `(int maxInitialLineLength, int maxHeaderSize, int maxChunkSize, boolean validateHeaders, ...)` 系列构造器**已全部标 `@Deprecated`**（`...:115` / `:130` / `:148` / `:165`），原因是它们允许把 `validateHeaders` 设成 `false`：

```java
// 源码：codec-http/src/main/java/io/netty/handler/codec/http/HttpServerCodec.java:193
public HttpServerCodec(HttpDecoderConfig config, int maxPipelineDepth) {
    this.maxPipelineDepth = ObjectUtil.checkPositive(maxPipelineDepth, "maxPipelineDepth");
    init(new HttpServerRequestDecoder(config), new HttpServerResponseEncoder());
}
```

`init(...)` 来自 `CombinedChannelDuplexHandler`——所以 `HttpServerCodec` 在 pipeline 里只占**一个位置**，但内部是 `HttpServerRequestDecoder`（`extends HttpRequestDecoder`，`...:261`）与 `HttpServerResponseEncoder`（`extends HttpResponseEncoder`，`...:303`）两个私有内部类。

### Pipelining Depth

4.2 的 `HttpServerCodec` 多了一层 **pipelining 深度保护**（源码：`...:207` / `:269`）。请求方法被编码成 2 bit 塞进一个 `long methodQueue`（`...:80`），因为 `Long.SIZE / 2 = 32`，所以 ≤ 32 个在途请求**零分配**；超过 32 才退化成 `ArrayDeque<Byte> methodOverflowQueue`：

```java
// 源码：codec-http/src/main/java/io/netty/handler/codec/http/HttpServerCodec.java:278
for (int i = oldSize; i < size; i++) {
    Object obj = out.get(i);
    if (obj instanceof HttpRequest) {
        if (!enqueueMethod(((HttpRequest) obj).method())) {
            // We hit the limit, let's discard everything and release everything and also ensure
            // we close the connection once the first response is written back.
            mustCloseAfterResponse = true;
            discard = true;
            ReferenceCountUtil.release(obj);
            while (++i < size) {
                ReferenceCountUtil.release(out.get(i));
            }
            out.clear();
            throw new IllegalStateException("maxPipelineDepth exceeded: " + maxPipelineDepth);
        }
    }
}
```

触发后：置 `discard = true`（后续字节 `skipBytes` 丢弃）、释放本轮已解出的全部对象、抛 `IllegalStateException`，并置 `mustCloseAfterResponse` 让 encoder 在写完下一个 `LastHttpContent` 后 `ChannelFutureListener.CLOSE`（`...:309`）。

这里记录方法（HEAD / CONNECT / 其他）是为了正确判断响应是否「内容恒空」（`...:330` 的 `isContentAlwaysEmpty`）——HEAD 请求的响应没有 body，CONNECT 成功后要剥掉 `Transfer-Encoding` 头（`...:317`）。

### HttpObjectEncoder

出站方向的基类（源码：`codec-http/src/main/java/io/netty/handler/codec/http/HttpObjectEncoder.java:55`），`HttpRequestEncoder` / `HttpResponseEncoder` 都是它的子类。它是 `MessageToMessageEncoder<Object>`，所以编码结果是**一组 `ByteBuf`**（初始行 + 头 + 内容体可能分成多个），由基类的 `PromiseCombiner` 聚合成一个 promise。

编码状态机只有 4 态（源码：`...:71`）：

| 状态                       | 含义                              |
| :----------------------- | :------------------------------ |
| `ST_INIT`                | 还没开始写消息，期待一个 `HttpMessage`      |
| `ST_CONTENT_NON_CHUNK`   | 已写头，`Content-Length` 已知，直写内容体    |
| `ST_CONTENT_CHUNK`       | 已写头，`Transfer-Encoding: chunked` |
| `ST_CONTENT_ALWAYS_EMPTY` | 内容恒空（204/304/HEAD 响应等），不再写内容体   |

`encode` 按消息类型分派（源码：`...:158`），注意 `msg == Unpooled.EMPTY_BUFFER` 有快速路径——这是 `MessageToByteEncoder`「空结果改写 `EMPTY_BUFFER`」那套逻辑在 HTTP 侧的对口处理。

两个有意思的优化：

1. **头部大小预测器**。`headersEncodedSizeAccumulator` 用指数加权平均（源码：`...:66` 的 `HEADERS_WEIGHT_NEW = 1/5f`）预测下一次要分配多大的 buffer，避免每次从默认容量开始扩容：

   ```java
   // 源码：codec-http/src/main/java/io/netty/handler/codec/http/HttpObjectEncoder.java:340
   headersEncodedSizeAccumulator = HEADERS_WEIGHT_NEW * padSizeForAccumulation(buf.readableBytes()) +
           HEADERS_WEIGHT_HISTORICAL * headersEncodedSizeAccumulator;
   ```

2. **小内容内联**。`FullHttpMessage` 且非 chunked 时，若内容体小于 `max(COPY_CONTENT_THRESHOLD(128), headersEncodedSizeAccumulator / 8)`，就把内容体**拷进同一个 buffer**（`accountForContentSize`，源码：`...:325`），一次分配搞定「头 + 内容」，省掉一次 `writev`/buffer 切换。阈值取「头部预估大小的 1/8」是为了限制预测错误时的内存浪费。

状态机还兼作**协议正确性检查**：`state != ST_INIT` 时再收到 `HttpMessage` 会 `throwUnexpectedMessageTypeEx`（源码：`...:310`），即「上一条响应还没写完就又来一条」会被立刻发现，而不是写出一串让对端解析错位的字节。

### HttpObjectAggregator

```java
// 源码：codec-http/src/main/java/io/netty/handler/codec/http/HttpObjectAggregator.java:114
public HttpObjectAggregator(int maxContentLength) {
    this(maxContentLength, false);
}
```

> [!WARNING]
>
> 4.2 中 **`HttpObjectAggregator` 没有无参构造、也没有默认 `maxContentLength`**，必须显式传。`DEFAULT_MAX_COMPOSITEBUFFER_COMPONENTS = 1024` 定义在父类 `MessageAggregator`（`codec-base/src/main/java/io/netty/handler/codec/MessageAggregator.java:55`），不在本类。

第二个构造器参数是 `closeOnExpectationFailed`（源码：`.../HttpObjectAggregator.java:127`）：`Expect: 100-continue` 且内容超限时，`true` 表示回 413 后直接关连接，`false`（默认）表示连接保持打开、把后续数据读完丢弃直到下一个请求。

聚合用 `CompositeByteBuf` 拼 `HttpContent`，见 [MessageAggregator](/docs/CS/Framework/Netty/Codec.md?id=messageaggregator)。`Expect: 100-continue` 由重写后的 `newContinueResponse` 处理（源码：`.../HttpObjectAggregator.java:179`）：长度合法回 `CONTINUE`(100)，超限回 `TOO_LARGE`(413)；请求超限时发 `TOO_LARGE_CLOSE`（413 + `Connection: close`，源码：`...:93` 与 `...:251`）。

### Compression and Upgrade

```java
// 源码：codec-http/src/main/java/io/netty/handler/codec/http/HttpContentCompressor.java:51
public class HttpContentCompressor extends HttpContentEncoder {
    private final int contentSizeThreshold;
```

4.2 支持 `CompressionOptions...` 与 `contentSizeThreshold`（小于阈值的响应不压缩，省 CPU）。默认压缩算法集合在 `DEFAULT_COMPRESSION_OPTIONS`（源码：`...:62`）里按可用性装配：`StandardCompressionOptions.gzip()` + `deflate()` + `snappy()`，若类路径支持则再加 `brotli()` 与 `zstd()`。

`HttpServerUpgradeHandler extends HttpObjectAggregator`（源码：`codec-http/src/main/java/io/netty/handler/codec/http/HttpServerUpgradeHandler.java:41`）——它**本身就是一个聚合器**，内部接口为 `SourceCodec` / `UpgradeCodec` / `UpgradeCodecFactory`，握手成功时 fire `UpgradeEvent`。`HttpServerCodec` 实现 `SourceCodec` 的 `upgradeFrom(ctx)` 就是简单地把自己从 pipeline 移除（源码：`.../HttpServerCodec.java:203`）。

### Typical Pipeline

```java
ChannelPipeline p = ch.pipeline();
p.addLast(new HttpServerCodec());
p.addLast(new HttpObjectAggregator(65536));
p.addLast(new HttpContentCompressor());
p.addLast(new MyBusinessHandler());
```

顺序不能颠倒：聚合器必须在 codec 之后（输入已是 `HttpObject`），压缩器必须在聚合之后（需要完整的 `FullHttpResponse` 才能决定压缩）。

## WebSocket

### Handlers

```java
public class WebSocketServerProtocolHandler extends WebSocketProtocolHandler {
```

`handlerAdded` 时在自己**之前**插入握手 handler 与 UTF-8 校验器：

```java
@Override
public void handlerAdded(ChannelHandlerContext ctx) {
    ChannelPipeline cp = ctx.pipeline();
    if (cp.get(WebSocketServerProtocolHandshakeHandler.class) == null) {
        // Add the WebSocketHandshakeHandler before this one.
        cp.addBefore(ctx.name(), WebSocketServerProtocolHandshakeHandler.class.getName(),
                new WebSocketServerProtocolHandshakeHandler(serverConfig));
    }
    if (serverConfig.decoderConfig().withUTF8Validator() && cp.get(Utf8FrameValidator.class) == null) {
        // Add the UFT8 checking before this one.
        cp.addBefore(ctx.name(), Utf8FrameValidator.class.getName(),
                new Utf8FrameValidator(serverConfig.decoderConfig().closeOnProtocolViolation()));
    }
}
```

### Config

`WebSocketServerProtocolConfig` 顶层 9 个字段，默认值来自 `newBuilder()`（源码：`codec-http/src/main/java/io/netty/handler/codec/http/websocketx/WebSocketServerProtocolConfig.java:118`）：

```java
// 源码：codec-http/src/main/java/io/netty/handler/codec/http/websocketx/WebSocketServerProtocolConfig.java:118
public static Builder newBuilder() {
    return new Builder("/", null, false, DEFAULT_HANDSHAKE_TIMEOUT_MILLIS,
        DEFAULT_FORCE_CLOSE_TIMEOUT_MILLIS, true, WebSocketCloseStatus.NORMAL_CLOSURE, true,
        WebSocketDecoderConfig.DEFAULT);
}
```

| 配置项                       | 默认值                                    | 源码位置                                        |
| :------------------------ | :------------------------------------- | :------------------------------------------ |
| `websocketPath`           | `"/"`                                  | `WebSocketServerProtocolConfig.java:119`    |
| `subprotocols`            | `null`                                 | 同上                                          |
| `checkStartsWith`         | `false`                                | 同上                                          |
| `handshakeTimeoutMillis`  | `10000`（`DEFAULT_HANDSHAKE_TIMEOUT_MILLIS`）    | `...:28`                                    |
| `forceCloseTimeoutMillis` | `10000`（`DEFAULT_FORCE_CLOSE_TIMEOUT_MILLIS`） | `...:29`                                    |
| `handleCloseFrames`       | `true`                                 | `...:120`                                   |
| `sendCloseFrame`          | `WebSocketCloseStatus.NORMAL_CLOSURE`   | 同上                                          |
| `dropPongFrames`          | `true`                                 | 同上                                          |
| `decoderConfig`           | `WebSocketDecoderConfig.DEFAULT`       | `WebSocketDecoderConfig.java:25`            |

`maxFramePayloadLength`、`allowExtensions`、`closeOnProtocolViolation` **不在顶层**，只是 builder 的转发方法，实际存在 `WebSocketDecoderConfig.DEFAULT = new WebSocketDecoderConfig(65536, true, false, false, true, true)`（源码：`codec-http/src/main/java/io/netty/handler/codec/http/websocketx/WebSocketDecoderConfig.java:25`），即 `maxFramePayloadLength=65536`、`expectMaskedFrames=true`、`allowMaskMismatch=false`、**`allowExtensions=false`**、**`closeOnProtocolViolation=false`**、`withUTF8Validator=true`。

> [!NOTE]
>
> `WebSocketDecoderConfig.DEFAULT`、`DEFAULT_HANDSHAKE_TIMEOUT_MILLIS`、`DEFAULT_FORCE_CLOSE_TIMEOUT_MILLIS` 三个都是**包私有** `static final`（`static final` 而无 `public`），外部代码引用不到，只能通过 builder 或直接构造 `WebSocketServerProtocolConfig` 设置。

### Handshake

`WebSocketServerProtocolHandshakeHandler.channelRead` 只做三件事——记录 handshaker、移除自己、在握手完成后 fire 事件（源码：`codec-http/src/main/java/io/netty/handler/codec/http/websocketx/WebSocketServerProtocolHandshakeHandler.java:83`）：

```java
// 源码：codec-http/src/main/java/io/netty/handler/codec/http/websocketx/WebSocketServerProtocolHandshakeHandler.java:83
WebSocketServerProtocolHandler.setHandshaker(ctx.channel(), handshaker);
ctx.pipeline().remove(this);
// The write via the removed handler's ctx still starts at this handler's former position.
final ChannelFuture handshakeFuture = handshaker.handshake(ctx, req);
handshakeFuture.addListener(future -> {
    if (!future.isSuccess()) {
        localHandshakePromise.tryFailure(future.cause());
        ctx.fireExceptionCaught(future.cause());
    } else {
        localHandshakePromise.trySuccess();
        // Kept for compatibility
        ctx.fireUserEventTriggered(ServerHandshakeStateEvent.HANDSHAKE_COMPLETE);
        ctx.fireUserEventTriggered(
                new WebSocketServerProtocolHandler.HandshakeComplete(
                        req.uri(), req.headers(), handshaker.selectedSubprotocol()));
    }
});
applyHandshakeTimeout();
```

**真正的 pipeline 替换在 `WebSocketServerHandshaker.handshake0(...)`**（源码：`codec-http/src/main/java/io/netty/handler/codec/http/websocketx/WebSocketServerHandshaker.java:254`）：

```java
// 源码：codec-http/src/main/java/io/netty/handler/codec/http/websocketx/WebSocketServerHandshaker.java:254
private ChannelFuture handshake0(final ChannelOutboundInvoker invoker, final Channel channel, FullHttpRequest req,
                                 HttpHeaders responseHeaders, final ChannelPromise promise) {
    FullHttpResponse response = newHandshakeResponse(req, responseHeaders);
    ChannelPipeline p = channel.pipeline();
    if (p.get(HttpObjectAggregator.class) != null) {
        p.remove(HttpObjectAggregator.class);
    }
    if (p.get(HttpContentCompressor.class) != null) {
        p.remove(HttpContentCompressor.class);
    }
    ChannelHandlerContext ctx = p.context(HttpRequestDecoder.class);
    final String encoderName;
    if (ctx == null) {
        // this means the user use an HttpServerCodec
        ctx = p.context(HttpServerCodec.class);
        if (ctx == null) {
            promise.setFailure(
                    new IllegalStateException("No HttpDecoder and no HttpServerCodec in the pipeline"));
            response.release();
            return promise;
        }
        p.addBefore(ctx.name(), "wsencoder", newWebSocketEncoder());
        p.addBefore(ctx.name(), "wsdecoder", newWebsocketDecoder());
        encoderName = ctx.name();
    } else {
        p.replace(ctx.name(), "wsdecoder", newWebsocketDecoder());
        encoderName = p.context(HttpResponseEncoder.class).name();
        p.addBefore(encoderName, "wsencoder", newWebSocketEncoder());
    }
    invoker.writeAndFlush(response).addListener(future -> {
        if (future.isSuccess()) {
            ChannelPipeline p1 = channel.pipeline();
            p1.remove(encoderName);
            promise.setSuccess();
        } else {
            promise.setFailure(future.cause());
        }
    });
    return promise;
}
```

替换序列：移除 `HttpObjectAggregator` → 移除 `HttpContentCompressor` → 插入 `wsencoder` → 插入 `wsdecoder`（或 replace `HttpRequestDecoder`）→ **写完 101 响应成功后才移除原 HTTP codec**。这个顺序保证 HTTP codec 不会提前消失导致 101 响应发不出去。

三个容易忽略的点：

- `p.context(HttpRequestDecoder.class)` 先找独立的解码器；找不到再找 `HttpServerCodec`。因为 `HttpServerCodec` 是 `CombinedChannelDuplexHandler`，`p.context(HttpRequestDecoder.class)` 对它**不匹配**——`CombinedChannelDuplexHandler` 内部持有解码器实例，但 pipeline 里的 `ChannelHandlerContext` 是 `HttpServerCodec` 自己的。
- 两个都找不到时不是静默失败：`promise.setFailure(new IllegalStateException("No HttpDecoder and no HttpServerCodec in the pipeline"))` + `response.release()`，避免刚构造的 `FullHttpResponse` 泄漏。
- `invoker.writeAndFlush(response)` 里的 `invoker` 是**被移除的握手 handler 的 ctx**（`ctx` 版本传入的），所以 101 响应仍从握手 handler 原来的位置开始向后传播——这正是注释 "The write via the removed handler's ctx still starts at this handler's former position" 的含义。

握手超时由 `applyHandshakeTimeout()` 设置（源码：`codec-http/src/main/java/io/netty/handler/codec/http/websocketx/WebSocketServerProtocolHandshakeHandler.java:141`）。超时回调里先把 promise 置为失败（`WebSocketServerHandshakeException("handshake timed out")`），再 `ctx.flush().fireUserEventTriggered(ServerHandshakeStateEvent.HANDSHAKE_TIMEOUT).close()`——注意是**直接 close 而不是按 `sendCloseFrame` 发关闭帧**，因为此时握手都没完成、对端还在 HTTP 语义下。握手成功时通过 `localHandshakePromise.addListener(f -> timeoutFuture.cancel(false))` 取消定时任务。

`forceCloseTimeoutMillis` 则用在另一处：正常关闭流程里发完 close 帧后，用 `applyCloseSentTimeout(ctx)` 起一个兜底强制关闭（源码：`.../WebSocketServerProtocolHandler.java:248`），防止对端不回 close 帧导致连接悬挂。

### Frames

六个帧类型都直接 `extends WebSocketFrame`（其本身 `extends DefaultByteBufHolder`）：`TextWebSocketFrame`、`BinaryWebSocketFrame`、`PingWebSocketFrame`、`PongWebSocketFrame`、`CloseWebSocketFrame`、`ContinuationWebSocketFrame`。

分片规则由 `WebSocket08FrameDecoder` 的 `fragmentedFramesCount` 维护：

- 控制帧**禁止分片**（`!frameFinalFlag` 时协议违规）
- 控制帧载荷必须 ≤ 125 字节
- 孤立 CONT 帧（`fragmentedFramesCount == 0 && frameOpcode == OPCODE_CONT`）违规
- 分片过程中收到非 CONT 数据帧违规
- 收尾：`frameFinalFlag ? fragmentedFramesCount = 0 : fragmentedFramesCount++`

需要合并分片可加 `WebSocketFrameAggregator`。

## HTTP/2 and HTTP/3

`codec-http2` 在 4.2.19 中存在（源码：`codec-http2/src/main/java/io/netty/handler/codec/http2/`），核心类：

- `Http2FrameCodec`：HTTP/2 帧与 `Http2StreamFrame` 对象互转
- `Http2MultiplexHandler`：把一条连接的多路复用流映射成多个子 `Channel`
- `CleartextHttp2ServerUpgradeHandler`：h2c 升级（基于 HTTP/1.1 Upgrade 机制）

帧层 / HPACK / 多路复用 / 流控 / Netty 接入 / h2c 升级的实现细节见 [HTTP/2 专题](/docs/CS/Framework/Netty/HTTP2.md)。

`codec-http3` 在 4.2.19 中同样存在，服务端入口是 `Http3ServerConnectionHandler`（源码：`codec-http3/src/main/java/io/netty/handler/codec/http3/Http3ServerConnectionHandler.java:31`）：

```java
// 源码：codec-http3/src/main/java/io/netty/handler/codec/http3/Http3ServerConnectionHandler.java:31
public final class Http3ServerConnectionHandler extends Http3ConnectionHandler {
```

配套类按职责分成三组，注意命名：

| 组         | 类                                                                                          |
| :-------- | :----------------------------------------------------------------------------------------- |
| 连接级       | `Http3ConnectionHandler` / `Http3ClientConnectionHandler` / `Http3ControlStreamInboundHandler` / `Http3ControlStreamOutboundHandler` |
| 编码        | `Http3FrameCodec`、`Http3FrameToHttpObjectCodec`、`Http3HeadersSink`                          |
| 请求流       | `Http3RequestStreamInitializer`、`Http3RequestStreamValidationHandler`、`Http3RequestStreamEncodeStateValidator` / `Http3RequestStreamDecodeStateValidator` |

> [!NOTE]
>
> 常见误记：**没有 `Http3RequestStreamCodec` 这个类**。4.2.19 里只有 `Http3RequestStreamCodecState`——它是一个**接口**（源码：`codec-http3/src/main/java/io/netty/handler/codec/http3/Http3RequestStreamCodecState.java`，带内置 `NO_STATE` 实现），用于跟踪该流是否已 `started()` / `receivedFinalHeaders()` / `terminated()`。请求流的编解码由 `Http3FrameCodec` + `Http3FrameToHttpObjectCodec` + `Http3RequestStream*ValidationHandler` 组合完成。
>
> 另外，`codec-http3` 整个包（含 `Http3ServerConnectionHandler`、`Http3FrameCodec`）在 4.2.19 中**没有任何一个类标注 `@UnstableApi`**——与 io_uring 的情况一致。这并不等于 API 已冻结，只是 Netty 没有给这些类打该注解。

## Links

- [Netty](/docs/CS/Framework/Netty/Netty.md)
- [编解码器体系](/docs/CS/Framework/Netty/Codec.md)
- [ChannelHandler 与 Pipeline](/docs/CS/Framework/Netty/ChannelHandler.md)
- [TCP Fast Open](/docs/CS/Framework/Netty/TPO.md)
- [HTTP 协议](/docs/CS/CN/HTTP/HTTP.md)
- [TCP](/docs/CS/CN/TCP/TCP.md)

## References

1. [Netty 4.2 Javadoc - SslHandler](https://netty.io/4.2/api/io/netty/handler/ssl/SslHandler.html)
2. [Netty 4.2 Javadoc - HttpServerCodec](https://netty.io/4.2/api/io/netty/handler/codec/http/HttpServerCodec.html)
3. [Netty 4.2 Javadoc - WebSocketServerProtocolHandler](https://netty.io/4.2/api/io/netty/handler/codec/http/websocketx/WebSocketServerProtocolHandler.html)
4. [RFC 6455 - The WebSocket Protocol](https://datatracker.ietf.org/doc/html/rfc6455)
5. [RFC 9113 - HTTP/2](https://datatracker.ietf.org/doc/html/rfc9113)
