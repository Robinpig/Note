## Introduction

在 JDK 提供 `AbstractQueuedSynchronizer`（AQS）和 `ReentrantLock` 之前，锁设计者经历了一系列*基于自旋*与*基于队列*的互斥算法。它们在此处很重要，因为 **AQS 是 CLH 队列的一种阻塞（park）变体**，所以理解 CLH / MCS 就能解释 *为什么* AQS 是现在这个样子（一个虚拟的双向链表 FIFO 队列，每个等待者检查其前驱节点）。

这三种算法都是**概念性**的——JDK 并未提供 `TicketLock` / `CLHLock` / `MCSLock` 类。它们是用来描述"竞争激烈的锁应当如何行为"以及"是什么取舍推动设计走向 AQS"的术语。

这一演进由同一个扩展性问题驱动：朴素的自旋锁读写同一个共享标志，因此在竞争下每个等待者都猛击同一条缓存行（跨核的"乒乓"效应）。后续的算法把自旋从共享位置移开，转移到*每线程*状态上。

## Ticket Lock

最简单的*公平*自旋锁。两个全局变量：一个 `ticket` 计数器（下一次发出的号）和一个 `turn` 计数器（当前正在服务的号）。获取锁意味着取一个号并自旋，直到 `turn == myTicket`。释放锁意味着 `turn++`。

```java
class TicketLock {
    private final AtomicInteger ticket = new AtomicInteger(0);
    private final AtomicInteger turn   = new AtomicInteger(0);

    private final ThreadLocal<Integer> myTicket = ThreadLocal.withInitial(() -> 0);

    void lock() {
        int t = ticket.getAndIncrement();     // 取号
        myTicket.set(t);
        while (turn.get() != t) {             // 自旋等待叫号
            Thread.onSpinWait();
        }
    }

    void unlock() {
        turn.set(myTicket.get() + 1);         // 叫下一个号
    }
}
```

特性：

- **FIFO 公平性**：按到达顺序发号，因此不会发生饥饿。
- **扩展性上限**：每个等待者都自旋在单一的 `turn` 位置上。锁释放时，`turn` 由持有者写入、被*所有*等待者同时读取——每次释放都会引发一次缓存行所有权反弹。Ticket 锁在少量竞争核心之外无法扩展。
- 历史上曾作为构造块使用，但在真实竞争下不适合作为操作系统级或库级锁。

## CLH Lock

Craig–Landin–Hagersten 锁（简称 CLH 锁）：一种*队列*锁，每个线程自旋在**前驱**标志上，而非共享变量上。每个线程拥有一个包含 `locked` 布尔值的节点（线程持有锁或正在等待时为 true）。获取锁时，线程用 CAS 把自己的节点追加到队尾，然后自旋在其**前驱**的 `locked` 字段上。释放锁时，它只需把自己的节点 `locked` 置为 false——这正好唤醒正在监视该字段的后继节点。

```java
class CLHLock {
    static class Node { volatile boolean locked = true; }   // 默认 true = 仍持有/等待

    private final AtomicReference<Node> tail = new AtomicReference<>(new Node());

    // 每个线程持有自己的节点（thread-local），并记得前驱
    private final ThreadLocal<Node> pred = new ThreadLocal<>();
    private final ThreadLocal<Node> node = new ThreadLocal<>();

    void lock() {
        Node my = new Node();                 // 我来了，默认 locked=true
        node.set(my);
        Node p = tail.getAndSet(my);          // 原子地把自己挂到队尾，拿回前驱
        pred.set(p);
        while (p.locked) {                    // 自旋在前驱的 locked 上
            Thread.onSpinWait();
        }
        // 前驱释放（把它 locked 置 false）后，我获得锁
    }

    void unlock() {
        Node my = node.get();
        my.locked = false;                    // 通知后继：我走了
        // my 节点可被后续复用以避免分配；前驱节点也可回收
    }
}
```

为什么 CLH 能扩展而 Ticket 不能：

- 每个等待者都自旋在一个**不同**的内存位置（其前驱节点）上，因此释放锁只触及*一个*后继的缓存行，而非全部。
- 节点是单写者/单读者配对（节点只由其拥有者写入、只被其后继读取），这是缓存一致性友好的访问模式。

代价在于：线程必须知道其前驱，因此队列需要尾指针和每线程的前驱链接。在纯 CLH 中，取消（线程在排队时放弃）很别扭，而这正是 AQS 必须解决的难点。

## MCS Lock

Mellor-Crummey–Scott 锁（简称 MCS 锁）：另一种队列锁，但与 CLH 互为镜像——每个线程自旋在**自己节点**中的标志上，而非前驱的。释放路径是差异所在：持有者解锁时必须找到其后继，并将 `locked = false` *写入*后继节点以唤醒它。

