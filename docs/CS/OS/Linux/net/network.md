## Introduction

在 TCP/IP ⽹络分层模型⾥，整个协议栈被分成了物理层、链路层、⽹络层，传输层和应⽤层。
物理层对应的是⽹卡和⽹线，应⽤层对应的是我们常⻅的 Nginx，FTP 等等各种应⽤。
Linux 实现的是链路层、⽹络层和传输层这三层。
在 Linux 内核实现中，链路层协议靠⽹卡驱动来实现，内核协议栈来实现⽹络层和传输层。内核对更上层的应⽤层提供 socket 接⼝来供⽤户进程访问

在 Linux 的源代码中，⽹络设备驱动对应的逻辑位于 `driver/net/ethernet` , 其中 intel 系列⽹卡的
⽬录 `driver/net/ethernet/intel` ⽬录下。
协议栈模块代码位于 kernel 和 net 目录

内核和⽹络设备驱动是通过中断的⽅式来处理的。
当设备上有数据到达的时候，会给 CPU 的相关引脚上触发⼀个电压变化，以通知 CPU 来处理数据。
对于⽹络模块来说，由于处理过程⽐较复杂和耗时，如果在中断函数中完成所有的处理，将会导致中断处理函数（优先级过⾼）将过度占据 CPU ，将导致 CPU ⽆法响应其它设备，例如⿏标和键盘的消息。
因此Linux中断处理函数是分上半部和下半部的。
上半部是只进⾏最简单的⼯作，快速处理然后释放 CPU ，接着 CPU 就可以允许其它中断进来。
剩下将绝⼤部分的⼯作都放到下半部中，可以慢慢从容处理。
2.4 以后的内核版本采⽤的下半部实现⽅式是软中断，由 [ksoftirqd](/docs/CS/OS/Linux/Interrupt.md?id=softirq) 内核线程全权处理。
和硬中断不同的是，硬中断是通过给 CPU 物理引脚施加电压变化，⽽软中断是通过给内存中的⼀个变量的⼆进制值以通知软中断处理程序





Linux 网络子系统使用哈希表管理所有的TCP连接
struct inet_hashinfo
ehash 已经建立连接hash表
bhash bind状态哈希表
lhash2 和 listening_hash 代表listen状态哈希表




## init

网络子系统的初始化流程

Linux 驱动，内核协议栈等等模块在具备接收⽹卡数据包之前，要做很多的准备⼯作才⾏。
⽐如要提前创建好ksoftirqd内核线程，要注册好各个协议对应的处理函数，⽹卡设备⼦系统要提前初始化好，⽹卡要启动好。
只有这些都Ready之后，我们才能真正开始接收数据包。


### Softirq Kernel Thread Creation

Linux 的软中断都是在专⻔的内核线程 [ksoftirqd](/docs/CS/OS/Linux/Interrupt.md?id=init_softirq) 进行
系统初始化时为每个CPU创建独立的 ksoftirqd

### Network Subsystem Initialization

linux 内核通过调⽤ subsys_initcall 来初始化各个⼦系统，在源代码⽬录⾥你可以 grep 出许多对这个函数的调⽤。这⾥我们要说的是⽹络⼦系统的初始化，会执⾏到 net_dev_init 函数

> initcall see [kernel_init](/docs/CS/OS/Linux/boot/init.md?id=kernel_init)

初始化 DEV 模块。
<br/>
引导时遍历设备列表，把初始化失败（通常是硬件不存在）的设备摘除，最终得到一份存在且可用的设备清单。
<br/>
这一步在引导期单线程执行，因此不需要持有 rtnl 信号量。

