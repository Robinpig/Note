# HTTP/2

## Introduction

Jetty 12 的 HTTP/2 **不是一台另一套服务器**，而是**同一个 `Connector` 上多一个 `ConnectionFactory`、每个请求多一个 `HttpStream` 实现**。整棵 `jetty-http2-server-12.1.14` 只有 10 个 Java 文件，其中 4 个在 `internal/`，加起来 1539 行；它没有自己的 handler、没有自己的 session 池、没有自己的请求对象，全部复用 `jetty-server` 的 `HttpChannel`。这是 Jetty 与 Tomcat 在 HTTP/2 上最根本的架构分歧：Tomcat 把 HTTP/2 做成 `UpgradeProtocol` 插件，代价是要在 `AbstractHttp02Processor` 里重新搭一套请求适配层（见 [Tomcat 的 HTTP/2 实现](/docs/CS/Framework/Tomcat/HTTP2.md)）；Undertow 则只有 HTTP/1.1，需要前置 nghttpx（见 [Undertow XNIO](/docs/CS/Framework/Undertow/XNIO.md)）。

Jetty 的做法可以压缩成一句话：**协议差异只允许出现在两个扩展点上** —— `ConnectionFactory.newConnection()` 与 `HttpStream`。本篇以 `jetty-http2-server-12.1.14` 源码为主线，讲清这两个扩展点如何撑起完整的 HTTP/2 服务端。

> [!WARNING]
>
> 本镜像里 `http2-common-12.1.14/` 与 `http2-server-12.1.14/` 两个目录是**空的**（sources jar 未发布）。`HTTP2Connection`、`HTTP2Session`、`HTTP2Stream`、`HTTP2Channel`、`Generator`、`ServerParser`、`BufferingFlowControlStrategy`、`HpackContext`、`Frame`、`SettingsFrame` 全部属于 `http2-common`，**本篇只写它们的名字与调用点（这些能从 import 与方法签名确认），不写它们内部的实现**；凡涉及其内部语义的推断，正文里显式标注「未在镜像中确认」。

源码位置全部相对 `/tmp/src/tree/`，格式 `路径:行号`。

## Artifact rename and dependency trap

Jetty 12.1 把 HTTP/2 的 artifact 名从 `http2-server` 改成了 **`jetty-http2-server`**。Maven Central 实测：`org.eclipse.jetty.http2:http2-server` 的 latest 停在 **11.0.26**，而 `org.eclipse.jetty.http2:jetty-http2-server` 有 **12.1.14**。

> [!IMPORTANT]
>
> 按旧坐标 `org.eclipse.jetty.http2:http2-server` 拉依赖，**Maven 会静默解析到 Jetty 11.0.26 的包**，而 Jetty 11 与 12 的 core 层（`Request`/`Response`/`HttpStream`/`Callback`）完全不兼容——报错形式是一堆 `NoSuchMethodError`，而不是版本冲突提示。同理 `http2-client` 也已改名为 `jetty-http2-client*`。

包名没变，仍是 `org.eclipse.jetty.http2.server`，模块名从 JPMS 描述符可以确认（`jetty-http2-server-12.1.14/module-info.java`）：

```java
module org.eclipse.jetty.http2.server
{
    requires transitive org.eclipse.jetty.http2.common;
    requires transitive org.eclipse.jetty.server;
    exports org.eclipse.jetty.http2.server;
}
```

注意 `exports` 只暴露 `org.eclipse.jetty.http2.server`，`internal/` 三个类不在导出包里——**应用代码不应依赖 `HTTP2ServerConnection` 与 `HttpStreamOverHTTP2`**，JPMS 下拿不到。帧 API（`org.eclipse.jetty.http2.frames`）与流控/HPACK 由 `http2.common` 传递依赖带入。

## Division of the three ConnectionFactory

| 工厂 | 协议名 | 传输 | 语义层 | 典型用途 |
| :--- | :--- | :--- | :--- | :--- |
| `HTTP2ServerConnectionFactory` | `h2` | TLS + ALPN | 完整 HTTP，接 `Handler` | 生产默认 |
| `HTTP2CServerConnectionFactory` | `h2c` | 明文 | 完整 HTTP，另实现 `ConnectionFactory.Upgrading` | 单端口 HTTP/1 + HTTP/2、服务网格 sidecar |
| `RawHTTP2ServerConnectionFactory` | `h2`/`h2c` 自选 | 由外层决定 | **只有帧**，不产生 `HttpChannel` | 自研协议、gRPC 风格实现、测试 |

