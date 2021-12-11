## Introduction




see [TCP protocol](/docs/CS/CN/TCP.md)

## init
call tcp_init by [inet_init](/docs/CS/OS/Linux/network.md?id=init-inet)
### tcp_init
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

	/* Size and allocate the main established and bind bucket
	 * hash tables.
	 *
	 * The methodology is similar to that of the buffer cache.
	 */
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
see system calls:
1. [socket](/docs/CS/OS/Linux/socket.md?id=create)
2. [bind](/docs/CS/OS/Linux/Calls.md?id=bind)
3. [listen](/docs/CS/OS/Linux/Calls.md?id=listen)
5. [connect](/docs/CS/OS/Linux/Calls.md?id=connect)
6. [send](/docs/CS/OS/Linux/TCP.md?id=send)
7. [recv](/docs/CS/OS/Linux/TCP.md?id=recv)


```c
// Server
socket(...,SOCK_STREAM,0);
bind(...,&server_address, ...);
listen(...);
accept(..., &client_address, ...);
recv(..., &clientaddr, ...);
close(...);
```



```c
// Client
socket(...,SOCK_STREAM,0);
connect();
send(...,&server_address,...);
```



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

see [systemcall send](/docs/CS/OS/Linux/Calls.md?id=send)
### tcp_sendmsg
called by inet_sendmsg

write to internet by [tcp_transmit_skb](/docs/CS/OS/Linux/TCP.md?id=tcp_transmit_skb)
```c
// net/ipv4/tcp.c
int tcp_sendmsg(struct sock *sk, struct msghdr *msg, size_t size)
{
       int ret;

       lock_sock(sk);
       ret = tcp_sendmsg_locked(sk, msg, size);
       release_sock(sk);

       return ret;
}



int tcp_sendmsg_locked(struct sock *sk, struct msghdr *msg, size_t size)
{
	struct tcp_sock *tp = tcp_sk(sk);
	struct ubuf_info *uarg = NULL;
	struct sk_buff *skb;
	struct sockcm_cookie sockc;
	int flags, err, copied = 0;
	int mss_now = 0, size_goal, copied_syn = 0;
	int process_backlog = 0;
	bool zc = false;
	long timeo;

	flags = msg->msg_flags;

	if (flags & MSG_ZEROCOPY && size && sock_flag(sk, SOCK_ZEROCOPY)) {
		skb = tcp_write_queue_tail(sk);
		uarg = msg_zerocopy_realloc(sk, size, skb_zcopy(skb));
		if (!uarg) {
			err = -ENOBUFS;
			goto out_err;
		}

		zc = sk->sk_route_caps & NETIF_F_SG;
		if (!zc)
			uarg->zerocopy = 0;
	}
	
  /** fastopen */
	if (unlikely(flags & MSG_FASTOPEN || inet_sk(sk)->defer_connect) &&
	    !tp->repair) {
		err = tcp_sendmsg_fastopen(sk, msg, &copied_syn, size, uarg);
		if (err == -EINPROGRESS && copied_syn > 0)
			goto out;
		else if (err)
			goto out_err;
	}

	timeo = sock_sndtimeo(sk, flags & MSG_DONTWAIT);

	tcp_rate_check_app_limited(sk);  /* is sending application-limited? */

	/* Wait for a connection to finish. One exception is TCP Fast Open
	 * (passive side) where data is allowed to be sent before a connection
	 * is fully established.
	 */
	if (((1 << sk->sk_state) & ~(TCPF_ESTABLISHED | TCPF_CLOSE_WAIT)) &&
	    !tcp_passive_fastopen(sk)) {
		err = sk_stream_wait_connect(sk, &timeo);
		if (err != 0)
			goto do_error;
	}

	if (unlikely(tp->repair)) {
		if (tp->repair_queue == TCP_RECV_QUEUE) {
			copied = tcp_send_rcvq(sk, msg, size);
			goto out_nopush;
		}

		err = -EINVAL;
		if (tp->repair_queue == TCP_NO_QUEUE)
			goto out_err;

		/* 'common' sending to sendq */
	}

	sockcm_init(&sockc, sk);
	if (msg->msg_controllen) {
		err = sock_cmsg_send(sk, msg, &sockc);
		if (unlikely(err)) {
			err = -EINVAL;
			goto out_err;
		}
	}

	/* This should be in poll */
	sk_clear_bit(SOCKWQ_ASYNC_NOSPACE, sk);

	/* Ok commence sending. */
	copied = 0;

restart:
	mss_now = tcp_send_mss(sk, &size_goal, flags);

	err = -EPIPE;
	if (sk->sk_err || (sk->sk_shutdown & SEND_SHUTDOWN))
		goto do_error;

	while (msg_data_left(msg)) {
		int copy = 0;

		skb = tcp_write_queue_tail(sk);
		if (skb)
			copy = size_goal - skb->len;

		if (copy <= 0 || !tcp_skb_can_collapse_to(skb)) {
			bool first_skb;

new_segment:
			if (!sk_stream_memory_free(sk))
				goto wait_for_space;

			if (unlikely(process_backlog >= 16)) {
				process_backlog = 0;
				if (sk_flush_backlog(sk))
					goto restart;
			}
			first_skb = tcp_rtx_and_write_queues_empty(sk);
			skb = sk_stream_alloc_skb(sk, 0, sk->sk_allocation,
						  first_skb);
			if (!skb)
				goto wait_for_space;

			process_backlog++;
			skb->ip_summed = CHECKSUM_PARTIAL;

			skb_entail(sk, skb);
			copy = size_goal;

			/* All packets are restored as if they have
			 * already been sent. skb_mstamp_ns isn't set to
			 * avoid wrong rtt estimation.
			 */
			if (tp->repair)
				TCP_SKB_CB(skb)->sacked |= TCPCB_REPAIRED;
		}

		/* Try to append data to the end of skb. */
		if (copy > msg_data_left(msg))
			copy = msg_data_left(msg);

		/* Where to copy to? */
		if (skb_availroom(skb) > 0 && !zc) {
			/* We have some space in skb head. Superb! */
			copy = min_t(int, copy, skb_availroom(skb));
			err = skb_add_data_nocache(sk, skb, &msg->msg_iter, copy);
			if (err)
				goto do_fault;
		} else if (!zc) {
			bool merge = true;
			int i = skb_shinfo(skb)->nr_frags;
			struct page_frag *pfrag = sk_page_frag(sk);

			if (!sk_page_frag_refill(sk, pfrag))
				goto wait_for_space;

			if (!skb_can_coalesce(skb, i, pfrag->page,
					      pfrag->offset)) {
				if (i >= sysctl_max_skb_frags) {
					tcp_mark_push(tp, skb);
					goto new_segment;
				}
				merge = false;
			}

			copy = min_t(int, copy, pfrag->size - pfrag->offset);

			if (!sk_wmem_schedule(sk, copy))
				goto wait_for_space;

			err = skb_copy_to_page_nocache(sk, &msg->msg_iter, skb,
						       pfrag->page,
						       pfrag->offset,
						       copy);
			if (err)
				goto do_error;

			/* Update the skb. */
			if (merge) {
				skb_frag_size_add(&skb_shinfo(skb)->frags[i - 1], copy);
			} else {
				skb_fill_page_desc(skb, i, pfrag->page,
						   pfrag->offset, copy);
				page_ref_inc(pfrag->page);
			}
			pfrag->offset += copy;
		} else {
			err = skb_zerocopy_iter_stream(sk, skb, msg, copy, uarg);
			if (err == -EMSGSIZE || err == -EEXIST) {
				tcp_mark_push(tp, skb);
				goto new_segment;
			}
			if (err < 0)
				goto do_error;
			copy = err;
		}

		if (!copied)
			TCP_SKB_CB(skb)->tcp_flags &= ~TCPHDR_PSH;

		WRITE_ONCE(tp->write_seq, tp->write_seq + copy);
		TCP_SKB_CB(skb)->end_seq += copy;
		tcp_skb_pcount_set(skb, 0);

		copied += copy;
		if (!msg_data_left(msg)) {
			if (unlikely(flags & MSG_EOR))
				TCP_SKB_CB(skb)->eor = 1;
			goto out;
		}

		if (skb->len < size_goal || (flags & MSG_OOB) || unlikely(tp->repair))
			continue;

		if (forced_push(tp)) {
			tcp_mark_push(tp, skb);
			__tcp_push_pending_frames(sk, mss_now, TCP_NAGLE_PUSH);
		} else if (skb == tcp_send_head(sk))
```
call tcp_push_one
```c
			tcp_push_one(sk, mss_now);
		continue;

wait_for_space:
		set_bit(SOCK_NOSPACE, &sk->sk_socket->flags);
		if (copied)
			tcp_push(sk, flags & ~MSG_MORE, mss_now,
				 TCP_NAGLE_PUSH, size_goal);

		err = sk_stream_wait_memory(sk, &timeo);
		if (err != 0)
			goto do_error;

		mss_now = tcp_send_mss(sk, &size_goal, flags);
	}

out:
	if (copied) {
		tcp_tx_timestamp(sk, sockc.tsflags);
		tcp_push(sk, flags, mss_now, tp->nonagle, size_goal);
	}
out_nopush:
	net_zcopy_put(uarg);
	return copied + copied_syn;

do_error:
	skb = tcp_write_queue_tail(sk);
do_fault:
	tcp_remove_empty_skb(sk, skb);

	if (copied + copied_syn)
		goto out;
out_err:
	net_zcopy_put_abort(uarg, true);
	err = sk_stream_error(sk, flags, err);
	/* make sure we wake any epoll edge trigger waiter */
	if (unlikely(tcp_rtx_and_write_queues_empty(sk) && err == -EAGAIN)) {
		sk->sk_write_space(sk);
		tcp_chrono_stop(sk, TCP_CHRONO_SNDBUF_LIMITED);
	}
	return err;
}
```



#### FastOpen
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

### push

##### forced_push

force push when `data size > max_window >> 1`

```c
static inline bool forced_push(const struct tcp_sock *tp)
{
       return after(tp->write_seq, tp->pushed_seq + (tp->max_window >> 1));
}
```


##### mark_push
```c
static inline void tcp_mark_push(struct tcp_sock *tp, struct sk_buff *skb)
{
       TCP_SKB_CB(skb)->tcp_flags |= TCPHDR_PSH;
       tp->pushed_seq = tp->write_seq;
}
```

##### tcp_push
tcp_push call __tcp_push_pending_frames
```c
void tcp_push(struct sock *sk, int flags, int mss_now,
             int nonagle, int size_goal)
{
       struct tcp_sock *tp = tcp_sk(sk);
       struct sk_buff *skb;

       skb = tcp_write_queue_tail(sk);
       if (!skb)
              return;
       if (!(flags & MSG_MORE) || forced_push(tp))
              tcp_mark_push(tp, skb);

       tcp_mark_urg(tp, flags);

       if (tcp_should_autocork(sk, skb, size_goal)) {

              /* avoid atomic op if TSQ_THROTTLED bit is already set */
              if (!test_bit(TSQ_THROTTLED, &sk->sk_tsq_flags)) {
                     NET_INC_STATS(sock_net(sk), LINUX_MIB_TCPAUTOCORKING);
                     set_bit(TSQ_THROTTLED, &sk->sk_tsq_flags);
              }
              /* It is possible TX completion already happened
               * before we set TSQ_THROTTLED.
               */
              if (refcount_read(&sk->sk_wmem_alloc) > skb->truesize)
                     return;
       }

       if (flags & MSG_MORE)
              nonagle = TCP_NAGLE_CORK;

       __tcp_push_pending_frames(sk, mss_now, nonagle);
}
```


##### tcp_push_one

Send _single_ skb sitting at the send head. This function requires true push pending frames to setup probe timer etc.

```c
void tcp_push_one(struct sock *sk, unsigned int mss_now)
{
       struct sk_buff *skb = tcp_send_head(sk);

       BUG_ON(!skb || skb->len < mss_now);

       tcp_write_xmit(sk, mss_now, TCP_NAGLE_PUSH, 1, sk->sk_allocation);
}
```


__tcp_push_pending_frames

Push out any pending frames which were held back due to TCP_CORK or attempt at coalescing tiny packets. The socket must be locked by the caller.

```c
void __tcp_push_pending_frames(struct sock *sk, unsigned int cur_mss,
                            int nonagle)
{
       /* If we are closed, the bytes will have to remain here.
        * In time closedown will finish, we empty the write queue and
        * all will be happy.
        */
       if (unlikely(sk->sk_state == TCP_CLOSE))
              return;

       if (tcp_write_xmit(sk, cur_mss, nonagle, 0,
                        sk_gfp_mask(sk, GFP_ATOMIC)))
              tcp_check_probe_timer(sk);
}
```

### write to internet

#### tcp_write_xmit

This routine writes packets to the network.  It advances the send_head.  This happens as incoming acks open up the remote window for us.

LARGESEND note: !tcp_urg_mode is overkill, only frames between snd_up-64k-mss .. snd_up cannot be large. However, taking into account rare use of URG, this is not a big flaw.

Send at most one packet when push_one > 0. Temporarily ignore cwnd limit to force at most one packet out when push_one == 2.

Returns true, if no segments are in flight and we have queued segments, but cannot send anything now because of SWS or another problem.

