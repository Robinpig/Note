## Introduction

```shell
#include <sys/epoll.h>
```

epoll 是 Linux 特有的 I/O 事件通知机制，功能与 `poll` 类似——监控多个文件描述符、等待其中任意一个可进行 I/O——但它把"维护关注集合"和"等待就绪"拆开，并以回调驱动、只返回就绪 fd，因此在被监控描述符数量很大时仍能保持高性能。epoll 支持边沿触发（edge-triggered）和水平触发（level-triggered）两种通知方式。使用它要经过三个系统调用：

- `epoll_create(2)` / `epoll_create1(2)`：创建一个 epoll 实例，返回指向它的文件描述符；
- `epoll_ctl(2)`：向实例中注册/修改/删除感兴趣的文件描述符，当前注册在一个 epoll 实例上的集合称为 epoll set；
- `epoll_wait(2)`：等待 I/O 事件，没有就绪事件时阻塞调用线程。

一个最小的使用骨架：

```c
int main(){
  listen(lfd, ...);
  cfd1 = accept(...);
  cfd2 = accept(...);

  efd = epoll_create(...);
  epoll_ctl(efd, EPOLL_CTL_ADD, cfd1, ...);
  epoll_ctl(efd, EPOLL_CTL_ADD, cfd2, ...);
  epoll_wait(efd, ...)
}
```


## epoll_create



申请分配 `eventpoll` 所需的内存并初始化

```c
// fs/eventpoll.c
SYSCALL_DEFINE1(epoll_create1, int, flags)
{
	return do_epoll_create(flags);
}

static int do_epoll_create(int flags)
{
	struct eventpoll *ep = NULL;
	ep_alloc(&ep);

}
```




```c
// fs/eventpoll.c
static int ep_alloc(struct eventpoll **pep)
{
    ep = kzalloc(sizeof(*ep), GFP_KERNEL);
	...
    
	init_waitqueue_head(&ep->wq);
	init_waitqueue_head(&ep->poll_wait);
	INIT_LIST_HEAD(&ep->rdllist);
	ep->rbr = RB_ROOT_CACHED;
	ep->ovflist = EP_UNACTIVE_PTR;
}
```

接下来，分配一个空闲的文件描述符 `fd` 和匿名文件 `file` 。注意，`eventpoll` 实例会保存一份匿名文件的引用，并通过调用 `fd_install` 将文件描述符和匿名文件关联起来。

另外还需注意 `anon_inode_getfile` 调用时将 `eventpoll` 作为匿名文件的 `private_data` 保存了起来。后面就可以通过 `epoll` 实例的文件描述符快速的找到 `eventpoll` 对象。

最后，将文件描述符 `fd` 作为 epoll 的句柄返回给调用者。**`epoll` 实例其实就是一个匿名文件**

```c
static int do_epoll_create(int flags)

{
// ...

fd = get_unused_fd_flags(O_RDWR | (flags & O_CLOEXEC));

if (fd < 0) {

error = fd;

goto out_free_ep;

}

file = anon_inode_getfile("[eventpoll]", &eventpoll_fops, ep,

O_RDWR | (flags & O_CLOEXEC));

if (IS_ERR(file)) {

error = PTR_ERR(file);

goto out_free_fd;

}

ep->file = file;

fd_install(fd, file);

return fd;

}
```


### eventpoll

这个结构保存在 file 的 `private_data` 中，是 eventpoll 接口的核心数据结构。

- wq 存储等待进程
- rdlist for ready file descriptors
- rbr for monitored fd structs
- *ovflist : This is a single linked list that chains all the "struct epitem" that happened while transferring ready events to userspace w/out holding ->lock.


```c
struct eventpoll {
	/* Wait queue used by sys_epoll_wait() */
	wait_queue_head_t wq;

	/* Wait queue used by file->poll() */
	wait_queue_head_t poll_wait;

	/* List of ready file descriptors */
	struct list_head rdllist;

	/* RB tree root used to store monitored fd structs */
	struct rb_root_cached rbr;

	/*
	 * This is a single linked list that chains all the "struct epitem" that
	 * happened while transferring ready events to userspace w/out
	 * holding ->lock.
	 */
	struct epitem *ovflist;
};
```


