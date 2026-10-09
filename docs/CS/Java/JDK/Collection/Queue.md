## Introduction

A queue interface specifies that you can add elements at the tail end of the queue, remove them at the head, and find out how many elements are in the queue. 
You use a queue when you need to collect objects and retrieve them in a “first in, first out” fashion.

Queues provide additional insertion, extraction, and inspection operations.

Each of these methods exists in two forms: one throws an exception if the operation fails, the other returns a special
value (either null or false, depending on the operation).

The latter form of the insert operation is designed specifically for use with capacity-restricted Queue implementations;
in most implementations, insert operations cannot fail. Summary of Queue methods


|         | Throws exception | Returns special value |
| ------- | ---------------- | --------------------- |
| Insert  | `add(e)`         | `offer(e)`            |
| Remove  | `remove()`       | `poll()`              |
| Examine | `element()`      | `peek()`              |

Queues **typically, but do not necessarily**, order elements in a `FIFO (first-in-first-out)` manner.
Among the exceptions are priority queues, which order elements according to a supplied comparator, or the elements' natural ordering,
and LIFO queues (or stacks) which order the elements LIFO (last-in-first-out).
Whatever the ordering used, the head of the queue is that element which would be removed by a call to remove() or poll().
In a FIFO queue, all new elements are inserted at the tail of the queue.
Other kinds of queues may use different placement rules.
Every Queue implementation must specify its ordering properties.

<div style="text-align: center;">

![Fig.1. Queue](img/Queue.png)

</div>

<p style="text-align: center;">
Fig.1. Queue
</p>

```java
public interface Queue<E> extends Collection<E> {
    boolean add(E e);

    boolean offer(E e);

    E remove();

    E poll();

    E element();

    E peek();
}
```

### AbstractQueue

## Deque

<table>
    <thead>
        <tr>
            <th></th>
            <th colspan="2">First Element (Head)</th>
          	<th colspan="2">Last Element (Tail)</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td></td>
            <td>Throws exception</td>
            <td>Special value</td>
          	<td>Throws exception</td>
          	<td>Special value</td>
        </tr>
        <tr>
          	<th>Insert</th>
            <td>addFirst(e)</td>
            <td>offerFirst(e)</td>
            <td>addLast(e)</td>
            <td>offerLast(e)</td>
        </tr>
        <tr>
          	<th>Remove</th>
            <td>removeFirst()</td>
            <td>pollFirst()</td>
            <td>removeLast()</td>
            <td>pollLast()</td>
        </tr>
        <tr>
          	<th>Examine</th>
            <td>getFirst()</td>
            <td>peekFirst()</td>
            <td>getLast()</td>
            <td>peekLast()</td>
        </tr>
    </tbody>
</table>

#### Queue Method Equivalent Deque Method


| Queue Method | Equivalent Deque Method |
| ------------ | ----------------------- |
| add(e)       | addLast(e)              |
| offer(e)     | offerLast(e)            |
| remove()     | removeFirst()           |
| poll()       | pollFirst()             |
| element()    | getFirst()              |
| peek()       | peekFirst()             |

#### Comparison of Stack and Deque methods

Deques can also be used as LIFO (Last-In-First-Out) stacks. This interface should be used in preference to the legacy `Stack` class.
When a deque is used as a stack, elements are pushed and popped from the beginning of the deque.
Stack methods are precisely equivalent to Deque methods as indicated in the table below:


| Stack Method | Equivalent Deque Method |
| ------------ | ----------------------- |
| push(e)      | addFirst(e)             |
| pop()        | removeFirst()           |
| peek()       | peekFirst()             |

### ArrayDeque

Resizable-array implementation of the Deque interface.
Array deques have no capacity restrictions; they grow as necessary to support usage.
They are not thread-safe; in the absence of external synchronization, they do not support concurrent access by multiple threads.
Null elements are prohibited. This class is likely to be faster than Stack when used as a stack, and faster than LinkedList when used as a queue.

Most ArrayDeque operations run in amortized constant time. Exceptions include remove, removeFirstOccurrence, removeLastOccurrence, contains, iterator.remove(), and the bulk operations, all of which run in linear time.

The iterators returned by this class's iterator method are fail-fast:
If the deque is modified at any time after the iterator is created, in any way except through the iterator's own remove method, the iterator will generally throw a **ConcurrentModificationException**.
Thus, in the face of concurrent modification, the iterator fails quickly and cleanly, rather than risking arbitrary, non-deterministic behavior at an undetermined time in the future.

Note that the fail-fast behavior of an iterator cannot be guaranteed as it is, generally speaking, impossible to make any hard guarantees in the presence of unsynchronized concurrent modification.
Fail-fast iterators throw ConcurrentModificationException on a best-effort basis.
Therefore, it would be wrong to write a program that depended on this exception for its correctness: the fail-fast behavior of iterators should be used only to detect bugs.

This class and its iterator implement all of the optional methods of the Collection and Iterator interfaces.

