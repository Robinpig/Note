## Introduction

Linux 的 TCP 拥塞控制不是一个算法，而是**一套插件框架 + 一个五态状态机 + 一条默认实现**。CUBIC 只是默认插件，BBR 是另一个插件，两者共享的是下面这层机制：算法怎么注册、怎么被选中、丢包/ECN 来了内核怎么推进状态、cwnd 削减怎么执行、削减错了怎么撤销。

本篇讲的就是这层**框架**。它主要由三个文件构成：

| 文件 | 职责 |
| --- | --- |
| `net/ipv4/tcp_cong.c`（538 行） | 插件注册表、选择逻辑、Reno 默认实现、AIMD 基础函数 |
| `include/net/tcp.h` 的 `struct tcp_congestion_ops` | 算法要实现的回调契约 |
| `net/ipv4/tcp_input.c` 的状态迁移函数 | `tcp_enter_cwr` / `tcp_enter_recovery` / `tcp_enter_loss` / `tcp_cwnd_reduction` / undo |

具体的算法实现不在这里——CUBIC 见 [CUBIC](/docs/CS/OS/Linux/net/TCP/TCP.md?id=cubic)，BBR 见 [BBR](/docs/CS/OS/Linux/net/TCP/BBR.md)。本篇讲的是它们共同站在上面的那层。

一个先要澄清的分工：**"哪些包丢了"不归拥塞控制管**。丢包判定由 RACK/TLP/超时负责（见 [Retransmission](/docs/CS/OS/Linux/net/TCP/Retransmission.md)），拥塞控制只回答"知道丢包之后发多快"。这两个子系统在 v7.2.7 上是明确分离的。

## Plugin System: How Algorithms Are Registered

### Contract: Which Callbacks Are Mandatory

`struct tcp_congestion_ops`（`include/net/tcp.h:1324`）定义了一组回调，注册时会先校验（`tcp_cong.c:78`）：

```c
int tcp_validate_congestion_control(struct tcp_congestion_ops *ca)
{
	/* all algorithms must implement these */
	if (!ca->ssthresh || !ca->undo_cwnd ||
	    !(ca->cong_avoid || ca->cong_control)) {
		pr_err("%s does not implement required ops\n", ca->name);
		return -EINVAL;
	}

	return 0;
}
```

即**三个必选项**：

| 回调 | 必选 | 作用 |
| --- | --- | --- |
| `ssthresh` | ✅ | 进入削减时返回新的慢启动阈值 |
| `undo_cwnd` | ✅ | 撤销削减时返回应恢复的 cwnd |
| `cong_avoid` **或** `cong_control` | ✅ 二选一 | 增窗 / 完全接管 |

`cong_avoid` 与 `cong_control` 的二选一决定了算法属于哪一派。头文件里说得清楚（`include/net/tcp.h:1327`）：`cong_avoid` 适用于"想复用内核标准 Reno/CUBIC 式丢包响应、RFC3168 ECN、idle 处理、pacing 计算"的算法；`cong_control` 适用于"想要完全自定义行为"的算法。

其余都是可选：`init` / `release`、`set_state`、`cwnd_event`、`cwnd_event_tx_start`、`in_ack_event`、`pkts_acked`、`min_tso_segs`、`sndbuf_expand`、`get_info`、`flags`。

### Registration: Hash the Name into a Key, Attach to the RCU Linked List

```c
int tcp_register_congestion_control(struct tcp_congestion_ops *ca)
{
	int ret;

	ret = tcp_validate_congestion_control(ca);
	if (ret)
		return ret;

	ca->key = jhash(ca->name, sizeof(ca->name), strlen(ca->name));

	spin_lock(&tcp_cong_list_lock);
	if (ca->key == TCP_CA_UNSPEC || tcp_ca_find_key(ca->key)) {
		pr_notice("%s already registered or non-unique key\n",
			  ca->name);
		ret = -EEXIST;
	} else {
		list_add_tail_rcu(&ca->list, &tcp_cong_list);
		...
```

（`tcp_cong.c:93`）

三个设计点：

1. **算法按名字而不是指针标识**。`jhash` 把名字算成 `u32 key`，这个 key 会通过 `tcp_info` 暴露给用户态，也用于 BPF struct_ops 定位。好处是模块卸载再加载后 key 仍然一致。
2. **线性查找**，注释直言"don't expect many entries"——算法最多十几个，不值得用哈希表。
3. **RCU 保护**。查找走 `list_for_each_entry_rcu`，注册/注销用 spinlock + `synchronize_rcu()`。注销时那句注释解释了为什么要 `synchronize_rcu()`：模块引用计数保证没有 socket 在用，但仍有并发读者可能正持有指针。

