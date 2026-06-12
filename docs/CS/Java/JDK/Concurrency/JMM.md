## Introduction


A *memory model* describes, given a program and an execution trace of that program, whether the execution trace is a legal execution of the program.
The Java programming language memory model works by examining each read in an execution trace and checking that the write observed by that read is valid according to certain rules.

The memory model describes possible behaviors of a program.
An implementation is free to produce any code it likes, as long as all resulting executions of a program produce a result that can be predicted by the memory model.

This provides a great deal of freedom for the implementor to perform a myriad of code transformations, including the reordering of actions and removal of unnecessary synchronization.


A memory model specifies how threads and objects interact
- **Atomicity**
  Locking to obtain mutual exclusion for field updates
- **Visibility**
  Ensuring that changes made in one thread are seen in other threads
- **Ordering**
  Ensuring that you aren’t surprised by the order in which statements are executed


The Java Memory Model (JMM) is a relaxed memory model which acts as a contract between Java programmers, compiler writers and JVM implementors.

## Cache Coherence



### Memory Consistency Properties

Defines the happens-before relation on memory operations such as reads and writes of shared variables.
The results of a write by one thread are guaranteed to be visible to a read by another thread only if the write operation happens-before the read operation.
The synchronized and volatile constructs, as well as the Thread.start() and Thread.join() methods, can form happens-before relationships.
In particular: Each action in a thread happens-before every action in that thread that comes later in the program's order.
An unlock (synchronized block or method exit) of a monitor happens-before every subsequent lock (synchronized block or method entry) of that same monitor.
And because the happens-before relation is transitive, all actions of a thread prior to unlocking happen-before all actions subsequent to any thread locking that monitor.
A write to a volatile field happens-before every subsequent read of that same field.
Writes and reads of volatile fields have similar memory consistency effects as entering and exiting monitors, but do not entail mutual exclusion locking.
A call to start on a thread happens-before any action in the started thread.

All actions in a thread happen-before any other thread successfully returns from a join on that thread.
The methods of all classes in java.util.concurrent and its subpackages extend these guarantees to higher-level synchronization.
In particular:
Actions in a thread prior to placing an object into any concurrent collection happen-before actions subsequent to the access or removal of that element from the collection in another thread.
Actions in a thread prior to the submission of a Runnable to an Executor happen-before its execution begins. Similarly for Callables submitted to an ExecutorService.
Actions taken by the asynchronous computation represented by a Future happen-before actions subsequent to the retrieval of the result via Future.get() in another thread.
Actions prior to "releasing" synchronizer methods such as Lock.unlock, S
emaphore.release, and CountDownLatch.countDown happen-before actions subsequent to a successful "acquiring" method such as Lock.lock, Semaphore.acquire, Condition.await, and CountDownLatch.await on the same synchronizer object in another thread.
For each pair of threads that successfully exchange objects via an Exchanger, actions prior to the exchange() in each thread happen-before those subsequent to the corresponding exchange() in another thread.
Actions prior to calling CyclicBarrier.await and Phaser.awaitAdvance (as well as its variants) happen-before actions performed by the barrier action, and actions performed by the barrier action happen-before actions subsequent to a successful return from the corresponding await in other threads.


### MESI



Modified（已修改）, Exclusive（独占的）,Shared（共享的），Invalid（无效的）

总线风暴

总线嗅探技术有哪些缺点？

由于MESI缓存一致性协议，需要不断对主线进行内存嗅探，大量的交互会导致总线带宽达到峰值。

NUMA(Non-Uniform Memory Access Architecture)

## Java Memory Model

### Shared Variables

Memory that can be shared between threads is called *shared memory* or *heap memory*.

All instance fields, `static` fields, and array elements are stored in heap memory. In this chapter, we use the term *variable* to refer to both fields and array elements.