```java
    /*
     * VMs excel at optimizing simple array loops where indices are
     * incrementing or decrementing over a valid slice, e.g.
     *
     * for (int i = start; i < end; i++) ... elements[i]
     *
     * Because in a circular array, elements are in general stored in
     * two disjoint such slices, we help the VM by writing unusual
     * nested loops for all traversals over the elements.  Having only
     * one hot inner loop body instead of two or three eases human
     * maintenance and encourages VM loop inlining into the caller.
     */

    /**
     * The array in which the elements of the deque are stored.
     * All array cells not holding deque elements are always null.
     * The array always has at least one null slot (at tail).
     */
    transient Object[] elements;

    /**
     * The index of the element at the head of the deque (which is the
     * element that would be removed by remove() or pop()); or an
     * arbitrary number 0 <= head < elements.length equal to tail if
     * the deque is empty.
     */
    transient int head;

    /**
     * The index at which the next element would be added to the tail
     * of the deque (via addLast(E), add(E), or push(E));
     * elements[tail] is always null.
     */
    transient int tail;

    /**
     * The maximum size of array to allocate.
     * Some VMs reserve some header words in an array.
     * Attempts to allocate larger arrays may result in
     * OutOfMemoryError: Requested array size exceeds VM limit
     */
    private static final int MAX_ARRAY_SIZE = Integer.MAX_VALUE - 8;
```

## ConcurrentLinkedQueue

unbounded queue
head tail volatile

```java

private static class Node<E> {
   volatile E item;
   volatile Node<E> next;

   /**
    * Constructs a new node.  Uses relaxed write because item can
    * only be seen after publication via casNext.
    */
   Node(E item) {
      UNSAFE.putObject(this, itemOffset, item);
   }

   boolean casItem(E cmp, E val) {
      return UNSAFE.compareAndSwapObject(this, itemOffset, cmp, val);
   }

   void lazySetNext(Node<E> val) {
      UNSAFE.putOrderedObject(this, nextOffset, val);
   }

   boolean casNext(Node<E> cmp, Node<E> val) {
      return UNSAFE.compareAndSwapObject(this, nextOffset, cmp, val);
   }

   // Unsafe mechanics
...
}

 /**
  * A node from which the first live (non-deleted) node (if any)
  * can be reached in O(1) time.
  * Invariants:
  * - all live nodes are reachable from head via succ()
  * - head != null
  * - (tmp = head).next != tmp || tmp != head
  * Non-invariants:
  * - head.item may or may not be null.
  * - it is permitted for tail to lag behind head, that is, for tail
  *   to not be reachable from head!
  */
 private transient volatile Node<E> head;

 /**
  * A node from which the last node on list (that is, the unique
  * node with node.next == null) can be reached in O(1) time.
  * Invariants:
  * - the last node is always reachable from tail via succ()
  * - tail != null
  * Non-invariants:
  * - tail.item may or may not be null.
  * - it is permitted for tail to lag behind head, that is, for tail
  *   to not be reachable from head!
  * - tail.next may or may not be self-pointing to tail.
  */
 private transient volatile Node<E> tail;
```

cas

## PriorityQueue

An unbounded priority queue based on a priority heap. 
The elements of the priority queue are ordered according to their natural ordering, or by a Comparator provided at queue construction time, depending on which constructor is used.
A priority queue does not permit null elements. 
A priority queue relying on natural ordering also does not permit insertion of non-comparable objects (doing so may result in ClassCastException).

The head of this queue is the least element with respect to the specified ordering. 
If multiple elements are tied for least value, the head is one of those elements -- ties are broken arbitrarily. 
The queue retrieval operations poll, remove, peek, and element access the element at the head of the queue.
A
priority queue is unbounded, but has an internal capacity governing the size of an array used to store the elements on the queue. 
It is always at least as large as the queue size. As elements are added to a priority queue, its capacity grows automatically. 
The details of the growth policy are not specified.

This class and its iterator implement all of the optional methods of the Collection and Iterator interfaces. 
The Iterator provided in method iterator() and the Spliterator provided in method spliterator() are not guaranteed to traverse the elements of the priority queue in any particular order. 
If you need ordered traversal, consider using Arrays.sort(pq.toArray()).

|             |              |        |
| ----------- | ------------ | ------ |
| Root index  | 0            | 1      |
| Left index  | 2i+1         | 2i     |
| Right index | 2i+2         | 2i+1   |
| Get parent  | (i - 1) >>>1 | i >>>1 |

### siftUp

```java
/**
 * Inserts item x at position k, maintaining heap invariant by
 * promoting x up the tree until it is greater than or equal to
 * its parent, or is the root.
 *
 * To simplify and speed up coercions and comparisons, the
 * Comparable and Comparator versions are separated into different
 * methods that are otherwise identical. (Similarly for siftDown.)
 *
 * @param k the position to fill
 * @param x the item to insert
 */
private void siftUp(int k, E x) {
    if (comparator != null)
        siftUpUsingComparator(k, x, queue, comparator);
    else
        siftUpComparable(k, x, queue);
}

private static <T> void siftUpComparable(int k, T x, Object[] es) {
    Comparable<? super T> key = (Comparable<? super T>) x;
    while (k > 0) {
        int parent = (k - 1) >>> 1;
        Object e = es[parent];
        if (key.compareTo((T) e) >= 0)
            break;
        es[k] = e;
        k = parent;
    }
    es[k] = key;
}

private static <T> void siftUpUsingComparator(
    int k, T x, Object[] es, Comparator<? super T> cmp) {
    while (k > 0) {
        int parent = (k - 1) >>> 1;
        Object e = es[parent];
        if (cmp.compare(x, (T) e) >= 0)
            break;
        es[k] = e;
        k = parent;
    }
    es[k] = x;
}
```

