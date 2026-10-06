## Introduction

传统 [内存回收](/docs/CS/OS/Linux/mm/Reclaim.md) 建立在 active / inactive 两条 LRU 之上。这套模型在大内存机器上有两个越来越明显的问题：

- **判定冷热靠链表移动，代价高且粗糙**。一个页被访问后，要在 LRU lock 下从 inactive 搬到 active；为了决定谁该被回收，内核还得反复扫描大批页。TB 级内存上，链表本身和扫描开销都很可观。
- **"最近是否用过"信息利用不充分**。传统 LRU 主要靠页的 accessed / referenced 位做有限的二次机会判断，对"通过页表被访问"和"通过文件描述符被访问"两种热度区分不足，容易把还在工作集里的页换出去，随后又 **refault**（刚回收又被读回）。

多代 LRU（Multi-Gen LRU，简称 MGLRU，内核 6.1 合入）针对这两点重造：把可回收页按"**代（generation）**"组织，越年轻的代越热，回收时优先扫描最老的代；判断一页在某代内有没有被用过，则直接批量**走查页表、读 accessed 位**，而不是频繁移动链表。本篇讲清它的结构、老化与驱逐两条主线。

## generation 与滑动窗口

MGLRU 的核心数据结构是挂在 lruvec 上的 `struct lru_gen_folio`（定义见 `include/linux/mmzone.h`）。它用两个单调递增的序号划定一个**滑动窗口**：

```c
#define MIN_NR_GENS		2U
#define MAX_NR_GENS		4U

struct lru_gen_folio {
	/* the aging increments the youngest generation number */
	unsigned long max_seq;
	/* the eviction increments the oldest generation numbers */
	unsigned long min_seq[ANON_AND_FILE];
	/* the birth time of each generation in jiffies */
	unsigned long timestamps[MAX_NR_GENS];
	/* the multi-gen LRU lists, lazily sorted on eviction */
	struct list_head folios[MAX_NR_GENS][ANON_AND_FILE][MAX_NR_ZONES];
	/* the multi-gen LRU sizes, eventually consistent */
	long nr_pages[MAX_NR_GENS][ANON_AND_FILE][MAX_NR_ZONES];
	...
	bool enabled;
};
```

- `max_seq` 是**最年轻代**的编号，新页（fault 进来的页）进这一代；
- `min_seq[]` 是**最老代**的编号，驱逐从这一代开始，每驱逐完一代就把它 +1；
- 二者之间最多保留 `MAX_NR_GENS`（4）代、最少 `MIN_NR_GENS`（2）代。`seq % MAX_NR_GENS` 得到的 `gen` 才是真正索引链表的下标。

为什么最少两代？因为要给页**二次机会**：第一次看到 accessed 位可能只是初始 fault 时设置的，必须清掉后再观察一轮，确认它此后没被用过才能驱逐（内核注释里明确要求 aging 至少检查两次 accessed 位）。这与传统 active/inactive 的二次机会语义一脉相承——事实上为了兼容 `/proc/vmstat`，最年轻的两代被算作 "active"，其余算 "inactive"。

> `min_seq` 对匿名和文件分开记录（`min_seq[ANON_AND_FILE]`），因为干净文件页不受 swap 限制、总能驱逐；当 swap 空间不足时，允许文件页的 `min_seq` 单独前进、把匿名页甩在后面。

## tier：文件描述符访问热度

除了按"代"区分新旧，MGLRU 还在每代内部按 **tier（层级）** 区分"通过文件描述符被反复访问"的热度：

```c
#define MAX_NR_TIERS		4U
```

一个页通过 fd 被访问 N 次，就落在第 `order_base_2(N)` 层。关键好处是**跨 tier 只改 folio->flags 上的位、不用拿 LRU lock**，所以 buffered I/O 热路径上几乎零成本；驱逐时再用 `avg_refaulted` / `avg_total` 的指数移动平均，统计反复 refault 的页是不是真热点、值不值得保护。代（时间维度）+ 层（fd 访问维度）共同刻画了一页的冷热。

## aging：走查页表、推进新生代

回收要解决的第一个问题是"哪些页其实还在被用"。MGLRU 的 **aging（老化）** 不搬链表，而是批量**走查各进程的页表**：对页表项读 accessed（young）位——

- accessed 位被置过，说明这一轮里页被访问过，把它**提升到更年轻的代**（`folio_inc_gen()`）；随后清掉 accessed 位，等下一轮再观察；
- accessed 位没被置，说明页确实冷，留在老代，等驱逐。

