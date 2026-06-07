## Introduction

*Java* *NIO*（New IO）是一种替代的 Java IO API。
注意：有时 NIO 被认为是指 *Non-blocking IO*。
然而，这并不是 NIO 最初的含义。
此外，部分 NIO API 实际上是阻塞的——例如文件 API——因此"非阻塞"这个标签会有些误导。

下表总结了 Java NIO 和 IO 之间的主要区别。

| IO              | NIO             |
| --------------- | --------------- |
| Stream oriented | Buffer oriented |
| Blocking IO     | Non blocking IO |
|                 | Selectors       |



Java NIO 使你可以执行非阻塞 IO。
例如，一个线程可以请求 channel 将数据读入 buffer。
当 channel 将数据读入 buffer 时，线程可以执行其他操作。一旦数据读入 buffer，线程就可以继续处理它。
写入数据到 channel 也是如此。



在 NIO 中，你使用 channel 和 buffer 进行操作。数据总是从 channel 读入 buffer，或从 buffer 写入 channel。

## Channels

Java NIO Channels 与流类似，但有一些区别：

* 你可以对 Channel 进行读写操作。流通常是单向的（读取或写入）。
* Channel 可以异步读写。
* Channel 总是从 Buffer 读取数据或向 Buffer 写入数据。

Channel 表示与实体（如硬件设备、文件、网络 socket 或能够执行一个或多个不同 I/O 操作（例如读取或写入）的程序组件）的开放连接。
Channel 要么打开要么关闭。Channel 在创建时打开，一旦关闭就保持关闭。一旦 Channel 关闭，任何尝试在其上调用 I/O 操作都将抛出 ClosedChannelException。
可以通过调用其 isOpen 方法来测试 Channel 是否打开。

通常，Channel 旨在支持多线程安全访问，如扩展和实现此接口的接口和类的规范所述。

Socket 拥有 Channel 当且仅当该 Channel 本身是通过 `SocketChannel.open` 或 `ServerSocketChannel.accept` 方法创建的。

以下是 Java NIO 中最重要的 Channel 实现：

* SocketChannel
* ServerSocketChannel
* DatagramChannel
* FileChannel


### SocketChannel



#### Connect

连接此 channel 的 socket。

如果此 channel 处于非阻塞模式，则调用此方法会启动非阻塞连接操作。
- 如果连接立即建立（如同本地连接可能发生的情况），则此方法返回 true。
- 否则此方法返回 false，连接操作稍后必须通过调用 finishConnect 方法完成。

如果此 channel 处于阻塞模式，则调用此方法将阻塞，直到建立连接或发生 I/O 错误。

此方法执行与 Socket 类完全相同的安全检查。
也就是说，如果已安装安全管理器，则此方法验证其 checkConnect 方法是否允许连接到给定远程端点的地址和端口号。

此方法可以随时调用。
如果在此方法调用过程中对此 channel 调用了读取或写入操作，则该操作将首先阻塞，直到此调用完成。
如果连接尝试启动但失败，即如果此方法的调用抛出已检查异常，则 channel 将被关闭。


### FileChannel


FileChannel 可安全地被多个并发线程使用。

FileChannel 通过调用此类定义的 open 方法之一创建。
也可以从现有的 FileInputStream、FileOutputStream 或 RandomAccessFile 对象调用其 getChannel 方法获得 FileChannel，
该方法返回连接到同一底层文件的 FileChannel。
当从现有流或随机访问文件获取 FileChannel 时，FileChannel 的状态与返回该 channel 的对象的状态密切相关。
显式地或通过读取/写入字节来更改 channel 的位置，都将更改原始对象的文件位置，反之亦然。
通过 FileChannel 更改文件长度将更改原始对象看到的长度，反之亦然。
通过写入字节更改文件内容将更改原始对象看到的内容，反之亦然。
关闭 channel 将关闭原始对象。




- Attempt a direct transfer
- Attempt a mapped transfer
- HeapBuffer



通过 NativeDispatcher 对具体 Channel 操作实现分发，调用具体的系统调用

#### read

```java
public class FileChannelImpl extends FileChannel {
    public int read(ByteBuffer dst) throws IOException {
        // ...
        synchronized (positionLock) {
            // ...
            try {
                // ...
                do {
                    long comp = Blocker.begin();
                    try {
                        n = IOUtil.read(fd, dst, -1, direct, alignment, nd);
                    } finally {
                        Blocker.end(comp);
                    }
                } while ((n == IOStatus.INTERRUPTED) && isOpen());
                return IOStatus.normalize(n);
            } finally {
                // ...
            }
        }
    }
}
```

当我们使用 HeapByteBuffer 传入 FileChannel 的 read or write 方法对文件进行读写时，JDK 会首先创建一个临时的 DirectByteBuffer，对于 `FileChannel#read` 来说，JDK 在 native 层会将 read 系统调用从文件中读取的内容首先存放到这个临时的 DirectByteBuffer 中，然后在拷贝到 HeapByteBuffer 中返回

```java
public class IOUtil {
    static int read(FileDescriptor fd, ByteBuffer dst, long position,
                    boolean directIO, boolean async,
                    int alignment, NativeDispatcher nd)
    throws IOException
    {
        if (dst.isReadOnly())
            throw new IllegalArgumentException("Read-only buffer");
        if (dst instanceof DirectBuffer)
            return readIntoNativeBuffer(fd, dst, position, directIO, async, alignment, nd);

        // Substitute a native buffer
        ByteBuffer bb;
        int rem = dst.remaining();
        if (directIO) {
            Util.checkRemainingBufferSizeAligned(rem, alignment);
            bb = Util.getTemporaryAlignedDirectBuffer(rem, alignment);
        } else {
            bb = Util.getTemporaryDirectBuffer(rem);
        }
        try {
            int n = readIntoNativeBuffer(fd, bb, position, directIO, async, alignment, nd);
            bb.flip();
            if (n > 0)
                dst.put(bb);
            return n;
        } finally {
            Util.offerFirstTemporaryDirectBuffer(bb);
        }
    }
}
```



```java
private static int readIntoNativeBuffer(FileDescriptor fd, ByteBuffer bb,
                                            long position, boolean directIO,
                                            boolean async, int alignment,
                                            NativeDispatcher nd)
        throws IOException
    {
        int pos = bb.position();
        int lim = bb.limit();
        assert (pos <= lim);
        int rem = (pos <= lim ? lim - pos : 0);

        if (directIO) {
            Util.checkBufferPositionAligned(bb, pos, alignment);
            Util.checkRemainingBufferSizeAligned(rem, alignment);
        }

        if (rem == 0)
            return 0;
        int n = 0;
        acquireScope(bb, async);
        try {
            if (position != -1) {
                n = nd.pread(fd, bufferAddress(bb) + pos, rem, position);
            } else {
                n = nd.read(fd, bufferAddress(bb) + pos, rem);
            }
        } finally {
            releaseScope(bb);
        }
        if (n > 0)
            bb.position(pos + n);
        return n;
    }
```

