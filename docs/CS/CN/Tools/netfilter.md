## Introduction

netfilter 围绕着网络层有 5 个 hook（精确名与编号见内核 uapi/linux/netfilter_ipv4.h，NF_INET_* 为同值别名）：

- NF_IP_PRE_ROUTING（0）：报文进入协议栈后、路由决策前
- NF_IP_LOCAL_IN（1）：发往本机的报文
- NF_IP_FORWARD（2）：转发的报文
- NF_IP_LOCAL_OUT（3）：本机生成的报文
- NF_IP_POST_ROUTING（4）：报文经路由决策后、离开协议栈前

NF_IP_NUMHOOKS 定义为 5。在 iptables 中，这些钩子对应 PREROUTING / INPUT / FORWARD / OUTPUT / POSTROUTING 五条内置链。

Netfilter 允许同一个钩子处注册多个回调函数，每个回调函数有明确的优先级，确保按照预定顺序触发。一个钩子处的多个回调函数串联起来便形成了一条“回调链”（Chained Callbacks）

## Hook Priorities

同一 hook 内的回调按注册的优先级排序，数值小者先执行。netfilter 预定义的优先级常量：

| 优先级常量 | 数值 | 用途 |
| --- | --- | --- |
| NF_IP_PRI_RAW | -300 | raw 表，先于连接跟踪 |
| NF_IP_PRI_CONNTRACK | -200 | 连接跟踪 |
| NF_IP_PRI_MANGLE | -150 | mangle 表 |
| NF_IP_PRI_NAT_DST | -100 | 目的地址 NAT（DNAT） |
| NF_IP_PRI_FILTER | 0 | filter 表 |
| NF_IP_PRI_SECURITY | 50 | security 表 |
| NF_IP_PRI_NAT_SRC | 100 | 源地址 NAT（SNAT） |

除 5 个 IPv4 hook 外，内核 4.2 引入了 ingress hook（NF_NETDEV_INGRESS）：它挂在具体网卡上、早于 prerouting 触发，可用于网卡级别的流量丢弃与重定向。

## Tables and Chains

netfilter 用"表（table）"按功能组织规则，每张表只注册到与自身功能相关的 hook 上，因此每张表在 iptables 中只能出现在特定链里：

| 表 | 注册的 hook | iptables 中的链 |
| --- | --- | --- |
| filter | LOCAL_IN / FORWARD / LOCAL_OUT | INPUT / FORWARD / OUTPUT |
| nat | PRE_ROUTING / POST_ROUTING（编译进 CONFIG_IP_NF_NAT_LOCAL 时另有 LOCAL_OUT / LOCAL_IN） | PREROUTING / POSTROUTING 等 |
| mangle | 全部 5 个 hook | 全部 5 条链 |
| raw | PRE_ROUTING / LOCAL_OUT | PREROUTING / OUTPUT |
| security | LOCAL_IN / FORWARD / LOCAL_OUT | INPUT / FORWARD / OUTPUT |

注意 filter 表不在 PRE_ROUTING / POST_ROUTING 注册：报文刚进来尚未做路由决策、或已经路由完准备发出时，都不适合做"过滤"裁决，这是 hook 语义决定的。

## Connection Tracking

conntrack 子系统把报文关联到连接与状态，是有状态防火墙（`-m conntrack --ctstate`）和 NAT 的基础。四类核心状态：

- INVALID：无法关联到任何已知连接的报文（畸形或乱序）；
- NEW：新连接的报文，或只见过单向报文；
- ESTABLISHED：双向报文都见过，连接已建立；
- RELATED：与新连接关联的既有连接上的流量，典型如 FTP 的数据通道，或 ICMP 差错报文。

相关 sysctl（/proc/sys/net/netfilter/）：
- nf_conntrack_count：只读，当前表内条目数；
- nf_conntrack_max：最大条目数，默认等于 nf_conntrack_buckets。注意**每条连接两个方向各占一条**（原始方向加反向方向），所以默认配置下打满时的平均哈希链长是 2 而非 1。

> [!WARNING]
> 
> conntrack 表满时，内核直接丢包并打印限速日志（nf_conntrack_core.c 原话 "nf_conntrack: table full, dropping packet"）。机器出现"莫名丢包"、`nf_conntrack_count` 逼近 `nf_conntrack_max` 时，应优先排查此处，而不是先怀疑网卡或对端。

## iptables

Netfilter 的钩子回调固然强大，但得通过程序编码才能使用，并不适合系统管理员日常运维。为此，基于 Netfilter 框架开发的应用便出现了，如 iptables

Netfilter 中的钩子，在 iptables 中称作“链”（chain）

iptables 只是用户态前端之一。nftables 自 Linux 3.13 进入内核（自带 iptables 兼容层），如今各发行版已陆续切换：
- RHEL 8：nftables 成为默认过滤框架，iptables 等命令变为同名的 nft-based drop-in。用 `iptables --version` 可区分：显示 `(nf_tables)` 为新版，`(legacy)` 为旧版；
- RHEL 9：iptables-nft 包已标记 deprecated；
- Ubuntu 22.04 LTS：nftables 为默认防火墙后端。

nftables.org 官网的口径是 "nftables is the successor of iptables"。

## Links

- [IP](/docs/CS/CN/IP.md)
- [tcpdump](/docs/CS/CN/Tools/tcpdump.md)
- [WireShark](/docs/CS/CN/Tools/WireShark.md)
- [Xcap](/docs/CS/CN/Tools/Xcap.md)
- [Linux netfilter](/docs/CS/OS/Linux/net/netfilter.md)

## References

1. [Linux netfilter Hacking HOWTO](https://www.netfilter.org/documentation/HOWTO/netfilter-hacking-HOWTO.html)
2. [Netfilter Conntrack Sysctl - Linux Kernel Documentation](https://docs.kernel.org/networking/nf_conntrack-sysctl.html)
3. [nftables wiki](https://wiki.nftables.org/wiki-nftables/index.php/Main_Page)
