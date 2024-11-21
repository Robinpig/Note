## Introduction


在Linux上直接查看Page Cache的方式有很多，包括/proc/meminfo、free 、/proc/vmstat命令等，它们的内容其实是一致的
> [free](https://gitlab.com/procps-ng/procps/-/blob/master/src/free.c) 是读取了/proc/meminfo

这些内容都是page cache
```
Buffers + Cached + SwapCached = Active(file) + Inactive(file) + Shmem + SwapCached
```

在Page Cache中，Active(file)+Inactive(file)是File-backed page（与文件对应的内存页），是你最需要关注的部分。因为你平时用的mmap()内存映射方式和buffered I/O来消耗的内存就属于这部分，最重要的是，这部分在真实的生产环境上也最容易产生问题
SwapCached是在打开了Swap分区后，把Inactive(anon)+Active(anon)这两项里的匿名页给交换到磁盘（swap out），然后再读入到内存（swap in）后分配的内存。由于读入到内存后原来的Swap File还在，所以SwapCached也可以认为是File-backed page，即属于Page Cache。这样做的目的也是为了减少I/O
SwapCached只在Swap分区打开的情况下才会有，而我建议你在生产环境中关闭Swap分区，因为Swap过程产生的I/O会很容易引起性能抖动。

> Shmem是指匿名共享映射这种方式分配的内存（free命令中shared这一项），比如tmpfs（临时文件系统），这部分在真实的生产环境中产生的问题比较少

Page Cache的产生有两种不同的方式：
- Buffered I/O（标准I/O）标准I/O是写的(write(2))用户缓冲区(Userpace Page对应的内存)，然后再将用户缓冲区里的数据拷贝到内核缓冲区(Pagecache Page对应的内存)；如果是读的(read(2))话则是先从内核缓冲区拷贝到用户缓冲区，再从用户缓冲区读数据，也就是buffer和文件内容不存在任何映射关系
- Memory-Mapped I/O（存储映射I/O）。对于存储映射I/O而言，则是直接将Pagecache Page给映射到用户地址空间，用户直接读写Pagecache Page中内容

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



page cache 在内核中的数据结构是一个叫做 address_space 的结构体 每个文件都会有自己的 page cache。struct address_space 结构在内存中只会保留一份

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





## Links

- [Linux Memory](/docs/CS/OS/Linux/mm/memory.md)



## References

1. 