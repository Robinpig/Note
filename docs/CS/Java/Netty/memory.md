## Introduction




Some methods such as `ByteBuf.readBytes(int)` will cause a memory leak if the returned buffer is not released or added to the out List. 
Use derived buffers like `ByteBuf.readSlice(int)` to avoid leaking memory.


## Recycler


count

Chunk
Page
SubPage




```java
// PooledDirectByteBuf
final class PooledDirectByteBuf extends PooledByteBuf<ByteBuffer> {

    private static final Recycler<PooledDirectByteBuf> RECYCLER = new Recycler<PooledDirectByteBuf>() {
        @Override
        protected PooledDirectByteBuf newObject(Handle<PooledDirectByteBuf> handle) {
            return new PooledDirectByteBuf(handle, 0);
        }
    };
  

  private PooledDirectByteBuf(Recycler.Handle<PooledDirectByteBuf> recyclerHandle, int maxCapacity) {
    super(recyclerHandle, maxCapacity);
  }
 ... 
}
```



### get

```java
static PooledDirectByteBuf newInstance(int maxCapacity) {
    PooledDirectByteBuf buf = RECYCLER.get();
    buf.reuse(maxCapacity);
    return buf;
}
```


get from [FastThreadLocal](/docs/CS/Java/Netty/FastThreadLocal.md)
```java
// Recycler
public final T get() {
    if (maxCapacityPerThread == 0) {
        return newObject((Handle<T>) NOOP_HANDLE);
    }
    Stack<T> stack = threadLocal.get(); // FastThreadLocal#get()
    DefaultHandle<T> handle = stack.pop();
    if (handle == null) {
        handle = stack.newHandle();
        handle.value = newObject(handle);
    }
    return (T) handle.value;
}


```
Method must be called before reuse this PooledByteBufAllocator

```java
final void reuse(int maxCapacity) {
    maxCapacity(maxCapacity);
    resetRefCnt();
    setIndex0(0, 0);
    discardMarks();
}
```



```java
// Recycler
private final FastThreadLocal<Stack<T>> threadLocal = new FastThreadLocal<Stack<T>>() {
    @Override
    protected Stack<T> initialValue() {
        return new Stack<T>(Recycler.this, Thread.currentThread(), maxCapacityPerThread, maxSharedCapacityFactor,
                interval, maxDelayedQueuesPerThread, delayedQueueInterval);
    }

    @Override
    protected void onRemoval(Stack<T> value) {
        // Let us remove the WeakOrderQueue from the WeakHashMap directly if its safe to remove some overhead
        if (value.threadRef.get() == Thread.currentThread()) {
           if (DELAYED_RECYCLED.isSet()) {
               DELAYED_RECYCLED.get().remove(value);
           }
        }
    }
};
```


### recycle

```java
protected final void deallocate() {
    if (handle >= 0) {
        final long handle = this.handle;
        this.handle = -1;
        memory = null;
        chunk.arena.free(chunk, tmpNioBuf, handle, maxLength, cache);
        tmpNioBuf = null;
        chunk = null;
        recycle();
    }
}

public void recycle(Object object) {
    if (object != value) {
        throw new IllegalArgumentException("object does not belong to handle");
    }

    Stack<?> stack = this.stack;
    if (lastRecycledId != recycleId || stack == null) {
        throw new IllegalStateException("recycled already");
    }

    stack.push(this);
}
```


### Stack

