## Introduction

For TCP/IP networks, the *Address Resolution Protocol* (ARP) provides a dynamic mapping between IPv4 addresses and the hardware addresses used by various network technologies.
ARP is used with IPv4 only; IPv6 uses the Neighbor Discovery Protocol (NDP), which is incorporated into ICMPv6.

> [!WARNING]
> **常见误传（先破一个直觉）**：不少中文资料写「ARP 广播逐跳传到目的网络，最后由目的主机应答」——**这是错的**。ARP 是**链路本地（link-local）**行为：请求只以链路层广播发给本网段内的所有主机；RFC 1812 明确规定路由器不得转发收到的链路层广播。主机访问远程网络时，ARP 的对象是**网关/下一跳**（由路由表决定），拿到网关 MAC 后把 IP 报文交给它，此后的跨网段转发是路由器的活，与 ARP 无关。把 ARP 理解成「逐跳解析到终点」会在排障时找错方向。

> [!NOTE]
> A related protocol that provides the reverse mapping from ARP, called RARP, was used by systems lacking a disk drive (normally diskless workstations or X terminals).
It is rarely used today and requires manual configuration by the system administrator.

## Packet Format

An ARP request is sent as a link-layer broadcast to every host on the local segment. For the common Ethernet + IPv4 case the ARP packet is **28 bytes**:

| Field | Size | Ethernet + IPv4 |
| :-- | :-- | :-- |
| Hardware address space (`hrd`) | 16 bit | 1（Ethernet） |
| Protocol address space (`pro`) | 16 bit | 2048（IPv4 的 ethertype） |
| Hardware address length (`hln`) | 8 bit | 6 |
| Protocol address length (`pln`) | 8 bit | 4 |
| Opcode (`op`) | 16 bit | 1 request / 2 reply |
| Sender hardware address (`sha`) | `hln` bytes | 6 |
| Sender protocol address (`spa`) | `pln` bytes | 4 |
| Target hardware address (`tha`) | `hln` bytes | 6（请求中未知，为空/广播） |
| Target protocol address (`tpa`) | `pln` bytes | 4 |

> [!NOTE]
> Opcode 3/4（reverse request/reply）属于 RARP，出自 **RFC 903**，不是 RFC 826——RFC 826 只定义了 1 和 2。引用时别把两个 RFC 混为一谈。

## Operation

一台主机要向同网段的目的 IP 发送报文时：

1. 查本地 ARP 缓存，命中则直接取出 MAC 组装帧；
2. 未命中则广播 ARP request（`op=1`，`tha` 留空）；
3. 网段内每台主机都收到请求，但只有 `tpa` 与自身 IP 相符的主机**单播**回复 ARP reply（`op=2`），其余主机静默丢弃；
4. 请求方把映射写入缓存，后续报文直接使用。

目的主机在别的网段时，第 2 步的 `tpa` 填的是网关 IP——见开头的 WARNING。

**无故 ARP（gratuitous ARP）**：主机主动广播「我的 IP 是 X，我的 MAC 是 Y」的 reply。用途有两个：宣告地址变更（刷新网段内各主机的缓存），以及**地址冲突检测**（RFC 5227 的 IPv4 ACD：开机或链路 up 时先无故 ARP 探一遍，收到他人应答说明 IP 冲突）。 gratuitous ARP 也是 ARP 欺骗的载体，见 [Attack](/docs/CS/CN/Attack.md)。

```shell
# 查看/操作 ARP 缓存（Linux）
arp -a              # 等价于 ip neigh show
ip neigh show
```

## ARP Cache

Essential to the efficient operation of ARP is the maintenance of an ARP cache (or table) on each host and router.
This cache maintains the recent mappings from network-layer addresses to hardware addresses for each interface that uses address resolution.
没有缓存就意味着每个报文都要先广播一次请求，链路层会被 ARP 广播打满。

### Cache Timeout

> [!WARNING]
> **「ARP 缓存默认 20 分钟」没有出处**：RFC 826 明确把缓存老化排除在协议范围外——原文 *"It may be desirable to have table aging and/or timeouts. The implementation of these is outside the scope of this protocol."* RFC 1122 只要求主机提供清除过期表项的机制且超时应可配置。一些教材里的「20 分钟」是示例值，不是任何标准的规定值。

Linux 的实际口径（`/proc/sys/net/ipv4/neigh/`，每个网卡一份，`default/` 是兜底）：

| 参数 | 默认值 | 含义 |
| :-- | :-- | :-- |
| `gc_stale_time` | 60 秒 | 条目闲置超过该时间即可被垃圾回收清除 |
| `gc_thresh1/2/3` | 128 / 512 / 1024 | 缓存条目软上限、加压上限、硬上限；超过 `gc_thresh3` 后新表项分配失败 |
| `base_reachable_time` | — | 条目有效期基准（由 ARP 交互自适应调整），现行内核文档已不再列出固定默认值 |

缓存必须老化的原因很直接：IP 地址会换手（DHCP 重分配）、设备会迁移、网卡会更换——一个永不过期的映射会把报文持续发给错误的 MAC。

## Proxy ARP

代理 ARP 让一台路由器**代替**不在本网段的目的主机应答 ARP 请求：请求方以为目的主机就在网段上，把报文直接交给代理路由器，由它继续转发。典型用途是让两个子网的主机在不改路由表和掩码的前提下互通（ legacy 网络的粘合层），以及某些「透明网关」组网。

代价与风险：排障时网段内主机看不到真实拓扑（网络层不可见）；更常见的是被滥用为中间人跳板，因此在设计良好的网络里通常应关闭。

## RARP

Reverse ARP（RFC 903）用与 ARP 相反的流程：无盘工作站已知自己的 MAC，向服务器询问自己的 IP。它需要网段内配一台 RARP 服务器、靠手工维护 MAC→IP 表，且不能跨路由器。这两个短板正是 BOOTP（引入中继，可跨网段）与后来的 DHCP（动态租约 + 丰富 option）取代它的原因。今天只有在排查古董设备时才会遇到它。

## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [IP](/docs/CS/CN/IP.md)
- [ICMP](/docs/CS/CN/ICMP.md)
- [Attack](/docs/CS/CN/Attack.md)
- [Linux Neighbor](/docs/CS/OS/Linux/net/Neighbor.md)

## References

1. [RFC 826 - An Ethernet Address Resolution Protocol](https://datatracker.ietf.org/doc/html/rfc826)
2. [RFC 903 - A Reverse Address Resolution Protocol](https://datatracker.ietf.org/doc/html/rfc903)
3. [RFC 5227 - IPv4 Address Conflict Detection](https://datatracker.ietf.org/doc/html/rfc5227)
4. [RFC 1812 - Requirements for IP Version 4 Routers](https://datatracker.ietf.org/doc/html/rfc1812)
5. [Linux kernel documentation - ip-sysctl](https://docs.kernel.org/networking/ip-sysctl.html)
