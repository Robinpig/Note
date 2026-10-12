## Introduction


所谓 *memory model*（内存模型），是指在给定一个程序及其执行轨迹（execution trace）的前提下，判定该执行轨迹是否为程序的合法执行。
Java 语言的内存模型通过检查执行轨迹中的每一次读操作，并依据特定规则验证该读操作所观察到的写操作是否合法来运作。

内存模型描述的是程序的可能行为（possible behaviors）。
只要程序的所有执行结果都能被内存模型预测，具体实现便可以自由地生成任意代码。

这为实现者提供了极大的自由度，使其能够进行大量代码变换，包括操作重排序（reordering）以及去除不必要的同步。


内存模型规定了线程与对象之间的交互方式：
- **原子性（Atomicity）**
  通过加锁获得字段更新的互斥访问
- **可见性（Visibility）**
  确保一个线程所作的修改对其他线程可见
- **有序性（Ordering）**
  确保语句的执行顺序不会带来意料之外的结果


Java 内存模型（JMM）是一种宽松（relaxed）的内存模型，在 Java 程序员、编译器编写者与 JVM 实现者之间充当一种契约。

## Cache Coherence



### Memory Consistency Properties

定义了共享变量（shared variables）的读、写等内存操作之间的 happens-before 关系。
仅当某线程的写操作 happens-before 另一线程的读操作时，前者的写结果才保证对后者的读可见。
synchronized 与 volatile 构造，以及 Thread.start() 和 Thread.join() 方法，均可以形成 happens-before 关系。
具体而言：线程中的任一动作 happens-before 该线程程序顺序中在其之后的所有动作。
对监视器（monitor）的解锁（退出 synchronized 块或方法）happens-before 随后对该同一监视器的每一次加锁（进入 synchronized 块或方法）。
由于 happens-before 关系具有传递性，线程在解锁前的所有动作 happens-before 任何其他线程对该监视器加锁后的所有动作。
对 volatile 字段的写 happens-before 随后对该同一字段的每一次读。
volatile 字段的读写具有与进入/退出监视器相似的内存一致性效果，但不需要互斥加锁。
对线程调用 start 的动作 happens-before 被启动线程中的任一动作。

线程中的所有动作 happens-before 任何其他线程成功从该线程的 join 返回。
java.util.concurrent 及其子包中所有类的方法，将这些保证扩展到了更高层次的同步。
具体而言：
线程将对象放入任一并发集合前的动作 happens-before 另一线程从该集合访问或移除该元素后的动作。
线程向 Executor 提交 Runnable 前的动作 happens-before 其开始执行。向 ExecutorService 提交 Callable 同理。
由 Future 代表的异步计算所采取的动作 happens-before 另一线程通过 Future.get() 取回结果后的动作。
在调用 Lock.unlock、Semaphore.release、CountDownLatch.countDown 等“释放”同步器方法前的动作 happens-before 另一线程对同一同步器对象成功调用 Lock.lock、Semaphore.acquire、Condition.await、CountDownLatch.await 等“获取”方法后的动作。
每一对通过 Exchanger 成功交换对象的线程，各自在 exchange() 之前的动作 happens-before 另一线程对应 exchange() 之后的动作。
在调用 CyclicBarrier.await 与 Phaser.awaitAdvance（及其变体）之前的动作 happens-before 由屏障动作（barrier action）执行的动作，而屏障动作执行的动作 happens-before 其他线程成功从对应 await 返回之后的动作。


### MESI



Modified（已修改）, Exclusive（独占的）,Shared（共享的），Invalid（无效的）

总线风暴

总线嗅探技术有哪些缺点？

由于MESI缓存一致性协议，需要不断对主线进行内存嗅探，大量的交互会导致总线带宽达到峰值。

NUMA（非统一内存访问架构，Non-Uniform Memory Access Architecture）

## Java Memory Model

### Shared Variables

线程之间可以共享的内存称为 *shared memory*（共享内存）或 *heap memory*（堆内存）。

所有实例字段、`static` 字段与数组元素都存储在堆内存中。本章使用术语 *variable*（变量）来同时指代字段与数组元素。

