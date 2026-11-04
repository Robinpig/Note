## Introduction

本页（文件名 `TPO` 为历史命名）记录 **TCP Fast Open（TFO，TCP 快速打开）在 Netty 中的支持**。TCP 协议侧的 TFO 握手、Fast Open Cookie 选项（Kind=34）与 TFO RT 见 [TCP Fast Open](/docs/CS/CN/TCP/TCP.md?id=fast-open)。

回顾 TFO 解决的问题：标准 TCP 三次握手完成前不能携带应用数据，短连接每次都要付出一个 RTT 的握手代价。TFO 允许客户端在**首次握手之后**，于 SYN 包中就携带数据（前提是握有服务器此前下发的 Fast Open Cookie），从而把"握手 + 首包"合并，为频繁短连接省去一个 RTT；首次连接仍走正常三次握手并申领 Cookie。

本文以 **Netty 4.2.19.Final**（git tag `netty-4.2.19.Final`，commit `64cc10f`）源码为准。epoll transport 的 Java 源码在 **`transport-classes-epoll`**（`transport-classes-epoll/src/main/java/io/netty/channel/epoll/`），`transport-native-epoll` 只放 JNI 的 C 源码与测试。

## Netty Support Scope

Netty 对 TFO 的支持**依赖操作系统原生能力，只有 native epoll transport 可用**：

- **Linux + `netty-transport-native-epoll`**：最主要、生产可用的路径，通过 `EpollServerSocketChannel` / `EpollSocketChannel` 开启，底层 `setsockopt(IPPROTO_TCP, TCP_FASTOPEN / TCP_FASTOPEN_CONNECT, ...)`。
- **NIO transport 不支持**：`ChannelOption.TCP_FASTOPEN` / `TCP_FASTOPEN_CONNECT` 虽然定义在核心 `transport` 模块，但 `NioSocketChannelConfig` / `NioServerSocketChannelConfig` **不处理**这两个 option，JDK 的 `StandardSocketOptions` 里也没有对应项。所以 `NioServerSocketChannel` 上设这个 option 是无效的，必须换到 epoll（Linux）。
- 操作系统/内核也要启用，见 [Kernel Prerequisites](/docs/CS/Framework/Netty/TPO.md?id=kernel-prerequisites)。

### Option Names

> [!NOTE]
>
> 4.2.19 里 **TFO 的规范写法是 `io.netty.channel.ChannelOption` 上的常量**，`EpollChannelOption` 上的两个同名常量已经标 `@Deprecated`。
>
> 源码：`transport-classes-epoll/src/main/java/io/netty/channel/epoll/EpollChannelOption.java:37`
>
> ```java
> // 源码：transport-classes-epoll/src/main/java/io/netty/channel/epoll/EpollChannelOption.java:37
> /**
>  * @deprecated Use {@link ChannelOption#TCP_FASTOPEN} instead.
>  */
> @Deprecated
> public static final ChannelOption<Integer> TCP_FASTOPEN = ChannelOption.TCP_FASTOPEN;
>
> /**
>  * @deprecated Use {@link ChannelOption#TCP_FASTOPEN_CONNECT} instead.
>  */
> @Deprecated
> public static final ChannelOption<Boolean> TCP_FASTOPEN_CONNECT = ChannelOption.TCP_FASTOPEN_CONNECT;
> ```
>
> 两者指向**同一个对象**（直接赋值，不是 `valueOf` 新建），所以行为完全一致，只是 `EpollChannelOption` 上的引用被废弃了。新代码请用 `ChannelOption.TCP_FASTOPEN` / `ChannelOption.TCP_FASTOPEN_CONNECT`。

| 常量                                    | 定义位置                                                                    | 类型                     | 用途              |
| :------------------------------------- | :---------------------------------------------------------------------- | :--------------------- | :-------------- |
| `ChannelOption.TCP_FASTOPEN`           | `transport/src/main/java/io/netty/channel/ChannelOption.java:146`        | `ChannelOption<Integer>` | **服务端**：TFO 队列长度 |
| `ChannelOption.TCP_FASTOPEN_CONNECT`   | `transport/src/main/java/io/netty/channel/ChannelOption.java:141`        | `ChannelOption<Boolean>` | **客户端**：是否启用 TFO |
| `EpollChannelOption.TCP_FASTOPEN`      | `.../epoll/EpollChannelOption.java:41`                                  | 同上，**已废弃别名**           | —               |
| `EpollChannelOption.TCP_FASTOPEN_CONNECT` | `.../epoll/EpollChannelOption.java:47`                                | 同上，**已废弃别名**           | —               |