## epoll_ctl

下面是 eventpoll 文件的控制接口实现，负责在关注集合中插入、删除或修改文件描述符。

1. create epitem
2. Add socket to wait queue, set callback `ep_poll_callback`
3. insert epitem into rbtree

```c
// fs/eventpoll.c
SYSCALL_DEFINE4(epoll_ctl, int, epfd, int, op, int, fd,
		struct epoll_event __user *, event)
{
	return do_epoll_ctl(epfd, op, fd, &epds, false);
}

int do_epoll_ctl(int epfd, int op, int fd, struct epoll_event *epds,
               bool nonblock)
{
       struct fd f, tf;
       struct eventpoll *ep;
       struct epitem *epi;
       struct eventpoll *tep = NULL;

       f = fdget(epfd);

       /* Get the "struct file *" for the target file */
       tf = fdget(fd);

       /*
        * epoll adds to the wakeup queue at EPOLL_CTL_ADD time only,
        * so EPOLLEXCLUSIVE is not allowed for a EPOLL_CTL_MOD operation.
        * Also, we do not currently supported nested exclusive wakeups.
        */
       if (ep_op_has_event(op) && (epds->events & EPOLLEXCLUSIVE)) {
              if (op == EPOLL_CTL_MOD)
                     goto error_tgt_fput;
              if (op == EPOLL_CTL_ADD && (is_file_epoll(tf.file) ||
                            (epds->events & ~EPOLLEXCLUSIVE_OK_BITS)))
                     goto error_tgt_fput;
       }

       /*
        * At this point it is safe to assume that the "private_data" contains
        * our own data structure.
        */
       ep = f.file->private_data;

      
       /*
        * Try to lookup the file inside our RB tree. Since we grabbed "mtx"
        * above, we can be sure to be able to use the item looked up by
        * ep_find() till we release the mutex.
        */
       epi = ep_find(ep, tf.file, fd);

       switch (op) {
       case EPOLL_CTL_ADD:
              if (!epi) {
                     epds->events |= EPOLLERR | EPOLLHUP;
                     error = ep_insert(ep, epds, tf.file, fd, full_check);
              } else
                     error = -EEXIST;
              break;
       ...
       }
}
```

### ep_insert

1. zmalloc epitem
2. insert into rb
3. Initialize the poll table in `ep_ptable_queue_proc`
4. set revents = `ep_item_poll`

```c
/*
 * Must be called with "mtx" held.
 */
static int ep_insert(struct eventpoll *ep, const struct epoll_event *event,
		     struct file *tfile, int fd, int full_check)
{
	__poll_t revents;
	struct epitem *epi;
	struct ep_pqueue epq;
	struct eventpoll *tep = NULL;

	if (!(epi = kmem_cache_zalloc(epi_cache, GFP_KERNEL)))
		return -ENOMEM;

	/* Item initialization follow here ... */
	INIT_LIST_HEAD(&epi->rdllink);
	epi->ep = ep;
	ep_set_ffd(&epi->ffd, tfile, fd);
	epi->event = *event;
	epi->next = EP_UNACTIVE_PTR;

	ep_rbtree_insert(ep, epi);
	
	/* Initialize the poll table using the queue callback */
	epq.epi = epi;
	init_poll_funcptr(&epq.pt, ep_ptable_queue_proc);


	revents = ep_item_poll(epi, &epq.pt, 1);

	/* record NAPI ID of new item if present */
	ep_set_busy_poll_napi_id(epi);
}
```


#### epitem



每个添加到 eventpoll 的文件描述符都会有一个对应的 epitem，挂在红黑树 `rbr` 上。注意不要增大这个结构——服务器上可能有成千上万个，多占一个缓存行都会显著增加内存开销。

