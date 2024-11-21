## Introduction

*Java* *NIO* (New IO) is an alternative IO API for Java. Note: Sometimes NIO is claimed to mean *Non-blocking IO* . However, this is not what NIO meant originally. Also, parts of the NIO APIs are actually blocking - e.g. the file APIs - so the label "Non-blocking" would be slightly misleading.

The table below summarizes the main differences between Java NIO and IO.

| IO              | NIO             |
| --------------- | --------------- |
| Stream oriented | Buffer oriented |
| Blocking IO     | Non blocking IO |
|                 | Selectors       |



Java NIO enables you to do non-blocking IO. For instance, a thread can ask a channel to read data into a buffer. While the channel reads data into the buffer, the thread can do something else. Once data is read into the buffer, the thread can then continue processing it. The same is true for writing data to channels.



In NIO you work with channels and buffers. Data is always read from a channel into a buffer, or written from a buffer to a channel.

## Channels

Java NIO Channels are similar to streams with a few differences:

* You can both read and write to a Channels. Streams are typically one-way (read or write).
* Channels can be read and written asynchronously.
* Channels always read to, or write from, a Buffer.

Here are the most important Channel implementations in Java NIO:

* FileChannel
* DatagramChannel
* SocketChannel
* ServerSocketChannel


### FileChannel

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







#### transfer

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


## Buffers

A buffer is essentially a block of memory into which you can write data, which you can then later read again. This memory block is wrapped in a NIO Buffer object, which provides a set of methods that makes it easier to work with the memory block.


Capacity, Position and Limit

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

A byte buffer is either direct or non-direct. Given a direct byte buffer, the Java virtual machine will make a best effort to perform native I/ O operations directly upon it. That is, it will attempt to avoid copying the buffer's content to (or from) an intermediate buffer before (or after) each invocation of one of the underlying operating system's native I/ O operations.

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

A direct byte buffer may be created by invoking the allocateDirect factory method of this class. The buffers returned by this method typically have somewhat higher allocation and deallocation costs than non-direct buffers. The contents of direct buffers may reside outside of the normal garbage-collected heap, and so their impact upon the memory footprint of an application might not be obvious. It is therefore recommended that direct buffers be allocated primarily for large, long-lived buffers that are subject to the underlying system's native I/ O operations. In general it is best to allocate direct buffers only when they yield a measurable gain in program performance.
A direct byte buffer may also be created by mapping a region of a file directly into memory. An implementation of the Java platform may optionally support the creation of direct byte buffers from native code via JNI. If an instance of one of these kinds of buffers refers to an inaccessible region of memory then an attempt to access that region will not change the buffer's content and will cause an unspecified exception to be thrown either at the time of the access or at some later time.
Whether a byte buffer is direct or non-direct may be determined by invoking its isDirect method. This method is provided so that explicit buffer management can be done in performance-critical code.


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

A direct byte buffer whose content is a memory-mapped region of a file.


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

Mapped byte buffers are created via the FileChannel.map method.

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
调用到native方法map0

捕获到的OOM会以 OOM:Map failed抛出

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

            assert (IOStatus.checkAll(addr));
            assert (addr % allocationGranularity == 0);
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

调用的mmp64指向了[mmap](/docs/CS/OS/Linux/mm/mmap.md)

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


## Selectors

A selector is an object that can monitor multiple channels for events (like: connection opened, data arrived etc.). 
Thus, a single thread can monitor multiple channels for data.

轮询注册的channel状态
SelectorProvider sychronized 单例
依据不同JDK生成不同的Selector实现类
调用OS的接口创建FD

A selectable channel's registration with a selector is represented by a SelectionKey object. A selector maintains three sets of selection keys:

- The key set contains the keys representing the current channel registrations of this selector. This set is returned by the keys method.
- The selected-key set is the set of keys such that each key's channel was detected to be ready for at least one of the operations identified in the key's interest set during a prior selection operation that adds keys or updates keys in the set. 
  This set is returned by the selectedKeys method. The selected-key set is always a subset of the key set.
- The cancelled-key set is the set of keys that have been cancelled but whose channels have not yet been deregistered. 
  This set is not directly accessible. The cancelled-key set is always a subset of the key set.

All three sets are empty in a newly-created selector.


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

## Links

## Reference

1. [Java NIO Tutorial](http://tutorials.jenkov.com/java-nio/index.html)
2. [从 Linux 内核角度探秘 JDK MappedByteBuffer](https://mp.weixin.qq.com/s?__biz=Mzg2MzU3Mjc3Ng==&mid=2247489304&idx=1&sn=18e905f573906ecff411ebdcf9c1a9c5&chksm=ce77d15ff9005849b022e4288e793e5036bda42916591a4a3d28f76554188c25cfbd35d951f9&cur_album_id=2486138956225757185&scene=190#rd)
