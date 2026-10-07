## Introduction

**Qdisc（queueing discipline，排队规则）是 Linux 在网卡发送队列（`netdev_queue`）与网卡驱动之间插入的一层调度器**。协议栈下发的 SKB 不会直接交给硬件，而是先 `enqueue` 进某个 qdisc，再由 qdisc 按自己的算法决定**先送谁、丢谁、限速到多少**。

为什么要这一层？多个进程 / 连接会同时往一张网卡发包，而网卡的发送能力有限。如果没有排队管理：

- 突发流量会瞬间撑爆驱动的环形队列，多余的包只能粗暴丢弃，导致缓冲膨胀（bufferbloat）或全局同步；
- 无法做**优先级**（让低延迟的小包插队）、**公平**（防止一条流占满带宽）、**整形**（把出口速率限制到指定值，如 tc 限速、云主机带宽）。

Qdisc 把"什么时候发、发哪个"的策略从协议栈里抽离出来，做成可插拔模块（`net/sched/sch_*.c`），用 `tc` 命令配置。

[network](/docs/CS/OS/Linux/net/network.md) 的 Egress 一章讲的是 `dev_queue_xmit → qdisc_run → sch_direct_xmit` 这条**驱动 qdisc 出队并发送**的机械过程；本篇聚焦 qdisc 内部——**入队时怎么分类调度、怎么整形、有哪些内置算法**。

## Position on the Send Path

```
协议栈 ip_local_out / neigh
        │
        ▼
 dev_queue_xmit ── netdev_core_pick_tx 选定发送队列 txq
        │            txq->qdisc 就是该队列挂的 qdisc
        ▼
   q->enqueue ?                        ◀── 本篇：有 enqueue 的可调度 qdisc
   ├─ 是：__dev_xmit_skb → qdisc_enqueue → qdisc_run
   └─ 否（空 qdisc）：直接 sch_direct_xmit，绕过排队
        │
        ▼
 __qdisc_run：循环 qdisc_restart
   dequeue_skb(q)  ── qdisc 自己决定出哪个包   ◀── 本篇
        │
        ▼
 sch_direct_xmit → dev_hard_start_xmit → ndo_start_xmit → DMA
```

关键分叉在 `dev_queue_xmit`：

```c
// net/core/dev.c
txq = netdev_core_pick_tx(dev, skb, sb_dev);
q = rcu_dereference_bh(txq->qdisc);

if (q->enqueue) {
    rc = __dev_xmit_skb(skb, q, dev, txq);   // 走排队
    goto out;
}
// q->enqueue == NULL：noop/enqueue-less qdisc，直接发送，不做调度
```

`enqueue` 回调是否存在，是"可调度 qdisc"与"空 qdisc（如 `noqueue`、回环设备）"的分水岭。

## Core Data Structures

每个 qdisc 是一个 `Qdisc` 对象，挂在某个发送队列上（多队列网卡通过 `mq` qdisc 让每个硬件队列再各挂一个子 qdisc）。

```c
// include/net/sch_generic.h
struct Qdisc {
	int 			(*enqueue)(struct sk_buff *skb,
				   struct Qdisc *sch,
				   struct sk_buff **to_free);
	struct sk_buff *	(*dequeue)(struct Qdisc *sch);
	struct sk_buff *	(*peek)(struct Qdisc *sch);
	unsigned int		flags;          /* TCQ_F_* */
	struct qdisc_size_table	*stab;
	struct gnet_stats_basic_sync bstats;  /* 收发包/字节统计 */
	struct gnet_stats_queue	qstats;       /* drop/overlimit/requeues */
	struct netdev_queue	*dev_queue;
	spinlock_t		busylock;
	seqcount_t		running;
	struct Qdisc		*next_sched;     /* 挂到 softnet_data output_queue */
	int			(*init)(struct Qdisc *sch, struct nlattr *opts,
				struct netlink_ext_attach_parms *);
	int			(*change)(struct Qdisc *, struct nlattr *, ...);
	int			(*dump)(struct Qdisc *, struct sk_buff *skb);
	...
};
```

