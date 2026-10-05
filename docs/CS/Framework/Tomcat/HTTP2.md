# HTTP/2

## Introduction

Tomcat 11.0.26 的 HTTP/2 实现全部住在 `tomcat-coyote` 的 **`org.apache.coyote.http2`** 包里（注意：不是 `org.apache.tomcat.http2`，旧资料常写错）。它不是一个独立的 connector，也不是一个 `ProtocolHandler`，而是一个**挂在 HTTP/1.1 `ProtocolHandler` 下面的协议插件** `Http2Protocol implements UpgradeProtocol`（`tomcat-coyote-11.0.26/org/apache/coyote/http2/Http2Protocol.java:46`）。

本篇覆盖：这个插件为什么这样设计、怎么开、连接与流的对象模型、双层并发上限、HPACK、流控唤醒、流状态机、overhead 防护、服务端 push 移除的影响面，以及几个高频坑。源码引用一律标 `相对 /tmp/src/tree/ 路径:行号`。

`UpgradeToken` / `UpgradeProcessor` 这条 HTTP/1.1 → 升级处理器的衔接链路在 [Connector](/docs/CS/Framework/Tomcat/Connector.md) 里已经讲过，本篇只写 HTTP/2 特有的部分。

## Why UpgradeProtocol instead of a separate connector

这是 Tomcat HTTP/2 最反直觉的设计：**一个 connector 只跑一个 `ProtocolHandler`（HTTP/1.1），HTTP/2 是这个 handler 在运行时切换出来的**。原因是 HTTP/2 的落地方式有两种，而这两种都不需要新端口：

1. **TLS + ALPN**：握手期在 `ConnectionHandler` 里按 ALPN 标识 `h2` 选中 HTTP/2。`Http2Protocol` 提供标识：

   ```java
   private static final String HTTP_UPGRADE_NAME = "h2c";
   private static final String ALPN_NAME = "h2";
   private static final byte[] ALPN_IDENTIFIER = ALPN_NAME.getBytes(StandardCharsets.UTF_8);
   ```

   （`http2/Http2Protocol.java:81-83`，`getAlpnIdentifier()` / `getAlpnName()` 在 `:150-158`）

2. **明文 h2c + Upgrade 头**：先按 HTTP/1.1 收一个带 `Upgrade: h2c` 的请求，再切协议。

`UpgradeProtocol` 的查找机制就是为这两条路准备的：`AbstractHttp11Protocol` 持有若干 `UpgradeProtocol` 实例，用 `getHttpUpgradeName(isSSLEnabled)` 建 Upgrade-token 表、用 `getAlpnIdentifier()` 建 ALPN 表，命中后调用 `getInternalUpgradeHandler(...)` 拿到 `InternalHttpUpgradeHandler`。**关键细节：h2c 的 Upgrade 路径只在非 TLS 连接器上注册**：

```java
@Override
public String getHttpUpgradeName(boolean isSSLEnabled) {
    if (isSSLEnabled) {
        return null;
    } else {
        return HTTP_UPGRADE_NAME;
    }
}
```

（`http2/Http2Protocol.java:141-148`）

也就是说 TLS 连接器上不会出现 `h2c` 这个 upgrade token，只能靠 ALPN 协商 `h2`。ALPN 本身不是 Coyote 实现的，它依赖底层 TLS 实现是否暴露 ALPN（OpenSSL / Java 9+ `SSLEngine`），见 [TLS](/docs/CS/Framework/Tomcat/TLS.md)。

这样设计换来的收益是：连接池、`maxConnections`、`LimitLatch`、SSL 卸载、Apr/JSSE 差异、读超时等一整套 connector 级设施不用重写第二遍；代价是 HTTP/2 的调优参数**散落在两个地方**——`Http2Protocol` 自己的字段和父级 `AbstractHttp11Protocol` 的字段，且后者通过引用反向拿：

```java
public void setHttp11Protocol(AbstractHttp11Protocol<?> http11Protocol) {
    this.http11Protocol = http11Protocol;
    recycledRequestsAndResponses.setLimit(http11Protocol.getMaxConnections());
```

（`http2/Http2Protocol.java:617-620`；`getHttp11Protocol()` 在 `:612-614`，`getContinueResponseTimingInternal()` 直接委托给父级 `:602-604`）

## Enabling in server.xml