### siftDown

```java
/**
 * Inserts item x at position k, maintaining heap invariant by
 * demoting x down the tree repeatedly until it is less than or
 * equal to its children or is a leaf.
 *
 * @param k the position to fill
 * @param x the item to insert
 */
private void siftDown(int k, E x) {
    if (comparator != null)
        siftDownUsingComparator(k, x, queue, size, comparator);
    else
        siftDownComparable(k, x, queue, size);
}

private static <T> void siftDownComparable(int k, T x, Object[] es, int n) {
    // assert n > 0;
    Comparable<? super T> key = (Comparable<? super T>)x;
    int half = n >>> 1;           // loop while a non-leaf
    while (k < half) {
        int child = (k << 1) + 1; // assume left child is least
        Object c = es[child];
        int right = child + 1;
        if (right < n &&
            ((Comparable<? super T>) c).compareTo((T) es[right]) > 0)
            c = es[child = right];
        if (key.compareTo((T) c) <= 0)
            break;
        es[k] = c;
        k = child;
    }
    es[k] = key;
}

private static <T> void siftDownUsingComparator(
    int k, T x, Object[] es, int n, Comparator<? super T> cmp) {
    // assert n > 0;
    int half = n >>> 1;
    while (k < half) {
        int child = (k << 1) + 1;
        Object c = es[child];
        int right = child + 1;
        if (right < n && cmp.compare((T) c, (T) es[right]) > 0)
            c = es[child = right];
        if (cmp.compare(x, (T) c) <= 0)
            break;
        es[k] = c;
        k = child;
    }
    es[k] = x;
}
```

## BlockingQueue

A Queue that additionally supports operations that:

1. wait for the queue to become non-empty when retrieving an element
2. wait for space to become available in the queue when storing an element.

BlockingQueue methods come in four forms, with different ways of handling operations that cannot be satisfied immediately, but may be satisfied at some point in the future: one throws an exception, the second returns a special value (either null or false, depending on the operation), the third blocks the current thread indefinitely until the operation can succeed, and the fourth blocks for only a given maximum time limit before giving up.

These methods are summarized in the following table:


|             | Throws exception | Special value | Blocks         | Times out            |
| ----------- | ---------------- | ------------- | -------------- | -------------------- |
| **Insert**  | add(e)           | offer(e)      | put(e)         | offer(e, time, unit) |
| **Remove**  | remove()         | poll()        | take()         | poll(time, unit)     |
| **Examine** | element()        | peek()        | not applicable | not applicable       |

A BlockingQueue **does not accept null elements**. Implementations throw **NullPointerException** on attempts to add, put or offer a null. A null is used as a sentinel value to indicate failure of *poll* operations.

A BlockingQueue may be capacity bounded. At any given time it may have a remainingCapacity beyond which no additional elements can be put without blocking. A BlockingQueue without any intrinsic capacity constraints always reports a remaining capacity of Integer.MAX_VALUE.

BlockingQueue implementations are designed to be used primarily for producer-consumer queues, but additionally support the Collection interface. So, for example, it is possible to remove an arbitrary element from a queue using remove(x). However, such operations are in general not performed very efficiently, and are intended for only occasional use, such as when a queued message is cancelled.

BlockingQueue implementations are thread-safe. All queuing methods achieve their effects atomically using internal locks or other forms of concurrency control. However, the bulk Collection operations addAll, containsAll, retainAll and removeAll are not necessarily performed atomically unless specified otherwise in an implementation. So it is possible, for example, for addAll(c) to fail (throwing an exception) after adding only some of the elements in c.

A BlockingQueue does not intrinsically support any kind of "close" or "shutdown" operation to indicate that no more items will be added. The needs and usage of such features tend to be implementation-dependent. For example, a common tactic is for producers to insert special end-of-stream or poison objects, that are interpreted accordingly when taken by consumers.

Usage example, based on a typical producer-consumer scenario. Note that a BlockingQueue can safely be used with multiple producers and multiple consumers.

### Example

```java
class Producer implements Runnable {
   private final BlockingQueue queue;
   Producer(BlockingQueue q) { queue = q; }
   public void run() {
     try {
       while (true) { queue.put(produce()); }
     } catch (InterruptedException ex) { ... handle ...}
   }
   Object produce() { ... }
 }

 class Consumer implements Runnable {
   private final BlockingQueue queue;
   Consumer(BlockingQueue q) { queue = q; }
   public void run() {
     try {
       while (true) { consume(queue.take()); }
     } catch (InterruptedException ex) { ... handle ...}
   }
   void consume(Object x) { ... }
 }

 class Setup {
   void main() {
     BlockingQueue q = new SomeQueueImplementation();
     Producer p = new Producer(q);
     Consumer c1 = new Consumer(q);
     Consumer c2 = new Consumer(q);
     new Thread(p).start();
     new Thread(c1).start();
     new Thread(c2).start();
   }
 }
```

