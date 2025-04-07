## Introduction

系统调用的实现基础，其实就是两条汇编指令，分别是syscall和sysret。

syscall使执行逻辑从用户态切换到内核态，在进入到内核态之后，cpu会从 MSR_LSTAR 寄存器中，获取处理系统调用内核代码的起始地址，即上面的 entry_SYSCALL_64。
在执行 entry_SYSCALL_64 函数时，内核代码会根据约定，先从rax寄存器中获取想要执行的系统调用的编号，然后根据该编号从sys_call_table数组中找到对应的系统调用函数。
接着，从 rdi, rsi, rdx, r10, r8, r9 寄存器中获取该系统调用函数所需的参数，然后调用该函数，把这些参数传入其中。
在系统调用函数执行完毕之后，执行结果会被放到rax寄存器中。
最后，执行sysret汇编指令，从内核态切换回用户态，用户程序继续执行。
如果用户程序需要该系统调用的返回结果，则从rax中获取。

sys_call_table数组的定义：

该数组各元素的默认值都是 __x64_sys_ni_syscall
该函数也非常简单，就是直接返回错误码 -ENOSYS，表示系统调用非法。
sys_call_table数组定义的地方好像只设置了默认值，并没有设置真正的系统调用函数

我们再回头仔细看下sys_call_table数组的定义，它在设置完默认值之后，后面还include了一个名为asm/syscalls_64.h的头文件 这个头文件是编译时生成的 makefile中使用了syscalltbl.sh脚本和syscall_64.tbl模板文件来生成这个syscalls_64.h头文件。

来看下生成的syscalls_64.h头文件：




```c
__visible noinstr bool do_syscall_64(struct pt_regs *regs, int nr)
{
    add_random_kstack_offset();
    nr = syscall_enter_from_user_mode(regs, nr);

    instrumentation_begin();

    if (!do_syscall_x64(regs, nr) && !do_syscall_x32(regs, nr) && nr != -1) {
        /* Invalid system call, but still a system call. */
        regs->ax = __x64_sys_ni_syscall(regs);
    }

    instrumentation_end();
    syscall_exit_to_user_mode(regs);

    /*
	 * Check that the register state is valid for using SYSRET to exit
	 * to userspace.  Otherwise use the slower but fully capable IRET
	 * exit path.
	 */

    /* XEN PV guests always use the IRET path */
    if (cpu_feature_enabled(X86_FEATURE_XENPV))
        return false;

    /* SYSRET requires RCX == RIP and R11 == EFLAGS */
    if (unlikely(regs->cx != regs->ip || regs->r11 != regs->flags))
        return false;

    /* CS and SS must match the values set in MSR_STAR */
    if (unlikely(regs->cs != __USER_CS || regs->ss != __USER_DS))
        return false;

    /*
	 * On Intel CPUs, SYSRET with non-canonical RCX/RIP will #GP
	 * in kernel space.  This essentially lets the user take over
	 * the kernel, since userspace controls RSP.
	 *
	 * TASK_SIZE_MAX covers all user-accessible addresses other than
	 * the deprecated vsyscall page.
	 */
    if (unlikely(regs->ip >= TASK_SIZE_MAX))
        return false;

    /*
	 * SYSRET cannot restore RF.  It can restore TF, but unlike IRET,
	 * restoring TF results in a trap from userspace immediately after
	 * SYSRET.
	 */
    if (unlikely(regs->flags & (X86_EFLAGS_RF | X86_EFLAGS_TF)))
        return false;

    /* Use SYSRET to exit to userspace */
    return true;
}
```

efi stub是linux的一个feature，它可以通过配置 CONFIG_EFI_STUB 来开启和关闭。
它的实现原理是，按照 uefi 指定的 pecoff 格式，将内核伪装成一个 uefi application，这样在支持 uefi 的各种硬件上，就可以按照 uefi 协议，直接启动linux内核了。

linux内核efi stub有关pecoff 格式定义的部分都在 arch/x86/boot/header.S 这个文件里


```c
// include/uapi/linux/net.h
#define SYS_SOCKET     1             /* sys_socket(2)              */
#define SYS_BIND       2             /* sys_bind(2)               */
#define SYS_CONNECT    3             /* sys_connect(2)             */
#define SYS_LISTEN     4             /* sys_listen(2)              */
#define SYS_ACCEPT     5             /* sys_accept(2)              */
#define SYS_GETSOCKNAME        6             /* sys_getsockname(2)         */
#define SYS_GETPEERNAME        7             /* sys_getpeername(2)         */
#define SYS_SOCKETPAIR 8             /* sys_socketpair(2)          */
#define SYS_SEND       9             /* sys_send(2)               */
#define SYS_RECV       10            /* sys_recv(2)               */
#define SYS_SENDTO     11            /* sys_sendto(2)              */
#define SYS_RECVFROM   12            /* sys_recvfrom(2)            */
#define SYS_SHUTDOWN   13            /* sys_shutdown(2)            */
#define SYS_SETSOCKOPT 14            /* sys_setsockopt(2)          */
#define SYS_GETSOCKOPT 15            /* sys_getsockopt(2)          */
#define SYS_SENDMSG    16            /* sys_sendmsg(2)             */
#define SYS_RECVMSG    17            /* sys_recvmsg(2)             */
#define SYS_ACCEPT4    18            /* sys_accept4(2)             */
#define SYS_RECVMMSG   19            /* sys_recvmmsg(2)            */
#define SYS_SENDMMSG   20            /* sys_sendmmsg(2)            */
```

