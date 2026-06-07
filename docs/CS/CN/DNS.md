## 简介

DNS 是一个分布式客户端/服务器网络数据库，被 TCP/IP 应用程序用于主机名和 IP 地址之间的映射（反之亦然），
以及提供电子邮件路由信息、服务命名等功能。

> Because accuracy is essential, TCP or some other reliable protocol must be used for AXFR requests.

在绝大多数情况下，DNS 都是使用 UDP 协议进行通信的，DNS 协议在设计之初也推荐我们在进行域名解析时首先使用 UDP

实际上，DNS 不仅使用了 UDP 协议，也使用了 TCP 协议

DNS 查询的类型不止包含 A 记录、CNAME 记录等常见查询，还包含 AXFR 类型的特殊查询，这种特殊查询主要用于 [DNS 区域传输](https://en.wikipedia.org/wiki/DNS_zone_transfer)，它的作用就是在多个命名服务器之间快速迁移记录，由于查询返回的响应比较大，所以会使用 TCP 协议来传输数据包

1. DNS 在设计之初就在区域传输中引入了 TCP 协议，在查询中使用 UDP 协议；
2. 当 DNS 超过了 512 字节的限制，我们第一次在 DNS 协议中明确了『当 DNS 查询被截断时，应该使用 TCP 协议进行重试』这一规范；
3. 随后引入的 EDNS 机制允许我们使用 UDP 最多传输 4096 字节的数据，但是由于 MTU 的限制导致的数据分片以及丢失，使得这一特性不够可靠；
4. 在最近的几年，我们重新规定了 DNS 应该同时支持 UDP 和 TCP 协议，TCP 协议也不再只是重试时的选择

DNS 是一个分层 DNS 服务器实现的分布式数据库，以及一个允许主机查询该分布式数据库的应用层协议。
DNS 服务器通常是运行 Berkeley Internet Name Domain（BIND）软件的 UNIX 机器 [BIND 2016]。
DNS 协议运行在 UDP 之上，使用端口 53。

除了将主机名转换为 IP 地址之外，DNS 还提供其他一些重要服务：
- 主机别名（Host aliasing）
- 邮件服务器别名（Mail server aliasing）
- 负载分配（Load distribution）

DNS解析流程

1. 询问local DNS server，有缓存IP即自动返回
2. local DNS server询问root DNS server，逐步遍历出子DNS server 获取IP，缓存到本地后返回

## 实现

DNS 的一个简单设计是让一个 DNS 服务器包含所有映射。
虽然这种设计简单有吸引力，但它不适合当今拥有庞大（且不断增长）数量主机的互联网。
集中式设计的问题包括：

- 单点故障（A single point of failure）
- 流量压力（Traffic volume）
- 远程集中式数据库，会导致显著的延迟（Distant centralized database）
- 维护困难（Maintenance）

总之，单一 DNS 服务器上的集中式数据库根本无法扩展。因此，DNS 在设计上是分布式的。

一个分层的分布式数据库

- 根 DNS 服务器（Root DNS servers）
- 顶级域服务器（Top-level domain (TLD) servers）
- 权威 DNS 服务器（Authoritative DNS servers）

还有另一种重要类型的 DNS 服务器，称为本地 DNS 服务器。
本地 DNS 服务器严格来说不属于服务器层次结构，但对 DNS 架构至关重要。

### 缓存

DNS 广泛利用 DNS 缓存来提高延迟性能，并减少 DNS 消息在网络中的传播数量。

```shell
cat /etc/hosts

```'

```shell

cat /etc/resolv.conf | grep nameserver

nslookup

# +trace
dig

drill

```

```shell

systemctl restart networking
```

also cache DNS

in JAVA
`InetAddress`

please using singleton to avoid resolving DNS each time

## DNS 记录和消息

实现 DNS 分布式数据库的 DNS 服务器存储资源记录（RR），包括提供主机名到 IP 地址映射的记录。

资源记录是一个四元组，包含以下字段：

```
(Name, Value, Type, TTL)
```

TTL 是资源记录的生存时间；它决定了一个资源何时应从缓存中移除。
在下面给出的示例记录中，我们忽略 TTL 字段。
Name 和 Value 的含义取决于 Type：

- 如果 Type=A，则 Name 是主机名，Value 是该主机名的 IP 地址。
  因此，Type A 记录提供了标准的主机名到 IP 地址的映射。
  例如，(relay1.bar.foo.com, 145.37.93.126, A) 是一条 Type A 记录。
- 如果 Type=AAAA
- 如果 Type=NS，则 Name 是一个域（如 foo.com），Value 是知道如何获取该域中主机 IP 地址的权威 DNS 服务器的主机名。
  此记录用于沿着查询链进一步路由 DNS 查询。
  例如，(foo.com, dns.foo.com, NS) 是一条 Type NS 记录。
- 如果 Type=CNAME，则 Value 是别名主机名 Name 的规范主机名。
  此记录可以为查询主机提供主机名的规范名称。
  例如，(foo.com, relay1.bar.foo.com, CNAME) 是一条 CNAME 记录。
- 如果 Type=MX，则 Value 是具有别名主机名 Name 的邮件服务器的规范名称。
  例如，(foo.com, mail.bar.foo.com, MX) 是一条 MX 记录。
  MX 记录允许邮件服务器的主机名具有简单的别名。
- 如果 Type=TXT
- 如果 Type=SRV
- 如果 Type=SOA
- 如果 Type=PTR

## DNS 攻击

针对 DNS 的攻击主要有两种形式。
- 第一种形式涉及 DoS 攻击，通过使重要的 DNS 服务器（如根或 TLD 服务器）过载来使其无法工作。
- 第二种形式会更改资源记录的内容，或伪装成官方 DNS 服务器但回复虚假资源记录，
  从而导致主机在尝试连接到另一台机器时联系错误的 IP 地址。

DNS劫持

DNS调用次数 服务多了之后域名多需要解析更多域名

客户端程序启动时跑马测试出最快的IP, 之后使用IP直连

自建DNS

## 链接

- [计算机网络](/docs/CS/CN/CN.md)
- [HTTP](/docs/CS/CN/HTTP/HTTP.md)

## 参考文献

1. [RFC 1034 - Domain names - concepts and facilities](https://datatracker.ietf.org/doc/html/rfc1034)
2. [RFC 1035 - Domain names - implementation and specification](https://datatracker.ietf.org/doc/html/rfc1035)
3. [RFC 8484 - DNS Queries over HTTPS (DoH)](https://datatracker.ietf.org/doc/html/rfc8484)
4. [为什么 DNS 使用 UDP 协议](https://draven.co/whys-the-design-dns-udp-tcp/)