三个核心回调刻画了一个排队规则：

- **enqueue**：包到来时怎么存。简单算法放进单一 FIFO，复杂算法（classful）先**分类**再放进对应子类的队列；
- **dequeue**：qdisc_run 要包时给哪个。这是调度策略真正生效的地方——从多个队列 / 流里挑一个；
- **peek**：不出队地查看下一个包。

可调度的发送工作量通过两种方式驱动：

- 当前进程直接在 `__qdisc_run` 里循环 dequeue 发送，直到配额（`dev_tx_weight`）用尽；
- 配额用尽或队列暂时无法发送（设备 busy）时，把 qdisc 通过 `next_sched` 挂到本 CPU `softnet_data->output_queue`，触发 `NET_TX_SOFTIRQ`，由 [net_tx_action](/docs/CS/OS/Linux/net/network.md?id=net_tx_action) 稍后继续 `qdisc_run`。

## Classless qdisc: classless

**Classless qdisc 不区分子类**，对所有包一视同仁（或只看包自身的优先级标记），结构简单，是绝大多数网卡的默认选择。

### pfifo_fast (Historical Default)

基于 skb 优先级（`skb->priority`，可由 IP header 的 TOS 字段映射）放入三个 band：

- 三个 band 是三个 FIFO，**永远先送 band 0，再 band 1，最后 band 2**；
- 高优先级（如交互式、低延迟）的包进 band 0 立刻插队到最前，band 2 只有在更高 band 为空时才被服务。

它提供了基础优先级，但**每个 band 内部不保证公平**，一条大流仍可能饿死同 band 的其它流，也没有主动队列管理。现代内核默认已改为 fq_codel。

### fq_codel (Modern Default)

**fq_codel = fair queueing + CoDel**，是当前内核的默认 qdisc（`CONFIG_DEFAULT_NET_SCH`），针对缓冲膨胀设计：

- **fair queue（FQ）**：按流哈希把包散到许多独立的 FIFO，按字节数做轮询/赤字调度，保证每条流公平分享出口带宽，一条打满带宽的流不会拖慢其它流；
- **CoDel（controlled delay）**：不再靠队列长度判断拥塞，而是**直接测量包在队列里的驻留时间（sojourn time）**。当最小排队延迟持续超过 target（默认 5ms），才开始以随时间增长的概率丢包；队列一恢复就停止。
- 对新流的前几个包优先调度（`sched_flow` 的 new-flow 机制），让刚建立的连接、请求-响应型小包（典型如网页、DNS）快速通过，降低交互延迟。

### fq

比 fq_codel 更强调**按流 pacing**。它是 TCP 内部 pacing 的内核侧实现伙伴（TCP 用 `sch_fq` 来精确控制每个包的发送时刻）：

- 每流维护发送时间，早于时间的包不发，从而实现 pacing（把拥塞窗口允许的突发均匀摊到一个 RTT 上），配合 BBR / EDT（earliest departure time）模型效果最好；
- 高优先级包（如本地环路、TCP 重传标记）有独立的高优先 band。

### tbf: Token Bucket Shaping

**TBF（token bucket filter）只做一件事——把发送速率整形到配置带宽**：

- 桶里以固定速率积累令牌，包发送要消耗对应字节数的令牌；令牌不够就排队等待；
- 允许短时突发（桶可积蓄一定令牌），但长期平均速率被严格限制。云主机按带宽 / 流量计费、容器限速常以它为底层。

## Classful qdisc: classful

**Classful qdisc 是一棵树**：根 qdisc 下挂多个 **class（类）**，每个类可以再挂自己的 qdisc 或子类，叶子类最终排队真实的包。配合**分类器（classifier，如 u32、fwmark、route）**把包归入不同类，从而对不同流量区别对待。

### HTB: Hierarchical Token Bucket

**HTB（hierarchical token bucket）是最常用的带宽管理 qdisc**，在 TBF 之上引入层级：

- 每个类设 `rate`（保证带宽）和 `ceil`（允许借用的上限）；
- 子类带宽不够时可向父类**借用空闲带宽**，父类再在其子类间仲裁；
- 典型用法：给不同用户 / 业务划固定带宽保底，空闲时互相借用、但不超过各自上限。

