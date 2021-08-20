## Introduction


[man - epoll - I/O event notification facility](https://man7.org/linux/man-pages/man7/epoll.7.html)
```shell
#include <sys/epoll.h>
```

The  epoll  API  performs  a similar task to `poll`: monitoring multiple file descriptors to see if I/O is possible on any of them.  The epoll API can be used either as an edge-triggered or a level-triggered interface and scales well to  large  numbers of watched file descriptors.  The following system calls are provided to create and manage an epoll instance:

* epoll_create(2)  creates  a  new epoll instance and returns a file descriptor referring to that instance.  (The more recent
  epoll_create1(2) extends the functionality of epoll_create(2).)
* Interest in particular file descriptors is then registered via epoll_ctl(2).  The set of file descriptors currently  regis‐
  tered on an epoll instance is sometimes called an epoll set.
* epoll_wait(2) waits for I/O events, blocking the calling thread if no events are currently available.

![](https://mmbiz.qpic.cn/mmbiz_png/BBjAFF4hcwolcxS62c1ZRibFc0NUVCJ46h2GrIOb4GbapWqATZwAALWXWH8505zthGzEEyiawU3TicRQgHMj0B0eg/640?wx_fmt=png&tp=webp&wxfrom=5&wx_lazy=1&wx_co=1)

## epoll_create

create struct eventpoll

```c
SYSCALL_DEFINE1(epoll_create1, int, flags)
{
	return do_epoll_create(flags);
}

/*
 * Open an eventpoll file descriptor.
 */
static int do_epoll_create(int flags)
{
	int error, fd;
	struct eventpoll *ep = NULL;
	struct file *file;

	/* Check the EPOLL_* constant for consistency.  */
	BUILD_BUG_ON(EPOLL_CLOEXEC != O_CLOEXEC);

	if (flags & ~EPOLL_CLOEXEC)
		return -EINVAL;
	/*
	 * Create the internal data structure ("struct eventpoll").
	 */
	error = ep_alloc(&ep);
	if (error < 0)
		return error;
	/*
	 * Creates all the items needed to setup an eventpoll file. That is,
	 * a file structure and a free file descriptor.
	 */
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

out_free_fd:
	put_unused_fd(fd);
out_free_ep:
	ep_free(ep);
	return error;
}
```

### eventpoll

rdlist : storage ready file descriptors
rbr root of rb

*ovflist : This is a single linked list that chains all the "struct epitem" that happened while transferring ready events to userspace w/out holding ->lock.


```c
/*
 * This structure is stored inside the "private_data" member of the file
 * structure and represents the main data structure for the eventpoll
 * interface.
 */
struct eventpoll {
	/*
	 * This mutex is used to ensure that files are not removed
	 * while epoll is using them. This is held during the event
	 * collection loop, the file cleanup path, the epoll file exit
	 * code and the ctl operations.
	 */
	struct mutex mtx;

	/* Wait queue used by sys_epoll_wait() */
	wait_queue_head_t wq;

	/* Wait queue used by file->poll() */
	wait_queue_head_t poll_wait;

	/* List of ready file descriptors */
	struct list_head rdllist;

	/* Lock which protects rdllist and ovflist */
	rwlock_t lock;

	/* RB tree root used to store monitored fd structs */
	struct rb_root_cached rbr;

	/*
	 * This is a single linked list that chains all the "struct epitem" that
	 * happened while transferring ready events to userspace w/out
	 * holding ->lock.
	 */
	struct epitem *ovflist;

	/* wakeup_source used when ep_scan_ready_list is running */
	struct wakeup_source *ws;

	/* The user that created the eventpoll descriptor */
	struct user_struct *user;

	struct file *file;

	/* used to optimize loop detection check */
	u64 gen;
	struct hlist_head refs;

#ifdef CONFIG_NET_RX_BUSY_POLL
	/* used to track busy poll napi_id */
	unsigned int napi_id;
#endif

#ifdef CONFIG_DEBUG_LOCK_ALLOC
	/* tracks wakeup nests for lockdep validation */
	u8 nests;
#endif
};
```

### epitem

```c

/*
 * Each file descriptor added to the eventpoll interface will
 * have an entry of this type linked to the "rbr" RB tree.
 * Avoid increasing the size of this struct, there can be many thousands
 * of these on a server and we do not want this to take another cache line.
 */
struct epitem {
	union {
		/* RB tree node links this structure to the eventpoll RB tree */
		struct rb_node rbn;
		/* Used to free the struct epitem */
		struct rcu_head rcu;
	};

	/* List header used to link this structure to the eventpoll ready list */
	struct list_head rdllink;

	/*
	 * Works together "struct eventpoll"->ovflist in keeping the
	 * single linked chain of items.
	 */
	struct epitem *next;

	/* The file descriptor information this item refers to */
	struct epoll_filefd ffd;

	/* List containing poll wait queues */
	struct eppoll_entry *pwqlist;

	/* The "container" of this item */
	struct eventpoll *ep;

	/* List header used to link this item to the "struct file" items list */
	struct hlist_node fllink;

	/* wakeup_source used when EPOLLWAKEUP is set */
	struct wakeup_source __rcu *ws;

	/* The structure that describe the interested events and the source fd */
	struct epoll_event event;
};
```

### ep_alloc
```c
//linux/fs/eventpoll.c
static int ep_alloc(struct eventpoll **pep)
{
	int error;
	struct user_struct *user;
	struct eventpoll *ep;

	user = get_current_user();
	error = -ENOMEM;
	ep = kzalloc(sizeof(*ep), GFP_KERNEL);
	if (unlikely(!ep))
		goto free_uid;

	mutex_init(&ep->mtx);
	rwlock_init(&ep->lock);
	init_waitqueue_head(&ep->wq);
	init_waitqueue_head(&ep->poll_wait);
	INIT_LIST_HEAD(&ep->rdllist);
	ep->rbr = RB_ROOT_CACHED;
	ep->ovflist = EP_UNACTIVE_PTR;
	ep->user = user;

	*pep = ep;

	return 0;

free_uid:
	free_uid(user);
	return error;
}
```

## epoll_ctl
```c
//linux/fs/eventpoll.c
/*
 * The following function implements the controller interface for
 * the eventpoll file that enables the insertion/removal/change of
 * file descriptors inside the interest set.
 */
SYSCALL_DEFINE4(epoll_ctl, int, epfd, int, op, int, fd,
		struct epoll_event __user *, event)
{
	struct epoll_event epds;

	if (ep_op_has_event(op) &&
	    copy_from_user(&epds, event, sizeof(struct epoll_event)))
		return -EFAULT;

	return do_epoll_ctl(epfd, op, fd, &epds, false);
}

int do_epoll_ctl(int epfd, int op, int fd, struct epoll_event *epds,
               bool nonblock)
{
       int error;
       int full_check = 0;
       struct fd f, tf;
       struct eventpoll *ep;
       struct epitem *epi;
       struct eventpoll *tep = NULL;

       error = -EBADF;
       f = fdget(epfd);
       if (!f.file)
              goto error_return;

       /* Get the "struct file *" for the target file */
       tf = fdget(fd);
       if (!tf.file)
              goto error_fput;

       /* The target file descriptor must support poll */
       error = -EPERM;
       if (!file_can_poll(tf.file))
              goto error_tgt_fput;

       /* Check if EPOLLWAKEUP is allowed */
       if (ep_op_has_event(op))
              ep_take_care_of_epollwakeup(epds);

       /*
        * We have to check that the file structure underneath the file descriptor
        * the user passed to us _is_ an eventpoll file. And also we do not permit
        * adding an epoll file descriptor inside itself.
        */
       error = -EINVAL;
       if (f.file == tf.file || !is_file_epoll(f.file))
              goto error_tgt_fput;

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
        * When we insert an epoll file descriptor inside another epoll file
        * descriptor, there is the chance of creating closed loops, which are
        * better be handled here, than in more critical paths. While we are
        * checking for loops we also determine the list of files reachable
        * and hang them on the tfile_check_list, so we can check that we
        * haven't created too many possible wakeup paths.
        *
        * We do not need to take the global 'epumutex' on EPOLL_CTL_ADD when
        * the epoll file descriptor is attaching directly to a wakeup source,
        * unless the epoll file descriptor is nested. The purpose of taking the
        * 'epmutex' on add is to prevent complex toplogies such as loops and
        * deep wakeup paths from forming in parallel through multiple
        * EPOLL_CTL_ADD operations.
        */
       error = epoll_mutex_lock(&ep->mtx, 0, nonblock);
       if (error)
              goto error_tgt_fput;
       if (op == EPOLL_CTL_ADD) {
              if (READ_ONCE(f.file->f_ep) || ep->gen == loop_check_gen ||
                  is_file_epoll(tf.file)) {
                     mutex_unlock(&ep->mtx);
                     error = epoll_mutex_lock(&epmutex, 0, nonblock);
                     if (error)
                            goto error_tgt_fput;
                     loop_check_gen++;
                     full_check = 1;
                     if (is_file_epoll(tf.file)) {
                            tep = tf.file->private_data;
                            error = -ELOOP;
                            if (ep_loop_check(ep, tep) != 0)
                                   goto error_tgt_fput;
                     }
                     error = epoll_mutex_lock(&ep->mtx, 0, nonblock);
                     if (error)
                            goto error_tgt_fput;
              }
       }

       /*
        * Try to lookup the file inside our RB tree. Since we grabbed "mtx"
        * above, we can be sure to be able to use the item looked up by
        * ep_find() till we release the mutex.
        */
       epi = ep_find(ep, tf.file, fd);

       error = -EINVAL;
       switch (op) {
       case EPOLL_CTL_ADD:
              if (!epi) {
                     epds->events |= EPOLLERR | EPOLLHUP;
                     error = ep_insert(ep, epds, tf.file, fd, full_check);
              } else
                     error = -EEXIST;
              break;
       case EPOLL_CTL_DEL:
              if (epi)
                     error = ep_remove(ep, epi);
              else
                     error = -ENOENT;
              break;
       case EPOLL_CTL_MOD:
              if (epi) {
                     if (!(epi->event.events & EPOLLEXCLUSIVE)) {
                            epds->events |= EPOLLERR | EPOLLHUP;
                            error = ep_modify(ep, epi, epds);
                     }
              } else
                     error = -ENOENT;
              break;
       }
       mutex_unlock(&ep->mtx);

error_tgt_fput:
       if (full_check) {
              clear_tfile_check_list();
              loop_check_gen++;
              mutex_unlock(&epmutex);
       }

       fdput(tf);
error_fput:
       fdput(f);
error_return:

       return error;
}
```

### ep_insert

insert into rb
```c
/*
 * Must be called with "mtx" held.
 */
static int ep_insert(struct eventpoll *ep, const struct epoll_event *event,
		     struct file *tfile, int fd, int full_check)
{
	int error, pwake = 0;
	__poll_t revents;
	long user_watches;
	struct epitem *epi;
	struct ep_pqueue epq;
	struct eventpoll *tep = NULL;

	if (is_file_epoll(tfile))
		tep = tfile->private_data;

	lockdep_assert_irqs_enabled();

	user_watches = atomic_long_read(&ep->user->epoll_watches);
	if (unlikely(user_watches >= max_user_watches))
		return -ENOSPC;
	if (!(epi = kmem_cache_zalloc(epi_cache, GFP_KERNEL)))
		return -ENOMEM;

	/* Item initialization follow here ... */
	INIT_LIST_HEAD(&epi->rdllink);
	epi->ep = ep;
	ep_set_ffd(&epi->ffd, tfile, fd);
	epi->event = *event;
	epi->next = EP_UNACTIVE_PTR;

	if (tep)
		mutex_lock_nested(&tep->mtx, 1);
	/* Add the current item to the list of active epoll hook for this file */
	if (unlikely(attach_epitem(tfile, epi) < 0)) {
		kmem_cache_free(epi_cache, epi);
		if (tep)
			mutex_unlock(&tep->mtx);
		return -ENOMEM;
	}

	if (full_check && !tep)
		list_file(tfile);

	atomic_long_inc(&ep->user->epoll_watches);

	/*
	 * Add the current item to the RB tree. All RB tree operations are
	 * protected by "mtx", and ep_insert() is called with "mtx" held.
	 */
	ep_rbtree_insert(ep, epi);
	if (tep)
		mutex_unlock(&tep->mtx);

	/* now check if we've created too many backpaths */
	if (unlikely(full_check && reverse_path_check())) {
		ep_remove(ep, epi);
		return -EINVAL;
	}

	if (epi->event.events & EPOLLWAKEUP) {
		error = ep_create_wakeup_source(epi);
		if (error) {
			ep_remove(ep, epi);
			return error;
		}
	}

	/* Initialize the poll table using the queue callback */
	epq.epi = epi;
	init_poll_funcptr(&epq.pt, ep_ptable_queue_proc);

	/*
	 * Attach the item to the poll hooks and get current event bits.
	 * We can safely use the file* here because its usage count has
	 * been increased by the caller of this function. Note that after
	 * this operation completes, the poll callback can start hitting
	 * the new item.
	 */
	revents = ep_item_poll(epi, &epq.pt, 1);

	/*
	 * We have to check if something went wrong during the poll wait queue
	 * install process. Namely an allocation for a wait queue failed due
	 * high memory pressure.
	 */
	if (unlikely(!epq.epi)) {
		ep_remove(ep, epi);
		return -ENOMEM;
	}

	/* We have to drop the new item inside our item list to keep track of it */
	write_lock_irq(&ep->lock);

	/* record NAPI ID of new item if present */
	ep_set_busy_poll_napi_id(epi);

	/* If the file is already "ready" we drop it inside the ready list */
	if (revents && !ep_is_linked(epi)) {
		list_add_tail(&epi->rdllink, &ep->rdllist);
		ep_pm_stay_awake(epi);

		/* Notify waiting tasks that events are available */
		if (waitqueue_active(&ep->wq))
			wake_up(&ep->wq);
		if (waitqueue_active(&ep->poll_wait))
			pwake++;
	}

	write_unlock_irq(&ep->lock);

	/* We have to call this outside the lock */
	if (pwake)
		ep_poll_safewake(ep, NULL);

	return 0;
}
```

## epoll_wait



```c
// /linux/fs/eventpoll.c
SYSCALL_DEFINE4(epoll_wait, int, epfd, struct epoll_event __user *, events,
              int, maxevents, int, timeout)
{
       struct timespec64 to;

       return do_epoll_wait(epfd, events, maxevents,
                          ep_timeout_to_timespec(&to, timeout));
}

/*
 * Implement the event wait interface for the eventpoll file. It is the kernel
 * part of the user space epoll_wait(2).
 */
static int do_epoll_wait(int epfd, struct epoll_event __user *events,
                      int maxevents, struct timespec64 *to)
{
       int error;
       struct fd f;
       struct eventpoll *ep;

       /* The maximum number of event must be greater than zero */
       if (maxevents <= 0 || maxevents > EP_MAX_EVENTS)
              return -EINVAL;

       /* Verify that the area passed by the user is writeable */
       if (!access_ok(events, maxevents * sizeof(struct epoll_event)))
              return -EFAULT;

       /* Get the "struct file *" for the eventpoll file */
       f = fdget(epfd);
       if (!f.file)
              return -EBADF;

       /*
        * We have to check that the file structure underneath the fd
        * the user passed to us _is_ an eventpoll file.
        */
       error = -EINVAL;
       if (!is_file_epoll(f.file))
              goto error_fput;

       /*
        * At this point it is safe to assume that the "private_data" contains
        * our own data structure.
        */
       ep = f.file->private_data;

       /* Time to fish for events ... */
       error = ep_poll(ep, events, maxevents, to);

error_fput:
       fdput(f);
       return error;
}
```

### ep_poll

```c
/**
 * ep_poll - Retrieves ready events, and delivers them to the caller-supplied
 *           event buffer.
 *
 * @ep: Pointer to the eventpoll context.
 * @events: Pointer to the userspace buffer where the ready events should be
 *          stored.
 * @maxevents: Size (in terms of number of events) of the caller event buffer.
 * @timeout: Maximum timeout for the ready events fetch operation, in
 *           timespec. If the timeout is zero, the function will not block,
 *           while if the @timeout ptr is NULL, the function will block
 *           until at least one event has been retrieved (or an error
 *           occurred).
 *
 * Return: the number of ready events which have been fetched, or an
 *          error code, in case of error.
 */
static int ep_poll(struct eventpoll *ep, struct epoll_event __user *events,
                 int maxevents, struct timespec64 *timeout)
{
       int res, eavail, timed_out = 0;
       u64 slack = 0;
       wait_queue_entry_t wait;
       ktime_t expires, *to = NULL;

       lockdep_assert_irqs_enabled();

       if (timeout && (timeout->tv_sec | timeout->tv_nsec)) {
              slack = select_estimate_accuracy(timeout);
              to = &expires;
              *to = timespec64_to_ktime(*timeout);
       } else if (timeout) {
              /*
               * Avoid the unnecessary trip to the wait queue loop, if the
               * caller specified a non blocking operation.
               */
              timed_out = 1;
       }

       /*
        * This call is racy: We may or may not see events that are being added
        * to the ready list under the lock (e.g., in IRQ callbacks). For cases
        * with a non-zero timeout, this thread will check the ready list under
        * lock and will add to the wait queue.  For cases with a zero
        * timeout, the user by definition should not care and will have to
        * recheck again.
        */
       eavail = ep_events_available(ep);

       while (1) {
              if (eavail) {
                     /*
                      * Try to transfer events to user space. In case we get
                      * 0 events and there's still timeout left over, we go
                      * trying again in search of more luck.
                      */
                     res = ep_send_events(ep, events, maxevents);
                     if (res)
                            return res;
              }

              if (timed_out)
                     return 0;

              eavail = ep_busy_loop(ep, timed_out);
              if (eavail)
                     continue;

              if (signal_pending(current))
                     return -EINTR;

              /*
               * Internally init_wait() uses autoremove_wake_function(),
               * thus wait entry is removed from the wait queue on each
               * wakeup. Why it is important? In case of several waiters
               * each new wakeup will hit the next waiter, giving it the
               * chance to harvest new event. Otherwise wakeup can be
               * lost. This is also good performance-wise, because on
               * normal wakeup path no need to call __remove_wait_queue()
               * explicitly, thus ep->lock is not taken, which halts the
               * event delivery.
               */
              init_wait(&wait);

              write_lock_irq(&ep->lock);
              /*
               * Barrierless variant, waitqueue_active() is called under
               * the same lock on wakeup ep_poll_callback() side, so it
               * is safe to avoid an explicit barrier.
               */
              __set_current_state(TASK_INTERRUPTIBLE);

              /*
               * Do the final check under the lock. ep_scan_ready_list()
               * plays with two lists (->rdllist and ->ovflist) and there
               * is always a race when both lists are empty for short
               * period of time although events are pending, so lock is
               * important.
               */
              eavail = ep_events_available(ep);
              if (!eavail)
                     __add_wait_queue_exclusive(&ep->wq, &wait);

              write_unlock_irq(&ep->lock);

              if (!eavail)
                     timed_out = !schedule_hrtimeout_range(to, slack,
                                                       HRTIMER_MODE_ABS);
              __set_current_state(TASK_RUNNING);

              /*
               * We were woken up, thus go and try to harvest some events.
               * If timed out and still on the wait queue, recheck eavail
               * carefully under lock, below.
               */
              eavail = 1;

              if (!list_empty_careful(&wait.entry)) {
                     write_lock_irq(&ep->lock);
                     /*
                      * If the thread timed out and is not on the wait queue,
                      * it means that the thread was woken up after its
                      * timeout expired before it could reacquire the lock.
                      * Thus, when wait.entry is empty, it needs to harvest
                      * events.
                      */
                     if (timed_out)
                            eavail = list_empty(&wait.entry);
                     __remove_wait_queue(&ep->wq, &wait);
                     write_unlock_irq(&ep->lock);
              }
       }
}
```



ep_poll_callback

tcp 内存使用slab分配

dmidecode 查看CPU 内存信息
每个CPU和它直接相连的内存条组成Node

numactl --hardware
查看Node情况
Node划分为Zone

```shell
cat /proc/zoneinfo #查看zone信息
```

Zone包含Page 一般为4KB


```shell
cat /proc/slabinfo
slabtop
```
slab_def.h

mm/slab.h

空establish 连接占用3.3KB左右

Level-triggered and edge-triggered
The epoll event distribution interface is able to behave both as edge-triggered (ET) and as level-triggered (LT).  The differ‐
ence between the two mechanisms can be described as follows.  Suppose that this scenario happens:

```shell
   1. The file descriptor that represents the read side of a pipe (rfd) is registered on the epoll instance.

   2. A pipe writer writes 2 kB of data on the write side of the pipe.

   3. A call to epoll_wait(2) is done that will return rfd as a ready file descriptor.

   4. The pipe reader reads 1 kB of data from rfd.

   5. A call to epoll_wait(2) is done.
```


If the rfd file descriptor has been added to the epoll  interface  using  the  EPOLLET  (edge-triggered)  flag,  the  call  to
epoll_wait(2)  done  in step 5 will probably hang despite the available data still present in the file input buffer; meanwhile
the remote peer might be expecting a response based on the data it already sent.  The reason for this is  that  edge-triggered
mode  delivers events only when changes occur on the monitored file descriptor.  So, in step 5 the caller might end up waiting
for some data that is already present inside the input buffer.  In the above example,  an  event  on  rfd  will  be  generated
because  of the write done in 2 and the event is consumed in 3.  Since the read operation done in 4 does not consume the whole
buffer data, the call to epoll_wait(2) done in step 5 might block indefinitely.

An application that employs the EPOLLET flag should use nonblocking file descriptors to avoid having a blocking read or  write
starve  a  task  that  is  handling  multiple file descriptors.  The suggested way to use epoll as an edge-triggered (EPOLLET)
interface is as follows:

              i   with nonblocking file descriptors; and
    
              ii  by waiting for an event only after read(2) or write(2) return EAGAIN.





       By contrast, when used as a level-triggered interface (the default, when EPOLLET is not specified), epoll is simply  a  faster
       poll(2), and can be used wherever the latter is used since it shares the same semantics.
    
       Since even with edge-triggered epoll, multiple events can be generated upon receipt of multiple chunks of data, the caller has
       the option to specify the EPOLLONESHOT flag, to tell epoll to disable the associated file descriptor after the receipt  of  an
       event  with  epoll_wait(2).   When  the  EPOLLONESHOT  flag  is specified, it is the caller's responsibility to rearm the file
       descriptor using epoll_ctl(2) with EPOLL_CTL_MOD.


Interaction with autosleep
If the system is in autosleep mode via /sys/power/autosleep and an event happens which wakes the device from sleep, the device
driver  will  keep  the  device awake only until that event is queued.  To keep the device awake until the event has been pro‐
cessed, it is necessary to use the epoll_ctl(2) EPOLLWAKEUP flag.

When the EPOLLWAKEUP flag is set in the events field for a struct epoll_event, the system will be kept awake from  the  moment
the  event  is queued, through the epoll_wait(2) call which returns the event until the subsequent epoll_wait(2) call.  If the
event should keep the system awake beyond that time, then a separate wake_lock should be taken before the second epoll_wait(2)
call.

/proc interfaces
The following interfaces can be used to limit the amount of kernel memory consumed by epoll:

       /proc/sys/fs/epoll/max_user_watches (since Linux 2.6.28)
              This  specifies  a limit on the total number of file descriptors that a user can register across all epoll instances on
              the system.  The limit is per real user ID.  Each registered file descriptor costs roughly 90 bytes on a 32-bit kernel,
              and roughly 160 bytes on a 64-bit kernel.  Currently, the default value for max_user_watches is 1/25 (4%) of the avail‐
              able low memory, divided by the registration cost in bytes.


## ET & LT

Edge Triggered

Level Triggered



## Example for suggested usage
While the usage of epoll when employed as a level-triggered interface does have the same semantics as poll(2), the  edge-trig‐
gered  usage  requires  more clarification to avoid stalls in the application event loop.  In this example, listener is a non‐
blocking socket on which listen(2) has been called.  The function do_use_fd() uses the new ready file descriptor until  EAGAIN
is  returned  by  either read(2) or write(2).  An event-driven state machine application should, after having received EAGAIN,
record its current state so that at the next call to do_use_fd() it will continue to read(2) or write(2) from where it stopped
before.

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

When  used as an edge-triggered interface, for performance reasons, it is possible to add the file descriptor inside the epoll
interface (EPOLL_CTL_ADD) once by specifying (EPOLLIN|EPOLLOUT).  This allows you  to  avoid  continuously  switching  between
EPOLLIN and EPOLLOUT calling epoll_ctl(2) with EPOLL_CTL_MOD.

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

