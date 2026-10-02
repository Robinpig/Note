## Introduction

拥塞控制回答"能发多少"，缓冲管理回答"发给谁之前放在哪、放多少"。后者在内核里是一套**独立的核算体系**，而且比前者更容易被误解——因为 TCP 里"字节数"和"内存量"从来不是一回事：一个 64KB 的 GSO 大包可能只占几 KB 内存，而一个 1 字节的小包要占掉一整个 skb 结构加上按 2 的幂取整的 head 缓冲区。

本篇讲三件事：

1. **全局与每 socket 的内存账怎么算**（`sysctl_tcp_mem` 三档、`sk_forward_alloc` 的批量预取、memcg 的双重核算）
2. **收发缓冲怎么自动调优**（sndbuf 扩展、DRS 接收缓冲动态缩放、`window_clamp` / `rcv_ssthresh` 的两段缓冲模型）
3. **字节数与内存量之间那个会被 TSO/GRO 反复扭曲的换算**（`scaling_ratio`，以及 v7.2.7 上它取代了旧的固定换算）

全部对照 v7.2.7 源码。窗口**选择**逻辑（cwnd 与 rwnd 怎么取小、糊涂窗口综合征）在 [Window](/docs/CS/OS/Linux/net/TCP/TCP.md?id=window) 一节，本篇只讲窗口**底下那块内存**。

一个先要说清的前提：**绝大多数缓冲调优只在用户没有显式设置时生效**。`SO_SNDBUF` / `SO_RCVBUF` 一旦被 `setsockopt` 设置，内核就置上 `SOCK_SNDBUF_LOCK` / `SOCK_RCVBUF_LOCK`，此后自动调优全线停摆。这是个很常见的踩坑点——"我调大缓冲区想提速"，结果反而锁死了内核的自适应。

## 三道闸门：从"想发一个包"到"真的能发"

发送一个 skb 之前，内存要走三次判断。入口是 `tcp_stream_alloc_skb()`（`net/ipv4/tcp.c:926`）：

```c
struct sk_buff *tcp_stream_alloc_skb(struct sock *sk, gfp_t gfp,
				     bool force_schedule)
{
	struct sk_buff *skb;

	skb = alloc_skb_fclone(MAX_TCP_HEADER, gfp);
	if (likely(skb)) {
		bool mem_scheduled;

		skb->truesize = SKB_TRUESIZE(skb_end_offset(skb));
		if (force_schedule) {
			mem_scheduled = true;
			sk_forced_mem_schedule(sk, skb->truesize);
		} else {
			mem_scheduled = sk_wmem_schedule(sk, skb->truesize);
		}
		if (likely(mem_scheduled)) {
			skb_reserve(skb, MAX_TCP_HEADER);
			skb->ip_summed = CHECKSUM_PARTIAL;
			INIT_LIST_HEAD(&skb->tcp_tsorted_anchor);
			return skb;
		}
		__kfree_skb(skb);
	} else {
		if (!sk->sk_bypass_prot_mem)
			tcp_enter_memory_pressure(sk);
		sk_stream_moderate_sndbuf(sk);
	}
	return NULL;
}
```

注意失败路径：分配失败时**先宣布内存压力，再收缩 sndbuf**，而不是直接返回错误。这是一次自我驯服——承认系统内存紧张，把这条连接的发送上限压低。

### 闸门一：sk_forward_alloc 的批量预取

```c
static inline bool sk_wmem_schedule(struct sock *sk, int size)
{
	int delta;

	if (!sk_has_account(sk))
		return true;
	delta = size - sk->sk_forward_alloc;
	return delta <= 0 || __sk_mem_schedule(sk, delta, SK_MEM_SEND);
}
```

（`include/net/sock.h:1577`）

`sk_forward_alloc` 是**已获批但尚未用掉的额度**。只有当申请量超过余额时才真正去全局账上取。取的时候是按页批量的：

