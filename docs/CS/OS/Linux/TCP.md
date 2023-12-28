## Introduction

> See [TCP](/docs/CS/CN/TCP/TCP.md)

TCP sockets are an example of *stream sockets*.

## tcp_init

call tcp_init by [inet_init](/docs/CS/OS/Linux/network.md?id=init-inet)

Size and allocate the main established and bind bucket hash tables.

```c

void __init tcp_init(void)
{
	int max_rshare, max_wshare, cnt;
	unsigned long limit;
	unsigned int i;

	BUILD_BUG_ON(TCP_MIN_SND_MSS <= MAX_TCP_OPTION_SPACE);
	BUILD_BUG_ON(sizeof(struct tcp_skb_cb) >
		     sizeof_field(struct sk_buff, cb));

	percpu_counter_init(&tcp_sockets_allocated, 0, GFP_KERNEL);

	timer_setup(&tcp_orphan_timer, tcp_orphan_update, TIMER_DEFERRABLE);
	mod_timer(&tcp_orphan_timer, jiffies + TCP_ORPHAN_TIMER_PERIOD);

	inet_hashinfo_init(&tcp_hashinfo);
	inet_hashinfo2_init(&tcp_hashinfo, "tcp_listen_portaddr_hash",
			    thash_entries, 21,  /* one slot per 2 MB*/
			    0, 64 * 1024);
	tcp_hashinfo.bind_bucket_cachep =
		kmem_cache_create("tcp_bind_bucket",
				  sizeof(struct inet_bind_bucket), 0,
				  SLAB_HWCACHE_ALIGN | SLAB_PANIC |
				  SLAB_ACCOUNT,
				  NULL);

	tcp_hashinfo.ehash =
		alloc_large_system_hash("TCP established",
					sizeof(struct inet_ehash_bucket),
					thash_entries,
					17, /* one slot per 128 KB of memory */
					0,
					NULL,
					&tcp_hashinfo.ehash_mask,
					0,
					thash_entries ? 0 : 512 * 1024);
	for (i = 0; i <= tcp_hashinfo.ehash_mask; i++)
		INIT_HLIST_NULLS_HEAD(&tcp_hashinfo.ehash[i].chain, i);

	if (inet_ehash_locks_alloc(&tcp_hashinfo))
		panic("TCP: failed to alloc ehash_locks");
	tcp_hashinfo.bhash =
		alloc_large_system_hash("TCP bind",
					sizeof(struct inet_bind_hashbucket),
					tcp_hashinfo.ehash_mask + 1,
					17, /* one slot per 128 KB of memory */
					0,
					&tcp_hashinfo.bhash_size,
					NULL,
					0,
					64 * 1024);
	tcp_hashinfo.bhash_size = 1U << tcp_hashinfo.bhash_size;
	for (i = 0; i < tcp_hashinfo.bhash_size; i++) {
		spin_lock_init(&tcp_hashinfo.bhash[i].lock);
		INIT_HLIST_HEAD(&tcp_hashinfo.bhash[i].chain);
	}


	cnt = tcp_hashinfo.ehash_mask + 1;
	sysctl_tcp_max_orphans = cnt / 2;

	tcp_init_mem();
	/* Set per-socket limits to no more than 1/128 the pressure threshold */
	limit = nr_free_buffer_pages() << (PAGE_SHIFT - 7);
	max_wshare = min(4UL*1024*1024, limit);
	max_rshare = min(6UL*1024*1024, limit);

	init_net.ipv4.sysctl_tcp_wmem[0] = SK_MEM_QUANTUM;
	init_net.ipv4.sysctl_tcp_wmem[1] = 16*1024;
	init_net.ipv4.sysctl_tcp_wmem[2] = max(64*1024, max_wshare);

	init_net.ipv4.sysctl_tcp_rmem[0] = SK_MEM_QUANTUM;
	init_net.ipv4.sysctl_tcp_rmem[1] = 131072;
	init_net.ipv4.sysctl_tcp_rmem[2] = max(131072, max_rshare);

	pr_info("Hash tables configured (established %u bind %u)\n",
		tcp_hashinfo.ehash_mask + 1, tcp_hashinfo.bhash_size);

	tcp_v4_init();
	tcp_metrics_init();
	BUG_ON(tcp_register_congestion_control(&tcp_reno) != 0);
	tcp_tasklet_init();
	mptcp_init();
}
```

set [tasklet](/docs/CS/OS/Linux/Interrupt.md?id=tasklet)

```c
void __init tcp_tasklet_init(void)
{
	int i;

	for_each_possible_cpu(i) {
		struct tsq_tasklet *tsq = &per_cpu(tsq_tasklet, i);

		INIT_LIST_HEAD(&tsq->head);
		tasklet_setup(&tsq->tasklet, tcp_tasklet_func);
	}
}
```

## Usages

Interface for multiple protocols

```c
struct proto tcp_prot = {
       .name                = "TCP",
       .owner               = THIS_MODULE,
       .close               = tcp_close,
       .pre_connect          = tcp_v4_pre_connect,
       .connect              = tcp_v4_connect,
       .disconnect           = tcp_disconnect,
       .accept                      = inet_csk_accept,
       .ioctl               = tcp_ioctl,
       .init                = tcp_v4_init_sock,
       .destroy              = tcp_v4_destroy_sock,
       .shutdown             = tcp_shutdown,
       .setsockopt           = tcp_setsockopt,
       .getsockopt           = tcp_getsockopt,
       .bpf_bypass_getsockopt = tcp_bpf_bypass_getsockopt,
       .keepalive            = tcp_set_keepalive,
       .recvmsg              = tcp_recvmsg,
       .sendmsg              = tcp_sendmsg,
       .sendpage             = tcp_sendpage,
       .backlog_rcv          = tcp_v4_do_rcv,
       .release_cb           = tcp_release_cb,
       .hash                = inet_hash,
       .unhash                      = inet_unhash,
       .get_port             = inet_csk_get_port,
#ifdef CONFIG_BPF_SYSCALL
       .psock_update_sk_prot  = tcp_bpf_update_proto,
#endif
       .enter_memory_pressure = tcp_enter_memory_pressure,
       .leave_memory_pressure = tcp_leave_memory_pressure,
       .stream_memory_free    = tcp_stream_memory_free,
       .sockets_allocated     = &tcp_sockets_allocated,
       .orphan_count         = &tcp_orphan_count,
       .memory_allocated      = &tcp_memory_allocated,
       .memory_pressure       = &tcp_memory_pressure,
       .sysctl_mem           = sysctl_tcp_mem,
       .sysctl_wmem_offset    = offsetof(struct net, ipv4.sysctl_tcp_wmem),
       .sysctl_rmem_offset    = offsetof(struct net, ipv4.sysctl_tcp_rmem),
       .max_header           = MAX_TCP_HEADER,
       .obj_size             = sizeof(struct tcp_sock),
       .slab_flags           = SLAB_TYPESAFE_BY_RCU,
       .twsk_prot            = &tcp_timewait_sock_ops,
       .rsk_prot             = &tcp_request_sock_ops,
       .h.hashinfo           = &tcp_hashinfo,
       .no_autobind          = true,
       .diag_destroy         = tcp_abort,
};
```

## Send

[systemcall send](/docs/CS/OS/Linux/Calls.md?id=send) with TCP protocol -> tcp_sendmsg

push:

- force push when `data size > max_window >> 1`
- or skb == tcp_send_head(sk)

```c
// net/ipv4/tcp.c
int tcp_sendmsg(struct sock *sk, struct msghdr *msg, size_t size)
{
       ret = tcp_sendmsg_locked(sk, msg, size);
}

int tcp_sendmsg_locked(struct sock *sk, struct msghdr *msg, size_t size)
{
    ...
    if (forced_push(tp)) {
        __tcp_push_pending_frames(sk, mss_now, TCP_NAGLE_PUSH);
    } else if (skb == tcp_send_head(sk))
        tcp_push_one(sk, mss_now);
    continue;
}
```

### push

Both `tcp_push_one` and `tcp_push_pending_frames` call tcp_write_xmit

<!-- tabs:start -->

##### **tcp_push_one**

Send _single_ skb sitting at the send head. This function requires true push pending frames to setup probe timer etc.

```c
void tcp_push_one(struct sock *sk, unsigned int mss_now)
{
       struct sk_buff *skb = tcp_send_head(sk);

       tcp_write_xmit(sk, mss_now, TCP_NAGLE_PUSH, 1, sk->sk_allocation);
}
```

##### **__tcp_push_pending_frames**

Push out any pending frames which were held back due to TCP_CORK or attempt at coalescing tiny packets.
The socket must be locked by the caller.

```c
void __tcp_push_pending_frames(struct sock *sk, unsigned int cur_mss,
                            int nonagle)
{
       if (tcp_write_xmit(sk, cur_mss, nonagle, 0,
                        sk_gfp_mask(sk, GFP_ATOMIC)))
              tcp_check_probe_timer(sk);
}
```

<!-- tabs:end -->

#### tcp_write_xmit

This routine writes packets to the network.
It advances the send_head.  This happens as incoming acks open up the remote window for us.

LARGESEND note: !tcp_urg_mode is overkill, only frames between snd_up-64k-mss .. snd_up cannot be large. However, taking into account rare use of URG, this is not a big flaw.

Send at most one packet when push_one > 0.
Temporarily ignore cwnd limit to force at most one packet out when push_one == 2.

Returns true, if no segments are in flight and we have queued segments, but cannot send anything now because of SWS or another problem.

```c
// net/ipv4/tcp_output.c
static bool tcp_write_xmit(struct sock *sk, unsigned int mss_now, int nonagle, ...)
{
       ...
       while ((skb = tcp_send_head(sk))) {
              cwnd_quota = tcp_cwnd_test(tp, skb);
              tcp_snd_wnd_test(tp, skb, mss_now);
              tcp_mss_split_point(sk, skb, mss_now,
                                              min_t(unsigned int,
                                                   cwnd_quota,
                                                   max_segs),
                                              nonagle);

              tso_fragment(sk, skb, limit, mss_now, gfp);

              tcp_transmit_skb(sk, skb, 1, gfp);
       }
       ...
}
```

#### tcp_transmit_skb

This routine actually transmits TCP packets queued in by tcp_do_sendmsg().
This is used by both the initial transmission and possible later retransmissions.

All SKB's seen here are completely headerless.
It is our job to **build the TCP header**, and **pass the packet down to [IP](/docs/CS/OS/Linux/IP.md?id=ip_queue_xmit)** so it can do the same plus pass the packet off to the device.

> [!NOTE]
>
> We are working here with either a clone of the original SKB, or a fresh unique copy made by the retransmit engine.

