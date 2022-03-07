## Introduction


`Domain Name System`



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

```shell

cat /etc/resolv.conf

nslookup

# +trace
dig


```

also cache DNS

in JAVA
`InetAddress`

please using singleton to avoid resolving DNS each time





DNS劫持

DNS调用次数 服务多了之后域名多需要解析更多域名

客户端程序启动时跑马测试出最快的IP, 之后使用IP直连

自建DNS

Cache

```shell
cat /etc/hosts

```

## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [HTTP](/docs/CS/CN/HTTP.md)