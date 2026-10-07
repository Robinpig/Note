## Introduction

本目录收 Linux 内核里 **TCP 协议的实现笔记**，按连接生命周期组织。

为什么要单独拆一个子目录：TCP 是内核协议栈里唯一一个**自带状态机、自带重传计时器、自带拥塞控制插件体系**的传输层协议。`net/` 目录下其他笔记讲的都是"一个包怎么穿过去"（路由、邻居、qdisc、NAPI），而 TCP 关心的是另一件事——**在一条会丢包、会乱序、会拥塞的链路上，怎么让字节流既不丢也不乱，同时不吃垮网络**。前者是一次性的转发动作，后者是跨多个 RTT 的持续控制过程。

也正因为如此，TCP 的笔记不能按"收 / 发"二分，得按**一条连接从生到死的时间线**来看：建连 → 传数据 → 检测丢包与重传 → 拥塞控制 → 关闭。下面几节就沿这条线走。

另一个分工要说明：`docs/CS/CN/TCP/` 下的笔记讲的是**协议本身**（报文格式、状态机、为什么三次握手），本目录讲的是**Linux 怎么把它实现出来**（哪个函数发 SYN、重传计时器在哪个字段、拥塞算法怎么注册进来）。看协议概念去前者，看内核代码来这里。

## Connection Establishment: Which Functions the Handshake Lands On in the Kernel

三次握手在教科书上是三个箭头，在内核里是**两个进程各走一遍跨系统调用的路径**，中间还夹着一个只在握手期存在的临时对象。

客户端从 `connect()` 进入 `tcp_v4_connect()`，这里要做的第一件事不是发 SYN，而是**挑一个本地端口**——`inet_hash_connect()` 在 `ip_local_port_range` 里找空闲端口并完成哈希注册，端口耗尽就是在这里失败。随后 `tcp_connect()` 构造 SYN 报文、初始化重传计时器，把连接置为 `TCP_SYN_SENT`。

服务端这侧的入口完全不同：监听 socket 收到 SYN 后走 `tcp_conn_request()`，它**不创建完整 socket**，而是分配一个轻量的 `request_sock` 放进半连接队列（SYN queue），然后回 SYNACK，并挂上 `tcp_rtx_synack()` 负责 SYNACK 的重传——因为此时还没有任何重传状态可用。等到最后一个 ACK 到达，`tcp_check_req()` 才真正创建 `sock`，由 `inet_csk_complete_hashdance()` 完成从半连接队列到全连接队列的"哈希接力"，`accept()` 才能取到它。

这条路径上**两个队列的长度**（`tcp_max_syn_backlog` 与 listen backlog）决定了抗 SYN flood 的能力，`tcp_syncookies` 则是在半连接队列被打满时彻底不分配 `request_sock` 的兜底方案。完整追踪见 [Connection_Setup](/docs/CS/OS/Linux/net/TCP/Connection_Setup.md)。

## Data Transfer: Windows and Queues in Both Directions

连建好之后，剩下的问题就是"**能发多少**"和"**收到的怎么交给用户**"。

发送侧的核心是 `tcp_write_xmit()`，它在一个循环里反复问三个问题：还能发多少（拥塞窗口 cwnd 与对端通告窗口 rwnd 取小）、发哪个（重传队列优先还是新数据）、一次发几个（TSO/GSO 允许的段数）。窗口的选择逻辑单独在 [Window](/docs/CS/OS/Linux/net/TCP/TCP.md?id=window) 一节——这里的微妙之处在于**通告窗口要考虑接收缓冲的可用空间，还要避免糊涂窗口综合征**，不是简单报个数字。真正的报文构造与发出在 `tcp_transmit_skb()`。

接收侧 `tcp_rcv_established()` 是热路径，它按"快速路径 / 慢速路径"分流：理想情况（按序到达、无异常标志）直接在当前上下文里把数据放进接收队列、发 ACK；一旦出现乱序、紧急数据、窗口变化等，就退到慢速路径做完整处理。数据落地后 `tcp_queue_rcv()` 入队、`sk_data_ready` 唤醒等待的进程，而用户态 `recv()` 阻塞在 `sk_wait_data()` 上。这两半见 [Send](/docs/CS/OS/Linux/net/TCP/TCP.md?id=send) 与 [Recv](/docs/CS/OS/Linux/net/TCP/TCP.md?id=recv)。

