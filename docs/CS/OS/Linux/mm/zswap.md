## Introduction

zswap 位于内存与 swap 设备之间的**压缩写回缓存**（compressed write-back cache）。匿名页被回收时，若开启 zswap，页先被压缩存进内存里的一个池子，而不是直接写盘；池子满或压缩失败才真正落到 swap 设备。它和 zram（压缩**块设备**）是不同机制：zram 本身就是 swap 后端，zswap 是真实 swap 设备的**前端缓存**——store 成功时无 swap IO，load 在 `swap_read_folio` 中先于设备读被拦截。它正是 [内存回收 Reclaim](/docs/CS/OS/Linux/mm/Reclaim.md?id=shrink_folio_list-decision-tree-for-keeping-or-evicting-a-single-page) 里那句"匿名页必须先写 swap（或 zswap 压缩）"的完整展开。

## Data Structures and the xarray Index

v7.2 的 zswap 已经过一轮重构，几个常见旧认知在此**不成立**：

- **没有 `struct zswap_tree` rbtree**。旧的 per-swap-device rbtree 已移除，现用 `static struct xarray *zswap_trees[MAX_SWAPFILES]`（`mm/zswap.c:200`），按 swap type 分桶、每 64 MiB 再细分为一个 xarray（`ZSWAP_ADDRESS_SPACE_SHIFT = 14`，`zswap.c:229`）。`swap_zswap_tree(swp)`（`zswap.c:231`）用 `swp_type` / `swp_offset >> 14` 选桶。
- **没有 zpool 抽象层、没有 zbud 后端**。旧的 `include/linux/zpool.h` / `mm/zpool.c` / `mm/zbud.c` 已移除，zsmalloc 被直接内嵌：`struct zswap_pool`（`mm/zswap.c:153`）内含 `struct zs_pool *zs_pool`（**注意是 `zs_pool`，不是旧资料里的 `zspool`**，`include/linux/zsmalloc.h:24`）。
- `struct zswap_entry`（`mm/zswap.c:190`）：字段 `swpentry`、`length`、`referenced`、`pool`、`handle`（zsmalloc 对象句柄）、`objcg`、`lru`——**无 rbtree 节点字段**，索引改由 xarray 直接存指针。

一个换出页的寻址链：`swp_entry_t` → `swp_type` + `swp_offset` → `swap_zswap_tree()` 选 xarray → `xa_load/xa_store/xa_erase(offset)` 得到 `struct zswap_entry *` → `entry->handle` 是 zsmalloc 对象句柄 → `zs_obj_read/zs_obj_write`（`zsmalloc.h:43/50`）读写压缩字节。压缩本身走 `crypto_acomp`（`zswap_compress`，`zswap.c:840`）。

## store and load Paths

回收路径：`shrink_folio_list()`（`mm/vmscan.c:1392` 的 `pageout()` 分支）→ `pageout()`（`vmscan.c:613`）→ `swap_writeout()`（`vmscan.c:652` 调用；定义于 `mm/page_io.c:251`）→ **`zswap_store()`**（`mm/page_io.c:285`）。

> ⚠️ 旧资料里的 `swap_writepage` 在 v7.2.7 已重命名为 `swap_writeout`；真正落盘的是 `__swap_writepage`（`page_io.c:466`）。store 成功即 `goto out_unlock`（`page_io.c:287`），**不落盘**；仅当 store 失败 / 禁用才 `__swap_writepage`（`page_io.c:298`）。

`zswap_store(struct folio *folio)`（`mm/zswap.c:1477`）：**确认参数为 `struct folio *`（folio 化 refactor 已完成）**。流程：检查 `zswap_enabled`（`:1490`）→ `obj_cgroup_may_zswap` 超限则 `shrink_memcg`（`:1494`）→ `zswap_check_limits()`（`:1503`）→ `zswap_pool_current_get`（`:1506`）→ 按 `folio_nr_pages` 循环调 `zswap_store_page`（`:1519`）→ 成功 `ret = true`；失败且池已满则 `queue_work(&zswap_shrink_work)`（`:1538`）。`zswap_store_page()`（`zswap.c:1397`）：`zswap_entry_cache_alloc`（失败 → `zswap_reject_kmemcache_fail++`）→ `zswap_compress`（`:1411`）→ `xa_store`（`:1414`）→ `obj_cgroup_charge_zswap`（`:1443`）→ `zswap_lru_add`（`:1465`）。