1. 在这个函数⾥，会为每个 CPU 都申请⼀个 softnet_data 数据结构，在这个数据结构⾥的
poll_list 是等待驱动程序将其 poll 函数注册进来
2.  open_softirq 注册了每⼀种软中断都注册⼀个处理函数。 `NET_TX_SOFTIRQ` 的处理函数为 `net_tx_action`，`NET_RX_SOFTIRQ` 的为 `net_rx_action`。这个注册的⽅式是记录在 softirq_vec 变量⾥的。ksoftirqd 线程收到软中断的时候，也会使⽤这个变量
来找到每⼀种软中断对应的处理函数 注册处理函数见 [softirq](/docs/CS/OS/Linux/Interrupt.md?id=open_softirq)
- [net_rx_action](/docs/CS/OS/Linux/net/network.md?id=net_rx_action) 接收处理函数
- [net_tx_action](/docs/CS/OS/Linux/net/network.md?id=net_tx_action) 发送处理函数


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

### Protocol Stack Registration

内核实现了⽹络层的IP协议，也实现了传输层的TCP协议和UDP协议。这些协议对应的实现函数分别是 `ip_rcv()`、`tcp_v4_rcv()` 和 `udp_rcv() `
fs_initcall 调⽤ inet init 后开始⽹络协议栈注册，通过inet init， 将这些函数注册到 `inet_protos` 和 `ptype_base` 数据结构中

1. IP
2. [UDP](/docs/CS/OS/Linux/net/UDP.md)
3. [TCP](/docs/CS/OS/Linux/net/TCP/TCP.md?id=tcp_init)
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

向网络栈添加一个协议处理函数。
传入的处理对象会被链接进内核链表，在从链表移除之前不可释放。

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

### NIC Driver Initialization

每⼀个驱动程序（不仅仅包括⽹卡驱动程序）会使⽤ `module_init` 向内核注册⼀个初始化函数，当驱动程序被加载时，内核会调⽤这个函数
igb 的初始化函数（igb_init_module）以及它通过 module_init 完成的注册，位于 `drivers/net/ethernet/intel/igb/igb_main.c`。

设备初始化的大部分工作发生在调用 `pci_register_driver` 时。

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

注册一个新的 PCI 驱动

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

probe 函数相当基础，只需完成设备的早期初始化，然后向内核注册网络设备。

`igb_probe` 会做一些重要的网络设备初始化。
除了 PCI 相关工作，它还会完成更通用的网络与网络设备工作：

1. 注册 `struct net_device_ops`；
2. 注册 `ethtool` 操作；
3. 从网卡读取默认 MAC 地址；
4. 设置 `net_device` 的特性标志；
5. 以及其它许多工作。

ndo_open 函数。

```c
static const struct net_device_ops igb_netdev_ops = {
	.ndo_open		= igb_open,
	...
};
```

### Bring Up the Network Card

调用 open 函数 -> 分配收发（RX/TX）内存

__igb_open —— 当网络接口被激活时调用

当系统激活网络接口（IFF_UP）时调用 open 入口。
此时会分配收发所需的全部资源、向系统注册中断处理函数、启动看门狗定时器，并通知协议栈接口已就绪。

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

- igb_tx_buffer 数组
- e1000_adv_tx_desc 的 DMA 数组

检查 RX/TX overruns：

```shell
ifconfig | grep overruns
```

分配了


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

用 `igb_poll` 初始化 NAPI


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

#### igb_request_msix

注册 [igb_msix_ring](/docs/CS/OS/Linux/net/network.md?id=igb_msix_ring)


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

网络包发送流程

### send

沿 socket 向下发送一个数据报。

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


根据fd将真正的Socket找出，这个Socket对象中记录着各种协议栈的函数地址，然后构造struct msghdr对象，将用户需要发送的数据全部封装在这个struct msghdr结构体中




### inet_sendmsg

sock_sendmsg -> sock_sendmsg_nosec -> inet_sendmsg ->

- [udp_sendmsg](/docs/CS/OS/Linux/net/UDP.md?id=udp_sendmsg)
- 或 [tcp_sendmsg](/docs/CS/OS/Linux/net/TCP/TCP.md?id=send)

