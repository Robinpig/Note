## Introduction

TCP 是字节流协议，一次 `read` 拿到的既可能不足一个请求，也可能包含多个请求——这就是粘包/拆包问题。Netty 把这件事从业务 handler 里剥离出来，交给 `io.netty.handler.codec` 的编解码器层：入站方向把 `ByteBuf` 解码成消息对象，出站方向把消息对象编码成 `ByteBuf`。

本文以 **Netty 4.2**（最新 GA 为 4.2.19.Final，2026-10-06 发布）源码为准；4.1 系列最新为 4.1.139.Final（同日发布）。编解码基类在 4.2 中位于 **`codec-base`** 模块（`io.netty.handler.codec`），HTTP 相关在 `codec-http`。经逐行比对，本文涉及的 `ByteToMessageDecoder` / `LengthFieldBasedFrameDecoder` 在 4.1 与 4.2 之间**几乎没有差异**（前者仅一处泛型语法差异，后者 diff 为空），因此结论对两个版本同时成立。

理解这一层的关键是两条主线：

- **累积（cumulation）**：上一次没解完的半包要留到下一次，由 `ByteToMessageDecoder` 内部的 `cumulation` 承担
- **判活（progress detection）**：怎么知道 `decode()` 这一轮有没有消费数据，从而决定是继续循环还是等更多数据

## ByteToMessageDecoder

### Type

```java
public abstract class ByteToMessageDecoder extends ChannelInboundHandlerAdapter {

    protected ByteToMessageDecoder() {
        ensureNotSharable();
    }

    protected abstract void decode(ChannelHandlerContext ctx, ByteBuf in, List<Object> out) throws Exception;
}
```

构造器里的 `ensureNotSharable()` 是硬约束：**子类绝不能标 `@Sharable`**，因为它持有 `cumulation` 这种连接级可变状态。

### State

```java
private static final byte STATE_INIT = 0;
private static final byte STATE_CALLING_CHILD_DECODE = 1;
private static final byte STATE_HANDLER_REMOVED_PENDING = 2;

// Used to guard the inputs for reentrant channelRead calls
private Queue<Object> inputMessages;
ByteBuf cumulation;
private Cumulator cumulator = MERGE_CUMULATOR;
private boolean singleDecode;
private boolean first;
private boolean firedChannelRead;
private boolean selfFiredChannelRead;
private byte decodeState = STATE_INIT;
private int discardAfterReads = 16;
private int numReads;
```

几个容易读错的点：

- **默认 cumulator 是 `MERGE_CUMULATOR`**（内存拷贝合并），不是 `COMPOSITE_CUMULATOR`
- `discardAfterReads` 默认 **16**：累积缓冲区累计参与 16 次读之后触发一次 `discardSomeReadBytes()`，回收已读空间
- 不存在 `decodeWasNull` 字段（那是 Netty 4.0 的实现），判活改用 `oldInputLength == in.readableBytes()`
- `inputMessages` 是重入保护队列：在 `decode()` 里触发的 `channelRead` 不会递归，而是排队

### channelRead

```java
public void channelRead(ChannelHandlerContext ctx, Object input) throws Exception {
    if (decodeState == STATE_INIT) {
        do {
            if (input instanceof ByteBuf) {
                selfFiredChannelRead = true;
                CodecOutputList out = CodecOutputList.newInstance();
                try {
                    first = cumulation == null;
                    cumulation = cumulator.cumulate(ctx.alloc(),
                            first ? EMPTY_BUFFER : cumulation, (ByteBuf) input);
                    callDecode(ctx, cumulation, out);
                } catch (DecoderException e) {
                    throw e;
                } catch (Exception e) {
                    throw new DecoderException(e);
                } finally {
                    try {
                        if (cumulation != null && !cumulation.isReadable()) {
                            numReads = 0;
                            try {
                                cumulation.release();
                            } catch (IllegalReferenceCountException e) {
                                throw new IllegalReferenceCountException(e.getMessage() +
                                        " This could happen if the pipeline has multiple " +
                                        ByteToMessageDecoder.class.getSimpleName() +
                                        " instances, which is not allowed.");
                            }
                            cumulation = null;
                        } else if (++numReads >= discardAfterReads) {
                            numReads = 0;
                            discardSomeReadBytes();
                        }
                        int size = out.size();
                        firedChannelRead |= out.insertSinceRecycled();
                        fireChannelRead(ctx, out, size);
                    } finally {
                        out.recycle();
                    }
                }
            } else {
                ctx.fireChannelRead(input);
            }
        } while (inputMessages != null && (input = inputMessages.poll()) != null);
    } else {
        // Reentrant call. Bail out here and let original call process our message.
        if (inputMessages == null) {
            inputMessages = new ArrayDeque<>(2);
        }
        inputMessages.offer(input);
    }
}
```