```c
static int tcp_transmit_skb(struct sock *sk, struct sk_buff *skb, int clone_it, gfp_t gfp_mask)
{
       return __tcp_transmit_skb(sk, skb, clone_it, gfp_mask,
                              tcp_sk(sk)->rcv_nxt);
}

static int __tcp_transmit_skb(struct sock *sk, struct sk_buff *skb, ...)
{
	if (clone_it) {
		TCP_SKB_CB(skb)->tx.in_flight = TCP_SKB_CB(skb)->end_seq
			- tp->snd_una;
		oskb = skb;

		tcp_skb_tsorted_save(oskb) {
			if (unlikely(skb_cloned(oskb)))
				skb = pskb_copy(oskb, gfp_mask);
			else
				skb = skb_clone(oskb, gfp_mask);
		} tcp_skb_tsorted_restore(oskb);
	}

	/* Build TCP header and checksum it. */
	th = (struct tcphdr *)skb->data;
	th->source		= inet->inet_sport;
	th->dest		= inet->inet_dport;
	th->seq			= htonl(tcb->seq);
	th->ack_seq		= htonl(rcv_nxt);

	err = INDIRECT_CALL_INET(icsk->icsk_af_ops->queue_xmit,
				 inet6_csk_xmit, ip_queue_xmit,
				 sk, skb, &inet->cork.fl);
}
```

### FastOpen

tcp_sendmsg_fastopen

```c
static int tcp_sendmsg_fastopen(struct sock *sk, struct msghdr *msg,
                            int *copied, size_t size,
                            struct ubuf_info *uarg)
{
       struct tcp_sock *tp = tcp_sk(sk);
       struct inet_sock *inet = inet_sk(sk);
       struct sockaddr *uaddr = msg->msg_name;
       int err, flags;

       if (!(sock_net(sk)->ipv4.sysctl_tcp_fastopen & TFO_CLIENT_ENABLE) ||
           (uaddr && msg->msg_namelen >= sizeof(uaddr->sa_family) &&
            uaddr->sa_family == AF_UNSPEC))
              return -EOPNOTSUPP;
       if (tp->fastopen_req)
              return -EALREADY; /* Another Fast Open is in progress */

       tp->fastopen_req = kzalloc(sizeof(struct tcp_fastopen_request),
                               sk->sk_allocation);
       if (unlikely(!tp->fastopen_req))
              return -ENOBUFS;
       tp->fastopen_req->data = msg;
       tp->fastopen_req->size = size;
       tp->fastopen_req->uarg = uarg;

       if (inet->defer_connect) {
              err = tcp_connect(sk);
              /* Same failure procedure as in tcp_v4/6_connect */
              if (err) {
                     tcp_set_state(sk, TCP_CLOSE);
                     inet->inet_dport = 0;
                     sk->sk_route_caps = 0;
              }
       }
       flags = (msg->msg_flags & MSG_DONTWAIT) ? O_NONBLOCK : 0;
       err = __inet_stream_connect(sk->sk_socket, uaddr,
                                msg->msg_namelen, flags, 1);
       /* fastopen_req could already be freed in __inet_stream_connect
        * if the connection times out or gets rst
        */
       if (tp->fastopen_req) {
              *copied = tp->fastopen_req->copied;
              tcp_free_fastopen_req(tp);
              inet->defer_connect = 0;
       }
       return err;
}
```

### Window

#### select window

Chose a new window to advertise, update state in tcp_sock for the socket, and return result with RFC1323 scaling applied.
The return value can be stuffed directly into th->window for an outgoing frame.

```c
static u16 tcp_select_window(struct sock *sk)
{
       struct tcp_sock *tp = tcp_sk(sk);
       u32 old_win = tp->rcv_wnd;
       u32 cur_win = tcp_receive_window(tp);
       u32 new_win = __tcp_select_window(sk);

       /* Never shrink the offered window */
       if (new_win < cur_win) {
              /* Danger Will Robinson!
               * Don't update rcv_wup/rcv_wnd here or else
               * we will not be able to advertise a zero
               * window in time.  --DaveM
               *
               * Relax Will Robinson.
               */
              if (new_win == 0)
                     NET_INC_STATS(sock_net(sk),
                                  LINUX_MIB_TCPWANTZEROWINDOWADV);
              new_win = ALIGN(cur_win, 1 << tp->rx_opt.rcv_wscale);
       }
       tp->rcv_wnd = new_win;
       tp->rcv_wup = tp->rcv_nxt;

       /* Make sure we do not exceed the maximum possible
        * scaled window.
        */
       if (!tp->rx_opt.rcv_wscale &&
           sock_net(sk)->ipv4.sysctl_tcp_workaround_signed_windows)
              new_win = min(new_win, MAX_TCP_WINDOW);
       else
              new_win = min(new_win, (65535U << tp->rx_opt.rcv_wscale));

       /* RFC1323 scaling applied */
       new_win >>= tp->rx_opt.rcv_wscale;

       /* If we advertise zero window, disable fast path. */
       if (new_win == 0) {
              tp->pred_flags = 0;
              if (old_win)
                     NET_INC_STATS(sock_net(sk),
                                  LINUX_MIB_TCPTOZEROWINDOWADV);
       } else if (old_win == 0) {
              NET_INC_STATS(sock_net(sk), LINUX_MIB_TCPFROMZEROWINDOWADV);
       }

       return new_win;
}
```

##### __tcp_select_window

This function returns the amount that we can raise the
usable window based on the following constraints

1. The window can never be shrunk once it is offered (RFC 793)
2. We limit memory per socket

RFC 1122:
"the suggested [SWS] avoidance algorithm for the receiver is to keep
RECV.NEXT + RCV.WIN fixed until:
RCV.BUFF - RCV.USER - RCV.WINDOW >= min(1/2 RCV.BUFF, MSS)"

i.e. don't raise the right edge of the window until you can raise
it at least MSS bytes.

Unfortunately, the recommended algorithm breaks header prediction,
since header prediction assumes th->window stays fixed.

Strictly speaking, keeping th->window fixed violates the receiver
side SWS prevention criteria. The problem is that under this rule
a stream of single byte packets will cause the right side of the
window to always advance by a single byte.

Of course, if the sender implements sender side SWS prevention
then this will not be a problem.

BSD seems to make the following compromise:

If the free space is less than the 1/4 of the maximum
space available and the free space is less than 1/2 mss,
then set the window to 0.
[ Actually, bsd uses MSS and 1/4 of maximal _window_ ]
Otherwise, just prevent the window from shrinking
and from being larger than the largest representable value.

This prevents incremental opening of the window in the regime
where TCP is limited by the speed of the reader side taking
data out of the TCP receive queue. It does nothing about
those cases where the window is constrained on the sender side
because the pipeline is full.

BSD also seems to "accidentally" limit itself to windows that are a multiple of MSS, at least until the free space gets quite small. This would appear to be a side effect of the mbuf implementation.
Combining these two algorithms results in the observed behavior of having a fixed window size at almost all times.

Below we obtain similar behavior by forcing the offered window to
a multiple of the mss when it is feasible to do so.

Note, we don't "adjust" for TIMESTAMP or SACK option bytes.
Regular options like TIMESTAMP are taken into account.

```c
u32 __tcp_select_window(struct sock *sk)
{
	struct inet_connection_sock *icsk = inet_csk(sk);
	struct tcp_sock *tp = tcp_sk(sk);
	/* MSS for the peer's data.  Previous versions used mss_clamp
	 * here.  I don't know if the value based on our guesses
	 * of peer's MSS is better for the performance.  It's more correct
	 * but may be worse for the performance because of rcv_mss
	 * fluctuations.  --SAW  1998/11/1
	 */
	int mss = icsk->icsk_ack.rcv_mss;
	int free_space = tcp_space(sk);
	int allowed_space = tcp_full_space(sk);
	int full_space, window;

	if (sk_is_mptcp(sk))
		mptcp_space(sk, &free_space, &allowed_space);

	full_space = min_t(int, tp->window_clamp, allowed_space);

	if (unlikely(mss > full_space)) {
		mss = full_space;
		if (mss <= 0)
			return 0;
	}
	if (free_space < (full_space >> 1)) {
		icsk->icsk_ack.quick = 0;

		if (tcp_under_memory_pressure(sk))
			tp->rcv_ssthresh = min(tp->rcv_ssthresh,
					       4U * tp->advmss);

		/* free_space might become our new window, make sure we don't
		 * increase it due to wscale.
		 */
		free_space = round_down(free_space, 1 << tp->rx_opt.rcv_wscale);

		/* if free space is less than mss estimate, or is below 1/16th
		 * of the maximum allowed, try to move to zero-window, else
		 * tcp_clamp_window() will grow rcv buf up to tcp_rmem[2], and
		 * new incoming data is dropped due to memory limits.
		 * With large window, mss test triggers way too late in order
		 * to announce zero window in time before rmem limit kicks in.
		 */
		if (free_space < (allowed_space >> 4) || free_space < mss)
			return 0;
	}

	if (free_space > tp->rcv_ssthresh)
		free_space = tp->rcv_ssthresh;

	/* Don't do rounding if we are using window scaling, since the
	 * scaled window will not line up with the MSS boundary anyway.
	 */
	if (tp->rx_opt.rcv_wscale) {
		window = free_space;

		/* Advertise enough space so that it won't get scaled away.
		 * Import case: prevent zero window announcement if
		 * 1<<rcv_wscale > mss.
		 */
		window = ALIGN(window, (1 << tp->rx_opt.rcv_wscale));
	} else {
		window = tp->rcv_wnd;
		/* Get the largest window that is a nice multiple of mss.
		 * Window clamp already applied above.
		 * If our current window offering is within 1 mss of the
		 * free space we just keep it. This prevents the divide
		 * and multiply from happening most of the time.
		 * We also don't do any window rounding when the free space
		 * is too small.
		 */
		if (window <= free_space - mss || window > free_space)
			window = rounddown(free_space, mss);
		else if (mss == full_space &&
			 free_space > window + (full_space >> 1))
			window = free_space;
	}

	return window;
}
```

## Recv

### tcp_recvmsg

`recvfrom` -> `inet_recvmsg` -> `tcp_recvmsg`

process sk_receive_queue or sk_wait_data

```c
int tcp_recvmsg(struct sock *sk, struct msghdr *msg, size_t len, int nonblock,
              int flags, int *addr_len)
{
       ret = tcp_recvmsg_locked(sk, msg, len, nonblock, flags, &tss,
                             &cmsg_flags);
}

static int tcp_recvmsg_locked(struct sock *sk, struct msghdr *msg, size_t len, ...)
{
	target = sock_rcvlowat(sk, flags & MSG_WAITALL, len);

	do {
        ...
		skb_queue_walk(&sk->sk_receive_queue, skb);
        ...

            if (copied >= target) {
                /* Do not sleep, just process backlog. */
                release_sock(sk);
                lock_sock(sk);
            } else { /* Wait if none enough data */
                sk_wait_data(sk, &timeo, last);
            }
		}
		...
}
```