最终会调用到 NativeDispatcher 的 read 方法 对于FileChannel 的实现为 FileDispatcherImpl

```java
class UnixFileDispatcherImpl extends FileDispatcher {

    int read(FileDescriptor fd, long address, int len) throws IOException {
        return read0(fd, address, len);
    }
}
```

系统调用[read](/docs)

```c
JNIEXPORT jint JNICALL
Java_sun_nio_ch_FileDispatcherImpl_read0(JNIEnv *env, jclass clazz, jobject fdo,
                                      jlong address, jint len)
{
    // ...
    result = ReadFile(h,          /* File handle to read */
                      (LPVOID)address,    /* address to put data */
                      len,        /* number of bytes to read */
                      &read,      /* number of bytes read */
                      NULL);      /* no overlapped struct */
    // ...
    return convertReturnVal(env, (jint)read, JNI_TRUE);
}
```





#### write


  
JDK 会首先将 HeapByteBuffer 中的待写入数据拷贝到临时的 DirectByteBuffer 中，然后在 native 层通过 write 系统调用将 DirectByteBuffer 中的数据写入到文件的 page cache 中


为什么必须要在 DirectByteBuffer 中做一次中转

HeapByteBuffer 是位于 JVM 堆中的内存，那么它必然会受到 GC 的管理 GC执行过程中会移动存活对象 内存地址会发生变化

内存从HeapByteBuffer拷贝到临时DirectByteBuffer过程调用的是Unsafe#copyMemory 不在safepoint中 拷贝过程不会执行GC

```java
@IntrinsicCandidate
    private native void copyMemory0(Object srcBase, long srcOffset, Object destBase, long destOffset, long bytes);
```



#### transferTo

FileChannelImpl 对于 FileChannel 的 transfer 方法中有三种实现
- 需要操作系统支持 操作系统直接传送数据
- 使用 mmap 方式共享内存传送
- 传统方式传送

```java
public long transferTo(long position, long count, WritableByteChannel target) throws IOException {
        ensureOpen();
        if (!target.isOpen())
            throw new ClosedChannelException();
        if (!readable)
            throw new NonReadableChannelException();
        if (target instanceof FileChannelImpl &&
            !((FileChannelImpl)target).writable)
            throw new NonWritableChannelException();
        if ((position < 0) || (count < 0))
            throw new IllegalArgumentException();
        long sz = size();
        if (position > sz)
            return 0;

        if ((sz - position) < count)
            count = sz - position;

        // Attempt a direct transfer, if the kernel supports it, limiting
        // the number of bytes according to which platform
        int icount = (int)Math.min(count, MAX_DIRECT_TRANSFER_SIZE);
        long n;
        if ((n = transferToDirectly(position, icount, target)) >= 0)
            return n;

        // Attempt a mapped transfer, but only to trusted channel types
        if ((n = transferToTrustedChannel(position, count, target)) >= 0)
            return n;

        // Slow path for untrusted targets
        return transferToArbitraryChannel(position, count, target);
}
```

##### transferToDirectly
```java
private long transferToDirectlyInternal(long position, int icount,
                                            WritableByteChannel target,
                                            FileDescriptor targetFD)
        throws IOException
    {
        assert !nd.transferToDirectlyNeedsPositionLock() ||
               Thread.holdsLock(positionLock);

        long n = -1;
        int ti = -1;
        try {
            beginBlocking();
            ti = threads.add();
            if (!isOpen())
                return -1;
            do {
                long comp = Blocker.begin();
                try {
                    n = transferTo0(fd, position, icount, targetFD);
                } finally {
                    Blocker.end(comp);
                }
            } while ((n == IOStatus.INTERRUPTED) && isOpen());
            if (n == IOStatus.UNSUPPORTED_CASE) {
                if (target instanceof SinkChannelImpl)
                    pipeSupported = false;
                if (target instanceof FileChannelImpl)
                    fileSupported = false;
                return IOStatus.UNSUPPORTED_CASE;
            }
            if (n == IOStatus.UNSUPPORTED) {
                // Don't bother trying again
                transferToNotSupported = true;
                return IOStatus.UNSUPPORTED;
            }
            return IOStatus.normalize(n);
        } finally {
            threads.remove(ti);
            end (n > -1);
        }
    }

```


##### transferTo0

通过 JNI 调用本地方法 transferTo0 完成传送

```c

JNIEXPORT jlong JNICALL
Java_sun_nio_ch_FileDispatcherImpl_transferTo0(JNIEnv *env, jobject this,
                                                    jobject srcFDO,
                                                    jlong position, jlong count,
                                                    jobject dstFDO, jboolean append)
{
    jint srcFD = fdval(env, srcFDO);
    jint dstFD = fdval(env, dstFDO);

    jlong max = (jlong)java_lang_Integer_MAX_VALUE;
    struct sf_parms sf_iobuf;
    jlong result;

    if (position > max)
        return IOS_UNSUPPORTED_CASE;

    if (count > max)
        count = max;

    memset(&sf_iobuf, 0, sizeof(sf_iobuf));
    sf_iobuf.file_descriptor = srcFD;
    sf_iobuf.file_offset = (off_t)position;
    sf_iobuf.file_bytes = count;

    result = send_file(&dstFD, &sf_iobuf, SF_SYNC_CACHE);

    /* AIX send_file() will return 0 when this operation complete successfully,
     * return 1 when partial bytes transferred and return -1 when an error has
     * occurred.
     */
    if (result == -1) {
        if (errno == EWOULDBLOCK)
            return IOS_UNAVAILABLE;
        if ((errno == EINVAL) && ((ssize_t)count >= 0))
            return IOS_UNSUPPORTED_CASE;
        if (errno == EINTR)
            return IOS_INTERRUPTED;
        if (errno == ENOTSOCK)
            return IOS_UNSUPPORTED;
        JNU_ThrowIOExceptionWithLastError(env, "Transfer failed");
        return IOS_THROWN;
    }

    if (sf_iobuf.bytes_sent > 0)
        return (jlong)sf_iobuf.bytes_sent;

    return IOS_UNSUPPORTED_CASE;
}

```


### ServerSocketChannel

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



## Buffers

Buffer 本质上是一个内存块，你可以向其中写入数据，之后可以再次读取。
这个内存块被包装在 NIO Buffer 对象中，该对象提供了一组便于操作内存块的方法。

特定原始类型数据的容器。

Buffer 是特定原始类型元素的线性、有限序列。除了其内容外，Buffer 的基本属性包括容量（capacity）、界限（limit）和位置（position）：

- Buffer 的容量是其包含的元素数量。Buffer 的容量从不负且从不改变。
- Buffer 的界限是不应被读取或写入的第一个元素的索引。Buffer 的界限从不负且从不超过其容量。
- Buffer 的位置是下一个要读取或写入的元素的索引。Buffer 的位置从不负且从不超过其界限。

