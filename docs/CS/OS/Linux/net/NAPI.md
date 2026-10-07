## Introduction

网卡收到一个帧，最直接的响应是发一个硬中断让 CPU 来取。低速网络这没问题，但到了万兆、十万兆——每秒上百万个包——这个模型会崩：CPU 全部时间花在进出中断上下文上，收包队列始终填满，协议栈反而得不到执行机会，系统看起来"还活着但什么都不干"。这个现象有个专门的名字：**接收活锁（receive livelock）**。

NAPI（New API）就是为解决它而生的。它的思路是**中断与轮询的混合**：网卡空闲时用中断，一有包立刻知道；一旦进入持续收包状态，就**关掉该队列的中断、转为轮询**，一次轮询批量收割几十上百个包，收干净了再开中断睡觉。于是开销从"每包一次中断"摊薄成"每批一次中断"。

.Netdev 之外，NAPI 还有第二个价值：它把"收包"抽象成了一个**可调度的实体**（`struct napi_struct`），而不是绑定在中断处理里。这让内核能用同一个框架表达硬件多队列（RSS）、软件分发（RPS）、GRO 聚合、忙轮询、线程化 NAPI 等完全不同的机制，甚至"没有硬件队列的兜底队列"（backlog）也是一个 NAPI 实例。

本页专讲这条收包主线本身的机制。整条上行（驱动 → 协议栈 → socket 唤醒）见 [network 的 Ingress 章](/docs/CS/OS/Linux/net/network.md?id=net_rx_action)，发送侧的对应机制见 [Qdisc](/docs/CS/OS/Linux/net/Qdisc.md)。

## Why Pure Interrupts Do Not Work

先把问题说清楚，才知道 NAPI 每个设计取舍的来由。三个方案的对照：

| 方案 | 空闲时开销 | 高负载时开销 | 延迟 | 问题 |
|---|---|---|---|---|
| 纯中断 | 零 | 极高 | 低 | 每包一次中断上下文切换 + cache/TLB 冲刷；高 PPS 下 CPU 全被中断吃掉 → **livelock** |
| 纯轮询 | 100% CPU 空转 | 低（批量摊薄） | 取决于轮询频率 | 空闲时白烧 CPU；轮询间隔长则延迟高 |
| **NAPI** | 零（靠中断唤醒） | 低（批量收割） | 低 | 需要状态机管理"中断开关"与"收完了吗" |

livelock 的关键在于**中断优先级高于一切**：只要网卡持续来包，硬中断就会不断抢占正在跑的协议栈代码，而协议栈正是唯一能消耗掉这些包的那一方。结果是一个自我维持的死循环——CPU 在中断上打满，吞吐量反而接近零。

NAPI 的破解点很直接：**在忙的时候不让网卡发中断**。没有中断就不会被抢占，协议栈得以连续运行，收完一批再开中断。

## Core Structure: napi_struct

一个 NAPI 实例通常对应**一个接收队列**（多队列网卡每个队列一个，配合 RSS 分散到不同 CPU）。定义如下（6.12 `include/linux/netdevice.h`）：

```c
struct napi_struct {
	/* The poll_list must only be managed by the entity which
	 * changes the state of the NAPI_STATE_SCHED bit.  This means
	 * whoever atomically sets that bit can add this napi_struct
	 * to the per-CPU poll_list, and whoever clears that bit
	 * can remove from the list right before clearing the bit.
	 */
	struct list_head	poll_list;

	unsigned long		state;
	int			weight;
	u32			defer_hard_irqs_count;
	unsigned long		gro_bitmask;
	int			(*poll)(struct napi_struct *, int);
#ifdef CONFIG_NETPOLL
	/* CPU actively polling if netpoll is configured */
	int			poll_owner;
#endif
	/* CPU on which NAPI has been scheduled for processing */
	int			list_owner;
	struct net_device	*dev;
	struct gro_list		gro_hash[GRO_HASH_BUCKETS];
	struct sk_buff		*skb;
	struct list_head	rx_list; /* Pending GRO_NORMAL skbs */
	int			rx_count; /* length of rx_list */
	unsigned int		napi_id;
	struct hrtimer		timer;
	struct task_struct	*thread;
	/* control-path-only fields follow */
	struct list_head	dev_list;
	struct hlist_node	napi_hash_node;
	int			irq;
};
```

字段按职责分成四组：