注意职责边界：**`channelRead` 里不触发 `channelReadComplete`**，只负责累积、解码、逐条 `fireChannelRead`。

### callDecode

```java
protected void callDecode(ChannelHandlerContext ctx, ByteBuf in, List<Object> out) {
    try {
        while (in.isReadable()) {
            final int outSize = out.size();
            if (outSize > 0) {
                fireChannelRead(ctx, out, outSize);
                out.clear();
                if (ctx.isRemoved()) {
                    break;
                }
            }
            int oldInputLength = in.readableBytes();
            decodeRemovalReentryProtection(ctx, in, out);

            if (ctx.isRemoved()) {
                break;
            }

            if (out.isEmpty()) {
                if (oldInputLength == in.readableBytes()) {
                    break;
                } else {
                    continue;
                }
            }

            if (oldInputLength == in.readableBytes()) {
                throw new DecoderException(StringUtil.simpleClassName(getClass()) +
                        ".decode() did not read anything but decoded a message.");
            }

            if (isSingleDecode()) {
                break;
            }
        }
    } catch (DecoderException e) {
        throw e;
    } catch (Exception cause) {
        throw new DecoderException(cause);
    }
}
```

判活逻辑读起来像绕口令，展开是三种情形：

| 情形                                       | 结果                                                |
| :--------------------------------------- | :------------------------------------------------ |
| `out` 空 + `readableBytes` 未变              | 数据不够，跳出循环等下一次读                                    |
| `out` 空 + `readableBytes` 变少              | 消费了但未产出消息（例如只丢弃了分隔符），`continue` 继续             |
| `out` 非空 + `readableBytes` 未变            | **异常**：产出消息却没移动 readerIndex，说明 `decode` 实现有 bug |

### Cumulator

`MERGE_CUMULATOR` 把新数据**拷贝**进累积缓冲区：

```java
if (cumulation == in) {
    in.release();
    return cumulation;
}
if (!cumulation.isReadable() && in.isContiguous()) {
    // If cumulation is empty and input buffer is contiguous, use it directly
    cumulation.release();
    return in;
}
try {
    final int required = in.readableBytes();
    if (required > cumulation.maxWritableBytes() ||
        required > cumulation.maxFastWritableBytes() && cumulation.refCnt() > 1 ||
        cumulation.isReadOnly()) {
        return expandCumulation(alloc, cumulation, in);
    }
    cumulation.writeBytes(in, in.readerIndex(), required);
    in.readerIndex(in.writerIndex());
    return cumulation;
} finally {
    in.release();
}
```

两个关键优化：累积区已空且输入是**连续内存**时直接接管输入 buffer（零拷贝）；容量不足时走 `expandCumulation`，按 `alloc.calculateNewCapacity()` 扩容并搬运。

`COMPOSITE_CUMULATOR` 不拷贝，改用 `CompositeByteBuf` 拼组件：

```java
if (!cumulation.isReadable()) {
    cumulation.release();
    return in;
}
CompositeByteBuf composite = null;
try {
    if (cumulation instanceof CompositeByteBuf && cumulation.refCnt() == 1) {
        composite = (CompositeByteBuf) cumulation;
        // Writer index must equal capacity if we are going to "write" new components to the end
        if (composite.writerIndex() != composite.capacity()) {
            composite.capacity(composite.writerIndex());
        }
    } else {
        composite = alloc.compositeBuffer(Integer.MAX_VALUE).addFlattenedComponents(true, cumulation);
    }
    composite.addFlattenedComponents(true, in);
    in = null;
    return composite;
} finally {
    if (in != null) {
        in.release();
        if (composite != null && composite != cumulation) {
            composite.release();
        }
    }
}
```

