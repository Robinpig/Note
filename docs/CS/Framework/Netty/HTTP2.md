## Introduction

HTTP/2（RFC 9113）是 HTTP/1.1 的下一代二进制协议，核心目标是解决 HTTP/1.1 的队头阻塞与头部冗余。Netty 用 `codec-http2` 模块承载全部实现，源码位于 `codec-http2/src/main/java/io/netty/handler/codec/http2/`，HPACK 相关类（含静态表、动态表、Huffman 编解码）也在同一包内（并非独立 `hpack` 子包）。

本文以 **Netty 4.2.19.Final**（git tag `netty-4.2.19.Final`）源码为准。典型接入方式是 `Http2FrameCodec`（帧 ↔ 对象桥接）+ `Http2MultiplexHandler`（流 ↔ 子 Channel 映射），或直接使用 `Http2ConnectionHandler` 族。

> [!NOTE]
>
> 4.2 把老的 `netty-codec-http2` jar 归并进 `codec-http2` 模块，但**包路径未变**，仍是 `io.netty.handler.codec.http2`。4.1 与 4.2 在 HTTP/2 这层的 API 形态（`Http2FrameCodec`、`Http2MultiplexHandler`、`HpackDecoder`/`HpackEncoder` 等）基本一致，本页结论对两代通用；下文只对确有差异处用提示块点明。

## Frame Layer

HTTP/2 是**二进制分帧**协议：所有语义（请求、响应、推送、流控）都封装成一个个 frame，每个 frame 以固定 9 字节帧头开头。帧头写入顺序由 `Http2CodecUtil.writeFrameHeaderInternal` 决定（源码：`codec-http2/src/main/java/io/netty/handler/codec/http2/Http2CodecUtil.java:257`）：

```java
// 源码：codec-http2/src/main/java/io/netty/handler/codec/http2/Http2CodecUtil.java:257
static void writeFrameHeaderInternal(ByteBuf out, int payloadLength, byte type,
        Http2Flags flags, int streamId) {
    out.writeMedium(payloadLength);   // 24 bit：payload 长度（不含 9 字节头）
    out.writeByte(type);              //  8 bit：帧类型
    out.writeByte(flags.value());     //  8 bit：标志位
    out.writeInt(streamId);           // 32 bit：流 ID，最高 1 bit 为保留位 R，实际 31 bit
}
```

`FRAME_HEADER_LENGTH = 9` 是常量（源码：`Http2CodecUtil.java:59`）。帧类型枚举集中在 `Http2FrameTypes`（源码：`codec-http2/src/main/java/io/netty/handler/codec/http2/Http2FrameTypes.java:18`）：

| 类型常量 | 值 | 作用 |
| :--- | :--- | :--- |
| `DATA` | `0x0` | 承载 HTTP 消息体（受流控约束） |
| `HEADERS` | `0x1` | 发起流 / 携带请求或响应头（含优先级提示） |
| `PRIORITY` | `0x2` | 建议流的优先级依赖关系 |
| `RST_STREAM` | `0x3` | 立即终止一条流（带错误码） |
| `SETTINGS` | `0x4` | 连接级参数协商（窗口、表大小、并发数等），须 ACK |
| `PUSH_PROMISE` | `0x5` | 服务端主动推送承诺（服务端 → 客户端） |
| `PING` | `0x6` | 测量 RTT / 保活，8 字节不透明数据 |
| `GOAWAY` | `0x7` | 告知对端本端将关闭连接，并附带最后的流 ID |
| `WINDOW_UPDATE` | `0x8` | 逐流或连接级流控窗口增量 |
| `CONTINUATION` | `0x9` | 续传被 `HEADERS`/`PUSH_PROMISE` 分片的头部块 |

`flags` 的语义随帧类型而不同，由 `Http2Flags` 解析（如 `END_STREAM`、`END_HEADERS`、`ACK`）。多个 frame 在一条 TCP 连接上**交错**发送，靠 `streamId` 区分归属——这正是多路复用的物理基础。

## HPACK

HTTP/1.1 每次请求都重发大量重复头部（如 `user-agent`、`cookie`），在高并发下浪费严重。HTTP/2 用 **HPACK（RFC 7541）** 做头部压缩，由 `HpackDecoder`（`decode`）与 `HpackEncoder`（`encodeHeaders`）实现，二者都在 `io.netty.handler.codec.http2` 包内。

HPACK 维持两张表：

