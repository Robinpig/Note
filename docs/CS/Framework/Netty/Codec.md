## Introduction

TCP 是字节流协议，一次 `read` 拿到的既可能不足一个请求，也可能包含多个请求——这就是粘包/拆包问题。Netty 把这件事从业务 handler 里剥离出来，交给 `io.netty.handler.codec` 的编解码器层：入站方向把 `ByteBuf` 解码成消息对象，出站方向把消息对象编码成 `ByteBuf`。

本文以 **Netty 4.2.19.Final**（git tag `netty-4.2.19.Final`，commit `64cc10f`）源码为准。编解码基类在 4.2 中位于 **`codec-base`** 模块（`codec-base/src/main/java/io/netty/handler/codec/ByteToMessageDecoder.java`），HTTP 相关在 `codec-http`。

> [!NOTE]
>
> 4.2 的模块拆分：老 `netty-codec` jar 仍在（artifact `netty-codec`，源码：`codec/pom.xml:26`），但它是**纯聚合包、自身已无 `src/`**，只依赖 `netty-codec-base` + `netty-codec-compression` + `netty-codec-protobuf`。因此找 `ByteToMessageDecoder` / `LengthFieldBasedFrameDecoder` / `ReplayingDecoder` 这类基类源码时，路径是 **`codec-base/...` 而不是 `codec/...`**。
>
> 本 checkout 只有 4.2.19 一个 tag，无法就地比对 4.1；因此下文凡涉及「4.1 vs 4.2」的判断，都只标注**在 4.2.19 中确实存在且值得注意**的东西，不反向断言 4.1 没有。典型的 4.2 新物是第三个 `Cumulator` 实现 `AdaptiveCumulator`（源码：`codec-base/src/main/java/io/netty/handler/codec/AdaptiveCumulator.java:29`，版权年份 2026），详见 [Cumulator](/docs/CS/Framework/Netty/Codec.md?id=cumulator)。

理解这一层的关键是两条主线：

- **累积（cumulation）**：上一次没解完的半包要留到下一次，由 `ByteToMessageDecoder` 内部的 `cumulation` 承担
- **判活（progress detection）**：怎么知道 `decode()` 这一轮有没有消费数据，从而决定是继续循环还是等更多数据

## ByteToMessageDecoder

### Type

```java
// 源码：codec-base/src/main/java/io/netty/handler/codec/ByteToMessageDecoder.java:78
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

几个容易读错的点（源码：`codec-base/src/main/java/io/netty/handler/codec/ByteToMessageDecoder.java:163` 的 `STATE_*`、`...:170` 的 `cumulator = MERGE_CUMULATOR`、`...:191` 的 `discardAfterReads = 16`）：

- **默认 cumulator 是 `MERGE_CUMULATOR`**（内存拷贝合并），不是 `COMPOSITE_CUMULATOR`
- `discardAfterReads` 默认 **16**：累积缓冲区累计参与 16 次读之后触发一次 `discardSomeReadBytes()`，回收已读空间
- 4.2.19 里**没有 `decodeWasNull` 字段**（老资料里出现的那个布尔标志在当前源码中不存在），判活完全靠比较 `oldInputLength == in.readableBytes()`
- `inputMessages` 是重入保护队列：在 `decode()` 里触发的 `channelRead` 不会递归，而是排队

### channelRead

```java
// 源码：codec-base/src/main/java/io/netty/handler/codec/ByteToMessageDecoder.java:286
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
                                //noinspection ThrowFromFinallyBlock
                                throw new IllegalReferenceCountException(
                                        getClass().getSimpleName() +
                                                "#decode() might have released its input buffer, " +
                                                "or passed it down the pipeline without a retain() call, " +
                                                "which is not allowed.", e);
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
// 源码：codec-base/src/main/java/io/netty/handler/codec/ByteToMessageDecoder.java:464
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

累积策略由 `Cumulator` 接口决定（源码：`codec-base/src/main/java/io/netty/handler/codec/ByteToMessageDecoder.java:596`），契约只有一条：**返回值持有累积后的全部字节，实现方负责 `in` 的引用计数**。默认实现是 `MERGE_CUMULATOR`（源码：`...:170`），可通过 `setCumulator(...)` 替换（源码：`...:221`）。

4.2.19 里共有三个实现：

| 实现                       | 定义位置                                                    | 策略                                                    |
| :----------------------- | :------------------------------------------------------ | :---------------------------------------------------- |
| `MERGE_CUMULATOR`        | `ByteToMessageDecoder.java:83`                          | 内存拷贝合并到一块连续 buffer（**默认**）                           |
| `COMPOSITE_CUMULATOR`    | `ByteToMessageDecoder.java:123`                         | 不拷贝，用 `CompositeByteBuf` 挂组件                          |
| `AdaptiveCumulator`      | `AdaptiveCumulator.java:29`（独立文件，`implements Cumulator`） | 按 `composeMinSize` 阈值在「挂组件」与「合并到尾组件」之间自适应切换          |

#### MERGE_CUMULATOR

把新数据**拷贝**进累积缓冲区：

```java
// 源码：codec-base/src/main/java/io/netty/handler/codec/ByteToMessageDecoder.java:85
public ByteBuf cumulate(ByteBufAllocator alloc, ByteBuf cumulation, ByteBuf in) {
    if (cumulation == in) {
        // when the in buffer is the same as the cumulation it is doubly retained, release it once
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
}
```

三个分支依次是：

