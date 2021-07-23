## Introduction



###  ByteBuf Hierarchy

![ByteBuf](./images/ByteBuf.png)



ByteBuf
1. readIndex and  writeIndex
2. auto expand
3. reference count
4. Pool area
5. Zero copy



## AbstractByteBuf

```java
int readerIndex;
int writerIndex;
private int markedReaderIndex;
private int markedWriterIndex;
private int maxCapacity;
```



### capacity( )

auto expand

```java
@Override
public ByteBuf writeBytes(byte[] src, int srcIndex, int length) {
    ensureWritable(length);
    setBytes(writerIndex, src, srcIndex, length);
    writerIndex += length;
    return this;
}

final void ensureWritable0(int minWritableBytes) {
    ensureAccessible();
    if (minWritableBytes <= writableBytes()) {
        return;
    }
    final int writerIndex = writerIndex();
    if (checkBounds) {
        if (minWritableBytes > maxCapacity - writerIndex) {
            throw new IndexOutOfBoundsException(String.format(
                    "writerIndex(%d) + minWritableBytes(%d) exceeds maxCapacity(%d): %s",
                    writerIndex, minWritableBytes, maxCapacity, this));
        }
    }

    // Normalize the current capacity to the power of 2.
    int minNewCapacity = writerIndex + minWritableBytes;
    int newCapacity = alloc().calculateNewCapacity(minNewCapacity, maxCapacity);

    int fastCapacity = writerIndex + maxFastWritableBytes();
    // Grow by a smaller amount if it will avoid reallocation
    if (newCapacity > fastCapacity && minNewCapacity <= fastCapacity) {
        newCapacity = fastCapacity;
    }

    // Adjust to the new capacity.
    capacity(newCapacity);
}

/**
 * Adjusts the capacity of this buffer.  If the {@code newCapacity} is less than the current
 * capacity, the content of this buffer is truncated.  If the {@code newCapacity} is greater
 * than the current capacity, the buffer is appended with unspecified data whose length is
 * {@code (newCapacity - currentCapacity)}.
 *
 * @throws IllegalArgumentException if the {@code newCapacity} is greater than {@link #maxCapacity()}
 */
@Override
public ByteBuf capacity(int newCapacity) {
    checkNewCapacity(newCapacity);

    int oldCapacity = array.length;
    byte[] oldArray = array;
    if (newCapacity > oldCapacity) {
        byte[] newArray = allocateArray(newCapacity);
        System.arraycopy(oldArray, 0, newArray, 0, oldArray.length);
        setArray(newArray);
        freeArray(oldArray);
    } else if (newCapacity < oldCapacity) {
        byte[] newArray = allocateArray(newCapacity);
        int readerIndex = readerIndex();
        if (readerIndex < newCapacity) {
            int writerIndex = writerIndex();
            if (writerIndex > newCapacity) {
                writerIndex(writerIndex = newCapacity);
            }
            System.arraycopy(oldArray, readerIndex, newArray, readerIndex, writerIndex - readerIndex);
        } else {
            setIndex(newCapacity, newCapacity);
        }
        setArray(newArray);
        freeArray(oldArray);
    }
    return this;
}
```





## AbstractReferenceCountedByteBuf

refCnt use AtomicIntegerFieldUpdater rather than AtomicInteger to reduce memory

```java
/**
 * Abstract base class for {@link ByteBuf} implementations that count references.
 */
public abstract class AbstractReferenceCountedByteBuf extends AbstractByteBuf {
    private static final long REFCNT_FIELD_OFFSET =
            ReferenceCountUpdater.getUnsafeOffset(AbstractReferenceCountedByteBuf.class, "refCnt");
    private static final AtomicIntegerFieldUpdater<AbstractReferenceCountedByteBuf> AIF_UPDATER =
            AtomicIntegerFieldUpdater.newUpdater(AbstractReferenceCountedByteBuf.class, "refCnt");

    private static final ReferenceCountUpdater<AbstractReferenceCountedByteBuf> updater =
            new ReferenceCountUpdater<AbstractReferenceCountedByteBuf>() {
        @Override
        protected AtomicIntegerFieldUpdater<AbstractReferenceCountedByteBuf> updater() {
            return AIF_UPDATER;
        }
        @Override
        protected long unsafeOffset() {
            return REFCNT_FIELD_OFFSET;
        }
    };

// Value might not equal "real" reference count, all access should be via the updater
@SuppressWarnings("unused")
private volatile int refCnt = updater.initialValue();
```