- **调度**：`poll_list`（挂到 per-CPU 待轮询链表）、`state`（状态位图）、`list_owner`（当前挂在哪个 CPU 上）。注释里那句"谁设置 SCHED 位谁负责加链表，谁清位谁负责摘链表"是理解 NAPI 并发模型的钥匙——**链表操作与状态位绑定**，因此不需要额外的大锁。
- **收割**：`poll`（驱动提供的收割回调）、`weight`（一次轮询最多收多少包，`netif_napi_add()` 默认 `NAPI_POLL_WEIGHT` = 64）。
- **聚合**：`gro_hash[]`、`rx_list`、`rx_count`、`gro_bitmask`——GRO 状态直接挂在 NAPI 上，每个 NAPI 有自己独立的聚合表，见下文 GRO 一节。
- **现代扩展**：`defer_hard_irqs_count` + `timer`（中断延迟打开与超时兜底）、`thread`（线程化 NAPI）、`irq`（绑定的中断号，供 irq/NAPI 亲和性调优）。

**状态位**是 NAPI 并发控制的核心，全部是位图上的原子操作：

```c
enum {
	NAPI_STATE_SCHED,		/* Poll is scheduled */
	NAPI_STATE_MISSED,		/* reschedule a napi */
	NAPI_STATE_DISABLE,		/* Disable pending */
	NAPI_STATE_NPSVC,		/* Netpoll - don't dequeue from poll_list */
	NAPI_STATE_LISTED,		/* NAPI added to system lists */
	NAPI_STATE_NO_BUSY_POLL,	/* Do not add in napi_hash, no busy polling */
	NAPI_STATE_IN_BUSY_POLL,	/* sk_busy_loop() owns this NAPI */
	NAPI_STATE_PREFER_BUSY_POLL,	/* prefer busy-polling over softirq processing*/
	NAPI_STATE_THREADED,		/* The poll is performed inside its own thread*/
	NAPI_STATE_SCHED_THREADED,	/* Napi is currently scheduled in threaded mode */
};
```

最需要理解的是 `SCHED` 与 `MISSED` 的配合。`SCHED` 表示"已在待轮询链表里（或正被处理）"，它的存在保证了**同一个 NAPI 不会被两个 CPU 同时 poll**。而 `MISSED` 解决一个微妙竞态：轮询进行中网卡又来了新包，此时 `SCHED` 已置位，中断处理不能再把它加进链表（会破坏链表），于是改成置 `MISSED` 位——等这一轮 poll 结束时，若发现 `MISSED` 被置过，就**再排一轮**，从而不丢包。

## Scheduling Side: softnet_data

NAPI 不是全局管理的，而是**每 CPU 一份**（`net/core/dev.c`）：

```c
DEFINE_PER_CPU_ALIGNED(struct softnet_data, softnet_data) = {
	.process_queue_bh_lock = INIT_LOCAL_LOCK(process_queue_bh_lock),
};
```

`struct softnet_data` 中与收包相关的字段（`include/linux/netdevice.h`）：

```c
struct softnet_data {
	struct list_head	poll_list;
	struct sk_buff_head	process_queue;
	local_lock_t		process_queue_bh_lock;

	/* stats */
	unsigned int		processed;
	unsigned int		time_squeeze;
	...
	unsigned int		received_rps;
	bool			in_net_rx_action;
	bool			in_napi_threaded_poll;
	...
	struct sk_buff_head	input_pkt_queue;
	struct napi_struct	backlog;

	atomic_t		dropped ____cacheline_aligned_in_smp;
	...
};
```

要点：

- `poll_list` 是**本 CPU 待轮询的 NAPI 链表**，`net_rx_action` 逐个取出执行。
- `backlog` 是一个内嵌的 NAPI 实例——它不对应硬件队列，而是"没有硬件队列时的兜底队列"，RPS 也借用它，见下文。
- `input_pkt_queue` / `process_queue` 是 backlog 用的**双队列**：前者接收生产者塞入的包，后者是当前这一轮正在处理的快照。分成两个队列是为了让"入队"和"出队"不必同一把锁互相阻塞。
- `time_squeeze`、`processed`、`dropped`、`received_rps` 是观测计数，直接对应 `/proc/net/softnet_stat`。
- 结构是 `____cacheline_aligned_in_smp` 对齐的 per-CPU 数据，因此**本 CPU 访问无需加锁**——这是收包路径能无锁化的基础。

## Scheduling: From Hard Interrupt to poll_list

驱动在硬中断里做的事极少，典型实现就一行（`igb_msix_ring`，完整上下文见 [network 的 driver process 章](/docs/CS/OS/Linux/net/network.md?id=igb_msix_ring)）：

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

`napi_schedule()` 分两步，先判断再排队（`include/linux/netdevice.h`）：

```c
static inline bool napi_schedule(struct napi_struct *n)
{
	if (napi_schedule_prep(n)) {
		__napi_schedule(n);
		return true;
	}

	return false;
}
```

判断逻辑 `napi_schedule_prep()` 是整个机制里最精巧的一段（`net/core/dev.c`）：

