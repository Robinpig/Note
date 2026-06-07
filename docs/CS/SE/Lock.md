## Introduction

我们有两种锁：

- **乐观锁**：不阻止可能危险的操作，继续执行，希望一切顺利。
- **悲观锁**：在操作前阻塞对资源的访问，操作结束时释放锁。

使用**乐观锁**时，通常使用数据库记录上的版本字段，更新时检查读取的数据是否与正在写入的数据具有相同的版本。

像 [Hibernate](https://docs.jboss.org/hibernate/orm/current/userguide/html_single/Hibernate_User_Guide.html#locking-optimistic) 这样的数据库访问库通常提供使用乐观锁的功能。

**悲观锁**则依赖于一个外部系统来为我们的微服务持有锁。

锁本质上是有问题的；除非确实必要，否则应避免使用。

## Evaluation Lcoks

- 提供互斥
- 公平性
  - 饥饿
- 性能
  - 无锁
  - MPSC
  - MPMC

Dekker

最容易理解的硬件支持是 test-and-set（或原子交换）指令。
支持 test-and-set 的每种架构都有不同的名称。
在 SPARC 上称为 load/store unsigned byte 指令（`ldstub`）；在 x86 上称为带有锁前缀的原子交换（`xchg`）。

某些系统提供的另一种硬件原语是 compare-and-swap 指令（例如在 SPARC 上），或 compare-and-exchange（在 x86 上）。

## Spin Locks

要在单处理器上正确工作，需要抢占式调度器（即通过定时器中断线程以运行其他线程的调度器）。
没有抢占，自旋锁在单 CPU 上没有太大意义，因为在一个 CPU 上自旋的线程永远不会放弃它。

自旋锁不提供任何公平性保证。实际上，在竞争激烈时，自旋锁可能会永远旋转。简单的自旋锁不公平，可能导致饥饿。

对于自旋锁，在单 CPU 情况下，性能开销可能非常大；想象持有锁的线程在临界区中被抢占的情况。
调度器可能会运行所有其他线程（假设有 N-1 个），每个线程都尝试获取锁。
在这种情况下，每个线程将旋转整个时间片才放弃 CPU，浪费 CPU 周期。
然而，在多 CPU 上，自旋锁工作得相当好（如果线程数大致等于 CPU 数）。
逻辑如下：想象 CPU 1 上的线程 A 和 CPU 2 上的线程 B 竞争一个锁。
如果线程 A 拿到锁，然后线程 B 尝试获取，B 将在 CPU 2 上自旋。
然而，临界区通常很短，因此锁很快变得可用，并被线程 B 获取。
这种情况下，自旋等待另一个处理器持有的锁不会浪费太多周期，因此有效。

## Two-Phase Locks

## Distributed Lock

容错共识是昂贵的。
单个进程的独占访问（也称为锁定）是廉价的，但不具备容错性——如果进程在持锁时失败，则其他人无法访问该资源。
为锁添加超时使其成为容错锁或"lease"。
因此，进程对状态组件或"资源"持有 lease 直到过期时间；我们说进程在持有 lease 期间是该资源的"master"。
在 lease 到期之前，没有其他进程会接触该资源。
当然，这需要进程具有同步时钟。
更准确地说，如果两个进程时钟之间的最大偏差为 ε，进程 P 的 lease 在时间 t 过期，那么 P 知道在 P 时钟的 t - ε 时间之前没有其他进程会接触该资源。

在持有 lease 期间，master 可以自由读写资源。
写操作必须是有界时间的，以便保证要么失败，要么在 lease 过期后启动的任何操作之前完成；
对于像 SCSI 磁盘这样具有弱排序保证和长写入时间上界的资源，这可能是一个严重问题。

进程可以通过在 lease 过期前续约来保持对资源的控制。
也可以按需释放 lease。
但如果无法与持有 lease 的进程通信（可能是因为它已失败），只能等待 lease 过期才能接触其资源。
因此，续约成本与等待 lease 过期的时间之间存在权衡。
短 lease 意味着恢复期间等待时间短，但续约成本高。
长 lease 意味着恢复期间等待时间长，但续约成本低。

对于乐观锁，像 Hibernate 这样的数据库访问库通常提供相关功能，但在分布式场景中，我们会使用更具体的解决方案来实现更复杂的算法，如：

- [Redis](/docs/CS/DB/Redis/Lock.md) 使用实现锁算法的库，如 [ShedLock](https://github.com/lukas-krecan/ShedLock) 和 [Redisson](https://github.com/redisson/redisson/wiki/8.-Distributed-locks-and-synchronizers)。
  前者还使用其他系统（如 MongoDB、DynamoDB 等）提供锁实现。
- [Zookeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md?id=lock) 提供了一些关于锁的 recipes。
- [Hazelcast](https://hazelcast.com/blog/long-live-distributed-locks/) 基于其 [CP subsystem](https://docs.hazelcast.org/docs/3.12.3/manual/html-single/index.html#cp-subsystem) 提供了锁系统。
- [有赞 Bond](https://tech.youzan.com/bond/)

数据库 select for update

Redisson lua 基于 Redis 单线程模型

RedissonLock#unlockInnerAsync

- 减到零时删除
- 广播给等待者

实现悲观锁有一个大问题：如果锁持有者不释放锁怎么办？锁将永远被持有，可能导致**死锁**。
为防止此问题，我们为锁设置**过期时间**，这样锁将**自动释放**。

但如果第一个锁持有者的任务在时间到期前未完成，另一个微服务可以获取锁，然后两个锁持有者都可以释放锁，导致不一致。
记住，在异步网络中，没有定时器假设是可靠的。

我们需要使用**fencing token**，每次微服务获取锁时递增。
释放锁时必须将此 token 传递给锁管理器，因此如果第一个持有者在第二个持有者之前释放锁，系统将拒绝第二次锁释放。
根据实现，也可以决定让第二个锁持有者胜出。

场景：

- 锁超时重试
- 独占解锁
- 关闭前优雅解锁
- 可重入锁
- 锁 TTL
- 热 key

## Lock-based Concurrent Data Structures

近似计数器通过使用多个本地物理计数器（每个 CPU 核心一个）以及一个全局计数器来表示单个逻辑计数器。
具体来说，在具有四个 CPU 的机器上，有四个本地计数器和一个全局计数器。
除了这些计数器，还有锁：每个本地计数器一个，全局计数器一个。

近似计数的基本思想如下。
当给定核心上运行的线程希望增加计数器时，它增加其本地计数器；通过相应的本地锁同步对该本地计数器的访问。
因为每个 CPU 有自己的本地计数器，跨 CPU 的线程可以无竞争地更新本地计数器，因此对计数器的更新是可扩展的。

然而，为了使全局计数器保持最新（以防线程需要读取其值），本地值定期传输到全局计数器：获取全局锁，将其增加本地计数器的值，然后将本地计数器重置为零。

本地到全局传输的频率由阈值 S 决定。
S 越小，计数器行为越像不可扩展的计数器；S 越大，计数器越可扩展，但全局值可能偏离实际计数更远。
可以获取所有本地锁和全局锁（按指定顺序以避免死锁）来获得精确值，但这不可扩展。

### Concurrent Linked List

在列表中实现更高并发的是所谓的**hand-over-hand locking**（也称为**lock coupling**）。
不是为整个列表使用单个锁，而是为列表的每个节点添加一个锁。
遍历列表时，代码首先获取下一个节点的锁，然后释放当前节点的锁。

概念上，hand-over-hand 链表有一定意义；它在列表操作中实现了高度并发。
然而，在实践中，很难使这种结构比简单的单锁方法更快，因为遍历列表时为每个节点获取和释放锁的开销太大。
即使对于非常大的列表和大量线程，允许多个并发遍历所带来的并发性也不太可能比简单地获取单个锁、执行操作并释放它更快。
也许某种混合方式（每 N 个节点获取一个新锁）值得研究。

### Concurrent Queues

不是使用单个锁，而是使用两个锁，一个用于队列头部，一个用于尾部。
这两个锁的目标是启用入队和出队操作的并发性。
在通常情况下，入队列例程只访问尾锁，出队列只访问头锁。

添加一个虚拟节点（在队列初始化代码中分配）；这个虚拟节点使得头部和尾部操作可以分离。

队列常用于多线程应用程序。
然而，这里使用的队列类型（仅使用锁）通常不能完全满足此类程序的需求。
更完善的有限队列允许线程在队列为空或过满时等待（条件变量）。

### Concurrent Hash Table

不是为整个结构使用单个锁，而是为每个哈希桶（每个桶由一个列表表示）使用一个锁。这样做使得许多并发操作可以同时进行。

## Condition Variables

**条件变量**是一个显式队列，线程可以在执行状态（即某个条件）不符合预期时将自己放入其中（通过**等待**条件）；
当其他线程改变该状态时，可以唤醒一个（或多个）等待线程，从而允许它们继续执行（通过**通知**条件）。

> [!TIP]
>
> 调用 `signal` 或 `wait` 时始终持有锁。
>
> 使用条件变量时始终使用 while 循环。

covering condition 保守地涵盖线程需要唤醒的所有情况。
一般来说，如果发现程序只有在将 signal 改为 broadcast 时才有效（但你认为不需要这样），很可能有 bug；修复它！

## Semaphores

信号量是一个具有整数值的对象，可以通过两个例程操作；在 POSIX 标准中，这些例程是 `sem_wait()` 和 `sem_post()`。

因为信号量的初始值决定其行为，在调用其他例程与之交互之前，必须先将其初始化为某个值。

### Binary Semaphores (Locks)

只需用 sem_wait()/sem_post() 对包围关键的临界区。
初始值应为 1。

```c
sem_t m;
sem_init(&m, 0, X); // 将信号量初始化为 X；X 应该是什么？

sem_wait(&m);
// 临界区
sem_post(&m);
```

### Reader-Writer Locks

### Implement Semaphores

用锁和条件变量实现信号量：

```c

typedef struct __Zem_t {
  int value;
  pthread_cond_t cond;
  pthread_mutex_t lock;
} Zem_t;

// 只能有一个线程调用此函数
void Zem_init(Zem_t *s, int value) {
  s->value = value;
  Cond_init(&s->cond);
  Mutex_init(&s->lock);
}

void Zem_wait(Zem_t *s) {
  Mutex_lock(&s->lock);
  while (s->value <= 0)
  Cond_wait(&s->cond, &s->lock);
  s->value--;
  Mutex_unlock(&s->lock);
}

void Zem_post(Zem_t *s) {
  Mutex_lock(&s->lock);
  s->value++;
  Cond_signal(&s->cond);
  Mutex_unlock(&s->lock);
}
```

我们只使用一个锁和一个条件变量，加上一个跟踪信号量值的状态变量。
有趣的是，用信号量构建条件变量要棘手得多。

## References

1. [Everything I Know About Distributed Locks](https://dzone.com/articles/everything-i-know-about-distributed-locks)
2. [Leases: an efficient fault-tolerant mechanism for distributed file cache consistency](https://dl.acm.org/doi/pdf/10.1145/74851.74870)
3. [How to do distributed locking](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html)
4. [A simple distributed lock with memcached](https://bluxte.net/musings/2009/10/28/simple-distributed-lock-memcached/)
5. [Distributed resource locking using memcached](https://source.coveo.com/2014/12/29/distributed-resource-locking/)
6. [The Chubby lock service for loosely-coupled distributed systems]()
7. [Redis and Zookeeper for distributed lock](https://www.fatalerrors.org/a/redis-and-zookeeper-for-distributed-lock.html)
