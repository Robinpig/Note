## Introduction

网络排障要按协议层从下往上排查（"It's always DNS" 之前先排除物理/连通性）：链路层 → IP 层 → 传输层 → 应用层。本篇把常用工具按层归类，并给出最常用的命令组合。总工具索引见 [Tools](/docs/CS/OS/Linux/Tools/Tools.md)。

## Transport Layer

- **telnet**：纯文本 TCP 建连工具，现在主要用于探测"端口通不通、服务有没有监听"（能连上就说明 TCP 三次握手成功）：`telnet host 3306`，不带明文加密，不用于实际登录。
- **nc（netcat）**：网络界的瑞士军刀，既能建连也能监听：`nc -vz host 80` 端口扫描式探测；`nc -l 8080` 本机起监听做联调；还能传文件、发原始报文。
- **netstat/ss**：看连接四元组和监听状态。ss 是 netstat 的现代替代（直接读 netlink/sock_diag，快得多）：

```shell
netstat -ant          # 所有 TCP 连接、不反解名字（-n）、端口数字显示
ss -antp state time-wait | head
ss -s                 # 套接字汇总：established/timewait/ orphan 计数
ss -lntup             # 监听中的 TCP/UDP 进程
```

`-ant` 即 all/numeric/tcp；连接状态重点看 ESTABLISHED、TIME-WAIT（短连接过多会占满本地端口）、LISTEN；排查"服务起没起"先 `ss -lntp | grep :8080`。

- **iftop / nethogs**：iftop 按连接显示实时带宽（谁在跟谁通信、占多少）；nethogs 按进程统计带宽。

## IP Layer

- **ping（ICMP Echo）**：验证三层可达和 RTT；不通时不能简单判定主机挂了——很多防火墙和云主机默认禁 ICMP，要结合其他手段。
- **traceroute**：递增 TTL 触发沿途路由器回 ICMP Time Exceeded，逐跳显示路径。默认 UDP，用 `-I` 走 ICMP（更容易放行），`-T` 走 TCP：

```shell
traceroute -I example.com
mtr -rwbzc 100 example.com   # 结合 traceroute+ping，每跳统计丢包率/延迟分布
```

- **mtr**：持续探测，给出每一跳的 Loss%、Avg、StDev、各分位；定位"哪一跳开始丢包"比 traceroute 单次结果可靠得多（`-r` 报告模式，`-b` 同时显示 ASN/IP）。
- **ip（iproute2）**：取代 ifconfig/route：`ip addr`、`ip route`、`ip neigh`（ARP 表）、`ip -s link`（网卡计数/丢包）。

```shell
ip route get 8.8.8.8     # 查去目标实际走的源地址、网卡、网关
ip neigh                 # ARP/邻居表，排查二层异常
```

- 抓包 **tcpdump/Wireshark**：`tcpdump -i any -nn 'host 1.2.3.4 and tcp port 443' -w cap.pcap`，应用层问题抓包是最终裁判；HTTP API 调试用 [curl](/docs/CS/OS/Linux/Tools/curl.md)。

## Link Layer

- **ethtool**：查网卡硬件状态与驱动参数：

```shell
ethtool eth0            # 速率/双工/链路是否 up（Speed/Duplex/Link detected）
ethtool -S eth0 | grep -i err    # 网卡计数器：rx/tx errors、dropped、CRC
ethtool -i eth0         # 驱动/固件版本
ethtool -g eth0         # ring buffer 大小（丢包时调大）
ethtool -l eth0         # 队列数（与 RSS/CPU 中断均衡相关）
```

网卡层面的错误计数（CRC、fifo error）与 IP 层的丢包含义不同：CRC 错误多指向物理层（网线、光模块、双工协商），ring buffer 溢出（fifo/rx_dropped）指向内核来不及收包。

- **ip link / arp / arping**：二层状态与免费 ARP；原理见 [ARP](/docs/CS/CN/ARP.md)。
- **tc（iproute2）**：流量控制（Qdisc、HTB 限流、netem 模拟延迟丢包），压测构造弱网必备：`tc qdisc add dev eth0 root netem delay 100ms loss 1%`。

## Troubleshooting Path Quick Reference

```
网页打不开
 ├─ ip link/ethtool：网卡 up？物理错误？
 ├─ ping 网关 / ping 公网 IP：二层→三层哪段断
 ├─ mtr：哪一跳开始丢包
 ├─ dig/nslookup：DNS 解析对不对
 ├─ nc -vz host port：TCP 端口通不通
 ├─ ss -antp：本机连接状态、TIME_WAIT/CLOSE_WAIT 堆积
 ├─ openssl s_client -connect host:443：TLS 握手/证书
 └─ tcpdump：上述都正常时抓包看实际收发
```

## Links

- [Tools](/docs/CS/OS/Linux/Tools/Tools.md)
- [curl](/docs/CS/OS/Linux/Tools/curl.md)
- [Computer Network](/docs/CS/CN/CN.md)
- [ping 原理（ICMP）](/docs/CS/CN/ICMP.md)

## References

1. [Linux Advanced Routing & Traffic Control HOWTO](https://tldp.org/HOWTO/Adv-Routing-HOWTO/)
2. [tcpdump 手册](https://www.tcpdump.org/manpages/tcpdump.1.html)
