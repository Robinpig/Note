## Introduction





## init

Create [ksoftirqd](/docs/CS/OS/Linux/Interrupt.md?id=init_softirq) for each cpu.

### init net dev

> initcall see [kernel_init](/docs/CS/OS/Linux/init.md?id=kernel_init)

Initialize the DEV module.
<br/>
At boot time this walks the device list and unhooks any devices that fail to initialise (normally hardware not present) and leaves us with a valid list of present and active devices.
<br/>
This is called single threaded during boot, so no need to take the rtnl semaphore.

1. Initialise the packet receive queues for each cpu.
2. register func with [softirq](/docs/CS/OS/Linux/Interrupt.md?id=open_softirq)
   - [net_rx_action](/docs/CS/OS/Linux/net/network.mdk.md?id=net_rx_action) receive func
   - [net_tx_action](/docs/CS/OS/Linux/net/network.mdk.md?id=net_tx_action) transmit func

```c
// net/core/dev.c
subsys_initcall(net_dev_init);

static int __init net_dev_init(void)
{
	for_each_possible_cpu(i) {
		struct softnet_data *sd = &per_cpu(softnet_data, i);

		skb_queue_head_init(&sd->input_pkt_queue);
		skb_queue_head_init(&sd->process_queue);
		INIT_LIST_HEAD(&sd->poll_list);
		sd->output_queue_tailp = &sd->output_queue;

		init_gro_hash(&sd->backlog);
		sd->backlog.poll = process_backlog;
		sd->backlog.weight = weight_p;
	}

	open_softirq(NET_TX_SOFTIRQ, net_tx_action);
	open_softirq(NET_RX_SOFTIRQ, net_rx_action);
}
```

### init inet

Register protocols into `inet_protos` and `ptype_base`:

1. IP
2. [UDP](/docs/CS/OS/Linux/net/UDP.md)
3. [TCP](/docs/CS/OS/Linux/TCP.md?id=tcp_init)
4. ...

```c
fs_initcall(inet_init);
static int __init inet_init(void)
{
    ......
	/* Add all the base protocols. 	*/
	if (inet_add_protocol(&icmp_protocol, IPPROTO_ICMP) < 0)
		pr_crit("%s: Cannot add ICMP protocol\n", __func__);
	if (inet_add_protocol(&udp_protocol, IPPROTO_UDP) < 0)
		pr_crit("%s: Cannot add UDP protocol\n", __func__);
	if (inet_add_protocol(&tcp_protocol, IPPROTO_TCP) < 0)
		pr_crit("%s: Cannot add TCP protocol\n", __func__);
    ......

	arp_init();
	ip_init();
	tcp_init();
	udp_init();
    ...
    dev_add_pack(&ip_packet_type);
}
```

#### inet_add_protocol

Add a protocol handler to the networking stack.
The passed &packet_type is linked into kernel lists and may not be freed until it has been removed from the kernel lists.

```c
// net/ipv4/protocol.c
int inet_add_protocol(const struct net_protocol *prot, unsigned char protocol)
{
	return !cmpxchg((const struct net_protocol **)&inet_protos[protocol],
			NULL, prot) ? 0 : -1;
}
```

#### dev_add_pack

ip_packet_type

```c
// net/ipv4/af_inet.c
static struct packet_type ip_packet_type __read_mostly = {
	.func = ip_rcv,
};

static struct net_protocol tcp_protocol = {
	.handler	=	tcp_v4_rcv,
};

static struct net_protocol udp_protocol = {
	.handler =	udp_rcv,
};

```

dev_add_pack

```c
// net/core/dev.c
void dev_add_pack(struct packet_type *pt)
{
	struct list_head *head = ptype_head(pt);
}

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

A driver registers an initialization function which is called by the kernel when the driver is loaded.
This function is registered by using the module_init macro.
<br/>
The igb initialization function (igb_init_module) and its registration with module_init can be found in `drivers/net/ethernet/intel/igb/igb_main.c`.

The bulk of the work to initialize the device happens with the call to `pci_register_driver`.

```c
//  igb_main.c
static struct pci_driver igb_driver = {
	.probe    = igb_probe,
};

static int __init igb_init_module(void)
{
    pci_register_driver(&igb_driver);
}
module_init(igb_init_module);
```

register a new pci driver

```c
#define pci_register_driver(driver)		\
	__pci_register_driver(driver, THIS_MODULE, KBUILD_MODNAME)