```c
int __sk_mem_schedule(struct sock *sk, int size, int kind)
{
	int ret, amt = sk_mem_pages(size);

	sk_forward_alloc_add(sk, amt << PAGE_SHIFT);
	ret = __sk_mem_raise_allocated(sk, size, amt, kind);
	if (!ret)
		sk_forward_alloc_add(sk, -(amt << PAGE_SHIFT));
	return ret;
}
```

（`net/core/sock.c:3451`）

为什么要批量？因为**全局计数器是原子变量，高频连接上每次分配都去加减它会成为热点**。批量预取把"每 skb 一次原子操作"降为"每 4KB 一次"。代价是 socket 会短暂地"占着不用"，这也是为什么内存压力判断里要把 `sk_forward_alloc` 算进 socket 的占用量。

### 闸门二：__sk_mem_raise_allocated 的四道判据

这是全局内存控制的核心（`net/core/sock.c:3338` 起）：

```c
	/* Under limit. */
	if (allocated <= sk_prot_mem_limits(sk, 0)) {
		sk_leave_memory_pressure(sk);
		return 1;
	}

	/* Under pressure. */
	if (allocated > sk_prot_mem_limits(sk, 1))
		sk_enter_memory_pressure(sk);

	/* Over hard limit. */
	if (allocated > sk_prot_mem_limits(sk, 2))
		goto suppress_allocation;
```

`sk_prot_mem_limits(sk, N)` 就是 `sysctl_tcp_mem[N]`，三档分别是 **low / pressure / high**（单位是**页**）：

| 档位 | 含义 |
| --- | --- |
| `tcp_mem[0]` | 低于此值：安全区，还会主动解除压力标志 |
| `tcp_mem[1]` | 高于此值：**进入内存压力**，后续分配受限 |
| `tcp_mem[2]` | 高于此值：**硬上限**，分配被拒绝 |

三档之间不是"越线就拒"，而是渐进的。越线之后还有两层豁免：

**豁免一：最小缓冲保证**（`sock.c:3368`）

```c
	/* Guarantee minimum buffer size under pressure (either global
	 * or memcg) to make sure features described in RFC 7323 (TCP
	 * Extensions for High Performance) work properly.
	 *
	 * This rule does NOT stand when exceeds global or memcg's hard
	 * limit, or else a DoS attack can be taken place by spawning
	 * lots of sockets whose usage are under minimum buffer size.
	 */
	if (kind == SK_MEM_RECV) {
		if (atomic_read(&sk->sk_rmem_alloc) < sk_get_rmem0(sk, prot))
			return 1;

	} else { /* SK_MEM_SEND */
		int wmem0 = sk_get_wmem0(sk, prot);

		if (sk->sk_type == SOCK_STREAM) {
			if (sk->sk_wmem_queued < wmem0)
				return 1;
		} ...
	}
```

即：**只要这条连接的用量还没到 `tcp_wmem[0]` / `tcp_rmem[0]`（最小值），即使全局处于压力也放行**。理由是保证高性能扩展（RFC 7323，窗口缩放等）还能工作。注释特意说明这条豁免**在超过硬上限时不生效**——否则开一堆不到最小值的 socket 就能把系统内存吃干。

**豁免二：低于平均值的 socket 优先**（`sock.c:3391`）

```c
	if (sk_has_memory_pressure(sk)) {
		u64 alloc;

		if (!sk_under_global_memory_pressure(sk))
			return 1;

		/* Try to be fair among all the sockets under global
		 * pressure by allowing the ones that below average
		 * usage to raise.
		 */
		alloc = sk_sockets_allocated_read_positive(sk);
		if (sk_prot_mem_limits(sk, 2) > alloc *
		    sk_mem_pages(sk->sk_wmem_queued +
				 atomic_read(&sk->sk_rmem_alloc) +
				 sk->sk_forward_alloc))
			return 1;
	}
```

判据是 `tcp_mem[2] > socket 数 × 本 socket 占用页数`——也就是"**如果每个 socket 都像我这样用，总共会不会超硬上限**"。不会就放行。这是一个很漂亮的公平性近似：不用维护全局排序，用一个乘法就把"低于平均占用"的 socket 挑出来。注意这里的 `sk_forward_alloc` 被算进占用，防止靠囤积额度来绕过。

