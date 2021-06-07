# MpscLinkedQueue

The code was inspired by the similarly named JCTools class:
https://github.com/JCTools/JCTools/blob/master/jctools-core/src/main/java/org/jctools/queues/atomic



1. Unsupport remove & iterate


```java
/**
 * A multi-producer single consumer unbounded queue.
 * @param <E> the contained value type
 */
final class MpscLinkedQueue<E> extends AbstractQueue<E> implements BiPredicate<E, E> {

  private volatile LinkedQueueNode<E> producerNode;

  private final static AtomicReferenceFieldUpdater<MpscLinkedQueue, LinkedQueueNode> PRODUCER_NODE_UPDATER
        = AtomicReferenceFieldUpdater.newUpdater(MpscLinkedQueue.class, LinkedQueueNode.class, "producerNode");

  private volatile LinkedQueueNode<E> consumerNode;
  private final static AtomicReferenceFieldUpdater<MpscLinkedQueue, LinkedQueueNode> CONSUMER_NODE_UPDATER
        = AtomicReferenceFieldUpdater.newUpdater(MpscLinkedQueue.class, LinkedQueueNode.class, "consumerNode");

  public MpscLinkedQueue() {
     LinkedQueueNode<E> node = new LinkedQueueNode<>();
     CONSUMER_NODE_UPDATER.lazySet(this, node);
     PRODUCER_NODE_UPDATER.getAndSet(this, node);// this ensures correct construction:
     // StoreLoad
  }
 ... 
}
```





```java
static final class LinkedQueueNode<E>
{
   private volatile LinkedQueueNode<E> next;
   private final static AtomicReferenceFieldUpdater<LinkedQueueNode, LinkedQueueNode> NEXT_UPDATER
         = AtomicReferenceFieldUpdater.newUpdater(LinkedQueueNode.class, LinkedQueueNode.class, "next");

   private E value;

   LinkedQueueNode()
   {
      this(null);
   }


   LinkedQueueNode(@Nullable E val)
   {
      spValue(val);
   }

   /**
    * Gets the current value and nulls out the reference to it from this node.
    *
    * @return value
    */
   @Nullable
   public E getAndNullValue()
   {
      E temp = lpValue();
      spValue(null);
      return temp;
   }

   @Nullable
   public E lpValue()
   {
      return value;
   }

   public void spValue(@Nullable E newValue)
   {
      value = newValue;
   }

   public void soNext(@Nullable LinkedQueueNode<E> n)
   {
      NEXT_UPDATER.lazySet(this, n);
   }

   @Nullable
   public LinkedQueueNode<E> lvNext()
   {
      return next;
   }
}
```





poll



```java
/**
 * {@inheritDoc} <br>
 * <p>
 * IMPLEMENTATION NOTES:<br>
 * Poll is allowed from a SINGLE thread.<br>
 * Poll reads the next node from the consumerNode and:
 * <ol>
 * <li>If it is null, the queue is assumed empty (though it might not be).
 * <li>If it is not null set it as the consumer node and return it's now evacuated value.
 * </ol>
 * This means the consumerNode.value is always null, which is also the starting point for the queue.
 * Because null values are not allowed to be offered this is the only node with it's value set to null at
 * any one time.
 *
 * @see java.util.Queue#poll()
 */
@Nullable
@Override
public E poll() {
   LinkedQueueNode<E> currConsumerNode = consumerNode; // don't load twice, it's alright
   LinkedQueueNode<E> nextNode = currConsumerNode.lvNext();

   if (nextNode != null)
   {
      // we have to null out the value because we are going to hang on to the node
      final E nextValue = nextNode.getAndNullValue();

      // Fix up the next ref of currConsumerNode to prevent promoted nodes from keeping new ones alive.
      // We use a reference to self instead of null because null is already a meaningful value (the next of
      // producer node is null).
      currConsumerNode.soNext(currConsumerNode);
      CONSUMER_NODE_UPDATER.lazySet(this, nextNode);
      // currConsumerNode is now no longer referenced and can be collected
      return nextValue;
   }
   else if (currConsumerNode != producerNode)
   {
      while ((nextNode = currConsumerNode.lvNext()) == null) { }
      // got the next node...
      // we have to null out the value because we are going to hang on to the node
      final E nextValue = nextNode.getAndNullValue();

      // Fix up the next ref of currConsumerNode to prevent promoted nodes from keeping new ones alive.
      // We use a reference to self instead of null because null is already a meaningful value (the next of
      // producer node is null).
      currConsumerNode.soNext(currConsumerNode);
      CONSUMER_NODE_UPDATER.lazySet(this, nextNode);
      // currConsumerNode is now no longer referenced and can be collected
      return nextValue;
   }
   return null;
}
```





offer

```java
/**
 * {@inheritDoc} <br>
 * <p>
 * IMPLEMENTATION NOTES:<br>
 * Offer is allowed from multiple threads.<br>
 * Offer allocates a new node and:
 * <ol>
 * <li>Swaps it atomically with current producer node (only one producer 'wins')
 * <li>Sets the new node as the node following from the swapped producer node
 * </ol>
 * This works because each producer is guaranteed to 'plant' a new node and link the old node. No 2
 * producers can get the same producer node as part of XCHG guarantee.
 *
 * @see java.util.Queue#offer(java.lang.Object)
 */
@Override
@SuppressWarnings("unchecked")
public final boolean offer(final E e) {
   Objects.requireNonNull(e, "The offered value 'e' must be non-null");

   final LinkedQueueNode<E> nextNode = new LinkedQueueNode<>(e);
   final LinkedQueueNode<E> prevProducerNode = PRODUCER_NODE_UPDATER.getAndSet(this, nextNode);//CAS
   // Should a producer thread get interrupted here the chain WILL be broken until that thread is resumed
   // and completes the store in prev.next.
   prevProducerNode.soNext(nextNode); // StoreStore
   return true;
}
```