1. **零拷贝接管**（`:91`）：累积区已空（`!cumulation.isReadable()`）且输入是连续内存（`in.isContiguous()`）时，直接释放空的累积区、把 `in` 提为新的累积区。这是**最常见路径**——上一包刚好解完、这一包刚好完整时，全程没有拷贝。
2. **原地追加**（`:107`）：累积区还有可读字节但容量够，一次 `writeBytes` 拷进去。
3. **扩容搬运**（`:105` → `expandCumulation`）：`required > maxWritableBytes()`，或 buffer 被共享（`refCnt() > 1`，说明下游有人 `slice().retain()` 过，扩容会踩到别人的内存），或只读时，新分配一块并整体搬运。

```java
// 源码：codec-base/src/main/java/io/netty/handler/codec/ByteToMessageDecoder.java:574
static ByteBuf expandCumulation(ByteBufAllocator alloc, ByteBuf oldCumulation, ByteBuf in) {
    int oldBytes = oldCumulation.readableBytes();
    int newBytes = in.readableBytes();
    int totalBytes = oldBytes + newBytes;
    ByteBuf newCumulation = alloc.buffer(alloc.calculateNewCapacity(totalBytes, Integer.MAX_VALUE));
    ByteBuf toRelease = newCumulation;
    try {
        // This avoids redundant checks and stack depth compared to calling writeBytes(...)
        newCumulation.setBytes(0, oldCumulation, oldCumulation.readerIndex(), oldBytes)
            .setBytes(oldBytes, in, in.readerIndex(), newBytes)
            .writerIndex(totalBytes);
        in.readerIndex(in.writerIndex());
        toRelease = oldCumulation;
        return newCumulation;
    } finally {
        toRelease.release();
    }
}
```

`alloc.calculateNewCapacity()` 是倍增到最近 2 的幂，所以反复扩容的拷贝量摊还后是 O(n) 而不是 O(n²)。

#### COMPOSITE_CUMULATOR

不拷贝，改用 `CompositeByteBuf` 挂组件：

```java
// 源码：codec-base/src/main/java/io/netty/handler/codec/ByteToMessageDecoder.java:125
public ByteBuf cumulate(ByteBufAllocator alloc, ByteBuf cumulation, ByteBuf in) {
    if (cumulation == in) {
        in.release();
        return cumulation;
    }
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
}
```

注意 `addFlattenedComponents(true, in)`：第二个参数会让 `CompositeByteBuf` 把 `in` 自身**摊平**成若干组件（若 `in` 也是 `CompositeByteBuf`），避免嵌套组合导致的索引退化。

#### Why MERGE by Default

源码 javadoc 直接给了结论（源码：`codec-base/src/main/java/io/netty/handler/codec/ByteToMessageDecoder.java:118`）：

```java
/**
 * Cumulate {@link ByteBuf}s by add them to a {@link CompositeByteBuf} and so do no memory copy whenever possible.
 * Be aware that {@link CompositeByteBuf} use a more complex indexing implementation so depending on your use-case
 * and the decoder implementation this may be slower than just use the {@link #MERGE_CUMULATOR}.
 */
```

拆开看是三笔账：

| 维度        | `MERGE_CUMULATOR`                          | `COMPOSITE_CUMULATOR`                 |
| :-------- | :----------------------------------------- | :----------------------------------- |
| 写入          | 每次 `channelRead` 一次 memcpy（或零拷贝接管）         | 挂一个组件，O(1)                            |
| 读取/随机访问    | 连续内存，`getInt` / `array()` 直取                | 需二分查找定位组件，再叠加组件内偏移                    |
| 组件数增长      | 恒为 1                                       | 组件数随 `channelRead` 次数线性增长，查找成本随之上升    |
| 与 `discardSomeReadBytes` 配合 | 有效：已读字节可直接回收                               | 组件被整体持有，单个组件内的已读字节回收不了               |

默认选 MERGE 的现实理由是：**绝大多数协议下累积区里的数据量很小（一个帧通常几 KB 以内）**，一次 memcpy 的绝对成本（纳秒级）远低于后续每一次解码读取都要走的间接寻址；同时累积区始终是**单块连续内存**，解码器可以放心用 `getInt(in.readerIndex())` 这类快速路径，而组合 buffer 上同样的代码会退化。只有在「每包很大且大多一次解不完」时（例如聚合大文件、TLS record 边界不对齐）组合才划算——`SslHandler` 就是按引擎类型主动换成 `COMPOSITE_CUMULATOR` 的，见 [TLS 与 SslHandler](/docs/CS/Framework/Netty/Protocol.md?id=sslhandler)。

#### AdaptiveCumulator

`COMPOSITE_CUMULATOR` 有个攻击面：如果攻击者每次只发 1 字节，累积区会挂出成百上千个组件，内存开销与读取成本都被放大。`AdaptiveCumulator` 就是为此加的第三个选项（源码：`codec-base/src/main/java/io/netty/handler/codec/AdaptiveCumulator.java:29`）：

```java
// 源码：codec-base/src/main/java/io/netty/handler/codec/AdaptiveCumulator.java:148
private static boolean shouldCompose(CompositeByteBuf composite, ByteBuf in, int composeMinSize) {
    int componentCount = composite.numComponents();
    if (componentCount == 0) {
        return true;
    }
    int inputSize = in.readableBytes();
    int tailStart = composite.toByteIndex(componentCount - 1);
    long tailSize = composite.writerIndex() - tailStart;
    return tailSize + inputSize >= composeMinSize;
}
```

判据是**尾组件大小 + 本次输入大小**是否达到 `composeMinSize`：

- 达到 → `composite.addFlattenedComponents(true, in)`，走零拷贝挂组件
- 未达到 → `mergeWithCompositeTail(...)`（源码：`...:183`），把输入合并进尾组件；尾组件能原地扩容就 `writeBytes`，否则按 `calculateNewCapacity` 重新分配（容量倍增，把 O(n²) 摊还为 O(n)）

用「尾 + 输入之和」而不是单看输入大小，是为了防攻击者**交替发送大小包**把策略稳在 compose 侧。