还有个很有意思的函数 `tcp_update_congestion_control()`（`tcp_cong.c:146`）——**热替换一个已注册算法**，要求新算法名字与旧的相同，并且"先加后删"以保证任何时刻都有一个实现可用。这是给 **BPF struct_ops** 用的：允许在运行时用 BPF 程序替换拥塞算法，不用重新加载内核模块。

### flags: Permissions and ECN Negotiation

```c
#define TCP_CONG_NON_RESTRICTED		BIT(0)
/* Requires ECN/ECT set on all packets */
#define TCP_CONG_NEEDS_ECN		BIT(1)
/* Require successfully negotiated AccECN capability */
#define TCP_CONG_NEEDS_ACCECN		BIT(2)
/* Use ECT(1) instead of ECT(0) while the CA is uninitialized */
#define TCP_CONG_ECT_1_NEGOTIATION	BIT(3)
/* Cannot fallback to RFC3168 during AccECN negotiation */
#define TCP_CONG_NO_FALLBACK_RFC3168	BIT(4)
```

（`include/net/tcp.h:1276`）

- **`TCP_CONG_NON_RESTRICTED`** 是权限位：没有它的算法，普通进程 `setsockopt(TCP_CONGESTION)` 会被拒（`tcp_cong.c:436`），只有 `CAP_NET_ADMIN` 能用。
- 后四个是 **AccECN（RFC 9000 风格的精确 ECN 反馈）** 引入的协商标志，v7.2.7 上比较新。它们决定连接建立时怎么协商 ECN 能力。

### Auto-load Modules

```c
static struct tcp_congestion_ops *tcp_ca_find_autoload(const char *name)
{
	struct tcp_congestion_ops *ca = tcp_ca_find(name);

#ifdef CONFIG_MODULES
	if (!ca && capable(CAP_NET_ADMIN)) {
		rcu_read_unlock();
		request_module("tcp_%s", name);
		rcu_read_lock();
		ca = tcp_ca_find(name);
	}
#endif
	return ca;
}
```

（`tcp_cong.c:50`）

算法编成模块时（如 `tcp_bbr.ko`），第一次按名字引用会自动 `request_module("tcp_bbr")`。注意这里的**临时释放 RCU 读锁再重新获取**——因为 `request_module` 可能睡眠，不能在 RCU 临界区里调用。另外只有 `CAP_NET_ADMIN` 能触发加载，防止普通用户通过反复请求不存在的模块来刷内核日志。

## Selecting Algorithms: Priority of Three Levels

一个连接最终用哪个算法，是三层决定的，越靠下优先级越高：

### 1. Compile-time Default -> `late_initcall`

```c
static int __init tcp_congestion_default(void)
{
	return tcp_set_default_congestion_control(&init_net,
						  CONFIG_DEFAULT_TCP_CONG);
}
late_initcall(tcp_congestion_default);
```

`CONFIG_DEFAULT_TCP_CONG` 来自 `net/ipv4/Kconfig`，v7.2.7 上**默认仍是 `cubic`**（`bbr` 是可选值之一）。

### 2. Per-netns Default -> sysctl

`net.ipv4.tcp_congestion_control` 走 `tcp_set_default_congestion_control()`（`tcp_cong.c:281`）：

```c
	} else if (!net_eq(net, &init_net) &&
			!(ca->flags & TCP_CONG_NON_RESTRICTED)) {
		/* Only init netns can set default to a restricted algorithm */
		ret = -EPERM;
	} else {
		prev = xchg(&net->ipv4.tcp_congestion_control, ca);
		if (prev)
			bpf_module_put(prev, prev->owner);

		ca->flags |= TCP_CONG_NON_RESTRICTED;
		ret = 0;
	}
```

两个细节：**非 init netns 不能把默认算法设成受限算法**；以及**一旦某个算法被设为某 netns 的默认，它就被标记为 NON_RESTRICTED**（因为这个 netns 里的所有 socket 都会用它，再限制就没意义了）。

### 3. Per-socket Default -> setsockopt

`TCP_CONGESTION` 走 `tcp_set_congestion_control()`（`tcp_cong.c:412`）。第一个检查就值得注意：