```c
struct epitem {
	/* List header used to link this structure to the eventpoll ready list */
	struct list_head rdllink;

	struct epitem *next;

	struct epoll_filefd ffd;

	/* List containing poll wait queues */
	struct eppoll_entry *pwqlist;

	struct eventpoll *ep;

	/* The structure that describe the interested events and the source fd */
	struct epoll_event event;
};
```

#### ep_ptable_queue_proc

初始化 poll table，队列回调设为 `ep_poll_callback`，它会在 [sk_data_ready](/docs/CS/OS/Linux/net/network.md?id=sk_data_ready) 时被调用。

这个回调负责把我们的等待队列添加到目标文件的唤醒链表上。
```c
static void ep_ptable_queue_proc(struct file *file, wait_queue_head_t *whead,
				 poll_table *pt)
{
	pwq = kmem_cache_alloc(pwq_cache, GFP_KERNEL);
	init_waitqueue_func_entry(&pwq->wait, ep_poll_callback);	
    add_wait_queue(whead, &pwq->wait);
}
```

set func for each socket in order to call by [sock_def_readable](/docs/CS/OS/Linux/net/TCP/TCP.md?id=tcp_data_ready)

```c
// include/linux/wait.h

static inline void
init_waitqueue_func_entry(struct wait_queue_entry *wq_entry, wait_queue_func_t func)
{
	wq_entry->flags		= 0;
	wq_entry->private	= NULL;
	wq_entry->func		= func;
}
```



```c
// kernel/sched/wait.c
void add_wait_queue_exclusive(struct wait_queue_head *wq_head, struct wait_queue_entry *wq_entry)
{
	unsigned long flags;

	wq_entry->flags |= WQ_FLAG_EXCLUSIVE;
	spin_lock_irqsave(&wq_head->lock, flags);
	__add_wait_queue_entry_tail(wq_head, wq_entry);
	spin_unlock_irqrestore(&wq_head->lock, flags);
}
```



#### ep_item_poll

与 `ep_eventpoll_poll()` 的区别在于：内部调用者已经持有 ep->mtx，所以这里要从 depth=1 开始，让 `mutex_lock_nested()` 能正确标注锁的嵌套层级。

```c

static __poll_t ep_item_poll(const struct epitem *epi, poll_table *pt,
				 int depth)
{
	struct file *file = epi->ffd.file;
	__poll_t res;

	pt->_key = epi->event.events;
	if (!is_file_epoll(file))
		res = vfs_poll(file, pt);
	else
		res = __ep_eventpoll_poll(file, pt, depth);
	return res & epi->event.events;
}


// include/linux/poll.h
static inline __poll_t vfs_poll(struct file *file, struct poll_table_struct *pt)
{
	if (unlikely(!file->f_op->poll))
		return DEFAULT_POLLMASK;
	return file->f_op->poll(file, pt);
}

// fs/eventpoll.c
static __poll_t __ep_eventpoll_poll(struct file *file, poll_table *wait, int depth)
{
	struct eventpoll *ep = file->private_data;
	LIST_HEAD(txlist);
	struct epitem *epi, *tmp;
	poll_table pt;
	__poll_t res = 0;

	init_poll_funcptr(&pt, NULL);

	/* Insert inside our poll wait queue */
	poll_wait(file, &ep->poll_wait, wait);

	/*
	 * Proceed to find out if wanted events are really available inside
	 * the ready list.
	 */
	mutex_lock_nested(&ep->mtx, depth);
	ep_start_scan(ep, &txlist);
	list_for_each_entry_safe(epi, tmp, &txlist, rdllink) {
		if (ep_item_poll(epi, &pt, depth + 1)) {
			res = EPOLLIN | EPOLLRDNORM;
			break;
		} else {
			/*
			 * Item has been dropped into the ready list by the poll
			 * callback, but it's not actually ready, as far as
			 * caller requested events goes. We can remove it here.
			 */
			__pm_relax(ep_wakeup_source(epi));
			list_del_init(&epi->rdllink);
		}
	}
	ep_done_scan(ep, &txlist);
	mutex_unlock(&ep->mtx);
	return res;
}
```





## epoll_wait