取舍：组合模式省掉拷贝，但 `CompositeByteBuf` 的随机访问要二分查找组件，且组件数增长后访问成本上升。默认走 `MERGE_CUMULATOR` 是因为大多数场景数据量小、拷贝代价低于组合的间接寻址。

### Removal Reentry

```java
final void decodeRemovalReentryProtection(ChannelHandlerContext ctx, ByteBuf in, List<Object> out)
        throws Exception {
    decodeState = STATE_CALLING_CHILD_DECODE;
    try {
        decode(ctx, in, out);
    } finally {
        if (inputMessages == null || inputMessages.isEmpty()) {
            boolean removePending = decodeState == STATE_HANDLER_REMOVED_PENDING;
            decodeState = STATE_INIT;
            if (removePending) {
                fireChannelRead(ctx, out, out.size());
                out.clear();
                handlerRemoved(ctx);
            }
        }
    }
}
```

场景是"在 `decode()` 里把自己从 pipeline 移除"（例如握手完成后换掉解码器）。若立即执行 `handlerRemoved`，累积区会在消息传播完之前被释放，形成 use-after-free。Netty 的做法是先标记 `STATE_HANDLER_REMOVED_PENDING`，把已解码消息传播干净，再真正走 `handlerRemoved`。

### Release

```java
public void channelReadComplete(ChannelHandlerContext ctx) throws Exception {
    numReads = 0;
    discardSomeReadBytes();
    if (selfFiredChannelRead && !firedChannelRead && !ctx.channel().config().isAutoRead()) {
        ctx.read();
    }
    firedChannelRead = false;
    selfFiredChannelRead = false;
    ctx.fireChannelReadComplete();
}

protected final void discardSomeReadBytes() {
    if (cumulation != null && !first && cumulation.refCnt() == 1) {
        cumulation.discardSomeReadBytes();
    }
}
```

`handlerRemoved` 里对累积区的处理尤其值得注意：**还有可读字节时不直接释放，而是 `fireChannelRead` 把所有权移交下游**；只有不可读时才 `release()`。这样"解码器被摘掉但半包还没解完"的场景不会丢数据。

## LengthFieldBasedFrameDecoder

长度字段是最常见的私有协议帧格式。四个参数决定帧边界：

| 参数                   | 语义（javadoc 原文）                                                                                                                     |
| :------------------- | :-------------------------------------------------------------------------------------------------------------------------------- |
| `maxFrameLength`     | the maximum length of the frame. If the length of the frame is greater than this value, `TooLongFrameException` will be thrown.    |
| `lengthFieldOffset`  | the offset of the length field                                                                                                    |
| `lengthFieldLength`  | the length of the length field                                                                                                    |
| `lengthAdjustment`   | the compensation value to add to the value of the length field                                                                     |
| `initialBytesToStrip`| the number of first bytes to strip out from the decoded frame                                                                       |

核心计算：

```java
int actualLengthFieldOffset = in.readerIndex() + lengthFieldOffset;
frameLength = getUnadjustedFrameLength(in, actualLengthFieldOffset, lengthFieldLength, byteOrder);

if (frameLength < 0) {
    failOnNegativeLengthField(in, frameLength, lengthFieldEndOffset);
}

frameLength += lengthAdjustment + lengthFieldEndOffset;
```

即**帧总长 = 长度字段原始值 + lengthAdjustment + (lengthFieldOffset + lengthFieldLength)**。`lengthAdjustment` 用于修正"长度字段只算 body 而不含 header"这类偏移，取值可以为负。

`lengthFieldLength` 只支持 **1 / 2 / 3 / 4 / 8**：