### ReferenceCountUpdater

### retain0

```java
// rawIncrement == increment << 1
private T retain0(T instance, final int increment, final int rawIncrement) {
    int oldRef = updater().getAndAdd(instance, rawIncrement);
    if (oldRef != 2 && oldRef != 4 && (oldRef & 1) != 0) {
        throw new IllegalReferenceCountException(0, increment);
    }
    // don't pass 0!
    if ((oldRef <= 0 && oldRef + rawIncrement >= 0)
            || (oldRef >= 0 && oldRef + rawIncrement < oldRef)) {
        // overflow case
        updater().getAndAdd(instance, -rawIncrement);
        throw new IllegalReferenceCountException(realRefCnt(oldRef), increment);
    }
    return instance;
}
```



### release( )

```java
public final boolean release(T instance) {
    int rawCnt = nonVolatileRawCnt(instance);
    return rawCnt == 2 ? tryFinalRelease0(instance, 2) || retryRelease0(instance, 1)
            : nonFinalRelease0(instance, 1, rawCnt, toLiveRealRefCnt(rawCnt, 1));
}

public final boolean release(T instance, int decrement) {
    int rawCnt = nonVolatileRawCnt(instance);
    int realCnt = toLiveRealRefCnt(rawCnt, checkPositive(decrement, "decrement"));
    return decrement == realCnt ? tryFinalRelease0(instance, rawCnt) || retryRelease0(instance, decrement)
            : nonFinalRelease0(instance, decrement, rawCnt, realCnt);
}

private boolean tryFinalRelease0(T instance, int expectRawCnt) {
    return updater().compareAndSet(instance, expectRawCnt, 1); // any odd number will work
}

private boolean nonFinalRelease0(T instance, int decrement, int rawCnt, int realCnt) {
    if (decrement < realCnt
            // all changes to the raw count are 2x the "real" change - overflow is OK
            && updater().compareAndSet(instance, rawCnt, rawCnt - (decrement << 1))) {
        return false;
    }
    return retryRelease0(instance, decrement);
}

private boolean retryRelease0(T instance, int decrement) {
    for (;;) {
        int rawCnt = updater().get(instance), realCnt = toLiveRealRefCnt(rawCnt, decrement);
        if (decrement == realCnt) {
            if (tryFinalRelease0(instance, rawCnt)) {
                return true;
            }
        } else if (decrement < realCnt) {
            // all changes to the raw count are 2x the "real" change
            if (updater().compareAndSet(instance, rawCnt, rawCnt - (decrement << 1))) {
                return false;
            }
        } else {
            throw new IllegalReferenceCountException(realCnt, -decrement);
        }
        Thread.yield(); // this benefits throughput under high contention
    }
}
```



## CompositeByteBuf

```java
/**
 * Cumulate {@link ByteBuf}s by add them to a {@link CompositeByteBuf} and so do no memory copy whenever possible.
 * Be aware that {@link CompositeByteBuf} use a more complex indexing implementation so depending on your use-case
 * and the decoder implementation this may be slower then just use the {@link #MERGE_CUMULATOR}.
 */
public static final Cumulator COMPOSITE_CUMULATOR = new Cumulator() {
    @Override
    public ByteBuf cumulate(ByteBufAllocator alloc, ByteBuf cumulation, ByteBuf in) {
        ByteBuf buffer;
        try {
            if (cumulation.refCnt() > 1) {
                // Expand cumulation (by replace it) when the refCnt is greater then 1 which may happen when the
                // user use slice().retain() or duplicate().retain().
                //
                // See:
                // - https://github.com/netty/netty/issues/2327
                // - https://github.com/netty/netty/issues/1764
                buffer = expandCumulation(alloc, cumulation, in.readableBytes());
                buffer.writeBytes(in);
            } else {
                CompositeByteBuf composite;
                if (cumulation instanceof CompositeByteBuf) {
                    composite = (CompositeByteBuf) cumulation;
                } else {
                    composite = alloc.compositeBuffer(Integer.MAX_VALUE);
                    composite.addComponent(true, cumulation);
                }
                composite.addComponent(true, in);
                in = null;
                buffer = composite;
            }
            return buffer;
        } finally {
            if (in != null) {
                // We must release if the ownership was not transferred as otherwise it may produce a leak if
                // writeBytes(...) throw for whatever release (for example because of OutOfMemoryError).
                in.release();
            }
        }
    }
};
```