```c
// net/ipv4/tcp_output.c
static bool tcp_write_xmit(struct sock *sk, unsigned int mss_now, int nonagle,
                        int push_one, gfp_t gfp)
{
       struct tcp_sock *tp = tcp_sk(sk);
       struct sk_buff *skb;
       unsigned int tso_segs, sent_pkts;
       int cwnd_quota;
       int result;
       bool is_cwnd_limited = false, is_rwnd_limited = false;
       u32 max_segs;

       sent_pkts = 0;

       tcp_mstamp_refresh(tp);
       if (!push_one) {
              /* Do MTU probing. */
              result = tcp_mtu_probe(sk);
              if (!result) {
                     return false;
              } else if (result > 0) {
                     sent_pkts = 1;
              }
       }

       max_segs = tcp_tso_segs(sk, mss_now);
       while ((skb = tcp_send_head(sk))) {
              unsigned int limit;

              if (unlikely(tp->repair) && tp->repair_queue == TCP_SEND_QUEUE) {
                     /* "skb_mstamp_ns" is used as a start point for the retransmit timer */
                     skb->skb_mstamp_ns = tp->tcp_wstamp_ns = tp->tcp_clock_cache;
                     list_move_tail(&skb->tcp_tsorted_anchor, &tp->tsorted_sent_queue);
                     tcp_init_tso_segs(skb, mss_now);
                     goto repair; /* Skip network transmission */
              }

              if (tcp_pacing_check(sk))
                     break;

              tso_segs = tcp_init_tso_segs(skb, mss_now);
              BUG_ON(!tso_segs);

              cwnd_quota = tcp_cwnd_test(tp, skb);
              if (!cwnd_quota) {
                     if (push_one == 2)
                            /* Force out a loss probe pkt. */
                            cwnd_quota = 1;
                     else
                            break;
              }

              if (unlikely(!tcp_snd_wnd_test(tp, skb, mss_now))) {
                     is_rwnd_limited = true;
                     break;
              }

              if (tso_segs == 1) {
                     if (unlikely(!tcp_nagle_test(tp, skb, mss_now,
                                               (tcp_skb_is_last(sk, skb) ?
                                                nonagle : TCP_NAGLE_PUSH))))
                            break;
              } else {
                     if (!push_one &&
                         tcp_tso_should_defer(sk, skb, &is_cwnd_limited,
                                           &is_rwnd_limited, max_segs))
                            break;
              }

              limit = mss_now;
              if (tso_segs > 1 && !tcp_urg_mode(tp))
                     limit = tcp_mss_split_point(sk, skb, mss_now,
                                              min_t(unsigned int,
                                                   cwnd_quota,
                                                   max_segs),
                                              nonagle);

              if (skb->len > limit &&
                  unlikely(tso_fragment(sk, skb, limit, mss_now, gfp)))
                     break;

              if (tcp_small_queue_check(sk, skb, 0))
                     break;

              /* Argh, we hit an empty skb(), presumably a thread
               * is sleeping in sendmsg()/sk_stream_wait_memory().
               * We do not want to send a pure-ack packet and have
               * a strange looking rtx queue with empty packet(s).
               */
              if (TCP_SKB_CB(skb)->end_seq == TCP_SKB_CB(skb)->seq)
                     break;
```
call [tcp_transmit_skb](/docs/CS/OS/Linux/TCP.md?id=tcp_transmit_skb)
```c
              if (unlikely(tcp_transmit_skb(sk, skb, 1, gfp)))
                     break;

repair:
              /* Advance the send_head.  This one is sent out.
               * This call will increment packets_out.
               */
              tcp_event_new_data_sent(sk, skb);

              tcp_minshall_update(tp, mss_now, skb);
              sent_pkts += tcp_skb_pcount(skb);

              if (push_one)
                     break;
       }

       if (is_rwnd_limited)
              tcp_chrono_start(sk, TCP_CHRONO_RWND_LIMITED);
       else
              tcp_chrono_stop(sk, TCP_CHRONO_RWND_LIMITED);

       is_cwnd_limited |= (tcp_packets_in_flight(tp) >= tp->snd_cwnd);
       if (likely(sent_pkts || is_cwnd_limited))
              tcp_cwnd_validate(sk, is_cwnd_limited);

       if (likely(sent_pkts)) {
              if (tcp_in_cwnd_reduction(sk))
                     tp->prr_out += sent_pkts;

              /* Send one loss probe per tail loss episode. */
              if (push_one != 2)
                     tcp_schedule_loss_probe(sk, false);
              return false;
       }
       return !tp->packets_out && !tcp_write_queue_empty(sk);
}
```

#### tcp_transmit_skb

This routine actually transmits TCP packets queued in by tcp_do_sendmsg().  This is used by both the initial transmission and possible later retransmissions.

All SKB's seen here are completely headerless.  It is our job to **build the TCP header**, and **pass the packet down to IP** so it can do the same plus pass the packet off to the device.

We are working here with either a clone of the original SKB, or a fresh unique copy made by the retransmit engine.

```c
static int tcp_transmit_skb(struct sock *sk, struct sk_buff *skb, int clone_it,
                         gfp_t gfp_mask)
{
       return __tcp_transmit_skb(sk, skb, clone_it, gfp_mask,
                              tcp_sk(sk)->rcv_nxt);
}

static int __tcp_transmit_skb(struct sock *sk, struct sk_buff *skb,
			      int clone_it, gfp_t gfp_mask, u32 rcv_nxt)
{
	const struct inet_connection_sock *icsk = inet_csk(sk);
	struct inet_sock *inet;
	struct tcp_sock *tp;
	struct tcp_skb_cb *tcb;
	struct tcp_out_options opts;
	unsigned int tcp_options_size, tcp_header_size;
	struct sk_buff *oskb = NULL;
	struct tcp_md5sig_key *md5;
	struct tcphdr *th;
	u64 prior_wstamp;
	int err;

	BUG_ON(!skb || !tcp_skb_pcount(skb));
	tp = tcp_sk(sk);
	prior_wstamp = tp->tcp_wstamp_ns;
	tp->tcp_wstamp_ns = max(tp->tcp_wstamp_ns, tp->tcp_clock_cache);
	skb->skb_mstamp_ns = tp->tcp_wstamp_ns;
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

		if (unlikely(!skb))
			return -ENOBUFS;
		/* retransmit skbs might have a non zero value in skb->dev
		 * because skb->dev is aliased with skb->rbnode.rb_left
		 */
		skb->dev = NULL;
	}

	inet = inet_sk(sk);
	tcb = TCP_SKB_CB(skb);
	memset(&opts, 0, sizeof(opts));

	if (unlikely(tcb->tcp_flags & TCPHDR_SYN)) {
		tcp_options_size = tcp_syn_options(sk, skb, &opts, &md5);
	} else {
		tcp_options_size = tcp_established_options(sk, skb, &opts,
							   &md5);
		/* Force a PSH flag on all (GSO) packets to expedite GRO flush
		 * at receiver : This slightly improve GRO performance.
		 * Note that we do not force the PSH flag for non GSO packets,
		 * because they might be sent under high congestion events,
		 * and in this case it is better to delay the delivery of 1-MSS
		 * packets and thus the corresponding ACK packet that would
		 * release the following packet.
		 */
		if (tcp_skb_pcount(skb) > 1)
			tcb->tcp_flags |= TCPHDR_PSH;
	}
	tcp_header_size = tcp_options_size + sizeof(struct tcphdr);

	/* if no packet is in qdisc/device queue, then allow XPS to select
	 * another queue. We can be called from tcp_tsq_handler()
	 * which holds one reference to sk.
	 *
	 * TODO: Ideally, in-flight pure ACK packets should not matter here.
	 * One way to get this would be to set skb->truesize = 2 on them.
	 */
	skb->ooo_okay = sk_wmem_alloc_get(sk) < SKB_TRUESIZE(1);

	/* If we had to use memory reserve to allocate this skb,
	 * this might cause drops if packet is looped back :
	 * Other socket might not have SOCK_MEMALLOC.
	 * Packets not looped back do not care about pfmemalloc.
	 */
	skb->pfmemalloc = 0;

	skb_push(skb, tcp_header_size);
	skb_reset_transport_header(skb);

	skb_orphan(skb);
	skb->sk = sk;
	skb->destructor = skb_is_tcp_pure_ack(skb) ? __sock_wfree : tcp_wfree;
	refcount_add(skb->truesize, &sk->sk_wmem_alloc);

	skb_set_dst_pending_confirm(skb, sk->sk_dst_pending_confirm);

	/* Build TCP header and checksum it. */
	th = (struct tcphdr *)skb->data;
	th->source		= inet->inet_sport;
	th->dest		= inet->inet_dport;
	th->seq			= htonl(tcb->seq);
	th->ack_seq		= htonl(rcv_nxt);
	*(((__be16 *)th) + 6)	= htons(((tcp_header_size >> 2) << 12) |
					tcb->tcp_flags);

	th->check		= 0;
	th->urg_ptr		= 0;

	/* The urg_mode check is necessary during a below snd_una win probe */
	if (unlikely(tcp_urg_mode(tp) && before(tcb->seq, tp->snd_up))) {
		if (before(tp->snd_up, tcb->seq + 0x10000)) {
			th->urg_ptr = htons(tp->snd_up - tcb->seq);
			th->urg = 1;
		} else if (after(tcb->seq + 0xFFFF, tp->snd_nxt)) {
			th->urg_ptr = htons(0xFFFF);
			th->urg = 1;
		}
	}

	skb_shinfo(skb)->gso_type = sk->sk_gso_type;
	if (likely(!(tcb->tcp_flags & TCPHDR_SYN))) {
		th->window      = htons(tcp_select_window(sk));
		tcp_ecn_send(sk, skb, th, tcp_header_size);
	} else {
		/* RFC1323: The window in SYN & SYN/ACK segments
		 * is never scaled.
		 */
		th->window	= htons(min(tp->rcv_wnd, 65535U));
	}

	tcp_options_write((__be32 *)(th + 1), tp, &opts);

#ifdef CONFIG_TCP_MD5SIG
	/* Calculate the MD5 hash, as we have all we need now */
	if (md5) {
		sk_nocaps_add(sk, NETIF_F_GSO_MASK);
		tp->af_specific->calc_md5_hash(opts.hash_location,
					       md5, sk, skb);
	}
#endif

	/* BPF prog is the last one writing header option */
	bpf_skops_write_hdr_opt(sk, skb, NULL, NULL, 0, &opts);

	INDIRECT_CALL_INET(icsk->icsk_af_ops->send_check,
			   tcp_v6_send_check, tcp_v4_send_check,
			   sk, skb);

	if (likely(tcb->tcp_flags & TCPHDR_ACK))
		tcp_event_ack_sent(sk, tcp_skb_pcount(skb), rcv_nxt);

	if (skb->len != tcp_header_size) {
		tcp_event_data_sent(tp, sk);
		tp->data_segs_out += tcp_skb_pcount(skb);
		tp->bytes_sent += skb->len - tcp_header_size;
	}

	if (after(tcb->end_seq, tp->snd_nxt) || tcb->seq == tcb->end_seq)
		TCP_ADD_STATS(sock_net(sk), TCP_MIB_OUTSEGS,
			      tcp_skb_pcount(skb));

	tp->segs_out += tcp_skb_pcount(skb);
	skb_set_hash_from_sk(skb, sk);
	/* OK, its time to fill skb_shinfo(skb)->gso_{segs|size} */
	skb_shinfo(skb)->gso_segs = tcp_skb_pcount(skb);
	skb_shinfo(skb)->gso_size = tcp_skb_mss(skb);

	/* Leave earliest departure time in skb->tstamp (skb->skb_mstamp_ns) */

	/* Cleanup our debris for IP stacks */
	memset(skb->cb, 0, max(sizeof(struct inet_skb_parm),
			       sizeof(struct inet6_skb_parm)));

	tcp_add_tx_delay(skb, tp);

```
call [ip_queue_xmit](/docs/CS/OS/Linux/IP.md?id=ip_queue_xmit)
```
	err = INDIRECT_CALL_INET(icsk->icsk_af_ops->queue_xmit,
				 inet6_csk_xmit, ip_queue_xmit,
				 sk, skb, &inet->cork.fl);

	if (unlikely(err > 0)) {
		tcp_enter_cwr(sk);
		err = net_xmit_eval(err);
	}
	if (!err && oskb) {
		tcp_update_skb_after_send(sk, oskb, prior_wstamp);
		tcp_rate_skb_sent(sk, oskb);
	}
	return err;
}
```


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


### call tcp_v4_rcv
`ip_rcv` -> ip_rcv_finish -> dst_input -> ip_local_deliver -> [tcp_v4_rcv](/docs/CS/OS/Linux/TCP.md?id=tcp_v4_rcv)

### call tcp_recvmsg

recv/recvfrom -> sys_recvfrom -> sock_recvmsg -> inet_recvmsg -> [tcp_recvmsg](/docs/CS/OS/Linux/TCP.md?id=tcp_recvmsg)


Receive a frame from the socket and optionally record the address of the
sender. We verify the buffers are writable and if needed move the
sender address from kernel to user space.

1. sock_recvmsg
2. move_addr_to_user

```c
//
int __sys_recvfrom(int fd, void __user *ubuf, size_t size, unsigned int flags,
		   struct sockaddr __user *addr, int __user *addr_len)
{
	struct socket *sock;
	struct iovec iov;
	struct msghdr msg;
	struct sockaddr_storage address;
	...
	
	err = sock_recvmsg(sock, &msg, flags);

	if (err >= 0 && addr != NULL) {
		err2 = move_addr_to_user(&address,
					 msg.msg_namelen, addr, addr_len);
	}
	return err;
}
```

Receives msg from sock, passing through LSM. Returns the total number of bytes received, or an error.
```c
// 
int sock_recvmsg(struct socket *sock, struct msghdr *msg, int flags)
{
	int err = security_socket_recvmsg(sock, msg, msg_data_left(msg), flags);
	return err ?: sock_recvmsg_nosec(sock, msg, flags);
}
```
call inet_recvmsg or inet6_recvmsg
```c
static inline int sock_recvmsg_nosec(struct socket *sock, struct msghdr *msg,
				     int flags)
{
	return INDIRECT_CALL_INET(sock->ops->recvmsg, inet6_recvmsg,
				  inet_recvmsg, sock, msg, msg_data_left(msg),
				  flags);
}
```
inet_recvmsg calls:
1. tcp_recvmsg
2. udp_recvmsg
```c
// net/ipv4/af_inet.c
int inet_recvmsg(struct socket *sock, struct msghdr *msg, size_t size,
		 int flags)
{
	struct sock *sk = sock->sk;
	int addr_len = 0;
	int err;

	err = INDIRECT_CALL_2(sk->sk_prot->recvmsg, tcp_recvmsg, udp_recvmsg,
			      sk, msg, size, flags & MSG_DONTWAIT,
			      flags & ~MSG_DONTWAIT, &addr_len);
	if (err >= 0)
		msg->msg_namelen = addr_len;
	return err;
}
```
inet6_recvmsg calls:
1. tcp_recvmsg
2. udpv6_recvmsg
```c
// net/ipv6/af_inet6.c
int inet6_recvmsg(struct socket *sock, struct msghdr *msg, size_t size,
		  int flags)
{
	struct sock *sk = sock->sk;
	int addr_len = 0;
	int err;

	err = INDIRECT_CALL_2(sk->sk_prot->recvmsg, tcp_recvmsg, udpv6_recvmsg,
			      sk, msg, size, flags & MSG_DONTWAIT,
			      flags & ~MSG_DONTWAIT, &addr_len);
	if (err >= 0)
		msg->msg_namelen = addr_len;
	return err;
}
```




### tcp_v4_rcv
1. not PACKET_HOST, discard
2. copy to skb
3. get tcp header and valid it
4. inet lookup: check if in ehash or bhash
5. do time wait if sk_state == TCP_TIME_WAIT
6. do if sk_state == TCP_NEW_SYN_RECV
7. do tcp_v4_do_rcv if sk_state == TCP_LISTEN
8. lock sock
9. if user own sock
   - not: tcp_v4_do_rcv
   - else: tcp_add_backlog
10. unlock sock