三者的继承关系：`HTTP2ServerConnectionFactory extends AbstractHTTP2ServerConnectionFactory implements CipherDiscriminator`（`:52`）、`HTTP2CServerConnectionFactory extends HTTP2ServerConnectionFactory implements ConnectionFactory.Upgrading`（`:43`）、`RawHTTP2ServerConnectionFactory extends AbstractHTTP2ServerConnectionFactory`（`:32`）——`Raw` 既不实现 `CipherDiscriminator` 也不实现 `Upgrading`，因为它不接 HTTP 语义。

分叉点只有一个：`protected abstract ServerSessionListener newSessionListener(Connector, EndPoint)`（`AbstractHTTP2ServerConnectionFactory.java:350`）。`HTTP2ServerConnectionFactory` 返回内部类 `HTTPServerSessionListener`（`:74-77`、`:89`），后者把帧事件转成 `HTTP2ServerConnection.onNewStream()`；`RawHTTP2ServerConnectionFactory` 直接返回用户传进来的 listener（`:53-57`），所以永远收不到 `HttpChannel`。

> [!WARNING]
>
> `RawHTTP2ServerConnectionFactory` 的**两个构造行为不一致**：`HttpConfiguration + listener` 那会把用户 listener 包一层 `RawServerSessionListener`（`:41-45`），包装类负责把工厂侧的 `newSettings()` 与用户 settings 合并（`:74-80`）；而带 `String... protocols` 的构造（`:47-51`）**不包装**，直接用原始 listener。用三参构造时工厂默认 SETTINGS 不生效，需要自己在 `onPreface()` 里返回全部 settings。这是源码里可见的差异（对比 `:44` 与 `:50`），不是猜测。

## AbstractHTTP2ServerConnectionFactory defaults

`AbstractHTTP2ServerConnectionFactory.java:57-70` 是一张明确的默认值表，几乎每个运维问题都落在这里：

| 字段 | 默认值（行号） | 调大的后果 | 调小的后果 |
| :--- | :--- | :--- | :--- |
| `maxConcurrentStreams` | `128`（`:61`） | 单连接内存上升：`HttpChannel` 复用队列无上限，靠这个值天然兜住（`internal/HTTP2ServerConnection.java:66-68` 注释） | 客户端并发度受损，且**push 流与远端流共用同一值**（`:324-325` 同时设 `maxLocalStreams` 与 `maxRemoteStreams`） |
| `initialSessionRecvWindow` | `1024 * 1024`（`:59`） | 大文件上传吞吐↑，但缓冲驻留内存↑，易被慢客户端放大成内存攻击面 | 高 BDP 链路上 session 级窗口耗尽，整条连接所有流一起停 |
| `initialStreamRecvWindow` | `512 * 1024`（`:60`） | 单流缓冲↑ | 单流下载变慢，`maxConcurrentStreams × 此值` 才是真实内存上限 |
| `maxFrameSize` | `Frame.DEFAULT_MAX_SIZE`（`:63`，规范初值 16384） | 帧头开销摊薄，但单次 write 抖动变大 | 帧数上升，触发 `ServerParser` 的速率限制更容易 |
| `maxSettingsKeys` | `SettingsFrame.DEFAULT_MAX_KEYS`（`:64`） | 放宽 SETTINGS 键数量上限，属防护参数，一般不动 | 客户端合法的多组 SETTINGS 会被判协议错误 |
| `maxHeaderBlockFragment` | `0`（`:62`） | 拆 CONTINUATION，兼容极老的中间盒 | 0 = 不主动切分，HEADERS 可能很大 |
| `connectProtocolEnabled` | `true`（`:65`） | 打开 Extended CONNECT（RFC 8441） | 关掉即禁用 WebSocket over HTTP/2 |
| `rateControlFactory` | `new WindowRateControl.Factory(128)`（`:66`） | 放宽帧速率防护 | 正常流量被限，表现为 WINDOW_UPDATE 迟迟不来 |
| `flowControlStrategyFactory` | `() -> new BufferingFlowControlStrategy(0.5F)`（`:67`） | — | 见「流控」节 |
| `maxEncoderTableCapacity` / `maxDecoderTableCapacity` | `HpackContext.DEFAULT_MAX_TABLE_CAPACITY`（`:57-58`） | HPACK 动态表命中率↑ | 设 `0` 直接禁用动态表（`:113-118` javadoc） |
| `streamIdleTimeout` | `0`（`:68`） | — | 见「idle timeout 回落」 |