`ChannelOption` 上的 javadoc 也明确分了工（源码：`transport/src/main/java/io/netty/channel/ChannelOption.java:139`）：

```java
// 源码：transport/src/main/java/io/netty/channel/ChannelOption.java:139
/**
 * Client-side TCP FastOpen. Sending data with the initial TCP handshake.
 */
public static final ChannelOption<Boolean> TCP_FASTOPEN_CONNECT = valueOf("TCP_FASTOPEN_CONNECT");

/**
 * Server-side TCP FastOpen. Configures the maximum number of outstanding (waiting to be accepted) TFO connections.
 */
public static final ChannelOption<Integer> TCP_FASTOPEN = valueOf(ChannelOption.class, "TCP_FASTOPEN");
```

另外：**4.2.19 中没有 `TcpFastOpen` 这个类**。早期资料里提到的 `io.netty.channel.epoll.TcpFastOpen`（一个只有几个静态常量的 holder）在当前源码树里不存在，能力探测改由 `Epoll` 上的静态方法提供。

### Availability Checks

能力探测在 `Epoll` 上（源码：`transport-classes-epoll/src/main/java/io/netty/channel/epoll/Epoll.java:111`）：

```java
// 源码：transport-classes-epoll/src/main/java/io/netty/channel/epoll/Epoll.java:111
public static boolean isTcpFastOpenClientSideAvailable() {
    return isAvailable() && Native.IS_SUPPORTING_TCP_FASTOPEN_CLIENT;
}

// 源码：.../Epoll.java:121
public static boolean isTcpFastOpenServerSideAvailable() {
    return isAvailable() && Native.IS_SUPPORTING_TCP_FASTOPEN_SERVER;
}
```

两个方法都要求「epoll 本身可用」**且**「内核 sysctl 打开了对应方向」。`Native` 侧的掩码（源码：`transport-classes-epoll/src/main/java/io/netty/channel/epoll/Native.java:126`）：

```java
// 源码：transport-classes-epoll/src/main/java/io/netty/channel/epoll/Native.java:126
private static final int TFO_ENABLED_CLIENT_MASK = 0x1;
private static final int TFO_ENABLED_SERVER_MASK = 0x2;
private static final int TCP_FASTOPEN_MODE = tcpFastopenMode();

static final boolean IS_SUPPORTING_TCP_FASTOPEN_CLIENT =
        (TCP_FASTOPEN_MODE & TFO_ENABLED_CLIENT_MASK) == TFO_ENABLED_CLIENT_MASK;

static final boolean IS_SUPPORTING_TCP_FASTOPEN_SERVER =
        (TCP_FASTOPEN_MODE & TFO_ENABLED_SERVER_MASK) == TFO_ENABLED_SERVER_MASK;
```

`Native.IS_SUPPORTING_TCP_FASTOPEN`（源码：`...:146`，指向 `Native.java`）也已 **`@Deprecated`**，javadoc 要求改用上面两个 `Epoll` 方法——因为合并的布尔值分不清「客户端可用」还是「服务端可用」。

## Server Side

服务端通过 `ChannelOption.TCP_FASTOPEN` 开启，参数是一个整数，含义是**允许同时处于「SYN 已收、三次握手未完成」状态的 TFO 请求数上限**（源码注释叫 `pendingFastOpenRequestsThreshold`，语义接近 listen backlog 但不是同一个值）：

```java
EventLoopGroup boss = new EpollEventLoopGroup(1);
EventLoopGroup worker = new EpollEventLoopGroup();

ServerBootstrap b = new ServerBootstrap();
b.group(boss, worker)
 .channel(EpollServerSocketChannel.class)                // 必须是 epoll，NioXxx 不支持
 .option(ChannelOption.TCP_FASTOPEN, 256)                // pendingFastOpenRequestsThreshold
 .childHandler(new ChannelInitializer<EpollSocketChannel>() {
     @Override
     protected void initChannel(EpollSocketChannel ch) {
         ch.pipeline().addLast(new MyBusinessHandler());
     }
 });
```