```c

int tcp_v4_rcv(struct sk_buff *skb)
{
	struct net *net = dev_net(skb->dev);
	struct sk_buff *skb_to_free;
	int sdif = inet_sdif(skb);
	int dif = inet_iif(skb);
	const struct iphdr *iph;
	const struct tcphdr *th;
	bool refcounted;
	struct sock *sk;
	int ret;

	if (skb->pkt_type != PACKET_HOST)
		goto discard_it;

	/* Count it even if it's bad */
	__TCP_INC_STATS(net, TCP_MIB_INSEGS);

	if (!pskb_may_pull(skb, sizeof(struct tcphdr)))
		goto discard_it;

	th = (const struct tcphdr *)skb->data;

	if (unlikely(th->doff < sizeof(struct tcphdr) / 4))
		goto bad_packet;
	if (!pskb_may_pull(skb, th->doff * 4))
		goto discard_it;

	/* An explanation is required here, I think.
	 * Packet length and doff are validated by header prediction,
	 * provided case of th->doff==0 is eliminated.
	 * So, we defer the checks. */

	if (skb_checksum_init(skb, IPPROTO_TCP, inet_compute_pseudo))
		goto csum_error;

	th = (const struct tcphdr *)skb->data;
	iph = ip_hdr(skb);
lookup:
	sk = __inet_lookup_skb(&tcp_hashinfo, skb, __tcp_hdrlen(th), th->source,
			       th->dest, sdif, &refcounted);
	if (!sk)
		goto no_tcp_socket;

process:
	if (sk->sk_state == TCP_TIME_WAIT)
		goto do_time_wait;

	if (sk->sk_state == TCP_NEW_SYN_RECV) {
		struct request_sock *req = inet_reqsk(sk);
		bool req_stolen = false;
		struct sock *nsk;

		sk = req->rsk_listener;
		if (unlikely(tcp_v4_inbound_md5_hash(sk, skb, dif, sdif))) {
			sk_drops_add(sk, skb);
			reqsk_put(req);
			goto discard_it;
		}
		if (tcp_checksum_complete(skb)) {
			reqsk_put(req);
			goto csum_error;
		}
		if (unlikely(sk->sk_state != TCP_LISTEN)) {
			inet_csk_reqsk_queue_drop_and_put(sk, req);
			goto lookup;
		}
		/* We own a reference on the listener, increase it again
		 * as we might lose it too soon.
		 */
		sock_hold(sk);
		refcounted = true;
		nsk = NULL;
		if (!tcp_filter(sk, skb)) {
			th = (const struct tcphdr *)skb->data;
			iph = ip_hdr(skb);
			tcp_v4_fill_cb(skb, iph, th);
			nsk = tcp_check_req(sk, skb, req, false, &req_stolen);
		}
		if (!nsk) {
			reqsk_put(req);
			if (req_stolen) {
				/* Another cpu got exclusive access to req
				 * and created a full blown socket.
				 * Try to feed this packet to this socket
				 * instead of discarding it.
				 */
				tcp_v4_restore_cb(skb);
				sock_put(sk);
				goto lookup;
			}
			goto discard_and_relse;
		}
		if (nsk == sk) {
			reqsk_put(req);
			tcp_v4_restore_cb(skb);
		} else if (tcp_child_process(sk, nsk, skb)) {
			tcp_v4_send_reset(nsk, skb);
			goto discard_and_relse;
		} else {
			sock_put(sk);
			return 0;
		}
	}
	if (unlikely(iph->ttl < inet_sk(sk)->min_ttl)) {
		__NET_INC_STATS(net, LINUX_MIB_TCPMINTTLDROP);
		goto discard_and_relse;
	}

	if (!xfrm4_policy_check(sk, XFRM_POLICY_IN, skb))
		goto discard_and_relse;

	if (tcp_v4_inbound_md5_hash(sk, skb, dif, sdif))
		goto discard_and_relse;

	nf_reset_ct(skb);

	if (tcp_filter(sk, skb))
		goto discard_and_relse;
	th = (const struct tcphdr *)skb->data;
	iph = ip_hdr(skb);
	tcp_v4_fill_cb(skb, iph, th);

	skb->dev = NULL;

	if (sk->sk_state == TCP_LISTEN) {
		ret = tcp_v4_do_rcv(sk, skb);
		goto put_and_return;
	}

	sk_incoming_cpu_update(sk);

	bh_lock_sock_nested(sk);
	tcp_segs_in(tcp_sk(sk), skb);
	ret = 0;
	if (!sock_owned_by_user(sk)) {
		skb_to_free = sk->sk_rx_skb_cache;
		sk->sk_rx_skb_cache = NULL;
		ret = tcp_v4_do_rcv(sk, skb);
	} else {
		if (tcp_add_backlog(sk, skb))
			goto discard_and_relse;
		skb_to_free = NULL;
	}
	bh_unlock_sock(sk);
	if (skb_to_free)
		__kfree_skb(skb_to_free);

put_and_return:
	if (refcounted)
		sock_put(sk);

	return ret;

no_tcp_socket:
	if (!xfrm4_policy_check(NULL, XFRM_POLICY_IN, skb))
		goto discard_it;

	tcp_v4_fill_cb(skb, iph, th);

	if (tcp_checksum_complete(skb)) {
csum_error:
		__TCP_INC_STATS(net, TCP_MIB_CSUMERRORS);
bad_packet:
		__TCP_INC_STATS(net, TCP_MIB_INERRS);
	} else {
		tcp_v4_send_reset(NULL, skb);
	}

discard_it:
	/* Discard frame. */
	kfree_skb(skb);
	return 0;

discard_and_relse:
	sk_drops_add(sk, skb);
	if (refcounted)
		sock_put(sk);
	goto discard_it;

do_time_wait:
	if (!xfrm4_policy_check(NULL, XFRM_POLICY_IN, skb)) {
		inet_twsk_put(inet_twsk(sk));
		goto discard_it;
	}

	tcp_v4_fill_cb(skb, iph, th);

	if (tcp_checksum_complete(skb)) {
		inet_twsk_put(inet_twsk(sk));
		goto csum_error;
	}
	switch (tcp_timewait_state_process(inet_twsk(sk), skb, th)) {
	case TCP_TW_SYN: {
		struct sock *sk2 = inet_lookup_listener(dev_net(skb->dev),
							&tcp_hashinfo, skb,
							__tcp_hdrlen(th),
							iph->saddr, th->source,
							iph->daddr, th->dest,
							inet_iif(skb),
							sdif);
		if (sk2) {
			inet_twsk_deschedule_put(inet_twsk(sk));
			sk = sk2;
			tcp_v4_restore_cb(skb);
			refcounted = false;
			goto process;
		}
	}
		/* to ACK */
		fallthrough;
	case TCP_TW_ACK:
		tcp_v4_timewait_ack(sk, skb);
		break;
	case TCP_TW_RST:
		tcp_v4_send_reset(sk, skb);
		inet_twsk_deschedule_put(inet_twsk(sk));
		goto discard_it;
	case TCP_TW_SUCCESS:;
	}
	goto discard_it;
}

```



#### inet_lookup

```c
// include/net/inet_hashtables.h
static inline struct sock *__inet_lookup_skb(struct inet_hashinfo *hashinfo,
					     struct sk_buff *skb,
					     int doff,
					     const __be16 sport,
					     const __be16 dport,
					     const int sdif,
					     bool *refcounted)
{
	struct sock *sk = skb_steal_sock(skb, refcounted);
	const struct iphdr *iph = ip_hdr(skb);

	if (sk)
		return sk;

	return __inet_lookup(dev_net(skb_dst(skb)->dev), hashinfo, skb,
			     doff, iph->saddr, sport,
			     iph->daddr, dport, inet_iif(skb), sdif,
			     refcounted);
}

static inline struct sock *__inet_lookup(struct net *net,
					 struct inet_hashinfo *hashinfo,
					 struct sk_buff *skb, int doff,
					 const __be32 saddr, const __be16 sport,
					 const __be32 daddr, const __be16 dport,
					 const int dif, const int sdif,
					 bool *refcounted)
{
	u16 hnum = ntohs(dport);
	struct sock *sk;

	sk = __inet_lookup_established(net, hashinfo, saddr, sport,
				       daddr, hnum, dif, sdif);
	*refcounted = true;
	if (sk)
		return sk;
	*refcounted = false;
	return __inet_lookup_listener(net, hashinfo, skb, doff, saddr,
				      sport, daddr, hnum, dif, sdif);
}
```


##### inet_lookup_established
```c
// net/ipv4/inet_hashtables.c
struct sock *__inet_lookup_established(struct net *net,
				  struct inet_hashinfo *hashinfo,
				  const __be32 saddr, const __be16 sport,
				  const __be32 daddr, const u16 hnum,
				  const int dif, const int sdif)
{
	INET_ADDR_COOKIE(acookie, saddr, daddr);
	const __portpair ports = INET_COMBINED_PORTS(sport, hnum);
	struct sock *sk;
	const struct hlist_nulls_node *node;
	/* Optimize here for direct hit, only listening connections can
	 * have wildcards anyways.
	 */
	unsigned int hash = inet_ehashfn(net, daddr, hnum, saddr, sport);
	unsigned int slot = hash & hashinfo->ehash_mask;
	struct inet_ehash_bucket *head = &hashinfo->ehash[slot];

begin:
	sk_nulls_for_each_rcu(sk, node, &head->chain) {
		if (sk->sk_hash != hash)
			continue;
		if (likely(INET_MATCH(sk, net, acookie,
				      saddr, daddr, ports, dif, sdif))) {
			if (unlikely(!refcount_inc_not_zero(&sk->sk_refcnt)))
				goto out;
			if (unlikely(!INET_MATCH(sk, net, acookie,
						 saddr, daddr, ports,
						 dif, sdif))) {
				sock_gen_put(sk);
				goto begin;
			}
			goto found;
		}
	}
	/*
	 * if the nulls value we got at the end of this lookup is
	 * not the expected one, we must restart lookup.
	 * We probably met an item that was moved to another chain.
	 */
	if (get_nulls_value(node) != slot)
		goto begin;
out:
	sk = NULL;
found:
	return sk;
}
```

##### inet_lookup_listener
```c

struct sock *__inet_lookup_listener(struct net *net,
				    struct inet_hashinfo *hashinfo,
				    struct sk_buff *skb, int doff,
				    const __be32 saddr, __be16 sport,
				    const __be32 daddr, const unsigned short hnum,
				    const int dif, const int sdif)
{
	struct inet_listen_hashbucket *ilb2;
	struct sock *result = NULL;
	unsigned int hash2;

	/* Lookup redirect from BPF */
	if (static_branch_unlikely(&bpf_sk_lookup_enabled)) {
		result = inet_lookup_run_bpf(net, hashinfo, skb, doff,
					     saddr, sport, daddr, hnum);
		if (result)
			goto done;
	}

	hash2 = ipv4_portaddr_hash(net, daddr, hnum);
	ilb2 = inet_lhash2_bucket(hashinfo, hash2);

	result = inet_lhash2_lookup(net, ilb2, skb, doff,
				    saddr, sport, daddr, hnum,
				    dif, sdif);
	if (result)
		goto done;

	/* Lookup lhash2 with INADDR_ANY */
	hash2 = ipv4_portaddr_hash(net, htonl(INADDR_ANY), hnum);
	ilb2 = inet_lhash2_bucket(hashinfo, hash2);

	result = inet_lhash2_lookup(net, ilb2, skb, doff,
				    saddr, sport, htonl(INADDR_ANY), hnum,
				    dif, sdif);
done:
	if (IS_ERR(result))
		return NULL;
	return result;
}
```

```c
// include/net/inet_hashtables.h
#define INET_MATCH(__sk, __net, __cookie, __saddr, __daddr, __ports, __dif, __sdif) \
	(((__sk)->sk_portpair == (__ports))		&&		\
	 ((__sk)->sk_daddr	== (__saddr))		&&		\
	 ((__sk)->sk_rcv_saddr	== (__daddr))		&&		\
	 (((__sk)->sk_bound_dev_if == (__dif))		||		\
	  ((__sk)->sk_bound_dev_if == (__sdif)))	&&		\
	 net_eq(sock_net(__sk), (__net)))
#endif /* 64-bit arch */
```





#### tcp_v4_do_rcv

The socket must have it's spinlock held when we get here, unless it is a TCP_LISTEN socket.

We have a potential double-lock case here, so even when doing backlog processing we use the BH locking scheme. This is because we cannot sleep with the original spinlock held.

```c
// 
int tcp_v4_do_rcv(struct sock *sk, struct sk_buff *skb)
{
       struct sock *rsk;

       if (sk->sk_state == TCP_ESTABLISHED) { /* Fast path */
              struct dst_entry *dst = sk->sk_rx_dst;

              sock_rps_save_rxhash(sk, skb);
              sk_mark_napi_id(sk, skb);
              if (dst) {
                     if (inet_sk(sk)->rx_dst_ifindex != skb->skb_iif ||
                         !INDIRECT_CALL_1(dst->ops->check, ipv4_dst_check,
                                        dst, 0)) {
                            dst_release(dst);
                            sk->sk_rx_dst = NULL;
                     }
              }
              tcp_rcv_established(sk, skb);
              return 0;
       }

       if (tcp_checksum_complete(skb))
              goto csum_err;

       if (sk->sk_state == TCP_LISTEN) {
              struct sock *nsk = tcp_v4_cookie_check(sk, skb);

              if (!nsk)
                     goto discard;
              if (nsk != sk) {
                     if (tcp_child_process(sk, nsk, skb)) {
                            rsk = nsk;
                            goto reset;
                     }
                     return 0;
              }
       } else
              sock_rps_save_rxhash(sk, skb);

       if (tcp_rcv_state_process(sk, skb)) {
              rsk = sk;
              goto reset;
       }
       return 0;

reset:
       tcp_v4_send_reset(rsk, skb);
discard:
       kfree_skb(skb);
       /* Be careful here. If this function gets more complicated and
        * gcc suffers from register pressure on the x86, sk (in %ebx)
        * might be destroyed here. This current version compiles correctly,
        * but you have been warned.
        */
       return 0;

csum_err:
       TCP_INC_STATS(sock_net(sk), TCP_MIB_CSUMERRORS);
       TCP_INC_STATS(sock_net(sk), TCP_MIB_INERRS);
       goto discard;
}
```

### tcp_rcv_established

TCP receive function for the ESTABLISHED state.
It is split into a fast path and a slow path. The fast path is
disabled when:
- A zero window was announced from us - zero window probing
      is only handled properly in the slow path.
- Out of order segments arrived.
- Urgent data is expected.
- There is no buffer space left
- Unexpected TCP flags/window values/header lengths are received
  (detected by checking the TCP header against pred_flags)
- Data is sent in both directions. Fast path only supports pure senders
  or pure receivers (this means either the sequence number or the ack
  value must stay constant)
- Unexpected TCP option.

When these conditions are not satisfied it drops into a standard
receive procedure patterned after RFC793 to handle all cases.
The first three cases are guaranteed by proper pred_flags setting,
the rest is checked inline. Fast processing is turned on in
tcp_data_queue when everything is OK.

1. `tcp_queue_rcv`
2. `tcp_data_ready`