Local variables ([§14.4](https://docs.oracle.com/javase/specs/jls/se8/html/jls-14.html#jls-14.4)), formal method parameters ([§8.4.1](https://docs.oracle.com/javase/specs/jls/se8/html/jls-8.html#jls-8.4.1)), and exception handler parameters ([§14.20](https://docs.oracle.com/javase/specs/jls/se8/html/jls-14.html#jls-14.20)) are never shared between threads and are unaffected by the memory model.

Two accesses to (reads of or writes to) the same variable are said to be *conflicting* if at least one of the accesses is a write.





### Ordering

- compiler, JIT Instruction Reorder
- CPU
- Memory



### volatile



Variants of lock rule apply to volatile fields and thread control
- Writing a volatile has same basic memory effects as unlock
- Reading a volatile has same basic memory effects as lock

Similarly for thread start and termination

Details differ from locks in minor ways


- visually
- prevent reorder


### Final fields
All threads will read the final value so long as it is guaranteed
to be assigned before the object could be made visible to other
threads. So DON'T write:


```java
class Stupid implements Runnable {
  final int id;
  Stupid(int i) { new Thread(this).start(); id = i; }
  public void run() { System.out.println(id); }
}
```

Extremely weak rules for unsynchronized, non-volatile, non-final
reads and writes
type-safe, not-out-of-thin-air, but can be reordered, invisible



### Programs and Program Order

Among all the inter-thread actions performed by each thread *t*, the *program order* of *t* is a total order that reflects the order in which these actions would be performed according to the intra-thread semantics of *t*.

A set of actions is *sequentially consistent* if all actions occur in a total order (the execution order) that is consistent with program order, and furthermore, each read *r* of a variable *v* sees the value written by the write *w* to *v* such that:

- *w* comes before *r* in the execution order, and
- there is no other write *w*' such that *w* comes before *w*' and *w*' comes before *r* in the execution order.

Sequential consistency is a very strong guarantee that is made about visibility and ordering in an execution of a program. Within a sequentially consistent execution, there is a total order over all individual actions (such as reads and writes) which is consistent with the order of the program, and each individual action is atomic and is immediately visible to every thread.

If a program has no data races, then all executions of the program will appear to be sequentially consistent.

Sequential consistency and/or freedom from data races still allows errors arising from groups of operations that need to be perceived atomically and are not.

If we were to use sequential consistency as our memory model, many of the compiler and processor optimizations that we have discussed would be illegal. For example, in the trace in [Table 17.4-C](https://docs.oracle.com/javase/specs/jls/se8/html/jls-17.html#jls-17.4-C), as soon as the write of `3` to `p.x` occurred, subsequent reads of that location would be required to see that value.



### Synchronization Order

**Every execution has a *synchronization order*.** A synchronization order is a total order over all of the synchronization actions of an execution. For each thread *t*, the synchronization order of the synchronization actions ([§17.4.2](https://docs.oracle.com/javase/specs/jls/se8/html/jls-17.html#jls-17.4.2)) in *t* is consistent with the program order ([§17.4.3](https://docs.oracle.com/javase/specs/jls/se8/html/jls-17.html#jls-17.4.3)) of *t*.

Synchronization actions induce the *synchronized-with* relation on actions, defined as follows:

- An unlock action on monitor *m* *synchronizes-with* all subsequent lock actions on *m* (where "subsequent" is defined according to the synchronization order).

- A write to a volatile variable *v* ([§8.3.1.4](https://docs.oracle.com/javase/specs/jls/se8/html/jls-8.html#jls-8.3.1.4)) *synchronizes-with* all subsequent reads of *v* by any thread (where "subsequent" is defined according to the synchronization order).

- An action that starts a thread *synchronizes-with* the first action in the thread it starts.

- The write of the default value (zero, `false`, or `null`) to each variable *synchronizes-with* the first action in every thread.

  Although it may seem a little strange to write a default value to a variable before the object containing the variable is allocated, conceptually every object is created at the start of the program with its default initialized values.

- The final action in a thread `T1` *synchronizes-with* any action in another thread `T2` that detects that `T1` has terminated.

  `T2` may accomplish this by calling `T1``.isAlive()` or `T1``.join()`.

- If thread `T1` interrupts thread `T2`, the interrupt by `T1` *synchronizes-with* any point where any other thread (including `T2`) determines that `T2` has been interrupted (by having an `InterruptedException` thrown or by invoking `Thread.interrupted` or `Thread.isInterrupted`).

The source of a *synchronizes-with* edge is called a *release*, and the destination is called an *acquire*.



### Happens-before Order

Two actions can be ordered by a *happens-before* relationship. If one action *happens-before* another, then the first is visible to and ordered before the second.

If we have two actions *x* and *y*, we write *hb(x, y)* to indicate that *x happens-before y*.

- If *x* and *y* are actions of the same thread and *x* comes before *y* in program order, then *hb(x, y)*.
- There is a *happens-before* edge from the end of a constructor of an object to the start of a finalizer ([§12.6](https://docs.oracle.com/javase/specs/jls/se8/html/jls-12.html#jls-12.6)) for that object.
- If an action *x* *synchronizes-with* a following action *y*, then we also have *hb(x, y)*.
- If *hb(x, y)* and *hb(y, z)*, then *hb(x, z)*.

The `wait` methods of class `Object` ([§17.2.1](https://docs.oracle.com/javase/specs/jls/se8/html/jls-17.html#jls-17.2.1)) have lock and unlock actions associated with them; their *happens-before* relationships are defined by these associated actions.

It should be noted that the presence of a *happens-before* relationship between two actions does not necessarily imply that they have to take place in that order in an implementation. If the reordering produces results consistent with a legal execution, it is not illegal.

For example, the write of a default value to every field of an object constructed by a thread need not happen before the beginning of that thread, as long as no read ever observes that fact.

More specifically, if two actions share a *happens-before* relationship, they do not necessarily have to appear to have happened in that order to any code with which they do not share a *happens-before* relationship. Writes in one thread that are in a data race with reads in another thread may, for example, appear to occur out of order to those reads.

The *happens-before* relation defines when data races take place.

A set of synchronization edges, *S*, is *sufficient* if it is the minimal set such that the transitive closure of *S* with the program order determines all of the *happens-before* edges in the execution. This set is unique.

It follows from the above definitions that:

- An unlock on a monitor *happens-before* every subsequent lock on that monitor.
- A write to a `volatile` field *happens-before* every subsequent read of that field.
- A call to `start()` on a thread *happens-before* any actions in the started thread.
- All actions in a thread *happen-before* any other thread successfully returns from a `join()` on that thread.
- The default initialization of any object *happens-before* any other actions (other than default-writes) of a program.

When a program contains two conflicting accesses that are not ordered by a happens-before relationship, it is said to contain a *data race*.

The semantics of operations other than inter-thread actions, such as reads of array lengths, executions of checked casts, and invocations of virtual methods, are not directly affected by data races.

Therefore, a data race cannot cause incorrect behavior such as returning the wrong length for an array.

A program is *correctly synchronized* if and only if all sequentially consistent executions are free of data races.

If a program is correctly synchronized, then all executions of the program will appear to be sequentially consistent.

This is an extremely strong guarantee for programmers. Programmers do not need to reason about reorderings to determine that their code contains data races. Therefore they do not need to reason about reorderings when determining whether their code is correctly synchronized. Once the determination that the code is correctly synchronized is made, the programmer does not need to worry that reorderings will affect his or her code.

A program must be correctly synchronized to avoid the kinds of counterintuitive behaviors that can be observed when code is reordered. The use of correct synchronization does not ensure that the overall behavior of a program is correct. However, its use does allow a programmer to reason about the possible behaviors of a program in a simple way; the behavior of a correctly synchronized program is much less dependent on possible reorderings. Without correct synchronization, very strange, confusing and counterintuitive behaviors are possible.

We say that a read *r* of a variable *v* is allowed to observe a write *w* to *v* if, in the *happens-before* partial order of the execution trace:

- *r* is not ordered before *w* (i.e., it is not the case that *hb(r, w)*), and
- there is no intervening write *w*' to *v* (i.e. no write *w*' to *v* such that *hb(w, w')* and *hb(w', r)*).

Informally, a read *r* is allowed to see the result of a write *w* if there is no *happens-before* ordering to prevent that read.

A set of actions *A* is *happens-before consistent* if for all reads *r* in *A*, where *W(r)* is the write action seen by *r*, it is not the case that either *hb(r, W(r))* or that there exists a write *w* in *A* such that *w.v* = *r.v* and *hb(W(r), w)* and *hb(w, r)*.

In a *happens-before consistent* set of actions, each read sees a write that it is allowed to see by the *happens-before* ordering.



## happens-before

Before presenting the Java memory model in full, we will present a simpler memory model, called the happens-before memory model. 

This model involves several properties/requirements:
- There is a total order over all synchronization actions, known as the synchronization order. This order is consistent with program order and with mutual exclusion of locks.
- Synchronization actions induce synchronizes-with edges between matched actions.
- The transitive closure of the synchronizes-with edges and program order gives a partial order known as the happens-before order.
- The values that can be seen by a non-volatile read are determined by a rule known as happens before consistency.
- The value seen by a volatile read are determined by a rule known as synchronization order consistency. 

  

Happens-before consistency says that a read r of a variable v is allowed to observe a write w to v if, in the happens-before partial order of the execution trace: 

- r is not ordered before w (i.e., it is not the case that r hb → w), and 
- there is no intervening write w 0 to v (i.e., no write w 0 to v such that w hb → w 0 hb → r). 

Synchronization order consistency says that each read r of a volatile variable v returns the last write to v to come before it in the synchronization order. 

For example, the behavior shown in Figure 1 is allowed by the happens-before memory model. 
There are no synchronizes-with or happens-before edges between threads, and each read is allowed to see the write by the other thread.



snooping


**The rules for happens‐before are:**
- Program order rule. 
  Each action in a thread happens‐before every action in that thread that comes later in the program order.
- Monitor lock rule. 
  An unlock on a monitor lock happens‐before every subsequent lock on that same monitor lock.(Locks and unlocks on explicit Lock objects have the same memory semantics as intrinsic locks.)
- Volatile variable rule. 
  A write to a volatile field happens‐before every subsequent read of that same field.(Reads and writes of atomic variables have the same memory semantics as volatile variables.)
- Thread start rule. 
  A call to Thread.start on a thread happens‐before every action in the started thread.
- Thread termination rule. 
  Any action in a thread happens‐before any other thread detects that thread has terminated, either by successfully return from Thread.join or by Thread.isAlive returning false.
- Interruption rule. 
  A thread calling interrupt on another thread happens‐before the interrupted thread detects the interrupt (either by having InterruptedException thrown, or invoking isInterrupted or interrupted).
- Finalizer rule. 
  The end of a constructor for an object happens‐before the start of the finalizer for that object.
- Transitivity. 
  If A happens‐before B, and B happens‐before C, then A happens‐before C.

### Piggybacking on Synchronization

The implementation of the protected AbstractQueuedSynchronizer methods in FutureTask illustrates piggybacking. 
AQS maintains an integer of synchronizer state that FutureTask uses to store the task state: running, completed, or cancelled. 
But FutureTask also maintains additional variables, such as the result of the computation. 
When one thread calls set to save the result and another thread calls get to retrieve it, the two had better be ordered by happens‐before. 
This could be done by making the reference to the result volatile, but it is possible to exploit existing synchronization to achieve the same result at lower cost.

FutureTask is carefully crafted to ensure that a successful call to tryReleaseShared always happens‐before a subsequent call to TRyAcquireShared; 
ry-ReleaseShared always writes to a volatile variable that is read by TRyAcquire-Shared. 

We call this technique "piggybacking" because it uses an existing happens‐before ordering that was created for some other reason to ensure the visibility of object X, rather than creating a happens‐before ordering specifically for publishing X.

Other happens‐before orderings guaranteed by the class library include:
- Placing an item in a thread‐safe collection happens‐before another thread retrieves that item from the collection;
- Counting down on a CountDownLatch happens‐before a thread returns from await on that latch;
- Releasing a permit to a Semaphore happens‐before acquiring a permit from that same Semaphore;
- Actions taken by the task represented by a Future happens‐before another thread successfully returns from Future.get;
- Submitting a Runnable or Callable to an Executor happens‐before the task begins execution; and
- A thread arriving at a CyclicBarrier or Exchanger happens‐before the other threads are released from that same barrier or exchange point. If CyclicBarrier uses a barrier action, arriving at the barrier happens‐before the barrier action, which in turn happens‐before threads are released from the barrier.



### Memory Barries


写读

Buffer Fully Flush




## Links
- [Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
- [JSR 133: JavaTM Memory Model and Thread Specification Revision](https://jcp.org/en/jsr/detail?id=133)
- [JEP 188: Java Memory Model Update](http://openjdk.java.net/jeps/188)
- [Java Memory Model Examples: Good, Bad and Ugly](https://groups.inf.ed.ac.uk/request/jmmexamples.pdf)




## References

1. [为什么需要内存屏障 - zhihu](https://zhuanlan.zhihu.com/p/55767485)
2. [Java 并发基础之内存模型](https://www.javadoop.com/post/java-memory-model)
3. [JLS - Chapter 17. Threads and Locks](https://docs.oracle.com/javase/specs/jls/se8/html/jls-17.html#jls-17.4.4)
4. [Double-checked locking: Clever, but broken](https://www.infoworld.com/article/2074979/double-checked-locking--clever--but-broken.html)
5. [JSR 133 (Java Memory Model) FAQ](https://www.cs.umd.edu/~pugh/java/memoryModel/jsr-133-faq.html)
