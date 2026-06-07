## 简介

BBR（瓶颈带宽和往返时间）TCP 拥塞控制旨在最大化网络利用率并最小化队列。
它构建了瓶颈传输速率和路径往返传播延迟的显式模型。
它容忍与拥塞无关的数据包丢失和延迟。
它可以在局域网、广域网、蜂窝网络、WiFi 或电缆调制解调器链路上运行。
它可以与使用基于丢失的拥塞控制的流共存，并且可以在浅缓冲区、深缓冲区、缓冲区膨胀、策略器或不提供延迟信号的 AQM 方案下运行。
它需要 fq（"公平队列"）速率节奏数据包调度器。

BBR 拥塞控制根据从 ACK 估计的传输速率（吞吐量）计算发送速率。
简而言之：

在每个 ACK 上，更新我们对网络路径的模型：
bottleneck_bandwidth = windowed_max(delivered / elapsed, 10 round trips)
min_rtt = windowed_min(rtt, 10 seconds)
pacing_rate = pacing_gain * bottleneck_bandwidth
cwnd = max(cwnd_gain * bottleneck_bandwidth * min_rtt, 4)

核心算法不直接对数据包丢失或延迟做出反应，尽管 BBR 可能在观察到丢失时调整每次 ACK 的下一次发送大小，或者如果估计存在流量策略器则调整发送速率，以保持丢包率合理。

以下是 BBR 的状态转换图：

```c
/*
*             |
*             V
*    +---> STARTUP  ----+
*    |        |         |
*    |        V         |
*    |      DRAIN   ----+
*    |        |         |
*    |        V         |
*    +---> PROBE_BW ----+
*    |      ^    |      |
*    |      |    |      |
*    |      +----+      |
*    |                  |
*    +---- PROBE_RTT <--+
*/
```

BBR 流从 STARTUP 开始，并快速增加其发送速率。
当它估计管道已满时，进入 DRAIN 以排空队列。
在稳定状态下，BBR 流仅使用 PROBE_BW 和 PROBE_RTT。
长期存在的 BBR 流绝大多数时间（重复地）停留在 PROBE_BW，以公平的方式充分探测和利用管道的带宽，并保持小而有限的队列。
*如果*一个流持续发送了整整一个 min_rtt 窗口，并且在 10 秒内没有看到匹配或降低其 min_rtt 估计的 RTT 样本，
则它会短暂进入 PROBE_RTT，将正在传输中的数据量减少到最小值，以重新探测路径的双向传播延迟（min_rtt）。
当退出 PROBE_RTT 时，如果我们估计已达到管道的满带宽，则进入 PROBE_BW；否则进入 STARTUP 以尝试填充管道。

BBR 的详细描述见：
"BBR: Congestion-Based Congestion Control",
Neal Cardwell, Yuchung Cheng, C. Stephen Gunn, Soheil Hassas Yeganeh,
Van Jacobson. ACM Queue, Vol. 14 No. 5, September-October 2016.

有一个用于讨论 BBR 开发和测试的公共邮件列表：https://groups.google.com/forum/#!forum/bbr-dev

注意：BBR 可能需要与启用节奏的 fq qdisc（"man tc-fq"）一起使用，否则 TCP 栈会退回到使用每个 TCP 套接字一个高分辨率定时器的内部节奏，这可能会使用更多资源。

以 pkt/uSec 为单位的速率缩放因子，以避免带宽估计中的截断。速率单位 ~= (1500 bytes / 1 usec / 2^24) ~= 715 bps。
这在 u32 中处理从 0.06pps（715bps）到 256Mpps（3Tbps）的带宽。
由于最小窗口 >= 4 个数据包，下限不是问题。上限对于现有技术来说也不是问题。

## 链接

- [计算机网络 TCP](/docs/CS/CN/TCP/TCP.md)
- [Linux TCP](/docs/CS/OS/Linux/net/TCP/TCP.md)

## 参考

1. [BBR – An Implementation of Bottleneck Bandwidth and Round-trip Time Congestion Control for ns-3](https://web.cs.wpi.edu/~claypool/papers/bbr-prime/claypool-final.pdf)
