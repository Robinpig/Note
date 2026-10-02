## Introduction

Linux 里"网卡"并不只对应一块物理硬件。**内核把网络设备抽象成 `net_device` 结构体，任何模块都可以注册一个虚拟的 `net_device`**——它没有硬件 / DMA / 中断，收发包靠软件在内存里搬运。这些虚拟设备是容器网络、虚拟化、隧道和软件交换的地基。

本篇按用途串起最常用的几类虚拟设备，并从**内核实现视角**讲它们如何复用协议栈的收发路径：

- **bridge**：一台软件交换机，把多台"主机/容器"接入同一个二层网络；
- **veth**：一对互通的虚拟网卡，是把容器从自己的 network namespace 接回宿主网桥的"网线"；
- **bonding / team**：把多块物理网卡绑成一个逻辑网卡，做冗余与带宽聚合；
- **VLAN（802.1Q）**：在一张物理网卡上划分多个二层广播域；
- **VXLAN / 隧道**：把二层帧封装进 UDP，跨三层网络构建覆盖网络（overlay）。

容器"怎么用"这些设备组网（bridge/host 模式、跨主机方案）见 [Docker 网络](/docs/CS/Container/Docker/net.md) 与 [K8s 网络](/docs/CS/Container/k8s/net.md)，namespace 的创建见 [namespace](/docs/CS/OS/Linux/namespace.md)；本篇聚焦**内核侧它们各自怎么实现收发包**。

## 统一前提：net_device 与收发复用

每个虚拟设备都注册为一个 `net_device`，有自己的 `net_device_ops`。协议栈对它和物理网卡一视同仁：

- 发送时，协议栈照常 `dev_queue_xmit → qdisc → ndo_start_xmit`。对物理网卡，`ndo_start_xmit` 把描述符挂给硬件；**对虚拟设备，`ndo_start_xmit` 是一段纯软件逻辑**——把 SKB 转发、封装或直接注入另一个设备；
- 接收时，虚拟设备需要一个包"凭空"出现在自己的收包路径上，统一用 `netif_rx(skb)` 或 `netif_receive_skb(skb)` 把 SKB 从软件注入协议栈，等价于物理网卡从硬件收到一帧。

理解这两个回调就抓住了全部虚拟设备的本质：**`ndo_start_xmit` 决定"发出去的包软件上怎么处理"，`netif_rx` 决定"怎么让一个包像是被自己收到"**。

## bridge：软件交换机

**bridge 是一台内核里的二层交换机（switch）**。物理网卡、veth 等可以" enslave "（挂载）成 bridge 的端口（port）。bridge 本身也是一个 `net_device`（`br0`），拥有 IP 时它同时是该二层网络的网关。

### 入口：从端口收到帧

普通设备收到帧后走 `netif_receive_skb`，其内部会调用 `rx_handler`。设备被加入 bridge 时，内核给它注册了 `br_handle_frame` 作为 `rx_handler`，于是这个端口收到的帧被截走、交给 bridge 的转发逻辑，而不再按普通三层协议栈处理：

```c
// net/bridge/br_input.c
rx_handler_result_t br_handle_frame(struct sk_buff **pskb)
{
	struct net_bridge_port *p = br_port_get_rcu(skb->dev);
	...
	if (unlikely(is_link_local_ether_addr(dest)))
		return handle_link_local(skb, p);   /* STP 等协议帧本机处理 */

	switch (p->state) {
	case BR_STATE_FORWARDING:
		rh = br_handle_vlan(p, skb, &vid);
		if (rh)
			return rh;
		fallthrough;
	case BR_STATE_LEARNING:
		if (ether_addr_equal(p->br->dev->dev_addr, dest))
			skb->pkt_type = PACKET_HOST;
		NF_HOOK(NFPROTO_BRIDGE, NF_BR_PRE_ROUTING, ...,
			br_handle_frame_finish);
		break;
	default:    /* LISTENING / DISABLED 等状态丢弃 */
		goto drop;
	}
}
```

### 学习与转发：fdb

bridge 维护一张 **fdb（forwarding database，转发数据库）**，等价于交换机的 MAC 地址表：

- **源 MAC 学习**：从某端口收到帧时，记录「源 MAC → 端口」并刷新老化时间（`br_fdb_update`）。下次去往该 MAC 的帧就知道该从哪个端口送出；
- **按目的 MAC 转发**（`br_handle_frame_finish → br_fdb_find_rcu`）：
  - 命中 fdb 且对应端口明确 → 只从该端口**单播**送出（`br_forward`）；
  - 未命中（未知单播）或目的是广播 / 组播 → 从除入端口外的所有端口**泛洪**（`br_flood`）；
  - 目的 MAC 是 bridge 自己（如网关流量）→ 上交本机协议栈（`br_pass_frame_up`，把 `skb->dev` 改写为 `br0` 再走 `netif_rx`）。

### STP：避免环路

多台 bridge 用多条链路连接会形成二层环路，广播帧无限循环。bridge 实现了 **STP（spanning tree protocol，802.1D）**：交换 BPDU、选举根桥、把部分端口置为 blocking（只收 BPDU、不转发数据），逻辑上断环。端口状态机 `DISABLED → LISTENING → LEARNING → FORWARDING` 决定一个端口能否学习和转发。现代部署常用无环的上层设计或 RSTP/MSTP。

### 端口隔离与 VLAN

bridge 还支持 port isolation（端口之间互不可达、只能上行）和 per-port VLAN（`br_handle_vlan`，结合下一节的 802.1Q），用于精细的二层隔离。

## veth：一根虚拟网线的两头

