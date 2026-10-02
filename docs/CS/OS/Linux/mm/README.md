## Introduction

Linux 内存管理维护的是三个对象之间的关系：**内存介质**（RAM + MMIO）、**物理地址空间**、**虚拟地址空间**。把这三者打通的，是一条贯穿内核上下的链路——开机先**探测**出有哪些物理内存，再把它们**组织**成 node / zone / page，交给 **buddy** 按页分配；内核用 **slab / mempool** 在其上切出字节级对象与预留担保，用户进程则通过 **虚拟地址空间 + page fault** 按需拿页，文件数据统一住进 **页缓存**；空闲页吃紧时由 **回收** 拿回来，实在救不回来才触发 **OOM** 杀进程；而 **memcg** 作为横切机制，把这条链沿 cgroup 层级整段切开记账与限额。

本页是 `mm/` 目录的**链路总图**：按上面这条因果顺序串联各篇笔记，讲清每一环节"为什么要它、解决什么问题、与相邻环节什么关系"。需要细节时再进入对应笔记。

> 物理内存并非"一页页"地躺在板上，页（struct page）只是内核做的逻辑划分；同理 MMIO 把设备寄存器/显存也映射进物理地址空间，所以物理地址空间里既含 RAM，也含外设（见 `/proc/iomem`）。

## 起点：开机探测与早期内存

链路的第一环发生在 boot。内核刚被加载时，连"机器上插了多少内存、内存在哪些物理地址区间"都不知道，必须先向固件询问——x86 上通过 **e820** 拿到一张"可用 / 保留 / 坏页"的内存地图。这一步的展开见 [内核启动与内存初始化](/docs/CS/OS/Linux/mm/memory.md) 的 [boot](/docs/CS/OS/Linux/mm/memory.md?id=boot)（`detect_memory` / `detect_memory_e820`）。

需要特别澄清这篇笔记的**身份**：[memory.md](/docs/CS/OS/Linux/mm/memory.md) 记录的是 `detect_memory` / e820 / `mem_init` / `paging_init` / `kmalloc` 等**早期启动路径**，是链路的"序章"，**并非"内存管理总入口"**。全站旧链接把它当 "Linux Memory" 引用是历史错配；本页才是导航枢纽，物理内存运行时主线请以 [pm.md](/docs/CS/OS/Linux/mm/pm.md) 为准。启动期 zone、page、kmalloc 的初始化流程归属见该篇的 [init](/docs/CS/OS/Linux/mm/memory.md?id=init)。

## 物理内存主线：组织与按页分配

探到内存之后，内核要把"真实硬件内存"组织成可管理的结构，这是整条链的基石，集中在 [pm.md](/docs/CS/OS/Linux/mm/pm.md)（约 1700 行）。

第一步是按 **NUMA node** 切分。传统 SMP 下所有 CPU 抢总线、扩展受限，Linux 于是把内存切成 node，每个 node 用一个 `pg_data_t` 描述本地布局；UMA 机器上整个系统就只有一个 node。为什么需要 node？因为内存访问延迟不等价——跨 socket 的远端内存比本地慢，调度与分配都得知道"这块内存在哪个 node 上"。详见 [node](/docs/CS/OS/Linux/mm/pm.md?id=node)。

同一 node 内还要再分 **zone**，原因是**硬件对物理地址有硬性限制**：老设备做 DMA 只能访问低 4G（甚至低 16M）。于是 node 内划出 `DMA` / `DMA32` / `Normal`（64 位机通常只剩 DMA32 与 Normal 有意义），把"物理地址能力不同"的页分组，才能满足"这块内存必须能被网卡 DMA 到"这类约束。zone 与 `struct zone`（水位线、lowmem_reserve、冷热页链表、free_area）的完整定义见 [zone](/docs/CS/OS/Linux/mm/pm.md?id=zone)。

每个 zone 管理一串物理页，每页一个 `struct page`。问题是物理内存不一定连续（热插拔、空洞、MMIO 都会制造空洞），内核不能用"页帧号下标数组"硬映射所有 page，这引出 **memory model**：[FLATMEM](/docs/CS/OS/Linux/mm/pm.md?id=flatmem)（连续平板）、[DISCONTIGMEM](/docs/CS/OS/Linux/mm/pm.md?id=discontigmem)（按 node 离散）、[SPARSEMEM](/docs/CS/OS/Linux/mm/pm.md?id=sparsemem)（按 section 稀疏，6.x 默认，支撑热插拔与巨大地址空间），回答"page 数组怎么和物理布局解耦"。

