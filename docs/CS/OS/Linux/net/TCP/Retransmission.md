## Introduction

TCP 的全部复杂性，几乎都来自一个无法消除的困境：**发送方永远分不清"包丢了"和"包晚到了"**。它拿到的反馈只有 ACK——没收到 ACK，可能是包丢了，可能是 ACK 丢了，也可能只是还没到。而这两种情况的代价完全相反：过早重传会浪费带宽并加剧拥塞，过晚重传则让整条连接空转一个 RTO。

所以重传不是一个动作，而是**三个量共同决定的一个判断**：

1. **RTT**——这条路正常情况下要多久（测量问题）
2. **RTO**——等多久算"不正常"（统计问题，要容忍抖动）
3. **丢失判据**——除了"等太久"，还有没有更早的信号（推断问题）

本篇沿这条线走：先讲 RTT 怎么测、RTO 怎么算，再讲除了"等 RTO"之外内核还有哪些更早的判据。全部对照 v7.2.7 源码。RTO 到点之后的退避与放弃逻辑，[TCP](/docs/CS/OS/Linux/net/TCP/TCP.md?id=retry) 的 `## retry` 一节有代码摘录，本篇侧重讲那个超时值是怎么来的、以及为什么要尽量避免走到它。

一个容易事先搞错的事实：**在 v7.2.7 上，RACK 和 TLP 都是默认开启的**（`tcp_ipv4.c:3474-3475`），不是什么需要手动打开的新特性。所以"用重复 ACK 判丢包"这套教科书叙述，已经不是当前内核的主路径了。

## RTT：先测准，才谈得上重传

### 一次测量从哪来：三个来源的优先级

每个 ACK 都可能携带一个 RTT 样本，但可信度不同。`tcp_ack_update_rtt()` 同时收到三个候选（`net/ipv4/tcp_input.c:3459`）：

```c
static bool tcp_ack_update_rtt(struct sock *sk, const int flag,
			       long seq_rtt_us, long sack_rtt_us,
			       long ca_rtt_us, struct rate_sample *rs)
{
	const struct tcp_sock *tp = tcp_sk(sk);

	/* Prefer RTT measured from ACK's timing to TS-ECR. This is because
	 * broken middle-boxes or peers may corrupt TS-ECR fields. But
	 * Karn's algorithm forbids taking RTT if some retransmitted data
	 * is acked (RFC6298).
	 */
	if (seq_rtt_us < 0)
		seq_rtt_us = sack_rtt_us;
```

三个来源：

- **`seq_rtt_us`**——用"这个 skb 的发送时间"到"ACK 到达时间"直接相减。最可信，因为它依赖本地时钟，不依赖对端填的字段。但它**只能对从未重传、且刚被 ACK 推进 snd_una 的 skb 计算**。
- **`sack_rtt_us`**——来自 SACK 块对应的发送时间。当 ACK 没有推进 snd_una（比如只带 SACK 的重复 ACK）时用它。
- **`ca_rtt_us`**——来自时间戳选项的 TSecr 回显。只有当 ACK 确认了新数据时才采用（`tcp_input.c:3479`），这是 RFC 7323 的 RTTM 规则，防止纯 ACK 或重传 ACK 污染测量。

优先用第一个，退到第二个，再退到第三个，三个都拿不到就返回 false——**这一次 ACK 不产生 RTT 样本**。

### Jacobson 算法与它的定点放大

拿到了样本之后，`tcp_rtt_estimator()` 做平滑（`tcp_input.c:1070`）。这段代码在内核里躺了三十年，注释本身就是史料：

```c
	/*	The following amusing code comes from Jacobson's
	 *	article in SIGCOMM '88.  Note that rtt and mdev
	 *	are scaled versions of rtt and mean deviation.
	 *	This is designed to be as fast as possible
	 *	m stands for "measurement".
	 *
	 *	On a 1990 paper the rto value is changed to:
	 *	RTO = rtt + 4 * mdev
	 *
	 * Funny. This algorithm seems to be very broken.
	 */
	if (srtt != 0) {
		m -= (srtt >> 3);	/* m is now error in rtt est */
		srtt += m;		/* rtt = 7/8 rtt + 1/8 new */
		if (m < 0) {
			m = -m;		/* m is now abs(error) */
			m -= (tp->mdev_us >> 2);   /* similar update on mdev */
			if (m > 0)
				m >>= 3;
		} else {
			m -= (tp->mdev_us >> 2);   /* similar update on mdev */
		}
		tp->mdev_us += m;		/* mdev = 3/4 mdev + 1/4 new */
```

三个关键：**这是定点数，不是浮点数**。

| 字段 | 放大倍数 | 更新式 |
|---|---|---|
| `srtt_us` | 8× | `srtt += (m - srtt/8)`，即 7/8 旧 + 1/8 新 |
| `mdev_us` | 4× | `mdev += (|err| - mdev/4)`，即 3/4 旧 + 1/4 新 |
| `rttvar_us` | 4× | 由 `mdev_max_us` 收敛而来（见下） |

放大倍数直接写在移位里：`srtt >> 3` 是除以 8，`mdev >> 2` 是除以 4。**读这段代码时如果忘了这一点，所有的算式都会算错八倍。**

另一个容易忽略的细节是 `m < 0` 分支里的 `m >>= 3`——RTT 变小时（测量值低于估计值），对 mdev 的更新用**更细的增益**。注释说得很清楚，这是 Eifel 算法的一个变体：

```c
			/* This is similar to one of Eifel findings.
			 * Eifel blocks mdev updates when rtt decreases.
			 * This solution is a bit different: we use finer gain
			 * for mdev in this case (alpha*beta).
			 * Like Eifel it also prevents growth of rto,
			 * but also it also limits too fast rto decreases,
			 * happening in pure Eifel.
			 */
```

含义是：RTT 下降时不要立刻收紧 RTO（否则下一个正常抖动就会触发虚假超时），但也不要像纯 Eifel 那样完全冻结，而是用小得多的步长跟上。

