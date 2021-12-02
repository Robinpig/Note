
## bind
Bind a name to a socket. Nothing much to do here since it's
the protocol's responsibility to handle the local address.

We move the socket address to kernel space before we call
the protocol layer (having also checked the address is ok).

1. move_addr_to_kernel
2. inet_bind
```c

SYSCALL_DEFINE3(bind, int, fd, struct sockaddr __user *, umyaddr, int, addrlen)
{
	return __sys_bind(fd, umyaddr, addrlen);
}

int __sys_bind(int fd, struct sockaddr __user *umyaddr, int addrlen)
{
	struct socket *sock;
	struct sockaddr_storage address;
	int err, fput_needed;

	sock = sockfd_lookup_light(fd, &err, &fput_needed);
	if (sock) {
		err = move_addr_to_kernel(umyaddr, addrlen, &address);
		if (!err) {
			err = security_socket_bind(sock,
						   (struct sockaddr *)&address,
						   addrlen);
			if (!err)
				err = sock->ops->bind(sock,
						      (struct sockaddr *)
						      &address, addrlen);
		}
		fput_light(sock->file, fput_needed);
	}
	return err;
}

```
### move addr

Support routines.
Move socket addresses back and forth across the kernel/user
divide and look after the messy bits.


move_addr_to_kernel	-	copy a socket address into kernel space
- uaddr: Address in user space
- kaddr: Address in kernel space
- ulen: Length in user space

The address is copied into kernel space. If the provided address is
too long an error code of -EINVAL is returned. If the copy gives
invalid addresses -EFAULT is returned. On a success 0 is returned.
```c

int move_addr_to_kernel(void __user *uaddr, int ulen, struct sockaddr_storage *kaddr)
{
	if (ulen < 0 || ulen > sizeof(struct sockaddr_storage))
		return -EINVAL;
	if (ulen == 0)
		return 0;
	if (copy_from_user(kaddr, uaddr, ulen))
		return -EFAULT;
	return audit_sockaddr(ulen, kaddr);
}
```
move_addr_to_user	-	copy an address to user space
- kaddr: kernel space address
- klen: length of address in kernel
- uaddr: user space address
- ulen: pointer to user length field

The value pointed to by ulen on entry is the buffer length available.
This is overwritten with the buffer space used. -EINVAL is returned if an overlong buffer is specified or a negative buffer size. -EFAULT is returned if either the buffer or the length field are not accessible.

After copying the data up to the limit the user specifies, the true length of the data is written over the length limit the user specified. Zero is returned for a success.

```c
//
static int move_addr_to_user(struct sockaddr_storage *kaddr, int klen,
			     void __user *uaddr, int __user *ulen)
{
	int err;
	int len;

	BUG_ON(klen > sizeof(struct sockaddr_storage));
	err = get_user(len, ulen);
	if (err)
		return err;
	if (len > klen)
		len = klen;
	if (len < 0)
		return -EINVAL;
	if (len) {
		if (audit_sockaddr(klen, kaddr))
			return -ENOMEM;
		if (copy_to_user(uaddr, kaddr, len))
			return -EFAULT;
	}
	/*
	 *      "fromlen shall refer to the value before truncation.."
	 *                      1003.1g
	 */
	return __put_user(klen, ulen);
}
```

### inet_bind

```c

```c
const struct proto_ops inet_stream_ops = {
	.family		   = PF_INET,
	.bind		   = inet_bind
	...
}
```


```c
// net/ipv4/af_inet.c
int inet_bind(struct socket *sock, struct sockaddr *uaddr, int addr_len)
{
	struct sock *sk = sock->sk;
	u32 flags = BIND_WITH_LOCK;
	int err;

	/* If the socket has its own bind function then use it. (RAW) */
	if (sk->sk_prot->bind) {
		return sk->sk_prot->bind(sk, uaddr, addr_len);
	}
	if (addr_len < sizeof(struct sockaddr_in))
		return -EINVAL;

	/* BPF prog is run before any checks are done so that if the prog
	 * changes context in a wrong way it will be caught.
	 */
	err = BPF_CGROUP_RUN_PROG_INET_BIND_LOCK(sk, uaddr,
						 BPF_CGROUP_INET4_BIND, &flags);
	if (err)
		return err;

	return __inet_bind(sk, uaddr, addr_len, flags);
}
```


```c

