## Introduction

maple tree 是内核里用于**把区间映射到指针**的数据结构：key 不是一个整数下标，而是一段闭区间 `[index, last]`，value 是一个指针。它从 6.1 起进入主线，第一个也是最重的用户是进程地址空间——[VMA](/docs/CS/OS/Linux/mm/vm.md?id=vma) 的管理从「红黑树 + 双向链表」换成 `struct mm_struct` 里的 `mm_mt`。

它的定位可以用一句话概括：**一棵 RCU 安全的、节点类型可变的 B 树变体**。RCU 安全意味着读侧可以不拿锁（这正是替换红黑树的核心动机），节点类型可变意味着同一棵树能在"叶子存数据 / 内部存子节点 / 记账空洞"几种形态间按需切换。

本文源码取自本地内核源码树 `/Users/robin/Tools/linux-7.2.7`（v7.2.7），涉及 `include/linux/maple_tree.h` 与 `lib/maple_tree.c`（7050 行）。

## 为什么 VMA 不能继续用红黑树

红黑树索引 VMA 的方式是：拿 `vm_start` 当 key 插入一棵 rbtree。这个方案在内核里躺了二十年，问题也积累了同样久，归纳起来是三条：

| 红黑树的短板 | 后果 |
| --- | --- |
| 只能索引**点**，表达不了区间 | 一个 VMA 本质是 `[vm_start, vm_end]` 区间，红黑树只认 `vm_start`，区间的"长度"与"相邻关系"得靠比较函数和调用方自己兜 |
| rebalance 会**同时改动多个节点** | 读侧无法无锁遍历，只能整棵树加 `mmap_lock`（读写信号量）；多线程程序频繁查 VMA，锁争抢明显 |
| 遍历成本高 | 光有树还不够，另需一条双向链表把所有 VMA 串起来供顺序遍历，两套结构要同步维护 |

maple tree 针对这三点分别给出答案：

1. **区间是一等公民**：节点里存的是 pivot（区间端点），一次查找直接得到"这个地址落在哪个区间、区间边界是什么"。
2. **写侧整节点替换**：树在 RCU 模式下做写操作时，不原地修改节点，而是分配一个新节点、拷贝内容、一次性替换父节点里的指针，旧节点等 RCU 宽限期过后释放。读侧要么看到旧节点、要么看到新节点，不会看到中间态，因此可以不拿锁。
3. **遍历即前序/后序游走**：`ma_state` 游标在树上前后移动（`mas_next` / `mas_prev` / `mas_find`），不需要额外的链表。

需要澄清一个常见误解：maple tree **不是** xarray 的替代品。页缓存（`address_space->i_pages`）仍用 xarray——它是下标索引、扇出固定为 64 的 radix 树，擅长"按 offset 查 page"；maple tree 擅长"按区间查对象、且要找空洞"。两者在内核里并存。

## 节点：256 字节里的四种形态

所有 maple 节点都装在同一个 256 字节的 `struct maple_node` 里，靠 union 解释成不同形态：

```c
struct maple_node {
	union {
		struct {
			struct maple_pnode *parent;
			void __rcu *slot[MAPLE_NODE_SLOTS];
		};
		struct {
			void *pad;
			struct rcu_head rcu;
			struct maple_enode *piv_parent;
			unsigned char parent_slot;
			enum maple_type type;
			unsigned char slot_len;
			unsigned int ma_flags;
		};
		struct maple_range_64 mr64;
		struct maple_arange_64 ma64;
		struct maple_copy cp;
	};
};
```

第二个视图是给"回收中的节点"用的：节点从树上摘下后，`slot[]` 数组不再有意义，于是把这块空间复用成 `rcu_head` 等字段——这就是头文件里那句"lets us reuse the slots array for the RCU head"。

节点按 256 字节对齐，槽位数由 `sizeof` 反推出来：

```c
#if defined(CONFIG_64BIT) || defined(BUILD_VDSO32_64)
/* 64bit sizes */
#define MAPLE_NODE_SLOTS	31	/* 256 bytes including ->parent */
#define MAPLE_RANGE64_SLOTS	16	/* 256 bytes */
#define MAPLE_ARANGE64_SLOTS	10	/* 240 bytes */
#define MAPLE_ALLOC_SLOTS	(MAPLE_NODE_SLOTS - 1)
#else
/* 32bit sizes */
#define MAPLE_NODE_SLOTS	63	/* 256 bytes including ->parent */
#define MAPLE_RANGE64_SLOTS	32	/* 256 bytes */
#define MAPLE_ARANGE64_SLOTS	21	/* 240 bytes */
#define MAPLE_ALLOC_SLOTS	(MAPLE_NODE_SLOTS - 2)
#endif
```

