## Introduction

VPN（Virtual Private Network，虚拟专用网络）在公共网络（互联网）之上构建一条逻辑上的"专用通道"：通信双方虽然走的是公网链路，但通过**隧道封装 + 加密 + 身份认证**，获得了类似物理专线的机密性、完整性与身份可信，而成本远低于拉专线。典型用途：分支机构互联（site-to-site）、远程员工接入内网（remote access）、跨云 VPC 互通。

三个核心机制：

- **隧道（Tunnel）**：把原始报文（内层 IP 包）当作数据，再封装一层外层协议头通过公网转发；到达对端后解封装。封装本身不提供安全，安全来自加密。
- **加密与完整性**：对封装报文加密并做 MAC/认证，防嗅探与篡改，密码学基础见 [TLS](/docs/CS/CN/TLS.md)。
- **认证与密钥协商**：通信前确认对端身份并协商会话密钥（IKE 等握手协议）。

## 构建技术

主流的三类隧道技术：PPTP、IPsec、SSL/TLS VPN。

### PPTP VPN

PPTP（Point-to-Point Tunneling Protocol，RFC 2637）由微软推动，曾是 Windows 自带的远程接入方案：在 TCP 1723 上建立控制通道，PPP 帧用 GRE（IP 协议号 47）封装传输，认证沿用 PPP 的 PAP/CHAP/MS-CHAPv2。

缺点使它已被淘汰：控制面基于 TCP、设计年代早，MS-CHAPv2 已被证明可快速破解，MPPE 加密强度弱（RC4/128bit），GRE 还常被 NAT/防火墙拦截。新系统不应再部署。

### IPsec VPN

IPsec 工作在**网络层**，对任意 IP 报文提供保护，对上层应用透明（应用无需改造）。它不是单一协议而是协议族：

- **AH**（认证头，协议号 51）：只保证完整性与来源认证，不加密；NAT 会改 IP 导致校验失败，实践中几乎被 ESP 取代。
- **ESP**（协议号 50）：加密 + 认证，是实际使用的协议。
- **IKE**（Internet Key Exchange，UDP 500/4500）：协商加密算法、完成双向认证（预共享密钥或证书）、建立密钥，分主模式/快速模式两阶段（IKEv1）；IKEv2 大幅简化并支持 MOBIKE（移动网络切换不掉线）。

两种工作模式：

| 模式 | 保护范围 | 场景 |
|------|---------|------|
| Transport | 只加密 IP 载荷，保留原 IP 头 | 两台主机间通信 |
| Tunnel | 整个原始 IP 包加密后再加新 IP 头 | 网关到网关（site-to-site），内网地址穿越公网 |

IPsec 是企业分支互联、云厂商 VPN 网关的标准方案；难点在策略配置复杂、双 NAT 场景要开 NAT-T（ESP over UDP 4500）。

### SSL/TLS VPN

利用 [TLS](/docs/CS/CN/TLS.md)（TCP 443）在**应用层/传输层**建隧道，客户端只需浏览器或轻量 agent，无需预装协议栈，也几乎不被防火墙拦截（443 永远开着）。两种形态：

- **Clientless**：通过网页门户直接访问内网 Web 应用、书签、文件共享；
- **Tunnel mode（AnyConnect/OpenConnect 类）**：装一个轻量客户端，装上虚拟网卡，把路由到内网的流量送入 TLS 隧道，体验接近 IPsec 但部署更简单。

OpenVPN（TLS + 虚拟 TUN/TAP 网卡）、WireGuard（UDP + 现代密码学，代码仅数千行、性能高、内核内置）属于这一路线的现代演进；企业产品（Pulse/FortiClient/AnyConnect）多为 SSL VPN。

### 技术对比

| 维度 | PPTP | IPsec | SSL/TLS VPN（含 WireGuard） |
|------|------|-------|------------------------------|
| 工作层 | 数据链路（PPP/GRE） | 网络层（IP） | 应用/传输层（也可虚拟网卡到网络层） |
| 加密 | MPPE，已不安全 | ESP（AES 等），强 | TLS 1.2/1.3 或现代 AEAD，强 |
| 穿透 NAT/防火墙 | 差（GRE） | 需 NAT-T/UDP 500,4500 | 好（443） |
| 客户端 | 系统自带但已淘汰 | 配置复杂，网关场景为主 | 浏览器/轻客户端，部署快 |
| 典型场景 | （淘汰） | site-to-site、云 VPN | 远程办公接入 |

## 注意区分

- VPN 解决的是**通道可信**，不等于访问控制：接入内网后仍要靠零信任（ZTNA，按身份与设备状态逐次授权）限制横向移动；
- 反向代理 / SOCKS 代理只转发流量、默认不加密不鉴权，不是 VPN；
- 专线（如 MPLS）由运营商保证隔离但不加密；VPN 用密码学在公网上模拟专线效果。

## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [TLS](/docs/CS/CN/TLS.md)
- [Security](/docs/CS/CN/Security.md)
- [IP](/docs/CS/CN/IP.md)

## References

1. [RFC 4301 - Security Architecture for IP](https://datatracker.ietf.org/doc/html/rfc4301)
2. [WireGuard 论文与白皮书](https://www.wireguard.com/papers/wireguard.pdf)
