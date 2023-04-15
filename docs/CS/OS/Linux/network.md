## Introduction

Linux provide drivers and protocols
driver：drivers/net/ethernet
protocol: kernel & net

The high-level path network data takes from a user program to a network device is as follows:

1. Data is written using a system call (like `sendto`, `sendmsg`, et. al.).
2. Data passes through the socket subsystem on to the socket’s protocol family’s system (in our case, `AF_INET`).
3. The protocol family passes data through the protocol layers which (in many cases) arrange the data into packets.
4. The data passes through the routing layer, populating the destination and neighbour caches along the way (if they are cold). This can generate ARP traffic if an ethernet address needs to be looked up.
5. After passing through the protocol layers, packets reach the device agnostic layer.
6. The output queue is chosen using XPS (if enabled) or a hash function.
7. The device driver’s transmit function is called.
8. The data is then passed on to the queue discipline (qdisc) attached to the output device.
9. The qdisc will either transmit the data directly if it can, or queue it up to be sent during the `NET_TX` softirq.
10. Eventually the data is handed down to the driver from the qdisc.
11. The driver creates the needed DMA mappings so the device can read the data from RAM.
12. The driver signals the device that the data is ready to be transmit.
13. The device fetches the data from RAM and transmits it.
14. Once transmission is complete, the device raises an interrupt to signal transmit completion.
15. The driver’s registered IRQ handler for transmit completion runs. For many devices, this handler simply triggers the NAPI poll loop to start running via the `NET_RX` softirq.
16. The poll function runs via a softIRQ and calls down into the driver to unmap DMA regions and free packet data.

The high level path a packet takes from arrival to socket receive buffer is as follows:

