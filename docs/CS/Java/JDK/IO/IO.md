## Introduction

## Network

java.net 包支持两种协议：

- TCP：传输控制协议，在发送方和接收方之间提供可靠通信。TCP 与互联网协议一起使用，称为 TCP/IP。
- UDP：用户数据报协议，通过允许数据包在两个或多个节点之间传输来提供无连接协议服务。

### Socket

此类表示没有协议附加的 Socket 地址。
作为抽象类，它旨在由特定的、依赖于协议的实现进行子类化。
它提供一个不可变对象，供 socket 用于绑定、连接或作为返回值。

```java
public abstract class SocketAddress implements java.io.Serializable {

    @java.io.Serial
    static final long serialVersionUID = 5215720748342549866L;

}
```

此类表示互联网协议（IP）地址。
IP 地址是 IP（UDP 和 TCP 等协议构建在其上的底层协议）使用的 32 位或 128 位无符号数。
IP 地址架构由 RFC 790：分配编号、RFC 1918：私有互联网地址分配、RFC 2365：管理范围 IP 多播和 RFC 2373：IP 版本 6 寻址架构定义。

InetAddress 实例由一个 IP 地址和可能对应的主机名组成（取决于它是使用主机名构造还是已经执行了反向主机名解析）。

InetAddress

### ServerSocket

监听此 socket 的连接并接受它。
该方法会阻塞直到建立连接。

如果存在安全管理器，则创建一个新的 Socket s，并调用安全管理器的 checkAccept 方法，传入 s.getInetAddress().getHostAddress() 和 s.getPort() 作为参数，以确保允许该操作。
这可能导致 SecurityException。

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

### Address Types

- unicast（单播）
  单个接口的标识符。发送到单播地址的数据包将传送到该地址标识的接口。
  - 未指定地址（Unspecified Address）——也称为任意本地或通配符地址。绝不能分配给任何节点。它表示不存在地址。其用途之一是作为 bind 的目标，允许服务器在任何接口上接受客户端连接，以防服务器主机有多个接口。
    未指定地址不能用作 IP 数据包的目标地址。
  - 回环地址（Loopback Addresses）——这是分配给回环接口的地址。发送到此 IP 地址的任何内容都会回环并成为本地主机的 IP 输入。该地址通常用于测试客户端。
- multicast（多播）
  一组接口（通常属于不同节点）的标识符。发送到多播地址的数据包将传送到该地址标识的所有接口。

#### IP 地址范围

链路本地地址（Link-local addresses）设计用于单个链路上的寻址，用于自动地址配置、邻居发现或没有路由器的情况。
站点本地地址（Site-local addresses）设计用于站点内的寻址，无需全局前缀。
全局地址（Global addresses）在互联网上是唯一的。
IP 地址的文本表示
IP 地址的文本表示因地址族而异。
对于 IPv4 地址格式，请参阅 Inet4Address#format；对于 IPv6 地址格式，请参阅 Inet6Address#format。
有一些系统属性会影响 IPv4 和 IPv6 地址的使用方式。

主机名解析

主机名到 IP 地址的解析通过使用本地机器配置信息和网络命名服务（如域名系统（DNS）和网络信息服务（NIS））的组合来完成。
使用的特定命名服务默认为本地机器配置的服务。对于任何主机名，返回其对应的 IP 地址。
反向名称解析意味着对于任何 IP 地址，返回该 IP 地址关联的主机名。
InetAddress 类提供了将主机名解析为其 IP 地址以及反向解析的方法。

#### InetAddress 缓存

InetAddress 类有一个缓存，用于存储成功和失败的主机名解析结果。

默认情况下，当安装了安全管理器时，为了防御 DNS 欺骗攻击，正向主机名解析的结果会永久缓存。
当没有安装安全管理器时，默认行为是将条目缓存一段有限的（依赖于实现的）时间。
失败的主机名解析结果会缓存很短的时间（10 秒）以提高性能。