#### sk_wait_data

wait for data to arrive at sk_receive_queue

```c
int sk_wait_data(struct sock *sk, long *timeo, const struct sk_buff *skb)
{
    DEFINE_WAIT_FUNC(wait, woken_wake_function);

	add_wait_queue(sk_sleep(sk), &wait);
	sk_set_bit(SOCKWQ_ASYNC_WAITDATA, sk);
	rc = sk_wait_event(sk, timeo, skb_peek_tail(&sk->sk_receive_queue) != skb, &wait);
	sk_clear_bit(SOCKWQ_ASYNC_WAITDATA, sk);
	remove_wait_queue(sk_sleep(sk), &wait);
}
```

### tcp_rcv_established

From dev [ip_local_deliver](/docs/CS/OS/Linux/network.md?id=ip_local_deliver)

```c

int tcp_v4_rcv(struct sk_buff *skb)
{
    ...
	__inet_lookup_skb(&tcp_hashinfo, skb, __tcp_hdrlen(th), th->source,
			       th->dest, sdif, &refcounted);
	...
	if (!sock_owned_by_user(sk)) {
		ret = tcp_v4_do_rcv(sk, skb);
	}
	...
}

// 
int tcp_v4_do_rcv(struct sock *sk, struct sk_buff *skb)
{
    if (sk->sk_state == TCP_ESTABLISHED) { /* Fast path */
        tcp_rcv_established(sk, skb);
    }
    ...
}
```

TCP receive function for the ESTABLISHED state.

1. `tcp_queue_rcv`
2. `tcp_data_ready`

```c
// net/ipv4/tcp_input.c
void tcp_rcv_established(struct sock *sk, struct sk_buff *skb)
{
    ...
    /* Bulk data transfer: receiver */
    __skb_pull(skb, tcp_header_len);
    tcp_queue_rcv(sk, skb, &fragstolen);

    tcp_event_data_recv(sk, skb);
    ...
}
```

#### tcp_queue_rcv

```c

static int __must_check tcp_queue_rcv(struct sock *sk, struct sk_buff *skb,
				      bool *fragstolen)
{
	...
	if (!eaten) {
		__skb_queue_tail(&sk->sk_receive_queue, skb);
		skb_set_owner_r(skb, sk);
	}
	return eaten;
}
```

#### tcp_data_ready

Call [sk_data_ready](/docs/CS/OS/Linux/network.md?id=sk_data_ready)

```c
void tcp_data_ready(struct sock *sk)
{
	if (tcp_epollin_ready(sk, sk->sk_rcvlowat) || sock_flag(sk, SOCK_DONE))
		sk->sk_data_ready(sk);
}
```

## Client Connect

### send ACK

#### tcp_send_ack

This routine sends an ack and also updates the window.

1. return if TCP_CLOSE
2. alloc_skb
3. skb_reserve
4. tcp_init_nondata_skb
5. skb_set_tcp_pure_ack
6. tcp_transmit_skb

```c
void __tcp_send_ack(struct sock *sk, u32 rcv_nxt)
{
	struct sk_buff *buff;

	/* If we have been reset, we may not send again. */
	if (sk->sk_state == TCP_CLOSE)
		return;

	/* We are not putting this on the write queue, so
	 * tcp_transmit_skb() will set the ownership to this
	 * sock.
	 */
	buff = alloc_skb(MAX_TCP_HEADER,
			 sk_gfp_mask(sk, GFP_ATOMIC | __GFP_NOWARN));
	if (unlikely(!buff)) {
		struct inet_connection_sock *icsk = inet_csk(sk);
		unsigned long delay;

		delay = TCP_DELACK_MAX << icsk->icsk_ack.retry;
		if (delay < TCP_RTO_MAX)
			icsk->icsk_ack.retry++;
		inet_csk_schedule_ack(sk);
		icsk->icsk_ack.ato = TCP_ATO_MIN;
		inet_csk_reset_xmit_timer(sk, ICSK_TIME_DACK, delay, TCP_RTO_MAX);
		return;
	}

	/* Reserve space for headers and prepare control bits. */
	skb_reserve(buff, MAX_TCP_HEADER);
	tcp_init_nondata_skb(buff, tcp_acceptable_seq(sk), TCPHDR_ACK);

	/* We do not want pure acks influencing TCP Small Queues or fq/pacing
	 * too much.
	 * SKB_TRUESIZE(max(1 .. 66, MAX_TCP_HEADER)) is unfortunately ~784
	 */
	skb_set_tcp_pure_ack(buff);

	/* Send it off, this clears delayed acks for us. */
	__tcp_transmit_skb(sk, buff, 0, (__force gfp_t)0, rcv_nxt);
}

```

## retry

```c
void tcp_retransmit_timer(struct sock *sk)
{
    ...
  
	if (retransmits_timed_out(sk, net->ipv4.sysctl_tcp_retries1 + 1, 0))
		__sk_dst_reset(sk);
}

/* A write timeout has occurred. Process the after effects. */
static int tcp_write_timeout(struct sock *sk)
{
	struct inet_connection_sock *icsk = inet_csk(sk);
	struct tcp_sock *tp = tcp_sk(sk);
	struct net *net = sock_net(sk);
	bool expired = false, do_reset;
	int retry_until;

	if ((1 << sk->sk_state) & (TCPF_SYN_SENT | TCPF_SYN_RECV)) {
		if (icsk->icsk_retransmits)
			__dst_negative_advice(sk);
		retry_until = icsk->icsk_syn_retries ? : net->ipv4.sysctl_tcp_syn_retries;
		expired = icsk->icsk_retransmits >= retry_until;
	} else {
		if (retransmits_timed_out(sk, net->ipv4.sysctl_tcp_retries1, 0)) {
			/* Black hole detection */
			tcp_mtu_probing(icsk, sk);

			__dst_negative_advice(sk);
		}
		}
```

#### tcp_write_timeout

- if in TCPF_SYN_SENT | TCPF_SYN_RECV,  see `tcp_syn_retries`
- else , `tcp_retries1` tcp_mtu_probing, __dst_negative_advice
- `tcp_retries2`
- if SOCK_DEAD, see`tcp_orphan_retries`

```c

/* A write timeout has occurred. Process the after effects. */
static int tcp_write_timeout(struct sock *sk)
{
	struct inet_connection_sock *icsk = inet_csk(sk);
	struct tcp_sock *tp = tcp_sk(sk);
	struct net *net = sock_net(sk);
	bool expired = false, do_reset;
	int retry_until;

	if ((1 << sk->sk_state) & (TCPF_SYN_SENT | TCPF_SYN_RECV)) {
		if (icsk->icsk_retransmits)
			__dst_negative_advice(sk);
		retry_until = icsk->icsk_syn_retries ? : net->ipv4.sysctl_tcp_syn_retries;
		expired = icsk->icsk_retransmits >= retry_until;
	} else {
		if (retransmits_timed_out(sk, net->ipv4.sysctl_tcp_retries1, 0)) {
			/* Black hole detection */
			tcp_mtu_probing(icsk, sk);

			__dst_negative_advice(sk);
		}

		retry_until = net->ipv4.sysctl_tcp_retries2;
		if (sock_flag(sk, SOCK_DEAD)) {
			const bool alive = icsk->icsk_rto < TCP_RTO_MAX;

			retry_until = tcp_orphan_retries(sk, alive);
			do_reset = alive ||
				!retransmits_timed_out(sk, retry_until, 0);

			if (tcp_out_of_resources(sk, do_reset))
				return 1;
		}
	}
	if (!expired)
		expired = retransmits_timed_out(sk, retry_until,
						icsk->icsk_user_timeout);
	tcp_fastopen_active_detect_blackhole(sk, expired);

	if (BPF_SOCK_OPS_TEST_FLAG(tp, BPF_SOCK_OPS_RTO_CB_FLAG))
		tcp_call_bpf_3arg(sk, BPF_SOCK_OPS_RTO_CB,
				  icsk->icsk_retransmits,
				  icsk->icsk_rto, (int)expired);

	if (expired) {
		/* Has it gone just too far? */
		tcp_write_err(sk);
		return 1;
	}

	if (sk_rethink_txhash(sk)) {
		tp->timeout_rehash++;
		__NET_INC_STATS(sock_net(sk), LINUX_MIB_TCPTIMEOUTREHASH);
	}

	return 0;
}
```

##### retransmits_timed_out

retransmits_timed_out() - returns true if this connection has timed out

- sk:       The current socket
- boundary: max number of retransmissions
- timeout:  A custom timeout value. If set to 0 the default timeout is calculated and used. Using TCP_RTO_MIN and the number of unsuccessful retransmits.

The default "timeout" value this function can calculate and use
is equivalent to the timeout of a TCP Connection
after "boundary" unsuccessful, exponentially backed-off
retransmissions with an initial RTO of TCP_RTO_MIN.

```c
//
static bool retransmits_timed_out(struct sock *sk,
				  unsigned int boundary,
				  unsigned int timeout)
{
	unsigned int start_ts;

	if (!inet_csk(sk)->icsk_retransmits)
		return false;

	start_ts = tcp_sk(sk)->retrans_stamp;
	if (likely(timeout == 0)) {
		unsigned int rto_base = TCP_RTO_MIN;

		if ((1 << sk->sk_state) & (TCPF_SYN_SENT | TCPF_SYN_RECV))
			rto_base = tcp_timeout_init(sk);
		timeout = tcp_model_timeout(sk, boundary, rto_base);
	}

	return (s32)(tcp_time_stamp(tcp_sk(sk)) - start_ts - timeout) >= 0;
}


static unsigned int tcp_model_timeout(struct sock *sk,
				      unsigned int boundary,
				      unsigned int rto_base)
{
	unsigned int linear_backoff_thresh, timeout;

	linear_backoff_thresh = ilog2(TCP_RTO_MAX / rto_base);
	if (boundary <= linear_backoff_thresh)
		timeout = ((2 << boundary) - 1) * rto_base;
	else
		timeout = ((2 << linear_backoff_thresh) - 1) * rto_base +
			(boundary - linear_backoff_thresh) * TCP_RTO_MAX;
	return jiffies_to_msecs(timeout);
}
```

`tcp_retries1` 失败后通知IP层进行MTU探测、刷新路由等流程而不是关闭连接

同样受timeout限制

## Congestion Control

Congestion control is essentially ”feedback-control”

- If senders get acknowledgment of receipt of packets
  - They know if packets are dropped or not
- Based on this, senders can infer the following
  - If packets are not dropped
    − sender is sending at rate lower than the capacity
  - If packets are dropped
    − sender is sending at rate higher than capacity
  - Use drops of packets as “signal of congestion”
  - Change rate as a reaction to packet drop so as to achieve “fair-share”

