## Introduction



SQ and CQ both of them are one-Producer-one-Consumer queue which shared in user space and kernel space.

app consume CQ don't need change to kernel space



Three modes:

1. Interrupt driven
2. polled
3. kernel polled


### io_ring_ctx
```c

struct io_ring_ctx {
	/* const or read-mostly hot data */
	struct {
		struct percpu_ref	refs;

		struct io_rings		*rings;
		unsigned int		flags;
		unsigned int		compat: 1;
		unsigned int		drain_next: 1;
		unsigned int		eventfd_async: 1;
		unsigned int		restricted: 1;
		unsigned int		off_timeout_used: 1;
		unsigned int		drain_active: 1;
	} ____cacheline_aligned_in_smp;

	/* submission data */
	struct {
		struct mutex		uring_lock;

		/*
		 * Ring buffer of indices into array of io_uring_sqe, which is
		 * mmapped by the application using the IORING_OFF_SQES offset.
		 *
		 * This indirection could e.g. be used to assign fixed
		 * io_uring_sqe entries to operations and only submit them to
		 * the queue when needed.
		 *
		 * The kernel modifies neither the indices array nor the entries
		 * array.
		 */
		u32			*sq_array;
		struct io_uring_sqe	*sq_sqes;
		unsigned		cached_sq_head;
		unsigned		sq_entries;
		struct list_head	defer_list;

		/*
		 * Fixed resources fast path, should be accessed only under
		 * uring_lock, and updated through io_uring_register(2)
		 */
		struct io_rsrc_node	*rsrc_node;
		struct io_file_table	file_table;
		unsigned		nr_user_files;
		unsigned		nr_user_bufs;
		struct io_mapped_ubuf	**user_bufs;

		struct io_submit_state	submit_state;
		struct list_head	timeout_list;
		struct list_head	ltimeout_list;
		struct list_head	cq_overflow_list;
		struct xarray		io_buffers;
		struct xarray		personalities;
		u32			pers_next;
		unsigned		sq_thread_idle;
	} ____cacheline_aligned_in_smp;

	/* IRQ completion list, under ->completion_lock */
	struct list_head	locked_free_list;
	unsigned int		locked_free_nr;

	const struct cred	*sq_creds;	/* cred used for __io_sq_thread() */
	struct io_sq_data	*sq_data;	/* if using sq thread polling */

	struct wait_queue_head	sqo_sq_wait;
	struct list_head	sqd_list;

	unsigned long		check_cq_overflow;

	struct {
		unsigned		cached_cq_tail;
		unsigned		cq_entries;
		struct eventfd_ctx	*cq_ev_fd;
		struct wait_queue_head	poll_wait;
		struct wait_queue_head	cq_wait;
		unsigned		cq_extra;
		atomic_t		cq_timeouts;
		unsigned		cq_last_tm_flush;
	} ____cacheline_aligned_in_smp;

	struct {
		spinlock_t		completion_lock;

		spinlock_t		timeout_lock;

		/*
		 * ->iopoll_list is protected by the ctx->uring_lock for
		 * io_uring instances that don't use IORING_SETUP_SQPOLL.
		 * For SQPOLL, only the single threaded io_sq_thread() will
		 * manipulate the list, hence no extra locking is needed there.
		 */
		struct list_head	iopoll_list;
		struct hlist_head	*cancel_hash;
		unsigned		cancel_hash_bits;
		bool			poll_multi_queue;
	} ____cacheline_aligned_in_smp;
```

### io_uring_init

```c
__initcall(io_uring_init);
```





