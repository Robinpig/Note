## Introduction

块设备（block device）是按**固定大小的"块"**寻址、可以随机读写、并且能挂载文件系统的设备——磁盘、SSD、NVMe、虚拟磁盘（loop、ramdisk）都是。它与字符设备的根本差别不在"能不能随机读"，而在于：字符设备的一次 read/write 由驱动**立即**处理，数据可能只有几个字节；块设备面对的是高速存储介质，内核必须把大量并发的小块 I/O **合并、排序、批量**后再交给硬件，否则磁盘性能会被寻道和中断开销彻底拖垮。

因此块设备驱动从不直接对接 read/write 系统调用，而是站在一条**分层 I/O 栈**的底端：文件系统 → PageCache → `bio` → 通用块层（block layer）→ `request` → I/O 调度器 → 多队列派发 → 驱动硬件队列。本页从驱动视角讲清这条链：用 `gendisk` 描述一个磁盘、用 `request_queue` 承载请求、用 blk-mq 把请求派到硬件，以及驱动如何把一个磁盘注册进设备模型。

## Three Core Objects

写块驱动前先分清三个极易混淆的结构。它们在 6.12 里的关系是：**`gendisk` 描述物理磁盘，`block_device` 描述一个可打开的块设备节点，`request_queue` 负责排队和下发 I/O**。

**gendisk——一个磁盘**。`struct gendisk`（`include/linux/blkdev.h`）是驱动注册磁盘的主体，关键字段：

```c
struct gendisk {
	int major;
	int first_minor;
	int minors;

	char disk_name[DISK_NAME_LEN];	/* name of major driver */

	struct xarray part_tbl;
	struct block_device *part0;

	const struct block_device_operations *fops;
	struct request_queue *queue;
	void *private_data;

	struct bio_set bio_split;

	int flags;
	unsigned long state;
    ...
	struct backing_dev_info	*bdi;
    ...
	u64 diskseq;
    ...
};
```

- `fops`：块设备操作集（打开、释放、ioctl，以及 bio-based 驱动的 `submit_bio`）；
- `queue`：该磁盘的请求队列，I/O 最终经它下发；
- `part_tbl` / `part0`：分区表与**整盘对应的 block_device**。

注意现代内核里 `major/minors` 不再需要驱动手填——块核心层自动分配，这也是注释里明确写的。

**block_device——一个可打开的设备节点**。用户态 `open("/dev/sda")` 或 `open("/dev/sda1")` 对应的是 `struct block_device`（`include/linux/blk_types.h`），整盘和每个分区各有一个：

```c
struct block_device {
	sector_t		bd_start_sect;
	sector_t		bd_nr_sectors;
	struct gendisk *	bd_disk;
	struct request_queue *	bd_queue;
    ...
	dev_t			bd_dev;
	struct address_space	*bd_mapping;	/* page cache */

	atomic_t		bd_openers;
    ...
};
```

`bd_disk` 指回所属 gendisk，`bd_start_sect` 给出该分区在整盘上的起始扇区，`bd_mapping` 是块设备自己的 address_space（直接访问裸设备时的 PageCache 落点）。`gendisk` 与 `block_device` 的对应宏是 `disk_to_dev` / `dev_to_disk`。

**request_queue——请求队列**。`struct request_queue`（`include/linux/blkdev.h`）持有块层排队、合并、派发所需的全部状态：

```c
struct request_queue {
	void			*queuedata;

	struct elevator_queue	*elevator;

	const struct blk_mq_ops	*mq_ops;

	/* sw queues */
	struct blk_mq_ctx __percpu	*queue_ctx;
    ...
	/* hw dispatch queues */
	unsigned int		nr_hw_queues;
	struct xarray		hctx_table;

	struct percpu_ref	q_usage_counter;

	struct request		*last_merge;

	spinlock_t		queue_lock;
    ...
	struct gendisk		*disk;
    ...
	struct queue_limits	limits;
    ...
	unsigned long		nr_requests;	/* Max # of requests */
    ...
};
```

`queuedata` 是驱动私有数据；`elevator` 指向 I/O 调度器；`nr_hw_queues` / `hctx_table` 是 blk-mq 的硬件队列；`limits` 描述扇区大小、最大扇区数、对齐、是否可丢弃等队列约束；`q_usage_counter` 是 percpu 引用计数，进入/退出 I/O 路径（`blk_queue_enter`/`blk_queue_exit`）靠它冻结队列。

三者关系一句话：**一个 gendisk 持有一个 request_queue，并对应一个整盘 block_device（part0）；整盘和每个分区的 block_device 都指回同一个 gendisk、共享同一个 request_queue**。

## Operations Set: block_device_operations

块驱动通过 `block_device_operations`（`include/linux/blkdev.h`）交出能力。它和字符设备的 `file_operations` 长得像，但内核在 6.12 里已经把传统的 `request_fn` 请求函数彻底移除，改为两种现代形态：