每个非 boolean 原始类型都有一个此类的子类。

标记与重置（Marking and resetting）

> The following invariant holds for the mark, position, limit, and capacity values:
>
> 0 <= mark <= position <= limit <= capacity

只读缓冲区（Read-only buffers）

每个 Buffer 都是可读的，但并非每个 Buffer 都是可写的。每个 Buffer 类的修改方法被指定为可选操作，在只读 Buffer 上调用时将抛出 ReadOnlyBufferException。
只读 Buffer 不允许更改其内容，但其 mark、position 和 limit 值是可变的。可以通过调用其 isReadOnly 方法来确定 Buffer 是否为只读。

线程安全

**Buffer 不适合多线程并发使用。** 如果 Buffer 将被多个线程使用，则应通过适当的同步来控制对 Buffer 的访问。

容量、位置和界限（Capacity, Position and Limit）

```java
public abstract class Buffer {
    // Invariants: mark <= position <= limit <= capacity
    private int mark = -1;
    private int position = 0;
    private int limit;
    private int capacity;
}
```


Using a `Buffer` to read and write data typically follows this little 4-step process:

1. Write data into the Buffer
2. Call** **`buffer.flip()`
3. Read data out of the Buffer
4. Call** **`buffer.clear()` or** **`buffer.compact()`

调用flip切换到read
```java
public Buffer flip() {
    limit = position;
    position = 0;
    mark = -1;
    return this;
}
```


```java
public Buffer clear() {
    position = 0;
    limit = capacity;
    mark = -1;
    return this;
}
```

读取了 Buffer 中的部分数据，但是还有一部分数据没有读取，这时候，调用 clear() 方法开启写模式向 Buffer 中写入数据的话，就会出问题，因为这会覆盖掉我们还没有读取的数据部分



JDK NIO 为每一种 Java 基本类型定义了对应的 Buffer 类（boolean 类型除外）

针对每一种基本类型的 Buffer ，NIO 又根据 Buffer 背后的数据存储内存不同分为了：HeapBuffer，DirectBuffer，MappedBuffer
这三种不同类型 ByteBuffer 的本质区别就是其背后依赖的虚拟内存在 JVM 进程虚拟内存空间中的布局位置不同

位于 JVM 堆之外的内存其实都可以归属到 DirectByteBuffer 的范畴中。
比如，位于 OS 堆之内，JVM 堆之外的 MetaSpace，即时编译(JIT) 之后的 codecache，JVM 线程栈，Native 线程栈，JNI 相关的内存，等等
JVM 在 OS 堆中划分出的 Direct Memory （上图红色部分）特指受到参数 -XX:MaxDirectMemorySize 限制的直接内存区域，比如通过 ByteBuffer#allocateDirect 申请到的 Direct Memory 容量就会受到该参数的限制

通过 Unsafe#allocateMemory 申请到的 Direct Memory 容量则不会受任何 JVM 参数的限制，只会受操作系统本身对进程所使用内存容量的限制。也就是说 Unsafe 类会脱离 JVM 直接向操作系统进行内存申请

MappedByteBuffer 背后所占用的内存位于 JVM 进程虚拟内存空间中的文件映射与匿名映射区中，系统调用 mmap 映射出来的内存就是在这个区域中划分的


当 GC 结束之后，JVM 会唤醒 ReferenceHandler 线程去执行 pending 队列中的这些 Cleaner，在 Cleaner 中会释放其背后引用的 Native Memory


```java
class HeapByteBuffer extends ByteBuffer {
    public ByteBuffer compact() {

        int pos = position();
        int lim = limit();
        assert (pos <= lim);
        int rem = (pos <= lim ? lim - pos : 0);
        System.arraycopy(hb, ix(pos), hb, ix(0), rem);
        position(rem);
        limit(capacity());
        discardMark();
        return this;
    }
}
```

### ByteBuffer

Byte buffer 要么是 direct 要么是 non-direct。对于 direct byte buffer，Java 虚拟机将尽最大努力直接在其上执行原生 I/O 操作。也就是说，它将尝试避免在每次调用底层操作系统的原生 I/O 操作之前（或之后）将 buffer 的内容复制到中间 buffer（或从中间 buffer 复制）。

```java
public abstract class ByteBuffer
    extends Buffer
    implements Comparable<ByteBuffer> {
    // These fields are declared here rather than in Heap-X-Buffer in order to
    // reduce the number of virtual method invocations needed to access these
    // values, which is especially costly when coding small buffers.
    //
    final byte[] hb;
    final int offset;
    boolean isReadOnly;
}
```

Direct byte buffer 可以通过调用此类的 allocateDirect 工厂方法创建。此方法返回的 buffer 通常比 non-direct buffer 具有更高的分配和释放成本。Direct buffer 的内容可能位于常规垃圾回收堆之外，因此它们对应用程序内存占用的影响可能不明显。因此建议 primarily 为大而长寿命的、受底层系统原生 I/O 操作影响的 buffer 分配 direct buffer。通常，最好仅在 direct buffer 能带来可衡量的程序性能提升时才分配它们。
Direct byte buffer 也可以通过将文件区域直接映射到内存来创建。Java 平台的实现可以选择支持通过 JNI 从原生代码创建 direct byte buffer。如果这些类型的 buffer 实例引用了不可访问的内存区域，则尝试访问该区域不会更改 buffer 的内容，并且会在访问时或稍后抛出未指定的异常。
可以通过调用其 isDirect 方法来确定 byte buffer 是 direct 还是 non-direct。提供此方法是为了可以在性能关键代码中进行显式 buffer 管理。


NIO 又根据 Buffer 背后的数据存储内存不同分为了：HeapBuffer，DirectBuffer，MappedBuffer


DirectBuffer 背后的存储内存是在堆外内存中分配，MappedBuffer 是通过内存文件映射将文件中的内容直接映射到堆外内存中，其本质也是一个 DirectBuffer


由于 DirectBuffer 和 MappedBuffer 背后的存储内存是在堆外内存中分配，不受 JVM 管理，所以不能用一个 Java 基本类型的数组表示，而是直接记录这段堆外内存的起始地址
```java
public abstract class Buffer {
    // Used by heap byte buffers or direct buffers with Unsafe access
    // For heap byte buffers this field will be the address relative to the
    // array base address and offset into that array. The address might
    // not align on a word boundary for slices, nor align at a long word
    // (8 byte) boundary for byte[] allocations on 32-bit systems.
    // For direct buffers it is the start address of the memory region. The
    // address might not align on a word boundary for slices, nor when created
    // using JNI, see NewDirectByteBuffer(void*, long).
    // Should ideally be declared final
    // NOTE: hoisted here for speed in JNI GetDirectBufferAddress
    long address;
}
```

### HeapByteBuffer