### mdev_max 与 rttvar：为什么用两层

平滑后的 mdev 并不直接用于 RTO，中间还夹了一层（`tcp_input.c:1112`）：

```c
		if (tp->mdev_us > tp->mdev_max_us) {
			tp->mdev_max_us = tp->mdev_us;
			if (tp->mdev_max_us > tp->rttvar_us)
				tp->rttvar_us = tp->mdev_max_us;
		}
		if (after(tp->snd_una, tp->rtt_seq)) {
			if (tp->mdev_max_us < tp->rttvar_us)
				tp->rttvar_us -= (tp->rttvar_us - tp->mdev_max_us) >> 2;
			tp->rtt_seq = tp->snd_nxt;
			tp->mdev_max_us = tcp_rto_min_us(sk);
		}
```

- **`mdev_max_us`** 是"**当前这个 RTT 窗口内**观测到的最大偏差"。每跨过一个窗口（`snd_una` 超过 `rtt_seq`，`rtt_seq` 被重置为 `snd_nxt`）就清零重来，下限是 `rto_min`。
- **`rttvar_us`** 是**跨窗口的记忆**：窗口内偏差变大就立刻跟上（第一行），偏差变小则每次只收敛 1/4（第二行）。

这个不对称是刻意的——**抖动变大要立刻反应，变小要慢慢信**。如果 rttvar 对称收敛，一次偶发的大抖动之后的平静期会让 RTO 快速收紧，紧接着的第二次抖动就会造成虚假超时。

### 首次测量：为什么是 3×RTT

没有任何历史样本时（`tcp_input.c:1125`）：

```c
	} else {
		/* no previous measure. */
		srtt = m << 3;		/* take the measured time to be rtt */
		tp->mdev_us = m << 1;	/* make sure rto = 3*rtt */
		tp->rttvar_us = max(tp->mdev_us, tcp_rto_min_us(sk));
		tp->mdev_max_us = tp->rttvar_us;
		tp->rtt_seq = tp->snd_nxt;
	}
```

`srtt = 8m`、`mdev = 2m`，代入 RTO 公式就是 `m + 2m = 3m`。首次 RTT 没有任何统计量支撑，用三倍来兜底。注意 `rttvar` 还要和 `rto_min` 取大——即使首测 RTT 只有 1ms，RTO 也不会低于 200ms 量级。

### 重传歧义：Karn 在 Linux 怎么落地

Karn 算法的原始表述是"重传过的包，其 ACK 不能用于 RTT 测量"——因为你分不清这个 ACK 是在应答原始包还是重传包。Linux 上有两处实现，第一处就是前面看到的"只采未重传 skb 的发送时间"。

第二处在 RACK 的推进逻辑里（`tcp_input.c:1583`）：

```c
static void tcp_rack_advance(struct tcp_sock *tp, u8 sacked,
			     u32 end_seq, u64 xmit_time)
{
	u32 rtt_us;

	rtt_us = tcp_stamp_us_delta(tp->tcp_mstamp, xmit_time);
	if (rtt_us < tcp_min_rtt(tp) && (sacked & TCPCB_RETRANS)) {
		/* If the sacked packet was retransmitted, it's ambiguous
		 * whether the retransmission or the original (or the prior
		 * retransmission) was sacked.
		 *
		 * If the original is lost, there is no ambiguity. Otherwise
		 * we assume the original can be delayed up to aRTT + min_rtt.
		 * the aRTT term is bounded by the fast recovery or timeout,
		 * so it's at least one RTT (i.e., retransmission is at least
		 * an RTT later).
		 */
		return;
	}
```

判定条件是**测量值小于历史最小 RTT 且这个包被重传过**。逻辑很直接：重传至少比原始发送晚一个 RTT，所以如果测出来的"RTT"比历史最小值还小，那它一定是在应答原始包（或更早的某次重传），不是最近这次重传。这种样本必须丢弃，否则 RTT 会被系统性低估，进而 RTO 过紧、虚假超时。

## RTO：从方差到上下界

### 公式

有了 srtt 和 rttvar，RTO 就是一行（`include/net/tcp.h:879`）：

```c
static inline u32 __tcp_set_rto(const struct tcp_sock *tp)
{
	return usecs_to_jiffies((tp->srtt_us >> 3) + tp->rttvar_us);
}
```

即 **RTO = SRTT + RTTVAR**，其中 RTTVAR 已经是 4 倍放大的平均偏差——这正是 Jacobson 论文里的 `RTO = rtt + 4·mdev`。

`tcp_set_rto()` 算出后会做上界钳制（`tcp_input.c:1188`）：

```c
	inet_csk(sk)->icsk_rto = __tcp_set_rto(tp);
	tcp_bound_rto(sk);
```

而 `tcp_bound_rto()` 只做一件事（`tcp.h:874`）：`icsk_rto = min(icsk_rto, tcp_rto_max(sk))`。**下界不在这里钳**——注释说得很清楚（`tcp_input.c:1196`）：算法本身保证 RTO 不会低于 `TCP_RTO_MIN`，不需要额外夹一次。下界在 `tcp_rto_min()` 里体现，它是 `icsk_rto_min`（逐 socket 可设）与路由度量 `RTAX_RTO_MIN` 的合并结果。

相关常量（`include/net/tcp.h:160-168`）：

| 常量 | 值 | 含义 |
|---|---|---|
| `TCP_RTO_MIN` | `HZ/5`（250ms @ HZ=250，200ms @ HZ=1000） | RTO 下界 |
| `TCP_RTO_MAX` | 120 秒 | RTO 上界，也是协议定义的最大 RTT |
| `TCP_TIMEOUT_INIT` | 1 秒 | RFC 6298 建议的初始 RTO |
| `TCP_TIMEOUT_FALLBACK` | 3 秒 | RFC 1122 的旧值，SYN 重传后退到这里 |
| `TCP_TIMEOUT_MIN_US` | 2 毫秒 | 定时器最小分辨率 |

### 退避只在该重置时重置