```c
static int __init io_uring_init(void)
{
#define __BUILD_BUG_VERIFY_ELEMENT(stype, eoffset, etype, ename) do { \
       BUILD_BUG_ON(offsetof(stype, ename) != eoffset); \
       BUILD_BUG_ON(sizeof(etype) != sizeof_field(stype, ename)); \
} while (0)

#define BUILD_BUG_SQE_ELEM(eoffset, etype, ename) \
       __BUILD_BUG_VERIFY_ELEMENT(struct io_uring_sqe, eoffset, etype, ename)
       BUILD_BUG_ON(sizeof(struct io_uring_sqe) != 64);
       BUILD_BUG_SQE_ELEM(0,  __u8,   opcode);
       BUILD_BUG_SQE_ELEM(1,  __u8,   flags);
       BUILD_BUG_SQE_ELEM(2,  __u16,  ioprio);
       BUILD_BUG_SQE_ELEM(4,  __s32,  fd);
       BUILD_BUG_SQE_ELEM(8,  __u64,  off);
       BUILD_BUG_SQE_ELEM(8,  __u64,  addr2);
       BUILD_BUG_SQE_ELEM(16, __u64,  addr);
       BUILD_BUG_SQE_ELEM(16, __u64,  splice_off_in);
       BUILD_BUG_SQE_ELEM(24, __u32,  len);
       BUILD_BUG_SQE_ELEM(28,     __kernel_rwf_t, rw_flags);
       BUILD_BUG_SQE_ELEM(28, /* compat */   int, rw_flags);
       BUILD_BUG_SQE_ELEM(28, /* compat */ __u32, rw_flags);
       BUILD_BUG_SQE_ELEM(28, __u32,  fsync_flags);
       BUILD_BUG_SQE_ELEM(28, /* compat */ __u16,  poll_events);
       BUILD_BUG_SQE_ELEM(28, __u32,  poll32_events);
       BUILD_BUG_SQE_ELEM(28, __u32,  sync_range_flags);
       BUILD_BUG_SQE_ELEM(28, __u32,  msg_flags);
       BUILD_BUG_SQE_ELEM(28, __u32,  timeout_flags);
       BUILD_BUG_SQE_ELEM(28, __u32,  accept_flags);
       BUILD_BUG_SQE_ELEM(28, __u32,  cancel_flags);
       BUILD_BUG_SQE_ELEM(28, __u32,  open_flags);
       BUILD_BUG_SQE_ELEM(28, __u32,  statx_flags);
       BUILD_BUG_SQE_ELEM(28, __u32,  fadvise_advice);
       BUILD_BUG_SQE_ELEM(28, __u32,  splice_flags);
       BUILD_BUG_SQE_ELEM(32, __u64,  user_data);
       BUILD_BUG_SQE_ELEM(40, __u16,  buf_index);
       BUILD_BUG_SQE_ELEM(40, __u16,  buf_group);
       BUILD_BUG_SQE_ELEM(42, __u16,  personality);
       BUILD_BUG_SQE_ELEM(44, __s32,  splice_fd_in);
       BUILD_BUG_SQE_ELEM(44, __u32,  file_index);

       BUILD_BUG_ON(sizeof(struct io_uring_files_update) !=
                   sizeof(struct io_uring_rsrc_update));
       BUILD_BUG_ON(sizeof(struct io_uring_rsrc_update) >
                   sizeof(struct io_uring_rsrc_update2));

       /* ->buf_index is u16 */
       BUILD_BUG_ON(IORING_MAX_REG_BUFFERS >= (1u << 16));

       /* should fit into one byte */
       BUILD_BUG_ON(SQE_VALID_FLAGS >= (1 << 8));

       BUILD_BUG_ON(ARRAY_SIZE(io_op_defs) != IORING_OP_LAST);
       BUILD_BUG_ON(__REQ_F_LAST_BIT > 8 * sizeof(int));

       req_cachep = KMEM_CACHE(io_kiocb, SLAB_HWCACHE_ALIGN | SLAB_PANIC |
                            SLAB_ACCOUNT);
       return 0;
};
```



### io_uring_setup

#### io_uring_params
Passed in for io_uring_setup(2). Copied back with updated info on success

```c
struct io_uring_params {
	__u32 sq_entries;
	__u32 cq_entries;
	__u32 flags;
	__u32 sq_thread_cpu;
	__u32 sq_thread_idle;
	__u32 features;
	__u32 wq_fd;
	__u32 resv[3];
	struct io_sqring_offsets sq_off;
	struct io_cqring_offsets cq_off;
};
```

Sets up an aio uring context, and returns the fd. Applications asks for a ring size, we return the actual sq/cq ring sizes (among other things) in the params structure passed in.

