## Introduction



struct sock_common - minimal network layer representation of sockets

This is the minimal network layer representation of sockets, the header for struct sock and struct inet_timewait_sock.

```c
// include/net/sock.h
struct sock_common {
       /* skc_daddr and skc_rcv_saddr must be grouped on a 8 bytes aligned
        * address on 64bit arches : cf INET_MATCH()
        */
       union {
              __addrpair     skc_addrpair;
              struct {
                     __be32 skc_daddr;
                     __be32 skc_rcv_saddr;
              };
       };
       union  {
              unsigned int   skc_hash;
              __u16         skc_u16hashes[2];
       };
       /* skc_dport && skc_num must be grouped as well */
       union {
              __portpair     skc_portpair;
              struct {
                     __be16 skc_dport;
                     __u16  skc_num;
              };
       };

       unsigned short        skc_family;
       volatile unsigned char skc_state;
       unsigned char         skc_reuse:4;
       unsigned char         skc_reuseport:1;
       unsigned char         skc_ipv6only:1;
       unsigned char         skc_net_refcnt:1;
       int                  skc_bound_dev_if;
       union {
              struct hlist_node      skc_bind_node;
              struct hlist_node      skc_portaddr_node;
       };
       struct proto          *skc_prot;
       possible_net_t        skc_net;

#if IS_ENABLED(CONFIG_IPV6)
       struct in6_addr               skc_v6_daddr;
       struct in6_addr               skc_v6_rcv_saddr;
#endif

       atomic64_t            skc_cookie;

       /* following fields are padding to force
        * offset(struct sock, sk_refcnt) == 128 on 64bit arches
        * assuming IPV6 is enabled. We use this padding differently
        * for different kind of 'sockets'
        */
       union {
              unsigned long  skc_flags;
              struct sock    *skc_listener; /* request_sock */
              struct inet_timewait_death_row *skc_tw_dr; /* inet_timewait_sock */
       };
       /*
        * fields between dontcopy_begin/dontcopy_end
        * are not copied in sock_copy()
        */
       /* private: */
       int                  skc_dontcopy_begin[0];
       /* public: */
       union {
              struct hlist_node      skc_node;
              struct hlist_nulls_node skc_nulls_node;
       };
       unsigned short        skc_tx_queue_mapping;
#ifdef CONFIG_SOCK_RX_QUEUE_MAPPING
       unsigned short        skc_rx_queue_mapping;
#endif
       union {
              int           skc_incoming_cpu;
              u32           skc_rcv_wnd;
              u32           skc_tw_rcv_nxt; /* struct tcp_timewait_sock  */
       };

       refcount_t            skc_refcnt;
       /* private: */
       int                     skc_dontcopy_end[0];
       union {
              u32           skc_rxhash;
              u32           skc_window_clamp;
              u32           skc_tw_snd_nxt; /* struct tcp_timewait_sock */
       };
       /* public: */
};
```



struct sock - network layer representation of sockets