```java
private static final class Stack<T> {

    // we keep a queue of per-thread queues, which is appended to once only, each time a new thread other
    // than the stack owner recycles: when we run out of items in our stack we iterate this collection
    // to scavenge those that can be reused. this permits us to incur minimal thread synchronisation whilst
    // still recycling all items.
    final Recycler<T> parent;

    // We store the Thread in a WeakReference as otherwise we may be the only ones that still hold a strong
    // Reference to the Thread itself after it died because DefaultHandle will hold a reference to the Stack.
    //
    // The biggest issue is if we do not use a WeakReference the Thread may not be able to be collected at all if
    // the user will store a reference to the DefaultHandle somewhere and never clear this reference (or not clear
    // it in a timely manner).
    final WeakReference<Thread> threadRef;
    final AtomicInteger availableSharedCapacity;
    private final int maxDelayedQueues;

    private final int maxCapacity;
    private final int interval;
    private final int delayedQueueInterval;
    DefaultHandle<?>[] elements;	// handles
    int size;
    private int handleRecycleCount;
    private WeakOrderQueue cursor, prev;
    private volatile WeakOrderQueue head;

    Stack(Recycler<T> parent, Thread thread, int maxCapacity, int maxSharedCapacityFactor,
          int interval, int maxDelayedQueues, int delayedQueueInterval) {
        this.parent = parent;
        threadRef = new WeakReference<Thread>(thread);
        this.maxCapacity = maxCapacity;
        availableSharedCapacity = new AtomicInteger(max(maxCapacity / maxSharedCapacityFactor, LINK_CAPACITY));
        elements = new DefaultHandle[min(INITIAL_CAPACITY, maxCapacity)];
        this.interval = interval;
        this.delayedQueueInterval = delayedQueueInterval;
        handleRecycleCount = interval; // Start at interval so the first one will be recycled.
        this.maxDelayedQueues = maxDelayedQueues;
    }

    // Marked as synchronized to ensure this is serialized.
    synchronized void setHead(WeakOrderQueue queue) {
        queue.setNext(head);
        head = queue;
    }

    int increaseCapacity(int expectedCapacity) {
        int newCapacity = elements.length;
        int maxCapacity = this.maxCapacity;
        do {
            newCapacity <<= 1;
        } while (newCapacity < expectedCapacity && newCapacity < maxCapacity);

        newCapacity = min(newCapacity, maxCapacity);
        if (newCapacity != elements.length) {
            elements = Arrays.copyOf(elements, newCapacity);
        }

        return newCapacity;
    }

    @SuppressWarnings({ "unchecked", "rawtypes" })
    DefaultHandle<T> pop() {
        int size = this.size;
        if (size == 0) {
            if (!scavenge()) {
                return null;
            }
            size = this.size;
            if (size <= 0) {
                // double check, avoid races
                return null;
            }
        }
        size --;
        DefaultHandle ret = elements[size];
        elements[size] = null;
        // As we already set the element[size] to null we also need to store the updated size before we do
        // any validation. Otherwise we may see a null value when later try to pop again without a new element
        // added before.
        this.size = size;

        if (ret.lastRecycledId != ret.recycleId) {
            throw new IllegalStateException("recycled multiple times");
        }
        ret.recycleId = 0;
        ret.lastRecycledId = 0;
        return ret;
    }

    private boolean scavenge() {
        // continue an existing scavenge, if any
        if (scavengeSome()) {
            return true;
        }

        // reset our scavenge cursor
        prev = null;
        cursor = head;
        return false;
    }

    private boolean scavengeSome() {
        WeakOrderQueue prev;
        WeakOrderQueue cursor = this.cursor;
        if (cursor == null) {
            prev = null;
            cursor = head;
            if (cursor == null) {
                return false;
            }
        } else {
            prev = this.prev;
        }

        boolean success = false;
        do {
            if (cursor.transfer(this)) {
                success = true;
                break;
            }
            WeakOrderQueue next = cursor.getNext();
            if (cursor.get() == null) {
                // If the thread associated with the queue is gone, unlink it, after
                // performing a volatile read to confirm there is no data left to collect.
                // We never unlink the first queue, as we don't want to synchronize on updating the head.
                if (cursor.hasFinalData()) {
                    for (;;) {
                        if (cursor.transfer(this)) {
                            success = true;
                        } else {
                            break;
                        }
                    }
                }

                if (prev != null) {
                    // Ensure we reclaim all space before dropping the WeakOrderQueue to be GC'ed.
                    cursor.reclaimAllSpaceAndUnlink();
                    prev.setNext(next);
                }
            } else {
                prev = cursor;
            }

            cursor = next;

        } while (cursor != null && !success);

        this.prev = prev;
        this.cursor = cursor;
        return success;
    }

    void push(DefaultHandle<?> item) {
        Thread currentThread = Thread.currentThread();
        if (threadRef.get() == currentThread) {
            // The current Thread is the thread that belongs to the Stack, we can try to push the object now.
            pushNow(item);
        } else {
            // The current Thread is not the one that belongs to the Stack
            // (or the Thread that belonged to the Stack was collected already), we need to signal that the push
            // happens later.
            pushLater(item, currentThread);
        }
    }

    private void pushNow(DefaultHandle<?> item) {
        if ((item.recycleId | item.lastRecycledId) != 0) {
            throw new IllegalStateException("recycled already");
        }
        item.recycleId = item.lastRecycledId = OWN_THREAD_ID;

        int size = this.size;
        if (size >= maxCapacity || dropHandle(item)) {
            // Hit the maximum capacity or should drop - drop the possibly youngest object.
            return;
        }
        if (size == elements.length) {
            elements = Arrays.copyOf(elements, min(size << 1, maxCapacity));
        }

        elements[size] = item;
        this.size = size + 1;
    }

   

    /**
     * Allocate a new {@link WeakOrderQueue} or return {@code null} if not possible.
     */
    private WeakOrderQueue newWeakOrderQueue(Thread thread) {
        return WeakOrderQueue.newQueue(this, thread);
    }

    boolean dropHandle(DefaultHandle<?> handle) {
        if (!handle.hasBeenRecycled) {
            if (handleRecycleCount < interval) {
                handleRecycleCount++;
                // Drop the object.
                return true;
            }
            handleRecycleCount = 0;
            handle.hasBeenRecycled = true;
        }
        return false;
    }

    DefaultHandle<T> newHandle() {
        return new DefaultHandle<T>(this);
    }
}
```



