## Introduction

1. Safety Hazards
2. Liveness Hazards(deadlock, starvation and livelock)
3. Performance Hazards

A liveness failure occurs when an activity gets into a state such that it is permanently unable to make forward progress.

If multiple threads access the same mutable state variable without appropriate synchronization, your program is broken. There are three ways to fix it:
- Don't share the state variable across threads;
- Make the state variable immutable; or
- Use synchronization whenever accessing the state variable.


**Stateless objects are always thread-safe.**

The term race condition is often confused with the related term data race, which arises when synchronization is not used to coordinate all access to a shared nonfinal field. 
You risk a data race whenever a thread writes a variable that might next be read by another thread or reads a variable that might have last been written by another thread if both threads do not use synchronization; 
code with data races has no useful defined semantics under the Java Memory Model. Not all race conditions are data races, and not all data races are race conditions, but they both can cause concurrent programs to fail in unpredictable ways. 
UnsafeCountingFactorizer has both race conditions and data races. See Chapter 16 for more on data races.

This type of race condition is called `check-then-act`: you observe something to be true (file X doesn’t
exist) and then take action based on that observation (create X); but in fact the
observation could have become invalid between the time you observed it and the
time you acted on it (someone else created X in the meantime), causing a problem
(unexpected exception, overwritten data, file corruption).

We refer collectively to `check-then-act` and `read-modify-write` sequences as compound actions: sequences of operations that must be executed atomically in order to remain thread-safe.

**To preserve state consistency, update related state variables in a single atomic operation.**




### Memory Model

- [JMM](/docs/CS/Java/JDK/Concurrency/JMM.md)
- [CAS](/docs/CS/Java/JDK/Basic/unsafe.md?id=CAS)
- [volatile](/docs/CS/Java/JDK/Concurrency/volatile.md)
- [synchronized Block](/docs/CS/Java/JDK/Concurrency/synchronized.md)


## Thread Fundamentals
- [Thread](/docs/CS/Java/JDK/Concurrency/Thread.md)
- [ThreadLocal](/docs/CS/Java/JDK/Concurrency/ThreadLocal.md)
- [ThreadLocalRandom](/docs/CS/Java/JDK/Concurrency/ThreadLocalRandom.md)
- [Atomics](/docs/CS/Java/JDK/Concurrency/Atomic.md)



## Concurrent Collections

1. fail-fast for Collections in `java.util`, such as `HashMap`, `ArrayList`
2. fail-safe for Collections in `java.util.concurrent`, such as `ConcurrentHashMap`, `CopyOnWriteArrayList`

- [CopyOnWriteArrayList](/docs/CS/Java/JDK/Collection/List.md?id=CopyOnWriteArrayList)
- [ConcurrentHashMap](/docs/CS/Java/JDK/Collection/Map.md?id=ConcurrentHashMap)
- [ConcurrentSkipListMap](/docs/CS/Java/JDK/Collection/Map.md?id=ConcurrentSkipListMap)
- [BlockingQueue](/docs/CS/Java/JDK/Collection/Queue.md?id=BlockingQueue)



## Locks

![locks](../images/juc-locks.png)

- [Lock and Conditions](/docs/CS/Java/JDK/Concurrency/Lock.md)
- [AQS](/docs/CS/Java/JDK/Concurrency/AQS.md)
- [ReentrantLock](/docs/CS/Java/JDK/Concurrency/ReentrantLock.md)
- [ReadWriteLock](/docs/CS/Java/JDK/Concurrency/ReadWriteLock.md)
- [StampedLock](/docs/CS/Java/JDK/Concurrency/StampedLock.md)


## Synchronizers
- [Semaphore](/docs/CS/Java/JDK/Concurrency/Semaphore.md)
- [CountDownLatch](/docs/CS/Java/JDK/Concurrency/CountDownLatch.md)
- [CyclicBarrier](/docs/CS/Java/JDK/Concurrency/CyclicBarrier.md)
- [Exchanger](/docs/CS/Java/JDK/Concurrency/Exchanger.md)
- [Phaser](/docs/CS/Java/JDK/Concurrency/Phaser.md)

## Executor

- [ThreadPoolExecutor](/docs/CS/Java/JDK/Concurrency/ThreadPoolExecutor.md)
- [ForkJoinPool](/docs/CS/Java/JDK/Concurrency/ForkJoinPool.md)
- [Future](/docs/CS/Java/JDK/Concurrency/Future.md)
