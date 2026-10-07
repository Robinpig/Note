## Introduction

Dubbo 的 RPC 抽象（`Protocol` / `Invoker`）之下还有一层「传输」抽象（`Transporter`）。它只负责一件事：把「收发字节」这件事抽象出来，因此同一套 RPC 协议既可以跑在 Netty 上，也可以跑在 HTTP/2、WebSocket 之上。流传最广的三个说法，本文逐条从源码推翻：

- **「Dubbo 有 netty / netty4 / mina 三个 Transporter 实现」**——不成立。`netty` 与 `netty4` 这两个扩展名**指向同一个类**（`org.apache.dubbo.remoting.transport.netty4.NettyTransporter`）；`mina` 在 3.x 主仓库**已被彻底移除**，全仓检索 `mina` 只命中 `isTerminated`、`awaitTermination` 这类误匹配的测试代码。
- **「`Transporters` 是门面类，里面有 `connectAsync` 异步连接入口」**——不成立。3.3.6 的 `Transporters` 一共只有 5 个静态方法：`bind`(×2)、`connect`(×2)、`getTransporter`，**没有任何异步连接方法**。
- **「`NettyServer` 用 `SSL_ENABLED_KEY` 开关决定是否加 SSL handler」**——不成立。3.3.6 的 pipeline **无条件**插入 `negotiation`（`SslServerTlsHandler`），TLS 协商变成一种「嗅探式」的渐进增强，不再受 URL 参数开关控制。

版本基线：Apache Dubbo **3.3.6**，源码 tag `dubbo-3.3.6`。本文所有类签名、SPI 注册文件内容、默认值、行号均取自该 tag 官方源码。

事实来源声明：`dubbo-remoting/` 的模块清单与 SPI 注册文件内容来自 `ls` 与读取 `META-INF/dubbo/internal/org.apache.dubbo.remoting.Transporter`；类实现逐行取自 `dubbo-remoting/dubbo-remoting-netty4/` 与 `dubbo-remoting/dubbo-remoting-api/` 的 `.java` 文件。本文不引用任何二手博客或网络文章。

`Channel` / `ChannelHandler` / `Codec` / `Dispatcher` 的接口结构已在 [remoting.md](/docs/CS/Framework/Dubbo/remoting.md) 展开，线程模型（`Dispatcher` 与 `ThreadPool`）见 [ThreadPool.md](/docs/CS/Framework/Dubbo/ThreadPool.md)，协议族与端口复用见 [Triple.md](/docs/CS/Framework/Dubbo/Triple.md)，本文不重复，只聚焦「传输层由谁实现、怎么装配、生命周期怎么走」。

## Overall Positioning: The Position of the Transport Layer in the Call Chain

一次 Dubbo RPC 从上到下依次穿过：

| 层 | 入口 | 产物 |
| :--- | :--- | :--- |
| 配置层 | `ServiceConfig` / `ReferenceConfig` | `URL` |
| 协议层 | `Protocol`（如 `DubboProtocol`） | `Exporter` / `Invoker` |
| 交换层 | `Exchanger`（默认 `header`） | `ExchangeServer` / `ExchangeClient` |
| 传输层 | `Transporter`（默认 `netty`） | `RemotingServer` / `Client` |

`HeaderExchanger` 是两层之间唯一的桥：

```java
// dubbo-remoting/dubbo-remoting-api/src/main/java/org/apache/dubbo/remoting/exchange/support/header/HeaderExchanger.java:49-58
@Override
public ExchangeServer bind(URL url, ExchangeHandler handler) throws RemotingException {
    ExchangeServer server;
    boolean isPuServerKey = url.getParameter(IS_PU_SERVER_KEY, false);
    if (isPuServerKey) {
        server = new HeaderExchangeServer(
                PortUnificationExchanger.bind(url, new DecodeHandler(new HeaderExchangeHandler(handler))));
    } else {
        server = new HeaderExchangeServer(
                Transporters.bind(url, new DecodeHandler(new HeaderExchangeHandler(handler))));
    }
    return server;
}
```

> [!TIP]
> `IS_PU_SERVER_KEY`（URL 参数 `ispuserver`）是「单端口多协议」的开关。为 `true` 时走 `PortUnificationExchanger`，否则走普通 `Transporters`——这条分支是理解「DubboProtocol 与 Triple 如何共用一个端口」的关键，详见 [Triple.md](/docs/CS/Framework/Dubbo/Triple.md?id=port-and-single-port-multi-protocol)。

`Protocol` 层不感知具体传输实现，只通过 URL 上的 `transporter` 参数间接选择扩展。参数校验在 `ConfigValidationUtils.java:586,599`，会先用 `ExtensionLoader.hasExtension` 确认扩展存在。

## `dubbo-remoting/` Module Overview

3.3.6 的 `dubbo-remoting/` 有 **7 个子模块**：

| 子模块 | 职责 | 含 `Transporter` SPI |
| :--- | :--- | :--- |
| `dubbo-remoting-api` | 核心 API：`Transporter` / `Client` / `RemotingServer` / `Channel` / `Codec2` / `Exchange` / `transport` / `buffer` / `dispatcher` / `utils`，以及 `ConnectionManager` / `PortUnificationTransporter` 的抽象 | 否（只有接口与 test 注册） |
| `dubbo-remoting-netty4` | **默认实现**。`NettyTransporter` / `NettyServer` / `NettyClient`，含 `ssl/`、`http2/`、`aot/`、`logging/` 子包 | **是**（`netty`、`netty4`） |
| `dubbo-remoting-netty` | Netty 3.x 遗留实现，仅保留 `netty3` 名字与 `PortUnificationTransporter` | **是**（`netty3`） |
| `dubbo-remoting-http12` | HTTP/1.1 与 HTTP/2 的 `Codec2` 实现，`h1` / `command` / `rest` / `message.codec` 等包 | 否 |
| `dubbo-remoting-http3` | HTTP/3（`http3/netty4`） | 否 |
| `dubbo-remoting-websocket` | WebSocket（`websocket/netty4`） | 否 |
| `dubbo-remoting-zookeeper-curator5` | Curator5 客户端，**给注册中心/元数据中心用**，不是业务传输通道 | 否 |

