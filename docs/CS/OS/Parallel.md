## Introduction

并行计算关注如何在多个执行单元（多核、多 CPU、多机）上协同完成同一计算，核心矛盾有两个：**任务怎么切分**（并行模型）与**工作怎么分配**（调度与负载均衡）。并行（parallel）不等于并发（concurrent）：并发是结构上同时处理多个任务的能力（时间片轮转也算），并行是物理上同一时刻真的有多个任务在执行。

## 并行模型

| 模型 | 通信方式 | 同步 | 代表 |
|------|---------|------|------|
| 共享内存（线程） | 共享变量 + 锁/原子 | 隐式（同地址空间） | pthread、Java 线程 |
| fork-join | 分叉子任务、join 汇合 | 结构化屏障 | Cilk、Java ForkJoinPool、Go 的扇出模式 |
| 消息传递 | 显式 send/recv | 显式 | MPI（HPC）、Actor（Akka/Erlang） |
| 数据流/CSP | 通过 channel 传递数据 | 由数据就绪驱动 | Go goroutine+channel |
| SIMD/GPU | 单指令驱动多数据 | 锁步 | AVX、CUDA warp |
| MapReduce / 批处理 | 分布式 shuffle | 阶段屏障 | Hadoop/Spark 阶段 |

## Work-first 与 Work-Stealing

并行任务的执行时间有两个经典度量：**work** $T_1$（在一个核上串行执行全部指令的时间）与 **span/depth** $T_\infty$（关键路径长度，无限多核下的最短时间）。$p$ 个核上的理论加速比上限由 work law（$T_p \ge T_1/p$）与 span law（$T_p \ge T_\infty$）共同约束，效率取决于调度器如何把任务铺到核上。

**Work-stealing（工作窃取，ABP 论文）** 是 fork-join 并行事实上的标准调度：

- 每个 worker 线程维护自己的双端任务队列（deque）：本地任务从**底端** LIFO 取（先取刚分叉出的子任务，保持缓存局部性）；
- 空闲 worker 从其他随机选中的受害者队列**顶端** FIFO 偷任务（偷走的是最老、粒度最大的子树，一次偷到大量工作，减少窃取次数）；
- ABP 证明其期望执行时间 $T_p = O(T_1/p + T_\infty)$，空间开销也有界，且只在窃取时发生跨核同步，竞争极低。

这正是 Cilk、Java ForkJoinPool、Go 调度器（GMP 中 P 的本地 runq + work-stealing，见 [Go 并发](/docs/CS/Go/Concurrency/Concurrency.md)）的共同基础。Linux 内核调度器处理的是固定实体（task），负载均衡用域间主动拉取（[EAS/负载均衡](/docs/CS/OS/Linux/proc/sche.md)）；用户态 work-stealing 处理的是动态生成的任务 DAG，这是两者问题形态的差异。

## 随机化负载均衡：Power of Two Choices

n 个任务随机分配到 n 个队列（随机放置）时，最大负载约为 $\log n/\log\log n$；而**二选一策略**（随机挑两个队列，选其中负载更轻的放进去）把最大负载降到约 $\log\log n$——只用一个额外的随机采样，就从对数级压到双对数级，这是分布式系统中性价比最高的理论结果之一。

应用随处可见：

- nginx `least_conn` / 随机二选一的上游选择；
- 键值存储的数据放置（"随机挑两个节点放副本"）；
- work-stealing 中随机选受害者（避免全局协调与 thundering herd）；
- 哈希冲突解决（two-way chaining，对比单哈希桶显著降低最长链）。

对照集中式最少连接（least-loaded）：全局最优要知道所有队列负载（协调成本高、有状态），二选一只看局部、无共享状态，在大规模下几乎免费地逼近最优。

## 并行性能的工程要点

- **Amdahl 定律**：串行比例为 $s$ 时，加速比上限 $1/(s+(1-s)/p)$——哪怕 1% 的串行段，无穷多核也只能加速 100 倍。优化应先消除串行瓶颈。
- **Gustafson 定律**是另一视角：问题规模随核数增长时，加速比可以近似线性，适用于可扩展数据规模的场景。
- 超线程（SMT）共享执行单元，对计算密集型任务加速有限（通常 1.1–1.3x），对阻塞多的任务更友好；
- 伪共享（false sharing）：不同核的变量落在同一 cache line，每次写都使对方缓存失效——性能骤降时用 perf c2c 排查，padding/对齐修复；
- 扩展性受限于共享资源：内存带宽、锁、allocator、NUMA 跨节点访问，并行度到一定程度后曲线先平后降；
- 并发正确性是另一维问题：数据竞争、死锁、内存序，同步原语见 [Lock 目录](/docs/CS/OS/Linux/Lock/README.md)。

## Links

- [Operating Systems](/docs/CS/OS/OS.md)
- [Linux 调度](/docs/CS/OS/Linux/proc/sche.md)
- [Go 并发模型](/docs/CS/Go/Concurrency/Concurrency.md)
- [Amortized Analysis](/docs/CS/Algorithms/Amortized.md)
- [Computer Organization](/docs/CS/CO/CO.md)

## References

1. [Arora, Blumofe, Plaxton - Thread Scheduling for Multiprogrammed Multiprocessors (Work-Stealing/ABP)](https://www.csd.uwo.ca/~mmorenom/CS433-CS9624/Resources/arora-blumofe-toc01.pdf)
2. [Mitzenmacher - The Power of Two Choices in Randomized Load Balancing](http://www.eecs.harvard.edu/~michaelm/postscripts/tpds2001.pdf)