介质就绪、分配器才能上岗，但**引导早期还没有伙伴系统**——临时由 [memblock](/docs/CS/OS/Linux/mm/pm.md?id=memblock) 接管 boot 期分配（记录可用/保留区间，边启动边收缩），等把内存交给伙伴系统后退居二线。运行时主力是 **buddy 伙伴系统**（[buddy](/docs/CS/OS/Linux/mm/pm.md?id=buddy)）：以**页**为最小单位，用 2 的幂次空闲块链表解决外部碎片，是内核所有"要物理连续内存"请求的源头——`vmalloc`、slab、内核栈要的页，最终都从 buddy 来。

分配路径本身分两段：快速路径 [alloc_pages](/docs/CS/OS/Linux/mm/pm.md?id=alloc_pages) 在本地 zone 找够水位就返回；不够则进入慢速路径 [alloc_pages_slowpath](/docs/CS/OS/Linux/mm/pm.md?id=alloc_pages_slowpath)——唤醒 kswapd、直接回收、[内存压缩](/docs/CS/OS/Linux/mm/Compaction.md)、[NUMA 平衡](/docs/CS/OS/Linux/mm/Numa.md)，逐级升级直到 OOM。释放侧见 [free](/docs/CS/OS/Linux/mm/pm.md?id=free)。理解这条快慢分叉，才看得懂"为什么分配会卡住、为什么进程被杀"——它正是后面 [Reclaim](/docs/CS/OS/Linux/mm/Reclaim.md) 与 [oom](/docs/CS/OS/Linux/mm/oom.md) 两环的入口。

## 内核侧：字节级对象与紧急担保

buddy 只给整页，但内核的需求以**字节**为单位——为一个 20 字节的 `task_struct` 分配一整页是灾难。于是有了建在 buddy 之上的 [slab](/docs/CS/OS/Linux/mm/slab.md)：把整页再切成字节级对象池，并缓存常用对象的初始化状态、做 slab 着色提高 CPU cache 利用率。`task_struct` / `mm_struct` / `struct file` / `struct socket` 等频繁创建释放的对象都走专属 slab。现代内核常用实现是 **slub**（精简元数据、针对多核与 NUMA 优化），嵌入式小内存场景用 **slob**。主干是 [kmem_cache](/docs/CS/OS/Linux/mm/slab.md?id=kmem_cache) 与通用入口 [kmalloc](/docs/CS/OS/Linux/mm/slab.md?id=kmalloc)。

slab 解决"省"，但解决不了"绝不能失败"。块设备层做 I/O 时，请求对象的分配**必须成功、又不能触发可能睡眠的回收**，否则系统卡死。这就需要在 slab 之上再叠一层预留担保 [mempool](/docs/CS/OS/Linux/mm/mempool.md)：核心是 `min_nr` 个常驻保底元素，[mempool_alloc](/docs/CS/OS/Linux/mm/mempool.md?id=mempool_alloc) 在底层分配失败时才动用预留池，[mempool_free](/docs/CS/OS/Linux/mm/mempool.md?id=mempool_free) 则优先把元素补回池中自愈，从而保证前向进展。这是典型的"用空间换确定性"。

## 用户侧：虚拟地址空间与按需分页

物理页是稀缺的全局资源，用户进程并不直接持有它，而是各自拥有一套独立的**虚拟地址空间**，由 [vm.md](/docs/CS/OS/Linux/mm/vm.md) 描述。每个进程一个 [mm_struct](/docs/CS/OS/Linux/mm/vm.md?id=mm_struct)，记录用 [VMA](/docs/CS/OS/Linux/mm/vm.md?id=vma)（`vm_area_struct`）切出的各段区间（代码/堆/栈/映射区）；VMA 早期用红黑树、6.1 起改用 [maple tree](/docs/CS/OS/Linux/mm/maple_tree.md) 索引（`mm_struct->mm_mt`），配套 `find_vma` / `vma_iter_*` 管理；exec 装载 ELF 时由 [load binary](/docs/CS/OS/Linux/mm/vm.md?id=load-binary) 建立初始布局，内核自己的虚拟地址空间则是写死的 [kernel vm](/docs/CS/OS/Linux/mm/vm.md?id=kernel-vm)。

关键在于 VMA 只是"地址区间的约定"，背后**未必有物理页**。进程第一次访问某地址时触发 [page fault](/docs/CS/OS/Linux/mm/vm.md?id=page-fault)，内核才在异常处理里分配物理页、建立页表（demand paging）；写时复制由 `do_wp_page` 处理。内核态不保证连续、只保证虚拟连续的 [vmalloc](/docs/CS/OS/Linux/mm/vm.md?id=vmalloc) 也在这一篇。

