## Introduction

BBR（Bottleneck Bandwidth and RTT）是 Linux 里唯一一个**不把丢包当作拥塞信号**的主流拥塞控制算法。Reno / CUBIC 那一脉的逻辑是"丢包 = 管道满了 = 该退让"，BBR 认为这个等式在 2016 年之后的网络上已经不成立了：浅缓冲、无线链路、流量整形器（policer）都会产生**与拥塞无关的丢包**，而深缓冲（bufferbloat）又让"队列真的满了"这件事在丢包发生前已经延迟了几百毫秒。基于丢包的算法只能在这两头之间二选一：要么在浅缓冲链路上白白退让，要么在深缓冲链路上先把延迟灌满再等到丢包。

BBR 的解法是换一个观测量：**不去猜拥塞，而是直接测量这条路径的两个物理属性**——瓶颈带宽 BtlBw 和往返传播延迟 RTprop——然后把发送速率和 inflight 直接设到这两个量算出来的工作点上。丢包不再是指挥棒，只是"模型可能需要修正"的一个提示。

本篇按 `net/ipv4/tcp_bbr.c`（v7.2.7，1200 行）的源码展开：先讲它测什么、怎么测（定点数单位、两个窗口滤波器、packet-timed round 这个反直觉的时间基准），再讲四态状态机与增益循环，最后讲几个容易被忽略但决定实际行为的子机制（EDT 感知的 inflight、ACK 聚合补偿、policer 检测、丢包时的 packet conservation）。

需要先说明版本事实：**主线内核里只有 BBR v1**。v7.2.7 的 `net/ipv4/` 目录下只有 `tcp_bbr.c` 一个 BBR 实现，没有 BBRv2 / v3。Google 后来推出的 BBRv2（引入丢包与 ECN 作为显式信号）、BBRv3 一直没有合入主线，只存在于 Google 自己的分支里。所以下文所有内容都是 **BBR v1** 的行为，包括它那些广为诟病的公平性问题。

内核头注释里那句话值得记住：**BBR 需要 fq qdisc 配合**。准确说法是"没有 fq 也能跑，但会退化"——`bbr_init()` 里把 `sk_pacing_status` 置成 `SK_PACING_NEEDED`，如果底层 qdisc 不做 pacing，内核就退回**每 socket 一个高精度定时器**的软件 pacing，能工作但 CPU 开销高得多、精度也差。

## Modeling: What Exactly Does BBR Measure

### Two Quantities, and Why They Cannot Be Measured Simultaneously

BBR 的整个算法建立在两个测量值上：

| 量 | 含义 | 滤波器 | 窗口 |
| --- | --- | --- | --- |
| **BtlBw** | 瓶颈带宽（delivery rate 的上界） | windowed **max** | 最近 10 个 round trip |
| **RTprop** | 往返传播延迟（不含排队） | windowed **min** | 最近 10 秒 |

这两个量都必须用极值滤波器而不是平均值——BtlBw 取最大值是因为**被低估的带宽会直接限制吞吐**（你永远不会比实际带宽发得更快，所以最大观测值就是最贴近真值的下界估计）；RTprop 取最小值是因为**排队只会让 RTT 变大**，最小观测值才是"空载"的真实传播延迟。

关键性质是这两个量**在数学上无法同时测量**：要把带宽测准就得把管道灌满，而灌满必然产生排队，排队就会污染 RTT；要把 RTT 测准就得把队列排空，而排空时就没有数据可用来测带宽。BBR 的处理是把时间分片：**绝大部分时间靠 BtlBw 驱动（不断有数据在发，RTT 可能被污染），偶尔花 200ms 进入 PROBE_RTT 把队列排空、重新校准 RTprop**。这就是四个状态里 PROBE_RTT 存在的唯一理由。

有了这两个量，BDP（bandwidth-delay product）就是直接相乘：

```
BDP = BtlBw × RTprop
```

这个数就是"让管道刚好填满、且队列为零"所需的 inflight 字节数。BBR 的全部目标就是**让 inflight 稳定在 BDP 附近**——比它小则带宽浪费，比它大则产生排队延迟。对比一下 CUBIC：CUBIC 是在用丢包去"碰"这个点，碰到了就乘性减，然后三次函数爬回去，整个过程围绕最优点在振荡；BBR 是直接算出这个点在哪。

### Fixed-point Numbers: BW_SCALE and BBR_SCALE

内核里没有浮点，所有速率和增益都是定点整数。`tcp_bbr.c:75-79` 定义了两级放大：

```c
#define BW_SCALE 24
#define BW_UNIT (1 << BW_SCALE)

#define BBR_SCALE 8	/* scaling factor for fractions in BBR (e.g. gains) */
#define BBR_UNIT (1 << BBR_SCALE)
```

**BW_SCALE = 24** 用于带宽：带宽单位是 **pkt/µs，左移 24 位**。注释里解释了取值理由——1 个单位是 `1500 bytes / 1µs / 2^24 ≈ 715 bps`，于是 u32 能表示从 715bps 到 3Tbps 的范围，既不会在低速时截断（最小窗口 ≥ 4 包，下界不成问题），也不会在高速时溢出。

**BBR_SCALE = 8** 用于增益：`BBR_UNIT = 256` 就是增益 1.0。所以 `BBR_UNIT * 5 / 4 = 320` 表示 1.25，`BBR_UNIT * 3 / 4 = 192` 表示 0.75。

把带宽换算成字节/秒的函数在 `tcp_bbr.c:245`，**乘法顺序是刻意安排的**，为了避免 u64 溢出：