于是 64 位机上：叶子/内部节点各 16 个 slot、15 个 pivot；带空洞记账的内部节点（arange64）用 10 个 slot、9 个 pivot，空出来的字节正好放 `gap[10]`。这也是很多资料里"叶子最多 16 项、内部最多 10 项"说法的由来。

### pivot 与 slot 的对应

B 树里叫 key 的东西，maple tree 叫 **pivot**，原因是它描述的是区间而非唯一点：pivot 与同下标 slot 的取值是**闭区间包含**关系。源码开头的注释画得很清楚：

```
 Slots -> | 0 | 1 | 2 | ... | 12 | 13 | 14 | 15 |
          ┬   ┬   ┬   ┬     ┬    ┬    ┬    ┬    ┬
          │   │   │   │     │    │    │    │    └─ Implied maximum
          │   │   │   │     │    │    │    └─ Pivot 14
          │   │   │   │     │    └─ Pivot 13
          │   │   │   │     └─ Pivot 12
          │   │   │   └─ Pivot 2
          │   │   └─ Pivot 1
          │   └─ Pivot 0
          └─  Implied minimum
```

即：slot[i] 覆盖的区间是 `pivot[i-1]+1 .. pivot[i]`，两端由父节点（或根节点的 `0` 与 `ULONG_MAX`）隐含给出。所以 16 个 slot 只需要 15 个 pivot。

### 四种节点类型

```c
enum maple_type {
	maple_dense,
	maple_leaf_64,
	maple_range_64,
	maple_arange_64,
	maple_copy,
};
```

| 类型 | 用途 | pivot | 备注 |
| --- | --- | --- | --- |
| `maple_dense` | 索引**连续**分布的稠密数据（如页缓存按 offset 排布） | 无，隐含为 `slot 下标 + node min` | `mt_pivots[]` 里记为 0 |
| `maple_leaf_64` | 叶子，slot 存用户数据 | 15 个 | `ma_is_leaf()` 判定为 `type < maple_range_64` |
| `maple_range_64` | 内部节点，slot 指向子节点 | 15 个 | 最常见形态 |
| `maple_arange_64` | 内部节点 + 空洞记账 | 9 个 | 额外 `gap[10]`，只在 `MT_FLAGS_ALLOC_RANGE` 树上出现 |
| `maple_copy` | 写路径的**临时模拟节点** | 3 个 | 不在树中，用于 spanning store 的一次性计算 |

`ma_is_leaf()` / `ma_is_dense()` 之所以能用 `<` 比较，是因为 `enum maple_type` 的取值顺序被刻意安排成"稠密 < 叶子 < 内部"。

### metadata：避免每次都扫描

每个节点（除 dense）尾部带两个字节的元数据：

```c
struct maple_metadata {
	unsigned char end;	/* end of data */
	unsigned char gap;	/* offset of largest gap */
};
```

`end` 记录节点里最后一个有效 slot 的下标，`gap` 记录最大空洞所在的偏移。查找"节点末尾在哪"、更新空洞时就不必扫描整个 pivot 数组。

## 位编码：指针里挤出来的信息

maple tree 大量使用"指针对齐、低位空闲"的技巧。节点 256 字节对齐，低 8 位（`MAPLE_NODE_MASK = 255UL`）全部可以做标记：

- **parent 指针**：若 bit 0 置位，说明这是根节点，其余位指向所属的 `struct maple_tree`；否则是非根节点，低位存放本节点在父节点中的 slot，bit 3-6 存放父节点的 `enum maple_type`（`MAPLE_NODE_TYPE_SHIFT = 3`）。
- **ma_root**：树里只有 index 0 的单个条目时，可以直接把数据指针塞进 `ma_root`，省掉一次节点访问。但不是所有值都能这么做——低两位为 `10` 的值会被强制放进节点，且内核保留小于 4096（`MAPLE_RESERVED_RANGE`）且低两位为 `10` 的值自用。

