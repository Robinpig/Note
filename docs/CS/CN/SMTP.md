## Introduction

SMTP（Simple Mail Transfer Protocol，简单邮件传输协议）是 Internet 电子邮件的主要应用层协议。它利用 [TCP](/docs/CS/CN/TCP/TCP.md) 的可靠数据传输服务，**将邮件从发送方邮件服务器传送到接收方邮件服务器**。

## Comparison with HTTP

下面简要比较 SMTP 与 [HTTP](/docs/CS/CN/HTTP/HTTP.md)。

两者都用于把文件从一台主机传送到另一台：HTTP 把文件（也称对象）从 Web 服务器传送到 Web 客户端（通常是浏览器）；SMTP 把文件（即电子邮件消息）从一台邮件服务器传送到另一台邮件服务器。传输文件时，持久 HTTP 与 SMTP 都使用持久连接。

但二者有重要区别：

- 第一，HTTP 主要是拉（pull）协议——有人把信息加载到 Web 服务器上，用户用 HTTP 在方便时从服务器拉取信息；具体说，TCP 连接由想要接收文件的机器发起。而 SMTP 主要是推（push）协议——发送方邮件服务器把文件推送给接收方邮件服务器；TCP 连接由想要发送文件的机器发起。
- 第二，SMTP 要求每条消息（包括消息体）都采用 7 位 ASCII 格式。如果消息含有非 7 位 ASCII 字符（如带重音的法文字符）或二进制数据（如图像文件），则必须先编码为 7 位 ASCII；HTTP 数据没有这一限制。
- 第三，关于如何处理由文本与图像（及可能的其他媒体类型）组成的文档：HTTP 把每个对象封装在各自的 HTTP 响应消息中；SMTP 则把消息的所有对象放进一条消息里。

## POP3

POP3（Post Office Protocol v3）是邮件访问协议，用户代理（user agent）通过它从邮件服务器下载邮件。

## IMAP

IMAP（Internet Message Access Protocol）同样是邮件访问协议，相比 POP3 支持在服务器上管理邮件文件夹与状态。

## Web-Based E-Mail

在此类服务中，用户代理就是普通的 Web 浏览器，用户通过 HTTP 与其远程邮箱通信。当收件人（如 Bob）想访问邮箱中的消息时，该邮件消息是从 Bob 的邮件服务器经 HTTP（而非 POP3 或 IMAP）发往 Bob 的浏览器；当发件人（如 Alice）想发送邮件时，邮件从她的浏览器经 HTTP（而非 SMTP）发往她的邮件服务器。不过，Alice 的邮件服务器仍使用 SMTP 向其他邮件服务器发送、并从其他邮件服务器接收消息。

## Links

- [Computer Network](/docs/CS/CN/CN.md)

## References

1. [RFC 5321 - Simple Mail Transfer Protocol](https://www.rfc-editor.org/info/rfc5321)
2. [RFC 1939 - Post Office Protocol - Version 3](https://www.rfc-editor.org/info/rfc1939)
3. [RFC 3501 - INTERNET MESSAGE ACCESS PROTOCOL - VERSION 4rev1](https://www.rfc-editor.org/info/rfc3501)