> [!NOTE]
>
> `AdaptiveCumulator` 在 4.2.19 中**只被定义、没有被任何主源码默认使用**（全仓 `grep AdaptiveCumulator` 只命中它自己的定义，`SslHandler` 换的仍是 `COMPOSITE_CUMULATOR`）。要用必须显式 `setCumulator(new AdaptiveCumulator(composeMinSize))`。

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

### Read Complete

`channelReadComplete` 是**每次读事件结束**的压缩点（源码：`codec-base/src/main/java/io/netty/handler/codec/ByteToMessageDecoder.java:366`）：

```java
// 源码：codec-base/src/main/java/io/netty/handler/codec/ByteToMessageDecoder.java:366
@Override
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

// 源码：.../ByteToMessageDecoder.java:377
protected final void discardSomeReadBytes() {
    if (cumulation != null && !first && cumulation.refCnt() == 1) {
        // discard some bytes if possible to make more room in the
        // buffer but only if the refCnt == 1  as otherwise the user may have
        // used slice().retain() or duplicate().retain().
        cumulation.discardSomeReadBytes();
    }
}
```

答案是**会压缩，但有条件**。`discardSomeReadBytes()` 把已读字节（readerIndex 之前的）丢弃、把剩余字节搬到 buffer 头部，从而腾出可写空间。两个守卫条件：

- **`!first`**：`first` 是「本次 `channelRead` 进入时 `cumulation` 是否为 null」（源码：`...:293` 的 `first = cumulation == null`）。为 true 说明累积区是刚从 `in` 零拷贝接管来的、还没经过合并，此时压缩既没必要也可能影响刚接管的 buffer。
- **`cumulation.refCnt() == 1`**：buffer 被共享说明下游可能 `slice().retain()` / `duplicate().retain()` 过，搬字节会破坏别人的视图。

第三个压缩点在 `channelRead` 的 finally 里（源码：`...:316`）：累积满 `discardAfterReads`（默认 16）次读之后强制压一次，避免长时间不触发 `channelReadComplete` 时 OOM。

`selfFiredChannelRead && !firedChannelRead && !isAutoRead()` 这一段是**半包兜底**：本轮虽然过了数据，但一条消息都没解出来（`firedChannelRead == false`），且用户关了自动读——此时不主动 `ctx.read()` 就会永久卡住，因为再没有读事件来触发下一轮解码。

### Removal and Release

```java
// 源码：codec-base/src/main/java/io/netty/handler/codec/ByteToMessageDecoder.java:258
@Override
public final void handlerRemoved(ChannelHandlerContext ctx) throws Exception {
    if (decodeState == STATE_CALLING_CHILD_DECODE) {
        decodeState = STATE_HANDLER_REMOVED_PENDING;
        return;
    }
    ByteBuf buf = cumulation;
    if (buf != null) {
        // Directly set this to null, so we are sure we not access it in any other method here anymore.
        cumulation = null;
        numReads = 0;
        int readable = buf.readableBytes();
        if (readable > 0) {
            ctx.fireChannelRead(buf);
            ctx.fireChannelReadComplete();
        } else {
            buf.release();
        }
    }
    handlerRemoved0(ctx);
}
```

注意 `handlerRemoved` 是 `final` 的，子类要挂清理逻辑只能重写 `handlerRemoved0(ctx)`（源码：`...:283`）。对累积区的处理尤其值得注意：**还有可读字节时不直接释放，而是 `fireChannelRead` + `fireChannelReadComplete` 把所有权移交下游**；只有不可读时才 `release()`。这样"解码器被摘掉但半包还没解完"的场景不会丢数据。

### Input Close and decodeLast

输入侧关闭时（对端 FIN 或半关闭事件）要走另一条路径（源码：`...:391`）：

```java
// 源码：codec-base/src/main/java/io/netty/handler/codec/ByteToMessageDecoder.java:406
private void channelInputClosed(ChannelHandlerContext ctx, boolean callChannelInactive) {
    CodecOutputList out = CodecOutputList.newInstance();
    try {
        channelInputClosed(ctx, out);
    } ... finally {
        try {
            if (cumulation != null) {
                cumulation.release();
                cumulation = null;
            }
            int size = out.size();
            fireChannelRead(ctx, out, size);
            if (size > 0) {
                // Something was read, call fireChannelReadComplete()
                ctx.fireChannelReadComplete();
            }
            if (callChannelInactive) {
                ctx.fireChannelInactive();
            }
        } finally {
            out.recycle();
        }
    }
}

// 源码：.../ByteToMessageDecoder.java:440
void channelInputClosed(ChannelHandlerContext ctx, List<Object> out) throws Exception {
    if (cumulation != null) {
        callDecode(ctx, cumulation, out);
        // If callDecode(...) removed the handle from the pipeline we should not call decodeLast(...) as this would
        // be unexpected.
        if (!ctx.isRemoved()) {
            // Use Unpooled.EMPTY_BUFFER if cumulation become null after calling callDecode(...).
            ByteBuf buffer = cumulation == null ? Unpooled.EMPTY_BUFFER : cumulation;
            decodeLast(ctx, buffer, out);
        }
    } else {
        decodeLast(ctx, Unpooled.EMPTY_BUFFER, out);
    }
}

// 源码：.../ByteToMessageDecoder.java:566
protected void decodeLast(ChannelHandlerContext ctx, ByteBuf in, List<Object> out) throws Exception {
    if (in.isReadable()) {
        // Only call decode() if there is something left in the buffer to decode.
        decodeRemovalReentryProtection(ctx, in, out);
    }
}
```

`decodeLast` 的用途是**收尾**：`decode()` 只在「攒够一个完整帧」时才产出，连接关闭时缓冲区里剩下的半帧永远等不到下一包，需要一次「不再等了」的回调来做三件事：