```cpp
// fs/io_uring.c

SYSCALL_DEFINE2(io_uring_setup, u32, entries,
		struct io_uring_params __user *, params)
{
	return io_uring_setup(entries, params);
}

static long io_uring_setup(u32 entries, struct io_uring_params __user *params)
{
	struct io_uring_params p;
	int i;

	if (copy_from_user(&p, params, sizeof(p)))
		return -EFAULT;
	for (i = 0; i < ARRAY_SIZE(p.resv); i++) {
		if (p.resv[i])
			return -EINVAL;
	}

```

```c
	if (p.flags & ~(IORING_SETUP_IOPOLL | IORING_SETUP_SQPOLL |
			IORING_SETUP_SQ_AFF | IORING_SETUP_CQSIZE |
			IORING_SETUP_CLAMP | IORING_SETUP_ATTACH_WQ |
			IORING_SETUP_R_DISABLED))
		return -EINVAL;

	return  io_uring_create(entries, &p, params);
}

```



#### io_uring_create

```c
static int io_uring_create(unsigned entries, struct io_uring_params *p,
                        struct io_uring_params __user *params)
{
       struct io_ring_ctx *ctx;
       struct file *file;
       int ret;

       if (!entries)
              return -EINVAL;
       if (entries > IORING_MAX_ENTRIES) {
              if (!(p->flags & IORING_SETUP_CLAMP))
                     return -EINVAL;
              entries = IORING_MAX_ENTRIES;
       }
```
Use twice as many entries for the CQ ring. It's possible for the
application to drive a higher depth than the size of the SQ ring,
since the sqes are only used at submission time. This allows for
some flexibility in overcommitting a bit. If the application has
set IORING_SETUP_CQSIZE, it will have passed in the desired number
of CQ ring entries manually.
```c
       p->sq_entries = roundup_pow_of_two(entries);
       if (p->flags & IORING_SETUP_CQSIZE) {
              /*
               * If IORING_SETUP_CQSIZE is set, we do the same roundup
               * to a power-of-two, if it isn't already. We do NOT impose
               * any cq vs sq ring sizing.
               */
              if (!p->cq_entries)
                     return -EINVAL;
              if (p->cq_entries > IORING_MAX_CQ_ENTRIES) {
                     if (!(p->flags & IORING_SETUP_CLAMP))
                            return -EINVAL;
                     p->cq_entries = IORING_MAX_CQ_ENTRIES;
              }
              p->cq_entries = roundup_pow_of_two(p->cq_entries);
              if (p->cq_entries < p->sq_entries)
                     return -EINVAL;
       } else {
              p->cq_entries = 2 * p->sq_entries;
       }

       ctx = io_ring_ctx_alloc(p);
       if (!ctx)
              return -ENOMEM;
       ctx->compat = in_compat_syscall();
       if (!capable(CAP_IPC_LOCK))
              ctx->user = get_uid(current_user());

       /*
        * This is just grabbed for accounting purposes. When a process exits,
        * the mm is exited and dropped before the files, hence we need to hang
        * on to this mm purely for the purposes of being able to unaccount
        * memory (locked/pinned vm). It's not used for anything else.
        */
       mmgrab(current->mm);
       ctx->mm_account = current->mm;

       ret = io_allocate_scq_urings(ctx, p);
       if (ret)
              goto err;

       ret = io_sq_offload_create(ctx, p);
       if (ret)
              goto err;
       /* always set a rsrc node */
       ret = io_rsrc_node_switch_start(ctx);
       if (ret)
              goto err;
       io_rsrc_node_switch(ctx, NULL);

       memset(&p->sq_off, 0, sizeof(p->sq_off));
       p->sq_off.head = offsetof(struct io_rings, sq.head);
       p->sq_off.tail = offsetof(struct io_rings, sq.tail);
       p->sq_off.ring_mask = offsetof(struct io_rings, sq_ring_mask);
       p->sq_off.ring_entries = offsetof(struct io_rings, sq_ring_entries);
       p->sq_off.flags = offsetof(struct io_rings, sq_flags);
       p->sq_off.dropped = offsetof(struct io_rings, sq_dropped);
       p->sq_off.array = (char *)ctx->sq_array - (char *)ctx->rings;

       memset(&p->cq_off, 0, sizeof(p->cq_off));
       p->cq_off.head = offsetof(struct io_rings, cq.head);
       p->cq_off.tail = offsetof(struct io_rings, cq.tail);
       p->cq_off.ring_mask = offsetof(struct io_rings, cq_ring_mask);
       p->cq_off.ring_entries = offsetof(struct io_rings, cq_ring_entries);
       p->cq_off.overflow = offsetof(struct io_rings, cq_overflow);
       p->cq_off.cqes = offsetof(struct io_rings, cqes);
       p->cq_off.flags = offsetof(struct io_rings, cq_flags);

       p->features = IORING_FEAT_SINGLE_MMAP | IORING_FEAT_NODROP |
                     IORING_FEAT_SUBMIT_STABLE | IORING_FEAT_RW_CUR_POS |
                     IORING_FEAT_CUR_PERSONALITY | IORING_FEAT_FAST_POLL |
                     IORING_FEAT_POLL_32BITS | IORING_FEAT_SQPOLL_NONFIXED |
                     IORING_FEAT_EXT_ARG | IORING_FEAT_NATIVE_WORKERS |
                     IORING_FEAT_RSRC_TAGS;

       if (copy_to_user(params, p, sizeof(*p))) {
              ret = -EFAULT;
              goto err;
       }

       file = io_uring_get_file(ctx);
       if (IS_ERR(file)) {
              ret = PTR_ERR(file);
              goto err;
       }

       /*
```
Install ring fd as the very last thing, so we don't risk someone having closed it before we finish setup
```c
       ret = io_uring_install_fd(ctx, file);
       if (ret < 0) {
              /* fput will clean it up */
              fput(file);
              return ret;
       }

       trace_io_uring_create(ret, ctx, p->sq_entries, p->cq_entries, p->flags);
       return ret;
err:
       io_ring_ctx_wait_and_kill(ctx);
       return ret;
}
```