```c
struct block_device_operations {
	void (*submit_bio)(struct bio *bio);
	int (*poll_bio)(struct bio *bio, struct io_comp_batch *iob,
			unsigned int flags);
	int (*open)(struct gendisk *disk, blk_mode_t mode);
	void (*release)(struct gendisk *disk);
	int (*ioctl)(struct block_device *bdev, blk_mode_t mode,
			unsigned cmd, unsigned long arg);
    ...
	int (*getgeo)(struct block_device *, struct hd_geometry *);
    ...
	struct module *owner;
    ...
};
```

- `open` / `release`：设备首次被打开、最后一个引用关闭时回调；
- `ioctl`：块设备专属命令（分区扫描、刷缓存、几何信息等）；
- `submit_bio`：**bio-based 驱动**的入口——驱动直接收 bio，自己处理（典型如 ramdisk、loop、zram）。不实现它则默认走 **request-based** 的 blk-mq 路径。

块核心层在磁盘注册时探测这个回调，设置 `BD_HAS_SUBMIT_BIO` 标志（`block/genhd.c`）：

```c
	if (disk->fops->submit_bio)
		bdev_set_flag(disk->part0, BD_HAS_SUBMIT_BIO);
```

## Registering a Disk

现代块驱动的注册流程（6.12）大致四步：分配 tag_set 与磁盘 → 填 gendisk → 注册块设备号（可选）→ 添加磁盘。

第一步，**分配硬件队列与磁盘**。request-based 驱动先初始化一个 `blk_mq_tag_set`，再用 `blk_mq_alloc_disk` 一次性分配 request_queue + gendisk：

```c
struct gendisk *__blk_mq_alloc_disk(struct blk_mq_tag_set *set,
		struct queue_limits *lim, void *queuedata,
		struct lock_class_key *lkclass);

#define blk_mq_alloc_disk(set, lim, queuedata)				\
({									\
	static struct lock_class_key __key;				\
	__blk_mq_alloc_disk(set, lim, queuedata, &__key);		\
})
```

`blk_mq_tag_set` 描述驱动支持多少硬件队列、每队列深度、操作集等（`include/linux/blk-mq.h`）：

```c
struct blk_mq_tag_set {
	const struct blk_mq_ops	*ops;
	struct blk_mq_queue_map	map[HCTX_MAX_TYPES];
	unsigned int		nr_maps;
	unsigned int		nr_hw_queues;
	unsigned int		queue_depth;
	unsigned int		reserved_tags;
	unsigned int		cmd_size;
	int			numa_node;
	unsigned int		timeout;
	unsigned int		flags;
	void			*drivers_data;
    ...
};
```

第二步，**填写 gendisk**：`set_capacity(disk, nsectors)` 设置容量（单位是 512 字节扇区）、设置 `disk->fops`、`major`/`minors` 留空让核心分配。

第三步，**注册设备号**（动态主设备号时通常省略，核心自动处理）；旧式静态主设备号用 `__register_blkdev`：

```c
int __register_blkdev(unsigned int major, const char *name,
		void (*probe)(dev_t devt));
```

第四步，**添加磁盘**，把它挂进设备模型、建立 sysfs、触发分区扫描与 uevent：

```c
int __must_check device_add_disk(struct device *parent, struct gendisk *disk,
				 const struct attribute_group **groups);

static inline int add_disk(struct gendisk *disk)
{
	return device_add_disk(NULL, disk, NULL);
}
```

注销走反向流程：`del_gendisk()` 摘除并触发分区清理，再 `put_disk()` 释放 gendisk（内部连带清理 request_queue），最后 `blk_mq_free_tag_set()` 释放 tag_set。注意 6.12 里旧的 `blk_cleanup_disk()` 已不存在，统一由 `put_disk()` 处理。

## I/O Stack: How a bio Becomes a Hardware Command

磁盘注册好后，一次写请求是怎么落到硬件的？自顶向下：

1. 应用 `write()` 进入文件系统，数据先写进 **PageCache**，标记脏页；
2. 回写（writeback）时文件系统针对设备构造一个或多个 **`bio`**，bio 描述"对 `block_device` 上从某扇区开始的一段，执行读/写"，承载一组 `bio_vec`（页 + 偏移 + 长度）。bio 结构见 [IO 的 bio 章](/docs/CS/OS/Linux/IO/IO.md)；
3. bio 经 `submit_bio` → `submit_bio_noacct` 进入通用块层，块层做 cgroup 记账、合并、拆分到队列限制；
4. 在 `__submit_bio`（`block/blk-core.c`）处分流：

```c
	if (!bdev_test_flag(bio->bi_bdev, BD_HAS_SUBMIT_BIO)) {
		blk_mq_submit_bio(bio);
	} else if (likely(bio_queue_enter(bio) == 0)) {
		struct gendisk *disk = bio->bi_bdev->bd_disk;

		disk->fops->submit_bio(bio);
		blk_queue_exit(disk->queue);
	}
```

**bio-based** 驱动直接收到 bio；**request-based** 驱动则由 `blk_mq_submit_bio` 把 bio 转化/合并进一个 `request`，再经 blk-mq 派发。

## blk-mq: Multi-Queue Dispatch