指数退避的 `icsk_backoff` 只在**拿到有效 RTT 样本**时清零（`tcp_input.c:3495`）：

```c
	/* RFC6298: only reset backoff on valid RTT measurement. */
	inet_csk(sk)->icsk_backoff = 0;
	return true;
```

如果 ACK 只是推进了 snd_una 但没产生 RTT 样本（比如应答的是重传包），`tcp_ack_update_rtt()` 返回 false，backoff 保持不动。少了这一行，一次丢包后的退避会被后续 ACK 提前抹平，重传风暴就压不住。

## 超时之后：退避、放弃与两个例外

### tcp_retransmit_timer 的主干

RTO 到点进入 `tcp_retransmit_timer()`（`net/ipv4/tcp_timer.c:537`）。它有两个必须知道的例外分支。

**第一个例外：零窗口探测不算数。** 如果对端把接收窗口缩到 0，重传会退化成零窗探测，此时**不能**按"连接超时"处理（`tcp_timer.c:564`）：

```c
	if (!tp->snd_wnd && !sock_flag(sk, SOCK_DEAD) &&
	    !((1 << sk->sk_state) & (TCPF_SYN_SENT | TCPF_SYN_RECV))) {
		/* Receiver dastardly shrinks window. Our retransmits
		 * become zero probes, but we should not timeout this
		 * connection. If the socket is an orphan, time it out,
		 * we cannot allow such beasts to hang infinitely.
		 */
```

注释里的措辞（"dastardly"）相当直白。判断超时用的是 `tcp_rtx_probe0_timed_out()`，上限是 `tcp_rto_max(sk) * 2`。

**正常路径**则记 `LINUX_MIB_TCPTIMEOUTS`，调 `tcp_write_timeout()` 判是否放弃，然后：

```c
	tcp_enter_loss(sk);

	tcp_update_rto_stats(sk);
	if (tcp_retransmit_skb(sk, tcp_rtx_queue_head(sk), 1) > 0) {
```

注意最后这个参数 `1`——**RTO 只重传重传队列的队首一个包**，不像快速重传那样可以一次重传多个被标丢失的包。RTO 后没有可靠的丢包信息，只能从头开始，这也是它进入 `TCP_CA_Loss` 状态（慢启动重传）而非 `TCP_CA_Recovery` 的原因。

首次 RTO 时还会按当时的拥塞状态记不同的计数器（`tcp_timer.c:609-628`）：Recovery 状态下超时记 `TCPSACKRECOVERYFAIL`（Reno 记 `TCPRENORECOVERYFAIL`），Loss 状态记 `TCPLOSSFAILURES`，Disorder 记 `TCPSACKFAILURES`。**这几个计数器是"快速重传没能救回来"的直接证据**，排障时比 `TCPTimeouts` 更能说明问题。

### 退避：指数为主，薄流走线性

退避在 `out_reset_timer` 标签之后，但对"薄流"（thin stream，如 SSH、在线游戏的交互流量）有特殊处理（`tcp_timer.c:660`）：

```c
	if (sk->sk_state == TCP_ESTABLISHED &&
	    (tp->thin_lto || READ_ONCE(net->ipv4.sysctl_tcp_thin_linear_timeouts)) &&
	    tcp_stream_is_thin(tp) &&
	    icsk->icsk_retransmits <= TCP_THIN_LINEAR_RETRIES) {
		icsk->icsk_backoff = 0;
		icsk->icsk_rto = clamp(__tcp_set_rto(tp),
				       tcp_rto_min(sk),
				       tcp_rto_max(sk));
```

薄流的特点是在途包很少、丢一个就卡住，指数退避会让它延迟爆炸。所以这里**每次都重算 RTO 而不累积退避**，最多 `TCP_THIN_LINEAR_RETRIES` 次之后退回指数退避——注释说明了理由：避免对着黑洞一直线性重传。

### 放弃连接不是"重传 N 次"，而是"超过 N 次的时间预算"

这是本篇最容易被误解的一点。`tcp_retries2 = 15` 看上去是"重传 15 次就放弃"，实际不是。

判据在 `retransmits_timed_out()`（`tcp_timer.c:215`）：

```c
	start_ts = tp->retrans_stamp;
	if (likely(timeout == 0)) {
		unsigned int rto_base = TCP_RTO_MIN;

		if ((1 << sk->sk_state) & (TCPF_SYN_SENT | TCPF_SYN_RECV))
			rto_base = tcp_timeout_init(sk);
		timeout = tcp_model_timeout(sk, boundary, rto_base);
	}
```

`retrans_stamp` 是**这一轮丢包中第一次重传的时刻**（`tcp_retransmit_skb()` 里设置，`tcp_output.c:3711`）。判定的是"从那时起到现在过去了多久"，超过 `tcp_model_timeout()` 算出来的预算就放弃。

`tcp_model_timeout()` 建模的是"如果真的重传了 N 次、每次指数退避，总耗时是多少"（`tcp_timer.c:188`）：

```c
	linear_backoff_thresh = ilog2(tcp_rto_max(sk) / rto_base);
	if (boundary <= linear_backoff_thresh)
		timeout = ((2 << boundary) - 1) * rto_base;
	else
		timeout = ((2 << linear_backoff_thresh) - 1) * rto_base +
			(boundary - linear_backoff_thresh) * tcp_rto_max(sk);
	return jiffies_to_msecs(timeout);
```

分成两段：**退避还没到 `TCP_RTO_MAX` 之前按几何级数求和**，之后每次固定加一个 `rto_max`（因为 RTO 已经被钳住了，不再增长）。

代入默认值算一遍（HZ=1000，`TCP_RTO_MIN`=200ms，`tcp_rto_max`=120s，`tcp_retries2`=15）：

- `linear_backoff_thresh = ilog2(120000 / 200) = ilog2(600) = 9`
- 15 > 9，走第二段：`(2<<9 - 1) × 200ms + (15 - 9) × 120s = 1023 × 0.2s + 720s = 204.6s + 720s ≈ 924.6s`