```c
// include/net/sock.h
struct sock {
       /*
        * Now struct inet_timewait_sock also uses sock_common, so please just
        * don't add nothing before this first member (__sk_common) --acme
        */
       struct sock_common     __sk_common;
#define sk_node                      __sk_common.skc_node
#define sk_nulls_node         __sk_common.skc_nulls_node
#define sk_refcnt             __sk_common.skc_refcnt
#define sk_tx_queue_mapping    __sk_common.skc_tx_queue_mapping
#ifdef CONFIG_SOCK_RX_QUEUE_MAPPING
#define sk_rx_queue_mapping    __sk_common.skc_rx_queue_mapping
#endif

#define sk_dontcopy_begin      __sk_common.skc_dontcopy_begin
#define sk_dontcopy_end               __sk_common.skc_dontcopy_end
#define sk_hash                      __sk_common.skc_hash
#define sk_portpair           __sk_common.skc_portpair
#define sk_num               __sk_common.skc_num
#define sk_dport              __sk_common.skc_dport
#define sk_addrpair           __sk_common.skc_addrpair
#define sk_daddr              __sk_common.skc_daddr
#define sk_rcv_saddr          __sk_common.skc_rcv_saddr
#define sk_family             __sk_common.skc_family
#define sk_state              __sk_common.skc_state
#define sk_reuse              __sk_common.skc_reuse
#define sk_reuseport          __sk_common.skc_reuseport
#define sk_ipv6only           __sk_common.skc_ipv6only
#define sk_net_refcnt         __sk_common.skc_net_refcnt
#define sk_bound_dev_if               __sk_common.skc_bound_dev_if
#define sk_bind_node          __sk_common.skc_bind_node
#define sk_prot                      __sk_common.skc_prot
#define sk_net               __sk_common.skc_net
#define sk_v6_daddr           __sk_common.skc_v6_daddr
#define sk_v6_rcv_saddr        __sk_common.skc_v6_rcv_saddr
#define sk_cookie             __sk_common.skc_cookie
#define sk_incoming_cpu               __sk_common.skc_incoming_cpu
#define sk_flags              __sk_common.skc_flags
#define sk_rxhash             __sk_common.skc_rxhash

       socket_lock_t         sk_lock;
       atomic_t              sk_drops;
       int                  sk_rcvlowat;
       struct sk_buff_head    sk_error_queue;
       struct sk_buff        *sk_rx_skb_cache;
       struct sk_buff_head    sk_receive_queue;
       /*
        * The backlog queue is special, it is always used with
        * the per-socket spinlock held and requires low latency
        * access. Therefore we special case it's implementation.
        * Note : rmem_alloc is in this structure to fill a hole
        * on 64bit arches, not because its logically part of
        * backlog.
        */
       struct {
              atomic_t       rmem_alloc;
              int           len;
              struct sk_buff *head;
              struct sk_buff *tail;
       } sk_backlog;
#define sk_rmem_alloc sk_backlog.rmem_alloc

       int                  sk_forward_alloc;
#ifdef CONFIG_NET_RX_BUSY_POLL
       unsigned int          sk_ll_usec;
       /* ===== mostly read cache line ===== */
       unsigned int          sk_napi_id;
#endif
       int                  sk_rcvbuf;

       struct sk_filter __rcu *sk_filter;
       union {
              struct socket_wq __rcu *sk_wq;
              /* private: */
              struct socket_wq       *sk_wq_raw;
              /* public: */
       };
#ifdef CONFIG_XFRM
       struct xfrm_policy __rcu *sk_policy[2];
#endif
       struct dst_entry       *sk_rx_dst;
       struct dst_entry __rcu *sk_dst_cache;
       atomic_t              sk_omem_alloc;
       int                  sk_sndbuf;

       /* ===== cache line for TX ===== */
       int                  sk_wmem_queued;
       refcount_t            sk_wmem_alloc;
       unsigned long         sk_tsq_flags;
       union {
              struct sk_buff *sk_send_head;
              struct rb_root tcp_rtx_queue;
       };
       struct sk_buff        *sk_tx_skb_cache;
       struct sk_buff_head    sk_write_queue;
       __s32                sk_peek_off;
       int                  sk_write_pending;
       __u32                sk_dst_pending_confirm;
       u32                  sk_pacing_status; /* see enum sk_pacing */
       long                 sk_sndtimeo;
       struct timer_list      sk_timer;
       __u32                sk_priority;
       __u32                sk_mark;
       unsigned long         sk_pacing_rate; /* bytes per second */
       unsigned long         sk_max_pacing_rate;
       struct page_frag       sk_frag;
       netdev_features_t      sk_route_caps;
       netdev_features_t      sk_route_nocaps;
       netdev_features_t      sk_route_forced_caps;
       int                  sk_gso_type;
       unsigned int          sk_gso_max_size;
       gfp_t                sk_allocation;
       __u32                sk_txhash;

       /*
        * Because of non atomicity rules, all
        * changes are protected by socket lock.
        */
       u8                   sk_padding : 1,
                            sk_kern_sock : 1,
                            sk_no_check_tx : 1,
                            sk_no_check_rx : 1,
                            sk_userlocks : 4;
       u8                   sk_pacing_shift;
       u16                  sk_type;
       u16                  sk_protocol;
       u16                  sk_gso_max_segs;
       unsigned long          sk_lingertime;
       struct proto          *sk_prot_creator;
       rwlock_t              sk_callback_lock;
       int                  sk_err,
                            sk_err_soft;
       u32                  sk_ack_backlog;
       u32                  sk_max_ack_backlog;
       kuid_t               sk_uid;
#ifdef CONFIG_NET_RX_BUSY_POLL
       u8                   sk_prefer_busy_poll;
       u16                  sk_busy_poll_budget;
#endif
       struct pid            *sk_peer_pid;
       const struct cred      *sk_peer_cred;
       long                 sk_rcvtimeo;
       ktime_t                      sk_stamp;
#if BITS_PER_LONG==32
       seqlock_t             sk_stamp_seq;
#endif
       u16                  sk_tsflags;
       u8                   sk_shutdown;
       u32                  sk_tskey;
       atomic_t              sk_zckey;

       u8                   sk_clockid;
       u8                   sk_txtime_deadline_mode : 1,
                            sk_txtime_report_errors : 1,
                            sk_txtime_unused : 6;

       struct socket         *sk_socket;
       void                 *sk_user_data;
#ifdef CONFIG_SECURITY
       void                 *sk_security;
#endif
       struct sock_cgroup_data        sk_cgrp_data;
       struct mem_cgroup      *sk_memcg;
       void                 (*sk_state_change)(struct sock *sk);
       void                 (*sk_data_ready)(struct sock *sk);
       void                 (*sk_write_space)(struct sock *sk);
       void                 (*sk_error_report)(struct sock *sk);
       int                  (*sk_backlog_rcv)(struct sock *sk,
                                            struct sk_buff *skb);
#ifdef CONFIG_SOCK_VALIDATE_XMIT
       struct sk_buff*               (*sk_validate_xmit_skb)(struct sock *sk,
                                                 struct net_device *dev,
                                                 struct sk_buff *skb);
#endif
       void                    (*sk_destruct)(struct sock *sk);
       struct sock_reuseport __rcu    *sk_reuseport_cb;
#ifdef CONFIG_BPF_SYSCALL
       struct bpf_local_storage __rcu *sk_bpf_storage;
#endif
       struct rcu_head               sk_rcu;
};
```



