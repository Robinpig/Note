## Introduction

代码灵感来源于类似的 JCTools 类：
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

用于创建 Queue 实例的工厂，这些实例将用于存储 EventLoop 的任务。通常来说，返回的 Queue 必须是线程安全的，并且根据 EventLoop 的实现，必须是 java.util.concurrent.BlockingQueue 类型。

```java
public interface EventLoopTaskQueueFactory {

    //返回一个新的 Queue 供使用。
    Queue<Runnable> newTaskQueue(int maxCapacity);
}
```



创建一个适用于多生产者（不同线程）和单消费者（一个线程）的 Queue。

```java
private static Queue<Runnable> newTaskQueue0(int maxPendingTasks) {
    // This event loop never calls takeTask()
    return maxPendingTasks == Integer.MAX_VALUE ? PlatformDependent.<Runnable>newMpscQueue()
            : PlatformDependent.<Runnable>newMpscQueue(maxPendingTasks);
}
```



默认使用 `MpscUnboundedArrayQueue`

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
 * 此方法假定 index 实际上是 (index << 1)，因为低位用于表示扩容。
 * 这通过减少元素偏移来补偿。该计算是常量折叠的，因此没有额外成本。
 */
static long modifiedCalcCircularRefElementOffset(long index, long mask)
{
    return REF_ARRAY_BASE + ((index & mask) << (REF_ELEMENT_SHIFT - 1));
}
```



```java
/**
 * 我们不将 resize 内联到此方法中，因为我们不会在填充时立即扩容。
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
 * 将元素有序存储到给定偏移量
 *
 * @param buffer this.buffer
 * @param offset 通过 {@link UnsafeRefArrayAccess#calcCircularRefElementOffset} 计算
 * @param e      待存储的元素
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

从消费者线程调用，受限于实现的特定约束，并遵循 Queue.poll() 接口约定。
此实现仅适用于单消费者线程使用。

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
     * 线程可能在读取生产者和消费者索引之间被中断或重新调度，因此需要保护以确保 size 在有效范围内。
     * 在此方法发生并发 poll/offer 时，size 会被高估，因为我们在生产者索引之前读取消费者索引。
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




## Links

- [Netty](/docs/CS/Framework/Netty/Netty.md)