对应的配置方法（源码：`transport-classes-epoll/src/main/java/io/netty/channel/epoll/EpollServerChannelConfig.java:155`）——注意方法名是小写的 **`setTcpFastopen`**（不是 `setTcpFastOpen`）：

```java
// 源码：transport-classes-epoll/src/main/java/io/netty/channel/epoll/EpollServerChannelConfig.java:143
public int getTcpFastopen() {
    return pendingFastOpenRequestsThreshold;
}

/**
 * Enables tcpFastOpen on the server channel. If the underlying os doesn't support TCP_FASTOPEN setting this has no
 * effect. This has to be set before doing listen on the socket otherwise this takes no effect.
 *
 * @param pendingFastOpenRequestsThreshold number of requests to be pending for fastopen at a given point in time
 * for security.
 *
 * @see <a href="https://tools.ietf.org/html/rfc7413#appendix-A.2">RFC 7413 Passive Open</a>
 */
public EpollServerChannelConfig setTcpFastopen(int pendingFastOpenRequestsThreshold) {
    this.pendingFastOpenRequestsThreshold = checkPositiveOrZero(pendingFastOpenRequestsThreshold,
            "pendingFastOpenRequestsThreshold");
    return this;
}
```

**真正下发给内核的时机在 `doBind`**（源码：`transport-classes-epoll/src/main/java/io/netty/channel/epoll/EpollServerSocketChannel.java:77`）：

```java
// 源码：transport-classes-epoll/src/main/java/io/netty/channel/epoll/EpollServerSocketChannel.java:77
@Override
protected void doBind(SocketAddress localAddress) throws Exception {
    super.doBind(localAddress);
    final int tcpFastopen;
    if (IS_SUPPORTING_TCP_FASTOPEN_SERVER && (tcpFastopen = config.getTcpFastopen()) > 0) {
        socket.setTcpFastOpen(tcpFastopen);
    }
    socket.listen(config.getBacklog());
    active = true;
    // We now listen for new connections, submit the ops so we receive events.
    submitCurrentOps();
}
```

三点值得注意：

1. **顺序是 bind → `setTcpFastOpen` → `listen`**。javadoc 里那句 "This has to be set before doing listen on the socket otherwise this takes no effect" 就是这个意思：`TCP_FASTOPEN` 是 `setsockopt` 到已 bind 的监听 fd 上，必须在 `listen()` 之前设。所以只能通过 `ServerBootstrap.option(...)`（在 bind 前生效）设置，**bind 之后再 set 就无效了**。
2. **阈值必须 `> 0` 才下发**。`getTcpFastopen()` 默认 0，即默认关闭；`checkPositiveOrZero` 保证不能给负数。
3. 若内核不支持（`IS_SUPPORTING_TCP_FASTOPEN_SERVER == false`），整个分支被跳过，**静默降级**为普通监听，不报错。

`LinuxSocket.setTcpFastOpen(int)`（源码：`transport-classes-epoll/src/main/java/io/netty/channel/epoll/LinuxSocket.java:188`）是 JNI 方法，最终落到（源码：`transport-native-epoll/src/main/c/netty_epoll_linuxsocket.c:230`）：

```c
// 源码：transport-native-epoll/src/main/c/netty_epoll_linuxsocket.c:230
netty_unix_socket_setOption(env, fd, IPPROTO_TCP, TCP_FASTOPEN, &optval, sizeof(optval));
```

首次连接时服务器在 SYN-ACK 中下发 Cookie；之后客户端在 SYN 中带 Cookie 与数据，服务器验证通过即可在握手阶段把数据交付应用。

## Client Side

客户端用 `ChannelOption.TCP_FASTOPEN_CONNECT`（布尔值）开启，配合 `EpollSocketChannel`：

```java
Bootstrap b = new Bootstrap();
b.group(new EpollEventLoopGroup())
 .channel(EpollSocketChannel.class)
 .option(ChannelOption.TCP_FASTOPEN_CONNECT, true)
 .handler(new ChannelInitializer<EpollSocketChannel>() {
     @Override
     protected void initChannel(EpollSocketChannel ch) {
         ch.pipeline().addLast(new MyClientHandler());
     }
 });
```

配置方法（源码：`transport-classes-epoll/src/main/java/io/netty/channel/epoll/EpollSocketChannelConfig.java:592`）：