> [!WARNING]
> 网上流传的「Dubbo 支持 netty / mina / grizzly / thrift」清单对应的是 2.x 时代。3.3.6 主仓库**没有** `dubbo-remoting-mina`，也**没有** `dubbo-remoting-grizzly`、`dubbo-remoting-etcd3`。`mina` 相关实现需要显式引入外部 `org.apache.dubbo.extensions` 生态仓库；grizzly / thrift 传输在 3.x 主线已不可用。

## `Transporter` SPI and Registration Mechanism

### Interface Definition

```java
// dubbo-remoting/dubbo-remoting-api/src/main/java/org/apache/dubbo/remoting/Transporter.java:32-58
@SPI(value = "netty", scope = ExtensionScope.FRAMEWORK)
public interface Transporter {

    @Adaptive({Constants.SERVER_KEY, Constants.TRANSPORTER_KEY})
    RemotingServer bind(URL url, ChannelHandler handler) throws RemotingException;

    @Adaptive({Constants.CLIENT_KEY, Constants.TRANSPORTER_KEY})
    Client connect(URL url, ChannelHandler handler) throws RemotingException;
}
```

两处容易记错的细节：

- `@SPI` 的默认值是 `netty`，**不是 `netty4`**。之所以能正常工作，是因为 `netty` 与 `netty4` 两个扩展名注册到了同一个类。
- `@Adaptive` 的 key 不同：`bind` 读 `server` / `transporter`，`connect` 读 `client` / `transporter`。写 `transporter=netty4` 两者都生效；只写 `client=netty4` 只影响连接侧。

`scope = ExtensionScope.FRAMEWORK` 表示这个扩展是**框架级**的，一个 `FrameworkModel` 内单例，被所有 `ApplicationModel` 共享。SPI 的 scope 机制详见 [SPI.md](/docs/CS/Framework/Dubbo/SPI.md)。

### Three SPI Registration Files

生产代码里只有 **2 份**（第 3 份在 test 资源里），共注册 4 个扩展名：

```properties
# dubbo-remoting/dubbo-remoting-netty4/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.remoting.Transporter
netty4=org.apache.dubbo.remoting.transport.netty4.NettyTransporter
netty=org.apache.dubbo.remoting.transport.netty4.NettyTransporter
```

```properties
# dubbo-remoting/dubbo-remoting-netty/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.remoting.Transporter
netty3=org.apache.dubbo.remoting.transport.netty.NettyTransporter
```

第 3 份在 `dubbo-remoting-api/src/test/resources/` 下，注册 `mockTransporter=org.apache.dubbo.remoting.MockTransporter`，仅测试用。

| 扩展名 | 实现类 | 状态 |
| :--- | :--- | :--- |
| `netty` | `transport.netty4.NettyTransporter` | 默认（`@SPI` 指定） |
| `netty4` | `transport.netty4.NettyTransporter` | **与 `netty` 同一个类** |
| `netty3` | `transport.netty.NettyTransporter` | Netty 3.x 遗留，向后兼容别名 |
| `mockTransporter` | `MockTransporter` | 仅测试 |

> [!NOTE]
> `netty` 这个别名是历史包袱：早期 `netty` 指向 Netty 3.x 实现，Netty 4 成为默认后没有清理别名，而是让两者同时指向新实现。因此「把 `transporter=netty` 改成 `netty4` 以启用 Netty 4」这类操作在 3.x 上**没有任何效果**。

### NettyTransporter

```java
// dubbo-remoting/dubbo-remoting-netty4/src/main/java/org/apache/dubbo/remoting/transport/netty4/NettyTransporter.java:29-42
/**
 * Default extension of {@link Transporter} using netty4.x.
 */
public class NettyTransporter implements Transporter {

    public static final String NAME = "netty";

    @Override
    public RemotingServer bind(URL url, ChannelHandler handler) throws RemotingException {
        return new NettyServer(url, handler);
    }

    @Override
    public Client connect(URL url, ChannelHandler handler) throws RemotingException {
        return new NettyClient(url, handler);
    }
}
```

实现只有两行 `new`，**没有任何连接池、线程池、重试逻辑**。它甚至没有实现 `Transporter` 之外的能力——`NAME` 常量为 `"netty"` 而类在 `netty4` 包下，这种「常量与包名不一致」正是双别名演化的残留。

## `Transporters` Facade

`Transporters` 是纯静态门面，构造器私有，**3.3.6 只有 5 个方法**。核心是 `getTransporter` 与两个 handler 分发方法：

```java
// dubbo-remoting/dubbo-remoting-api/src/main/java/org/apache/dubbo/remoting/Transporters.java:34-47,69-73
public static RemotingServer bind(URL url, ChannelHandler... handlers) throws RemotingException {
    if (url == null) {
        throw new IllegalArgumentException("url == null");
    }
    if (handlers == null || handlers.length == 0) {
        throw new IllegalArgumentException("handlers == null");
    }
    ChannelHandler handler;
    if (handlers.length == 1) {
        handler = handlers[0];
    } else {
        handler = new ChannelHandlerDispatcher(handlers);
    }
    return getTransporter(url).bind(url, handler);
}

public static Transporter getTransporter(URL url) {
    return url.getOrDefaultFrameworkModel()
            .getExtensionLoader(Transporter.class)
            .getAdaptiveExtension();
}
```

