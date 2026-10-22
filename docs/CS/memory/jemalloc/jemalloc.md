## Introduction

jemalloc 是 2005 年起进入 FreeBSD libc 的通用 `malloc(3)` 实现，上游给自己定的两个目标是**避免碎片**与**可扩展的并发**。这两句听上去像宣传语，落到代码里却是两个彼此拉扯的约束：碎片要求把同尺寸的对象压进尽量少的页里，并发要求让不同线程尽量不碰同一个锁。jemalloc 的整套结构——尺寸类、slab、分片、线程缓存、页分配器——都可以读成这两条约束在不同层级上的折中。

本子树以 jemalloc `5.4.0`（tag `5.4.0`）为基线，按"机制差异最大的维度"切成九篇。它们不是功能清单的展开，而是同一条调用链在不同深度上的剖面，读者最好带着下面三条主线去看。

第一条，**按地址反查元数据是快慢路径真正的分界线**。`malloc` 快路径可以完全不碰元数据，`free` 不行——它只拿到一个指针，必须反推出这个指针属于哪个 slab、哪个尺寸类。这条反查链的代价决定了线程缓存能省掉多少工作，也决定了 `edata_t`、rtree、TSD 为什么长成现在这样。

第二条，**缓存里存的是"预测"，不是"空间"**。线程缓存猜"这个线程马上还会再要这个尺寸"，页分配器猜"这块脏页马上会被复用"。所有自适应代码——低水位、GC、decay 曲线——都是在用观测修正这个预测；而预测错了不会泄漏，只会退化成一次更慢的分配。

第三条，**归还是与分配相互独立的一条管线**。内存从 slab 回到页分配器、从 dirty 走到 muzzy 再交还内核，全程由 epoch 与后台线程推动，与"最后一次 `free` 何时发生"没有直接关系。把归还当成 `free` 的副作用，会同时读错延迟参数和 RSS 曲线。

## One Request, One Ladder

理解 jemalloc 最省力的办法是跟一个 41 字节的请求走完全程。第一站是 [Size Classes](/docs/CS/memory/jemalloc/Size_Classes.md)：所有尺寸类都被写成 `size = (1 << lg_base) + ndelta * (1 << lg_delta)` 的代数形式，组内四个等距类，于是"该用哪一类"退化成位运算，请求向上取整最多浪费一个组距。同一套代数还顺手决定了 slab 的大小——不是固定一页，而是页大小与该类 region 大小的最小公倍数，所以 448 字节的类独占 7 页，页内不留尾巴。

第二站是线程缓存。[Thread Caches](/docs/CS/memory/jemalloc/Tcache.md) 讲 `cache_bin` 这个后进先出的栈，以及一个容易读反的语义：`ncached_max` 是**上限而不是目标**，缓存靠低水位与六条调整规则自己找合适深度。命中就到此为止，一次栈指针移动就结束。

不命中时要落到 arena。[Arena Bins and Slabs](/docs/CS/memory/jemalloc/Arena_Bin_Slab.md) 讲 bin 如何用一张**反向增长**的 bitmap 跟踪空闲 region、为什么锁的等级是 leaf、以及 sharding 如何把一把 bin 锁切成多把——碎片与并发的第一处正面冲突就在这里解决。slab 用尽或整块空出时，才轮到 [Page Allocator](/docs/CS/memory/jemalloc/Page_Allocator.md)：PAC 与 HPA 两个后端，四种 ecache（dirty / muzzy / retained / pinned）各有自己的合并时机，fit 规则还要给"可切分尺寸"设上限，防止一次切小、永久变小。

再往上就是 `mmap` / `madvise` 与内核，那部分不在本子树展开。

## The Reverse Map Decides Where the Fast Path Ends

[Allocation Fast Path](/docs/CS/memory/jemalloc/Fastpath.md) 把最好情况拆成三步：一次移位加查表拿到尺寸类与 usize，一次减法比较判断有没有线程事件到期，一次栈指针移动取走对象。其中第三步之后什么也没有——这正是线程缓存存在的意义。

但 `free` 多出一步反查。这一步的技术核心在 [Address to Metadata Mapping](/docs/CS/memory/jemalloc/Address_Map.md)：`edata_t` 被强制 128 字节对齐，为的是把 rtree 叶子低 7 位腾出来放"尺寸类 + edata 指针"；`e_size_esn` 把尺寸与一个可辨识的序号塞进同一个字；rtree 的叶子在一次写入里同时完成"这是多大的对象"和"它的元数据在哪"。

两处细节最能说明这条链的设计压力。其一，`edata_t` 的对齐理由逐字写在 `include/jemalloc/internal/edata.h:21-25`，不是缓存行对齐的泛泛之谈，而是"让叶子空出低位"这一具体目的。其二，`rtree_leaf_elm_write` 的 `dependent` 参数是一份内存序契约——调用方保证"写 rtree 发生在指针可见之前"时用 RELAXED，面对任意指针时必须 ACQUIRE（`include/jemalloc/internal/rtree.h:171-180`）。快路径之所以敢省掉屏障，是因为分配路径自己满足了这份契约。