**Memory consistency effects**: As with other concurrent collections, actions in a thread prior to placing an object into a BlockingQueue happen-before actions subsequent to the access or removal of that element from the BlockingQueue in another thread.
This interface is a member of the Java Collections Framework.


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

1 [ReentrantLock](/docs/CS/Java/JDK/Concurrency/ReentrantLock.md) and 2 conditions

```java
/** Main lock guarding all access */
final ReentrantLock lock;

/** Condition for waiting takes */
@SuppressWarnings("serial")  // Classes implementing Condition may be serializable.
private final Condition notEmpty;

/** Condition for waiting puts */
@SuppressWarnings("serial")  // Classes implementing Condition may be serializable.
private final Condition notFull;
```

```java
public ArrayBlockingQueue(int capacity) {
  this(capacity, false);
}

/**
  * Creates an {@code ArrayBlockingQueue} with the given (fixed)
  * capacity and the specified access policy.
  */
public ArrayBlockingQueue(int capacity, boolean fair) {
  if (capacity <= 0)
    throw new IllegalArgumentException();
  this.items = new Object[capacity];
  lock = new ReentrantLock(fair);
  notEmpty = lock.newCondition();
  notFull =  lock.newCondition();
}



public ArrayBlockingQueue(int capacity, boolean fair,
                          Collection<? extends E> c) {
    this(capacity, fair);

    final ReentrantLock lock = this.lock;
    lock.lock(); // Lock only for visibility, not mutual exclusion
    try {
        final Object[] items = this.items;
        int i = 0;
        try {
            for (E e : c)
                items[i++] = Objects.requireNonNull(e);
        } catch (ArrayIndexOutOfBoundsException ex) {
            throw new IllegalArgumentException();
        }
        count = i;
        putIndex = (i == capacity) ? 0 : i;
    } finally {
        lock.unlock();
    }
}
```

### LinkedBlockingQueue

takeLock and putLock

```java
/** Lock held by take, poll, etc */
private final ReentrantLock takeLock = new ReentrantLock();

/** Wait queue for waiting takes */
private final Condition notEmpty = takeLock.newCondition();

/** Lock held by put, offer, etc */
private final ReentrantLock putLock = new ReentrantLock();

/** Wait queue for waiting puts */
private final Condition notFull = putLock.newCondition();
```

```java
public void put(E e) throws InterruptedException {
    if (e == null) throw new NullPointerException();
    final int c;
    final Node<E> node = new Node<E>(e);
    final ReentrantLock putLock = this.putLock;
    final AtomicInteger count = this.count;
    putLock.lockInterruptibly();
    try {
        /*
         * Note that count is used in wait guard even though it is
         * not protected by lock. This works because count can
         * only decrease at this point (all other puts are shut
         * out by lock), and we (or some other waiting put) are
         * signalled if it ever changes from capacity. Similarly
         * for all other uses of count in other wait guards.
         */
        while (count.get() == capacity) {
            notFull.await();
        }
        enqueue(node);
        c = count.getAndIncrement();
        if (c + 1 < capacity)
            notFull.signal();
    } finally {
        putLock.unlock();
    }
    if (c == 0) // isEmpty before current put
        signalNotEmpty();
}
```

### DelayQueue

`DelayQueue` 是一个**无界阻塞队列，只有「到期」的元素才能被取出**。元素必须实现 `Delayed`：

```java
public interface Delayed extends Comparable<Delayed> {
    long getDelay(TimeUnit unit);   // 返回剩余的延迟时间，<=0 表示已到期
}
```

即元素自己要会算「还剩多久」，同时能互相比较（`compareTo` 决定堆内顺序，通常是按到期时间升序）。

内部结构是「一把锁 + 一个 `PriorityQueue`」：

```java
public class DelayQueue<E extends Delayed> extends AbstractQueue<E>
    implements BlockingQueue<E> {

    private final transient ReentrantLock lock = new ReentrantLock();
    private final PriorityQueue<E> q = new PriorityQueue<E>();

    /**
     * Thread designated to wait for the element at the head of
     * the queue. This variant of the Leader-Follower pattern
     * (http://www.cs.wustl.edu/~schmidt/POSA/POSA2/) serves to
     * minimize unnecessary timed waiting. When a thread becomes
     * the leader, it waits only for the next delay to elapse, but
     * other threads await indefinitely.
     */
    private Thread leader;

    private final Condition available = lock.newCondition();
}
```

#### Leader-Follower

`take()` 是这个类最值得看的地方。朴素实现里每个等待线程都 `awaitNanos(自己的剩余时间)`，但**所有线程等的其实都是同一个队首元素**，于是会有 N 个定时器在跑。`DelayQueue` 用 Leader-Follower 消掉这个浪费：**只有一个线程（leader）做定时等待，其余线程无限期等待**。