1. **再试一次解码**：默认实现只是 `in.isReadable()` 时再跑一遍 `decode`，让恰好在关闭时凑齐的帧仍能产出。
2. **产生终止消息**：例如 `HttpObjectDecoder.decodeLast`（源码：`codec-http/src/main/java/io/netty/handler/codec/http/HttpObjectDecoder.java:574`）在 `READ_VARIABLE_LENGTH_CONTENT` 状态且已无可读字节时补一个 `LastHttpContent.EMPTY_LAST_CONTENT`，让下游看到完整的「请求 + 结束」序列，而不是丢一个悬空的 `HttpContent`。
3. **产出错误信号**：仍在 `READ_HEADER` 状态就关闭，说明连头都没收全，`HttpObjectDecoder` 会补一个带 `PrematureChannelClosureException` 的无效消息，使下游能区分「正常结束」与「连接被掐断」。

两点容易踩：

- `decodeLast` **只在 `ctx.isRemoved()` 为 false 时调用**——`callDecode` 若把 handler 摘了（协议升级常见），就不再调用，因为此时 buffer 所有权已经移交。
- `channelInactive` 走 `channelInputClosed(ctx, true)`；半关闭走 `userEventTriggered` 里的 `ChannelInputShutdownEvent` → `channelInputClosed(ctx, false)`（源码：`...:396`），后者不传播 `channelInactive`，因为连接还能往回写。

## LengthFieldBasedFrameDecoder

长度字段是最常见的私有协议帧格式（源码：`codec-base/src/main/java/io/netty/handler/codec/LengthFieldBasedFrameDecoder.java:187`）。

### Frame Parameters

构造器共 **5 个参数**（源码：`...:236`，另有带 `byteOrder` 的 7 参版本 `...:302`，默认 `ByteOrder.BIG_ENDIAN`）：

| 参数                    | 语义（javadoc 原文）                                                                                                                  | 校验                                     |
| :-------------------- | :------------------------------------------------------------------------------------------------------------------------------ | :------------------------------------- |
| `maxFrameLength`      | the maximum length of the frame. If the length of the frame is greater than this value, `TooLongFrameException` will be thrown. | `checkPositive`                        |
| `lengthFieldOffset`   | the offset of the length field                                                                                                  | `checkPositiveOrZero`                  |
| `lengthFieldLength`   | the length of the length field                                                                                                  | 只支持 1/2/3/4/8，见 `getUnadjustedFrameLength` |
| `lengthAdjustment`    | the compensation value to add to the value of the length field                                                                   | 无校验，可为负                                |
| `initialBytesToStrip` | the number of first bytes to strip out from the decoded frame                                                                     | `checkPositiveOrZero`                  |
| `failFast`            | 是否一发现超长就抛（6/7 参构造器，默认 `true`）                                                                                                   | —                                      |

> [!NOTE]
>
> `lengthFieldEndOffset` **不是参数**，而是构造器里派生出来的字段（源码：`...:326`）：
>
> ```java
> // 源码：codec-base/src/main/java/io/netty/handler/codec/LengthFieldBasedFrameDecoder.java:326
> this.lengthFieldEndOffset = lengthFieldOffset + lengthFieldLength;
> ```
>
> 它参与每一次帧长计算，但只能由 `lengthFieldOffset + lengthFieldLength` 推出。另外构造器还校验 `lengthFieldOffset > maxFrameLength - lengthFieldLength` 时直接抛 `IllegalArgumentException`（源码：`...:314`）——即「长度字段必须落在 `maxFrameLength` 之内」。

### Decode Formula

核心计算（源码：`...:397` 的 `decode`）：

```java
// 源码：codec-base/src/main/java/io/netty/handler/codec/LengthFieldBasedFrameDecoder.java:397
protected Object decode(ChannelHandlerContext ctx, ByteBuf in) throws Exception {
    long frameLength = 0;
    if (frameLengthInt == -1) { // new frame
        if (discardingTooLongFrame) {
            discardingTooLongFrame(in);
        }
        if (in.readableBytes() < lengthFieldEndOffset) {
            return null;
        }
        int actualLengthFieldOffset = in.readerIndex() + lengthFieldOffset;
        frameLength = getUnadjustedFrameLength(in, actualLengthFieldOffset, lengthFieldLength, byteOrder);
        if (frameLength < 0) {
            failOnNegativeLengthField(in, frameLength, lengthFieldEndOffset);
        }
        frameLength += lengthAdjustment + lengthFieldEndOffset;
        if (frameLength < lengthFieldEndOffset) {
            failOnFrameLengthLessThanLengthFieldEndOffset(in, frameLength, lengthFieldEndOffset);
        }
        if (frameLength > maxFrameLength) {
            exceededFrameLength(in, frameLength);
            return null;
        }
        // never overflows because it's less than maxFrameLength
        frameLengthInt = (int) frameLength;
    }
    if (in.readableBytes() < frameLengthInt) { // frameLengthInt exist, just check buf
        return null;
    }
    if (initialBytesToStrip > frameLengthInt) {
        int frameLengthToSkip = frameLengthInt;
        frameLengthInt = -1;
        failOnFrameLengthLessThanInitialBytesToStrip(in, frameLengthToSkip, initialBytesToStrip);
    }
    in.skipBytes(initialBytesToStrip);

    // extract frame
    int readerIndex = in.readerIndex();
    int actualFrameLength = frameLengthInt - initialBytesToStrip;
    ByteBuf frame = extractFrame(ctx, in, readerIndex, actualFrameLength);
    in.readerIndex(readerIndex + actualFrameLength);
    frameLengthInt = -1; // start processing the next frame
    return frame;
}
```

即：