协议名白名单硬编码为 `case "h2", "h2c" -> true`、`default -> false`（`:46-53`），传 `"h3"` 会抛 `IllegalArgumentException`（`:82-83`）——**HTTP/2 工厂不可能承载 HTTP/3**，这与 `h3` 在别处的存在并不矛盾，见「h3 的现实状态」。

## Manual assembly in newConnection

`AbstractHTTP2ServerConnectionFactory.java:308-348` 是全篇信息密度最高的方法：Jetty 在这里**手写依赖图**，没有工厂类、没有 SPI。

```java
ServerSessionListener listener = newSessionListener(connector, endPoint);

Generator generator = new Generator(connector.getByteBufferPool(), isUseOutputDirectByteBuffers(), getMaxHeaderBlockFragment());
...
FlowControlStrategy flowControl = getFlowControlStrategyFactory().newFlowControlStrategy();

ServerParser parser = newServerParser(connector, getRateControlFactory().newRateControl(endPoint));
...
HTTP2ServerSession session = new HTTP2ServerSession(connector.getScheduler(), endPoint, parser, generator, listener, flowControl);
session.setMaxLocalStreams(getMaxConcurrentStreams());
session.setMaxRemoteStreams(getMaxConcurrentStreams());
...
long streamIdleTimeout = getStreamIdleTimeout();
if (streamIdleTimeout == 0)
    streamIdleTimeout = endPoint.getIdleTimeout();
...
HTTP2Connection connection = new HTTP2ServerConnection(connector, endPoint, httpConfiguration, session, listener);
...
parser.init(connection);
return configure(connection, connector, endPoint);
```

三个容易忽略的点：

1. **`Generator` 与 `ServerParser` 是每连接一个实例**，各自持有 HPACK 编/解码器，因此 HPACK 动态表天然是 per-connection 状态，不能跨连接共享。
2. **`parser.init(connection)` 必须在 `configure()` 之前**（`:345-347`），否则解析器回调找不到宿主。
3. **`streamIdleTimeout == 0` 回落到 `endPoint.getIdleTimeout()`**（`:331-333`）。`:327-330` 的注释解释了这条回落的动机：单流连接上流超时与连接超时会互相赛跑，通常连接更忙所以流超时先到。`-1` 是**关闭**流超时，`0` 是**跟随连接**，正数是显式毫秒——三个值语义不同，运维脚本里写 `0` 往往不是想要的。

## Object model connection session stream HttpStream

四层职责必须分清，否则会误判 bug 属于哪一层：

| 层 | 类 | 在镜像中 | 职责 |
| :--- | :--- | :--- | :--- |
| IO 驱动 | `HTTP2Connection` | ❌ `http2-common` | 从 `EndPoint` 拉字节喂 parser，回写 generator |
| IO 驱动（server） | `internal/HTTP2ServerConnection.java:62` `extends HTTP2Connection implements ConnectionMetaData, ServerParser.Listener` | ✅ 415 行 | 把帧事件翻译成 HTTP 语义，并充当 `ConnectionMetaData` |
| 会话状态机 | `HTTP2Session` ❌ / `internal/HTTP2ServerSession.java:45` `extends HTTP2Session implements ServerParser.Listener` ✅ 230 行 | 部分 | 流表、SETTINGS、GOAWAY、窗口、idle 计时 |
| 单流 | `HTTP2Stream`、`HTTP2Channel` | ❌ `http2-common` | 帧与 promise 队列、流级窗口 |
| server 语义适配 | `internal/HttpStreamOverHTTP2.java:58` `implements HttpStream, HTTP2Channel.Server` | ✅ 809 行 | 与 HTTP/1 共用同一个 `HttpStream` 契约 |
| 流端点视图 | `internal/ServerHTTP2StreamEndPoint.java` | ✅ 85 行 | 把 stream 伪装成 `EndPoint` 供 `Request` 取地址（逐字段未核对） |