**约 15.4 分钟**。这就是那个流传已久的"tcp_retries2 默认大约 15 分钟"的真实来源——它不是 15 次重传的时间，是 15 次重传**预算**的时间。实际重传次数取决于真实 RTO 增长得多快，通常会少于 15 次。

三档重试的分工（`tcp_timer.c:243` 起的 `tcp_write_timeout()`）：

| 档位 | 默认 | 触发什么 |
|---|---|---|
| `tcp_retries1` | 3 | **不放弃**，只做黑洞探测：`tcp_mtu_probing()` + `__dst_negative_advice()`（刷新路由缓存） |
| `tcp_retries2` | 15 | 放弃连接，`tcp_write_err()` 上报 ETIMEDOUT |
| `tcp_orphan_retries` | 0 → 8 | 已关闭/已 detach 的 socket 单独计算，防止占着资源不放 |

`tcp_retries1` 那一档常被人忽略，但它解释了"为什么链路刚出问题时会看到一次 MTU 探测"——那是内核在怀疑"是不是 MTU 太大被中间设备静默丢弃了"。

最后还有 `TCP_USER_TIMEOUT`（`icsk_user_timeout`）：应用可以通过 `setsockopt` 设置自己的上限，它会直接参与 `retransmits_timed_out()` 的 timeout 计算，优先级高于默认预算。

上面这套是**连接建立之后**的重传。握手阶段的 SYN / SYNACK 重传走的是另一条路：此时还没有 `tcp_sock` 的重传状态可用，SYNACK 靠 `tcp_rtx_synack()`、SYN 靠 `tcp_retransmit_timer()` 的 `TCPF_SYN_SENT` 分支，且默认次数完全不同（`tcp_syn_retries` = 6、`tcp_synack_retries` = 5）。详见 [Connection_Setup](/docs/CS/OS/Linux/net/TCP/Connection_Setup.md)。

## 丢失判据之一：重复 ACK 与 SACK 计分板

### dupthresh：数够 N 个就算丢

最原始的判据是"收到 N 个重复 ACK"。内核里这个阈值叫 `reordering`，默认 `TCP_FASTRETRANS_THRESH = 3`（`include/net/tcp.h:94`），并且**会随观测到的重排程度动态调整**（上限 `sysctl_tcp_max_reordering = 300`）。

没有 SACK 能力时走 `tcp_newreno_mark_lost()`（`net/ipv4/tcp_recovery.c:142`）：

```c
void tcp_newreno_mark_lost(struct sock *sk, bool snd_una_advanced)
{
	const u8 state = inet_csk(sk)->icsk_ca_state;
	struct tcp_sock *tp = tcp_sk(sk);

	if ((state < TCP_CA_Recovery && tp->sacked_out >= tp->reordering) ||
	    (state == TCP_CA_Recovery && snd_una_advanced)) {
```

条件是两个之一：还没进 Recovery 且重复 ACK 数够了；或者已在 Recovery 且 snd_una 又推进了（RFC 6582 的部分确认处理）。判定后标记**重传队列队首**为丢失——Reno 只能看到队首，这是它相对 SACK 的根本局限。

### SACK 计分板：一个六状态的交换图

有 SACK 之后，内核维护的是一张"哪些段到了、哪些没到"的计分板。每个 skb 的 `TCP_SKB_CB(skb)->sacked` 是这张表的位图，`tcp_input.c:1355` 那段长注释给出了完整定义：

```
 * Valid combinations are:
 * Tag  InFlight	Description
 * 0	1		- orig segment is in flight.
 * S	0		- nothing flies, orig reached receiver.
 * L	0		- nothing flies, orig lost by net.
 * R	2		- both orig and retransmit are in flight.
 * L|R	1		- orig is lost, retransmit is in flight.
 * S|R  1		- orig reached receiver, retrans is still in flight.
```

六个状态由四个比特组合而成：`TCPCB_SACKED_ACKED`（S）、`TCPCB_LOST`（L）、`TCPCB_SACKED_RETRANS`（R）。`InFlight` 那一列是状态机的精要——它决定了 `packets_out` 怎么算，而 `packets_out` 又是拥塞控制的输入。

驱动这张表的事件有四类（`tcp_input.c:1372`）：新 ACK/SACK 到达、重传发生、丢失检测判定、以及 **D-SACK 把任何状态改成 S**。

注释里还点出了一个很漂亮的性质：

> It is pleasant to note, that state diagram turns out to be commutative, so that we are allowed not to be bothered by order of our actions, when multiple events arrive simultaneously.

即这个状态机是**可交换的**——多个事件同时到达时，处理顺序不影响结果。这让内核不必为事件排序操心。

### DSACK：让接收方告诉发送方"你多发了一次"

D-SACK（RFC 2883）是 SACK 的扩展：接收方用它报告"这个范围的字节我**已经收到过**了"。这是唯一能让发送方确认"我刚才那次重传是多余的"的机制。

内核的识别逻辑在 `tcp_check_dsack()`（`tcp_input.c:1484`）：

```c
	if (before(start_seq_0, TCP_SKB_CB(ack_skb)->ack_seq)) {
		NET_INC_STATS(sock_net(sk), LINUX_MIB_TCPDSACKRECV);
	} else if (num_sacks > 1) {
		u32 end_seq_1 = get_unaligned_be32(&sp[1].end_seq);
		u32 start_seq_1 = get_unaligned_be32(&sp[1].start_seq);

		if (after(end_seq_0, end_seq_1) || before(start_seq_0, start_seq_1))
			return false;
		NET_INC_STATS(sock_net(sk), LINUX_MIB_TCPDSACKOFORECV);
	} else {
		return false;
	}
```

两种形态：**第一个 SACK 块落在 ACK 序号之下**（说明是重复数据），或者**第一个块被第二个块完全覆盖**（重复报告乱序段）。都不是就不是 DSACK。

识别出来之后还要过一道"可疑 DSACK"过滤（`tcp_input.c:1232`）：