```c
static u64 bbr_rate_bytes_per_sec(struct sock *sk, u64 rate, int gain)
{
	unsigned int mss = tcp_sk(sk)->mss_cache;

	rate *= mss;
	rate *= gain;
	rate >>= BBR_SCALE;
	rate *= USEC_PER_SEC / 100 * (100 - bbr_pacing_margin_percent);
	return rate >> BW_SCALE;
}
```

注意 `bbr_pacing_margin_percent = 1`（`tcp_bbr.c:148`）：**平均 pacing 速率刻意比估计带宽低 1%**。这不是误差补偿，是设计的一部分——注释说得很直白，目的是"把网络往更短的队列、更低的延迟方向推"，代价是理论吞吐的 1%。

### BtlBw: Windowed Max Three-slot Algorithm

滤波器用的是 Kathleen Nichols 的 windowed min/max（`lib/win_minmax.c`），只占三个槽位、每次更新 O(1)：

```c
struct minmax {
	struct minmax_sample s[3];
};
```

算法维护"最优、次优、第三优"三个候选，并维持不变式**第 n 优的测量时间 ≥ 第 n-1 优的测量时间**。当窗口完全滑过而没有新值时，就把次优提升为最优、第三优提升为次优，新值填第三优（`minmax_subwin_update()`）。

BBR 用它取最大带宽（`tcp_bbr.c:801`）：

```c
if (!rs->is_app_limited || bw >= bbr_max_bw(sk)) {
	/* Incorporate new sample into our max bw filter. */
	minmax_running_max(&bbr->bw, bbr_bw_rtts, bbr->rtt_cnt, bw);
}
```

两个细节值得注意：

1. **窗口长度是 10，单位是 round trip 而不是时间**。`bbr_bw_rtts = CYCLE_LEN + 2 = 10`（`tcp_bbr.c:134`），传入的 `t` 是 `bbr->rtt_cnt`。也就是说窗口是"最近 10 个 packet-timed round"，不是"最近 10 个 RTT 时长"。
2. **app-limited 样本被过滤掉，除非它不低于当前模型**。如果应用没数据可发，测出来的 delivery rate 反映的是应用行为而不是网络能力，直接用会把带宽估计拖下去、导致无谓的降速。所以只有 `bw >= bbr_max_bw(sk)` 的 app-limited 样本才被采纳。

### RTprop: 10-second Window and 'Opportunistic' Sampling

min RTT 的更新在 `bbr_update_min_rtt()`（`tcp_bbr.c:942`）：

```c
filter_expired = after(tcp_jiffies32,
		       bbr->min_rtt_stamp + bbr_min_rtt_win_sec * HZ);
if (rs->rtt_us >= 0 &&
    (rs->rtt_us < bbr->min_rtt_us ||
     (filter_expired && !rs->is_ack_delayed))) {
	bbr->min_rtt_us = rs->rtt_us;
	bbr->min_rtt_stamp = tcp_jiffies32;
}
```

窗口是 **10 秒**（`bbr_min_rtt_win_sec`）。窗口过期后有个放宽条件：即使新样本不是更小的，只要**不是延迟 ACK** 也可以刷新——因为过期意味着旧的 min_rtt 可能已经不可信了。

这里有一处很漂亮的观察（注释里写明了）：**交互式应用（Web、RPC、视频分片）往往不需要主动进 PROBE_RTT**。它们在 10 秒内天然存在静默期或低速期，速率低到足以把瓶颈队列排空，这时候的 RTT 样本自然就是 RTprop，min 滤波器会自动"捡"到它。只有持续满速发送的长连接才需要付出 PROBE_RTT 的代价。

### Time Base: packet-timed round, Not Wall Clock

这是 BBR 里最反直觉、也最容易被忽略的设计。绝大多数基于时间的算法用墙钟（jiffies / µs）衡量"过了一轮"，BBR 用的是**包序驱动的 round**：

```c
	/* See if we've reached the next RTT */
	if (!before(rs->prior_delivered, bbr->next_rtt_delivered)) {
		bbr->next_rtt_delivered = tp->delivered;
		bbr->rtt_cnt++;
		bbr->round_start = 1;
		bbr->packet_conservation = 0;
	}
```

（`tcp_bbr.c:773`，`bbr_update_bw()`）

判据是"当前 ACK 对应的 `prior_delivered` 是否已经越过上一轮结束时的 `delivered` 计数"。也就是说，一个 round 的定义是**"从我标记的那一刻起发出去的包，都已经被确认了"**，而不是"过了 N 微秒"。

为什么不用墙钟？因为**延迟 ACK、TSO 聚合、调度抖动都会让"一个 RTT"在墙钟上忽长忽短**，用墙钟衡量的话，一轮里到底发了多少包是不确定的，带宽估计会被 ACK 时序的噪声污染。用包序驱动则保证"每一轮覆盖相同的一批包的确认过程"，与时序抖动解耦。

`round_start` 这个标志在 BBR 里到处都是——它是几乎所有状态推进的前提条件（`bbr_check_full_bw_reached`、`bbr_lt_bw_sampling`、`bbr_update_ack_aggregation` 都以它为门）。

## State Machine: Four modes and Two Sets of Gains

### State Diagram and Gain Table

`enum bbr_mode`（`tcp_bbr.c:82`）只有四个状态，每个状态同时决定两个增益（`bbr_update_gains()`，`tcp_bbr.c:988`）：