int __pci_register_driver(struct pci_driver *drv, struct module *owner, const char *mod_name)
{
	/* initialize common driver fields */

	/* register with core */
	return driver_register(&drv->driver);
}
EXPORT_SYMBOL(__pci_register_driver);

int driver_register(struct device_driver *drv)
{
	if ((drv->bus->probe && drv->probe) ||
	    (drv->bus->remove && drv->remove) ||
	    (drv->bus->shutdown && drv->shutdown))
		pr_warn("Driver '%s' needs updating - please use "
			"bus_type methods\n", drv->name);

	deferred_probe_extend_timeout();
}
```

#### probe

The probe function is quite basic, and only needs to perform a device's early init, and then register our network device with the kernel.

The `igb_probe` function does some important network device initialization.
In addition to the PCI specific work, it will do more general networking and network device work:

1. The `struct net_device_ops` is registered.
2. `ethtool` operations are registered.
3. The default MAC address is obtained from the NIC.
4. `net_device` feature flags are set.
5. And lots more.

ndo_open func.

```c
static const struct net_device_ops igb_netdev_ops = {
	.ndo_open		= igb_open,
	...
};
```

### open NIC

call open function -> allocate RX TX memory

__igb_open - Called when a network interface is made active

The open entry point is called when a network interface is made active by the system (IFF_UP).
At this point all resources needed for transmit and receive operations are allocated, the interrupt handler is registered with the OS, the watchdog timer is started, and the stack is notified that the interface is ready.

```c
static int __igb_open(struct net_device *netdev, bool resuming)
{

	/* allocate transmit descriptors */
	igb_setup_all_tx_resources(adapter);
	/* allocate receive descriptors */
	igb_setup_all_rx_resources(adapter);

	igb_power_up_link(adapter);

	igb_request_irq(adapter);

	/* Notify the stack of the actual queue counts. */
	netif_set_real_num_tx_queues(adapter->netdev,
					   adapter->num_tx_queues);

	netif_set_real_num_rx_queues(adapter->netdev,
					   adapter->num_rx_queues);

	for (i = 0; i < adapter->num_q_vectors; i++)
		napi_enable(&(adapter->q_vector[i]->napi));

	igb_irq_enable(adapter);
	}

	netif_tx_start_all_queues(netdev);

	/* start the watchdog. */
	hw->mac.get_link_status = 1;
	schedule_work(&adapter->watchdog_task);
}
```

#### setup descriptors

- igb_tx_buffer array
- e1000_adv_tx_desc DMA array

check RX/TX overruns:

```shell
ifconfig | grep overruns
```

```c
static int igb_setup_all_tx_resources(struct igb_adapter *adapter)
{
	struct pci_dev *pdev = adapter->pdev;
	int i, err = 0;

	for (i = 0; i < adapter->num_tx_queues; i++) {
		err = igb_setup_tx_resources(adapter->tx_ring[i]);
		......
	}
	return err;
}

int igb_setup_tx_resources(struct igb_ring *tx_ring)
{
	struct device *dev = tx_ring->dev;
	int size;

	size = sizeof(struct igb_tx_buffer) * tx_ring->count;

	tx_ring->tx_buffer_info = vmalloc(size);

	/* round up to nearest 4K */
	tx_ring->size = tx_ring->count * sizeof(union e1000_adv_tx_desc);
	tx_ring->size = ALIGN(tx_ring->size, 4096);

	tx_ring->desc = dma_alloc_coherent(dev, tx_ring->size,
					   &tx_ring->dma, GFP_KERNEL);

	tx_ring->next_to_use = 0;
	tx_ring->next_to_clean = 0;

	return 0;
}
```

#### register_irq

```c
static int igb_request_irq(struct igb_adapter *adapter)
{
	if (adapter->flags & IGB_FLAG_HAS_MSIX) {
		err = igb_request_msix(adapter);
		/* fall back to MSI */
		igb_free_all_tx_resources(adapter);
		igb_free_all_rx_resources(adapter);

		igb_clear_interrupt_scheme(adapter);
		err = igb_init_interrupt_scheme(adapter, false);

		igb_setup_all_tx_resources(adapter);
		igb_setup_all_rx_resources(adapter);
		igb_configure(adapter);
	}

	igb_assign_vector(adapter->q_vector[0], 0);

	request_irq(pdev->irq, igb_intr, IRQF_SHARED,
			  netdev->name, adapter);

}