Drop Detection and Rate-Control are key ideas behind current congestion control protocols.

Current TCP:

- Packet conservation: inject new packet when old packet wave has
  reached destination
- Slow-start: search for capacity starting from zero
- Rate-control: control rate via packet drop feedback, and be “good user"

Sender Algorithm

- Slow Start
- Sliding Window

Receiver Algorithm

- Packet-loss Detection

### State

#### tcp_ca_state

```c

/*
 * Sender's congestion state indicating normal or abnormal situations
 * in the last round of packets sent. The state is driven by the ACK
 * information and timer events.
 */
enum tcp_ca_state {
	/*
	 * Nothing bad has been observed recently.
	 * No apparent reordering, packet loss, or ECN marks.
	 */
	TCP_CA_Open = 0,
#define TCPF_CA_Open	(1<<TCP_CA_Open)
	/*
	 * The sender enters disordered state when it has received DUPACKs or
	 * SACKs in the last round of packets sent. This could be due to packet
	 * loss or reordering but needs further information to confirm packets
	 * have been lost.
	 */
	TCP_CA_Disorder = 1,
#define TCPF_CA_Disorder (1<<TCP_CA_Disorder)
	/*
	 * The sender enters Congestion Window Reduction (CWR) state when it
	 * has received ACKs with ECN-ECE marks, or has experienced congestion
	 * or packet discard on the sender host (e.g. qdisc).
	 */
	TCP_CA_CWR = 2,
#define TCPF_CA_CWR	(1<<TCP_CA_CWR)
	/*
	 * The sender is in fast recovery and retransmitting lost packets,
	 * typically triggered by ACK events.
	 */
	TCP_CA_Recovery = 3,
#define TCPF_CA_Recovery (1<<TCP_CA_Recovery)
	/*
	 * The sender is in loss recovery triggered by retransmission timeout.
	 */
	TCP_CA_Loss = 4
#define TCPF_CA_Loss	(1<<TCP_CA_Loss)
};
```

#### CWR

Enter CWR state. Disable cwnd undo since congestion is proven with ECN

```c

void tcp_enter_cwr(struct sock *sk)
{
	struct tcp_sock *tp = tcp_sk(sk);

	tp->prior_ssthresh = 0;
	if (inet_csk(sk)->icsk_ca_state < TCP_CA_CWR) {
		tp->undo_marker = 0;
		tcp_init_cwnd_reduction(sk);
		tcp_set_ca_state(sk, TCP_CA_CWR);
	}
}
```

#### Loss

```c

void tcp_enter_loss(struct sock *sk)
{
	const struct inet_connection_sock *icsk = inet_csk(sk);
	struct tcp_sock *tp = tcp_sk(sk);
	struct net *net = sock_net(sk);
	bool new_recovery = icsk->icsk_ca_state < TCP_CA_Recovery;

	tcp_timeout_mark_lost(sk);

	/* Reduce ssthresh if it has not yet been made inside this window. */
	if (icsk->icsk_ca_state <= TCP_CA_Disorder ||
	    !after(tp->high_seq, tp->snd_una) ||
	    (icsk->icsk_ca_state == TCP_CA_Loss && !icsk->icsk_retransmits)) {
		tp->prior_ssthresh = tcp_current_ssthresh(sk);
		tp->prior_cwnd = tp->snd_cwnd;
		tp->snd_ssthresh = icsk->icsk_ca_ops->ssthresh(sk);
		tcp_ca_event(sk, CA_EVENT_LOSS);
		tcp_init_undo(tp);
	}
	tp->snd_cwnd	   = tcp_packets_in_flight(tp) + 1;
	tp->snd_cwnd_cnt   = 0;
	tp->snd_cwnd_stamp = tcp_jiffies32;

	/* Timeout in disordered state after receiving substantial DUPACKs
	 * suggests that the degree of reordering is over-estimated.
	 */
	if (icsk->icsk_ca_state <= TCP_CA_Disorder &&
	    tp->sacked_out >= net->ipv4.sysctl_tcp_reordering)
		tp->reordering = min_t(unsigned int, tp->reordering,
				       net->ipv4.sysctl_tcp_reordering);
	tcp_set_ca_state(sk, TCP_CA_Loss);
	tp->high_seq = tp->snd_nxt;
	tcp_ecn_queue_cwr(tp);

	/* F-RTO RFC5682 sec 3.1 step 1: retransmit SND.UNA if no previous
	 * loss recovery is underway except recurring timeout(s) on
	 * the same SND.UNA (sec 3.2). Disable F-RTO on path MTU probing
	 */
	tp->frto = net->ipv4.sysctl_tcp_frto &&
		   (new_recovery || icsk->icsk_retransmits) &&
		   !inet_csk(sk)->icsk_mtup.probe_size;
}
```

### ECN

IP_ECN_set_ce

```c

static inline int IP_ECN_set_ce(struct iphdr *iph)
{
	u32 ecn = (iph->tos + 1) & INET_ECN_MASK;
	__be16 check_add;

	/*
	 * After the last operation we have (in binary):
	 * INET_ECN_NOT_ECT => 01
	 * INET_ECN_ECT_1   => 10
	 * INET_ECN_ECT_0   => 11
	 * INET_ECN_CE      => 00
	 */
	if (!(ecn & 2))
		return !ecn;

	/*
	 * The following gives us:
	 * INET_ECN_ECT_1 => check += htons(0xFFFD)
	 * INET_ECN_ECT_0 => check += htons(0xFFFE)
	 */
	check_add = (__force __be16)((__force u16)htons(0xFFFB) +
				     (__force u16)htons(ecn));

	iph->check = csum16_add(iph->check, check_add);
	iph->tos |= INET_ECN_CE;
	return 1;
}
```

#### tcp_fastretrans_alert

Process an event, which can update packets-in-flight not trivially.

Main goal of this function is to calculate new estimate for left_out, taking into account both packets sitting in receiver's buffer and packets lost by network.

Besides that it updates the congestion state when packet loss or ECN is detected. But it does not reduce the cwnd, it is done by the congestion control later.

It does _not_ decide what to send, it is made in function tcp_xmit_retransmit_queue().

```c

static void tcp_fastretrans_alert(struct sock *sk, const u32 prior_snd_una,
				  int num_dupack, int *ack_flag, int *rexmit)
{
	struct inet_connection_sock *icsk = inet_csk(sk);
	struct tcp_sock *tp = tcp_sk(sk);
	int fast_rexmit = 0, flag = *ack_flag;
	bool ece_ack = flag & FLAG_ECE;
	bool do_lost = num_dupack || ((flag & FLAG_DATA_SACKED) &&
				      tcp_force_fast_retransmit(sk));

	if (!tp->packets_out && tp->sacked_out)
		tp->sacked_out = 0;

	/* Now state machine starts.
	 * A. ECE, hence prohibit cwnd undoing, the reduction is required. */
	if (ece_ack)
		tp->prior_ssthresh = 0;

	/* B. In all the states check for reneging SACKs. */
	if (tcp_check_sack_reneging(sk, flag))
		return;

	/* C. Check consistency of the current state. */
	tcp_verify_left_out(tp);

	/* D. Check state exit conditions. State can be terminated
	 *    when high_seq is ACKed. */
	if (icsk->icsk_ca_state == TCP_CA_Open) {
		WARN_ON(tp->retrans_out != 0 && !tp->syn_data);
		tp->retrans_stamp = 0;
	} else if (!before(tp->snd_una, tp->high_seq)) {
		switch (icsk->icsk_ca_state) {
		case TCP_CA_CWR:
			/* CWR is to be held something *above* high_seq
			 * is ACKed for CWR bit to reach receiver. */
			if (tp->snd_una != tp->high_seq) {
				tcp_end_cwnd_reduction(sk);
				tcp_set_ca_state(sk, TCP_CA_Open);
			}
			break;

		case TCP_CA_Recovery:
			if (tcp_is_reno(tp))
				tcp_reset_reno_sack(tp);
			if (tcp_try_undo_recovery(sk))
				return;
			tcp_end_cwnd_reduction(sk);
			break;
		}
	}

	/* E. Process state. */
	switch (icsk->icsk_ca_state) {
	case TCP_CA_Recovery:
		if (!(flag & FLAG_SND_UNA_ADVANCED)) {
			if (tcp_is_reno(tp))
				tcp_add_reno_sack(sk, num_dupack, ece_ack);
		} else {
			if (tcp_try_undo_partial(sk, prior_snd_una))
				return;
			/* Partial ACK arrived. Force fast retransmit. */
			do_lost = tcp_force_fast_retransmit(sk);
		}
		if (tcp_try_undo_dsack(sk)) {
			tcp_try_keep_open(sk);
			return;
		}
		tcp_identify_packet_loss(sk, ack_flag);
		break;
	case TCP_CA_Loss:
		tcp_process_loss(sk, flag, num_dupack, rexmit);
		tcp_identify_packet_loss(sk, ack_flag);
		if (!(icsk->icsk_ca_state == TCP_CA_Open ||
		      (*ack_flag & FLAG_LOST_RETRANS)))
			return;
		/* Change state if cwnd is undone or retransmits are lost */
		fallthrough;
	default:
		if (tcp_is_reno(tp)) {
			if (flag & FLAG_SND_UNA_ADVANCED)
				tcp_reset_reno_sack(tp);
			tcp_add_reno_sack(sk, num_dupack, ece_ack);
		}

		if (icsk->icsk_ca_state <= TCP_CA_Disorder)
			tcp_try_undo_dsack(sk);

		tcp_identify_packet_loss(sk, ack_flag);
		if (!tcp_time_to_recover(sk, flag)) {
			tcp_try_to_open(sk, flag);
			return;
		}

		/* MTU probe failure: don't reduce cwnd */
		if (icsk->icsk_ca_state < TCP_CA_CWR &&
		    icsk->icsk_mtup.probe_size &&
		    tp->snd_una == tp->mtu_probe.probe_seq_start) {
			tcp_mtup_probe_failed(sk);
			/* Restores the reduction we did in tcp_mtup_probe() */
			tp->snd_cwnd++;
			tcp_simple_retransmit(sk);
			return;
		}

		/* Otherwise enter Recovery state */
		tcp_enter_recovery(sk, ece_ack);
		fast_rexmit = 1;
	}

	if (!tcp_is_rack(sk) && do_lost)
		tcp_update_scoreboard(sk, fast_rexmit);
	*rexmit = REXMIT_LOST;
}
```

### Congestion cControl Interface

