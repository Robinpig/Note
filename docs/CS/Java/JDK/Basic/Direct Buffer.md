# Direct Buffer



How to allocate direct memory?

1. `ByteBuffer.allocteDirect` invoke `Unsafe.allocateMemory`
2. `Unsafe.allocateMemory`



```cpp
//unsafe.cpp
UNSAFE_ENTRY(jlong, Unsafe_AllocateMemory0(JNIEnv *env, jobject unsafe, jlong size)) {
  size_t sz = (size_t)size;

  sz = align_up(sz, HeapWordSize);
  void* x = os::malloc(sz, mtOther);

  return addr_to_java(x);
} UNSAFE_END

UNSAFE_ENTRY(void, Unsafe_FreeMemory0(JNIEnv *env, jobject unsafe, jlong addr)) {
  void* p = addr_from_java(addr);

  os::free(p);
} UNSAFE_END
```

`Unsafe.allocateMemory/freeMemory` invoke `os::malloc/free ` finally use `glib::malloc/free`.



## create DirectByteBuffer

```java
//ByteBuffer.java 
public static ByteBuffer allocateDirect(int capacity) {
    return new DirectByteBuffer(capacity);
}

//DirectByteBuffer.java
// Primary constructor
DirectByteBuffer(int cap) {                   // package-private
    super(-1, 0, cap, cap);
    boolean pa = VM.isDirectMemoryPageAligned();
    int ps = Bits.pageSize();
    long size = Math.max(1L, (long)cap + (pa ? ps : 0));
    Bits.reserveMemory(size, cap);//reserveMemory

    long base = 0;
    try {
        base = unsafe.allocateMemory(size);//finally invoke unsafe.allocateMemory
    } catch (OutOfMemoryError x) {
        Bits.unreserveMemory(size, cap);
        throw x;
    }
    //init memory
    unsafe.setMemory(base, size, (byte) 0);
    if (pa && (base % ps != 0)) {
        // Round up to page boundary
        address = base + ps - (base & (ps - 1));
    } else {
        address = base;
    }
    //create a cleaner to recycle direct memory when directByteBuffer instance unused
    cleaner = Cleaner.create(this, new Deallocator(base, size, cap));
    att = null;
}
```





```java
public class Cleaner extends PhantomReference<Object> {
    private Cleaner(Object referent, Runnable thunk) {
        super(referent, dummyQueue);
        this.thunk = thunk;
    }
    public void clean() {
        if (remove(this)) {
                //thunk = new Deallocator at this time
                this.thunk.run();
        }
    }
}

private static class Deallocator
    implements Runnable
    {
        private static Unsafe unsafe = Unsafe.getUnsafe();

        private long address;
        private long size;
        private int capacity;

        private Deallocator(long address, long size, int capacity) {
            assert (address != 0);
            this.address = address;
            this.size = size;
            this.capacity = capacity;
        }

        public void run() {
            if (address == 0) {
                // Paranoia
                return;
            }
            //invoke unsafe.freeMemory
            unsafe.freeMemory(address);
            address = 0;
            Bits.unreserveMemory(size, capacity);
        }

    }
```



[Cleaner extends PhantomReference](/docs/CS/Java/JDK/Basic/Ref.md)



