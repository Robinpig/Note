# CMA

## Introduction

CMA（Contiguous Memory Allocator，连续内存分配器）解决的是一类特殊需求：**大块、物理连续**的内存。很多硬件（显示控制器、视频编解码器、部分 DMA 设备）的 DMA 不支持 scatter-gather 或只支持有限段，必须拿到一段地址连续的物理页才能工作。[pm](/docs/CS/OS/Linux/mm/pm.md) 里 `MIGRATE_CMA` 这个 migratetype 就是 CMA 在 buddy 里的"身份标签"。

CMA 的核心设计是**预约但不独占**：启动时为设备预留一段区域，但平时这片页以 `MIGRATE_CMA` 身份**借给可移动分配**（page cache、用户匿名页等）当普通内存用；只有当设备真正 `cma_alloc()` 时，才把这段区间隔离出来、把落在里面的已分配页全部迁移走、交给设备。它和 [zswap](/docs/CS/OS/Linux/mm/zswap.md)/zram 不同（那是 swap 压缩），也和 [THP](/docs/CS/OS/Linux/mm/THP.md) 不同（那是恰好 2MB 的连续块、靠 buddy 直接分配）。

## Core Structure

`struct cma`（`mm/cma.h:39-65`）v7.2.7 已是**多段（multi-range）**结构——因为预留总量可能大于单个物理连续段（中间有内存空洞），所以一个 CMA area 可挂多个 `ranges[]`：

- `count` / `available_count`（`cma.h:40-41`）、`order_per_bit`（`:42`）：每个 bitmap 位覆盖的页阶。
- `lock` / `alloc_mutex`（`:43-44`）、`name[CMA_MAX_NAME]`（`:49`，`CMA_MAX_NAME=64`）。
- `nranges` + `ranges[CMA_MAX_RANGES]`（`:50-51`，`CMA_MAX_RANGES=8`）：**真正的 `base_pfn` / `bitmap` 下沉到 `struct cma_memrange`**（`cma.h:26-36`），没有顶层 `bitmap_size` 字段，bitmap 由 `bitmap_zalloc` 动态分配（`cma.c:151`）。
- `flags` / `nid`（`:62-64`）；`CONFIG_CMA_SYSFS` 下还有统计字段 `nr_pages_succeeded/failed/released` + `cma_kobj`。

`MIGRATE_CMA` 定义在 `include/linux/mmzone.h:135`，位于 `enum migratetype` 内、受 `#ifdef CONFIG_CMA` 保护，**值 = 4**（UNMOVABLE=0, MOVABLE=1, RECLAIMABLE=2, CMA=4, ISOLATE=5）。配套 `is_migrate_cma()` / `is_migrate_cma_page()`。全局 `struct cma cma_areas[MAX_CMA_AREAS]`（`cma.c:37`）+ `cma_area_count`（`cma.c:38`）由 `CONFIG_CMA_AREAS` 决定容量（UMA 默认 8 / NUMA 默认 20）。

## Reservation at Boot

`cma_declare_contiguous_nid()`（`cma.c:737`）→ 真正干活的是 `__cma_declare_contiguous_nid()`（`cma.c:434`）：

- 对齐：取 `max(alignment, CMA_MIN_ALIGNMENT_BYTES)`（`cma.c:462`），`CMA_MIN_ALIGNMENT_PAGES = pageblock_nr_pages`。
- 经 memblock 预留（`cma_fixed_reserve` / `cma_alloc_mem`），失败 `-ENOMEM`。
- 最后 `cma_init_reserved_mem()`（`cma.c:271-309`）建 bitmap、填 `ranges[0]`、`nranges=1`。

**关键：预留的页如何"平时可复用"** —— `cma_activate_area()`（`cma.c:141`）对每个 pageblock 调 `init_cma_reserved_pageblock()`（`mm/mm_init.c:2240`），把页块标成 `MIGRATE_CMA` 后 `__free_pages()` 还给 buddy（`mm_init.c:2250-2257`）。启动期 `cma_init_reserved_areas()`（`cma.c:206`）统一激活。此后 buddy 可正常从 `MIGRATE_CMA` 取页（`page_alloc.c:1931` `__rmqueue_smallest(zone, order, MIGRATE_CMA)`），即 CMA 区域作为 movable 内存被复用。

## Allocation and Release

`cma_alloc()`（`cma.c:947`）→ `cma_alloc_frozen()`（`:922`）→ `__cma_alloc_frozen()`（`:864`），后者遍历 `nranges` 调 **`cma_range_alloc()`**（`:784`）：

1. 先在 bitmap `bitmap_set` 占坑（`:834`）；
2. 调 **`alloc_contig_frozen_range()`**（`page_alloc.c:7164`）：
   - `start_isolate_page_range(start, end, PB_ISOLATE_MODE_CMA_ALLOC)` 把目标区间从 buddy 摘离（真身在 `mm/page_isolation.c:482`）；
   - `__alloc_contig_migrate_range()`（`page_alloc.c:7017`）逐页 `isolate_migratepages_range`（`:7041`，真身 `compaction.c:855`）→ **`migrate_pages(&cc->migratepages, ..., MR_CONTIG_RANGE, ...)`**（`:7055`，reason `MR_CONTIG_RANGE`）把区间内所有已分配页搬走。

> 注意：`alloc_contig_range()`（`page_alloc.c:7321`）仍然存在，是 `alloc_contig_frozen_range` 的薄封装；v7.2.7 走 frozen 变体是为了分配"已冻结、可被 compound 直接持有"的页。frozen 封装不影响"先 isolate + 迁移区间内页"的本质。

