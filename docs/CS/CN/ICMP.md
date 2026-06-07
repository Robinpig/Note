## 简介

ICMP 处理路由器和主机之间的错误和控制信息。
这些消息通常由 TCP/IP 网络软件本身生成和处理，而非用户进程，不过我们也会展示使用 ICMP 的 ping 和 traceroute 程序。
我们有时将此协议称为 ICMPv4，以区别于 ICMPv6。

[IP 协议](/docs/CS/CN/IP.md)本身不提供任何直接方式让终端系统了解未能到达目的地的 IP 数据包的命运。
此外，IP 也不提供获取诊断信息的直接方式（例如，路径上使用了哪些路由器，或估算往返时间的方法）。
为了解决这些缺陷，一种称为[互联网控制消息协议（ICMP）](https://en.wikipedia.org/wiki/Internet_Control_Message_Protocol)的特殊协议
与 IP 结合使用，提供与 IP 协议层配置和 IP 数据包处置相关的诊断和控制信息。
ICMP 通常被视为 IP 层本身的一部分，并且任何 IP 实现都必须包含它。
它使用 IP 协议进行传输。因此，准确地说，它既不是网络协议也不是传输协议，而是介于两者之间。

![](https://upload.wikimedia.org/wikipedia/commons/thumb/e/e1/ICMP_header_-_General-en.svg/2560px-ICMP_header_-_General-en.svg.png)

ICMP 提供可能需要关注的错误和控制消息的传递。
ICMP 消息通常由 IP 层本身、上层传输协议（如 TCP 或 UDP）以及在某些情况下由用户应用程序处理。
注意，ICMP 不为 IP 提供可靠性。
相反，它指示某些类型的故障和配置信息。数据包丢弃的最常见原因（路由器缓冲区溢出）不会引发任何 ICMP 信息。
其他协议（如 TCP）处理此类情况。

由于 ICMP 能够影响重要系统功能的运行并获取配置信息，攻击者在大量攻击中利用了 ICMP 消息。
出于对此类攻击的担忧，网络管理员通常安排防火墙阻止 ICMP 消息，尤其是在边界路由器上。
然而，如果 ICMP 被阻止，许多常见的诊断工具（如 ping、traceroute）将无法正常工作。

## ICMP 消息

ICMP 消息分为两大类：
- 与 IP 数据报传递问题相关的消息（称为*错误消息*）
- 与信息收集和配置相关的消息（称为*查询或信息性消息*）

### ping

_**Ping** 是一种[计算机网络](https://en.wikipedia.org/wiki/Computer_network)管理[软件工具](https://en.wikipedia.org/wiki/Utility_software)，用于测试[互联网协议](https://en.wikipedia.org/wiki/Internet_Protocol)（IP）网络上[主机](https://en.wikipedia.org/wiki/Host_(network))的可达性。几乎所有具有网络能力的操作系统都支持它，包括大多数嵌入式网络管理软件。_

回显请求 8

回显回复 0

TTL 值因操作系统和设备的版本而异。
Linux/Unix 的默认初始 TTL 值为 64，Windows 的 TTL 值为 128。

### traceroute

```shell
#cent os
yum install -y traceroute
```

## 涉及 ICMP 的攻击

涉及 ICMP 的攻击类型主要分为三类：洪水攻击、炸弹攻击和信息泄露。
本质上，洪水攻击会产生大量流量，导致一台或多台计算机遭受有效的 DoS 攻击。
炸弹攻击（有时称为核攻击）指发送特制的消息，导致 IP 或 ICMP 处理崩溃或挂起。
信息泄露攻击本身通常不会造成危害，但可用于告知其他攻击方法所采用的方法，以避免浪费时间或不被检测到。
针对 TCP 的 ICMP 攻击已有单独记录。

## 链接

- [计算机网络](/docs/CS/CN/CN.md)

## 参考文献

1. [wiki-ICMP](https://en.wikipedia.org/wiki/Internet_Control_Message_Protocol)