```c
// net/ipv4/tcp_input.c
void tcp_rcv_established(struct sock *sk, struct sk_buff *skb)
{
	const struct tcphdr *th = (const struct tcphdr *)skb->data;
	struct tcp_sock *tp = tcp_sk(sk);
	unsigned int len = skb->len;

	/* TCP congestion window tracking */
	trace_tcp_probe(sk, skb);

	tcp_mstamp_refresh(tp);
	if (unlikely(!sk->sk_rx_dst))
		inet_csk(sk)->icsk_af_ops->sk_rx_dst_set(sk, skb);
	/*
	 *	Header prediction.
	 *	The code loosely follows the one in the famous
	 *	"30 instruction TCP receive" Van Jacobson mail.
	 *
	 *	Van's trick is to deposit buffers into socket queue
	 *	on a device interrupt, to call tcp_recv function
	 *	on the receive process context and checksum and copy
	 *	the buffer to user space. smart...
	 *
	 *	Our current scheme is not silly either but we take the
	 *	extra cost of the net_bh soft interrupt processing...
	 *	We do checksum and copy also but from device to kernel.
	 */

	tp->rx_opt.saw_tstamp = 0;

	/*	pred_flags is 0xS?10 << 16 + snd_wnd
	 *	if header_prediction is to be made
	 *	'S' will always be tp->tcp_header_len >> 2
	 *	'?' will be 0 for the fast path, otherwise pred_flags is 0 to
	 *  turn it off	(when there are holes in the receive
	 *	 space for instance)
	 *	PSH flag is ignored.
	 */

	if ((tcp_flag_word(th) & TCP_HP_BITS) == tp->pred_flags &&
	    TCP_SKB_CB(skb)->seq == tp->rcv_nxt &&
	    !after(TCP_SKB_CB(skb)->ack_seq, tp->snd_nxt)) {
		int tcp_header_len = tp->tcp_header_len;

		/* Timestamp header prediction: tcp_header_len
		 * is automatically equal to th->doff*4 due to pred_flags
		 * match.
		 */

		/* Check timestamp */
		if (tcp_header_len == sizeof(struct tcphdr) + TCPOLEN_TSTAMP_ALIGNED) {
			/* No? Slow path! */
			if (!tcp_parse_aligned_timestamp(tp, th))
				goto slow_path;

			/* If PAWS failed, check it more carefully in slow path */
			if ((s32)(tp->rx_opt.rcv_tsval - tp->rx_opt.ts_recent) < 0)
				goto slow_path;

			/* DO NOT update ts_recent here, if checksum fails
			 * and timestamp was corrupted part, it will result
			 * in a hung connection since we will drop all
			 * future packets due to the PAWS test.
			 */
		}

		if (len <= tcp_header_len) {
			/* Bulk data transfer: sender */
			if (len == tcp_header_len) {
				/* Predicted packet is in window by definition.
				 * seq == rcv_nxt and rcv_wup <= rcv_nxt.
				 * Hence, check seq<=rcv_wup reduces to:
				 */
				if (tcp_header_len ==
				    (sizeof(struct tcphdr) + TCPOLEN_TSTAMP_ALIGNED) &&
				    tp->rcv_nxt == tp->rcv_wup)
					tcp_store_ts_recent(tp);

				/* We know that such packets are checksummed
				 * on entry.
				 */
				tcp_ack(sk, skb, 0);
				__kfree_skb(skb);
				tcp_data_snd_check(sk);
				/* When receiving pure ack in fast path, update
				 * last ts ecr directly instead of calling
				 * tcp_rcv_rtt_measure_ts()
				 */
				tp->rcv_rtt_last_tsecr = tp->rx_opt.rcv_tsecr;
				return;
			} else { /* Header too small */
				TCP_INC_STATS(sock_net(sk), TCP_MIB_INERRS);
				goto discard;
			}
		} else {
			int eaten = 0;
			bool fragstolen = false;

			if (tcp_checksum_complete(skb))
				goto csum_error;

			if ((int)skb->truesize > sk->sk_forward_alloc)
				goto step5;

			/* Predicted packet is in window by definition.
			 * seq == rcv_nxt and rcv_wup <= rcv_nxt.
			 * Hence, check seq<=rcv_wup reduces to:
			 */
			if (tcp_header_len ==
			    (sizeof(struct tcphdr) + TCPOLEN_TSTAMP_ALIGNED) &&
			    tp->rcv_nxt == tp->rcv_wup)
				tcp_store_ts_recent(tp);

			tcp_rcv_rtt_measure_ts(sk, skb);

			NET_INC_STATS(sock_net(sk), LINUX_MIB_TCPHPHITS);

			/* Bulk data transfer: receiver */
			__skb_pull(skb, tcp_header_len);
			eaten = tcp_queue_rcv(sk, skb, &fragstolen);

			tcp_event_data_recv(sk, skb);

			if (TCP_SKB_CB(skb)->ack_seq != tp->snd_una) {
				/* Well, only one small jumplet in fast path... */
				tcp_ack(sk, skb, FLAG_DATA);
				tcp_data_snd_check(sk);
				if (!inet_csk_ack_scheduled(sk))
					goto no_ack;
			} else {
				tcp_update_wl(tp, TCP_SKB_CB(skb)->seq);
			}

			__tcp_ack_snd_check(sk, 0);
no_ack:
			if (eaten)
				kfree_skb_partial(skb, fragstolen);
			tcp_data_ready(sk);
			return;
		}
	}

slow_path:
	if (len < (th->doff << 2) || tcp_checksum_complete(skb))
		goto csum_error;

	if (!th->ack && !th->rst && !th->syn)
		goto discard;

	/*
	 *	Standard slow path.
	 */
	if (!tcp_validate_incoming(sk, skb, th, 1))
		return;

step5:
	if (tcp_ack(sk, skb, FLAG_SLOWPATH | FLAG_UPDATE_TS_RECENT) < 0)
		goto discard;

	tcp_rcv_rtt_measure_ts(sk, skb);

	/* Process urgent data. */
	tcp_urg(sk, skb, th);

	/* step 7: process the segment text */
	tcp_data_queue(sk, skb);

	tcp_data_snd_check(sk);
	tcp_ack_snd_check(sk);
	return;

csum_error:
	trace_tcp_bad_csum(skb);
	TCP_INC_STATS(sock_net(sk), TCP_MIB_CSUMERRORS);
	TCP_INC_STATS(sock_net(sk), TCP_MIB_INERRS);

discard:
	tcp_drop(sk, skb);
}
```



#### tcp_queue_rcv

```c

static int __must_check tcp_queue_rcv(struct sock *sk, struct sk_buff *skb,
				      bool *fragstolen)
{
	int eaten;
	struct sk_buff *tail = skb_peek_tail(&sk->sk_receive_queue);

	eaten = (tail &&
		 tcp_try_coalesce(sk, tail,
				  skb, fragstolen)) ? 1 : 0;
	tcp_rcv_nxt_update(tcp_sk(sk), TCP_SKB_CB(skb)->end_seq);
	if (!eaten) {
		__skb_queue_tail(&sk->sk_receive_queue, skb);
		skb_set_owner_r(skb, sk);
	}
	return eaten;
}
```



#### tcp_data_ready

```c
void tcp_data_ready(struct sock *sk)
{
	if (tcp_epollin_ready(sk, sk->sk_rcvlowat) || sock_flag(sk, SOCK_DONE))
		sk->sk_data_ready(sk);
}
```

`sk_data_ready` = `sock_def_readable` , see [Socket]()

```c
void sock_def_readable(struct sock *sk)
{
	struct socket_wq *wq;

	rcu_read_lock();
	wq = rcu_dereference(sk->sk_wq);
	if (skwq_has_sleeper(wq))
		wake_up_interruptible_sync_poll(&wq->wait, EPOLLIN | EPOLLPRI |
						EPOLLRDNORM | EPOLLRDBAND);
	sk_wake_async(sk, SOCK_WAKE_WAITD, POLL_IN);
	rcu_read_unlock();
}
```

`wake_up_interruptible_sync_poll` see Thundering Hred



### tcp_check_req
Process an incoming packet for SYN_RECV sockets represented as a
request_sock. Normally sk is the listener socket but for TFO it
points to the child socket.

XXX (TFO) - The current impl contains a special check for ack
validation and inside tcp_v4_reqsk_send_ack(). Can we do better?
We don't need to initialize tmp_opt.sack_ok as we don't use the results
```c

struct sock *tcp_check_req(struct sock *sk, struct sk_buff *skb,
			   struct request_sock *req,
			   bool fastopen, bool *req_stolen)
{
	struct tcp_options_received tmp_opt;
	struct sock *child;
	const struct tcphdr *th = tcp_hdr(skb);
	__be32 flg = tcp_flag_word(th) & (TCP_FLAG_RST|TCP_FLAG_SYN|TCP_FLAG_ACK);
	bool paws_reject = false;
	bool own_req;

	tmp_opt.saw_tstamp = 0;
	if (th->doff > (sizeof(struct tcphdr)>>2)) {
		tcp_parse_options(sock_net(sk), skb, &tmp_opt, 0, NULL);

		if (tmp_opt.saw_tstamp) {
			tmp_opt.ts_recent = req->ts_recent;
			if (tmp_opt.rcv_tsecr)
				tmp_opt.rcv_tsecr -= tcp_rsk(req)->ts_off;
			/* We do not store true stamp, but it is not required,
			 * it can be estimated (approximately)
			 * from another data.
			 */
			tmp_opt.ts_recent_stamp = ktime_get_seconds() - ((TCP_TIMEOUT_INIT/HZ)<<req->num_timeout);
			paws_reject = tcp_paws_reject(&tmp_opt, th->rst);
		}
	}

	/* Check for pure retransmitted SYN. */
	if (TCP_SKB_CB(skb)->seq == tcp_rsk(req)->rcv_isn &&
	    flg == TCP_FLAG_SYN &&
	    !paws_reject) {
		/*
		 * RFC793 draws (Incorrectly! It was fixed in RFC1122)
		 * this case on figure 6 and figure 8, but formal
		 * protocol description says NOTHING.
		 * To be more exact, it says that we should send ACK,
		 * because this segment (at least, if it has no data)
		 * is out of window.
		 *
		 *  CONCLUSION: RFC793 (even with RFC1122) DOES NOT
		 *  describe SYN-RECV state. All the description
		 *  is wrong, we cannot believe to it and should
		 *  rely only on common sense and implementation
		 *  experience.
		 *
		 * Enforce "SYN-ACK" according to figure 8, figure 6
		 * of RFC793, fixed by RFC1122.
		 *
		 * Note that even if there is new data in the SYN packet
		 * they will be thrown away too.
		 *
		 * Reset timer after retransmitting SYNACK, similar to
		 * the idea of fast retransmit in recovery.
		 */
		if (!tcp_oow_rate_limited(sock_net(sk), skb,
					  LINUX_MIB_TCPACKSKIPPEDSYNRECV,
					  &tcp_rsk(req)->last_oow_ack_time) &&

		    !inet_rtx_syn_ack(sk, req)) {
			unsigned long expires = jiffies;

			expires += min(TCP_TIMEOUT_INIT << req->num_timeout,
				       TCP_RTO_MAX);
			if (!fastopen)
				mod_timer_pending(&req->rsk_timer, expires);
			else
				req->rsk_timer.expires = expires;
		}
		return NULL;
	}

	/* Further reproduces section "SEGMENT ARRIVES"
	   for state SYN-RECEIVED of RFC793.
	   It is broken, however, it does not work only
	   when SYNs are crossed.

	   You would think that SYN crossing is impossible here, since
	   we should have a SYN_SENT socket (from connect()) on our end,
	   but this is not true if the crossed SYNs were sent to both
	   ends by a malicious third party.  We must defend against this,
	   and to do that we first verify the ACK (as per RFC793, page
	   36) and reset if it is invalid.  Is this a true full defense?
	   To convince ourselves, let us consider a way in which the ACK
	   test can still pass in this 'malicious crossed SYNs' case.
	   Malicious sender sends identical SYNs (and thus identical sequence
	   numbers) to both A and B:

		A: gets SYN, seq=7
		B: gets SYN, seq=7

	   By our good fortune, both A and B select the same initial
	   send sequence number of seven :-)

		A: sends SYN|ACK, seq=7, ack_seq=8
		B: sends SYN|ACK, seq=7, ack_seq=8

	   So we are now A eating this SYN|ACK, ACK test passes.  So
	   does sequence test, SYN is truncated, and thus we consider
	   it a bare ACK.

	   If icsk->icsk_accept_queue.rskq_defer_accept, we silently drop this
	   bare ACK.  Otherwise, we create an established connection.  Both
	   ends (listening sockets) accept the new incoming connection and try
	   to talk to each other. 8-)

	   Note: This case is both harmless, and rare.  Possibility is about the
	   same as us discovering intelligent life on another plant tomorrow.

	   But generally, we should (RFC lies!) to accept ACK
	   from SYNACK both here and in tcp_rcv_state_process().
	   tcp_rcv_state_process() does not, hence, we do not too.

	   Note that the case is absolutely generic:
	   we cannot optimize anything here without
	   violating protocol. All the checks must be made
	   before attempt to create socket.
	 */

	/* RFC793 page 36: "If the connection is in any non-synchronized state ...
	 *                  and the incoming segment acknowledges something not yet
	 *                  sent (the segment carries an unacceptable ACK) ...
	 *                  a reset is sent."
	 *
	 * Invalid ACK: reset will be sent by listening socket.
	 * Note that the ACK validity check for a Fast Open socket is done
	 * elsewhere and is checked directly against the child socket rather
	 * than req because user data may have been sent out.
	 */
	if ((flg & TCP_FLAG_ACK) && !fastopen &&
	    (TCP_SKB_CB(skb)->ack_seq !=
	     tcp_rsk(req)->snt_isn + 1))
		return sk;

	/* Also, it would be not so bad idea to check rcv_tsecr, which
	 * is essentially ACK extension and too early or too late values
	 * should cause reset in unsynchronized states.
	 */

	/* RFC793: "first check sequence number". */

	if (paws_reject || !tcp_in_window(TCP_SKB_CB(skb)->seq, TCP_SKB_CB(skb)->end_seq,
					  tcp_rsk(req)->rcv_nxt, tcp_rsk(req)->rcv_nxt + req->rsk_rcv_wnd)) {
		/* Out of window: send ACK and drop. */
		if (!(flg & TCP_FLAG_RST) &&
		    !tcp_oow_rate_limited(sock_net(sk), skb,
					  LINUX_MIB_TCPACKSKIPPEDSYNRECV,
					  &tcp_rsk(req)->last_oow_ack_time))
			req->rsk_ops->send_ack(sk, skb, req);
		if (paws_reject)
			__NET_INC_STATS(sock_net(sk), LINUX_MIB_PAWSESTABREJECTED);
		return NULL;
	}

	/* In sequence, PAWS is OK. */

	if (tmp_opt.saw_tstamp && !after(TCP_SKB_CB(skb)->seq, tcp_rsk(req)->rcv_nxt))
		req->ts_recent = tmp_opt.rcv_tsval;

	if (TCP_SKB_CB(skb)->seq == tcp_rsk(req)->rcv_isn) {
		/* Truncate SYN, it is out of window starting
		   at tcp_rsk(req)->rcv_isn + 1. */
		flg &= ~TCP_FLAG_SYN;
	}

	/* RFC793: "second check the RST bit" and
	 *	   "fourth, check the SYN bit"
	 */
	if (flg & (TCP_FLAG_RST|TCP_FLAG_SYN)) {
		__TCP_INC_STATS(sock_net(sk), TCP_MIB_ATTEMPTFAILS);
		goto embryonic_reset;
	}

	/* ACK sequence verified above, just make sure ACK is
	 * set.  If ACK not set, just silently drop the packet.
	 *
	 * XXX (TFO) - if we ever allow "data after SYN", the
	 * following check needs to be removed.
	 */
	if (!(flg & TCP_FLAG_ACK))
		return NULL;

	/* For Fast Open no more processing is needed (sk is the
	 * child socket).
	 */
	if (fastopen)
		return sk;

	/* While TCP_DEFER_ACCEPT is active, drop bare ACK. */
	if (req->num_timeout < inet_csk(sk)->icsk_accept_queue.rskq_defer_accept &&
	    TCP_SKB_CB(skb)->end_seq == tcp_rsk(req)->rcv_isn + 1) {
		inet_rsk(req)->acked = 1;
		__NET_INC_STATS(sock_net(sk), LINUX_MIB_TCPDEFERACCEPTDROP);
		return NULL;
	}

	/* OK, ACK is valid, create big socket and
	 * feed this segment to it. It will repeat all
	 * the tests. THIS SEGMENT MUST MOVE SOCKET TO
	 * ESTABLISHED STATE. If it will be dropped after
	 * socket is created, wait for troubles.
	 */
	child = inet_csk(sk)->icsk_af_ops->syn_recv_sock(sk, skb, req, NULL,
							 req, &own_req);
	if (!child)
		goto listen_overflow;

	if (own_req && rsk_drop_req(req)) {
		reqsk_queue_removed(&inet_csk(sk)->icsk_accept_queue, req);
		inet_csk_reqsk_queue_drop_and_put(sk, req);
		return child;
	}

	sock_rps_save_rxhash(child, skb);
	tcp_synack_rtt_meas(child, req);
	*req_stolen = !own_req;
	return inet_csk_complete_hashdance(sk, child, req, own_req);
```