HeapBuffer 背后是有一个对应的基本类型数组作为存储的
DirectBuffer 和 MappedBuffer 背后的存储内存是在堆外内存中分配，不受 JVM 管理，所以不能用一个 Java 基本类型的数组表示，而是直接记录这段堆外内存的起始地址


```java
class HeapByteBuffer extends ByteBuffer {
    // For speed these fields are actually declared in X-Buffer;
    // these declarations are here as documentation
    /*
    protected final byte[] hb;
    protected final int offset;
    */

    HeapByteBuffer(int cap, int lim, MemorySegmentProxy segment) {            // package-private
        super(-1, 0, lim, cap, new byte[cap], 0, segment);
        /*
        hb = new byte[cap];
        offset = 0;
        */
        this.address = ARRAY_BASE_OFFSET;
    }
} 
```

```java
public abstract class ByteBuffer extends Buffer implements Comparable<ByteBuffer> {
    public static ByteBuffer wrap(byte[] array, int offset, int length) {
        try {
            return new HeapByteBuffer(array, offset, length, null);
        } catch (IllegalArgumentException x) {
            throw new IndexOutOfBoundsException();
        }
    }
}
```




### MappedByteBuffer

一种 direct byte buffer，其内容是文件的内存映射区域。

MappedByteBuffer属于映射buffer（自己看看虚拟内存），但是DirectByteBuffer只是说明该部分内存是JVＭ在直接内存区分配的连续缓冲区，并不一是映射的。也就是说MappedByteBuffer应该是DirectByteBuffer的子类，但是为了方便和优化，把MappedByteBuffer作为了DirectByteBuffer的父类。另外，虽然MappedByteBuffer在逻辑上应该是DirectByteBuffer的子类，而且MappedByteBuffer的内存的GC和直接内存的GC类似（和堆GC不同），但是分配的MappedByteBuffer的大小不受-XX:MaxDirectMemorySize参数影响。
MappedByteBuffer封装的是内存映射文件操作，也就是只能进行文件IO操作。MappedByteBuffer是根据mmap产生的映射缓冲区，这部分缓冲区被映射到对应的文件页上，属于直接内存在用户态，通过MappedByteBuffer可以直接操作映射缓冲区，而这部分缓冲区又被映射到文件页上，操作系统通过对应内存页的调入和调出完成文件的写入和写出




```java
public abstract class MappedByteBuffer
    extends ByteBuffer {
    private final FileDescriptor fd;
    private final boolean isSync;

    // This should only be invoked by the DirectByteBuffer constructors
    //
    MappedByteBuffer(int mark, int pos, int lim, int cap, // package-private
                     FileDescriptor fd, boolean isSync, MemorySegmentProxy segment) {
        super(mark, pos, lim, cap, segment);
        this.fd = fd;
        this.isSync = isSync;
    }
}
```

Mapped byte buffer 通过 FileChannel.map 方法创建。

映射信息封装到Unmapper中
```java
public MappedByteBuffer map(MapMode mode, long position, long size) throws IOException {
        if (size > Integer.MAX_VALUE)
            throw new IllegalArgumentException("Size exceeds Integer.MAX_VALUE");
        boolean isSync = isSync(Objects.requireNonNull(mode, "Mode is null"));
        int prot = toProt(mode);
        Unmapper unmapper = mapInternal(mode, position, size, prot, isSync);
        if (unmapper == null) {
            // a valid file descriptor is not required
            FileDescriptor dummy = new FileDescriptor();
            if ((!writable) || (prot == MAP_RO))
                return Util.newMappedByteBufferR(0, 0, dummy, null, isSync);
            else
                return Util.newMappedByteBuffer(0, 0, dummy, null, isSync);
        } else if ((!writable) || (prot == MAP_RO)) {
            return Util.newMappedByteBufferR((int)unmapper.cap,
                    unmapper.address + unmapper.pagePosition,
                    unmapper.fd,
                    unmapper, isSync);
        } else {
            return Util.newMappedByteBuffer((int)unmapper.cap,
                    unmapper.address + unmapper.pagePosition,
                    unmapper.fd,
                    unmapper, isSync);
        }
    }
```
调用到native方法 map0 若捕获到的OOM 会先尝试触发一次 System.gc 再重试 map0 若依旧 OOM 则将以 IOException(Map failed) 的形式抛出

```java
private Unmapper mapInternal(MapMode mode, long position, long size, int prot, boolean isSync)
        throws IOException
    {
        ensureOpen();
        // check ...
        long addr = -1;
        int ti = -1;
        try {
            beginBlocking();
            ti = threads.add();
            if (!isOpen())
                return null;

            long mapSize;
            int pagePosition;
            synchronized (positionLock) {
                long filesize;
                do {
                    long comp = Blocker.begin();
                    try {
                        filesize = nd.size(fd);
                    } finally {
                        Blocker.end(comp);
                    }
                } while ((filesize == IOStatus.INTERRUPTED) && isOpen());
                if (!isOpen())
                    return null;

                if (filesize < position + size) { // Extend file size
                    if (!writable) {
                        throw new IOException("Channel not open for writing " +
                            "- cannot extend file to required size");
                    }
                    int rv;
                    do {
                        long comp = Blocker.begin();
                        try {
                            rv = nd.truncate(fd, position + size);
                        } finally {
                            Blocker.end(comp);
                        }
                    } while ((rv == IOStatus.INTERRUPTED) && isOpen());
                    if (!isOpen())
                        return null;
                }

                if (size == 0) {
                    return null;
                }

                pagePosition = (int)(position % allocationGranularity);
                long mapPosition = position - pagePosition;
                mapSize = size + pagePosition;
                try {
                    // If map0 did not throw an exception, the address is valid
                    addr = map0(fd, prot, mapPosition, mapSize, isSync);
                } catch (OutOfMemoryError x) {
                    // An OutOfMemoryError may indicate that we've exhausted
                    // memory so force gc and re-attempt map
                    System.gc();
                    try {
                        Thread.sleep(100);
                    } catch (InterruptedException y) {
                        Thread.currentThread().interrupt();
                    }
                    try {
                        addr = map0(fd, prot, mapPosition, mapSize, isSync);
                    } catch (OutOfMemoryError y) {
                        // After a second OOME, fail
                        throw new IOException("Map failed", y);
                    }
                }
            } // synchronized

            // On Windows, and potentially other platforms, we need an open
            // file descriptor for some mapping operations.
            FileDescriptor mfd;
            try {
                mfd = nd.duplicateForMapping(fd);
            } catch (IOException ioe) {
                unmap0(addr, mapSize);
                throw ioe;
            }

            Unmapper um = (isSync
                           ? new SyncUnmapper(addr, mapSize, size, mfd, pagePosition)
                           : new DefaultUnmapper(addr, mapSize, size, mfd, pagePosition));
            return um;
        } finally {
            threads.remove(ti);
            endBlocking(IOStatus.checkAll(addr));
        }
}
```