## socket

see [sys_socket](/docs/CS/OS/Linux/net/socket.md?id=create)

## bind

Bind a name to a socket.
Nothing much to do here since it's the protocol's responsibility to handle the local address.

We move the socket address to kernel space before we call the protocol layer (having also checked the address is ok).

Data Structures Related to bind

- tcp_hashinfo
- tcp_bind_hashbucket
- tcp_bind_bucket

### sys_bind

1. sockfd_lookup_light
2. move_addr_to_kernel
3. inet_bind

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

	/* If the socket has its own bind function then use it. (RAW) */
	if (sk->sk_prot->bind) {
		return sk->sk_prot->bind(sk, uaddr, addr_len);
	}
	if (addr_len < sizeof(struct sockaddr_in))
		return -EINVAL;

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
```

```c
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

### reuse

ip_autobind_reuse - BOOLEAN

By default, bind() does not select the ports automatically even if the new socket and all sockets bound to the port have SO_REUSEADDR.
ip_autobind_reuse allows bind() to reuse the port and this is useful when you use bind()+connect(), but may break some applications.
The preferred solution is to use IP_BIND_ADDRESS_NO_PORT and this option should only be set by experts.

Default: 0

## listen

> -- [listen(2) — Linux manual page](https://man7.org/linux/man-pages/man2/listen.2.html)
>
> The behavior of the backlog argument on TCP sockets changed with Linux 2.2.
> Now it specifies the queue length for completely established sockets waiting to be accepted, instead of the number of incomplete connection requests.
> The maximum length of the queue for incomplete sockets can be set using /proc/sys/net/ipv4/tcp_max_syn_backlog.
> When syncookies are enabled there is no logical maximum length and this setting is ignored. 
>
> If the backlog argument is greater than the value in /proc/sys/net/core/somaxconn, then it is silently capped to that value.
> Since Linux 5.4, the default in this file is 4096; in earlier kernels, the default value is 128.  
> In kernels before 2.4.25, this limit was a hard coded value, SOMAXCONN, with the value 128.

**listen for socket connections and limit the queue of incoming connections**

Perform a listen. Basically, we allow the protocol to do anything necessary for a listen, and if that works, we mark the socket as ready for listening.

1. sockfd_lookup_light
2. set backlog
3. call inet_listen/sock_no_listen

get somaxconn by `cat /proc/sys/net/core/somaxconn`, and `max_ack_backlog = Min(backlog, net.core.somaxconn)`

限制了全连接队列大小和半连接个数 

listen 可以重复调用，重复调用 listen 可修改 backlog，


```c
// socket.c
SYSCALL_DEFINE2(listen, int, fd, int, backlog)
{
       return __sys_listen(fd, backlog);
}

int __sys_listen(int fd, int backlog)
{
       sock = sockfd_lookup_light(fd, &err, &fput_needed);
       if (sock) {
              somaxconn = sock_net(sock->sk)->core.sysctl_somaxconn;
              if ((unsigned int)backlog > somaxconn)
                     backlog = somaxconn;

             err = sock->ops->listen(sock, backlog);
       }
       return err;
}
```

We call the protocol - specifi c listen function finally.
This is `sock->ops->listen()`. For the *PF_INET* protocol family, `sock->ops` is set to `inet_stream_ops`.
So, we are calling `listen()` function from `inet_stream_ops`, *[inet_listen()](/docs/CS/OS/Linux/Calls.md?id=inet_listen)*.

call `inet_listen`

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

set sk_max_ack_backlog = backlog

```c
// af_inet.c
int inet_listen(struct socket *sock, int backlog)
{
       WRITE_ONCE(sk->sk_max_ack_backlog, backlog);
      
       if (old_state != TCP_LISTEN) {
              err = inet_csk_listen_start(sk, backlog);
       }
}
```

#### inet_csk_listen_start

inet_connection_sock see [socket](/docs/CS/OS/Linux/net/socket.md?id=inet_connection_sock)

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
              err = sk->sk_prot->hash(sk); /** enter to listen haah table  **/

              if (likely(!err))
                     return 0;
       }

       inet_sk_set_state(sk, TCP_CLOSE);
       return err;
}
```

call inet_hash

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

##### inet_hashinfo

```c
struct inet_hashinfo {
       /* This is for sockets with full identity only.  Sockets here will
        * always be without wildcards and will have the following invariant:
        *
        *          TCP_ESTABLISHED <= sk->sk_state < TCP_CLOSE
        *
        */
       struct inet_ehash_bucket       *ehash;
       spinlock_t                   *ehash_locks;
       unsigned int                 ehash_mask;
       unsigned int                 ehash_locks_mask;