```

igb_init_interrupt_scheme -> igb_alloc_q_vector

initialize NAPI with `igb_poll`

```c
static int igb_alloc_q_vector(struct igb_adapter *adapter,
			      int v_count, int v_idx,
			      int txr_count, int txr_idx,
			      int rxr_count, int rxr_idx)
{
    ...
	/* initialize NAPI */
	netif_napi_add(adapter->netdev, &q_vector->napi, igb_poll);
}
```

##### igb_request_msix

register [igb_msix_ring](/docs/CS/OS/Linux/net/network.mdk.md?id=igb_msix_ring)

```c
static int igb_request_msix(struct igb_adapter *adapter)
{
	unsigned int num_q_vectors = adapter->num_q_vectors;
	struct net_device *netdev = adapter->netdev;
	int i, err = 0, vector = 0, free_vector = 0;

	err = request_irq(adapter->msix_entries[vector].vector,
			  igb_msix_other, 0, netdev->name, adapter);
	if (err)
		goto err_out;

	if (num_q_vectors > MAX_Q_VECTORS) {
		num_q_vectors = MAX_Q_VECTORS;
		dev_warn(&adapter->pdev->dev,
			 "The number of queue vectors (%d) is higher than max allowed (%d)\n",
			 adapter->num_q_vectors, MAX_Q_VECTORS);
	}
	for (i = 0; i < num_q_vectors; i++) {
		struct igb_q_vector *q_vector = adapter->q_vector[i];

		vector++;

		q_vector->itr_register = adapter->io_addr + E1000_EITR(vector);

		if (q_vector->rx.ring && q_vector->tx.ring)
			sprintf(q_vector->name, "%s-TxRx-%u", netdev->name,
				q_vector->rx.ring->queue_index);
		else if (q_vector->tx.ring)
			sprintf(q_vector->name, "%s-tx-%u", netdev->name,
				q_vector->tx.ring->queue_index);
		else if (q_vector->rx.ring)
			sprintf(q_vector->name, "%s-rx-%u", netdev->name,
				q_vector->rx.ring->queue_index);
		else
			sprintf(q_vector->name, "%s-unused", netdev->name);

		err = request_irq(adapter->msix_entries[vector].vector,
				  igb_msix_ring, 0, q_vector->name,
				  q_vector);
		if (err)
			goto err_free;
	}

	igb_configure_msix(adapter);
	return 0;
}
```

## Egress

### send

Send a datagram down a socket.

```c
// net/socket.c
SYSCALL_DEFINE6(sendto, int, fd, void __user *, buff, size_t, len, ...)
{
	return __sys_sendto(fd, buff, len, flags, addr, addr_len);
}

SYSCALL_DEFINE4(send, int, fd, void __user *, buff, size_t, len, ...)
{
	return __sys_sendto(fd, buff, len, flags, NULL, 0);
}

int __sys_sendto(int fd, void __user *buff, size_t len, unsigned int flags, ...)
{
	err = sock_sendmsg(sock, &msg);
}
```

### inet_sendmsg

sock_sendmsg -> sock_sendmsg_nosec -> inet_sendmsg ->

- [udp_sendmsg](/docs/CS/OS/Linux/net/UDP.md?id=udp_sendmsg)
- or [tcp_sendmsg](/docs/CS/OS/Linux/TCP.md?id=send)

```c
int inet_sendmsg(struct socket *sock, struct msghdr *msg, size_t size)
{
	struct sock *sk = sock->sk;
	return INDIRECT_CALL_2(sk->sk_prot->sendmsg, tcp_sendmsg, udp_sendmsg,
			       sk, msg, size);
}
```

### ip_queue_xmit

Both `ip_queue_xmit` and `ip_send_skb` call [ip_local_out](/docs/CS/OS/Linux/net/IP.md?id=ip_local_out)

<!-- tabs:start -->

##### **ip_queue_xmit**

Called by [tcp_transmit_skb](/docs/CS/OS/Linux/TCP.md?id=tcp_transmit_skb)

Note: skb->sk can be different from sk, in case of tunnels

```c
int __ip_queue_xmit(struct sock *sk, struct sk_buff *skb, struct flowi *fl,
		    __u8 tos)
{
    ...
	res = ip_local_out(net, sk, skb);
}
```

##### **ip_send_skb**

Called by [UDP](/docs/CS/OS/Linux/net/UDP.md?id=transmit)

```c

