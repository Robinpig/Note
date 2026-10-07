## Introduction

netlink 是内核与用户态进程之间的一种**基于 socket 的双向 IPC 机制**：它本身是一个协议族（`AF_NETLINK`），用户态用普通 socket API 收发，但对端不是另一台主机，而是内核（或别的用户态进程）。相比老式的 `ioctl`，它具备**双向、可多播、消息可扩展、缓冲区队列化**的优势，因此成为网络配置、设备事件、审计等子系统对外的统一通道。

可以这样定位它在本目录的角色：[Route](/docs/CS/OS/Linux/net/Route.md) 讲"路由表怎么查"，而增删路由的命令 `ip route` 之所以能改到内核，正是通过 netlink 的 **rtnetlink** 子协议；[udev](/docs/CS/OS/Linux/dev/udev.md) 监听设备 add/remove 也是靠 netlink。本篇讲 netlink 机制本身。

## Protocol Family and Address

打开一个 netlink socket 时要指定**子协议号**（协议族是 `AF_NETLINK`，类型通常 `SOCK_RAW`/`SOCK_DGRAM`）：

```c
socket(AF_NETLINK, SOCK_RAW | SOCK_CLOEXEC, NETLINK_ROUTE);
```

`include/uapi/linux/netlink.h` 里的主要子协议：

| 子协议 | 号 | 用途 |
| :-- | :-- | :-- |
| `NETLINK_ROUTE` | 0 | rtnetlink：路由、网卡、地址、邻居等网络配置 |
| `NETLINK_USERSOCK` | 2 | 用户态进程之间通信 |
| `NETLINK_SOCK_DIAG` | 4 | socket 监控（ss 背后，别名 `NETLINK_INET_DIAG`） |
| `NETLINK_XFRM` | 6 | IPsec 策略/状态 |
| `NETLINK_AUDIT` | 9 | 审计子系统 |
| `NETLINK_KOBJECT_UEVENT` | 15 | 内核设备事件（udev） |
| `NETLINK_GENERIC` | 16 | generic netlink：新子系统的复用入口 |
| `NETLINK_NETFILTER` | 12 | netfilter 内部配置 |

通信地址是 `sockaddr_nl`：

```c
struct sockaddr_nl {
	__kernel_sa_family_t	nl_family;  // AF_NETLINK
	unsigned short		nl_pad;
	__u32			nl_pid;     // 端口标识（通常取进程 pid）；内核端为 0
	__u32			nl_groups;  // 多播组掩码（订阅事件用）
};
```

- **单播**：`nl_pid` 标识对端，发给内核时内核端 `pid=0`；
- **多播**：进程把 `nl_groups` 置上相应位加入组，内核一次广播、所有订阅者收到——状态变化通知不必逐个进程查询，这正是 netlink 相对 ioctl 的关键优势。

## Message Format

每条消息以固定的 `nlmsghdr` 开头，后接按 4 字节对齐的有效载荷：

```c
struct nlmsghdr {
	__u32		nlmsg_len;   // 整条消息长度（含头部）
	__u16		nlmsg_type;  // 消息类型
	__u16		nlmsg_flags; // 标志
	__u32		nlmsg_seq;   // 序列号（请求/应答配对、dump 一致性）
	__u32		nlmsg_pid;   // 发送方端口
};
```

通用控制类型（`< NLMSG_MIN_TYPE(0x10)` 为保留）：`NLMSG_NOOP`(0x1) 空操作、`NLMSG_ERROR`(0x2) 错误/ACK、`NLMSG_DONE`(0x3) 一次 dump 结束、`NLMSG_OVERRUN`(0x4) 数据丢失。

常用 flags：

| flag | 值 | 含义 |
| :-- | :-- | :-- |
| `NLM_F_REQUEST` | 0x01 | 这是一个请求 |
| `NLM_F_MULTI` | 0x02 | 多部分消息，以 NLMSG_DONE 收尾 |
| `NLM_F_ACK` | 0x04 | 要求内核回复 ACK |
| `NLM_F_DUMP` | 0x100\|0x200 | 请求导出整张表（如列出全部路由） |
| `NLM_F_CREATE` / `EXCL` | 0x400 / 0x20 | 新建 / 已存在则不碰 |
| `NLM_F_REPLACE` | 0x100 | 替换已有项 |

一个 socket buffer 里可连续放多条消息（用 `NLMSG_NEXT` 遍历、`NLMSG_OK` 校验）；消息长度按 `NLMSG_ALIGN` 对齐。错误 / ACK 用 `nlmsgerr`（含错误码与原消息头），新版还能携带可读错误串、出错属性偏移等扩展信息（`NETLINK_EXT_ACK`）。

## Attribute TLV

载荷普遍用 **TLV（type-length-value）** 属性承载，便于向后兼容地增删字段：

```c
struct nlattr {
	__u16		nla_len;   // 含头部的总长
	__u16		nla_type;  // 类型；高位 NLA_F_NESTED / NLA_F_NET_BYTEORDER
};
```

- 属性可嵌套（`NLA_F_NESTED`），形成层级结构；
- 内核侧用 **nla_policy** 声明每个属性的类型与取值 / 长度范围，接收时统一校验，越界即拒绝；
- 这套"头部 + 可空属性 + 策略校验"使 netlink 消息可以在不破坏旧程序的前提下持续扩展。

## rtnetlink

`NETLINK_ROUTE` 是最常用的子系统，`ip` 命令即其前端。它围绕几类对象定义消息：

- 链路（网卡）：`RTM_NEWLINK` / `DELLINK` / `GETLINK`；
- 地址：`RTM_NEWADDR` / `DELADDR`；
- 路由：`RTM_NEWROUTE` / `DELROUTE`（最终落到 [FIB](/docs/CS/OS/Linux/net/Route.md) 的 `fib_table_insert()`）；
- 规则、邻居、QDISC 等同理。

链路状态变化（up/down、地址增删、路由更新）内核会**反向多播**给订阅者——这就是为什么监听 rtnetlink 的程序能实时感知网络拓扑变化。

## Generic Netlink

当一个新内核功能需要 netlink 通道但又不想占用稀缺的子协议号时，统一走 `NETLINK_GENERIC`：它是一个复用层，子系统先注册一个**家族名（family）**，由家族内自己定义命令、属性与多播组。多数现代子系统优先选 generic netlink 而非新增 `NETLINK_*` 号。

## Key Implementation Points on the Kernel Side

- netlink 在内核里也是一种 socket（`netlink_create`），每个子系统注册 `struct netlink_kernel_cfg` 与接收回调；
- 发送到内核的消息先进入接收队列、由回调解析（多在进程上下文，可睡眠、可取 `capable()` 鉴权）；
- 内核主动通知用 `nlmsg_multicast()` 广播；接收缓冲不足时用户态会收到 `ENOBUFS`（dump 被中断，对应 `NLM_F_DUMP_INTR`）；
- 还支持把收发缓冲 **mmap** 成环形帧（`NETLINK_RX_RING`/`TX_RING`），减少高频场景的拷贝。

## Links

- [网络知识地图](/docs/CS/OS/Linux/net/README.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

1. [RFC 3549 - Linux Netlink as an IP Services Protocol](https://www.rfc-editor.org/rfc/rfc3549)
2. [内核文档：Netlink](https://docs.kernel.org/networking/netlink.html)
3. [kernel.org netlink.h](https://github.com/torvalds/linux/blob/master/include/uapi/linux/netlink.h)
