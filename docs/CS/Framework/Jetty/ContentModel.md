## Introduction

Jetty 12 把「一条 HTTP 报文的 body 到底怎么流动」这件事，从 servlet 层的 `InputStream`/`OutputStream` 里彻底剥离出来，下沉成一组只有三个方法的接口：`Content.Source`、`Content.Sink`、`Content.Chunk`。这层抽象要解决的问题很具体：同一套读写代码必须同时服务四种差异极大的载体——HTTP/1.1 的字节流、HTTP/2 的多路复用帧、WebSocket 的二进制帧、以及客户端侧的响应体。如果每种载体各自实现一套 buffered reader 和 write queue，阻塞 API 就得写四遍，背压语义也会各走各的。

分层后的结果是这样一条链：

| 层 | 位置 | 职责 |
| :--- | :--- | :--- |
| 端点 | `jetty-io` 的 `EndPoint` | 只做 socket 级读写，产出/消费 `ByteBuffer` |
| 内容抽象 | `jetty-io` 的 `Content.*` | 把字节切成带 last/failure 语义的 `Chunk`，定义 read/demand 与 write/Callback |
| 报文编解码 | `jetty-http` 的 `HttpParser` / `HttpGenerator` | 字节 ↔ `MetaData` + `HttpFields`，与内容传输解耦 |
| 连接驱动 | `HttpConnection`（`jetty-server` 的 `internal` 包） | 用 `IteratingCallback` 把 parser/generator 的状态机跑起来 |
| 阻塞外壳 | `jetty-ee10-servlet` 的 `BlockingContentProducer` / `HttpOutput` | 用 `Blocker` 与 semaphore 把异步内核盖成 `read()`/`write()` |

看懂 `Content.*` 加 `Blocker`，Jetty 12 的 IO 就只剩下「谁来驱动循环」这一个问题；剩下的都在 [Jetty/Threading.md](/docs/CS/Framework/Jetty/Threading.md) 与 [Jetty/RequestFlow.md](/docs/CS/Framework/Jetty/RequestFlow.md) 里。HTTP/2 侧如何复用同一套接口见 [Jetty/Http2.md](/docs/CS/Framework/Jetty/Http2.md)，servlet 语义映射见 [Jetty/EeLayer.md](/docs/CS/Framework/Jetty/EeLayer.md)。

## Content is a namespace class not an interface

⚠️ **Jetty 12 里不存在顶层的 `ContentSource` / `ContentSink` 类**。`jetty-io-12.1.14/org/eclipse/jetty/io/Content.java:61` 是一个纯粹的命名空间类，注释（`:57-59`）说明它只是用来承载内嵌接口与静态工具方法的容器：

```java
// Content.java:61
public class Content
{
    public static void copy(Source source, Sink sink, Callback callback)   // :81-84
    {
        new ContentCopier(source, sink, callback).iterate();
    }
```

三个内嵌接口才是主角，全库所有实现都是它们的实现类：

| 接口 | 声明位置 | 核心方法 | 语义 |
| :--- | :--- | :--- | :--- |
| `Content.Source` | `Content.java:162` | `Chunk read()`、`void demand(Runnable)`、`fail(Throwable)` | 读侧，非阻塞 pull |
| `Content.Sink` | `Content.java:714` | `void write(boolean last, ByteBuffer, Callback)` | 写侧，非阻塞 push |
| `Content.Chunk` | `Content.java:945`，`extends RetainableByteBuffer` | `isLast()`、`getFailure()`、`retain()`/`release()` | 一次读到的内容单元 |

注意 `Chunk` 是 `RetainableByteBuffer` 的子类型——它不是「一个 buffer 加个标志位」的 DTO，而是带引用计数、可以直接归还进池的缓冲区。这个决定贯穿全篇：内容的所有权靠 `retain`/`release` 传递，不靠 GC。

## Source read and demand contract

`Source` 的 javadoc（`Content.java:111-160`）罕见地给了一段完整的惯用法伪码，值得原样抄下来，因为几乎所有坑都出自没照它写：