```c
// fs/eventpoll.c
SYSCALL_DEFINE4(epoll_wait, int, epfd, struct epoll_event __user *, events,
              int, maxevents, int, timeout)
{
       return do_epoll_wait(epfd, events, maxevents, ...);
}

static int do_epoll_wait(int epfd, struct epoll_event __user *events,
                      int maxevents, struct timespec64 *to)
{
       ep_poll(ep, events, maxevents, to);
}
```

### ep_poll

取出就绪事件，投递到调用者提供的事件缓冲区。
- 若 ep_events_available 有事件，走 ep_send_events
- 否则挂起等待



Do the final check under the lock. ep_scan_ready_list() plays with two lists (->rdllist and ->ovflist) and there is always a race when both lists are empty for short period of time although events are pending, so lock is important.

```c
static int ep_poll(struct eventpoll *ep, struct epoll_event __user *events,
                 int maxevents, struct timespec64 *timeout)
{
       int res, eavail, timed_out = 0;
       wait_queue_entry_t wait;

       eavail = ep_events_available(ep);
       while (1) {
              if (eavail) {
                     res = ep_send_events(ep, events, maxevents);
              }

              init_wait(&wait);
              __set_current_state(TASK_INTERRUPTIBLE);

              eavail = ep_events_available(ep);
              if (!eavail)
                     __add_wait_queue_exclusive(&ep->wq, &wait);

              timed_out = !schedule_hrtimeout_range(to, slack,
                                                       HRTIMER_MODE_ABS);
              __set_current_state(TASK_RUNNING);
       }
}
```



#### ep_events_available

检查是否可能存在就绪事件。

这个检查是有竞态的：我们不一定能看到正在锁保护下被加入就绪链表的事件（如中断回调里添加的）。
- 对于非零超时，本线程随后会在锁内再次检查就绪链表，并把自己加进等待队列；
- 对于零超时，调用方本就只做探测，需要自行再次确认。

```c

static inline int ep_events_available(struct eventpoll *ep)
{
	return !list_empty_careful(&ep->rdllist) ||
		READ_ONCE(ep->ovflist) != EP_UNACTIVE_PTR;
}
```




#### init_wait

init_wait() 内部用的是 `default_wake_function()`，等待项在每次唤醒后会从等待队列移除。为什么这很重要？当有多个等待者时，每次新的唤醒会命中下一个等待者，让它也有机会收割新事件。

否则唤醒可能丢失。这在性能上也有好处：正常唤醒路径上不必显式调用 `__remove_wait_queue()`，从而不必取 ep->lock——取锁会中断事件投递。

```c
// include/linux/wait.h
#define init_wait(wait)								\
	do {									\
		(wait)->private = current;					\
		(wait)->func = autoremove_wake_function;			\
		INIT_LIST_HEAD(&(wait)->entry);					\
		(wait)->flags = 0;						\
	} while (0)

int autoremove_wake_function(struct wait_queue_entry *wq_entry, unsigned mode, int sync, void *key)
{
	int ret = default_wake_function(wq_entry, mode, sync, key);

	if (ret)
		list_del_init_careful(&wq_entry->entry);

	return ret;
}
```



```c
// kernel/sched/core.c
int default_wake_function(wait_queue_entry_t *curr, unsigned mode, int wake_flags,
			  void *key)
{
	WARN_ON_ONCE(IS_ENABLED(CONFIG_SCHED_DEBUG) && wake_flags & ~WF_SYNC);
	return try_to_wake_up(curr->private, mode, wake_flags);
}
```





#### add_wait_queue

Used for wake-one threads:

```c
// include/linux/wait.h
static inline void
__add_wait_queue_exclusive(struct wait_queue_head *wq_head, struct wait_queue_entry *wq_entry)
{
	wq_entry->flags |= WQ_FLAG_EXCLUSIVE;
	__add_wait_queue(wq_head, wq_entry);
}


static inline void __add_wait_queue(struct wait_queue_head *wq_head, struct wait_queue_entry *wq_entry)
{
	struct list_head *head = &wq_head->head;
	struct wait_queue_entry *wq;

	list_for_each_entry(wq, &wq_head->head, entry) {
		if (!(wq->flags & WQ_FLAG_PRIORITY))
			break;
		head = &wq->entry;
	}
	list_add(&wq_entry->entry, head);
}
```



