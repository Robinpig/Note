## Introduction

计数信号量。从概念上讲，信号量维护一组许可。
每次 acquire 都会阻塞（如果必要）直到许可可用，然后获取它。每次 release 添加一个许可，可能释放一个阻塞的获取者。
然而，实际上并没有使用实际的许可对象；Semaphore 只是维护可用数量的计数并相应行动。
Semaphore 是一种经典的并发工具。
**信号量通常用于限制可以访问某些（物理或逻辑）资源的线程数。**

在获取条目之前，每个线程必须从信号量获取一个许可，确保有条目可用。当线程用完该条目后，将其返回到池中，并将许可返回给信号量，允许另一个线程获取该条目。注意，在调用 acquire 时不持有同步锁，因为这会阻止条目被返回到池中。**信号量封装了限制对池访问所需的同步，与维护池本身一致性所需的任何同步分开**。
初始化为 1 的信号量，并且其使用方式使其最多只有一个许可可用，可以作为互斥锁使用。这通常称为二值信号量，因为它只有两个状态：一个许可可用或零个许可可用。以这种方式使用时，二值信号量具有一个属性（与许多 `java.util.concurrent.locks.Lock` 实现不同），即**"锁"可以由非拥有者的线程释放（因为信号量没有所有权的概念）**。这在某些特殊情况下很有用，例如死锁恢复。

此类的构造方法可选择接受一个公平性参数。当设置为 false 时，此类不保证线程获取许可的顺序。特别是，允许插队，即调用 acquire 的线程可能被分配一个先于已等待线程的许可——逻辑上新线程将自己置于等待线程队列的头部。当公平性设置为 true 时，信号量保证调用任何 acquire 方法的线程按照其对这些方法的调用被处理的顺序（先进先出；FIFO）选择获得许可。注意，FIFO 排序必然适用于这些方法内的特定内部执行点。因此，一个线程可能在另一个线程之前调用 acquire，但在之后到达排序点，并且在从方法返回时也是如此。另请注意，无定时的 tryAcquire 方法不遵守公平性设置，但会获取任何可用许可。
通常，用于控制资源访问的信号量应初始化为公平的，以确保没有线程因访问资源而饥饿。当使用信号量进行其他类型的同步控制时，非公平排序的吞吐量优势往往超过公平性考虑。
此类还提供了同时获取和释放多个许可的便捷方法。注意，当这些方法在没有设置公平性的情况下使用时，无限期推迟的风险会增加。
**_内存一致性效应_**：*一个线程中调用 release() 之前的操作 **happens-before** 另一个线程中成功 acquire() 之后的操作。*

```java
public class Semaphore implements java.io.Serializable {
    /** All mechanics via AbstractQueuedSynchronizer subclass */
    private final Sync sync;
  
   public Semaphore(int permits) {
        sync = new NonfairSync(permits);
    }
  
   public Semaphore(int permits, boolean fair) {
        sync = fair ? new FairSync(permits) : new NonfairSync(permits);
    }
}
```

## Links

- [JDK Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
