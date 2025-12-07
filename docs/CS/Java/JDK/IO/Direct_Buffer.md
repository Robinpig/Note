## Introduction

How to allocate direct memory?

Allocates a new direct byte buffer.
The new buffer's position will be zero, its limit will be its capacity, its mark will be undefined, and each of its elements will be initialized to zero. 
Whether or not it has a backing array is unspecified.


```java
    // ByteBuffer
    public static ByteBuffer allocateDirect(int capacity) {
        return new DirectByteBuffer(capacity);
    }

    DirectByteBuffer(int cap) {                   // package-private
        super(-1, 0, cap, cap);
        boolean pa = VM.isDirectMemoryPageAligned();
        int ps = Bits.pageSize();
        long size = Math.max(1L, (long) cap + (pa ? ps : 0));
        Bits.reserveMemory(size, cap);

        long base = 0;
        try {
            base = unsafe.allocateMemory(size);
        } catch (OutOfMemoryError x) {
            Bits.unreserveMemory(size, cap);
            throw x;
        }
        unsafe.setMemory(base, size, (byte) 0);
        if (pa && (base % ps != 0)) {
            // Round up to page boundary
            address = base + ps - (base & (ps - 1));
        } else {
            address = base;
        }
        cleaner = Cleaner.create(this, new Deallocator(base, size, cap));
        att = null;

    }
```
检查当前 JVM 进程堆外内存是否超过了 -XX:MaxDirectMemorySize 的限制 通过检查后会执行 unsafe.allocateMemory 申请堆外内存

```java

// A user-settable upper limit on the maximum amount of allocatable direct
// buffer memory.  This value may be changed during VM initialization if
// "java" is launched with "-XX:MaxDirectMemorySize=<size>".
//
// The initial value of this field is arbitrary; during JRE initialization
// it will be reset to the value specified on the command line, if any,
// otherwise to Runtime.getRuntime().maxMemory().
//
private static long directMemory = 64 * 1024 * 1024;

```

### Unsafe.allocateMemory


Unsafe.allocateMemory 通过  `malloc` 申请虚拟内存
它是在堆外内存（C_HEAP）中分配一块内存空间，并返回堆外内存的基地址

```cpp
//unsafe.cpp
UNSAFE_ENTRY(jlong, Unsafe_AllocateMemory0(JNIEnv *env, jobject unsafe, jlong size)) {
  size_t sz = (size_t)size;

  sz = align_up(sz, HeapWordSize);
  void* x = os::malloc(sz, mtOther);

  return addr_to_java(x);
} UNSAFE_END

```



## create DirectByteBuffer


1. `reserveMemory` 该函数执行返回只有两种 正常返回有足够内存, 或者没有足够内存 抛出 OOM
   1. if has enough memory, return
   1. Else `tryHandlePendingReference` free memory util enough memory
   2. `System.gc()`
   3. Continue step 1, 2 util enough memory or MAX_SLEEPS
   4. if still no enough memory, OOM
3. `unsafe.allocateMemory`
4. init memory with `(byte) 0`
5. create a `Cleaner` with `Deallocator` to free direct memory when directByteBuffer instance unused



