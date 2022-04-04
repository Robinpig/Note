## Introduction

DNS is a distributed client/server networked database that is used by TCP/IP applications to map between host names and IP addresses (and vice versa), 
to provide electronic mail routing information, service naming, and other capabilities.

The DNS is (1) a distributed database implemented in a hierarchy of DNS servers, and (2) an application-layer protocol that allows hosts to query the distributed database. 
The DNS servers are often UNIX machines running the Berkeley Internet Name Domain (BIND) software [BIND 2016]. 
The DNS protocol runs over UDP and uses port 53.


DNS provides a few other important services in addition to translating hostnames to IP addresses:
- Host aliasing
- Mail server aliasing
- Load distribution

DNS解析流程

1. 询问local DNS server，有缓存IP即自动返回
2. local DNS server询问root DNS server，逐步遍历出子DNS server 获取IP，缓存到本地后返回



建立在UDP之上


域名解析记录
域名与IP绑定时添加的记录

A
Address

AAAA
主机名或域名指向IPv6


CNAME
Canonical Name(Alias) for another domain

MX
Mail Exchange

NS
子域名指定域名服务器解析

TXT
做验证记录时使用 可选

SRV
添加服务记录服务器服务记录

SOA
起始授权机构记录 记录NS记录中的主服务器

PTR
A记录的逆向 IP解析为域名

URL转发
* 显性 转发地址 修改地址栏
* 隐性 转发地址 不修改地址栏


## Caching

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
- [HTTP](/docs/CS/CN/HTTP.md)

## References

1. [RFC 8484 - DNS Queries over HTTPS (DoH)](https://datatracker.ietf.org/doc/html/rfc8484)