```c
	seq_len = end_seq - start_seq;
	/* Dubious DSACK: DSACKed range greater than maximum advertised rwnd */
	if (seq_len > tp->max_window)
		return 0;
	if (seq_len > tp->mss_cache)
		dup_segs = DIV_ROUND_UP(seq_len, tp->mss_cache);
```

报告的范围大得不合理（超过对端通告过的最大窗口）就丢弃，计入 `TCPDSACKIGNOREDDUBIOUS`。这是对**对端可能撒谎或被中间盒篡改**的防御——内核不会仅凭 DSACK 就撤销拥塞窗口。

DSACK 的两个用途：

1. **检测重排**：DSACK 出现在"已 SACK 过又被重传"的段上，说明原始包不是丢了只是晚到。这是 `rack.dsack_seen` 的来源，RACK 用它来调大重排窗口。
2. **撤销虚假重传的代价**：`tp->undo_retrans` 递减（`tcp_input.c:1515`），配合 `tcp_undo_cwnd_reduction()` 恢复被误砍的拥塞窗口。

## 丢失判据之二：RACK——把判据从序号域搬到时间域

### 为什么 dupack 不够

基于重复 ACK 的判据有三个结构性盲区：

- **尾部丢失**：如果丢的是最后发出的几个包，后面没有包能触发重复 ACK，只能干等 RTO。
- **重传之后再丢**：重传的包又丢了，收到的重复 ACK 无法区分是在说原始包还是重传包。
- **重排与丢失混淆**：链路有重排时，dupthresh 只能靠调大阈值来容忍，而调大又意味着**真正的丢包也要等更久才被发现**。

RACK（Recent ACKnowledgment）换了判据的度量。内核注释把三种判据的差别讲得极清楚（`net/ipv4/tcp_recovery.c:38`）：

```c
/* RACK loss detection (IETF RFC8985):
 *
 * Marks a packet lost, if some packet sent later has been (s)acked.
 * The underlying idea is similar to the traditional dupthresh and FACK
 * but they look at different metrics:
 *
 * dupthresh: 3 OOO packets delivered (packet count)
 * FACK: sequence delta to highest sacked sequence (sequence space)
 * RACK: sent time delta to the latest delivered packet (time domain)
 *
 * The advantage of RACK is it applies to both original and retransmitted
 * packet and therefore is robust against tail losses. Another advantage
 * is being more resilient to reordering by simply allowing some
 * "settling delay", instead of tweaking the dupthresh.
 */
```

一句话：**dupthresh 数包数，FACK 量序号距离，RACK 算时间差**。

### 判据本身

核心就一个不等式（`tcp_recovery.c:32`）：

```c
s32 tcp_rack_skb_timeout(struct tcp_sock *tp, struct sk_buff *skb, u32 reo_wnd)
{
	return tp->rack.rtt_us + reo_wnd -
	       tcp_stamp_us_delta(tp->tcp_mstamp, tcp_skb_timestamp_us(skb));
}
```

`rack.rtt_us` 是最近一次被确认的包的 RTT，`tcp_stamp_us_delta(...)` 是这个 skb 发出去多久了。返回值就是"**还能再等多久**"，小于等于 0 就判丢（`tcp_recovery.c:84`）：

```c
		remaining = tcp_rack_skb_timeout(tp, skb, reo_wnd);
		if (remaining <= 0) {
			tcp_mark_skb_lost(sk, skb);
			list_del_init(&skb->tcp_tsorted_anchor);
		} else {
			/* Record maximum wait time */
			*reo_timeout = max_t(u32, *reo_timeout, remaining);
		}
```

没到期的包不会白算：它们的最大剩余时间会被记下来，用来设置 `ICSK_TIME_REO_TIMEOUT` 定时器——**到期时再来判一次**，而不是等 RTO。

### 遍历的是"按发送时间排序"的队列

RACK 要按时间比较，所以内核额外维护了一个队列（`include/linux/tcp.h:285`）：

```c
	struct list_head tsorted_sent_queue; /* time-sorted sent but un-SACKed skbs */
```

`tcp_rack_detect_loss()` 遍历的是它，不是按序号组织的 `tcp_rtx_queue`（`tcp_recovery.c:66`）。遍历在遇到第一个"发送时间晚于参照点"的包时 `break`——因为后面的包都更晚发出，不可能被判丢。

参照点 `tp->rack` 的定义（`include/linux/tcp.h:382`）：

```c
	struct tcp_rack {
		u64 mstamp; /* (Re)sent time of the skb */
		u32 rtt_us;  /* Associated RTT */
		u32 end_seq; /* Ending TCP sequence of the skb */
		u32 last_delivered; /* tp->delivered at last reo_wnd adj */
		u8 reo_wnd_steps;   /* Allowed reordering window */
#define TCP_RACK_RECOVERY_THRESH 16
		u8 reo_wnd_persist:5, /* No. of recovery since last adj */
		   dsack_seen:1, /* Whether DSACK seen after last adj */
		   advanced:1;	 /* mstamp advanced since last lost marking */
	} rack;
```

`tcp_skb_sent_after()` 比较时会同时看时间和序号——序号用于在发送时间相同（同一个 TSO 突发）时打破平局。

### 重排窗口：给"晚到"留出的余量

`reo_wnd` 是 RACK 里的关键参数，它决定"多久算晚"（`tcp_recovery.c:5`）：

```c
static u32 tcp_rack_reo_wnd(const struct sock *sk)
{
	const struct tcp_sock *tp = tcp_sk(sk);

	if (!tp->reord_seen) {
		/* If reordering has not been observed, be aggressive during
		 * the recovery or starting the recovery by DUPACK threshold.
		 */
		if (inet_csk(sk)->icsk_ca_state >= TCP_CA_Recovery)
			return 0;

		if (tp->sacked_out >= tp->reordering &&
		    !(READ_ONCE(sock_net(sk)->ipv4.sysctl_tcp_recovery) &
		      TCP_RACK_NO_DUPTHRESH))
			return 0;
	}

	/* To be more reordering resilient, allow min_rtt/4 settling delay.
	 * Use min_rtt instead of the smoothed RTT because reordering is
	 * often a path property and less related to queuing or delayed ACKs.
	 * Upon receiving DSACKs, linearly increase the window up to the
	 * smoothed RTT.
	 */
	return min((tcp_min_rtt(tp) >> 2) * tp->rack.reo_wnd_steps,
		   tp->srtt_us >> 3);
}
```