1. **静态表（Static Table）**：协议预定义的 61 项（索引 1–61），含常用伪头与头部名。`HpackStaticTable` 用 `STATIC_TABLE` 列表显式列出全部 61 项，并以 `length = STATIC_TABLE.size()` 暴露（源码：`codec-http2/src/main/java/io/netty/handler/codec/http2/HpackStaticTable.java:53`、`HpackStaticTable.java:195`）。
2. **动态表（Dynamic Table）**：连接生命周期内、按最近最少使用维护的变长表，上限由 `SETTINGS_HEADER_TABLE_SIZE` 协商。`HpackDecoder` / `HpackEncoder` 各自持有 `HpackDynamicTable`（源码：`HpackDecoder.java:92`、`HpackEncoder.java:63` 附近）。

编码方式分三类（源码：`HpackEncoder.java`）：

| 编码 | 首字节前缀（mask / N） | 说明 |
| :--- | :--- | :--- |
| 索引头部（完全命中静态/动态表） | `0x80` / 7 | 只发一个索引号，最省 |
| 增量字面量（Literal + 增量索引） | `0x40` / 6 | 发 name+value，并把新条目加入动态表（源码：`HpackEncoder.java:343`） |
| 无索引字面量 | `0x00` / 4 | 发 name+value，不进动态表（源码：`HpackEncoder.java:346`） |
| 永不索引字面量 | `0x10` / 4 | 敏感头（如 `Authorization`），禁止缓存（源码：`HpackEncoder.java:349`） |
| 动态表大小更新 | `0x20` / 5 | 编码器通知解码器调整动态表上限（源码：`HpackEncoder.java:159`、`HpackEncoder.java:162`） |

字符串值（name/value）可进一步用 **Huffman 编码**压缩：`HpackEncoder.encodeStringLiteral` 在 Huffman 编码后长度小于原串时才启用，首字节 `0x80/7` 表示「Huffman 编码」（源码：`HpackEncoder.java:315`）。解码侧由 `HpackHuffmanDecoder` 还原。

`HpackDecoder` 的关键约束：

- 动态表上限必须在 `[MIN_HEADER_TABLE_SIZE, MAX_HEADER_TABLE_SIZE]` 之间，否则抛异常（源码：`HpackDecoder.java:321`，`MAX_HEADER_TABLE_SIZE = MAX_UNSIGNED_INT`，`HpackDecoder.java:322` 引用 `Http2CodecUtil.MAX_HEADER_TABLE_SIZE`）。
- 默认动态表上限 `DEFAULT_HEADER_TABLE_SIZE = 4096`（源码：`Http2CodecUtil.java:105`），也是 `HpackDecoder` 构造时的初值（源码：`HpackDecoder.java:106`）。
- 头部列表总大小受 `SETTINGS_MAX_HEADER_LIST_SIZE` 约束，超限触发 `PROTOCOL_ERROR`（源码：`Http2CodecUtil.java:239` 的 `headerListSizeExceeded`）。

> 为什么头部压缩对 HTTP/2 至关重要：HTTP/2 的流是**并发**复用的，若头部不压缩，每个请求都携带数百字节的重复头，多条流叠加后带宽与解析开销会抵消多路复用的收益；HPACK 还刻意避免 gzip 类压缩的「CRIME/BREACH」侧信道风险——敏感头用「永不索引」语义，从根本上不参与压缩。

## Multiplexing

一条 TCP 连接上可并发存在多条**流（stream）**，每条流是一个独立的、双向的帧序列。流的标识是 31 bit 的 `streamId`，**奇偶分配区分发起方**（源码：`Http2CodecUtil.java:151`）：

```java
// 源码：codec-http2/src/main/java/io/netty/handler/codec/http2/Http2CodecUtil.java:151
public static boolean isOutboundStream(boolean server, int streamId) {
    boolean even = (streamId & 1) == 0;
    return streamId > 0 && server == even;   // server 用偶数，client 用奇数
}
```

即：**客户端发起的流为奇数 ID，服务端发起（含 PUSH_PROMISE 的承诺流）为偶数 ID**。流 ID `0` 保留给连接级控制帧（SETTINGS、PING、GOAWAY 等）。

每条流有严格的状态机（`Http2Stream.State`，源码：`codec-http2/src/main/java/io/netty/handler/codec/http2/Http2Stream.java:26`）：

| 状态 | `localSideOpen` | `remoteSideOpen` | 含义 |
| :--- | :--- | :--- | :--- |
| `IDLE` | false | false | 新建、尚未收发 HEADERS |
| `RESERVED_LOCAL` | false | false | 服务端发过 PUSH_PROMISE，待发响应体 |
| `RESERVED_REMOTE` | false | false | 收到 PUSH_PROMISE，预留接收 |
| `OPEN` | true | true | 双向均开，正常收发 |
| `HALF_CLOSED_LOCAL` | false | true | 本端已发 `END_STREAM`，只收不发 |
| `HALF_CLOSED_REMOTE` | true | false | 对端已结束，本端仍可调 |
| `CLOSED` | false | false | 双向关闭 |