事件回调用三层嵌套接口传下去：`ServerSessionListener`（`http2-common` 公开 API）← `HTTP2ServerSession.Listener extends ServerSessionListener`（`internal/HTTP2ServerSession.java:226`）← `HTTPServerSessionListener implements HTTP2ServerSession.Listener, Stream.Listener`（`HTTP2ServerConnectionFactory.java:89`）。`Stream.Listener` 同时被 `onNewStream` 返回（`:110-118`），意味着**每个流的后续事件直接落到工厂的内部类上**，不经过 `HttpChannel`。

## onStream isomorphic to HTTP/1 startRequest

这是本篇最重要的架构论点。**HTTP/2 与 HTTP/1 在进入业务逻辑之前就已经汇合成同一条路径**，看 `internal/HTTP2ServerConnection.java:139-151`：

```java
public void onNewStream(HTTP2Stream stream, HeadersFrame frame)
{
    if (LOG.isDebugEnabled())
        LOG.debug("Processing {} on {}", frame, stream);

    HttpChannel httpChannel = pollHttpChannel();
    HttpStreamOverHTTP2 httpStream = new HttpStreamOverHTTP2(this, httpChannel, stream);
    httpChannel.setHttpStream(httpStream);
    stream.setAttachment(httpStream);
    Runnable task = httpStream.onRequest(frame);
    if (task != null)
        offerTask(task, false);
}
```

对照 HTTP/1 侧的 `HttpConnection` → `HttpChannel` → `HttpStreamOverHTTP1`，结构完全一致：**取一个 `HttpChannel`（能复用就复用）、造一个 `HttpStream` 实现、双向绑定（`setHttpStream` 与 `setAttachment` 各指一次）、把请求事件交给 channel、拿到 `Runnable` 再投递**。差异全在 `HttpStream` 实现内部，`HttpChannel` 与 `Handler` 一行都不用改。请求生命周期细节见 [Jetty 请求处理流程](/docs/CS/Framework/Jetty/RequestFlow.md)，内容模型见 [Jetty 内容模型](/docs/CS/Framework/Jetty/ContentModel.md)。

`HttpChannel` 的复用值得单看（`:268-283`）：

```java
private HttpChannel pollHttpChannel()
{
    HttpChannel httpChannel = null;
    if (isRecycleHttpChannels())
        httpChannel = httpChannels.poll();
    if (httpChannel == null)
        httpChannel = httpChannelFactory.newHttpChannel(this);
    httpChannel.initialize();
    return httpChannel;
}
```

`recycleHttpChannels` 默认 `true`（`:88`），队列是 `ConcurrentLinkedQueue` 且注释明说「无界但被 max concurrent streams 天然限制」（`:67`）。这条注释解释了为什么 `maxConcurrentStreams` 同时也是**每连接内存占用的一级旋钮**。

push 请求走的是同一套代码（`:255-266`）：`connection.push()` 同样 `pollHttpChannel()` + `new HttpStreamOverHTTP2(...)`，只是事件入口换成 `onPushRequest(request)`。

还有一处关键细节：`HTTPServerSessionListener.onNewStream()` 返回 `this` 但**不 demand DATA 帧**，源码注释（`HTTP2ServerConnectionFactory.java:112-117`）给出的理由是「让带 `:protocol` 伪头的 CONNECT 把 DATA 帧缓冲到升级完成为止」——这是 Extended CONNECT 能工作的前提。

## Flow control

镜像内可见的只有**装配**，实现全在 `http2-common`。装配三件套：