### discardReadComponents( )

```java
/**
 * Discard all {@link ByteBuf}s which are read.
 */
public CompositeByteBuf discardReadComponents() {
    ensureAccessible();
    final int readerIndex = readerIndex();
    if (readerIndex == 0) {
        return this;
    }

    // Discard everything if (readerIndex = writerIndex = capacity).
    int writerIndex = writerIndex();
    if (readerIndex == writerIndex && writerIndex == capacity()) {
        for (int i = 0, size = componentCount; i < size; i++) {
            components[i].free();
        }
        lastAccessed = null;
        clearComps();
        setIndex(0, 0);
        adjustMarkers(readerIndex);
        return this;
    }

    // Remove read components.
    int firstComponentId = 0;
    Component c = null;
    for (int size = componentCount; firstComponentId < size; firstComponentId++) {
        c = components[firstComponentId];
        if (c.endOffset > readerIndex) {
            break;
        }
        c.free();
    }
    if (firstComponentId == 0) {
        return this; // Nothing to discard
    }
    Component la = lastAccessed;
    if (la != null && la.endOffset <= readerIndex) {
        lastAccessed = null;
    }
    removeCompRange(0, firstComponentId);

    // Update indexes and markers.
    int offset = c.offset;
    updateComponentOffsets(0);
    setIndex(readerIndex - offset, writerIndex - offset);
    adjustMarkers(offset);
    return this;
}
```



## PooledByteBuf



## PoolArea



### allocate( )

```java
private void allocate(PoolThreadCache cache, PooledByteBuf<T> buf, final int reqCapacity) {
    final int normCapacity = normalizeCapacity(reqCapacity);
    if (isTinyOrSmall(normCapacity)) { // capacity < pageSize
        int tableIdx;
        PoolSubpage<T>[] table;
        boolean tiny = isTiny(normCapacity);
        if (tiny) { // < 512
            if (cache.allocateTiny(this, buf, reqCapacity, normCapacity)) {
                // was able to allocate out of the cache so move on
                return;
            }
            tableIdx = tinyIdx(normCapacity);
            table = tinySubpagePools;
        } else {
            if (cache.allocateSmall(this, buf, reqCapacity, normCapacity)) {
                // was able to allocate out of the cache so move on
                return;
            }
            tableIdx = smallIdx(normCapacity);
            table = smallSubpagePools;
        }

        final PoolSubpage<T> head = table[tableIdx];

        /**
         * Synchronize on the head. This is needed as {@link PoolChunk#allocateSubpage(int)} and
         * {@link PoolChunk#free(long)} may modify the doubly linked list as well.
         */
        synchronized (head) {
            final PoolSubpage<T> s = head.next;
            if (s != head) {
                assert s.doNotDestroy && s.elemSize == normCapacity;
                long handle = s.allocate();
                assert handle >= 0;
                s.chunk.initBufWithSubpage(buf, null, handle, reqCapacity);
                incTinySmallAllocation(tiny);
                return;
            }
        }
        synchronized (this) {
            allocateNormal(buf, reqCapacity, normCapacity);
        }

        incTinySmallAllocation(tiny);
        return;
    }
    if (normCapacity <= chunkSize) {
        if (cache.allocateNormal(this, buf, reqCapacity, normCapacity)) {
            // was able to allocate out of the cache so move on
            return;
        }
        synchronized (this) {
            allocateNormal(buf, reqCapacity, normCapacity);
            ++allocationsNormal;
        }
    } else {
        // Huge allocations are never served via the cache so just call allocateHuge
        allocateHuge(buf, reqCapacity);
    }
}
```



## PoolChunk



## PooledDirectByteBuf

### newInstance( )

```java
static PooledDirectByteBuf newInstance(int maxCapacity) {
    PooledDirectByteBuf buf = RECYCLER.get();
    buf.reuse(maxCapacity);
    return buf;
}
```



## CompositeByteBuf


### Component( )

