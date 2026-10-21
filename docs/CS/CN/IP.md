## Introduction

IP is the workhorse protocol of the TCP/IP protocol suite. All TCP, UDP, ICMP, and IGMP data gets transmitted as IP datagrams. 
**IP provides a best-effort, connectionless datagram delivery service.**

By “best-effort” we mean there are no guarantees that an IP datagram gets to its destination successfully. 
Although IP does not simply drop all traffic unnecessarily, it provides no guarantees as to the fate of the packets it attempts to deliver. 
When something goes wrong, such as a router temporarily running out of buffers, IP has a simple error-handling algorithm: throw away some data (usually the last datagram that arrived). 
Any required reliability must be provided by the upper layers (e.g., TCP). 
IPv4 and IPv6 both use this basic best-effort delivery model.

The term connectionless means that: 
- IP does not maintain any connection state information about related datagrams within the network elements (i.e., within the routers); each datagram is handled independently from all other others. 
- This also means that IP datagrams can be delivered out of order. 
- Other things can happen to IP datagrams as well: they may be duplicated in transit, and they may have their data altered as the result of errors. 

Again, some protocol above IP (usually TCP) has to handle all of these potential problems in order to provide an error-free delivery abstraction for applications.

The official specification for IPv4 is given in [RFC 791](https://datatracker.ietf.org/doc/html/rfc791). 
IPv6 is specified by [RFC 8200](https://datatracker.ietf.org/doc/html/rfc8200) (STD 86), which obsoleted RFC 2460.


## IPv4 and IPv6 Headers

IPv4 头部字段（RFC 791）：

| 字段 | 位数 | 说明 |
| --- | --- | --- |
| Version | 4 | 协议版本，IPv4 为 4 |
| IHL | 4 | 头部长度，以 32 bit 字为单位，最小为 5（即 20 字节） |
| DS | 8 | 区分服务字段；RFC 2474 起 = DSCP 6 bit + CU 2 bit，RFC 3168 把 CU 2 bit 用作 ECN：00 Not-ECT、10 ECT(0)、01 ECT(1)、11 CE |
| Total Length | 16 | 头部加数据的总字节数，最大 65535 |
| Identification | 16 | 标识被分片的同一原始数据报 |
| Flags | 3 | bit0 保留必须为 0；bit1 为 DF；bit2 为 MF |
| Fragment Offset | 13 | 分片在原始数据中的偏移，**以 8 字节为单位** |
| TTL | 8 | 每经一跳路由器减 1 |
| Protocol | 8 | 上层协议号：1 = ICMP、6 = TCP、17 = UDP |
| Header Checksum | 16 | 仅覆盖头部，逐跳重算 |
| Source Address | 32 | 源地址 |
| Destination Address | 32 | 目的地址 |

分片（fragmentation）：数据报超过链路 MTU 且未设置 DF 标志时才可能被分片，只有第一个分片带有 TCP/UDP 头部，重组只在目的主机进行。 
DF 置位而路由器又无法不分片转发时，路由器回 ICMP Destination Unreachable（type 3, code 4）——这是路径 MTU 发现（PMTUD）的基础。

The *Time-to-Live* field, or *TTL*, sets an upper limit on the number of routers through which a datagram can pass. 
It is initialized by the sender to some value (64 is recommended in [RFC 1122](https://datatracker.ietf.org/doc/html/rfc1122), although 128 or 255 is not uncommon) and decremented by 1 by every router that forwards the datagram. 
When this field reaches 0, the datagram is thrown away, and the sender is notified with an ICMP message. 
This prevents packets from getting caught in the network forever should an unwanted routing loop occur.



地址分类

| 地址 | 起始位 |      |
| ---- | ------ | ---- |
| A    | 0      |      |
| B    | 10     |      |
| C    | 110    |      |
| D    | 1110   |      |
| E    | 11110  |      |

缺陷：

同类地址无层次

地址资源没有和实际应用场景相适配，C类地址过少 B类地址过多

C类地址

主机号8bit

主机号为0代表某个网络

主机号全为1代表所有主机，用于组播



路由器默认不转发直接广播，只转发本地广播

D E类地址没有主机号

D类用于多播 E类暂未使用

前4位为1110为多播地址，即224.0.0.0 ~ 239.255.255.255



CIDR

a.b.c.d/x

/x 前x位为网络号



子网掩码&IP地址=网络号

子网地址号



MTU

MSS can be set through iptables while send SYNC

```shell
iptables -A FORWARD -p tcp --tcp-flags SYN SYN -j TCPMSS -set-mss 1400
```


Default unsupport fragment.




IPv6

IPv6 头部为固定的 40 字节：没有头部校验和（去掉了逐跳校验的负担，转发更快，但差错检测完全依赖上层协议），也不再由路由器分片——分片改由源主机通过 Fragment 扩展头完成；新增的 Flow Label 字段用于标识同一条流以便特殊处理。更多细节见 [Linux IPv6](/docs/CS/OS/Linux/net/IPv6.md)。


## Attacks Involving IP


Without authentication or encryption (or when it is disabled for IPv6), IP spoofing attacks are possible. 
常见缓解手段是入口过滤（ingress filtering，BCP 38 / RFC 2827）与 uRPF 检查；IPv6 同样没有内建的源地址认证机制。


## IPSec

IPsec 在 IP 层提供安全服务：传输模式（transport mode）保护上层载荷，隧道模式（tunnel mode）封装整个 IP 数据报，是 VPN 的常见基础。 
两个核心协议是 AH（协议号 51，提供认证与完整性）与 ESP（协议号 50，在认证之外提供加密）；安全参数由 IKEv2 协商建立。详细内容见 [Security](/docs/CS/CN/Security.md)。

## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [Linux IP](/docs/CS/OS/Linux/net/IP.md)

## References

1. [RFC 791 - Internet Protocol](https://datatracker.ietf.org/doc/html/rfc791)
1. [RFC 8200 - Internet Protocol, Version 6 (IPv6) Specification](https://datatracker.ietf.org/doc/html/rfc8200)
1. [RFC 1122 - Requirements for Internet Hosts — Communication Layers](https://datatracker.ietf.org/doc/html/rfc1122)
1. [RFC 2474 - Definition of the Differentiated Services Field (DS Field) in the IPv4 and IPv6 Headers](https://datatracker.ietf.org/doc/html/rfc2474)
1. [RFC 3168 - The Addition of Explicit Congestion Notification (ECN) to IP](https://datatracker.ietf.org/doc/html/rfc3168)
1. [RFC 2827 - Network Ingress Filtering: Defeating Denial of Service Attacks which employ IP Source Address Spoofing](https://datatracker.ietf.org/doc/html/rfc2827)
