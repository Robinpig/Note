## Introduction

C 语言本身在 C11 之前**没有**并发原语。线程来自 POSIX 线程库（本库由 glibc 提供，见 [glibc](/docs/CS/C/glibc.md)）或 C11 可选的 `<threads.h>`（多数实现基于 pthread）；**原子操作与内存模型**到 C11 的 `<stdatomic.h>` 才正式进入标准。并发相关的「数据竞争」本身是 [未定义行为](/docs/CS/C/UB.md)，必须靠同步消除。

## POSIX 线程基础

```c
pthread_t tid;
pthread_create(&tid, NULL, worker, arg);
pthread_join(tid, NULL);   // 等待结束
```

线程间共享同一地址空间——这正是共享数据需要同步的原因。线程池的实践模式见 [Thread](/docs/CS/C/Thread.md)。

## 互斥量（mutex）

临界区用 `pthread_mutex_t` 互斥：

```c
pthread_mutex_t m = PTHREAD_MUTEX_INITIALIZER;
pthread_mutex_lock(&m);
/* 临界区：同一时刻仅一个线程能进 */
pthread_mutex_unlock(&m);
```

忘记解锁、或在持非递归锁时再次取同一把锁会死锁。

## 条件变量（condvar）

条件变量让线程「等某个谓词成立」而非忙等，必须与 mutex 配合：

```c
pthread_cond_t c = PTHREAD_COND_INITIALIZER;
pthread_mutex_lock(&m);
while (!ready)                 // 必须用 while：防止虚假唤醒
    pthread_cond_wait(&c, &m); // 原子地放锁 + 睡眠
/* ready 为真，处理 */
pthread_mutex_unlock(&m);

/* 另一线程 */
pthread_mutex_lock(&m);
ready = true;
pthread_cond_signal(&c);       // 或 broadcast 唤醒全部
pthread_mutex_unlock(&m);
```

`while` 而非 `if` 是因为**虚假唤醒**可能发生；`pthread_cond_wait` 返回时已重新持锁。

## 读写锁与屏障

- `pthread_rwlock_t`：多读单写，读多写少场景提升并发。
- `pthread_barrier_t`：让若干线程在某点汇合，全部到齐才继续（常用于并行算法的分阶段同步）。

## 数据竞争

两个线程无同步地访问同一对象、且至少一个是写，就是**数据竞争**——属于 UB。只要共享可变状态，就必须有 mutex 或原子保护，不能赌单核 / 测试时没事。

## C11 原子：`<stdatomic.h>`

`_Atomic` 是类型限定符，对该类型的一切读写都是原子的：

```c
#include <stdatomic.h>
atomic_int counter = 0;
atomic_fetch_add(&counter, 1);          // 无锁自增
int v = atomic_load(&counter);
atomic_store(&counter, 0);
```

无锁（lock-free）与否取决于类型与平台；`atomic_is_lock_free(&counter)` 可查询。

## 内存序（memory_order）

原子操作自带**内存序**，控制它与其它内存访问的可见性 / 重排：

- `memory_order_relaxed`：只保证原子性，不排序其它访问。
- `memory_order_acquire`（读）/ `memory_order_release`（写）：构成 **release-acquire** 同步——release 之前的所有写，对随后 acquire 同一原子的线程**可见**（happens-before）。
- `memory_order_seq_cst`：默认、最严，全局单一总序。
- `consume` / `acq_rel`：前者已不建议新代码使用，后者用于读-改-写操作同时承担两头。

典型生产者-消费者：

```c
atomic_int ready = 0;
int        data = 0;

/* 生产者 */
data = 42;
atomic_store_explicit(&ready, 1, memory_order_release);

/* 消费者 */
while (!atomic_load_explicit(&ready, memory_order_acquire)) { /* 自旋 */ }
/* 此处读 data 必得 42 */
```

这与 Go 的 **happens-before**（[Go 内存模型](/docs/CS/Go/memory.md) / [Go 原子](/docs/CS/Go/atomic.md)）和 Java 的 `volatile` / `synchronized` 是同一套思想的三种表述；跨语言对照时抓住「同步 = 建立可见性顺序」这一条主线即可。

## Links

- [C](/docs/CS/C/C.md)
- [Thread](/docs/CS/C/Thread.md)
- [glibc](/docs/CS/C/glibc.md)
- [未定义行为](/docs/CS/C/UB.md)
- [Go 内存模型](/docs/CS/Go/memory.md)
- [Go 原子](/docs/CS/Go/atomic.md)

## References

1. [POSIX Threads 概览（man7）](https://man7.org/linux/man-pages/man7/pthreads.7.html)
2. [cppreference：原子操作与内存序](https://en.cppreference.com/w/c/atomic)