### push



```java
// Stack
void push(DefaultHandle<?> item) {
  Thread currentThread = Thread.currentThread();
  if (threadRef.get() == currentThread) {
    // The current Thread is the thread that belongs to the Stack, we can try to push the object now.
    pushNow(item);
  } else {
    // The current Thread is not the one that belongs to the Stack
    // (or the Thread that belonged to the Stack was collected already), we need to signal that the push
    // happens later.
    pushLater(item, currentThread);
  }
}

private void pushNow(DefaultHandle<?> item) {
  if ((item.recycleId | item.lastRecycledId) != 0) {
    throw new IllegalStateException("recycled already");
  }
  item.recycleId = item.lastRecycledId = OWN_THREAD_ID;

  int size = this.size;
  if (size >= maxCapacity || dropHandle(item)) {
    // Hit the maximum capacity or should drop - drop the possibly youngest object.
    return;
  }
  if (size == elements.length) {
    elements = Arrays.copyOf(elements, min(size << 1, maxCapacity));
  }

  elements[size] = item;
  this.size = size + 1;
}
 
private void pushLater(DefaultHandle<?> item, Thread thread) {
  if (maxDelayedQueues == 0) {
    // We don't support recycling across threads and should just drop the item on the floor.
    return;
  }

  // we don't want to have a ref to the queue as the value in our weak map
  // so we null it out; to ensure there are no races with restoring it later
  // we impose a memory ordering here (no-op on x86)
  Map<Stack<?>, WeakOrderQueue> delayedRecycled = DELAYED_RECYCLED.get();
  WeakOrderQueue queue = delayedRecycled.get(this);
  if (queue == null) {
    if (delayedRecycled.size() >= maxDelayedQueues) {
      // Add a dummy queue so we know we should drop the object
      delayedRecycled.put(this, WeakOrderQueue.DUMMY);
      return;
    }
    // Check if we already reached the maximum number of delayed queues and if we can allocate at all.
    if ((queue = newWeakOrderQueue(thread)) == null) {
      // drop object
      return;
    }
    delayedRecycled.put(this, queue);
  } else if (queue == WeakOrderQueue.DUMMY) {
    // drop object
    return;
  }

  queue.add(item);
}
```