```c
	if (icsk->icsk_ca_dst_locked)
		return -EPERM;
```

`icsk_ca_dst_locked` 来自**路由 metric**——如果路由项上锁定了 `RTAX_CC_ALGO`（`ip route change ... congctl lock`），socket 就不能覆盖它。这让管理员可以按目的地址强制指定算法。

另外，如果请求的算法就是当前的，只置 `icsk_ca_setsockopt = 1` 而不重新初始化——这个标志用于 `ss` 显示"这条连接被显式设置过算法"。

还有一个容易被忽略的**白名单机制**：`net.ipv4.tcp_allowed_congestion_control` 通过 `tcp_set_allowed_congestion_control()`（`tcp_cong.c:369`）批量改写所有算法的 `NON_RESTRICTED` 位。实现是三趟：先校验所有名字都存在，再清空所有标志，最后按名单置位——保证不会因为中间出错留下半改状态。

### Side Effects of Binding: ECN Negotiation and Private Area Zeroing

```c
void tcp_assign_congestion_control(struct sock *sk)
{
	...
	rcu_read_lock();
	ca = rcu_dereference(net->ipv4.tcp_congestion_control);
	if (unlikely(!bpf_try_module_get(ca, ca->owner)))
		ca = &tcp_reno;
	icsk->icsk_ca_ops = ca;
	rcu_read_unlock();

	memset(icsk->icsk_ca_priv, 0, sizeof(icsk->icsk_ca_priv));
	if (ca->flags & TCP_CONG_NEEDS_ECN)
		INET_ECN_xmit_ect_1_negotiation(sk);
	else
		INET_ECN_dontxmit(sk);
}
```

（`tcp_cong.c:216`）

三点：模块引用拿不到就**回退到 Reno**（Reno 编译进内核，永远可用）；私有区 `icsk_ca_priv` 被清零（BBR 的 `struct bbr` 就放在这里，`BUILD_BUG_ON(sizeof(struct bbr) > ICSK_CA_PRIV_SIZE)` 保证不溢出）；按算法需求决定是否发起 ECN 协商。

## State Machine: The Five States of tcp_ca_state

### Definitions of the Five States

状态在 uAPI 头里（`include/uapi/linux/tcp.h:199`），因为它要通过 `tcp_info` 暴露给用户态：

| 状态 | 值 | 进入条件 |
| --- | --- | --- |
| **Open** | 0 | 默认。"最近没观察到坏事" |
| **Disorder** | 1 | 收到 DUPACK 或 SACK，可能是丢包也可能是乱序，**尚未确认** |
| **CWR** | 2 | 收到 ECN-ECE 标记，或发送端主机自身丢包（如 qdisc 丢） |
| **Recovery** | 3 | 快速恢复中，正在重传丢失的包，由 ACK 事件触发 |
| **Loss** | 4 | 由 **RTO 超时**触发的丢失恢复 |

**Disorder 这个状态存在本身就是一种谨慎**：收到重复 ACK 不等于丢包，也可能只是乱序。内核不立刻削减窗口，而是先标 Disorder 继续观察，等 RACK 或 dupthresh 给出更强的证据才进 Recovery。

### A Counterintuitive Fact: Loss Is Not in cwnd Reduction

```c
static inline bool tcp_in_cwnd_reduction(const struct sock *sk)
{
	return (TCPF_CA_CWR | TCPF_CA_Recovery) &
	       (1 << inet_csk(sk)->icsk_ca_state);
}
```

（`include/net/tcp.h:1538`）

`tcp_in_cwnd_reduction()` 只覆盖 **CWR 和 Recovery**，**不包括 Loss**。原因是 Loss 态的窗口处理走完全不同的路径——`tcp_enter_loss()` 直接把 cwnd 设成 `inflight + 1`（`tcp_input.c:2574`），彻底回到慢启动，不需要 PRR 那种"平滑削减"。所以"处于 cwnd reduction"和"处于非 Open 状态"是两个不同的判断。

### Three Entry Functions

**CWR**（`tcp_input.c:3030`）：

```c
void tcp_enter_cwr(struct sock *sk)
{
	struct tcp_sock *tp = tcp_sk(sk);

	tp->prior_ssthresh = 0;
	if (inet_csk(sk)->icsk_ca_state < TCP_CA_CWR) {
		tp->undo_marker = 0;
		tcp_init_cwnd_reduction(sk);
		tcp_set_ca_state(sk, TCP_CA_CWR);
	}
}
```