```c
struct maple_tree {
	union {
		spinlock_t		ma_lock;
#ifdef CONFIG_LOCKDEP
		struct lockdep_map	*ma_external_lock;
#endif
	};
	unsigned int	ma_flags;
	void __rcu      *ma_root;
};
```

`ma_flags` 同时承担静态属性与动态状态两类信息：

```c
#define MT_FLAGS_ALLOC_RANGE	0x01
#define MT_FLAGS_USE_RCU	0x02
#define MT_FLAGS_HEIGHT_OFFSET	0x02
#define MT_FLAGS_HEIGHT_MASK	0x7C
#define MT_FLAGS_LOCK_MASK	0x300
#define MT_FLAGS_LOCK_IRQ	0x100
#define MT_FLAGS_LOCK_BH	0x200
#define MT_FLAGS_LOCK_EXTERN	0x300
#define MT_FLAGS_ALLOC_WRAPPED	0x0800

#define MAPLE_HEIGHT_MAX	31
```

- `MT_FLAGS_ALLOC_RANGE`：这棵树需要跟踪空洞（gap），内部节点会用 arange64。
- `MT_FLAGS_USE_RCU`：当前处于 RCU 模式，写操作要整节点替换。这个标志是**动态的**，可以在运行时用 `mt_set_in_rcu()` / `mt_clear_in_rcu()` 切换，当树上只有一个使用者时就关掉它、允许原地复用节点。
- `MT_FLAGS_LOCK_EXTERN`：不用内部的 `ma_lock`，改由调用者的锁保护（mmap 场景就是 `mmap_lock`），配合 lockdep 的 `ma_external_lock` 做持有检查。
- `MT_FLAGS_HEIGHT_MASK`：树的高度直接编在 flags 里，`mt_height()` 取出来即可。

## 游标 ma_state：一次操作的全部上下文

maple tree 的 API 分两层：简单 API（`mtree_load` / `mtree_store` / `mtree_insert` …）每次从根开始；高级 API 则用 `struct ma_state` 作为游标，**跨多次操作保留位置**，避免重复下降。

```c
struct ma_state {
	struct maple_tree *tree;	/* The tree we're operating in */
	unsigned long index;		/* The index we're operating on - range start */
	unsigned long last;		/* The last index we're operating on - range end */
	struct maple_enode *node;	/* The node containing this entry */
	unsigned long min;		/* The minimum index of this node - implied pivot min */
	unsigned long max;		/* The maximum index of this node - implied pivot max */
	struct slab_sheaf *sheaf;	/* Allocated nodes for this operation */
	struct maple_node *alloc;	/* A single allocated node for fast path writes */
	unsigned long node_request;	/* The number of nodes to allocate for this operation */
	enum maple_status status;	/* The status of the state (active, start, none, etc) */
	unsigned char depth;		/* depth of tree descent during write */
	unsigned char offset;
	unsigned char mas_flags;
	unsigned char end;		/* The end of the node */
	enum store_type store_type;	/* The type of store needed for this operation */
};
```

`min` / `max` 是当前节点的**隐含边界**（来自父节点的 pivot），`offset` 是节点内关心的槽位，`index` / `last` 在返回时被回填成命中的完整区间。这就是高级 API 能"一次调用拿到区间"的原因。

`status` 有九种取值，决定了下一次动作如何看待这份状态：

| status | 含义 |
| --- | --- |
| `ma_start` | 还没开始走，下次动作从根下降 |
| `ma_active` | 正指向树中某个节点与槽位，可继续操作 |
| `ma_root` | 查到的条目就住在 `ma_root` 里（index 0 的单条目树） |
| `ma_none` | 走完了，树上没有对应条目 |
| `ma_pause` | 数据可能已失效，需要重走 |
| `ma_overflow` / `ma_underflow` | 触到了搜索上界 / 下界 |
| `ma_error` | 出错，`node` 里编着 errno |

初始化用宏 `MA_STATE(name, mt, first, end)`，把 `min` 设为 0、`max` 设为 `ULONG_MAX`、`status` 设为 `ma_start`。

## 查找：从根下降到叶子

`mas_start()` 先把三种树形态分开：