```
帧总长 frameLength = 长度字段原始值 + lengthAdjustment + lengthFieldEndOffset
                  = 长度字段原始值 + lengthAdjustment + (lengthFieldOffset + lengthFieldLength)
实际交出的帧长 = frameLength - initialBytesToStrip
```

`lengthAdjustment` 用于修正"长度字段只算 body 而不含 header"这类偏移，取值可以为负。四个失败分支都值得单独记：

| 分支                                                    | 触发条件                                        | 异常                              | 副作用                             |
| :---------------------------------------------------- | :------------------------------------------ | :------------------------------ | :------------------------------ |
| `failOnNegativeLengthField`                           | 长度字段原始值 < 0（4 字节及以上可能读到负数）                  | `CorruptedFrameException`       | 跳过 `lengthFieldEndOffset` 字节 |
| `failOnFrameLengthLessThanLengthFieldEndOffset`       | 调整后帧长 < `lengthFieldEndOffset`（`lengthAdjustment` 负数给多了） | `CorruptedFrameException`       | 同上                              |
| `exceededFrameLength`                                 | 调整后帧长 > `maxFrameLength`                    | `TooLongFrameException`         | 进入 `discardingTooLongFrame` 丢弃模式 |
| `failOnFrameLengthLessThanInitialBytesToStrip`        | `initialBytesToStrip > frameLengthInt`      | `CorruptedFrameException`       | 先复位 `frameLengthInt = -1` 再抛    |

`lengthFieldLength` 只支持 **1 / 2 / 3 / 4 / 8**（源码：`...:458`，`protected` 方法，可重写以自定义长度字段编码）：

```java
// 源码：codec-base/src/main/java/io/netty/handler/codec/LengthFieldBasedFrameDecoder.java:458
protected long getUnadjustedFrameLength(ByteBuf buf, int offset, int length, ByteOrder order) {
    buf = buf.order(order);
    long frameLength;
    switch (length) {
    case 1:
        frameLength = buf.getUnsignedByte(offset);
        break;
    case 2:
        frameLength = buf.getUnsignedShort(offset);
        break;
    case 3:
        frameLength = buf.getUnsignedMedium(offset);
        break;
    case 4:
        frameLength = buf.getUnsignedInt(offset);
        break;
    case 8:
        frameLength = buf.getLong(offset);
        break;
    default:
        throw new DecoderException(
                "unsupported lengthFieldLength: " + lengthFieldLength + " (expected: 1, 2, 3, 4, or 8)");
    }
    return frameLength;
}
```

取出的帧是**视图而非拷贝**（源码：`...:505`）：

```java
protected ByteBuf extractFrame(ChannelHandlerContext ctx, ByteBuf buffer, int index, int length) {
    return buffer.retainedSlice(index, length);
}
```

`retainedSlice` 会把累积区的引用计数 +1，因此下游必须 `release()`；好处是帧数据零拷贝，代价是**只要下游不释放，累积区整块内存就回收不了**——这也是 `discardSomeReadBytes` 要求 `refCnt() == 1` 的原因。

### State Across Reads

`frameLengthInt`（初值 `-1`，源码：`...:200`）跨 `channelRead` 缓存已解析的帧长：长度字段解析过一次后，后续 `channelRead` 只比较 `in.readableBytes() < frameLengthInt`，不再重复解析长度字段。注意它是 `int` 而非 `long`——因为已经确保 `frameLength <= maxFrameLength`，而 `maxFrameLength` 是 `int`，所以不会溢出（源码注释 `...:426`）。

`failFast` 控制超长帧的抛错时机，这是唯一受它影响的地方：

```java
// 源码：codec-base/src/main/java/io/netty/handler/codec/LengthFieldBasedFrameDecoder.java:484
private void failIfNecessary(boolean firstDetectionOfTooLongFrame) {
    if (bytesToDiscard == 0) {
        // Reset to the initial state and tell the handlers that the frame was too large.
        long tooLongFrameLength = this.tooLongFrameLength;
        this.tooLongFrameLength = 0;
        discardingTooLongFrame = false;
        if (!failFast || firstDetectionOfTooLongFrame) {
            fail(tooLongFrameLength);
        }
    } else {
        // Keep discarding and notify handlers if necessary.
        if (failFast && firstDetectionOfTooLongFrame) {
            fail(tooLongFrameLength);
        }
    }
}
```

`failFast = true`（默认）一发现帧长超限就抛；`false` 则先把整个超长帧读干净再抛。取舍要澄清：后者**不会**更快止损，反而要先把超长帧的字节全部读完（`exceededFrameLength` 里 `bytesToDiscard = frameLength - in.readableBytes()`，见 `...:364`），好处是连接状态保持一致、可以继续解析后续帧；`failFast = true` 节省的是内存与等待时间，代价是连接通常已经不可用。

四种典型参数组合：

| 场景                       | lengthFieldOffset | lengthFieldLength | lengthAdjustment | initialBytesToStrip |
| :----------------------- | :---------------- | :---------------- | :--------------- | :------------------ |
| 长度字段在头部，值 = body 长度        | 0                 | 2                 | 0                | 0                   |
| 长度字段在头部，值 = body 长度，要剥掉头 | 0                 | 2                 | 0                | 2                   |
| 长度字段值 = 整帧长度，要剥掉头        | 0                 | 2                 | -2               | 0                   |
| 长度字段前还有 2 字节魔数           | 2                 | 2                 | 0                | 0                   |

## ReplayingDecoder

`ByteToMessageDecoder` 的 `decode()` 里必须先判 `in.readableBytes() >= N` 再读，代码里到处是长度检查。`ReplayingDecoder` 用异常把这个检查藏起来（源码：`codec-base/src/main/java/io/netty/handler/codec/ReplayingDecoder.java:268`）：

