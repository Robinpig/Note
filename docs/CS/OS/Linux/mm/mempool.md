## Introduction

某些内核代码路径对内存分配有**"不能失败"**的硬约束：最典型的是块设备层提交 I/O（bio / request）和文件系统元数据操作。这些路径本身往往处在回收上下文里（GFP_NOIO / GFP_NOFS），**不能触发直接回收**，否则会自己和自己死锁；而一旦分配失败返回 NULL，就可能丢请求、损坏元数据。

普通 `kmalloc` / `kmem_cache_alloc` 在内存紧张时仍可能失败。mempool 的解法是维护一个**最小预留元素池（min_nr）**：只要池里还留着预留元素，分配就一定能成功，不依赖底层分配器此刻能否分配。所以它解决的不是"分配速度"，而是**前向进展（forward progress）保证**——在内存压力下也能把关键对象拿到手。

mempool 不是另一种分配器，而是**在底层分配器（通常是 slab 的 kmem_cache）之上加的一层预留担保**：平时走底层，底层失败才动预留池，归还时优先把预留池补满。

## mempool_t

内存池的核心描述符，字段直接决定"预留多少、现在剩多少、谁负责真正分配"：

```c
typedef struct mempool_s {
	spinlock_t lock;
	int min_nr;		/* nr of elements at *elements */
	int curr_nr;		/* Current nr of elements at *elements */
	void **elements;

	void *pool_data;
	mempool_alloc_t *alloc;
	mempool_free_t *free;
	wait_queue_head_t wait;
} mempool_t;
```

- `min_nr`：预留元素的**下限**。mempool 保证池中元素数不少于它，分配者在前向进展受阻时有保底可用。
- `curr_nr`：池中**当前**元素数（`elements` 数组里已填的有效指针个数），`0 ≤ curr_nr ≤ 容量`。
- `elements`：指向一个长度为 `min_nr` 的指针数组，存的是"已分配好、随时可借出"的预留元素。
- `alloc` / `free`：底层分配 / 释放回调。平时分配和"超量归还"都通过它们落到真正的分配器（如 slab）；`pool_data` 是传给回调的私有参数（比如对应的 `kmem_cache *`）。
- `wait`：等待队列。当底层分配失败、且预留池也空、调用者又允许睡眠时，挂在上面等别的路径 `mempool_free` 把元素还回来再唤醒。
- `lock`：保护 `curr_nr` / `elements` 的自旋锁，因为预留池的借用与归还可能跨上下文并发。

## Creation and Initialization

创建内存池时会**立即预填充** `min_nr` 个元素进 `elements` 数组——这是"预留"的来处；之后 `curr_nr == min_nr`。

```c
mempool_t *mempool_create(int min_nr, mempool_alloc_t *alloc_fn,
				mempool_free_t *free_fn, void *pool_data)
{
	return mempool_create_node(min_nr, alloc_fn, free_fn, pool_data,
				   GFP_KERNEL, NUMA_NO_NODE);
}
EXPORT_SYMBOL(mempool_create);

mempool_t *mempool_create_node(int min_nr, mempool_alloc_t *alloc_fn,
			       mempool_free_t *free_fn, void *pool_data,
			       gfp_t gfp_mask, int node_id)
{
	mempool_t *pool;

	pool = kzalloc_node(sizeof(*pool), gfp_mask, node_id);
	if (!pool)
		return NULL;

	if (mempool_init_node(pool, min_nr, alloc_fn, free_fn, pool_data,
			      gfp_mask, node_id)) {
		kfree(pool);
		return NULL;
	}

	return pool;
}
EXPORT_SYMBOL(mempool_create_node);
```

- `mempool_create` 等价于在 `NUMA_NO_NODE` 上调用 `mempool_create_node`，分配器自己按当前策略选 node。
- 还有 `mempool_init` / `mempool_init_node` 的无锁（不动态分配 `mempool_t` 本身）版本，供调用方已静态内嵌 `mempool_t` 的场景使用，逻辑与 `create` 一致，只是 `mempool_t` 内存由调用方提供。
- 创建成功的前提：**`min_nr` 个元素都能通过 `alloc_fn` 预先分配出来**。若预填充失败，池直接返回 NULL——也就是说 mempool 建立时是"尽量把保底铺满"的。

常用的标准后端回调（内核已提供，直接接 slab / kmalloc）：

- `mempool_alloc_slab` / `mempool_free_slab`：后端是 `kmem_cache`，`pool_data` 传 `struct kmem_cache *`。这是块设备层最常见的搭法。
- `mempool_kmalloc` / `mempool_kfree`：后端是 `kmalloc`，`pool_data` 传元素大小。
- 另有 `mempool_kzalloc` / `mempool_kvmalloc` 等变体，满足"零初始化"或"大对象可 vmalloc 回退"的需求。

## mempool_alloc

分配策略是 mempool 的灵魂，分三层降级：

1. **先走底层**：用 `gfp_temp = gfp_mask & ~(__GFP_DIRECT_RECLAIM | __GFP_IO)`（去掉直接回收与 IO，做一次非阻塞尝试）调用 `pool->alloc`。成功就直接返回——绝大多数情况下根本不会动预留池。
2. **再动预留池**：底层失败，自旋锁保护下若 `curr_nr > 0`，原子地从 `elements` 里取一个元素返回（`curr_nr--`）。这就是"前向进展担保"真正生效的地方：即使此刻系统内存枯竭，只要池里还有保底，分配照样成功。
3. **最后看能否等待**：
   - 若 `gfp_mask` 不允许直接回收（原子上下文，无 `__GFP_DIRECT_RECLAIM`），预留池也空 → 返回 NULL，调用者必须自己兜底。
   - 否则挂到 `pool->wait` 上睡眠，等别的路径 `mempool_free` 把元素还回池并 `wake_up`，再重试第 1/2 步。

