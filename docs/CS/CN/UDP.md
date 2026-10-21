## Introduction

UDP is a simple, datagram-oriented, transport-layer protocol that preserves message boundaries.
It can provide error detection, and it includes the first true end-to-end checksum at the transport layer that we have encountered. 
Generally, each UDP output operation requested by an application produces exactly one UDP datagram, which causes one IP datagram to be sent.

> UDP can be full-duplex.

Some applications are better suited for UDP for the following reasons:

- Finer application-level control over what data is sent, and when.
- No connection establishment.
- No connection state.
- Small packet header overhead.
The TCP segment has 20 bytes of header overhead in every segment, whereas UDP has only 8 bytes of overhead.

### Header Format

UDP 头部只有 4 个字段，每个 16 bit，因此头部（也是 UDP 数据报的最小长度）为 8 字节（RFC 768）。

| 字段 | 位数 | 说明 |
| --- | --- | --- |
| Source Port | 16 | 发送方端口；不使用时可为 0（如仅需单向报文） |
| Destination Port | 16 | 接收端解复用之依据 |
| Length | 16 | 头部加数据的字节数，最小为 8 |
| Checksum | 16 | 覆盖伪首部、UDP 头部与数据 |

> [!NOTE]
> RFC 768 已被 RFC 9868（Transport Options for UDP）更新，但未被废止。

### Checksum

Why UDP provides a checksum in the first place, as many link-layer protocols(including the popular Ethernet protocol) also provide error checking. 
The reason is that there is no guarantee that all the links between source and destination provide error checking; that is, one of the links may use a link-layer protocol that does not provide error checking.
Furthermore, even if segments are correctly transferred across a link, it’s possible that bit errors could be introduced when a segment is stored in a router’s memory. 
Given that neither link-by-link reliability nor in-memory error detection is guaranteed, UDP must provide error detection at the transport layer, on an end-end basis, if the endend data transfer service is to provide error detection. 
This is an example of the celebrated end-end principle in system design, which states that since certain functionality (error detection, in this case) must be implemented on an end-end basis: 
“functions placed at the lower levels may be redundant or of little value when compared to the cost of providing them at the higher level.”

Because IP is supposed to run over just about any layer-2 protocol, it is useful for the transport layer to provide error checking as a safety measure. 
Although UDP provides error checking, it does not do anything to recover from an error. 
Some implementations of UDP simply discard the damaged segment; others pass the damaged segment to the application with a warning.

校验和计算时会在前面拼接一个**伪首部（pseudo-header）**（只参与计算、不随报文传输）：

- IPv4：源地址（32 bit）+ 目的地址（32 bit）+ protocol（8 bit，UDP 为 17）+ UDP 长度（16 bit）。
- IPv6：源地址（128 bit）+ 目的地址（128 bit）+ 上层包长（32 bit）+ zero（24 bit）+ Next Header（8 bit）。

> [!NOTE]
> IPv4 下校验和是**可选**的：全 0 表示发送方未计算校验和（常见于调试或高层不关心差错的场景）。IPv6 下校验和是**必须**的——IPv6 头部本身没有校验和，若收到校验和为 0 的 UDP 数据报必须丢弃并记录错误；无法计算时填 0xFFFF（RFC 8200 §8.1）。

## Congestion Control

UDP **没有内建拥塞控制**：发送速率完全由应用决定，没有任何来自网络的反馈调节。 
不加调速的 UDP 洪泛会伤害同一路径上的其他流量，即使发送者并无恶意（见下文 Attacks）。 
因此基于 UDP 的可靠传输要么自己在应用层实现拥塞控制（如 QUIC 的可测量拥塞控制），要么直接使用自带拥塞控制的协议（如 DCCP，RFC 4340）。 
放大器攻击利用的正是「小请求触发大响应」这类协议（如历史上的 DNS 开放解析器），与 UDP 不调速的特性叠加后危害被进一步放大。





## Attacks Involving UDP and IP Fragmentation

Most attacks involving UDP relate to exhaustion of some shared resource (buffers, link capacity, etc.) or exploitation of bugs in protocol implementations causing system crashes or other undesired behavior. 
Both fall into the broad category of DoS attacks: the successful attacker is able to cause services to be made unavailable to legitimate users. 
The most straightforward DoS attack with UDP is simply generating massive amounts of traffic as fast as possible. 
Because UDP does not regulate its sending traffic rate, this can negatively impact the performance of other applications sharing the same network path. 
This can happen even without malicious intent.

A more sophisticated form of DoS attack frequently associated with UDP is a magnification attack. 
This type of attack generally involves an attacker sending a small amount of traffic that induces other systems to generate much more. 
The classic example is an open DNS resolver: a small query triggers a much larger response, and with a spoofed source address the response is directed at the victim.







## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [Linux UDP](/docs/CS/OS/Linux/net/UDP.md)

## References

1. [RFC 768 - User Datagram Protocol](https://www.rfc-editor.org/info/rfc768)
1. [RFC 4340 - Datagram Congestion Control Protocol (DCCP)](https://www.rfc-editor.org/info/rfc4340)
1. [RFC 8200 - Internet Protocol, Version 6 (IPv6) Specification](https://www.rfc-editor.org/info/rfc8200)
1. [RFC 9868 - Transport Options for UDP](https://www.rfc-editor.org/info/rfc9868)
