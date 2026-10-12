## Introduction

Phaser 提供了一种更灵活的屏障形式，可用于控制多线程之间的分阶段（phased）计算。
它是一种可复用的同步屏障，功能上类似 CyclicBarrier 和 CountDownLatch，但支持更灵活的使用方式。


```java
public Phaser() {
    this(null, 0);
}

public Phaser(Phaser parent, int parties) {
  if (parties >>> PARTIES_SHIFT != 0)
    throw new IllegalArgumentException("Illegal number of parties");
  int phase = 0;
  this.parent = parent;
  if (parent != null) {
    final Phaser root = parent.root;
    this.root = root;
    this.evenQ = root.evenQ;
    this.oddQ = root.oddQ;
    if (parties != 0)
      phase = parent.doRegister(1);
  }
  else {
    this.root = this;
    this.evenQ = new AtomicReference<QNode>();
    this.oddQ = new AtomicReference<QNode>();
  }
  this.state = (parties == 0) ? (long)EMPTY :
  ((long)phase << PHASE_SHIFT) |
    ((long)parties << PARTIES_SHIFT) |
    ((long)parties);
}
```



**注册（Registration）**。与其他屏障不同，注册到某个 phaser 上进行同步的参与方（party）数量可随时间变化。任务可在任意时刻注册（使用 register、bulkRegister 方法，或建立初始参与方数量的构造方法），并可选地在某些到达（arrival）时注销（使用 arriveAndDeregister）。与多数基础同步构造一样，注册和注销只影响内部计数，不会建立任何额外内部记录，因此任务无法查询自己是否已注册。（不过，可以通过继承本类来引入这类记录。）

**同步（Synchronization）**。与 CyclicBarrier 类似，Phaser 可被反复等待。方法 arriveAndAwaitAdvance 的效果类似于 CyclicBarrier.await。Phaser 的每一代（generation）都关联一个阶段号（phase number）。阶段号从 0 开始，当所有参与方都到达 phaser 时推进，达到 Integer.MAX_VALUE 后回绕到 0。阶段号的使用使得"到达 phaser 时"与"等待其他参与方时"这两类动作可以独立控制，这是通过任意已注册参与方都可调用的两类方法实现的：

**到达（Arrival）**。方法 arrive 和 arriveAndDeregister 记录到达动作。这些方法不会阻塞，而是返回一个关联的到达阶段号，即此次到达所应用的 phaser 的阶段号。当某个阶段的最后一个参与方到达时，会执行一个可选动作，并推进阶段。这些动作由触发阶段推进的参与方执行，通过重写 onAdvance(int, int) 方法来安排，该方法同时也控制终止。重写该方法与给 CyclicBarrier 提供屏障动作类似，但更灵活。

**等待（Waiting）**。方法 awaitAdvance 需要一个表示到达阶段号的参数，并在 phaser 推进到（或已经处于）另一个阶段时返回。与使用 CyclicBarrier 的类似构造不同，即便等待线程被中断，awaitAdvance 也会继续等待。也提供了可中断和带超时的版本，但在以可中断或超时方式等待时遇到的异常不会改变 phaser 的状态。必要时，可以在这些异常的处理器中执行相关恢复操作，通常是在调用 forceTermination 之后。Phaser 也可用于 ForkJoinPool 中执行的任务。只要池的并行度（parallelism level）能容纳同时被阻塞的参与方的最大数量，就能保证进展。



**终止（Termination）**。Phaser 可能进入终止状态，可通过 isTerminated 方法检查。一旦终止，所有同步方法都会立即返回而无需等待推进，这通过负的返回值来表明。类似地，在终止后进行注册尝试没有效果。当 onAdvance 的调用返回 true 时触发终止。默认实现在注销导致已注册参与方数量变为 0 时返回 true。如下文所示，当 phaser 控制具有固定迭代次数的动作时，通常很方便通过重写该方法，使当前阶段号达到阈值时触发终止。方法 forceTermination 也可用于立即释放等待线程并允许它们终止。

**分层（Tiering）**。Phaser 可以分层（即以树形结构构建）以降低竞争。参与方数量很大、否则会承受沉重同步竞争开销的 phaser，可以改为让若干子 phaser 共享同一个父 phaser 的方式搭建。即便这会带来更大的单次操作开销，却可能大幅提升吞吐。
在分层 phaser 的树中，子 phaser 与其父 phaser 之间的注册和注销是自动管理的。每当子 phaser 的已注册参与方数量变为非 0（由 Phaser(Phaser, int) 构造方法、register 或 bulkRegister 建立）时，该子 phaser 就会注册到其父 phaser。每当因调用 arriveAndDeregister 导致已注册参与方数量变为 0 时，该子 phaser 就会从其父 phaser 注销。