### 闸门三：memcg 的第二层账

```c
	if (mem_cgroup_sk_enabled(sk)) {
		memcg_enabled = true;
		charged = mem_cgroup_sk_charge(sk, amt, gfp_memcg_charge());
		if (!charged)
			goto suppress_allocation;
	}
```

TCP 内存同时受**全局计数器**和 **memcg 限额**两重约束，任一超限都拒绝。这是容器场景里容易被忽略的一点：`tcp_mem` 没超限不代表能分配，cgroup 的 memory limit 也在管。释放侧对应 `mem_cgroup_sk_uncharge()`。

### 被拒之后：对 TCP 流的特殊处理

```c
suppress_allocation:

	if (kind == SK_MEM_SEND && sk->sk_type == SOCK_STREAM) {
		sk_stream_moderate_sndbuf(sk);

		/* Fail only if socket is _under_ its sndbuf.
		 * In this case we cannot block, so that we have to fail.
		 */
		if (sk->sk_wmem_queued + size >= sk->sk_sndbuf) {
			/* Force charge with __GFP_NOFAIL */
			if (memcg_enabled && !charged)
				mem_cgroup_sk_charge(sk, amt,
						     gfp_memcg_charge() | __GFP_NOFAIL);
			return 1;
		}
	}
```

SOCK_STREAM 有个特殊规则：**如果 socket 已经在自己的 sndbuf 上限附近，就强制放行**。注释解释了理由——这种情况下内核不能阻塞等待（TCP 发送路径不能睡眠），只能强制记账放行。memcg 那边用 `__GFP_NOFAIL` 硬充。

## 全局：sysctl_tcp_mem 三档怎么来的

`sysctl_tcp_mem` 是**开机自动算的**（`tcp_init_mem()`），不是固定值。它按系统总内存的页数量级分档，所以在一台 4GB 的机器和一台 256GB 的机器上完全不同。查看与调整：

```bash
cat /proc/sys/net/ipv4/tcp_mem        # 单位：页
# 典型输出（机器相关）：187107 249478 374214
```

压力状态的进入与退出（`net/ipv4/tcp.c:325`）：

```c
void tcp_enter_memory_pressure(struct sock *sk)
{
	unsigned long val;

	if (READ_ONCE(tcp_memory_pressure))
		return;
	val = jiffies;

	if (!val)
		val--;
	if (!cmpxchg(&tcp_memory_pressure, 0, val))
		NET_INC_STATS(sock_net(sk), LINUX_MIB_TCPMEMORYPRESSURES);
}
```

一个巧妙之处：`tcp_memory_pressure` 不是 bool，而是**进入压力时的 jiffies 时间戳**。`cmpxchg(0 → val)` 保证只记录第一次，退出时（`tcp_leave_memory_pressure`）用它算出压力持续了多久并累加到 `TCPMEMORYPRESSURESCHRONO` 计数器。于是"系统经历过多少次内存压力"和"累计压力时长"两个指标都从同一个变量里出来了。`val--` 那行是处理 jiffies 恰好为 0 的边界情况（0 被用作"无压力"哨兵）。

## 每 socket：wmem / rmem 三元组

### 默认值的由来

```c
	/* Set per-socket limits to no more than 1/128 the pressure threshold */
	limit = nr_free_buffer_pages() << (PAGE_SHIFT - 7);
	max_wshare = min(4UL*1024*1024, limit);
	max_rshare = min(32UL*1024*1024, limit);

	init_net.ipv4.sysctl_tcp_wmem[0] = PAGE_SIZE;
	init_net.ipv4.sysctl_tcp_wmem[1] = 16*1024;
	init_net.ipv4.sysctl_tcp_wmem[2] = max(64*1024, max_wshare);

	init_net.ipv4.sysctl_tcp_rmem[0] = PAGE_SIZE;
	init_net.ipv4.sysctl_tcp_rmem[1] = 131072;
	init_net.ipv4.sysctl_tcp_rmem[2] = max(131072, max_rshare);
```

