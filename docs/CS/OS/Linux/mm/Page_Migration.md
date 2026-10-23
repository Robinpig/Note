# Page Migration

## Introduction

页迁移（page migration）做的只有一件事：把一页（或一组页）**内容 + 全部映射**从旧物理页搬到新物理页，并让所有指向旧页的 PTE/PMD、以及非表里映射（如 GUP 的 pin、设备的页表项）最终都重定向到新页。它不分配"用户看得见的内存"，只是**移动**已经存在的内存。

本目录下 [Numa](/docs/CS/OS/Linux/mm/Numa.md)（AutoNUMA promote）、[Tiered_Memory](/docs/CS/OS/Linux/mm/Tiered_Memory.md)（demote/promote）、[Compaction](/docs/CS/OS/Linux/mm/Compaction.md)（整理连续块）、[THP](/docs/CS/OS/Linux/mm/THP.md)（split 后逐 4K 搬）、[DAMON](/docs/CS/OS/Linux/mm/DAMON.md)（`DAMOS_MIGRATE_*`）、CMA（见 [pm](/docs/CS/OS/Linux/mm/pm.md) 的 `MIGRATE_CMA`）全都**调用**迁移——本文是这些笔记共用的"引擎层"，只讲迁移本身怎么发生，不重复各调用方的场景。

## Core Entry: migrate_pages (folio list form)

v7.2.7 的入口是 `migrate_pages()`（`mm/migrate.c:2094`），已是 **folio 链表**形式：

```c
int migrate_pages(struct list_head *from, new_folio_t get_new_folio,
        free_folio_t put_new_folio, unsigned long private,
        enum migrate_mode mode, int reason, unsigned int *ret_succeeded);
```

内部先 `migrate_hugetlbs()` 处理大页，普通 folio 按模式分批：`MIGRATE_ASYNC` 走 `migrate_pages_batch()`（`migrate.c:2133`，批量并行），其余走 `migrate_pages_sync()`（`migrate.c:2138`）。失败的**大 folio** 会被 `split_folios` 拆成 4K 再以 `MIGRATE_ASYNC` 重试一次（`migrate.c:2147-2157`）——这就是"大页先拆后搬"的落点。

> ⚠️ 旧文档里常写的 `unmap_and_move()` 在 v7.2.7 **已不存在**，被拆成 `migrate_folio_unmap` + `migrate_folio_move` 两步（见下）。

## Single-Folio Engine: unmap, then move

单页迁移主干现在是两段式：

- **`migrate_folio_unmap()`**（`mm/migrate.c:1208`）：先 `get_new_folio` 分配 dst（`:1220`）→ 锁 src（`:1227`）→ 处理写回中页（`MIGRATE_SYNC` 才等，否则 `-EBUSY`，`:1261`）→ `get_anon_vma`（`:1293`）→ 关键一步 **`try_to_migrate(src, ...)`**（`:1333`）把旧页的所有 PTE 改成"迁移专用条目"。
- **`migrate_folio_move()`**（`mm/migrate.c:1358`）：调 `move_to_new_folio()`（`:1387`）拷贝内容与元数据 → `folio_add_lru(dst)`（`:1409`）→ 若曾被映射则 `remove_migration_ptes(src, dst, 0)`（`:1414`）把 PTE 指回新页。

大页走保留的单函数 `unmap_and_move_huge_page()`（`migrate.c:1474`）。

### Content + metadata copy

`move_to_new_folio()`（`migrate.c:1097`）按 `folio_mapping` 分派：匿名页走 `migrate_folio`，文件页/交换页走 `a_ops->migrate_folio`，否则 `fallback_migrate_folio`。真正的拷贝在 `__migrate_folio()`（`migrate.c:862`）：`folio_mc_copy(dst, src)`（`:872`，即带机器检查的数据拷贝）+ `__folio_migrate_mapping()`（`:876`，address_space/xarray 重定向）+ `folio_migrate_flags()`（`:883`，拷贝 flags/dirty/accessed）。buffer head 由 `__buffer_migrate_folio` / `filemap_migrate_folio` 处理。

## rmap: Unmap and Rebuild Mapping

### try_to_migrate vs try_to_unmap

两者都是 rmap walk 族（`mm/rmap.c:2746` / `:2398`），但 `.rmap_one` 回调不同：

- `try_to_migrate_one` 把 PTE 换成**迁移专用条目**（源 subpage 的 pfn 编码进 `swp_entry` 的 `SWP_MIGRATION_*`）；
- `try_to_unmap_one` 把 PTE 换成普通 swap/空条目。

