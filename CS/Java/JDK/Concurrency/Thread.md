# Thread



## Create

*How to create a Thread instance?*

***Just new a Thread instance.***

### Thread

```JAVA
/**
 * Allocates a new Thread object.
 */
public Thread() {
    init(null, null, "Thread-" + nextThreadNum(), 0);
}

/**
 * Allocates a new Thread object with Runnable taarget.
 */
public Thread(Runnable target) {
    init(null, target, "Thread-" + nextThreadNum(), 0);
}
```



### Runnable

*The Runnable interface should be implemented by any class whose instances are intended to be **executed by a thread**. The class must define a method of no arguments **called run**.*
*This interface is designed to provide a common protocol for objects that wish to execute code while they are active. **Runnable is implemented by class Thread.***

*A class that implements Runnable can run without subclassing Thread by instantiating a Thread instance and passing itself in as the target.his is important because classes should not be subclassed unless the programmer intends on modifying or enhancing the fundamental behavior of the class.*

```java
@FunctionalInterface
public interface Runnable {

    public abstract void run();
}
```



### Callable

*A task that **returns a result and may throw an exception**. Implementors define a single method with no arguments **called call**.*

**Runnable does not return a result and cannot throw a checked exception.**

**The Callable interface is similar to Runnable**, in that both are designed for classes whose instances are potentially executed by another thread. 



The **Executors** class contains utility methods to convert from other common forms to Callable classes.

```java
@FunctionalInterface
public interface Callable<V> {
    /**
     * Computes a result, or throws an exception if unable to do so.
     */
    V call() throws Exception;
}
```



## Lifetime