```c
	switch (bbr->mode) {
	case BBR_STARTUP:
		bbr->pacing_gain = bbr_high_gain;
		bbr->cwnd_gain	 = bbr_high_gain;
		break;
	case BBR_DRAIN:
		bbr->pacing_gain = bbr_drain_gain;	/* slow, to drain */
		bbr->cwnd_gain	 = bbr_high_gain;	/* keep cwnd */
		break;
	case BBR_PROBE_BW:
		bbr->pacing_gain = (bbr->lt_use_bw ?
				    BBR_UNIT :
				    bbr_pacing_gain[bbr->cycle_idx]);
		bbr->cwnd_gain	 = bbr_cwnd_gain;
		break;
	case BBR_PROBE_RTT:
		bbr->pacing_gain = BBR_UNIT;
		bbr->cwnd_gain	 = BBR_UNIT;
		break;
```

| mode | pacing_gain | cwnd_gain | 目的 |
| --- | --- | --- | --- |
| STARTUP | 2.885 | 2.885 | 指数探测，快速填满管道 |
| DRAIN | 0.347 | 2.885 | 排空 STARTUP 制造的队列 |
| PROBE_BW | 8 相循环（1.25 / 0.75 / 1.0×6） | 2.0 | 稳态：周期性探测带宽 + 让出带宽 |
| PROBE_RTT | 1.0 | 1.0 | 排空队列重测 RTprop |

`pacing_gain` 决定**发多快**（`sk_pacing_rate`），`cwnd_gain` 决定**最多允许多少 inflight**（`snd_cwnd`）。两者分开是 BBR 的核心机制：**速率由 pacing 控制，cwnd 只是一个安全上界**。

### STARTUP: Why 2/ln(2)

```c
static const int bbr_high_gain  = BBR_UNIT * 2885 / 1000 + 1;
```

数值上 `739 / 256 ≈ 2.887`，即 2/ln(2) ≈ 2.885。注释解释了取这个值的理由：它是**能让 pacing rate 平滑地每 RTT 翻一倍**的最小增益，使得 BBR 在 STARTUP 阶段每 RTT 发出的包数与"不做 pacing 的 Reno/CUBIC 慢启动"相同——也就是和现有算法保持同样的侵略性，不多也不少。

探测"管道是否满了"的判据在 `bbr_check_full_bw_reached()`（`tcp_bbr.c:874`）：

```c
	bw_thresh = (u64)bbr->full_bw * bbr_full_bw_thresh >> BBR_SCALE;
	if (bbr_max_bw(sk) >= bw_thresh) {
		bbr->full_bw = bbr_max_bw(sk);
		bbr->full_bw_cnt = 0;
		return;
	}
	++bbr->full_bw_cnt;
	bbr->full_bw_reached = bbr->full_bw_cnt >= bbr_full_bw_cnt;
```

即：**连续 3 个 round（`bbr_full_bw_cnt`）里带宽增长都没有超过 25%（`bbr_full_bw_thresh = BBR_UNIT * 5/4`）**，就认为管道已满。为什么是 3 轮，注释给了分步解释：第 1 轮接收窗口自动调优把 rwin 撑大，第 2 轮填满更大的 rwin，第 3 轮才拿到更高的 delivery rate 样本。另外也给"临时性的交叉流量或无线噪声消失"留了观察时间。

注意这个判据**只在 `round_start` 且非 app-limited 时才推进**（`tcp_bbr.c:880`），再次体现 packet-timed round 的作用。

### DRAIN: Drain with 1/2.885

```c
static const int bbr_drain_gain = BBR_UNIT * 1000 / 2885;
```

`88 / 256 ≈ 0.344`，即 1/2.885。这个值是算出来的：用 STARTUP 增益的倒数，正好可以在**一个 round 内**排掉 STARTUP 期间堆积的队列。注意 cwnd_gain 在 DRAIN 期间**保持 2.885 不变**——降的只是 pacing 速率，cwnd 不动，因为 cwnd 是上界而不是目标。

退出条件在 `bbr_check_drain()`（`tcp_bbr.c:894`）：

```c
	if (bbr->mode == BBR_DRAIN &&
	    bbr_packets_in_net_at_edt(sk, tcp_packets_in_flight(tcp_sk(sk))) <=
	    bbr_inflight(sk, bbr_max_bw(sk), BBR_UNIT))
		bbr_reset_probe_bw_mode(sk);  /* we estimate queue is drained */
```

即"网络中的包数已经降到 1.0×BDP 以下"。

### PROBE_BW: 8-phase Gain Cycle

稳态是 BBR 花时间最多的地方。增益在一个 8 元素数组里循环（`tcp_bbr.c:163`）：

```c
static const int bbr_pacing_gain[] = {
	BBR_UNIT * 5 / 4,	/* probe for more available bw */
	BBR_UNIT * 3 / 4,	/* drain queue and/or yield bw to other flows */
	BBR_UNIT, BBR_UNIT, BBR_UNIT,	/* cruise at 1.0*bw to utilize pipe, */
	BBR_UNIT, BBR_UNIT, BBR_UNIT	/* without creating excess queue... */
};
```

一个完整周期是 `1.25, 0.75, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0`：先用 1.25 探一下有没有更多带宽可用，紧接着用 0.75 把刚才可能堆起来的队列排掉（同时向其他流让出带宽），剩下 6 相以 1.0 巡航。平均下来 `(1.25 + 0.75 + 6)/8 = 1.0`，所以长期平均速率就是估计带宽——**探测是免费的**，这正是增益循环比"周期性大幅上调再回撤"优雅的地方。

进入 PROBE_BW 时起始相位是**随机化**的（`bbr_reset_probe_bw_mode()`，`tcp_bbr.c:618`）：

```c
	bbr->cycle_idx = CYCLE_LEN - 1 - get_random_u32_below(bbr_cycle_rand);
	bbr_advance_cycle_phase(sk);	/* flip to next phase of gain cycle */
```

`bbr_cycle_rand = 7`，即在前 7 相里随机挑一个作为起点。目的是**让多条 BBR 流的探测相位错开**，避免它们同时上调、同时排空造成同步振荡。