在已有的 HTTP/1.1 connector 里加一个子元素，`className` 必填（源码里的全限定名是 `org.apache.coyote.http2.Http2Protocol`，由 `package org.apache.coyote.http2;` + 类名确定）：

```xml
<Connector port="8443" protocol="org.apache.coyote.http11.Http11NioProtocol"
           SSLEnabled="true" ...>
    <UpgradeProtocol className="org.apache.coyote.http2.Http2Protocol"
                     maxConcurrentStreams="100"
                     maxConcurrentStreamExecution="20"
                     streamReadTimeout="20000" />
    <Host name="localhost" ... />
</Connector>
```

`<UpgradeProtocol>` 元素本身由 connector 解析，配置项则逐条落到 `Http2Protocol` 的 setter 上。可调项与默认值（全部来自 `http2/Http2Protocol.java`）：

| 属性 | 默认 | 位置 |
| :--- | :--- | :--- |
| `readTimeout` / `writeTimeout` | 5000 ms（连接级） | `:59-60, 87-88` |
| `streamReadTimeout` / `streamWriteTimeout` | 20000 ms（流级） | `:62-63, 91-92` |
| `keepAliveTimeout` | 20000 ms | `:61, 89` |
| `maxConcurrentStreams` | 100 | `:65, 94` |
| `maxConcurrentStreamExecution` | 20 | `:68, 95` |
| `initialWindowSize` | `ConnectionSettingsBase.DEFAULT_INITIAL_WINDOW_SIZE` | `:96-98` |
| `maxHeaderCount` / `maxTrailerCount` | 100 / 100 | `:100-101` |
| `overheadCountFactor` | 10 | `:70, 102` |
| `overheadResetFactor` | 50 | `:72, 103` |
| `overheadContinuationThreshold` / `overheadDataThreshold` / `overheadWindowUpdateThreshold` | 1024 字节 | `:77-79, 104-106` |
| `initiatePingDisabled` | false | `:108` |
| `useSendfile` | true | `:109` |
| `allowSchemeMismatch` | false | `:110` |
| `discardRequestsAndResponses` | false | `:125` |
| `drainTimeout` | 0（未设置时用最近 RTT） | `:128-139` |

## Two handlers and two negotiation paths

`Http2Protocol` 只有一个决策点决定用哪个 handler，判据是**底层 socket 是否有异步 IO**，而不是明文/密文：

```java
@Override
public InternalHttpUpgradeHandler getInternalUpgradeHandler(SocketWrapperBase<?> socketWrapper, Adapter adapter,
        Request coyoteRequest) {
    return socketWrapper.hasAsyncIO() ? new Http2AsyncUpgradeHandler(this, adapter, coyoteRequest, socketWrapper) :
            new Http2UpgradeHandler(this, adapter, coyoteRequest, socketWrapper);
}
```

（`http2/Http2Protocol.java:167-172`；`Http2AsyncUpgradeHandler extends Http2UpgradeHandler`，见 `http2/Http2AsyncUpgradeHandler.java:46`）

两条协商路径的差异体现在**入口参数**上，而不是 handler 类上：

- **ALPN / prior-knowledge**：根本没有 HTTP/1.1 请求对象，`getProcessor()` 直接造一个 `coyoteRequest == null` 的 `UpgradeProcessor`：

  ```java
  @Override
  public Processor getProcessor(SocketWrapperBase<?> socketWrapper, Adapter adapter) {
      return new UpgradeProcessorInternal(socketWrapper, new UpgradeToken(
              getInternalUpgradeHandler(socketWrapper, adapter, null), null, null, getUpgradeProtocolName()), null);
  }
  ```

  （`http2/Http2Protocol.java:160-164`）随后由 parser 校验 24 字节连接前缀：`parser.readConnectionPreface(webConnection, stream)`（`http2/Http2UpgradeHandler.java:318`）。

- **h2c Upgrade**：必须先让 HTTP/1.1 processor 判断这个请求是否真的能升级，判据是 `accept(Request)`——**有且仅有一个** `HTTP2-Settings` 头，且某个 `Connection` 头里含 `HTTP2-Settings` token（`http2/Http2Protocol.java:175-194`）。任一条不满足就留在 HTTP/1.1。

`getUpgradeProtocolName()` 又按连接器是否 TLS 返回 `h2` 或 `h2c`（`:639-645`），这个名字会进入 JMX ObjectName，所以**同一个 connector 的 HTTP/1.1 与 HTTP/2 统计是两个 MBean**。

