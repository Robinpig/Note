## Introduction

DNS（Domain Name System，域名系统）是一个分布式的客户端/服务器网络数据库，供 TCP/IP 应用程序在主机名与 IP 地址之间（以及反向）相互映射，并提供电子邮件路由信息、服务命名等能力。

> 由于准确性至关重要，AXFR 区域传送请求必须使用 TCP 或其他可靠协议。

在绝大多数情况下，DNS 都使用 UDP 协议通信，协议设计之初也推荐域名解析优先使用 UDP。实际上，DNS 不仅使用 UDP，也使用 TCP：

1. 设计之初就在区域传输中引入 TCP，常规查询使用 UDP；
2. 当响应超过 512 字节上限时，规范首次明确「查询被截断应使用 TCP 重试」；
3. 随后引入的 EDNS 机制允许 UDP 最多传输 4096 字节，但受 MTU 限制易分片丢包，仍不够可靠；
4. 近年规范规定 DNS 应同时支持 UDP 与 TCP，TCP 不再是仅用于重试的备选。

DNS 是一个以层级 DNS 服务器实现的分布式数据库，同时也是一种允许主机查询该数据库的应用层协议。DNS 服务器多为运行 BIND（Berkeley Internet Name Domain）软件的 UNIX 主机 [BIND 2016]，协议基于 UDP、使用 53 端口。

除主机名到 IP 地址的转换外，DNS 还提供几项重要服务：

- 主机别名（Host aliasing）
- 邮件服务器别名（Mail server aliasing）
- 负载均衡（Load distribution）

DNS 解析流程：

1. 先询问本地 DNS 服务器（local DNS server），若已有缓存的 IP 则直接返回；
2. 本地服务器再向根 DNS 服务器（root）发起查询，逐级遍历各子域 DNS 服务器取得目标 IP，缓存到本地后返回给客户端。

## Implementation

DNS 最简单的设计是只用一台服务器保存全部映射。尽管简单，但对今天规模庞大且持续增长的互联网主机而言并不合适。集中式设计的问题包括：

- 单点故障（single point of failure）；
- 流量集中（traffic volume）；
- 远程集中数据库会导致显著时延（distant centralized database）；
- 维护困难（maintenance）。

总而言之，单台 DNS 服务器的集中式数据库根本无法扩展，因此 DNS 从设计上就是分布式的。

### Distributed, Hierarchical Database

DNS 服务器按层级分为三类：

- 根 DNS 服务器（Root DNS servers）
- 顶级域服务器（Top-level domain, TLD servers）
- 权威 DNS 服务器（Authoritative DNS servers）

此外还有一类重要的本地 DNS 服务器（local DNS server）。它并不严格属于上述层级，却是 DNS 架构的核心：它代理客户端的递归查询，并缓存结果。

### Caching

DNS 大量利用缓存来改善时延性能、减少在互联网上兜圈子的 DNS 报文数量。常见的诊断与配置命令：

```shell
cat /etc/hosts                        # 本地静态主机名映射
cat /etc/resolv.conf | grep nameserver  # 查看本机配置的 DNS 服务器
nslookup example.com                  # 交互式查询
dig example.com +trace                # 显示完整解析链路
drill example.com                     # 类似 dig 的查询工具
systemctl restart networking          # 重启网络（修改 resolv.conf 后）
```

Java 程序也会缓存 DNS 解析结果（`InetAddress` 内部维护缓存）。为避免每次网络调用都重新解析，建议使用单例（singleton）复用同一 `InetAddress` 实例。

## DNS Records and Messages

共同实现 DNS 分布式数据库的各类服务器，存储着资源记录（Resource Records, RRs），其中包括提供主机名到 IP 地址映射的记录。

一条资源记录是一个四元组，包含以下字段：

```
(Name, Value, Type, TTL)
```

TTL（Time To Live）表示该资源记录的生存时间，决定它何时应从缓存中移除；下面的示例记录忽略 TTL 字段。Name 与 Value 的含义取决于 Type：

- 若 Type=A，则 Name 是主机名，Value 是该主机名对应的 IP 地址。A 记录提供标准的主机名到 IP 地址映射，例如 `(relay1.bar.foo.com, 145.37.93.126, A)`。
- 若 Type=AAAA，则 Name 是主机名，Value 是 IPv6 地址（A 对应 IPv4，AAAA 对应 IPv6）。
- 若 Type=NS，则 Name 是一个域（如 foo.com），Value 是知道如何获取该域内主机 IP 的权威 DNS 服务器主机名。该记录用于将查询进一步路由到下一跳，例如 `(foo.com, dns.foo.com, NS)`。
- 若 Type=CNAME，则 Value 是别名主机名 Name 的规范主机名（canonical hostname）。它让查询方能拿到主机名的规范名，例如 `(foo.com, relay1.bar.foo.com, CNAME)`。
- 若 Type=MX，则 Value 是别名为 Name 的邮件服务器的规范名。MX 记录允许邮件服务器拥有简单别名，例如 `(foo.com, mail.bar.foo.com, MX)`。
- 若 Type=TXT，则 Value 是一段文本字符串，常用于域名验证、SPF 等策略声明。
- 若 Type=SRV，记录某服务所在的主机与端口（如 `_sip._tcp.example.com`），用于服务发现。
- 若 Type=SOA，是区域的起始授权记录，包含该区域的权威信息（主服务器、管理员邮箱、序列号、刷新/重试/过期/最小 TTL 等）。
- 若 Type=PTR，用于反向解析，Name 是 IP 地址（逆序的 in-addr.arpa 形式），Value 是对应的主机名。

## Attacks on the DNS

针对 DNS 的攻击主要有两类：

- 第一类是 DoS 攻击：通过压垮根服务器、TLD 服务器等关键节点，使 DNS 整体无法工作；
- 第二类是篡改资源记录或伪装成官方 DNS 服务器返回伪造记录，使主机在尝试连接时误连到错误的 IP 地址。

**DNS 劫持**是上述第二类的典型表现：攻击者控制了解析结果，将用户导向钓鱼或恶意站点。

当服务规模变大、需要解析的域名增多时，DNS 调用次数也随之上升。一种常见优化是：客户端在启动阶段对各候选 IP 做测速（「跑马」），之后改用 IP 直连，跳过每次的域名解析开销。在可控环境下也可自建 DNS 以缩短解析链路。

## Links

- [Computer Network](/docs/CS/CN/CN.md)

## References

1. [RFC 1034 - Domain names - concepts and facilities](https://datatracker.ietf.org/doc/html/rfc1034)
2. [RFC 1035 - Domain names - implementation and specification](https://datatracker.ietf.org/doc/html/rfc1035)
3. [RFC 8484 - DNS Queries over HTTPS (DoH)](https://datatracker.ietf.org/doc/html/rfc8484)
4. [为什么 DNS 使用 UDP 协议](https://draven.co/whys-the-design-dns-udp-tcp/)