相位推进的判据 `bbr_is_next_cycle_phase()`（`tcp_bbr.c:555`）按增益分三种情况：

```c
	if (bbr->pacing_gain == BBR_UNIT)
		return is_full_length;		/* just use wall clock time */

	inflight = bbr_packets_in_net_at_edt(sk, rs->prior_in_flight);
	bw = bbr_max_bw(sk);

	if (bbr->pacing_gain > BBR_UNIT)
		return is_full_length &&
			(rs->losses ||
			 inflight >= bbr_inflight(sk, bw, bbr->pacing_gain));

	return is_full_length ||
		inflight <= bbr_inflight(sk, bw, BBR_UNIT);
```

- **增益 1.0**：只看是否超过一个 min_rtt（`is_full_length`）。
- **增益 > 1（探测）**：需要"时间够了 **且** inflight 已经到 1.25×BDP"。但**如果有丢包就提前结束**——因为浅缓冲路径可能根本装不下 1.25×BDP，硬撑只会白白丢包。
- **增益 < 1（排空）**：时间够了 **或** inflight 已经降到 BDP 以下就结束，避免排空过头导致管道利用率不足。

`is_full_length` 的定义也值得一提：

```c
	bool is_full_length =
		tcp_stamp_us_delta(tp->delivered_mstamp, bbr->cycle_mstamp) >
		bbr->min_rtt_us;
```

用的是 `delivered_mstamp`（最后一个交付包的时间戳）而不是当前时间——这样衡量的是"数据实际在网络里流动了多久"，把发送端的空闲时间排除掉。

### PROBE_RTT: The 2% Cost

```c
static const u32 bbr_probe_rtt_mode_ms = 200;
static const u32 bbr_cwnd_min_target = 4;
```

进入条件（`tcp_bbr.c:958`）：min_rtt 窗口（10 秒）过期 **且** 不是在 idle 重启 **且** 当前不在 PROBE_RTT。进入时把 cwnd 压到 **4 个包**，持续**至少 200ms 且至少经过一个 packet-timed round**（`tcp_bbr.c:970-981`）。

200ms 这个数字是算出来的：200ms / 10s = **2%**，即"为了持续获得准确的 RTprop，吞吐上界的损失约为 2%"。

退出后回哪个状态由 `bbr_reset_mode()` 决定（`tcp_bbr.c:627`）——**取决于是否曾达到过满带宽**：满了回 PROBE_BW，没满回 STARTUP 重新填管道。

## What Happens on One ACK: The Call Chain of bbr_main

### Scheduling Point: The Fork Between cong_control and cong_avoid

BBR 之所以能完全绕开内核的拥塞状态机，是因为它注册的是 `cong_control` 而不是 `cong_avoid`。分岔点在 `tcp_cong_control()`（`net/ipv4/tcp_input.c:3858`）：

```c
static void tcp_cong_control(struct sock *sk, u32 ack, u32 acked_sacked,
			     int flag, const struct rate_sample *rs)
{
	const struct inet_connection_sock *icsk = inet_csk(sk);

	if (icsk->icsk_ca_ops->cong_control) {
		icsk->icsk_ca_ops->cong_control(sk, ack, flag, rs);
		return;
	}

	if (tcp_in_cwnd_reduction(sk)) {
		/* Reduce cwnd if state mandates */
		tcp_cwnd_reduction(sk, acked_sacked, rs->losses, flag);
	} else if (tcp_may_raise_cwnd(sk, flag)) {
		/* Advance cwnd if state allows */
		tcp_cong_avoid(sk, ack, acked_sacked);
	}
	tcp_update_pacing_rate(sk);
}
```

注意这个 `return`——**只要算法提供了 `cong_control`，内核的 cwnd 削减（`tcp_cwnd_reduction`）和通用 pacing 计算（`tcp_update_pacing_rate`）就都不会执行**。BBR 拿到了完全的控制权。

对比一下被跳过的 `tcp_update_pacing_rate()`（`tcp_input.c:1138`）：它的逻辑是 `sk_pacing_rate = 200% × cwnd × mss / srtt`（慢启动时）或 120%（拥塞避免时）。这是个**基于 cwnd 的启发式**，而 BBR 的 pacing 是基于自己测出来的带宽模型，两者不是一回事。

头文件里对这两个回调的分工有明确说明（`include/net/tcp.h:1327`）：`cong_avoid` 适用于"想复用内核标准 Reno/CUBIC 式丢包响应、ECN、pacing 计算"的算法；`cong_control` 适用于"想要完全自定义行为"的算法。

### bbr_main: Three Steps

```c
__bpf_kfunc static void bbr_main(struct sock *sk, u32 ack, int flag, const struct rate_sample *rs)
{
	struct bbr *bbr = inet_csk_ca(sk);
	u32 bw;

	bbr_update_model(sk, rs);

	bw = bbr_bw(sk);
	bbr_set_pacing_rate(sk, bw, bbr->pacing_gain);
	bbr_set_cwnd(sk, rs, rs->acked_sacked, bw, bbr->cwnd_gain);
}
```

（`tcp_bbr.c:1028`）

`bbr_update_model()` 是五个更新的固定顺序（`tcp_bbr.c:1017`）：

```c
static void bbr_update_model(struct sock *sk, const struct rate_sample *rs)
{
	bbr_update_bw(sk, rs);
	bbr_update_ack_aggregation(sk, rs);
	bbr_update_cycle_phase(sk, rs);
	bbr_check_full_bw_reached(sk, rs);
	bbr_check_drain(sk, rs);
	bbr_update_min_rtt(sk, rs);
	bbr_update_gains(sk);
}
```

