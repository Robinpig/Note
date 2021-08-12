

## Lock

*Lock implementations provide more extensive locking operations than can be obtained using synchronized methods and statements. They allow more flexible structuring, may have quite different properties, and may support multiple associated Condition objects.*

*A lock is a tool for controlling access to a shared resource by multiple threads. Commonly, a lock provides exclusive access to a shared resource: only one thread at a time can acquire the lock and all access to the shared resource requires that the lock be acquired first. However, some locks may allow concurrent access to a shared resource, such as the read lock of a ReadWriteLock.*

*The use of synchronized methods or statements provides access to the implicit monitor lock associated with every object, but forces all lock acquisition and release to occur in a block-structured way: when multiple locks are acquired they must be released in the opposite order, and all locks must be released in the same lexical scope in which they were acquired.*

*While the scoping mechanism for synchronized methods and statements makes it much easier to program with monitor locks, and helps avoid many common programming errors involving locks, there are occasions where you need to work with locks in a more flexible way. For example, some algorithms for traversing concurrently accessed data structures require the use of "hand-over-hand" or "chain locking": you acquire the lock of node A, then node B, then release A and acquire C, then release B and acquire D and so on. Implementations of the Lock interface enable the use of such techniques by allowing a lock to be acquired and released in different scopes, and allowing multiple locks to be acquired and released in any order.*



```java
public interface Lock {

    //Acquires the lock.
    void lock();

    void lockInterruptibly() throws InterruptedException;

    boolean tryLock();

    boolean tryLock(long time, TimeUnit unit) throws InterruptedException;

    //Releases the lock.
    void unlock();

    Condition newCondition();
}
```

TicketLock

CLHLock

MCSLock


## Condition

### Condition vs Object#wait()/notify()



|               | Object                | Condition                          |
| ------------- | --------------------- | ---------------------------------- |
| Method        | wait/notify           | await/signal                       |
| Depend        | synchronized          | AQS                                |
| Implement     | C++                   | Java                               |
| Interruptibility | interruptibility |                                    |
| wait time     |                       | could set a future time            |
| Num           |                       | a Lock can use multiple Conditions |
| Sleep         | Unsupported           | Supported                          |
|               |                       |                                    |





## LockSupport

*LockSupport call [Unsafe](/docs/CS/Java/JDK/Basic/unsafe.md).*



### parker

Disables the current thread for thread scheduling purposes unless the permit is available.

If the permit is available then it is consumed and the call returns immediately; otherwise the current thread becomes disabled for thread scheduling purposes and lies dormant until one of three things happens:
- Some other thread invokes unpark with the current thread as the target; or
- Some other thread interrupts the current thread; or
- The call spuriously (that is, for no reason) returns.

This method does not report which of these caused the method to return. Callers should re-check the conditions which caused the thread to park in the first place. Callers may also determine, for example, the interrupt status of the thread upon return.

```java
 public static void park(Object blocker) {
        Thread t = Thread.currentThread();
        setBlocker(t, blocker);
        UNSAFE.park(false, 0L);
        setBlocker(t, null);
    }

private static void setBlocker(Thread t, Object arg) {
    // Even though volatile, hotspot doesn't need a write barrier here.
    UNSAFE.putObject(t, parkBlockerOffset, arg);
    }
```
**sample**:

```java
while (!canProceed()) { ... LockSupport.park(this); }
```

Makes available the permit for the given thread, if it was not already available. 
If the thread was blocked on park then it will unblock. 
Otherwise, its next call to park is guaranteed not to block. This operation is not guaranteed to have any effect at all if the given thread has not been started.
```java
public static void unpark(Thread thread) {
  if (thread != null)
      UNSAFE.unpark(thread);
}
```

### Sample


```java
class FIFOMutex {
    private final AtomicBoolean locked = new AtomicBoolean(false);
    private final Queue<Thread> waiters
      = new ConcurrentLinkedQueue<Thread>();
 
    public void lock() {
      boolean wasInterrupted = false;
      Thread current = Thread.currentThread();
      waiters.add(current);
 
      // Block while not first in queue or cannot acquire lock
      while (waiters.peek() != current ||
             !locked.compareAndSet(false, true)) {
        LockSupport.park(this);
        if (Thread.interrupted()) // ignore interrupts while waiting
          wasInterrupted = true;
      }

      waiters.remove();
      if (wasInterrupted)          // reassert interrupt status on exit
        current.interrupt();
    }
 
    public void unlock() {
      locked.set(false);
      LockSupport.unpark(waiters.peek());
    }
  }
```