## Introduction


```shell
#include <sys/epoll.h>
```

The  epoll  API  performs  a similar task to `poll`: monitoring multiple file descriptors to see if I/O is possible on any of them. 
The epoll API can be used either as an edge-triggered or a level-triggered interface and scales well to large numbers of watched file descriptors. 
The following system calls are provided to create and manage an epoll instance:

* epoll_create(2)  creates  a  new epoll instance and returns a file descriptor referring to that instance.  
  (The more recent epoll_create1(2) extends the functionality of epoll_create(2).)
* Interest in particular file descriptors is then registered via epoll_ctl(2).  
  The set of file descriptors currently  registered on an epoll instance is sometimes called an epoll set.
* epoll_wait(2) waits for I/O events, blocking the calling thread if no events are currently available.


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

This structure is stored inside the "private_data" member of the file structure and represents the main data structure for the eventpoll interface.

- rdlist : storage ready file descriptors
- rbr root of rb
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

The following function implements the controller interface for the eventpoll file that enables the insertion/removal/change of file descriptors inside the interest set.

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



Each file descriptor added to the eventpoll interface will have an entry of this type linked to the "rbr" RB tree.
Avoid increasing the size of this struct, there can be many thousands of these on a server and we do not want this to take another cache line.

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

Initialize the poll table using the queue callback = `ep_poll_callback` which will be invoked at [sk_data_ready](/docs/CS/OS/Linux/net/network.md?id=sk_data_ready).

This is the callback that is used to add our wait queue to the target file wakeup lists.
```c
static void ep_ptable_queue_proc(struct file *file, wait_queue_head_t *whead,
				 poll_table *pt)
{
	pwq = kmem_cache_alloc(pwq_cache, GFP_KERNEL);
	init_waitqueue_func_entry(&pwq->wait, ep_poll_callback);	
    add_wait_queue(whead, &pwq->wait);
}
```

set func for each socket in order to call by [sock_def_readable](/docs/CS/OS/Linux/TCP.md?id=tcp_data_ready)

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

Differs from `ep_eventpoll_poll()` in that internal callers already have the ep->mtx so we need to start from depth=1, such that mutex_lock_nested() is correctly annotated.

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

Retrieves ready events, and delivers them to the caller-supplied event buffer.
- if ep_events_available, ep_send_events
- else wait 



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

Checks if ready events might be available.

This call is racy: We may or may not see events that are being added to the ready list under the lock (e.g., in IRQ callbacks). 
- For cases with a non-zero timeout, this thread will check the ready list under lock and will add to the wait queue. 
- For cases with a zero timeout, the user by definition should not care and will have to recheck again.

```c

static inline int ep_events_available(struct eventpoll *ep)
{
	return !list_empty_careful(&ep->rdllist) ||
		READ_ONCE(ep->ovflist) != EP_UNACTIVE_PTR;
}
```




#### init_wait

Internally init_wait() uses `default_wake_function()`, thus wait entry is removed from the wait queue on each wakeup. Why it is important? In case of several waiters each new wakeup will hit the next waiter, giving it the chance to harvest new event. 

Otherwise wakeup can be lost. This is also good performance-wise, because on normal wakeup path no need to call `__remove_wait_queue()` explicitly, thus ep->lock is not taken, which halts the event delivery.

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
Try to transfer events to user space. In case we get 0 events and there's still timeout left over, we go trying again in search of more luck.
call [ep_item_poll](/docs/CS/OS/Linux/epoll.md?id=ep_item_poll)

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

This is the callback that is passed to the wait queue wakeup mechanism. It is called by the stored file descriptors when they have events to report.
This callback takes a read lock in order not to contend with concurrent events from another file descriptor, thus all modifications to ->rdllist or ->ovflist are lockless.  Read lock is paired with the write lock from ep_scan_ready_list(), which stops all list modifications and guarantees that lists state is seen correctly.

Another thing worth to mention is that ep_poll_callback() can be called concurrently for the same @epi from different CPUs if poll table was inited with several wait queues entries.  Plural wakeup from different CPUs of a
single wait queue is serialized by wq.lock, but the case when multiple wait queues are used should be detected accordingly.  This is detected using cmpxchg() operation.

1. get epitem from wait
2. add event to ready list
3. Wake up ( if active ) both the eventpoll wait list and the ->poll() wait list.

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