顺序是有讲究的：先更新带宽与 RTT 这两个**观测量**，再据此推进**状态机**，最后才算出**增益**给下一步用。也就是说每个 ACK 的处理都是"先修正模型，再按模型行动"。

### bbr_set_pacing_rate: The Exception That Only Increases

```c
static void bbr_set_pacing_rate(struct sock *sk, u32 bw, int gain)
{
	struct tcp_sock *tp = tcp_sk(sk);
	struct bbr *bbr = inet_csk_ca(sk);
	unsigned long rate = bbr_bw_to_pacing_rate(sk, bw, gain);

	if (unlikely(!bbr->has_seen_rtt && tp->srtt_us))
		bbr_init_pacing_rate_from_rtt(sk);
	if (bbr_full_bw_reached(sk) || rate > READ_ONCE(sk->sk_pacing_rate))
		WRITE_ONCE(sk->sk_pacing_rate, rate);
}
```

（`tcp_bbr.c:287`）

默认行为是**只允许 pacing 速率上升，不允许下降**——除非已经达到满带宽。原因是带宽滤波器的 max 值只会随时间窗口滑出才下降，而**主动降速会自我强化**（降速 → 测到更低带宽 → 再降速），形成负反馈陷阱。所以在 STARTUP 阶段（还没确认满带宽）速率单调不减。

### bbr_set_cwnd: The Only Place That 'Cuts' the Window

```c
	target_cwnd = bbr_bdp(sk, bw, gain);

	/* Increment the cwnd to account for excess ACKed data that seems
	 * due to aggregation (of data and/or ACKs) visible in the ACK stream.
	 */
	target_cwnd += bbr_ack_aggregation_cwnd(sk);
	target_cwnd = bbr_quantization_budget(sk, target_cwnd);

	/* If we're below target cwnd, slow start cwnd toward target cwnd. */
	if (bbr_full_bw_reached(sk))  /* only cut cwnd if we filled the pipe */
		cwnd = min(cwnd + acked, target_cwnd);
	else if (cwnd < target_cwnd || tp->delivered < TCP_INIT_CWND)
		cwnd = cwnd + acked;
	cwnd = max(cwnd, bbr_cwnd_min_target);

done:
	tcp_snd_cwnd_set(tp, min(cwnd, tp->snd_cwnd_clamp));	/* apply global cap */
	if (bbr->mode == BBR_PROBE_RTT)  /* drain queue, refresh min_rtt */
		tcp_snd_cwnd_set(tp, min(tcp_snd_cwnd(tp), bbr_cwnd_min_target));
```

（`tcp_bbr.c:520`）

关键分支：**只有在确认填满管道之后才允许把 cwnd 砍到目标值以下**（`min(cwnd + acked, target_cwnd)`）；在 STARTUP 期间 cwnd 只增不减。最后 PROBE_RTT 阶段无条件压到 4 包。

### bbr_bdp and Quantization Budget

```c
static u32 bbr_bdp(struct sock *sk, u32 bw, int gain)
{
	...
	if (unlikely(bbr->min_rtt_us == ~0U))	 /* no valid RTT samples yet? */
		return TCP_INIT_CWND;  /* be safe: cap at default initial cwnd*/

	w = (u64)bw * bbr->min_rtt_us;

	bdp = (((w * gain) >> BBR_SCALE) + BW_UNIT - 1) / BW_UNIT;

	return bdp;
}
```

（`tcp_bbr.c:361`）注意 `min_rtt_us == ~0U` 表示从未拿到有效 RTT 样本（注释说明：这种情况发生在连接没开时间戳、且到目前为止所有 SYN/SYNACK/数据的 ACK 都来自重传包），此时保守地用 `TCP_INIT_CWND`。

BDP 算出来之后还要加一个"量化预算"（`tcp_bbr.c:396`）：

```c
	cwnd += 3 * bbr_tso_segs_goal(sk);

	/* Reduce delayed ACKs by rounding up cwnd to the next even number. */
	cwnd = (cwnd + 1) & ~1U;

	/* Ensure gain cycling gets inflight above BDP even for small BDPs. */
	if (bbr->mode == BBR_PROBE_BW && bbr->cycle_idx == 0)
		cwnd += 2;
```

三件事：

1. **`+3 × tso_segs_goal`**——注释解释得清楚：要让高速路径跑满，两端主机上还得各留够 inflight（发送端 qdisc 里一个 skb、TSO/GSO 引擎里一个、接收端 LRO/GRO/延迟 ACK 引擎里一个）。低速时 `tso_segs_goal` 是 1，所以不会撑大窗口。
2. **向上取偶数**——减少延迟 ACK 的发生（滑动窗口协议每两个包回一个 ACK，奇数窗口会导致最后那个包的 ACK 被延迟）。
3. **PROBE_BW 第 0 相再 +2**——保证即使 BDP 很小，探测相位也能把 inflight 推到 BDP 之上。

### EDT-aware inflight: Why 'In Flight' Does Not Equal 'In the Network'

这是一个容易被忽略但很关键的细节。有了 fq qdisc 的 EDT（Earliest Departure Time）pacing 之后，**很多 skb 其实还排在发送端的 pacing 层里，带着一个未来的出发时间**，它们算在 `packets_in_flight` 里但并不在网络中。BBR 关心的是后者：