#### io_sq_thread
```c

static int io_sq_thread(void *data)
{
	struct io_sq_data *sqd = data;
	struct io_ring_ctx *ctx;
	unsigned long timeout = 0;
	char buf[TASK_COMM_LEN];
	DEFINE_WAIT(wait);

	snprintf(buf, sizeof(buf), "iou-sqp-%d", sqd->task_pid);
	set_task_comm(current, buf);

	if (sqd->sq_cpu != -1)
		set_cpus_allowed_ptr(current, cpumask_of(sqd->sq_cpu));
	else
		set_cpus_allowed_ptr(current, cpu_online_mask);
	current->flags |= PF_NO_SETAFFINITY;

	mutex_lock(&sqd->lock);
	while (1) {
		bool cap_entries, sqt_spin = false;

		if (io_sqd_events_pending(sqd) || signal_pending(current)) {
			if (io_sqd_handle_event(sqd))
				break;
			timeout = jiffies + sqd->sq_thread_idle;
		}

		cap_entries = !list_is_singular(&sqd->ctx_list);
		list_for_each_entry(ctx, &sqd->ctx_list, sqd_list) {
			int ret = __io_sq_thread(ctx, cap_entries);

			if (!sqt_spin && (ret > 0 || !list_empty(&ctx->iopoll_list)))
				sqt_spin = true;
		}
		if (io_run_task_work())
			sqt_spin = true;

		if (sqt_spin || !time_after(jiffies, timeout)) {
			cond_resched();
			if (sqt_spin)
				timeout = jiffies + sqd->sq_thread_idle;
			continue;
		}

		prepare_to_wait(&sqd->wait, &wait, TASK_INTERRUPTIBLE);
		if (!io_sqd_events_pending(sqd) && !current->task_works) {
			bool needs_sched = true;

			list_for_each_entry(ctx, &sqd->ctx_list, sqd_list) {
				io_ring_set_wakeup_flag(ctx);

				if ((ctx->flags & IORING_SETUP_IOPOLL) &&
				    !list_empty_careful(&ctx->iopoll_list)) {
					needs_sched = false;
					break;
				}
				if (io_sqring_entries(ctx)) {
					needs_sched = false;
					break;
				}
			}

			if (needs_sched) {
				mutex_unlock(&sqd->lock);
				schedule();
				mutex_lock(&sqd->lock);
			}
			list_for_each_entry(ctx, &sqd->ctx_list, sqd_list)
				io_ring_clear_wakeup_flag(ctx);
		}

		finish_wait(&sqd->wait, &wait);
		timeout = jiffies + sqd->sq_thread_idle;
	}

	io_uring_cancel_generic(true, sqd);
	sqd->thread = NULL;
	list_for_each_entry(ctx, &sqd->ctx_list, sqd_list)
		io_ring_set_wakeup_flag(ctx);
	io_run_task_work();
	mutex_unlock(&sqd->lock);

	complete(&sqd->exited);
	do_exit(0);
}

```

