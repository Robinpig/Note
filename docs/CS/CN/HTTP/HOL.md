## Introduction

队头阻塞（Head-of-Line blocking，HOL blocking）是计算机网络中的一种性能受限现象：一列数据包被第一个数据包卡住，后面的都走不了。
典型例子包括：输入缓冲的网络交换机、乱序交付，以及 HTTP 流水线中的多个请求。

### Network switches

交换机可以由带缓冲的输入端口、交换矩阵和带缓冲的输出端口组成。
如果输入缓冲区采用先进先出（FIFO）策略，只有最老的数据包可以被转发。
如果最老的数据包因为其目标输出端口正忙而无法转发，后到达的数据包也就无法被转发。
输出端口忙，通常意味着存在输出争用（output contention）。

如果没有队头阻塞，新到达的数据包本可以绕过卡住的最老数据包，被转发到各自的目的地。
队头阻塞会给输入缓冲系统带来性能下降。

这一现象限制了交换机的吞吐。
对 FIFO 输入缓冲区而言，一个「定长信元、目的地均匀分布」的简单模型表明：随着链路数增多，吞吐会被限制到总量的 58.6%。

克服这一限制的一种方法是使用虚拟输出队列（virtual output queues）。

只有带输入缓冲的交换机才可能发生队头阻塞。
只要内部带宽足够，就不需要输入缓冲：所有缓冲都在输出侧完成，队头阻塞也就无从发生。
这种无输入缓冲架构在中小型以太网交换机中很常见。

### Out-of-order delivery

乱序交付指按序编号的数据包没有按顺序到达。其原因可能是数据包走了不同路径，也可能是数据包被丢弃后重发。
队头阻塞会显著加剧数据包乱序。

在有大量对端的易丢包网络上可靠地广播消息是个难题。
原子广播算法虽然解决了中心化服务器的单点故障问题，却引入了队头阻塞问题。
Bimodal Multicast 是一种使用 gossip 协议的随机化算法，它允许部分消息乱序接收，从而避免了队头阻塞。

### HTTP

HTTP/1.1 中队头阻塞的一种表现形式是：浏览器允许的并行请求数用完时，后续请求必须等待前一个完成才能发出。
这主要是因为该协议本质上是纯文本的，且资源分片之间没有分隔符。
HTTP/1.1 引入了[「流水线」（Pipelining）](/docs/CS/CN/HTTP/HTTP.md?id=pipelining)特性，允许客户端在同一条 TCP 连接上连续发送多个 HTTP 请求。
但 HTTP/1.1 仍然要求响应按序返回，所以它并没有真正解决队头阻塞问题，到今天也没有被广泛采用。

正因如此，HTTP/2 的目标非常明确：**通过解决队头阻塞问题，让我们得以回到单条 TCP 连接**。
HTTP/2 通过请求**多路复用（multiplexing）**来应对这一问题，消除了应用层的队头阻塞，但传输层（TCP）的队头阻塞依然存在。
换句话说：我们希望实现资源分片的正确多路复用。
这在 HTTP/1.1 中做不到，因为没有办法分辨一个分片属于哪个资源、在哪里结束、另一个又从哪里开始。
HTTP/2 的解法相当优雅：在资源分片前加上小的控制消息，称为**帧（frame）**。
通过给每条消息「分帧」，HTTP/2 比 HTTP/1.1 灵活得多：它允许多个资源的分片在单条 TCP 连接上交错发送，实现多路复用。

HTTP/3 使用 [QUIC](/docs/CS/CN/HTTP/QUIC.md) 取代 TCP，从而消除了传输层的队头阻塞。

TCP 数据包在传输途中丢失时，接收端在服务器重传该包之前无法确认后续收到的包。
由于 TCP 按设计并不感知 HTTP 这类上层协议，单个丢包就会阻塞整条流上所有在途的 HTTP 请求，直到丢失的数据被重传。
换句话说，两个层之间的视角存在错位：HTTP/2 看到的是多条相互独立的资源字节流，而 TCP 看到的只是一条不透明的字节流。

> QUIC 消除队头阻塞，对实际 Web 性能的提升可能并没有那么大。

### TLS HOL blocking

TLS 协议为 HTTP 等应用层协议提供加密（及其他能力）。
它的做法是把从 HTTP 收到的数据包装进 TLS 记录（record），后者在概念上类似 HTTP/2 帧或 TCP 数据包。
例如，记录开头有一小段元数据标明记录的长度。这条记录及其中的 HTTP 内容随后被加密，交给 TCP 传输。

但关键在于：TLS 只能整条解密一条记录，因此会出现一种 TLS 队头阻塞。
假设一条 TLS 记录分散在 11 个 TCP 数据包里，而最后一个 TCP 包丢失了。
由于 TLS 记录不完整，它无法被解密，只能卡住等待最后一个 TCP 包重传。
注意，在这个特定场景下并不存在 TCP 队头阻塞：第 11 号包之后没有数据包在等待重传。

虽然这是高度特殊的场景，实践中未必常发生，但设计 QUIC 协议时仍考虑到了它。
在 QUIC 中，目标是彻底消除各种形式的队头阻塞（或尽可能消除），连这种边缘情况也要去掉。
这正是 QUIC 虽然集成了 TLS，却总是按数据包逐个加密、不直接使用 TLS 记录的原因之一。
如前所见，这种方式效率更低、更耗 CPU，也是目前 QUIC 实现可能仍比 TCP 慢的主要原因之一。

> See [Optimizing TLS Record Size & Buffering Latency](https://www.igvita.com/2013/10/24/optimizing-tls-record-size-and-buffering-latency/)

## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [HTTP](/docs/CS/CN/HTTP/HTTP.md)
- [QUIC](/docs/CS/CN/HTTP/QUIC.md)

## References

1. [Head-of-line blocking - Wiki](https://en.wikipedia.org/wiki/Head-of-line_blocking)
2. [Making the Web Faster with HTTP 2.0 HTTP continues to evolve](https://queue.acm.org/detail.cfm?id=2555617)
3. [Head-of-Line Blocking in QUIC and HTTP/3: The Details](https://github.com/rmarx/holblocking-blogpost#sec_tls)