int __inet_bind(struct sock *sk, struct sockaddr *uaddr, int addr_len,
		u32 flags)
{
	struct sockaddr_in *addr = (struct sockaddr_in *)uaddr;
	struct inet_sock *inet = inet_sk(sk);
	struct net *net = sock_net(sk);
	unsigned short snum;
	int chk_addr_ret;
	u32 tb_id = RT_TABLE_LOCAL;
	int err;

	if (addr->sin_family != AF_INET) {
		/* Compatibility games : accept AF_UNSPEC (mapped to AF_INET)
		 * only if s_addr is INADDR_ANY.
		 */
		err = -EAFNOSUPPORT;
		if (addr->sin_family != AF_UNSPEC ||
		    addr->sin_addr.s_addr != htonl(INADDR_ANY))
			goto out;
	}

	tb_id = l3mdev_fib_table_by_index(net, sk->sk_bound_dev_if) ? : tb_id;
	chk_addr_ret = inet_addr_type_table(net, addr->sin_addr.s_addr, tb_id);

	/* Not specified by any standard per-se, however it breaks too
	 * many applications when removed.  It is unfortunate since
	 * allowing applications to make a non-local bind solves
	 * several problems with systems using dynamic addressing.
	 * (ie. your servers still start up even if your ISDN link
	 *  is temporarily down)
	 */
	err = -EADDRNOTAVAIL;
	if (!inet_can_nonlocal_bind(net, inet) &&
	    addr->sin_addr.s_addr != htonl(INADDR_ANY) &&
	    chk_addr_ret != RTN_LOCAL &&
	    chk_addr_ret != RTN_MULTICAST &&
	    chk_addr_ret != RTN_BROADCAST)
		goto out;

	snum = ntohs(addr->sin_port);
	err = -EACCES;
	if (!(flags & BIND_NO_CAP_NET_BIND_SERVICE) &&
	    snum && inet_port_requires_bind_service(net, snum) &&
	    !ns_capable(net->user_ns, CAP_NET_BIND_SERVICE))
		goto out;

	/*      We keep a pair of addresses. rcv_saddr is the one
	 *      used by hash lookups, and saddr is used for transmit.
	 *
	 *      In the BSD API these are the same except where it
	 *      would be illegal to use them (multicast/broadcast) in
	 *      which case the sending device address is used.
	 */
	if (flags & BIND_WITH_LOCK)
		lock_sock(sk);

	/* Check these errors (active socket, double bind). */
	err = -EINVAL;
	if (sk->sk_state != TCP_CLOSE || inet->inet_num)
		goto out_release_sock;

	inet->inet_rcv_saddr = inet->inet_saddr = addr->sin_addr.s_addr;
	if (chk_addr_ret == RTN_MULTICAST || chk_addr_ret == RTN_BROADCAST)
		inet->inet_saddr = 0;  /* Use device */

	/* Make sure we are allowed to bind here. */
	if (snum || !(inet->bind_address_no_port ||
		      (flags & BIND_FORCE_ADDRESS_NO_PORT))) {
		if (sk->sk_prot->get_port(sk, snum)) {
			inet->inet_saddr = inet->inet_rcv_saddr = 0;
			err = -EADDRINUSE;
			goto out_release_sock;
		}
		if (!(flags & BIND_FROM_BPF)) {
			err = BPF_CGROUP_RUN_PROG_INET4_POST_BIND(sk);
			if (err) {
				inet->inet_saddr = inet->inet_rcv_saddr = 0;
				goto out_release_sock;
			}
		}
	}

	if (inet->inet_rcv_saddr)
		sk->sk_userlocks |= SOCK_BINDADDR_LOCK;
	if (snum)
		sk->sk_userlocks |= SOCK_BINDPORT_LOCK;
	inet->inet_sport = htons(inet->inet_num);
	inet->inet_daddr = 0;
	inet->inet_dport = 0;
	sk_dst_reset(sk);
	err = 0;
out_release_sock:
	if (flags & BIND_WITH_LOCK)
		release_sock(sk);
out:
	return err;
}
```



## Listen

**listen for socket connections and limit the queue of incoming connections** -- see [listen(3) - Linux man page](https://linux.die.net/man/3/listen)

Perform a listen. Basically, we allow the protocol to do anything
necessary for a listen, and if that works, we mark the socket as
ready for listening.



`Max_ack_backlog = Min(backlog,net.core.somaxconn)`



```c
// socket.c
SYSCALL_DEFINE2(listen, int, fd, int, backlog)
{
       return __sys_listen(fd, backlog);
}