走查由 `lru_gen_mm_walk` 结构记录进度（下一个待扫描地址、批量提升的页数等），并用 Bloom filter 快速过滤"这一轮根本没出现在页表里的页"。需要时既清叶子 PTE 的 accessed 位、也清非叶子 PMD/PUD 的 accessed 位（对应开关里的两个独立位）。`folio_inc_gen()` 用 cmpxchg 无锁地改 `folio->flags` 上的代编号：

```c
do {
    new_gen = ((old_flags & LRU_GEN_MASK) >> LRU_GEN_PGOFF) - 1;
    if (new_gen >= 0 && new_gen != old_gen)
        return new_gen;                 /* 已被提升 */
    new_gen = (old_gen + 1) % MAX_NR_GENS;
    new_flags = old_flags & ~(LRU_GEN_MASK | LRU_REFS_MASK | LRU_REFS_FLAGS);
    new_flags |= (new_gen + 1UL) << LRU_GEN_PGOFF;
} while (!try_cmpxchg(&folio->flags, &old_flags, new_flags));
```

aging 被刻意做得**懒惰**：`should_run_aging()` 检查代的数量与各代页的分布，理想状态是保持 `MIN_NR_GENS+1` 代、每页均匀分布，没到需要老化的程度就不扫，以此把页表走查的开销降到最低。

## eviction：从最老代驱逐

第二个问题是"真正要回收时回收谁"。**eviction（驱逐）** 经 `lru_gen_shrink_lruvec()` → `try_to_shrink_lruvec()` → `evict_folios()`，从 `min_seq` 指向的最老代开始取页。代内的链表是**懒排序**的（注释 "lazily sorted on eviction"）——平时不维护顺序，只在要驱逐时才对这一批页整理，省掉了传统 LRU 持续的链表维护。

驱逐对页的最终处置，仍复用传统回收的判定：干净文件页直接释放、脏页先回写、匿名页换出到 [Swap](/docs/CS/OS/Linux/Swap.md)。驱逐完一整代后把 `min_seq` 推进，下一轮再从更年轻的代取。这与 NUMA hinting / 内存压缩的页迁移也有协作：页被隔离迁移时会从代链表上摘下（见 `lru_gen_add_folio` / `lru_gen_del_folio`）。

## 与传统 LRU 的对照

| 维度 | 传统 active/inactive LRU | MGLRU |
| --- | --- | --- |
| 冷热划分 | 两态（active / inactive） | 最多 4 代 × 4 层 |
| 热度依据 | referenced 位 + 链表移动 | 页表 accessed 位批量走查 |
| 链表维护 | 持续移动、需 LRU lock | 代内懒排序，跨代/跨层多用原子位 |
| 二次机会 | active 链表有限保护 | 至少两代 + aging 两轮检查 |
| 大内存适配 | 扫描与链表开销高 | Bloom filter + 懒惰 aging，扫描更省 |
| 可观测兼容 | native | 最年轻两代映射为 active 计数 |

## 接口与调优

通过 `/sys/kernel/mm/lru_gen/` 控制，`enabled` 是个位掩码：

| 位 | 含义 |
| --- | --- |
| `0x0001` | MGLRU 主开关 |
| `0x0002` | aging 时清叶子 PTE 的 accessed 位 |
| `0x0004` | aging 时清非叶子 PMD/PUD 的 accessed 位 |

全开时读出 `0x0007`。另有 `min_ttl_ms`：写入 N 可保护工作集 N 毫秒内不被驱逐，用于压住抖动型负载的过早回收。需要 `CONFIG_LRU_GEN` 编译支持，启用还需 `CONFIG_LRU_GEN_ENABLED`；未启用或不支持的位会被忽略。运行统计仍走 `/proc/vmstat`，refault 相关字段是评估"回收是否误伤工作集"的关键口径。

## Links

- [内存管理知识地图](/docs/CS/OS/Linux/mm/README.md)
- [虚拟内存](/docs/CS/OS/Linux/mm/vm.md)

## References

1. [Multi-Gen LRU — kernel.org admin guide](https://www.kernel.org/doc/html/latest/admin-guide/mm/multigen_lru.html)
2. [Multi-Gen LRU design document](https://www.kernel.org/doc/html/latest/mm/multigen_lru.html)
3. [The multi-generational LRU — lwn.net](https://lwn.net/Articles/856931/)