int ip_send_skb(struct net *net, struct sk_buff *skb)
{
	ip_local_out(net, skb->sk, skb);
}
```

<!-- tabs:end -->

#### ip_local_out

ip_local_out -> dst_output -> ip_output -> ip_finish_output2 -> neigh_hh_output -> dev_queue_xmit

```c
// net/ipv4/ip_output.c
int __ip_local_out(struct net *net, struct sock *sk, struct sk_buff *skb)
{
	struct iphdr *iph = ip_hdr(skb);

	iph->tot_len = htons(skb->len);
	ip_send_check(iph);

	skb->protocol = htons(ETH_P_IP);
	return nf_hook(NFPROTO_IPV4, NF_INET_LOCAL_OUT,
		       net, sk, skb, NULL, skb_dst(skb)->dev,
		       dst_output);
}

// include/net/dst.h
static inline int dst_output(struct net *net, struct sock *sk, struct sk_buff *skb)
{
	return INDIRECT_CALL_INET(skb_dst(skb)->output,
				  ip6_output, ip_output,
				  net, sk, skb);
}

int ip_output(struct net *net, struct sock *sk, struct sk_buff *skb)
{
	return NF_HOOK_COND(NFPROTO_IPV4, NF_INET_POST_ROUTING,
			    net, sk, skb, indev, dev,
			    ip_finish_output,
			    !(IPCB(skb)->flags & IPSKB_REROUTED));
}

static int __ip_finish_output(struct net *net, struct sock *sk, struct sk_buff *skb)
{
	unsigned int mtu;
	mtu = ip_skb_dst_mtu(sk, skb);

	if (skb->len > mtu || IPCB(skb)->frag_max_size)
		return ip_fragment(net, sk, skb, mtu, ip_finish_output2);

	return ip_finish_output2(net, sk, skb);
}
```

#### neigh_hh_output

ip_finish_output2 -> neigh_output -> neigh_hh_output

call dev_queue_xmit

```c
// include/net/neighbour.h
static inline int neigh_hh_output(const struct hh_cache *hh, struct sk_buff *skb)
{
    ...
	__skb_push(skb, hh_len);
	return dev_queue_xmit(skb);
}
```

### dev_queue_xmit

transmit a buffer

Queue a buffer for transmission to a network device.
The caller must have set the device and priority and built the buffer before calling this function.
The function can be called from an interrupt.

A negative errno code is returned on a failure.
A success does not guarantee the frame will be transmitted as it may be dropped due to congestion or traffic shaping.

I notice this method can also return errors from the queue disciplines, including NET_XMIT_DROP, which is a positive value.
So, errors can also be positive.

Regardless of the return value, the skb is consumed, so it is currently difficult to retry a send to this method.
(You can bump the ref count before sending to hold a reference for retry if you are careful.)

When calling this method, interrupts MUST be enabled.
This is because the BH enable code must have IRQs enabled so that it will not deadlock.

```c
// net/core/dev.c
static int __dev_queue_xmit(struct sk_buff *skb, struct net_device *sb_dev)
{
	txq = netdev_core_pick_tx(dev, skb, sb_dev);
	q = rcu_dereference_bh(txq->qdisc);

	trace_net_dev_queue(skb);
	if (q->enqueue) {
		rc = __dev_xmit_skb(skb, q, dev, txq);
		goto out;
	}
	...
}