```java
// 源码：codec-base/src/main/java/io/netty/handler/codec/ReplayingDecoder.java:268
public abstract class ReplayingDecoder<S> extends ByteToMessageDecoder {
    static final Signal REPLAY = Signal.valueOf(ReplayingDecoder.class, "REPLAY");

    private final ReplayingDecoderByteBuf replayable = new ReplayingDecoderByteBuf();
    private S state;
    private int checkpoint = -1;
}
```

### Error Is Replay

`ReplayingDecoderByteBuf` 包装累积区，数据不足时抛 `REPLAY`（一个**缓存的** `Signal` 实例，不带栈回溯，避免构造成本——`Signal.valueOf` 只在类初始化时构造一次）。子类 `decode` 拿到的是 `replayable` 而不是原始累积区，见 `callDecode`（源码：`...:341`）：

```java
// 源码：codec-base/src/main/java/io/netty/handler/codec/ReplayingDecoder.java:341
@Override
protected void callDecode(ChannelHandlerContext ctx, ByteBuf in, List<Object> out) {
    replayable.setCumulation(in);
    try {
        while (in.isReadable()) {
            int oldReaderIndex = checkpoint = in.readerIndex();
            int outSize = out.size();
            ...
            S oldState = state;
            int oldInputLength = in.readableBytes();
            try {
                decodeRemovalReentryProtection(ctx, replayable, out);
                if (ctx.isRemoved()) {
                    break;
                }
                if (outSize == out.size()) {
                    if (oldInputLength == in.readableBytes() && oldState == state) {
                        throw new DecoderException(
                                StringUtil.simpleClassName(getClass()) + ".decode() must consume the inbound " +
                                "data or change its state if it did not decode anything.");
                    } else {
                        // Previous data has been discarded or caused state transition.
                        continue;
                    }
                }
            } catch (Signal replay) {
                replay.expect(REPLAY);
                // Check if this handler was removed before continuing the loop.
                if (ctx.isRemoved()) {
                    break;
                }
                // Return to the checkpoint (or oldPosition) and retry.
                int checkpoint = this.checkpoint;
                if (checkpoint >= 0) {
                    in.readerIndex(checkpoint);
                } else {
                    // Called by cleanup() - no need to maintain the readerIndex
                    // anymore because the buffer has been released already.
                }
                break;
            }
            if (oldReaderIndex == in.readerIndex() && oldState == state) {
                throw new DecoderException(
                       StringUtil.simpleClassName(getClass()) + ".decode() method must consume the inbound data " +
                       "or change its state if it decoded something.");
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

三个关键设计：

1. **每轮循环都重置 checkpoint**（`...:345` 的 `int oldReaderIndex = checkpoint = in.readerIndex()`）。所以即便从不显式调 `checkpoint()`，REPLAY 时也会回卷到**本轮解码开始处**而不是缓冲区开头——至少不会重复解码整包。显式 `checkpoint()`（源码：`...:293`）的价值是把回卷点往前推，跳过已经确认消费掉的字段。
2. **回卷 = 重放**。REPLAY 之后 `break` 出循环，本次解出的消息（如果有）照常往下传；等下一包数据到达时，`decode` 会**从 checkpoint 重新执行一遍**。这就是「错误即回放」的代价：`decode` 必须是**幂等**的，不能在其中做累加型副作用（javadoc 在 `...:106` 给了 `values.offer()` 被重复执行的反例，正解是每轮先 `values.clear()`）。
3. **判活比父类多一个维度**：父类只看 `readableBytes` 是否变化，这里还要看 `oldState == state`。因为状态机解码允许「读了数据但不产出」也允许「没读数据但推进状态」，条件是**消费数据或切换状态，二者至少做一件**。对应的两条异常分别是「没产出消息时，既没消费数据也没换状态」（`...:377`）和「产出了消息时，既没消费数据也没换状态」（`...:409`）。

`checkpoint(S state)`（源码：`...:301`）是 `checkpoint()` + `state(state)` 的合体，配合 `Enum` 状态用最顺手。

### Input Close

`ReplayingDecoder` 还重写了 `channelInputClosed`（源码：`...:325`），因为关闭时不能再让 `ReplayingDecoderByteBuf` 抛 REPLAY：

```java
// 源码：codec-base/src/main/java/io/netty/handler/codec/ReplayingDecoder.java:325
@Override
final void channelInputClosed(ChannelHandlerContext ctx, List<Object> out) throws Exception {
    try {
        replayable.terminate();
        if (cumulation != null) {
            callDecode(ctx, internalBuffer(), out);
        } else {
            replayable.setCumulation(Unpooled.EMPTY_BUFFER);
        }
        decodeLast(ctx, replayable, out);
    } catch (Signal replay) {
        // Ignore
        replay.expect(REPLAY);
    }
}
```

`terminate()` 之后 `replayable` 不再抛 REPLAY，因此 `decodeLast` 里即使数据不足也会正常返回；外层 catch 只是兜底。

### Cost

代价是每次读操作都可能抛异常、且 `ReplayingDecoderByteBuf` 是间接层，性能不如直接写检查的 `ByteToMessageDecoder`；好处是能用近乎阻塞式的写法表达复杂协议。不需要状态机时 `extends ReplayingDecoder<Void>`。

## Encoder

### MessageToByteEncoder

出站方向的基类（源码：`codec-base/src/main/java/io/netty/handler/codec/MessageToByteEncoder.java:46`）：

```java
// 源码：codec-base/src/main/java/io/netty/handler/codec/MessageToByteEncoder.java:46
public abstract class MessageToByteEncoder<I> extends ChannelOutboundHandlerAdapter {
    private final TypeParameterMatcher matcher;
    private final boolean preferDirect;