tcp_abort_on_overflow
```c
listen_overflow:
	if (!sock_net(sk)->ipv4.sysctl_tcp_abort_on_overflow) {
		inet_rsk(req)->acked = 1;
		return NULL;
	}

```


```c
embryonic_reset:
	if (!(flg & TCP_FLAG_RST)) {
		/* Received a bad SYN pkt - for TFO We try not to reset
		 * the local connection unless it's really necessary to
		 * avoid becoming vulnerable to outside attack aiming at
		 * resetting legit local connections.
		 */
		req->rsk_ops->send_reset(sk, skb);
	} else if (fastopen) { /* received a valid RST pkt */
		reqsk_fastopen_remove(sk, req, true);
		tcp_reset(sk, skb);
	}
	if (!fastopen) {
		bool unlinked = inet_csk_reqsk_queue_drop(sk, req);

		if (unlinked)
			__NET_INC_STATS(sock_net(sk), LINUX_MIB_EMBRYONICRSTS);
		*req_stolen = !unlinked;
	}
	return NULL;
}
```


#### tcp_rtx_synack
```c
int inet_rtx_syn_ack(const struct sock *parent, struct request_sock *req)
{
	int err = req->rsk_ops->rtx_syn_ack(parent, req);

	if (!err)
		req->num_retrans++;
	return err;
}


struct request_sock_ops tcp_request_sock_ops __read_mostly = {
	.family		=	PF_INET,
	.obj_size	=	sizeof(struct tcp_request_sock),
	.rtx_syn_ack	=	tcp_rtx_synack,
	.send_ack	=	tcp_v4_reqsk_send_ack,
	.destructor	=	tcp_v4_reqsk_destructor,
	.send_reset	=	tcp_v4_send_reset,
	.syn_ack_timeout =	tcp_syn_ack_timeout,
};
```

```c

int tcp_rtx_synack(const struct sock *sk, struct request_sock *req)
{
	const struct tcp_request_sock_ops *af_ops = tcp_rsk(req)->af_specific;
	struct flowi fl;
	int res;

	tcp_rsk(req)->txhash = net_tx_rndhash();
	res = af_ops->send_synack(sk, NULL, &fl, req, NULL, TCP_SYNACK_NORMAL,
				  NULL);
	if (!res) {
		__TCP_INC_STATS(sock_net(sk), TCP_MIB_RETRANSSEGS);
		__NET_INC_STATS(sock_net(sk), LINUX_MIB_TCPSYNRETRANS);
		if (unlikely(tcp_passive_fastopen(sk)))
			tcp_sk(sk)->total_retrans++;
		trace_tcp_retransmit_synack(sk, req);
	}
	return res;
}
```

#### inet_csk_complete_hashdance
call `inet_csk_reqsk_queue_add` add into accept queue
```c

struct sock *inet_csk_complete_hashdance(struct sock *sk, struct sock *child,
					 struct request_sock *req, bool own_req)
{
	if (own_req) {
		inet_csk_reqsk_queue_drop(sk, req);
		reqsk_queue_removed(&inet_csk(sk)->icsk_accept_queue, req);
		if (inet_csk_reqsk_queue_add(sk, req, child))
			return child;
	}
	/* Too bad, another child took ownership of the request, undo. */
	bh_unlock_sock(child);
	sock_put(child);
	return NULL;
}
```


### tcp_recvmsg

`recvfrom` -> `inet_recvmsg` -> `tcp_recvmsg`

```c
int tcp_recvmsg(struct sock *sk, struct msghdr *msg, size_t len, int nonblock,
              int flags, int *addr_len)
{
       int cmsg_flags = 0, ret, inq;
       struct scm_timestamping_internal tss;

       if (unlikely(flags & MSG_ERRQUEUE))
              return inet_recv_error(sk, msg, len, addr_len);

       if (sk_can_busy_loop(sk) &&
           skb_queue_empty_lockless(&sk->sk_receive_queue) &&
           sk->sk_state == TCP_ESTABLISHED)
              sk_busy_loop(sk, nonblock);

       ret = tcp_recvmsg_locked(sk, msg, len, nonblock, flags, &tss,
                             &cmsg_flags);
       ...
       return ret;
}
```

#### tcp_recvmsg_locked

```c

static int tcp_recvmsg_locked(struct sock *sk, struct msghdr *msg, size_t len,
			      int nonblock, int flags,
			      struct scm_timestamping_internal *tss,
			      int *cmsg_flags)
{
	struct tcp_sock *tp = tcp_sk(sk);
	int copied = 0;
	u32 peek_seq;
	u32 *seq;
	unsigned long used;
	int err;
	int target;		/* Read at least this many bytes */
	long timeo;
	struct sk_buff *skb, *last;
	u32 urg_hole = 0;

	err = -ENOTCONN;
	if (sk->sk_state == TCP_LISTEN)
		goto out;

	if (tp->recvmsg_inq)
		*cmsg_flags = TCP_CMSG_INQ;
	timeo = sock_rcvtimeo(sk, nonblock);

	/* Urgent data needs to be handled specially. */
	if (flags & MSG_OOB)
		goto recv_urg;

	if (unlikely(tp->repair)) {
		err = -EPERM;
		if (!(flags & MSG_PEEK))
			goto out;

		if (tp->repair_queue == TCP_SEND_QUEUE)
			goto recv_sndq;

		err = -EINVAL;
		if (tp->repair_queue == TCP_NO_QUEUE)
			goto out;

		/* 'common' recv queue MSG_PEEK-ing */
	}

	seq = &tp->copied_seq;
	if (flags & MSG_PEEK) {
		peek_seq = tp->copied_seq;
		seq = &peek_seq;
	}

	target = sock_rcvlowat(sk, flags & MSG_WAITALL, len);

	do {
		u32 offset;

		/* Are we at urgent data? Stop if we have read anything or have SIGURG pending. */
		if (tp->urg_data && tp->urg_seq == *seq) {
			if (copied)
				break;
			if (signal_pending(current)) {
				copied = timeo ? sock_intr_errno(timeo) : -EAGAIN;
				break;
			}
		}

		/* Next get a buffer. */

		last = skb_peek_tail(&sk->sk_receive_queue);
		skb_queue_walk(&sk->sk_receive_queue, skb) {
			last = skb;
			/* Now that we have two receive queues this
			 * shouldn't happen.
			 */
			if (WARN(before(*seq, TCP_SKB_CB(skb)->seq),
				 "TCP recvmsg seq # bug: copied %X, seq %X, rcvnxt %X, fl %X\n",
				 *seq, TCP_SKB_CB(skb)->seq, tp->rcv_nxt,
				 flags))
				break;

			offset = *seq - TCP_SKB_CB(skb)->seq;
			if (unlikely(TCP_SKB_CB(skb)->tcp_flags & TCPHDR_SYN)) {
				pr_err_once("%s: found a SYN, please report !\n", __func__);
				offset--;
			}
			if (offset < skb->len)
				goto found_ok_skb;
			if (TCP_SKB_CB(skb)->tcp_flags & TCPHDR_FIN)
				goto found_fin_ok;
			WARN(!(flags & MSG_PEEK),
			     "TCP recvmsg seq # bug 2: copied %X, seq %X, rcvnxt %X, fl %X\n",
			     *seq, TCP_SKB_CB(skb)->seq, tp->rcv_nxt, flags);
		}

		/* Well, if we have backlog, try to process it now yet. */

		if (copied >= target && !READ_ONCE(sk->sk_backlog.tail))
			break;

		if (copied) {
			if (sk->sk_err ||
			    sk->sk_state == TCP_CLOSE ||
			    (sk->sk_shutdown & RCV_SHUTDOWN) ||
			    !timeo ||
			    signal_pending(current))
				break;
		} else {
			if (sock_flag(sk, SOCK_DONE))
				break;

			if (sk->sk_err) {
				copied = sock_error(sk);
				break;
			}

			if (sk->sk_shutdown & RCV_SHUTDOWN)
				break;

			if (sk->sk_state == TCP_CLOSE) {
				/* This occurs when user tries to read
				 * from never connected socket.
				 */
				copied = -ENOTCONN;
				break;
			}

			if (!timeo) {
				copied = -EAGAIN;
				break;
			}

			if (signal_pending(current)) {
				copied = sock_intr_errno(timeo);
				break;
			}
		}

		tcp_cleanup_rbuf(sk, copied);

		if (copied >= target) {
			/* Do not sleep, just process backlog. */
			release_sock(sk);
			lock_sock(sk);
		} else { /* Wait if none enough data */
			sk_wait_data(sk, &timeo, last);
		}

		if ((flags & MSG_PEEK) &&
		    (peek_seq - copied - urg_hole != tp->copied_seq)) {
			net_dbg_ratelimited("TCP(%s:%d): Application bug, race in MSG_PEEK\n",
					    current->comm,
					    task_pid_nr(current));
			peek_seq = tp->copied_seq;
		}
		continue;

found_ok_skb:
		/* Ok so how much can we use? */
		used = skb->len - offset;
		if (len < used)
			used = len;

		/* Do we have urgent data here? */
		if (tp->urg_data) {
			u32 urg_offset = tp->urg_seq - *seq;
			if (urg_offset < used) {
				if (!urg_offset) {
					if (!sock_flag(sk, SOCK_URGINLINE)) {
						WRITE_ONCE(*seq, *seq + 1);
						urg_hole++;
						offset++;
						used--;
						if (!used)
							goto skip_copy;
					}
				} else
					used = urg_offset;
			}
		}

		if (!(flags & MSG_TRUNC)) {
			err = skb_copy_datagram_msg(skb, offset, msg, used);
			if (err) {
				/* Exception. Bailout! */
				if (!copied)
					copied = -EFAULT;
				break;
			}
		}

		WRITE_ONCE(*seq, *seq + used);
		copied += used;
		len -= used;

		tcp_rcv_space_adjust(sk);

skip_copy:
		if (tp->urg_data && after(tp->copied_seq, tp->urg_seq)) {
			tp->urg_data = 0;
			tcp_fast_path_check(sk);
		}

		if (TCP_SKB_CB(skb)->has_rxtstamp) {
			tcp_update_recv_tstamps(skb, tss);
			*cmsg_flags |= TCP_CMSG_TS;
		}

		if (used + offset < skb->len)
			continue;

		if (TCP_SKB_CB(skb)->tcp_flags & TCPHDR_FIN)
			goto found_fin_ok;
		if (!(flags & MSG_PEEK))
			sk_eat_skb(sk, skb);
		continue;

found_fin_ok:
		/* Process the FIN. */
		WRITE_ONCE(*seq, *seq + 1);
		if (!(flags & MSG_PEEK))
			sk_eat_skb(sk, skb);
		break;
	} while (len > 0);

	/* According to UNIX98, msg_name/msg_namelen are ignored
	 * on connected socket. I was just happy when found this 8) --ANK
	 */

	/* Clean up data we have read: This will do ACK frames. */
	tcp_cleanup_rbuf(sk, copied);
	return copied;

out:
	return err;

recv_urg:
	err = tcp_recv_urg(sk, msg, len, flags);
	goto out;

recv_sndq:
	err = tcp_peek_sndq(sk, msg, len);
	goto out;
}
```
#### sk_wait_data

wait for data to arrive at sk_receive_queue

```c
int sk_wait_data(struct sock *sk, long *timeo, const struct sk_buff *skb)
{
	DEFINE_WAIT_FUNC(wait, woken_wake_function);
	int rc;

	add_wait_queue(sk_sleep(sk), &wait);
	sk_set_bit(SOCKWQ_ASYNC_WAITDATA, sk);
	rc = sk_wait_event(sk, timeo, skb_peek_tail(&sk->sk_receive_queue) != skb, &wait);
	
  sk_clear_bit(SOCKWQ_ASYNC_WAITDATA, sk);
	remove_wait_queue(sk_sleep(sk), &wait);
	return rc;
}
```






## Client Connect

### send SYN
#### tcp_v4_connect
This will initiate an outgoing connection.


- rcu_dereference_protected
- ip_route_connect
- tcp_set_state `SYN-SENT`
- inet_hash_connect
- ip_route_newports
- tcp_fastopen_defer_connect
- tcp_connect

tcp_death_row