```java
public E take() throws InterruptedException {
    final ReentrantLock lock = this.lock;
    lock.lockInterruptibly();
    try {
        for (;;) {
            E first = q.peek();
            if (first == null)
                available.await();                      // 空队列：无限期等
            else {
                long delay = first.getDelay(NANOSECONDS);
                if (delay <= 0L)
                    return q.poll();                    // 已到期：直接取走
                first = null;                           // 等待期间不再持有引用
                if (leader != null)
                    available.await();                  // 已有 leader：自己无限期等
                else {
                    Thread thisThread = Thread.currentThread();
                    leader = thisThread;                // 抢占 leader
                    try {
                        available.awaitNanos(delay);    // 只有 leader 做定时等待
                    } finally {
                        if (leader == thisThread)
                            leader = null;
                    }
                }
            }
        }
    } finally {
        if (leader == null && q.peek() != null)
            available.signal();                         // 交班：唤醒一个 follower
        lock.unlock();
    }
}
```

`offer` 侧对应地要做一件事：**如果新元素成了队首，必须让旧 leader 作废**，否则旧 leader 还在按老元素的剩余时间等：

```java
public boolean offer(E e) {
    final ReentrantLock lock = this.lock;
    lock.lock();
    try {
        q.offer(e);
        if (q.peek() == e) {          // 新元素插到了堆顶
            leader = null;            // 旧 leader 的等待时间已失效
            available.signal();       // 唤醒一个 follower 重新抢 leader
        }
        return true;
    } finally {
        lock.unlock();
    }
}
```

#### Expired Head

「到期」是相对队首而言的，取元素只看堆顶：

```java
public E poll() {
    final ReentrantLock lock = this.lock;
    lock.lock();
    try {
        E first = q.peek();
        return (first == null || first.getDelay(NANOSECONDS) > 0)
            ? null                    // 队首还没到期 → 整个队列没有可取元素
            : q.poll();
    } finally {
        lock.unlock();
    }
}
```

由此推出四条容易踩的语义：

1. **`poll()` 返回 `null` 不代表队列空**，只代表「队首未到期」。
2. **`size()` 包含未到期的元素**，`isEmpty()` 同样如此。
3. **`peek()` 是唯一例外**：它返回队首而**不管到期与否**（javadoc 明说 "returns the element that will expire next"）。
4. **不受 `remainingCapacity` / 超时限制**：队列无界，`put` / `offer` 永不阻塞，所以 `SynchronousQueue` 那套「必须配对」的约束这里没有。

> [!WARNING]
>
> `getDelay` 的返回值会被 `take()` 直接当纳秒用（`available.awaitNanos(delay)`），所以 **`compareTo` 与 `getDelay` 必须用同一个时间源**。混用 `System.currentTimeMillis()` 与 `System.nanoTime()` 会造出「堆顶不是最早到期」的错乱顺序，表现为任务延迟触发。

典型用法：延迟任务调度、缓存条目过期、超时连接回收——`ScheduledThreadPoolExecutor` 的 `DelayedWorkQueue` 就是同一套思路的专用实现。

### SynchronousQueue

A blocking queue in which **each insert operation must wait for a corresponding remove operation by another thread, and vice versa**.
A synchronous queue **does not have any internal capacity, not even a capacity of one**.

The head of the queue is the element that the first queued inserting thread is trying to add to the queue; if there is
no such queued thread then no element is available for removal and poll() will return null.

For purposes of other Collection methods (for example contains), a SynchronousQueue acts as an empty collection. This
queue does not permit null elements.

Synchronous queues are similar to rendezvous channels used in CSP and Ada. 
They are well suited for handoff designs, in
which an object running in one thread must sync up with an object running in another thread in order to hand it some
information, event, or task.
This class supports an optional fairness policy for ordering waiting producer and consumer threads. By default, this
ordering is not guaranteed. However, a queue constructed with fairness set to true grants threads access in FIFO order.
This class and its iterator implement all of the optional methods of the Collection and Iterator interfaces.

```java
public class SynchronousQueue<E> extends AbstractQueue<E>
        implements BlockingQueue<E>, java.io.Serializable {

   private ReentrantLock qlock;
   private WaitQueue waitingProducers;
   private WaitQueue waitingConsumers;


   /**
    * The transferer. Set only in constructor, but cannot be declared
    * as final without further complicating serialization.  Since
    * this is accessed only at most once per public method, there
    * isn't a noticeable performance penalty for using volatile
    * instead of final here.
    */
   private transient volatile Transferer<E> transferer;

   abstract static class Transferer<E> {
      // Performs a put or take.
      abstract E transfer(E e, boolean timed, long nanos);
   }

   public SynchronousQueue(boolean fair) { // default false
      transferer = fair ? new TransferQueue<E>() : new TransferStack<E>();
   }
}
```

You cannot peek at a synchronous queue because an element is only present when you try to remove it.
You cannot iterate as there is nothing to iterate.

```java
   public E peek() {
      return null;
   }

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

#### transfer

both of them call *transfer()*, and *put* send a param

```java
// Adds the specified element to this queue, waiting if necessary for another thread to receive it.
public void put(E e) throws InterruptedException {
    if (e == null) throw new NullPointerException();
    if (transferer.transfer(e, false, 0) == null) {
        Thread.interrupted();
        throw new InterruptedException();
    }
}