    protected MessageToByteEncoder() {
        this(true);
    }
```

四个构造器（`...:54`/`:61`/`:72`/`:85`）本质是 `preferDirect` 与「类型参数自动推断 vs 显式 `Class`」的笛卡尔积：`matcher = TypeParameterMatcher.find(this, MessageToByteEncoder.class, "I")`（`...:73`）通过反射解析泛型实参，若子类是泛型擦除边界不明的写法就需要走显式 `Class` 版本。

### Allocate and Write

整条流程只有 160 行，`write` 是全部逻辑（源码：`...:99`）：

```java
// 源码：codec-base/src/main/java/io/netty/handler/codec/MessageToByteEncoder.java:99
@Override
public void write(ChannelHandlerContext ctx, Object msg, ChannelPromise promise) throws Exception {
    ByteBuf buf = null;
    try {
        if (acceptOutboundMessage(msg)) {
            @SuppressWarnings("unchecked")
            I cast = (I) msg;
            buf = allocateBuffer(ctx, cast, preferDirect);
            try {
                encode(ctx, cast, buf);
            } finally {
                ReferenceCountUtil.release(cast);
            }

            if (buf.isReadable()) {
                ctx.write(buf, promise);
            } else {
                buf.release();
                ctx.write(Unpooled.EMPTY_BUFFER, promise);
            }
            buf = null;
        } else {
            ctx.write(msg, promise);
        }
    } catch (EncoderException e) {
        throw e;
    } catch (Throwable e) {
        throw new EncoderException(e);
    } finally {
        if (buf != null) {
            buf.release();
        }
    }
}
```

按执行顺序拆：

1. **类型匹配**：`acceptOutboundMessage(msg)` 用 `matcher` 判断；不匹配就 `ctx.write(msg, promise)` 原样透传，不做任何分配。这是「一个 pipeline 里串多个 encoder」的基础。
2. **分配目标 buffer**：`allocateBuffer(ctx, cast, preferDirect)`，默认实现（源码：`...:137`）：

   ```java
   // 源码：codec-base/src/main/java/io/netty/handler/codec/MessageToByteEncoder.java:137
   protected ByteBuf allocateBuffer(ChannelHandlerContext ctx, I msg, boolean preferDirect) throws Exception {
       if (preferDirect) {
           return ctx.alloc().ioBuffer();
       } else {
           return ctx.alloc().heapBuffer();
       }
   }
   ```

   注意是 `ioBuffer()` 而非 `directBuffer()`：`ioBuffer()` 在能可靠释放直接内存（`PlatformDependent.hasUnsafe()` 且 direct buffer 不被 `-Dio.netty.noPreferDirect` 之类的开关禁用）时才给 direct，否则退回 heap。子类重写这个方法可以按消息预估大小给 `initialCapacity`，省掉扩容。
3. **编码并释放原消息**：`encode` 之后立刻 `ReferenceCountUtil.release(cast)`（在 `finally` 里，即使 `encode` 抛异常也释放）。**这一句意味着 `MessageToByteEncoder` 会消费掉入参消息的引用**，业务代码里 `writeAndFlush(msg)` 之后不能再碰 `msg`，也不能自己再 `release()`。
4. **空结果处理**：编码后 `buf` 不可读就释放它、改写一个 `Unpooled.EMPTY_BUFFER`——不能什么都不写，否则调用方拿到的 promise 永远不会完成。
5. **异常路径**：异常时 `buf != null`，由最外层 `finally` 释放，避免 `encode` 中途抛异常导致泄漏。

### MessageToMessageEncoder

消息到消息的转换，允许一对多（源码：`codec-base/src/main/java/io/netty/handler/codec/MessageToMessageEncoder.java:82`）：

```java
if (out.isEmpty()) {
    throw new EncoderException(StringUtil.simpleClassName(this) + " must produce at least one message.");
}
```

单条直接 `ctx.write`，多条用 `PromiseCombiner` 把多个 promise 聚合成一个——这样调用方拿到的 `ChannelFuture` 仍然代表"这批消息都写完"。两个细节：

- 多条且 `promise == ctx.voidPromise()` 时走 `writeVoidPromise`（源码：`codec-base/src/main/java/io/netty/handler/codec/MessageToMessageEncoder.java:118`），不创建 `PromiseCombiner`，减少 GC 压力（注释引用 issue #2525）
- `encode` 抛异常时先 `ReferenceCountUtil.safeRelease(cast)`（源码：`...:92`）再 `PlatformDependent.throwException(th)`，保证入参消息不泄漏

### ByteToMessageCodec / MessageToMessageCodec

`ByteToMessageCodec<I> extends ChannelDuplexHandler`（源码：`codec-base/src/main/java/io/netty/handler/codec/ByteToMessageCodec.java:34`），内部持有一个匿名 `ByteToMessageDecoder` 和一个匿名 `MessageToByteEncoder`，两个构造器都 `ensureNotSharable()`（`...:73` 与 `...:87`）。入站 `decode` / 出站 `encode` 由外层的抽象方法转发进去。

`MessageToMessageCodec<INBOUND_IN, OUTBOUND_IN> extends ChannelDuplexHandler`（源码：`codec-base/src/main/java/io/netty/handler/codec/MessageToMessageCodec.java:55`）内部同样是两个匿名 handler，但**它们的 `isSharable()` 委托给外层**（`...:71` 与 `...:89`）——所以外层若标了 `@Sharable`，内层也跟着被识别为可共享。这是**唯一可以 `@Sharable` 的双工编解码基类**（前提是自身无状态）。

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

长度守卫在每次追加前（源码：`codec-base/src/main/java/io/netty/handler/codec/MessageAggregator.java:285`）：

```java
// 源码：codec-base/src/main/java/io/netty/handler/codec/MessageAggregator.java:285
final C m = (C) msg;
// Handle oversized message.
if (content.readableBytes() > maxContentLength - m.content().readableBytes()) {
    // By convention, full message type extends first message type.
    S s = (S) currentMessage;
    invokeHandleOversizedMessage(ctx, s);
    return;
}

// Append the content of the chunk.
appendPartialContent(content, m.content());
```

`appendPartialContent`（源码：`...:325`）只在 `partialContent.isReadable()` 时才 `addComponent(true, partialContent.retain())`，空的 chunk 不会白占一个组件——这对 `maxCumulationBufferComponents`（默认 1024，源码：`...:55`）是有效的保护。

`Expect: 100-continue` 由 `newContinueResponse` 钩子处理（源码：`...:221` 的调用点），`HttpObjectAggregator` 的实现会视长度是否超限回 `CONTINUE`(100) 或 `TOO_LARGE`(413)。

## CodecOutputList

编解码是最热的路径，每次 `channelRead`/`write` 都要一个临时 `List` 装结果，用 `ArrayList` 会产生大量短命对象和扩容拷贝。`CodecOutputList` 用 `FastThreadLocal` 池化（源码：`codec-base/src/main/java/io/netty/handler/codec/CodecOutputList.java:29`）：

```java
// 源码：codec-base/src/main/java/io/netty/handler/codec/CodecOutputList.java:29
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

每线程缓存 16 个实例，每个内部数组初始容量 16；池空时降级为容量 4 的不回收实例。`clear()` 只置 `size = 0` 不置 null，`recycle()` 才清空引用防止内存泄漏。`getUnsafe(int)`（源码：`...:207`）跳过边界检查配合 `size` 使用。

注意它用的是 `FastThreadLocal` 池而非 `Recycler` 对象池——因为生命周期严格限制在单次 `channelRead` 调用栈内，不需要跨线程回收。

`insertSinceRecycled()`（源码：`...:185`）是一个容易被忽略的字段：它记录「这个 list 自上次 `recycle()` 以来是否真的插入过元素」，`ByteToMessageDecoder.channelRead` 用它来累积 `firedChannelRead`（源码：`.../ByteToMessageDecoder.java:324`），从而在关闭自动读时判断本轮是否真的有消息传给下游。

## Frame Decoders

| 类                              | 边界依据        | 要点                                                                                                                                          | 源码位置                                       |
| :----------------------------- | :---------- | :------------------------------------------------------------------------------------------------------------------------------------------ | :----------------------------------------- |
| `FixedLengthFrameDecoder`      | 固定长度        | `in.readableBytes() < frameLength` 返回 null，否则 `in.readRetainedSlice(frameLength)`                                                          | `.../FixedLengthFrameDecoder.java:73`      |
| `LineBasedFrameDecoder`        | `\n` / `\r\n` | `delimLength = buffer.getByte(eol) == '\r'? 2 : 1`；`stripDelimiter` 为 false 时把换行符一起留在帧里                                                  | `.../LineBasedFrameDecoder.java:110`       |
| `DelimiterBasedFrameDecoder`   | 自定义分隔符数组    | 构造期若 `isLineBased(delimiters) && !isSubclass()` 就内部造一个 `LineBasedFrameDecoder` 全权委派（`...:184`）；否则对每个分隔符扫描，取**最短帧**                        | `.../DelimiterBasedFrameDecoder.java:245`  |
| `LengthFieldBasedFrameDecoder` | 长度字段        | 见 [Frame Parameters](/docs/CS/Framework/Netty/Codec.md?id=frame-parameters)，`extractFrame` 默认 `retainedSlice`                                                                   | `.../LengthFieldBasedFrameDecoder.java:397` |
| `LengthFieldPrepender`         | —（编码器）      | `@Sharable`（`...:55`），`LengthFieldBasedFrameDecoder` 的对端，支持 `lengthIncludesLengthFieldLength` 让长度值含长度字段自身                                | `.../LengthFieldPrepender.java:56`         |

`DelimiterBasedFrameDecoder` 的「取最短帧」值得一提：多个分隔符可能都在缓冲区里命中，只有**最早出现的那个**才是真正的帧边界，所以 `minFrameLength`（`...:248`）要在所有分隔符的扫描结果里取最小值；扫描窗口按倍增方式扩张，避免每次只多扫一个字节。

## Pitfalls

- **不要在 `ByteToMessageDecoder` 子类上加 `@Sharable`**：构造器会 `ensureNotSharable()`（源码：`.../ByteToMessageDecoder.java:195`），因为它持有连接级 `cumulation`
- **不要在 `decode()` 里 `await` 或做耗时操作**：它跑在 EventLoop 线程上，会阻塞同一线程上的所有连接
- **`decode()` 不消费数据也不产出消息会白跑**：`callDecode` 在 `out` 空且 `readableBytes` 未变时 `break`（不会死循环），但等于每次读到数据都白跑一遍 `decode`；`ReplayingDecoder` 上更严格——既不消费数据也不换状态会直接抛 `DecoderException`
- **`decode()` 产出了消息却不移动 readerIndex 会抛异常**：`callDecode` 里 `out` 非空且 `readableBytes` 未变 → `DecoderException`（源码：`.../ByteToMessageDecoder.java:502`）
- **下游必须释放 `LengthFieldBasedFrameDecoder` 的帧**：`extractFrame` 返回的是 `retainedSlice`，累积区的引用计数被 +1；不释放会让整个累积区回收不了，`discardSomeReadBytes` 也会因 `refCnt() > 1` 而失效
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
4. [Netty 4.2 Javadoc - MessageToByteEncoder](https://netty.io/4.2/api/io/netty/handler/codec/MessageToByteEncoder.html)
5. [Netty Source (GitHub)](https://github.com/netty/netty)
