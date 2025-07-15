## Introduction

XArray 是 Linux 内核从 4.20 版本 开始引入的一种新型数据结构，旨在替代传统的 radix tree 和 idr（ID Allocator）
其数据结构是哈希函数固定的多级哈希表 最适用的场景是整数域（例如文件描述符、内存映射、inode 等）
它继承了多级哈希的节约空间 快速索引 局部锁的高性能特性

当 xarray 中存在数据时 head 必定不为 NULL

```c
struct xarray {
	spinlock_t	xa_lock;
/* private: The rest of the data structure is not to be used directly. */
	gfp_t		xa_flags;
	void __rcu *	xa_head;
};
```

若存在其它不为 NULL 的节点 则 xa_head 指向 下一个 xa_node

一个 xa_node 就是 xarray 中一个节点 每个节点中包含以下字段

```c
struct xa_node {
	unsigned char	shift;		/* Bits remaining in each slot */
	unsigned char	offset;		/* Slot offset in parent */
	unsigned char	count;		/* Total entry count */
	unsigned char	nr_values;	/* Value entry count */
	struct xa_node __rcu *parent;	/* NULL at top of tree */
	struct xarray	*array;		/* The array we belong to */
	union {
		struct list_head private_list;	/* For tree user */
		struct rcu_head	rcu_head;	/* Used when freeing node */
	};
	void __rcu	*slots[XA_CHUNK_SIZE];
	union {
		unsigned long	tags[XA_MAX_MARKS][XA_MARK_LONGS];
		unsigned long	marks[XA_MAX_MARKS][XA_MARK_LONGS];
	};
};

```

## Summary




## Links

- [Linux struct](/docs/CS/OS/Linux/struct/struct.md)
