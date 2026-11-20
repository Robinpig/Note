# gRPC Framing: Length-Prefixed Message

## Introduction

gRPC 的"薄"体现在它几乎没有自定义传输协议——它把一次 RPC 完整地映射到 HTTP/2 帧序列上。理解 gRPC 编码，本质就是理解三件事：请求/响应如何拆成 HEADERS / DATA / Trailers、消息体如何定界、状态与元数据如何通过头部传递。完整的帧序列与强制头部约束见 [Architecture](/docs/CS/Framework/gRPC/Architecture.md)；本页聚焦**消息定界**：从一个 Java 对象到 HTTP/2 DATA 帧之间，那 5 个字节前缀是怎么来的。

> 版本基线：grpc-java 1.75.0（commit 3abc0e6）。以下片段均取自该 tag。

两个反直觉点：

- **帧边界与消息边界无关**：一条 DATA 帧可以承载多条消息的片段，一条消息也可能跨多条 DATA 帧。接收方必须按长度前缀**重新组帧**，不能假设"一次 `messagesAvailable` 就是一条完整消息"之外的对齐。
- **帧头高 7 位是保留位**：源码用 `RESERVED_MASK = 0xFE` 校验，非零直接判 `INTERNAL`，并非只有"压缩标志 + 长度"两个字段那么宽松。

## The Wire Format

gRFC 规范给出的消息格式：

```text
Length-Prefixed-Message → Compressed-Flag Message-Length Message
Compressed-Flag         → 0 / 1     ; 1 字节无符号整数
Message-Length          →           ; 4 字节无符号整数（大端）
Message                 → *{binary octet}
```

即每条消息前有 **5 字节前缀**：1 字节压缩标志 + 4 字节大端长度。Java 侧 `MessageFramer` 把这三个常量写死：

```java
// core/src/main/java/io/grpc/internal/MessageFramer.java
private static final int HEADER_LENGTH = 5;
private static final byte UNCOMPRESSED = 0;
private static final byte COMPRESSED = 1;
```

## Framing Outbound: MessageFramer

`writePayload` 是发送侧的入口。它先判断消息是否已知长度（`KnownLength` 或 `ByteArrayInputStream`），据此走两条路径：已知长度走 `writeKnownLengthUncompressed`（可预分配缓冲），未知长度走 `BufferChainOutputStream` 边写边扩。

```java
// core/src/main/java/io/grpc/internal/MessageFramer.java
@Override
public void writePayload(InputStream message) {
  verifyNotClosed();
  messagesBuffered++;
  currentMessageSeqNo++;
  currentMessageWireSize = 0;
  statsTraceCtx.outboundMessage(currentMessageSeqNo);
  boolean compressed = messageCompression && compressor != Codec.Identity.NONE;
  int written = -1;
  int messageLength = -2;
  try {
    messageLength = getKnownLength(message);
    if (messageLength != 0 && compressed) {
      written = writeCompressed(message, messageLength);
    } else {
      written = writeUncompressed(message, messageLength);
    }
  } catch (IOException e) {
    throw Status.INTERNAL.withDescription("Failed to frame message")
        .withCause(e).asRuntimeException();
  }
  // ...
}
```

写已知长度消息时，5 字节头由 `ByteBuffer.put(flag).putInt(length)` 产出——`ByteBuffer` 默认**大端**，这正是规范要求的字节序：

```java
// core/src/main/java/io/grpc/internal/MessageFramer.java
private int writeKnownLengthUncompressed(InputStream message, int messageLength)
    throws IOException {
  if (maxOutboundMessageSize >= 0 && messageLength > maxOutboundMessageSize) {
    throw Status.RESOURCE_EXHAUSTED
        .withDescription(String.format(Locale.US, "message too large %d > %d",
            messageLength, maxOutboundMessageSize))
        .asRuntimeException();
  }
  headerScratch.clear();
  headerScratch.put(UNCOMPRESSED).putInt(messageLength);
  // Allocate the initial buffer chunk based on frame header + payload length.
  knownLengthPendingAllocation = HEADER_LENGTH + messageLength;
  writeRaw(headerScratch.array(), 0, headerScratch.position());
  return writeToOutputStream(message, outputStreamAdapter);
}
```

