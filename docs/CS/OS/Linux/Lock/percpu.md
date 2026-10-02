## Introduction

前面所有笔记都在讨论"怎么正确地竞争同一份数据"，per-CPU 变量则换个思路：**把数据按 CPU 切分，让竞争根本不发生**。每个 CPU 只读写自己的副本，因此不需要锁、不需要原子操作、也不产生 cache line 在核间的来回弹跳（false sharing 的主要来源）——这是内核里"以空间换同步"的标准手段。

代价同样明显：内存占用 ×CPU 数，且**读取全局视图需要聚合所有副本**（聚合值只是近似，除非另加保护）。

## API

```c
DEFINE_PER_CPU(int, counter);        /* 静态定义：每个 CPU 一份 int */

per_cpu(counter, cpu)++;             /* 访问指定 CPU 的副本（调用者保证安全） */

get_cpu_var(counter)++;              /* 禁抢占 + 取本 CPU 副本的左值 */
put_cpu_var(counter);                /* 恢复抢占 */

this_cpu_inc(counter);               /* 本 CPU 单次 RMW，自带禁抢占语义 */
this_cpu_read(counter);              /* 读本 CPU 副本 */

ptr = alloc_percpu(struct stat);     /* 动态分配（按 cache line 对齐，避免 false sharing） */
free_percpu(ptr);
```

x86-64 上 `this_cpu_*` 通常编译成一条以 `gs:` 段基址寻址的指令（如 `incq %gs:offset`），原子且免抢占——这是"副本 + 单指令"能做到的最快计数方式。

## 正确性前提

1. **写侧只属于本 CPU**：`per_cpu(var, cpu)` 直写别的 CPU 的副本是被禁止的（除非你知道对方无法访问它）。操作本 CPU 变量期间必须保证不被迁移到别的 CPU——`get_cpu_var`/`this_cpu_*` 隐含禁抢占，裸用 `per_cpu(var, smp_processor_id())` 则要自己 `preempt_disable()`；
2. **单次 RMW ≠ 复合原子**：`this_cpu_inc` 是一条指令，但"读→判断→写"的多步逻辑仍会被抢占打断，需要显式禁抢占或锁；
3. **其他 CPU 可以读你的副本**（比如统计聚合），但没有一致性保证——要么容忍瞬时偏差（多数统计场景无所谓），要么聚合时加锁/用 [seqlock](/docs/CS/OS/Linux/Lock/rwsem.md?id=seqlock) 模式。

## 典型应用

- **统计计数**：`percpu_counter`（带 `batch` 容差的聚合计数器：各 CPU 记增量，够一批才合并到全局值；vmstat、`nr_files` 等都用它）；
- **slab 分配器的 per-CPU 对象缓存**：分配/释放对象通常只碰本 CPU 的 freelist，无锁无原子；
- **网络与块设备的热路径**：per-CPU 收发队列、per-CPU backlog，避免包处理在核间竞争；
- **per-CPU 副本 + 机制组合**：与 [RCU](/docs/CS/OS/Linux/Lock/RCU.md)（每 CPU 经历静止状态）、per-CPU seqlock（latch 方案）搭配是常见套路。

## 与锁的取舍

| | 锁 / 原子操作 | per-CPU 变量 |
| :-- | :-- | :-- |
| 保护范围 | 任意多个变量的复合不变量 | 单个 CPU 副本的独立更新 |
| 内存 | 一份 | N 份（×CPU 数） |
| 全局读 | 直接读 | 需要聚合，且是近似值 |
| 竞争开销 | cache line 争用、等待 | 零（各写各的 line） |
| 适用频率 | 中低频、复杂不变量 | 高频简单累加/缓存 |

经验法则：**计数器、缓存、队列这类"高频单变量写"先想想能不能 per-CPU 化，不行再上锁**；反之复合不变量只能用锁。

## 用户态对照

同一个思想在各语言运行时里反复出现：Java 的 `LongAdder`（Striped64，按 cell 分散计数）、Go 的 per-P mcache/本地 runq（见 [GMP](/docs/CS/Go/Concurrency/Goroutine.md?id=gmp)）、C/C++ 的 `thread_local`。它们都验证同一条规律——**把共享拆成按执行单元隔离，再在低频路径上聚合**。

## Links

- [Linux Lock](/docs/CS/OS/Linux/Lock/README.md)
- [原子操作与内存屏障](/docs/CS/OS/Linux/Lock/atomic.md) — `this_cpu_*` 的单指令原子性基础
- [spinlock](/docs/CS/OS/Linux/Lock/spinlock.md) — qspinlock 的 per-CPU 节点同样是这一思想
- [GMP（Go 并发）](/docs/CS/Go/Concurrency/Goroutine.md)