```java
public void onContentAvailable() {
    while (true) {
        // Read a chunk
        Chunk chunk = source.read();

        // There is no chunk, demand to be called back and exit.
        if (chunk == null) {
            source.demand(this::onContentAvailable);
            return;
        }

        // The chunk is a failure.
        if (Content.Chunk.isFailure(chunk))
        {
            boolean fatal = chunk.isLast();
            if (fatal)
            {
                handleFatalFailure(chunk.getFailure());
                return;
            }
            else
            {
                handleTransientFailure(chunk.getFailure());
                continue;
            }
        }

        // It's a valid chunk, consume the chunk's bytes.
        ByteBuffer buffer = chunk.getByteBuffer();
        // ...

        // Release the chunk when it has been consumed.
        chunk.release();

        // Exit if the Content.Source is fully consumed.
        if (chunk.isLast())
            break;
    }
}
```

`read()`（`:639`）返回 `null` 表示「此刻没有」，不表示「结束了」；一旦返回过 last chunk，后续 `read()` 会继续返回 last chunk（实例可能不同），所以 last 是幂等的、可重读的。

`demand(Runnable)`（`:661-671`）的契约是这套模型里最容易被略过的部分，逐条列出来：

| 契约条款 | 原文要点 | 违反的后果 |
| :--- | :--- | :--- |
| 可重入 | 实现保证 `demand` 与回调互相递归时不会栈溢出 | 自己写实现时若同步调用回调，深循环会 `StackOverflowError` |
| 回调串行化 | 前一个 demand 回调返回前，不会调用下一个 | **回调里绝不能阻塞等待未来的 demand 回调**，否则自锁 |
| 可能 spurious | 回调被调用后 `read()` 仍可能返回 `null` | 把「回调来了」当成「有数据」，会写出漏数据的代码 |
| 重复 demand 抛异常 | 已有 pending demand 时再调 → `IllegalStateException` | 循环里 `demand` 不加 `return` 就抛 |
| 回调抛异常 | 自动转为 `fail(Throwable)` | 业务异常会把整条内容流终结，而不是被外层 catch |

`fail(Throwable)`（`:685`）与 `fail(Throwable, boolean last)`（`:697-702`）区分两种失败：`last = true` 是持久失败，行为等同单参版本，会丢弃尚未读到的累积 chunk；`last = false` 是瞬时失败，failure chunk 会按序夹在正常 chunk 中间，之后的 `read()` 仍可能返回真实内容。**读方可以把瞬时失败当持久失败处理，反过来不行**（javadoc 明说）。`rewind()` 是 `default false`——可重读不是义务，`PathContentSource` 只是把它转委托给内部 source。

静态工厂与聚合方法决定「怎么拿到一个 Source」和「怎么一次性拿完」：`from(ByteBuffer...)`、`from(Path)` / `from(Path, offset, length)`、`from(ByteBufferPool.Sized, ByteChannel | SeekableByteChannel | InputStream, ...)`（`:200-262` 起），聚合侧 `asByteBuffer`、`asByteBufferAsync`、`asByteArrayAsync`、`asRetainableByteBuffer`、`asString`。还有一条容易漏：`from(Content.Source, offset, length)` 在 offset/length 恰好覆盖全量时**直接返回原 source 不包装**，否则返回 `ContentSourceRange`。

## Chunk failure semantics and release

`Chunk.from(ByteBuffer, boolean last)`（`:1012` 附近）有一个省内存的细节：buffer 没有 remaining 时不分配对象，直接返回单例 `EOF`（last）或 `EMPTY`（非 last）。

失败如何沿着链传下去，看 `Chunk.next(Chunk)`（`:1173` 起）最清楚——它是给 `while` 循环用的状态函数：

```java
static Chunk next(Chunk chunk)
{
    if (chunk == null)
        return null;
    if (Content.Chunk.isFailure(chunk))
    {
        // Handle transient failure.
        if (!chunk.isLast())
            return null;

        // Handle persistent failure returning a new exception to
        // avoid problems with try-with-resources and addSuppressed().
        return new Empty()
        {
            private Throwable failure;

            @Override
            public Throwable getFailure()
            {
                if (failure == null)
                    failure = new IOException(chunk.getFailure());
                return failure;
            }
            ...
        };
    }
    if (chunk.isLast())
        return EOF;
    return null;
}
```

注意它把持久失败的原始异常**重新包一层 `IOException`**，注释给出的理由很实用：如果复用同一个异常实例，配合 try-with-resources 的 `addSuppressed()` 会出现「自己 suppress 自己」的问题。`releaseAndNext(Chunk)`（`:1228`）= `release()` + `next()`，是循环里最常用的收尾。`isFailure(chunk)` 的定义是「非 null 且 `getFailure() != null`」。