上面反复出现"建立页表"，但页表本身一直没单独讲过——它才是把 VMA 的约定**兑现成一次真实地址翻译**的机制。[pagetable.md](/docs/CS/OS/Linux/mm/pagetable.md) 补上这一环：虚拟地址被切成 4~5 段逐级索引（4 级下 PGD/PUD/PMD/PTE 各 9 位加 12 位页内偏移），每级一张 512 项的表恰好占一页，因此页表页能像普通页一样从 buddy 来；表项里硬件位与软件位共享同一条 64 位（`PROTNONE` 借用 `GLOBAL` 的 bit、`SAVED_DIRTY` 是为 CET 新增的），而页表页自己用 [ptdesc](/docs/CS/OS/Linux/mm/pagetable.md?id=页表页是特殊的页：ptdesc) 与 `struct page` 逐字段对齐。页表不是一次建好的——缺页时由 [逐级 alloc](/docs/CS/OS/Linux/mm/pagetable.md?id=惰性生长：缺页时逐级建表) 按需生长；改动页表后必须走 [mmu_gather](/docs/CS/OS/Linux/mm/pagetable.md?id=mmu_gather：批量-tlb-失效) 把"摘除 → TLB 失效 → 释放"三步批量拆开，否则会留下能读到别人数据的残留翻译。

用户程序主动建立映射的系统调用入口是 [mmap](/docs/CS/OS/Linux/mm/mmap.md)：`ksys_mmap_pgoff` → `do_mmap` → `mmap_region`，把一段虚拟区域接到**匿名页**或**文件**上。接匿名页就是绕开 malloc 直接拿内存，接文件则让进程通过缺页直接读写 [页缓存](/docs/CS/OS/Linux/mm/PageCache.md)，省掉 read/write 的一次拷贝。解除映射见 [munmap](/docs/CS/OS/Linux/mm/mmap.md?id=munmap)。

## 文件数据的家：页缓存

磁盘和内存差着几个数量级，Linux 用 [PageCache](/docs/CS/OS/Linux/mm/PageCache.md) 把读过/写过的文件页缓存到内存里。它以 `address_space` 为索引挂在 inode 上，是 buffered I/O 与 mmap 文件映射共同的落点：读时不在缓存就分配新页、触发预读从磁盘填充；写时先改缓存页、把落盘延迟（write back），从而合并多次小写。`/proc/meminfo` 里的 `Active(file)` / `Inactive(file)` 就是 file-backed 页。

页缓存和前面两环咬合得很紧：mmap 访问文件时的缺页由它来满足，而缓存页本身也是**回收**最重要的对象——干净页可直接丢弃，脏页必须先回写。这种"可被回收"正是它能放心占用大量空闲内存的前提。

## 空闲吃紧：内存回收

分配慢路径发现 free 页低于水位，就进入 [Reclaim](/docs/CS/OS/Linux/mm/Reclaim.md) 这一环。每个 zone 维护 `MIN / LOW / HIGH` 三条[水位线](/docs/CS/OS/Linux/mm/Reclaim.md?id=水位线与-kswapd)：低于 LOW 唤醒后台 **kswapd** 异步回收，低于 MIN 则迫使申请进程直接回收（direct reclaim，这正是分配"卡住"的原因）。回收对象在 [LRU 链表](/docs/CS/OS/Linux/mm/Reclaim.md?id=lru-链表与页面老化)上按"活跃/不活跃、匿名/文件"老化排序，扫描主干经 `try_to_free_pages` / `shrink_lruvec` / `shrink_list` 进入逐页决策。

单页去留在 [shrink_folio_list](/docs/CS/OS/Linux/mm/Reclaim.md?id=shrink_folio_list：单页去留的决策树) 这棵决策树里判定：文件干净页直接丢、脏页回写、匿名页换出到 [Swap](/docs/CS/OS/Linux/Swap.md)、被引用的页激活或保留。除了页，[shrinker](/docs/CS/OS/Linux/mm/Reclaim.md?id=shrink_slab-与-shrinker) 机制还让 slab/dentry/inode 缓存等内核对象注册自己的回收回调。回收把页还给 buddy，分配才得以重试成功——它是 buddy 慢路径与 OOM 之间的关键缓冲。

