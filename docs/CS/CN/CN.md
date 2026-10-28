## Introduction

[计算机网络](https://en.wikipedia.org/wiki/Computer_network)（computer network）是一组由网络节点提供或位于网络节点上的、共享资源的计算机。
这些计算机通过通用的通信协议在数字化的互联链路上相互通信。
互联链路由电信网络技术构成，可以是有线、光纤，也可以是无线射频，并组织成各种网络拓扑。

## Knowledge Map

本目录的阅读顺序建议自顶向下：先用下面各章建立分层模型与端到端论证的直觉，再按工作需要下沉到具体协议的专题页。

**应用层**的入口是 [HTTP](/docs/CS/CN/HTTP/HTTP.md)——消息格式、连接管理、版本演进都从它展开，其下设五个分册：[HTTPS](/docs/CS/CN/HTTP/HTTPS.md) 把 TLS 插进 HTTP 与 TCP 之间并算清握手的 RTT 成本，[QUIC](/docs/CS/CN/HTTP/QUIC.md) 是 HTTP/3 的传输底座，[HOL](/docs/CS/CN/HTTP/HOL.md) 解释队头阻塞这一限制 HTTP 演进的关键约束，[OAuth](/docs/CS/CN/HTTP/OAuth.md) 与 [Security](/docs/CS/CN/HTTP/Security.md) 分别覆盖授权框架与浏览器侧安全头。名称解析走 [DNS](/docs/CS/CN/DNS.md)，地址分配走 [DHCP](/docs/CS/CN/DHCP.md)，文件与邮件传输是 [FTP](/docs/CS/CN/FTP.md) 与 [SMTP](/docs/CS/CN/SMTP.md)（附件编码看 [MIME](/docs/CS/CN/MIME.md)），全双工推送看 [WebSocket](/docs/CS/CN/WebSocket.md)；把万级并发连接作为一类工程问题单独讨论的是 [C10k](/docs/CS/CN/C10k.md)。

**传输层**的主体是 [TCP](/docs/CS/CN/TCP/TCP.md)——状态机、重传、窗口与拥塞控制的全貌；拥塞控制另立 [Congestion](/docs/CS/CN/TCP/Congestion.md) 存放算法专题与经典论文。与 TCP 并列的另外两种传输语义：[UDP](/docs/CS/CN/UDP.md) 轻量不可靠，[SCTP](/docs/CS/CN/SCTP.md) 面向多宿主与多流消息。而套接字 API 的统一入口是 [Socket](/docs/CS/CN/Socket.md)，select/poll/epoll 的 I/O 模型演进与它同主线，配合 [MultiIO](/docs/CS/CN/MultiIO.md) 阅读。

**网络层与链路层**由三页支撑：[IP](/docs/CS/CN/IP.md) 管寻址与转发，[ICMP](/docs/CS/CN/ICMP.md) 管控制报文与诊断，[ARP](/docs/CS/CN/ARP.md) 管 IP 到 MAC 的解析。

**安全**是一条横切主线：[TLS](/docs/CS/CN/TLS.md) 是协议本身（各版本差异与握手细节），[Security](/docs/CS/CN/Security.md) 是防护视角的总览，[Attack](/docs/CS/CN/Attack.md) 从攻击面反推防御，[VPN](/docs/CS/CN/VPN.md) 覆盖远程接入与隧道；学科框架见 [CyberSecurity](/docs/CS/CN/CyberSecurity/CyberSecurity.md)，其下按密码学原语、PKI、防火墙、IDS/IPS、恶意软件、认证协议、无线安全七个分册展开。

**服务器与代理**是本目录最大的工程分支：[nginx](/docs/CS/CN/nginx/nginx.md) 是其下全部专题的唯一枢纽，事件循环、内存池、upstream、缓存、TLS 各有专篇，各代代理的系统性对比在 [compare](/docs/CS/CN/nginx/compare.md)。同代或同类的还有四层能力更细的 [HAProxy](/docs/CS/CN/Tools/HAProxy.md)、配置极简的 [Caddy](/docs/CS/CN/Caddy.md)、Rust 重写的 [Pingora](/docs/CS/CN/Pingora.md)；负载均衡的通用概念收敛在 [Load Balance](/docs/CS/CN/Load%20Balance.md)。排查工具集中在 Tools 目录：抓包看 [tcpdump](/docs/CS/CN/Tools/tcpdump.md) 与 [WireShark](/docs/CS/CN/Tools/WireShark.md)，防火墙与连接跟踪看 [netfilter](/docs/CS/CN/Tools/netfilter.md)，抓包分析平台看 [Xcap](/docs/CS/CN/Tools/Xcap.md)。运维层面的方法论——分层视角、五大故障分类、监控三视角、告警收敛与拓扑定位——单独成篇：[Ops](/docs/CS/CN/Ops.md)。

## Computer Networks and the Internet

### Network Protocols

> 协议（protocol）定义了两个或多个通信实体之间交换报文的格式与顺序，以及报文传输和/或接收时（或其他事件发生时）所采取的动作。——Kurose & Ross 的经典定义

协议是计算机网络的核心抽象：发送方与接收方必须对「报文长什么样、按什么顺序发、收到后做什么」达成一致，通信才可能进行。
围绕协议有两个贯穿全篇的概念：

- **PDU（Protocol Data Unit，协议数据单元）**：某一层协议处理的数据单位，即该层的报文（如链路层的帧、网络层的数据报、传输层的报文段）。
- **SDU（Service Data Unit，服务数据单元）**：上层交给本层的数据，加上本层的头部（有时还有尾部）后成为本层的 PDU——一层输出的 PDU 是下一层的 SDU。

### The Network Edge

越来越多的非传统「物」（things）正作为端系统（end system）接入互联网。
端系统也称**主机（host）**。
主机常进一步分为两类：**客户端（client）**与**服务器（server）**。

### The Network Core

网络核心（network core）是由分组交换机与链路组成的网格，把互联网的端系统互连起来。
端系统接入网络的方式主要有两类，对应核心中两种交换范式：

**电路交换（Circuit Switching）**

- 低时延（链路资源预留，排队可忽略）
- 保序（同一电路上的比特按序到达）
- 无冲突（独占资源，不会互相碰撞）

**分组交换（Packet Switching）**

- 无连接（每个分组独立选路，不事先建立电路）
- 高可靠（路由冗余，单点故障可绕行）
- 有转发时延（存储转发：每个分组要在交换机排队并整体收下才能发出）

### Packet Switching Delay

一个分组从源主机出发，经过一系列路由器，最终到达另一台目的主机。
分组沿路径从一个节点（主机或路由器）传到下一个节点时，在每个节点都会遭受几种时延。
其中最重要的是**结点处理时延**、**排队时延**、**传输时延**和**传播时延**，它们累加为总的结点时延：

- 检查分组首部、决定把分组导向何处所需的时间属于**处理时延** $d_{proc}$。
- 分组在队列中等待发送到链路上时经历**排队时延** $d_{queue}$，其长度取决于队列中早已到达、正在等待传输的分组数量。
- **传输时延** $d_{trans}$ 是路由器把分组全部推入链路所需的时间，只与分组长度和链路传输速率有关，与两台路由器间的距离无关。
- **传播时延** $d_{prop}$ 则是一个比特从一台路由器传播到下一台所需的时间，只与距离有关，与分组长度和链路速率无关。

若用 $d_{proc}$、$d_{queue}$、$d_{trans}$、$d_{prop}$ 分别表示这四种时延，则总结点时延为

$$
d_{nodal}=d_{proc}+d_{queue}+d_{trans}+d_{prop}

$$

结点时延中最复杂、最有意思的成分是排队时延 $d_{queue}$。记流量强度（traffic intensity）为 $La/R$（$a$ 为分组平均到达率，$L$ 为分组长度，$R$ 为链路速率）：

> [!TIP]
>
> 设计系统时，让流量强度不大于 1。

当流量强度接近 1 时，平均排队时延会急剧上升——强度的小幅百分比增长会带来时延大得多的百分比增长。
丢包率也随流量强度上升。因此结点的性能通常不仅用时延衡量，也用丢包概率衡量。

### Performance

评价网络性能的常用维度：

- Speed（速率）——链路每秒能传多少比特
- Bandwidth（带宽）——链路上限速率
- Throughput（吞吐量）——端到端实际达到的速率
- Delay（时延）——上面四种时延的累加
- RTT（Round-Trip Time，往返时延）——报文到达对端再返回的总时间

### Network Model

#### OSI Model

描述网络分层的一种通用方式是国际标准化组织（ISO）的开放系统互连（OSI）模型。
七层从下到上依次为：物理层、链路层、网络层、传输层、会话层、表示层、应用层。

> [!TIP]
>
> 一张图看懂各层协议分布：[科来-网络通信协议图-2020](http://www.colasoft.com.cn/download/network-protocol-map-2020.pdf)

应用可以绕过传输层直接使用 IPv4/IPv6，这称为**原始套接字（raw socket）**。

OSI 模型的上三层在互联网协议栈中被合并为一个**应用层**——它就是 Web 客户端（浏览器）、Telnet 客户端、Web 服务器、FTP 服务器等我们正在使用的程序。
使用互联网协议时，上三层几乎不做区分。

本书讲述的[套接字编程接口](/docs/CS/CN/Socket.md)，正是上三层（应用层）进入传输层的接口。
为什么套接字恰好提供「上三层 → 传输层」的接口？

- 其一，上三层处理应用的全部细节（FTP、Telnet、HTTP 等），对通信细节知之甚少；下四层则对应用一无所知，却包办了所有通信细节：发送数据、等待确认、重排乱序到达的数据、计算并校验校验和等。
- 其二，上三层通常构成所谓的**用户进程**，而下四层一般由操作系统内核提供。Unix 以及许多同时代的操作系统都提供了这种用户进程与内核的分离。

因此，第 4 层与第 5 层之间的界面是构建 API 的自然位置。




## Application Layer

网络应用是计算机网络存在的理由（raison d'être）。

应用层协议分布在多个端系统上：一个端系统中的应用使用该协议与另一个端系统中的应用交换信息。
我们把应用层的这个信息包称为**报文（message）**。

- [Dynamic Host Configuration Protocol](/docs/CS/CN/DHCP.md)——地址自动分配
- [FTP](/docs/CS/CN/FTP.md)、[SMTP](/docs/CS/CN/SMTP.md)——文件传输与邮件传输（附件编码看 [MIME](/docs/CS/CN/MIME.md)）

### HTTP

[超文本传输协议（HTTP）](/docs/CS/CN/HTTP/HTTP.md) 是一个应用层协议，为分布式协作式超媒体信息系统提供所需的轻量与速度。

### DNS

[DNS](/docs/CS/CN/DNS.md) 是一个分布式客户机/服务器网络数据库，TCP/IP 应用用它来在主机名与 IP 地址之间互相映射（反之亦然），
并提供邮件路由信息、服务命名等能力。

### Websocket

[WebSocket](/docs/CS/CN/WebSocket.md)——全双工的长连接推送，见专页。

## Transport Layer

传输层协议为运行在不同主机上的应用进程提供**逻辑通信**。
所谓逻辑通信，是指从应用的视角看，两台运行进程的主机好像直接相连；实际上它们可能在地球两端，中间隔着无数路由器与各种链路类型。
应用进程借助传输层提供的逻辑通信互发报文，无须关心承载这些报文的物理基础设施细节。
传输层的数据包称为**报文段（segment）**。

传输层协议只在端系统中实现，不在网络路由器中实现。
发送侧，传输层把从发送应用进程收到的应用层报文转换成传输层分组（即报文段）：可能把应用报文切成小块，给每块加上传输层首部。
然后传输层把报文段交给网络层，封装成网络层分组（数据报）发往目的地。
注意：**网络路由器只作用于数据报的网络层字段，不检查封装在内的传输层报文段字段**。
接收侧，网络层从数据报中取出传输层报文段上交传输层，传输层处理该报文段，把其中的数据提供给接收应用。

传输协议能提供的服务常受底层网络层协议服务模型的约束：
如果网络层不能为端主机间的报文段提供时延或带宽保证，传输层也就无法为应用报文提供相应保证。

不过，有些服务即使底层网络协议不提供，传输层仍能提供。例如：

- 底层网络协议不可靠（丢包、损坏、重复）时，传输层仍能向应用提供**可靠数据传输**；
- 网络层无法保证机密性时，传输层仍能用加密保证应用报文不被入侵者读取。

主流传输协议的能力对照：

|                    | [TCP](/docs/CS/CN/TCP/TCP.md)                                                       | [UDP](/docs/CS/CN/UDP.md)    |
| -------------------- | --------------------------------------------------------------------------------- | ------------------------------ |
| 连接性         | 面向连接                                                                     | 无连接               |
| 可靠性        | 确认、序号、RTT 估计、超时、重传 | 无                           |
| 流量控制       | 有                                                                             | 无                           |
| 拥塞控制 | 有                                                                             | 无                           |
| 全双工        | 有                                                                             | 可以                       |
| 通信模式        | 一对一                                                                      | 一对一 / 一对多 |

任意时刻，多个进程可以共用同一种传输协议：[UDP](/docs/CS/CN/UDP.md)、[SCTP](/docs/CS/CN/SCTP.md) 或 [TCP](/docs/CS/CN/TCP/TCP.md)。
三者的传输层都用 16 位整数端口号来区分这些进程。

### Multiplexing and Demultiplexing

接收主机如何把收到的传输层报文段导向正确的套接字？
每个报文段有一组用于此目的的字段：接收侧传输层检查这些字段，识别出接收套接字，再把报文段交给它。
把报文段中的数据交付到正确套接字的工作称为**分用（demultiplexing）**；
在源主机把不同套接字的数据块收集起来、各自加上首部信息（供后续分用）打成报文段、再交给网络层的工作称为**复用（multiplexing）**。

传输层实现分用的一种方式：给主机中每个套接字分配一个**端口号**，报文段到达时传输层检查其目的端口号，把报文段导向对应套接字，数据经套接字进入绑定的进程。
UDP 基本就是这样做的；而 TCP 的复用/分用还要更精细（见 [TCP 专页](/docs/CS/CN/TCP/TCP.md)）。

### Reliable Data Transfer

校验和、序号、定时器以及肯定/否定确认报文，在协议运行中各司其职又缺一不可。

发送方不必停下来等待确认，而可以连续发送多个分组——由于在途的发送方到接收方分组可以被想象成填满一条流水线，这种技术称为**流水线（pipelining）**。
流水线对可靠数据传输协议带来以下影响：

- 序号范围必须扩大：每个在途分组（不含重传）都要有唯一序号，在途未确认的分组可能有多个。
- 协议两端可能需要缓存多个分组：发送方至少要缓存已发送但未确认的分组；接收方也可能需要缓存已正确收到的分组。
- 序号范围与缓存需求取决于协议如何应对丢失、损坏和过度延迟的分组。流水线的差错恢复有两大基本思路：**Go-Back-N（GBN）**与**选择重传（selective repeat）**。

在 GBN 协议中，发送方可以连续发送多个分组（在有数据时），但在途未确认分组数不得超过一个上限 N。
N 常称为**窗口长度（window size）**，GBN 协议本身也称为**滑动窗口协议（sliding-window protocol）**。

为什么不允许无限多个在途分组？
原因之一是流量控制——必须限制发送方的发送速率；
另一个原因见 [TCP 拥塞控制](/docs/CS/CN/TCP/Congestion.md)。

GBN 发送方必须响应三类事件：

- 上层调用（有数据要发）。
- 收到 ACK。GBN 中序号为 n 的确认被理解为**累积确认**，表明序号不超过 n 的所有分组都已被正确接收。
- 超时事件。

GBN 允许发送方「填满流水线」，从而避免了停等方式的信道利用率问题。
但 GBN 自身也有性能隐患：当窗口长度与带宽时延积都很大时，流水线里可以容纳很多分组，**一个分组的差错就可能触发大量不必要的重传**；信道差错率越高，流水线越容易被这些无谓重传占满。

**可靠数据传输机制及其用途一览**

| 机制 | 用途与说明 |
| --- | --- |
| 校验和 | 检测传输分组中的比特差错。 |
| 定时器 | 超时并重传分组（分组或其 ACK 可能在信道中丢失）。 |
| 序号 | 给发送方到接收方的数据分组顺序编号；接收端序号的缺口让接收方检测到分组丢失，重复的序号让接收方检测到重复副本。 |
| 确认 | 接收方告知发送方一个或一组分组已被正确接收；确认通常携带被确认分组的序号，可以是个别的或累积的，取决于协议。 |
| 否定确认 | 接收方告知发送方某分组未被正确接收；通常携带未被正确接收的分组序号。 |
| 窗口、流水线 | 发送方只能发送序号落在给定范围内的分组；允许多个分组在途未确认，使发送方利用率高于停等方式。 |

可靠数据传输协议的经典参考：

- [RFC 908 - Reliable Data Protocol](https://datatracker.ietf.org/doc/rfc908/)
- [RFC 1151 - Version 2 of the Reliable Data Protocol (RDP)](https://datatracker.ietf.org/doc/rfc1151/)

### Connection

#### Connectionless

注意：[UDP](/docs/CS/CN/UDP.md) 套接字完全由一个二元组（目的 IP 地址 + 目的端口号）标识。
因此，若两个 UDP 报文段的源 IP/源端口不同但目的 IP 与目的端口相同，它们会被导向同一个目的套接字、交给同一个进程。

#### Connection-Oriented

[TCP](/docs/CS/CN/TCP/TCP.md) 连接的套接字对（socket pair）是定义连接两端点的四元组：本地 IP、本地端口、外部 IP、外部端口。
一个套接字对在全网唯一确定一条 TCP 连接。
SCTP 的关联（association）则由一组本地 IP、一个本地端口、一组外部 IP 和一个外部端口标识；
在最简单的双宿主（非 multihomed）形式下与 TCP 的四元组相同，但任一端多宿主时，同一个关联可能对应多组四元组（IP 不同、端口相同）。

标识每个端点的两个值——IP 地址与端口号——合称一个**套接字（socket）**。

套接字对的概念也可以扩展到 UDP（尽管 UDP 无连接）。
讲述套接字函数（bind、connect、getpeername 等）时会说明各函数指定套接字对中的哪些值：
例如 bind 让应用为 TCP、UDP、SCTP 套接字指定本地 IP 与本地端口。
服务端要同时照看成千上万条连接时，select/poll/epoll 的 I/O 多路复用模型演进见 [I/O Multiplexing](/docs/CS/CN/MultiIO.md)。

## Network Layer

网络中的每一台主机和路由器都有一部分是网络层。
网络层可以分解为两个相互作用的部分：**数据平面（data-plane）**与**控制平面（control-plane）**。

数据平面是网络层的本地功能：决定从路由器某条输入链路到达的数据报（即网络层分组）如何被转发到该路由器的某条输出链路。
既包括传统的 IP 转发（依据数据报的目的地址），也包括广义转发（利用首部中多个字段的值执行转发及其他功能）。

控制平面是全网络范围的逻辑：决定数据报如何沿端到端路径在一系列路由器之间从源主机选路到目的主机。
包括路由算法，以及 OSPF、BGP 等当今互联网广泛使用的路由协议。
传统上，控制平面的路由协议与数据平面的转发功能在路由器内单体实现；
软件定义网络（SDN）则把控制平面功能实现为独立的远程服务（controller），显式分离数据平面与控制平面。

网络层的主要作用看似简单——把分组从发送主机搬到接收主机。为此可以识别出两个重要功能：

- **转发（Forwarding）**：路由器本地的动作，把分组从一条输入链路接口转移到合适的输出链路接口。
  转发发生在极短的时间尺度上（通常几纳秒），因此通常由硬件实现，是网络层数据平面的关键功能。
- **路由（Routing）**：全网范围的过程，决定分组从源到目的地所走的端到端路径。
  路由发生在长得多的时间尺度上（通常以秒计），通常由软件实现。

每台路由器中的关键部件是**转发表（forwarding table）**。
路由器转发分组时检查到达分组首部中一个或多个字段的值，用这些值索引转发表；表项中存的值指示该分组应从哪条输出链路接口发出。

### SDN

SDN（软件定义网络）把「怎么转发」（数据平面，交换机内）与「往哪转」（控制平面，远端控制器）显式分离：
控制器集中掌握全网拓扑与策略，通过南向接口（如 OpenFlow）向交换机下发流表。
由此带来可编程的网络控制、快速的策略部署，以及控制平面的集中化风险（单点故障需要多控制器集群缓解）。

### Routing Algorithms

网络层必须决定分组从发送方流向接收方时经过的路径，计算这些路径的算法称为**路由算法**。

第一种分类维度是集中式还是分散式：

- **集中式路由算法**用完整的全局网络知识计算源到目的地的最小费用路径。掌握全局状态信息的算法常称为**链路状态（LS）算法**，因为算法必须知道网络中每条链路的费用。
- **分散式路由算法**中，最小费用路径的计算以迭代、分布式的方式由路由器们共同完成。

第二种维度是静态还是动态；第三种维度是负载敏感（load-sensitive）还是负载不敏感（load-insensitive）。

#### The Link-State (LS) Routing Algorithm

回顾：链路状态算法中，网络拓扑与所有链路费用都是已知的，即作为 LS 算法的输入。
实践中由各路由器洪泛链路状态通告（LSA），每个节点据此构建一致的拓扑图，再运行 Dijkstra 最短路径算法。

#### The Distance-Vector (DV) Routing Algorithm

LS 算法使用全局信息，而距离向量（DV）算法是迭代、异步、分布式的。
分布式：每个节点从一个或多个直连邻居接收信息，执行计算，再把计算结果分发回邻居。
迭代：这个过程不断持续，直到邻居之间不再交换信息（有趣的是算法会自行终止——没有任何信号通知计算停止，它自己就停了）。
异步：不要求所有节点锁步操作。
实践中即 RIP 与 BGP 的路径向量思想所本，代表性问题是计数到无穷大。

#### OSPF

OSPF（Open Shortest Path First）是内部网关协议（IGP），链路状态类型，运行在 IP 之上，按区域（area）分层收敛。

#### BGP

BGP（Border Gateway Protocol）是互联网事实上的域间路由协议，路径向量类型，在自治系统（AS）之间交换可达性信息与策略。

### IP

[Internet Protocol(IP)](/docs/CS/CN/IP.md)——寻址、分片、转发的基本约定，见专页。

本质上，启用 NAT 的路由器把家庭网络的细节对外部世界隐藏起来：对外只暴露一个公网地址，内网主机共享它出网。

### ICMP

[Internet Control Message Protocol](/docs/CS/CN/ICMP.md)——控制报文与诊断（ping/traceroute 的载体），见专页。

## Data Link Layer

本章把运行链路层（即第 2 层）协议的任何设备方便地称为**节点（node）**。
节点包括主机、路由器、交换机和 WiFi 接入点。
把通信路径上相邻节点之间的通信信道称为**链路（link）**。
在给定链路上，发送节点把网络层数据报封装进**链路层帧（link-layer frame）**，再把帧发送到链路中。

链路层协议可能提供的服务：

- **成帧（Framing）**：几乎所有链路层协议在传输前都把每个网络层数据报封装在链路层帧中。
- **链路接入（Link access）**：介质访问控制（MAC）协议规定帧发送到链路上的规则。
- **可靠交付（Reliable delivery）**：链路层提供可靠交付服务时，保证无差错地把每个网络层数据报搬过链路。
  常用于差错率高的链路（如无线），目的是就地纠正错误，而不是迫使传输层/应用层做端到端重传。
  但对光纤、同轴电缆和许多双绞铜线这类低误码链路，可靠交付是不必要的开销，因此许多有线链路层协议不提供该服务。
- **差错检测与纠正（Error detection and correction）**：比特差错由信号衰减与电磁噪声引入。
  互联网的传输层与网络层也提供有限形式的差错检测——互联网校验和；链路层的差错检测通常更复杂且由硬件实现。
  差错纠正在检测之外还能定位帧中错误发生的位置并予以纠正。

链路层大部分实现在**网络适配器（network adapter，又称网卡 NIC）**中。

### Error-Detection and Correction

一般而言，越复杂的差错检测/纠正技术（漏检比特差错的概率越小），开销越大——需要更多计算来算并传输更多的检错/纠错比特。

三种检测传输数据差错的技术：

- **奇偶校验（parity checks）**——说明差错检测与纠正的基本思想；
- **校验和（checksumming）**——更多用于传输层；
- **循环冗余检查（CRC）**——更多用于适配器中的链路层。

#### CRC

当今计算机网络广泛使用的差错检测技术基于**循环冗余码（CRC）**。
CRC 也称**多项式码（polynomial codes）**：把要发送的比特串看作一个多项式（系数为比特串中的 0/1），比特串上的运算解释为多项式算术。

### Multiple Access Links and Protocols

如何协调多个收发节点对一条共享广播信道的接入——**多路访问问题（multiple access problem）**。
计算机网络用相应的协议——**多路访问协议（multiple access protocols）**——来规范节点向共享广播信道的发送。

几乎任何多路访问协议都可归入三类之一：**信道划分协议**、**随机接入协议**与**轮流协议**。

理想情况下，对速率为 R bit/s 的广播信道，多路访问协议应有以下特性：

1. 只有一个节点要发送时，该节点吞吐量为 R bps。
2. M 个节点都要发送时，每个节点吞吐量为 R/M bps。
   这不要求每个节点瞬时速率都是 R/M，而是要求在一个适当定义的时间区间内平均传输速率为 R/M。
3. 协议是去中心化的：没有代表单点故障的主节点。
4. 协议简单，实现成本低。

#### Channel Partitioning Protocols

**时分复用（TDM）**与**频分复用（FDM）**是两种在共享信道所有节点间划分广播信道带宽的技术。
第三种信道划分协议是**码分多址（CDMA）**：TDM 与 FDM 分别给节点分配时隙与频率，CDMA 则给每个节点分配不同的编码。

#### Random Access Protocols

随机接入协议中，发送节点总是以信道的全速率 R bps 发送。
发生碰撞时，参与的每个节点反复重传其帧，直到帧无碰撞地通过。
但节点遭遇碰撞后不会立即重传，而是等待一个随机时延。
**碰撞涉及的每个节点选择相互独立的随机时延。**
正因为随机时延独立选择，有可能某个节点选中的时延足够小于其他碰撞节点，从而能把帧「溜」进信道而不发生碰撞。

- **ALOHA**：纯 ALOHA 与时隙 ALOHA，最早的随机接入协议，最大效率分别约 18% 与 37%。
- **CSMA（载波监听多路访问）**：发送前先监听信道（1-坚持、非坚持、p-坚持等变体），碰撞仍未避免时配合冲突检测（CSMA/CD，以太网）或碰撞避免（CSMA/CA，WiFi）。

#### Taking-Turns Protocols

**轮询协议（polling）**消除了困扰随机接入协议的碰撞与空时隙，因此能达到高得多的效率，但有两个缺点：

- 其一，协议引入轮询时延——通知某节点可以发送所需的时间；
- 其二（可能更严重），主节点故障时整个信道瘫痪。

第二种轮流协议是**令牌传递协议（token-passing）**：没有主节点，一个称为令牌（token）的特殊小帧在节点间按某种固定顺序传递，拿到令牌才有权发送。

### Link-Layer Addressing

[ARP: Address Resolution Protocol](/docs/CS/CN/ARP.md)——IP 地址到 MAC 地址的解析，见专页。

## Physical Layer

物理层关心比特在链路上的电气/光学表示：

- **serial / parallel**：串行传输（一位一位，抗干扰强、距离远）与并行传输（多位同时，需解决线间串扰，适合板内短距）。
- **Byte synchronization**：字节同步——接收方如何从比特流中划分字节边界。
- **async / sync**：异步传输（起止位定界，如 UART）与同步传输（共享时钟或时钟恢复，如同步以太网）。

### Signal

物理层把比特表示为可在信道上传输的信号：数字信号（方波、NRZ、曼彻斯特编码等）或模拟信号（ASK/FSK/PSK/QAM 调制），核心指标是带宽、信噪比与码元速率。

### Encoding

线路编码（如 4B/5B、8B/10B、PAM）在比特与电平/码元之间建立映射，兼顾直流平衡、时钟恢复与检错能力。

## Wireless and Mobile Networks

无线网络的组成元素：

- **无线主机（wireless hosts）**。
- **无线链路（wireless links）**。

有线链路与无线链路的重要差异：

- **信号强度衰减**：电磁辐射穿过物质时衰减（如无线电穿墙）；即使在自由空间，信号也会扩散，随收发双方距离增加而强度下降（称为**路径损耗 path loss**）。
- **来自其他源的干扰**：同频段发射的无线源会互相干扰；环境中的电磁噪声（附近的电机、微波炉）也会造成干扰。
- **多径传播（multipath propagation）**：电磁波的部分能量经物体和地面反射，以不同长度的路径到达接收方，导致接收信号模糊；收发之间移动的物体会使多径传播随时间变化。

**信噪比（signal-to-noise ratio, SNR）**是接收信号强度（所传信息）与噪声的相对度量，通常以分贝（dB）计。

**比特差错率（bit error rate, BER）**大致而言是传输的比特在接收端被收错的概率。

理解高层无线通信协议所需的几个物理层特性：

- 对给定调制方案，SNR 越高，BER 越低。
- 对给定 SNR，比特传输速率越高的调制技术，BER 越高。
- 可以动态选择物理层调制技术，使调制适配信道条件。

**码分多址（CDMA）**属于信道划分协议家族，广泛用于无线局域网与蜂窝技术。

### WiFi

**IEEE 802.11 无线局域网**，通称 **WiFi**。安全体制（WEP/WPA2/WPA3 与 KRACK、Dragonblood 等）见 [Wireless Security](/docs/CS/CN/CyberSecurity/Wireless_Security.md)。

## Networks Under Attack

[计算机安全](/docs/CS/CN/CyberSecurity/CyberSecurity.md)（computer security，又称 cybersecurity、digital security 或 IT security）是信息安全领域下的一个子学科，
研究如何保护计算机软件、系统与网络免受威胁——这些威胁可能导致未授权的信息泄露、硬件/软件/数据被窃取或损坏，以及服务被中断或误导。

### Malware

恶意软件的两大经典形态：

- **病毒（Viruses）**：依附于宿主程序传播，需要用户交互（打开文件、执行程序）才会感染。
- **蠕虫（Worms）**：自我复制、自主通过网络传播，无须用户交互，可在短时间内大规模扩散。

#### Attack Servers and Network Infrastructure

另一大类安全威胁是拒绝服务（DoS）攻击：

- **漏洞攻击（Vulnerability attack）**：利用协议或实现缺陷发送少量精心构造的报文使服务崩溃。
- **带宽洪泛（Bandwidth flooding）**：用海量流量塞满链路，耗尽受害者的接入带宽。
- **连接洪泛（Connection flooding）**：建立大量半开或完整连接，耗尽受害者的连接表/内存等资源。

### Sniff Packets

观察执行中的协议实体之间交换报文的基本工具称为**分组嗅探器（packet sniffer）**。
嗅探到的分组可以离线分析，从中提取敏感信息。
[Wireshark](/docs/CS/CN/Tools/WireShark.md) 就是这样一个分组嗅探器。

#### Masquerade as Someone You Trust

用虚假源地址向互联网注入分组的能力称为 **IP 欺骗（IP spoofing）**，
它是众多「一个用户冒充另一个用户」手法中的一种。

## Operations

分层运维视角、五大故障分类、故障发现与定位体系，以及 HAProxy 的快速上手另见 [Ops](/docs/CS/CN/Ops.md)；万级并发（C10K）与千万级并发（C10M）的调度问题见 [C10k](/docs/CS/CN/C10k.md)。

## Links

- [Operating Systems](/docs/CS/OS/OS.md)
- [Linux Networking](/docs/CS/OS/Linux/net/network.md)
- [Data Structures and Algorithms](/docs/CS/Algorithms/Algorithms.md)
- [Computer Organization](/docs/CS/CO/CO.md)

## References

1. [Computer Networking: A Top-Down Approach 8 edition](https://gaia.cs.umass.edu/kurose_ross/interactive/)
2. [Internet Assigned Numbers Authority](https://www.iana.org/)