`zswap_load(struct folio *folio)`（`zswap.c:1583`）：`xa_load`（`:1606`）→ `zswap_decompress`（`:1610`）→ `folio_mark_uptodate`（`:1615`）→ `xa_erase` + `zswap_entry_free`（`:1629`）。**大 folio 在 load 时被拒绝**（`folio_test_large` 直接 `WARN + return -EINVAL`，`:1601`）——当前 zswap 不支撑大 folio 换入；store 侧则是对 folio 内各页逐页循环。

## writeback to the Real Swap Device

池满检测：`zswap_check_limits()`（`zswap.c:509`）达到 `zswap_max_pages()`（`:486`，= `totalram_pages() * max_pool_percent / 100`）时置 `zswap_pool_reached_full`；store 失败时若满则触发 shrink work（`:1538`）。

回写完全由 **memcg-aware 的 shrinker** 驱动（不再有旧 `zpool` 的 `evict` 回调）：前端 LRU 是 `static struct list_lru zswap_list_lru`（`zswap.c:164`）。`zswap_shrinker_scan`（`zswap.c:1169`）→ `shrink_memcg_cb`（`zswap.c:1088`，二次机会算法看 `referenced` 位 `:1102`）→ **`zswap_writeback_entry()`**（`zswap.c:987`）：分配 swap cache folio → `zswap_decompress` 解压 → `xa_erase` → `__swap_writepage(folio, NULL)`（`zswap.c:1052`）**真正落盘**。计数 `zswap_written_back_pages++`（`:1163`），失败 `zswap_reject_reclaim_fail++`（`:1150`）。

### memcg 限制

`struct mem_cgroup` 里两个字段真实存在且语义明确：

- `unsigned long zswap_max;`（`include/linux/memcontrol.h:225`）：该 memcg 的 zswap 压缩内存上限（字节）。`0` = 拒绝一切新 store；`PAGE_COUNTER_MAX` = 不限。
- `bool zswap_writeback;`（`include/linux/memcontrol.h:231`）：是否允许该 memcg 的压缩页回写 swap 设备（关掉后不可压缩页会被直接拒）。

对应的 cgroup v2 接口 **`memory.zswap.max` / `memory.zswap.current` / `memory.zswap.writeback` 在 v7.2.7 全部实现**（`memcontrol.c:6100` / `:6095` / `:6106`），仅 cgroup v2 生效（`obj_cgroup_charge_zswap` 内 `cgroup_subsys_on_dfl` 判断）。这与 [cgroup 内存控制 memcg](/docs/CS/OS/Linux/mm/memcg.md?id=limit-interface-cgroup-v2) 的 `zswap` 统计口径一致。

## User ABI and Observability

`/sys/module/zswap/parameters/`（v7.2.7 实测）：

| 参数 | 默认 | 含义 |
| :--- | :--- | :--- |
| `enabled` | **OFF**（`IS_ENABLED(CONFIG_ZSWAP_DEFAULT_ON)`，而该 Kconfig 无 `default y`） | 总开关 |
| `compressor` | **`lzo`**（`ZSWAP_COMPRESSOR_DEFAULT_LZO`） | 压缩算法，可用 `zswap.compressor=` 覆盖 |
| `max_pool_percent` | `20` | 压缩池占物理内存的最大百分比 |
| `accept_threshold_percent` | `90` | 池满后恢复接收新页的阈值 |
| `shrinker_enabled` | OFF（`CONFIG_ZSWAP_SHRINKER_DEFAULT_ON` 默认 n） | 是否启用基于压力的 shrinker |