注意 `tp->undo_marker = 0`——**进入 CWR 时禁用 undo**。注释解释了理由：ECN 是**已被证明的拥塞**（网络明确报告了），不像 dupack 那样可能是误判。`tp->prior_ssthresh = 0` 同样是这个意思（undo 时要用 `prior_ssthresh` 恢复）。

**Recovery**（`tcp_input.c:3177`）：

```c
	tp->prior_ssthresh = 0;
	tcp_init_undo(tp);

	if (!tcp_in_cwnd_reduction(sk)) {
		if (!ece_ack)
			tp->prior_ssthresh = tcp_current_ssthresh(sk);
		tcp_init_cwnd_reduction(sk);
	}
	tcp_set_ca_state(sk, TCP_CA_Recovery);
```

对照 CWR 看差别很清楚：Recovery **保留** `prior_ssthresh`（除非是 ECE 触发的），所以要启用 undo；而且只在"当前不在削减中"时才初始化削减——避免在 Recovery 里再次进入时把状态重置。

**Loss**（`tcp_input.c:2554`）：

```c
	/* Reduce ssthresh if it has not yet been made inside this window. */
	if (icsk->icsk_ca_state <= TCP_CA_Disorder ||
	    !after(tp->high_seq, tp->snd_una) ||
	    (icsk->icsk_ca_state == TCP_CA_Loss && !icsk->icsk_retransmits)) {
		tp->prior_ssthresh = tcp_current_ssthresh(sk);
		tp->prior_cwnd = tcp_snd_cwnd(tp);
		WRITE_ONCE(tp->snd_ssthresh, icsk->icsk_ca_ops->ssthresh(sk));
		tcp_ca_event(sk, CA_EVENT_LOSS);
		tcp_init_undo(tp);
	}
	tcp_snd_cwnd_set(tp, tcp_packets_in_flight(tp) + 1);
```

这就是**调用算法 `ssthresh` 回调的地方**——`WRITE_ONCE(tp->snd_ssthresh, icsk->icsk_ca_ops->ssthresh(sk))`。Reno 的实现是 `max(cwnd >> 1, 2)`，CUBIC 是自己的 β 折算。条件判断保证"同一个窗口内只削减一次 ssthresh"。

### The Full Picture of State Transitions

`tcp_set_ca_state()`（`tcp_cong.c:38`）是唯一的设置入口，它会先通知算法：

```c
void tcp_set_ca_state(struct sock *sk, const u8 ca_state)
{
	struct inet_connection_sock *icsk = inet_csk(sk);

	trace_tcp_cong_state_set(sk, ca_state);

	if (icsk->icsk_ca_ops->set_state)
		icsk->icsk_ca_ops->set_state(sk, ca_state);
	icsk->icsk_ca_state = ca_state;
}
```

**先回调算法，再改状态**——这样算法在 `set_state` 里还能读到旧状态。BBR 的 `bbr_set_state()` 就靠这个：它只在 `new_state == TCP_CA_Loss` 时动作，清空 `full_bw` 让模型重新收敛。

退出路径有两条：`tcp_try_to_open()`（`tcp_input.c:3057`，正常 ACK 处理里）和 undo 路径（下面一节）。

## Classic Path: What Happens in the cong_avoid Branch

### Scheduling Points

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

（`tcp_input.c:3858`）

这就是整个框架的分水岭：**有 `cong_control` 就整体接管；否则内核按状态机在"削减"和"增窗"之间二选一**，最后用通用公式算 pacing。

### The Gate Before Window Growth: tcp_is_cwnd_limited

Reno/CUBIC 的 `cong_avoid` 开头都有这个判断：

```c
static inline bool tcp_is_cwnd_limited(const struct sock *sk)
{
	const struct tcp_sock *tp = tcp_sk(sk);

	if (tp->is_cwnd_limited)
		return true;

	/* If in slow start, ensure cwnd grows to twice what was ACKed. */
	if (tcp_in_slow_start(tp))
		return tcp_snd_cwnd(tp) < 2 * tp->max_packets_out;

	return false;
}
```

（`include/net/tcp.h:1593`）

**这是防止"应用没数据"时虚增 cwnd 的关键**。如果连接是 app-limited 的（应用发得慢，窗口根本没用满），此时 ACK 回来不代表网络有能力承受更多，增窗就是在积累一个假的大窗口，等到某刻应用突然大量发送就会一次性灌进网络。