```java
switch (length) {
case 1: frameLength = buf.getUnsignedByte(offset);   break;
case 2: frameLength = buf.getUnsignedShort(offset);  break;
case 3: frameLength = buf.getUnsignedMedium(offset); break;
case 4: frameLength = buf.getUnsignedInt(offset);    break;
case 8: frameLength = buf.getLong(offset);           break;
default: throw new DecoderException("unsupported lengthFieldLength: " + lengthFieldLength
                                    + " (expected: 1, 2, 3, 4, or 8)");
}
```

`failFast` 控制超长帧的抛错时机，这是唯一受它影响的地方：

```java
private void failIfNecessary(boolean firstDetectionOfTooLongFrame) {
    if (bytesToDiscard == 0) {
        long tooLongFrameLength = this.tooLongFrameLength;
        this.tooLongFrameLength = 0;
        discardingTooLongFrame = false;
        if (!failFast || firstDetectionOfTooLongFrame) {
            fail(tooLongFrameLength);
        }
    } else {
        if (failFast && firstDetectionOfTooLongFrame) {
            fail(tooLongFrameLength);
        }
    }
}
```

`failFast = true`（默认）一发现帧长超限就抛；`false` 则先把整个超长帧读干净再抛——后者能避免攻击者用超长帧持续占用带宽，但对端可能在抛错前已经发完。另有 `frameLengthInt` 字段跨 `channelRead` 缓存已解析的帧长，避免重复解析长度字段。

四种典型参数组合：

| 场景                       | lengthFieldOffset | lengthFieldLength | lengthAdjustment | initialBytesToStrip |
| :----------------------- | :---------------- | :---------------- | :--------------- | :------------------ |
| 长度字段在头部，值 = body 长度        | 0                 | 2                 | 0                | 0                   |
| 长度字段在头部，值 = body 长度，要剥掉头 | 0                 | 2                 | 0                | 2                   |
| 长度字段值 = 整帧长度，要剥掉头        | 0                 | 2                 | -2               | 0                   |
| 长度字段前还有 2 字节魔数           | 2                 | 2                 | 0                | 0                   |

## ReplayingDecoder

`ByteToMessageDecoder` 的 `decode()` 里必须先判 `in.readableBytes() >= N` 再读，代码里到处是长度检查。`ReplayingDecoder` 用异常把这个检查藏起来：

```java
public abstract class ReplayingDecoder<S> extends ByteToMessageDecoder {
    static final Signal REPLAY = Signal.valueOf(ReplayingDecoder.class, "REPLAY");
    private final ReplayingDecoderByteBuf replayable = new ReplayingDecoderByteBuf();
    private S state;
    private int checkpoint = -1;
}
```

`ReplayingDecoderByteBuf` 包装累积区，数据不足时抛 `REPLAY`（一个**缓存的** `Signal` 实例，不带栈回溯，避免构造成本）。`callDecode` 捕获它并回卷 readerIndex：

```java
} catch (Signal replay) {
    replay.expect(REPLAY);
    if (ctx.isRemoved()) {
        break;
    }
    int checkpoint = this.checkpoint;
    if (checkpoint >= 0) {
        in.readerIndex(checkpoint);
    }
    break;
}
```

`checkpoint()` 记录当前 readerIndex 作为"本次解码的起点"，REPLAY 时回卷到这里而不是缓冲区开头，避免重复解码已读部分。判活条件比父类多一条：

```java
if (oldInputLength == in.readableBytes() && oldState == state) {
    throw new DecoderException(StringUtil.simpleClassName(getClass()) +
            ".decode() must consume the inbound data or change its state if it did not decode anything.");
}
```

即**消费数据或切换状态，二者至少做一件**。代价是每次读操作都可能抛异常、且 `ReplayingDecoderByteBuf` 是间接层，性能不如直接写检查的 `ByteToMessageDecoder`；好处是能用近乎阻塞式的写法表达复杂协议。不需要状态机时 `extends ReplayingDecoder<Void>`。

## Encoder

### MessageToByteEncoder