### io_uring_enter

```c
SYSCALL_DEFINE6(io_uring_enter, unsigned int, fd, u32, to_submit,
              u32, min_complete, u32, flags, const void __user *, argp,
              size_t, argsz)
{
       struct io_ring_ctx *ctx;
       int submitted = 0;
       struct fd f;
       long ret;

       io_run_task_work();

       if (unlikely(flags & ~(IORING_ENTER_GETEVENTS | IORING_ENTER_SQ_WAKEUP |
                            IORING_ENTER_SQ_WAIT | IORING_ENTER_EXT_ARG)))
              return -EINVAL;

       f = fdget(fd);
       if (unlikely(!f.file))
              return -EBADF;

       ret = -EOPNOTSUPP;
       if (unlikely(f.file->f_op != &io_uring_fops))
              goto out_fput;

       ret = -ENXIO;
       ctx = f.file->private_data;
       if (unlikely(!percpu_ref_tryget(&ctx->refs)))
              goto out_fput;

       ret = -EBADFD;
       if (unlikely(ctx->flags & IORING_SETUP_R_DISABLED))
              goto out;

```

For SQ polling, the thread will do all submissions and completions.
Just return the requested submit count, and wake the thread if we were asked to.
     
```c
       ret = 0;
       if (ctx->flags & IORING_SETUP_SQPOLL) {
              io_cqring_overflow_flush(ctx);

              if (unlikely(ctx->sq_data->thread == NULL)) {
                     ret = -EOWNERDEAD;
                     goto out;
              }
              if (flags & IORING_ENTER_SQ_WAKEUP)
                     wake_up(&ctx->sq_data->wait);
              if (flags & IORING_ENTER_SQ_WAIT) {
                     ret = io_sqpoll_wait_sq(ctx);
                     if (ret)
                            goto out;
              }
              submitted = to_submit;
       } else if (to_submit) {
              ret = io_uring_add_tctx_node(ctx);
              if (unlikely(ret))
                     goto out;
              mutex_lock(&ctx->uring_lock);
              submitted = io_submit_sqes(ctx, to_submit);
              mutex_unlock(&ctx->uring_lock);

              if (submitted != to_submit)
                     goto out;
       }
       if (flags & IORING_ENTER_GETEVENTS) {
              const sigset_t __user *sig;
              struct __kernel_timespec __user *ts;

              ret = io_get_ext_arg(flags, argp, &argsz, &ts, &sig);
              if (unlikely(ret))
                     goto out;

              min_complete = min(min_complete, ctx->cq_entries);
```

When SETUP_IOPOLL and SETUP_SQPOLL are both enabled, user space applications don't need to do io completion events
polling again, they can rely on io_sq_thread to do polling work, which can reduce cpu usage and uring_lock contention.
```c
              if (ctx->flags & IORING_SETUP_IOPOLL &&
                  !(ctx->flags & IORING_SETUP_SQPOLL)) {
                     ret = io_iopoll_check(ctx, min_complete);
              } else {
                     ret = io_cqring_wait(ctx, min_complete, sig, argsz, ts);
              }
       }

out:
       percpu_ref_put(&ctx->refs);
out_fput:
       fdput(f);
       return submitted ? submitted : ret;
}
```



### io_uring_register

