## Introduction

透明大页（Transparent Huge Pages, THP）让内核在**不修改应用程序**的前提下，把原本以 4 KiB 页为单位的映射改用 2 MiB（PMD 级）甚至 1 GiB（PUD 级）的大页来翻译。它解决的问题很直接：**TLB 容量有限**，4 KiB 页下大片连续虚拟地址要占掉大量 TLB 项，访存密集程序因此频繁 TLB miss。把映射粒度放大到 2 MiB，同样的 TLB 项能覆盖 512 倍的地址范围。

THP 与 HugeTLB 是两套不同机制：HugeTLB 走 `MAP_HUGETLB` / `hugetlbfs`，页大小由预留的 hstate 决定、须显式预留；THP 对应用**透明**，由内核在缺页与后台折叠时自动决定，物理内存按需从 buddy 索取。本篇聚焦 THP；HugeTLB 的页表共享等位级机制见 [页表](/docs/CS/OS/Linux/mm/pagetable.md)。THP 在整条 MM 链路里的位置是：依赖 [buddy](/docs/CS/OS/Linux/mm/pm.md?id=buddy) 提供连续大块、依赖 [Compaction](/docs/CS/OS/Linux/mm/Compaction.md?id=kcompactd-background-compaction) 在碎片时造出连续块、把 PMD 当作大页叶子、并对 [Reclaim](/docs/CS/OS/Linux/mm/Reclaim.md) / [NUMA 平衡](/docs/CS/OS/Linux/mm/Numa.md) / 迁移施加"大页难拆"的反作用。

## Compound Pages and the Head/Tail Representation

THP 的底层载体是**复合页（compound page）**：一个 order-N 的连续物理块，由一个 head folio 带着 2^N−1 个 tail page 组成。内核不为此新造结构，而是复用 `struct page` 的字段区分头尾：

- `PG_head`（`page->flags` 的 bit 6，`include/linux/page-flags.h:100`）：head 页置此位，`PageHead()` 读它；
- `PageTail()`（同文件 `:315`）的语义**编码在 `page->page_type` 的 bit 0**（`:230` / `:278` 注释 "Bit 0 encodes PageTail()"），即尾页不用 `flags`、而用 `page_type` 区分；
- `compound_head()` 沿复用字段找到 head，一个 tail page 能 O(1) 走到它所属的 head folio。

这是 folio 化之后 THP 的物理基础：应用看到的是 `folio`，内核在 `page` 层用 head/tail 位把它拆回 4 KiB 的页来做某些逐页操作（如 `split_huge_page`）。

## anon THP: On-Demand Allocation at Fault

匿名映射的 THP 在**缺页时按需分配**。当访问一个尚未映射的匿名地址、且 VMA 允许 THP 时，`handle_pte_fault` → `create_huge_pmd`（`mm/memory.c:6200`）→ `do_huge_pmd_anonymous_page()`（`mm/huge_memory.c:1519`）尝试直接分配一个 order-9（2 MiB）的 folio：

- 前置判断 `thp_vma_suitable_order(vma, haddr, PMD_ORDER)`（`:1525`）确保地址对齐到 PMD、且 VMA 足够大；
- 成功则建立 PMD 叶子映射；随后 `khugepaged_enter_vma(vma, ...)`（`:1530`）把这个 VMA 登记给后台折叠线程，兜底下一次未必能拿到大页的情况；
- 若 buddy 一时给不出连续 2 MiB（见 [Compaction](/docs/CS/OS/Linux/mm/Compaction.md?id=kcompactd-background-compaction)），缺页路径**退化到 4 KiB 普通缺页**，不阻塞进程——这正是 `defrag` 策略要控制的（见下）。

### huge zero page

读缺页（非写）且未禁用 zeropage 时，内核不分配私有零页，而是复用全局**大零页** `huge_zero_folio`（`huge_memory.c:82`，由 `mm_get_huge_zero_folio()` `:263` / `:360` 取得），经 `set_huge_zero_folio()`（`:1507`）写入 PMD。它带引用计数 `huge_zero_refcount` 与名为 `"thp-zero"` 的 shrinker（`:342` / `:319`），在无引用时释放——除非开了 `CONFIG_PERSISTENT_HUGE_ZERO_FOLIO`。写缺页才走 `__do_huge_pmd_anonymous_page()`（`:1381`）真正分配可写 folio。

## khugepaged: Background Collapse

缺页时若只能拿到 4 KiB 页（因为当时没连续块、或 `defrag=never`），已建立的 PTE 映射不会自动变大。khugepaged 线程周期性地把**一段已存在的 4 KiB 映射折叠（collapse）成 PMD 大页**，弥补这一缺口。

`collapse_huge_page()`（`mm/khugepaged.c:1272`）是核心：分配一个 order-9 folio，经 `__collapse_huge_page_swapin`（`:1141`）→ `__collapse_huge_page_isolate`（`:661`，把各 PTE 页锁进新 folio 并置 RO）→ `__collapse_huge_page_copy`（`:927`，拷数据）→ 用 `set_huge_pmd` 一次性把旧 PTE 替换为 PMD 叶子。