```java
// FileChannelImpl.java
private native long map0(int prot, long position, long length, boolean isSync)
        throws IOException;
```
##### map0

map0 调用的 `mmap64` 函数 指向了[Linux mmap](/docs/CS/OS/Linux/mm/mmap.md)

```c
// UnixFileDispatcherImpl.c

#define mmap64 mmap

JNIEXPORT jlong JNICALL
Java_sun_nio_ch_UnixFileDispatcherImpl_map0(JNIEnv *env, jclass klass, jobject fdo,
jint prot, jlong off, jlong len,
jboolean map_sync)
{
void *mapAddress = 0;
jint fd = fdval(env, fdo);
int protections = 0;
int flags = 0;

    // should never be called with map_sync and prot == PRIVATE
    assert((prot != sun_nio_ch_UnixFileDispatcherImpl_MAP_PV) || !map_sync);

    if (prot == sun_nio_ch_UnixFileDispatcherImpl_MAP_RO) {
        protections = PROT_READ;
        flags = MAP_SHARED;
    } else if (prot == sun_nio_ch_UnixFileDispatcherImpl_MAP_RW) {
        protections = PROT_WRITE | PROT_READ;
        flags = MAP_SHARED;
    } else if (prot == sun_nio_ch_UnixFileDispatcherImpl_MAP_PV) {
        protections =  PROT_WRITE | PROT_READ;
        flags = MAP_PRIVATE;
    }

    // if MAP_SYNC and MAP_SHARED_VALIDATE are not defined then it is
    // best to define them here. This ensures the code compiles on old
    // OS releases which do not provide the relevant headers. If run
    // on the same machine then it will work if the kernel contains
    // the necessary support otherwise mmap should fail with an
    // invalid argument error

#ifndef MAP_SYNC
#define MAP_SYNC 0x80000
#endif
#ifndef MAP_SHARED_VALIDATE
#define MAP_SHARED_VALIDATE 0x03
#endif

    if (map_sync) {
        // ensure
        //  1) this is Linux on AArch64, x86_64, or PPC64 LE
        //  2) the mmap APIs are available at compile time
#if !defined(LINUX) || ! (defined(aarch64) || (defined(amd64) && defined(_LP64)) || defined(ppc64le))
// TODO - implement for solaris/AIX/BSD/WINDOWS and for 32 bit
JNU_ThrowInternalError(env, "should never call map on platform where MAP_SYNC is unimplemented");
return IOS_THROWN;
#else
flags |= MAP_SYNC | MAP_SHARED_VALIDATE;
#endif
}

    mapAddress = mmap64(
        0,                    /* Let OS decide location */
        len,                  /* Number of bytes to map */
        protections,          /* File permissions */
        flags,                /* Changes are shared */
        fd,                   /* File descriptor of mapped file */
        off);                 /* Offset into file */

    if (mapAddress == MAP_FAILED) {
        if (map_sync && errno == ENOTSUP) {
            JNU_ThrowIOExceptionWithLastError(env, "map with mode MAP_SYNC unsupported");
            return IOS_THROWN;
        }

        if (errno == ENOMEM) {
            JNU_ThrowOutOfMemoryError(env, "Map failed");
            return IOS_THROWN;
        }
        return handle(env, -1, "Map failed");
    }

    return ((jlong) (unsigned long) mapAddress);
}
```


后续 JVM 进程在访问这段 MappedByteBuffer 的时候就相当于是直接访问映射文件的 page cache。整个过程是在用户态进行，不需要切态。

假设现在系统中有两个 JVM 进程同时通过 mmap 对同一个磁盘文件上的同一段文件区域进行私有内存映射，那么这两个 JVM 进程就会在各自的内存空间中获取到一段属于各自的 MappedByteBuffer（进程的虚拟内存空间是相互隔离的）。

现在第一个 JVM 进程已经访问过它的 MappedByteBuffer 了，并且已经完成了缺页处理，但是第二个 JVM 进程还没有访问过它的 MappedByteBuffer，所以 JVM  进程2 页表中相应的 pte 还是空的，它访问这段 MappedByteBuffer 的时候仍然会产生缺页中断。

但是 进程2 的缺页处理就很简单了，因为前面 进程1 已经通过缺页中断将映射的文件内容加载到 page cache 中了，所以 进程2 进入到内核中一下就在 page cache 中找到它所需要的文件页了，与属于它的 MappedByteBuffer 通过页表关联一下就可以了。同样是因为采用私有文件映射的原因，进程 2 的这个页表项 pte 也是只读的

#### Unmapper

```java
// FileChannelImpl.java
private static abstract class Unmapper
        implements Runnable, UnmapperProxy {
    // may be required to close file
    private static final NativeDispatcher nd = new FileDispatcherImpl();

    private volatile long address;
    protected final long size;
    protected final long cap;
    private final FileDescriptor fd;
    private final int pagePosition;

    private Unmapper(long address, long size, long cap,
                     FileDescriptor fd, int pagePosition) {
        assert (address != 0);
        this.address = address;
        this.size = size;
        this.cap = cap;
        this.fd = fd;
        this.pagePosition = pagePosition;
    }
}
```


#### load

```java
public abstract class MappedByteBuffer extends ByteBuffer
{
  public final MappedByteBuffer load() {
    if (fd == null) {
      return this;
    }
    try {
      SCOPED_MEMORY_ACCESS.load(session(), address, isSync, capacity());
    } finally {
      Reference.reachabilityFence(this);
    }
    return this;
  }
}
```


```c
// MappedMemoryUtils.c 
JNIEXPORT void JNICALL
Java_java_nio_MappedMemoryUtils_load0(JNIEnv *env, jobject obj, jlong address,
                                     jlong len)
{
    char *a = (char *)jlong_to_ptr(address);
    int result = madvise((caddr_t)a, (size_t)len, MADV_WILLNEED);
    if (result == -1) {
        JNU_ThrowIOExceptionWithMessageAndLastError(env, "madvise with advise MADV_WILLNEED failed");
    }
}
```

load0 方法在 native 层面调用了一个叫做 madvise 的系统调用

这里我们用到的 advice 选项为 MADV_WILLNEED ，该选项用来告诉内核我们将会马上访问这段虚拟内存，内核在收到这个建议之后，将会马上触发一次预读操作，尽可能将 MappedByteBuffer 背后映射的文件内容全部加载到 page cache 中

madvise 这里只是负责将 MappedByteBuffer 映射的文件内容加载到内存中（page cache），并不负责将 MappedByteBuffer（虚拟内存） 与 page cache 中的这些文件页（物理内存）进行关联映射，也就是说此时 MappedByteBuffer 在 JVM 进程页表中相关的页表项 PTE 还是空的。
所以 JDK 在调用完 load0 方法之后，还需要再次按照内存页的粒度对 MappedByteBuffer 进行访问，目的是触发缺页中断，在缺页中断处理中内核会将 MappedByteBuffer 与 page cache 通过进程页表关联映射起来。后续我们在对 MappedByteBuffer 进行访问就是直接访问 page cache 了，没有缺页中断也没有磁盘 IO 的开销