```java
public abstract class MessageToByteEncoder<I> extends ChannelOutboundHandlerAdapter {
    private final TypeParameterMatcher matcher;
    private final boolean preferDirect;

    protected MessageToByteEncoder() {
        this(true);
    }
```

`write` 的关键决策是**编码结果为空就不往下传**：

```java
if (buf.isReadable()) {
    ctx.write(buf, promise);
} else {
    buf.release();
    ctx.write(Unpooled.EMPTY_BUFFER, promise);
}
```

缓冲区来自 `allocateBuffer`，注意是 `ioBuffer()` 而非 `directBuffer()`：

```java
protected ByteBuf allocateBuffer(ChannelHandlerContext ctx, I msg, boolean preferDirect) throws Exception {
    if (preferDirect) {
        return ctx.alloc().ioBuffer();
    } else {
        return ctx.alloc().heapBuffer();
    }
}
```

`ioBuffer()` 在能可靠释放直接内存时才给 direct，否则退回 heap。

### MessageToMessageEncoder

消息到消息的转换，允许一对多：

```java
if (out.isEmpty()) {
    throw new EncoderException(StringUtil.simpleClassName(this) + " must produce at least one message.");
}
```

单条直接 `ctx.write`，多条用 `PromiseCombiner` 把多个 promise 聚合成一个——这样调用方拿到的 `ChannelFuture` 仍然代表"这批消息都写完"。

### ByteToMessageCodec / MessageToMessageCodec

`ByteToMessageCodec<I> extends ChannelDuplexHandler`，内部持有一个 `ByteToMessageDecoder` 和一个 `MessageToByteEncoder`，构造时同样 `ensureNotSharable()`。

`MessageToMessageCodec<INBOUND_IN, OUTBOUND_IN>` 是**唯一可以 `@Sharable` 的编解码基类**（前提是自身无状态），它把 `isSharable()` 委托给外层实现。

| 基类                           | 入站         | 出站         | @Sharable |
| :--------------------------- | :--------- | :--------- | :-------- |
| `ByteToMessageDecoder`       | ByteBuf→消息  | —          | ❌ 构造器禁止   |
| `MessageToMessageDecoder`    | 消息→消息      | —          | ✅（需无状态）   |
| `MessageToByteEncoder`       | —          | 消息→ByteBuf | ✅（需无状态）   |
| `MessageToMessageEncoder`    | —          | 消息→消息      | ✅（需无状态）   |
| `ByteToMessageCodec`         | ByteBuf→消息  | 消息→ByteBuf | ❌ 构造器禁止   |
| `MessageToMessageCodec`      | 消息→消息      | 消息→消息      | ✅（需无状态）   |

## MessageAggregator

HTTP 的 `HttpRequest` + 多个 `HttpContent` + `LastHttpContent` 这种"一个逻辑消息被切成一串"的模型，由聚合器重新拼起来：

```java
public abstract class MessageAggregator<I, S, C extends ByteBufHolder, O extends ByteBufHolder>
        extends MessageToMessageDecoder<I> {

    static final int DEFAULT_MAX_COMPOSITEBUFFER_COMPONENTS = 1024;
}
```

聚合过程：

1. start 消息（`HttpMessage`）到达时建 `CompositeByteBuf content = ctx.alloc().compositeBuffer(maxCumulationBufferComponents)`
2. 后续 content 消息 `content.addComponent(true, partialContent.retain())`，仅当 `isReadable()`
3. `isLastContentMessage(m)` 为真时 `finishAggregation0` 并把完整消息放进 `out`

长度守卫在每次追加前：

```java
if (content.readableBytes() > maxContentLength - m.content().readableBytes()) {
    invokeHandleOversizedMessage(ctx, m);
}
```

`Expect: 100-continue` 由 `newContinueResponse` 钩子处理，`HttpObjectAggregator` 的实现会视长度是否超限回 `CONTINUE`(100) 或 `TOO_LARGE`(413)。

## CodecOutputList

编解码是最热的路径，每次 `channelRead`/`write` 都要一个临时 `List` 装结果，用 `ArrayList` 会产生大量短命对象和扩容拷贝。`CodecOutputList` 用 `FastThreadLocal` 池化：