#### ep_send_events
尝试把事件转交到用户空间。若一个事件都没取到、且还有剩余超时，就再循环碰运气。
调用 [ep_item_poll](/docs/CS/OS/Linux/IO/epoll.md?id=ep_item_poll)

```c

static int ep_send_events(struct eventpoll *ep,
			  struct epoll_event __user *events, int maxevents)
{
	struct epitem *epi, *tmp;
	LIST_HEAD(txlist);
	poll_table pt;
	int res = 0;

	/*
	 * Always short-circuit for fatal signals to allow threads to make a
	 * timely exit without the chance of finding more events available and
	 * fetching repeatedly.
	 */
	if (fatal_signal_pending(current))
		return -EINTR;

	init_poll_funcptr(&pt, NULL);

	mutex_lock(&ep->mtx);
	ep_start_scan(ep, &txlist);

	/*
	 * We can loop without lock because we are passed a task private list.
	 * Items cannot vanish during the loop we are holding ep->mtx.
	 */
	list_for_each_entry_safe(epi, tmp, &txlist, rdllink) {
		struct wakeup_source *ws;
		__poll_t revents;

		if (res >= maxevents)
			break;

		/*
		 * Activate ep->ws before deactivating epi->ws to prevent
		 * triggering auto-suspend here (in case we reactive epi->ws
		 * below).
		 *
		 * This could be rearranged to delay the deactivation of epi->ws
		 * instead, but then epi->ws would temporarily be out of sync
		 * with ep_is_linked().
		 */
		ws = ep_wakeup_source(epi);
		if (ws) {
			if (ws->active)
				__pm_stay_awake(ep->ws);
			__pm_relax(ws);
		}

		list_del_init(&epi->rdllink);

		/*
		 * If the event mask intersect the caller-requested one,
		 * deliver the event to userspace. Again, we are holding ep->mtx,
		 * so no operations coming from userspace can change the item.
		 */
		revents = ep_item_poll(epi, &pt, 1);
		if (!revents)
			continue;

		events = epoll_put_uevent(revents, epi->event.data, events);
		if (!events) {
			list_add(&epi->rdllink, &txlist);
			ep_pm_stay_awake(epi);
			if (!res)
				res = -EFAULT;
			break;
		}
		res++;
```

If this file has been added with Level Trigger mode, we need to insert back inside the ready list, so that the next call to `epoll_wait()` will check again the events availability. At this point, no one can insert into `ep->rdllist` besides us. The `epoll_ctl()` callers are locked out by` ep_scan_ready_list()` holding "mtx" and the poll callback will queue them in `ep->ovflist`.
```c
		if (epi->event.events & EPOLLONESHOT)
			epi->event.events &= EP_PRIVATE_BITS;
		else if (!(epi->event.events & EPOLLET)) {
			list_add_tail(&epi->rdllink, &ep->rdllist);
			ep_pm_stay_awake(epi);
		}
```

```c
	}
	ep_done_scan(ep, &txlist);
	mutex_unlock(&ep->mtx);

	return res;
}
```



#### schedule_hrtimeout_range