## Connection and stream object model

层次是「一个连接一个 handler，一个流一个 Stream + 一个 StreamProcessor」：

- `Http2Protocol`：**每个 connector 一个实例**，是配置载体与回收池的持有者，不持连接状态。
- `Http2UpgradeHandler extends AbstractStream implements InternalHttpUpgradeHandler, Input, Output`（`http2/Http2UpgradeHandler.java:72`）：**每条连接一个**，自己伪装成流 ID 0 的控制流（`AbstractStream` 就是为流 0 抽出来的基类），负责 parser、连接窗口、SETTINGS、PING、流表。
- `Stream`：真正的请求流。它的流控管理器是内嵌字段 `private final WindowAllocationManager allocationManager = new WindowAllocationManager(this);`（`http2/Stream.java:90`）。
- `StreamProcessor extends AbstractProcessor implements NonPipeliningProcessor`（`http2/StreamProcessor.java:56`）：每个流一个，`service()` 里 `adapter.service(request, response)`（`:458-461`）。HTTP/2 就是这样把复用出来的流**塞回 Servlet 引擎**的——对 Valve 层来说，一个流和一个 HTTP/1.1 请求毫无区别（见 [Valve](/docs/CS/Framework/Tomcat/Valve.md)）。
- `RecycledStream extends AbstractNonZeroStream`（`http2/RecycledStream.java:25`）：流关闭后**不会立刻消失**，而是换成一个只保留必要信息的替身：`connectionId`、`identifier`、`StreamStateMachine state`、`remainingFlowControlWindow`（`:27-30`）。原因是已关闭的流仍可能收到 `WINDOW_UPDATE`/`PRIORITY`，必须知道它原来的状态和窗口余量才能判定是忽略还是连接错误；替换逻辑见 `http2/Http2UpgradeHandler.java:1976` 的注释「Only replace the Stream once. No point replacing one RecycledStream instance with another.」。

替身对象靠**定期清理**回收：`newStreamsSinceLastPrune`（`http2/Http2UpgradeHandler.java:173`）每建 10 个流做一次 prune（`:1447-1453` 的 `< 9` 自增 / 归零逻辑）。这解释了长连接上为什么内存不会随流数线性增长，但也解释了为什么 prune 前那一刻 RSS 会台阶式上涨。

还有一层容易忽略的回收：**Request/Response 对象池**。HTTP/1.1 每条连接一个 `Request`，而 HTTP/2 每个流需要一个，于是 `Http2Protocol` 自己维护一个跨连接的栈：

```java
Request popRequestAndResponse() {
    Request requestAndResponse = null;
    if (!discardRequestsAndResponses) {
        requestAndResponse = recycledRequestsAndResponses.pop();
    }
    if (requestAndResponse == null) {
        requestAndResponse = new Request();
        Response response = new Response();
        requestAndResponse.setResponse(response);
    }
    return requestAndResponse;
}
```

（`http2/Http2Protocol.java:698-709`；入池在 `:712-716`；栈上限设为 `maxConnections` 见 `:620`）

`discardRequestsAndResponses` 的注释直接给了实测数据：简单 Spring Boot JSON 响应场景下，true ≈ 108k req/s，false ≈ 124k req/s（`:116-125`）。响应体越大、处理越慢，这个开关的影响越小。

## Two-layer concurrency control

Tomcat 对「并发」开了两个互相独立的闸，这是调优时最容易配错的一组：

| 层 | 字段 | 默认 | 语义 |
| :--- | :--- | :--- | :--- |
| 协议层 | `maxConcurrentStreams` | 100（`Http2Protocol.java:65, 94`，注释写明「spec recommends a minimum default of 100」） | 通过 SETTINGS 广告给客户端，限制**对端能开多少流** |
| 执行层 | `maxConcurrentStreamExecution` | 20（`:68, 95`） | 限制本端同时**在容器线程上执行**的流数 |

必须分两层，是因为这两个数字衡量的东西不同：`maxConcurrentStreams` 保护的是**客户端能占用的连接资源**（流表、每流的窗口与 HPACK 上下文都在服务端内存里），它管不住 CPU；而一条连接上开着 100 个流完全可能是 99 个在等 I/O、只有 1 个在算——如果让 100 个流全部涌向容器线程，几条连接就能吃光 `maxThreads`。执行层的实现是排队而不是拒绝（`http2/Http2UpgradeHandler.java:392-404`）：

