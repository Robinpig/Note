## Introduction

*Java* *NIO* (New IO) is an alternative IO API for Java. Note: Sometimes NIO is claimed to mean *Non-blocking IO* . However, this is not what NIO meant originally. Also, parts of the NIO APIs are actually blocking - e.g. the file APIs - so the label "Non-blocking" would be slightly misleading.

The table below summarizes the main differences between Java NIO and IO.

| IO              | NIO             |
| --------------- | --------------- |
| Stream oriented | Buffer oriented |
| Blocking IO     | Non blocking IO |
|                 | Selectors       |



Java NIO enables you to do non-blocking IO. For instance, a thread can ask a channel to read data into a buffer.
While the channel reads data into the buffer, the thread can do something else. Once data is read into the buffer, the thread can then continue processing it. The same is true for writing data to channels.



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


File channels are safe for use by multiple concurrent threads.


A file channel is created by invoking one of the open methods defined by this class. A file channel can also be obtained from an existing FileInputStream, FileOutputStream, or RandomAccessFile object by invoking that object's getChannel method, which returns a file channel that is connected to the same underlying file. Where the file channel is obtained from an existing stream or random access file then the state of the file channel is intimately connected to that of the object whose getChannel method returned the channel. Changing the channel's position, whether explicitly or by reading or writing bytes, will change the file position of the originating object, and vice versa. Changing the file's length via the file channel will change the length seen via the originating object, and vice versa. Changing the file's content by writing bytes will change the content seen by the originating object, and vice versa. Closing the channel will close the originating object.




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




transferTo0

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

A buffer is essentially a block of memory into which you can write data, which you can then later read again. 
This memory block is wrapped in a NIO Buffer object, which provides a set of methods that makes it easier to work with the memory block.


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



JDK NIO 为每一种 Java 基本类型定义了对应的 Buffer 类（boolean 类型除外）

针对每一种基本类型的 Buffer ，NIO 又根据 Buffer 背后的数据存储内存不同分为了：HeapBuffer，DirectBuffer，MappedBuffer
这三种不同类型 ByteBuffer 的本质区别就是其背后依赖的虚拟内存在 JVM 进程虚拟内存空间中的布局位置不同

位于 JVM 堆之外的内存其实都可以归属到 DirectByteBuffer 的范畴中。比如，位于 OS 堆之内，JVM 堆之外的 MetaSpace，即时编译(JIT) 之后的 codecache，JVM 线程栈，Native 线程栈，JNI 相关的内存，等等
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

A direct byte buffer whose content is a memory-mapped region of a file.

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