**veth 是成对出现的虚拟网卡（veth pair）**，从一头 `ndo_start_xmit` 发出的包，会立刻从另一头的接收路径冒出来，像一根两端各插一个设备的网线。它的实现极简：

```c
// drivers/net/veth.c
static netdev_tx_t veth_xmit(struct sk_buff *skb, struct net_device *dev)
{
	struct veth_priv *rcv_priv, *priv = netdev_priv(dev);
	struct net_device *rcv = rcu_dereference(priv->peer);
	...
	rcv_priv = netdev_priv(rcv);
	if (rcv_priv->rx_handler)
		napi = &rcv_priv->napi;
	...
	if (napi)                    /* 对端是 bridge 端口，走 NAPI 批量注入 */
		veth_forward_skb(rcv, skb, napi, rcv_priv->xdp_prog);
	else                        /* 普通注入对端协议栈 */
		netif_rx(skb);
	...
}
```

注意转发目标是 `priv->peer`（配对的另一头），把 `skb->dev` 改写为 peer 后注入。它在容器组网里的标准用法：

1. 创建 veth pair，一头放在宿主、一头放进容器的 network namespace；
2. 宿主那头 `enslave` 到 `br0`，容器那头配 IP、设默认路由；
3. 容器发包：从容器内 eth0（veth 一头）发出 → peer 端（宿主）收到 → peer 是 bridge 端口，`rx_handler = br_handle_frame` 把帧交给 bridge → 按 fdb 从接外网的上行口送出。回程相反。

较新内核为 veth 引入了 NAPI 收包（`veth_poll`）和 XDP 支持（`veth_forward_skb` 里的 `xdp_prog`），让容器高 PPS 场景能批量化、并在驱动层跑 XDP，而不是每个包都立即走 `netif_rx`。

## bonding / team：多网卡绑定

**bonding 把多块物理网卡聚合成一个逻辑 `net_device`（`bond0`）**，提供：

- **容错**：活动链路断开自动切到备用（active-backup 模式）；
- **带宽叠加 / 负载分担**：按流哈希（L2/L3/L4 字段）把不同连接散到不同成员网卡（802.3ad LACP、xor 模式）。

实现上，成员网卡的 `rx_handler` 被设为 `bond_handle_frame`，收帧时把 `skb->dev` 改写为 `bond0` 上交，使上层只见一个接口；发送时 bond 的 `ndo_start_xmit` 按模式选一个成员实际发出。**team** 是 bonding 的现代化替代：把策略（选路、链路检测）做成 userspace 程序，内核只保留精简的快速路径，扩展性更好。云环境里 bond 常用于保证管理网 / 业务网高可用。

## VLAN（802.1Q）：一网卡划分多网段

**802.1Q VLAN 在以太网帧头插入 4 字节 VLAN tag（VID 1~4094）**，让一张物理网卡承载多个相互隔离的二层网络。内核为每个 VID 创建一个 `vlan` 类型的 `net_device`（如 `eth0.100`）：

- 发送：往 `eth0.100` 发包，其 `ndo_start_xmit`（`vlan_dev_hard_start_xmit`）在帧头压入 tag（或利用网卡的 VLAN offload，只在描述符里标记），再交给底层 `eth0`；
- 接收：`eth0` 收到带 tag 的帧，`vlan_untag` / `__netif_receive_skb` 按 VID 找到对应 `eth0.100`，把 `skb->dev` 重定向给它上交，于是各 VLAN 的协议栈处理彼此独立。

现代网卡普遍支持 VLAN tag 的插入 / 剥离 offload，快路径里 tag 不实际进 skb 数据，而记录在 `skb->vlan_tci`，由硬件完成。

## VXLAN 与隧道：跨三层的 overlay

二层网络受限于物理范围，且 VLAN 只有 4094 个。**VXLAN 把整个二层帧封装进 UDP（目的端口 4789），加 8 字节 VXLAN header（含 24 bit VNI，约 1600 万段），通过底层三层 IP 网络（underlay）送达另一台宿主机**，再解封装还原原始帧。对容器而言，这让分布在不同宿主机上的容器像接在同一个大二层交换机里。

内核 `vxlan` 设备的两端：

- 发送（`vxlan_xmit`）：按内层目的 MAC 查 VXLAN 自己的 fdb，得到远端宿主机的 underlay IP；找不到就组播 / 借由入口学习。然后把原始帧作为 UDP payload，外层填本地 VTEP → 远端 VTEP，经普通 UDP/IP 路径发出；
- 接收：底层 UDP socket（由 VXLAN 设备监听）收到 VXLAN 包，`vxlan_rcv` 校验 VNI、剥掉外层封装，把内层帧注入该 VNI 对应的本地处理（找到 vxlan 设备，必要时再交给本机 bridge / 容器 veth）。

同源思想的其它隧道设备：**ipip/gre/gretap**（把 IP 或以太网帧封进 IP/GRE）、**geneve**（比 VXLAN 更灵活的可扩展封装，Open vSwitch 默认）、**wireguard**（加密的三层隧道）。它们都是"`ndo_start_xmit` 里加封装、对端 socket 收到后解封装注入"这一模式的变体。

## Links

- [netfilter](/docs/CS/OS/Linux/net/netfilter.md)
- [Qdisc](/docs/CS/OS/Linux/net/Qdisc.md)
- [socket](/docs/CS/OS/Linux/net/socket.md)
- [namespace](/docs/CS/OS/Linux/namespace.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

- [Linux Bridge — Kernel documentation](https://docs.kernel.org/networking/bridge.html)
- [Virtual eXtensible Local Area Network (VXLAN), RFC 7348](https://datatracker.ietf.org/doc/html/rfc7348)
- [Linux Networking documentation: veth, bonding](https://docs.kernel.org/networking/index.html)