传统 active / inactive LRU 在大内存机器上扫描与链表开销高、冷热判定粗糙，6.1 起可选 [MGLRU 多代 LRU](/docs/CS/OS/Linux/mm/MGLRU.md)：把页按"代"组织、直接批量走查页表读 accessed 位判冷热，回收更省、误伤工作集更少，可与传统回收模型二选一启用。

## 碎片整理：内存压缩

回收解决"空闲页不够"，但还剩一种情况——**空闲页总量够、却凑不出物理连续的大块**：长期运行让空闲页以 order-0 散落。驱动的大 DMA 缓冲、THP 大页都要物理连续，于是慢路径在水位允许时进入 [Compaction](/docs/CS/OS/Linux/mm/Compaction.md)。它用两个**相向扫描器**：低地址端隔离可移动的占用页、高地址端隔离空闲页，再把前者搬到后者上，空闲页因此在一端聚集出连续块；页的数据一页不少，只改物理排布。压缩既由后台 [kcompactd](/docs/CS/OS/Linux/mm/Compaction.md?id=kcompactd：后台规整) 异步做，也可在分配中同步直接做，并支持按碎片指数触发的[主动压缩](/docs/CS/OS/Linux/mm/Compaction.md?id=主动压缩：proactive-compaction)。压缩需要空闲页落脚，所以常与回收前后配合——先回收出余量、再压缩。

## 局部性优化：NUMA 平衡

[node](/docs/CS/OS/Linux/mm/pm.md?id=node) 切分只给了"位置"，但任务和它的数据未必同处一个 node，会产生大量代价更高的远端访问。[Numa](/docs/CS/OS/Linux/mm/Numa.md) 让二者尽量靠拢：内核侧的 **AutoNUMA** 周期性把页表标记为不可访问，任务一旦真访问就触发 hinting fault，内核据此把页迁移到当前 node（`do_numa_page` / `migrate_misplaced_folio`），并用 `task_numa_fault` 的评分反向把任务迁到数据所在的 node，形成双向收敛；用户也可用 **mempolicy**（`MPOL_BIND` / `INTERLEAVE` / `PREFERRED` 等）显式指定放置。分配时本地 node 不足是"先本地回收还是直接用远端"由 `zone_reclaim_mode` 决定——内存充裕的机器上盲目开启本地回收，是 direct reclaim 抖动的常见根因。

## 最后兜底：OOM Killer

如果 kswapd、直接回收、内存压缩、NUMA 平衡都救不回来、连 MIN 水位都满足不了，链路只能走到 [oom](/docs/CS/OS/Linux/mm/oom.md)。`out_of_memory` 经 [select_bad_process / oom_badness](/docs/CS/OS/Linux/mm/oom.md?id=select_bad_process-与-oom_badness) 给各进程打分（RSS + swap + 页表，再叠加用户可调的 `oom_score_adj`），选出 victim 杀掉，再由 [oom_reaper](/docs/CS/OS/Linux/mm/oom.md?id=oom_reaper) 异步收割其内存尽快解困。`oom_score_adj` 正是 K8s 三种 QoS 在内核里的来路；容器配额到顶则触发 [memcg 局部 OOM](/docs/CS/OS/Linux/mm/oom.md?id=memcg-oom)，只杀组内进程、不波及整机。

## 横切机制：按 cgroup 记账与限额

上述整条链默认管理的是"整机一台"的内存，[memcg](/docs/CS/OS/Linux/mm/memcg.md) 把它沿 cgroup 层级整段切开。它在三个着力点改写链路：给每个 `page` 打上归属（`page->memcg_data`）、为每组维护独立的 per-memcg lruvec、在分配关卡用 `__GFP_ACCOUNT` 记账。由此[页与内核对象](/docs/CS/OS/Linux/mm/memcg.md?id=记账：页与内核对象)两条路径都按组计费，限额通过 [memory.max / high / low / min](/docs/CS/OS/Linux/mm/memcg.md?id=限额接口（cgroup-v2）) 表达，超限有[三条路径](/docs/CS/OS/Linux/mm/memcg.md?id=超限之后：三条路径)：到 `high` 节流回收、到 `max` 组内直接回收、仍不够则组内 OOM。`memory.stat` / `memory.events` 是排障口径，与 K8s QoS 的映射见该篇；通用机制对照 [cgroup](/docs/CS/OS/Linux/cgroup.md)。

## 板块现状与缺口

