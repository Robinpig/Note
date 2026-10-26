## Introduction

KSM（Kernel Same-page Merging，内核同页合并）把多个进程 / 映射里**内容完全相同**的匿名页，合并成单一物理页、以 Copy-On-Write 共享。典型收益是虚拟机 / 容器密度：100 个 idle 的相同镜像进程，其大量只读代码页与零数据页可以合到一份物理页上。它和 [PageCache](/docs/CS/OS/Linux/mm/PageCache.md) 的"文件页缓存共享"是**不同层**的去重——KSM 只合匿名（私有）页，从不合并 page cache 页（官方 `Documentation/admin-guide/mm/ksm.rst:25` 明确 "KSM only merges anonymous (private) pages, never pagecache (file) pages"）。

与 [GUP 与 pin 页](/docs/CS/OS/Linux/mm/gup.md) 的关系尤其微妙：被 pin 住的页**不能**被 KSM 合并（详见下文 [与 GUP 的互斥](#cow-and-the-gup-exclusion)），这条规则在 `gup.md` 里有专门的 "KSM: Pinned Pages Are Not Merged" 小节，本篇给出其源码依据。

## Data Structures

KSM 的核心对象如下（v7.2.7 实测命名，注意两处常见误解）：

- `struct ksm_mm_slot`（`mm/ksm.c:126`）= 通用 `struct mm_slot`（`mm/mm_slot.h:15`）内嵌 `struct ksm_rmap_item *rmap_list`。内核用一个全局 `ksm_mm_head` 把这些 slot 串成链表，扫描线程沿链逐个 mm 走。
- `struct ksm_scan`（`mm/ksm.c:140`）：全局扫描游标，记录当前 `mm_slot`、`address`、`rmap_list`、`seqnr`（全扫描计数）。
- `struct ksm_stable_node`（`mm/ksm.c:159`）：stable tree 节点（rb 节点 + `hlist` 链着所有 `rmap_item` + `kpfn` + `rmap_hlist_len` + NUMA `nid`）。它同时兼作 "chain/dup" 机制节点（`STABLE_NODE_CHAIN = -1024`）。
- `struct ksm_rmap_item`（`mm/ksm.c:201`）：反向映射项；其 `union { struct rb_node node; ...}` 在它充当 **unstable tree 节点**时使用 `node` 挂入 rbtree（`:215` 注释 "when node of the unstable tree"）。

> ⚠️ **unstable tree 没有独立的节点结构**：它的节点就是 `ksm_rmap_item` 本身，所谓的 `struct unstable_node` 在 v7.2 源码里**不存在**。许多旧资料描述的 `unstable_node` 是早期实现遗留的叫法。

全局调参（定义位置与默认值）：

| 参数 | 默认 | 含义 |
| :--- | :--- | :--- |
| `ksm_thread_pages_to_scan` | `DEFAULT_PAGES_TO_SCAN` = 100 | 每轮扫描页数（`:282` / `:252`） |
| `ksm_thread_sleep_millisecs` | `20` ms | 每轮之间休眠（`:285`） |
| `ksm_max_page_sharing` | `256` | 单 stable node 允许共享的最大页槽数（`:279`） |
| `ksm_merge_across_nodes` | `1`（允许） | 是否跨 NUMA 节点合并（`:471`） |
| `ksm_run` | `KSM_RUN_STOP` = `0` | **默认关闭**（`:482`） |
| `ksm_use_zero_pages` | `false` | 是否把全零页合到 dedicated zero page（`:291`） |
| `ksm_smart_scan` | `true` | 跳过已知不可合并项（`:295`） |

此外 v7.2 还带有 **KSM advisor**（`KSM_ADVISOR_SCAN_TIME`，`ksm.c:334`）：按 CPU / scan-time 自动调 `pages_to_scan`，无需手工调参。

## stable vs unstable Trees

两棵树职责不同（源码注释 `mm/ksm.c:100`）：

- **unstable tree**：每完成一次全扫描就**清空并重建**；只插入"自上次扫描校验和未变"的页；是 rbtree，按节点颜色平衡（内容变化不致失衡），用于"试探"候选页。
- **stable tree**：**永不清空**；一旦在 unstable tree 找到匹配并合并成功，页就被固化进 stable tree。

`cmp_and_merge_page()`（`mm/ksm.c:2251`）的搜索顺序是**先 stable（`:2300`）后 unstable（`:2328`）**：命中 stable 就 `try_to_merge_with_ksm_page()`（`:2312`）+ `stable_tree_append()`（`:2319`）把本 `rmap_item` 链到同一 `stable_node`；未命中才查 / 插 unstable tree；两页匹配上则 `try_to_merge_two_pages()`（`:2332`）→ 成功后 `stable_tree_insert`（`:2353`）建新 stable 节点，并把 `tree_rmap_item` 与 `rmap_item` **都** `stable_tree_append` 到同一节点（`:2355`）。若 `merge_across_nodes=0`，则为每个 NUMA 节点各维护一棵 stable + 一棵 unstable tree（`:117`）。

## Merge Flow

`scan_get_next_rmap_item()`（`mm/ksm.c:2577`）是扫描入口：沿 `ksm_mm_head.slot.mm_node` 链表取下一个 `mm_slot`（`:2631`），每个 mm 用 `vma_iter_init` + `for_each_vma` 遍历 VMA、仅处理带 `VM_MERGEABLE` 的（`:2655`），每页用 `walk_page_range_vma()`（`:2673`）取回，`get_next_rmap_item()`（`:2391`）分配 / 复用 `rmap_item` 挂入 `rmap_list`。每轮全扫描前清空 unstable tree（`:2627`）并 drain LRU（`:2605`）。

合并落地的两个关键函数：

- `try_to_merge_one_page()`（`mm/ksm.c:1478`）：先 `write_protect_page()` 把 PTE 写保护，再 `replace_page()`。
- `replace_page()`（`mm/ksm.c:1375`）：用 `mk_pte(kpage, vma->vm_page_prot)`（`:1428`）**安装只读 PTE**，把原匿名页换成 KSM 共享页；`:1417` 处有 `VM_BUG_ON_PAGE(PageAnonExclusive(page), page)`——被替换页必须不是 exclusive 的（见下与 GUP 的互斥）。

写时复制分裂路径：`break_ksm()`（`mm/ksm.c:692`，PMD 级 walk）触发 COW unshare，用于 unmerge / 退出；某进程写共享页时走 `do_wp_page` → `wp_page_copy()` 真正分裂拷贝（`mm/memory.c:4332` 计 `COW_KSM`）。

## COW and the GUP Exclusion

KSM 合并出的页是**只读共享**的，写入触发 COW 分裂——这点和普通匿名页一致。但它与 GUP 的**互斥**是 KSM 最容易被写错的地方。

机制证据在 `write_protect_page()`（`mm/ksm.c:1280`）：

1. `:1310` 取 `anon_exclusive = PageAnonExclusive(&folio->page)`；
2. `:1311-1312` 当 PTE 可写 / 脏 / `anon_exclusive` / `mm_tlb_flush_pending` 时，先清 PTE + flush TLB；
3. `:1334` 关键判据 `folio_mapcount(folio) + 1 + swapped != folio_ref_count(folio)`——这正是"页被 GUP / O_DIRECT pin 时 refcount 高于 mapcount"的判定，命中则放弃合并；
4. `:1340-1344` 若 `anon_exclusive` 为真，必须 `folio_try_share_anon_rmap_pte()` 成功，否则 `goto out_unlock` 放弃。

**GUP 持有 exclusive 匿名页（`PageAnonExclusive`）时该 share 调用失败 → KSM 无法合并。** 这与 [GUP 与 pin 页](/docs/CS/OS/Linux/mm/gup.md) 的 "KSM: Pinned Pages Are Not Merged" 小节完全吻合：KSM 只合并 `PageAnonExclusive` 为假的页（即从未被 pin 过的页），而 pin 的前提是"必须独占"，两者天然互斥。

## RMAP for KSM Pages

普通匿名页的 RMAP 走 `anon_vma`；**KSM 页没有 `anon_vma`**（`mm/rmap.c:874` 注释 "KSM folios don't reach here because of the !anon_vma check"）。它的反向映射走 `rmap_walk_ksm()`（`mm/rmap.c:3110`）：`if (unlikely(folio_test_ksm(folio))) rmap_walk_ksm(folio, rwc);`，它遍历 `stable_node->hlist` 上**所有** `rmap_item`——一个 `stable_node` 对应多个 `rmap_item`。所以 COW / unmap 时必须更新全部映射，而不能只改一处。

## User ABI and Observability

合并的入口是 `madvise(addr, len, MADV_MERGEABLE)`：`ksm_madvise()`（`mm/ksm.c:2978`）在 `MADV_MERGEABLE`（`:2985`）时首次置 `MMF_VM_MERGEABLE` 并 `__ksm_enter(mm)`（`:2992`），再给 VMA 加 `VM_MERGEABLE`（`:2997`）；`MADV_UNMERGEABLE`（`:3000`）先 `break_ksm()`（`:3005`）再 unmerge。`MADV_MERGEABLE` / `MADV_UNMERGEABLE` 的定义在 `include/uapi/asm-generic/mman-common.h:59`（值 12 / 13）——**不在** `include/uapi/linux/ksm.h`（该文件在 v7.2 不存在）。

`/sys/kernel/mm/ksm/`（`ksm_attrs`，`mm/ksm.c:3942`）下真实存在的文件包括：`sleep_millisecs`、`pages_to_scan`、`run`、`pages_scanned`、`pages_shared`、`pages_sharing`、`pages_unshared`、`pages_volatile`、`pages_skipped`、`ksm_zero_pages`、`full_scans`、`merge_across_nodes`、`max_page_sharing`、`stable_node_chains`、`stable_node_dups`、`stable_node_chains_prune_millisecs`、`use_zero_pages`、`general_profit`、`smart_scan`、以及 `advisor_*`（`advisor_mode` / `advisor_max_cpu` / `advisor_min_pages_to_scan` / `advisor_max_pages_to_scan` / `advisor_target_scan_time`）。`general_profit`（`pages_sharing - pages_unshared` 的估算收益）是判断是否值得开 KSM 的一手指标。

> ⚠️ `/proc/meminfo` 里**没有** KSM 行（搜 `fs/proc/meminfo.c` 无 `KSM` 命中）。KSM 统计只在 `/sys/kernel/mm/ksm/` 与 `ksm_process_profit()` 里，排障别去 meminfo 找。

## Interaction with the MM Chain

- **vs PageCache**：匿名页去重 vs 文件页缓存共享——两条不同层的"共享"，KSM 只碰匿名页。
- **vs [Reclaim](/docs/CS/OS/Linux/mm/Reclaim.md?id=watermarks-and-kswapd)**：KSM 页可被回收（官方 rst 说明 "can now be swapped out"）；`ksm_max_page_sharing=256` 限长与 `stable_node_chains` / chain 机制（`chain_prune()` `:1805`、`stable_node_chains_prune_millisecs=2000` `:276`）直接影响回收时 stale 节点剪枝开销。
- **vs [NUMA 平衡](/docs/CS/OS/Linux/mm/Numa.md)**：`merge_across_nodes`（默认 1）为 0 时每节点独立双树（`root_stable_tree[nid]`），跨节点合并代价体现在 `get_ksm_stable_node_nid()`（`:838`）与分树查找。
- **vs mmap（v7.2 路径修正）**：KSM 的 VMA 注册**不走 `mmap` 主路径**。真实链路是 `madvise` → `ksm_madvise` → `__ksm_enter`（`mm/ksm.c:3018`）→ `ksm_add_vmas`（`:2888`）→ `__ksm_add_vma`（`:2839`）。`mm/mmap.c` 在 v7.2.7 里只调用 `ksm_fork()`（用于 `fork` 继承），不调用 `ksm_add_vma()`——本仓库 `mmap.md` 旧写法已据此校正。

## Versions and Defaults

- 引入版本：2.6.32（官方 `ksm.rst:9` "added to the Linux kernel in 2.6.32"）。
- 默认**关闭**：`ksm_run = KSM_RUN_STOP`（`mm/ksm.c:482`），正常构建需手动 `echo 1 > /sys/kernel/mm/ksm/run` 才启动扫描线程。
- `max_page_sharing=256`：限制单 stable node 共享槽数、避免 chain 爆炸（`is_page_sharing_candidate()` `:1653`）。
- `use_zero_pages` 默认 `false`（`ksm_init:3985` "Default to false for backwards compatibility"）；置 1 时全零页合并到 dedicated zero page。
- v7.2 新增并已稳定：`ksm_smart_scan`（跳过不可合并项）与 **KSM advisor**（按 CPU / scan-time 自动调参，6.8 / 6.9 前后引入）。

## Links

- [内存管理知识地图（mm 枢纽）](/docs/CS/OS/Linux/mm/README.md)
- [页缓存 PageCache](/docs/CS/OS/Linux/mm/PageCache.md) — 文件页共享 vs KSM 匿名页去重
- [内存回收 Reclaim](/docs/CS/OS/Linux/mm/Reclaim.md?id=watermarks-and-kswapd) — KSM 页的回收与 stable_node 剪枝
- [GUP 与 pin 页](/docs/CS/OS/Linux/mm/gup.md) — KSM 与 pin 的互斥（PageAnonExclusive）
- [NUMA 平衡](/docs/CS/OS/Linux/mm/Numa.md) — merge_across_nodes 的跨节点代价

## References

1. [Kernel Samepage Merging (admin-guide)](https://www.kernel.org/doc/html/latest/admin-guide/mm/ksm.html)
2. [LWN — A surprise with KSM (merge_across_nodes / zero page 语义陷阱)](https://lwn.net/Articles/853527/)
3. [LWN — KSM 早期介绍](https://lwn.net/Articles/306704/)
4. [LWN — KSM 合入讨论](https://lwn.net/Articles/330589/)