状态转移由 `HEADERS`/`DATA(END_STREAM)`/`RST_STREAM` 驱动（源码：`Http2Stream.java:74` 起的方法注释给出从 `IDLE` 出发的典型转移）。`DefaultHttp2Connection` 负责流的创建、编号分配、上下限检查与状态维护。

**对 HTTP/1.1 的改进**：HTTP/1.1 在同一连接上必须串行（pipelining 也仍受队头阻塞），一个慢响应会堵住后面所有请求；HTTP/2 的多路复用让 N 个请求/响应在一条 TCP 连接上交错传输，单条流的阻塞不再影响其它流。

## Flow Control

HTTP/2 的流控是**基于信用的滑动窗口**，分两层：

- **连接级窗口**：约束整条 TCP 连接上的 DATA 总量。
- **流级窗口**：每条流各自独立，由 `SETTINGS_INITIAL_WINDOW_SIZE` 设定初值。

`SETTINGS_INITIAL_WINDOW_SIZE` 的 settings id 为 `4`，默认窗口 `DEFAULT_WINDOW_SIZE = 65535` 字节（源码：`Http2CodecUtil.java:85`、`Http2CodecUtil.java:103`）。接收方用 `WINDOW_UPDATE` 帧归还信用，发送方只有在窗口有余量时才能发 DATA。

Netty 的实现：

- `DefaultHttp2LocalFlowController`：站在「本端接收」视角，维护每条流（及连接流）的可用窗口。收到 DATA 时 `receiveFlowControlledFrame` 扣减窗口（源码：`DefaultHttp2LocalFlowController.java:415`）；窗口低于下限则抛 `FLOW_CONTROL_ERROR`：

```java
// 源码：codec-http2/src/main/java/io/netty/handler/codec/http2/DefaultHttp2LocalFlowController.java:426
if (window < lowerBound) {
    throw streamError(stream.id(), FLOW_CONTROL_ERROR,
            "Flow control window exceeded for stream: %d", stream.id());
}
```

- `WINDOW_UPDATE` 增量若导致窗口溢出（`window > MAX_INITIAL_WINDOW_SIZE - delta`）同样抛 `FLOW_CONTROL_ERROR`（源码：`DefaultHttp2LocalFlowController.java:404`）。
- 窗口低于 `windowUpdateRatio` 阈值时，控制器自动发 `WINDOW_UPDATE` 把窗口补回初始值（源码：`DefaultHttp2LocalFlowController.java:453` 的 `writeWindowUpdateIfNeeded`）。
- `DefaultHttp2RemoteFlowController`：站在「本端发送」视角，依据对端通告的窗口决定能否发 DATA，并在应用层 `channel.write` 时做背压（`writable()` 反映窗口余量）。

要点：流控对**应用不可见**——`Http2FrameCodec` 在收到 DATA 时自动扣减 local 窗口、在消费完（应用 `read` 完）后自动补 `WINDOW_UPDATE`，无需业务代码手动管理。

## Netty Integration

### Http2FrameCodec：帧 ↔ 对象

`Http2FrameCodec extends Http2ConnectionHandler`（源码：`codec-http2/src/main/java/io/netty/handler/codec/http2/Http2FrameCodec.java:144`），把字节流里的各类 frame 解析成强类型对象（`DefaultHttp2HeadersFrame`、`DefaultHttp2DataFrame`、`DefaultHttp2SettingsFrame` 等，均实现 `Http2StreamFrame`），并挂到 pipeline。入站解析通过内部 `FrameListener implements Http2FrameListener` 完成（源码：`Http2FrameCodec.java:590`，构造时 `decoder.frameListener(new FrameListener())` 见 `Http2FrameCodec.java:171`）。

出站方向由 `write(...)` 分派（源码：`Http2FrameCodec.java:303`）：`Http2HeadersFrame` → `writeHeadersFrame`、`Http2GoAwayFrame` → `writeGoAwayFrame` 等。每个 `Http2StreamFrame` 必须带一个 `Http2FrameStream`（源码：`Http2FrameCodec.java:57` 说明「read 到的帧总会带 Http2FrameStream，写出的帧需要调用 `stream(Http2FrameStream)` 设置」）。

### Http2MultiplexHandler：流 ↔ 子 Channel

`Http2MultiplexHandler extends Http2ChannelDuplexHandler`（源码：`codec-http2/src/main/java/io/netty/handler/codec/http2/Http2MultiplexHandler.java:103`），把一条物理连接上的多路复用流**映射成多个「子 Channel」**：每出现一条新流，就创建一个 `Http2MultiplexHandlerStreamChannel`（源码：`Http2MultiplexHandler.java:268`、`Http2MultiplexHandler.java:271`；出站流在 `newStream()` 时创建，见 `Http2MultiplexHandler.java:305`）。

