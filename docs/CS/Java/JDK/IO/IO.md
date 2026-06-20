## Introduction



## Network

The java.net package supports two protocols,

- TCP: Transmission Control Protocol provides reliable communication between the sender and receiver. TCP is used along with the Internet Protocol referred as TCP/IP.
- UDP: User Datagram Protocol provides a connection-less protocol service by allowing packet of data to be transferred along two or more nodes

### Socket

This class represents a Socket Address with no protocol attachment. 
As an abstract class, it is meant to be subclassed with a specific, protocol dependent, implementation.
It provides an immutable object used by sockets for binding, connecting, or as returned values.

```java
public abstract class SocketAddress implements java.io.Serializable {

    @java.io.Serial
    static final long serialVersionUID = 5215720748342549866L;

}
```

This class represents an Internet Protocol (IP) address.
An IP address is either a 32-bit or 128-bit unsigned number used by IP, a lower-level protocol on which protocols like UDP and TCP are built.
The IP address architecture is defined by RFC 790: Assigned Numbers, RFC 1918: Address Allocation for Private Internets, RFC 2365: Administratively Scoped IP Multicast, and RFC 2373: IP Version 6 Addressing Architecture.

An instance of an InetAddress consists of an IP address and possibly its corresponding host name (depending on whether it is constructed with a host name or whether it has already done reverse host name resolution).

InetAddress


### ServerSocket


Listens for a connection to be made to this socket and accepts it. 
The method blocks until a connection is made.

A new Socket s is created and, if there is a security manager, the security manager's checkAccept method is called with s.getInetAddress().getHostAddress() and s.getPort() as its arguments to ensure the operation is allowed. 
This could result in a SecurityException.

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

- unicast
  An identifier for a single interface. A packet sent to a unicast address is delivered to the interface identified by that address.
  - The Unspecified Address -- Also called anylocal or wildcard address. It must never be assigned to any node. It indicates the absence of an address. One example of its use is as the target of bind, which allows a server to accept a client connection on any interface, in case the server host has multiple interfaces.
    The unspecified address must not be used as the destination address of an IP packet.
  - The Loopback Addresses -- This is the address assigned to the loopback interface. Anything sent to this IP address loops around and becomes IP input on the local host. This address is often used when testing a client.
- multicast
  An identifier for a set of interfaces (typically belonging to different nodes). A packet sent to a multicast address is delivered to all interfaces identified by that address.

#### IP address scope

Link-local addresses are designed to be used for addressing on a single link for purposes such as auto-address configuration, neighbor discovery, or when no routers are present.
Site-local addresses are designed to be used for addressing inside of a site without the need for a global prefix.
Global addresses are unique across the internet.
Textual representation of IP addresses
The textual representation of an IP address is address family specific.
For IPv4 address format, please refer to Inet4Address#format; For IPv6 address format, please refer to Inet6Address#format.
There is a couple of System Properties affecting how IPv4 and IPv6 addresses are used.

Host Name Resolution

Host name-to-IP address resolution is accomplished through the use of a combination of local machine configuration information and network naming services such as the Domain Name System (DNS) and Network Information Service(NIS).
The particular naming services(s) being used is by default the local machine configured one. For any host name, its corresponding IP address is returned.
Reverse name resolution means that for any IP address, the host associated with the IP address is returned.
The InetAddress class provides methods to resolve host names to their IP addresses and vice versa.

#### InetAddress Caching

The InetAddress class has a cache to store successful as well as unsuccessful host name resolutions.

By default, when a security manager is installed, in order to protect against DNS spoofing attacks, the result of positive host name resolutions are cached forever.
When a security manager is not installed, the default behavior is to cache entries for a finite (implementation dependent) period of time.
The result of unsuccessful host name resolution is cached for a very short period of time (10 seconds) to improve performance.

If the default behavior is not desired, then a Java security property can be set to a different Time-to-live (TTL) value for positive caching.
Likewise, a system admin can configure a different negative caching TTL value when needed.

Two Java security properties control the TTL values used for positive and negative host name resolution caching:

- networkaddress.cache.ttl
  Indicates the caching policy for successful name lookups from the name service. The value is specified as an integer to indicate the number of seconds to cache the successful lookup.
  The default setting is to cache for an implementation specific period of time. A value of -1 indicates "cache forever".
- networkaddress.cache.negative.ttl (default: 10)
  Indicates the caching policy for un-successful name lookups from the name service. The value is specified as an integer to indicate the number of seconds to cache the failure for un-successful lookups.
  A value of 0 indicates "never cache". A value of -1 indicates "cache forever".




## BIO


Java I/O (Input and Output) is used to process the input and produce the output.
Java uses the concept of a stream to make I/O operation fast.
The `java.io` package contains all the classes required for input and output operations.

### Stream

A stream is a sequence of data. In Java, a stream is composed of bytes. It's called a stream because it is like a stream of water that continues to flow.
Java application uses an stream to read/write data to a destination; it may be a file, an array, peripheral device or socket.

In Java, 3 streams are created for us automatically. All these streams are attached with the console.
1. System.out: standard output stream
2. System.in: standard input stream
3. System.err: standard error stream


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

Java BufferedOutputStream/BufferedInputStream class is used to read information from stream. It internally uses buffer mechanism to make the performance fast.


Iterative server serves client one by one.

concurrent servers


read

Reads the next byte of data from the input stream.
The value byte is returned as an int in the range 0 to 255
If no byte is available because the end of the stream has been reached, the value -1 is returned.
This method blocks until input data is available, the end of the stream is detected, or an exception is thrown.



### write
Writes the specified byte to this output stream. The general contract for write is that one byte is written to the output stream. The byte to be written is the eight low-order bits of the argument b. The 24 high-order bits of b are ignored.


In `IOUtil.write()`

1. `if (src instanceof DirectBuffer)`, `writeFromNativeBuffer`
2. Else  copy to directBuffer from `getTemporaryDirectBuffer`
then `writeFromNativeBuffer`


> Links: [Comparing performance of Java I/O and NIO: streams vs channels](https://github.com/romromov/java-io-benchmark)

## NIO


[Java NIO（New IO）](/docs/CS/Java/JDK/IO/NIO.md)是一种替代的 Java IO API，意即标准 Java IO 和 Java 网络 API 的替代方案
Java NIO 提供了与传统 IO API 不同的 IO 编程模型

## AIO


[IOCP](https://hg.openjdk.org/jdk/jdk/file/d8327f838b88/src/java.base/windows/classes/sun/nio/ch/Iocp.java)

## File

Read all lines from a file as a Stream. Unlike readAllLines, this method does not read all lines into a List, but instead populates lazily as the stream is consumed.

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

JAVA NIO 和 JAVA AIO并没有提供断连重连、网络闪断、半包读写、失败缓存、网络拥塞和异常码流等的处理，这些都需要开发者自己来补齐相关的工作
AIO在实践中，并没有比NIO更好。AIO在不同的平台有不同的实现，windows系统下使用的是一种异步IO技术：IOCP；
Linux下由于没有这种异步 IO 技术，所以使用的是epoll 对异步 IO 进行模拟。所以 AIO 在 Linux 下的性能并不理想。AIO 也没有提供对 UDP 的支持

在实际的大型互联网项目中，Java 原生的 API 应用并不广泛，取而代之的是一款第三方Java 框架，这就是 [Netty](/docs/CS/Framework/Netty/Netty.md)


## Links



## References

1. [Efficient data transfer through zero copy](https://developer.ibm.com/articles/j-zerocopy/)