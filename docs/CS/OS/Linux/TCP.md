## Introduction


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


## send



### tcp_sendmsg
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


mark_push
```c
static inline void tcp_mark_push(struct tcp_sock *tp, struct sk_buff *skb)
{
       TCP_SKB_CB(skb)->tcp_flags |= TCPHDR_PSH;
       tp->pushed_seq = tp->write_seq;
}
```


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


tcp_push_one

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

### write

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

    /** add ip_queue_xmit   */
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



## recv

recv read recvfrom at application layer


### tcp_v4_do_rcv
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



#### tcp_recvmsg

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

       lock_sock(sk);
       ret = tcp_recvmsg_locked(sk, msg, len, nonblock, flags, &tss,
                             &cmsg_flags);
       release_sock(sk);

       if (cmsg_flags && ret >= 0) {
              if (cmsg_flags & TCP_CMSG_TS)
                     tcp_recv_timestamp(msg, sk, &tss);
              if (cmsg_flags & TCP_CMSG_INQ) {
                     inq = tcp_inq_hint(sk);
                     put_cmsg(msg, SOL_TCP, TCP_CM_INQ, sizeof(inq), &inq);
              }
       }
       return ret;
}
```