```c
static inline struct maple_enode *mas_start(struct ma_state *mas)
{
	if (likely(mas_is_start(mas))) {
		struct maple_enode *root;

		mas->min = 0;
		mas->max = ULONG_MAX;

retry:
		mas->depth = 0;
		root = mas_root(mas);
		/* Tree with nodes */
		if (likely(xa_is_node(root))) {
			mas->depth = 0;
			mas->status = ma_active;
			mas->node = mte_safe_root(root);
			mas->offset = 0;
			if (mte_dead_node(mas->node))
				goto retry;

			return NULL;
		}

		mas->node = NULL;
		/* empty tree */
		if (unlikely(!root)) {
			mas->status = ma_none;
			mas->offset = MAPLE_NODE_SLOTS;
			return NULL;
		}

		/* Single entry tree */
		mas->status = ma_root;
		mas->offset = MAPLE_NODE_SLOTS;

		/* Single entry tree. */
		if (mas->index > 0)
			return NULL;

		return root;
	}

	return NULL;
}
```

往下走一层由 `mas_descend()` 完成，它同时把隐含边界收紧——这正是"pivot 区间"语义的体现：

```c
static inline void mas_descend(struct ma_state *mas)
{
	node = mas_mn(mas);
	type = mte_node_type(mas->node);
	pivots = ma_pivots(node, type);
	slots = ma_slots(node, type);

	if (mas->offset)
		mas->min = pivots[mas->offset - 1] + 1;
	mas->max = mas_safe_pivot(mas, pivots, mas->offset, type);
	mas->node = mas_slot(mas, slots, mas->offset);
}
```

往上的 `mas_ascend()` 要麻烦得多：节点的 `min`/`max` 是隐含的，可能需要连升若干层才能定出边界，途中若撞上死节点（并发写正在替换它）就返回 1，让调用方重走。

只读快速路径 `mtree_lookup_walk()` 连 `ma_state` 都不维护完整，只是逐层线性扫 pivot 找 offset：

```c
	next = mas->node;
	do {
		node = mte_to_node(next);
		type = mte_node_type(next);
		pivots = ma_pivots(node, type);
		end = mt_pivots[type];
		offset = 0;
		do {
			if (pivots[offset] >= mas->index)
				break;
		} while (++offset < end);

		slots = ma_slots(node, type);
		next = mt_slot(mas->tree, slots, offset);
		if (unlikely(ma_dead_node(node)))
			goto dead_node;
	} while (!ma_is_leaf(type));

	return (void *)next;

dead_node:
	mas_reset(mas);
	return NULL;
```

注意 pivot 数组只有 15 项、每项 8 字节，线性扫描比二分更划算（cache 友好）。

## RCU：读侧不拿锁的代价与实现

maple tree 的读侧并发靠两件事：**写侧整节点替换** + **读侧死节点检测**。

死节点的判定极其巧妙：节点被摘下时，把它的 `parent` 改成指向**它自己**。

```c
static __always_inline bool ma_dead_node(const struct maple_node *node)
{
	struct maple_node *parent;

	/* Do not reorder reads from the node prior to the parent check */
	smp_rmb();
	parent = (void *)((unsigned long) node->parent & ~MAPLE_NODE_MASK);
	return (parent == node);
}
```

读侧先读 slot 内容、再检查 parent 是否指向自身（中间用 `smp_rmb()` 阻止读重排），是就说明读到的是一个已被替换掉的旧节点，重走一遍即可。

写侧的替换逻辑在 `mas_wr_node_store()` 里体现得最直白：

```c
	/* set up node. */
	if (in_rcu) {
		newnode = mas_pop_node(mas);
	} else {
		memset(&reuse, 0, sizeof(struct maple_node));
		newnode = &reuse;
	}
	...
done:
	mas_leaf_set_meta(newnode, maple_leaf_64, new_end);
	if (in_rcu) {
		struct maple_enode *old_enode = mas->node;

		mas->node = mt_mk_node(newnode, wr_mas->type);
		mas_replace_node(mas, old_enode, mas_mt_height(mas));
	} else {
		memcpy(wr_mas->node, newnode, sizeof(struct maple_node));
	}
```

RCU 模式下：分配新节点 → 分三段拷贝（插入点之前、新条目、插入点之后）→ 一次性挂进树并把旧节点标记死亡；非 RCU 模式下直接 `memcpy` 覆盖原节点，省掉一次分配。

旧节点的释放走 RCU 回调：

```c
static void ma_free_rcu(struct maple_node *node)
{
	WARN_ON(node->parent != ma_parent_ptr(node));
	kfree_rcu(node, rcu);
}
```