`asChunk(...)`（`:1012-1103` 一组重载）负责把 `RetainableByteBuffer` 或带 `Runnable`/`Consumer<ByteBuffer>` 释放器的 buffer 变成 `Chunk`，因此**谁负责归还内存是构造期决定**的：`from(RetainableByteBuffer, last)` 返回的 chunk 不额外 `retain`，release 它会直接 release 传进来的 buffer。

## RetainableByteBuffer and ArrayByteBufferPool

`Chunk` 的引用计数来自 `RetainableByteBuffer`（`jetty-io-12.1.14/org/eclipse/jetty/io/RetainableByteBuffer.java`）与更底层的 `Retainable`。池的默认实现是 `ArrayByteBufferPool`，构造 Server 时即用（见 [Jetty/Connector.md](/docs/CS/Framework/Jetty/Connector.md)）。

分档逻辑必须看代码而不是背「2 的幂」这个印象（`ArrayByteBufferPool.java:67-70, 150-170`）：

```java
static final int DEFAULT_FACTOR = 4096;
static final int DEFAULT_MAX_CAPACITY_BY_FACTOR = 16;
...
private static IntUnaryOperator defaultBucketIndexFor(int minCapacity, int factor)
{
    int minCapIdx = (minCapacity - 1) / factor;
    return capacity -> ((capacity - 1) / factor) - minCapIdx;
}
```

- **线性分档，不是指数分档**：桶容量是 `factor` 的整数倍（4096、8192、12288 …），类注释里用 `factor = 1024` 举例说明 1024/2048/3072/4096/5120。
- 默认最大容量 `DEFAULT_MAX_CAPACITY_BY_FACTOR * factor` = 65536；超过桶档位的请求走 `NoBucketData` 路径（`_noBucketDirectAcquires` / `_noBucketIndirectAcquires` 记账）。
- 堆内与直接内存各一个 `RetainedBucket[]`（`_indirect` / `_direct`），`Type` 与 `ByteBufferPool.Sized` 的 `sizeHint` 决定是否直接内存。
- `maxHeapMemory`/`maxDirectMemory` 传 0 表示启发式：`Runtime.getRuntime().maxMemory() / 8`；传 -1 表示不限。
- `maxBucketSize` 默认 `Integer.MAX_VALUE`，即每档不限量，靠内存水位与 evictor（`_evictor` 用 `AtomicBoolean` 保证同一时刻只有一个淘汰者）收敛。

## Sink and Callback chain

写侧接口只有一个抽象方法（`Content.java:936`）：

```java
void write(boolean last, ByteBuffer byteBuffer, Callback callback);
```

`last` 是唯一的「结束」信号，`Callback` 是唯一的完成通知。javadoc 同样承诺**安全可重入**：`write` 与 `Callback` 互相递归时不会栈溢出——这条保证是让 `Content.copy()` / `HttpConnection.SendCallback` 这类循环能写成 `iterate()` 的前提。

静态阻塞版本 `Content.write(Sink, boolean, ByteBuffer)`（`:901-905`）就是 `Blocker.Callback` 三行包装：

```java
static void write(Sink sink, boolean last, ByteBuffer byteBuffer) throws IOException
{
    try (Blocker.Callback callback = Blocker.callback())
    {
        sink.write(last, byteBuffer, callback);
        callback.block();
    }
}
```

两个 `copy` 重载（`:81-84`、`:106-109`）都委托给 `ContentCopier`，后者是 `IteratingCallback`，可选的 `Chunk.Processor` 参数允许在每一跳上改写或拦截 chunk——`ContentSourceTransformer` 就是靠这个位置插进去的。

## Blocker as the synchronous bridge

`jetty-util-12.1.14/org/eclipse/jetty/util/Blocker.java:75` 是一个命名空间类，javadoc（`:33-63`）给出四种用法：非共享 `Runnable`、共享 `SharedRunnable`、非共享 `Callback`、共享 `Callback`，全部是 try-with-resources：

```java
try(Blocker.Callback callback = Blocker.callback())
{
    someMethod(callback);
    callback.block();
}
```