```c
int inet_sendmsg(struct socket *sock, struct msghdr *msg, size_t size)
{
	struct sock *sk = sock->sk;
	return INDIRECT_CALL_2(sk->sk_prot->sendmsg, tcp_sendmsg, udp_sendmsg,
			       sk, msg, size);
}
```

### ip_queue_xmit

`ip_queue_xmit` 与 `ip_send_skb` 都会调用 [ip_local_out](/docs/CS/OS/Linux/net/IP.md)

<!-- tabs:start -->

##### **ip_queue_xmit**

由 [tcp_transmit_skb](/docs/CS/OS/Linux/net/TCP/TCP.md?id=tcp_transmit_skb) 调用

注意：隧道场景下 skb->sk 可能与 sk 不同

```c
int __ip_queue_xmit(struct sock *sk, struct sk_buff *skb, struct flowi *fl,
		    __u8 tos)
{
    ...
	res = ip_local_out(net, sk, skb);
}
```

##### **ip_send_skb**

由 [UDP](/docs/CS/OS/Linux/net/UDP.md?id=transmit) 调用

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

调用 dev_queue_xmit

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

发送一个缓冲区

把缓冲区排队、准备发送给网络设备。
调用者在调用本函数前必须已设置好设备与优先级，并构造好缓冲区。
本函数可在中断中调用。

失败时返回负的 errno；成功也不保证帧一定被发出——它可能因拥塞或流量整形被丢弃。

要注意本方法也可能返回来自排队规则（qdisc）的错误值，包括正值的 NET_XMIT_DROP，因此错误也可能是正值。

无论返回什么，skb 都会被消耗，所以目前很难对本方法做发送重试。
（若足够小心，可在发送前增加引用计数、保留引用以便重试。）

调用本方法时必须开启中断，因为下半部（BH）的使能代码要求 IRQ 已开启，否则会死锁。

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

qdisc 能直接发送就直接发送，否则把数据排队、留待 NET_TX 软中断发送。

qdisc 内部的入队分类、调度与整形算法（pfifo_fast / fq_codel / HTB / TBF 等）见 [Qdisc](/docs/CS/OS/Linux/net/Qdisc.md)，这里只看驱动出队发送的过程。

当 quota <= 0 时触发 NET_TX_SOFTIRQ，以便执行 net_tx_action 并再次调用 `qdisc_run`

> NET_TX_SOFTIRQ类型的软中断只会在发送网络包时并且当用户线程的CPU quota用尽时，才会触发。剩下的接受过程中触发的软中断类型以及发送完数据触发的软中断类型均为 NET_RX_SOFTIRQ
> 所以这就是你在服务器上查看 /proc/softirqs，一般 NET_RX都要比 NET_TX大很多的的原因
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

最终由不同网卡驱动调用 [ndo_start_xmit](/docs/CS/OS/Linux/net/IP.md)。

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

发送完成后，网卡会触发一个硬中断（hard IRQ）通知完成。
驱动会处理该中断（关闭中断），并调度（软中断）NAPI 轮询机制，由 NAPI 处理接收包信号并释放内存。

数据发送完毕后，网卡设备会向CPU发送一个硬中断，CPU调用网卡驱动程序注册的硬中断响应程序，在硬中断响应中触发NET_RX_SOFTIRQ类型的软中断，
在软中断的回调函数igb_poll中清理释放 sk_buffer，清理网卡发送队列（RingBuffer），解除 DMA 映射


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


这里释放清理的只是sk_buffer的副本，真正的sk_buffer现在还是存放在Socket的发送队列中。
前面在传输层处理的时候我们提到过，因为传输层需要保证可靠性，所以 sk_buffer其实还没有删除。它得等收到对方的 ACK 之后才会真正删除


## Ingress

网络包接收流程