代价也很明确——RCU 模式下**不能在原地追加**，源码注释写得很清楚：

```c
/*
 * mas_wr_append: Attempt to append
 * @wr_mas: the maple write state
 *
 * This is currently unsafe in rcu mode since the end of the node may be cached
 * by readers while the node contents may be updated which could result in
 * inaccurate information.
 */
```

所以在 `mas_wr_store_type()` 里，append 分支额外要求 `!mt_in_rcu(mas->tree)`。

## 写路径：先分类，再预分配，最后落位

一次写操作被拆成三步，核心思想是**写之前就知道要几个节点**，把内存分配挪到持锁之前（或允许睡眠的时机）完成：

```c
static inline void mas_wr_preallocate(struct ma_wr_state *wr_mas, void *entry)
{
	struct ma_state *mas = wr_mas->mas;

	mas_wr_prealloc_setup(wr_mas);
	mas->store_type = mas_wr_store_type(wr_mas);
	mas_prealloc_calc(wr_mas, entry);
	if (!mas->node_request)
		return;

	mas_alloc_nodes(mas, GFP_NOWAIT);
}
```

### 第一步：分类

`enum store_type` 有九种，写操作首先要判断自己属于哪一类：

```c
enum store_type {
	wr_invalid,
	wr_new_root,
	wr_store_root,
	wr_exact_fit,
	wr_spanning_store,
	wr_split_store,
	wr_rebalance,
	wr_append,
	wr_node_store,
	wr_slot_store,
};
```

判定逻辑是一棵决策树（`mas_wr_store_type()`）：

```c
	if (unlikely(mas_is_none(mas) || mas_is_ptr(mas)))
		return wr_store_root;

	if (unlikely(!mas_wr_walk(wr_mas)))
		return wr_spanning_store;

	/* At this point, we are at the leaf node that needs to be altered. */
	mas_wr_end_piv(wr_mas);
	if (!wr_mas->entry)
		mas_wr_extend_null(wr_mas);

	if ((wr_mas->r_min == mas->index) && (wr_mas->r_max == mas->last))
		return wr_exact_fit;

	if (unlikely(!mas->index && mas->last == ULONG_MAX))
		return wr_new_root;

	new_end = mas_wr_new_end(wr_mas);
	/* Potential spanning rebalance collapsing a node */
	if (new_end < mt_min_slots[wr_mas->type]) {
		if (!mte_is_root(mas->node))
			return  wr_rebalance;
		return wr_node_store;
	}

	if (new_end >= mt_slots[wr_mas->type])
		return wr_split_store;

	if (!mt_in_rcu(mas->tree) && (mas->offset == mas->end))
		return wr_append;

	if ((new_end == mas->end) && (!mt_in_rcu(mas->tree) ||
		(wr_mas->offset_end - mas->offset == 1)))
		return wr_slot_store;

	return wr_node_store;
```

读法是从便宜到昂贵：能原地改最好（`exact_fit` / `append` / `slot_store`），实在不行才动结构。其中 `new_end` 是"写完之后这个节点会有多少个 slot"，用它和两类阈值比较——低于 `mt_min_slots[]` 说明节点太空、需要向邻居借（rebalance）；达到 `mt_slots[]` 说明装不下、需要分裂（split）。两个阈值分别是 6 和 16（`range_64`：`16/2-2` 与 `16`）。

### 第二步：算要几个节点

```c
	switch (mas->store_type) {
	case wr_exact_fit:
	case wr_append:
	case wr_slot_store:
		ret = 0;
		break;
	case wr_spanning_store:
		if (wr_mas->sufficient_height < wr_mas->vacant_height)
			ret = (height - wr_mas->sufficient_height) * 3 + 1;
		else
			ret = delta * 3 + 1;
		break;
	case wr_split_store:
		ret = delta * 2 + 1;
		break;
	case wr_rebalance:
		...
	case wr_node_store:
		ret = mt_in_rcu(mas->tree) ? 1 : 0;
		break;
	case wr_new_root:
		ret = 1;
		break;
	...
	}

	mas->node_request = ret;
```

默认是 `height * 3 + 1`（最坏情况每层都可能分裂成三份）。原地写不用分配；RCU 下的 `node_store` 固定只要 1 个（换掉一个节点）。

### 节点从哪来：slab sheaf 批量预取

