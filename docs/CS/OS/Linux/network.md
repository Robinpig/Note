## Introduction



Linux provide drivers and protocols
driver：drivers/net/ethernet
protocol: kernel & net



## init



## init softirq
based on [softirq](/docs/CS/OS/Linux/Interrupt.md?id=spawn_ksoftirqd)


### init net dev

initcall see [kernel_init](/docs/CS/OS/Linux/init.md?id=kernel_init)

```c
// net/core/dev.c
subsys_initcall(net_dev_init);
```



Initialize the DEV module. At boot time this walks the device list and
unhooks any devices that fail to initialise (normally hardware not
present) and leaves us with a valid list of present and active devices.

This is called single threaded during boot, so no need
to take the rtnl semaphore.

registe [net_rx_action](/docs/CS/OS/Linux/network.md?id=net_rx_action)
```c
// net/core/dev.c
static int __init net_dev_init(void)
{
	int i, rc = -ENOMEM;

	BUG_ON(!dev_boot_phase);

	if (dev_proc_init())
		goto out;

	if (netdev_kobject_init())
		goto out;

	INIT_LIST_HEAD(&ptype_all);
	for (i = 0; i < PTYPE_HASH_SIZE; i++)
		INIT_LIST_HEAD(&ptype_base[i]);

	INIT_LIST_HEAD(&offload_base);

	if (register_pernet_subsys(&netdev_net_ops))
		goto out;

	/*
	 *	Initialise the packet receive queues.
	 */

	for_each_possible_cpu(i) {
		struct work_struct *flush = per_cpu_ptr(&flush_works, i);
		struct softnet_data *sd = &per_cpu(softnet_data, i);

		INIT_WORK(flush, flush_backlog);

		skb_queue_head_init(&sd->input_pkt_queue);
		skb_queue_head_init(&sd->process_queue);
#ifdef CONFIG_XFRM_OFFLOAD
		skb_queue_head_init(&sd->xfrm_backlog);
#endif
		INIT_LIST_HEAD(&sd->poll_list);
		sd->output_queue_tailp = &sd->output_queue;
#ifdef CONFIG_RPS
		INIT_CSD(&sd->csd, rps_trigger_softirq, sd);
		sd->cpu = i;
#endif

		init_gro_hash(&sd->backlog);
		sd->backlog.poll = process_backlog;
		sd->backlog.weight = weight_p;
	}

	dev_boot_phase = 0;

	/* The loopback device is special if any other network devices
	 * is present in a network namespace the loopback device must
	 * be present. Since we now dynamically allocate and free the
	 * loopback device ensure this invariant is maintained by
	 * keeping the loopback device as the first device on the
	 * list of network devices.  Ensuring the loopback devices
	 * is the first device that appears and the last network device
	 * that disappears.
	 */
	if (register_pernet_device(&loopback_net_ops))
		goto out;

	if (register_pernet_device(&default_device_ops))
		goto out;
```

registe func [net_rx_action]() in [softirq](/docs/CS/OS/Linux/Interrupt.md?id=open_softirq)
```c
	open_softirq(NET_TX_SOFTIRQ, net_tx_action);
	open_softirq(NET_RX_SOFTIRQ, net_rx_action);

	rc = cpuhp_setup_state_nocalls(CPUHP_NET_DEV_DEAD, "net/dev:dead",
				       NULL, dev_cpu_dead);
	WARN_ON(rc < 0);
	rc = 0;
out:
	return rc;
}

```



#### process_backlog

```c
// net/core/dev.c
static int process_backlog(struct napi_struct *napi, int quota)
{
	struct softnet_data *sd = container_of(napi, struct softnet_data, backlog);
	bool again = true;
	int work = 0;

	/* Check if we have pending ipi, its better to send them now,
	 * not waiting net_rx_action() end.
	 */
	if (sd_has_rps_ipi_waiting(sd)) {
		local_irq_disable();
		net_rps_action_and_irq_enable(sd);
	}

	napi->weight = dev_rx_weight;
	while (again) {
		struct sk_buff *skb;

		while ((skb = __skb_dequeue(&sd->process_queue))) {
			rcu_read_lock();
```