（`bind(String)` / `connect(String)` 两个重载只是 `URL.valueOf` 转发；`connect` 的结构与 `bind` 相同但对 0 个 handler 走兜底而非抛异常。）

`bind` 与 `connect` 对 handler 的处理**故意不对称**，这是唯一的实质差异：

| 场景 | `bind` | `connect` |
| :--- | :--- | :--- |
| 0 个 handler | 抛 `IllegalArgumentException` | 兜一个 `ChannelHandlerAdapter` |
| 1 个 handler | 直接用 | 直接用 |
| 多个 handler | 包 `ChannelHandlerDispatcher` | 包 `ChannelHandlerDispatcher` |

服务端不允许「无 handler」，因为服务端必须由 handler 决定收到消息后做什么；客户端允许「无 handler」，用于纯探测连通性的场景。

> [!WARNING]
> **没有 `connectAsync`。** 3.3.6 的 `Transporters` 与整个 `dubbo-remoting`、`dubbo-rpc` 主源码目录检索 `connectAsync`，**0 命中**。需要异步建连的场景走 `ConnectionManager` 体系（见下文「3.x 新增扩展点」）。

`getTransporter` 用的是 `url.getOrDefaultFrameworkModel()` 而不是 `applicationModel`，与 `@SPI(scope = FRAMEWORK)` 对应——传输扩展在框架级查找，与应用级配置无关。

## `NettyServer` Lifecycle

3.3.6 的 `NettyServer` 相对 2.7.x 已重构：`extends AbstractServer`（不再显式 `implements RemotingServer`）、`doOpen` 拆成 5 个可覆写步骤、加入 metrics 上报、优雅停机带双参数、SSL 无条件启用。

### Separation of Construction and doOpen

```java
// dubbo-remoting/dubbo-remoting-netty4/src/main/java/org/apache/dubbo/remoting/transport/netty4/NettyServer.java:63-110
public class NettyServer extends AbstractServer {

    private Map<String, Channel> channels;
    private ServerBootstrap bootstrap;
    private io.netty.channel.Channel channel;
    private EventLoopGroup bossGroup;
    private EventLoopGroup workerGroup;
    private int serverShutdownTimeoutMills;

    public NettyServer(URL url, ChannelHandler handler) throws RemotingException {
        // the handler will be wrapped: MultiMessageHandler->HeartbeatHandler->handler
        super(url, ChannelHandlers.wrap(handler, url));
    }

    @Override
    protected void doOpen() throws Throwable {
        bootstrap = new ServerBootstrap();
        // read config before destroy
        serverShutdownTimeoutMills = ConfigurationUtils.getServerShutdownTimeout(getUrl().getOrDefaultModuleModel());

        bossGroup = createBossGroup();
        workerGroup = createWorkerGroup();
        final NettyServerHandler nettyServerHandler = createNettyServerHandler();
        channels = nettyServerHandler.getChannels();
        initServerBootstrap(nettyServerHandler);

        try {
            ChannelFuture channelFuture = bootstrap.bind(getBindAddress());
            channelFuture.syncUninterruptibly();
            channel = channelFuture.channel();
        } catch (Throwable t) {
            closeBootstrap();                      // 失败也要回收 EventLoop
            throw t;
        }
        // ... metrics 上报，见下文
    }
```

`doOpen` 被拆成 5 个 `protected` 方法（`createBossGroup` / `createWorkerGroup` / `createNettyServerHandler` / `initServerBootstrap` / `closeBootstrap`），**全部可覆写**——这是 3.3.6 相对 2.7.x 最大的结构变化，2.7.x 是一个 40 行的 `doOpen` 一把梭。

另外两个 2.7.x 时代的写法在 3.3.6 里已经不存在：`super(ExecutorUtil.setThreadName(url, SERVER_THREAD_POOL_NAME), ...)` 的线程名包装**已移到 `AbstractServer` 内部**（`AbstractServer.java:78,105`）；`private static final Logger logger` **已删除**，改用继承自 `AbstractEndpoint` 的 `ErrorTypeAwareLogger logger`（`AbstractEndpoint.java:37`），日志带错误码。

### IO Thread Count, SO_KEEPALIVE and pipeline Order

```java
// dubbo-remoting/dubbo-remoting-netty4/src/main/java/org/apache/dubbo/remoting/transport/netty4/NettyServer.java:157-161
protected EventLoopGroup createWorkerGroup() {
    return NettyEventLoopFactory.eventLoopGroup(
            getUrl().getPositiveParameter(IO_THREADS_KEY, Constants.DEFAULT_IO_THREADS),
            EVENT_LOOP_WORKER_POOL_NAME);
}
```

```java
// dubbo-remoting/dubbo-remoting-api/src/main/java/org/apache/dubbo/remoting/Constants.java:118
int DEFAULT_IO_THREADS = Math.min(Runtime.getRuntime().availableProcessors() + 1, 32);
```

boss 组固定 1 个线程（`createBossGroup`，`:153-155`），worker 组默认 `min(CPU+1, 32)`。`iothreads` 走 `getPositiveParameter`，配成 0 或负值会**回落到默认值**而不是建 0 个线程。3.3.6 还新增了一个 server 端 keepalive 选项，见下面的 `SO_KEEPALIVE`。