       /* Ok, let's try this, I give up, we do need a local binding
        * TCP hash as well as the others for fast bind/connect.
        */
       struct kmem_cache             *bind_bucket_cachep;
       struct inet_bind_hashbucket    *bhash;
       unsigned int                 bhash_size;

       /* The 2nd listener table hashed by local port and address */
       unsigned int                 lhash2_mask;
       struct inet_listen_hashbucket  *lhash2;

       /* All the above members are written once at bootup and
        * never written again _or_ are predominantly read-access.
        *
        * Now align to a new cache line as all the following members
        * might be often dirty.
        */
       /* All sockets in TCP_LISTEN state will be in listening_hash.
        * This is the only table where wildcard'd TCP sockets can
        * exist.  listening_hash is only hashed by local port number.
        * If lhash2 is initialized, the same socket will also be hashed
        * to lhash2 by port and address.
        */
       struct inet_listen_hashbucket  listening_hash[INET_LHTABLE_SIZE]
                                   ____cacheline_aligned_in_smp;
};
```
inet_ehash_nolisten
```c
// net/ipv4/inet_hashtables.c
bool inet_ehash_nolisten(struct sock *sk, struct sock *osk, bool *found_dup_sk)
{
       bool ok = inet_ehash_insert(sk, osk, found_dup_sk);

       if (ok) {
              sock_prot_inuse_add(sock_net(sk), sk->sk_prot, 1);
       } else {
              percpu_counter_inc(sk->sk_prot->orphan_count);
              inet_sk_set_state(sk, TCP_CLOSE);
              sock_set_flag(sk, SOCK_DEAD);
              inet_csk_destroy_sock(sk);
       }
       return ok;
}


Insert a socket into ehash, and eventually remove another one
(The another one can be a `SYN_RECV` or `TIMEWAIT`)

If an existing socket already exists, socket sk is not inserted,
and sets `found_dup_sk` parameter to true.

// net/ipv4/inet_hashtables.c
bool inet_ehash_insert(struct sock *sk, struct sock *osk, bool *found_dup_sk)
{
	struct inet_hashinfo *hashinfo = sk->sk_prot->h.hashinfo;
	struct hlist_nulls_head *list;
	struct inet_ehash_bucket *head;
	spinlock_t *lock;
	bool ret = true;

	WARN_ON_ONCE(!sk_unhashed(sk));

	sk->sk_hash = sk_ehashfn(sk);
	head = inet_ehash_bucket(hashinfo, sk->sk_hash);
	list = &head->chain;
	lock = inet_ehash_lockp(hashinfo, sk->sk_hash);

	spin_lock(lock);
	if (osk) {
		WARN_ON_ONCE(sk->sk_hash != osk->sk_hash);
		ret = sk_nulls_del_node_init_rcu(osk);
	} else if (found_dup_sk) {
		*found_dup_sk = inet_ehash_lookup_by_sk(sk, list);
		if (*found_dup_sk)
			ret = false;
	}

	if (ret)
		__sk_nulls_add_node_rcu(sk, list);

	spin_unlock(lock);

	return ret;
}
```

### accept queue

The Accept Queue contains fully established connections: ready to be picked up by the application.
When a process calls , the sockets are de-queued and passed to the application.accept()

This is a rather simplified view of SYN packet handling on Linux.
With socket toggles like TCP_DEFER_ACCEPT[2] and things work slightly differently.TCP_FASTOPEN

Queue size limits

The maximum allowed length of both the Accept and SYN Queues is taken from the parameter passed to the syscall by the application.
For example, this sets the Accept and SYN Queue sizes to 1,024:backloglisten(2)

Note: In kernels before 4.3 the SYN Queue length was counted differently.

This SYN Queue cap used to be configured by the toggle, but this isn't the case anymore. Nowadays caps both queue sizes. On our servers we set it to 16k:net.ipv4.tcp_max_syn_backlognet.core.somaxconn

```shell
$ sysctl net.core.somaxconn
net.core.somaxconn = 16384
```

Perfect backlog value
Knowing all that, we might ask the question - what is the ideal parameter value?backlog

The answer is: it depends. For the majority of trivial TCP Servers it doesn't really matter. For example, before version 1.11 Golang famously didn't support customizing backlog value. There are valid reasons to increase this value though:

When the rate of incoming connections is really large, even with a performant application, the inbound SYN Queue may need a larger number of slots.
The value controls the SYN Queue size. This effectively can be read as "ACK packets in flight". The larger the average round trip time to the client, the more slots are going to be used. In the case of many clients far away from the server, hundreds of milliseconds away, it makes sense to increase the backlog value.backlog
The option causes sockets to remain in the SYN-RECV state longer and contribute to the queue limits.TCP_DEFER_ACCEPT
Overshooting the is bad as well:backlog

Each slot in SYN Queue uses some memory. During a SYN Flood it makes no sense to waste resources on storing attack packets. Each entry in SYN Queue takes 256 bytes of memory on kernel 4.14.struct inet_request_sock
To peek into the SYN Queue on Linux we can use the command and look for sockets. For example, on one of Cloudflare's servers we can see 119 slots used in tcp/80 SYN Queue and 78 on tcp/443.ssSYN-RECV

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

Called by [TCP connect request](/docs/CS/OS/Linux/TCP.md?id=tcp_conn_request)

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

Called when [accept](/docs/CS/OS/Linux/Calls.md?id=inet_csk_accept)

remove head established connection from reqsk_queue and backlog - 1

```c
// 
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