（`net/ipv4/tcp.c:5358`）

三元组语义是 **[最小值, 默认值, 最大值]**。注意接收侧默认值（128KB）远大于发送侧（16KB）——发送缓冲要装的是"已经发出去但还没被确认的数据"，量级由 cwnd 决定；接收缓冲要装的是"到达但应用还没读走的数据"，受应用调度延迟影响更大，所以给得宽。

`1/128` 这个比例（`PAGE_SHIFT - 7`）是关键约束：**单个 socket 的上限不超过压力阈值的 1/128**，防止少数连接吃光全局配额。

### 发送缓冲扩展：tcp_sndbuf_expand

连接进入 ESTABLISHED 时，`tcp_init_buffer_space()` 会调 `tcp_sndbuf_expand()`（`net/ipv4/tcp_input.c:605`）：

```c
	/* Worst case is non GSO/TSO : each frame consumes one skb
	 * and skb->head is kmalloced using power of two area of memory
	 */
	per_mss = max_t(u32, tp->rx_opt.mss_clamp, tp->mss_cache) +
		  MAX_TCP_HEADER +
		  SKB_DATA_ALIGN(sizeof(struct skb_shared_info));

	per_mss = roundup_pow_of_two(per_mss) +
		  SKB_DATA_ALIGN(sizeof(struct sk_buff));

	nr_segs = max_t(u32, TCP_INIT_CWND, tcp_snd_cwnd(tp));
	nr_segs = max_t(u32, nr_segs, tp->reordering + 1);

	/* Fast Recovery (RFC 5681 3.2) :
	 * Cubic needs 1.7 factor, rounded to 2 to include
	 * extra cushion (application might react slowly to EPOLLOUT)
	 */
	sndmem = ca_ops->sndbuf_expand ? ca_ops->sndbuf_expand(sk) : 2;
	sndmem *= nr_segs * per_mss;

	if (sk->sk_sndbuf < sndmem)
		WRITE_ONCE(sk->sk_sndbuf,
			   min(sndmem, READ_ONCE(sock_net(sk)->ipv4.sysctl_tcp_wmem[2])));
```

三点值得注意：

1. **按"最坏情况"估算**：注释说明假设不做 GSO/TSO，每个帧一个 skb，且 `skb->head` 按 2 的幂取整分配——所以 `roundup_pow_of_two()`。这个估算是保守的，实际有 GSO 时用不了这么多。
2. **默认 2 倍余量来自"快速恢复需要"**：注释点名 CUBIC 需要 1.7 倍，向上取整到 2 还额外留了"应用对 EPOLLOUT 反应慢"的缓冲。
3. **拥塞算法可以覆盖这个倍数**——`ca_ops->sndbuf_expand`。BBR 返回 **3**（`tcp_bbr.c:1082`），理由是"BBR 即使在恢复期也可能慢启动"。这是拥塞算法影响内存占用的一个直接接口。

### 内存压力下收缩：sk_stream_moderate_sndbuf

```c
static inline void sk_stream_moderate_sndbuf(struct sock *sk)
{
	u32 val;

	if (sk->sk_userlocks & SOCK_SNDBUF_LOCK)
		return;

	val = min(sk->sk_sndbuf, sk->sk_wmem_queued >> 1);
	val = max_t(u32, val, sk_unused_reserved_mem(sk));

	WRITE_ONCE(sk->sk_sndbuf, max_t(u32, val, SOCK_MIN_SNDBUF));
}
```

（`include/net/sock.h:2630`）

逻辑是"**把 sndbuf 压到当前已排队量的一半**"，但不低于 `SOCK_MIN_SNDBUF`。开头那个 `SOCK_SNDBUF_LOCK` 检查就是前面说的：**用户显式设过 `SO_SNDBUF` 的连接不参与收缩**。

### SOCK_SNDBUF_LOCK 的陷阱

再强调一次这条链：`setsockopt(SO_SNDBUF)` → `sk_userlocks |= SOCK_SNDBUF_LOCK` → `tcp_sndbuf_expand()` 被跳过（`tcp_init_buffer_space()` 里 `if (!(sk->sk_userlocks & SOCK_SNDBUF_LOCK))`）、`sk_stream_moderate_sndbuf()` 直接返回。

