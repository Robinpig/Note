## Introduction

Threads are an inescapable feature of the Java language, and they can simplify the development of complex systems by turning complicated asynchronous code into simpler straight-line code. 
In addition, threads are the easiest way to tap the computing power of multiprocessor systems.
And, as processor counts increase, exploiting concurrency effectively will only become more important.


Several motivating factors led to the development of operating systems that allowed multiple programs to execute simultaneously:
- Resource utilization
- Fairness
- Convenience


Threads are sometimes called lightweight processes, and most modern operating systems treat threads, not processes, as the basic units of scheduling. 
In the absence of explicit coordination, threads execute simultaneously and asynchronously with respect to one another. 
Since threads share the memory address space of their owning process, all threads within a process have access to the same variables and allocate objects from the same heap, 
which allows finer-grained data sharing than inter-process mechanisms. 
But without explicit synchronization to coordinate access to shared data, a thread may modify variables that another thread is in the middle of using, with unpredictable results.

### Benefits of Threads
1. Exploiting Multiple Processors
2. Simplicity of Modeling 
3. Simplified Handling of Asynchronous Events
4. More Responsive User Interfaces

### Risks of Threads
1. Safety Hazards
2. Liveness Hazards
3. Performance Hazards

#### Safety Hazards
Thread safety can be unexpectedly subtle because, in the absence of sufficient synchronization, the ordering of operations in multiple threads is unpredictable and sometimes surprising.

Because threads share the same memory address space and run concurrently, they can access or modify variables that other threads might be using. 
This is a tremendous convenience, because it makes data sharing much easier than would other inter-thread communications mechanisms. 
But it is also a significant risk: threads can be confused by having data change unexpectedly. 
Allowing multiple threads to access and modify the same variables introduces an element of nonsequentiality into an otherwise sequential programming model, 
which can be confusing and difficult to reason about. 
For a multithreaded program's behavior to be predictable, access to shared variables must be properly coordinated so that threads do not interfere with one another. 
Fortunately, Java provides synchronization mechanisms to coordinate such access.

In the absence of synchronization, the compiler, hardware, and runtime are allowed to take substantial liberties with the timing and ordering of actions, 
such as caching variables in registers or processor-local caches where they are temporarily (or even permanently) invisible to other threads. 
These tricks are in aid of better performance and are generally desirable, but they place a burden on the developer to clearly identify 
where data is being shared across threads so that these optimizations do not undermine safety. 


#### Liveness Hazards 
While safety means “nothing bad ever happens”, liveness concerns the complementary goal that “something good eventually happens”. 
A liveness failure occurs when an activity gets into a state such that it is permanently unable to make forward progress. 
One form of liveness failure that can occur in sequential programs is an inadvertent infinite loop, where the code that follows the loop never gets executed. 
The use of threads introduces additional liveness risks. 
For example, if thread A is waiting for a resource that thread B holds exclusively, and B never releases it, A will wait forever. 
We will describe various forms of liveness failures and how to avoid them, including deadlock, starvation, and livelock.


#### Performance Hazards
Related to liveness is performance. Liveness means that something good eventually happens, eventually may not be good enough—we often want good things to happen quickly.
Performance issues subsume a broad range of problems, including poor service time, responsiveness, throughput, resource consumption, or scalability. 
Just as with safety and liveness, multithreaded programs are subject to all the performance hazards of single-threaded programs, 
and to others as well that are introduced by the use of threads.

In well designed concurrent applications the use of threads is a net performance gain, but threads nevertheless carry some degree of runtime overhead. 
Context switches—when the scheduler suspends the active thread temporarily so another thread can run—are more frequent in applications with many threads, 
and have significant costs: saving and restoring execution context, loss of locality, and CPU time spent scheduling threads instead of running them. 
When threads share data, they must use synchronization mechanisms that can inhibit compiler optimizations, 
flush or invalidate memory caches, and create synchronization traffic on the shared memory bus. 
All these factors introduce additional performance costs.

## Fundamentals

### Thread Safety
Writing thread-safe code is, at its core, about managing access to state, and in particular to *shared*, *mutable state*.

If multiple threads access the same mutable state variable without appropriate synchronization, your program is broken. There are three ways to fix it:
- Don't share the state variable across threads;
- Make the state variable immutable; or
- Use synchronization whenever accessing the state variable.