```java
void processStreamOnContainerThread(StreamProcessor streamProcessor, SocketEvent event) {
    StreamRunnable streamRunnable = new StreamRunnable(streamProcessor, event);
    if (streamConcurrency == null) {
        socketWrapper.execute(streamRunnable);
    } else {
        if (getStreamConcurrency() < protocol.getMaxConcurrentStreamExecution()) {
            increaseStreamConcurrency();
            socketWrapper.execute(streamRunnable);
        } else {
            queuedRunnable.offer(streamRunnable);
        }
    }
}
```

超出的流进 `queuedRunnable` 等待，而不是被 RST 掉。注意 `streamConcurrency == null` 这条分支——执行层门控是**可选启用**的，未启用时每个流直接 `socketWrapper.execute(...)`。

入口在 `processStreamOnContainerThread(Stream stream)`（`:373-377`）：先 `new StreamProcessor(this, stream, adapter, socketWrapper)`，再走上面的门控。

## HPACK

`Hpack.java:24-29` 定义 `final class Hpack`，`DEFAULT_TABLE_SIZE = 4096`——这就是 SETTINGS 里广告出去的表大小：`static final int DEFAULT_HEADER_TABLE_SIZE = Hpack.DEFAULT_TABLE_SIZE;`（`http2/ConnectionSettingsBase.java:41`）。

`ConnectionSettingsBase` 是本端/对端设置的公共基类，六个默认值一次性列全（`:57-63, 48`）：`HEADER_TABLE_SIZE`=4096、`MAX_CONCURRENT_STREAMS`=`UNLIMITED`（注意这是**基类**默认，`Http2Protocol` 层把它压到 100）、`INITIAL_WINDOW_SIZE`=`(1 << 16) - 1`（65535）、`MAX_FRAME_SIZE`=`MIN_MAX_FRAME_SIZE`、`MAX_HEADER_LIST_SIZE`=`1 << 15`、`NO_RFC7540_PRIORITIES`=1。最后这个值就是 RFC 9218 的开关：Tomcat 默认告诉对端「不要再用 RFC 7540 的那套优先级」。

`ConnectionSettingsLocal extends ConnectionSettingsBase<IllegalArgumentException>`（`http2/ConnectionSettingsLocal.java:30`）维护「当前值 + 待发值」两份，靠 `sendInProgress`（`:34`）避免上一次还没发出去就改；类注释明确写了 **setter 不做合法性校验**（`:26-29`），校验在别处，所以直接调 setter 配一个越界值不会被立刻拒绝。

编码端 `HpackEncoder`（`http2/HpackEncoder.java:37`）的动态表是两个普通集合：`Deque<TableEntry> evictionQueue = new ArrayDeque<>()` + `Map<String,List<TableEntry>> dynamicTable = new HashMap<>()`（`:78-79`，后者还留着「use a custom data structure」的 TODO）。**这两个字段都不是并发容器，整个类里也搜不到 `synchronized`**——线程安全完全靠调用方：一条连接的 HEADERS 编码由该连接的 handler 串行驱动，所以 encoder 实例绝不能跨连接共享，这是它不需要并发容器的根本原因（与 `Http2UpgradeHandler` 用连接级 `AbstractStream` 承载所有帧写出是一致的）。

解码端 `HpackDecoder` 独立跟踪自己的表预算，`resizeIfRequired()` 在解码路径上被调用（`http2/HpackDecoder.java:324`，方法定义 `:348`）。头部体积限制走的是 `maxHeaderSize`（默认 `Constants.DEFAULT_MAX_HEADER_SIZE` = 8 KiB，`http2/Constants.java:54`），并且有**两级阈值**：`headerSize + unreadSize > maxHeaderSize` 判超限，`> 2 * maxHeaderSize` 用于提前放弃读取（`http2/HpackDecoder.java:465-477`）。相关的还有 `DEFAULT_HEADER_READ_BUFFER_SIZE` = 1024、`DEFAULT_HEADERS_FRAME_SIZE` = 1024、`DEFAULT_HEADERS_ACK_FRAME_SIZE` = 64（`Constants.java:28-40`），以及 `DEFAULT_MAX_COOKIE_COUNT` = 200（`:46`）。