Level-triggered and edge-triggered
The epoll event distribution interface is able to behave both as edge-triggered (ET) and as level-triggered (LT).
The difference between the two mechanisms can be described as follows.  
Suppose that this scenario happens:
1. The file descriptor that represents the read side of a pipe (rfd) is registered on the epoll instance.
2. A pipe writer writes 2 kB of data on the write side of the pipe.
3. A call to epoll_wait(2) is done that will return rfd as a ready file descriptor.
4. The pipe reader reads 1 kB of data from rfd.
5. A call to epoll_wait(2) is done.

If the rfd file descriptor has been added to the epoll  interface  using  the  EPOLLET  (edge-triggered)  flag,  the  call  to
epoll_wait(2)  done  in step 5 will probably hang despite the available data still present in the file input buffer; meanwhile
the remote peer might be expecting a response based on the data it already sent. 
The reason for this is  that  edge-triggered mode  delivers events only when changes occur on the monitored file descriptor.  
So, in step 5 the caller might end up waiting for some data that is already present inside the input buffer. 
In the above example,  an  event  on  rfd  will  be  generated because  of the write done in 2 and the event is consumed in 3.
Since the read operation done in 4 does not consume the whole buffer data, the call to epoll_wait(2) done in step 5 might block indefinitely.

An application that employs the EPOLLET flag should use nonblocking file descriptors to avoid having a blocking read or  write starve  a  task  that  is  handling  multiple file descriptors. 
The suggested way to use epoll as an edge-triggered (EPOLLET) interface is as follows:

1.  with nonblocking file descriptors; and
2.  by waiting for an event only after read(2) or write(2) return EAGAIN.



By contrast, when used as a level-triggered interface (the default, when EPOLLET is not specified), epoll is simply  a  faster poll(2), and can be used wherever the latter is used since it shares the same semantics.
    
Since even with edge-triggered epoll, multiple events can be generated upon receipt of multiple chunks of data, the caller has the option to specify the EPOLLONESHOT flag, 
to tell epoll to disable the associated file descriptor after the receipt  of  an event  with  epoll_wait(2).   
When  the  EPOLLONESHOT  flag  is specified, it is the caller's responsibility to rearm the file descriptor using epoll_ctl(2) with EPOLL_CTL_MOD.

Interaction with autosleep
If the system is in autosleep mode via /sys/power/autosleep and an event happens which wakes the device from sleep, the device driver  will  keep  the  device awake only until that event is queued.  
To keep the device awake until the event has been processed, it is necessary to use the epoll_ctl(2) EPOLLWAKEUP flag.

When the EPOLLWAKEUP flag is set in the events field for a struct epoll_event, the system will be kept awake from  the  moment the  event  is queued, through the epoll_wait(2) call which returns the event until the subsequent epoll_wait(2) call. 
If the event should keep the system awake beyond that time, then a separate wake_lock should be taken before the second epoll_wait(2)
call.

/proc interfaces
The following interfaces can be used to limit the amount of kernel memory consumed by epoll:
/proc/sys/fs/epoll/max_user_watches (since Linux 2.6.28)
This  specifies  a limit on the total number of file descriptors that a user can register across all epoll instances on the system. 
The limit is per real user ID. 
Each registered file descriptor costs roughly 90 bytes on a 32-bit kernel, and roughly 160 bytes on a 64-bit kernel. 
Currently, the default value for max_user_watches is 1/25 (4%) of the available low memory, divided by the registration cost in bytes.


lt/et 模式区别的核心逻辑在 epoll_wait 的内核实现 ep_send_events_proc 函数里，就绪队列

epoll_wait 的相关工作流程：

- 当内核监控的 fd 产生用户关注的事件，内核将 fd (epi)节点信息添加进就绪队列。
- 内核发现就绪队列有数据，唤醒进程工作。
- 内核先将 fd 信息从就绪队列中删除。
- 然后将 fd 对应就绪事件信息从内核空间拷贝到用户空间。
- 事件数据拷贝完成后，内核检查事件模式是 lt 还是 et，如果不是 et，重新将 fd 信息添加回就绪队列，下次重新触发 epoll_wait。



## Example for suggested usage

While the usage of epoll when employed as a level-triggered interface does have the same semantics as poll(2), the  edge-triggered  usage  requires  more clarification to avoid stalls in the application event loop.  
In this example, listener is a non‐ blocking socket on which listen(2) has been called.  
The function do_use_fd() uses the new ready file descriptor until  EAGAIN is  returned  by  either read(2) or write(2).  
An event-driven state machine application should, after having received EAGAIN, 
record its current state so that at the next call to do_use_fd() it will continue to read(2) or write(2) from where it stopped before.