call [schedule]()
```c

/**
 * schedule_hrtimeout_range - sleep until timeout
 * @expires:	timeout value (ktime_t)
 * @delta:	slack in expires timeout (ktime_t)
 * @mode:	timer mode
 *
 * Make the current task sleep until the given expiry time has
 * elapsed. The routine will return immediately unless
 * the current task state has been set (see set_current_state()).
 *
 * The @delta argument gives the kernel the freedom to schedule the
 * actual wakeup to a time that is both power and performance friendly.
 * The kernel give the normal best effort behavior for "@expires+@delta",
 * but may decide to fire the timer earlier, but no earlier than @expires.
 *
 * You can set the task state as follows -
 *
 * %TASK_UNINTERRUPTIBLE - at least @timeout time is guaranteed to
 * pass before the routine returns unless the current task is explicitly
 * woken up, (e.g. by wake_up_process()).
 *
 * %TASK_INTERRUPTIBLE - the routine may return early if a signal is
 * delivered to the current task or the current task is explicitly woken
 * up.
 *
 * The current task state is guaranteed to be TASK_RUNNING when this
 * routine returns.
 *
 * Returns 0 when the timer has expired. If the task was woken before the
 * timer expired by a signal (only possible in state TASK_INTERRUPTIBLE) or
 * by an explicit wakeup, it returns -EINTR.
 */
int __sched schedule_hrtimeout_range(ktime_t *expires, u64 delta,
				     const enum hrtimer_mode mode)
{
	return schedule_hrtimeout_range_clock(expires, delta, mode,
					      CLOCK_MONOTONIC);
}


/** sleep until timeout */
int __sched
schedule_hrtimeout_range_clock(ktime_t *expires, u64 delta,
			       const enum hrtimer_mode mode, clockid_t clock_id)
{
	struct hrtimer_sleeper t;

	/*
	 * Optimize when a zero timeout value is given. It does not
	 * matter whether this is an absolute or a relative time.
	 */
	if (expires && *expires == 0) {
		__set_current_state(TASK_RUNNING);
		return 0;
	}

	/*
	 * A NULL parameter means "infinite"
	 */
	if (!expires) {
		schedule();
		return -EINTR;
	}

	hrtimer_init_sleeper_on_stack(&t, clock_id, mode);
	hrtimer_set_expires_range_ns(&t.timer, *expires, delta);
	hrtimer_sleeper_start_expires(&t, mode);

	if (likely(t.task))
		schedule();

	hrtimer_cancel(&t.timer);
	destroy_hrtimer_on_stack(&t.timer);

	__set_current_state(TASK_RUNNING);

	return !t.task ? 0 : -EINTR;
}
```






#### ep_poll_callback

这个回调被传给等待队列的唤醒机制：当被监控的文件描述符有事件要报告时调用它。
它取读锁以避免与来自其它文件描述符的并发事件争抢，因此对 ->rdllist 和 ->ovflist 的所有修改都是无锁的。读锁与 ep_scan_ready_list() 持有的写锁配对——后者会暂停所有链表修改、保证链表状态被正确读取。

另一点值得注意：如果 poll table 初始化时注册了多个等待队列项，ep_poll_callback() 可能在不同 CPU 上针对同一个 @epi 被并发调用。单个等待队列来自不同 CPU 的多次唤醒由 wq.lock 串行化；但用到多个等待队列时需要专门检测重复，这通过 cmpxchg() 操作完成。

1. 从 wait 取出 epitem
2. 把事件加入就绪链表
3. 若 eventpoll 等待链表和 ->poll() 等待链表处于活动状态，唤醒它们

ep_pol_callback ->`ep_poll_safewake`->[wake_up_poll](/docs/CS/OS/Linux/proc/thundering_herd.md?id=wake_up_poll)