// Retrieves and removes the head of this queue, waiting if necessary for another thread to insert it.
public E take() throws InterruptedException {
    E e = transferer.transfer(null, false, 0);
    if (e != null)
        return e;
    Thread.interrupted();
    throw new InterruptedException();
}
```

#### TransferStack

Basic algorithm is to loop trying one of three actions:

1. If apparently empty or already containing nodes of same mode, try to push node on stack and wait for a match, returning it, or null if cancelled.
2. If apparently containing node of complementary mode, try to push a fulfilling node on to stack, match with corresponding waiting node, pop both from stack, and return matched item. The matching or unlinking might not actually be necessary because of other threads performing action 3:
3. If top of stack already holds another fulfilling node, help it out by doing its match and/or pop
   operations, and then continue. The code for helping is essentially the same as for fulfilling, except that it doesn't return the item.

```java
/** 
 * Puts or takes an item.
 */
@SuppressWarnings("unchecked")
E transfer(E e, boolean timed, long nanos) {
    SNode s = null; // constructed/reused as needed
    int mode = (e == null) ? REQUEST : DATA;

    for (;;) {
        SNode h = head;
        if (h == null || h.mode == mode) {  // empty or same-mode
            if (timed && nanos <= 0L) {     // can't wait
                if (h != null && h.isCancelled())
                    casHead(h, h.next);     // pop cancelled node
                else
                    return null;
            } else if (casHead(h, s = snode(s, e, h, mode))) {
                SNode m = awaitFulfill(s, timed, nanos);
                if (m == s) {               // wait was cancelled
                    clean(s);
                    return null;
                }
                if ((h = head) != null && h.next == s)
                    casHead(h, s.next);     // help s's fulfiller
                return (E) ((mode == REQUEST) ? m.item : s.item);
            }
        } else if (!isFulfilling(h.mode)) { // try to fulfill
            if (h.isCancelled())            // already cancelled
                casHead(h, h.next);         // pop and retry
            else if (casHead(h, s=snode(s, e, h, FULFILLING|mode))) {
                for (;;) { // loop until matched or waiters disappear
                    SNode m = s.next;       // m is s's match
                    if (m == null) {        // all waiters are gone
                        casHead(s, null);   // pop fulfill node
                        s = null;           // use new node next time
                        break;              // restart main loop
                    }
                    SNode mn = m.next;
                    if (m.tryMatch(s)) {
                        casHead(s, mn);     // pop both s and m
                        return (E) ((mode == REQUEST) ? m.item : s.item);
                    } else                  // lost match
                        s.casNext(m, mn);   // help unlink
                }
            }
        } else {                            // help a fulfiller
            SNode m = h.next;               // m is h's match
            if (m == null)                  // waiter is gone
                casHead(h, null);           // pop fulfilling node
            else {
                SNode mn = m.next;
                if (m.tryMatch(h))          // help match
                    casHead(h, mn);         // pop both h and m
                else                        // lost match
                    h.casNext(m, mn);       // help unlink
            }
        }
    }
}
```

```java
static final class SNode {
    volatile SNode next;        // next node in stack
    volatile SNode match;       // the node matched to this
    volatile Thread waiter;     // to control park/unpark
    Object item;                // data; or null for REQUESTs
    int mode;
    // Note: item and mode fields don't need to be volatile
    // since they are always written before, and read after,
    // other volatile/atomic operations.

    SNode(Object item) {
        this.item = item;
    }
}
```

#### TransferQueue

Basic algorithm is to loop trying to take either of
two actions:

1. If queue apparently empty or holding same-mode nodes, try to add node to queue of waiters, wait to be fulfilled (or cancelled) and return matching item.
2. If queue apparently contains waiting items, and this call is of complementary mode, try to fulfill by CAS'ing item field of waiting node and dequeuing it, and then returning matching item.

In each case, along the way, check for and try to help advance head and tail on behalf of other stalled/slow threads.

The loop starts off with a null check guarding against seeing uninitialized head or tail values. This never happens in current SynchronousQueue, but could if callers held non-volatile/final ref to the transferer. The check is here anyway because it places null checks at top of loop, which is usually faster than having them implicitly interspersed.

```java
E transfer(E e, boolean timed, long nanos) {
    QNode s = null; // constructed/reused as needed
    boolean isData = (e != null);

    for (;;) {
        QNode t = tail;
        QNode h = head;
        if (t == null || h == null)         // saw uninitialized value
            continue;                       // spin

        if (h == t || t.isData == isData) { // empty or same-mode
            QNode tn = t.next;
            if (t != tail)                  // inconsistent read
                continue;
            if (tn != null) {               // lagging tail
                advanceTail(t, tn);
                continue;
            }
            if (timed && nanos <= 0L)       // can't wait
                return null;
            if (s == null)
                s = new QNode(e, isData);
            if (!t.casNext(null, s))        // failed to link in
                continue;

            advanceTail(t, s);              // swing tail and wait
            Object x = awaitFulfill(s, e, timed, nanos);
            if (x == s) {                   // wait was cancelled
                clean(t, s);
                return null;
            }

            if (!s.isOffList()) {           // not already unlinked
                advanceHead(t, s);          // unlink if head
                if (x != null)              // and forget fields
                    s.item = s;
                s.waiter = null;
            }
            return (x != null) ? (E)x : e;

        } else {                            // complementary-mode
            QNode m = h.next;               // node to fulfill
            if (t != tail || m == null || h != head)
                continue;                   // inconsistent read

            Object x = m.item;
            if (isData == (x != null) ||    // m already fulfilled
                x == m ||                   // m cancelled
                !m.casItem(x, e)) {         // lost CAS
                advanceHead(h, m);          // dequeue and retry
                continue;
            }

            advanceHead(h, m);              // successfully fulfilled
            LockSupport.unpark(m.waiter);
            return (x != null) ? (E)x : e;
        }
    }
}
```

```java
static final class QNode {
    volatile QNode next;          // next node in queue
    volatile Object item;         // CAS'ed to or from null
    volatile Thread waiter;       // to control park/unpark
    final boolean isData;