实现就是 `CountDownLatch(1)`（`:95` 起，`run()`/`succeeded()` 里 `countDown()`）：`block()` 无超时 await，`block(time, unit)` 超时抛 `TimeoutException`，异常统一走 `IO.rethrow`。这些对象都 `implements AutoCloseable` 并返回 `Invocable.InvocationType.NON_BLOCKING`（告诉上层调度器「我作为回调不占坑」），**close 时若 latch 未完成会打 WARN**——这正是「异步没回来就退出作用域」的泄漏信号。

代价要算清楚：`block()` 期间**当前线程被完整占用**。在 servlet 线程上 `block()`，等于一个容器线程既不跑 selector 也不跑别的请求；这就是 `BlockingContentProducer` 用 semaphore 而不是直接 `block()` 的原因之一（见下节）。共享形态 `Blocker.Shared` 用互斥保证同一实例不被并发复用，代价是共享 blocker 不能被两个线程同时 `block()`。线程池侧的取舍在 [Jetty/Threading.md](/docs/CS/Framework/Jetty/Threading.md)。

## Quick reference of io/content implementations

`jetty-io-12.1.14/org/eclipse/jetty/io/content/` 恰好 13 个文件，全是适配器；真正的引擎侧实现藏在 `io/internal/`（见下表最后一行）。

| 实现 | 方向 | 用途 |
| :--- | :--- | :--- |
| `AsyncContent` | — | 把 source/sink 的异步推进封装成可复用组件 |
| `BufferedContentSink` | Sink | 聚合小块写出，减少 write 次数 |
| `ByteBufferContentSource` | Source | `from(ByteBuffer...)` 的 backing，零或数个 buffer |
| `ChunksContentSource` | Source | 预置一串 `Chunk` 依次吐出 |
| `ContentSinkOutputStream` | Sink→`OutputStream` | 让 `Sink` 看起来像阻塞流（servlet `OutputStream` 侧） |
| `ContentSinkSubscriber` | Sink←`Flow.Subscriber` | `Content.sink(...)` 工厂返回值（`Content.java:890`） |
| `ContentSourceCompletableFuture` | Source→`CompletableFuture` | `FormFields.java:43` 即 `extends ContentSourceCompletableFuture<Fields>` |
| `ContentSourceInputStream` | Source→`InputStream` | servlet 非 async 读的外壳 |
| `ContentSourcePublisher` | Source→`Flow.Publisher<Chunk>` | 见下方 Reactive Streams 说明 |
| `ContentSourceTransformer` | Source→Source | 挂接 `Chunk.Processor` 做改写 |
| `InputStreamContentSource` | `InputStream`→Source | 把阻塞流伪装成 read/demand |
| `OutputStreamContentSource` | `OutputStream`→Source | 同上，供测试与桥接 |
| `PathContentSource` | Source | 文件内容，委托 `ByteChannelContentSource.PathContentSource` |

`PathContentSource` 值得单独纠正一个流传的说法：**它不做 sendfile 零拷贝**。它只是薄壳（`PathContentSource.java:24-90`），构造时 `Content.Source.from(sizedBufferPool, path)`，而后者是 `Content.java:265-268` → `new ByteChannelContentSource.PathContentSource(...)`；真正读文件的 `jetty-io-12.1.14/org/eclipse/jetty/io/internal/ByteChannelContentSource.java:40`（嵌套类 `:281`，`open()` `:307`）走 `_byteChannel.read(byteBuffer)`（`:189`、`:205`）把内容读进池化 buffer。全镜像里 `transferTo(` 在 `jetty-*` 与 `jetty-http*` 下**零命中**（只有 `xnio-api` 有），也没有 `FileChannel.map`。所以 Jetty 12 的静态资源路径是「一次内核到用户态的拷贝 + 池复用」，`offset`/`length` 与 `rewind()` 靠 seekable channel 实现，`getLength()` 直接透传给 `Content.Source`。想要真零拷贝得走连接器/OS 层，不是这一层。

`ContentSourcePublisher` 与 Reactive Streams 的衔接是核实过的：`public class ContentSourcePublisher implements Flow.Publisher<Content.Chunk>`（`:38`），用 JDK 的 `java.util.concurrent.Flow` 而非 Reactor；`Flow.Subscription#request(long)` 驱动从 `Content.Source` 读取并 `onNext(chunk)`（`:118`、`:201`）。类内注释按 spec 条款号自我约束——`rule 1.3` 要求 `onSubscribe`/`onNext`/`onError`/`onComplete` 串行发（`:150-151`），`rule 3.13` 要求 `cancel()` 最终让 publisher 停止（`:161`），非正数 request 报 `rule 3.9`（`:242`），违反 `rule 2.13` 的 subscriber 只记 trace 日志。

