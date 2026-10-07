## Introduction

网络攻击按目的可粗分为三类：破坏**可用性**（DoS/DDoS，让服务无法响应）、破坏**机密性/完整性**（嗅探、欺骗、中间人，窃取或篡改数据）、以及未授权访问。下面是教材中最经典的几种报文级攻击，理解它们也是理解 [TCP 连接管理](/docs/CS/CN/CN.md?id=connection-oriented)、[ARP](/docs/CS/CN/ARP.md) 与 [TLS](/docs/CS/CN/TLS.md) 等防御机制设计动机的最好途径。整体安全属性框架（CIA）见 [Security](/docs/CS/CN/Security.md)。

## IP Spoofing

伪造源 IP 地址发送报文，使目标无法识别真实来源，或让响应被导向被冒充的主机。

- 原理：IP 层本身不认证源地址，攻击者可任意填写 IP 头的 src 字段。配合三次握手缺陷时，攻击者可冒充受信主机（先预测目标的初始序列号，经典 Mitnick 攻击）。
- 放大/反射攻击：伪造源 IP 为受害者，向大量开放服务器发请求，服务器把体积大得多的响应发给受害者（DNS/NTP/memcached 反射放大，放大倍数可达数万）。
- 防御：入口/出口过滤（BCP38/RFC 2827，丢弃源地址不属于本网段的包）、反向路径校验 uRPF（检查源地址路由能否从入接口返回）、随机化初始序列号、不要用源 IP 做身份认证（身份认证必须靠密码学）。

## SYN Flooding

最经典的 DDoS/DoS 手段，攻击 TCP 三次握手：

1. 攻击者不断发送 SYN，但收到 SYN+ACK 后**不回 ACK**（或源 IP 伪造为不可达地址）；
2. 服务器为每个半连接在 SYN 队列（半连接队列）中保留 TCB，等待超时重传（默认重传数次、持续数十秒）；
3. 半连接队列被打满后，正常用户的 SYN 无法入队，服务拒绝。

防御（RFC 4987）：

- **SYN Cookies**：服务器不保存半连接，而是把连接信息编码进 ISN 发回；收到 ACK 时从其确认号还原并校验，合法才建连。代价是部分 TCP 选项在握手期协商受限。
- 调大半连接队列（`tcp_max_syn_backlog`）、减少 SYN+ACK 重传次数（`tcp_synack_retries`）、开启 `tcp_syncookies`；
- 上游清洗：防火墙/负载均衡做 SYN Proxy（先替服务器完成握手再转发）、运营商侧流量清洗、anycast 分散攻击流量；
- 协议层：现代 L4 LB（如 [Pingora](/docs/CS/CN/Pingora.md) 类架构）通常在用户态维护连接表以隔离后端。

## UDP Flooding

UDP 无连接、无握手，攻击者向目标端口发送大量 UDP 包：

- 打满带宽（纯粹的体积型洪水，常配合反射放大，如 DNS 放大）；
- 早期攻击 Chargen/Echo 服务：伪造源 IP 让两个 UDP 服务互发数据形成环路；
- 对类 DNS 服务制造大量无效查询消耗 CPU。

防御：限速与协议白名单（边缘封禁非必要 UDP）、连接追踪（conntrack 限速新流）、上游 DDoS 清洗、DNS 服务开响应速率限制（RRL）与源端口随机化。UDP 应用自身要在应用层做鉴权，不能假设"能到内网就可信"。

## TCP reset attack

TCP 报文头有 RST 位，用于异常关闭连接。攻击者（或链路上的中间盒）若能猜出一个处于连接四元组（src/dst IP+port）的序列号，就可以发送伪造 RST，让双方立即拆除连接：

- 早期 GFW 对加密流量的连接打断即基于此：看到敏感握手包后，注入双向 RST；
- 序列号只需落在对方的接收窗口内即有效（窗口随带宽增大而变大，猜测越来越容易）。

防御：TLS 只保护数据内容、**不能防 RST 打断连接**（RST 在 TCP 层）；实际对抗靠流量混淆（域名前置、代理协议把流量封装在对中间人不透明的会话里）、WireGuard 等 VPN 封装，以及服务端忽略窗口外 RST/校验时间戳等加固。

## Smurf Attack (ICMP Amplification)

> 原文小节标题 "Mock Attack" 应为经典的 **Smurf Attack**（蓝精灵攻击）。

攻击者伪造源 IP 为受害者，向一个广播地址发 ICMP Echo Request；同一广播域内的大量主机同时向受害者回 Echo Reply，形成放大洪水。Fraggle 攻击是其 UDP 版本（目标 Chargen/Echo 端口）。现代网络默认关闭路由器的定向广播转发（`no ip directed-broadcast`），主机也不应响应广播 ping，该攻击已基本绝迹，但"伪造源 IP + 广播/放大"的思路被 DNS 反射攻击继承。

## Man-in-the-Middle Attack

中间人攻击（MITM）：攻击者位于通信双方的路径上，对客户端冒充服务器、对服务器冒充客户端，可以窃听甚至篡改双方数据而不被察觉。

实施手段（按协议层）：

- 链路层：[ARP 欺骗](/docs/CS/CN/ARP.md)（发送免费 ARP 把网关 IP 关联到攻击者 MAC）、DHCP 欺骗（下发恶意网关/DNS）；
- 网络层：BGP 路由劫持、ICMP 重定向；
- 应用层：DNS 劫持/污染（把域名解析到钓鱼站点）、伪造 WiFi 热点（evil twin）；
- 典型套路：在公共 WiFi 上 ARP 欺骗 + 伪造证书弹窗，窃取 HTTP 明文账号密码。

防御：

- **加密通道是根本**：[TLS](/docs/CS/CN/TLS.md) + 证书校验（CA 体系、HSTS 强制 HTTPS、证书钉扎）让中间人拿不出合法证书；
- 网关侧开启 DAI（Dynamic ARP Inspection）、DHCP Snooping 绑定 IP-MAC；
- 敏感服务启用双向认证（mTLS）、DNSSEC/DNS over HTTPS 防解析篡改；
- 用户侧不连不可信热点、警惕证书告警——证书报错正是 MITM 在发生时最直接的信号。

## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [Security](/docs/CS/CN/Security.md)
- [TLS](/docs/CS/CN/TLS.md)
- [ARP](/docs/CS/CN/ARP.md)
- [IP](/docs/CS/CN/IP.md)

## References

1. [RFC 4987 - TCP SYN Flooding Attacks and Common Mitigations](https://datatracker.ietf.org/doc/html/rfc4987)
2. [RFC 2827 - Network Ingress Filtering (BCP38)](https://datatracker.ietf.org/doc/html/rfc2827)
3. [CERT - Smurf IP Denial-of-Service Attacks](https://www.cert.org/advisories/CA-1998-01.html)
