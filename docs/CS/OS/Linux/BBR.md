## Introduction

BBR (Bottleneck Bandwidth and RTT) TCP congestion control aims to maximize network utilization and minimize queues.
It builds an explicit model of the bottleneck delivery rate and path round-trip propagation delay.
It tolerates packet loss and delay unrelated to congestion.
It can operate over LAN, WAN, cellular, wifi, or cable modem links.
It can coexist with flows that use loss-based congestion control, and can operate with shallow buffers, deep buffers, bufferbloat, policers, or AQM schemes that do not provide a delay signal.
It requires the fq("Fair Queue") pacing packet scheduler.

BBR congestion control computes the sending rate based on the delivery rate (throughput) estimated from ACKs.
In a nutshell:

On each ACK, update our model of the network path:
bottleneck_bandwidth = windowed_max(delivered / elapsed, 10 round trips)
min_rtt = windowed_min(rtt, 10 seconds)
pacing_rate = pacing_gain * bottleneck_bandwidth
cwnd = max(cwnd_gain * bottleneck_bandwidth * min_rtt, 4)

The core algorithm does not react directly to packet losses or delays, although BBR may adjust the size of next send per ACK when loss is observed, or adjust the sending rate if it estimates there is a traffic policer, in order to keep the drop rate reasonable.

Here is a state transition diagram for BBR:

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

A BBR flow starts in STARTUP, and ramps up its sending rate quickly.
When it estimates the pipe is full, it enters DRAIN to drain the queue.
In steady state a BBR flow only uses PROBE_BW and PROBE_RTT.
A long-lived BBR flow spends the vast majority of its time remaining(repeatedly) in PROBE_BW, fully probing and utilizing the pipe's bandwidth in a fair manner, with a small, bounded queue.
*If* a flow has been continuously sending for the entire min_rtt window, and hasn't seen an RTT sample that matches or decreases its min_rtt estimate for 10 seconds,
then it briefly enters PROBE_RTT to cut inflight to a minimum value to re-probe the path's two-way propagation delay (min_rtt).
When exiting PROBE_RTT, if we estimated that we reached the full bw of the pipe then we enter PROBE_BW; otherwise we enter STARTUP to try to fill the pipe.

BBR is described in detail in:
"BBR: Congestion-Based Congestion Control",
Neal Cardwell, Yuchung Cheng, C. Stephen Gunn, Soheil Hassas Yeganeh,
Van Jacobson. ACM Queue, Vol. 14 No. 5, September-October 2016.

There is a public e-mail list for discussing BBR development and testing: https://groups.google.com/forum/#!forum/bbr-dev

NOTE: BBR might be used with the fq qdisc ("man tc-fq") with pacing enabled, otherwise TCP stack falls back to an internal pacing using one high resolution timer per TCP socket and may use more resources.


Scale factor for rate in pkt/uSec unit to avoid truncation in bandwidth estimation. The rate unit ~= (1500 bytes / 1 usec / 2^24) ~= 715 bps.
This handles bandwidths from 0.06pps (715bps) to 256Mpps (3Tbps) in a u32.
Since the minimum window is >=4 packets, the lower bound isn't an issue. The upper bound isn't an issue with existing technologies.




## Links

- [Computer Network TCP](/docs/CS/CN/TCP.md)
- [Linux TCP](/docs/CS/OS/Linux/TCP.md)


## References

1. [BBR’ – An Implementation of Boleneck Bandwidth and Round-trip Time Congestion Control for ns-3](https://web.cs.wpi.edu/~claypool/papers/bbr-prime/claypool-final.pdf)