```java
Component(ByteBuf buf, int srcOffset, int offset, int len, ByteBuf slice) {
    this.buf = buf;
    this.offset = offset;
    this.endOffset = offset + len;
    this.adjustment = srcOffset - offset;
    this.slice = slice;
}

/**
 * Precondition is that {@code buffer != null}.
 */
private int addComponent0(boolean increaseWriterIndex, int cIndex, ByteBuf buffer) {
    assert buffer != null;
    boolean wasAdded = false;
    try {
        checkComponentIndex(cIndex);

        // No need to consolidate - just add a component to the list.
        Component c = newComponent(buffer, 0);
        int readableBytes = c.length();

        addComp(cIndex, c);
        wasAdded = true;
        if (readableBytes > 0 && cIndex < componentCount - 1) {
            updateComponentOffsets(cIndex);
        } else if (cIndex > 0) {
            c.reposition(components[cIndex - 1].endOffset);
        }
        if (increaseWriterIndex) {
            writerIndex += readableBytes;
        }
        return cIndex;
    } finally {
        if (!wasAdded) {
            buffer.release();
        }
    }
}
```



## ResourceLeakDetector




```java
DefaultResourceLeak(
        Object referent,
        ReferenceQueue<Object> refQueue,
        Set<DefaultResourceLeak<?>> allLeaks) {
    super(referent, refQueue);

    assert referent != null;

    // Store the hash of the tracked object to later assert it in the close(...) method.
    // It's important that we not store a reference to the referent as this would disallow it from
    // be collected via the WeakReference.
    trackedHash = System.identityHashCode(referent);
    allLeaks.add(this);
    // Create a new Record so we always have the creation stacktrace included.
    headUpdater.set(this, new Record(Record.BOTTOM));
    this.allLeaks = allLeaks;
}
```




AbstractByteBufAllocator


```java
protected static ByteBuf toLeakAwareBuffer(ByteBuf buf) {
    ResourceLeakTracker<ByteBuf> leak;
    switch (ResourceLeakDetector.getLevel()) {
        case SIMPLE:
            leak = AbstractByteBuf.leakDetector.track(buf);
            if (leak != null) {
                buf = new SimpleLeakAwareByteBuf(buf, leak);
            }
            break;
        case ADVANCED:
        case PARANOID:
            leak = AbstractByteBuf.leakDetector.track(buf);
            if (leak != null) {
                buf = new AdvancedLeakAwareByteBuf(buf, leak);
            }
            break;
        default:
            break;
    }
    return buf;
}
```



track0( )

```java
@SuppressWarnings("unchecked")
private DefaultResourceLeak track0(T obj) {
    Level level = ResourceLeakDetector.level;
    if (level == Level.DISABLED) {
        return null;
    }

    if (level.ordinal() < Level.PARANOID.ordinal()) {
        if ((PlatformDependent.threadLocalRandom().nextInt(samplingInterval)) == 0) {
            reportLeak();
            return new DefaultResourceLeak(obj, refQueue, allLeaks);
        }
        return null;
    }
    reportLeak();
    return new DefaultResourceLeak(obj, refQueue, allLeaks);
}
```

reportLeak

```java
private void reportLeak() {
    if (!logger.isErrorEnabled()) {
        clearRefQueue();
        return;
    }

    // Detect and report previous leaks.
    for (;;) {
        @SuppressWarnings("unchecked")
        DefaultResourceLeak ref = (DefaultResourceLeak) refQueue.poll();
        if (ref == null) {
            break;
        }

        if (!ref.dispose()) {
            continue;
        }

        String records = ref.toString();
        if (reportedLeaks.putIfAbsent(records, Boolean.TRUE) == null) {
            if (records.isEmpty()) {
                reportUntracedLeak(resourceType);
            } else {
                reportTracedLeak(resourceType, records);
            }
        }
    }
}
```

dispose
```java
boolean dispose() {
    clear();
    return allLeaks.remove(this);
}
```

reportTracedLeak
```java
/**
 * This method is called when a traced leak is detected. It can be overridden for tracking how many times leaks
 * have been detected.
 */
protected void reportTracedLeak(String resourceType, String records) {
    logger.error(
            "LEAK: {}.release() was not called before it's garbage-collected. " +
            "See https://netty.io/wiki/reference-counted-objects.html for more information.{}",
            resourceType, records);
}
```

