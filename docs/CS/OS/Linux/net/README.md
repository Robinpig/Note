## Introduction

本目录是 Linux 内核**网络子系统**的笔记。Linux 实现了 TCP/IP 模型中的链路层、网络层与传输层：网卡驱动负责链路层收发，内核协议栈负责网络层与传输层，再向上通过 socket 接口把网络能力暴露给用户进程。各层共用的核心数据结构是 `sk_buff`（SKB）——它在整个收发路径上逐层被封装 / 解封装，而不是每层都拷贝一次。

想理解网络，主线是回答两个问题：**一个包怎么从用户进程走到网线（Egress / 发送），又怎么从网线回到用户进程（Ingress / 接收）**。下面的笔记就沿着这两条路径，外加协议与性能两个横切面组织。

## Send/Receive Main Line

入口是 **socket**。用户态的 `send()`/`recv()` 先落到 VFS 中的 socket 文件（sockfs），由 [socket](/docs/CS/OS/Linux/net/socket.md) 笔记承接——它梳理 `socket()`/`sock`/`sock_common` 等结构体、地址族（`sockaddr_in`）、SKB 与 `msghdr` 的布局，以及连接的哈希管理。socket 是协议无关的抽象层，真正的协议处理由注册进来的 `inet_stream_ops`（TCP）、`inet_dgram_ops`（UDP）等具体实现完成。

拿到数据后，发送路径在 [network](/docs/CS/OS/Linux/net/network.md) 的 Egress 一章逐层下行：`send → inet_sendmsg → ip_queue_xmit / ip_local_out →（邻居子系统）→ dev_queue_xmit`。其中 **qdisc**（排队规则）给设备发送队列做调度与整形——默认 fq_codel 按流公平并主动控制排队延迟，HTB/TBF 做层级带宽限速，详见 [Qdisc](/docs/CS/OS/Linux/net/Qdisc.md)。最终 `dev_hard_start_xmit → ndo_start_xmit` 交给网卡驱动把描述符（descriptor）挂到硬件环形队列上，由 DMA 发往网线。

接收方向相反，且是网络性能的关键。网卡收到帧后触发硬中断，中断上半部只做最小工作，随即通过 **NAPI** 关闭中断、把收割工作丢给软中断 `net_rx_action`（由 [ksoftirqd](/docs/CS/OS/Linux/Interrupt.md?id=softirq) 线程执行），用一次轮询批量收割多个包，避免每包一次中断的开销（否则高 PPS 下会陷入接收活锁）。之后 `netif_receive_skb → ip_rcv → ip_local_deliver`，在网络层完成路由与分片重组（见 [IP](/docs/CS/OS/Linux/net/IP.md)），再按协议号分发到传输层：UDP 走 [UDP](/docs/CS/OS/Linux/net/UDP.md) 的 `udp_rcv`，TCP 走 [TCP](/docs/CS/OS/Linux/net/TCP/TCP.md) 的接收路径，最终唤醒在等待队列上阻塞的用户进程（`sk_data_ready`）。

收包侧的机制细节——`napi_struct` 的状态机与 SCHED/MISSED 竞态、`net_rx_action` 的 budget 与 repoll 三条去路、GRO 如何挂在 NAPI 上攒批、以及 backlog 与 RPS 如何复用同一套抽象——单独成篇见 [NAPI](/docs/CS/OS/Linux/net/NAPI.md)。

## Routing and Next Hop

上面发送路径里 `ip_local_out` 之后、`dev_queue_xmit` 之前，实际还缺两环。**第一环是路由**：发包前先查内核的转发表 **FIB**（发送走 `ip_route_output`、接收走 `ip_route_input`），决定出口网卡与下一跳 IP——接收方向同时据此判断"本机收还是转发"。[Route](/docs/CS/OS/Linux/net/Route.md) 笔记梳理 LC-trie 最长前缀匹配、`fib_info` 下一跳、策略路由 `fib_rules`、ECMP 多路径。

**第二环是邻居**：路由只给了下一跳 IP，而帧要靠 MAC 才能在链路上送达。[Neighbor](/docs/CS/OS/Linux/net/Neighbor.md) 笔记讲解下一跳 MAC 的解析（IPv4 即 ARP）、NUD 状态机如何验证缓存可信、`hh_cache` 缓存帧头。两环合起来才闭环——**路由决定"发往哪个下一跳"，邻居决定"二层帧头填谁"**，随后才是 `dev_queue_xmit`。

## TCP Subtopics

TCP 是协议栈里最复杂的部分，独立放在 [TCP](/docs/CS/OS/Linux/net/TCP/README.md) 子目录，按连接生命周期拆分：

- **建连**：[Connection_Setup](/docs/CS/OS/Linux/net/TCP/Connection_Setup.md) 完整追踪三次握手在客户端与服务端两侧的内核流程——`connect → tcp_v4_connect`、服务端 `tcp_conn_request` 收 SYN 回 SYNACK、`tcp_check_req` 收最后一个 ACK 完成建连，以及半连接队列 / 全连接队列；
- **数据传输与状态机**：[TCP](/docs/CS/OS/Linux/net/TCP/TCP.md) 覆盖发送窗口、重传超时（RTO）、拥塞控制状态机（CUBIC）、主动 / 被动关闭与 TIME_WAIT、keepalive、Reset；
- **丢包与重传**：[Retransmission](/docs/CS/OS/Linux/net/TCP/Retransmission.md) 单独讲 RTT 测量与 RTO 计算、SACK 计分板与 DSACK、RACK 的时间域判据、TLP 尾包探测——这套机制决定"重传发生在哪个时刻"，是 TCP 里最反直觉的一块；
- **拥塞算法**：[BBR](/docs/CS/OS/Linux/net/TCP/BBR.md) 单独记录基于带宽与 RTT 建模的 BBR 思路，与基于丢包的 CUBIC 对照。

