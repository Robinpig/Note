## Introduction

本页（文件名 `TPO` 为历史命名）记录 **TCP Fast Open（TFO，TCP 快速打开）在 Netty 中的支持**。TCP 协议侧的 TFO 握手、Fast Open Cookie 选项（Kind=34）与 TFO RT 见 [TCP Fast Open](/docs/CS/CN/TCP/TCP.md?id=fast-open)。

回顾 TFO 解决的问题：标准 TCP 三次握手完成前不能携带应用数据，短连接每次都要付出一个 RTT 的握手代价。TFO 允许客户端在**首次握手之后**，于 SYN 包中就携带数据（前提是握有服务器此前下发的 Fast Open Cookie），从而把“握手 + 首包”合并，为频繁短连接省去一个 RTT；首次连接仍走正常三次握手并申领 Cookie。

## Netty Support Scope

Netty 对 TFO 的支持**依赖操作系统原生能力，只有 native transport 可用**：

- **Linux + `netty-transport-native-epoll`**：这是最主要、生产可用的路径，通过 `EpollServerSocketChannel` / `EpollSocketChannel` 开启，底层调用 `TCP_FASTOPEN` / `TCP_FASTOPEN_CONNECT` socket 选项。
- **NIO transport 不支持**：标准 Java NIO 没有暴露 TFO 选项，因此用 `NioServerSocketChannel` 时无法开启，必须切换到 epoll（Linux）。
- 操作系统/内核也要启用：Linux 通过 `net.ipv4.tcp_fastopen` 控制（`1` 仅客户端、`2` 仅服务端、`3` 双向开启）：

```shell
cat /proc/sys/net/ipv4/tcp_fastopen
# 双向开启
sysctl -w net.ipv4.tcp_fastopen=3
```

## Server Side

服务端通过 `EpollChannelOption.TCP_FASTOPEN` 开启，参数是一个整数 backlog（允许在完成三次握手前排队的 TFO 请求数，语义类似 listen backlog）：

```java
EventLoopGroup boss = new EpollEventLoopGroup(1);
EventLoopGroup worker = new EpollEventLoopGroup();

ServerBootstrap b = new ServerBootstrap();
b.group(boss, worker)
 .channel(EpollServerSocketChannel.class)   // 必须是 epoll，NioXxx 不支持
 .option(EpollChannelOption.TCP_FASTOPEN, 256) // backlog
 .childHandler(new ChannelInitializer<EpollSocketChannel>() {
     @Override
     protected void initChannel(EpollSocketChannel ch) {
         ch.pipeline().addLast(new MyBusinessHandler());
     }
 });
```

首次连接时服务器在 SYN-ACK 中下发 Cookie；之后客户端在 SYN 中带 Cookie 与数据，服务器验证通过即可在握手阶段把数据交付应用。

## Client Side

客户端用 `EpollChannelOption.TCP_FASTOPEN_CONNECT`（布尔值）开启，配合 `EpollSocketChannel`：

```java
Bootstrap b = new Bootstrap();
b.group(new EpollEventLoopGroup())
 .channel(EpollSocketChannel.class)
 .option(EpollChannelOption.TCP_FASTOPEN_CONNECT, true)
 .handler(new ChannelInitializer<EpollSocketChannel>() {
     @Override
     protected void initChannel(EpollSocketChannel ch) {
         ch.pipeline().addLast(new MyClientHandler());
     }
 });
```

第一次连接没有 Cookie，仍走标准握手并获取 Cookie；Netty/内核缓存该 Cookie 后，对同一目的地址的后续连接即可在 SYN 中带数据。

## Caveats

- 只对**反复建立的短连接**有明显收益；长连接复用（如 HTTP keep-alive、连接池、Netty 长链路）本就没有反复握手，TFO 意义不大。
- TFO 带来安全语义变化：SYN 可携带数据，伪造源地址的 SYN 可能触发服务器处理（依赖 Cookie 验证防滥用）；中间设备/防火墙若丢弃带未知选项的 SYN，会回退为普通握手（兼容性兜底，但收益消失）。
- 部署前确认内核版本、`tcp_fastopen` 开关、native epoll 依赖与 `Epoll*Channel` 都已正确使用，NIO 与 epoll channel 类型不能混用。
- 相关的握手/连接建立优化还有 TCP Fast Open 之外的 [SYN cookies 防 SYN flood](/docs/CS/CN/TCP/TCP.md)（二者都用到“服务端无状态/编码信息”的思路，但目的不同：TFO 省 RTT，SYN cookies 防半连接攻击）。

## Links

- [TCP Fast Open 协议细节](/docs/CS/CN/TCP/TCP.md?id=fast-open)
- [Linux TCP 实现](/docs/CS/OS/Linux/net/TCP/TCP.md)
- [Netty](/docs/CS/Framework/Netty/Netty.md)
- [Bootstrap 与 transport 选择](/docs/CS/Framework/Netty/Bootstrap.md)

## References

1. [Netty Javadoc - EpollChannelOption (TCP_FASTOPEN / TCP_FASTOPEN_CONNECT)](https://netty.io/4.1/api/io/netty/channel/epoll/EpollChannelOption.html)
2. [Netty native transports (epoll)](https://netty.io/wiki/native-transports.html)
3. [TCP Fast Open (RFC 7413)](https://datatracker.ietf.org/doc/html/rfc7413)