也正因为反查要花钱，线程缓存才值得存在；反过来，一旦指针带有采样标记或异常对齐，快路径就把请求整体交给慢路径统一处理，而不是在快路径里加分支。

## What Is Cached Is a Prediction, Not a Promise of Space

jemalloc 的每个缓存层都在回答同一个问题：**下一次还要不要这个尺寸**。答案不是固定的，而是被观测数据持续修正。

线程缓存侧的机制是低水位与 GC：`cache_bin_alloc_impl` 刻意用 `success` 而不是 `ret == NULL` 来判分支，又允许一次从空位读出但丢弃（`include/jemalloc/internal/cache_bin.h:382-424`），都是为了不让缓存命中付出流水线停顿的代价；而缓存的深度由命中率驱动，空闲过多就批量归还，不会无限膨胀。页分配器侧同样如此：dirty 池延迟合并，是因为注释判断"缓存很可能马上被复用"；muzzy 与 retained 当场合并，是因为它们不在关键路径上。

把"预测"这个词记住，能避免两类常见误读。第一，缓存里没有对象不代表内存已被归还，只代表这个线程暂时不打算再用它；第二，dirty 池里放着相邻的空闲 extent 却没有合并，是设计预期而非泄漏（见 Page Allocator 对 `delay_coalesce` 的说明）。

## Reclaim Is a Separate Pipeline

[Memory Reclaim and Decay](/docs/CS/memory/jemalloc/Decay_and_Purge.md) 是这九篇里最容易被跳过、但最影响线上表现的一篇。它的核心结论是：从"应用不再使用"到"内核收回物理页"之间隔着 dirty 与 muzzy 两个状态，每个状态的停留时间由一条**表驱动的衰减曲线**决定，而不是由某个定时器到点触发。

这条管线自己有两个推动者：分配路径上的几何计数 ticker，以及按最早截止时间唤醒的后台线程。两者刻意耦合——提前唤醒是被允许的，代价只是多算一次。真正归还动作是一条 `madvise` / `mmap` 阶梯，`pinned` extent 则完全不参与衰减。读延迟参数时如果把它当成 `free` 的延迟，就会同时误解"为什么 RSS 没降"和"为什么降得太快"。

## Two Surfaces That Cross Every Mechanism

剩下两篇不属于分配链路，但每个机制都要经过它们。

[Configuration and API](/docs/CS/memory/jemalloc/Config_and_API.md) 的主线是**三个生命周期**：`config.*` 编译期定型、`opt.*` 启动期投影且此后只读、少数 `arena.<i>.*` 与 `prof.*` 运行期可写。同一批旋钮经由 `MALLOC_CONF`、`/etc/malloc.conf` 等五个来源按固定顺序覆盖；`mallctl` 是一棵带类型的树而不是 switch；`mallocx` 家族被统一到同一个核心 `imalloc`，标志位只是显式旋钮。配置面最值得警惕的坑是"同一个已删除选项，走环境变量时静默忽略、走 `mallctl` 时返回 ENOENT"。

[Heap Profiling](/docs/CS/memory/jemalloc/Heap_Profiling.md) 的主线是采样**发生在分配之前**：是否采样、采多少，在拿到对象之前就已决定，因此剖析路径不会回头修正已经发生的分配。对象释放后进入 refcount 的 limbo，dump 是对快照的两趟遍历，最后还要对采样概率做反偏。这条链路解释了为什么开启 prof 会改变布局——被采样的分配会走页对齐的逃生通道。

## Version and Verification Notes

本子树的基线是 jemalloc `5.4.0`（tag `5.4.0`）。`路径:行号` 一律相对 jemalloc 仓库根，可回该 tag 复核。

本机源码树是单提交的浅克隆，且 `autom4te` / perl 缺失导致生成头文件 `jemalloc_internal_defs.h` 不可用，因此 `PAGE`、`LG_VADDR`、`SC_NSIZES`、`RTREE_HEIGHT`、`HUGEPAGE` 等宏**没有本地取值**。凡是依赖它们的数字，正文一律写成符号关系（例如"rtree 高度由 `RTREE_NSB` 决定"）而不给具体值；能给的整数都是源码里直接写死的常量。各篇末尾都有自己的 `## Version and Verification Notes`，那里列的未核实项是硬禁区，正文没有引用。

## Links

- [Memory](/docs/CS/memory/memory.md)
- [Garbage Collection](/docs/CS/memory/GC.md)
- [malloc](/docs/CS/C/malloc.md)
- [glibc](/docs/CS/C/glibc.md)
- [FreeBSD](/docs/CS/OS/unix/FreeBSD.md)

## References

1. [jemalloc](http://jemalloc.net/)
2. [jemalloc GitHub Repository](https://github.com/jemalloc/jemalloc)
3. [A Scalable Concurrent malloc(3) Implementation for FreeBSD](https://people.freebsd.org/~jasone/jemalloc/bsdcan2006/jemalloc.pdf)