```java
// A user-settable upper limit on the maximum amount of allocatable
// direct buffer memory.  This value may be changed during VM
// initialization if it is launched with "-XX:MaxDirectMemorySize=<size>".
private static volatile long maxMemory = VM.maxDirectMemory();

// These methods should be called whenever direct memory is allocated or
// freed.  They allow the user to control the amount of direct memory
// which a process may access.  All sizes are specified in bytes.
static void reserveMemory(long size, int cap) {

    if (!memoryLimitSet && VM.isBooted()) {
        maxMemory = VM.maxDirectMemory();
        memoryLimitSet = true;
    }

    // optimist!
    if (tryReserveMemory(size, cap)) {
        return;
    }

    final JavaLangRefAccess jlra = SharedSecrets.getJavaLangRefAccess();

    // retry while helping enqueue pending Reference objects
    // which includes executing pending Cleaner(s) which includes
    // Cleaner(s) that free direct buffer memory
    while (jlra.tryHandlePendingReference()) {
        if (tryReserveMemory(size, cap)) {
            return;
        }
    }

    // trigger VM's Reference processing
    System.gc();//disable on -XX:+DisableExplicitGC 

    // a retry loop with exponential back-off delays
    // (this gives VM some time to do it's job)
    boolean interrupted = false;
    try {
        long sleepTime = 1;
        int sleeps = 0;
        while (true) {
            if (tryReserveMemory(size, cap)) {
                return;
            }
            if (sleeps >= MAX_SLEEPS) {//MAX_SLEEPS = 9
                break;
            }
            if (!jlra.tryHandlePendingReference()) {
                try {
                    Thread.sleep(sleepTime);
                    sleepTime <<= 1;
                    sleeps++;
                } catch (InterruptedException e) {
                    interrupted = true;
                }
            }
        }

        // no luck
        throw new OutOfMemoryError("Direct buffer memory");

    } finally {
        if (interrupted) {
            // don't swallow interrupts
            Thread.currentThread().interrupt();
        }
    }
}

private static boolean tryReserveMemory(long size, int cap) {
    // -XX:MaxDirectMemorySize limits the total capacity rather than the
    // actual memory usage, which will differ when buffers are page
    // aligned.
    long totalCap;
    while (cap <= maxMemory - (totalCap = totalCapacity.get())) {
        if (totalCapacity.compareAndSet(totalCap, totalCap + cap)) {
            reservedMemory.addAndGet(size);
            count.incrementAndGet();
            return true;
        }
    }

    return false;
}

static boolean tryHandlePending(boolean waitForNotify) {
    Reference<Object> r;
    Cleaner c;
    try {
        synchronized (lock) {
            if (pending != null) {
                r = pending;
                // 'instanceof' might throw OutOfMemoryError sometimes
                // so do this before un-linking 'r' from the 'pending' chain...
                c = r instanceof Cleaner ? (Cleaner) r : null;
                // unlink 'r' from 'pending' chain
                pending = r.discovered;
                r.discovered = null;
            } else {
                // The waiting on the lock may cause an OutOfMemoryError
                // because it may try to allocate exception objects.
                if (waitForNotify) {
                    lock.wait();
                }
                // retry if waited
                return waitForNotify;
            }
        }
    } catch (OutOfMemoryError x) {
        // Give other threads CPU time so they hopefully drop some live references
        // and GC reclaims some space.
        // Also prevent CPU intensive spinning in case 'r instanceof Cleaner' above
        // persistently throws OOME for some time...
        Thread.yield();
        // retry
        return true;
    } catch (InterruptedException x) {
        // retry
        return true;
    }

    // Fast path for cleaners
    if (c != null) {
        c.clean();
        return true;
    }

    ReferenceQueue<? super Object> q = r.queue;
    if (q != ReferenceQueue.NULL) q.enqueue(r);
    return true;
}
```
cerate DirecByteBuffer


1. `reserveMemory`
1. if has enough memory, return
   2. Else `tryHandlePendingReference` free memory util enough memory
   3. `System.gc()`
   4. Continue step 1, 2 util enough memory or MAX_SLEEPS
   5. if still no enough memory, OOM
3. `unsafe.allocateMemory`
3. init memory with `(byte) 0`
4. create a `Cleaner` with `Deallocator` to free direct memory when directByteBuffer instance unused



## write

BIO

BIO的文件写`FileOutputStream#write`最终会调用到native层的`io_util.c#writeBytes`方法