- `initialSessionRecvWindow` / `initialStreamRecvWindow` → `session.setInitialSessionRecvWindow(...)`（`:335`）与 SETTINGS `INITIAL_WINDOW_SIZE`（`:294-296`）。协议规定的初值是 65535（`FlowControlStrategy.DEFAULT_WINDOW_SIZE`），Jetty 默认把它抬到 512 KiB——**这是 Jetty 对高 BDP 场景的主动调优，不是协议默认值**，迁移对比时别把两者混为一谈。
- `flowControlStrategyFactory = () -> new BufferingFlowControlStrategy(0.5F)`（`:67`）。`BufferingFlowControlStrategy` 不在镜像内，**0.5F 的确切语义未在源码中确认**；按类名与 Jetty 官方文档口径推断为「已消费窗口比例达到阈值才回补 WINDOW_UPDATE」，用于把微小的读进度合并成少量 WINDOW_UPDATE 帧，降低帧数。要改成每连接不同的策略，`setFlowControlStrategyFactory`（`:184-187`）是唯一入口。
- `rateControlFactory = new WindowRateControl.Factory(128)`（`:66`）→ 传给 `ServerParser`（`:320`、`:352-355`）。`WindowRateControl` **在 `jetty-io` 里，源码可见**：`jetty-io-12.1.14/org/eclipse/jetty/io/WindowRateControl.java:32` `class WindowRateControl implements RateControl`，`:39` 构造 `(int maxEvents, Duration window)`，`:82` `Factory(int maxEventRate)`。它保护的是 WINDOW_UPDATE 这类小帧的处理速率，属于抗帧洪水（对应 RFC 9113 的 `FLOW_CONTROL_ERROR` / 实现层限速）的第一道闸。

内存估算的实用式：**最坏缓冲 ≈ maxConcurrentStreams × initialStreamRecvWindow + initialSessionRecvWindow**（按默认 128 × 512 KiB + 1 MiB ≈ 65 MiB 每连接上界）。这条推导由镜像内的默认值组合而成，但真实占用还取决于 `setWriteThreshold(getHttpConfiguration().getOutputBufferSize())`（`:336`）与对端消费速度，只能当上界看。

## HPACK and SETTINGS mapping

SETTINGS 由 `newSettings()`（`:287-305`）产出，**多数键是条件发送**，刻意不覆盖对端的默认认知：

| SETTINGS 键 | 来源 | 发送条件 |
| :--- | :--- | :--- |
| `HEADER_TABLE_SIZE` | `maxDecoderTableCapacity` | 仅当 `!= HpackContext.DEFAULT_MAX_TABLE_CAPACITY` |
| `MAX_CONCURRENT_STREAMS` | `maxConcurrentStreams` | 恒定 |
| `INITIAL_WINDOW_SIZE` | `initialStreamRecvWindow` | 仅当 `!= FlowControlStrategy.DEFAULT_WINDOW_SIZE` |
| `MAX_FRAME_SIZE` | `maxFrameSize` | 仅当 `> Frame.DEFAULT_MAX_SIZE` |
| `MAX_HEADER_LIST_SIZE` | `HttpConfiguration.requestHeaderSize` | 仅当 `> 0` |
| `ENABLE_CONNECT_PROTOCOL` | `connectProtocolEnabled` | 恒定（`1` 或 `0`） |

恒定发送的只有两项。抓包时看不到 `HEADER_TABLE_SIZE` 属正常现象——**没改就等于没协商**。

HPACK 的三个装配点：

- 解码侧容量与 `requestHeaderSize` 一起进 `ServerParser`（`:352-355`）。
- 编码侧 `generator.getHpackEncoder().setMaxHeaderListSize(maxResponseHeaderSize)`（`:313-316`），其中 `maxResponseHeaderSize < 0` 时回落 `responseHeaderSize`——**`HttpConfiguration` 里设 negativeOne 表示「不限制」**，这条回落逻辑在 HTTP/1 侧也有对应物。
- 表容量对偶：encoder 用 `maxEncoderTableCapacity`（`:326`，本机发出去的压缩上下文），decoder 用 `maxDecoderTableCapacity`（→ `HEADER_TABLE_SIZE`，要求对端用的上下文）。两者都默认 `HpackContext.DEFAULT_MAX_TABLE_CAPACITY`，**该常量的具体字节数因 `HpackContext` 不在镜像中而未能确认**，需要时直接读 `http2-common` 源码，不要凭 RFC 7541 的示例值写进配置。

## executeImmediately for control frames

`internal/HTTP2ServerConnection.java` 里有两处刻意绕开队列（`:197`、`:229`），后者注释最有价值（`:226-229`）：

```java
Runnable task = channel.onFailure(failure, callback);
// The task may unblock a blocked read or write, so it cannot be
// queued, because there may be no threads available to run it.
ThreadPool.executeImmediately(getExecutor(), task);
```

因果链很清楚：HTTP/2 上单条连接可以有很多流同时阻塞在读写上；**「解除阻塞」的那类任务如果被投进线程池队列，而队列前方没有空闲线程，就会与它所等待的线程互为死锁**。所以 `onStreamFailure`（`:212-230`）与 `onStreamTimeout`（`:180-210`）走 `executeImmediately`，普通请求任务走 `offerTask`。同类约束在 HTTP/1 侧不存在（一条连接同一时刻只有一个请求）。