所以**在高 BDP 链路上手动设 `SO_SNDBUF` 往往会降低性能**，除非你算出来的值确实比内核自动调优的上限更合适。同理 `SO_RCVBUF` 会锁死接收侧 DRS。

## 接收缓冲自动调优：DRS

发送缓冲的大小主要由 cwnd 决定（相对好算），接收缓冲则难得多——它要同时容纳"网络上正在飞的数据"和"应用调度延迟期间堆积的数据"。内核的做法是**持续测量应用实际读取速率，据此反推需要多大的缓冲**。

### 两段缓冲模型

`tcp_input.c:637` 的注释讲得很清楚：

> All `tcp_full_space()` is split to two parts: "network" buffer, allocated forward and advertised in receiver window (`tp->rcv_wnd`) and "application buffer", required to isolate scheduling/application latencies from network.

即接收缓冲被切成两块：

- **网络缓冲**：提前分配、通过 `rcv_wnd` 通告给对端的部分
- **应用缓冲**：留给应用调度延迟的余量

`window_clamp` 是通告窗口的上限。`tcp_full_space() - window_clamp` 就是留给应用的那一块。注释还给了权衡说明：**window_clamp 越小，对网络越平滑（队列更短），但吞吐越低、对丢包越敏感**。

`rcv_ssthresh` 是"慢启动阶段"用的更严格的窗口上限，服务于两个目标（注释里的 check#1 / check#2）：强制发送端能做首部预测（header prediction），以及防止因窗口误判导致接收队列被裁剪。

### 测量：tcp_rcv_space_adjust

每次数据被复制到用户空间后调用（`tcp_input.c:960`）：

```c
	time = tcp_stamp_us_delta(tp->tcp_mstamp, tp->rcvq_space.time);
	if (time < (tp->rcv_rtt_est.rtt_us >> 3))
		return;

	/* Number of bytes copied to user in last RTT */
	copied = tp->copied_seq - tp->rcvq_space.seq;
	/* Number of bytes in receive queue. */
	inq = tp->rcv_nxt - tp->copied_seq;
	copied -= inq;
	if (copied <= tp->rcvq_space.space)
		goto new_measure;

	tcp_rcvbuf_grow(sk, copied);
```

即：**每过一个 RTT，量一次"这段时间内应用实际读走了多少字节"**。注意 `copied -= inq`——要减掉还留在接收队列里的，得到的才是真正被应用消费掉的净量。只有当这个量比上次记录的更大时才去增长缓冲。

注释里有个值得记的细节：这里**刻意不刷新 `tp->tcp_mstamp`**，理由是某些平台上 `ktime_get()` 很贵，用上次缓存的值对 DRS 来说精度够了。

### 增长：tcp_rcvbuf_grow 的两个分支

```c
	/* DRS is always one RTT late. */
	rcvwin = newval << 1;

	rtt_us = tp->rcv_rtt_est.rtt_us >> 3;
	rtt_threshold = READ_ONCE(net->ipv4.sysctl_tcp_rcvbuf_low_rtt);
	if (rtt_us < rtt_threshold) {
		/* For small RTT, we set @grow to rcvwin * rtt_us/rtt_threshold.
		 * It might take few additional ms to reach 'line rate',
		 * but will avoid sk_rcvbuf inflation and poor cache use.
		 */
		grow = div_u64((u64)rcvwin * rtt_us, rtt_threshold);
	} else {
		/* slow start: allow the sender to double its rate. */
		grow = div_u64(((u64)rcvwin << 1) * (newval - oldval), oldval);
	}
	rcvwin += grow;

	if (!RB_EMPTY_ROOT(&tp->out_of_order_queue))
		rcvwin += TCP_SKB_CB(tp->ooo_last_skb)->end_seq - tp->rcv_nxt;

	cap = READ_ONCE(net->ipv4.sysctl_tcp_rmem[2]);

	rcvbuf = min_t(u32, tcp_space_from_win(sk, rcvwin), cap);
	if (rcvbuf > sk->sk_rcvbuf) {
		WRITE_ONCE(sk->sk_rcvbuf, rcvbuf);
		/* Make the window clamp follow along.  */
		WRITE_ONCE(tp->window_clamp,
			   tcp_win_from_space(sk, rcvbuf));
	}
```