```java
// dubbo-remoting/dubbo-remoting-netty4/src/main/java/org/apache/dubbo/remoting/transport/netty4/NettyServer.java:167-189
protected void initServerBootstrap(NettyServerHandler nettyServerHandler) {
    boolean keepalive = getUrl().getParameter(KEEP_ALIVE_KEY, Boolean.FALSE);
    bootstrap
            .group(bossGroup, workerGroup)
            .channel(NettyEventLoopFactory.serverSocketChannelClass())
            .option(ChannelOption.SO_REUSEADDR, Boolean.TRUE)
            .childOption(ChannelOption.TCP_NODELAY, Boolean.TRUE)
            .childOption(ChannelOption.SO_KEEPALIVE, keepalive)
            .childOption(ChannelOption.ALLOCATOR, PooledByteBufAllocator.DEFAULT)
            .childHandler(new ChannelInitializer<SocketChannel>() {
                @Override
                protected void initChannel(SocketChannel ch) throws Exception {
                    int closeTimeout = UrlUtils.getCloseTimeout(getUrl());
                    NettyCodecAdapter adapter = new NettyCodecAdapter(getCodec(), getUrl(), NettyServer.this);
                    ch.pipeline().addLast("negotiation", new SslServerTlsHandler(getUrl()));
                    ch.pipeline()
                            .addLast("decoder", adapter.getDecoder())
                            .addLast("encoder", adapter.getEncoder())
                            .addLast("server-idle-handler", new IdleStateHandler(0, 0, closeTimeout, MILLISECONDS))
                            .addLast("handler", nettyServerHandler);
                }
            });
}
```

server 端 `SO_KEEPALIVE` **默认关闭**（`KEEP_ALIVE_KEY` 默认 `FALSE`），而 client 端**默认开启**（`NettyClient.initBootstrap` 里硬编码 `.option(ChannelOption.SO_KEEPALIVE, true)`）——两端默认值不一致，是很容易踩空的一点。

pipeline 顺序是 `negotiation` → `decoder` → `encoder` → `server-idle-handler` → `handler`。`SslServerTlsHandler` 是一个 `ByteToMessageDecoder`，握手成功后会**把自己从 pipeline 里移除**（`ssl/SslServerTlsHandler.java` 的 `userEventTriggered` 中 `ctx.pipeline().remove(this)`），并把 `SSLSession` 存入 channel 属性。因此它是无害的前置嗅探器：明文连接时它发现不是 TLS 流量就放行，业务代码零感知。

`IdleStateHandler` 的**写空闲超时**从 `heartbeat * 3` 换成了 `close.timeout`。这就是 2.7.x 源码里 `// FIXME: should we use getTimeout()?` 那条注释的答案——FIXME 已解决。

### getCloseTimeout: New Method in 3.3.6

2.7.x 只有 `getIdleTimeout` / `getHeartbeat` 两个方法。3.3.6 增加了 `getCloseTimeout`，且两者**不是替换关系**——`getCloseTimeout` 内部会回落到 `getIdleTimeout`：

```java
// dubbo-remoting/dubbo-remoting-api/src/main/java/org/apache/dubbo/remoting/utils/UrlUtils.java:40-70
public static int getCloseTimeout(URL url) {
    String configuredCloseTimeout = SystemPropertyConfigUtils.getSystemProperty(
            CommonConstants.DubboProperty.DUBBO_CLOSE_TIMEOUT_CONFIG_KEY);
    int defaultCloseTimeout = -1;
    if (StringUtils.isNotEmpty(configuredCloseTimeout)) {
        try {
            defaultCloseTimeout = Integer.parseInt(configuredCloseTimeout);
        } catch (NumberFormatException e) {
            // use default heartbeat
        }
    }
    if (defaultCloseTimeout < 0) {
        defaultCloseTimeout = getIdleTimeout(url);      // 回落
    }
    int closeTimeout = url.getParameter(Constants.CLOSE_TIMEOUT_KEY, defaultCloseTimeout);
    int heartbeat = getHeartbeat(url);
    if (closeTimeout < heartbeat * 2) {
        throw new IllegalStateException("closeTimeout < heartbeatInterval * 2");
    }
    return closeTimeout;
}

public static int getIdleTimeout(URL url) {
    int heartBeat = getHeartbeat(url);
    int idleTimeout = url.getParameter(Constants.HEARTBEAT_TIMEOUT_KEY, heartBeat * 3);
    if (idleTimeout < heartBeat * 2) {
        throw new IllegalStateException("idleTimeout < heartbeatInterval * 2");
    }
    return idleTimeout;
}
```

三者的关系与兜底链：

| 方法 | URL key | 默认值 | 系统属性兜底 |
| :--- | :--- | :--- | :--- |
| `getHeartbeat(URL)` | `heartbeat` | `60000`（`DEFAULT_HEARTBEAT`） | `DUBBO_HEARTBEAT_CONFIG_KEY` |
| `getIdleTimeout(URL)` | `heartbeat.timeout` | `heartbeat * 3` | 同上（经 `getHeartbeat`） |
| `getCloseTimeout(URL)` | `close.timeout` | 回落 `getIdleTimeout(url)` | `DUBBO_CLOSE_TIMEOUT_CONFIG_KEY` |

> [!TIP]
> `getHeartbeat` 在 3.3.6 里**会先读系统属性** `DUBBO_HEARTBEAT_CONFIG_KEY`。2.7.x 的简化实现只有 `url.getParameter(HEARTBEAT_KEY, DEFAULT_HEARTBEAT)`，照抄旧代码会漏掉这一层，从而在容器环境下算出不同的 idle 超时。

后两者都有**硬校验**：小于 `heartbeat * 2` 直接抛 `IllegalStateException`。调小 `heartbeat` 却忘了同步调 `close.timeout`，会在 `NettyServer` 构造时炸掉。

### Graceful Shutdown and the New Semantics of getChannels