`is_cwnd_limited` 这个标志由 `tcp_cwnd_validate()`（`tcp_output.c:2156`）在发送侧维护——**按窗口（window）而不是按 ACK 更新**：只在 `snd_una` 越过 `cwnd_usage_seq`（即一个完整窗口被确认完）时才重置，记录这一轮里 `packets_out` 的最大值。

慢启动时有放宽：注释说明"cwnd 允许涨到已确认量的两倍"——因为慢启动本来就冒着 100% 过冲的风险，放宽一点可以让 app-limited 的连接更激进地探测带宽，同时 discourages 应用靠发填充包人为撑大 cwnd。

### Slow Start: tcp_slow_start

```c
__bpf_kfunc u32 tcp_slow_start(struct tcp_sock *tp, u32 acked)
{
	u32 cwnd = min(tcp_snd_cwnd(tp) + acked, tp->snd_ssthresh);

	acked -= cwnd - tcp_snd_cwnd(tp);
	tcp_snd_cwnd_set(tp, min(cwnd, tp->snd_cwnd_clamp));

	return acked;
}
```

（`tcp_cong.c:456`）

很短，但有两个要点：

1. **cwnd 被 `snd_ssthresh` 截断，多出来的 acked 被返回给调用者**。Reno 的 `cong_avoid` 拿到这个剩余量继续走拥塞避免——这就是注释里说的"slow start exits when cwnd grows over ssthresh and returns the leftover acks"。
2. **一次 stretch ACK 的处理**。注释（447-454 行）解释：一个确认了 N 个包的 stretch ACK 被当作 N 个度为 1 的 ACK 连续处理。这里刻意**不实现 RFC 3465 的 ABC（Appropriate Byte Counting）**，因为它会把 N 限制到 2 从而减缓慢启动；内核的做法是"一个包只有被完整确认才算"，以防御该 RFC 描述的 ACK 攻击。

### Congestion Avoidance: tcp_cong_avoid_ai

AIMD 里的"加性增"在整数上怎么实现？答案是**信用计数**：

```c
__bpf_kfunc void tcp_cong_avoid_ai(struct tcp_sock *tp, u32 w, u32 acked)
{
	/* If credits accumulated at a higher w, apply them gently now. */
	if (tp->snd_cwnd_cnt >= w) {
		tp->snd_cwnd_cnt = 0;
		tcp_snd_cwnd_set(tp, tcp_snd_cwnd(tp) + 1);
	}

	tp->snd_cwnd_cnt += acked;
	if (tp->snd_cwnd_cnt >= w) {
		u32 delta = tp->snd_cwnd_cnt / w;

		tp->snd_cwnd_cnt -= delta * w;
		tcp_snd_cwnd_set(tp, tcp_snd_cwnd(tp) + delta);
	}
	tcp_snd_cwnd_set(tp, min(tcp_snd_cwnd(tp), tp->snd_cwnd_clamp));
}
```

（`tcp_cong.c:470`）

`snd_cwnd_cnt` 累加被确认的包数，每攒够 `w`（通常就是当前 cwnd）个就给 cwnd 加 1——这就是 `cwnd += 1/cwnd` 每包的定点实现，避免了浮点。

开头那个 `if (tp->snd_cwnd_cnt >= w)` 分支处理的是**窗口变小的情况**：如果之前在大窗口下攒了信用，现在 `w` 变小了，不能一次性全兑换（那会瞬间把 cwnd 顶上去），而是只加 1 并清零，重新开始攒。

### Reno: Fallback Implementation

```c
struct tcp_congestion_ops tcp_reno = {
	.flags		= TCP_CONG_NON_RESTRICTED,
	.name		= "reno",
	.owner		= THIS_MODULE,
	.ssthresh	= tcp_reno_ssthresh,
	.cong_avoid	= tcp_reno_cong_avoid,
	.undo_cwnd	= tcp_reno_undo_cwnd,
};
```

Reno 编译在内核里、永远可用，是所有失败场景的兜底（前面 `tcp_assign_congestion_control()` 里模块拿不到就回退到它）。它的三个回调都极简：ssthresh 砍半（最小 2）、cong_avoid 是慢启动 + AIMD、undo_cwnd 取 `max(cwnd, prior_cwnd)`。

## Window Reduction: PRR Algorithm