```c
void *mempool_alloc(mempool_t *pool, gfp_t gfp_mask)
{
	void *element;
	unsigned long flags;

	might_sleep_if(gfp_mask & __GFP_DIRECT_RECLAIM);

	/* 第一步：非阻塞地先试底层分配器，能成就不碰预留池 */
	gfp_t gfp_temp = gfp_mask & ~(__GFP_DIRECT_RECLAIM | __GFP_IO);
	element = pool->alloc(gfp_temp, pool->pool_data);
	if (likely(element != NULL))
		return element;

	/* 第二步：底层失败，原子地从预留池借一个 */
	spin_lock_irqsave(&pool->lock, flags);
	if (likely(pool->curr_nr)) {
		element = pool->elements[--pool->curr_nr];
		spin_unlock_irqrestore(&pool->lock, flags);
		return element;   /* 担保生效：借走一个预留元素 */
	}
	spin_unlock_irqrestore(&pool->lock, flags);

	/* 第三步：预留池也空 */
	if (!(gfp_mask & __GFP_DIRECT_RECLAIM))
		return NULL;      /* 原子上下文，没法等，直接失败 */

	/* 可睡眠：挂到等待队列，等 mempool_free 归还并唤醒后再重试 */
	/* ... prepare_to_wait(&pool->wait, ...) ... */
}
```

注意 `might_sleep_if(gfp_mask & __GFP_DIRECT_RECLAIM)`：允许直接回收的分配**可能**在第三步被阻塞，调用方得知道自己可能睡。

## mempool_free

归还逻辑与分配对称，关键是"借走的预留元素要优先补回池"：

1. 若 `curr_nr < min_nr`：把元素放回 `elements` 数组（`curr_nr++`），`wake_up` 等待队列里的分配者，直接返回——不浪费底层释放。
2. 否则：池已满了，把元素**还给底层分配器** `pool->free(element, pool_data)`。

```c
void mempool_free(void *element, mempool_t *pool)
{
	unsigned long flags;

	if (unlikely(element == NULL))
		return;

	if (pool->curr_nr < pool->min_nr) {
		spin_lock_irqsave(&pool->lock, flags);
		if (pool->curr_nr < pool->min_nr) {
			pool->elements[pool->curr_nr++] = element;  /* 补回预留池 */
			spin_unlock_irqrestore(&pool->lock, flags);
			wake_up(&pool->wait);   /* 唤醒等待分配的吃瓜群众 */
			return;
		}
		spin_unlock_irqrestore(&pool->lock, flags);
	}

	pool->free(element, pool->pool_data);  /* 池满，还给底层分配器 */
}
```

正是这个"free 优先补池"的设计让预留池能**自愈**：即使某次 `mempool_alloc` 借走了保底元素，只要后来有一次 `mempool_free` 且池未满，元素就回到 `elements`，`curr_nr` 重新涨回 `min_nr`。

## mempool_resize

运行时调整 `min_nr`：增大就批量用 `alloc_fn` 补元素直到 `curr_nr` 达标；减小就回收多余的预留元素给底层分配器。持锁下分步操作，避免一次性大分配卡住。对"负载变化时想动态改保底水位"的场景有用，但日常少见。

## Typical Use Cases and Pitfalls

**该用 mempool 的地方**：必须在回收路径里、且不能失败的分配。
- 块设备层：blk-mq 的 request / tag 缓存、bio 相关对象（提交 I/O 时不能因为内存压力把请求丢掉）。
- SCSI 中层、某些文件系统（如 XFS 元数据对象、buffer head）、NFS 等。
- 共性：这些对象小、分配频繁、且分配点本身就在"不能触发回收"的上下文里。

**不该用 / 容易踩坑**：
- mempool **不是性能优化**，常驻的 `min_nr` 个元素是实打实的内存占用（对象一直占着，不被回收）。别拿它当"避免 NULL 判断"的万能胶。
- mempool **不保证绝对成功**：它只缓解"瞬时压力"。如果 `min_nr` 个元素**同时**被借出、且同一时刻又来分配、底层也失败，那它只能返回 NULL 或让调用者睡——所以上层代码仍要处理失败。
- 与 slab 的关系：mempool 通常站在 slab 之上（`mempool_alloc_slab` 后端），但 slab 在内存压力下本身不保证可分配；mempool 补的是"**下限担保**"，不是替代 slab。底层分配器该用 slab 还是用 slab。

## Links

- [物理内存地图（mm 枢纽）](/docs/CS/OS/Linux/mm/README.md)
- [物理内存主线](/docs/CS/OS/Linux/mm/pm.md)
- [Swap 交换](/docs/CS/OS/Linux/Swap.md)

## References

1. [Linux kernel mm/mempool.c (Bootlin Elixir)](https://elixir.bootlin.com/linux/latest/source/mm/mempool.c)
2. [Kernel documentation: Memory Allocation Guide](https://www.kernel.org/doc/html/latest/core-api/memory-allocation.html)