局部变量（[§14.4](https://docs.oracle.com/javase/specs/jls/se8/html/jls-14.html#jls-14.4)）、方法的形式参数（[§8.4.1](https://docs.oracle.com/javase/specs/jls/se8/html/jls-8.html#jls-8.4.1)）以及异常处理器的参数（[§14.20](https://docs.oracle.com/javase/specs/jls/se8/html/jls-14.html#jls-14.20)）永远不会在线程之间共享，因此不受内存模型影响。

对同一个变量的两次访问（读或写），只要其中至少一次是写，就称为 *conflicting*（冲突访问）。





### Ordering

- 编译器、JIT 指令重排序
- CPU
- 内存



### volatile

锁规则的变体同样适用于 volatile 字段与线程控制
- 写入 volatile 具有与解锁（unlock）基本相同的内存效果
- 读取 volatile 具有与加锁（lock）基本相同的内存效果

线程的启动与终止同理

与锁的差别仅在细枝末节上

- 可见性层面
- 防止重排序

volatile 只给可见性与有序性，**不给互斥性**（`count++` 仍会丢更新），且只覆盖引用本身而不覆盖被引用对象的内部状态；
屏障落地的具体形态见 [volatile](/docs/CS/Java/JDK/Concurrency/volatile.md)。


### Final fields
只要能保证 final 字段在对象对其他线程可见之前完成赋值，所有线程都会读到该 final 值。因此不要写出这样的代码：


```java
class Stupid implements Runnable {
  final int id;
  Stupid(int i) { new Thread(this).start(); id = i; }
  public void run() { System.out.println(id); }
}
```

对于未同步、非 volatile、非 final 的读与写，规则极其宽松
保持类型安全、不会出现凭空（out-of-thin-air）的值，但可以被重排序、且不可见



### Programs and Program Order

在线程 *t* 所执行的全部线程间动作中，*t* 的*程序顺序*（program order）是一个全序，它反映了按照 *t* 的线程内语义这些动作本应被执行的先后次序。

若一组动作满足以下条件，则称其*顺序一致*（sequentially consistent）：所有动作都发生在一个与程序顺序相一致的全序（即执行顺序）之中；此外，对变量 *v* 的每次读 *r*，都能看到对 *v* 的某次写 *w* 所写入的值，该 *w* 满足：

- *w* 在执行顺序中位于 *r* 之前，并且
- 不存在另一次写 *w*'，使得 *w* 在执行顺序中位于 *w*' 之前、且 *w*' 位于 *r* 之前。

顺序一致是关于程序执行中可见性与有序性的一个极强的保证。在一次顺序一致的执行中，存在一个与程序顺序相一致的全序，涵盖所有单个动作（如读和写），并且每个单个动作都是原子的，且立即对每个线程可见。

如果一个程序不存在数据竞争，那么该程序的所有执行看上去都是顺序一致的。

顺序一致和/或不存在数据竞争，仍无法排除由「本应被原子地感知、实际却未被原子感知」的一组操作所引发的错误。

如果把顺序一致作为内存模型，本文讨论过的许多编译器与处理器优化都将是非法的。例如，在 [Table 17.4-C](https://docs.oracle.com/javase/specs/jls/se8/html/jls-17.html#jls-17.4-C) 的执行轨迹中，一旦对 `p.x` 写入了 `3`，后续对该位置的读就必须看到该值。



### Synchronization Order

**每次执行都有一个 *synchronization order*（同步顺序）。** 同步顺序是一次执行中所有同步动作的全序。对每个线程 *t*，*t* 中同步动作的顺序（[§17.4.2](https://docs.oracle.com/javase/specs/jls/se8/html/jls-17.html#jls-17.4.2)）与 *t* 的程序顺序（[§17.4.3](https://docs.oracle.com/javase/specs/jls/se8/html/jls-17.html#jls-17.4.3)）相一致。

同步动作在动作之间导出 *synchronized-with*（同步于）关系，定义如下：

- 对监视器 *m* 的解锁动作 *synchronizes-with* 其后对 *m* 的所有加锁动作（这里的「其后」按同步顺序来定义）。

- 对 volatile 变量 *v* 的写（[§8.3.1.4](https://docs.oracle.com/javase/specs/jls/se8/html/jls-8.html#jls-8.3.1.4)）*synchronizes-with* 其后任意线程对 *v* 的所有读（这里的「其后」按同步顺序来定义）。

- 启动线程的动作 *synchronizes-with* 被启动线程中的首个动作。

- 对每个变量写入默认值（`0`、`false` 或 `null`）*synchronizes-with* 每个线程中的首个动作。

  在包含该变量的对象被分配之前就写入默认值，看起来或许有些奇怪；但从概念上讲，每个对象都是在程序开始时以默认初始值创建出来的。

- 线程 `T1` 中的最后一个动作 *synchronizes-with* 另一线程 `T2` 中检测到 `T1` 已终止的任意动作。

  `T2` 可以通过调用 `T1``.isAlive()` 或 `T1``.join()` 来完成这一检测。

- 若线程 `T1` 中断了线程 `T2`，则 `T1` 发出的中断 *synchronizes-with* 任意其他线程（包括 `T2`）判定 `T2` 已被中断的任意时点（无论是抛出了 `InterruptedException`，还是调用了 `Thread.interrupted` 或 `Thread.isInterrupted`）。

*synchronizes-with* 边的起点称为 *release*（释放），终点称为 *acquire*（获取）。



### Happens-before Order

两个动作之间可以通过 *happens-before* 关系来定序。若动作 a *happens-before* 动作 b，则 a 对 b 可见，且在 b 之前发生。

对于两个动作 *x* 与 *y*，记 *hb(x, y)* 表示 *x happens-before y*。

- 若 *x* 与 *y* 是同一线程中的动作，且 *x* 在程序顺序中位于 *y* 之前，则 *hb(x, y)* 成立。
- 从某对象构造函数的结束到该对象终结器（finalizer）的开始（[§12.6](https://docs.oracle.com/javase/specs/jls/se8/html/jls-12.html#jls-12.6)）之间存在一条 *happens-before* 边。
- 若动作 *x* *synchronizes-with* 其后的动作 *y*，则同样有 *hb(x, y)*。
- 若 *hb(x, y)* 且 *hb(y, z)*，则 *hb(x, z)*。

`Object` 类的 `wait` 方法（[§17.2.1](https://docs.oracle.com/javase/specs/jls/se8/html/jls-17.html#jls-17.2.1)）关联着加锁与解锁动作；它们的 *happens-before* 关系由这些关联的动作定义。

需要注意，两个动作之间存在 *happens-before* 关系，并不必然意味着在具体实现中它们必须按此顺序发生。只要重排序产生的结果与某次合法执行一致，这种重排序就不算非法。

例如，某线程构造的对象中每个字段的默认值写入，无须 happens-before 该线程的开端，只要没有任何读观察到这一点即可。

更具体地说，若两个动作共享 *happens-before* 关系，那么对于与它们不共享 *happens-before* 关系的代码而言，它们并不必然表现为按该顺序发生。例如，一个线程中的写若与另一线程中的读构成数据竞争，就可能相对这些读表现为乱序。

*happens-before* 关系定义了数据竞争发生的时间点。

一组同步边 *S* 若满足：它是使 *S* 与程序顺序的传递闭包能够确定本次执行中全部 *happens-before* 边的最小集合，则称该集合 *sufficient*（充分）。这样的集合是唯一的。

由上述定义可推出：

- 对某监视器的解锁 *happens-before* 其后对该监视器的每次加锁。
- 对 `volatile` 字段的写 *happens-before* 其后对该字段的每次读。
- 对某线程调用 `start()` *happens-before* 被启动线程中的任意动作。
- 某线程中的所有动作 *happen-before* 另一线程从该线程的 `join()` 成功返回。
- 任意对象的默认初始化 *happens-before* 程序中其他所有动作（默认写除外）。

当一个程序包含两个未被 happens-before 关系定序的冲突访问时，称该程序包含 *data race*（数据竞争）。

线程间动作之外的操作语义，例如读取数组长度、执行受检类型转换、调用虚方法等，不受数据竞争的直接影响。

因此，数据竞争不会导致「为数组返回错误长度」这类错误行为。

当且仅当所有顺序一致的执行都不含数据竞争时，称程序是 *correctly synchronized*（正确同步的）。

若程序已正确同步，则该程序的所有执行看上去都是顺序一致的。

这对程序员而言是极强的保证。程序员无需推理重排序即可判定代码中是否存在数据竞争，因此在判断代码是否正确同步时也不必推理重排序。一旦确认代码已正确同步，程序员便无需再担心重排序会影响代码。

程序必须正确同步，才能避免代码被重排序时出现的那类反直觉行为。正确同步并不能确保程序的整体行为正确，但它的确让程序员能够以简单的方式推理程序可能的行为；正确同步的程序，其行为对可能的重排序的依赖要小得多。缺乏正确同步时，则可能出现非常奇怪、令人困惑且反直觉的行为。

若在执行轨迹的 *happens-before* 偏序中满足以下条件，则称对变量 *v* 的读 *r* 被允许观察到对 *v* 的写 *w*：

- *r* 不在 *w* 之前（即不存在 *hb(r, w)*），并且
- 中间不存在对 *v* 的写 *w*'（即不存在满足 *hb(w, w')* 且 *hb(w', r)* 的对 *v* 的写 *w*'）。

非正式地说，只要不存在阻止该读的 *happens-before* 定序，读 *r* 就被允许看到写 *w* 的结果。

若对动作集合 *A* 中的每个读 *r*（设 *W(r)* 为 *r* 所看到的写动作），既不存在 *hb(r, W(r))*，也不存在 *A* 中的写 *w* 满足 *w.v* = *r.v* 且 *hb(W(r), w)* 且 *hb(w, r)*，则称动作集合 *A* 是 *happens-before consistent*（happens-before 一致的）。

在一个 *happens-before consistent* 的动作集合中，每个读看到的都是按 *happens-before* 次序它被允许看到的某次写。



## happens-before

在完整介绍 Java 内存模型之前，先介绍一个更简单的模型，称为 happens-before 内存模型。

该模型包含若干性质与要求：
- 所有同步动作之上存在一个全序，称为同步顺序（synchronization order）。该顺序与程序顺序以及锁的互斥性相一致。
- 同步动作在相互匹配的动作之间导出 synchronizes-with 边。
- synchronizes-with 边与程序顺序的传递闭包给出一个偏序，称为 happens-before 顺序。
- 非 volatile 读可以看到的值，由一条称为 happens-before 一致性（happens before consistency）的规则决定。
- volatile 读所看到的值，由一条称为同步顺序一致性（synchronization order consistency）的规则决定。
  


happens-before 一致性规定：在执行轨迹的 happens-before 偏序中，若满足以下条件，则对变量 v 的读 r 被允许观察到对 v 的写 w：

- r 不在 w 之前（即不存在 r hb → w），并且
- 中间不存在对 v 的写 w 0（即不存在满足 w hb → w 0 hb → r 的对 v 的写 w 0）。

同步顺序一致性规定：对 volatile 变量 v 的每次读 r，返回同步顺序中位于它之前的最后一次对 v 的写。

例如，图 1 所示的行为是 happens-before 内存模型所允许的。
线程之间不存在 synchronizes-with 边或 happens-before 边，且每次读都被允许看到另一线程的写。



snooping（总线嗅探）


**happens-before 的规则如下：**
- 程序顺序规则。
  线程中的每个动作 happens-before 该线程中在程序顺序上更靠后的每个动作。
- 监视器锁规则。
  对监视器锁的解锁 happens-before 此后对同一监视器锁的每次加锁。（对显式 Lock 对象的加锁与解锁具有与内在锁相同的内存语义。）
- volatile 变量规则。
  对 volatile 字段的写 happens-before 此后对同一字段的每次读。（对原子变量的读写具有与 volatile 变量相同的内存语义。）
- 线程启动规则。
  对某线程调用 Thread.start happens-before 被启动线程中的每个动作。
- 线程终止规则。
  线程中的任一动作 happens-before 其他线程检测到该线程已终止的时刻，无论通过从 Thread.join 成功返回，还是通过 Thread.isAlive 返回 false。
- 中断规则。
  一个线程对另一个线程调用 interrupt happens-before 被中断的线程检测到该中断的时刻（无论是通过抛出 InterruptedException，还是通过调用 isInterrupted 或 interrupted）。
- 终结器规则。
  对象构造函数的结束 happens-before 该对象终结器的开始。
- 传递性。
  若 A happens-before B，且 B happens-before C，则 A happens-before C。

### Piggybacking on Synchronization

`FutureTask` 中对 `AbstractQueuedSynchronizer` 受保护方法的实现就是「搭便车」（piggybacking）的例子。
AQS 维护一个表示同步器状态的整数值，`FutureTask` 用它来存放任务状态：运行中、已完成或已取消。
但 `FutureTask` 还维护着额外的变量，例如计算结果。
当一个线程调用 `set` 保存结果、另一个线程调用 `get` 取回结果时，二者最好由 happens-before 定序。
一种做法是把结果的引用声明为 volatile，但也可以复用已有的同步，以更低的代价达到同样的效果。

`FutureTask` 的实现经过精心设计，确保成功调用 `tryReleaseShared` 总是 happens-before 随后对 `TRyAcquireShared` 的调用；
`tryReleaseShared` 总是写入一个 volatile 变量，而该变量正是由 `tryAcquireShared` 读取的。

之所以称这一手法为「搭便车」，是因为它复用了因其他原因而创建的既有 happens-before 次序，以保证对象 X 的可见性，而不是专门为发布 X 而新建一条 happens-before 次序。

类库所保证的其他 happens-before 次序还包括：
- 将某元素放入线程安全集合 happens-before 另一线程从该集合中取出该元素；
- 在某个 CountDownLatch 上计数减一 happens-before 某线程从该 latch 的 await 返回；
- 向 Semaphore 释放一个许可 happens-before 从同一个 Semaphore 获取一个许可；
- 由 Future 表示的任务所执行的动作 happens-before 另一线程从 Future.get 成功返回；
- 向 Executor 提交 Runnable 或 Callable happens-before 该任务开始执行；以及
- 线程到达 CyclicBarrier 或 Exchanger happens-before 其他线程从同一屏障或交换点被释放。若 CyclicBarrier 使用了屏障动作（barrier action），则到达屏障 happens-before 屏障动作，屏障动作又 happens-before 线程从屏障处被释放。



### Memory Barries


写读

缓冲区完全刷新（Buffer Fully Flush）




## Links
- [Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
- [VarHandle](/docs/CS/Java/JDK/Concurrency/VarHandle.md)
- [volatile](/docs/CS/Java/JDK/Concurrency/volatile.md)
- [JSR 133: JavaTM Memory Model and Thread Specification Revision](https://jcp.org/en/jsr/detail?id=133)
- [JEP 188: Java Memory Model Update](http://openjdk.java.net/jeps/188)
- [Java Memory Model Examples: Good, Bad and Ugly](https://groups.inf.ed.ac.uk/request/jmmexamples.pdf)




## References

1. [为什么需要内存屏障 - zhihu](https://zhuanlan.zhihu.com/p/55767485)
2. [Java 并发基础之内存模型](https://www.javadoop.com/post/java-memory-model)
3. [JLS - Chapter 17. Threads and Locks](https://docs.oracle.com/javase/specs/jls/se8/html/jls-17.html#jls-17.4.4)
4. [Double-checked locking: Clever, but broken](https://www.infoworld.com/article/2074979/double-checked-locking--clever--but-broken.html)
5. [JSR 133 (Java Memory Model) FAQ](https://www.cs.umd.edu/~pugh/java/memoryModel/jsr-133-faq.html)