    QNode(Object item, boolean isData) {
        this.item = item;
        this.isData = isData;
    }
}
```

### PriorityBlockingQueue

```java
/**
 * Default array capacity.
 */
private static final int DEFAULT_INITIAL_CAPACITY = 11;

/**
 * Priority queue represented as a balanced binary heap: the two
 * children of queue[n] are queue[2*n+1] and queue[2*(n+1)].  The
 * priority queue is ordered by comparator, or by the elements'
 * natural ordering, if comparator is null: For each node n in the
 * heap and each descendant d of n, n <= d.  The element with the
 * lowest value is in queue[0], assuming the queue is nonempty.
 */
private transient Object[] queue;

// The number of elements in the priority queue.
private transient int size;

// The comparator, or null if priority queue uses elements' natural ordering.
private transient Comparator<? super E> comparator;

// Lock used for all public operations.
private final ReentrantLock lock = new ReentrantLock();

// Condition for blocking when empty.
@SuppressWarnings("serial") // Classes implementing Condition may be serializable.
private final Condition notEmpty = lock.newCondition();

// Spinlock for allocation, acquired via CAS.
private transient volatile int allocationSpinLock;
```

#### Growth

`PriorityBlockingQueue` 无界，扩容时不阻塞消费者：它**先释放主锁**，用一个 CAS 自旋锁抢到扩容权，分配完新数组再重新拿锁：

```java
private void tryGrow(Object[] array, int oldCap) {
    lock.unlock();                  // 必须释放主锁再重拿：扩容期间允许 poll 继续进行
    Object[] newArray = null;
    if (allocationSpinLock == 0 &&
        ALLOCATIONSPINLOCK.compareAndSet(this, 0, 1)) {
        try {
            int growth = (oldCap < 64)
                ? (oldCap + 2)                          // 小堆长得快点
                : (oldCap >> 1);                        // 大堆每次 +50%
            int newCap = ArraysSupport.newLength(oldCap, 1, growth);
            if (queue == array)
                newArray = new Object[newCap];
        } finally {
            allocationSpinLock = 0;
        }
    }
    if (newArray == null)           // 另一个线程正在扩容：yield 让出，下次循环重试
        Thread.yield();
    lock.lock();
    if (newArray != null && queue == array) {
        queue = newArray;
        System.arraycopy(array, 0, newArray, 0, oldCap);
    }
}
```

三个细节值得记住：扩容**增量是 `oldCap >> 1`（约 1.5 倍）而不是 2 倍**（堆数组大，省内存优先）；`allocationSpinLock` 只保护「谁来分配」，不保护拷贝；`queue == array` 的二次检查是防止期间已被别的线程扩过。

## LinkedTransferQueue

`LinkedTransferQueue` 是 `ConcurrentLinkedQueue` 的「可移交」超集：既支持普通入队（元素可以堆在队列里等着），也支持生产者**越过队列直接把元素交给一个正在等待的消费者**。

```java
public class LinkedTransferQueue<E> extends AbstractQueue<E>
    implements TransferQueue<E>, java.io.Serializable {
```

它实现的 `TransferQueue` 在 `BlockingQueue` 之上多了五个方法：

| 方法                                  | 语义                                          |
| :---------------------------------- | :------------------------------------------ |
| `tryTransfer(e)`                    | 有消费者在等就立即交给它并返回 `true`，否则**不入队**直接返回 `false` |
| `transfer(e)`                       | 有消费者就交，没有就**阻塞到被取走**                         |
| `tryTransfer(e, timeout, unit)`     | 同上但限时，超时返回 `false`                           |
| `hasWaitingConsumer()`              | 是否有消费者正在等待                                  |
| `getWaitingConsumerCount()`          | 正在等待的消费者数量（估算值，用于 metrics 而不是控制流）            |

### Dual Queue with Slack

实现基于 Scherer & Scott 的 **Dual Queue**：链表里的节点既可以代表「数据」（data）也可以代表「请求」（request）。生产者入队时若撞上请求节点就直接**匹配并摘掉**它，反之消费者撞上数据节点同理。这样一条链表同时表达了两个方向的等待者。

所有操作都汇到一个 `xfer`：

```java
/**
 * @param e the item or null for take
 * @param ns timeout or negative if async, 0 if immediate,
 *        Long.MAX_VALUE if untimed
 * @return an item if matched, else e
 */
final Object xfer(Object e, long ns) {
    boolean haveData = (e != null);
    Object m;                           // the match or e if none
    DualNode s = null, p;               // enqueued node and its predecessor
    restart: for (DualNode prevp = null;;) {
        DualNode h, t, q;
        if ((h = head) == null &&       // initialize unless immediate
            (ns == 0L ||
             (h = cmpExHead(null, s = new DualNode(e, haveData))) == null)) {
            p = null;
            break;
        }
        p = (t = tail) != null && t.isData == haveData && t != prevp ? t : h;
        prevp = p;
        do {
            m = p.item;
            q = p.next;
            if (p.isData != haveData && haveData != (m != null) &&
                p.cmpExItem(m, e) == m) {
                Thread w = p.waiter;    // 匹配到互补节点：直接换数据并 unpark
                if (p != h && h == cmpExHead(h, (q == null) ? p : q))
                    h.next = h;         // advance head; self-link old
                LockSupport.unpark(w);
                return m;
            } else if (q == null) {
                if (ns == 0L)           // immediate：不匹配就放弃
                    ...
```

`ns` 这一个参数把四种语义编码在了一起：

| `ns` 取值               | 语义           | 对应方法                                          |
| :-------------------- | :----------- | :-------------------------------------------- |
| `-1L`                 | ASYNC，不匹配就入队 | `add` / `offer` / `put`                       |
| `0L`                  | NOW，不匹配就放弃   | `tryTransfer` / `poll()`（取模式下 `xfer(null,0)`） |
| `> 0`                 | TIMED，限时等待   | `tryTransfer(e, t, u)` / `poll(t, u)`         |
| `Long.MAX_VALUE`      | SYNC，无限等待    | `transfer` / `take()`                         |

「Slack」指的是**允许 `head` 落后于真正的队首若干步**（`MAX_HOPS = 8`）：匹配成功的线程并不急着更新 `head`，只有累积到一定距离才 CAS 推进。这是典型的「用少量遍历成本换 CAS 竞争」的权衡——`ConcurrentLinkedQueue` 里也有同名机制。

### Versus SynchronousQueue

两者都基于 dual queue，但容量语义相反：

| 维度       | `SynchronousQueue`   | `LinkedTransferQueue` |
| :------- | :------------------- | :-------------------- |
| 容量       | 0，元素从不落地              | 无界，可以堆积               |
| `offer`  | 无消费者时返回 `false`      | 直接入队返回 `true`         |
| 是否支持移交   | 是（`put` 必须配对）        | 是（额外提供 `tryTransfer`） |
| `size()` | 恒为 0                 | 真实元素数                 |
| 元素是否可达   | 否，`peek()` 恒 `null`  | 是                     |

选哪个的判断很简单：**要「背压」用 `SynchronousQueue`（生产者必须等到有人接），要「削峰 + 可选移交」用 `LinkedTransferQueue`**。

## Thread-Safe Queues


| Queue                 | Boundary           | Lock     | Struct     |
| --------------------- | ------------------ |----------| ---------- |
| ArrayBlockingQueue    | bounded            | 1 lock   | arrayList  |
| LinkedBlockingQueue   | optionally-bounded | 2 locks  | linkedList |
| ConcurrentLinkedQueue | unbounded          | Non-lock | linkedList |
| LinkedTransferQueue   | unbounded          | Non-lock | linkedList |
| SynchronousQueue      | zero capacity      | Non-lock | dual stack / dual queue |
| PriorityBlockingQueue | unbounded          | lock     | heap       |
| DelayQueue            | unbounded          | lock     | heap       |


队列的底层一般分成三种：数组、链表和堆。其中，堆一般情况下是为了实现带有优先级特性的队列，暂且不考虑。

我们就从数组和链表两种数据结构来看，基于数组线程安全的队列，比较典型的是ArrayBlockingQueue，它主要通过加锁的方式来保证线程安全；基于链表的线程安全队列分成LinkedBlockingQueue和ConcurrentLinkedQueue两大类，前者也通过锁的方式来实现线程安全，而后者以及上面表格中的LinkedTransferQueue都是通过原子变量compare and swap（以下简称“CAS”）这种不加锁的方式来实现的。

通过不加锁的方式实现的队列都是无界的（无法保证队列的长度在确定的范围内）；而加锁的方式，可以实现有界队列
在稳定性要求特别高的系统中，为了防止生产者速度过快，导致内存溢出，只能选择有界队列；同时，为了减少Java的垃圾回收对系统性能的影响，会尽量选择array/heap格式的数据结构。这样筛选下来，符合条件的队列就只有ArrayBlockingQueue。



## Links

- [Collection](/docs/CS/Java/JDK/Collection/Collection.md)
- [Set](/docs/CS/Java/JDK/Collection/Set.md)
- [Disruptor](/docs/CS/Java/Disruptor.md)

## References

1. [BlockingQueue (Java SE 25 & JDK 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/concurrent/BlockingQueue.html)
2. [TransferQueue (Java SE 25 & JDK 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/concurrent/TransferQueue.html)
3. [DelayQueue (Java SE 25 & JDK 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/concurrent/DelayQueue.html)
