## Introduction

DNS is a distributed client/server networked database that is used by TCP/IP applications to map between host names and IP addresses (and vice versa), 
to provide electronic mail routing information, service naming, and other capabilities.

在绝大多数情况下，DNS 都是使用 UDP 协议进行通信的，DNS 协议在设计之初也推荐我们在进行域名解析时首先使用 UDP

实际上，DNS 不仅使用了 UDP 协议，也使用了 TCP 协议

DNS 查询的类型不止包含 A 记录、CNAME 记录等常见查询，还包含 AXFR 类型的特殊查询，这种特殊查询主要用于 [DNS 区域传输](https://en.wikipedia.org/wiki/DNS_zone_transfer)，它的作用就是在多个命名服务器之间快速迁移记录，由于查询返回的响应比较大，所以会使用 TCP 协议来传输数据包

1. DNS 在设计之初就在区域传输中引入了 TCP 协议，在查询中使用 UDP 协议；
2. 当 DNS 超过了 512 字节的限制，我们第一次在 DNS 协议中明确了『当 DNS 查询被截断时，应该使用 TCP 协议进行重试』这一规范；
3. 随后引入的 EDNS 机制允许我们使用 UDP 最多传输 4096 字节的数据，但是由于 MTU 的限制导致的数据分片以及丢失，使得这一特性不够可靠；
4. 在最近的几年，我们重新规定了 DNS 应该同时支持 UDP 和 TCP 协议，TCP 协议也不再只是重试时的选择

The DNS is a distributed database implemented in a hierarchy of DNS servers, and an application-layer protocol that allows hosts to query the distributed database. 
The DNS servers are often UNIX machines running the Berkeley Internet Name Domain (BIND) software [BIND 2016]. 
The DNS protocol runs over UDP and uses port 53.


DNS provides a few other important services in addition to translating hostnames to IP addresses:
- Host aliasing
- Mail server aliasing
- Load distribution

DNS解析流程

1. 询问local DNS server，有缓存IP即自动返回
2. local DNS server询问root DNS server，逐步遍历出子DNS server 获取IP，缓存到本地后返回





## Implementation

A simple design for DNS would have one DNS server that contains all the mappings.
Although the simplicity of this design is attractive, it is inappropriate for today’s Internet, with its vast (and growing) number of hosts. 
The problems with a centralized design include:

- A single point of failure.
- Traffic volume.
- Distant centralized database. This can lead to significant delays.
- Maintenance.

In summary, a centralized database in a single DNS server simply doesn’t scale. Consequently, the DNS is distributed by design.

A Distributed, Hierarchical Database

- Root DNS servers
- Top-level domain (TLD) servers
- Authoritative DNS servers

There is another important type of DNS server called the local DNS server. 
A local DNS server does not strictly belong to the hierarchy of servers but is nevertheless central to the DNS architecture.




### Caching

DNS extensively exploits DNS caching in order to improve the delay performance and to reduce the number of DNS messages ricocheting around the Internet.

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

## DNS Records and Messages

The DNS servers that together implement the DNS distributed database store resource records (RRs), including RRs that provide hostname-to-IP address mappings.

A resource record is a four-tuple that contains the following fields:

```
(Name, Value, Type, TTL)
```

TTL is the time to live of the resource record; it determines when a resource should be removed from a cache. 
In the example records given below, we ignore the TTL field. 
The meaning of Name and Value depend on Type :

- If Type=A , then Name is a hostname and Value is the IP address for the hostname. 
  Thus, a Type A record provides the standard hostname-to-IP address mapping. 
  As an example,(relay1.bar.foo.com, 145.37.93.126, A) is a Type A record.
- If Type=AAAA  
- If Type=NS , then Name is a domain (such as foo.com ) and Value is the hostname of an authoritative DNS server that knows how to obtain the IP addresses for hosts in the domain. 
  This record is used to route DNS queries further along in the query chain. 
  As an example, (foo.com, dns.foo.com, NS) is a Type NS record.
- If Type=CNAME , then Value is a canonical hostname for the alias hostname Name. 
  This record can provide querying hosts the canonical name for a hostname. 
  As an example, (foo.com, relay1.bar.foo.com, CNAME) is a CNAME record.
- If Type=MX , then Value is the canonical name of a mail server that has an alias hostname Name.
  As an example, (foo.com, mail.bar.foo.com, MX) is an MX record. 
  MX records allow the hostnames of mail servers to have simple aliases.
- If Type=TXT
- If Type=SRV
- If Type=SOA
- If Type=PTR
  


## Attacks on the DNS

There have been two main forms of attacks against the DNS. 
- The first form involves a DoS attack where the DNS is rendered inoperative because of overloading of important DNS servers, such as the root or TLD servers. 
- The second form alters the contents of resource records or masquerades as an official DNS server but responds with bogus resource records, 
  thereby causing hosts to contact the incorrect IP address when attempting to connect to another machine.


DNS劫持

DNS调用次数 服务多了之后域名多需要解析更多域名

客户端程序启动时跑马测试出最快的IP, 之后使用IP直连

自建DNS



## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [HTTP](/docs/CS/CN/HTTP/HTTP.md)

## References

1. [RFC 1034 - Domain names - concepts and facilities](https://datatracker.ietf.org/doc/html/rfc1034)
1. [RFC 1035 - Domain names - implementation and specification](https://datatracker.ietf.org/doc/html/rfc1035)
1. [RFC 8484 - DNS Queries over HTTPS (DoH)](https://datatracker.ietf.org/doc/html/rfc8484)