call [netif_receive_skb](/docs/CS/OS/Linux/network.md?id=netif_receive_skb)
```c
			__netif_receive_skb(skb);
			rcu_read_unlock();
			input_queue_head_incr(sd);
			if (++work >= quota)
				return work;

		}

		local_irq_disable();
		rps_lock(sd);
		if (skb_queue_empty(&sd->input_pkt_queue)) {
			/*
			 * Inline a custom version of __napi_complete().
			 * only current cpu owns and manipulates this napi,
			 * and NAPI_STATE_SCHED is the only possible flag set
			 * on backlog.
			 * We can use a plain write instead of clear_bit(),
			 * and we dont need an smp_mb() memory barrier.
			 */
			napi->state = 0;
			again = false;
		} else {
			skb_queue_splice_tail_init(&sd->input_pkt_queue,
						   &sd->process_queue);
		}
		rps_unlock(sd);
		local_irq_enable();
	}

	return work;
}
```


### init inet 

```c
fs_initcall(inet_init);
```

Registe protocols:

1. ICMP
2. UDP
3. TCP
4. IGMP
5. ...

```c
static int __init inet_init(void)
{
	...
	/* Add all the base protocols. 	*/
	if (inet_add_protocol(&icmp_protocol, IPPROTO_ICMP) < 0)
		pr_crit("%s: Cannot add ICMP protocol\n", __func__);
	if (inet_add_protocol(&udp_protocol, IPPROTO_UDP) < 0)
		pr_crit("%s: Cannot add UDP protocol\n", __func__);
	if (inet_add_protocol(&tcp_protocol, IPPROTO_TCP) < 0)
		pr_crit("%s: Cannot add TCP protocol\n", __func__);
#ifdef CONFIG_IP_MULTICAST
	if (inet_add_protocol(&igmp_protocol, IPPROTO_IGMP) < 0)
		pr_crit("%s: Cannot add IGMP protocol\n", __func__);
#endif

	...
	
	arp_init();

	ip_init();

	tcp_init();

	udp_init();

	udplite4_register();

	raw_init();

	ping_init();
    
  `dev_add_pack(&ip_packet_type);
}


```

#### net_protocol

This is used to register protocols.

```c
// include/net/protocol.h
struct net_protocol {
       int                  (*early_demux)(struct sk_buff *skb);
       int                  (*early_demux_handler)(struct sk_buff *skb);
       int                  (*handler)(struct sk_buff *skb);

       /* This returns an error if we weren't able to handle the error. */
       int                  (*err_handler)(struct sk_buff *skb, u32 info);

       unsigned int          no_policy:1,
                            netns_ok:1,
                            /* does the protocol do more stringent
                             * icmp tag validation than simple
                             * socket lookup?
                             */
                            icmp_strict_tag_validation:1;
};
```



ip_packet_type net protocols

```c
// net/ipv4/af_inet.c
static struct packet_type ip_packet_type __read_mostly = {
	.type = cpu_to_be16(ETH_P_IP),
	.func = ip_rcv,
	.list_func = ip_list_rcv,
};


/* thinking of making this const? Don't.
 * early_demux can change based on sysctl.
 */
static struct net_protocol tcp_protocol = {
	.early_demux	=	tcp_v4_early_demux,
	.early_demux_handler =  tcp_v4_early_demux,
	.handler	=	tcp_v4_rcv,
	.err_handler	=	tcp_v4_err,
	.no_policy	=	1,
	.icmp_strict_tag_validation = 1,
};

/* thinking of making this const? Don't.
 * early_demux can change based on sysctl.
 */
static struct net_protocol udp_protocol = {
	.early_demux =	udp_v4_early_demux,
	.early_demux_handler =	udp_v4_early_demux,
	.handler =	udp_rcv,
	.err_handler =	udp_err,
	.no_policy =	1,
};

