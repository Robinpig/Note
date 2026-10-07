## Introduction

llist（lock-less list）是内核里最轻量的容器：**只有一个指针的头 + 单指针的节点**，用 `cmpxchg` 做无锁插入。它解决的问题只有一个 —— **在不能加锁的上下文里挂链**。

典型场景是中断上半部：那里必须关掉所有中断，一旦获取自旋锁就可能死锁（中断里拿一个被中断路径持有的锁）。llist 用一条 CAS 指令绕开了这个问题。

> [!NOTE]
>
> **文件名的历史错位**：本文件叫 `struct.md`，属于 `struct/` 目录下，但内容只讲 **llist**。这是早期沿用的名字。`struct/` 目录的数据结构地图以 [README](/docs/CS/OS/Linux/struct/README.md) 为准。

## Data Structures

```c
struct llist_head {
	struct llist_node *first;
};

struct llist_node {
	struct llist_node *next;
};
```

**各只有一个指针** —— 这是 llist 与 [list](/docs/CS/OS/Linux/struct/list.md) 最本质的差别：普通 list 的节点有 `next` + `prev` 两个指针（双向循环），llist 只有 `next`（单向、NULL 结尾）。

代价与收益都很直接：**省一半指针内存、单次插入只有一次原子操作**，但**只能从头部取、不能 O(1) 取尾、删除指定元素很麻烦**。

初始化：

```c
#define LLIST_HEAD_INIT(name)	{ NULL }
#define LLIST_HEAD(name)	struct llist_head name = LLIST_HEAD_INIT(name)

static inline void init_llist_head(struct llist_head *list);
static inline void init_llist_node(struct llist_node *node);
```

从成员反推宿主（与 list 家族同构）：

```c
#define llist_entry(ptr, type, member)		\
	container_of(ptr, type, member)
```

## llist_add: Lock-free Insertion

```c
static inline bool __llist_add(struct llist_node *new, struct llist_head *head);
static inline bool llist_add(struct llist_node *new, struct llist_head *head);
```

插入是**头插**（LIFO）：

```c
	do {
		new->next = first;
	} while (!try_cmpxchg(&head->first, &first, new_first));
```

用 `try_cmpxchg` 而不是"读 → 改 → 写"三步，是因为多生产者并发时必须保证不丢元素。`llist_add` 返回值表示"是否成功成为第一个"（仅用于调试并发场景）。

### Batch Insertion

```c
static inline bool llist_add_batch(struct llist_node *new_first,
				   struct llist_node *new_last,
				   struct llist_head *head);
```

一次性挂一整条链（`new_first` 到 `new_last`），**只做一次 CAS**。适合"一批对象已经串好，一次性移交"的场景，比逐个 `llist_add` 少 N-1 次原子操作。

## llist_del_first: Single-consumer Deletion

```c
struct llist_node *llist_del_first(struct llist_head *head);
```

```c
	entry = smp_load_acquire(&head->first);
	do {
		if (entry == NULL)
			return NULL;
		next = READ_ONCE(entry->next);
	} while (!try_cmpxchg(&head->first, &entry, next));
```

**取出的是"最新加入的"那个**（因为是头插）—— 这一点与其他容器的 FIFO 直觉相反，容易写错。

### Why Only a Single Consumer

头文件把限制写得很明确：

```c
 * Only one llist_del_first user can be used simultaneously with
 * multiple llist_add users without lock.  Because otherwise
 * llist_del_first, llist_add, llist_add (or llist_del_all, llist_add,
 * llist_add) sequence in another user may change @head->first->next,
 * but keep @head->first.
```

`llist_del_first()` 做的是"**改 `head->first` 指向的节点的 `next`**"这个两段式操作。如果两个消费者同时做，第二个可能在第一个改完 `head->first` 但还没改完 `next` 时，把 `next` 也改掉 —— 于是某个元素被摘走两次、另一个被跳过。

**多消费者只能用 `llist_del_all()`**（整体摘下整条链，原子地换掉 `head->first`），或者自己在消费者之间加锁。

### Conditional Deletion

```c
bool llist_del_first_this(struct llist_head *head, struct llist_node *this);
```

只有当 `this` 恰好是链表头时才删除它（原子地）。注释说明它可与多个 `llist_add` 并发使用，**前提是每个调用者传的 `this` 各不相同**。

```c
	/* acquire ensures orderig wrt try_cmpxchg() is llist_del_first() */
	entry = smp_load_acquire(&head->first);
	do {
		if (entry != this)
			return false;
		next = READ_ONCE(entry->next);
	} while (!try_cmpxchg(&head->first, &entry, next));
```

`llist_del_first_this()` **没有 `NULL` 检查** —— 链空时 `entry` 为 NULL，与 `this` 不等，返回 false。所以调用者**总是能安全调用，不需要先判空**。

## llist_del_all: Multiple Consumers

```c
static inline struct llist_node *llist_del_all(struct llist_head *head);
```

一次性摘下整条链并返回**旧的头**（现在是新链的头）。多个消费者各拿一段互不干扰的链，安全。

头文件说明了 del_all 之后元素的可遍历性：

```c
 * The list entries deleted via llist_del_all can be traversed with
```

即摘下后就是一条普通单向链表，可以顺序遍历（但**遍历期间不可再并发添加**，需要自己保证）。

## Traversal

