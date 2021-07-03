# IO




## epoll

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

### epoll_create

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
ep_alloc
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

### epoll_ctl
```
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
```

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

### epoll_wait


// in fs/eventpoll.c

invoke ep_poll


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

       1. The file descriptor that represents the read side of a pipe (rfd) is registered on the epoll instance.
    
       2. A pipe writer writes 2 kB of data on the write side of the pipe.
    
       3. A call to epoll_wait(2) is done that will return rfd as a ready file descriptor.
    
       4. The pipe reader reads 1 kB of data from rfd.
    
       5. A call to epoll_wait(2) is done.


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



### Example for suggested usage
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

Possible pitfalls and ways to avoid them
o Starvation (edge-triggered)

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

### accept

```c
//linux/net/socket.c
/*
 *	Socket files have a set of 'special' operations as well as the generic file ones. These don't appear
 *	in the operation structures but are done directly via the socketcall() multiplexor.
 */
static const struct file_operations socket_file_ops = {
	.owner =	THIS_MODULE,
	.llseek =	no_llseek,
	.read_iter =	sock_read_iter,
	.write_iter =	sock_write_iter,
	.poll =		sock_poll,
	.unlocked_ioctl = sock_ioctl,
#ifdef CONFIG_COMPAT
	.compat_ioctl = compat_sock_ioctl,
#endif
	.mmap =		sock_mmap,
	.release =	sock_close,
	.fasync =	sock_fasync,
	.sendpage =	sock_sendpage,
	.splice_write = generic_splice_sendpage,
	.splice_read =	sock_splice_read,
	.show_fdinfo =	sock_show_fdinfo,
};
```

```c
//linux/include/linux/net.h
/**
 *  struct socket - general BSD socket
 *  @state: socket state (%SS_CONNECTED, etc)
 *  @type: socket type (%SOCK_STREAM, etc)
 *  @flags: socket flags (%SOCK_NOSPACE, etc)
 *  @ops: protocol specific socket operations
 *  @file: File back pointer for gc
 *  @sk: internal networking protocol agnostic socket representation
 *  @wq: wait queue for several uses
 */
struct socket {
	socket_state		state;

	short			type;

	unsigned long		flags;

	struct file		*file;
	struct sock		*sk;
	const struct proto_ops	*ops;

	struct socket_wq	wq;
};
```

todo sock linux/include/net/sock.h


set sk_data_ready = sock_def_readable
```c
//linux/net/core/sock.c
void sock_init_data(struct socket *sock, struct sock *sk)
{
	sk_init_common(sk);
	sk->sk_send_head	=	NULL;

	timer_setup(&sk->sk_timer, NULL, 0);

	sk->sk_allocation	=	GFP_KERNEL;
	sk->sk_rcvbuf		=	sysctl_rmem_default;
	sk->sk_sndbuf		=	sysctl_wmem_default;
	sk->sk_state		=	TCP_CLOSE;
	sk_set_socket(sk, sock);

	sock_set_flag(sk, SOCK_ZAPPED);

	if (sock) {
		sk->sk_type	=	sock->type;
		RCU_INIT_POINTER(sk->sk_wq, &sock->wq);
		sock->sk	=	sk;
		sk->sk_uid	=	SOCK_INODE(sock)->i_uid;
	} else {
		RCU_INIT_POINTER(sk->sk_wq, NULL);
		sk->sk_uid	=	make_kuid(sock_net(sk)->user_ns, 0);
	}

	rwlock_init(&sk->sk_callback_lock);
	if (sk->sk_kern_sock)
		lockdep_set_class_and_name(
			&sk->sk_callback_lock,
			af_kern_callback_keys + sk->sk_family,
			af_family_kern_clock_key_strings[sk->sk_family]);
	else
		lockdep_set_class_and_name(
			&sk->sk_callback_lock,
			af_callback_keys + sk->sk_family,
			af_family_clock_key_strings[sk->sk_family]);

	sk->sk_state_change	=	sock_def_wakeup;
	sk->sk_data_ready	=	sock_def_readable;
	sk->sk_write_space	=	sock_def_write_space;
	sk->sk_error_report	=	sock_def_error_report;
	sk->sk_destruct		=	sock_def_destruct;

	sk->sk_frag.page	=	NULL;
	sk->sk_frag.offset	=	0;
	sk->sk_peek_off		=	-1;

	sk->sk_peer_pid 	=	NULL;
	sk->sk_peer_cred	=	NULL;
	sk->sk_write_pending	=	0;
	sk->sk_rcvlowat		=	1;
	sk->sk_rcvtimeo		=	MAX_SCHEDULE_TIMEOUT;
	sk->sk_sndtimeo		=	MAX_SCHEDULE_TIMEOUT;

	sk->sk_stamp = SK_DEFAULT_STAMP;
#if BITS_PER_LONG==32
	seqlock_init(&sk->sk_stamp_seq);
#endif
	atomic_set(&sk->sk_zckey, 0);

#ifdef CONFIG_NET_RX_BUSY_POLL
	sk->sk_napi_id		=	0;
	sk->sk_ll_usec		=	sysctl_net_busy_read;
#endif

	sk->sk_max_pacing_rate = ~0UL;
	sk->sk_pacing_rate = ~0UL;
	WRITE_ONCE(sk->sk_pacing_shift, 10);
	sk->sk_incoming_cpu = -1;

	sk_rx_queue_clear(sk);
	/*
	 * Before updating sk_refcnt, we must commit prior changes to memory
	 * (Documentation/RCU/rculist_nulls.rst for details)
	 */
	smp_wmb();
	refcount_set(&sk->sk_refcnt, 1);
	atomic_set(&sk->sk_drops, 0);
}
```

fd_install to fdlist of process

127.0.0.1 本机网络IO不需要经过网卡， 不经过Ring Buffer 直接把skb传送给协议接收栈， 可以通过BPF绕过内核协议栈，减少开销（Istio的sidecar代理与本地进程通信）

## mmap

## sendfile

## Reference

1. [打破砂锅挖到底—— Epoll 多路复用是如何转起来的？](https://mp.weixin.qq.com/s/Py2TE9CdQ92fGLpg-SEj_g)