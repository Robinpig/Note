## Introduction

Java 的 I/O 体系横跨 `java.io`（流式 BIO）、`java.net`（网络端点）、`java.nio`（通道 / 缓冲区 / 选择器）三大包，并在 JDK 7 之后通过 NIO.2（`java.nio.file`、异步通道）统一了文件与网络抽象。

本页是 **IO 子树的枢纽**：向下串起 [NIO](/docs/CS/Java/JDK/IO/NIO.md)（Buffer / Channel / Selector 的多路复用模型）、[Direct Buffer](/docs/CS/Java/JDK/IO/Direct_Buffer.md)（堆外内存的分配、页对齐与 Cleaner 回收）、[io_uring](/docs/CS/Java/JDK/IO/Uring.md)（Linux 异步 I/O 的 Java 侧接入）；向上承接 [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)。从「阻塞流」到「多路复用」再到「真正异步」的演进，是理解现代 Java 网络编程的主线。

## I/O Models

| 模型 | 包 | 阻塞点 | 并发单位 | 典型场景 |
|------|----|--------|----------|----------|
| BIO（流） | `java.io` | 读写阻塞整个线程 | 每连接一线程 | 低并发、简单协议、脚本工具 |
| NIO（多路复用） | `java.nio` | 仅 `Selector.select` 阻塞 | 少量线程 + 事件循环 | 高并发网络（Netty、Web 服务器） |
| AIO（异步） | `java.nio.channels` | 无（回调 / `Future`） | 回调线程池 | 文件大块 I/O、长耗时操作 |

> NIO 在 Linux 上的网络 `Selector` 底层仍是 **epoll**（详见 [Uring](/docs/CS/Java/JDK/IO/Uring.md) 的「JDK Mainline Integration Status」）；AIO 在 Windows 用 **IOCP** 实现，在 Linux 由 epoll 模拟，实践中并未比 NIO 更快——这也是大型项目普遍直接用 Netty 而非原生 AIO 的原因。

## Networking (java.net)

`java.net` 提供两套协议端点抽象：**TCP**（可靠、面向连接）与 **UDP**（无连接、数据报）。其上承载 `Socket` / `ServerSocket` / `DatagramSocket` 与 `InetAddress` 等。

### Socket

`SocketAddress` 是一个不带协议语义的抽象地址基类，通常由具体协议子类化（如 `InetSocketAddress`）后用于绑定、连接或作为返回值。

```java
public abstract class SocketAddress implements java.io.Serializable {

    @java.io.Serial
    static final long serialVersionUID = 5215720748342549866L;

}
```

`InetAddress` 封装一个 32 位（IPv4）或 128 位（IPv6）无符号 IP 地址，可能附带已解析或待解析的主机名。其地址语义由 RFC 790 / RFC 1918 / RFC 2365 / RFC 2373 定义。

### ServerSocket

`ServerSocket` 监听并接受入站连接，`accept()` 阻塞直到连接到达；若安装安全管理器，会调用其 `checkAccept` 校验。JDK 的 `ServerSocket` 在 JDK 14 后改为基于 `NioSocketImpl`（见 [NIO](/docs/CS/Java/JDK/IO/NIO.md)），`accept` 的核心委托如下：

```java
public class ServerSocket implements java.io.Closeable {
  public Socket accept() throws IOException {
    if (isClosed())
      throw new SocketException("Socket is closed");
    if (!isBound())
      throw new SocketException("Socket is not bound yet");
    Socket s = new Socket((SocketImpl) null);
    implAccept(s);
    return s;
  }

  protected final void implAccept(Socket s) throws IOException {
    SocketImpl si = s.impl;

    // Socket has no SocketImpl
    if (si == null) {
      si = implAccept();
      s.setImpl(si);
      s.postAccept();
      return;
    }

    // Socket has a SOCKS or HTTP SocketImpl, need delegate
    if (si instanceof DelegatingSocketImpl) {
      si = ((DelegatingSocketImpl) si).delegate();
      assert si instanceof PlatformSocketImpl;
    }

    // Accept connection with a platform or custom SocketImpl.
    // For the platform SocketImpl case:
    // - the connection is accepted with a new SocketImpl
    // - the SO_TIMEOUT socket option is copied to the new SocketImpl
    // - the Socket is connected to the new SocketImpl
    // - the existing/old SocketImpl is closed
    // For the custom SocketImpl case, the connection is accepted with the
    // existing custom SocketImpl.
    ensureCompatible(si);
    if (impl instanceof PlatformSocketImpl) {
      SocketImpl psi = platformImplAccept();
      si.copyOptionsTo(psi);
      s.setImpl(psi);
      si.closeQuietly();
    } else {
      s.impl = null; // temporarily break connection to impl
      try {
        customImplAccept(si);
      } finally {
        s.impl = si;  // restore connection to impl
      }
    }
    s.postAccept();
  }

}
```