Huffman 编解码在 `HPackHuffman`（注意大小写是 `HPack`，不是 `Hpack`）：`decode(ByteBuffer, int, StringBuilder, boolean isFieldName)` 与 `encode(ByteBuffer, String, boolean forceLowercase)`（`http2/HPackHuffman.java:394, 410, 480, 498`）。`forceLowercase` 参数对应 HPACK 强制 header name 小写的要求。

## Flow control and WindowAllocationManager

连接级 + 流级两个窗口，所以等待也有两种。`WindowAllocationManager` 的全部状态就是一个 `int waitingFor ∈ {NONE, STREAM, CONNECTION}`（`http2/WindowAllocationManager.java:53-59`）。**为什么要把「在等什么」显式记下来**，类注释讲得很清楚：流可能在等连接窗口，而此时到来的是一个流窗口分配；如果照单通知，异步处理会被无谓 dispatch 一次（`:30-42`）。所以通知前做位与判断：

```java
if ((notifyTarget & waitingFor) > NONE) {
    waitingFor = NONE;
    Response response = stream.getCoyoteResponse();
    if (response != null) {
        if (response.getWriteListener() == null) {
            // Blocking, so use notify to release StreamOutputBuffer
            stream.windowAllocationAvailable.signal();
        } else {
            // Non-blocking so dispatch
            response.action(ActionCode.DISPATCH_WRITE, null);
            // Need to explicitly execute dispatches on the StreamProcessor
            // as this thread is being processed by an UpgradeProcessor
            // which won't see this dispatch
            response.action(ActionCode.DISPATCH_EXECUTE, null);
        }
    }
}
```

（`http2/WindowAllocationManager.java:207-236`）

三个必须记住的点：

1. **唤醒条件是「有窗口 && 目标匹配」，不是「有 WINDOW_UPDATE」**。`waitingFor` 被重置为 `NONE` 后，后续连续的小窗口更新不会再触发通知——注释说明这是为了处理 backlog 里多个流 + 小窗口更新时「只有第一次 notify 才真正唤醒」，多余的 notify 会造成意外超时（`:208-213`）。
2. **同步与异步走完全不同的唤醒通道**：有 `WriteListener` 时不发 condition signal，而是 `DISPATCH_WRITE` + `DISPATCH_EXECUTE`；第二个 action 是必需的，因为当前线程正在跑的 `UpgradeProcessor` 看不见这个 dispatch（`:230-233` 的注释）。
3. **锁是 Stream 的**，不是 manager 的。`waitFor` / `notify` / `isWaitingFor` 全部持 `stream.windowAllocationLock`、等 `stream.windowAllocationAvailable`（`:131-240`）。类注释末尾解释了原因：旧实现给流通知和连接通知各一把锁，但「是否要等待」这个判断必须在持流锁时做，所以两种等待统一挂到 Stream 上（`:43-46`）。`Stream` 侧的对应封装在 `http2/Stream.java:237-320`（`waitForStream` / `waitForStreamNonBlocking` / `waitForConnection*` / `notifyConnection`）。

超时用 `System.nanoTime()` 重算剩余时间并循环处理虚假唤醒（`WindowAllocationManager.java:150-173`），超时值就是 `streamWriteTimeout`（默认 20000 ms）。

连接窗口的归还由 `Stream` 的 backpressure 判定驱动：只有当「流窗口 ≤ 0 或没人等流窗口」**且**「连接窗口 ≤ 0 或没人等连接窗口」**且**没有剩余数据时才认为不再需要分配（`http2/Stream.java:1189-1190`）。

`initialWindowSize` 有个源码里点名的坑：想广告一个不同于默认的值，改 `Http2Protocol.initialWindowSize`，**不要去改 `ConnectionSettingsBase.DEFAULT_INITIAL_WINDOW_SIZE`**（`http2/Http2Protocol.java:96-98` 的注释）。改的地方在 `http2/Http2UpgradeHandler.java:220`：`localSettings.set(Setting.INITIAL_WINDOW_SIZE, protocol.getInitialWindowSize(), true);`，并且连接级窗口要按增量补一次：`int increment = protocol.getInitialWindowSize() - ConnectionSettingsBase.DEFAULT_INITIAL_WINDOW_SIZE;`（`:774`）。对端回来的 SETTINGS 在 `:1849` 处按 `Setting.INITIAL_WINDOW_SIZE` 特判处理——这是唯一一个需要「改变已在途流状态」的设置。