static inline int __dev_xmit_skb(struct sk_buff *skb, struct Qdisc *q,
				 struct net_device *dev,
				 struct netdev_queue *txq)
{
	if (q->flags & TCQ_F_NOLOCK) {
		if (q->flags & TCQ_F_CAN_BYPASS && nolock_qdisc_is_empty(q) &&
		    qdisc_run_begin(q)) {

			if (sch_direct_xmit(skb, q, dev, txq, NULL, true) &&
			    !nolock_qdisc_is_empty(q))
				__qdisc_run(q);

			qdisc_run_end(q);
			return NET_XMIT_SUCCESS;
		}

		rc = dev_qdisc_enqueue(skb, q, &to_free, txq);
		qdisc_run(q);
  
        ...
}
```

#### qdisc_run

The qdisc will either transmit the data directly if it can, or queue it up to be sent during the NET_TX softirq.

raise NET_TX_SOFTIRQ if quota <= 0 in order to execute net_tx_action and recall `qdisc_run` func

```c
void __qdisc_run(struct Qdisc *q)
{
	int quota = READ_ONCE(dev_tx_weight);
	int packets;

	while (qdisc_restart(q, &packets)) {
		quota -= packets;
		if (quota <= 0) {
			if (q->flags & TCQ_F_NOLOCK)
				set_bit(__QDISC_STATE_MISSED, &q->state);
			else
				__netif_schedule(q);

			break;
		}
	}
}
```

#### net_tx_action

```c

static void __netif_reschedule(struct Qdisc *q)
{
	raise_softirq_irqoff(NET_TX_SOFTIRQ);
}
```

```c
static __latent_entropy void net_tx_action(struct softirq_action *h)
{
	struct softnet_data *sd = this_cpu_ptr(&softnet_data);

	...

	if (sd->output_queue) {
		struct Qdisc *head;

		head = sd->output_queue;
		sd->output_queue = NULL;
		sd->output_queue_tailp = &sd->output_queue;


		while (head) {
			struct Qdisc *q = head;
			spinlock_t *root_lock = NULL;

			head = head->next_sched;

			qdisc_run(q);
		}
	}
}
```

#### dev_hard_start_xmit

finally call [ndo_start_xmit](/docs/CS/OS/Linux/net/IP.md?id=ndo_start_xmit) by different adapters.

```c
static inline bool qdisc_restart(struct Qdisc *q, int *packets)
{
	skb = dequeue_skb(q, &validate, packets);

	return sch_direct_xmit(skb, q, dev, txq, root_lock, validate);
}

bool sch_direct_xmit(struct sk_buff *skb, struct Qdisc *q,
		     struct net_device *dev, struct netdev_queue *txq,
		     spinlock_t *root_lock, bool validate)
{
    skb = dev_hard_start_xmit(skb, dev, txq, &ret);
    ...
	return true;
}


// net/core/dev.c
struct sk_buff *dev_hard_start_xmit(struct sk_buff *first, struct net_device *dev,
				    struct netdev_queue *txq, int *ret)
{
	struct sk_buff *skb = first;

	while (skb) {
		struct sk_buff *next = skb->next;
		rc = xmit_one(skb, dev, txq, next != NULL);
		...
	}
}

static int xmit_one(struct sk_buff *skb, struct net_device *dev,
		    struct netdev_queue *txq, bool more)
{
	rc = netdev_start_xmit(skb, dev, txq, more);
}

static inline netdev_tx_t netdev_start_xmit(struct sk_buff *skb, struct net_device *dev,
					    struct netdev_queue *txq, bool more)
{
	rc = __netdev_start_xmit(ops, skb, dev, more);
}

static inline netdev_tx_t __netdev_start_xmit(const struct net_device_ops *ops,
					      struct sk_buff *skb, struct net_device *dev,
					      bool more)
{
	return ops->ndo_start_xmit(skb, dev);
}
```

### ndo_start_xmit

```c
// igb_main.c
static const struct net_device_ops igb_netdev_ops = {
	.ndo_start_xmit		= igb_xmit_frame,
    ...
}


static netdev_tx_t igb_xmit_frame(struct sk_buff *skb,
				  struct net_device *netdev)
{
	struct igb_adapter *adapter = netdev_priv(netdev);

	return igb_xmit_frame_ring(skb, igb_tx_queue_mapping(adapter, skb));
}



netdev_tx_t igb_xmit_frame_ring(struct sk_buff *skb,
				struct igb_ring *tx_ring)
{
	struct igb_tx_buffer *first;

	/* record the location of the first descriptor for this packet */
	first = &tx_ring->tx_buffer_info[tx_ring->next_to_use];
	first->type = IGB_TYPE_SKB;
	first->skb = skb;
	first->bytecount = skb->len;
	first->gso_segs = 1;

    ...
  