static const struct net_protocol icmp_protocol = {
	.handler =	icmp_rcv,
	.err_handler =	icmp_err,
	.no_policy =	1,
};
```

#### inet_add_protocol

```c
// net/ipv4/protocol.c
int inet_add_protocol(const struct net_protocol *prot, unsigned char protocol)
{
	return !cmpxchg((const struct net_protocol **)&inet_protos[protocol],
			NULL, prot) ? 0 : -1;
}
```



```c
// net/core/dev.c

/**
 *	dev_add_pack - add packet handler
 *	@pt: packet type declaration
 *
 *	Add a protocol handler to the networking stack. The passed &packet_type
 *	is linked into kernel lists and may not be freed until it has been
 *	removed from the kernel lists.
 *
 *	This call does not sleep therefore it can not
 *	guarantee all CPU's that are in middle of receiving packets
 *	will see the new packet type (until the next received packet).
 */

void dev_add_pack(struct packet_type *pt)
{
	struct list_head *head = ptype_head(pt);

	spin_lock(&ptype_lock);
	list_add_rcu(&pt->list, head);
	spin_unlock(&ptype_lock);
}


/*
 *	Add a protocol ID to the list. Now that the input handler is
 *	smarter we can dispense with all the messy stuff that used to be
 *	here.
 *
 *	BEWARE!!! Protocol handlers, mangling input packets,
 *	MUST BE last in hash buckets and checking protocol handlers
 *	MUST start from promiscuous ptype_all chain in net_bh.
 *	It is true now, do not change it.
 *	Explanation follows: if protocol handler, mangling packet, will
 *	be the first on list, it is not able to sense, that packet
 *	is cloned and should be copied-on-write, so that it will
 *	change it and subsequent readers will get broken packet.
 *							--ANK (980803)
 */