```c

int tcp_v4_connect(struct sock *sk, struct sockaddr *uaddr, int addr_len)
{
	struct sockaddr_in *usin = (struct sockaddr_in *)uaddr;
	struct inet_sock *inet = inet_sk(sk);
	struct tcp_sock *tp = tcp_sk(sk);
	__be16 orig_sport, orig_dport;
	__be32 daddr, nexthop;
	struct flowi4 *fl4;
	struct rtable *rt;
	int err;
	struct ip_options_rcu *inet_opt;
	struct inet_timewait_death_row *tcp_death_row = &sock_net(sk)->ipv4.tcp_death_row;

	if (addr_len < sizeof(struct sockaddr_in))
		return -EINVAL;

	if (usin->sin_family != AF_INET)
		return -EAFNOSUPPORT;

	nexthop = daddr = usin->sin_addr.s_addr;
	inet_opt = rcu_dereference_protected(inet->inet_opt,
					     lockdep_sock_is_held(sk));
	if (inet_opt && inet_opt->opt.srr) {
		if (!daddr)
			return -EINVAL;
		nexthop = inet_opt->opt.faddr;
	}

	orig_sport = inet->inet_sport;
	orig_dport = usin->sin_port;
	fl4 = &inet->cork.fl.u.ip4;
	rt = ip_route_connect(fl4, nexthop, inet->inet_saddr,
			      RT_CONN_FLAGS(sk), sk->sk_bound_dev_if,
			      IPPROTO_TCP,
			      orig_sport, orig_dport, sk);
	if (IS_ERR(rt)) {
		err = PTR_ERR(rt);
		if (err == -ENETUNREACH)
			IP_INC_STATS(sock_net(sk), IPSTATS_MIB_OUTNOROUTES);
		return err;
	}

	if (rt->rt_flags & (RTCF_MULTICAST | RTCF_BROADCAST)) {
		ip_rt_put(rt);
		return -ENETUNREACH;
	}

	if (!inet_opt || !inet_opt->opt.srr)
		daddr = fl4->daddr;

	if (!inet->inet_saddr)
		inet->inet_saddr = fl4->saddr;
	sk_rcv_saddr_set(sk, inet->inet_saddr);

	if (tp->rx_opt.ts_recent_stamp && inet->inet_daddr != daddr) {
		/* Reset inherited state */
		tp->rx_opt.ts_recent	   = 0;
		tp->rx_opt.ts_recent_stamp = 0;
		if (likely(!tp->repair))
			WRITE_ONCE(tp->write_seq, 0);
	}

	inet->inet_dport = usin->sin_port;
	sk_daddr_set(sk, daddr);

	inet_csk(sk)->icsk_ext_hdr_len = 0;
	if (inet_opt)
		inet_csk(sk)->icsk_ext_hdr_len = inet_opt->opt.optlen;

	tp->rx_opt.mss_clamp = TCP_MSS_DEFAULT;

	/* Socket identity is still unknown (sport may be zero).
	 * However we set state to SYN-SENT and not releasing socket
	 * lock select source port, enter ourselves into the hash tables and
	 * complete initialization after this.
	 */
	tcp_set_state(sk, TCP_SYN_SENT);
	err = inet_hash_connect(tcp_death_row, sk);
	if (err)
		goto failure;

	sk_set_txhash(sk);

	rt = ip_route_newports(fl4, rt, orig_sport, orig_dport,
			       inet->inet_sport, inet->inet_dport, sk);
	if (IS_ERR(rt)) {
		err = PTR_ERR(rt);
		rt = NULL;
		goto failure;
	}
	/* OK, now commit destination to socket.  */
	sk->sk_gso_type = SKB_GSO_TCPV4;
	sk_setup_caps(sk, &rt->dst);
	rt = NULL;

	if (likely(!tp->repair)) {
		if (!tp->write_seq)
			WRITE_ONCE(tp->write_seq,
				   secure_tcp_seq(inet->inet_saddr,
						  inet->inet_daddr,
						  inet->inet_sport,
						  usin->sin_port));
		tp->tsoffset = secure_tcp_ts_off(sock_net(sk),
						 inet->inet_saddr,
						 inet->inet_daddr);
	}

	inet->inet_id = prandom_u32();

	if (tcp_fastopen_defer_connect(sk, &err))
		return err;
	if (err)
		goto failure;

	err = tcp_connect(sk);

	if (err)
		goto failure;

	return 0;

failure:
	/** This unhashes the socket and releases the local port, if necessary.     */
	tcp_set_state(sk, TCP_CLOSE);
	ip_rt_put(rt);
	sk->sk_route_caps = 0;
	inet->inet_dport = 0;
	return err;
}
```

#### tcp_connect
Build a SYN and send it off.

- tcp_connect_init
- create and init nodata skb
- eq connect queue
- ECN syn
- fast open
- send next seq
- repeat the SYN until an answer

```c
// tcp_output.c
int tcp_connect(struct sock *sk)
{
	struct tcp_sock *tp = tcp_sk(sk);
	struct sk_buff *buff;
	int err;

	tcp_call_bpf(sk, BPF_SOCK_OPS_TCP_CONNECT_CB, 0, NULL);

	if (inet_csk(sk)->icsk_af_ops->rebuild_header(sk))
		return -EHOSTUNREACH; /* Routing failure or similar. */

	tcp_connect_init(sk);

	if (unlikely(tp->repair)) {
		tcp_finish_connect(sk, NULL);
		return 0;
	}

	buff = sk_stream_alloc_skb(sk, 0, sk->sk_allocation, true);
	if (unlikely(!buff))
		return -ENOBUFS;

	tcp_init_nondata_skb(buff, tp->write_seq++, TCPHDR_SYN);
	tcp_mstamp_refresh(tp);
	tp->retrans_stamp = tcp_time_stamp(tp);
	tcp_connect_queue_skb(sk, buff);
	tcp_ecn_send_syn(sk, buff);
	tcp_rbtree_insert(&sk->tcp_rtx_queue, buff);

	/* Send off SYN; include data in Fast Open. */
	err = tp->fastopen_req ? tcp_send_syn_data(sk, buff) :
	      tcp_transmit_skb(sk, buff, 1, sk->sk_allocation);
	if (err == -ECONNREFUSED)
		return err;

	/* We change tp->snd_nxt after the tcp_transmit_skb() call
	 * in order to make this packet get counted in tcpOutSegs.
	 */
	WRITE_ONCE(tp->snd_nxt, tp->write_seq);
	tp->pushed_seq = tp->write_seq;
	buff = tcp_send_head(sk);
	if (unlikely(buff)) {
		WRITE_ONCE(tp->snd_nxt, TCP_SKB_CB(buff)->seq);
		tp->pushed_seq	= TCP_SKB_CB(buff)->seq;
	}
	TCP_INC_STATS(sock_net(sk), TCP_MIB_ACTIVEOPENS);

	/* Timer for repeating the SYN until an answer. */
	inet_csk_reset_xmit_timer(sk, ICSK_TIME_RETRANS,
				  inet_csk(sk)->icsk_rto, TCP_RTO_MAX);
	return 0;
}
```

#### reqsk_timer_handler

```c

static void reqsk_timer_handler(struct timer_list *t)
{
	struct request_sock *req = from_timer(req, t, rsk_timer);
	struct sock *sk_listener = req->rsk_listener;
	struct net *net = sock_net(sk_listener);
	struct inet_connection_sock *icsk = inet_csk(sk_listener);
	struct request_sock_queue *queue = &icsk->icsk_accept_queue;
	int max_syn_ack_retries, qlen, expire = 0, resend = 0;

	if (inet_sk_state_load(sk_listener) != TCP_LISTEN)
		goto drop;

	max_syn_ack_retries = icsk->icsk_syn_retries ? : net->ipv4.sysctl_tcp_synack_retries;
	/* Normally all the openreqs are young and become mature
	 * (i.e. converted to established socket) for first timeout.
	 * If synack was not acknowledged for 1 second, it means
	 * one of the following things: synack was lost, ack was lost,
	 * rtt is high or nobody planned to ack (i.e. synflood).
	 * When server is a bit loaded, queue is populated with old
	 * open requests, reducing effective size of queue.
	 * When server is well loaded, queue size reduces to zero
	 * after several minutes of work. It is not synflood,
	 * it is normal operation. The solution is pruning
	 * too old entries overriding normal timeout, when
	 * situation becomes dangerous.
	 *
	 * Essentially, we reserve half of room for young
	 * embrions; and abort old ones without pity, if old
	 * ones are about to clog our table.
	 */
	qlen = reqsk_queue_len(queue);
	if ((qlen << 1) > max(8U, READ_ONCE(sk_listener->sk_max_ack_backlog))) {
		int young = reqsk_queue_len_young(queue) << 1;

		while (max_syn_ack_retries > 2) {
			if (qlen < young)
				break;
			max_syn_ack_retries--;
			young <<= 1;
		}
	}
	syn_ack_recalc(req, max_syn_ack_retries, READ_ONCE(queue->rskq_defer_accept),
		       &expire, &resend);
	req->rsk_ops->syn_ack_timeout(req);
	if (!expire &&
	    (!resend ||
	     !inet_rtx_syn_ack(sk_listener, req) ||
	     inet_rsk(req)->acked)) {
		unsigned long timeo;

		if (req->num_timeout++ == 0)
			atomic_dec(&queue->young);
		timeo = min(TCP_TIMEOUT_INIT << req->num_timeout, TCP_RTO_MAX);
		mod_timer(&req->rsk_timer, jiffies + timeo);
		return;
	}
drop:
	inet_csk_reqsk_queue_drop_and_put(sk_listener, req);
}
```


### rcv SYNACK


#### tcp_rcv_synsent_state_process

```c


static int tcp_rcv_synsent_state_process(struct sock *sk, struct sk_buff *skb,
					 const struct tcphdr *th)
{
	struct inet_connection_sock *icsk = inet_csk(sk);
	struct tcp_sock *tp = tcp_sk(sk);
	struct tcp_fastopen_cookie foc = { .len = -1 };
	int saved_clamp = tp->rx_opt.mss_clamp;
	bool fastopen_fail;

	tcp_parse_options(sock_net(sk), skb, &tp->rx_opt, 0, &foc);
	if (tp->rx_opt.saw_tstamp && tp->rx_opt.rcv_tsecr)
		tp->rx_opt.rcv_tsecr -= tp->tsoffset;

	if (th->ack) {
		/* rfc793:
		 * "If the state is SYN-SENT then
		 *    first check the ACK bit
		 *      If the ACK bit is set
		 *	  If SEG.ACK =< ISS, or SEG.ACK > SND.NXT, send
		 *        a reset (unless the RST bit is set, if so drop
		 *        the segment and return)"
		 */
		if (!after(TCP_SKB_CB(skb)->ack_seq, tp->snd_una) ||
		    after(TCP_SKB_CB(skb)->ack_seq, tp->snd_nxt)) {
			/* Previous FIN/ACK or RST/ACK might be ignored. */
			if (icsk->icsk_retransmits == 0)
				inet_csk_reset_xmit_timer(sk,
						ICSK_TIME_RETRANS,
						TCP_TIMEOUT_MIN, TCP_RTO_MAX);
			goto reset_and_undo;
		}

		if (tp->rx_opt.saw_tstamp && tp->rx_opt.rcv_tsecr &&
		    !between(tp->rx_opt.rcv_tsecr, tp->retrans_stamp,
			     tcp_time_stamp(tp))) {
			NET_INC_STATS(sock_net(sk),
					LINUX_MIB_PAWSACTIVEREJECTED);
			goto reset_and_undo;
		}
```

Now ACK is acceptable.

"If the RST bit is set If the ACK was acceptable then signal the user "error: connection reset", drop the segment, enter CLOSED state, delete TCB, and return."
```c
		if (th->rst) {
			tcp_reset(sk, skb);
			goto discard;
		}
```
rfc793:

"fifth, if neither of the SYN or RST bits is set then drop the segment and return."
See note below!     --ANK(990513)
```c
		if (!th->syn)
			goto discard_and_undo;
```



```c
		/* rfc793:
		 *   "If the SYN bit is on ...
		 *    are acceptable then ...
		 *    (our SYN has been ACKed), change the connection
		 *    state to ESTABLISHED..."
		 */

		tcp_ecn_rcv_synack(tp, th);

		tcp_init_wl(tp, TCP_SKB_CB(skb)->seq);
		tcp_try_undo_spurious_syn(sk);
		tcp_ack(sk, skb, FLAG_SLOWPATH);

		/* Ok.. it's good. Set up sequence numbers and
		 * move to established.
		 */
		WRITE_ONCE(tp->rcv_nxt, TCP_SKB_CB(skb)->seq + 1);
		tp->rcv_wup = TCP_SKB_CB(skb)->seq + 1;

		/* RFC1323: The window in SYN & SYN/ACK segments is
		 * never scaled.
		 */
		tp->snd_wnd = ntohs(th->window);

		if (!tp->rx_opt.wscale_ok) {
			tp->rx_opt.snd_wscale = tp->rx_opt.rcv_wscale = 0;
			tp->window_clamp = min(tp->window_clamp, 65535U);
		}

		if (tp->rx_opt.saw_tstamp) {
			tp->rx_opt.tstamp_ok	   = 1;
			tp->tcp_header_len =
				sizeof(struct tcphdr) + TCPOLEN_TSTAMP_ALIGNED;
			tp->advmss	    -= TCPOLEN_TSTAMP_ALIGNED;
			tcp_store_ts_recent(tp);
		} else {
			tp->tcp_header_len = sizeof(struct tcphdr);
		}

		tcp_sync_mss(sk, icsk->icsk_pmtu_cookie);
		tcp_initialize_rcv_mss(sk);

		/* Remember, tcp_poll() does not lock socket!
		 * Change state from SYN-SENT only after copied_seq
		 * is initialized. */
		WRITE_ONCE(tp->copied_seq, tp->rcv_nxt);

		smc_check_reset_syn(tp);

		smp_mb();

		tcp_finish_connect(sk, skb);
```

fastopen

```c
		fastopen_fail = (tp->syn_fastopen || tp->syn_data) &&
				tcp_rcv_fastopen_synack(sk, skb, &foc);

		if (!sock_flag(sk, SOCK_DEAD)) {
			sk->sk_state_change(sk);
			sk_wake_async(sk, SOCK_WAKE_IO, POLL_OUT);
		}
		if (fastopen_fail)
			return -1;
		if (sk->sk_write_pending ||
		    icsk->icsk_accept_queue.rskq_defer_accept ||
		    inet_csk_in_pingpong_mode(sk)) {
			/* Save one ACK. Data will be ready after
			 * several ticks, if write_pending is set.
			 *
			 * It may be deleted, but with this feature tcpdumps
			 * look so _wonderfully_ clever, that I was not able
			 * to stand against the temptation 8)     --ANK
			 */
			inet_csk_schedule_ack(sk);
			tcp_enter_quickack_mode(sk, TCP_MAX_QUICKACKS);
			inet_csk_reset_xmit_timer(sk, ICSK_TIME_DACK,
						  TCP_DELACK_MAX, TCP_RTO_MAX);

discard:
			tcp_drop(sk, skb);
			return 0;
		} else {
			tcp_send_ack(sk);
		}
		return -1;
	}

	/* No ACK in the segment */

	if (th->rst) {
		/* rfc793:
		 * "If the RST bit is set
		 *
		 *      Otherwise (no ACK) drop the segment and return."
		 */

		goto discard_and_undo;
	}
```

PAWS check
```c
	if (tp->rx_opt.ts_recent_stamp && tp->rx_opt.saw_tstamp &&
	    tcp_paws_reject(&tp->rx_opt, 0))
		goto discard_and_undo;
```