## Stream state machine

`StreamStateMachine` 的类注释直接指向 RFC 7540 §5.1 的状态图，并声明本实现的唯一扩展是**区分「正常关闭」与「被复位关闭」**（`http2/StreamStateMachine.java:27-33`）。这个扩展体现在三个终态上：`CLOSED_RX`（收完 END_STREAM）、`CLOSED_TX`（发完）、`CLOSED_RST_RX` / `CLOSED_RST_TX`（被 RST），外加 `CLOSED_FINAL`。

推进方式是**乐观尝试 + 前态匹配**，而不是显式转移表：

```java
private void stateChange(State oldState, State newState) {
    if (state == oldState) {
        state = newState;
```

（`:100-107`）

于是一次事件可以同时是多个转移的触发点，例如 `sentEndOfStream()` 会依次尝试 `OPEN → HALF_CLOSED_LOCAL` 与 `HALF_CLOSED_REMOTE → CLOSED_TX`（`:64-67`），`receivedEndOfStream()` 尝试 `OPEN → HALF_CLOSED_REMOTE` 与 `HALF_CLOSED_LOCAL → CLOSED_RX`（`:70-73`）——这正是半关闭流两端不对称的原因。

每个状态自带一张「允许哪些帧」的白名单和违规时的错误级别（`:159-224`），违规帧由 `checkFrameType()` 分派为连接错误或流错误（`:110-124`）。举几个值得注意的组合：

| 状态 | canRead | canWrite | 可收帧 | 违规级别 |
| :--- | :--- | :--- | :--- | :--- |
| `IDLE` | 否 | 否 | `HEADERS`, `PRIORITY` | 连接错误 / `PROTOCOL_ERROR` |
| `OPEN` | 是 | 是 | `DATA`,`HEADERS`,`PRIORITY`,`RST`,`PUSH_PROMISE`,`WINDOW_UPDATE` | 连接错误 |
| `HALF_CLOSED_REMOTE` | 是 | 否 | `PRIORITY`,`RST`,`WINDOW_UPDATE` | 连接错误 |
| `CLOSED_RX` | 否 | 否 | `PRIORITY` | **流错误 / `STREAM_CLOSED`** |
| `CLOSED_RST_TX` | 否 | 否 | 全部 6 种（含 `DATA`,`HEADERS`） | 流错误 / `STREAM_CLOSED` |

`CLOSED_RST_TX` 允许几乎所有帧，是为了「已发 RST 的流要静默吞掉对端可能在途的帧」；`HALF_CLOSED_REMOTE` 的 `canReset` 为 `false`（`:186`），因此 `sendReset()` 对已处于该状态的流是**空操作**而不是异常，只有 `IDLE` 才抛 `IllegalStateException`（`:85-92`）。`isActive()` 的定义是 `canWrite || canRead`（`:226-228`），这是连接级「还有多少活跃流」计数的判据（`decrementActiveRemoteStreamCount`，`http2/Http2UpgradeHandler.java:385-389`）。

## What overhead protection guards against

HTTP/2 有一类固有弱点：**客户端可以用极小的真实代价逼服务端做大量帧处理**——HPACK 炸弹、连续 `SETTINGS`/`PING`/`PRIORITY`、疯狂 `RST_STREAM`、把 body 切成一堆 1 字节 `DATA`、刷 `WINDOW_UPDATE`。Tomcat 的对策是一个「开销信用计数器」：

```java
static final int DEFAULT_OVERHEAD_COUNT_FACTOR = 10;
static final int DEFAULT_OVERHEAD_RESET_FACTOR = 50;
// Not currently configurable. This makes the practical limit for
// overheadCountFactor to be ~20. The exact limit will vary with traffic
static final int DEFAULT_OVERHEAD_REDUCTION_FACTOR = -20;
static final int DEFAULT_OVERHEAD_CONTINUATION_THRESHOLD = 1024;
static final int DEFAULT_OVERHEAD_DATA_THRESHOLD = 1024;
static final int DEFAULT_OVERHEAD_WINDOW_UPDATE_THRESHOLD = 1024;
```

（`http2/Http2Protocol.java:69-79`，字段 `:102-106`）

