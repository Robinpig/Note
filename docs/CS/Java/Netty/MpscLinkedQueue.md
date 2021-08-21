## Introduction

The code was inspired by the similarly named JCTools class:
https://github.com/JCTools/JCTools/blob/master/jctools-core/src/main/java/org/jctools/queues/atomic





```java
// NioEventLoop
protected static final int DEFAULT_MAX_PENDING_TASKS = Math.max(16,
            SystemPropertyUtil.getInt("io.netty.eventLoop.maxPendingTasks", Integer.MAX_VALUE));

private final Queue<Runnable> tailTasks;

private static Queue<Runnable> newTaskQueue(
        EventLoopTaskQueueFactory queueFactory) {
    if (queueFactory == null) {
        return newTaskQueue0(DEFAULT_MAX_PENDING_TASKS);
    }
    return queueFactory.newTaskQueue(DEFAULT_MAX_PENDING_TASKS);
}
```

Factory used to create Queue instances that will be used to store tasks for an EventLoop. Generally speaking the returned Queue MUST be thread-safe and depending on the EventLoop implementation must be of type java.util.concurrent.BlockingQueue.

```java
public interface EventLoopTaskQueueFactory {

    // Returns a new Queue to use.
    Queue<Runnable> newTaskQueue(int maxCapacity);
}
```



Create a new Queue which is safe to use for multiple producers (different threads) and a single consumer (one thread!).

```java
private static Queue<Runnable> newTaskQueue0(int maxPendingTasks) {
    // This event loop never calls takeTask()
    return maxPendingTasks == Integer.MAX_VALUE ? PlatformDependent.<Runnable>newMpscQueue()
            : PlatformDependent.<Runnable>newMpscQueue(maxPendingTasks);
}
```



default use `MpscUnboundedArrayQueue`

```java
// PlatformDependent

private static final boolean USE_MPSC_CHUNKED_ARRAY_QUEUE;
private static final int MPSC_CHUNK_SIZE =  1024;


static <T> Queue<T> newMpscQueue() {
  return USE_MPSC_CHUNKED_ARRAY_QUEUE ? new MpscUnboundedArrayQueue<T>(MPSC_CHUNK_SIZE)
    : new MpscUnboundedAtomicArrayQueue<T>(MPSC_CHUNK_SIZE);
}
```



```java
// define in BaseMpscLinkedArrayQueueColdProducerFields
private volatile long producerLimit;
protected long producerMask;
protected E[] producerBuffer;

// define in BaseMpscLinkedArrayQueueConsumerFields
private volatile long consumerIndex;
protected long consumerMask;
protected E[] consumerBuffer;
```





```java
public BaseMpscLinkedArrayQueue(final int initialCapacity)
{
  	// initialCapacity must >= 2
    RangeUtil.checkGreaterThanOrEqual(initialCapacity, 2, "initialCapacity");

    int p2capacity = Pow2.roundToPowerOfTwo(initialCapacity);
    // leave lower bit of mask clear
    long mask = (p2capacity - 1) << 1;
    // need extra element to point at next array
    E[] buffer = allocateRefArray(p2capacity + 1);
    producerBuffer = buffer;
    producerMask = mask;
    consumerBuffer = buffer;
    consumerMask = mask;
    soProducerLimit(mask); // we know it's all empty to start with
}
```



### offer

```java
@Override
public boolean offer(final E e)
{
    long mask;
    E[] buffer;
    long pIndex;

    while (true)
    {
        long producerLimit = lvProducerLimit();
        pIndex = lvProducerIndex();
        // lower bit is indicative of resize, if we see it we spin until it's cleared
        if ((pIndex & 1) == 1)
        {
            continue;
        }
        // pIndex is even (lower bit is 0) -> actual index is (pIndex >> 1)

        // mask/buffer may get changed by resizing -> only use for array access after successful CAS.
        mask = this.producerMask;
        buffer = this.producerBuffer;
        // a successful CAS ties the ordering, lv(pIndex) - [mask/buffer] -> cas(pIndex)

        // assumption behind this optimization is that queue is almost always empty or near empty
        if (producerLimit <= pIndex)
        {
            int result = offerSlowPath(mask, pIndex, producerLimit);
            switch (result)
            {
                case CONTINUE_TO_P_INDEX_CAS:
                    break;
                case RETRY:
                    continue;
                case QUEUE_FULL:
                    return false;
                case QUEUE_RESIZE:
                    resize(mask, buffer, pIndex, e, null);
                    return true;
            }
        }

        if (casProducerIndex(pIndex, pIndex + 2))
        {
            break;
        }
    }
    // INDEX visible before ELEMENT
    final long offset = modifiedCalcCircularRefElementOffset(pIndex, mask);
    soRefElement(buffer, offset, e); // release element e
    return true;
}
```







```java
/**
 * This method assumes index is actually (index << 1) because lower bit is
 * used for resize. This is compensated for by reducing the element shift.
 * The computation is constant folded, so there's no cost.
 */
static long modifiedCalcCircularRefElementOffset(long index, long mask)
{
    return REF_ARRAY_BASE + ((index & mask) << (REF_ELEMENT_SHIFT - 1));
}
```