SYN without ACK
```c
	if (th->syn) {
		/* We see SYN without ACK. It is attempt of
		 * simultaneous connect with crossed SYNs.
		 * Particularly, it can be connect to self.
		 */
		tcp_set_state(sk, TCP_SYN_RECV);

		if (tp->rx_opt.saw_tstamp) {
			tp->rx_opt.tstamp_ok = 1;
			tcp_store_ts_recent(tp);
			tp->tcp_header_len =
				sizeof(struct tcphdr) + TCPOLEN_TSTAMP_ALIGNED;
		} else {
			tp->tcp_header_len = sizeof(struct tcphdr);
		}

		WRITE_ONCE(tp->rcv_nxt, TCP_SKB_CB(skb)->seq + 1);
		WRITE_ONCE(tp->copied_seq, tp->rcv_nxt);
		tp->rcv_wup = TCP_SKB_CB(skb)->seq + 1;

		/* RFC1323: The window in SYN & SYN/ACK segments is
		 * never scaled.
		 */
		tp->snd_wnd    = ntohs(th->window);
		tp->snd_wl1    = TCP_SKB_CB(skb)->seq;
		tp->max_window = tp->snd_wnd;

		tcp_ecn_rcv_syn(tp, th);

		tcp_mtup_init(sk);
		tcp_sync_mss(sk, icsk->icsk_pmtu_cookie);
		tcp_initialize_rcv_mss(sk);

		tcp_send_synack(sk);
#if 0
		/* Note, we could accept data and URG from this segment.
		 * There are no obstacles to make this (except that we must
		 * either change tcp_recvmsg() to prevent it from returning data
		 * before 3WHS completes per RFC793, or employ TCP Fast Open).
		 *
		 * However, if we ignore data in ACKless segments sometimes,
		 * we have no reasons to accept it sometimes.
		 * Also, seems the code doing it in step6 of tcp_rcv_state_process
		 * is not flawless. So, discard packet for sanity.
		 * Uncomment this return to process the data.
		 */
		return -1;
#else
		goto discard;
#endif
	}
	/* "fifth, if neither of the SYN or RST bits is set then
	 * drop the segment and return."
	 */

discard_and_undo:
	tcp_clear_options(&tp->rx_opt);
	tp->rx_opt.mss_clamp = saved_clamp;
	goto discard;

reset_and_undo:
	tcp_clear_options(&tp->rx_opt);
	tp->rx_opt.mss_clamp = saved_clamp;
	return 1;
}
```

#### tcp_ack

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



## Server accept

### rcv SYN
see tcp_v4_do_rcv


#### tcp_rcv_state_process
This function implements the receiving procedure of RFC 793 for all states except ESTABLISHED and TIME_WAIT.

It's called from both tcp_v4_rcv and tcp_v6_rcv and should be address independent.

```c


int tcp_rcv_state_process(struct sock *sk, struct sk_buff *skb)
{
	struct tcp_sock *tp = tcp_sk(sk);
	struct inet_connection_sock *icsk = inet_csk(sk);
	const struct tcphdr *th = tcp_hdr(skb);
	struct request_sock *req;
	int queued = 0;
	bool acceptable;

	switch (sk->sk_state) {
	case TCP_CLOSE:
		goto discard;
```
ack when LISTEN, 
```c
	case TCP_LISTEN:
		if (th->ack)
			return 1;

		if (th->rst)
			goto discard;

```
syn when LISTEN, call [tcp_conn_request](/docs/CS/OS/Linux/TCP.md?id=tcp_conn_request)
```c
		if (th->syn) {
			if (th->fin)
				goto discard;
			/* It is possible that we process SYN packets from backlog,
			 * so we need to make sure to disable BH and RCU right there.
			 */
			rcu_read_lock();
			local_bh_disable();
			acceptable = icsk->icsk_af_ops->conn_request(sk, skb) >= 0;
			local_bh_enable();
			rcu_read_unlock();

			if (!acceptable)
				return 1;
			consume_skb(skb);
			return 0;
		}
		goto discard;
```

rcv syn+ack
```c

	case TCP_SYN_SENT:
		tp->rx_opt.saw_tstamp = 0;
		tcp_mstamp_refresh(tp);
		queued = tcp_rcv_synsent_state_process(sk, skb, th);
		if (queued >= 0)
			return queued;

		/* Do step6 onward by hand. */
		tcp_urg(sk, skb, th);
		__kfree_skb(skb);
		tcp_data_snd_check(sk);
		return 0;
	}

	tcp_mstamp_refresh(tp);
	tp->rx_opt.saw_tstamp = 0;
	req = rcu_dereference_protected(tp->fastopen_rsk,
					lockdep_sock_is_held(sk));
	if (req) {
		bool req_stolen;

		WARN_ON_ONCE(sk->sk_state != TCP_SYN_RECV &&
		    sk->sk_state != TCP_FIN_WAIT1);

		if (!tcp_check_req(sk, skb, req, true, &req_stolen))
			goto discard;
	}

	if (!th->ack && !th->rst && !th->syn)
		goto discard;

	if (!tcp_validate_incoming(sk, skb, th, 0))
		return 0;

	/* step 5: check the ACK field */
	acceptable = tcp_ack(sk, skb, FLAG_SLOWPATH |
				      FLAG_UPDATE_TS_RECENT |
				      FLAG_NO_CHALLENGE_ACK) > 0;

	if (!acceptable) {
		if (sk->sk_state == TCP_SYN_RECV)
			return 1;	/* send one RST */
		tcp_send_challenge_ack(sk, skb);
		goto discard;
	}
	switch (sk->sk_state) {
	case TCP_SYN_RECV:
		tp->delivered++; /* SYN-ACK delivery isn't tracked in tcp_ack */
		if (!tp->srtt_us)
			tcp_synack_rtt_meas(sk, req);

		if (req) {
			tcp_rcv_synrecv_state_fastopen(sk);
		} else {
			tcp_try_undo_spurious_syn(sk);
			tp->retrans_stamp = 0;
			tcp_init_transfer(sk, BPF_SOCK_OPS_PASSIVE_ESTABLISHED_CB,
					  skb);
			WRITE_ONCE(tp->copied_seq, tp->rcv_nxt);
		}
		smp_mb();
		tcp_set_state(sk, TCP_ESTABLISHED);
		sk->sk_state_change(sk);

		/* Note, that this wakeup is only for marginal crossed SYN case.
		 * Passively open sockets are not waked up, because
		 * sk->sk_sleep == NULL and sk->sk_socket == NULL.
		 */
		if (sk->sk_socket)
			sk_wake_async(sk, SOCK_WAKE_IO, POLL_OUT);

		tp->snd_una = TCP_SKB_CB(skb)->ack_seq;
		tp->snd_wnd = ntohs(th->window) << tp->rx_opt.snd_wscale;
		tcp_init_wl(tp, TCP_SKB_CB(skb)->seq);

		if (tp->rx_opt.tstamp_ok)
			tp->advmss -= TCPOLEN_TSTAMP_ALIGNED;

		if (!inet_csk(sk)->icsk_ca_ops->cong_control)
			tcp_update_pacing_rate(sk);

		/* Prevent spurious tcp_cwnd_restart() on first data packet */
		tp->lsndtime = tcp_jiffies32;

		tcp_initialize_rcv_mss(sk);
		tcp_fast_path_on(tp);
		break;

	case TCP_FIN_WAIT1: {
		int tmo;

		if (req)
			tcp_rcv_synrecv_state_fastopen(sk);

		if (tp->snd_una != tp->write_seq)
			break;

		tcp_set_state(sk, TCP_FIN_WAIT2);
		sk->sk_shutdown |= SEND_SHUTDOWN;

		sk_dst_confirm(sk);

		if (!sock_flag(sk, SOCK_DEAD)) {
			/* Wake up lingering close() */
			sk->sk_state_change(sk);
			break;
		}

		if (tp->linger2 < 0) {
			tcp_done(sk);
			NET_INC_STATS(sock_net(sk), LINUX_MIB_TCPABORTONDATA);
			return 1;
		}
		if (TCP_SKB_CB(skb)->end_seq != TCP_SKB_CB(skb)->seq &&
		    after(TCP_SKB_CB(skb)->end_seq - th->fin, tp->rcv_nxt)) {
			/* Receive out of order FIN after close() */
			if (tp->syn_fastopen && th->fin)
				tcp_fastopen_active_disable(sk);
			tcp_done(sk);
			NET_INC_STATS(sock_net(sk), LINUX_MIB_TCPABORTONDATA);
			return 1;
		}

		tmo = tcp_fin_time(sk);
		if (tmo > TCP_TIMEWAIT_LEN) {
			inet_csk_reset_keepalive_timer(sk, tmo - TCP_TIMEWAIT_LEN);
		} else if (th->fin || sock_owned_by_user(sk)) {
			/* Bad case. We could lose such FIN otherwise.
			 * It is not a big problem, but it looks confusing
			 * and not so rare event. We still can lose it now,
			 * if it spins in bh_lock_sock(), but it is really
			 * marginal case.
			 */
			inet_csk_reset_keepalive_timer(sk, tmo);
		} else {
			tcp_time_wait(sk, TCP_FIN_WAIT2, tmo);
			goto discard;
		}
		break;
	}

```

goto [tcp_time_wait](/docs/CS/OS/Linux/TCP.md?id=tcp_time_wait) when concurrent close
```c
	case TCP_CLOSING:
		if (tp->snd_una == tp->write_seq) {
			tcp_time_wait(sk, TCP_TIME_WAIT, 0);
			goto discard;
		}
		break;
```

rcv ACK
```c
	case TCP_LAST_ACK:
		if (tp->snd_una == tp->write_seq) {
			tcp_update_metrics(sk);
			tcp_done(sk);
			goto discard;
		}
		break;
	}
```


```c
	/* step 6: check the URG bit */
	tcp_urg(sk, skb, th);

	/* step 7: process the segment text */
	switch (sk->sk_state) {
	case TCP_CLOSE_WAIT:
	case TCP_CLOSING:
	case TCP_LAST_ACK:
		if (!before(TCP_SKB_CB(skb)->seq, tp->rcv_nxt)) {
			if (sk_is_mptcp(sk))
				mptcp_incoming_options(sk, skb);
			break;
		}
		fallthrough;
	case TCP_FIN_WAIT1:
	case TCP_FIN_WAIT2:
		/* RFC 793 says to queue data in these states,
		 * RFC 1122 says we MUST send a reset.
		 * BSD 4.4 also does reset.
		 */
		if (sk->sk_shutdown & RCV_SHUTDOWN) {
			if (TCP_SKB_CB(skb)->end_seq != TCP_SKB_CB(skb)->seq &&
			    after(TCP_SKB_CB(skb)->end_seq - th->fin, tp->rcv_nxt)) {
				NET_INC_STATS(sock_net(sk), LINUX_MIB_TCPABORTONDATA);
				tcp_reset(sk, skb);
				return 1;
			}
		}
		fallthrough;
	case TCP_ESTABLISHED:
		tcp_data_queue(sk, skb);
		queued = 1;
		break;
	}

	/* tcp_data could move socket to TIME-WAIT */
	if (sk->sk_state != TCP_CLOSE) {
		tcp_data_snd_check(sk);
		tcp_ack_snd_check(sk);
	}

	if (!queued) {
discard:
		tcp_drop(sk, skb);
	}
	return 0;
}
```


#### tcp_v4_cookie_check
```c

static struct sock *tcp_v4_cookie_check(struct sock *sk, struct sk_buff *skb)
{
#ifdef CONFIG_SYN_COOKIES
	const struct tcphdr *th = tcp_hdr(skb);

	if (!th->syn)
		sk = cookie_v4_check(sk, skb);
#endif
	return sk;
}
```

Check if a ack sequence number is a valid syncookie.
Return the decoded mss if it is, or 0 if not.

```c
// net/ipv4/syncookies.c
int __cookie_v4_check(const struct iphdr *iph, const struct tcphdr *th,
                    u32 cookie)
{
       __u32 seq = ntohl(th->seq) - 1;
       __u32 mssind = check_tcp_syn_cookie(cookie, iph->saddr, iph->daddr,
                                       th->source, th->dest, seq);

       return mssind < ARRAY_SIZE(msstab) ? msstab[mssind] : 0;
}
```

#### tcp_conn_request

tcp_conn_request for syn
```c

int tcp_conn_request(struct request_sock_ops *rsk_ops,
		     const struct tcp_request_sock_ops *af_ops,
		     struct sock *sk, struct sk_buff *skb)
{
	struct tcp_fastopen_cookie foc = { .len = -1 };
	__u32 isn = TCP_SKB_CB(skb)->tcp_tw_isn;
	struct tcp_options_received tmp_opt;
	struct tcp_sock *tp = tcp_sk(sk);
	struct net *net = sock_net(sk);
	struct sock *fastopen_sk = NULL;
	struct request_sock *req;
	bool want_cookie = false;
	struct dst_entry *dst;
	struct flowi fl;

	/* TW buckets are converted to open requests without
	 * limitations, they conserve resources and peer is
	 * evidently real one.
	 */
	 
```

tcp_syncookies == 2, skip check if check [reqsk queue is full]()
```c
	if ((net->ipv4.sysctl_tcp_syncookies == 2 ||
	     inet_csk_reqsk_queue_is_full(sk)) && !isn) {
		want_cookie = tcp_syn_flood_action(sk, rsk_ops->slab_name);
		if (!want_cookie)
			goto drop;
	}

```
check if [accept queue is full]()
```c
	if (sk_acceptq_is_full(sk)) {
		NET_INC_STATS(sock_net(sk), LINUX_MIB_LISTENOVERFLOWS);
		goto drop;
	}

	req = inet_reqsk_alloc(rsk_ops, sk, !want_cookie);
	if (!req)
		goto drop;

	req->syncookie = want_cookie;
	tcp_rsk(req)->af_specific = af_ops;
	tcp_rsk(req)->ts_off = 0;
#if IS_ENABLED(CONFIG_MPTCP)
	tcp_rsk(req)->is_mptcp = 0;
#endif

	tcp_clear_options(&tmp_opt);
	tmp_opt.mss_clamp = af_ops->mss_clamp;
	tmp_opt.user_mss  = tp->rx_opt.user_mss;
	tcp_parse_options(sock_net(sk), skb, &tmp_opt, 0,
			  want_cookie ? NULL : &foc);

	if (want_cookie && !tmp_opt.saw_tstamp)
		tcp_clear_options(&tmp_opt);

	if (IS_ENABLED(CONFIG_SMC) && want_cookie)
		tmp_opt.smc_ok = 0;

	tmp_opt.tstamp_ok = tmp_opt.saw_tstamp;
	tcp_openreq_init(req, &tmp_opt, skb, sk);
	inet_rsk(req)->no_srccheck = inet_sk(sk)->transparent;

	/* Note: tcp_v6_init_req() might override ir_iif for link locals */
	inet_rsk(req)->ir_iif = inet_request_bound_dev_if(sk, skb);

	dst = af_ops->route_req(sk, skb, &fl, req);
	if (!dst)
		goto drop_and_free;

	if (tmp_opt.tstamp_ok)
		tcp_rsk(req)->ts_off = af_ops->init_ts_off(net, skb);
```