### InetAddress and Caching

`InetAddress` 内置正/负向解析缓存。默认行为：

- 安装安全管理器时，正向解析结果**永久缓存**（防 DNS 欺骗）；
- 未安装时，缓存实现相关的一段有限时间；
- 负向解析（解析失败）缓存约 **10 秒**以提升性能。

两个 Java 安全属性控制 TTL：

- `networkaddress.cache.ttl`：正向缓存秒数，`-1` 表示「永久缓存」；
- `networkaddress.cache.negative.ttl`（默认 `10`）：负向缓存秒数，`0` 表示从不缓存，`-1` 表示永久。

### Address Types

- **unicast**：标识单个接口，发往该地址的包只投递给该接口。
  - **Unspecified Address**（通配 / wildcard）：绝不可分配给任何节点，表示「无地址」，常用于 `bind` 以监听任意接口。
  - **Loopback Addresses**：分配给回环接口，发往该地址的包在本地主机内环回，常用于客户端自测。
- **multicast**：标识一组接口（通常跨不同节点），发往该地址的包投递给所有匹配接口。

#### IP Address Scope

Link-local 地址用于单链路的自动配置 / 邻居发现；Site-local 用于站点内寻址；Global 地址在 Internet 上全局唯一。文本表示因地址族而异（IPv4 见 `Inet4Address#format`，IPv6 见 `Inet6Address#format`）。主机名解析由本地配置与 DNS / NIS 等命名服务共同完成，正反向解析均由 `InetAddress` 提供。

## BIO (java.io)

`java.io` 用**流（stream）**抽象顺序字节序列，所有类位于 `java.io` 包。JVM 自动创建三个标准流：`System.out`（标准输出）、`System.in`（标准输入）、`System.err`（标准错误）。

```java
public abstract class InputStream implements Closeable {

    // MAX_SKIP_BUFFER_SIZE is used to determine the maximum buffer size to
    // use when skipping.
    private static final int MAX_SKIP_BUFFER_SIZE = 2048;

    public abstract int read() throws IOException;
}

public abstract class OutputStream implements Closeable, Flushable {
    public abstract void write(int b) throws IOException;
}
```

### Buffered Stream

`BufferedInputStream` / `BufferedOutputStream` 内置缓冲区以提升批量读写性能。在并发服务器模型中，迭代服务器（iterative server）一次只服务一个客户端；并发服务器（concurrent server）则为每个连接分配线程或交由线程池。

### Read and Write

`InputStream.read()` 返回 `0..255` 的字节，到达流尾返回 `-1`，在无数据可用 / 流尾 / 异常前阻塞。在 `IOUtil.write()` 中，JDK 对缓冲区的写入有统一优化：

1. 若源是 `DirectBuffer`，直接走 `writeFromNativeBuffer`；
2. 否则先从 `getTemporaryDirectBuffer` 拷贝到临时堆外缓冲，再 `writeFromNativeBuffer`。