于是**每个流就像一条独立的连接**：开发者可以为 inbound 流挂一套与「单连接」无异的 inbound handler，为 outbound 流用 `Http2StreamChannelBootstrap` 开子 Channel 并挂 outbound handler。子 Channel 的 `writable()` 直接反映该流的流控窗口（源码：`Http2MultiplexHandler.java:88` 注释），写满会被流控背压。

典型服务端 pipeline：

```java
ChannelPipeline p = ch.pipeline();
p.addLast(SslHandler.class.getName(), sslHandler);      // TLS（h2 必须经 TLS）
p.addLast(Http2FrameCodecBuilder.forServer().build());  // 帧 ↔ 对象
p.addLast(new Http2MultiplexHandler(
        new MyStreamHandler()));                        // 每流一个子 Channel + 业务 handler
```

> [!NOTE]
>
> 4.2 中 `Http2MultiplexCodec`（早期「codec + multiplex」合一的类）已被 `Http2FrameCodec` + `Http2MultiplexHandler` 组合取代；新代码应直接用后者组合，二者通过 `Http2FrameStream` 衔接，职责更清晰。

## h2c Upgrade

**h2c** 指「明文（cleartext）HTTP/2」，不经过 TLS，常用于内网或对延迟极度敏感的场景。其升级基于 HTTP/1.1 的 `Upgrade` 机制：客户端先发一个带 `Upgrade: h2c` 与 `HTTP2-Settings` 的 HTTP/1.1 请求，服务端若支持则回 `101 Switching Protocols`，随后双方在同一条明文 TCP 上改跑 HTTP/2 帧。

Netty 用 `CleartextHttp2ServerUpgradeHandler extends ByteToMessageDecoder`（源码：`codec-http2/src/main/java/io/netty/handler/codec/http2/CleartextHttp2ServerUpgradeHandler.java:39`）承载该流程，并配合一个 `Http2ServerUpgradeCodec`（实现 `Http2ConnectionHandler` 的升级变体）在升级完成后接管 pipeline。它还会 fire 一个 `PriorKnowledgeUpgradeEvent` 以支持「先验知识（prior knowledge）」模式的直连 h2c（源码：`CleartextHttp2ServerUpgradeHandler.java:92`）。

> h2c 的 `Upgrade`/`prior knowledge` 与 ALPN 无关：ALPN 只在 TLS 握手中协商协议。TLS 上的 HTTP/2 用的 ALPN 名为 `h2`，HTTP/1.1 为 `http/1.1`（见 [Protocol - SslHandler / ALPN](/docs/CS/Framework/Netty/Protocol.md?id=alpn)）。

## HTTP/1.1 vs HTTP/2

| 维度 | HTTP/1.1 | HTTP/2 |
| :--- | :--- | :--- |
| 传输形态 | 文本明文，CRLF 分隔 | 二进制分帧（9 字节帧头 + payload） |
| 并发模型 | 单连接串行 / 多连接并发 | 单连接多路复用（流交错） |
| 队头阻塞 | 存在（一个慢响应堵住整条连接） | 流级隔离，单流阻塞不影响其它流 |
| 头部 | 每次完整重发，纯文本 | HPACK 静态表 + 动态表 + Huffman 压缩 |
| 服务端推送 | 不支持 | 支持 `PUSH_PROMISE` |
| 流控 | 依赖 TCP 窗口，仅连接级 | 逐流 + 连接级信用窗口（`WINDOW_UPDATE`） |
| 优先级 | 无 | `PRIORITY` 帧提示依赖与权重 |

## Links

- [Netty](/docs/CS/Framework/Netty/Netty.md)
- [Protocol Support 层（含 SslHandler / HTTP 接入）](/docs/CS/Framework/Netty/Protocol.md)
- [编解码器体系](/docs/CS/Framework/Netty/Codec.md)
- [ChannelHandler 与 Pipeline](/docs/CS/Framework/Netty/ChannelHandler.md)
- [EventLoop](/docs/CS/Framework/Netty/EventLoop.md)

## References

1. [RFC 9113 - HTTP/2](https://datatracker.ietf.org/doc/html/rfc9113)
2. [RFC 7541 - HPACK: Header Compression for HTTP/2](https://datatracker.ietf.org/doc/html/rfc7541)
3. [Netty 4.2 Javadoc - Http2FrameCodec](https://netty.io/4.2/api/io/netty/handler/codec/http2/Http2FrameCodec.html)
4. [Netty 4.2 Javadoc - Http2MultiplexHandler](https://netty.io/4.2/api/io/netty/handler/codec/http2/Http2MultiplexHandler.html)