（`tcp_input.c:911`）

基础量是 `newval << 1`（**DRS 永远晚一个 RTT**，所以要按两倍预取）。附加的 `grow` 分两种情况：

- **RTT 小（低于 `tcp_rcvbuf_low_rtt`）**：`grow = rcvwin × rtt_us / rtt_threshold`。注释解释了动机——小 RTT 下如果按标准慢启动增长，`sk_rcvbuf` 会被撑得过大，导致**缓存局部性变差**。这里宁可多花几毫秒才达到线速，也不让缓冲膨胀。这是个很实在的性能取舍。
- **RTT 大**：走慢启动，`grow` 与增长率 `(newval - oldval)/oldval` 成正比，让发送方速率能翻倍。

另外**有乱序队列时要把乱序数据量加进去**（`rcvwin += ooo_last_skb->end_seq - rcv_nxt`）——乱序数据占着缓冲但不推进 `copied_seq`，不补偿的话会低估需求。

最后增长会同步更新 `window_clamp`，保证通告窗口跟上。上限是 `tcp_rmem[2]`。

## 一个容易算错的换算：字节数 ≠ 内存量

### truesize 与 scaling_ratio

skb 的 `truesize` 是它实际占用的内存（含 skb 结构、按 2 的幂取整的 head、shared_info 等），而 `skb->len` 是它承载的数据字节数。两者的比值**随 TSO/GRO 剧烈变化**：

- 一个 1460 字节的普通包：truesize 可能 ~2300 字节（比值约 0.63）
- 一个 64KB 的 GSO 聚合包：truesize 可能 ~70KB（比值接近 0.93）

窗口通告的是字节数，内存核算用的是 truesize，中间必须有个换算。

**v7.2.7 上这个换算是 per-socket 动态测量的**，不是固定公式：

```c
/* Assume a 50% default for skb->len/skb->truesize ratio.
 * This may be adjusted later in tcp_measure_rcv_mss().
 */
#define TCP_DEFAULT_SCALING_RATIO (1 << (TCP_RMEM_TO_WIN_SCALE - 1))

static inline int tcp_win_from_space(const struct sock *sk, int space)
{
	return __tcp_win_from_space(tcp_sk(sk)->scaling_ratio, space);
}
```

测量点在 `tcp_measure_rcv_mss()`（`tcp_input.c:227`）：

```c
		if (unlikely(len != icsk->icsk_ack.rcv_mss)) {
			u64 val = (u64)skb->len << TCP_RMEM_TO_WIN_SCALE;
			u8 old_ratio = tcp_sk(sk)->scaling_ratio;

			do_div(val, skb->truesize);
			tcp_sk(sk)->scaling_ratio = val ? val : 1;

			if (old_ratio != tcp_sk(sk)->scaling_ratio) {
				struct tcp_sock *tp = tcp_sk(sk);

				val = tcp_win_from_space(sk, sk->sk_rcvbuf);
				WRITE_ONCE(tp->window_clamp, val);

				if (tp->window_clamp < tp->rcvq_space.space)
					tp->rcvq_space.space = tp->window_clamp;
			}
		}
```

即：**每次观测到新的 MSS 时，用 `len / truesize` 更新 `scaling_ratio`**，比值变化后立刻重算 `window_clamp`。初始值按 50% 假设（`TCP_DEFAULT_SCALING_RATIO`）。

⚠️ **版本差异**：旧内核（以及大量网上资料、调优文档）用的是 `sysctl_tcp_adv_win_scale` 的固定移位换算（`space - (space >> tcp_adv_win_scale)`）。v7.2.7 上 `sysctl_tcp_adv_win_scale` 这个 sysctl 仍然存在（默认 1），但 **`tcp_win_from_space()` 已经不看它了**——实际生效的是 per-socket 的 `scaling_ratio`。照旧文档调这个 sysctl 不会有效果。

