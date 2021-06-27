# Lock





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
| Interruptibly | must be interruptibly |                                    |
| wait time     |                       | could set a future time            |
| Num           |                       | a Lock can use multiple Conditions |





## LockSupport

LockSupport 和 CAS 是Java并发包中很多并发工具控制机制的基础，它们底层其实都是依赖Unsafe实现。

LockSupport是用来创建锁和其他同步类的基本**线程阻塞**原语。LockSupport 提供park()和unpark()方法实现阻塞线程和解除线程阻塞，LockSupport和每个使用它的线程都与一个许可(permit)关联。permit相当于1，0的开关，默认是0，调用一次unpark就加1变成1，调用一次park会消费permit, 也就是将1变成0，同时park立即返回。再次调用park会变成block（因为permit为0了，会阻塞在这里，直到permit变为1）, 这时调用unpark会把permit置为1。每个线程都有一个相关的permit, permit最多只有一个，重复调用unpark也不会积累。

park()和unpark()不会有 “Thread.suspend和Thread.resume所可能引发的死锁” 问题，由于许可的存在，调用 park 的线程和另一个试图将其 unpark 的线程之间的竞争将保持活性。

如果调用线程被中断，则park方法会返回。同时park也拥有可以设置超时时间的版本。

需要特别注意的一点：**park 方法还可以在其他任何时间“毫无理由”地返回，因此通常必须在重新检查返回条件的循环里调用此方法**。从这个意义上说，park 是“忙碌等待”的一种优化，它不会浪费这么多的时间进行自旋，但是必须将它与 unpark 配对使用才更高效。

三种形式的 park 还各自支持一个 blocker 对象参数。此对象在线程受阻塞时被记录，以允许监视工具和诊断工具确定线程受阻塞的原因。（这样的工具可以使用方法 getBlocker(java.lang.Thread) 访问 blocker。）建议最好使用这些形式，而不是不带此参数的原始形式。在锁实现中提供的作为 blocker 的普通参数是 this。
看下线程dump的结果来理解blocker的作用。

![线程dump结果对比](https://segmentfault.com/img/bVJuIP?w=783&h=375)

从线程dump结果可以看出：
有blocker的可以传递给开发人员更多的现场信息，可以查看到当前线程的阻塞对象，方便定位问题。所以java6新增加带blocker入参的系列park方法，替代原有的park方法。

看一个Java docs中的示例用法：一个先进先出非重入锁类的框架

```
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
  }}
```

### 主要成员变量

```
// Hotspot implementation via intrinsics API
    private static final sun.misc.Unsafe UNSAFE;
    private static final long parkBlockerOffset;
```

unsafe:全名sun.misc.Unsafe可以直接操控内存，被JDK广泛用于自己的包中，如java.nio和java.util.concurrent。但是不建议在生产环境中使用这个类。因为这个API十分不安全、不轻便、而且不稳定。
**LockSupport的方法底层都是调用Unsafe的方法实现。**

再来看parkBlockerOffset:
parkBlocker就是第一部分说到的用于记录线程被谁阻塞的，用于线程监控和分析工具来定位原因的，可以通过LockSupport的getBlocker获取到阻塞的对象。

```
 static {
        try {
            UNSAFE = sun.misc.Unsafe.getUnsafe();
            Class<?> tk = Thread.class;
            parkBlockerOffset = UNSAFE.objectFieldOffset
                (tk.getDeclaredField("parkBlocker"));
        } catch (Exception ex) { throw new Error(ex); }
 }
```

从这个静态语句块可以看的出来，先是通过反射机制获取Thread类的parkBlocker字段对象。然后通过sun.misc.Unsafe对象的objectFieldOffset方法获取到parkBlocker在内存里的偏移量，parkBlockerOffset的值就是这么来的.

JVM的实现可以自由选择如何实现Java对象的“布局”，也就是在内存里Java对象的各个部分放在哪里，包括对象的实例字段和一些元数据之类。 sun.misc.Unsafe里关于对象字段访问的方法把对象布局抽象出来，它提供了objectFieldOffset()方法用于获取某个字段相对 Java对象的“起始地址”的偏移量，也提供了getInt、getLong、getObject之类的方法可以使用前面获取的偏移量来访问某个Java 对象的某个字段。

为什么要用偏移量来获取对象？干吗不要直接写个get，set方法。多简单？
仔细想想就能明白，这个parkBlocker就是在线程处于阻塞的情况下才会被赋值。线程都已经阻塞了，如果不通过这种内存的方法，而是直接调用线程内的方法，线程是不会回应调用的。

### LockSupport的方法

![图片描述](https://segmentfault.com/img/bVJu1i?w=315&h=321)

可以看到，LockSupport中主要是park和unpark方法以及设置和读取parkBlocker方法。

```
 private static void setBlocker(Thread t, Object arg) {
        // Even though volatile, hotspot doesn't need a write barrier here.
        UNSAFE.putObject(t, parkBlockerOffset, arg);
  }
```

对给定线程t的parkBlocker赋值。

```
    public static Object getBlocker(Thread t) {
        if (t == null)
            throw new NullPointerException();
        return UNSAFE.getObjectVolatile(t, parkBlockerOffset);
    }
  
```

从线程t中获取它的parkBlocker对象，即返回的是阻塞线程t的Blocker对象。

接下来主查两类方法，一类是阻塞park方法，一类是解除阻塞unpark方法

### 阻塞线程

- park()

```
public static void park() {
        UNSAFE.park(false, 0L);
}
```

调用native方法阻塞当前线程。

- parkNanos(long nanos)

```
public static void parkNanos(long nanos) {
        if (nanos > 0)
            UNSAFE.park(false, nanos);
}
```

阻塞当前线程，最长不超过nanos纳秒，返回条件在park()的基础上增加了超时返回。

- parkUntil(long deadline)

```
public static void parkUntil(long deadline) {
  UNSAFE.park(true, deadline);
}
```

阻塞当前线程，知道deadline时间（deadline - 毫秒数）。

JDK1.6引入这三个方法对应的拥有Blocker版本。

- park(Object blocker)

```
public static void park(Object blocker) {
  Thread t = Thread.currentThread();
  setBlocker(t, blocker);
  UNSAFE.park(false, 0L);
  setBlocker(t, null);
}
```

1) 记录当前线程等待的对象（阻塞对象）；
2) 阻塞当前线程；
3) 当前线程等待对象置为null。

- parkNanos(Object blocker, long nanos)

```
public static void parkNanos(Object blocker, long nanos) {
  if (nanos > 0) {
      Thread t = Thread.currentThread();
      setBlocker(t, blocker);
      UNSAFE.park(false, nanos);
      setBlocker(t, null);
  }
}
```

阻塞当前线程，最长等待时间不超过nanos毫秒，同样，在阻塞当前线程的时候做了记录当前线程等待的对象操作。

- parkUntil(Object blocker, long deadline)

```
public static void parkUntil(Object blocker, long deadline) {
  Thread t = Thread.currentThread();
  setBlocker(t, blocker);
  UNSAFE.park(true, deadline);
  setBlocker(t, null);
}
```

阻塞当前线程直到deadline时间，相同的，也做了阻塞前记录当前线程等待对象的操作。

### 唤醒线程

- unpark(Thread thread)

```
public static void unpark(Thread thread) {
  if (thread != null)
      UNSAFE.unpark(thread);
}
```

唤醒处于阻塞状态的线程Thread。