```c
bool napi_schedule_prep(struct napi_struct *n)
{
	unsigned long new, val = READ_ONCE(n->state);

	do {
		if (unlikely(val & NAPIF_STATE_DISABLE))
			return false;
		new = val | NAPIF_STATE_SCHED;

		/* Sets STATE_MISSED bit if STATE_SCHED was already set
		 * This was suggested by Alexander Duyck, as compiler
		 * emits better code than :
		 * if (val & NAPIF_STATE_SCHED)
		 *     new |= NAPIF_STATE_MISSED;
		 */
		new |= (val & NAPIF_STATE_SCHED) / NAPIF_STATE_SCHED *
					   NAPIF_STATE_MISSED;
	} while (!try_cmpxchg(&n->state, &val, new));

	return !(val & NAPIF_STATE_SCHED);
}
```

三件事：

1. **返回值即"是不是我把它排上队的"**。只有原本 `SCHED` 未置位（即原来不在链表里）才返回 true，调用方据此才真正 `list_add`。这正是 `napi_struct` 注释里那条规则的实现。
2. **(val & SCHED)/SCHED * MISSED** 是个除法技巧，等价于 `if (val & SCHED) new |= MISSED`，但生成的指令更少。注意它是在**循环内**算的，因为 `try_cmpxchg` 失败后 `val` 会更新为新读到的值。
3. **`DISABLE` 优先**：正在被禁用（设备关闭/暂停）时直接放弃调度。

通过 prep 后，`__napi_schedule()` 把 NAPI 挂到本 CPU 的 `poll_list` 并触发 `NET_RX_SOFTIRQ`（软中断机制见 [Interrupt 的 softirq 章](/docs/CS/OS/Linux/Interrupt.md?id=softirq)）。注意这里**关中断调用**变体 `napi_schedule_irqoff()` 是驱动里更常用的形式——硬中断里中断本来就关着，省一次开关开销。

## Execution: net_rx_action and __napi_poll

软中断被调度后执行 `net_rx_action()`（`net/core/dev.c`）：

```c
static __latent_entropy void net_rx_action(void)
{
	struct softnet_data *sd = this_cpu_ptr(&softnet_data);
	unsigned long time_limit = jiffies +
		usecs_to_jiffies(READ_ONCE(net_hotdata.netdev_budget_usecs));
	struct bpf_net_context __bpf_net_ctx, *bpf_net_ctx;
	int budget = READ_ONCE(net_hotdata.netdev_budget);
	LIST_HEAD(list);
	LIST_HEAD(repoll);

	bpf_net_ctx = bpf_net_ctx_set(&__bpf_net_ctx);
start:
	sd->in_net_rx_action = true;
	local_irq_disable();
	list_splice_init(&sd->poll_list, &list);
	local_irq_enable();

	for (;;) {
		struct napi_struct *n;

		skb_defer_free_flush(sd);

		if (list_empty(&list)) {
			if (list_empty(&repoll)) {
				sd->in_net_rx_action = false;
				barrier();
				/* We need to check if ____napi_schedule()
				 * had refilled poll_list while
				 * sd->in_net_rx_action was true.
				 */
				if (!list_empty(&sd->poll_list))
					goto start;
				if (!sd_has_rps_ipi_waiting(sd))
					goto end;
			}
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
	else
		sd->in_net_rx_action = false;

	net_rps_action_and_irq_enable(sd);
end:
	bpf_net_ctx_clear(bpf_net_ctx);
}
```

几个必须看懂的设计：

- **双限额**。既有包数上限 `netdev_budget`（每次软中断总共最多收多少包），也有时间上限 `netdev_budget_usecs`。任一耗尽就 `time_squeeze++` 并退出——**软中断不能无限跑**，否则用户进程被饿死。这正是避免 livelock 的另一半保障。
- **本地快照 + 尾部合并**。开头 `list_splice_init(&sd->poll_list, &list)` 把待轮询链表整个取到本地，这样轮询期间新来的 NAPI 可以直接挂到 `sd->poll_list` 而不干扰本轮；结束时再把没干完的 `repoll` 和新到的合并回去。
- **没干完就再触发一次软中断**（`__raise_softirq_irqoff`），而不是在本轮里硬撑。这给了调度器一次介入机会，也保证其他 NAPI 实例（其他网卡/队列）能轮到。
- **`goto start` 那段竞态处理**：清 `in_net_rx_action` 后要再查一次 `poll_list`，因为期间可能有新 NAPI 被挂上——那时软中断已不会再被触发（只有 `in_net_rx_action` 为假时调度方才会 raise），需要自己回头再跑一轮。

真正的单次轮询在 `__napi_poll()`：