It would be better to replace it with a global counter for all sockets but then some measure against one socket starving all other sockets would be needed.

The minimum value of it is 128. Experiments with real servers show that it is absolutely not enough even at 100conn/sec. 256 cures most of problems.

This value is adjusted to 128 for low memory machines, and it will increase in proportion to the memory of machine.

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
全连接队列

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

The SYN Queue stores inbound SYN packets[1] (specifically: struct inet_request_sock).
It's responsible for sending out SYN+ACK packets and retrying them on timeout.
<br/>
On Linux the number of retries is configured with:

```shell
$ sysctl net.ipv4.tcp_synack_retries
net.ipv4.tcp_synack_retries = 5
```

After transmitting the SYN+ACK, the SYN Queue waits for an ACK packet from the client - the last packet in the three-way-handshake.
All received ACK packets must first be matched against the fully established connection table, and only then against data in the relevant SYN Queue.
On SYN Queue match, the kernel removes the item from the SYN Queue, happily creates a fully fledged connection (specifically: struct inet_sock), and adds it to the Accept Queue.

SYN queue - logic queue
see [qlen and max_syn_backlog](/docs/CS/OS/Linux/TCP.md?id=tcp_conn_request)

```c

const struct inet_connection_sock_af_ops ipv4_specific = {
	.conn_request	   = tcp_v4_conn_request,
	.syn_recv_sock	   = tcp_v4_syn_recv_sock,
    ...
};
```

```c

int tcp_v4_conn_request(struct sock *sk, struct sk_buff *skb)
{
	/* Never answer to SYNs send to broadcast or multicast */
	if (skb_rtable(skb)->rt_flags & (RTCF_BROADCAST | RTCF_MULTICAST))
		goto drop;

	return tcp_conn_request(&tcp_request_sock_ops,
				&tcp_request_sock_ipv4_ops, sk, skb);

drop:
	tcp_listendrop(sk);
	return 0;
}
```

#### tcp_v4_syn_recv_sock

The three way handshake has completed - we got a valid synack - now create the new socket.

```c
//
struct sock *tcp_v4_syn_recv_sock(const struct sock *sk, struct sk_buff *skb,
				  struct request_sock *req,
				  struct dst_entry *dst,
				  struct request_sock *req_unhash,
				  bool *own_req)
{
	struct inet_request_sock *ireq;
	bool found_dup_sk = false;
	struct inet_sock *newinet;
	struct tcp_sock *newtp;
	struct sock *newsk;
#ifdef CONFIG_TCP_MD5SIG
	const union tcp_md5_addr *addr;
	struct tcp_md5sig_key *key;
	int l3index;
#endif
	struct ip_options_rcu *inet_opt;

	if (sk_acceptq_is_full(sk))
		goto exit_overflow;

	newsk = tcp_create_openreq_child(sk, req, skb);
	if (!newsk)
		goto exit_nonewsk;

	newsk->sk_gso_type = SKB_GSO_TCPV4;
	inet_sk_rx_dst_set(newsk, skb);

	newtp		      = tcp_sk(newsk);
	newinet		      = inet_sk(newsk);
	ireq		      = inet_rsk(req);
	sk_daddr_set(newsk, ireq->ir_rmt_addr);
	sk_rcv_saddr_set(newsk, ireq->ir_loc_addr);
	newsk->sk_bound_dev_if = ireq->ir_iif;
	newinet->inet_saddr   = ireq->ir_loc_addr;
	inet_opt	      = rcu_dereference(ireq->ireq_opt);
	RCU_INIT_POINTER(newinet->inet_opt, inet_opt);
	newinet->mc_index     = inet_iif(skb);
	newinet->mc_ttl	      = ip_hdr(skb)->ttl;
	newinet->rcv_tos      = ip_hdr(skb)->tos;
	inet_csk(newsk)->icsk_ext_hdr_len = 0;
	if (inet_opt)
		inet_csk(newsk)->icsk_ext_hdr_len = inet_opt->opt.optlen;
	newinet->inet_id = prandom_u32();

	/* Set ToS of the new socket based upon the value of incoming SYN.
	 * ECT bits are set later in tcp_init_transfer().
	 */
	if (sock_net(sk)->ipv4.sysctl_tcp_reflect_tos)
		newinet->tos = tcp_rsk(req)->syn_tos & ~INET_ECN_MASK;

	if (!dst) {
		dst = inet_csk_route_child_sock(sk, newsk, req);
		if (!dst)
			goto put_and_exit;
	} else {
		/* syncookie case : see end of cookie_v4_check() */
	}
	sk_setup_caps(newsk, dst);

	tcp_ca_openreq_child(newsk, dst);

	tcp_sync_mss(newsk, dst_mtu(dst));
	newtp->advmss = tcp_mss_clamp(tcp_sk(sk), dst_metric_advmss(dst));

	tcp_initialize_rcv_mss(newsk);

#ifdef CONFIG_TCP_MD5SIG
	l3index = l3mdev_master_ifindex_by_index(sock_net(sk), ireq->ir_iif);
	/* Copy over the MD5 key from the original socket */
	addr = (union tcp_md5_addr *)&newinet->inet_daddr;
	key = tcp_md5_do_lookup(sk, l3index, addr, AF_INET);
	if (key) {
		/*
		 * We're using one, so create a matching key
		 * on the newsk structure. If we fail to get
		 * memory, then we end up not copying the key
		 * across. Shucks.
		 */
		tcp_md5_do_add(newsk, addr, AF_INET, 32, l3index, key->flags,
			       key->key, key->keylen, GFP_ATOMIC);
		sk_nocaps_add(newsk, NETIF_F_GSO_MASK);
	}
#endif

	if (__inet_inherit_port(sk, newsk) < 0)
		goto put_and_exit;
	*own_req = inet_ehash_nolisten(newsk, req_to_sk(req_unhash),
				       &found_dup_sk);
	if (likely(*own_req)) {
		tcp_move_syn(newtp, req);
		ireq->ireq_opt = NULL;
	} else {
		newinet->inet_opt = NULL;

		if (!req_unhash && found_dup_sk) {
			/* This code path should only be executed in the
			 * syncookie case only
			 */
			bh_unlock_sock(newsk);
			sock_put(newsk);
			newsk = NULL;
		}
	}
	return newsk;

exit_overflow:
	NET_INC_STATS(sock_net(sk), LINUX_MIB_LISTENOVERFLOWS);
exit_nonewsk:
	dst_release(dst);
exit:
	tcp_listendrop(sk);
	return NULL;
put_and_exit:
	newinet->inet_opt = NULL;
	inet_csk_prepare_forced_close(newsk);
	tcp_done(newsk);
	goto exit;
}
```