MappedByteBuffer 的 load 逻辑 , JDK 封装在 MappedMemoryUtils 类中


在进入 load0 native 实现之前，需要做一些转换工作。首先通过 mappingOffset 根据 MappedByteBuffer 的起始地址 address 计算出 address 距离其所在文件页的起始地址的长度，

```java
class MappedMemoryUtils {
    static void load(long address, boolean isSync, long size) {
        // no need to load a sync mapped buffer
        if (isSync) {
            return;
        }
        if ((address == 0) || (size == 0))
            return;
        long offset = mappingOffset(address);
        long length = mappingLength(offset, size);
        load0(mappingAddress(address, offset), length);

        // Read a byte from each page to bring it into memory. A checksum
        // is computed as we go along to prevent the compiler from otherwise
        // considering the loop as dead code.
        Unsafe unsafe = Unsafe.getUnsafe();
        int ps = Bits.pageSize();
        long count = Bits.pageCount(length);
        long a = mappingAddress(address, offset);
        byte x = 0;
        for (long i=0; i<count; i++) {
            // TODO consider changing to getByteOpaque thus avoiding
            // dead code elimination and the need to calculate a checksum
            x ^= unsafe.getByte(a);
            a += ps;
        }
        if (unused != 0)
            unused = x;
    }
}
```
#### handle_pte_fault

当我们开始访问这段 MappedByteBuffer 的时候， CPU 会将 MappedByteBuffer 背后的虚拟内存地址送到 MMU 地址翻译单元中进行地址翻译查找其背后的物理内存地址
如果 MMU 发现 MappedByteBuffer 在 JVM 进程页表中对应的页表项 PTE 还是空的，这说明 MappedByteBuffer 是刚刚被 mmap 系统调用映射出来的，还没有分配物理内存。
于是 MMU 就会产生缺页中断，随后 JVM  进程切入到内核态，进行缺页处理，为 MappedByteBuffer 分配物理内存


```c
static vm_fault_t handle_pte_fault(struct vm_fault *vmf)
{
	pte_t entry;

	if (unlikely(pmd_none(*vmf->pmd))) {
		/*
		 * Leave __pte_alloc() until later: because vm_ops->fault may
		 * want to allocate huge page, and if we expose page table
		 * for an instant, it will be difficult to retract from
		 * concurrent faults and from rmap lookups.
		 */
		vmf->pte = NULL;
		vmf->flags &= ~FAULT_FLAG_ORIG_PTE_VALID;
	} else {
		pmd_t dummy_pmdval;

		/*
		 * A regular pmd is established and it can't morph into a huge
		 * pmd by anon khugepaged, since that takes mmap_lock in write
		 * mode; but shmem or file collapse to THP could still morph
		 * it into a huge pmd: just retry later if so.
		 *
		 * Use the maywrite version to indicate that vmf->pte may be
		 * modified, but since we will use pte_same() to detect the
		 * change of the !pte_none() entry, there is no need to recheck
		 * the pmdval. Here we chooes to pass a dummy variable instead
		 * of NULL, which helps new user think about why this place is
		 * special.
		 */
		vmf->pte = pte_offset_map_rw_nolock(vmf->vma->vm_mm, vmf->pmd,
						    vmf->address, &dummy_pmdval,
						    &vmf->ptl);
		if (unlikely(!vmf->pte))
			return 0;
		vmf->orig_pte = ptep_get_lockless(vmf->pte);
		vmf->flags |= FAULT_FLAG_ORIG_PTE_VALID;

		if (pte_none(vmf->orig_pte)) {
			pte_unmap(vmf->pte);
			vmf->pte = NULL;
		}
	}

	if (!vmf->pte)
		return do_pte_missing(vmf);

	if (!pte_present(vmf->orig_pte))
		return do_swap_page(vmf);

	if (pte_protnone(vmf->orig_pte) && vma_is_accessible(vmf->vma))
		return do_numa_page(vmf);

	spin_lock(vmf->ptl);
	entry = vmf->orig_pte;
	if (unlikely(!pte_same(ptep_get(vmf->pte), entry))) {
		update_mmu_tlb(vmf->vma, vmf->address, vmf->pte);
		goto unlock;
	}
	if (vmf->flags & (FAULT_FLAG_WRITE|FAULT_FLAG_UNSHARE)) {
		if (!pte_write(entry))
			return do_wp_page(vmf);
		else if (likely(vmf->flags & FAULT_FLAG_WRITE))
			entry = pte_mkdirty(entry);
	}
	entry = pte_mkyoung(entry);
	if (ptep_set_access_flags(vmf->vma, vmf->address, vmf->pte, entry,
				vmf->flags & FAULT_FLAG_WRITE)) {
		update_mmu_cache_range(vmf, vmf->vma, vmf->address,
				vmf->pte, 1);
	} else {
		/* Skip spurious TLB flush for retried page fault */
		if (vmf->flags & FAULT_FLAG_TRIED)
			goto unlock;
		/*
		 * This is needed only for protection faults but the arch code
		 * is not yet telling us if this is a protection fault or not.
		 * This still avoids useless tlb flushes for .text page faults
		 * with threads.
		 */
		if (vmf->flags & FAULT_FLAG_WRITE)
			flush_tlb_fix_spurious_fault(vmf->vma, vmf->address,
						     vmf->pte);
	}
unlock:
	pte_unmap_unlock(vmf->pte, vmf->ptl);
	return 0;
}
```


filemap_fault