```c
#define MAX_EVENTS 10
           struct epoll_event ev, events[MAX_EVENTS];
           int listen_sock, conn_sock, nfds, epollfd;

           /* Code to set up listening socket, 'listen_sock',
              (socket(), bind(), listen()) omitted */

           epollfd = epoll_create1(0);
           if (epollfd == -1) {
               perror("epoll_create1");
               exit(EXIT_FAILURE);
           }

           ev.events = EPOLLIN;
           ev.data.fd = listen_sock;
           if (epoll_ctl(epollfd, EPOLL_CTL_ADD, listen_sock, &ev) == -1) {
               perror("epoll_ctl: listen_sock");
               exit(EXIT_FAILURE);
           }

           for (;;) {
               nfds = epoll_wait(epollfd, events, MAX_EVENTS, -1);
               if (nfds == -1) {
                   perror("epoll_wait");
                   exit(EXIT_FAILURE);
               }

               for (n = 0; n < nfds; ++n) {
                   if (events[n].data.fd == listen_sock) {
                       conn_sock = accept(listen_sock,
                                          (struct sockaddr *) &addr, &addrlen);
                       if (conn_sock == -1) {
                           perror("accept");
                           exit(EXIT_FAILURE);
                       }
                       setnonblocking(conn_sock);
                       ev.events = EPOLLIN | EPOLLET;
                       ev.data.fd = conn_sock;
                       if (epoll_ctl(epollfd, EPOLL_CTL_ADD, conn_sock,
                                   &ev) == -1) {
                           perror("epoll_ctl: conn_sock");
                           exit(EXIT_FAILURE);
                       }
                   } else {
                       do_use_fd(events[n].data.fd);
                   }
               }
           }
```

When  used as an edge-triggered interface, for performance reasons, it is possible to add the file descriptor inside the epoll interface (EPOLL_CTL_ADD) once by specifying (EPOLLIN|EPOLLOUT).  
This allows you  to  avoid  continuously  switching  between EPOLLIN and EPOLLOUT calling epoll_ctl(2) with EPOLL_CTL_MOD.