压缩路径则先压进 `BufferChainOutputStream`，压缩完才知道长度，再回头写头：

```java
// core/src/main/java/io/grpc/internal/MessageFramer.java
private void writeBufferChain(BufferChainOutputStream bufferChain, boolean compressed) {
  int messageLength = bufferChain.readableBytes();
  // ... max size check ...
  headerScratch.clear();
  headerScratch.put(compressed ? COMPRESSED : UNCOMPRESSED).putInt(messageLength);
  WritableBuffer writeableHeader = bufferAllocator.allocate(HEADER_LENGTH);
  writeableHeader.write(headerScratch.array(), 0, headerScratch.position());
  if (messageLength == 0) {
    // the payload had 0 length so make the header the current buffer.
    buffer = writeableHeader;
    return;
  }
  sink.deliverFrame(writeableHeader, false, false, messagesBuffered - 1);
  // ... commit all but last buffer to sink ...
}
```

> [!NOTE]
> 压缩上下文**不跨消息边界保持**：每条消息的 `writeCompressed` 都新建一个 `compressor.compress(bufferChain)` 流并在 `finally` 里 close。这与"整条 HTTP/2 流共用一个压缩上下文"的直觉相反，也是为什么每条消息都要单独带压缩标志位。

`maxOutboundMessageSize` 默认未设置（`-1`，即不限制），可由 `CallOptions` 或 channel builder 注入；一旦设置，超限时抛 `RESOURCE_EXHAUSTED`。

## Deframing Inbound: MessageDeframer

接收侧是个两状态机 `HEADER → BODY → HEADER`：

```java
// core/src/main/java/io/grpc/internal/MessageDeframer.java
private enum State {
  HEADER, BODY
}
private State state = State.HEADER;
private int requiredLength = HEADER_LENGTH;
private boolean compressedFlag;
```

`processHeader` 读 1 字节类型 + 4 字节长度，同时校验保留位和上限：

```java
// core/src/main/java/io/grpc/internal/MessageDeframer.java
private static final int HEADER_LENGTH = 5;
private static final int COMPRESSED_FLAG_MASK = 1;
private static final int RESERVED_MASK = 0xFE;

private void processHeader() {
  int type = nextFrame.readUnsignedByte();
  if ((type & RESERVED_MASK) != 0) {
    throw Status.INTERNAL.withDescription(
        "gRPC frame header malformed: reserved bits not zero")
        .asRuntimeException();
  }
  compressedFlag = (type & COMPRESSED_FLAG_MASK) != 0;

  // Update the required length to include the length of the frame.
  requiredLength = nextFrame.readInt();
  if (requiredLength < 0 || requiredLength > maxInboundMessageSize) {
    throw Status.RESOURCE_EXHAUSTED.withDescription(
        String.format(Locale.US, "gRPC message exceeds maximum size %d: %d",
            maxInboundMessageSize, requiredLength))
        .asRuntimeException();
  }
  // ...
  state = State.BODY;
}
```

`processBody` 根据压缩标志选解压流，投递给 listener 后立刻回到 HEADER 状态、把 `requiredLength` 复位为 5——这就是按长度前缀重新组帧的地方：

```java
// core/src/main/java/io/grpc/internal/MessageDeframer.java
private void processBody() {
  InputStream stream = compressedFlag ? getCompressedBody() : getUncompressedBody();
  nextFrame.touch();
  nextFrame = null;
  listener.messagesAvailable(new SingleMessageProducer(stream));

  // Done with this frame, begin processing the next header.
  state = State.HEADER;
  requiredLength = HEADER_LENGTH;
}
```

解压时若服务端未配置对应 decompressor，直接 `INTERNAL`——这是"客户端声明了压缩但服务端没注册解码器"的典型报错来源：