- ✅ **boot 探测**：[memory.md](/docs/CS/OS/Linux/mm/memory.md)——e820 / `mem_init` / `paging_init` / 早期 kmalloc 启动路径完整，定位为序章而非总入口。
- ✅ **物理内存主线**：[pm.md](/docs/CS/OS/Linux/mm/pm.md)——node / zone / 内存模型 / memblock / buddy / alloc_pages（fast+slow）/ free 自洽。
- ✅ **内核对象与担保**：[slab.md](/docs/CS/OS/Linux/mm/slab.md)（slab/slub/slob、kmem_cache、kmalloc/kfree）与 [mempool.md](/docs/CS/OS/Linux/mm/mempool.md)（三级降级、前向进展）均已独立成篇。
- ✅ **用户侧**：[vm.md](/docs/CS/OS/Linux/mm/vm.md)（mm_struct / VMA / page fault / vmalloc）与 [mmap.md](/docs/CS/OS/Linux/mm/mmap.md)（建立/解除映射）完整。
- ✅ **页表**：[pagetable.md](/docs/CS/OS/Linux/mm/pagetable.md)——把 VMA 兑现成翻译的底层机制：4 级/5 级布局与运行时 `pgdir_shift`、层级折叠（`__PAGETABLE_*_FOLDED`）、表项位与软件位复用、页表页的 `ptdesc` 表示与 `pagetable_*_ctor`、缺页时逐级惰性生长、`free_pgtables` 递归下降、`mmu_gather` 批量 TLB 失效与页表页延迟释放、`delayed_rmap`、`CONFIG_PT_RECLAIM` 页表回收。
- ✅ **VMA 的索引结构**：[maple_tree.md](/docs/CS/OS/Linux/mm/maple_tree.md)——区间树替换 rbtree 的完整机制：节点四种形态与位编码、`ma_state` 游标、RCU 无锁读与死节点检测、写路径九种 store 分类、gap 空洞记账与 `mas_empty_area()`。
- ✅ **缓存 / 回收 / OOM**：[PageCache.md](/docs/CS/OS/Linux/mm/PageCache.md)、[Reclaim.md](/docs/CS/OS/Linux/mm/Reclaim.md)、[oom.md](/docs/CS/OS/Linux/mm/oom.md) 三块均已从早期长笔记中拆出，独立权威。
- ✅ **碎片 / 局部性 / 回收模型增强**：[Compaction.md](/docs/CS/OS/Linux/mm/Compaction.md)（双扫描器、kcompactd、主动压缩）、[Numa.md](/docs/CS/OS/Linux/mm/Numa.md)（AutoNUMA、mempolicy、zone_reclaim_mode）、[MGLRU.md](/docs/CS/OS/Linux/mm/MGLRU.md)（多代 LRU、页表老化）均已独立成篇。
- ✅ **横切**：[memcg.md](/docs/CS/OS/Linux/mm/memcg.md)——记账、限额、三档超限路径、K8s 映射完整。
- ✅ **对外借出用户页**：[gup.md](/docs/CS/OS/Linux/mm/gup.md)——GUP 的两条路径（慢路径 `follow_page_mask` / `faultin_page`、快路径关中断无锁遍历与"先 pin 再验证 PTE"的双向协议）、`FOLL_*` 完整标志表与 `is_valid_gup_args` 的四条不变量、`GUP_PIN_COUNTING_BIAS` 的 refcount 高位编码与 `folio_maybe_dma_pinned` 的模糊语义、pin 对 fork / 迁移 / 回收 / KSM / COW / soft-dirty 的反作用、`FOLL_LONGTERM` 的落点合规与迁移重试契约。
- ⏭️ **后续可选**：分层内存的 demote/promote、异构内存（CXL / HMAT）的源码级展开——这些与 NUMA、回收强相关，留作下一阶段。

## Links

- [Linux 内核总览](/docs/CS/OS/Linux/Linux.md)
- [Swap 交换](/docs/CS/OS/Linux/Swap.md)
- [cgroup](/docs/CS/OS/Linux/cgroup.md)

## References

1. [一步一图带你深入理解 Linux 物理内存管理](https://mp.weixin.qq.com/s?__biz=Mzg2MzU3Mjc3Ng==&mid=2247486879&idx=1&sn=0bcc59a306d59e5199a11d1ca5313743&chksm=ce77cbd8f90042ce06f5086b1c976d1d2daa57bc5b768bac15f10ee3dc85874bbeddcd649d88&cur_album_id=2559805446807928833&scene=189#wechat_redirect)
2. [Linux Memory Management — kernel.org documentation](https://www.kernel.org/doc/html/latest/mm/index.html)