v7.2.7 里 maple 节点的分配已经改用 slab 的 **sheaf** 机制（一次预取一批对象，避免写路径上反复调用分配器）。`ma_state` 里的 `sheaf` 字段就是为此而设：

```c
void __init maple_tree_init(void)
{
	struct kmem_cache_args args = {
		.align  = sizeof(struct maple_node),
		.sheaf_capacity = 32,
	};

	maple_node_cache = kmem_cache_create("maple_node",
			sizeof(struct maple_node), &args,
			SLAB_PANIC);
}
```

取节点时优先从 sheaf 里拿，拿不到才退回单个分配：

```c
static __always_inline struct maple_node *mas_pop_node(struct ma_state *mas)
{
	struct maple_node *ret;

	if (mas->alloc) {
		ret = mas->alloc;
		mas->alloc = NULL;
		goto out;
	}

	if (WARN_ON_ONCE(!mas->sheaf))
		return NULL;

	ret = kmem_cache_alloc_from_sheaf(maple_node_cache, GFP_NOWAIT, mas->sheaf);

out:
	memset(ret, 0, sizeof(*ret));
	return ret;
}
```

### 第三步：分配不到怎么办

写操作通常持着锁（可能是 spinlock），不能睡眠分配。于是 `mas_alloc_nodes()` 一律先用 `GFP_NOWAIT` 试，失败就把 `mas->node` 编成 `-ENOMEM`，交给 `mas_nomem()` 处理：允许睡眠且锁是自己的（非外部锁）时，**放锁 → 用调用方的 gfp 分配 → 重新持锁 → 重走**。

```c
bool mas_nomem(struct ma_state *mas, gfp_t gfp)
	__must_hold(mas->tree->ma_lock)
{
	if (likely(mas->node != MA_ERROR(-ENOMEM)))
		return false;

	if (gfpflags_allow_blocking(gfp) && !mt_external_lock(mas->tree)) {
		mtree_unlock(mas->tree);
		mas_alloc_nodes(mas, gfp);
		mtree_lock(mas->tree);
	} else {
		mas_alloc_nodes(mas, gfp);
	}

	if (!mas->sheaf && !mas->alloc)
		return false;

	mas->status = ma_start;
	return true;
}
```

`mas_store_gfp()` 就是围着它写的一个 `retry` 循环：

```c
retry:
	mas_wr_preallocate(&wr_mas, entry);
	if (unlikely(mas_nomem(mas, gfp))) {
		if (!entry)
			__mas_set_range(mas, index, last);
		goto retry;
	}

	if (mas_is_err(mas)) {
		ret = xa_err(mas->node);
		goto out;
	}

	mas_wr_store_entry(&wr_mas);
```

调用方也可以反过来做：先 `mas_preallocate()` 把节点备好，再在绝不失败的上下文里 `mas_store_prealloc()`（VMA 操作就大量使用这个模式）。

### 落位：九种 store 各走各的路

```c
	switch (mas->store_type) {
	case wr_exact_fit:
		rcu_assign_pointer(wr_mas->slots[mas->offset], wr_mas->entry);
		if (!!wr_mas->entry ^ !!wr_mas->content)
			mas_update_gap(mas);
		break;
	case wr_append:
		mas_wr_append(wr_mas);
		break;
	case wr_slot_store:
		mas_wr_slot_store(wr_mas);
		break;
	case wr_node_store:
		mas_wr_node_store(wr_mas);
		break;
	case wr_spanning_store:
		mas_wr_spanning_store(wr_mas);
		break;
	case wr_split_store:
		mas_wr_split(wr_mas);
		break;
	case wr_rebalance:
		mas_wr_rebalance(wr_mas);
		break;
	case wr_new_root:
		mas_new_root(mas, wr_mas->entry);
		break;
	case wr_store_root:
		mas_store_root(mas, wr_mas->entry);
		break;
	case wr_invalid:
		MT_BUG_ON(mas->tree, 1);
	}
```

三种"轻活"值得单独看：

- **`wr_exact_fit`**：新区间与已有区间完全重合，一次 `rcu_assign_pointer` 搞定，只有在"从空变非空"或反向变化时才更新 gap。
- **`wr_slot_store`**：区间只跨了相邻两个 slot，改 1~2 个 pivot 即可，`mas->offset++` 保持游标准确。
- **`wr_append`**：在节点末尾追加，把新 pivot 写到 `new_end`、更新 metadata 的 `end`，全程原地完成——这是 RCU 模式唯一不能走的路径。

