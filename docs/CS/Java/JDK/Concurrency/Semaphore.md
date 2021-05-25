# Semaphore



_A counting semaphore. Conceptually, a semaphore maintains a set of permits. Each acquire blocks if necessary until a permit is available, and then takes it. Each release adds a permit, potentially releasing a blocking acquirer. However, no actual permit objects are used; the Semaphore just keeps a count of the number available and acts accordingly._
**Semaphores are often used to restrict the number of threads than can access some (physical or logical) resource.** 

Before obtaining an item each thread must acquire a permit from the semaphore, guaranteeing that an item is available for use. When the thread has finished with the item it is returned back to the pool and a permit is returned to the semaphore, allowing another thread to acquire that item. Note that no synchronization lock is held when acquire is called as that would prevent an item from being returned to the pool. **The semaphore encapsulates the synchronization needed to restrict access to the pool, separately from any synchronization needed to maintain the consistency of the pool itself**.
A semaphore initialized to one, and which is used such that it only has at most one permit available, can serve as a mutual exclusion lock. This is more commonly known as a binary semaphore, because it only has two states: one permit available, or zero permits available. When used in this way, the binary semaphore has the property (unlike many `java.util.concurrent.locks.Lock` implementations), that **the "lock" can be released by a thread other than the owner (as semaphores have no notion of ownership)**. This can be useful in some specialized contexts, such as deadlock recovery.

The constructor for this class optionally accepts a fairness parameter. When set false, this class makes no guarantees about the order in which threads acquire permits. In particular, barging is permitted, that is, a thread invoking acquire can be allocated a permit ahead of a thread that has been waiting - logically the new thread places itself at the head of the queue of waiting threads. When fairness is set true, the semaphore guarantees that threads invoking any of the acquire methods are selected to obtain permits in the order in which their invocation of those methods was processed (first-in-first-out; FIFO). Note that FIFO ordering necessarily applies to specific internal points of execution within these methods. So, it is possible for one thread to invoke acquire before another, but reach the ordering point after the other, and similarly upon return from the method. Also note that the untimed tryAcquire methods do not honor the fairness setting, but will take any permits that are available.
Generally, semaphores used to control resource access should be initialized as fair, to ensure that no thread is starved out from accessing a resource. When using semaphores for other kinds of synchronization control, the throughput advantages of non-fair ordering often outweigh fairness considerations.
This class also provides convenience methods to acquire and release multiple permits at a time. Beware of the increased risk of indefinite postponement when these methods are used without fairness set true.
**_Memory consistency effects_**: *Actions in a thread prior to calling release() **happen-before** actions following a successful acquire() in another thread.*



```java
public class Semaphore implements java.io.Serializable {
    /** All mechanics via AbstractQueuedSynchronizer subclass */
    private final Sync sync;
}
```



### Sync

```java
/**
 * Synchronization implementation for semaphore.  Uses AQS state
 * to represent permits. Subclassed into fair and nonfair
 * versions.
 */
abstract static class Sync extends AbstractQueuedSynchronizer {
    private static final long serialVersionUID = 1192457210091910933L;

    Sync(int permits) {
        setState(permits);
    }

    final int getPermits() {
        return getState();
    }
		// invoke by tryAcquire
    final int nonfairTryAcquireShared(int acquires) {
        for (;;) {
            int available = getState();
            int remaining = available - acquires;
            if (remaining < 0 ||
                compareAndSetState(available, remaining))
                return remaining;
        }
    }

    protected final boolean tryReleaseShared(int releases) {
        for (;;) {
            int current = getState();
            int next = current + releases;
            if (next < current) // overflow
                throw new Error("Maximum permit count exceeded");
            if (compareAndSetState(current, next))
                return true;
        }
    }

    final void reducePermits(int reductions) {
        for (;;) {
            int current = getState();
            int next = current - reductions;
            if (next > current) // underflow
                throw new Error("Permit count underflow");
            if (compareAndSetState(current, next))
                return;
        }
    }

    final int drainPermits() {
        for (;;) {
            int current = getState();
            if (current == 0 || compareAndSetState(current, 0))
                return current;
        }
    }
}
```





