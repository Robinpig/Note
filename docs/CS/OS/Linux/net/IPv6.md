## Introduction

**IPv6 是为解决 IPv4 地址枯竭而设计的下一代网络层协议**，地址长度从 32 bit 扩到 128 bit。但它不是"更长的 IPv4"——协议在设计时顺带修掉了 IPv4 几十年积累的诸多问题，这些差异直接反映在内核实现里：

- **固定 40 字节基础头部**，选项改为可链式追加的**扩展头部（extension header）**，中间路由器不再逐包处理选项，加快转发；
- **路由器不做分片**：只有源主机可分片，路径 MTU 发现（PMTUD）成为强制能力，避免路由器分片的性能与安全开销；
- **取消广播**，一律用组播（multicast），用 ICMPv6 的 **NDP** 同时取代了 IPv4 的 ARP、部分 ICMP 路由器发现与 DHCP；
- 支持即插即用的**地址自动配置（SLAAC）**，主机接入链路即可自行获得地址。

本篇从内核视角讲 IPv6：报文与扩展头部、收发路径、独立的 IPv6 路由表，以及 NDP / SLAAC。协议基础可对照 [IP](/docs/CS/CN/IP.md)。

## Packets and Addresses

### Basic Header

```c
// include/uapi/linux/ipv6.h
struct ipv6hdr {
#if defined(__LITTLE_ENDIAN_BITFIELD)
	__u8			priority:4,
				version:4;
#elif defined(__BIG_ENDIAN_BITFIELD)
	__u8			version:4,
				priority:4;
#endif
	__u8			flow_lbl[3];    /* traffic class + flow label */
	__be16			payload_len;
	__u8			nexthdr;        /* 传输层协议，或下一个扩展头 */
	__u8			hop_limit;      /* 类似 IPv4 TTL */
	struct	in6_addr	saddr;
	struct	in6_addr	daddr;          /* 各 16 字节 */
};
```

- **nexthdr**：相当于 IPv4 的 protocol，但如果存在扩展头部，它指向第一个扩展头；扩展头再用自己的 Next Header 字段串成一条链，链尾才是 TCP(6)/UDP(17)/ICMPv6(58)；
- **hop_limit**：等价 TTL；**payload_len** 只计负载（含扩展头），不含基础头；
- **flow label**：源端可标记同一条流，供中间设备不查内层即可识别。

常见扩展头：Hop-by-Hop(0)、Routing(43，如源路由 / SRv6)、Fragment(44)、ESP(50)/AH(51，IPsec)、Destination Options(60)。

### Address Types

| 类型 | 前缀 | 说明 |
|---|---|---|
| Global unicast | `2000::/3` | 全球可路由公网地址 |
| Link-local | `fe80::/10` | 仅本链路有效，每个 IPv6 接口自动拥有，NDP 用它通信 |
| Unique local | `fc00::/7` | 类似私网地址，组织内部用 |
| Loopback | `::1/128` | 本机回环 |
| Multicast | `ff00::/8` | 组播；末位含 scope（link-local `ff02::1` 所有节点、`ff02::2` 所有路由器） |
| Anycast | 同 unicast 格式 | 多台设备共享，路由到"最近"的一台 |

**没有广播地址**：IPv4 里的 ARP 广播、DHCP 广播在 IPv6 全部换成对应的组播组。

## Receive Path

IPv6 在 `inet_init` 之后由 `ipv6_module` 初始化，通过 `dev_add_pack` 注册以太网类型 `ETH_P_IPV6` 的接收入口 `ipv6_rcv`（位于 `net/ipv6/ip6_input.c`）。它和 IPv4 的 `ip_rcv` 平行：

