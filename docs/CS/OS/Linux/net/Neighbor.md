## Introduction

邻居子系统（neighbour）负责把**下一跳的网络层地址（IP）解析为链路层地址（MAC）**，并在解析成功后把二层帧头缓存起来。它位于网络层与设备发送队列之间：[路由子系统](/docs/CS/OS/Linux/net/Route.md)决定"包发往哪个下一跳 IP、走哪块网卡"，邻居子系统接着解决"这个下一跳的 MAC 是什么"，之后才能 `dev_queue_xmit` 交驱动发出（见 [network 的 Egress](/docs/CS/OS/Linux/net/network.md)）。

IPv4 下邻居子系统最典型的实现就是 **ARP**（`arp_tbl`）；IPv6 对应的是 NDP。它是**协议无关**的通用框架，不同协议注册自己的 `neigh_table` 与 `neigh_ops`。

## Data Structure

### neigh_table

每种邻居协议一张表，IPv4 的 ARP 表为 `arp_tbl`（`include/net/neighbour.h`）：

```c
struct neigh_table {
	int			family;        // AF_INET
	__be16			protocol;      // htons(ETH_P_IP)
	__u32			(*hash)(const void *pkey, const struct net_device *, __u32 *);
	int			(*constructor)(struct neighbour *);
	char			*id;           // "arp_cache"
	struct neigh_parms	parms;         // 可配参数与超时
	int			gc_thresh1, gc_thresh2, gc_thresh3;  // 回收水位
	struct delayed_work	gc_work;       // 异步垃圾回收
	struct timer_list	proxy_timer;   // proxy arp
	struct neigh_hash_table __rcu *nht;  // 邻居哈希表
	/* ... */
};
```

### neighbour

每个"下一跳 IP"对应一个 `neighbour` 条目，按协议地址（pkey）在表中哈希：

```c
struct neighbour {
	struct neigh_table	*tbl;
	struct neigh_parms	*parms;
	struct net_device	*dev;
	unsigned long		used;
	struct timer_list	timer;         // NUD 状态机定时器
	u8			nud_state;     // 当前状态（NUD_*）
	seqlock_t		ha_lock;
	unsigned char		ha[ALIGN(MAX_ADDR_LEN, sizeof(unsigned long))]; // 硬件地址(MAC)
	int			(*output)(struct neighbour *, struct sk_buff *);
	const struct neigh_ops	*ops;
	struct hh_cache		hh;            // 缓存的二层帧头
	struct sk_buff_head	arp_queue;     // 解析期间暂存的包
	/* ... */
};
```

### neigh_ops

不同状态下"怎么把包送出去"由四个函数区分：

```c
struct neigh_ops {
	void	(*solicit)(struct neighbour *, struct sk_buff *);  // 主动解析(发 ARP request)
	void	(*error_report)(struct neighbour *, struct sk_buff *);
	int	(*output)(struct neighbour *, struct sk_buff *);          // 通用输出(可能触发解析)
	int	(*connected_output)(struct neighbour *, struct sk_buff *); // 已知可达的快路径
};
```

## NUD State Machine

邻居条目的核心是一套状态机（`nud_state`），状态值定义在 `linux/neighbour.h`：

| 状态 | 值 | 含义 |
| :-- | :-- | :-- |
| `NUD_INCOMPLETE` | 0x01 | 已发出请求、尚未收到应答，MAC 未知 |
| `NUD_REACHABLE` | 0x02 | 最近被证实可达（收到应答 / 上层确认），缓存可信 |
| `NUD_STALE` | 0x04 | 曾有 MAC，但**可达性已过期**——可暂用，但用前需重新确认 |
| `NUD_DELAY` | 0x08 | STALE 后又有包要发，进入短暂等待，期间等待上层确认 |
| `NUD_PROBE` | 0x10 | DELAY 未获确认，开始周期性发请求探测 |
| `NUD_FAILED` | 0x20 | 探测次数耗尽仍无应答，解析失败 |
| `NUD_NOARP` | 0x40 | 无需 ARP 的设备（如点到点） |
| `NUD_PERMANENT` | 0x80 | 手工静态配置，永久有效 |

典型迁移：

```
(无条目) ──发包──▶ INCOMPLETE ──收到ARP reply──▶ REACHABLE
                      │ probe 超时               │ 可达超时
                      ▼                          ▼
                   FAILED(丢包/ICMP)          STALE ──又发包──▶ DELAY
                                                            │ 无确认
                                                            ▼
                                                          PROBE ──应答──▶ REACHABLE
                                                            │ 失败
                                                            ▼
                                                          FAILED
```

关键设计：**缓存的 MAC 不会被无条件信任**。REACHABLE 有超时，过期转 STALE；STALE 的 MAC 虽可"乐观使用"，但会通过 DELAY/PROBE 重新验证，避免长期向一个已失效的 MAC 发包。

## Parsing and Output Flow

发送时，IP 层之后调邻居输出（`neigh_output`），按状态分流：

1. 下一跳无 `neighbour` 条目 → 新建，状态 INCOMPLETE，调 `ops->solicit` 发 **ARP request**（"谁是 10.0.0.1，请告诉 10.0.0.2"，二层广播）；
2. 解析未完成期间，要发的包先挂在 `arp_queue` 等待（队列长度有上限），不立即丢弃；
3. 收到 **ARP reply** → 写入 `ha`、状态置 REACHABLE，刷新 `hh` 帧头，把 `arp_queue` 里的包冲刷出去；
4. 之后再发包走快路径 `connected_output`，直接把缓存帧头贴到包上；探测多次无应答则 `NUD_FAILED`，释放排队包并向上返回（常表现为 `neigh: arp_cache: neighbor table overflow!`）。

`neighbour->output` 这个函数指针会随状态在"通用解析路径 / connected 快路径"之间切换，使稳态发送几乎零额外开销。

## hh_cache

为避免每个包都重新拼二层帧头，解析成功后把帧头缓存进 `struct hh_cache`（`hh_len`、`hh_data`，用 seqlock 保护）。`neigh_hh_output` 直接把缓存头拷到 SKB 前部再送 `dev_queue_xmit`——这正是 [network](/docs/CS/OS/Linux/net/network.md) Egress 中 `neigh_hh_output` 一步的含义。无缓存或未就绪时才退化为逐包填头。

## Reclamation and Troubleshooting

- 垃圾回收由 `gc_work` 异步执行，按 `gc_thresh1/2/3` 三级水位清理长期不用的条目，条目总量受 `gc_thresh3` 限制（超限即报 table overflow）；
- 查看 / 调整：`ip neigh`、`arp -n`、`/proc/net/arp`；参数在 `/proc/sys/net/ipv4/neigh/<dev>/`（`gc_stale_time`、`base_reachable_time` 等）；
- **proxy ARP**：主机代为应答"不属于本网段"目标的 ARP 请求（`pneigh_entry` + `proxy_queue`），用于某些透明网关 / 跨网段桥接场景；
- **gratuitous ARP**：主动无偿广播自己的 IP→MAC（如网卡 up、VIP 漂移时），让相邻设备更新缓存，Keepalived 漂移虚 IP 即依赖它。

## Links

- [网络知识地图](/docs/CS/OS/Linux/net/README.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

1. [内核文档：neighbour（ARP 相关参数）](https://docs.kernel.org/networking/ip-sysctl.html)
2. [RFC 826 - An Ethernet Address Resolution Protocol](https://www.rfc-editor.org/rfc/rfc826)
