# CountDownLatch



A synchronization aid that allows one or more threads to wait until a set of operations being performed in other threads completes.
A CountDownLatch is initialized with a given count. The await methods block until the current count reaches zero due to invocations of the countDown method, after which all waiting threads are released and any subsequent invocations of await return immediately. This is a one-shot phenomenon -- the count cannot be reset. If you need a version that resets the count, consider using a **CyclicBarrier**.
A CountDownLatch is a versatile synchronization tool and can be used for a number of purposes. A CountDownLatch initialized with a count of one serves as a simple on/off latch, or gate: all threads invoking await wait at the gate until it is opened by a thread invoking countDown. A CountDownLatch initialized to N can be used to make one thread wait until N threads have completed some action, or some action has been completed N times.
A useful property of a CountDownLatch is that it doesn't require that threads calling countDown wait for the count to reach zero before proceeding, it simply prevents any thread from proceeding past an await until all threads could pass.

**Memory consistency effects**: *Until the count reaches zero, actions in a thread prior to calling countDown() happen-before actions following a successful return from a corresponding await() in another thread.*

Sync

```java
    /**
     * Synchronization control For CountDownLatch.
     * Uses AQS state to represent count.
     */
    private static final class Sync extends AbstractQueuedSynchronizer {
        private static final long serialVersionUID = 4982264981922014374L;

        Sync(int count) {
            setState(count);
        }

        int getCount() {
            return getState();
        }

        protected int tryAcquireShared(int acquires) {
            return (getState() == 0) ? 1 : -1;
        }

        protected boolean tryReleaseShared(int releases) {
            // Decrement count; signal when transition to zero
            for (;;) {
                int c = getState();
                if (c == 0)
                    return false;
                int nextc = c-1;
                if (compareAndSetState(c, nextc))
                    return nextc == 0;
            }
        }
    }
```





await

```java
/**
 * Causes the current thread to wait until the latch has counted down to
 * zero, unless the thread is {@linkplain Thread#interrupt interrupted},
 * or the specified waiting time elapses.
 *
 * <p>If the current count is zero then this method returns immediately
 * with the value {@code true}.
 *
 * <p>If the current count is greater than zero then the current
 * thread becomes disabled for thread scheduling purposes and lies
 * dormant until one of three things happen:
 * <ul>
 * <li>The count reaches zero due to invocations of the
 * {@link #countDown} method; or
 * <li>Some other thread {@linkplain Thread#interrupt interrupts}
 * the current thread; or
 * <li>The specified waiting time elapses.
 * </ul>
 *
 * <p>If the count reaches zero then the method returns with the
 * value {@code true}.
 *
 * <p>If the current thread:
 * <ul>
 * <li>has its interrupted status set on entry to this method; or
 * <li>is {@linkplain Thread#interrupt interrupted} while waiting,
 * </ul>
 * then {@link InterruptedException} is thrown and the current thread's
 * interrupted status is cleared.
 *
 * <p>If the specified waiting time elapses then the value {@code false}
 * is returned.  If the time is less than or equal to zero, the method
 * will not wait at all.
 *
 * @param timeout the maximum time to wait
 * @param unit the time unit of the {@code timeout} argument
 * @return {@code true} if the count reached zero and {@code false}
 *         if the waiting time elapsed before the count reached zero
 * @throws InterruptedException if the current thread is interrupted
 *         while waiting
 */
public boolean await(long timeout, TimeUnit unit)
    throws InterruptedException {
    return sync.tryAcquireSharedNanos(1, unit.toNanos(timeout));
}
```