```java
// dubbo-remoting/dubbo-remoting-netty4/src/main/java/org/apache/dubbo/remoting/transport/netty4/NettyServer.java:225-249
private void closeBootstrap() {
    try {
        if (bootstrap != null) {
            long timeout = ConfigurationUtils.reCalShutdownTime(serverShutdownTimeoutMills);
            long quietPeriod = Math.min(2000L, timeout);
            Future<?> bossGroupShutdownFuture = bossGroup.shutdownGracefully(quietPeriod, timeout, MILLISECONDS);
            Future<?> workerGroupShutdownFuture =
                    workerGroup.shutdownGracefully(quietPeriod, timeout, MILLISECONDS);
            bossGroupShutdownFuture.syncUninterruptibly();
            workerGroupShutdownFuture.syncUninterruptibly();
        }
    } catch (Throwable e) {
        logger.warn(TRANSPORT_FAILED_CLOSE, "", "", e.getMessage(), e);
    }
}

@Override
public Collection<Channel> getChannels() {
    return new ArrayList<>(channels.values());
}
```

`shutdownGracefully` 从 2.7.x 的**无参**形式变成 `(quietPeriod, timeout, MILLISECONDS)`：先静默 `quietPeriod`（≤ 2 秒）等待正在写出的消息落地，最多等 `timeout`。`timeout` 由 `ConfigurationUtils.reCalShutdownTime` 按停机窗口比例重算。`doClose()` 本身**不再声明 `throws Throwable`**（2.7.x 有），内部每一步各自 try-catch 并记日志，最后清空 `channels`。

`getChannels()` 的语义变化最容易被忽略：

| 版本 | 行为 |
| :--- | :--- |
| 2.7.x | 遍历 `channels.values()`，**过滤** `isConnected()`，并 `channels.remove(...)` 顺手清理死链，返回 `HashSet` |
| 3.3.6 | `new ArrayList<>(channels.values())`——**不过滤、不清理** |

也就是说 3.3.6 把「过滤死链」的职责从 `getChannels()` 挪走了。调用方如果依赖「拿到的都是活连接」，需要自己判断 `isConnected()`。新增的 `getChannelsSize()`（`:241-244`）返回 map 全量大小，不受此影响。

### metrics Reporting

3.3.6 在 `doOpen` 末尾新增了 Netty 分配器指标上报，共 **8 项**，全部读同一个 `PooledByteBufAllocator.DEFAULT`：

```java
// dubbo-remoting/dubbo-remoting-netty4/src/main/java/org/apache/dubbo/remoting/transport/netty4/NettyServer.java:121-124,144-151
if (isSupportMetrics()) {
    ApplicationModel applicationModel = ApplicationModel.defaultModel();
    MetricsEventBus.post(NettyEvent.toNettyEvent(applicationModel), () -> {
        Map<String, Long> dataMap = new HashMap<>();
        dataMap.put(MetricsKey.NETTY_ALLOCATOR_HEAP_MEMORY_USED.getName(),
                PooledByteBufAllocator.DEFAULT.metric().usedHeapMemory());
        // ... 另有 6 项 arena / cache 指标
        dataMap.put(MetricsKey.NETTY_ALLOCATOR_CHUNK_SIZE.getName(),
                (long) PooledByteBufAllocator.DEFAULT.chunkSize());
        return dataMap;
    });
}
```

| 指标 key 后缀 | 取值方法 |
| :--- | :--- |
| `HEAP_MEMORY_USED` / `DIRECT_MEMORY_USED` | `PooledByteBufAllocator.DEFAULT.metric().used*Memory()` |
| `HEAP_ARENAS_NUM` / `DIRECT_ARENAS_NUM` | `num* Arenas()` |
| `NORMAL_CACHE_SIZE` / `SMALL_CACHE_SIZE` | `normalCacheSize()` / `smallCacheSize()` |
| `THREAD_LOCAL_CACHES_NUM` / `CHUNK_SIZE` | `numThreadLocalCaches()` / `chunkSize()` |

上报本身用 `isSupportMetrics()` 做类存在性探测（`ClassUtils.isPresent("io.netty.buffer.PooledByteBufAllocatorMetric")`，`:153-155`）——**是否上报取决于 Netty 4.1.75+ 是否带该类**，老版本 Netty 会静默跳过，不是异常。指标体系详见 [Metrics.md](/docs/CS/Framework/Dubbo/Metrics.md)。

> [!NOTE]
> 上报取的是 `ApplicationModel.defaultModel()`，而不是 `getUrl().getOrDefaultApplicationModel()`。在多应用模型下这是已知的不精确点。

## `NettyClient` and `NettyChannel`

`NettyClient extends AbstractClient`，`doOpen` 只做两件事——建 handler、建 `Bootstrap`，真正的连接在 `doConnect`：

```java
// dubbo-remoting/dubbo-remoting-netty4/src/main/java/org/apache/dubbo/remoting/transport/netty4/NettyClient.java:60,72-75,82-84,98-104
public class NettyClient extends AbstractClient {

    private static final GlobalResourceInitializer<EventLoopGroup> EVENT_LOOP_GROUP = new GlobalResourceInitializer<>(
            () -> eventLoopGroup(Constants.DEFAULT_IO_THREADS, "NettyClientWorker"),
            EventExecutorGroup::shutdownGracefully);

    private Bootstrap bootstrap;

    private volatile Channel channel;

    public NettyClient(final URL url, final ChannelHandler handler) throws RemotingException {
        // the handler will be wrapped: MultiMessageHandler->HeartbeatHandler->handler
        super(url, wrapChannelHandler(url, handler));
    }

    @Override
    protected void doOpen() throws Throwable {
        final NettyClientHandler nettyClientHandler = createNettyClientHandler();
        bootstrap = new Bootstrap();
        initBootstrap(nettyClientHandler);
    }
```

