## Introduction

**Swap（交换）** 是 Linux 在物理内存不足时，把一部分**匿名页（anonymous page，如进程堆/栈，无磁盘文件做后盾）**写出到后备存储（交换分区或交换文件），以回收物理页框的机制。有文件后盾的页（page cache）内存紧张时可直接丢弃或回写原文件，不需要 swap；swap 主要解决的就是匿名页"无处可去"的问题。

交换空间本身不是内存大小的简单延伸——换出到磁盘的页再次被访问会触发 **major fault** 换入，延迟远高于内存，因此 swap 的意义更多是：承载不活跃匿名页、给突发内存压力留缓冲、避免过早 OOM、以及配合 cgroup/zswap 等做内存分层。相关的地址空间、页表与缺页背景见 [vm](/docs/CS/OS/Linux/mm/vm.md)，页缓存见 [PageCache](/docs/CS/OS/Linux/mm/PageCache.md)。

## Swap Area

交换后端可以是：

- **交换分区（swap partition）**：一个独立分区，`mkswap` 初始化、`swapon` 启用，性能最好；
- **交换文件（swapfile）**：普通文件作为交换空间，灵活但要求底层文件系统支持且尽量连续分配；
- **zswap / zram**：把页**压缩后放在内存里**（zram 是压缩内存块设备，zswap 是在真正写盘前的压缩前置缓存），用 CPU 换有效容量，云主机/无盘环境常见。

每个交换区由一组**槽位（swap slot）**组成，内核用 `swap_info_struct` 管理，记录设备/文件、槽位数量、空闲映射（cluster）、优先级。可启用多个交换区并按优先级/负载分布。

```bash
swapon -s                       # 查看当前交换区(/proc/swaps)
fallocate -l 2G /swapfile && chmod 600 /swapfile
mkswap /swapfile && swapon /swapfile
cat /proc/sys/vm/swappiness     # 0-100，权衡换匿名页 vs 回收文件页
```

## kswapd and Watermarks

回收由后台线程 **kswapd** 主动触发，每个 NUMA node 一个（下面是内核初始化代码，`mm/vmscan.c`；水位线、唤醒时机与 `shrink_lruvec` 扫描主干的完整展开见 [内存回收（Reclaim）](/docs/CS/OS/Linux/mm/Reclaim.md)）：

```c
// mm/vmscan.c
static int __init kswapd_init(void)
{
       int nid;

       swap_setup();
       for_each_node_state(nid, N_MEMORY)
              kswapd_run(nid);
       return 0;
}

module_init(kswapd_init)
```

每个 zone（DMA / DMA32 / Normal）维护水位线（watermark）：

- **WMARK_MIN**：最低，低于它连分配本身都要进入直接回收；
- **WMARK_LOW**：kswapd 被唤醒、开始异步回收的阈值；
- **WMARK_HIGH**：kswapd 回收到该水位即休眠。

两条回收路径：

1. **kswapd 后台回收（slowpath 之前）**：空闲页降到 low，kswapd 在后台把页补回 high，对分配延迟影响小；
2. **直接回收（direct reclaim）**：分配时空闲已低于 min，分配者自己进 `try_to_free_pages` 同步回收，是造成延迟毛刺的常见原因。

## LRU Page Reclamation

候选页由 **LRU 列表**组织，每个 node 上大致分：

- `LRU_INACTIVE_ANON` / `LRU_ACTIVE_ANON`：匿名页非活跃/活跃；
- `LRU_INACTIVE_FILE` / `LRU_ACTIVE_FILE`：文件页非活跃/活跃；
- 另有 `LRU_UNEVICTABLE`（被 mlock 等钉住、不可回收）。

回收倾向于从 **inactive** 列表取页，并通过 active/inactive 之间的提升（referenced 检测）逼近 LRU 语义（真正的实现是多次扫描 + "second chance"，并非严格栈式 LRU）。选择回收文件页还是匿名页由 **swappiness** 影响：