int __sys_listen(int fd, int backlog)
{
       struct socket *sock;
       int err, fput_needed;
       int somaxconn;

       sock = sockfd_lookup_light(fd, &err, &fput_needed);
       if (sock) {
              somaxconn = sock_net(sock->sk)->core.sysctl_somaxconn;
              if ((unsigned int)backlog > somaxconn)
                     backlog = somaxconn;

              err = security_socket_listen(sock, backlog);
              if (!err)
                     err = sock->ops->listen(sock, backlog);

              fput_light(sock->file, fput_needed);
       }
       return err;
}
```

call [inet_listen](/docs/CS/OS/Linux/IO.md?id=inet_listen)

```c
// net/ipv4/af_inet.c
const struct proto_ops inet_stream_ops = {
       .family                  = PF_INET,
       .listen                  = inet_listen
				...
}
```



#### inet_listen

Move a socket into listening state.

sk_max_ack_backlog = backlog
```c
// af_inet.c
int inet_listen(struct socket *sock, int backlog)
{
       struct sock *sk = sock->sk;
       unsigned char old_state;
       int err, tcp_fastopen;

       lock_sock(sk);

       err = -EINVAL;
       if (sock->state != SS_UNCONNECTED || sock->type != SOCK_STREAM)
              goto out;

       old_state = sk->sk_state;
       if (!((1 << old_state) & (TCPF_CLOSE | TCPF_LISTEN)))
              goto out;

       WRITE_ONCE(sk->sk_max_ack_backlog, backlog); /** set max ack backlog */
       /* Really, if the socket is already in listen state
        * we can only allow the backlog to be adjusted.
        */
       if (old_state != TCP_LISTEN) {
              /* Enable TFO w/o requiring TCP_FASTOPEN socket option.
               * Note that only TCP sockets (SOCK_STREAM) will reach here.
               * Also fastopen backlog may already been set via the option
               * because the socket was in TCP_LISTEN state previously but
               * was shutdown() rather than close().
               */
              tcp_fastopen = sock_net(sk)->ipv4.sysctl_tcp_fastopen;
              if ((tcp_fastopen & TFO_SERVER_WO_SOCKOPT1) &&
                  (tcp_fastopen & TFO_SERVER_ENABLE) &&
                  !inet_csk(sk)->icsk_accept_queue.fastopenq.max_qlen) {
                     fastopen_queue_tune(sk, backlog);
                     tcp_fastopen_init_key_once(sock_net(sk));
              }

              err = inet_csk_listen_start(sk, backlog);
              if (err)
                     goto out;
              tcp_call_bpf(sk, BPF_SOCK_OPS_TCP_LISTEN_CB, 0, NULL);
       }
       err = 0;

out:
       release_sock(sk);
       return err;
}
```




#### inet_csk_listen_start
inet_connection_sock see [socket](/docs/CS/OS/Linux/socket.md?id=inet_connection_sock)

call `reqsk_queue_alloc`

```c
// net/ipv4/iinet_connection_sock.c
int inet_csk_listen_start(struct sock *sk, int backlog)
{
       struct inet_connection_sock *icsk = inet_csk(sk);
       struct inet_sock *inet = inet_sk(sk);
       int err = -EADDRINUSE;

       reqsk_queue_alloc(&icsk->icsk_accept_queue);

       sk->sk_ack_backlog = 0;
       inet_csk_delack_init(sk);

       /* There is race window here: we announce ourselves listening,
        * but this transition is still not validated by get_port().
        * It is OK, because this socket enters to hash table only
        * after validation is complete.
        */
       inet_sk_state_store(sk, TCP_LISTEN);
       if (!sk->sk_prot->get_port(sk, inet->inet_num)) {
              inet->inet_sport = htons(inet->inet_num);

              sk_dst_reset(sk);
              err = sk->sk_prot->hash(sk); /** enter to haah table  **/

              if (likely(!err))
                     return 0;
       }

       inet_sk_set_state(sk, TCP_CLOSE);
       return err;
}
```



```c
// net/ipv4/tcp_ipv4.c
struct proto tcp_prot = {
       .name                = "TCP",
       .hash                = inet_hash,
			 ...
}
```

#### inet_hash

```c
// net/ipv4/inet_hashtables.c
int inet_hash(struct sock *sk)
{
       int err = 0;

       if (sk->sk_state != TCP_CLOSE) {
              local_bh_disable();
              err = __inet_hash(sk, NULL);
              local_bh_enable();
       }

       return err;
}