#### request_sock

struct request_sock - mini sock to represent a connection request

```c
// include/net/request_sock.h
struct request_sock {
       struct sock_common            __req_common;
#define rsk_refcnt                   __req_common.skc_refcnt
#define rsk_hash                     __req_common.skc_hash
#define rsk_listener                 __req_common.skc_listener
#define rsk_window_clamp              __req_common.skc_window_clamp
#define rsk_rcv_wnd                  __req_common.skc_rcv_wnd

       struct request_sock           *dl_next;
       u16                         mss;
       u8                          num_retrans; /* number of retransmits */
       u8                          syncookie:1; /* syncookie: encode tcpopts in timestamp */
       u8                          num_timeout:7; /* number of timeouts */
       u32                         ts_recent;
       struct timer_list             rsk_timer;
       const struct request_sock_ops  *rsk_ops;
       struct sock                  *sk;
       struct saved_syn              *saved_syn;
       u32                         secid;
       u32                         peer_secid;
};
```



#### socket buffer

struct sk_buff - socket buffer





```c
struct sk_buff {
union {
		struct {
			/* These two members must be first. */
			struct sk_buff		*next;
			struct sk_buff		*prev;

			union {
				struct net_device	*dev;
				/* Some protocols might use this space to store information,
				 * while device pointer would be NULL.
				 * UDP receive path is one user.
				 */
				unsigned long		dev_scratch;
			};
		};
		struct rb_node		rbnode; /* used in netem, ip4 defrag, and tcp stack */
		struct list_head	list;
	};

	union {
		struct sock		*sk;
		int			ip_defrag_offset;
	};

	union {
		ktime_t		tstamp;
		u64		skb_mstamp_ns; /* earliest departure time */
	};

  // ...
}
```