```java
// WeakOrderQueue
void add(DefaultHandle<?> handle) {
    handle.lastRecycledId = id;

    // While we also enforce the recycling ratio when we transfer objects from the WeakOrderQueue to the Stack
    // we better should enforce it as well early. Missing to do so may let the WeakOrderQueue grow very fast
    // without control
    if (handleRecycleCount < interval) {
        handleRecycleCount++;
        // Drop the item to prevent recycling to aggressive.
        return;
    }
    handleRecycleCount = 0;

    Link tail = this.tail;
    int writeIndex;
    if ((writeIndex = tail.get()) == LINK_CAPACITY) {
        Link link = head.newLink();
        if (link == null) {
            // Drop it.
            return;
        }
        // We allocate a Link so reserve the space
        this.tail = tail = tail.next = link;

        writeIndex = tail.get();
    }
    tail.elements[writeIndex] = handle;
    handle.stack = null;
    // we lazy set to ensure that setting stack to null appears before we unnull it in the owning thread;
    // this also means we guarantee visibility of an element in the queue if we see the index updated
    tail.lazySet(writeIndex + 1);
}
```



we keep a queue of per-thread queues, which is appended to once only, each time a new thread other than the stack owner recycles: when we run out of items in our stack we iterate this collection to scavenge those that can be reused. this permits us to incur minimal thread synchronisation whilst still recycling all items.



We store the Thread in a WeakReference as otherwise we may be the only ones that still hold a strong Reference to the Thread itself after it died because DefaultHandle will hold a reference to the Stack.
The biggest issue is if we do not use a WeakReference the Thread may not be able to be collected at all if the user will store a reference to the DefaultHandle somewhere and never clear this reference (or not clear it in a timely manner).