```java
// 源码：transport-classes-epoll/src/main/java/io/netty/channel/epoll/EpollSocketChannelConfig.java:592
public EpollSocketChannelConfig setTcpFastOpenConnect(boolean fastOpenConnect) {
    tcpFastopen = fastOpenConnect;
    return this;
}

// 源码：.../EpollSocketChannelConfig.java:600
public boolean isTcpFastOpenConnect() {
    return tcpFastopen;
}
```

关键实现在 `EpollSocketChannel.doConnect0`（源码：`transport-classes-epoll/src/main/java/io/netty/channel/epoll/EpollSocketChannel.java:134`）：

```java
// 源码：transport-classes-epoll/src/main/java/io/netty/channel/epoll/EpollSocketChannel.java:134
@Override
boolean doConnect0(SocketAddress remote) throws Exception {
    if (IS_SUPPORTING_TCP_FASTOPEN_CLIENT && config.isTcpFastOpenConnect()) {
        ChannelOutboundBuffer outbound = unsafe().outboundBuffer();
        outbound.addFlush();
        Object curr;
        if ((curr = outbound.current()) instanceof ByteBuf) {
            ByteBuf initialData = (ByteBuf) curr;
            // If no cookie is present, the write fails with EINPROGRESS and this call basically
            // becomes a normal async connect. All writes will be sent normally afterwards.
            long localFlushedAmount = doWriteOrSendBytes(
                    initialData, (InetSocketAddress) remote, true);
            if (localFlushedAmount > 0) {
                // We had a cookie and our fast-open proceeded. Remove written data
                // then continue with normal TCP operation.
                outbound.removeBytes(localFlushedAmount);
                return true;
            }
        }
    }
    return super.doConnect0(remote);
}
```

这段解释了 TFO 客户端的两个使用前提和一条兜底路径：

- **必须有已 flush 的 `ByteBuf` 才能带上数据**：`outbound.addFlush()` 后取 `outbound.current()`，只有它是 `ByteBuf` 才有"首包数据"可塞进 SYN。**在 `channelActive` 里写首包是来不及的**——那时 connect 已经走完，只能先 `write` 再 `connect`。
- **无 Cookie 时自动降级**：注释明确写了 "If no cookie is present, the write fails with EINPROGRESS and this call basically becomes a normal async connect"——首次连接（或 Cookie 过期）拿不到 `localFlushedAmount > 0`，于是退回普通异步 connect，后续写正常发送。**这个降级对应用完全透明，不需要业务代码处理**。
- `localFlushedAmount > 0` 表示 TFO 真的生效了，此时把已随 SYN 发出去的字节从 outbound buffer 里摘掉，之后走正常 TCP 数据流。

官方测试给出了"先写后连"的准确写法（源码：`testsuite/src/main/java/io/netty/testsuite/transport/socket/SocketConnectTest.java:253`）：

```java
// 源码：testsuite/src/main/java/io/netty/testsuite/transport/socket/SocketConnectTest.java:253
BufferingClientHandler handler = new BufferingClientHandler();
cb.handler(handler);
ChannelFuture register = cb.register();                          // ① 先 register
Channel channel = register.sync().channel();
ChannelFuture write = channel.write(initialDataFactory.apply(channel));  // ② 再 write（只 write 不 flush）
SocketAddress remoteAddress = sc.localAddress();
ChannelFuture connectFuture = channel.connect(remoteAddress);    // ③ 最后 connect
```

服务端侧的开启（源码：`.../SocketConnectTest.java:301`）：

```java
// 源码：testsuite/src/main/java/io/netty/testsuite/transport/socket/SocketConnectTest.java:301
protected void enableTcpFastOpen(ServerBootstrap sb, Bootstrap cb) {
    // TFO is an almost-pure optimisation and should not change any observable behaviour in our tests.
    sb.option(ChannelOption.TCP_FASTOPEN, 5);
    cb.option(ChannelOption.TCP_FASTOPEN_CONNECT, true);
}
```

测试还覆盖了两个边界：首包带**非零 readerIndex** 的 buffer（`BAD-PREFIX-` 前缀会被跳过）和 **`CompositeByteBuf`** 首包——因为 `doConnect0` 里有 `curr instanceof ByteBuf` 判断，`CompositeByteBuf` 也是 `ByteBuf`，可以正常带出去。