static inline struct list_head *ptype_head(const struct packet_type *pt)
{
	if (pt->type == htons(ETH_P_ALL))
		return pt->dev ? &pt->dev->ptype_all : &ptype_all;
	else
		return pt->dev ? &pt->dev->ptype_specific :
				 &ptype_base[ntohs(pt->type) & PTYPE_HASH_MASK];
}
```



### init driver







## process

Network Interface Controller 
-> Network Driver DMA into Memory RingBuffer and send a interrupt to CPU 
-> CPU set soft interrupt and release CPU 
-> ksoftirqd thread check soft interrupt, 
disable hard interrupts  and call `poll` get packet, 
then send to TCP/IP stack`(ip_rcv`) 
-> `tcp_rcv` or `udp_rcv`

like UDP will add into socket accept queue

TODO: [tcp-rcv](https://www.processon.com/diagraming/6195c8be07912906e6ab82c8)

### driver process



AMD

```c
// drivers/net/ethernet/amd/xgbe/xgbe-drv.c
static irqreturn_t xgbe_dma_isr(int irq, void *data)
{
	struct xgbe_channel *channel = data;
	struct xgbe_prv_data *pdata = channel->pdata;
	unsigned int dma_status;

	/* Per channel DMA interrupts are enabled, so we use the per
	 * channel napi structure and not the private data napi structure
	 */
	if (napi_schedule_prep(&channel->napi)) {
		/* Disable Tx and Rx interrupts */
		if (pdata->channel_irq_mode)
			xgbe_disable_rx_tx_int(pdata, channel);
		else
			disable_irq_nosync(channel->dma_irq);

		/* Turn on polling */
		__napi_schedule_irqoff(&channel->napi);
	}

	/* Clear Tx/Rx signals */
	dma_status = 0;
	XGMAC_SET_BITS(dma_status, DMA_CH_SR, TI, 1);
	XGMAC_SET_BITS(dma_status, DMA_CH_SR, RI, 1);
	XGMAC_DMA_IOWRITE(channel, DMA_CH_SR, dma_status);

	return IRQ_HANDLED;
}
```

`__napi_schedule_irqoff` call `____napi_schedule`



```c
// net/core/net.c
/* Called with irq disabled */
static inline void ____napi_schedule(struct softnet_data *sd,
				     struct napi_struct *napi)
{
	...
    
	list_add_tail(&napi->poll_list, &sd->poll_list);
```
call [raise_softirq_irqoff](/docs/CS/OS/Linux/Interrupt.md?id=raise_softirq) to invoke [net_rx_action](/docs/CS/OS/Linux/network.md?id=net_rx_action)
```c
	__raise_softirq_irqoff(NET_RX_SOFTIRQ);
}
```



### net_rx_action

```c
// net/core/dev.c
static __latent_entropy void net_rx_action(struct softirq_action *h)
{
	struct softnet_data *sd = this_cpu_ptr(&softnet_data);
	unsigned long time_limit = jiffies +
		usecs_to_jiffies(netdev_budget_usecs);
	int budget = netdev_budget;
	LIST_HEAD(list);
	LIST_HEAD(repoll);

	local_irq_disable();
	list_splice_init(&sd->poll_list, &list);
	local_irq_enable();

	for (;;) {
		struct napi_struct *n;

		if (list_empty(&list)) {
			if (!sd_has_rps_ipi_waiting(sd) && list_empty(&repoll))
				return;
			break;
		}

		n = list_first_entry(&list, struct napi_struct, poll_list);
		budget -= napi_poll(n, &repoll);

		/* If softirq window is exhausted then punt.
		 * Allow this to run for 2 jiffies since which will allow
		 * an average latency of 1.5/HZ.
		 */
		if (unlikely(budget <= 0 ||
			     time_after_eq(jiffies, time_limit))) {
			sd->time_squeeze++;
			break;
		}
	}

	local_irq_disable();

	list_splice_tail_init(&sd->poll_list, &list);
	list_splice_tail(&repoll, &list);
	list_splice(&list, &sd->poll_list);
	if (!list_empty(&sd->poll_list))
		__raise_softirq_irqoff(NET_RX_SOFTIRQ);

	net_rps_action_and_irq_enable(sd);
}
```
xgbe_one_poll ->
xgbe_tx_poll ->
xgbe_rx_poll ->
napi_gro_receive


```c
// net/core/dev.c
gro_result_t napi_gro_receive(struct napi_struct *napi, struct sk_buff *skb)
{
	skb_gro_reset_offset(skb, 0);
	return napi_skb_finish(napi, skb, dev_gro_receive(napi, skb));
}


static gro_result_t napi_skb_finish(struct napi_struct *napi,
				    struct sk_buff *skb,
				    gro_result_t ret)
{
	switch (ret) {
	case GRO_NORMAL:
		gro_normal_one(napi, skb, 1);
		break;
    ...
	}

	return ret;
}
```

napi_gro_receive -> napi_skb_finish -> gro_normal_one 
-> gro_normal_list -> netif_receive_skb_list_internal
-> __netif_receive_skb_list -> deliver_skb


#### netif_receive_skb
call deliver_skb
```c

static int __netif_receive_skb_core(struct sk_buff **pskb, bool pfmemalloc,
				    struct packet_type **ppt_prev)
{
	...
    
	list_for_each_entry_rcu(ptype, &ptype_all, list) {
		if (pt_prev)
			ret = deliver_skb(skb, pt_prev, orig_dev);
		pt_prev = ptype;
	}

	list_for_each_entry_rcu(ptype, &skb->dev->ptype_all, list) {
		if (pt_prev)
			ret = deliver_skb(skb, pt_prev, orig_dev);
		pt_prev = ptype;
	}
	
  ...
}
```

goto protocol func

```c
static inline int deliver_skb(struct sk_buff *skb,
			      struct packet_type *pt_prev,
			      struct net_device *orig_dev)
{
	if (unlikely(skb_orphan_frags_rx(skb, GFP_ATOMIC)))
		return -ENOMEM;
	refcount_inc(&skb->users);
	return pt_prev->func(skb, skb->dev, pt_prev, orig_dev);
}
```




### ip_rcv
```c

/*
 * IP receive entry point
 */
int ip_rcv(struct sk_buff *skb, struct net_device *dev, struct packet_type *pt,
	   struct net_device *orig_dev)
{
	struct net *net = dev_net(dev);

	skb = ip_rcv_core(skb, net);
	if (skb == NULL)
		return NET_RX_DROP;

	return NF_HOOK(NFPROTO_IPV4, NF_INET_PRE_ROUTING,
		       net, NULL, skb, dev, NULL,
		       ip_rcv_finish);
}
```


#### ip_rcv_finish

```c

static int ip_rcv_finish(struct net *net, struct sock *sk, struct sk_buff *skb)
{
	struct net_device *dev = skb->dev;
	int ret;

	/* if ingress device is enslaved to an L3 master device pass the
	 * skb to its handler for processing
	 */
	skb = l3mdev_ip_rcv(skb);
	if (!skb)
		return NET_RX_SUCCESS;

	ret = ip_rcv_finish_core(net, sk, skb, dev, NULL);
	if (ret != NET_RX_DROP)
		ret = dst_input(skb);
	return ret;
}
```



```c
/* Input packet from network to transport.  */
static inline int dst_input(struct sk_buff *skb)
{
	return INDIRECT_CALL_INET(skb_dst(skb)->input,
				  ip6_input, ip_local_deliver, skb);
}
```

#### ip_local_deliver

```c

/*
 * 	Deliver IP Packets to the higher protocol layers.
 */
int ip_local_deliver(struct sk_buff *skb)
{
	/*
	 *	Reassemble IP fragments.
	 */
	struct net *net = dev_net(skb->dev);

	if (ip_is_fragment(ip_hdr(skb))) {
		if (ip_defrag(net, skb, IP_DEFRAG_LOCAL_DELIVER))
			return 0;
	}

	return NF_HOOK(NFPROTO_IPV4, NF_INET_LOCAL_IN,
		       net, NULL, skb, skb->dev, NULL,
		       ip_local_deliver_finish);
}
```

`ip_local_deliver_finish` ->`ip_protocol_deliver_rcu` -> `tcp_v4_rcv` or `udp_rcv` etc.



```c
void ip_protocol_deliver_rcu(struct net *net, struct sk_buff *skb, int protocol)
{
	...
    
	ipprot = rcu_dereference(inet_protos[protocol]);
	if (ipprot) {
		...
		ret = INDIRECT_CALL_2(ipprot->handler, tcp_v4_rcv, udp_rcv,
				      skb);
		...
	}
  
```
}
## Optimization



### Limits

1. OS `/proc/sys/fs/file-max`
2. Process fs.nr_open
3. User process in `/etc/security/limits.conf`

```shell
> cat /proc/sys/fs/file-max 
174837

# vi /etc/sysctl.conf 
> sysctl -a |grep nr_open
fs.nr_open = 1048576

# hard limit <= fs.nr_open
> cat /etc/security/limits.conf
root soft nofile 65535
root hard nofile 65535
```





```shell
> sysctl -a |grep rmem
net.core.rmem_default = 212992
net.core.rmem_max = 212992
net.ipv4.tcp_rmem = 4096        87380   6291456
net.ipv4.udp_rmem_min = 4096
```





```shell
> sysctl -a |grep wmem
net.core.wmem_default = 212992
net.core.wmem_max = 212992
net.ipv4.tcp_wmem = 4096        16384   4194304
net.ipv4.udp_wmem_min = 4096
vm.lowmem_reserve_ratio = 256   256     32      0       0
```



```shell
> sysctl -a |grep range
net.ipv4.ip_local_port_range = 32768    60999
```





empty establish : 3.3KB


strace



```shell
# 
> watch 'netstat -s |grep LISTEN'

# 
> watch 'netstat -s |grep overflowed'
```



```shell
> cat  /proc/sys/net/ipv4/tcp_max_syn_backlog 
1024
```



```shell

> cat /proc/sys/net/core/somaxconn 
128
```

check network

```shell
ss -nlt
```


[TCP RESET/RST Reasons](https://iponwire.com/tcp-reset-rst-reasons/)