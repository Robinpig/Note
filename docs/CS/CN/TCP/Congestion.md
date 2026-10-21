## Introduction

拥塞控制（congestion control）是发送端根据网络拥塞程度自适应调整发送速率的机制。它与流控制（flow control）回答两个不同的问题：流控制防止发送方压垮**接收方**，拥塞控制防止发送方压垮**网络**。两者的最终实现都是限制在途数据量——发送窗口取两者较小值：

$$
W = \min(cwnd,\; rwnd)
$$

其中 $rwnd$ 由接收方通告（流控制），$cwnd$（congestion window）由发送方依据对网络拥塞的推断自行维护（拥塞控制）。协议行为（状态机、重传、窗口管理）的主干在 [TCP](/docs/CS/CN/TCP/TCP.md)，内核实现见 [Linux TCP](/docs/CS/OS/Linux/net/TCP/TCP.md?id=congestion-control)。

## AIMD

经典 TCP 拥塞控制被概括为 **additive-increase / multiplicative-decrease（AIMD）**：每收到一个 ACK 就把 $cwnd$ 增加一点（加性增），一旦推断出丢包就把 $cwnd$ 减半（乘性减）。其稳态行为是锯齿形（sawtooth）——每个 RTT 线性爬升，遇丢包骤降，如此反复。AIMD 之所以是稳定与公平的折中：乘性减保证各连接快速让出带宽，加性增保证带宽利用缓慢回升，两者合力把多个竞争连接推向平等的带宽分配。

丢包是拥塞的信号而非原因：路由器缓存排满后丢弃报文，发送端只能以丢包作为拥塞的间接证据。这一推断在无线等非拥塞丢包场景下会误判，也是后来各代算法试图修正的核心假设。

## Slow Start and Congestion Avoidance

$cwnd$ 的调节分两个阶段，以**慢启动门限** $ssthresh$ 为界：

- **慢启动（slow start）**：连接开始（或超时重建）时 $cwnd$ 从一个 MSS 起，每经过一个 RTT **翻倍**（指数增长）。"慢"是相对于最终可达速率而言——初期增速其实最快。
- **拥塞避免（congestion avoidance）**：$cwnd$ 达到 $ssthresh$ 后改为每 RTT **线性**增长约一个 MSS，谨慎探测剩余带宽。

超时（timeout）被视为强拥塞信号：$ssthresh \leftarrow cwnd/2$，$cwnd \leftarrow 1\ \text{MSS}$，重新慢启动。

## Fast Retransmit and Fast Recovery

Reno 引入对**重复 ACK** 的快速反应，避免每次都跌回慢启动：收到 **3 个重复 ACK**（快重传触发条件，表明个别报文段丢失而非严重拥塞）时执行**快恢复**——$ssthresh \leftarrow cwnd/2$，$cwnd \leftarrow ssthresh$ 并维持在网络中继续注入报文，而不是回到 1 个 MSS。

Tahoe 只有慢启动（任何丢包都回到 $cwnd=1$）；Reno 加了快重传/快恢复；NewReno 进一步修正了快恢复对**多个**同时丢失报文段的处理（靠部分 ACK 推进）。这是早期三代算法的主要差别。

## Algorithm Evolution

内核中可插拔的拥塞控制算法（`tcp_congestion_control`）大致沿三条路线演进：

| 算法 | 思路 | 备注 |
| :-- | :-- | :-- |
| Reno / NewReno | 基于丢包的 AIMD | 经典基线，行为可预测 |
| Vegas | 基于 **RTT 变化**预判拥塞 | 在丢包前主动减速，与丢包型算法混跑时吃亏 |
| BIC / CUBIC | 二分搜索 + 三次函数增长 | **Linux 2.6.19 起的默认算法**；高带宽长时延管道下比 Reno 收敛快 |
| BBR | 基于**模型**（带宽 × RTT）主动探测 | Linux 4.9 引入；不把丢包当拥塞信号，抗随机丢包，但与 CUBIC 混跑有公平性争议 |

选型上的经验规则：内网低时延小管道用默认 CUBIC 即可；高带宽时延积（长肥管道）或存在非拥塞丢包（无线、跨国链路）的场景值得试 BBR；任何混合部署都要评估与既有 CUBIC 流量的公平性。

## Active Queue Management

路由器侧的配合机制是主动队列管理（AQM）：不等缓存排满再丢包，而是**提前**随机丢弃（RED 及其变种）或打标通知发送端（ECN）。对 TCP 的含义是：拥塞信号可以更平滑、更早到达，减少全局同步（多连接同时超时又同时恢复）造成的利用率震荡。

## Links

- [TCP](/docs/CS/CN/TCP/TCP.md)
- [Linux TCP](/docs/CS/OS/Linux/net/TCP/TCP.md)
- [Computer Network](/docs/CS/CN/CN.md)

## References

1. [TCP Congestion Control: A Systems Approach](https://tcpcc.systemsapproach.org/intro.html)
2. [Congestion Avoidance and Control](https://ee.lbl.gov/papers/congavoid.pdf)
3. [RFC 5348 - TCP Friendly Rate Control (TFRC): Protocol Specification](https://datatracker.ietf.org/doc/html/rfc5348)
4. [RFC 5681 - TCP Congestion Control](https://datatracker.ietf.org/doc/html/rfc5681)
5. [TCP拥塞控制 - DeepNoMind](https://mp.weixin.qq.com/mp/appmsgalbum?__biz=MzU2MTgxODgwNA==&action=getalbum&album_id=2460055314927255553&scene=173&subscene=&sessionid=svr_aa1205af5b5&enterid=1736050086&from_msgid=2247485888&from_itemidx=1&count=3&nolastread=1#wechat_redirect)