- swappiness 高 → 更愿意换出匿名页（走 swap）；
- swappiness 低（如 0/1）→ 尽量回收文件页（丢弃干净页或回写脏页）；
- 它是**权衡旋钮不是开关**，现代内核（cgroup v2）语义还包含对回收代价（IO、是否有交换区）的自适应。

## Swap Cache and Reclaim Path

换出不是直接写磁盘，中间有一层 **swap cache**（本质是以 `swp_entry_t` 为键的页缓存）：

1. 回收匿名页时，`add_to_swap` 分配 swap slot，把页加入 swap cache；
2. 页被标记为脏并回写到交换区（`swap_writepage`）；
3. 回写完成、页表项改成 **swap entry（非 present 的 PTE）** 后，页框才可释放；
4. 该 PTE 仍记录"这页在哪个交换区的哪个槽位"。

**换入（swap-in）**：进程访问到 present=0 但带 swap entry 的 PTE → 缺页异常 → `do_swap_page` 从交换区（或仍命中 swap cache）读回一个新页框，重建映射。若期间有多个进程共享同一换出页（如 fork 后），swap cache 还负责去重和正确的引用计数。

## Write Path

一次内存压力下的回收链路概括为：

```
分配失败/水位低
   → kswapd 或 direct reclaim (shrink_lruvec)
   → shrink_folio_list: 从 inactive LRU 取页
        ├─ 文件页: 干净则丢弃, 脏则回写原文件(page cache)
        └─ 匿名页: add_to_swap → swap cache → 回写 swap 区 → PTE 改 swap entry
   → 释放页框回伙伴分配器
```

这条路径与直接的页回写、writeback 线程以及块 IO 栈相互作用，高回收压力时大量 `swap_writepage` 会在磁盘（尤其机械盘/HDD）上造成明显卡顿。

## zram and zswap

为缓解换出到慢速设备的代价：

- **zram**：内核提供的压缩内存块设备，在其上建 swap，页被压缩存放在 RAM 中，容量换内存占用，适合无盘/容器/移动端；
- **zswap**：在普通 swap 之前插入一个压缩内存池，页先压缩进内存池，池满或必要时才"驱逐"到后端真正的 swap 设备，兼顾压缩收益与大容量后备；
- 二者都让"换出"尽量不触盘，把 swap 变成内存压缩分层。

## OOM and Swappiness

当回收速度跟不上、连 min 水位都无法满足时进入 **OOM（Out-Of-Memory）**，由 oom-killer 按 oom_score（占用、运行时间、`/proc/<pid>/oom_score_adj` 调整等）选择牺牲进程杀掉释放内存，打分公式与 `oom_reaper` 收割细节见 [OOM killer](/docs/CS/OS/Linux/mm/oom.md)。合理配置 swap/swappiness/zswap 的目的之一，就是避免在本可用冷页缓冲的场景下直接 OOM；但 swap 也不能无限掩盖真实内存不足，否则表现为长时间僵死（thrashing）而非快速失败。

cgroup v2 通过 `memory.swap.max`、`memory.high/low/min` 把这套回收/交换行为限制到单个容器，使每个控制组有独立的回收压力与交换配额（memcg 侧的记账对象、接口语义与层级保护见 [cgroup 内存控制（memcg）](/docs/CS/OS/Linux/mm/memcg.md)）。

## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)
- [vm (address space / page fault)](/docs/CS/OS/Linux/mm/vm.md)
- [Page Cache](/docs/CS/OS/Linux/mm/PageCache.md)
- [slab](/docs/CS/OS/Linux/mm/slab.md)
- [mempool](/docs/CS/OS/Linux/mm/mempool.md)
- [cgroup](/docs/CS/OS/Linux/cgroup.md)

## References

1. [Kernel Documentation: Swap Management](https://docs.kernel.org/mm/swap.html)
2. [Kernel Documentation: zswap](https://docs.kernel.org/admin-guide/mm/zswap.html)
3. [Kernel source: mm/vmscan.c](https://elixir.bootlin.com/linux/latest/source/mm/vmscan.c)
4. [Understanding the Linux Virtual Memory Manager (Mel Gorman)](https://www.kernel.org/doc/gorman/html/understand/)