```java
class MCSLock {
    static class Node {
        volatile boolean locked = true;       // 自旋在自己节点的这个标志上
        volatile Node next;                   // 后继指针
    }

    private final AtomicReference<Node> tail = new AtomicReference<>(null);
    private final ThreadLocal<Node> node = new ThreadLocal<>();

    void lock() {
        Node my = new Node();
        node.set(my);
        Node p = tail.getAndSet(my);          // 原子地成为新 tail
        if (p != null) {
            p.next = my;                      // 我是 p 的后继，p 释放时会通知我
            while (my.locked) {               // 自旋在自己节点的 locked 上
                Thread.onSpinWait();
            }
        }
        // p == null 说明队列原本空，我直接获得锁
    }

    void unlock() {
        Node my = node.get();
        if (my.next == null) {                // 可能暂无后继
            if (tail.compareAndSet(my, null)) // 真的没有 -> 直接清空 tail
                return;
            // 有并发后继正在挂接，自旋等它把 next 写好
            while (my.next == null) Thread.onSpinWait();
        }
        my.next.locked = false;               // 通知后继：轮到你了
    }
}
```

CLH 与 MCS——决定性差异在于**等待者在何处自旋、以及释放时由谁写入**：

| | 自旋目标 | 释放时写入 | 需要前驱？ | 需要后继？ |
| --- | --- | --- | --- | --- |
| **CLH** | 前驱节点的 `locked` | 自身的 `locked`（单写者） | 是 | 否 |
| **MCS** | 自身的 `locked` | 后继节点的 `locked` | 否 | 是 |

在 NUMA / 大型系统上，MCS 是更缓存友好的设计，因为每个等待者都纯粹自旋在本地状态上；而 CLH 释放更简单（无需查找后继）且每节点内存占用更少（无 `next` 指针），这正是 **AQS 选择 CLH 形态** 的原因。

## AQS as a CLH Variant

`AbstractQueuedSynchronizer` 明确是 *CLH 队列的一种变体*。其映射关系如下：

- AQS 的 `Node` 充当每线程的队列元素；它的 `waitStatus` 把 CLH 单一的 `locked` 布尔量推广成了多种状态（AQS 增加了 `CANCELLED`、`SIGNAL`、`CONDITION`、共享的 `PROPAGATE` 语义，在 JDK 25 中节点类型又进一步拆分）。

- 等待者依旧检查自己的**前驱**来决定能否继续推进——这就是 CLH "问前驱"的规则——但它不是忙等自旋，而是 **park** 挂起（`LockSupport.park`，参见 [LockSupport](/docs/CS/Java/JDK/Concurrency/Lock.md?id=locksupport)），并由前驱在释放时将其唤醒。这把纯自旋锁变成了阻塞锁，避免了长时间竞争下的 CPU 空转。

- AQS 用显式的 `CANCELLED` 节点以及 `acquireQueued` 中的跳过逻辑，补上了 CLH 在取消处理上的短板。

因此阅读 [AQS](/docs/CS/Java/JDK/Concurrency/AQS.md) 或 [ReentrantLock](/docs/CS/Java/JDK/Concurrency/ReentrantLock.md) 时，可以在脑中替换成这样的理解："一个节点改为 park 而非自旋的 CLH 队列，`state`（那个 int）以一个通用同步器计数器取代了单一的 `locked` 标志。"

## Comparison

| 算法 | 公平 | 每等待者的自旋目标 | 释放开销 | JDK 是否提供 |
| --- | --- | --- | --- | --- |
| Ticket | 是 | 共享的 `turn`（热点） | O(等待者数) 次缓存行反弹 | 否（仅概念） |
| CLH | 是 | 前驱节点 | O(1)（写自身标志） | 否——AQS 是 CLH 的变体 |
| MCS | 是 | 自身节点 | O(1)，但需要找到后继 | 否（仅概念） |
| 基于 AQS（ReentrantLock） | 可选 | 前驱（park） | O(1) 唤醒后继 | 是 |

实践结论：**不要在生产代码中手写自旋锁。** 在真实竞争下，原始自旋会空耗 CPU 且不主动让出；基于 AQS 的阻塞锁（ReentrantLock / StampedLock）会把等待者 park 起来，只在极短超时时才短暂自旋。

## Summary

- Ticket → CLH → MCS 正是教科书上从"共享热点变量"走向"每线程本地自旋、O(1) 交接"的路径。
- CLH 在前驱上自旋，并通过翻转自身标志来释放；MCS 在自身节点上自旋，并通过翻转后继的标志来释放。
- AQS 则是把 CLH 的思路改造为阻塞式（park/unpark）并具备取消处理能力的实现，`java.util.concurrent` 中的每一种锁都建立在它之上。

## Links

- [Lock](/docs/CS/Java/JDK/Concurrency/Lock.md)
- [AQS](/docs/CS/Java/JDK/Concurrency/AQS.md)
- [ReentrantLock](/docs/CS/Java/JDK/Concurrency/ReentrantLock.md)
- [LockSupport](/docs/CS/Java/JDK/Concurrency/Parker.md)

## References

1. [The java.util.concurrent Synchronizer Framework (AQS paper, Doug Lea)](http://gee.cs.oswego.edu/dl/papers/aqs.pdf)
2. [MCS locks — Mellor-Crummey & Scott, 1991](https://www.cs.rochester.edu/~scott/papers/1991_TOCS_synch.pdf)
3. [CLH locks — Craig / Landin / Hagersten](https://www.cl.cam.ac.uk/techreports/UCAM-CL-TR-579.pdf)