int __inet_hash(struct sock *sk, struct sock *osk)
{
       struct inet_hashinfo *hashinfo = sk->sk_prot->h.hashinfo;
       struct inet_listen_hashbucket *ilb;
       int err = 0;

       if (sk->sk_state != TCP_LISTEN) {
              inet_ehash_nolisten(sk, osk, NULL);
              return 0;
       }
       WARN_ON(!sk_unhashed(sk));
       ilb = &hashinfo->listening_hash[inet_sk_listen_hashfn(sk)];

       spin_lock(&ilb->lock);
       if (sk->sk_reuseport) {
              err = inet_reuseport_add_sock(sk, ilb);
              if (err)
                     goto unlock;
       }
       if (IS_ENABLED(CONFIG_IPV6) && sk->sk_reuseport &&
              sk->sk_family == AF_INET6)
              __sk_nulls_add_node_tail_rcu(sk, &ilb->nulls_head);
       else
              __sk_nulls_add_node_rcu(sk, &ilb->nulls_head);
       inet_hash2(hashinfo, sk);
       ilb->count++;
       sock_set_flag(sk, SOCK_RCU_FREE);
       sock_prot_inuse_add(sock_net(sk), sk->sk_prot, 1);
unlock:
       spin_unlock(&ilb->lock);

       return err;
}
```

### accept queue

```c
// include/net/sock.h
static inline void sk_acceptq_removed(struct sock *sk)
{
	WRITE_ONCE(sk->sk_ack_backlog, sk->sk_ack_backlog - 1);
}

static inline void sk_acceptq_added(struct sock *sk)
{
	WRITE_ONCE(sk->sk_ack_backlog, sk->sk_ack_backlog + 1);
}
```
#### inet_csk_reqsk_queue_add
call `sk_acceptq_added`
```c
//
struct sock *inet_csk_reqsk_queue_add(struct sock *sk,
				      struct request_sock *req,
				      struct sock *child)
{
	struct request_sock_queue *queue = &inet_csk(sk)->icsk_accept_queue;

