# Queue



## Queue



### AbstractQueue



## Deque



### ArrayDeque



## PriorityQueue





## BlockingQueue

阻塞队列(BlockingQueue)是一个支持两个附加操作的队列。这两个附加的操作是：在队列为空时，获取元素的线程会等待队列变为非空。当队列满时，存储元素的线程会等待队列可用。阻塞队列常用于生产者和消费者的场景，生产者是往队列里添加元素的线程，消费者是从队列里拿元素的线程。阻塞队列就是生产者存放元素的容器，而消费者也只从容器里拿元素。

| Blocking Queue Name   | Description      |
| --------------------- | ---------------- |
| ArrayBlockingQueue    | array FIFO       |
| LinkedBlockingQueue   | linked tableFIFO |
| PriorityBlockingQueue |                  |
| DelayQueue            |                  |
| SynchronousQueue      |                  |
| LinkedTransferQueue   | transfer method  |
| LinkedBlockingDeque   | Deque            |


### ArrayBlockingQueue


### SynchronousQueue

*A blocking queue in which **each insert operation must wait for a corresponding remove operation by another thread, and vice versa**. A synchronous queue **does not have any internal capacity, not even a capacity of one**.*

*you cannot insert an element (using any method) unless another thread is trying to remove it;*

*The head of the queue is the element that the first queued inserting thread is trying to add to the queue; if there is no such queued thread then no element is available for removal and poll() will return null.*

*For purposes of other Collection methods (for example contains), a SynchronousQueue acts as an empty collection. This queue does not permit null elements.*

*Synchronous queues are similar to rendezvous channels used in CSP and Ada. They are well suited for handoff designs, in which an object running in one thread must sync up with an object running in another thread in order to hand it some information, event, or task.*
*This class supports an optional fairness policy for ordering waiting producer and consumer threads. By default, this ordering is not guaranteed. However, a queue constructed with fairness set to true grants threads access in FIFO order.*
*This class and its iterator implement all of the optional methods of the Collection and Iterator interfaces.*

```java
public class SynchronousQueue<E> extends AbstractQueue<E>
    implements BlockingQueue<E>, java.io.Serializable {}
```



`You cannot peek at a synchronous queue because an element is only present when you try to remove it.`

```java
public E peek() {
    return null;
}
```
`You cannot iterate as there is nothing to iterate.`

```java
public Iterator<E> iterator() {
    return Collections.emptyIterator();
}

public boolean isEmpty() {
    return true;
}

public int size() {
    return 0;
}

public int remainingCapacity() {
    return 0;
}
```



#### TransferQueue

