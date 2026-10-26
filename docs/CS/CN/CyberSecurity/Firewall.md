## Introduction

防火墙是网络层的"门卫"：依据规则集决定哪些报文可以进出边界。它与 [IDS/IPS](/docs/CS/CN/CyberSecurity/IDS_IPS.md) 的分工是经典的一对——防火墙做**访问控制**（允许/拒绝），检测系统做**发现与告警**（看到了什么异常）；与 WAF（应用层规则，见 [nginx security](/docs/CS/CN/nginx/security.md)）的差别是作用的层。Linux 内核里的实现细节（netfilter 钩子、连接跟踪表）在 [netfilter](/docs/CS/CN/Tools/netfilter.md)，本页讲概念谱系、拓扑与工程演进。

## The Firewall Family

按"看得多深"排成谱系，每一代都是被上一代的盲区逼出来的：

| 类型 | 判定依据 | 盲区 |
| :--- | :--- | :--- |
| 无状态包过滤 | 逐报文看源/目的 IP、端口、协议号 | 不懂连接方向，应答流要手动放行；伪造源 IP 即可绕过 |
| 状态检测 | 跟踪连接状态（conntrack），应答流自动放行 | 只看 L3/L4，不解析应用载荷 |
| 应用代理 | 代替客户端建连、检查应用层请求 | 性能差、每协议要一个代理；HTTPS 普及后大幅退场 |
| 下一代防火墙（NGFW） | 应用识别（App-ID）、用户身份、集成 IPS、TLS 解密后检查 | TLS 1.3 + ECH 正在削弱解密检查；成本与复杂度高 |

部署位置也分两路：**网络边界防火墙**（专用 appliance，守 DMZ 与互联网出口）与**主机防火墙**（每台机器本地，云上就是 security group——有状态虚拟防火墙，附着在实例/网卡上）。现代架构两者并用：边界挡洪泛与扫描，主机防火墙限制横向移动——后者才是零信任"默认不信任内网"的执行点（VPN 的边界失效问题见 [VPN](/docs/CS/CN/VPN.md)）。

## Zones and DMZ

防火墙的核心概念是**区域（zone）**：把网络按信任级别划段（untrust / dmz / trust），段间默认拒绝、按需放行。DMZ 是给"必须对外暴露、又不该放进内网"的服务（公网 Web、邮件网关）准备的中间段：

```dot
digraph dmz {
  rankdir=LR; node [shape=box, style=rounded, fontname="Helvetica"];
  inet [label="Internet", shape=ellipse, fillcolor="#f5e6e6"];
  fw1 [label="边界防火墙", fillcolor="#e8eef8"];
  dmz [label="DMZ\n公网 Web / 邮件网关", fillcolor="#f8f0e8"];
  fw2 [label="内部防火墙", fillcolor="#e8eef8"];
  lan [label="内网\n应用 / 数据库", fillcolor="#e8f0e8"];
  inet -> fw1 -> dmz;
  dmz -> fw2 -> lan;
  inet -> fw1 [label="仅 80/443", style=dashed];
}
```

实践要点：

- **默认拒绝 + 白名单**。唯一可维护的策略形态；黑名单策略等于没有策略；
- **方向要对称地看**：只守 ingress 不守 egress 的网络，出站被植入恶意软件后可以任意回连。出口过滤（限制出站目的端口、禁已知恶意 IP）是被低估的高价值规则；
- **规则顺序即语义**：多数防火墙首条命中即止，规则腐化（十年累积、彼此覆盖、注释缺失）是审计重灾区，NIST SP 800-41 的"防火墙策略审查"专讲这件事。

## Stateful Inspection

状态检测的底座是**连接跟踪（conntrack）**：为每条流维护五元组状态表，首包建表、后续报文查表、超时回收。带来的能力与代价：

- TCP 握手状态可精确识别（NEW / ESTABLISHED / RELATED / INVALID），非法标志组合（如 XMAS 扫描）直接按 INVALID 丢弃；
- FTP 等"控制通道协商数据端口"的协议需要 ALG（应用层网关）辅助，否则数据连接会被状态表拦掉；
- **跟踪表是资源、也是攻击面**：SYN flood（见 [Attack](/docs/CS/CN/Attack.md)）打的正是半连接表；表满时新流被拒，是 DoS 的直接形态；
- 非对称路由（同一流的进出路径不同）会让流在不同网关上各建一半状态，表现为"随机丢包"——排查这类问题的标准动作是看 conntrack 计数与超时。

## Linux Firewalling

