





```c
// socket.c
SYSCALL_DEFINE2(listen, int, fd, int, backlog)
{
       return __sys_listen(fd, backlog);
}

/*
 *     Perform a listen. Basically, we allow the protocol to do anything
 *     necessary for a listen, and if that works, we mark the socket as
 *     ready for listening.
 */

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



Max_ack_backlog is min of backlog / net.core.somaxconn

```c
/* af_inet.c
 *     Move a socket into listening state.
 */
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

       WRITE_ONCE(sk->sk_max_ack_backlog, backlog);
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
EXPORT_SYMBOL(inet_listen);
```





```c
// inet_connection_sock.c
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
              err = sk->sk_prot->hash(sk);

              if (likely(!err))
                     return 0;
       }

       inet_sk_set_state(sk, TCP_CLOSE);
       return err;
}
EXPORT_SYMBOL_GPL(inet_csk_listen_start);
```





```c
/* request_sock.c
 * Maximum number of SYN_RECV sockets in queue per LISTEN socket.
 * One SYN_RECV socket costs about 80bytes on a 32bit machine.
 * It would be better to replace it with a global counter for all sockets
 * but then some measure against one socket starving all other sockets
 * would be needed.
 *
 * The minimum value of it is 128. Experiments with real servers show that
 * it is absolutely not enough even at 100conn/sec. 256 cures most
 * of problems.
 * This value is adjusted to 128 for low memory machines,
 * and it will increase in proportion to the memory of machine.
 * Note : Dont forget somaxconn that may limit backlog too.
 */

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





```c
/** inet_connection_sock.h

inet_connection_sock - INET connection oriented sock
 *
 * @icsk_accept_queue:    FIFO of established children
 * @icsk_bind_hash:       Bind node
 * @icsk_timeout:         Timeout
 * @icsk_retransmit_timer: Resend (no ack)
 * @icsk_rto:            Retransmit timeout
 * @icsk_pmtu_cookie      Last pmtu seen by socket
 * @icsk_ca_ops                  Pluggable congestion control hook
 * @icsk_af_ops                  Operations which are AF_INET{4,6} specific
 * @icsk_ulp_ops          Pluggable ULP control hook
 * @icsk_ulp_data         ULP private data
 * @icsk_clean_acked      Clean acked data hook
 * @icsk_listen_portaddr_node  hash to the portaddr listener hashtable
 * @icsk_ca_state:        Congestion control state
 * @icsk_retransmits:     Number of unrecovered [RTO] timeouts
 * @icsk_pending:         Scheduled timer event
 * @icsk_backoff:         Backoff
 * @icsk_syn_retries:      Number of allowed SYN (or equivalent) retries
 * @icsk_probes_out:      unanswered 0 window probes
 * @icsk_ext_hdr_len:     Network protocol overhead (IP/IPv6 options)
 * @icsk_ack:            Delayed ACK control data
 * @icsk_mtup;           MTU probing control data
 * @icsk_probes_tstamp:    Probe timestamp (cleared by non-zero window ack)
 * @icsk_user_timeout:    TCP_USER_TIMEOUT value
 */
struct inet_connection_sock {
       /* inet_sock has to be the first member! */
       struct inet_sock         icsk_inet;
       struct request_sock_queue icsk_accept_queue;
       struct inet_bind_bucket          *icsk_bind_hash;
       unsigned long           icsk_timeout;
       struct timer_list        icsk_retransmit_timer;
       struct timer_list        icsk_delack_timer;
       __u32                  icsk_rto;
       __u32                     icsk_rto_min;
       __u32                     icsk_delack_max;
       __u32                  icsk_pmtu_cookie;
       const struct tcp_congestion_ops *icsk_ca_ops;
       const struct inet_connection_sock_af_ops *icsk_af_ops;
       const struct tcp_ulp_ops  *icsk_ulp_ops;
       void __rcu              *icsk_ulp_data;
       void (*icsk_clean_acked)(struct sock *sk, u32 acked_seq);
       struct hlist_node         icsk_listen_portaddr_node;
       unsigned int            (*icsk_sync_mss)(struct sock *sk, u32 pmtu);
       __u8                   icsk_ca_state:5,
                              icsk_ca_initialized:1,
                              icsk_ca_setsockopt:1,
                              icsk_ca_dst_locked:1;
       __u8                   icsk_retransmits;
       __u8                   icsk_pending;
       __u8                   icsk_backoff;
       __u8                   icsk_syn_retries;
       __u8                   icsk_probes_out;
       __u16                  icsk_ext_hdr_len;
       struct {
              __u8            pending;      /* ACK is pending                      */
              __u8            quick;        /* Scheduled number of quick acks        */
              __u8            pingpong;     /* The session is interactive           */
              __u8            retry;        /* Number of attempts                  */
              __u32           ato;         /* Predicted tick of soft clock          */
              unsigned long    timeout;      /* Currently scheduled timeout                  */
              __u32           lrcvtime;     /* timestamp of last received data packet */
              __u16           last_seg_size; /* Size of last incoming segment         */
              __u16           rcv_mss;      /* MSS used for delayed ACK decisions    */
       } icsk_ack;
       struct {
              /* Range of MTUs to search */
              int             search_high;
              int             search_low;

              /* Information on the current probe. */
              u32             probe_size:31,
              /* Is the MTUP feature enabled for this connection? */
                              enabled:1;

              u32             probe_timestamp;
       } icsk_mtup;
       u32                    icsk_probes_tstamp;
       u32                    icsk_user_timeout;

       u64                    icsk_ca_priv[104 / sizeof(u64)];
#define ICSK_CA_PRIV_SIZE      (13 * sizeof(u64))
};
```





```c
/** request_sock.h 

struct request_sock_queue - queue of request_socks
 *
 * @rskq_accept_head - FIFO head of established children
 * @rskq_accept_tail - FIFO tail of established children
 * @rskq_defer_accept - User waits for some data after accept()
 *
 */
struct request_sock_queue {
       spinlock_t            rskq_lock;
       u8                   rskq_defer_accept;

       u32                  synflood_warned;
       atomic_t              qlen;
       atomic_t              young;

       struct request_sock    *rskq_accept_head;
       struct request_sock    *rskq_accept_tail;
       struct fastopen_queue  fastopenq;  /* Check max_qlen != 0 to determine
                                        * if TFO is enabled.
                                        */
};
```





listen 最主要的工作就是**申请和初始化接收队列，包括全连接队列和半连接队列**。其中全连接队列是一个链表，而半连接队列由于需要快速的查找，所以使用的是一个哈希表（其实半连接队列更准确的的叫法应该叫半连接哈希表）。





**1.全连接队列的长度**
对于全连接队列来说，其最大长度是 listen 时传入的 backlog 和 net.core.somaxconn 之间较小的那个值。如果需要加大全连接队列长度，那么就是调整 backlog 和 somaxconn。

**2.半连接队列的长度**
在 listen 的过程中，内核我们也看到了对于半连接队列来说，其最大长度是 min(backlog, somaxconn, tcp_max_syn_backlog) + 1 再上取整到 2 的幂次，但最小不能小于16。如果需要加大半连接队列长度，那么需要一并考虑 backlog，somaxconn 和 tcp_max_syn_backlog 这三个参数。网上任何告诉你修改某一个参数就能提高半连接队列长度的文章都是错的。