## HttpParser and the deleted ParseResult

⚠️ **`ParseResult` 与 `ParseState` 在 Jetty 12 已不存在**。在 `jetty-http-12.1.14/` 与 `jetty-io-12.1.14/` 全镜像 grep `ParseResult|ParseState` 零命中，但大量 Jetty 9/10 时代的教程仍在教 `ParseResult fill(_buffer)` 加 `switch (result)` 的写法——照抄必然编译不过。

替代物是 parser 内部的一个 `State` 枚举（`HttpParser.java:201`）加对外唯一的推进方法 `public boolean parseNext(ByteBuffer)`（`:1699`）：

```java
public enum State
{
    START,
    METHOD,
    RESPONSE_VERSION,
    SPACE1,
    STATUS,
    URI,
    SPACE2,
    REQUEST_VERSION,
    REASON,
    PROXY,
    HEADER,
    CONTENT,
    EOF_CONTENT,
    CHUNKED_CONTENT,
    CHUNK_SIZE,
    CHUNK,
    CHUNK_END,
    CONTENT_END,
    TRAILER,
    END,
    CLOSE,  // The associated stream/endpoint should be closed
    CLOSED  // The associated stream/endpoint is at EOF
}
```

`CLOSE` 与 `CLOSED` 的注释区分很重要：前者是「应当关端点」（协议要求非持久、解析出错），后者是「已经 EOF」。两个 `EnumSet` 常量把它们分组（`:246-247`）：`__idleStates = {START, END, CLOSE, CLOSED}`、`__completeStates = {END, CLOSE, CLOSED}`。头字段解析另有 `FieldState`（`:221`：`FIELD`/`IN_NAME`/`VALUE`/`IN_VALUE`/`WS_AFTER_NAME`），chunk 扩展参数另有 `ChunkSizeState`（`:233`，8 个状态覆盖 `;ext=value` 的引号与空白形式）。对外的状态查询只剩 `inContentState()`、`isComplete()`、`isTerminated()`、`hasContent()`、`atEOF()`、`reset()`、`close()`。

### parseNext contract

类注释（`HttpParser.java:55-76`）把调用顺序说得很硬：

> The contract of the `HttpHandler` API is that if a call returns true then the call to `parseNext(ByteBuffer)` will return as soon as possible also with a true response. … It is the preferred calling style that handling such as calling a servlet to process a request, should be done after a true return from `parseNext(ByteBuffer)` rather than from within the scope of a call like `RequestHandler#messageComplete()`

原因是 handler 返回 `true` 是**提前中断解析**的信号：此时 parser 停在当前边界立刻返回，把控制权交回驱动循环。如果你在 `messageComplete()` 的作用域里去调 servlet，servlet 内部再触发写或再入读，就会在 parser 的调用栈里跑一整条请求生命周期——栈深不可控，且和上面 `demand` 串行化的约定冲突。正确姿势是：`parseNext` 返回 true → 出栈 → 由 `HttpConnection` 的 `FillCallback`/`IteratingCallback` 再驱动下一轮。

### Three layers of header caching

性能设计同样写在类注释（`:77-84`）里：解析「高度依赖 `Index#getBest(ByteBuffer, int, int)` 单遍同时前瞻结构（`:` 与 CRLF）与语义（哪个 header、什么 value）」。落地成三层：

1. **静态组合缓存** `HttpParser.CACHE`（`:113` 起，一个 `caseSensitive(false)` 的 `Index<HttpField>`）：收录 `Connection: close`、`Content-Length: 0`、`Transfer-Encoding: chunked`、常见 `Accept-Encoding`/`Accept-Language`/`Accept` 组合、按 `MimeTypes.Type` 生成的 Content-Type（含 `;charset=` 与 `; charset=` 两种写法），以及为**每个 `HttpHeader`** 预置的 `"<header>: "` → value 为 `"\u0000"` 占位的条目——这样即使 name:value 组合未命中，也至少能一次查出 header 名。
2. **每 parser 动态 Trie**：`FieldCache`（`:2474` 之后），对 value 不可能静态穷举的头（`Host`、`Cookie`）用「上一条已解析的 `HttpFields`」建缓存。`LEGACY` 合规模式会绕过它。
3. **`Index.getBest` 单遍前瞻**：避免「先找冒号再找 CRLF」两遍扫描。