```c

struct tcp_congestion_ops {
/* fast path fields are put first to fill one cache line */

	/* return slow start threshold (required) */
	u32 (*ssthresh)(struct sock *sk);

	/* do new cwnd calculation (required) */
	void (*cong_avoid)(struct sock *sk, u32 ack, u32 acked);

	/* call before changing ca_state (optional) */
	void (*set_state)(struct sock *sk, u8 new_state);

	/* call when cwnd event occurs (optional) */
	void (*cwnd_event)(struct sock *sk, enum tcp_ca_event ev);

	/* call when ack arrives (optional) */
	void (*in_ack_event)(struct sock *sk, u32 flags);

	/* hook for packet ack accounting (optional) */
	void (*pkts_acked)(struct sock *sk, const struct ack_sample *sample);

	/* override sysctl_tcp_min_tso_segs */
	u32 (*min_tso_segs)(struct sock *sk);

	/* call when packets are delivered to update cwnd and pacing rate,
	 * after all the ca_state processing. (optional)
	 */
	void (*cong_control)(struct sock *sk, const struct rate_sample *rs);


	/* new value of cwnd after loss (required) */
	u32  (*undo_cwnd)(struct sock *sk);
	/* returns the multiplier used in tcp_sndbuf_expand (optional) */
	u32 (*sndbuf_expand)(struct sock *sk);

/* control/slow paths put last */
	/* get info for inet_diag (optional) */
	size_t (*get_info)(struct sock *sk, u32 ext, int *attr,
			   union tcp_cc_info *info);

	char 			name[TCP_CA_NAME_MAX];
	struct module		*owner;
	struct list_head	list;
	u32			key;
	u32			flags;

	/* initialize private data (optional) */
	void (*init)(struct sock *sk);
	/* cleanup private data  (optional) */
	void (*release)(struct sock *sk);
} ____cacheline_aligned_in_smp;

```

Events passed to congestion control interface

```c

enum tcp_ca_event {
	CA_EVENT_TX_START,	/* first transmit when no packets in flight */
	CA_EVENT_CWND_RESTART,	/* congestion window restart */
	CA_EVENT_COMPLETE_CWR,	/* end of congestion recovery */
	CA_EVENT_LOSS,		/* loss timeout */
	CA_EVENT_ECN_NO_CE,	/* ECT set, but not CE marked */
	CA_EVENT_ECN_IS_CE,	/* received CE marked IP packet */
};
```

Information about inbound ACK, passed to cong_ops->in_ack_event()

```c

enum tcp_ca_ack_event_flags {
	CA_ACK_SLOWPATH		= (1 << 0),	/* In slow path processing */
	CA_ACK_WIN_UPDATE	= (1 << 1),	/* ACK updated window */
	CA_ACK_ECE		= (1 << 2),	/* ECE bit is set on ack */
};
```

Attach new congestion control algorithm to the list of available options.

```c

int tcp_register_congestion_control(struct tcp_congestion_ops *ca)
{
	int ret = 0;

	/* all algorithms must implement these */
	if (!ca->ssthresh || !ca->undo_cwnd ||
	    !(ca->cong_avoid || ca->cong_control)) {
		pr_err("%s does not implement required ops\n", ca->name);
		return -EINVAL;
	}

	ca->key = jhash(ca->name, sizeof(ca->name), strlen(ca->name));

	spin_lock(&tcp_cong_list_lock);
	if (ca->key == TCP_CA_UNSPEC || tcp_ca_find_key(ca->key)) {
		pr_notice("%s already registered or non-unique key\n",
			  ca->name);
		ret = -EEXIST;
	} else {
		list_add_tail_rcu(&ca->list, &tcp_cong_list);
		pr_debug("%s registered\n", ca->name);
	}
	spin_unlock(&tcp_cong_list_lock);

	return ret;
}
```

Remove congestion control algorithm, called from the module's remove function.  Module ref counts are used to ensure that this can't be done till all sockets using that method are closed.

```c
void tcp_unregister_congestion_control(struct tcp_congestion_ops *ca)
{
	spin_lock(&tcp_cong_list_lock);
	list_del_rcu(&ca->list);
	spin_unlock(&tcp_cong_list_lock);

	/* Wait for outstanding readers to complete before the
	 * module gets removed entirely.
	 *
	 * A try_module_get() should fail by now as our module is
	 * in "going" state since no refs are held anymore and
	 * module_exit() handler being called.
	 */
	synchronize_rcu();
}
```

### CUBIC

```c

static int __init cubictcp_register(void)
{
	BUILD_BUG_ON(sizeof(struct bictcp) > ICSK_CA_PRIV_SIZE);

	/* Precompute a bunch of the scaling factors that are used per-packet
	 * based on SRTT of 100ms
	 */

	beta_scale = 8*(BICTCP_BETA_SCALE+beta) / 3
		/ (BICTCP_BETA_SCALE - beta);

	cube_rtt_scale = (bic_scale * 10);	/* 1024*c/rtt */

	/* calculate the "K" for (wmax-cwnd) = c/rtt * K^3
	 *  so K = cubic_root( (wmax-cwnd)*rtt/c )
	 * the unit of K is bictcp_HZ=2^10, not HZ
	 *
	 *  c = bic_scale >> 10
	 *  rtt = 100ms
	 *
	 * the following code has been designed and tested for
	 * cwnd < 1 million packets
	 * RTT < 100 seconds
	 * HZ < 1,000,00  (corresponding to 10 nano-second)
	 */

	/* 1/c * 2^2*bictcp_HZ * srtt */
	cube_factor = 1ull << (10+3*BICTCP_HZ); /* 2^40 */

	/* divide by bic_scale and by constant Srtt (100ms) */
	do_div(cube_factor, bic_scale * 10);

	return tcp_register_congestion_control(&cubictcp);
}
```

```c
static struct tcp_congestion_ops cubictcp __read_mostly = {
	.init		= cubictcp_init,
	.ssthresh	= cubictcp_recalc_ssthresh,
	.cong_avoid	= cubictcp_cong_avoid,
	.set_state	= cubictcp_state,
	.undo_cwnd	= tcp_reno_undo_cwnd,
	.cwnd_event	= cubictcp_cwnd_event,
	.pkts_acked     = cubictcp_acked,
	.owner		= THIS_MODULE,
	.name		= "cubic",
};
```

cubictcp_init

```c

static void cubictcp_init(struct sock *sk)
{
	struct bictcp *ca = inet_csk_ca(sk);

	bictcp_reset(ca);

	if (hystart)
		bictcp_hystart_reset(sk);

	if (!hystart && initial_ssthresh)
		tcp_sk(sk)->snd_ssthresh = initial_ssthresh;
}
```

cubictcp_cong_avoid

```c
static void cubictcp_cong_avoid(struct sock *sk, u32 ack, u32 acked)
{
struct tcp_sock *tp = tcp_sk(sk);
struct bictcp *ca = inet_csk_ca(sk);

	if (!tcp_is_cwnd_limited(sk))
		return;

	if (tcp_in_slow_start(tp)) {
		if (hystart && after(ack, ca->end_seq))
			bictcp_hystart_reset(sk);
		acked = tcp_slow_start(tp, acked);
		if (!acked)
			return;
	}
	bictcp_update(ca, tp->snd_cwnd, acked);
	tcp_cong_avoid_ai(tp, ca->cnt, acked);
}
```

Compute congestion window to use.

```c

static inline void bictcp_update(struct bictcp *ca, u32 cwnd, u32 acked)
{
	u32 delta, bic_target, max_cnt;
	u64 offs, t;

	ca->ack_cnt += acked;	/* count the number of ACKed packets */

	if (ca->last_cwnd == cwnd &&
	    (s32)(tcp_jiffies32 - ca->last_time) <= HZ / 32)
		return;

	/* The CUBIC function can update ca->cnt at most once per jiffy.
	 * On all cwnd reduction events, ca->epoch_start is set to 0,
	 * which will force a recalculation of ca->cnt.
	 */
	if (ca->epoch_start && tcp_jiffies32 == ca->last_time)
		goto tcp_friendliness;

	ca->last_cwnd = cwnd;
	ca->last_time = tcp_jiffies32;

	if (ca->epoch_start == 0) {
		ca->epoch_start = tcp_jiffies32;	/* record beginning */
		ca->ack_cnt = acked;			/* start counting */
		ca->tcp_cwnd = cwnd;			/* syn with cubic */

		if (ca->last_max_cwnd <= cwnd) {
			ca->bic_K = 0;
			ca->bic_origin_point = cwnd;
		} else {
			/* Compute new K based on
			 * (wmax-cwnd) * (srtt>>3 / HZ) / c * 2^(3*bictcp_HZ)
			 */
			ca->bic_K = cubic_root(cube_factor
					       * (ca->last_max_cwnd - cwnd));
			ca->bic_origin_point = ca->last_max_cwnd;
		}
	}

	/* cubic function - calc*/
	/* calculate c * time^3 / rtt,
	 *  while considering overflow in calculation of time^3
	 * (so time^3 is done by using 64 bit)
	 * and without the support of division of 64bit numbers
	 * (so all divisions are done by using 32 bit)
	 *  also NOTE the unit of those veriables
	 *	  time  = (t - K) / 2^bictcp_HZ
	 *	  c = bic_scale >> 10
	 * rtt  = (srtt >> 3) / HZ
	 * !!! The following code does not have overflow problems,
	 * if the cwnd < 1 million packets !!!
	 */

	t = (s32)(tcp_jiffies32 - ca->epoch_start);
	t += usecs_to_jiffies(ca->delay_min);
	/* change the unit from HZ to bictcp_HZ */
	t <<= BICTCP_HZ;
	do_div(t, HZ);

	if (t < ca->bic_K)		/* t - K */
		offs = ca->bic_K - t;
	else
		offs = t - ca->bic_K;

	/* c/rtt * (t-K)^3 */
	delta = (cube_rtt_scale * offs * offs * offs) >> (10+3*BICTCP_HZ);
	if (t < ca->bic_K)                            /* below origin*/
		bic_target = ca->bic_origin_point - delta;
	else                                          /* above origin*/
		bic_target = ca->bic_origin_point + delta;

	/* cubic function - calc bictcp_cnt*/
	if (bic_target > cwnd) {
		ca->cnt = cwnd / (bic_target - cwnd);
	} else {
		ca->cnt = 100 * cwnd;              /* very small increment*/
	}

	/*
	 * The initial growth of cubic function may be too conservative
	 * when the available bandwidth is still unknown.
	 */
	if (ca->last_max_cwnd == 0 && ca->cnt > 20)
		ca->cnt = 20;	/* increase cwnd 5% per RTT */

tcp_friendliness:
	/* TCP Friendly */
	if (tcp_friendliness) {
		u32 scale = beta_scale;

		delta = (cwnd * scale) >> 3;
		while (ca->ack_cnt > delta) {		/* update tcp cwnd */
			ca->ack_cnt -= delta;
			ca->tcp_cwnd++;
		}

		if (ca->tcp_cwnd > cwnd) {	/* if bic is slower than tcp */
			delta = ca->tcp_cwnd - cwnd;
			max_cnt = cwnd / delta;
			if (ca->cnt > max_cnt)
				ca->cnt = max_cnt;
		}
	}

	/* The maximum rate of cwnd increase CUBIC allows is 1 packet per
	 * 2 packets ACKed, meaning cwnd grows at 1.5x per RTT.
	 */
	ca->cnt = max(ca->cnt, 2U);
}
```