第一次连接没有 Cookie，仍走标准握手并获取 Cookie；内核缓存该 Cookie 后，对同一目的地址的后续连接即可在 SYN 中带数据。Cookie 由内核维护，Netty 侧没有 Cookie 缓存代码。

## Kernel Prerequisites

- **Linux ≥ 3.7**：`TCP_FASTOPEN` socket option 引入。Netty 的 C 源码为兼容老内核做了兜底定义（源码：`transport-native-epoll/src/main/c/netty_epoll_linuxsocket.c:41`）：

  ```c
  // 源码：transport-native-epoll/src/main/c/netty_epoll_linuxsocket.c:41
  // TCP_FASTOPEN is defined in linux 3.7. We define this here so older kernels can compile.
  #ifndef TCP_FASTOPEN
  #define TCP_FASTOPEN 23
  #endif
  ```

- **Linux ≥ 4.11**：客户端侧的 `TCP_FASTOPEN_CONNECT`（`= 30`，源码：`.../netty_epoll_linuxsocket.c:46`）。低于此版本只能当服务端用 TFO。
- **`net.ipv4.tcp_fastopen` 必须打开**：`1` 仅客户端、`2` 仅服务端、`3` 双向开启。Netty **直接读这个 sysctl 来判定能力**（源码：`transport-native-epoll/src/main/c/netty_epoll_native.c:712`）：

  ```c
  // 源码：transport-native-epoll/src/main/c/netty_epoll_native.c:712
  static jint netty_epoll_native_tcpFastopenMode(JNIEnv* env, jclass clazz) {
      int fastopen = 0;
      getSysctlValue("/proc/sys/net/ipv4/tcp_fastopen", &fastopen);
      return fastopen;
  }
  ```

  也就是说，内核开关没打开时 `Native.IS_SUPPORTING_TCP_FASTOPEN_*` 为 false，服务端静默降级、客户端走普通 connect——**不会有任何报错**，这是 TFO"配了没效果"最常见的原因。

```shell
cat /proc/sys/net/ipv4/tcp_fastopen
# 双向开启
sysctl -w net.ipv4.tcp_fastopen=3
```

## Caveats

- 只对**反复建立的短连接**有明显收益；长连接复用（如 HTTP keep-alive、连接池、Netty 长链路）本就没有反复握手，TFO 意义不大。
- TFO 带来安全语义变化：SYN 可携带数据，伪造源地址的 SYN 可能触发服务器处理（依赖 Cookie 验证防滥用）。服务端那个 `pendingFastOpenRequestsThreshold` 正是为此设的——它限定了「握手未完成就已排队」的 TFO 请求数，防止攻击者用海量带数据 SYN 耗尽资源。
- 中间设备/防火墙若丢弃带未知选项的 SYN，会回退为普通握手（兼容性兜底，但收益消失）。
- 部署前确认四项：内核版本（服务端 ≥ 3.7、客户端 ≥ 4.11）、`tcp_fastopen` 开关、native epoll 依赖已加载、`Epoll*Channel` 已正确使用。NIO 与 epoll channel 类型不能混用。
- 用 `Epoll.isTcpFastOpenClientSideAvailable()` / `isTcpFastOpenServerSideAvailable()` 做启动自检，比事后抓包排查高效。
- 相关的握手/连接建立优化还有 TCP Fast Open 之外的 [SYN cookies 防 SYN flood](/docs/CS/CN/TCP/TCP.md)（二者都用到"服务端无状态/编码信息"的思路，但目的不同：TFO 省 RTT，SYN cookies 防半连接攻击）。

## Links

- [TCP Fast Open 协议细节](/docs/CS/CN/TCP/TCP.md?id=fast-open)
- [Linux TCP 实现](/docs/CS/OS/Linux/net/TCP/TCP.md)
- [Netty](/docs/CS/Framework/Netty/Netty.md)
- [Bootstrap 与 transport 选择](/docs/CS/Framework/Netty/Bootstrap.md)

## References

1. [Netty 4.2 Javadoc - ChannelOption](https://netty.io/4.2/api/io/netty/channel/ChannelOption.html)
2. [Netty 4.2 Javadoc - Epoll](https://netty.io/4.2/api/io/netty/channel/epoll/Epoll.html)
3. [Netty native transports (epoll)](https://netty.io/wiki/native-transports.html)
4. [TCP Fast Open (RFC 7413)](https://datatracker.ietf.org/doc/html/rfc7413)