	spin_lock(&queue->rskq_lock);
	if (unlikely(sk->sk_state != TCP_LISTEN)) {
		inet_child_forget(sk, req, child);
		child = NULL;
	} else {
		req->sk = child;
		req->dl_next = NULL;
		if (queue->rskq_accept_head == NULL)
			WRITE_ONCE(queue->rskq_accept_head, req);
		else
			queue->rskq_accept_tail->dl_next = req;
		queue->rskq_accept_tail = req;
		sk_acceptq_added(sk);
	}
	spin_unlock(&queue->rskq_lock);
	return child;
}
```

#### reqsk_queue_remove
```c

static inline struct request_sock *reqsk_queue_remove(struct request_sock_queue *queue,
						      struct sock *parent)
{
	struct request_sock *req;

	spin_lock_bh(&queue->rskq_lock);
	req = queue->rskq_accept_head;
	if (req) {
		sk_acceptq_removed(parent);
		WRITE_ONCE(queue->rskq_accept_head, req->dl_next);
		if (queue->rskq_accept_head == NULL)
			queue->rskq_accept_tail = NULL;
	}
	spin_unlock_bh(&queue->rskq_lock);
	return req;
}
```

#### reqsk_queue_alloc
Maximum number of SYN_RECV sockets in queue per LISTEN socket.
One SYN_RECV socket costs about 80bytes on a 32bit machine.

It would be better to replace it with a global counter for all sockets
but then some measure against one socket starving all other sockets
would be needed.

The minimum value of it is 128. Experiments with real servers show that
it is absolutely not enough even at 100conn/sec. 256 cures most
of problems.

This value is adjusted to 128 for low memory machines,
and it will increase in proportion to the memory of machine.

Note : Dont forget somaxconn that may limit backlog too.
```c
// request_sock.c
void reqsk_queue_alloc(struct request_sock_queue *queue)
{
       spin_lock_init(&queue->rskq_lock);

       spin_lock_init(&queue->fastopenq.lock);
       queue->fastopenq.rskq_rst_head = NULL;
       queue->fastopenq.rskq_rst_tail = NULL;
       queue->fastopenq.qlen = 0;

       queue->rskq_accept_head = NULL;
}
```



#### request_sock_queue
struct request_sock_queue -  queue of request_socks
```c
// request_sock.h 
struct request_sock_queue {
       spinlock_t            rskq_lock;
       u8                   rskq_defer_accept; /** User waits for some data after accept() */

       u32                  synflood_warned;
       atomic_t              qlen;
       atomic_t              young;

       /** FIFO established children    */
       struct request_sock    *rskq_accept_head;
       struct request_sock    *rskq_accept_tail;
       
       struct fastopen_queue  fastopenq;  /* Check max_qlen != 0 to determine
                                        * if TFO is enabled.
                                        */
};
```

### SYN queue
SYN queue - logic queue
see [qlen and max_syn_backlog](/docs/CS/OS/Linux/TCP.md?id=tcp_v4_conn_request)


## accept

```c
// net/socket.c
SYSCALL_DEFINE4(accept4, int, fd, struct sockaddr __user *, upeer_sockaddr,
		int __user *, upeer_addrlen, int, flags)
{
	return __sys_accept4(fd, upeer_sockaddr, upeer_addrlen, flags);
}
```

For accept, we attempt to create a new socket, set up the link with the client, wake up the client, then return the new connected fd. We collect the address of the connector in kernel space and move it to user at the very end. This is unclean because we open the socket then return an error.

1003.1g adds the ability to `recvmsg()` to query connection pending status to recvmsg. We need to add that support in a way thats clean when we restructure accept also.

1. do_accept
2. fd_install

```c

int __sys_accept4(int fd, struct sockaddr __user *upeer_sockaddr,
		  int __user *upeer_addrlen, int flags)
{
	int ret = -EBADF;
	struct fd f;

	f = fdget(fd);
	if (f.file) {
		ret = __sys_accept4_file(f.file, 0, upeer_sockaddr,
						upeer_addrlen, flags,
						rlimit(RLIMIT_NOFILE));
		fdput(f);
	}

	return ret;
}