```java
//ByteBuffer.java 
public static ByteBuffer allocateDirect(int capacity) {
    return new DirectByteBuffer(capacity);
}

//DirectByteBuffer.java
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
reserveMemory

```java
    static void reserveMemory(long size, long cap) {

        if (!MEMORY_LIMIT_SET && VM.initLevel() >= 1) {
            MAX_MEMORY = VM.maxDirectMemory();
            MEMORY_LIMIT_SET = true;
        }

        // optimist!
        if (tryReserveMemory(size, cap)) {
            return;
        }

        final JavaLangRefAccess jlra = SharedSecrets.getJavaLangRefAccess();
        boolean interrupted = false;
        try {

            // Retry allocation until success or there are no more
            // references (including Cleaners that might free direct
            // buffer memory) to process and allocation still fails.
            boolean refprocActive;
            do {
                try {
                    refprocActive = jlra.waitForReferenceProcessing();
                } catch (InterruptedException e) {
                    // Defer interrupts and keep trying.
                    interrupted = true;
                    refprocActive = true;
                }
                if (tryReserveMemory(size, cap)) {
                    return;
                }
            } while (refprocActive);

            // trigger VM's Reference processing
            System.gc();

            // A retry loop with exponential back-off delays.
            // Sometimes it would suffice to give up once reference
            // processing is complete.  But if there are many threads
            // competing for memory, this gives more opportunities for
            // any given thread to make progress.  In particular, this
            // seems to be enough for a stress test like
            // DirectBufferAllocTest to (usually) succeed, while
            // without it that test likely fails.  Since failure here
            // ends in OOME, there's no need to hurry.
            long sleepTime = 1;
            int sleeps = 0;
            while (true) {
                if (tryReserveMemory(size, cap)) {
                    return;
                }
                if (sleeps >= MAX_SLEEPS) {
                    break;
                }
                try {
                    if (!jlra.waitForReferenceProcessing()) {
                        Thread.sleep(sleepTime);
                        sleepTime <<= 1;
                        sleeps++;
                    }
                } catch (InterruptedException e) {
                    interrupted = true;
                }
            }

            // no luck
            throw new OutOfMemoryError
                ("Cannot reserve "
                 + size + " bytes of direct buffer memory (allocated: "
                 + RESERVED_MEMORY.get() + ", limit: " + MAX_MEMORY +")");

        } finally {
            if (interrupted) {
                // don't swallow interrupts
                Thread.currentThread().interrupt();
            }
        }
    }
```
tryReserveMemory 

```java
    private static boolean tryReserveMemory(long size, long cap) {

        // -XX:MaxDirectMemorySize limits the total capacity rather than the
        // actual memory usage, which will differ when buffers are page
        // aligned.
        long totalCap;
        while (cap <= MAX_MEMORY - (totalCap = TOTAL_CAPACITY.get())) {
            if (TOTAL_CAPACITY.compareAndSet(totalCap, totalCap + cap)) {
                RESERVED_MEMORY.addAndGet(size);
                COUNT.incrementAndGet();
                return true;
            }
        }

        return false;
    }
```



```java
 static void unreserveMemory(long size, long cap) {
     long cnt = COUNT.decrementAndGet();
     long reservedMem = RESERVED_MEMORY.addAndGet(-size);
     long totalCap = TOTAL_CAPACITY.addAndGet(-cap);
     assert cnt >= 0 && reservedMem >= 0 && totalCap >= 0;
 }
```


## Cleaner

Direct buffers are indirectly freed by the Garbage Collector.

When [ReferenceHandler](/docs/CS/Java/JDK/Basic/Ref.md?id=referencehandler) get the `PhantomReference`(`Cleaner`) of `DirectByteBuffer` instance, invoke` Cleaner.clean()` -> `unsafe.freeMemory()`




clean() 方法主要做两件事情：

- 将 Cleaner 对象从 Cleaner 链表中移除；
- 调用 unsafe.freeMemory() 释放掉指定堆外内存地址的内存空间，然后重新统计系统中的 DirectByteBuffer 的大小情况

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


`Unsafe.allocateMemory/freeMemory` invoke `os::malloc/free ` finally use `glib::malloc/free`.


```c
UNSAFE_ENTRY(void, Unsafe_FreeMemory0(JNIEnv *env, jobject unsafe, jlong addr)) {
  void* p = addr_from_java(addr);

  os::free(p);
} UNSAFE_END
```

[Cleaner extends PhantomReference](/docs/CS/Java/JDK/Basic/Ref.md?id=phantom-reference)



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

enable NMT

```
-XX:NativeMemoryTracking={summary|detail}
```

-XX:+UnlockDiagnosticVMOptions -XX:+PrintNMTStatistics



## Links
- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)