```java
public void acquire() throws InterruptedException {
    sync.acquireSharedInterruptibly(1);
}
```



```java
final int acquire(Node node, int arg, boolean shared,
                  boolean interruptible, boolean timed, long time) {
    Thread current = Thread.currentThread();
    byte spins = 0, postSpins = 0;   // retries upon unpark of first thread
    boolean interrupted = false, first = false;
    Node pred = null;                // predecessor of node when enqueued

    /*
     * Repeatedly:
     *  Check if node now first
     *    if so, ensure head stable, else ensure valid predecessor
     *  if node is first or not yet enqueued, try acquiring
     *  else if node not yet created, create it
     *  else if not yet enqueued, try once to enqueue
     *  else if woken from park, retry (up to postSpins times)
     *  else if WAITING status not set, set and retry
     *  else park and clear WAITING status, and check cancellation
     */

    for (;;) {
        if (!first && (pred = (node == null) ? null : node.prev) != null &&
            !(first = (head == pred))) {
            if (pred.status < 0) {
                cleanQueue();           // predecessor cancelled
                continue;
            } else if (pred.prev == null) {
                Thread.onSpinWait();    // ensure serialization
                continue;
            }
        }
        if (first || pred == null) {
            boolean acquired;
            try {
                if (shared)
                    acquired = (tryAcquireShared(arg) >= 0);
                else
                    acquired = tryAcquire(arg);
            } catch (Throwable ex) {
                cancelAcquire(node, interrupted, false);
                throw ex;
            }
            if (acquired) {
                if (first) {
                    node.prev = null;
                    head = node;
                    pred.next = null;
                    node.waiter = null;
                    if (shared)
                        signalNextIfShared(node);
                    if (interrupted)
                        current.interrupt();
                }
                return 1;
            }
        }
        if (node == null) {                 // allocate; retry before enqueue
            if (shared)
                node = new SharedNode();
            else
                node = new ExclusiveNode();
        } else if (pred == null) {          // try to enqueue
            node.waiter = current;
            Node t = tail;
            node.setPrevRelaxed(t);         // avoid unnecessary fence
            if (t == null)
                tryInitializeHead();
            else if (!casTail(t, node))
                node.setPrevRelaxed(null);  // back out
            else
                t.next = node;
        } else if (first && spins != 0) {
            --spins;                        // reduce unfairness on rewaits
            Thread.onSpinWait();
        } else if (node.status == 0) {
            node.status = WAITING;          // enable signal and recheck
        } else {
            long nanos;
            spins = postSpins = (byte)((postSpins << 1) | 1);
            if (!timed)
                LockSupport.park(this);
            else if ((nanos = time - System.nanoTime()) > 0L)
                LockSupport.parkNanos(this, nanos);
            else
                break;
            node.clearStatus();
            if ((interrupted |= Thread.interrupted()) && interruptible)
                break;
        }
    }
    return cancelAcquire(node, interrupted, interruptible);
}
```

## Example

_For example, here is a class that uses a semaphore to control access to a pool of items:_

```java
  
 class Pool {
   private static final int MAX_AVAILABLE = 100;
   private final Semaphore available = new Semaphore(MAX_AVAILABLE, true);

   public Object getItem() throws InterruptedException {
     available.acquire();
     return getNextAvailableItem();
   }

   public void putItem(Object x) {
     if (markAsUnused(x))
       available.release();
   }

   // Not a particularly efficient data structure; just for demo

   protected Object[] items = ... whatever kinds of items being managed
   protected boolean[] used = new boolean[MAX_AVAILABLE];

   protected synchronized Object getNextAvailableItem() {
     for (int i = 0; i < MAX_AVAILABLE; ++i) {
       if (!used[i]) {
         used[i] = true;
         return items[i];
       }
     }
     return null; // not reached
   }

   protected synchronized boolean markAsUnused(Object item) {
     for (int i = 0; i < MAX_AVAILABLE; ++i) {
       if (item == items[i]) {
         if (used[i]) {
           used[i] = false;
           return true;
         } else
           return false;
       }
     }
     return false;
   }
 }
```