窗口底下那块**内存**另有一套独立账本，见 [Buffer](/docs/CS/OS/Linux/net/TCP/Buffer.md)：`sysctl_tcp_mem` 三档（low/pressure/hard）怎么拦分配、`sk_forward_alloc` 为什么按页批量预取、sndbuf 的自动扩展、以及接收侧 **DRS** 怎样靠"应用实际读走多少字节"反推缓冲该多大。三个要点：

1. **`SO_SNDBUF` / `SO_RCVBUF` 会锁死自动调优**。一旦 `setsockopt` 设过，`SOCK_SNDBUF_LOCK` 置位，`tcp_sndbuf_expand()` 被跳过、内存压力下的收缩也直接返回——在高 BDP 链路上手动设大缓冲区**往往反而更慢**。
2. **字节数 ≠ 内存量**。skb 的 `truesize` 与 `len` 的比值随 TSO/GRO 剧烈变化，v7.2.7 用 per-socket 动态测量的 `scaling_ratio` 换算，**旧的 `sysctl_tcp_adv_win_scale` 已经不参与这个换算了**（sysctl 还在，但 `tcp_win_from_space()` 不看它）。
3. **内存核算受全局与 memcg 双重约束**，任一超限都拒绝分配；但低于最小缓冲（`tcp_wmem[0]`）的连接在压力下仍被放行。

## Packet Loss and Retransmission: RTO Is the Fallback, Not the Main Force

TCP 判断"包丢了"有三类判据，按代价从高到低是：**超时**（等满一个 RTO，连接停摆）、**重复 ACK 计数**（数够 N 个才算）、**时间序推断**（看这个包比已被确认的包早发多久）。

理解它们的关键在于——**RTO 是最后手段，不是主要机制**。整条重传链的设计目标是"在 RTO 到点之前把丢包判出来"，所以真正要回答的是两个问题：RTO 那个超时值凭什么是这个数？以及除了干等，还有哪些更早的信号？

[Retransmission](/docs/CS/OS/Linux/net/TCP/Retransmission.md) 一篇完整覆盖这条链：RTT 怎么测（`tcp_rtt_estimator()` 的定点放大、mdev/rttvar 的非对称收敛、Karn 校正在 Linux 的两处落地）→ RTO 怎么算（srtt + rttvar、上下界）→ 超时后退避与放弃的**真实判据**（不是"重传 N 次"，而是"时间预算耗尽"）→ SACK 计分板的六态状态机与 DSACK → RACK 的时间域判据与自适应重排窗口 → TLP 怎么处理尾包丢失。

三个反直觉的点值得先记住：

1. **v7.2.7 上 RACK 与 TLP 是默认开启的**（`tcp_ipv4.c:3474-3475`）。`tcp_identify_packet_loss()` 只在连接不支持 SACK 时才退回 dupthresh，所以教科书那套"三个重复 ACK 触发快速重传"已经不是主路径。
2. **放弃连接看的是时间不是次数**。`tcp_retries2 = 15` 不是重传 15 次，而是"从第一次重传起，超过 15 次指数退避的时间预算"（默认约 15 分钟）。
3. **RTO / TLP / RACK 重排超时共用同一个定时器**，靠 `icsk_pending` 区分——同一时刻只有一个在跑，所以每次切换都要重新武装并补偿已流逝的时间。

[TCP](/docs/CS/OS/Linux/net/TCP/TCP.md?id=retry) 的 `## retry` 一节有 `tcp_write_timeout()` 的代码摘录，可与上一篇对照着看（注意那一段是旧版本代码，差异见该节标注）。

## Congestion Control: A Plugin System with Two Schools

内核把拥塞算法做成了**可插拔的接口**：`tcp_congestion_ops` 定义一组回调（`cong_avoid`、`ssthresh`、`undo_cwnd`、`set_state` 等），各算法注册进全局表，运行时按 sysctl 或 `setsockopt(TCP_CONGESTION)` 逐连接选择。

[Congestion](/docs/CS/OS/Linux/net/TCP/Congestion.md) 一篇讲这层框架：注册与校验（哪些回调必选）、三层选择优先级（编译期默认 → 每 netns sysctl → 每 socket setsockopt，且路由可锁死）、`tcp_ca_state` 五态状态机、PRR 削减、以及 **undo 机制**（削减错了怎么撤销）。框架侧代码摘录见 [Congestion Control Interface](/docs/CS/OS/Linux/net/TCP/TCP.md?id=congestion-control-interface)。

三个反直觉的点：