当⽹卡上收到数据以后，Linux 中第⼀个⼯作的模块是⽹络驱动。
⽹络驱动会以 DMA 的⽅式把⽹卡上收到的帧写到内存⾥。再向 CPU 发起⼀个中断，以通知 CPU 有数据到达。
当 CPU 收到中断请求后，会去调⽤⽹络驱动注册的中断处理函数。 
⽹卡的中断处理函数并不做过多⼯作，发出软中断请求，然后尽快释放 CPU。
ksoftirqd 检测到有软中断请求到达，调⽤ poll 开始轮询收包，收到后交由各级协议栈处理。
对于 udp 包来说，会被放到⽤户 socket 的接收队列中。

### driver process


当网络数据帧通过网络传输到达网卡时，网卡会将网络数据帧通过DMA的方式放到环形缓冲区RingBuffer中

RingBuffer是网卡在启动的时候分配和初始化的环形缓冲队列。当RingBuffer满的时候，新来的数据包就会被丢弃。我们可以通过ifconfig命令查看网卡收发数据包的情况。
其中overruns数据项表示当RingBuffer满时，被丢弃的数据包。如果发现出现丢包情况，可以通过ethtool命令来增大RingBuffer长度


#### igb_msix_ring

当DMA操作完成时，网卡会向CPU发起一个硬中断，告诉CPU有网络数据到达。CPU调用网卡驱动注册的硬中断响应程序。
网卡硬中断响应程序会为网络数据帧创建内核数据结构 sk_buffer，并将网络数据帧拷贝到sk_buffer中。然后发起软中断请求，通知内核有新的网络数据帧到达


本函数在[网卡激活](/docs/CS/OS/Linux/net/network.md)时注册，用于处理硬中断

驱动会 `schedule a NAPI`（触发 `soft IRQ (NET_RX_SOFTIRQ)`）。

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

调用 [raise_softirq_irqoff](/docs/CS/OS/Linux/Interrupt.md?id=raise_softirq) 触发 [net_rx_action](/docs/CS/OS/Linux/net/network.md?id=net_rx_action)

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

内核线程 ksoftirqd 发现有软中断请求到来，随后调用网卡驱动注册的poll函数，poll函数将sk_buffer中的网络数据包送到内核协议栈中注册的ip_rcv函数中

> 网卡硬中断响应程序中发出的软中断请求也会在这个CPU绑定的ksoftirqd线程中响应。所以如果发现Linux软中断，CPU消耗都集中在一个核上的话，那么就需要调整硬中断的CPU亲和性来打散硬中断

NAPI 本身的机制——`napi_struct` 的状态位与 SCHED/MISSED 竞态、`net_rx_action` 的 budget 与 repoll 三条去路、`napi_complete_done()` 的中断延迟打开、GRO 攒批、backlog 与 RPS——见 [NAPI](/docs/CS/OS/Linux/net/NAPI.md)。本页只讲它在整条上行里的位置。

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

napi_poll 函数

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
-> __netif_receive_skb_list -> __netif_receive_skb_list_core -> __netif_receive_skb_core（其中含 [tcpdump](/docs/CS/CN/Tools/tcpdump.md) 的处理点）

#### netif_receive_skb

将 packet 送到协议栈

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

转到协议处理函数

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

IP 接收入口

经过 NF_HOOK（iptables，见 [netfilter](/docs/CS/CN/Tools/netfilter.md)）后执行 ip_rcv_finish

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

把来自网络的包送往传输层。

```c
static inline int dst_input(struct sk_buff *skb)
{
	return INDIRECT_CALL_INET(skb_dst(skb)->input,
				  ip6_input, ip_local_deliver, skb);
}
```

#### ip_local_deliver

把 IP 包递交给更高层协议。

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

它调用 L4 协议（`tcp_v4_rcv` 或 `udp_rcv`）

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

协议层把数据挂到属于 socket 的接收缓冲区。

把 skb 加入接收队列尾部，并调用 `sk_data_ready` 唤醒一个进程。

<!-- tabs:start -->

##### **tcp_v4_rcv**

tcp_queue_rcv 与 sk_data_ready 见 [tcp_rcv_established](/docs/CS/OS/Linux/net/TCP/TCP.md?id=tcp_rcv_established)

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