```c
vm_fault_t filemap_fault(struct vm_fault *vmf)
{
	int error;
	struct file *file = vmf->vma->vm_file;
	struct file *fpin = NULL;
	struct address_space *mapping = file->f_mapping;
	struct inode *inode = mapping->host;
	pgoff_t max_idx, index = vmf->pgoff;
	struct folio *folio;
	vm_fault_t ret = 0;
	bool mapping_locked = false;

	max_idx = DIV_ROUND_UP(i_size_read(inode), PAGE_SIZE);
	if (unlikely(index >= max_idx))
		return VM_FAULT_SIGBUS;

	trace_mm_filemap_fault(mapping, index);

	/*
	 * Do we have something in the page cache already?
	 */
	folio = filemap_get_folio(mapping, index);
	if (likely(!IS_ERR(folio))) {
		/*
		 * We found the page, so try async readahead before waiting for
		 * the lock.
		 */
		if (!(vmf->flags & FAULT_FLAG_TRIED))
			fpin = do_async_mmap_readahead(vmf, folio);
		if (unlikely(!folio_test_uptodate(folio))) {
			filemap_invalidate_lock_shared(mapping);
			mapping_locked = true;
		}
	} else {
		ret = filemap_fault_recheck_pte_none(vmf);
		if (unlikely(ret))
			return ret;

		/* No page in the page cache at all */
		count_vm_event(PGMAJFAULT);
		count_memcg_event_mm(vmf->vma->vm_mm, PGMAJFAULT);
		ret = VM_FAULT_MAJOR;
		fpin = do_sync_mmap_readahead(vmf);
retry_find:
		/*
		 * See comment in filemap_create_folio() why we need
		 * invalidate_lock
		 */
		if (!mapping_locked) {
			filemap_invalidate_lock_shared(mapping);
			mapping_locked = true;
		}
		folio = __filemap_get_folio(mapping, index,
					  FGP_CREAT|FGP_FOR_MMAP,
					  vmf->gfp_mask);
		if (IS_ERR(folio)) {
			if (fpin)
				goto out_retry;
			filemap_invalidate_unlock_shared(mapping);
			return VM_FAULT_OOM;
		}
	}

	if (!lock_folio_maybe_drop_mmap(vmf, folio, &fpin))
		goto out_retry;

	/* Did it get truncated? */
	if (unlikely(folio->mapping != mapping)) {
		folio_unlock(folio);
		folio_put(folio);
		goto retry_find;
	}
	VM_BUG_ON_FOLIO(!folio_contains(folio, index), folio);

	/*
	 * We have a locked folio in the page cache, now we need to check
	 * that it's up-to-date. If not, it is going to be due to an error,
	 * or because readahead was otherwise unable to retrieve it.
	 */
	if (unlikely(!folio_test_uptodate(folio))) {
		/*
		 * If the invalidate lock is not held, the folio was in cache
		 * and uptodate and now it is not. Strange but possible since we
		 * didn't hold the page lock all the time. Let's drop
		 * everything, get the invalidate lock and try again.
		 */
		if (!mapping_locked) {
			folio_unlock(folio);
			folio_put(folio);
			goto retry_find;
		}

		/*
		 * OK, the folio is really not uptodate. This can be because the
		 * VMA has the VM_RAND_READ flag set, or because an error
		 * arose. Let's read it in directly.
		 */
		goto page_not_uptodate;
	}

	/*
	 * We've made it this far and we had to drop our mmap_lock, now is the
	 * time to return to the upper layer and have it re-find the vma and
	 * redo the fault.
	 */
	if (fpin) {
		folio_unlock(folio);
		goto out_retry;
	}
	if (mapping_locked)
		filemap_invalidate_unlock_shared(mapping);

	/*
	 * Found the page and have a reference on it.
	 * We must recheck i_size under page lock.
	 */
	max_idx = DIV_ROUND_UP(i_size_read(inode), PAGE_SIZE);
	if (unlikely(index >= max_idx)) {
		folio_unlock(folio);
		folio_put(folio);
		return VM_FAULT_SIGBUS;
	}

	vmf->page = folio_file_page(folio, index);
	return ret | VM_FAULT_LOCKED;

page_not_uptodate:
	/*
	 * Umm, take care of errors if the page isn't up-to-date.
	 * Try to re-read it _once_. We do this synchronously,
	 * because there really aren't any performance issues here
	 * and we need to check for errors.
	 */
	fpin = maybe_unlock_mmap_for_io(vmf, fpin);
	error = filemap_read_folio(file, mapping->a_ops->read_folio, folio);
	if (fpin)
		goto out_retry;
	folio_put(folio);

	if (!error || error == AOP_TRUNCATED_PAGE)
		goto retry_find;
	filemap_invalidate_unlock_shared(mapping);

	return VM_FAULT_SIGBUS;

out_retry:
	/*
	 * We dropped the mmap_lock, we need to return to the fault handler to
	 * re-find the vma and come back and find our hopefully still populated
	 * page.
	 */
	if (!IS_ERR(folio))
		folio_put(folio);
	if (mapping_locked)
		filemap_invalidate_unlock_shared(mapping);
	if (fpin)
		fput(fpin);
	return ret | VM_FAULT_RETRY;
}
EXPORT_SYMBOL(filemap_fault);
```




## Selectors

Selector 是一个可以监视多个 channel 事件（如：连接打开、数据到达等）的对象。
因此，单个线程可以监视多个 channel 的数据。

轮询注册的channel状态
SelectorProvider sychronized 单例
依据不同JDK生成不同的Selector实现类
调用OS的接口创建FD

可选择的 channel 在 selector 上的注册由 SelectionKey 对象表示。Selector 维护三组 selection key：

- key 集包含表示此 selector 当前 channel 注册的 key。此集合由 keys 方法返回。
- selected-key 集是 key 的集合，其中每个 key 的 channel 在先前将 key 添加或更新到集中的选择操作期间，被检测为准备好执行该 key 的 interest 集中标识的至少一个操作。
  此集合由 selectedKeys 方法返回。selected-key 集始终是 key 集的子集。
- cancelled-key 集是已被取消但其 channel 尚未注销的 key 的集合。
  此集合不能直接访问。cancelled-key 集始终是 key 集的子集。

在新建的 selector 中，所有三个集合都是空的。


