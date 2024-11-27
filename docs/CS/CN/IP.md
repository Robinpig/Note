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

The official specification for IPv4 is given in [RFC0791]. A series of RFCs describe IPv6, starting with [RFC2460].


## IPv4 and IPv6 Headers



The *Time-to-Live* field, or *TTL*, sets an upper limit on the number of routers through which a datagram can pass. 
It is initialized by the sender to some value (64 is recommended [RFC1122], although 128 or 255 is not uncommon) and decremented by 1 by every router that forwards the datagram. 
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




## Attacks Involving IP


Without authentication or encryption (or when it is disabled for IPv6), IP spoofing attacks are possible.


## IPSec





## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [Linux IP](/docs/CS/OS/Linux/net/IP.md)