CWR 和 Recovery 期间的 cwnd 不是"砍一刀然后等着"，而是用 **PRR（Proportional Rate Reduction，RFC 6937）** 平滑地降下来。注释在 `tcp_input.c:2962` 讲得很清楚：

```c
void tcp_cwnd_reduction(struct sock *sk, int newly_acked_sacked, int newly_lost, int flag)
{
	struct tcp_sock *tp = tcp_sk(sk);
	int sndcnt = 0;
	int delta = tp->snd_ssthresh - tcp_packets_in_flight(tp);

	if (newly_acked_sacked <= 0 || WARN_ON_ONCE(!tp->prior_cwnd))
		return;

	tp->prr_delivered += newly_acked_sacked;
	if (delta < 0) {
		u64 dividend = (u64)tp->snd_ssthresh * tp->prr_delivered +
			       tp->prior_cwnd - 1;
		sndcnt = div_u64(dividend, tp->prior_cwnd) - tp->prr_out;
	} else {
		sndcnt = max_t(int, tp->prr_delivered - tp->prr_out,
			       newly_acked_sacked);
		if (flag & FLAG_SND_UNA_ADVANCED && !newly_lost)
			sndcnt++;
		sndcnt = min(delta, sndcnt);
	}
	/* Force a fast retransmit upon entering fast recovery */
	sndcnt = max(sndcnt, (tp->prr_out ? 0 : 1));
	tcp_snd_cwnd_set(tp, tcp_packets_in_flight(tp) + sndcnt);
}
```

（`tcp_input.c:2985`）

两个分支：

- **`delta < 0`（inflight 还大于 ssthresh）**——走 **PRR-SSRB**：削减被**摊到一个完整 RTT** 上完成，而不是瞬间砍到 ssthresh。公式 `ssthresh × prr_delivered / prior_cwnd - prr_out` 的含义是"按已交付比例，现在应该允许总共发出多少"。
- **`delta >= 0`（inflight 已经降到 ssthresh 以下）**——走 packet conservation：每确认 N 个就发 N 个。但如果 `SND_UNA` 前进了且没有新丢包，就额外 +1（慢慢往 ssthresh 爬，加快恢复）。

最后那行 `sndcnt = max(sndcnt, (tp->prr_out ? 0 : 1))` 保证**进入快速恢复时至少能发一个包**（强制快速重传）。

为什么要这么麻烦？直接砍到 ssthresh 的问题在于：如果 inflight 远大于 ssthresh，一刀砍下去会让发送方**在一个 RTT 内完全停止发送**（因为 inflight 已经超过新的 cwnd），造成吞吐断崖和可能的 RTO。PRR 让这个下降过程分散到一个 RTT 里。

### Reduction Ends

```c
static inline void tcp_end_cwnd_reduction(struct sock *sk)
{
	struct tcp_sock *tp = tcp_sk(sk);

	if (inet_csk(sk)->icsk_ca_ops->cong_control)
		return;

	/* Reset cwnd to ssthresh in CWR or Recovery (unless it's undone) */
	if (tp->snd_ssthresh < TCP_INFINITE_SSTHRESH &&
	    (inet_csk(sk)->icsk_ca_state == TCP_CA_CWR || tp->undo_marker)) {
		tcp_snd_cwnd_set(tp, tp->snd_ssthresh);
		tp->snd_cwnd_stamp = tcp_jiffies32;
	}
	tcp_ca_event(sk, CA_EVENT_COMPLETE_CWR);
}
```

（`tcp_input.c:3013`）

又是那个 `cong_control` 提前返回——BBR 不参与任何这套逻辑。另外 `snd_ssthresh < TCP_INFINITE_SSTHRESH` 这个条件会跳过 BBR（它把 ssthresh 设成无穷大）。

## Undo: Reverse an Incorrect Reduction

拥塞控制最尴尬的处境是：**削减完发现其实没拥塞**。典型场景是 RTO 触发了削减，但随后发现原始包只是延迟到达（RTO 是虚假的）。内核为此准备了完整的 undo 机制。

三个字段构成 undo 的账本：

| 字段 | 含义 |
| --- | --- |
| `prior_cwnd` | 削减前的 cwnd |
| `prior_ssthresh` | 削减前的 ssthresh（`0` 表示"不可撤销"） |
| `undo_marker` | 削减发生时的 `snd_una`；`0` 表示未启用 |

核心函数（`tcp_input.c:2843`）：