三个要点：

- **EventLoopGroup 是全进程共享的**：`GlobalResourceInitializer` 持有单例 + `EventExecutorGroup::shutdownGracefully` 释放钩子，不是每个 client 一个线程池。客户端的 IO 线程数也用 `DEFAULT_IO_THREADS`，但**不读 `iothreads` 参数**。
- **一个 client 只有一条连接**：`channel` 字段是 `volatile` 单值，`doConnect` 每次成功都用新 channel 替换并关掉旧 channel（源码注释写明 "Each successful invocation of doConnect() will replace this with new channel and close old channel"）。多 Reference 的连接复用规则见 [ThreadPool.md](/docs/CS/Framework/Dubbo/ThreadPool.md?id=multiple-references-share-one-connection-by-default)。
- **业务线程池不是它创建的**：`initExecutor` 在 `AbstractClient.java:145-156`，把 `THREADPOOL_KEY` 补上 `DEFAULT_CLIENT_THREADPOOL`（即 `cached`）后交给 `ExecutorRepository` 全局创建，**全应用共享一个池**。这就是消费端线程池默认 `cached` 的来源。

`initBootstrap` 的 client 侧 pipeline 是 `negotiation`（**条件性**，仅 `sslContext != null` 时加）→ `decoder` → `encoder` → `client-idle-handler`（`IdleStateHandler(heartbeatInterval, 0, 0)`，只写空闲触发心跳）→ `handler`。与 server 端相反，client 端仍受 `SslContexts.buildClientSslContext(getUrl())` 是否返回非空控制。它还支持 SOCKS5 代理：若配置了 `socksProxyHost` 且目标地址不是本机，则 `pipeline().addFirst(new Socks5ProxyHandler(...))`，默认端口 `1080`。

### NettyChannel.send and the Semantics of sent

```java
// dubbo-remoting/dubbo-remoting-netty4/src/main/java/org/apache/dubbo/remoting/transport/netty4/NettyChannel.java:191-232
@Override
public void send(Object message, boolean sent) throws RemotingException {
    super.send(message, sent);                    // 父类先做关闭检查
    boolean success = true;
    int timeout = 0;
    ByteBuf buf = null;
    try {
        Object outputMessage = message;
        if (!encodeInIOThread) {                  // 非 IO 线程则先编码
            buf = channel.alloc().buffer();
            ChannelBuffer buffer = new NettyBackedChannelBuffer(buf);
            codec.encode(this, buffer, message);
            outputMessage = buf;
        }
        ChannelFuture future = writeQueue.enqueue(outputMessage).addListener((ChannelFutureListener) f -> {
            if (!(message instanceof Request)) {
                return;                            // 仅 Request 回调
            }
            ChannelHandler handler = getChannelHandler();
            if (f.isSuccess()) {
                handler.sent(NettyChannel.this, message);
            } else {
                Throwable t = f.cause();
                if (t == null) {
                    return;
                }
                // 写失败转成 error response，走正常的 received 分发
                Response response = buildErrorResponse((Request) message, t);
                handler.received(NettyChannel.this, response);
            }
        });
        if (sent) {                                // sent=true 才阻塞等待
            timeout = getUrl().getPositiveParameter(TIMEOUT_KEY, DEFAULT_TIMEOUT);
            success = future.await(timeout);
        }
        Throwable cause = future.cause();
        if (cause != null) {
            throw cause;
        }
    } catch (Throwable e) {
        removeChannelIfDisconnected(channel);
        if (buf != null) {
            ReferenceCountUtil.safeRelease(buf);   // 防止 ByteBuf 泄漏
        }
        throw new RemotingException(...);
    }
```

| `sent` | 行为 | 超时来源 |
| :--- | :--- | :--- |
| `true` | `future.await(timeout)` **阻塞等待**写完成 | `TIMEOUT_KEY`（URL 参数 `timeout`），走 `getPositiveParameter` |
| `false` | 注册 listener 后**立即返回**，靠 listener 回调 | 不等待 |

`sent` 的语义是**「是否等这一笔写完」**，不是「是否等业务响应」。业务响应由 `DefaultFuture` + 时间轮处理，属 [Protocol.md](/docs/CS/Framework/Dubbo/Protocol.md?id=timeout-mechanism-time-wheel-timer-not-a-scanning-thread) 的范畴。

> [!TIP]
> `sent` 默认值来自 URL 参数 `Constants.SENT_KEY`，见 `AbstractPeer.send(Object)`：`send(message, url.getParameter(SENT_KEY, false))`——**默认 `false`（异步）**。

listener 里只有 `Request` 才回调（`:208`）。写失败时不是抛异常，而是**构造一个 error response 走 `handler.received()`**，让上层按正常的错误响应处理，这是 Dubbo 把「写失败」与「读失败」统一到一套 handler 语义里的关键设计。

`!encodeInIOThread` 分支是**在业务线程里提前编码**：`NettyBackedChannelBuffer` 把 Dubbo 的 `ChannelBuffer` 包装到 Netty 的 `ByteBuf` 上，让 `codec.encode` 直接写出字节，IO 线程只做搬运。`writeQueue` 是 `Netty4BatchWriteQueue`（继承 `BatchExecutorQueue`），提供 `enqueue` 批量写能力。

### Codec Adaptation Layer

`NettyCodecAdapter`（`NettyCodecAdapter.java:37-60`）是 `Codec2` 与 Netty pipeline 之间的桥，`final class`，构造时同时创建 `InternalEncoder`（`extends MessageToByteEncoder`）与 `InternalDecoder`（`extends ByteToMessageDecoder`），由 `getEncoder()` / `getDecoder()` 取出后放进 pipeline。