## Virtual Network Devices

容器和云里的"网卡"大多不是物理硬件，而是内核里注册的虚拟 `net_device`——没有 DMA / 中断，靠软件在内存里搬运 SKB。[Virtual](/docs/CS/OS/Linux/net/Virtual.md) 按用途串起它们的内核实现：**bridge** 是一台软件交换机（`br_handle_frame` 截走端口帧、fdb 做 MAC 学习与转发、STP 防环）；**veth pair** 的一头发出即从另一头收到，是把容器接回宿主网桥的"网线"；bonding/team 做网卡冗余与聚合、VLAN 划分二层域、**VXLAN** 把二层帧封进 UDP 跨主机组建 overlay。它们都是"`ndo_start_xmit` 里软件转发/封装、`netif_rx` 注入协议栈"这一模式的变体，是容器网络的地基。

## IPv6

现代网络逐渐以 IPv6 为主，它不是"更长的 IPv4"，而是重做了网络层。[IPv6](/docs/CS/OS/Linux/net/IPv6.md) 讲解固定 40 字节头 + 链式扩展头、独立的收发入口（`ipv6_rcv`/`ip6_xmit`）与 IPv6 路由表 fib6；其**邻居发现 NDP**（RS/RA/NS/NA，复用邻居子系统的 NUD 状态机）取代了 ARP，配合 RA 完成无状态地址自动配置 **SLAAC** 与重复地址检测 DAD。理解它才能跟上纯 v6 / 双栈环境。

## Control Feedback: ICMP

IP 层还需要一条"控制与反馈"回路，这就是 **ICMP**（协议号 1）。[ICMP](/docs/CS/OS/Linux/net/ICMP.md) 讲解报文类型（echo 的 ping、目的不可达、TTL 超时、重定向）、内核 `icmp_rcv` 如何应答 echo 并把差错交给对应 socket 的错误队列，以及靠"DF 置位 + ICMP fragmentation needed"实现的路径 MTU 发现（PMTUD）。完全封禁 ICMP 会让大包黑洞、连接莫名卡死，不能简单当成"诊断协议"。ICMPv6 则是 IPv6 NDP 的载体。

## Filtering and Connection Tracking

协议栈并不是只做"尽力转发"——在上述收发路径的固定位置，它通过 `NF_HOOK` 把包交给 **netfilter** 框架。[netfilter](/docs/CS/OS/Linux/net/netfilter.md) 笔记梳理五个挂载点（PRE_ROUTING/LOCAL_IN/FORWARD/LOCAL_OUT/POST_ROUTING）与两条收发路径的对应、回调如何按优先级串联、verdict 裁决，以及建立在其上的三大能力：**conntrack** 连接跟踪、NAT、iptables/nftables 前端。容器网络（Docker 端口映射、kube-proxy 负载均衡）就构建在这套机制上。

## Configuration Channel

前面看到的"路由表 / 网卡 / 邻居"都需要一个让用户态改到内核、并让内核反向通知变化的通道，这个通道就是 **netlink**。[netlink](/docs/CS/OS/Linux/net/netlink.md) 笔记讲解它作为 `AF_NETLINK` socket 的消息格式（`nlmsghdr` + TLV 属性 + 策略校验）、多播通知，以及最常用的 rtnetlink（`ip` 命令背后）与 generic netlink。理解 netlink 才能把"`ip route add` 一条命令如何落到 FIB"这条链补全。

## Performance and Protocol Cross-cutting

[network](/docs/CS/OS/Linux/net/network.md) 的 Optimization 一章给出调优入口：文件描述符与连接数上限（`fs.file-max` / `fs.nr_open` / `net.core.somaxconn`）；多核扩展 **RSS/RPS/RFS/XPS** 把中断、协议栈处理与缓存亲和性分散到多 CPU；**TSO/GSO/GRO** 等分段与聚合卸载让协议栈只处理少而大的 SKB。协议本身（非内核实现视角）可对照网络基础笔记：[IP](/docs/CS/CN/IP.md)、[UDP](/docs/CS/CN/UDP.md)、[TCP](/docs/CS/CN/TCP/TCP.md)。

内核视角要记住一点：网络收发本质是**中断 + 软中断 + 等待队列唤醒**驱动的生产者-消费者过程，与进程调度、内存分配（SKB 来自专门的 slab 分配）紧密耦合，并非孤立的协议代码。

这套机制在用户态最典型的落地就是 nginx：它在协议栈之上用少量 worker + epoll 事件循环承接海量连接，四层的 [stream](/docs/CS/CN/nginx/stream.md) 与三层的 [HTTP](/docs/CS/CN/nginx/HTTP.md) 是两套平行实现；[HTTP/3](/docs/CS/CN/nginx/http3.md) 更进一步——它绕开内核 TCP，在 worker 里自己实现了 QUIC 的可靠传输，内核只负责 UDP 收发。内核侧机制与 nginx 侧实现的逐项对照见 [Nginx Event](/docs/CS/CN/nginx/event.md) 与 [内核协同链路](/docs/CS/OS/Linux/Architecture.md)。

## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)
- [CS 总目录](/docs/CS/CS.md)