```c
//
static int ep_poll_callback(wait_queue_entry_t *wait, unsigned mode, int sync, void *key)
{
	int pwake = 0;
	struct epitem *epi = ep_item_from_wait(wait);
	struct eventpoll *ep = epi->ep;
	__poll_t pollflags = key_to_poll(key);
	unsigned long flags;
	int ewake = 0;

	read_lock_irqsave(&ep->lock, flags);

	ep_set_busy_poll_napi_id(epi);

	/*
	 * If the event mask does not contain any poll(2) event, we consider the
	 * descriptor to be disabled. This condition is likely the effect of the
	 * EPOLLONESHOT bit that disables the descriptor when an event is received,
	 * until the next EPOLL_CTL_MOD will be issued.
	 */
	if (!(epi->event.events & ~EP_PRIVATE_BITS))
		goto out_unlock;

	/*
	 * Check the events coming with the callback. At this stage, not
	 * every device reports the events in the "key" parameter of the
	 * callback. We need to be able to handle both cases here, hence the
	 * test for "key" != NULL before the event match test.
	 */
	if (pollflags && !(pollflags & epi->event.events))
		goto out_unlock;

	/*
	 * If we are transferring events to userspace, we can hold no locks
	 * (because we're accessing user memory, and because of linux f_op->poll()
	 * semantics). All the events that happen during that period of time are
	 * chained in ep->ovflist and requeued later on.
	 */
	if (READ_ONCE(ep->ovflist) != EP_UNACTIVE_PTR) {
		if (chain_epi_lockless(epi))
			ep_pm_stay_awake_rcu(epi);
	} else if (!ep_is_linked(epi)) {
		/* In the usual case, add event to ready list. */
		if (list_add_tail_lockless(&epi->rdllink, &ep->rdllist))
			ep_pm_stay_awake_rcu(epi);
	}

	/*
	 * Wake up ( if active ) both the eventpoll wait list and the ->poll()
	 * wait list.
	 */
	if (waitqueue_active(&ep->wq)) {
		if ((epi->event.events & EPOLLEXCLUSIVE) &&
					!(pollflags & POLLFREE)) {
			switch (pollflags & EPOLLINOUT_BITS) {
			case EPOLLIN:
				if (epi->event.events & EPOLLIN)
					ewake = 1;
				break;
			case EPOLLOUT:
				if (epi->event.events & EPOLLOUT)
					ewake = 1;
				break;
			case 0:
				ewake = 1;
				break;
			}
		}
		wake_up(&ep->wq); /** call __wake_up_common */
	}
	if (waitqueue_active(&ep->poll_wait))
		pwake++;

out_unlock:
	read_unlock_irqrestore(&ep->lock, flags);

	/* We have to call this outside the lock */
	if (pwake)
		ep_poll_safewake(ep, epi);

	if (!(epi->event.events & EPOLLEXCLUSIVE))
		ewake = 1;

	if (pollflags & POLLFREE) {
		/*
		 * If we race with ep_remove_wait_queue() it can miss
		 * ->whead = NULL and do another remove_wait_queue() after
		 * us, so we can't use __remove_wait_queue().
		 */
		list_del_init(&wait->entry);
		/*
		 * ->whead != NULL protects us from the race with ep_free()
		 * or ep_remove(), ep_remove_wait_queue() takes whead->lock
		 * held by the caller. Once we nullify it, nothing protects
		 * ep/epi or even wait.
		 */
		smp_store_release(&ep_pwq_from_wait(wait)->whead, NULL);
	}

	return ewake;
}

```

## ET & LT

epoll 通知就绪的时机有两种，决定上层事件循环怎么写。

**LT（水平触发，默认）**：只要 fd 的条件仍然成立（数据没被读完、仍可写），每次 `epoll_wait` 都会通知它。语义与 `poll(2)` 完全一致，可以看作"一个更快的 poll"，编程简单、不易漏事件，代价是可能重复通知。

**ET（边沿触发）**：只在 fd 状态"从无到有"发生变化时通知一次，之后即使数据没读完也不再通知。用一个经典场景说明：pipe 写端写入 2KB → `epoll_wait` 返回读端就绪 → 读端只读走 1KB → 再次 `epoll_wait`。若以 `EPOLLET` 注册，第二次调用会一直阻塞，尽管缓冲区里还剩 1KB——因为边沿事件已在第一次被消费、状态没有再变化，等待者可能因此饿死。

所以用 ET 必须遵守两条规则：

1. 把 fd 设为**非阻塞**，避免一次阻塞读写卡住处理多个 fd 的任务；
2. 收到事件后用循环一直 read/write，直到返回 `EAGAIN`，确认本次就绪的数据已被完全处理。

对包/令牌型文件（数据报 socket、规范模式终端），只能靠读到 `EAGAIN` 判断结束；对流式文件（pipe、FIFO、流 socket），也可通过"请求读 N 字节但返回少于 N"判断数据已耗尽。ET 减少了通知次数、配合非阻塞 I/O 性能更高，是高性能框架的主流选择，但代价是编程更易出错。

