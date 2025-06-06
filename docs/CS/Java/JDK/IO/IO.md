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


### Channel

A nexus for I/O operations.

A channel represents an open connection to an entity such as a hardware device, a file, a network socket, or a program component that is capable of performing one or more distinct I/O operations, for example reading or writing.
A channel is either open or closed. A channel is open upon creation, and once closed it remains closed. Once a channel is closed, any attempt to invoke an I/O operation upon it will cause a ClosedChannelException to be thrown.
Whether or not a channel is open may be tested by invoking its isOpen method.

Channels are, in general, intended to be safe for multithreaded access as described in the specifications of the interfaces and classes that extend and implement this interface.

A socket will have a channel if, and only if, the channel itself was created via the `SocketChannel.open` or `ServerSocketChannel.accept` methods.

#### ServerSocketChannel

```java
public abstract class ServerSocketChannel extends AbstractSelectableChannel implements NetworkChannel {
  
  private final ReentrantLock acceptLock = new ReentrantLock();
  
  public SocketChannel accept() throws IOException {
    int n = 0;
    FileDescriptor newfd = new FileDescriptor();
    InetSocketAddress[] isaa = new InetSocketAddress[1];

    acceptLock.lock();
    try {
      boolean blocking = isBlocking();
      try {
        begin(blocking);
        n = Net.accept(this.fd, newfd, isaa);
        if (blocking) {
          while (IOStatus.okayToRetry(n) && isOpen()) {
            park(Net.POLLIN);
            n = Net.accept(this.fd, newfd, isaa);
          }
        }
      } finally {
        end(blocking, n > 0);
        assert IOStatus.check(n);
      }
    } finally {
      acceptLock.unlock();
    }

    if (n > 0) {
      return finishAccept(newfd, isaa[0]);
    } else {
      return null;
    }
  }
}
```


#### Connect

Connects this channel's socket.

If this channel is in non-blocking mode then an invocation of this method initiates a non-blocking connection operation.
- If the connection is established immediately, as can happen with a local connection, then this method returns true.
- Otherwise this method returns false and the connection operation must later be completed by invoking the finishConnect method.

If this channel is in blocking mode then an invocation of this method will block until the connection is established or an I/O error occurs.

This method performs exactly the same security checks as the Socket class.
That is, if a security manager has been installed then this method verifies that its checkConnect method permits connecting to the address and port number of the given remote endpoint.

This method may be invoked at any time.
If a read or write operation upon this channel is invoked while an invocation of this method is in progress then that operation will first block until this invocation is complete.
If a connection attempt is initiated but fails, that is, if an invocation of this method throws a checked exception, then the channel will be closed.


### Buffer

A container for data of a specific primitive type.

A buffer is a linear, finite sequence of elements of a specific primitive type. Aside from its content, the essential properties of a buffer are its capacity, limit, and position:

- A buffer's capacity is the number of elements it contains. The capacity of a buffer is never negative and never changes.
- A buffer's limit is the index of the first element that should not be read or written. A buffer's limit is never negative and is never greater than its capacity.
- A buffer's position is the index of the next element to be read or written. A buffer's position is never negative and is never greater than its limit.

There is one subclass of this class for each non-boolean primitive type.

#### Marking and resetting

> The following invariant holds for the mark, position, limit, and capacity values:
>
> 0 <= mark <= position <= limit <= capacity

#### Read-only buffers

Every buffer is readable, but not every buffer is writable. The mutation methods of each buffer class are specified as optional operations that will throw a ReadOnlyBufferException when invoked upon a read-only buffer.
A read-only buffer does not allow its content to be changed, but its mark, position, and limit values are mutable. Whether or not a buffer is read-only may be determined by invoking its isReadOnly method.

#### Thread safety

**Buffers are not safe for use by multiple concurrent threads.** If a buffer is to be used by more than one thread then access to the buffer should be controlled by appropriate synchronization.