> ⚠️ 区别**不是** `TTU_MIGRATION` 标志——v7.2.7 的 `TTU_*` 枚举里**没有**这个常量（`include/linux/rmap.h:95-103` 已确认）。旧资料里的 `TTU_MIGRATION` 是过时写法。

### Migration PTE encoding

`try_to_migrate_one`（`rmap.c:2685-2693`）按可写/独占/只读分别 `make_writable_migration_entry` / `make_readable_exclusive_migration_entry` / `make_readable_migration_entry`。本树把这套包了一层 `softleaf_t` 抽象（`include/linux/leafops.h`），底层仍是 `swp_entry(SWP_MIGRATION_READ/WRITE, offset)`（`include/linux/swapops.h:173-183`）。young/dirty/soft-dirty/uffd-wp 等位一并迁进迁移条目；PMD 大页走 `set_pmd_migration_entry()`（需 `CONFIG_ARCH_ENABLE_THP_MIGRATION`）。

### remove_migration_ptes

`remove_migration_ptes()`（`migrate.c:459`）反向 walk dst 的 rmap，回调 `remove_migration_pte()`（`:346`）把迁移条目还原成指向新页的正常 PTE——按 **anon**（`folio_add_anon_rmap_pte`）、**文件页**（`folio_add_file_rmap_pte`）、**hugetlb**、**device-private** 分别处理（`:404-439`）。KSM 页走独立的 `rmap_walk_ksm` 路径（`rmap.c:3110`），不在 `try_to_migrate_one` 里分支。

## Reference Count and Pin Exclusion

迁移期间引擎自身持有 src 的一份引用，`folio_migrate_mapping()`（`migrate.c:718`）据此校验：

```c
expected_count = folio_expected_ref_count(folio) + extra_count + 1;  // 这个 +1 是迁移引擎自己占的引用
if (folio_ref_count(folio) != expected_count) return -EAGAIN;
```

**被 GUP pin 的页不能迁移**，互斥在引擎层由两条共同保证（并非在 `migrate_folio_unmap` 里直接调 `folio_maybe_dma_pinned`）：

1. **rmap 拒绝 unshare**：`try_to_migrate_one` 建迁移 PTE 前调 `folio_try_share_anon_rmap_pte`（`rmap.h:767`），当 `folio_maybe_dma_pinned()` 为真即 `return -EBUSY`（`rmap.c:2673`），walk 中断、页保持映射 → 解映射失败 → `-EAGAIN`。
2. **引用计数兜底**：pin 占用了 `GUP_PIN_COUNTING_BIAS` 高位，使 `folio_ref_count != expected_count` → `-EAGAIN`。

此外调用方在入口就跳过 pin 页：`demote` 路径 `vmscan.c:1257`、`mbind` 路径 `mempolicy.c:850` 都显式 `if (folio_maybe_dma_pinned(folio)) goto skip`。这与 [gup](/docs/CS/OS/Linux/mm/gup.md) "pin 与迁移互斥" 的结论一致。

## Modes and Reasons

`enum migrate_mode`（`include/linux/migrate_mode.h:11-15`）**只有 3 项**：

| Mode | 语义 |
| --- | --- |
| `MIGRATE_ASYNC` | 永不阻塞 |
| `MIGRATE_SYNC_LIGHT` | 阻塞多数操作，但不等 `->writepage` |
| `MIGRATE_SYNC` | 阻塞迁移全过程 |

> ⚠️ 旧资料的 `MIGRATE_SYNC_NO_COPY` 在 v7.2.7 **不存在**（全树 grep 未命中）。

`enum migrate_reason`（`include/linux/migrate_mode.h:17-29`）标记"谁发起的迁移"：

`MR_COMPACTION` / `MR_MEMORY_FAILURE` / `MR_MEMORY_HOTPLUG` / `MR_SYSCALL` / `MR_MEMPOLICY_MBIND` / `MR_NUMA_MISPLACED` / `MR_CONTIG_RANGE` / `MR_LONGTERM_PIN` / `MR_DEMOTION` / `MR_DAMON` / `MR_TYPES`。

## Coupling with Existing Subsystems

