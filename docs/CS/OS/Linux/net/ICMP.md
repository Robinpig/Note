## Introduction

**ICMP（Internet control message protocol，互联网控制报文协议）是 IP 层的"控制与反馈"协议**，封装在 IP 报文里传输（协议号 1）。它不承载用户数据，而是用来在主机、路由器之间传递**网络是否可达、问题出在哪**的信号——连通性测试（ping）、目的不可达、超时、重定向、路径 MTU 发现都依赖它。

ICMP 常被误解为"可有可无的诊断协议"，实际上它是 IP 正确运转的反馈回路：没有 ICMP，发送方就无法知道包为何被丢、路径 MTU 是多少、有没有更优路由，很多连接会莫名其妙地卡住。

本篇讲 IPv4 的 ICMP：报文格式、类型、内核接收处理 `icmp_rcv`、各类差错报文的产生，以及 PMTU。ICMPv6（协议号 58）是 NDP 的载体，见 [IPv6](/docs/CS/OS/Linux/net/IPv6.md)；协议基础对照 [CN/ICMP](/docs/CS/CN/ICMP.md)。

## Packet Format

```c
// include/uapi/linux/icmp.h
struct icmphdr {
  __u8		type;       /* 消息类型 */
  __u8		code;       /* 子类型 */
  __sum16	checksum;
  union {
	struct {
		__be16	id;     /* ping：标识，通常是进程 pid */
		__be16	sequence; /* ping：序号 */
	} echo;
	__be32	gateway;    /* redirect：优选路由器地址 */
	struct {
		__be16	__unused;
		__be16	mtu;     /* fragmentation needed + DF：下一跳 MTU */
	} frag;
	__u8	reserved[4];
  } un;
};
```

所有 ICMP 报文头 8 字节，`type` 决定大类、`code` 区分具体情形，后续为变长数据区。**差错报文（error）的数据区按规定要回填"触发该错误的原始 IP 头 + 前若干字节负载"**，以便发送方识别是哪条连接、哪个包出了问题。

## Type Overview

ICMP 分**查询类（query）**与**差错类（error）**：

### Query Class

| Type | 名称 | 作用 |
|---|---|---|
| 8 / 0 | Echo request / reply | **ping**：8 探测、0 回应，配合 id/sequence 算 RTT 与丢包 |
| 13 / 14 | Timestamp request/reply | 时间戳查询（少用） |
| 17 / 18 | Mask request/reply | 地址掩码请求（基本废弃） |
| 30 / 31 | Traceroute（已废弃） | 老的路由追踪扩展 |

### Error Class

| Type | 名称 | 典型 code 与含义 |
|---|---|---|
| 3 | Destination unreachable | 0 网络不可达、1 主机不可达、**3 端口不可达（UDP 未监听）**、4 需分片但 DF 置位、13 被管理策略禁止（防火墙） |
| 11 | Time exceeded | 0 TTL 减到 0（traceroute 原理）、1 分片重组超时 |
| 5 | Redirect | 告知主机有更优的下一跳，应改路由表 |
| 4 | Source quench（已废弃） | 旧的拥塞反馈，现被 ECN / 拥塞控制取代 |
| 12 | Parameter problem | IP 头字段非法 / 缺少必需选项 |

## Receive Processing icmp_rcv

ICMP 在协议栈注册阶段由 `inet_add_protocol(&icmp_protocol, IPPROTO_ICMP)` 登记。IP 层收到协议号 1 的包、本机交付时，分发到 `icmp_rcv`（`net/ipv4/icmp.c`）：

```c
// net/ipv4/icmp.c
int icmp_rcv(struct sk_buff *skb)
{
	struct icmphdr *icmph;
	struct rtable *rt = skb_rtable(skb);
	struct net *net = dev_net(rt->dst.dev);

	...
	switch (icmph->type) {
	case ICMP_ECHOREQUEST:
		icmp_echo(skb);
		STATS_INC_MIB(net, ICMP_MIB_INECHOES);
		goto out;

	case ICMP_ECHOREPLY:
		if (!net->ipv4.sysctl_ping_group_range)
			break;
		break;
	}

	/*
	* 差错报文：交给协议栈/传输层处理。如 ICMP_UNREACH_PORT
	* 由相关 socket 的 err 队列消化；TCP 据此判断 PMTU / 硬错误。
	*/
	if (icmp_pointers[icmph->type].error)
		icmp_pointers[icmph->type].error(net, skb, info);
	consume_skb(skb);
}
```