**EPOLLONESHOT**：即使在 ET 下，一个 fd 也可能因多次数据到达而产生多个事件。设了 `EPOLLONESHOT` 后，epoll 在交付一次事件后就禁用该 fd，必须由调用方用 `epoll_ctl(EPOLL_CTL_MOD)` 重新武装，适合需要严格控制"同一 fd 同时只有一个线程处理"的场景。

LT 与 ET 的分叉点在 `ep_send_events` 的内核逻辑里：事件拷给用户空间后，检查该 fd 的模式——若既不是 ET 也不是 ONESHOT，就把 epitem **重新挂回 rdllist**，于是下次 `epoll_wait` 仍会通知（LT）；ET 则不挂回，等待下一次状态变化。

一个 ET 模式的最小服务端骨架：监听 socket 就绪后 `accept` 出新连接、设为非阻塞、以 `EPOLLIN | EPOLLET` 注册；已连接 fd 就绪则循环处理到 `EAGAIN`。

```c
#define MAX_EVENTS 10
struct epoll_event ev, events[MAX_EVENTS];
int listen_sock, epollfd;

epollfd = epoll_create1(0);
ev.events = EPOLLIN;
ev.data.fd = listen_sock;
epoll_ctl(epollfd, EPOLL_CTL_ADD, listen_sock, &ev);

for (;;) {
	int nfds = epoll_wait(epollfd, events, MAX_EVENTS, -1);
	for (int n = 0; n < nfds; ++n) {
		if (events[n].data.fd == listen_sock) {
			int conn_sock = accept(listen_sock, NULL, NULL);
			setnonblocking(conn_sock);
			ev.events = EPOLLIN | EPOLLET;
			ev.data.fd = conn_sock;
			epoll_ctl(epollfd, EPOLL_CTL_ADD, conn_sock, &ev);
		} else {
			/* 循环 read/write 直到 EAGAIN */
			do_use_fd(events[n].data.fd);
		}
	}
}
```

ET 使用上的两个常见坑：

- **饿死其它 fd**：一个 fd 有海量数据时，若一直埋头 drain 它，其它 fd 会迟迟得不到处理。解法是维护应用自己的就绪列表、标记 fd 状态，在所有就绪 fd 间轮转，而不是死磕一个。
- **事件缓存与 fd 提前关闭**：若一次 `epoll_wait` 返回多个事件、处理 #47 时关闭了 #13 的 fd，缓存里 #13 的记录就成了悬空引用。应在关闭时同步 `EPOLL_CTL_DEL` 并把它在缓存中标记为已移除。

## 资源限制

`/proc/sys/fs/epoll/max_user_watches`（Linux 2.6.28+）限制一个真实用户在系统所有 epoll 实例上能注册的 fd 总数。每个注册项在 32 位内核约占 90 字节、64 位约 160 字节；默认值为可用低端内存的约 4% 除以单项开销。epoll API 自内核 2.5.44 引入、glibc 2.3.2 起支持，是 Linux 特有接口（FreeBSD 对应 kqueue）。某进程正在监控的 fd 集合可在 `/proc/[pid]/fdinfo` 中查看。

## Summary

1. `epoll_create` 创建 `eventpoll`
2. `epoll_ctl` 把 socket 加入/修改/移出红黑树
3. `epoll_wait` 检查就绪链表，否则挂进 ep->wq 调度睡眠
4. 被回调唤醒后重新检查就绪链表并返回

数据面：socket 收到数据 → epitem 被加入就绪链表 → 从 wq 唤醒等待进程。

## Links

- [I/O 与多路复用（目录枢纽）](/docs/CS/OS/Linux/IO/README.md)
- [multiplexing（select/poll）](/docs/CS/OS/Linux/IO/multiplexing.md)
- [io_uring](/docs/CS/OS/Linux/IO/io_uring.md)
- [Nginx Event](/docs/CS/CN/nginx/event.md)

## References

1. [epoll(7) — I/O event notification facility](https://man7.org/linux/man-pages/man7/epoll.7.html)