Linux 侧的事实（2026-10 核实）：

- **netfilter** 是内核报文处理框架，在 PREROUTING / INPUT / FORWARD / OUTPUT / POSTROUTING 五个钩子处回调规则，细节见 [netfilter](/docs/CS/CN/Tools/netfilter.md)；
- **nftables 是现行前端**：统一了 iptables / ip6tables / arptables / ebtables 四套工具与规则链，原生支持集合（set）与映射、原子加载整表、大规则集下查找从 O(n) 变 O(1)。Debian 10+、RHEL/AlmaLinux 8+（firewalld 默认后端即 nftables）、Ubuntu 20.10+ 的默认 iptables 后端均已切到 nftables；
- **iptables 仍在，但多为兼容层**：现代发行版的 `iptables` 命令背后是 iptables-nft 翻译器，规则实际落在 nftables 表里。两套工具混管同一内核是经典事故源；
- 前端选择：firewalld（zone 模型，RHEL 系默认）、ufw（极简，Ubuntu 默认）、裸 `nft`（配置文件最透明）。

一段最小可用的 nftables 基线，体现了状态检测 + 默认拒绝的全部要素：

```shell
table inet filter {
  chain input {
    type filter hook input priority 0; policy drop;
    iif lo accept
    ct state established,related accept
    ct state invalid drop
    tcp dport { 22, 80, 443 } accept
  }
  chain forward { type filter hook forward priority 0; policy drop; }
  chain output { type filter hook output priority 0; policy accept; }
}
```

## eBPF and XDP

内核数据路径的新前沿是 **eBPF/XDP**：XDP（eXpress Data Path）把可编程处理点前移到网卡驱动收包后、协议栈之前，在分配 skb 之前就能丢包，是软件侧能做到的最早处理位置。

- **DDoS 清洗**：Cloudflare、Meta 等用 XDP/eBPF 在边缘以线速丢恶意流量，绕过完整协议栈的每字节成本；
- **云原生网络**：Cilium 用 eBPF 实现 Kubernetes 的 Service 负载均衡与 NetworkPolicy（替代 kube-proxy 的 iptables 路径），策略直接挂在 L3/L4 上、无需逐规则翻译；
- 与 netfilter 的关系不是取代而是分层：XDP 管"最前置的粗粒度丢弃"，conntrack/nftables 继续管有状态的细粒度策略。

## NAT as a Side Effect

防火墙与 NAT 在实现上同源（都在钩子处改写报文），工程上常被混为一谈：SNAT/masquerade 隐藏内网地址，DNAT/端口映射把公网请求导进 DMZ。NAT 对 [IPsec/VPN](/docs/CS/CN/VPN.md) 是麻烦（ESP 无端口，需 NAT-T 封装到 UDP 4500），对连接跟踪是负担（NAT 表与 conntrack 表互相依赖）。安全边界上要记住：NAT 不是安全机制——"内网不可达"只是路由副作用，不是访问控制。

## Limitations

防火墙的盲区决定了纵深防御的必要性（全景见 [Security](/docs/CS/CN/Security.md)）：

- **加密流量**：HTTPS 占比超过九成的今天，传统防火墙只看 L3/L4；TLS 1.3 的加密 ClientHello（ECH）正在把"解密后检查"这条路也变窄；
- **应用层漏洞**：放行了 80/443 不等于防住 Web 漏洞——那是 WAF 与安全开发的事（见 [nginx security](/docs/CS/CN/nginx/security.md) 与 OWASP Top 10 的攻击分类）；
- **规则腐化**：规则只增不减、注释缺失、来源不可考，是几乎所有老化网络的共性；
- **单点依赖**：防火墙策略写错（把自己锁在外面、放行了不该放行的）影响面是全边界，变更需要灰度与回滚预案。

## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [netfilter](/docs/CS/CN/Tools/netfilter.md)
- [IDS IPS](/docs/CS/CN/CyberSecurity/IDS_IPS.md)
- [nginx security](/docs/CS/CN/nginx/security.md)
- [VPN](/docs/CS/CN/VPN.md)

## References

1. [NIST SP 800-41 Rev. 1 - Guidelines on Firewalls and Firewall Policy](https://csrc.nist.gov/pubs/sp/800/41/r1/final)
2. [nftables Wiki](https://wiki.nftables.org)
3. [Cloudflare Blog - XDP: eXpress Data Path](https://blog.cloudflare.com/xdp-ebpf-and-you/)
4. [Cilium Documentation - eBPF Datapath](https://docs.cilium.io/en/stable/network/ebpf/)