int __sys_accept4_file(struct file *file, unsigned file_flags,
		       struct sockaddr __user *upeer_sockaddr,
		       int __user *upeer_addrlen, int flags,
		       unsigned long nofile)
{
	struct file *newfile;
	int newfd;

	newfile = do_accept(file, file_flags, upeer_sockaddr, upeer_addrlen,
			    flags);

	fd_install(newfd, newfile);	/* 	install newfile */
	return newfd;
}
```

### do_accept


1. get listen sock from file
2. [sock_alloc]()
3. copy type and ops from listen socket
3. [alloc_file]() for newsock
3. call `inet_accept`

```c

struct file *do_accept(struct file *file, unsigned file_flags,
		       struct sockaddr __user *upeer_sockaddr,
		       int __user *upeer_addrlen, int flags)
{
	struct socket *sock, *newsock;
	struct file *newfile;
	int err, len;
	struct sockaddr_storage address;

	sock = sock_from_file(file);

	newsock = sock_alloc();

	newsock->type = sock->type;
	newsock->ops = sock->ops;


	newfile = sock_alloc_file(newsock, flags, sock->sk->sk_prot_creator->name);

	err = sock->ops->accept(sock, newsock, sock->file->f_flags | file_flags,
					false);
	...
    
	/* File flags are not inherited via accept() unlike another OSes. */
	return newfile;
}
```



#### sock_alloc_file

Bind a &socket to a &file

```c

struct file *sock_alloc_file(struct socket *sock, int flags, const char *dname)
{
	struct file *file;

	file = alloc_file_pseudo(SOCK_INODE(sock), sock_mnt, dname,
				O_RDWR | (flags & O_NONBLOCK),
				&socket_file_ops);
	

	sock->file = file;
	file->private_data = sock;
	stream_open(SOCK_INODE(sock), file);
	return file;
}
```

#### alloc_file

```c
// fs/file_table.c
struct file *alloc_file_pseudo(struct inode *inode, struct vfsmount *mnt,
				const char *name, int flags,
				const struct file_operations *fops)
{
	...
	file = alloc_file(&path, flags, fops);
	return file;
}