**Stateless objects are always thread-safe.**
> An object is immutable if:
> - Its state cannot be modified after construction;
> - All its fields are final; and
> - It is properly constructed (the this reference does not escape during construction).

A class is **thread-safe** if it behaves correctly when accessed from multiple threads, regardless of the scheduling or interleaving of the execution of those threads by the runtime environment, 
and with no additional synchronization or other coordination on the part of the calling code.

#### Atomicity

**To preserve state consistency, update related state variables in a single atomic operation.**

##### Race Condition


We refer collectively to `check-then-act` and `read-modify-write` sequences as compound actions: 
sequences of operations that must be executed atomically in order to remain thread-safe.


Where practical, use existing thread-safe objects, like [AtomicLong](/docs/CS/Java/JDK/Concurrency/Atomic.md), to manage your class's state. 
It is simpler to reason about the possible states and state transitions for existing thread-safe objects than it is for arbitrary state variables, 
and this makes it easier to maintain and verify thread safety.



The design process for a thread‐safe class should include these three basic elements:
- Identify the variables that form the object's state;
- Identify the invariants that constrain the state variables;
- Establish a policy for managing concurrent access to the object's state.

Constraints placed on states or state transitions by invariants and post‐conditions create additional synchronization or encapsulation requirements. If certain states are invalid, then the underlying state variables must be encapsulated, otherwise client code could put the object into an invalid state. If an operation has invalid state transitions, it must be made atomic. On the other hand, if the class does not impose any such constraints, we may be able to relax encapsulation or serialization requirements to obtain greater flexibility or better performance.

#### Locking

##### Intrinsic Locks
Java provides a built-in locking mechanism for enforcing atomicity: the [synchronized block](/docs/CS/Java/JDK/Concurrency/synchronized.md).
A synchronized block has two parts: a reference to an object that will serve as the lock, and a block of code to be guarded by that lock. 
A synchronized method is a shorthand for a synchronized block that spans an entire method body, and whose lock is the object on which the method is being invoked. 
(Static synchronized methods use the Class object for the lock.)

Every Java object can implicitly act as a lock for purposes of synchronization; these built-in locks are called **intrinsic locks** or **monitor locks**. 
The lock is automatically acquired by the executing thread before entering a synchronized block and automatically released when control exits the synchronized block, 
whether by the normal control path or by throwing an exception out of the block. 
The only way to acquire an intrinsic lock is to enter a synchronized block or method guarded by that lock.


There are advantages to using a private lock object instead of an object's intrinsic lock (or any other publicly accessible lock). Making the lock object private encapsulates the lock so that client code cannot acquire it, whereas a publicly accessible lock allows client code to participate in its synchronization policy ‐ correctly or incorrectly. Clients that improperly acquire another object's lock could cause liveness problems, and verifying that a publicly accessible lock is properly used requires examining the entire program rather than a single class.


##### Reentrancy
Reentrancy means that locks are acquired on a per-thread rather than per-invocation basis.
> Code that would Deadlock if Locks were Not Reentrant.

##### Guarding State with Locks
For every invariant that involves more than one variable, all the variables involved in that invariant must be guarded by the same lock.

##### Liveness and Performance
Avoid holding locks during lengthy computations or operations at risk of not completing quickly such as network or console I/O.


### Sharing Objects

#### Visibility

#### Publication and Escape


#### Instance Confinement
- Ad-hoc Thread Confinement
- Stack Confinement
- ThreadLocal


### Building Blocks

#### Synchronized Collections

#### Concurrent Collections

#### Synchronizers
A synchronizer is any object that coordinates the control flow of threads based on its state. 
Blocking queues can act as synchronizers; other types of synchronizers include semaphores, barriers, and latches.


##### Latches

A latch is a synchronizer that can delay the progress of threads until it reaches its terminal state.

[CountDownLatch](/docs/CS/Java/JDK/Concurrency/CountDownLatch.md?id=Introduction) is a flexible latch implementation.
It allows one or more threads to wait for a set of events to occur. 
The latch state consists of a counter initialized to a positive number, representing the number of events to wait for.
The countDown method decrements the counter, indicating that an event has occurred, and the await methods wait for the counter to reach zero, which happens when all the events have occurred. 
If the counter is nonzero on entry, await blocks until the counter reaches zero, the waiting thread is interrupted, or the wait times out.