```c
SYSCALL_DEFINE4(io_uring_register, unsigned int, fd, unsigned int, opcode,
              void __user *, arg, unsigned int, nr_args)
{
       struct io_ring_ctx *ctx;
       long ret = -EBADF;
       struct fd f;

       f = fdget(fd);
       if (!f.file)
              return -EBADF;

       ret = -EOPNOTSUPP;
       if (f.file->f_op != &io_uring_fops)
              goto out_fput;

       ctx = f.file->private_data;

       io_run_task_work();

       mutex_lock(&ctx->uring_lock);
       ret = __io_uring_register(ctx, opcode, arg, nr_args);
       mutex_unlock(&ctx->uring_lock);
       trace_io_uring_register(ctx, opcode, ctx->nr_user_files, ctx->nr_user_bufs,
                                                 ctx->cq_ev_fd != NULL, ret);
out_fput:
       fdput(f);
       return ret;
}
```



```c
static int __io_uring_register(struct io_ring_ctx *ctx, unsigned opcode,
                            void __user *arg, unsigned nr_args)
       __releases(ctx->uring_lock)
       __acquires(ctx->uring_lock)
{
       int ret;

       /*
        * We're inside the ring mutex, if the ref is already dying, then
        * someone else killed the ctx or is already going through
        * io_uring_register().
        */
       if (percpu_ref_is_dying(&ctx->refs))
              return -ENXIO;

       if (ctx->restricted) {
              if (opcode >= IORING_REGISTER_LAST)
                     return -EINVAL;
              opcode = array_index_nospec(opcode, IORING_REGISTER_LAST);
              if (!test_bit(opcode, ctx->restrictions.register_op))
                     return -EACCES;
       }

       if (io_register_op_must_quiesce(opcode)) {
              ret = io_ctx_quiesce(ctx);
              if (ret)
                     return ret;
       }

       switch (opcode) {
       case IORING_REGISTER_BUFFERS:
              ret = io_sqe_buffers_register(ctx, arg, nr_args, NULL);
              break;
       case IORING_UNREGISTER_BUFFERS:
              ret = -EINVAL;
              if (arg || nr_args)
                     break;
              ret = io_sqe_buffers_unregister(ctx);
              break;
       case IORING_REGISTER_FILES:
              ret = io_sqe_files_register(ctx, arg, nr_args, NULL);
              break;
       case IORING_UNREGISTER_FILES:
              ret = -EINVAL;
              if (arg || nr_args)
                     break;
              ret = io_sqe_files_unregister(ctx);
              break;
       case IORING_REGISTER_FILES_UPDATE:
              ret = io_register_files_update(ctx, arg, nr_args);
              break;
       case IORING_REGISTER_EVENTFD:
       case IORING_REGISTER_EVENTFD_ASYNC:
              ret = -EINVAL;
              if (nr_args != 1)
                     break;
              ret = io_eventfd_register(ctx, arg);
              if (ret)
                     break;
              if (opcode == IORING_REGISTER_EVENTFD_ASYNC)
                     ctx->eventfd_async = 1;
              else
                     ctx->eventfd_async = 0;
              break;
       case IORING_UNREGISTER_EVENTFD:
              ret = -EINVAL;
              if (arg || nr_args)
                     break;
              ret = io_eventfd_unregister(ctx);
              break;
       case IORING_REGISTER_PROBE:
              ret = -EINVAL;
              if (!arg || nr_args > 256)
                     break;
              ret = io_probe(ctx, arg, nr_args);
              break;
       case IORING_REGISTER_PERSONALITY:
              ret = -EINVAL;
              if (arg || nr_args)
                     break;
              ret = io_register_personality(ctx);
              break;
       case IORING_UNREGISTER_PERSONALITY:
              ret = -EINVAL;
              if (arg)
                     break;
              ret = io_unregister_personality(ctx, nr_args);
              break;
       case IORING_REGISTER_ENABLE_RINGS:
              ret = -EINVAL;
              if (arg || nr_args)
                     break;
              ret = io_register_enable_rings(ctx);
              break;
       case IORING_REGISTER_RESTRICTIONS:
              ret = io_register_restrictions(ctx, arg, nr_args);
              break;
       case IORING_REGISTER_FILES2:
              ret = io_register_rsrc(ctx, arg, nr_args, IORING_RSRC_FILE);
              break;
       case IORING_REGISTER_FILES_UPDATE2:
              ret = io_register_rsrc_update(ctx, arg, nr_args,
                                         IORING_RSRC_FILE);
              break;
       case IORING_REGISTER_BUFFERS2:
              ret = io_register_rsrc(ctx, arg, nr_args, IORING_RSRC_BUFFER);
              break;
       case IORING_REGISTER_BUFFERS_UPDATE:
              ret = io_register_rsrc_update(ctx, arg, nr_args,
                                         IORING_RSRC_BUFFER);
              break;
       case IORING_REGISTER_IOWQ_AFF:
              ret = -EINVAL;
              if (!arg || !nr_args)
                     break;
              ret = io_register_iowq_aff(ctx, arg, nr_args);
              break;
       case IORING_UNREGISTER_IOWQ_AFF:
              ret = -EINVAL;
              if (arg || nr_args)
                     break;
              ret = io_unregister_iowq_aff(ctx);
              break;
       case IORING_REGISTER_IOWQ_MAX_WORKERS:
              ret = -EINVAL;
              if (!arg || nr_args != 2)
                     break;
              ret = io_register_iowq_max_workers(ctx, arg);
              break;
       default:
              ret = -EINVAL;
              break;
       }

       if (io_register_op_must_quiesce(opcode)) {
              /* bring the ctx back to life */
              percpu_ref_reinit(&ctx->refs);
              reinit_completion(&ctx->ref_comp);
       }
       return ret;
}
```