三种"重活"分别是**分裂**（节点满）、**再平衡**（节点太空，先向邻居借，借不到才分裂）、**跨节点写**（一次 store 覆盖多个节点）。第三种最复杂：maple tree 不逐个节点修改，而是用一个临时结构 `struct maple_copy` 同时模拟最多 3 个目标节点和 4 个源节点，一次算清所有 pivot 与 slot，再整体落位。

被摘下来的节点不能立刻释放（RCU 读者可能还在上面），于是串进一个"修剪清单"：

```c
/*
 * More complicated stores can cause two nodes to become one or three and
 * potentially alter the height of the tree.  Either half of the tree may need
 * to be rebalanced against the other.  The ma_topiary struct is used to track
 * which nodes have been 'cut' from the tree so that the change can be done
 * safely at a later date.  This is done to support RCU.
 */
struct ma_topiary {
	struct maple_enode *head;
	struct maple_enode *tail;
	struct maple_tree *mtree;
};
```

（topiary 本义是"修剪造型的灌木"，这里借指"剪下来待处理的节点串"。）

## gap：为空洞搜索付出的记账成本

有些树不仅要"查区间"，还要"找一段够大的空隙"——VMA 布局就是典型。`MT_FLAGS_ALLOC_RANGE` 打开的正是这项能力，代价是每个 arange64 节点多带一个 `gap[]` 数组：

```c
struct maple_arange_64 {
	struct maple_pnode *parent;
	unsigned long pivot[MAPLE_ARANGE64_SLOTS - 1];
	void __rcu *slot[MAPLE_ARANGE64_SLOTS];
	unsigned long gap[MAPLE_ARANGE64_SLOTS];
	struct maple_metadata meta;
};
```

`gap[i]` 记录 slot[i] 覆盖区间内**最大的一段 NULL 空洞有多大**。更新只在 alloc range 树上做：

```c
static inline void mas_update_gap(struct ma_state *mas)
{
	if (!mt_is_alloc(mas->tree))
		return;

	if (mte_is_root(mas->node))
		return;

	max_gap = mas_max_gap(mas);

	pslot = mte_parent_slot(mas->node);
	p_gap = ma_gaps(mte_parent(mas->node),
			mas_parent_type(mas, mas->node))[pslot];

	if (p_gap != max_gap)
		mas_parent_gap(mas, pslot, max_gap);
}
```

注意它只在父节点记录的值**发生变化**时才向上传播，多数写操作因此不用爬整棵树。

找空洞时，`mas_anode_descend()` 在每个 slot 上先比 `gap` 再决定下降：

```c
	for (; offset <= data_end; offset++) {
		pivot = mas_safe_pivot(mas, pivots, offset, type);

		/* Not within lower bounds */
		if (mas->index > pivot)
			goto next_slot;

		if (gaps)
			gap = gaps[offset];
		else if (!mas_slot(mas, slots, offset))
			gap = min(pivot, mas->last) - max(mas->index, min) + 1;
		else
			goto next_slot;

		if (gap >= size) {
			if (ma_is_leaf(type)) {
				found = true;
				break;
			}

			mas->node = mas_slot(mas, slots, offset);
			mas->min = min;
			mas->max = pivot;
			offset = 0;
			break;
		}
next_slot:
		min = pivot + 1;
		...
	}
```

外层 `mas_awalk()` 在"下降 / 回溯 / 找到 / 失败（-EBUSY）"四态间循环，最终 `mas_empty_area()` 给出最低可用地址，`mas_empty_area_rev()` 给出最高可用地址。

## 内核里的使用者

### 进程地址空间

`mm_struct` 里那棵树的 flags 把三种能力全开了——需要找空洞、锁由调用方（mmap_lock）提供、要支持无锁读：

```c
#define MM_MT_FLAGS	(MT_FLAGS_ALLOC_RANGE | MT_FLAGS_LOCK_EXTERN | \
			 MT_FLAGS_USE_RCU)
```

`find_vma()` 退化成一行 `mt_find`：

```c
struct vm_area_struct *find_vma(struct mm_struct *mm, unsigned long addr)
{
	unsigned long index = addr;

	mmap_assert_locked(mm);
	return mt_find(&mm->mm_mt, &index, ULONG_MAX);
}
```