```java
/**
 * We do not inline resize into this method because we do not resize on fill.
 */
private int offerSlowPath(long mask, long pIndex, long producerLimit)
{
    final long cIndex = lvConsumerIndex();
    long bufferCapacity = getCurrentBufferCapacity(mask);

    if (cIndex + bufferCapacity > pIndex)
    {
        if (!casProducerLimit(producerLimit, cIndex + bufferCapacity))
        {
            // retry from top
            return RETRY;
        }
        else
        {
            // continue to pIndex CAS
            return CONTINUE_TO_P_INDEX_CAS;
        }
    }
    // full and cannot grow
    else if (availableInQueue(pIndex, cIndex) <= 0)
    {
        // offer should return false;
        return QUEUE_FULL;
    }
    // grab index for resize -> set lower bit
    else if (casProducerIndex(pIndex, pIndex + 1))
    {
        // trigger a resize
        return QUEUE_RESIZE;
    }
    else
    {
        // failed resize attempt, retry from top
        return RETRY;
    }
}
```



```java
/**
 * An ordered store of an element to a given offset
 *
 * @param buffer this.buffer
 * @param offset computed via {@link UnsafeRefArrayAccess#calcCircularRefElementOffset}
 * @param e      an orderly kitty
 */
public static <E> void soRefElement(E[] buffer, long offset, E e)
{
    UNSAFE.putOrderedObject(buffer, offset, e);
}
```



### resize

```java
private void resize(long oldMask, E[] oldBuffer, long pIndex, E e, Supplier<E> s)
{
    assert (e != null && s == null) || (e == null || s != null);
    int newBufferLength = getNextBufferSize(oldBuffer);
    final E[] newBuffer;
    try
    {
        newBuffer = allocateRefArray(newBufferLength);
    }
    catch (OutOfMemoryError oom)
    {
        assert lvProducerIndex() == pIndex + 1;
        soProducerIndex(pIndex);
        throw oom;
    }

    producerBuffer = newBuffer;
    final int newMask = (newBufferLength - 2) << 1;
    producerMask = newMask;

    final long offsetInOld = modifiedCalcCircularRefElementOffset(pIndex, oldMask);
    final long offsetInNew = modifiedCalcCircularRefElementOffset(pIndex, newMask);

    soRefElement(newBuffer, offsetInNew, e == null ? s.get() : e);// element in new array
    soRefElement(oldBuffer, nextArrayOffset(oldMask), newBuffer);// buffer linked

    // ASSERT code
    final long cIndex = lvConsumerIndex();
    final long availableInQueue = availableInQueue(pIndex, cIndex);
    RangeUtil.checkPositive(availableInQueue, "availableInQueue");

    // Invalidate racing CASs
    // We never set the limit beyond the bounds of a buffer
    soProducerLimit(pIndex + Math.min(newMask, availableInQueue));

    // make resize visible to the other producers
    soProducerIndex(pIndex + 2);

    // INDEX visible before ELEMENT, consistent with consumer expectation

    // make resize visible to consumer
    soRefElement(oldBuffer, offsetInOld, JUMP);
}
```



### poll

Called from the consumer thread subject to the restrictions appropriate to the implementation and according to the Queue.poll() interface.
This implementation is correct for single consumer thread use only.

```java
@SuppressWarnings("unchecked")
@Override
public E poll()
{
    final E[] buffer = consumerBuffer;
    final long index = lpConsumerIndex();
    final long mask = consumerMask;

    final long offset = modifiedCalcCircularRefElementOffset(index, mask);
    Object e = lvRefElement(buffer, offset);
    if (e == null)
    {
        if (index != lvProducerIndex())
        {
            // poll() == null iff queue is empty, null element is not strong enough indicator, so we must
            // check the producer index. If the queue is indeed not empty we spin until element is
            // visible.
            do
            {
                e = lvRefElement(buffer, offset);
            }
            while (e == null);
        }
        else
        {
            return null;
        }
    }

    if (e == JUMP)
    {
        final E[] nextBuffer = nextBuffer(buffer, mask);
        return newBufferPoll(nextBuffer, index);
    }

    soRefElement(buffer, offset, null); // release element null
    soConsumerIndex(index + 2); // release cIndex
    return (E) e;
}
```



### size

```java
@Override
public int size()
{
    // NOTE: because indices are on even numbers we cannot use the size util.

    /*
     * It is possible for a thread to be interrupted or reschedule between the read of the producer and
     * consumer indices, therefore protection is required to ensure size is within valid range. In the
     * event of concurrent polls/offers to this method the size is OVER estimated as we read consumer
     * index BEFORE the producer index.
     */
    long after = lvConsumerIndex();
    long size;
    while (true)
    {
        final long before = after;
        final long currentProducerIndex = lvProducerIndex();
        after = lvConsumerIndex();
        if (before == after)
        {
            size = ((currentProducerIndex - after) >> 1);
            break;
        }
    }
    // Long overflow is impossible, so size is always positive. Integer overflow is possible for the unbounded
    // indexed queues.
    if (size > Integer.MAX_VALUE)
    {
        return Integer.MAX_VALUE;
    }
    else
    {
        return (int) size;
    }
}
```



```java
@Override
public boolean isEmpty()
{
    // Order matters!
    // Loading consumer before producer allows for producer increments after consumer index is read.
    // This ensures this method is conservative in it's estimate. Note that as this is an MPMC there is
    // nothing we can do to make this an exact method.
    return (this.lvConsumerIndex() == this.lvProducerIndex());
}
```



```java
abstract class BaseMpscLinkedArrayQueuePad1<E> extends AbstractQueue<E> implements IndexedQueue
{
    long p01, p02, p03, p04, p05, p06, p07;
    long p10, p11, p12, p13, p14, p15, p16, p17;
}
```



### BaseMpscLinkedArrayQueue

```java

public class MpscUnboundedAtomicArrayQueue<E> extends BaseMpscLinkedAtomicArrayQueue<E> {}
```