1. Driver is loaded and initialized.
2. Packet arrives at the NIC from the network.
3. Packet is copied (via DMA) to a ring buffer in kernel memory.
4. Hardware interrupt is generated to let the system know a packet is in memory.
5. Driver calls into [NAPI](http://www.linuxfoundation.org/collaborate/workgroups/networking/napi) to start a poll loop if one was not running already.
6. `ksoftirqd` processes run on each CPU on the system. They are registered at boot time. The  processes pull packets off the ring buffer by calling the NAPI  function that the device driver registered during initialization.`ksoftirqd``poll`
7. Memory regions in the ring buffer that have had network data written to them are unmapped.
8. Data that was DMA’d into memory is passed up the networking layer as an ‘skb’ for more processing.
9. Incoming network data frames are distributed among multiple CPUs if packet steering is enabled or if the NIC has multiple receive queues.
10. Network data frames are handed to the protocol layers from the queues.
11. Protocol layers process data.
12. Data is added to receive buffers attached to sockets by protocol layers.


## init

### init net dev

initcall see [kernel_init](/docs/CS/OS/Linux/init.md?id=kernel_init)

Initialize the DEV module.
At boot time this walks the device list and unhooks any devices that fail to initialise (normally hardware not present) and leaves us with a valid list of present and active devices.

This is called single threaded during boot, so no need to take the rtnl semaphore.

```c
// net/core/dev.c
subsys_initcall(net_dev_init);

static int __init net_dev_init(void)
{
```
Initialise the packet receive queues for each cpu.
```c
	for_each_possible_cpu(i) {
		struct work_struct *flush = per_cpu_ptr(&flush_works, i);
		struct softnet_data *sd = &per_cpu(softnet_data, i);

		INIT_WORK(flush, flush_backlog);

		skb_queue_head_init(&sd->input_pkt_queue);
		skb_queue_head_init(&sd->process_queue);
		INIT_LIST_HEAD(&sd->poll_list);
		sd->output_queue_tailp = &sd->output_queue;

		init_gro_hash(&sd->backlog);
		sd->backlog.poll = process_backlog;
		sd->backlog.weight = weight_p;
	}
```

register func with [softirq](/docs/CS/OS/Linux/Interrupt.md?id=open_softirq)

- [net_rx_action](/docs/CS/OS/Linux/network.md?id=net_rx_action) receive func
- [net_tx_action](/docs/CS/OS/Linux/network.md?id=net_tx_action) transmit func

```c
	open_softirq(NET_TX_SOFTIRQ, net_tx_action);
	open_softirq(NET_RX_SOFTIRQ, net_rx_action);
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

register [netif_receive_skb](/docs/CS/OS/Linux/network.md?id=netif_receive_skb) func.

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


Register protocols into `inet_protos` and `ptype_base`:

1. ICMP
2. [UDP](/docs/CS/OS/Linux/UDP.md)
3. [TCP](/docs/CS/OS/Linux/TCP.md?id=tcp_init)
4. IGMP
5. ...

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
#ifdef CONFIG_IP_MULTICAST
	if (inet_add_protocol(&igmp_protocol, IPPROTO_IGMP) < 0)
		pr_crit("%s: Cannot add IGMP protocol\n", __func__);
#endif
    ......

	arp_init();
	ip_init();
	tcp_init();
	udp_init();
	udplite4_register();
	raw_init();
	ping_init();
  
    dev_add_pack(&ip_packet_type);
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

Add a protocol handler to the networking stack.
The passed &packet_type is linked into kernel lists and may not be freed until it has been removed from the kernel lists.


```c
// net/ipv4/protocol.c
int inet_add_protocol(const struct net_protocol *prot, unsigned char protocol)
{
	return !cmpxchg((const struct net_protocol **)&inet_protos[protocol],
			NULL, prot) ? 0 : -1;
}

// net/core/dev.c
void dev_add_pack(struct packet_type *pt)
{
	struct list_head *head = ptype_head(pt);

	spin_lock(&ptype_lock);
	list_add_rcu(&pt->list, head);
	spin_unlock(&ptype_lock);
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

Network Device Driver Initialization

A driver registers an initialization function which is called by the kernel when the driver is loaded.
This function is registered by using the module_init macro.
The igb initialization function (igb_init_module) and its registration with module_init can be found in `drivers/net/ethernet/intel/igb/igb_main.c`.

The bulk of the work to initialize the device happens with the call to pci_register_driver.

```c
//  igb_main.c
static struct pci_driver igb_driver = {
	.name     = igb_driver_name,
	.id_table = igb_pci_tbl,
	.probe    = igb_probe,
	.remove   = igb_remove,
#ifdef CONFIG_PM
	.driver.pm = &igb_pm_ops,
#endif
	.shutdown = igb_shutdown,
	.sriov_configure = igb_pci_sriov_configure,
	.err_handler = &igb_err_handler
};

static int __init igb_init_module(void)
{
	int ret;

	pr_info("%s\n", igb_driver_string);
	pr_info("%s\n", igb_copyright);

#ifdef CONFIG_IGB_DCA
	dca_register_notify(&dca_notifier);
#endif
	ret = pci_register_driver(&igb_driver);
	return ret;
}

module_init(igb_init_module);
```

The probe function is quite basic, and only needs to perform a device's early init, and then register our network device with the kernel.

In other words, the probe function has to:

1. Allocate the network device along with its private data using the alloc_etherdev() function (helped by netdev_priv()).
2. Initialize private data fields (mutexes, spinlock, work_queue, and so on). You should use work queues (and mutexes) if the device sits on a bus whose access functions may sleep (SPI, for example).
   In this case, the hwirq just has to acknowledge the kernel code, and schedule the job that will perform operations on the device. An alternative solution is to use threaded IRQs.
   If the device is MMIO, you can use spinlock to protect ...

The `igb_probe` function does some important network device initialization.
In addition to the PCI specific work, it will do more general networking and network device work:

1. The `struct net_device_ops` is registered.
2. `ethtool` operations are registered.
3. The default MAC address is obtained from the NIC.
4. `net_device` feature flags are set.
5. And lots more.

```c

static const struct net_device_ops igb_netdev_ops = {
	.ndo_open		= igb_open,
	.ndo_stop		= igb_close,
	.ndo_start_xmit		= igb_xmit_frame,
	.ndo_get_stats64	= igb_get_stats64,
	.ndo_set_rx_mode	= igb_set_rx_mode,
	.ndo_set_mac_address	= igb_set_mac,
	.ndo_change_mtu		= igb_change_mtu,
	.ndo_eth_ioctl		= igb_ioctl,
	.ndo_tx_timeout		= igb_tx_timeout,
	.ndo_validate_addr	= eth_validate_addr,
	.ndo_vlan_rx_add_vid	= igb_vlan_rx_add_vid,
	.ndo_vlan_rx_kill_vid	= igb_vlan_rx_kill_vid,
	.ndo_set_vf_mac		= igb_ndo_set_vf_mac,
	.ndo_set_vf_vlan	= igb_ndo_set_vf_vlan,
	.ndo_set_vf_rate	= igb_ndo_set_vf_bw,
	.ndo_set_vf_spoofchk	= igb_ndo_set_vf_spoofchk,
	.ndo_set_vf_trust	= igb_ndo_set_vf_trust,
	.ndo_get_vf_config	= igb_ndo_get_vf_config,
	.ndo_fix_features	= igb_fix_features,
	.ndo_set_features	= igb_set_features,
	.ndo_fdb_add		= igb_ndo_fdb_add,
	.ndo_features_check	= igb_features_check,
	.ndo_setup_tc		= igb_setup_tc,
	.ndo_bpf		= igb_xdp,
	.ndo_xdp_xmit		= igb_xdp_xmit,
};
```

### open network interface

call open function -> allocate RX TX memory

__igb_open - Called when a network interface is made active

The open entry point is called when a network interface is made active by the system (IFF_UP).
At this point all resources needed for transmit and receive operations are allocated, the interrupt handler is registered with the OS, the watchdog timer is started, and the stack is notified that the interface is ready.

```c
static int __igb_open(struct net_device *netdev, bool resuming)
{
	struct igb_adapter *adapter = netdev_priv(netdev);
	struct e1000_hw *hw = &adapter->hw;
	struct pci_dev *pdev = adapter->pdev;
	int err;
	int i;

	/* disallow open during test */
	if (test_bit(__IGB_TESTING, &adapter->state)) {
		WARN_ON(resuming);
		return -EBUSY;
	}

	if (!resuming)
		pm_runtime_get_sync(&pdev->dev);

	netif_carrier_off(netdev);

	/* allocate transmit descriptors */
	err = igb_setup_all_tx_resources(adapter);
	if (err)
		goto err_setup_tx;

	/* allocate receive descriptors */
	err = igb_setup_all_rx_resources(adapter);
	if (err)
		goto err_setup_rx;

	igb_power_up_link(adapter);

	/* before we allocate an interrupt, we must be ready to handle it.
	 * Setting DEBUG_SHIRQ in the kernel makes it fire an interrupt
	 * as soon as we call pci_request_irq, so we have to setup our
	 * clean_rx handler before we do so.
	 */
	igb_configure(adapter);

	err = igb_request_irq(adapter);
	if (err)
		goto err_req_irq;

	/* Notify the stack of the actual queue counts. */
	err = netif_set_real_num_tx_queues(adapter->netdev,
					   adapter->num_tx_queues);
	if (err)
		goto err_set_queues;

	err = netif_set_real_num_rx_queues(adapter->netdev,
					   adapter->num_rx_queues);
	if (err)
		goto err_set_queues;

	/* From here on the code is the same as igb_up() */
	clear_bit(__IGB_DOWN, &adapter->state);

	for (i = 0; i < adapter->num_q_vectors; i++)
		napi_enable(&(adapter->q_vector[i]->napi));

	/* Clear any pending interrupts. */
	rd32(E1000_TSICR);
	rd32(E1000_ICR);

	igb_irq_enable(adapter);

	/* notify VFs that reset has been completed */
	if (adapter->vfs_allocated_count) {
		u32 reg_data = rd32(E1000_CTRL_EXT);

		reg_data |= E1000_CTRL_EXT_PFRSTD;
		wr32(E1000_CTRL_EXT, reg_data);
	}

	netif_tx_start_all_queues(netdev);

	if (!resuming)
		pm_runtime_put(&pdev->dev);

	/* start the watchdog. */
	hw->mac.get_link_status = 1;
	schedule_work(&adapter->watchdog_task);

	return 0;

err_set_queues:
	igb_free_irq(adapter);
err_req_irq:
	igb_release_hw_control(adapter);
	igb_power_down_link(adapter);
	igb_free_all_rx_resources(adapter);
err_setup_rx:
	igb_free_all_tx_resources(adapter);
err_setup_tx:
	igb_reset(adapter);
	if (!resuming)
		pm_runtime_put(&pdev->dev);

	return err;
}
```

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

register irq

```c
static int igb_request_irq(struct igb_adapter *adapter)
{
	struct net_device *netdev = adapter->netdev;
	struct pci_dev *pdev = adapter->pdev;
	int err = 0;

	if (adapter->flags & IGB_FLAG_HAS_MSIX) {
		err = igb_request_msix(adapter);
		if (!err)
			goto request_done;
		/* fall back to MSI */
		igb_free_all_tx_resources(adapter);
		igb_free_all_rx_resources(adapter);

		igb_clear_interrupt_scheme(adapter);
		err = igb_init_interrupt_scheme(adapter, false);
		if (err)
			goto request_done;

		igb_setup_all_tx_resources(adapter);
		igb_setup_all_rx_resources(adapter);
		igb_configure(adapter);
	}

	igb_assign_vector(adapter->q_vector[0], 0);

	if (adapter->flags & IGB_FLAG_HAS_MSI) {
		err = request_irq(pdev->irq, igb_intr_msi, 0,
				  netdev->name, adapter);
		if (!err)
			goto request_done;

		/* fall back to legacy interrupts */
		igb_reset_interrupt_capability(adapter);
		adapter->flags &= ~IGB_FLAG_HAS_MSI;
	}

	err = request_irq(pdev->irq, igb_intr, IRQF_SHARED,
			  netdev->name, adapter);

request_done:
	return err;
}


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


## Ingress

1. Packets arrive at the NIC
2. NIC will verify `MAC` (if not on promiscuous mode) and `FCS` and decide to drop or to continue
3. NIC will [DMA packets at RAM](https://en.wikipedia.org/wiki/Direct_memory_access), in a region previously prepared (mapped) by the driver
4. NIC will enqueue references to the packets at receive [ring buffer](https://en.wikipedia.org/wiki/Circular_buffer) queue `rx` until `rx-usecs` timeout or `rx-frames`
5. NIC will raise a `hard IRQ`
6. CPU will run the `IRQ handler` that runs the driver's code
7. Driver will `schedule a NAPI`, clear the `hard IRQ` and return
8. Driver raise a `soft IRQ (NET_RX_SOFTIRQ)`
9. NAPI will poll data from the receive ring buffer until `netdev_budget_usecs` timeout or `netdev_budget` and `dev_weight` packets
10. Linux will also allocate memory to `sk_buff`
11. Linux fills the metadata: protocol, interface, setmacheader, removes ethernet
12. Linux will pass the skb to the kernel stack (`netif_receive_skb`)
13. It will set the network header, clone `skb` to taps (i.e. [tcpdump](/docs/CS/CN/Tools/tcpdump.md)) and pass it to tc ingress
14. Packets are handled to a qdisc sized `netdev_max_backlog` with its algorithm defined by `default_qdisc`
15. It calls `ip_rcv` and packets are handled to IP
16. It calls [netfilter](/docs/CS/CN/Tools/netfilter.md) (`PREROUTING`)
17. It looks at the routing table, if forwarding or local
18. If it's local it calls netfilter (`LOCAL_IN`)
19. It calls the L4 protocol (for instance `tcp_v4_rcv`)
20. It finds the right socket
21. It goes to the tcp finite state machine
22. Enqueue the packet to the receive buffer and sized as `tcp_rmem` rules
    1. If `tcp_moderate_rcvbuf` is enabled kernel will auto-tune the receive buffer
23. Kernel will signalize that there is data available to apps (epoll or any polling system)
24. Application wakes up and reads the data



like UDP will add into socket accept queue

TODO: [tcp-rcv](https://www.processon.com/diagraming/6195c8be07912906e6ab82c8)

### driver process

Hard interrupt

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
```

call napi_poll function

```
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


```

irq disabled and enabled around.

```c
	local_irq_disable();

	list_splice_tail_init(&sd->poll_list, &list);
	list_splice_tail(&repoll, &list);
	list_splice(&list, &sd->poll_list);
	if (!list_empty(&sd->poll_list))
		__raise_softirq_irqoff(NET_RX_SOFTIRQ);

	net_rps_action_and_irq_enable(sd);
}
```

napi_poll function

```c
static int igb_poll(struct napi_struct *napi, int budget)
{
	struct igb_q_vector *q_vector = container_of(napi,
						     struct igb_q_vector,
						     napi);
	bool clean_complete = true;
	int work_done = 0;

#ifdef CONFIG_IGB_DCA
	if (q_vector->adapter->flags & IGB_FLAG_DCA_ENABLED)
		igb_update_dca(q_vector);
#endif
	if (q_vector->tx.ring)
		clean_complete = igb_clean_tx_irq(q_vector, budget);

	if (q_vector->rx.ring) {
		int cleaned = igb_clean_rx_irq(q_vector, budget);

		work_done += cleaned;
		if (cleaned >= budget)
			clean_complete = false;
	}

	/* If all work not completed, return budget and keep polling */
	if (!clean_complete)
		return budget;

	/* Exit the polling mode, but don't re-enable interrupts if stack might
	 * poll us due to busy-polling
	 */
	if (likely(napi_complete_done(napi, work_done)))
		igb_ring_irq_enable(q_vector);

	return work_done;
}
```

igb_get_rx_buffer

```c

static int igb_clean_rx_irq(struct igb_q_vector *q_vector, const int budget)
{
	struct igb_adapter *adapter = q_vector->adapter;
	struct igb_ring *rx_ring = q_vector->rx.ring;
	struct sk_buff *skb = rx_ring->skb;
	unsigned int total_bytes = 0, total_packets = 0;
	u16 cleaned_count = igb_desc_unused(rx_ring);
	unsigned int xdp_xmit = 0;
	struct xdp_buff xdp;
	u32 frame_sz = 0;
	int rx_buf_pgcnt;

	/* Frame size depend on rx_ring setup when PAGE_SIZE=4K */
#if (PAGE_SIZE < 8192)
	frame_sz = igb_rx_frame_truesize(rx_ring, 0);
#endif
	xdp_init_buff(&xdp, frame_sz, &rx_ring->xdp_rxq);

	while (likely(total_packets < budget)) {
		union e1000_adv_rx_desc *rx_desc;
		struct igb_rx_buffer *rx_buffer;
		ktime_t timestamp = 0;
		int pkt_offset = 0;
		unsigned int size;
		void *pktbuf;


		/* return some buffers to hardware, one at a time is too slow */
		if (cleaned_count >= IGB_RX_BUFFER_WRITE) {
			igb_alloc_rx_buffers(rx_ring, cleaned_count);
			cleaned_count = 0;
		}

		rx_desc = IGB_RX_DESC(rx_ring, rx_ring->next_to_clean);
		size = le16_to_cpu(rx_desc->wb.upper.length);
		if (!size)
			break;

		/* This memory barrier is needed to keep us from reading
		 * any other fields out of the rx_desc until we know the
		 * descriptor has been written back
		 */
		dma_rmb();

		rx_buffer = igb_get_rx_buffer(rx_ring, size, &rx_buf_pgcnt);
		pktbuf = page_address(rx_buffer->page) + rx_buffer->page_offset;

		/* pull rx packet timestamp if available and valid */
		if (igb_test_staterr(rx_desc, E1000_RXDADV_STAT_TSIP)) {
			int ts_hdr_len;

			ts_hdr_len = igb_ptp_rx_pktstamp(rx_ring->q_vector,
							 pktbuf, &timestamp);

			pkt_offset += ts_hdr_len;
			size -= ts_hdr_len;
		}

		/* retrieve a buffer from the ring */
		if (!skb) {
			unsigned char *hard_start = pktbuf - igb_rx_offset(rx_ring);
			unsigned int offset = pkt_offset + igb_rx_offset(rx_ring);

			xdp_prepare_buff(&xdp, hard_start, offset, size, true);
			xdp_buff_clear_frags_flag(&xdp);
#if (PAGE_SIZE > 4096)
			/* At larger PAGE_SIZE, frame_sz depend on len size */
			xdp.frame_sz = igb_rx_frame_truesize(rx_ring, size);
#endif
			skb = igb_run_xdp(adapter, rx_ring, &xdp);
		}

		if (IS_ERR(skb)) {
			unsigned int xdp_res = -PTR_ERR(skb);

			if (xdp_res & (IGB_XDP_TX | IGB_XDP_REDIR)) {
				xdp_xmit |= xdp_res;
				igb_rx_buffer_flip(rx_ring, rx_buffer, size);
			} else {
				rx_buffer->pagecnt_bias++;
			}
			total_packets++;
			total_bytes += size;
		} else if (skb)
			igb_add_rx_frag(rx_ring, rx_buffer, skb, size);
		else if (ring_uses_build_skb(rx_ring))
			skb = igb_build_skb(rx_ring, rx_buffer, &xdp,
					    timestamp);
		else
			skb = igb_construct_skb(rx_ring, rx_buffer,
						&xdp, timestamp);

		/* exit if we failed to retrieve a buffer */
		if (!skb) {
			rx_ring->rx_stats.alloc_failed++;
			rx_buffer->pagecnt_bias++;
			break;
		}

		igb_put_rx_buffer(rx_ring, rx_buffer, rx_buf_pgcnt);
		cleaned_count++;

		/* fetch next buffer in frame if non-eop */
		if (igb_is_non_eop(rx_ring, rx_desc))
			continue;

		/* verify the packet layout is correct */
		if (igb_cleanup_headers(rx_ring, rx_desc, skb)) {
			skb = NULL;
			continue;
		}

		/* probably a little skewed due to removing CRC */
		total_bytes += skb->len;

		/* populate checksum, timestamp, VLAN, and protocol */
		igb_process_skb_fields(rx_ring, rx_desc, skb);
```

napi_gro_receive

```
		napi_gro_receive(&q_vector->napi, skb);

		/* reset skb pointer */
		skb = NULL;

		/* update budget accounting */
		total_packets++;
	}

	/* place incomplete frames back on ring for completion */
	rx_ring->skb = skb;

	if (xdp_xmit & IGB_XDP_REDIR)
		xdp_do_flush();

	if (xdp_xmit & IGB_XDP_TX) {
		struct igb_ring *tx_ring = igb_xdp_tx_queue_mapping(adapter);

		igb_xdp_ring_update_tail(tx_ring);
	}

	u64_stats_update_begin(&rx_ring->rx_syncp);
	rx_ring->rx_stats.packets += total_packets;
	rx_ring->rx_stats.bytes += total_bytes;
	u64_stats_update_end(&rx_ring->rx_syncp);
	q_vector->rx.total_packets += total_packets;
	q_vector->rx.total_bytes += total_bytes;

	if (cleaned_count)
		igb_alloc_rx_buffers(rx_ring, cleaned_count);

	return total_packets;
}
```

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
-> __netif_receive_skb_list -> __netif_receive_skb_list_core -> __netif_receive_skb_core(contains [tcpdump](/docs/CS/CN/Tools/tcpdump.md)) -> deliver_skb


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
}
```



## Egress

1. Application sends message (`sendmsg` or other)
2. TCP send message allocates skb_buff
3. It enqueues skb to the socket write buffer of `tcp_wmem` size
4. Builds the TCP header (src and dst port, checksum)
5. Calls L3 handler (in this case `ipv4` on `tcp_write_xmit` and `tcp_transmit_skb`)
6. L3 (`ip_queue_xmit`) does its work: build ip header and call netfilter (`LOCAL_OUT`)
7. Calls output route action
8. Calls netfilter (`POST_ROUTING`)
9. Fragment the packet (`ip_output`)
10. Calls L2 send function (`dev_queue_xmit`)
11. Feeds the output (QDisc) queue of `txqueuelen` length with its algorithm `default_qdisc`
12. The driver code enqueue the packets at the `ring buffer tx`
13. The driver will do a `soft IRQ (NET_TX_SOFTIRQ)` after `tx-usecs` timeout or `tx-frames`
14. Re-enable hard IRQ to NIC
15. Driver will map all the packets (to be sent) to some DMA'ed region
16. NIC fetches the packets (via DMA) from RAM to transmit
17. After the transmission NIC will raise a `hard IRQ` to signal its completion
18. The driver will handle this IRQ (turn it off)
19. And schedule (`soft IRQ`) the NAPI poll system
20. NAPI will handle the receive packets signaling and free the RAM


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

TCP Segmentation Offload

OS split segmentation to n * MSS, and let device to split MSS

### I/O AT

- Network Flow Affinity
- Asynchronous Lower Copy with DMA
- Optimize Packet

## Links

Return [Linux](/docs/CS/OS/Linux/Linux.md)