	igb_tx_map(tx_ring, first, hdr_len);
}
```

#### igb_tx_map

```c

static int igb_tx_map(struct igb_ring *tx_ring,
		      struct igb_tx_buffer *first,
		      const u8 hdr_len)
{
	tx_desc = IGB_TX_DESC(tx_ring, i);

	dma = dma_map_single(tx_ring->dev, skb->data, size, DMA_TO_DEVICE);

	for (frag = &skb_shinfo(skb)->frags[0];; frag++) {
		tx_desc->read.buffer_addr = cpu_to_le64(dma);

		while (unlikely(size > IGB_MAX_DATA_PER_TXD)) {
			tx_desc->read.cmd_type_len =
				cpu_to_le32(cmd_type ^ IGB_MAX_DATA_PER_TXD);
            ...
			tx_desc->read.olinfo_status = 0;
		}
	    ...
	}

	tx_desc->read.cmd_type_len = cpu_to_le32(cmd_type);
    ...
}
```

### transmission completion

After the transmission NIC will raise a `hard IRQ` to signal its completion.
The driver will handle this IRQ (turn it off) and schedule (`soft IRQ`) the NAPI poll system.
NAPI will handle the receive packets signaling and free the RAM.

Reclaim resources after transmit completes

```c
static int igb_poll(struct napi_struct *napi, int budget)
{
	if (q_vector->tx.ring)
		clean_complete = igb_clean_tx_irq(q_vector, budget);
    ...
}

static bool igb_clean_tx_irq(struct igb_q_vector *q_vector, int napi_budget)
{
	tx_buffer = &tx_ring->tx_buffer_info[i];
	tx_desc = IGB_TX_DESC(tx_ring, i);

	do {
		union e1000_adv_tx_desc *eop_desc = tx_buffer->next_to_watch;

		/* clear next_to_watch to prevent false hangs */
		tx_buffer->next_to_watch = NULL;

		/* free the skb */
		if (tx_buffer->type == IGB_TYPE_SKB)
			napi_consume_skb(tx_buffer->skb, napi_budget);
		else
			xdp_return_frame(tx_buffer->xdpf);

		/* unmap skb header data */
		dma_unmap_single(tx_ring->dev,
				 dma_unmap_addr(tx_buffer, dma),
				 dma_unmap_len(tx_buffer, len),
				 DMA_TO_DEVICE);

		/* clear tx_buffer data */
		dma_unmap_len_set(tx_buffer, len, 0);

		/* clear last DMA location and unmap remaining buffers */
		while (tx_desc != eop_desc) {
            ...
		}

		...
	} while (likely(budget));
    ...
}
```

## Ingress

### driver process

#### igb_msix_ring

This function is registered when the [NIC is active](/docs/CS/OS/Linux/net/network.mdk.md?id=open-NIC), in order to handle hard interrupts

Driver will `schedule a NAPI`(raise a `soft IRQ (NET_RX_SOFTIRQ)`).

```c
static irqreturn_t igb_msix_ring(int irq, void *data)
{
	struct igb_q_vector *q_vector = data;

	/* Write the ITR value calculated from the previous interrupt. */
	igb_write_itr(q_vector);

	napi_schedule(&q_vector->napi);

	return IRQ_HANDLED;
}
```

#### napi_schedule

call [raise_softirq_irqoff](/docs/CS/OS/Linux/Interrupt.md?id=raise_softirq) to invoke [net_rx_action](/docs/CS/OS/Linux/net/network.mdk.md?id=net_rx_action)

```c
// net/core/net.c
/* Called with irq disabled */
static inline void ____napi_schedule(struct softnet_data *sd,
				     struct napi_struct *napi)
{
	...
	list_add_tail(&napi->poll_list, &sd->poll_list);

