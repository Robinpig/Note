# IO



## accept

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
// linux/include/linux/net.h
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

## References

1. [打破砂锅挖到底—— Epoll 多路复用是如何转起来的？](https://mp.weixin.qq.com/s/Py2TE9CdQ92fGLpg-SEj_g)