FutureTask also acts like a latch. (FutureTask implements Future, which describes an abstract result-bearing computation).
FutureTask is used by the Executor framework to represent asynchronous tasks, and can also be used to represent any potentially lengthy computation that can be started before the results are needed.



##### Semaphores

Counting [semaphores](/docs/CS/Java/JDK/Concurrency/Semaphore.md?id=Introduction) are used to control the number of activities that can access a certain resource or perform a given action at the same time.


##### Barriers

[CyclicBarrier](/docs/CS/Java/JDK/Concurrency/CyclicBarrier.md?id=Introduction) allows a fixed number of parties to rendezvous repeatedly at a barrier point and is useful in parallel iterative algorithms 
that break down a problem into a fixed number of independent subproblems. 
Threads call await when they reach the barrier point, and await blocks until all the threads have reached the barrier point. 
If all threads meet at the barrier point, the barrier has been successfully passed, in which case all threads are released and the barrier is reset so it can be used again. 
If a call to await times out or a thread blocked in await is interrupted, then the barrier is considered broken and all outstanding calls to await terminate with BrokenBarrierException. 
If the barrier is successfully passed, await returns a unique arrival index for each thread, which can be used to “elect” a leader that takes some special action in the next iteration. 
CyclicBar rier also lets you pass a barrier action to the constructor; this is a Runnable that is executed (in one of the subtask threads) when the barrier is successfully passed but before the blocked threads are released.


Another form of barrier is [Exchanger](/docs/CS/Java/JDK/Concurrency/Exchanger.md?id=Introduction), a two-party barrier in which the parties exchange data at the barrier point. 
Exchangers are useful when the parties perform asymmetric activities, for example when one thread fills a buffer with data and the other thread consumes the data from the buffer; 
these threads could use an Exchanger to meet and exchange a full buffer for an empty one. 
When two threads exchange objects via an Exchanger, the exchange constitutes a safe publication of both objects to the other party.



[Phaser](/docs/CS/Java/JDK/Concurrency/Phaser.md?id=Introduction) is a reusable synchronization barrier, similar in functionality to CyclicBarrier and CountDownLatch but supporting more flexible usage.



### Summary of Fundamentals
> We've covered a lot of material so far! The following "concurrency cheat sheet" summarizes the main concepts and rules:
> - It's the mutable state, stupid. 
>   All concurrency issues boil down to coordinating access to mutable state. The less mutable state, the easier it is to
>   ensure thread safety.
> -  Make fields final unless they need to be mutable.
> -  Immutable objects are automatically thread‐safe.
>  Immutable objects simplify concurrent programming tremendously. They are simpler and safer, and can be shared
>   freely without locking or defensive copying.
> -  Encapsulation makes it practical to manage the complexity.
>    You could write a thread‐safe program with all data stored in global variables, but why would you want to?
>    Encapsulating data within objects makes it easier to preserve their invariants; encapsulating synchronization within
>    objects makes it easier to comply with their synchronization policy.
> - Guard each mutable variable with a lock.
> - Guard all variables in an invariant with the same lock.
> - Hold locks for the duration of compound actions.
> - A program that accesses a mutable variable from multiple threads without synchronization is a broken program.
> - Don't rely on clever reasoning about why you don't need to synchronize.
> - Include thread safety in the design processor explicitly document that your class is not thread‐safe.
> - Document your synchronization policy.



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



### Task Execution

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



## Executor

- [ThreadPoolExecutor](/docs/CS/Java/JDK/Concurrency/ThreadPoolExecutor.md)
- [ForkJoinPool](/docs/CS/Java/JDK/Concurrency/ForkJoinPool.md)
- [Future](/docs/CS/Java/JDK/Concurrency/Future.md)

## References
1. [Java Concurrency in Practice](https://jcip.net/)
2. [Concurrency JSR-166 Interest Site](http://gee.cs.oswego.edu/dl/concurrency-interest/index.html)
3. [The java.util.concurrent Synchronizer Framework](http://gee.cs.oswego.edu/dl/papers/aqs.pdf)
4. [Concurrent Programming in Java](http://gee.cs.oswego.edu/dl/cpj/index.html)