三个要点：

1. **没观测到重排时可以激进**——如果 dupthresh 已经满足（进入快速重传的现场）或已在 Recovery，窗口直接给 0，不等。
2. **基础值是 `min_rtt/4`**。注释解释了为什么用 min_rtt 而不是 srtt：重排是**路径属性**（多路径、并行链路），跟排队延迟无关，用最小 RTT 更能反映路径本身的特性。
3. **上限是 srtt**，且可以因 DSACK 而放大：`reo_wnd_steps` 每见一次 DSACK 加 1（`tcp_input.c:4264`），上限 0xFF；连续 `TCP_RACK_RECOVERY_THRESH`（16）次恢复都没再见 DSACK 就退回 1。

也就是说，**RACK 是从观测到的重排中学习的**，而不是靠人工调阈值——这正是它相对 dupthresh 的核心优势。

### 入口：Reno 与 SACK 在这里分道扬镳

`tcp_identify_packet_loss()` 是每次收到 ACK 后做丢失判定的统一入口（`tcp_input.c:3297`）：

```c
static void tcp_identify_packet_loss(struct sock *sk, int *ack_flag)
{
	struct tcp_sock *tp = tcp_sk(sk);

	if (tcp_rtx_queue_empty(sk))
		return;

	if (unlikely(tcp_is_reno(tp))) {
		tcp_newreno_mark_lost(sk, *ack_flag & FLAG_SND_UNA_ADVANCED);
	} else {
		u32 prior_retrans = tp->retrans_out;

		if (tcp_rack_mark_lost(sk))
			*ack_flag &= ~FLAG_SET_XMIT_TIMER;
		if (prior_retrans > tp->retrans_out)
			*ack_flag |= FLAG_LOST_RETRANS;
	}
}
```

代码非常直白：**没有 SACK 才走 dupthresh，否则一律走 RACK**。在 v7.2.7 的默认值下（SACK 默认开），绝大多数连接走的是 RACK 分支。

还有一处值得注意：进入恢复的判据 `tcp_time_to_recover()` 在 v7.2.7 已经简化成一行（`tcp_input.c:2717`）：

```c
static bool tcp_time_to_recover(const struct tcp_sock *tp)
{
	/* Has loss detection marked at least one packet lost? */
	return tp->lost_out != 0;
}
```

**旧版本里那一大段 "Trick#1: the loss is proven"、"Trick#2"、"Trick#3" 的条件判断已经全部消失**。原因是判据被统一了：不管丢包是 dupthresh、RACK 还是 RTO 判出来的，最终都体现在 `lost_out` 上，进入恢复就只看这一个条件。如果照着老资料去读 `tcp_time_to_recover()` 会找不到那些分支——它们被 RACK 的引入淘汰了。

## 尾包丢失：TLP

### 为什么尾包是特殊情况

RACK 需要"有更晚发出的包被确认"才能推断更早的包丢了。**如果丢的就是最后发出的包，没有任何更晚的包可供参照**——RACK 失效，只剩 RTO 一条路。而尾包丢失在短连接、请求-响应型流量里恰恰很常见。

TLP（Tail Loss Probe）的解法是：**与其干等 RTO，不如先主动发一个探测包**。探测包到达后会引发对端的 ACK（或 SACK），这个反馈就能喂给 RACK 做判定。

### PTO 的计算

探测超时叫 PTO，由 `tcp_schedule_loss_probe()` 设置（`net/ipv4/tcp_output.c:3099`）：

```c
	/* Probe timeout is 2*rtt. Add minimum RTO to account
	 * for delayed ack when there's one outstanding packet. If no RTT
	 * sample is available then probe after TCP_TIMEOUT_INIT.
	 */
	if (tp->srtt_us) {
		timeout_us = tp->srtt_us >> 2;
		if (tp->packets_out == 1)
			timeout_us += tcp_rto_min_us(sk);
		else
			timeout_us += TCP_TIMEOUT_MIN_US;
		timeout = usecs_to_jiffies(timeout_us);
	} else {
		timeout = TCP_TIMEOUT_INIT;
	}
```

`srtt_us` 是 8 倍放大，所以 `>> 2` 等于 **2 倍 RTT**。两个修正项都有讲究：

- 只有 1 个包在途时加 `rto_min`——因为对端大概率在延迟确认，要等一个 delack 超时才会回 ACK；
- 否则只加 `TCP_TIMEOUT_MIN_US`（2ms），避免定时器抖动导致过早触发。

最后还要跟 RTO 取小（`tcp_output.c:3137`）：

```c
	/* If the RTO formula yields an earlier time, then use that time. */
	rto_delta_us = advancing_rto ?
			jiffies_to_usecs(inet_csk(sk)->icsk_rto) :
			tcp_rto_delta_us(sk);  /* How far in future is RTO? */
	if (rto_delta_us > 0)
		timeout = min_t(u32, timeout, usecs_to_jiffies(rto_delta_us));
```

**TLP 永远不会比 RTO 晚**。如果算出来的 PTO 比 RTO 剩余时间还长，那就没意义了（等 RTO 更合理）。

触发条件也要看清（`tcp_output.c:3116`）：需要 `sysctl_tcp_early_retrans` 为 3 或 4（**默认值就是 3**）、连接支持 SACK、且处于 Open 或 CWR 状态——**已经在恢复中的连接不做 TLP**。

### 探测发什么：优先新数据

`tcp_send_loss_probe()` 的第一个选择可能反直觉（`tcp_output.c:3182`）：