```c
static int __napi_poll(struct napi_struct *n, bool *repoll)
{
	int work, weight;

	weight = n->weight;

	/* This NAPI_STATE_SCHED test is for avoiding a race
	 * with netpoll's poll_napi().  Only the entity which
	 * obtains the lock and sees NAPI_STATE_SCHED set will
	 * actually make the ->poll() call.  Therefore we avoid
	 * accidentally calling ->poll() when NAPI is not scheduled.
	 */
	work = 0;
	if (napi_is_scheduled(n)) {
		work = n->poll(n, weight);
		trace_napi_poll(n, work, weight);

		xdp_do_check_flushed(n);
	}

	if (unlikely(work > weight))
		netdev_err_once(n->dev, "NAPI poll function %pS returned %d, exceeding its budget of %d.\n",
				n->poll, work, weight);

	if (likely(work < weight))
		return work;

	/* Drivers must not modify the NAPI state if they
	 * consume the entire weight.  In such cases this code
	 * still "owns" the NAPI instance and therefore can
	 * move the instance around on the list at-will.
	 */
	if (unlikely(napi_disable_pending(n))) {
		napi_complete(n);
		return work;
	}

	/* The NAPI context has more processing work, but busy-polling
	 * is preferred. Exit early.
	 */
	if (napi_prefer_busy_poll(n)) {
		if (napi_complete_done(n, work)) {
			/* If timeout is not set, we need to make sure
			 * that the NAPI is re-scheduled.
			 */
			napi_schedule(n);
		}
		return work;
	}

	if (n->gro_bitmask) {
		/* flush too old packets
		 * If HZ < 1000, flush all packets.
		 */
		napi_gro_flush(n, HZ >= 1000);
	}

	gro_normal_list(n);

	/* Some drivers may have called napi_schedule
	 * prior to exhausting their budget.
	 */
	if (unlikely(!list_empty(&n->poll_list))) {
		pr_warn_once("%s: Budget exhausted after napi rescheduled\n",
			     n->dev ? n->dev->name : "backlog");
		return work;
	}

	*repoll = true;

	return work;
}
```

poll 返回值决定三条去路，这是驱动必须遵守的契约：

| 返回值 | 含义 | 后续 |
|---|---|---|
| `work < weight` | 队列收干净了 | 驱动自己应已调用 `napi_complete_done()` 重开中断；NAPI 不再排队 |
| `work == weight` | 用光额度，可能还有包 | 设 `*repoll`，NAPI 被移到本轮链表尾部，下轮再来（或被重新 raise 软中断） |
| `work > weight` | **驱动 bug** | 内核打 `netdev_err_once` 警告 |

注意注释里的约束：**用光 weight 时驱动不许改 NAPI 状态**——因为此时所有权仍归 `net_rx_action`，它要把实例在链表上挪动。这条常被写驱动的人忽略。

## Wrap-up: napi_complete_done and Interrupt Delay Re-enable

收干净后，驱动调用 `napi_complete_done()` 宣布"我这轮干完了，可以重新开中断了"。现代版本（6.x）里它做的事远不止清状态位：

```c
bool napi_complete_done(struct napi_struct *n, int work_done)
{
	unsigned long flags, val, new, timeout = 0;
	bool ret = true;

	/*
	 * 1) Don't let napi dequeue from the cpu poll list
	 *    just in case its running on a different cpu.
	 * 2) If we are busy polling, do nothing here, we have
	 *    the guarantee we will be called later.
	 */
	if (unlikely(n->state & (NAPIF_STATE_NPSVC |
				 NAPIF_STATE_IN_BUSY_POLL)))
		return false;

	if (work_done) {
		if (n->gro_bitmask)
			timeout = READ_ONCE(n->dev->gro_flush_timeout);
		n->defer_hard_irqs_count = READ_ONCE(n->dev->napi_defer_hard_irqs);
	}
	if (n->defer_hard_irqs_count > 0) {
		n->defer_hard_irqs_count--;
		timeout = READ_ONCE(n->dev->gro_flush_timeout);
		if (timeout)
			ret = false;
	}
	if (n->gro_bitmask) {
		/* When the NAPI instance uses a timeout and keeps postponing
		 * it, we need to bound somehow the time packets are kept in
		 * the GRO layer
		 */
		napi_gro_flush(n, !!timeout);
	}

	gro_normal_list(n);

	if (unlikely(!list_empty(&n->poll_list))) {
		/* If n->poll_list is not empty, we need to mask irqs */
		local_irq_save(flags);
		list_del_init(&n->poll_list);
		local_irq_restore(flags);
	}
	WRITE_ONCE(n->list_owner, -1);

	val = READ_ONCE(n->state);
	do {
		WARN_ON_ONCE(!(val & NAPIF_STATE_SCHED));

		new = val & ~(NAPIF_STATE_MISSED | NAPIF_STATE_SCHED |
			      NAPIF_STATE_SCHED_THREADED |
			      NAPIF_STATE_PREFER_BUSY_POLL);

		/* If STATE_MISSED was set, leave STATE_SCHED set,
		 * because we will call napi->poll() one more time.
		 * This C code was suggested by Alexander Duyck to help gcc.
		 */
		new |= (val & NAPIF_STATE_MISSED) / NAPIF_STATE_MISSED *
						    NAPIF_STATE_SCHED;
	} while (!try_cmpxchg(&n->state, &val, new));

	if (unlikely(val & NAPIF_STATE_MISSED)) {
		__napi_schedule(n);
		return false;
	}

	if (timeout)
		hrtimer_start(&n->timer, ns_to_ktime(timeout),
			      HRTIMER_MODE_REL_PINNED);
	return ret;
}
```