处理分两路：

- **Echo request**：`icmp_echo` 立刻把源 / 目的地址对调、类型改为 Echo reply，沿原路发回。这就是 ping 不需要目标端开任何服务、由内核直接应答的原因；
- **差错报文**：不交给用户进程，而是 `icmp_unreach` → `ip_icmp_error` → `tcp_v4_err` / `__udp4_lib_err`，按回填的原始报文头找到对应 socket：
  - TCP 收到"需分片 DF"用其中的 MTU 更新路由的 pmtu；收到"主机不可达"等硬错误影响连接建立 / 重传；
  - UDP socket 若设置了 `IP_RECVERR`，错误进入其错误队列供 `recvmsg(MSG_ERRQUEUE)` 读取，否则通常静默（UDP 本就不可靠）。

### Rate Limit and Security

内核会对 ICMP 差错报文做速率限制（`net.ipv4.icmp_ratelimit` / `icmp_ratemask`），既防止错误应答被用于放大攻击，也避免风暴。普通站点安全实践常**放行 echo request 而屏蔽部分出站差错**，但**完全封禁 ICMP 会破坏 PMTUD**，导致大包黑洞，需要谨慎。

## How Error Messages Are Generated

协议栈在各处理点发现问题时主动调用 `icmp_send` 构造差错报文：

```c
// net/ipv4/ip_output.c / icmp.c
void icmp_send(struct sk_buff *skb_in, int type, int code, __be32 info)
{
	/* 回填 skb_in 的原始 IP 头到 payload，使对端定位到出错的包 */
	...
}
```

典型触发点：

- **UDP 收到发往未监听端口的包**：`udp_protocol.err → icmp_send(skb, ICMP_DEST_UNREACH, ICMP_PORT_UNREACH, 0)`，这是 `traceroute`（UDP 模式）判断到达目的主机的依据；
- **TTL 减到 0**：转发时 `ip_decrease_ttl` 发现归零 → 回 ICMP_TIME_EXCEEDED，是 `traceroute` 逐跳定位的原理（每一跳 TTL +1，依次逼出各路由器超时）；
- **路由命中 RTN_UNREACHABLE / 无路由**：回目的不可达；
- **需转发但设置了 DF 且超过出接口 MTU**：回 type 3 code 4 并携带下一跳 MTU。

## PMTU: Path MTU Discovery

**PMTUD（path MTU discovery）让发送方知道到对端整条路径上最小的 MTU**，从而一次发出不需中途分片的最大包：

1. 发送方在 IP 头置 **DF（don't fragment）**位；
2. 若某跳的出接口 MTU 装不下，该路由器**不分片**，丢弃并回 **ICMP type 3 code 4（fragmentation needed）**，报文里带该链路的 MTU（`icmph.un.frag.mtu`）；
3. 发送方把到该目的的路由缓存 PMTU 调小，重传；重复直到全程可通过。

内核为每条路由维护 PMTU（`dst_pmtu`），TCP 在建连后主动做 PMTU 探测并据此设置 MSS；这也和 [Qdisc](/docs/CS/OS/Linux/net/Qdisc.md) 无关、属于 IP 输出路径。在 ICMP 被防火墙吞掉的网络里，PMTUD 会失效——包反复以原大小发、又反复被丢，形成 **MSS/PMTU 黑洞**，表现为"小包通、大包卡（如 TLS 握手后无响应）"。较新内核支持 RFC 4821 的报文分层探测（PLPMTUD）减少对 ICMP 的依赖。

## Links

- [IP](/docs/CS/OS/Linux/net/IP.md)
- [IPv6](/docs/CS/OS/Linux/net/IPv6.md)
- [UDP](/docs/CS/OS/Linux/net/UDP.md)
- [network](/docs/CS/OS/Linux/net/network.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

- [Internet Control Message Protocol, RFC 792](https://datatracker.ietf.org/doc/html/rfc792)
- [Path MTU Discovery, RFC 1191](https://datatracker.ietf.org/doc/html/rfc1191)
- [ICMP man page / Linux ip-sysctl documentation](https://docs.kernel.org/networking/ip-sysctl.html)