代价也必须写明：`executeImmediately` 会**即时借用执行能力**，恶意客户端批量制造失败流或流超时，就能绕过线程池的排队上限，形成线程放大。把它与 `maxConcurrentStreams`、连接 `idleTimeout` 一起当作配套参数看，别单调。线程模型见 [Jetty 线程模型](/docs/CS/Framework/Jetty/Threading.md)。

## ALPN and CipherDiscriminator

`h2` 只可能经 ALPN 协商而来，而 Jetty 把「密码套件够不够格跑 HTTP/2」这个判断**下放给了协议工厂**：`HTTP2ServerConnectionFactory implements CipherDiscriminator`（`:52`），判据写在 `isAcceptable()`（`:80-87`）里——`"h2-14".equals(protocol) || !(HTTP2Cipher.isBlackListProtocol(tlsProtocol) && HTTP2Cipher.isBlackListCipher(tlsCipher))`，源码注释「Implement 9.2.2 for draft 14」。

`CipherDiscriminator` 定义在 `jetty-server-12.1.14/org/eclipse/jetty/server/NegotiatingServerConnection.java:32-35`，只有一个方法 `isAcceptable(String, String, String)`。这是 RFC 9113 TLS 实现要求的黑名单（`HTTP2Cipher` 属 `http2-common`，黑名单内容未确认）。`HTTP2CServerConnectionFactory` 把它重写成**恒 `false`**（`:62-67`，注释「Never use TLS with h2c」），所以 h2c 工厂永远不会被 ALPN 选中——想同时支持两种形态，正确做法是**两个 connector 或同 connector 上两个工厂，靠协议名区分**。

ALPN 提供方要澄清两处：接口 `ALPNProcessor` 的实际路径是 **`jetty-io-12.1.14/org/eclipse/jetty/io/ssl/ALPNProcessor.java:20`**（不在 `jetty-util`），三个 default 方法是 `init()`（`:27`）、`appliesTo(SSLEngine)`（`:37`）、`configure(SSLEngine, Connection)`（`:49`）；`:53-65` 定义了两个空子接口 `Server`、`Client`，各自 javadoc 写明「used by ServiceLoader」。`SslContextFactory` 在 `jetty-util-12.1.14/org/eclipse/jetty/util/ssl/SslContextFactory.java:103`（`abstract class ... extends ContainerLifeCycle implements Dumpable`）。**真正的 ALPN 实现模块不在本镜像内，本篇不写其类名**；能确认的只有「通过 ServiceLoader 注入、`appliesTo` 决定谁生效」这一机制。TLS 参数见 [Tomcat TLS](/docs/CS/Framework/Tomcat/TLS.md)。

## Two h2c paths

两条路径**共用同一个入口**：`HTTP2CServerConnectionFactory.upgradeConnection()`（`:69-82`）。它先拒绝带 body 的升级请求（`:75-76` `request.getContentLength() > 0` 返回 `null`），再 `newConnection()` 并交给 `HTTP2ServerConnection.upgrade(request, response101)`。真正的分叉在 `internal/HTTP2ServerConnection.java:285-324`：

```java
public boolean upgrade(Request request, HttpFields.Mutable responseFields)
{
    if (HttpMethod.PRI.is(request.getMethod()))
    {
        getSession().directUpgrade();
    }
    else
    {
        HttpField settingsField = request.getHttpFields().getField(HttpHeader.HTTP2_SETTINGS);
        if (settingsField == null)
            throw new HttpException.IllegalStateException(HttpStatus.BAD_REQUEST_400, "Missing " + HttpHeader.HTTP2_SETTINGS + " header");
        ...
        responseFields.put(HttpHeader.UPGRADE, "h2c");
        responseFields.put(HttpHeader.CONNECTION, "Upgrade");

        getSession().standardUpgrade();

        // We fake that we received a client preface, so that we can send the
        // server preface as the first HTTP/2 frame as required by the spec.
        // When the client sends the real preface, the parser won't notify it.
        upgradeFrames.add(new PrefaceFrame());
        // This is the settings from the HTTP2-Settings header.
        upgradeFrames.add(settingsFrame);
        // Remember the request to send a response.
        upgradeFrames.add(new HeadersFrame(1, request, null, true));
    }
    return true;
}
```