### Dual-end reuse and three handler layers

同一份 parser 既做服务端又做客户端，靠 handler 类型分派（类注释 `:59-63`）：传 `RequestHandler` 就是服务端解析（多一个 `startRequest(method, uri, version)`，`:2441` 附近），传 `ResponseHandler` 就是客户端解析（多一个 `startResponse(version, status, reason)`，`:2453`）。基接口 `HttpParser.HttpHandler` 还提供 `badMessage(HttpException)`（`:2441`）与 `default getComplianceViolationListener()`（`:2431`），合规违例是回调而不是抛异常。

### Compliance modes

`HttpParser` 类注释（`:87-96`）列出的模式，对应 `HttpConfiguration.java:83-88` 上六个独立开关（`_httpCompliance`、`_uriCompliance`、`_redirectUriCompliance`、`_requestCookieCompliance`、`_responseCookieCompliance`、`_multiPartCompliance`）：

| 模式 | 语义 |
| :--- | :--- |
| `RFC9110` | 默认，同时满足 RFC9110 + RFC9112 |
| `RFC7230` | 旧语义（注释里也标了 default，属历史遗留措辞，实际默认取 `RFC9110`） |
| `RFC2616` | 允许折行头（wrapped headers）与 HTTP/0.9 |
| `LEGACY` | 迁就 Servlet 规范对头名精确大小写的要求，**绕过头缓存**（缓存不区分大小写），其余等同 `RFC2616` |

## HttpGenerator two enums drive one loop

`jetty-http-12.1.14/org/eclipse/jetty/http/HttpGenerator.java:40` 与 parser 对称，但它是 pull 式：调用方给 buffer，它告诉你要不要再来一次。

`State`（`:62-69`）是报文生命周期：`START` → `COMMITTED`（头已生成）→ `COMPLETING_1XX`/`COMPLETING` → `END`。`Result`（`:71-84`）是每次调用的输出指令，注释原样：

```java
public enum Result
{
    NEED_CHUNK,             // Need a small chunk buffer of CHUNK_SIZE
    NEED_INFO,              // Need the request/response metadata info
    NEED_HEADER,            // Need a buffer to build HTTP headers into
    HEADER_OVERFLOW,        // The header buffer overflowed
    NEED_CHUNK_TRAILER,     // Need a large chunk buffer for last chunk and trailers
    FLUSH,                  // The buffers previously generated should be flushed
    CONTINUE,               // Continue generating the message
    SHUTDOWN_OUT,           // Need EOF to be signaled
    DONE                    // The current phase of generation is complete
}
```

入口是 `generateRequest(...)`（`:200`）与 `generateResponse(MetaData.Response info, boolean head, ByteBuffer header, ByteBuffer chunk, ByteBuffer content, boolean last)`（`:368`）。常量：`DEFAULT_CHUNK_MAX_LENGTH = 1024 * 1024 * 1024`（`:45`，单个 transfer-encoding chunk 的默认上限）、`CHUNK_SIZE = 12`（`:48`，chunk 长度行本身只需 12 字节的 buffer）、`CONTINUE_100_INFO`（`:52`，一个 `100` + HTTP/1.1 + 空头字段的 `MetaData.Response` 常量）、`__STRICT`（`:50`，系统属性 `org.eclipse.jetty.http.HttpGenerator.STRICT`）：严格模式原样输出方法名与头名的大小写，否则用大小写不敏感的快速查表、可能改写部分大小写与空白。

驱动它的是 `HttpConnection.SendCallback extends IteratingCallback`——注意这个类在 **`jetty-server-12.1.14/org/eclipse/jetty/server/internal/HttpConnection.java:740`**（Jetty 12 把 `HttpConnection` 挪进了 server 的 `internal` 包，不在 `jetty-http`），在 `:857` 拿 `generateResponse` 的返回值做 switch：