`cma_release()`（`cma.c:1017`）→ `__cma_release_frozen()`（`:994`）调 `free_contig_frozen_range()`（`:1001`，`page_alloc.c:7136`）并 `cma_clear_bitmap`，收尾阶段把 pageblock 改回 `MIGRATE_CMA`/`MIGRATE_MOVABLE`。

## Coupling with Existing Subsystems

- **与 [pm](/docs/CS/OS/Linux/mm/pm.md)**：`MIGRATE_CMA` 是 buddy 中受保护的独立 migratetype，注释明确"page allocator never implicitly change migration type of MIGRATE_CMA pageblock"（`mmzone.h:128-129`），fallback list 不会随意吞掉它——这正是 pm 讲的 migratetype 分类与 fallback 语义。
- **与 [Compaction](/docs/CS/OS/Linux/mm/Compaction.md)**：`__alloc_contig_migrate_range` 内逐页 `migrate_pages` 与 compaction 共用同一套迁移引擎（`compact_zone` 同源），`isolate_migratepages_block` 真身就是 compaction 的扫描器。
- **与 [Page Migration](/docs/CS/OS/Linux/mm/Page_Migration.md)**：`alloc_contig_range` → `__alloc_contig_migrate_range` → `migrate_pages(MR_CONTIG_RANGE)` 是迁移引擎的一大调用方。迁移细节见该篇。
- **与 [gup](/docs/CS/OS/Linux/mm/gup.md)**：被 GUP pin 的页无法迁移 → `migrate_pages` 失败 → `cma_range_alloc` 清 bitmap 重试/失败（`cma.c:849-851`）→ `cma_alloc` 返回 NULL → 设备报 allocation fail。这是"外设拿不到连续内存"的常见根因。

## User Interface and Observability

⚠️ **sysfs 与 debugfs 是两个不同的东西**，旧资料常混为一谈：

- **sysfs**（`CONFIG_CMA_SYSFS`，`mm/Kconfig:1088`）= `/sys/kernel/mm/cma/<name>/`，文件在 `mm/cma_sysfs.c:92-99`：`alloc_pages_success`、`alloc_pages_fail`、`release_pages_success`、`total_pages`、`available_pages`。**没有** `base_pfn`/`count`/`order_per_bit`/`free`/`alloc`。
- **debugfs**（`CONFIG_CMA_DEBUGFS`，`mm/Kconfig:1082`）= `/sys/kernel/debug/cma/<name>/`，文件在 `mm/cma_debug.c:168-196`：`alloc`(WO)、`free`(WO)、`count`(RO)、`order_per_bit`(RO)、`used`(RO)、`maxchunk`(RO)、`ranges/N/base_pfn`、`ranges/N/bitmap`。你想要的 `base_pfn`/`count`/`order_per_bit` 在这里。

启动参数 `cma=size[@start]` 由 **`early_cma`**（`kernel/dma/contiguous.c:103`，`early_param("cma", early_cma)` 在 `:122`）解析，不在 `mm/cma.c`。可用 `cma=0` 关闭。

tracepoint（`include/trace/events/cma.h`）：`cma_alloc_start` / `cma_alloc_finish` / `cma_alloc_busy_retry` / `cma_release`（**没有** `cma_trace_alloc/release`）。

`CONFIG_CMA`（bool，默认 n，`mm/Kconfig:1067`）`select MIGRATION` + `select MEMORY_ISOLATION`；`CONFIG_DMA_CMA`（`kernel/dma/Kconfig:157`）`depends on HAVE_DMA_CONTIGUOUS && CMA`，是 CMA 面向 DMA 的子选项。

## Usage Scenarios

- **DMA 缓冲**：`dma_alloc_contiguous()`（`kernel/dma/contiguous.c:415`）按 `dev->cma_area` → per-numa CMA → 默认全局 CMA 依次 `cma_alloc_aligned()`；`size<=PAGE_SIZE` 不走 CMA（`contiguous.c:426`）。`dma_alloc_coherent` 大块时回落 CMA。
- **GPU/DRM、V4L2/视频编解码**：通过 device-tree `memory-region` 或 `dev->cma_area` 预留私有 area。
- **为什么需要连续内存**：许多硬件 DMA 不支持 I/O map 也不支持 scatter-gather（`kernel/dma/Kconfig:157-168` 原文），必须用物理连续缓冲。

## Links

- [物理内存 pm](/docs/CS/OS/Linux/mm/pm.md) — MIGRATE_CMA migratetype 与 buddy fallback
- [内存压缩 Compaction](/docs/CS/OS/Linux/mm/Compaction.md) — 共享 isolate_migratepages_block 扫描器
- [页迁移 Page_Migration](/docs/CS/OS/Linux/mm/Page_Migration.md) — alloc_contig_range 经 migrate_pages(MR_CONTIG_RANGE) 搬走区间内页
- [GUP 与 pin 页](/docs/CS/OS/Linux/mm/gup.md) — pin 住的页导致 cma_alloc 失败

## References

1. 本地源码即权威：`<linux-7.2.7>/mm/cma.c`、`mm/cma.h`、`mm/page_alloc.c`（`alloc_contig_range`）、`mm/page_isolation.c`（`start_isolate_page_range`）、`mm/compaction.c`（`isolate_migratepages_block`）、`kernel/dma/contiguous.c`（`early_cma`、`dma_alloc_contiguous`）。
2. 本地文档：`<linux-7.2.7>/Documentation/admin-guide/mm/cma_debugfs.rst`（已确认存在，含 base_pfn/count/order_per_bit/alloc/free 说明；注意 `cma.rst` 本树不存在）。
3. LWN — "A deep dive into CMA"（设计原理与演进）：https://lwn.net/Articles/486301/
4. LWN — "Contiguous memory allocation for DMA"（cma= 与 DMA_CMA）：https://lwn.net/Articles/396707/