```c
static void tcp_undo_cwnd_reduction(struct sock *sk, bool unmark_loss)
{
	...
	if (tp->prior_ssthresh) {
		const struct inet_connection_sock *icsk = inet_csk(sk);

		tcp_snd_cwnd_set(tp, icsk->icsk_ca_ops->undo_cwnd(sk));

		if (tp->prior_ssthresh > tp->snd_ssthresh) {
			WRITE_ONCE(tp->snd_ssthresh, tp->prior_ssthresh);
			tcp_ecn_withdraw_cwr(tp);
		}
	}
	tp->snd_cwnd_stamp = tcp_jiffies32;
	tp->undo_marker = 0;
	tp->rack.advanced = 1; /* Force RACK to re-exam losses */
}
```

**恢复多少由算法说了算**——`icsk->icsk_ca_ops->undo_cwnd(sk)`。Reno 返回 `max(cwnd, prior_cwnd)`；BBR 的 `bbr_undo_cwnd()` 除了返回当前 cwnd，还顺手清空 `full_bw` 让模型重新探测（`tcp_bbr.c:1091`）。

最后一行 `tp->rack.advanced = 1` 是和 RACK 的联动：撤销之后强制 RACK 重新检查一遍丢失判定，因为之前的判定是在"丢包了"这个（错误的）前提下做的。

四个触发 undo 的入口，对应四种"我们搞错了"的证据：

| 函数 | 触发条件 |
| --- | --- |
| `tcp_try_undo_recovery` | 恢复期内 `tcp_may_undo()` 成立（没重传或原始传输成功） |
| `tcp_try_undo_dsack` | **DSACK 确认了所有重传数据**——最强证据，说明根本没丢 |
| `tcp_try_undo_loss` | Loss 态下的 partial ACK，或 **F-RTO** 判定 RTO 是虚假的 |
| `tcp_try_undo_partial` | 部分 ACK 表明只有部分重传是必要的 |

DSACK 那条路径还顺带调整了 RACK 的重排窗口持久计数（`reo_wnd_persist`），让 RACK 下次更保守一些。

## ECN and Congestion Algorithm Interaction

ECN 是唯一一个"网络主动报告拥塞"的信号，比丢包更早也更明确。它在框架里有两处体现：

1. **算法声明需要 ECN**：`TCP_CONG_NEEDS_ECN` flag（DCTCP 就是典型）。`tcp_assign_congestion_control()` 见到这个 flag 就调用 `INET_ECN_xmit_ect_1_negotiation()` 发起协商；`tcp_init_congestion_control()` 之后按 `tcp_ca_needs_ecn()` 决定实际发包时是否打 ECT 标记。
2. **收到 CE 就进 CWR**：`tcp_try_to_open()` 里 `if (flag & FLAG_ECE) tcp_enter_cwr(sk);`。

前面提过，进 CWR 会**禁用 undo**（`undo_marker = 0`、`prior_ssthresh = 0`）——因为 ECN 是明确证据，不需要留后路。这是 ECN 与丢包在框架层面最重要的行为差异。

v7.2.7 上还新增了 **AccECN** 相关的四个 flag（`NEEDS_ACCECN` / `ECT_1_NEGOTIATION` / `NO_FALLBACK_RFC3168`），用于精确 ECN 反馈的协商。这部分较新，涉及 RFC 3168 与 AccECN 的回退规则。

## Observation and Debugging

```bash
# 已注册 / 允许 / 当前默认
cat /proc/sys/net/ipv4/tcp_available_congestion_control
cat /proc/sys/net/ipv4/tcp_allowed_congestion_control
cat /proc/sys/net/ipv4/tcp_congestion_control

# 切换（需要模块已加载或可自动加载）
sysctl -w net.ipv4.tcp_congestion_control=cubic

# 每条连接看算法与状态（tcpi_ca_state 就是那五个状态的值）
ss -ti
```

`ss -ti` 输出的 `cubic rto:... cwnd:... ssthresh:...` 里，开头的名字来自 `tcp_get_default_congestion_control()`，而 `cwnd` / `ssthresh` 来自 `tcp_info`。算法私有信息（如 BBR 的带宽与增益）走 `get_info` 回调 + `INET_DIAG_*` 扩展，各算法自己定义格式。

BPF struct_ops 是更进阶的观测与替换手段：`tcp_update_congestion_control()` 的存在就是为了支持运行时替换算法实现，v7.2.7 上 BBR 与 Reno 的多个回调都标了 `__bpf_kfunc`，可以被 BPF 程序直接调用。