拆开看：

- **返回值语义**：返回 `true` 表示"中断可以重新打开了"，驱动据此写寄存器开中断。返回 `false` 表示"别开，我还会再被调度"。
- **`MISSED` 位兑现**。前面硬中断里记下的"轮询期间又来了包"在这里兑付：若 `MISSED` 被置过，则保留 `SCHED` 位并立即 `__napi_schedule(n)` 再来一轮——所以**收尾路径也是调度路径**。
- **中断延迟打开（interrupt deferral）**。这是 5.x 后期引入的重要优化，服务于两个 sysfs/sysctl 参数：
  - `gro_flush_timeout`：GRO 层允许把包多攥一会儿（攒更大的聚合），单位是纳秒；
  - `napi_defer_hard_irqs`：忙队列上"推迟多少次硬中断"。

  两者配合的效果是：忙的时候收完一批**不立即开中断**，而是起一个 `hrtimer` 兜底，继续用轮询/GRO 攒包，直到超时或队列转空。这把"每批一次中断"进一步摊薄成"每若干个批一次中断"，代价是极轻微的包延迟。
- **兜底定时器**。`napi->timer` 在 `netif_napi_add_weight()` 里就初始化好（`hrtimer_init` + `napi_watchdog`），超时回调负责把 NAPI 重新排上队：

  ```c
  static enum hrtimer_restart napi_watchdog(struct hrtimer *timer)
  {
  	struct napi_struct *napi;

  	napi = container_of(timer, struct napi_struct, timer);

  	/* Note : we use a relaxed variant of napi_schedule_prep() not setting
  	 * NAPI_STATE_MISSED, since we do not react to a device IRQ.
  	 */
  	if (!napi_disable_pending(napi) &&
  	    !test_and_set_bit(NAPI_STATE_SCHED, &napi->state)) {
  		clear_bit(NAPI_STATE_PREFER_BUSY_POLL, &napi->state);
  		__napi_schedule_irqoff(napi);
  	}
  	...
  ```

  注意这里用的是"宽松版" prep——不设 `MISSED`，因为这不是设备中断触发的。

驱动侧的配套写法（e1000e，`drivers/net/ethernet/intel/e1000e/netdev.c`）展示了正确姿势：

```c
static int e1000e_poll(struct napi_struct *napi, int budget)
{
	...
	adapter->clean_rx(adapter->rx_ring, &work_done, budget);

	if (!tx_cleaned || work_done == budget)
		return budget;

	/* Exit the polling mode, but don't re-enable interrupts if stack might
	 * poll us due to busy-polling
	 */
	if (likely(napi_complete_done(napi, work_done))) {
		if (adapter->itr_setting & 3)
			e1000_set_itr(adapter);
		if (!test_bit(__E1000_DOWN, &adapter->state)) {
			if (adapter->msix_entries)
				ew32(IMS, adapter->rx_ring->ims_val);
			else
				e1000_irq_enable(adapter);
		}
	}

	return work_done;
}
```

**只有 `napi_complete_done()` 返回真才重新开中断**——这正是 deferral 能在驱动无感的情况下生效的原因。

## GRO and NAPI Coupling

GRO 状态直接长在 `napi_struct` 里（`gro_hash[]`、`rx_list`、`rx_count`），这不是随意的：**聚合必须按 NAPI 上下文隔离**，否则不同队列（可能不同 CPU、不同流）的包会被错误合并。

聚合结果由 `enum gro_result` 表达：

```c
enum gro_result {
	GRO_MERGED,
	GRO_MERGED_FREE,
	GRO_HELD,
	GRO_NORMAL,
	GRO_CONSUMED,
};
```

`GRO_MERGED` 表示并进了已有聚合 SKB；`GRO_HELD` 表示作为新流的种子被 GRO 层攥住（还没上交）；`GRO_NORMAL` 表示这个包不参与聚合、应当正常上交。