record0
```java
/**
 * This method works by exponentially backing off as more records are present in the stack. Each record has a
 * 1 / 2^n chance of dropping the top most record and replacing it with itself. This has a number of convenient
 * properties:
 *
 * <ol>
 * <li>  The current record is always recorded. This is due to the compare and swap dropping the top most
 *       record, rather than the to-be-pushed record.
 * <li>  The very last access will always be recorded. This comes as a property of 1.
 * <li>  It is possible to retain more records than the target, based upon the probability distribution.
 * <li>  It is easy to keep a precise record of the number of elements in the stack, since each element has to
 *     know how tall the stack is.
 * </ol>
 *
 * In this particular implementation, there are also some advantages. A thread local random is used to decide
 * if something should be recorded. This means that if there is a deterministic access pattern, it is now
 * possible to see what other accesses occur, rather than always dropping them. Second, after
 * {@link #TARGET_RECORDS} accesses, backoff occurs. This matches typical access patterns,
 * where there are either a high number of accesses (i.e. a cached buffer), or low (an ephemeral buffer), but
 * not many in between.
 *
 * The use of atomics avoids serializing a high number of accesses, when most of the records will be thrown
 * away. High contention only happens when there are very few existing records, which is only likely when the
 * object isn't shared! If this is a problem, the loop can be aborted and the record dropped, because another
 * thread won the race.
 */
private void record0(Object hint) {
    // Check TARGET_RECORDS > 0 here to avoid similar check before remove from and add to lastRecords
    if (TARGET_RECORDS > 0) {
        Record oldHead;
        Record prevHead;
        Record newHead;
        boolean dropped;
        do {
            if ((prevHead = oldHead = headUpdater.get(this)) == null) {
                // already closed.
                return;
            }
            final int numElements = oldHead.pos + 1;
            if (numElements >= TARGET_RECORDS) {
                final int backOffFactor = Math.min(numElements - TARGET_RECORDS, 30);
                if (dropped = PlatformDependent.threadLocalRandom().nextInt(1 << backOffFactor) != 0) {
                    prevHead = oldHead.next;
                }
            } else {
                dropped = false;
            }
            newHead = hint != null ? new Record(prevHead, hint) : new Record(prevHead);
        } while (!headUpdater.compareAndSet(this, oldHead, newHead));
        if (dropped) {
            droppedRecordsUpdater.incrementAndGet(this);
        }
    }
}
```



## Allocator

Implementations are responsible to allocate buffers. Implementations of this interface are expected to be thread-safe.

```java
public interface ByteBufAllocator {

    ByteBufAllocator DEFAULT = ByteBufUtil.DEFAULT_ALLOCATOR;
  ...
}   
```



```java
// ByteBufUtil
static final ByteBufAllocator DEFAULT_ALLOCATOR;

static {
    String allocType = SystemPropertyUtil.get(
            "io.netty.allocator.type", PlatformDependent.isAndroid() ? "unpooled" : "pooled");
    allocType = allocType.toLowerCase(Locale.US).trim();

    ByteBufAllocator alloc;
    if ("unpooled".equals(allocType)) {
        alloc = UnpooledByteBufAllocator.DEFAULT;
    } else if ("pooled".equals(allocType)) {
        alloc = PooledByteBufAllocator.DEFAULT; // default
    } else {
        alloc = PooledByteBufAllocator.DEFAULT;
    }

    DEFAULT_ALLOCATOR = alloc;

    THREAD_LOCAL_BUFFER_SIZE = SystemPropertyUtil.getInt("io.netty.threadLocalDirectBufferSize", 0);

    MAX_CHAR_BUFFER_SIZE = SystemPropertyUtil.getInt("io.netty.maxThreadLocalCharBufferSize", 16 * 1024);
}
```



```java
public static final PooledByteBufAllocator DEFAULT =
        new PooledByteBufAllocator(PlatformDependent.directBufferPreferred());
```



```java
/**
 * Returns {@code true} if the platform has reliable low-level direct buffer access API and a user has not specified
 * {@code -Dio.netty.noPreferDirect} option.
 */
public static boolean directBufferPreferred() {
    return DIRECT_BUFFER_PREFERRED;
}
```



pageSize 8192