## Shutdown

### tcp_shutdown

Shutdown the sending side of a connection. Much like close except that we don't receive shut down or sock_set_flag(sk, SOCK_DEAD).

```c

void tcp_shutdown(struct sock *sk, int how)
{
	/*	We need to grab some memory, and put together a FIN,
	 *	and then put it into the queue to be sent.
	 *		Tim MacKenzie(tym@dibbler.cs.monash.edu.au) 4 Dec '92.
	 */
	if (!(how & SEND_SHUTDOWN))
		return;

	/* If we've already sent a FIN, or it's a closed state, skip this. */
	if ((1 << sk->sk_state) &
	    (TCPF_ESTABLISHED | TCPF_SYN_SENT |
	     TCPF_SYN_RECV | TCPF_CLOSE_WAIT)) {
		/* Clear out any half completed packets.  FIN if needed. */
		if (tcp_close_state(sk))
			tcp_send_fin(sk);
	}
}
```

## Active Close

### send FIN

#### tcp_close

```c

void tcp_close(struct sock *sk, long timeout)
{
	lock_sock(sk);
	__tcp_close(sk, timeout);
	release_sock(sk);
	sock_put(sk);
}


void __tcp_close(struct sock *sk, long timeout)
{
	struct sk_buff *skb;
	int data_was_unread = 0;
	int state;

	sk->sk_shutdown = SHUTDOWN_MASK;

	if (sk->sk_state == TCP_LISTEN) {
		tcp_set_state(sk, TCP_CLOSE);

		/* Special case. */
		inet_csk_listen_stop(sk);

		goto adjudge_to_death;
	}

	/*  We need to flush the recv. buffs.  We do this only on the
	 *  descriptor close, not protocol-sourced closes, because the
	 *  reader process may not have drained the data yet!
	 */
	while ((skb = __skb_dequeue(&sk->sk_receive_queue)) != NULL) {
		u32 len = TCP_SKB_CB(skb)->end_seq - TCP_SKB_CB(skb)->seq;

		if (TCP_SKB_CB(skb)->tcp_flags & TCPHDR_FIN)
			len--;
		data_was_unread += len;
		__kfree_skb(skb);
	}

	sk_mem_reclaim(sk);

	/* If socket has been already reset (e.g. in tcp_reset()) - kill it. */
	if (sk->sk_state == TCP_CLOSE)
		goto adjudge_to_death;

	/* As outlined in RFC 2525, section 2.17, we send a RST here because
	 * data was lost. To witness the awful effects of the old behavior of
	 * always doing a FIN, run an older 2.1.x kernel or 2.0.x, start a bulk
	 * GET in an FTP client, suspend the process, wait for the client to
	 * advertise a zero window, then kill -9 the FTP client, wheee...
	 * Note: timeout is always zero in such a case.
	 */
	if (unlikely(tcp_sk(sk)->repair)) {
		sk->sk_prot->disconnect(sk, 0);
	} else if (data_was_unread) {
		/* Unread data was tossed, zap the connection. */
		NET_INC_STATS(sock_net(sk), LINUX_MIB_TCPABORTONCLOSE);
		tcp_set_state(sk, TCP_CLOSE);
		tcp_send_active_reset(sk, sk->sk_allocation);
	} else if (sock_flag(sk, SOCK_LINGER) && !sk->sk_lingertime) {
		/* Check zero linger _after_ checking for unread data. */
		sk->sk_prot->disconnect(sk, 0);
		NET_INC_STATS(sock_net(sk), LINUX_MIB_TCPABORTONDATA);
	} else if (tcp_close_state(sk)) {
		/* We FIN if the application ate all the data before
		 * zapping the connection.
		 */

		/* RED-PEN. Formally speaking, we have broken TCP state
		 * machine. State transitions:
		 *
		 * TCP_ESTABLISHED -> TCP_FIN_WAIT1
		 * TCP_SYN_RECV	-> TCP_FIN_WAIT1 (forget it, it's impossible)
		 * TCP_CLOSE_WAIT -> TCP_LAST_ACK
		 *
		 * are legal only when FIN has been sent (i.e. in window),
		 * rather than queued out of window. Purists blame.
		 *
		 * F.e. "RFC state" is ESTABLISHED,
		 * if Linux state is FIN-WAIT-1, but FIN is still not sent.
		 *
		 * The visible declinations are that sometimes
		 * we enter time-wait state, when it is not required really
		 * (harmless), do not send active resets, when they are
		 * required by specs (TCP_ESTABLISHED, TCP_CLOSE_WAIT, when
		 * they look as CLOSING or LAST_ACK for Linux)
		 * Probably, I missed some more holelets.
		 * 						--ANK
		 * XXX (TFO) - To start off we don't support SYN+ACK+FIN
		 * in a single packet! (May consider it later but will
		 * probably need API support or TCP_CORK SYN-ACK until
		 * data is written and socket is closed.)
		 */
		tcp_send_fin(sk);
	}

	sk_stream_wait_close(sk, timeout);

adjudge_to_death:
	state = sk->sk_state;
	sock_hold(sk);
	sock_orphan(sk);

	local_bh_disable();
	bh_lock_sock(sk);
	/* remove backlog if any, without releasing ownership. */
	__release_sock(sk);

	percpu_counter_inc(sk->sk_prot->orphan_count);

	/* Have we already been destroyed by a softirq or backlog? */
	if (state != TCP_CLOSE && sk->sk_state == TCP_CLOSE)
		goto out;

	/*	This is a (useful) BSD violating of the RFC. There is a
	 *	problem with TCP as specified in that the other end could
	 *	keep a socket open forever with no application left this end.
	 *	We use a 1 minute timeout (about the same as BSD) then kill
	 *	our end. If they send after that then tough - BUT: long enough
	 *	that we won't make the old 4*rto = almost no time - whoops
	 *	reset mistake.
	 *
	 *	Nope, it was not mistake. It is really desired behaviour
	 *	f.e. on http servers, when such sockets are useless, but
	 *	consume significant resources. Let's do it with special
	 *	linger2	option.					--ANK
	 */

	if (sk->sk_state == TCP_FIN_WAIT2) {
		struct tcp_sock *tp = tcp_sk(sk);
		if (tp->linger2 < 0) {
			tcp_set_state(sk, TCP_CLOSE);
			tcp_send_active_reset(sk, GFP_ATOMIC);
			__NET_INC_STATS(sock_net(sk),
					LINUX_MIB_TCPABORTONLINGER);
		} else {
			const int tmo = tcp_fin_time(sk);

			if (tmo > TCP_TIMEWAIT_LEN) {
				inet_csk_reset_keepalive_timer(sk,
						tmo - TCP_TIMEWAIT_LEN);
			} else {
				tcp_time_wait(sk, TCP_FIN_WAIT2, tmo);
				goto out;
			}
		}
	}
	if (sk->sk_state != TCP_CLOSE) {
		sk_mem_reclaim(sk);
		if (tcp_check_oom(sk, 0)) {
			tcp_set_state(sk, TCP_CLOSE);
			tcp_send_active_reset(sk, GFP_ATOMIC);
			__NET_INC_STATS(sock_net(sk),
					LINUX_MIB_TCPABORTONMEMORY);
		} else if (!check_net(sock_net(sk))) {
			/* Not possible to send reset; just close */
			tcp_set_state(sk, TCP_CLOSE);
		}
	}

	if (sk->sk_state == TCP_CLOSE) {
		struct request_sock *req;

		req = rcu_dereference_protected(tcp_sk(sk)->fastopen_rsk,
						lockdep_sock_is_held(sk));
		/* We could get here with a non-NULL req if the socket is
		 * aborted (e.g., closed with unread data) before 3WHS
		 * finishes.
		 */
		if (req)
			reqsk_fastopen_remove(sk, req, false);
		inet_csk_destroy_sock(sk);
	}
	/* Otherwise, socket is reprieved until protocol close. */

out:
	bh_unlock_sock(sk);
	local_bh_enable();
}

```

#### tcp_send_fin

Send a FIN. The caller locks the socket for us.

We should try to send a FIN packet really hard, but eventually give up.

```c

void tcp_send_fin(struct sock *sk)
{
	struct sk_buff *skb, *tskb, *tail = tcp_write_queue_tail(sk);
	struct tcp_sock *tp = tcp_sk(sk);

	/* Optimization, tack on the FIN if we have one skb in write queue and
	 * this skb was not yet sent, or we are under memory pressure.
	 * Note: in the latter case, FIN packet will be sent after a timeout,
	 * as TCP stack thinks it has already been transmitted.
	 */
	tskb = tail;
	if (!tskb && tcp_under_memory_pressure(sk))
		tskb = skb_rb_last(&sk->tcp_rtx_queue);

	if (tskb) {
		TCP_SKB_CB(tskb)->tcp_flags |= TCPHDR_FIN;
		TCP_SKB_CB(tskb)->end_seq++;
		tp->write_seq++;
		if (!tail) {
			/* This means tskb was already sent.
			 * Pretend we included the FIN on previous transmit.
			 * We need to set tp->snd_nxt to the value it would have
			 * if FIN had been sent. This is because retransmit path
			 * does not change tp->snd_nxt.
			 */
			WRITE_ONCE(tp->snd_nxt, tp->snd_nxt + 1);
			return;
		}
	} else {
		skb = alloc_skb_fclone(MAX_TCP_HEADER, sk->sk_allocation);
		if (unlikely(!skb))
			return;

		INIT_LIST_HEAD(&skb->tcp_tsorted_anchor);
		skb_reserve(skb, MAX_TCP_HEADER);
		sk_forced_mem_schedule(sk, skb->truesize);
		/* FIN eats a sequence byte, write_seq advanced by tcp_queue_skb(). */
		tcp_init_nondata_skb(skb, tp->write_seq,
				     TCPHDR_ACK | TCPHDR_FIN);
		tcp_queue_skb(sk, skb);
	}
	__tcp_push_pending_frames(sk, tcp_current_mss(sk), TCP_NAGLE_OFF);
}
```

### rcv ACK

see [tcp_rcv_state_process](/docs/CS/OS/Linux/TCP.md?id=tcp_rcv_state_process)

#### tcp_time_wait

Move a socket to time-wait or dead fin-wait-2 state.