`sk_data_ready` = `sock_def_readable` , 见 [Socket](/docs/CS/OS/Linux/net/socket.md?id=sock_init_data)

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

[wake_up_interruptible_sync_poll](/docs/CS/OS/Linux/proc/thundering_herd.md?id=wake-up), wake up and invoke callback func

## Local Network IO

本机网络 IO 不需要经过真实网卡，节省了驱动层面的一些开销：发送数据不必走 Ring Buffer 的驱动队列，直接把 skb 通过软中断传递给接收协议栈。但系统调用、协议栈、网络设备子系统、“驱动”程序都完整走了一遍。如果需要绕过协议栈的开销，可以使用 eBPF 的 sockmap 与 sk redirect。

> [!NOTE]
>
> 本机 IO 不经过硬中断。

> [!TIP]
>
> 本机 IP 192.168.0.x 和 127.0.0.1 没什么差别，都走虚拟的环回设备 IO。
> 因为内核在设置 IP 时，把所有本机 IP 都初始化到 local 路由表里了，类型写死为 RTN_LOCAL。
> 在后面路由项选择时发现类型是 RTN_LOCAL，就选择环回 IO 设备。

### Loopback Send

回顾[发送流程](/docs/CS/OS/Linux/net/network.md?id=ndo_start_xmit)，环回驱动注册的 `net_device_ops` 为：

```c
static const struct net_device_ops loopback_ops = {
	.ndo_start_xmit  = loopback_xmit,
};

static netdev_tx_t loopback_xmit(struct sk_buff *skb,
				 struct net_device *dev)
{
	skb_orphan(skb);

	__netif_rx(skb);
}
```

`__netif_rx` 把 skb 加入 per-CPU 的 backlog 队列（input_pkt_queue），并为 backlog 设备[调度 NAPI](/docs/CS/OS/Linux/net/network.md?id=napi_schedule)：

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

### backlog Polling

回顾设备初始化函数，backlog 默认的 poll 函数是 `process_backlog`：它把 input_pkt_queue 挂到 process_queue，再逐个出队调用 [__netif_receive_skb](/docs/CS/OS/Linux/net/network.md?id=netif_receive_skb)，让包进入与真实网卡一致的协议栈接收路径。