```java
public PooledByteBufAllocator(boolean preferDirect, int nHeapArena, int nDirectArena, int pageSize, int maxOrder,
                              int smallCacheSize, int normalCacheSize,
                              boolean useCacheForAllThreads, int directMemoryCacheAlignment) {
    super(preferDirect);
    threadCache = new PoolThreadLocalCache(useCacheForAllThreads);
    this.smallCacheSize = smallCacheSize;
    this.normalCacheSize = normalCacheSize;
    chunkSize = validateAndCalculateChunkSize(pageSize, maxOrder);

    checkPositiveOrZero(nHeapArena, "nHeapArena");
    checkPositiveOrZero(nDirectArena, "nDirectArena");

    checkPositiveOrZero(directMemoryCacheAlignment, "directMemoryCacheAlignment");
    if (directMemoryCacheAlignment > 0 && !isDirectMemoryCacheAlignmentSupported()) {
        throw new IllegalArgumentException("directMemoryCacheAlignment is not supported");
    }

    if ((directMemoryCacheAlignment & -directMemoryCacheAlignment) != directMemoryCacheAlignment) {
        throw new IllegalArgumentException("directMemoryCacheAlignment: "
                + directMemoryCacheAlignment + " (expected: power of two)");
    }

    int pageShifts = validateAndCalculatePageShifts(pageSize);

    if (nHeapArena > 0) {
        heapArenas = newArenaArray(nHeapArena);
        List<PoolArenaMetric> metrics = new ArrayList<PoolArenaMetric>(heapArenas.length);
        for (int i = 0; i < heapArenas.length; i ++) {
            PoolArena.HeapArena arena = new PoolArena.HeapArena(this,
                    pageSize, pageShifts, chunkSize,
                    directMemoryCacheAlignment);
            heapArenas[i] = arena;
            metrics.add(arena);
        }
        heapArenaMetrics = Collections.unmodifiableList(metrics);
    } else {
        heapArenas = null;
        heapArenaMetrics = Collections.emptyList();
    }

    if (nDirectArena > 0) {
        directArenas = newArenaArray(nDirectArena);
        List<PoolArenaMetric> metrics = new ArrayList<PoolArenaMetric>(directArenas.length);
        for (int i = 0; i < directArenas.length; i ++) {
            PoolArena.DirectArena arena = new PoolArena.DirectArena(
                    this, pageSize, pageShifts, chunkSize, directMemoryCacheAlignment);
            directArenas[i] = arena;
            metrics.add(arena);
        }
        directArenaMetrics = Collections.unmodifiableList(metrics);
    } else {
        directArenas = null;
        directArenaMetrics = Collections.emptyList();
    }
    metric = new PooledByteBufAllocatorMetric(this);
}
```





```java
/**
 * Metrics for a chunk.
 */
public interface PoolChunkMetric {

    /**
     * Return the percentage of the current usage of the chunk.
     */
    int usage();

    /**
     * Return the size of the chunk in bytes, this is the maximum of bytes that can be served out of the chunk.
     */
    int chunkSize();

    /**
     * Return the number of free bytes in the chunk.
     */
    int freeBytes();
}
```





```java
abstract class PoolArena<T> extends SizeClasses implements PoolArenaMetric {
```



### allocate



```java
// PoolArena
PooledByteBuf<T> allocate(PoolThreadCache cache, int reqCapacity, int maxCapacity) {
    PooledByteBuf<T> buf = newByteBuf(maxCapacity);
    allocate(cache, buf, reqCapacity);
    return buf;
}

private void allocate(PoolThreadCache cache, PooledByteBuf<T> buf, final int reqCapacity) {
    final int sizeIdx = size2SizeIdx(reqCapacity);

    if (sizeIdx <= smallMaxSizeIdx) {
        tcacheAllocateSmall(cache, buf, reqCapacity, sizeIdx);
    } else if (sizeIdx < nSizes) {
        tcacheAllocateNormal(cache, buf, reqCapacity, sizeIdx);
    } else {
        int normCapacity = directMemoryCacheAlignment > 0
                ? normalizeSize(reqCapacity) : reqCapacity;
        // Huge allocations are never served via the cache so just call allocateHuge
        allocateHuge(buf, normCapacity);
    }
}
```

#### tcacheAllocateSmall

1. cahe allocateSmall
2. synchronized head 
3. synchronized PoolArena, allocateNormal