## accept

accept, accept4 - accept a connection on a socket

accept返回的fd 中持有 file的指针 file-> *private_data 指向socket socket-> *file 又指回到 file 互相持有引用

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
// net/socket.c
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
4. [alloc_file]() for newsock
5. call `inet_accept`

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

Socket files have a set of 'special' operations as well as the generic file ones. 
These don't appear in the operation structures but are done directly via the socketcall() multiplexor.

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
call [reqsk_queue_remove](/docs/CS/OS/Linux/Calls.md?id=reqsk_queue_remove)

```c
struct sock *inet_csk_accept(struct sock *sk, struct proto_accept_arg *arg)
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
        long timeo = sock_rcvtimeo(sk, arg->flags & O_NONBLOCK);

        /* If this is a non blocking socket don't sleep */
        error = -EAGAIN;
        if (!timeo)
            goto out_err;

        error = inet_csk_wait_for_connect(sk, timeo);
        if (error)
            goto out_err;
    }
    req = reqsk_queue_remove(queue, sk);
    arg->is_empty = reqsk_queue_empty(queue);
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
    
    if (req)
        reqsk_put(req);
    ...

    return newsk;
}
```



## recv

```c
/**
 *    recv 	---+--- 	recvfrom
 *                |
 * 			  \|/
 *			sys_recvfrom ---> sock_recvmsg ---> inet_recvmsg
 *                                                     |
 *											        \|/
 *					            tcp_recvmsg      ----+----      udp_recvmsg
 */
```





## read

内核通过查找进程文件符表，定位到内核已打开文件集上的文件信息，从而找到此文件的inode。
inode在address_space上查找要请求的文件页是否已经缓存在页缓存中。如果存在，则直接返回这片文件页的内容。
如果不存在，则通过inode定位到文件磁盘地址，将数据从磁盘复制到页缓存。 之后再次发起读页面过程，进而将页缓存中的数据发给用户进程

```c
// fs/read_write.c
SYSCALL_DEFINE3(read, unsigned int, fd, char __user *, buf, size_t, count)
{
    return ksys_read(fd, buf, count);
}

ssize_t ksys_read(unsigned int fd, char __user *buf, size_t count)
{
	struct fd f = fdget_pos(fd);
	ssize_t ret = -EBADF;

	if (f.file) {
		loff_t pos, *ppos = file_ppos(f.file);
		if (ppos) {
			pos = *ppos;
			ppos = &pos;
		}
		ret = vfs_read(f.file, buf, count, ppos);
		if (ret >= 0 && ppos)
			f.file->f_pos = pos;
		fdput_pos(f);
	}
	return ret;
}

static inline struct fd fdget_pos(int fd)
{
	return __to_fd(__fdget_pos(fd));
}

/* file_ppos returns &file->f_pos or NULL if file is stream */
static inline loff_t *file_ppos(struct file *file)
{
	return file->f_mode & FMODE_STREAM ? NULL : &file->f_pos;
}
```

file->f_op 包含着文件系统对文件的操作函数

其实真正的读 read 操作是调用 file -> f_op -> read()

### vfs_read

