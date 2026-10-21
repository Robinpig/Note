## Introduction

SCTP 在客户端与服务端之间提供「关联（associations）」。

SCTP 是面向消息的（message-oriented）。

SCTP 能够在连接端点之间提供多条流（multiple streams），每条流各自拥有可靠的、按序的消息交付。其中一条流上的消息丢失，不会阻塞其他流上的消息交付。这与 TCP 形成对比：TCP 单条字节流中任何一点的丢失都会阻塞该连接上此后所有数据的交付，直到丢失被修复。

SCTP 还提供多归属（multihoming）特性，允许单个 SCTP 端点支持多个 IP 地址。

SCTP 像 TCP 一样面向连接，因此也有关联建立与终止的握手。不过 SCTP 的握手与 TCP 不同，故在此描述。

### Four-Way Handshake

与 TCP 类似，SCTP 关联建立时发生如下过程：

1. 服务端必须准备好接受入站关联。这一准备通常通过调用 socket、bind、listen 完成，称为被动打开（passive open）；
2. 客户端通过调用 connect 或发送消息发起主动打开（active open），隐式打开关联。这会让客户端 SCTP 发送一条 INIT 消息（initialization，初始化），告知服务端客户端的 IP 地址列表、初始序列号、用于标识本关联内所有报文的组合标签（initiation tag）、客户端请求的出口流数，以及客户端能支持的入口流数；
3. 服务端用 INIT-ACK 消息确认客户端的 INIT，其中包含服务端的 IP 地址列表、初始序列号、initiation tag、服务端请求的出口流数、服务端能支持的入口流数，以及一个状态 Cookie（state cookie）。该 Cookie 包含服务端为确认关联有效所需的全部状态，并经数字签名以保证其有效性；
4. 客户端以 COOKIE-ECHO 消息回显服务端的 Cookie，该消息也可在同一报文内携带用户数据；
5. 服务端以 COOKIE-ACK 消息确认 Cookie 正确、关联已建立，该消息同样可携带用户数据。

这一交换最少需要四个报文，因此称为 SCTP 的「四路握手（four-way handshake）」。SCTP 四路握手在许多方面与 TCP 的三次握手相似，区别在于 Cookie 的生成是其不可分割的一部分。

SCTP 使用 Cookie 的四路握手，将一种防御拒绝服务攻击的方法形式化。许多 TCP 实现采用类似方法，最大区别在于：TCP 的 Cookie 状态必须编码进仅有 32 位的初始序列号中；而 SCTP 提供了任意长度的字段，并要求使用密码学安全手段来防止攻击。

### Association Termination

与 TCP 不同，SCTP 不允许「半关闭（half-closed）」的关联。当一端关闭关联时，另一端必须停止发送新数据。关闭请求的接收方先发送队列中已有的数据（若有），然后完成关闭。

SCTP 不像 TCP 那样存在 TIME_WAIT 状态，因为它使用了验证标签（verification tags）。所有块（chunk）都带有在 INIT 块中交换的标签；来自旧连接的块会带着错误的标签到达。因此，SCTP 不是把整个连接保留在 TIME_WAIT，而是把验证标签值保留在 TIME_WAIT。

### State Transition Diagram

## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [TCP](/docs/CS/CN/TCP/TCP.md)

## References

1. [RFC 4960 - Stream Control Transmission Protocol](https://datatracker.ietf.org/doc/html/rfc4960)