`GRO_NORMAL` 的包不是逐个上交的，而是**攒批**：

```c
/* Queue one GRO_NORMAL SKB up for list processing. If batch size exceeded,
 * pass the whole batch up to the stack.
 */
static inline void gro_normal_one(struct napi_struct *napi, struct sk_buff *skb, int segs)
{
	list_add_tail(&skb->list, &napi->rx_list);
	napi->rx_count += segs;
	if (napi->rx_count >= READ_ONCE(net_hotdata.gro_normal_batch))
		gro_normal_list(napi);
}

static inline void gro_normal_list(struct napi_struct *napi)
{
	if (!napi->rx_count)
		return;
	netif_receive_skb_list_internal(&napi->rx_list);
	INIT_LIST_HEAD(&napi->rx_list);
	napi->rx_count = 0;
}
```

批的提交点有三处：攒够 `gro_normal_batch`、`__napi_poll()` 里额度耗尽时、以及 `napi_complete_done()` 收尾时。用链表批量上交（`netif_receive_skb_list_internal`）比逐个 `netif_receive_skb` 少了很多重复的每包开销。GRO 与 LRO 的取舍见 [network 的卸载章](/docs/CS/OS/Linux/net/network.md?id=segmentation-and-aggregation-offload-tso--gso--gro)。

## backlog: Fallback Queue and RPS

不是所有包都来自有 NAPI 的硬件队列。环回、隧道设备、以及 RPS 分发过来的包，走的是每 CPU 内嵌的 `backlog` NAPI，其 poll 是 `process_backlog()`。入队逻辑（`net/core/dev.c`）：

```c
static int enqueue_to_backlog(struct sk_buff *skb, int cpu,
			      unsigned int *qtail)
{
	...
	qlen = skb_queue_len_lockless(&sd->input_pkt_queue);
	max_backlog = READ_ONCE(net_hotdata.max_backlog);
	if (unlikely(qlen > max_backlog))
		goto cpu_backlog_drop;
	backlog_lock_irq_save(sd, &flags);
	qlen = skb_queue_len(&sd->input_pkt_queue);
	if (qlen <= max_backlog && !skb_flow_limit(skb, qlen)) {
		if (!qlen) {
			/* Schedule NAPI for backlog device. We can use
			 * non atomic operation as we own the queue lock.
			 */
			if (!__test_and_set_bit(NAPI_STATE_SCHED,
						&sd->backlog.state))
				napi_schedule_rps(sd);
		}
		__skb_queue_tail(&sd->input_pkt_queue, skb);
		...
```

三个要点：

1. **队列长度上限** `netdev_max_backlog`。超过就丢弃并计 `sd->dropped`——这是"软中断跟不上"的直接症状。
2. **`skb_flow_limit()`**：同一条流占的队列份额有上限，避免一条大象流把队列吃光、饿死其他流。
3. **空队列时才调度**。只有从空变非空才置 `SCHED` 并触发——因为非空意味着 backlog 已在链表里了，这与 `napi_schedule_prep` 的语义一致。

`process_backlog()` 的结构值得一提，它体现了双队列设计的用意：

```c
static int process_backlog(struct napi_struct *napi, int quota)
{
	struct softnet_data *sd = container_of(napi, struct softnet_data, backlog);
	bool again = true;
	int work = 0;
	...
	napi->weight = READ_ONCE(net_hotdata.dev_rx_weight);
	while (again) {
		struct sk_buff *skb;

		local_lock_nested_bh(&softnet_data.process_queue_bh_lock);
		while ((skb = __skb_dequeue(&sd->process_queue))) {
			local_unlock_nested_bh(&softnet_data.process_queue_bh_lock);
			rcu_read_lock();
			__netif_receive_skb(skb);
			rcu_read_unlock();
			if (++work >= quota) {
				rps_input_queue_head_add(sd, work);
				return work;
			}

			local_lock_nested_bh(&softnet_data.process_queue_bh_lock);
		}
		local_unlock_nested_bh(&softnet_data.process_queue_bh_lock);

		backlog_lock_irq_disable(sd);
		if (skb_queue_empty(&sd->input_pkt_queue)) {
			/*
			 * Inline a custom version of __napi_complete().
			 * only current cpu owns and manipulates this napi,
			 * and NAPI_STATE_SCHED is the only possible flag set
			 * on backlog.
			 * We can use a plain write instead of clear_bit(),
			 * and we dont need an smp_mb() memory barrier.
			 */
			napi->state &= NAPIF_STATE_THREADED;
			again = false;
		} else {
			local_lock_nested_bh(&softnet_data.process_queue_bh_lock);
			skb_queue_splice_tail_init(&sd->input_pkt_queue,
						   &sd->process_queue);
			local_unlock_nested_bh(&softnet_data.process_queue_bh_lock);
		}
		backlog_unlock_irq_enable(sd);
	}
	...
```