```c
	tp->tlp_retrans = 0;
	skb = tcp_send_head(sk);
	if (skb && tcp_snd_wnd_test(tp, skb, mss)) {
		pcount = tp->packets_out;
		tcp_write_xmit(sk, mss, TCP_NAGLE_OFF, 2, GFP_ATOMIC);
		if (tp->packets_out > pcount)
			goto probe_sent;
		goto rearm_timer;
	}
```

**先试着重传……不对，是先试着发新数据**。如果有未发送的新数据且窗口允许，就发一个新段（注意 `tcp_write_xmit` 的第 4 个参数 `2`，那是 `push_one` 的特殊值，表示强制发一个）。发新数据的好处是它既能触发 ACK，又不浪费带宽——万一尾包没丢，这个新数据也是有用的。

没有新数据才重传重传队列的最后一个包（`tcp_output.c:3190`）：

```c
	skb = skb_rb_last(&sk->tcp_rtx_queue);
```

重传之前还有一道检查——`skb_still_in_host_queue()`（`tcp_output.c:3152`）：

```c
/* Thanks to skb fast clones, we can detect if a prior transmit of
 * a packet is still in a qdisc or driver queue.
 * In this case, there is very little point doing a retransmit !
 */
```

如果上一个副本还卡在本机的 qdisc 或驱动队列里，重传毫无意义，统计进 `TCPSpuriousRtxHostQueues` 并跳过。**TSQ 或驱动拥塞造成的"假超时"就靠这个挡掉**。

最后记录 `tp->tlp_high_seq = tp->snd_nxt`（`tcp_output.c:3222`）用于丢失判定，计数 `TCPLossProbes`，然后重新武装 RTO 定时器。

## 三个机制共用一个定时器

RTO、TLP、RACK 重排超时三者**共用同一个 `sk->tcp_retransmit_timer`**，靠 `icsk_pending` 区分当前挂的是哪种（`net/ipv4/tcp_timer.c:714`）：

```c
	switch (event) {
	case ICSK_TIME_REO_TIMEOUT:
		tcp_rack_reo_timeout(sk);
		break;
	case ICSK_TIME_LOSS_PROBE:
		tcp_send_loss_probe(sk);
		break;
	case ICSK_TIME_RETRANS:
		smp_store_release(&icsk->icsk_pending, 0);
		tcp_retransmit_timer(sk);
		break;
	case ICSK_TIME_PROBE0:
		smp_store_release(&icsk->icsk_pending, 0);
		tcp_probe_timer(sk);
		break;
	}
```

这个设计有个重要推论：**同一时刻只有一个重传类定时器在跑**。`tcp_rearm_rto()` 重新武装 RTO 时，会把已经在跑的 TLP 或 REO_TIMEOUT 替换掉——所以前面 `tcp_send_loss_probe()` 结尾必须调 `tcp_rearm_rto()`，否则探测之后就没有兜底了。

替换时还会补偿已经流逝的时间（`tcp_input.c:3540`）：

```c
		/* Offset the time elapsed after installing regular RTO */
		if (icsk->icsk_pending == ICSK_TIME_REO_TIMEOUT ||
		    icsk->icsk_pending == ICSK_TIME_LOSS_PROBE) {
			s64 delta_us = tcp_rto_delta_us(sk);
			rto = usecs_to_jiffies(max_t(int, delta_us, 1));
		}
```

否则从 TLP 切回 RTO 时，RTO 会被"重置"成一个完整周期，丢包恢复的总时长就被拉长了。

## 真正重传什么

判定完成后，实际发包由 `tcp_xmit_retransmit_queue()` 完成（`net/ipv4/tcp_output.c:3725`）。它遍历重传队列，但有几个明确的停止条件：

```c
		if (tp->retrans_out >= tp->lost_out) {
			break;
		} else if (!(sacked & TCPCB_LOST)) {
			if (!hole && !(sacked & (TCPCB_SACKED_RETRANS|TCPCB_SACKED_ACKED)))
				hole = skb;
			continue;
		} else {
			if (icsk->icsk_ca_state != TCP_CA_Loss)
				mib_idx = LINUX_MIB_TCPFASTRETRANS;
			else
				mib_idx = LINUX_MIB_TCPSLOWSTARTRETRANS;
		}
```

- **只重传带 `TCPCB_LOST` 标记的**，没被判丢的一律跳过（计入 hole 供后续参考）
- **已重传的数量追平丢失数量就停**（`retrans_out >= lost_out`），避免重传风暴
- **`TCPFASTRETRANS` 与 `TCPSLOWSTARTRETRANS` 的区别就是"是否在 Loss 状态"**——前者是快速重传（有丢包信息），后者是 RTO 之后的慢启动重传

单个包的重传在 `__tcp_retransmit_skb()`（`tcp_output.c:3550`），里面有几处容易被忽略的处理：

**窗口收缩之后不再盲目重传**（`tcp_output.c:3593`）：

```c
	/* If receiver has shrunk his window, and skb is out of
	 * new window, do not retransmit it. The exception is the
	 * case, when window is shrunk to zero. In this case
	 * our retransmit of one segment serves as a zero window probe.
	 */
	if (avail_wnd <= 0) {
		if (TCP_SKB_CB(skb)->seq != tp->snd_una) {
			err = -EAGAIN;
			goto out;
		}
		avail_wnd = cur_mss;
	}
```

**TSO 要重新分段**：MSS 可能已经变了（PMTU 变化、对端选项变化），重传前要按当前 MSS 重新计算分段（`tcp_output.c:3624`），必要时调用 `tcp_fragment()` 拆包。

**重传时顺手合并小包**：`tcp_retrans_try_collapse()`（`tcp_output.c:3631`）——重传是小包时，如果后面还有能塞进同一个 MSS 的数据，就合并了再发。这能显著改善重传效率，由 `sysctl_tcp_retrans_collapse` 控制（默认开）。

**ECN 会在反复超时后回退**（`tcp_output.c:3634`）：