折叠节奏由几个 sysfs 参数控制（默认值均来自 v7.2.7 源码）：

| 参数 | 默认 | 含义 |
| :--- | :--- | :--- |
| `khugepaged_pages_to_scan` | `HPAGE_PMD_NR * 8`（= 4096 页） | 每轮扫描的页上限（`:476`） |
| `khugepaged_scan_sleep_millisecs` | `10000` ms | 每轮之间的休眠（`:79`） |
| `khugepaged_alloc_sleep_millisecs` | `60000` ms | 分配失败后的休眠（`:81`） |

主循环 `collapse_scan_mm_slot()`（`:2836`）每轮扫 `khugepaged_pages_to_scan` 个页（`:2968`），休眠用 `khugepaged_scan_sleep_millisecs`（`:3017`）。除 anon 折叠外，khugepaged 还支持 file 折叠 `collapse_file()`（`:2236`）与 mTHP 折叠 `mthp_collapse()`（`:1483`）。

> 启动条件：内存小于 512 MiB 时 `hugepage_init()`（`huge_memory.c:1085`）直接禁用并不启动线程；否则由 `start_stop_khugepaged()`（`:1090`）在 `hugepage_enabled()`（`khugepaged.c:512`）为真时 `kthread_run` 拉起。

## file and shmem THP and Large Folios

文件映射的 THP 与 anon 的"缺页 / PMD 级"思路不同，它是 **readahead 时按需分配 large folio**：`filemap` 路径上，若 `mapping_large_folio_support(mapping)`（`include/linux/pagemap.h:507`，本质 `mapping_max_folio_order(mapping) > 0`）为真，就放大分配 order（`filemap.c:3340`）。匿名映射恒支持 large folio（`pagemap.h:511` 有 WARN），但文件页的 large folio **无全局 always 开关**，完全由 readahead 决策驱动——这层机制也是 [PageCache](/docs/CS/OS/Linux/mm/PageCache.md) 现在以 folio 为中心的原因之一。

shmem / tmpfs 的 THP 由 `shmem_enabled` 控制，取值 `never/always/within_size/advise/deny/force`（`shmem.c:4441`）；**默认 `SHMEM_HUGE_NEVER`**（Kconfig `mm/Kconfig:895` / `:940`）。

### multi-size THP (mTHP)

v7.2 已落地**多尺寸 THP**：除 PMD 级 2 MiB 外，内核按 order 为每个尺寸建一个 `hugepages-<size>kB` sysfs 目录（`thpsize_create`，`huge_memory.c:888`），内含该尺寸的 anon `enabled`（取值 `always/inherit/madvise/never`，`inherit` 继承全局）与 shmem `shmem_enabled`、统计组，以及 `khugepaged/` 子目录。这意味着可以只开 64 KiB 大页而保留 4 KiB 基页，兼顾 TLB 收益与内部碎片。

## sysfs ABI and Tunables

顶层接口在 `/sys/kernel/mm/transparent_hugepage/`，由 `hugepage_attr[]`（`huge_memory.c:619`）定义：

- `enabled`：全局 anon THP 开关，取值 `always/madvise/never`（`:418`）；每尺寸另有独立的 `hugepages-<size>kB/enabled`（取值多一个 `inherit`）。
- `defrag`：决定分配大页时**是否、以及如何阻塞去造连续块**，取值与 `vma_thp_gfp_mask()`（`huge_memory.c:1480`）的映射：

  | defrag 取值 | 行为 |
  | :--- | :--- |
  | `always` | `GFP_TRANSHUGE`，**同步 direct compaction**（`:1485`） |
  | `defer` | `GFP_TRANSHUGE_LIGHT \| __GFP_KSWAPD_RECLAIM`，仅唤醒 kcompactd，快速失败 |
  | `defer+madvise` | madvised VMA 才加 `__GFP_DIRECT_RECLAIM`（`:1493`） |
  | `madvise` | 仅 madvised VMA 允许阻塞（`:1499`） |
  | `never` | `GFP_TRANSHUGE_LIGHT`，绝不阻塞 |

  默认显示 `[madvise]`（初始化置 `DEFRAG_REQ_MADV`，`:533`）。`defrag` 直接决定 THP 与 [Compaction](/docs/CS/OS/Linux/mm/Compaction.md?id=kcompactd-background-compaction) 的耦合强度——`always` 下每次缺页都可能触发同步压缩。
