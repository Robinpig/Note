## Introduction

1. Safety Hazards
2. Liveness Hazards(deadlock, starvation and livelock)
3. Performance Hazards

If multiple threads access the same mutable state variable without appropriate synchronization, your program is broken. There are three ways to fix it:
- Don't share the state variable across threads;
- Make the state variable immutable; or
- Use synchronization whenever accessing the state variable.


**Stateless objects are always thread-safe.**

The term race condition is often confused with the related term data race, which arises when synchronization is not used to coordinate all access to a shared nonfinal field. You risk a data race whenever a thread writes a variable that might next be read by another thread or reads a variable that might have last been written by another thread if both threads do not use synchronization; code with data races has no useful defined semantics under the Java Memory Model. Not all race conditions are data races, and not all data races are race conditions, but they both can cause concurrent programs to fail in unpredictable ways. UnsafeCountingFactorizer has both race conditions and data races. See Chapter 16 for more on data races.

This type of race condition is called `check-then-act`: you observe something to be true (file X doesn’t exist) and then take action based on that observation (create X); but in fact the observation could have become invalid between the time you observed it and the time you acted on it (someone else created X in the meantime), causing a problem(unexpected exception, overwritten data, file corruption).

We refer collectively to `check-then-act` and `read-modify-write` sequences as compound actions: sequences of operations that must be executed atomically in order to remain thread-safe.

**To preserve state consistency, update related state variables in a single atomic operation.**


The design process for a thread‐safe class should include these three basic elements:
• Identify the variables that form the object's state;
• Identify the invariants that constrain the state variables;
• Establish a policy for managing concurrent access to the object's state.

Constraints placed on states or state transitions by invariants and post‐conditions create additional synchronization or encapsulation requirements. If certain states are invalid, then the underlying state variables must be encapsulated, otherwise client code could put the object into an invalid state. If an operation has invalid state transitions, it must be made atomic. On the other hand, if the class does not impose any such constraints, we may be able to relax encapsulation or serialization requirements to obtain greater flexibility or better performance.

### Immutability
An object is immutable if:
• Its state cannot be modified after construction;
• All its fields are final; and
• It is properly constructed (the this reference does not escape during construction).

### State Ownership


### Instance Confinement
- Ad-hoc Thread Confinement
- Stack Confinement
- ThreadLocal

There are advantages to using a private lock object instead of an object's intrinsic lock (or any other publicly accessible lock). Making the lock object private encapsulates the lock so that client code cannot acquire it, whereas a publicly accessible lock allows client code to participate in its synchronization policy ‐ correctly or incorrectly. Clients that improperly acquire another object's lock could cause liveness problems, and verifying that a publicly accessible lock is properly used requires examining the entire program rather than a single class.

## Summary of Part I
We've covered a lot of material so far! The following "concurrency cheat sheet" summarizes the main concepts and rules presented in Part I.
- It's the mutable state, stupid. 
  All concurrency issues boil down to coordinating access to mutable state. The less mutable state, the easier it is to
  ensure thread safety.
-  Make fields final unless they need to be mutable.
-  Immutable objects are automatically thread‐safe.
 Immutable objects simplify concurrent programming tremendously. They are simpler and safer, and can be shared
  freely without locking or defensive copying.
-  Encapsulation makes it practical to manage the complexity.
   You could write a thread‐safe program with all data stored in global variables, but why would you want to?
   Encapsulating data within objects makes it easier to preserve their invariants; encapsulating synchronization within
   objects makes it easier to comply with their synchronization policy.
- Guard each mutable variable with a lock.
- Guard all variables in an invariant with the same lock.
- Hold locks for the duration of compound actions.
- A program that accesses a mutable variable from multiple threads without synchronization is a broken program.
- Don't rely on clever reasoning about why you don't need to synchronize.
- Include thread safety in the design processor explicitly document that your class is not thread‐safe.
- Document your synchronization policy.



Given these definitions:
$$
\begin{aligned}
&N_{cpu} = number\; of\; CPUs 
\\&U_{cpu}= target\; CPU\; utilization,\; 0\leq U_{cpu}\leq 1
\\&\frac{W}C= ratio\; of\; wait\; time\; to\; compute\; time
\end{aligned}
$$

The optimal pool size for keeping the processors at the desired utilization is:
$$
N_{threads} = N_{cpu}*U_{cpu}*(1+\frac{W}C)
$$

You can determine the number of CPUs using Runtime:

```java
int N_CPUS = Runtime.getRuntime().availableProcessors();
```


## Liveness Hazards

A liveness failure occurs when an activity gets into a state such that it is permanently unable to make forward progress.

Liveness failures are a serious problem because there is no way to recover from them short of aborting the application.
The most common form of liveness failure is lock‐ordering deadlock. Avoiding lock ordering deadlock starts at design
time: ensure that when threads acquire multiple locks, they do so in a consistent order. The best way to do this is by
using open calls throughout your program.

### Deadlock
A program will be free of lock‐ordering deadlocks if all threads acquire the locks they need in a fixed global order.

Open Calls

### Starvation

Poor Responsiveness

### Livelock

## Performance
Improving performance means doing more work with fewer resources. The meaning of "resources" can vary; for a given activity, some specific resource is usually in shortest supply, whether it is CPU cycles, memory, network bandwidth, I/O bandwidth, database requests, disk space, or any number of other resources. When the performance of an activity is limited by availability of a particular resource, we say it is bound by that resource: CPU‐bound, database‐bound, etc.

In using concurrency to achieve better performance, we are trying to do two things: utilize the processing resources we have more effectively, and enable our program to exploit additional processing resources if they become available.
From a performance monitoring perspective, this means we are looking to keep the CPUs as busy as possible.

> Avoid premature optimization. First make it right, then make it fast ‐ if it is not already fast enough.
### Amdahl's Law
Amdahl's law describes how much a program can theoretically be sped up by additional computing resources, based on the proportion of parallelizable and serial components. If F is the fraction of the calculation that must be executed serially, then Amdahl's law says that on a machine with N processors, we can achieve a speedup of at most:
$$
Speedup \leq \frac{1}{F+\frac{1-F}N}
$$
As N approaches infinity, the maximum speedup converges to 1/F.

### Costs Introduced by Threads

#### Context Switching
Context switches are not free; thread scheduling requires manipulating shared data structures in the OS and JVM. The OS and JVMuse the same CPUs your program does; more CPU time spent in JVM and OS code means less is available for your program. But OS and JVM activity is not the only cost of context switches. When a new thread is switched in, the data it needs is unlikely to be in the local processor cache, so a context switch causes a flurry of cache misses, and thus threads run a little more slowly when they are first scheduled.

#### Memory Synchronization
#### Blocking

### Reducing Lock Contention


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

## References
1. [Java Concurrency in Practice](https://jcip.net/)
2. [Concurrency JSR-166 Interest Site](http://gee.cs.oswego.edu/dl/concurrency-interest/index.html)
2.[Concurrency JSR-166 Interest Site](http://gee.cs.oswego.edu/dl/concurrency-interest/index.html)