- **prior-knowledge（`PRI * HTTP/2.0`）** → `directUpgrade()`，不产出任何 `upgradeFrames`。这条路径的**识别方在 HTTP/1 侧**：`jetty-server-12.1.14/org/eclipse/jetty/server/internal/HttpConnection.java:388-398` 在解析后检查 `getEndPoint().getConnection() != this`，注释直接点名「for example PRI * HTTP/2」，一旦被换掉就 `break` 让位。前提是同端口必须还挂着 `HttpConnectionFactory` 作为默认协议（`HTTP2CServerConnectionFactory.java:36-42` 的 javadoc 明说这一点）。
- **Upgrade 协商（`Upgrade: h2c`）** → `standardUpgrade()` + **伪造三帧**：一个假 `PrefaceFrame`（为了让服务端先出自己那半程 preface，真 preface 到达时 parser 不再通知）、`HTTP2-Settings` 头 base64url 解出的 SETTINGS、以及流 1 上的 `HeadersFrame(request, endStream=true)` 用于回响应。三帧暂存在 `upgradeFrames`（`:70`），`onOpen()` 时按序重放（`:113-116`）。

`directUpgrade` / `standardUpgrade` 的实现在 `HTTP2Session`（`http2-common`，**未确认**）。注意 `settingsField == null` 或解析失败时抛的是 **400**（`:295`、`:306`），这是排查 h2c 兼容性时最有用的信号。

> [!WARNING]
>
> h2c 没有 ALPN 保护，经过任何不识别 HTTP/2 的代理或 LB 都可能被拆坏帧。生产上 h2c 只在**自己掌控的服务间链路**（sidecar、gRPC、内网直连）使用，公网入口一律 `h2` over TLS。

## Extended CONNECT and WebSocket over HTTP/2

三处装配连成一条线：`connectProtocolEnabled = true`（`:65`）→ SETTINGS `ENABLE_CONNECT_PROTOCOL=1`（`:303`）→ `session.setConnectProtocolEnabled(...)`（`:337`）。配合 `onNewStream` **不 demand DATA**（见上文 `:112-117`），使得带 `:protocol` 伪头的 CONNECT 可以把 DATA 帧先缓冲起来，等升级完成再消费。

对端支持在镜像内可确认：`jetty-websocket-core-server-12.1.14/org/eclipse/jetty/websocket/core/server/internal/RFC8441Handshaker.java` 与同目录 `RFC8441Negotiation.java`（两个文件均存在，实现细节本篇不展开）。反过来，若把 `connectProtocolEnabled` 设为 `false`，SETTINGS 里是 `0` 而不是缺省——客户端能明确看到禁用，这比不发该键更干净。Servlet 侧的 WebSocket 升级路径见 [Servlet](/docs/CS/Java/JDK/Servlet.md)。

## Status of push

Jetty 12.1 **协议层仍然完整实现了 server push**，这与 Tomcat 11 移除 push 的做法相反：

- `jetty-server-12.1.14/org/eclipse/jetty/server/HttpStream.java:104-106` 的 `default void push(MetaData.Request resource)` 抛 `UnsupportedOperationException`（javadoc `:101-102` 明确指向 `ConnectionMetaData#isPushSupported()`）。
- `internal/HttpStreamOverHTTP2.java:486-513` **真实覆写**了它：先查 `_stream.getSession().isPushEnabled()`，不通过则 debug 日志「HTTP/2 push disabled」（`:488-492`）；通过则 `_stream.push(new PushPromiseFrame(_stream.getId(), resource), Promise)`，成功回调里 `_connection.push((HTTP2Stream)pushStream, resource)`（`:498-503`）。
- `internal/HTTP2ServerConnection.java:369-372` 的 `isPushSupported()` **委托给 `getSession().isPushEnabled()`**，不是恒 `true`；`isPushEnabled` 的判定逻辑（对端 SETTINGS_ENABLE_PUSH）在 `http2-common`，未确认。
- 接收方向一律禁止：`HTTP2ServerSession.java:167` 与 `HTTP2ServerConnectionFactory.java:159-164` 收到 `PUSH_PROMISE` 都按 `PROTOCOL_ERROR` 关会话（注释「Servers do not receive pushes.」）。