计数器在 handler 构造时预扣一段信用，让新连接先有缓冲：`overheadCount = new AtomicLong(-10L * protocol.getOverheadCountFactor());`（`http2/Http2UpgradeHandler.java:205`）。之后每类帧加权累加（注释见 `:1526-1540`：`SETTINGS`/`PRIORITY`/`PING` 按 `overheadCountFactor` 计，`RST` 按 `overheadResetFactor` 计，`CONTINUATION`/`DATA`/`WINDOW_UPDATE` 则先看 payload 是否越过各自 1024 字节阈值），每完成一次真实请求按 `-20` 递减。**一旦 `overheadCount.get() > 0` 就判定超限**（`isOverheadLimitExceeded()`，`:1575-1576`），parser 在读帧循环里检查它并终止连接（`http2/Http2AsyncParser.java:287`、`http2/Http2UpgradeHandler.java:479`）。

调优含义有两条。其一，注释自己点明「reduction factor 不可配置，所以 `overheadCountFactor` 的实际上限约 20」——把它调到 100 以上，正常流量也会自杀式断连。其二，`overheadResetFactor`（50）远大于普通帧（10），因为 `RST_STREAM` 是最廉价的攻击手段；这个比值就是这套防护的倾斜方向。

## Server push is gone

这是从 Tomcat 9/10 迁移过来最容易踩空的一点：**Tomcat 11 不提供服务端 push API**。在整个 `tomcat-coyote-11.0.26` 镜像里搜 `PushBuilder` / `Http2PushBuilder` / `pushPromise`，命中的只有 Jetty 与 Undertow 的 `PushBuilderImpl`，Tomcat 侧一个都没有——`javax`/`jakarta` 的 `PushBuilder` 早已废弃，Tomcat 11 干脆把实现删掉了。

残骸只剩常量：`FrameType.PUSH_PROMISE(5, ...)`（`http2/FrameType.java:30`，帧类型号到枚举的映射在 `:96`），以及 `StreamStateMachine` 的三张白名单里仍列着 `FrameType.PUSH_PROMISE`（`http2/StreamStateMachine.java:169, 184, 203`）。

影响面：

- 旧文档里的 `request.newPushBuilder()`、`Http2PushBuilder`、以及基于 push 的性能调优段落全部作废，不要再照着配。
- 客户端若真发来 `PUSH_PROMISE`（这是客户端→服务端方向的非法帧），行为由上表的状态白名单决定，而不是由「有没有 push API」决定——想搞清楚自己遇到的具体报错，看的是 `StreamStateMachine.checkFrameType()`。
- 想替代 push 的收益，只能回到 `103 Early Hints`、preload 或 HTTP/3。

## Combining with virtual threads

HTTP/2 与线程模型的关系集中在两点。

第一，**流执行不经过 `maxThreads` 那道 `LimitLatch`**。HTTP/1.1 的每个请求由 connector 线程池领走，池子的上限与统计都在 `LimitLatch` / `ThreadPoolExecutor`（`tomcat-util-11.0.26/org/apache/tomcat/util/threads/`，见 [threads](/docs/CS/Framework/Tomcat/threads.md)）；HTTP/2 的流是在连接的 handler 里造 `StreamProcessor` 后 `socketWrapper.execute(...)` 提交的（`http2/Http2UpgradeHandler.java:373-404`），受 `maxConcurrentStreamExecution` 排队控制。**结果是：只看线程池指标看不出有多少流在排队**，要看执行层并发必须同时看 `streamConcurrency` 与 `queuedRunnable`。

第二，**JMX 统计口径变了**。`Http2Protocol` 自带一个全局分组对象 `private final RequestGroupInfo global = new RequestGroupInfo();`（`http2/Http2Protocol.java:114`），在 `setHttp11Protocol()` 里以「connector ObjectName + upgrade 名」注册（`:622-630`）。对应的类是 `org/apache/coyote/RequestGroupInfo.java` 与 `org/apache/coyote/http11/upgrade/UpgradeGroupInfo.java`——后者服务于 upgrade 连接这一分组，`global` 则是所有 HTTP/2 流的汇总单元。监控面板要把 HTTP/1.1 与 h2/h2c 两组分别取，否则会漏掉大部分并发。