```c
static inline bool llist_empty(const llist_head *head);
static inline struct llist_node *llist_next(struct llist_node *node);
```

**llist 没有像 list 那样的一站式 `for_each_entry` 宏** —— 因为遍历期间链可能仍在被修改。需要安全遍历时，正确模式是"反复 `llist_del_all()`"或"反复 `llist_del_first()`"，而不是裸遍历。

头文件里有两个遍历相关的宏（`llist_entry` 的 pos 形式），但它们要求调用者自己保证遍历期间链表不被并发修改。

## Memory Ordering: Three Key Points

llist 的正确性完全依赖内存序，这是它最容易出错的地方：

| 位置 | 操作 | 作用 |
| :-- | :-- | :-- |
| `llist_add` | `try_cmpxchg` | 写入 `new->next` 后再发布 `new` 指针 |
| `llist_del_first` | `smp_load_acquire` | 读到 `first` 后，保证其 `next` 的写入对自己可见 |
| `llist_del_first` | `READ_ONCE(entry->next)` | 避免编译器把 `next` 读多次或优化到寄存器 |

`llist_del_first_this()` 的注释点明了 acquire 的作用：

```c
	/* acquire ensures orderig wrt try_cmpxchg() is llist_del_first() */
```

**用 `READ_ONCE` 而不是裸读**是因为 `next` 可能被并发写（另一个消费者在 CAS）。裸读可能被编译器重排或合并，导致读到不一致的值。

## NMI Constraints

`lib/llist.c` 的头注释给出了一条硬约束：

```c
 * The basic atomic operation of this list is cmpxchg on long.  On
 * architectures that don't have NMI-safe cmpxchg implementation, the
 * list can NOT be used in NMI handlers.  So code that uses the list in
 * an NMI handler should depend on CONFIG_ARCH_HAVE_NMI_SAFE_CMPXCHG.
```

**llist 依赖架构提供 NMI-safe 的 cmpxchg**。没有这个保证的架构上，llist 不能用于 NMI 处理器 —— 因为 NMI 可能在 CAS 指令执行到一半时打断，而 cmpxchg 不是可重入的。

这解释了 llist 的典型使用场景（中断上半部而非 NMI）：普通中断关中断后不会被同优先级打断，CAS 是原子的；NMI 则不同。

## Other Operations

```c
static inline bool llist_on_list(const struct llist_node *node);
struct llist_node *llist_reverse_order(struct llist_head *head);
```

`llist_reverse_order()` 把链反转（因为头插导致 LIFO，反转后变 FIFO）。`lib/llist.c` 只有 94 行 —— **整个 llist 的实现只有三个函数**（`llist_del_first` / `llist_del_first_this` / `llist_reverse_order`），加与遍历都在头文件 inline。

## When to Use llist

| 场景 | 建议 |
| :-- | :-- |
| 中断上半部挂 deferred work | ✅ llist 的本职 |
| 无锁栈（后进先出，天然匹配头插） | ✅ |
| 多生产者 + 单消费者 | ✅ |
| 多生产者 + 多消费者 | ⚠️ 只能用 `llist_del_all`，或加锁 |
| 需要 O(1) 取尾 | ❌ 用 [list](/docs/CS/OS/Linux/struct/list.md) |
| 需要按键查找 | ❌ 用 [hlist](/docs/CS/OS/Linux/struct/hlist.md) / [xarray](/docs/CS/OS/Linux/struct/xarray.md) |
| NMI 处理器 | ⚠️ 需 `CONFIG_ARCH_HAVE_NMI_SAFE_CMPXCHG` |

内核里的实际用法：`fs/` 的 `file` / `dentry` 缓存、终端层（`n_tty` 的 read 队列）、部分驱动的 pending 队列。共同点是"**中断里挂、进程上下文取**"。

## Troubleshooting Quick Reference

llist 本身没有 sysfs 接口。相关排查手段：

```shell
# 确认架构支持 NMI-safe cmpxchg
grep ARCH_HAVE_NMI_SAFE_CMPXCHG /boot/config-$(uname -r)

# 查某驱动是否用 llist（源码层面）
grep -rn "llist_add\|llist_del_first" --include='*.c' drivers/<你的驱动>/

# 调试并发问题：lockdep 与 KCSAN
echo 1 > /sys/kernel/debug/lockdep/depgraph
cat /sys/kernel/debug/lockdep/lockdep-stats
```

llist 的问题几乎都是**并发使用错误**（多消费者用了 `del_first`、`next` 被并发改），而不是功能缺失。定位手段是 KCSAN 报告的数据竞争。

## Links

- [struct/README（数据结构地图）](/docs/CS/OS/Linux/struct/README.md)
- [list](/docs/CS/OS/Linux/struct/list.md)
- [hlist](/docs/CS/OS/Linux/struct/hlist.md)
- [xarray](/docs/CS/OS/Linux/struct/xarray.md)
- [工作队列 workqueue](/docs/CS/OS/Linux/workqueue.md)
- [中断与 softirq](/docs/CS/OS/Linux/Interrupt.md)

## References

1. [Linux Kernel Documentation — Lock-less lists](https://docs.kernel.org/locking/locktypes.html)
2. [include/linux/llist.h](https://elixir.bootlin.com/linux/latest/source/include/linux/llist.h)
3. [lib/llist.c](https://elixir.bootlin.com/linux/latest/source/lib/llist.c)