```java
final class CodecOutputList extends AbstractList<Object> implements RandomAccess {

    private static final FastThreadLocal<CodecOutputLists> CODEC_OUTPUT_LISTS_POOL =
            new FastThreadLocal<CodecOutputLists>() {
                @Override
                protected CodecOutputLists initialValue() throws Exception {
                    // 16 CodecOutputList per Thread are cached.
                    return new CodecOutputLists(16);
                }
            };
}
```

每线程缓存 16 个实例，每个内部数组初始容量 16；池空时降级为容量 4 的不回收实例。`clear()` 只置 `size = 0` 不置 null，`recycle()` 才清空引用防止内存泄漏。`getUnsafe(int)` 跳过边界检查配合 `size` 使用。

注意它用的是 `FastThreadLocal` 池而非 `Recycler` 对象池——因为生命周期严格限制在单次 `channelRead` 调用栈内，不需要跨线程回收。

## Frame Decoders

| 类                              | 边界依据                                    | 要点                                                                    |
| :----------------------------- | :-------------------------------------- | :-------------------------------------------------------------------- |
| `FixedLengthFrameDecoder`      | 固定长度                                    | `in.readableBytes() < frameLength` 返回 null，否则 `readRetainedSlice(frameLength)` |
| `LineBasedFrameDecoder`        | `\n` / `\r\n`                           | `delimLength = buffer.getByte(eol) == '\r' ? 2 : 1`；`stripDelimiter` 控制是否保留换行符 |
| `DelimiterBasedFrameDecoder`   | 自定义分隔符数组                                | 若分隔符是行分隔符且非子类，内部委派给 `LineBasedFrameDecoder`；否则在倍增扫描窗口内取**最短帧**       |
| `LengthFieldBasedFrameDecoder` | 长度字段                                    | 见上文                                                                   |
| `LengthFieldPrepender`         | —（编码器）                                  | `@Sharable`，`LengthFieldBasedFrameDecoder` 的对端，支持 `lengthIncludesLengthFieldLength` |

## Pitfalls

- **不要在 `ByteToMessageDecoder` 子类上加 `@Sharable`**：构造器会抛异常，因为它持有连接级 `cumulation`
- **不要在 `decode()` 里 `await` 或做耗时操作**：它跑在 EventLoop 线程上，会阻塞同一线程上的所有连接
- **`decode()` 不消费数据也不产出消息会死循环**：`callDecode` 在 `out` 空且 `readableBytes` 未变时跳出，等于每次读到数据都白跑一遍
- **超长帧要设 `failFast` 之外的防护**：即便抛了 `TooLongFrameException`，连接通常已经不可用，应配合 `ChannelFutureListener.CLOSE`
- **`HttpObjectAggregator` 的 `maxContentLength` 是内存上界**：聚合用的是 `CompositeByteBuf`，超限前不会拒绝，需要按业务峰值而非平均值设

## Links

- [Netty](/docs/CS/Framework/Netty/Netty.md)
- [ByteBuf](/docs/CS/Framework/Netty/ByteBuf.md)
- [ChannelHandler](/docs/CS/Framework/Netty/ChannelHandler.md)
- [HTTP / WebSocket / TLS 协议栈](/docs/CS/Framework/Netty/Protocol.md)
- [内存池](/docs/CS/Framework/Netty/memory.md)
- [Bootstrap](/docs/CS/Framework/Netty/Bootstrap.md)

## References

1. [Netty 4.2 Javadoc - ByteToMessageDecoder](https://netty.io/4.2/api/io/netty/handler/codec/ByteToMessageDecoder.html)
2. [Netty 4.2 Javadoc - LengthFieldBasedFrameDecoder](https://netty.io/4.2/api/io/netty/handler/codec/LengthFieldBasedFrameDecoder.html)
3. [Netty 4.2 Javadoc - ReplayingDecoder](https://netty.io/4.2/api/io/netty/handler/codec/ReplayingDecoder.html)
4. [Netty Source (GitHub)](https://github.com/netty/netty)