```c
static int __init net_dev_init(void)
{
	for_each_possible_cpu(i) {
	    ...
		sd->backlog.poll = process_backlog;
	}
}

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
3. 用户进程在 `/etc/security/limits.conf` 中配置

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

### Multi-core Scaling RSS / RPS / RFS / XPS

背景：现代服务器是多 CPU + 多队列网卡，但中断默认集中在某一个 CPU，单 CPU 处理协议栈会先于网卡打满。这一组机制沿"接收中断 → 协议栈处理 → 应用消费 → 发送"链路，把负载和缓存亲和性分散到多核。按软硬与方向区分：

| 机制 | 方向 | 硬件/软件 | 解决的问题 |
| :-- | :-- | :-- | :-- |
| RSS | 接收 | 网卡硬件 | 把不同流的中断 / 接收队列分散到多 CPU |
| RPS | 接收 | 内核软件 | 软件版 RSS，把协议栈处理分散到多 CPU |
| RFS | 接收 | 内核软件(可硬件加速) | 把流导向"消费它的应用"所在 CPU，保缓存命中 |
| XPS | 发送 | 内核软件 | 让每个 CPU 优先用特定发送队列，避免争抢 |

**RSS（Receive Side Scaling）**：网卡对每个包算一个哈希（通常基于四元组，可用 Toeplitz），按一张**间接表（indirection table）**把不同流映射到不同接收队列，每个队列的中断再通过 `smp_affinity` 绑到不同 CPU——于是收包从第一跳就并行。配置：`ethtool -x eth0` 看间接表、`ethtool -X` 改权重。

**RPS（Receive Packet Steering）**：单队列网卡或 RSS 粒度不够时，在 `netif_rx`（驱动把包交给协议栈）之后、按 SKB 的 `rxhash` 把包通过 IPI 投递到目标 CPU 的 per-CPU backlog，让**协议栈处理**（而非仅中断）分散到多核。目标 CPU 由 rx-queue 的 `rps_cpus` 掩码决定：

```shell
# 让 rx 队列 0 的协议栈处理可分散到 CPU 0-15
echo ffff > /sys/class/net/eth0/queues/rx-0/rps_cpus
```

**RFS（Receive Flow Steering）**：RPS 只按哈希静态分散，可消费该 socket 的应用在另一个 CPU，仍有 cache miss 和跨核 IPI。RFS 进一步把流导向**应用所在 CPU**：内核维护一张全局 socket 流表（应用每次 recv/send 更新它期望的 CPU），各 rx 队列再维护一张设备流表记录该流当前被送往的 CPU，两表一致才投递，避免乱序；硬件支持时由网卡做 **aRFS（加速 RFS）**。配置：

```shell
sysctl -w net.core.rps_sock_flow_entries=32768            # 全局表容量
echo 2048 > /sys/class/net/eth0/queues/rx-0/rps_flow_cnt # 每队列表容量
```

**XPS（Transmit Packet Steering）**：发送方向，为每个 tx 队列配置"由哪些 CPU 使用"的掩码，使某 CPU 发包时优先选亲和的队列——避免多个 CPU 争抢同一队列的 `__QUEUE_STATE_*` 锁，也让发送完成中断尽量回到发起 CPU。较新的 `xps_rxqs` 还能让发送队列选择跟随接收队列的 CPU：

```shell
echo ff > /sys/class/net/eth0/queues/tx-0/xps_cpus
```

### Segmentation and Aggregation Offload TSO / GSO / GRO

核心思想是**让协议栈尽量处理少而大的 SKB**，把"切成 MSS 大小"或"合并多个包"的工作尽量推迟到驱动（硬件能做就交给硬件），减少上层处理次数与每包开销。

**GSO（Generic Segmentation Offload）**：协议栈上层只需生成一个可能超过 MSS 的大 SKB，把分段**推迟到提交给驱动之前**；若网卡不支持硬件分段，内核在最后一刻用软件切成 n 个 MSS。这样上层的队列、拥塞、重传逻辑都只需处理一个段。

**TSO（TCP Segmentation Offload）**：GSO 在 TCP 场景的硬件实现——内核把大 SKB 交给网卡，由网卡硬件切成多个 MSS 再发出去。对应还有 UFO（UDP）、以及通用的 `GSO` 隧道场景。

**GRO（Generic Receive Offload）**：接收方向的"反向 TSO"。NAPI 轮询时，`napi_gro_receive` 把属于**同一条流**且连续到达的多个小包（TCP 为主，也覆盖 UDP 隧道 / VXLAN 等）在驱动层聚合成一个大 SKB，再上交给协议栈，显著降低高 PPS 下的每包开销。聚合在以下情况必须 flush：遇到带 TCP PSH、超出 GRO 最大尺寸、超过聚合时间、或属于不同流。它取代了早期的 **LRO**（网卡硬件的接收聚合，过于激进、可能破坏转发，只适合本机终止的流量）。

```shell
ethtool -k eth0 | grep -E 'tcp-segmentation|generic-receive|generic-segmentation'
ethtool -K eth0 tso off gro off gso off   # 按需开关（基准测试时常临时关闭以排除干扰）
```

### I/O AT

- 网络流亲和性（Network Flow Affinity）
- 基于 DMA 的异步底层拷贝（Asynchronous Lower Copy）
- 优化数据包

## Links

- [网络知识地图](/docs/CS/OS/Linux/net/README.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)
- [Nginx Event](/docs/CS/CN/nginx/event.md) — 协议栈之上的用户态事件驱动服务端
