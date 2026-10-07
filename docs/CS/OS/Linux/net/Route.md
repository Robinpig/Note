## Introduction

路由子系统回答一个核心问题：**这个包该从哪块网卡、发往哪个下一跳**。它由两部分组成——内核里维护的**转发表 FIB**（Forwarding Information Base），以及在收发路径上对 FIB 的**查找**。

本笔记聚焦 FIB 表本体与查找过程。查找的**结果对象**（`dst_entry`/`rtable`/`flowi`）见 [socket 的 Route 章](/docs/CS/OS/Linux/net/socket.md)——那里是"查到之后拿到什么缓存"，本篇是"表里有什么、怎么查"。路由查找的结果随后决定 Egress 是否需要经过**邻居子系统**解析下一跳 MAC（见 [Neighbor](/docs/CS/OS/Linux/net/Neighbor.md)）。

## Lookup Timing

路由查找在两个方向发生：

- **发送（输出）**：本机进程发包时，在 `ip_queue_xmit` 之前调用 `ip_route_output_*`，确定出口网卡与下一跳；查找条件由 `struct flowi4` 描述（源/目的 IP、ToS、出口约束 `oif`、mark、uid 等）；
- **接收（输入）**：网卡收到包、在 `ip_rcv_finish` 里调用 `ip_route_input`，根据目的地址判断——是本机收（挂 `ip_local_deliver`）、还是要转发（走 FORWARD 路径）。

无论哪个方向，命中后都会把结果（一个 `rtable`，内含 `dst_entry`）缓存在 socket（`inet_sock->inet_dst_cache`）或 SKB 上，避免每个包重复查表。

## FIB Table Structure

现代内核（约 5.x 起）的 IPv4 FIB 用 **LC-trie**（层级压缩前缀树）组织，取代了早期的 hash 表，使**最长前缀匹配**在大规模路由下依然高效。`include/net/ip_fib.h` 中的核心对象：

```c
struct fib_table {
	struct hlist_node	tb_hlist;
	u32			tb_id;        // 表编号：254=main，255=local
	int			tb_num_default;
	struct rcu_head		rcu;
	unsigned long		*tb_data;
	unsigned long		__data[];
};
```

- 系统默认有两张表：**local（id 255）**存本机地址与广播地址，**main（id 254）**存普通路由；
- 注意 `fib_table` 里**不再有函数指针**（早期的 `tb_lookup`/`tb_insert` 已废弃），表操作统一由 `fib_table_lookup()`、`fib_table_insert()` 等外部函数承担；
- trie 的叶子上挂着一组前缀相同的路由条目（旧实现里是 `fib_alias`，按 ToS/priority 排序），每个条目指向一个 `fib_info`。

### fib_info: The Route's 'How to Go'

`trie` 只负责"匹配到前缀"，真正描述下一跳与出接口的是 `fib_info`：

```c
struct fib_info {
	struct hlist_node	fib_hash;
	struct list_head	nh_list;
	struct net		*fib_net;
	unsigned char		fib_protocol;   // 路由来源：static/boot/kernel...
	unsigned char		fib_scope;      // 作用域：link/global/host
	unsigned char		fib_type;       // RTN_UNICAST/LOCAL/BROADCAST/UNREACHABLE/BLACKHOLE...
	__be32			fib_prefsrc;    // 首选源地址
	u32			fib_tb_id;
	u32			fib_priority;   // metric/优先级（越小越优）
	struct dst_metrics	*fib_metrics;   // MTU、cwnd hint 等
	int			fib_nhs;        // 下一跳数量
	struct nexthop		*nh;            // 5.6+：可独立复用的 nexthop 对象
	struct fib_nh		fib_nh[];       // 旧式内联下一跳（fib_nhs 个）
};
```

下一跳的公共部分是 `fib_nh_common`，IPv4 的 `fib_nh` 内嵌它：

```c
struct fib_nh_common {
	struct net_device	*nhc_dev;    // 出口网卡
	int			nhc_oif;
	unsigned char		nhc_scope;
	u8			nhc_gw_family;
	union { __be32 ipv4; struct in6_addr ipv6; } nhc_gw;  // 网关地址
	int			nhc_weight;                       // ECMP 权重
	struct lwtunnel_state	*nhc_lwtstate;                    // 轻量隧道（mpls/seg6…）
	/* ... per-cpu 路由缓存、例外缓存 ... */
};
```

字段语义：

- `nhc_dev` 是出口设备，`nhc_gw` 是网关——**直连路由没有网关**（`nhc_gw_family=0`），包的目的即下一跳；
- `fib_type` 决定匹配后动作：`RTN_UNICAST` 正常转发，`RTN_UNREACHABLE`/`RTN_BLACKHOLE` 直接产生 ICMP 不可达 / 静默丢弃；
- 现代内核（5.6+）推荐用独立的 **nexthop 对象**（`struct nexthop`），多个路由可引用同一下一跳组，便于 ECMP 组的原子替换。

### fib_result: Lookup Return Value

查找命中后，结果回填到 `fib_result`：

```c
struct fib_result {
	__be32			prefix;
	unsigned char		prefixlen;
	unsigned char		nh_sel;   // ECMP 选中的下一跳下标
	unsigned char		type;
	unsigned char		scope;
	struct fib_nh_common	*nhc;     // 最终选定的下一跳
	struct fib_info		*fi;
	struct fib_table	*table;
};
```

## Policy Routing

启用 `CONFIG_IP_MULTIPLE_TABLES` 后，查找不再只查 main/local 两张表，而是先过一组 **`fib_rules`**（策略规则），按规则把流量引导到不同表：

- 规则可匹配源/目的网段、ToS、`fwmark`、入接口、uid 等；
- 每条规则动作：查表（`goto table N`）、直接拒绝、或不可达；
- 规则按优先级顺序匹配，命中即止——这就是 `ip rule` / `ip route show table N` 背后的机制。

## ECMP and Multipath

一条路由可有多个下一跳（`fib_nhs > 1` 或 nexthop group）：

- 内核按五元组哈希（而非逐包轮转）把不同流分到不同下一跳，避免乱序；
- `nh_sel`/`nhc_weight` 决定选哪条、按多大权重；
- 下一跳失效（链路 down、邻居解析失败）时会做 **next-hop alive 检测**，把流量迁到存活路径并缓存例外（`nhc_exceptions`）。

## Interface with User Space

路由表通过 [**rtnetlink**](/docs/CS/OS/Linux/net/netlink.md?id=rtnetlink)（`NETLINK_ROUTE`）增删改：`ip route`、`ip rule` 命令在内核里对应 `RTM_NEWROUTE`/`RTM_DELROUTE` 等消息，最终调 `fib_table_insert()` 等落地。链路状态变化（网卡 up/down、地址增删）也以同样通道反向通知用户态。

## Links

- [网络知识地图](/docs/CS/OS/Linux/net/README.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

1. [内核文档：IP 路由（Policy Routing）](https://docs.kernel.org/networking/ip-sysctl.html)
2. [Linux Advanced Routing & Traffic Control HOWTO](https://lartc.org/howto/)