```c
static u32 bbr_packets_in_net_at_edt(struct sock *sk, u32 inflight_now)
{
	...
	now_ns = tp->tcp_clock_cache;
	edt_ns = max(tp->tcp_wstamp_ns, now_ns);
	interval_us = div_u64(edt_ns - now_ns, NSEC_PER_USEC);
	interval_delivered = (u64)bbr_bw(sk) * interval_us >> BW_SCALE;
	inflight_at_edt = inflight_now;
	if (bbr->pacing_gain > BBR_UNIT)              /* increasing inflight */
		inflight_at_edt += bbr_tso_segs_goal(sk);  /* include EDT skb */
	if (interval_delivered >= inflight_at_edt)
		return 0;
	return inflight_at_edt - interval_delivered;
}
```

（`tcp_bbr.c:438`）

公式是注释里那行：**`in_network_at_edt = inflight_at_edt - (EDT - now) × bw`**。从现在到下一个 skb 的 EDT 时刻这段时间内，按当前带宽会有 `interval_delivered` 个包被交付掉，所以到时候真正在网络里的只剩差值。增益 > 1 时还要把 EDT 那个 skb 本身算进去（因为要判断"发出它会不会超过目标"）。

这个函数用在三处：DRAIN 退出判据、PROBE_BW 相位推进判据、以及 `bbr_is_next_cycle_phase()` 的 inflight 比较。

## Three Easily Overlooked Sub-mechanisms

### ACK Aggregation Compensation: extra_acked

问题场景：接收端（或中间设备）把多个 ACK 攒起来一起发，形成"ACK 突发"。突发之间是一段静默，BBR 在这段静默里会因为没有 ACK 而停止发送，管道出现空洞。

补偿方式是测量"比预期多确认了多少数据"（`bbr_update_ack_aggregation()`，`tcp_bbr.c:818`）：在一个 epoch 内，用 `bbr_bw × epoch 时长` 算出**预期应该确认多少**，实际确认数减去它就是 `extra_acked`。取最近 5~10 个 round 的最大值，然后加进 cwnd：

```c
	max_aggr_cwnd = ((u64)bbr_bw(sk) * bbr_extra_acked_max_us)
			/ BW_UNIT;
	aggr_cwnd = (bbr_extra_acked_gain * bbr_extra_acked(sk))
		     >> BBR_SCALE;
	aggr_cwnd = min(aggr_cwnd, max_aggr_cwnd);
```

两个钳制：`extra_acked` 不超过当前 cwnd，补偿量不超过 `bw × 100ms`（`bbr_extra_acked_max_us`）。后者是为了防止在极端聚合下 cwnd 被撑得过大、反而制造排队。

实现上用了**双槽交替重置**（`extra_acked[2]` + `extra_acked_win_idx`）来近似滑动窗口，避免每轮清零导致估计值剧烈跳动——这也是 win_minmax 那套"别让窗口滑动造成估值断崖"思路的复用。

另外注意 `bbr_full_bw_reached(sk)` 是补偿的前提：管道还没填满时不加这个补偿。

### Traffic Shaper Detection: LT bandwidth sampling

令牌桶整形（policer）在网络里很常见（SIGCOMM 2016 的 "An Internet-Wide Analysis of Traffic Policing"）。面对 policer，BBR 的带宽探测会持续撞上令牌耗尽导致的丢包，探测行为本身变得有害。

检测逻辑在 `bbr_lt_bw_sampling()`（`tcp_bbr.c:689`），判据是**连续两个采样间隔的吞吐量一致且丢包率高**：

```c
	/* Is loss rate (lost/delivered) >= lt_loss_thresh? If not, wait. */
	if (!delivered || (lost << BBR_SCALE) < bbr_lt_loss_thresh * delivered)
		return;
```

`bbr_lt_loss_thresh = 50`，即 `lost/delivered ≥ 50/256 ≈ 19.5%`（注释里简称 20%）。

两个间隔的带宽"一致"的判据（`bbr_lt_bw_interval_done()`，`tcp_bbr.c:659`）是二选一：

```c
		diff = abs(bw - bbr->lt_bw);
		if ((diff * BBR_UNIT <= bbr_lt_bw_ratio * bbr->lt_bw) ||
		    (bbr_rate_bytes_per_sec(sk, diff, BBR_UNIT) <=
		     bbr_lt_bw_diff)) {
			/* All criteria are met; estimate we're policed. */
			bbr->lt_bw = (bw + bbr->lt_bw) >> 1;  /* avg 2 intvls */
			bbr->lt_use_bw = 1;
			bbr->pacing_gain = BBR_UNIT;  /* try to avoid drops */
			bbr->lt_rtt_cnt = 0;
			return;
		}
```

- **相对判据**：`diff ≤ 1/8 × lt_bw`（`bbr_lt_bw_ratio = BBR_UNIT / 8 = 32`）
- **绝对判据**：`diff ≤ 500 字节/秒`（`bbr_lt_bw_diff = 4000 / 8`，注释写的是 4 Kbit/sec）

绝对判据是为了低速场景——这时候 1/8 的相对差太小，几乎不可能满足。

一旦判定被整形，就用两个间隔的平均值作为 `lt_bw`，并把 `pacing_gain` 钉在 1.0（不再探测）。这个状态最多持续 **48 个 round**（`bbr_lt_bw_max_rtts`）然后重置、重新进入增益循环（`tcp_bbr.c:697-703`）。

还有几个防御性细节值得注意：

- **等到第一次丢包才开始采样**（`tcp_bbr.c:710`）：让 policer 先把令牌耗尽，这样测到的才是 policer 允许的稳态速率；过早采样会把突发速率算进去，高估带宽。
- **采样间隔以丢包结束**（`tcp_bbr.c:736`）：同上，令牌耗尽才说明到了稳态。
- **app-limited 就重置**（`tcp_bbr.c:718`）：避免低估。
- **间隔长度限制**：至少 4 个 round（`bbr_lt_intvl_min_rtts`），超过 `4 × 4 = 16` 个 round 就重置。

