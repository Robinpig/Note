## 简介

SMTP 是互联网电子邮件的主要应用层协议。
它利用 [TCP](/docs/CS/CN/TCP/TCP.md) 的可靠数据传输服务，**将邮件从发送方的邮件服务器传输到接收方的邮件服务器**。

## 与 HTTP 的对比

现在让我们简要对比 SMTP 和 [HTTP](/docs/CS/CN/HTTP/HTTP.md)。

两种协议都用于将文件从一台主机传输到另一台主机：
HTTP 将文件（也称为对象）从 Web 服务器传输到 Web 客户端（通常是浏览器）；
SMTP 将文件（即电子邮件消息）从一个邮件服务器传输到另一个邮件服务器。
在传输文件时，持久 HTTP 和 SMTP 都使用持久连接。

然而，两者之间存在重要差异。

首先，HTTP 主要是一种拉取协议——有人将信息加载到 Web 服务器上，用户使用 HTTP 在方便时从服务器拉取信息。
具体来说，TCP 连接由想要接收文件的机器发起。
另一方面，SMTP 主要是一种推送协议——发送邮件服务器将文件推送到接收邮件服务器。
具体来说，TCP 连接由想要发送文件的机器发起。

第二个差异，我们之前提到过，SMTP 要求每条消息（包括每条消息的正文）采用 7 位 ASCII 格式。
如果消息包含非 7 位 ASCII 字符（例如带重音的法语字符）或包含二进制数据（如图像文件），则消息必须编码为 7 位 ASCII。
HTTP 数据没有此限制。

第三个重要差异涉及由文本和图像（以及可能的其他媒体类型）组成的文档的处理方式。
HTTP 将每个对象封装在自己的 HTTP 响应消息中。
SMTP 将所有消息的对象放在一条消息中。

## POP3

user proxy

## IMAP

user proxy

## 基于 Web 的电子邮件

使用此服务时，用户代理是一个普通的 Web 浏览器，用户通过 HTTP 与其远程邮箱通信。
当收件人（如 Bob）想要访问其邮箱中的邮件时，电子邮件消息通过 HTTP 协议（而非 POP3 或 IMAP 协议）从 Bob 的邮件服务器发送到 Bob 的浏览器。
当发件人（如 Alice）想要发送电子邮件消息时，电子邮件消息通过 HTTP 从她的浏览器发送到她的邮件服务器（而非通过 SMTP）。
然而，Alice 的邮件服务器仍然使用 SMTP 向其他邮件服务器发送和接收消息。

## 链接

- [计算机网络](/docs/CS/CN/CN.md)

## 参考文献

1. [RFC 5321 - Simple Mail Transfer Protocol](https://www.rfc-editor.org/info/rfc5321)
2. [RFC 1939 - Post Office Protocol - Version 3](https://www.rfc-editor.org/info/rfc1939)
3. [RFC 3501 - INTERNET MESSAGE ACCESS PROTOCOL - VERSION 4rev1](https://www.rfc-editor.org/info/rfc3501)