```java
// PoolArena
private void tcacheAllocateSmall(PoolThreadCache cache, PooledByteBuf<T> buf, final int reqCapacity,
                                 final int sizeIdx) {

    if (cache.allocateSmall(this, buf, reqCapacity, sizeIdx)) {
        // was able to allocate out of the cache so move on
        return;
    }

    /**
     * Synchronize on the head. This is needed as {@link PoolChunk#allocateSubpage(int)} and
     * {@link PoolChunk#free(long)} may modify the doubly linked list as well.
     */
    final PoolSubpage<T> head = smallSubpagePools[sizeIdx];
    final boolean needsNormalAllocation;
    synchronized (head) {
        final PoolSubpage<T> s = head.next;
        needsNormalAllocation = s == head;
        if (!needsNormalAllocation) {
            assert s.doNotDestroy && s.elemSize == sizeIdx2size(sizeIdx);
            long handle = s.allocate();
            assert handle >= 0;
            s.chunk.initBufWithSubpage(buf, null, handle, reqCapacity, cache);
        }
    }

    if (needsNormalAllocation) {
        synchronized (this) {
            allocateNormal(buf, reqCapacity, sizeIdx, cache);
        }
    }

    incSmallAllocation();
}
```





```java
// PoolThreadcache
private boolean allocate(MemoryRegionCache<?> cache, PooledByteBuf buf, int reqCapacity) {
    if (cache == null) {
        // no cache found so just return false here
        return false;
    }
    boolean allocated = cache.allocate(buf, reqCapacity, this);
  	//  freeSweepAllocationThreshold default 8192
    if (++ allocations >= freeSweepAllocationThreshold) {
        allocations = 0;
        trim();
    }
    return allocated;
}


// Allocate something out of the cache if possible and remove the entry from the cache.
public final boolean allocate(PooledByteBuf<T> buf, int reqCapacity, PoolThreadCache threadCache) {
  Entry<T> entry = queue.poll();
  if (entry == null) {
    return false;
  }
  initBuf(entry.chunk, entry.nioBuffer, entry.handle, buf, reqCapacity, threadCache);
  entry.recycle();

  // allocations is not thread-safe which is fine as this is only called from the same thread all time.
  ++ allocations;
  return true;
}
```





```java

// Free up cached {@link PoolChunk}s if not allocated frequently enough.
public final void trim() {
  int free = size - allocations;
  allocations = 0;

  // We not even allocated all the number that are
  if (free > 0) {
    free(free, false);
  }
}

private int free(int max, boolean finalizer) {
    int numFreed = 0;
    for (; numFreed < max; numFreed++) {
        Entry<T> entry = queue.poll();
        if (entry != null) {
            freeEntry(entry, finalizer);
        } else {
            // all cleared
            return numFreed;
        }
    }
    return numFreed;
}

private  void freeEntry(Entry entry, boolean finalizer) {
  PoolChunk chunk = entry.chunk;
  long handle = entry.handle;
  ByteBuffer nioBuffer = entry.nioBuffer;

  if (!finalizer) {
    // recycle now so PoolChunk can be GC'ed. This will only be done if this is not freed because of
    // a finalizer.
    entry.recycle();
  }

  chunk.arena.freeChunk(chunk, handle, entry.normCapacity, sizeClass, nioBuffer, finalizer);
}
```



##### PoolSubpage::allocate

```java
/** PoolSubpage
 * Returns the bitmap index of the subpage allocation.
 */
long allocate() {
    if (numAvail == 0 || !doNotDestroy) {
        return -1;
    }

    final int bitmapIdx = getNextAvail();
    int q = bitmapIdx >>> 6;
    int r = bitmapIdx & 63;
    assert (bitmap[q] >>> r & 1) == 0;
    bitmap[q] |= 1L << r;

    if (-- numAvail == 0) {
        removeFromPool();
    }

    return toHandle(bitmapIdx);
}
```