### What to Do on Packet Loss: Packet Conservation

BBR 的核心不响应丢包，但完全无视丢包会让丢包率失控。折中方案在 `bbr_set_cwnd_to_recover_or_restore()`（`tcp_bbr.c:481`）：

```c
	/* An ACK for P pkts should release at most 2*P packets. We do this
	 * in two steps. First, here we deduct the number of lost packets.
	 * Then, in bbr_set_cwnd() we slow start up toward the target cwnd.
	 */
	if (rs->losses > 0)
		cwnd = max_t(s32, cwnd - rs->losses, 1);

	if (state == TCP_CA_Recovery && prev_state != TCP_CA_Recovery) {
		/* Starting 1st round of Recovery, so do packet conservation. */
		bbr->packet_conservation = 1;
		bbr->next_rtt_delivered = tp->delivered;  /* start round now */
		/* Cut unused cwnd from app behavior, TSQ, or TSO deferral: */
		cwnd = tcp_packets_in_flight(tp) + acked;
	} else if (prev_state >= TCP_CA_Recovery && state < TCP_CA_Recovery) {
		/* Exiting loss recovery; restore cwnd saved before recovery. */
		cwnd = max(cwnd, bbr->prior_cwnd);
		bbr->packet_conservation = 0;
	}
```

策略是分阶段的：

1. **进入恢复的第一轮**：严格 packet conservation——**收到 P 个包的 ACK 就只发 P 个包**。同时把 cwnd 砍到 `inflight + acked`，目的是削掉那些因为应用行为、TSQ 或 TSO 延迟而"占着但不在使用"的 cwnd。
2. **恢复的第一轮之后**：放宽到"P 个 ACK 最多释放 2P 个包"，即慢启动往目标 cwnd 爬。
3. **退出恢复**：恢复成进入恢复前保存的 `prior_cwnd`（取较大值）。

注意这里 `bbr->next_rtt_delivered = tp->delivered` 手动开了一个新 round——进入恢复等于一次"重新计时"。

保存/恢复 cwnd 的逻辑在 `bbr_save_cwnd()`（`tcp_bbr.c:322`）：

```c
	if (bbr->prev_ca_state < TCP_CA_Recovery && bbr->mode != BBR_PROBE_RTT)
		bbr->prior_cwnd = tcp_snd_cwnd(tp);  /* this cwnd is good enough */
	else  /* loss recovery or BBR_PROBE_RTT have temporarily cut cwnd */
		bbr->prior_cwnd = max(bbr->prior_cwnd, tcp_snd_cwnd(tp));
```

即：不在恢复态时直接记录当前 cwnd（认为它"够好"）；在恢复态或 PROBE_RTT 里（cwnd 已被临时压低）则只往上取最大值，避免把压低后的值记成"好 cwnd"。

还有一处和 RTO 的配合（`bbr_set_state()`，`tcp_bbr.c:1130`）：

```c
	if (new_state == TCP_CA_Loss) {
		struct rate_sample rs = { .losses = 1 };

		bbr->prev_ca_state = TCP_CA_Loss;
		bbr->full_bw = 0;
		bbr->round_start = 1;	/* treat RTO like end of a round */
		bbr_lt_bw_sampling(sk, &rs);
	}
```

进入 Loss 状态（即 RTO 触发）时，清空 `full_bw`（重新探测管道是否满）、把这次当成一轮结束、并给 LT 采样器喂一个"丢了 1 个包"的合成样本。这是 BBR 对 RTO 唯一的直接反应——它**不乘性减窗口**，只是让模型重新收敛。

## BBR Interface with Other Kernel Parts

### tcp_congestion_ops Registration

```c
static struct tcp_congestion_ops tcp_bbr_cong_ops __read_mostly = {
	.flags		= TCP_CONG_NON_RESTRICTED,
	.name		= "bbr",
	.owner		= THIS_MODULE,
	.init		= bbr_init,
	.cong_control	= bbr_main,
	.sndbuf_expand	= bbr_sndbuf_expand,
	.undo_cwnd	= bbr_undo_cwnd,
	.cwnd_event_tx_start	= bbr_cwnd_event_tx_start,
	.ssthresh	= bbr_ssthresh,
	.min_tso_segs	= bbr_min_tso_segs,
	.get_info	= bbr_get_info,
	.set_state	= bbr_set_state,
};
```

（`tcp_bbr.c:1144`）

几个值得说明的：

- **`TCP_CONG_NON_RESTRICTED`**：允许非特权用户设置这个算法（受限算法需要 `CAP_NET_ADMIN`）。
- **没有 `cong_avoid`**：走的是 `cong_control` 路径，完全接管（前面讲过）。
- **`sndbuf_expand = 3`**：`bbr_sndbuf_expand()` 返回 3，注释说"因为 BBR 即使在恢复期也可能慢启动"，所以发送缓冲要按 3 倍 cwnd 预留。
- **只有 `cwnd_event_tx_start`，没有通用的 `cwnd_event`**：BBR 只关心"开始发送"这一个事件。它的作用是从 idle 恢复时重置 ACK 聚合 epoch，并在 PROBE_BW 期间把 pacing 速率重设为 1.0×bw（`tcp_bbr.c:333`）——因为从空闲恢复时不需要激进探测，按估计带宽走就行。
- **`min_tso_segs`**：低速时（`sk_pacing_rate < 1.2Mbps/8`）强制 TSO 段数为 1，避免在低带宽下攒大包造成突发。

`bbr_init()` 里有两件事值得单独记：

```c
	WRITE_ONCE(tp->snd_ssthresh, TCP_INFINITE_SSTHRESH);
	...
	cmpxchg(&sk->sk_pacing_status, SK_PACING_NONE, SK_PACING_NEEDED);
```