VMA 迭代器 `struct vma_iterator` 干脆就是 `ma_state` 的一层包装：

```c
struct vma_iterator {
	struct ma_state mas;
};
```

写入走 `vma_iter_store_gfp()`，本质是用 VMA 的起止地址设置区间后调 `mas_store_gfp()`：

```c
	__mas_set_range(&vmi->mas, vma->vm_start, vma->vm_end - 1);
	mas_store_gfp(&vmi->mas, vma, gfp);
	if (unlikely(mas_is_err(&vmi->mas)))
		return -ENOMEM;
```

而 [mmap](/docs/CS/OS/Linux/mm/mmap.md) 布局时的"找一段空闲地址"，正是 gap 机制的用武之地：自低向高的 `unmapped_area()` 调 `vma_iter_area_lowest()`（即 `mas_empty_area()`），自高向低的 `unmapped_area_topdown()` 调 `vma_iter_area_highest()`（即 `mas_empty_area_rev()`）。相比红黑树时代遍历 VMA 链表逐个比对地址窗口，这里一次下降就能定位候选空洞。

### 其他用户

同一套 API 也被用在这些地方：

- `kernel/irq/irqdesc.c`：分配 irq 号，flags 与 `mm_mt` 一致（`ALLOC_RANGE | LOCK_EXTERN | USE_RCU`），典型"从整数空间里找空闲号"的场景。
- `mm/execmem.c`：维护可执行内存（module / bpf trampoline 等）的 busy/free 区间。
- `drivers/iommu/iommufd`、`drivers/gpu/drm/nouveau/nouveau_uvmm`：用户态驱动的虚拟地址/IOVA 空间管理。
- `lib/alloc_tag.c`、`fs/libfs.c`：内核内部的区间记账。

## 与 rbtree、xarray 的取舍

| | rbtree | xarray | maple tree |
| --- | --- | --- | --- |
| 索引对象 | 点（key） | 点（index），有多槽位条目 | 区间 `[index, last]` |
| 结构 | 二叉平衡树 | 固定 64 扇出 radix | B 树变体，节点类型可变 |
| 无锁读 | 不支持（rebalance 影响多节点） | 支持（RCU） | 支持（RCU + 整节点替换） |
| 查找空洞 | 需自行遍历 | 有 `xa_alloc` 系列 | 内建 `gap[]` 记账与 `mas_empty_area()` |
| 遍历 | 需额外链表 | 需 xa_state 游标 | `ma_state` 游标前后移动 |
| 典型用户 | 调度器 CFS、定时器 | 页缓存 `i_pages` | VMA、irq 号、IOVA |

一句话选型：**按整数下标查对象用 xarray，按区间查对象、还要找空洞用 maple tree**；需要严格的顺序语义或自己管锁的场景，rbtree 依然在位。

## 调试与验证

maple tree 自带相当完善的可观测设施：

- `CONFIG_DEBUG_MAPLE_TREE` 打开后，`MT_BUG_ON` / `MAS_WARN_ON` 会在断言失败时自动 `mt_dump()` 把整棵树打出来，并统计 `maple_tree_tests_run` / `maple_tree_tests_passed`；`mt_validate()` 会对 gap、parent slot、child slot、区间上下界、NULL 条目五类不变量做全树校验。
- tracepoint 定义在 `trace/events/maple_tree.h`，`ma_read` / `ma_write` / `ma_op` 三个点位可以观测到每次读写涉及的 index 与区间。
- 用户态测试在 `tools/testing/radix-tree/maple.c`（3.6 万行），覆盖各种插入/删除/分裂/再平衡序列。
- v7.x 还有 Rust 绑定 `rust/kernel/maple_tree.rs`；头文件里明确写了改动 `MA_STATE` 宏时必须同步该文件。

## Links

- [RCU](/docs/CS/OS/Linux/Lock/RCU.md)
- [页缓存](/docs/CS/OS/Linux/mm/PageCache.md)
- [内存管理链路总图](/docs/CS/OS/Linux/mm/README.md)

## References

1. [Introducing maple trees](https://lwn.net/Articles/845507/)
2. [Maple Tree — The Linux Kernel documentation](https://docs.kernel.org/core-api/maple_tree.html)
3. [The Maple Tree, A Modern Data Structure for a Complex Problem](https://blogs.oracle.com/linux/the-maple-tree)