## The Landscape of Algorithms

v7.2.7 的 `net/ipv4/` 下自带这些实现（`tcp_*.c`），Kconfig 里 `TCP_CONG_ADVANCED` 打开后可单独选：

| 算法 | 流派 | 特点 |
| --- | --- | --- |
| **reno** | 基于丢包 | 内置兜底，AIMD 基线 |
| **cubic** | 基于丢包 | **默认**。三次函数增窗，长肥管道友好 |
| **bic** | 基于丢包 | CUBIC 前身，二分搜索增窗 |
| **westwood** | 基于带宽估计 | 用 ACK 速率估带宽来设 ssthresh |
| **htcp** | 基于丢包 | Hamilton TCP，按 RTT 调整增窗速度 |
| **highspeed** | 基于丢包 | RFC 3649，为大 BDP 链路设计 |
| **hybla** | 基于丢包 | 为高延迟卫星链路补偿 RTT |
| **vegas** | **基于延迟** | 最早的延迟派，RTT 变大就退让 |
| **veno** | 混合 | 在 Reno 上叠加延迟判断，区分无线丢包 |
| **scalable** | 基于丢包 | 恒定倍率增窗，恢复快 |
| **lp** | 基于延迟 | Low Priority，后台流量用 |
| **nv** | 基于延迟 | 用延迟梯度做判断 |
| **yeah** | 混合 | 结合 Reno 与延迟估计 |
| **illinois** | 基于延迟 | 按 RTT 动态调整 α/β |
| **dctcp** | **基于 ECN** | 数据中心场景，需要 ECN |
| **cdg** | 基于延迟 | 延迟梯度 + 丢包回退 |
| **bbr** | **基于建模** | 测 BDP，不吃丢包信号 |

按信号源分就是四类：**丢包 / 延迟 / ECN / 建模**。历史脉络是从丢包（Reno 1988）→ 延迟（Vegas 1994）→ 建模（BBR 2016），中间大量混合方案试图兼得——但"延迟会随交叉流量变化"这个固有缺陷让纯延迟派始终没成为主流。

## Relationship with Other Notes

框架层本身不长，但它是理解具体算法的前提：

- **[BBR](/docs/CS/OS/Linux/net/TCP/BBR.md)** 是 `cong_control` 派的代表——注册了 `cong_control` 之后，`tcp_cong_control()` 里的削减与通用 pacing 全部被跳过。反过来读这两篇会更容易明白为什么 BBR 能对丢包"无动于衷"。
- **[CUBIC](/docs/CS/OS/Linux/net/TCP/TCP.md?id=cubic)** 是 `cong_avoid` 派的代表，吃完整套框架：慢启动 → AIMD → PRR → undo。
- **[Retransmission](/docs/CS/OS/Linux/net/TCP/Retransmission.md)** 讲"哪些包丢了"（RACK/TLP），本篇讲"知道之后怎么办"。两者的接口就是 `rate_sample` 结构与 `rs->losses`。
- [Connection_Setup](/docs/CS/OS/Linux/net/TCP/Connection_Setup.md) 里建连阶段的窗口初始化，是这套状态机的起点（`icsk_ca_state` 初始为 Open）。

## Links

- [socket](/docs/CS/OS/Linux/net/socket.md)
- [网络知识地图](/docs/CS/OS/Linux/net/README.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

- [RFC 5681: TCP Congestion Control](https://www.rfc-editor.org/rfc/rfc5681.html)
- [RFC 6937: Proportional Rate Reduction for TCP](https://www.rfc-editor.org/rfc/rfc6937.html)
- [RFC 8312: CUBIC for Fast Long-Distance Networks](https://www.rfc-editor.org/rfc/rfc8312.html)
- [RFC 3168: The Addition of Explicit Congestion Notification (ECN) to IP](https://www.rfc-editor.org/rfc/rfc3168.html)
- [RFC 3465: Appropriate Byte Counting for TCP Congestion Control](https://www.rfc-editor.org/rfc/rfc3465.html)
- [RFC 3522: The Eifel Detection Algorithm for TCP](https://www.rfc-editor.org/rfc/rfc3522.html)
- [Congestion Avoidance and Control (Jacobson, SIGCOMM 88)](https://ee.lbl.gov/papers/congavoid.pdf)
- [Linux Pluggable Congestion Control (docs.kernel.org)](https://docs.kernel.org/networking/index.html)