### 三个换算函数

```c
static inline int tcp_space(const struct sock *sk)
{
	return tcp_win_from_space(sk, READ_ONCE(sk->sk_rcvbuf) -
				  READ_ONCE(sk->sk_backlog.len) -
				  atomic_read(&sk->sk_rmem_alloc));
}

static inline int tcp_full_space(const struct sock *sk)
{
	return tcp_win_from_space(sk, READ_ONCE(sk->sk_rcvbuf));
}
```

（`include/net/tcp.h:1772`）

`tcp_space()` 是当前可通告的窗口（扣掉 backlog 和已用），`tcp_full_space()` 是缓冲全空时的理论上限。反向换算 `tcp_space_from_win()` 用于从"想要的窗口"反推"需要多大的 rcvbuf"（DRS 里就用它）。

## TSO / GSO 对缓冲的影响

发送侧一次能聚合多少，由 `tcp_xmit_size_goal()` 决定（`net/ipv4/tcp.c:957`）：

```c
	/* Note : tcp_tso_autosize() will eventually split this later */
	new_size_goal = tcp_bound_to_half_wnd(tp, sk->sk_gso_max_size);

	/* We try hard to avoid divides here */
	size_goal = tp->gso_segs * mss_now;
	if (unlikely(new_size_goal < size_goal ||
		     new_size_goal >= size_goal + mss_now)) {
		tp->gso_segs = min_t(u16, new_size_goal / mss_now,
				     sk->sk_gso_max_segs);
		size_goal = tp->gso_segs * mss_now;
	}

	return max(size_goal, mss_now);
```

三个约束：`sk_gso_max_size`（驱动给的字节上限，还要被 `tcp_bound_to_half_wnd` 限制到半个拥塞窗口以内）、`sk_gso_max_segs`（驱动给的段数上限）、以及 MSS。`tp->gso_segs` 缓存了算出来的段数，只有目标变化超出一个 MSS 才重算——注释说"我们尽力避免除法"。

**为什么 TSO 会让缓冲需求变小**：聚合后一个 skb 承载多个段，skb 结构与 head 的开销被摊薄，同样的字节数占用更少的 truesize。这正是 `scaling_ratio` 必须动态测量的原因——GRO 开启的接收侧比值会明显更高。

拥塞算法也能干预这个：`tcp_congestion_ops.min_tso_segs` 回调可以覆盖 `sysctl_tcp_min_tso_segs`。BBR 的实现是低速时强制段数为 1（`tcp_bbr.c:300`），避免低带宽下攒大包造成突发。

## TCP 选项的空间成本

选项不是免费的，它们直接从 MSS 里扣：

```c
#define MAX_TCP_OPTION_SPACE 40
#define MAX_TCP_HEADER	L1_CACHE_ALIGN(128 + MAX_HEADER)
#define TCP_MIN_GSO_SIZE	(TCP_MIN_SND_MSS - MAX_TCP_OPTION_SPACE)
```

（`include/net/tcp.h:70`）

`MAX_TCP_OPTION_SPACE = 40` 是 TCP 首部选项区的总上限（首部最长 60 字节，固定部分 20 字节）。内核给 skb 预留 `MAX_TCP_HEADER`（按 L1 缓存行对齐）就是为了容纳最坏情况下的首部。

常见选项的开销（对齐后）：

| 选项 | 字节 | 说明 |
| --- | --- | --- |
| MSS | 4 | 仅 SYN 阶段 |
| 窗口缩放 wscale | 4（含 NOP 对齐） | 仅 SYN 阶段，但**决定了后续窗口能否超过 64KB** |
| SACK Permitted | 2 | 仅 SYN 阶段 |
| Timestamp | 12（`TCPOLEN_TSTAMP_ALIGNED`） | **每个数据包都带** |
| SACK block | 8 每块，基础 4（`TCPOLEN_SACK_BASE_ALIGNED`） | 丢包时由接收端回带 |

