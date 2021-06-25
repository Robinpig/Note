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

1. `unsafe.allocateMemory()`
2. `unsafe.setMemory()`
3. create a `Cleaner` to recycle direct memory when directByteBuffer instance unused

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



### Cleaner

When [ReferenceHandler](/docs/CS/Java/JDK/Basic/Ref.md?id=referencehandler) get the `PhantomReference`(`Cleaner`) of `DirectByteBuffer` instance, invoke` Cleaner.clean()` -> `unsafe.freeMemory()`

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