结论要分层说：**Jetty 保留了协议能力，但 Servlet 规范侧 `PushBuilder` 的可用性属另一层，本篇不下结论**（EE10/EE11 的演进见 [Jetty EE 分层](/docs/CS/Framework/Jetty/EeLayer.md)）。新代码按「不依赖 push」设计即可。

## Reality of h3

`HTTP2ServerConnectionFactory` 构造时会给 `HttpConfiguration` 挂一个 `AltSvcCustomizer`（`:64`、`:70`），它遍历 server 的 connector，找 `connector.getProtocols().contains("h3")` 的 `NetworkConnector`，命中就发 `Alt-Svc: h3=":port"`，可带 `ma=` 与 `persist=1`（`:253-280`）。

三点要说清：

1. 这是**纯字符串匹配**，`h3` 这个名字由别的模块的 ConnectionFactory 申报；本镜像里**没有任何 QUIC / HTTP/3 模块**，`jetty-server` 与 `jetty-http` 里 `h3` 只出现在 `HttpVersion.HTTP_3` 枚举与若干 javadoc 中。
2. 因此默认部署下 `AltSvcCustomizer` 的分支**不会命中，也就不发 Alt-Svc 头**——`HTTP/3` 支持与否取决于是否另行引入 Jetty 的 h3/QUIC artifact，不能从 `HTTP2ServerConnectionFactory` 的存在推断出来。
3. 反过来，`AbstractHTTP2ServerConnectionFactory` 的白名单**禁止**给 HTTP/2 工厂申报 `h3`（`:46-53`），所以 Alt-Svc 广告与 h2 工厂是解耦的：前者查全 server 的 connector 列表，后者只管自己。

## Pitfalls

| 症状 | 根因 | 定位 |
| :--- | :--- | :--- |
| 一堆 `NoSuchMethodError` | 依赖写成旧坐标 `http2-server`，解析到 Jetty 11.0.26 | 见「artifact 改名」节 |
| 并发一大就变慢，但线程池未满 | `maxConcurrentStreams=128` 是**每连接**闸门；客户端只开 1 条连接时，128 就是全局并发上限 | `AbstractHTTP2ServerConnectionFactory.java:61` |
| 请求偶发被 400 拒 | h2c 缺 `HTTP2-Settings` 头或 base64url 解不出 | `internal/HTTP2ServerConnection.java:295, 306` |
| 单流长轮询被莫名关闭 | `streamIdleTimeout=0` 回落到连接 idle timeout，与你的预期不同 | `:331-333`；要显式设正值或 `-1` |
| 大量流失败后线程数暴涨 | `executeImmediately` 绕开队列，失败风暴直接借线程 | `:226-229` |
| WebSocket over HTTP/2 不生效 | `connectProtocolEnabled` 被关成 `0`，或 websocket 模块缺 `RFC8441Handshaker` | `:65`、`:303` |
| 想按 HTTP/3 配置却发现无接口 | h2 工厂白名单不含 `h3`，QUIC 是独立模块 | `:46-53` |

## Links

- [Jetty](/docs/CS/Framework/Jetty/Jetty.md)
- [Jetty Connector 与 ConnectionFactory](/docs/CS/Framework/Jetty/Connector.md)
- [Jetty 线程模型](/docs/CS/Framework/Jetty/Threading.md)
- [Jetty 请求处理流程](/docs/CS/Framework/Jetty/RequestFlow.md)
- [Tomcat HTTP/2 实现](/docs/CS/Framework/Tomcat/HTTP2.md)
- [Servlet](/docs/CS/Java/JDK/Servlet.md)

## References

- [RFC 9113 HTTP/2](https://datatracker.ietf.org/doc/html/rfc9113)
- [RFC 7541 HPACK](https://datatracker.ietf.org/doc/html/rfc7541)
- [RFC 8441 Bootstrapping WebSockets with HTTP/2](https://datatracker.ietf.org/doc/html/rfc8441)
- [RFC 7838 HTTP Alternative Services](https://datatracker.ietf.org/doc/html/rfc7838)
- [Maven Central: jetty-http2-server](https://repo1.maven.org/maven2/org/eclipse/jetty/http2/jetty-http2-server/)
- [Jetty 官方文档](https://jetty.org/docs/)