```java
// PoolArena
void freeChunk(PoolChunk<T> chunk, long handle, int normCapacity, SizeClass sizeClass, ByteBuffer nioBuffer,
               boolean finalizer) {
    final boolean destroyChunk;
    synchronized (this) {
        // We only call this if freeChunk is not called because of the PoolThreadCache finalizer as otherwise this
        // may fail due lazy class-loading in for example tomcat.
        if (!finalizer) {
            switch (sizeClass) {
                case Normal:
                    ++deallocationsNormal;
                    break;
                case Small:
                    ++deallocationsSmall;
                    break;
                default:
                    throw new Error();
            }
        }
        destroyChunk = !chunk.parent.free(chunk, handle, normCapacity, nioBuffer);
    }
    if (destroyChunk) {
        // destroyChunk not need to be called while holding the synchronized lock.
        destroyChunk(chunk);
    }
}
```



#### allocateNormal

```java
// PoolArena
// Method must be called inside synchronized(this) { ... } block
private void allocateNormal(PooledByteBuf<T> buf, int reqCapacity, int sizeIdx, PoolThreadCache threadCache) {
    if (q050.allocate(buf, reqCapacity, sizeIdx, threadCache) ||
        q025.allocate(buf, reqCapacity, sizeIdx, threadCache) ||
        q000.allocate(buf, reqCapacity, sizeIdx, threadCache) ||
        qInit.allocate(buf, reqCapacity, sizeIdx, threadCache) ||
        q075.allocate(buf, reqCapacity, sizeIdx, threadCache)) {
        return;
    }

    // Add a new chunk.
    PoolChunk<T> c = newChunk(pageSize, nPSizes, pageShifts, chunkSize);
    boolean success = c.allocate(buf, reqCapacity, sizeIdx, threadCache);
    assert success;
    qInit.add(c);
}
```





```java
// PoolChunk
boolean allocate(PooledByteBuf<T> buf, int reqCapacity, int sizeIdx, PoolThreadCache cache) {
    final long handle;
    if (sizeIdx <= arena.smallMaxSizeIdx) {
        // small
        handle = allocateSubpage(sizeIdx);
        if (handle < 0) {
            return false;
        }
        assert isSubpage(handle);
    } else {
        // normal
        // runSize must be multiple of pageSize
        int runSize = arena.sizeIdx2size(sizeIdx);
        handle = allocateRun(runSize);
        if (handle < 0) {
            return false;
        }
    }

    ByteBuffer nioBuffer = cachedNioBuffers != null? cachedNioBuffers.pollLast() : null;
    initBuf(buf, nioBuffer, handle, reqCapacity, cache);
    return true;
}
```

##### allocateSubpage

```java
/**
 * Create / initialize a new PoolSubpage of normCapacity. Any PoolSubpage created / initialized here is added to
 * subpage pool in the PoolArena that owns this PoolChunk
 *
 * @param sizeIdx sizeIdx of normalized size
 *
 * @return index in memoryMap
 */
private long allocateSubpage(int sizeIdx) {
    // Obtain the head of the PoolSubPage pool that is owned by the PoolArena and synchronize on it.
    // This is need as we may add it back and so alter the linked-list structure.
    PoolSubpage<T> head = arena.findSubpagePoolHead(sizeIdx);
    synchronized (head) {
        //allocate a new run
        int runSize = calculateRunSize(sizeIdx);
        //runSize must be multiples of pageSize
        long runHandle = allocateRun(runSize);
        if (runHandle < 0) {
            return -1;
        }

        int runOffset = runOffset(runHandle);
        int elemSize = arena.sizeIdx2size(sizeIdx);

        PoolSubpage<T> subpage = new PoolSubpage<T>(head, this, pageShifts, runOffset,
                           runSize(pageShifts, runHandle), elemSize);

        subpages[runOffset] = subpage;
        return subpage.allocate();
    }
}
```



##### allocateRun

```java
private long allocateRun(int runSize) {
    int pages = runSize >> pageShifts;
    int pageIdx = arena.pages2pageIdx(pages);

    synchronized (runsAvail) {
        //find first queue which has at least one big enough run
        int queueIdx = runFirstBestFit(pageIdx);
        if (queueIdx == -1) {
            return -1;
        }

        //get run with min offset in this queue
        PriorityQueue<Long> queue = runsAvail[queueIdx];
        long handle = queue.poll();

        assert !isUsed(handle);

        removeAvailRun(queue, handle);

        if (handle != -1) {
            handle = splitLargeRun(handle, pages);
        }

        freeBytes -= runSize(pageShifts, handle);
        return handle;
    }
}
```