```java
// core/src/main/java/io/grpc/internal/MessageDeframer.java
private InputStream getCompressedBody() {
  if (decompressor == Codec.Identity.NONE) {
    throw Status.INTERNAL.withDescription(
        "Can't decode compressed gRPC message as compression not configured")
        .asRuntimeException();
  }
  // ...
}
```

## Size Limits and Buffering

几个源码中的硬编码值：

| 常量 | 值 | 位置 / 含义 |
| :--- | :--- | :--- |
| `DEFAULT_MAX_MESSAGE_SIZE` | 4 MiB | `GrpcUtil`，入站消息默认上限 |
| `DEFAULT_MAX_HEADER_LIST_SIZE` | 8192 (8 KiB) | `GrpcUtil`，头部列表上限，对齐 HTTP/2 `SETTINGS_MAX_HEADER_LIST_SIZE` |
| `MAX_BUFFER_SIZE` | 2 MiB | `MessageDeframer`，内部组合缓冲上限 |
| `FIRST_BUFFER_SIZE` | 4096 | `MessageFramer.BufferChainOutputStream`，首块大小，不够则翻倍扩张 |

> [!WARNING]
> 这些是 **Java** 实现的默认值。grpc-go 的 `defaultClientMaxHeaderListSize` / `defaultServerMaxHeaderListSize` 是 **16 MiB**，8 KiB 在那边只是"计划中的默认值"（`upcomingDefaultHeaderListSize`）。跨语言对照时务必先看实现，别照抄。

## Request and Response Framing

把 5 字节消息放进 HTTP/2，一次 unary 调用的帧序列（取自官方规范）：

```text
HEADERS (flags = END_HEADERS)
:method = POST
:scheme = http
:path = /google.pubsub.v2.PublisherService/CreateTopic
:authority = pubsub.googleapis.com
grpc-timeout = 1S
content-type = application/grpc+proto
grpc-encoding = gzip

DATA (flags = END_STREAM)
<Length-Prefixed Message>
```

```text
HEADERS (flags = END_HEADERS)
:status = 200
content-type = application/grpc+proto

DATA
<Length-Prefixed Message>

HEADERS (flags = END_STREAM, END_HEADERS)
grpc-status = 0
```

关键点：`:method` 恒为 POST，RPC 方法名编码进 `:path`（`/Service/Method`）；`TE` 必须为 `trailers`（探测不兼容代理）；`:status` 恒为 200，真正成败在 trailer 的 `grpc-status`；`content-type` 必须以 `application/grpc` 开头，否则应返回 HTTP 415。响应有正常路径与 **Trailers-Only**（立即出错时状态放唯一 HEADERS 帧）两条，且状态**必须**出现在 Trailers 中。

## Links

- [gRPC](/docs/CS/Framework/gRPC/gRPC.md) — 枢纽：架构、版本基线与纠偏
- [ClientCallChain](/docs/CS/Framework/gRPC/ClientCallChain.md) — sendMessage 如何调用到 framer
- [Streaming](/docs/CS/Framework/gRPC/Streaming.md) — 帧之上如何承载四种流模式
- [Status](/docs/CS/Framework/gRPC/Status.md) — trailer 中的状态码与元数据
- [Protocol Buffers](/docs/CS/Distributed/RPC/ProtoBuf.md) — 默认 codec 与 IDL
- [HTTP](/docs/CS/CN/HTTP/HTTP.md) — HTTP/2 帧、流与头部压缩基础

## References

- [grpc-java v1.75.0 MessageFramer.java](https://github.com/grpc/grpc-java/blob/v1.75.0/core/src/main/java/io/grpc/internal/MessageFramer.java)
- [grpc-java v1.75.0 MessageDeframer.java](https://github.com/grpc/grpc-java/blob/v1.75.0/core/src/main/java/io/grpc/internal/MessageDeframer.java)
- [gRFC: gRPC over HTTP/2](https://github.com/grpc/grpc/blob/master/doc/PROTOCOL-HTTP2.md)
- [RFC 7540 - HTTP/2](https://datatracker.ietf.org/doc/rfc7540/)