与 `useVirtualThreads` 的组合因此是**两层叠加**：虚拟线程把「每个流一个线程」的成本压下去，但如果 `maxConcurrentStreamExecution` 仍是默认 20，流照样在 `queuedRunnable` 里排队，虚拟线程的收益拿不到。要放开执行层（`streamConcurrency` 未启用的分支即等价于不门控），同时把客户端侧的 `maxConcurrentStreams` 也一并评估——两个数不匹配时，瓶颈取小的那个。这里没做基准验证，属于「按源码语义推的配置方向」，上线前请自行压测。

## Pitfalls

- **`useSendfile` 在 h2 下的真实语义**。默认 `true`（`Http2Protocol.java:109`），但 sendfile 只有在「异步 IO + 显式开启」时才生效：`this.coyoteRequest.setSendfile(handler.hasAsyncIO() && handler.getProtocol().getUseSendfile());`（`http2/Stream.java:160`）。同步 handler 的 `processSendfile()` 直接 `return SendfileState.DONE;` 什么都不做（`http2/Http2UpgradeHandler.java:1226-1227`），真正的实现在 `http2/Http2AsyncUpgradeHandler.java:341-400`（含 `SendfileCompletionHandler`，失败路径返回 `SendfileState.ERROR`）。所以「用了 NIO2 + useSendfile=false」和「用了同步 NIO + useSendfile=true」在静态文件吞吐上的差别可能和你预期相反。
- **`initiatePingDisabled`**。setter 的 javadoc 写明是关掉**服务端主动发的周期性 PING 帧**（`http2/Http2Protocol.java:566-570`，getter `:580`），实现在 `Http2UpgradeHandler` 的 `protected class PingManager`（`:2055`）。关掉能省帧，但注意 graceful shutdown 的两次 GOAWAY 之间默认取**最近一次测得的 RTT** 当排空时间（`:128-139`），PING 是 RTT 的主要来源——关 PING 又同时依赖自动排空，drain 时间可能失准，此时应显式配 `drainTimeout`。
- **h2c 与前置代理**。只有非 TLS 连接器注册 `h2c` token（`:141-148`），且 `accept()` 要求恰好一个 `HTTP2-Settings` 头（`:175-194`）。现实中 Nginx/ALB 常见做法是明文 `proxy_pass http://backend`，那是 HTTP/1.1；若要 h2c 透传必须逐跳都支持 Upgrade，否则表现为「升级悄悄失败、退回 HTTP/1.1」，排查方式是抓 `Connection`/`Upgrade`/`HTTP2-Settings` 三个头。
- **scheme 不一致**。`allowSchemeMismatch`（默认 `false`，`:110, 203-216`）：`:authority` 与 `:scheme` 和实际传输层是否 TLS 冲突时，默认拒绝。经过只转发不重写伪头的代理时容易误伤。
- **`discardRequestsAndResponses`**。默认 `false`；设 `true` 会在 `popRequestAndResponse()` / `pushRequestAndResponse()` 两处都跳过池（`:698-716`），代价是每流新建 `Request`+`Response`，实测约 13% 吞吐差（`:116-125`）。它只在需要压内存驻留时才值得开。
- **流 0 与 `RecycledStream` 都属于 `AbstractStream` 谱系**，读栈信息时别把 `AbstractNonZeroStream`（如 `RecycledStream`）当成真正的用户流。

## Links

- [Tomcat](/docs/CS/Framework/Tomcat/Tomcat.md)
- [Connector](/docs/CS/Framework/Tomcat/Connector.md)
- [TLS](/docs/CS/Framework/Tomcat/TLS.md)
- [WebSocket](/docs/CS/Framework/Tomcat/WebSocket.md)
- [threads](/docs/CS/Framework/Tomcat/threads.md)
- [Version_Migration](/docs/CS/Framework/Tomcat/Version_Migration.md)

## References

- [Tomcat 11.0 - HTTP/2 Connector Configuration](https://tomcat.apache.org/tomcat-11.0-doc/config/http2.html)
- [RFC 9113: HTTP/2](https://datatracker.ietf.org/doc/html/rfc9113)
- [RFC 7541: HPACK - Header Compression for HTTP/2](https://datatracker.ietf.org/doc/html/rfc7541)
- [RFC 7540: HTTP/2 (section 5.1 Stream State Machine)](https://datatracker.ietf.org/doc/html/rfc7540)
- [RFC 9218: Extensible Prioritization Scheme for HTTP](https://datatracker.ietf.org/doc/html/rfc9218)