**监控（Monitoring）**。虽然同步方法只能由已注册参与方调用，但 phaser 的当前状态可由任意调用者监控。在任意时刻，总共有 getRegisteredParties 个参与方，其中 getArrivedParties 个已到达当前阶段（getPhase）。当剩余（getUnarrivedParties）的参与方到达时，阶段推进。这些方法返回的值可能反映瞬时状态，因此一般不能用于同步控制。方法 toString 以方便非正式监控的形式返回这些状态查询的快照。



## Sample usages
Phaser 可以替代 CountDownLatch，用于控制服务可变数量参与方的一次性动作。典型用法是：负责搭建的方法先注册，再启动所有动作，最后注销，如下所示：
```java
 void runTasks(List<Runnable> tasks) {
   Phaser startingGate = new Phaser(1); // "1" to register self
   // create and start threads
   for (Runnable task : tasks) {
     startingGate.register();
     new Thread(() -> {
       startingGate.arriveAndAwaitAdvance();
       task.run();
     }).start();
   }

   // deregister self to allow threads to proceed
   startingGate.arriveAndDeregister();
 }
```

让一组线程针对给定的迭代次数反复执行动作，有一种方式是重写 onAdvance：
```java
 void startTasks(List<Runnable> tasks, int iterations) {
   Phaser phaser = new Phaser() {
     protected boolean onAdvance(int phase, int registeredParties) {
       return phase >= iterations - 1 || registeredParties == 0;
     }
   };
   phaser.register();
   for (Runnable task : tasks) {
     phaser.register();
     new Thread(() -> {
       do {
         task.run();
         phaser.arriveAndAwaitAdvance();
       } while (!phaser.isTerminated());
     }).start();
   }
   // allow threads to proceed; don't wait for them
   phaser.arriveAndDeregister();
 }
```
如果主任务稍后还需等待终止，它可以重新注册，然后执行类似的循环：
```java
   // ...
   phaser.register();
   while (!phaser.isTerminated())
     phaser.arriveAndAwaitAdvance();
```
在确信阶段号永远不会回绕 `Integer.MAX_VALUE` 的场景中，还可以用类似写法等待特定的阶段号。例如：
```java
 void awaitPhase(Phaser phaser, int phase) {
   int p = phaser.register(); // assumes caller not already registered
   while (p < phase) {
     if (phaser.isTerminated())
       // ... deal with unexpected termination
     else
       p = phaser.arriveAndAwaitAdvance();
   }
   phaser.arriveAndDeregister();
 }
```
要用一棵 phaser 树创建一组 n 个任务，可以采用如下形式，前提是存在一个 Task 类，其构造方法接受一个 Phaser 并在构造时向其注册。调用 build(new Task[n], 0, n, new Phaser()) 之后，这些任务便可以启动，例如提交到某个线程池中：
```java
 void build(Task[] tasks, int lo, int hi, Phaser ph) {
   if (hi - lo > TASKS_PER_PHASER) {
     for (int i = lo; i < hi; i += TASKS_PER_PHASER) {
       int j = Math.min(i + TASKS_PER_PHASER, hi);
       build(tasks, i, j, new Phaser(ph));
     }
   } else {
     for (int i = lo; i < hi; ++i)
       tasks[i] = new Task(ph);
       // assumes new Task(ph) performs ph.register()
   }
 }
```

TASKS_PER_PHASER 的最佳取值主要取决于预期的同步频率。对于极小的每阶段任务体（因而频率很高），低至 4 的值可能合适；而对于极大的任务体，则可取到数百。
实现说明：本实现将最大参与方数量限制为 65535。尝试注册更多参与方会导致 IllegalStateException。不过，你可以且应当创建分层 phaser 以容纳任意大规模的参与方集合。

## Links

- [AQS](/docs/CS/Java/JDK/Concurrency/AQS.md)
- [Atomic](/docs/CS/Java/JDK/Concurrency/Atomic.md)
- [Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
- [CountDownLatch](/docs/CS/Java/JDK/Concurrency/CountDownLatch.md)
- [CyclicBarrier](/docs/CS/Java/JDK/Concurrency/CyclicBarrier.md)
- [Exchanger](/docs/CS/Java/JDK/Concurrency/Exchanger.md)