`Codec2` 实例从哪来：`AbstractEndpoint.getChannelCodec(url)`（`AbstractEndpoint.java:48-60`）——读 URL 参数 `codec`，**为空则直接用协议名**（因为 Dubbo 约定 codec 扩展名与协议名相同），先去 `Codec2` 扩展里找，找不到再退 `Codec` 扩展。`NettyBackedChannelBuffer` / `NettyBackedChannelBufferFactory` 则是 `Buffer` 体系对 Netty `ByteBuf` 的适配，让上层（`Codec2` 实现、`Payload` 检查）不必认识 Netty 类型。

## New Extension Points in 3.x

### ChannelHandlers.wrap Chain

`NettyServer` / `NettyClient` 构造时都会把业务 handler 包一层，顺序是**从外到内** `MultiMessageHandler` → `HeartbeatHandler` → `Dispatcher 包装后的 handler`：

```java
// dubbo-remoting/dubbo-remoting-api/src/main/java/org/apache/dubbo/remoting/transport/dispatcher/ChannelHandlers.java:42-50
protected ChannelHandler wrapInternal(ChannelHandler handler, URL url) {
    return new MultiMessageHandler(new HeartbeatHandler(url.getOrDefaultFrameworkModel()
            .getExtensionLoader(Dispatcher.class)
            .getAdaptiveExtension()
            .dispatch(handler, url)));
}
```

`MultiMessageHandler` 处理组合请求（一次请求携带多个子请求），`HeartbeatHandler` 收发心跳，`Dispatcher` 决定哪些事件进业务线程池——**三层的注册顺序与执行顺序正好相反**，这是读 pipeline 时的常见困惑点。`Dispatcher` 的五种派发模型见 [ThreadPool.md](/docs/CS/Framework/Dubbo/ThreadPool.md)。

### ConnectionManager: Connection-Level Management

3.x 新增的 `ConnectionManager` SPI，用于 Triple / 端口复用这类需要「在一条连接上跑多路协议」的场景：

```java
// dubbo-remoting/dubbo-remoting-api/src/main/java/org/apache/dubbo/remoting/api/connection/ConnectionManager.java:25-31
@SPI(scope = ExtensionScope.FRAMEWORK)
public interface ConnectionManager {

    AbstractConnectionClient connect(URL url, ChannelHandler handler);

    void forEachConnection(Consumer<AbstractConnectionClient> connectionConsumer);
}
```

两份注册文件（SPI 全名为 `org.apache.dubbo.remoting.api.connection.ConnectionManager`）：

| 文件所在模块 | 注册的扩展名 |
| :--- | :--- |
| `dubbo-remoting-api` | `multiple` → `MultiplexProtocolConnectionManager`；`single` → `SingleProtocolConnectionManager` |
| `dubbo-remoting-netty4` | `netty4` = `netty` → `NettyConnectionManager` |

`NettyConnectionManager` 的实现极简：`connect` 返回 `new NettyConnectionClient(url, handler)`，`forEachConnection` **是空实现（Do nothing）**。netty4 模块下同样只有 `netty` / `netty4` 两个别名。netty4 侧对应的连接级类是 `NettyConnectionClient` / `AbstractNettyConnectionClient` / `NettyConnectionHandler`，它们在 pipeline 里额外插入 HTTP/2 的 `Http2FrameCodec` 与 preface promise，用于多路复用。

### NettyPortUnificationTransporter: Single Port Multiple Protocols

`PortUnificationTransporter` 是 `Transporter` 之外的**独立 SPI**，专门做端口统一，注册在 `org.apache.dubbo.remoting.api.pu.PortUnificationTransporter`（netty4 模块注册 `netty4`，netty3 模块注册 `netty3`）：

```java
// dubbo-remoting/dubbo-remoting-netty4/src/main/java/org/apache/dubbo/remoting/transport/netty4/NettyPortUnificationTransporter.java:29-43
public class NettyPortUnificationTransporter implements PortUnificationTransporter {

    public static final String NAME = "netty4";

    @Override
    public AbstractPortUnificationServer bind(URL url, ChannelHandler handler) throws RemotingException {
        return new NettyPortUnificationServer(url, handler);
    }

    @Override
    public AbstractConnectionClient connect(URL url, ChannelHandler handler) throws RemotingException {
        ConnectionManager manager = url.getOrDefaultFrameworkModel()
                .getExtensionLoader(ConnectionManager.class)
                .getExtension(MultiplexProtocolConnectionManager.NAME);
        return manager.connect(url, handler);
    }
}
```

注意 `connect` 侧不是走自身的 `ConnectionManager` 实现，而是**硬编码取 `MultiplexProtocolConnectionManager`**——与 `NettyConnectionManager.NAME = "netty4"` 是两条不同的扩展路径，不要混。触发路径是 `HeaderExchanger.bind` 里读 `IS_PU_SERVER_KEY`；DubboProtocol 与 Triple 共用端口的完整机制见 [Triple.md](/docs/CS/Framework/Dubbo/Triple.md?id=port-and-single-port-multi-protocol)。

### Other New Classes in 3.x

| 类 | 作用 |
| :--- | :--- |
| `NettyConfigOperator` / `NettySslContextOperator` / `ssl/SslContexts` | 动态配置调整与 SSL 上下文构建缓存 |
| `ssl/aot/`、`http2/`、`logging/` | AOT 预置 SSL 上下文、HTTP/2 handler、日志桥接 |
| `AddressUtils` / `ChannelAddressAccessor` | 地址工具 |

## Default Value Summary Table