- `NEED_INFO` → 直接 `throw new EofException("request lifecycle violation")`（`:869`），因为响应没有元数据可生成说明请求生命周期已被破坏。
- `NEED_HEADER` → 先 `_generator.setMaxHeaderBytes(maxHeaderBytes)` 再按档 `acquire` 一个 header buffer（`:873-880`）；`maxHeaderBytes` 优先取 `maxResponseHeadersSize`，否则退回 `responseHeadersSize`。
- `HEADER_OVERFLOW` → **自动扩容一次**：若配置了更大的 `maxResponseHeadersSize`，释放旧 buffer、按新尺寸重新 acquire 并更新 `responseHeadersSize`（`:882-888`），下一轮重试；扩无可扩才报错。这就是「大 cookie / 多 `Vary` 头偶发 500」的现场。
- `NEED_CHUNK` / `NEED_CHUNK_TRAILER` → 申请 12 字节的 chunk 头尾 buffer，或为最后一个 chunk 与 trailer 申请大 buffer。
- `FLUSH` → 把已生成的 buffer 交给端点写出，写完 `continue` 回循环。
- `CONTINUE` → 不返回、继续迭代；`DONE` → 结束本轮并把 `Callback` 交给上层。
- `SHUTDOWN_OUT` → 连接器关闭时补一个 EOF 信号（配合 `:966` 的 `isShutdown() && isEnd() && isPersistent()`）。

100-continue 走 `State.COMPLETING_1XX`：先 `CONTINUE_100_INFO` 生成一条临时响应，`isPersistent` 不因它改变。

## MetaData separated from content

`jetty-http-12.1.14/org/eclipse/jetty/http/MetaData.java:28` 是 `implements Iterable<HttpField>` 的抽象类，`MetaData.Request`（`:132`）与 `MetaData.Response`（`:283`）分别承载方法/URI/版本与状态/原因。它**只描述报文，不含 body**。传递入口是 `HttpStream.send(request, response, last, content, callback)`：一个方法同时给出元数据、是否最后一帧、内容 buffer 与完成回调。这正是 `Content.Sink.write(boolean, ByteBuffer, Callback)` 拿不到 `MetaData` 的原因——头与体在不同抽象层，HTTP/2 可以把 `info` 编成 HEADERS 帧、把 content 编成 DATA 帧，而 HTTP/1 用 `HttpGenerator` 拼在一起。见 [Jetty/Connector.md](/docs/CS/Framework/Jetty/Connector.md)。

## ee10 read strategies and write path

servlet 的 `ServletInputStream` 有三种语义（`isReady()`/`setReadListener()`/阻塞 `read()`），Jetty 用 `ContentProducer` 接口的三个实现来映射（`jetty-ee10-servlet-12.1.14/org/eclipse/jetty/ee10/servlet/ContentProducer.java:21`，核心方法 `Chunk nextChunk()` `:97`）：

`AsyncContentProducer`（`:35`）**永不阻塞**：`isReady()` 里若没有 chunk，就 `state.onReadUnready()` 然后 `_servletChannel.getRequest().demand(_demandTask)`（`:258`）并返回 `false`——把「等数据」变成「注册一次 demand」，线程立刻交还。

`BlockingContentProducer`（`:24`）在 async producer 外面套 semaphore，`nextChunk()`（`:96-126`）的循环结构解释了为什么不能直接 `block()`：

```java
Content.Chunk chunk = _asyncContentProducer.nextChunk();
if (chunk != null)
    return chunk;

// IFF isReady() returns false then Request.demand() has been called,
// thus we know that eventually a call to onContentProducible will come.
if (_asyncContentProducer.isReady())
    continue;

try
{
    _semaphore.acquire();
}
catch (InterruptedException e)
{
    return Content.Chunk.from(e);
}
```

关键是「先 demand 再等」：因为 `isReady()` 为 false 时 demand 已经注册，`onContentProducible` 一定会 release 这个 permit，不会丢唤醒。`consumeAvailable()`（`:88-93`）在 `isReady()` 为真时先把已有 chunk 吃掉、随后 `release()` 平衡 permit。被中断不是抛出去，而是**转成 failure chunk**（`Content.Chunk.from(e)`）——异常沿着 Content 语义而非线程异常传播。

写侧终点在 `HttpOutput.java:238-255`：阻塞版 `channelWrite(ByteBuffer, boolean complete)` 用 `_writeBlocker.callback()` 拿一个共享 `Blocker.Callback`，调用异步版后 `block()`；异步版只是 `_servletChannel.getResponse().write(last, content, callback)`（`:249`）。`_writeBlocker` 是 `Blocker.Shared` 形态，因此同一时刻只允许一个线程在 `HttpOutput` 上阻塞写——这与 servlet 容器「输出流非线程安全」的约定一致。servlet 生命周期细节见 [Java/JDK/Servlet.md](/docs/CS/Java/JDK/Servlet.md)。