```c

void tcp_time_wait(struct sock *sk, int state, int timeo)
{
	const struct inet_connection_sock *icsk = inet_csk(sk);
	const struct tcp_sock *tp = tcp_sk(sk);
	struct inet_timewait_sock *tw;
	struct inet_timewait_death_row *tcp_death_row = &sock_net(sk)->ipv4.tcp_death_row;

	tw = inet_twsk_alloc(sk, tcp_death_row, state);

	if (tw) {
		struct tcp_timewait_sock *tcptw = tcp_twsk((struct sock *)tw);
		const int rto = (icsk->icsk_rto << 2) - (icsk->icsk_rto >> 1);
		struct inet_sock *inet = inet_sk(sk);

		tw->tw_transparent	= inet->transparent;
		tw->tw_mark		= sk->sk_mark;
		tw->tw_priority		= sk->sk_priority;
		tw->tw_rcv_wscale	= tp->rx_opt.rcv_wscale;
		tcptw->tw_rcv_nxt	= tp->rcv_nxt;
		tcptw->tw_snd_nxt	= tp->snd_nxt;
		tcptw->tw_rcv_wnd	= tcp_receive_window(tp);
		tcptw->tw_ts_recent	= tp->rx_opt.ts_recent;
		tcptw->tw_ts_recent_stamp = tp->rx_opt.ts_recent_stamp;
		tcptw->tw_ts_offset	= tp->tsoffset;
		tcptw->tw_last_oow_ack_time = 0;
		tcptw->tw_tx_delay	= tp->tcp_tx_delay;
#if IS_ENABLED(CONFIG_IPV6)
		if (tw->tw_family == PF_INET6) {
			struct ipv6_pinfo *np = inet6_sk(sk);

			tw->tw_v6_daddr = sk->sk_v6_daddr;
			tw->tw_v6_rcv_saddr = sk->sk_v6_rcv_saddr;
			tw->tw_tclass = np->tclass;
			tw->tw_flowlabel = be32_to_cpu(np->flow_label & IPV6_FLOWLABEL_MASK);
			tw->tw_txhash = sk->sk_txhash;
			tw->tw_ipv6only = sk->sk_ipv6only;
		}
#endif

#ifdef CONFIG_TCP_MD5SIG
		/*
		 * The timewait bucket does not have the key DB from the
		 * sock structure. We just make a quick copy of the
		 * md5 key being used (if indeed we are using one)
		 * so the timewait ack generating code has the key.
		 */
		do {
			tcptw->tw_md5_key = NULL;
			if (static_branch_unlikely(&tcp_md5_needed)) {
				struct tcp_md5sig_key *key;

				key = tp->af_specific->md5_lookup(sk, sk);
				if (key) {
					tcptw->tw_md5_key = kmemdup(key, sizeof(*key), GFP_ATOMIC);
					BUG_ON(tcptw->tw_md5_key && !tcp_alloc_md5sig_pool());
				}
			}
		} while (0);
#endif

		/* Get the TIME_WAIT timeout firing. */
		if (timeo < rto)
			timeo = rto;

		if (state == TCP_TIME_WAIT)
			timeo = TCP_TIMEWAIT_LEN;

		/* tw_timer is pinned, so we need to make sure BH are disabled
		 * in following section, otherwise timer handler could run before
		 * we complete the initialization.
		 */
		local_bh_disable();
		inet_twsk_schedule(tw, timeo);
		/* Linkage updates.
		 * Note that access to tw after this point is illegal.
		 */
		inet_twsk_hashdance(tw, sk, &tcp_hashinfo);
		local_bh_enable();
	} else {
		/* Sorry, if we're out of memory, just CLOSE this
		 * socket up.  We've got bigger problems than
		 * non-graceful socket closings.
		 */
		NET_INC_STATS(sock_net(sk), LINUX_MIB_TCPTIMEWAITOVERFLOW);
	}

	tcp_update_metrics(sk);
	tcp_done(sk);
}
```

### rcv FIN

#### tcp_timewait_state_process

Main purpose of TIME-WAIT state is to close connection gracefully,
when one of ends sits in LAST-ACK or CLOSING retransmitting FIN
(and, probably, tail of data) and one or more our ACKs are lost.

What is TIME-WAIT timeout? It is associated with maximal packet
lifetime in the internet, which results in wrong conclusion, that
it is set to catch "old duplicate segments" wandering out of their path.
It is not quite correct. This timeout is calculated so that it exceeds
maximal retransmission timeout enough to allow to lose one (or more)
segments sent by peer and our ACKs. This time may be calculated from RTO.

When TIME-WAIT socket receives RST, it means that another end
finally closed and we are allowed to kill TIME-WAIT too.

Second purpose of TIME-WAIT is catching old duplicate segments.
Well, certainly it is pure paranoia, but if we load TIME-WAIT
with this semantics, we MUST NOT kill TIME-WAIT state with RSTs.

If we invented some more clever way to catch duplicates
(f.e. based on PAWS), we could truncate TIME-WAIT to several RTOs.
The algorithm below is based on FORMAL INTERPRETATION of RFCs.
When you compare it to RFCs, please, read section SEGMENT ARRIVES
from the very beginning.

NOTE. With recycling (and later with fin-wait-2) TW bucket
is _not_ stateless. It means, that strictly speaking we must
spinlock it. I do not want! Well, probability of misbehaviour
is ridiculously low and, seems, we could use some mb() tricks
to avoid misread sequence numbers, states etc.  --ANK

We don't need to initialize tmp_out.sack_ok as we don't use the results

```c
tcp_timewait_state_process(struct inet_timewait_sock *tw, struct sk_buff *skb,
			   const struct tcphdr *th)
{
	struct tcp_options_received tmp_opt;
	struct tcp_timewait_sock *tcptw = tcp_twsk((struct sock *)tw);
	bool paws_reject = false;

	tmp_opt.saw_tstamp = 0;
	if (th->doff > (sizeof(*th) >> 2) && tcptw->tw_ts_recent_stamp) {
		tcp_parse_options(twsk_net(tw), skb, &tmp_opt, 0, NULL);

		if (tmp_opt.saw_tstamp) {
			if (tmp_opt.rcv_tsecr)
				tmp_opt.rcv_tsecr -= tcptw->tw_ts_offset;
			tmp_opt.ts_recent	= tcptw->tw_ts_recent;
			tmp_opt.ts_recent_stamp	= tcptw->tw_ts_recent_stamp;
			paws_reject = tcp_paws_reject(&tmp_opt, th->rst);
		}
	}

	if (tw->tw_substate == TCP_FIN_WAIT2) {
		/* Just repeat all the checks of tcp_rcv_state_process() */

		/* Out of window, send ACK */
		if (paws_reject ||
		    !tcp_in_window(TCP_SKB_CB(skb)->seq, TCP_SKB_CB(skb)->end_seq,
				   tcptw->tw_rcv_nxt,
				   tcptw->tw_rcv_nxt + tcptw->tw_rcv_wnd))
			return tcp_timewait_check_oow_rate_limit(
				tw, skb, LINUX_MIB_TCPACKSKIPPEDFINWAIT2);

		if (th->rst)
			goto kill;

		if (th->syn && !before(TCP_SKB_CB(skb)->seq, tcptw->tw_rcv_nxt))
			return TCP_TW_RST;

		/* Dup ACK? */
		if (!th->ack ||
		    !after(TCP_SKB_CB(skb)->end_seq, tcptw->tw_rcv_nxt) ||
		    TCP_SKB_CB(skb)->end_seq == TCP_SKB_CB(skb)->seq) {
			inet_twsk_put(tw);
			return TCP_TW_SUCCESS;
		}

		/* New data or FIN. If new data arrive after half-duplex close,
		 * reset.
		 */
		if (!th->fin ||
		    TCP_SKB_CB(skb)->end_seq != tcptw->tw_rcv_nxt + 1)
			return TCP_TW_RST;

		/* FIN arrived, enter true time-wait state. */
		tw->tw_substate	  = TCP_TIME_WAIT;
		tcptw->tw_rcv_nxt = TCP_SKB_CB(skb)->end_seq;
		if (tmp_opt.saw_tstamp) {
			tcptw->tw_ts_recent_stamp = ktime_get_seconds();
			tcptw->tw_ts_recent	  = tmp_opt.rcv_tsval;
		}

		inet_twsk_reschedule(tw, TCP_TIMEWAIT_LEN);
		return TCP_TW_ACK;
	}
```

Now real TIME-WAIT state.

RFC 1122:
"When a connection is [...] on TIME-WAIT state [...]
[a TCP] MAY accept a new SYN from the remote TCP to
reopen the connection directly, if it:

1. assigns its initial sequence number for the new
   connection to be larger than the largest sequence
   number it used on the previous connection incarnation,
   and
2. returns to TIME-WAIT state if the SYN turns out
   to be an old duplicate".

if sysctl_tcp_rfc1337 enable, ignore RST

```c
	if (!paws_reject &&
	    (TCP_SKB_CB(skb)->seq == tcptw->tw_rcv_nxt &&
	     (TCP_SKB_CB(skb)->seq == TCP_SKB_CB(skb)->end_seq || th->rst))) {
		/* In window segment, it may be only reset or bare ack. */

		if (th->rst) {
			/* This is TIME_WAIT assassination, in two flavors.
			 * Oh well... nobody has a sufficient solution to this
			 * protocol bug yet.
			 */
			if (twsk_net(tw)->ipv4.sysctl_tcp_rfc1337 == 0) {
kill:
				inet_twsk_deschedule_put(tw);
				return TCP_TW_SUCCESS;
			}
		} else {
			inet_twsk_reschedule(tw, TCP_TIMEWAIT_LEN);
		}

		if (tmp_opt.saw_tstamp) {
			tcptw->tw_ts_recent	  = tmp_opt.rcv_tsval;
			tcptw->tw_ts_recent_stamp = ktime_get_seconds();
		}

		inet_twsk_put(tw);
		return TCP_TW_SUCCESS;
	}

	/* Out of window segment.

	   All the segments are ACKed immediately.

	   The only exception is new SYN. We accept it, if it is
	   not old duplicate and we are not in danger to be killed
	   by delayed old duplicates. RFC check is that it has
	   newer sequence number works at rates <40Mbit/sec.
	   However, if paws works, it is reliable AND even more,
	   we even may relax silly seq space cutoff.

	   RED-PEN: we violate main RFC requirement, if this SYN will appear
	   old duplicate (i.e. we receive RST in reply to SYN-ACK),
	   we must return socket to time-wait state. It is not good,
	   but not fatal yet.
	 */

	if (th->syn && !th->rst && !th->ack && !paws_reject &&
	    (after(TCP_SKB_CB(skb)->seq, tcptw->tw_rcv_nxt) ||
	     (tmp_opt.saw_tstamp &&
	      (s32)(tcptw->tw_ts_recent - tmp_opt.rcv_tsval) < 0))) {
		u32 isn = tcptw->tw_snd_nxt + 65535 + 2;
		if (isn == 0)
			isn++;
		TCP_SKB_CB(skb)->tcp_tw_isn = isn;
		return TCP_TW_SYN;
	}

	if (paws_reject)
		__NET_INC_STATS(twsk_net(tw), LINUX_MIB_PAWSESTABREJECTED);

	if (!th->rst) {
		/* In this case we must reset the TIMEWAIT timer.
		 *
		 * If it is ACKless SYN it may be both old duplicate
		 * and new good SYN with random sequence number <rcv_nxt.
		 * Do not reschedule in the last case.
		 */
		if (paws_reject || th->ack)
			inet_twsk_reschedule(tw, TCP_TIMEWAIT_LEN);

		return tcp_timewait_check_oow_rate_limit(
			tw, skb, LINUX_MIB_TCPACKSKIPPEDTIMEWAIT);
	}
	inet_twsk_put(tw);
	return TCP_TW_SUCCESS;
}
```

