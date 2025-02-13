## Introduction

The *page cache* is the main disk cache used by the Linux kernel. In most cases, the kernel refers to the page cache when reading from or writing to disk. New pages are added to the page cache to satisfy User Mode processes’s read requests. If the page is not already in the cache, a new entry is added to the cache and filled with the data read from the disk. If there is enough free memory, the page is kept in the cache for an indefinite period of time and can then be reused by other processes without accessing the disk.

Similarly, before writing a page of data to a block device, the kernel verifies whether the corresponding page is already included in the cache; if not, a new entry is added to the cache and filled with the data to be written on disk. The I/O data transfer does not start immediately: the disk update is delayed for a few seconds, thus giving a chance to the processes to further modify the data to be written (in other words, the kernel implements deferred write operations




在Linux上直接查看Page Cache的方式有很多，包括/proc/meminfo、free 、/proc/vmstat命令等，它们的内容其实是一致的
> [free](https://gitlab.com/procps-ng/procps/-/blob/master/src/free.c) 是读取了/proc/meminfo

这两边的内容都是page cache
```
Buffers + Cached + SwapCached = Active(file) + Inactive(file) + Shmem + SwapCached
```

在Page Cache中，Active(file)+Inactive(file)是File-backed page（与文件对应的内存页），是你最需要关注的部分。因为你平时用的mmap()内存映射方式和buffered I/O来消耗的内存就属于这部分，最重要的是，这部分在真实的生产环境上也最容易产生问题



两边都有SwapCached，它也是Page Cache的一部分 SwapCached是在打开了Swap分区后，把Inactive(anon)+Active(anon)这两项里的匿名页给交换到磁盘（swap out），然后再读入到内存（swap in）后分配的内存。由于读入到内存后原来的Swap File还在，所以SwapCached也可以认为是File-backed page，即属于Page Cache。这样做的目的也是为了减少I/O

SwapCached只在Swap分区打开的情况下才会有，而我建议你在生产环境中关闭Swap分区，因为Swap过程产生的I/O会很容易引起性能抖动。

> Shmem是指匿名共享映射这种方式分配的内存（free命令中shared这一项），比如tmpfs（临时文件系统），这部分在真实的生产环境中产生的问题比较少

Page Cache的产生有两种不同的方式：
- Buffered I/O（标准I/O）<br/>标准I/O是写的(write(2))用户缓冲区(Userpace Page对应的内存)，然后再将用户缓冲区里的数据拷贝到内核缓冲区(Pagecache Page对应的内存)；如果是读的(read(2))话则是先从内核缓冲区拷贝到用户缓冲区，再从用户缓冲区读数据，也就是buffer和文件内容不存在任何映射关系
- Memory-Mapped I/O（存储映射I/O）<br/>对于存储映射I/O而言，则是直接将Pagecache Page给映射到用户地址空间，用户直接读写Pagecache Page中内容

显然，存储映射I/O要比标准I/O效率高一些，毕竟少了“用户空间到内核空间互相拷贝”的过程

查看dirty page统计
```shell
cat /proc/vmstat | egrep "dirty|writeback"
```


当内存水位低于watermark low时，就会唤醒kswapd进行后台回收，然后kswapd会一直回收到watermark high。
那么，我们可以增大min_free_kbytes这个配置选项来及早地触发后台回收
vm.min_free_kbytes = 4194304
对于大于等于128G的系统而言，将min_free_kbytes设置为4G比较合理，这是我们在处理很多这种问题时总结出来的一个经验值，既不造成较多的内存浪费，又能避免掉绝大多数的直接内存回收。
该值的设置和总的物理内存并没有一个严格对应的关系，我们在前面也说过，如果配置不当会引起一些副作用，所以在调整该值之前，我的建议是：你可以渐进式地增大该值，比如先调整为1G，观察sar -B中pgscand是否还有不为0的情况；如果存在不为0的情况，继续增加到2G，再次观察是否还有不为0的情况来决定是否增大，以此类推。
这样做也有一些缺陷：提高了内存水位后，应用程序可以直接使用的内存量就会减少，这在一定程度上浪费了内存。所以在调整这一项之前，你需要先思考一下，应用程序更加关注什么，如果关注延迟那就适当地增大该值，如果关注内存的使用量那就适当地调小该值。

通过调整内存水位，在一定程度上保障了应用的内存申请，但是同时也带来了一定的内存浪费，因为系统始终要保障有这么多的free内存，这就压缩了Page Cache的空间。调整的效果你可以通过/proc/zoneinfo来观察：

```shell
egrep "min|low|high" /proc/zoneinfo
```



page cache 在内核中的数据结构是一个叫做 address_space 的结构体 每个文件都会有自己的 page cache

```c
struct file {
    ...
    struct address_space *f_mapping;
};
```



struct address_space 结构在内存中只会保留一份

i_pages 用于存储当前文件的 `页缓存` 这里使用的是 xarray 在 前使用的是radix tree

```c
struct address_space {
    struct inode        *host;
    struct xarray       i_pages;
    gfp_t           gfp_mask;
    atomic_t        i_mmap_writable;
#ifdef CONFIG_READ_ONLY_THP_FOR_FS
    /* number of thp, only for non-shmem files */
    atomic_t        nr_thps;
#endif
    struct rb_root_cached   i_mmap;
    struct rw_semaphore i_mmap_rwsem;
    unsigned long       nrpages;
    unsigned long       nrexceptional;
    pgoff_t         writeback_index;
    const struct address_space_operations *a_ops;
    unsigned long       flags;
    errseq_t        wb_err;
    spinlock_t      private_lock;
    struct list_head    private_list;
    void            *private_data;
} __attribute__((aligned(sizeof(long)))) __randomize_layout;
```



在 struct address_space 中通过 host 指针与文件的 inode 关联。而在 inode 结构体 struct inode 中又通过 i_mapping 指针与文件的 page cache 进行关联



```c
struct inode {
 struct address_space *i_mapping;
}
```

a_ops 定义了 page cache 中所有针对缓存页的 IO 操作，提供了管理 page cache 的各种行为

```c
struct address_space_operations {
    int (*writepage)(struct page *page, struct writeback_control *wbc);
    int (*readpage)(struct file *, struct page *);

    /* Write back some dirty pages from this mapping. */
    int (*writepages)(struct address_space *, struct writeback_control *);

    /* Set a page dirty.  Return true if this dirtied it */
    int (*set_page_dirty)(struct page *page);

    /*
     * Reads in the requested pages. Unlike ->readpage(), this is
     * PURELY used for read-ahead!.
     */
    int (*readpages)(struct file *filp, struct address_space *mapping,
            struct list_head *pages, unsigned nr_pages);
    void (*readahead)(struct readahead_control *);

    int (*write_begin)(struct file *, struct address_space *mapping,
                loff_t pos, unsigned len, unsigned flags,
                struct page **pagep, void **fsdata);
    int (*write_end)(struct file *, struct address_space *mapping,
                loff_t pos, unsigned len, unsigned copied,
                struct page *page, void *fsdata);

    /* Unfortunately this kludge is needed for FIBMAP. Don't use it */
    sector_t (*bmap)(struct address_space *, sector_t);
    void (*invalidatepage) (struct page *, unsigned int, unsigned int);
    int (*releasepage) (struct page *, gfp_t);
    void (*freepage)(struct page *);
    ssize_t (*direct_IO)(struct kiocb *, struct iov_iter *iter);
    /*
     * migrate the contents of a page to the specified target. If
     * migrate_mode is MIGRATE_ASYNC, it must not block.
     */
    int (*migratepage) (struct address_space *,
            struct page *, struct page *, enum migrate_mode);
    bool (*isolate_page)(struct page *, isolate_mode_t);
    void (*putback_page)(struct page *);
    int (*launder_page) (struct page *);
    int (*is_partially_uptodate) (struct page *, unsigned long,
                    unsigned long);
    void (*is_dirty_writeback) (struct page *, bool *, bool *);
    int (*error_remove_page)(struct address_space *, struct page *);

    /* swapfile support */
    int (*swap_activate)(struct swap_info_struct *sis, struct file *file,
                sector_t *span);
    void (*swap_deactivate)(struct file *file);
};
```



Xarray

The XArray is an abstract data type which behaves like a very large array of pointers. It takes advantage of RCU to perform lookups without locking.

```c
struct file {
    struct file_ra_state f_ra;
}
```

用于描述文件预读信息的结构体在内核中用 struct file_ra_state 结构体来表示

```c
/*
 * Track a single file's readahead state
 */
struct file_ra_state {
    pgoff_t start;          /* where readahead started */
    unsigned int size;      /* # of readahead pages */
    unsigned int async_size;    /* do asynchronous readahead when
                       there are only # of pages ahead */

    unsigned int ra_pages;      /* Maximum readahead window */
    unsigned int mmap_miss;     /* Cache miss stat for mmap accesses */
    loff_t prev_pos;        /* Cache last read() position */
};
```

内核可以根据 start 和 prev_pos 这两个字段来判断进程是否在顺序访问文件





那么内核在什么情况下才会去触发 page cache 中的脏页回写呢？

1. **内核在初始化的时候，会创建一个 timer 定时器去定时唤醒内核 flusher 线程回写脏页。**
2. **当内存中脏页的数量太多了达到了一定的比例，就会主动唤醒内核中的 flusher 线程去回写脏页。**
3. **脏页在内存中停留的时间太久了，等到 flusher 线程下一次被唤醒的时候就会回写这些驻留太久的脏页。**
4. **用户进程可以通过 sync() 回写内存中的所有脏页和 fsync() 回写指定文件的所有脏页，这些是进程主动发起脏页回写请求。**
5. **在内存比较紧张的情况下，需要回收物理页或者将物理页中的内容 swap 到磁盘上时，如果发现通过页面置换算法置换出来的页是脏页，那么就会触发回写。**


dirty_writeback_centisecs 内核参数的默认值为 500。单位为 0.01 s。也就是说内核会每隔 5s 唤醒一次 flusher 线程来执行相关脏页的回写。**该参数在内核源码中对应的变量名为 dirty_writeback_interval**

```c
static int __init default_bdi_init(void)
{
    int err;

    bdi_wq = alloc_workqueue("writeback", WQ_MEM_RECLAIM | WQ_UNBOUND |
                 WQ_SYSFS, 0);
    if (!bdi_wq)
        return -ENOMEM;

    err = bdi_init(&noop_backing_dev_info);

    return err;
}
subsys_initcall(default_bdi_init);
```





在系统启动的时候，内核会调用 default_bdi_init 来创建 bdi_wq 队列和初始化 backing_dev_info

```c
static int bdi_init(struct backing_dev_info *bdi)
{
    int ret;

    bdi->dev = NULL;

    kref_init(&bdi->refcnt);
    bdi->min_ratio = 0;
    bdi->max_ratio = 100;
    bdi->max_prop_frac = FPROP_FRAC_BASE;
    INIT_LIST_HEAD(&bdi->bdi_list);
    INIT_LIST_HEAD(&bdi->wb_list);
    init_waitqueue_head(&bdi->wb_waitq);

    ret = cgwb_bdi_init(bdi);

    return ret;
}
```





## fault





以`ext4`为例，`ext4_filemap_fault()`为缺页处理函数，具体调用了内存管理模块的`filemap_fault()`来完成:

```c
// fs/ext4/file.c
static const struct vm_operations_struct ext4_file_vm_ops = {
    .fault		= filemap_fault,
    .map_pages	= filemap_map_pages,
    .page_mkwrite   = ext4_page_mkwrite,
};
```



Page Cache 的插入主要流程如下:

- 判断查找的 Page 是否存在于 Page Cache，存在即直接返回
- 否则通过[Linux 内核物理内存分配](https://www.leviathan.vip/2019/06/01/Linux内核源码分析-Page-Cache原理分析/[http://leviathan.vip/2019/04/13/Linux内核源码分析-物理内存的分配/#核心算法](http://leviathan.vip/2019/04/13/Linux内核源码分析-物理内存的分配/#核心算法)介绍的伙伴系统分配一个空闲的 Page.
- 将 Page 插入 Page Cache，即插入`address_space`的`i_pages`.
- 调用`address_space`的`readpage()`来读取指定 offset 的 Page



```c
// mm/filemap.c
vm_fault_t filemap_fault(struct vm_fault *vmf)
{
    int error;
    struct file *file = vmf->vma->vm_file;
    struct file *fpin = NULL;
    struct address_space *mapping = file->f_mapping;
    struct inode *inode = mapping->host;
    pgoff_t max_idx, index = vmf->pgoff;
    struct folio *folio;
    vm_fault_t ret = 0;
    bool mapping_locked = false;

    max_idx = DIV_ROUND_UP(i_size_read(inode), PAGE_SIZE);
    if (unlikely(index >= max_idx))
        return VM_FAULT_SIGBUS;

    /*
  * Do we have something in the page cache already?
    */
    folio = filemap_get_folio(mapping, index);
    if (likely(!IS_ERR(folio))) {
        /*
      * We found the page, so try async readahead before waiting for
        * the lock.
        */
        if (!(vmf->flags & FAULT_FLAG_TRIED))
            fpin = do_async_mmap_readahead(vmf, folio);
        if (unlikely(!folio_test_uptodate(folio))) {
            filemap_invalidate_lock_shared(mapping);
            mapping_locked = true;
        }
    } else {
        ret = filemap_fault_recheck_pte_none(vmf);
        if (unlikely(ret))
            return ret;

        /* No page in the page cache at all */
        count_vm_event(PGMAJFAULT);
        count_memcg_event_mm(vmf->vma->vm_mm, PGMAJFAULT);
        ret = VM_FAULT_MAJOR;
        fpin = do_sync_mmap_readahead(vmf);
        retry_find:
        /*
              * See comment in filemap_create_folio() why we need
              * invalidate_lock
              */
        if (!mapping_locked) {
            filemap_invalidate_lock_shared(mapping);
            mapping_locked = true;
        }
        folio = __filemap_get_folio(mapping, index,
                                            FGP_CREAT|FGP_FOR_MMAP,
                                            vmf->gfp_mask);
        if (IS_ERR(folio)) {
            if (fpin)
                goto out_retry;
            filemap_invalidate_unlock_shared(mapping);
            return VM_FAULT_OOM;
        }
    }

    if (!lock_folio_maybe_drop_mmap(vmf, folio, &fpin))
        goto out_retry;

    /* Did it get truncated? */
    if (unlikely(folio->mapping != mapping)) {
        folio_unlock(folio);
        folio_put(folio);
        goto retry_find;
    }
    VM_BUG_ON_FOLIO(!folio_contains(folio, index), folio);

    /*
                        * We have a locked folio in the page cache, now we need to check
                        * that it's up-to-date. If not, it is going to be due to an error,
                        * or because readahead was otherwise unable to retrieve it.
                        */
    if (unlikely(!folio_test_uptodate(folio))) {
        /*
                          * If the invalidate lock is not held, the folio was in cache
                            * and uptodate and now it is not. Strange but possible since we
                            * didn't hold the page lock all the time. Let's drop
                            * everything, get the invalidate lock and try again.
                            */
                            if (!mapping_locked) {
                              folio_unlock(folio);
                              folio_put(folio);
                              goto retry_find;
                              }

                              /*
                              * OK, the folio is really not uptodate. This can be because the
                              * VMA has the VM_RAND_READ flag set, or because an error
                              * arose. Let's read it in directly.
                              */
                              goto page_not_uptodate;
                              }

                              /*
                              * We've made it this far and we had to drop our mmap_lock, now is the
                              * time to return to the upper layer and have it re-find the vma and
                              * redo the fault.
                              */
                              if (fpin) {
                                folio_unlock(folio);
                                goto out_retry;
                                }
                                if (mapping_locked)
                                  filemap_invalidate_unlock_shared(mapping);

                                  /*
                                  * Found the page and have a reference on it.
                                  * We must recheck i_size under page lock.
	 */
	max_idx = DIV_ROUND_UP(i_size_read(inode), PAGE_SIZE);
	if (unlikely(index >= max_idx)) {
		folio_unlock(folio);
		folio_put(folio);
		return VM_FAULT_SIGBUS;
	}

	vmf->page = folio_file_page(folio, index);
	return ret | VM_FAULT_LOCKED;

page_not_uptodate:
	/*
	 * Umm, take care of errors if the page isn't up-to-date.
	 * Try to re-read it _once_. We do this synchronously,
	 * because there really aren't any performance issues here
	 * and we need to check for errors.
	 */
	fpin = maybe_unlock_mmap_for_io(vmf, fpin);
	error = filemap_read_folio(file, mapping->a_ops->read_folio, folio);
	if (fpin)
		goto out_retry;
	folio_put(folio);

	if (!error || error == AOP_TRUNCATED_PAGE)
		goto retry_find;
	filemap_invalidate_unlock_shared(mapping);

	return VM_FAULT_SIGBUS;

out_retry:
	/*
	 * We dropped the mmap_lock, we need to return to the fault handler to
	 * re-find the vma and come back and find our hopefully still populated
	 * page.
	 */
	if (!IS_ERR(folio))
		folio_put(folio);
	if (mapping_locked)
		filemap_invalidate_unlock_shared(mapping);
	if (fpin)
		fput(fpin);
	return ret | VM_FAULT_RETRY;
}
EXPORT_SYMBOL(filemap_fault);
```



假如 Page Cache 中的 Page 经过了修改，它的 flags 会被置为`PG_dirty`. 在 Linux 内核中，假如没有打开`O_DIRECT`标志，写操作实际上会被延迟刷盘，以下几种策略可以将脏页刷盘:

- 手动调用`fsync()`或者`sync`强制落盘
- 脏页占用比率过高，超过了设定的阈值，导致内存空间不足，触发刷盘(**强制回写**).
- 脏页驻留时间过长，触发刷盘(**周期回写**).



`bdi`是`backing device info`的缩写，它描述备用存储设备相关信息，就是我们通常所说的存储介质 SSD 硬盘等等。Linux 内核为每一个存储设备构造了一个`backing_dev_info`，假如磁盘有几个分区，每个分区对应一个`backing_dev_info`结构体.





```c
struct backing_dev_info {
    u64 id;
    struct rb_node rb_node; /* keyed by ->id */
    struct list_head bdi_list;
    unsigned long ra_pages;	/* max readahead in PAGE_SIZE units */
    unsigned long io_pages;	/* max allowed IO size */

    struct kref refcnt;	/* Reference counter for the structure */
    unsigned int capabilities; /* Device capabilities */
    unsigned int min_ratio;
    unsigned int max_ratio, max_prop_frac;

    /*
	 * Sum of avg_write_bw of wbs with dirty inodes.  > 0 if there are
	 * any dirty wbs, which is depended upon by bdi_has_dirty().
	 */
    atomic_long_t tot_write_bandwidth;
    /*
	 * Jiffies when last process was dirty throttled on this bdi. Used by
	 * blk-wbt.
	 */
    unsigned long last_bdp_sleep;

    struct bdi_writeback wb;  /* the root writeback info for this bdi */
    struct list_head wb_list; /* list of all wbs */
    #ifdef CONFIG_CGROUP_WRITEBACK
    struct radix_tree_root cgwb_tree; /* radix tree of active cgroup wbs */
    struct mutex cgwb_release_mutex;  /* protect shutdown of wb structs */
    struct rw_semaphore wb_switch_rwsem; /* no cgwb switch while syncing */
    #endif
    wait_queue_head_t wb_waitq;

    struct device *dev;
    char dev_name[64];
    struct device *owner;

    struct timer_list laptop_mode_wb_timer;

    #ifdef CONFIG_DEBUG_FS
    struct dentry *debug_dir;
    #endif
};

```





```c
// include/linux/backing-dev-defs.h
struct bdi_writeback {
    struct backing_dev_info *bdi;	/* our parent bdi */

    unsigned long state;		/* Always use atomic bitops on this */
    unsigned long last_old_flush;	/* last old data flush */

    struct list_head b_dirty;	/* dirty inodes */
    struct list_head b_io;		/* parked for writeback */
    struct list_head b_more_io;	/* parked for more writeback */
    struct list_head b_dirty_time;	/* time stamps are dirty */
    spinlock_t list_lock;		/* protects the b_* lists */

    atomic_t writeback_inodes;	/* number of inodes under writeback */
    struct percpu_counter stat[NR_WB_STAT_ITEMS];

    unsigned long bw_time_stamp;	/* last time write bw is updated */
    unsigned long dirtied_stamp;
    unsigned long written_stamp;	/* pages written at bw_time_stamp */
    unsigned long write_bandwidth;	/* the estimated write bandwidth */
    unsigned long avg_write_bandwidth; /* further smoothed write bw, > 0 */

    /*
	 * The base dirty throttle rate, re-calculated on every 200ms.
	 * All the bdi tasks' dirty rate will be curbed under it.
	 * @dirty_ratelimit tracks the estimated @balanced_dirty_ratelimit
	 * in small steps and is much more smooth/stable than the latter.
	 */
    unsigned long dirty_ratelimit;
    unsigned long balanced_dirty_ratelimit;

    struct fprop_local_percpu completions;
    int dirty_exceeded;
    enum wb_reason start_all_reason;

    spinlock_t work_lock;		/* protects work_list & dwork scheduling */
    struct list_head work_list;
    struct delayed_work dwork;	/* work item used for writeback */
    struct delayed_work bw_dwork;	/* work item used for bandwidth estimate */

    struct list_head bdi_node;	/* anchored at bdi->wb_list */

    #ifdef CONFIG_CGROUP_WRITEBACK
    struct percpu_ref refcnt;	/* used only for !root wb's */
    struct fprop_local_percpu memcg_completions;
    struct cgroup_subsys_state *memcg_css; /* the associated memcg */
    struct cgroup_subsys_state *blkcg_css; /* and blkcg */
    struct list_head memcg_node;	/* anchored at memcg->cgwb_list */
    struct list_head blkcg_node;	/* anchored at blkcg->cgwb_list */
    struct list_head b_attached;	/* attached inodes, protected by list_lock */
    struct list_head offline_node;	/* anchored at offline_cgwbs */

    union {
        struct work_struct release_work;
        struct rcu_head rcu;
    };
    #endif
};
```



- `bdi`是该`bdi_writeback`所属的`backing_dev_info`.
- `b_dirty`代表文件系统中被修改的`inode`节点.
- `b_io`代表等待 I/O 的`inode`节点.
- `dwork`是一个封装的延迟工作任务，由它的主函数将脏页回写存储设备:



```c
static int wb_init(struct bdi_writeback *wb, struct backing_dev_info *bdi,
		   gfp_t gfp)
{
	int err;

	memset(wb, 0, sizeof(*wb));

	wb->bdi = bdi;
	wb->last_old_flush = jiffies;
	INIT_LIST_HEAD(&wb->b_dirty);
	INIT_LIST_HEAD(&wb->b_io);
	INIT_LIST_HEAD(&wb->b_more_io);
	INIT_LIST_HEAD(&wb->b_dirty_time);
	spin_lock_init(&wb->list_lock);

	atomic_set(&wb->writeback_inodes, 0);
	wb->bw_time_stamp = jiffies;
	wb->balanced_dirty_ratelimit = INIT_BW;
	wb->dirty_ratelimit = INIT_BW;
	wb->write_bandwidth = INIT_BW;
	wb->avg_write_bandwidth = INIT_BW;

	spin_lock_init(&wb->work_lock);
	INIT_LIST_HEAD(&wb->work_list);
	INIT_DELAYED_WORK(&wb->dwork, wb_workfn);
	INIT_DELAYED_WORK(&wb->bw_dwork, wb_update_bandwidth_workfn);

	err = fprop_local_init_percpu(&wb->completions, gfp);
	if (err)
		return err;

	err = percpu_counter_init_many(wb->stat, 0, gfp, NR_WB_STAT_ITEMS);
	if (err)
		fprop_local_destroy_percpu(&wb->completions);

	return err;
}
```

`bdi_writeback`对象封装了`dwork`以及需要处理的`inode`队列。当 Page Cache 调用`__mark_inode_dirty()`时，将需要刷脏的`inode`挂载到`bdi_writeback`对象的`b_dirty`队列上，然后唤醒对应的`bdi`刷脏线程。



Handle writeback of dirty data for the device backed by this bdi. Also reschedules periodically and does kupdated style flushing.



```c
void wb_workfn(struct work_struct *work)
{
	struct bdi_writeback *wb = container_of(to_delayed_work(work),
						struct bdi_writeback, dwork);
	long pages_written;

	set_worker_desc("flush-%s", bdi_dev_name(wb->bdi));

	if (likely(!current_is_workqueue_rescuer() ||
		   !test_bit(WB_registered, &wb->state))) {
		/*
		 * The normal path.  Keep writing back @wb until its
		 * work_list is empty.  Note that this path is also taken
		 * if @wb is shutting down even when we're running off the
		 * rescuer as work_list needs to be drained.
		 */
		do {
			pages_written = wb_do_writeback(wb);
			trace_writeback_pages_written(pages_written);
		} while (!list_empty(&wb->work_list));
	} else {
		/*
		 * bdi_wq can't get enough workers and we're running off
		 * the emergency worker.  Don't hog it.  Hopefully, 1024 is
		 * enough for efficient IO.
		 */
		pages_written = writeback_inodes_wb(wb, 1024,
						    WB_REASON_FORKER_THREAD);
		trace_writeback_pages_written(pages_written);
	}

	if (!list_empty(&wb->work_list))
		wb_wakeup(wb);
	else if (wb_has_dirty_io(wb) && dirty_writeback_interval)
		wb_wakeup_delayed(wb);
}
```

`wb_do_writeback`分别实现了周期回写和后台回写两部分: `wb_check_old_data_flush()`，`wb_check_background_flush()`，具体实现我们分不同的场景分析，因为每一个存储设备都有一个`backing_dev_info`，所以每个存储设备之间的脏页回写互不影响.



周期回写的时间单位是0.01s，默认为5s，可以通过`/proc/sys/vm/dirty_writeback_centisecs`调节:



`Page`驻留为`dirty`状态的时间单位也为0.01s，默认为30s，可以通过`/proc/sys/vm/dirty_expire_centisecs`来调节:



```c
static long wb_check_old_data_flush(struct bdi_writeback *wb)
{
	unsigned long expired;
	long nr_pages;

	/*
	 * When set to zero, disable periodic writeback
	 */
	if (!dirty_writeback_interval)
		return 0;

	expired = wb->last_old_flush +
			msecs_to_jiffies(dirty_writeback_interval * 10);
	if (time_before(jiffies, expired))
		return 0;

	wb->last_old_flush = jiffies;
	nr_pages = get_nr_dirty_pages();

	if (nr_pages) {
		struct wb_writeback_work work = {
			.nr_pages	= nr_pages,
			.sync_mode	= WB_SYNC_NONE,
			.for_kupdate	= 1,
			.range_cyclic	= 1,
			.reason		= WB_REASON_PERIODIC,
		};

		return wb_writeback(wb, &work);
	}

	return 0;
}
```



强制回写分为**后台线程回写**和**用户进程主动回写**。

当脏页数量超过了设定的阈值，后台回写线程会将脏页写回存储设备，后台回写阈值是脏页占可用内存大小的比例或者脏页的字节数，默认比例是10. 用户可以通过修改`/proc/sys/vm/dirty_background_ratio`修改脏页比或者修改`/proc/sys/vm/dirty_background_bytes`修改脏页的字节数。

而在用户调用`write()`接口写文件时，假如脏页占可用内存大小的比例或者脏页的字节数超过了设定的阈值，会进行主动回写，用户可以通过设置`/proc/sys/vm/dirty_ratio`或者`/proc/sys/vm/dirty_bytes`修改这两个阈值





```c
static long wb_check_background_flush(struct bdi_writeback *wb)
{
	if (wb_over_bg_thresh(wb)) {

		struct wb_writeback_work work = {
			.nr_pages	= LONG_MAX,
			.sync_mode	= WB_SYNC_NONE,
			.for_background	= 1,
			.range_cyclic	= 1,
			.reason		= WB_REASON_BACKGROUND,
		};

		return wb_writeback(wb, &work);
	}

	return 0;
}
```



假如用户调用`write()`或者其他写文件接口时，在写文件的过程中，产生了脏页后会调用`balance_dirty_pages`调节平衡脏页的状态. 假如脏页的数量超过了**(后台回写设定的阈值+ 进程主动回写设定的阈值) / 2 **，即`(background_thresh + dirty_thresh) / 2`会强制进行脏页回写. **用户线程进行的强制回写仍然是触发后台线程进行回写**







触发 Page Cache 刷脏的几个条件如下:

- 周期回写，可以通过设置`/proc/sys/vm/dirty_writeback_centisecs`调节周期.
- 当**后台回写阈值是脏页占可用内存大小的比例或者脏页的字节数**超过了设定的阈值会触发后台线程回写.
- 当用户进程写文件时会进行脏页检查假如超过了阈值会触发回写，从而调用后台线程完成回写.

`Page`的写回操作是文件系统的封装，即`address_space`的`writepage`操作.



Linux内核为每个存储设备都设置了刷脏进程，所以假如在日常开发过程遇到了刷脏压力过大的情况下，在条件允许的情况下，将写入文件分散在不同的存储设备，可以提高的写入速度，减小刷脏的压力















## write back



```c
void balance_dirty_pages_ratelimited(struct address_space *mapping)
{
	balance_dirty_pages_ratelimited_flags(mapping, 0);
}
EXPORT_SYMBOL(balance_dirty_pages_ratelimited);

int balance_dirty_pages_ratelimited_flags(struct address_space *mapping,
					unsigned int flags)
{
	struct inode *inode = mapping->host;
	struct backing_dev_info *bdi = inode_to_bdi(inode);
	struct bdi_writeback *wb = NULL;
	int ratelimit;
	int ret = 0;
	int *p;

	if (!(bdi->capabilities & BDI_CAP_WRITEBACK))
		return ret;

	if (inode_cgwb_enabled(inode))
		wb = wb_get_create_current(bdi, GFP_KERNEL);
	if (!wb)
		wb = &bdi->wb;

	ratelimit = current->nr_dirtied_pause;
	if (wb->dirty_exceeded)
		ratelimit = min(ratelimit, 32 >> (PAGE_SHIFT - 10));

	preempt_disable();
	/*
	 * This prevents one CPU to accumulate too many dirtied pages without
	 * calling into balance_dirty_pages(), which can happen when there are
	 * 1000+ tasks, all of them start dirtying pages at exactly the same
	 * time, hence all honoured too large initial task->nr_dirtied_pause.
	 */
	p =  this_cpu_ptr(&bdp_ratelimits);
	if (unlikely(current->nr_dirtied >= ratelimit))
		*p = 0;
	else if (unlikely(*p >= ratelimit_pages)) {
		*p = 0;
		ratelimit = 0;
	}
	/*
	 * Pick up the dirtied pages by the exited tasks. This avoids lots of
	 * short-lived tasks (eg. gcc invocations in a kernel build) escaping
	 * the dirty throttling and livelock other long-run dirtiers.
	 */
	p = this_cpu_ptr(&dirty_throttle_leaks);
	if (*p > 0 && current->nr_dirtied < ratelimit) {
		unsigned long nr_pages_dirtied;
		nr_pages_dirtied = min(*p, ratelimit - current->nr_dirtied);
		*p -= nr_pages_dirtied;
		current->nr_dirtied += nr_pages_dirtied;
	}
	preempt_enable();

	if (unlikely(current->nr_dirtied >= ratelimit))
		ret = balance_dirty_pages(wb, current->nr_dirtied, flags);

	wb_put(wb);
	return ret;
}
EXPORT_SYMBOL_GPL(balance_dirty_pages_ratelimited_flags);
```





balance_dirty_pages() must be called by processes which are generating dirty data. 

 It looks at the number of dirty pages in the machine and will force the caller to wait once crossing the (background_thresh + dirty_thresh) / 2.

If we're over `background_thresh' then the writeback threads are woken to perform some writeout.

```c
static int balance_dirty_pages(struct bdi_writeback *wb,
			       unsigned long pages_dirtied, unsigned int flags)
{
	struct dirty_throttle_control gdtc_stor = { GDTC_INIT(wb) };
	struct dirty_throttle_control mdtc_stor = { MDTC_INIT(wb, &gdtc_stor) };
	struct dirty_throttle_control * const gdtc = &gdtc_stor;
	struct dirty_throttle_control * const mdtc = mdtc_valid(&mdtc_stor) ?
						     &mdtc_stor : NULL;
	struct dirty_throttle_control *sdtc;
	unsigned long nr_reclaimable;	/* = file_dirty */
	long period;
	long pause;
	long max_pause;
	long min_pause;
	int nr_dirtied_pause;
	bool dirty_exceeded = false;
	unsigned long task_ratelimit;
	unsigned long dirty_ratelimit;
	struct backing_dev_info *bdi = wb->bdi;
	bool strictlimit = bdi->capabilities & BDI_CAP_STRICTLIMIT;
	unsigned long start_time = jiffies;
	int ret = 0;

	for (;;) {
		unsigned long now = jiffies;
		unsigned long dirty, thresh, bg_thresh;
		unsigned long m_dirty = 0;	/* stop bogus uninit warnings */
		unsigned long m_thresh = 0;
		unsigned long m_bg_thresh = 0;

		nr_reclaimable = global_node_page_state(NR_FILE_DIRTY);
		gdtc->avail = global_dirtyable_memory();
		gdtc->dirty = nr_reclaimable + global_node_page_state(NR_WRITEBACK);

		domain_dirty_limits(gdtc);

		if (unlikely(strictlimit)) {
			wb_dirty_limits(gdtc);

			dirty = gdtc->wb_dirty;
			thresh = gdtc->wb_thresh;
			bg_thresh = gdtc->wb_bg_thresh;
		} else {
			dirty = gdtc->dirty;
			thresh = gdtc->thresh;
			bg_thresh = gdtc->bg_thresh;
		}

		if (mdtc) {
			unsigned long filepages, headroom, writeback;

			/*
			 * If @wb belongs to !root memcg, repeat the same
			 * basic calculations for the memcg domain.
			 */
			mem_cgroup_wb_stats(wb, &filepages, &headroom,
					    &mdtc->dirty, &writeback);
			mdtc->dirty += writeback;
			mdtc_calc_avail(mdtc, filepages, headroom);

			domain_dirty_limits(mdtc);

			if (unlikely(strictlimit)) {
				wb_dirty_limits(mdtc);
				m_dirty = mdtc->wb_dirty;
				m_thresh = mdtc->wb_thresh;
				m_bg_thresh = mdtc->wb_bg_thresh;
			} else {
				m_dirty = mdtc->dirty;
				m_thresh = mdtc->thresh;
				m_bg_thresh = mdtc->bg_thresh;
			}
		}

		/*
		 * In laptop mode, we wait until hitting the higher threshold
		 * before starting background writeout, and then write out all
		 * the way down to the lower threshold.  So slow writers cause
		 * minimal disk activity.
		 *
		 * In normal mode, we start background writeout at the lower
		 * background_thresh, to keep the amount of dirty memory low.
		 */
		if (!laptop_mode && nr_reclaimable > gdtc->bg_thresh &&
		    !writeback_in_progress(wb))
			wb_start_background_writeback(wb);

		/*
		 * Throttle it only when the background writeback cannot
		 * catch-up. This avoids (excessively) small writeouts
		 * when the wb limits are ramping up in case of !strictlimit.
		 *
		 * In strictlimit case make decision based on the wb counters
		 * and limits. Small writeouts when the wb limits are ramping
		 * up are the price we consciously pay for strictlimit-ing.
		 *
		 * If memcg domain is in effect, @dirty should be under
		 * both global and memcg freerun ceilings.
		 */
		if (dirty <= dirty_freerun_ceiling(thresh, bg_thresh) &&
		    (!mdtc ||
		     m_dirty <= dirty_freerun_ceiling(m_thresh, m_bg_thresh))) {
			unsigned long intv;
			unsigned long m_intv;

free_running:
			intv = dirty_poll_interval(dirty, thresh);
			m_intv = ULONG_MAX;

			current->dirty_paused_when = now;
			current->nr_dirtied = 0;
			if (mdtc)
				m_intv = dirty_poll_interval(m_dirty, m_thresh);
			current->nr_dirtied_pause = min(intv, m_intv);
			break;
		}

		/* Start writeback even when in laptop mode */
		if (unlikely(!writeback_in_progress(wb)))
			wb_start_background_writeback(wb);

		mem_cgroup_flush_foreign(wb);

		/*
		 * Calculate global domain's pos_ratio and select the
		 * global dtc by default.
		 */
		if (!strictlimit) {
			wb_dirty_limits(gdtc);

			if ((current->flags & PF_LOCAL_THROTTLE) &&
			    gdtc->wb_dirty <
			    dirty_freerun_ceiling(gdtc->wb_thresh,
						  gdtc->wb_bg_thresh))
				/*
				 * LOCAL_THROTTLE tasks must not be throttled
				 * when below the per-wb freerun ceiling.
				 */
				goto free_running;
		}

		dirty_exceeded = (gdtc->wb_dirty > gdtc->wb_thresh) &&
			((gdtc->dirty > gdtc->thresh) || strictlimit);

		wb_position_ratio(gdtc);
		sdtc = gdtc;

		if (mdtc) {
			/*
			 * If memcg domain is in effect, calculate its
			 * pos_ratio.  @wb should satisfy constraints from
			 * both global and memcg domains.  Choose the one
			 * w/ lower pos_ratio.
			 */
			if (!strictlimit) {
				wb_dirty_limits(mdtc);

				if ((current->flags & PF_LOCAL_THROTTLE) &&
				    mdtc->wb_dirty <
				    dirty_freerun_ceiling(mdtc->wb_thresh,
							  mdtc->wb_bg_thresh))
					/*
					 * LOCAL_THROTTLE tasks must not be
					 * throttled when below the per-wb
					 * freerun ceiling.
					 */
					goto free_running;
			}
			dirty_exceeded |= (mdtc->wb_dirty > mdtc->wb_thresh) &&
				((mdtc->dirty > mdtc->thresh) || strictlimit);

			wb_position_ratio(mdtc);
			if (mdtc->pos_ratio < gdtc->pos_ratio)
				sdtc = mdtc;
		}

		if (dirty_exceeded != wb->dirty_exceeded)
			wb->dirty_exceeded = dirty_exceeded;

		if (time_is_before_jiffies(READ_ONCE(wb->bw_time_stamp) +
					   BANDWIDTH_INTERVAL))
			__wb_update_bandwidth(gdtc, mdtc, true);

		/* throttle according to the chosen dtc */
		dirty_ratelimit = READ_ONCE(wb->dirty_ratelimit);
		task_ratelimit = ((u64)dirty_ratelimit * sdtc->pos_ratio) >>
							RATELIMIT_CALC_SHIFT;
		max_pause = wb_max_pause(wb, sdtc->wb_dirty);
		min_pause = wb_min_pause(wb, max_pause,
					 task_ratelimit, dirty_ratelimit,
					 &nr_dirtied_pause);

		if (unlikely(task_ratelimit == 0)) {
			period = max_pause;
			pause = max_pause;
			goto pause;
		}
		period = HZ * pages_dirtied / task_ratelimit;
		pause = period;
		if (current->dirty_paused_when)
			pause -= now - current->dirty_paused_when;
		/*
		 * For less than 1s think time (ext3/4 may block the dirtier
		 * for up to 800ms from time to time on 1-HDD; so does xfs,
		 * however at much less frequency), try to compensate it in
		 * future periods by updating the virtual time; otherwise just
		 * do a reset, as it may be a light dirtier.
		 */
		if (pause < min_pause) {
			trace_balance_dirty_pages(wb,
						  sdtc->thresh,
						  sdtc->bg_thresh,
						  sdtc->dirty,
						  sdtc->wb_thresh,
						  sdtc->wb_dirty,
						  dirty_ratelimit,
						  task_ratelimit,
						  pages_dirtied,
						  period,
						  min(pause, 0L),
						  start_time);
			if (pause < -HZ) {
				current->dirty_paused_when = now;
				current->nr_dirtied = 0;
			} else if (period) {
				current->dirty_paused_when += period;
				current->nr_dirtied = 0;
			} else if (current->nr_dirtied_pause <= pages_dirtied)
				current->nr_dirtied_pause += pages_dirtied;
			break;
		}
		if (unlikely(pause > max_pause)) {
			/* for occasional dropped task_ratelimit */
			now += min(pause - max_pause, max_pause);
			pause = max_pause;
		}

pause:
		trace_balance_dirty_pages(wb,
					  sdtc->thresh,
					  sdtc->bg_thresh,
					  sdtc->dirty,
					  sdtc->wb_thresh,
					  sdtc->wb_dirty,
					  dirty_ratelimit,
					  task_ratelimit,
					  pages_dirtied,
					  period,
					  pause,
					  start_time);
		if (flags & BDP_ASYNC) {
			ret = -EAGAIN;
			break;
		}
		__set_current_state(TASK_KILLABLE);
		wb->dirty_sleep = now;
		io_schedule_timeout(pause);

		current->dirty_paused_when = now + pause;
		current->nr_dirtied = 0;
		current->nr_dirtied_pause = nr_dirtied_pause;

		/*
		 * This is typically equal to (dirty < thresh) and can also
		 * keep "1000+ dd on a slow USB stick" under control.
		 */
		if (task_ratelimit)
			break;

		/*
		 * In the case of an unresponsive NFS server and the NFS dirty
		 * pages exceeds dirty_thresh, give the other good wb's a pipe
		 * to go through, so that tasks on them still remain responsive.
		 *
		 * In theory 1 page is enough to keep the consumer-producer
		 * pipe going: the flusher cleans 1 page => the task dirties 1
		 * more page. However wb_dirty has accounting errors.  So use
		 * the larger and more IO friendly wb_stat_error.
		 */
		if (sdtc->wb_dirty <= wb_stat_error())
			break;

		if (fatal_signal_pending(current))
			break;
	}
	return ret;
}

```


domain_dirty_limits


```c

static void domain_dirty_limits(struct dirty_throttle_control *dtc)
{
	const unsigned long available_memory = dtc->avail;
	struct dirty_throttle_control *gdtc = mdtc_gdtc(dtc);
	unsigned long bytes = vm_dirty_bytes;
	unsigned long bg_bytes = dirty_background_bytes;
	/* convert ratios to per-PAGE_SIZE for higher precision */
	unsigned long ratio = (vm_dirty_ratio * PAGE_SIZE) / 100;
	unsigned long bg_ratio = (dirty_background_ratio * PAGE_SIZE) / 100;
	unsigned long thresh;
	unsigned long bg_thresh;
	struct task_struct *tsk;

	/* gdtc is !NULL iff @dtc is for memcg domain */
	if (gdtc) {
		unsigned long global_avail = gdtc->avail;

		/*
		 * The byte settings can't be applied directly to memcg
		 * domains.  Convert them to ratios by scaling against
		 * globally available memory.  As the ratios are in
		 * per-PAGE_SIZE, they can be obtained by dividing bytes by
		 * number of pages.
		 */
		if (bytes)
			ratio = min(DIV_ROUND_UP(bytes, global_avail),
				    PAGE_SIZE);
		if (bg_bytes)
			bg_ratio = min(DIV_ROUND_UP(bg_bytes, global_avail),
				       PAGE_SIZE);
		bytes = bg_bytes = 0;
	}

	if (bytes)
		thresh = DIV_ROUND_UP(bytes, PAGE_SIZE);
	else
		thresh = (ratio * available_memory) / PAGE_SIZE;

	if (bg_bytes)
		bg_thresh = DIV_ROUND_UP(bg_bytes, PAGE_SIZE);
	else
		bg_thresh = (bg_ratio * available_memory) / PAGE_SIZE;

	if (bg_thresh >= thresh)
		bg_thresh = thresh / 2;
	tsk = current;
	if (rt_task(tsk)) {
		bg_thresh += bg_thresh / 4 + global_wb_domain.dirty_limit / 32;
		thresh += thresh / 4 + global_wb_domain.dirty_limit / 32;
	}
	dtc->thresh = thresh;
	dtc->bg_thresh = bg_thresh;

	/* we should eventually report the domain in the TP */
	if (!gdtc)
		trace_global_dirty_state(bg_thresh, thresh);
}

```

node_dirtyable_memory

空闲内存加上page cache，再减去totalreserve


```c
static unsigned long node_dirtyable_memory(struct pglist_data *pgdat)
{
    unsigned long nr_pages = 0;
    int z;

    for (z = 0; z < MAX_NR_ZONES; z++) {
        struct zone *zone = pgdat->node_zones + z;

        if (!populated_zone(zone))
            continue;

        nr_pages += zone_page_state(zone, NR_FREE_PAGES);
    }

    /*
	 * Pages reserved for the kernel should not be considered
	 * dirtyable, to prevent a situation where reclaim has to
	 * clean pages in order to balance the zones.
	 */
    nr_pages -= min(nr_pages, pgdat->totalreserve_pages);

    nr_pages += node_page_state(pgdat, NR_INACTIVE_FILE);
    nr_pages += node_page_state(pgdat, NR_ACTIVE_FILE);

    return nr_pages;
}
```



## Links

- [Linux Memory](/docs/CS/OS/Linux/mm/memory.md)



## References

1. 