1. **`tcp_in_cwnd_reduction()` 不含 Loss 态**——它只覆盖 CWR 和 Recovery。Loss 态走的是完全不同的路径（直接 `cwnd = inflight + 1` 回慢启动），不需要 PRR。
2. **进 CWR 会禁用 undo，进 Recovery 不会**。因为 ECN 是网络明确报告的拥塞，而 dupack 可能是误判。
3. **增窗前要先过 `tcp_is_cwnd_limited()` 这道门**。app-limited 时 ACK 回来不代表网络有能力承受更多，放行会把 cwnd 虚增成一个定时炸弹。

两种流派的差别是根本性的：

- **基于丢包**（Reno / CUBIC）——把丢包当作拥塞信号，加性增、乘性减。CUBIC 用三次函数替代线性增长，让长肥管道能更快回到窗口上限，是 Linux 多年默认。[CUBIC](/docs/CS/OS/Linux/net/TCP/TCP.md?id=cubic) 一节有源码级展开。
- **基于建模**（BBR）——不去猜丢包，而是**主动估计路径的带宽与最小 RTT**（BDP），按这个模型决定发送速率与 pacing。它能在有随机丢包的链路上跑满带宽，代价是需要 fq qdisc 配合做 pacing，且对公平性的争论一直没停。

[BBR](/docs/CS/OS/Linux/net/TCP/BBR.md) 一篇按 `tcp_bbr.c` 展开：BtlBw（10 个 round 的 windowed max）与 RTprop（10 秒 windowed min）为什么必须分片测量 → 定点数单位 `BW_SCALE`/`BBR_SCALE` → **packet-timed round** 这个不用墙钟的时间基准 → 四态状态机与两套增益（`pacing_gain` 管发多快、`cwnd_gain` 管上界）→ PROBE_BW 的 8 相增益循环为什么平均下来恰好是 1.0 → EDT 感知的 inflight 修正 → ACK 聚合补偿与 policer 检测。

四个容易搞错的点：

1. **速率由 pacing 决定，cwnd 只是安全上界**。这两个是分开的两个增益，BBR 甚至把 `snd_ssthresh` 设成 `TCP_INFINITE_SSTHRESH`——它根本没有"慢启动阈值"这个概念。
2. **`cong_control` 一旦注册就完全接管**。`tcp_cong_control()` 里 `cong_control` 分支是 `return`，内核的 `tcp_cwnd_reduction()` 和 `tcp_update_pacing_rate()` 都不会跑。
3. **BBR 对丢包几乎不做乘性减**。丢包时只在恢复第一轮做 packet conservation，退出时还原 `prior_cwnd`；RTO 进 Loss 态的唯一动作是清空 `full_bw` 让模型重新收敛。
4. **主线只有 BBR v1**。v7.2.7 的 `net/ipv4/` 下只有 `tcp_bbr.c`，BBRv2/v3 从未合入主线——讨论公平性争议时必须指定版本。

## Close: Why Must Stay 2xMSL

连接不能一说再见就忘掉。主动关闭方发 FIN 后进入 FIN_WAIT，收到对端 FIN+ACK 后进入 **TIME_WAIT** 并保持 `tcp_fin_time()`（约 60 秒），原因有二：**让最后一个 ACK 有机会重传**（若对端没收到会重发 FIN），以及**让本次连接的残留报文在网络中消散**，否则复用同样四元组的新连接会收到旧包。

TIME_WAIT 期间 socket 已经销毁，但内核保留一个轻量的 timewait 控制块来处理迟到的报文（`tcp_timewait_state_process()`）。对服务器而言，大量 TIME_WAIT 是正常的——它是正确性的代价，不是泄漏。主动与被动关闭的两条完整路径见 [Active Close](/docs/CS/OS/Linux/net/TCP/TCP.md?id=active-close) 与 [Passive Close](/docs/CS/OS/Linux/net/TCP/TCP.md?id=passive-close)。

## Links

- [socket](/docs/CS/OS/Linux/net/socket.md)
- [network](/docs/CS/OS/Linux/net/network.md)
- [NAPI](/docs/CS/OS/Linux/net/NAPI.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)
- [nginx](/docs/CS/CN/nginx/nginx.md) — 监听队列 / backlog 的工程侧，四层 TCP 转发见 [stream](/docs/CS/CN/nginx/stream.md)

## References

- [RFC 9293: Transmission Control Protocol](https://www.rfc-editor.org/rfc/rfc9293.html)
- [Linux networking documentation](https://docs.kernel.org/networking/index.html)