	__raise_softirq_irqoff(NET_RX_SOFTIRQ);
}
```

### net_rx_action

```c
// net/core/dev.c
static __latent_entropy void net_rx_action(struct softirq_action *h)
{
	struct softnet_data *sd = this_cpu_ptr(&softnet_data);

	for (;;) {
		struct napi_struct *n;
		...
		n = list_first_entry(&list, struct napi_struct, poll_list);
		budget -= napi_poll(n, &repoll);
	}
}
```

#### poll

napi_poll function

```c
static int igb_poll(struct napi_struct *napi, int budget)
{
	if (q_vector->tx.ring)
		clean_complete = igb_clean_tx_irq(q_vector, budget);

	if (q_vector->rx.ring) {
		int cleaned = igb_clean_rx_irq(q_vector, budget);
	}
    ...
}
```

igb_clean_rx_irq

```c

static int igb_clean_rx_irq(struct igb_q_vector *q_vector, const int budget)
{
	while (likely(total_packets < budget)) {
		union e1000_adv_rx_desc *rx_desc;
		struct igb_rx_buffer *rx_buffer;

		/* retrieve a buffer from the ring */
		if (!skb) {
			unsigned char *hard_start = pktbuf - igb_rx_offset(rx_ring);
			unsigned int offset = pkt_offset + igb_rx_offset(rx_ring);

			xdp_prepare_buff(&xdp, hard_start, offset, size, true);
			xdp_buff_clear_frags_flag(&xdp);
			skb = igb_run_xdp(adapter, rx_ring, &xdp);
		}

		igb_put_rx_buffer(rx_ring, rx_buffer, rx_buf_pgcnt);

		/* fetch next buffer in frame if non-eop */
		if (igb_is_non_eop(rx_ring, rx_desc))
			continue;

		/* verify the packet layout is correct */
		if (igb_cleanup_headers(rx_ring, rx_desc, skb)) {
			skb = NULL;
			continue;
		}

		/* populate checksum, timestamp, VLAN, and protocol */
		igb_process_skb_fields(rx_ring, rx_desc, skb);

		napi_gro_receive(&q_vector->napi, skb);
	}
    ...
}

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
-> __netif_receive_skb_list -> __netif_receive_skb_list_core -> __netif_receive_skb_core(contains [tcpdump](/docs/CS/CN/Tools/tcpdump.md))

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

IP receive entry point

execute ip_rcv_finish after NF_HOOK iptables [netfilter](/docs/CS/CN/Tools/netfilter.md)

```c
int ip_rcv(struct sk_buff *skb, struct net_device *dev, struct packet_type *pt,
	   struct net_device *orig_dev)
{
	struct net *net = dev_net(dev);

	skb = ip_rcv_core(skb, net);

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

ip_rcv_finish_core

Input packet from network to transport.

```c
static inline int dst_input(struct sk_buff *skb)
{
	return INDIRECT_CALL_INET(skb_dst(skb)->input,
				  ip6_input, ip_local_deliver, skb);
}
```

#### ip_local_deliver

Deliver IP Packets to the higher protocol layers.

```c
int ip_local_deliver(struct sk_buff *skb)
{
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

`ip_local_deliver_finish` ->`ip_protocol_deliver_rcu`

It calls the L4 protocol(`tcp_v4_rcv` or `udp_rcv`)

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
}
```

### l4 rcv

Data is added to receive buffers attached to sockets by protocol layers.

tail skb queue and invoke func `sk_data_ready` to wake up 1 process.

<!-- tabs:start -->

##### **tcp_v4_rcv**

tcp_queue_rcv and sk_data_ready in [tcp_rcv_established](/docs/CS/OS/Linux/TCP.md?id=tcp_rcv_established)

```c
int tcp_v4_do_rcv(struct sock *sk, struct sk_buff *skb)
{
       if (sk->sk_state == TCP_ESTABLISHED) { /* Fast path */
              ...
              tcp_rcv_established(sk, skb);
       }
}

void tcp_rcv_established(struct sock *sk, struct sk_buff *skb)
{
    ...
    eaten = tcp_queue_rcv(sk, skb, &fragstolen);
    tcp_data_ready(sk);
    ...
}

void tcp_data_ready(struct sock *sk)
{
	if (tcp_epollin_ready(sk, sk->sk_rcvlowat) || sock_flag(sk, SOCK_DONE))
		sk->sk_data_ready(sk);
}   
```

##### **udp_rcv**

```c

int udp_rcv(struct sk_buff *skb)
{
	return __udp4_lib_rcv(skb, &udp_table, IPPROTO_UDP);
}

int __udp4_lib_rcv(struct sk_buff *skb, struct udp_table *udptable, int proto)
{
    ...
	udp_unicast_rcv_skb(sk, skb, uh);
    ...
}

static int udp_unicast_rcv_skb(struct sock *sk, struct sk_buff *skb, struct udphdr *uh)
{
	ret = udp_queue_rcv_skb(sk, skb);
}

static int __udp_queue_rcv_skb(struct sock *sk, struct sk_buff *skb)
{
	rc = __udp_enqueue_schedule_skb(sk, skb);
}

int __udp_enqueue_schedule_skb(struct sock *sk, struct sk_buff *skb)
{
	__skb_queue_tail(list, skb);
    sk->sk_data_ready(sk);
}
```

<!-- tabs:end -->

#### sk_data_ready

`sk_data_ready` = `sock_def_readable` , see [Socket](/docs/CS/OS/Linux/socket.md?id=sock_init_data)

```c
void sock_def_readable(struct sock *sk)
{
	struct socket_wq *wq;
	wq = rcu_dereference(sk->sk_wq);
	if (skwq_has_sleeper(wq))   // check if there are any waiting processes
		wake_up_interruptible_sync_poll(&wq->wait, EPOLLIN | EPOLLPRI |
						EPOLLRDNORM | EPOLLRDBAND);
	sk_wake_async(sk, SOCK_WAKE_WAITD, POLL_IN);
}
```

[wake_up_interruptible_sync_poll](/docs/CS/OS/Linux/thundering_herd.md?id=wake-up), wake up and invoke callback func

## Native IO

> [!NOTE]
>
> Native IO without hard irq.

### Native Egress

Recall the [egress flow](/docs/CS/OS/Linux/net/network.mdk.md?id=ndo_start_xmit), the loopback driver register `net_device_ops`:

```c

static const struct net_device_ops loopback_ops = {
	.ndo_start_xmit  = loopback_xmit,
};

atic netdev_tx_t loopback_xmit(struct sk_buff *skb,
				 struct net_device *dev)
{
	skb_orphan(skb);