**Timestamp 是唯一每个包都付的固定成本**（12 字节）。它同时服务于 RTT 测量（见 [Retransmission](/docs/CS/OS/Linux/net/TCP/Retransmission.md)）和 PAWS（防止序号回绕）。在 1460 字节的 MSS 上，12 字节约占 0.8%——看着不多，但在小包密集的场景（如 RPC）里比例会显著上升。

`tcp_measure_rcv_mss()` 末尾那句注释 "Account for possibly-removed options" 就是在处理这个：内核可能在接收路径上剥掉选项，此时要相应调整 `rcv_mss`。

## 观测

```bash
# 全局三档（单位：页）与当前用量
cat /proc/sys/net/ipv4/tcp_mem
grep Tcp /proc/net/sockstat{,6}      # 含 mem 字段（页数）

# 压力发生过多少次 / 累计时长
nstat -a | grep -i memorypressure

# 每 socket 三元组
cat /proc/sys/net/ipv4/tcp_rmem
cat /proc/sys/net/ipv4/tcp_wmem

# 单条连接：rcvbuf / sndbuf / 窗口 / 选项
ss -tm
```

`ss -tm` 会给出 `skmem:(r<rmem_alloc>,rb<rcvbuf>,t<wmem_alloc>,tb<sndbuf>,...)`，其中 `rb` / `tb` 就是本篇讲的自动调优结果。对照 `tcp_rmem[2]` 看 `rb` 是否已经顶到上限，是判断"接收缓冲是不是瓶颈"的直接方法。

内存压力相关的两个计数器来自前面那个 jiffies 技巧：`TcpMemoryPressures`（进入次数）与 `TcpMemoryPressuresChrono`（累计毫秒，由 `tcp_leave_memory_pressure()` 累加）。

## 与其他笔记的关系

- **[Retransmission](/docs/CS/OS/Linux/net/TCP/Retransmission.md)**：timestamp 选项（12 字节）是 RTT 测量的载体，SACK 选项（8 字节/块）是丢包反馈的载体——两者都是本篇讲的选项成本的主要来源。
- **[BBR](/docs/CS/OS/Linux/net/TCP/BBR.md)**：BBR 通过 `sndbuf_expand = 3` 和 `min_tso_segs` 两个回调直接参与缓冲管理，比 CUBIC 更激进。
- **[Congestion](/docs/CS/OS/Linux/net/TCP/Congestion.md)**：拥塞窗口 cwnd 决定的是"能发多少字节"，本篇的 sndbuf 决定"能排队多少内存"，`tcp_sndbuf_expand()` 把两者连起来（`nr_segs = max(TCP_INIT_CWND, tcp_snd_cwnd(tp))`）。
- [Window](/docs/CS/OS/Linux/net/TCP/TCP.md?id=window)：通告窗口的选择逻辑，本篇讲的 `window_clamp` / `rcv_ssthresh` 是它的输入。
- [Qdisc](/docs/CS/OS/Linux/net/Qdisc.md)：qdisc 队列是另一个缓冲层级，与 socket 发送缓冲是串联的两段。

## Links

- [socket](/docs/CS/OS/Linux/net/socket.md)
- [网络知识地图](/docs/CS/OS/Linux/net/README.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

- [RFC 7323: TCP Extensions for High Performance](https://www.rfc-editor.org/rfc/rfc7323.html)
- [RFC 1323: TCP Extensions for High Performance (obsoleted by 7323)](https://www.rfc-editor.org/rfc/rfc1323.html)
- [RFC 1122: Requirements for Internet Hosts](https://www.rfc-editor.org/rfc/rfc1122.html)
- [RFC 8511: TCP Alternative Backoff with ECN (ABE)](https://www.rfc-editor.org/rfc/rfc8511.html)
- [Linux tcp(7) man page - Socket Options](https://man7.org/linux/man-pages/man7/tcp.7.html)
- [Linux socket(7) man page - SO_SNDBUF / SO_RCVBUF](https://man7.org/linux/man-pages/man7/socket.7.html)