### send ACK

#### tcp_v4_timewait_ack

call tcp_v4_send_ack

```c

static void tcp_v4_timewait_ack(struct sock *sk, struct sk_buff *skb)
{
	struct inet_timewait_sock *tw = inet_twsk(sk);
	struct tcp_timewait_sock *tcptw = tcp_twsk(sk);

	tcp_v4_send_ack(sk, skb,
			tcptw->tw_snd_nxt, tcptw->tw_rcv_nxt,
			tcptw->tw_rcv_wnd >> tw->tw_rcv_wscale,
			tcp_time_stamp_raw() + tcptw->tw_ts_offset,
			tcptw->tw_ts_recent,
			tw->tw_bound_dev_if,
			tcp_twsk_md5_key(tcptw),
			tw->tw_transparent ? IP_REPLY_ARG_NOSRCCHECK : 0,
			tw->tw_tos
			);

	inet_twsk_put(tw);
}
```

#### tcp_v4_send_ack

The code following below sending ACKs in SYN-RECV and TIME-WAIT states outside socket context.

```c

static void tcp_v4_send_ack(const struct sock *sk,
			    struct sk_buff *skb, u32 seq, u32 ack,
			    u32 win, u32 tsval, u32 tsecr, int oif,
			    struct tcp_md5sig_key *key,
			    int reply_flags, u8 tos)
{
	const struct tcphdr *th = tcp_hdr(skb);
	struct {
		struct tcphdr th;
		__be32 opt[(TCPOLEN_TSTAMP_ALIGNED >> 2)
#ifdef CONFIG_TCP_MD5SIG
			   + (TCPOLEN_MD5SIG_ALIGNED >> 2)
#endif
			];
	} rep;
	struct net *net = sock_net(sk);
	struct ip_reply_arg arg;
	struct sock *ctl_sk;
	u64 transmit_time;

	memset(&rep.th, 0, sizeof(struct tcphdr));
	memset(&arg, 0, sizeof(arg));

	arg.iov[0].iov_base = (unsigned char *)&rep;
	arg.iov[0].iov_len  = sizeof(rep.th);
	if (tsecr) {
		rep.opt[0] = htonl((TCPOPT_NOP << 24) | (TCPOPT_NOP << 16) |
				   (TCPOPT_TIMESTAMP << 8) |
				   TCPOLEN_TIMESTAMP);
		rep.opt[1] = htonl(tsval);
		rep.opt[2] = htonl(tsecr);
		arg.iov[0].iov_len += TCPOLEN_TSTAMP_ALIGNED;
	}

	/* Swap the send and the receive. */
	rep.th.dest    = th->source;
	rep.th.source  = th->dest;
	rep.th.doff    = arg.iov[0].iov_len / 4;
	rep.th.seq     = htonl(seq);
	rep.th.ack_seq = htonl(ack);
	rep.th.ack     = 1;
	rep.th.window  = htons(win);

#ifdef CONFIG_TCP_MD5SIG
	if (key) {
		int offset = (tsecr) ? 3 : 0;

		rep.opt[offset++] = htonl((TCPOPT_NOP << 24) |
					  (TCPOPT_NOP << 16) |
					  (TCPOPT_MD5SIG << 8) |
					  TCPOLEN_MD5SIG);
		arg.iov[0].iov_len += TCPOLEN_MD5SIG_ALIGNED;
		rep.th.doff = arg.iov[0].iov_len/4;

		tcp_v4_md5_hash_hdr((__u8 *) &rep.opt[offset],
				    key, ip_hdr(skb)->saddr,
				    ip_hdr(skb)->daddr, &rep.th);
	}
#endif
	arg.flags = reply_flags;
	arg.csum = csum_tcpudp_nofold(ip_hdr(skb)->daddr,
				      ip_hdr(skb)->saddr, /* XXX */
				      arg.iov[0].iov_len, IPPROTO_TCP, 0);
	arg.csumoffset = offsetof(struct tcphdr, check) / 2;
	if (oif)
		arg.bound_dev_if = oif;
	arg.tos = tos;
	arg.uid = sock_net_uid(net, sk_fullsock(sk) ? sk : NULL);
	local_bh_disable();
	ctl_sk = this_cpu_read(*net->ipv4.tcp_sk);
	ctl_sk->sk_mark = (sk->sk_state == TCP_TIME_WAIT) ?
			   inet_twsk(sk)->tw_mark : sk->sk_mark;
	ctl_sk->sk_priority = (sk->sk_state == TCP_TIME_WAIT) ?
			   inet_twsk(sk)->tw_priority : sk->sk_priority;
	transmit_time = tcp_transmit_time(sk);
```

call ip_send_unicast_reply -> ip_push_pending_frames

```c
	ip_send_unicast_reply(ctl_sk,
			      skb, &TCP_SKB_CB(skb)->header.h4.opt,
			      ip_hdr(skb)->saddr, ip_hdr(skb)->daddr,
			      &arg, arg.iov[0].iov_len,
			      transmit_time);

	ctl_sk->sk_mark = 0;
	__TCP_INC_STATS(net, TCP_MIB_OUTSEGS);
	local_bh_enable();
}
```

## Passive Close

### rcv FIN

#### tcp_fin

Process the FIN bit. This now behaves as it is supposed to work and the FIN takes effect when it is validly part of sequence space. Not before when we get holes.

- If we are TCP_SYN_RECV or ESTABLISHED, a received fin moves us to CLOSE-WAIT(and thence onto LAST-ACK and finally, CLOSE, we never enter TIME-WAIT)
- If we are in FINWAIT-1, a received FIN indicates simultaneous close and we go into CLOSING (and later onto TIME-WAIT)
- If we are in FINWAIT-2, a received FIN moves us to TIME-WAIT.

```c
void tcp_fin(struct sock *sk)
{
	struct tcp_sock *tp = tcp_sk(sk);

	inet_csk_schedule_ack(sk);

	sk->sk_shutdown |= RCV_SHUTDOWN;
	sock_set_flag(sk, SOCK_DONE);

	switch (sk->sk_state) {
	case TCP_SYN_RECV:
	case TCP_ESTABLISHED:
		/* Move to CLOSE_WAIT */
		tcp_set_state(sk, TCP_CLOSE_WAIT);
		inet_csk_enter_pingpong_mode(sk);
		break;

	case TCP_CLOSE_WAIT:
	case TCP_CLOSING:
		/* Received a retransmission of the FIN, do
		 * nothing.
		 */
		break;
	case TCP_LAST_ACK:
		/* RFC793: Remain in the LAST-ACK state. */
		break;

	case TCP_FIN_WAIT1:
		/* This case occurs when a simultaneous close
		 * happens, we must ack the received FIN and
		 * enter the CLOSING state.
		 */
		tcp_send_ack(sk);
		tcp_set_state(sk, TCP_CLOSING);
		break;
	case TCP_FIN_WAIT2:
		/* Received a FIN -- send ACK and enter TIME_WAIT. */
		tcp_send_ack(sk);
		tcp_time_wait(sk, TCP_TIME_WAIT, 0);
		break;
	default:
		/* Only TCP_LISTEN and TCP_CLOSE are left, in these
		 * cases we should never reach this piece of code.
		 */
		pr_err("%s: Impossible, sk->sk_state=%d\n",
		       __func__, sk->sk_state);
		break;
	}

	/* It _is_ possible, that we have something out-of-order _after_ FIN.
	 * Probably, we should reset in this case. For now drop them.
	 */
	skb_rbtree_purge(&tp->out_of_order_queue);
	if (tcp_is_sack(tp))
		tcp_sack_reset(&tp->rx_opt);
	sk_mem_reclaim(sk);

	if (!sock_flag(sk, SOCK_DEAD)) {
		sk->sk_state_change(sk);

		/* Do not send POLL_HUP for half duplex close. */
		if (sk->sk_shutdown == SHUTDOWN_MASK ||
		    sk->sk_state == TCP_CLOSE)
			sk_wake_async(sk, SOCK_WAKE_WAITD, POLL_HUP);
		else
			sk_wake_async(sk, SOCK_WAKE_WAITD, POLL_IN);
	}
}
```

### send ACK

### send FIN

close decrement ref, when ref=0, close both sides.

shutdown could close one side

like [send FIN in Active Close](/docs/CS/OS/Linux/TCP.md?id=send-FIN)

### rcv ACK

see [tcp_rcv_state_process](/docs/CS/OS/Linux/TCP.md?id=tcp_rcv_state_process)

TIME_WAIT 60s

```c
#define TCP_TIMEWAIT_LEN (60*HZ) /* how long to wait to destroy TIME-WAIT
                              * state, about 60 seconds    */
```

## Others

#### tcp_fin_time

call by
timout >= 7/2 RTO

```c

static inline int tcp_fin_time(const struct sock *sk)
{
	int fin_timeout = tcp_sk(sk)->linger2 ? : sock_net(sk)->ipv4.sysctl_tcp_fin_timeout;
	const int rto = inet_csk(sk)->icsk_rto;

	if (fin_timeout < (rto << 2) - (rto >> 1))
		fin_timeout = (rto << 2) - (rto >> 1);

	return fin_timeout;
}
```

### keepalive

### test

send window and congestion window

Nagle

delay ack

writev reduce send frequency

SO_REUSEADDR vs. tw_reuse

## Links

- [Linux Network](/docs/CS/OS/Linux/Linux.md?id=Network)
- [TCP](/docs/CS/CN/TCP/TCP.md)

## References

1. [Analysis_TCP_in_Linux](https://github.com/fzyz999/Analysis_TCP_in_Linux)
2. [Congestion Control - MIT6.976](https://web.mit.edu/6.976/www/notes/Notes3.pdf)
