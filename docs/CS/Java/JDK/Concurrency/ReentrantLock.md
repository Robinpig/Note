# ReentrantLock



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

