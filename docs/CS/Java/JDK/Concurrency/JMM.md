## Introduction



### Shared Variables

Memory that can be shared between threads is called *shared memory* or *heap memory*.

All instance fields, `static` fields, and array elements are stored in heap memory. In this chapter, we use the term *variable* to refer to both fields and array elements.

Local variables ([§14.4](https://docs.oracle.com/javase/specs/jls/se8/html/jls-14.html#jls-14.4)), formal method parameters ([§8.4.1](https://docs.oracle.com/javase/specs/jls/se8/html/jls-8.html#jls-8.4.1)), and exception handler parameters ([§14.20](https://docs.oracle.com/javase/specs/jls/se8/html/jls-14.html#jls-14.20)) are never shared between threads and are unaffected by the memory model.

Two accesses to (reads of or writes to) the same variable are said to be *conflicting* if at least one of the accesses is a write.



Atomic

Orderable

Shareable

### Orderable

compiler
CPU
Memory



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

Every execution has a *synchronization order*. A synchronization order is a total order over all of the synchronization actions of an execution. For each thread *t*, the synchronization order of the synchronization actions ([§17.4.2](https://docs.oracle.com/javase/specs/jls/se8/html/jls-17.html#jls-17.4.2)) in *t* is consistent with the program order ([§17.4.3](https://docs.oracle.com/javase/specs/jls/se8/html/jls-17.html#jls-17.4.3)) of *t*.

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
- A write to a `volatile` field ([§8.3.1.4](https://docs.oracle.com/javase/specs/jls/se8/html/jls-8.html#jls-8.3.1.4)) *happens-before* every subsequent read of that field.
- A call to `start()` on a thread *happens-before* any actions in the started thread.
- All actions in a thread *happen-before* any other thread successfully returns from a `join()` on that thread.
- The default initialization of any object *happens-before* any other actions (other than default-writes) of a program.

When a program contains two conflicting accesses ([§17.4.1](https://docs.oracle.com/javase/specs/jls/se8/html/jls-17.html#jls-17.4.1)) that are not ordered by a happens-before relationship, it is said to contain a *data race*.

The semantics of operations other than inter-thread actions, such as reads of array lengths ([§10.7](https://docs.oracle.com/javase/specs/jls/se8/html/jls-10.html#jls-10.7)), executions of checked casts ([§5.5](https://docs.oracle.com/javase/specs/jls/se8/html/jls-5.html#jls-5.5), [§15.16](https://docs.oracle.com/javase/specs/jls/se8/html/jls-15.html#jls-15.16)), and invocations of virtual methods ([§15.12](https://docs.oracle.com/javase/specs/jls/se8/html/jls-15.html#jls-15.12)), are not directly affected by data races.

Therefore, a data race cannot cause incorrect behavior such as returning the wrong length for an array.

A program is *correctly synchronized* if and only if all sequentially consistent executions are free of data races.

If a program is correctly synchronized, then all executions of the program will appear to be sequentially consistent ([§17.4.3](https://docs.oracle.com/javase/specs/jls/se8/html/jls-17.html#jls-17.4.3)).

This is an extremely strong guarantee for programmers. Programmers do not need to reason about reorderings to determine that their code contains data races. Therefore they do not need to reason about reorderings when determining whether their code is correctly synchronized. Once the determination that the code is correctly synchronized is made, the programmer does not need to worry that reorderings will affect his or her code.

A program must be correctly synchronized to avoid the kinds of counterintuitive behaviors that can be observed when code is reordered. The use of correct synchronization does not ensure that the overall behavior of a program is correct. However, its use does allow a programmer to reason about the possible behaviors of a program in a simple way; the behavior of a correctly synchronized program is much less dependent on possible reorderings. Without correct synchronization, very strange, confusing and counterintuitive behaviors are possible.

We say that a read *r* of a variable *v* is allowed to observe a write *w* to *v* if, in the *happens-before* partial order of the execution trace:

- *r* is not ordered before *w* (i.e., it is not the case that *hb(r, w)*), and
- there is no intervening write *w*' to *v* (i.e. no write *w*' to *v* such that *hb(w, w')* and *hb(w', r)*).

Informally, a read *r* is allowed to see the result of a write *w* if there is no *happens-before* ordering to prevent that read.

A set of actions *A* is *happens-before consistent* if for all reads *r* in *A*, where *W(r)* is the write action seen by *r*, it is not the case that either *hb(r, W(r))* or that there exists a write *w* in *A* such that *w.v* = *r.v* and *hb(W(r), w)* and *hb(w, r)*.

In a *happens-before consistent* set of actions, each read sees a write that it is allowed to see by the *happens-before* ordering.




## happen-before

>- 程序顺序规则：一个线程中的每个操作，happens-before于该线程中的任意后续操作。
>- 监视器锁规则：对一个锁的解锁，happens-before于随后对这个锁的加锁。
>- volatile变量规则：对一个volatile域的写，happens-before于任意后续对这个volatile域的读。
>- 传递性：如果A happens-before B，且B happens-before C，那么A happens-before C。
>- start()规则：如果线程A执行操作ThreadB.start()（启动线程B），那么A线程的ThreadB.start()操作happens-before于线程B中的任意操作。
>- join()规则：如果线程A执行操作ThreadB.join()并成功返回，那么线程B中的任意操作happens-before于线程A从ThreadB.join()操作成功返回。
>- 线程中断规则:对线程interrupt方法的调用happens-before于被中断线程的代码检测到中断事件的发生。



snooping



### MESI



Modified（已修改）, Exclusive（独占的）,Shared（共享的），Invalid（无效的）

总线风暴

总线嗅探技术有哪些缺点？

由于MESI缓存一致性协议，需要不断对主线进行内存嗅探，大量的交互会导致总线带宽达到峰值。

### Memory Barries



## Reference

1. [为什么需要内存屏障 - zhihu](https://zhuanlan.zhihu.com/p/55767485)
2. [Java 并发基础之内存模型](https://www.javadoop.com/post/java-memory-model)
3. [JLS - Chapter 17. Threads and Locks](https://docs.oracle.com/javase/specs/jls/se8/html/jls-17.html#jls-17.4.4)