**ssthresh 被设为无穷大**——BBR 不用传统的"慢启动阈值"，因为它的 cwnd 完全由 BDP 模型决定，不需要一个"什么时候从指数增长切到线性增长"的开关。这也是为什么 `bbr_ssthresh()` 直接返回 `tp->snd_ssthresh` 原值不动，只顺手保存一下 cwnd。

**`SK_PACING_NEEDED`** 就是前面说的 pacing 要求：没有 fq qdisc 时内核用每 socket 一个 hrtimer 的软件 pacing 兜底。

### Observation: What ss Can See

`bbr_get_info()`（`tcp_bbr.c:1108`）通过 `INET_DIAG_BBRINFO` 暴露内部状态：

```c
		u64 bw = bbr_bw(sk);

		bw = bw * tp->mss_cache * USEC_PER_SEC >> BW_SCALE;
		...
		info->bbr.bbr_bw_lo		= (u32)bw;
		info->bbr.bbr_bw_hi		= (u32)(bw >> 32);
		info->bbr.bbr_min_rtt		= bbr->min_rtt_us;
		info->bbr.bbr_pacing_gain	= bbr->pacing_gain;
		info->bbr.bbr_cwnd_gain		= bbr->cwnd_gain;
```

`ss -ti` 里看到的 `bbr:(bw:..., mrtt:..., pacing_gain:..., cwnd_gain:...)` 就是这个。带宽拆成 lo/hi 两个 u32 是因为字节/秒的值可能超过 32 位。

### How to Enable

```bash
# 确认模块可用
cat /proc/sys/net/ipv4/tcp_available_congestion_control

# 系统默认（也可在 Kconfig 的 DEFAULT_BBR 里编译期指定）
sysctl -w net.ipv4.tcp_congestion_control=bbr

# 配 fq qdisc（强烈建议）
tc qdisc replace dev eth0 root fq
```

Kconfig 里 `DEFAULT_TCP_CONG` 的默认值仍是 `cubic`（`net/ipv4/Kconfig`），BBR 需要显式选。

## Limitations and Controversies

如实记录，不粉饰：

1. **与 CUBIC 共存的公平性问题**。BBRv1 的 PROBE_BW 只按自己的模型走，对丢包不敏感，所以在 CUBIC 流旁边会持续占据更多带宽。这是 BBRv1 最主要的批评点，也是 BBRv2 引入丢包/ECN 显式信号的动因。
2. **BBR 流之间的公平性靠随机相位**。8 相增益循环的随机起始相位只是让探测错开，并没有真正的收敛机制。RTT 差异大的 BBR 流之间仍会不平衡（短 RTT 流的增益循环跑得更快）。
3. **PROBE_RTT 的 2% 是"上界损失"，实际影响因流而异**。对持续满速的长连接是实打实的 2%；对有静默期的流几乎为零。但在多条流同时进入 PROBE_RTT 时，聚合吞吐会有可见的周期性凹陷。
4. **对 ACK 聚合严重的链路（部分 Wi-Fi / 蜂窝）估计偏差**。extra_acked 补偿有 100ms 的钳制，超出部分无能为力。
5. **BBRv2 / v3 不在主线内核**。v7.2.7 的 `net/ipv4/` 下只有 `tcp_bbr.c`。想要 BBRv2 的行为需要用 Google 的分支或第三方补丁，评估时必须分清版本。
6. **需要 fq 才能发挥**。没有 EDT pacing 时退化为 per-socket hrtimer，精度和 CPU 开销都变差。

## Relationship with Other Notes

BBR 不是孤立的一块，它依赖的三个上游都在本目录其他笔记里：

- **丢包检测**：BBR 自己只做 packet conservation，真正的"哪些包丢了"由 RACK/TLP 判定，见 [Retransmission](/docs/CS/OS/Linux/net/TCP/Retransmission.md)。RACK 与 BBR 是分工关系——RACK 负责发现丢包，BBR 负责决定发现之后发多快。
- **拥塞框架**：`cong_control` vs `cong_avoid` 的分岔、`tcp_ca_state` 状态机、算法注册表都在 [Congestion Control](/docs/CS/OS/Linux/net/TCP/TCP.md?id=congestion-control) 与 [Congestion Control Interface](/docs/CS/OS/Linux/net/TCP/TCP.md?id=congestion-control-interface)。
- **CUBIC**：对照看 [CUBIC](/docs/CS/OS/Linux/net/TCP/TCP.md?id=cubic) 有助于理解 BBR 到底改变了什么——同样是"探测带宽"，一个用丢包当停止信号，一个用 delivery rate 的停滞当停止信号。
- **pacing 的落地**：EDT 与 `sk_pacing_rate` 的具体消费者在 [Qdisc](/docs/CS/OS/Linux/net/Qdisc.md)。

## Links

- [socket](/docs/CS/OS/Linux/net/socket.md)
- [网络知识地图](/docs/CS/OS/Linux/net/README.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

- [BBR: Congestion-Based Congestion Control (Cardwell et al., ACM Queue 2016)](https://queue.acm.org/detail.cfm?id=3022184)
- [An Internet-Wide Analysis of Traffic Policing (SIGCOMM 2016)](https://dl.acm.org/doi/10.1145/2934872.2934878)
- [draft-cardwell-iccrg-bbr-congestion-control](https://datatracker.ietf.org/doc/draft-cardwell-iccrg-bbr-congestion-control/)
- [BBR Development and Testing Mailing List](https://groups.google.com/forum/#!forum/bbr-dev)
- [tc-fq(8) man page](https://man7.org/linux/man-pages/man8/tc-fq.8.html)