如果默认行为不理想，可以设置 Java 安全属性为不同的正向缓存生存时间（TTL）值。
同样，系统管理员可以在需要时配置不同的负向缓存 TTL 值。

两个 Java 安全属性控制正向和负向主机名解析缓存的 TTL 值：

- networkaddress.cache.ttl
  指示名称服务成功名称查找的缓存策略。该值指定为整数，表示缓存成功查找的秒数。
  默认设置为缓存一段实现特定的时间。值为 -1 表示"永久缓存"。
- networkaddress.cache.negative.ttl（默认值：10）
  指示名称服务失败名称查找的缓存策略。该值指定为整数，表示缓存失败查找的秒数。
  值为 0 表示"从不缓存"。值为 -1 表示"永久缓存"。

## BIO

Java I/O（输入和输出）用于处理输入和产生输出。
Java 使用流的概念来使 I/O 操作快速。
`java.io` 包包含输入和输出操作所需的所有类。

### Stream

流是一系列数据。在 Java 中，流由字节组成。之所以称为流，是因为它像持续流动的水流。
Java 应用程序使用流来读取/写入数据到目标；它可以是文件、数组、外围设备或 socket。

在 Java 中，会自动为我们创建 3 个流。所有这些流都连接到控制台。
1. System.out：标准输出流
2. System.in：标准输入流
3. System.err：标准错误流

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

#### BufferedStream

Java BufferedOutputStream/BufferedInputStream 类用于从流中读取信息。它在内部使用缓冲机制来提高性能。

迭代服务器逐个服务客户端。

并发服务器

read

从输入流中读取下一个字节数据。
该值字节作为 0 到 255 范围内的 int 返回。
如果没有可用字节，因为已到达流末尾，则返回 -1。
此方法会阻塞，直到输入数据可用、检测到流末尾或抛出异常。

### write

将指定字节写入此输出流。write 的一般约定是向输出流写入一个字节。要写入的字节是参数 b 的八个低位。b 的 24 个高位被忽略。

在 `IOUtil.write()` 中：

1. `if (src instanceof DirectBuffer)`，调用 `writeFromNativeBuffer`
2. 否则，从 `getTemporaryDirectBuffer` 复制到 directBuffer
然后调用 `writeFromNativeBuffer`

> Links: [Comparing performance of Java I/O and NIO: streams vs channels](https://github.com/romromov/java-io-benchmark)

## NIO

[Java NIO（New IO）](/docs/CS/Java/JDK/IO/NIO.md)是一种替代的 Java IO API，意即标准 Java IO 和 Java 网络 API 的替代方案。
Java NIO 提供了与传统 IO API 不同的 IO 编程模型。

## AIO

[IOCP](https://hg.openjdk.org/jdk/jdk/file/d8327f838b88/src/java.base/windows/classes/sun/nio/ch/Iocp.java)

## File

从文件中读取所有行作为 Stream。与 readAllLines 不同，此方法不会将所有行读入 List，而是在消费流时惰性地填充。

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

JAVA NIO 和 JAVA AIO并没有提供断连重连、网络闪断、半包读写、失败缓存、网络拥塞和异常码流等的处理，这些都需要开发者自己来补齐相关的工作。
AIO在实践中，并没有比NIO更好。AIO在不同的平台有不同的实现，windows系统下使用的是一种异步IO技术：IOCP；
Linux下由于没有这种异步 IO 技术，所以使用的是epoll 对异步 IO 进行模拟。所以 AIO 在 Linux 下的性能并不理想。AIO 也没有提供对 UDP 的支持。

在实际的大型互联网项目中，Java 原生的 API 应用并不广泛，取而代之的是一款第三方Java 框架，这就是 [Netty](/docs/CS/Framework/Netty/Netty.md)

## Links

## References

1. [Efficient data transfer through zero copy](https://developer.ibm.com/articles/j-zerocopy/)