```
网卡 → NAPI → netif_receive_skb
   → ptype_base[ETH_P_IPV6] → ipv6_rcv        ◀ IPv6 入口
        │  校验版本/长度/hop_limit
        ▼
   NF_HOOK(IP6_PRE_ROUTING) → ip6_rcv_finish
        │  查 IPv6 路由（dst）
        ▼
   分叉（由 fib6 的 rt->rt6i_flags 决定）
   ├─ 本机地址：ip6_input → ip6_protocol_deliver_rcu
   │     逐个处理扩展头 → 按 nexthdr inet6_add_protocol 分发
   │     TCP tcp_v6_rcv / UDP udpv6_rcv / ICMPv6 icmpv6_rcv
   ├─ 需转发：ip6_forward → ip6_forward_finish → 邻居 → 发出
   └─ 不可达/超跳数：icmpv6_send 报错后丢弃
```

```c
// net/ipv6/ip6_input.c
int ipv6_rcv(struct sk_buff *skb, struct net_device *dev,
	     struct packet_type *pt, struct net_device *orig_dev)
{
	const struct ipv6hdr *hdr;
	struct net *net = dev_net(skb->dev);

	if (!pskb_may_pull(skb, sizeof(struct ipv6hdr)))
		goto drop;
	hdr = ipv6_hdr(skb);
	if (hdr->version != 6)
		goto err;
	...
	return NF_HOOK(NFPROTO_IPV6, NF_INET_PRE_ROUTING,
		       net, NULL, skb, dev, NULL, ip6_rcv_finish);
}
```

扩展头部的处理集中在 `ip6_protocol_deliver_rcu` → `ipv6_parse_extensions`：按 nexthdr 顺序解析、对 Fragment 头做分片重组、对超数量 / 非法顺序的扩展头按 RFC 丢弃并发 ICMPv6 参数错误。

netfilter 对 IPv6 有独立的 `NFPROTO_IPV6` 钩子集，挂载点与 IPv4 五钩子一一对应（[netfilter](/docs/CS/OS/Linux/net/netfilter.md) 中的 `NF_INET_*` 已对 v4/v6 共用）。

## Send Path

IPv6 的发送入口是 `ip6_xmit`（`net/ipv6/ip6_output.c`），由 TCPv6 / UDPv6 的发送函数调用：

```
tcp_v6_send_response / udp_v6_send_skb
        ▼
   ip6_make_skb / ip6_xmit        ◀ 填基础头、追加扩展头
        ▼
   NF_HOOK(IP6_LOCAL_OUT) → ip6_local_out → dst_output
        ▼
   ip6_output → ip6_finish_output
        ├─ 超过 MTU？IPv6 不像 v4 那样在路由器分片：
        │   源端这里经 ip6_fragment 分片；中途设备超 MTU 只能回
        │   ICMPv6 "Packet Too Big"，由源端据 PMTU 缩小
        ▼
   ip6_finish_output2：经邻居子系统（NDP）解析下一跳 MAC → dev_queue_xmit
```

路由结果同样以 `dst_entry` 形式挂在 SKB 上（具体是 `rt6_info`），结构与 IPv4 的 `rtable` 对应。

## IPv6 Routing Table fib6

IPv6 用一套独立于 IPv4 FIB 的路由实现（`net/ipv6/ip6_fib.c`），核心是 **fib6**：

- 早期按 `struct fib6_node` 组织成一棵按地址前缀的 radix 树，叶子挂 `rt6_info`（含下一跳、出口设备、路由标志）；现代内核把通用的下一跳对象 `fib_nh` 与 `fib6_info` 抽象出来，与 IPv4 [Route](/docs/CS/OS/Linux/net/Route.md) 的 `fib_info` 共用 nexthop / ECMP 基础设施；
- 路由查找 `ip6_route_output` / `ip6_route_input` 返回 `rt6_info`，其 `rt6i_flags` 同时决定"本机 / 网关 / 丢弃"——`RTF_LOCAL` 表示目的是本机、`RTF_GATEWAY` 表示需经下一跳；
- 默认路由是 `::/0`；链路本地路由自动生成（`fe80::/10`）。

用户态同样经 [netlink](/docs/CS/OS/Linux/net/netlink.md)（rtnetlink 的 AF_INET6 地址族）用 `ip -6 route` 管理。