- **与 [gup](/docs/CS/OS/Linux/mm/gup.md)**：pin 页经 rmap 拒绝 unshare + refcount 不符双重拦截，无法迁移（见上）。
- **与 [THP](/docs/CS/OS/Linux/mm/THP.md)**：非 THP 迁移时先 `split_folio_to_list()`（迁到 `split_folios` 列表，`migrate.c:1585/1596`）；NUMA 提升路径（`MR_NUMA_MISPLACED`）设 `nosplit` 不复用拆分重试。
- **与 [Compaction](/docs/CS/OS/Linux/mm/Compaction.md)**：`compact_zone` 内 `migrate_pages(&cc->migratepages, compaction_alloc, ..., cc->mode, MR_COMPACTION, ...)`（`compaction.c:2700`），模式在 `MIGRATE_ASYNC`/`MIGRATE_SYNC_LIGHT` 间选。
- **与 [KSM](/docs/CS/OS/Linux/mm/KSM.md)**：KSM 合并出的只读共享页经 `rmap_walk_ksm` 独立路径参与迁移，`ksm.c:641` 也识别迁移条目。
- **与 [Tiered_Memory](/docs/CS/OS/Linux/mm/Tiered_Memory.md)**：demote 是 `migrate_pages(..., MR_DEMOTION)`（`vmscan.c:1025`），promote 是 `migrate_misplaced_folio()`→`migrate_pages(..., MR_NUMA_MISPLACED)`（`migrate.c:2759/2761`）——二者都是本引擎的调用方。
- **与 [DAMON](/docs/CS/OS/Linux/mm/DAMON.md)**：`DAMOS_MIGRATE_HOT/COLD` 经 `damon_migrate_pages`（`damon/ops-common.c:387`）→ `migrate_pages(..., MR_DAMON)`。
- **与 [CMA](/docs/CS/OS/Linux/mm/CMA.md)**：`alloc_contig_range` → `__alloc_contig_migrate_range` → `migrate_pages(..., MR_CONTIG_RANGE)` 是引擎的另一大调用方。

## Errors and Rollback

`migrate_folio_unmap` 的返回值决定去向（`migrate.c:1914-1921`）：`0`=进入 unmap/dst 列表；`-EAGAIN`/`ENOMEM`=留在 `from` 列表重试；其它 errno=进入 `ret_folios` 永久失败列表。写回中页（`folio_test_writeback`）非 `MIGRATE_SYNC` 返回 `-EBUSY`。迁移失败的 folio 最终由调用方 `putback_movable_pages()` 放回 LRU（**不是** `vmscan.c` 的 `move_folios_to_lru`，那是回收助手）。

统计：`migrate_pages()` 末尾 `count_vm_events(PGMIGRATE_SUCCESS/PGMIGRATE_FAIL, ...)`（`migrate.c:2175-2176`）。

## User Interface

- `move_pages` 系统调用 `SYSCALL_DEFINE6(move_pages, ...)`（`migrate.c:2627`）→ `kernel_move_pages` → 最终 `migrate_pages(MR_SYSCALL)`，把指定虚拟地址的页迁到指定 node。
- `migrate_pages` 系统调用 `SYSCALL_DEFINE4(migrate_pages, ...)`（`mempolicy.c:1948`）按 numa 策略批量迁移。
- `/proc/vmstat` 计数：`pgmigrate_success` / `pgmigrate_fail`（定义 `vmstat.c:1365-1366`）。

## Links

- [分层内存 Tiered_Memory](/docs/CS/OS/Linux/mm/Tiered_Memory.md) — demote/promote 都是本引擎的 MR_DEMOTION/MR_NUMA_MISPLACED 调用方
- [NUMA 平衡 Numa](/docs/CS/OS/Linux/mm/Numa.md) — promote 经 migrate_misplaced_folio
- [内存压缩 Compaction](/docs/CS/OS/Linux/mm/Compaction.md) — 调用本引擎做页移动（MR_COMPACTION）
- [GUP 与 pin 页](/docs/CS/OS/Linux/mm/gup.md) — pin 页无法迁移的互斥机制
- [THP 透明大页](/docs/CS/OS/Linux/mm/THP.md) — 大页先 split 再逐 4K 迁移
- [CMA 连续内存分配器](/docs/CS/OS/Linux/mm/CMA.md) — 分配连续块时通过 migrate_pages(MR_CONTIG_RANGE) 搬走区间内页

## References

1. 本地源码即权威：`<linux-7.2.7>/mm/migrate.c`、`mm/rmap.c`、`include/linux/migrate_mode.h`、`include/linux/migrate.h`、`include/linux/rmap.h`、`include/linux/leafops.h`、`include/linux/swapops.h`。
2. LWN — "Accelerate page migration with batch copying and hardware offload"（与 v7.2.7 的 `migrate_folio_unmap`/`migrate_folio_move` 流程一致）：https://lwn.net/Articles/1080459/
3. LWN — 同系列 V3（含 `migrate_pages_batch`/`migrate_folio_unmap` 批处理与 `MIGRATE_ASYNC` 说明）：https://lwn.net/Articles/1039253/
4. LWN — "Hot-page migration and specific-purpose NUMA nodes"（MR_NUMA_MISPLACED / MR_DEMOTION 上下文）：https://lwn.net/Articles/1046249/