drop if `qlen` > (`max_syn_backlog` >> 2)
```c
	if (!want_cookie && !isn) {
		/* Kill the following clause, if you dislike this way. */
		if (!net->ipv4.sysctl_tcp_syncookies &&
		    (net->ipv4.sysctl_max_syn_backlog - inet_csk_reqsk_queue_len(sk) <
		     (net->ipv4.sysctl_max_syn_backlog >> 2)) &&
		    !tcp_peer_is_proven(req, dst)) {
			/* Without syncookies last quarter of
			 * backlog is filled with destinations,
			 * proven to be alive.
			 * It means that we continue to communicate
			 * to destinations, already remembered
			 * to the moment of synflood.
			 */
			pr_drop_req(req, ntohs(tcp_hdr(skb)->source),
				    rsk_ops->family);
			goto drop_and_release;
		}

		isn = af_ops->init_seq(skb);
	}
```


```c
	tcp_ecn_create_request(req, skb, sk, dst);

	if (want_cookie) {
		isn = cookie_init_sequence(af_ops, sk, skb, &req->mss);
		if (!tmp_opt.tstamp_ok)
			inet_rsk(req)->ecn_ok = 0;
	}

	tcp_rsk(req)->snt_isn = isn;
	tcp_rsk(req)->txhash = net_tx_rndhash();
	tcp_rsk(req)->syn_tos = TCP_SKB_CB(skb)->ip_dsfield;
	tcp_openreq_init_rwin(req, sk, dst);
	sk_rx_queue_set(req_to_sk(req), skb);
	if (!want_cookie) {
		tcp_reqsk_record_syn(sk, req, skb);
		fastopen_sk = tcp_try_fastopen(sk, skb, req, &foc, dst);
	}
	if (fastopen_sk) {
		af_ops->send_synack(fastopen_sk, dst, &fl, req,
				    &foc, TCP_SYNACK_FASTOPEN, skb);
```
call [inet_csk_reqsk_queue_add](/docs/CS/OS/Linux/Calls.md?id=inet_csk_reqsk_queue_add)
```c
		/* Add the child socket directly into the accept queue */
		if (!inet_csk_reqsk_queue_add(sk, req, fastopen_sk)) {
			reqsk_fastopen_remove(fastopen_sk, req, false);
			bh_unlock_sock(fastopen_sk);
			sock_put(fastopen_sk);
			goto drop_and_free;
		}
```

```c
		sk->sk_data_ready(sk);
		bh_unlock_sock(fastopen_sk);
		sock_put(fastopen_sk);
	} else {
		tcp_rsk(req)->tfo_listener = false;
		if (!want_cookie)
			inet_csk_reqsk_queue_hash_add(sk, req,
				tcp_timeout_init((struct sock *)req));
		af_ops->send_synack(sk, dst, &fl, req, &foc,
				    !want_cookie ? TCP_SYNACK_NORMAL :
						   TCP_SYNACK_COOKIE,
				    skb);
		if (want_cookie) {
			reqsk_free(req);
			return 0;
		}
	}
	reqsk_put(req);
	return 0;

drop_and_release:
	dst_release(dst);
drop_and_free:
	__reqsk_free(req);
drop:
	tcp_listendrop(sk);
	return 0;
}
```
##### queue is full


```c

static inline int inet_csk_reqsk_queue_is_full(const struct sock *sk)
{
	return inet_csk_reqsk_queue_len(sk) >= sk->sk_max_ack_backlog;
}
```


> Note: If you think the test should be:
> return READ_ONCE(sk->sk_ack_backlog) >= READ_ONCE(sk->sk_max_ack_backlog);
> Then please take a look at commit 64a146513f8f ("[NET]: Revert incorrect accept queue backlog changes.")
```c
// 
static inline bool sk_acceptq_is_full(const struct sock *sk)
{
	return READ_ONCE(sk->sk_ack_backlog) > READ_ONCE(sk->sk_max_ack_backlog);
}
```

##### inet_csk_reqsk_queue_hash_add
1. reqsk_queue_hash_req
2. [accept queue added](/docs/CS/OS/Linux/Calls.md?id=accept-queue) inc young and `qlen`
```c

void inet_csk_reqsk_queue_hash_add(struct sock *sk, struct request_sock *req,
				   unsigned long timeout)
{
	reqsk_queue_hash_req(req, timeout);
	inet_csk_reqsk_queue_added(sk); /** atomic_inc young and qlen of queue */
}



static void reqsk_queue_hash_req(struct request_sock *req,
				 unsigned long timeout)
{
	timer_setup(&req->rsk_timer, reqsk_timer_handler, TIMER_PINNED);
	mod_timer(&req->rsk_timer, jiffies + timeout);

	inet_ehash_insert(req_to_sk(req), NULL, NULL);
	/* before letting lookups find us, make sure all req fields
	 * are committed to memory and refcnt initialized.
	 */
	smp_wmb();
	refcount_set(&req->rsk_refcnt, 2 + 1);
}
```
##### inet_ehash_insert
Insert a socket into ehash, and eventually remove another one
(The another one can be a `SYN_RECV` or `TIMEWAIT`)

If an existing socket already exists, socket sk is not inserted,
and sets `found_dup_sk` parameter to true.
```c
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



### send SYNACK

#### tcp_send_synack
```c

/* Send a crossed SYN-ACK during socket establishment.
 * WARNING: This routine must only be called when we have already sent
 * a SYN packet that crossed the incoming SYN that caused this routine
 * to get called. If this assumption fails then the initial rcv_wnd
 * and rcv_wscale values will not be correct.
 */
int tcp_send_synack(struct sock *sk)
{
	struct sk_buff *skb;

	skb = tcp_rtx_queue_head(sk);
	if (!skb || !(TCP_SKB_CB(skb)->tcp_flags & TCPHDR_SYN)) {
		pr_err("%s: wrong queue state\n", __func__);
		return -EFAULT;
	}
	if (!(TCP_SKB_CB(skb)->tcp_flags & TCPHDR_ACK)) {
		if (skb_cloned(skb)) {
			struct sk_buff *nskb;

			tcp_skb_tsorted_save(skb) {
				nskb = skb_copy(skb, GFP_ATOMIC);
			} tcp_skb_tsorted_restore(skb);
			if (!nskb)
				return -ENOMEM;
			INIT_LIST_HEAD(&nskb->tcp_tsorted_anchor);
			tcp_highest_sack_replace(sk, skb, nskb);
			tcp_rtx_queue_unlink_and_free(skb, sk);
			__skb_header_release(nskb);
			tcp_rbtree_insert(&sk->tcp_rtx_queue, nskb);
			sk_wmem_queued_add(sk, nskb->truesize);
			sk_mem_charge(sk, nskb->truesize);
			skb = nskb;
		}

		TCP_SKB_CB(skb)->tcp_flags |= TCPHDR_ACK;
		tcp_ecn_send_synack(sk, skb);
	}
	return tcp_transmit_skb(sk, skb, 1, GFP_ATOMIC);
}

```
#### tcp_v4_send_synack

tcp_v4_send_synack

Send a SYN-ACK after having received a SYN.

This still operates on a request_sock only, not on a big socket.
```c


/*
 *	Send a SYN-ACK after having received a SYN.
 *	This still operates on a request_sock only, not on a big
 *	socket.
 */
static int tcp_v4_send_synack(const struct sock *sk, struct dst_entry *dst,
			      struct flowi *fl,
			      struct request_sock *req,
			      struct tcp_fastopen_cookie *foc,
			      enum tcp_synack_type synack_type,
			      struct sk_buff *syn_skb)
{
	const struct inet_request_sock *ireq = inet_rsk(req);
	struct flowi4 fl4;
	int err = -1;
	struct sk_buff *skb;
	u8 tos;

	/* First, grab a route. */
	if (!dst && (dst = inet_csk_route_req(sk, &fl4, req)) == NULL)
		return -1;

	skb = tcp_make_synack(sk, dst, req, foc, synack_type, syn_skb);

	if (skb) {
		__tcp_v4_send_check(skb, ireq->ir_loc_addr, ireq->ir_rmt_addr);

		tos = sock_net(sk)->ipv4.sysctl_tcp_reflect_tos ?
				(tcp_rsk(req)->syn_tos & ~INET_ECN_MASK) |
				(inet_sk(sk)->tos & INET_ECN_MASK) :
				inet_sk(sk)->tos;

		if (!INET_ECN_is_capable(tos) &&
		    tcp_bpf_ca_needs_ecn((struct sock *)req))
			tos |= INET_ECN_ECT_0;

		rcu_read_lock();
		err = ip_build_and_send_pkt(skb, sk, ireq->ir_loc_addr,
					    ireq->ir_rmt_addr,
					    rcu_dereference(ireq->ireq_opt),
					    tos);
		rcu_read_unlock();
		err = net_xmit_eval(err);
	}

	return err;
}
```

#### tcp_make_synack 
Allocate one skb and build a SYNACK packet.
```c
struct sk_buff *tcp_make_synack(const struct sock *sk, struct dst_entry *dst,
				struct request_sock *req,
				struct tcp_fastopen_cookie *foc,
				enum tcp_synack_type synack_type,
				struct sk_buff *syn_skb)
{
	struct inet_request_sock *ireq = inet_rsk(req);
	const struct tcp_sock *tp = tcp_sk(sk);
	struct tcp_md5sig_key *md5 = NULL;
	struct tcp_out_options opts;
	struct sk_buff *skb;
	int tcp_header_size;
	struct tcphdr *th;
	int mss;
	u64 now;

	skb = alloc_skb(MAX_TCP_HEADER, GFP_ATOMIC);
	if (unlikely(!skb)) {
		dst_release(dst);
		return NULL;
	}
	/* Reserve space for headers. */
	skb_reserve(skb, MAX_TCP_HEADER);

	switch (synack_type) {
	case TCP_SYNACK_NORMAL:
		skb_set_owner_w(skb, req_to_sk(req));
		break;
	case TCP_SYNACK_COOKIE:
		/* Under synflood, we do not attach skb to a socket,
		 * to avoid false sharing.
		 */
		break;
	case TCP_SYNACK_FASTOPEN:
		/* sk is a const pointer, because we want to express multiple
		 * cpu might call us concurrently.
		 * sk->sk_wmem_alloc in an atomic, we can promote to rw.
		 */
		skb_set_owner_w(skb, (struct sock *)sk);
		break;
	}
	skb_dst_set(skb, dst);

	mss = tcp_mss_clamp(tp, dst_metric_advmss(dst));

	memset(&opts, 0, sizeof(opts));
	now = tcp_clock_ns();
#ifdef CONFIG_SYN_COOKIES
	if (unlikely(synack_type == TCP_SYNACK_COOKIE && ireq->tstamp_ok))
		skb->skb_mstamp_ns = cookie_init_timestamp(req, now);
	else
#endif
	{
		skb->skb_mstamp_ns = now;
		if (!tcp_rsk(req)->snt_synack) /* Timestamp first SYNACK */
			tcp_rsk(req)->snt_synack = tcp_skb_timestamp_us(skb);
	}

#ifdef CONFIG_TCP_MD5SIG
	rcu_read_lock();
	md5 = tcp_rsk(req)->af_specific->req_md5_lookup(sk, req_to_sk(req));
#endif
	skb_set_hash(skb, tcp_rsk(req)->txhash, PKT_HASH_TYPE_L4);
	/* bpf program will be interested in the tcp_flags */
	TCP_SKB_CB(skb)->tcp_flags = TCPHDR_SYN | TCPHDR_ACK;
	tcp_header_size = tcp_synack_options(sk, req, mss, skb, &opts, md5,
					     foc, synack_type,
					     syn_skb) + sizeof(*th);

	skb_push(skb, tcp_header_size);
	skb_reset_transport_header(skb);

	th = (struct tcphdr *)skb->data;
	memset(th, 0, sizeof(struct tcphdr));
	th->syn = 1;
	th->ack = 1;
	tcp_ecn_make_synack(req, th);
	th->source = htons(ireq->ir_num);
	th->dest = ireq->ir_rmt_port;
	skb->mark = ireq->ir_mark;
	skb->ip_summed = CHECKSUM_PARTIAL;
	th->seq = htonl(tcp_rsk(req)->snt_isn);
	/* XXX data is queued and acked as is. No buffer/window check */
	th->ack_seq = htonl(tcp_rsk(req)->rcv_nxt);

	/* RFC1323: The window in SYN & SYN/ACK segments is never scaled. */
	th->window = htons(min(req->rsk_rcv_wnd, 65535U));
	tcp_options_write((__be32 *)(th + 1), NULL, &opts);
	th->doff = (tcp_header_size >> 2);
	__TCP_INC_STATS(sock_net(sk), TCP_MIB_OUTSEGS);

#ifdef CONFIG_TCP_MD5SIG
	/* Okay, we have all we need - do the md5 hash if needed */
	if (md5)
		tcp_rsk(req)->af_specific->calc_md5_hash(opts.hash_location,
					       md5, req_to_sk(req), skb);
	rcu_read_unlock();
#endif

	bpf_skops_write_hdr_opt((struct sock *)sk, skb, req, syn_skb,
				synack_type, &opts);

	skb->skb_mstamp_ns = now;
	tcp_add_tx_delay(skb, tp);

	return skb;
}
```


### rcv ACK
see tcp_v4_do-rcv

#### tcp_child_process
Queue segment on the new socket if the new socket is active, otherwise we just shortcircuit this and continue with the new socket.

For the vast majority of cases child->sk_state will be TCP_SYN_RECV when entering. But other states are possible due to a race condition where after __inet_lookup_established() fails but before the listener locked is obtained, other packets cause the same connection to be created.
```c


int tcp_child_process(struct sock *parent, struct sock *child,
		      struct sk_buff *skb)
	__releases(&((child)->sk_lock.slock))
{
	int ret = 0;
	int state = child->sk_state;

	/* record NAPI ID of child */
	sk_mark_napi_id(child, skb);

	tcp_segs_in(tcp_sk(child), skb);
	if (!sock_owned_by_user(child)) {
		ret = tcp_rcv_state_process(child, skb);
		/* Wakeup parent, send SIGIO */
		if (state == TCP_SYN_RECV && child->sk_state != state)
			parent->sk_data_ready(parent);
	} else {
		/* Alas, it is possible again, because we do lookup
		 * in main socket hash table and lock on listening
		 * socket does not protect us more.
		 */
		__sk_add_backlog(child, skb);
	}

	bh_unlock_sock(child);
	sock_put(child);
	return ret;
}
```


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

## References
1. [Analysis_TCP_in_Linux](https://github.com/fzyz999/Analysis_TCP_in_Linux)
2. [Congestion Control - MIT6.976](https://web.mit.edu/6.976/www/notes/Notes3.pdf)