### Selector

A multiplexor of SelectableChannel objects.

A selector may be created by invoking the open method of this class, which will use the system's default selector provider to create a new selector.
A selector may also be created by invoking the openSelector method of a custom selector provider. A selector remains open until it is closed via its close method.

A selectable channel's registration with a selector is represented by a SelectionKey object. A selector maintains three sets of selection keys:

- The key set contains the keys representing the current channel registrations of this selector. This set is returned by the keys method.
- The selected-key set is the set of keys such that each key's channel was detected to be ready for at least one of the operations identified in the key's interest set
  during a prior selection operation that adds keys or updates keys in the set.
  This set is returned by the selectedKeys method. The selected-key set is always a subset of the key set.
- The cancelled-key set is the set of keys that have been cancelled but whose channels have not yet been deregistered.
  This set is not directly accessible. The cancelled-key set is always a subset of the key set.

All three sets are empty in a newly-created selector.

A key is added to a selector's key set as a side effect of registering a channel via the channel's register method. Cancelled keys are removed from the key set during selection operations.
The key set itself is not directly modifiable.

A key is added to its selector's cancelled-key set when it is cancelled, whether by closing its channel or by invoking its cancel method.
Cancelling a key will cause its channel to be deregistered during the next selection operation, at which time the key will be removed from all of the selector's key sets.

Keys are added to the selected-key set by selection operations. A key may be removed directly from the selected-key set by invoking the set's remove method or by invoking the remove method of an iterator obtained from the set.
All keys may be removed from the selected-key set by invoking the set's clear method. Keys may not be added directly to the selected-key set.

#### Selection

A selection operation queries the underlying operating system for an update as to the readiness of each registered channel to perform any of the operations identified by its key's interest set. There are two forms of selection operation:

- The select(), select(long), and selectNow() methods add the keys of channels ready to perform an operation to the selected-key set, or update the ready-operation set of keys already in the selected-key set.
- The select(Consumer), select(Consumer, long), and selectNow(Consumer) methods perform an action on the key of each channel that is ready to perform an operation. These methods do not add to the selected-key set.

#### Selection operations that add to the selected-key set

During each selection operation, keys may be added to and removed from a selector's selected-key set and may be removed from its key and cancelled-key sets. Selection is performed by the select(), select(long), and selectNow() methods, and involves three steps:

- Each key in the cancelled-key set is removed from each key set of which it is a member, and its channel is deregistered. This step leaves the cancelled-key set empty.
- The underlying operating system is queried for an update as to the readiness of each remaining channel to perform any of the operations identified by its key's interest set as of the moment that the selection operation began.
  For a channel that is ready for at least one such operation, one of the following two actions is performed:
  - If the channel's key is not already in the selected-key set then it is added to that set and its ready-operation set is modified to identify exactly those operations for which the channel is now reported to be ready.
    Any readiness information previously recorded in the ready set is discarded.
  - Otherwise the channel's key is already in the selected-key set, so its ready-operation set is modified to identify any new operations for which the channel is reported to be ready.
    Any readiness information previously recorded in the ready set is preserved; in other words, the ready set returned by the underlying system is bitwise-disjoined into the key's current ready set.
- If all of the keys in the key set at the start of this step have empty interest sets then neither the selected-key set nor any of the keys' ready-operation sets will be updated.
- If any keys were added to the cancelled-key set while step (2) was in progress then they are processed as in step (1).

Whether or not a selection operation blocks to wait for one or more channels to become ready, and if so for how long, is the only essential difference between the three selection methods.

#### Selection operations that perform an action on selected keys

During each selection operation, keys may be removed from the selector's key, selected-key, and cancelled-key sets. Selection is performed by the select(Consumer), select(Consumer, long), and selectNow(Consumer) methods, and involves three steps:

- Each key in the cancelled-key set is removed from each key set of which it is a member, and its channel is deregistered. This step leaves the cancelled-key set empty.
- The underlying operating system is queried for an update as to the readiness of each remaining channel to perform any of the operations identified by its key's interest set as of the moment that the selection operation began.
  For a channel that is ready for at least one such operation, the ready-operation set of the channel's key is set to identify exactly the operations for which the channel is ready and the action specified to the select method is invoked to consume the channel's key.
  Any readiness information previously recorded in the ready set is discarded prior to invoking the action.
  Alternatively, where a channel is ready for more than one operation, the action may be invoked more than once with the channel's key and ready-operation set modified to a subset of the operations for which the channel is ready.
  Where the action is invoked more than once for the same key then its ready-operation set never contains operation bits that were contained in the set at previous calls to the action in the same selection operation.
- If any keys were added to the cancelled-key set while step (2) was in progress then they are processed as in step (1).

#### Concurrency

A Selector and its key set are safe for use by multiple concurrent threads. Its selected-key set and cancelled-key set, however, are not.

The selection operations synchronize on the selector itself, on the selected-key set, in that order. They also synchronize on the cancelled-key set during steps (1) and (3) above.

Changes made to the interest sets of a selector's keys while a selection operation is in progress have no effect upon that operation; they will be seen by the next selection operation.

Keys may be cancelled and channels may be closed at any time. Hence the presence of a key in one or more of a selector's key sets does not imply that the key is valid or that its channel is open.
Application code should be careful to synchronize and check these conditions as necessary if there is any possibility that another thread will cancel a key or close a channel.

A thread blocked in a selection operation may be interrupted by some other thread in one of three ways:

- By invoking the selector's wakeup method,
- By invoking the selector's close method, or
- By invoking the blocked thread's interrupt method, in which case its interrupt status will be set and the selector's wakeup method will be invoked.

The close method synchronizes on the selector and its selected-key set in the same order as in a selection operation.

A Selector's key set is safe for use by multiple concurrent threads.
Retrieval operations from the key set do not generally block and so may overlap with new registrations that add to the set, or with the cancellation steps of selection operations that remove keys from the set.
Iterators and spliterators return elements reflecting the state of the set at some point at or since the creation of the iterator/spliterator. They do not throw ConcurrentModificationException.

A selector's selected-key set is not, in general, safe for use by multiple concurrent threads.
If such a thread might modify the set directly then access should be controlled by synchronizing on the set itself.
The iterators returned by the set's iterator methods are fail-fast: If the set is modified after the iterator is created, in any way except by invoking the iterator's own remove method, then a java.util.ConcurrentModificationException will be thrown.


#### select

Selects a set of keys whose corresponding channels are ready for I/O operations.

Both `select()` and `select(timeout)` methods perform a blocking selection operation.
And return only after at least one channel is selected, this selector's wakeup method is invoked, or the current thread is interrupted, whichever comes first.
The `select(timeout)` method  also returns after the given timeout period expires.
This method does not offer real-time guarantees: It schedules the timeout as if by invoking the Object.wait(long) method.


The `selectNow()` method performs a non-blocking selection operation.
If no channels have become selectable since the previous selection operation then this method immediately returns zero.
Invoking this method clears the effect of any previous invocations of the wakeup method.

```java

public abstract int select() throws IOException;

public abstract int select(long timeout) throws IOException;

public abstract int selectNow() throws IOException;
```


#### wakeup

Causes the first selection operation that has not yet returned to return immediately.

If another thread is currently blocked in a selection operation then that invocation will return immediately. 
If no selection operation is currently in progress then the next invocation of a selection operation will return immediately unless selectNow() or selectNow(Consumer) is invoked in the meantime. 
In any case the value returned by that invocation may be non-zero. 
Subsequent selection operations will block as usual unless this method is invoked again in the meantime.
> [!TIP]
> 
> Invoking this method more than once between two successive selection operations has the same effect as invoking it just once.

```java
public abstract Selector wakeup();
```


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