```java
// a queue that makes only moderate guarantees about visibility: items are seen in the correct order,
// but we aren't absolutely guaranteed to ever see anything at all, thereby keeping the queue cheap to maintain
private static final class WeakOrderQueue extends WeakReference<Thread> {

    static final WeakOrderQueue DUMMY = new WeakOrderQueue();

    // Let Link extend AtomicInteger for intrinsics. The Link itself will be used as writerIndex.
    @SuppressWarnings("serial")
    static final class Link extends AtomicInteger {
        final DefaultHandle<?>[] elements = new DefaultHandle[LINK_CAPACITY];

        int readIndex;
        Link next;
    }

    // Its important this does not hold any reference to either Stack or WeakOrderQueue.
    private static final class Head {
        private final AtomicInteger availableSharedCapacity;

        Link link;

        Head(AtomicInteger availableSharedCapacity) {
            this.availableSharedCapacity = availableSharedCapacity;
        }

        /**
         * Reclaim all used space and also unlink the nodes to prevent GC nepotism.
         */
        void reclaimAllSpaceAndUnlink() {
            Link head = link;
            link = null;
            int reclaimSpace = 0;
            while (head != null) {
                reclaimSpace += LINK_CAPACITY;
                Link next = head.next;
                // Unlink to help GC and guard against GC nepotism.
                head.next = null;
                head = next;
            }
            if (reclaimSpace > 0) {
                reclaimSpace(reclaimSpace);
            }
        }

        private void reclaimSpace(int space) {
            availableSharedCapacity.addAndGet(space);
        }

        void relink(Link link) {
            reclaimSpace(LINK_CAPACITY);
            this.link = link;
        }

        /**
         * Creates a new {@link} and returns it if we can reserve enough space for it, otherwise it
         * returns {@code null}.
         */
        Link newLink() {
            return reserveSpaceForLink(availableSharedCapacity) ? new Link() : null;
        }

        static boolean reserveSpaceForLink(AtomicInteger availableSharedCapacity) {
            for (;;) {
                int available = availableSharedCapacity.get();
                if (available < LINK_CAPACITY) {
                    return false;
                }
                if (availableSharedCapacity.compareAndSet(available, available - LINK_CAPACITY)) {
                    return true;
                }
            }
        }
    }

    // chain of data items
    private final Head head;
    private Link tail;
    // pointer to another queue of delayed items for the same stack
    private WeakOrderQueue next;
    private final int id = ID_GENERATOR.getAndIncrement();
    private final int interval;
    private int handleRecycleCount;

    private WeakOrderQueue() {
        super(null);
        head = new Head(null);
        interval = 0;
    }

    private WeakOrderQueue(Stack<?> stack, Thread thread) {
        super(thread);
        tail = new Link();

        // Its important that we not store the Stack itself in the WeakOrderQueue as the Stack also is used in
        // the WeakHashMap as key. So just store the enclosed AtomicInteger which should allow to have the
        // Stack itself GCed.
        head = new Head(stack.availableSharedCapacity);
        head.link = tail;
        interval = stack.delayedQueueInterval;
        handleRecycleCount = interval; // Start at interval so the first one will be recycled.
    }

    static WeakOrderQueue newQueue(Stack<?> stack, Thread thread) {
        // We allocated a Link so reserve the space
        if (!Head.reserveSpaceForLink(stack.availableSharedCapacity)) {
            return null;
        }
        final WeakOrderQueue queue = new WeakOrderQueue(stack, thread);
        // Done outside of the constructor to ensure WeakOrderQueue.this does not escape the constructor and so
        // may be accessed while its still constructed.
        stack.setHead(queue);

        return queue;
    }

    WeakOrderQueue getNext() {
        return next;
    }

    void setNext(WeakOrderQueue next) {
        assert next != this;
        this.next = next;
    }

    void reclaimAllSpaceAndUnlink() {
        head.reclaimAllSpaceAndUnlink();
        this.next = null;
    }

    void add(DefaultHandle<?> handle) {
        handle.lastRecycledId = id;

        // While we also enforce the recycling ratio when we transfer objects from the WeakOrderQueue to the Stack
        // we better should enforce it as well early. Missing to do so may let the WeakOrderQueue grow very fast
        // without control
        if (handleRecycleCount < interval) {
            handleRecycleCount++;
            // Drop the item to prevent recycling to aggressive.
            return;
        }
        handleRecycleCount = 0;

        Link tail = this.tail;
        int writeIndex;
        if ((writeIndex = tail.get()) == LINK_CAPACITY) {
            Link link = head.newLink();
            if (link == null) {
                // Drop it.
                return;
            }
            // We allocate a Link so reserve the space
            this.tail = tail = tail.next = link;

            writeIndex = tail.get();
        }
        tail.elements[writeIndex] = handle;
        handle.stack = null;
        // we lazy set to ensure that setting stack to null appears before we unnull it in the owning thread;
        // this also means we guarantee visibility of an element in the queue if we see the index updated
        tail.lazySet(writeIndex + 1);
    }

    boolean hasFinalData() {
        return tail.readIndex != tail.get();
    }

    // transfer as many items as we can from this queue to the stack, returning true if any were transferred
    @SuppressWarnings("rawtypes")
    boolean transfer(Stack<?> dst) {
        Link head = this.head.link;
        if (head == null) {
            return false;
        }

        if (head.readIndex == LINK_CAPACITY) {
            if (head.next == null) {
                return false;
            }
            head = head.next;
            this.head.relink(head);
        }

        final int srcStart = head.readIndex;
        int srcEnd = head.get();
        final int srcSize = srcEnd - srcStart;
        if (srcSize == 0) {
            return false;
        }

        final int dstSize = dst.size;
        final int expectedCapacity = dstSize + srcSize;

        if (expectedCapacity > dst.elements.length) {
            final int actualCapacity = dst.increaseCapacity(expectedCapacity);
            srcEnd = min(srcStart + actualCapacity - dstSize, srcEnd);
        }

        if (srcStart != srcEnd) {
            final DefaultHandle[] srcElems = head.elements;
            final DefaultHandle[] dstElems = dst.elements;
            int newDstSize = dstSize;
            for (int i = srcStart; i < srcEnd; i++) {
                DefaultHandle<?> element = srcElems[i];
                if (element.recycleId == 0) {
                    element.recycleId = element.lastRecycledId;
                } else if (element.recycleId != element.lastRecycledId) {
                    throw new IllegalStateException("recycled already");
                }
                srcElems[i] = null;

                if (dst.dropHandle(element)) {
                    // Drop the object.
                    continue;
                }
                element.stack = dst;
                dstElems[newDstSize ++] = element;
            }

            if (srcEnd == LINK_CAPACITY && head.next != null) {
                // Add capacity back as the Link is GCed.
                this.head.relink(head.next);
            }

            head.readIndex = srcEnd;
            if (dst.size == newDstSize) {
                return false;
            }
            dst.size = newDstSize;
            return true;
        } else {
            // The destination stack is full already.
            return false;
        }
    }
}
```