### io_uring_submit

Submit sqes acquired from io_uring_get_sqe() to the kernel.
Returns number of sqes submitted

```c
// tools/io_uring/queue.c
int io_uring_submit(struct io_uring *ring)
{
       struct io_uring_sq *sq = &ring->sq;
       const unsigned mask = *sq->kring_mask;
       unsigned ktail, ktail_next, submitted, to_submit;
       int ret;

       /*
        * If we have pending IO in the kring, submit it first. We need a
        * read barrier here to match the kernels store barrier when updating
        * the SQ head.
        */
       read_barrier();
       if (*sq->khead != *sq->ktail) {
              submitted = *sq->kring_entries;
              goto submit;
       }

       if (sq->sqe_head == sq->sqe_tail)
              return 0;

       /*
        * Fill in sqes that we have queued up, adding them to the kernel ring
        */
       submitted = 0;
       ktail = ktail_next = *sq->ktail;
       to_submit = sq->sqe_tail - sq->sqe_head;
       while (to_submit--) {
              ktail_next++;
              read_barrier();

              sq->array[ktail & mask] = sq->sqe_head & mask;
              ktail = ktail_next;

              sq->sqe_head++;
              submitted++;
       }

       if (!submitted)
              return 0;

       if (*sq->ktail != ktail) {
              /*
               * First write barrier ensures that the SQE stores are updated
               * with the tail update. This is needed so that the kernel
               * will never see a tail update without the preceeding sQE
               * stores being done.
               */
              write_barrier();
              *sq->ktail = ktail;
              /*
               * The kernel has the matching read barrier for reading the
               * SQ tail.
               */
              write_barrier();
       }

submit:
       ret = io_uring_enter(ring->ring_fd, submitted, 0,
                            IORING_ENTER_GETEVENTS, NULL);
       if (ret < 0)
              return -errno;

       return ret;
}
```





## References

1. [An Introduction to the io_uring Asynchronous I/O Framework](https://blogs.oracle.com/site/linux/post/an-introduction-to-the-io-uring-asynchronous-io-framework)
2. [Improved_Storage_Performance_Using_the_New_Linux_Kernel_I.O_Interface](https://www.snia.org/sites/default/files/SDC/2019/presentations/Storage_Performance/Kariuki_John_Verma_Vishal_Improved_Storage_Performance_Using_the_New_Linux_Kernel_I.O_Interface.pdf)
3. [Efficient IO with io_uring](https://kernel.dk/io_uring.pdf)
4. [What’s new with io_uring](https://kernel.dk/io_uring-whatsnew.pdf)