```c
ssize_t vfs_read(struct file *file, char __user *buf, size_t count, loff_t *pos)
{
    ssize_t ret;
    // ...
    ret = rw_verify_area(READ, file, pos, count);

    if (file->f_op->read)
        ret = file->f_op->read(file, buf, count, pos);
    else if (file->f_op->read_iter)
        ret = new_sync_read(file, buf, count, pos);
    else
        ret = -EINVAL;
    if (ret > 0) {
        fsnotify_access(file);
        add_rchar(current, ret);
    }
    inc_syscr(current);
    return ret;
}
```

#### new_sync_read

```c
static ssize_t new_sync_read(struct file *filp, char __user *buf, size_t len, loff_t *ppos)
{
    struct iovec iov = { .iov_base = buf, .iov_len = len };
    struct kiocb kiocb;
    struct iov_iter iter;
    ssize_t ret;

    init_sync_kiocb(&kiocb, filp);
    kiocb.ki_pos = (ppos ? *ppos : 0);
    iov_iter_init(&iter, READ, &iov, 1, len);

    ret = call_read_iter(filp, &kiocb, &iter);
    BUG_ON(ret == -EIOCBQUEUED);
    if (ppos)
        *ppos = kiocb.ki_pos;
    return ret;
}

static inline ssize_t call_read_iter(struct file *file, struct kiocb *kio,
				     struct iov_iter *iter)
{
	return file->f_op->read_iter(kio, iter);
}
```

read_iter



socket走到tcp_recvmsg



```c
static ssize_t sock_read_iter(struct kiocb *iocb, struct iov_iter *to)
{
    struct file *file = iocb->ki_filp;
    struct socket *sock = file->private_data;
    struct msghdr msg = {.msg_iter = *to,
                 .msg_iocb = iocb};
    ssize_t res;

    if (file->f_flags & O_NONBLOCK || (iocb->ki_flags & IOCB_NOWAIT))
        msg.msg_flags = MSG_DONTWAIT;

    if (iocb->ki_pos != 0)
        return -ESPIPE;

    if (!iov_iter_count(to))    /* Match SYS5 behaviour */
        return 0;

    res = sock_recvmsg(sock, &msg, msg.msg_flags);
    *to = msg.msg_iter;
    return res;
}

```







```c
size_t copy_page_to_iter(struct page *page, size_t offset, size_t bytes,
             struct iov_iter *i)
{
    if (unlikely(!page_copy_sane(page, offset, bytes)))
        return 0;
    if (i->type & (ITER_BVEC|ITER_KVEC)) {
        void *kaddr = kmap_atomic(page);
        size_t wanted = copy_to_iter(kaddr + offset, bytes, i);
        kunmap_atomic(kaddr);
        return wanted;
    } else if (unlikely(iov_iter_is_discard(i)))
        return bytes;
    else if (likely(!iov_iter_is_pipe(i)))
        return copy_page_to_iter_iovec(page, offset, bytes, i);
    else
        return copy_page_to_iter_pipe(page, offset, bytes, i);
}
EXPORT_SYMBOL(copy_page_to_iter);
```

## write

```c
// fs/read_write.c
SYSCALL_DEFINE3(write, unsigned int, fd, const char __user *, buf,
        size_t, count)
{
    return ksys_write(fd, buf, count);
}

ssize_t ksys_write(unsigned int fd, const char __user *buf, size_t count)
{
    struct fd f = fdget_pos(fd);
    ssize_t ret = -EBADF;

    if (f.file) {
        loff_t pos, *ppos = file_ppos(f.file);
        if (ppos) {
            pos = *ppos;
            ppos = &pos;
        }
        ret = vfs_write(f.file, buf, count, ppos);
        if (ret >= 0 && ppos)
            f.file->f_pos = pos;
        fdput_pos(f);
    }

    return ret;
}
```







```c
ssize_t vfs_write(struct file *file, const char __user *buf, size_t count, loff_t *pos)
{
    ssize_t ret;
    // ...
    ret = rw_verify_area(WRITE, file, pos, count);

    file_start_write(file);
    if (file->f_op->write)
        ret = file->f_op->write(file, buf, count, pos);
    else if (file->f_op->write_iter)
        ret = new_sync_write(file, buf, count, pos);
    else
        ret = -EINVAL;
    if (ret > 0) {
        fsnotify_modify(file);
        add_wchar(current, ret);
    }
    inc_syscw(current);
    file_end_write(file);
    return ret;
}
```





```c

static ssize_t new_sync_write(struct file *filp, const char __user *buf, size_t len, loff_t *ppos)
{
    struct iovec iov = { .iov_base = (void __user *)buf, .iov_len = len };
    struct kiocb kiocb;
    struct iov_iter iter;
    ssize_t ret;

    init_sync_kiocb(&kiocb, filp);
    kiocb.ki_pos = (ppos ? *ppos : 0);
    iov_iter_init(&iter, WRITE, &iov, 1, len);

    ret = call_write_iter(filp, &kiocb, &iter);
    BUG_ON(ret == -EIOCBQUEUED);
    if (ret > 0 && ppos)
        *ppos = kiocb.ki_pos;
    return ret;
}
```



## sendfile

sendfile() copies data between one file descriptor and another.
Because this copying is done within the kernel, sendfile() is more efficient than the combination of * **read** (2)* and  * **write** (2)* , which would require transferring data to and from user space.