传统块层只有一把队列锁，多核高 IOPS 的 SSD/NVMe 下锁竞争严重。**blk-mq（block multi-queue）**把队列分两层，是现代 request-based 驱动的核心：

- **软件队列（`blk_mq_ctx`，per-CPU）**：每个 CPU 一个，bio 先在本 CPU 的软件队列里缓存、合并，无锁；
- **硬件队列（`blk_mq_hw_ctx`）**：对应硬件的提交队列，NVMe 可有几十个，每个带自己的派发链表；
- **tag**：每个在途 request 占一个 tag，硬件队列深度（`queue_depth`）限制在途命令数。

`blk_mq_hw_ctx`（`include/linux/blk-mq.h`）持有派发链表与硬件队列运行状态：

```c
struct blk_mq_hw_ctx {
	struct {
		spinlock_t		lock;
		struct list_head	dispatch;
		unsigned long		state;
	} ____cacheline_aligned_in_smp;

	struct delayed_work	run_work;
	cpumask_var_t		cpumask;
    ...
};
```

驱动通过 `blk_mq_ops` 提供最关键的硬件下发回调 `queue_rq`（`include/linux/blk-mq.h`）：

```c
struct blk_mq_ops {
	blk_status_t (*queue_rq)(struct blk_mq_hw_ctx *,
				 const struct blk_mq_queue_data *);
    ...
	enum blk_eh_timer_return (*timeout)(struct request *);
	int (*poll)(struct blk_mq_hw_ctx *, struct io_comp_batch *);
    ...
};
```

`blk_mq_submit_bio`（`block/blk-mq.c`）构造 request 后，优先尝试**直接派发**（`blk_mq_try_issue_directly` → `queue_rq`），不经过 I/O 调度器以降延迟；直接派发失败或需要排队时，request 进入软件队列，由 I/O 调度器（`elevator`，如 mq-deadline、none、BFQ）按规则排序后批量 `queue_rq`。函数头注释明确列出了不立即下发的三种情形：

```c
 * The request may not be queued directly to hardware if:
 * * This request can be merged with another one
 * * We want to place request at plug queue for possible future merging
 * * There is an IO scheduler active at this queue
```

`queue_rq` 里驱动把 request 翻译成硬件命令（填 SQE、挂 DMA 描述符、敲门铃），命令完成后由中断触发 `blk_mq_complete_request` 结束 request、再逐层 `bio_endio` 唤醒等待者。

## bio-based vs request-based

| 维度 | bio-based | request-based（blk-mq） |
| --- | --- | --- |
| 驱动入口 | `fops->submit_bio(bio)` | `blk_mq_ops->queue_rq(hctx, bd)` |
| 中间对象 | 直接处理 bio | bio → request，经 I/O 调度器 |
| 是否要 tag_set | 否（可用 `blk_alloc_disk`） | 是，需 `blk_mq_tag_set` |
| 典型设备 | ramdisk、loop、zram、部分虚拟设备 | NVMe、SCSI/SATA、virtio-blk、MMC |
| 适用场景 | I/O 由软件即时满足、无需硬件队列 | 真实高速硬件，需要合并、排序、多队列 |

简单判据：**数据最终要发给真实硬件、受命令队列约束，用 blk-mq；I/O 在内存里就被消化、驱动自己消费 bio，用 submit_bio**。

## Boundary with the File System and Page Cache

块驱动是块 I/O 的终点，但它不关心文件——文件系统负责把"文件 + 偏移"翻译成"扇区区间"并构造 bio，块层和驱动只看到扇区。这条边界有几个直接推论：

- **缓冲写**先落 [PageCache](/docs/CS/OS/Linux/mm/PageCache.md)，由回写线程异步下发 bio；内存紧张时 [Reclaim](/docs/CS/OS/Linux/mm/Reclaim.md) 会先回写脏页才能回收；
- **直接 I/O / O_DIRECT** 绕过 PageCache，bio 直接引用用户页，要求对齐到 `queue_limits`；
- 裸设备 `/dev/sdX` 也有自己的 `bd_mapping`，对块设备的缓冲读写仍可经 PageCache；
- 请求合并依赖 bio 的扇区相邻性，因此块层只在"块"这一层做文章，不感知上层文件结构。

## Links

- [Linux 内核总览](/docs/CS/OS/Linux/Linux.md)
- [设备驱动链路](/docs/CS/OS/Linux/dev/README.md)
- [设备模型 device](/docs/CS/OS/Linux/dev/device.md)
- [udev](/docs/CS/OS/Linux/dev/udev.md)
- [内核协同链路](/docs/CS/OS/Linux/Architecture.md)

## References

1. [Block Layer — kernel.org documentation](https://www.kernel.org/doc/html/latest/core-api/kernel-api.html#block-layer)
2. [Linux Block IO: Introducing Multi-queue SSD Access on Multi-core Systems](https://www.kernel.org/doc/ols/2010/ols2010-pages-163-174.pdf)
3. [blk-mq — kernel.org docs](https://www.kernel.org/doc/html/latest/block/blk-mq.html)