## NDP: Neighbor Discovery Protocol

**NDP（neighbor discovery protocol）是 ICMPv6 的一组消息**，承担了 IPv4 里 ARP、ICMP 路由器发现、地址冲突检测等多项工作。它运行在链路本地地址之上：

| 消息 | 类型 | IPv4 对应 | 作用 |
|---|---|---|---|
| Router Solicitation (RS) | 133 | （无标准） | 主机开机请求路由器立刻宣告 |
| Router Advertisement (RA) | 134 | （无标准） | 路由器周期/应 RS 宣告前缀、MTU、跳数、是否可 SLAAC/DHCPv6 |
| Neighbor Solicitation (NS) | 135 | ARP request | 请求某 IPv6 地址对应的 MAC，也做可达性检测 |
| Neighbor Advertisement (NA) | 136 | ARP reply | 回应自己的 MAC |
| Redirect | 137 | ICMP redirect | 通知主机有更优下一跳 |

解析下一跳 MAC 的过程与 ARP 同构，但复用了协议无关的**邻居子系统**：IPv6 注册自己的 `nd_tbl`（`neigh_table`），状态机仍是 NUD（[Neighbor](/docs/CS/OS/Linux/net/Neighbor.md)）。NS 不是发广播，而是发给目标地址对应的**请求节点组播地址（solicited-node multicast，`ff02::1:ff00:0/104` + 地址末 24 bit）**，这样每台主机只需监听极少的组播组。

### DAD: Duplicate Address Detection

主机给接口配置地址前，先对该地址发 NS（源地址用未指定地址 `::`）：如果有人回 NA，说明地址已被占用，该地址不能启用。这是 IPv4 长期缺失、靠 gratuitous ARP 勉强实现的能力，在 IPv6 是启用地址前的强制步骤。

## SLAAC: Stateless Auto-configuration

**SLAAC（stateless address autoconfiguration）让主机不依赖 DHCP 即可获得全球地址**，实现即插即用：

1. 接口启用，先自动生成 link-local 地址并完成 DAD；
2. 主机发 **RS**（或等待周期 RA）；
3. 路由器回 **RA**，携带一个或多个前缀（如 `2001:db8::/64`）及标志位：
   - **A 位（autonomous）**：允许主机用该前缀自行拼接地址——主机用 EUI-64（MAC 推导）或 RFC 7217 的稳定随机后缀生成接口标识，拼上前缀得到全球地址，再做 DAD；
   - **M 位（managed）**：要求用 **DHCPv6** 获取地址；**O 位（other）**：地址靠 SLAAC，但 DNS 等其它信息找 DHCPv6；
4. RA 还给出 hop limit、MTU、默认路由器（RA 的发送者即默认网关），前缀含 preferred/valid lifetime，到期重新生成或废弃。

内核侧实现在 `net/ipv6/addrconf.c`（`addrconf_rs_timer`、`addrconf_prefix_rcv` 等），地址状态在 `tentative（DAD 中）→ preferred → deprecated → invalid` 间迁移。现代系统默认开启隐私扩展（RFC 8981），对外用定期轮换的临时地址、稳定地址只用于入站，防止用地址追踪设备。

## Links

- [Neighbor](/docs/CS/OS/Linux/net/Neighbor.md)
- [Route](/docs/CS/OS/Linux/net/Route.md)
- [IP](/docs/CS/OS/Linux/net/IP.md)
- [netfilter](/docs/CS/OS/Linux/net/netfilter.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

- [Internet Protocol, Version 6 (IPv6), RFC 8200](https://datatracker.ietf.org/doc/html/rfc8200)
- [Neighbor Discovery for IP version 6, RFC 4861](https://datatracker.ietf.org/doc/html/rfc4861)
- [IPv6 Stateless Address Autoconfiguration, RFC 4862](https://datatracker.ietf.org/doc/html/rfc4862)