### Priority qdisc (prio)

pfifo_fast 的 classful 版本：固定三个 band，按过滤器分类，严格优先服务低 band。适合"语音/信令必须绝对优先、数据尽力而为"，但高优先级类持续有包时低优先类会被饿死。

### HFSC

用曲线而非单一速率描述服务，可以同时对带宽和延迟做保证，适合需要严格延迟 SLA 的场景，配置比 HTB 复杂。

## ingress qdisc: Special Node for the Ingress Direction

上面的 qdisc 都挂在 **egress（发送）**。接收方向默认没有排队调度（包由 NAPI 直接收上来），但内核提供了一个 **ingress qdisc**：

- 挂在设备的特殊 ingress 位置，对每个收到的帧调用一次，可以挂过滤器执行 **drop / redirect / mirred（镜像到另一设备）/ police（入向限速）**；
- 它不是真正排队（没有队列、不做调度），更像一个**只做裁决的钩子**，在协议栈处理前就过滤或重定向；
- 现代高性能入向处理更多直接用 **XDP**（驱动层，甚至网卡 offload），见 [eBPF](/docs/CS/OS/Linux/Tools/eBPF.md)。ingress qdisc 是 tc 侧的等价入口。

## Classifier and Actions

有类 qdisc / ingress qdisc 要靠**分类器（filter/classifier）**决定包进哪个类或执行什么动作：

- **u32**：直接匹配 IP/端口/协议位，最通用；
- **fw**：依据 `skb->mark`（`iptables -j MARK` / nft `meta mark` 设置）分类，把"哪些流量"的判断交给防火墙；
- **route**：依据路由结果分类；bpf：挂载 eBPF 程序做分类，灵活度最高；
- **动作（action）**：police 限速、mirred 重定向/镜像、vlan push/pop、nat 等，可在分类后执行。

## Interface with User Space: tc

所有 qdisc / class / filter 的增删改查通过 **`tc`（iproute2）** 命令完成，底层走 [netlink](/docs/CS/OS/Linux/net/netlink.md) 的 rtnetlink（`RTM_NEWQDISC`/`RTM_NEWTFILTER` 等）：

```bash
# 查看某网卡根 qdisc
tc qdisc show dev eth0

# 根挂 HTB
tc qdisc add dev eth0 root handle 1: htb default 20
# 类：1:1 总带宽 100mbit；1:10 保证 30mbit、上限 100mbit
tc class add dev eth0 parent 1: classid 1:1 htb rate 100mbit
tc class add dev eth0 parent 1:1 classid 1:10 htb rate 30mbit ceil 100mbit
# 叶子类下挂 fq_codel，避免一个类内部缓冲膨胀
tc qdisc add dev eth0 parent 1:10 fq_codel
# 源端口 5001 的流量归入 1:10
tc filter add dev eth0 protocol ip parent 1: prio 1 u32 \
  match ip sport 5001 0xffff flowid 1:10
```

实践要点：**做带宽整形时，叶子类下应再挂 fq_codel / fq 等无类 qdisc**——HTB 只负责把字节按配额发出去，类内部仍可能因 FIFO 排长队导致延迟。

统计可在 `tc -s qdisc show` 看每 qdisc 的 packets/bytes/drops/requeues，以及 fq_codel 的 maxpacket/ecn_mark，是排查"包被谁丢了"的直接入口。

## Links

- [network](/docs/CS/OS/Linux/net/network.md)
- [netlink](/docs/CS/OS/Linux/net/netlink.md)
- [netfilter](/docs/CS/OS/Linux/net/netfilter.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

- [Linux Advanced Routing & Traffic Control HOWTO](https://tldp.org/HOWTO/Adv-Routing-HOWTO/)
- [man tc(8) — Linux manual page](https://man7.org/linux/man-pages/man8/tc.8.html)
- [Controlling Queue Delay (CoDel), ACM Queue](https://queue.acm.org/detail.cfm?id=2209336)