```cpp
void
writeBytes(JNIEnv *env, jobject this, jbyteArray bytes,
           jint off, jint len, jboolean append, jfieldID fid)
{
    jint n;
    char stackBuf[BUF_SIZE];
    char *buf = NULL;
    FD fd;

 	...

    // 如果写入长度为0，直接返回0
    if (len == 0) {
        return;
    } else if (len > BUF_SIZE) {
        // 如果写入长度大于BUF_SIZE（8192），无法使用栈空间buffer
        // 需要调用malloc在堆空间申请buffer
        buf = malloc(len);
        if (buf == NULL) {
            JNU_ThrowOutOfMemoryError(env, NULL);
            return;
        }
    } else {
        buf = stackBuf;
    }

    // 复制Java传入的byte数组数据到C空间的buffer中
    (*env)->GetByteArrayRegion(env, bytes, off, len, (jbyte *)buf);
 	
     if (!(*env)->ExceptionOccurred(env)) {
        off = 0;
        while (len > 0) {
            fd = GET_FD(this, fid);
            if (fd == -1) {
                JNU_ThrowIOException(env, "Stream Closed");
                break;
            }
            //写入到文件，这里传递的数组是我们新创建的buf
            if (append == JNI_TRUE) {
                n = (jint)IO_Append(fd, buf+off, len);
            } else {
                n = (jint)IO_Write(fd, buf+off, len);
            }
            if (n == JVM_IO_ERR) {
                JNU_ThrowIOExceptionWithLastError(env, "Write error");
                break;
            } else if (n == JVM_IO_INTR) {
                JNU_ThrowByName(env, "java/io/InterruptedIOException", NULL);
                break;
            }
            off += n;
            len -= n;
        }
    }
}
```

`GetByteArrayRegion`其实就是对数组进行了一份拷贝，该函数的实现在jni.cpp宏定义中，找了很久才找到

```cpp
//jni.cpp
JNI_ENTRY(void, \
jni_Get##Result##ArrayRegion(JNIEnv *env, ElementType##Array array, jsize start, \
             jsize len, ElementType *buf)) \
 ...
      int sc = TypeArrayKlass::cast(src->klass())->log2_element_size(); \
      //内存拷贝
      memcpy((u_char*) buf, \
             (u_char*) src->Tag##_at_addr(start), \
             len << sc);                          \
...
  } \
JNI_END
```

可以看到，传统的BIO，在native层真正写文件前，会在堆外内存（c分配的内存）中对字节数组拷贝一份，之后真正IO时，使用的是堆外的数组。





NIO

In `IOUtil.write()`

1. `if (src instanceof DirectBuffer)`, `writeFromNativeBuffer`
2. Else  copy to directBuffer from `getTemporaryDirectBuffer`

```java
static int write(FileDescriptor fd, ByteBuffer src, long position,
                 NativeDispatcher nd)
    throws IOException
{
    if (src instanceof DirectBuffer)
        return writeFromNativeBuffer(fd, src, position, nd);

    // Substitute a native buffer
    int pos = src.position();
    int lim = src.limit();
    assert (pos <= lim);
    int rem = (pos <= lim ? lim - pos : 0);
  //not DirectBuffer will 
    ByteBuffer bb = Util.getTemporaryDirectBuffer(rem);
    try {
        bb.put(src);
        bb.flip();
        // Do not update src until we see how many bytes were written
        src.position(pos);

        int n = writeFromNativeBuffer(fd, bb, position, nd);
        if (n > 0) {
            // now update src
            src.position(pos + n);
        }
        return n;
    } finally {
        Util.offerFirstTemporaryDirectBuffer(bb);
    }
}

public static ByteBuffer getTemporaryDirectBuffer(int size) {
    if (isBufferTooLarge(size)) {
        return ByteBuffer.allocateDirect(size);
    }

    BufferCache cache = bufferCache.get();
    ByteBuffer buf = cache.get(size);
    if (buf != null) {
        return buf;
    } else {
        // No suitable buffer in the cache so we need to allocate a new
        // one. To avoid the cache growing then we remove the first
        // buffer from the cache and free it.
        if (!cache.isEmpty()) {
            buf = cache.removeFirst();
            free(buf);
        }
      //Releases a temporary buffer by returning to the cache or freeing it.
        return ByteBuffer.allocateDirect(size);
    }
}
```