![Thread-Lifetime](https://github.com/Robinpig/Note/raw/master/images/JDK/Thread-Lifetime.png)

### Status

A thread can be in one of the following states:

| Status       | Description                                                  |
| ------------ | ------------------------------------------------------------ |
| NEW          | A thread that has not yet started is in this state.          |
| RUNNABLE     | A thread executing in the Java virtual machine is in this state. |
| BLOCKED      | A thread that is blocked waiting for a monitor lock is in this state. |
| WATING       | A thread that is waiting indefinitely for another thread to perform a particular action is in this state. |
| TIME_WAITING | A thread that is waiting for another thread to perform an action for up to a specified waiting time is in this state. |
| TERMINATED   | A thread that has exited is in this state.                   |



## Order

### join

Waits at most millis milliseconds for this thread to die. A timeout of 0 means to wait forever.
This implementation uses **a loop of this.wait** calls conditioned on this.isAlive. As a thread terminates the this.notifyAll method is invoked. It is recommended that applications not use wait, notify, or notifyAll on Thread instances.

```java
public final synchronized void join(long millis)
throws InterruptedException {
    long base = System.currentTimeMillis();
    long now = 0;

    if (millis < 0) {
        throw new IllegalArgumentException("timeout value is negative");
    }

    if (millis == 0) {
        while (isAlive()) {
            wait(0);
        }
    } else {
        while (isAlive()) {
            long delay = millis - now;
            if (delay <= 0) {
                break;
            }
            wait(delay);
            now = System.currentTimeMillis() - base;
        }
    }
}
```



## Interrupt

```java
/**
 * Interrupts this thread.
 *
 * <p> Unless the current thread is interrupting itself, which is
 * always permitted, the {@link #checkAccess() checkAccess} method
 * of this thread is invoked, which may cause a {@link
 * SecurityException} to be thrown.
 *
 * <p> If this thread is blocked in an invocation of the {@link
 * Object#wait() wait()}, {@link Object#wait(long) wait(long)}, or {@link
 * Object#wait(long, int) wait(long, int)} methods of the {@link Object}
 * class, or of the {@link #join()}, {@link #join(long)}, {@link
 * #join(long, int)}, {@link #sleep(long)}, or {@link #sleep(long, int)},
 * methods of this class, then its interrupt status will be cleared and it
 * will receive an {@link InterruptedException}.
 *
 * <p> If this thread is blocked in an I/O operation upon an {@link
 * java.nio.channels.InterruptibleChannel InterruptibleChannel}
 * then the channel will be closed, the thread's interrupt
 * status will be set, and the thread will receive a {@link
 * java.nio.channels.ClosedByInterruptException}.
 *
 * <p> If this thread is blocked in a {@link java.nio.channels.Selector}
 * then the thread's interrupt status will be set and it will return
 * immediately from the selection operation, possibly with a non-zero
 * value, just as if the selector's {@link
 * java.nio.channels.Selector#wakeup wakeup} method were invoked.
 *
 * <p> If none of the previous conditions hold then this thread's interrupt
 * status will be set. </p>
 *
 * <p> Interrupting a thread that is not alive need not have any effect.
 *
 * @throws  SecurityException
 *          if the current thread cannot modify this thread
 *
 * @revised 6.0
 * @spec JSR-51
 */
public void interrupt() {
    if (this != Thread.currentThread())
        checkAccess();

    synchronized (blockerLock) {
        Interruptible b = blocker;
        if (b != null) {
            interrupt0();           // Just to set the interrupt flag
            b.interrupt(this);
            return;
        }
    }
    interrupt0();
}

/**
 * Tests whether the current thread has been interrupted.  The
 * <i>interrupted status</i> of the thread is cleared by this method.  In
 * other words, if this method were to be called twice in succession, the
 * second call would return false (unless the current thread were
 * interrupted again, after the first call had cleared its interrupted
 * status and before the second call had examined it).
 *
 * <p>A thread interruption ignored because a thread was not alive
 * at the time of the interrupt will be reflected by this method
 * returning false.
 *
 * @return  <code>true</code> if the current thread has been interrupted;
 *          <code>false</code> otherwise.
 * @see #isInterrupted()
 * @revised 6.0
 */
public static boolean interrupted() {
    return currentThread().isInterrupted(true);
}

/**
 * Tests whether this thread has been interrupted.  The <i>interrupted
 * status</i> of the thread is unaffected by this method.
 *
 * <p>A thread interruption ignored because a thread was not alive
 * at the time of the interrupt will be reflected by this method
 * returning false.
 *
 * @return  <code>true</code> if this thread has been interrupted;
 *          <code>false</code> otherwise.
 * @see     #interrupted()
 * @revised 6.0
 */
public boolean isInterrupted() {
    return isInterrupted(false);
}

/**
 * Tests if some Thread has been interrupted.  The interrupted state
 * is reset or not based on the value of ClearInterrupted that is
 * passed.
 */
private native boolean isInterrupted(boolean ClearInterrupted);
```





## wait and notify

Provider-consumer 

Wait-notify只是一个condition queue 仅使用于单生产/消费模型

```java
/**
 * Wakes up a single thread that is waiting on this object's
 * monitor. If any threads are waiting on this object, one of them
 * is chosen to be awakened. The choice is arbitrary and occurs at
 * the discretion of the implementation. A thread waits on an object's
 * monitor by calling one of the {@code wait} methods.
 * <p>
 * The awakened thread will not be able to proceed until the current
 * thread relinquishes the lock on this object. The awakened thread will
 * compete in the usual manner with any other threads that might be
 * actively competing to synchronize on this object; for example, the
 * awakened thread enjoys no reliable privilege or disadvantage in being
 * the next thread to lock this object.
 * <p>
 * This method should only be called by a thread that is the owner
 * of this object's monitor. A thread becomes the owner of the
 * object's monitor in one of three ways:
 * <ul>
 * <li>By executing a synchronized instance method of that object.
 * <li>By executing the body of a {@code synchronized} statement
 *     that synchronizes on the object.
 * <li>For objects of type {@code Class,} by executing a
 *     synchronized static method of that class.
 * </ul>
 * <p>
 * Only one thread at a time can own an object's monitor.
 */
public final native void notify();

/**
 * Wakes up all threads that are waiting on this object's monitor. A
 * thread waits on an object's monitor by calling one of the
 * {@code wait} methods.
 * <p>
 * The awakened threads will not be able to proceed until the current
 * thread relinquishes the lock on this object. The awakened threads
 * will compete in the usual manner with any other threads that might
 * be actively competing to synchronize on this object; for example,
 * the awakened threads enjoy no reliable privilege or disadvantage in
 * being the next thread to lock this object.
 */
public final native void notifyAll();

/**
 * Causes the current thread to wait until either another thread invokes the
 * {@link java.lang.Object#notify()} method or the
 * {@link java.lang.Object#notifyAll()} method for this object, or a
 * specified amount of time has elapsed.
 * <p>
 * The current thread must own this object's monitor.
 * <p>
 * This method causes the current thread (call it <var>T</var>) to
 * place itself in the wait set for this object and then to relinquish
 * any and all synchronization claims on this object. Thread <var>T</var>
 * becomes disabled for thread scheduling purposes and lies dormant
 * until one of four things happens:
 * <ul>
 * <li>Some other thread invokes the {@code notify} method for this
 * object and thread <var>T</var> happens to be arbitrarily chosen as
 * the thread to be awakened.
 * <li>Some other thread invokes the {@code notifyAll} method for this
 * object.
 * <li>Some other thread {@linkplain Thread#interrupt() interrupts}
 * thread <var>T</var>.
 * <li>The specified amount of real time has elapsed, more or less.  If
 * {@code timeout} is zero, however, then real time is not taken into
 * consideration and the thread simply waits until notified.
 * </ul>
 * The thread <var>T</var> is then removed from the wait set for this
 * object and re-enabled for thread scheduling. It then competes in the
 * usual manner with other threads for the right to synchronize on the
 * object; once it has gained control of the object, all its
 * synchronization claims on the object are restored to the status quo
 * ante - that is, to the situation as of the time that the {@code wait}
 * method was invoked. Thread <var>T</var> then returns from the
 * invocation of the {@code wait} method. Thus, on return from the
 * {@code wait} method, the synchronization state of the object and of
 * thread {@code T} is exactly as it was when the {@code wait} method
 * was invoked.
 * <p>
 * A thread can also wake up without being notified, interrupted, or
 * timing out, a so-called <i>spurious wakeup</i>.  While this will rarely
 * occur in practice, applications must guard against it by testing for
 * the condition that should have caused the thread to be awakened, and
 * continuing to wait if the condition is not satisfied.  In other words,
 * waits should always occur in loops, like this one:
 * <pre>
 *     synchronized (obj) {
 *         while (&lt;condition does not hold&gt;)
 *             obj.wait(timeout);
 *         ... // Perform action appropriate to condition
 *     }
 * </pre>
 * (For more information on this topic, see Section 3.2.3 in Doug Lea's
 * "Concurrent Programming in Java (Second Edition)" (Addison-Wesley,
 * 2000), or Item 50 in Joshua Bloch's "Effective Java Programming
 * Language Guide" (Addison-Wesley, 2001).
 *
 * <p>If the current thread is {@linkplain java.lang.Thread#interrupt()
 * interrupted} by any thread before or while it is waiting, then an
 * {@code InterruptedException} is thrown.  This exception is not
 * thrown until the lock status of this object has been restored as
 * described above.
 *
 * <p>
 * Note that the {@code wait} method, as it places the current thread
 * into the wait set for this object, unlocks only this object; any
 * other objects on which the current thread may be synchronized remain
 * locked while the thread waits.
 */
public final native void wait(long timeout) throws InterruptedException;

/**
 * Causes the current thread to wait until another thread invokes the
 * {@link java.lang.Object#notify()} method or the
 * {@link java.lang.Object#notifyAll()} method for this object, or
 * some other thread interrupts the current thread, or a certain
 * amount of real time has elapsed.
 * <p>
 * This method is similar to the {@code wait} method of one
 * argument, but it allows finer control over the amount of time to
 * wait for a notification before giving up. The amount of real time,
 * measured in nanoseconds, is given by:
 * <blockquote>
 * <pre>
 * 1000000*timeout+nanos</pre></blockquote>
 * <p>
 * In all other respects, this method does the same thing as the
 * method {@link #wait(long)} of one argument. In particular,
 * {@code wait(0, 0)} means the same thing as {@code wait(0)}.
 * <p>
 * The current thread must own this object's monitor. The thread
 * releases ownership of this monitor and waits until either of the
 * following two conditions has occurred:
 * <ul>
 * <li>Another thread notifies threads waiting on this object's monitor
 *     to wake up either through a call to the {@code notify} method
 *     or the {@code notifyAll} method.
 * <li>The timeout period, specified by {@code timeout}
 *     milliseconds plus {@code nanos} nanoseconds arguments, has
 *     elapsed.
 * </ul>
 * <p>
 * The thread then waits until it can re-obtain ownership of the
 * monitor and resumes execution.
 * <p>
 * As in the one argument version, interrupts and spurious wakeups are
 * possible, and this method should always be used in a loop:
 * <pre>
 *     synchronized (obj) {
 *         while (&lt;condition does not hold&gt;)
 *             obj.wait(timeout, nanos);
 *         ... // Perform action appropriate to condition
 *     }
 */
public final void wait(long timeout, int nanos) throws InterruptedException {
    if (timeout < 0) {
        throw new IllegalArgumentException("timeout value is negative");
    }

    if (nanos < 0 || nanos > 999999) {
        throw new IllegalArgumentException(
                            "nanosecond timeout value out of range");
    }

    if (nanos > 0) {
        timeout++;
    }

    wait(timeout);
}

/**
 * Causes the current thread to wait until another thread invokes the
 * {@link java.lang.Object#notify()} method or the
 * {@link java.lang.Object#notifyAll()} method for this object.
 * In other words, this method behaves exactly as if it simply
 * performs the call {@code wait(0)}.
 * <p>
 * The current thread must own this object's monitor. The thread
 * releases ownership of this monitor and waits until another thread
 * notifies threads waiting on this object's monitor to wake up
 * either through a call to the {@code notify} method or the
 * {@code notifyAll} method. The thread then waits until it can
 * re-obtain ownership of the monitor and resumes execution.
 * <p>
 * As in the one argument version, interrupts and spurious wakeups are
 * possible, and this method should always be used in a loop:
 * <pre>
 *     synchronized (obj) {
 *         while (&lt;condition does not hold&gt;)
 *             obj.wait();
 *         ... // Perform action appropriate to condition
 *     }
 * </pre>
 * This method should only be called by a thread that is the owner
 * of this object's monitor. See the {@code notify} method for a
 * description of the ways in which a thread can become the owner of
 * a monitor.
 *
 * @throws  IllegalMonitorStateException  if the current thread is not
 *               the owner of the object's monitor.
 * @throws  InterruptedException if any thread interrupted the
 *             current thread before or while the current thread
 *             was waiting for a notification.  The <i>interrupted
 *             status</i> of the current thread is cleared when
 *             this exception is thrown.
 * @see        java.lang.Object#notify()
 * @see        java.lang.Object#notifyAll()
 */
public final void wait() throws InterruptedException {
    wait(0);
}
```



### Sleep

#### yield 跟 sleep 

1. yield 跟 sleep 都能暂停当前线程，都不会释放锁资源，sleep 可以指定具体休眠的时间，而 yield 则依赖 CPU 的时间片划分
2. sleep方法给其他线程运行机会时不考虑线程的优先级，因此会给低优先级的线程以运行的机会。yield方法只会给相同优先级或更高优先级的线程以运行的机会
3. 调用 sleep 方法使线程进入等待状态，等待休眠时间达到，而调用我们的 yield方法，线程会进入就绪状态，也就是sleep需要等待设置的时间后才会进行就绪状态，而yield会立即进入就绪状态
4. sleep方法声明会抛出 InterruptedException，而 yield 方法没有声明任何异常
5. yield 不能被中断，而 sleep 则可以接受中断。
6. sleep方法比yield方法具有更好的移植性(跟操作系统CPU调度相关)

#### wait 跟 sleep 

1. wait来自Object，sleep 来自 Thread
2. wait 释放锁，sleep 不释放
3. wait 必须在同步代码块中，sleep 可以任意使用
4. wait 不需要捕获异常，sleep 需捕获异常





## Lock

### Dead Lock



产生死锁必须满足四个条件：

1. 互斥条件：该资源任意⼀个时刻只由⼀个线程占⽤。
2. 请求与保持条件：⼀个进程因请求资源⽽阻塞时，对已获得的资源保持不放。
3. 不剥夺条件:线程已获得的资源在末使⽤完之前不能被其他线程强⾏剥夺，只有⾃⼰使⽤完毕后才释放资源。
4. 循环等待条件:若⼲进程之间形成⼀种头尾相接的循环等待资源关系。






### Live Lock



## JMM