- `use_zero_page`：是否用 [huge zero page](#huge-zero-page)；默认开（`USE_ZERO_PAGE_FLAG`）。
- `shmem_enabled`：见上。
- `shrink_underused`（`split_underused_thp`，`:616`）：定期拆分利用率低的大页，回收内部碎片。

`MADV_HUGEPAGE` / `MADV_NOHUGEPAGE`（`mm/madvise.c:1424`）在 VMA 上置 / 清 `VM_HUGEPAGE` / `VM_NOHUGEPAGE`（`include/linux/mm.h:437`），让 `defrag=madvise` 或 `enabled=madvise` 时只对特定 VMA 生效。

## Boot Parameters

没有名为 `THP=` 的启动参数。真实的两个是：

- `transparent_hugepage=`（[`__setup`](https://www.kernel.org/doc/html/latest/admin-guide/mm/transhuge.html)，`huge_memory.c:1135`）：仅接受 `always/madvise/never`，在引导早期定全局 `enabled`；
- `thp_anon=`（[`setup_thp_anon`](https://www.kernel.org/doc/html/latest/admin-guide/mm/transhuge.html)，`huge_memory.c:1138`）：按尺寸区间 + `always/inherit/madvise/never` 配置 mTHP，例如 `thp_anon=64K-2M:always`。

> 注意：HugeTLB 的尺寸参数 `hugepagesz=` / `hugepages=` 属于 HugeTLB，**不是** THP。

## Interaction with the MM Chain

THP 不是孤立特性，它对上下游都有强反作用：

- **buddy / Compaction**：PMD 级 THP 要 order-9（2 MiB）连续块；`HPAGE_PMD_ORDER = HPAGE_PMD_SHIFT - PAGE_SHIFT`（`huge_mm.h:117`），x86-64 上 `PMD_SHIFT=21` ⇒ order 9。`CONFIG_TRANSPARENT_HUGEPAGE` 直接 `select COMPACTION`（`mm/Kconfig:849`），`vma_thp_gfp_mask` 按 `defrag` 请求同步 / 异步压缩。碎片多时靠 [Compaction](/docs/CS/OS/Linux/mm/Compaction.md?id=kcompactd-background-compaction) 先造块，khugepaged 再折叠。
- **pagetable**：THP 用 PMD 叶子（非规范 PTE 表），`pmd_trans_huge()`（`include/linux/pgtable.h:2087`）判断。`ptdesc` 里的 `pt_share_count`（`include/linux/mm_types.h:591`）专用于 **HugeTLB 共享 PMD 页表**（THP 与 HugeTLB 共用 PMD 大页概念），细节见 [pagetable](/docs/CS/OS/Linux/mm/pagetable.md?id=page-table-pages-are-special-pages-ptdesc)。
- **Reclaim / NUMA / 迁移**：大页难迁移、拆分贵。`split_huge_page_to_list_to_order()`（`huge_memory.c:4310`）是核心拆分路径；PMD 级 `split_huge_pmd_locked`（`:3358`）/ `__split_huge_pmd`（`:3366`）在 MADV_DONTNEED（`madvise_dontneed_single_vma` `:859`，经 `zap_huge_pmd`）、unmap、[NUMA 平衡](/docs/CS/OS/Linux/mm/Numa.md) 的 `numa_rebuild_large_mapping`（`mm/memory.c:6187`）处被调用——大页在 NUMA 迁移前常要先拆回 4 KiB。这解释了为什么开了 THP 的机器在内存紧张或 NUMA 重平衡时会出现短暂的 split 抖动。

## Observability

- `/proc/meminfo`：`AnonHugePages:`（`fs/proc/meminfo.c:142`）、`ShmemHugePages:`（`:144`）给出当前驻留的大页量。
- `/proc/vmstat` 的 `thp_*` 事件（`include/linux/vm_event_item.h:87`）：`THP_FAULT_ALLOC` / `THP_FAULT_FALLBACK`（分配成败）、`THP_COLLAPSE_ALLOC`、`THP_SPLIT_PAGE` / `THP_SPLIT_PMD` / `THP_SPLIT_PUD`、`THP_ZERO_PAGE_ALLOC` 等。
- `/sys/kernel/mm/transparent_hugepage/khugepaged/`：`pages_collapsed`、`full_scans` 反映折叠进度。

## Links

- [内存管理知识地图（mm 枢纽）](/docs/CS/OS/Linux/mm/README.md)
- [物理内存与 buddy 分配器](/docs/CS/OS/Linux/mm/pm.md?id=buddy) — THP 的连续大块来源
- [内存压缩 Compaction](/docs/CS/OS/Linux/mm/Compaction.md?id=kcompactd-background-compaction) — 碎片时造连续块供 THP/khugepaged
- [页表 pagetable](/docs/CS/OS/Linux/mm/pagetable.md?id=page-table-pages-are-special-pages-ptdesc) — PMD 大页叶子与 ptdesc
- [NUMA 平衡](/docs/CS/OS/Linux/mm/Numa.md) — 大页迁移前的拆分

## References

1. [Transparent Hugepage Support (admin-guide)](https://www.kernel.org/doc/html/latest/admin-guide/mm/transhuge.html)
2. [sysctl vm (admin-guide)](https://www.kernel.org/doc/html/latest/admin-guide/sysctl/vm.html)
3. [LWN — Transparent huge pages in 2.6.38](https://lwn.net/Articles/423584/)
4. [LWN — Multi-size THP for anonymous memory](https://lwn.net/Articles/937239/)
5. [LWN — Reworking file-backed THP](https://lwn.net/Articles/849618/)