> 相关基准：[Comparing performance of Java I/O and NIO: streams vs channels](https://github.com/romromov/java-io-benchmark)

## NIO

[Java NIO（New IO）](/docs/CS/Java/JDK/IO/NIO.md) 是标准 Java IO 与网络 API 的替代方案，提供与传统 `java.io` 不同的编程模型：**Buffer + Channel + Selector** 的多路复用，使少量线程即可支撑海量连接。

## AIO

[AIO / AsynchronousChannel](https://hg.openjdk.org/jdk/jdk/file/d8327f838b88/src/java.base/windows/classes/sun/nio/ch/Iocp.java) 在 Windows 上基于 **IOCP** 实现；Linux 没有原生异步文件 I/O，由 epoll 模拟，因此实践中性能并不优于 NIO，且不支持 UDP。

## io_uring

Linux 5.1 引入的 [io_uring](/docs/CS/OS/Linux/IO/io_uring.md) 通过 SQ/CQ 双环形队列批量提交 I/O，JDK 主线尚未内置支持；Java 侧通过 [JUring](/docs/CS/Java/JDK/IO/Uring.md)（基于 FFM API）或 Netty incubator transport 接入，也是补齐 NIO 文件 I/O 阻塞短板的候选方向，详见 [Uring](/docs/CS/Java/JDK/IO/Uring.md)。

## Direct Buffer

直接缓冲区在**堆外（native）**分配，绕过 Java 堆，减少一次内核↔用户空间拷贝，是 NIO 零拷贝与高网络吞吐的关键。其分配、`-XX:MaxDirectMemorySize` 预留、`Cleaner` 回收机制见 [Direct Buffer](/docs/CS/Java/JDK/IO/Direct_Buffer.md)。

## File (java.nio.file)

`java.nio.file`（NIO.2）是 JDK 7 引入的文件系统抽象层，在 Linux 上由 `LinuxFileSystemProvider` / `LinuxFileSystem` 落地：文件打开、目录遍历、属性读取分别映射到 `open(2)` / `getdents64(2)` / `fstatat(2)`，零拷贝走 `copy_file_range`→`sendfile`，目录变更监听则基于 inotify。底层系统调用与 `WatchService` 的 inotify 实现分别见 [NIO.2 File System](/docs/CS/Java/JDK/IO/NIO2.md) 与 [WatchService (inotify)](/docs/CS/Java/JDK/IO/WatchService.md)。异步文件通道 [AsynchronousFileChannel](/docs/CS/Java/JDK/IO/AsyncFileChannel.md) 在 Linux 上**并非内核 AIO**，而是 `ExecutorService` 线程池模拟——与 socket 侧 `EPollPort`（epoll 模拟）同源。

`Files.lines` 以惰性 `Stream<String>` 读取文件，不一次性读入 `List`：

```java
public static Stream<String> lines(Path path, Charset cs) throws IOException {
    // Use the good splitting spliterator if:
    // 1) the path is associated with the default file system;
    // 2) the character set is supported; and
    // 3) the file size is such that all bytes can be indexed by int values
    //    (this limitation is imposed by ByteBuffer)
    if (path.getFileSystem() == FileSystems.getDefault() &&
        FileChannelLinesSpliterator.SUPPORTED_CHARSET_NAMES.contains(cs.name())) {
        FileChannel fc = FileChannel.open(path, StandardOpenOption.READ);

        Stream<String> fcls = createFileChannelLinesStream(fc, cs);
        if (fcls != null) {
            return fcls;
        }
        fc.close();
    }

    return createBufferedReaderLinesStream(Files.newBufferedReader(path, cs));
}
```

## Tuning

原生 NIO / AIO 并不提供断连重连、网络闪断、半包读写、失败缓存、拥塞与异常码流等处理，这些需要开发者自行补齐。实践中 AIO 并不比 NIO 更好——Linux 下它仍是 epoll 模拟，且不支持 UDP。大型互联网项目普遍不直接使用原生 API，而是采用 [Netty](/docs/CS/Framework/Netty/Netty.md) 这类框架。

## Links

- [NIO](/docs/CS/Java/JDK/IO/NIO.md)
- [Selector (epoll)](/docs/CS/Java/JDK/IO/Selector_Epoll.md)
- [NIO.2 File System](/docs/CS/Java/JDK/IO/NIO2.md)
- [WatchService (inotify)](/docs/CS/Java/JDK/IO/WatchService.md)
- [Direct Buffer](/docs/CS/Java/JDK/IO/Direct_Buffer.md)
- [io_uring](/docs/CS/Java/JDK/IO/Uring.md)
- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)
- [JDK](/docs/CS/Java/JDK/JDK.md)

## References

1. [Efficient data transfer through zero copy](https://developer.ibm.com/articles/j-zerocopy/)