> ⚠️ v7.2 **没有** `non_same_filled_pages_enabled` 参数——旧资料里"same-filled page 直接存"的机制已迁出 zswap，零页由 `is_folio_zero_filled` + `swap_zeromap_folio_set` 在 `swap_writeout` 中先于 zswap 处理（`page_io.c:273`）。也**没有** `zswap_zpool` 参数：zsmalloc 是唯一且硬编码的后端。

`/sys/kernel/debug/zswap/`（`zswap_debugfs_init`，`zswap.c:1717`）暴露：`pool_limit_hit`、`reject_reclaim_fail`、`reject_alloc_fail`、`reject_kmemcache_fail`、`reject_compress_fail`、`reject_compress_poor`（`zswap.c:914` 于 `-ENOSPC` 自增）、`decompress_fail`、`written_back_pages`、`pool_total_size`、`stored_pages`、`stored_incompressible_pages`。`reject_compress_poor` 高说明很多页压完不划算（接近原大小），`written_back_pages` 高说明池满回写频繁。

## Interaction with the MM Chain

- **vs [Reclaim](/docs/CS/OS/Linux/mm/Reclaim.md?id=shrink_folio_list-decision-tree-for-keeping-or-evicting-a-single-page)**：匿名页回收经 `shrink_folio_list → pageout → swap_writeout`，在 `swap_writeout` 内先 `zswap_store`（`page_io.c:285`）；store 成功即不落盘。这正是"匿名页先压缩再换出"的完整路径——压缩池占用的是**内存**，所以 `max_pool_percent` 实质是在"省 swap IO"与"占内存"之间取平衡。
- **vs [memcg](/docs/CS/OS/Linux/mm/memcg.md?id=limit-interface-cgroup-v2)**：`memory.zswap.{max,current,writeback}` 三接口把压缩缓存纳入 cgroup 记账，容器场景可单独限某组的压缩占用。
- **vs [Swap](/docs/CS/OS/Linux/Swap.md)**：zswap 是 swap 设备的**前端**，不是 swap 本身；store 失败时最终仍走 `__swap_writepage` 落到真实设备。
- **zswap vs zram**：zram 在 `drivers/block/zram/` 是压缩块设备、自身即 swap 后端；zswap 不取代 swap 设备，只是它前面的一层压缩缓存，两者代码层无共用抽象。

## Versions and Changes

- 引入版本：3.11（2013）。**默认不启用**。
- v7.2 已确认的变化（与旧资料差异大）：
  1. **folio 化**：`zswap_store/load` 收 `struct folio *`（`zswap.c:1477` / `:1583`）；
  2. **multi-tree xarray**：`zswap_trees[]`（`:200`）取代单一 rbtree；
  3. **zpool 抽象 + zbud 后端移除**：`struct zs_pool` 直接内嵌（`:154`）；
  4. **memcg-aware shrinker**：`zswap_shrinker` + `zswap_list_lru`（`list_lru_init_memcg`，`:1786`）取代旧自有 shrinker；
  5. **`swap_writepage` → `swap_writeout`** 重命名（`page_io.c:251` / `:285`）；
  6. **same-filled → swap zeromap**：零页改走 `swap_zeromap_folio_set`；
  7. **大 folio**：store 逐页循环、load 拒绝大 folio（`:1601`）。

## Links

- [内存管理知识地图（mm 枢纽）](/docs/CS/OS/Linux/mm/README.md)
- [内存回收 Reclaim](/docs/CS/OS/Linux/mm/Reclaim.md?id=shrink_folio_list-decision-tree-for-keeping-or-evicting-a-single-page) — 匿名页换出先经 zswap_store
- [cgroup 内存控制 memcg](/docs/CS/OS/Linux/mm/memcg.md?id=limit-interface-cgroup-v2) — memory.zswap.* 三接口
- [Swap 交换](/docs/CS/OS/Linux/Swap.md) — zswap 是 swap 设备的前端缓存

## References

1. [zswap (admin-guide)](https://www.kernel.org/doc/html/latest/admin-guide/mm/zswap.html)
2. [LWN — The compression ratio (zswap 压缩基准讨论)](https://lwn.net/Articles/751795/)
3. [zswap 补丁检索 (lore.kernel.org)](https://lore.kernel.org/linux-mm/?q=zswap)