### Sample

*A 线程申请，A 线程回收的场景。*

- 显然，当对象的申请与回收是在一个线程中时，直接把对象放入到 A 线程的对象池中即可，不存在资源的竞争，简单轻松。

*A 线程申请，B 线程回收的场景。*

- 首先，当 A 线程通过其对象池申请了一个对象后，在 B 线程调用 recycle()方法回收该对象。显然，该对象是应该回收到 A 线程私有的对象池当中的，不然，该对象池也失去了其意义。
- 那么 B 线程中，并不会直接将该对象放入到 A 线程的对象池中，如果这样操作在多线程场景下存在资源的竞争，只有增加性能的开销，才能保证并发情况下的线程安全，显然不是 netty 想要看到的。
- 那么 B 线程会专门申请一个针对 A 线程回收的专属队列，在首次创建的时候会将该队列放入到 A 线程对象池的链表首节点（这里是唯一存在的资源竞争场景，需要加锁），并将被回收的对象放入到该专属队列中，宣告回收结束。
- 在 A 线程的对象池数组耗尽之后，将会尝试把各个别的线程针对 A 线程的专属队列里的对象重新放入到对象池数组中，以便下次继续使用。




## Allocator


```java
public class PooledByteBufAllocator extends AbstractByteBufAllocator implements ByteBufAllocatorMetricProvider {
    @Override
    protected ByteBuf newHeapBuffer(int initialCapacity, int maxCapacity) {
        PoolThreadCache cache = threadCache.get();
        PoolArena<byte[]> heapArena = cache.heapArena;

        final ByteBuf buf;
        if (heapArena != null) {
            buf = heapArena.allocate(cache, initialCapacity, maxCapacity);
        } else {
            buf = PlatformDependent.hasUnsafe() ?
                    new UnpooledUnsafeHeapByteBuf(this, initialCapacity, maxCapacity) :
                    new UnpooledHeapByteBuf(this, initialCapacity, maxCapacity);
        }

        return toLeakAwareBuffer(buf);
    }

    @Override
    protected ByteBuf newDirectBuffer(int initialCapacity, int maxCapacity) {
        PoolThreadCache cache = threadCache.get();
        PoolArena<ByteBuffer> directArena = cache.directArena;

        final ByteBuf buf;
        if (directArena != null) {
            buf = directArena.allocate(cache, initialCapacity, maxCapacity);
        } else {
            buf = PlatformDependent.hasUnsafe() ?
                    UnsafeByteBufUtil.newUnsafeDirectByteBuf(this, initialCapacity, maxCapacity) :
                    new UnpooledDirectByteBuf(this, initialCapacity, maxCapacity);
        }

        return toLeakAwareBuffer(buf);
    }

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
}
```

## Recv Allocator

guess size of buf, actual allocate using Allocator



## Type




- PoolThreadCache
- PoolArena
- PoolChunk



## Links

- [Netty](/docs/CS/Java/Netty/Netty.md)