```c
	if (!tcp_ecn_mode_pending(tp) || icsk->icsk_retransmits > 1) {
		/* RFC3168, section 6.1.1.1. ECN fallback
		 * As AccECN uses the same SYN flags (+ AE), this check
		 * covers both cases.
		 */
		if ((TCP_SKB_CB(skb)->tcp_flags & TCPHDR_SYN_ECN) ==
		    TCPHDR_SYN_ECN)
			tcp_ecn_clear_syn(sk, skb);
	}
```

重传超过一次就认为对端或路径不支持 ECN，降级重试——这是 RFC 3166 6.1.1.1 规定的行为。

## 观测与排障

**单连接级别**，`ss -ti` 的字段直接来自 `tcp_get_info()`，对应内核字段（`include/uapi/linux/tcp.h`）：

| `ss -ti` 字段 | 内核字段 | 说明 |
|---|---|---|
| `rto:` | `tcpi_rto` | 当前 RTO（ms），含退避 |
| `rtt:` | `tcpi_rtt` / `tcpi_rttvar` | srtt 与 rttvar，已还原为真实微秒 |
| `retrans:` | `tcpi_retrans` / `tcpi_total_retrans` | 当前在途重传数 / 连接累计重传数 |
| `lost:` | `tcpi_lost` | 当前判丢的包数（`lost_out`） |
| `sacked:` | `tcpi_sacked` | SACK 确认的包数 |
| `reordering:` | `tcpi_reordering` | 当前的 dupthresh 阈值 |

`retrans:0/5` 这种写法里，斜杠后是 `total_retrans`，判断"这条连接是否一直有问题"看它。

**全局级别**，`/proc/net/snmp`（或 `nstat`）里与本篇相关的计数器：

| 计数器 | 含义 |
|---|---|
| `TCPTimeouts` | RTO 超时次数——**这是"所有快速机制都失败了"的信号** |
| `TCPSpuriousRtxHostQueues` | 重传被跳过，因为旧副本还卡在本机队列（TSQ/驱动拥塞） |
| `TCPLossProbes` | TLP 探测发出次数 |
| `TCPLossProbeRecovery` | TLP 探测成功救回的次数 |
| `TCPLostRetransmit` | 重传的包又丢了 |
| `TCPDSACKRecv` / `TCPDSACKOfoRecv` | 收到 DSACK；后者是乱序场景下的 |
| `TCPDSACKIgnoredDubious` | 被判定为可疑而忽略的 DSACK |
| `TCPSACKReneging` | 接收方撤销了已 SACK 的数据 |
| `TCPSACKFailures` / `TCPRenoFailures` | 快速重传没能救回，最终走了 RTO |

排障时的判据大致是：

- `TCPTimeouts` 高而 `TCPLossProbes` 为 0 → TLP 没生效（检查 `tcp_early_retrans` 被改过没，或连接不支持 SACK）
- `TCPSpuriousRtxHostQueues` 高 → 问题在本机发送路径（qdisc 队列太深、TSQ 限制），不在网络
- `TCPDSACKRecv` 持续增长 → 链路上有重排，或本端 RTO 过紧导致虚假重传
- `TCPLostRetransmit` 高 → 丢包是持续性的（拥塞或链路质量问题），不是偶发

相关 sysctl 与默认值（v7.2.7）：

| sysctl | 默认 | 作用 |
|---|---|---|
| `net.ipv4.tcp_retries1` | 3 | 触发黑洞探测，不放弃连接 |
| `net.ipv4.tcp_retries2` | 15 | 放弃连接的时间预算（约 15 分钟） |
| `net.ipv4.tcp_reordering` | 3 | 初始 dupthresh |
| `net.ipv4.tcp_max_reordering` | 300 | dupthresh 上限 |
| `net.ipv4.tcp_early_retrans` | 3 | TLP 开关（3/4 启用） |
| `net.ipv4.tcp_recovery` | 1 (`TCP_RACK_LOSS_DETECTION`) | RACK 开关 |
| `net.ipv4.tcp_frto` | 2 | F-RTO：RTO 后通过收到的 ACK 判断是丢包还是只是延迟 |
| `net.ipv4.tcp_thin_linear_timeouts` | 0 | 薄流线性超时 |

`tcp_frto` 值得单独提一句：它是 `tcp_enter_loss()` 里设置的（`tcp_input.c:2596`），作用是**在 RTO 重传后通过第一个回来的 ACK 判断这次超时是不是虚假的**——如果 ACK 确认的是重传之前就发出的数据，说明原始包只是延迟，可以撤销拥塞窗口的削减。它和 RACK 是互补的：RACK 防的是"不必要的 RTO"，F-RTO 治的是"已经发生的 RTO 造成的损失"。

## Links

- [socket](/docs/CS/OS/Linux/net/socket.md)
- [NAPI](/docs/CS/OS/Linux/net/NAPI.md)
- [Qdisc](/docs/CS/OS/Linux/net/Qdisc.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

- [RFC 6298: Computing TCP's Retransmission Timer](https://www.rfc-editor.org/rfc/rfc6298.html)
- [RFC 8985: The RACK-TLP Loss Detection Algorithm for TCP](https://www.rfc-editor.org/rfc/rfc8985.html)
- [RFC 2018: TCP Selective Acknowledgment Options](https://www.rfc-editor.org/rfc/rfc2018.html)
- [RFC 2883: An Extension to the Selective Acknowledgement (SACK) Option for TCP](https://www.rfc-editor.org/rfc/rfc2883.html)
- [RFC 6582: The NewReno Modification to TCP's Fast Recovery Algorithm](https://www.rfc-editor.org/rfc/rfc6582.html)
- [RFC 5682: Forward RTO-Recovery (F-RTO)](https://www.rfc-editor.org/rfc/rfc5682.html)
- [RFC 3168: The Addition of Explicit Congestion Notification (ECN) to IP](https://www.rfc-editor.org/rfc/rfc3168.html)
- [Congestion Avoidance and Control (Jacobson, SIGCOMM 88)](https://ee.lbl.gov/papers/congavoid.pdf)