Questions and answers
Q0  What is the key used to distinguish the file descriptors registered in an epoll set?

       A0  The  key  is the combination of the file descriptor number and the open file description (also known as an "open file han‐
           dle", the kernel's internal representation of an open file).
    
       Q1  What happens if you register the same file descriptor on an epoll instance twice?
    
       A1  You will probably get EEXIST.  However, it is possible to  add  a  duplicate  (dup(2),  dup2(2),  fcntl(2)  F_DUPFD)  file
           descriptor  to  the  same  epoll  instance.   This  can  be a useful technique for filtering events, if the duplicate file
           descriptors are registered with different events masks.
    
       Q2  Can two epoll instances wait for the same file descriptor?  If so, are events reported to both epoll file descriptors?
    
       A2  Yes, and events would be reported to both.  However, careful programming may be needed to do this correctly.
    
       Q3  Is the epoll file descriptor itself poll/epoll/selectable?
    
       A3  Yes.  If an epoll file descriptor has events waiting, then it will indicate as being readable.
    
       Q4  What happens if one attempts to put an epoll file descriptor into its own file descriptor set?
    
       A4  The epoll_ctl(2) call fails (EINVAL).  However, you can add an epoll file descriptor inside another epoll file  descriptor
           set.
    
       Q5  Can I send an epoll file descriptor over a UNIX domain socket to another process?
    
       A5  Yes,  but  it does not make sense to do this, since the receiving process would not have copies of the file descriptors in
           the epoll set.
    
       Q6  Will closing a file descriptor cause it to be removed from all epoll sets automatically?
    
       A6  Yes, but be aware of the following point.  A file descriptor is a reference to an open  file  description  (see  open(2)).
           Whenever  a  file descriptor is duplicated via dup(2), dup2(2), fcntl(2) F_DUPFD, or fork(2), a new file descriptor refer‐
           ring to the same open file description is created.  An open file description continues to exist until all file descriptors
           referring  to  it  have  been  closed.  A file descriptor is removed from an epoll set only after all the file descriptors
           referring to the underlying open file description have been closed (or before if the file descriptor is explicitly removed
           using  epoll_ctl(2)  EPOLL_CTL_DEL).   This  means that even after a file descriptor that is part of an epoll set has been
           closed, events may be reported for that file descriptor if other file descriptors referring to the  same  underlying  file
           description remain open.
    
       Q7  If more than one event occurs between epoll_wait(2) calls, are they combined or reported separately?
    
       A7  They will be combined.
    
       Q8  Does an operation on a file descriptor affect the already collected but not yet reported events?
    
       A8  You  can do two operations on an existing file descriptor.  Remove would be meaningless for this case.  Modify will reread
           available I/O.

Q9  Do I need to continuously read/write a file descriptor until EAGAIN when using the EPOLLET flag (edge-triggered  behavior)
?

       A9  Receiving an event from epoll_wait(2) should suggest to you that such file descriptor is ready for the requested I/O oper‐
           ation.  You must consider it ready until the next (nonblocking) read/write yields EAGAIN.  When and how you will  use  the
           file descriptor is entirely up to you.
    
           For packet/token-oriented files (e.g., datagram socket, terminal in canonical mode), the only way to detect the end of the
           read/write I/O space is to continue to read/write until EAGAIN.
    
           For stream-oriented files (e.g., pipe, FIFO, stream socket), the condition that the read/write I/O space is exhausted  can
           also  be  detected  by checking the amount of data read from / written to the target file descriptor.  For example, if you
           call read(2) by asking to read a certain amount of data and read(2) returns a lower number of bytes, you can  be  sure  of
           having  exhausted  the read I/O space for the file descriptor.  The same is true when writing using write(2).  (Avoid this
           latter technique if you cannot guarantee that the monitored file descriptor always refers to a stream-oriented file.)

Possible pitfalls and ways to avoid them o Starvation (edge-triggered)

       If there is a large amount of I/O space, it is possible that by trying to drain it the other  files  will  not  get  processed
       causing starvation.  (This problem is not specific to epoll.)
    
       The  solution  is  to  maintain  a  ready list and mark the file descriptor as ready in its associated data structure, thereby
       allowing the application to remember which files need to be processed but still round robin amongst all the ready files.  This
       also supports ignoring subsequent events you receive for file descriptors that are already ready.
    
       o If using an event cache...
    
       If  you  use  an event cache or store all the file descriptors returned from epoll_wait(2), then make sure to provide a way to
       mark its closure dynamically (i.e.,  caused  by  a  previous  event's  processing).   Suppose  you  receive  100  events  from
       epoll_wait(2),  and in event #47 a condition causes event #13 to be closed.  If you remove the structure and close(2) the file
       descriptor for event #13, then your event cache might still say there are events waiting for that file descriptor causing con‐
       fusion.
    
       One solution for this is to call, during the processing of event 47, epoll_ctl(EPOLL_CTL_DEL) to delete file descriptor 13 and
       close(2), then mark its associated data structure as removed and link it to a cleanup list.  If you  find  another  event  for
       file  descriptor 13 in your batch processing, you will discover the file descriptor had been previously removed and there will
       be no confusion.

VERSIONS
The epoll API was introduced in Linux kernel 2.5.44.  Support was added to glibc in version 2.3.2.

CONFORMING TO
The epoll API is Linux-specific.  Some other systems provide similar mechanisms, for example, FreeBSD has kqueue, and  Solaris
has /dev/poll.

NOTES
The  set  of  file  descriptors that is being monitored via an epoll file descriptor can be viewed via the entry for the epoll
file descriptor in the process's /proc/[pid]/fdinfo directory.  See proc(5) for further details.

       The kcmp(2) KCMP_EPOLL_TFD operation can be used to test whether a file descriptor is present in an epoll instance.

SEE ALSO
epoll_create(2), epoll_create1(2), epoll_ctl(2), epoll_wait(2), poll(2), select(2)

COLOPHON
This page is part of release 4.15 of the Linux man-pages project.  A description of the project, information  about  reporting
bugs, and the latest version of this page, can be found at https://www.kernel.org/doc/man-pages/.



## Summary

1. `epoll_create` create `eventpoll`
2. `epoll_ctl` add/modify/delete socket to rbr
3. `epoll_wait` check if in ready list, or else add ep->wq and schedule
4. Woken up, recheck list



1. socket get data
2. epitem add to ready list
3. Wake up process from wq


## Links

- [IO](/docs/CS/OS/IO.md)

## References

1. [man - epoll - I/O event notification facility](https://man7.org/linux/man-pages/man7/epoll.7.html)