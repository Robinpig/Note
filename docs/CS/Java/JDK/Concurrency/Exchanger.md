## Introduction



线程可两两配对并在配对间交换元素的同步点。
Exchanger 允许两个线程在一个会合点（rendezvous point）交换对象，在若干管道（pipeline）设计中很有用。

每个线程在调用 exchange 方法时提交某个对象，与伙伴线程配对，并在返回时收到伙伴线程的对象。
Exchanger 可视为 **SynchronousQueue** 的双向形式。
Exchanger 在遗传算法和管道设计等应用中可能很有用。
使用示例：下面是一个类的要点，它使用 Exchanger 在线程间交换缓冲区，使得填充缓冲区的线程在需要时能拿到一个刚清空的新缓冲区，同时把填满的缓冲区交给清空缓冲区的线程。



```java
 class FillAndEmpty {
   Exchanger<DataBuffer> exchanger = new Exchanger<>();
   DataBuffer initialEmptyBuffer = ... a made-up type
   DataBuffer initialFullBuffer = ...

   class FillingLoop implements Runnable {
     public void run() {
       DataBuffer currentBuffer = initialEmptyBuffer;
       try {
         while (currentBuffer != null) {
           addToBuffer(currentBuffer);
           if (currentBuffer.isFull())
             currentBuffer = exchanger.exchange(currentBuffer);
         }
       } catch (InterruptedException ex) { ... handle ... }
     }
   }

   class EmptyingLoop implements Runnable {
     public void run() {
       DataBuffer currentBuffer = initialFullBuffer;
       try {
         while (currentBuffer != null) {
           takeFromBuffer(currentBuffer);
           if (currentBuffer.isEmpty())
             currentBuffer = exchanger.exchange(currentBuffer);
         }
       } catch (InterruptedException ex) { ... handle ...}
     }
   }

   void start() {
     new Thread(new FillingLoop()).start();
     new Thread(new EmptyingLoop()).start();
   }
 }
```

**内存一致性效应（memory consistency effects）**：对于每一对通过 Exchanger 成功交换对象的线程，每个线程中 exchange() 调用之前的操作 happen-before 另一线程中对应 exchange() 返回之后的操作。

## Implementation

单个交换位（slot）上的算法是经典的 **dual data structure**（Scott & Scherer，DISC 04）：

```java
for (;;) {
  if (slot is empty) {                       // offer：放入自己的 Node
    if (can CAS slot from empty to node) {
      wait for release;
      return matching item in node;
    }
  }
  else if (can CAS slot from node to empty) { // release：取走对方的 item、放入自己的
    get the item in node;
    set matching item in node;
    release waiting thread;
  }
  // else retry on CAS failure
}
```

但单槽 CAS 的扩展性很差——所有线程竞争同一个内存位置，参与者一多吞吐就崩。所以 Exchanger 实际是一个 **elimination arena**：让冲突的线程在不同槽位上配对抵消，从而把竞争摊开。JDK 25 源码（`Exchanger.java:110-240` 类注释）的关键设计：

- **Node 是 ThreadLocal**（`Participant`）：持有 `seed`（XorShift 随机源）、`index`（arena 下标）、`item`、`volatile match`、`volatile parked`。槽位只在「指向 Node」与「置空」间交替，天然没有 ABA 问题，所以 per-thread Node 可以安全复用。
- **Slot 用 `@Contended` 填充**：arena 槽位之间不共享 cache line，否则消除arena几乎无收益；Node 不填充（分布较散，偶发 false sharing 可接受）。
- **arena 大小自适应**：`bound` 字段带版本号（`SEQ`）。同一 bound 下第三次 CAS 冲突 → 尝试扩容；第二次 spinout → 尝试缩容；错位次数（misses）用 XorShift 随机重选下标。`MMASK = 0xff`，arena 上限 256。
- **自旋与阻塞的权衡**：`SPINS = 1 << 10` 次 `Thread.onSpinWait()` 后仍未配对就 park。**虚拟线程场景特判**：用 `ForkJoinWorkerThread.hasKnownQueuedWork` 判断自旋是否可能等到释放者——没希望就直接让出上下文。
- **null 特判**：算法靠「item 字段非空」判断槽位状态，用户传 `null` 时翻译成静态 `Participant` 引用，返回前再翻译回来。
- **超时与中断**：为了 arena 边界控制，spinout 期间**忽略时间上限**（可能延迟 `TimeoutException`）；中断也推迟到成功取消后才真正抛出。

三个 VarHandle（`BOUND` / `MATCH` / `ENTRY`）完成对 arena 边界与槽位的 volatile 读与 CAS，见 [VarHandle](/docs/CS/Java/JDK/Concurrency/VarHandle.md)。

## Links

- [AQS](/docs/CS/Java/JDK/Concurrency/AQS.md)
- [Atomic](/docs/CS/Java/JDK/Concurrency/Atomic.md)
- [Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
- [CountDownLatch](/docs/CS/Java/JDK/Concurrency/CountDownLatch.md)
- [CyclicBarrier](/docs/CS/Java/JDK/Concurrency/CyclicBarrier.md)
- [ForkJoinPool](/docs/CS/Java/JDK/Concurrency/ForkJoinPool.md)