/* alloc_file - allocate and initialize a 'struct file' 	*/
static struct file *alloc_file(const struct path *path, int flags,
		const struct file_operations *fop)
{
	struct file *file;

	file = alloc_empty_file(flags, current_cred());
	...
	file->f_op = fop;
	return file;
}
```



#### file_operations

Socket files have a set of 'special' operations as well as the generic file ones. These don't appear in the operation structures but are done directly via the socketcall() multiplexor.

```c
// net/socket.c
static const struct file_operations socket_file_ops = {
	.owner =	THIS_MODULE,
	.llseek =	no_llseek,
	.read_iter =	sock_read_iter,
	.write_iter =	sock_write_iter,
	.poll =		sock_poll, 	/** sock_poll 	*/
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

### fd_install

Install a file pointer in the fd array.

The VFS is full of places where we drop the files lock between setting the open_fds bitmap and installing the file in the file array.  At any such point, we are vulnerable to a dup2() race installing a file in the array before us.  We need to detect this and fput() the struct file we are about to overwrite in this case.

It should never happen - if we allow dup2() do it, _really_ bad things will follow.

This consumes the "file" refcount, so callers should treat it as if they had called fput(file).



```c
void fd_install(unsigned int fd, struct file *file)
{
	struct files_struct *files = current->files;
	struct fdtable *fdt;

  ...
	fdt = files_fdtable(files);	
	rcu_assign_pointer(fdt->fd[fd], file);
	
}
```



### inet_accept

```c
// net/ipv4/af_inet.c
/*
 *	Accept a pending connection. The TCP layer now gives BSD semantics.
 */
int inet_accept(struct socket *sock, struct socket *newsock, int flags,
		bool kern)
{
	struct sock *sk1 = sock->sk;
	int err = -EINVAL;
	struct sock *sk2 = sk1->sk_prot->accept(sk1, flags, &err, kern);

	if (!sk2)
		goto do_err;

	lock_sock(sk2);

	sock_rps_record_flow(sk2);
	WARN_ON(!((1 << sk2->sk_state) &
		  (TCPF_ESTABLISHED | TCPF_SYN_RECV |
		  TCPF_CLOSE_WAIT | TCPF_CLOSE)));

	sock_graft(sk2, newsock);

	newsock->state = SS_CONNECTED;
	err = 0;
	release_sock(sk2);
do_err:
	return err;
}
```

call `inet_csk_accept`
```c
// net/ipv4/tcp_ipv4.c
struct proto tcp_prot = {
	.name			= "TCP",
	.accept			= inet_csk_accept,
	...
};
```

#### inet_csk_accept
This will accept the next outstanding connection.
call [reqsk_queue_remove](/docs/CS/OS/Linux/IO.md?id=reqsk_queue_remove)
```c
// 
struct sock *inet_csk_accept(struct sock *sk, int flags, int *err, bool kern)
{
	struct inet_connection_sock *icsk = inet_csk(sk);
	struct request_sock_queue *queue = &icsk->icsk_accept_queue;
	struct request_sock *req;
	struct sock *newsk;
	int error;

	lock_sock(sk);

	/* We need to make sure that this socket is listening,
	 * and that it has something pending.
	 */
	error = -EINVAL;
	if (sk->sk_state != TCP_LISTEN)
		goto out_err;

	/* Find already established connection */
	if (reqsk_queue_empty(queue)) {
		long timeo = sock_rcvtimeo(sk, flags & O_NONBLOCK);

		/* If this is a non blocking socket don't sleep */
		error = -EAGAIN;
		if (!timeo)
			goto out_err;

		error = inet_csk_wait_for_connect(sk, timeo);
		if (error)
			goto out_err;
	}
	req = reqsk_queue_remove(queue, sk);
	newsk = req->sk;

	if (sk->sk_protocol == IPPROTO_TCP &&
	    tcp_rsk(req)->tfo_listener) {
		spin_lock_bh(&queue->fastopenq.lock);
		if (tcp_rsk(req)->tfo_listener) {
			/* We are still waiting for the final ACK from 3WHS
			 * so can't free req now. Instead, we set req->sk to
			 * NULL to signify that the child socket is taken
			 * so reqsk_fastopen_remove() will free the req
			 * when 3WHS finishes (or is aborted).
			 */
			req->sk = NULL;
			req = NULL;
		}
		spin_unlock_bh(&queue->fastopenq.lock);
	}

out:
	release_sock(sk);
	if (newsk && mem_cgroup_sockets_enabled) {
		int amt;

		/* atomically get the memory usage, set and charge the
		 * newsk->sk_memcg.
		 */
		lock_sock(newsk);

		/* The socket has not been accepted yet, no need to look at
		 * newsk->sk_wmem_queued.
		 */
		amt = sk_mem_pages(newsk->sk_forward_alloc +
				   atomic_read(&newsk->sk_rmem_alloc));
		mem_cgroup_sk_alloc(newsk);
		if (newsk->sk_memcg && amt)
			mem_cgroup_charge_skmem(newsk->sk_memcg, amt);

		release_sock(newsk);
	}
	if (req)
		reqsk_put(req);
	return newsk;
out_err:
	newsk = NULL;
	req = NULL;
	*err = error;
	goto out;
}
```

TODO:

> 127.0.0.1 本机网络IO不需要经过网卡， 不经过Ring Buffer 直接把skb传送给协议接收栈， 可以通过BPF绕过内核协议栈，减少开销（Istio的sidecar代理与本地进程通信）

## mmap

## sendfile



## select

1. copy fd_set to kernelspace from userspace
2. register `__pollwait` callback
3. iterate all fds

```c
static __attribute__((unused))
int select(int nfds, fd_set *rfds, fd_set *wfds, fd_set *efds, struct timeval *timeout)
{
	int ret = sys_select(nfds, rfds, wfds, efds, timeout);

	if (ret < 0) {
		SET_ERRNO(-ret);
		ret = -1;
	}
	return ret;
}
```





```c

static __attribute__((unused))
int sys_select(int nfds, fd_set *rfds, fd_set *wfds, fd_set *efds, struct timeval *timeout)
{
#if defined(__ARCH_WANT_SYS_OLD_SELECT) && !defined(__NR__newselect)
	struct sel_arg_struct {
		unsigned long n;
		fd_set *r, *w, *e;
		struct timeval *t;
	} arg = { .n = nfds, .r = rfds, .w = wfds, .e = efds, .t = timeout };
	return my_syscall1(__NR_select, &arg);
#elif defined(__ARCH_WANT_SYS_PSELECT6) && defined(__NR_pselect6)
	struct timespec t;

	if (timeout) {
		t.tv_sec  = timeout->tv_sec;
		t.tv_nsec = timeout->tv_usec * 1000;
	}
	return my_syscall6(__NR_pselect6, nfds, rfds, wfds, efds, timeout ? &t : NULL, NULL);
#elif defined(__NR__newselect) || defined(__NR_select)
#ifndef __NR__newselect
#define __NR__newselect __NR_select
#endif
	return my_syscall5(__NR__newselect, nfds, rfds, wfds, efds, timeout);
#else
#error None of __NR_select, __NR_pselect6, nor __NR__newselect defined, cannot implement sys_select()
#endif
}
```





```c
// fs/select.c

static int do_sys_poll(struct pollfd __user *ufds, unsigned int nfds,
		struct timespec64 *end_time)
{
	struct poll_wqueues table;
	int err = -EFAULT, fdcount, len;
	/* Allocate small arguments on the stack to save memory and be
	   faster - use long to make sure the buffer is aligned properly
	   on 64 bit archs to avoid unaligned access */
	long stack_pps[POLL_STACK_ALLOC/sizeof(long)];
	struct poll_list *const head = (struct poll_list *)stack_pps;
 	struct poll_list *walk = head;
 	unsigned long todo = nfds;

	if (nfds > rlimit(RLIMIT_NOFILE))
		return -EINVAL;

	len = min_t(unsigned int, nfds, N_STACK_PPS);
	for (;;) {
		walk->next = NULL;
		walk->len = len;
		if (!len)
			break;

		if (copy_from_user(walk->entries, ufds + nfds-todo,
					sizeof(struct pollfd) * walk->len))
			goto out_fds;

		todo -= walk->len;
		if (!todo)
			break;

		len = min(todo, POLLFD_PER_PAGE);
		walk = walk->next = kmalloc(struct_size(walk, entries, len),
					    GFP_KERNEL);
		if (!walk) {
			err = -ENOMEM;
			goto out_fds;
		}
	}

	poll_initwait(&table);
	fdcount = do_poll(head, &table, end_time);
	poll_freewait(&table);

	if (!user_write_access_begin(ufds, nfds * sizeof(*ufds)))
		goto out_fds;

	for (walk = head; walk; walk = walk->next) {
		struct pollfd *fds = walk->entries;
		int j;

		for (j = walk->len; j; fds++, ufds++, j--)
			unsafe_put_user(fds->revents, &ufds->revents, Efault);
  	}
	user_write_access_end();

	err = fdcount;
out_fds:
	walk = head->next;
	while (walk) {
		struct poll_list *pos = walk;
		walk = walk->next;
		kfree(pos);
	}

	return err;

Efault:
	user_write_access_end();
	err = -EFAULT;
	goto out_fds;
}
```



## poll



```c
// include/upai/asm-generic/poll.h
struct pollfd {
	int fd;
	short events;
	short revents;
};
```





## References

1. [打破砂锅挖到底—— Epoll 多路复用是如何转起来的？](https://mp.weixin.qq.com/s/Py2TE9CdQ92fGLpg-SEj_g)