处理时先把 `input_pkt_queue` **整体拼到 `process_queue`**，然后只消费后者。这样生产者（别的 CPU 经 RPS 入队）只需短暂持锁往 `input_pkt_queue` 尾部追加，不必和消费者长时间互斥。另外注意那段注释：backlog 这个 NAPI **只被本 CPU 操作**，所以收尾可以退化成普通写而不需要原子操作与内存屏障——这是"共享程度决定同步强度"的典型案例。

**RPS（Receive Packet Steering）** 正是借此实现的：硬件只有少量队列、中断集中在少数 CPU 时，可以在收包早期按流的哈希把包排到**另一个 CPU 的 backlog**，再用 IPI 触发该 CPU 的 `NET_RX_SOFTIRQ`。于是协议栈处理被分散到多核。它与硬件 RSS 的对照（谁算哈希、能否避免跨 CPU 缓存抖动）见 [network 的多核扩展章](/docs/CS/OS/Linux/net/network.md?id=multi-core-scaling-rss--rps--rfs--xps)。

## Variant: Threaded NAPI and Busy Polling

**线程化 NAPI（threaded NAPI）**：设了 `NAPI_STATE_THREADED` 的实例不再在软中断里跑 poll，而是每个 NAPI 一个专属内核线程 `napi/<dev>-<id>`（见 `napi_kthread_create()`）。好处是收包路径变成**可调度、可设优先级**的普通任务——需要确定性延迟的场景（如配合 RT 应用）可以把它设成实时优先级，且不会被其他软中断阻塞。代价是每次调度多一次上下文切换。

**忙轮询（busy polling）**：低延迟场景嫌"等中断 → 软中断"的路径太长，于是让**用户进程自己直接调驱动的 poll**。`SO_BUSY_POLL` / `epoll` 的忙轮询选项让应用在阻塞等待时主动 `sk_busy_loop()`，去 `napi_hash` 里找到本 socket 关联的 NAPI（靠 `napi_id`），直接收割。此时 NAPI 处于 `NAPI_STATE_IN_BUSY_POLL` 或 `PREFER_BUSY_POLL`：

- `IN_BUSY_POLL`：进程正在持有这个 NAPI，`napi_complete_done()` 会直接返回 false 不做收尾（因为进程会继续收）；
- `PREFER_BUSY_POLL`：`__napi_poll()` 里见到就提前退出并重新排队，把机会让给忙轮询的进程。

二者都依赖 `napi_id` 与全局 `napi_hash`，因此设了 `NAPI_STATE_NO_BUSY_POLL` 的实例不进这个哈希表。

## How to Write the Driver

注册就是告诉内核"这个队列的收割函数是它"（`netif_napi_add()` 默认 weight = `NAPI_POLL_WEIGHT` = 64，需要不同额度用 `netif_napi_add_weight()`）：

```c
void netif_napi_add_weight(struct net_device *dev, struct napi_struct *napi,
			   int (*poll)(struct napi_struct *, int), int weight)
{
	if (WARN_ON(test_and_set_bit(NAPI_STATE_LISTED, &napi->state)))
		return;

	INIT_LIST_HEAD(&napi->poll_list);
	INIT_HLIST_NODE(&napi->napi_hash_node);
	hrtimer_init(&napi->timer, CLOCK_MONOTONIC, HRTIMER_MODE_REL_PINNED);
	napi->timer.function = napi_watchdog;
	...
```

典型生命周期：probe 里 `netif_napi_add()` → 开设备时 `netif_napi_enable()` → 硬中断里 `napi_schedule_irqoff()` → poll 里收割并在 `work < weight` 时 `napi_complete_done()` 后重开中断 → 关设备时 `netif_napi_disable()`（它会置 `DISABLE` 位并等待 poll 退出，因此**必须在确保不再有中断后调用**）→ 卸载时 `netif_napi_del()`。

常见错误：

| 错误 | 后果 |
|---|---|
| poll 返回超过 weight | 内核 `netdev_err_once` 警告；budget 记账错乱 |
| 用光 weight 时仍调 `napi_complete_done()` | 违反所有权约定，可能丢包（正确做法是直接 `return weight`） |
| `napi_complete_done()` 返回 false 仍开中断 | 破坏中断延迟打开/忙轮询，性能退化 |
| 在 poll 里睡眠 | poll 在软中断上下文，不允许睡眠；真要睡眠请用 [workqueue](/docs/CS/OS/Linux/workqueue.md) |
| 未设 `.owner`/未在 disable 后停止中断 | 卸载/关闭路径的 use-after-free |

