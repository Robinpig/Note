## Introduction

ReentrantLock implements [Lock](/docs/CS/Java/JDK/Concurrency/Lock.md), providing the same mutual exclusion and memory-visibility guarantees as [synchronized](/docs/CS/Java/JDK/Concurrency/synchronized.md). 
Acquiring a ReentrantLock has the same memory semantics as entering a synchronized block, and releasing a ReentrantLock has the same memory semantics as exiting a synchronized block.
And, like synchronized, ReentrantLock offers reentrant locking semantics. 
ReentrantLock supports all of the lock-acquisition modes defined by Lock, providing more flexibility for dealing with lock unavailability than does synchronized.



**Why create a new locking mechanism that is so similar to intrinsic locking?**

Intrinsic locking works fine in most situations but has some functional limitations—it is not possible to interrupt a thread waiting to acquire a lock, 
or to attempt to acquire a lock without being willing to wait for it forever. 
Intrinsic locks also must be released in the same block of code in which they are acquired; 
this simplifies coding and interacts nicely with exception handling, but makes non-blockstructured locking disciplines impossible.


A reentrant mutual exclusion Lock with the same basic behavior and semantics as the implicit monitor lock accessed using synchronized methods and statements, but with extended capabilities.
A ReentrantLock is owned by the thread last successfully locking, but not yet unlocking it. A thread invoking lock will return, 
successfully acquiring the lock, when the lock is not owned by another thread. 
The method will return immediately if the current thread already owns the lock. 
This can be checked using methods isHeldByCurrentThread, and getHoldCount.


The constructor for this class accepts an optional fairness parameter. When set true, under contention, locks favor granting access to the longest-waiting thread. Otherwise this lock does not guarantee any particular access order. Programs using fair locks accessed by many threads may display lower overall throughput (i.e., are slower; often much slower) than those using the default setting, but have smaller variances in times to obtain locks and guarantee lack of starvation. Note however, that fairness of locks does not guarantee fairness of thread scheduling. Thus, one of many threads using a fair lock may obtain it multiple times in succession while other active threads are not progressing and not currently holding the lock. Also note that the untimed tryLock() method does not honor the fairness setting. It will succeed if the lock is available even if other threads are waiting.

It is recommended practice to always immediately follow a call to lock with a try block, most typically in a before/after construction such as:

```java

 class X {
   private final ReentrantLock lock = new ReentrantLock();
   // ...

   public void m() {
     lock.lock();  // block until condition holds
     try {
       // ... method body
     } finally {
       lock.unlock()
     }
   }
 }
```

In addition to implementing the Lock interface, this class defines a number of public and protected methods for inspecting the state of the lock. 
Some of these methods are only useful for instrumentation and monitoring.
Serialization of this class behaves in the same way as built-in locks: a deserialized lock is in the unlocked state, regardless of its state when serialized.
This lock supports a maximum of 2147483647 recursive locks by the same thread. Attempts to exceed this limit result in Error throws from locking methods.


## lock

```java
public void lock() {
    sync.lock();
}

// NonFairSync
final void lock() {
    if (compareAndSetState(0, 1)) // quick CAS for first lock
        setExclusiveOwnerThread(Thread.currentThread());
    else
        acquire(1);
}

// FairSync
final void lock() {
    acquire(1);
}
```



### nonfairTryAcquire

invoke in tryAcquire

```java
final boolean nonfairTryAcquire(int acquires) {
    final Thread current = Thread.currentThread();
    int c = getState();
    if (c == 0) {
        if (compareAndSetState(0, acquires)) {
            setExclusiveOwnerThread(current);
            return true;
        }
    }
    else if (current == getExclusiveOwnerThread()) {
        int nextc = c + acquires;
        if (nextc < 0) // overflow
            throw new Error("Maximum lock count exceeded");
        setState(nextc);
        return true;
    }
    return false;
}
```



### FairSync#tryAcquire 

```java
/**
 * Fair version of tryAcquire.  Don't grant access unless
 * recursive call or no waiters or is first.
 */
protected final boolean tryAcquire(int acquires) {
    final Thread current = Thread.currentThread();
    int c = getState();
    if (c == 0) {
        if (!hasQueuedPredecessors() &&
            compareAndSetState(0, acquires)) {
            setExclusiveOwnerThread(current);
            return true;
        }
    }
    else if (current == getExclusiveOwnerThread()) {
        int nextc = c + acquires;
        if (nextc < 0)
            throw new Error("Maximum lock count exceeded");
        setState(nextc);
        return true;
    }
    return false;
}
```

see [hasQueuedPredecessors](/docs/CS/Java/JDK.Concurrency/AQS.md?id=hasqueuedpredecessors)

## unlock

```java
public void unlock() {
    sync.release(1);
}

protected final boolean tryRelease(int releases) {
    int c = getState() - releases;
    if (Thread.currentThread() != getExclusiveOwnerThread())
        throw new IllegalMonitorStateException();
    boolean free = false;
    if (c == 0) {
        free = true;
        setExclusiveOwnerThread(null);
    }
    setState(c);
   
```



## tryLock

only nonfairTryAcquire

```java
public boolean tryLock() {
    return sync.nonfairTryAcquire(1);
}
```



## FairSync vs NonFairSync

|        | FairSync                    | NonFairSync |
| ------ | --------------------------- | ----------- |
| lock   | check hasQueuedPredecessors | quick CAS   |
| unlock | -                           | -           |
|        |                             |             |



## ReentrantLock vs synchronized



|               | ReentrantLock     | synchronized |
| ------------- | ----------------- | ------------ |
| Fair          | has FairLock      | - |
| Share         | has shared        | - |
| Interruptible | has interruptible | - |
| Timeout | has tryLock(timeout) | - |
| Condition | Multiple conditions | - |
| Other | can get length of queue | - |
| Use | only for code block | for method/code block |
| Unlock | must unlock in finally | Auto Unlock |





## Summary

