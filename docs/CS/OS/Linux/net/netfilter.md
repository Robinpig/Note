## Introduction

netfilter 是内核协议栈里的**包过滤框架**：它在协议栈处理包的关键位置预留挂载点（hook），允许模块把回调函数挂上去，对经过的每个包做检查、修改、丢弃或排队。我们平时说的防火墙（iptables/nftables）、连接跟踪（conntrack）、NAT，本质都是挂在 netfilter 上的模块。

它不是独立于协议栈的旁路，而是被协议栈代码用 `NF_HOOK()` 直接调用——见 [network](/docs/CS/OS/Linux/net/network.md) 收发路径中的 `NF_INET_PRE_ROUTING`、`NF_INET_LOCAL_IN`、`NF_INET_LOCAL_OUT`、`NF_INET_POST_ROUTING` 四处。概念与运维侧的入门笔记见 [netfilter 概念](/docs/CS/CN/Tools/netfilter.md)，本篇聚焦内核实现。

## 五个挂载点

对 IPv4/IPv6，netfilter 定义五个钩子（`NF_INET_*`），对应包在协议栈里的五个时机：

| 挂载点 | 时机 | 典型用途 |
| :-- | :-- | :-- |
| `PRE_ROUTING` | 刚进入协议栈、路由判定之前 | DNAT、conntrack 建条目 |
| `LOCAL_IN` | 已判定为本机收、交给传输层之前 | 入站过滤（INPUT 链） |
| `FORWARD` | 判定为要转发、非本机 | 转发过滤 |
| `LOCAL_OUT` | 本机进程发出、刚进入协议栈 | 出站过滤（OUTPUT 链） |
| `POST_ROUTING` | 路由之后、交给网卡之前 | SNAT/Masquerade |

两条主路径：

- **本机收发**：入向 `PRE_ROUTING → LOCAL_IN`；出向 `LOCAL_OUT → POST_ROUTING`；
- **转发**：`PRE_ROUTING → FORWARD → POST_ROUTING`。

## NF_HOOK 调用机制

协议栈不直接遍历规则，而是在固定位置调一个宏。以接收为例：

```c
return NF_HOOK(NFPROTO_IPV4, NF_INET_PRE_ROUTING,
               net, NULL, skb, dev, NULL, ip_rcv_finish);
```

`NF_HOOK` 的关键约定（来自 `include/linux/netfilter.h`）：

- 若该挂载点没有注册任何回调，**直接调用 `okfn`**（这里是 `ip_rcv_finish`），开销极小；新版用 jump label（`nf_hooks_needed`）把这个判断优化到几乎零成本；
- 否则构造一个 `nf_hook_state`（记录 `pf`、`hook`、入/出设备 `in`/`out`、关联 socket `sk`、network namespace `net` 和 `okfn`），进入 `nf_hook_slow` 依次执行该点的回调数组；
- 全部回调放行后，才调用 `okfn` 让协议栈继续往下走。

同一个挂载点可注册多个回调，按 `nf_hook_ops.priority` **升序**排成 `nf_hook_entries`（注册时构建、读多写少，读路径在 RCU 下直接遍历紧凑数组，避免链表的缓存不友好）。模块通过 `nf_register_net_hook()` 注册，每个回调可声明类型（`NF_HOOK_OP_NF_TABLES` / `_NAT` / `_BPF` 等）。

## verdict

每个回调返回一个裁决值，决定包的命运：

| verdict | 含义 |
| :-- | :-- |
| `NF_ACCEPT` | 放行，继续下一个回调 |
| `NF_DROP` | 丢弃，释放 SKB |
| `NF_STOLEN` | 包被回调接管，协议栈不再处理（如排队到用户态） |
| `NF_QUEUE` | 送队列给用户态处理（NFQUEUE） |
| `NF_REPEAT` | 重新执行当前回调 |

非 `NF_ACCEPT` 的返回都会中断后续链。

## 连接跟踪 conntrack

conntrack 是 NAT 和有状态过滤的基础：它为每条"流"维护一个状态条目 `nf_conn`，用 **tuple（源/目的 IP、端口、协议号）** 唯一标识，区分原始方向与应答方向（双向 tuple）。

- 在 `PRE_ROUTING`/`LOCAL_OUT` 处，conntrack 先查包是否属于已有流，否则新建"未确认"条目；在包离开前（`POST_ROUTING`/`LOCAL_IN`）`confirm` 正式落表；
- 状态机：`NEW → ESTABLISHED`，并跟踪 `RELATED`（如 FTP 数据连接、ICMP 错误）、`TIME_WAIT`、`CLOSE` 等；分片包需先做 defrag 才能跟踪；
- 条目记录在网络命名空间内的哈希表，受超时与表容量上限约束（超限导致丢包，常见 `nf_conntrack: table full`）；
- 运维查看：`conntrack -L`、`/proc/net/nf_conntrack`，调 `nf_conntrack_max`。

## NAT

NAT 依赖 conntrack：在连接的首包上改写地址/端口并把映射记进 `nf_conn`，同一条流的后续包及应答方向自动套用反向映射。

- **DNAT** 在 `PRE_ROUTING`（让本机/后端收到改了目标的包）；**SNAT / Masquerade** 在 `POST_ROUTING`；
- Masquerade 是 SNAT 的特化：出口 IP 动态时自动用当前出接口地址，拨号/云场景常用；
- NAT 只能对"连接的首包"建立映射，因此规则顺序与 conntrack 状态密切相关。

## 前端：iptables 与 nftables

netfilter 只提供内核机制，规则如何写由前端决定：

- **iptables**：表（filter/nat/mangle…）+ 链（对应五个挂载点）+ 匹配/动作的老式结构，每个协议（v4/v6）各一套，扩展靠模块；
- **nftables**（现代替代，命令 `nft`）：用一个虚拟机在内核执行规则、统一 IPv4/IPv6、支持集合/字典与动态集，语义更规整；iptables 命令在新系统上常由 nftables 后端兼容。

容器场景大量依赖 netfilter：Docker 用 DNAT + proxy 实现端口映射，Kubernetes 的 [kube-proxy](/docs/CS/Container/k8s/kube-proxy.md) 早期用 iptables、后转向 IPVS 来做 Service 的负载均衡。

## Links

- [网络知识地图](/docs/CS/OS/Linux/net/README.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

1. [netfilter 项目官网](https://netfilter.org/)
2. [nftables 文档](https://wiki.nftables.org/)