## Comparison with Tomcat read buffer

Tomcat 的对应层是 `InternalInputBuffer` + `CoyoteInputStream`：socket 字节先经 `Http11InputBuffer` 解析进 request 的 `ByteChunk`，body 由 `doRead` 系列按 Content-Length/chunked 逐块搬运，**默认以阻塞读为主**，非阻塞靠 `AsyncStateMachine` 与 `Poller` 切换（详见 [Tomcat/Connector.md](/docs/CS/Framework/Jetty/Connector.md)）。差异集中在三点：Jetty 的读单元是带引用计数的 `Chunk` 而不是共享 `ByteChunk`；Jetty 的「等数据」原语是 `demand(Runnable)` 而非状态机回调，因此 spurious 唤醒是合法行为；Jetty 的阻塞 servlet 读不是「另一条代码路径」，而是同一异步路径上的 semaphore 包装，Tomcat 则是两套（blocking / non-blocking）实现。Netty 侧的对照（`ByteBuf` + `ChannelHandlerContext.read()` 显式背压）见 [Netty/Netty.md](/docs/CS/Framework/Netty/Netty.md)。

## Pitfalls

1. **找 `ContentSource` 类**。它不存在；顶层只有 `Content.Source` / `Content.Sink` / `Content.Chunk`，带后缀的名字只在 `io/content/` 的适配器里。
2. **照旧文章写 `ParseResult` / `ParseState`**。Jetty 12 已删，只剩 `parseNext(ByteBuffer)` + 内部 `State`。
3. **把 `read()` 返回 `null` 当成 EOF**。EOF 只有 `chunk.isLast()`；`null` 只是「现在没有」，必须 `demand` 后返回。
4. **不 release chunk**。`Chunk` 是池化 buffer，漏 release 就是 `ArrayByteBufferPool` 的内存水位上涨与 leak 记录，而且 last chunk 幂等可重读会掩盖问题。
5. **重复 `demand`**。已有 pending demand 时再调抛 `IllegalStateException`；惯用法是 `demand(...)` 后紧跟 `return`。
6. **在 demand 回调里阻塞等未来回调**。回调被串行化，自己等自己就是死锁。
7. **在 `messageComplete()` 里调 servlet**。要在 `parseNext` 返回 true 之后处理，否则整条请求跑在 parser 栈上。
8. **`Blocker` 当成非阻塞用**。它 100% 占住当前线程；`try-with-resources` 退出时未完成还会打 WARN，那条 WARN 通常意味着异步路径丢了回调。
9. **误以为 `PathContentSource` 是零拷贝**。它走 `ByteChannelContentSource` 的 `read` 到池化 buffer，本镜像内没有 `transferTo`/`map`。
10. **`HEADER_OVERFLOW` 只当成「头太大直接报错」**。它有一次自动扩容（`responseHeadersSize` → `maxResponseHeadersSize`），要调的是这两个配置而不是 `requestHeaderSize` 一个值。
11. **`LEGACY` 合规模式当免费开关**。它绕过头缓存，换来 servlet 规范的头名精确大小写，代价是解析性能。
12. **凭印象给 `ArrayByteBufferPool` 参数**。默认是 `factor = 4096` 的线性档位、上限 16 档，堆/直接内存启发式是 `maxMemory()/8`，不是 2 的幂分桶。

## Links

- [Jetty](/docs/CS/Framework/Jetty/Jetty.md)
- [Jetty 线程模型](/docs/CS/Framework/Jetty/Threading.md)
- [Jetty Connector](/docs/CS/Framework/Jetty/Connector.md)
- [Jetty EE 层](/docs/CS/Framework/Jetty/EeLayer.md)
- [Jetty HTTP/2](/docs/CS/Framework/Jetty/Http2.md)
- [Tomcat Connector](/docs/CS/Framework/Tomcat/Connector.md)

## References

- [RFC 9110: HTTP Semantics](https://datatracker.ietf.org/doc/html/rfc9110)
- [RFC 9112: HTTP/1.1](https://datatracker.ietf.org/doc/html/rfc9112)
- [Jetty 12 Documentation](https://jetty.org/docs/)
- [java.util.concurrent.Flow (Java SE 17 API)](https://docs.oracle.com/en/java/javase/17/docs/api/java.base/java/util/concurrent/Flow.html)