	__netif_rx(skb);
}

```

#### __netif_rx

tail input_pkt_queue with skb

[Schedule NAPI](/docs/CS/OS/Linux/net/network.mdk.md?id=napi_schedule) for backlog device

```c
int __netif_rx(struct sk_buff *skb)
{
	ret = netif_rx_internal(skb);
}

static int netif_rx_internal(struct sk_buff *skb)
{
    ret = enqueue_to_backlog(skb, smp_processor_id(), &qtail);
}

static int enqueue_to_backlog(struct sk_buff *skb, int cpu,
			      unsigned int *qtail)
{
	sd = &per_cpu(softnet_data, cpu);
    ...
    __skb_queue_tail(&sd->input_pkt_queue, skb);
    input_queue_tail_incr_save(sd, qtail);
  
    napi_schedule_rps(sd);
}
```

## Native Ingress

Recall the dev init func, the default backlog poll func is `process_backlog`.

```c
static int __init net_dev_init(void)
{
	for_each_possible_cpu(i) {
	    ...
		sd->backlog.poll = process_backlog;
	}
```

#### process_backlog

tail process_queue with input_pkt_queue

call [__netif_receive_skb](/docs/CS/OS/Linux/net/network.mdk.md?id=netif_receive_skb) with process_queue

```c

static int process_backlog(struct napi_struct *napi, int quota)
{
	struct softnet_data *sd = container_of(napi, struct softnet_data, backlog);

	while (again) {
		struct sk_buff *skb;
		while ((skb = __skb_dequeue(&sd->process_queue))) {
			__netif_receive_skb(skb);
		}

		if (skb_queue_empty(&sd->input_pkt_queue)) {
			napi->state = 0;
			again = false;
		} else {
			skb_queue_splice_tail_init(&sd->input_pkt_queue, &sd->process_queue);
		}
	}
}
```

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

check RingBuffer

```shell
ethtool -g eth0
```

NIC queue

```shell
ls /sys/class/net/eth0/queues

```

### GSO

Generic Segmentation Offload


#### TSO

TCP Segmentation Offload

OS split segmentation to n * MSS, and let device to split MSS


GRO

```shell
ethtool -k enp0s3 | grep offload
```


```shell
ethtool -k enp0s3 tso off
```

### I/O AT

- Network Flow Affinity
- Asynchronous Lower Copy with DMA
- Optimize Packet

## Links

Return [Linux](/docs/CS/OS/Linux/Linux.md)