[Epoll](https://hg.openjdk.org/jdk/jdk/file/d8327f838b88/src/java.base/linux/classes/sun/nio/ch/EPollSelectorImpl.java)

### SelectorProvider

```java
//java.nio.channels.spi.SelectorProvider#provider()
public static SelectorProvider provider() {
        synchronized (lock) {
            if (provider != null)
                return provider;
            return AccessController.doPrivileged(
                new PrivilegedAction<SelectorProvider>() {
                    public SelectorProvider run() {
                            if (loadProviderFromProperty())
                                return provider;
                            if (loadProviderAsService())
                                return provider;
                            provider = sun.nio.ch.DefaultSelectorProvider.create();
                            return provider;
                        }
                    });
        }
    }

//sun.nio.ch.DefaultSelectorProvider.create()
public static SelectorProvider create() {
        String osname = AccessController
            .doPrivileged(new GetPropertyAction("os.name"));
        if (osname.equals("SunOS"))
            return createProvider("sun.nio.ch.DevPollSelectorProvider");
        if (osname.equals("Linux"))
            return createProvider("sun.nio.ch.EPollSelectorProvider");
        return new sun.nio.ch.PollSelectorProvider();
    }
```

See [Netty EventLoop - Selector](/docs/CS/Framework/Netty/EventLoop.md?id=Selector).

### Selection

选择操作查询底层操作系统以获取每个已注册 channel 准备好执行由其 key 的 interest 集标识的任何操作的更新。有两种形式的选择操作：

- select()、select(long) 和 selectNow() 方法将准备好执行操作的 channel 的 key 添加到 selected-key 集，或更新已在 selected-key 集中的 key 的 ready-operation 集。
- select(Consumer)、select(Consumer, long) 和 selectNow(Consumer) 方法在每个准备好执行操作的 channel 的 key 上执行操作。这些方法不会添加到 selected-key 集。

添加到 selected-key 集的选择操作

在每个选择操作期间，key 可能会被添加和删除到 selector 的 selected-key 集，并可能从其 key 和 cancelled-key 集中删除。选择由 select()、select(long) 和 selectNow() 方法执行，涉及三个步骤：

- cancelled-key 集中的每个 key 从其所属的每个 key 集中移除，并且其 channel 被注销。此步骤使 cancelled-key 集为空。
- 查询底层操作系统以获取每个剩余 channel 准备好执行由其 key 的 interest 集标识的任何操作的更新。
  对于一个至少准备好一个此类操作的 channel，执行以下两种操作之一：
  - 如果 channel 的 key 尚未在 selected-key 集中，则将其添加到该集，并修改其 ready-operation 集以标识 channel 现在被报告为准备好的确切操作。
    先前在 ready 集中记录的任何 readiness 信息将被丢弃。
  - 否则 channel 的 key 已在 selected-key 集中，因此修改其 ready-operation 集以标识 channel 被报告为准备好的任何新操作。
    先前在 ready 集中记录的任何 readiness 信息将被保留；换句话说，底层系统返回的 ready 集按位分离到 key 的当前 ready 集中。
- 如果在此步骤开始时 key 集中的所有 key 都具有空的 interest 集，则 selected-key 集和任何 key 的 ready-operation 集都不会更新。
- 如果在步骤（2）进行过程中有任何 key 被添加到 cancelled-key 集，则它们将按照步骤（1）处理。

选择操作是否阻塞等待一个或多个 channel 变为就绪，以及阻塞多长时间，是这三种选择方法之间唯一的本质区别。

在选定 key 上执行操作的选择操作

在每个选择操作期间，key 可能会从 selector 的 key、selected-key 和 cancelled-key 集中删除。选择由 select(Consumer)、select(Consumer, long) 和 selectNow(Consumer) 方法执行，涉及三个步骤：

- cancelled-key 集中的每个 key 从其所属的每个 key 集中移除，并且其 channel 被注销。此步骤使 cancelled-key 集为空。
- 查询底层操作系统以获取每个剩余 channel 准备好执行由其 key 的 interest 集标识的任何操作的更新。
  对于一个至少准备好一个此类操作的 channel，将 channel 的 key 的 ready-operation 集设置为标识 channel 准备好的确切操作，并调用指定给 select 方法的操作来消费该 channel 的 key。
  在调用该操作之前，先前在 ready 集中记录的任何 readiness 信息将被丢弃。
  或者，当一个 channel 准备好多个操作时，该操作可能会被多次调用，每次使用该 channel 的 key 和 ready-operation 集（修改为 channel 准备好的操作的子集）。
  当对同一个 key 多次调用该操作时，其 ready-operation 集永远不会包含在同一选择操作中先前调用该操作时该集合中包含的操作位。
- 如果在步骤（2）进行过程中有任何 key 被添加到 cancelled-key 集，则它们将按照步骤（1）处理。


### Concurrency

Selector 及其 key 集可安全地被多个并发线程使用。但其 selected-key 集和 cancelled-key 集则不然。

选择操作按顺序在 selector 本身和 selected-key 集上同步。它们还在上述步骤（1）和（3）期间在 cancelled-key 集上同步。

在选择操作进行期间对 selector 的 key 的 interest 集所做的更改对该操作没有影响；它们将在下一次选择操作中可见。

Key 可以随时被取消，channel 可以随时被关闭。因此，key 出现在 selector 的一个或多个 key 集中并不表示该 key 有效或其 channel 是打开的。
应用程序代码应小心同步并在必要时检查这些条件，如果有其他线程可能取消 key 或关闭 channel。

在 selection 操作中阻塞的线程可以通过以下三种方式之一被其他线程中断：

- 通过调用 selector 的 wakeup 方法，
- 通过调用 selector 的 close 方法，或
- 通过调用阻塞线程的 interrupt 方法，在这种情况下，其中断状态将被设置，并且 selector 的 wakeup 方法将被调用。

close 方法以与 selection 操作相同的顺序在 selector 及其 selected-key 集上同步。

Selector 的 key 集可安全地被多个并发线程使用。
从 key 集进行的检索操作通常不会阻塞，因此可能与向该集添加新注册的操作重叠，或与从该集中删除 key 的选择操作的取消步骤重叠。
迭代器和 spliterator 返回反映该集在迭代器/spliterator 创建时或自创建以来某一时刻状态的元素。它们不会抛出 ConcurrentModificationException。

Selector 的 selected-key 集通常不能安全地被多个并发线程使用。
如果这样的线程可能直接修改该集，则应通过对该集本身进行同步来控制访问。
该集的 iterator 方法返回的迭代器是快速失败的（fail-fast）：如果在创建迭代器后以任何方式修改该集（除了调用迭代器自身的 remove 方法之外），则将抛出 java.util.ConcurrentModificationException。


### select

选择一组其对应 channel 已准备好进行 I/O 操作的 key。

`select()` 和 `select(timeout)` 方法都执行阻塞选择操作。
并且只有在至少选择一个 channel、调用了此 selector 的 wakeup 方法或当前线程被中断时（以先发生者为准）才返回。
`select(timeout)` 方法也会在给定的超时期限到期后返回。
此方法不提供实时保证：它通过调用 Object.wait(long) 方法来调度超时。

`selectNow()` 方法执行非阻塞选择操作。
如果自上次选择操作以来没有 channel 变为可选择，则此方法立即返回零。
调用此方法会清除之前任何 wakeup 方法调用的效果。

```java

public abstract int select() throws IOException;

public abstract int select(long timeout) throws IOException;

public abstract int selectNow() throws IOException;
```

### wakeup

导致第一个尚未返回的选择操作立即返回。

如果另一个线程当前在 selection 操作中阻塞，则该调用将立即返回。
如果当前没有 selection 操作在进行，则下一次 selection 操作调用将立即返回，除非在此期间调用了 selectNow() 或 selectNow(Consumer)。
在任何情况下，该调用返回的值可能非零。
后续的 selection 操作将像往常一样阻塞，除非在此期间再次调用此方法。
> [!TIP]
>
> 在两个连续的选择操作之间多次调用此方法与仅调用一次效果相同。

```java
public abstract Selector wakeup();
```


## Links

## Reference

1. [Java NIO Tutorial](http://tutorials.jenkov.com/java-nio/index.html)
2. [从 Linux 内核角度探秘 JDK MappedByteBuffer](https://mp.weixin.qq.com/s?__biz=Mzg2MzU3Mjc3Ng==&mid=2247489304&idx=1&sn=18e905f573906ecff411ebdcf9c1a9c5&chksm=ce77d15ff9005849b022e4288e793e5036bda42916591a4a3d28f76554188c25cfbd35d951f9&cur_album_id=2486138956225757185&scene=190#rd)