```c
// fs/read_write.c


static ssize_t do_sendfile(int out_fd, int in_fd, loff_t *ppos,
		  	   size_t count, loff_t max)
{
	struct fd in, out;
	struct inode *in_inode, *out_inode;
	struct pipe_inode_info *opipe;
	loff_t pos;
	loff_t out_pos;
	ssize_t retval;
	int fl;

	/*
	 * Get input file, and verify that it is ok..
	 */
	retval = -EBADF;
	in = fdget(in_fd);
	if (!in.file)
		goto out;
	if (!(in.file->f_mode & FMODE_READ))
		goto fput_in;
	retval = -ESPIPE;
	if (!ppos) {
		pos = in.file->f_pos;
	} else {
		pos = *ppos;
		if (!(in.file->f_mode & FMODE_PREAD))
			goto fput_in;
	}
	retval = rw_verify_area(READ, in.file, &pos, count);
	if (retval < 0)
		goto fput_in;
	if (count > MAX_RW_COUNT)
		count =  MAX_RW_COUNT;

	/*
	 * Get output file, and verify that it is ok..
	 */
	retval = -EBADF;
	out = fdget(out_fd);
	if (!out.file)
		goto fput_in;
	if (!(out.file->f_mode & FMODE_WRITE))
		goto fput_out;
	in_inode = file_inode(in.file);
	out_inode = file_inode(out.file);
	out_pos = out.file->f_pos;

	if (!max)
		max = min(in_inode->i_sb->s_maxbytes, out_inode->i_sb->s_maxbytes);

	if (unlikely(pos + count > max)) {
		retval = -EOVERFLOW;
		if (pos >= max)
			goto fput_out;
		count = max - pos;
	}

	fl = 0;
#if 0
	/*
	 * We need to debate whether we can enable this or not. The
	 * man page documents EAGAIN return for the output at least,
	 * and the application is arguably buggy if it doesn't expect
	 * EAGAIN on a non-blocking file descriptor.
	 */
	if (in.file->f_flags & O_NONBLOCK)
		fl = SPLICE_F_NONBLOCK;
#endif
	opipe = get_pipe_info(out.file, true);
	if (!opipe) {
		retval = rw_verify_area(WRITE, out.file, &out_pos, count);
		if (retval < 0)
			goto fput_out;
		file_start_write(out.file);
		retval = do_splice_direct(in.file, &pos, out.file, &out_pos,
					  count, fl);
		file_end_write(out.file);
	} else {
		retval = splice_file_to_pipe(in.file, opipe, &pos, count, fl);
	}

	if (retval > 0) {
		add_rchar(current, retval);
		add_wchar(current, retval);
		fsnotify_access(in.file);
		fsnotify_modify(out.file);
		out.file->f_pos = out_pos;
		if (ppos)
			*ppos = pos;
		else
			in.file->f_pos = pos;
	}

	inc_syscr(current);
	inc_syscw(current);
	if (pos > max)
		retval = -EOVERFLOW;

fput_out:
	fdput(out);
fput_in:
	fdput(in);
out:
	return retval;
}

SYSCALL_DEFINE4(sendfile, int, out_fd, int, in_fd, off_t __user *, offset, size_t, count)
{
	loff_t pos;
	off_t off;
	ssize_t ret;

	if (offset) {
		if (unlikely(get_user(off, offset)))
			return -EFAULT;
		pos = off;
		ret = do_sendfile(out_fd, in_fd, &pos, count, MAX_NON_LFS);
		if (unlikely(put_user(pos, offset)))
			return -EFAULT;
		return ret;
	}

	return do_sendfile(out_fd, in_fd, NULL, count, 0);
}
```

### do_splice_direct

splices data directly between two files

- in:		file to splice from
- ppos:	input file offset
- out:	file to splice to
- opos:	output file offset
- len:	number of bytes to splice
- flags:	splice modifier flags

Description:

For use by do_sendfile(). splice can easily emulate sendfile, but doing it in the application would incur an extra system call(splice in + splice out, as compared to just sendfile()). So this helper
can splice directly through a process-private pipe.

```c
// fs/splice.c
long do_splice_direct(struct file *in, loff_t *ppos, struct file *out,
		      loff_t *opos, size_t len, unsigned int flags)
{
	struct splice_desc sd = {
		.len		= len,
		.total_len	= len,
		.flags		= flags,
		.pos		= *ppos,
		.u.file		= out,
		.opos		= opos,
	};
	long ret;

	if (unlikely(!(out->f_mode & FMODE_WRITE)))
		return -EBADF;

	if (unlikely(out->f_flags & O_APPEND))
		return -EINVAL;

	ret = rw_verify_area(WRITE, out, opos, len);
	if (unlikely(ret < 0))
		return ret;

	ret = splice_direct_to_actor(in, &sd, direct_splice_actor);
	if (ret > 0)
		*ppos = sd.pos;

	return ret;
}
```

### splice_direct_to_actor

splices data directly between two non-pipes

- in:		file to splice from
- sd:		actor information on where to splice to
- actor:	handles the data splicing

Description:

This is a special case helper to splice directly between two
points, without requiring an explicit pipe. Internally an allocated
pipe is cached in the process, and reused during the lifetime of
that process.

```c
// fs/splice.c
ssize_t splice_direct_to_actor(struct file *in, struct splice_desc *sd,
			       splice_direct_actor *actor)
{
	struct pipe_inode_info *pipe;
	long ret, bytes;
	umode_t i_mode;
	size_t len;
	int i, flags, more;

	/*
	 * We require the input being a regular file, as we don't want to
	 * randomly drop data for eg socket -> socket splicing. Use the
	 * piped splicing for that!
	 */
	i_mode = file_inode(in)->i_mode;
	if (unlikely(!S_ISREG(i_mode) && !S_ISBLK(i_mode)))
		return -EINVAL;

	/*
	 * neither in nor out is a pipe, setup an internal pipe attached to
	 * 'out' and transfer the wanted data from 'in' to 'out' through that
	 */
	pipe = current->splice_pipe;
	if (unlikely(!pipe)) {
		pipe = alloc_pipe_info();
		if (!pipe)
			return -ENOMEM;

		/*
		 * We don't have an immediate reader, but we'll read the stuff
		 * out of the pipe right after the splice_to_pipe(). So set
		 * PIPE_READERS appropriately.
		 */
		pipe->readers = 1;

		current->splice_pipe = pipe;
	}

	/*
	 * Do the splice.
	 */
	ret = 0;
	bytes = 0;
	len = sd->total_len;
	flags = sd->flags;

	/*
	 * Don't block on output, we have to drain the direct pipe.
	 */
	sd->flags &= ~SPLICE_F_NONBLOCK;
	more = sd->flags & SPLICE_F_MORE;

	WARN_ON_ONCE(!pipe_empty(pipe->head, pipe->tail));

	while (len) {
		size_t read_len;
		loff_t pos = sd->pos, prev_pos = pos;

		ret = do_splice_to(in, &pos, pipe, len, flags);
		if (unlikely(ret <= 0))
			goto out_release;

		read_len = ret;
		sd->total_len = read_len;

		/*
		 * If more data is pending, set SPLICE_F_MORE
		 * If this is the last data and SPLICE_F_MORE was not set
		 * initially, clears it.
		 */
		if (read_len < len)
			sd->flags |= SPLICE_F_MORE;
		else if (!more)
			sd->flags &= ~SPLICE_F_MORE;
		/*
		 * NOTE: nonblocking mode only applies to the input. We
		 * must not do the output in nonblocking mode as then we
		 * could get stuck data in the internal pipe:
		 */
		ret = actor(pipe, sd);
		if (unlikely(ret <= 0)) {
			sd->pos = prev_pos;
			goto out_release;
		}

		bytes += ret;
		len -= ret;
		sd->pos = pos;

		if (ret < read_len) {
			sd->pos = prev_pos + ret;
			goto out_release;
		}
	}

done:
	pipe->tail = pipe->head = 0;
	file_accessed(in);
	return bytes;

out_release:
	/*
	 * If we did an incomplete transfer we must release
	 * the pipe buffers in question:
	 */
	for (i = 0; i < pipe->ring_size; i++) {
		struct pipe_buffer *buf = &pipe->bufs[i];

		if (buf->ops)
			pipe_buf_release(pipe, buf);
	}

	if (!bytes)
		bytes = ret;

	goto done;
}
```

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

sys_select

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

do_sys_poll

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

pollfd

```c
// include/upai/asm-generic/poll.h
struct pollfd {
	int fd;
	short events;
	short revents;
};
```

```c
// include/upai/asm-generic/poll.h

/* These are specified by iBCS2 */
#define POLLIN		0x0001
#define POLLPRI		0x0002
#define POLLOUT		0x0004
#define POLLERR		0x0008
#define POLLHUP		0x0010
#define POLLNVAL	0x0020

/* The rest seem to be more-or-less nonstandard. Check them! */
#define POLLRDNORM	0x0040
#define POLLRDBAND	0x0080
#ifndef POLLWRNORM
#define POLLWRNORM	0x0100
#endif
#ifndef POLLWRBAND
#define POLLWRBAND	0x0200
#endif
#ifndef POLLMSG
#define POLLMSG		0x0400
#endif
#ifndef POLLREMOVE
#define POLLREMOVE	0x1000
#endif
#ifndef POLLRDHUP
#define POLLRDHUP       0x2000
#endif

#define POLLFREE	(__force __poll_t)0x4000	/* currently only for epoll */

#define POLL_BUSY_LOOP	(__force __poll_t)0x8000
```

## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)
- [I/O Multiplexing](/docs/CS/CN/MultiIO.md)

## References

1. [打破砂锅挖到底—— Epoll 多路复用是如何转起来的？](https://mp.weixin.qq.com/s/Py2TE9CdQ92fGLpg-SEj_g)
2. [SYN packet handling in the wild](https://blog.cloudflare.com/syn-packet-handling-in-the-wild/#queuesizelimits)
3. [[内核源码] 网络协议栈 - listen (tcp)](https://wenfh2020.com/2021/07/21/kernel-sys-listen/)