## Observation and Tuning

第一手观测是 `/proc/net/softnet_stat`，**每行一个 CPU**（6.12 `net/core/net-procfs.c`，15 列十六进制）：

| 列 | 字段 | 含义 |
|---|---|---|
| 1 | `sd->processed` | 该 CPU 处理的包总数 |
| 2 | `sd->dropped` | 因 backlog 满而丢弃 |
| 3 | `sd->time_squeeze` | 因 budget/时间耗尽而提前退出的次数——**这个是关键健康指标**，持续增长说明该 CPU 收包跟不上 |
| 10 | `sd->received_rps` | 经 RPS 从别的 CPU 过来的包数 |
| 11 | `flow_limit_count` | 被流限制拦下的次数（需 `CONFIG_NET_FLOW_LIMIT`） |
| 12 | `input_qlen + process_qlen` | backlog 当前总长度 |
| 13 | seq->index | 对应 CPU 号 |
| 14 / 15 | `input_qlen` / `process_qlen` | 两个队列各自长度 |

（第 4~9 列是历史遗留字段，恒定 0。）

可调参数集中在 `net.core.*`（`net/core/sysctl_net_core.c` 注册）：

| sysctl | 作用 |
|---|---|
| `netdev_budget` | 一次 `NET_RX_SOFTIRQ` 最多收多少包 |
| `netdev_budget_usecs` | 同上，时间上限（微秒） |
| `dev_weight` / `dev_weight_rx_bias` / `dev_weight_tx_bias` | NAPI 的 weight；rx 实际值 = `dev_weight * rx_bias` |
| `netdev_max_backlog` | backlog 队列上限，超了丢包 |
| `gro_normal_batch` | GRO 上交的批大小 |

另外 `/proc/softirqs` 里的 `NET_RX` 行看各 CPU 的收包软中断次数，`/proc/interrupts` 看硬中断分布（判断是否该调 IRQ 亲和性），`ethtool -S` 看驱动自身计数（如 `rx_missed`、`rx_overruns` 指向 RingBuffer 溢出）。

## Boundaries with Other Subsystems

- **中断与下半部**：NAPI 就是 [NET_RX_SOFTIRQ](/docs/CS/OS/Linux/Interrupt.md?id=softirq) 的实体。它不选用 tasklet/workqueue 的理由很清楚——tasklet 不能跨 CPU 并行、且粒度太粗；workqueue 走的是进程上下文，调度延迟不可控且没法保证"收完这一批"。收包需要的是**在软中断上下文里可批量、可限额、可跨 CPU 并行**的执行体，这正是 NAPI 的形状。
- **发送侧**：发送走 [Qdisc](/docs/CS/OS/Linux/net/Qdisc.md) 排队与 `NET_TX_SOFTIRQ`，与 NAPI 的收包路径结构对称但目的不同——一个做流量调度与整形，一个做批量收割与背压。
- **协议栈上行**：NAPI 把包交给 `netif_receive_skb` 之后的全部事情归 [network](/docs/CS/OS/Linux/net/network.md)，终点是 [socket](/docs/CS/OS/Linux/net/socket.md) 的接收队列与进程唤醒。
- **旁路路线**：如果连"中断 + 软中断 + 协议栈"都嫌重，就走到 [DPDK](/docs/CS/OS/Linux/IO/DPDK.md) 那类用户态轮询（内核旁路）；存储方向的异步则归 [io_uring](/docs/CS/OS/Linux/IO/io_uring.md)。三者的取舍见 [I/O 链路总图](/docs/CS/OS/Linux/IO/README.md)。
- **设备模型**：NAPI 由 [网络设备驱动](/docs/CS/OS/Linux/dev/README.md) 在 probe 阶段注册，本身不是 `device`，但借助 `net_device` 参与 sysfs 与统计。

## Links

- [网络知识地图](/docs/CS/OS/Linux/net/README.md)
- [Linux 内核总览](/docs/CS/OS/Linux/Linux.md)
- [timer 时间子系统](/docs/CS/OS/Linux/timer.md)

## References

1. [Linux Networking Documentation — NAPI](https://www.kernel.org/doc/html/latest/networking/napi.html)
2. [NAPI_HOWTO.txt — Linux kernel source](https://www.kernel.org/doc/Documentation/networking/NAPI_HOWTO.txt)
3. [Mogul & Ramakrishnan, Eliminating Receive Livelock in an Interrupt-Driven Kernel](https://www.usenix.org/legacy/event/usenix2000/freenix/full_papers/salim/salim.pdf)
4. [Scaling in the Linux Networking Stack — kernel.org](https://www.kernel.org/doc/html/latest/networking/scaling.html)
