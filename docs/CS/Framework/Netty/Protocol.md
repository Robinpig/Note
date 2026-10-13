## Introduction

Protocol Support 层是在 [Pipeline](/docs/CS/Framework/Netty/ChannelHandler.md) 上叠加的一组开箱即用的 handler：TLS、HTTP/1.1、WebSocket、HTTP/2、HTTP/3。它们不参与 Reactor 线程模型，只是在入站方向把字节解成协议对象、出站方向反过来。

本文以 **Netty 4.2**（最新 GA 4.2.19.Final，2026-10-06）源码为准。模块划分：`handler`（SSL）、`codec-http`、`codec-http2`、`codec-http3`。

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

### Handshake State Machine

握手由 `SSLEngineResult.HandshakeStatus` 驱动，状态机在 `wrapNonAppData(...)` 里：

```java
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

`NEED_TASK` 是关键分支：TLS 握手里有 RSA/ECDH 这类耗时计算，`SSLEngine` 把它作为 `Runnable` 交给调用方执行。Netty 用 `runDelegatedTasks` 把这些任务丢给 `delegatingTaskExecutor`（默认 `ImmediateExecutor`，即当前线程）——**握手计算默认跑在 EventLoop 线程上**，大并发握手会拖慢同线程的其他连接，生产上应考虑专用 executor。

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

| 项                    | 位置                                        | 默认值                                        |
| :------------------- | :---------------------------------------- | :----------------------------------------- |
| `handshakeTimeoutMillis` | **`SslHandler`**（不是 `SslContext`/`SslContextBuilder`） | **10000**（10 秒）                             |
| `startTls`           | `SslHandler(SSLEngine engine, boolean startTls)` | false；为 true 时首个写请求明文透传，之后才握手 |
| SNI                  | `SslContext.newHandler(alloc, peerHost, peerPort)` | 引擎构造期传入，`SslHandler` 里没有 SNI 相关代码 |

异步结果：`handshakeFuture()` 返回 `handshakePromise`，`sslCloseFuture()` 返回 `sslClosePromise`，两者都是 `LazyChannelPromise`。

### Engine

- JDK `SSLEngine`：JSSE 实现，走堆/直接 `ByteBuffer` 与 `SSLEngineResult` 状态机，零额外依赖
- `OpenSslEngine`：`io.netty.handler.ssl` 包内存在，JNI 直连 BoringSSL（netty-tcnative），支持 ALPN、OCSP、多证书凭据；可用性用 `OpenSsl.isAvailable()`，失败原因看 `OpenSsl.unavailabilityCause()`

`SslHandler` 通过 `engineType.wantsDirectBuffer` 与 `SslHandlerCoalescingBufferQueue` 适配两者的缓冲区偏好差异。

## HTTP/1.1

### HttpServerCodec

```java
public final class HttpServerCodec extends CombinedChannelDuplexHandler<HttpRequestDecoder, HttpResponseEncoder>
        implements HttpServerUpgradeHandler.SourceCodec {
```

`CombinedChannelDuplexHandler` 把一对编解码器合并成一个 handler，只占 pipeline 一个位置。实际 init 的是它的两个私有内部类 `HttpServerRequestDecoder extends HttpRequestDecoder` 与 `HttpServerResponseEncoder extends HttpResponseEncoder`。

默认常量定义在 `HttpObjectDecoder`，`HttpServerCodec` 用静态导入引用：

```java
public static final int DEFAULT_MAX_INITIAL_LINE_LENGTH = 4096;
public static final int DEFAULT_MAX_HEADER_SIZE = 8192;
public static final int DEFAULT_MAX_CHUNK_SIZE = 8192;
```

另有 `HttpServerCodec.DEFAULT_MAX_PIPELINE_DEPTH = 128`，限制 HTTP pipelining 的深度。

### HttpObjectAggregator

```java
public class HttpObjectAggregator
        extends MessageAggregator<HttpObject, HttpMessage, HttpContent, FullHttpMessage> {

    public HttpObjectAggregator(int maxContentLength) {
        this(maxContentLength, false);
    }
}
```

> [!WARNING]
>
> 4.2 中 **`HttpObjectAggregator` 没有无参构造、也没有默认 `maxContentLength`**，必须显式传。`DEFAULT_MAX_COMPOSITEBUFFER_COMPONENTS = 1024` 定义在父类 `MessageAggregator`（`codec-base`），不在本类。

聚合用 `CompositeByteBuf` 拼 `HttpContent`，见 [MessageAggregator](/docs/CS/Framework/Netty/Codec.md?id=messageaggregator)。`Expect: 100-continue` 由重写后的 `newContinueResponse` 处理：长度合法回 `CONTINUE`(100)，超限回 `TOO_LARGE`(413)；请求超限时发 `TOO_LARGE_CLOSE`（413 + `Connection: close`）。

### Compression and Upgrade

`HttpContentCompressor extends HttpContentEncoder`，4.2 支持 `CompressionOptions...` 与 `contentSizeThreshold`（小于阈值的响应不压缩，省 CPU）。

`HttpServerUpgradeHandler extends HttpObjectAggregator`——它本身就是一个聚合器，内部接口为 `SourceCodec` / `UpgradeCodec` / `UpgradeCodecFactory`，握手成功时 fire `UpgradeEvent`。

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

`WebSocketServerProtocolConfig` 顶层 9 个字段，默认值如下：

| 配置项                        | 默认值                                    |
| :------------------------- | :------------------------------------- |
| `websocketPath`            | `"/"`                                  |
| `subprotocols`             | `null`                                 |
| `checkStartsWith`          | `false`                                |
| `handshakeTimeoutMillis`   | `10000`                                |
| `forceCloseTimeoutMillis`  | `10000`                                |
| `handleCloseFrames`        | `true`                                 |
| `sendCloseFrame`           | `WebSocketCloseStatus.NORMAL_CLOSURE`  |
| `dropPongFrames`           | `true`                                 |
| `decoderConfig`            | `WebSocketDecoderConfig.DEFAULT`       |

`maxFramePayloadLength`、`allowExtensions`、`closeOnProtocolViolation` **不在顶层**，只是 builder 的转发方法，实际存在 `WebSocketDecoderConfig.DEFAULT = new WebSocketDecoderConfig(65536, true, false, false, true, true)`，即 `maxFramePayloadLength=65536`、`expectMaskedFrames=true`、`allowMaskMismatch=false`、**`allowExtensions=false`**、**`closeOnProtocolViolation=false`**、`withUTF8Validator=true`。

### Handshake

`WebSocketServerProtocolHandshakeHandler.channelRead` 只做三件事——记录 handshaker、移除自己、在握手完成后 fire 事件：

```java
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

**真正的 pipeline 替换在 `WebSocketServerHandshaker.handshake0(...)`**：

```java
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
    p.addBefore(ctx.name(), "wsencoder", newWebSocketEncoder());
    p.addBefore(ctx.name(), "wsdecoder", newWebSocketDecoder());
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
```

替换序列：移除 `HttpObjectAggregator` → 移除 `HttpContentCompressor` → 插入 `wsencoder` → 插入 `wsdecoder`（或 replace `HttpRequestDecoder`）→ **写完 101 响应成功后才移除原 HTTP codec**。这个顺序保证 HTTP codec 不会提前消失导致 101 响应发不出去。

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

`codec-http2` 在 4.2 中存在，核心类：

- `Http2FrameCodec`：HTTP/2 帧与 `Http2StreamFrame` 对象互转
- `Http2MultiplexHandler`：把一条连接的多路复用流映射成多个子 `Channel`
- `CleartextHttp2ServerUpgradeHandler`：h2c 升级（基于 HTTP/1.1 Upgrade 机制）

`codec-http3` 在 4.2 中同样存在（79 个 java 文件），入口是 `Http3ServerConnectionHandler extends Http3ConnectionHandler`，配套 `Http3FrameCodec`、`Http3RequestStreamCodec` 等。与 io_uring 一样，4.2.20 上这些类**未标注 `@UnstableApi`**。

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