| 项 | 默认值 | 来源 |
| :--- | :--- | :--- |
| `Transporter` 扩展名 / scope | `netty` / `FRAMEWORK` | `Transporter.java:32` |
| 注册的扩展名 | `netty`、`netty4`、`netty3` | 2 份 SPI 文件 |
| `DEFAULT_TRANSPORTER` / `DEFAULT_REMOTING_CLIENT` / `DEFAULT_EXCHANGER` | `netty` / `netty` / `header` | `remoting/Constants.java:110,106,114` |
| server worker / boss IO 线程 | `min(CPU+1, 32)` / `1` | `remoting/Constants.java:118`（走 `getPositiveParameter`）；`NettyServer.java:153-155` |
| client IO 线程 | `min(CPU+1, 32)` | `NettyClient.java:72-75`，**不读 `iothreads`** |
| server / client `SO_KEEPALIVE` | `false` / `true` | `NettyServer.java:168`；`NettyClient.initBootstrap` 硬编码 |
| `heartbeat` | `60000` ms | `remoting/Constants.java:157` |
| `heartbeat.timeout`（idle） | `heartbeat * 3` | `UrlUtils.java:62-70` |
| `close.timeout` | 回落 `idleTimeout` | `UrlUtils.java:40-60` |
| `sent` | `false` | `AbstractPeer.send(Object)` 读 `SENT_KEY` |
| 消费端线程池 | `cached` | `CommonConstants.java:135`，`AbstractClient.java:155` |
| 停机 `quietPeriod` | `min(2000, timeout)` | `NettyServer.java:230` |
| SOCKS5 默认端口 | `1080` | `NettyClient.java:66` |

## Pitfall List

| 直觉写法 / 印象 | 源码实际 | 后果 |
| :--- | :--- | :--- |
| 「Dubbo 有 netty / netty4 / mina 三个实现」 | `netty` 与 `netty4` 同一个类；`mina` 已彻底移除 | 引入不存在的依赖；升级后 mina 配置失效 |
| 「`transporter=netty4` 才能启用 Netty 4」 | `netty` 本就指向 netty4 | 改配置无任何效果 |
| 「`Transporters.connectAsync` 提供异步建连」 | 3.3.6 全部主源码 0 命中 | 方法不存在，编译失败 |
| 「`NettyServer` 是 `AbstractServer` 且显式 `implements RemotingServer`」 | `extends AbstractServer`（父类已实现该接口） | 源码对照时误判为缺少实现 |
| 「server 端 SSL 由 `SSL_ENABLED_KEY` 控制」 | 无条件 `addLast("negotiation", new SslServerTlsHandler(...))` | 以为关掉了实际仍在 pipeline 上 |
| 「`NettyServer` 用 `getIdleTimeout` 且 FIXME 未解决」 | 已改 `getCloseTimeout`，FIXME 已删 | 调错参数名，idle 超时不生效 |
| 「`getHeartbeat` 只读 URL 参数」 | 先读系统属性 `DUBBO_HEARTBEAT_CONFIG_KEY` | 容器环境算出错误的 idle 超时 |
| 「`getChannels()` 返回的都是活连接」 | 3.3.6 是 `new ArrayList<>(values())`，不过滤不清理 | 把死链当活链用 |
| 「`NettyClient.doClose() throws Throwable`」 | `doClose()` 无 `throws`，内部逐段 catch | 覆写时签名对不上 |
| 「`shutdownGracefully()` 无参即可」 | 3.3.6 用 `(quietPeriod, timeout, MILLISECONDS)` | 停机时机不可控，消息被截断 |
| 「每个 `NettyClient` 有独立 IO 线程池」 | `GlobalResourceInitializer` 全进程单例 | 客户端连接数评估失真 |
| 「调 `iothreads` 可优化客户端 IO 线程」 | client 侧不读该参数，只有 server 侧读 | 优化无效 |
| 「server / client 的 `SO_KEEPALIVE` 默认一致」 | server 默认 `false`，client 默认 `true` | 长连接存活行为两端不对称 |
| 「`iothreads=0` 会建 0 个线程」 | `getPositiveParameter` 回落 `min(CPU+1, 32)` | 与其他 `threads` 参数语义不一致 |
| 「`ConnectionManager` 与 `NettyConnectionManager` 是同一个 SPI 名」 | SPI 文件名是 `...api.connection.ConnectionManager`；`NettyPortUnificationTransporter.connect` 硬编码取 `MultiplexProtocolConnectionManager` | 找错扩展名，拿到非预期实现 |
| 「端口复用走 `Transporter`」 | 走独立 SPI `PortUnificationTransporter`，由 `ispuserver` 触发 | 改造端口复用逻辑时改错层 |
| 「`NettyTransporter` 里有连接池和重试」 | 只有两行 `new NettyServer` / `new NettyClient` | 在错误层次做连接治理 |

## Links

- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)
- [remoting](/docs/CS/Framework/Dubbo/remoting.md)
- [ThreadPool](/docs/CS/Framework/Dubbo/ThreadPool.md?id=consumer-thread-model)
- [Triple](/docs/CS/Framework/Dubbo/Triple.md?id=port-and-single-port-multi-protocol)
- [Protocol](/docs/CS/Framework/Dubbo/Protocol.md?id=codec2-system-and-current-registration-status)
- [Metrics](/docs/CS/Framework/Dubbo/Metrics.md)

## References

1. [Apache Dubbo Remoting 模块源码](https://github.com/apache/dubbo/tree/3.3.6/dubbo-remoting)
2. [dubbo-remoting-netty4 模块源码](https://github.com/apache/dubbo/tree/3.3.6/dubbo-remoting/dubbo-remoting-netty4)
